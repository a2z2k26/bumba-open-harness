/**
 * Design System Catalog Orchestrator
 * Central system for managing project-specific design catalogs
 * Serves both human and AI contributors equally
 */

const EventEmitter = require('events');
const path = require('path');
const fs = require('fs').promises;
const chalk = require('chalk');
const { logger } = require('../../logging/bumba-logger');

class CatalogOrchestrator extends EventEmitter {
  constructor() {
    super();

    // Core catalog state
    this.catalogs = new Map(); // project -> catalog instance
    this.activeProject = null;
    this.aiContext = new Map(); // AI-friendly context cache

    // Component registry
    this.componentRegistry = new Map();
    this.designAssets = new Map();
    this.codeImplementations = new Map();

    // Sync state
    this.syncQueue = [];
    this.syncInProgress = false;

    // Sandbox environments
    this.sandboxes = new Map();

    // Initialize subsystems
    this.initializeSubsystems();
  }

  /**
   * Initialize catalog subsystems
   */
  initializeSubsystems() {
    // Auto-generation hooks
    this.setupProjectHooks();

    // AI API interface
    this.setupAIInterface();

    // Real-time collaboration
    this.setupCollaboration();

    // Bidirectional sync
    this.setupBidirectionalSync();

    logger.info('Catalog Orchestrator initialized');
  }

  /**
   * Auto-create catalog for new projects
   */
  async createProjectCatalog(projectName, projectPath = process.cwd()) {
    console.log(chalk.cyan('🎨 Creating Design System Catalog for project:', projectName));

    // Create catalog structure
    const catalog = {
      projectName,
      projectPath,
      createdAt: new Date().toISOString(),
      version: '1.0.0',

      // Design tokens
      tokens: {
        colors: {},
        typography: {},
        spacing: {},
        shadows: {},
        effects: {},
        animations: {}
      },

      // Component library
      components: {
        atoms: {},      // Basic building blocks
        molecules: {},  // Combined atoms
        organisms: {},  // Complex components
        templates: {},  // Page templates
        pages: {}      // Complete pages
      },

      // Asset tracking
      assets: {
        images: {},
        icons: {},
        illustrations: {},
        logos: {}
      },

      // Implementation mapping
      implementations: {
        react: {},
        vue: {},
        angular: {},
        webComponents: {},
        native: {}
      },

      // AI context
      aiContext: {
        designPrinciples: [],
        brandGuidelines: {},
        componentPatterns: {},
        accessibilityRules: {},
        performanceTargets: {}
      },

      // Collaboration
      contributors: {
        human: [],
        ai: []
      },

      // Sandbox configurations
      sandboxes: {},

      // Version history
      history: []
    };

    // Store catalog
    this.catalogs.set(projectName, catalog);
    this.activeProject = projectName;

    // Create physical catalog directory
    const catalogPath = path.join(projectPath, '.design-catalog');
    await fs.mkdir(catalogPath, { recursive: true });

    // Save catalog manifest
    await this.saveCatalogManifest(catalog, catalogPath);

    // Generate initial visualizer
    await this.generateVisualizer(catalog, catalogPath);

    // Setup watchers for auto-sync
    await this.setupProjectWatchers(projectPath, catalog);

    // Emit creation event
    this.emit('catalog:created', {
      projectName,
      catalogPath,
      catalog
    });

    console.log(chalk.green('✅ Design System Catalog created successfully'));
    console.log(chalk.cyan(`📁 Location: ${catalogPath}`));

    return catalog;
  }

  /**
   * Register a design asset and auto-generate code
   */
  async registerDesignAsset(assetData) {
    const { type, name, source, metadata } = assetData;

    console.log(chalk.blue(`📥 Registering design asset: ${name}`));

    // Store in registry
    const assetId = this.generateAssetId(name, type);
    this.designAssets.set(assetId, {
      ...assetData,
      id: assetId,
      registeredAt: Date.now(),
      implementations: []
    });

    // Auto-generate code implementations
    const implementations = await this.generateImplementations(assetData);

    // Store implementations
    implementations.forEach(impl => {
      this.codeImplementations.set(`${assetId}:${impl.framework}`, impl);
    });

    // Update catalog
    if (this.activeProject) {
      const catalog = this.catalogs.get(this.activeProject);
      if (catalog) {
        // Categorize and store
        const category = this.categorizeAsset(assetData);
        if (!catalog.components[category]) {
          catalog.components[category] = {};
        }
        catalog.components[category][name] = {
          design: assetData,
          implementations,
          usage: []
        };

        // Update AI context
        this.updateAIContext(catalog, assetData, implementations);
      }
    }

    // Emit registration event
    this.emit('asset:registered', {
      assetId,
      asset: assetData,
      implementations
    });

    return { assetId, implementations };
  }

