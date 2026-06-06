/**
 * shadcn-transformer.js
 * Transform ShadCN MCP response to Design Bridge component format
 */

/**
 * Transform ShadCN component data to Design Bridge format
 * @param {Object} shadcnData - Raw data from ShadCN MCP
 * @param {Object} options - Transform options
 * @returns {Object} Design Bridge component format
 */
function transformShadcnComponent(shadcnData, options = {}) {
  const {
    componentName,
    registryName = '@shadcn',
    sourceCode = '',
    examples = [],
    dependencies = []
  } = shadcnData;

  // Extract component info from source code
  const componentInfo = parseComponentSource(sourceCode);

  return {
    name: componentName,
    type: 'COMPONENT',
    category: inferCategory(componentName),
    description: componentInfo.description || `ShadCN ${componentName} component`,

    source: {
      type: 'shadcn',
      registry: registryName,
      extractedAt: new Date().toISOString()
    },

    // Token dependencies extracted from Tailwind classes
    tokenDependencies: {
      colors: [],
      typography: [],
      spacing: [],
      effects: [],
      borderRadius: []
    },

    // Variants from CVA
    variants: componentInfo.variants || [],

    // Props from TypeScript interface
    props: componentInfo.props || [],

    // Interactive states (from CVA hover/focus classes)
    interactiveStates: componentInfo.interactiveStates || {},

    // Dependencies
    dependencies: dependencies,

    // Example code for story generation
    examples: examples.map(ex => ({
      name: ex.name,
      code: ex.code,
      description: ex.description || ''
    })),

    // Paths for generated files
    paths: {
      rawSource: `.design/source/components/${sanitizeFileName(componentName)}.json`,
      codeOutput: `src/components/${pascalCase(componentName)}.tsx`,
      storyOutput: `src/components/${pascalCase(componentName)}.stories.tsx`
    },

    metadata: {
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      version: 1
    }
  };
}

/**
 * Parse component source code to extract structure
 * @param {string} sourceCode - Component source code
 * @returns {Object} Parsed component info
 */
function parseComponentSource(sourceCode) {
  const result = {
    description: '',
    variants: [],
    props: [],
    interactiveStates: {},
    hasCva: false,
    exports: []
  };

  if (!sourceCode) return result;

  // Detect CVA usage
  result.hasCva = sourceCode.includes('class-variance-authority') ||
                  sourceCode.includes('cva(');

  // Extract exports
  const exportMatches = sourceCode.matchAll(/export\s+(?:const|function|{)\s*(\w+)/g);
  for (const match of exportMatches) {
    result.exports.push(match[1]);
  }

  // Extract component description from JSDoc if present
  const jsdocMatch = sourceCode.match(/\/\*\*\s*\n([^*]|\*[^/])*\*\//);
  if (jsdocMatch) {
    const descMatch = jsdocMatch[0].match(/@description\s+(.+)/);
    if (descMatch) {
      result.description = descMatch[1].trim();
    }
  }

  return result;
}

/**
 * Infer component category from name
 * @param {string} name - Component name
 * @returns {string} Category
 */
function inferCategory(name) {
  const lowerName = name.toLowerCase();

  const categories = {
    button: ['button', 'btn', 'cta'],
    input: ['input', 'textfield', 'textarea', 'select', 'checkbox', 'radio', 'switch', 'slider'],
    card: ['card', 'tile'],
    modal: ['modal', 'dialog', 'alert-dialog', 'sheet', 'drawer'],
    navigation: ['nav', 'navigation', 'menu', 'menubar', 'dropdown', 'breadcrumb', 'tabs', 'pagination'],
    layout: ['accordion', 'collapsible', 'separator', 'aspect-ratio', 'scroll-area', 'resizable'],
    feedback: ['toast', 'sonner', 'alert', 'progress', 'skeleton'],
    overlay: ['popover', 'tooltip', 'hover-card', 'context-menu', 'command'],
    data: ['table', 'data-table', 'calendar', 'date-picker', 'chart'],
    form: ['form', 'label', 'input-otp'],
    display: ['avatar', 'badge', 'carousel', 'image']
  };

  for (const [category, keywords] of Object.entries(categories)) {
    if (keywords.some(kw => lowerName.includes(kw))) {
      return category;
    }
  }

  return 'component';
}

/**
 * Sanitize file name
 * @param {string} name - Input name
 * @returns {string} Sanitized name
 */
function sanitizeFileName(name) {
  return name
    .toLowerCase()
    .replace(/\s+/g, '-')
    .replace(/[^a-z0-9-]/g, '')
    .replace(/-+/g, '-');
}

/**
 * Convert to PascalCase
 * @param {string} name - Input name
 * @returns {string} PascalCase name
 */
function pascalCase(name) {
  return name
    .split(/[\s-_]+/)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join('');
}

/**
 * Transform multiple components
 * @param {Array} components - Array of component data
 * @param {Object} options - Transform options
 * @returns {Array} Transformed components
 */
function transformMultipleComponents(components, options = {}) {
  return components.map(comp => transformShadcnComponent(comp, options));
}

/**
 * Merge example data into component
 * @param {Object} component - Base component
 * @param {Array} examples - Example data
 * @returns {Object} Component with examples
 */
function mergeExamples(component, examples) {
  if (!examples || !examples.length) return component;

  return {
    ...component,
    examples: examples.map(ex => ({
      name: ex.name || 'default',
      code: ex.code || '',
      description: ex.description || ''
    }))
  };
}

/**
 * Format component for display
 * @param {Object} component - Transformed component
 * @returns {string} Formatted output
 */
function formatComponentSummary(component) {
  const lines = [
    `Component: ${component.name}`,
    `Category: ${component.category}`,
    `Type: ${component.type}`,
    `Source: ${component.source.type} (${component.source.registry})`,
    '',
    `Variants: ${component.variants.length}`,
    `Props: ${component.props.length}`,
    `Examples: ${component.examples?.length || 0}`,
    `Dependencies: ${component.dependencies?.length || 0}`
  ];

  if (component.variants.length > 0) {
    lines.push('', 'Variants:');
    component.variants.forEach(v => {
      lines.push(`  - ${v.name}: ${v.options?.join(', ') || 'N/A'}`);
    });
  }

  return lines.join('\n');
}

module.exports = {
  transformShadcnComponent,
  transformMultipleComponents,
  parseComponentSource,
  mergeExamples,
  inferCategory,
  sanitizeFileName,
  pascalCase,
  formatComponentSummary
};
