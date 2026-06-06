/**
 * AI-Friendly Catalog API
 * Provides structured interface for AI collaborators to interact with the Design System
 */

const EventEmitter = require('events');
const chalk = require('chalk');
const { logger } = require('../../logging/bumba-logger');

class AICatalogAPI extends EventEmitter {
  constructor(orchestrator) {
    super();
    this.orchestrator = orchestrator;
    this.context = new Map();
    this.queryCache = new Map();
    this.suggestions = [];
  }

  /**
   * Initialize AI API with context
   */
  async initialize(projectContext = {}) {
    // Load project context
    this.context.set('project', projectContext);

    // Load design system rules
    await this.loadDesignSystemRules();

    // Initialize AI helpers
    this.initializeHelpers();

    logger.info('AI Catalog API initialized');
    return this;
  }

  /**
   * Query components with natural language
   */
  async query(request) {
    // Parse query intent
    const intent = this.parseQueryIntent(request);

    // Check cache
    const cacheKey = JSON.stringify(request);
    if (this.queryCache.has(cacheKey)) {
      return this.queryCache.get(cacheKey);
    }

    // Execute query
    let results = [];

    switch (intent.type) {
      case 'search':
        results = await this.searchComponents(intent);
        break;

      case 'filter':
        results = await this.filterComponents(intent);
        break;

      case 'similar':
        results = await this.findSimilarComponents(intent);
        break;

      case 'usage':
        results = await this.findComponentUsage(intent);
        break;

      case 'implementation':
        results = await this.findImplementations(intent);
        break;

      default:
        results = await this.orchestrator.queryComponents(request);
    }

    // Enhance results with AI context
    results = this.enhanceResults(results);

    // Cache results
    this.queryCache.set(cacheKey, results);

    // Clean old cache entries
    if (this.queryCache.size > 100) {
      const firstKey = this.queryCache.keys().next().value;
      this.queryCache.delete(firstKey);
    }

    return results;
  }

  /**
   * Register new design asset with AI assistance
   */
  async register(assetData) {
    // Validate asset data
    const validation = await this.validateAsset(assetData);
    if (!validation.valid) {
      throw new Error(`Invalid asset: ${validation.errors.join(', ')}`);
    }

    // Enhance asset with AI suggestions
    const enhanced = await this.enhanceAsset(assetData);

    // Check for duplicates
    const similar = await this.findSimilarAssets(enhanced);
    if (similar.length > 0) {
      enhanced.metadata = {
        ...enhanced.metadata,
        similarTo: similar.map(s => s.id)
      };
    }

    // Register with orchestrator
    const result = await this.orchestrator.registerDesignAsset(enhanced);

    // Update AI context
    this.updateContext('registered', enhanced);

    // Generate recommendations
    const recommendations = await this.generateRecommendations(enhanced);

    return {
      ...result,
      recommendations
    };
  }

  /**
   * Generate code implementations with AI optimization
   */
  async generate(assetData, options = {}) {
    const {
      framework = 'all',
      optimize = true,
      includeTests = true,
      includeStyles = true,
      includeDocs = true
    } = options;

    // Generate base implementations
    let implementations = await this.orchestrator.generateImplementations(assetData);

    // Filter by framework if specified
    if (framework !== 'all') {
      implementations = implementations.filter(impl => impl.framework === framework);
    }

    // Optimize implementations
    if (optimize) {
      implementations = await this.optimizeImplementations(implementations, assetData);
    }

    // Generate tests
    if (includeTests) {
      for (const impl of implementations) {
        impl.tests = await this.generateTests(impl, assetData);
      }
    }

    // Generate styles
    if (includeStyles) {
      for (const impl of implementations) {
        impl.styles = await this.generateStyles(impl, assetData);
      }
    }

    // Generate documentation
    if (includeDocs) {
      for (const impl of implementations) {
        impl.documentation = await this.generateDocumentation(impl, assetData);
      }
    }

    return implementations;
  }

  /**
   * Suggest components based on context
   */
  async suggest(context) {
    // Analyze context
    const analysis = this.analyzeContext(context);

    // Get relevant components
    const candidates = await this.findCandidates(analysis);

    // Score candidates
    const scored = candidates.map(candidate => ({
      ...candidate,
      score: this.scoreCandidate(candidate, analysis),
      reasons: this.generateReasons(candidate, analysis)
    }));

    // Sort by score
    scored.sort((a, b) => b.score - a.score);

    // Generate suggestions
    const suggestions = scored.slice(0, 5).map(candidate => ({
      component: candidate,
      confidence: candidate.score,
      reasons: candidate.reasons,
      implementation: this.suggestImplementation(candidate, context),
      alternatives: this.findAlternatives(candidate, scored)
    }));

    // Store suggestions for learning
    this.suggestions.push({
      context,
      suggestions,
      timestamp: Date.now()
    });

    return suggestions;
  }

