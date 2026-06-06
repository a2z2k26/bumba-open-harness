/**
 * shadcn-token-extractor.js
 * Extract token dependencies from Tailwind classes and CSS variables
 */

/**
 * Extract all token dependencies from component source code
 * @param {string} sourceCode - Component source code
 * @returns {Object} Token dependencies by category
 */
function extractTokenDependencies(sourceCode) {
  if (!sourceCode) {
    return createEmptyTokens();
  }

  return {
    colors: extractColorTokens(sourceCode),
    typography: extractTypographyTokens(sourceCode),
    spacing: extractSpacingTokens(sourceCode),
    effects: extractEffectTokens(sourceCode),
    borderRadius: extractBorderRadiusTokens(sourceCode),
    cssVariables: extractCssVariables(sourceCode)
  };
}

/**
 * Create empty token structure
 * @returns {Object} Empty token dependencies
 */
function createEmptyTokens() {
  return {
    colors: [],
    typography: [],
    spacing: [],
    effects: [],
    borderRadius: [],
    cssVariables: []
  };
}

/**
 * Extract color tokens from Tailwind classes
 * @param {string} sourceCode - Source code
 * @returns {Array} Color tokens
 */
function extractColorTokens(sourceCode) {
  const colors = new Set();

  // Background colors: bg-{color} including compound names
  const bgMatches = sourceCode.matchAll(/\bbg-([a-z]+(?:-[a-z0-9]+)*(?:\/\d+)?)/g);
  for (const match of bgMatches) {
    colors.add(`bg-${match[1]}`);
  }

  // Text colors: text-{color} including compound names like primary-foreground
  const textMatches = sourceCode.matchAll(/\btext-([a-z]+(?:-[a-z0-9]+)*(?:\/\d+)?)/g);
  for (const match of textMatches) {
    // Filter out text sizing (text-sm, text-lg, etc.)
    if (!['xs', 'sm', 'base', 'lg', 'xl', '2xl', '3xl', '4xl', '5xl'].includes(match[1])) {
      colors.add(`text-${match[1]}`);
    }
  }

  // Border colors: border-{color}
  const borderMatches = sourceCode.matchAll(/\bborder-([a-z]+-?\d*(?:\/\d+)?)/g);
  for (const match of borderMatches) {
    // Filter out border widths
    if (!['0', '2', '4', '8', 't', 'r', 'b', 'l', 'x', 'y'].includes(match[1])) {
      colors.add(`border-${match[1]}`);
    }
  }

  // Ring colors: ring-{color}
  const ringMatches = sourceCode.matchAll(/\bring-([a-z]+-?\d*(?:\/\d+)?)/g);
  for (const match of ringMatches) {
    if (!/^\d+$/.test(match[1]) && !['inset', 'offset'].includes(match[1])) {
      colors.add(`ring-${match[1]}`);
    }
  }

  // Fill/stroke colors
  const fillMatches = sourceCode.matchAll(/\bfill-([a-z]+-?\d*)/g);
  for (const match of fillMatches) {
    colors.add(`fill-${match[1]}`);
  }

  const strokeMatches = sourceCode.matchAll(/\bstroke-([a-z]+-?\d*)/g);
  for (const match of strokeMatches) {
    colors.add(`stroke-${match[1]}`);
  }

  return Array.from(colors).sort();
}

/**
 * Extract typography tokens from Tailwind classes
 * @param {string} sourceCode - Source code
 * @returns {Array} Typography tokens
 */
function extractTypographyTokens(sourceCode) {
  const typography = new Set();

  // Font sizes: text-{size}
  const sizeMatches = sourceCode.matchAll(/\btext-(xs|sm|base|lg|xl|2xl|3xl|4xl|5xl|6xl|7xl|8xl|9xl)/g);
  for (const match of sizeMatches) {
    typography.add(`text-${match[1]}`);
  }

  // Font weights: font-{weight}
  const weightMatches = sourceCode.matchAll(/\bfont-(thin|extralight|light|normal|medium|semibold|bold|extrabold|black)/g);
  for (const match of weightMatches) {
    typography.add(`font-${match[1]}`);
  }

  // Font families: font-{family}
  const familyMatches = sourceCode.matchAll(/\bfont-(sans|serif|mono)/g);
  for (const match of familyMatches) {
    typography.add(`font-${match[1]}`);
  }

  // Line heights: leading-{value}
  const leadingMatches = sourceCode.matchAll(/\bleading-(\d+|none|tight|snug|normal|relaxed|loose)/g);
  for (const match of leadingMatches) {
    typography.add(`leading-${match[1]}`);
  }

  // Letter spacing: tracking-{value}
  const trackingMatches = sourceCode.matchAll(/\btracking-(tighter|tight|normal|wide|wider|widest)/g);
  for (const match of trackingMatches) {
    typography.add(`tracking-${match[1]}`);
  }

  return Array.from(typography).sort();
}

/**
 * Extract spacing tokens from Tailwind classes
 * @param {string} sourceCode - Source code
 * @returns {Array} Spacing tokens
 */
