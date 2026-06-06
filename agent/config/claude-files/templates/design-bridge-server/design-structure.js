/**
 * Design Structure Manager
 *
 * Manages the .design/ directory structure and ensures all required
 * manifests and directories exist for the progressive context pipeline:
 *
 * Pipeline: JSON → Screenshot → HTML → Validated Screenshot → Framework Code
 *
 * v4.0.0 Directory Structure:
 * .design/
 * ├── config.json                    # Project configuration
 * ├── registry-index.json           # v4.0.0 Registry coordinator (NEW)
 * ├── registries/                   # v4.0.0 Unified registries (NEW)
 * │   ├── components.json           # Component registry v4.0.0
 * │   ├── tokens.json               # Token registry v4.0.0
 * │   └── layouts.json              # Layout registry v4.0.0
 * ├── componentRegistry.json         # Legacy component inventory (deprecated)
 * ├── layoutManifest.json           # Legacy layout inventory (deprecated)
 * ├── tokens/                        # Design tokens
 * │   ├── index.json                # Legacy token registry
 * │   ├── colors.json
 * │   ├── typography.json
 * │   ├── spacing.json
 * │   └── ...
 * ├── components/                    # Extracted component definitions (JSON)
 * │   └── <ComponentName>/
 * │       └── component.json
 * ├── layouts/                       # Layout pipeline artifacts
 * │   └── <layout-name>/
 * │       ├── layout.json           # Stage 1: Extracted structure
 * │       ├── screenshot.png        # Stage 2: Visual reference
 * │       ├── reference.html        # Stage 3: HTML for validation
 * │       ├── pass1-browser.png     # Stage 4a: Validation screenshots
 * │       ├── pass2-browser.png
 * │       ├── reference-validated.png # Stage 4b: Final validated screenshot
 * │       └── validation-report.json  # Stage 4c: Validation results
 * ├── extracted-code/               # Generated framework code
 * │   └── <framework>/
 * │       ├── components/
 * │       │   ├── index.ts          # Barrel export
 * │       │   └── <ComponentName>/
 * │       ├── tokens/
 * │       │   └── index.ts          # Barrel export
 * │       └── layouts/
 * │           ├── index.ts          # Barrel export
 * │           └── <LayoutName>.tsx
 * └── source/                       # Internal cache (can be cleaned)
 *
 * @version 2.0.0 - Added v4.0.0 registry structure support
 */

const fs = require('fs');
const path = require('path');

// Lazy-load RegistryManager to avoid circular dependencies
let _registryManagerModule = null;
function getRegistryManagerModule() {
  if (!_registryManagerModule) {
    _registryManagerModule = require('./registry-manager');
  }
  return _registryManagerModule;
}

/**
 * Design directory structure definition
 */
const STRUCTURE = {
  directories: [
    '.design',
    '.design/registries',        // v4.0.0 unified registries directory
    '.design/tokens',
    '.design/components',
    '.design/layouts',
    '.design/extracted-code',
    '.design/source'
  ],

  // Framework-specific subdirectories created on demand
  frameworkDirs: (framework) => [
    `.design/extracted-code/${framework}`,
    `.design/extracted-code/${framework}/components`,
    `.design/extracted-code/${framework}/tokens`,
    `.design/extracted-code/${framework}/layouts`
  ],

  // Legacy manifests (v3.0.0 and earlier)
  manifests: {
    config: '.design/config.json',
    componentRegistry: '.design/componentRegistry.json',
    layoutManifest: '.design/layoutManifest.json',
    tokenIndex: '.design/tokens/index.json'
  },

  // v4.0.0 registry files
  v4Registries: {
    index: '.design/registry-index.json',
    components: '.design/registries/components.json',
    tokens: '.design/registries/tokens.json',
    layouts: '.design/registries/layouts.json'
  }
};

/**
 * Default manifest templates
 */
