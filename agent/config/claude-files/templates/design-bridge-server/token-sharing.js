/**
 * Token Sharing Module
 * Maps source-specific token references to unified registry tokens
 */

const fs = require('fs');
const path = require('path');

// Token alias mappings by source type
const TOKEN_ALIASES = {
  // CSS variable mappings (ShadCN)
  css: {
    '--primary': 'Primary/500',
    '--primary-foreground': 'Primary/foreground',
    '--secondary': 'Secondary/500',
    '--secondary-foreground': 'Secondary/foreground',
    '--background': 'Neutral/background',
    '--foreground': 'Neutral/foreground',
    '--muted': 'Neutral/200',
    '--muted-foreground': 'Neutral/500',
    '--accent': 'Accent/500',
    '--accent-foreground': 'Accent/foreground',
    '--destructive': 'Destructive/500',
    '--destructive-foreground': 'Destructive/foreground',
    '--border': 'Border/default',
    '--input': 'Input/border',
    '--ring': 'Ring/default',
    '--radius': 'BorderRadius/default'
  },

  // Natural language mappings (NLP)
  natural: {
    'primary': 'Primary/500',
    'secondary': 'Secondary/500',
    'blue': 'Primary/500',
    'red': 'Destructive/500',
    'green': 'Success/500',
    'yellow': 'Warning/500',
    'gray': 'Neutral/500',
    'white': 'Neutral/0',
    'black': 'Neutral/900',
    'small': 'Spacing/sm',
    'medium': 'Spacing/md',
    'large': 'Spacing/lg',
    'rounded': 'BorderRadius/default',
    'bold': 'Typography/weight/bold',
    'italic': 'Typography/style/italic'
  },

  // Figma style ID patterns
  figma: {
    // Pattern: 'S:{styleId}' -> look up in Figma styles
    // These are resolved dynamically from Figma file
  }
};

// Token category mapping
const TOKEN_CATEGORIES = {
  colors: ['Primary', 'Secondary', 'Neutral', 'Accent', 'Destructive', 'Success', 'Warning', 'Border', 'Ring'],
  typography: ['Typography', 'Font'],
  spacing: ['Spacing', 'Gap', 'Padding', 'Margin'],
  effects: ['Shadow', 'Blur', 'Effect'],
  borderRadius: ['BorderRadius', 'Radius', 'Corner']
};

class TokenSharingManager {
  constructor(projectRoot) {
    this.projectRoot = projectRoot;
    this.tokensDir = path.join(projectRoot, '.design', 'tokens');
    this.customAliases = {};
    this.loadedTokens = null;
  }

  /**
   * Load all tokens from registry
   */
  loadTokens() {
    if (this.loadedTokens) return this.loadedTokens;

    const tokens = {
      colors: {},
      typography: {},
      spacing: {},
      effects: {},
      borderRadius: {}
    };

    const tokenFiles = {
      colors: 'colors.json',
      typography: 'typography.json',
      spacing: 'spacing.json',
      effects: 'effects.json',
      borderRadius: 'borderRadius.json'
    };

    for (const [category, filename] of Object.entries(tokenFiles)) {
      const filepath = path.join(this.tokensDir, filename);
      if (fs.existsSync(filepath)) {
        try {
          tokens[category] = JSON.parse(fs.readFileSync(filepath, 'utf-8'));
        } catch (err) {
          console.warn(`[token-sharing] Failed to load ${filename}:`, err.message);
        }
      }
    }

    this.loadedTokens = tokens;
    return tokens;
  }

  /**
   * Add custom alias mapping
   */
  addAlias(sourceRef, targetToken) {
    this.customAliases[sourceRef] = targetToken;
  }

  /**
   * Load custom aliases from project config
   */
  loadCustomAliases() {
    const aliasPath = path.join(this.tokensDir, 'aliases.json');
    if (fs.existsSync(aliasPath)) {
      try {
        this.customAliases = JSON.parse(fs.readFileSync(aliasPath, 'utf-8'));
      } catch (err) {
        console.warn('[token-sharing] Failed to load aliases.json:', err.message);
      }
    }
  }

