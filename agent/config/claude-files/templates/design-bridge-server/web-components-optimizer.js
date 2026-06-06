/**
 * Web Components & Accessibility Optimizer
 * Generates accessible, standards-compliant Web Components
 * Sprint 16: Web Components & Accessibility
 *
 * v4.0.0 Integration:
 * - Supports registry v4.0.0 canonical IDs
 * - O(1) component lookup via RegistryManager
 * - Static optimize() accepts entries from v4 registry
 *
 * @version 2.0.0
 */

const SmartCodeGenerator = require('./smart-code-generator');

// Lazy-load RegistryManager to avoid circular dependencies (v4.0.0)
let _registryManagerModule = null;
function getRegistryManagerModule() {
  if (!_registryManagerModule) {
    try {
      _registryManagerModule = require('./registry-manager');
    } catch (e) {
      _registryManagerModule = null;
    }
  }
  return _registryManagerModule;
}


class WebComponentsOptimizer {
  constructor() {
    this.name = 'WebComponentsOptimizer';
    this.version = '1.0.0';
    this.framework = 'web-components';

    // Web Components configuration
    this.config = {
      shadowDOM: true,
      customElements: true,
      htmlTemplates: true,
      cssVariables: true,
      slots: true,
      lifecycle: true,
      accessibility: {
        wcag: 'AA', // A, AA, AAA
        ariaSupport: true,
        keyboardNavigation: true,
        screenReaderOptimized: true,
        focusManagement: true,
        contrastRatio: 'AA',
        semanticHTML: true,
        announcements: true,
        skipLinks: false,
        reducedMotion: true
      },
      polyfills: false,
      typescript: true,
      litElement: false // Option to use Lit instead of vanilla
    };

    // WCAG compliance patterns
    this.wcagPatterns = {
      'A': this.getWCAG_A_Requirements(),
      'AA': this.getWCAG_AA_Requirements(),
      'AAA': this.getWCAG_AAA_Requirements()
    };

    // ARIA patterns
    this.ariaPatterns = this.getARIAPatterns();
  }

  /**
   * Optimize code for Web Components with accessibility
  
 *
 * v4.0.0 Integration:
 * - Supports registry v4.0.0 canonical IDs
 * - O(1) component lookup via RegistryManager
 * - Static optimize() accepts entries from v4 registry
 */
  async optimize(code, componentData, config) {
    let optimizedCode = code;

    // Apply Web Components optimizations
    optimizedCode = await this.optimizeShadowDOM(optimizedCode, componentData, config);
    optimizedCode = await this.optimizeCustomElements(optimizedCode, componentData, config);
    optimizedCode = await this.optimizeSlots(optimizedCode, componentData, config);

    // Apply accessibility optimizations
    optimizedCode = await this.optimizeAccessibility(optimizedCode, componentData, config);
    optimizedCode = await this.addARIASupport(optimizedCode, componentData, config);
    optimizedCode = await this.addKeyboardSupport(optimizedCode, componentData, config);
    optimizedCode = await this.addFocusManagement(optimizedCode, componentData, config);
    optimizedCode = await this.addScreenReaderSupport(optimizedCode, componentData, config);

    return optimizedCode;
  }

  /**
   * Generate Web Component from design data
   */
  async generateComponent(componentData, config) {
    const mergedConfig = { ...this.config, ...config };

    // Generate Web Component
    const component = mergedConfig.litElement
      ? this.generateLitElement(componentData, mergedConfig)
      : this.generateVanillaWebComponent(componentData, mergedConfig);

    return component;
  }

