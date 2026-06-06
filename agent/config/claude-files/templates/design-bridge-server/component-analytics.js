/**
 * component-analytics.js
 * Sprint 6.3: Component Analytics & Metrics
 *
 * Provides component usage analytics and metrics:
 * - Usage tracking
 * - Performance metrics
 * - Bundle size analysis
 * - Dependency graphs
 * - Quality scores
 */

const EventEmitter = require('events');
const crypto = require('crypto');

/**
 * Metric categories
 */
const METRIC_CATEGORIES = {
  usage: 'usage',
  performance: 'performance',
  quality: 'quality',
  complexity: 'complexity',
  accessibility: 'accessibility'
};

/**
 * Quality thresholds
 */
const QUALITY_THRESHOLDS = {
  excellent: 90,
  good: 75,
  acceptable: 60,
  needsWork: 40,
  poor: 0
};

/**
 * Complexity weights for scoring
 */
const COMPLEXITY_WEIGHTS = {
  props: 2,
  states: 3,
  effects: 4,
  dependencies: 1,
  linesOfCode: 0.01,
  cyclomaticComplexity: 5
};

class ComponentAnalytics extends EventEmitter {
  constructor(options = {}) {
    super();

    this.metricsStore = new Map();
    this.usageData = new Map();
    this.thresholds = { ...QUALITY_THRESHOLDS, ...options.thresholds };
    this.weights = { ...COMPLEXITY_WEIGHTS, ...options.weights };

    this.stats = {
      componentsAnalyzed: 0,
      metricsCollected: 0,
      reportsGenerated: 0
    };
  }

  /**
   * Analyze a component and collect metrics
   * @param {Object} component - Component data
   * @param {Object} options - Analysis options
   * @returns {Object} Component analytics
   */
  analyzeComponent(component, options = {}) {
    const {
      includeUsage = true,
      includePerformance = true,
      includeQuality = true,
      includeDependencies = true
    } = options;

    const analytics = {
      component: component.name,
      timestamp: new Date().toISOString(),
      metrics: {}
    };

    // Collect usage metrics
    if (includeUsage) {
      analytics.metrics.usage = this.collectUsageMetrics(component);
    }

    // Collect performance metrics
    if (includePerformance) {
      analytics.metrics.performance = this.collectPerformanceMetrics(component);
    }

    // Collect quality metrics
    if (includeQuality) {
      analytics.metrics.quality = this.collectQualityMetrics(component);
    }

    // Collect dependency metrics
    if (includeDependencies) {
      analytics.metrics.dependencies = this.collectDependencyMetrics(component);
    }

    // Calculate overall scores
    analytics.scores = this.calculateScores(analytics.metrics);

    // Store metrics
    this.metricsStore.set(component.name, analytics);

    this.stats.componentsAnalyzed++;
    this.emit('component:analyzed', { component: component.name, scores: analytics.scores });

    return analytics;
  }

  /**
   * Collect usage metrics
   */
  collectUsageMetrics(component) {
    const props = Object.keys(component.props || {});
    const requiredProps = props.filter(p => component.props[p].required);

    return {
      propsCount: props.length,
      requiredPropsCount: requiredProps.length,
      optionalPropsCount: props.length - requiredProps.length,
      hasDefaultExport: true,
      hasNamedExports: true,
      variants: this.detectVariants(component),
      estimatedUsageComplexity: this.calculateUsageComplexity(component)
    };
  }

  /**
   * Collect performance metrics
   */
  collectPerformanceMetrics(component) {
    // Simulated metrics - in real implementation would analyze actual bundle
    const propsCount = Object.keys(component.props || {}).length;

    return {
      estimatedBundleSize: this.estimateBundleSize(component),
      treeshakeable: true,
      hasMemoization: false,
      hasLazyLoading: false,
      renderComplexity: this.calculateRenderComplexity(component),
      recommendations: this.generatePerformanceRecommendations(component)
    };
  }

  /**
   * Collect quality metrics
   */
  collectQualityMetrics(component) {
    const props = component.props || {};
    const propsWithTypes = Object.values(props).filter(p => p.type).length;
    const propsWithDescriptions = Object.values(props).filter(p => p.description).length;
    const propsWithDefaults = Object.values(props).filter(p => p.default !== undefined).length;
    const totalProps = Object.keys(props).length || 1;

    return {
      typesCoverage: Math.round((propsWithTypes / totalProps) * 100),
      documentationCoverage: Math.round((propsWithDescriptions / totalProps) * 100),
      defaultsCoverage: Math.round((propsWithDefaults / totalProps) * 100),
      hasDescription: !!component.description,
      hasExamples: !!(component.examples && component.examples.length > 0),
      hasTests: !!(component.tests && component.tests.length > 0),
      qualityScore: this.calculateQualityScore(component)
    };
  }

