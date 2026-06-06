/**
 * Quality Metrics - Comprehensive design system quality assessment
 * Calculates health scores, identifies issues, and provides actionable metrics
 */

const { EventEmitter } = require('events');

class QualityMetrics extends EventEmitter {
  constructor(options = {}) {
    super();
    this.options = {
      strictMode: false,
      industryStandards: true,
      customWeights: {},
      ...options
    };

    this.weights = this.initializeWeights();
    this.benchmarks = this.initializeBenchmarks();
    this.cache = new Map();
  }

  // Main calculate method - entry point for quality assessment
  async calculate(tokens) {
    const analysis = await this.analyzeTokens(tokens);
    const metrics = await this.calculateQualityScore(tokens, analysis);

    return {
      ...metrics,
      tokenCount: this.countTokens(tokens),
      categories: Object.keys(tokens),
      accessibility: metrics.scores?.accessibility || 0,
      overallScore: metrics.overall || 0,
      recommendations: metrics.recommendations || []
    };
  }

  // Helper to count tokens
  countTokens(tokens) {
    let count = 0;
    for (const category of Object.values(tokens)) {
      if (typeof category === 'object') {
        count += Object.keys(category).length;
      }
    }
    return count;
  }

  // Analyze tokens for quality metrics
  async analyzeTokens(tokens) {
    return {
      hasColors: !!tokens.colors,
      hasTypography: !!tokens.typography,
      hasSpacing: !!tokens.spacing,
      colorCount: tokens.colors ? Object.keys(tokens.colors).length : 0,
      typographyCount: tokens.typography ? Object.keys(tokens.typography).length : 0,
      spacingCount: tokens.spacing ? Object.keys(tokens.spacing).length : 0
    };
  }

  async calculateQualityScore(tokens, analysis = {}) {
    const startTime = Date.now();

    try {
      const metrics = {
        consistency: await this.calculateConsistencyScore(tokens),
        accessibility: await this.calculateAccessibilityScore(tokens, analysis),
        performance: await this.calculatePerformanceScore(tokens),
        maintainability: await this.calculateMaintainabilityScore(tokens),
        scalability: await this.calculateScalabilityScore(tokens),
        usability: await this.calculateUsabilityScore(tokens),
        completeness: await this.calculateCompletenessScore(tokens),
        standardCompliance: await this.calculateStandardComplianceScore(tokens, analysis)
      };

      const overallScore = this.calculateOverallScore(metrics);
      const healthGrade = this.calculateHealthGrade(overallScore);
      const riskAssessment = this.assessRisks(metrics, tokens);

      const qualityReport = {
        overall: {
          score: overallScore,
          grade: healthGrade,
          percentile: this.calculatePercentile(overallScore)
        },
        metrics,
        risks: riskAssessment,
        recommendations: this.generateQualityRecommendations(metrics, tokens),
        trends: this.calculateTrends(metrics),
        benchmarks: this.compareToBenchmarks(metrics),
        processingTime: Date.now() - startTime,
        timestamp: new Date().toISOString()
      };

      this.emit('quality:calculated', qualityReport);
      return qualityReport;

    } catch (error) {
      this.emit('error', error);
      throw new Error(`Quality calculation failed: ${error.message}`);
    }
  }

  async calculateConsistencyScore(tokens) {
    const consistency = {
      naming: await this.analyzeNamingConsistency(tokens),
      values: await this.analyzeValueConsistency(tokens),
      structure: await this.analyzeStructuralConsistency(tokens),
      patterns: await this.analyzePatternConsistency(tokens)
    };

    const score = this.weightedAverage(consistency, {
      naming: 0.3,
      values: 0.3,
      structure: 0.2,
      patterns: 0.2
    });

    return {
      score,
      breakdown: consistency,
      issues: this.identifyConsistencyIssues(consistency),
      improvements: this.suggestConsistencyImprovements(consistency)
    };
  }

  async analyzeNamingConsistency(tokens) {
    const allNames = this.extractAllNames(tokens);

    // Analyze naming patterns
    const patterns = {
      kebabCase: /^[a-z][a-z0-9-]*$/,
      camelCase: /^[a-z][a-zA-Z0-9]*$/,
      snakeCase: /^[a-z][a-z0-9_]*$/,
      pascalCase: /^[A-Z][a-zA-Z0-9]*$/
    };

    const patternCounts = {};
    Object.keys(patterns).forEach(pattern => {
      patternCounts[pattern] = allNames.filter(name =>
        patterns[pattern].test(name)
      ).length;
    });

    const dominantPattern = Object.entries(patternCounts)
      .sort((a, b) => b[1] - a[1])[0];

    const consistencyScore = dominantPattern ?
      dominantPattern[1] / allNames.length : 0;

    // Analyze semantic consistency
    const semanticGroups = this.groupNamesBySemantics(allNames);
    const semanticConsistency = this.calculateSemanticConsistency(semanticGroups);

    // Analyze abbreviation consistency
    const abbreviationConsistency = this.analyzeAbbreviationConsistency(allNames);

    return {
      score: (consistencyScore + semanticConsistency + abbreviationConsistency) / 3,
      patternConsistency: consistencyScore,
      dominantPattern: dominantPattern ? dominantPattern[0] : 'none',
      semanticConsistency,
      abbreviationConsistency,
      violations: this.findNamingViolations(allNames, patterns[dominantPattern?.[0]])
    };
  }

  async analyzeValueConsistency(tokens) {
    const valueConsistency = {
      colors: this.analyzeColorValueConsistency(tokens.colors || {}),
      spacing: this.analyzeSpacingValueConsistency(tokens.spacing || {}),
      typography: this.analyzeTypographyValueConsistency(tokens.typography || {}),
      borderRadius: this.analyzeBorderRadiusConsistency(tokens.borderRadius || {}),
      shadows: this.analyzeShadowConsistency(tokens.shadows || {})
    };

    const score = this.weightedAverage(valueConsistency, {
      colors: 0.25,
      spacing: 0.25,
      typography: 0.25,
      borderRadius: 0.125,
      shadows: 0.125
    });

    return {
      score,
      breakdown: valueConsistency,
      inconsistencies: this.findValueInconsistencies(valueConsistency)
    };
  }

  analyzeColorValueConsistency(colors) {
    if (Object.keys(colors).length === 0) return { score: 1, issues: [] };

    const issues = [];
    let consistentPairs = 0;
    let totalPairs = 0;

    // Check for consistent color relationships
    const colorEntries = Object.entries(colors);
    for (let i = 0; i < colorEntries.length; i++) {
      for (let j = i + 1; j < colorEntries.length; j++) {
        totalPairs++;

        const [name1, color1] = colorEntries[i];
        const [name2, color2] = colorEntries[j];

        if (this.areColorsRelated(name1, name2, color1, color2)) {
          consistentPairs++;
        } else {
          issues.push({
            type: 'color_relationship',
            colors: [name1, name2],
            issue: 'Colors with similar names have inconsistent values'
          });
        }
      }
    }

    // Check for shade consistency
    const shadeGroups = this.groupColorsByShades(colors);
    const shadeConsistency = this.calculateShadeConsistency(shadeGroups);

    return {
      score: totalPairs > 0 ? (consistentPairs / totalPairs + shadeConsistency) / 2 : 1,
      relationshipConsistency: totalPairs > 0 ? consistentPairs / totalPairs : 1,
      shadeConsistency,
      issues
    };
  }

