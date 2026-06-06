/**
 * shadcn-example-handler.js
 * Handle ShadCN component examples - parsing, transformation, and story generation
 */

/**
 * Parse examples from ShadCN MCP response
 * @param {Object} mcpResponse - Response from get_item_examples_from_registries
 * @param {string} componentName - Target component name
 * @returns {Object} Parsed examples
 */
function parseExamplesFromMcp(mcpResponse, componentName) {
  if (!mcpResponse || !mcpResponse.examples) {
    return { main: null, demos: [], all: [] };
  }

  const examples = mcpResponse.examples;
  const lowerName = componentName.toLowerCase();

  // Categorize examples
  const main = examples.find(ex =>
    ex.name === componentName ||
    ex.name === lowerName ||
    (ex.type === 'registry:ui' && ex.name.toLowerCase().includes(lowerName))
  );

  const demos = examples.filter(ex =>
    ex.name.includes('-demo') ||
    ex.name.includes('example') ||
    ex.type === 'registry:example'
  );

  return {
    main: main ? parseExample(main) : null,
    demos: demos.map(parseExample),
    all: examples.map(parseExample)
  };
}

/**
 * Parse a single example
 * @param {Object} example - Raw example from MCP
 * @returns {Object} Parsed example
 */
function parseExample(example) {
  const code = example.code || example.content || '';

  return {
    name: example.name,
    type: example.type || 'unknown',
    code: code,
    path: example.path || '',
    imports: extractImports(code),
    componentUsage: extractComponentUsage(code),
    propsUsed: extractPropsFromUsage(code),
    hasVariants: code.includes('variant=') || code.includes('variant:'),
    description: generateExampleDescription(example.name, code)
  };
}

/**
 * Extract import statements from code
 * @param {string} code - Source code
 * @returns {Array} Import statements
 */
function extractImports(code) {
  const imports = [];
  const importPattern = /import\s+({[^}]+}|[\w*]+)\s+from\s+['"]([^'"]+)['"]/g;

  let match;
  while ((match = importPattern.exec(code)) !== null) {
    imports.push({
      specifiers: match[1].trim(),
      source: match[2]
    });
  }

  return imports;
}

/**
 * Extract JSX component usage from code
 * @param {string} code - Source code
 * @returns {Array} Component usage instances
 */
function extractComponentUsage(code) {
  const usages = [];

  // Match JSX components with their props
  // <ComponentName prop1="value" prop2={expr}>
  const componentPattern = /<([A-Z][a-zA-Z0-9]*)\s*([^>]*?)(?:\/>|>)/g;

  let match;
  while ((match = componentPattern.exec(code)) !== null) {
    const componentName = match[1];
    const propsString = match[2];

    usages.push({
      component: componentName,
      props: parsePropsString(propsString),
      raw: match[0]
    });
  }

  return usages;
}

/**
 * Parse props from JSX props string
 * @param {string} propsString - Props string like 'variant="primary" size="lg"'
 * @returns {Object} Parsed props
 */
function parsePropsString(propsString) {
  const props = {};

  // Match prop="value" or prop={value}
  const propPattern = /(\w+)=(?:"([^"]*)"|{([^}]*)})/g;

  let match;
  while ((match = propPattern.exec(propsString)) !== null) {
    const propName = match[1];
    const stringValue = match[2];
    const exprValue = match[3];

    props[propName] = stringValue !== undefined ? stringValue : `{${exprValue}}`;
  }

  // Match boolean props (just prop name)
  const boolPattern = /(?:^|\s)(\w+)(?=\s|$|\/|>)/g;
  while ((match = boolPattern.exec(propsString)) !== null) {
    const propName = match[1];
    if (!props[propName] && propName !== '') {
      props[propName] = true;
    }
  }

  return props;
}

/**
 * Extract props used across all component usages
 * @param {string} code - Source code
 * @returns {Object} Props by component
 */
