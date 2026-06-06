/**
 * Export Format Router
 * Sprint 32: Route generated code to correct export formats
 *
 * Handles format detection, conversion, and routing for:
 * - Styles: CSS, SCSS, Less, Styled-Components, Emotion
 * - Code: TypeScript, JavaScript, JSX, TSX
 * - Config: JSON, YAML, JS
 */

const EventEmitter = require('events');

class ExportFormatRouter extends EventEmitter {
  constructor(options = {}) {
    super();

    this.options = {
      defaultStyleFormat: options.defaultStyleFormat || 'css',
      defaultCodeFormat: options.defaultCodeFormat || 'typescript',
      enableConversion: options.enableConversion !== false,
      ...options
    };

    // Format mappings
    this.styleFormats = new Map([
      ['css', { extension: 'css', exporter: this.exportCSS.bind(this), supports: ['variables', 'nesting'] }],
      ['scss', { extension: 'scss', exporter: this.exportSCSS.bind(this), supports: ['variables', 'nesting', 'mixins', 'functions'] }],
      ['sass', { extension: 'sass', exporter: this.exportSass.bind(this), supports: ['variables', 'nesting', 'mixins'] }],
      ['less', { extension: 'less', exporter: this.exportLess.bind(this), supports: ['variables', 'nesting', 'mixins'] }],
      ['styled-components', { extension: 'ts', exporter: this.exportStyledComponents.bind(this), supports: ['props', 'theming'] }],
      ['emotion', { extension: 'ts', exporter: this.exportEmotion.bind(this), supports: ['props', 'css-prop'] }],
      ['css-modules', { extension: 'module.css', exporter: this.exportCSSModules.bind(this), supports: ['scoping'] }]
    ]);

    this.codeFormats = new Map([
      ['typescript', { extension: 'ts', exporter: this.exportTypeScript.bind(this), supports: ['types', 'interfaces'] }],
      ['tsx', { extension: 'tsx', exporter: this.exportTSX.bind(this), supports: ['types', 'jsx'] }],
      ['javascript', { extension: 'js', exporter: this.exportJavaScript.bind(this), supports: ['es6'] }],
      ['jsx', { extension: 'jsx', exporter: this.exportJSX.bind(this), supports: ['jsx'] }],
      ['es6', { extension: 'js', exporter: this.exportES6.bind(this), supports: ['modules'] }],
      ['commonjs', { extension: 'js', exporter: this.exportCommonJS.bind(this), supports: ['require'] }]
    ]);

    this.configFormats = new Map([
      ['json', { extension: 'json', exporter: this.exportJSON.bind(this) }],
      ['yaml', { extension: 'yaml', exporter: this.exportYAML.bind(this) }],
      ['js', { extension: 'js', exporter: this.exportJSConfig.bind(this) }]
    ]);

    // Statistics
    this.stats = {
      totalExports: 0,
      exportsByFormat: {},
      conversions: 0,
      lastExport: null
    };
  }

  /**
   * Route code to appropriate exporter
   */
  async route(content, contentType, targetFormat, options = {}) {
    this.stats.totalExports++;

    const exportId = `export_${Date.now()}`;

    this.emit('export:started', {
      id: exportId,
      contentType,
      targetFormat,
      timestamp: new Date().toISOString()
    });

    try {
      let result;

      // Route based on content type
      switch (contentType) {
        case 'style':
          result = await this.routeStyle(content, targetFormat, options);
          break;

        case 'code':
          result = await this.routeCode(content, targetFormat, options);
          break;

        case 'config':
          result = await this.routeConfig(content, targetFormat, options);
          break;

        default:
          throw new Error(`Unknown content type: ${contentType}`);
      }

      // Track statistics
      if (!this.stats.exportsByFormat[targetFormat]) {
        this.stats.exportsByFormat[targetFormat] = 0;
      }
      this.stats.exportsByFormat[targetFormat]++;
      this.stats.lastExport = new Date().toISOString();

      this.emit('export:completed', {
        id: exportId,
        format: targetFormat,
        size: result.content.length,
        timestamp: new Date().toISOString()
      });

      return result;

    } catch (error) {
      this.emit('export:failed', {
        id: exportId,
        error: error.message,
        timestamp: new Date().toISOString()
      });

      throw error;
    }
  }

  /**
   * Route style content
   */
  async routeStyle(content, targetFormat, options = {}) {
    const format = this.styleFormats.get(targetFormat);

    if (!format) {
      throw new Error(`Unsupported style format: ${targetFormat}`);
    }

    const exported = await format.exporter(content, options);

    return {
      content: exported,
      format: targetFormat,
      extension: format.extension,
      type: 'style',
      metadata: {
        supports: format.supports,
        timestamp: new Date().toISOString()
      }
    };
  }