  /**
   * Generate Vanilla Web Component
   */
  generateVanillaWebComponent(data, config) {
    const { name, props, state, styles } = data;
    const tagName = this.toKebabCase(name);

    let code = [];

    // Class definition
    code.push(`class ${name} extends HTMLElement {`);

    // Constructor
    code.push('  constructor() {');
    code.push('    super();');

    if (config.shadowDOM) {
      code.push("    this.attachShadow({ mode: 'open' });");
    }

    // Initialize state
    if (state) {
      code.push(this.generateStateInitialization(state));
    }

    // Bind methods
    code.push(this.generateMethodBindings(data));

    code.push('  }');
    code.push('');

    // Observed attributes
    if (props && Object.keys(props).length > 0) {
      code.push('  static get observedAttributes() {');
      code.push(`    return [${Object.keys(props).map(p => `'${this.toKebabCase(p)}'`).join(', ')}];`);
      code.push('  }');
      code.push('');
    }

    // Properties getters/setters
    if (props) {
      code.push(this.generateProperties(props));
    }

    // Connected callback
    code.push('  connectedCallback() {');
    code.push('    this.render();');
    code.push('    this.setupEventListeners();');
    code.push('    this.setupAccessibility();');
    if (config.accessibility.keyboardNavigation) {
      code.push('    this.setupKeyboardNavigation();');
    }
    if (config.accessibility.focusManagement) {
      code.push('    this.setupFocusManagement();');
    }
    code.push('  }');
    code.push('');

    // Disconnected callback
    code.push('  disconnectedCallback() {');
    code.push('    this.removeEventListeners();');
    code.push('  }');
    code.push('');

    // Attribute changed callback
    code.push('  attributeChangedCallback(name, oldValue, newValue) {');
    code.push('    if (oldValue !== newValue) {');
    code.push('      this.render();');
    code.push('    }');
    code.push('  }');
    code.push('');

    // Render method
    code.push('  render() {');
    code.push('    const template = this.getTemplate();');
    code.push('    const styles = this.getStyles();');

    if (config.shadowDOM) {
      code.push('    this.shadowRoot.innerHTML = `');
      code.push('      <style>${styles}</style>');
      code.push('      ${template}');
      code.push('    `;');
    } else {
      code.push('    this.innerHTML = template;');
    }

    code.push('  }');
    code.push('');

    // Template method
    code.push('  getTemplate() {');
    code.push(this.generateTemplate(data, config));
    code.push('  }');
    code.push('');

    // Styles method
    code.push('  getStyles() {');
    code.push(this.generateComponentStyles(data, config));
    code.push('  }');
    code.push('');

    // Event listeners setup
    code.push('  setupEventListeners() {');
    code.push(this.generateEventListeners(data));
    code.push('  }');
    code.push('');

    // Event listeners cleanup
    code.push('  removeEventListeners() {');
    code.push('    // Remove event listeners');
    code.push('  }');
    code.push('');

    // Accessibility setup
    code.push('  setupAccessibility() {');
    code.push(this.generateAccessibilitySetup(data, config));
    code.push('  }');
    code.push('');

    // Keyboard navigation
    if (config.accessibility.keyboardNavigation) {
      code.push('  setupKeyboardNavigation() {');
      code.push(this.generateKeyboardNavigation(data));
      code.push('  }');
      code.push('');
    }

    // Focus management
    if (config.accessibility.focusManagement) {
      code.push('  setupFocusManagement() {');
      code.push(this.generateFocusManagement(data));
      code.push('  }');
      code.push('');
    }

    // Custom methods
    if (data.methods) {
      Object.entries(data.methods).forEach(([name, method]) => {
        code.push(`  ${name}(${method.params || ''}) {`);
        code.push(`    ${method.body}`);
        code.push('  }');
        code.push('');
      });
    }

    code.push('}');
    code.push('');

    // Register custom element
    code.push(`customElements.define('${tagName}', ${name});`);
    code.push('');

    // Export
    code.push(`export default ${name};`);

    return code.join('\n');
  }

  /**
   * Generate Lit Element (alternative)
   */
  generateLitElement(data, config) {
    const { name, props, state } = data;
    const tagName = this.toKebabCase(name);

    let code = [];

    // Imports
    code.push("import { LitElement, html, css } from 'lit';");
    code.push("import { customElement, property, state } from 'lit/decorators.js';");
    code.push('');

    // Component class
    code.push(`@customElement('${tagName}')`);
    code.push(`class ${name} extends LitElement {`);

    // Static styles
    code.push('  static styles = css`');
    code.push(this.generateLitStyles(data, config));
    code.push('  `;');
    code.push('');

    // Properties
    if (props) {
      Object.entries(props).forEach(([key, prop]) => {
        code.push(`  @property({ type: ${this.getLitType(prop.type)} })`);
        code.push(`  ${key} = ${JSON.stringify(prop.default || '')};`);
        code.push('');
      });
    }

    // State
    if (state) {
      Object.entries(state).forEach(([key, value]) => {
        code.push('  @state()');
        code.push(`  ${key} = ${JSON.stringify(value)};`);
        code.push('');
      });
    }

    // Render method
    code.push('  render() {');
    code.push('    return html`');
    code.push(this.generateLitTemplate(data, config));
    code.push('    `;');
    code.push('  }');

    code.push('}');
    code.push('');

    code.push(`export default ${name};`);

    return code.join('\n');
  }

