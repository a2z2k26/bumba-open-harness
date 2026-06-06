/**
 * JSON Schema Validation Module
 * Phase 3 - Sprints 141-152: Input/Output Validation
 *
 * Provides schema-based validation for all pipeline inputs and outputs
 * to ensure data integrity throughout the transformation process.
 */

const { ValidationError, SchemaValidationError } = require('./error-types');
const { createLogger } = require('./unified-logger');

const logger = createLogger('schema-validator');

// =============================================================================
// JSON SCHEMA DEFINITIONS
// =============================================================================

/**
 * Figma component input schema
 */
const FIGMA_COMPONENT_SCHEMA = {
  type: 'object',
  required: ['id', 'name', 'type'],
  properties: {
    id: { type: 'string', minLength: 1 },
    name: { type: 'string', minLength: 1 },
    type: {
      type: 'string',
      enum: ['COMPONENT', 'COMPONENT_SET', 'FRAME', 'GROUP', 'INSTANCE', 'TEXT', 'RECTANGLE', 'ELLIPSE', 'LINE', 'VECTOR']
    },
    children: {
      type: 'array',
      items: { $ref: '#' }
    },
    fills: { type: 'array' },
    strokes: { type: 'array' },
    effects: { type: 'array' },
    cornerRadius: { type: 'number' },
    absoluteBoundingBox: {
      type: 'object',
      properties: {
        x: { type: 'number' },
        y: { type: 'number' },
        width: { type: 'number' },
        height: { type: 'number' }
      }
    },
    layoutMode: {
      type: 'string',
      enum: ['NONE', 'HORIZONTAL', 'VERTICAL']
    },
    itemSpacing: { type: 'number' },
    paddingTop: { type: 'number' },
    paddingRight: { type: 'number' },
    paddingBottom: { type: 'number' },
    paddingLeft: { type: 'number' }
  }
};

/**
 * Token file schema
 */
const TOKEN_SCHEMA = {
  type: 'object',
  additionalProperties: {
    anyOf: [
      { $ref: '#/definitions/tokenValue' },
      { $ref: '#/definitions/tokenGroup' }
    ]
  },
  definitions: {
    tokenValue: {
      type: 'object',
      required: ['value'],
      properties: {
        value: { type: ['string', 'number'] },
        type: { type: 'string' },
        description: { type: 'string' }
      }
    },
    tokenGroup: {
      type: 'object',
      additionalProperties: {
        anyOf: [
          { $ref: '#/definitions/tokenValue' },
          { $ref: '#/definitions/tokenGroup' }
        ]
      }
    }
  }
};

/**
 * Component registry entry schema (v4.0.0)
 */
const REGISTRY_ENTRY_SCHEMA = {
  type: 'object',
  required: ['id', 'name', 'source'],
  properties: {
    id: { type: 'string', minLength: 1 },
    name: { type: 'string', minLength: 1 },
    source: {
      type: 'string',
      enum: ['figma', 'shadcn', 'nlp', 'manual', 'code']
    },
    figmaNodeId: { type: 'string' },
    shadcnName: { type: 'string' },
    category: { type: 'string' },
    transformedTo: {
      type: 'array',
      items: { type: 'string' }
    },
    outputPaths: {
      type: 'object',
      additionalProperties: { type: 'string' }
    },
    metadata: { type: 'object' },
    syncMetadata: {
      type: 'object',
      properties: {
        lastSynced: { type: 'string', format: 'date-time' },
        version: { type: 'string' },
        contentHash: { type: 'string' }
      }
    }
  }
};

/**
 * Generated component output schema
 */
const GENERATED_COMPONENT_SCHEMA = {
  type: 'object',
  required: ['name', 'code', 'framework'],
  properties: {
    name: { type: 'string', minLength: 1 },
    code: { type: 'string', minLength: 1 },
    framework: { type: 'string', minLength: 1 },
    styles: { type: 'object' },
    props: {
      type: 'object',
      additionalProperties: {
        type: 'object',
        properties: {
          type: { type: 'string' },
          default: {},
          required: { type: 'boolean' },
          description: { type: 'string' }
        }
      }
    },
    variants: { type: 'array' },
    accessibility: { type: 'object' },
    dependencies: {
      type: 'array',
      items: { type: 'string' }
    }
  }
};

/**
 * Story file output schema
 */
const STORY_SCHEMA = {
  type: 'object',
  required: ['componentName', 'content'],
  properties: {
    componentName: { type: 'string', minLength: 1 },
    content: { type: 'string', minLength: 1 },
    framework: { type: 'string' },
    argTypes: { type: 'object' },
    args: { type: 'object' },
    variants: {
      type: 'array',
      items: { type: 'string' }
    }
  }
};