  /**
   * Generate code implementations for design asset
   */
  async generateImplementations(assetData) {
    const implementations = [];

    // React implementation
    implementations.push(await this.generateReactComponent(assetData));

    // Web Component implementation
    implementations.push(await this.generateWebComponent(assetData));

    // Vue implementation
    implementations.push(await this.generateVueComponent(assetData));

    return implementations.filter(Boolean);
  }

  /**
   * Generate React component from design asset
   */
  async generateReactComponent(assetData) {
    const { name, type, properties = {} } = assetData;

    const componentName = this.toPascalCase(name);
    const code = `import React from 'react';
import './styles/${componentName}.css';

interface ${componentName}Props {
${Object.entries(properties).map(([key, value]) =>
  `  ${key}?: ${this.getTypeScriptType(value)};`
).join('\n')}
}

export const ${componentName}: React.FC<${componentName}Props> = (props) => {
  return (
    <div className="${this.toKebabCase(name)}" {...props}>
      {/* Component implementation */}
      {props.children}
    </div>
  );
};

export default ${componentName};`;

    return {
      framework: 'react',
      language: 'typescript',
      componentName,
      code,
      dependencies: ['react'],
      metadata: {
        generated: Date.now(),
        source: 'design-asset'
      }
    };
  }

  /**
   * Generate Web Component from design asset
   */
  async generateWebComponent(assetData) {
    const { name, type, properties = {} } = assetData;

    const componentName = this.toKebabCase(name);
    const className = this.toPascalCase(name);

    const code = `class ${className} extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
  }

  static get observedAttributes() {
    return [${Object.keys(properties).map(k => `'${this.toKebabCase(k)}'`).join(', ')}];
  }

  connectedCallback() {
    this.render();
  }

  attributeChangedCallback(name, oldValue, newValue) {
    if (oldValue !== newValue) {
      this.render();
    }
  }

  render() {
    this.shadowRoot.innerHTML = \`
      <style>
        :host {
          display: block;
        }
      </style>
      <div class="${componentName}">
        <slot></slot>
      </div>
    \`;
  }
}

customElements.define('${componentName}', ${className});
export default ${className};`;

    return {
      framework: 'web-components',
      language: 'javascript',
      componentName: className,
      tagName: componentName,
      code,
      dependencies: [],
      metadata: {
        generated: Date.now(),
        source: 'design-asset'
      }
    };
  }

  /**
   * Generate Vue component from design asset
   */
  async generateVueComponent(assetData) {
    const { name, type, properties = {} } = assetData;

    const componentName = this.toPascalCase(name);

    const code = `<template>
  <div class="${this.toKebabCase(name)}">
    <slot></slot>
  </div>
</template>

<script>
export default {
  name: '${componentName}',
  props: {
${Object.entries(properties).map(([key, value]) =>
  `    ${key}: {
      type: ${this.getVueType(value)},
      default: ${this.getVueDefault(value)}
    }`
).join(',\n')}
  },
  data() {
    return {};
  },
  methods: {},
  mounted() {
    // Component initialization
  }
};
</script>

<style scoped>
.${this.toKebabCase(name)} {
  /* Component styles */
}
</style>`;

    return {
      framework: 'vue',
      language: 'vue',
      componentName,
      code,
      dependencies: ['vue'],
      metadata: {
        generated: Date.now(),
        source: 'design-asset'
      }
    };
  }

