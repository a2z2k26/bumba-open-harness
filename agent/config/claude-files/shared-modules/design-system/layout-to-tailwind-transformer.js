/**
 * Layout to Tailwind CSS Transformer
 *
 * Converts extracted Figma layout data into production-ready HTML with Tailwind CSS utility classes.
 * Generates semantic HTML with Tailwind classes instead of inline styles.
 */

const fs = require('fs');
const path = require('path');

/**
 * Map Figma spacing values to Tailwind spacing scale
 */
function mapToTailwindSpacing(px) {
  const spacingMap = {
    0: '0',
    1: '0.5',
    2: '0.5',
    4: '1',
    6: '1.5',
    8: '2',
    10: '2.5',
    12: '3',
    14: '3.5',
    16: '4',
    20: '5',
    24: '6',
    28: '7',
    32: '8',
    36: '9',
    40: '10',
    44: '11',
    48: '12',
    56: '14',
    64: '16',
    80: '20',
    96: '24',
    112: '28',
    128: '32'
  };

  // Find closest match
  const closest = Object.keys(spacingMap).reduce((prev, curr) => {
    return Math.abs(curr - px) < Math.abs(prev - px) ? curr : prev;
  });

  return spacingMap[closest];
}

/**
 * Convert Figma auto-layout properties to Tailwind classes
 */
function convertAutoLayoutToTailwind(layout) {
  const classes = ['flex'];

  // Direction
  if (layout.layoutMode === 'VERTICAL') {
    classes.push('flex-col');
  } else if (layout.layoutMode === 'HORIZONTAL') {
    classes.push('flex-row');
  }

  // Primary axis alignment (justify-content)
  const primaryAxisMap = {
    'MIN': 'justify-start',
    'CENTER': 'justify-center',
    'MAX': 'justify-end',
    'SPACE_BETWEEN': 'justify-between'
  };
  if (layout.primaryAxisAlignItems && primaryAxisMap[layout.primaryAxisAlignItems]) {
    classes.push(primaryAxisMap[layout.primaryAxisAlignItems]);
  }

  // Counter axis alignment (align-items)
  const counterAxisMap = {
    'MIN': 'items-start',
    'CENTER': 'items-center',
    'MAX': 'items-end',
    'STRETCH': 'items-stretch'
  };
  if (layout.counterAxisAlignItems && counterAxisMap[layout.counterAxisAlignItems]) {
    classes.push(counterAxisMap[layout.counterAxisAlignItems]);
  }

  // Gap (itemSpacing)
  if (layout.itemSpacing && layout.itemSpacing > 0) {
    const gapClass = `gap-${mapToTailwindSpacing(layout.itemSpacing)}`;
    classes.push(gapClass);
  }

  // Padding
  const pt = layout.paddingTop || 0;
  const pr = layout.paddingRight || 0;
  const pb = layout.paddingBottom || 0;
  const pl = layout.paddingLeft || 0;

  if (pt || pr || pb || pl) {
    // Check if uniform padding
    if (pt === pr && pr === pb && pb === pl && pt > 0) {
      classes.push(`p-${mapToTailwindSpacing(pt)}`);
    } else {
      // Individual padding
      if (pt > 0) classes.push(`pt-${mapToTailwindSpacing(pt)}`);
      if (pr > 0) classes.push(`pr-${mapToTailwindSpacing(pr)}`);
      if (pb > 0) classes.push(`pb-${mapToTailwindSpacing(pb)}`);
      if (pl > 0) classes.push(`pl-${mapToTailwindSpacing(pl)}`);
    }
  }

  // Sizing - use custom values with [] syntax for exact pixel values
  if (layout.width) {
    classes.push(`w-[${layout.width}px]`);
  }
  if (layout.height) {
    classes.push(`h-[${layout.height}px]`);
  }

  return classes;
}

/**
 * Generate HTML for a component reference placeholder
 */
function generateComponentPlaceholder(node, options = {}) {
  const name = node.componentRef?.name || node.name || 'Unknown';
  const width = node.width || 100;
  const height = node.height || 40;

  // Generate Tailwind classes for component dimensions
  const classes = [];
  classes.push(`w-[${width}px]`);
  classes.push(`h-[${height}px]`);
  classes.push('border-2');
  classes.push('border-dashed');
  classes.push('border-indigo-500');
  classes.push('bg-indigo-50');
  classes.push('flex');
  classes.push('items-center');
  classes.push('justify-center');
  classes.push('rounded');
  classes.push('text-xs');
  classes.push('font-medium');
  classes.push('text-indigo-600');

  return `    <div class="${classes.join(' ')}" data-component="${escapeHtml(name)}">
      ${escapeHtml(name)}
    </div>`;
}

/**
 * Generate HTML for a layout frame and its children
 */
function generateFrameHTML(node, depth = 0) {
  const indent = '  '.repeat(depth + 1);
  const classes = convertAutoLayoutToTailwind(node);

  let childrenHTML = '';

  if (node.children && node.children.length > 0) {
    const childLines = node.children.map(child => {
      if (child.type === 'INSTANCE' || child.componentRef) {
        return generateComponentPlaceholder(child);
      } else if (child.type === 'FRAME' || child.children) {
        return generateFrameHTML(child, depth + 1);
      } else if (child.type === 'TEXT') {
        const text = escapeHtml(child.characters || child.name);
        const textClasses = ['text-sm', 'text-gray-900'];
        if (child.width) textClasses.push(`w-[${child.width}px]`);
        return `${indent}  <div class="${textClasses.join(' ')}">${text}</div>`;
      } else {
        return `${indent}  <div class="w-[${child.width || 0}px] h-[${child.height || 0}px] bg-gray-100 border border-gray-200"></div>`;
      }
    });
    childrenHTML = '\n' + childLines.join('\n') + '\n' + indent;
  }

  return `${indent}<div class="${classes.join(' ')}" data-figma-id="${escapeHtml(node.id || '')}" data-name="${escapeHtml(node.name || '')}">${childrenHTML}</div>`;
}

