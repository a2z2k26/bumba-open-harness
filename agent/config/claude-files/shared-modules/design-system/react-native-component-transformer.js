/**
 * React Native Component Transformer
 *
 * Extends EnhancedComponentTransformer for React Native
 * Generates complete React Native components with full content from Figma
 */

const EnhancedComponentTransformer = require('./enhanced-component-transformer');

class ReactNativeComponentTransformer extends EnhancedComponentTransformer {
  constructor(projectPath, options = {}) {
    super(projectPath, 'react-native', options);
    this.useTypeScript = options.typescript !== false;
    // React Native is preview-only (no Storybook)
    this.generateStorybook = false;
  }

  /**
   * Generate complete React Native component code
   */
  generateCode(componentName, extractedContent, dependencies) {
    const pascalName = this.toPascalCase(componentName);

    const imports = this.generateImports(dependencies);
    const propsInterface = this.generatePropsInterface(pascalName, extractedContent);
    const componentBody = this.generateComponentBody(pascalName, extractedContent);
    const styles = this.generateStyleSheet(extractedContent.styles);

    return `/**
 * ${pascalName} Component
 * Generated from Figma Design System with full content extraction
 * Extracted: ${new Date().toISOString()}
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
${imports}

${propsInterface}

${componentBody}

${styles}

export default ${pascalName};
`;
  }

  /**
   * Generate TypeScript props interface
   */
  generatePropsInterface(componentName, extractedContent) {
    if (!this.useTypeScript) return '';

    const props = [];

    // Add variant props from Figma
    if (extractedContent.variants) {
      for (const [key, value] of Object.entries(extractedContent.variants)) {
        const propName = this.toCamelCase(key);
        props.push(`  ${propName}?: string;`);
      }
    }

    // Standard props
    props.push(`  style?: any;`);
    props.push(`  children?: React.ReactNode;`);

    return `export interface ${componentName}Props {
${props.join('\n')}
}`;
  }

  /**
   * Generate component body
   */
  generateComponentBody(componentName, extractedContent) {
    const propsType = this.useTypeScript ? `React.FC<${componentName}Props>` : 'React.FC';

    // Extract default props from variants
    const defaultProps = [];
    if (extractedContent.variants) {
      for (const [key, value] of Object.entries(extractedContent.variants)) {
        const propName = this.toCamelCase(key);
        defaultProps.push(`${propName} = '${value}'`);
      }
    }

    const propsDestructure = defaultProps.length > 0
      ? `{ ${defaultProps.join(', ')}, style, children }`
      : `{ style, children }`;

    const structure = this.generateStructure(extractedContent, 2);

    return `/**
 * ${componentName} component
 */
export const ${componentName}: ${propsType} = (${propsDestructure}) => {
  return (
    <View style={[styles.container, style]}>
${structure}
    </View>
  );
};`;
  }

  /**
   * Generate React Native structure from extracted content tree
   */
  generateStructure(node, indent = 0) {
    const indentStr = '      ' + '  '.repeat(Math.max(0, indent - 2));

    // Handle text nodes
    if (node.content && node.content.type === 'text') {
      const text = node.content.value;
      return `${indentStr}<Text style={styles.text}>${text}</Text>`;
    }

    // Handle nested component instances (resolved)
    if (node.nestedComponent && node.nestedComponent.resolved) {
      const comp = node.nestedComponent;
      const componentName = this.toPascalCase(comp.name.replace(/\s+/g, ''));
      const props = this._extractComponentProps(node);
      const propsStr = props.length > 0 ? ' ' + props.join(' ') : '';

      return `${indentStr}<${componentName}${propsStr} />`;
    }

    // Handle containers with children
    if (node.children && node.children.length > 0) {
      const childStructures = node.children
        .map(child => this.generateStructure(child, indent + 1))
        .filter(s => s.trim().length > 0)
        .join('\n');

      if (childStructures) {
        return `${indentStr}<View style={styles.row}>
${childStructures}
${indentStr}</View>`;
      }
    }

    // Handle unresolved nested components
    if (node.nestedComponent && !node.nestedComponent.resolved) {
      return `${indentStr}{/* TODO: Transform component '${node.nestedComponent.name}' first */}`;
    }

    return '';
  }

