/**
 * figma-state-detector.js
 * Detect interactive states from Figma component variants
 *
 * This module analyzes COMPONENT_SET children to detect hover, pressed,
 * focused, and disabled states based on variant naming conventions.
 */

/**
 * State naming patterns to detect
 */
const STATE_PATTERNS = {
  default: [
    /^state\s*=\s*default$/i,
    /^default$/i,
    /\bdefault\b/i
  ],
  hover: [
    /^state\s*=\s*hover$/i,
    /^hover$/i,
    /\bhover\b/i,
    /\bhovered\b/i
  ],
  pressed: [
    /^state\s*=\s*pressed$/i,
    /^pressed$/i,
    /\bpressed\b/i,
    /\bactive\b/i,
    /^state\s*=\s*active$/i
  ],
  focused: [
    /^state\s*=\s*focus$/i,
    /^state\s*=\s*focused$/i,
    /^focus$/i,
    /\bfocus(ed)?\b/i
  ],
  disabled: [
    /^state\s*=\s*disabled$/i,
    /^disabled$/i,
    /\bdisabled\b/i
  ]
};

/**
 * Detect interactive states from a COMPONENT_SET
 * @param {Object} componentSet - The component set node
 * @returns {Object} Interactive states object
 */
function detectInteractiveStates(componentSet) {
  if (componentSet.type !== 'COMPONENT_SET' || !componentSet.children) {
    return {};
  }

  const variants = componentSet.children;
  const states = {};

  // Find default variant
  const defaultVariant = findVariantByState(variants, 'default');

  if (!defaultVariant) {
    // If no explicit default, use the first variant
    const firstVariant = variants[0];
    if (!firstVariant) return {};

    // Check if any variant matches state patterns
    const hasStates = variants.some(v =>
      matchesAnyStatePattern(v.name, Object.values(STATE_PATTERNS).flat())
    );

    if (!hasStates) return {};
  }

  const baseVariant = defaultVariant || variants[0];

  // Detect each state type
  for (const [stateName, patterns] of Object.entries(STATE_PATTERNS)) {
    if (stateName === 'default') continue;

    const stateVariant = findVariantByState(variants, stateName);

    if (stateVariant && stateVariant !== baseVariant) {
      const diff = computeStateDiff(baseVariant, stateVariant);

      if (Object.keys(diff).length > 0) {
        states[stateName] = diff;
      }
    }
  }

  return states;
}

/**
 * Find a variant matching a specific state
 * @param {Array} variants - Array of variant nodes
 * @param {string} stateName - State name to find
 * @returns {Object|null} Matching variant
 */
function findVariantByState(variants, stateName) {
  const patterns = STATE_PATTERNS[stateName];
  if (!patterns) return null;

  return variants.find(v => matchesAnyStatePattern(v.name, patterns));
}

/**
 * Check if name matches any pattern
 * @param {string} name - Variant name
 * @param {Array} patterns - Array of RegExp patterns
 * @returns {boolean} Whether any pattern matches
 */
function matchesAnyStatePattern(name, patterns) {
  return patterns.some(pattern => pattern.test(name));
}

/**
 * Compute the visual difference between two variants
 * @param {Object} baseVariant - Default state variant
 * @param {Object} stateVariant - Alternative state variant
 * @returns {Object} Style differences
 */
function computeStateDiff(baseVariant, stateVariant) {
  const diff = {};

  // Compare fills
  const baseFills = baseVariant.figmaProperties?.fills || baseVariant.fills || [];
  const stateFills = stateVariant.figmaProperties?.fills || stateVariant.fills || [];

  if (!arraysEqual(baseFills, stateFills)) {
    diff.backgroundColor = extractPrimaryColor(stateFills);
    diff.fills = stateFills;
  }

  // Compare strokes
  const baseStrokes = baseVariant.figmaProperties?.strokes || baseVariant.strokes || [];
  const stateStrokes = stateVariant.figmaProperties?.strokes || stateVariant.strokes || [];

  if (!arraysEqual(baseStrokes, stateStrokes)) {
    diff.borderColor = extractPrimaryColor(stateStrokes);
    diff.strokes = stateStrokes;
  }

  // Compare effects (shadows)
  const baseEffects = baseVariant.figmaProperties?.effects || baseVariant.effects || [];
  const stateEffects = stateVariant.figmaProperties?.effects || stateVariant.effects || [];

  if (!arraysEqual(baseEffects, stateEffects)) {
    diff.boxShadow = formatEffectsAsCss(stateEffects);
    diff.effects = stateEffects;
  }

  // Compare opacity
  const baseOpacity = baseVariant.figmaProperties?.opacity ?? baseVariant.opacity ?? 1;
  const stateOpacity = stateVariant.figmaProperties?.opacity ?? stateVariant.opacity ?? 1;

  if (baseOpacity !== stateOpacity) {
    diff.opacity = stateOpacity;
  }

  // Compare corner radius
  const baseRadius = baseVariant.figmaProperties?.cornerRadius ?? baseVariant.cornerRadius;
  const stateRadius = stateVariant.figmaProperties?.cornerRadius ?? stateVariant.cornerRadius;

  if (baseRadius !== stateRadius && stateRadius !== undefined) {
    diff.borderRadius = `${stateRadius}px`;
  }

  // Compare transform/scale (check dimensions)
  const baseWidth = baseVariant.dimensions?.width;
  const stateWidth = stateVariant.dimensions?.width;

  if (baseWidth && stateWidth && baseWidth !== stateWidth) {
    const scale = stateWidth / baseWidth;
    if (scale !== 1) {
      diff.transform = `scale(${scale.toFixed(2)})`;
    }
  }

  return diff;
}

