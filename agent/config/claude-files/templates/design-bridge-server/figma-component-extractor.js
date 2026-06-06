/**
 * figma-component-extractor.js
 * Deep extraction of Figma component structure
 *
 * This module provides comprehensive component extraction from Figma nodes,
 * including visual properties, layout, variants, and token dependencies.
 */

/**
 * Extract complete component data for Design Bridge
 * @param {Object} node - Figma node
 * @param {Object} context - Extraction context
 * @returns {Object} Extracted component
 */
function extractComponent(node, context = {}) {
  const { styles = {}, depth = 0, maxDepth = 10 } = context;

  const component = {
    id: node.id,
    name: node.name,
    type: node.type,
    description: node.description || '',

    // Dimensions
    bounds: node.absoluteBoundingBox ? {
      x: node.absoluteBoundingBox.x,
      y: node.absoluteBoundingBox.y,
      width: node.absoluteBoundingBox.width,
      height: node.absoluteBoundingBox.height
    } : null,

    // Visual properties
    visual: extractVisualProperties(node),

    // Layout (auto-layout)
    layout: extractLayoutProperties(node),

    // For COMPONENT_SET: variant definitions
    variants: node.type === 'COMPONENT_SET'
      ? extractVariantDefinitions(node)
      : null,

    // For INSTANCE: component reference
    componentRef: node.type === 'INSTANCE'
      ? { id: node.componentId, name: node.name }
      : null,

    // Props for component (from variant properties)
    props: extractPropsFromVariants(node),

    // Token dependencies
    tokenDependencies: {
      colors: [],
      typography: [],
      spacing: [],
      effects: [],
      borderRadius: []
    },

    // Original Figma data for optimizer
    _figma: {
      type: node.type,
      fills: node.fills,
      strokes: node.strokes,
      effects: node.effects,
      cornerRadius: node.cornerRadius,
      constraints: node.constraints,
      layoutMode: node.layoutMode,
      itemSpacing: node.itemSpacing
    }
  };

  // Extract token dependencies
  extractTokenDependencies(node, component.tokenDependencies, styles);

  // Process children recursively
  if (node.children && depth < maxDepth) {
    component.children = node.children.map(child =>
      extractComponent(child, { ...context, depth: depth + 1 })
    );

    // Aggregate child token dependencies
    aggregateChildTokens(component);
  }

  return component;
}

/**
 * Extract visual properties (fills, strokes, effects)
 * @param {Object} node - Figma node
 * @returns {Object} Visual properties
 */
function extractVisualProperties(node) {
  return {
    opacity: node.opacity ?? 1,
    blendMode: node.blendMode || 'NORMAL',
    visible: node.visible !== false,

    fills: (node.fills || []).filter(f => f.visible !== false).map(fill => ({
      type: fill.type,
      color: fill.type === 'SOLID' ? {
        r: fill.color.r,
        g: fill.color.g,
        b: fill.color.b,
        a: fill.color.a ?? 1
      } : null,
      opacity: fill.opacity ?? 1,
      gradientStops: fill.gradientStops,
      imageRef: fill.imageRef
    })),

    strokes: (node.strokes || []).filter(s => s.visible !== false).map(stroke => ({
      type: stroke.type,
      color: stroke.type === 'SOLID' ? stroke.color : null,
      weight: node.strokeWeight
    })),

    effects: (node.effects || []).filter(e => e.visible !== false).map(effect => ({
      type: effect.type,
      color: effect.color,
      offset: effect.offset,
      radius: effect.radius,
      spread: effect.spread
    })),

    cornerRadius: extractCornerRadius(node)
  };
}

/**
 * Extract corner radius (handles individual corners)
 * @param {Object} node - Figma node
 * @returns {Object|null} Corner radius configuration
 */
function extractCornerRadius(node) {
  if (typeof node.cornerRadius === 'number') {
    return { all: node.cornerRadius };
  }

  if (node.rectangleCornerRadii) {
    return {
      topLeft: node.rectangleCornerRadii[0],
      topRight: node.rectangleCornerRadii[1],
      bottomRight: node.rectangleCornerRadii[2],
      bottomLeft: node.rectangleCornerRadii[3]
    };
  }

  return null;
}

/**
 * Extract auto-layout properties
 * @param {Object} node - Figma node
 * @returns {Object|null} Layout properties
 */
function extractLayoutProperties(node) {
  if (!node.layoutMode || node.layoutMode === 'NONE') {
    return null;
  }

  return {
    mode: node.layoutMode, // HORIZONTAL | VERTICAL
    direction: node.layoutMode === 'HORIZONTAL' ? 'row' : 'column',

    // Spacing
    gap: node.itemSpacing || 0,
    padding: {
      top: node.paddingTop || 0,
      right: node.paddingRight || 0,
      bottom: node.paddingBottom || 0,
      left: node.paddingLeft || 0
    },

    // Sizing
    primaryAxisSizing: node.primaryAxisSizingMode, // FIXED | AUTO
    counterAxisSizing: node.counterAxisSizingMode, // FIXED | AUTO

    // Alignment
    primaryAxisAlignment: node.primaryAxisAlignItems, // MIN | CENTER | MAX | SPACE_BETWEEN
    counterAxisAlignment: node.counterAxisAlignItems, // MIN | CENTER | MAX

    // Wrap
    layoutWrap: node.layoutWrap // NO_WRAP | WRAP
  };
}

/**
 * Extract variant definitions from COMPONENT_SET
 * @param {Object} node - Figma node
 * @returns {Array|null} Variant definitions
 */
