/**
 * Pattern Recognizer Extended - Additional pattern detection methods
 * Continues the PatternRecognizer class with specialized detection algorithms
 */

const PatternRecognizer = require('./pattern-recognizer');

class PatternRecognizerExtended extends PatternRecognizer {

  // Bootstrap-specific detection methods
  checkBootstrapSpacing(spacing) {
    const bootstrapSpacers = [0, 0.25, 0.5, 1, 1.5, 3]; // rem values
    const bootstrapClasses = ['m-', 'p-', 'mx-', 'my-', 'px-', 'py-'];

    let matches = 0;
    let total = Object.keys(spacing).length;

    Object.entries(spacing).forEach(([name, value]) => {
      const normalized = name.toLowerCase();
      const hasBootstrapNaming = bootstrapClasses.some(cls => normalized.includes(cls));

      if (hasBootstrapNaming) matches++;

      // Check if value matches Bootstrap spacer scale
      const numValue = this.parseSpacingValue(value);
      if (numValue && bootstrapSpacers.includes(numValue)) {
        matches++;
      }
    });

    return {
      score: total > 0 ? matches / (total * 2) : 0, // *2 because we check both naming and value
      matches,
      total,
      hasBootstrapNaming: matches > 0
    };
  }

  checkBootstrapBreakpoints(breakpoints) {
    const bootstrapBreakpoints = {
      xs: 0,
      sm: 576,
      md: 768,
      lg: 992,
      xl: 1200,
      xxl: 1400
    };

    let matches = 0;
    Object.entries(breakpoints).forEach(([name, value]) => {
      const normalized = name.toLowerCase();
      if (bootstrapBreakpoints[normalized] &&
          Math.abs(bootstrapBreakpoints[normalized] - this.parseSpacingValue(value)) < 50) {
        matches++;
      }
    });

    return {
      score: matches / Object.keys(bootstrapBreakpoints).length,
      matches,
      total: Object.keys(breakpoints).length
    };
  }

  checkBootstrapUtilities(tokens) {
    const utilities = ['text-', 'bg-', 'border-', 'rounded-', 'shadow-', 'display-'];
    let utilityMatches = 0;
    let totalTokens = 0;

    Object.values(tokens).forEach(category => {
      if (typeof category === 'object') {
        Object.keys(category).forEach(tokenName => {
          totalTokens++;
          if (utilities.some(util => tokenName.toLowerCase().includes(util))) {
            utilityMatches++;
          }
        });
      }
    });

    return {
      score: totalTokens > 0 ? utilityMatches / totalTokens : 0,
      matches: utilityMatches,
      total: totalTokens
    };
  }

  detectBootstrapVersion(indicators) {
    // Bootstrap 5 has different color system
    if (indicators.utilities?.score > 0.3) {
      return 'Bootstrap 5';
    }
    if (indicators.spacing?.hasBootstrapNaming) {
      return 'Bootstrap 4';
    }
    return 'Bootstrap 3';
  }

  gatherBootstrapEvidence(indicators) {
    const evidence = [];

    if (indicators.colors?.hasSemanticColors) {
      evidence.push('Found Bootstrap semantic color system');
    }
    if (indicators.spacing?.hasBootstrapNaming) {
      evidence.push('Detected Bootstrap spacing utilities');
    }
    if (indicators.breakpoints?.matches > 2) {
      evidence.push('Found Bootstrap responsive breakpoints');
    }

    return evidence;
  }

  // Tailwind-specific detection methods
  checkTailwindSpacing(spacing) {
    const tailwindScale = [0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 24, 32, 40, 48, 56, 64, 72, 80, 96];

    let matches = 0;
    Object.values(spacing).forEach(value => {
      const numValue = this.parseSpacingValue(value);
      if (numValue && tailwindScale.includes(numValue)) {
        matches++;
      }
    });

    return {
      score: Object.keys(spacing).length > 0 ? matches / Object.keys(spacing).length : 0,
      matches,
      total: Object.keys(spacing).length,
      scaleCompliance: matches / tailwindScale.length
    };
  }