function extractPropsFromUsage(code) {
  const usages = extractComponentUsage(code);
  const propsByComponent = {};

  for (const usage of usages) {
    if (!propsByComponent[usage.component]) {
      propsByComponent[usage.component] = new Set();
    }

    Object.keys(usage.props).forEach(prop =>
      propsByComponent[usage.component].add(prop)
    );
  }

  // Convert sets to arrays
  const result = {};
  for (const [comp, props] of Object.entries(propsByComponent)) {
    result[comp] = Array.from(props);
  }

  return result;
}

/**
 * Generate description from example name and code
 * @param {string} name - Example name
 * @param {string} code - Example code
 * @returns {string} Generated description
 */
function generateExampleDescription(name, code) {
  // Parse name like "button-demo" -> "Button Demo"
  const formatted = name
    .replace(/-/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());

  // Try to extract description from JSDoc comment
  const jsdocMatch = code.match(/\/\*\*\s*\n\s*\*\s*(.+?)\n/);
  if (jsdocMatch) {
    return jsdocMatch[1].trim();
  }

  // Try to extract from first line comment
  const commentMatch = code.match(/^\/\/\s*(.+)/m);
  if (commentMatch) {
    return commentMatch[1].trim();
  }

  return formatted;
}

/**
 * Generate Storybook story entries from examples
 * @param {Array} examples - Parsed examples
 * @param {string} componentName - Component name
 * @returns {Array} Story entries
 */
function generateStoryEntries(examples, componentName) {
  const stories = [];

  for (const example of examples) {
    const storyName = formatStoryName(example.name, componentName);

    stories.push({
      name: storyName,
      exportName: toCamelCase(storyName),
      description: example.description,
      code: example.code,
      args: extractStoryArgs(example),
      play: null // For interaction tests
    });
  }

  return stories;
}

/**
 * Format story name from example name
 * @param {string} exampleName - Example name
 * @param {string} componentName - Component name
 * @returns {string} Story name
 */
function formatStoryName(exampleName, componentName) {
  // Remove component name prefix if present
  let name = exampleName
    .replace(new RegExp(`^${componentName}-?`, 'i'), '')
    .replace(/-demo$/i, '')
    .replace(/-example$/i, '');

  // Default to "Default" if empty or just "demo"/"example"
  if (!name || name.toLowerCase() === 'demo' || name.toLowerCase() === 'example') {
    return 'Default';
  }

  // Convert to title case
  return name
    .split('-')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join('');
}

/**
 * Extract args for Storybook from example
 * @param {Object} example - Parsed example
 * @returns {Object} Story args
 */
function extractStoryArgs(example) {
  const args = {};

  // Look for variant-like props
  for (const usage of example.componentUsage) {
    if (usage.props.variant) {
      args.variant = usage.props.variant;
    }
    if (usage.props.size) {
      args.size = usage.props.size;
    }
    if (usage.props.disabled !== undefined) {
      args.disabled = usage.props.disabled === 'true' || usage.props.disabled === true;
    }
  }

  return args;
}

/**
 * Convert to camelCase
 * @param {string} str - Input string
 * @returns {string} camelCase string
 */
function toCamelCase(str) {
  return str
    .replace(/(?:^\w|[A-Z]|\b\w)/g, (letter, index) =>
      index === 0 ? letter.toLowerCase() : letter.toUpperCase()
    )
    .replace(/\s+/g, '');
}

/**
 * Group examples by variant combinations
 * @param {Array} examples - Parsed examples
 * @returns {Object} Grouped examples
 */
function groupExamplesByVariant(examples) {
  const groups = {
    default: [],
    variants: {},
    sizes: {},
    states: {},
    compositions: []
  };

  for (const example of examples) {
    const name = example.name.toLowerCase();

    // Check for variant in name
    const variantMatch = name.match(/(?:variant[-_]?)?(\w+)(?:-demo)?$/);

    if (name.includes('default') || !name.includes('-')) {
      // Default: explicitly named 'default' OR base component with no suffix (e.g., 'button')
      groups.default.push(example);
    } else if (name.includes('with') || name.includes('loading')) {
      // Check compositions first (with-icon, with-loading, etc.) before size check
      groups.compositions.push(example);
    } else if (name.includes('size') || ['sm', 'lg', 'xl', 'icon'].some(s => name.includes(s))) {
      const sizeName = variantMatch ? variantMatch[1] : 'unknown';
      if (!groups.sizes[sizeName]) groups.sizes[sizeName] = [];
      groups.sizes[sizeName].push(example);
    } else if (['hover', 'active', 'focus', 'disabled'].some(s => name.includes(s))) {
      const stateName = variantMatch ? variantMatch[1] : 'unknown';
      if (!groups.states[stateName]) groups.states[stateName] = [];
      groups.states[stateName].push(example);
    } else {
      const variantName = variantMatch ? variantMatch[1] : 'other';
      if (!groups.variants[variantName]) groups.variants[variantName] = [];
      groups.variants[variantName].push(example);
    }
  }

  return groups;
}

