/**
 * Design Bridge - Configuration System
 * Phase 7, Sprint 7.2
 *
 * Provides comprehensive configuration management:
 * - Multi-environment configuration
 * - Schema validation
 * - Config file loading/saving
 * - Environment variable overrides
 * - Config inheritance and merging
 */

const EventEmitter = require('events');
const path = require('path');
const fs = require('fs');

// Configuration schema definition
const CONFIG_SCHEMA = {
  figma: {
    type: 'object',
    properties: {
      accessToken: { type: 'string', env: 'FIGMA_ACCESS_TOKEN', sensitive: true },
      teamId: { type: 'string', env: 'FIGMA_TEAM_ID' },
      fileIds: { type: 'array', items: { type: 'string' } },
      pollInterval: { type: 'number', default: 30000, min: 5000, max: 300000 }
    },
    required: ['accessToken']
  },
  output: {
    type: 'object',
    properties: {
      directory: { type: 'string', default: './src/components' },
      framework: { type: 'string', enum: ['react', 'vue', 'svelte', 'angular', 'web-components'], default: 'react' },
      typescript: { type: 'boolean', default: true },
      styleFormat: { type: 'string', enum: ['css', 'scss', 'less', 'styled-components', 'emotion', 'tailwind'], default: 'css' },
      fileNaming: { type: 'string', enum: ['kebab-case', 'camelCase', 'PascalCase'], default: 'PascalCase' }
    }
  },
  tokens: {
    type: 'object',
    properties: {
      outputPath: { type: 'string', default: './src/tokens' },
      formats: { type: 'array', items: { type: 'string', enum: ['css', 'scss', 'js', 'ts', 'json', 'tailwind'] }, default: ['css', 'json'] },
      prefix: { type: 'string', default: '' },
      colorFormat: { type: 'string', enum: ['hex', 'rgb', 'hsl'], default: 'hex' }
    }
  },
  testing: {
    type: 'object',
    properties: {
      visual: {
        type: 'object',
        properties: {
          enabled: { type: 'boolean', default: true },
          threshold: { type: 'number', default: 0.1, min: 0, max: 1 },
          viewports: { type: 'array', items: { type: 'string' }, default: ['mobile', 'desktop'] }
        }
      },
      accessibility: {
        type: 'object',
        properties: {
          enabled: { type: 'boolean', default: true },
          wcagLevel: { type: 'string', enum: ['A', 'AA', 'AAA'], default: 'AA' },
          rules: { type: 'array', items: { type: 'string' }, default: [] }
        }
      }
    }
  },
  sync: {
    type: 'object',
    properties: {
      watchMode: { type: 'boolean', default: false },
      autoSync: { type: 'boolean', default: false },
      syncOnStart: { type: 'boolean', default: true },
      ignorePatterns: { type: 'array', items: { type: 'string' }, default: [] }
    }
  },
  plugins: {
    type: 'array',
    items: {
      type: 'object',
      properties: {
        name: { type: 'string' },
        enabled: { type: 'boolean', default: true },
        options: { type: 'object' }
      }
    },
    default: []
  }
};

// Environment configurations
const ENVIRONMENTS = {
  development: {
    sync: { watchMode: true, autoSync: true },
    testing: { visual: { enabled: false } }
  },
  staging: {
    sync: { watchMode: false, autoSync: false },
    testing: { visual: { enabled: true } }
  },
  production: {
    sync: { watchMode: false, autoSync: false },
    testing: { visual: { enabled: true }, accessibility: { wcagLevel: 'AA' } }
  },
  test: {
    sync: { watchMode: false, autoSync: false },
    testing: { visual: { enabled: true }, accessibility: { enabled: true } }
  }
};

// Config file names by priority
const CONFIG_FILES = [
  'design-bridge.config.js',
  'design-bridge.config.json',
  '.designbridgerc.js',
  '.designbridgerc.json',
  '.designbridgerc'
];

/**
 * Validation error class
 */
class ConfigValidationError extends Error {
  constructor(message, path, value) {
    super(message);
    this.name = 'ConfigValidationError';
    this.path = path;
    this.value = value;
  }
}

/**
 * Configuration System Class
 */
class ConfigSystem extends EventEmitter {
  constructor(options = {}) {
    super();

    this.options = {
      configDir: options.configDir || process.cwd(),
      env: options.env || process.env.NODE_ENV || 'development',
      watchConfig: options.watchConfig || false,
      ...options
    };

    this.config = {};
    this.loadedFrom = null;
    this.watchers = new Map();
    this.validationErrors = [];
  }

