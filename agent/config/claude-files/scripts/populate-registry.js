#!/usr/bin/env node
/**
 * Populate Component Registry
 *
 * Scans .design/components/ for all Figma-extracted JSON files
 * and populates .design/componentRegistry.json with canonical names.
 *
 * Process:
 * 1. Read all JSON files from .design/components/
 * 2. Extract Figma name from each component
 * 3. Convert to canonical PascalCase name
 * 4. Check for naming collisions
 * 5. Add to registry with source metadata
 * 6. Write updated registry
 *
 * Usage:
 *   node scripts/populate-registry.js [--dry-run] [--force]
 *
 * Options:
 *   --dry-run    Show what would be added without writing registry
 *   --force      Overwrite existing registry (backup created)
 */

const fs = require('fs');
const path = require('path');
const NamingNormalizer = require('../shared-modules/design-system/naming-normalizer');

class RegistryPopulator {
  constructor(projectPath, options = {}) {
    this.projectPath = projectPath;
    this.options = {
      dryRun: options.dryRun || false,
      force: options.force || false
    };

    this.normalizer = new NamingNormalizer();
    this.componentsDir = path.join(projectPath, '.design', 'components');
    this.registryPath = path.join(projectPath, '.design', 'componentRegistry.json');

    // Tracking
    this.stats = {
      total: 0,
      added: 0,
      skipped: 0,
      errors: 0,
      collisions: []
    };
  }

  /**
   * Main execution method
   */
  async populate() {
    console.log('=== Component Registry Population ===\n');
    console.log(`Project: ${this.projectPath}`);
    console.log(`Components: ${this.componentsDir}`);
    console.log(`Registry: ${this.registryPath}\n`);

    if (this.options.dryRun) {
      console.log('🔍 DRY RUN MODE - No changes will be written\n');
    }

    // Step 1: Verify components directory exists
    if (!fs.existsSync(this.componentsDir)) {
      console.error(`❌ Error: Components directory not found: ${this.componentsDir}`);
      console.error('Please ensure Figma components have been extracted.\n');
      process.exit(1);
    }

    // Step 2: Load or create registry
    let registry = this._loadOrCreateRegistry();

    // Step 3: Scan components directory
    console.log('📂 Scanning components directory...');
    const jsonFiles = this._scanComponentsDirectory();
    console.log(`   Found ${jsonFiles.length} JSON files\n`);

    if (jsonFiles.length === 0) {
      console.log('⚠️  No components found. Nothing to do.\n');
      return;
    }

    this.stats.total = jsonFiles.length;

    // Step 4: Process each component
    console.log('🔄 Processing components...\n');
    const canonicalNameMap = new Map();  // Track collisions

    for (const file of jsonFiles) {
      try {
        const result = this._processComponent(file, canonicalNameMap);

        if (result.collision) {
          this.stats.collisions.push(result.collision);
          this.stats.errors++;
        } else if (result.component) {
          // Add to registry (use plugin ID as key for v3.0.0 compatibility)
          const pluginId = result.pluginId;
          const canonicalName = result.component.canonicalName;

          registry.components[pluginId] = result.component;
          this.stats.added++;

          console.log(`   ✓ ${result.component.figmaName} → ${canonicalName} (${pluginId})`);
        } else {
          this.stats.skipped++;
        }
      } catch (error) {
        console.error(`   ❌ Error processing ${file}: ${error.message}`);
        this.stats.errors++;
      }
    }

    console.log('');

    // Step 5: Report collisions
    if (this.stats.collisions.length > 0) {
      console.error('❌ NAMING COLLISIONS DETECTED:\n');
      for (const collision of this.stats.collisions) {
        console.error(`   Canonical: "${collision.canonical}"`);
        console.error(`   Figma 1:   "${collision.figma1}" (${collision.file1})`);
        console.error(`   Figma 2:   "${collision.figma2}" (${collision.file2})`);
        console.error('');
      }
      console.error('Please rename components in Figma to avoid collisions.\n');
      process.exit(1);
    }

    // Step 6: Write registry (unless dry run)
    if (!this.options.dryRun) {
      this._writeRegistry(registry);
    }

    // Step 7: Report results
    this._reportResults();
  }

  /**
   * Load existing registry or create new one
   */
  _loadOrCreateRegistry() {
    if (fs.existsSync(this.registryPath)) {
      if (!this.options.force) {
        console.log('⚠️  Registry already exists. Use --force to overwrite.\n');
        console.log('Existing registry will be merged with new components.\n');
      } else {
        // Backup existing registry
        const backupPath = this.registryPath + '.backup.' + Date.now();
        fs.copyFileSync(this.registryPath, backupPath);
        console.log(`📦 Backed up existing registry to: ${backupPath}\n`);
      }

      const content = fs.readFileSync(this.registryPath, 'utf8');
      return JSON.parse(content);
    }

    // Create new registry structure
    return {
      version: '2.0.0',
      generated: new Date().toISOString(),
      components: {}
    };
  }

  /**
   * Scan components directory for JSON files
   */
  _scanComponentsDirectory() {
    const files = fs.readdirSync(this.componentsDir);

    return files
      .filter(file => {
        // Include only .json files, but exclude registry.json itself
        return file.endsWith('.json') && file !== 'registry.json';
      })
      .map(file => path.join(this.componentsDir, file))
      .sort();
  }