  analyzeSpacingValueConsistency(spacing) {
    if (Object.keys(spacing).length === 0) return { score: 1, progression: null };

    const values = Object.values(spacing)
      .map(v => this.parseNumericValue(v))
      .filter(v => v !== null)
      .sort((a, b) => a - b);

    if (values.length < 2) return { score: 1, progression: 'insufficient_data' };

    // Check for mathematical progression
    const progression = this.detectProgression(values);
    const consistencyScore = this.calculateProgressionConsistency(values, progression);

    // Check for common scale adherence
    const scaleAdherence = this.checkScaleAdherence(values);

    return {
      score: (consistencyScore + scaleAdherence.score) / 2,
      progression: progression.type,
      progressionScore: consistencyScore,
      scaleAdherence: scaleAdherence.score,
      recommendedScale: scaleAdherence.recommendedScale,
      outliers: this.findSpacingOutliers(values, progression)
    };
  }

  analyzeTypographyValueConsistency(typography) {
    if (Object.keys(typography).length === 0) return { score: 1, scale: null };

    const fontSizes = [];
    const lineHeights = [];
    const fontWeights = [];

    Object.values(typography).forEach(typeface => {
      if (typeface.fontSize) {
        fontSizes.push(this.parseNumericValue(typeface.fontSize));
      }
      if (typeface.lineHeight) {
        lineHeights.push(this.parseNumericValue(typeface.lineHeight));
      }
      if (typeface.fontWeight) {
        fontWeights.push(this.parseNumericValue(typeface.fontWeight));
      }
    });

    const fontSizeConsistency = this.analyzeTypographicScale(fontSizes);
    const lineHeightConsistency = this.analyzeLineHeightConsistency(lineHeights, fontSizes);
    const fontWeightConsistency = this.analyzeFontWeightConsistency(fontWeights);

    return {
      score: (fontSizeConsistency.score + lineHeightConsistency.score + fontWeightConsistency.score) / 3,
      fontSize: fontSizeConsistency,
      lineHeight: lineHeightConsistency,
      fontWeight: fontWeightConsistency
    };
  }

  async calculateAccessibilityScore(tokens, analysis = {}) {
    const accessibility = {
      contrast: await this.analyzeContrastAccessibility(tokens.colors || {}),
      colorBlindness: await this.analyzeColorBlindnessSupport(tokens.colors || {}),
      typography: await this.analyzeTypographyAccessibility(tokens.typography || {}),
      focusStates: await this.analyzeFocusStateAccessibility(tokens),
      motion: await this.analyzeMotionAccessibility(tokens.animations || {})
    };

    const score = this.weightedAverage(accessibility, {
      contrast: 0.35,
      colorBlindness: 0.20,
      typography: 0.25,
      focusStates: 0.15,
      motion: 0.05
    });

    return {
      score,
      breakdown: accessibility,
      wcagLevel: this.determineWCAGLevel(accessibility),
      violations: this.findAccessibilityViolations(accessibility),
      recommendations: this.generateAccessibilityRecommendations(accessibility)
    };
  }

  async analyzeContrastAccessibility(colors) {
    if (Object.keys(colors).length === 0) return { score: 1, pairs: [] };

    const contrastPairs = this.generateContrastPairs(colors);
    const wcagAACompliant = contrastPairs.filter(pair => pair.ratio >= 4.5);
    const wcagAAACompliant = contrastPairs.filter(pair => pair.ratio >= 7);

    const aaScore = contrastPairs.length > 0 ? wcagAACompliant.length / contrastPairs.length : 1;
    const aaaScore = contrastPairs.length > 0 ? wcagAAACompliant.length / contrastPairs.length : 1;

    return {
      score: aaScore, // Base score on AA compliance
      wcagAA: {
        score: aaScore,
        compliantPairs: wcagAACompliant.length,
        totalPairs: contrastPairs.length
      },
      wcagAAA: {
        score: aaaScore,
        compliantPairs: wcagAAACompliant.length,
        totalPairs: contrastPairs.length
      },
      violations: contrastPairs.filter(pair => pair.ratio < 4.5),
      recommendations: this.generateContrastRecommendations(contrastPairs)
    };
  }

  async analyzeColorBlindnessSupport(colors) {
    const colorBlindnessTypes = ['protanopia', 'deuteranopia', 'tritanopia'];
    const simulatedColors = {};

    // Simulate color blindness for each type
    colorBlindnessTypes.forEach(type => {
      simulatedColors[type] = this.simulateColorBlindness(colors, type);
    });

    // Check for distinguishability
    const distinguishability = this.calculateColorDistinguishability(colors, simulatedColors);

    return {
      score: distinguishability.overall,
      byType: distinguishability.byType,
      criticalIssues: distinguishability.criticalIssues,
      recommendations: this.generateColorBlindnessRecommendations(distinguishability)
    };
  }

  async calculatePerformanceScore(tokens) {
    const performance = {
      size: this.calculateTokenSizeMetrics(tokens),
      complexity: this.calculateTokenComplexity(tokens),
      redundancy: this.calculateTokenRedundancy(tokens),
      bundling: this.calculateBundlingEfficiency(tokens)
    };

    const score = this.weightedAverage(performance, {
      size: 0.25,
      complexity: 0.25,
      redundancy: 0.25,
      bundling: 0.25
    });

    return {
      score,
      breakdown: performance,
      optimizations: this.identifyPerformanceOptimizations(performance),
      estimatedSavings: this.calculateEstimatedSavings(performance)
    };
  }

  calculateTokenSizeMetrics(tokens) {
    const serialized = JSON.stringify(tokens);
    const sizeBytes = new Blob([serialized]).size;
    const sizeKB = sizeBytes / 1024;

    // Performance thresholds
    const thresholds = {
      excellent: 50,    // < 50KB
      good: 100,        // < 100KB
      fair: 200,        // < 200KB
      poor: 500         // >= 500KB
    };

    let score = 1;
    if (sizeKB >= thresholds.poor) score = 0.2;
    else if (sizeKB >= thresholds.fair) score = 0.4;
    else if (sizeKB >= thresholds.good) score = 0.7;
    else if (sizeKB >= thresholds.excellent) score = 0.9;

    return {
      score,
      sizeBytes,
      sizeKB: Math.round(sizeKB * 100) / 100,
      grade: this.getSizeGrade(sizeKB, thresholds),
      recommendations: this.getSizeRecommendations(sizeKB, thresholds)
    };
  }

  calculateTokenComplexity(tokens) {
    let complexityScore = 0;
    let totalTokens = 0;

    const calculateObjectComplexity = (obj, depth = 0) => {
      Object.entries(obj).forEach(([key, value]) => {
        totalTokens++;

        // Depth complexity
        complexityScore += depth * 0.1;

        // Value type complexity
        if (typeof value === 'object' && value !== null) {
          if (Array.isArray(value)) {
            complexityScore += value.length * 0.05;
          } else {
            calculateObjectComplexity(value, depth + 1);
          }
        } else if (typeof value === 'string') {
          // String complexity based on length and special characters
          complexityScore += value.length * 0.001;
          complexityScore += (value.match(/[^a-zA-Z0-9\s]/g) || []).length * 0.01;
        }
      });
    };

    calculateObjectComplexity(tokens);

    const averageComplexity = totalTokens > 0 ? complexityScore / totalTokens : 0;
    const normalizedScore = Math.max(0, 1 - (averageComplexity / 2)); // Normalize to 0-1

    return {
      score: normalizedScore,
      totalTokens,
      averageComplexity,
      recommendations: this.getComplexityRecommendations(averageComplexity)
    };
  }