  checkTailwindNaming(tokens) {
    const tailwindPatterns = [
      /^(m|p)[xytrbl]?-\d+$/,
      /^text-(xs|sm|base|lg|xl|\d+xl)$/,
      /^w-\d+$/,
      /^h-\d+$/,
      /^space-[xy]-\d+$/,
      /^gap-\d+$/
    ];

    let matches = 0;
    let total = 0;

    Object.values(tokens).forEach(category => {
      if (typeof category === 'object') {
        Object.keys(category).forEach(tokenName => {
          total++;
          if (tailwindPatterns.some(pattern => pattern.test(tokenName))) {
            matches++;
          }
        });
      }
    });

    return {
      score: total > 0 ? matches / total : 0,
      matches,
      total
    };
  }

  checkTailwindScale(tokens) {
    const tailwindSizes = [
      'xs', 'sm', 'base', 'lg', 'xl', '2xl', '3xl', '4xl', '5xl', '6xl', '7xl', '8xl', '9xl'
    ];

    let sizeMatches = 0;
    let totalSizes = 0;

    if (tokens.typography) {
      Object.keys(tokens.typography).forEach(typeName => {
        totalSizes++;
        if (tailwindSizes.some(size => typeName.includes(size))) {
          sizeMatches++;
        }
      });
    }

    return {
      score: totalSizes > 0 ? sizeMatches / totalSizes : 0,
      matches: sizeMatches,
      total: totalSizes
    };
  }

  checkTailwindShadePattern(colors) {
    const expectedShades = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];
    const colorGroups = this.groupColorsByBase(colors);

    let properGroups = 0;
    Object.values(colorGroups).forEach(group => {
      const shades = group.map(color => this.extractShadeNumber(color.name)).filter(Boolean);
      const hasProperShades = expectedShades.filter(shade => shades.includes(shade)).length >= 5;

      if (hasProperShades) properGroups++;
    });

