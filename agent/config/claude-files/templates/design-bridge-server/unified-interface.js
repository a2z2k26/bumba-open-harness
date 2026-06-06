/**
 * unified-interface.js
 * Unified Extraction Interface for Design Bridge
 * Defines common input/output contracts for all extraction methods
 */

/**
 * Supported extraction methods
 */
const ExtractionMethods = {
  FIGMA_PLUGIN: 'figma-plugin',
  FIGMA_MCP: 'figma-mcp',
  SHADCN: 'shadcn',
  NLP_PROMPT: 'nlp-prompt',
  MANUAL: 'manual'
};

/**
 * Unified Input Schema
 * All extraction methods accept this format
 */
const UnifiedInputSchema = {
  // Required
  method: {
    type: 'enum',
    values: Object.values(ExtractionMethods),
    required: true,
    description: 'Extraction method to use'
  },

  // Method-specific target (one required based on method)
  target: {
    type: 'string',
    required: true,
    description: 'URL, component name, description, or JSON specification'
  },

  // Options (all optional)
  options: {
    framework: {
      type: 'enum',
      values: ['react', 'vue', 'svelte', 'angular'],
      default: 'react'
    },
    outputDir: {
      type: 'string',
      default: '.design'
    },
    generateStory: {
      type: 'boolean',
      default: false
    },
    generateCode: {
      type: 'boolean',
      default: true
    },
    updateExisting: {
      type: 'enum',
      values: ['update', 'merge', 'skip', 'new'],
      default: 'update'
    },
    trackHistory: {
      type: 'boolean',
      default: true
    }
  }
};

/**
 * Unified Output Schema
 * All extraction methods return this format
 */
const UnifiedOutputSchema = {
  success: 'boolean',
  method: 'string',
  timestamp: 'string (ISO)',

  // Component data (on success)
  component: {
    id: 'string',
    name: 'string',
    type: 'COMPONENT | COMPONENT_SET | FRAME',
    category: 'string',
    source: {
      type: 'string (method)',
      extractedAt: 'string (ISO)'
      // method-specific additional fields
    },
    paths: {
      rawSource: 'string (path)',
      component: 'string (path)',
      generated: 'string (path) | null',
      story: 'string (path) | null'
    }
  },

  // Warnings and errors
  warnings: ['string'],
  errors: ['string'],

  // Extraction metadata
  metadata: {
    duration: 'number (ms)',
    normalizedFields: 'number',
    tokensExtracted: 'number'
  }
};

/**
 * Known ShadCN component names for detection
 */
const SHADCN_COMPONENTS = [
  'accordion', 'alert', 'alert-dialog', 'aspect-ratio', 'avatar',
  'badge', 'button', 'calendar', 'card', 'carousel', 'checkbox',
  'collapsible', 'combobox', 'command', 'context-menu', 'data-table',
  'date-picker', 'dialog', 'drawer', 'dropdown-menu', 'form',
  'hover-card', 'input', 'label', 'menubar', 'navigation-menu',
  'pagination', 'popover', 'progress', 'radio-group', 'resizable',
  'scroll-area', 'select', 'separator', 'sheet', 'skeleton',
  'slider', 'sonner', 'switch', 'table', 'tabs', 'textarea',
  'toast', 'toggle', 'toggle-group', 'tooltip'
];

/**
 * Normalize input across methods
 * @param {Object|string} rawInput - Raw input (string or object)
 * @returns {Object} Normalized input object
 */
function normalizeInput(rawInput) {
  // Handle string input (auto-detect method)
  if (typeof rawInput === 'string') {
    return detectMethodFromTarget(rawInput);
  }

  // Validate input is an object
  if (typeof rawInput !== 'object' || rawInput === null) {
    throw new Error('Input must be a string or object');
  }

  // Validate required fields
  if (!rawInput.method && !rawInput.target) {
    throw new Error('Input must specify method or target');
  }

  // Auto-detect method from target if not specified
  if (!rawInput.method && rawInput.target) {
    const detected = detectMethodFromTarget(rawInput.target);
    rawInput.method = detected.method;
  }

  // Apply defaults
  return {
    method: rawInput.method,
    target: rawInput.target,
    options: {
      framework: rawInput.options?.framework || 'react',
      outputDir: rawInput.options?.outputDir || '.design',
      generateStory: rawInput.options?.generateStory ?? false,
      generateCode: rawInput.options?.generateCode ?? true,
      updateExisting: rawInput.options?.updateExisting || 'update',
      trackHistory: rawInput.options?.trackHistory ?? true
    }
  };
}

