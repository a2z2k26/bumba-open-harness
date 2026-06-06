/**
 * Custom Error Types
 * Phase 3 - Sprint 126: Structured error handling with codes and context
 *
 * Provides domain-specific error types for better error handling,
 * debugging, and user-friendly error messages.
 */

/**
 * Base error class for Design Bridge errors
 */
class DesignBridgeError extends Error {
  constructor(message, options = {}) {
    super(message);
    this.name = 'DesignBridgeError';
    this.code = options.code || 'DESIGN_BRIDGE_ERROR';
    this.statusCode = options.statusCode || 500;
    this.context = options.context || {};
    this.cause = options.cause || null;
    this.recoverable = options.recoverable !== false;
    this.timestamp = new Date().toISOString();

    // Capture stack trace
    if (Error.captureStackTrace) {
      Error.captureStackTrace(this, this.constructor);
    }
  }

  /**
   * Convert to JSON for logging/serialization
   */
  toJSON() {
    return {
      name: this.name,
      code: this.code,
      message: this.message,
      statusCode: this.statusCode,
      context: this.context,
      recoverable: this.recoverable,
      timestamp: this.timestamp,
      stack: this.stack,
      cause: this.cause ? {
        name: this.cause.name,
        message: this.cause.message,
        code: this.cause.code
      } : null
    };
  }

  /**
   * Get user-friendly error message
   */
  getUserMessage() {
    return this.message;
  }
}

// =============================================================================
// VALIDATION ERRORS
// =============================================================================

/**
 * Input validation error
 */
class ValidationError extends DesignBridgeError {
  constructor(message, options = {}) {
    super(message, {
      ...options,
      code: options.code || 'VALIDATION_ERROR',
      statusCode: 400
    });
    this.name = 'ValidationError';
    this.field = options.field || null;
    this.value = options.value;
    this.expected = options.expected || null;
  }

  getUserMessage() {
    if (this.field) {
      return `Invalid ${this.field}: ${this.message}`;
    }
    return `Validation failed: ${this.message}`;
  }
}

/**
 * Schema validation error
 */
class SchemaValidationError extends ValidationError {
  constructor(message, options = {}) {
    super(message, {
      ...options,
      code: 'SCHEMA_VALIDATION_ERROR'
    });
    this.name = 'SchemaValidationError';
    this.schemaPath = options.schemaPath || null;
    this.errors = options.errors || [];
  }

  getUserMessage() {
    if (this.errors.length > 0) {
      return `Schema validation failed with ${this.errors.length} error(s)`;
    }
    return `Schema validation failed: ${this.message}`;
  }
}

/**
 * Required field missing error
 */
class RequiredFieldError extends ValidationError {
  constructor(field, options = {}) {
    super(`Required field '${field}' is missing`, {
      ...options,
      code: 'REQUIRED_FIELD_ERROR',
      field
    });
    this.name = 'RequiredFieldError';
  }
}

// =============================================================================
// COMPONENT ERRORS
// =============================================================================

/**
 * Component not found error
 */
class ComponentNotFoundError extends DesignBridgeError {
  constructor(componentId, options = {}) {
    super(`Component not found: ${componentId}`, {
      ...options,
      code: 'COMPONENT_NOT_FOUND',
      statusCode: 404,
      context: { componentId, ...options.context }
    });
    this.name = 'ComponentNotFoundError';
    this.componentId = componentId;
  }

  getUserMessage() {
    return `Could not find component '${this.componentId}'`;
  }
}

/**
 * Component generation error
 */
class ComponentGenerationError extends DesignBridgeError {
  constructor(message, options = {}) {
    super(message, {
      ...options,
      code: options.code || 'COMPONENT_GENERATION_ERROR',
      statusCode: 500
    });
    this.name = 'ComponentGenerationError';
    this.componentName = options.componentName || null;
    this.framework = options.framework || null;
    this.phase = options.phase || null;
  }

  getUserMessage() {
    if (this.componentName && this.framework) {
      return `Failed to generate ${this.framework} component for '${this.componentName}'`;
    }
    return `Component generation failed: ${this.message}`;
  }
}

/**
 * Component parse error
 */
class ComponentParseError extends DesignBridgeError {
  constructor(message, options = {}) {
    super(message, {
      ...options,
      code: 'COMPONENT_PARSE_ERROR',
      statusCode: 400
    });
    this.name = 'ComponentParseError';
    this.source = options.source || null;
    this.line = options.line || null;
    this.column = options.column || null;
  }
}

// =============================================================================
// REGISTRY ERRORS
// =============================================================================

/**
 * Registry read error
 */
