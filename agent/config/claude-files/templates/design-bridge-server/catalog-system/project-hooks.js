/**
 * Project Hooks for Design System Catalog
 * Auto-generates catalog for new projects
 */

const path = require('path');
const fs = require('fs').promises;
const chalk = require('chalk');
const { logger } = require('../../logging/bumba-logger');
const { getInstance: getCatalogOrchestrator } = require('./catalog-orchestrator');

class ProjectHooks {
  constructor() {
    this.orchestrator = getCatalogOrchestrator();
    this.initialized = false;
  }

  /**
   * Initialize project hooks
   */
  async initialize() {
    if (this.initialized) return;

    // Hook into BUMBA CLI project events
    this.setupCommandHooks();

    // Watch for project initialization
    this.watchProjectInit();

    // Monitor design file creation
    this.setupDesignFileWatchers();

    this.initialized = true;
    logger.info('Project hooks initialized for Design System Catalog');
  }

  /**
   * Setup command hooks for BUMBA CLI
   */
  setupCommandHooks() {
    // Hook into 'bumba new' command
    this.interceptNewCommand();

    // Hook into 'bumba init' command
    this.interceptInitCommand();

    // Hook into 'bumba design' commands
    this.interceptDesignCommands();
  }

  /**
   * Intercept 'bumba new' command
   */
  interceptNewCommand() {
    const originalNew = global.bumbaCommands?.new;

    if (originalNew) {
      global.bumbaCommands.new = async (...args) => {
        // Execute original command
        const result = await originalNew(...args);

        // Extract project info
        const projectName = args[0] || 'unnamed-project';
        const projectPath = args[1] || process.cwd();

        // Auto-create catalog
        await this.createCatalogForProject(projectName, projectPath);

        return result;
      };
    }
  }

  /**
   * Intercept 'bumba init' command
   */
  interceptInitCommand() {
    const originalInit = global.bumbaCommands?.init;

    if (originalInit) {
      global.bumbaCommands.init = async (...args) => {
        // Execute original command
        const result = await originalInit(...args);

        // Get project info from current directory
        const projectPath = process.cwd();
        const projectName = path.basename(projectPath);

        // Check if catalog exists
        const catalogPath = path.join(projectPath, '.design-catalog');
        try {
          await fs.access(catalogPath);
          console.log(chalk.yellow('📁 Design System Catalog already exists'));
        } catch {
          // Create new catalog
          await this.createCatalogForProject(projectName, projectPath);
        }

        return result;
      };
    }
  }

  /**
   * Intercept design commands
   */
  interceptDesignCommands() {
    const originalDesign = global.bumbaCommands?.design;

    if (originalDesign) {
      global.bumbaCommands.design = async (action, ...args) => {
        // Execute original command
        const result = await originalDesign(action, ...args);

        // Handle specific design actions
        switch (action) {
          case 'extract':
            await this.handleDesignExtract(result, args);
            break;

          case 'generate':
            await this.handleDesignGenerate(result, args);
            break;

          case 'analyze':
            await this.handleDesignAnalyze(result, args);
            break;

          case 'export':
            await this.handleDesignExport(result, args);
            break;
        }

        return result;
      };
    }
  }

  /**
   * Create catalog for new project
   */
  async createCatalogForProject(projectName, projectPath) {
    console.log(chalk.cyan('🎨 Auto-generating Design System Catalog...'));

    try {
      // Create catalog through orchestrator
      const catalog = await this.orchestrator.createProjectCatalog(projectName, projectPath);

      // Setup initial templates
      await this.setupInitialTemplates(catalog, projectPath);

      // Create starter components
      await this.createStarterComponents(catalog);

      // Setup AI context
      await this.setupAIContext(catalog, projectPath);

      // Generate initial documentation
      await this.generateInitialDocs(catalog, projectPath);

      console.log(chalk.green('✅ Design System Catalog ready'));
      console.log(chalk.gray('   • Visual catalog at: .design-catalog/index.html'));
      console.log(chalk.gray('   • AI API available via catalog.getAIAPI()'));
      console.log(chalk.gray('   • Sandbox ready for component iteration'));

    } catch (error) {
      logger.error('Failed to create catalog:', error);
      console.error(chalk.red('❌ Failed to create Design System Catalog'));
    }
  }

  /**
   * Setup initial templates
   */
  async setupInitialTemplates(catalog, projectPath) {
    const templatesPath = path.join(projectPath, '.design-catalog', 'templates');
    await fs.mkdir(templatesPath, { recursive: true });

    // Create base component template
    const componentTemplate = `/**
 * Component: {{NAME}}
 * Category: {{CATEGORY}}
 * Created: {{DATE}}
 */

import React from 'react';
import './{{NAME}}.css';

export interface {{NAME}}Props {
  // Component props
}

export const {{NAME}}: React.FC<{{NAME}}Props> = (props) => {
  return (
    <div className="{{kebab-name}}">
      {props.children}
    </div>
  );
};

export default {{NAME}};`;

    await fs.writeFile(
      path.join(templatesPath, 'component.template'),
      componentTemplate
    );

    // Create style template
    const styleTemplate = `.{{kebab-name}} {
  /* Component styles */
  display: flex;
  padding: var(--spacing-md);
  background: var(--color-surface);
  border-radius: var(--radius-md);
}`;

    await fs.writeFile(
      path.join(templatesPath, 'style.template'),
      styleTemplate
    );
  }

