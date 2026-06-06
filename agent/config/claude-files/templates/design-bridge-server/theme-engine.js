/**
 * Theme Engine
 * Manages theme detection, extraction, and switching for design systems
 * Sprint 4: Theme Engine Development
 */

const EventEmitter = require('events');

class ThemeEngine extends EventEmitter {
  constructor() {
    super();
    this.name = 'ThemeEngine';
    this.version = '1.0.0';

    // Theme registry
    this.themes = new Map();

    // Active theme
    this.activeTheme = 'light';

    // Theme detection patterns
    this.detectionPatterns = {
      light: ['light', 'default', 'day', 'bright'],
      dark: ['dark', 'night', 'dim', 'midnight'],
      highContrast: ['high-contrast', 'hc', 'a11y', 'accessible'],
      custom: []
    };

    // Color scheme mappings
    this.colorSchemes = {
      light: {
        background: '#FFFFFF',
        foreground: '#000000',
        primary: '#0066CC',
        secondary: '#6B7280',
        accent: '#10B981',
        error: '#EF4444',
        warning: '#F59E0B',
        success: '#10B981',
        info: '#3B82F6'
      },
      dark: {
        background: '#1F2937',
        foreground: '#F9FAFB',
        primary: '#3B82F6',
        secondary: '#9CA3AF',
        accent: '#34D399',
        error: '#F87171',
        warning: '#FBBF24',
        success: '#34D399',
        info: '#60A5FA'
      },
      highContrast: {
        background: '#000000',
        foreground: '#FFFFFF',
        primary: '#FFFF00',
        secondary: '#FFFFFF',
        accent: '#00FFFF',
        error: '#FF0000',
        warning: '#FFA500',
        success: '#00FF00',
        info: '#0080FF'
      }
    };

    // Theme variables
    this.themeVariables = new Map();

    // Initialize default themes
    this.initializeDefaultThemes();
  }

  /**
   * Initialize default themes
   */
  initializeDefaultThemes() {
    // Light theme
    this.registerTheme('light', {
      name: 'Light',
      type: 'light',
      colors: this.colorSchemes.light,
      typography: this.generateTypographyTheme('light'),
      spacing: this.generateSpacingTheme('light'),
      shadows: this.generateShadowTheme('light'),
      borders: this.generateBorderTheme('light'),
      animations: this.generateAnimationTheme('light')
    });

    // Dark theme
    this.registerTheme('dark', {
      name: 'Dark',
      type: 'dark',
      colors: this.colorSchemes.dark,
      typography: this.generateTypographyTheme('dark'),
      spacing: this.generateSpacingTheme('dark'),
      shadows: this.generateShadowTheme('dark'),
      borders: this.generateBorderTheme('dark'),
      animations: this.generateAnimationTheme('dark')
    });

    // High contrast theme
    this.registerTheme('highContrast', {
      name: 'High Contrast',
      type: 'highContrast',
      colors: this.colorSchemes.highContrast,
      typography: this.generateTypographyTheme('highContrast'),
      spacing: this.generateSpacingTheme('highContrast'),
      shadows: this.generateShadowTheme('highContrast'),
      borders: this.generateBorderTheme('highContrast'),
      animations: this.generateAnimationTheme('highContrast')
    });
  }

  /**
   * Detect and extract themes from design file
   */
  async detectAndExtract(designFile, options = {}) {
    const detectedThemes = [];

    try {
      // Analyze file structure for theme indicators
      const themeIndicators = await this.analyzeForThemes(designFile);

      // Extract color themes
      const colorThemes = await this.extractColorThemes(designFile, themeIndicators);

      // Extract component themes
      const componentThemes = await this.extractComponentThemes(designFile, themeIndicators);

      // Detect theme variables
      const themeVariables = await this.detectThemeVariables(designFile);

      // Build theme configurations
      for (const indicator of themeIndicators) {
        const theme = await this.buildTheme({
          name: indicator.name,
          type: indicator.type,
          colors: colorThemes[indicator.name],
          components: componentThemes[indicator.name],
          variables: themeVariables[indicator.name],
          source: designFile
        });

        detectedThemes.push(theme);
        this.registerTheme(indicator.name, theme);
      }

      this.emit('themes:detected', detectedThemes);
      return detectedThemes;
    } catch (error) {
      this.emit('theme:error', error);
      throw error;
    }
  }