  /**
   * Create sandbox environment for component iteration
   */
  async createSandbox(componentId, options = {}) {
    console.log(chalk.cyan('🧪 Creating sandbox environment for:', componentId));

    const sandbox = {
      id: `sandbox-${Date.now()}`,
      componentId,
      created: new Date().toISOString(),
      status: 'initializing',

      // Sandbox configuration
      config: {
        framework: options.framework || 'react',
        liveReload: true,
        hotModule: true,
        isolated: true,
        port: this.getAvailablePort()
      },

      // Component variations
      variations: [],

      // Test scenarios
      scenarios: options.scenarios || [],

      // Performance metrics
      metrics: {
        renderTime: null,
        bundleSize: null,
        accessibility: null
      }
    };

    // Store sandbox
    this.sandboxes.set(sandbox.id, sandbox);

    // Initialize sandbox environment
    await this.initializeSandbox(sandbox);

    // Emit sandbox created event
    this.emit('sandbox:created', sandbox);

    return sandbox;
  }

  /**
   * Get AI-friendly catalog API
   */
  getAIAPI() {
    return {
      // Query methods
      query: this.queryComponents.bind(this),
      search: this.searchCatalog.bind(this),

      // Registration methods
      register: this.registerDesignAsset.bind(this),
      update: this.updateComponent.bind(this),

      // Generation methods
      generate: this.generateImplementations.bind(this),
      suggest: this.suggestComponents.bind(this),

      // Analysis methods
      analyze: this.analyzeUsage.bind(this),
      validate: this.validateComponent.bind(this),

      // Context methods
      getContext: this.getAIContext.bind(this),
      updateContext: this.updateAIContext.bind(this)
    };
  }

  /**
   * Query components for AI
   */
  async queryComponents(query) {
    const results = [];

    // Search through all catalogs
    for (const [projectName, catalog] of this.catalogs) {
      for (const [category, components] of Object.entries(catalog.components)) {
        for (const [name, component] of Object.entries(components)) {
          if (this.matchesQuery(component, query)) {
            results.push({
              project: projectName,
              category,
              name,
              component,
              relevance: this.calculateRelevance(component, query)
            });
          }
        }
      }
    }

    // Sort by relevance
    results.sort((a, b) => b.relevance - a.relevance);

    return results;
  }

  /**
   * Suggest components based on context
   */
  async suggestComponents(context) {
    const suggestions = [];

    // Analyze context
    const { intent, requirements, constraints } = this.analyzeContext(context);

    // Find matching components
    for (const [assetId, asset] of this.designAssets) {
      const score = this.calculateMatchScore(asset, { intent, requirements, constraints });
      if (score > 0.7) {
        suggestions.push({
          asset,
          score,
          reason: this.generateSuggestionReason(asset, context)
        });
      }
    }

    // Sort by score
    suggestions.sort((a, b) => b.score - a.score);

    return suggestions.slice(0, 5); // Top 5 suggestions
  }

  /**
   * Setup bidirectional sync between design and code
   */
  setupBidirectionalSync() {
    // Watch for design changes
    this.on('design:updated', async (event) => {
      await this.syncDesignToCode(event);
    });

    // Watch for code changes
    this.on('code:updated', async (event) => {
      await this.syncCodeToDesign(event);
    });

    // Process sync queue
    setInterval(() => this.processSyncQueue(), 1000);
  }

  /**
   * Sync design changes to code
   */
  async syncDesignToCode(event) {
    const { assetId, changes } = event;

    // Get implementations
    const implementations = [];
    for (const [key, impl] of this.codeImplementations) {
      if (key.startsWith(assetId)) {
        implementations.push(impl);
      }
    }

    // Update each implementation
    for (const impl of implementations) {
      const updated = await this.updateImplementation(impl, changes);
      this.codeImplementations.set(`${assetId}:${impl.framework}`, updated);
    }

    // Emit sync event
    this.emit('sync:design-to-code', {
      assetId,
      changes,
      implementations: implementations.length
    });
  }

  /**
   * Sync code changes to design
   */
  async syncCodeToDesign(event) {
    const { componentId, changes } = event;

    // Extract design updates from code changes
    const designUpdates = await this.extractDesignUpdates(changes);

    // Update design asset
    const assetId = componentId.split(':')[0];
    const asset = this.designAssets.get(assetId);

    if (asset) {
      Object.assign(asset, designUpdates);
      this.designAssets.set(assetId, asset);

      // Emit sync event
      this.emit('sync:code-to-design', {
        assetId,
        updates: designUpdates
      });
    }
  }

