/**
 * Design Pattern Analyzer
 * Recognizes and extracts design patterns from design systems
 * Sprint 5: Pattern Recognition Engine
 */

const EventEmitter = require('events');

class DesignPatternAnalyzer extends EventEmitter {
  constructor() {
    super();
    this.name = 'DesignPatternAnalyzer';
    this.version = '1.0.0';

    // Pattern detection configuration
    this.config = {
      colorThreshold: 0.1,
      typographyThreshold: 0.05,
      spacingThreshold: 2,
      componentSimilarityThreshold: 0.85,
      maxPatternDepth: 5
    };

    // Detected patterns registry
    this.patterns = {
      colors: new Map(),
      typography: new Map(),
      spacing: new Map(),
      components: new Map(),
      layouts: new Map(),
      animations: new Map()
    };

    // Common design system patterns
    this.commonPatterns = {
      colorSchemes: ['monochromatic', 'analogous', 'complementary', 'triadic'],
      typographyScales: ['minor-second', 'major-second', 'minor-third', 'major-third', 'perfect-fourth'],
      spacingScales: ['linear', 'exponential', 'fibonacci', 'custom'],
      layoutPatterns: ['grid', 'flexbox', 'stack', 'masonry']
    };
  }

  /**
   * Analyze design file for patterns
   */
  async analyzeDesignFile(designFile, options = {}) {
    const config = { ...this.config, ...options };

    try {
      const analysis = {
        id: this.generateAnalysisId(),
        timestamp: new Date().toISOString(),
        file: designFile.name || 'untitled',
        patterns: {
          colors: await this.extractColorPatterns(designFile, config),
          typography: await this.extractTypographyPatterns(designFile, config),
          spacing: await this.extractSpacingPatterns(designFile, config),
          components: await this.extractComponentPatterns(designFile, config),
          layouts: await this.extractLayoutPatterns(designFile, config),
          animations: await this.extractAnimationPatterns(designFile, config)
        },
        recommendations: [],
        score: 0
      };

      // Generate recommendations
      analysis.recommendations = this.generateRecommendations(analysis.patterns);

      // Calculate design system score
      analysis.score = this.calculateSystemScore(analysis.patterns);

      // Store patterns
      this.storePatterns(analysis.patterns);

      // Emit analysis complete
      this.emit('analysis:complete', analysis);

      return analysis;
    } catch (error) {
      this.emit('analysis:error', { designFile, error });
      throw error;
    }
  }

  /**
   * Extract color patterns
   */
  async extractColorPatterns(designFile, config) {
    const colors = [];
    const colorPalette = {
      primary: [],
      secondary: [],
      neutral: [],
      semantic: {
        success: [],
        warning: [],
        error: [],
        info: []
      }
    };

    // Extract colors from styles
    if (designFile.styles) {
      for (const style of designFile.styles) {
        if (style.styleType === 'FILL' && style.paints) {
          for (const paint of style.paints) {
            if (paint.type === 'SOLID') {
              colors.push({
                name: style.name,
                color: paint.color,
                opacity: paint.opacity || 1,
                usage: []
              });
            }
          }
        }
      }
    }

    // Analyze color relationships
    const relationships = this.analyzeColorRelationships(colors);

    // Detect color scheme
    const scheme = this.detectColorScheme(colors);

    // Generate color scales
    const scales = this.generateColorScales(colors);

    // Categorize colors
    for (const color of colors) {
      const category = this.categorizeColor(color);
      if (colorPalette[category.type]) {
        if (category.type === 'semantic') {
          colorPalette.semantic[category.subtype].push(color);
        } else {
          colorPalette[category.type].push(color);
        }
      }
    }

    return {
      palette: colorPalette,
      relationships,
      scheme,
      scales,
      totalColors: colors.length,
      contrast: this.analyzeColorContrast(colors)
    };
  }

