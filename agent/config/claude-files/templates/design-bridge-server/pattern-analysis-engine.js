/**
 * Pattern Analysis Engine - Orchestrates comprehensive pattern detection
 * Coordinates all pattern recognition modules and generates actionable insights
 */

const { EventEmitter } = require('events');
const PatternRecognizerExtended = require('./pattern-recognizer-extended');

class PatternAnalysisEngine extends EventEmitter {
  constructor(options = {}) {
    super();
    this.options = {
      confidence: 0.7,
      enableCaching: true,
      deepAnalysis: true,
      generateRecommendations: true,
      ...options
    };

    this.recognizer = new PatternRecognizerExtended(this.options);
    this.cache = new Map();
    this.analysisHistory = [];
  }

  async analyzeDesignSystem(tokens, metadata = {}) {
    const analysisId = this.generateAnalysisId(tokens, metadata);
    const startTime = Date.now();

    try {
      // Check cache if enabled
      if (this.options.enableCaching && this.cache.has(analysisId)) {
        this.emit('analysis:cached', { analysisId });
        return this.cache.get(analysisId);
      }

      this.emit('analysis:started', { analysisId, timestamp: startTime });

      // Comprehensive pattern analysis
      const analysis = {
        id: analysisId,
        timestamp: startTime,
        metadata,
        patterns: await this.recognizer.analyzePatterns(tokens, metadata),
        quality: await this.analyzeQuality(tokens),
        consistency: await this.analyzeConsistency(tokens),
        maturity: await this.analyzeMaturity(tokens),
        accessibility: await this.analyzeAccessibility(tokens),
        performance: await this.analyzePerformance(tokens),
        recommendations: [],
        insights: {},
        score: 0
      };

      // Generate insights and recommendations
      if (this.options.generateRecommendations) {
        analysis.recommendations = await this.generateComprehensiveRecommendations(analysis);
        analysis.insights = await this.generateInsights(analysis);
      }

      // Calculate overall score
      analysis.score = this.calculateOverallScore(analysis);

      // Deep analysis if enabled
      if (this.options.deepAnalysis) {
        analysis.deep = await this.performDeepAnalysis(tokens, analysis);
      }

      analysis.processingTime = Date.now() - startTime;

      // Cache and store
      if (this.options.enableCaching) {
        this.cache.set(analysisId, analysis);
      }
      this.analysisHistory.push({
        id: analysisId,
        timestamp: startTime,
        score: analysis.score,
        patterns: Object.keys(analysis.patterns || {}).length
      });

      this.emit('analysis:completed', analysis);
      return analysis;

    } catch (error) {
      this.emit('analysis:error', { analysisId, error });
      throw new Error(`Pattern analysis failed: ${error.message}`);
    }
  }

  async analyzeQuality(tokens) {
    return {
      naming: await this.analyzeNamingQuality(tokens),
      organization: await this.analyzeOrganizationQuality(tokens),
      completeness: await this.analyzeCompletenessQuality(tokens),
      scalability: await this.analyzeScalabilityQuality(tokens)
    };
  }

  async analyzeNamingQuality(tokens) {
    const allNames = this.extractAllTokenNames(tokens);

    const namingPatterns = {
      kebabCase: /^[a-z][a-z0-9]*(-[a-z0-9]+)*$/,
      camelCase: /^[a-z][a-zA-Z0-9]*$/,
      snakeCase: /^[a-z][a-z0-9]*(_[a-z0-9]+)*$/,
      pascalCase: /^[A-Z][a-zA-Z0-9]*$/
    };

    const consistency = this.analyzeNamingConsistency(allNames, namingPatterns);
    const clarity = this.analyzeNamingClarity(allNames);
    const semantics = this.analyzeNamingSemantics(allNames);

    return {
      consistency,
      clarity,
      semantics,
      score: (consistency.score + clarity.score + semantics.score) / 3,
      recommendations: this.generateNamingRecommendations(consistency, clarity, semantics)
    };
  }

