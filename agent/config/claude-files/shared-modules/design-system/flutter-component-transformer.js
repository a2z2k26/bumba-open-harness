/**
 * Flutter Component Transformer
 *
 * Extends EnhancedComponentTransformer for Flutter/Dart
 * Generates complete Flutter widgets with full content from Figma
 */

const EnhancedComponentTransformer = require('./enhanced-component-transformer');

class FlutterComponentTransformer extends EnhancedComponentTransformer {
  constructor(projectPath, options = {}) {
    super(projectPath, 'flutter', options);
    // Flutter uses native widget previews, not Storybook
    this.generateStorybook = false;
  }

  /**
   * Generate complete Flutter widget code
   */
  generateCode(componentName, extractedContent, dependencies) {
    const pascalName = this.toPascalCase(componentName);

    const imports = this.generateImports(dependencies);
    const classDeclaration = this.generateClassDeclaration(pascalName, extractedContent);
    const buildMethod = this.generateBuildMethod(extractedContent);

    return `/**
 * ${pascalName} Widget
 * Generated from Figma Design System with full content extraction
 * Extracted: ${new DateTime.now().toIso8601String()}
 */

import 'package:flutter/material.dart';
${imports}

${classDeclaration}
  ${buildMethod}
}
`;
  }

  /**
   * Generate Flutter class declaration with constructor
   */
  generateClassDeclaration(componentName, extractedContent) {
    const properties = this.generateProperties(extractedContent);
    const constructor = this.generateConstructor(componentName, extractedContent);

    return `class ${componentName} extends StatelessWidget {
${properties}

${constructor}`;
  }

  /**
   * Generate widget properties from variants
   */
  generateProperties(extractedContent) {
    const properties = [];

    // Add variant properties from Figma
    if (extractedContent.variants) {
      for (const [key, value] of Object.entries(extractedContent.variants)) {
        const propName = this.toCamelCase(key);
        properties.push(`  final String ${propName};`);
      }
    }

    // Standard properties
    properties.push(`  final Key? key;`);

    return properties.length > 0 ? properties.join('\n') : '  // No properties';
  }

  /**
   * Generate constructor
   */
  generateConstructor(componentName, extractedContent) {
    const params = [];

    // Add variant parameters
    if (extractedContent.variants) {
      for (const [key, value] of Object.entries(extractedContent.variants)) {
        const propName = this.toCamelCase(key);
        params.push(`    this.${propName} = '${value}'`);
      }
    }

    const paramsStr = params.length > 0 ? ',\n' + params.join(',\n') + ',\n' : '';

    return `  const ${componentName}({
    super.key${paramsStr}
  });`;
  }

  /**
   * Generate build method
   */
  generateBuildMethod(extractedContent) {
    const structure = this.generateStructure(extractedContent, 2);

    return `@override
  Widget build(BuildContext context) {
    return ${structure};
  }`;
  }

  /**
   * Generate Flutter widget structure from extracted content tree
   */
  generateStructure(node, indent = 0) {
    const indentStr = '    ' + '  '.repeat(Math.max(0, indent - 2));

    // Handle text nodes
    if (node.content && node.content.type === 'text') {
      const text = node.content.value;
      return `Text(
${indentStr}  '${text}',
${indentStr})`;
    }

    // Handle nested component instances (resolved)
    if (node.nestedComponent && node.nestedComponent.resolved) {
      const comp = node.nestedComponent;
      const componentName = this.toPascalCase(comp.name.replace(/\s+/g, ''));
      const props = this._extractComponentProps(node);
      const propsStr = props.length > 0 ? '\n' + props.map(p => `${indentStr}  ${p}`).join(',\n') + ',\n' + indentStr : '';

      return `${componentName}(${propsStr})`;
    }

    // Handle containers with children
    if (node.children && node.children.length > 0) {
      const childStructures = node.children
        .map(child => this.generateStructure(child, indent + 1))
        .filter(s => s.trim().length > 0);

      if (childStructures.length > 0) {
        const styles = this.generateContainerStyles(node);
        const direction = node.styles?.layout?.mode === 'HORIZONTAL' ? 'Row' : 'Column';

        return `${direction}(
${styles}
${indentStr}  children: [
${childStructures.map(c => `${indentStr}    ${c}`).join(',\n')},
${indentStr}  ],
${indentStr})`;
      }
    }

    // Handle unresolved nested components
    if (node.nestedComponent && !node.nestedComponent.resolved) {
      return `// TODO: Transform component '${node.nestedComponent.name}' first
${indentStr}Container()`;
    }

    return 'Container()';
  }

