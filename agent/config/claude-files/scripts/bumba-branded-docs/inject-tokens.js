#!/usr/bin/env node
/**
 * inject-tokens.js
 * Converts design tokens to CSS custom properties for injection into HTML templates
 *
 * Usage:
 *   const { tokensToCSS } = require('./inject-tokens');
 *   const css = tokensToCSS(tokens);
 *
 * CLI:
 *   node inject-tokens.js [projectPath]
 */

const { loadDesignTokens } = require('./load-design-tokens');

/**
 * Convert a shadow effect object to CSS box-shadow value
 * @param {object|array} effect - Shadow effect from tokens
 * @returns {string} CSS box-shadow value
 */
function effectToCSS(effect) {
  // Handle array of effects (multiple shadows)
  if (Array.isArray(effect)) {
    return effect.map(e => effectToCSS(e)).join(', ');
  }

  if (!effect || typeof effect !== 'object') {
    return 'none';
  }

  // Handle DROP_SHADOW type
  if (effect.type === 'DROP_SHADOW') {
    const x = effect.x || '0px';
    const y = effect.y || '0px';
    const blur = effect.blur || '0px';
    const spread = effect.spread || '0px';
    const color = effect.color || 'rgba(0,0,0,0.25)';
    return `${x} ${y} ${blur} ${spread} ${color}`;
  }

  // Handle INNER_SHADOW type
  if (effect.type === 'INNER_SHADOW') {
    const x = effect.x || '0px';
    const y = effect.y || '0px';
    const blur = effect.blur || '0px';
    const spread = effect.spread || '0px';
    const color = effect.color || 'rgba(0,0,0,0.25)';
    return `inset ${x} ${y} ${blur} ${spread} ${color}`;
  }

  return 'none';
}

/**
 * Sanitize a token name for use as a CSS variable
 * @param {string} name - Token name
 * @returns {string} Sanitized CSS variable name
 */
function sanitizeName(name) {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, '-')
    .replace(/--+/g, '-')
    .replace(/^-|-$/g, '');
}

/**
 * Convert design tokens to CSS custom properties
 * @param {object} tokens - Normalized design tokens
 * @returns {string} CSS :root block with custom properties
 */
function tokensToCSS(tokens) {
  const lines = [':root {'];

  // Colors
  if (tokens.colors) {
    lines.push('  /* Colors */');
    Object.entries(tokens.colors).forEach(([name, value]) => {
      const safeName = sanitizeName(name);
      // Handle both flat and rich format
      const colorValue = typeof value === 'object' ? value.value : value;
      if (colorValue) {
        lines.push(`  --color-${safeName}: ${colorValue};`);
      }
    });
    lines.push('');
  }

  // Typography
  if (tokens.typography) {
    lines.push('  /* Typography */');
    Object.entries(tokens.typography).forEach(([name, styles]) => {
      const safeName = sanitizeName(name);
      if (typeof styles === 'object') {
        if (styles.fontFamily) {
          lines.push(`  --font-${safeName}-family: "${styles.fontFamily}";`);
        }
        if (styles.fontSize) {
          lines.push(`  --font-${safeName}-size: ${styles.fontSize};`);
        }
        if (styles.fontWeight) {
          lines.push(`  --font-${safeName}-weight: ${styles.fontWeight};`);
        }
        if (styles.lineHeight) {
          lines.push(`  --font-${safeName}-line-height: ${styles.lineHeight};`);
        }
        if (styles.letterSpacing) {
          lines.push(`  --font-${safeName}-letter-spacing: ${styles.letterSpacing};`);
        }
      }
    });
    lines.push('');
  }

  // Spacing
  if (tokens.spacing) {
    lines.push('  /* Spacing */');
    Object.entries(tokens.spacing).forEach(([name, value]) => {
      const safeName = sanitizeName(name);
      const spacingValue = typeof value === 'object' ? value.value : value;
      if (spacingValue) {
        lines.push(`  --spacing-${safeName}: ${spacingValue};`);
      }
    });
    lines.push('');
  }

  // Border Radius
  if (tokens.borderRadius) {
    lines.push('  /* Border Radius */');
    Object.entries(tokens.borderRadius).forEach(([name, value]) => {
      const safeName = sanitizeName(name);
      const radiusValue = typeof value === 'object' ? value.value : value;
      if (radiusValue) {
        lines.push(`  --radius-${safeName}: ${radiusValue};`);
      }
    });
    lines.push('');
  }

  // Effects (shadows)
  if (tokens.effects) {
    lines.push('  /* Effects */');
    Object.entries(tokens.effects).forEach(([name, value]) => {
      const safeName = sanitizeName(name);
      const shadowValue = effectToCSS(value);
      if (shadowValue !== 'none') {
        lines.push(`  --${safeName}: ${shadowValue};`);
      }
    });
    lines.push('');
  }

  lines.push('}');

  return lines.join('\n');
}