  /**
   * Generate template
   */
  generateTemplate(data, config) {
    const { name } = data;
    const className = this.toKebabCase(name);

    let template = [];

    template.push('    return `');
    template.push(`      <div class="${className}" role="${this.getRole(data)}">`);

    // Skip link for keyboard navigation
    if (config.accessibility.skipLinks) {
      template.push('        <a href="#main-content" class="skip-link">Skip to main content</a>');
    }

    // Header with proper heading hierarchy
    if (data.header) {
      template.push(`        <header role="banner">`);
      template.push(`          <h1>${data.header}</h1>`);
      template.push('        </header>');
    }

    // Main content with landmark
    template.push('        <main id="main-content" role="main">');

    // Slots for content projection
    if (data.slots) {
      data.slots.forEach(slot => {
        const slotName = slot.name ? ` name="${slot.name}"` : '';
        template.push(`          <slot${slotName}>${slot.fallback || ''}</slot>`);
      });
    } else {
      template.push('          <slot></slot>');
    }

    template.push('        </main>');

    // Footer with proper role
    if (data.footer) {
      template.push('        <footer role="contentinfo">');
      template.push(`          ${data.footer}`);
      template.push('        </footer>');
    }

    template.push('      </div>');
    template.push('    `;');

    return template.join('\n');
  }

  /**
   * Generate component styles
   */
  generateComponentStyles(data, config) {
    const { name } = data;
    const className = this.toKebabCase(name);

    let styles = [];

    styles.push('    return `');

    // CSS custom properties for theming
    styles.push('      :host {');
    styles.push('        --primary-color: #007bff;');
    styles.push('        --text-color: #333;');
    styles.push('        --background-color: #fff;');
    styles.push('        --focus-color: #0056b3;');
    styles.push('        --focus-outline: 2px solid var(--focus-color);');
    styles.push('        display: block;');
    styles.push('      }');
    styles.push('');

    // Skip link styles
    if (config.accessibility.skipLinks) {
      styles.push('      .skip-link {');
      styles.push('        position: absolute;');
      styles.push('        top: -40px;');
      styles.push('        left: 0;');
      styles.push('        background: var(--primary-color);');
      styles.push('        color: white;');
      styles.push('        padding: 8px;');
      styles.push('        text-decoration: none;');
      styles.push('        z-index: 100;');
      styles.push('      }');
      styles.push('');
      styles.push('      .skip-link:focus {');
      styles.push('        top: 0;');
      styles.push('      }');
      styles.push('');
    }

    // Focus styles for accessibility
    styles.push('      :focus {');
    styles.push('        outline: var(--focus-outline);');
    styles.push('        outline-offset: 2px;');
    styles.push('      }');
    styles.push('');

    // Reduced motion support
    if (config.accessibility.reducedMotion) {
      styles.push('      @media (prefers-reduced-motion: reduce) {');
      styles.push('        * {');
      styles.push('          animation-duration: 0.01ms !important;');
      styles.push('          animation-iteration-count: 1 !important;');
      styles.push('          transition-duration: 0.01ms !important;');
      styles.push('        }');
      styles.push('      }');
      styles.push('');
    }

    // High contrast mode support
    styles.push('      @media (prefers-contrast: high) {');
    styles.push('        :host {');
    styles.push('          --primary-color: #000;');
    styles.push('          --background-color: #fff;');
    styles.push('        }');
    styles.push('      }');
    styles.push('');

    // Dark mode support
    styles.push('      @media (prefers-color-scheme: dark) {');
    styles.push('        :host {');
    styles.push('          --text-color: #f0f0f0;');
    styles.push('          --background-color: #1a1a1a;');
    styles.push('        }');
    styles.push('      }');

    styles.push('    `;');

    return styles.join('\n');
  }

