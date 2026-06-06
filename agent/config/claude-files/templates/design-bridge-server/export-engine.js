/**
 * Export Engine - Multi-format design token export system
 * Supports CSS, SCSS, JSON, TypeScript, Style Dictionary, and more
 */

const { EventEmitter } = require('events');
const fs = require('fs').promises;
const path = require('path');

class ExportEngine extends EventEmitter {
  constructor(options = {}) {
    super();
    this.options = {
      outputDir: './design-tokens',
      formats: ['css', 'scss', 'json', 'typescript'],
      compression: false,
      validation: true,
      ...options
    };

    this.formatters = this.initializeFormatters();
    this.validators = this.initializeValidators();
  }

  async exportTokens(tokens, formats = this.options.formats, exportOptions = {}) {
    const startTime = Date.now();

    try {
      const exportResults = {
        success: true,
        exports: [],
        errors: [],
        metadata: {
          timestamp: new Date().toISOString(),
          formats: formats,
          tokenCount: this.countTokens(tokens),
          processingTime: 0
        }
      };

      // Validate tokens if enabled
      if (this.options.validation) {
        const validation = await this.validateTokensForExport(tokens);
        if (!validation.valid) {
          exportResults.errors.push(...validation.errors);
          if (validation.errors.some(error => error.severity === 'error')) {
            exportResults.success = false;
            return exportResults;
          }
        }
      }

      // Process each format
      for (const format of formats) {
        try {
          const formatResult = await this.exportFormat(tokens, format, exportOptions);
          exportResults.exports.push(formatResult);
          this.emit('format:exported', { format, result: formatResult });
        } catch (error) {
          exportResults.errors.push({
            format,
            error: error.message,
            severity: 'error'
          });
          this.emit('format:error', { format, error });
        }
      }

      exportResults.metadata.processingTime = Date.now() - startTime;
      this.emit('export:completed', exportResults);

      return exportResults;

    } catch (error) {
      this.emit('export:error', error);
      throw new Error(`Export failed: ${error.message}`);
    }
  }

  async exportFormat(tokens, format, options = {}) {
    const formatter = this.formatters[format];
    if (!formatter) {
      throw new Error(`Unsupported format: ${format}`);
    }

    const formatOptions = {
      ...this.getDefaultOptionsForFormat(format),
      ...options
    };

    const formatted = await formatter.format(tokens, formatOptions);
    const filePath = await this.writeFormattedOutput(formatted, format, formatOptions);

    return {
      format,
      filePath,
      size: formatted.content.length,
      options: formatOptions,
      metadata: formatted.metadata || {}
    };
  }

  initializeFormatters() {
    const formatters = require('./export-formatters.js');
    return {
      css: new formatters.CSSFormatter(),
      scss: new formatters.SCSSFormatter(),
      sass: new formatters.SassFormatter(),
      less: new formatters.LessFormatter(),
      stylus: new formatters.StylusFormatter(),
      json: new formatters.JSONFormatter(),
      yaml: new formatters.YAMLFormatter(),
      typescript: new formatters.TypeScriptFormatter(),
      javascript: new formatters.JavaScriptFormatter(),
      swift: new formatters.SwiftFormatter(),
      kotlin: new formatters.KotlinFormatter(),
      dart: new formatters.DartFormatter(),
      xml: new formatters.XMLFormatter(),
      plist: new formatters.PlistFormatter(),
      sketch: new formatters.SketchFormatter(),
      figma: new formatters.FigmaFormatter(),
      android: new formatters.AndroidFormatter(),
      ios: new formatters.iOSFormatter(),
      flutter: new formatters.FlutterFormatter(),
      reactNative: new formatters.ReactNativeFormatter(),
      styledComponents: new formatters.StyledComponentsFormatter(),
      emotion: new formatters.EmotionFormatter(),
      tailwind: new formatters.TailwindFormatter(),
      bootstrap: new formatters.BootstrapFormatter(),
      styleDictionary: new formatters.StyleDictionaryFormatter(),
      theorysix: new formatters.TheorySixFormatter()
    };
  }

  initializeValidators() {
    return {
      css: (tokens) => this.validateCSSTokens(tokens),
      typescript: (tokens) => this.validateTypeScriptTokens(tokens),
      json: (tokens) => this.validateJSONTokens(tokens)
    };
  }

  async validateTokensForExport(tokens) {
    const validation = {
      valid: true,
      errors: [],
      warnings: []
    };

    // Check for required properties
    if (!tokens || typeof tokens !== 'object') {
      validation.errors.push({
        type: 'structure',
        message: 'Tokens must be a valid object',
        severity: 'error'
      });
      validation.valid = false;
    }

    // Check for circular references
    try {
      JSON.stringify(tokens);
    } catch (error) {
      validation.errors.push({
        type: 'circular_reference',
        message: 'Tokens contain circular references',
        severity: 'error'
      });
      validation.valid = false;
    }

    // Check for valid token values
    const invalidTokens = this.findInvalidTokens(tokens);
    if (invalidTokens.length > 0) {
      validation.warnings.push({
        type: 'invalid_values',
        message: `Found ${invalidTokens.length} tokens with potentially invalid values`,
        severity: 'warning',
        tokens: invalidTokens
      });
    }

    return validation;
  }

