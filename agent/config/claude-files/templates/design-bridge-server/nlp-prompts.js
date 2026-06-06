/**
 * nlp-prompts.js
 * NLP Component Generation Prompts
 * Templates for LLM-based component generation
 */

/**
 * Base component generation prompt
 */
const componentGenerationPrompt = `
You are a design system expert generating component definitions for the Design Bridge system.

## Input
Component Name: {{name}}
Description: {{description}}
Category: {{category}}
Framework Target: {{framework}}
{{#if variants}}Requested Variants: {{variants}}{{/if}}
{{#if sizes}}Requested Sizes: {{sizes}}{{/if}}
{{#if states}}Requested States: {{states}}{{/if}}

## Task
Generate a complete Design Bridge component definition based on the description.

## Output Format
Return a JSON object with this exact structure:
{
  "id": "nlp-{{kebabCase name}}-{{timestamp}}",
  "name": "{{name}}",
  "type": "COMPONENT",
  "category": "{{category}}",
  "description": "{{description}}",

  "source": {
    "type": "nlp-prompt",
    "extractedAt": "{{isoTimestamp}}",
    "prompt": "{{description}}"
  },

  "structure": {
    "type": "FRAME",
    "name": "{{name}}",
    "layout": "flex-row|flex-col|grid",
    "children": [
      // Nested structure based on description
    ]
  },

  "tokenDependencies": {
    "colors": ["Primary/500", "Neutral/100"],
    "typography": ["text-sm", "font-medium"],
    "spacing": ["4", "8", "16"],
    "borderRadius": ["md"]
  },

  "variants": {
    // Variant definitions with style changes
  },

  "props": [
    // Inferred prop definitions
  ],

  "interactiveStates": ["default", "hover", "disabled"]
}

## Guidelines
1. Structure should reflect the visual hierarchy described
2. Token dependencies should use design system tokens
3. Variants should have distinct visual differences
4. Props should match common patterns for the component type
5. Include accessibility considerations

Return ONLY the JSON object, no explanation.
`;

/**
 * Structure generation prompt (for complex components)
 */
const structurePrompt = `
Given this component description, generate the nested structure:

Description: {{description}}

Rules:
1. Use FRAME for containers
2. Use TEXT for text elements
3. Use IMAGE for images
4. Use COMPONENT for referenced components
5. Specify layout (flex-row, flex-col, grid)
6. Include padding/spacing hints

Example output:
{
  "type": "FRAME",
  "name": "Card",
  "layout": "flex-col",
  "children": [
    { "type": "IMAGE", "name": "HeaderImage", "fill": "cover" },
    { "type": "FRAME", "name": "Content", "layout": "flex-col", "gap": 8, "children": [
      { "type": "TEXT", "name": "Title", "style": "heading" },
      { "type": "TEXT", "name": "Description", "style": "body" }
    ]},
    { "type": "FRAME", "name": "Actions", "layout": "flex-row", "gap": 4, "children": [
      { "type": "COMPONENT", "name": "ActionButton", "ref": "Button" }
    ]}
  ]
}

Return ONLY the JSON structure.
`;

/**
 * Token inference prompt
 */
const tokenInferencePrompt = `
Based on this component description, infer the design tokens needed:

Description: {{description}}
Category: {{category}}

Token Categories:
- colors: Background, text, border, accent colors
- typography: Font sizes, weights, line heights
- spacing: Padding, margins, gaps
- borderRadius: Corner rounding
- shadows: Drop shadows, box shadows

Return a JSON object with arrays for each category:
{
  "colors": ["Primary/500", "Neutral/100", "Neutral/900"],
  "typography": ["text-sm", "font-medium"],
  "spacing": ["4", "8", "16"],
  "borderRadius": ["md"],
  "shadows": ["shadow-sm"]
}

Use standard design system token names.
`;

/**
 * Variant generation prompt
 */
const variantPrompt = `
Generate variant definitions for this component:

Component: {{name}}
Description: {{description}}
Requested Variants: {{variants}}

For each variant, specify:
- name: Variant name
- properties: Props that identify this variant
- tokenOverrides: Token changes for this variant

Example output:
{
  "variant": {
    "primary": {
      "properties": { "variant": "primary" },
      "tokenOverrides": {
        "backgroundColor": "Primary/500",
        "textColor": "White"
      }
    },
    "secondary": {
      "properties": { "variant": "secondary" },
      "tokenOverrides": {
        "backgroundColor": "Secondary/500",
        "textColor": "White"
      }
    },
    "outline": {
      "properties": { "variant": "outline" },
      "tokenOverrides": {
        "backgroundColor": "transparent",
        "borderColor": "Primary/500",
        "textColor": "Primary/500"
      }
    }
  }
}

Return ONLY the JSON object.
`;