function extractSpacingTokens(sourceCode) {
  const spacing = new Set();

  // Padding: p{side}-{value}
  const paddingMatches = sourceCode.matchAll(/\bp([xytblr]?)-(\d+(?:\.\d+)?|\[[\d.]+(?:px|rem|em)\])/g);
  for (const match of paddingMatches) {
    spacing.add(`p${match[1]}-${match[2]}`);
  }

  // Margin: m{side}-{value}
  const marginMatches = sourceCode.matchAll(/\bm([xytblr]?)-(\d+(?:\.\d+)?|\[[\d.]+(?:px|rem|em)\])/g);
  for (const match of marginMatches) {
    spacing.add(`m${match[1]}-${match[2]}`);
  }

  // Gap: gap-{value}
  const gapMatches = sourceCode.matchAll(/\bgap-(\d+(?:\.\d+)?|\[[\d.]+(?:px|rem|em)\])/g);
  for (const match of gapMatches) {
    spacing.add(`gap-${match[1]}`);
  }

  // Space between: space-{axis}-{value}
  const spaceMatches = sourceCode.matchAll(/\bspace-([xy])-(\d+(?:\.\d+)?)/g);
  for (const match of spaceMatches) {
    spacing.add(`space-${match[1]}-${match[2]}`);
  }

  // Width/Height: w-{value}, h-{value}
  const widthMatches = sourceCode.matchAll(/\bw-(\d+|full|screen|min|max|fit|\[[\d.]+(?:px|rem|%)\])/g);
  for (const match of widthMatches) {
    spacing.add(`w-${match[1]}`);
  }

  const heightMatches = sourceCode.matchAll(/\bh-(\d+|full|screen|min|max|fit|\[[\d.]+(?:px|rem|%)\])/g);
  for (const match of heightMatches) {
    spacing.add(`h-${match[1]}`);
  }

  // Size: size-{value}
  const sizeMatches = sourceCode.matchAll(/\bsize-(\d+|full|\[[\d.]+(?:px|rem)\])/g);
  for (const match of sizeMatches) {
    spacing.add(`size-${match[1]}`);
  }

  return Array.from(spacing).sort();
}

/**
 * Extract effect tokens (shadows, opacity)
 * @param {string} sourceCode - Source code
 * @returns {Array} Effect tokens
 */
function extractEffectTokens(sourceCode) {
  const effects = new Set();

  // Shadows: shadow-{value}
  const shadowMatches = sourceCode.matchAll(/\bshadow-(xs|sm|md|lg|xl|2xl|inner|none)/g);
  for (const match of shadowMatches) {
    effects.add(`shadow-${match[1]}`);
  }

  // Opacity: opacity-{value}
  const opacityMatches = sourceCode.matchAll(/\bopacity-(\d+)/g);
  for (const match of opacityMatches) {
    effects.add(`opacity-${match[1]}`);
  }

  // Ring: ring-{value}
  const ringMatches = sourceCode.matchAll(/\bring-(\d+|\[[\d.]+(?:px)\])/g);
  for (const match of ringMatches) {
    effects.add(`ring-${match[1]}`);
  }

  // Ring offset: ring-offset-{value}
  const ringOffsetMatches = sourceCode.matchAll(/\bring-offset-(\d+)/g);
  for (const match of ringOffsetMatches) {
    effects.add(`ring-offset-${match[1]}`);
  }

  // Backdrop: backdrop-{filter}
  const backdropMatches = sourceCode.matchAll(/\bbackdrop-(blur|brightness|contrast|grayscale|invert|opacity|saturate|sepia)-?(\d+)?/g);
  for (const match of backdropMatches) {
    effects.add(`backdrop-${match[1]}${match[2] ? `-${match[2]}` : ''}`);
  }

  // Transition: transition-{property}
  const transitionMatches = sourceCode.matchAll(/\btransition(-all|-colors|-opacity|-shadow|-transform|-none)?/g);
  for (const match of transitionMatches) {
    effects.add(`transition${match[1] || ''}`);
  }

  return Array.from(effects).sort();
}

/**
 * Extract border radius tokens
 * @param {string} sourceCode - Source code
 * @returns {Array} Border radius tokens
 */
function extractBorderRadiusTokens(sourceCode) {
  const radii = new Set();

  // Rounded: rounded-{value}
  const roundedMatches = sourceCode.matchAll(/\brounded(-none|-sm|-md|-lg|-xl|-2xl|-3xl|-full)?(-[tblr])?(-[tblr])?/g);
  for (const match of roundedMatches) {
    let token = 'rounded';
    if (match[1]) token += match[1];
    if (match[2]) token += match[2];
    if (match[3]) token += match[3];
    radii.add(token);
  }

  return Array.from(radii).sort();
}

/**
 * Extract CSS variables from source code
 * @param {string} sourceCode - Source code
 * @returns {Array} CSS variable names
 */
