/**
 * nlp-variant-generator.js
 * NLP Variant Generator
 * Generates component variants from natural language descriptions
 */

/**
 * Common variant patterns
 */
const variantPatterns = {
  appearance: {
    pattern: /\b(primary|secondary|tertiary|outline[d]?|ghost|link|destructive|danger|success|warning|info)\b/gi,
    type: 'variant'
  },
  size: {
    pattern: /\b(xs|sm|small|md|medium|lg|large|xl|extra.?large|icon)\b/gi,
    type: 'size'
  },
  state: {
    pattern: /\b(default|hover|active|pressed|focus|disabled|loading|error|success)\b/gi,
    type: 'state'
  },
  style: {
    pattern: /\b(filled|outlined|contained|text|elevated|flat)\b/gi,
    type: 'style'
  }
};

/**
 * Generate variants from description
 * @param {string} description - Natural language description
 * @param {Array} explicitVariants - Explicitly requested variants
 * @returns {Object} Variant definitions
 */
function generateVariants(description, explicitVariants = []) {
  const variants = {};

  // Parse implicit variants from description
  const implicitVariants = parseVariantsFromDescription(description);

  // Merge with explicit variants
  const allVariants = mergeVariants(implicitVariants, explicitVariants);

  // Generate variant definitions
  for (const [variantType, values] of Object.entries(allVariants)) {
    if (values.length > 0) {
      variants[variantType] = generateVariantDefinitions(variantType, values);
    }
  }

  return variants;
}

/**
 * Parse variants from description
 */
function parseVariantsFromDescription(description) {
  const found = {
    variant: [],
    size: [],
    state: []
  };

  for (const [category, config] of Object.entries(variantPatterns)) {
    const matches = description.match(config.pattern) || [];
    const unique = [...new Set(matches.map(m => normalizeVariantName(m)))];

    if (config.type === 'variant' || config.type === 'style') {
      found.variant.push(...unique);
    } else if (config.type === 'size') {
      found.size.push(...unique.map(normalizeSizeName));
    } else if (config.type === 'state') {
      found.state.push(...unique);
    }
  }

  return found;
}

/**
 * Normalize variant name
 */
function normalizeVariantName(name) {
  const normalized = name.toLowerCase();

  // Map similar names
  const mappings = {
    danger: 'destructive',
    filled: 'primary',
    contained: 'primary',
    text: 'ghost',
    flat: 'ghost',
    outlined: 'outline'
  };

  return mappings[normalized] || normalized;
}

/**
 * Normalize size name
 */
function normalizeSizeName(name) {
  const normalized = name.toLowerCase().replace(/[^a-z]/g, '');

  const mappings = {
    small: 'sm',
    medium: 'md',
    large: 'lg',
    extralarge: 'xl'
  };

  return mappings[normalized] || normalized;
}

/**
 * Merge implicit and explicit variants
 */
function mergeVariants(implicit, explicit) {
  const result = { ...implicit };

  explicit.forEach(variant => {
    const normalized = normalizeVariantName(variant);

    // Determine type
    if (['sm', 'md', 'lg', 'xl', 'xs', 'icon'].includes(normalized)) {
      if (!result.size.includes(normalized)) {
        result.size.push(normalized);
      }
    } else {
      if (!result.variant.includes(normalized)) {
        result.variant.push(normalized);
      }
    }
  });

  return result;
}

/**
 * Generate variant definitions
 */
function generateVariantDefinitions(variantType, values) {
  const definitions = {};

  values.forEach(value => {
    definitions[value] = {
      properties: { [variantType]: value },
      styles: getVariantStyles(variantType, value),
      tokenOverrides: getVariantTokenOverrides(variantType, value)
    };
  });

  return definitions;
}

/**
 * Get styles for variant
 */
function getVariantStyles(variantType, value) {
  if (variantType === 'variant') {
    return getAppearanceStyles(value);
  }
  if (variantType === 'size') {
    return getSizeStyles(value);
  }
  if (variantType === 'state') {
    return getStateStyles(value);
  }
  return {};
}

/**
 * Get appearance variant styles
 */
