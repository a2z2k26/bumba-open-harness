/**
 * Web Components Component Transformer
 *
 * Extends EnhancedComponentTransformer for Web Components (Custom Elements)
 * Generates complete Custom Elements with Shadow DOM and full content from Figma
 */

const EnhancedComponentTransformer = require('./enhanced-component-transformer');
const StorybookGenerator = require('./storybook-generator');

class WebComponentsComponentTransformer extends EnhancedComponentTransformer {
  constructor(projectPath, options = {}) {
    super(projectPath, 'web-components', options);
    this.useTypeScript = options.typescript !== false;
    this.generateStorybook = options.storybook !== false;
    this.storybookGenerator = new StorybookGenerator(projectPath);
  }

  /**
   * Generate complete Web Component code
   */
  generateCode(componentName, extractedContent, dependencies) {
    const pascalName = this.toPascalCase(componentName);
    const tagName = this.toKebabCase(componentName);

    const imports = this.generateImports(dependencies);
    const classDefinition = this.generateClassDefinition(pascalName, extractedContent);
    const registration = this.generateRegistration(pascalName, tagName);

    const extension = this.useTypeScript ? 'ts' : 'js';

    return `/**
 * ${pascalName} Web Component
 * Generated from Figma Design System with full content extraction
 * Extracted: ${new Date().toISOString()}
 *
 * Usage: <${tagName}></${tagName}>
 */

${imports}

${classDefinition}

${registration}

export default ${pascalName};
`;
  }

  /**
   * Generate Custom Element class definition
   */
  generateClassDefinition(componentName, extractedContent) {
    const typeAnnotation = this.useTypeScript ? ': string' : '';
    const properties = this.generateProperties(extractedContent);
    const observedAttributes = this.generateObservedAttributes(extractedContent);
    const constructor = this.generateConstructor(componentName);
    const connectedCallback = this.generateConnectedCallback(extractedContent);
    const attributeChangedCallback = this.generateAttributeChangedCallback(extractedContent);
    const renderMethod = this.generateRenderMethod(extractedContent);

    return `class ${componentName} extends HTMLElement {
${properties}

${observedAttributes}

${constructor}

${connectedCallback}

${attributeChangedCallback}

${renderMethod}
}`;
  }

  /**
   * Generate class properties from variants
   */
  generateProperties(extractedContent) {
    const props = [];

    // Add variant properties from Figma
    if (extractedContent.variants) {
      for (const [key, value] of Object.entries(extractedContent.variants)) {
        const propName = this.toCamelCase(key);
        if (this.useTypeScript) {
          props.push(`    private _${propName}: string = '${value}';`);
        } else {
          props.push(`    _${propName} = '${value}';`);
        }
      }
    }

    return props.length > 0 ? props.join('\n') : '    // No properties';
  }

  /**
   * Generate static observedAttributes
   */
  generateObservedAttributes(extractedContent) {
    const attrs = [];

    if (extractedContent.variants) {
      for (const key of Object.keys(extractedContent.variants)) {
        const attrName = this.toKebabCase(key);
        attrs.push(`'${attrName}'`);
      }
    }

    const attrsStr = attrs.length > 0 ? attrs.join(', ') : '';
    return `    static get observedAttributes()${this.useTypeScript ? ': string[]' : ''} {
        return [${attrsStr}];
    }`;
  }

  /**
   * Generate constructor
   */
  generateConstructor(componentName) {
    return `    constructor() {
        super();
        // Attach shadow DOM
        this.attachShadow({ mode: 'open' });
    }`;
  }

  /**
   * Generate connectedCallback
   */
  generateConnectedCallback(extractedContent) {
    // Generate getters/setters for properties
    const accessors = [];
    if (extractedContent.variants) {
      for (const [key, value] of Object.entries(extractedContent.variants)) {
        const propName = this.toCamelCase(key);
        const attrName = this.toKebabCase(key);

        accessors.push(`
        // ${propName} property
        Object.defineProperty(this, '${propName}', {
            get()${this.useTypeScript ? ': string' : ''} {
                return this._${propName};
            },
            set(value${this.useTypeScript ? ': string' : ''}) {
                this._${propName} = value;
                this.setAttribute('${attrName}', value);
            }
        });`);
      }
    }

    return `    connectedCallback()${this.useTypeScript ? ': void' : ''} {${accessors.join('')}

        this.render();
    }`;
  }