const DEFAULT_MANIFESTS = {
  config: (options = {}) => ({
    version: '1.0.0',
    createdAt: new Date().toISOString(),
    project: {
      name: options.projectName || path.basename(process.cwd()),
      framework: options.framework || 'react',
      typescript: options.typescript !== false,
      styling: options.styling || 'css-modules'
    },
    tokens: {
      source: options.tokenSource || 'figma',
      categories: ['colors', 'typography', 'spacing', 'effects', 'borderRadius']
    },
    pipeline: {
      autoValidation: false,
      maxValidationPasses: 3,
      openPreviewOnGenerate: true
    },
    output: {
      components: `.design/extracted-code/${options.framework || 'react'}/components`,
      tokens: `.design/extracted-code/${options.framework || 'react'}/tokens`,
      layouts: `.design/extracted-code/${options.framework || 'react'}/layouts`
    }
  }),

  componentRegistry: () => ({
    version: '3.0.0',
    lastUpdated: new Date().toISOString(),
    components: {},
    metadata: {
      schemaVersion: '3.0.0',
      totalComponents: 0,
      sources: {
        figma: 0,
        shadcn: 0,
        nlp: 0,
        manual: 0
      }
    }
  }),

  layoutManifest: () => ({
    version: '1.0.0',
    lastUpdated: new Date().toISOString(),
    layouts: [],
    pipelineStages: {
      1: 'extracted',      // layout.json exists
      2: 'screenshot',     // screenshot.png exists
      3: 'html-generated', // reference.html exists
      4: 'validated',      // validation-report.json with status=validated
      5: 'code-generated'  // framework code exists
    },
    metadata: {
      totalLayouts: 0,
      byStage: {
        extracted: 0,
        screenshot: 0,
        'html-generated': 0,
        validated: 0,
        'code-generated': 0
      }
    }
  }),

  tokenIndex: () => ({
    version: '1.0.0',
    lastUpdated: new Date().toISOString(),
    categories: {
      colors: { file: 'colors.json', count: 0 },
      typography: { file: 'typography.json', count: 0 },
      spacing: { file: 'spacing.json', count: 0 },
      effects: { file: 'effects.json', count: 0 },
      borderRadius: { file: 'border-radius.json', count: 0 }
    },
    totalTokens: 0
  })
};

/**
 * Framework file extensions
 */
const FRAMEWORK_EXTENSIONS = {
  'react': 'tsx',
  'vue': 'vue',
  'svelte': 'svelte',
  'angular': 'component.ts',
  'react-native': 'tsx',
  'flutter': 'dart',
  'swiftui': 'swift',
  'jetpack-compose': 'kt',
  'web-components': 'ts'
};

class DesignStructure {
  constructor(projectPath) {
    this.projectPath = projectPath;
    this.designPath = path.join(projectPath, '.design');
  }

  /**
   * Initialize the complete .design/ directory structure
   * @param {Object} options - Configuration options
   * @returns {Object} Initialization result
   */
  initialize(options = {}) {
    const results = {
      directoriesCreated: [],
      manifestsCreated: [],
      manifestsUpdated: [],
      errors: []
    };

    // Create base directories
    for (const dir of STRUCTURE.directories) {
      const fullPath = path.join(this.projectPath, dir);
      if (!fs.existsSync(fullPath)) {
        try {
          fs.mkdirSync(fullPath, { recursive: true });
          results.directoriesCreated.push(dir);
        } catch (e) {
          results.errors.push(`Failed to create ${dir}: ${e.message}`);
        }
      }
    }

    // Create framework-specific directories
    const framework = options.framework || 'react';
    for (const dir of STRUCTURE.frameworkDirs(framework)) {
      const fullPath = path.join(this.projectPath, dir);
      if (!fs.existsSync(fullPath)) {
        try {
          fs.mkdirSync(fullPath, { recursive: true });
          results.directoriesCreated.push(dir);
        } catch (e) {
          results.errors.push(`Failed to create ${dir}: ${e.message}`);
        }
      }
    }

    // Create or update manifests
    this.ensureManifest('config', options, results);
    this.ensureManifest('componentRegistry', options, results);
    this.ensureManifest('layoutManifest', options, results);
    this.ensureManifest('tokenIndex', options, results);

    // Create barrel exports for framework directories
    this.ensureBarrelExports(framework, results);

    return {
      success: results.errors.length === 0,
      ...results
    };
  }

