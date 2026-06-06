/**
 * Source Migration Module
 * Migrate components between extraction sources
 */

const fs = require('fs');
const path = require('path');

class SourceMigration {
  constructor(projectRoot) {
    this.projectRoot = projectRoot;
    this.registryPath = path.join(projectRoot, '.design');
  }

  /**
   * Migrate a component from one source to another
   * @param {string} componentId - Component ID to migrate
   * @param {object} options - Migration options
   * @returns {object} - Migration result
   */
  async migrate(componentId, options) {
    const {
      fromSource,
      toSource,
      newSourceConfig = {},
      preserveCustomizations = true,
      preserveTokenMappings = true,
      updateStories = true,
      dryRun = false
    } = options;

    const result = {
      componentId,
      fromSource,
      toSource,
      started: new Date().toISOString(),
      preserved: {},
      updated: {},
      warnings: [],
      success: false
    };

    try {
      // Load existing component
      const registryFile = path.join(this.registryPath, 'components', 'registry.json');
      const registry = JSON.parse(fs.readFileSync(registryFile, 'utf-8'));
      const component = registry.components[componentId];

      if (!component) {
        throw new Error(`Component not found: ${componentId}`);
      }

      // Verify source matches
      if (fromSource && component.source?.type !== fromSource) {
        throw new Error(`Component source is ${component.source?.type}, not ${fromSource}`);
      }

      // Collect customizations to preserve
      const customizations = this.collectCustomizations(component);
      result.preserved = customizations;

      // Extract from new source
      console.log(`[migrate] Extracting ${component.name} from ${toSource}...`);
      const newData = await this.extractFromSource(toSource, newSourceConfig, component.name);

      if (!newData) {
        throw new Error(`Failed to extract from ${toSource}`);
      }

      // Merge customizations
      const mergedComponent = this.mergeCustomizations(newData, customizations, {
        preserveCustomizations,
        preserveTokenMappings
      });

      // Update source metadata
      mergedComponent.source = {
        type: toSource,
        extractedAt: new Date().toISOString(),
        migratedFrom: {
          type: component.source?.type,
          migratedAt: new Date().toISOString()
        },
        ...newSourceConfig
      };

      // Add migration history
      mergedComponent.migrationHistory = [
        ...(component.migrationHistory || []),
        {
          from: component.source?.type,
          to: toSource,
          at: new Date().toISOString(),
          preserved: Object.keys(customizations)
        }
      ];

      result.updated = {
        source: mergedComponent.source,
        structure: !!newData.structure,
        tokenDependencies: !!newData.tokenDependencies,
        variants: !!newData.variants
      };

      if (!dryRun) {
        // Update registry
        registry.components[componentId] = mergedComponent;
        fs.writeFileSync(registryFile, JSON.stringify(registry, null, 2));

        // Update raw source file
        if (newData.rawData) {
          const rawDir = path.join(this.registryPath, 'components', 'raw');
          if (!fs.existsSync(rawDir)) {
            fs.mkdirSync(rawDir, { recursive: true });
          }
          const rawPath = path.join(rawDir, `${componentId}.json`);
          fs.writeFileSync(rawPath, JSON.stringify(newData.rawData, null, 2));
          mergedComponent.paths = mergedComponent.paths || {};
          mergedComponent.paths.rawSource = `components/raw/${componentId}.json`;
        }

        // Re-transform
        console.log(`[migrate] Re-transforming ${component.name}...`);
        await this.retransform(componentId);

        // Update stories if requested
        if (updateStories && component.paths?.storyOutput) {
          console.log(`[migrate] Updating stories...`);
          await this.updateStories(componentId, mergedComponent);
        }
      }

      result.success = true;
      result.completed = new Date().toISOString();

    } catch (err) {
      result.error = err.message;
      result.success = false;
    }

    return result;
  }

  /**
   * Collect customizations from existing component
   */
  collectCustomizations(component) {
    return {
      // Custom props not from source
      customProps: component.customProps || {},

      // Local style overrides
      styleOverrides: component.styleOverrides || {},

      // Custom token mappings
      tokenMappings: component.tokenMappings || {},

      // Custom interactive states
      customStates: component.interactiveStates?.custom || {},

      // Manual documentation
      documentation: component.documentation || {},

      // Tags and categories
      tags: component.tags || [],
      category: component.category,

      // Output paths (preserve structure)
      paths: component.paths
    };
  }