  /**
   * Extract typography patterns
   */
  async extractTypographyPatterns(designFile, config) {
    const typography = {
      fontFamilies: new Set(),
      fontSizes: [],
      lineHeights: [],
      letterSpacing: [],
      fontWeights: new Set(),
      scale: null,
      hierarchy: []
    };

    // Extract text styles
    if (designFile.styles) {
      for (const style of designFile.styles) {
        if (style.styleType === 'TEXT') {
          const textStyle = {
            name: style.name,
            fontFamily: style.fontFamily,
            fontSize: style.fontSize,
            fontWeight: style.fontWeight,
            lineHeight: style.lineHeight,
            letterSpacing: style.letterSpacing,
            textTransform: style.textTransform
          };

          typography.fontFamilies.add(style.fontFamily);
          typography.fontSizes.push(style.fontSize);
          typography.fontWeights.add(style.fontWeight);
          typography.hierarchy.push(textStyle);
        }
      }
    }

    // Detect typography scale
    typography.scale = this.detectTypographyScale(typography.fontSizes);

    // Sort hierarchy by size
    typography.hierarchy.sort((a, b) => b.fontSize - a.fontSize);

    // Convert sets to arrays
    typography.fontFamilies = Array.from(typography.fontFamilies);
    typography.fontWeights = Array.from(typography.fontWeights);

    return typography;
  }

  /**
   * Extract spacing patterns
   */
  async extractSpacingPatterns(designFile, config) {
    const spacing = {
      values: new Set(),
      grid: null,
      scale: null,
      patterns: []
    };

    // Extract spacing from components
    if (designFile.components) {
      for (const component of designFile.components) {
        // Extract padding
        if (component.padding) {
          Object.values(component.padding).forEach(value => {
            if (value > 0) spacing.values.add(value);
          });
        }

        // Extract gaps
        if (component.gap) {
          spacing.values.add(component.gap);
        }

        // Extract margins
        if (component.margins) {
          Object.values(component.margins).forEach(value => {
            if (value > 0) spacing.values.add(value);
          });
        }
      }
    }

    // Convert to array and sort
    const spacingArray = Array.from(spacing.values).sort((a, b) => a - b);

    // Detect spacing scale
    spacing.scale = this.detectSpacingScale(spacingArray);

    // Detect grid system
    spacing.grid = this.detectGridSystem(spacingArray);

    // Find spacing patterns
    spacing.patterns = this.findSpacingPatterns(spacingArray);

    return {
      ...spacing,
      values: spacingArray
    };
  }

  /**
   * Extract component patterns
   */
  async extractComponentPatterns(designFile, config) {
    const patterns = {
      atomic: {
        atoms: [],
        molecules: [],
        organisms: []
      },
      recurring: [],
      variations: new Map(),
      relationships: []
    };

    if (designFile.components) {
      // Categorize components by atomic design
      for (const component of designFile.components) {
        const category = this.categorizeByAtomicDesign(component);
        patterns.atomic[category].push({
          id: component.id,
          name: component.name,
          type: component.type,
          complexity: this.calculateComponentComplexity(component)
        });
      }

      // Find recurring patterns
      patterns.recurring = this.findRecurringPatterns(designFile.components);

      // Find component variations
      patterns.variations = this.findComponentVariations(designFile.components);

      // Analyze relationships
      patterns.relationships = this.analyzeComponentRelationships(designFile.components);
    }

    return patterns;
  }

  /**
   * Extract layout patterns
   */
  async extractLayoutPatterns(designFile, config) {
    const layouts = {
      grids: [],
      flexLayouts: [],
      absoluteLayouts: [],
      autoLayouts: [],
      constraints: []
    };

    if (designFile.components) {
      for (const component of designFile.components) {
        // Detect grid layouts
        if (this.isGridLayout(component)) {
          layouts.grids.push(this.extractGridLayout(component));
        }

        // Detect flex layouts
        if (component.layoutMode === 'HORIZONTAL' || component.layoutMode === 'VERTICAL') {
          layouts.flexLayouts.push({
            id: component.id,
            name: component.name,
            direction: component.layoutMode,
            gap: component.gap,
            padding: component.padding,
            alignment: component.alignment
          });
        }

        // Detect auto layouts
        if (component.layoutMode === 'AUTO') {
          layouts.autoLayouts.push({
            id: component.id,
            name: component.name,
            settings: component.autoLayoutSettings
          });
        }

        // Extract constraints
        if (component.constraints) {
          layouts.constraints.push({
            id: component.id,
            constraints: component.constraints
          });
        }
      }
    }

    return layouts;
  }

