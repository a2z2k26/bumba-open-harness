/**
 * Graceful Degradation System
 *
 * Provides fallback mechanisms for handling transformation failures.
 * When primary transformations fail, the system automatically falls back
 * to simpler, more reliable alternatives.
 *
 * Key Principle: Make failures observable and recoverable, not silent and destructive.
 *
 * @module graceful-degradation
 */

'use strict';

// =============================================================================
// FALLBACK REGISTRY
// =============================================================================

/**
 * Fallback levels from most preferred to least
 */
const FALLBACK_LEVELS = {
  FULL: 'full',           // Full transformation with all features
  SIMPLIFIED: 'simplified', // Simplified transformation with core features
  BASIC: 'basic',         // Basic transformation with minimal features
  MINIMAL: 'minimal',     // Minimal output, structure only
  PLACEHOLDER: 'placeholder', // Placeholder content
  NONE: 'none'            // No transformation possible
};

/**
 * Fallback categories for different aspects of transformation
 */
const FALLBACK_CATEGORIES = {
  LAYOUT: 'layout',
  STYLING: 'styling',
  COMPONENT: 'component',
  INTERACTION: 'interaction',
  CONTENT: 'content',
  ASSET: 'asset',
  ANIMATION: 'animation'
};

/**
 * Framework-specific fallback strategies
 */
const FRAMEWORK_FALLBACKS = {
  react: {
    component: {
      full: (node) => `<${node.componentName} {...props} />`,
      simplified: (node) => `<${node.componentName} />`,
      basic: (node) => `<div className="${node.className}">{/* ${node.name} */}</div>`,
      minimal: (node) => `<div>{/* ${node.name} */}</div>`,
      placeholder: (node) => `{/* TODO: Implement ${node.name} */}`
    },
    layout: {
      full: (node) => ({ display: 'flex', ...node.layout }),
      simplified: (node) => ({ display: 'flex', flexDirection: node.layout?.direction || 'column' }),
      basic: (node) => ({ display: 'block' }),
      minimal: () => ({}),
      placeholder: () => ({})
    },
    styling: {
      full: (node) => node.styles,
      simplified: (node) => ({
        width: node.styles?.width,
        height: node.styles?.height,
        backgroundColor: node.styles?.backgroundColor
      }),
      basic: (node) => ({ width: '100%' }),
      minimal: () => ({}),
      placeholder: () => ({})
    }
  },

  vue: {
    component: {
      full: (node) => `<${node.componentName} v-bind="props" />`,
      simplified: (node) => `<${node.componentName} />`,
      basic: (node) => `<div :class="'${node.className}'"><!-- ${node.name} --></div>`,
      minimal: (node) => `<div><!-- ${node.name} --></div>`,
      placeholder: (node) => `<!-- TODO: Implement ${node.name} -->`
    },
    layout: {
      full: (node) => ({ display: 'flex', ...node.layout }),
      simplified: (node) => ({ display: 'flex', flexDirection: node.layout?.direction || 'column' }),
      basic: (node) => ({ display: 'block' }),
      minimal: () => ({}),
      placeholder: () => ({})
    }
  },

  svelte: {
    component: {
      full: (node) => `<${node.componentName} {...$$restProps} />`,
      simplified: (node) => `<${node.componentName} />`,
      basic: (node) => `<div class="${node.className}"><!-- ${node.name} --></div>`,
      minimal: (node) => `<div><!-- ${node.name} --></div>`,
      placeholder: (node) => `<!-- TODO: Implement ${node.name} -->`
    }
  },

  angular: {
    component: {
      full: (node) => `<app-${node.componentName} [data]="data"></app-${node.componentName}>`,
      simplified: (node) => `<app-${node.componentName}></app-${node.componentName}>`,
      basic: (node) => `<div class="${node.className}"><!-- ${node.name} --></div>`,
      minimal: (node) => `<div><!-- ${node.name} --></div>`,
      placeholder: (node) => `<!-- TODO: Implement ${node.name} -->`
    }
  },

  'react-native': {
    component: {
      full: (node) => `<${node.componentName} {...props} />`,
      simplified: (node) => `<${node.componentName} />`,
      basic: (node) => `<View style={styles.${node.styleName}}>{/* ${node.name} */}</View>`,
      minimal: (node) => `<View>{/* ${node.name} */}</View>`,
      placeholder: (node) => `{/* TODO: Implement ${node.name} */}`
    },
    layout: {
      full: (node) => ({ flex: 1, ...node.layout }),
      simplified: (node) => ({ flex: 1, flexDirection: node.layout?.direction || 'column' }),
      basic: () => ({ flex: 1 }),
      minimal: () => ({}),
      placeholder: () => ({})
    }
  },

  flutter: {
    component: {
      full: (node) => `${node.componentName}(${node.propsString})`,
      simplified: (node) => `${node.componentName}()`,
      basic: (node) => `Container(child: /* ${node.name} */)`,
      minimal: (node) => `Container()`,
      placeholder: (node) => `// TODO: Implement ${node.name}`
    },
    layout: {
      full: (node) => `Column(children: [${node.children}])`,
      simplified: (node) => `Column(children: [])`,
      basic: () => `Container()`,
      minimal: () => `SizedBox()`,
      placeholder: () => `// Layout placeholder`
    }
  },

  swiftui: {
    component: {
      full: (node) => `${node.componentName}(${node.propsString})`,
      simplified: (node) => `${node.componentName}()`,
      basic: (node) => `// ${node.name}\nEmptyView()`,
      minimal: () => `EmptyView()`,
      placeholder: (node) => `// TODO: Implement ${node.name}`
    },
    layout: {
      full: (node) => `VStack { ${node.children} }`,
      simplified: () => `VStack { }`,
      basic: () => `EmptyView()`,
      minimal: () => `EmptyView()`,
      placeholder: () => `// Layout placeholder`
    }
  },

  'jetpack-compose': {
    component: {
      full: (node) => `${node.componentName}(${node.propsString})`,
      simplified: (node) => `${node.componentName}()`,
      basic: (node) => `Box { /* ${node.name} */ }`,
      minimal: () => `Box { }`,
      placeholder: (node) => `// TODO: Implement ${node.name}`
    },
    layout: {
      full: (node) => `Column { ${node.children} }`,
      simplified: () => `Column { }`,
      basic: () => `Box { }`,
      minimal: () => `Spacer()`,
      placeholder: () => `// Layout placeholder`
    }
  },

  'web-components': {
    component: {
      full: (node) => `<${node.componentName} ...props></${node.componentName}>`,
      simplified: (node) => `<${node.componentName}></${node.componentName}>`,
      basic: (node) => `<div class="${node.className}"><!-- ${node.name} --></div>`,
      minimal: (node) => `<div><!-- ${node.name} --></div>`,
      placeholder: (node) => `<!-- TODO: Implement ${node.name} -->`
    }
  }
};