  /**
   * Save custom aliases to project config
   */
  saveCustomAliases() {
    const aliasPath = path.join(this.tokensDir, 'aliases.json');

    // Ensure directory exists
    if (!fs.existsSync(this.tokensDir)) {
      fs.mkdirSync(this.tokensDir, { recursive: true });
    }

    fs.writeFileSync(aliasPath, JSON.stringify(this.customAliases, null, 2));
  }

  /**
   * Resolve a source-specific token reference to registry token
   * @param {string} sourceRef - The source-specific reference
   * @param {string} sourceType - Source type (css, natural, figma, manual)
   * @returns {object} - { resolved: string, exists: boolean, category: string }
   */
  resolveToken(sourceRef, sourceType) {
    // Check custom aliases first
    if (this.customAliases[sourceRef]) {
      return this.validateToken(this.customAliases[sourceRef]);
    }

    // Check source-specific aliases
    const sourceAliases = TOKEN_ALIASES[sourceType] || {};
    if (sourceAliases[sourceRef]) {
      return this.validateToken(sourceAliases[sourceRef]);
    }

    // Check if it's already a valid token reference
    if (this.isValidTokenFormat(sourceRef)) {
      return this.validateToken(sourceRef);
    }

    // Try to auto-resolve based on naming patterns
    const autoResolved = this.autoResolve(sourceRef);
    if (autoResolved) {
      return this.validateToken(autoResolved);
    }

    // Return unresolved
    return {
      resolved: sourceRef,
      exists: false,
      category: null,
      suggestion: this.suggestToken(sourceRef)
    };
  }

  /**
   * Check if token reference format is valid
   */
  isValidTokenFormat(ref) {
    // Format: Category/Path or Category/Subcategory/Path
    return /^[A-Za-z]+\/[A-Za-z0-9\/]+$/.test(ref);
  }

  /**
   * Validate if token exists in registry
   */
  validateToken(tokenRef) {
    const tokens = this.loadTokens();
    const parts = tokenRef.split('/');
    const category = this.findCategory(parts[0]);

    if (!category) {
      return { resolved: tokenRef, exists: false, category: null };
    }

    // Navigate to token value
    let current = tokens[category];
    for (const part of parts) {
      if (current && current[part]) {
        current = current[part];
      } else if (current && current.value !== undefined) {
        // Found token with value
        break;
      } else {
        return { resolved: tokenRef, exists: false, category };
      }
    }

    return { resolved: tokenRef, exists: true, category };
  }

  /**
   * Find category for token prefix
   */
  findCategory(prefix) {
    for (const [category, prefixes] of Object.entries(TOKEN_CATEGORIES)) {
      if (prefixes.some(p => p.toLowerCase() === prefix.toLowerCase())) {
        return category;
      }
    }
    return null;
  }

  /**
   * Auto-resolve common patterns
   */
  autoResolve(sourceRef) {
    // Try common transformations
    const transforms = [
      // camelCase to Path: primaryColor -> Primary/color
      (ref) => {
        const match = ref.match(/^([a-z]+)([A-Z][a-z]+)$/);
        if (match) {
          return `${match[1].charAt(0).toUpperCase() + match[1].slice(1)}/${match[2].toLowerCase()}`;
        }
        return null;
      },
      // kebab-case to Path: primary-color -> Primary/color
      (ref) => {
        const parts = ref.split('-');
        if (parts.length >= 2) {
          return parts.map((p, i) => i === 0 ? p.charAt(0).toUpperCase() + p.slice(1) : p).join('/');
        }
        return null;
      },
      // Scale values: primary500 -> Primary/500
      (ref) => {
        const match = ref.match(/^([a-zA-Z]+)(\d+)$/);
        if (match) {
          return `${match[1].charAt(0).toUpperCase() + match[1].slice(1)}/${match[2]}`;
        }
        return null;
      }
    ];

    for (const transform of transforms) {
      const result = transform(sourceRef);
      if (result && this.validateToken(result).exists) {
        return result;
      }
    }

    return null;
  }