  /**
   * Extract animation patterns
   */
  async extractAnimationPatterns(designFile, config) {
    const animations = {
      transitions: [],
      interactions: [],
      easingFunctions: new Set(),
      durations: []
    };

    // Extract from prototyping settings
    if (designFile.prototypeSettings) {
      for (const setting of designFile.prototypeSettings) {
        if (setting.transitionType) {
          animations.transitions.push({
            type: setting.transitionType,
            duration: setting.transitionDuration,
            easing: setting.transitionEasing
          });

          animations.easingFunctions.add(setting.transitionEasing);
          animations.durations.push(setting.transitionDuration);
        }
      }
    }

    // Convert sets to arrays
    animations.easingFunctions = Array.from(animations.easingFunctions);

    return animations;
  }

  /**
   * Analyze color relationships
   */
  analyzeColorRelationships(colors) {
    const relationships = [];

    for (let i = 0; i < colors.length; i++) {
      for (let j = i + 1; j < colors.length; j++) {
        const relation = this.compareColors(colors[i], colors[j]);
        if (relation.similarity > 0.8) {
          relationships.push(relation);
        }
      }
    }

    return relationships;
  }

  /**
   * Compare two colors
   */
  compareColors(color1, color2) {
    const rgb1 = color1.color;
    const rgb2 = color2.color;

    const distance = Math.sqrt(
      Math.pow(rgb1.r - rgb2.r, 2) +
      Math.pow(rgb1.g - rgb2.g, 2) +
      Math.pow(rgb1.b - rgb2.b, 2)
    );

    return {
      color1: color1.name,
      color2: color2.name,
      similarity: 1 - (distance / Math.sqrt(3)),
      relationship: this.determineColorRelationship(rgb1, rgb2)
    };
  }

  /**
   * Determine color relationship type
   */
  determineColorRelationship(rgb1, rgb2) {
    // Simplified relationship detection
    const hue1 = this.rgbToHue(rgb1);
    const hue2 = this.rgbToHue(rgb2);
    const hueDiff = Math.abs(hue1 - hue2);

    if (hueDiff < 30) return 'analogous';
    if (hueDiff > 150 && hueDiff < 210) return 'complementary';
    if (hueDiff > 110 && hueDiff < 130) return 'triadic';
    return 'custom';
  }

  /**
   * Convert RGB to Hue
   */
  rgbToHue(rgb) {
    const max = Math.max(rgb.r, rgb.g, rgb.b);
    const min = Math.min(rgb.r, rgb.g, rgb.b);
    const delta = max - min;

    if (delta === 0) return 0;

    let hue = 0;
    if (max === rgb.r) {
      hue = ((rgb.g - rgb.b) / delta) % 6;
    } else if (max === rgb.g) {
      hue = (rgb.b - rgb.r) / delta + 2;
    } else {
      hue = (rgb.r - rgb.g) / delta + 4;
    }

    return Math.round(hue * 60);
  }

  /**
   * Detect color scheme type
   */
  detectColorScheme(colors) {
    // Simplified scheme detection
    const hues = colors.map(c => this.rgbToHue(c.color));
    const uniqueHues = [...new Set(hues)];

    if (uniqueHues.length === 1) return 'monochromatic';
    if (uniqueHues.length === 2) return 'complementary';
    if (uniqueHues.length === 3) return 'triadic';
    return 'custom';
  }

  /**
   * Generate color scales
   */
  generateColorScales(colors) {
    const scales = {};

    // Group colors by hue
    const colorsByHue = {};
    for (const color of colors) {
      const hue = Math.round(this.rgbToHue(color.color) / 10) * 10;
      if (!colorsByHue[hue]) colorsByHue[hue] = [];
      colorsByHue[hue].push(color);
    }

    // Generate scales for each hue
    for (const [hue, hueColors] of Object.entries(colorsByHue)) {
      if (hueColors.length >= 3) {
        scales[`hue-${hue}`] = hueColors.sort((a, b) => {
          const lum1 = this.calculateLuminance(a.color);
          const lum2 = this.calculateLuminance(b.color);
          return lum1 - lum2;
        });
      }
    }

    return scales;
  }

