/**
 * nlp-input-schema.js
 * NLP Component Generation Input Schema
 * Defines the structured input format for component descriptions
 */

const nlpInputSchema = {
  $schema: 'http://json-schema.org/draft-07/schema#',
  title: 'NLP Component Generation Input',
  type: 'object',

  required: ['name', 'description'],

  properties: {
    // Required fields
    name: {
      type: 'string',
      description: 'Component name in PascalCase',
      pattern: '^[A-Z][a-zA-Z0-9]*$',
      examples: ['Button', 'Card', 'NavBar']
    },

    description: {
      type: 'string',
      description: 'Natural language description of the component',
      minLength: 10,
      maxLength: 2000,
      examples: [
        'A primary button with rounded corners and hover effect',
        'A card with header image, title, description, and action buttons'
      ]
    },

    // Optional fields
    category: {
      type: 'string',
      enum: ['button', 'card', 'input', 'navigation', 'layout', 'feedback', 'overlay', 'data', 'form'],
      description: 'Component category for organization'
    },

    variants: {
      type: 'array',
      items: { type: 'string' },
      description: 'Visual variants to generate',
      examples: [['primary', 'secondary', 'outline', 'ghost']]
    },

    sizes: {
      type: 'array',
      items: { type: 'string' },
      description: 'Size variants to generate',
      examples: [['sm', 'md', 'lg']]
    },

    states: {
      type: 'array',
      items: { type: 'string' },
      description: 'Interactive states to include',
      examples: [['default', 'hover', 'active', 'disabled', 'loading']]
    },

    colors: {
      type: 'object',
      description: 'Specific colors to use (overrides inference)',
      additionalProperties: { type: 'string' },
      examples: [{
        primary: '#3B82F6',
        secondary: '#6B7280',
        background: '#FFFFFF'
      }]
    },

    framework: {
      type: 'string',
      enum: ['react', 'vue', 'svelte', 'angular', 'html'],
      default: 'react',
      description: 'Target framework for code generation'
    },

    refinement: {
      type: 'object',
      description: 'Refinement context from previous generation',
      properties: {
        previousId: { type: 'string' },
        feedback: { type: 'string' },
        keepFields: { type: 'array', items: { type: 'string' } }
      }
    }
  }
};

/**
 * Category hints for inference
 */
const categoryHints = {
  button: ['button', 'btn', 'click', 'submit', 'action'],
  card: ['card', 'tile', 'panel', 'box'],
  input: ['input', 'field', 'text', 'textarea', 'select', 'checkbox', 'radio'],
  navigation: ['nav', 'menu', 'breadcrumb', 'tab', 'link'],
  layout: ['container', 'wrapper', 'grid', 'flex', 'layout', 'section'],
  feedback: ['alert', 'toast', 'notification', 'progress', 'skeleton', 'spinner'],
  overlay: ['modal', 'dialog', 'drawer', 'popover', 'tooltip', 'sheet'],
  data: ['table', 'list', 'avatar', 'badge', 'tag'],
  form: ['form', 'label', 'field', 'validation']
};

/**
 * Validate input against schema
 * @param {Object} input - Input to validate
 * @returns {Object} Validation result with errors array
 */
