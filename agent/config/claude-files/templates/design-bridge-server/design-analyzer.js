/**
 * Design Analyzer
 * Analyzes design components for patterns, structure, and semantics
 *
 * This is a facade that aggregates multiple specialized analyzers
 */

const EventEmitter = require('events');
const ComponentAnalyzer = require('./component-analyzer');
const DesignPatternAnalyzer = require('./design-pattern-analyzer');
const SemanticAnalyzer = require('./semantic-analyzer');
const SpacingAnalyzer = require('./spacing-analyzer');

class DesignAnalyzer extends EventEmitter {
  constructor(options = {}) {
    super();

    this.options = options;

    // Initialize specialized analyzers
    this.componentAnalyzer = new ComponentAnalyzer(options);
    this.patternAnalyzer = new DesignPatternAnalyzer(options);
    this.semanticAnalyzer = new SemanticAnalyzer(options);
    this.spacingAnalyzer = new SpacingAnalyzer(options);
  }

  /**
   * Analyze design component
   */
  async analyze(component, options = {}) {
    const results = {
      component: null,
      patterns: null,
      semantics: null,
      spacing: null,
      timestamp: new Date().toISOString()
    };

    try {
      // Component analysis
      if (this.componentAnalyzer && typeof this.componentAnalyzer.analyze === 'function') {
        results.component = await this.componentAnalyzer.analyze(component);
      }

      // Pattern analysis
      if (this.patternAnalyzer && typeof this.patternAnalyzer.analyze === 'function') {
        results.patterns = await this.patternAnalyzer.analyze(component);
      }

      // Semantic analysis
      if (this.semanticAnalyzer && typeof this.semanticAnalyzer.analyze === 'function') {
        results.semantics = await this.semanticAnalyzer.analyze(component);
      }

      // Spacing analysis
      if (this.spacingAnalyzer && typeof this.spacingAnalyzer.analyze === 'function') {
        results.spacing = await this.spacingAnalyzer.analyze(component);
      }

      this.emit('analysis:complete', results);
      return results;

    } catch (error) {
      this.emit('analysis:error', error);
      throw error;
    }
  }

  /**
   * Analyze multiple components in batch
   */
  async analyzeBatch(components, options = {}) {
    const results = [];

    for (const component of components) {
      const result = await this.analyze(component, options);
      results.push(result);
    }

    return results;
  }
}

module.exports = DesignAnalyzer;