  /**
   * Route code content
   */
  async routeCode(content, targetFormat, options = {}) {
    const format = this.codeFormats.get(targetFormat);

    if (!format) {
      throw new Error(`Unsupported code format: ${targetFormat}`);
    }

    const exported = await format.exporter(content, options);

    return {
      content: exported,
      format: targetFormat,
      extension: format.extension,
      type: 'code',
      metadata: {
        supports: format.supports,
        timestamp: new Date().toISOString()
      }
    };
  }

  /**
   * Route config content
   */
  async routeConfig(content, targetFormat, options = {}) {
    const format = this.configFormats.get(targetFormat);

    if (!format) {
      throw new Error(`Unsupported config format: ${targetFormat}`);
    }

    const exported = await format.exporter(content, options);

    return {
      content: exported,
      format: targetFormat,
      extension: format.extension,
      type: 'config',
      metadata: {
        timestamp: new Date().toISOString()
      }
    };
  }

  /**
   * Auto-detect format from content/filename
   */
  detectFormat(content, filename) {
    if (filename) {
      const ext = filename.split('.').pop().toLowerCase();

      // Check style formats
      for (const [format, config] of this.styleFormats) {
        if (ext === config.extension || ext === config.extension.replace('module.', '')) {
          return { type: 'style', format };
        }
      }

      // Check code formats
      for (const [format, config] of this.codeFormats) {
        if (ext === config.extension) {
          return { type: 'code', format };
        }
      }

      // Check config formats
      for (const [format, config] of this.configFormats) {
        if (ext === config.extension) {
          return { type: 'config', format };
        }
      }
    }

    // Detect from content
    if (typeof content === 'string') {
      if (content.includes('import') && content.includes('export')) {
        return { type: 'code', format: content.includes(':') ? 'typescript' : 'javascript' };
      }

      if (content.trim().startsWith('{')) {
        return { type: 'config', format: 'json' };
      }

      if (content.includes('$') && content.includes('@')) {
        return { type: 'style', format: 'scss' };
      }
    }

    return { type: 'unknown', format: 'unknown' };
  }

  /**
   * Convert between formats
   */
  async convert(content, fromFormat, toFormat, options = {}) {
    this.stats.conversions++;

    this.emit('conversion:started', { fromFormat, toFormat });

    // Special case: TypeScript to JavaScript
    if (fromFormat === 'typescript' && toFormat === 'javascript') {
      const converted = this.stripTypeAnnotations(content);
      return this.route(converted, 'code', toFormat, options);
    }

    // Special case: SCSS to CSS
    if (fromFormat === 'scss' && toFormat === 'css') {
      // Simplified SCSS to CSS conversion (would need sass compiler for full conversion)
      const converted = this.simplifyScss(content);
      return this.route(converted, 'style', toFormat, options);
    }

    // Default: route to target format directly
    const detected = this.detectFormat(content);
    return this.route(content, detected.type, toFormat, options);
  }

  // Style Exporters

  async exportCSS(content, options) {
    // Standard CSS export
    if (typeof content === 'object') {
      return this.objectToCSS(content);
    }
    return content;
  }

  async exportSCSS(content, options) {
    // SCSS export with variables and nesting
    if (typeof content === 'object') {
      return this.objectToSCSS(content);
    }
    return content;
  }

  async exportSass(content, options) {
    // Sass export (indented syntax)
    const scss = await this.exportSCSS(content, options);
    return this.scssToSass(scss);
  }

  async exportLess(content, options) {
    // Less export
    if (typeof content === 'object') {
      return this.objectToLess(content);
    }
    return content;
  }

  async exportStyledComponents(content, options) {
    // Styled-components export
    if (typeof content === 'object') {
      return this.objectToStyledComponents(content);
    }
    return content;
  }

  async exportEmotion(content, options) {
    // Emotion CSS export
    if (typeof content === 'object') {
      return this.objectToEmotion(content);
    }
    return content;
  }

  async exportCSSModules(content, options) {
    // CSS Modules export (scoped CSS)
    return this.exportCSS(content, options);
  }

  // Code Exporters

  async exportTypeScript(content, options) {
    // TypeScript export with type annotations
    if (typeof content === 'object') {
      return this.objectToTypeScript(content);
    }
    return content;
  }

  async exportTSX(content, options) {
    // TSX export (TypeScript + JSX)
    return this.exportTypeScript(content, { ...options, jsx: true });
  }

  async exportJavaScript(content, options) {
    // JavaScript export (strip types if present)
    if (typeof content === 'object') {
      return this.objectToJavaScript(content);
    }
    return this.stripTypeAnnotations(content);
  }

  async exportJSX(content, options) {
    // JSX export
    return this.exportJavaScript(content, { ...options, jsx: true });
  }

  async exportES6(content, options) {
    // ES6 module export
    return this.exportJavaScript(content, { ...options, modules: 'es6' });
  }

