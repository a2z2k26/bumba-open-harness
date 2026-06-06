/**
 * Layout to Flutter/Dart Transformer
 *
 * Converts extracted Figma layout data into production-ready Flutter/Dart code.
 * Generates Flutter widgets with Column, Row, and proper spacing/padding.
 */

const fs = require('fs');
const path = require('path');

/**
 * Convert Figma auto-layout properties to Flutter widget properties
 */
function convertAutoLayoutToFlutter(layout) {
  const result = {
    widgetType: 'Column', // default
    mainAxisAlignment: 'MainAxisAlignment.start',
    crossAxisAlignment: 'CrossAxisAlignment.center',
    spacing: 0,
    padding: null
  };

  // Direction
  if (layout.layoutMode === 'VERTICAL') {
    result.widgetType = 'Column';
  } else if (layout.layoutMode === 'HORIZONTAL') {
    result.widgetType = 'Row';
  }

  // Primary axis alignment (mainAxisAlignment)
  const primaryAxisMap = {
    'MIN': 'MainAxisAlignment.start',
    'CENTER': 'MainAxisAlignment.center',
    'MAX': 'MainAxisAlignment.end',
    'SPACE_BETWEEN': 'MainAxisAlignment.spaceBetween'
  };
  if (layout.primaryAxisAlignItems && primaryAxisMap[layout.primaryAxisAlignItems]) {
    result.mainAxisAlignment = primaryAxisMap[layout.primaryAxisAlignItems];
  }

  // Counter axis alignment (crossAxisAlignment)
  const counterAxisMap = {
    'MIN': 'CrossAxisAlignment.start',
    'CENTER': 'CrossAxisAlignment.center',
    'MAX': 'CrossAxisAlignment.end',
    'STRETCH': 'CrossAxisAlignment.stretch'
  };
  if (layout.counterAxisAlignItems && counterAxisMap[layout.counterAxisAlignItems]) {
    result.crossAxisAlignment = counterAxisMap[layout.counterAxisAlignItems];
  }

  // Spacing (itemSpacing)
  if (layout.itemSpacing && layout.itemSpacing > 0) {
    result.spacing = layout.itemSpacing;
  }

  // Padding
  const pt = layout.paddingTop || 0;
  const pr = layout.paddingRight || 0;
  const pb = layout.paddingBottom || 0;
  const pl = layout.paddingLeft || 0;

  if (pt || pr || pb || pl) {
    // Check if uniform padding
    if (pt === pr && pr === pb && pb === pl) {
      result.padding = { type: 'uniform', value: pt };
    } else if (pt === pb && pl === pr) {
      result.padding = { type: 'symmetric', vertical: pt, horizontal: pl };
    } else {
      result.padding = { type: 'only', top: pt, right: pr, bottom: pb, left: pl };
    }
  }

  // Sizing
  if (layout.width) {
    result.width = layout.width;
  }
  if (layout.height) {
    result.height = layout.height;
  }

  return result;
}

/**
 * Generate EdgeInsets padding
 */
function generatePadding(padding) {
  if (!padding) return null;

  if (padding.type === 'uniform') {
    return `EdgeInsets.all(${padding.value})`;
  } else if (padding.type === 'symmetric') {
    return `EdgeInsets.symmetric(vertical: ${padding.vertical}, horizontal: ${padding.horizontal})`;
  } else if (padding.type === 'only') {
    const parts = [];
    if (padding.top > 0) parts.push(`top: ${padding.top}`);
    if (padding.right > 0) parts.push(`right: ${padding.right}`);
    if (padding.bottom > 0) parts.push(`bottom: ${padding.bottom}`);
    if (padding.left > 0) parts.push(`left: ${padding.left}`);
    return `EdgeInsets.only(${parts.join(', ')})`;
  }

  return null;
}

/**
 * Generate Flutter widget for a component reference
 */
function generateComponentFlutter(node, indent = '') {
  const name = node.componentRef?.name || node.name || 'Unknown';
  const componentName = toPascalCase(name);

  // Extract props if any
  const props = node.componentRef?.props || {};
  const propEntries = Object.entries(props);

  if (propEntries.length > 0) {
    const propsStr = propEntries.map(([key, value]) => {
      if (typeof value === 'string') {
        return `${key}: '${value}'`;
      } else if (typeof value === 'boolean') {
        return `${key}: ${value}`;
      } else {
        return `${key}: ${JSON.stringify(value)}`;
      }
    }).join(', ');
    return `${indent}${componentName}(${propsStr})`;
  }

  return `${indent}${componentName}()`;
}

/**
 * Generate SizedBox for spacing between items
 */
function generateSizedBox(spacing, isVertical, indent = '') {
  if (spacing <= 0) return null;

  if (isVertical) {
    return `${indent}SizedBox(height: ${spacing})`;
  } else {
    return `${indent}SizedBox(width: ${spacing})`;
  }
}

/**
 * Generate Flutter widget for a layout frame and its children
 */
