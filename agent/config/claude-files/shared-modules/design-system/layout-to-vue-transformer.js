/**
 * Layout to Vue Transformer
 *
 * Converts extracted Figma layout data into production-ready Vue 3 components.
 * Generates Vue SFC (Single File Components) with Composition API and scoped styles.
 */

const fs = require('fs');
const path = require('path');

/**
 * Convert Figma auto-layout properties to CSS flexbox
 */
function convertAutoLayoutToCSS(layout) {
  const css = {
    display: 'flex'
  };

  // Direction
  if (layout.layoutMode === 'VERTICAL') {
    css['flex-direction'] = 'column';
  } else if (layout.layoutMode === 'HORIZONTAL') {
    css['flex-direction'] = 'row';
  }

  // Primary axis alignment (justify-content)
  const primaryAxisMap = {
    'MIN': 'flex-start',
    'CENTER': 'center',
    'MAX': 'flex-end',
    'SPACE_BETWEEN': 'space-between'
  };
  if (layout.primaryAxisAlignItems && primaryAxisMap[layout.primaryAxisAlignItems]) {
    css['justify-content'] = primaryAxisMap[layout.primaryAxisAlignItems];
  }

  // Counter axis alignment (align-items)
  const counterAxisMap = {
    'MIN': 'flex-start',
    'CENTER': 'center',
    'MAX': 'flex-end',
    'STRETCH': 'stretch'
  };
  if (layout.counterAxisAlignItems && counterAxisMap[layout.counterAxisAlignItems]) {
    css['align-items'] = counterAxisMap[layout.counterAxisAlignItems];
  }

  // Gap (itemSpacing)
  if (layout.itemSpacing && layout.itemSpacing > 0) {
    css['gap'] = `${layout.itemSpacing}px`;
  }

  // Padding
  const pt = layout.paddingTop || 0;
  const pr = layout.paddingRight || 0;
  const pb = layout.paddingBottom || 0;
  const pl = layout.paddingLeft || 0;

  if (pt || pr || pb || pl) {
    css['padding'] = `${pt}px ${pr}px ${pb}px ${pl}px`;
  }

  // Sizing
  if (layout.width) {
    css['width'] = `${layout.width}px`;
  }
  if (layout.height) {
    css['height'] = `${layout.height}px`;
  }

  return css;
}

/**
 * Convert CSS object to CSS string
 */
function cssObjectToString(cssObj, selector) {
  const properties = Object.entries(cssObj)
    .map(([key, value]) => `  ${key}: ${value};`)
    .join('\n');

  return `${selector} {
${properties}
}`;
}

/**
 * Generate Vue template for a component reference
 */
function generateComponentTemplate(node, indent = '') {
  const name = node.componentRef?.name || node.name || 'Unknown';
  const componentName = toKebabCase(name);

  // Extract props if any
  const props = node.componentRef?.props || {};
  const propEntries = Object.entries(props);

  if (propEntries.length > 0) {
    const propsStr = propEntries.map(([key, value]) => {
      const propKey = toKebabCase(key);
      if (typeof value === 'string') {
        return `${propKey}="${value}"`;
      } else if (typeof value === 'boolean') {
        return value ? propKey : `:${propKey}="false"`;
      } else {
        return `:${propKey}="${JSON.stringify(value)}"`;
      }
    }).join(' ');
    return `${indent}<${componentName} ${propsStr} />`;
  }

  return `${indent}<${componentName} />`;
}

/**
 * Generate Vue template for a layout frame and its children
 */
function generateFrameTemplate(node, depth = 0, parentIndex = 0) {
  const indent = '  '.repeat(depth + 2);
  const className = `frame-${depth}-${parentIndex}`;
  const hasChildren = node.children && node.children.length > 0;

  let templateContent = '';

  if (hasChildren) {
    const childLines = node.children.map((child, idx) => {
      if (child.type === 'INSTANCE' || child.componentRef) {
        return generateComponentTemplate(child, indent);
      } else if (child.type === 'FRAME' || child.children) {
        return generateFrameTemplate(child, depth + 1, idx);
      } else if (child.type === 'TEXT') {
        const text = child.characters || child.name || '';
        return `${indent}<div class="text-node">${text}</div>`;
      } else {
        return `${indent}<div class="node"></div>`;
      }
    });

    templateContent = '\n' + childLines.join('\n') + '\n' + indent.slice(2);
  }

  return `${indent.slice(2)}<div class="${className}">${templateContent}</div>`;
}

/**
 * Generate CSS for all frames in the layout
 */