  /**
   * Generate attributeChangedCallback
   */
  generateAttributeChangedCallback(extractedContent) {
    const cases = [];

    if (extractedContent.variants) {
      for (const [key, value] of Object.entries(extractedContent.variants)) {
        const propName = this.toCamelCase(key);
        const attrName = this.toKebabCase(key);

        cases.push(`            case '${attrName}':
                this._${propName} = newValue || '${value}';
                break;`);
      }
    }

    const casesStr = cases.length > 0 ? cases.join('\n') : '            // No attributes';

    return `    attributeChangedCallback(name${this.useTypeScript ? ': string' : ''}, oldValue${this.useTypeScript ? ': string | null' : ''}, newValue${this.useTypeScript ? ': string | null' : ''})${this.useTypeScript ? ': void' : ''} {
        switch (name) {
${casesStr}
        }
        this.render();
    }`;
  }

  /**
   * Generate render method
   */
  generateRenderMethod(extractedContent) {
    const structure = this.generateStructure(extractedContent, 2);
    const styles = this.generateStyles(extractedContent.styles);

    return `    render()${this.useTypeScript ? ': void' : ''} {
        if (!this.shadowRoot) return;

        this.shadowRoot.innerHTML = \`
            <style>
${styles}
            </style>
            <div class="${this.toKebabCase(extractedContent.name || 'component')}">
${structure}
            </div>
        \`;
    }`;
  }

  /**
   * Generate HTML structure from extracted content tree
   */
  generateStructure(node, indent = 0) {
    const indentStr = '                ' + '    '.repeat(Math.max(0, indent - 2));

    // Handle text nodes
    if (node.content && node.content.type === 'text') {
      const text = node.content.value;
      return `${indentStr}<!-- ${node.name} -->
${indentStr}${text}`;
    }

    // Handle nested component instances (resolved)
    if (node.nestedComponent && node.nestedComponent.resolved) {
      const comp = node.nestedComponent;
      const tagName = this.toKebabCase(comp.name.replace(/\s+/g, '-'));
      const props = this._extractComponentProps(node);
      const propsStr = props.length > 0 ? ' ' + props.join(' ') : '';

      return `${indentStr}<!-- ${comp.name} component -->
${indentStr}<${tagName}${propsStr}></${tagName}>`;
    }

    // Handle containers with children
    if (node.children && node.children.length > 0) {
      const childStructures = node.children
        .map(child => this.generateStructure(child, indent + 1))
        .filter(s => s.trim().length > 0)
        .join('\n');

      if (childStructures) {
        return `${indentStr}<!-- ${node.name} - container -->
${indentStr}<div class="container">
${childStructures}
${indentStr}</div>`;
      }
    }

    // Handle unresolved nested components
    if (node.nestedComponent && !node.nestedComponent.resolved) {
      return `${indentStr}<!-- TODO: Transform component '${node.nestedComponent.name}' first -->`;
    }

    return '';
  }

  /**
   * Extract props for component instance (HTML attribute syntax)
   */
  _extractComponentProps(node) {
    const props = [];

    // Extract variant props
    if (node.variants) {
      for (const [key, value] of Object.entries(node.variants)) {
        const attrName = this.toKebabCase(key);
        props.push(`${attrName}="${value}"`);
      }
    }

    return props;
  }

