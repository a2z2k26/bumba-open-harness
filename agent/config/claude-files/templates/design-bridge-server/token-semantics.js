/**
 * Token Semantics Layer for AI-Human Partnership
 * Provides semantic context, usage guidelines, and WCAG compliance for design tokens
 */

class TokenSemanticsLayer {
  constructor() {
    this.colorSemantics = this.initializeColorSemantics();
    this.spacingSemantics = this.initializeSpacingSemantics();
    this.typographySemantics = this.initializeTypographySemantics();
    this.shadowSemantics = this.initializeShadowSemantics();
  }

  /**
   * Initialize color semantics with WCAG compliance
   */
  initializeColorSemantics() {
    return {
      // Primary colors
      'primary-500': {
        usage: 'Primary brand color, interactive elements, key actions',
        wcag: {
          onWhite: { ratio: 3.4, level: 'AA-Large' },
          onBlack: { ratio: 6.2, level: 'AA' }
        },
        emotion: 'Innovative, creative, premium',
        attention: 'High - draws immediate attention',
        relationships: ['primary-600', 'primary-400'],
        aiContext: {
          intent: 'Use for primary CTAs, brand moments, key interactions',
          avoid: 'Body text, low-emphasis elements',
          pairsWith: ['neutral backgrounds', 'white text when dark enough']
        }
      },
      'primary-600': {
        usage: 'Hover state for primary, deeper brand moments',
        wcag: {
          onWhite: { ratio: 4.8, level: 'AA' },
          onBlack: { ratio: 4.4, level: 'AA-Large' }
        },
        emotion: 'Confident, established, sophisticated',
        attention: 'High - active state emphasis',
        relationships: ['primary-500', 'primary-700'],
        aiContext: {
          intent: 'Hover/focus states, emphasis within primary contexts',
          avoid: 'Initial states, should be darker variant only',
          pairsWith: ['white text', 'light backgrounds']
        }
      },
      'success': {
        usage: 'Positive actions, confirmations, success states',
        wcag: {
          onWhite: { ratio: 2.8, level: 'AA-Large' },
          onBlack: { ratio: 7.5, level: 'AAA' }
        },
        emotion: 'Positive, growth, completion',
        attention: 'Medium - contextual feedback',
        relationships: ['success-dark', 'success-light'],
        aiContext: {
          intent: 'Success messages, positive feedback, completion states',
          avoid: 'Primary CTAs unless specifically success-oriented',
          pairsWith: ['white text on dark', 'success-light backgrounds']
        }
      },
      'warning': {
        usage: 'Caution states, non-critical alerts',
        wcag: {
          onWhite: { ratio: 2.1, level: 'AA-Large' },
          onBlack: { ratio: 10.0, level: 'AAA' }
        },
        emotion: 'Caution, attention, consideration',
        attention: 'Medium-High - requires user attention',
        relationships: ['warning-dark', 'warning-light'],
        aiContext: {
          intent: 'Warning messages, caution states, important notices',
          avoid: 'Error states, success states',
          pairsWith: ['dark text preferred', 'warning-light backgrounds']
        }
      },
      'error': {
        usage: 'Error states, destructive actions, critical alerts',
        wcag: {
          onWhite: { ratio: 3.9, level: 'AA-Large' },
          onBlack: { ratio: 5.4, level: 'AA' }
        },
        emotion: 'Urgent, critical, stop',
        attention: 'Highest - immediate action required',
        relationships: ['error-dark', 'error-light'],
        aiContext: {
          intent: 'Error messages, validation errors, destructive actions',
          avoid: 'General warnings, success states',
          pairsWith: ['white text', 'error-light backgrounds for containers']
        }
      }
    };
  }