function extractCssVariables(sourceCode) {
  const variables = new Set();

  // Match var(--{name})
  const varMatches = sourceCode.matchAll(/var\(--([a-zA-Z0-9-]+)\)/g);
  for (const match of varMatches) {
    variables.add(`--${match[1]}`);
  }

  return Array.from(variables).sort();
}

/**
 * Map extracted tokens to design token names
 * @param {Object} tokens - Extracted tokens
 * @param {Object} mappings - Token name mappings
 * @returns {Object} Mapped tokens
 */
function mapToDesignTokens(tokens, mappings = {}) {
  const defaultMappings = {
    // Color mappings
    'bg-primary': 'colors/primary/500',
    'bg-secondary': 'colors/secondary/500',
    'bg-destructive': 'colors/error/500',
    'bg-muted': 'colors/neutral/100',
    'bg-accent': 'colors/accent/500',
    'bg-background': 'colors/background',
    'text-primary': 'colors/primary/500',
    'text-primary-foreground': 'colors/primary/foreground',
    'text-secondary-foreground': 'colors/secondary/foreground',
    'text-muted-foreground': 'colors/neutral/500',
    'text-foreground': 'colors/foreground',
    'text-destructive': 'colors/error/500',
    'border-input': 'colors/input/border',
    'border-ring': 'colors/ring',

    // Typography mappings
    'text-sm': 'typography/size/sm',
    'text-base': 'typography/size/base',
    'text-lg': 'typography/size/lg',
    'font-medium': 'typography/weight/medium',
    'font-semibold': 'typography/weight/semibold',

    // Spacing mappings
    'px-4': 'spacing/4',
    'py-2': 'spacing/2',
    'gap-2': 'spacing/2',
    'h-9': 'sizing/9',
    'h-10': 'sizing/10',

    // Effect mappings
    'shadow-sm': 'effects/shadow/sm',
    'shadow-xs': 'effects/shadow/xs',

    // Radius mappings
    'rounded-md': 'radii/md',
    'rounded-lg': 'radii/lg',
    'rounded-full': 'radii/full',

    ...mappings
  };

  const mapped = {
    colors: [],
    typography: [],
    spacing: [],
    effects: [],
    borderRadius: []
  };

  // Map color tokens
  for (const token of tokens.colors) {
    const designToken = defaultMappings[token];
    if (designToken) {
      mapped.colors.push({ tailwind: token, designToken });
    } else {
      mapped.colors.push({ tailwind: token, designToken: null });
    }
  }

  // Map typography tokens
  for (const token of tokens.typography) {
    const designToken = defaultMappings[token];
    mapped.typography.push({ tailwind: token, designToken: designToken || null });
  }

  // Map spacing tokens
  for (const token of tokens.spacing) {
    const designToken = defaultMappings[token];
    mapped.spacing.push({ tailwind: token, designToken: designToken || null });
  }

  // Map effect tokens
  for (const token of tokens.effects) {
    const designToken = defaultMappings[token];
    mapped.effects.push({ tailwind: token, designToken: designToken || null });
  }

  // Map border radius tokens
  for (const token of tokens.borderRadius) {
    const designToken = defaultMappings[token];
    mapped.borderRadius.push({ tailwind: token, designToken: designToken || null });
  }

  return mapped;
}

/**
 * Format token summary for display
 * @param {Object} tokens - Extracted tokens
 * @returns {string} Formatted summary
 */
function formatTokenSummary(tokens) {
  const lines = ['Token Dependencies:', ''];

  lines.push(`Colors (${tokens.colors.length}):`);
  tokens.colors.slice(0, 10).forEach(t => lines.push(`  - ${t}`));
  if (tokens.colors.length > 10) lines.push(`  ... and ${tokens.colors.length - 10} more`);

  lines.push('');
  lines.push(`Typography (${tokens.typography.length}):`);
  tokens.typography.forEach(t => lines.push(`  - ${t}`));

  lines.push('');
  lines.push(`Spacing (${tokens.spacing.length}):`);
  tokens.spacing.slice(0, 10).forEach(t => lines.push(`  - ${t}`));
  if (tokens.spacing.length > 10) lines.push(`  ... and ${tokens.spacing.length - 10} more`);

  lines.push('');
  lines.push(`Effects (${tokens.effects.length}):`);
  tokens.effects.forEach(t => lines.push(`  - ${t}`));

  lines.push('');
  lines.push(`Border Radius (${tokens.borderRadius.length}):`);
  tokens.borderRadius.forEach(t => lines.push(`  - ${t}`));

  if (tokens.cssVariables && tokens.cssVariables.length > 0) {
    lines.push('');
    lines.push(`CSS Variables (${tokens.cssVariables.length}):`);
    tokens.cssVariables.forEach(v => lines.push(`  - ${v}`));
  }

  return lines.join('\n');
}

module.exports = {
  extractTokenDependencies,
  extractColorTokens,
  extractTypographyTokens,
  extractSpacingTokens,
  extractEffectTokens,
  extractBorderRadiusTokens,
  extractCssVariables,
  mapToDesignTokens,
  formatTokenSummary,
  createEmptyTokens
};
