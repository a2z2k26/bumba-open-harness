/**
 * registry-migration.js
 * Migration module for converting legacy registries to v4.0.0 schema
 *
 * Handles migration from:
 * - componentRegistry.json (v3.0.0) -> registries/components.json (v4.0.0)
 * - tokens/index.json (v1.0.0) -> registries/tokens.json (v4.0.0)
 * - layoutManifest.json (v1.0.0) -> registries/layouts.json (v4.0.0)
 *
 * @module registry-migration
 */

const fs = require('fs').promises;
const path = require('path');

const { RegistryManager, getRegistryManager } = require('./registry-manager');

// Legacy file paths (relative to .design)
const LEGACY_PATHS = {
  components: 'componentRegistry.json',
  tokens: 'tokens/index.json',
  layouts: 'layoutManifest.json',
  storyHashes: 'storyHashRegistry.json',
  idMappings: 'id-mappings.json'
};

/**
 * RegistryMigration - Handles migration from legacy registries to v4.0.0
 *
 * @class RegistryMigration
 */
class RegistryMigration {
  /**
   * Creates a new RegistryMigration instance
   *
   * @param {RegistryManager} registryManager - Initialized RegistryManager
   */
  constructor(registryManager) {
    this.registryManager = registryManager;
    this.designRoot = registryManager.designRoot;

    // Migration status tracking
    this.status = {
      started: null,
      completed: null,
      components: { migrated: 0, skipped: 0, errors: [] },
      tokens: { migrated: 0, skipped: 0, errors: [] },
      layouts: { migrated: 0, skipped: 0, errors: [] },
      idMappings: { imported: 0 },
      totalErrors: 0
    };

    // Progress callback
    this.onProgress = null;
  }

  /**
   * Sets a progress callback function
   *
   * @param {Function} callback - Function(phase, progress, message)
   */
  setProgressCallback(callback) {
    this.onProgress = callback;
  }

  /**
   * Reports progress to callback
   */
  reportProgress(phase, progress, message) {
    if (this.onProgress) {
      this.onProgress(phase, progress, message);
    }
  }

  // ==========================================================================
  // DETECTION
  // ==========================================================================

  /**
   * Detects which legacy registries exist
   *
   * @returns {Promise<Object>} Detection results { components, tokens, layouts, storyHashes, idMappings }
   */
  async detectLegacyRegistries() {
    const results = {};

    for (const [type, relativePath] of Object.entries(LEGACY_PATHS)) {
      const fullPath = path.join(this.designRoot, relativePath);

      try {
        await fs.access(fullPath);
        const stat = await fs.stat(fullPath);
        const content = await fs.readFile(fullPath, 'utf8');
        const data = JSON.parse(content);

        results[type] = {
          exists: true,
          path: fullPath,
          size: stat.size,
          version: data.version || 'unknown',
          schemaVersion: data.metadata?.schemaVersion || data.schemaVersion || data.version || 'unknown'
        };

        // Add counts
        if (type === 'components' && data.components) {
          results[type].count = Object.keys(data.components).length;
        } else if (type === 'tokens' && data.categories) {
          let tokenCount = 0;
          for (const cat of Object.values(data.categories)) {
            tokenCount += cat.tokens?.length || 0;
          }
          results[type].count = tokenCount;
        } else if (type === 'layouts' && data.layouts) {
          results[type].count = data.layouts.length;
        }
      } catch {
        results[type] = { exists: false };
      }
    }

    return results;
  }

  // ==========================================================================
  // BACKUP & ROLLBACK
  // ==========================================================================

  /**
   * Creates a timestamped backup of all legacy files
   *
   * @returns {Promise<string>} Backup directory path
   */
  async createBackup() {
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const backupDir = path.join(this.designRoot, `backup-${timestamp}`);

    await fs.mkdir(backupDir, { recursive: true });

    for (const [type, relativePath] of Object.entries(LEGACY_PATHS)) {
      const sourcePath = path.join(this.designRoot, relativePath);

      try {
        await fs.access(sourcePath);
        const destPath = path.join(backupDir, relativePath);
        await fs.mkdir(path.dirname(destPath), { recursive: true });
        await fs.copyFile(sourcePath, destPath);
      } catch {
        // File doesn't exist, skip
      }
    }

    // Also backup registries directory if it exists
    const registriesDir = path.join(this.designRoot, 'registries');
    try {
      await fs.access(registriesDir);
      const files = await fs.readdir(registriesDir);
      const backupRegistriesDir = path.join(backupDir, 'registries');
      await fs.mkdir(backupRegistriesDir, { recursive: true });

      for (const file of files) {
        await fs.copyFile(
          path.join(registriesDir, file),
          path.join(backupRegistriesDir, file)
        );
      }
    } catch {
      // Registries dir doesn't exist
    }

    // Backup registry-index.json
    const indexPath = path.join(this.designRoot, 'registry-index.json');
    try {
      await fs.access(indexPath);
      await fs.copyFile(indexPath, path.join(backupDir, 'registry-index.json'));
    } catch {
      // Index doesn't exist
    }

    return backupDir;
  }