function extractVariantDefinitions(node) {
  if (node.type !== 'COMPONENT_SET') return null;

  const definitions = node.componentPropertyDefinitions || {};
  const variants = [];

  for (const [name, def] of Object.entries(definitions)) {
    if (def.type === 'VARIANT') {
      variants.push({
        name: name,
        type: 'variant',
        options: def.variantOptions || [],
        default: def.defaultValue
      });
    } else if (def.type === 'BOOLEAN') {
      variants.push({
        name: name,
        type: 'boolean',
        default: def.defaultValue
      });
    } else if (def.type === 'TEXT') {
      variants.push({
        name: name,
        type: 'text',
        default: def.defaultValue
      });
    } else if (def.type === 'INSTANCE_SWAP') {
      variants.push({
        name: name,
        type: 'slot',
        preferredValues: def.preferredValues
      });
    }
  }

  return variants;
}

/**
 * Extract component props from variant definitions
 * @param {Object} node - Figma node
 * @returns {Array} Props array
 */
function extractPropsFromVariants(node) {
  const variants = extractVariantDefinitions(node);
  if (!variants) return [];

  return variants.map(v => {
    switch (v.type) {
      case 'variant':
        return {
          name: toCamelCase(v.name),
          type: v.options.map(o => `'${o}'`).join(' | '),
          values: v.options,  // P7: Preserve array for Storybook argTypes
          required: false,
          default: v.default ? `'${v.default}'` : undefined
        };
      case 'boolean':
        return {
          name: toCamelCase(v.name),
          type: 'boolean',
          required: false,
          default: v.default
        };
      case 'text':
        return {
          name: toCamelCase(v.name),
          type: 'string',
          required: false,
          default: v.default ? `'${v.default}'` : undefined
        };
      case 'slot':
        return {
          name: toCamelCase(v.name),
          type: 'ReactNode',
          required: false
        };
      default:
        return null;
    }
  }).filter(Boolean);
}

/**
 * Convert string to camelCase
 * @param {string} str - Input string
 * @returns {string} camelCase string
 */
function toCamelCase(str) {
  // First lowercase the first character, then handle the rest
  return str
    .replace(/[^a-zA-Z0-9]+(.)/g, (_, c) => c.toUpperCase()) // capitalize after special chars
    .replace(/^[A-Z]/, c => c.toLowerCase()); // lowercase first char
}

/**
 * Extract token dependencies from node
 * @param {Object} node - Figma node
 * @param {Object} deps - Token dependencies object
 * @param {Object} styles - Style mappings
 */
function extractTokenDependencies(node, deps, styles) {
  // Extract colors from fills
  if (node.fills) {
    node.fills.forEach(fill => {
      if (fill.type === 'SOLID' && fill.boundVariables?.color) {
        const styleId = fill.boundVariables.color.id;
        if (styles[styleId]) {
          deps.colors.push(styles[styleId].name);
        }
      }
    });
  }

  // Extract typography from text styles
  if (node.type === 'TEXT' && node.styles?.text) {
    const styleId = node.styles.text;
    if (styles[styleId]) {
      deps.typography.push(styles[styleId].name);
    }
  }

  // Extract corner radius
  if (node.cornerRadius) {
    deps.borderRadius.push(`${node.cornerRadius}px`);
  }

  // Extract spacing from auto-layout
  if (node.itemSpacing) {
    deps.spacing.push(`${node.itemSpacing}px`);
  }

  // Extract effects
  if (node.effects && node.styles?.effect) {
    const styleId = node.styles.effect;
    if (styles[styleId]) {
      deps.effects.push(styles[styleId].name);
    }
  }
}

/**
 * Aggregate token dependencies from children
 * @param {Object} component - Component with children
 */
function aggregateChildTokens(component) {
  if (!component.children) return;

  component.children.forEach(child => {
    if (child.tokenDependencies) {
      Object.keys(component.tokenDependencies).forEach(key => {
        if (Array.isArray(child.tokenDependencies[key])) {
          component.tokenDependencies[key].push(...child.tokenDependencies[key]);
        }
      });
    }
  });

  // Deduplicate
  Object.keys(component.tokenDependencies).forEach(key => {
    component.tokenDependencies[key] = [...new Set(component.tokenDependencies[key])];
  });
}

/**
 * Format component extraction result for display
 * @param {Object} component - Extracted component
 * @returns {string} Formatted output
 */
function formatComponentResult(component) {
  const lines = [
    `Component: ${component.name}`,
    `Type: ${component.type}`,
    `ID: ${component.id}`
  ];

  if (component.bounds) {
    lines.push(`Size: ${component.bounds.width}x${component.bounds.height}`);
  }

  if (component.layout) {
    lines.push(`Layout: ${component.layout.direction} (gap: ${component.layout.gap}px)`);
  }

  if (component.variants && component.variants.length > 0) {
    lines.push(`Variants: ${component.variants.map(v => v.name).join(', ')}`);
  }

  if (component.props && component.props.length > 0) {
    lines.push(`Props: ${component.props.map(p => p.name).join(', ')}`);
  }

  const tokenCount = Object.values(component.tokenDependencies)
    .reduce((sum, arr) => sum + arr.length, 0);
  if (tokenCount > 0) {
    lines.push(`Token Dependencies: ${tokenCount}`);
  }

  if (component.children) {
    lines.push(`Children: ${component.children.length}`);
  }

  return lines.join('\n');
}

module.exports = {
  extractComponent,
  extractVisualProperties,
  extractLayoutProperties,
  extractVariantDefinitions,
  extractPropsFromVariants,
  extractCornerRadius,
  extractTokenDependencies,
  aggregateChildTokens,
  toCamelCase,
  formatComponentResult
};
