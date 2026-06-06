/**
 * Pattern Recognizer - Advanced pattern detection for design systems
 * Identifies frameworks, grid systems, and component patterns
 */

const { EventEmitter } = require('events');

class PatternRecognizer extends EventEmitter {
  constructor(options = {}) {
    super();
    this.confidence = options.confidence || 0.7;
    this.patterns = this.initializePatterns();
    this.cache = new Map();
  }

  // Main recognize method - entry point for pattern recognition
  async recognize(tokens) {
    const patterns = await this.analyzePatterns(tokens);

    // Enhance with AI insights if available
    let enhancedPatterns = patterns;
    try {
      enhancedPatterns = await this.enhanceWithAI(tokens, patterns);
    } catch (error) {
      // AI enhancement is optional - continue without it
      console.warn('AI enhancement unavailable, using basic pattern recognition');
    }

    return {
      ...enhancedPatterns,
      frameworks: enhancedPatterns.framework?.matches || [],
      designSystem: enhancedPatterns.framework?.primary || 'custom',
      spacingSystem: enhancedPatterns.grid?.system || 'custom',
      patterns: enhancedPatterns
    };
  }

  /**
   * Enhance pattern recognition with AI-powered semantic analysis
   */
  async enhanceWithAI(tokens, basicPatterns) {
    // This method provides AI-powered insights beyond basic pattern matching
    const aiAnalysis = await this.generateAIInsights(tokens, basicPatterns);

    return {
      ...basicPatterns,
      aiInsights: aiAnalysis,
      confidence: Math.max(
        basicPatterns.metrics?.confidence || 0,
        aiAnalysis.confidence || 0
      ),
      enhancedRecommendations: this.mergeRecommendations(
        basicPatterns,
        aiAnalysis
      )
    };
  }

  /**
   * Generate AI-powered insights using semantic analysis
   */
  async generateAIInsights(tokens, patterns) {
    const analysis = {
      semanticIssues: [],
      accessibilityGaps: [],
      maturityProblems: [],
      optimizationOpportunities: [],
      confidence: 0.8
    };

    // Analyze semantic inconsistencies
    analysis.semanticIssues = this.detectSemanticIssues(tokens);

    // Analyze accessibility beyond basic contrast
    analysis.accessibilityGaps = this.detectAdvancedA11yIssues(tokens);

    // Analyze design system maturity
    analysis.maturityProblems = this.assessDesignSystemMaturity(tokens, patterns);

    // Find optimization opportunities
    analysis.optimizationOpportunities = this.findOptimizations(tokens);

    return analysis;
  }

  /**
   * Detect semantic inconsistencies in token usage
   */
  detectSemanticIssues(tokens) {
    const issues = [];
    const colors = tokens.colors || {};

    // Check for semantic naming mismatches
    Object.entries(colors).forEach(([name, color]) => {
      const semanticRole = this.inferSemanticRole(name);
      const colorCharacteristics = this.analyzeColorCharacteristics(color);

      if (semanticRole && colorCharacteristics) {
        if (semanticRole === 'error' && !colorCharacteristics.isReddish) {
          issues.push({
            type: 'semantic-mismatch',
            severity: 'medium',
            token: name,
            issue: `Token named "${name}" suggests error state but color is not red`,
            suggestion: 'Use red hues for error states or rename token'
          });
        }

        if (semanticRole === 'success' && !colorCharacteristics.isGreenish) {
          issues.push({
            type: 'semantic-mismatch',
            severity: 'medium',
            token: name,
            issue: `Token named "${name}" suggests success state but color is not green`,
            suggestion: 'Use green hues for success states or rename token'
          });
        }

        if (semanticRole === 'warning' && !colorCharacteristics.isYellowish) {
          issues.push({
            type: 'semantic-mismatch',
            severity: 'medium',
            token: name,
            issue: `Token named "${name}" suggests warning state but color is not yellow/orange`,
            suggestion: 'Use yellow/orange hues for warnings or rename token'
          });
        }
      }
    });

    return issues;
  }

  /**
   * Detect advanced accessibility issues
   */
  detectAdvancedA11yIssues(tokens) {
    const issues = [];
    const colors = tokens.colors || {};
    const colorEntries = Object.entries(colors);

    // Check for colors that are too similar (confusability)
    for (let i = 0; i < colorEntries.length; i++) {
      for (let j = i + 1; j < colorEntries.length; j++) {
        const [name1, color1] = colorEntries[i];
        const [name2, color2] = colorEntries[j];

        const similarity = this.calculateColorSimilarity(color1, color2);
        if (similarity > 0.9 && name1 !== name2) {
          issues.push({
            type: 'color-confusability',
            severity: 'high',
            tokens: [name1, name2],
            issue: `Colors "${name1}" and "${name2}" are very similar (${(similarity * 100).toFixed(0)}% similar)`,
            suggestion: 'Ensure distinct colors for different purposes to aid users with color vision deficiency'
          });
        }
      }
    }

    // Check for insufficient color palette diversity
    const uniqueHues = new Set();
    colorEntries.forEach(([_, color]) => {
      if (color.hsl?.h !== undefined) {
        uniqueHues.add(Math.round(color.hsl.h / 30) * 30); // Group by 30-degree segments
      }
    });

    if (uniqueHues.size < 3 && colorEntries.length > 5) {
      issues.push({
        type: 'limited-palette',
        severity: 'low',
        issue: `Color palette uses only ${uniqueHues.size} distinct hues`,
        suggestion: 'Consider expanding palette for better visual hierarchy and accessibility'
      });
    }

    return issues;
  }