  /**
   * Restores from a backup directory
   *
   * @param {string} backupDir - Backup directory path
   * @returns {Promise<void>}
   */
  async rollback(backupDir) {
    // Verify backup exists
    try {
      await fs.access(backupDir);
    } catch {
      throw new Error(`Backup directory not found: ${backupDir}`);
    }

    // Restore legacy files
    for (const [type, relativePath] of Object.entries(LEGACY_PATHS)) {
      const backupPath = path.join(backupDir, relativePath);
      const destPath = path.join(this.designRoot, relativePath);

      try {
        await fs.access(backupPath);
        await fs.mkdir(path.dirname(destPath), { recursive: true });
        await fs.copyFile(backupPath, destPath);
      } catch {
        // File wasn't backed up
      }
    }

    // Restore registries directory
    const backupRegistriesDir = path.join(backupDir, 'registries');
    try {
      await fs.access(backupRegistriesDir);
      const registriesDir = path.join(this.designRoot, 'registries');

      // Clear existing
      try {
        await fs.rm(registriesDir, { recursive: true, force: true });
      } catch {}

      await fs.mkdir(registriesDir, { recursive: true });
      const files = await fs.readdir(backupRegistriesDir);

      for (const file of files) {
        await fs.copyFile(
          path.join(backupRegistriesDir, file),
          path.join(registriesDir, file)
        );
      }
    } catch {
      // No registries to restore
    }

    // Restore registry-index.json
    const backupIndexPath = path.join(backupDir, 'registry-index.json');
    const indexPath = path.join(this.designRoot, 'registry-index.json');
    try {
      await fs.access(backupIndexPath);
      await fs.copyFile(backupIndexPath, indexPath);
    } catch {
      // No index to restore
    }
  }

  /**
   * Lists available backups
   *
   * @returns {Promise<Array>} Array of backup info objects
   */
  async listBackups() {
    const backups = [];

    try {
      const entries = await fs.readdir(this.designRoot, { withFileTypes: true });

      for (const entry of entries) {
        if (entry.isDirectory() && entry.name.startsWith('backup-')) {
          const backupPath = path.join(this.designRoot, entry.name);
          const stat = await fs.stat(backupPath);

          // Extract timestamp from name
          const timestamp = entry.name.replace('backup-', '').replace(/-/g, ':');

          backups.push({
            name: entry.name,
            path: backupPath,
            timestamp: timestamp,
            created: stat.birthtime
          });
        }
      }
    } catch {
      // Directory doesn't exist or not readable
    }

    return backups.sort((a, b) => b.created - a.created);
  }

  // ==========================================================================
  // MAIN MIGRATION
  // ==========================================================================