  analyzeNamingConsistency(names, patterns) {
    const patternMatches = {};

    Object.entries(patterns).forEach(([patternName, regex]) => {
      patternMatches[patternName] = names.filter(name => regex.test(name)).length;
    });

    const dominantPattern = Object.entries(patternMatches)
      .sort((a, b) => b[1] - a[1])[0];

    const consistencyScore = dominantPattern ? dominantPattern[1] / names.length : 0;

    return {
      score: consistencyScore,
      dominantPattern: dominantPattern ? dominantPattern[0] : 'none',
      patternDistribution: patternMatches,
      inconsistentNames: names.filter(name =>
        !patterns[dominantPattern?.[0]]?.test(name)
      )
    };
  }

  analyzeNamingClarity(names) {
    const clarityMetrics = {
      abbreviations: this.countAbbreviations(names),
      ambiguous: this.findAmbiguousNames(names),
      descriptive: this.countDescriptiveNames(names),
      length: this.analyzeNameLength(names)
    };

    const clarityScore = this.calculateClarityScore(clarityMetrics, names.length);

    return {
      score: clarityScore,
      metrics: clarityMetrics,
      issues: this.identifyClarityIssues(clarityMetrics)
    };
  }

  analyzeNamingSemantics(names) {
    const semanticCategories = {
      colors: names.filter(name => this.isColorName(name)),
      typography: names.filter(name => this.isTypographyName(name)),
      spacing: names.filter(name => this.isSpacingName(name)),
      components: names.filter(name => this.isComponentName(name)),
      utilities: names.filter(name => this.isUtilityName(name))
    };

    const semanticScore = this.calculateSemanticScore(semanticCategories, names);

    return {
      score: semanticScore,
      categories: semanticCategories,
      uncategorized: names.filter(name =>
        !Object.values(semanticCategories).some(category => category.includes(name))
      )
    };
  }

  async analyzeOrganizationQuality(tokens) {
    const structure = this.analyzeTokenStructure(tokens);
    const hierarchy = this.analyzeTokenHierarchy(tokens);
    const grouping = this.analyzeTokenGrouping(tokens);

    return {
      structure,
      hierarchy,
      grouping,
      score: (structure.score + hierarchy.score + grouping.score) / 3
    };
  }

  async analyzeCompletenessQuality(tokens) {
    const essentialCategories = ['colors', 'typography', 'spacing'];
    const recommendedCategories = ['shadows', 'borderRadius', 'breakpoints'];
    const advancedCategories = ['animations', 'transitions', 'zIndex'];

    const present = {
      essential: essentialCategories.filter(cat => tokens[cat]),
      recommended: recommendedCategories.filter(cat => tokens[cat]),
      advanced: advancedCategories.filter(cat => tokens[cat])
    };

    const completenessScore =
      (present.essential.length / essentialCategories.length) * 0.6 +
      (present.recommended.length / recommendedCategories.length) * 0.3 +
      (present.advanced.length / advancedCategories.length) * 0.1;

    return {
      score: completenessScore,
      present,
      missing: {
        essential: essentialCategories.filter(cat => !tokens[cat]),
        recommended: recommendedCategories.filter(cat => !tokens[cat]),
        advanced: advancedCategories.filter(cat => !tokens[cat])
      },
      coverage: {
        essential: present.essential.length / essentialCategories.length,
        recommended: present.recommended.length / recommendedCategories.length,
        advanced: present.advanced.length / advancedCategories.length
      }
    };
  }

  async analyzeScalabilityQuality(tokens) {
    const scalabilityFactors = {
      tokenCount: this.analyzeTokenCount(tokens),
      naming: this.analyzeNamingScalability(tokens),
      organization: this.analyzeOrganizationScalability(tokens),
      relationships: this.analyzeTokenRelationships(tokens)
    };

    const scalabilityScore = Object.values(scalabilityFactors)
      .reduce((sum, factor) => sum + factor.score, 0) / Object.keys(scalabilityFactors).length;

    return {
      score: scalabilityScore,
      factors: scalabilityFactors,
      recommendations: this.generateScalabilityRecommendations(scalabilityFactors)
    };
  }