function validateInput(input) {
  const errors = [];

  // Check required fields
  if (!input.name) {
    errors.push('Missing required field: name');
  } else if (!/^[A-Z][a-zA-Z0-9]*$/.test(input.name)) {
    errors.push('Name must be PascalCase (e.g., Button, NavBar)');
  }

  if (!input.description) {
    errors.push('Missing required field: description');
  } else if (input.description.length < 10) {
    errors.push('Description too short (minimum 10 characters)');
  } else if (input.description.length > 2000) {
    errors.push('Description too long (maximum 2000 characters)');
  }

  // Validate optional fields
  if (input.category && !nlpInputSchema.properties.category.enum.includes(input.category)) {
    errors.push(`Invalid category: ${input.category}. Valid: ${nlpInputSchema.properties.category.enum.join(', ')}`);
  }

  if (input.framework && !nlpInputSchema.properties.framework.enum.includes(input.framework)) {
    errors.push(`Invalid framework: ${input.framework}. Valid: ${nlpInputSchema.properties.framework.enum.join(', ')}`);
  }

  // Validate arrays
  if (input.variants && !Array.isArray(input.variants)) {
    errors.push('variants must be an array of strings');
  }

  if (input.sizes && !Array.isArray(input.sizes)) {
    errors.push('sizes must be an array of strings');
  }

  if (input.states && !Array.isArray(input.states)) {
    errors.push('states must be an array of strings');
  }

  // Validate colors object
  if (input.colors && typeof input.colors !== 'object') {
    errors.push('colors must be an object mapping color names to values');
  }

  // Validate refinement object
  if (input.refinement) {
    if (typeof input.refinement !== 'object') {
      errors.push('refinement must be an object');
    } else {
      if (input.refinement.previousId && typeof input.refinement.previousId !== 'string') {
        errors.push('refinement.previousId must be a string');
      }
      if (input.refinement.feedback && typeof input.refinement.feedback !== 'string') {
        errors.push('refinement.feedback must be a string');
      }
      if (input.refinement.keepFields && !Array.isArray(input.refinement.keepFields)) {
        errors.push('refinement.keepFields must be an array');
      }
    }
  }

  return {
    valid: errors.length === 0,
    errors
  };
}

/**
 * Infer category from name and description
 * Uses word boundary matching to avoid false positives (e.g., 'tab' in 'table')
 * @param {string} name - Component name
 * @param {string} description - Component description
 * @returns {string} Inferred category
 */
function inferCategory(name, description) {
  const lowercaseName = name.toLowerCase();
  const lowercaseDesc = description.toLowerCase();

  // Check with word boundary matching to avoid partial matches
  for (const [category, hints] of Object.entries(categoryHints)) {
    for (const hint of hints) {
      // Create word boundary regex for the hint
      const wordRegex = new RegExp(`\\b${hint}\\b`, 'i');
      if (wordRegex.test(lowercaseName) || wordRegex.test(lowercaseDesc)) {
        return category;
      }
    }
  }

  return 'component';
}

/**
 * Normalize input with defaults
 * @param {Object} input - Raw input
 * @returns {Object} Normalized input with defaults
 */
function normalizeInput(input) {
  return {
    name: input.name,
    description: input.description,
    category: input.category || inferCategory(input.name, input.description),
    variants: input.variants || [],
    sizes: input.sizes || [],
    states: input.states || ['default', 'hover', 'disabled'],
    colors: input.colors || {},
    framework: input.framework || 'react',
    refinement: input.refinement || null
  };
}

/**
 * Parse description to extract hints
 * @param {string} description - Component description
 * @returns {Object} Extracted hints
 */