  /**
   * Ensure a manifest file exists with valid structure
   */
  ensureManifest(manifestName, options, results) {
    const manifestPath = path.join(this.projectPath, STRUCTURE.manifests[manifestName]);
    const defaultFactory = DEFAULT_MANIFESTS[manifestName];

    if (!fs.existsSync(manifestPath)) {
      try {
        const content = defaultFactory(options);
        fs.writeFileSync(manifestPath, JSON.stringify(content, null, 2));
        results.manifestsCreated.push(manifestName);
      } catch (e) {
        results.errors.push(`Failed to create ${manifestName}: ${e.message}`);
      }
    } else {
      // Validate existing manifest has required fields
      try {
        const existing = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
        const template = defaultFactory(options);
        let updated = false;

        // Add missing top-level keys
        for (const key of Object.keys(template)) {
          if (!(key in existing)) {
            existing[key] = template[key];
            updated = true;
          }
        }

        if (updated) {
          existing.lastUpdated = new Date().toISOString();
          fs.writeFileSync(manifestPath, JSON.stringify(existing, null, 2));
          results.manifestsUpdated.push(manifestName);
        }
      } catch (e) {
        results.errors.push(`Failed to validate ${manifestName}: ${e.message}`);
      }
    }
  }

  /**
   * Ensure barrel export files exist for framework directories
   */
  ensureBarrelExports(framework, results) {
    const dirs = ['components', 'tokens', 'layouts'];
    const ext = framework === 'flutter' ? 'dart' : 'ts';

    for (const dir of dirs) {
      const indexPath = path.join(
        this.projectPath,
        '.design',
        'extracted-code',
        framework,
        dir,
        `index.${ext}`
      );

      if (!fs.existsSync(indexPath)) {
        try {
          const comment = framework === 'flutter'
            ? '// Design Bridge - Auto-generated barrel export\n// Re-export all ${dir}\n'
            : `// Design Bridge - Auto-generated barrel export\n// Re-export all ${dir}\n`;

          fs.writeFileSync(indexPath, comment + '\n');
          results.directoriesCreated.push(`${framework}/${dir}/index.${ext}`);
        } catch (e) {
          // Directory might not exist yet, that's ok
        }
      }
    }
  }

  // ==========================================================================
  // v4.0.0 Registry Integration
  // ==========================================================================

  /**
   * Initialize v4.0.0 unified registry structure
   * Creates registry-index.json and registries/ directory with empty registries
   * @param {Object} options - Initialization options
   * @returns {Promise<Object>} Initialization result
   */
  async initializeV4Registry(options = {}) {
    const results = {
      created: [],
      skipped: [],
      errors: []
    };

    try {
      const { getRegistryManager, clearRegistryManager } = getRegistryManagerModule();

      // Clear any cached manager first
      clearRegistryManager();

      // Get the registry manager - it will create structure if needed
      const manager = await getRegistryManager(this.designPath);

      // Check what was created
      const indexPath = path.join(this.designPath, 'registry-index.json');
      const registriesPath = path.join(this.designPath, 'registries');

      if (fs.existsSync(indexPath)) {
        results.created.push('registry-index.json');
      }

      if (fs.existsSync(registriesPath)) {
        results.created.push('registries/');

        for (const type of ['components', 'tokens', 'layouts']) {
          const regPath = path.join(registriesPath, `${type}.json`);
          if (fs.existsSync(regPath)) {
            results.created.push(`registries/${type}.json`);
          }
        }
      }

      console.log('[DesignStructure] v4.0.0 registry initialized');

      return {
        success: true,
        ...results
      };

    } catch (error) {
      console.error('[DesignStructure] v4.0.0 initialization failed:', error.message);
      results.errors.push(error.message);

      return {
        success: false,
        ...results
      };
    }
  }

  /**
   * Check if v4.0.0 registry exists
   * @returns {boolean} True if v4.0.0 registry is initialized
   */
  hasV4Registry() {
    const indexPath = path.join(this.designPath, 'registry-index.json');
    return fs.existsSync(indexPath);
  }