  /**
   * Runs the full migration from legacy to v4.0.0
   *
   * @param {Object} options - Migration options
   * @param {boolean} options.dryRun - If true, don't actually modify files
   * @param {boolean} options.skipBackup - If true, skip creating backup
   * @returns {Promise<Object>} Migration results
   */
  async migrateFromLegacy(options = {}) {
    const { dryRun = false, skipBackup = false } = options;

    this.status.started = new Date().toISOString();
    let backupDir = null;

    try {
      // Create backup
      if (!skipBackup && !dryRun) {
        this.reportProgress('backup', 0, 'Creating backup...');
        backupDir = await this.createBackup();
        this.reportProgress('backup', 100, `Backup created: ${backupDir}`);
      }

      // Detect legacy registries
      this.reportProgress('detect', 0, 'Detecting legacy registries...');
      const detected = await this.detectLegacyRegistries();
      this.reportProgress('detect', 100, 'Detection complete');

      // Migrate tokens first (so we can resolve token references in components/layouts)
      if (detected.tokens?.exists) {
        this.reportProgress('tokens', 0, 'Migrating tokens...');
        await this.migrateTokens(detected.tokens.path, dryRun);
        this.reportProgress('tokens', 100, `Migrated ${this.status.tokens.migrated} tokens`);
      }

      // Migrate components
      if (detected.components?.exists) {
        this.reportProgress('components', 0, 'Migrating components...');
        await this.migrateComponents(detected.components.path, dryRun);
        this.reportProgress('components', 100, `Migrated ${this.status.components.migrated} components`);
      }

      // Migrate layouts
      if (detected.layouts?.exists) {
        this.reportProgress('layouts', 0, 'Migrating layouts...');
        await this.migrateLayouts(detected.layouts.path, dryRun);
        this.reportProgress('layouts', 100, `Migrated ${this.status.layouts.migrated} layouts`);
      }

      // Import ID mappings if they exist
      if (detected.idMappings?.exists) {
        this.reportProgress('idMappings', 0, 'Importing ID mappings...');
        await this.importIdMappings(detected.idMappings.path, dryRun);
        this.reportProgress('idMappings', 100, 'ID mappings imported');
      }

      // Rebuild dependency graph
      if (!dryRun) {
        this.reportProgress('finalize', 0, 'Rebuilding dependency graph...');
        await this.registryManager.rebuildDependencyGraph();
        this.reportProgress('finalize', 100, 'Migration complete');
      }

      this.status.completed = new Date().toISOString();

      return {
        success: true,
        dryRun,
        backupDir,
        status: this.status
      };

    } catch (error) {
      this.status.totalErrors++;

      return {
        success: false,
        dryRun,
        backupDir,
        status: this.status,
        error: error.message
      };
    }
  }

  // ==========================================================================
  // COMPONENT MIGRATION
  // ==========================================================================

  /**
   * Migrates components from legacy format
   *
   * @param {string} legacyPath - Path to legacy componentRegistry.json
   * @param {boolean} dryRun - Don't modify files if true
   */
  async migrateComponents(legacyPath, dryRun = false) {
    const content = await fs.readFile(legacyPath, 'utf8');
    const legacyData = JSON.parse(content);

    // Handle both object and array formats
    const components = legacyData.components
      ? Object.values(legacyData.components)
      : (Array.isArray(legacyData) ? legacyData : []);

    for (const oldEntry of components) {
      try {
        const newEntry = this.convertLegacyComponent(oldEntry);

        if (!dryRun) {
          // Check if already exists
          const existing = await this.registryManager.findByNodeId(oldEntry.source?.nodeId);

          if (existing) {
            await this.registryManager.updateEntry('components', existing.id, newEntry);
            this.status.components.skipped++;
          } else {
            await this.registryManager.addEntry('components', newEntry);
            this.status.components.migrated++;
          }
        } else {
          this.status.components.migrated++;
        }
      } catch (error) {
        this.status.components.errors.push({
          entry: oldEntry.name || oldEntry.id,
          error: error.message
        });
        this.status.totalErrors++;
      }
    }
  }

  /**
   * Converts a legacy component entry to v4.0.0 format
   *
   * @param {Object} old - Legacy component entry
   * @returns {Object} New format entry
   */
  convertLegacyComponent(old) {
    const now = new Date().toISOString();

    // Flatten token dependencies to canonical IDs where possible
    const tokenDeps = this.flattenTokenDependencies(old.tokenDependencies);

    return {
      name: old.name,
      displayName: old.name,
      category: old.category || this.inferCategory(old.name, old.type),
      source: {
        type: old.source?.type || 'figma-plugin',
        fileKey: old.source?.fileKey || null,
        nodeId: old.source?.nodeId || this.extractNodeIdFromLegacyId(old.id),
        styleId: old.source?.styleId || null,
        extractedAt: old.source?.extractedAt || now,
        rawDataPath: old.source?.rawDataPath || old.rawDataPath || null
      },
      transformation: {
        state: old.transformation?.state || 'raw',
        framework: old.transformation?.framework || null,
        codePath: old.transformation?.codePath || null,
        storyPath: old.transformation?.storyPath || null,
        codeHash: old.transformation?.codeHash || null,
        transformedAt: old.transformation?.transformedAt || null,
        version: old.transformation?.version || 1
      },
      dependencies: {
        tokens: tokenDeps,
        components: []
      },
      sync: {
        lastFigmaSync: old.syncMetadata?.lastFigmaSync || old.source?.extractedAt || now,
        figmaModifiedAt: old.syncMetadata?.figmaModifiedAt || null,
        localModifiedAt: old.syncMetadata?.localModifiedAt || null,
        userModified: old.syncMetadata?.userModified || false,
        syncCount: old.syncMetadata?.syncCount || 1
      },
      // Preserve legacy data for reference
      _legacyData: {
        originalId: old.id,
        type: old.type,
        tokenDependencies: old.tokenDependencies
      }
    };
  }