// =============================================================================
// VALIDATION ENGINE
// =============================================================================

/**
 * Validate a value against a JSON schema
 */
function validate(data, schema, options = {}) {
  const errors = [];
  const path = options.path || '$';

  // Null check
  if (data === null || data === undefined) {
    if (schema.nullable !== true) {
      errors.push({
        path,
        message: `Value at ${path} is ${data === null ? 'null' : 'undefined'}`,
        keyword: 'type',
        expected: schema.type || 'value'
      });
    }
    return { valid: errors.length === 0, errors };
  }

  // Type validation
  if (schema.type) {
    const types = Array.isArray(schema.type) ? schema.type : [schema.type];
    const actualType = Array.isArray(data) ? 'array' : typeof data;

    if (!types.includes(actualType)) {
      errors.push({
        path,
        message: `Expected ${types.join(' or ')} at ${path}, got ${actualType}`,
        keyword: 'type',
        expected: types,
        actual: actualType
      });
      // Early return for type mismatch unless lenient mode
      if (!options.lenient) {
        return { valid: false, errors };
      }
    }
  }

  // Enum validation
  if (schema.enum && !schema.enum.includes(data)) {
    errors.push({
      path,
      message: `Value at ${path} must be one of: ${schema.enum.join(', ')}`,
      keyword: 'enum',
      expected: schema.enum,
      actual: data
    });
  }

  // String validations
  if (typeof data === 'string') {
    if (schema.minLength !== undefined && data.length < schema.minLength) {
      errors.push({
        path,
        message: `String at ${path} must be at least ${schema.minLength} characters`,
        keyword: 'minLength',
        expected: schema.minLength,
        actual: data.length
      });
    }
    if (schema.maxLength !== undefined && data.length > schema.maxLength) {
      errors.push({
        path,
        message: `String at ${path} must be at most ${schema.maxLength} characters`,
        keyword: 'maxLength',
        expected: schema.maxLength,
        actual: data.length
      });
    }
    if (schema.pattern) {
      const regex = new RegExp(schema.pattern);
      if (!regex.test(data)) {
        errors.push({
          path,
          message: `String at ${path} must match pattern: ${schema.pattern}`,
          keyword: 'pattern',
          pattern: schema.pattern
        });
      }
    }
  }

  // Number validations
  if (typeof data === 'number') {
    if (schema.minimum !== undefined && data < schema.minimum) {
      errors.push({
        path,
        message: `Number at ${path} must be >= ${schema.minimum}`,
        keyword: 'minimum',
        expected: schema.minimum,
        actual: data
      });
    }
    if (schema.maximum !== undefined && data > schema.maximum) {
      errors.push({
        path,
        message: `Number at ${path} must be <= ${schema.maximum}`,
        keyword: 'maximum',
        expected: schema.maximum,
        actual: data
      });
    }
  }

  // Array validations
  if (Array.isArray(data)) {
    if (schema.minItems !== undefined && data.length < schema.minItems) {
      errors.push({
        path,
        message: `Array at ${path} must have at least ${schema.minItems} items`,
        keyword: 'minItems',
        expected: schema.minItems,
        actual: data.length
      });
    }
    if (schema.items) {
      data.forEach((item, index) => {
        const itemPath = `${path}[${index}]`;
        const itemResult = validate(item, schema.items, { ...options, path: itemPath });
        errors.push(...itemResult.errors);
      });
    }
  }

  // Object validations
  if (typeof data === 'object' && data !== null && !Array.isArray(data)) {
    // Required properties
    if (schema.required) {
      for (const prop of schema.required) {
        if (!(prop in data)) {
          errors.push({
            path: `${path}.${prop}`,
            message: `Missing required property: ${prop}`,
            keyword: 'required',
            property: prop
          });
        }
      }
    }

    // Property validation
    if (schema.properties) {
      for (const [prop, propSchema] of Object.entries(schema.properties)) {
        if (prop in data) {
          const propPath = `${path}.${prop}`;
          const propResult = validate(data[prop], propSchema, { ...options, path: propPath });
          errors.push(...propResult.errors);
        }
      }
    }

    // Additional properties validation
    if (schema.additionalProperties !== undefined) {
      const knownProps = new Set(Object.keys(schema.properties || {}));
      for (const prop of Object.keys(data)) {
        if (!knownProps.has(prop)) {
          if (schema.additionalProperties === false) {
            errors.push({
              path: `${path}.${prop}`,
              message: `Additional property not allowed: ${prop}`,
              keyword: 'additionalProperties',
              property: prop
            });
          } else if (typeof schema.additionalProperties === 'object') {
            const propPath = `${path}.${prop}`;
            const propResult = validate(data[prop], schema.additionalProperties, { ...options, path: propPath });
            errors.push(...propResult.errors);
          }
        }
      }
    }
  }

  return {
    valid: errors.length === 0,
    errors
  };
}