  /**
   * Analyze design file for theme indicators
   */
  async analyzeForThemes(designFile) {
    const indicators = [];

    // Check for named pages/artboards with theme names
    if (designFile.pages) {
      for (const page of designFile.pages) {
        const themeName = this.detectThemeName(page.name);
        if (themeName) {
          indicators.push({
            name: themeName,
            type: this.detectThemeType(themeName),
            source: 'page',
            id: page.id
          });
        }
      }
    }

    // Check for color styles with theme prefixes
    if (designFile.styles) {
      const themeStyles = this.groupStylesByTheme(designFile.styles);
      for (const [themeName, styles] of Object.entries(themeStyles)) {
        indicators.push({
          name: themeName,
          type: this.detectThemeType(themeName),
          source: 'styles',
          styles
        });
      }
    }

    // Check for variant properties indicating themes
    if (designFile.components) {
      const themeVariants = this.detectThemeVariants(designFile.components);
      for (const variant of themeVariants) {
        indicators.push({
          name: variant.name,
          type: variant.type,
          source: 'variants',
          components: variant.components
        });
      }
    }

    return indicators;
  }

  /**
   * Extract color themes
   */
  async extractColorThemes(designFile, indicators) {
    const colorThemes = {};

    for (const indicator of indicators) {
      const colors = {};

      // Extract from color styles
      if (indicator.styles) {
        for (const style of indicator.styles) {
          if (style.styleType === 'FILL') {
            colors[this.normalizeColorName(style.name)] = this.extractColorValue(style);
          }
        }
      }

      // Extract from components
      if (indicator.components) {
        const componentColors = await this.extractComponentColors(indicator.components);
        Object.assign(colors, componentColors);
      }

      // Map to semantic colors
      colorThemes[indicator.name] = this.mapToSemanticColors(colors);
    }

    return colorThemes;
  }

  /**
   * Build complete theme configuration
   */
  async buildTheme(config) {
    const theme = {
      id: this.generateThemeId(config.name),
      name: config.name,
      type: config.type || 'custom',
      colors: config.colors || {},
      typography: config.typography || this.generateTypographyTheme(config.type),
      spacing: config.spacing || this.generateSpacingTheme(config.type),
      shadows: config.shadows || this.generateShadowTheme(config.type),
      borders: config.borders || this.generateBorderTheme(config.type),
      animations: config.animations || this.generateAnimationTheme(config.type),
      components: config.components || {},
      variables: config.variables || {},
      metadata: {
        source: config.source,
        created: new Date().toISOString(),
        version: '1.0.0'
      }
    };

    // Calculate theme properties
    theme.properties = this.calculateThemeProperties(theme);

    // Generate CSS variables
    theme.cssVariables = this.generateCSSVariables(theme);

    // Generate theme tokens
    theme.tokens = this.generateThemeTokens(theme);

    return theme;
  }

  /**
   * Register a theme
   */
  registerTheme(name, config) {
    const theme = {
      ...config,
      id: config.id || this.generateThemeId(name),
      registered: new Date().toISOString()
    };

    this.themes.set(name, theme);
    this.emit('theme:registered', { name, theme });

    return theme;
  }

  /**
   * Switch to a different theme
   */
  switchTheme(themeName) {
    if (!this.themes.has(themeName)) {
      throw new Error(`Theme '${themeName}' not found`);
    }

    const previousTheme = this.activeTheme;
    this.activeTheme = themeName;

    const theme = this.themes.get(themeName);

    this.emit('theme:switched', {
      from: previousTheme,
      to: themeName,
      theme
    });

    return theme;
  }