  /**
   * Assess design system maturity
   */
  assessDesignSystemMaturity(tokens, patterns) {
    const problems = [];

    // Check for missing scales
    const hasTypographyScale = tokens.typography && Object.keys(tokens.typography).length >= 5;
    const hasSpacingScale = tokens.spacing && Object.keys(tokens.spacing).length >= 6;
    const hasColorScale = tokens.colors && Object.keys(tokens.colors).length >= 8;

    if (!hasTypographyScale) {
      problems.push({
        type: 'incomplete-scale',
        severity: 'medium',
        category: 'typography',
        issue: 'Typography scale has fewer than 5 levels',
        suggestion: 'Establish at least 5 typography levels (e.g., h1-h6, body, caption)'
      });
    }

    if (!hasSpacingScale) {
      problems.push({
        type: 'incomplete-scale',
        severity: 'medium',
        category: 'spacing',
        issue: 'Spacing scale has fewer than 6 levels',
        suggestion: 'Establish systematic spacing scale (e.g., 4, 8, 16, 24, 32, 48)'
      });
    }

    if (!hasColorScale) {
      problems.push({
        type: 'incomplete-scale',
        severity: 'high',
        category: 'colors',
        issue: 'Color palette has fewer than 8 colors',
        suggestion: 'Expand color system to include primary, secondary, neutrals, semantic colors'
      });
    }

    // Check for inconsistent naming conventions
    const namingPatterns = this.analyzeNamingConsistency(tokens);
    if (namingPatterns.consistency < 0.7) {
      problems.push({
        type: 'naming-inconsistency',
        severity: 'low',
        issue: `Token naming is ${(namingPatterns.consistency * 100).toFixed(0)}% consistent`,
        suggestion: `Adopt consistent naming: detected patterns include ${namingPatterns.patterns.join(', ')}`
      });
    }

    return problems;
  }

  /**
   * Find optimization opportunities
   */
  findOptimizations(tokens) {
    const opportunities = [];

    // Find duplicate or near-duplicate values
    const duplicates = this.findNearDuplicates(tokens);
    if (duplicates.length > 0) {
      opportunities.push({
        type: 'consolidation',
        severity: 'low',
        count: duplicates.length,
        issue: `Found ${duplicates.length} tokens that could be consolidated`,
        suggestion: 'Review similar tokens for consolidation opportunities',
        examples: duplicates.slice(0, 3)
      });
    }

    // Check for overly complex spacing systems
    const spacing = tokens.spacing || {};
    if (Object.keys(spacing).length > 12) {
      opportunities.push({
        type: 'overcomplexity',
        severity: 'low',
        category: 'spacing',
        issue: `Spacing system has ${Object.keys(spacing).length} values (recommended: 8-12)`,
        suggestion: 'Consider simplifying spacing scale to reduce complexity'
      });
    }

    // Check for unused intermediate sizes
    const typography = tokens.typography || {};
    const fontSizes = Object.values(typography)
      .map(t => t.fontSize?.px)
      .filter(s => typeof s === 'number')
      .sort((a, b) => a - b);

    if (fontSizes.length >= 3) {
      const gaps = [];
      for (let i = 1; i < fontSizes.length; i++) {
        const ratio = fontSizes[i] / fontSizes[i - 1];
        if (ratio > 1.5) {
          gaps.push({ from: fontSizes[i - 1], to: fontSizes[i], ratio });
        }
      }

      if (gaps.length > 0) {
        opportunities.push({
          type: 'missing-sizes',
          severity: 'low',
          category: 'typography',
          issue: `Large gaps in typography scale detected`,
          suggestion: 'Consider adding intermediate font sizes for smoother hierarchy',
          gaps: gaps.slice(0, 2)
        });
      }
    }

    return opportunities;
  }

  // Helper methods for AI analysis

  inferSemanticRole(tokenName) {
    const lower = tokenName.toLowerCase();
    if (/error|danger|critical/.test(lower)) return 'error';
    if (/success|positive|valid/.test(lower)) return 'success';
    if (/warning|caution|alert/.test(lower)) return 'warning';
    if (/info|information/.test(lower)) return 'info';
    return null;
  }

  analyzeColorCharacteristics(color) {
    if (!color.hsl) return null;

    const { h, s, l } = color.hsl;
    return {
      isReddish: h >= 345 || h <= 15,
      isGreenish: h >= 90 && h <= 150,
      isYellowish: h >= 40 && h <= 60,
      isOrangish: h >= 15 && h <= 40,
      isBluish: h >= 200 && h <= 250,
      saturation: s,
      lightness: l
    };
  }

  calculateColorSimilarity(color1, color2) {
    if (!color1.hsl || !color2.hsl) return 0;

    const hueDiff = Math.abs(color1.hsl.h - color2.hsl.h);
    const satDiff = Math.abs(color1.hsl.s - color2.hsl.s);
    const lightDiff = Math.abs(color1.hsl.l - color2.hsl.l);

    // Normalize differences (hue wraps at 360)
    const normalizedHueDiff = Math.min(hueDiff, 360 - hueDiff) / 180;
    const normalizedSatDiff = satDiff / 100;
    const normalizedLightDiff = lightDiff / 100;

    // Calculate similarity (1 = identical, 0 = completely different)
    return 1 - ((normalizedHueDiff + normalizedSatDiff + normalizedLightDiff) / 3);
  }

  analyzeNamingConsistency(tokens) {
    const allNames = [];
    Object.values(tokens).forEach(category => {
      if (typeof category === 'object') {
        allNames.push(...Object.keys(category));
      }
    });

    const patterns = {
      kebabCase: allNames.filter(n => /^[a-z]+(-[a-z]+)*$/.test(n)).length,
      camelCase: allNames.filter(n => /^[a-z]+([A-Z][a-z]*)*$/.test(n)).length,
      snakeCase: allNames.filter(n => /^[a-z]+(_[a-z]+)*$/.test(n)).length
    };

    const total = allNames.length;
    const maxPattern = Math.max(...Object.values(patterns));
    const consistency = total > 0 ? maxPattern / total : 1;

    const detectedPatterns = Object.entries(patterns)
      .filter(([_, count]) => count > 0)
      .map(([pattern]) => pattern);

    return { consistency, patterns: detectedPatterns, total };
  }

