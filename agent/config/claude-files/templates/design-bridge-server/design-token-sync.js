/**
 * design-token-sync.js
 * Sprint 6.4: Design Token Synchronization
 *
 * Provides real-time design token synchronization:
 * - Figma to code token sync
 * - Token transformation pipelines
 * - Multi-format export (CSS, SCSS, JS, JSON)
 * - Token versioning and diffing
 * - Theme generation
 */

const EventEmitter = require('events');
const crypto = require('crypto');

/**
 * Token categories
 */
const TOKEN_CATEGORIES = {
  color: 'color',
  spacing: 'spacing',
  typography: 'typography',
  shadow: 'shadow',
  border: 'border',
  radius: 'radius',
  opacity: 'opacity',
  animation: 'animation',
  breakpoint: 'breakpoint',
  zIndex: 'z-index'
};

/**
 * Export formats
 */
const EXPORT_FORMATS = {
  css: 'css',
  scss: 'scss',
  less: 'less',
  js: 'javascript',
  ts: 'typescript',
  json: 'json',
  tailwind: 'tailwind'
};

/**
 * Default transform configurations
 */
const DEFAULT_TRANSFORMS = {
  color: {
    format: 'hex', // hex, rgb, hsl
    opacity: true,
    colorSpace: 'srgb'
  },
  spacing: {
    unit: 'rem',
    baseFontSize: 16
  },
  typography: {
    fontSizeUnit: 'rem',
    lineHeightUnit: 'unitless'
  }
};

class DesignTokenSync extends EventEmitter {
  constructor(options = {}) {
    super();

    this.tokens = new Map();
    this.themes = new Map();
    this.transforms = { ...DEFAULT_TRANSFORMS, ...options.transforms };
    this.version = options.version || '1.0.0';
    this.history = [];

    this.stats = {
      tokensProcessed: 0,
      syncsPerformed: 0,
      exportsGenerated: 0
    };
  }

  /**
   * Process tokens from Figma data
   * @param {Object} figmaTokens - Tokens from Figma
   * @param {Object} options - Processing options
   * @returns {Object} Processed tokens
   */
  processTokens(figmaTokens, options = {}) {
    const processed = {
      colors: {},
      spacing: {},
      typography: {},
      shadows: {},
      borders: {},
      radii: {},
      effects: {},
      metadata: {
        processedAt: new Date().toISOString(),
        source: options.source || 'figma',
        version: this.version
      }
    };

    // Process color tokens
    if (figmaTokens.colors) {
      processed.colors = this.processColors(figmaTokens.colors);
    }

    // Process spacing tokens
    if (figmaTokens.spacing) {
      processed.spacing = this.processSpacing(figmaTokens.spacing);
    }

    // Process typography tokens
    if (figmaTokens.typography) {
      processed.typography = this.processTypography(figmaTokens.typography);
    }

    // Process shadow tokens
    if (figmaTokens.shadows || figmaTokens.effects) {
      processed.shadows = this.processShadows(figmaTokens.shadows || figmaTokens.effects);
    }

    // Process border tokens
    if (figmaTokens.borders) {
      processed.borders = this.processBorders(figmaTokens.borders);
    }

    // Process radius tokens
    if (figmaTokens.radii || figmaTokens.borderRadius) {
      processed.radii = this.processRadii(figmaTokens.radii || figmaTokens.borderRadius);
    }

    // Store processed tokens
    this.tokens.set('default', processed);

    this.stats.tokensProcessed +=
      Object.keys(processed.colors).length +
      Object.keys(processed.spacing).length +
      Object.keys(processed.typography).length;

    this.emit('tokens:processed', {
      counts: {
        colors: Object.keys(processed.colors).length,
        spacing: Object.keys(processed.spacing).length,
        typography: Object.keys(processed.typography).length
      }
    });

    return processed;
  }

  /**
   * Process color tokens
   */
  processColors(colors) {
    const processed = {};

    Object.entries(colors).forEach(([name, value]) => {
      const tokenName = this.normalizeTokenName(name);

      if (typeof value === 'string') {
        processed[tokenName] = {
          value: this.transformColor(value),
          original: value,
          category: TOKEN_CATEGORIES.color
        };
      } else if (typeof value === 'object') {
        // Handle nested color objects (e.g., primary.500)
        if (value.value) {
          processed[tokenName] = {
            value: this.transformColor(value.value),
            original: value.value,
            description: value.description,
            category: TOKEN_CATEGORIES.color
          };
        } else {
          // Nested object - flatten
          Object.entries(value).forEach(([shade, shadeValue]) => {
            const nestedName = `${tokenName}-${shade}`;
            processed[nestedName] = {
              value: this.transformColor(typeof shadeValue === 'object' ? shadeValue.value : shadeValue),
              original: typeof shadeValue === 'object' ? shadeValue.value : shadeValue,
              category: TOKEN_CATEGORIES.color
            };
          });
        }
      }
    });

    return processed;
  }