  /**
   * Initialize configuration
   */
  async init() {
    // Load config file
    await this.loadConfig();

    // Apply environment-specific overrides
    this.applyEnvironment();

    // Apply environment variable overrides
    this.applyEnvVars();

    // Validate configuration
    this.validate();

    // Setup watch if enabled
    if (this.options.watchConfig) {
      this.watchConfigFile();
    }

    this.emit('config:loaded', {
      source: this.loadedFrom,
      env: this.options.env
    });

    return this.config;
  }

  /**
   * Load configuration from file
   */
  async loadConfig() {
    const configDir = this.options.configDir;

    for (const fileName of CONFIG_FILES) {
      const filePath = path.join(configDir, fileName);

      if (this.fileExists(filePath)) {
        try {
          const config = await this.loadConfigFile(filePath);
          this.config = this.mergeWithDefaults(config);
          this.loadedFrom = filePath;
          return;
        } catch (error) {
          this.emit('config:error', { file: filePath, error });
        }
      }
    }

    // No config file found, use defaults
    this.config = this.getDefaults();
    this.loadedFrom = null;
  }

  /**
   * Load a specific config file
   */
  async loadConfigFile(filePath) {
    const ext = path.extname(filePath);

    if (ext === '.js') {
      // Clear require cache for hot reloading
      delete require.cache[require.resolve(filePath)];
      const module = require(filePath);
      return typeof module === 'function' ? module() : module;
    } else if (ext === '.json' || ext === '') {
      const content = fs.readFileSync(filePath, 'utf8');
      return JSON.parse(content);
    }

    throw new Error(`Unsupported config file format: ${ext}`);
  }