  /**
   * Generate accessibility setup
   */
  generateAccessibilitySetup(data, config) {
    const setup = [];
    const root = config.shadowDOM ? 'this.shadowRoot' : 'this';

    // Set ARIA attributes
    setup.push(`    // Set ARIA attributes`);
    setup.push(`    this.setAttribute('role', '${this.getRole(data)}');`);

    if (data.ariaLabel) {
      setup.push(`    this.setAttribute('aria-label', '${data.ariaLabel}');`);
    }

    // Live regions for announcements
    if (config.accessibility.announcements) {
      setup.push(`    // Setup live region for announcements`);
      setup.push(`    const liveRegion = document.createElement('div');`);
      setup.push(`    liveRegion.setAttribute('role', 'status');`);
      setup.push(`    liveRegion.setAttribute('aria-live', 'polite');`);
      setup.push(`    liveRegion.setAttribute('aria-atomic', 'true');`);
      setup.push(`    liveRegion.className = 'sr-only';`);
      setup.push(`    ${root}.appendChild(liveRegion);`);
    }

    // Form field associations
    if (data.type === 'input' || data.type === 'form') {
      setup.push(`    // Associate labels with form fields`);
      setup.push(`    const inputs = ${root}.querySelectorAll('input, select, textarea');`);
      setup.push(`    inputs.forEach((input, index) => {`);
      setup.push(`      if (!input.id) input.id = \`input-\${index}\`;`);
      setup.push(`      const label = input.previousElementSibling;`);
      setup.push(`      if (label && label.tagName === 'LABEL') {`);
      setup.push(`        label.setAttribute('for', input.id);`);
      setup.push(`      }`);
      setup.push(`    });`);
    }

    return setup.join('\n');
  }

  /**
   * Generate keyboard navigation
   */
  generateKeyboardNavigation(data) {
    const nav = [];

    nav.push(`    // Keyboard navigation`);
    nav.push(`    this.addEventListener('keydown', (e) => {`);
    nav.push(`      switch(e.key) {`);
    nav.push(`        case 'Enter':`);
    nav.push(`        case ' ':`);
    nav.push(`          if (e.target.matches('button, a, [role="button"]')) {`);
    nav.push(`            e.preventDefault();`);
    nav.push(`            e.target.click();`);
    nav.push(`          }`);
    nav.push(`          break;`);
    nav.push(`        case 'Escape':`);
    nav.push(`          if (this.hasAttribute('closable')) {`);
    nav.push(`            this.close();`);
    nav.push(`          }`);
    nav.push(`          break;`);
    nav.push(`        case 'Tab':`);
    nav.push(`          // Handle tab navigation`);
    nav.push(`          this.handleTabNavigation(e);`);
    nav.push(`          break;`);
    nav.push(`        case 'ArrowUp':`);
    nav.push(`        case 'ArrowDown':`);
    nav.push(`          // Handle arrow navigation for menus/lists`);
    nav.push(`          this.handleArrowNavigation(e);`);
    nav.push(`          break;`);
    nav.push(`      }`);
    nav.push(`    });`);

    return nav.join('\n');
  }

  /**
   * Generate focus management
   */
  generateFocusManagement(data) {
    const focus = [];

    focus.push(`    // Focus management`);
    focus.push(`    const focusableElements = this.querySelectorAll(`);
    focus.push(`      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'`);
    focus.push(`    );`);
    focus.push(``);
    focus.push(`    if (focusableElements.length > 0) {`);
    focus.push(`      this.firstFocusableElement = focusableElements[0];`);
    focus.push(`      this.lastFocusableElement = focusableElements[focusableElements.length - 1];`);
    focus.push(`    }`);
    focus.push(``);
    focus.push(`    // Trap focus for modal-like components`);
    focus.push(`    if (this.hasAttribute('trap-focus')) {`);
    focus.push(`      this.addEventListener('keydown', (e) => {`);
    focus.push(`        if (e.key === 'Tab') {`);
    focus.push(`          if (e.shiftKey && document.activeElement === this.firstFocusableElement) {`);
    focus.push(`            e.preventDefault();`);
    focus.push(`            this.lastFocusableElement.focus();`);
    focus.push(`          } else if (!e.shiftKey && document.activeElement === this.lastFocusableElement) {`);
    focus.push(`            e.preventDefault();`);
    focus.push(`            this.firstFocusableElement.focus();`);
    focus.push(`          }`);
    focus.push(`        }`);
    focus.push(`      });`);
    focus.push(`    }`);

    return focus.join('\n');
  }

  /**
   * Helper: Get WCAG requirements
   */
  getWCAG_A_Requirements() {
    return {
      altText: true,
      headingHierarchy: true,
      keyboardAccess: true,
      formLabels: true,
      errorIdentification: true
    };
  }

  getWCAG_AA_Requirements() {
    return {
      ...this.getWCAG_A_Requirements(),
      colorContrast: 4.5,
      focusVisible: true,
      consistentNavigation: true,
      multipleWays: true,
      headingsAndLabels: true
    };
  }

  getWCAG_AAA_Requirements() {
    return {
      ...this.getWCAG_AA_Requirements(),
      colorContrast: 7,
      contextChanges: true,
      unusualWords: true,
      abbreviations: true,
      readingLevel: true
    };
  }