/**
 * Default fallback strategies (used when framework-specific not available)
 */
const DEFAULT_FALLBACKS = {
  component: {
    full: (node) => `<Component name="${node.name}" />`,
    simplified: (node) => `<Component />`,
    basic: (node) => `<div><!-- ${node.name} --></div>`,
    minimal: () => `<div></div>`,
    placeholder: (node) => `<!-- TODO: ${node.name} -->`
  },
  layout: {
    full: (node) => node.layout || {},
    simplified: (node) => ({ display: node.layout?.display || 'block' }),
    basic: () => ({ display: 'block' }),
    minimal: () => ({}),
    placeholder: () => ({})
  },
  styling: {
    full: (node) => node.styles || {},
    simplified: (node) => ({ width: node.styles?.width, height: node.styles?.height }),
    basic: () => ({}),
    minimal: () => ({}),
    placeholder: () => ({})
  },
  content: {
    full: (node) => node.content || '',
    simplified: (node) => node.content?.substring(0, 100) || '',
    basic: () => '[Content]',
    minimal: () => '',
    placeholder: () => '[Placeholder]'
  },
  asset: {
    full: (node) => node.assetUrl,
    simplified: (node) => node.assetUrl,
    basic: () => '/placeholder.png',
    minimal: () => null,
    placeholder: () => '/placeholder.png'
  },
  animation: {
    full: (node) => node.animation,
    simplified: () => ({ duration: 300 }),
    basic: () => null,
    minimal: () => null,
    placeholder: () => null
  }
};