  /**
   * Check if file exists
   */
  fileExists(filePath) {
    try {
      fs.accessSync(filePath, fs.constants.F_OK);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Get default configuration from schema
   */
  getDefaults() {
    return this.extractDefaults(CONFIG_SCHEMA);
  }

  /**
   * Extract default values from schema
   */
  extractDefaults(schema, result = {}) {
    for (const [key, def] of Object.entries(schema)) {
      if (def.type === 'object' && def.properties) {
        result[key] = this.extractDefaults(def.properties, {});
      } else if (def.default !== undefined) {
        result[key] = JSON.parse(JSON.stringify(def.default));
      }
    }
    return result;
  }

  /**
   * Merge config with defaults
   */
  mergeWithDefaults(config) {
    const defaults = this.getDefaults();
    return this.deepMerge(defaults, config);
  }

  /**
   * Deep merge objects
   */
  deepMerge(target, source) {
    const result = { ...target };

    for (const [key, value] of Object.entries(source)) {
      if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
        result[key] = this.deepMerge(result[key] || {}, value);
      } else {
        result[key] = value;
      }
    }

    return result;
  }

  /**
   * Apply environment-specific configuration
   */
  applyEnvironment() {
    const envConfig = ENVIRONMENTS[this.options.env];

    if (envConfig) {
      this.config = this.deepMerge(this.config, envConfig);
    }
  }

  /**
   * Apply environment variable overrides
   */
  applyEnvVars() {
    this.applyEnvVarsRecursive(CONFIG_SCHEMA, this.config, []);
  }

  /**
   * Recursively apply environment variables
   */
  applyEnvVarsRecursive(schema, config, path) {
    for (const [key, def] of Object.entries(schema)) {
      const currentPath = [...path, key];

      if (def.type === 'object' && def.properties) {
        if (!config[key]) config[key] = {};
        this.applyEnvVarsRecursive(def.properties, config[key], currentPath);
      } else if (def.env && process.env[def.env]) {
        const envValue = process.env[def.env];
        config[key] = this.coerceValue(envValue, def.type);
      }
    }
  }

  /**
   * Coerce string value to proper type
   */
  coerceValue(value, type) {
    switch (type) {
      case 'number':
        return Number(value);
      case 'boolean':
        return value === 'true' || value === '1';
      case 'array':
        try {
          return JSON.parse(value);
        } catch {
          return value.split(',').map(s => s.trim());
        }
      default:
        return value;
    }
  }

  /**
   * Validate configuration against schema
   */
  validate() {
    this.validationErrors = [];
    this.validateRecursive(CONFIG_SCHEMA, this.config, []);

    if (this.validationErrors.length > 0) {
      this.emit('config:validation-errors', this.validationErrors);
    }

    return this.validationErrors.length === 0;
  }

  /**
   * Recursive validation
   */
  validateRecursive(schema, config, path) {
    for (const [key, def] of Object.entries(schema)) {
      const currentPath = [...path, key].join('.');
      const value = config ? config[key] : undefined;

      // Check required fields
      if (def.required && (value === undefined || value === null || value === '')) {
        this.validationErrors.push(
          new ConfigValidationError(`Required field missing: ${currentPath}`, currentPath, value)
        );
        continue;
      }

      if (value === undefined || value === null) continue;

      // Type validation
      if (def.type === 'object' && def.properties) {
        if (typeof value !== 'object' || Array.isArray(value)) {
          this.validationErrors.push(
            new ConfigValidationError(`Expected object at ${currentPath}`, currentPath, value)
          );
        } else {
          this.validateRecursive(def.properties, value, [...path, key]);
        }
      } else if (def.type === 'array') {
        if (!Array.isArray(value)) {
          this.validationErrors.push(
            new ConfigValidationError(`Expected array at ${currentPath}`, currentPath, value)
          );
        } else if (def.items && def.items.enum) {
          for (const item of value) {
            if (!def.items.enum.includes(item)) {
              this.validationErrors.push(
                new ConfigValidationError(
                  `Invalid array item at ${currentPath}: ${item}. Expected one of: ${def.items.enum.join(', ')}`,
                  currentPath,
                  item
                )
              );
            }
          }
        }
      } else if (def.type === 'string') {
        if (typeof value !== 'string') {
          this.validationErrors.push(
            new ConfigValidationError(`Expected string at ${currentPath}`, currentPath, value)
          );
        } else if (def.enum && !def.enum.includes(value)) {
          this.validationErrors.push(
            new ConfigValidationError(
              `Invalid value at ${currentPath}: ${value}. Expected one of: ${def.enum.join(', ')}`,
              currentPath,
              value
            )
          );
        }
      } else if (def.type === 'number') {
        if (typeof value !== 'number') {
          this.validationErrors.push(
            new ConfigValidationError(`Expected number at ${currentPath}`, currentPath, value)
          );
        } else {
          if (def.min !== undefined && value < def.min) {
            this.validationErrors.push(
              new ConfigValidationError(`Value at ${currentPath} is below minimum ${def.min}`, currentPath, value)
            );
          }
          if (def.max !== undefined && value > def.max) {
            this.validationErrors.push(
              new ConfigValidationError(`Value at ${currentPath} exceeds maximum ${def.max}`, currentPath, value)
            );
          }
        }
      } else if (def.type === 'boolean') {
        if (typeof value !== 'boolean') {
          this.validationErrors.push(
            new ConfigValidationError(`Expected boolean at ${currentPath}`, currentPath, value)
          );
        }
      }
    }
  }

  /**
   * Get configuration value by path
   */
  get(keyPath, defaultValue = undefined) {
    const keys = keyPath.split('.');
    let value = this.config;

    for (const key of keys) {
      if (value === null || value === undefined) {
        return defaultValue;
      }
      value = value[key];
    }

    return value !== undefined ? value : defaultValue;
  }

  /**
   * Set configuration value by path
   */
  set(keyPath, value) {
    const keys = keyPath.split('.');
    const lastKey = keys.pop();
    let target = this.config;

    for (const key of keys) {
      if (!(key in target)) {
        target[key] = {};
      }
      target = target[key];
    }

    const oldValue = target[lastKey];
    target[lastKey] = value;

    this.emit('config:changed', { path: keyPath, oldValue, newValue: value });

    return this;
  }

  /**
   * Check if configuration has a key
   */
  has(keyPath) {
    return this.get(keyPath) !== undefined;
  }

  /**
   * Get entire configuration
   */
  getAll() {
    return JSON.parse(JSON.stringify(this.config));
  }

  /**
   * Watch config file for changes
   */
  watchConfigFile() {
    if (!this.loadedFrom) return;

    const watcher = fs.watch(this.loadedFrom, async (eventType) => {
      if (eventType === 'change') {
        this.emit('config:file-changed', { file: this.loadedFrom });

        try {
          const newConfig = await this.loadConfigFile(this.loadedFrom);
          const oldConfig = this.config;

          this.config = this.mergeWithDefaults(newConfig);
          this.applyEnvironment();
          this.applyEnvVars();
          this.validate();

          this.emit('config:reloaded', {
            oldConfig,
            newConfig: this.config,
            source: this.loadedFrom
          });
        } catch (error) {
          this.emit('config:reload-error', { error, file: this.loadedFrom });
        }
      }
    });

    this.watchers.set(this.loadedFrom, watcher);
  }

  /**
   * Stop watching config files
   */
  stopWatching() {
    for (const watcher of this.watchers.values()) {
      watcher.close();
    }
    this.watchers.clear();
  }

  /**
   * Save configuration to file
   */
  async save(filePath = null) {
    const targetPath = filePath || this.loadedFrom || path.join(this.options.configDir, CONFIG_FILES[1]);
    const ext = path.extname(targetPath);

    let content;
    if (ext === '.js') {
      content = `module.exports = ${JSON.stringify(this.getSafeConfig(), null, 2)};\n`;
    } else {
      content = JSON.stringify(this.getSafeConfig(), null, 2);
    }

    fs.writeFileSync(targetPath, content, 'utf8');
    this.emit('config:saved', { file: targetPath });

    return targetPath;
  }

  /**
   * Get config without sensitive values
   */
  getSafeConfig() {
    const config = this.getAll();
    this.maskSensitive(CONFIG_SCHEMA, config);
    return config;
  }

  /**
   * Mask sensitive values in config
   */
  maskSensitive(schema, config, mask = true) {
    for (const [key, def] of Object.entries(schema)) {
      if (def.type === 'object' && def.properties && config[key]) {
        this.maskSensitive(def.properties, config[key], mask);
      } else if (def.sensitive && config[key] && mask) {
        config[key] = '***REDACTED***';
      }
    }
  }

  /**
   * Generate config file template
   */
  generateTemplate(format = 'js') {
    const defaults = this.getDefaults();

    if (format === 'js') {
      return `/**
 * Design Bridge Configuration
 * @see https://design-bridge.dev/docs/configuration
 */
module.exports = ${JSON.stringify(defaults, null, 2)};
`;
    } else if (format === 'json') {
      return JSON.stringify(defaults, null, 2);
    }

    throw new Error(`Unsupported format: ${format}`);
  }

  /**
   * Get schema documentation
   */
  getSchemaDoc() {
    return this.generateSchemaDoc(CONFIG_SCHEMA, '', []);
  }

  /**
   * Generate schema documentation
   */
  generateSchemaDoc(schema, indent = '', docs = []) {
    for (const [key, def] of Object.entries(schema)) {
      const required = def.required ? ' (required)' : '';
      const defaultVal = def.default !== undefined ? ` [default: ${JSON.stringify(def.default)}]` : '';
      const enumVals = def.enum ? ` [options: ${def.enum.join(', ')}]` : '';
      const env = def.env ? ` [env: ${def.env}]` : '';

      if (def.type === 'object' && def.properties) {
        docs.push(`${indent}${key}: {${required}`);
        this.generateSchemaDoc(def.properties, indent + '  ', docs);
        docs.push(`${indent}}`);
      } else {
        docs.push(`${indent}${key}: ${def.type}${required}${defaultVal}${enumVals}${env}`);
      }
    }

    return docs.join('\n');
  }

  /**
   * Extend schema with custom fields
   */
  extendSchema(extension) {
    Object.assign(CONFIG_SCHEMA, extension);
    this.emit('schema:extended', { fields: Object.keys(extension) });
  }

  /**
   * Reset to defaults
   */
  reset() {
    this.config = this.getDefaults();
    this.loadedFrom = null;
    this.validationErrors = [];
    this.emit('config:reset');
  }

  /**
   * Create environment-specific config
   */
  createEnvConfig(env, overrides = {}) {
    const base = ENVIRONMENTS[env] || {};
    return this.deepMerge(this.deepMerge(this.getDefaults(), base), overrides);
  }

  /**
   * Export config for different environments
   */
  exportForEnv(env) {
    const envConfig = this.createEnvConfig(env);
    return JSON.stringify(envConfig, null, 2);
  }

  /**
   * Import config from external source
   */
  importConfig(externalConfig) {
    this.config = this.deepMerge(this.config, externalConfig);
    this.validate();
    this.emit('config:imported', { source: 'external' });
    return this;
  }

  /**
   * Clone configuration
   */
  clone() {
    const newInstance = new ConfigSystem(this.options);
    newInstance.config = this.getAll();
    newInstance.loadedFrom = this.loadedFrom;
    return newInstance;
  }
}

// Factory function
function createConfig(options = {}) {
  return new ConfigSystem(options);
}

// Export
module.exports = {
  ConfigSystem,
  createConfig,
  CONFIG_SCHEMA,
  ENVIRONMENTS,
  CONFIG_FILES,
  ConfigValidationError
};