/**
 * Detect extraction method from target string
 * @param {string|Object} target - Target to detect method from
 * @returns {Object} Object with method and target
 */
function detectMethodFromTarget(target) {
  // If target is an object, it's likely manual/JSON spec
  if (typeof target === 'object') {
    return {
      method: ExtractionMethods.MANUAL,
      target: target
    };
  }

  // Figma URL
  if (isFigmaUrl(target)) {
    return {
      method: ExtractionMethods.FIGMA_MCP,
      target: target
    };
  }

  // ShadCN component name (simple identifier)
  if (isShadcnComponent(target)) {
    return {
      method: ExtractionMethods.SHADCN,
      target: target
    };
  }

  // JSON specification (JSON string)
  if (isJsonSpec(target)) {
    return {
      method: ExtractionMethods.MANUAL,
      target: target
    };
  }

  // Natural language (default fallback for descriptive text)
  return {
    method: ExtractionMethods.NLP_PROMPT,
    target: target
  };
}

/**
 * Check if target is a Figma URL
 * @param {string} target - Target string
 * @returns {boolean} True if Figma URL
 */
function isFigmaUrl(target) {
  if (typeof target !== 'string') return false;

  const figmaPatterns = [
    /figma\.com\/file\//i,
    /figma\.com\/design\//i,
    /figma\.com\/proto\//i
  ];
  return figmaPatterns.some(pattern => pattern.test(target));
}

/**
 * Check if target is a ShadCN component name
 * @param {string} target - Target string
 * @returns {boolean} True if ShadCN component
 */
function isShadcnComponent(target) {
  if (typeof target !== 'string') return false;

  const normalizedTarget = target.toLowerCase().trim();

  // Check against known ShadCN components
  if (SHADCN_COMPONENTS.includes(normalizedTarget)) {
    return true;
  }

  // ShadCN components are typically lowercase, single words or hyphenated
  // Short identifier pattern (less than 30 chars, lowercase alphanumeric with hyphens)
  return /^[a-z][a-z0-9-]*$/.test(normalizedTarget) && normalizedTarget.length < 30;
}

/**
 * Check if target is a JSON specification
 * @param {string|Object} target - Target to check
 * @returns {boolean} True if JSON spec
 */
function isJsonSpec(target) {
  if (typeof target === 'object') return true;

  if (typeof target !== 'string') return false;

  // Check if it starts with { (JSON object)
  const trimmed = target.trim();
  if (!trimmed.startsWith('{')) return false;

  try {
    const parsed = JSON.parse(trimmed);
    // Must have a name property to be considered a component spec
    return typeof parsed === 'object' && parsed !== null && parsed.name;
  } catch {
    return false;
  }
}

/**
 * Create unified output from method-specific result
 * @param {Object} result - Method-specific result
 * @param {string} method - Extraction method used
 * @param {number} startTime - Extraction start timestamp
 * @returns {Object} Unified output
 */
function createUnifiedOutput(result, method, startTime) {
  const duration = Date.now() - startTime;

  return {
    success: result.success !== false,
    method: method,
    timestamp: new Date().toISOString(),

    component: result.success !== false ? {
      id: result.component?.id || result.id,
      name: result.component?.name || result.name,
      type: result.component?.type || result.type || 'COMPONENT',
      category: result.component?.category || result.category || 'utility',
      source: {
        type: method,
        extractedAt: new Date().toISOString(),
        ...(result.source || result.component?.source || {})
      },
      paths: {
        rawSource: result.paths?.rawSource || result.component?.paths?.rawSource || null,
        component: result.paths?.component || result.component?.paths?.component || null,
        generated: result.paths?.generated || result.component?.paths?.generated || null,
        story: result.paths?.story || result.component?.paths?.story || null
      }
    } : null,

    warnings: result.warnings || [],
    errors: result.errors || [],

    metadata: {
      duration,
      normalizedFields: countNormalizedFields(result),
      tokensExtracted: countTokens(result)
    }
  };
}

/**
 * Count normalized fields in result
 * @param {Object} result - Extraction result
 * @returns {number} Count of normalized fields
 */