/**
 * Props inference prompt
 */
const propsPrompt = `
Infer the TypeScript props interface for this component:

Component: {{name}}
Category: {{category}}
Description: {{description}}
Variants: {{variants}}

Generate props that:
1. Are common for this component type
2. Support the described functionality
3. Include TypeScript types
4. Have reasonable defaults

Example output:
{
  "props": [
    {
      "name": "children",
      "type": "React.ReactNode",
      "required": true,
      "description": "Button content"
    },
    {
      "name": "variant",
      "type": "'primary' | 'secondary' | 'outline'",
      "required": false,
      "default": "'primary'",
      "description": "Visual variant"
    },
    {
      "name": "size",
      "type": "'sm' | 'md' | 'lg'",
      "required": false,
      "default": "'md'",
      "description": "Button size"
    },
    {
      "name": "disabled",
      "type": "boolean",
      "required": false,
      "default": "false",
      "description": "Disabled state"
    },
    {
      "name": "onClick",
      "type": "() => void",
      "required": false,
      "description": "Click handler"
    }
  ]
}

Return ONLY the JSON object.
`;

/**
 * Accessibility prompt
 */
const accessibilityPrompt = `
Add accessibility requirements for this component:

Component: {{name}}
Category: {{category}}
Description: {{description}}

Specify:
- role: ARIA role
- requiredProps: Required ARIA props
- keyboardInteraction: Keyboard handling
- focusManagement: Focus behavior

Example output:
{
  "accessibility": {
    "role": "button",
    "requiredProps": ["aria-label"],
    "keyboardInteraction": {
      "Enter": "activate",
      "Space": "activate"
    },
    "focusManagement": "focusable",
    "notes": ["Ensure sufficient color contrast", "Provide visible focus indicator"]
  }
}

Return ONLY the JSON object.
`;

/**
 * Compile prompt with context
 * @param {string} template - Prompt template
 * @param {Object} context - Context values
 * @returns {string} Compiled prompt
 */
function compilePrompt(template, context) {
  let compiled = template;

  // Replace simple placeholders
  for (const [key, value] of Object.entries(context)) {
    const placeholder = new RegExp(`\\{\\{${key}\\}\\}`, 'g');
    const stringValue = Array.isArray(value) ? value.join(', ') : (value || '');
    compiled = compiled.replace(placeholder, stringValue);
  }

  // Handle conditionals {{#if field}}...{{/if}}
  compiled = compiled.replace(/\{\{#if (\w+)\}\}([\s\S]*?)\{\{\/if\}\}/g, (match, field, content) => {
    const fieldValue = context[field];
    const hasValue = Array.isArray(fieldValue) ? fieldValue.length > 0 : Boolean(fieldValue);
    return hasValue ? content : '';
  });

  // Handle helpers
  compiled = compiled.replace(/\{\{kebabCase (\w+)\}\}/g, (match, field) => {
    return toKebabCase(context[field] || '');
  });

  compiled = compiled.replace(/\{\{timestamp\}\}/g, Date.now().toString());
  compiled = compiled.replace(/\{\{isoTimestamp\}\}/g, new Date().toISOString());

  return compiled.trim();
}

/**
 * Convert string to kebab-case
 * @param {string} str - Input string
 * @returns {string} kebab-case string
 */
function toKebabCase(str) {
  return str
    .replace(/([a-z])([A-Z])/g, '$1-$2')
    .replace(/([0-9])([A-Z])/g, '$1-$2')
    .replace(/\s+/g, '-')
    .toLowerCase();
}

/**
 * Get all available prompts
 * @returns {Object} All prompt templates
 */
function getAllPrompts() {
  return {
    componentGeneration: componentGenerationPrompt,
    structure: structurePrompt,
    tokenInference: tokenInferencePrompt,
    variant: variantPrompt,
    props: propsPrompt,
    accessibility: accessibilityPrompt
  };
}

/**
 * Create a full generation context
 * @param {Object} input - Normalized input
 * @returns {Object} Full context for prompt compilation
 */
function createGenerationContext(input) {
  return {
    name: input.name,
    description: input.description,
    category: input.category,
    framework: input.framework || 'react',
    variants: input.variants || [],
    sizes: input.sizes || [],
    states: input.states || []
  };
}

module.exports = {
  componentGenerationPrompt,
  structurePrompt,
  tokenInferencePrompt,
  variantPrompt,
  propsPrompt,
  accessibilityPrompt,
  compilePrompt,
  toKebabCase,
  getAllPrompts,
  createGenerationContext
};
