/**
 * SwiftUI Component Transformer
 *
 * Extends EnhancedComponentTransformer for SwiftUI/Swift
 * Generates complete SwiftUI Views with full content from Figma
 */

const EnhancedComponentTransformer = require('./enhanced-component-transformer');

class SwiftUIComponentTransformer extends EnhancedComponentTransformer {
  constructor(projectPath, options = {}) {
    super(projectPath, 'swiftui', options);
    // SwiftUI uses native Xcode previews, not Storybook
    this.generateStorybook = false;
  }

  /**
   * Generate complete SwiftUI View code
   */
  generateCode(componentName, extractedContent, dependencies) {
    const pascalName = this.toPascalCase(componentName);

    const imports = this.generateImports(dependencies);
    const structDeclaration = this.generateStructDeclaration(pascalName, extractedContent);
    const bodyProperty = this.generateBodyProperty(extractedContent);
    const preview = this.generatePreview(pascalName, extractedContent);

    return `/**
 * ${pascalName} View
 * Generated from Figma Design System with full content extraction
 * Extracted: ${new Date().toISOString()}
 */

import SwiftUI
${imports}

${structDeclaration}
${bodyProperty}
}

${preview}
`;
  }

  /**
   * Generate SwiftUI struct declaration
   */
  generateStructDeclaration(componentName, extractedContent) {
    const properties = this.generateProperties(extractedContent);
    const initializer = this.generateInitializer(componentName, extractedContent);

    return `struct ${componentName}: View {
${properties}

${initializer}`;
  }

  /**
   * Generate properties from variants
   */
  generateProperties(extractedContent) {
    const properties = [];

    // Add variant properties from Figma
    if (extractedContent.variants) {
      for (const [key, value] of Object.entries(extractedContent.variants)) {
        const propName = this.toCamelCase(key);
        properties.push(`    var ${propName}: String`);
      }
    }

    return properties.length > 0 ? properties.join('\n') : '    // No properties';
  }

  /**
   * Generate initializer with default values
   */
  generateInitializer(componentName, extractedContent) {
    const params = [];
    const assignments = [];

    // Add variant parameters
    if (extractedContent.variants) {
      for (const [key, value] of Object.entries(extractedContent.variants)) {
        const propName = this.toCamelCase(key);
        params.push(`${propName}: String = "${value}"`);
        assignments.push(`        self.${propName} = ${propName}`);
      }
    }

    const paramsStr = params.length > 0 ? '\n        ' + params.join(',\n        ') + '\n    ' : '';
    const assignmentsStr = assignments.length > 0 ? '\n' + assignments.join('\n') + '\n    ' : '';

    return `    init(${paramsStr}) {${assignmentsStr}}`;
  }

  /**
   * Generate body property
   */
  generateBodyProperty(extractedContent) {
    const structure = this.generateStructure(extractedContent, 2);

    return `
    var body: some View {
${structure}
    }`;
  }

  /**
   * Generate SwiftUI view structure from extracted content tree
   */
  generateStructure(node, indent = 0) {
    const indentStr = '        ' + '    '.repeat(Math.max(0, indent - 2));

    // Handle text nodes
    if (node.content && node.content.type === 'text') {
      const text = node.content.value;
      return `${indentStr}Text("${text}")`;
    }

    // Handle nested component instances (resolved)
    if (node.nestedComponent && node.nestedComponent.resolved) {
      const comp = node.nestedComponent;
      const componentName = this.toPascalCase(comp.name.replace(/\s+/g, ''));
      const props = this._extractComponentProps(node);
      const propsStr = props.length > 0 ? '\n' + props.map(p => `${indentStr}    ${p}`).join('\n') + '\n' + indentStr : '';

      return `${indentStr}${componentName}(${propsStr})`;
    }

    // Handle containers with children
    if (node.children && node.children.length > 0) {
      const childStructures = node.children
        .map(child => this.generateStructure(child, indent + 1))
        .filter(s => s.trim().length > 0);

      if (childStructures.length > 0) {
        const styles = this.generateViewModifiers(node);
        const stack = node.styles?.layout?.mode === 'HORIZONTAL' ? 'HStack' : 'VStack';
        const alignment = this.getStackAlignment(node.styles?.layout);
        const spacing = this.getStackSpacing(node.styles?.layout);

        return `${indentStr}${stack}(alignment: ${alignment}, spacing: ${spacing}) {
${childStructures.join('\n')}
${indentStr}}${styles}`;
      }
    }

    // Handle unresolved nested components
    if (node.nestedComponent && !node.nestedComponent.resolved) {
      return `${indentStr}// TODO: Transform component '${node.nestedComponent.name}' first
${indentStr}Text("${node.nestedComponent.name}")`;
    }

    return `${indentStr}EmptyView()`;
  }