class RegistryReadError extends DesignBridgeError {
  constructor(message, options = {}) {
    super(message, {
      ...options,
      code: 'REGISTRY_READ_ERROR',
      statusCode: 500
    });
    this.name = 'RegistryReadError';
    this.registryPath = options.registryPath || null;
  }
}

/**
 * Registry write error
 */
class RegistryWriteError extends DesignBridgeError {
  constructor(message, options = {}) {
    super(message, {
      ...options,
      code: 'REGISTRY_WRITE_ERROR',
      statusCode: 500
    });
    this.name = 'RegistryWriteError';
    this.registryPath = options.registryPath || null;
  }
}

/**
 * Registry corruption error
 */
class RegistryCorruptionError extends DesignBridgeError {
  constructor(message, options = {}) {
    super(message, {
      ...options,
      code: 'REGISTRY_CORRUPTION_ERROR',
      statusCode: 500,
      recoverable: false
    });
    this.name = 'RegistryCorruptionError';
  }

  getUserMessage() {
    return 'Registry data is corrupted. Please run `design-bridge repair` to fix.';
  }
}

// =============================================================================
// TOKEN ERRORS
// =============================================================================

/**
 * Token not found error
 */
class TokenNotFoundError extends DesignBridgeError {
  constructor(tokenPath, options = {}) {
    super(`Token not found: ${tokenPath}`, {
      ...options,
      code: 'TOKEN_NOT_FOUND',
      statusCode: 404,
      context: { tokenPath, ...options.context }
    });
    this.name = 'TokenNotFoundError';
    this.tokenPath = tokenPath;
  }
}

/**
 * Token resolution error
 */
class TokenResolutionError extends DesignBridgeError {
  constructor(message, options = {}) {
    super(message, {
      ...options,
      code: 'TOKEN_RESOLUTION_ERROR',
      statusCode: 500
    });
    this.name = 'TokenResolutionError';
    this.tokenPath = options.tokenPath || null;
    this.resolvedValue = options.resolvedValue;
  }
}

// =============================================================================
// FIGMA ERRORS
// =============================================================================

/**
 * Figma API error
 */
class FigmaApiError extends DesignBridgeError {
  constructor(message, options = {}) {
    super(message, {
      ...options,
      code: options.code || 'FIGMA_API_ERROR',
      statusCode: options.statusCode || 502
    });
    this.name = 'FigmaApiError';
    this.figmaErrorCode = options.figmaErrorCode || null;
    this.endpoint = options.endpoint || null;
  }
}

/**
 * Figma node not found error
 */
class FigmaNodeNotFoundError extends FigmaApiError {
  constructor(nodeId, options = {}) {
    super(`Figma node not found: ${nodeId}`, {
      ...options,
      code: 'FIGMA_NODE_NOT_FOUND',
      statusCode: 404
    });
    this.name = 'FigmaNodeNotFoundError';
    this.nodeId = nodeId;
  }
}

/**
 * Figma rate limit error
 */
class FigmaRateLimitError extends FigmaApiError {
  constructor(options = {}) {
    super('Figma API rate limit exceeded', {
      ...options,
      code: 'FIGMA_RATE_LIMIT',
      statusCode: 429
    });
    this.name = 'FigmaRateLimitError';
    this.retryAfter = options.retryAfter || 60;
  }

  getUserMessage() {
    return `Figma API rate limit reached. Please wait ${this.retryAfter} seconds.`;
  }
}

// =============================================================================
// FRAMEWORK ERRORS
// =============================================================================

/**
 * Unsupported framework error
 */
class UnsupportedFrameworkError extends DesignBridgeError {
  constructor(framework, options = {}) {
    super(`Unsupported framework: ${framework}`, {
      ...options,
      code: 'UNSUPPORTED_FRAMEWORK',
      statusCode: 400,
      context: { framework, ...options.context }
    });
    this.name = 'UnsupportedFrameworkError';
    this.framework = framework;
    this.supportedFrameworks = options.supportedFrameworks || [];
  }

  getUserMessage() {
    if (this.supportedFrameworks.length > 0) {
      return `Framework '${this.framework}' is not supported. Supported: ${this.supportedFrameworks.join(', ')}`;
    }
    return `Framework '${this.framework}' is not supported`;
  }
}

/**
 * Framework configuration error
 */
class FrameworkConfigError extends DesignBridgeError {
  constructor(message, options = {}) {
    super(message, {
      ...options,
      code: 'FRAMEWORK_CONFIG_ERROR',
      statusCode: 400
    });
    this.name = 'FrameworkConfigError';
    this.framework = options.framework || null;
  }
}

// =============================================================================
// FILE SYSTEM ERRORS
// =============================================================================

/**
 * File not found error
 */
