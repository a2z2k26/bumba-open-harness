/**
 * Multi-Framework Generator
 * Sprint 29: Enable parallel framework generation
 *
 * Generates code for multiple frameworks simultaneously
 */

const EventEmitter = require('events');
const { getOptimizerRegistry } = require('./optimizer-registry');
const { StoryGenerator } = require('./story-generator');
const { updateStoryRegistry, getStoryRegistry, storyExists } = require('./story-registry');

class MultiFrameworkGenerator extends EventEmitter {
  constructor(config = {}) {
    super();
    this.optimizerRegistry = getOptimizerRegistry();
    this.generationQueue = new Map();
    this.results = new Map();

    // Story generation integration (Sprint 3.2)
    this.storyGenerator = new StoryGenerator(config);
    this.projectPath = config.projectPath || process.cwd();
    this.generateStories = config.generateStories !== false; // Default true
    this.pendingStories = []; // Collect stories for batch registry update
  }

  /**
   * Generate code for multiple frameworks in parallel
   */
  async generateForFrameworks(designComponent, frameworks, options = {}) {
    const generationId = `multi_${Date.now()}`;

    this.emit('generation:started', {
      id: generationId,
      frameworks,
      component: designComponent.name
    });

    try {
      // Generate for all frameworks in parallel
      const generationPromises = frameworks.map(framework =>
        this.generateForFramework(designComponent, framework, options)
          .then(result => ({ framework, result, success: true }))
          .catch(error => ({ framework, error, success: false }))
      );

      const results = await Promise.all(generationPromises);

      // Organize results by framework
      const organized = {
        id: generationId,
        component: designComponent.name,
        frameworks: {},
        successful: [],
        failed: [],
        timestamp: new Date().toISOString()
      };

      results.forEach(({ framework, result, error, success }) => {
        if (success) {
          organized.frameworks[framework] = result;
          organized.successful.push(framework);
        } else {
          organized.frameworks[framework] = { error: error.message };
          organized.failed.push(framework);
        }
      });

      // Store results
      this.results.set(generationId, organized);

      this.emit('generation:completed', organized);

      return organized;

    } catch (error) {
      this.emit('generation:failed', { id: generationId, error });
      throw error;
    }
  }

  /**
   * Generate code for a single framework
   * @param {Object} designComponent - Component design data
   * @param {string} framework - Target framework
   * @param {Object} options - Generation options
   * @param {boolean} options.generateStories - Generate story files (default: this.generateStories)
   */
  async generateForFramework(designComponent, framework, options = {}) {
    const optimizer = this.optimizerRegistry.getOptimizer(framework);

    if (!optimizer) {
      throw new Error(`No optimizer found for framework: ${framework}`);
    }

    // Run the optimizer pipeline
    const result = await this.optimizerRegistry.runPipeline(
      designComponent,
      framework,
      options
    );

    // Story generation (Sprint 3.4)
    const shouldGenerateStories = options.generateStories ?? this.generateStories;
    if (shouldGenerateStories) {
      try {
        const storyContent = this.storyGenerator.generateStoryFile(designComponent, framework);
        if (storyContent) {
          result.story = {
            content: storyContent,
            framework,
            extension: this.storyGenerator.getStoryExtension(framework)
          };

          // Register story (Sprint 3.6)
          this.pendingStories.push({
            component: designComponent.name,
            framework,
            path: `${designComponent.name}${result.story.extension}`,
            generatedAt: new Date().toISOString(),
            variants: ['Default'],
            hasProps: Object.keys(designComponent.props || {}).length > 0,
            propsCount: Object.keys(designComponent.props || {}).length
          });

          this.emit('story:generated', {
            component: designComponent.name,
            framework
          });
        }
      } catch (storyError) {
        // Log but don't fail generation if story fails
        this.emit('story:failed', {
          component: designComponent.name,
          framework,
          error: storyError.message
        });
        result.storyError = storyError.message;
      }
    }

    return result;
  }

  /**
   * Generate for all supported frameworks
   */
  async generateForAllFrameworks(designComponent, options = {}) {
    const frameworks = this.optimizerRegistry.getSupportedFrameworks();
    return this.generateForFrameworks(designComponent, frameworks, options);
  }

  /**
   * Generate with framework comparison
   */
  async generateWithComparison(designComponent, frameworks, options = {}) {
    const results = await this.generateForFrameworks(designComponent, frameworks, options);

    // Add comparison metrics
    const comparison = {
      ...results,
      comparison: this.compareFrameworkOutputs(results.frameworks)
    };

    return comparison;
  }

