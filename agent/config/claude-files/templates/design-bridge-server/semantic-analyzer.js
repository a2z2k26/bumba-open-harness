/**
 * Semantic Analysis Engine
 * Advanced AI-powered semantic understanding of design tokens and components
 */

const { EventEmitter } = require('events');

class SemanticAnalyzer extends EventEmitter {
  constructor(options = {}) {
    super();
    this.confidence = options.confidence || 0.7;
    this.learningData = new Map();
    this.patterns = this.initializePatterns();
    this.semanticRules = this.defineSemanticRules();
  }

  initializePatterns() {
    return {
      colorSemantics: {
        primary: {
          keywords: ['primary', 'brand', 'main', 'key', 'hero', 'accent-primary'],
          contexts: ['buttons', 'links', 'headers', 'navigation'],
          confidence: 0.9
        },
        secondary: {
          keywords: ['secondary', 'alt', 'alternative', 'sub'],
          contexts: ['secondary-buttons', 'sidebar', 'footer'],
          confidence: 0.85
        },
        success: {
          keywords: ['success', 'valid', 'positive', 'good', 'correct', 'green'],
          contexts: ['alerts', 'status', 'feedback', 'validation'],
          confidence: 0.95
        },
        error: {
          keywords: ['error', 'danger', 'invalid', 'negative', 'wrong', 'red'],
          contexts: ['alerts', 'validation', 'errors', 'warnings'],
          confidence: 0.95
        },
        warning: {
          keywords: ['warning', 'caution', 'attention', 'yellow', 'amber'],
          contexts: ['alerts', 'notifications', 'status'],
          confidence: 0.9
        },
        info: {
          keywords: ['info', 'information', 'note', 'blue', 'notice'],
          contexts: ['alerts', 'tooltips', 'help', 'notifications'],
          confidence: 0.85
        },
        neutral: {
          keywords: ['neutral', 'gray', 'grey', 'text', 'body', 'content'],
          contexts: ['text', 'backgrounds', 'borders', 'dividers'],
          confidence: 0.8
        },
        surface: {
          keywords: ['surface', 'background', 'bg', 'base', 'canvas', 'page'],
          contexts: ['backgrounds', 'containers', 'cards', 'modals'],
          confidence: 0.85
        }
      },

      typographySemantics: {
        display: {
          keywords: ['display', 'hero', 'banner', 'poster', 'showcase'],
          characteristics: { minSize: 32, weight: [300, 700] },
          contexts: ['headers', 'banners', 'landing'],
          confidence: 0.9
        },
        heading: {
          keywords: ['heading', 'title', 'header', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'],
          characteristics: { minSize: 18, weight: [500, 900] },
          contexts: ['sections', 'articles', 'cards'],
          confidence: 0.95
        },
        body: {
          keywords: ['body', 'paragraph', 'content', 'text', 'regular'],
          characteristics: { sizeRange: [14, 18], weight: [400, 500] },
          contexts: ['content', 'descriptions', 'articles'],
          confidence: 0.85
        },
        caption: {
          keywords: ['caption', 'small', 'note', 'detail', 'meta', 'helper'],
          characteristics: { maxSize: 14, weight: [300, 500] },
          contexts: ['captions', 'footnotes', 'metadata'],
          confidence: 0.9
        },
        label: {
          keywords: ['label', 'tag', 'badge', 'chip', 'form'],
          characteristics: { sizeRange: [12, 16], weight: [500, 700] },
          contexts: ['forms', 'navigation', 'tags'],
          confidence: 0.85
        },
        code: {
          keywords: ['code', 'mono', 'monospace', 'terminal', 'console'],
          characteristics: { fontFamily: ['mono', 'code'] },
          contexts: ['code', 'technical', 'data'],
          confidence: 0.95
        }
      },

      spacingSemantics: {
        micro: {
          keywords: ['micro', 'tiny', 'minimal', 'tight'],
          range: [1, 4],
          usage: ['borders', 'fine-details', 'icon-spacing'],
          confidence: 0.8
        },
        small: {
          keywords: ['small', 'sm', 'compact', 'dense'],
          range: [4, 12],
          usage: ['padding', 'margins', 'gaps'],
          confidence: 0.85
        },
        medium: {
          keywords: ['medium', 'md', 'default', 'normal'],
          range: [12, 24],
          usage: ['sections', 'components', 'layouts'],
          confidence: 0.8
        },
        large: {
          keywords: ['large', 'lg', 'spacious', 'loose'],
          range: [24, 48],
          usage: ['sections', 'page-layout', 'headers'],
          confidence: 0.85
        },
        huge: {
          keywords: ['huge', 'xl', 'jumbo', 'massive'],
          range: [48, 96],
          usage: ['page-sections', 'hero-areas', 'major-layout'],
          confidence: 0.9
        }
      },

      componentSemantics: {
        atoms: {
          patterns: ['button', 'input', 'icon', 'avatar', 'badge', 'chip', 'tag'],
          characteristics: { complexity: 'low', variants: [1, 5] },
          confidence: 0.9
        },
        molecules: {
          patterns: ['card', 'form-field', 'search-box', 'breadcrumb', 'pagination'],
          characteristics: { complexity: 'medium', variants: [2, 8] },
          confidence: 0.85
        },
        organisms: {
          patterns: ['header', 'sidebar', 'modal', 'table', 'form', 'navigation'],
          characteristics: { complexity: 'high', variants: [3, 10] },
          confidence: 0.8
        }
      }
    };
  }

  defineSemanticRules() {
    return {
      colorRules: [
        {
          name: 'brand-hierarchy',
          description: 'Primary colors should dominate, secondary should support',
          validator: this.validateBrandHierarchy.bind(this)
        },
        {
          name: 'semantic-consistency',
          description: 'Semantic colors should be consistent across contexts',
          validator: this.validateSemanticConsistency.bind(this)
        },
        {
          name: 'color-psychology',
          description: 'Colors should align with psychological expectations',
          validator: this.validateColorPsychology.bind(this)
        }
      ],

      typographyRules: [
        {
          name: 'hierarchy-clarity',
          description: 'Typography hierarchy should be clear and logical',
          validator: this.validateTypographyHierarchy.bind(this)
        },
        {
          name: 'readability-optimization',
          description: 'Typography should optimize for readability',
          validator: this.validateReadability.bind(this)
        }
      ],

      componentRules: [
        {
          name: 'atomic-design',
          description: 'Components should follow atomic design principles',
          validator: this.validateAtomicDesign.bind(this)
        },
        {
          name: 'semantic-structure',
          description: 'Component structure should reflect semantic meaning',
          validator: this.validateSemanticStructure.bind(this)
        }
      ]
    };
  }

  // Main analyze method - entry point for semantic analysis
  async analyze(tokens) {
    const analysis = await this.analyzeTokens(tokens);

    return {
      ...analysis,
      categories: analysis.categories || {},
      semanticGroups: analysis.semanticGroups || {},
      summary: {
        totalTokens: this.countTokens(tokens),
        categories: Object.keys(tokens)
      }
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

  async analyzeTokens(tokens) {
    this.emit('analysis:started', { timestamp: Date.now() });

    const analysis = {
      colors: [],
      typography: [],
      spacing: [],
      components: [],
      semanticMapping: {},
      relationships: {},
      insights: [],
      recommendations: [],
      confidence: {},
      metadata: {
        analysisTime: Date.now(),
        totalTokens: this.countTokens(tokens),
        analyzedTokens: 0
      }
    };

    try {
      // Phase 1: Individual token semantic analysis
      analysis.semanticMapping = await this.mapTokenSemantics(tokens);

      // Populate structured analysis for compatibility
      if (tokens.colors) {
        analysis.colors = Object.keys(tokens.colors).map(colorName => ({
          name: colorName,
          semantic: analysis.semanticMapping[`color:${colorName}`] || 'neutral',
          confidence: 0.8
        }));
      }

      if (tokens.typography) {
        analysis.typography = Object.keys(tokens.typography).map(typeName => ({
          name: typeName,
          semantic: analysis.semanticMapping[`typography:${typeName}`] || 'body',
          confidence: 0.8
        }));
      }

      // Phase 2: Relationship analysis
      analysis.relationships = await this.analyzeRelationships(tokens, analysis.semanticMapping);

      // Phase 3: Context analysis
      const contextAnalysis = await this.analyzeContext(tokens, analysis.semanticMapping);
      analysis.insights.push(...contextAnalysis.insights);

      // Phase 4: Pattern recognition
      const patterns = await this.recognizePatterns(tokens, analysis.semanticMapping);
      analysis.insights.push(...patterns.insights);

      // Phase 5: Generate recommendations
      analysis.recommendations = await this.generateSmartRecommendations(
        tokens,
        analysis.semanticMapping,
        analysis.relationships
      );

      // Phase 6: Calculate confidence scores
      analysis.confidence = this.calculateConfidenceScores(analysis);

      analysis.metadata.analyzedTokens = Object.keys(analysis.semanticMapping).length;
      analysis.metadata.analysisTime = Date.now() - analysis.metadata.analysisTime;

      this.emit('analysis:completed', analysis);
      return analysis;

    } catch (error) {
      this.emit('analysis:error', error);
      throw error;
    }
  }

  async mapTokenSemantics(tokens) {
    const semanticMap = {};

    // Analyze colors
    if (tokens.tokens?.colors) {
      for (const [name, color] of Object.entries(tokens.tokens.colors)) {
        semanticMap[`color:${name}`] = await this.analyzeColorSemantics(name, color);
      }
    }

    // Analyze typography
    if (tokens.tokens?.typography) {
      for (const [name, typo] of Object.entries(tokens.tokens.typography)) {
        semanticMap[`typography:${name}`] = await this.analyzeTypographySemantics(name, typo);
      }
    }

    // Analyze spacing
    if (tokens.tokens?.spacing) {
      for (const [name, spacing] of Object.entries(tokens.tokens.spacing)) {
        semanticMap[`spacing:${name}`] = await this.analyzeSpacingSemantics(name, spacing);
      }
    }

    // Analyze components
    if (tokens.tokens?.components) {
      for (const [name, component] of Object.entries(tokens.tokens.components)) {
        semanticMap[`component:${name}`] = await this.analyzeComponentSemantics(name, component);
      }
    }

    return semanticMap;
  }

  async analyzeColorSemantics(name, color) {
    const semantics = {
      name,
      type: 'color',
      inferredRole: null,
      confidence: 0,
      reasoning: [],
      contexts: [],
      relationships: [],
      accessibility: {},
      psychology: {}
    };

    // Name-based analysis
    const nameAnalysis = this.analyzeNameSemantics(name, this.patterns.colorSemantics);
    if (nameAnalysis.match) {
      semantics.inferredRole = nameAnalysis.role;
      semantics.confidence = nameAnalysis.confidence;
      semantics.contexts = nameAnalysis.contexts;
      semantics.reasoning.push(`Name "${name}" suggests ${nameAnalysis.role} role`);
    }

    // Color value analysis
    const colorAnalysis = this.analyzeColorValue(color);
    semantics.psychology = colorAnalysis.psychology;
    semantics.accessibility = colorAnalysis.accessibility;

    if (colorAnalysis.suggestedRole) {
      if (semantics.inferredRole === colorAnalysis.suggestedRole) {
        semantics.confidence += 0.2;
        semantics.reasoning.push('Color value confirms name-based inference');
      } else if (!semantics.inferredRole) {
        semantics.inferredRole = colorAnalysis.suggestedRole;
        semantics.confidence = 0.6;
        semantics.reasoning.push(`Color value suggests ${colorAnalysis.suggestedRole} role`);
      } else {
        semantics.reasoning.push('Color value conflicts with name-based inference');
        semantics.confidence -= 0.1;
      }
    }

    // Context enhancement
    if (color.semantic?.usage) {
      semantics.contexts = [...new Set([...semantics.contexts, ...color.semantic.usage])];
      semantics.confidence += 0.1;
      semantics.reasoning.push('Usage context provides additional validation');
    }

    return semantics;
  }

  async analyzeTypographySemantics(name, typography) {
    const semantics = {
      name,
      type: 'typography',
      inferredRole: null,
      confidence: 0,
      reasoning: [],
      hierarchy: {},
      readability: {},
      contexts: []
    };

    // Name-based analysis
    const nameAnalysis = this.analyzeNameSemantics(name, this.patterns.typographySemantics);
    if (nameAnalysis.match) {
      semantics.inferredRole = nameAnalysis.role;
      semantics.confidence = nameAnalysis.confidence;
      semantics.contexts = nameAnalysis.contexts;
      semantics.reasoning.push(`Name "${name}" suggests ${nameAnalysis.role} role`);
    }

    // Typography characteristics analysis
    const charAnalysis = this.analyzeTypographyCharacteristics(typography);
    if (charAnalysis.suggestedRole) {
      if (semantics.inferredRole === charAnalysis.suggestedRole) {
        semantics.confidence += 0.2;
        semantics.reasoning.push('Typography characteristics confirm name-based inference');
      } else if (!semantics.inferredRole) {
        semantics.inferredRole = charAnalysis.suggestedRole;
        semantics.confidence = 0.7;
        semantics.reasoning.push(`Typography characteristics suggest ${charAnalysis.suggestedRole} role`);
      }
    }

    semantics.hierarchy = charAnalysis.hierarchy;
    semantics.readability = charAnalysis.readability;

    return semantics;
  }

  async analyzeSpacingSemantics(name, spacing) {
    const semantics = {
      name,
      type: 'spacing',
      inferredRole: null,
      confidence: 0,
      reasoning: [],
      scale: {},
      usage: []
    };

    // Name-based analysis
    const nameAnalysis = this.analyzeNameSemantics(name, this.patterns.spacingSemantics);
    if (nameAnalysis.match) {
      semantics.inferredRole = nameAnalysis.role;
      semantics.confidence = nameAnalysis.confidence;
      semantics.usage = nameAnalysis.usage;
      semantics.reasoning.push(`Name "${name}" suggests ${nameAnalysis.role} scale`);
    }

    // Value-based analysis
    const value = spacing.px || spacing.value;
    if (typeof value === 'number') {
      const scaleAnalysis = this.analyzeSpacingScale(value);
      if (scaleAnalysis.category) {
        if (semantics.inferredRole === scaleAnalysis.category) {
          semantics.confidence += 0.2;
        } else if (!semantics.inferredRole) {
          semantics.inferredRole = scaleAnalysis.category;
          semantics.confidence = 0.6;
        }
        semantics.scale = scaleAnalysis;
        semantics.reasoning.push(`Value ${value}px fits ${scaleAnalysis.category} scale`);
      }
    }

    return semantics;
  }

  async analyzeComponentSemantics(name, component) {
    const semantics = {
      name,
      type: 'component',
      inferredType: null,
      confidence: 0,
      reasoning: [],
      complexity: 'unknown',
      patterns: [],
      atomicLevel: null
    };

    // Name-based analysis
    const namePattern = this.analyzeComponentName(name);
    if (namePattern.atomicLevel) {
      semantics.atomicLevel = namePattern.atomicLevel;
      semantics.confidence = namePattern.confidence;
      semantics.reasoning.push(`Name "${name}" suggests ${namePattern.atomicLevel} level component`);
    }

    // Structure analysis
    const structureAnalysis = this.analyzeComponentStructure(component);
    semantics.complexity = structureAnalysis.complexity;
    semantics.patterns = structureAnalysis.patterns;

    if (structureAnalysis.suggestedLevel) {
      if (semantics.atomicLevel === structureAnalysis.suggestedLevel) {
        semantics.confidence += 0.2;
      } else if (!semantics.atomicLevel) {
        semantics.atomicLevel = structureAnalysis.suggestedLevel;
        semantics.confidence = 0.7;
      }
      semantics.reasoning.push(`Structure suggests ${structureAnalysis.suggestedLevel} level`);
    }

    return semantics;
  }

  analyzeNameSemantics(name, patterns) {
    const lowercaseName = name.toLowerCase();
    let bestMatch = null;
    let highestConfidence = 0;

    for (const [role, pattern] of Object.entries(patterns)) {
      const keywordMatches = pattern.keywords.filter(keyword =>
        lowercaseName.includes(keyword)
      );

      if (keywordMatches.length > 0) {
        const confidence = (keywordMatches.length / pattern.keywords.length) * pattern.confidence;
        if (confidence > highestConfidence) {
          highestConfidence = confidence;
          bestMatch = {
            role,
            confidence,
            contexts: pattern.contexts || [],
            usage: pattern.usage || [],
            keywords: keywordMatches
          };
        }
      }
    }

    return bestMatch ? { match: true, ...bestMatch } : { match: false };
  }

  analyzeColorValue(color) {
    const analysis = {
      psychology: {},
      accessibility: {},
      suggestedRole: null
    };

    if (color.hsl) {
      const { h, s, l } = color.hsl;

      // Psychological analysis based on hue
      if (h >= 0 && h < 30 || h >= 330 && h <= 360) {
        analysis.psychology = { mood: 'energetic', associations: ['passion', 'urgency', 'power'] };
        if (s > 50 && l < 60) analysis.suggestedRole = 'error';
      } else if (h >= 30 && h < 60) {
        analysis.psychology = { mood: 'optimistic', associations: ['warmth', 'caution', 'creativity'] };
        if (s > 40 && l > 40 && l < 80) analysis.suggestedRole = 'warning';
      } else if (h >= 60 && h < 150) {
        analysis.psychology = { mood: 'peaceful', associations: ['nature', 'growth', 'success'] };
        if (s > 30 && l > 25 && l < 75) analysis.suggestedRole = 'success';
      } else if (h >= 180 && h < 270) {
        analysis.psychology = { mood: 'trustworthy', associations: ['stability', 'information', 'technology'] };
        if (s > 40 && l > 30 && l < 70) analysis.suggestedRole = 'info';
      } else if (h >= 270 && h < 330) {
        analysis.psychology = { mood: 'creative', associations: ['luxury', 'mystery', 'imagination'] };
      }

      // Accessibility analysis
      analysis.accessibility = {
        lightness: l,
        saturation: s,
        suitableForText: l < 20 || l > 80,
        suitableForBackground: l > 90 || l < 10
      };
    }

    return analysis;
  }

  analyzeTypographyCharacteristics(typography) {
    const analysis = {
      hierarchy: {},
      readability: {},
      suggestedRole: null
    };

    const fontSize = typography.fontSize?.px || typography.value?.fontSize?.px;
    const fontWeight = typography.fontWeight || typography.value?.fontWeight;

    if (fontSize) {
      analysis.hierarchy.size = fontSize;

      if (fontSize >= 32) {
        analysis.suggestedRole = 'display';
        analysis.hierarchy.level = 'display';
      } else if (fontSize >= 24) {
        analysis.suggestedRole = 'heading';
        analysis.hierarchy.level = 'h1-h2';
      } else if (fontSize >= 18) {
        analysis.suggestedRole = 'heading';
        analysis.hierarchy.level = 'h3-h4';
      } else if (fontSize >= 14) {
        analysis.suggestedRole = 'body';
        analysis.hierarchy.level = 'body';
      } else {
        analysis.suggestedRole = 'caption';
        analysis.hierarchy.level = 'small';
      }
    }

    if (fontWeight) {
      analysis.hierarchy.weight = fontWeight;
      if (fontWeight >= 700) {
        analysis.hierarchy.emphasis = 'strong';
      } else if (fontWeight >= 500) {
        analysis.hierarchy.emphasis = 'medium';
      } else {
        analysis.hierarchy.emphasis = 'normal';
      }
    }

    // Readability analysis
    const lineHeight = typography.lineHeight?.unitless || typography.value?.lineHeight?.unitless;
    if (lineHeight) {
      analysis.readability.lineHeight = lineHeight;
      analysis.readability.lineHeightRating =
        lineHeight >= 1.4 && lineHeight <= 1.6 ? 'optimal' :
        lineHeight >= 1.2 && lineHeight < 1.4 ? 'tight' :
        lineHeight > 1.6 && lineHeight <= 2.0 ? 'loose' : 'extreme';
    }

    return analysis;
  }

  analyzeSpacingScale(value) {
    for (const [category, pattern] of Object.entries(this.patterns.spacingSemantics)) {
      if (value >= pattern.range[0] && value <= pattern.range[1]) {
        return {
          category,
          scale: pattern.range,
          usage: pattern.usage,
          fit: 'exact'
        };
      }
    }

    // Find closest match
    let closest = null;
    let minDistance = Infinity;

    for (const [category, pattern] of Object.entries(this.patterns.spacingSemantics)) {
      const distance = Math.min(
        Math.abs(value - pattern.range[0]),
        Math.abs(value - pattern.range[1])
      );

      if (distance < minDistance) {
        minDistance = distance;
        closest = {
          category,
          scale: pattern.range,
          usage: pattern.usage,
          fit: 'approximate',
          distance
        };
      }
    }

    return closest;
  }

  analyzeComponentName(name) {
    const lowercaseName = name.toLowerCase();

    for (const [level, patterns] of Object.entries(this.patterns.componentSemantics)) {
      const matches = patterns.patterns.filter(pattern =>
        lowercaseName.includes(pattern)
      );

      if (matches.length > 0) {
        return {
          atomicLevel: level.slice(0, -1), // Remove 's' from 'atoms', 'molecules', etc.
          confidence: patterns.confidence,
          patterns: matches
        };
      }
    }

    return { atomicLevel: null, confidence: 0 };
  }

  analyzeComponentStructure(component) {
    const analysis = {
      complexity: 'low',
      patterns: [],
      suggestedLevel: null
    };

    const variantCount = component.variants?.length || 0;
    const propertyCount = Object.keys(component.properties || {}).length;

    // Complexity analysis
    if (variantCount <= 2 && propertyCount <= 3) {
      analysis.complexity = 'low';
      analysis.suggestedLevel = 'atom';
    } else if (variantCount <= 5 && propertyCount <= 8) {
      analysis.complexity = 'medium';
      analysis.suggestedLevel = 'molecule';
    } else {
      analysis.complexity = 'high';
      analysis.suggestedLevel = 'organism';
    }

    // Pattern detection
    if (component.slots?.length > 0) {
      analysis.patterns.push('composition');
    }

    if (component.dependencies?.length > 0) {
      analysis.patterns.push('dependencies');
    }

    if (component.variants?.some(v => v.name.includes('state'))) {
      analysis.patterns.push('stateful');
    }

    return analysis;
  }

  async analyzeRelationships(tokens, semanticMapping) {
    const relationships = {
      colorHarmonies: [],
      typographyPairings: [],
      spacingProgressions: [],
      componentHierarchies: []
    };

    // Color relationship analysis
    const colors = Object.entries(semanticMapping)
      .filter(([key]) => key.startsWith('color:'))
      .map(([key, value]) => ({ key, ...value }));

    relationships.colorHarmonies = this.analyzeColorHarmonies(colors, tokens.tokens?.colors);

    // Typography relationship analysis
    const typography = Object.entries(semanticMapping)
      .filter(([key]) => key.startsWith('typography:'))
      .map(([key, value]) => ({ key, ...value }));

    relationships.typographyPairings = this.analyzeTypographyPairings(typography);

    // Spacing progression analysis
    const spacing = Object.entries(semanticMapping)
      .filter(([key]) => key.startsWith('spacing:'))
      .map(([key, value]) => ({ key, ...value }));

    relationships.spacingProgressions = this.analyzeSpacingProgressions(spacing, tokens.tokens?.spacing);

    return relationships;
  }

  analyzeColorHarmonies(colors, colorTokens) {
    const harmonies = [];

    // Group colors by hue similarity
    const hueGroups = new Map();

    colors.forEach(color => {
      const colorData = colorTokens[color.name];
      if (colorData?.hsl?.h !== undefined) {
        const hueGroup = Math.round(colorData.hsl.h / 30) * 30; // Group by 30-degree segments
        if (!hueGroups.has(hueGroup)) {
          hueGroups.set(hueGroup, []);
        }
        hueGroups.get(hueGroup).push({ ...color, colorData });
      }
    });

    // Analyze harmony within groups
    hueGroups.forEach((groupColors, hue) => {
      if (groupColors.length >= 2) {
        const lightnessValues = groupColors.map(c => c.colorData.hsl.l).sort((a, b) => a - b);
        const isProgressive = this.isProgressiveSequence(lightnessValues);

        harmonies.push({
          type: 'monochromatic',
          hue,
          colors: groupColors.map(c => c.name),
          progressive: isProgressive,
          confidence: isProgressive ? 0.9 : 0.7
        });
      }
    });

    // Check for complementary colors
    const hues = Array.from(hueGroups.keys());
    for (let i = 0; i < hues.length; i++) {
      for (let j = i + 1; j < hues.length; j++) {
        const hueDiff = Math.abs(hues[i] - hues[j]);
        if (hueDiff >= 150 && hueDiff <= 210) { // Approximately complementary
          harmonies.push({
            type: 'complementary',
            hues: [hues[i], hues[j]],
            colors: [
              ...hueGroups.get(hues[i]).map(c => c.name),
              ...hueGroups.get(hues[j]).map(c => c.name)
            ],
            confidence: 0.85
          });
        }
      }
    }

    return harmonies;
  }

  analyzeTypographyPairings(typography) {
    const pairings = [];

    // Group by font family
    const fontFamilies = new Map();
    typography.forEach(typo => {
      const family = typo.name.split('-')[0] || 'default';
      if (!fontFamilies.has(family)) {
        fontFamilies.set(family, []);
      }
      fontFamilies.get(family).push(typo);
    });

    // Analyze hierarchy within families
    fontFamilies.forEach((familyTypos, family) => {
      if (familyTypos.length >= 2) {
        const hierarchy = familyTypos
          .sort((a, b) => (b.hierarchy?.size || 0) - (a.hierarchy?.size || 0))
          .map(t => ({
            name: t.name,
            role: t.inferredRole,
            size: t.hierarchy?.size,
            weight: t.hierarchy?.weight
          }));

        pairings.push({
          type: 'hierarchy',
          family,
          typography: hierarchy,
          confidence: 0.8
        });
      }
    });

    return pairings;
  }

  analyzeSpacingProgressions(spacing, spacingTokens) {
    const progressions = [];

    // Extract spacing values
    const spacingValues = spacing
      .map(s => ({
        name: s.name,
        value: spacingTokens[s.name]?.px || spacingTokens[s.name]?.value || 0,
        category: s.inferredRole
      }))
      .filter(s => s.value > 0)
      .sort((a, b) => a.value - b.value);

    if (spacingValues.length >= 3) {
      const values = spacingValues.map(s => s.value);
      const isGeometric = this.isGeometricProgression(values);
      const isArithmetic = this.isArithmeticProgression(values);

      if (isGeometric || isArithmetic) {
        progressions.push({
          type: isGeometric ? 'geometric' : 'arithmetic',
          values: spacingValues,
          ratio: isGeometric ? this.calculateGeometricRatio(values) : null,
          step: isArithmetic ? this.calculateArithmeticStep(values) : null,
          confidence: isGeometric ? 0.9 : 0.8
        });
      }
    }

    return progressions;
  }

  async analyzeContext(tokens, semanticMapping) {
    const insights = [];

    // Brand context analysis
    const brandInsights = this.analyzeBrandContext(semanticMapping);
    insights.push(...brandInsights);

    // Design system maturity
    const maturityInsights = this.analyzeDesignSystemMaturity(tokens, semanticMapping);
    insights.push(...maturityInsights);

    // Accessibility context
    const a11yInsights = this.analyzeAccessibilityContext(tokens, semanticMapping);
    insights.push(...a11yInsights);

    return { insights };
  }

  analyzeBrandContext(semanticMapping) {
    const insights = [];

    const primaryColors = Object.values(semanticMapping)
      .filter(s => s.type === 'color' && s.inferredRole === 'primary');

    if (primaryColors.length === 0) {
      insights.push({
        type: 'brand',
        level: 'warning',
        message: 'No primary brand colors detected',
        recommendation: 'Establish clear primary brand colors for consistent identity',
        confidence: 0.9
      });
    } else if (primaryColors.length > 3) {
      insights.push({
        type: 'brand',
        level: 'info',
        message: 'Multiple primary colors detected',
        recommendation: 'Consider consolidating to 1-2 primary brand colors',
        confidence: 0.8
      });
    }

    return insights;
  }

  analyzeDesignSystemMaturity(tokens, semanticMapping) {
    const insights = [];

    const tokenCounts = {
      colors: Object.keys(tokens.tokens?.colors || {}).length,
      typography: Object.keys(tokens.tokens?.typography || {}).length,
      spacing: Object.keys(tokens.tokens?.spacing || {}).length,
      components: Object.keys(tokens.tokens?.components || {}).length
    };

    const semanticRoles = Object.values(semanticMapping)
      .filter(s => s.inferredRole && s.confidence > 0.7)
      .length;

    const semanticCoverage = semanticRoles / Object.keys(semanticMapping).length;

    let maturityLevel = 'emerging';
    if (semanticCoverage > 0.8 && tokenCounts.colors >= 8 && tokenCounts.typography >= 6) {
      maturityLevel = 'mature';
    } else if (semanticCoverage > 0.6 && tokenCounts.colors >= 5 && tokenCounts.typography >= 4) {
      maturityLevel = 'developing';
    }

    insights.push({
      type: 'maturity',
      level: 'info',
      message: `Design system maturity: ${maturityLevel}`,
      data: { maturityLevel, semanticCoverage, tokenCounts },
      confidence: 0.85
    });

    return insights;
  }

  analyzeAccessibilityContext(tokens, semanticMapping) {
    const insights = [];

    const colorTokens = Object.values(semanticMapping)
      .filter(s => s.type === 'color' && s.accessibility);

    const accessibleColors = colorTokens.filter(c =>
      c.accessibility?.suitableForText || c.accessibility?.suitableForBackground
    );

    const accessibilityScore = accessibleColors.length / colorTokens.length;

    if (accessibilityScore < 0.5) {
      insights.push({
        type: 'accessibility',
        level: 'warning',
        message: 'Low accessibility optimization in color system',
        recommendation: 'Review color contrast ratios and ensure sufficient dark/light variants',
        confidence: 0.9
      });
    }

    return insights;
  }

  async recognizePatterns(tokens, semanticMapping) {
    const insights = [];

    // Color palette patterns
    const colorPatterns = this.recognizeColorPatterns(semanticMapping);
    insights.push(...colorPatterns);

    // Typography scale patterns
    const typographyPatterns = this.recognizeTypographyPatterns(semanticMapping);
    insights.push(...typographyPatterns);

    // Spacing scale patterns
    const spacingPatterns = this.recognizeSpacingPatterns(semanticMapping);
    insights.push(...spacingPatterns);

    return { insights };
  }

  recognizeColorPatterns(semanticMapping) {
    const patterns = [];

    const colors = Object.values(semanticMapping).filter(s => s.type === 'color');

    // Material Design pattern detection
    const materialColors = colors.filter(c =>
      c.reasoning.some(r => r.includes('50') || r.includes('100') || r.includes('500'))
    );

    if (materialColors.length >= 5) {
      patterns.push({
        type: 'pattern',
        pattern: 'Material Design Color System',
        confidence: 0.8,
        evidence: `${materialColors.length} colors follow Material Design naming`
      });
    }

    // Tailwind pattern detection
    const tailwindColors = colors.filter(c =>
      c.name.match(/-\d{2,3}$/) // Ends with dash and number like -100, -500
    );

    if (tailwindColors.length >= 5) {
      patterns.push({
        type: 'pattern',
        pattern: 'Tailwind CSS Color System',
        confidence: 0.85,
        evidence: `${tailwindColors.length} colors follow Tailwind naming convention`
      });
    }

    return patterns;
  }

  recognizeTypographyPatterns(semanticMapping) {
    const patterns = [];

    const typography = Object.values(semanticMapping).filter(s => s.type === 'typography');

    // Modular scale detection
    const fontSizes = typography
      .map(t => t.hierarchy?.size)
      .filter(size => typeof size === 'number')
      .sort((a, b) => a - b);

    if (fontSizes.length >= 4) {
      const isModularScale = this.detectModularScale(fontSizes);
      if (isModularScale.detected) {
        patterns.push({
          type: 'pattern',
          pattern: 'Modular Typography Scale',
          confidence: 0.9,
          evidence: `Scale ratio: ${isModularScale.ratio.toFixed(2)}`
        });
      }
    }

    return patterns;
  }

  recognizeSpacingPatterns(semanticMapping) {
    const patterns = [];

    const spacing = Object.values(semanticMapping).filter(s => s.type === 'spacing');

    // 8pt grid detection
    const spacingValues = spacing
      .map(s => s.scale?.scale?.[0] || 0)
      .filter(v => v > 0);

    const eightPointGrid = spacingValues.filter(v => v % 8 === 0);
    if (eightPointGrid.length / spacingValues.length > 0.8) {
      patterns.push({
        type: 'pattern',
        pattern: '8-Point Grid System',
        confidence: 0.9,
        evidence: `${eightPointGrid.length}/${spacingValues.length} values align to 8pt grid`
      });
    }

    // 4pt grid detection
    const fourPointGrid = spacingValues.filter(v => v % 4 === 0);
    if (fourPointGrid.length / spacingValues.length > 0.8 && eightPointGrid.length / spacingValues.length <= 0.8) {
      patterns.push({
        type: 'pattern',
        pattern: '4-Point Grid System',
        confidence: 0.85,
        evidence: `${fourPointGrid.length}/${spacingValues.length} values align to 4pt grid`
      });
    }

    return patterns;
  }

  detectPatterns(tokens) {
    const patterns = [];

    try {
      // Color patterns
      if (tokens.tokens?.colors) {
        const colors = Object.entries(tokens.tokens.colors);

        // Material Design pattern
        const materialColors = colors.filter(([name]) =>
          /-(50|100|200|300|400|500|600|700|800|900)$/.test(name)
        );
        if (materialColors.length >= 5) {
          patterns.push({
            type: 'color-system',
            framework: 'Material Design',
            confidence: 0.9,
            matches: materialColors.length
          });
        }

        // Tailwind pattern
        const tailwindColors = colors.filter(([name]) =>
          /-(50|100|200|300|400|500|600|700|800|900)$/.test(name)
        );
        if (tailwindColors.length >= 3) {
          patterns.push({
            type: 'color-system',
            framework: 'Tailwind CSS',
            confidence: 0.8,
            matches: tailwindColors.length
          });
        }
      }

      // Typography patterns
      if (tokens.tokens?.typography) {
        const typography = Object.entries(tokens.tokens.typography);

        // Bootstrap typography pattern
        const bootstrapTypo = typography.filter(([name]) =>
          /^(h[1-6]|display-[1-4]|lead|text-(xs|sm|base|lg|xl))/.test(name)
        );
        if (bootstrapTypo.length >= 3) {
          patterns.push({
            type: 'typography-system',
            framework: 'Bootstrap',
            confidence: 0.85,
            matches: bootstrapTypo.length
          });
        }
      }

      // Spacing patterns
      if (tokens.tokens?.spacing) {
        const spacing = Object.values(tokens.tokens.spacing);
        const spacingValues = spacing.map(s => s.px || s.value || 0);

        // 8pt grid pattern
        const eightPtGrid = spacingValues.filter(v => v % 8 === 0);
        if (eightPtGrid.length / spacingValues.length > 0.8) {
          patterns.push({
            type: 'spacing-system',
            framework: '8pt Grid',
            confidence: 0.9,
            matches: eightPtGrid.length
          });
        }
      }

    } catch (error) {
      console.warn('Pattern detection error:', error.message);
    }

    return patterns;
  }

  async generateSmartRecommendations(tokens, semanticMapping, relationships) {
    const recommendations = [];

    // Semantic role recommendations
    const semanticRecs = this.generateSemanticRecommendations(semanticMapping);
    recommendations.push(...semanticRecs);

    // Consistency recommendations
    const consistencyRecs = this.generateConsistencyRecommendations(relationships);
    recommendations.push(...consistencyRecs);

    // Accessibility recommendations
    const accessibilityRecs = this.generateAccessibilityRecommendations(semanticMapping);
    recommendations.push(...accessibilityRecs);

    // Scale optimization recommendations
    const scaleRecs = this.generateScaleRecommendations(relationships);
    recommendations.push(...scaleRecs);

    return recommendations.sort((a, b) => b.priority - a.priority);
  }

  generateSemanticRecommendations(semanticMapping) {
    const recommendations = [];

    const lowConfidenceTokens = Object.values(semanticMapping)
      .filter(s => s.confidence < 0.6);

    if (lowConfidenceTokens.length > 0) {
      recommendations.push({
        type: 'semantic',
        priority: 8,
        title: 'Improve token naming clarity',
        description: `${lowConfidenceTokens.length} tokens have unclear semantic meaning`,
        action: 'Rename tokens to better reflect their purpose and context',
        impact: 'high',
        effort: 'medium'
      });
    }

    const missingRoles = this.findMissingSemanticRoles(semanticMapping);
    if (missingRoles.length > 0) {
      recommendations.push({
        type: 'semantic',
        priority: 7,
        title: 'Add missing semantic roles',
        description: `Missing key roles: ${missingRoles.join(', ')}`,
        action: 'Create tokens for missing semantic roles',
        impact: 'high',
        effort: 'high'
      });
    }

    return recommendations;
  }

  generateConsistencyRecommendations(relationships) {
    const recommendations = [];

    if (relationships.colorHarmonies.length === 0) {
      recommendations.push({
        type: 'consistency',
        priority: 6,
        title: 'Establish color harmony',
        description: 'No clear color harmonies detected',
        action: 'Create systematic color relationships using color theory',
        impact: 'medium',
        effort: 'high'
      });
    }

    const brokenProgressions = relationships.spacingProgressions
      .filter(p => p.confidence < 0.7);

    if (brokenProgressions.length > 0) {
      recommendations.push({
        type: 'consistency',
        priority: 5,
        title: 'Fix spacing scale inconsistencies',
        description: 'Spacing values do not follow a consistent progression',
        action: 'Adopt a geometric or arithmetic spacing scale',
        impact: 'medium',
        effort: 'medium'
      });
    }

    return recommendations;
  }

  generateAccessibilityRecommendations(semanticMapping) {
    const recommendations = [];

    const colorTokens = Object.values(semanticMapping)
      .filter(s => s.type === 'color');

    const inaccessibleColors = colorTokens.filter(c =>
      c.accessibility && !c.accessibility.suitableForText && !c.accessibility.suitableForBackground
    );

    if (inaccessibleColors.length > 0) {
      recommendations.push({
        type: 'accessibility',
        priority: 9,
        title: 'Improve color accessibility',
        description: `${inaccessibleColors.length} colors may have accessibility issues`,
        action: 'Ensure sufficient contrast ratios and provide dark/light variants',
        impact: 'high',
        effort: 'medium'
      });
    }

    return recommendations;
  }

  generateScaleRecommendations(relationships) {
    const recommendations = [];

    const typographyPairings = relationships.typographyPairings;
    if (typographyPairings.length === 0) {
      recommendations.push({
        type: 'scale',
        priority: 4,
        title: 'Establish typography hierarchy',
        description: 'No clear typography hierarchy detected',
        action: 'Create systematic font size and weight progressions',
        impact: 'medium',
        effort: 'medium'
      });
    }

    return recommendations;
  }

  // Helper methods
  countTokens(tokens) {
    return Object.values(tokens.tokens || {}).reduce((count, category) => {
      return count + Object.keys(category || {}).length;
    }, 0);
  }

  calculateConfidenceScores(analysis) {
    const mappingValues = Object.values(analysis.semanticMapping);
    const avgConfidence = mappingValues.reduce((sum, s) => sum + s.confidence, 0) / mappingValues.length;

    return {
      overall: avgConfidence,
      semantic: avgConfidence,
      relationships: analysis.relationships.colorHarmonies.length > 0 ? 0.8 : 0.4,
      patterns: analysis.insights.filter(i => i.type === 'pattern').length * 0.2
    };
  }

  isProgressiveSequence(values) {
    if (values.length < 3) return false;

    const diffs = [];
    for (let i = 1; i < values.length; i++) {
      diffs.push(values[i] - values[i - 1]);
    }

    const avgDiff = diffs.reduce((sum, diff) => sum + diff, 0) / diffs.length;
    const variance = diffs.reduce((sum, diff) => sum + Math.pow(diff - avgDiff, 2), 0) / diffs.length;

    return variance < avgDiff * 0.5; // Low variance indicates progression
  }

  isGeometricProgression(values) {
    if (values.length < 3) return false;

    const ratios = [];
    for (let i = 1; i < values.length; i++) {
      ratios.push(values[i] / values[i - 1]);
    }

    const avgRatio = ratios.reduce((sum, ratio) => sum + ratio, 0) / ratios.length;
    const variance = ratios.reduce((sum, ratio) => sum + Math.pow(ratio - avgRatio, 2), 0) / ratios.length;

    return variance < 0.3;
  }

  isArithmeticProgression(values) {
    return this.isProgressiveSequence(values);
  }

  calculateGeometricRatio(values) {
    const ratios = [];
    for (let i = 1; i < values.length; i++) {
      ratios.push(values[i] / values[i - 1]);
    }
    return ratios.reduce((sum, ratio) => sum + ratio, 0) / ratios.length;
  }

  calculateArithmeticStep(values) {
    const diffs = [];
    for (let i = 1; i < values.length; i++) {
      diffs.push(values[i] - values[i - 1]);
    }
    return diffs.reduce((sum, diff) => sum + diff, 0) / diffs.length;
  }

  detectModularScale(fontSizes) {
    const ratios = [];
    for (let i = 1; i < fontSizes.length; i++) {
      ratios.push(fontSizes[i] / fontSizes[i - 1]);
    }

    const avgRatio = ratios.reduce((sum, ratio) => sum + ratio, 0) / ratios.length;
    const variance = ratios.reduce((sum, ratio) => sum + Math.pow(ratio - avgRatio, 2), 0) / ratios.length;

    const commonRatios = [1.125, 1.2, 1.25, 1.333, 1.414, 1.5, 1.618]; // Common modular scale ratios
    const isCommonRatio = commonRatios.some(ratio => Math.abs(avgRatio - ratio) < 0.1);

    return {
      detected: variance < 0.1 && isCommonRatio,
      ratio: avgRatio,
      variance
    };
  }

  findMissingSemanticRoles(semanticMapping) {
    const presentRoles = new Set(
      Object.values(semanticMapping)
        .filter(s => s.inferredRole && s.confidence > 0.6)
        .map(s => s.inferredRole)
    );

    const essentialColorRoles = ['primary', 'secondary', 'success', 'error', 'warning'];
    const essentialTypographyRoles = ['heading', 'body', 'caption'];

    const missingRoles = [];

    essentialColorRoles.forEach(role => {
      if (!presentRoles.has(role)) {
        missingRoles.push(`color:${role}`);
      }
    });

    essentialTypographyRoles.forEach(role => {
      if (!presentRoles.has(role)) {
        missingRoles.push(`typography:${role}`);
      }
    });

    return missingRoles;
  }

  // Business rule validators (from validation system integration)
  async validateBrandHierarchy(tokens) {
    // Implementation would validate brand color hierarchy
    return { errors: [], warnings: [] };
  }

  async validateSemanticConsistency(tokens) {
    // Implementation would validate semantic consistency
    return { errors: [], warnings: [] };
  }

  async validateColorPsychology(tokens) {
    // Implementation would validate color psychology alignment
    return { errors: [], warnings: [] };
  }

  async validateTypographyHierarchy(tokens) {
    // Implementation would validate typography hierarchy
    return { errors: [], warnings: [] };
  }

  async validateReadability(tokens) {
    // Implementation would validate readability
    return { errors: [], warnings: [] };
  }

  async validateAtomicDesign(tokens) {
    // Implementation would validate atomic design principles
    return { errors: [], warnings: [] };
  }

  async validateSemanticStructure(tokens) {
    // Implementation would validate semantic structure
    return { errors: [], warnings: [] };
  }

  /**
   * Check if two colors are related
   */
  areColorsRelated(color1, color2, threshold = 30) {
    // Convert both colors to HSL for comparison
    const hsl1 = this.toHSL(color1);
    const hsl2 = this.toHSL(color2);

    if (!hsl1 || !hsl2) return false;

    // Check hue similarity (within threshold degrees)
    const hueDiff = Math.abs(hsl1.h - hsl2.h);
    const circularDiff = Math.min(hueDiff, 360 - hueDiff);

    // Check if colors are variations (similar hue, different lightness/saturation)
    if (circularDiff <= threshold) {
      return true;
    }

    // Check if colors are complementary (opposite on color wheel)
    if (Math.abs(circularDiff - 180) <= threshold) {
      return true;
    }

    // Check if colors are part of a triad (120 degrees apart)
    if (Math.abs(circularDiff - 120) <= threshold || Math.abs(circularDiff - 240) <= threshold) {
      return true;
    }

    return false;
  }

  /**
   * Convert color to HSL format
   */
  toHSL(color) {
    if (!color) return null;

    // If already HSL
    if (color.hsl) return color.hsl;
    if (color.h !== undefined && color.s !== undefined && color.l !== undefined) return color;

    // Convert from hex
    if (typeof color === 'string' && color.startsWith('#')) {
      return this.hexToHSL(color);
    }

    // Convert from RGB
    if (color.rgb || (color.r !== undefined && color.g !== undefined && color.b !== undefined)) {
      const rgb = color.rgb || color;
      return this.rgbToHSL(rgb.r, rgb.g, rgb.b);
    }

    return null;
  }

  /**
   * Convert hex to HSL
   */
  hexToHSL(hex) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    if (!result) return null;

    const r = parseInt(result[1], 16);
    const g = parseInt(result[2], 16);
    const b = parseInt(result[3], 16);

    return this.rgbToHSL(r, g, b);
  }

  /**
   * Convert RGB to HSL
   */
  rgbToHSL(r, g, b) {
    r /= 255;
    g /= 255;
    b /= 255;

    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    let h, s, l = (max + min) / 2;

    if (max === min) {
      h = s = 0; // achromatic
    } else {
      const d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);

      switch (max) {
        case r:
          h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
          break;
        case g:
          h = ((b - r) / d + 2) / 6;
          break;
        case b:
          h = ((r - g) / d + 4) / 6;
          break;
      }
    }

    return {
      h: Math.round(h * 360),
      s: Math.round(s * 100),
      l: Math.round(l * 100)
    };
  }

  /**
   * Detect color relationship between two colors
   */
  detectColorRelationship(color1, color2) {
    const hsl1 = this.toHSL(color1);
    const hsl2 = this.toHSL(color2);

    if (!hsl1 || !hsl2) return null;

    const hueDiff = Math.abs(hsl1.h - hsl2.h);
    const circularDiff = Math.min(hueDiff, 360 - hueDiff);

    // Monochromatic - same hue, different lightness/saturation
    if (circularDiff <= 10) {
      return 'monochromatic';
    }

    // Analogous - adjacent on color wheel (within 30-60 degrees)
    if (circularDiff > 10 && circularDiff <= 60) {
      return 'analogous';
    }

    // Triadic - 120 degrees apart
    if (Math.abs(circularDiff - 120) <= 15) {
      return 'triadic';
    }

    // Tetradic - 90 degrees apart
    if (Math.abs(circularDiff - 90) <= 15 || Math.abs(circularDiff - 270) <= 15) {
      return 'tetradic';
    }

    // Complementary - opposite on color wheel
    if (Math.abs(circularDiff - 180) <= 15) {
      return 'complementary';
    }

    return null;
  }
}

module.exports = SemanticAnalyzer;