  /**
   * Process a single component file
   *
   * @param {string} filePath - Absolute path to component JSON file
   * @param {Map} canonicalNameMap - Track canonical names for collision detection
   * @returns {Object} { component, collision }
   */
  _processComponent(filePath, canonicalNameMap) {
    const fileName = path.basename(filePath);

    // Read component JSON
    let componentData;
    try {
      const content = fs.readFileSync(filePath, 'utf8');
      componentData = JSON.parse(content);
    } catch (error) {
      throw new Error(`Failed to read/parse JSON: ${error.message}`);
    }

    // Extract Figma name
    const figmaName = componentData.name;
    if (!figmaName) {
      throw new Error('Component has no name field');
    }

    // Extract Figma ID and node ID
    const figmaId = componentData.id || null;
    const nodeId = figmaId; // Preserve original node ID

    // Convert to canonical name
    let canonicalName;
    try {
      canonicalName = this.normalizer.figmaToCanonical(figmaName);
    } catch (error) {
      throw new Error(`Failed to create canonical name: ${error.message}`);
    }

    // Check for collision
    if (canonicalNameMap.has(canonicalName)) {
      const existingFile = canonicalNameMap.get(canonicalName);

      return {
        collision: {
          canonical: canonicalName,
          figma1: existingFile.figmaName,
          file1: existingFile.fileName,
          figma2: figmaName,
          file2: fileName
        }
      };
    }

    // Track canonical name
    canonicalNameMap.set(canonicalName, {
      figmaName,
      fileName
    });

    // Generate plugin-compatible ID (v3.0.0 format)
    // Format: figma-plugin-{name-slug}-{nodeId}
    const nameSlug = figmaName.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '');
    const pluginId = `figma-plugin-${nameSlug}-${nodeId}`;

    // Build hybrid registry entry (compatible with v3.0.0 + new canonical naming)
    const component = {
      // v3.0.0 fields (backward compatibility with plugin)
      id: pluginId,
      name: figmaName,
      type: componentData.type || 'COMPONENT',
      category: componentData.category || 'uncategorized',

      // New canonical naming fields
      figmaId: figmaId,
      figmaName: figmaName,
      canonicalName: canonicalName,

      source: {
        type: 'figma-plugin',
        fileKey: null,
        nodeId: nodeId,
        rawDataPath: `.design/components/${fileName}`,
        extractedAt: componentData.extractedAt || new Date().toISOString()
      },

      // v3.0.0 single-framework transformation (for plugin compatibility)
      transformation: {
        state: null,
        framework: null,
        transformedAt: null,
        codePath: null,
        storyPath: null
      },

      // New multi-framework transformations
      transformations: {
        react: null,
        vue: null,
        angular: null,
        flutter: null,
        'react-native': null,
        svelte: null,
        swiftui: null,
        'jetpack-compose': null,
        'web-components': null
      },

      // Plugin sync metadata
      syncMetadata: {
        lastFigmaSync: null,
        syncCount: 0
      },

      // Token dependencies (for plugin)
      tokenDependencies: componentData.tokenDependencies || {}
    };

    return { component, pluginId };
  }

  /**
   * Write registry to disk
   */
  _writeRegistry(registry) {
    console.log('💾 Writing registry...');

    // Update metadata
    registry.version = '2.0.0';
    registry.generated = new Date().toISOString();
    registry.totalComponents = Object.keys(registry.components).length;

    // Ensure directory exists
    const registryDir = path.dirname(this.registryPath);
    if (!fs.existsSync(registryDir)) {
      fs.mkdirSync(registryDir, { recursive: true });
    }

    // Write with pretty formatting
    fs.writeFileSync(
      this.registryPath,
      JSON.stringify(registry, null, 2),
      'utf8'
    );

    console.log(`   ✓ Registry written: ${this.registryPath}\n`);
  }

  /**
   * Report final results
   */
  _reportResults() {
    console.log('=== ✅ Registry Population Complete ===\n');
    console.log(`Total components scanned: ${this.stats.total}`);
    console.log(`Successfully added: ${this.stats.added}`);
    console.log(`Skipped: ${this.stats.skipped}`);
    console.log(`Errors: ${this.stats.errors}`);
    console.log('');

    if (this.options.dryRun) {
      console.log('🔍 DRY RUN - No changes were written');
      console.log('Run without --dry-run to populate the registry.\n');
    } else {
      console.log('Next Steps:');
      console.log('  - Review registry: .design/componentRegistry.json');
      console.log('  - Run tests: node tests/test-naming.js');
      console.log('  - Transform components: /design-transform-react ComponentName');
      console.log('');
    }
  }
}

// CLI support
if (require.main === module) {
  const args = process.argv.slice(2);
  const dryRun = args.includes('--dry-run');
  const force = args.includes('--force');

  const populator = new RegistryPopulator(process.cwd(), {
    dryRun,
    force
  });

  populator.populate()
    .then(() => {
      process.exit(0);
    })
    .catch(error => {
      console.error('❌ Unexpected error:', error);
      console.error(error.stack);
      process.exit(1);
    });
}

module.exports = RegistryPopulator;