  /**
   * Generate CSS styles from extracted styles
   */
  generateStyles(styles) {
    if (!styles) return '                /* Add component styles */';

    const cssRules = [];

    // Host styles
    cssRules.push('                :host {');
    cssRules.push('                    display: block;');
    cssRules.push('                }');
    cssRules.push('');

    // Container styles
    const containerStyles = [];

    // Layout
    if (styles.layout) {
      const layout = styles.layout;

      if (layout.mode === 'HORIZONTAL' || layout.mode === 'VERTICAL') {
        containerStyles.push('                    display: flex;');
        containerStyles.push(`                    flex-direction: ${layout.mode === 'HORIZONTAL' ? 'row' : 'column'};`);

        // Alignment
        const justifyMap = {
          'MIN': 'flex-start',
          'CENTER': 'center',
          'MAX': 'flex-end',
          'SPACE_BETWEEN': 'space-between'
        };
        const alignMap = {
          'MIN': 'flex-start',
          'CENTER': 'center',
          'MAX': 'flex-end',
          'BASELINE': 'baseline'
        };

        if (layout.primaryAxisAlignItems) {
          containerStyles.push(`                    justify-content: ${justifyMap[layout.primaryAxisAlignItems] || 'flex-start'};`);
        }
        if (layout.counterAxisAlignItems) {
          containerStyles.push(`                    align-items: ${alignMap[layout.counterAxisAlignItems] || 'flex-start'};`);
        }

        // Gap
        if (layout.itemSpacing) {
          containerStyles.push(`                    gap: ${layout.itemSpacing}px;`);
        }
      }

      // Padding
      if (layout.padding) {
        const { top, right, bottom, left } = layout.padding;
        if (top || right || bottom || left) {
          containerStyles.push(`                    padding: ${top}px ${right}px ${bottom}px ${left}px;`);
        }
      }
    }

    // Background fills
    if (styles.fills && styles.fills.length > 0) {
      const solidFill = styles.fills.find(fill => fill.type === 'SOLID');
      if (solidFill && solidFill.color) {
        containerStyles.push(`                    background: ${solidFill.color};`);
      }
    }

    // Border
    if (styles.strokes && styles.strokes.length > 0) {
      const stroke = styles.strokes[0];
      if (stroke.color) {
        const weight = styles.strokeWeight || 1;
        containerStyles.push(`                    border: ${weight}px solid ${stroke.color};`);
      }
    }

    // Border radius
    if (styles.borderRadius !== undefined) {
      containerStyles.push(`                    border-radius: ${styles.borderRadius}px;`);
    }

    // Opacity
    if (styles.opacity !== undefined && styles.opacity !== 1) {
      containerStyles.push(`                    opacity: ${styles.opacity};`);
    }

    // Effects (shadows)
    if (styles.effects && styles.effects.length > 0) {
      const shadows = styles.effects
        .filter(effect => effect.type === 'DROP_SHADOW')
        .map(effect => {
          const { offset, radius, spread, color } = effect;
          return `${offset.x}px ${offset.y}px ${radius}px ${spread || 0}px ${color}`;
        });

      if (shadows.length > 0) {
        containerStyles.push(`                    box-shadow: ${shadows.join(', ')};`);
      }
    }

    if (containerStyles.length > 0) {
      cssRules.push('                .container {');
      cssRules.push(...containerStyles);
      cssRules.push('                }');
    }

    return cssRules.join('\n');
  }

  /**
   * Generate component registration
   */
  generateRegistration(componentName, tagName) {
    return `// Register the custom element
if (!customElements.get('${tagName}')) {
    customElements.define('${tagName}', ${componentName});
}`;
  }

  /**
   * Generate import statement for Web Components
   */
  generateImport(componentName, importPath) {
    const pascalName = this.toPascalCase(componentName.replace(/\s+/g, ''));
    const extension = this.useTypeScript ? '.ts' : '.js';
    return `import ${pascalName} from '${importPath}${extension}';`;
  }

  /**
   * Get file extension
   */
  getFileExtension() {
    return this.useTypeScript ? '.ts' : '.js';
  }

  /**
   * Convert to kebab-case for custom element tags
   */
  toKebabCase(str) {
    return str
      .replace(/([a-z])([A-Z])/g, '$1-$2')
      .replace(/[\s_]+/g, '-')
      .toLowerCase();
  }

  /**
   * Override transform to add Storybook generation
   */
  async transform(componentJson, options = {}) {
    // Call parent transform
    const result = await super.transform(componentJson, options);

    // Generate Storybook story if enabled
    if (this.generateStorybook && result.success) {
      try {
        console.log(`  → Generating Storybook story...`);

        const storyResult = this.storybookGenerator.generateAndWrite(
          result.componentName,
          result.extractedContent,
          {
            category: options.storybookCategory || 'Components',
            includeVariants: true,
            includeControls: true
          }
        );

        console.log(`  ✓ Story created: ${storyResult.path}`);

        result.storyPath = storyResult.path;
      } catch (error) {
        console.warn(`  ⚠ Failed to generate story: ${error.message}`);
        // Don't fail the whole transform if story generation fails
      }
    }

    return result;
  }
}

module.exports = WebComponentsComponentTransformer;
