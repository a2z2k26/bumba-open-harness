/**
 * Layout to Jetpack Compose Transformer
 *
 * Converts extracted Figma layout data into production-ready Jetpack Compose/Kotlin code.
 * Generates Compose functions with Column, Row, and proper spacing/padding modifiers.
 */

const fs = require('fs');
const path = require('path');

/**
 * Convert Figma auto-layout properties to Compose properties
 */
function convertAutoLayoutToCompose(layout) {
  const result = {
    composableType: 'Column', // default
    horizontalAlignment: 'Alignment.CenterHorizontally',
    verticalAlignment: 'Alignment.CenterVertically',
    arrangement: null,
    spacing: 0,
    padding: null
  };

  // Direction
  if (layout.layoutMode === 'VERTICAL') {
    result.composableType = 'Column';
  } else if (layout.layoutMode === 'HORIZONTAL') {
    result.composableType = 'Row';
  }

  // Primary axis arrangement
  const arrangementMap = {
    'MIN': 'Arrangement.Top', // or Start for Row
    'CENTER': 'Arrangement.Center',
    'MAX': 'Arrangement.Bottom', // or End for Row
    'SPACE_BETWEEN': 'Arrangement.SpaceBetween'
  };

  if (layout.primaryAxisAlignItems) {
    const baseArrangement = arrangementMap[layout.primaryAxisAlignItems];
    if (baseArrangement) {
      // Adjust for Row vs Column
      if (result.composableType === 'Row') {
        result.arrangement = baseArrangement
          .replace('Top', 'Start')
          .replace('Bottom', 'End');
      } else {
        result.arrangement = baseArrangement;
      }
    }
  }

  // Add spacing to arrangement if needed
  if (layout.itemSpacing && layout.itemSpacing > 0) {
    result.spacing = layout.itemSpacing;
    if (result.arrangement) {
      // Convert Arrangement.X to Arrangement.spacedBy(Xdp, Alignment.Y)
      const alignmentPart = result.arrangement.split('.')[1];
      result.arrangement = `Arrangement.spacedBy(${layout.itemSpacing}.dp, ${result.arrangement})`;
    } else {
      result.arrangement = `Arrangement.spacedBy(${layout.itemSpacing}.dp)`;
    }
  }

  // Counter axis alignment
  const alignmentMap = {
    'MIN': result.composableType === 'Column' ? 'Alignment.Start' : 'Alignment.Top',
    'CENTER': result.composableType === 'Column' ? 'Alignment.CenterHorizontally' : 'Alignment.CenterVertically',
    'MAX': result.composableType === 'Column' ? 'Alignment.End' : 'Alignment.Bottom'
  };

  if (layout.counterAxisAlignItems && alignmentMap[layout.counterAxisAlignItems]) {
    if (result.composableType === 'Column') {
      result.horizontalAlignment = alignmentMap[layout.counterAxisAlignItems];
    } else {
      result.verticalAlignment = alignmentMap[layout.counterAxisAlignItems];
    }
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
      result.padding = { type: 'individual', start: pl, top: pt, end: pr, bottom: pb };
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
 * Generate padding modifier
 */
function generatePaddingModifier(padding) {
  if (!padding) return null;

  if (padding.type === 'uniform') {
    return `.padding(${padding.value}.dp)`;
  } else if (padding.type === 'symmetric') {
    return `.padding(horizontal = ${padding.horizontal}.dp, vertical = ${padding.vertical}.dp)`;
  } else if (padding.type === 'individual') {
    const parts = [];
    if (padding.start > 0) parts.push(`start = ${padding.start}.dp`);
    if (padding.top > 0) parts.push(`top = ${padding.top}.dp`);
    if (padding.end > 0) parts.push(`end = ${padding.end}.dp`);
    if (padding.bottom > 0) parts.push(`bottom = ${padding.bottom}.dp`);
    return `.padding(${parts.join(', ')})`;
  }

  return null;
}

/**
 * Generate size modifier
 */
function generateSizeModifier(width, height) {
  const modifiers = [];

  if (width && height) {
    modifiers.push(`.size(width = ${width}.dp, height = ${height}.dp)`);
  } else {
    if (width) modifiers.push(`.width(${width}.dp)`);
    if (height) modifiers.push(`.height(${height}.dp)`);
  }

  return modifiers;
}

/**
 * Generate Compose code for a component reference
 */
function generateComponentCompose(node, indent = '') {
  const name = node.componentRef?.name || node.name || 'Unknown';
  const componentName = toPascalCase(name);

  // Extract props if any
  const props = node.componentRef?.props || {};
  const propEntries = Object.entries(props);

  if (propEntries.length > 0) {
    const propsStr = propEntries.map(([key, value]) => {
      if (typeof value === 'string') {
        return `${key} = "${value}"`;
      } else if (typeof value === 'boolean') {
        return `${key} = ${value}`;
      } else {
        return `${key} = ${JSON.stringify(value)}`;
      }
    }).join(', ');
    return `${indent}${componentName}(${propsStr})`;
  }

  return `${indent}${componentName}()`;
}

/**
 * Generate Compose code for a layout frame and its children
 */
function generateFrameCompose(node, depth = 0) {
  const indent = '    '.repeat(depth + 1);
  const layout = convertAutoLayoutToCompose(node);
  const hasChildren = node.children && node.children.length > 0;

  if (!hasChildren) {
    return `${indent}Box(modifier = Modifier)`;
  }

  // Generate children
  const childLines = node.children.map((child, idx) => {
    if (child.type === 'INSTANCE' || child.componentRef) {
      return generateComponentCompose(child, indent + '    ');
    } else if (child.type === 'FRAME' || child.children) {
      return generateFrameCompose(child, depth + 1);
    } else if (child.type === 'TEXT') {
      const text = child.characters || child.name || '';
      return `${indent}    Text("${text.replace(/"/g, '\\"')}")`;
    } else {
      return `${indent}    // TODO: Handle ${child.type}`;
    }
  });

  const childrenContent = childLines.join('\n');

  // Build modifiers
  const modifiers = ['Modifier'];

  const sizeModifiers = generateSizeModifier(layout.width, layout.height);
  modifiers.push(...sizeModifiers);

  const paddingMod = generatePaddingModifier(layout.padding);
  if (paddingMod) modifiers.push(paddingMod);

  const modifierChain = modifiers.join('\n' + indent + '    ');

  // Build composable parameters
  const params = [];

  // Add modifier
  params.push(`modifier = ${modifierChain}`);

  // Add alignment/arrangement based on type
  if (layout.composableType === 'Column') {
    if (layout.horizontalAlignment !== 'Alignment.CenterHorizontally') {
      params.push(`horizontalAlignment = ${layout.horizontalAlignment}`);
    }
    if (layout.arrangement) {
      params.push(`verticalArrangement = ${layout.arrangement}`);
    }
  } else if (layout.composableType === 'Row') {
    if (layout.verticalAlignment !== 'Alignment.CenterVertically') {
      params.push(`verticalAlignment = ${layout.verticalAlignment}`);
    }
    if (layout.arrangement) {
      params.push(`horizontalArrangement = ${layout.arrangement}`);
    }
  }

  const paramsStr = params.join(',\n' + indent + '    ');

  const code = `${indent}${layout.composableType}(
${indent}    ${paramsStr}
${indent}) {
${childrenContent}
${indent}}`;

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
 * Generate complete Jetpack Compose composable from layout data
 */
function generateCompose(layout, options = {}) {
  const layoutName = layout.name || 'UntitledLayout';
  const composableName = toPascalCase(layoutName);

  // Extract component references
  const components = extractComponentReferences(layout);

  // Generate imports
  const componentImports = components.length > 0
    ? `// Component imports\n// import com.example.components.${components.join('\n// import com.example.components.')}\n`
    : '';

  // Generate Compose body
  const bodyContent = generateFrameCompose(layout, 0);

  const code = `/**
 * ${composableName} Layout Composable
 * Generated from Figma layout extraction
 *
 * This composable uses transformed design system components.
 * Generated: ${new Date().toISOString()}
 */

package com.example.layouts

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp

${componentImports}
@Composable
fun ${composableName}() {
${bodyContent}
}

@Preview(showBackground = true)
@Composable
fun ${composableName}Preview() {
    ${composableName}()
}
`;

  return code;
}

/**
 * Transform layout data to Compose and save artifacts
 */
async function transformLayoutToCompose(layoutData, options = {}) {
  const {
    outputDir = '.design/extracted-code/compose/layouts'
  } = options;

  const layoutName = layoutData.name || 'untitled';
  const composableName = toPascalCase(layoutName);

  // Ensure directory exists
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  // Generate Compose
  const composeCode = generateCompose(layoutData, options);

  // Save file
  const outputPath = path.join(outputDir, `${composableName}.kt`);
  fs.writeFileSync(outputPath, composeCode);

  // Extract component dependencies
  const components = extractComponentReferences(layoutData);

  return {
    success: true,
    layoutName,
    composableName,
    outputPath,
    fileExtension: 'kt',
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

  return transformLayoutToCompose(layoutData, options);
}

module.exports = {
  convertAutoLayoutToCompose,
  generateCompose,
  generateFrameCompose,
  generateComponentCompose,
  generatePaddingModifier,
  generateSizeModifier,
  extractComponentReferences,
  toPascalCase,
  transformLayoutToCompose,
  transformLayoutFile
};