  async analyzeConsistency(tokens) {
    return {
      values: await this.analyzeValueConsistency(tokens),
      naming: await this.analyzeNamingPatternConsistency(tokens),
      structure: await this.analyzeStructuralConsistency(tokens),
      relationships: await this.analyzeRelationshipConsistency(tokens)
    };
  }

  async analyzeValueConsistency(tokens) {
    const consistency = {
      colors: this.analyzeColorConsistency(tokens.colors || {}),
      spacing: this.analyzeSpacingConsistency(tokens.spacing || {}),
      typography: this.analyzeTypographyConsistency(tokens.typography || {}),
      shadows: this.analyzeShadowConsistency(tokens.shadows || {})
    };

    return {
      byCategory: consistency,
      overall: Object.values(consistency).reduce((sum, c) => sum + c.score, 0) / Object.keys(consistency).length,
      issues: this.identifyConsistencyIssues(consistency)
    };
  }

  async analyzeMaturity(tokens) {
    const maturityIndicators = {
      systematization: this.analyzeSystematization(tokens),
      documentation: this.analyzeDocumentation(tokens),
      adoption: this.analyzeAdoption(tokens),
      evolution: this.analyzeEvolution(tokens),
      governance: this.analyzeGovernance(tokens)
    };

    const maturityLevel = this.calculateMaturityLevel(maturityIndicators);

    return {
      level: maturityLevel,
      indicators: maturityIndicators,
      score: Object.values(maturityIndicators).reduce((sum, i) => sum + i.score, 0) / Object.keys(maturityIndicators).length,
      recommendations: this.generateMaturityRecommendations(maturityLevel, maturityIndicators)
    };
  }

  async analyzeAccessibility(tokens) {
    return {
      contrast: await this.analyzeContrastAccessibility(tokens.colors || {}),
      typography: await this.analyzeTypographyAccessibility(tokens.typography || {}),
      focus: await this.analyzeFocusAccessibility(tokens),
      motion: await this.analyzeMotionAccessibility(tokens.animations || {}),
      color: await this.analyzeColorAccessibility(tokens.colors || {})
    };
  }

  async analyzePerformance(tokens) {
    return {
      size: this.analyzeTokenSize(tokens),
      complexity: this.analyzeTokenComplexity(tokens),
      redundancy: this.analyzeTokenRedundancy(tokens),
      efficiency: this.analyzeTokenEfficiency(tokens)
    };
  }

  async generateComprehensiveRecommendations(analysis) {
    const recommendations = [];

    // Pattern-based recommendations
    if (analysis.patterns) {
      recommendations.push(...await this.generatePatternRecommendations(analysis.patterns));
    }

    // Quality-based recommendations
    if (analysis.quality) {
      recommendations.push(...this.generateQualityRecommendations(analysis.quality));
    }

    // Consistency-based recommendations
    if (analysis.consistency) {
      recommendations.push(...this.generateConsistencyRecommendations(analysis.consistency));
    }

    // Accessibility-based recommendations
    if (analysis.accessibility) {
      recommendations.push(...this.generateAccessibilityRecommendations(analysis.accessibility));
    }

    // Performance-based recommendations
    if (analysis.performance) {
      recommendations.push(...this.generatePerformanceRecommendations(analysis.performance));
    }

    // Sort by priority and impact
    return this.prioritizeRecommendations(recommendations);
  }

  async generateInsights(analysis) {
    return {
      strengths: this.identifyStrengths(analysis),
      weaknesses: this.identifyWeaknesses(analysis),
      opportunities: this.identifyOpportunities(analysis),
      risks: this.identifyRisks(analysis),
      trends: this.identifyTrends(analysis),
      comparisons: await this.generateComparisons(analysis)
    };
  }

