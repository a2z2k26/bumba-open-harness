/**
 * figma-error-handler.js
 * Error handling and validation for Figma MCP extractions
 *
 * Provides robust error handling for edge cases including:
 * - Invalid/malformed Figma data
 * - Missing required fields
 * - Network/API errors
 * - Empty components
 * - Circular references
 * - Large datasets
 */

/**
 * Custom error types for Figma extraction
 */
class FigmaExtractionError extends Error {
  constructor(message, code, details = {}) {
    super(message);
    this.name = 'FigmaExtractionError';
    this.code = code;
    this.details = details;
    this.timestamp = new Date().toISOString();
  }

  toJSON() {
    return {
      name: this.name,
      code: this.code,
      message: this.message,
      details: this.details,
      timestamp: this.timestamp
    };
  }
}

/**
 * Error codes for different failure types
 */
const ErrorCodes = {
  INVALID_NODE: 'INVALID_NODE',
  MISSING_FIELD: 'MISSING_FIELD',
  INVALID_TYPE: 'INVALID_TYPE',
  EMPTY_COMPONENT: 'EMPTY_COMPONENT',
  CIRCULAR_REFERENCE: 'CIRCULAR_REFERENCE',
  DEPTH_EXCEEDED: 'DEPTH_EXCEEDED',
  VALIDATION_FAILED: 'VALIDATION_FAILED',
  PARSE_ERROR: 'PARSE_ERROR',
  NETWORK_ERROR: 'NETWORK_ERROR',
  RATE_LIMIT: 'RATE_LIMIT',
  FILE_ERROR: 'FILE_ERROR',
  UNKNOWN: 'UNKNOWN'
};

/**
 * Validate a Figma node has required fields
 * @param {Object} node - Figma node to validate
 * @param {Object} options - Validation options
 * @returns {Object} Validation result { valid, errors }
 */
function validateNode(node, options = {}) {
  const errors = [];
  const {
    requireId = true,
    requireName = true,
    requireType = true,
    allowedTypes = null
  } = options;

  // Check if node exists
  if (!node || typeof node !== 'object') {
    errors.push({
      code: ErrorCodes.INVALID_NODE,
      message: 'Node is null, undefined, or not an object',
      field: 'node'
    });
    return { valid: false, errors };
  }

  // Check required fields
  if (requireId && !node.id) {
    errors.push({
      code: ErrorCodes.MISSING_FIELD,
      message: 'Node missing required field: id',
      field: 'id'
    });
  }

  if (requireName && !node.name) {
    errors.push({
      code: ErrorCodes.MISSING_FIELD,
      message: 'Node missing required field: name',
      field: 'name'
    });
  }

  if (requireType && !node.type) {
    errors.push({
      code: ErrorCodes.MISSING_FIELD,
      message: 'Node missing required field: type',
      field: 'type'
    });
  }

  // Check allowed types
  if (allowedTypes && node.type && !allowedTypes.includes(node.type)) {
    errors.push({
      code: ErrorCodes.INVALID_TYPE,
      message: `Invalid node type: ${node.type}. Allowed: ${allowedTypes.join(', ')}`,
      field: 'type',
      actual: node.type,
      allowed: allowedTypes
    });
  }

  return {
    valid: errors.length === 0,
    errors
  };
}

/**
 * Validate component data before registry update
 * @param {Object} component - Component data to validate
 * @returns {Object} Validation result { valid, errors, warnings }
 */