  /**
   * Collect dependency metrics
   */
  collectDependencyMetrics(component) {
    const dependencies = component.dependencies || [];
    const peerDependencies = component.peerDependencies || [];

    return {
      dependencyCount: dependencies.length,
      peerDependencyCount: peerDependencies.length,
      externalDependencies: dependencies.filter(d => !d.startsWith('.')),
      internalDependencies: dependencies.filter(d => d.startsWith('.')),
      dependencyGraph: this.buildDependencyGraph(component),
      circularDependencies: [],
      unusedDependencies: []
    };
  }

  /**
   * Detect component variants
   */
  detectVariants(component) {
    const variants = [];
    const props = component.props || {};

    Object.entries(props).forEach(([name, config]) => {
      if (config.options || config.enum) {
        variants.push({
          prop: name,
          options: config.options || config.enum,
          count: (config.options || config.enum).length
        });
      }
    });

    return variants;
  }

  /**
   * Calculate usage complexity score (0-100)
   */
  calculateUsageComplexity(component) {
    const props = component.props || {};
    const propsCount = Object.keys(props).length;
    const requiredCount = Object.values(props).filter(p => p.required).length;

    // More props and more required props = higher complexity
    let complexity = 0;
    complexity += Math.min(propsCount * 3, 30);
    complexity += requiredCount * 5;

    // Variants add complexity
    const variants = this.detectVariants(component);
    complexity += variants.reduce((acc, v) => acc + v.count, 0);

    return Math.min(100, complexity);
  }

  /**
   * Estimate bundle size in bytes
   */
  estimateBundleSize(component) {
    // Rough estimation based on component complexity
    const baseSize = 500; // Base component overhead
    const propsSize = Object.keys(component.props || {}).length * 50;
    const descriptionSize = (component.description || '').length;

    return baseSize + propsSize + descriptionSize;
  }

  /**
   * Calculate render complexity (1-10 scale)
   */
  calculateRenderComplexity(component) {
    const props = component.props || {};
    const propsCount = Object.keys(props).length;

    // Simple heuristic based on props
    if (propsCount <= 3) return 1;
    if (propsCount <= 6) return 3;
    if (propsCount <= 10) return 5;
    if (propsCount <= 15) return 7;
    return 9;
  }

  /**
   * Generate performance recommendations
   */
  generatePerformanceRecommendations(component) {
    const recommendations = [];
    const props = component.props || {};
    const propsCount = Object.keys(props).length;

    if (propsCount > 10) {
      recommendations.push({
        type: 'optimization',
        message: 'Consider splitting into smaller components',
        priority: 'medium'
      });
    }

    // Check for callback props that might benefit from useCallback
    const callbackProps = Object.entries(props).filter(([_, config]) =>
      config.type === 'function'
    );

    if (callbackProps.length > 2) {
      recommendations.push({
        type: 'memoization',
        message: 'Multiple callback props detected - consider React.memo',
        priority: 'low'
      });
    }

    return recommendations;
  }

  /**
   * Calculate quality score (0-100)
   */
  calculateQualityScore(component) {
    const props = component.props || {};
    const totalProps = Object.keys(props).length || 1;

    let score = 0;

    // Documentation (40 points max)
    if (component.description) score += 10;
    const docsCount = Object.values(props).filter(p => p.description).length;
    score += Math.round((docsCount / totalProps) * 30);

    // Types (30 points max)
    const typedCount = Object.values(props).filter(p => p.type).length;
    score += Math.round((typedCount / totalProps) * 30);

    // Defaults (20 points max)
    const defaultsCount = Object.values(props).filter(p => p.default !== undefined).length;
    score += Math.round((defaultsCount / totalProps) * 20);

    // Features (10 points max)
    if (component.features && component.features.length > 0) score += 5;
    if (component.examples && component.examples.length > 0) score += 5;

    return Math.min(100, score);
  }

  /**
   * Build dependency graph
   */
  buildDependencyGraph(component) {
    const dependencies = component.dependencies || [];

    return {
      nodes: [
        { id: component.name, type: 'component' },
        ...dependencies.map(d => ({ id: d, type: 'dependency' }))
      ],
      edges: dependencies.map(d => ({
        from: component.name,
        to: d,
        type: 'depends-on'
      }))
    };
  }

