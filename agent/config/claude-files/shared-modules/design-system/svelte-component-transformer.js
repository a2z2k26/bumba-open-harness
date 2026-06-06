/**
 * Svelte Component Transformer
 *
 * Extends EnhancedComponentTransformer for Svelte
 * Generates complete Svelte components with full content from Figma
 */

const EnhancedComponentTransformer = require('./enhanced-component-transformer');
const StorybookGenerator = require('./storybook-generator');

class SvelteComponentTransformer extends EnhancedComponentTransformer {
  constructor(projectPath, options = {}) {
    super(projectPath, 'svelte', options);
    this.useTypeScript = options.typescript !== false;
    this.generateStorybook = options.storybook !== false;
    this.storybookGenerator = new StorybookGenerator(projectPath);
  }

  /**
   * Generate complete Svelte component code
   */
  generateCode(componentName, extractedContent, dependencies) {
    const pascalName = this.toPascalCase(componentName);

    const script = this.generateScript(pascalName, extractedContent, dependencies);
    const template = this.generateTemplate(extractedContent);
    const styles = this.generateStyleSection(extractedContent.styles);

    return `<!--
 * ${pascalName} Component
 * Generated from Figma Design System with full content extraction
 * Extracted: ${new Date().toISOString()}
 -->

${script}

${template}

${styles}
`;
  }

  /**
   * Generate Svelte script section
   */
  generateScript(componentName, extractedContent, dependencies) {
    const lang = this.useTypeScript ? ' lang="ts"' : '';
    const imports = this.generateImports(dependencies);

    // Extract props from variants
    const props = this.generateProps(extractedContent);

    return `<script${lang}>
${imports}

  // Component props
${props}
</script>`;
  }

  /**
   * Generate props from variants
   */
  generateProps(extractedContent) {
    const props = [];

    // Add variant props from Figma
    if (extractedContent.variants) {
      for (const [key, value] of Object.entries(extractedContent.variants)) {
        const propName = this.toCamelCase(key);
        if (this.useTypeScript) {
          props.push(`  export let ${propName}: string = '${value}';`);
        } else {
          props.push(`  export let ${propName} = '${value}';`);
        }
      }
    }

    // Standard props
    if (this.useTypeScript) {
      props.push(`  export let className: string = '';`);
    } else {
      props.push(`  export let className = '';`);
    }

    return props.length > 0 ? props.join('\n') : '  // No props';
  }

  /**
   * Generate Svelte template/markup
   */
  generateTemplate(extractedContent) {
    const structure = this.generateStructure(extractedContent, 0);

    return `<div class="${this.toKebabCase(extractedContent.name || 'component')} {className}">
${structure}
</div>`;
  }

  /**
   * Generate Svelte style section
   */
  generateStyleSection(styles) {
    const cssRules = this.generateStyles(styles);

    return `<style>
${cssRules}
</style>`;
  }

  /**
   * Generate Svelte structure from extracted content tree
   */
  generateStructure(node, indent = 0) {
    const indentStr = '  ' + '  '.repeat(indent);

    // Handle text nodes
    if (node.content && node.content.type === 'text') {
      const text = node.content.value;
      return `${indentStr}<!-- ${node.name} -->
${indentStr}{${JSON.stringify(text)}}`;
    }

    // Handle nested component instances (resolved)
    if (node.nestedComponent && node.nestedComponent.resolved) {
      const comp = node.nestedComponent;
      const componentName = this.toPascalCase(comp.name.replace(/\s+/g, ''));
      const props = this._extractComponentProps(node);
      const propsStr = props.length > 0 ? ' ' + props.join(' ') : '';

      return `${indentStr}<!-- ${comp.name} component -->
${indentStr}<${componentName}${propsStr} />`;
    }

    // Handle containers with children
    if (node.children && node.children.length > 0) {
      const childStructures = node.children
        .map(child => this.generateStructure(child, indent + 1))
        .filter(s => s.trim().length > 0)
        .join('\n\n');

      if (childStructures) {
        return `${indentStr}<!-- ${node.name} - container -->
${indentStr}<div>
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
   * Extract props for component instance (Svelte binding syntax)
   */
  _extractComponentProps(node) {
    const props = [];

    // Extract variant props
    if (node.variants) {
      for (const [key, value] of Object.entries(node.variants)) {
        const propName = this.toCamelCase(key);
        props.push(`${propName}="${value}"`);
      }
    }

    return props;
  }

  /**
   * Generate CSS styles from extracted styles
   */
  generateStyles(styles) {
    if (!styles) return '  /* Add component styles */';

    const cssRules = [];

    // Layout styles
    if (styles.layout) {
      const layout = styles.layout;

      if (layout.mode === 'HORIZONTAL' || layout.mode === 'VERTICAL') {
        cssRules.push('  display: flex;');
        cssRules.push(`  flex-direction: ${layout.mode === 'HORIZONTAL' ? 'row' : 'column'};`);

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
          cssRules.push(`  justify-content: ${justifyMap[layout.primaryAxisAlignItems] || 'flex-start'};`);
        }
        if (layout.counterAxisAlignItems) {
          cssRules.push(`  align-items: ${alignMap[layout.counterAxisAlignItems] || 'flex-start'};`);
        }

        // Gap
        if (layout.itemSpacing) {
          cssRules.push(`  gap: ${layout.itemSpacing}px;`);
        }
      }

      // Padding
      if (layout.padding) {
        const { top, right, bottom, left } = layout.padding;
        if (top || right || bottom || left) {
          cssRules.push(`  padding: ${top}px ${right}px ${bottom}px ${left}px;`);
        }
      }
    }

    // Background fills
    if (styles.fills && styles.fills.length > 0) {
      const solidFill = styles.fills.find(fill => fill.type === 'SOLID');
      if (solidFill && solidFill.color) {
        cssRules.push(`  background: ${solidFill.color};`);
      }
    }

    // Border
    if (styles.strokes && styles.strokes.length > 0) {
      const stroke = styles.strokes[0];
      if (stroke.color) {
        const weight = styles.strokeWeight || 1;
        cssRules.push(`  border: ${weight}px solid ${stroke.color};`);
      }
    }

    // Border radius
    if (styles.borderRadius !== undefined) {
      cssRules.push(`  border-radius: ${styles.borderRadius}px;`);
    }

    // Opacity
    if (styles.opacity !== undefined && styles.opacity !== 1) {
      cssRules.push(`  opacity: ${styles.opacity};`);
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
        cssRules.push(`  box-shadow: ${shadows.join(', ')};`);
      }
    }

    return cssRules.length > 0 ? cssRules.join('\n') : '  /* Add component styles */';
  }

  /**
   * Generate import statement for Svelte
   */
  generateImport(componentName, importPath) {
    const pascalName = this.toPascalCase(componentName.replace(/\s+/g, ''));
    return `  import ${pascalName} from '${importPath}.svelte';`;
  }

  /**
   * Get file extension
   */
  getFileExtension() {
    return '.svelte';
  }

  /**
   * Convert to kebab-case for Svelte
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

module.exports = SvelteComponentTransformer;
