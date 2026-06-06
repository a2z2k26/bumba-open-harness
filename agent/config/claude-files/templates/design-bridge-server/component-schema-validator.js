/**
 * Component Schema Validator
 * Sprint 31: Component schema validation
 *
 * Validates design components against schemas to ensure data quality
 */

const EventEmitter = require('events');

class ComponentSchemaValidator extends EventEmitter {
  constructor(options = {}) {
    super();

    this.version = '1.0.0';
    this.options = {
      strictMode: options.strictMode !== false,
      allowAdditionalProps: options.allowAdditionalProps !== false,
      ...options
    };

    // Define component schemas
    this.schemas = this.defineSchemas();

    // Validation statistics
    this.stats = {
      totalValidations: 0,
      successfulValidations: 0,
      failedValidations: 0,
      lastValidation: null
    };
  }

  /**
   * Define component schemas
   */
  defineSchemas() {
    return {
      // Schema version 1.0.0
      '1.0.0': {
        // Base component schema
        component: {
          id: { type: 'string', required: true },
          name: { type: 'string', required: true },
          type: { type: 'string', required: true },
          props: { type: 'object', required: false, default: {} },
          state: { type: 'object', required: false, default: {} },
          styles: { type: 'object', required: false, default: {} },
          children: { type: 'array', required: false, default: [] },
          variants: { type: 'array', required: false, default: [] },
          interactions: { type: 'array', required: false, default: [] }
        },

        // Button component schema
        button: {
          id: { type: 'string', required: true },
          name: { type: 'string', required: true },
          type: { type: 'string', required: true, enum: ['button'] },
          label: { type: 'string', required: true },
          variant: { type: 'string', required: false, enum: ['primary', 'secondary', 'tertiary', 'ghost'] },
          size: { type: 'string', required: false, enum: ['small', 'medium', 'large'] },
          disabled: { type: 'boolean', required: false, default: false },
          icon: { type: 'object', required: false },
          onClick: { type: 'function', required: false },
          styles: { type: 'object', required: false }
        },

        // Input component schema
        input: {
          id: { type: 'string', required: true },
          name: { type: 'string', required: true },
          type: { type: 'string', required: true, enum: ['input', 'text', 'email', 'password', 'number'] },
          label: { type: 'string', required: false },
          placeholder: { type: 'string', required: false },
          value: { type: 'string', required: false },
          required: { type: 'boolean', required: false, default: false },
          disabled: { type: 'boolean', required: false, default: false },
          error: { type: 'string', required: false },
          helperText: { type: 'string', required: false },
          validation: { type: 'object', required: false }
        },

        // Card component schema
        card: {
          id: { type: 'string', required: true },
          name: { type: 'string', required: true },
          type: { type: 'string', required: true, enum: ['card'] },
          header: { type: 'object', required: false },
          body: { type: 'object', required: false },
          footer: { type: 'object', required: false },
          image: { type: 'object', required: false },
          elevation: { type: 'number', required: false, min: 0, max: 24 },
          padding: { type: 'string', required: false }
        },

        // Modal component schema
        modal: {
          id: { type: 'string', required: true },
          name: { type: 'string', required: true },
          type: { type: 'string', required: true, enum: ['modal', 'dialog'] },
          title: { type: 'string', required: false },
          content: { type: 'object', required: false },
          actions: { type: 'array', required: false },
          size: { type: 'string', required: false, enum: ['small', 'medium', 'large', 'fullscreen'] },
          closable: { type: 'boolean', required: false, default: true },
          overlay: { type: 'boolean', required: false, default: true }
        },

        // Design token schema
        designToken: {
          category: { type: 'string', required: true },
          name: { type: 'string', required: true },
          value: { type: 'any', required: true },
          description: { type: 'string', required: false },
          type: { type: 'string', required: false }
        }
      }
    };
  }