  /**
   * Extract component data from specified source
   */
  async extractFromSource(sourceType, config, componentName) {
    switch (sourceType) {
      case 'figma-mcp':
        return this.extractFromFigmaMCP(config, componentName);
      case 'figma-plugin':
        return this.extractFromFigmaPlugin(config, componentName);
      case 'shadcn':
        return this.extractFromShadCN(config, componentName);
      case 'nlp-prompt':
        return this.extractFromNLP(config, componentName);
      case 'manual':
        return this.extractFromManual(config, componentName);
      default:
        throw new Error(`Unknown source type: ${sourceType}`);
    }
  }

  async extractFromFigmaMCP(config, componentName) {
    // Load Figma MCP skill
    const skillPath = path.join(this.projectRoot, '.claude', 'wrappers', 'extract-figma-mcp.js');
    if (!fs.existsSync(skillPath)) {
      throw new Error('Figma MCP skill not installed');
    }

    const skill = require(skillPath);
    return skill.extract({
      url: config.url,
      nodeId: config.nodeId,
      componentName
    });
  }

  async extractFromFigmaPlugin(config, componentName) {
    // Load Figma Plugin skill
    const skillPath = path.join(this.projectRoot, '.claude', 'wrappers', 'extract-figma-plugin.js');
    if (!fs.existsSync(skillPath)) {
      throw new Error('Figma Plugin skill not installed');
    }

    const skill = require(skillPath);
    return skill.extract({
      fileKey: config.fileKey,
      nodeId: config.nodeId,
      componentName
    });
  }

  async extractFromShadCN(config, componentName) {
    const skillPath = path.join(this.projectRoot, '.claude', 'wrappers', 'extract-shadcn.js');
    if (!fs.existsSync(skillPath)) {
      throw new Error('ShadCN skill not installed');
    }

    const skill = require(skillPath);
    return skill.extract({
      component: config.component || componentName.toLowerCase(),
      registry: config.registry || '@shadcn'
    });
  }

  async extractFromNLP(config, componentName) {
    const skillPath = path.join(this.projectRoot, '.claude', 'wrappers', 'extract-nlp.js');
    if (!fs.existsSync(skillPath)) {
      throw new Error('NLP skill not installed');
    }

    const skill = require(skillPath);
    return skill.extract({
      description: config.description,
      componentName
    });
  }

  async extractFromManual(config, componentName) {
    const skillPath = path.join(this.projectRoot, '.claude', 'wrappers', 'extract-manual.js');
    if (!fs.existsSync(skillPath)) {
      throw new Error('Manual skill not installed');
    }

    const skill = require(skillPath);
    return skill.extract({
      input: config.input,
      template: config.template,
      componentName
    });
  }

  /**
   * Merge customizations into new data
   */
  mergeCustomizations(newData, customizations, options) {
    const merged = { ...newData };

    if (options.preserveCustomizations) {
      // Preserve custom props
      if (customizations.customProps && Object.keys(customizations.customProps).length > 0) {
        merged.customProps = customizations.customProps;
      }

      // Preserve style overrides
      if (customizations.styleOverrides && Object.keys(customizations.styleOverrides).length > 0) {
        merged.styleOverrides = customizations.styleOverrides;
      }

      // Preserve documentation
      if (customizations.documentation && Object.keys(customizations.documentation).length > 0) {
        merged.documentation = customizations.documentation;
      }

      // Preserve tags
      if (customizations.tags && customizations.tags.length > 0) {
        merged.tags = customizations.tags;
      }

      // Preserve category
      if (customizations.category) {
        merged.category = customizations.category;
      }

      // Preserve paths
      if (customizations.paths) {
        merged.paths = customizations.paths;
      }
    }

    if (options.preserveTokenMappings) {
      // Merge token mappings
      if (customizations.tokenMappings && Object.keys(customizations.tokenMappings).length > 0) {
        merged.tokenMappings = {
          ...(newData.tokenMappings || {}),
          ...customizations.tokenMappings
        };
      }
    }

    return merged;
  }

  /**
   * Re-transform component after migration
   */
  async retransform(componentId) {
    try {
      const { BatchTransformer } = require('./batch-transform');
      const transformer = new BatchTransformer(this.projectRoot);
      await transformer.transform([componentId], { framework: 'react' });
    } catch (err) {
      console.warn(`[migrate] Re-transform failed: ${err.message}`);
    }
  }

  /**
   * Update stories after migration
   */
  async updateStories(componentId, component) {
    const storyGeneratorPath = path.join(
      this.projectRoot,
      'design-feature',
      'packages',
      '@design-bridge',
      'server',
      'story-generator.js'
    );

    if (fs.existsSync(storyGeneratorPath)) {
      try {
        const generator = require(storyGeneratorPath);
        await generator.generateStory(component, component.paths?.storyOutput);
      } catch (err) {
        console.warn(`[migrate] Story update failed: ${err.message}`);
      }
    }
  }