  /**
   * Create starter components
   */
  async createStarterComponents(catalog) {
    // Register basic button component
    await this.orchestrator.registerDesignAsset({
      type: 'atom',
      name: 'Button',
      source: 'starter-kit',
      properties: {
        variant: 'primary',
        size: 'medium',
        disabled: false,
        onClick: 'function'
      },
      metadata: {
        category: 'atoms',
        description: 'Basic button component',
        accessibility: 'WCAG 2.1 AA compliant'
      }
    });

    // Register card component
    await this.orchestrator.registerDesignAsset({
      type: 'molecule',
      name: 'Card',
      source: 'starter-kit',
      properties: {
        title: 'string',
        description: 'string',
        image: 'string',
        actions: 'array'
      },
      metadata: {
        category: 'molecules',
        description: 'Card component for content display',
        complexity: 'medium'
      }
    });

    // Register layout component
    await this.orchestrator.registerDesignAsset({
      type: 'organism',
      name: 'Layout',
      source: 'starter-kit',
      properties: {
        header: 'component',
        sidebar: 'component',
        main: 'component',
        footer: 'component'
      },
      metadata: {
        category: 'organisms',
        description: 'Main layout component',
        complexity: 'high'
      }
    });
  }

  /**
   * Setup AI context for catalog
   */
  async setupAIContext(catalog, projectPath) {
    // Read package.json for project info
    let projectInfo = {};
    try {
      const packagePath = path.join(projectPath, 'package.json');
      const packageContent = await fs.readFile(packagePath, 'utf8');
      projectInfo = JSON.parse(packageContent);
    } catch {
      // No package.json found
    }

    // Update catalog AI context
    catalog.aiContext = {
      ...catalog.aiContext,
      projectInfo: {
        name: projectInfo.name || catalog.projectName,
        version: projectInfo.version || '1.0.0',
        description: projectInfo.description || '',
        dependencies: projectInfo.dependencies || {},
        framework: this.detectFramework(projectInfo)
      },
      designPrinciples: [
        'Consistency across all components',
        'Accessibility first approach',
        'Performance optimized',
        'Mobile responsive',
        'Dark mode support'
      ],
      brandGuidelines: {
        primaryColor: '#00AA00',
        secondaryColor: '#FFDD00',
        accentColor: '#DD0000',
        fontFamily: 'iA Writer Duo, monospace',
        borderRadius: '8px',
        spacing: '8px grid system'
      },
      componentPatterns: {
        atoms: [],
        molecules: [],
        organisms: []
      },
      accessibilityRules: {
        wcagLevel: 'AA',
        colorContrast: 4.5,
        focusIndicators: true,
        ariaLabels: true,
        keyboardNavigation: true
      },
      performanceTargets: {
        firstPaint: 1000,
        interactiveTime: 3000,
        bundleSize: 200000,
        componentRenderTime: 16
      }
    };
  }

