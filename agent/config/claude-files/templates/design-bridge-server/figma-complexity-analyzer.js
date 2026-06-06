/**
 * Figma Complexity Analyzer
 *
 * Analyzes Figma node trees to detect complexity levels, potential issues,
 * and transformation challenges. Enables informed decision-making about
 * whether designs can be reliably transformed.
 *
 * Key Principle: Make failures observable and recoverable, not silent and destructive.
 *
 * @module figma-complexity-analyzer
 */

'use strict';

// =============================================================================
// COMPLEXITY METRICS SCHEMA
// =============================================================================

/**
 * Metric definitions with weights for scoring
 * Higher weights = more impact on overall complexity score
 */
const COMPLEXITY_METRICS = {
  // Structural Metrics
  nodeCount: {
    name: 'Node Count',
    description: 'Total number of nodes in the design tree',
    weight: 1.0,
    category: 'structural',
    unit: 'nodes'
  },
  maxDepth: {
    name: 'Maximum Depth',
    description: 'Deepest nesting level in the node tree',
    weight: 1.5,
    category: 'structural',
    unit: 'levels'
  },
  averageDepth: {
    name: 'Average Depth',
    description: 'Average nesting level across all nodes',
    weight: 1.0,
    category: 'structural',
    unit: 'levels'
  },
  childrenPerNode: {
    name: 'Children Per Node',
    description: 'Average number of children per container node',
    weight: 0.8,
    category: 'structural',
    unit: 'children'
  },

  // Component Metrics
  componentCount: {
    name: 'Component Count',
    description: 'Total number of component instances',
    weight: 1.2,
    category: 'components',
    unit: 'components'
  },
  uniqueComponentCount: {
    name: 'Unique Components',
    description: 'Number of distinct component definitions used',
    weight: 1.0,
    category: 'components',
    unit: 'components'
  },
  nestedComponentDepth: {
    name: 'Nested Component Depth',
    description: 'Maximum nesting of components within components',
    weight: 2.0,
    category: 'components',
    unit: 'levels'
  },
  variantCount: {
    name: 'Variant Count',
    description: 'Total number of component variants',
    weight: 0.8,
    category: 'components',
    unit: 'variants'
  },

  // Layout Metrics
  autoLayoutCount: {
    name: 'Auto Layout Count',
    description: 'Number of auto-layout containers',
    weight: 0.5,
    category: 'layout',
    unit: 'containers'
  },
  absolutePositionCount: {
    name: 'Absolute Position Count',
    description: 'Number of absolutely positioned elements',
    weight: 1.2,
    category: 'layout',
    unit: 'elements'
  },
  constraintComplexity: {
    name: 'Constraint Complexity',
    description: 'Combined complexity of constraint definitions',
    weight: 1.5,
    category: 'layout',
    unit: 'score'
  },
  mixedLayoutCount: {
    name: 'Mixed Layout Count',
    description: 'Containers mixing auto-layout with absolute children',
    weight: 2.0,
    category: 'layout',
    unit: 'containers'
  },

  // Visual Metrics
  effectCount: {
    name: 'Effect Count',
    description: 'Total number of visual effects (shadows, blurs)',
    weight: 0.8,
    category: 'visual',
    unit: 'effects'
  },
  blendModeCount: {
    name: 'Blend Mode Count',
    description: 'Number of non-normal blend modes',
    weight: 1.5,
    category: 'visual',
    unit: 'elements'
  },
  gradientCount: {
    name: 'Gradient Count',
    description: 'Total number of gradient fills',
    weight: 0.6,
    category: 'visual',
    unit: 'gradients'
  },
  maskCount: {
    name: 'Mask Count',
    description: 'Number of mask operations',
    weight: 1.8,
    category: 'visual',
    unit: 'masks'
  },
  booleanOperationCount: {
    name: 'Boolean Operation Count',
    description: 'Number of boolean path operations',
    weight: 1.5,
    category: 'visual',
    unit: 'operations'
  },

  // Content Metrics
  textNodeCount: {
    name: 'Text Node Count',
    description: 'Total number of text elements',
    weight: 0.3,
    category: 'content',
    unit: 'texts'
  },
  imageCount: {
    name: 'Image Count',
    description: 'Total number of images/fills',
    weight: 0.5,
    category: 'content',
    unit: 'images'
  },
  vectorCount: {
    name: 'Vector Count',
    description: 'Number of vector/path elements',
    weight: 0.8,
    category: 'content',
    unit: 'vectors'
  },

  // Advanced Metrics
  variableBindingCount: {
    name: 'Variable Binding Count',
    description: 'Number of Figma variable bindings',
    weight: 1.2,
    category: 'advanced',
    unit: 'bindings'
  },
  prototypeInteractionCount: {
    name: 'Prototype Interaction Count',
    description: 'Number of prototype interactions/triggers',
    weight: 0.5,
    category: 'advanced',
    unit: 'interactions'
  },
  styleReferenceCount: {
    name: 'Style Reference Count',
    description: 'Number of shared style references',
    weight: 0.4,
    category: 'advanced',
    unit: 'references'
  }
};

/**
 * Get all metrics in a specific category
 * @param {string} category - Category name
 * @returns {Object} Metrics in that category
 */
function getMetricsByCategory(category) {
  const result = {};
  for (const [key, metric] of Object.entries(COMPLEXITY_METRICS)) {
    if (metric.category === category) {
      result[key] = metric;
    }
  }
  return result;
}

/**
 * Get all available metric categories
 * @returns {string[]} Array of category names
 */
function getMetricCategories() {
  const categories = new Set();
  for (const metric of Object.values(COMPLEXITY_METRICS)) {
    categories.add(metric.category);
  }
  return Array.from(categories);
}

// =============================================================================
// COMPLEXITY THRESHOLDS
// =============================================================================

/**
 * Thresholds defining complexity levels
 * - low: Safe to transform, likely to succeed
 * - medium: Proceed with caution, may need adjustments
 * - high: Review carefully, significant transformation challenges
 * - critical: Manual intervention likely needed
 */