  /**
   * Calculate overall scores
   */
  calculateScores(metrics) {
    const scores = {};

    if (metrics.usage) {
      // Lower complexity = better score
      scores.usability = Math.max(0, 100 - metrics.usage.estimatedUsageComplexity);
    }

    if (metrics.performance) {
      // Smaller bundle = better score
      const bundleScore = Math.max(0, 100 - (metrics.performance.estimatedBundleSize / 100));
      const complexityScore = (10 - metrics.performance.renderComplexity) * 10;
      scores.performance = Math.round((bundleScore + complexityScore) / 2);
    }

    if (metrics.quality) {
      scores.quality = metrics.quality.qualityScore;
    }

    if (metrics.dependencies) {
      // Fewer dependencies = better score
      const depScore = Math.max(0, 100 - metrics.dependencies.dependencyCount * 10);
      scores.maintainability = depScore;
    }

    // Overall score
    const scoreValues = Object.values(scores);
    scores.overall = Math.round(
      scoreValues.reduce((a, b) => a + b, 0) / scoreValues.length
    );

    return scores;
  }

  /**
   * Track component usage
   * @param {string} componentName - Component name
   * @param {Object} context - Usage context
   */
  trackUsage(componentName, context = {}) {
    const existing = this.usageData.get(componentName) || {
      totalUsages: 0,
      contexts: [],
      firstUsed: new Date().toISOString(),
      lastUsed: null
    };

    existing.totalUsages++;
    existing.lastUsed = new Date().toISOString();

    if (context.file) {
      existing.contexts.push({
        file: context.file,
        line: context.line,
        timestamp: new Date().toISOString()
      });
    }

    this.usageData.set(componentName, existing);
    this.emit('usage:tracked', { component: componentName, count: existing.totalUsages });
  }

  /**
   * Generate analytics dashboard data
   * @returns {Object} Dashboard data
   */
  generateDashboard() {
    const components = Array.from(this.metricsStore.entries());

    const dashboard = {
      summary: {
        totalComponents: components.length,
        averageQuality: 0,
        averagePerformance: 0,
        topPerformers: [],
        needsAttention: []
      },
      byCategory: {
        quality: { excellent: 0, good: 0, acceptable: 0, needsWork: 0, poor: 0 },
        performance: { excellent: 0, good: 0, acceptable: 0, needsWork: 0, poor: 0 }
      },
      trends: [],
      recommendations: []
    };

    if (components.length === 0) {
      return dashboard;
    }

    // Calculate averages and categorize
    let totalQuality = 0;
    let totalPerformance = 0;

    components.forEach(([name, analytics]) => {
      const { scores } = analytics;

      if (scores.quality !== undefined) {
        totalQuality += scores.quality;
        this.categorizeScore(dashboard.byCategory.quality, scores.quality);
      }

      if (scores.performance !== undefined) {
        totalPerformance += scores.performance;
        this.categorizeScore(dashboard.byCategory.performance, scores.performance);
      }

      // Track top performers and needs attention
      if (scores.overall >= this.thresholds.excellent) {
        dashboard.summary.topPerformers.push({ name, score: scores.overall });
      } else if (scores.overall < this.thresholds.acceptable) {
        dashboard.summary.needsAttention.push({ name, score: scores.overall });
      }
    });

    dashboard.summary.averageQuality = Math.round(totalQuality / components.length);
    dashboard.summary.averagePerformance = Math.round(totalPerformance / components.length);

    // Sort lists
    dashboard.summary.topPerformers.sort((a, b) => b.score - a.score);
    dashboard.summary.needsAttention.sort((a, b) => a.score - b.score);

    // Generate recommendations
    dashboard.recommendations = this.generateDashboardRecommendations(dashboard);

    this.stats.reportsGenerated++;
    this.emit('dashboard:generated', dashboard.summary);

    return dashboard;
  }

  /**
   * Categorize score into threshold bucket
   */
  categorizeScore(categories, score) {
    if (score >= this.thresholds.excellent) categories.excellent++;
    else if (score >= this.thresholds.good) categories.good++;
    else if (score >= this.thresholds.acceptable) categories.acceptable++;
    else if (score >= this.thresholds.needsWork) categories.needsWork++;
    else categories.poor++;
  }

  /**
   * Generate dashboard recommendations
   */
  generateDashboardRecommendations(dashboard) {
    const recommendations = [];

    if (dashboard.byCategory.quality.poor > 0) {
      recommendations.push({
        type: 'quality',
        priority: 'high',
        message: `${dashboard.byCategory.quality.poor} component(s) have poor quality scores. Consider adding documentation and types.`
      });
    }

    if (dashboard.byCategory.performance.needsWork > 0) {
      recommendations.push({
        type: 'performance',
        priority: 'medium',
        message: `${dashboard.byCategory.performance.needsWork} component(s) may benefit from performance optimization.`
      });
    }

    if (dashboard.summary.averageQuality < this.thresholds.good) {
      recommendations.push({
        type: 'documentation',
        priority: 'high',
        message: 'Overall documentation quality is below target. Focus on adding prop descriptions and examples.'
      });
    }

    return recommendations;
  }