  /**
   * Generate initial documentation
   */
  async generateInitialDocs(catalog, projectPath) {
    const docsPath = path.join(projectPath, '.design-catalog', 'docs');
    await fs.mkdir(docsPath, { recursive: true });

    // Create README
    const readme = `# Design System Catalog

## Project: ${catalog.projectName}

This Design System Catalog serves as the single source of truth for all design assets and their code implementations.

### Features

- **Auto-generation**: Components are automatically cataloged when created
- **Bidirectional Sync**: Changes in design update code and vice versa
- **AI-Friendly API**: Provides structured access for AI collaborators
- **Visual Sandbox**: Test and iterate on components in isolation
- **Real-time Collaboration**: Multiple contributors can work simultaneously

### Getting Started

1. **View Catalog**: Open \`.design-catalog/index.html\` in your browser
2. **Create Components**: Use \`bumba design create <component>\`
3. **Access AI API**: \`catalog.getAIAPI()\` in your code
4. **Launch Sandbox**: \`bumba design sandbox <component>\`

### Structure

\`\`\`
.design-catalog/
├── catalog.json        # Catalog manifest
├── index.html          # Visual catalog
├── components/         # Component library
├── templates/          # Component templates
├── sandbox/           # Sandbox environments
└── docs/              # Documentation
\`\`\`

### AI Collaboration

The catalog provides an AI-friendly API for querying and managing components:

\`\`\`javascript
const catalog = require('.design-catalog/api');

// Query components
const buttons = await catalog.query({ type: 'button' });

// Register new component
await catalog.register({
  type: 'atom',
  name: 'CustomButton',
  properties: { ... }
});

// Generate implementations
const code = await catalog.generate('CustomButton', 'react');
\`\`\`

### Contributing

Both human and AI contributors can:
1. Add new design assets
2. Generate code implementations
3. Update existing components
4. Test in sandbox environment
5. Review and validate changes

---

Generated by BUMBA CLI v1.0
`;

    await fs.writeFile(path.join(docsPath, 'README.md'), readme);

    // Create API documentation
    const apiDocs = `# Design System Catalog API

## AI Interface

The catalog provides a comprehensive API for AI collaborators:

### Query Methods

\`\`\`javascript
// Search for components
catalog.query({ type: 'button', framework: 'react' });

// Full-text search
catalog.search('primary button with icon');
\`\`\`

### Registration Methods

\`\`\`javascript
// Register design asset
catalog.register({
  type: 'molecule',
  name: 'SearchBar',
  properties: { ... }
});

// Update component
catalog.update('componentId', { ... });
\`\`\`

### Generation Methods

\`\`\`javascript
// Generate code from design
catalog.generate(assetData);

// Get suggestions
catalog.suggest({ intent: 'form-input' });
\`\`\`

### Analysis Methods

\`\`\`javascript
// Analyze usage
catalog.analyze('Button');

// Validate component
catalog.validate('componentId');
\`\`\`

### Context Methods

\`\`\`javascript
// Get AI context
catalog.getContext();

// Update context
catalog.updateContext({ ... });
\`\`\`
`;

    await fs.writeFile(path.join(docsPath, 'API.md'), apiDocs);
  }

  /**
   * Watch for project initialization
   */
  watchProjectInit() {
    // Monitor current directory for new projects
    const checkForNewProject = async () => {
      const cwd = process.cwd();
      const catalogPath = path.join(cwd, '.design-catalog');

      try {
        await fs.access(catalogPath);
      } catch {
        // Check if this is a new project
        try {
          await fs.access(path.join(cwd, 'package.json'));
          // Has package.json but no catalog - create one
          const projectName = path.basename(cwd);
          await this.createCatalogForProject(projectName, cwd);
        } catch {
          // Not a project directory
        }
      }
    };

    // Check periodically
    setInterval(checkForNewProject, 10000); // Every 10 seconds
  }

  /**
   * Setup design file watchers
   */
  setupDesignFileWatchers() {
    // Watch for .fig, .sketch, .xd files
    // In real implementation, would use chokidar or similar
    logger.debug('Design file watchers configured');
  }

  /**
   * Handle design extract command
   */
  async handleDesignExtract(result, args) {
    if (result && result.tokens) {
      // Register extracted tokens in catalog
      for (const [category, tokens] of Object.entries(result.tokens)) {
        for (const [name, value] of Object.entries(tokens)) {
          await this.orchestrator.registerDesignAsset({
            type: 'token',
            name: `${category}-${name}`,
            source: 'figma-extract',
            properties: { value },
            metadata: { category }
          });
        }
      }
    }
  }

  /**
   * Handle design generate command
   */
  async handleDesignGenerate(result, args) {
    if (result && result.components) {
      // Register generated components
      for (const component of result.components) {
        await this.orchestrator.registerDesignAsset({
          type: 'generated',
          name: component.name,
          source: 'ai-generation',
          properties: component.props || {},
          metadata: component.metadata || {}
        });
      }
    }
  }

  /**
   * Handle design analyze command
   */
  async handleDesignAnalyze(result, args) {
    // Update catalog with analysis results
    if (result && result.analysis) {
      const catalog = this.orchestrator.catalogs.get(this.orchestrator.activeProject);
      if (catalog) {
        catalog.aiContext.analysisResults = result.analysis;
      }
    }
  }

  /**
   * Handle design export command
   */
  async handleDesignExport(result, args) {
    // Track exported assets
    if (result && result.exported) {
      logger.info(`Exported ${result.exported.length} design assets`);
    }
  }

  /**
   * Detect project framework
   */
  detectFramework(packageInfo) {
    const deps = { ...packageInfo.dependencies, ...packageInfo.devDependencies };

    if (deps.react) return 'react';
    if (deps.vue) return 'vue';
    if (deps.angular || deps['@angular/core']) return 'angular';
    if (deps.svelte) return 'svelte';
    if (deps.next) return 'nextjs';
    if (deps.nuxt) return 'nuxt';

    return 'vanilla';
  }
}

// Singleton instance
let instance = null;

module.exports = {
  ProjectHooks,
  getInstance: () => {
    if (!instance) {
      instance = new ProjectHooks();
    }
    return instance;
  },
  initialize: async () => {
    const hooks = module.exports.getInstance();
    await hooks.initialize();
  }
};