  /**
   * Initialize spacing semantics with layout context
   */
  initializeSpacingSemantics() {
    return {
      '0': {
        usage: 'No spacing, flush alignment',
        layoutContext: 'Reset, remove default spacing',
        density: 'Maximum',
        aiContext: {
          intent: 'Remove spacing, create flush layouts',
          commonUse: ['Reset margins', 'Inline elements'],
          avoid: 'Between interactive elements'
        }
      },
      '1': {
        usage: 'Micro spacing, tight relationships',
        layoutContext: 'Within components, icon gaps',
        density: 'Very High',
        touchTarget: false,
        aiContext: {
          intent: 'Minimal separation within related items',
          commonUse: ['Icon-to-text gaps', 'Badge padding'],
          avoid: 'Between sections, touch targets'
        }
      },
      '2': {
        usage: 'Small spacing, component internal',
        layoutContext: 'Padding within buttons, form fields',
        density: 'High',
        touchTarget: false,
        aiContext: {
          intent: 'Internal component spacing',
          commonUse: ['Button padding', 'Input padding', 'List item gaps'],
          avoid: 'Major section separation'
        }
      },
      '4': {
        usage: 'Standard spacing, component separation',
        layoutContext: 'Between related components',
        density: 'Medium',
        touchTarget: true,
        aiContext: {
          intent: 'Default spacing between elements',
          commonUse: ['Card padding', 'Form field gaps', 'Paragraph spacing'],
          avoid: 'Micro-interactions, major sections'
        }
      },
      '8': {
        usage: 'Large spacing, section separation',
        layoutContext: 'Between distinct sections',
        density: 'Low',
        touchTarget: true,
        aiContext: {
          intent: 'Major visual separation',
          commonUse: ['Section margins', 'Card gaps', 'Modal padding'],
          avoid: 'Within components, tight layouts'
        }
      }
    };
  }

  /**
   * Initialize typography semantics with hierarchy
   */
  initializeTypographySemantics() {
    return {
      'heading-1': {
        usage: 'Page titles, hero text',
        hierarchy: 1,
        semanticHTML: 'h1',
        readability: {
          idealLineLength: '20-30 characters',
          minContrastRatio: 4.5
        },
        aiContext: {
          intent: 'Primary page heading, single use per page',
          voice: 'Bold, authoritative, clear',
          avoid: 'Multiple per page, body content',
          accessibility: 'Screen readers announce as main heading'
        }
      },
      'body-default': {
        usage: 'Standard body text, readable content',
        hierarchy: 0,
        semanticHTML: 'p',
        readability: {
          idealLineLength: '45-75 characters',
          minContrastRatio: 4.5,
          optimalLineHeight: 1.5
        },
        aiContext: {
          intent: 'Main content, descriptions, articles',
          voice: 'Clear, informative, neutral',
          avoid: 'Headings, labels, micro-copy',
          accessibility: 'Base reading experience'
        }
      }
    };
  }

  /**
   * Initialize shadow semantics with elevation context
   */
  initializeShadowSemantics() {
    return {
      'sm': {
        usage: 'Subtle elevation, card hover',
        elevation: 1,
        interaction: 'Rest state, minimal depth',
        aiContext: {
          intent: 'Gentle elevation, separate from background',
          commonUse: ['Cards', 'Buttons', 'Input focus'],
          avoid: 'Modals, high-emphasis elements'
        }
      },
      'md': {
        usage: 'Standard elevation, dropdowns',
        elevation: 2,
        interaction: 'Interactive state, clear separation',
        aiContext: {
          intent: 'Clear elevation, interactive elements',
          commonUse: ['Dropdowns', 'Popovers', 'Raised buttons'],
          avoid: 'Background elements, subtle separations'
        }
      },
      'lg': {
        usage: 'High elevation, modals',
        elevation: 3,
        interaction: 'Overlay state, highest priority',
        aiContext: {
          intent: 'Maximum elevation, overlay content',
          commonUse: ['Modals', 'Dialogs', 'Important notifications'],
          avoid: 'Regular content, inline elements'
        }
      }
    };
  }

  /**
   * Get semantic context for a token
   */
  getTokenSemantics(category, tokenName) {
    const categoryMap = {
      colors: this.colorSemantics,
      spacing: this.spacingSemantics,
      typography: this.typographySemantics,
      shadows: this.shadowSemantics
    };

    const semantics = categoryMap[category];
    return semantics ? semantics[tokenName] || null : null;
  }

  /**
   * Analyze contrast ratio between two colors
   */
  analyzeContrast(foreground, background) {
    const ratio = this.calculateContrastRatio(foreground, background);
    return {
      ratio: ratio.toFixed(2),
      wcagAA: ratio >= 4.5,
      wcagAAA: ratio >= 7.0,
      wcagAALarge: ratio >= 3.0,
      recommendation: this.getContrastRecommendation(ratio)
    };
  }