  /**
   * Process spacing tokens
   */
  processSpacing(spacing) {
    const processed = {};

    Object.entries(spacing).forEach(([name, value]) => {
      const tokenName = this.normalizeTokenName(name);
      const numValue = typeof value === 'object' ? value.value : value;

      processed[tokenName] = {
        value: this.transformSpacing(numValue),
        original: numValue,
        pixels: this.toPixels(numValue),
        category: TOKEN_CATEGORIES.spacing
      };
    });

    return processed;
  }

  /**
   * Process typography tokens
   */
  processTypography(typography) {
    const processed = {};

    Object.entries(typography).forEach(([name, value]) => {
      const tokenName = this.normalizeTokenName(name);

      if (typeof value === 'object') {
        processed[tokenName] = {
          fontFamily: value.fontFamily || value.font,
          fontSize: this.transformFontSize(value.fontSize || value.size),
          fontWeight: value.fontWeight || value.weight || 400,
          lineHeight: value.lineHeight || 1.5,
          letterSpacing: value.letterSpacing || 'normal',
          category: TOKEN_CATEGORIES.typography
        };
      }
    });

    return processed;
  }

  /**
   * Process shadow tokens
   */
  processShadows(shadows) {
    const processed = {};

    Object.entries(shadows || {}).forEach(([name, value]) => {
      const tokenName = this.normalizeTokenName(name);

      if (typeof value === 'object') {
        processed[tokenName] = {
          value: this.transformShadow(value),
          original: value,
          category: TOKEN_CATEGORIES.shadow
        };
      }
    });

    return processed;
  }

  /**
   * Process border tokens
   */
  processBorders(borders) {
    const processed = {};

    Object.entries(borders || {}).forEach(([name, value]) => {
      const tokenName = this.normalizeTokenName(name);

      processed[tokenName] = {
        width: typeof value === 'object' ? value.width : value,
        style: typeof value === 'object' ? value.style : 'solid',
        color: typeof value === 'object' ? value.color : undefined,
        category: TOKEN_CATEGORIES.border
      };
    });

    return processed;
  }

  /**
   * Process radius tokens
   */
  processRadii(radii) {
    const processed = {};

    Object.entries(radii || {}).forEach(([name, value]) => {
      const tokenName = this.normalizeTokenName(name);
      const numValue = typeof value === 'object' ? value.value : value;

      processed[tokenName] = {
        value: this.transformSpacing(numValue),
        original: numValue,
        category: TOKEN_CATEGORIES.radius
      };
    });

    return processed;
  }

  /**
   * Transform color value
   */
  transformColor(color) {
    if (!color) return color;

    // Already in desired format
    if (this.transforms.color.format === 'hex' && color.startsWith('#')) {
      return color;
    }

    // Convert to RGB if needed
    if (this.transforms.color.format === 'rgb') {
      return this.hexToRgb(color);
    }

    return color;
  }

  /**
   * Transform spacing value
   */
  transformSpacing(value) {
    if (typeof value === 'string') {
      // Already has unit
      if (value.endsWith('rem') || value.endsWith('px') || value.endsWith('em')) {
        return value;
      }
      value = parseFloat(value);
    }

    if (this.transforms.spacing.unit === 'rem') {
      return `${value / this.transforms.spacing.baseFontSize}rem`;
    }

    return `${value}px`;
  }

  /**
   * Transform font size value
   */
  transformFontSize(value) {
    if (typeof value === 'string' && value.endsWith('rem')) {
      return value;
    }

    const numValue = typeof value === 'string' ? parseFloat(value) : value;

    if (this.transforms.typography.fontSizeUnit === 'rem') {
      return `${numValue / this.transforms.spacing.baseFontSize}rem`;
    }

    return `${numValue}px`;
  }

  /**
   * Transform shadow value
   */
  transformShadow(shadow) {
    const {
      x = 0,
      y = 0,
      blur = 0,
      spread = 0,
      color = 'rgba(0, 0, 0, 0.1)',
      inset = false
    } = shadow;

    const parts = [
      inset ? 'inset' : '',
      `${x}px`,
      `${y}px`,
      `${blur}px`,
      `${spread}px`,
      color
    ].filter(Boolean);

    return parts.join(' ');
  }