// =============================================================================
// FALLBACK REGISTRY CLASS
// =============================================================================

/**
 * Registry for managing fallback strategies
 */
class FallbackRegistry {
  constructor() {
    this.frameworkFallbacks = { ...FRAMEWORK_FALLBACKS };
    this.defaultFallbacks = { ...DEFAULT_FALLBACKS };
    this.customFallbacks = new Map();
    this.fallbackHistory = [];
    this.stats = {
      total: 0,
      byLevel: {},
      byCategory: {},
      byFramework: {}
    };
  }

  /**
   * Register a custom fallback strategy
   * @param {string} key - Unique key for the fallback
   * @param {Object} strategy - Strategy with level handlers
   */
  registerFallback(key, strategy) {
    this.customFallbacks.set(key, strategy);
  }

  /**
   * Unregister a custom fallback
   * @param {string} key - Fallback key
   * @returns {boolean} True if removed
   */
  unregisterFallback(key) {
    return this.customFallbacks.delete(key);
  }

  /**
   * Get fallback strategy for a given context
   * @param {string} framework - Target framework
   * @param {string} category - Fallback category
   * @param {string} level - Fallback level
   * @returns {Function|null} Fallback function or null
   */
  getFallback(framework, category, level) {
    // Check custom fallbacks first
    const customKey = `${framework}:${category}`;
    if (this.customFallbacks.has(customKey)) {
      const custom = this.customFallbacks.get(customKey);
      if (custom[level]) {
        return custom[level];
      }
    }

    // Check framework-specific fallbacks
    if (this.frameworkFallbacks[framework]?.[category]?.[level]) {
      return this.frameworkFallbacks[framework][category][level];
    }

    // Fall back to defaults
    if (this.defaultFallbacks[category]?.[level]) {
      return this.defaultFallbacks[category][level];
    }

    return null;
  }

  /**
   * Get all available levels for a category
   * @param {string} framework - Target framework
   * @param {string} category - Fallback category
   * @returns {string[]} Available levels
   */
  getAvailableLevels(framework, category) {
    const levels = new Set();

    // Check custom
    const customKey = `${framework}:${category}`;
    if (this.customFallbacks.has(customKey)) {
      Object.keys(this.customFallbacks.get(customKey)).forEach(l => levels.add(l));
    }

    // Check framework-specific
    if (this.frameworkFallbacks[framework]?.[category]) {
      Object.keys(this.frameworkFallbacks[framework][category]).forEach(l => levels.add(l));
    }

    // Check defaults
    if (this.defaultFallbacks[category]) {
      Object.keys(this.defaultFallbacks[category]).forEach(l => levels.add(l));
    }

    // Sort by preference order
    const levelOrder = Object.values(FALLBACK_LEVELS);
    return Array.from(levels).sort((a, b) => {
      return levelOrder.indexOf(a) - levelOrder.indexOf(b);
    });
  }

  /**
   * Record a fallback usage
   * @param {Object} record - Fallback usage record
   */
  recordFallback(record) {
    this.fallbackHistory.push({
      ...record,
      timestamp: Date.now()
    });

    // Keep history bounded
    if (this.fallbackHistory.length > 1000) {
      this.fallbackHistory = this.fallbackHistory.slice(-1000);
    }

    // Update stats
    this.stats.total++;
    this.stats.byLevel[record.level] = (this.stats.byLevel[record.level] || 0) + 1;
    this.stats.byCategory[record.category] = (this.stats.byCategory[record.category] || 0) + 1;
    this.stats.byFramework[record.framework] = (this.stats.byFramework[record.framework] || 0) + 1;
  }

  /**
   * Get fallback statistics
   * @returns {Object} Statistics
   */
  getStats() {
    return { ...this.stats };
  }

  /**
   * Get recent fallback history
   * @param {number} limit - Number of records to return
   * @returns {Object[]} Recent fallback records
   */
  getHistory(limit = 100) {
    return this.fallbackHistory.slice(-limit);
  }

  /**
   * Reset statistics
   */
  resetStats() {
    this.stats = {
      total: 0,
      byLevel: {},
      byCategory: {},
      byFramework: {}
    };
    this.fallbackHistory = [];
  }
}