  /**
   * Generate typography theme
   */
  generateTypographyTheme(type) {
    const baseSize = type === 'highContrast' ? 18 : 16;

    return {
      fontFamily: {
        sans: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        serif: 'Georgia, Cambria, "Times New Roman", Times, serif',
        mono: 'Menlo, Monaco, Consolas, "Courier New", monospace'
      },
      fontSize: {
        xs: `${baseSize * 0.75}px`,
        sm: `${baseSize * 0.875}px`,
        base: `${baseSize}px`,
        lg: `${baseSize * 1.125}px`,
        xl: `${baseSize * 1.25}px`,
        '2xl': `${baseSize * 1.5}px`,
        '3xl': `${baseSize * 1.875}px`,
        '4xl': `${baseSize * 2.25}px`
      },
      fontWeight: {
        thin: 100,
        light: 300,
        normal: 400,
        medium: 500,
        semibold: 600,
        bold: 700,
        extrabold: 800
      },
      lineHeight: {
        none: 1,
        tight: 1.25,
        snug: 1.375,
        normal: 1.5,
        relaxed: 1.625,
        loose: 2
      }
    };
  }

  /**
   * Generate spacing theme
   */
  generateSpacingTheme(type) {
    const base = 4;

    return {
      0: '0',
      px: '1px',
      0.5: `${base * 0.5}px`,
      1: `${base}px`,
      2: `${base * 2}px`,
      3: `${base * 3}px`,
      4: `${base * 4}px`,
      5: `${base * 5}px`,
      6: `${base * 6}px`,
      8: `${base * 8}px`,
      10: `${base * 10}px`,
      12: `${base * 12}px`,
      16: `${base * 16}px`,
      20: `${base * 20}px`,
      24: `${base * 24}px`,
      32: `${base * 32}px`
    };
  }

  /**
   * Generate shadow theme
   */
  generateShadowTheme(type) {
    if (type === 'highContrast') {
      return {
        none: 'none',
        sm: '0 0 0 2px currentColor',
        md: '0 0 0 3px currentColor',
        lg: '0 0 0 4px currentColor',
        xl: '0 0 0 5px currentColor'
      };
    }

    const shadowColor = type === 'dark' ? 'rgba(0, 0, 0, 0.5)' : 'rgba(0, 0, 0, 0.1)';

    return {
      none: 'none',
      sm: `0 1px 2px 0 ${shadowColor}`,
      md: `0 4px 6px -1px ${shadowColor}`,
      lg: `0 10px 15px -3px ${shadowColor}`,
      xl: `0 20px 25px -5px ${shadowColor}`,
      '2xl': `0 25px 50px -12px ${shadowColor}`,
      inner: `inset 0 2px 4px 0 ${shadowColor}`
    };
  }

  /**
   * Generate border theme
   */
  generateBorderTheme(type) {
    const borderColor = type === 'dark' ? '#374151' : '#E5E7EB';

    return {
      width: {
        0: '0',
        DEFAULT: '1px',
        2: '2px',
        4: '4px',
        8: '8px'
      },
      style: {
        solid: 'solid',
        dashed: 'dashed',
        dotted: 'dotted',
        double: 'double',
        none: 'none'
      },
      color: {
        DEFAULT: borderColor,
        transparent: 'transparent',
        current: 'currentColor'
      },
      radius: {
        none: '0',
        sm: '2px',
        DEFAULT: '4px',
        md: '6px',
        lg: '8px',
        xl: '12px',
        '2xl': '16px',
        full: '9999px'
      }
    };
  }

  /**
   * Generate animation theme
   */
  generateAnimationTheme(type) {
    const reducedMotion = type === 'highContrast';

    return {
      duration: {
        fast: reducedMotion ? '0ms' : '150ms',
        normal: reducedMotion ? '0ms' : '250ms',
        slow: reducedMotion ? '0ms' : '500ms'
      },
      easing: {
        linear: 'linear',
        in: 'cubic-bezier(0.4, 0, 1, 1)',
        out: 'cubic-bezier(0, 0, 0.2, 1)',
        inOut: 'cubic-bezier(0.4, 0, 0.2, 1)'
      },
      transition: {
        none: 'none',
        all: 'all',
        colors: 'background-color, border-color, color, fill, stroke',
        opacity: 'opacity',
        shadow: 'box-shadow',
        transform: 'transform'
      }
    };
  }

  /**
   * Generate CSS variables from theme
   */
  generateCSSVariables(theme) {
    const variables = {};

    // Color variables
    for (const [key, value] of Object.entries(theme.colors)) {
      variables[`--color-${key}`] = value;
    }

    // Typography variables
    for (const [category, values] of Object.entries(theme.typography)) {
      for (const [key, value] of Object.entries(values)) {
        variables[`--${category}-${key}`] = value;
      }
    }

    // Spacing variables
    for (const [key, value] of Object.entries(theme.spacing)) {
      variables[`--spacing-${key}`] = value;
    }

    // Shadow variables
    for (const [key, value] of Object.entries(theme.shadows)) {
      variables[`--shadow-${key}`] = value;
    }

    return variables;
  }