  /**
   * Generate component report
   * @param {string} componentName - Component name
   * @returns {Object} Component report
   */
  generateComponentReport(componentName) {
    const analytics = this.metricsStore.get(componentName);
    const usage = this.usageData.get(componentName);

    if (!analytics) {
      return { error: `No analytics found for ${componentName}` };
    }

    return {
      component: componentName,
      analytics,
      usage: usage || { totalUsages: 0, contexts: [] },
      grade: this.calculateGrade(analytics.scores.overall),
      insights: this.generateInsights(analytics),
      generatedAt: new Date().toISOString()
    };
  }

  /**
   * Calculate letter grade from score
   */
  calculateGrade(score) {
    if (score >= 90) return 'A';
    if (score >= 80) return 'B';
    if (score >= 70) return 'C';
    if (score >= 60) return 'D';
    return 'F';
  }

  /**
   * Generate insights for a component
   */
  generateInsights(analytics) {
    const insights = [];
    const { metrics, scores } = analytics;

    // Quality insights
    if (metrics.quality) {
      if (metrics.quality.typesCoverage < 100) {
        insights.push({
          type: 'quality',
          message: `TypeScript coverage is ${metrics.quality.typesCoverage}%. Consider adding types to all props.`
        });
      }

      if (metrics.quality.documentationCoverage < 80) {
        insights.push({
          type: 'documentation',
          message: `Documentation coverage is ${metrics.quality.documentationCoverage}%. Adding descriptions improves usability.`
        });
      }
    }

    // Performance insights
    if (metrics.performance) {
      if (metrics.performance.estimatedBundleSize > 2000) {
        insights.push({
          type: 'performance',
          message: 'Component may be larger than optimal. Consider code splitting.'
        });
      }

      insights.push(...metrics.performance.recommendations);
    }

    // Usage insights
    if (metrics.usage) {
      if (metrics.usage.estimatedUsageComplexity > 50) {
        insights.push({
          type: 'usability',
          message: 'Component API may be complex. Consider simplifying or providing helper components.'
        });
      }
    }

    return insights;
  }

  /**
   * Export analytics data
   * @param {string} format - Export format ('json', 'csv')
   * @returns {string} Exported data
   */
  exportAnalytics(format = 'json') {
    const data = {
      components: Array.from(this.metricsStore.entries()).map(([name, analytics]) => ({
        name,
        ...analytics
      })),
      usage: Array.from(this.usageData.entries()).map(([name, usage]) => ({
        name,
        ...usage
      })),
      exportedAt: new Date().toISOString()
    };

    if (format === 'csv') {
      return this.convertToCSV(data.components);
    }

    return JSON.stringify(data, null, 2);
  }

  /**
   * Convert analytics to CSV format
   */
  convertToCSV(components) {
    if (components.length === 0) return '';

    const headers = ['Component', 'Quality Score', 'Performance Score', 'Overall Score', 'Grade'];
    const rows = components.map(c => [
      c.name,
      c.scores?.quality || 'N/A',
      c.scores?.performance || 'N/A',
      c.scores?.overall || 'N/A',
      this.calculateGrade(c.scores?.overall || 0)
    ]);

    return [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
  }

  /**
   * Get all metrics
   */
  getAllMetrics() {
    return Array.from(this.metricsStore.entries()).map(([name, data]) => ({
      name,
      ...data
    }));
  }

  /**
   * Get usage data
   */
  getUsageData() {
    return Array.from(this.usageData.entries()).map(([name, data]) => ({
      name,
      ...data
    }));
  }

  /**
   * Get statistics
   */
  getStats() {
    return {
      ...this.stats,
      metricsCollected: this.metricsStore.size
    };
  }

  /**
   * Reset all data
   */
  reset() {
    this.metricsStore.clear();
    this.usageData.clear();
    this.stats = {
      componentsAnalyzed: 0,
      metricsCollected: 0,
      reportsGenerated: 0
    };
  }
}

// Export singleton and class
const componentAnalytics = new ComponentAnalytics();

module.exports = {
  ComponentAnalytics,
  componentAnalytics,
  METRIC_CATEGORIES,
  QUALITY_THRESHOLDS,
  COMPLEXITY_WEIGHTS
};
