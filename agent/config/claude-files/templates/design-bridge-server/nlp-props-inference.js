/**
 * nlp-props-inference.js
 * NLP Props Inference
 * Infers component props from description and category
 */

/**
 * Standard props for each HTML element type
 * These are injected based on the inferred semantic element
 */
const ELEMENT_PROPS = {
  button: [
    {
      name: 'onClick',
      type: '() => void',
      description: 'Click handler',
      optional: true
    },
    {
      name: 'disabled',
      type: 'boolean',
      default: 'false',
      description: 'Disabled state',
      optional: true
    },
    {
      name: 'type',
      type: "'button' | 'submit' | 'reset'",
      default: "'button'",
      description: 'Button type',
      optional: true
    }
  ],
  input: [
    {
      name: 'value',
      type: 'string',
      description: 'Input value',
      optional: true
    },
    {
      name: 'onChange',
      type: '(e: React.ChangeEvent<HTMLInputElement>) => void',
      description: 'Change handler',
      optional: true
    },
    {
      name: 'placeholder',
      type: 'string',
      description: 'Placeholder text',
      optional: true
    },
    {
      name: 'disabled',
      type: 'boolean',
      default: 'false',
      optional: true
    },
    {
      name: 'name',
      type: 'string',
      description: 'Input name for forms',
      optional: true
    }
  ],
  textarea: [
    {
      name: 'value',
      type: 'string',
      description: 'Textarea value',
      optional: true
    },
    {
      name: 'onChange',
      type: '(e: React.ChangeEvent<HTMLTextAreaElement>) => void',
      description: 'Change handler',
      optional: true
    },
    {
      name: 'placeholder',
      type: 'string',
      optional: true
    },
    {
      name: 'rows',
      type: 'number',
      default: '3',
      optional: true
    }
  ],
  a: [
    {
      name: 'href',
      type: 'string',
      default: "'#'",
      description: 'Link URL',
      optional: true
    },
    {
      name: 'target',
      type: "'_self' | '_blank' | '_parent' | '_top'",
      default: "'_self'",
      optional: true
    },
    {
      name: 'onClick',
      type: '() => void',
      optional: true
    }
  ],
  select: [
    {
      name: 'value',
      type: 'string',
      description: 'Selected value',
      optional: true
    },
    {
      name: 'onChange',
      type: '(e: React.ChangeEvent<HTMLSelectElement>) => void',
      optional: true
    },
    {
      name: 'options',
      type: 'Array<{ value: string; label: string }>',
      description: 'Select options',
      optional: true
    }
  ],
  img: [
    {
      name: 'src',
      type: 'string',
      description: 'Image source URL',
      optional: false
    },
    {
      name: 'alt',
      type: 'string',
      description: 'Alt text for accessibility',
      optional: false
    },
    {
      name: 'width',
      type: 'number | string',
      optional: true
    },
    {
      name: 'height',
      type: 'number | string',
      optional: true
    }
  ],
  form: [
    {
      name: 'onSubmit',
      type: '(e: React.FormEvent) => void',
      description: 'Form submit handler',
      optional: true
    }
  ],
  dialog: [
    {
      name: 'open',
      type: 'boolean',
      description: 'Whether dialog is open',
      optional: true
    },
    {
      name: 'onClose',
      type: '() => void',
      description: 'Close handler',
      optional: true
    }
  ]
};

// Base props that all components get
const BASE_PROPS = [
  {
    name: 'children',
    type: 'React.ReactNode',
    description: 'Child content',
    optional: true
  },
  {
    name: 'className',
    type: 'string',
    description: 'Additional CSS class names',
    optional: true
  },
  {
    name: 'style',
    type: 'React.CSSProperties',
    description: 'Inline styles',
    optional: true
  }
];

/**
 * Get standard props for a given HTML element type
 * @param {string} elementType - HTML element name (button, input, a, etc.)
 * @returns {Array} Array of prop definitions
 */
function getElementProps(elementType) {
  const elementProps = ELEMENT_PROPS[elementType] || [];
  return [...BASE_PROPS, ...elementProps];
}

/**
 * Merge element-based props with component-specific props
 * @param {Object} componentProps - Props inferred from component
 * @param {string} elementType - Inferred HTML element type
 * @returns {Object} Merged props object
 */
function mergeWithElementProps(componentProps, elementType) {
  const elementPropsList = getElementProps(elementType);
  const merged = { ...componentProps };

  for (const prop of elementPropsList) {
    if (!merged[prop.name]) {
      merged[prop.name] = {
        type: prop.type,
        description: prop.description,
        default: prop.default,
        optional: prop.optional !== false
      };
    }
  }

  return merged;
}