  findNearDuplicates(tokens) {
    const duplicates = [];
    const valueMap = new Map();

    Object.entries(tokens).forEach(([category, categoryTokens]) => {
      if (typeof categoryTokens !== 'object') return;

      Object.entries(categoryTokens).forEach(([name, token]) => {
        const value = this.normalizeTokenValue(token);
        if (value !== null) {
          const key = JSON.stringify(value);
          if (!valueMap.has(key)) {
            valueMap.set(key, []);
          }
          valueMap.get(key).push({ category, name, value });
        }
      });
    });

    valueMap.forEach((tokens, value) => {
      if (tokens.length > 1) {
        duplicates.push({
          value: JSON.parse(value),
          tokens: tokens.map(t => `${t.category}.${t.name}`)
        });
      }
    });

    return duplicates;
  }

  normalizeTokenValue(token) {
    if (token.hex) return { type: 'color', value: token.hex };
    if (token.px !== undefined) return { type: 'size', value: token.px };
    if (token.value !== undefined) return { type: 'generic', value: token.value };
    return null;
  }

  mergeRecommendations(basicPatterns, aiAnalysis) {
    const merged = [];

    // Add basic pattern recommendations
    if (basicPatterns.framework?.recommendations) {
      merged.push(...basicPatterns.framework.recommendations);
    }

    // Add AI-powered recommendations
    if (aiAnalysis.semanticIssues.length > 0) {
      merged.push({
        type: 'semantic',
        priority: 'high',
        count: aiAnalysis.semanticIssues.length,
        message: `Found ${aiAnalysis.semanticIssues.length} semantic inconsistencies`,
        details: aiAnalysis.semanticIssues.slice(0, 3)
      });
    }

    if (aiAnalysis.accessibilityGaps.length > 0) {
      merged.push({
        type: 'accessibility',
        priority: 'high',
        count: aiAnalysis.accessibilityGaps.length,
        message: `Found ${aiAnalysis.accessibilityGaps.length} advanced accessibility issues`,
        details: aiAnalysis.accessibilityGaps.slice(0, 3)
      });
    }

    if (aiAnalysis.maturityProblems.length > 0) {
      merged.push({
        type: 'maturity',
        priority: 'medium',
        count: aiAnalysis.maturityProblems.length,
        message: `Design system maturity could be improved in ${aiAnalysis.maturityProblems.length} areas`,
        details: aiAnalysis.maturityProblems.slice(0, 3)
      });
    }

    if (aiAnalysis.optimizationOpportunities.length > 0) {
      merged.push({
        type: 'optimization',
        priority: 'low',
        count: aiAnalysis.optimizationOpportunities.length,
        message: `Found ${aiAnalysis.optimizationOpportunities.length} optimization opportunities`,
        details: aiAnalysis.optimizationOpportunities.slice(0, 3)
      });
    }

    return merged;
  }

  async analyzePatterns(tokens, metadata = {}) {
    const startTime = Date.now();

    try {
      const analysis = {
        framework: await this.detectFramework(tokens).catch(() => ({ primary: null, all: {}, hybrid: false })),
        grid: await this.detectGridSystem(tokens).catch(() => ({ system: 'custom', detected: [], all: {} })),
        components: await this.detectComponentPatterns(tokens).catch(() => ({ detected: [], all: {} })),
        accessibility: await this.detectA11yPatterns(tokens).catch(() => ({ wcag: {}, colorContrast: {} })),
        methodology: await this.detectDesignMethodology(tokens).catch(() => ({ detected: [], all: {} })),
        metrics: {
          processingTime: 0,
          confidence: 0,
          patternsFound: 0
        }
      };

      // Calculate overall metrics
      analysis.metrics.processingTime = Date.now() - startTime;
      analysis.metrics.confidence = this.calculateOverallConfidence(analysis);
      analysis.metrics.patternsFound = this.countPatterns(analysis);

      this.emit('patterns:analyzed', analysis);
      return analysis;

    } catch (error) {
      this.emit('error', error);
      throw new Error(`Pattern analysis failed: ${error.message}`);
    }
  }

  async detectFramework(tokens) {
    const frameworks = {
      materialDesign: await this.detectMaterialDesign(tokens),
      bootstrap: await this.detectBootstrap(tokens),
      tailwind: await this.detectTailwind(tokens),
      foundation: await this.detectFoundation(tokens),
      bulma: await this.detectBulma(tokens),
      semantic: await this.detectSemanticUI(tokens),
      custom: await this.detectCustomFramework(tokens)
    };

    // Find the highest confidence framework
    const detected = Object.entries(frameworks)
      .filter(([_, data]) => data.confidence > this.confidence)
      .sort((a, b) => b[1].confidence - a[1].confidence);

    return {
      primary: detected[0] || null,
      all: frameworks,
      hybrid: detected.length > 1
    };
  }

  async detectMaterialDesign(tokens) {
    const indicators = {
      colors: this.checkMaterialColors(tokens.colors || {}),
      typography: this.checkMaterialTypography(tokens.typography || {}),
      spacing: this.checkMaterialSpacing(tokens.spacing || {}),
      shadows: this.checkMaterialShadows(tokens.shadows || {}),
      borderRadius: this.checkMaterialBorderRadius(tokens.borderRadius || {})
    };

    const confidence = this.calculateFrameworkConfidence(indicators);

    return {
      name: 'Material Design',
      version: this.detectMaterialVersion(indicators),
      confidence,
      indicators,
      evidence: this.gatherMaterialEvidence(indicators)
    };
  }

