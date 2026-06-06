/**
 * Template Engine
 * Enhanced template system for code generation
 * Sprint 33-36: Template Engine Enhancement
 */

const EventEmitter = require('events');

class TemplateEngine extends EventEmitter {
  constructor(options = {}) {
    super();
    this.templates = new Map();
    this.partials = new Map();
    this.helpers = new Map();

    this.initializeHelpers();
  }

  /**
   * Initialize template helpers
   */
  initializeHelpers() {
    // String helpers
    this.helpers.set('capitalize', (str) =>
      str.charAt(0).toUpperCase() + str.slice(1)
    );

    this.helpers.set('camelCase', (str) =>
      str.replace(/[-_](.)/g, (_, c) => c.toUpperCase())
    );

    this.helpers.set('pascalCase', (str) => {
      const camel = this.helpers.get('camelCase')(str);
      return camel.charAt(0).toUpperCase() + camel.slice(1);
    });

    this.helpers.set('kebabCase', (str) =>
      str.replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase()
    );

    // Conditional helpers
    this.helpers.set('if', (condition, trueVal, falseVal) =>
      condition ? trueVal : falseVal
    );

    this.helpers.set('unless', (condition, trueVal, falseVal) =>
      !condition ? trueVal : falseVal
    );

    // Array helpers
    this.helpers.set('join', (arr, separator = ', ') =>
      Array.isArray(arr) ? arr.join(separator) : arr
    );

    this.helpers.set('map', (arr, fn) =>
      Array.isArray(arr) ? arr.map(fn) : []
    );
  }

  /**
   * Register template
   * @param {string} name - Template name
   * @param {string} template - Template string
   */
  registerTemplate(name, template) {
    this.templates.set(name, template);
    this.emit('template:registered', { name });
  }

  /**
   * Register partial template
   * @param {string} name - Partial name
   * @param {string} template - Partial template
   */
  registerPartial(name, template) {
    this.partials.set(name, template);
    this.emit('partial:registered', { name });
  }

  /**
   * Register helper function
   * @param {string} name - Helper name
   * @param {Function} fn - Helper function
   */
  registerHelper(name, fn) {
    this.helpers.set(name, fn);
    this.emit('helper:registered', { name });
  }

  /**
   * Render template with data
   * @param {string} templateName - Template name or string
   * @param {Object} data - Template data
   * @returns {string} Rendered output
   */
  render(templateName, data = {}) {
    let template = this.templates.get(templateName) || templateName;

    // Process partials
    template = this.processPartials(template, data);

    // Process conditionals and loops first (they have block syntax)
    template = this.processConditionals(template, data);
    template = this.processLoops(template, data);

    // Process helpers (single-tag syntax)
    template = this.processHelpers(template, data);

    // Process variables last
    template = this.processVariables(template, data);

    return template;
  }

  /**
   * Process partial includes
   * @param {string} template - Template string
   * @param {Object} data - Template data
   * @returns {string} Processed template
   */
  processPartials(template, data) {
    const partialRegex = /\{\{>\s*(\w+)\s*\}\}/g;

    return template.replace(partialRegex, (match, partialName) => {
      const partial = this.partials.get(partialName);
      return partial ? this.render(partial, data) : match;
    });
  }

