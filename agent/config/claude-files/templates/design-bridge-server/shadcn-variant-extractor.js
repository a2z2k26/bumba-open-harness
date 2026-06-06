/**
 * shadcn-variant-extractor.js
 * Extract CVA (class-variance-authority) variants from ShadCN components
 */

/**
 * Extract CVA variants from component source code
 * @param {string} sourceCode - Component source code
 * @returns {Object} Extracted variants and defaults
 */
function extractCvaVariants(sourceCode) {
  if (!sourceCode) {
    return { variants: [], defaultVariants: {}, baseClasses: '' };
  }

  // Find all cva() calls in the source
  const cvaBlocks = findCvaBlocks(sourceCode);

  if (cvaBlocks.length === 0) {
    return { variants: [], defaultVariants: {}, baseClasses: '' };
  }

  // Parse the first (primary) CVA block
  const primaryCva = cvaBlocks[0];

  return {
    variants: primaryCva.variants,
    defaultVariants: primaryCva.defaultVariants,
    baseClasses: primaryCva.baseClasses,
    allCvaBlocks: cvaBlocks
  };
}

/**
 * Find all CVA blocks in source code
 * @param {string} sourceCode - Source code
 * @returns {Array} Array of parsed CVA blocks
 */
function findCvaBlocks(sourceCode) {
  const blocks = [];

  // Match cva( patterns and extract content
  // This regex finds the variable name and the cva call (without trailing whitespace)
  const cvaPattern = /const\s+(\w+Variants?)\s*=\s*cva\s*\(/g;
  let match;

  while ((match = cvaPattern.exec(sourceCode)) !== null) {
    const varName = match[1];
    // startIndex - 1 now correctly points to the opening (
    const openParenIndex = match.index + match[0].length - 1;

    // Extract the cva arguments by counting parentheses
    const cvaContent = extractBalancedContent(sourceCode, openParenIndex, '(', ')');

    if (cvaContent) {
      const parsed = parseCvaContent(cvaContent, varName);
      if (parsed) {
        blocks.push(parsed);
      }
    }
  }

  return blocks;
}

/**
 * Extract content between balanced delimiters
 * @param {string} str - Source string
 * @param {number} startIndex - Start index (at opening delimiter)
 * @param {string} open - Opening delimiter
 * @param {string} close - Closing delimiter
 * @returns {string|null} Content between delimiters
 */
function extractBalancedContent(str, startIndex, open, close) {
  let depth = 0;
  let start = -1;

  for (let i = startIndex; i < str.length; i++) {
    if (str[i] === open) {
      if (depth === 0) start = i;
      depth++;
    } else if (str[i] === close) {
      depth--;
      if (depth === 0) {
        return str.substring(start + 1, i);
      }
    }
  }

  return null;
}

/**
 * Parse CVA content to extract variants
 * @param {string} content - CVA call content
 * @param {string} varName - Variable name
 * @returns {Object} Parsed CVA data
 */
function parseCvaContent(content, varName) {
  // Split into base classes and config object
  // cva("base classes", { variants: ... })

  // Find the first string (base classes)
  const baseMatch = content.match(/^\s*["'`]([^"'`]*)["'`]/);
  const baseClasses = baseMatch ? baseMatch[1] : '';

  // Find the variants object
  const variantsMatch = content.match(/variants\s*:\s*{/);
  if (!variantsMatch) {
    return {
      name: varName,
      baseClasses,
      variants: [],
      defaultVariants: {}
    };
  }

  // Extract variants section
  const variantsStart = content.indexOf('variants:');
  const variantsContent = extractBalancedContent(content, variantsStart + 'variants:'.length, '{', '}');

  // Extract defaultVariants section
  const defaultsMatch = content.match(/defaultVariants\s*:\s*{/);
  let defaultVariants = {};
  if (defaultsMatch) {
    const defaultsStart = content.indexOf('defaultVariants:');
    const defaultsContent = extractBalancedContent(content, defaultsStart + 'defaultVariants:'.length, '{', '}');
    if (defaultsContent) {
      defaultVariants = parseDefaultVariants(defaultsContent);
    }
  }

  // Parse variant dimensions
  const variants = parseVariantDimensions(variantsContent || '');

  return {
    name: varName,
    baseClasses,
    variants,
    defaultVariants
  };
}

/**
 * Parse variant dimensions from variants object content
 * @param {string} content - Variants object content
 * @returns {Array} Array of variant dimensions
 */
function parseVariantDimensions(content) {
  const dimensions = [];

  // Match dimension: { option: "classes", ... }
  const dimensionPattern = /(\w+)\s*:\s*{([^}]+)}/g;
  let match;

  while ((match = dimensionPattern.exec(content)) !== null) {
    const dimensionName = match[1];
    const optionsContent = match[2];

    // Parse options within this dimension
    const options = parseVariantOptions(optionsContent);

    dimensions.push({
      name: dimensionName,
      type: 'variant',
      options: options
    });
  }

  return dimensions;
}

/**
 * Parse variant options from dimension content
 * @param {string} content - Dimension content
 * @returns {Array} Array of option objects
 */
function parseVariantOptions(content) {
  const options = [];

  // Match option: "classes" or option: `classes`
  const optionPattern = /(\w+)\s*:\s*["'`]([^"'`]*)["'`]/g;
  let match;

  while ((match = optionPattern.exec(content)) !== null) {
    const optionName = match[1];
    const classes = match[2];

    options.push({
      value: optionName,
      classes: classes,
      tokens: extractTokensFromClasses(classes)
    });
  }

  return options;
}

/**
 * Parse default variants from defaultVariants content
 * @param {string} content - DefaultVariants content
 * @returns {Object} Default variants mapping
 */
function parseDefaultVariants(content) {
  const defaults = {};

  // Match dimension: "value" or dimension: 'value'
  const defaultPattern = /(\w+)\s*:\s*["'`](\w+)["'`]/g;
  let match;

  while ((match = defaultPattern.exec(content)) !== null) {
    defaults[match[1]] = match[2];
  }

  return defaults;
}

/**
 * Extract token references from Tailwind classes
 * @param {string} classes - Tailwind class string
 * @returns {Array} Token references
 */
function extractTokensFromClasses(classes) {
  const tokens = [];

  // Color tokens
  const colorMatches = classes.matchAll(/(?:bg|text|border|ring)-([a-z]+-?\d*(?:\/\d+)?)/g);
  for (const match of colorMatches) {
    tokens.push({ type: 'color', value: match[0] });
  }

  // Spacing tokens (p-4, px-4, py-2, m-4, mx-auto, gap-2, etc.)
  const spacingMatches = classes.matchAll(/(?:p|m|gap|space|w|h|size)[xytblr]?-(\d+|\[[\d.]+(?:px|rem)\])/g);
  for (const match of spacingMatches) {
    tokens.push({ type: 'spacing', value: match[0] });
  }

  // Effect tokens
  const effectMatches = classes.matchAll(/(?:shadow|opacity|ring)-(\w+)/g);
  for (const match of effectMatches) {
    tokens.push({ type: 'effect', value: match[0] });
  }

  return tokens;
}

/**
 * Convert variants to Design Bridge format
 * @param {Array} variants - Parsed variants
 * @param {Object} defaults - Default variants
 * @returns {Array} Design Bridge variant format
 */
function toDesignBridgeFormat(variants, defaults = {}) {
  return variants.map(dimension => ({
    name: dimension.name,
    type: 'variant',
    default: defaults[dimension.name] || dimension.options[0]?.value || null,
    options: dimension.options.map(opt => opt.value)
  }));
}

/**
 * Generate TypeScript props interface from variants
 * @param {Array} variants - Parsed variants
 * @returns {string} TypeScript interface
 */
function generatePropsInterface(variants, componentName = 'Component') {
  const lines = [`interface ${componentName}Props {`];

  for (const dimension of variants) {
    const optionTypes = dimension.options.map(opt => `'${opt.value}'`).join(' | ');
    lines.push(`  ${dimension.name}?: ${optionTypes};`);
  }

  lines.push('  className?: string;');
  lines.push('  children?: React.ReactNode;');
  lines.push('}');

  return lines.join('\n');
}

/**
 * Extract interactive states from variant classes
 * @param {Array} variants - Parsed variants
 * @returns {Object} Interactive states
 */
function extractInteractiveStates(variants) {
  const states = {
    hover: {},
    focus: {},
    active: {},
    disabled: {}
  };

  for (const dimension of variants) {
    for (const option of dimension.options) {
      const classes = option.classes;

      // Extract hover states
      const hoverMatches = classes.matchAll(/hover:([^\s]+)/g);
      for (const match of hoverMatches) {
        if (!states.hover[dimension.name]) states.hover[dimension.name] = {};
        states.hover[dimension.name][option.value] = match[1];
      }

      // Extract focus states
      const focusMatches = classes.matchAll(/focus(?:-visible)?:([^\s]+)/g);
      for (const match of focusMatches) {
        if (!states.focus[dimension.name]) states.focus[dimension.name] = {};
        states.focus[dimension.name][option.value] = match[1];
      }

      // Extract active states
      const activeMatches = classes.matchAll(/active:([^\s]+)/g);
      for (const match of activeMatches) {
        if (!states.active[dimension.name]) states.active[dimension.name] = {};
        states.active[dimension.name][option.value] = match[1];
      }

      // Extract disabled states
      const disabledMatches = classes.matchAll(/disabled:([^\s]+)/g);
      for (const match of disabledMatches) {
        if (!states.disabled[dimension.name]) states.disabled[dimension.name] = {};
        states.disabled[dimension.name][option.value] = match[1];
      }
    }
  }

  // Clean up empty state objects
  for (const [state, value] of Object.entries(states)) {
    if (Object.keys(value).length === 0) {
      delete states[state];
    }
  }

  return states;
}

/**
 * Format variants for display
 * @param {Object} cvaData - Extracted CVA data
 * @returns {string} Formatted output
 */
function formatVariantSummary(cvaData) {
  const lines = ['CVA Variants:', ''];

  if (cvaData.baseClasses) {
    lines.push('Base Classes:');
    lines.push(`  ${cvaData.baseClasses.substring(0, 100)}...`);
    lines.push('');
  }

  lines.push(`Variant Dimensions (${cvaData.variants.length}):`);
  for (const dim of cvaData.variants) {
    const options = dim.options.map(o => o.value).join(', ');
    const defaultVal = cvaData.defaultVariants[dim.name];
    lines.push(`  ${dim.name}: [${options}]${defaultVal ? ` (default: ${defaultVal})` : ''}`);
  }

  if (Object.keys(cvaData.defaultVariants).length > 0) {
    lines.push('');
    lines.push('Default Variants:');
    for (const [key, value] of Object.entries(cvaData.defaultVariants)) {
      lines.push(`  ${key}: ${value}`);
    }
  }

  return lines.join('\n');
}

module.exports = {
  extractCvaVariants,
  findCvaBlocks,
  parseCvaContent,
  parseVariantDimensions,
  parseVariantOptions,
  parseDefaultVariants,
  extractTokensFromClasses,
  toDesignBridgeFormat,
  generatePropsInterface,
  extractInteractiveStates,
  formatVariantSummary
};