  calculateTokenRedundancy(tokens) {
    const allValues = [];
    const valueFrequency = new Map();

    const extractValues = (obj) => {
      Object.values(obj).forEach(value => {
        if (typeof value === 'object' && value !== null) {
          if (!Array.isArray(value)) {
            extractValues(value);
          }
        } else {
          const strValue = String(value);
          allValues.push(strValue);
          valueFrequency.set(strValue, (valueFrequency.get(strValue) || 0) + 1);
        }
      });
    };

    extractValues(tokens);

    const duplicateValues = Array.from(valueFrequency.entries())
      .filter(([_, count]) => count > 1);

    const redundancyRatio = duplicateValues.length > 0 ?
      duplicateValues.reduce((sum, [_, count]) => sum + (count - 1), 0) / allValues.length : 0;

    const score = Math.max(0, 1 - redundancyRatio);

    return {
      score,
      redundancyRatio,
      duplicateValues: duplicateValues.length,
      totalValues: allValues.length,
      mostDuplicated: duplicateValues.sort((a, b) => b[1] - a[1]).slice(0, 5),
      recommendations: this.getRedundancyRecommendations(redundancyRatio, duplicateValues)
    };
  }

  async calculateMaintainabilityScore(tokens) {
    const maintainability = {
      naming: this.analyzeMaintainableNaming(tokens),
      structure: this.analyzeMaintainableStructure(tokens),
      dependencies: this.analyzeDependencies(tokens),
      documentation: this.analyzeDocumentation(tokens),
      versioning: this.analyzeVersioning(tokens)
    };

    const score = this.weightedAverage(maintainability, {
      naming: 0.25,
      structure: 0.25,
      dependencies: 0.20,
      documentation: 0.15,
      versioning: 0.15
    });

    return {
      score,
      breakdown: maintainability,
      risks: this.identifyMaintainabilityRisks(maintainability),
      recommendations: this.generateMaintainabilityRecommendations(maintainability)
    };
  }

  async calculateScalabilityScore(tokens) {
    const scalability = {
      architecture: this.analyzeArchitecturalScalability(tokens),
      naming: this.analyzeNamingScalability(tokens),
      organization: this.analyzeOrganizationalScalability(tokens),
      extensibility: this.analyzeExtensibility(tokens)
    };

    const score = this.weightedAverage(scalability, {
      architecture: 0.3,
      naming: 0.25,
      organization: 0.25,
      extensibility: 0.2
    });

    return {
      score,
      breakdown: scalability,
      bottlenecks: this.identifyScalabilityBottlenecks(scalability),
      recommendations: this.generateScalabilityRecommendations(scalability)
    };
  }

  async calculateUsabilityScore(tokens) {
    const usability = {
      intuitiveness: this.analyzeIntuitiveness(tokens),
      discoverability: this.analyzeDiscoverability(tokens),
      learnability: this.analyzeLearnability(tokens),
      efficiency: this.analyzeUsageEfficiency(tokens)
    };

    const score = this.weightedAverage(usability, {
      intuitiveness: 0.3,
      discoverability: 0.25,
      learnability: 0.25,
      efficiency: 0.2
    });

    return {
      score,
      breakdown: usability,
      userExperience: this.assessUserExperience(usability),
      recommendations: this.generateUsabilityRecommendations(usability)
    };
  }

  async calculateCompletenessScore(tokens) {
    const required = ['colors', 'typography', 'spacing'];
    const recommended = ['shadows', 'borderRadius', 'breakpoints', 'zIndex'];
    const advanced = ['animations', 'transitions', 'motions', 'elevations'];

    const completeness = {
      required: this.calculateCategoryCompleteness(tokens, required),
      recommended: this.calculateCategoryCompleteness(tokens, recommended),
      advanced: this.calculateCategoryCompleteness(tokens, advanced)
    };

    const score =
      completeness.required.score * 0.6 +
      completeness.recommended.score * 0.3 +
      completeness.advanced.score * 0.1;

    return {
      score,
      breakdown: completeness,
      missing: this.identifyMissingCategories(tokens, required, recommended, advanced),
      recommendations: this.generateCompletenessRecommendations(completeness)
    };
  }

  async calculateStandardComplianceScore(tokens, analysis = {}) {
    const compliance = {
      w3c: this.analyzeW3CCompliance(tokens),
      wcag: this.analyzeWCAGCompliance(tokens, analysis.accessibility),
      designTokens: this.analyzeDesignTokenStandards(tokens),
      industry: this.analyzeIndustryStandards(tokens, analysis.patterns)
    };

    const score = this.weightedAverage(compliance, {
      w3c: 0.25,
      wcag: 0.35,
      designTokens: 0.25,
      industry: 0.15
    });

    return {
      score,
      breakdown: compliance,
      certifications: this.determineCertifications(compliance),
      recommendations: this.generateComplianceRecommendations(compliance)
    };
  }

  async analyzePatternConsistency(tokens) {
    let score = 1.0;
    const issues = [];

    try {
      // Check color pattern consistency
      if (tokens.colors) {
        const colorPatterns = this.detectColorPatterns(tokens.colors);
        if (colorPatterns.inconsistent.length > 0) {
          score -= 0.1 * Math.min(colorPatterns.inconsistent.length / 5, 0.3);
          issues.push(`${colorPatterns.inconsistent.length} inconsistent color patterns`);
        }
      }

      // Check spacing pattern consistency
      if (tokens.spacing) {
        const spacingPattern = this.detectSpacingPattern(tokens.spacing);
        if (!spacingPattern.isConsistent) {
          score -= 0.15;
          issues.push('Inconsistent spacing scale');
        }
      }

      // Check typography pattern consistency
      if (tokens.typography) {
        const typographyPattern = this.detectTypographyPattern(tokens.typography);
        if (!typographyPattern.isConsistent) {
          score -= 0.15;
          issues.push('Inconsistent typography scale');
        }
      }

      // Check naming pattern consistency
      const allNames = this.extractAllNames(tokens);
      const namingPatterns = this.analyzeNamingPatterns(allNames);
      const dominantPattern = Object.entries(namingPatterns)
        .sort(([,a], [,b]) => b - a)[0];

      if (dominantPattern) {
        const [pattern, count] = dominantPattern;
        const consistency = count / allNames.length;
        if (consistency < 0.7) {
          score -= 0.2 * (1 - consistency);
          issues.push(`Mixed naming patterns (${Math.round(consistency * 100)}% ${pattern})`);
        }
      }

    } catch (error) {
      console.warn('Pattern consistency analysis error:', error.message);
      score = 0.5;
    }

    return {
      score: Math.max(0, score),
      issues
    };
  }

  detectColorPatterns(colors) {
    const patterns = {
      consistent: [],
      inconsistent: []
    };

    const colorNames = Object.keys(colors);
    const hasNumericScale = colorNames.filter(name => /-\d{2,3}$/.test(name));
    const hasSemanticNames = colorNames.filter(name => /^(primary|secondary|success|error|warning)/.test(name));
    const hasBrandColors = colorNames.filter(name => /^brand-/.test(name));

    // Check for mixed patterns
    if (hasNumericScale.length > 0 && hasSemanticNames.length > 0) {
      if (hasNumericScale.length < colorNames.length / 2 && hasSemanticNames.length < colorNames.length / 2) {
        patterns.inconsistent.push('Mixed numeric and semantic color naming');
      }
    }

    return patterns;
  }