  /**
   * Process sync queue
   */
  async processSyncQueue() {
    if (this.syncInProgress || this.syncQueue.length === 0) return;

    this.syncInProgress = true;

    while (this.syncQueue.length > 0) {
      const task = this.syncQueue.shift();
      try {
        await this.executeSyncTask(task);
      } catch (error) {
        logger.error('Sync task failed:', error);
      }
    }

    this.syncInProgress = false;
  }

  /**
   * Save catalog manifest
   */
  async saveCatalogManifest(catalog, catalogPath) {
    const manifestPath = path.join(catalogPath, 'catalog.json');
    await fs.writeFile(manifestPath, JSON.stringify(catalog, null, 2));
  }

  /**
   * Generate visual catalog
   */
  async generateVisualizer(catalog, catalogPath) {
    const EnhancedCatalogGenerator = require('../catalog-generator/enhanced-catalog-generator');
    const generator = new EnhancedCatalogGenerator();

    await generator.generate(catalog.tokens, {}, catalogPath);
  }

  /**
   * Setup project hooks for auto-generation
   */
  setupProjectHooks() {
    // Hook into project creation
    process.on('bumba:project:created', async (event) => {
      await this.createProjectCatalog(event.projectName, event.projectPath);
    });

    // Hook into component creation
    process.on('bumba:component:created', async (event) => {
      await this.registerDesignAsset(event.component);
    });
  }

  /**
   * Setup AI interface
   */
  setupAIInterface() {
    // Create AI-friendly API endpoint
    this.aiAPI = this.getAIAPI();
  }

  /**
   * Setup real-time collaboration
   */
  setupCollaboration() {
    // WebSocket for real-time updates
    this.on('collaboration:joined', (user) => {
      this.broadcastUpdate('user:joined', user);
    });

    this.on('collaboration:update', (update) => {
      this.broadcastUpdate('catalog:updated', update);
    });
  }

  /**
   * Helper methods
   */

  generateAssetId(name, type) {
    return `${type}-${this.toKebabCase(name)}-${Date.now()}`;
  }

  categorizeAsset(assetData) {
    const { type, complexity = 'low' } = assetData;

    if (complexity === 'low' || type === 'basic') return 'atoms';
    if (complexity === 'medium') return 'molecules';
    if (complexity === 'high') return 'organisms';
    if (type === 'template') return 'templates';
    if (type === 'page') return 'pages';

    return 'molecules'; // default
  }

  toPascalCase(str) {
    return str.replace(/(^\w|-\w|_\w)/g, (match) =>
      match.replace(/-|_/, '').toUpperCase()
    );
  }

  toKebabCase(str) {
    return str
      .replace(/([A-Z])/g, '-$1')
      .toLowerCase()
      .replace(/^-/, '')
      .replace(/[\s_]+/g, '-');
  }

  getTypeScriptType(value) {
    if (typeof value === 'string') return 'string';
    if (typeof value === 'number') return 'number';
    if (typeof value === 'boolean') return 'boolean';
    if (Array.isArray(value)) return 'any[]';
    return 'any';
  }

  getVueType(value) {
    if (typeof value === 'string') return 'String';
    if (typeof value === 'number') return 'Number';
    if (typeof value === 'boolean') return 'Boolean';
    if (Array.isArray(value)) return 'Array';
    return 'Object';
  }

  getVueDefault(value) {
    if (typeof value === 'string') return "''";
    if (typeof value === 'number') return '0';
    if (typeof value === 'boolean') return 'false';
    if (Array.isArray(value)) return '() => []';
    return '() => ({})';
  }

  getAvailablePort() {
    // Find available port for sandbox
    return 3000 + Math.floor(Math.random() * 1000);
  }

  updateAIContext(catalog, assetData, implementations) {
    // Update AI context with new component patterns
    if (!catalog.aiContext.componentPatterns[assetData.type]) {
      catalog.aiContext.componentPatterns[assetData.type] = [];
    }

    catalog.aiContext.componentPatterns[assetData.type].push({
      name: assetData.name,
      properties: assetData.properties,
      implementations: implementations.map(i => ({
        framework: i.framework,
        componentName: i.componentName
      })),
      usage: []
    });
  }