function parseDescriptionHints(description) {
  const hints = {
    variants: [],
    sizes: [],
    states: [],
    elements: [],
    interactions: []
  };

  const lowercaseDesc = description.toLowerCase();

  // Extract variant hints
  const variantPatterns = {
    primary: /\bprimary\b/,
    secondary: /\bsecondary\b/,
    outline: /\boutline[d]?\b/,
    ghost: /\bghost\b/,
    destructive: /\bdestructive\b|\bdanger\b|\berror\b/,
    success: /\bsuccess\b/,
    warning: /\bwarning\b/
  };

  for (const [variant, pattern] of Object.entries(variantPatterns)) {
    if (pattern.test(lowercaseDesc)) {
      hints.variants.push(variant);
    }
  }

  // Extract size hints
  const sizePatterns = {
    sm: /\bsmall\b|\bsm\b|\bcompact\b/,
    md: /\bmedium\b|\bmd\b|\bdefault\s+size\b/,
    lg: /\blarge\b|\blg\b/,
    xl: /\bextra\s*large\b|\bxl\b/,
    icon: /\bicon\s*only\b|\bicon\s*button\b/
  };

  for (const [size, pattern] of Object.entries(sizePatterns)) {
    if (pattern.test(lowercaseDesc)) {
      hints.sizes.push(size);
    }
  }

  // Extract state hints
  const statePatterns = {
    hover: /\bhover\b/,
    active: /\bactive\b|\bpressed\b/,
    focus: /\bfocus\b/,
    disabled: /\bdisabled\b/,
    loading: /\bloading\b|\bspinner\b/
  };

  for (const [state, pattern] of Object.entries(statePatterns)) {
    if (pattern.test(lowercaseDesc)) {
      hints.states.push(state);
    }
  }

  // Extract element hints
  const elementPatterns = {
    icon: /\bicon\b/,
    image: /\bimage\b|\bpicture\b|\bphoto\b|\bthumbnail\b/,
    text: /\btext\b|\blabel\b|\btitle\b/,
    button: /\bbutton\b|\bcta\b|\baction\b/,
    input: /\binput\b|\bfield\b/,
    avatar: /\bavatar\b/,
    badge: /\bbadge\b|\btag\b/
  };

  for (const [element, pattern] of Object.entries(elementPatterns)) {
    if (pattern.test(lowercaseDesc)) {
      hints.elements.push(element);
    }
  }

  // Extract interaction hints
  const interactionPatterns = {
    clickable: /\bclick\b|\btap\b/,
    hoverable: /\bhover\b/,
    draggable: /\bdrag\b|\bdraggable\b/,
    expandable: /\bexpand\b|\bcollapse\b|\baccordion\b/,
    dismissible: /\bdismiss(?:ed|ible)?\b|\bclose[d]?\b/
  };

  for (const [interaction, pattern] of Object.entries(interactionPatterns)) {
    if (pattern.test(lowercaseDesc)) {
      hints.interactions.push(interaction);
    }
  }

  return hints;
}

/**
 * Format validation errors as readable message
 * @param {Array} errors - Array of error strings
 * @returns {string} Formatted error message
 */
function formatValidationErrors(errors) {
  if (errors.length === 0) return '';

  return [
    'Input validation failed:',
    ...errors.map(e => `  • ${e}`)
  ].join('\n');
}

/**
 * Create example input for a component type
 * @param {string} componentType - Type of component
 * @returns {Object} Example input
 */
function createExampleInput(componentType) {
  const examples = {
    button: {
      name: 'Button',
      description: 'A primary button with rounded corners, hover effect, and optional loading state',
      category: 'button',
      variants: ['primary', 'secondary', 'outline', 'ghost', 'destructive'],
      sizes: ['sm', 'md', 'lg', 'icon'],
      states: ['default', 'hover', 'active', 'disabled', 'loading']
    },
    card: {
      name: 'Card',
      description: 'A card component with header, content area, and optional footer with actions',
      category: 'card',
      variants: ['default', 'outlined', 'elevated'],
      sizes: ['sm', 'md', 'lg']
    },
    input: {
      name: 'Input',
      description: 'A text input field with label, placeholder, and validation states',
      category: 'input',
      variants: ['default', 'filled', 'outlined'],
      sizes: ['sm', 'md', 'lg'],
      states: ['default', 'focus', 'error', 'disabled']
    },
    modal: {
      name: 'Modal',
      description: 'A modal dialog with header, content, and action buttons. Includes overlay backdrop.',
      category: 'overlay',
      variants: ['default', 'alert', 'fullscreen'],
      sizes: ['sm', 'md', 'lg', 'full']
    }
  };

  return examples[componentType] || examples.button;
}

module.exports = {
  nlpInputSchema,
  validateInput,
  normalizeInput,
  inferCategory,
  parseDescriptionHints,
  formatValidationErrors,
  createExampleInput,
  categoryHints
};