  /**
   * Extract props for component instance
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
   * Generate StyleSheet from extracted styles
   */
  generateStyleSheet(styles) {
    if (!styles) {
      return `const styles = StyleSheet.create({
  container: {
    // Add component styles
  },
  text: {
    // Add text styles
  },
  row: {
    // Add row styles
  },
});`;
    }

    const containerStyles = this.generateContainerStyle(styles);
    const textStyles = this.generateTextStyle(styles);
    const rowStyles = this.generateRowStyle(styles);

    return `const styles = StyleSheet.create({
  container: {
${containerStyles}
  },
  text: {
${textStyles}
  },
  row: {
${rowStyles}
  },
});`;
  }

  /**
   * Generate container styles
   */
  generateContainerStyle(styles) {
    const styleProps = [];

    // Layout
    if (styles.layout) {
      const layout = styles.layout;

      if (layout.mode === 'HORIZONTAL' || layout.mode === 'VERTICAL') {
        styleProps.push(`    flexDirection: '${layout.mode === 'HORIZONTAL' ? 'row' : 'column'}'`);

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
          styleProps.push(`    justifyContent: '${justifyMap[layout.primaryAxisAlignItems] || 'flex-start'}'`);
        }
        if (layout.counterAxisAlignItems) {
          styleProps.push(`    alignItems: '${alignMap[layout.counterAxisAlignItems] || 'flex-start'}'`);
        }

        // Gap (use margin as RN doesn't support gap)
        if (layout.itemSpacing) {
          styleProps.push(`    gap: ${layout.itemSpacing}`);
        }
      }

      // Padding
      if (layout.padding) {
        const { top, right, bottom, left } = layout.padding;
        if (top) styleProps.push(`    paddingTop: ${top}`);
        if (right) styleProps.push(`    paddingRight: ${right}`);
        if (bottom) styleProps.push(`    paddingBottom: ${bottom}`);
        if (left) styleProps.push(`    paddingLeft: ${left}`);
      }
    }

    // Background fills
    if (styles.fills && styles.fills.length > 0) {
      const solidFill = styles.fills.find(fill => fill.type === 'SOLID');
      if (solidFill && solidFill.color) {
        styleProps.push(`    backgroundColor: '${solidFill.color}'`);
      }
    }

    // Border
    if (styles.strokes && styles.strokes.length > 0) {
      const stroke = styles.strokes[0];
      if (stroke.color) {
        const weight = styles.strokeWeight || 1;
        styleProps.push(`    borderWidth: ${weight}`);
        styleProps.push(`    borderColor: '${stroke.color}'`);
      }
    }

    // Border radius
    if (styles.borderRadius !== undefined) {
      styleProps.push(`    borderRadius: ${styles.borderRadius}`);
    }

    // Opacity
    if (styles.opacity !== undefined && styles.opacity !== 1) {
      styleProps.push(`    opacity: ${styles.opacity}`);
    }

    return styleProps.length > 0 ? styleProps.join(',\n') : '    // Add container styles';
  }

  /**
   * Generate text styles
   */
  generateTextStyle(styles) {
    return '    fontSize: 14,\n    color: \'#000000\'';
  }

  /**
   * Generate row styles
   */
  generateRowStyle(styles) {
    return '    flexDirection: \'row\',\n    alignItems: \'center\'';
  }

  /**
   * Generate import statement for React Native
   */
  generateImport(componentName, importPath) {
    const pascalName = this.toPascalCase(componentName.replace(/\s+/g, ''));
    return `import ${pascalName} from '${importPath}';`;
  }

  /**
   * Get file extension
   */
  getFileExtension() {
    return this.useTypeScript ? '.tsx' : '.jsx';
  }
}

module.exports = ReactNativeComponentTransformer;