// =============================================================================
// FALLBACK SELECTOR
// =============================================================================

/**
 * Selector for choosing appropriate fallback level
 */
class FallbackSelector {
  /**
   * Create a fallback selector
   * @param {FallbackRegistry} registry - Fallback registry
   * @param {Object} options - Selector options
   */
  constructor(registry, options = {}) {
    this.registry = registry;
    this.options = {
      preferredLevel: FALLBACK_LEVELS.FULL,
      allowPlaceholder: true,
      strictMode: false,
      onFallback: null,
      ...options
    };
  }

  /**
   * Select appropriate fallback for a transformation
   * @param {Object} context - Transformation context
   * @returns {Object} Selected fallback result
   */
  select(context) {
    const {
      framework,
      category,
      node,
      error = null,
      attemptedLevel = FALLBACK_LEVELS.FULL
    } = context;

    // Get available levels
    const availableLevels = this.registry.getAvailableLevels(framework, category);

    if (availableLevels.length === 0) {
      return {
        success: false,
        level: FALLBACK_LEVELS.NONE,
        result: null,
        reason: 'No fallbacks available'
      };
    }

    // Find the next level after the attempted one
    const levelOrder = Object.values(FALLBACK_LEVELS);
    const attemptedIndex = levelOrder.indexOf(attemptedLevel);

    // Try each level from current to placeholder
    for (let i = attemptedIndex; i < levelOrder.length; i++) {
      const level = levelOrder[i];

      // Skip placeholder if not allowed
      if (level === FALLBACK_LEVELS.PLACEHOLDER && !this.options.allowPlaceholder) {
        continue;
      }

      // Skip 'none' level
      if (level === FALLBACK_LEVELS.NONE) {
        break;
      }

      // Check if this level is available
      if (!availableLevels.includes(level)) {
        continue;
      }

      // Get and try the fallback
      const fallbackFn = this.registry.getFallback(framework, category, level);
      if (!fallbackFn) {
        continue;
      }

      try {
        const result = fallbackFn(node);

        // Record this fallback
        this.registry.recordFallback({
          framework,
          category,
          level,
          nodeId: node?.id,
          nodeName: node?.name,
          originalError: error?.message
        });

        // Notify callback
        if (this.options.onFallback) {
          this.options.onFallback({
            framework,
            category,
            level,
            node,
            result,
            originalError: error
          });
        }

        return {
          success: true,
          level,
          result,
          degraded: level !== FALLBACK_LEVELS.FULL,
          reason: level === FALLBACK_LEVELS.FULL ? null : `Degraded to ${level}`
        };
      } catch (fallbackError) {
        // This level failed, try next
        continue;
      }
    }

    // No fallback worked
    return {
      success: false,
      level: FALLBACK_LEVELS.NONE,
      result: null,
      reason: 'All fallbacks failed'
    };
  }

  /**
   * Try transformation with automatic fallback
   * @param {Function} transformFn - Primary transformation function
   * @param {Object} context - Transformation context
   * @returns {Object} Transformation result with fallback info
   */
  async tryWithFallback(transformFn, context) {
    const { framework, category, node } = context;

    try {
      // Try primary transformation
      const result = await transformFn(node);
      return {
        success: true,
        result,
        level: FALLBACK_LEVELS.FULL,
        degraded: false
      };
    } catch (error) {
      // Primary failed, try fallback
      const fallbackResult = this.select({
        ...context,
        error,
        attemptedLevel: FALLBACK_LEVELS.SIMPLIFIED
      });

      if (this.options.strictMode && !fallbackResult.success) {
        throw error;
      }

      return {
        ...fallbackResult,
        originalError: error.message
      };
    }
  }