/**
 * Extract primary color from fills array
 * @param {Array} fills - Array of fill objects
 * @returns {string|null} CSS color string
 */
function extractPrimaryColor(fills) {
  const solidFill = fills.find(f => f.type === 'SOLID' && f.visible !== false);
  if (!solidFill || !solidFill.color) return null;

  const { r, g, b, a } = solidFill.color;
  if (a !== undefined && a < 1) {
    return `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${a})`;
  }
  return rgbToHex(r, g, b);
}

/**
 * Convert RGB values (0-1) to hex color
 * @param {number} r - Red (0-1)
 * @param {number} g - Green (0-1)
 * @param {number} b - Blue (0-1)
 * @returns {string} Hex color
 */
function rgbToHex(r, g, b) {
  const toHex = n => Math.round(n * 255).toString(16).padStart(2, '0');
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`.toUpperCase();
}

/**
 * Format effects as CSS box-shadow
 * @param {Array} effects - Array of effect objects
 * @returns {string} CSS box-shadow value
 */
function formatEffectsAsCss(effects) {
  const shadows = effects
    .filter(e => (e.type === 'DROP_SHADOW' || e.type === 'INNER_SHADOW') && e.visible !== false)
    .map(e => {
      const color = e.color ? extractPrimaryColor([{ type: 'SOLID', color: e.color }]) : 'rgba(0,0,0,0.25)';
      const inset = e.type === 'INNER_SHADOW' ? 'inset ' : '';
      return `${inset}${e.offset?.x || 0}px ${e.offset?.y || 0}px ${e.radius || 0}px ${e.spread || 0}px ${color}`;
    });

  return shadows.join(', ') || 'none';
}

/**
 * Simple array equality check
 * @param {Array} a - First array
 * @param {Array} b - Second array
 * @returns {boolean} Whether arrays are equal
 */
function arraysEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * Generate CSS for interactive states
 * @param {Object} states - Interactive states object
 * @param {string} selector - CSS selector
 * @returns {string} Generated CSS
 */
function generateStateCss(states, selector = '.component') {
  let css = '';

  if (states.hover) {
    css += `${selector}:hover {\n`;
    css += formatStateAsCss(states.hover);
    css += '}\n\n';
  }

  if (states.pressed) {
    css += `${selector}:active {\n`;
    css += formatStateAsCss(states.pressed);
    css += '}\n\n';
  }

  if (states.focused) {
    css += `${selector}:focus {\n`;
    css += formatStateAsCss(states.focused);
    css += '}\n\n';
  }

  if (states.disabled) {
    css += `${selector}:disabled, ${selector}[disabled] {\n`;
    css += formatStateAsCss(states.disabled);
    css += '}\n\n';
  }

  return css;
}

/**
 * Format a single state as CSS properties
 * @param {Object} state - State object
 * @returns {string} CSS properties
 */
function formatStateAsCss(state) {
  let css = '';

  if (state.backgroundColor) css += `  background-color: ${state.backgroundColor};\n`;
  if (state.borderColor) css += `  border-color: ${state.borderColor};\n`;
  if (state.boxShadow && state.boxShadow !== 'none') css += `  box-shadow: ${state.boxShadow};\n`;
  if (state.opacity !== undefined) css += `  opacity: ${state.opacity};\n`;
  if (state.borderRadius) css += `  border-radius: ${state.borderRadius};\n`;
  if (state.transform) css += `  transform: ${state.transform};\n`;

  return css;
}

/**
 * Format state detection results for display
 * @param {Object} states - Detected states
 * @returns {string} Formatted output
 */
function formatStateResults(states) {
  const stateNames = Object.keys(states);

  if (stateNames.length === 0) {
    return 'No interactive states detected';
  }

  const lines = [`Detected ${stateNames.length} interactive state(s):`];

  for (const [name, diff] of Object.entries(states)) {
    lines.push(`\n  ${name}:`);
    const props = Object.keys(diff).filter(k => k !== 'fills' && k !== 'strokes' && k !== 'effects');
    props.forEach(prop => {
      lines.push(`    ${prop}: ${diff[prop]}`);
    });
  }

  return lines.join('\n');
}

module.exports = {
  detectInteractiveStates,
  computeStateDiff,
  findVariantByState,
  matchesAnyStatePattern,
  generateStateCss,
  formatStateAsCss,
  extractPrimaryColor,
  rgbToHex,
  formatEffectsAsCss,
  formatStateResults,
  STATE_PATTERNS
};