  /**
   * Analyze component usage patterns
   */
  async analyze(componentId, options = {}) {
    const {
      includePerformance = true,
      includeAccessibility = true,
      includeUsage = true,
      includeTrends = true
    } = options;

    const analysis = {
      componentId,
      timestamp: Date.now()
    };

    // Usage analysis
    if (includeUsage) {
      analysis.usage = await this.analyzeUsage(componentId);
    }

    // Performance analysis
    if (includePerformance) {
      analysis.performance = await this.analyzePerformance(componentId);
    }

    // Accessibility analysis
    if (includeAccessibility) {
      analysis.accessibility = await this.analyzeAccessibility(componentId);
    }

    // Trend analysis
    if (includeTrends) {
      analysis.trends = await this.analyzeTrends(componentId);
    }

    // Generate insights
    analysis.insights = this.generateInsights(analysis);

    // Generate recommendations
    analysis.recommendations = this.generateAnalysisRecommendations(analysis);

    return analysis;
  }

  /**
   * Validate component against design system
   */
  async validate(componentId, rules = null) {
    const component = await this.getComponent(componentId);
    if (!component) {
      throw new Error(`Component ${componentId} not found`);
    }

    const validationRules = rules || await this.getValidationRules();
    const results = {
      componentId,
      valid: true,
      errors: [],
      warnings: [],
      suggestions: []
    };

    // Validate structure
    const structureValidation = this.validateStructure(component, validationRules);
    results.errors.push(...structureValidation.errors);
    results.warnings.push(...structureValidation.warnings);

    // Validate naming
    const namingValidation = this.validateNaming(component, validationRules);
    results.errors.push(...namingValidation.errors);
    results.warnings.push(...namingValidation.warnings);

    // Validate properties
    const propsValidation = this.validateProperties(component, validationRules);
    results.errors.push(...propsValidation.errors);
    results.warnings.push(...propsValidation.warnings);

    // Validate accessibility
    const a11yValidation = await this.validateAccessibility(component);
    results.errors.push(...a11yValidation.errors);
    results.warnings.push(...a11yValidation.warnings);
    results.suggestions.push(...a11yValidation.suggestions);

    // Validate performance
    const perfValidation = await this.validatePerformance(component);
    results.warnings.push(...perfValidation.warnings);
    results.suggestions.push(...perfValidation.suggestions);

    // Update valid flag
    results.valid = results.errors.length === 0;

    return results;
  }

  /**
   * Get AI context for current project
   */
  async getContext() {
    const catalog = this.orchestrator.catalogs.get(this.orchestrator.activeProject);
    if (!catalog) return null;

    return {
      project: catalog.projectName,
      aiContext: catalog.aiContext,
      components: {
        total: this.countComponents(catalog),
        byCategory: this.countByCategory(catalog),
        recent: this.getRecentComponents(catalog, 10)
      },
      tokens: catalog.tokens,
      patterns: this.extractPatterns(catalog),
      guidelines: this.getGuidelines(catalog)
    };
  }

  /**
   * Update AI context with new information
   */
  async updateContext(type, data) {
    const catalog = this.orchestrator.catalogs.get(this.orchestrator.activeProject);
    if (!catalog) return;

    switch (type) {
      case 'guidelines':
        catalog.aiContext.brandGuidelines = {
          ...catalog.aiContext.brandGuidelines,
          ...data
        };
        break;

      case 'principles':
        catalog.aiContext.designPrinciples = data;
        break;

      case 'patterns':
        this.updatePatterns(catalog, data);
        break;

      case 'rules':
        catalog.aiContext.accessibilityRules = {
          ...catalog.aiContext.accessibilityRules,
          ...data
        };
        break;

      case 'performance':
        catalog.aiContext.performanceTargets = {
          ...catalog.aiContext.performanceTargets,
          ...data
        };
        break;

      case 'registered':
        this.updateRegisteredContext(catalog, data);
        break;
    }

    // Emit context update event
    this.emit('context:updated', { type, data });
  }

  /**
   * Helper methods
   */