  /**
   * Flattens token dependencies from legacy format
   * Converts named references to canonical IDs where possible
   *
   * @param {Object} tokenDeps - Legacy token dependencies
   * @returns {Array} Array of token canonical IDs or names
   */
  flattenTokenDependencies(tokenDeps) {
    if (!tokenDeps) return [];

    const flattened = [];

    // Process each category
    for (const [category, tokens] of Object.entries(tokenDeps)) {
      if (Array.isArray(tokens)) {
        for (const token of tokens) {
          // If it's a string (token name), try to resolve it
          if (typeof token === 'string') {
            flattened.push(token);
          }
        }
      }
    }

    return [...new Set(flattened)]; // Dedupe
  }

  /**
   * Extracts nodeId from legacy ID format
   *
   * @param {string} legacyId - Legacy canonical ID
   * @returns {string|null} Node ID
   */
  extractNodeIdFromLegacyId(legacyId) {
    if (!legacyId) return null;

    // Format: figma-plugin-name-123-456 -> 123:456
    const parts = legacyId.split('-');
    if (parts.length >= 2) {
      const lastTwo = parts.slice(-2);
      if (/^\d+$/.test(lastTwo[0]) && /^\d+$/.test(lastTwo[1])) {
        return `${lastTwo[0]}:${lastTwo[1]}`;
      }
    }

    return null;
  }

  /**
   * Infers category from component name
   *
   * @param {string} name - Component name
   * @param {string} type - Component type
   * @returns {string} Inferred category
   */
  inferCategory(name, type) {
    const lowerName = (name || '').toLowerCase();

    if (lowerName.includes('button')) return 'buttons';
    if (lowerName.includes('input') || lowerName.includes('text')) return 'inputs';
    if (lowerName.includes('card')) return 'cards';
    if (lowerName.includes('alert') || lowerName.includes('toast')) return 'feedback';
    if (lowerName.includes('modal') || lowerName.includes('dialog')) return 'overlays';
    if (lowerName.includes('nav') || lowerName.includes('menu')) return 'navigation';
    if (lowerName.includes('icon')) return 'icons';
    if (lowerName.includes('form')) return 'forms';

    return 'ui-elements';
  }

  // ==========================================================================
  // TOKEN MIGRATION
  // ==========================================================================

  /**
   * Migrates tokens from legacy format
   *
   * @param {string} legacyPath - Path to legacy tokens/index.json
   * @param {boolean} dryRun - Don't modify files if true
   */
  async migrateTokens(legacyPath, dryRun = false) {
    const content = await fs.readFile(legacyPath, 'utf8');
    const legacyData = JSON.parse(content);

    // Process each category
    for (const [category, categoryData] of Object.entries(legacyData.categories || {})) {
      const tokens = categoryData.tokens || [];

      for (const oldToken of tokens) {
        try {
          const newEntry = this.convertLegacyToken(oldToken, category);

          if (!dryRun) {
            // Check if already exists by styleId
            const existing = await this.registryManager.findByStyleId(oldToken.source?.styleId);

            if (existing) {
              await this.registryManager.updateEntry('tokens', existing.id, newEntry);
              this.status.tokens.skipped++;
            } else {
              await this.registryManager.addEntry('tokens', newEntry);
              this.status.tokens.migrated++;
            }
          } else {
            this.status.tokens.migrated++;
          }
        } catch (error) {
          this.status.tokens.errors.push({
            entry: oldToken.name,
            error: error.message
          });
          this.status.totalErrors++;
        }
      }
    }
  }

