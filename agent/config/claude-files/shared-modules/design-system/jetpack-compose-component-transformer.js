/**
 * Jetpack Compose Component Transformer
 *
 * Extends EnhancedComponentTransformer for Jetpack Compose/Kotlin
 * Generates complete Composable functions with full content from Figma
 */

const EnhancedComponentTransformer = require('./enhanced-component-transformer');

class JetpackComposeComponentTransformer extends EnhancedComponentTransformer {
  constructor(projectPath, options = {}) {
    super(projectPath, 'jetpack-compose', options);
    // Jetpack Compose uses native @Preview, not Storybook
    this.generateStorybook = false;
  }

  /**
   * Generate complete Jetpack Compose code
   */
  generateCode(componentName, extractedContent, dependencies) {
    const pascalName = this.toPascalCase(componentName);

    const imports = this.generateImports(dependencies);
    const composable = this.generateComposable(pascalName, extractedContent);
    const preview = this.generatePreview(pascalName, extractedContent);

    return `/**
 * ${pascalName} Composable
 * Generated from Figma Design System with full content extraction
 * Extracted: ${new Date().toISOString()}
 */

package com.example.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
${imports}

${composable}

${preview}
`;
  }

  /**
   * Generate @Composable function
   */
  generateComposable(componentName, extractedContent) {
    const parameters = this.generateParameters(extractedContent);
    const structure = this.generateStructure(extractedContent, 1);

    return `@Composable
fun ${componentName}(
${parameters}
    modifier: Modifier = Modifier
) {
${structure}
}`;
  }

  /**
   * Generate function parameters from variants
   */
  generateParameters(extractedContent) {
    const params = [];

    // Add variant parameters from Figma
    if (extractedContent.variants) {
      for (const [key, value] of Object.entries(extractedContent.variants)) {
        const propName = this.toCamelCase(key);
        params.push(`    ${propName}: String = "${value}"`);
      }
    }

    return params.length > 0 ? params.join(',\n') + ',\n' : '';
  }

  /**
   * Generate Jetpack Compose structure from extracted content tree
   */
  generateStructure(node, indent = 0) {
    const indentStr = '    '.repeat(indent);

    // Handle text nodes
    if (node.content && node.content.type === 'text') {
      const text = node.content.value;
      return `${indentStr}Text(text = "${text}")`;
    }

    // Handle nested component instances (resolved)
    if (node.nestedComponent && node.nestedComponent.resolved) {
      const comp = node.nestedComponent;
      const componentName = this.toPascalCase(comp.name.replace(/\s+/g, ''));
      const props = this._extractComponentProps(node);
      const propsStr = props.length > 0 ? '\n' + props.map(p => `${indentStr}    ${p}`).join(',\n') + ',\n' : '';

      return `${indentStr}${componentName}(${propsStr}${indentStr})`;
    }

    // Handle containers with children
    if (node.children && node.children.length > 0) {
      const childStructures = node.children
        .map(child => this.generateStructure(child, indent + 1))
        .filter(s => s.trim().length > 0);

      if (childStructures.length > 0) {
        const layout = node.styles?.layout;
        const container = layout?.mode === 'HORIZONTAL' ? 'Row' : 'Column';
        const modifiers = this.generateModifiers(node.styles, indent + 1);
        const arrangement = this.getArrangement(layout);
        const alignment = this.getAlignment(layout, container);

        return `${indentStr}${container}(
${indentStr}    modifier = modifier${modifiers},
${indentStr}    horizontalArrangement = ${arrangement},
${indentStr}    verticalAlignment = ${alignment}
${indentStr}) {
${childStructures.join('\n')}
${indentStr}}`;
      }
    }

    // Handle unresolved nested components
    if (node.nestedComponent && !node.nestedComponent.resolved) {
      return `${indentStr}// TODO: Transform component '${node.nestedComponent.name}' first
${indentStr}Text(text = "${node.nestedComponent.name}")`;
    }

    return `${indentStr}Box {}`;
  }

  /**
   * Get arrangement for Row/Column
   */
  getArrangement(layout) {
    if (!layout || !layout.primaryAxisAlignItems) return 'Arrangement.Start';

    const arrangementMap = {
      'MIN': 'Arrangement.Start',
      'CENTER': 'Arrangement.Center',
      'MAX': 'Arrangement.End',
      'SPACE_BETWEEN': 'Arrangement.SpaceBetween'
    };

    return arrangementMap[layout.primaryAxisAlignItems] || 'Arrangement.Start';
  }