  /**
   * Helper: Get ARIA patterns
   */
  getARIAPatterns() {
    return {
      landmarks: ['banner', 'main', 'navigation', 'contentinfo', 'complementary'],
      roles: ['button', 'link', 'textbox', 'checkbox', 'radio', 'combobox', 'listbox'],
      properties: ['aria-label', 'aria-labelledby', 'aria-describedby', 'aria-required'],
      states: ['aria-expanded', 'aria-selected', 'aria-checked', 'aria-disabled']
    };
  }

  /**
   * Helper: Get role for component
   */
  getRole(data) {
    const typeRoles = {
      button: 'button',
      input: 'textbox',
      navigation: 'navigation',
      modal: 'dialog',
      alert: 'alert',
      list: 'list',
      form: 'form'
    };
    return typeRoles[data.type] || 'region';
  }

  /**
   * Helper: Utility functions
   */
  toKebabCase(str) {
    return str.replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase();
  }

  getLitType(type) {
    const typeMap = {
      string: 'String',
      number: 'Number',
      boolean: 'Boolean',
      array: 'Array',
      object: 'Object'
    };
    return typeMap[type] || 'String';
  }

  /**
   * Helper: Other methods (stubs for now)
   */
  generateStateInitialization(state) {
    return Object.entries(state)
      .map(([key, value]) => `    this.${key} = ${JSON.stringify(value)};`)
      .join('\n');
  }

  generateMethodBindings(data) {
    return '    // Bind methods';
  }

  generateProperties(props) {
    return Object.entries(props)
      .map(([key]) => `  get ${key}() { return this.getAttribute('${this.toKebabCase(key)}'); }
  set ${key}(value) { this.setAttribute('${this.toKebabCase(key)}', value); }`)
      .join('\n\n');
  }

  generateEventListeners(data) {
    return '    // Setup event listeners';
  }

  generateLitStyles(data, config) {
    return '    /* Component styles */';
  }

  generateLitTemplate(data, config) {
    return '      <div>${this.content}</div>';
  }

  /**
   * Optimization implementations
   */
  async optimizeShadowDOM(code, data, config) {
    return code;
  }

  async optimizeCustomElements(code, data, config) {
    return code;
  }

  async optimizeSlots(code, data, config) {
    return code;
  }

  async optimizeAccessibility(code, data, config) {
    return code;
  }

  async addARIASupport(code, data, config) {
    return code;
  }

  async addKeyboardSupport(code, data, config) {
    return code;
  }

  async addFocusManagement(code, data, config) {
    return code;
  }

  async addScreenReaderSupport(code, data, config) {
    return code;
  }

  /**
   * Static transform method for wrapper compatibility
   * Transforms design tokens into Web Components code
   */
  static async transform(tokens, options = {}) {
    const fs = require('fs');
    const path = require('path');

    const instance = new WebComponentsOptimizer();
    const files = [];
    const outputPath = options.outputPath || './output';

    // Create output directories
    const srcDir = path.join(outputPath, 'src');
    const tokensDir = path.join(srcDir, 'tokens');
    fs.mkdirSync(tokensDir, { recursive: true });

    // Generate CSS custom properties
    const cssVariables = instance.generateCSSVariables(tokens);
    const cssFile = path.join(tokensDir, 'variables.css');
    fs.writeFileSync(cssFile, cssVariables);
    files.push(cssFile);

    // Generate JavaScript token object
    const ext = options.typescript ? 'ts' : 'js';
    const jsTokens = instance.generateJSTokens(tokens, options);
    const jsFile = path.join(tokensDir, `tokens.${ext}`);
    fs.writeFileSync(jsFile, jsTokens);
    files.push(jsFile);

    // Generate token utilities
    const utilities = instance.generateTokenUtilities(tokens, options);
    const utilFile = path.join(tokensDir, `utils.${ext}`);
    fs.writeFileSync(utilFile, utilities);
    files.push(utilFile);

    // Generate index file
    const indexContent = instance.generateTokenIndex(options);
    const indexFile = path.join(tokensDir, `index.${ext}`);
    fs.writeFileSync(indexFile, indexContent);
    files.push(indexFile);

    return { files, framework: 'web-components' };
  }