function generateFrameFlutter(node, depth = 0) {
  const indent = '  '.repeat(depth + 2);
  const layout = convertAutoLayoutToFlutter(node);
  const hasChildren = node.children && node.children.length > 0;

  if (!hasChildren) {
    return `${indent}SizedBox()`;
  }

  const isVertical = layout.widgetType === 'Column';

  // Generate children with spacing
  const childWidgets = [];
  node.children.forEach((child, idx) => {
    let childWidget;

    if (child.type === 'INSTANCE' || child.componentRef) {
      childWidget = generateComponentFlutter(child, indent + '  ');
    } else if (child.type === 'FRAME' || child.children) {
      childWidget = generateFrameFlutter(child, depth + 1);
    } else if (child.type === 'TEXT') {
      const text = child.characters || child.name || '';
      childWidget = `${indent}  Text('${text.replace(/'/g, "\\'")}')`;
    } else {
      childWidget = `${indent}  // TODO: Handle ${child.type}`;
    }

    childWidgets.push(childWidget);

    // Add SizedBox for spacing between items (except after last item)
    if (layout.spacing > 0 && idx < node.children.length - 1) {
      const sizedBox = generateSizedBox(layout.spacing, isVertical, indent + '  ');
      if (sizedBox) childWidgets.push(sizedBox);
    }
  });

  const childrenContent = childWidgets.join(',\n');

  // Build widget
  const properties = [];

  if (layout.mainAxisAlignment !== 'MainAxisAlignment.start') {
    properties.push(`mainAxisAlignment: ${layout.mainAxisAlignment}`);
  }
  if (layout.crossAxisAlignment !== 'CrossAxisAlignment.center') {
    properties.push(`crossAxisAlignment: ${layout.crossAxisAlignment}`);
  }

  properties.push(`children: [\n${childrenContent}\n${indent}  ]`);

  let code = `${indent}${layout.widgetType}(\n${indent}  ${properties.join(',\n' + indent + '  ')}\n${indent})`;

  // Wrap in Padding if needed
  if (layout.padding) {
    const paddingStr = generatePadding(layout.padding);
    if (paddingStr) {
      code = `${indent}Padding(\n${indent}  padding: ${paddingStr},\n${indent}  child: ${code.trim()}\n${indent})`;
    }
  }

  // Wrap in SizedBox for fixed dimensions
  if (layout.width || layout.height) {
    const sizeProps = [];
    if (layout.width) sizeProps.push(`width: ${layout.width}`);
    if (layout.height) sizeProps.push(`height: ${layout.height}`);
    code = `${indent}SizedBox(\n${indent}  ${sizeProps.join(',\n' + indent + '  ')},\n${indent}  child: ${code.trim()}\n${indent})`;
  }

  return code;
}

/**
 * Extract unique component references from layout
 */
function extractComponentReferences(node, components = new Set()) {
  if (node.type === 'INSTANCE' || node.componentRef) {
    const name = node.componentRef?.name || node.name;
    if (name) {
      components.add(toPascalCase(name));
    }
  }

  if (node.children && Array.isArray(node.children)) {
    node.children.forEach(child => extractComponentReferences(child, components));
  }

  return Array.from(components);
}

/**
 * Convert string to PascalCase
 */
function toPascalCase(str) {
  return str
    .replace(/[-_\s/]+(.)?/g, (_, char) => char ? char.toUpperCase() : '')
    .replace(/^[a-z]/, char => char.toUpperCase());
}

/**
 * Generate complete Flutter widget from layout data
 */
function generateFlutter(layout, options = {}) {
  const layoutName = layout.name || 'UntitledLayout';
  const widgetName = toPascalCase(layoutName);

  // Extract component references
  const components = extractComponentReferences(layout);

  // Generate imports
  const componentImports = components.length > 0
    ? components.map(comp => `// import '${comp.toLowerCase()}.dart';`).join('\n')
    : '';

  // Generate Flutter body
  const bodyContent = generateFrameFlutter(layout, 0);

  const code = `/**
 * ${widgetName} Layout Widget
 * Generated from Figma layout extraction
 *
 * This widget uses transformed design system components.
 * Generated: ${new Date().toISOString()}
 */

import 'package:flutter/material.dart';
${componentImports ? '\n' + componentImports + '\n' : ''}
class ${widgetName} extends StatelessWidget {
  const ${widgetName}({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return ${bodyContent.trim()};
  }
}
`;

  return code;
}

/**
 * Transform layout data to Flutter and save artifacts
 */
async function transformLayoutToFlutter(layoutData, options = {}) {
  const {
    outputDir = '.design/extracted-code/flutter/layouts'
  } = options;

  const layoutName = layoutData.name || 'untitled';
  const widgetName = toPascalCase(layoutName);
  const fileName = widgetName.replace(/([A-Z])/g, '_$1').toLowerCase().slice(1);

  // Ensure directory exists
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  // Generate Flutter
  const flutterCode = generateFlutter(layoutData, options);

  // Save file
  const outputPath = path.join(outputDir, `${fileName}.dart`);
  fs.writeFileSync(outputPath, flutterCode);

  // Extract component dependencies
  const components = extractComponentReferences(layoutData);

  return {
    success: true,
    layoutName,
    widgetName,
    outputPath,
    fileExtension: 'dart',
    dependencies: components
  };
}

/**
 * Load and transform layout from JSON file
 */
async function transformLayoutFile(layoutJsonPath, options = {}) {
  if (!fs.existsSync(layoutJsonPath)) {
    throw new Error(`Layout file not found: ${layoutJsonPath}`);
  }

  const layoutData = JSON.parse(fs.readFileSync(layoutJsonPath, 'utf8'));

  return transformLayoutToFlutter(layoutData, options);
}

module.exports = {
  convertAutoLayoutToFlutter,
  generateFlutter,
  generateFrameFlutter,
  generateComponentFlutter,
  generatePadding,
  generateSizedBox,
  extractComponentReferences,
  toPascalCase,
  transformLayoutToFlutter,
  transformLayoutFile
};