  /**
   * Process multiple nodes with fallback support
   * @param {Function} transformFn - Transformation function
   * @param {Object[]} nodes - Nodes to process
   * @param {Object} context - Base context
   * @returns {Object} Batch result
   */
  async processBatch(transformFn, nodes, context) {
    const results = [];
    const degradations = [];
    let successCount = 0;
    let degradedCount = 0;
    let failedCount = 0;

    for (const node of nodes) {
      const nodeContext = { ...context, node };
      const result = await this.tryWithFallback(transformFn, nodeContext);

      results.push({
        nodeId: node.id,
        nodeName: node.name,
        ...result
      });

      if (result.success) {
        successCount++;
        if (result.degraded) {
          degradedCount++;
          degradations.push({
            nodeId: node.id,
            nodeName: node.name,
            level: result.level,
            reason: result.reason
          });
        }
      } else {
        failedCount++;
      }
    }

    return {
      total: nodes.length,
      successCount,
      degradedCount,
      failedCount,
      results,
      degradations,
      summary: {
        successRate: (successCount / nodes.length) * 100,
        degradationRate: (degradedCount / nodes.length) * 100,
        failureRate: (failedCount / nodes.length) * 100
      }
    };
  }
}

// =============================================================================
// GRACEFUL DEGRADATION MANAGER
// =============================================================================

/**
 * Main manager for graceful degradation
 */
class GracefulDegradationManager {
  /**
   * Create a degradation manager
   * @param {Object} options - Manager options
   */
  constructor(options = {}) {
    this.registry = new FallbackRegistry();
    this.selector = new FallbackSelector(this.registry, options);
    this.options = {
      enableLogging: true,
      maxDegradationLevel: FALLBACK_LEVELS.MINIMAL,
      reportDegradations: true,
      ...options
    };

    this.degradationReport = [];
  }

  /**
   * Transform with graceful degradation
   * @param {Function} transformFn - Primary transform function
   * @param {Object} context - Transformation context
   * @returns {Object} Result with degradation info
   */
  async transform(transformFn, context) {
    const result = await this.selector.tryWithFallback(transformFn, context);

    if (this.options.reportDegradations && result.degraded) {
      this.degradationReport.push({
        timestamp: Date.now(),
        nodeId: context.node?.id,
        nodeName: context.node?.name,
        framework: context.framework,
        category: context.category,
        level: result.level,
        reason: result.reason
      });
    }

    return result;
  }

  /**
   * Transform multiple nodes
   * @param {Function} transformFn - Transform function
   * @param {Object[]} nodes - Nodes to transform
   * @param {Object} context - Base context
   * @returns {Object} Batch result
   */
  async transformBatch(transformFn, nodes, context) {
    return this.selector.processBatch(transformFn, nodes, context);
  }

  /**
   * Register a custom fallback
   * @param {string} key - Fallback key
   * @param {Object} strategy - Fallback strategy
   */
  registerFallback(key, strategy) {
    this.registry.registerFallback(key, strategy);
  }

  /**
   * Get degradation report
   * @returns {Object[]} Degradation records
   */
  getDegradationReport() {
    return [...this.degradationReport];
  }

  /**
   * Get summary of degradations
   * @returns {Object} Summary statistics
   */
  getDegradationSummary() {
    const report = this.degradationReport;

    if (report.length === 0) {
      return {
        total: 0,
        byLevel: {},
        byCategory: {},
        byFramework: {}
      };
    }

    const byLevel = {};
    const byCategory = {};
    const byFramework = {};

    for (const record of report) {
      byLevel[record.level] = (byLevel[record.level] || 0) + 1;
      byCategory[record.category] = (byCategory[record.category] || 0) + 1;
      byFramework[record.framework] = (byFramework[record.framework] || 0) + 1;
    }

    return {
      total: report.length,
      byLevel,
      byCategory,
      byFramework
    };
  }

  /**
   * Clear degradation report
   */
  clearReport() {
    this.degradationReport = [];
  }

  /**
   * Get registry statistics
   * @returns {Object} Registry stats
   */
  getStats() {
    return this.registry.getStats();
  }
}

// =============================================================================
// ERROR HANDLER INTEGRATION
// =============================================================================

/**
 * Create an error handler with graceful degradation
 * @param {GracefulDegradationManager} manager - Degradation manager
 * @param {Object} options - Handler options
 * @returns {Function} Error handler function
 */