  findInvalidTokens(tokens, path = '') {
    const invalid = [];

    const traverse = (obj, currentPath) => {
      Object.entries(obj).forEach(([key, value]) => {
        const fullPath = currentPath ? `${currentPath}.${key}` : key;

        if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
          traverse(value, fullPath);
        } else {
          // Check for common invalid patterns
          if (value === null || value === undefined) {
            invalid.push({ path: fullPath, value, issue: 'null_or_undefined' });
          } else if (typeof value === 'string' && value.trim() === '') {
            invalid.push({ path: fullPath, value, issue: 'empty_string' });
          } else if (typeof value === 'number' && (isNaN(value) || !isFinite(value))) {
            invalid.push({ path: fullPath, value, issue: 'invalid_number' });
          }
        }
      });
    };

    traverse(tokens, path);
    return invalid;
  }

  getDefaultOptionsForFormat(format) {
    const defaults = {
      css: {
        prefix: '--',
        selector: ':root',
        mediaQueries: true,
        customProperties: true
      },
      scss: {
        prefix: '$',
        maps: true,
        functions: true,
        mixins: true
      },
      typescript: {
        interface: true,
        enums: true,
        namespace: 'DesignTokens',
        exportType: 'const'
      },
      json: {
        indent: 2,
        sortKeys: true,
        metadata: true
      },
      swift: {
        struct: true,
        namespace: 'DesignTokens',
        accessibility: true
      },
      android: {
        resourceType: 'values',
        density: 'mdpi',
        generateDimens: true,
        generateColors: true
      }
    };

    return defaults[format] || {};
  }

  async writeFormattedOutput(formatted, format, options) {
    const outputDir = path.resolve(this.options.outputDir);
    await this.ensureDirectoryExists(outputDir);

    const fileName = this.generateFileName(format, options);
    const filePath = path.join(outputDir, fileName);

    let content = formatted.content;

    // Apply compression if enabled
    if (this.options.compression && this.supportsCompression(format)) {
      content = this.compressContent(content, format);
    }

    await fs.writeFile(filePath, content, 'utf8');

    // Write additional files if needed (e.g., TypeScript declarations)
    if (formatted.additionalFiles) {
      for (const [additionalFileName, additionalContent] of Object.entries(formatted.additionalFiles)) {
        const additionalPath = path.join(outputDir, additionalFileName);
        await fs.writeFile(additionalPath, additionalContent, 'utf8');
      }
    }

    return filePath;
  }

  generateFileName(format, options) {
    const extensions = {
      css: 'css',
      scss: 'scss',
      sass: 'sass',
      less: 'less',
      stylus: 'styl',
      json: 'json',
      yaml: 'yml',
      typescript: 'ts',
      javascript: 'js',
      swift: 'swift',
      kotlin: 'kt',
      dart: 'dart',
      xml: 'xml',
      plist: 'plist'
    };

    const extension = extensions[format] || format;
    const prefix = options.fileName || 'design-tokens';
    const suffix = options.suffix ? `-${options.suffix}` : '';

    return `${prefix}${suffix}.${extension}`;
  }

  async ensureDirectoryExists(dir) {
    try {
      await fs.access(dir);
    } catch {
      await fs.mkdir(dir, { recursive: true });
    }
  }

  supportsCompression(format) {
    return ['css', 'scss', 'json', 'javascript'].includes(format);
  }

  compressContent(content, format) {
    switch (format) {
      case 'css':
      case 'scss':
        return content
          .replace(/\s+/g, ' ')
          .replace(/;\s*}/g, '}')
          .replace(/,\s*/g, ',')
          .trim();

      case 'json':
        try {
          return JSON.stringify(JSON.parse(content));
        } catch {
          return content;
        }

      case 'javascript':
        return content
          .replace(/\s+/g, ' ')
          .replace(/;\s*/g, ';')
          .trim();

      default:
        return content;
    }
  }

  countTokens(tokens) {
    let count = 0;

    const traverse = (obj) => {
      Object.values(obj).forEach(value => {
        if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
          traverse(value);
        } else {
          count++;
        }
      });
    };

    traverse(tokens);
    return count;
  }

  // Utility methods for specific validations
  validateCSSTokens(tokens) {
    const errors = [];

    // Check for valid CSS property names
    const invalidCSSNames = this.findInvalidCSSNames(tokens);
    if (invalidCSSNames.length > 0) {
      errors.push({
        type: 'invalid_css_names',
        message: 'Found tokens with invalid CSS property names',
        tokens: invalidCSSNames
      });
    }

    return { valid: errors.length === 0, errors };
  }

  validateTypeScriptTokens(tokens) {
    const errors = [];

    // Check for valid TypeScript identifiers
    const invalidTSNames = this.findInvalidTypeScriptNames(tokens);
    if (invalidTSNames.length > 0) {
      errors.push({
        type: 'invalid_ts_names',
        message: 'Found tokens with invalid TypeScript identifiers',
        tokens: invalidTSNames
      });
    }

    return { valid: errors.length === 0, errors };
  }

  validateJSONTokens(tokens) {
    const errors = [];

    try {
      JSON.stringify(tokens);
    } catch (error) {
      errors.push({
        type: 'json_serialization',
        message: 'Tokens cannot be serialized to JSON',
        error: error.message
      });
    }

    return { valid: errors.length === 0, errors };
  }

  findInvalidCSSNames(tokens, path = '') {
    const invalid = [];
    const cssNameRegex = /^[a-zA-Z-][a-zA-Z0-9-]*$/;

    const traverse = (obj, currentPath) => {
      Object.keys(obj).forEach(key => {
        const fullPath = currentPath ? `${currentPath}.${key}` : key;

        if (!cssNameRegex.test(key)) {
          invalid.push({ path: fullPath, name: key, issue: 'invalid_css_name' });
        }

        if (typeof obj[key] === 'object' && obj[key] !== null && !Array.isArray(obj[key])) {
          traverse(obj[key], fullPath);
        }
      });
    };

    traverse(tokens, path);
    return invalid;
  }

  findInvalidTypeScriptNames(tokens, path = '') {
    const invalid = [];
    const tsNameRegex = /^[a-zA-Z_$][a-zA-Z0-9_$]*$/;

    const traverse = (obj, currentPath) => {
      Object.keys(obj).forEach(key => {
        const fullPath = currentPath ? `${currentPath}.${key}` : key;

        if (!tsNameRegex.test(key)) {
          invalid.push({ path: fullPath, name: key, issue: 'invalid_ts_name' });
        }

        if (typeof obj[key] === 'object' && obj[key] !== null && !Array.isArray(obj[key])) {
          traverse(obj[key], fullPath);
        }
      });
    };

    traverse(tokens, path);
    return invalid;
  }

  // Export presets for common use cases
  async exportForWeb(tokens, options = {}) {
    return await this.exportTokens(tokens, ['css', 'scss', 'json'], {
      css: { prefix: '--', mediaQueries: true },
      scss: { maps: true, functions: true },
      json: { indent: 2, metadata: true },
      ...options
    });
  }

  async exportForMobile(tokens, options = {}) {
    return await this.exportTokens(tokens, ['swift', 'kotlin', 'dart'], {
      swift: { struct: true, accessibility: true },
      kotlin: { objects: true, extensions: true },
      dart: { classes: true, constants: true },
      ...options
    });
  }

  async exportForReact(tokens, options = {}) {
    return await this.exportTokens(tokens, ['typescript', 'styledComponents', 'emotion'], {
      typescript: { interface: true, namespace: 'Theme' },
      styledComponents: { theme: true, typescript: true },
      emotion: { theme: true, typescript: true },
      ...options
    });
  }

  async exportForDesignTools(tokens, options = {}) {
    return await this.exportTokens(tokens, ['sketch', 'figma', 'styleDictionary'], {
      sketch: { symbols: true, artboards: true },
      figma: { components: true, styles: true },
      styleDictionary: { transforms: true, formats: ['css', 'ios', 'android'] },
      ...options
    });
  }

  // Batch export functionality
  async batchExport(tokensArray, formats, options = {}) {
    const results = [];

    for (let i = 0; i < tokensArray.length; i++) {
      const tokens = tokensArray[i];
      const batchOptions = {
        ...options,
        suffix: options.suffix ? `${options.suffix}-${i + 1}` : `batch-${i + 1}`
      };

      try {
        const result = await this.exportTokens(tokens, formats, batchOptions);
        results.push(result);
      } catch (error) {
        results.push({
          success: false,
          error: error.message,
          index: i
        });
      }
    }

    return results;
  }

  // Live export functionality for real-time updates
  setupLiveExport(tokens, formats, options = {}) {
    const liveExporter = {
      update: async (updatedTokens) => {
        return await this.exportTokens(updatedTokens, formats, {
          ...options,
          suffix: `live-${Date.now()}`
        });
      },

      stop: () => {
        this.removeAllListeners('tokens:updated');
      }
    };

    // Listen for token updates
    this.on('tokens:updated', async (updatedTokens) => {
      try {
        await liveExporter.update(updatedTokens);
        this.emit('live:exported', { formats, timestamp: Date.now() });
      } catch (error) {
        this.emit('live:error', error);
      }
    });

    return liveExporter;
  }

  // Export statistics and analytics
  getExportStatistics() {
    return {
      totalExports: this.listenerCount('format:exported'),
      formatUsage: this.getFormatUsageStats(),
      averageProcessingTime: this.getAverageProcessingTime(),
      errorRate: this.getErrorRate()
    };
  }

  getFormatUsageStats() {
    // This would be implemented with proper tracking
    return {};
  }

  getAverageProcessingTime() {
    // This would be implemented with proper tracking
    return 0;
  }

  getErrorRate() {
    // This would be implemented with proper tracking
    return 0;
  }
}

module.exports = ExportEngine;