  async exportCommonJS(content, options) {
    // CommonJS export
    let code = await this.exportJavaScript(content, options);

    // Convert ES6 imports/exports to CommonJS
    code = code.replace(/import\s+(\w+)\s+from\s+['"](.+)['"]/g, 'const $1 = require(\'$2\')');
    code = code.replace(/export\s+default\s+/g, 'module.exports = ');
    code = code.replace(/export\s+\{([^}]+)\}/g, 'module.exports = { $1 }');

    return code;
  }

  // Config Exporters

  async exportJSON(content, options) {
    if (typeof content === 'object') {
      return JSON.stringify(content, null, 2);
    }
    return content;
  }

  async exportYAML(content, options) {
    if (typeof content === 'object') {
      return this.objectToYAML(content);
    }
    return content;
  }

  async exportJSConfig(content, options) {
    if (typeof content === 'object') {
      return `module.exports = ${JSON.stringify(content, null, 2)}`;
    }
    return content;
  }

  // Helper: Object to CSS
  objectToCSS(obj, selector = '') {
    let css = '';

    Object.entries(obj).forEach(([key, value]) => {
      if (typeof value === 'object' && !Array.isArray(value)) {
        css += this.objectToCSS(value, selector ? `${selector} ${key}` : key);
      } else {
        if (!selector) return;
        const prop = key.replace(/([A-Z])/g, '-$1').toLowerCase();
        css += `${selector} {\n  ${prop}: ${value};\n}\n\n`;
      }
    });

    return css;
  }

  // Helper: Object to SCSS
  objectToSCSS(obj, indent = 0) {
    let scss = '';
    const spaces = '  '.repeat(indent);

    Object.entries(obj).forEach(([key, value]) => {
      if (typeof value === 'object' && !Array.isArray(value)) {
        scss += `${spaces}${key} {\n`;
        scss += this.objectToSCSS(value, indent + 1);
        scss += `${spaces}}\n\n`;
      } else {
        const prop = key.replace(/([A-Z])/g, '-$1').toLowerCase();
        scss += `${spaces}${prop}: ${value};\n`;
      }
    });

    return scss;
  }

  // Helper: Strip type annotations
  stripTypeAnnotations(code) {
    return code
      .replace(/:\s*\w+(\[\])?(\s*=)/g, '$2') // Remove type annotations
      .replace(/:\s*\w+(\[\])?\s*[,;)]/g, '$1') // Remove type annotations before delimiters
      .replace(/<\w+>/g, '') // Remove generic types
      .replace(/interface\s+\w+\s*{[^}]+}/g, ''); // Remove interfaces
  }

  // Helper: Simplify SCSS to CSS
  simplifyScss(scss) {
    // Basic SCSS to CSS conversion (remove $ variables, flatten nesting)
    let css = scss
      .replace(/\$[\w-]+/g, '') // Remove variable references
      .replace(/@mixin\s+[\w-]+[^}]+}/g, ''); // Remove mixins

    return css;
  }

  // Helper: SCSS to Sass (indented syntax)
  scssToSass(scss) {
    return scss
      .replace(/\s*{\s*/g, '\n  ')
      .replace(/\s*}\s*/g, '\n')
      .replace(/;/g, '');
  }

  // Helper: Object to YAML
  objectToYAML(obj, indent = 0) {
    let yaml = '';
    const spaces = '  '.repeat(indent);

    Object.entries(obj).forEach(([key, value]) => {
      if (typeof value === 'object' && !Array.isArray(value)) {
        yaml += `${spaces}${key}:\n`;
        yaml += this.objectToYAML(value, indent + 1);
      } else {
        yaml += `${spaces}${key}: ${value}\n`;
      }
    });

    return yaml;
  }

  /**
   * Get supported formats
   */
  getSupportedFormats() {
    return {
      styles: Array.from(this.styleFormats.keys()),
      code: Array.from(this.codeFormats.keys()),
      config: Array.from(this.configFormats.keys())
    };
  }

  /**
   * Get format information
   */
  getFormatInfo(format) {
    return (
      this.styleFormats.get(format) ||
      this.codeFormats.get(format) ||
      this.configFormats.get(format) ||
      null
    );
  }

  /**
   * Get export statistics
   */
  getStats() {
    return {
      ...this.stats,
      supportedFormats: {
        styles: this.styleFormats.size,
        code: this.codeFormats.size,
        config: this.configFormats.size
      }
    };
  }

  /**
   * Test format routing
   */
  async testRouting() {
    console.log('🧪 Testing export format routing...\n');

    const testContent = {
      button: {
        backgroundColor: '#007bff',
        color: '#ffffff',
        padding: '10px 20px'
      }
    };

    const testFormats = ['css', 'scss', 'json'];

    for (const format of testFormats) {
      console.log(`Testing ${format} export...`);

      const detected = this.detectFormat(null, `test.${format}`);
      const result = await this.route(testContent, detected.type, format);

      console.log(`  ✓ Format: ${result.format}`);
      console.log(`  ✓ Extension: ${result.extension}`);
      console.log(`  ✓ Size: ${result.content.length} bytes\n`);
    }

    console.log('✅ Format routing test complete!\n');
  }
}

module.exports = ExportFormatRouter;