  /**
   * Normalize token name
   */
  normalizeTokenName(name) {
    return name
      .replace(/\//g, '-')
      .replace(/\s+/g, '-')
      .replace(/\./g, '-')
      .toLowerCase();
  }

  /**
   * Convert to pixels
   */
  toPixels(value) {
    if (typeof value === 'number') return value;
    if (typeof value === 'string') {
      if (value.endsWith('px')) return parseFloat(value);
      if (value.endsWith('rem')) return parseFloat(value) * this.transforms.spacing.baseFontSize;
    }
    return parseFloat(value) || 0;
  }

  /**
   * Hex to RGB conversion
   */
  hexToRgb(hex) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    if (result) {
      return `rgb(${parseInt(result[1], 16)}, ${parseInt(result[2], 16)}, ${parseInt(result[3], 16)})`;
    }
    return hex;
  }

  /**
   * Export tokens to specified format
   * @param {string} format - Export format
   * @param {Object} options - Export options
   * @returns {string} Exported tokens
   */
  exportTokens(format = 'css', options = {}) {
    const tokens = this.tokens.get(options.theme || 'default');

    if (!tokens) {
      return '';
    }

    this.stats.exportsGenerated++;

    switch (format) {
      case EXPORT_FORMATS.css:
        return this.exportToCSS(tokens, options);
      case EXPORT_FORMATS.scss:
        return this.exportToSCSS(tokens, options);
      case EXPORT_FORMATS.js:
      case EXPORT_FORMATS.ts:
        return this.exportToJS(tokens, options);
      case EXPORT_FORMATS.json:
        return this.exportToJSON(tokens, options);
      case EXPORT_FORMATS.tailwind:
        return this.exportToTailwind(tokens, options);
      default:
        return this.exportToCSS(tokens, options);
    }
  }

  /**
   * Export to CSS custom properties
   */
  exportToCSS(tokens, options = {}) {
    const prefix = options.prefix || '';
    let css = `:root {\n`;

    // Colors
    Object.entries(tokens.colors || {}).forEach(([name, token]) => {
      css += `  --${prefix}color-${name}: ${token.value};\n`;
    });

    // Spacing
    Object.entries(tokens.spacing || {}).forEach(([name, token]) => {
      css += `  --${prefix}spacing-${name}: ${token.value};\n`;
    });

    // Typography
    Object.entries(tokens.typography || {}).forEach(([name, token]) => {
      css += `  --${prefix}font-size-${name}: ${token.fontSize};\n`;
      css += `  --${prefix}font-weight-${name}: ${token.fontWeight};\n`;
      css += `  --${prefix}line-height-${name}: ${token.lineHeight};\n`;
    });

    // Shadows
    Object.entries(tokens.shadows || {}).forEach(([name, token]) => {
      css += `  --${prefix}shadow-${name}: ${token.value};\n`;
    });

    // Radii
    Object.entries(tokens.radii || {}).forEach(([name, token]) => {
      css += `  --${prefix}radius-${name}: ${token.value};\n`;
    });

    css += `}\n`;

    this.emit('export:complete', { format: 'css' });
    return css;
  }

  /**
   * Export to SCSS variables
   */
  exportToSCSS(tokens, options = {}) {
    const prefix = options.prefix || '';
    let scss = `// Design Tokens - Generated by Design Bridge\n// Version: ${this.version}\n\n`;

    // Colors
    scss += `// Colors\n`;
    Object.entries(tokens.colors || {}).forEach(([name, token]) => {
      scss += `$${prefix}color-${name}: ${token.value};\n`;
    });

    // Spacing
    scss += `\n// Spacing\n`;
    Object.entries(tokens.spacing || {}).forEach(([name, token]) => {
      scss += `$${prefix}spacing-${name}: ${token.value};\n`;
    });

    // Typography
    scss += `\n// Typography\n`;
    Object.entries(tokens.typography || {}).forEach(([name, token]) => {
      scss += `$${prefix}font-${name}: (\n`;
      scss += `  font-family: ${token.fontFamily || 'inherit'},\n`;
      scss += `  font-size: ${token.fontSize},\n`;
      scss += `  font-weight: ${token.fontWeight},\n`;
      scss += `  line-height: ${token.lineHeight}\n`;
      scss += `);\n`;
    });

    // Shadows
    scss += `\n// Shadows\n`;
    Object.entries(tokens.shadows || {}).forEach(([name, token]) => {
      scss += `$${prefix}shadow-${name}: ${token.value};\n`;
    });

    // Radii
    scss += `\n// Border Radius\n`;
    Object.entries(tokens.radii || {}).forEach(([name, token]) => {
      scss += `$${prefix}radius-${name}: ${token.value};\n`;
    });

    // Generate maps for easy access
    scss += `\n// Token Maps\n`;
    scss += `$colors: (\n`;
    Object.entries(tokens.colors || {}).forEach(([name, token], index, arr) => {
      scss += `  '${name}': ${token.value}${index < arr.length - 1 ? ',' : ''}\n`;
    });
    scss += `);\n`;

    this.emit('export:complete', { format: 'scss' });
    return scss;
  }