/**
 * Generate documentation from examples
 * @param {Array} examples - Parsed examples
 * @param {string} componentName - Component name
 * @returns {Object} Documentation structure
 */
function generateDocsFromExamples(examples, componentName) {
  const groups = groupExamplesByVariant(examples);

  const docs = {
    title: componentName,
    description: `Examples and usage patterns for the ${componentName} component.`,
    sections: []
  };

  // Default section
  if (groups.default.length > 0) {
    docs.sections.push({
      title: 'Basic Usage',
      examples: groups.default.map(ex => ({
        title: ex.description,
        code: ex.code
      }))
    });
  }

  // Variants section
  if (Object.keys(groups.variants).length > 0) {
    docs.sections.push({
      title: 'Variants',
      examples: Object.entries(groups.variants).flatMap(([variant, exs]) =>
        exs.map(ex => ({
          title: `${variant.charAt(0).toUpperCase() + variant.slice(1)} Variant`,
          code: ex.code
        }))
      )
    });
  }

  // Sizes section
  if (Object.keys(groups.sizes).length > 0) {
    docs.sections.push({
      title: 'Sizes',
      examples: Object.entries(groups.sizes).flatMap(([size, exs]) =>
        exs.map(ex => ({
          title: `Size: ${size.toUpperCase()}`,
          code: ex.code
        }))
      )
    });
  }

  // States section
  if (Object.keys(groups.states).length > 0) {
    docs.sections.push({
      title: 'States',
      examples: Object.entries(groups.states).flatMap(([state, exs]) =>
        exs.map(ex => ({
          title: `${state.charAt(0).toUpperCase() + state.slice(1)} State`,
          code: ex.code
        }))
      )
    });
  }

  // Compositions section
  if (groups.compositions.length > 0) {
    docs.sections.push({
      title: 'Compositions',
      description: 'Examples with icons, loading states, and other compositions.',
      examples: groups.compositions.map(ex => ({
        title: ex.description,
        code: ex.code
      }))
    });
  }

  return docs;
}

/**
 * Format examples summary for display
 * @param {Object} parsedExamples - Output from parseExamplesFromMcp
 * @returns {string} Formatted summary
 */
function formatExamplesSummary(parsedExamples) {
  const lines = [
    'ShadCN Examples Summary',
    '=====================',
    ''
  ];

  if (parsedExamples.main) {
    lines.push(`Main Component: ${parsedExamples.main.name}`);
    lines.push(`  Path: ${parsedExamples.main.path || 'N/A'}`);
    lines.push(`  Has variants: ${parsedExamples.main.hasVariants}`);
    lines.push('');
  }

  lines.push(`Demo Examples: ${parsedExamples.demos.length}`);
  for (const demo of parsedExamples.demos.slice(0, 5)) {
    lines.push(`  - ${demo.name}: ${demo.description}`);
  }
  if (parsedExamples.demos.length > 5) {
    lines.push(`  ... and ${parsedExamples.demos.length - 5} more`);
  }

  lines.push('');
  lines.push(`Total Examples: ${parsedExamples.all.length}`);

  return lines.join('\n');
}

module.exports = {
  parseExamplesFromMcp,
  parseExample,
  extractImports,
  extractComponentUsage,
  parsePropsString,
  extractPropsFromUsage,
  generateStoryEntries,
  formatStoryName,
  extractStoryArgs,
  groupExamplesByVariant,
  generateDocsFromExamples,
  formatExamplesSummary
};