  calculateOverallScore(analysis) {
    const weights = {
      patterns: 0.25,
      quality: 0.25,
      consistency: 0.20,
      accessibility: 0.15,
      performance: 0.10,
      maturity: 0.05
    };

    let totalScore = 0;
    let totalWeight = 0;

    Object.entries(weights).forEach(([category, weight]) => {
      const categoryAnalysis = analysis[category];
      if (categoryAnalysis && typeof categoryAnalysis.score === 'number') {
        totalScore += categoryAnalysis.score * weight;
        totalWeight += weight;
      }
    });

    return totalWeight > 0 ? (totalScore / totalWeight) * 100 : 0;
  }

  async performDeepAnalysis(tokens, analysis) {
    return {
      relationships: await this.analyzeDeepRelationships(tokens),
      patterns: await this.analyzeAdvancedPatterns(tokens, analysis.patterns),
      optimization: await this.analyzeOptimizationOpportunities(tokens),
      evolution: await this.analyzeEvolutionPotential(tokens, analysis),
      integration: await this.analyzeIntegrationReadiness(tokens)
    };
  }

  // Helper methods
  generateAnalysisId(tokens, metadata) {
    const tokenHash = this.hashObject(tokens);
    const metadataHash = this.hashObject(metadata);
    return `analysis_${tokenHash}_${metadataHash}_${Date.now()}`;
  }

  hashObject(obj) {
    return require('crypto')
      .createHash('md5')
      .update(JSON.stringify(obj))
      .digest('hex')
      .substring(0, 8);
  }

  extractAllTokenNames(tokens) {
    const names = [];

    const extractFromObject = (obj, prefix = '') => {
      Object.entries(obj).forEach(([key, value]) => {
        const fullKey = prefix ? `${prefix}-${key}` : key;
        names.push(fullKey);

        if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
          extractFromObject(value, fullKey);
        }
      });
    };

    extractFromObject(tokens);
    return names;
  }

  countAbbreviations(names) {
    const abbreviationPatterns = [
      /\b[a-z]{1,3}\b/g,  // Short abbreviations
      /\w*[A-Z]{2,}\w*/g   // Multiple capitals
    ];

    return names.filter(name =>
      abbreviationPatterns.some(pattern => pattern.test(name))
    ).length;
  }

  findAmbiguousNames(names) {
    const ambiguousPatterns = [
      /^(item|element|thing|stuff)$/i,
      /^(data|info|content)$/i,
      /^(temp|tmp|test)$/i
    ];

    return names.filter(name =>
      ambiguousPatterns.some(pattern => pattern.test(name))
    );
  }

  isColorName(name) {
    return /color|bg|background|foreground|text|border|fill|stroke/i.test(name);
  }

  isTypographyName(name) {
    return /font|text|type|heading|body|caption|title/i.test(name);
  }

  isSpacingName(name) {
    return /space|spacing|margin|padding|gap|gutter/i.test(name);
  }

  isComponentName(name) {
    return /button|card|modal|nav|header|footer|sidebar/i.test(name);
  }

  isUtilityName(name) {
    return /util|helper|mixin|function|opacity|visibility/i.test(name);
  }

  prioritizeRecommendations(recommendations) {
    const priorityWeights = { high: 3, medium: 2, low: 1 };

    return recommendations.sort((a, b) => {
      const aPriority = priorityWeights[a.priority] || 1;
      const bPriority = priorityWeights[b.priority] || 1;

      if (aPriority !== bPriority) {
        return bPriority - aPriority;
      }

      return (b.impact || 1) - (a.impact || 1);
    });
  }

  // Analysis history and caching
  getAnalysisHistory() {
    return [...this.analysisHistory];
  }

  clearCache() {
    this.cache.clear();
    this.emit('cache:cleared');
  }

  getCacheStats() {
    return {
      size: this.cache.size,
      entries: Array.from(this.cache.keys())
    };
  }
}

module.exports = PatternAnalysisEngine;