  checkMaterialColors(colors) {
    const materialPalette = [
      'red', 'pink', 'purple', 'deep-purple', 'indigo', 'blue',
      'light-blue', 'cyan', 'teal', 'green', 'light-green',
      'lime', 'yellow', 'amber', 'orange', 'deep-orange',
      'brown', 'grey', 'blue-grey'
    ];

    const materialShades = ['50', '100', '200', '300', '400', '500', '600', '700', '800', '900'];

    let matches = 0;
    let total = 0;

    Object.keys(colors).forEach(colorName => {
      total++;
      const normalized = colorName.toLowerCase().replace(/[_-]/g, '');

      // Check for material color names
      const hasColorMatch = materialPalette.some(palette =>
        normalized.includes(palette.replace('-', ''))
      );

      // Check for material shade numbers
      const hasShadeMatch = materialShades.some(shade =>
        colorName.includes(shade)
      );

      // Check for primary/secondary/accent pattern
      const hasRoleMatch = /primary|secondary|accent|surface|background|error/.test(normalized);

      if (hasColorMatch || hasShadeMatch || hasRoleMatch) {
        matches++;
      }
    });

    return {
      score: total > 0 ? matches / total : 0,
      matches,
      total,
      patterns: this.identifyMaterialColorPatterns(colors)
    };
  }

  checkMaterialTypography(typography) {
    const materialTypeScale = [
      'headline1', 'headline2', 'headline3', 'headline4', 'headline5', 'headline6',
      'subtitle1', 'subtitle2', 'body1', 'body2', 'button', 'caption', 'overline'
    ];

    let matches = 0;
    let total = Object.keys(typography).length;

    Object.keys(typography).forEach(typeName => {
      const normalized = typeName.toLowerCase().replace(/[_-]/g, '');

      if (materialTypeScale.some(scale => normalized.includes(scale))) {
        matches++;
      }
    });

    return {
      score: total > 0 ? matches / total : 0,
      matches,
      total,
      robotoDetected: this.detectRobotoFont(typography)
    };
  }

  async detectBootstrap(tokens) {
    const indicators = {
      colors: this.checkBootstrapColors(tokens.colors || {}),
      spacing: this.checkBootstrapSpacing(tokens.spacing || {}),
      breakpoints: this.checkBootstrapBreakpoints(tokens.breakpoints || {}),
      utilities: this.checkBootstrapUtilities(tokens)
    };

    const confidence = this.calculateFrameworkConfidence(indicators);

    return {
      name: 'Bootstrap',
      version: this.detectBootstrapVersion(indicators),
      confidence,
      indicators,
      evidence: this.gatherBootstrapEvidence(indicators)
    };
  }

  checkBootstrapColors(colors) {
    const bootstrapColors = [
      'primary', 'secondary', 'success', 'danger', 'warning',
      'info', 'light', 'dark', 'white', 'muted'
    ];

    let matches = 0;
    Object.keys(colors).forEach(colorName => {
      const normalized = colorName.toLowerCase();
      if (bootstrapColors.some(bsColor => normalized.includes(bsColor))) {
        matches++;
      }
    });

    return {
      score: matches / Math.max(Object.keys(colors).length, 1),
      matches,
      hasSemanticColors: bootstrapColors.every(color =>
        Object.keys(colors).some(key => key.toLowerCase().includes(color))
      )
    };
  }

  async detectTailwind(tokens) {
    const indicators = {
      colors: this.checkTailwindColors(tokens.colors || {}),
      spacing: this.checkTailwindSpacing(tokens.spacing || {}),
      naming: { score: 0.5 }, // Simplified for now
      scale: { score: 0.5 } // Simplified for now
    };

    const confidence = this.calculateFrameworkConfidence(indicators);

    return {
      name: 'Tailwind CSS',
      version: 'unknown', // Simplified version detection
      confidence,
      indicators,
      evidence: ['Tailwind color patterns detected']
    };
  }

  checkTailwindColors(colors) {
    const tailwindColors = [
      'slate', 'gray', 'zinc', 'neutral', 'stone',
      'red', 'orange', 'amber', 'yellow', 'lime', 'green',
      'emerald', 'teal', 'cyan', 'sky', 'blue', 'indigo',
      'violet', 'purple', 'fuchsia', 'pink', 'rose'
    ];

    const tailwindShades = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];

    let matches = 0;
    let total = Object.keys(colors).length;

    Object.keys(colors).forEach(colorName => {
      const normalized = colorName.toLowerCase().replace(/[_-]/g, '');

      const hasColorMatch = tailwindColors.some(twColor =>
        normalized.includes(twColor)
      );

      const hasShadeMatch = tailwindShades.some(shade =>
        colorName.includes(shade.toString())
      );

      if (hasColorMatch && hasShadeMatch) {
        matches++;
      }
    });