  /**
   * Get the RegistryManager instance for this project
   * @returns {Promise<Object>} RegistryManager instance
   */
  async getRegistryManager() {
    const { getRegistryManager } = getRegistryManagerModule();
    return getRegistryManager(this.designPath);
  }

  /**
   * Get v4.0.0 registry statistics
   * @returns {Promise<Object>} Registry stats
   */
  async getV4RegistryStats() {
    if (!this.hasV4Registry()) {
      return null;
    }

    try {
      const manager = await this.getRegistryManager();
      return await manager.getStats();
    } catch (error) {
      console.error('[DesignStructure] Failed to get v4.0.0 stats:', error.message);
      return null;
    }
  }

  /**
   * Get the current structure status
   * @returns {Object} Structure status report
   */
  getStatus() {
    const status = {
      initialized: fs.existsSync(this.designPath),
      directories: {},
      manifests: {},
      frameworks: {},
      v4Registry: {
        available: false,
        files: {}
      }
    };

    // Check v4.0.0 registry
    const indexPath = path.join(this.projectPath, STRUCTURE.v4Registries.index);
    if (fs.existsSync(indexPath)) {
      status.v4Registry.available = true;
      try {
        const data = JSON.parse(fs.readFileSync(indexPath, 'utf8'));
        status.v4Registry.version = data.version;
        status.v4Registry.lastUpdated = data.lastUpdated;
      } catch (e) {
        status.v4Registry.error = 'Invalid JSON';
      }

      // Check individual registry files
      for (const [name, relPath] of Object.entries(STRUCTURE.v4Registries)) {
        const fullPath = path.join(this.projectPath, relPath);
        status.v4Registry.files[name] = {
          exists: fs.existsSync(fullPath),
          path: relPath
        };

        if (status.v4Registry.files[name].exists && name !== 'index') {
          try {
            const data = JSON.parse(fs.readFileSync(fullPath, 'utf8'));
            status.v4Registry.files[name].count = Object.keys(data.entries || {}).length;
          } catch (e) {
            status.v4Registry.files[name].error = 'Invalid JSON';
          }
        }
      }
    }

    // Check directories
    for (const dir of STRUCTURE.directories) {
      const fullPath = path.join(this.projectPath, dir);
      status.directories[dir] = fs.existsSync(fullPath);
    }

    // Check manifests
    for (const [name, relPath] of Object.entries(STRUCTURE.manifests)) {
      const fullPath = path.join(this.projectPath, relPath);
      status.manifests[name] = {
        exists: fs.existsSync(fullPath),
        path: relPath
      };

      if (status.manifests[name].exists) {
        try {
          const data = JSON.parse(fs.readFileSync(fullPath, 'utf8'));
          status.manifests[name].version = data.version;
          status.manifests[name].lastUpdated = data.lastUpdated;
        } catch (e) {
          status.manifests[name].error = 'Invalid JSON';
        }
      }
    }

    // Check framework directories
    const extractedCodePath = path.join(this.designPath, 'extracted-code');
    if (fs.existsSync(extractedCodePath)) {
      const frameworks = fs.readdirSync(extractedCodePath, { withFileTypes: true })
        .filter(e => e.isDirectory())
        .map(e => e.name);

      for (const fw of frameworks) {
        status.frameworks[fw] = {
          components: this.countFiles(path.join(extractedCodePath, fw, 'components')),
          tokens: this.countFiles(path.join(extractedCodePath, fw, 'tokens')),
          layouts: this.countFiles(path.join(extractedCodePath, fw, 'layouts'))
        };
      }
    }

    return status;
  }

  /**
   * Count files in a directory (excluding index files)
   */
  countFiles(dirPath) {
    if (!fs.existsSync(dirPath)) return 0;

    try {
      return fs.readdirSync(dirPath)
        .filter(f => !f.startsWith('index.') && !f.startsWith('.'))
        .length;
    } catch (e) {
      return 0;
    }
  }

