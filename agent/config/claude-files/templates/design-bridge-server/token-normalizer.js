/**
 * Token Normalizer
 * Standardizes and normalizes design tokens across different formats
 */

class TokenNormalizer {
  constructor() {
    this.normalizationRules = {
      colors: this.normalizeColor.bind(this),
      spacing: this.normalizeSpacing.bind(this),
      typography: this.normalizeTypography.bind(this),
      effects: this.normalizeEffect.bind(this)
    };
  }

  /**
   * Normalize a collection of tokens
   */
  normalize(tokens) {
    const normalized = {};

    for (const [category, categoryTokens] of Object.entries(tokens)) {
      if (this.normalizationRules[category]) {
        normalized[category] = {};
        for (const [name, value] of Object.entries(categoryTokens)) {
          normalized[category][name] = this.normalizationRules[category](value, name);
        }
      } else {
        // Pass through unchanged if no normalization rule
        normalized[category] = categoryTokens;
      }
    }

    return normalized;
  }

  /**
   * Normalize color values
   */
  normalizeColor(value, name) {
    if (typeof value === 'string') {
      // Convert to uppercase hex
      if (value.startsWith('#')) {
        return value.toUpperCase();
      }
      // Convert rgb/rgba to hex if possible
      if (value.startsWith('rgb')) {
        return this.rgbToHex(value);
      }
      return value;
    }

    if (typeof value === 'object' && value.value) {
      return this.normalizeColor(value.value, name);
    }

    return value;
  }

  /**
   * Normalize spacing values
   */
  normalizeSpacing(value, name) {
    if (typeof value === 'string') {
      // Ensure px units
      if (/^\d+$/.test(value)) {
        return `${value}px`;
      }
      return value;
    }

    if (typeof value === 'number') {
      return `${value}px`;
    }

    if (typeof value === 'object' && value.value) {
      return this.normalizeSpacing(value.value, name);
    }

    return value;
  }

  /**
   * Normalize typography values
   */
  normalizeTypography(value, name) {
    if (typeof value === 'object') {
      const normalized = { ...value };

      // Normalize font size
      if (normalized.fontSize) {
        if (typeof normalized.fontSize === 'number') {
          normalized.fontSize = `${normalized.fontSize}px`;
        } else if (/^\d+$/.test(normalized.fontSize)) {
          normalized.fontSize = `${normalized.fontSize}px`;
        }
      }

      // Normalize line height
      if (normalized.lineHeight) {
        if (typeof normalized.lineHeight === 'number' && normalized.lineHeight < 3) {
          // Assume it's a multiplier
          normalized.lineHeight = String(normalized.lineHeight);
        } else if (typeof normalized.lineHeight === 'number') {
          normalized.lineHeight = `${normalized.lineHeight}px`;
        }
      }

      // Normalize font weight
      if (normalized.fontWeight) {
        if (typeof normalized.fontWeight === 'string') {
          const weightMap = {
            'thin': 100,
            'light': 300,
            'regular': 400,
            'normal': 400,
            'medium': 500,
            'semibold': 600,
            'bold': 700,
            'heavy': 800,
            'black': 900
          };
          if (weightMap[normalized.fontWeight.toLowerCase()]) {
            normalized.fontWeight = weightMap[normalized.fontWeight.toLowerCase()];
          }
        }
      }

      return normalized;
    }

    return value;
  }

  /**
   * Normalize effect values
   */
  normalizeEffect(value, name) {
    if (typeof value === 'string') {
      // Normalize shadow values
      if (value.includes('box-shadow:')) {
        return value.replace('box-shadow:', '').trim();
      }
      return value;
    }

    if (typeof value === 'object' && value.value) {
      return this.normalizeEffect(value.value, name);
    }

    return value;
  }

  /**
   * Convert RGB/RGBA to hex
   */
  rgbToHex(rgb) {
    const match = rgb.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (match) {
      const r = parseInt(match[1]);
      const g = parseInt(match[2]);
      const b = parseInt(match[3]);
      return '#' + [r, g, b].map(x => {
        const hex = x.toString(16);
        return hex.length === 1 ? '0' + hex : hex;
      }).join('').toUpperCase();
    }
    return rgb;
  }

  /**
   * Convert hex to RGB
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
   * Normalize naming convention
   */
  normalizeName(name, convention = 'kebab-case') {
    switch (convention) {
      case 'kebab-case':
        return name.replace(/([A-Z])/g, '-$1').toLowerCase().replace(/^-/, '');
      case 'camelCase':
        return name.replace(/-([a-z])/g, (g) => g[1].toUpperCase());
      case 'snake_case':
        return name.replace(/([A-Z])/g, '_$1').toLowerCase().replace(/^_/, '');
      default:
        return name;
    }
  }

  /**
   * Validate normalized tokens
   */
  validate(tokens) {
    const issues = [];

    // Check for required categories
    const requiredCategories = ['colors', 'typography', 'spacing'];
    for (const category of requiredCategories) {
      if (!tokens[category] || Object.keys(tokens[category]).length === 0) {
        issues.push({
          type: 'warning',
          category,
          message: `Missing or empty ${category} category`
        });
      }
    }

    return {
      valid: issues.filter(i => i.type === 'error').length === 0,
      issues
    };
  }
}

module.exports = TokenNormalizer;