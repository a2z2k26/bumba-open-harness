/**
 * nlp-token-inference.js
 * NLP Token Inference
 * Infers design token dependencies from component description
 */

/**
 * Color word to token mappings
 */
const colorMappings = {
  // Primary variations
  primary: 'Primary/500',
  'primary-dark': 'Primary/700',
  'primary-light': 'Primary/300',

  // Secondary variations
  secondary: 'Secondary/500',

  // Semantic colors
  success: 'Success/500',
  error: 'Error/500',
  warning: 'Warning/500',
  info: 'Info/500',

  // Color words
  blue: 'Primary/500',
  red: 'Error/500',
  green: 'Success/500',
  yellow: 'Warning/500',
  orange: 'Warning/600',
  purple: 'Purple/500',
  pink: 'Pink/500',

  // Neutrals
  white: 'White',
  black: 'Black',
  gray: 'Neutral/500',
  grey: 'Neutral/500',
  dark: 'Neutral/900',
  light: 'Neutral/100',

  // Background
  background: 'Background',
  foreground: 'Foreground',
  surface: 'Surface',
  overlay: 'Overlay',

  // Border
  border: 'Border',
  divider: 'Divider'
};

/**
 * Typography word to token mappings
 */
const typographyMappings = {
  // Sizes
  tiny: { fontSize: 'text-xs' },
  small: { fontSize: 'text-sm' },
  medium: { fontSize: 'text-base' },
  large: { fontSize: 'text-lg' },
  huge: { fontSize: 'text-2xl' },

  // Elements
  heading: { fontSize: 'text-xl', fontWeight: 'font-bold' },
  title: { fontSize: 'text-lg', fontWeight: 'font-semibold' },
  subtitle: { fontSize: 'text-sm', fontWeight: 'font-medium' },
  body: { fontSize: 'text-base', fontWeight: 'font-normal' },
  caption: { fontSize: 'text-xs', fontWeight: 'font-normal' },
  label: { fontSize: 'text-sm', fontWeight: 'font-medium' },

  // Weights
  bold: { fontWeight: 'font-bold' },
  semibold: { fontWeight: 'font-semibold' },
  normal: { fontWeight: 'font-normal' },
  light: { fontWeight: 'font-light' }
};

/**
 * Spacing word to token mappings
 */
const spacingMappings = {
  // Descriptive
  tight: '2',
  compact: '4',
  normal: '8',
  loose: '12',
  spacious: '16',
  relaxed: '24',

  // Sizes
  xs: '2',
  sm: '4',
  md: '8',
  lg: '16',
  xl: '24',
  '2xl': '32'
};

/**
 * Border radius word to token mappings
 */
const radiusMappings = {
  sharp: 'none',
  square: 'none',
  rounded: 'md',
  'slightly-rounded': 'sm',
  'very-rounded': 'lg',
  pill: 'full',
  circular: 'full',
  circle: 'full'
};

/**
 * Infer all token dependencies from description
 * @param {string} description - Natural language description
 * @param {string} category - Component category
 * @returns {Object} Token dependencies
 */
function inferTokenDependencies(description, category) {
  const lowercaseDesc = description.toLowerCase();

  const tokens = {
    colors: inferColors(lowercaseDesc, category),
    typography: inferTypography(lowercaseDesc, category),
    spacing: inferSpacing(lowercaseDesc, category),
    borderRadius: inferBorderRadius(lowercaseDesc, category),
    shadows: inferShadows(lowercaseDesc, category)
  };

  // Add defaults based on category
  addCategoryDefaults(tokens, category);

  return tokens;
}

/**
 * Infer color tokens from description
 * @param {string} description - Lowercase description
 * @param {string} category - Component category
 * @returns {Array} Color tokens
 */
function inferColors(description, category) {
  const colors = [];
  const colorSet = new Set();

  // Check for explicit color mentions
  for (const [word, token] of Object.entries(colorMappings)) {
    if (description.includes(word) && !colorSet.has(token)) {
      colors.push({ name: token, source: word });
      colorSet.add(token);
    }
  }

  // Add category defaults if no colors found
  if (colors.length === 0) {
    const defaults = getCategoryColorDefaults(category);
    defaults.forEach(token => {
      if (!colorSet.has(token)) {
        colors.push({ name: token, source: 'default' });
        colorSet.add(token);
      }
    });
  }

  return colors;
}

/**
 * Get default colors for category
 * @param {string} category - Component category
 * @returns {Array} Default color tokens
 */
function getCategoryColorDefaults(category) {
  const defaults = {
    button: ['Primary/500', 'White', 'Primary/700'],
    card: ['Background', 'Foreground', 'Border'],
    input: ['Background', 'Border', 'Foreground', 'Primary/500'],
    navigation: ['Background', 'Foreground', 'Primary/500'],
    feedback: ['Info/500', 'Success/500', 'Error/500', 'Warning/500'],
    overlay: ['Background', 'Overlay', 'Foreground'],
    default: ['Primary/500', 'Background', 'Foreground']
  };

  return defaults[category] || defaults.default;
}

/**
 * Infer typography tokens
 * @param {string} description - Lowercase description
 * @param {string} category - Component category
 * @returns {Array} Typography tokens
 */