  /**
   * Calculate luminance
   */
  calculateLuminance(rgb) {
    return 0.299 * rgb.r + 0.587 * rgb.g + 0.114 * rgb.b;
  }

  /**
   * Categorize color
   */
  categorizeColor(color) {
    const name = color.name.toLowerCase();

    // Check for semantic colors
    if (name.includes('success') || name.includes('green')) {
      return { type: 'semantic', subtype: 'success' };
    }
    if (name.includes('warning') || name.includes('yellow')) {
      return { type: 'semantic', subtype: 'warning' };
    }
    if (name.includes('error') || name.includes('danger') || name.includes('red')) {
      return { type: 'semantic', subtype: 'error' };
    }
    if (name.includes('info') || name.includes('blue')) {
      return { type: 'semantic', subtype: 'info' };
    }

    // Check for primary/secondary
    if (name.includes('primary')) return { type: 'primary' };
    if (name.includes('secondary')) return { type: 'secondary' };

    // Check for neutrals
    const luminance = this.calculateLuminance(color.color);
    const saturation = this.calculateSaturation(color.color);
    if (saturation < 0.1) return { type: 'neutral' };

    return { type: 'primary' };
  }

  /**
   * Calculate saturation
   */
  calculateSaturation(rgb) {
    const max = Math.max(rgb.r, rgb.g, rgb.b);
    const min = Math.min(rgb.r, rgb.g, rgb.b);
    const delta = max - min;
    return max === 0 ? 0 : delta / max;
  }

  /**
   * Analyze color contrast
   */
  analyzeColorContrast(colors) {
    const contrasts = [];

    // Check contrast between color pairs
    for (let i = 0; i < colors.length; i++) {
      for (let j = i + 1; j < colors.length; j++) {
        const ratio = this.calculateContrastRatio(colors[i].color, colors[j].color);
        contrasts.push({
          color1: colors[i].name,
          color2: colors[j].name,
          ratio,
          wcag: this.getWCAGLevel(ratio)
        });
      }
    }

    return contrasts.sort((a, b) => b.ratio - a.ratio);
  }

  /**
   * Calculate contrast ratio
   */
  calculateContrastRatio(color1, color2) {
    const lum1 = this.calculateLuminance(color1);
    const lum2 = this.calculateLuminance(color2);
    const brightest = Math.max(lum1, lum2);
    const darkest = Math.min(lum1, lum2);
    return (brightest + 0.05) / (darkest + 0.05);
  }

  /**
   * Get WCAG level for contrast ratio
   */
  getWCAGLevel(ratio) {
    if (ratio >= 7) return 'AAA';
    if (ratio >= 4.5) return 'AA';
    if (ratio >= 3) return 'AA-large';
    return 'FAIL';
  }

  /**
   * Detect typography scale
   */
  detectTypographyScale(sizes) {
    if (sizes.length < 2) return null;

    const sortedSizes = [...sizes].sort((a, b) => a - b);
    const ratios = [];

    for (let i = 1; i < sortedSizes.length; i++) {
      ratios.push(sortedSizes[i] / sortedSizes[i - 1]);
    }

    const avgRatio = ratios.reduce((a, b) => a + b, 0) / ratios.length;

    // Match to known scales
    const scales = {
      'minor-second': 1.067,
      'major-second': 1.125,
      'minor-third': 1.2,
      'major-third': 1.25,
      'perfect-fourth': 1.333
    };

    let closestScale = 'custom';
    let minDiff = Infinity;

    for (const [name, ratio] of Object.entries(scales)) {
      const diff = Math.abs(avgRatio - ratio);
      if (diff < minDiff) {
        minDiff = diff;
        closestScale = name;
      }
    }

    return {
      type: closestScale,
      ratio: avgRatio,
      sizes: sortedSizes
    };
  }