  /**
   * Export to JavaScript/TypeScript
   */
  exportToJS(tokens, options = {}) {
    const isTS = options.typescript !== false;

    let js = `// Design Tokens - Generated by Design Bridge\n`;
    js += `// Version: ${this.version}\n\n`;

    if (isTS) {
      js += `export interface DesignTokens {\n`;
      js += `  colors: Record<string, string>;\n`;
      js += `  spacing: Record<string, string>;\n`;
      js += `  typography: Record<string, TypographyToken>;\n`;
      js += `  shadows: Record<string, string>;\n`;
      js += `  radii: Record<string, string>;\n`;
      js += `}\n\n`;

      js += `export interface TypographyToken {\n`;
      js += `  fontFamily?: string;\n`;
      js += `  fontSize: string;\n`;
      js += `  fontWeight: number;\n`;
      js += `  lineHeight: number | string;\n`;
      js += `  letterSpacing?: string;\n`;
      js += `}\n\n`;
    }

    js += `export const tokens${isTS ? ': DesignTokens' : ''} = {\n`;

    // Colors
    js += `  colors: {\n`;
    Object.entries(tokens.colors || {}).forEach(([name, token]) => {
      js += `    '${name}': '${token.value}',\n`;
    });
    js += `  },\n`;

    // Spacing
    js += `  spacing: {\n`;
    Object.entries(tokens.spacing || {}).forEach(([name, token]) => {
      js += `    '${name}': '${token.value}',\n`;
    });
    js += `  },\n`;

    // Typography
    js += `  typography: {\n`;
    Object.entries(tokens.typography || {}).forEach(([name, token]) => {
      js += `    '${name}': {\n`;
      if (token.fontFamily) js += `      fontFamily: '${token.fontFamily}',\n`;
      js += `      fontSize: '${token.fontSize}',\n`;
      js += `      fontWeight: ${token.fontWeight},\n`;
      js += `      lineHeight: ${token.lineHeight},\n`;
      if (token.letterSpacing) js += `      letterSpacing: '${token.letterSpacing}',\n`;
      js += `    },\n`;
    });
    js += `  },\n`;

    // Shadows
    js += `  shadows: {\n`;
    Object.entries(tokens.shadows || {}).forEach(([name, token]) => {
      js += `    '${name}': '${token.value}',\n`;
    });
    js += `  },\n`;

    // Radii
    js += `  radii: {\n`;
    Object.entries(tokens.radii || {}).forEach(([name, token]) => {
      js += `    '${name}': '${token.value}',\n`;
    });
    js += `  },\n`;

    js += `};\n\n`;

    js += `export default tokens;\n`;

    this.emit('export:complete', { format: isTS ? 'ts' : 'js' });
    return js;
  }

  /**
   * Export to JSON
   */
  exportToJSON(tokens, options = {}) {
    const output = {
      $schema: 'https://design-tokens.org/schema/v1',
      version: this.version,
      generatedAt: new Date().toISOString(),
      tokens: {
        color: {},
        spacing: {},
        typography: {},
        shadow: {},
        radius: {}
      }
    };

    // Map tokens to standard format
    Object.entries(tokens.colors || {}).forEach(([name, token]) => {
      output.tokens.color[name] = {
        $value: token.value,
        $type: 'color'
      };
    });

    Object.entries(tokens.spacing || {}).forEach(([name, token]) => {
      output.tokens.spacing[name] = {
        $value: token.value,
        $type: 'dimension'
      };
    });

    Object.entries(tokens.typography || {}).forEach(([name, token]) => {
      output.tokens.typography[name] = {
        $value: {
          fontFamily: token.fontFamily,
          fontSize: token.fontSize,
          fontWeight: token.fontWeight,
          lineHeight: token.lineHeight
        },
        $type: 'typography'
      };
    });

    this.emit('export:complete', { format: 'json' });
    return JSON.stringify(output, null, 2);
  }