  /**
   * Get alignment for Row/Column
   */
  getAlignment(layout, container) {
    if (!layout || !layout.counterAxisAlignItems) {
      return container === 'Row' ? 'Alignment.CenterVertically' : 'Alignment.CenterHorizontally';
    }

    const alignMap = {
      'MIN': container === 'Row' ? 'Alignment.Top' : 'Alignment.Start',
      'CENTER': container === 'Row' ? 'Alignment.CenterVertically' : 'Alignment.CenterHorizontally',
      'MAX': container === 'Row' ? 'Alignment.Bottom' : 'Alignment.End',
      'BASELINE': 'Alignment.CenterVertically'
    };

    return alignMap[layout.counterAxisAlignItems] || (container === 'Row' ? 'Alignment.CenterVertically' : 'Alignment.CenterHorizontally');
  }

  /**
   * Generate Modifier chain from styles
   */
  generateModifiers(styles, indent = 1) {
    if (!styles) return '';

    const modifiers = [];
    const indentStr = '\n' + '    '.repeat(indent);

    // Padding
    if (styles.layout?.padding) {
      const { top, right, bottom, left } = styles.layout.padding;
      if (top || right || bottom || left) {
        modifiers.push(`${indentStr}.padding(start = ${left}.dp, top = ${top}.dp, end = ${right}.dp, bottom = ${bottom}.dp)`);
      }
    }

    // Background color
    if (styles.fills && styles.fills.length > 0) {
      const solidFill = styles.fills.find(fill => fill.type === 'SOLID');
      if (solidFill && solidFill.color) {
        const color = this.convertToComposeColor(solidFill.color);
        modifiers.push(`${indentStr}.background(${color})`);
      }
    }

    // Border radius
    if (styles.borderRadius !== undefined) {
      const radius = styles.borderRadius;
      modifiers.push(`${indentStr}.clip(RoundedCornerShape(${radius}.dp))`);
    }

    // Border
    if (styles.strokes && styles.strokes.length > 0) {
      const stroke = styles.strokes[0];
      if (stroke.color) {
        const color = this.convertToComposeColor(stroke.color);
        const weight = styles.strokeWeight || 1;
        const radius = styles.borderRadius || 0;
        modifiers.push(`${indentStr}.border(${weight}.dp, ${color}, RoundedCornerShape(${radius}.dp))`);
      }
    }

    // Shadow
    if (styles.effects && styles.effects.length > 0) {
      const shadow = styles.effects.find(effect => effect.type === 'DROP_SHADOW');
      if (shadow) {
        const elevation = shadow.radius || 4;
        modifiers.push(`${indentStr}.shadow(${elevation}.dp)`);
      }
    }

    // Opacity
    if (styles.opacity !== undefined && styles.opacity !== 1) {
      modifiers.push(`${indentStr}.alpha(${styles.opacity}f)`);
    }

    return modifiers.join('');
  }

  /**
   * Convert color string to Jetpack Compose Color
   */
  convertToComposeColor(colorStr) {
    // Handle hex colors
    if (colorStr.startsWith('#')) {
      const hex = colorStr.substring(1);
      return `Color(0xFF${hex})`;
    }

    // Handle rgb colors
    const match = colorStr.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
    if (match) {
      const r = parseInt(match[1]).toString(16).padStart(2, '0');
      const g = parseInt(match[2]).toString(16).padStart(2, '0');
      const b = parseInt(match[3]).toString(16).padStart(2, '0');
      return `Color(0xFF${r}${g}${b})`;
    }

    return 'Color.Black';
  }

  /**
   * Extract props for component instance (Kotlin named arguments)
   */
  _extractComponentProps(node) {
    const props = [];

    // Extract variant props
    if (node.variants) {
      for (const [key, value] of Object.entries(node.variants)) {
        const propName = this.toCamelCase(key);
        props.push(`${propName} = "${value}"`);
      }
    }

    return props;
  }

  /**
   * Generate @Preview function
   */
  generatePreview(componentName, extractedContent) {
    // Extract default prop values
    const defaultProps = [];
    if (extractedContent.variants) {
      for (const [key, value] of Object.entries(extractedContent.variants)) {
        const propName = this.toCamelCase(key);
        defaultProps.push(`${propName} = "${value}"`);
      }
    }

    const propsStr = defaultProps.length > 0 ? '\n        ' + defaultProps.join(',\n        ') + '\n    ' : '';

    return `@Preview(showBackground = true)
@Composable
fun ${componentName}Preview() {
    MaterialTheme {
        ${componentName}(${propsStr})
    }
}`;
  }

  /**
   * Generate import statement for Jetpack Compose
   */
  generateImport(componentName, importPath) {
    const pascalName = this.toPascalCase(componentName.replace(/\s+/g, ''));
    return `import com.example.components.${pascalName}`;
  }

  /**
   * Get file extension
   */
  getFileExtension() {
    return '.kt';
  }
}

module.exports = JetpackComposeComponentTransformer;