  /**
   * Generate CSS custom properties from tokens
   */
  generateCSSVariables(tokens) {
    const lines = [];

    lines.push('/* Auto-generated CSS custom properties from design tokens */');
    lines.push(':root {');

    // Colors
    if (tokens.colors) {
      lines.push('  /* Colors */');
      Object.entries(tokens.colors).forEach(([key, value]) => {
        if (typeof value === 'object' && value !== null) {
          Object.entries(value).forEach(([subKey, subValue]) => {
            lines.push(`  --color-${this.toKebabCase(key)}-${this.toKebabCase(subKey)}: ${subValue};`);
          });
        } else {
          lines.push(`  --color-${this.toKebabCase(key)}: ${value};`);
        }
      });
      lines.push('');
    }

    // Typography
    if (tokens.typography) {
      lines.push('  /* Typography */');
      Object.entries(tokens.typography).forEach(([key, value]) => {
        if (value.fontSize) {
          lines.push(`  --font-size-${this.toKebabCase(key)}: ${value.fontSize};`);
        }
        if (value.fontWeight) {
          lines.push(`  --font-weight-${this.toKebabCase(key)}: ${value.fontWeight};`);
        }
        if (value.lineHeight) {
          lines.push(`  --line-height-${this.toKebabCase(key)}: ${value.lineHeight};`);
        }
      });
      lines.push('');
    }

    // Spacing
    if (tokens.spacing) {
      lines.push('  /* Spacing */');
      Object.entries(tokens.spacing).forEach(([key, value]) => {
        lines.push(`  --spacing-${this.toKebabCase(key)}: ${value};`);
      });
      lines.push('');
    }

    lines.push('}');

    return lines.join('\n');
  }

  /**
   * Generate JavaScript token object
   */
  generateJSTokens(tokens, options) {
    const lines = [];

    lines.push('// Auto-generated design tokens for Web Components');
    lines.push('');

    if (options.typescript) {
      lines.push('export interface DesignTokens {');
      lines.push('  colors: Record<string, string | Record<string, string>>;');
      lines.push('  typography: Record<string, { fontSize?: string; fontWeight?: string; lineHeight?: string }>;');
      lines.push('  spacing: Record<string, string>;');
      lines.push('}');
      lines.push('');
    }

    lines.push(`export const tokens${options.typescript ? ': DesignTokens' : ''} = ${JSON.stringify(tokens, null, 2)};`);
    lines.push('');
    lines.push('export default tokens;');

    return lines.join('\n');
  }

  /**
   * Generate token utilities
   */
  generateTokenUtilities(tokens, options) {
    const lines = [];

    lines.push('// Auto-generated token utilities for Web Components');
    lines.push("import { tokens } from './tokens';");
    lines.push('');

    lines.push('/**');
    lines.push(' * Get CSS variable reference');
    lines.push(' */');
    if (options.typescript) {
      lines.push('export function cssVar(name: string): string {');
    } else {
      lines.push('export function cssVar(name) {');
    }
    lines.push('  return `var(--${name})`;');
    lines.push('}');
    lines.push('');

    lines.push('/**');
    lines.push(' * Apply tokens to element as CSS custom properties');
    lines.push(' */');
    if (options.typescript) {
      lines.push('export function applyTokens(element: HTMLElement): void {');
    } else {
      lines.push('export function applyTokens(element) {');
    }
    lines.push('  const style = element.style;');
    lines.push('  ');
    lines.push('  if (tokens.colors) {');
    lines.push('    Object.entries(tokens.colors).forEach(([key, value]) => {');
    lines.push("      if (typeof value === 'object') {");
    lines.push('        Object.entries(value).forEach(([subKey, subValue]) => {');
    lines.push('          style.setProperty(`--color-${key}-${subKey}`, subValue);');
    lines.push('        });');
    lines.push('      } else {');
    lines.push('        style.setProperty(`--color-${key}`, value);');
    lines.push('      }');
    lines.push('    });');
    lines.push('  }');
    lines.push('}');
    lines.push('');

    lines.push('/**');
    lines.push(' * Get shared styles for Shadow DOM');
    lines.push(' */');
    if (options.typescript) {
      lines.push('export function getSharedStyles(): string {');
    } else {
      lines.push('export function getSharedStyles() {');
    }
    lines.push("  return `");
    lines.push('    :host {');
    lines.push('      /* Inherit CSS custom properties from root */');
    lines.push('    }');
    lines.push('  `;');
    lines.push('}');

    return lines.join('\n');
  }

  /**
   * Generate token index file
   */
  generateTokenIndex(options) {
    const lines = [];

    lines.push('// Auto-generated token index');
    lines.push("export * from './tokens';");
    lines.push("export * from './utils';");

    return lines.join('\n');
  }