  /**
   * Get migration history for a component
   */
  getMigrationHistory(componentId) {
    const registryFile = path.join(this.registryPath, 'components', 'registry.json');

    if (!fs.existsSync(registryFile)) {
      return { error: 'Registry not found' };
    }

    const registry = JSON.parse(fs.readFileSync(registryFile, 'utf-8'));
    const component = registry.components[componentId];

    if (!component) {
      return { error: 'Component not found' };
    }

    return {
      componentId,
      componentName: component.name,
      currentSource: component.source?.type,
      history: component.migrationHistory || []
    };
  }

  /**
   * List all migrations across all components
   */
  listAllMigrations() {
    const registryFile = path.join(this.registryPath, 'components', 'registry.json');

    if (!fs.existsSync(registryFile)) {
      return { error: 'Registry not found', migrations: [] };
    }

    const registry = JSON.parse(fs.readFileSync(registryFile, 'utf-8'));
    const migrations = [];

    for (const [id, component] of Object.entries(registry.components || {})) {
      if (component.migrationHistory && component.migrationHistory.length > 0) {
        migrations.push({
          componentId: id,
          componentName: component.name,
          currentSource: component.source?.type,
          migrations: component.migrationHistory
        });
      }
    }

    return { migrations, total: migrations.length };
  }

  /**
   * Preview migration without executing
   * @param {string} componentId - Component ID
   * @param {object} options - Migration options
   * @returns {object} - Preview of what would change
   */
  async preview(componentId, options) {
    return this.migrate(componentId, { ...options, dryRun: true });
  }

  /**
   * Generate migration report
   */
  generateReport(result) {
    const lines = [
      '=== Source Migration Report ===',
      '',
      `Component: ${result.componentId}`,
      `From: ${result.fromSource || 'auto-detected'}`,
      `To: ${result.toSource}`,
      `Status: ${result.success ? 'SUCCESS' : 'FAILED'}`,
      ''
    ];

    if (result.preserved && Object.keys(result.preserved).length > 0) {
      lines.push('Preserved Customizations:');
      for (const [key, value] of Object.entries(result.preserved)) {
        if (value && (Array.isArray(value) ? value.length > 0 : Object.keys(value).length > 0)) {
          lines.push(`  - ${key}`);
        }
      }
      lines.push('');
    }

    if (result.updated) {
      lines.push('Updated:');
      for (const [key, updated] of Object.entries(result.updated)) {
        if (updated) {
          lines.push(`  - ${key}`);
        }
      }
      lines.push('');
    }

    if (result.warnings && result.warnings.length > 0) {
      lines.push('Warnings:');
      for (const warning of result.warnings) {
        lines.push(`  ! ${warning}`);
      }
      lines.push('');
    }

    if (result.error) {
      lines.push(`Error: ${result.error}`);
    }

    return lines.join('\n');
  }
}

// CLI entry point
async function migrateCLI(args) {
  const projectRoot = process.cwd();
  const migration = new SourceMigration(projectRoot);

  if (args.history) {
    // Show migration history
    if (args.componentId) {
      const history = migration.getMigrationHistory(args.componentId);
      console.log(JSON.stringify(history, null, 2));
    } else {
      const all = migration.listAllMigrations();
      console.log(JSON.stringify(all, null, 2));
    }
    return;
  }

  if (!args.componentId || !args.toSource) {
    console.log('Usage: migrate --componentId=<id> --toSource=<source> [options]');
    console.log('');
    console.log('Options:');
    console.log('  --componentId    Component ID to migrate');
    console.log('  --toSource       Target source (figma-mcp, figma-plugin, shadcn, nlp-prompt, manual)');
    console.log('  --fromSource     Expected current source (optional, validates)');
    console.log('  --preview        Preview without executing');
    console.log('  --no-preserve    Do not preserve customizations');
    console.log('  --no-tokens      Do not preserve token mappings');
    console.log('  --no-stories     Do not update stories');
    console.log('  --history        Show migration history');
    console.log('  --config=<json>  Source-specific config (JSON string)');
    return;
  }

  const options = {
    toSource: args.toSource,
    fromSource: args.fromSource,
    newSourceConfig: args.config ? JSON.parse(args.config) : {},
    preserveCustomizations: args.preserve !== false,
    preserveTokenMappings: args.tokens !== false,
    updateStories: args.stories !== false,
    dryRun: args.preview || false
  };

  const result = await migration.migrate(args.componentId, options);
  console.log(migration.generateReport(result));
  return result;
}

module.exports = { SourceMigration, migrateCLI };