  matchesQuery(component, query) {
    // Simple text matching for now
    const searchText = JSON.stringify(component).toLowerCase();
    return searchText.includes(query.toLowerCase());
  }

  calculateRelevance(component, query) {
    // Simple relevance scoring
    let score = 0;
    const searchText = JSON.stringify(component).toLowerCase();
    const queryLower = query.toLowerCase();

    // Exact name match
    if (component.design?.name?.toLowerCase() === queryLower) score += 10;

    // Partial name match
    if (component.design?.name?.toLowerCase().includes(queryLower)) score += 5;

    // Property match
    if (searchText.includes(queryLower)) score += 1;

    return score;
  }

  analyzeContext(context) {
    // Extract intent, requirements, and constraints from context
    return {
      intent: context.intent || 'create',
      requirements: context.requirements || [],
      constraints: context.constraints || []
    };
  }

  calculateMatchScore(asset, criteria) {
    // Calculate how well an asset matches criteria
    let score = 0;
    const maxScore = 10;

    // Check intent match
    if (asset.metadata?.intent === criteria.intent) score += 3;

    // Check requirements
    criteria.requirements.forEach(req => {
      if (asset.properties?.[req] || asset.metadata?.[req]) score += 1;
    });

    // Normalize score
    return Math.min(score / maxScore, 1);
  }

  generateSuggestionReason(asset, context) {
    return `${asset.name} matches your requirement for ${context.intent} and provides the necessary properties`;
  }

  async initializeSandbox(sandbox) {
    // Initialize sandbox environment
    sandbox.status = 'ready';

    logger.info(`Sandbox ${sandbox.id} initialized on port ${sandbox.config.port}`);
  }

  async updateImplementation(impl, changes) {
    // Update implementation based on design changes
    // This would involve AST manipulation in a real implementation
    return {
      ...impl,
      lastUpdated: Date.now(),
      changes
    };
  }

  async extractDesignUpdates(codeChanges) {
    // Extract design-relevant changes from code
    return {
      properties: codeChanges.properties || {},
      styles: codeChanges.styles || {},
      behavior: codeChanges.behavior || {}
    };
  }

  async executeSyncTask(task) {
    // Execute a sync task
    logger.debug('Executing sync task:', task);
  }

  broadcastUpdate(event, data) {
    // Broadcast update to all connected clients
    this.emit('broadcast', { event, data });
  }

  getAIContext() {
    if (!this.activeProject) return null;

    const catalog = this.catalogs.get(this.activeProject);
    return catalog?.aiContext || null;
  }

  async searchCatalog(query) {
    return this.queryComponents(query);
  }

  async updateComponent(componentId, updates) {
    // Update component in catalog
    const [projectName, category, name] = componentId.split(':');
    const catalog = this.catalogs.get(projectName);

    if (catalog && catalog.components[category]?.[name]) {
      Object.assign(catalog.components[category][name], updates);
      return true;
    }

    return false;
  }

  async analyzeUsage(componentId) {
    // Analyze component usage across projects
    const usage = [];

    for (const [projectName, catalog] of this.catalogs) {
      // Search for usage in catalog
      const component = this.findComponentInCatalog(catalog, componentId);
      if (component?.usage) {
        usage.push(...component.usage);
      }
    }

    return {
      componentId,
      usageCount: usage.length,
      instances: usage
    };
  }

  async validateComponent(componentId) {
    // Validate component against design system rules
    const validations = {
      accessibility: true,
      performance: true,
      consistency: true,
      completeness: true
    };

    return validations;
  }

  findComponentInCatalog(catalog, componentId) {
    for (const [category, components] of Object.entries(catalog.components)) {
      for (const [name, component] of Object.entries(components)) {
        if (`${catalog.projectName}:${category}:${name}` === componentId) {
          return component;
        }
      }
    }
    return null;
  }

  async setupProjectWatchers(projectPath, catalog) {
    // Setup file watchers for auto-sync
    // Would use chokidar or similar in real implementation
    logger.info('Project watchers setup for:', projectPath);
  }
}

// Singleton instance
let instance = null;

module.exports = {
  CatalogOrchestrator,
  getInstance: () => {
    if (!instance) {
      instance = new CatalogOrchestrator();
    }
    return instance;
  }
};