function generateFrameStyles(node, depth = 0, parentIndex = 0, styles = []) {
  const className = `.frame-${depth}-${parentIndex}`;
  const css = convertAutoLayoutToCSS(node);

  styles.push(cssObjectToString(css, className));

  // Recursively process children
  if (node.children && Array.isArray(node.children)) {
    node.children.forEach((child, idx) => {
      if (child.type === 'FRAME' || child.children) {
        generateFrameStyles(child, depth + 1, idx, styles);
      }
    });
  }

  return styles;
}

/**
 * Extract unique component references from layout
 */
function extractComponentReferences(node, components = new Set()) {
  if (node.type === 'INSTANCE' || node.componentRef) {
    const name = node.componentRef?.name || node.name;
    if (name) {
      components.add({
        kebab: toKebabCase(name),
        pascal: toPascalCase(name)
      });
    }
  }

  if (node.children && Array.isArray(node.children)) {
    node.children.forEach(child => extractComponentReferences(child, components));
  }

  return Array.from(components);
}

/**
 * Convert string to kebab-case
 */
function toKebabCase(str) {
  return str
    .replace(/([a-z])([A-Z])/g, '$1-$2')
    .replace(/[\s_]+/g, '-')
    .toLowerCase();
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
 * Generate complete Vue SFC from layout data
 */
function generateVue(layout, options = {}) {
  const layoutName = layout.name || 'UntitledLayout';
  const componentName = toPascalCase(layoutName);
  const {
    typescript = true,
    compositionAPI = true
  } = options;

  // Extract component references
  const components = extractComponentReferences(layout);

  // Generate imports
  const imports = components.length > 0
    ? components.map(comp => `import ${comp.pascal} from './${comp.pascal}.vue';`).join('\n')
    : '';

  // Generate template
  const templateContent = generateFrameTemplate(layout, 0, 0);

  // Generate styles
  const styles = generateFrameStyles(layout, 0, 0);
  const styleContent = styles.join('\n\n');

  // Generate script section
  let scriptContent = '';

  if (compositionAPI) {
    scriptContent = `<script${typescript ? ' lang="ts"' : ''} setup>
${imports ? imports + '\n' : ''}
${typescript ? `interface Props {
  // Add custom props here if needed
}

const props = defineProps<Props>();
` : '// Component logic here'}
</script>`;
  } else {
    scriptContent = `<script${typescript ? ' lang="ts"' : ''}>
import { defineComponent } from 'vue';
${imports ? '\n' + imports : ''}

export default defineComponent({
  name: '${componentName}',
  ${components.length > 0 ? `components: {
    ${components.map(c => c.pascal).join(',\n    ')}
  },` : ''}
  ${typescript ? `props: {
    // Add custom props here if needed
  },` : ''}
  setup(props) {
    // Component logic here
    return {};
  }
});
</script>`;
  }

  const code = `<!--
  ${componentName} Layout Component
  Generated from Figma layout extraction

  This component uses transformed design system components.
  Generated: ${new Date().toISOString()}
-->

<template>
${templateContent}
</template>

${scriptContent}

<style scoped>
${styleContent}

.text-node {
  font-size: 14px;
  color: #333;
}

.node {
  background: rgba(0, 0, 0, 0.05);
  border: 1px solid rgba(0, 0, 0, 0.1);
}
</style>
`;

  return code;
}

/**
 * Transform layout data to Vue and save artifacts
 */
async function transformLayoutToVue(layoutData, options = {}) {
  const {
    outputDir = '.design/extracted-code/vue/layouts',
    typescript = true,
    compositionAPI = true
  } = options;

  const layoutName = layoutData.name || 'untitled';
  const componentName = toPascalCase(layoutName);

  // Ensure directory exists
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  // Generate Vue
  const vueCode = generateVue(layoutData, {
    typescript,
    compositionAPI
  });

  // Save file
  const outputPath = path.join(outputDir, `${componentName}.vue`);
  fs.writeFileSync(outputPath, vueCode);

  // Extract component dependencies
  const components = extractComponentReferences(layoutData);

  return {
    success: true,
    layoutName,
    componentName,
    outputPath,
    fileExtension: 'vue',
    dependencies: components.map(c => c.pascal),
    typescript,
    compositionAPI
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

  return transformLayoutToVue(layoutData, options);
}

module.exports = {
  convertAutoLayoutToCSS,
  cssObjectToString,
  generateVue,
  generateFrameTemplate,
  generateFrameStyles,
  generateComponentTemplate,
  extractComponentReferences,
  toKebabCase,
  toPascalCase,
  transformLayoutToVue,
  transformLayoutFile
};