  /**
   * Generate container styles for Flutter
   */
  generateContainerStyles(node) {
    const styles = node.styles;
    if (!styles) return '';

    const styleProps = [];
    const indentStr = '      ';

    // Main axis alignment
    if (styles.layout?.primaryAxisAlignItems) {
      const alignMap = {
        'MIN': 'MainAxisAlignment.start',
        'CENTER': 'MainAxisAlignment.center',
        'MAX': 'MainAxisAlignment.end',
        'SPACE_BETWEEN': 'MainAxisAlignment.spaceBetween'
      };
      styleProps.push(`mainAxisAlignment: ${alignMap[styles.layout.primaryAxisAlignItems] || 'MainAxisAlignment.start'}`);
    }

    // Cross axis alignment
    if (styles.layout?.counterAxisAlignItems) {
      const alignMap = {
        'MIN': 'CrossAxisAlignment.start',
        'CENTER': 'CrossAxisAlignment.center',
        'MAX': 'CrossAxisAlignment.end',
        'BASELINE': 'CrossAxisAlignment.baseline'
      };
      styleProps.push(`crossAxisAlignment: ${alignMap[styles.layout.counterAxisAlignItems] || 'CrossAxisAlignment.start'}`);
    }

    return styleProps.length > 0 ? indentStr + styleProps.join(',\n' + indentStr) + ',' : '';
  }

  /**
   * Extract props for component instance (Flutter named parameters)
   */
  _extractComponentProps(node) {
    const props = [];

    // Extract variant props
    if (node.variants) {
      for (const [key, value] of Object.entries(node.variants)) {
        const propName = this.toCamelCase(key);
        props.push(`${propName}: '${value}'`);
      }
    }

    return props;
  }

  /**
   * Generate styles from extracted styles (BoxDecoration, etc.)
   */
  generateStyles(styles) {
    if (!styles) return '';

    const decorationProps = [];

    // Background fills
    if (styles.fills && styles.fills.length > 0) {
      const solidFill = styles.fills.find(fill => fill.type === 'SOLID');
      if (solidFill && solidFill.color) {
        decorationProps.push(`color: Color(${this.convertColorToHex(solidFill.color)})`);
      }
    }

    // Border radius
    if (styles.borderRadius !== undefined) {
      decorationProps.push(`borderRadius: BorderRadius.circular(${styles.borderRadius})`);
    }

    // Border
    if (styles.strokes && styles.strokes.length > 0) {
      const stroke = styles.strokes[0];
      if (stroke.color) {
        const weight = styles.strokeWeight || 1;
        decorationProps.push(`border: Border.all(color: Color(${this.convertColorToHex(stroke.color)}), width: ${weight})`);
      }
    }

    // Effects (shadows)
    if (styles.effects && styles.effects.length > 0) {
      const shadows = styles.effects
        .filter(effect => effect.type === 'DROP_SHADOW')
        .map(effect => {
          return `BoxShadow(
            offset: Offset(${effect.offset.x}, ${effect.offset.y}),
            blurRadius: ${effect.radius},
            spreadRadius: ${effect.spread || 0},
            color: Color(${this.convertColorToHex(effect.color)}),
          )`;
        });

      if (shadows.length > 0) {
        decorationProps.push(`boxShadow: [\n        ${shadows.join(',\n        ')},\n      ]`);
      }
    }

    if (decorationProps.length > 0) {
      return `decoration: BoxDecoration(
      ${decorationProps.join(',\n      ')},
    )`;
    }

    return '';
  }

  /**
   * Convert color string to Flutter hex format
   */
  convertColorToHex(colorStr) {
    // Assuming color is in rgb(r, g, b) format
    const match = colorStr.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
    if (match) {
      const r = parseInt(match[1]).toString(16).padStart(2, '0');
      const g = parseInt(match[2]).toString(16).padStart(2, '0');
      const b = parseInt(match[3]).toString(16).padStart(2, '0');
      return `0xFF${r}${g}${b}`;
    }
    return '0xFF000000';
  }

  /**
   * Generate import statement for Flutter
   */
  generateImport(componentName, importPath) {
    // Convert component name to snake_case for Dart files
    const snakeName = this.toSnakeCase(componentName.replace(/\s+/g, '_'));
    return `import '${importPath}.dart';`;
  }

  /**
   * Get file extension
   */
  getFileExtension() {
    return '.dart';
  }

  /**
   * Convert to snake_case for Dart file names
   */
  toSnakeCase(str) {
    return str
      .replace(/([A-Z])/g, '_$1')
      .toLowerCase()
      .replace(/^_/, '')
      .replace(/[\s-]+/g, '_');
  }
}

module.exports = FlutterComponentTransformer;