/**
 * Escape HTML special characters
 */
function escapeHtml(str) {
  if (typeof str !== 'string') return '';
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Generate complete HTML document from layout data
 */
function generateHTML(layout, options = {}) {
  const layoutName = layout.name || 'Untitled Layout';
  const frameHTML = generateFrameHTML(layout, 0);

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="layout-name" content="${escapeHtml(layoutName)}">
  <meta name="source" content="figma-extraction">
  <meta name="generator" content="design-bridge-layout-to-tailwind">
  <title>${escapeHtml(layoutName)} - Tailwind Layout</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    * {
      box-sizing: border-box;
    }

    body {
      font-family: system-ui, -apple-system, sans-serif;
      background: #f5f5f5;
      padding: 20px;
    }

    .layout-container {
      background: white;
      border-radius: 8px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.1);
      overflow: hidden;
    }
  </style>
</head>
<body>
  <h1 class="text-base font-semibold mb-3 text-gray-900">
    ${escapeHtml(layoutName)}
  </h1>
  <p class="text-xs text-gray-600 mb-5">
    Layout Reference - Generated with Tailwind CSS from Figma extraction
  </p>

  <div class="layout-container">
${frameHTML}
  </div>
${options.includeScreenshot && options.screenshotPath ? `
  <div class="flex gap-5 mt-5">
    <div class="border border-gray-300 rounded-lg overflow-hidden">
      <div class="bg-gray-800 text-white px-3 py-2 text-xs font-medium">
        Original Screenshot
      </div>
      <img src="${escapeHtml(options.screenshotPath)}" alt="Original Figma screenshot" class="max-w-full block">
    </div>
  </div>
` : ''}
</body>
</html>`;

  return html;
}

/**
 * Generate React component with Tailwind classes
 */
function generateTailwindJSX(node, depth = 0) {
  const indent = '  '.repeat(depth + 2);
  const classes = convertAutoLayoutToTailwind(node);
  const hasChildren = node.children && node.children.length > 0;

  let jsxContent = '';

  if (hasChildren) {
    const childLines = node.children.map((child, idx) => {
      if (child.type === 'INSTANCE' || child.componentRef) {
        const name = child.componentRef?.name || child.name || 'Unknown';
        const componentName = toPascalCase(name);
        return `${indent}<${componentName} />`;
      } else if (child.type === 'FRAME' || child.children) {
        return generateTailwindJSX(child, depth + 1);
      } else if (child.type === 'TEXT') {
        const text = child.characters || child.name || '';
        return `${indent}<div className="text-sm text-gray-900">${text}</div>`;
      } else {
        return `${indent}<div className="bg-gray-100 border border-gray-200" />`;
      }
    });

    jsxContent = '\n' + childLines.join('\n') + '\n' + indent.slice(2);
  }

  return `${indent.slice(2)}<div className="${classes.join(' ')}">${jsxContent}</div>`;
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
 * Generate complete React component with Tailwind
 */
function generateReactTailwind(layout, options = {}) {
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
    ? components.map(comp => `import { ${comp} } from '${importPath}/${comp}';`).join('\n')
    : '';

  // Generate JSX body
  const jsxBody = generateTailwindJSX(layout, 0);

  // Generate component
  const fileExt = typescript ? 'tsx' : 'jsx';
  const typeAnnotation = typescript ? ': React.FC' : '';

  const code = `/**
 * ${componentName} Layout Component
 * Generated from Figma layout extraction with Tailwind CSS
 *
 * This component uses Tailwind utility classes for styling.
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
 * Transform layout data to Tailwind and save artifacts
 */
async function transformLayoutToTailwind(layoutData, options = {}) {
  const {
    outputDir = '.design/extracted-code/tailwind/layouts',
    format = 'html', // 'html' or 'jsx'
    typescript = true,
    importPath = '../components',
    exportDefault = true,
    includeScreenshot = true
  } = options;

  const layoutName = layoutData.name || 'untitled';
  const componentName = toPascalCase(layoutName);

  // Ensure directory exists
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  let outputPath;
  let code;

  if (format === 'jsx') {
    // Generate React component with Tailwind
    code = generateReactTailwind(layoutData, {
      typescript,
      importPath,
      exportDefault
    });
    const fileExt = typescript ? 'tsx' : 'jsx';
    outputPath = path.join(outputDir, `${componentName}.${fileExt}`);
  } else {
    // Generate HTML with Tailwind
    code = generateHTML(layoutData, {
      includeScreenshot,
      screenshotPath: includeScreenshot ? 'screenshot.png' : null
    });
    outputPath = path.join(outputDir, `${layoutName.toLowerCase().replace(/\s+/g, '-')}.html`);
  }

  fs.writeFileSync(outputPath, code);

  // Extract component dependencies
  const components = extractComponentReferences(layoutData);

  return {
    success: true,
    layoutName,
    componentName,
    outputPath,
    format,
    fileExtension: format === 'jsx' ? (typescript ? 'tsx' : 'jsx') : 'html',
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

  return transformLayoutToTailwind(layoutData, options);
}

module.exports = {
  convertAutoLayoutToTailwind,
  mapToTailwindSpacing,
  generateHTML,
  generateFrameHTML,
  generateTailwindJSX,
  generateReactTailwind,
  generateComponentPlaceholder,
  extractComponentReferences,
  toPascalCase,
  transformLayoutToTailwind,
  transformLayoutFile
};
