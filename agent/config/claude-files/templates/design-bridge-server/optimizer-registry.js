/**
 * Optimizer Registry
 * Sprint 28: Generator-Optimizer Pipeline
 *
 * Central registry for all framework optimizers
 * Connects SmartCodeGenerator to framework-specific optimizers
 */

// Lazy load optimizers to avoid circular dependencies
let ReactOptimizer, VueOptimizer, SvelteOptimizer, AngularOptimizer, WebComponentsOptimizer;
let ReactNativeOptimizer, FlutterOptimizer, SwiftUIOptimizer, JetpackComposeOptimizer;
let NextOptimizer;

class OptimizerRegistry {
  constructor() {
    this.optimizers = new Map();
    this.initialized = false;
  }

  /**
   * Initialize all framework optimizers
   */
  initialize() {
    if (this.initialized) {
      return this.optimizers;
    }

    // Register all framework optimizers
    this.registerFrameworkOptimizers();

    this.initialized = true;
    console.log(`✓ Optimizer Registry initialized with ${this.optimizers.size} optimizers`);

    return this.optimizers;
  }

  /**
   * Register all framework optimizers
   */
  registerFrameworkOptimizers() {
    // Lazy load optimizer classes to avoid circular dependencies
    if (!ReactOptimizer) {
      // Web frameworks
      ReactOptimizer = require('./react-optimizer');
      VueOptimizer = require('./vue-optimizer');
      SvelteOptimizer = require('./svelte-optimizer');
      AngularOptimizer = require('./angular-optimizer');
      WebComponentsOptimizer = require('./web-components-optimizer');

      // Mobile frameworks
      ReactNativeOptimizer = require('./react-native-optimizer');
      FlutterOptimizer = require('./flutter-optimizer');
      SwiftUIOptimizer = require('./swiftui-optimizer');
      JetpackComposeOptimizer = require('./jetpack-compose-optimizer');

      // Next.js framework
      NextOptimizer = require('./next-optimizer');
    }

    // React
    const reactOptimizer = new ReactOptimizer();
    this.optimizers.set('react', reactOptimizer);

    // Vue
    const vueOptimizer = new VueOptimizer();
    this.optimizers.set('vue', vueOptimizer);

    // Svelte
    const svelteOptimizer = new SvelteOptimizer();
    this.optimizers.set('svelte', svelteOptimizer);

    // Angular
    const angularOptimizer = new AngularOptimizer();
    this.optimizers.set('angular', angularOptimizer);

    // Web Components
    const webComponentsOptimizer = new WebComponentsOptimizer();
    this.optimizers.set('web-components', webComponentsOptimizer);
    this.optimizers.set('webcomponents', webComponentsOptimizer); // Alias

    // React Native
    const reactNativeOptimizer = new ReactNativeOptimizer();
    this.optimizers.set('react-native', reactNativeOptimizer);
    this.optimizers.set('reactnative', reactNativeOptimizer); // Alias

    // Flutter
    const flutterOptimizer = new FlutterOptimizer();
    this.optimizers.set('flutter', flutterOptimizer);

    // SwiftUI
    const swiftUIOptimizer = new SwiftUIOptimizer();
    this.optimizers.set('swiftui', swiftUIOptimizer);
    this.optimizers.set('swift-ui', swiftUIOptimizer); // Alias with hyphen
    this.optimizers.set('swift', swiftUIOptimizer); // Short alias

    // Jetpack Compose
    const jetpackComposeOptimizer = new JetpackComposeOptimizer();
    this.optimizers.set('jetpack-compose', jetpackComposeOptimizer);
    this.optimizers.set('jetpackcompose', jetpackComposeOptimizer); // No hyphen alias
    this.optimizers.set('compose', jetpackComposeOptimizer); // Short alias
    this.optimizers.set('android', jetpackComposeOptimizer); // Platform alias

    // Next.js
    const nextOptimizer = new NextOptimizer();
    this.optimizers.set('nextjs', nextOptimizer);
    this.optimizers.set('next', nextOptimizer); // Short alias
    this.optimizers.set('next.js', nextOptimizer); // Dot notation alias
  }

  /**
   * Get optimizer for specific framework
   */
  getOptimizer(framework) {
    const normalizedFramework = framework.toLowerCase();

    if (!this.optimizers.has(normalizedFramework)) {
      console.warn(`Optimizer not found for framework: ${framework}. Using React as fallback.`);
      return this.optimizers.get('react');
    }

    return this.optimizers.get(normalizedFramework);
  }