  /**
   * Compare outputs across frameworks
   */
  compareFrameworkOutputs(frameworkResults) {
    const comparison = {
      codeSize: {},
      complexity: {},
      fileCount: {}
    };

    Object.entries(frameworkResults).forEach(([framework, result]) => {
      if (result.result) {
        comparison.codeSize[framework] = result.result.code?.length || 0;
        comparison.fileCount[framework] = Object.keys(result.result.files || {}).length;
      }
    });

    return comparison;
  }

  /**
   * Batch generate for multiple components and frameworks
   */
  async batchGenerate(components, frameworks, options = {}) {
    const batchId = `batch_${Date.now()}`;

    this.emit('batch:started', {
      id: batchId,
      components: components.length,
      frameworks: frameworks.length
    });

    const batchResults = [];

    for (const component of components) {
      const result = await this.generateForFrameworks(component, frameworks, options);
      batchResults.push(result);
    }

    this.emit('batch:completed', {
      id: batchId,
      results: batchResults.length
    });

    return {
      id: batchId,
      results: batchResults,
      summary: {
        totalComponents: components.length,
        totalFrameworks: frameworks.length,
        totalGenerations: components.length * frameworks.length
      }
    };
  }

  /**
   * Get generation results
   */
  getResults(generationId) {
    return this.results.get(generationId);
  }

  /**
   * Get supported frameworks
   */
  getSupportedFrameworks() {
    return this.optimizerRegistry.getSupportedFrameworks();
  }

  /**
   * Check if framework is supported
   */
  isFrameworkSupported(framework) {
    return this.optimizerRegistry.isSupported(framework);
  }

  /**
   * Store generated code by framework
   */
  async storeByFramework(generationId, outputDir) {
    const results = this.results.get(generationId);

    if (!results) {
      throw new Error(`No results found for generation: ${generationId}`);
    }

    const fs = require('fs').promises;
    const path = require('path');

    const stored = {};

    for (const [framework, result] of Object.entries(results.frameworks)) {
      if (result.result) {
        const frameworkDir = path.join(outputDir, framework);
        await fs.mkdir(frameworkDir, { recursive: true });

        // Store main component file
        const componentFile = path.join(frameworkDir, `${results.component}.${this.getFileExtension(framework)}`);
        await fs.writeFile(componentFile, result.result.code || '');

        // Store supporting files
        if (result.result.files) {
          for (const [fileName, content] of Object.entries(result.result.files)) {
            const filePath = path.join(frameworkDir, fileName);
            await fs.writeFile(filePath, content);
          }
        }

        // Store story file if generated (Sprint 3.5)
        if (result.result.story && result.result.story.content) {
          const storyExtension = result.result.story.extension || this.storyGenerator.getStoryExtension(framework);
          const storyFile = path.join(frameworkDir, `${results.component}${storyExtension}`);
          await fs.writeFile(storyFile, result.result.story.content);

          this.emit('story:written', {
            component: results.component,
            framework,
            path: storyFile
          });
        }

        stored[framework] = frameworkDir;
      }
    }

    return stored;
  }

  /**
   * Get file extension for framework
   */
  getFileExtension(framework) {
    const extensions = {
      // Web frameworks
      react: 'tsx',
      vue: 'vue',
      svelte: 'svelte',
      angular: 'component.ts',
      'web-components': 'js',
      // Mobile frameworks
      'react-native': 'tsx',
      flutter: 'dart',
      swiftui: 'swift',
      'jetpack-compose': 'kt'
    };

    return extensions[framework] || 'js';
  }

  /**
   * Generate framework selection UI data
   */
  getFrameworkSelectionData() {
    const frameworks = this.getSupportedFrameworks();

    return frameworks.map(framework => {
      const optimizer = this.optimizerRegistry.getOptimizer(framework);

      return {
        id: framework,
        name: framework.charAt(0).toUpperCase() + framework.slice(1),
        version: optimizer.version || 'unknown',
        supported: true,
        features: this.getFrameworkFeatures(framework)
      };
    });
  }

  /**
   * Get framework-specific features
   */
  getFrameworkFeatures(framework) {
    const optimizer = this.optimizerRegistry.getOptimizer(framework);

    return {
      typescript: optimizer.config?.useTypeScript !== false,
      hooks: optimizer.config?.useHooks || false,
      composition: framework === 'vue' ? true : false,
      stores: framework === 'svelte' ? true : false
    };
  }