  /**
   * Get active theme
   */
  getActiveTheme() {
    return this.themes.get(this.activeTheme);
  }

  /**
   * Get all themes
   */
  getAllThemes() {
    return Array.from(this.themes.values());
  }

  /**
   * Export theme configuration
   */
  exportTheme(themeName, format = 'json') {
    const theme = this.themes.get(themeName);

    if (!theme) {
      throw new Error(`Theme '${themeName}' not found`);
    }

    switch (format) {
      case 'json':
        return JSON.stringify(theme, null, 2);
      case 'css':
        return this.exportAsCSS(theme);
      case 'scss':
        return this.exportAsSCSS(theme);
      case 'js':
        return this.exportAsJS(theme);
      default:
        throw new Error(`Unsupported export format: ${format}`);
    }
  }

  /**
   * Helper: Generate theme ID
   */
  generateThemeId(name) {
    return `theme-${name.toLowerCase().replace(/\s+/g, '-')}-${Date.now()}`;
  }

  /**
   * Helper: Detect theme name
   */
  detectThemeName(name) {
    const normalized = name.toLowerCase();

    for (const [type, patterns] of Object.entries(this.detectionPatterns)) {
      for (const pattern of patterns) {
        if (normalized.includes(pattern)) {
          return name;
        }
      }
    }

    return null;
  }

  /**
   * Helper: Detect theme type
   */
  detectThemeType(name) {
    const normalized = name.toLowerCase();

    for (const [type, patterns] of Object.entries(this.detectionPatterns)) {
      for (const pattern of patterns) {
        if (normalized.includes(pattern)) {
          return type;
        }
      }
    }

    return 'custom';
  }

  /**
   * Helper: Group styles by theme
   */
  groupStylesByTheme(styles) {
    const grouped = {};

    for (const style of styles) {
      const themeName = this.extractThemeFromStyleName(style.name);
      if (themeName) {
        if (!grouped[themeName]) {
          grouped[themeName] = [];
        }
        grouped[themeName].push(style);
      }
    }

    return grouped;
  }

  /**
   * Helper: Extract theme from style name
   */
  extractThemeFromStyleName(name) {
    if (!name) return null;

    const normalized = name.toLowerCase();

    // Check for theme indicators in style name
    for (const [type, patterns] of Object.entries(this.detectionPatterns)) {
      for (const pattern of patterns) {
        if (normalized.includes(pattern)) {
          // Extract the theme part from the name
          const parts = name.split(/[\/\-_]/);
          for (const part of parts) {
            if (part.toLowerCase().includes(pattern)) {
              return part;
            }
          }
        }
      }
    }

    return null;
  }

  /**
   * Helper: Detect theme variants
   */
  detectThemeVariants(components) {
    const variants = [];

    for (const component of components) {
      if (component.variantProperties?.theme) {
        for (const theme of component.variantProperties.theme) {
          const existing = variants.find(v => v.name === theme);
          if (existing) {
            existing.components.push(component);
          } else {
            variants.push({
              name: theme,
              type: this.detectThemeType(theme),
              components: [component]
            });
          }
        }
      }
    }

    return variants;
  }

  /**
   * Helper: Extract component colors
   */
  async extractComponentColors(components) {
    const colors = {};

    for (const component of components) {
      if (component.fills) {
        for (const fill of component.fills) {
          if (fill.type === 'SOLID') {
            const colorName = this.generateColorName(component, fill);
            colors[colorName] = this.rgbToHex(fill.color);
          }
        }
      }
    }

    return colors;
  }

  /**
   * Helper: Extract color value from style
   */
  extractColorValue(style) {
    if (style.paints && style.paints[0]) {
      const paint = style.paints[0];
      if (paint.type === 'SOLID') {
        return this.rgbToHex(paint.color);
      }
    }
    return '#000000';
  }

  /**
   * Helper: Normalize color name
   */
  normalizeColorName(name) {
    return name.toLowerCase().replace(/[\s\-_\/]/g, '-');
  }