class FileNotFoundError extends DesignBridgeError {
  constructor(filePath, options = {}) {
    super(`File not found: ${filePath}`, {
      ...options,
      code: 'FILE_NOT_FOUND',
      statusCode: 404,
      context: { filePath, ...options.context }
    });
    this.name = 'FileNotFoundError';
    this.filePath = filePath;
  }
}

/**
 * File write error
 */
class FileWriteError extends DesignBridgeError {
  constructor(filePath, options = {}) {
    super(`Failed to write file: ${filePath}`, {
      ...options,
      code: 'FILE_WRITE_ERROR',
      statusCode: 500,
      context: { filePath, ...options.context }
    });
    this.name = 'FileWriteError';
    this.filePath = filePath;
  }
}

/**
 * Permission error
 */
class PermissionError extends DesignBridgeError {
  constructor(message, options = {}) {
    super(message, {
      ...options,
      code: 'PERMISSION_ERROR',
      statusCode: 403
    });
    this.name = 'PermissionError';
    this.path = options.path || null;
    this.operation = options.operation || null;
  }
}

// =============================================================================
// SYNC ERRORS
// =============================================================================

/**
 * Sync conflict error
 */
class SyncConflictError extends DesignBridgeError {
  constructor(message, options = {}) {
    super(message, {
      ...options,
      code: 'SYNC_CONFLICT',
      statusCode: 409
    });
    this.name = 'SyncConflictError';
    this.componentId = options.componentId || null;
    this.localVersion = options.localVersion || null;
    this.remoteVersion = options.remoteVersion || null;
  }

  getUserMessage() {
    return 'Sync conflict detected. Please resolve the conflict before continuing.';
  }
}

/**
 * Sync timeout error
 */
class SyncTimeoutError extends DesignBridgeError {
  constructor(options = {}) {
    super('Sync operation timed out', {
      ...options,
      code: 'SYNC_TIMEOUT',
      statusCode: 504
    });
    this.name = 'SyncTimeoutError';
    this.timeout = options.timeout || null;
  }
}

// =============================================================================
// CONFIGURATION ERRORS
// =============================================================================

/**
 * Configuration error
 */
class ConfigurationError extends DesignBridgeError {
  constructor(message, options = {}) {
    super(message, {
      ...options,
      code: 'CONFIGURATION_ERROR',
      statusCode: 500
    });
    this.name = 'ConfigurationError';
    this.configPath = options.configPath || null;
    this.configKey = options.configKey || null;
  }
}

/**
 * Missing configuration error
 */
class MissingConfigError extends ConfigurationError {
  constructor(configKey, options = {}) {
    super(`Missing required configuration: ${configKey}`, {
      ...options,
      configKey
    });
    this.name = 'MissingConfigError';
    this.code = 'MISSING_CONFIG';
  }
}

// =============================================================================
// ERROR UTILITIES
// =============================================================================

/**
 * Wrap an error in a DesignBridgeError
 */
function wrapError(err, options = {}) {
  if (err instanceof DesignBridgeError) {
    return err;
  }

  return new DesignBridgeError(err.message, {
    ...options,
    cause: err,
    code: err.code || 'WRAPPED_ERROR'
  });
}

/**
 * Check if error is a specific type
 */
function isErrorType(err, ErrorClass) {
  return err instanceof ErrorClass;
}

/**
 * Check if error is recoverable
 */
function isRecoverable(err) {
  if (err instanceof DesignBridgeError) {
    return err.recoverable;
  }
  return true; // Assume unknown errors are recoverable
}

/**
 * Get error code
 */
function getErrorCode(err) {
  if (err instanceof DesignBridgeError) {
    return err.code;
  }
  return err.code || 'UNKNOWN_ERROR';
}

module.exports = {
  // Base
  DesignBridgeError,

  // Validation
  ValidationError,
  SchemaValidationError,
  RequiredFieldError,

  // Component
  ComponentNotFoundError,
  ComponentGenerationError,
  ComponentParseError,

  // Registry
  RegistryReadError,
  RegistryWriteError,
  RegistryCorruptionError,

  // Token
  TokenNotFoundError,
  TokenResolutionError,

  // Figma
  FigmaApiError,
  FigmaNodeNotFoundError,
  FigmaRateLimitError,

  // Framework
  UnsupportedFrameworkError,
  FrameworkConfigError,

  // File System
  FileNotFoundError,
  FileWriteError,
  PermissionError,

  // Sync
  SyncConflictError,
  SyncTimeoutError,

  // Configuration
  ConfigurationError,
  MissingConfigError,

  // Utilities
  wrapError,
  isErrorType,
  isRecoverable,
  getErrorCode
};