function createDegradingErrorHandler(manager, options = {}) {
  const {
    onError = null,
    onDegradation = null,
    onRecovery = null,
    logErrors = true
  } = options;

  return async function handleWithDegradation(error, context) {
    // Log the error
    if (logErrors) {
      console.error(`[GracefulDegradation] Error in ${context.category}:`, error.message);
    }

    // Notify error callback
    if (onError) {
      onError(error, context);
    }

    // Attempt degradation
    const fallbackResult = manager.selector.select({
      ...context,
      error,
      attemptedLevel: context.currentLevel || FALLBACK_LEVELS.SIMPLIFIED
    });

    if (fallbackResult.success) {
      // Degradation succeeded
      if (onDegradation) {
        onDegradation({
          originalError: error,
          fallbackLevel: fallbackResult.level,
          result: fallbackResult.result,
          context
        });
      }

      if (onRecovery) {
        onRecovery({
          level: fallbackResult.level,
          result: fallbackResult.result
        });
      }

      return {
        handled: true,
        degraded: true,
        level: fallbackResult.level,
        result: fallbackResult.result
      };
    }

    // Degradation failed
    return {
      handled: false,
      degraded: false,
      level: FALLBACK_LEVELS.NONE,
      result: null,
      error: error.message
    };
  };
}

/**
 * Wrap a transformer with graceful degradation
 * @param {Function} transformer - Transformer function
 * @param {Object} options - Wrapper options
 * @returns {Function} Wrapped transformer
 */
function wrapWithDegradation(transformer, options = {}) {
  const manager = new GracefulDegradationManager(options);

  const wrapped = async function degradingTransformer(node, context = {}) {
    const fullContext = {
      framework: context.framework || 'react',
      category: context.category || FALLBACK_CATEGORIES.COMPONENT,
      node,
      ...context
    };

    return manager.transform(
      (n) => transformer(n, context),
      fullContext
    );
  };

  // Expose manager for inspection
  wrapped.manager = manager;
  wrapped.getReport = () => manager.getDegradationReport();
  wrapped.getSummary = () => manager.getDegradationSummary();
  wrapped.getStats = () => manager.getStats();

  return wrapped;
}

// =============================================================================
// CONVENIENCE FUNCTIONS
// =============================================================================

/**
 * Create a simple fallback chain
 * @param {Function[]} handlers - Array of handler functions, tried in order
 * @returns {Function} Chain function
 */
function createFallbackChain(...handlers) {
  return async function chain(input) {
    let lastError = null;

    for (let i = 0; i < handlers.length; i++) {
      try {
        const result = await handlers[i](input);
        return {
          success: true,
          result,
          handlerIndex: i,
          degraded: i > 0
        };
      } catch (error) {
        lastError = error;
      }
    }

    return {
      success: false,
      result: null,
      error: lastError?.message,
      degraded: true
    };
  };
}

/**
 * Get default fallback for a framework and category
 * @param {string} framework - Target framework
 * @param {string} category - Fallback category
 * @param {string} level - Fallback level
 * @returns {Function|null} Fallback function
 */
function getDefaultFallback(framework, category, level = FALLBACK_LEVELS.BASIC) {
  if (FRAMEWORK_FALLBACKS[framework]?.[category]?.[level]) {
    return FRAMEWORK_FALLBACKS[framework][category][level];
  }
  if (DEFAULT_FALLBACKS[category]?.[level]) {
    return DEFAULT_FALLBACKS[category][level];
  }
  return null;
}

/**
 * Quick degradation check - can we degrade for this context?
 * @param {string} framework - Target framework
 * @param {string} category - Fallback category
 * @returns {boolean} True if degradation is possible
 */
function canDegrade(framework, category) {
  return !!(
    FRAMEWORK_FALLBACKS[framework]?.[category] ||
    DEFAULT_FALLBACKS[category]
  );
}

// =============================================================================
// EXPORTS
// =============================================================================

module.exports = {
  // Classes
  FallbackRegistry,
  FallbackSelector,
  GracefulDegradationManager,
  // Constants
  FALLBACK_LEVELS,
  FALLBACK_CATEGORIES,
  FRAMEWORK_FALLBACKS,
  DEFAULT_FALLBACKS,
  // Integration functions
  createDegradingErrorHandler,
  wrapWithDegradation,
  // Convenience functions
  createFallbackChain,
  getDefaultFallback,
  canDegrade
};