  /**
   * Suggest similar tokens for unresolved reference
   */
  suggestToken(sourceRef) {
    const tokens = this.loadTokens();
    const suggestions = [];
    const lowerRef = sourceRef.toLowerCase();

    // Search all tokens for similar names
    const searchTokens = (obj, prefix = '') => {
      for (const [key, value] of Object.entries(obj)) {
        const fullPath = prefix ? `${prefix}/${key}` : key;
        if (key.toLowerCase().includes(lowerRef) || lowerRef.includes(key.toLowerCase())) {
          suggestions.push(fullPath);
        }
        if (typeof value === 'object' && value !== null && !value.value) {
          searchTokens(value, fullPath);
        }
      }
    };

    for (const category of Object.values(tokens)) {
      searchTokens(category);
    }

    return suggestions.slice(0, 5);
  }

  /**
   * Resolve all token dependencies for a component
   * @param {object} tokenDependencies - Component's token dependencies
   * @param {string} sourceType - Source type
   * @returns {object} - Resolved dependencies with validation status
   */
  resolveComponentTokens(tokenDependencies, sourceType) {
    const resolved = {};
    const missing = [];

    for (const [category, refs] of Object.entries(tokenDependencies || {})) {
      resolved[category] = [];

      for (const ref of refs) {
        const result = this.resolveToken(ref, sourceType);
        resolved[category].push(result.resolved);

        if (!result.exists) {
          missing.push({
            original: ref,
            resolved: result.resolved,
            category,
            suggestions: result.suggestion
          });
        }
      }
    }

    return {
      resolved,
      missing,
      valid: missing.length === 0
    };
  }

  /**
   * Create token mapping report for a component
   */
  generateTokenReport(componentName, tokenDependencies, sourceType) {
    const result = this.resolveComponentTokens(tokenDependencies, sourceType);

    const lines = [
      `Token Mapping Report: ${componentName}`,
      `Source Type: ${sourceType}`,
      `Status: ${result.valid ? 'All tokens resolved' : `${result.missing.length} unresolved tokens`}`,
      '',
      'Resolved Tokens:',
    ];

    for (const [category, tokens] of Object.entries(result.resolved)) {
      if (tokens.length > 0) {
        lines.push(`  ${category}: ${tokens.join(', ')}`);
      }
    }

    if (result.missing.length > 0) {
      lines.push('', 'Unresolved Tokens:');
      for (const missing of result.missing) {
        lines.push(`  - ${missing.original} (${missing.category})`);
        if (missing.suggestions.length > 0) {
          lines.push(`    Suggestions: ${missing.suggestions.join(', ')}`);
        }
      }
    }

    return lines.join('\n');
  }

  /**
   * Clear cached tokens
   */
  clearCache() {
    this.loadedTokens = null;
  }

  /**
   * Get all aliases (built-in + custom)
   */
  getAllAliases() {
    return {
      css: { ...TOKEN_ALIASES.css },
      natural: { ...TOKEN_ALIASES.natural },
      figma: { ...TOKEN_ALIASES.figma },
      custom: { ...this.customAliases }
    };
  }

  /**
   * Get token categories
   */
  getCategories() {
    return { ...TOKEN_CATEGORIES };
  }
}

// Source-type detection from source metadata
function detectSourceType(source) {
  if (!source || !source.type) return 'manual';

  switch (source.type) {
    case 'figma-mcp':
    case 'figma-plugin':
      return 'figma';
    case 'shadcn':
      return 'css';
    case 'nlp-prompt':
      return 'natural';
    case 'manual':
    default:
      return 'manual';
  }
}

module.exports = {
  TokenSharingManager,
  TOKEN_ALIASES,
  TOKEN_CATEGORIES,
  detectSourceType
};