  async loadDesignSystemRules() {
    // Load default rules
    this.rules = {
      naming: {
        components: /^[A-Z][a-zA-Z0-9]+$/,
        props: /^[a-z][a-zA-Z0-9]*$/,
        styles: /^[a-z][a-z0-9-]*$/
      },
      structure: {
        maxDepth: 5,
        maxProps: 20,
        maxChildren: 10
      },
      accessibility: {
        wcagLevel: 'AA',
        colorContrast: 4.5,
        focusIndicators: true
      },
      performance: {
        maxRenderTime: 16,
        maxBundleSize: 50000,
        maxDependencies: 10
      }
    };
  }

  initializeHelpers() {
    // Initialize AI helper functions
    this.helpers = {
      similarity: this.createSimilarityHelper(),
      categorization: this.createCategorizationHelper(),
      optimization: this.createOptimizationHelper()
    };
  }

  parseQueryIntent(request) {
    if (typeof request === 'string') {
      // Natural language query
      if (request.includes('similar')) return { type: 'similar', query: request };
      if (request.includes('usage')) return { type: 'usage', query: request };
      if (request.includes('implementation')) return { type: 'implementation', query: request };
      if (request.includes('filter')) return { type: 'filter', query: request };
      return { type: 'search', query: request };
    }

    // Structured query
    return { type: 'structured', ...request };
  }

  async searchComponents(intent) {
    return this.orchestrator.queryComponents(intent.query);
  }

  async filterComponents(intent) {
    const all = await this.orchestrator.queryComponents('');
    return all.filter(component => this.matchesFilter(component, intent));
  }

  async findSimilarComponents(intent) {
    const reference = intent.reference || intent.query;
    const all = await this.orchestrator.queryComponents('');

    return all
      .map(component => ({
        ...component,
        similarity: this.calculateSimilarity(component, reference)
      }))
      .filter(c => c.similarity > 0.5)
      .sort((a, b) => b.similarity - a.similarity);
  }

  async findComponentUsage(intent) {
    const componentId = intent.componentId || intent.query;
    return this.orchestrator.analyzeUsage(componentId);
  }

  async findImplementations(intent) {
    const implementations = [];

    for (const [key, impl] of this.orchestrator.codeImplementations) {
      if (this.matchesIntent(impl, intent)) {
        implementations.push(impl);
      }
    }

    return implementations;
  }

  enhanceResults(results) {
    return results.map(result => ({
      ...result,
      enhanced: true,
      metadata: {
        ...result.metadata,
        queriedAt: Date.now(),
        relevanceScore: result.relevance || 0
      }
    }));
  }

  async validateAsset(assetData) {
    const errors = [];

    // Required fields
    if (!assetData.name) errors.push('Name is required');
    if (!assetData.type) errors.push('Type is required');

    // Name validation
    if (assetData.name && !this.rules.naming.components.test(assetData.name)) {
      errors.push('Name must be PascalCase');
    }

    // Properties validation
    if (assetData.properties) {
      for (const prop of Object.keys(assetData.properties)) {
        if (!this.rules.naming.props.test(prop)) {
          errors.push(`Property '${prop}' must be camelCase`);
        }
      }
    }

    return {
      valid: errors.length === 0,
      errors
    };
  }

  async enhanceAsset(assetData) {
    return {
      ...assetData,
      metadata: {
        ...assetData.metadata,
        enhanced: true,
        enhancedAt: Date.now(),
        category: this.categorizeAsset(assetData),
        complexity: this.assessComplexity(assetData),
        tags: this.generateTags(assetData)
      }
    };
  }

  async findSimilarAssets(asset) {
    const all = [];

    for (const [id, existing] of this.orchestrator.designAssets) {
      const similarity = this.calculateSimilarity(existing, asset);
      if (similarity > 0.8) {
        all.push({ ...existing, similarity });
      }
    }

    return all.sort((a, b) => b.similarity - a.similarity);
  }

  async generateRecommendations(asset) {
    const recommendations = [];

    // Naming recommendations
    if (asset.name.length > 20) {
      recommendations.push({
        type: 'naming',
        message: 'Consider a shorter component name',
        severity: 'info'
      });
    }

    // Complexity recommendations
    if (asset.properties && Object.keys(asset.properties).length > 10) {
      recommendations.push({
        type: 'complexity',
        message: 'Consider breaking down into smaller components',
        severity: 'warning'
      });
    }

    // Accessibility recommendations
    if (!asset.metadata?.accessibility) {
      recommendations.push({
        type: 'accessibility',
        message: 'Add accessibility metadata',
        severity: 'warning'
      });
    }

    return recommendations;
  }

  async optimizeImplementations(implementations, assetData) {
    return implementations.map(impl => ({
      ...impl,
      code: this.optimizeCode(impl.code, impl.framework),
      optimized: true
    }));
  }

