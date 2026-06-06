/**
 * Layout to JSX Transformer
 *
 * Converts extracted Figma layout data into production-ready JSX/React code.
 * Unlike layout-to-html which creates HTML reference files, this generates
 * actual React components ready for use in React/Next.js applications.
 */

const fs = require('fs');
const path = require('path');

/**
 * Convert Figma auto-layout properties to React inline style object
 */
function convertAutoLayoutToReactStyle(layout) {
  const style = {
    display: 'flex'
  };

  // Direction
  if (layout.layoutMode === 'VERTICAL') {
    style.flexDirection = 'column';
  } else if (layout.layoutMode === 'HORIZONTAL') {
    style.flexDirection = 'row';
  }

  // Primary axis alignment (justify-content)
  const primaryAxisMap = {
    'MIN': 'flex-start',
    'CENTER': 'center',
    'MAX': 'flex-end',
    'SPACE_BETWEEN': 'space-between'
  };
  if (layout.primaryAxisAlignItems && primaryAxisMap[layout.primaryAxisAlignItems]) {
    style.justifyContent = primaryAxisMap[layout.primaryAxisAlignItems];
  }

  // Counter axis alignment (align-items)
  const counterAxisMap = {
    'MIN': 'flex-start',
    'CENTER': 'center',
    'MAX': 'flex-end',
    'STRETCH': 'stretch'
  };
  if (layout.counterAxisAlignItems && counterAxisMap[layout.counterAxisAlignItems]) {
    style.alignItems = counterAxisMap[layout.counterAxisAlignItems];
  }

  // Gap (itemSpacing)
  if (layout.itemSpacing && layout.itemSpacing > 0) {
    style.gap = `${layout.itemSpacing}px`;
  }

  // Padding
  const pt = layout.paddingTop || 0;
  const pr = layout.paddingRight || 0;
  const pb = layout.paddingBottom || 0;
  const pl = layout.paddingLeft || 0;

  if (pt || pr || pb || pl) {
    style.padding = `${pt}px ${pr}px ${pb}px ${pl}px`;
  }

  // Sizing
  if (layout.width) {
    style.width = `${layout.width}px`;
  }
  if (layout.height) {
    style.height = `${layout.height}px`;
  }

  return style;
}

/**
 * Convert style object to JSX inline style format (camelCase keys)
 */
function styleObjectToJSXString(styleObj, indent = '') {
  const entries = Object.entries(styleObj);
  if (entries.length === 0) return '{}';

  const lines = entries.map(([key, value]) => {
    return `${indent}  ${key}: '${value}'`;
  });

  return `{\n${lines.join(',\n')}\n${indent}}`;
}

/**
 * Generate import statement for a component
 */
function generateComponentImport(componentName, importPath = '../components') {
  return `import { ${componentName} } from '${importPath}/${componentName}';`;
}

/**
 * Generate JSX for a component reference
 */
function generateComponentJSX(node, indent = '') {
  const name = node.componentRef?.name || node.name || 'Unknown';
  const componentName = toPascalCase(name);

  // Extract props if any
  const props = node.componentRef?.props || {};
  const propEntries = Object.entries(props);

  if (propEntries.length > 0) {
    const propsStr = propEntries.map(([key, value]) => {
      if (typeof value === 'string') {
        return `${key}="${value}"`;
      } else if (typeof value === 'boolean') {
        return value ? key : `${key}={false}`;
      } else {
        return `${key}={${JSON.stringify(value)}}`;
      }
    }).join(' ');
    return `${indent}<${componentName} ${propsStr} />`;
  }

  return `${indent}<${componentName} />`;
}

/**
 * Generate JSX for a layout frame and its children
 */
function generateFrameJSX(node, depth = 0, componentIndex = 0) {
  const indent = '  '.repeat(depth + 2);
  const style = convertAutoLayoutToReactStyle(node);
  const hasChildren = node.children && node.children.length > 0;

  let jsxContent = '';

  if (hasChildren) {
    const childLines = node.children.map((child, idx) => {
      if (child.type === 'INSTANCE' || child.componentRef) {
        return generateComponentJSX(child, indent);
      } else if (child.type === 'FRAME' || child.children) {
        return generateFrameJSX(child, depth + 1, idx);
      } else if (child.type === 'TEXT') {
        const text = child.characters || child.name || '';
        return `${indent}<div className="text-node">${text}</div>`;
      } else {
        return `${indent}<div className="node" />`;
      }
    });

    jsxContent = '\n' + childLines.join('\n') + '\n' + indent.slice(2);
  }

  const styleStr = Object.keys(style).length > 0
    ? ` style={${styleObjectToJSXString(style, indent.slice(2))}}`
    : '';

  return `${indent.slice(2)}<div${styleStr}>${jsxContent}</div>`;
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
 * Generate complete React/JSX component from layout data
 */
function generateJSX(layout, options = {}) {
  const layoutName = layout.name || 'UntitledLayout';
  const componentName = toPascalCase(layoutName);
  const {
    typescript = true,
    importPath = '../components',
    exportDefault = true
  } = options;

  // Extract component references
  const components = extractComponentReferences(layout);

  // Generate imports
  const imports = components.length > 0
    ? components.map(comp => generateComponentImport(comp, importPath)).join('\n')
    : '';

  // Generate JSX body
  const jsxBody = generateFrameJSX(layout, 0);

  // Generate component
  const fileExt = typescript ? 'tsx' : 'jsx';
  const typeAnnotation = typescript ? ': React.FC' : '';

  const code = `/**
 * ${componentName} Layout Component
 * Generated from Figma layout extraction
 *
 * This component uses transformed design system components.
 * Generated: ${new Date().toISOString()}
 */

import React from 'react';
${imports ? imports + '\n' : ''}
${typescript ? `export interface ${componentName}Props {
  // Add custom props here if needed
}

` : ''}const ${componentName}${typeAnnotation}${typescript ? `<${componentName}Props>` : ''} = (${typescript ? 'props' : ''}) => {
  return (
${jsxBody}
  );
};

${componentName}.displayName = '${componentName}';

${exportDefault ? `export default ${componentName};` : `export { ${componentName} };`}
`;

  return code;
}

/**
 * Transform layout data to JSX and save artifacts
 */
async function transformLayoutToJSX(layoutData, options = {}) {
  const {
    outputDir = '.design/extracted-code/react/layouts',
    typescript = true,
    importPath = '../components',
    exportDefault = true
  } = options;

  const layoutName = layoutData.name || 'untitled';
  const componentName = toPascalCase(layoutName);
  const fileExt = typescript ? 'tsx' : 'jsx';

  // Ensure directory exists
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  // Generate JSX
  const jsxCode = generateJSX(layoutData, {
    typescript,
    importPath,
    exportDefault
  });

  // Save file
  const outputPath = path.join(outputDir, `${componentName}.${fileExt}`);
  fs.writeFileSync(outputPath, jsxCode);

  // Extract component dependencies
  const components = extractComponentReferences(layoutData);

  return {
    success: true,
    layoutName,
    componentName,
    outputPath,
    fileExtension: fileExt,
    dependencies: components,
    typescript
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

  return transformLayoutToJSX(layoutData, options);
}

module.exports = {
  convertAutoLayoutToReactStyle,
  generateJSX,
  generateFrameJSX,
  generateComponentJSX,
  generateComponentImport,
  extractComponentReferences,
  toPascalCase,
  transformLayoutToJSX,
  transformLayoutFile
};