  /**
   * Static optimize method for registry-based transformation
   * Accepts enriched input format: { raw, registry, options }
   * @param {Object} input - Enriched input with raw data, registry metadata, and options
   * @returns {Promise<Object>} Transformation result
   */
  static async optimize(input) {
    const { raw, registry, options = {} } = input;
    const instance = new WebComponentsOptimizer();
    const warnings = [];

    // Build component data from raw + registry
    const componentData = instance.buildComponentData(raw, registry);

    // Generate component with enriched data
    const config = {
      ...instance.config,
      shadowDOM: options.shadowDOM !== false,
      litElement: options.litElement || false,
      typescript: options.typescript !== false,
      accessibility: {
        ...instance.config.accessibility,
        wcag: options.wcag || 'AA',
        ...options.accessibility
      },
      ...options
    };

    let code;
    try {
      code = await instance.generateComponent(componentData, config);

      // Apply registry-aware optimizations
      if (registry.tokenDependencies) {
        code = instance.applyTokenDependencies(code, registry.tokenDependencies, config);
      }
      if (registry.interactiveStates) {
        code = instance.applyInteractiveStates(code, registry.interactiveStates, config);
      }
      if (registry.variants && registry.variants.length > 0) {
        code = instance.applyVariants(code, registry.variants, config);
      }
    } catch (error) {
      return { success: false, error: error.message, warnings };
    }

    // Generate story if requested
    let story = null;
    if (options.generateStory) {
      try {
        story = instance.generateStory(componentData, registry, config);
      } catch (error) {
        warnings.push(`Story generation failed: ${error.message}`);
      }
    }

    return {
      success: true,
      code,
      story,
      output: code, // Alias for compatibility
      warnings
    };
  }

  /**
   * Build component data from raw Figma data + registry metadata
   */
  buildComponentData(raw, registry) {
    const componentData = {
      name: registry.name || raw.name || 'Component',
      type: raw.type || 'container',
      props: this.extractProps(raw),
      state: this.extractState(raw),
      styles: this.extractStyles(raw),
      slots: this.extractSlots(raw),
      ariaLabel: raw.ariaLabel || registry.name,
      header: raw.header,
      footer: raw.footer,
      children: raw.children || []
    };

    return componentData;
  }

  /**
   * Extract props from raw data
   */
  extractProps(raw) {
    const props = {};
    if (raw.componentProperties) {
      Object.entries(raw.componentProperties).forEach(([key, value]) => {
        props[key] = {
          type: this.inferPropType(value),
          default: value.defaultValue || value.value,
          required: !value.defaultValue
        };
      });
    }
    return props;
  }

  /**
   * Extract state from raw data
   */
  extractState(raw) {
    const state = {};
    if (raw.state || raw.componentState) {
      const stateSource = raw.state || raw.componentState;
      Object.entries(stateSource).forEach(([key, value]) => {
        state[key] = typeof value === 'object' ? value : { default: value };
      });
    }
    return state;
  }

  /**
   * Extract styles from raw data
   */
  extractStyles(raw) {
    const styles = {};
    if (raw.fills && raw.fills.length > 0) {
      const fill = raw.fills[0];
      if (fill.color) {
        const { r, g, b, a = 1 } = fill.color;
        styles['background-color'] = `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${a})`;
      }
    }
    if (raw.cornerRadius) styles['border-radius'] = `${raw.cornerRadius}px`;
    if (raw.paddingLeft) styles['padding-left'] = `${raw.paddingLeft}px`;
    if (raw.paddingRight) styles['padding-right'] = `${raw.paddingRight}px`;
    if (raw.paddingTop) styles['padding-top'] = `${raw.paddingTop}px`;
    if (raw.paddingBottom) styles['padding-bottom'] = `${raw.paddingBottom}px`;
    if (raw.itemSpacing) styles['gap'] = `${raw.itemSpacing}px`;
    return styles;
  }

  /**
   * Extract slots from raw data
   */
  extractSlots(raw) {
    const slots = [];
    if (raw.children) {
      raw.children.forEach(child => {
        if (child.type === 'SLOT' || child.name?.startsWith('slot:')) {
          slots.push({
            name: child.name?.replace('slot:', '') || 'default',
            fallback: child.fallback || ''
          });
        }
      });
    }
    return slots.length > 0 ? slots : null;
  }