const THRESHOLDS = {
  // Structural thresholds
  nodeCount: {
    low: 50,
    medium: 200,
    high: 500,
    critical: 1000
  },
  maxDepth: {
    low: 5,
    medium: 10,
    high: 15,
    critical: 25
  },
  averageDepth: {
    low: 3,
    medium: 5,
    high: 8,
    critical: 12
  },
  childrenPerNode: {
    low: 5,
    medium: 10,
    high: 20,
    critical: 50
  },

  // Component thresholds
  componentCount: {
    low: 10,
    medium: 30,
    high: 75,
    critical: 150
  },
  uniqueComponentCount: {
    low: 5,
    medium: 15,
    high: 30,
    critical: 60
  },
  nestedComponentDepth: {
    low: 2,
    medium: 4,
    high: 6,
    critical: 10
  },
  variantCount: {
    low: 10,
    medium: 25,
    high: 50,
    critical: 100
  },

  // Layout thresholds
  autoLayoutCount: {
    low: 20,
    medium: 50,
    high: 100,
    critical: 200
  },
  absolutePositionCount: {
    low: 5,
    medium: 15,
    high: 30,
    critical: 75
  },
  constraintComplexity: {
    low: 10,
    medium: 30,
    high: 60,
    critical: 100
  },
  mixedLayoutCount: {
    low: 2,
    medium: 5,
    high: 10,
    critical: 20
  },

  // Visual thresholds
  effectCount: {
    low: 10,
    medium: 25,
    high: 50,
    critical: 100
  },
  blendModeCount: {
    low: 2,
    medium: 5,
    high: 10,
    critical: 25
  },
  gradientCount: {
    low: 5,
    medium: 15,
    high: 30,
    critical: 60
  },
  maskCount: {
    low: 2,
    medium: 5,
    high: 10,
    critical: 25
  },
  booleanOperationCount: {
    low: 3,
    medium: 10,
    high: 20,
    critical: 50
  },

  // Content thresholds
  textNodeCount: {
    low: 20,
    medium: 50,
    high: 100,
    critical: 250
  },
  imageCount: {
    low: 10,
    medium: 25,
    high: 50,
    critical: 100
  },
  vectorCount: {
    low: 10,
    medium: 30,
    high: 60,
    critical: 150
  },

  // Advanced thresholds
  variableBindingCount: {
    low: 10,
    medium: 30,
    high: 60,
    critical: 150
  },
  prototypeInteractionCount: {
    low: 5,
    medium: 15,
    high: 30,
    critical: 75
  },
  styleReferenceCount: {
    low: 10,
    medium: 30,
    high: 60,
    critical: 120
  },

  // Overall score thresholds
  overallScore: {
    low: 25,
    medium: 50,
    high: 75,
    critical: 90
  }
};

/**
 * Severity levels for warnings and issues
 */
const SEVERITY_LEVELS = {
  INFO: 'info',
  WARNING: 'warning',
  ERROR: 'error',
  CRITICAL: 'critical'
};

/**
 * Complexity level enumeration
 */
const COMPLEXITY_LEVELS = {
  LOW: 'low',
  MEDIUM: 'medium',
  HIGH: 'high',
  CRITICAL: 'critical'
};

// =============================================================================
// ANALYSIS RESULT CLASS
// =============================================================================

/**
 * Represents the result of a complexity analysis
 */
class AnalysisResult {
  /**
   * Create an analysis result
   * @param {Object} options - Initial values
   */
  constructor(options = {}) {
    // Metadata
    this.analyzedAt = options.analyzedAt || new Date().toISOString();
    this.nodeId = options.nodeId || null;
    this.nodeName = options.nodeName || 'Unknown';
    this.nodeType = options.nodeType || 'UNKNOWN';
    this.version = '1.0.0';

    // Raw metrics (initialized to 0)
    this.metrics = {};
    for (const key of Object.keys(COMPLEXITY_METRICS)) {
      this.metrics[key] = options.metrics?.[key] ?? 0;
    }

    // Calculated scores (0-100 per metric)
    this.scores = {};
    for (const key of Object.keys(COMPLEXITY_METRICS)) {
      this.scores[key] = options.scores?.[key] ?? 0;
    }

    // Overall complexity
    this.overallScore = options.overallScore ?? 0;
    this.complexityLevel = options.complexityLevel || COMPLEXITY_LEVELS.LOW;

    // Warnings and issues
    this.warnings = options.warnings || [];
    this.issues = options.issues || [];

    // Category summaries
    this.categorySummaries = options.categorySummaries || {};

    // Recommendations
    this.recommendations = options.recommendations || [];

    // Framework-specific notes
    this.frameworkNotes = options.frameworkNotes || {};
  }

  /**
   * Add a warning to the result
   * @param {string} message - Warning message
   * @param {string} severity - Severity level
   * @param {Object} context - Additional context
   */
  addWarning(message, severity = SEVERITY_LEVELS.WARNING, context = {}) {
    this.warnings.push({
      message,
      severity,
      timestamp: new Date().toISOString(),
      ...context
    });
  }

  /**
   * Add an issue to the result
   * @param {string} metric - Metric name that triggered the issue
   * @param {string} message - Issue description
   * @param {string} level - Complexity level
   * @param {Object} context - Additional context
   */
  addIssue(metric, message, level, context = {}) {
    this.issues.push({
      metric,
      message,
      level,
      timestamp: new Date().toISOString(),
      ...context
    });
  }

  /**
   * Add a recommendation
   * @param {string} title - Recommendation title
   * @param {string} description - Detailed description
   * @param {string} priority - Priority level (high, medium, low)
   */
  addRecommendation(title, description, priority = 'medium') {
    this.recommendations.push({
      title,
      description,
      priority
    });
  }

  /**
   * Set metric value and calculate its score
   * @param {string} metricName - Name of the metric
   * @param {number} value - Raw metric value
   */
  setMetric(metricName, value) {
    if (!COMPLEXITY_METRICS[metricName]) {
      console.warn(`Unknown metric: ${metricName}`);
      return;
    }

    this.metrics[metricName] = value;
    this.scores[metricName] = this._calculateMetricScore(metricName, value);
  }

  /**
   * Calculate score for a single metric (0-100)
   * @param {string} metricName - Metric name
   * @param {number} value - Raw value
   * @returns {number} Score from 0-100
   * @private
   */
  _calculateMetricScore(metricName, value) {
    const threshold = THRESHOLDS[metricName];
    if (!threshold) return 0;

    if (value <= threshold.low) return 0;
    if (value <= threshold.medium) {
      // Linear interpolation: low->medium = 0->33
      return Math.round(((value - threshold.low) / (threshold.medium - threshold.low)) * 33);
    }
    if (value <= threshold.high) {
      // Linear interpolation: medium->high = 33->66
      return Math.round(33 + ((value - threshold.medium) / (threshold.high - threshold.medium)) * 33);
    }
    if (value <= threshold.critical) {
      // Linear interpolation: high->critical = 66->100
      return Math.round(66 + ((value - threshold.high) / (threshold.critical - threshold.high)) * 34);
    }
    // Beyond critical
    return 100;
  }