// =============================================================================
// HIGH-LEVEL VALIDATORS
// =============================================================================

/**
 * Validate Figma component input
 */
function validateFigmaComponent(data, options = {}) {
  const result = validate(data, FIGMA_COMPONENT_SCHEMA, options);

  if (!result.valid && !options.silent) {
    logger.warn('Figma component validation failed', {
      errorCount: result.errors.length,
      firstError: result.errors[0]?.message
    });
  }

  return result;
}

/**
 * Validate token file
 */
function validateTokens(data, options = {}) {
  const result = validate(data, TOKEN_SCHEMA, options);

  if (!result.valid && !options.silent) {
    logger.warn('Token validation failed', {
      errorCount: result.errors.length,
      firstError: result.errors[0]?.message
    });
  }

  return result;
}

/**
 * Validate registry entry
 */
function validateRegistryEntry(data, options = {}) {
  const result = validate(data, REGISTRY_ENTRY_SCHEMA, options);

  if (!result.valid && !options.silent) {
    logger.warn('Registry entry validation failed', {
      component: data?.name,
      errorCount: result.errors.length,
      firstError: result.errors[0]?.message
    });
  }

  return result;
}

/**
 * Validate generated component output
 */
function validateGeneratedComponent(data, options = {}) {
  const result = validate(data, GENERATED_COMPONENT_SCHEMA, options);

  if (!result.valid && !options.silent) {
    logger.warn('Generated component validation failed', {
      component: data?.name,
      framework: data?.framework,
      errorCount: result.errors.length,
      firstError: result.errors[0]?.message
    });
  }

  return result;
}

/**
 * Validate story file
 */
function validateStory(data, options = {}) {
  const result = validate(data, STORY_SCHEMA, options);

  if (!result.valid && !options.silent) {
    logger.warn('Story validation failed', {
      component: data?.componentName,
      errorCount: result.errors.length,
      firstError: result.errors[0]?.message
    });
  }

  return result;
}

// =============================================================================
// VALIDATION MIDDLEWARE
// =============================================================================

/**
 * Create validation middleware for pipeline stages
 */
function createValidationMiddleware(schema, stageName) {
  return function validateMiddleware(data) {
    const result = validate(data, schema, { lenient: true });

    if (!result.valid) {
      throw new SchemaValidationError(`Validation failed at stage: ${stageName}`, {
        schemaPath: stageName,
        errors: result.errors
      });
    }

    return data;
  };
}

/**
 * Validate and throw on error
 */
function assertValid(data, schema, message = 'Validation failed') {
  const result = validate(data, schema);

  if (!result.valid) {
    throw new SchemaValidationError(message, {
      errors: result.errors
    });
  }

  return data;
}

/**
 * Validate with graceful fallback
 */
function validateWithFallback(data, schema, fallback, options = {}) {
  const result = validate(data, schema, { ...options, lenient: true });

  if (!result.valid) {
    if (options.logWarning !== false) {
      logger.warn('Validation failed, using fallback', {
        errorCount: result.errors.length,
        fallbackProvided: fallback !== undefined
      });
    }
    return { data: fallback ?? data, valid: false, errors: result.errors };
  }

  return { data, valid: true, errors: [] };
}

// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

/**
 * Check if data matches a schema (boolean result)
 */
function matches(data, schema) {
  return validate(data, schema, { silent: true }).valid;
}

/**
 * Get schema for a specific type
 */
function getSchema(type) {
  const schemas = {
    'figma-component': FIGMA_COMPONENT_SCHEMA,
    'token': TOKEN_SCHEMA,
    'registry-entry': REGISTRY_ENTRY_SCHEMA,
    'generated-component': GENERATED_COMPONENT_SCHEMA,
    'story': STORY_SCHEMA
  };

  return schemas[type] || null;
}

/**
 * List available schema types
 */
function listSchemaTypes() {
  return [
    'figma-component',
    'token',
    'registry-entry',
    'generated-component',
    'story'
  ];
}

module.exports = {
  // Core validation
  validate,
  assertValid,
  validateWithFallback,
  matches,

  // Schema-specific validators
  validateFigmaComponent,
  validateTokens,
  validateRegistryEntry,
  validateGeneratedComponent,
  validateStory,

  // Middleware
  createValidationMiddleware,

  // Schema access
  getSchema,
  listSchemaTypes,

  // Schemas (for extending)
  FIGMA_COMPONENT_SCHEMA,
  TOKEN_SCHEMA,
  REGISTRY_ENTRY_SCHEMA,
  GENERATED_COMPONENT_SCHEMA,
  STORY_SCHEMA
};