/**
 * Generate a complete CSS block for injection into HTML
 * @param {string} projectPath - Path to project root
 * @returns {string} Complete CSS including tokens and utility classes
 */
function generateBrandCSS(projectPath = process.cwd()) {
  const tokens = loadDesignTokens(projectPath);
  const tokenCSS = tokensToCSS(tokens);

  // Add utility classes that use the tokens
  const utilities = `
/* Brand Utilities */
.text-primary { color: var(--color-primary); }
.text-secondary { color: var(--color-secondary); }
.bg-primary { background-color: var(--color-primary); }
.bg-secondary { background-color: var(--color-secondary); }
.font-heading { font-family: var(--font-heading-family), serif; }
.font-body { font-family: var(--font-body-family), system-ui, sans-serif; }
.accent { color: var(--color-secondary); }
.highlight { background: var(--color-primary); color: white; padding: 0.2em 0.5em; }
`;

  return tokenCSS + '\n' + utilities;
}

/**
 * Get token summary for display
 * @param {object} tokens - Design tokens
 * @returns {object} Summary of brand tokens
 */
function getTokenSummary(tokens) {
  const summary = {
    colors: {},
    typography: {},
    hasSpacing: false,
    hasEffects: false,
    hasBorderRadius: false
  };

  // Extract key colors
  if (tokens.colors) {
    ['primary', 'secondary', 'success', 'warning', 'error'].forEach(key => {
      if (tokens.colors[key]) {
        const value = typeof tokens.colors[key] === 'object'
          ? tokens.colors[key].value
          : tokens.colors[key];
        summary.colors[key] = value;
      }
    });
  }

  // Extract typography families
  if (tokens.typography) {
    ['heading', 'body', 'caption'].forEach(key => {
      if (tokens.typography[key]?.fontFamily) {
        summary.typography[key] = tokens.typography[key].fontFamily;
      }
    });
  }

  summary.hasSpacing = !!(tokens.spacing && Object.keys(tokens.spacing).length > 0);
  summary.hasEffects = !!(tokens.effects && Object.keys(tokens.effects).length > 0);
  summary.hasBorderRadius = !!(tokens.borderRadius && Object.keys(tokens.borderRadius).length > 0);

  return summary;
}

// CLI usage
if (require.main === module) {
  const projectPath = process.argv[2] || process.cwd();

  try {
    const tokens = loadDesignTokens(projectPath);
    const css = tokensToCSS(tokens);
    const summary = getTokenSummary(tokens);

    console.log('/* Generated CSS Custom Properties */');
    console.log(css);
    console.log('\n/* Token Summary */');
    console.log('/*');
    console.log(JSON.stringify(summary, null, 2));
    console.log('*/');
  } catch (error) {
    console.error(`Error: ${error.message}`);
    process.exit(1);
  }
}

module.exports = {
  tokensToCSS,
  generateBrandCSS,
  getTokenSummary,
  effectToCSS,
  sanitizeName
};