  /**
   * Performance benchmark across frameworks
   */
  async benchmarkFrameworks(designComponent, options = {}) {
    const frameworks = this.getSupportedFrameworks();
    const benchmarks = {};

    for (const framework of frameworks) {
      const startTime = Date.now();

      try {
        await this.generateForFramework(designComponent, framework, options);
        const endTime = Date.now();

        benchmarks[framework] = {
          duration: endTime - startTime,
          success: true
        };
      } catch (error) {
        benchmarks[framework] = {
          duration: null,
          success: false,
          error: error.message
        };
      }
    }

    return {
      component: designComponent.name,
      benchmarks,
      fastest: this.findFastest(benchmarks),
      slowest: this.findSlowest(benchmarks)
    };
  }

  /**
   * Find fastest framework
   */
  findFastest(benchmarks) {
    let fastest = null;
    let minDuration = Infinity;

    Object.entries(benchmarks).forEach(([framework, data]) => {
      if (data.success && data.duration < minDuration) {
        minDuration = data.duration;
        fastest = framework;
      }
    });

    return { framework: fastest, duration: minDuration };
  }

  /**
   * Find slowest framework
   */
  findSlowest(benchmarks) {
    let slowest = null;
    let maxDuration = 0;

    Object.entries(benchmarks).forEach(([framework, data]) => {
      if (data.success && data.duration > maxDuration) {
        maxDuration = data.duration;
        slowest = framework;
      }
    });

    return { framework: slowest, duration: maxDuration };
  }

  /**
   * Load configuration from .design/config.json (Sprint 3.7)
   * @param {string} projectPath - Path to project root
   * @returns {Object} Configuration object
   */
  static loadConfig(projectPath = process.cwd()) {
    const fs = require('fs');
    const path = require('path');

    const configPath = path.join(projectPath, '.design', 'config.json');

    if (!fs.existsSync(configPath)) {
      return { generateStories: true }; // Default
    }

    try {
      const configContent = fs.readFileSync(configPath, 'utf8');
      const config = JSON.parse(configContent);

      return {
        generateStories: config.stories?.enabled !== false,
        storyFormat: config.stories?.format || 'default',
        storyOutput: config.stories?.outputDir || 'stories',
        frameworks: config.frameworks || [],
        ...config
      };
    } catch (error) {
      console.warn(`Failed to load config from ${configPath}:`, error.message);
      return { generateStories: true };
    }
  }

  /**
   * Create instance with project config (Sprint 3.7)
   * @param {string} projectPath - Path to project root
   * @returns {MultiFrameworkGenerator} Configured instance
   */
  static createWithConfig(projectPath = process.cwd()) {
    const config = MultiFrameworkGenerator.loadConfig(projectPath);
    return new MultiFrameworkGenerator(config);
  }

  /**
   * Get story generation status
   * @returns {Object} Story generation configuration
   */
  getStoryConfig() {
    return {
      enabled: this.generateStories,
      generator: this.storyGenerator ? 'StoryGenerator' : null,
      projectPath: this.projectPath,
      pendingStories: this.pendingStories.length,
      supportedFrameworks: this.storyGenerator?.getSupportedFrameworks() || []
    };
  }

  /**
   * Flush pending stories to registry (Sprint 3.6)
   * @returns {Object|null} Updated registry or null
   */
  flushStoriesToRegistry() {
    if (this.pendingStories.length === 0) {
      return null;
    }

    try {
      const registry = updateStoryRegistry(this.projectPath, this.pendingStories);
      const flushedCount = this.pendingStories.length;
      this.pendingStories = [];

      this.emit('registry:updated', {
        storiesAdded: flushedCount,
        projectPath: this.projectPath
      });

      return registry;
    } catch (error) {
      this.emit('registry:error', {
        error: error.message,
        projectPath: this.projectPath
      });
      return null;
    }
  }

  /**
   * Check if story exists for component
   * @param {string} componentName - Component name
   * @returns {boolean} Whether story exists
   */
  hasStory(componentName) {
    return storyExists(this.projectPath, componentName);
  }

  /**
   * Get current story registry
   * @returns {Object|null} Registry or null
   */
  getRegistry() {
    return getStoryRegistry(this.projectPath);
  }
}

module.exports = MultiFrameworkGenerator;