  /**
   * Export to Tailwind config format
   */
  exportToTailwind(tokens, options = {}) {
    let config = `// Tailwind CSS Design Tokens\n`;
    config += `// Generated by Design Bridge v${this.version}\n\n`;
    config += `module.exports = {\n`;
    config += `  theme: {\n`;
    config += `    extend: {\n`;

    // Colors
    config += `      colors: {\n`;
    Object.entries(tokens.colors || {}).forEach(([name, token]) => {
      config += `        '${name}': '${token.value}',\n`;
    });
    config += `      },\n`;

    // Spacing
    config += `      spacing: {\n`;
    Object.entries(tokens.spacing || {}).forEach(([name, token]) => {
      config += `        '${name}': '${token.value}',\n`;
    });
    config += `      },\n`;

    // Font sizes
    config += `      fontSize: {\n`;
    Object.entries(tokens.typography || {}).forEach(([name, token]) => {
      config += `        '${name}': ['${token.fontSize}', { lineHeight: '${token.lineHeight}' }],\n`;
    });
    config += `      },\n`;

    // Box shadow
    config += `      boxShadow: {\n`;
    Object.entries(tokens.shadows || {}).forEach(([name, token]) => {
      config += `        '${name}': '${token.value}',\n`;
    });
    config += `      },\n`;

    // Border radius
    config += `      borderRadius: {\n`;
    Object.entries(tokens.radii || {}).forEach(([name, token]) => {
      config += `        '${name}': '${token.value}',\n`;
    });
    config += `      },\n`;

    config += `    },\n`;
    config += `  },\n`;
    config += `};\n`;

    this.emit('export:complete', { format: 'tailwind' });
    return config;
  }

  /**
   * Create a theme from tokens
   * @param {string} themeName - Theme name
   * @param {Object} overrides - Token overrides for theme
   * @returns {Object} Theme tokens
   */
  createTheme(themeName, overrides = {}) {
    const baseTokens = this.tokens.get('default');

    if (!baseTokens) {
      throw new Error('No base tokens found. Process tokens first.');
    }

    const theme = JSON.parse(JSON.stringify(baseTokens)); // Deep clone

    // Apply overrides
    Object.entries(overrides).forEach(([category, tokens]) => {
      if (theme[category]) {
        Object.entries(tokens).forEach(([name, value]) => {
          const tokenName = this.normalizeTokenName(name);
          if (theme[category][tokenName]) {
            theme[category][tokenName].value = value;
          } else {
            theme[category][tokenName] = {
              value,
              category
            };
          }
        });
      }
    });

    theme.metadata = {
      ...theme.metadata,
      themeName,
      createdAt: new Date().toISOString()
    };

    this.themes.set(themeName, theme);
    this.emit('theme:created', { name: themeName });

    return theme;
  }

  /**
   * Compare tokens between two versions
   * @param {Object} oldTokens - Old tokens
   * @param {Object} newTokens - New tokens
   * @returns {Object} Diff result
   */
  diffTokens(oldTokens, newTokens) {
    const diff = {
      added: [],
      removed: [],
      changed: [],
      unchanged: 0
    };

    const categories = ['colors', 'spacing', 'typography', 'shadows', 'radii'];

    categories.forEach(category => {
      const oldCat = oldTokens[category] || {};
      const newCat = newTokens[category] || {};

      // Find added tokens
      Object.keys(newCat).forEach(key => {
        if (!oldCat[key]) {
          diff.added.push({ category, name: key, value: newCat[key].value });
        } else if (JSON.stringify(oldCat[key]) !== JSON.stringify(newCat[key])) {
          diff.changed.push({
            category,
            name: key,
            oldValue: oldCat[key].value,
            newValue: newCat[key].value
          });
        } else {
          diff.unchanged++;
        }
      });

      // Find removed tokens
      Object.keys(oldCat).forEach(key => {
        if (!newCat[key]) {
          diff.removed.push({ category, name: key, value: oldCat[key].value });
        }
      });
    });

    return diff;
  }

  /**
   * Get all tokens
   */
  getTokens(theme = 'default') {
    return this.tokens.get(theme);
  }

  /**
   * Get all themes
   */
  getThemes() {
    return Array.from(this.themes.keys());
  }

  /**
   * Get statistics
   */
  getStats() {
    return { ...this.stats };
  }

  /**
   * Reset sync state
   */
  reset() {
    this.tokens.clear();
    this.themes.clear();
    this.history = [];
    this.stats = {
      tokensProcessed: 0,
      syncsPerformed: 0,
      exportsGenerated: 0
    };
  }
}

// Export singleton and class
const designTokenSync = new DesignTokenSync();

module.exports = {
  DesignTokenSync,
  designTokenSync,
  TOKEN_CATEGORIES,
  EXPORT_FORMATS,
  DEFAULT_TRANSFORMS
};