  /**
   * Converts a legacy token entry to v4.0.0 format
   *
   * @param {Object} old - Legacy token entry
   * @param {string} category - Token category
   * @returns {Object} New format entry
   */
  convertLegacyToken(old, category) {
    const now = new Date().toISOString();

    return {
      name: old.name,
      displayName: old.source?.styleName || old.name,
      category: category,
      value: old.value,
      source: {
        type: old.source?.type || 'figma-plugin',
        fileKey: old.source?.fileKey || null,
        nodeId: null,
        styleId: old.source?.styleId || null,
        extractedAt: old.source?.extractedAt || now,
        rawDataPath: old.rawPath || null
      },
      transformation: {
        state: 'raw',
        framework: null,
        codePath: null,
        storyPath: null,
        codeHash: null,
        transformedAt: null,
        version: 1
      },
      dependencies: {
        tokens: [],
        components: []
      },
      sync: {
        lastFigmaSync: old.source?.extractedAt || now,
        figmaModifiedAt: null,
        localModifiedAt: null,
        userModified: false,
        syncCount: 1
      },
      // Token-specific fields
      cssVariable: this.generateCssVariableName(old.name, category),
      // Preserve legacy data
      _legacyData: {
        styleName: old.source?.styleName
      }
    };
  }

  /**
   * Generates CSS variable name from token name
   *
   * @param {string} name - Token name
   * @param {string} category - Token category
   * @returns {string} CSS variable name
   */
  generateCssVariableName(name, category) {
    const prefix = category === 'colors' ? 'color' :
                   category === 'typography' ? 'font' :
                   category === 'spacing' ? 'spacing' :
                   category === 'effects' ? 'effect' :
                   category === 'borderRadius' ? 'radius' : category;

    return `--${prefix}-${name.replace(/[^a-zA-Z0-9]/g, '-').toLowerCase()}`;
  }

  // ==========================================================================
  // LAYOUT MIGRATION
  // ==========================================================================

  /**
   * Migrates layouts from legacy format
   *
   * @param {string} legacyPath - Path to legacy layoutManifest.json
   * @param {boolean} dryRun - Don't modify files if true
   */
  async migrateLayouts(legacyPath, dryRun = false) {
    const content = await fs.readFile(legacyPath, 'utf8');
    const legacyData = JSON.parse(content);

    const layouts = legacyData.layouts || [];

    for (const oldLayout of layouts) {
      try {
        const newEntry = await this.convertLegacyLayout(oldLayout);

        if (!dryRun) {
          // Check if already exists
          const existing = await this.registryManager.findByNodeId(oldLayout.source?.nodeId || oldLayout.id);

          if (existing) {
            await this.registryManager.updateEntry('layouts', existing.id, newEntry);
            this.status.layouts.skipped++;
          } else {
            await this.registryManager.addEntry('layouts', newEntry);
            this.status.layouts.migrated++;
          }
        } else {
          this.status.layouts.migrated++;
        }
      } catch (error) {
        this.status.layouts.errors.push({
          entry: oldLayout.name || oldLayout.id,
          error: error.message
        });
        this.status.totalErrors++;
      }
    }
  }

  /**
   * Converts a legacy layout entry to v4.0.0 format
   *
   * @param {Object} old - Legacy layout entry
   * @returns {Promise<Object>} New format entry
   */
  async convertLegacyLayout(old) {
    const now = new Date().toISOString();

    // Resolve component dependencies to canonical IDs
    const resolvedDeps = await this.resolveLayoutDependencies(
      old.componentDependencies || []
    );

    return {
      name: old.name,
      displayName: old.name,
      category: 'layouts',
      source: {
        type: old.source?.type || 'figma-plugin',
        fileKey: old.source?.fileKey || null,
        nodeId: old.source?.nodeId || old.id,
        styleId: old.source?.styleId || null,
        extractedAt: old.source?.extractedAt || now,
        rawDataPath: old.rawPath || null
      },
      transformation: {
        state: 'raw',
        framework: old.framework || 'react',
        codePath: old.path || null,
        storyPath: null,
        codeHash: null,
        transformedAt: null,
        version: 1
      },
      dependencies: {
        tokens: this.flattenTokenDependencies(old.tokenDependencies),
        components: resolvedDeps.resolved
      },
      sync: {
        lastFigmaSync: old.lastSynced || now,
        figmaModifiedAt: null,
        localModifiedAt: null,
        userModified: false,
        syncCount: 1
      },
      // Layout-specific fields
      dimensions: old.dimensions || null,
      screenshot: old.screenshot || null,
      figmaUrl: old.figmaUrl || null,
      behavior: old.behavior || null,
      canGenerate: old.canGenerate !== false,
      // Track unresolved dependencies
      dependencyStatus: {
        resolved: resolvedDeps.resolved,
        missing: resolvedDeps.missing,
        outdated: old.dependencyStatus?.outdated || []
      },
      // Preserve legacy data
      _legacyData: {
        originalId: old.id,
        rawComponentDependencies: old.componentDependencies,
        errors: old.errors
      }
    };
  }