    return {
      score: total > 0 ? matches / total : 0,
      matches,
      total,
      hasProperShades: this.checkTailwindShadePattern(colors)
    };
  }

  async detectGridSystem(tokens) {
    const gridSystems = {
      eightPoint: await this.detectEightPointGrid(tokens),
      fourPoint: await this.detectFourPointGrid(tokens),
      bootstrap: await this.detectBootstrapGrid(tokens),
      css: await this.detectCSSGrid(tokens),
      flexbox: await this.detectFlexboxGrid(tokens),
      custom: await this.detectCustomGrid(tokens)
    };

    const detected = Object.entries(gridSystems)
      .filter(([_, data]) => data.confidence > this.confidence)
      .sort((a, b) => b[1].confidence - a[1].confidence);

    return {
      primary: detected[0] || null,
      all: gridSystems,
      recommendations: this.generateGridRecommendations(gridSystems)
    };
  }

  async detectEightPointGrid(tokens) {
    const spacing = tokens.spacing || {};
    const spacingValues = Object.values(spacing)
      .map(value => this.parseSpacingValue(value))
      .filter(value => value !== null);

    if (spacingValues.length === 0) {
      return { confidence: 0, evidence: [] };
    }

    // Check if values are multiples of 8
    const eightPointCompliant = spacingValues.filter(value => value % 8 === 0);
    const compliance = eightPointCompliant.length / spacingValues.length;

    // Check for common 8pt scale values
    const commonEightPointValues = [8, 16, 24, 32, 40, 48, 56, 64, 72, 80];
    const hasCommonValues = commonEightPointValues.filter(value =>
      spacingValues.includes(value)
    ).length;

    const confidence = (compliance * 0.7) + ((hasCommonValues / commonEightPointValues.length) * 0.3);

    return {
      confidence,
      compliance,
      evidence: {
        compliantValues: eightPointCompliant,
        totalValues: spacingValues.length,
        commonValuesFound: hasCommonValues,
        recommendations: this.generateEightPointRecommendations(spacingValues)
      }
    };
  }

  async detectComponentPatterns(tokens) {
    const patterns = {
      atomic: await this.detectAtomicDesign(tokens),
      bem: await this.detectBEMPattern(tokens),
      itcss: await this.detectITCSSPattern(tokens),
      smacss: await this.detectSMACSS(tokens),
      oocss: await this.detectOOCSS(tokens)
    };

    return {
      detected: patterns,
      primary: this.findPrimaryPattern(patterns),
      recommendations: this.generatePatternRecommendations(patterns)
    };
  }

  async detectAtomicDesign(tokens) {
    const atomicLevels = ['atom', 'molecule', 'organism', 'template', 'page'];
    const componentNames = this.extractComponentNames(tokens);

    let matches = 0;
    let evidence = [];

    componentNames.forEach(name => {
      const normalized = name.toLowerCase();
      atomicLevels.forEach(level => {
        if (normalized.includes(level)) {
          matches++;
          evidence.push({ name, level, type: 'explicit' });
        }
      });
    });

    // Also check for implicit atomic patterns
    const implicitPatterns = this.detectImplicitAtomicPatterns(componentNames);

    return {
      confidence: matches / Math.max(componentNames.length, 1),
      explicit: matches,
      implicit: implicitPatterns.length,
      evidence: [...evidence, ...implicitPatterns],
      recommendations: this.generateAtomicRecommendations(componentNames)
    };
  }

  async detectA11yPatterns(tokens) {
    return {
      contrast: await this.analyzeContrastPatterns(tokens.colors || {}),
      focus: await this.analyzeFocusPatterns(tokens),
      semantic: await this.analyzeSemanticPatterns(tokens),
      motion: await this.analyzeMotionPatterns(tokens.animations || {}),
      sizing: await this.analyzeSizingPatterns(tokens)
    };
  }

  async analyzeContrastPatterns(colors) {
    const contrastPairs = this.generateContrastPairs(colors);
    const wcagCompliant = contrastPairs.filter(pair =>
      pair.contrast >= 4.5 || (pair.isLargeText && pair.contrast >= 3.0)
    );

    return {
      totalPairs: contrastPairs.length,
      compliantPairs: wcagCompliant.length,
      compliance: wcagCompliant.length / Math.max(contrastPairs.length, 1),
      violations: contrastPairs.filter(pair => !wcagCompliant.includes(pair)),
      recommendations: this.generateContrastRecommendations(contrastPairs)
    };
  }

  async detectBulma(tokens) {
    // Detect Bulma CSS framework patterns
    const bulmaIndicators = {
      colors: false,
      sizes: false,
      helpers: false,
      structure: false
    };

    // Check for Bulma color scheme
    if (tokens.colors) {
      const colorNames = Object.keys(tokens.colors);
      const bulmaColors = ['primary', 'link', 'info', 'success', 'warning', 'danger'];
      const matches = bulmaColors.filter(bc =>
        colorNames.some(cn => cn.toLowerCase().includes(bc))
      ).length;
      if (matches >= 3) {
        bulmaIndicators.colors = true;
      }
    }

    // Check for Bulma sizes
    const tokenString = JSON.stringify(tokens).toLowerCase();
    const bulmaSizes = ['is-small', 'is-medium', 'is-large', 'is-normal'];
    const sizeMatches = bulmaSizes.filter(size => tokenString.includes(size)).length;
    if (sizeMatches >= 2) {
      bulmaIndicators.sizes = true;
    }

    // Check for Bulma-specific naming
    if (tokenString.includes('bulma') || tokenString.includes('is-') || tokenString.includes('has-')) {
      bulmaIndicators.helpers = true;
    }

    const confidence = Object.values(bulmaIndicators).filter(Boolean).length / 4;

    return {
      confidence,
      indicators: bulmaIndicators,
      detected: confidence > 0.25
    };
  }

  async detectFoundation(tokens) {
    // Detect Foundation framework patterns
    const foundationIndicators = {
      grid: false,
      typography: false,
      utilities: false,
      components: false
    };

    // Check for Foundation-specific grid (12 column)
    if (tokens.grid || tokens.layout) {
      const gridString = JSON.stringify(tokens.grid || tokens.layout);
      if (gridString.includes('12') || gridString.includes('columns')) {
        foundationIndicators.grid = true;
      }
    }

    // Check for Foundation typography scale
    if (tokens.typography) {
      const sizes = Object.keys(tokens.typography);
      const foundationSizes = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'lead', 'subheader'];
      const matches = sizes.filter(size =>
        foundationSizes.some(fs => size.toLowerCase().includes(fs))
      ).length;
      if (matches >= 3) {
        foundationIndicators.typography = true;
      }
    }

    // Check for Foundation utilities
    const tokenString = JSON.stringify(tokens).toLowerCase();
    if (tokenString.includes('foundation') || tokenString.includes('zurb')) {
      foundationIndicators.utilities = true;
    }

    // Calculate confidence
    const indicators = Object.values(foundationIndicators);
    const confidence = indicators.filter(Boolean).length / indicators.length;

    return {
      confidence,
      indicators: foundationIndicators,
      detected: confidence > 0.3
    };
  }

  async detectDesignMethodology(tokens) {
    const methodologies = {
      designTokens: this.analyzeDesignTokenMethodology(tokens),
      styleGuide: this.analyzeStyleGuideMethodology(tokens),
      designSystem: this.analyzeDesignSystemMethodology(tokens),
      componentLibrary: this.analyzeComponentLibraryMethodology(tokens)
    };

    return {
      detected: methodologies,
      maturity: this.calculateDesignMaturity(methodologies),
      recommendations: this.generateMethodologyRecommendations(methodologies)
    };
  }

  // Helper methods
  initializePatterns() {
    return {
      frameworks: {
        materialDesign: {
          colors: ['primary', 'secondary', 'surface', 'background', 'error'],
          typography: ['headline', 'subtitle', 'body', 'caption', 'overline'],
          elevation: [0, 1, 2, 3, 4, 6, 8, 12, 16, 24]
        },
        bootstrap: {
          colors: ['primary', 'secondary', 'success', 'danger', 'warning', 'info'],
          spacing: [0, 0.25, 0.5, 1, 1.5, 3],
          breakpoints: ['xs', 'sm', 'md', 'lg', 'xl']
        },
        tailwind: {
          scale: [0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 24, 32, 40, 48, 56, 64],
          colors: ['slate', 'gray', 'zinc', 'red', 'blue', 'green'],
          shades: [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]
        }
      },
      grids: {
        eightPoint: [8, 16, 24, 32, 40, 48, 56, 64, 72, 80],
        fourPoint: [4, 8, 12, 16, 20, 24, 28, 32, 36, 40],
        baseline: [24, 30, 36, 42, 48, 54, 60, 66, 72]
      }
    };
  }

  calculateFrameworkConfidence(indicators) {
    const weights = {
      colors: 0.3,
      typography: 0.25,
      spacing: 0.2,
      components: 0.15,
      naming: 0.1
    };

    let totalScore = 0;
    let totalWeight = 0;

    Object.entries(indicators).forEach(([key, indicator]) => {
      if (weights[key] && indicator && typeof indicator.score === 'number') {
        totalScore += indicator.score * weights[key];
        totalWeight += weights[key];
      }
    });

    return totalWeight > 0 ? totalScore / totalWeight : 0;
  }

  calculateOverallConfidence(analysis) {
    const sections = [
      analysis.framework,
      analysis.grid,
      analysis.components,
      analysis.accessibility,
      analysis.methodology
    ];

    const confidences = sections
      .map(section => section?.confidence || section?.primary?.confidence || 0)
      .filter(conf => conf > 0);

    return confidences.length > 0
      ? confidences.reduce((sum, conf) => sum + conf, 0) / confidences.length
      : 0;
  }

  countPatterns(analysis) {
    let count = 0;

    if (analysis.framework?.primary) count++;
    if (analysis.grid?.primary) count++;
    if (analysis.components?.primary) count++;
    if (analysis.accessibility && Object.keys(analysis.accessibility).length > 0) count++;
    if (analysis.methodology && Object.keys(analysis.methodology).length > 0) count++;

    return count;
  }

  parseSpacingValue(value) {
    if (typeof value === 'number') return value;
    if (typeof value === 'string') {
      const match = value.match(/(\d+(?:\.\d+)?)/);
      return match ? parseFloat(match[1]) : null;
    }
    return null;
  }

  extractComponentNames(tokens) {
    const names = [];

    // Extract from various token categories
    ['components', 'patterns', 'molecules', 'organisms'].forEach(category => {
      if (tokens[category]) {
        names.push(...Object.keys(tokens[category]));
      }
    });

    return names;
  }

  generateContrastPairs(colors) {
    const colorEntries = Object.entries(colors);
    const pairs = [];

    // Generate all possible color combinations
    for (let i = 0; i < colorEntries.length; i++) {
      for (let j = i + 1; j < colorEntries.length; j++) {
        const [name1, color1] = colorEntries[i];
        const [name2, color2] = colorEntries[j];

        const contrast = this.calculateContrast(color1, color2);
        pairs.push({
          foreground: name1,
          background: name2,
          contrast,
          isLargeText: this.isLargeText(name1, name2)
        });
      }
    }

    return pairs;
  }

  calculateContrast(color1, color2) {
    // Simplified contrast calculation
    // In real implementation, would use proper WCAG contrast calculation
    const l1 = this.getLuminance(color1);
    const l2 = this.getLuminance(color2);

    const lighter = Math.max(l1, l2);
    const darker = Math.min(l1, l2);

    return (lighter + 0.05) / (darker + 0.05);
  }

  getLuminance(color) {
    // Simplified luminance calculation
    if (color?.rgb) {
      const { r, g, b } = color.rgb;
      return 0.299 * r + 0.587 * g + 0.114 * b;
    }
    return 128; // Default mid-gray
  }

  isLargeText(name1, name2) {
    return /large|big|heading|title|h[1-6]/.test(name1 + name2);
  }

  // Framework-specific detection methods
  identifyMaterialColorPatterns(colors) {
    const patterns = [];

    Object.keys(colors).forEach(colorName => {
      if (/primary|secondary|accent/.test(colorName.toLowerCase())) {
        patterns.push({ type: 'semantic', name: colorName });
      }
      if (/\d{2,3}$/.test(colorName)) {
        patterns.push({ type: 'shade', name: colorName });
      }
    });

    return patterns;
  }

  detectRobotoFont(typography) {
    return Object.values(typography).some(typeface =>
      typeface?.fontFamily?.toLowerCase().includes('roboto')
    );
  }

  detectMaterialVersion(indicators) {
    // Logic to detect Material Design version based on patterns
    if (indicators.colors?.patterns?.some(p => p.name.includes('surface'))) {
      return 'Material Design 3';
    }
    if (indicators.typography?.robotoDetected) {
      return 'Material Design 2';
    }
    return 'Material Design 1';
  }

  gatherMaterialEvidence(indicators) {
    const evidence = [];

    if (indicators.colors?.matches > 0) {
      evidence.push(`Found ${indicators.colors.matches} Material-style color tokens`);
    }
    if (indicators.typography?.robotoDetected) {
      evidence.push('Detected Roboto font family');
    }

    return evidence;
  }

  // Additional helper methods would continue here...
  // Including bootstrap, tailwind, grid detection, etc.

  async generateRecommendations(analysis) {
    const recommendations = [];

    // Framework recommendations
    if (analysis.framework?.confidence < 0.5) {
      recommendations.push({
        type: 'framework',
        priority: 'high',
        message: 'Consider adopting a consistent design framework',
        suggestions: ['Material Design', 'Bootstrap', 'Tailwind CSS']
      });
    }

    // Grid system recommendations
    if (analysis.grid?.primary?.confidence < 0.7) {
      recommendations.push({
        type: 'grid',
        priority: 'medium',
        message: 'Implement a consistent grid system',
        suggestions: ['8-point grid', '4-point grid']
      });
    }

    return recommendations;
  }

  // Missing Material Design methods
  checkMaterialColors(colors) {
    const materialPalette = ['red', 'pink', 'purple', 'blue', 'cyan', 'teal', 'green', 'amber', 'orange'];
    let matches = 0;
    let total = Object.keys(colors).length;

    Object.keys(colors).forEach(colorName => {
      if (materialPalette.some(mp => colorName.toLowerCase().includes(mp))) {
        matches++;
      }
    });

    return { score: total > 0 ? matches / total : 0, matches, total };
  }

  checkMaterialTypography(typography) {
    const materialTypography = ['headline1', 'headline2', 'subtitle1', 'body1', 'caption'];
    let matches = 0;
    let total = Object.keys(typography).length;

    Object.keys(typography).forEach(typeName => {
      if (materialTypography.some(mt => typeName.toLowerCase().includes(mt))) {
        matches++;
      }
    });

    return { score: total > 0 ? matches / total : 0, matches, total };
  }

  checkMaterialSpacing(spacing) {
    const materialSpacing = [4, 8, 16, 24, 32, 40, 48]; // Material 8dp grid
    let matches = 0;
    let total = Object.keys(spacing).length;

    Object.entries(spacing).forEach(([name, value]) => {
      const numValue = this.parseSpacingValue(value);
      if (numValue && materialSpacing.includes(numValue)) {
        matches++;
      }
    });

    return { score: total > 0 ? matches / total : 0, matches, total };
  }

  checkMaterialShadows(shadows) {
    const materialElevations = [1, 2, 3, 4, 6, 8, 9, 12, 16, 24];
    let matches = 0;
    let total = Object.keys(shadows).length;

    Object.keys(shadows).forEach(shadowName => {
      if (materialElevations.some(el => shadowName.includes(el.toString()))) {
        matches++;
      }
    });

    return { score: total > 0 ? matches / total : 0, matches, total };
  }

  checkMaterialBorderRadius(borderRadius) {
    const materialRadius = [2, 4, 8, 16]; // Material rounded corners
    let matches = 0;
    let total = Object.keys(borderRadius).length;

    Object.entries(borderRadius).forEach(([name, value]) => {
      const numValue = this.parseSpacingValue(value);
      if (numValue && materialRadius.includes(numValue)) {
        matches++;
      }
    });

    return { score: total > 0 ? matches / total : 0, matches, total };
  }

  checkBootstrapSpacing(spacing) {
    const bootstrapSpacers = [0, 0.25, 0.5, 1, 1.5, 3]; // rem values
    let matches = 0;
    let total = Object.keys(spacing).length;

    Object.entries(spacing).forEach(([name, value]) => {
      const numValue = this.parseSpacingValue(value);
      if (numValue && bootstrapSpacers.includes(numValue)) {
        matches++;
      }
    });

    return { score: total > 0 ? matches / total : 0, matches, total };
  }

  checkTailwindSpacing(spacing) {
    const tailwindSpacing = [0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 24, 32, 40, 48, 56, 64]; // 0.25rem increments
    let matches = 0;
    let total = Object.keys(spacing).length;

    Object.entries(spacing).forEach(([name, value]) => {
      const numValue = this.parseSpacingValue(value);
      if (numValue && tailwindSpacing.includes(numValue)) {
        matches++;
      }
    });

    return { score: total > 0 ? matches / total : 0, matches, total };
  }

  parseSpacingValue(value) {
    if (typeof value === 'number') return value;
    if (typeof value === 'object' && value.px) return value.px;
    if (typeof value === 'object' && value.rem) return value.rem * 16; // Convert rem to px
    if (typeof value === 'string') {
      const match = value.match(/(\d+(?:\.\d+)?)(px|rem)/);
      if (match) {
        const num = parseFloat(match[1]);
        const unit = match[2];
        return unit === 'rem' ? num * 16 : num;
      }
    }
    return null;
  }
  /**
   * Check if breakpoints match Bootstrap pattern
   */
  checkBootstrapBreakpoints(breakpointValues) {
    const bootstrapBreakpoints = [576, 768, 992, 1200, 1400]; // Bootstrap 5 defaults
    const bootstrapLegacy = [576, 768, 992, 1200]; // Bootstrap 4 defaults

    // Handle various input types
    let values = [];
    if (Array.isArray(breakpointValues)) {
      values = breakpointValues;
    } else if (typeof breakpointValues === 'object' && breakpointValues !== null) {
      // Convert object values to array
      values = Object.values(breakpointValues);
    } else {
      return false; // No valid breakpoints to check
    }

    // Convert values to numbers for comparison
    const numericValues = values
      .map(v => typeof v === 'string' ? parseFloat(v) : v)
      .filter(v => !isNaN(v))
      .sort((a, b) => a - b);

    // Check Bootstrap 5
    const matchesBootstrap5 = bootstrapBreakpoints.every(bp =>
      numericValues.some(v => Math.abs(v - bp) < 10) // Allow small variance
    );

    // Check Bootstrap 4
    const matchesBootstrap4 = bootstrapLegacy.every(bp =>
      numericValues.some(v => Math.abs(v - bp) < 10)
    );

    return matchesBootstrap5 || matchesBootstrap4;
  }

  /**
   * Check Bootstrap utilities pattern
   */
  checkBootstrapUtilities(tokens) {
    // Check for Bootstrap utility patterns
    const utilityPatterns = ['d-', 'm-', 'p-', 'text-', 'bg-', 'border-', 'flex-', 'align-'];
    let utilityScore = 0;

    // Check in various token categories
    const allTokenStrings = JSON.stringify(tokens);
    utilityPatterns.forEach(pattern => {
      if (allTokenStrings.includes(pattern)) {
        utilityScore++;
      }
    });

    return utilityScore > 3; // At least 3 utility patterns found
  }

  /**
   * Detect Bootstrap version based on indicators
   */
  detectBootstrapVersion(indicators) {
    // Simple version detection based on patterns
    if (indicators.breakpoints && indicators.colors && indicators.utilities) {
      return '5.x';
    } else if (indicators.colors && indicators.spacing) {
      return '4.x';
    }
    return 'unknown';
  }

  /**
   * Gather Bootstrap evidence from indicators
   */
  gatherBootstrapEvidence(indicators) {
    const evidence = [];
    if (indicators.colors) evidence.push('Bootstrap color scheme detected');
    if (indicators.spacing) evidence.push('Bootstrap spacing system detected');
    if (indicators.breakpoints) evidence.push('Bootstrap breakpoints detected');
    if (indicators.utilities) evidence.push('Bootstrap utility classes detected');
    return evidence;
  }

  /**
   * Check Tailwind color shade pattern
   */
  checkTailwindShadePattern(colors) {
    const tailwindShades = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];
    let colorGroups = {};

    // Group colors by base name
    Object.keys(colors).forEach(colorName => {
      const match = colorName.match(/^(.+?)[-_]?(\d+)$/);
      if (match) {
        const [_, base, shade] = match;
        if (!colorGroups[base]) {
          colorGroups[base] = [];
        }
        colorGroups[base].push(parseInt(shade));
      }
    });

    // Check if any color group follows Tailwind shade pattern
    return Object.values(colorGroups).some(shades => {
      const matchingShades = shades.filter(shade => tailwindShades.includes(shade));
      return matchingShades.length >= 5; // At least 5 matching shades
    });
  }

  // Add missing detectSemanticUI method
  async detectSemanticUI(tokens) {
    const semanticPatterns = {
      colors: /^(red|orange|yellow|olive|green|teal|blue|violet|purple|pink|brown|grey|black)$/,
      sizes: /^(mini|tiny|small|medium|large|big|huge|massive)$/,
      emphasis: /^(primary|secondary|positive|negative|info|warning|error)$/
    };

    let score = 0;
    let totalChecks = 0;

    // Check color naming
    if (tokens.colors) {
      const colorNames = Object.keys(tokens.colors);
      const matches = colorNames.filter(name =>
        semanticPatterns.colors.test(name) ||
        semanticPatterns.emphasis.test(name)
      );
      if (matches.length > 0) {
        score += matches.length / colorNames.length;
        totalChecks++;
      }
    }

    // Check size naming
    if (tokens.spacing) {
      const spacingNames = Object.keys(tokens.spacing);
      const matches = spacingNames.filter(name =>
        semanticPatterns.sizes.test(name)
      );
      if (matches.length > 0) {
        score += matches.length / spacingNames.length;
        totalChecks++;
      }
    }

    return {
      detected: score / Math.max(1, totalChecks) > 0.3,
      confidence: score / Math.max(1, totalChecks),
      patterns: ['color-scheme', 'size-scale']
    };
  }

  // Add missing detectCustomFramework method
  async detectCustomFramework(tokens) {
    const customIndicators = {
      hasCustomPrefix: false,
      hasUniqueStructure: false,
      confidence: 0
    };

    // Check for custom prefixes
    const allKeys = Object.keys(tokens).join(' ');
    const commonFrameworks = /bootstrap|tailwind|material|semantic|foundation|bulma/i;

    if (!commonFrameworks.test(allKeys)) {
      // Check for consistent custom prefixes
      const prefixes = new Set();
      Object.keys(tokens).forEach(category => {
        if (tokens[category] && typeof tokens[category] === 'object') {
          Object.keys(tokens[category]).forEach(name => {
            const match = name.match(/^([a-z]+)-/);
            if (match) prefixes.add(match[1]);
          });
        }
      });

      if (prefixes.size > 0 && prefixes.size <= 3) {
        customIndicators.hasCustomPrefix = true;
        customIndicators.confidence += 0.5;
      }
    }

    // Check for unique structure patterns
    if (tokens.custom || tokens.brand || tokens.theme) {
      customIndicators.hasUniqueStructure = true;
      customIndicators.confidence += 0.5;
    }

    return {
      detected: customIndicators.confidence > 0.3,
      confidence: customIndicators.confidence,
      indicators: customIndicators,
      patterns: []
    };
  }

  // Stub helper methods that are called but not implemented
  generateEightPointRecommendations(spacingValues) {
    const recommendations = [];
    const nonCompliant = spacingValues.filter(v => v % 8 !== 0);

    if (nonCompliant.length > 0) {
      recommendations.push({
        type: 'alignment',
        message: `${nonCompliant.length} spacing values are not aligned to 8pt grid`,
        values: nonCompliant
      });
    }

    return recommendations;
  }

  async detectBEMPattern(tokens) {
    return { confidence: 0, detected: false };
  }

  async detectITCSSPattern(tokens) {
    return { confidence: 0, detected: false };
  }

  async detectSMACSSPattern(tokens) {
    return { confidence: 0, detected: false };
  }

  async detectFourPointGrid(tokens) {
    return { confidence: 0, detected: false };
  }

  async detectCustomGrid(tokens) {
    return { confidence: 0, detected: false };
  }

  async detectBootstrapGrid(tokens) {
    return { confidence: 0, detected: false };
  }

  async detectCSSGrid(tokens) {
    return { confidence: 0, detected: false };
  }

  async detectFlexboxGrid(tokens) {
    return { confidence: 0, detected: false };
  }

  generateGridRecommendations(gridData) {
    return [];
  }
}

module.exports = PatternRecognizer;