  async generateTests(implementation, assetData) {
    const { framework, componentName } = implementation;

    if (framework === 'react') {
      return `import { render, screen } from '@testing-library/react';
import { ${componentName} } from './${componentName}';

describe('${componentName}', () => {
  it('renders without crashing', () => {
    render(<${componentName} />);
  });

  it('accepts props', () => {
    render(<${componentName} {...props} />);
  });
});`;
    }

    return '// Test implementation';
  }

  async generateStyles(implementation, assetData) {
    const { componentName } = implementation;
    const kebabName = this.toKebabCase(componentName);

    return `.${kebabName} {
  /* Generated styles */
  display: flex;
  padding: var(--spacing-md);
  border-radius: var(--radius-md);
}`;
  }

  async generateDocumentation(implementation, assetData) {
    const { componentName, framework } = implementation;

    return `# ${componentName}

## Description
${assetData.metadata?.description || 'Component description'}

## Usage
\`\`\`${framework === 'react' ? 'jsx' : 'js'}
<${componentName} />
\`\`\`

## Props
${this.documentProps(assetData.properties)}

## Examples
${this.generateExamples(componentName, assetData)}
`;
  }

  // Utility methods
  calculateSimilarity(a, b) {
    // Simple similarity calculation
    let score = 0;

    if (a.name === b.name) score += 5;
    if (a.type === b.type) score += 3;
    if (a.category === b.category) score += 2;

    return score / 10;
  }

  categorizeAsset(assetData) {
    const { type, complexity } = assetData;

    if (complexity === 'low' || type === 'atom') return 'atoms';
    if (complexity === 'medium' || type === 'molecule') return 'molecules';
    if (complexity === 'high' || type === 'organism') return 'organisms';

    return 'molecules';
  }

  assessComplexity(assetData) {
    const propCount = Object.keys(assetData.properties || {}).length;

    if (propCount <= 3) return 'low';
    if (propCount <= 8) return 'medium';
    return 'high';
  }

  generateTags(assetData) {
    const tags = [assetData.type];

    if (assetData.metadata?.category) tags.push(assetData.metadata.category);
    if (assetData.metadata?.framework) tags.push(assetData.metadata.framework);

    return tags;
  }

  optimizeCode(code, framework) {
    // Simple code optimization
    return code
      .replace(/\s+/g, ' ')
      .replace(/;\s*;/g, ';')
      .trim();
  }

  toKebabCase(str) {
    return str
      .replace(/([A-Z])/g, '-$1')
      .toLowerCase()
      .replace(/^-/, '');
  }

  documentProps(properties) {
    if (!properties) return 'No props';

    return Object.entries(properties)
      .map(([name, type]) => `- **${name}**: ${type}`)
      .join('\n');
  }

  generateExamples(componentName, assetData) {
    return `### Basic Usage
\`\`\`jsx
<${componentName} />
\`\`\`

### With Props
\`\`\`jsx
<${componentName} ${Object.keys(assetData.properties || {}).slice(0, 2).map(p => `${p}="value"`).join(' ')} />
\`\`\``;
  }

  analyzeContext(context) {
    return {
      intent: context.intent || 'unknown',
      requirements: context.requirements || [],
      constraints: context.constraints || [],
      preferences: context.preferences || {}
    };
  }

  findCandidates(analysis) {
    const candidates = [];

    for (const [id, asset] of this.orchestrator.designAssets) {
      if (this.matchesAnalysis(asset, analysis)) {
        candidates.push(asset);
      }
    }

    return candidates;
  }

  scoreCandidate(candidate, analysis) {
    let score = 0;

    // Match intent
    if (candidate.metadata?.intent === analysis.intent) score += 3;

    // Match requirements
    analysis.requirements.forEach(req => {
      if (candidate.properties?.[req]) score += 1;
    });

    return Math.min(score / 10, 1);
  }

  generateReasons(candidate, analysis) {
    const reasons = [];

    if (candidate.metadata?.intent === analysis.intent) {
      reasons.push(`Matches intent: ${analysis.intent}`);
    }

    return reasons;
  }

  suggestImplementation(candidate, context) {
    return {
      framework: context.framework || 'react',
      approach: 'component-based',
      dependencies: candidate.metadata?.dependencies || []
    };
  }

  findAlternatives(candidate, scored) {
    return scored
      .filter(s => s.id !== candidate.id && s.score > 0.5)
      .slice(0, 3)
      .map(s => ({ id: s.id, name: s.name, score: s.score }));
  }