  /**
   * Register a new layout in the manifest
   * @param {Object} layoutInfo - Layout information
   */
  registerLayout(layoutInfo) {
    const manifestPath = path.join(this.projectPath, STRUCTURE.manifests.layoutManifest);

    let manifest;
    if (fs.existsSync(manifestPath)) {
      manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
    } else {
      manifest = DEFAULT_MANIFESTS.layoutManifest();
    }

    // Find existing or create new entry
    const existingIndex = manifest.layouts.findIndex(l => l.name === layoutInfo.name);
    const entry = {
      id: layoutInfo.id || `layout-${Date.now()}`,
      name: layoutInfo.name,
      directory: `.design/layouts/${layoutInfo.safeName || layoutInfo.name.toLowerCase().replace(/\s+/g, '-')}`,
      status: layoutInfo.status || 'extracted',
      stage: layoutInfo.stage || 1,
      dimensions: layoutInfo.dimensions || null,
      artifacts: {
        layoutJson: layoutInfo.layoutJson || null,
        screenshot: layoutInfo.screenshot || null,
        referenceHtml: layoutInfo.referenceHtml || null,
        validationReport: layoutInfo.validationReport || null,
        frameworkCode: layoutInfo.frameworkCode || {}
      },
      createdAt: layoutInfo.createdAt || new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };

    if (existingIndex >= 0) {
      manifest.layouts[existingIndex] = { ...manifest.layouts[existingIndex], ...entry };
    } else {
      manifest.layouts.push(entry);
    }

    // Update metadata
    manifest.metadata.totalLayouts = manifest.layouts.length;
    manifest.metadata.byStage = this.countLayoutsByStage(manifest.layouts);
    manifest.lastUpdated = new Date().toISOString();

    fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));

    return entry;
  }

  /**
   * Update layout pipeline stage
   * @param {string} layoutName - Layout name
   * @param {number} stage - Pipeline stage (1-5)
   * @param {Object} artifacts - Artifacts for this stage
   */
  updateLayoutStage(layoutName, stage, artifacts = {}) {
    const manifestPath = path.join(this.projectPath, STRUCTURE.manifests.layoutManifest);

    if (!fs.existsSync(manifestPath)) {
      throw new Error('Layout manifest not found. Run initialize() first.');
    }

    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
    const layout = manifest.layouts.find(l =>
      l.name === layoutName ||
      l.name.toLowerCase() === layoutName.toLowerCase()
    );

    if (!layout) {
      throw new Error(`Layout not found: ${layoutName}`);
    }

    const stageNames = {
      1: 'extracted',
      2: 'screenshot',
      3: 'html-generated',
      4: 'validated',
      5: 'code-generated'
    };

    layout.stage = stage;
    layout.status = stageNames[stage] || layout.status;
    layout.artifacts = { ...layout.artifacts, ...artifacts };
    layout.updatedAt = new Date().toISOString();

    manifest.metadata.byStage = this.countLayoutsByStage(manifest.layouts);
    manifest.lastUpdated = new Date().toISOString();

    fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));

    return layout;
  }

  /**
   * Count layouts by pipeline stage
   */
  countLayoutsByStage(layouts) {
    const counts = {
      extracted: 0,
      screenshot: 0,
      'html-generated': 0,
      validated: 0,
      'code-generated': 0
    };

    for (const layout of layouts) {
      if (layout.status in counts) {
        counts[layout.status]++;
      }
    }

    return counts;
  }

  /**
   * Register a component in the registry
   * @param {Object} componentInfo - Component information
   */
  registerComponent(componentInfo) {
    const registryPath = path.join(this.projectPath, STRUCTURE.manifests.componentRegistry);

    let registry;
    if (fs.existsSync(registryPath)) {
      registry = JSON.parse(fs.readFileSync(registryPath, 'utf8'));
    } else {
      registry = DEFAULT_MANIFESTS.componentRegistry();
    }

    const entry = {
      id: componentInfo.id || `comp-${Date.now()}`,
      name: componentInfo.name,
      source: componentInfo.source || 'manual',
      figmaNodeId: componentInfo.figmaNodeId || null,
      transformedTo: componentInfo.transformedTo || [],
      outputPaths: componentInfo.outputPaths || {},
      metadata: componentInfo.metadata || {},
      createdAt: componentInfo.createdAt || new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };

    // Find existing or add new
    const existingIndex = registry.components.findIndex(c => c.name === entry.name);
    if (existingIndex >= 0) {
      registry.components[existingIndex] = { ...registry.components[existingIndex], ...entry };
    } else {
      registry.components.push(entry);
    }

    // Update metadata
    registry.metadata.totalComponents = registry.components.length;
    registry.metadata.sources = {
      figma: registry.components.filter(c => c.source === 'figma').length,
      shadcn: registry.components.filter(c => c.source === 'shadcn').length,
      nlp: registry.components.filter(c => c.source === 'nlp').length,
      manual: registry.components.filter(c => c.source === 'manual').length
    };
    registry.lastUpdated = new Date().toISOString();

    fs.writeFileSync(registryPath, JSON.stringify(registry, null, 2));

    return entry;
  }

  /**
   * Update barrel exports after adding new components/layouts
   * @param {string} framework - Target framework
   * @param {string} type - 'components', 'tokens', or 'layouts'
   */
  updateBarrelExport(framework, type) {
    const dirPath = path.join(this.designPath, 'extracted-code', framework, type);
    if (!fs.existsSync(dirPath)) return;

    const ext = FRAMEWORK_EXTENSIONS[framework] || 'ts';
    const indexPath = path.join(dirPath, `index.${ext === 'dart' ? 'dart' : 'ts'}`);

    // Get all files in directory (excluding index)
    const files = fs.readdirSync(dirPath, { withFileTypes: true })
      .filter(e => {
        if (e.name.startsWith('index.')) return false;
        if (e.name.startsWith('.')) return false;
        return e.isFile() || e.isDirectory();
      });

    let exports = [];

    if (framework === 'flutter') {
      // Dart exports
      exports = files.map(f => {
        const name = f.isDirectory() ? f.name : f.name.replace(/\.\w+$/, '');
        const file = f.isDirectory() ? `${f.name}/${f.name}.dart` : f.name;
        return `export '${file}';`;
      });
    } else {
      // TypeScript/JavaScript exports
      exports = files.map(f => {
        const name = f.isDirectory() ? f.name : f.name.replace(/\.\w+$/, '');
        const importPath = f.isDirectory() ? `./${f.name}` : `./${name}`;
        return `export * from '${importPath}';`;
      });
    }

    const header = `// Design Bridge - Auto-generated barrel export
// ${type.charAt(0).toUpperCase() + type.slice(1)} for ${framework}
// Last updated: ${new Date().toISOString()}
`;

    fs.writeFileSync(indexPath, header + '\n' + exports.join('\n') + '\n');
  }

  /**
   * Get layout by name
   * @param {string} layoutName - Layout name
   * @returns {Object|null} Layout entry or null
   */
  getLayout(layoutName) {
    const manifestPath = path.join(this.projectPath, STRUCTURE.manifests.layoutManifest);

    if (!fs.existsSync(manifestPath)) return null;

    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
    return manifest.layouts.find(l =>
      l.name === layoutName ||
      l.name.toLowerCase() === layoutName.toLowerCase() ||
      l.directory.endsWith(`/${layoutName}`)
    ) || null;
  }

  /**
   * Get component by name
   * @param {string} componentName - Component name
   * @returns {Object|null} Component entry or null
   */
  getComponent(componentName) {
    const registryPath = path.join(this.projectPath, STRUCTURE.manifests.componentRegistry);

    if (!fs.existsSync(registryPath)) return null;

    const registry = JSON.parse(fs.readFileSync(registryPath, 'utf8'));
    return registry.components.find(c =>
      c.name === componentName ||
      c.name.toLowerCase() === componentName.toLowerCase()
    ) || null;
  }
}

/**
 * Factory function
 */
function createDesignStructure(projectPath) {
  return new DesignStructure(projectPath);
}

/**
 * Quick initialization
 */
function initializeDesignStructure(projectPath, options = {}) {
  const structure = new DesignStructure(projectPath);
  return structure.initialize(options);
}

module.exports = {
  DesignStructure,
  createDesignStructure,
  initializeDesignStructure,
  STRUCTURE,
  DEFAULT_MANIFESTS,
  FRAMEWORK_EXTENSIONS
};