function getAppearanceStyles(variant) {
  const styles = {
    primary: {
      backgroundColor: 'var(--primary)',
      color: 'var(--primary-foreground)',
      border: 'none'
    },
    secondary: {
      backgroundColor: 'var(--secondary)',
      color: 'var(--secondary-foreground)',
      border: 'none'
    },
    destructive: {
      backgroundColor: 'var(--destructive)',
      color: 'var(--destructive-foreground)',
      border: 'none'
    },
    outline: {
      backgroundColor: 'transparent',
      color: 'var(--primary)',
      border: '1px solid var(--border)'
    },
    ghost: {
      backgroundColor: 'transparent',
      color: 'var(--foreground)',
      border: 'none'
    },
    link: {
      backgroundColor: 'transparent',
      color: 'var(--primary)',
      border: 'none',
      textDecoration: 'underline'
    }
  };

  return styles[variant] || styles.primary;
}

/**
 * Get size variant styles
 */
function getSizeStyles(size) {
  const styles = {
    xs: { height: '24px', padding: '0 8px', fontSize: '12px' },
    sm: { height: '32px', padding: '0 12px', fontSize: '14px' },
    md: { height: '40px', padding: '0 16px', fontSize: '14px' },
    lg: { height: '48px', padding: '0 24px', fontSize: '16px' },
    xl: { height: '56px', padding: '0 32px', fontSize: '18px' },
    icon: { height: '40px', width: '40px', padding: '0' }
  };

  return styles[size] || styles.md;
}

/**
 * Get state styles
 */
function getStateStyles(state) {
  const styles = {
    default: {},
    hover: { filter: 'brightness(0.95)' },
    active: { filter: 'brightness(0.9)' },
    pressed: { transform: 'scale(0.98)' },
    focus: { outline: '2px solid var(--ring)', outlineOffset: '2px' },
    disabled: { opacity: '0.5', pointerEvents: 'none' },
    loading: { opacity: '0.7', pointerEvents: 'none' },
    error: { borderColor: 'var(--destructive)' },
    success: { borderColor: 'var(--success)' }
  };

  return styles[state] || {};
}

/**
 * Get token overrides for variant
 */
function getVariantTokenOverrides(variantType, value) {
  if (variantType === 'variant') {
    const overrides = {
      primary: { backgroundColor: 'Primary/500', textColor: 'White' },
      secondary: { backgroundColor: 'Secondary/500', textColor: 'White' },
      destructive: { backgroundColor: 'Error/500', textColor: 'White' },
      outline: { borderColor: 'Primary/500', textColor: 'Primary/500' },
      ghost: { textColor: 'Foreground' },
      link: { textColor: 'Primary/500' }
    };
    return overrides[value] || {};
  }

  if (variantType === 'size') {
    const overrides = {
      xs: { padding: '2', fontSize: 'text-xs' },
      sm: { padding: '4', fontSize: 'text-sm' },
      md: { padding: '8', fontSize: 'text-base' },
      lg: { padding: '12', fontSize: 'text-lg' },
      xl: { padding: '16', fontSize: 'text-xl' }
    };
    return overrides[value] || {};
  }

  return {};
}

/**
 * Generate compound variants
 */
function generateCompoundVariants(variants) {
  const compounds = [];

  // Example: size + variant combinations that need special handling
  if (variants.variant && variants.size) {
    // Icon size with any variant needs square dimensions
    if (variants.size.icon) {
      Object.keys(variants.variant).forEach(v => {
        compounds.push({
          conditions: { variant: v, size: 'icon' },
          styles: { width: '40px', height: '40px', padding: '0' }
        });
      });
    }
  }

  return compounds;
}

/**
 * Generate default variants
 */
function generateDefaultVariants(variants) {
  const defaults = {};

  if (variants.variant) {
    defaults.variant = 'primary';
  }

  if (variants.size) {
    defaults.size = variants.size.md ? 'md' : Object.keys(variants.size)[0];
  }

  return defaults;
}

module.exports = {
  generateVariants,
  parseVariantsFromDescription,
  generateVariantDefinitions,
  getVariantStyles,
  getVariantTokenOverrides,
  generateCompoundVariants,
  generateDefaultVariants,
  variantPatterns
};
