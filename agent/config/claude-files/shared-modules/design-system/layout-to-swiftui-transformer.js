/**
 * Layout to SwiftUI Transformer
 *
 * Converts extracted Figma layout data into production-ready SwiftUI code.
 * Generates SwiftUI views with VStack, HStack, and proper spacing/padding.
 */

const fs = require('fs');
const path = require('path');

/**
 * Convert Figma auto-layout properties to SwiftUI stack and modifiers
 */
function convertAutoLayoutToSwiftUI(layout) {
  const result = {
    stackType: 'VStack', // default
    alignment: '.center',
    spacing: 0,
    padding: null
  };

  // Direction
  if (layout.layoutMode === 'VERTICAL') {
    result.stackType = 'VStack';
  } else if (layout.layoutMode === 'HORIZONTAL') {
    result.stackType = 'HStack';
  }

  // Alignment mapping
  const alignmentMap = {
    'MIN': layout.layoutMode === 'VERTICAL' ? '.leading' : '.top',
    'CENTER': '.center',
    'MAX': layout.layoutMode === 'VERTICAL' ? '.trailing' : '.bottom'
  };

  // Primary axis alignment for cross-axis in SwiftUI
  if (layout.counterAxisAlignItems && alignmentMap[layout.counterAxisAlignItems]) {
    result.alignment = alignmentMap[layout.counterAxisAlignItems];
  }

  // Spacing
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
      result.padding = { type: 'edges', vertical: pt, horizontal: pl };
    } else {
      result.padding = { type: 'individual', top: pt, leading: pl, bottom: pb, trailing: pr };
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
 * Generate padding modifier string
 */
function generatePaddingModifier(padding, indent = '') {
  if (!padding) return '';

  if (padding.type === 'uniform') {
    return `${indent}.padding(${padding.value})`;
  } else if (padding.type === 'edges') {
    const parts = [];
    if (padding.vertical > 0) parts.push(`.vertical, ${padding.vertical}`);
    if (padding.horizontal > 0) parts.push(`.horizontal, ${padding.horizontal}`);
    return `${indent}.padding([${parts.join(', ')}])`;
  } else if (padding.type === 'individual') {
    const edges = [];
    if (padding.top > 0) edges.push(`.top, ${padding.top}`);
    if (padding.leading > 0) edges.push(`.leading, ${padding.leading}`);
    if (padding.bottom > 0) edges.push(`.bottom, ${padding.bottom}`);
    if (padding.trailing > 0) edges.push(`.trailing, ${padding.trailing}`);

    if (edges.length === 0) return '';
    if (edges.length === 1) {
      return `${indent}.padding(${edges[0]})`;
    }
    return edges.map(e => `${indent}.padding(${e})`).join('\n');
  }

  return '';
}

/**
 * Generate SwiftUI view for a component reference
 */
function generateComponentSwiftUI(node, indent = '') {
  const name = node.componentRef?.name || node.name || 'Unknown';
  const componentName = toPascalCase(name);

  // Extract props if any
  const props = node.componentRef?.props || {};
  const propEntries = Object.entries(props);

  if (propEntries.length > 0) {
    const propsStr = propEntries.map(([key, value]) => {
      if (typeof value === 'string') {
        return `${key}: "${value}"`;
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
 * Generate SwiftUI view for a layout frame and its children
 */
function generateFrameSwiftUI(node, depth = 0) {
  const indent = '    '.repeat(depth + 1);
  const layout = convertAutoLayoutToSwiftUI(node);
  const hasChildren = node.children && node.children.length > 0;

  if (!hasChildren) {
    return `${indent}EmptyView()`;
  }

  // Generate children
  const childLines = node.children.map((child, idx) => {
    if (child.type === 'INSTANCE' || child.componentRef) {
      return generateComponentSwiftUI(child, indent + '    ');
    } else if (child.type === 'FRAME' || child.children) {
      return generateFrameSwiftUI(child, depth + 1);
    } else if (child.type === 'TEXT') {
      const text = child.characters || child.name || '';
      return `${indent}    Text("${text.replace(/"/g, '\\"')}")`;
    } else {
      return `${indent}    // TODO: Handle ${child.type}`;
    }
  });

  const childrenContent = childLines.join('\n');

  // Build stack with alignment and spacing
  const alignmentStr = layout.alignment !== '.center' ? `alignment: ${layout.alignment}, ` : '';
  const spacingStr = layout.spacing > 0 ? `spacing: ${layout.spacing}` : '';
  const stackParams = alignmentStr || spacingStr ? `(${alignmentStr}${spacingStr})` : '';

  let code = `${indent}${layout.stackType}${stackParams} {\n${childrenContent}\n${indent}}`;

  // Add modifiers
  const modifiers = [];

  if (layout.padding) {
    const paddingMod = generatePaddingModifier(layout.padding, indent);
    if (paddingMod) modifiers.push(paddingMod);
  }

  if (layout.width) {
    modifiers.push(`${indent}.frame(width: ${layout.width})`);
  }
  if (layout.height) {
    modifiers.push(`${indent}.frame(height: ${layout.height})`);
  }

  if (modifiers.length > 0) {
    code += '\n' + modifiers.join('\n');
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
 * Generate complete SwiftUI view from layout data
 */
function generateSwiftUI(layout, options = {}) {
  const layoutName = layout.name || 'UntitledLayout';
  const viewName = toPascalCase(layoutName);

  // Extract component references
  const components = extractComponentReferences(layout);

  // Generate imports (if needed)
  const imports = components.length > 0
    ? `// Component imports\n// import ${components.join(', ')}\n`
    : '';

  // Generate SwiftUI body
  const bodyContent = generateFrameSwiftUI(layout, 0);

  const code = `/**
 * ${viewName} Layout View
 * Generated from Figma layout extraction
 *
 * This view uses transformed design system components.
 * Generated: ${new Date().toISOString()}
 */

import SwiftUI

${imports}
struct ${viewName}: View {
    var body: some View {
${bodyContent}
    }
}

#Preview {
    ${viewName}()
}
`;

  return code;
}

/**
 * Transform layout data to SwiftUI and save artifacts
 */
async function transformLayoutToSwiftUI(layoutData, options = {}) {
  const {
    outputDir = '.design/extracted-code/swiftui/layouts'
  } = options;

  const layoutName = layoutData.name || 'untitled';
  const viewName = toPascalCase(layoutName);

  // Ensure directory exists
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  // Generate SwiftUI
  const swiftUICode = generateSwiftUI(layoutData, options);

  // Save file
  const outputPath = path.join(outputDir, `${viewName}.swift`);
  fs.writeFileSync(outputPath, swiftUICode);

  // Extract component dependencies
  const components = extractComponentReferences(layoutData);

  return {
    success: true,
    layoutName,
    viewName,
    outputPath,
    fileExtension: 'swift',
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

  return transformLayoutToSwiftUI(layoutData, options);
}

module.exports = {
  convertAutoLayoutToSwiftUI,
  generateSwiftUI,
  generateFrameSwiftUI,
  generateComponentSwiftUI,
  generatePaddingModifier,
  extractComponentReferences,
  toPascalCase,
  transformLayoutToSwiftUI,
  transformLayoutFile
};