  /**
   * Calculate overall complexity score
   */
  calculateOverallScore() {
    let totalWeight = 0;
    let weightedSum = 0;

    for (const [metricName, score] of Object.entries(this.scores)) {
      const metric = COMPLEXITY_METRICS[metricName];
      if (metric) {
        weightedSum += score * metric.weight;
        totalWeight += metric.weight;
      }
    }

    this.overallScore = totalWeight > 0 ? Math.round(weightedSum / totalWeight) : 0;
    this.complexityLevel = this._determineComplexityLevel(this.overallScore);

    return this.overallScore;
  }

  /**
   * Determine complexity level from score
   * @param {number} score - Overall score
   * @returns {string} Complexity level
   * @private
   */
  _determineComplexityLevel(score) {
    const t = THRESHOLDS.overallScore;
    if (score <= t.low) return COMPLEXITY_LEVELS.LOW;
    if (score <= t.medium) return COMPLEXITY_LEVELS.MEDIUM;
    if (score <= t.high) return COMPLEXITY_LEVELS.HIGH;
    return COMPLEXITY_LEVELS.CRITICAL;
  }

  /**
   * Generate category summaries
   */
  generateCategorySummaries() {
    const categories = getMetricCategories();

    for (const category of categories) {
      const categoryMetrics = getMetricsByCategory(category);
      let categoryScore = 0;
      let metricCount = 0;
      const details = [];

      for (const metricName of Object.keys(categoryMetrics)) {
        categoryScore += this.scores[metricName] || 0;
        metricCount++;
        details.push({
          metric: metricName,
          value: this.metrics[metricName],
          score: this.scores[metricName],
          unit: categoryMetrics[metricName].unit
        });
      }

      this.categorySummaries[category] = {
        averageScore: metricCount > 0 ? Math.round(categoryScore / metricCount) : 0,
        metricCount,
        details
      };
    }
  }

  /**
   * Check if transformation is recommended
   * @returns {Object} Transformation recommendation
   */
  getTransformationRecommendation() {
    if (this.complexityLevel === COMPLEXITY_LEVELS.LOW) {
      return {
        recommended: true,
        confidence: 'high',
        message: 'Design complexity is low. Transformation should proceed smoothly.'
      };
    }
    if (this.complexityLevel === COMPLEXITY_LEVELS.MEDIUM) {
      return {
        recommended: true,
        confidence: 'medium',
        message: 'Design has moderate complexity. Review warnings before proceeding.'
      };
    }
    if (this.complexityLevel === COMPLEXITY_LEVELS.HIGH) {
      return {
        recommended: false,
        confidence: 'low',
        message: 'Design is highly complex. Consider simplifying or manual implementation.'
      };
    }
    return {
      recommended: false,
      confidence: 'none',
      message: 'Design complexity is critical. Manual implementation strongly recommended.'
    };
  }

  /**
   * Convert to plain object for serialization
   * @returns {Object} Plain object representation
   */
  toJSON() {
    return {
      meta: {
        analyzedAt: this.analyzedAt,
        nodeId: this.nodeId,
        nodeName: this.nodeName,
        nodeType: this.nodeType,
        version: this.version
      },
      metrics: this.metrics,
      scores: this.scores,
      overallScore: this.overallScore,
      complexityLevel: this.complexityLevel,
      warnings: this.warnings,
      issues: this.issues,
      categorySummaries: this.categorySummaries,
      recommendations: this.recommendations,
      frameworkNotes: this.frameworkNotes,
      transformationRecommendation: this.getTransformationRecommendation()
    };
  }