  /**
   * Detect spacing scale
   */
  detectSpacingScale(values) {
    if (values.length < 2) return null;

    // Check for linear scale
    const diffs = [];
    for (let i = 1; i < values.length; i++) {
      diffs.push(values[i] - values[i - 1]);
    }

    const isLinear = diffs.every(d => Math.abs(d - diffs[0]) < 2);
    if (isLinear) {
      return { type: 'linear', base: diffs[0] };
    }

    // Check for exponential scale
    const ratios = [];
    for (let i = 1; i < values.length; i++) {
      if (values[i - 1] !== 0) {
        ratios.push(values[i] / values[i - 1]);
      }
    }

    const avgRatio = ratios.reduce((a, b) => a + b, 0) / ratios.length;
    const isExponential = ratios.every(r => Math.abs(r - avgRatio) < 0.1);

    if (isExponential) {
      return { type: 'exponential', ratio: avgRatio };
    }

    return { type: 'custom', values };
  }

  /**
   * Detect grid system
   */
  detectGridSystem(values) {
    // Find common divisor
    const gcd = (a, b) => b === 0 ? a : gcd(b, a % b);
    const findGCD = (arr) => arr.reduce((a, b) => gcd(a, b));

    const intValues = values.map(Math.round).filter(v => v > 0);
    if (intValues.length < 2) return null;

    const baseUnit = findGCD(intValues);

    if (baseUnit > 1) {
      return {
        baseUnit,
        columns: Math.max(...intValues) / baseUnit,
        gutters: values.filter(v => v < baseUnit * 2)
      };
    }

    return null;
  }

  /**
   * Find spacing patterns
   */
  findSpacingPatterns(values) {
    const patterns = [];

    // Find arithmetic progressions
    for (let i = 0; i < values.length - 2; i++) {
      if (values[i + 1] - values[i] === values[i + 2] - values[i + 1]) {
        patterns.push({
          type: 'arithmetic',
          start: values[i],
          step: values[i + 1] - values[i],
          count: 3
        });
      }
    }

    // Find geometric progressions
    for (let i = 0; i < values.length - 2; i++) {
      if (values[i] !== 0 && values[i + 1] !== 0) {
        const ratio1 = values[i + 1] / values[i];
        const ratio2 = values[i + 2] / values[i + 1];
        if (Math.abs(ratio1 - ratio2) < 0.01) {
          patterns.push({
            type: 'geometric',
            start: values[i],
            ratio: ratio1,
            count: 3
          });
        }
      }
    }

    return patterns;
  }

  /**
   * Categorize by atomic design
   */
  categorizeByAtomicDesign(component) {
    const childCount = component.children?.length || 0;
    const complexity = this.calculateComponentComplexity(component);

    if (childCount === 0 || complexity < 0.2) return 'atoms';
    if (childCount < 5 || complexity < 0.5) return 'molecules';
    return 'organisms';
  }

  /**
   * Calculate component complexity
   */
  calculateComponentComplexity(component) {
    let complexity = 0;

    // Factor in number of children
    complexity += (component.children?.length || 0) * 0.1;

    // Factor in number of properties
    complexity += Object.keys(component).length * 0.05;

    // Factor in nesting depth
    const depth = this.calculateNestingDepth(component);
    complexity += depth * 0.15;

    return Math.min(complexity, 1);
  }

  /**
   * Calculate nesting depth
   */
  calculateNestingDepth(component, depth = 0) {
    if (!component.children || component.children.length === 0) {
      return depth;
    }

    let maxDepth = depth;
    for (const child of component.children) {
      const childDepth = this.calculateNestingDepth(child, depth + 1);
      maxDepth = Math.max(maxDepth, childDepth);
    }

    return maxDepth;
  }

  /**
   * Find recurring patterns
   */
  findRecurringPatterns(components) {
    const patterns = {};

    for (const component of components) {
      const signature = this.generateComponentSignature(component);
      if (!patterns[signature]) {
        patterns[signature] = [];
      }
      patterns[signature].push(component);
    }

    return Object.entries(patterns)
      .filter(([_, instances]) => instances.length > 1)
      .map(([signature, instances]) => ({
        signature,
        instances: instances.length,
        components: instances.map(c => ({ id: c.id, name: c.name }))
      }));
  }