  /**
   * Resolves layout component dependencies to canonical IDs
   *
   * @param {Array} rawDeps - Raw dependency list (node IDs or names)
   * @returns {Promise<Object>} { resolved: [], missing: [] }
   */
  async resolveLayoutDependencies(rawDeps) {
    const resolved = [];
    const missing = [];

    for (const rawId of rawDeps) {
      // Try to find by nodeId
      const byNodeId = await this.registryManager.findByNodeId(rawId);
      if (byNodeId) {
        resolved.push(byNodeId.id);
        continue;
      }

      // Try to find by name
      const byName = await this.registryManager.findByName(rawId, 'components');
      if (byName.length > 0) {
        resolved.push(byName[0].id);
        continue;
      }

      // Not found
      missing.push(rawId);
    }

    return { resolved, missing };
  }

  // ==========================================================================
  // ID MAPPINGS IMPORT
  // ==========================================================================

  /**
   * Imports existing ID mappings into the registry
   *
   * @param {string} legacyPath - Path to id-mappings.json
   * @param {boolean} dryRun - Don't modify files if true
   */
  async importIdMappings(legacyPath, dryRun = false) {
    try {
      const content = await fs.readFile(legacyPath, 'utf8');
      const mappings = JSON.parse(content);

      // Import into sourceMapping
      if (!dryRun && mappings) {
        for (const [figmaId, canonicalId] of Object.entries(mappings)) {
          if (!this.registryManager.index.sourceMapping[figmaId]) {
            this.registryManager.index.sourceMapping[figmaId] = canonicalId;
            this.status.idMappings.imported++;
          }
        }

        await this.registryManager.saveIndex();
      }
    } catch {
      // ID mappings file might not exist or be invalid
    }
  }

  // ==========================================================================
  // REPORT GENERATION
  // ==========================================================================

  /**
   * Generates a migration report
   *
   * @returns {string} Formatted report
   */
  generateReport() {
    const lines = [
      '==========================================',
      '  Registry Migration Report',
      '==========================================',
      '',
      `Started:   ${this.status.started}`,
      `Completed: ${this.status.completed}`,
      '',
      '--- Components ---',
      `  Migrated: ${this.status.components.migrated}`,
      `  Skipped:  ${this.status.components.skipped}`,
      `  Errors:   ${this.status.components.errors.length}`,
      '',
      '--- Tokens ---',
      `  Migrated: ${this.status.tokens.migrated}`,
      `  Skipped:  ${this.status.tokens.skipped}`,
      `  Errors:   ${this.status.tokens.errors.length}`,
      '',
      '--- Layouts ---',
      `  Migrated: ${this.status.layouts.migrated}`,
      `  Skipped:  ${this.status.layouts.skipped}`,
      `  Errors:   ${this.status.layouts.errors.length}`,
      '',
      '--- ID Mappings ---',
      `  Imported: ${this.status.idMappings.imported}`,
      '',
      `Total Errors: ${this.status.totalErrors}`,
      ''
    ];

    // Add error details if any
    if (this.status.totalErrors > 0) {
      lines.push('--- Error Details ---');

      for (const err of this.status.components.errors) {
        lines.push(`  Component "${err.entry}": ${err.error}`);
      }
      for (const err of this.status.tokens.errors) {
        lines.push(`  Token "${err.entry}": ${err.error}`);
      }
      for (const err of this.status.layouts.errors) {
        lines.push(`  Layout "${err.entry}": ${err.error}`);
      }

      lines.push('');
    }

    lines.push('==========================================');

    return lines.join('\n');
  }

  /**
   * Saves migration report to file
   *
   * @returns {Promise<string>} Report file path
   */
  async saveReport() {
    const report = this.generateReport();
    const reportPath = path.join(
      this.designRoot,
      `migration-report-${new Date().toISOString().replace(/[:.]/g, '-')}.txt`
    );

    await fs.writeFile(reportPath, report);
    return reportPath;
  }
}

// ==========================================================================
// EXPORTS
// ==========================================================================

module.exports = RegistryMigration;
module.exports.RegistryMigration = RegistryMigration;
module.exports.LEGACY_PATHS = LEGACY_PATHS;

/**
 * Factory function to create migration instance
 *
 * @param {string} designRoot - Path to .design directory
 * @returns {Promise<RegistryMigration>} Migration instance
 */
module.exports.createMigration = async function(designRoot) {
  const manager = await getRegistryManager(designRoot);
  return new RegistryMigration(manager);
};