function validateComponent(component) {
  const errors = [];
  const warnings = [];

  // Basic node validation
  const nodeValidation = validateNode(component, {
    requireId: true,
    requireName: true,
    requireType: false
  });
  errors.push(...nodeValidation.errors);

  // Check for empty component
  if (component && !component.children?.length &&
      !component.visual?.fills?.length &&
      !component.layout) {
    warnings.push({
      code: ErrorCodes.EMPTY_COMPONENT,
      message: 'Component appears to be empty (no children, fills, or layout)',
      field: 'component'
    });
  }

  // Validate name format
  if (component?.name) {
    if (component.name.length > 255) {
      warnings.push({
        code: ErrorCodes.VALIDATION_FAILED,
        message: 'Component name exceeds 255 characters',
        field: 'name',
        actual: component.name.length
      });
    }

    // Check for potentially problematic characters
    if (/[<>:"/\\|?*]/.test(component.name)) {
      warnings.push({
        code: ErrorCodes.VALIDATION_FAILED,
        message: 'Component name contains characters that may cause file system issues',
        field: 'name',
        problematic: component.name.match(/[<>:"/\\|?*]/g)
      });
    }
  }

  // Validate ID format
  if (component?.id && typeof component.id !== 'string') {
    errors.push({
      code: ErrorCodes.INVALID_TYPE,
      message: 'Component id must be a string',
      field: 'id',
      actual: typeof component.id
    });
  }

  return {
    valid: errors.length === 0,
    errors,
    warnings
  };
}

/**
 * Detect circular references in node tree
 * @param {Object} node - Root node to check
 * @param {Set} visited - Set of visited node IDs
 * @param {Array} path - Current path for debugging
 * @returns {Object} Result { hasCircular, circularPath }
 */
function detectCircularReferences(node, visited = new Set(), path = []) {
  if (!node || !node.id) {
    return { hasCircular: false, circularPath: null };
  }

  // Check if we've seen this node before
  if (visited.has(node.id)) {
    return {
      hasCircular: true,
      circularPath: [...path, node.id]
    };
  }

  // Mark as visited
  visited.add(node.id);
  const currentPath = [...path, node.id];

  // Check children
  if (node.children && Array.isArray(node.children)) {
    for (const child of node.children) {
      const result = detectCircularReferences(child, visited, currentPath);
      if (result.hasCircular) {
        return result;
      }
    }
  }

  return { hasCircular: false, circularPath: null };
}

/**
 * Safe extraction wrapper with error handling
 * @param {Function} extractFn - Extraction function to wrap
 * @param {Object} node - Node to extract from
 * @param {Object} context - Extraction context
 * @returns {Object} Result { success, data, error }
 */
function safeExtract(extractFn, node, context = {}) {
  try {
    // Validate node first
    const validation = validateNode(node);
    if (!validation.valid) {
      return {
        success: false,
        data: null,
        error: new FigmaExtractionError(
          'Node validation failed',
          ErrorCodes.VALIDATION_FAILED,
          { errors: validation.errors }
        )
      };
    }

    // Check for circular references
    const circularCheck = detectCircularReferences(node);
    if (circularCheck.hasCircular) {
      return {
        success: false,
        data: null,
        error: new FigmaExtractionError(
          'Circular reference detected in node tree',
          ErrorCodes.CIRCULAR_REFERENCE,
          { path: circularCheck.circularPath }
        )
      };
    }

    // Check depth
    const maxDepth = context.maxDepth || 50;
    const currentDepth = context.depth || 0;
    if (currentDepth > maxDepth) {
      return {
        success: false,
        data: null,
        error: new FigmaExtractionError(
          `Maximum extraction depth exceeded (${maxDepth})`,
          ErrorCodes.DEPTH_EXCEEDED,
          { maxDepth, currentDepth }
        )
      };
    }

    // Execute extraction
    const data = extractFn(node, context);

    return {
      success: true,
      data,
      error: null
    };
  } catch (err) {
    return {
      success: false,
      data: null,
      error: new FigmaExtractionError(
        err.message || 'Unknown extraction error',
        ErrorCodes.UNKNOWN,
        { originalError: err.toString(), stack: err.stack }
      )
    };
  }
}

/**
 * Sanitize node data for safe processing
 * @param {Object} node - Node to sanitize
 * @returns {Object} Sanitized node
 */
function sanitizeNode(node) {
  if (!node || typeof node !== 'object') {
    return null;
  }

  // Create a shallow copy
  const sanitized = {};

  // Copy safe properties
  const safeProps = [
    'id', 'name', 'type', 'visible', 'opacity',
    'absoluteBoundingBox', 'fills', 'strokes', 'effects',
    'cornerRadius', 'rectangleCornerRadii', 'strokeWeight',
    'layoutMode', 'itemSpacing', 'paddingTop', 'paddingRight',
    'paddingBottom', 'paddingLeft', 'primaryAxisSizingMode',
    'counterAxisSizingMode', 'primaryAxisAlignItems',
    'counterAxisAlignItems', 'layoutWrap', 'description',
    'componentPropertyDefinitions', 'componentId', 'styles',
    'blendMode', 'constraints'
  ];

  for (const prop of safeProps) {
    if (node[prop] !== undefined) {
      sanitized[prop] = node[prop];
    }
  }

  // Ensure string fields don't exceed limits
  if (sanitized.name && sanitized.name.length > 255) {
    sanitized.name = sanitized.name.substring(0, 255);
  }

  if (sanitized.description && sanitized.description.length > 5000) {
    sanitized.description = sanitized.description.substring(0, 5000);
  }

  // Sanitize children recursively
  if (node.children && Array.isArray(node.children)) {
    sanitized.children = node.children
      .filter(child => child && typeof child === 'object')
      .map(child => sanitizeNode(child));
  }

  return sanitized;
}

/**
 * Handle array safely with bounds checking
 * @param {Array} arr - Array to access
 * @param {number} index - Index to access
 * @param {*} defaultValue - Default value if out of bounds
 * @returns {*} Array element or default
 */
function safeArrayAccess(arr, index, defaultValue = null) {
  if (!Array.isArray(arr)) return defaultValue;
  if (index < 0 || index >= arr.length) return defaultValue;
  return arr[index];
}

/**
 * Safely get nested property
 * @param {Object} obj - Object to access
 * @param {string} path - Dot-separated path
 * @param {*} defaultValue - Default value if not found
 * @returns {*} Property value or default
 */
function safeGet(obj, path, defaultValue = null) {
  if (!obj || typeof obj !== 'object') return defaultValue;

  const parts = path.split('.');
  let current = obj;

  for (const part of parts) {
    if (current === null || current === undefined) return defaultValue;
    if (typeof current !== 'object') return defaultValue;
    current = current[part];
  }

  return current !== undefined ? current : defaultValue;
}

/**
 * Parse color safely
 * @param {Object} color - Figma color object
 * @returns {Object|null} Normalized color or null
 */
function safeParseColor(color) {
  if (!color || typeof color !== 'object') return null;

  const r = typeof color.r === 'number' ? Math.max(0, Math.min(1, color.r)) : 0;
  const g = typeof color.g === 'number' ? Math.max(0, Math.min(1, color.g)) : 0;
  const b = typeof color.b === 'number' ? Math.max(0, Math.min(1, color.b)) : 0;
  const a = typeof color.a === 'number' ? Math.max(0, Math.min(1, color.a)) : 1;

  return { r, g, b, a };
}

/**
 * Format extraction errors for display
 * @param {Array} errors - Array of errors
 * @returns {string} Formatted error message
 */
function formatErrors(errors) {
  if (!Array.isArray(errors) || errors.length === 0) {
    return 'No errors';
  }

  const lines = [`Found ${errors.length} error(s):`];

  errors.forEach((err, index) => {
    const code = err.code || 'UNKNOWN';
    const message = err.message || 'Unknown error';
    const field = err.field ? ` (field: ${err.field})` : '';
    lines.push(`  ${index + 1}. [${code}] ${message}${field}`);
  });

  return lines.join('\n');
}

/**
 * Format validation result for display
 * @param {Object} result - Validation result
 * @returns {string} Formatted output
 */
function formatValidationResult(result) {
  const lines = [];

  if (result.valid) {
    lines.push('Validation: PASSED');
  } else {
    lines.push('Validation: FAILED');
    lines.push(formatErrors(result.errors));
  }

  if (result.warnings && result.warnings.length > 0) {
    lines.push('');
    lines.push(`Warnings (${result.warnings.length}):`);
    result.warnings.forEach((warn, index) => {
      lines.push(`  ${index + 1}. [${warn.code}] ${warn.message}`);
    });
  }

  return lines.join('\n');
}

/**
 * Create a result object with consistent structure
 * @param {boolean} success - Whether operation succeeded
 * @param {*} data - Result data
 * @param {*} error - Error if any
 * @param {Object} metadata - Additional metadata
 * @returns {Object} Structured result
 */
function createResult(success, data = null, error = null, metadata = {}) {
  return {
    success,
    data,
    error: error ? (error instanceof FigmaExtractionError ? error.toJSON() : { message: error instanceof Error ? error.message : String(error) }) : null,
    metadata: {
      timestamp: new Date().toISOString(),
      ...metadata
    }
  };
}

module.exports = {
  // Error classes
  FigmaExtractionError,
  ErrorCodes,

  // Validation
  validateNode,
  validateComponent,
  detectCircularReferences,

  // Safe operations
  safeExtract,
  sanitizeNode,
  safeArrayAccess,
  safeGet,
  safeParseColor,

  // Formatting
  formatErrors,
  formatValidationResult,
  createResult
};