  /**
   * Helper: Map to semantic colors
   */
  mapToSemanticColors(colors) {
    const semantic = {};

    // Map common color names to semantic names
    const mappings = {
      primary: ['primary', 'brand', 'main'],
      secondary: ['secondary', 'accent'],
      background: ['background', 'bg', 'surface'],
      foreground: ['foreground', 'fg', 'text'],
      error: ['error', 'danger', 'red'],
      warning: ['warning', 'caution', 'yellow', 'orange'],
      success: ['success', 'positive', 'green'],
      info: ['info', 'information', 'blue']
    };

    for (const [colorKey, colorValue] of Object.entries(colors)) {
      const normalized = colorKey.toLowerCase();

      for (const [semanticName, patterns] of Object.entries(mappings)) {
        if (patterns.some(pattern => normalized.includes(pattern))) {
          semantic[semanticName] = colorValue;
          break;
        }
      }
    }

    // Fill in missing semantic colors with defaults
    return { ...this.colorSchemes.light, ...semantic };
  }

  /**
   * Helper: Generate color name
   */
  generateColorName(component, fill) {
    const componentName = component.name || 'color';
    const fillName = fill.name || 'fill';
    return `${componentName}-${fillName}`.toLowerCase().replace(/\s+/g, '-');
  }

  /**
   * Helper: RGB to Hex conversion
   */
  rgbToHex(color) {
    if (!color) return '#000000';

    const r = Math.round((color.r || 0) * 255);
    const g = Math.round((color.g || 0) * 255);
    const b = Math.round((color.b || 0) * 255);

    return '#' + [r, g, b].map(x => {
      const hex = x.toString(16);
      return hex.length === 1 ? '0' + hex : hex;
    }).join('');
  }

  /**
   * Helper: Calculate theme properties
   */
  calculateThemeProperties(theme) {
    return {
      colorCount: Object.keys(theme.colors).length,
      hasTypography: theme.typography && Object.keys(theme.typography).length > 0,
      hasSpacing: theme.spacing && Object.keys(theme.spacing).length > 0,
      hasShadows: theme.shadows && Object.keys(theme.shadows).length > 0,
      isComplete: this.isThemeComplete(theme)
    };
  }

  /**
   * Helper: Check if theme is complete
   */
  isThemeComplete(theme) {
    const requiredColors = ['background', 'foreground', 'primary'];
    return requiredColors.every(color => theme.colors[color]);
  }

  /**
   * Helper: Generate theme tokens
   */
  generateThemeTokens(theme) {
    return {
      colors: theme.colors,
      typography: theme.typography,
      spacing: theme.spacing,
      shadows: theme.shadows,
      borders: theme.borders,
      animations: theme.animations
    };
  }

  /**
   * Helper: Export theme as CSS
   */
  exportAsCSS(theme) {
    let css = `:root {\n`;

    // Add CSS variables
    for (const [key, value] of Object.entries(theme.cssVariables)) {
      css += `  ${key}: ${value};\n`;
    }

    css += '}\n';
    return css;
  }

  /**
   * Helper: Export theme as SCSS
   */
  exportAsSCSS(theme) {
    let scss = '// Theme variables\n';

    // Add SCSS variables
    for (const [key, value] of Object.entries(theme.cssVariables)) {
      const scssKey = key.replace('--', '$');
      scss += `${scssKey}: ${value};\n`;
    }

    return scss;
  }

  /**
   * Helper: Export theme as JS
   */
  exportAsJS(theme) {
    return `export const theme = ${JSON.stringify(theme, null, 2)};`;
  }

  /**
   * Helper: Extract component themes
   */
  async extractComponentThemes(designFile, indicators) {
    const componentThemes = {};

    for (const indicator of indicators) {
      componentThemes[indicator.name] = {};
    }

    return componentThemes;
  }

  /**
   * Helper: Detect theme variables
   */
  async detectThemeVariables(designFile) {
    return {};
  }

  /**
   * Helper: Generate guards for state machine
   */
  generateGuards(component) {
    return {};
  }

  /**
   * Helper: Generate actions for state machine
   */
  generateActions(component) {
    return {};
  }
}

module.exports = ThemeEngine;