    return properGroups / Math.max(Object.keys(colorGroups).length, 1);
  }

  detectTailwindVersion(indicators) {
    if (indicators.colors?.hasProperShades && indicators.naming?.score > 0.5) {
      return 'Tailwind CSS 3.0+';
    }
    if (indicators.scale?.score > 0.3) {
      return 'Tailwind CSS 2.0+';
    }
    return 'Tailwind CSS 1.0';
  }

  gatherTailwindEvidence(indicators) {
    const evidence = [];

    if (indicators.colors?.hasProperShades) {
      evidence.push('Found Tailwind color shade system');
    }
    if (indicators.spacing?.scaleCompliance > 0.5) {
      evidence.push('Detected Tailwind spacing scale');
    }
    if (indicators.naming?.score > 0.3) {
      evidence.push('Found Tailwind utility class naming');
    }

    return evidence;
  }

  // Ant Design detection
  async detectAntDesign(tokens) {
    const indicators = {
      colors: this.checkAntDesignColors(tokens.colors || {}),
      typography: this.checkAntDesignTypography(tokens.typography || {}),
      spacing: this.checkAntDesignSpacing(tokens.spacing || {}),
      components: this.checkAntDesignComponents(tokens)
    };

    return {
      name: 'Ant Design',
      confidence: this.calculateFrameworkConfidence(indicators),
      indicators,
      evidence: this.gatherAntDesignEvidence(indicators)
    };
  }

  checkAntDesignColors(colors) {
    const antPrimary = ['blue', 'geekblue', 'purple'];
    const antFunctional = ['success', 'warning', 'error', 'info'];

    let matches = 0;
    Object.keys(colors).forEach(colorName => {
      const normalized = colorName.toLowerCase();
      if (antPrimary.some(color => normalized.includes(color)) ||
          antFunctional.some(color => normalized.includes(color))) {
        matches++;
      }
    });

    return {
      score: Object.keys(colors).length > 0 ? matches / Object.keys(colors).length : 0,
      matches,
      total: Object.keys(colors).length
    };
  }

  // Chakra UI detection
  async detectChakraUI(tokens) {
    const indicators = {
      colors: this.checkChakraColors(tokens.colors || {}),
      spacing: this.checkChakraSpacing(tokens.spacing || {}),
      typography: this.checkChakraTypography(tokens.typography || {}),
      theming: this.checkChakraTheming(tokens)
    };

    return {
      name: 'Chakra UI',
      confidence: this.calculateFrameworkConfidence(indicators),
      indicators,
      evidence: this.gatherChakraEvidence(indicators)
    };
  }

  checkChakraColors(colors) {
    const chakraColors = [
      'gray', 'red', 'orange', 'yellow', 'green', 'teal',
      'blue', 'cyan', 'purple', 'pink', 'whiteAlpha', 'blackAlpha'
    ];

    const chakraShades = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900];

    let matches = 0;
    Object.keys(colors).forEach(colorName => {
      const hasChakraColor = chakraColors.some(color =>
        colorName.toLowerCase().includes(color.toLowerCase())
      );
      const hasChakraShade = chakraShades.some(shade =>
        colorName.includes(shade.toString())
      );

      if (hasChakraColor && hasChakraShade) matches++;
    });

    return {
      score: Object.keys(colors).length > 0 ? matches / Object.keys(colors).length : 0,
      matches,
      total: Object.keys(colors).length
    };
  }

  checkChakraSpacing(spacing) {
    const chakraSpacing = [
      0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 24, 32, 40, 48, 56, 64, 72, 80, 96
    ];

    let matches = 0;
    Object.values(spacing).forEach(value => {
      const numValue = this.parseSpacingValue(value);
      if (chakraSpacing.includes(numValue)) matches++;
    });

    return {
      score: Object.keys(spacing).length > 0 ? matches / Object.keys(spacing).length : 0,
      matches,
      total: Object.keys(spacing).length
    };
  }

  // Grid system detection methods
  async detectFourPointGrid(tokens) {
    const spacing = tokens.spacing || {};
    const spacingValues = Object.values(spacing)
      .map(value => this.parseSpacingValue(value))
      .filter(value => value !== null);

    if (spacingValues.length === 0) {
      return { confidence: 0, evidence: [] };
    }

    const fourPointCompliant = spacingValues.filter(value => value % 4 === 0);
    const compliance = fourPointCompliant.length / spacingValues.length;

    const commonFourPointValues = [4, 8, 12, 16, 20, 24, 28, 32, 36, 40];
    const hasCommonValues = commonFourPointValues.filter(value =>
      spacingValues.includes(value)
    ).length;

    const confidence = (compliance * 0.7) + ((hasCommonValues / commonFourPointValues.length) * 0.3);

    return {
      confidence,
      compliance,
      evidence: {
        compliantValues: fourPointCompliant,
        totalValues: spacingValues.length,
        commonValuesFound: hasCommonValues
      }
    };
  }

  async detectBootstrapGrid(tokens) {
    const breakpoints = tokens.breakpoints || {};
    const columns = tokens.columns || tokens.grid?.columns || {};

    const bootstrapBreakpoints = ['xs', 'sm', 'md', 'lg', 'xl'];
    const hasBootstrapBreakpoints = bootstrapBreakpoints.filter(bp =>
      Object.keys(breakpoints).some(key => key.toLowerCase().includes(bp))
    ).length;

    const has12Columns = Object.values(columns).some(value =>
      value === 12 || value === '12' || (typeof value === 'string' && value.includes('12'))
    );

    const confidence = (hasBootstrapBreakpoints / bootstrapBreakpoints.length) * 0.6 +
                      (has12Columns ? 0.4 : 0);

    return {
      confidence,
      evidence: {
        breakpointMatches: hasBootstrapBreakpoints,
        has12Columns,
        detectedBreakpoints: Object.keys(breakpoints)
      }
    };
  }

  async detectCSSGrid(tokens) {
    const gridTokens = tokens.grid || {};
    const cssGridIndicators = [
      'grid-template-columns',
      'grid-template-rows',
      'grid-gap',
      'grid-areas',
      'fr',
      'minmax',
      'repeat'
    ];

    let matches = 0;
    let total = 0;

    Object.entries(gridTokens).forEach(([key, value]) => {
      total++;
      const keyLower = key.toLowerCase();
      const valueStr = String(value).toLowerCase();

      if (cssGridIndicators.some(indicator =>
          keyLower.includes(indicator) || valueStr.includes(indicator)
      )) {
        matches++;
      }
    });

    return {
      confidence: total > 0 ? matches / total : 0,
      evidence: {
        matches,
        total,
        indicators: cssGridIndicators.filter(ind =>
          Object.keys(gridTokens).some(key => key.toLowerCase().includes(ind))
        )
      }
    };
  }

  async detectFlexboxGrid(tokens) {
    const flexTokens = { ...tokens.layout, ...tokens.flex } || {};
    const flexboxIndicators = [
      'flex-direction',
      'flex-wrap',
      'justify-content',
      'align-items',
      'flex-grow',
      'flex-shrink',
      'flex-basis'
    ];

    let matches = 0;
    let total = Object.keys(flexTokens).length;

    Object.keys(flexTokens).forEach(key => {
      if (flexboxIndicators.some(indicator =>
          key.toLowerCase().includes(indicator.replace('-', ''))
      )) {
        matches++;
      }
    });

    return {
      confidence: total > 0 ? matches / total : 0,
      evidence: {
        matches,
        total,
        detectedProperties: Object.keys(flexTokens)
      }
    };
  }

  async detectCustomGrid(tokens) {
    const spacing = tokens.spacing || {};
    const layout = tokens.layout || {};

    // Look for consistent mathematical relationships
    const spacingValues = Object.values(spacing)
      .map(v => this.parseSpacingValue(v))
      .filter(v => v !== null)
      .sort((a, b) => a - b);

    if (spacingValues.length < 3) {
      return { confidence: 0, evidence: [] };
    }

    // Check for arithmetic progression
    const differences = [];
    for (let i = 1; i < spacingValues.length; i++) {
      differences.push(spacingValues[i] - spacingValues[i - 1]);
    }

    const isArithmetic = differences.every(diff =>
      Math.abs(diff - differences[0]) < 2
    );

    // Check for geometric progression
    const ratios = [];
    for (let i = 1; i < spacingValues.length; i++) {
      if (spacingValues[i - 1] !== 0) {
        ratios.push(spacingValues[i] / spacingValues[i - 1]);
      }
    }

    const isGeometric = ratios.length > 0 && ratios.every(ratio =>
      Math.abs(ratio - ratios[0]) < 0.1
    );

    const confidence = isArithmetic ? 0.8 : (isGeometric ? 0.7 : 0.3);

    return {
      confidence,
      evidence: {
        type: isArithmetic ? 'arithmetic' : (isGeometric ? 'geometric' : 'irregular'),
        values: spacingValues,
        pattern: isArithmetic ? differences[0] : (isGeometric ? ratios[0] : null)
      }
    };
  }

  // Component pattern detection
  // Missing methodology detection methods
  async detectITCSSPattern(tokens) {
    // ITCSS (Inverted Triangle CSS) detection
    return {
      confidence: 0,
      detected: false,
      evidence: []
    };
  }

  async detectSMACSS(tokens) {
    // SMACSS (Scalable and Modular Architecture for CSS) detection
    return {
      confidence: 0,
      detected: false,
      evidence: []
    };
  }

  async detectOOCSS(tokens) {
    // OOCSS (Object-Oriented CSS) detection
    return {
      confidence: 0,
      detected: false,
      evidence: []
    };
  }

  async detectBEMPattern(tokens) {
    const componentNames = this.extractComponentNames(tokens);
    const bemPattern = /^[a-z][a-z0-9-]*(__[a-z][a-z0-9-]*)?(-{1,2}[a-z][a-z0-9-]*)?$/;

    let matches = 0;
    componentNames.forEach(name => {
      if (bemPattern.test(name.toLowerCase())) {
        matches++;
      }
    });

    return {
      confidence: componentNames.length > 0 ? matches / componentNames.length : 0,
      matches,
      total: componentNames.length,
      evidence: componentNames.filter(name => bemPattern.test(name.toLowerCase()))
    };
  }

  detectImplicitAtomicPatterns(componentNames) {
    const atomicPatterns = {
      atoms: ['button', 'input', 'label', 'icon', 'badge'],
      molecules: ['form-group', 'nav-item', 'card-header', 'search-box'],
      organisms: ['header', 'footer', 'sidebar', 'navigation', 'hero']
    };

    const implicitMatches = [];

    componentNames.forEach(name => {
      const normalized = name.toLowerCase().replace(/[-_]/g, '');

      Object.entries(atomicPatterns).forEach(([level, patterns]) => {
        patterns.forEach(pattern => {
          if (normalized.includes(pattern.replace(/[-_]/g, ''))) {
            implicitMatches.push({
              name,
              level,
              pattern,
              type: 'implicit'
            });
          }
        });
      });
    });

    return implicitMatches;
  }

  generateAtomicRecommendations(componentNames) {
    const recommendations = [];

    if (componentNames.length === 0) {
      recommendations.push('Start by identifying atomic components (buttons, inputs, icons)');
      return recommendations;
    }

    const hasAtoms = componentNames.some(name =>
      /button|input|icon|badge|label/.test(name.toLowerCase())
    );

    if (!hasAtoms) {
      recommendations.push('Consider defining atomic-level components first');
    }

    const hasMolecules = componentNames.some(name =>
      /form|card|search|nav/.test(name.toLowerCase())
    );

    if (hasAtoms && !hasMolecules) {
      recommendations.push('Build molecules by combining your atoms');
    }

    return recommendations;
  }

  // Helper methods
  groupColorsByBase(colors) {
    const groups = {};

    Object.entries(colors).forEach(([name, color]) => {
      const baseName = name.replace(/[-_]?\d+$/, '');
      if (!groups[baseName]) groups[baseName] = [];
      groups[baseName].push({ name, color });
    });

    return groups;
  }

  extractShadeNumber(colorName) {
    const match = colorName.match(/(\d+)$/);
    return match ? parseInt(match[1]) : null;
  }

  generateEightPointRecommendations(spacingValues) {
    const recommendations = [];
    const nonCompliant = spacingValues.filter(value => value % 8 !== 0);

    if (nonCompliant.length > 0) {
      recommendations.push({
        type: 'spacing',
        message: `${nonCompliant.length} spacing values don't follow 8pt grid`,
        suggestions: nonCompliant.map(value => {
          const lower = Math.floor(value / 8) * 8;
          const upper = Math.ceil(value / 8) * 8;
          return `${value} → ${Math.abs(value - lower) < Math.abs(value - upper) ? lower : upper}`;
        })
      });
    }

    return recommendations;
  }

  generateGridRecommendations(gridSystems) {
    const recommendations = [];
    const bestGrid = Object.entries(gridSystems)
      .sort((a, b) => b[1].confidence - a[1].confidence)[0];

    if (!bestGrid || bestGrid[1].confidence < 0.5) {
      recommendations.push({
        type: 'grid',
        priority: 'high',
        message: 'No consistent grid system detected',
        suggestions: [
          'Implement 8-point grid for better spacing consistency',
          'Consider using a baseline grid for typography',
          'Define clear breakpoints for responsive design'
        ]
      });
    }

    return recommendations;
  }

  // Missing Ant Design methods
  checkAntDesignSpacing(spacing) {
    const antSpacing = [4, 8, 12, 16, 20, 24, 32]; // Ant Design spacing scale
    let matches = 0;
    let total = Object.keys(spacing).length;

    Object.entries(spacing).forEach(([name, value]) => {
      const numValue = this.parseSpacingValue(value);
      if (numValue && antSpacing.includes(numValue)) {
        matches++;
      }
    });

    return { score: total > 0 ? matches / total : 0, matches, total };
  }

  // Missing Chakra UI methods
  checkChakraSpacing(spacing) {
    const chakraSpacing = [1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 24, 32, 40, 48, 56, 64]; // Chakra spacing scale
    let matches = 0;
    let total = Object.keys(spacing).length;

    Object.entries(spacing).forEach(([name, value]) => {
      const numValue = this.parseSpacingValue(value);
      if (numValue && chakraSpacing.includes(numValue)) {
        matches++;
      }
    });

    return { score: total > 0 ? matches / total : 0, matches, total };
  }

  checkAntDesignTypography(typography) {
    const antTypeSizes = [12, 14, 16, 20, 24, 30, 38, 46, 56, 68]; // Ant Design typography scale
    const antTypeNames = ['caption', 'body2', 'body1', 'h6', 'h5', 'h4', 'h3', 'h2', 'h1', 'display'];

    let matches = 0;
    let total = Object.keys(typography).length;

    Object.entries(typography).forEach(([name, typo]) => {
      const normalized = name.toLowerCase();

      // Check naming patterns
      if (antTypeNames.some(antName => normalized.includes(antName))) {
        matches++;
      }

      // Check font sizes
      const fontSize = typo.fontSize?.px || typo.value || 0;
      if (antTypeSizes.includes(fontSize)) {
        matches++;
      }
    });

    return { score: total > 0 ? matches / (total * 2) : 0, matches, total };
  }

  checkChakraTypography(typography) {
    const chakraTypeSizes = [12, 14, 16, 18, 20, 24, 28, 36, 48, 60, 72]; // Chakra UI typography scale
    const chakraTypeNames = ['xs', 'sm', 'md', 'lg', 'xl', '2xl', '3xl', '4xl', '5xl', '6xl'];

    let matches = 0;
    let total = Object.keys(typography).length;

    Object.entries(typography).forEach(([name, typo]) => {
      const normalized = name.toLowerCase();

      // Check naming patterns
      if (chakraTypeNames.some(chakraName => normalized.includes(chakraName))) {
        matches++;
      }

      // Check font sizes
      const fontSize = typo.fontSize?.px || typo.value || 0;
      if (chakraTypeSizes.includes(fontSize)) {
        matches++;
      }
    });

    return { score: total > 0 ? matches / (total * 2) : 0, matches, total };
  }

  checkAntDesignComponents(tokens) {
    const antComponents = ['button', 'input', 'card', 'table', 'form', 'menu', 'modal', 'drawer'];
    const components = tokens.components || {};

    let matches = 0;
    let total = Object.keys(components).length;

    Object.keys(components).forEach(name => {
      const normalized = name.toLowerCase();
      if (antComponents.some(antComp => normalized.includes(antComp))) {
        matches++;
      }
    });

    return { score: total > 0 ? matches / total : 0, matches, total };
  }

  gatherAntDesignEvidence(indicators) {
    const evidence = [];

    if (indicators.colors.score > 0.3) {
      evidence.push(`${indicators.colors.matches} colors match Ant Design palette`);
    }
    if (indicators.spacing.score > 0.3) {
      evidence.push(`${indicators.spacing.matches} spacing values align with Ant Design scale`);
    }
    if (indicators.typography.score > 0.3) {
      evidence.push(`${indicators.typography.matches} typography tokens match Ant Design system`);
    }
    if (indicators.components.score > 0.3) {
      evidence.push(`${indicators.components.matches} components align with Ant Design patterns`);
    }

    return evidence;
  }

  checkChakraTheming(tokens) {
    let score = 0;
    let indicators = [];

    // Check for Chakra theme structure
    if (tokens.theme || tokens.chakra) {
      score += 0.5;
      indicators.push('Has theme structure');
    }

    // Check for Chakra-specific token naming
    const tokenKeys = Object.keys(tokens).join(' ');
    const chakraKeywords = ['chakra', 'theme', 'variants', 'baseStyle', 'sizes'];

    chakraKeywords.forEach(keyword => {
      if (tokenKeys.toLowerCase().includes(keyword)) {
        score += 0.1;
        indicators.push(`Contains ${keyword} tokens`);
      }
    });

    return { score: Math.min(score, 1), indicators };
  }

  gatherChakraEvidence(tokens) {
    const evidence = [];

    // Check theme structure
    if (tokens.theme) {
      evidence.push({
        type: 'structure',
        detail: 'Has theme object',
        confidence: 0.8
      });
    }

    // Check for Chakra-specific properties
    const chakraProps = ['space', 'sizes', 'radii', 'shadows', 'zIndices', 'colors', 'fonts'];
    chakraProps.forEach(prop => {
      if (tokens[prop]) {
        evidence.push({
          type: 'property',
          detail: `Has ${prop} property`,
          confidence: 0.6
        });
      }
    });

    // Check for semantic tokens
    if (tokens.semanticTokens) {
      evidence.push({
        type: 'semantic',
        detail: 'Has semantic tokens',
        confidence: 0.9
      });
    }

    // Check for responsive arrays
    const tokenString = JSON.stringify(tokens);
    if (tokenString.includes('[') && tokenString.includes(']')) {
      evidence.push({
        type: 'responsive',
        detail: 'Has responsive arrays',
        confidence: 0.5
      });
    }

    // Check for variants
    if (tokens.variants || tokens.components) {
      evidence.push({
        type: 'components',
        detail: 'Has component variants',
        confidence: 0.7
      });
    }

    return evidence;
  }
}

module.exports = PatternRecognizerExtended;