/**
 * Common prop patterns in descriptions
 */
const propPatterns = {
  onClick: /\b(click|clickable|action|button|submit|interactive)\b/i,
  onChange: /\b(change|input|select|editable|modifiable)\b/i,
  disabled: /\b(disabled|disable|inactive)\b/i,
  loading: /\b(loading|spinner|async|submitting)\b/i,
  required: /\b(required|mandatory)\b/i,
  error: /\b(error|invalid|validation)\b/i,
  placeholder: /\b(placeholder|hint|prompt)\b/i,
  icon: /\b(icon|symbol)\b/i,
  href: /\b(link|href|url|navigation)\b/i,
  title: /\b(title|heading)\b/i,
  description: /\b(description|subtitle|caption)\b/i,
  image: /\b(image|picture|photo|avatar)\b/i
};

/**
 * Category-specific prop templates
 */
const categoryPropTemplates = {
  button: [
    { name: 'children', type: 'React.ReactNode', required: true, description: 'Button content' },
    { name: 'onClick', type: '() => void', required: false, description: 'Click handler' },
    { name: 'disabled', type: 'boolean', default: 'false', description: 'Disabled state' },
    { name: 'type', type: "'button' | 'submit' | 'reset'", default: "'button'", description: 'Button type attribute' }
  ],

  input: [
    { name: 'value', type: 'string', required: false, description: 'Input value' },
    { name: 'onChange', type: '(e: React.ChangeEvent<HTMLInputElement>) => void', required: false, description: 'Change handler' },
    { name: 'placeholder', type: 'string', required: false, description: 'Placeholder text' },
    { name: 'disabled', type: 'boolean', default: 'false', description: 'Disabled state' },
    { name: 'type', type: "'text' | 'email' | 'password' | 'number'", default: "'text'", description: 'Input type' }
  ],

  card: [
    { name: 'children', type: 'React.ReactNode', required: true, description: 'Card content' },
    { name: 'onClick', type: '() => void', required: false, description: 'Click handler (if interactive)' }
  ],

  navigation: [
    { name: 'items', type: 'NavItem[]', required: true, description: 'Navigation items' },
    { name: 'activeItem', type: 'string', required: false, description: 'Currently active item ID' },
    { name: 'onItemClick', type: '(itemId: string) => void', required: false, description: 'Item click handler' }
  ],

  overlay: [
    { name: 'open', type: 'boolean', required: true, description: 'Open state' },
    { name: 'onClose', type: '() => void', required: true, description: 'Close handler' },
    { name: 'children', type: 'React.ReactNode', required: true, description: 'Overlay content' }
  ],

  feedback: [
    { name: 'message', type: 'string', required: true, description: 'Feedback message' },
    { name: 'type', type: "'info' | 'success' | 'warning' | 'error'", default: "'info'", description: 'Feedback type' },
    { name: 'onClose', type: '() => void', required: false, description: 'Close handler' }
  ],

  layout: [
    { name: 'children', type: 'React.ReactNode', required: true, description: 'Layout content' },
    { name: 'gap', type: 'number | string', required: false, description: 'Gap between children' }
  ],

  data: [
    { name: 'data', type: 'any[]', required: true, description: 'Data to display' },
    { name: 'loading', type: 'boolean', default: 'false', description: 'Loading state' }
  ],

  form: [
    { name: 'onSubmit', type: '(e: React.FormEvent) => void', required: false, description: 'Form submit handler' },
    { name: 'children', type: 'React.ReactNode', required: true, description: 'Form content' }
  ]
};

/**
 * Infer props from description and category
 * @param {string} description - Component description
 * @param {string} category - Component category
 * @param {Object} variants - Generated variants
 * @returns {Array} Inferred props
 */
function inferProps(description, category, variants = {}) {
  const props = [];
  const addedProps = new Set();

  // Start with category-specific props
  const categoryProps = categoryPropTemplates[category] || categoryPropTemplates.button;
  categoryProps.forEach(prop => {
    props.push({ ...prop });
    addedProps.add(prop.name);
  });

  // Add props from description patterns
  for (const [propName, pattern] of Object.entries(propPatterns)) {
    if (pattern.test(description) && !addedProps.has(propName)) {
      const propDef = generatePropDefinition(propName);
      if (propDef) {
        props.push(propDef);
        addedProps.add(propName);
      }
    }
  }

  // Add variant props
  if (variants.variant && !addedProps.has('variant')) {
    const variantValues = Object.keys(variants.variant);
    props.push({
      name: 'variant',
      type: variantValues.map(v => `'${v}'`).join(' | '),
      required: false,
      default: `'${variantValues[0]}'`,
      description: 'Visual variant'
    });
    addedProps.add('variant');
  }

  if (variants.size && !addedProps.has('size')) {
    const sizeValues = Object.keys(variants.size);
    props.push({
      name: 'size',
      type: sizeValues.map(s => `'${s}'`).join(' | '),
      required: false,
      default: `'${sizeValues.includes('md') ? 'md' : sizeValues[0]}'`,
      description: 'Component size'
    });
    addedProps.add('size');
  }

  // Always add className and style props
  if (!addedProps.has('className')) {
    props.push({
      name: 'className',
      type: 'string',
      required: false,
      description: 'Additional CSS classes'
    });
  }

  return props;
}