  /**
   * Infer prop type from value
   */
  inferPropType(value) {
    if (value.type === 'BOOLEAN') return 'boolean';
    if (value.type === 'VARIANT') return 'string';
    if (value.type === 'TEXT') return 'string';
    if (value.type === 'INSTANCE_SWAP') return 'string';
    if (typeof value.value === 'number') return 'number';
    if (typeof value.value === 'boolean') return 'boolean';
    return 'string';
  }

  /**
   * Apply token dependencies to generated code
   */
  applyTokenDependencies(code, tokenDependencies, config) {
    let updatedCode = code;

    // Add CSS custom property imports
    const tokenImports = [];
    Object.entries(tokenDependencies).forEach(([category, tokens]) => {
      tokens.forEach(token => {
        tokenImports.push(`--${category}-${this.toKebabCase(token)}`);
      });
    });

    if (tokenImports.length > 0) {
      // Inject token usage comment
      const tokenComment = `/* Token dependencies: ${tokenImports.join(', ')} */`;
      updatedCode = updatedCode.replace(
        ':host {',
        `:host {\n        ${tokenComment}`
      );
    }

    return updatedCode;
  }

  /**
   * Apply interactive states to generated code
   */
  applyInteractiveStates(code, interactiveStates, config) {
    let updatedCode = code;

    const stateStyles = [];

    if (interactiveStates.hover) {
      stateStyles.push(`
      :host(:hover) {
        /* Hover state */
        opacity: 0.9;
        cursor: pointer;
      }`);
    }

    if (interactiveStates.focus) {
      stateStyles.push(`
      :host(:focus), :host(:focus-visible) {
        /* Focus state */
        outline: var(--focus-outline);
        outline-offset: 2px;
      }`);
    }

    if (interactiveStates.active) {
      stateStyles.push(`
      :host(:active) {
        /* Active state */
        transform: scale(0.98);
      }`);
    }

    if (interactiveStates.disabled) {
      stateStyles.push(`
      :host([disabled]) {
        /* Disabled state */
        opacity: 0.5;
        pointer-events: none;
        cursor: not-allowed;
      }`);
    }

    if (stateStyles.length > 0) {
      updatedCode = updatedCode.replace(
        '    `;',
        `${stateStyles.join('\n')}\n    \`;`
      );
    }

    return updatedCode;
  }

  /**
   * Apply variants to generated code
   */
  applyVariants(code, variants, config) {
    let updatedCode = code;

    const variantStyles = variants.map(variant => {
      return `
      :host([variant="${variant.name}"]) {
        /* Variant: ${variant.name} */
        ${variant.styles ? Object.entries(variant.styles).map(([k, v]) => `${k}: ${v};`).join('\n        ') : '/* Custom styles */'}
      }`;
    }).join('\n');

    if (variantStyles) {
      updatedCode = updatedCode.replace(
        '    `;',
        `${variantStyles}\n    \`;`
      );
    }

    return updatedCode;
  }

  /**
   * Generate Storybook story for Web Component
   */
  generateStory(componentData, registry, config) {
    const { name } = componentData;
    const tagName = this.toKebabCase(name);
    const lines = [];

    lines.push(`// Auto-generated Storybook story for ${name}`);
    lines.push(`import './${name}';`);
    lines.push('');
    lines.push('export default {');
    lines.push(`  title: 'Components/${name}',`);
    lines.push(`  component: '${tagName}',`);
    lines.push('  argTypes: {');

    // Add prop controls
    if (componentData.props) {
      Object.entries(componentData.props).forEach(([key, prop]) => {
        const control = this.getStorybookControl(prop.type);
        lines.push(`    ${key}: { control: '${control}' },`);
      });
    }

    lines.push('  },');
    lines.push('};');
    lines.push('');

    // Default story
    lines.push(`export const Default = {`);
    lines.push(`  render: (args) => \`<${tagName}></${tagName}>\`,`);
    lines.push('};');

    // Variant stories
    if (registry.variants && registry.variants.length > 0) {
      registry.variants.forEach(variant => {
        const storyName = variant.name.charAt(0).toUpperCase() + variant.name.slice(1);
        lines.push('');
        lines.push(`export const ${storyName} = {`);
        lines.push(`  render: (args) => \`<${tagName} variant="${variant.name}"></${tagName}>\`,`);
        lines.push('};');
      });
    }

    return lines.join('\n');
  }

  /**
   * Get Storybook control type for prop type
   */
  getStorybookControl(type) {
    const controlMap = {
      'string': 'text',
      'number': 'number',
      'boolean': 'boolean',
      'array': 'object',
      'object': 'object'
    };
    return controlMap[type] || 'text';
  }
}

module.exports = WebComponentsOptimizer;