  /**
   * Get all available optimizers
   */
  getAllOptimizers() {
    return Array.from(this.optimizers.entries()).map(([framework, optimizer]) => ({
      framework,
      name: optimizer.name,
      version: optimizer.version
    }));
  }

  /**
   * Check if framework is supported
   */
  isSupported(framework) {
    return this.optimizers.has(framework.toLowerCase());
  }

  /**
   * Get supported frameworks list
   */
  getSupportedFrameworks() {
    return Array.from(this.optimizers.keys());
  }

  /**
   * Register custom optimizer
   */
  registerCustomOptimizer(framework, optimizer) {
    const normalizedFramework = framework.toLowerCase();

    // Validate optimizer has required methods
    if (!optimizer.optimize || typeof optimizer.optimize !== 'function') {
      throw new Error(`Invalid optimizer: ${framework}. Must have optimize() method.`);
    }

    this.optimizers.set(normalizedFramework, optimizer);
    console.log(`✓ Custom optimizer registered: ${framework}`);

    return true;
  }

  /**
   * Optimize code for specific framework
   */
  async optimizeCode(framework, code, componentData, config) {
    const optimizer = this.getOptimizer(framework);

    if (!optimizer) {
      throw new Error(`No optimizer available for framework: ${framework}`);
    }

    try {
      const optimizedCode = await optimizer.optimize(code, componentData, config);
      return optimizedCode;
    } catch (error) {
      console.error(`Optimization failed for ${framework}:`, error);
      throw error;
    }
  }

  /**
   * Run optimization pipeline
   * Extract → Generate → Optimize → Export
   */
  async runPipeline(designComponent, targetFramework, options = {}) {
    const config = {
      framework: targetFramework,
      ...options
    };

    // Get appropriate optimizer
    const optimizer = this.getOptimizer(targetFramework);

    if (!optimizer) {
      throw new Error(`Pipeline failed: No optimizer for ${targetFramework}`);
    }

    const pipeline = {
      framework: targetFramework,
      steps: [],
      result: null
    };

    try {
      // Step 1: Extract component data
      pipeline.steps.push({ step: 'extract', status: 'running' });
      const extracted = this.extractComponentData(designComponent);
      pipeline.steps[0].status = 'completed';

      // Step 2: Generate base code
      pipeline.steps.push({ step: 'generate', status: 'running' });
      const generated = await optimizer.generateComponent(extracted, config);
      pipeline.steps[1].status = 'completed';

      // Step 3: Optimize code
      pipeline.steps.push({ step: 'optimize', status: 'running' });
      const optimized = await optimizer.optimize(generated, extracted, config);
      pipeline.steps[2].status = 'completed';

      // Step 4: Export code
      pipeline.steps.push({ step: 'export', status: 'running' });
      const exported = this.exportCode(optimized, config);
      pipeline.steps[3].status = 'completed';

      pipeline.result = exported;
      pipeline.status = 'success';

      return pipeline;

    } catch (error) {
      pipeline.status = 'failed';
      pipeline.error = {
        message: error.message,
        step: pipeline.steps.findIndex(s => s.status === 'running')
      };

      throw error;
    }
  }

  /**
   * Extract component data (placeholder - will use actual extractor)
   */
  extractComponentData(designComponent) {
    // This would normally use the token-extractor
    return {
      id: designComponent.id || `component_${Date.now()}`,
      name: designComponent.name || 'Component',
      type: designComponent.type || 'component',
      props: designComponent.props || {},
      state: designComponent.state || {},
      variants: designComponent.variants || [],
      styles: designComponent.styles || {},
      children: designComponent.children || []
    };
  }

  /**
   * Export code (placeholder - will use actual exporter)
   */
  exportCode(code, config) {
    // This would normally use export-formatters
    return {
      code,
      format: config.framework,
      timestamp: new Date().toISOString()
    };
  }

  /**
   * Get registry statistics
   */
  getStats() {
    return {
      totalOptimizers: this.optimizers.size,
      frameworks: this.getSupportedFrameworks(),
      initialized: this.initialized
    };
  }
}

// Singleton instance
let registryInstance = null;

function getOptimizerRegistry() {
  if (!registryInstance) {
    registryInstance = new OptimizerRegistry();
    registryInstance.initialize();
  }
  return registryInstance;
}

// Export pattern that works with circular dependencies
module.exports.OptimizerRegistry = OptimizerRegistry;
module.exports.getOptimizerRegistry = getOptimizerRegistry;
module.exports.default = OptimizerRegistry;
