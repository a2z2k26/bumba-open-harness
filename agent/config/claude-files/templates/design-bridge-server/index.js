/**
 * Design Bridge Module
 * Central export for all Design Bridge components
 */

module.exports = {
  // Core Bridge
  DesignBridge: require('./design-bridge'),

  // Token Processing
  TokenValidator: require('./token-validator'),
  TokenNormalizer: require('./token-normalizer'),

  // Export System
  ExportEngine: require('./export-engine'),
  ExportFormatters: require('./export-formatters'),

  // Analysis Tools
  SemanticAnalyzer: require('./semantic-analyzer'),
  QualityMetrics: require('./quality-metrics'),
  PatternRecognizer: require('./pattern-recognizer'),

  // MCP Integration
  MCPBridge: require('./mcp-bridge-interface'),

  // Talk-to-Figma MCP Server
  TalkToFigma: require('./mcp/server'),

  // Plugin System
  PluginBridge: require('./plugin-bridge'),

  // Story Generation System
  StoryGenerator: require('./story-generator'),
  StoryGeneratorBase: require('./story-generator-base'),
  StoryRegistry: require('./story-registry'),

  // Optimizer System
  OptimizerRegistry: require('./optimizer-registry').OptimizerRegistry,
  getOptimizerRegistry: require('./optimizer-registry').getOptimizerRegistry,

  // Utilities
  utils: {
    validateToken: (token, rules) => {
      const validator = new (require('./token-validator'))();
      return validator.validateToken(token, rules);
    },

    exportTokens: async (tokens, format, options = {}) => {
      const exporter = new (require('./export-engine'))();
      return await exporter.export(tokens, format, options);
    },

    analyzeTokens: async (tokens) => {
      const analyzer = new (require('./semantic-analyzer'))();
      return await analyzer.analyze(tokens);
    },

    calculateMetrics: async (tokens) => {
      const metrics = new (require('./quality-metrics'))();
      return await metrics.calculate(tokens);
    },

    recognizePatterns: async (tokens) => {
      const recognizer = new (require('./pattern-recognizer'))();
      return await recognizer.recognize(tokens);
    }
  },

  // Constants
  SUPPORTED_FORMATS: ['css', 'scss', 'less', 'stylus', 'js', 'ts', 'json', 'yaml', 'swift', 'kotlin', 'dart', 'xml'],

  // Version
  version: '1.0.0'
};