  /**
   * Generate component signature
   */
  generateComponentSignature(component) {
    return `${component.type}-${component.children?.length || 0}-${component.layoutMode || 'none'}`;
  }

  /**
   * Find component variations
   */
  findComponentVariations(components) {
    const variations = new Map();

    for (const component of components) {
      const baseName = this.extractBaseName(component.name);
      if (!variations.has(baseName)) {
        variations.set(baseName, []);
      }
      variations.get(baseName).push(component);
    }

    // Filter to only keep groups with variations
    const result = new Map();
    for (const [name, comps] of variations.entries()) {
      if (comps.length > 1) {
        result.set(name, comps);
      }
    }

    return result;
  }

  /**
   * Extract base name
   */
  extractBaseName(name) {
    return name.replace(/[-_\s](default|hover|active|disabled|small|medium|large|light|dark)/gi, '').trim();
  }

  /**
   * Analyze component relationships
   */
  analyzeComponentRelationships(components) {
    const relationships = [];

    for (let i = 0; i < components.length; i++) {
      for (let j = i + 1; j < components.length; j++) {
        const similarity = this.calculateComponentSimilarity(components[i], components[j]);
        if (similarity > this.config.componentSimilarityThreshold) {
          relationships.push({
            component1: components[i].name,
            component2: components[j].name,
            similarity,
            type: this.determineRelationshipType(components[i], components[j])
          });
        }
      }
    }

    return relationships;
  }

  /**
   * Calculate component similarity
   */
  calculateComponentSimilarity(comp1, comp2) {
    let similarity = 0;

    // Compare types
    if (comp1.type === comp2.type) similarity += 0.3;

    // Compare structure
    if (comp1.children?.length === comp2.children?.length) similarity += 0.2;

    // Compare layout
    if (comp1.layoutMode === comp2.layoutMode) similarity += 0.2;

    // Compare properties
    const props1 = Object.keys(comp1).sort();
    const props2 = Object.keys(comp2).sort();
    const commonProps = props1.filter(p => props2.includes(p));
    similarity += (commonProps.length / Math.max(props1.length, props2.length)) * 0.3;

    return similarity;
  }

  /**
   * Determine relationship type
   */
  determineRelationshipType(comp1, comp2) {
    const name1 = comp1.name.toLowerCase();
    const name2 = comp2.name.toLowerCase();

    if (this.extractBaseName(comp1.name) === this.extractBaseName(comp2.name)) {
      return 'variant';
    }

    if (name1.includes(name2) || name2.includes(name1)) {
      return 'parent-child';
    }

    return 'similar';
  }

  /**
   * Check if grid layout
   */
  isGridLayout(component) {
    if (!component.children || component.children.length < 4) return false;

    // Check for regular spacing
    const positions = component.children.map(c => ({ x: c.x || 0, y: c.y || 0 }));

    // Simple grid detection - check if children are arranged in rows/columns
    const xPositions = [...new Set(positions.map(p => p.x))];
    const yPositions = [...new Set(positions.map(p => p.y))];

    return xPositions.length > 1 && yPositions.length > 1;
  }

  /**
   * Extract grid layout
   */
  extractGridLayout(component) {
    const children = component.children || [];
    const positions = children.map(c => ({ x: c.x || 0, y: c.y || 0 }));

    const xPositions = [...new Set(positions.map(p => p.x))].sort((a, b) => a - b);
    const yPositions = [...new Set(positions.map(p => p.y))].sort((a, b) => a - b);

    return {
      id: component.id,
      name: component.name,
      columns: xPositions.length,
      rows: yPositions.length,
      columnGap: xPositions.length > 1 ? xPositions[1] - xPositions[0] : 0,
      rowGap: yPositions.length > 1 ? yPositions[1] - yPositions[0] : 0
    };
  }