  /**
   * Create from plain object
   * @param {Object} data - Plain object data
   * @returns {AnalysisResult} New instance
   */
  static fromJSON(data) {
    const result = new AnalysisResult({
      analyzedAt: data.meta?.analyzedAt,
      nodeId: data.meta?.nodeId,
      nodeName: data.meta?.nodeName,
      nodeType: data.meta?.nodeType,
      metrics: data.metrics,
      scores: data.scores,
      overallScore: data.overallScore,
      complexityLevel: data.complexityLevel,
      warnings: data.warnings,
      issues: data.issues,
      categorySummaries: data.categorySummaries,
      recommendations: data.recommendations,
      frameworkNotes: data.frameworkNotes
    });
    return result;
  }
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Get threshold level for a metric value
 * @param {string} metricName - Metric name
 * @param {number} value - Metric value
 * @returns {string} Threshold level (low, medium, high, critical)
 */
function getThresholdLevel(metricName, value) {
  const threshold = THRESHOLDS[metricName];
  if (!threshold) return COMPLEXITY_LEVELS.LOW;

  if (value <= threshold.low) return COMPLEXITY_LEVELS.LOW;
  if (value <= threshold.medium) return COMPLEXITY_LEVELS.MEDIUM;
  if (value <= threshold.high) return COMPLEXITY_LEVELS.HIGH;
  return COMPLEXITY_LEVELS.CRITICAL;
}

/**
 * Check if a metric value exceeds a specific threshold level
 * @param {string} metricName - Metric name
 * @param {number} value - Metric value
 * @param {string} level - Level to check against
 * @returns {boolean} True if value exceeds the level threshold
 */
function exceedsThreshold(metricName, value, level = COMPLEXITY_LEVELS.MEDIUM) {
  const threshold = THRESHOLDS[metricName];
  if (!threshold) return false;
  return value > threshold[level];
}

/**
 * Get all metrics that exceed a threshold level
 * @param {Object} metrics - Metric values object
 * @param {string} level - Threshold level
 * @returns {Object[]} Array of exceeding metrics with details
 */
function getExceedingMetrics(metrics, level = COMPLEXITY_LEVELS.MEDIUM) {
  const exceeding = [];

  for (const [metricName, value] of Object.entries(metrics)) {
    if (exceedsThreshold(metricName, value, level)) {
      const threshold = THRESHOLDS[metricName];
      exceeding.push({
        metric: metricName,
        value,
        threshold: threshold[level],
        level: getThresholdLevel(metricName, value),
        metricInfo: COMPLEXITY_METRICS[metricName]
      });
    }
  }

  return exceeding;
}

// =============================================================================
// NODE WALKER
// =============================================================================

/**
 * Context object for node walking
 * @typedef {Object} WalkContext
 * @property {number} currentDepth - Current depth in the tree
 * @property {number} maxDepth - Maximum depth encountered
 * @property {number[]} depths - Array of all node depths
 * @property {Set<string>} visitedIds - Set of visited node IDs for cycle detection
 * @property {Map<string, number>} componentInstances - Map of component ID to instance count
 * @property {Object} counters - Raw metric counters
 */

/**
 * Create initial walk context
 * @returns {WalkContext} Fresh context object
 */
function createWalkContext() {
  return {
    currentDepth: 0,
    maxDepth: 0,
    depths: [],
    visitedIds: new Set(),
    componentInstances: new Map(),
    counters: {
      nodeCount: 0,
      componentCount: 0,
      uniqueComponentCount: 0,
      nestedComponentDepth: 0,
      variantCount: 0,
      autoLayoutCount: 0,
      absolutePositionCount: 0,
      constraintComplexity: 0,
      mixedLayoutCount: 0,
      effectCount: 0,
      blendModeCount: 0,
      gradientCount: 0,
      maskCount: 0,
      booleanOperationCount: 0,
      textNodeCount: 0,
      imageCount: 0,
      vectorCount: 0,
      variableBindingCount: 0,
      prototypeInteractionCount: 0,
      styleReferenceCount: 0,
      // Additional tracking
      containerNodes: 0,
      totalChildren: 0,
      componentDepths: []
    }
  };
}

/**
 * Figma node types that are containers (can have children)
 */
const CONTAINER_TYPES = new Set([
  'FRAME',
  'GROUP',
  'COMPONENT',
  'COMPONENT_SET',
  'INSTANCE',
  'SECTION',
  'BOOLEAN_OPERATION',
  'DOCUMENT',
  'PAGE',
  'CANVAS'
]);

/**
 * Figma node types that are vector-based
 */
const VECTOR_TYPES = new Set([
  'VECTOR',
  'LINE',
  'ELLIPSE',
  'POLYGON',
  'STAR',
  'REGULAR_POLYGON',
  'RECTANGLE'
]);

/**
 * Check if a node is a container type
 * @param {Object} node - Figma node
 * @returns {boolean} True if container
 */
function isContainerNode(node) {
  return CONTAINER_TYPES.has(node.type);
}

/**
 * Collect metrics from a single node
 * @param {Object} node - Figma node
 * @param {WalkContext} context - Walk context
 */
function collectNodeMetrics(node, context) {
  if (!node) return;

  // Basic counter
  context.counters.nodeCount++;
  context.depths.push(context.currentDepth);

  // Track max depth
  if (context.currentDepth > context.maxDepth) {
    context.maxDepth = context.currentDepth;
  }

  // Node type specific metrics
  switch (node.type) {
    case 'COMPONENT':
    case 'INSTANCE':
      context.counters.componentCount++;
      // Track unique components
      const componentId = node.componentId || node.id;
      if (!context.componentInstances.has(componentId)) {
        context.componentInstances.set(componentId, 0);
      }
      context.componentInstances.set(
        componentId,
        context.componentInstances.get(componentId) + 1
      );
      // Track component nesting depth
      context.counters.componentDepths.push(context.currentDepth);
      break;

    case 'COMPONENT_SET':
      // Variant count from component set
      if (node.children) {
        context.counters.variantCount += node.children.filter(
          c => c.type === 'COMPONENT'
        ).length;
      }
      break;

    case 'TEXT':
      context.counters.textNodeCount++;
      break;

    case 'BOOLEAN_OPERATION':
      context.counters.booleanOperationCount++;
      break;

    default:
      if (VECTOR_TYPES.has(node.type)) {
        context.counters.vectorCount++;
      }
  }

  // Container tracking
  if (isContainerNode(node)) {
    context.counters.containerNodes++;
    if (node.children) {
      context.counters.totalChildren += node.children.length;
    }
  }

  // Layout metrics
  if (node.layoutMode) {
    context.counters.autoLayoutCount++;
    // Check for mixed layout (auto-layout with absolutely positioned children)
    if (node.children) {
      const hasAbsoluteChild = node.children.some(
        child => child.layoutPositioning === 'ABSOLUTE'
      );
      if (hasAbsoluteChild) {
        context.counters.mixedLayoutCount++;
      }
    }
  }

  if (node.layoutPositioning === 'ABSOLUTE') {
    context.counters.absolutePositionCount++;
  }

  // Constraint complexity
  if (node.constraints) {
    let complexity = 0;
    if (node.constraints.horizontal && node.constraints.horizontal !== 'LEFT') {
      complexity++;
    }
    if (node.constraints.vertical && node.constraints.vertical !== 'TOP') {
      complexity++;
    }
    // More complex constraints
    if (node.constraints.horizontal === 'SCALE' || node.constraints.vertical === 'SCALE') {
      complexity += 2;
    }
    context.counters.constraintComplexity += complexity;
  }

  // Visual effects
  if (node.effects && Array.isArray(node.effects)) {
    context.counters.effectCount += node.effects.filter(e => e.visible !== false).length;
  }

  // Blend modes
  if (node.blendMode && node.blendMode !== 'NORMAL' && node.blendMode !== 'PASS_THROUGH') {
    context.counters.blendModeCount++;
  }

  // Fills (gradients and images)
  if (node.fills && Array.isArray(node.fills)) {
    for (const fill of node.fills) {
      if (fill.visible === false) continue;
      if (fill.type === 'GRADIENT_LINEAR' ||
          fill.type === 'GRADIENT_RADIAL' ||
          fill.type === 'GRADIENT_ANGULAR' ||
          fill.type === 'GRADIENT_DIAMOND') {
        context.counters.gradientCount++;
      }
      if (fill.type === 'IMAGE') {
        context.counters.imageCount++;
      }
    }
  }

  // Masks
  if (node.isMask || node.isMaskOutline) {
    context.counters.maskCount++;
  }

  // Variable bindings
  if (node.boundVariables) {
    context.counters.variableBindingCount += Object.keys(node.boundVariables).length;
  }

  // Prototype interactions
  if (node.reactions && Array.isArray(node.reactions)) {
    context.counters.prototypeInteractionCount += node.reactions.length;
  }

  // Style references
  if (node.styles) {
    context.counters.styleReferenceCount += Object.keys(node.styles).length;
  }
}

/**
 * Walk a Figma node tree recursively
 * @param {Object} node - Root Figma node
 * @param {WalkContext} context - Walk context
 * @param {Object} options - Walk options
 * @param {number} options.maxDepth - Maximum depth to walk (default: 100)
 * @param {boolean} options.skipInvisible - Skip invisible nodes (default: false)
 * @param {Function} options.onNode - Callback for each node
 * @returns {boolean} True if walk completed without issues
 */
function walkNodes(node, context, options = {}) {
  const {
    maxDepth = 100,
    skipInvisible = false,
    onNode = null
  } = options;

  if (!node) return true;

  // Depth limit check
  if (context.currentDepth > maxDepth) {
    return false;
  }

  // Cycle detection
  if (node.id) {
    if (context.visitedIds.has(node.id)) {
      console.warn(`Cycle detected at node: ${node.id}`);
      return false;
    }
    context.visitedIds.add(node.id);
  }

  // Skip invisible if requested
  if (skipInvisible && node.visible === false) {
    return true;
  }

  // Collect metrics for this node
  collectNodeMetrics(node, context);

  // Custom callback
  if (onNode && typeof onNode === 'function') {
    onNode(node, context);
  }

  // Recurse into children
  if (node.children && Array.isArray(node.children)) {
    context.currentDepth++;
    for (const child of node.children) {
      walkNodes(child, context, options);
    }
    context.currentDepth--;
  }

  return true;
}

/**
 * Walk nodes and return collected metrics
 * @param {Object} node - Root Figma node
 * @param {Object} options - Walk options
 * @returns {Object} Collected metrics
 */
function walkAndCollect(node, options = {}) {
  const context = createWalkContext();
  const completed = walkNodes(node, context, options);

  // Calculate derived metrics
  const metrics = {
    ...context.counters,
    maxDepth: context.maxDepth,
    averageDepth: context.depths.length > 0
      ? context.depths.reduce((a, b) => a + b, 0) / context.depths.length
      : 0,
    childrenPerNode: context.counters.containerNodes > 0
      ? context.counters.totalChildren / context.counters.containerNodes
      : 0,
    uniqueComponentCount: context.componentInstances.size,
    nestedComponentDepth: context.counters.componentDepths.length > 0
      ? Math.max(...context.counters.componentDepths) - Math.min(...context.counters.componentDepths)
      : 0
  };

  // Remove internal tracking fields
  delete metrics.containerNodes;
  delete metrics.totalChildren;
  delete metrics.componentDepths;

  return {
    metrics,
    completed,
    nodesVisited: context.visitedIds.size,
    maxDepthReached: context.maxDepth
  };
}

/**
 * Calculate complexity for a specific subtree
 * @param {Object} node - Root node of subtree
 * @returns {Object} Subtree complexity summary
 */
function calculateSubtreeComplexity(node) {
  const { metrics, completed, nodesVisited } = walkAndCollect(node);

  // Quick score calculation
  let score = 0;
  let totalWeight = 0;

  for (const [metricName, value] of Object.entries(metrics)) {
    const metricDef = COMPLEXITY_METRICS[metricName];
    const threshold = THRESHOLDS[metricName];
    if (metricDef && threshold) {
      const metricScore = value > threshold.critical ? 100 :
                         value > threshold.high ? 75 :
                         value > threshold.medium ? 50 :
                         value > threshold.low ? 25 : 0;
      score += metricScore * metricDef.weight;
      totalWeight += metricDef.weight;
    }
  }

  const overallScore = totalWeight > 0 ? Math.round(score / totalWeight) : 0;

  return {
    nodeName: node.name || 'Unknown',
    nodeType: node.type || 'UNKNOWN',
    nodeCount: metrics.nodeCount,
    maxDepth: metrics.maxDepth,
    overallScore,
    complexityLevel: overallScore < 25 ? 'low' :
                     overallScore < 50 ? 'medium' :
                     overallScore < 75 ? 'high' : 'critical',
    completed
  };
}

// =============================================================================
// WARNING GENERATOR
// =============================================================================

/**
 * Warning templates for different metric issues
 */
const WARNING_TEMPLATES = {
  nodeCount: {
    high: 'Large design with {value} nodes may slow transformation',
    critical: 'Very large design with {value} nodes - consider splitting into smaller components'
  },
  maxDepth: {
    high: 'Deep nesting ({value} levels) may produce complex CSS/component hierarchies',
    critical: 'Extremely deep nesting ({value} levels) will be difficult to maintain'
  },
  nestedComponentDepth: {
    medium: 'Nested components ({value} levels deep) may require careful prop drilling',
    high: 'Deeply nested components ({value} levels) - consider flattening structure',
    critical: 'Component nesting ({value} levels) exceeds recommended limits'
  },
  absolutePositionCount: {
    medium: '{value} absolute positions may not translate well to responsive layouts',
    high: 'Many absolute positions ({value}) will likely need manual responsive handling',
    critical: 'Excessive absolute positioning ({value}) - consider redesigning with flexbox/grid'
  },
  mixedLayoutCount: {
    low: '{value} containers mix auto-layout with absolute children',
    medium: '{value} mixed layout containers may cause unpredictable behavior',
    high: 'Significant layout mixing ({value} containers) - framework support varies'
  },
  blendModeCount: {
    medium: '{value} blend modes - some frameworks have limited support',
    high: 'Many blend modes ({value}) may require fallbacks',
    critical: 'Excessive blend modes ({value}) - many will degrade or need manual handling'
  },
  maskCount: {
    medium: '{value} masks may require SVG or canvas rendering',
    high: 'Many masks ({value}) - performance and compatibility concerns',
    critical: 'Excessive masking ({value}) - significant performance impact expected'
  },
  booleanOperationCount: {
    medium: '{value} boolean operations will be exported as SVG paths',
    high: 'Many boolean operations ({value}) - consider simplifying or using images'
  },
  variableBindingCount: {
    medium: '{value} variable bindings need manual mapping to framework state',
    high: 'Many variable bindings ({value}) require significant state management work'
  },
  effectCount: {
    high: '{value} effects may impact performance on mobile devices',
    critical: 'Excessive effects ({value}) - consider reducing for better performance'
  },
  gradientCount: {
    high: '{value} gradients - CSS/native support varies',
    critical: 'Many gradients ({value}) may have rendering differences across platforms'
  },
  constraintComplexity: {
    high: 'Complex constraints (score: {value}) may not map directly to CSS/native layouts',
    critical: 'Very complex constraints (score: {value}) will likely need manual adjustment'
  }
};

/**
 * Generate warnings based on metrics analysis
 * @param {Object} metrics - Collected metrics
 * @param {Object} options - Options
 * @param {string[]} options.skipMetrics - Metrics to skip warnings for
 * @returns {Object[]} Array of warning objects
 */
function generateWarnings(metrics, options = {}) {
  const { skipMetrics = [] } = options;
  const warnings = [];

  for (const [metricName, value] of Object.entries(metrics)) {
    if (skipMetrics.includes(metricName)) continue;

    const templates = WARNING_TEMPLATES[metricName];
    if (!templates) continue;

    const level = getThresholdLevel(metricName, value);
    const template = templates[level];

    if (template && (level === COMPLEXITY_LEVELS.MEDIUM ||
                     level === COMPLEXITY_LEVELS.HIGH ||
                     level === COMPLEXITY_LEVELS.CRITICAL)) {
      warnings.push({
        metric: metricName,
        level,
        severity: level === COMPLEXITY_LEVELS.CRITICAL ? SEVERITY_LEVELS.ERROR :
                  level === COMPLEXITY_LEVELS.HIGH ? SEVERITY_LEVELS.WARNING :
                  SEVERITY_LEVELS.INFO,
        message: template.replace('{value}', value),
        value,
        threshold: THRESHOLDS[metricName]?.[level] || 0
      });
    }
  }

  // Sort by severity (critical first)
  const severityOrder = {
    [SEVERITY_LEVELS.CRITICAL]: 0,
    [SEVERITY_LEVELS.ERROR]: 1,
    [SEVERITY_LEVELS.WARNING]: 2,
    [SEVERITY_LEVELS.INFO]: 3
  };

  warnings.sort((a, b) => severityOrder[a.severity] - severityOrder[b.severity]);

  return warnings;
}

// =============================================================================
// FRAMEWORK-SPECIFIC NOTES
// =============================================================================

/**
 * Framework-specific considerations for different patterns
 */
const FRAMEWORK_NOTES = {
  react: {
    absolutePositionCount: 'Use absolute positioning sparingly with Tailwind or styled-components',
    blendModeCount: 'CSS blend modes well supported, consider mix-blend-mode utility classes',
    maskCount: 'Use SVG masks or clip-path for best React compatibility',
    variableBindingCount: 'Map to React state/props, consider Zustand or Redux for complex state',
    nestedComponentDepth: 'Use React.memo for deeply nested components to prevent re-renders'
  },
  vue: {
    absolutePositionCount: 'Vue scoped styles work well with absolute positioning',
    blendModeCount: 'Full CSS blend mode support in Vue templates',
    variableBindingCount: 'Map to computed properties and reactive refs',
    nestedComponentDepth: 'Consider provide/inject for deeply nested state'
  },
  svelte: {
    absolutePositionCount: 'Svelte scoped styles handle positioning well',
    blendModeCount: 'CSS blend modes fully supported',
    variableBindingCount: 'Svelte stores provide excellent state management',
    effectCount: 'Svelte transitions can replace some Figma effects'
  },
  angular: {
    absolutePositionCount: 'Use Angular CDK for complex positioning scenarios',
    blendModeCount: 'Encapsulation may affect blend mode scoping',
    variableBindingCount: 'Map to services and RxJS observables',
    nestedComponentDepth: 'Angular change detection may be impacted by deep nesting'
  },
  'react-native': {
    absolutePositionCount: 'React Native uses different positioning model - manual conversion needed',
    blendModeCount: 'Limited blend mode support - may need native modules',
    gradientCount: 'Use react-native-linear-gradient for gradients',
    effectCount: 'Shadow effects require platform-specific handling',
    maskCount: 'Use react-native-svg for mask operations'
  },
  flutter: {
    absolutePositionCount: 'Use Stack and Positioned widgets for absolute layouts',
    blendModeCount: 'BlendMode enum maps well to Figma blend modes',
    gradientCount: 'LinearGradient/RadialGradient have excellent support',
    effectCount: 'BoxShadow and BackdropFilter for effects',
    maskCount: 'ClipPath and ShapeBorder for masking'
  },
  swiftui: {
    absolutePositionCount: 'Use GeometryReader or position modifier sparingly',
    blendModeCount: 'blendMode modifier supported on most views',
    gradientCount: 'Native gradient support with LinearGradient/RadialGradient',
    effectCount: 'shadow() modifier and blur() available',
    maskCount: 'mask() modifier and clipShape() for clipping'
  },
  'jetpack-compose': {
    absolutePositionCount: 'Use Box with Modifier.offset for positioning',
    blendModeCount: 'graphicsLayer with BlendMode for composition',
    gradientCount: 'Brush.linearGradient/radialGradient supported',
    effectCount: 'shadow modifier and blur filters available',
    maskCount: 'clip modifier with custom shapes'
  },
  'web-components': {
    absolutePositionCount: 'Standard CSS positioning works within shadow DOM',
    blendModeCount: 'Full CSS blend mode support',
    variableBindingCount: 'Map to component properties and attributes',
    nestedComponentDepth: 'Shadow DOM boundaries affect CSS cascade'
  }
};

/**
 * Generate framework-specific notes based on metrics
 * @param {string} framework - Target framework
 * @param {Object} metrics - Collected metrics
 * @returns {Object[]} Array of framework-specific notes
 */
function generateFrameworkNotes(framework, metrics) {
  const frameworkNotesMap = FRAMEWORK_NOTES[framework];
  if (!frameworkNotesMap) {
    return [{
      metric: null,
      note: `No specific notes available for ${framework}`,
      type: 'info'
    }];
  }

  const notes = [];

  for (const [metricName, note] of Object.entries(frameworkNotesMap)) {
    const value = metrics[metricName] || 0;
    const level = getThresholdLevel(metricName, value);

    // Only include notes for metrics that exceed low threshold
    if (level !== COMPLEXITY_LEVELS.LOW) {
      notes.push({
        metric: metricName,
        value,
        level,
        note,
        type: level === COMPLEXITY_LEVELS.CRITICAL ? 'critical' :
              level === COMPLEXITY_LEVELS.HIGH ? 'warning' : 'info'
      });
    }
  }

  return notes;
}

/**
 * Get all supported frameworks
 * @returns {string[]} Array of framework names
 */
function getSupportedFrameworks() {
  return Object.keys(FRAMEWORK_NOTES);
}

// =============================================================================
// MAIN ANALYSIS FUNCTIONS
// =============================================================================

/**
 * Analyze a Figma node and return comprehensive complexity analysis
 * @param {Object} node - Figma node to analyze
 * @param {Object} options - Analysis options
 * @param {boolean} options.skipInvisible - Skip invisible nodes (default: false)
 * @param {number} options.maxDepth - Maximum depth to traverse (default: 100)
 * @param {string} options.targetFramework - Target framework for notes
 * @param {boolean} options.includeRecommendations - Include recommendations (default: true)
 * @returns {AnalysisResult} Complete analysis result
 */
function analyzeNode(node, options = {}) {
  const {
    skipInvisible = false,
    maxDepth = 100,
    targetFramework = null,
    includeRecommendations = true
  } = options;

  // Create result
  const result = new AnalysisResult({
    nodeId: node.id || null,
    nodeName: node.name || 'Unknown',
    nodeType: node.type || 'UNKNOWN'
  });

  // Walk and collect metrics
  const { metrics, completed, maxDepthReached } = walkAndCollect(node, {
    maxDepth,
    skipInvisible
  });

  // Set all metrics on result
  for (const [metricName, value] of Object.entries(metrics)) {
    if (COMPLEXITY_METRICS[metricName]) {
      result.setMetric(metricName, value);
    }
  }

  // Calculate overall score
  result.calculateOverallScore();

  // Generate category summaries
  result.generateCategorySummaries();

  // Generate warnings
  const warnings = generateWarnings(metrics);
  for (const warning of warnings) {
    result.addWarning(warning.message, warning.severity, {
      metric: warning.metric,
      level: warning.level,
      value: warning.value
    });
  }

  // Add issues for critical metrics
  const criticalMetrics = getExceedingMetrics(metrics, COMPLEXITY_LEVELS.HIGH);
  for (const { metric, value, threshold, level, metricInfo } of criticalMetrics) {
    result.addIssue(
      metric,
      `${metricInfo.name} (${value} ${metricInfo.unit}) exceeds ${level} threshold (${threshold})`,
      level,
      { value, threshold }
    );
  }

  // Add walk status warning if incomplete
  if (!completed) {
    result.addWarning(
      `Analysis may be incomplete - max depth (${maxDepth}) reached at level ${maxDepthReached}`,
      SEVERITY_LEVELS.WARNING,
      { maxDepth, maxDepthReached }
    );
  }

  // Generate framework-specific notes if target specified
  if (targetFramework) {
    const notes = generateFrameworkNotes(targetFramework, metrics);
    result.frameworkNotes[targetFramework] = notes;
  }

  // Generate recommendations
  if (includeRecommendations) {
    generateRecommendations(result, metrics);
  }

  return result;
}

/**
 * Generate recommendations based on analysis
 * @param {AnalysisResult} result - Analysis result to update
 * @param {Object} metrics - Collected metrics
 */
function generateRecommendations(result, metrics) {
  // Structure recommendations
  if (metrics.maxDepth > THRESHOLDS.maxDepth.high) {
    result.addRecommendation(
      'Flatten Deep Nesting',
      'Consider reducing nesting depth by extracting deeply nested elements into separate components.',
      'high'
    );
  }

  // Component recommendations
  if (metrics.nestedComponentDepth > THRESHOLDS.nestedComponentDepth.medium) {
    result.addRecommendation(
      'Simplify Component Hierarchy',
      'Deeply nested components can be hard to maintain. Consider composition patterns or slot-based design.',
      'medium'
    );
  }

  // Layout recommendations
  if (metrics.mixedLayoutCount > THRESHOLDS.mixedLayoutCount.medium) {
    result.addRecommendation(
      'Standardize Layout Approach',
      'Mixed layout containers can cause unpredictable behavior. Choose either auto-layout or manual positioning consistently.',
      'high'
    );
  }

  if (metrics.absolutePositionCount > THRESHOLDS.absolutePositionCount.high) {
    result.addRecommendation(
      'Reduce Absolute Positioning',
      'Excessive absolute positioning makes responsive design difficult. Use auto-layout where possible.',
      'high'
    );
  }

  // Visual recommendations
  if (metrics.blendModeCount > THRESHOLDS.blendModeCount.medium) {
    result.addRecommendation(
      'Review Blend Mode Usage',
      'Not all blend modes translate well to all frameworks. Test visual fidelity early.',
      'medium'
    );
  }

  if (metrics.maskCount > THRESHOLDS.maskCount.medium) {
    result.addRecommendation(
      'Simplify Masking',
      'Complex masks often require SVG or canvas rendering. Consider simpler alternatives.',
      'medium'
    );
  }

  // Performance recommendations
  if (metrics.nodeCount > THRESHOLDS.nodeCount.high) {
    result.addRecommendation(
      'Split Large Designs',
      'Large node counts can impact both transformation and runtime performance. Consider splitting into smaller components.',
      'high'
    );
  }

  if (metrics.effectCount > THRESHOLDS.effectCount.high) {
    result.addRecommendation(
      'Optimize Visual Effects',
      'Many effects can impact rendering performance, especially on mobile. Review necessity of each effect.',
      'medium'
    );
  }

  // State management recommendations
  if (metrics.variableBindingCount > THRESHOLDS.variableBindingCount.medium) {
    result.addRecommendation(
      'Plan State Architecture',
      'Many variable bindings suggest complex state. Design your state management approach before transformation.',
      'high'
    );
  }
}

/**
 * Analyze an entire Figma document
 * @param {Object} document - Figma document object with pages
 * @param {Object} options - Analysis options
 * @param {string[]} options.pageIds - Specific page IDs to analyze (all if empty)
 * @param {string} options.targetFramework - Target framework for notes
 * @returns {Object} Document analysis with per-page results
 */
function analyzeDocument(document, options = {}) {
  const {
    pageIds = [],
    targetFramework = null,
    ...nodeOptions
  } = options;

  const startTime = Date.now();
  const pageResults = [];
  let totalNodeCount = 0;
  let highestScore = 0;
  let overallLevel = COMPLEXITY_LEVELS.LOW;

  // Get pages to analyze
  const pages = document.children || [];
  const pagesToAnalyze = pageIds.length > 0
    ? pages.filter(p => pageIds.includes(p.id))
    : pages;

  // Analyze each page
  for (const page of pagesToAnalyze) {
    if (page.type !== 'CANVAS' && page.type !== 'PAGE') continue;

    const pageResult = analyzeNode(page, {
      ...nodeOptions,
      targetFramework
    });

    pageResults.push({
      pageId: page.id,
      pageName: page.name,
      result: pageResult.toJSON()
    });

    totalNodeCount += pageResult.metrics.nodeCount;
    if (pageResult.overallScore > highestScore) {
      highestScore = pageResult.overallScore;
      overallLevel = pageResult.complexityLevel;
    }
  }

  // Aggregate warnings and issues
  const allWarnings = [];
  const allIssues = [];
  for (const { result } of pageResults) {
    allWarnings.push(...result.warnings.map(w => ({
      ...w,
      page: result.meta.nodeName
    })));
    allIssues.push(...result.issues.map(i => ({
      ...i,
      page: result.meta.nodeName
    })));
  }

  const analysisTime = Date.now() - startTime;

  return {
    meta: {
      analyzedAt: new Date().toISOString(),
      documentName: document.name || 'Unknown Document',
      pageCount: pagesToAnalyze.length,
      totalNodeCount,
      analysisTimeMs: analysisTime,
      targetFramework
    },
    summary: {
      highestComplexityScore: highestScore,
      overallComplexityLevel: overallLevel,
      totalWarnings: allWarnings.length,
      totalIssues: allIssues.length,
      recommendation: getDocumentRecommendation(highestScore, overallLevel)
    },
    pages: pageResults,
    aggregatedWarnings: allWarnings,
    aggregatedIssues: allIssues
  };
}

/**
 * Get recommendation for entire document
 * @param {number} score - Highest complexity score
 * @param {string} level - Overall complexity level
 * @returns {Object} Recommendation object
 */
function getDocumentRecommendation(score, level) {
  if (level === COMPLEXITY_LEVELS.LOW) {
    return {
      proceed: true,
      confidence: 'high',
      message: 'Document complexity is low. Automated transformation should work well.',
      suggestedApproach: 'Full automation'
    };
  }
  if (level === COMPLEXITY_LEVELS.MEDIUM) {
    return {
      proceed: true,
      confidence: 'medium',
      message: 'Document has moderate complexity. Review warnings before proceeding.',
      suggestedApproach: 'Automated with manual review'
    };
  }
  if (level === COMPLEXITY_LEVELS.HIGH) {
    return {
      proceed: false,
      confidence: 'low',
      message: 'Document is highly complex. Consider component-by-component transformation.',
      suggestedApproach: 'Incremental transformation'
    };
  }
  return {
    proceed: false,
    confidence: 'none',
    message: 'Document complexity is critical. Manual implementation recommended.',
    suggestedApproach: 'Manual implementation with design reference'
  };
}

/**
 * Quick complexity check for a node
 * Returns a simple pass/fail with basic info
 * @param {Object} node - Figma node
 * @param {string} level - Threshold level to check against (default: high)
 * @returns {Object} Quick check result
 */
function quickComplexityCheck(node, level = COMPLEXITY_LEVELS.HIGH) {
  const { metrics, completed } = walkAndCollect(node, { maxDepth: 50 });

  const exceeding = getExceedingMetrics(metrics, level);
  const pass = exceeding.length === 0;

  return {
    pass,
    nodeCount: metrics.nodeCount,
    maxDepth: metrics.maxDepth,
    exceedingCount: exceeding.length,
    criticalMetrics: exceeding.slice(0, 3).map(e => e.metric),
    completed
  };
}

/**
 * Compare complexity of multiple nodes
 * @param {Object[]} nodes - Array of Figma nodes
 * @returns {Object[]} Sorted array with complexity info
 */
function compareNodeComplexity(nodes) {
  const results = nodes.map(node => {
    const subtree = calculateSubtreeComplexity(node);
    return {
      nodeId: node.id,
      nodeName: node.name,
      nodeType: node.type,
      ...subtree
    };
  });

  // Sort by complexity score descending
  results.sort((a, b) => b.overallScore - a.overallScore);

  return results;
}

// =============================================================================
// EXPORTS
// =============================================================================

module.exports = {
  // Schema
  COMPLEXITY_METRICS,
  THRESHOLDS,
  SEVERITY_LEVELS,
  COMPLEXITY_LEVELS,
  // Classes
  AnalysisResult,
  // Helper functions
  getMetricsByCategory,
  getMetricCategories,
  getThresholdLevel,
  exceedsThreshold,
  getExceedingMetrics,
  // Node walking
  createWalkContext,
  collectNodeMetrics,
  walkNodes,
  walkAndCollect,
  calculateSubtreeComplexity,
  isContainerNode,
  CONTAINER_TYPES,
  VECTOR_TYPES,
  // Warning generation
  WARNING_TEMPLATES,
  generateWarnings,
  // Framework notes
  FRAMEWORK_NOTES,
  generateFrameworkNotes,
  getSupportedFrameworks,
  // Main analysis functions
  analyzeNode,
  analyzeDocument,
  generateRecommendations,
  getDocumentRecommendation,
  quickComplexityCheck,
  compareNodeComplexity
};

// =============================================================================
// UNIT TEST STUBS (for documentation)
// =============================================================================

/*
Unit tests should cover:

1. analyzeNode:
   - Returns AnalysisResult with populated metrics
   - Calculates correct overall score
   - Generates warnings for exceeding metrics
   - Includes framework notes when targetFramework specified
   - Handles empty/null nodes gracefully

2. analyzeDocument:
   - Analyzes all pages by default
   - Filters pages when pageIds provided
   - Aggregates warnings and issues across pages
   - Returns correct highest complexity score
   - Includes timing information

3. generateWarnings:
   - Creates warnings for metrics exceeding thresholds
   - Sorts by severity (critical first)
   - Respects skipMetrics option
   - Templates are correctly populated

4. generateFrameworkNotes:
   - Returns notes for valid framework
   - Handles unknown framework gracefully
   - Only includes notes for exceeding metrics

5. quickComplexityCheck:
   - Returns pass/fail correctly
   - Identifies critical metrics
   - Handles deep trees with maxDepth limit

6. compareNodeComplexity:
   - Sorts by complexity descending
   - Includes all node info
*/