  /**
   * Calculate WCAG contrast ratio
   */
  calculateContrastRatio(fg, bg) {
    const getLuminance = (hexColor) => {
      const rgb = this.hexToRgb(hexColor);
      const sRGB = [rgb.r / 255, rgb.g / 255, rgb.b / 255];
      const linearRGB = sRGB.map(val => {
        if (val <= 0.03928) return val / 12.92;
        return Math.pow((val + 0.055) / 1.055, 2.4);
      });
      return linearRGB[0] * 0.2126 + linearRGB[1] * 0.7152 + linearRGB[2] * 0.0722;
    };

    const fgLum = getLuminance(fg);
    const bgLum = getLuminance(bg);
    const lighter = Math.max(fgLum, bgLum);
    const darker = Math.min(fgLum, bgLum);

    return (lighter + 0.05) / (darker + 0.05);
  }

  /**
   * Get contrast recommendation
   */
  getContrastRecommendation(ratio) {
    if (ratio >= 7.0) return 'Excellent - AAA compliant';
    if (ratio >= 4.5) return 'Good - AA compliant';
    if (ratio >= 3.0) return 'Acceptable - AA Large text only';
    return 'Poor - Fails WCAG, increase contrast';
  }

  /**
   * Helper: Convert hex to RGB
   */
  hexToRgb(hex) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    return result ? {
      r: parseInt(result[1], 16),
      g: parseInt(result[2], 16),
      b: parseInt(result[3], 16)
    } : null;
  }

  /**
   * Generate AI-friendly token documentation
   */
  generateAIDocumentation(tokens) {
    const documentation = {
      overview: 'Design token system with semantic meanings and relationships',
      categories: {}
    };

    for (const [category, categoryTokens] of Object.entries(tokens)) {
      documentation.categories[category] = {
        tokens: {},
        usage: this.getCategoryUsage(category),
        relationships: this.getCategoryRelationships(category)
      };

      for (const [tokenName, tokenValue] of Object.entries(categoryTokens)) {
        const semantics = this.getTokenSemantics(category, tokenName);
        documentation.categories[category].tokens[tokenName] = {
          value: tokenValue,
          semantics: semantics || {},
          examples: this.generateUsageExamples(category, tokenName)
        };
      }
    }

    return documentation;
  }

  /**
   * Get category usage guidelines
   */
  getCategoryUsage(category) {
    const usageMap = {
      colors: 'Define brand identity, states, and visual hierarchy',
      spacing: 'Create consistent rhythm and relationships between elements',
      typography: 'Establish content hierarchy and readability',
      shadows: 'Indicate elevation and spatial relationships'
    };
    return usageMap[category] || 'Design tokens for consistent styling';
  }

  /**
   * Get category relationships
   */
  getCategoryRelationships(category) {
    const relationshipMap = {
      colors: ['typography (contrast)', 'shadows (depth perception)'],
      spacing: ['typography (line height)', 'layout (grid system)'],
      typography: ['colors (contrast)', 'spacing (vertical rhythm)'],
      shadows: ['colors (shadow color)', 'spacing (elevation scale)']
    };
    return relationshipMap[category] || [];
  }

  /**
   * Generate usage examples
   */
  generateUsageExamples(category, tokenName) {
    const exampleMap = {
      colors: {
        'primary-500': '<Button variant="primary">Click me</Button>',
        'success': '<Alert type="success">Operation completed</Alert>',
        'error': '<FormError>Required field</FormError>'
      },
      spacing: {
        '4': 'padding: var(--spacing-4); // Standard component padding',
        '8': 'margin-bottom: var(--spacing-8); // Section separation'
      },
      typography: {
        'heading-1': '<h1 className="heading-1">Page Title</h1>',
        'body-default': '<p className="body-default">Content text</p>'
      }
    };

    return exampleMap[category]?.[tokenName] || null;
  }

  /**
   * Validate token relationships
   */
  validateRelationships(tokens) {
    const issues = [];

    // Check color contrast relationships
    if (tokens.colors) {
      for (const [colorName, colorValue] of Object.entries(tokens.colors)) {
        if (typeof colorValue === 'string' && colorValue.startsWith('#')) {
          const whiteContrast = this.calculateContrastRatio(colorValue, '#FFFFFF');
          const blackContrast = this.calculateContrastRatio(colorValue, '#000000');

          if (whiteContrast < 3.0 && blackContrast < 3.0) {
            issues.push({
              type: 'warning',
              token: colorName,
              message: 'Color has poor contrast with both black and white'
            });
          }
        }
      }
    }

    return issues;
  }
}

module.exports = TokenSemanticsLayer;