  /**
   * Generate recommendations
   */
  generateRecommendations(patterns) {
    const recommendations = [];

    // Color recommendations
    if (patterns.colors.totalColors > 20) {
      recommendations.push({
        type: 'warning',
        category: 'colors',
        message: 'Consider reducing color palette complexity'
      });
    }

    // Typography recommendations
    if (patterns.typography.fontFamilies.length > 3) {
      recommendations.push({
        type: 'warning',
        category: 'typography',
        message: 'Using more than 3 font families may reduce consistency'
      });
    }

    // Spacing recommendations
    if (!patterns.spacing.scale || patterns.spacing.scale.type === 'custom') {
      recommendations.push({
        type: 'suggestion',
        category: 'spacing',
        message: 'Consider using a consistent spacing scale'
      });
    }

    return recommendations;
  }

  /**
   * Calculate system score
   */
  calculateSystemScore(patterns) {
    let score = 100;

    // Deduct for inconsistencies
    if (patterns.colors.totalColors > 20) score -= 10;
    if (patterns.typography.fontFamilies.length > 3) score -= 10;
    if (!patterns.spacing.scale || patterns.spacing.scale.type === 'custom') score -= 15;

    // Add for good practices
    if (patterns.colors.scheme !== 'custom') score += 5;
    if (patterns.typography.scale && patterns.typography.scale.type !== 'custom') score += 5;
    if (patterns.spacing.grid) score += 5;

    return Math.max(0, Math.min(100, score));
  }

  /**
   * Store patterns
   */
  storePatterns(patterns) {
    for (const [category, data] of Object.entries(patterns)) {
      if (this.patterns[category]) {
        this.patterns[category].set(Date.now(), data);
      }
    }
  }

  /**
   * Generate analysis ID
   */
  generateAnalysisId() {
    return `analysis-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
  }

  /**
   * Export patterns
   */
  exportPatterns(format = 'json') {
    const patterns = {};

    for (const [category, map] of Object.entries(this.patterns)) {
      patterns[category] = Array.from(map.values());
    }

    switch (format) {
      case 'json':
        return JSON.stringify(patterns, null, 2);
      case 'css':
        return this.exportAsCSSVariables(patterns);
      case 'scss':
        return this.exportAsSCSS(patterns);
      default:
        return patterns;
    }
  }

  /**
   * Export as CSS variables
   */
  exportAsCSSVariables(patterns) {
    let css = ':root {\n';

    // Export colors
    if (patterns.colors) {
      for (const colorData of patterns.colors) {
        if (colorData.palette) {
          for (const [type, colors] of Object.entries(colorData.palette)) {
            if (Array.isArray(colors)) {
              colors.forEach((color, index) => {
                css += `  --color-${type}-${index}: rgb(${color.color.r * 255}, ${color.color.g * 255}, ${color.color.b * 255});\n`;
              });
            }
          }
        }
      }
    }

    // Export spacing
    if (patterns.spacing) {
      for (const spacingData of patterns.spacing) {
        if (spacingData.values) {
          spacingData.values.forEach((value, index) => {
            css += `  --spacing-${index}: ${value}px;\n`;
          });
        }
      }
    }

    css += '}\n';
    return css;
  }

  /**
   * Export as SCSS
   */
  exportAsSCSS(patterns) {
    let scss = '// Generated Design System Variables\n\n';

    // Export colors
    if (patterns.colors) {
      scss += '// Colors\n';
      for (const colorData of patterns.colors) {
        if (colorData.palette) {
          for (const [type, colors] of Object.entries(colorData.palette)) {
            if (Array.isArray(colors)) {
              colors.forEach((color, index) => {
                scss += `$color-${type}-${index}: rgb(${color.color.r * 255}, ${color.color.g * 255}, ${color.color.b * 255});\n`;
              });
            }
          }
        }
      }
    }

    // Export typography
    if (patterns.typography) {
      scss += '\n// Typography\n';
      for (const typographyData of patterns.typography) {
        if (typographyData.fontSizes) {
          typographyData.fontSizes.forEach((size, index) => {
            scss += `$font-size-${index}: ${size}px;\n`;
          });
        }
      }
    }

    return scss;
  }
}

module.exports = DesignPatternAnalyzer;