  detectSpacingPattern(spacing) {
    const values = Object.values(spacing).map(v =>
      typeof v === 'string' ? parseFloat(v) : v
    ).filter(v => !isNaN(v));

    if (values.length < 2) return { isConsistent: true };

    // Check for mathematical progression
    const sorted = values.sort((a, b) => a - b);
    let isLinear = true;
    let isExponential = true;

    // Check linear progression
    const diffs = [];
    for (let i = 1; i < sorted.length; i++) {
      diffs.push(sorted[i] - sorted[i - 1]);
    }
    const avgDiff = diffs.reduce((a, b) => a + b, 0) / diffs.length;
    isLinear = diffs.every(d => Math.abs(d - avgDiff) < avgDiff * 0.2);

    // Check exponential progression
    const ratios = [];
    for (let i = 1; i < sorted.length; i++) {
      if (sorted[i - 1] !== 0) {
        ratios.push(sorted[i] / sorted[i - 1]);
      }
    }
    const avgRatio = ratios.reduce((a, b) => a + b, 0) / ratios.length;
    isExponential = ratios.every(r => Math.abs(r - avgRatio) < avgRatio * 0.2);

    return { isConsistent: isLinear || isExponential };
  }

  identifyConsistencyIssues(consistency) {
    const issues = [];

    // Check color consistency
    if (consistency.colors && consistency.colors.score < 0.8) {
      issues.push({
        type: 'color',
        severity: consistency.colors.score < 0.5 ? 'high' : 'medium',
        message: `Color consistency score: ${(consistency.colors.score * 100).toFixed(0)}%`,
        details: consistency.colors.issues || []
      });
    }

    // Check spacing consistency
    if (consistency.spacing && consistency.spacing.score < 0.8) {
      issues.push({
        type: 'spacing',
        severity: consistency.spacing.score < 0.5 ? 'high' : 'medium',
        message: `Spacing consistency score: ${(consistency.spacing.score * 100).toFixed(0)}%`,
        details: consistency.spacing.issues || []
      });
    }

    // Check typography consistency
    if (consistency.typography && consistency.typography.score < 0.8) {
      issues.push({
        type: 'typography',
        severity: consistency.typography.score < 0.5 ? 'high' : 'medium',
        message: `Typography consistency score: ${(consistency.typography.score * 100).toFixed(0)}%`,
        details: consistency.typography.issues || []
      });
    }

    // Check naming consistency
    if (consistency.naming && consistency.naming.score < 0.7) {
      issues.push({
        type: 'naming',
        severity: consistency.naming.score < 0.4 ? 'high' : 'medium',
        message: `Naming consistency score: ${(consistency.naming.score * 100).toFixed(0)}%`,
        details: consistency.naming.patterns || []
      });
    }

    // Check value consistency
    if (consistency.values && consistency.values.score < 0.8) {
      issues.push({
        type: 'values',
        severity: consistency.values.score < 0.5 ? 'high' : 'medium',
        message: `Value consistency score: ${(consistency.values.score * 100).toFixed(0)}%`,
        details: consistency.values.inconsistencies || []
      });
    }

    return issues;
  }

  detectTypographyPattern(typography) {
    const sizes = [];

    Object.values(typography).forEach(value => {
      if (typeof value === 'object' && value.fontSize) {
        const size = parseFloat(value.fontSize);
        if (!isNaN(size)) sizes.push(size);
      }
    });

    if (sizes.length < 2) return { isConsistent: true };

    // Check for type scale ratio
    const sorted = sizes.sort((a, b) => a - b);
    const ratios = [];

    for (let i = 1; i < sorted.length; i++) {
      if (sorted[i - 1] !== 0) {
        ratios.push(sorted[i] / sorted[i - 1]);
      }
    }

    // Common type scale ratios
    const commonRatios = [1.067, 1.125, 1.2, 1.25, 1.333, 1.414, 1.5, 1.618];
    const avgRatio = ratios.reduce((a, b) => a + b, 0) / ratios.length;

    const isConsistent = commonRatios.some(cr =>
      Math.abs(avgRatio - cr) < 0.05
    );

    return { isConsistent };
  }

  async analyzeStructuralConsistency(tokens) {
    let score = 1.0;
    const issues = [];

    try {
      // Check for consistent property structure
      const hasColors = !!tokens.colors;
      const hasTypography = !!tokens.typography;
      const hasSpacing = !!tokens.spacing;
      const hasBreakpoints = !!tokens.breakpoints;

      // Basic structure presence
      if (!hasColors) {
        score -= 0.15;
        issues.push('Missing colors structure');
      }
      if (!hasTypography) {
        score -= 0.15;
        issues.push('Missing typography structure');
      }
      if (!hasSpacing) {
        score -= 0.10;
        issues.push('Missing spacing structure');
      }

      // Check for consistent nesting depth
      const depths = this.analyzeNestingDepth(tokens);
      if (depths.max > 5) {
        score -= 0.10;
        issues.push('Excessive nesting depth');
      }
      if (depths.variation > 3) {
        score -= 0.05;
        issues.push('Inconsistent nesting depth');
      }

      // Check for consistent value types
      const typeConsistency = this.checkValueTypeConsistency(tokens);
      if (typeConsistency < 0.7) {
        score -= 0.15;
        issues.push('Inconsistent value types');
      }

      // Check for orphaned tokens
      const orphaned = this.findOrphanedTokens(tokens);
      if (orphaned.length > 0) {
        score -= 0.05 * Math.min(orphaned.length / 10, 0.2);
        issues.push(`${orphaned.length} orphaned tokens`);
      }

    } catch (error) {
      console.warn('Structural consistency analysis error:', error.message);
      score = 0.5; // Default to medium score on error
    }

    return {
      score: Math.max(0, score),
      issues
    };
  }

  analyzeNestingDepth(obj, currentDepth = 0, depths = []) {
    depths.push(currentDepth);

    Object.values(obj).forEach(value => {
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        this.analyzeNestingDepth(value, currentDepth + 1, depths);
      }
    });

    if (currentDepth === 0) {
      const max = Math.max(...depths);
      const min = Math.min(...depths);
      const avg = depths.reduce((a, b) => a + b, 0) / depths.length;
      return {
        max,
        min,
        avg,
        variation: max - min
      };
    }