function countNormalizedFields(result) {
  const component = result.component || result;
  if (!component) return 0;

  let count = 0;
  const fields = ['id', 'name', 'type', 'category', 'source', 'tokenDependencies',
                  'children', 'variants', 'interactiveStates', 'props', 'structure'];

  for (const field of fields) {
    if (component[field] !== undefined) count++;
  }

  return count;
}

/**
 * Count extracted tokens
 * @param {Object} result - Extraction result
 * @returns {number} Count of tokens
 */
function countTokens(result) {
  const component = result.component || result;
  const deps = component?.tokenDependencies;
  if (!deps) return 0;

  let count = 0;
  for (const category of Object.values(deps)) {
    if (Array.isArray(category)) {
      count += category.length;
    }
  }
  return count;
}

/**
 * Validate unified output meets schema
 * @param {Object} output - Output to validate
 * @returns {Object} Validation result { valid: boolean, errors: string[] }
 */
function validateOutput(output) {
  const errors = [];

  if (typeof output.success !== 'boolean') {
    errors.push('Missing or invalid success field');
  }

  if (!output.method) {
    errors.push('Missing method field');
  }

  if (!output.timestamp) {
    errors.push('Missing timestamp field');
  }

  if (output.success && !output.component) {
    errors.push('Success response missing component data');
  }

  if (output.success && output.component) {
    if (!output.component.id) errors.push('Component missing id');
    if (!output.component.name) errors.push('Component missing name');
    if (!output.component.source?.type) errors.push('Component missing source.type');
  }

  if (!Array.isArray(output.warnings)) {
    errors.push('Missing or invalid warnings array');
  }

  if (!Array.isArray(output.errors)) {
    errors.push('Missing or invalid errors array');
  }

  return {
    valid: errors.length === 0,
    errors
  };
}

/**
 * Validate input against schema
 * @param {Object} input - Input to validate
 * @returns {Object} Validation result { valid: boolean, errors: string[] }
 */
function validateInput(input) {
  const errors = [];

  if (!input) {
    errors.push('Input is required');
    return { valid: false, errors };
  }

  if (!input.method && !input.target) {
    errors.push('Input must have method or target');
  }

  if (input.method && !Object.values(ExtractionMethods).includes(input.method)) {
    errors.push(`Invalid method: ${input.method}`);
  }

  if (input.options) {
    if (input.options.framework && !['react', 'vue', 'svelte', 'angular'].includes(input.options.framework)) {
      errors.push(`Invalid framework: ${input.options.framework}`);
    }

    if (input.options.updateExisting && !['update', 'merge', 'skip', 'new'].includes(input.options.updateExisting)) {
      errors.push(`Invalid updateExisting: ${input.options.updateExisting}`);
    }
  }

  return {
    valid: errors.length === 0,
    errors
  };
}

/**
 * Get method display name
 * @param {string} method - Method key
 * @returns {string} Human-readable method name
 */
function getMethodDisplayName(method) {
  const names = {
    [ExtractionMethods.FIGMA_PLUGIN]: 'Figma Plugin',
    [ExtractionMethods.FIGMA_MCP]: 'Figma MCP',
    [ExtractionMethods.SHADCN]: 'ShadCN Registry',
    [ExtractionMethods.NLP_PROMPT]: 'NLP Prompting',
    [ExtractionMethods.MANUAL]: 'Manual Specification'
  };
  return names[method] || method;
}

/**
 * Get all extraction methods as array
 * @returns {Array} Array of method objects { key, value, displayName }
 */
function getAllMethods() {
  return Object.entries(ExtractionMethods).map(([key, value]) => ({
    key,
    value,
    displayName: getMethodDisplayName(value)
  }));
}

module.exports = {
  // Constants
  ExtractionMethods,
  UnifiedInputSchema,
  UnifiedOutputSchema,
  SHADCN_COMPONENTS,

  // Core functions
  normalizeInput,
  detectMethodFromTarget,
  createUnifiedOutput,

  // Detection functions
  isFigmaUrl,
  isShadcnComponent,
  isJsonSpec,

  // Validation
  validateOutput,
  validateInput,

  // Utilities
  countNormalizedFields,
  countTokens,
  getMethodDisplayName,
  getAllMethods
};