function inferTypography(description, category) {
  const typography = [];
  const typographySet = new Set();

  // Check for explicit typography mentions
  for (const [word, tokens] of Object.entries(typographyMappings)) {
    if (description.includes(word)) {
      Object.values(tokens).forEach(token => {
        if (!typographySet.has(token)) {
          typography.push({ name: token, source: word });
          typographySet.add(token);
        }
      });
    }
  }

  // Add category defaults if minimal typography found
  if (typography.length < 2) {
    const defaults = getCategoryTypographyDefaults(category);
    defaults.forEach(token => {
      if (!typographySet.has(token)) {
        typography.push({ name: token, source: 'default' });
        typographySet.add(token);
      }
    });
  }

  return typography;
}

/**
 * Get default typography for category
 * @param {string} category - Component category
 * @returns {Array} Default typography tokens
 */
function getCategoryTypographyDefaults(category) {
  const defaults = {
    button: ['text-sm', 'font-medium'],
    card: ['text-lg', 'font-semibold', 'text-sm', 'font-normal'],
    input: ['text-sm', 'font-normal'],
    navigation: ['text-sm', 'font-medium'],
    feedback: ['text-sm', 'font-medium'],
    default: ['text-base', 'font-normal']
  };

  return defaults[category] || defaults.default;
}

/**
 * Infer spacing tokens
 * @param {string} description - Lowercase description
 * @param {string} category - Component category
 * @returns {Array} Spacing tokens
 */
function inferSpacing(description, category) {
  const spacing = [];
  const spacingSet = new Set();

  // Check for explicit spacing mentions
  for (const [word, token] of Object.entries(spacingMappings)) {
    if (description.includes(word) && !spacingSet.has(token)) {
      spacing.push({ name: token, source: word });
      spacingSet.add(token);
    }
  }

  // Add category defaults
  const defaults = getCategorySpacingDefaults(category);
  defaults.forEach(token => {
    if (!spacingSet.has(token)) {
      spacing.push({ name: token, source: 'default' });
      spacingSet.add(token);
    }
  });

  return spacing;
}

/**
 * Get default spacing for category
 * @param {string} category - Component category
 * @returns {Array} Default spacing tokens
 */
function getCategorySpacingDefaults(category) {
  const defaults = {
    button: ['4', '8', '16'],
    card: ['16', '24'],
    input: ['8', '12'],
    navigation: ['8', '16'],
    default: ['8', '16']
  };

  return defaults[category] || defaults.default;
}

/**
 * Infer border radius tokens
 * @param {string} description - Lowercase description
 * @param {string} category - Component category
 * @returns {Array} Border radius tokens
 */
function inferBorderRadius(description, category) {
  const radii = [];

  // Check for explicit radius mentions
  for (const [word, token] of Object.entries(radiusMappings)) {
    if (description.includes(word)) {
      radii.push({ name: token, source: word });
    }
  }

  // Add default if none found
  if (radii.length === 0) {
    radii.push({ name: 'md', source: 'default' });
  }

  return radii;
}

/**
 * Infer shadow tokens
 * @param {string} description - Lowercase description
 * @param {string} category - Component category
 * @returns {Array} Shadow tokens
 */
function inferShadows(description, category) {
  const shadows = [];

  // Shadow-related words
  const shadowWords = ['shadow', 'elevated', 'floating', 'raised', 'lifted', 'depth'];

  for (const word of shadowWords) {
    if (description.includes(word)) {
      shadows.push({ name: 'shadow-md', source: word });
      break;
    }
  }

  // Card and overlay typically have shadows
  if (shadows.length === 0 && ['card', 'overlay'].includes(category)) {
    shadows.push({ name: 'shadow-sm', source: 'category-default' });
  }

  return shadows;
}

/**
 * Add category-specific defaults to tokens
 * @param {Object} tokens - Token collections
 * @param {string} category - Component category
 */
function addCategoryDefaults(tokens, category) {
  // Ensure minimum tokens for each category
  const minimums = {
    colors: 2,
    typography: 2,
    spacing: 2,
    borderRadius: 1
  };

  for (const [tokenType, minimum] of Object.entries(minimums)) {
    if (tokens[tokenType].length < minimum) {
      // Already handled in individual inference functions
    }
  }
}

/**
 * Format tokens for output
 * @param {Object} tokens - Token collections with source info
 * @returns {Object} Simplified token arrays
 */
function formatTokensForOutput(tokens) {
  return {
    colors: tokens.colors.map(t => t.name),
    typography: tokens.typography.map(t => t.name),
    spacing: tokens.spacing.map(t => t.name),
    borderRadius: tokens.borderRadius.map(t => t.name),
    shadows: tokens.shadows.map(t => t.name)
  };
}

module.exports = {
  inferTokenDependencies,
  inferColors,
  inferTypography,
  inferSpacing,
  inferBorderRadius,
  inferShadows,
  formatTokensForOutput,
  addCategoryDefaults,
  getCategoryColorDefaults,
  getCategoryTypographyDefaults,
  getCategorySpacingDefaults,
  colorMappings,
  typographyMappings,
  spacingMappings,
  radiusMappings
};