/**
 * Generate prop definition from pattern name
 */
function generatePropDefinition(propName) {
  const definitions = {
    onClick: {
      name: 'onClick',
      type: '() => void',
      required: false,
      description: 'Click event handler'
    },
    onChange: {
      name: 'onChange',
      type: '(value: any) => void',
      required: false,
      description: 'Change event handler'
    },
    disabled: {
      name: 'disabled',
      type: 'boolean',
      required: false,
      default: 'false',
      description: 'Disabled state'
    },
    loading: {
      name: 'loading',
      type: 'boolean',
      required: false,
      default: 'false',
      description: 'Loading state'
    },
    required: {
      name: 'required',
      type: 'boolean',
      required: false,
      default: 'false',
      description: 'Required field'
    },
    error: {
      name: 'error',
      type: 'string | boolean',
      required: false,
      description: 'Error state or message'
    },
    placeholder: {
      name: 'placeholder',
      type: 'string',
      required: false,
      description: 'Placeholder text'
    },
    icon: {
      name: 'icon',
      type: 'React.ReactNode',
      required: false,
      description: 'Icon element'
    },
    href: {
      name: 'href',
      type: 'string',
      required: false,
      description: 'Link URL'
    },
    title: {
      name: 'title',
      type: 'string',
      required: false,
      description: 'Title text'
    },
    description: {
      name: 'description',
      type: 'string',
      required: false,
      description: 'Description text'
    },
    image: {
      name: 'image',
      type: 'string | { src: string; alt: string }',
      required: false,
      description: 'Image source'
    }
  };

  return definitions[propName];
}

/**
 * Generate TypeScript interface from props
 */
function generateTypeScriptInterface(componentName, props) {
  const lines = [`export interface ${componentName}Props {`];

  props.forEach(prop => {
    const optional = prop.required ? '' : '?';
    const comment = prop.description ? `  /** ${prop.description} */` : '';

    if (comment) lines.push(comment);
    lines.push(`  ${prop.name}${optional}: ${prop.type};`);
  });

  lines.push('}');

  return lines.join('\n');
}

/**
 * Generate JSDoc for props
 */
function generateJSDoc(props) {
  const lines = ['/**', ' * Component props'];

  props.forEach(prop => {
    const requiredTag = prop.required ? '(required)' : '';
    const defaultTag = prop.default ? `- default: ${prop.default}` : '';
    lines.push(` * @param {${prop.type}} ${prop.name} ${requiredTag} ${prop.description || ''} ${defaultTag}`);
  });

  lines.push(' */');

  return lines.join('\n');
}

/**
 * Validate props object
 */
function validateProps(props) {
  const errors = [];

  props.forEach((prop, index) => {
    if (!prop.name) {
      errors.push(`Prop at index ${index} missing name`);
    }
    if (!prop.type) {
      errors.push(`Prop "${prop.name}" missing type`);
    }
  });

  return {
    valid: errors.length === 0,
    errors
  };
}

/**
 * Get prop names from props array
 */
function getPropNames(props) {
  return props.map(p => p.name);
}

/**
 * Check if props include required children
 */
function hasChildrenProp(props) {
  return props.some(p => p.name === 'children');
}

/**
 * Get required props
 */
function getRequiredProps(props) {
  return props.filter(p => p.required);
}

/**
 * Get optional props
 */
function getOptionalProps(props) {
  return props.filter(p => !p.required);
}

module.exports = {
  inferProps,
  generatePropDefinition,
  generateTypeScriptInterface,
  generateJSDoc,
  validateProps,
  getPropNames,
  hasChildrenProp,
  getRequiredProps,
  getOptionalProps,
  categoryPropTemplates,
  propPatterns,
  // Element-based props (Sprint 4.1)
  ELEMENT_PROPS,
  BASE_PROPS,
  getElementProps,
  mergeWithElementProps
};