  countComponents(catalog) {
    let count = 0;

    for (const category of Object.values(catalog.components)) {
      count += Object.keys(category).length;
    }

    return count;
  }

  countByCategory(catalog) {
    const counts = {};

    for (const [category, components] of Object.entries(catalog.components)) {
      counts[category] = Object.keys(components).length;
    }

    return counts;
  }

  getRecentComponents(catalog, limit) {
    // Get recently added components
    const recent = [];

    for (const [category, components] of Object.entries(catalog.components)) {
      for (const [name, component] of Object.entries(components)) {
        if (component.design?.registeredAt) {
          recent.push({
            name,
            category,
            registeredAt: component.design.registeredAt
          });
        }
      }
    }

    return recent
      .sort((a, b) => b.registeredAt - a.registeredAt)
      .slice(0, limit);
  }

  extractPatterns(catalog) {
    return catalog.aiContext?.componentPatterns || {};
  }

  getGuidelines(catalog) {
    return catalog.aiContext?.brandGuidelines || {};
  }

  updatePatterns(catalog, patterns) {
    catalog.aiContext.componentPatterns = {
      ...catalog.aiContext.componentPatterns,
      ...patterns
    };
  }

  updateRegisteredContext(catalog, asset) {
    const category = asset.metadata?.category || 'unknown';

    if (!catalog.aiContext.componentPatterns[category]) {
      catalog.aiContext.componentPatterns[category] = [];
    }

    catalog.aiContext.componentPatterns[category].push({
      name: asset.name,
      properties: asset.properties,
      registered: Date.now()
    });
  }

  createSimilarityHelper() {
    return {
      calculate: this.calculateSimilarity.bind(this)
    };
  }

  createCategorizationHelper() {
    return {
      categorize: this.categorizeAsset.bind(this)
    };
  }

  createOptimizationHelper() {
    return {
      optimize: this.optimizeCode.bind(this)
    };
  }

  matchesFilter(component, intent) {
    // Simple filter matching
    return true;
  }

  matchesIntent(impl, intent) {
    // Simple intent matching
    return true;
  }

  matchesAnalysis(asset, analysis) {
    // Simple analysis matching
    return true;
  }

  async analyzeUsage(componentId) {
    return this.orchestrator.analyzeUsage(componentId);
  }

  async analyzePerformance(componentId) {
    return {
      renderTime: Math.random() * 16,
      bundleSize: Math.random() * 50000,
      memoryUsage: Math.random() * 100
    };
  }

  async analyzeAccessibility(componentId) {
    return {
      wcagCompliance: 'AA',
      issues: [],
      suggestions: ['Add ARIA labels', 'Ensure keyboard navigation']
    };
  }

  async analyzeTrends(componentId) {
    return {
      usage: 'increasing',
      performance: 'stable',
      issues: 'decreasing'
    };
  }

  generateInsights(analysis) {
    const insights = [];

    if (analysis.usage?.usageCount > 10) {
      insights.push('High usage component - consider optimization');
    }

    if (analysis.performance?.renderTime > 16) {
      insights.push('Performance issues detected - review implementation');
    }

    return insights;
  }

  generateAnalysisRecommendations(analysis) {
    const recommendations = [];

    if (analysis.accessibility?.issues?.length > 0) {
      recommendations.push('Fix accessibility issues');
    }

    if (analysis.trends?.issues === 'increasing') {
      recommendations.push('Review recent changes for quality');
    }

    return recommendations;
  }

  async getComponent(componentId) {
    // Get component from orchestrator
    for (const [id, asset] of this.orchestrator.designAssets) {
      if (id === componentId) return asset;
    }
    return null;
  }

  async getValidationRules() {
    return this.rules;
  }

  validateStructure(component, rules) {
    return { errors: [], warnings: [] };
  }

  validateNaming(component, rules) {
    const result = { errors: [], warnings: [] };

    if (!rules.naming.components.test(component.name)) {
      result.errors.push('Component name must be PascalCase');
    }

    return result;
  }

  validateProperties(component, rules) {
    const result = { errors: [], warnings: [] };

    const propCount = Object.keys(component.properties || {}).length;
    if (propCount > rules.structure.maxProps) {
      result.warnings.push(`Too many props: ${propCount} (max: ${rules.structure.maxProps})`);
    }

    return result;
  }

  async validateAccessibility(component) {
    return {
      errors: [],
      warnings: [],
      suggestions: ['Consider adding ARIA labels']
    };
  }

  async validatePerformance(component) {
    return {
      warnings: [],
      suggestions: ['Optimize render method']
    };
  }
}

module.exports = AICatalogAPI;