  /**
   * Get stack alignment for SwiftUI
   */
  getStackAlignment(layout) {
    if (!layout || !layout.counterAxisAlignItems) return '.center';

    const alignMap = {
      'MIN': '.leading',
      'CENTER': '.center',
      'MAX': '.trailing',
      'BASELINE': '.firstTextBaseline'
    };

    return alignMap[layout.counterAxisAlignItems] || '.center';
  }

  /**
   * Get stack spacing for SwiftUI
   */
  getStackSpacing(layout) {
    if (!layout || !layout.itemSpacing) return '8';
    return layout.itemSpacing.toString();
  }

  /**
   * Generate view modifiers from styles
   */
  generateViewModifiers(node) {
    const styles = node.styles;
    if (!styles) return '';

    const modifiers = [];

    // Padding
    if (styles.layout?.padding) {
      const { top, right, bottom, left } = styles.layout.padding;
      if (top || right || bottom || left) {
        modifiers.push(`\n        .padding(EdgeInsets(top: ${top}, leading: ${left}, bottom: ${bottom}, trailing: ${right}))`);
      }
    }

    // Background color
    if (styles.fills && styles.fills.length > 0) {
      const solidFill = styles.fills.find(fill => fill.type === 'SOLID');
      if (solidFill && solidFill.color) {
        const color = this.convertToSwiftUIColor(solidFill.color);
        modifiers.push(`\n        .background(${color})`);
      }
    }

    // Corner radius
    if (styles.borderRadius !== undefined) {
      modifiers.push(`\n        .cornerRadius(${styles.borderRadius})`);
    }

    // Border
    if (styles.strokes && styles.strokes.length > 0) {
      const stroke = styles.strokes[0];
      if (stroke.color) {
        const color = this.convertToSwiftUIColor(stroke.color);
        const weight = styles.strokeWeight || 1;
        modifiers.push(`\n        .overlay(RoundedRectangle(cornerRadius: ${styles.borderRadius || 0}).stroke(${color}, lineWidth: ${weight}))`);
      }
    }

    // Opacity
    if (styles.opacity !== undefined && styles.opacity !== 1) {
      modifiers.push(`\n        .opacity(${styles.opacity})`);
    }

    // Shadow
    if (styles.effects && styles.effects.length > 0) {
      const shadow = styles.effects.find(effect => effect.type === 'DROP_SHADOW');
      if (shadow) {
        const color = this.convertToSwiftUIColor(shadow.color);
        const radius = shadow.radius || 0;
        const x = shadow.offset?.x || 0;
        const y = shadow.offset?.y || 0;
        modifiers.push(`\n        .shadow(color: ${color}, radius: ${radius}, x: ${x}, y: ${y})`);
      }
    }

    return modifiers.join('');
  }

  /**
   * Convert color string to SwiftUI Color
   */
  convertToSwiftUIColor(colorStr) {
    // Handle hex colors
    if (colorStr.startsWith('#')) {
      return `Color(hex: "${colorStr}")`;
    }

    // Handle rgb colors
    const match = colorStr.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
    if (match) {
      const r = parseInt(match[1]) / 255;
      const g = parseInt(match[2]) / 255;
      const b = parseInt(match[3]) / 255;
      return `Color(red: ${r.toFixed(3)}, green: ${g.toFixed(3)}, blue: ${b.toFixed(3)})`;
    }

    return 'Color.black';
  }

  /**
   * Extract props for component instance (SwiftUI parameter syntax)
   */
  _extractComponentProps(node) {
    const props = [];

    // Extract variant props
    if (node.variants) {
      for (const [key, value] of Object.entries(node.variants)) {
        const propName = this.toCamelCase(key);
        props.push(`${propName}: "${value}"`);
      }
    }

    return props;
  }

  /**
   * Generate preview provider
   */
  generatePreview(componentName, extractedContent) {
    // Extract default prop values
    const defaultProps = [];
    if (extractedContent.variants) {
      for (const [key, value] of Object.entries(extractedContent.variants)) {
        const propName = this.toCamelCase(key);
        defaultProps.push(`${propName}: "${value}"`);
      }
    }

    const propsStr = defaultProps.length > 0 ? '\n            ' + defaultProps.join(',\n            ') + '\n        ' : '';

    return `struct ${componentName}_Previews: PreviewProvider {
    static var previews: some View {
        ${componentName}(${propsStr})
    }
}`;
  }

  /**
   * Generate import statement for SwiftUI
   */
  generateImport(componentName, importPath) {
    // SwiftUI doesn't use explicit imports for local files
    // They're automatically available in the same module
    return `// ${componentName} available in module`;
  }

  /**
   * Get file extension
   */
  getFileExtension() {
    return '.swift';
  }
}

module.exports = SwiftUIComponentTransformer;