    return depths;
  }

  checkValueTypeConsistency(tokens) {
    const typeMap = {};

    const analyzeTypes = (obj, path = '') => {
      Object.entries(obj).forEach(([key, value]) => {
        const fullPath = path ? `${path}.${key}` : key;

        if (value && typeof value === 'object' && !Array.isArray(value)) {
          if (value.value !== undefined) {
            // It's a token value
            const type = typeof value.value;
            const category = path.split('.')[0];
            if (!typeMap[category]) typeMap[category] = {};
            if (!typeMap[category][type]) typeMap[category][type] = 0;
            typeMap[category][type]++;
          } else {
            // Recurse deeper
            analyzeTypes(value, fullPath);
          }
        }
      });
    };

    analyzeTypes(tokens);

    // Calculate consistency score
    let totalConsistency = 0;
    let categories = 0;

    Object.values(typeMap).forEach(categoryTypes => {
      const total = Object.values(categoryTypes).reduce((a, b) => a + b, 0);
      const maxType = Math.max(...Object.values(categoryTypes));
      const consistency = maxType / total;
      totalConsistency += consistency;
      categories++;
    });

    return categories > 0 ? totalConsistency / categories : 1;
  }

  findOrphanedTokens(tokens) {
    const orphaned = [];
    const referenced = new Set();

    // Collect all references
    const findReferences = (obj) => {
      Object.values(obj).forEach(value => {
        if (typeof value === 'string' && value.startsWith('{') && value.endsWith('}')) {
          referenced.add(value.slice(1, -1));
        } else if (value && typeof value === 'object') {
          findReferences(value);
        }
      });
    };

    findReferences(tokens);

    // Find tokens that are never referenced
    const findTokenPaths = (obj, path = '') => {
      Object.entries(obj).forEach(([key, value]) => {
        const fullPath = path ? `${path}.${key}` : key;

        if (value && typeof value === 'object' && !Array.isArray(value)) {
          if (value.value !== undefined) {
            // It's a token
            if (!referenced.has(fullPath) && path !== '') {
              orphaned.push(fullPath);
            }
          } else {
            findTokenPaths(value, fullPath);
          }
        }
      });
    };

    findTokenPaths(tokens);

    return orphaned;
  }

  // Helper methods
  initializeWeights() {
    return {
      consistency: 0.20,
      accessibility: 0.20,
      performance: 0.15,
      maintainability: 0.15,
      scalability: 0.10,
      usability: 0.10,
      completeness: 0.05,
      standardCompliance: 0.05,
      ...this.options.customWeights
    };
  }

  initializeBenchmarks() {
    return {
      industry: {
        consistency: 0.75,
        accessibility: 0.80,
        performance: 0.70,
        overall: 0.75
      },
      enterprise: {
        consistency: 0.85,
        accessibility: 0.90,
        performance: 0.80,
        overall: 0.85
      },
      startup: {
        consistency: 0.65,
        accessibility: 0.70,
        performance: 0.75,
        overall: 0.70
      }
    };
  }

  calculateOverallScore(metrics) {
    let totalScore = 0;
    let totalWeight = 0;

    Object.entries(this.weights).forEach(([category, weight]) => {
      if (metrics[category] && typeof metrics[category].score === 'number') {
        totalScore += metrics[category].score * weight;
        totalWeight += weight;
      }
    });

    return totalWeight > 0 ? (totalScore / totalWeight) * 100 : 0;
  }

  calculateHealthGrade(score) {
    if (score >= 90) return 'A+';
    if (score >= 85) return 'A';
    if (score >= 80) return 'A-';
    if (score >= 75) return 'B+';
    if (score >= 70) return 'B';
    if (score >= 65) return 'B-';
    if (score >= 60) return 'C+';
    if (score >= 55) return 'C';
    if (score >= 50) return 'C-';
    if (score >= 40) return 'D';
    return 'F';
  }

  weightedAverage(metrics, weights) {
    let totalScore = 0;
    let totalWeight = 0;

    Object.entries(weights).forEach(([key, weight]) => {
      if (metrics[key] && typeof metrics[key].score === 'number') {
        totalScore += metrics[key].score * weight;
        totalWeight += weight;
      }
    });

    return totalWeight > 0 ? totalScore / totalWeight : 0;
  }

  extractAllNames(tokens) {
    const names = [];
    const extract = (obj, prefix = '') => {
      Object.keys(obj).forEach(key => {
        const fullKey = prefix ? `${prefix}.${key}` : key;
        names.push(fullKey);
        if (typeof obj[key] === 'object' && obj[key] !== null && !Array.isArray(obj[key])) {
          extract(obj[key], fullKey);
        }
      });
    };
    extract(tokens);
    return names;
  }

  parseNumericValue(value) {
    if (typeof value === 'number') return value;
    if (typeof value === 'string') {
      const match = value.match(/(\d+(?:\.\d+)?)/);
      return match ? parseFloat(match[1]) : null;
    }
    return null;
  }

  // Additional utility methods would continue here...
  // This includes all the analysis methods referenced above

  generateQualityRecommendations(metrics, tokens) {
    const recommendations = [];

    Object.entries(metrics).forEach(([category, metric]) => {
      if (metric.score < 0.7) {
        recommendations.push({
          category,
          priority: metric.score < 0.5 ? 'high' : 'medium',
          score: metric.score,
          issue: `${category} score is below acceptable threshold`,
          recommendations: metric.recommendations || metric.improvements || []
        });
      }
    });

    return recommendations.sort((a, b) => {
      const priorityOrder = { high: 3, medium: 2, low: 1 };
      return priorityOrder[b.priority] - priorityOrder[a.priority];
    });
  }

  // Missing methods
  groupNamesBySemantics(names) {
    const semanticGroups = {
      colors: [],
      spacing: [],
      typography: [],
      shadows: [],
      borders: [],
      other: []
    };

    names.forEach(name => {
      const lowercaseName = name.toLowerCase();
      if (lowercaseName.includes('color') || lowercaseName.includes('bg') || lowercaseName.includes('text')) {
        semanticGroups.colors.push(name);
      } else if (lowercaseName.includes('space') || lowercaseName.includes('margin') || lowercaseName.includes('padding')) {
        semanticGroups.spacing.push(name);
      } else if (lowercaseName.includes('font') || lowercaseName.includes('text') || lowercaseName.includes('heading')) {
        semanticGroups.typography.push(name);
      } else if (lowercaseName.includes('shadow') || lowercaseName.includes('elevation')) {
        semanticGroups.shadows.push(name);
      } else if (lowercaseName.includes('border') || lowercaseName.includes('radius')) {
        semanticGroups.borders.push(name);
      } else {
        semanticGroups.other.push(name);
      }
    });

    return semanticGroups;
  }

  calculateSemanticConsistency(semanticGroups) {
    let totalConsistency = 0;
    let groupCount = 0;

    Object.entries(semanticGroups).forEach(([category, names]) => {
      if (names.length > 1) {
        groupCount++;
        const patterns = this.analyzeNamingPatterns(names);
        const dominantPattern = Object.entries(patterns)
          .sort((a, b) => b[1] - a[1])[0];
        totalConsistency += dominantPattern ? dominantPattern[1] / names.length : 0;
      }
    });

    return groupCount > 0 ? totalConsistency / groupCount : 1;
  }

  analyzeNamingPatterns(names) {
    const patterns = {};

    names.forEach(name => {
      // Analyze case patterns
      if (/^[a-z]+[A-Z][a-zA-Z]*$/.test(name)) {
        patterns.camelCase = (patterns.camelCase || 0) + 1;
      } else if (/^[a-z]+(-[a-z]+)*$/.test(name)) {
        patterns.kebabCase = (patterns.kebabCase || 0) + 1;
      } else if (/^[a-z]+(_[a-z]+)*$/.test(name)) {
        patterns.snakeCase = (patterns.snakeCase || 0) + 1;
      } else if (/^[A-Z][a-zA-Z]*$/.test(name)) {
        patterns.PascalCase = (patterns.PascalCase || 0) + 1;
      }

      // Analyze semantic patterns
      if (name.includes('primary') || name.includes('main')) {
        patterns.semantic = (patterns.semantic || 0) + 1;
      }
      if (/\d+$/.test(name)) {
        patterns.numbered = (patterns.numbered || 0) + 1;
      }
      if (name.includes('-') && /\d+/.test(name)) {
        patterns.scaledNaming = (patterns.scaledNaming || 0) + 1;
      }
    });

    return patterns;
  }

  analyzeBorderRadiusConsistency(borderRadius) {
    const values = Object.values(borderRadius).map(br => br.px || br.value || 0);
    if (values.length === 0) return 1;

    // Check for consistent scale progression
    const sortedValues = [...values].sort((a, b) => a - b);
    let consistencyScore = 0;

    // Check for common patterns (0, 4, 8, 16, etc.)
    const commonRadii = [0, 2, 4, 6, 8, 12, 16, 20, 24, 32];
    const matchingValues = values.filter(v => commonRadii.includes(v));

    consistencyScore = values.length > 0 ? matchingValues.length / values.length : 1;

    return Math.max(0.1, consistencyScore); // Minimum 0.1 to avoid zero scores
  }

  analyzeShadowConsistency(shadows) {
    const shadowValues = Object.values(shadows);
    if (shadowValues.length === 0) return 1;

    // Check for consistent shadow progression (elevation patterns)
    const elevationLevels = [1, 2, 3, 4, 6, 8, 12, 16, 24];
    let consistentShadows = 0;

    shadowValues.forEach(shadow => {
      if (shadow.elevation && elevationLevels.includes(shadow.elevation)) {
        consistentShadows++;
      } else if (shadow.blur) {
        // Check if blur values follow common patterns
        const blur = shadow.blur.px || shadow.blur.value || 0;
        if ([2, 4, 8, 16, 24, 32].includes(blur)) {
          consistentShadows++;
        }
      }
    });

    return shadowValues.length > 0 ? consistentShadows / shadowValues.length : 1;
  }

  findValueInconsistencies(valueConsistency) {
    const inconsistencies = [];

    // Check naming inconsistencies
    if (valueConsistency.naming < 0.7) {
      inconsistencies.push({
        type: 'naming',
        severity: 'medium',
        message: 'Inconsistent naming patterns detected'
      });
    }

    // Check spacing inconsistencies
    if (valueConsistency.spacing && valueConsistency.spacing.scale < 0.6) {
      inconsistencies.push({
        type: 'spacing',
        severity: 'high',
        message: 'Spacing values do not follow a consistent scale'
      });
    }

    // Check color inconsistencies
    if (valueConsistency.colors && valueConsistency.colors.palette < 0.5) {
      inconsistencies.push({
        type: 'colors',
        severity: 'medium',
        message: 'Color palette lacks consistency'
      });
    }

    return inconsistencies;
  }

  analyzeAbbreviationConsistency(names) {
    const abbreviations = new Map();

    names.forEach(name => {
      const words = name.split(/[-_\s]+/);
      words.forEach(word => {
        if (word.length <= 3) {
          abbreviations.set(word.toLowerCase(), (abbreviations.get(word.toLowerCase()) || 0) + 1);
        }
      });
    });

    const totalAbbreviations = Array.from(abbreviations.values()).reduce((sum, count) => sum + count, 0);
    const consistentAbbreviations = Array.from(abbreviations.values()).filter(count => count > 1).reduce((sum, count) => sum + count, 0);

    return totalAbbreviations > 0 ? consistentAbbreviations / totalAbbreviations : 1;
  }

  findNamingViolations(names, pattern) {
    if (!pattern) return [];

    const violations = [];
    names.forEach(name => {
      if (!this.matchesPattern(name, pattern)) {
        violations.push({
          name,
          expected: pattern,
          actual: this.detectPattern(name)
        });
      }
    });

    return violations;
  }

  matchesPattern(name, pattern) {
    const patterns = {
      'camelCase': /^[a-z][a-zA-Z0-9]*$/,
      'PascalCase': /^[A-Z][a-zA-Z0-9]*$/,
      'kebab-case': /^[a-z][a-z0-9-]*$/,
      'snake_case': /^[a-z][a-z0-9_]*$/,
      'UPPER_CASE': /^[A-Z][A-Z0-9_]*$/
    };

    return patterns[pattern] ? patterns[pattern].test(name) : false;
  }

  detectPattern(name) {
    if (/^[a-z][a-zA-Z0-9]*$/.test(name)) return 'camelCase';
    if (/^[A-Z][a-zA-Z0-9]*$/.test(name)) return 'PascalCase';
    if (/^[a-z][a-z0-9-]*$/.test(name)) return 'kebab-case';
    if (/^[a-z][a-z0-9_]*$/.test(name)) return 'snake_case';
    if (/^[A-Z][A-Z0-9_]*$/.test(name)) return 'UPPER_CASE';
    return 'mixed';
  }

  // Color relationship methods
  areColorsRelated(name1, name2, color1, color2) {
    // Check if names suggest they should be related
    const nameRelated = this.areNamesRelated(name1, name2);

    if (!nameRelated) return true; // If names aren't related, no consistency check needed

    // Check if colors are similar
    return this.areColorsSimilar(color1, color2);
  }

  areNamesRelated(name1, name2) {
    const base1 = name1.replace(/-\d+$/, '').replace(/\d+$/, '');
    const base2 = name2.replace(/-\d+$/, '').replace(/\d+$/, '');

    return base1 === base2 ||
           name1.startsWith(base2) ||
           name2.startsWith(base1);
  }

  areColorsSimilar(color1, color2, threshold = 30) {
    try {
      const hsl1 = this.toHSL(color1);
      const hsl2 = this.toHSL(color2);

      if (!hsl1 || !hsl2) return false;

      const hueDiff = Math.abs(hsl1.h - hsl2.h);
      const satDiff = Math.abs(hsl1.s - hsl2.s);
      const lightDiff = Math.abs(hsl1.l - hsl2.l);

      // Colors are similar if within threshold
      return hueDiff <= threshold && satDiff <= 20 && lightDiff <= 20;
    } catch {
      return false;
    }
  }

  toHSL(color) {
    if (typeof color === 'object' && color.value) {
      color = color.value;
    }

    if (typeof color === 'string') {
      if (color.startsWith('#')) {
        return this.hexToHSL(color);
      } else if (color.startsWith('rgb')) {
        const match = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
        if (match) {
          return this.rgbToHSL(
            parseInt(match[1]),
            parseInt(match[2]),
            parseInt(match[3])
          );
        }
      }
    }

    return null;
  }

  hexToHSL(hex) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    if (!result) return null;

    const r = parseInt(result[1], 16);
    const g = parseInt(result[2], 16);
    const b = parseInt(result[3], 16);

    return this.rgbToHSL(r, g, b);
  }

  rgbToHSL(r, g, b) {
    r /= 255;
    g /= 255;
    b /= 255;

    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    let h, s, l = (max + min) / 2;

    if (max === min) {
      h = s = 0;
    } else {
      const d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);

      switch (max) {
        case r: h = ((g - b) / d + (g < b ? 6 : 0)) / 6; break;
        case g: h = ((b - r) / d + 2) / 6; break;
        case b: h = ((r - g) / d + 4) / 6; break;
      }
    }

    return {
      h: Math.round(h * 360),
      s: Math.round(s * 100),
      l: Math.round(l * 100)
    };
  }

  groupColorsByShades(colors) {
    const groups = {};

    Object.entries(colors).forEach(([name, color]) => {
      const base = name.replace(/-\d+$/, '').replace(/\d+$/, '');
      if (!groups[base]) {
        groups[base] = [];
      }
      groups[base].push({ name, color });
    });

    return groups;
  }

  calculateShadeConsistency(shadeGroups) {
    let totalConsistency = 0;
    let groupCount = 0;

    Object.values(shadeGroups).forEach(shades => {
      if (shades.length > 1) {
        groupCount++;
        // Check if shades follow a consistent progression
        const hslValues = shades
          .map(s => this.toHSL(s.color))
          .filter(hsl => hsl !== null)
          .sort((a, b) => a.l - b.l);

        if (hslValues.length > 1) {
          let consistent = true;
          for (let i = 1; i < hslValues.length; i++) {
            const hueDiff = Math.abs(hslValues[i].h - hslValues[i-1].h);
            if (hueDiff > 10) {
              consistent = false;
              break;
            }
          }
          totalConsistency += consistent ? 1 : 0.5;
        }
      }
    });

    return groupCount > 0 ? totalConsistency / groupCount : 1;
  }

  detectProgression(values) {
    if (values.length < 2) return { type: 'none', factor: 0 };

    // Check for linear progression
    const diffs = [];
    for (let i = 1; i < values.length; i++) {
      diffs.push(values[i] - values[i-1]);
    }

    const avgDiff = diffs.reduce((a, b) => a + b, 0) / diffs.length;
    const isLinear = diffs.every(d => Math.abs(d - avgDiff) < avgDiff * 0.2);

    if (isLinear) {
      return { type: 'linear', factor: avgDiff };
    }

    // Check for exponential progression
    const ratios = [];
    for (let i = 1; i < values.length; i++) {
      if (values[i-1] !== 0) {
        ratios.push(values[i] / values[i-1]);
      }
    }

    if (ratios.length > 0) {
      const avgRatio = ratios.reduce((a, b) => a + b, 0) / ratios.length;
      const isExponential = ratios.every(r => Math.abs(r - avgRatio) < avgRatio * 0.2);

      if (isExponential) {
        return { type: 'exponential', factor: avgRatio };
      }
    }

    return { type: 'mixed', factor: 0 };
  }

  calculateProgressionConsistency(values, progression) {
    if (progression.type === 'none' || progression.type === 'mixed') {
      return 0.5;
    }

    let deviations = 0;

    if (progression.type === 'linear') {
      for (let i = 1; i < values.length; i++) {
        const expected = values[i-1] + progression.factor;
        const deviation = Math.abs(values[i] - expected) / expected;
        deviations += deviation;
      }
    } else if (progression.type === 'exponential') {
      for (let i = 1; i < values.length; i++) {
        const expected = values[i-1] * progression.factor;
        const deviation = Math.abs(values[i] - expected) / expected;
        deviations += deviation;
      }
    }

    const avgDeviation = values.length > 1 ? deviations / (values.length - 1) : 0;
    return Math.max(0, 1 - avgDeviation);
  }

  checkScaleAdherence(values) {
    const commonScales = {
      'minor-third': 1.2,
      'major-third': 1.25,
      'perfect-fourth': 1.333,
      'augmented-fourth': 1.414,
      'perfect-fifth': 1.5,
      'golden-ratio': 1.618
    };

    let bestMatch = null;
    let bestScore = 0;

    Object.entries(commonScales).forEach(([name, ratio]) => {
      let score = 0;
      for (let i = 1; i < values.length; i++) {
        if (values[i-1] !== 0) {
          const actualRatio = values[i] / values[i-1];
          const deviation = Math.abs(actualRatio - ratio) / ratio;
          score += (1 - Math.min(deviation, 1));
        }
      }

      const avgScore = values.length > 1 ? score / (values.length - 1) : 0;
      if (avgScore > bestScore) {
        bestScore = avgScore;
        bestMatch = name;
      }
    });

    return {
      score: bestScore,
      recommendedScale: bestMatch
    };
  }

  findSpacingOutliers(values, progression) {
    const outliers = [];

    if (progression.type === 'linear' || progression.type === 'exponential') {
      for (let i = 1; i < values.length; i++) {
        let expected;
        if (progression.type === 'linear') {
          expected = values[i-1] + progression.factor;
        } else {
          expected = values[i-1] * progression.factor;
        }

        const deviation = Math.abs(values[i] - expected) / expected;
        if (deviation > 0.3) {
          outliers.push({
            value: values[i],
            expected,
            deviation: Math.round(deviation * 100)
          });
        }
      }
    }

    return outliers;
  }

  analyzeTypographicScale(fontSizes) {
    const sorted = fontSizes.filter(s => s !== null).sort((a, b) => a - b);

    if (sorted.length < 2) {
      return { score: 1, scale: 'insufficient-data' };
    }

    // Check for common type scales
    const typeScales = {
      'minor-second': 1.067,
      'major-second': 1.125,
      'minor-third': 1.2,
      'major-third': 1.25,
      'perfect-fourth': 1.333,
      'augmented-fourth': 1.414,
      'perfect-fifth': 1.5,
      'minor-sixth': 1.6,
      'golden-ratio': 1.618,
      'major-sixth': 1.667,
      'minor-seventh': 1.778,
      'major-seventh': 1.875,
      'octave': 2.0
    };

    let bestMatch = null;
    let bestScore = 0;

    Object.entries(typeScales).forEach(([name, ratio]) => {
      let score = 0;
      let comparisons = 0;

      for (let i = 1; i < sorted.length; i++) {
        if (sorted[i-1] > 0) {
          const actualRatio = sorted[i] / sorted[i-1];
          const deviation = Math.abs(actualRatio - ratio) / ratio;
          score += Math.max(0, 1 - deviation);
          comparisons++;
        }
      }

      const avgScore = comparisons > 0 ? score / comparisons : 0;
      if (avgScore > bestScore) {
        bestScore = avgScore;
        bestMatch = name;
      }
    });

    return {
      score: bestScore,
      scale: bestMatch,
      sizes: sorted.length
    };
  }

  analyzeLineHeightConsistency(lineHeights, fontSizes) {
    if (lineHeights.length === 0) {
      return { score: 1, ratio: 'none' };
    }

    const ratios = [];

    for (let i = 0; i < Math.min(lineHeights.length, fontSizes.length); i++) {
      if (fontSizes[i] && fontSizes[i] > 0) {
        ratios.push(lineHeights[i] / fontSizes[i]);
      }
    }

    if (ratios.length === 0) {
      return { score: 0.5, ratio: 'no-pairs' };
    }

    const avgRatio = ratios.reduce((a, b) => a + b, 0) / ratios.length;
    const consistency = ratios.reduce((score, ratio) => {
      const deviation = Math.abs(ratio - avgRatio) / avgRatio;
      return score + Math.max(0, 1 - deviation);
    }, 0) / ratios.length;

    return {
      score: consistency,
      ratio: avgRatio,
      consistent: consistency > 0.8
    };
  }

  analyzeFontWeightConsistency(fontWeights) {
    if (fontWeights.length === 0) {
      return { score: 1, weights: [] };
    }

    const standardWeights = [100, 200, 300, 400, 500, 600, 700, 800, 900];
    const validWeights = fontWeights.filter(w => w !== null);

    if (validWeights.length === 0) {
      return { score: 0.5, weights: [] };
    }

    const matchingStandard = validWeights.filter(w => standardWeights.includes(w));
    const score = matchingStandard.length / validWeights.length;

    return {
      score,
      weights: [...new Set(validWeights)].sort((a, b) => a - b),
      nonStandard: validWeights.filter(w => !standardWeights.includes(w))
    };
  }

  // Additional helper methods for other missing functionality
  generateContrastPairs(colors) {
    const pairs = [];
    const colorEntries = Object.entries(colors);

    for (let i = 0; i < colorEntries.length; i++) {
      for (let j = i + 1; j < colorEntries.length; j++) {
        const [name1, color1] = colorEntries[i];
        const [name2, color2] = colorEntries[j];

        const ratio = this.calculateContrastRatio(color1, color2);
        pairs.push({
          color1: name1,
          color2: name2,
          ratio
        });
      }
    }

    return pairs;
  }

  calculateContrastRatio(color1, color2) {
    // Simplified contrast calculation
    const l1 = this.getRelativeLuminance(color1);
    const l2 = this.getRelativeLuminance(color2);

    const lighter = Math.max(l1, l2);
    const darker = Math.min(l1, l2);

    return (lighter + 0.05) / (darker + 0.05);
  }

  getRelativeLuminance(color) {
    const rgb = this.colorToRGB(color);
    if (!rgb) return 0;

    const [r, g, b] = [rgb.r / 255, rgb.g / 255, rgb.b / 255].map(channel => {
      return channel <= 0.03928
        ? channel / 12.92
        : Math.pow((channel + 0.055) / 1.055, 2.4);
    });

    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }

  colorToRGB(color) {
    if (typeof color === 'object' && color.value) {
      color = color.value;
    }

    if (typeof color === 'string') {
      if (color.startsWith('#')) {
        const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(color);
        if (result) {
          return {
            r: parseInt(result[1], 16),
            g: parseInt(result[2], 16),
            b: parseInt(result[3], 16)
          };
        }
      } else if (color.startsWith('rgb')) {
        const match = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
        if (match) {
          return {
            r: parseInt(match[1]),
            g: parseInt(match[2]),
            b: parseInt(match[3])
          };
        }
      }
    }

    return null;
  }

  // Stub methods for missing functionality
  generateContrastRecommendations(contrastPairs) {
    return contrastPairs
      .filter(pair => pair.ratio < 4.5)
      .map(pair => `Improve contrast between ${pair.color1} and ${pair.color2}`);
  }

  simulateColorBlindness(colors, type) {
    // Simplified simulation - would need full implementation
    return colors;
  }

  calculateColorDistinguishability(colors, simulatedColors) {
    return {
      overall: 0.8,
      byType: { protanopia: 0.8, deuteranopia: 0.8, tritanopia: 0.8 },
      criticalIssues: []
    };
  }

  generateColorBlindnessRecommendations(distinguishability) {
    return [];
  }

  calculateBundlingEfficiency(tokens) {
    return { score: 0.8 };
  }

  identifyPerformanceOptimizations(performance) {
    return [];
  }

  calculateEstimatedSavings(performance) {
    return { bytes: 0, percentage: 0 };
  }

  // Additional stub methods
  getSizeGrade(sizeKB, thresholds) {
    if (sizeKB < thresholds.excellent) return 'A';
    if (sizeKB < thresholds.good) return 'B';
    if (sizeKB < thresholds.fair) return 'C';
    return 'D';
  }

  getSizeRecommendations(sizeKB, thresholds) {
    if (sizeKB > thresholds.fair) {
      return ['Consider splitting tokens into modules', 'Remove unused tokens'];
    }
    return [];
  }

  getComplexityRecommendations(complexity) {
    if (complexity > 1) {
      return ['Simplify token structure', 'Reduce nesting depth'];
    }
    return [];
  }

  getRedundancyRecommendations(ratio, duplicates) {
    if (ratio > 0.2) {
      return ['Use token references instead of duplicating values'];
    }
    return [];
  }

  // More stub methods for missing functionality
  analyzeMaintainableNaming(tokens) {
    return { score: 0.8 };
  }

  analyzeMaintainableStructure(tokens) {
    return { score: 0.8 };
  }

  analyzeDependencies(tokens) {
    return { score: 0.8 };
  }

  analyzeDocumentation(tokens) {
    return { score: 0.7 };
  }

  analyzeVersioning(tokens) {
    return { score: 0.7 };
  }

  identifyMaintainabilityRisks(maintainability) {
    return [];
  }

  generateMaintainabilityRecommendations(maintainability) {
    return [];
  }

  analyzeArchitecturalScalability(tokens) {
    return { score: 0.8 };
  }

  analyzeNamingScalability(tokens) {
    return { score: 0.8 };
  }

  analyzeOrganizationalScalability(tokens) {
    return { score: 0.8 };
  }

  analyzeExtensibility(tokens) {
    return { score: 0.8 };
  }

  identifyScalabilityBottlenecks(scalability) {
    return [];
  }

  generateScalabilityRecommendations(scalability) {
    return [];
  }

  analyzeIntuitiveness(tokens) {
    return { score: 0.8 };
  }

  analyzeDiscoverability(tokens) {
    return { score: 0.8 };
  }

  analyzeLearnability(tokens) {
    return { score: 0.8 };
  }

  analyzeUsageEfficiency(tokens) {
    return { score: 0.8 };
  }

  assessUserExperience(usability) {
    return { score: 0.8 };
  }

  generateUsabilityRecommendations(usability) {
    return [];
  }

  calculateCategoryCompleteness(tokens, categories) {
    const present = categories.filter(cat => tokens[cat] && Object.keys(tokens[cat]).length > 0);
    return {
      score: present.length / categories.length,
      present: present.length,
      total: categories.length
    };
  }

  identifyMissingCategories(tokens, required, recommended, advanced) {
    const missing = {
      required: required.filter(cat => !tokens[cat] || Object.keys(tokens[cat]).length === 0),
      recommended: recommended.filter(cat => !tokens[cat] || Object.keys(tokens[cat]).length === 0),
      advanced: advanced.filter(cat => !tokens[cat] || Object.keys(tokens[cat]).length === 0)
    };

    return missing;
  }

  generateCompletenessRecommendations(completeness) {
    return [];
  }

  analyzeW3CCompliance(tokens) {
    return { score: 0.9 };
  }

  analyzeWCAGCompliance(tokens, accessibility) {
    return { score: accessibility ? accessibility.score : 0.8 };
  }

  analyzeDesignTokenStandards(tokens) {
    return { score: 0.8 };
  }

  analyzeIndustryStandards(tokens, patterns) {
    return { score: 0.8 };
  }

  determineCertifications(compliance) {
    return [];
  }

  generateComplianceRecommendations(compliance) {
    return [];
  }

  analyzeTypographyAccessibility(typography) {
    return { score: 0.8 };
  }

  analyzeFocusStateAccessibility(tokens) {
    return { score: 0.8 };
  }

  analyzeMotionAccessibility(animations) {
    return { score: 0.9 };
  }

  determineWCAGLevel(accessibility) {
    if (accessibility.contrast && accessibility.contrast.score >= 0.9) {
      return 'AAA';
    }
    if (accessibility.contrast && accessibility.contrast.score >= 0.7) {
      return 'AA';
    }
    return 'A';
  }

  findAccessibilityViolations(accessibility) {
    return [];
  }

  generateAccessibilityRecommendations(accessibility) {
    return [];
  }

  suggestConsistencyImprovements(consistency) {
    return [];
  }

  assessRisks(metrics, tokens) {
    return [];
  }

  calculateTrends(metrics) {
    return {};
  }

  compareToBenchmarks(metrics) {
    return {};
  }

  calculatePercentile(score) {
    if (score >= 90) return 95;
    if (score >= 80) return 85;
    if (score >= 70) return 70;
    if (score >= 60) return 50;
    if (score >= 50) return 30;
    return 10;
  }
}

module.exports = QualityMetrics;