  /**
   * Process helper functions
   * @param {string} template - Template string
   * @param {Object} data - Template data
   * @returns {string} Processed template
   */
  processHelpers(template, data) {
    const helperRegex = /\{\{#(\w+)\s+([^}]+)\}\}/g;

    return template.replace(helperRegex, (match, helperName, args) => {
      const helper = this.helpers.get(helperName);
      if (!helper) return match;

      try {
        const argValues = this.parseArgs(args, data);
        const result = helper(...argValues);
        return result !== undefined ? result : '';
      } catch (error) {
        console.error(`Helper ${helperName} error:`, error);
        return match;
      }
    });
  }

  /**
   * Process variables
   * @param {string} template - Template string
   * @param {Object} data - Template data
   * @returns {string} Processed template
   */
  processVariables(template, data) {
    const varRegex = /\{\{\s*([^#\/><][^}]*?)\s*\}\}/g;

    return template.replace(varRegex, (match, path) => {
      const value = this.resolveValue(path.trim(), data);
      return value !== undefined ? value : match;
    });
  }

  /**
   * Process conditionals (if/else)
   * @param {string} template - Template string
   * @param {Object} data - Template data
   * @returns {string} Processed template
   */
  processConditionals(template, data) {
    const ifRegex = /\{\{#if\s+([^}]+)\}\}([\s\S]*?)(?:\{\{#else\}\}([\s\S]*?))?\{\{\/if\}\}/g;

    return template.replace(ifRegex, (match, condition, trueBlock, falseBlock = '') => {
      const value = this.resolveValue(condition.trim(), data);
      return this.isTruthy(value) ? this.render(trueBlock, data) : this.render(falseBlock, data);
    });
  }

  /**
   * Process loops (each)
   * @param {string} template - Template string
   * @param {Object} data - Template data
   * @returns {string} Processed template
   */
  processLoops(template, data) {
    const eachRegex = /\{\{#each\s+(\w+)\}\}([\s\S]*?)\{\{\/each\}\}/g;

    return template.replace(eachRegex, (match, arrayName, loopTemplate) => {
      const array = this.resolveValue(arrayName, data);

      if (!Array.isArray(array)) return '';

      return array.map((item, index) => {
        const loopData = {
          ...data,
          this: item,
          '@index': index,
          '@first': index === 0,
          '@last': index === array.length - 1,
          '@key': item.id || item.key || index
        };
        return this.render(loopTemplate, loopData);
      }).join('');
    });
  }

  /**
   * Resolve value from data using path
   * @param {string} path - Dot notation path
   * @param {Object} data - Data object
   * @returns {*} Resolved value
   */
  resolveValue(path, data) {
    if (path === 'this') return data.this;
    if (path.startsWith('@')) return data[path];

    const parts = path.split('.');
    let value = data;

    for (const part of parts) {
      if (value && typeof value === 'object' && part in value) {
        value = value[part];
      } else {
        return undefined;
      }
    }

    return value;
  }

  /**
   * Parse helper arguments
   * @param {string} argsString - Arguments string
   * @param {Object} data - Template data
   * @returns {Array} Parsed arguments
   */
  parseArgs(argsString, data) {
    return argsString.split(/\s+/).map(arg => {
      // String literal
      if (arg.startsWith('"') || arg.startsWith("'")) {
        return arg.slice(1, -1);
      }

      // Number
      if (!isNaN(arg)) {
        return parseFloat(arg);
      }

      // Variable
      return this.resolveValue(arg, data);
    });
  }

  /**
   * Check if value is truthy
   * @param {*} value - Value to check
   * @returns {boolean} Is truthy
   */
  isTruthy(value) {
    return !!value && value !== '' && value !== 0 && value !== 'false';
  }

  /**
   * Clear all templates and partials
   */
  clear() {
    this.templates.clear();
    this.partials.clear();
    this.emit('templates:cleared');
  }

  /**
   * Get template names
   * @returns {Array} Template names
   */
  getTemplateNames() {
    return Array.from(this.templates.keys());
  }

  /**
   * Get partial names
   * @returns {Array} Partial names
   */
  getPartialNames() {
    return Array.from(this.partials.keys());
  }

  /**
   * Get helper names
   * @returns {Array} Helper names
   */
  getHelperNames() {
    return Array.from(this.helpers.keys());
  }
}

// Singleton instance
let instance = null;

function getTemplateEngine() {
  if (!instance) {
    instance = new TemplateEngine();
  }
  return instance;
}

module.exports = { TemplateEngine, getTemplateEngine };