  /**
   * Validate component against schema
   */
  validate(component, schemaType = 'component', schemaVersion = '1.0.0') {
    this.stats.totalValidations++;

    const result = {
      valid: true,
      errors: [],
      warnings: [],
      component: component.name || 'unknown',
      schemaType,
      schemaVersion,
      timestamp: new Date().toISOString()
    };

    try {
      // Check if schema exists
      const versionSchemas = this.schemas[schemaVersion];
      if (!versionSchemas) {
        throw new Error(`Schema version not found: ${schemaVersion}`);
      }

      const schema = versionSchemas[schemaType];
      if (!schema) {
        throw new Error(`Schema type not found: ${schemaType}`);
      }

      // Validate component
      this.validateObject(component, schema, result, '');

      // Check if validation passed
      if (result.errors.length > 0) {
        result.valid = false;
        this.stats.failedValidations++;
      } else {
        this.stats.successfulValidations++;
      }

      this.stats.lastValidation = result.timestamp;

      this.emit('validation:completed', result);

      return result;

    } catch (error) {
      result.valid = false;
      result.errors.push({
        field: 'validation',
        message: error.message,
        severity: 'error'
      });

      this.stats.failedValidations++;

      this.emit('validation:error', { component, error: error.message });

      return result;
    }
  }

  /**
   * Validate object against schema definition
   */
  validateObject(obj, schema, result, path) {
    // Check required fields
    Object.entries(schema).forEach(([fieldName, fieldSchema]) => {
      const fieldPath = path ? `${path}.${fieldName}` : fieldName;
      const value = obj[fieldName];

      // Required field check
      if (fieldSchema.required && (value === undefined || value === null)) {
        result.errors.push({
          field: fieldPath,
          message: `Required field '${fieldName}' is missing`,
          severity: 'error',
          expectedType: fieldSchema.type
        });
        return;
      }

      // Skip validation if field is not present and not required
      if (value === undefined || value === null) {
        return;
      }

      // Type validation
      if (!this.validateType(value, fieldSchema.type)) {
        result.errors.push({
          field: fieldPath,
          message: `Field '${fieldName}' has invalid type. Expected ${fieldSchema.type}, got ${typeof value}`,
          severity: 'error',
          expectedType: fieldSchema.type,
          actualType: typeof value
        });
        return;
      }

      // Enum validation
      if (fieldSchema.enum && !fieldSchema.enum.includes(value)) {
        result.errors.push({
          field: fieldPath,
          message: `Field '${fieldName}' has invalid value. Must be one of: ${fieldSchema.enum.join(', ')}`,
          severity: 'error',
          allowedValues: fieldSchema.enum,
          actualValue: value
        });
      }

      // Min/max validation for numbers
      if (fieldSchema.type === 'number') {
        if (fieldSchema.min !== undefined && value < fieldSchema.min) {
          result.errors.push({
            field: fieldPath,
            message: `Field '${fieldName}' is below minimum value. Min: ${fieldSchema.min}, actual: ${value}`,
            severity: 'error',
            min: fieldSchema.min,
            actualValue: value
          });
        }

        if (fieldSchema.max !== undefined && value > fieldSchema.max) {
          result.errors.push({
            field: fieldPath,
            message: `Field '${fieldName}' exceeds maximum value. Max: ${fieldSchema.max}, actual: ${value}`,
            severity: 'error',
            max: fieldSchema.max,
            actualValue: value
          });
        }
      }

      // Pattern validation for strings
      if (fieldSchema.type === 'string' && fieldSchema.pattern) {
        const regex = new RegExp(fieldSchema.pattern);
        if (!regex.test(value)) {
          result.errors.push({
            field: fieldPath,
            message: `Field '${fieldName}' does not match required pattern`,
            severity: 'error',
            pattern: fieldSchema.pattern,
            actualValue: value
          });
        }
      }
    });

    // Check for additional properties (if not allowed)
    if (!this.options.allowAdditionalProps) {
      Object.keys(obj).forEach(key => {
        if (!schema[key]) {
          result.warnings.push({
            field: path ? `${path}.${key}` : key,
            message: `Additional property '${key}' found (not in schema)`,
            severity: 'warning'
          });
        }
      });
    }
  }

  /**
   * Validate value type
   */
  validateType(value, expectedType) {
    if (expectedType === 'any') return true;

    const actualType = Array.isArray(value) ? 'array' : typeof value;

    switch (expectedType) {
      case 'string':
        return typeof value === 'string';
      case 'number':
        return typeof value === 'number' && !isNaN(value);
      case 'boolean':
        return typeof value === 'boolean';
      case 'object':
        return typeof value === 'object' && !Array.isArray(value) && value !== null;
      case 'array':
        return Array.isArray(value);
      case 'function':
        return typeof value === 'function';
      default:
        return false;
    }
  }

  /**
   * Batch validate multiple components
   */
  batchValidate(components, schemaType = 'component', schemaVersion = '1.0.0') {
    const results = components.map(component =>
      this.validate(component, schemaType, schemaVersion)
    );

    const summary = {
      total: results.length,
      valid: results.filter(r => r.valid).length,
      invalid: results.filter(r => !r.valid).length,
      results,
      timestamp: new Date().toISOString()
    };

    this.emit('batch:completed', summary);

    return summary;
  }

  /**
   * Register custom schema
   */
  registerSchema(version, type, schema) {
    if (!this.schemas[version]) {
      this.schemas[version] = {};
    }

    this.schemas[version][type] = schema;

    this.emit('schema:registered', { version, type });

    return true;
  }

  /**
   * Get schema for type
   */
  getSchema(type, version = '1.0.0') {
    return this.schemas[version]?.[type] || null;
  }

  /**
   * Get all available schemas
   */
  getAllSchemas() {
    return this.schemas;
  }

  /**
   * Migrate component to new schema version
   */
  migrateComponent(component, fromVersion, toVersion) {
    this.emit('migration:started', { component: component.name, fromVersion, toVersion });

    // Basic migration - copy all fields
    const migrated = { ...component };

    // Version-specific migration logic
    if (fromVersion === '1.0.0' && toVersion === '2.0.0') {
      // Add migration logic here when 2.0.0 is defined
    }

    migrated._schemaVersion = toVersion;
    migrated._migratedFrom = fromVersion;
    migrated._migratedAt = new Date().toISOString();

    this.emit('migration:completed', { component: migrated.name, fromVersion, toVersion });

    return migrated;
  }

  /**
   * Auto-detect component type
   */
  autoDetectType(component) {
    const name = (component.name || '').toLowerCase();
    const type = (component.type || '').toLowerCase();

    // Check explicit type first
    if (type && this.getSchema(type)) {
      return type;
    }

    // Detect from name
    if (name.includes('button')) return 'button';
    if (name.includes('input') || name.includes('field')) return 'input';
    if (name.includes('card')) return 'card';
    if (name.includes('modal') || name.includes('dialog')) return 'modal';

    // Default to generic component schema
    return 'component';
  }

  /**
   * Validate with auto-detection
   */
  autoValidate(component, schemaVersion = '1.0.0') {
    const detectedType = this.autoDetectType(component);
    return this.validate(component, detectedType, schemaVersion);
  }

  /**
   * Get validation statistics
   */
  getStats() {
    return {
      ...this.stats,
      successRate: this.stats.totalValidations > 0
        ? (this.stats.successfulValidations / this.stats.totalValidations * 100).toFixed(2) + '%'
        : 'N/A',
      schemaVersions: Object.keys(this.schemas),
      schemaTypes: Object.keys(this.schemas['1.0.0'])
    };
  }

  /**
   * Generate error report
   */
  generateErrorReport(validationResult) {
    if (validationResult.valid) {
      return 'No errors found';
    }

    let report = `Validation failed for component: ${validationResult.component}\n\n`;
    report += `Errors (${validationResult.errors.length}):\n`;

    validationResult.errors.forEach((error, index) => {
      report += `${index + 1}. ${error.field}: ${error.message}\n`;
    });

    if (validationResult.warnings.length > 0) {
      report += `\nWarnings (${validationResult.warnings.length}):\n`;
      validationResult.warnings.forEach((warning, index) => {
        report += `${index + 1}. ${warning.field}: ${warning.message}\n`;
      });
    }

    return report;
  }

  /**
   * Test validation
   */
  testValidation() {
    console.log('🧪 Testing component schema validation...\n');

    const testComponents = [
      {
        id: 'btn-1',
        name: 'PrimaryButton',
        type: 'button',
        label: 'Click Me',
        variant: 'primary',
        size: 'medium'
      },
      {
        id: 'input-1',
        name: 'EmailInput',
        type: 'email',
        label: 'Email Address',
        required: true
      },
      {
        // Missing required field
        name: 'InvalidComponent',
        type: 'button'
      }
    ];

    testComponents.forEach((component, index) => {
      console.log(`Test ${index + 1}: ${component.name}`);
      const result = this.autoValidate(component);
      console.log(`  Valid: ${result.valid ? '✓' : '✗'}`);
      console.log(`  Errors: ${result.errors.length}`);
      console.log(`  Warnings: ${result.warnings.length}`);

      if (!result.valid) {
        console.log(`  Report:\n${this.generateErrorReport(result)}`);
      }
      console.log('');
    });

    console.log('✅ Schema validation test complete!\n');
  }
}

module.exports = ComponentSchemaValidator;
