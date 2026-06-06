/**
 * Layout Transformer
 *
 * Transforms validated layout structures into framework-specific code.
 * This is distinct from component transformers - it handles composition
 * and spatial arrangement, not individual component generation.
 *
 * Flow:
 * 1. Receive validated HTML structure + layout JSON + screenshot reference
 * 2. Read project framework from .design/config.json
 * 3. Look up components in registry, get their import paths
 * 4. Generate framework-specific layout code using existing components
 *
 * v4.0.0 Integration:
 * - Added RegistryManager support for unified component/layout lookup
 * - O(1) component resolution via sourceMapping
 * - Backward compatible with legacy registry
 *
 * @version 2.0.0
 */

const fs = require('fs');
const path = require('path');
const { DesignStructure } = require('./design-structure');

// Lazy-load RegistryManager to avoid circular dependencies
let _registryManagerModule = null;
function getRegistryManagerModule() {
  if (!_registryManagerModule) {
    _registryManagerModule = require('./registry-manager');
  }
  return _registryManagerModule;
}

class LayoutTransformer {
  constructor(projectPath) {
    this.projectPath = projectPath;
    this.designPath = path.join(projectPath, '.design');
    this.designStructure = new DesignStructure(projectPath);
    this.config = this.loadConfig();
    this.registry = this.loadRegistry();
    this.framework = this.config.project?.framework || this.config.framework || 'react';
    this._registryManager = null;
    this._v4Available = null;
  }

  /**
   * Load project configuration
   */
  loadConfig() {
    const configPath = path.join(this.projectPath, '.design', 'config.json');
    if (fs.existsSync(configPath)) {
      return JSON.parse(fs.readFileSync(configPath, 'utf8'));
    }
    return { framework: 'react' };
  }

  /**
   * Load component registry
   */
  loadRegistry() {
    const registryPath = path.join(this.projectPath, '.design', 'componentRegistry.json');
    if (fs.existsSync(registryPath)) {
      return JSON.parse(fs.readFileSync(registryPath, 'utf8'));
    }
    return { components: [] };
  }

  /**
   * Load tokens
   */
  loadTokens() {
    const tokensPath = path.join(this.projectPath, '.design', 'tokens', 'index.json');
    if (fs.existsSync(tokensPath)) {
      return JSON.parse(fs.readFileSync(tokensPath, 'utf8'));
    }
    return {};
  }

  // ==========================================================================
  // v4.0.0 Registry Manager Integration
  // ==========================================================================

  /**
   * Check if v4.0.0 registry is available
   * @returns {boolean} True if v4.0.0 registry exists
   */
  hasV4Registry() {
    if (this._v4Available === null) {
      const indexPath = path.join(this.designPath, 'registry-index.json');
      this._v4Available = fs.existsSync(indexPath);
    }
    return this._v4Available;
  }

  /**
   * Get the RegistryManager instance (lazy-loaded)
   * @returns {Promise<Object>} RegistryManager instance
   */
  async getRegistryManager() {
    if (!this._registryManager && this.hasV4Registry()) {
      const { getRegistryManager } = getRegistryManagerModule();
      this._registryManager = await getRegistryManager(this.designPath);
    }
    return this._registryManager;
  }

  /**
   * Find component by Figma node ID using v4.0.0 registry (O(1) lookup)
   * @param {string} nodeId - Figma node ID
   * @returns {Promise<Object|null>} Component entry or null
   */
  async findComponentByNodeId(nodeId) {
    if (!this.hasV4Registry()) {
      return this.findComponentByNodeIdLegacy(nodeId);
    }

    try {
      const manager = await this.getRegistryManager();
      return await manager.findByNodeId(nodeId, 'components');
    } catch (error) {
      console.warn(`[LayoutTransformer] v4.0.0 lookup failed, falling back:`, error.message);
      return this.findComponentByNodeIdLegacy(nodeId);
    }
  }

  /**
   * Legacy fallback: Find component by Figma node ID
   * @param {string} nodeId - Figma node ID
   * @returns {Object|null} Component entry or null
   */
  findComponentByNodeIdLegacy(nodeId) {
    if (!this.registry.components || !nodeId) return null;

    const components = Array.isArray(this.registry.components)
      ? this.registry.components
      : Object.values(this.registry.components);

    return components.find(c =>
      c.source?.nodeId === nodeId ||
      c.figmaNodeId === nodeId ||
      c.id?.includes(nodeId.replace(/:/g, '-'))
    ) || null;
  }

  /**
   * Find all components referenced in a layout using v4.0.0 registry
   * @param {Array} componentRefs - Component references from layout
   * @returns {Promise<Array>} Resolved component entries
   */
  async resolveComponentRefsV4(componentRefs) {
    if (!this.hasV4Registry() || componentRefs.length === 0) {
      return componentRefs.map(ref => ({
        ...ref,
        resolved: this.findComponent(ref.name),
        source: 'legacy'
      }));
    }

    const manager = await this.getRegistryManager();
    const resolved = [];

    for (const ref of componentRefs) {
      let component = null;

      // Try by node ID first (O(1) lookup)
      if (ref.id) {
        component = await manager.findByNodeId(ref.id, 'components');
      }

      // Fall back to name search
      if (!component && ref.name) {
        const results = await manager.findByName(ref.name, 'components');
        component = results[0] || null;
      }

      resolved.push({
        ...ref,
        resolved: component,
        source: component ? 'v4' : 'not_found'
      });
    }

    return resolved;
  }

  /**
   * Get v4.0.0 registry statistics
   * @returns {Promise<Object|null>} Registry stats or null
   */
  async getV4Stats() {
    if (!this.hasV4Registry()) return null;

    try {
      const manager = await this.getRegistryManager();
      return await manager.getStats();
    } catch (error) {
      return null;
    }
  }

  /**
   * Find component in registry by name
   * @param {string} name - Component name
   * @returns {Object|null} Component registry entry
   */
  findComponent(name) {
    if (!this.registry.components) return null;

    // Handle both object and array formats for components
    const components = Array.isArray(this.registry.components)
      ? this.registry.components
      : Object.values(this.registry.components);

    // Try exact match first
    let component = components.find(c =>
      c.name === name || c.name.toLowerCase() === name.toLowerCase()
    );

    // Try partial match
    if (!component) {
      component = components.find(c =>
        c.name.toLowerCase().includes(name.toLowerCase()) ||
        name.toLowerCase().includes(c.name.toLowerCase())
      );
    }

    return component || null;
  }

  /**
   * Get the import path for a component in the target framework
   * @param {string} componentName - Component name
   * @returns {Object} Import info { path, name, exists }
   */
  getComponentImport(componentName) {
    const component = this.findComponent(componentName);
    const frameworkDir = path.join(
      this.projectPath,
      '.design',
      'extracted-code',
      this.framework
    );

    // Determine file extension based on framework
    const extensions = {
      'react': ['.tsx', '.jsx', '.js'],
      'vue': ['.vue'],
      'svelte': ['.svelte'],
      'angular': ['.component.ts'],
      'react-native': ['.tsx', '.jsx', '.js'],
      'flutter': ['.dart'],
      'swiftui': ['.swift'],
      'jetpack-compose': ['.kt'],
      'web-components': ['.js', '.ts']
    };

    const exts = extensions[this.framework] || ['.js'];

    // Check if transformed component exists
    for (const ext of exts) {
      const filePath = path.join(frameworkDir, `${componentName}${ext}`);
      if (fs.existsSync(filePath)) {
        return {
          path: `./${componentName}${ext}`,
          name: componentName,
          exists: true,
          fullPath: filePath,
          registryEntry: component
        };
      }
    }

    // Component not yet transformed
    return {
      path: null,
      name: componentName,
      exists: false,
      registryEntry: component
    };
  }

  /**
   * Extract component references from layout data
   * @param {Object} layoutData - Layout JSON data
   * @returns {Array} List of component references
   */
  extractComponentRefs(layoutData) {
    const refs = [];

    const traverse = (node) => {
      if (!node) return;

      // Check for component reference
      if (node.componentRef) {
        refs.push({
          name: node.componentRef.name,
          id: node.componentRef.mainComponentId,
          width: node.width,
          height: node.height,
          x: node.x,
          y: node.y
        });
      } else if (node.type === 'INSTANCE') {
        refs.push({
          name: node.name,
          id: node.id,
          width: node.width,
          height: node.height,
          x: node.x,
          y: node.y
        });
      }

      // Traverse children
      if (node.children && Array.isArray(node.children)) {
        node.children.forEach(traverse);
      }
    };

    traverse(layoutData);
    return refs;
  }

  /**
   * Convert validated CSS structure to framework-specific styles
   * @param {Object} cssStructure - Validated CSS from HTML pass
   * @returns {Object} Framework-specific style output
   */
  convertStyles(cssStructure) {
    switch (this.framework) {
      case 'react':
        return this.convertToReactStyles(cssStructure);
      case 'react-native':
        return this.convertToRNStyles(cssStructure);
      case 'vue':
        return this.convertToVueStyles(cssStructure);
      case 'svelte':
        return this.convertToSvelteStyles(cssStructure);
      case 'angular':
        return this.convertToAngularStyles(cssStructure);
      case 'flutter':
        return this.convertToFlutterStyles(cssStructure);
      case 'swiftui':
        return this.convertToSwiftUIStyles(cssStructure);
      case 'jetpack-compose':
        return this.convertToComposeStyles(cssStructure);
      case 'web-components':
        return this.convertToWebComponentStyles(cssStructure);
      default:
        return this.convertToReactStyles(cssStructure);
    }
  }

  // ============================================================================
  // Framework-Specific Layout Generators
  // ============================================================================

  /**
   * Generate React layout
   */
  generateReactLayout(layoutData, validatedStructure, components) {
    const imports = [];
    const componentImports = [];

    // Collect imports for used components
    components.forEach(comp => {
      const importInfo = this.getComponentImport(comp.name);
      if (importInfo.exists) {
        componentImports.push(`import { ${comp.name} } from '${importInfo.path}';`);
      } else {
        componentImports.push(`// TODO: Transform component '${comp.name}' first`);
      }
    });

    const layoutName = this.pascalCase(layoutData.name || 'Layout');
    const styles = this.convertToReactStyles(validatedStructure.css || {});

    return `import React from 'react';
${componentImports.join('\n')}

${styles.styledComponents || ''}

interface ${layoutName}Props {
  className?: string;
}

export const ${layoutName}: React.FC<${layoutName}Props> = ({ className }) => {
  return (
    <div className={className} style={styles.container}>
${this.generateReactChildren(layoutData.children || [], 3)}
    </div>
  );
};

const styles = {
  container: ${JSON.stringify(validatedStructure.css?.container || {}, null, 2)},
};

export default ${layoutName};
`;
  }

  /**
   * Generate React children JSX
   */
  generateReactChildren(children, indent = 0) {
    const spaces = '  '.repeat(indent);

    return children.map(child => {
      if (child.componentRef || child.type === 'INSTANCE') {
        const name = child.componentRef?.name || child.name;
        const importInfo = this.getComponentImport(name);

        if (importInfo.exists) {
          return `${spaces}<${name} />`;
        } else {
          return `${spaces}{/* ${name} - not yet transformed */}`;
        }
      } else if (child.type === 'FRAME' && child.children) {
        const frameStyle = this.extractFrameStyle(child);
        return `${spaces}<div style={${JSON.stringify(frameStyle)}}>
${this.generateReactChildren(child.children, indent + 1)}
${spaces}</div>`;
      } else if (child.type === 'TEXT') {
        return `${spaces}<span>${this.escapeJsx(child.characters || child.name)}</span>`;
      }
      return '';
    }).filter(Boolean).join('\n');
  }

  /**
   * Generate Vue layout
   */
  generateVueLayout(layoutData, validatedStructure, components) {
    const layoutName = this.pascalCase(layoutData.name || 'Layout');
    const componentImports = components.map(comp => {
      const importInfo = this.getComponentImport(comp.name);
      if (importInfo.exists) {
        return `import ${comp.name} from '${importInfo.path}';`;
      }
      return `// TODO: Transform component '${comp.name}' first`;
    });

    return `<script setup lang="ts">
${componentImports.join('\n')}

defineProps<{
  class?: string;
}>();
</script>

<template>
  <div class="${layoutName.toLowerCase()}-container">
${this.generateVueChildren(layoutData.children || [], 2)}
  </div>
</template>

<style scoped>
.${layoutName.toLowerCase()}-container {
${this.cssObjectToString(validatedStructure.css?.container || {}, 1)}
}
</style>
`;
  }

  /**
   * Generate Vue children template
   */
  generateVueChildren(children, indent = 0) {
    const spaces = '  '.repeat(indent);

    return children.map(child => {
      if (child.componentRef || child.type === 'INSTANCE') {
        const name = child.componentRef?.name || child.name;
        return `${spaces}<${name} />`;
      } else if (child.type === 'FRAME' && child.children) {
        return `${spaces}<div class="frame">
${this.generateVueChildren(child.children, indent + 1)}
${spaces}</div>`;
      } else if (child.type === 'TEXT') {
        return `${spaces}<span>${child.characters || child.name}</span>`;
      }
      return '';
    }).filter(Boolean).join('\n');
  }

  /**
   * Generate React Native layout
   */
  generateRNLayout(layoutData, validatedStructure, components) {
    const layoutName = this.pascalCase(layoutData.name || 'Layout');
    const componentImports = components.map(comp => {
      const importInfo = this.getComponentImport(comp.name);
      if (importInfo.exists) {
        return `import { ${comp.name} } from '${importInfo.path}';`;
      }
      return `// TODO: Transform component '${comp.name}' first`;
    });

    return `import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
${componentImports.join('\n')}

interface ${layoutName}Props {
  style?: object;
}

export const ${layoutName}: React.FC<${layoutName}Props> = ({ style }) => {
  return (
    <View style={[styles.container, style]}>
${this.generateRNChildren(layoutData.children || [], 3)}
    </View>
  );
};

const styles = StyleSheet.create({
  container: ${JSON.stringify(this.convertToRNStyleObject(validatedStructure.css?.container || {}), null, 2)},
});

export default ${layoutName};
`;
  }

  /**
   * Generate React Native children
   */
  generateRNChildren(children, indent = 0) {
    const spaces = '  '.repeat(indent);

    return children.map(child => {
      if (child.componentRef || child.type === 'INSTANCE') {
        const name = child.componentRef?.name || child.name;
        return `${spaces}<${name} />`;
      } else if (child.type === 'FRAME' && child.children) {
        return `${spaces}<View>
${this.generateRNChildren(child.children, indent + 1)}
${spaces}</View>`;
      } else if (child.type === 'TEXT') {
        return `${spaces}<Text>${child.characters || child.name}</Text>`;
      }
      return '';
    }).filter(Boolean).join('\n');
  }

  /**
   * Generate Flutter layout
   */
  generateFlutterLayout(layoutData, validatedStructure, components) {
    const layoutName = this.pascalCase(layoutData.name || 'Layout');

    return `import 'package:flutter/material.dart';

class ${layoutName} extends StatelessWidget {
  const ${layoutName}({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return ${this.generateFlutterWidget(layoutData, validatedStructure)};
  }
}
`;
  }

  /**
   * Generate Flutter widget tree
   */
  generateFlutterWidget(node, validatedStructure) {
    const css = validatedStructure.css?.container || {};
    const isColumn = css['flex-direction'] === 'column';
    const gap = parseFloat(css.gap) || 0;

    const children = (node.children || []).map(child => {
      if (child.componentRef || child.type === 'INSTANCE') {
        const name = child.componentRef?.name || child.name;
        return `// ${name} component`;
      } else if (child.type === 'FRAME' && child.children) {
        return this.generateFlutterWidget(child, { css: {} });
      } else if (child.type === 'TEXT') {
        return `Text('${child.characters || child.name}')`;
      }
      return 'SizedBox()';
    }).join(',\n        ');

    if (isColumn) {
      return `Column(
      mainAxisAlignment: MainAxisAlignment.${this.flutterMainAxis(css['justify-content'])},
      crossAxisAlignment: CrossAxisAlignment.${this.flutterCrossAxis(css['align-items'])},
      children: [
        ${children}
      ],
    )`;
    } else {
      return `Row(
      mainAxisAlignment: MainAxisAlignment.${this.flutterMainAxis(css['justify-content'])},
      crossAxisAlignment: CrossAxisAlignment.${this.flutterCrossAxis(css['align-items'])},
      children: [
        ${children}
      ],
    )`;
    }
  }

  /**
   * Generate SwiftUI layout
   */
  generateSwiftUILayout(layoutData, validatedStructure, components) {
    const layoutName = this.pascalCase(layoutData.name || 'Layout');
    const css = validatedStructure.css?.container || {};
    const isColumn = css['flex-direction'] === 'column';
    const spacing = parseFloat(css.gap) || 0;

    const stackType = isColumn ? 'VStack' : 'HStack';
    const alignment = this.swiftUIAlignment(css['align-items']);

    return `import SwiftUI

struct ${layoutName}: View {
    var body: some View {
        ${stackType}(alignment: .${alignment}, spacing: ${spacing}) {
${this.generateSwiftUIChildren(layoutData.children || [], 3)}
        }
    }
}

struct ${layoutName}_Previews: PreviewProvider {
    static var previews: some View {
        ${layoutName}()
    }
}
`;
  }

  /**
   * Generate SwiftUI children
   */
  generateSwiftUIChildren(children, indent = 0) {
    const spaces = '    '.repeat(indent);

    return children.map(child => {
      if (child.componentRef || child.type === 'INSTANCE') {
        const name = child.componentRef?.name || child.name;
        return `${spaces}// ${name}()`;
      } else if (child.type === 'TEXT') {
        return `${spaces}Text("${child.characters || child.name}")`;
      }
      return '';
    }).filter(Boolean).join('\n');
  }

  /**
   * Generate Jetpack Compose layout
   */
  generateComposeLayout(layoutData, validatedStructure, components) {
    const layoutName = this.pascalCase(layoutData.name || 'Layout');
    const css = validatedStructure.css?.container || {};
    const isColumn = css['flex-direction'] === 'column';
    const spacing = parseFloat(css.gap) || 0;

    return `package com.example.ui.layouts

import androidx.compose.foundation.layout.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun ${layoutName}(
    modifier: Modifier = Modifier
) {
    ${isColumn ? 'Column' : 'Row'}(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(${spacing}.dp),
        horizontalAlignment = Alignment.${this.composeAlignment(css['align-items'])}
    ) {
${this.generateComposeChildren(layoutData.children || [], 2)}
    }
}
`;
  }

  /**
   * Generate Compose children
   */
  generateComposeChildren(children, indent = 0) {
    const spaces = '    '.repeat(indent);

    return children.map(child => {
      if (child.componentRef || child.type === 'INSTANCE') {
        const name = child.componentRef?.name || child.name;
        return `${spaces}// ${name}()`;
      } else if (child.type === 'TEXT') {
        return `${spaces}Text("${child.characters || child.name}")`;
      }
      return '';
    }).filter(Boolean).join('\n');
  }

  // ============================================================================
  // Style Converters
  // ============================================================================

  convertToReactStyles(css) {
    return { css };
  }

  convertToRNStyles(css) {
    return this.convertToRNStyleObject(css);
  }

  convertToRNStyleObject(css) {
    const rnStyles = {};

    if (css.display === 'flex') {
      rnStyles.flexDirection = css['flex-direction'] === 'column' ? 'column' : 'row';
    }
    if (css['justify-content']) {
      rnStyles.justifyContent = css['justify-content'];
    }
    if (css['align-items']) {
      rnStyles.alignItems = css['align-items'];
    }
    if (css.gap) {
      rnStyles.gap = parseFloat(css.gap);
    }
    if (css.padding) {
      const parts = css.padding.split(' ').map(p => parseFloat(p));
      if (parts.length === 4) {
        rnStyles.paddingTop = parts[0];
        rnStyles.paddingRight = parts[1];
        rnStyles.paddingBottom = parts[2];
        rnStyles.paddingLeft = parts[3];
      }
    }

    return rnStyles;
  }

  convertToVueStyles(css) {
    return css;
  }

  convertToSvelteStyles(css) {
    return css;
  }

  convertToAngularStyles(css) {
    return css;
  }

  convertToFlutterStyles(css) {
    return css;
  }

  convertToSwiftUIStyles(css) {
    return css;
  }

  convertToComposeStyles(css) {
    return css;
  }

  convertToWebComponentStyles(css) {
    return css;
  }

  // ============================================================================
  // Screenshot and Reference Generation
  // ============================================================================

  /**
   * Capture screenshot from Figma layout
   * Sprint 5.1: Integrates with Figma MCP for image capture
   * @param {Object} layoutData - Layout data with figmaId
   * @param {string} outputPath - Directory to save screenshot
   * @returns {Object} Screenshot result { path, status }
   */
  async captureScreenshot(layoutData, outputPath) {
    const figmaNodeId = layoutData.figmaId || layoutData.id || layoutData.nodeId;

    if (!figmaNodeId) {
      return {
        path: null,
        status: 'error',
        error: 'No Figma node ID found for screenshot capture'
      };
    }

    // Ensure output directory exists
    if (!fs.existsSync(outputPath)) {
      fs.mkdirSync(outputPath, { recursive: true });
    }

    const screenshotPath = path.join(outputPath, 'screenshot.png');

    // Check if Figma file key is available in config
    const figmaFileKey = this.config.figma?.fileKey || layoutData.figmaFileKey;

    if (!figmaFileKey) {
      // Return pending status - screenshot will be captured via MCP tool
      return {
        path: screenshotPath,
        status: 'pending_capture',
        figmaNodeId,
        message: 'Figma file key not found. Use mcp__figma-context__download_figma_images to capture.'
      };
    }

    // Store metadata for later capture
    const captureMetadata = {
      figmaFileKey,
      figmaNodeId,
      targetPath: screenshotPath,
      requestedAt: new Date().toISOString()
    };

    const metadataPath = path.join(outputPath, 'screenshot-capture.json');
    fs.writeFileSync(metadataPath, JSON.stringify(captureMetadata, null, 2));

    return {
      path: screenshotPath,
      status: 'metadata_saved',
      metadataPath,
      figmaFileKey,
      figmaNodeId,
      message: 'Screenshot metadata saved. Run capture command to download image.'
    };
  }

  /**
   * Generate reference HTML from layout JSON for validation
   * Sprint 5.2: Creates a standalone HTML file for visual comparison
   * @param {Object} layoutData - Layout JSON data
   * @returns {string} HTML string
   */
  generateReferenceHTML(layoutData) {
    const styles = this.extractFrameStyle(layoutData);
    const cssString = Object.entries(styles)
      .map(([k, v]) => `  ${this.camelToKebab(k)}: ${v};`)
      .join('\n');

    const layoutName = layoutData.name || 'Layout';
    const width = layoutData.width || layoutData.absoluteBoundingBox?.width || 'auto';
    const height = layoutData.height || layoutData.absoluteBoundingBox?.height || 'auto';

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${layoutName} - Reference Layout</title>
  <style>
    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #f5f5f5;
      padding: 20px;
    }
    .layout-container {
      width: ${typeof width === 'number' ? width + 'px' : width};
      height: ${typeof height === 'number' ? height + 'px' : height};
      background: #ffffff;
      margin: 0 auto;
${cssString}
    }
    .component-placeholder {
      border: 2px dashed #007bff;
      background: rgba(0, 123, 255, 0.1);
      display: flex;
      align-items: center;
      justify-content: center;
      color: #007bff;
      font-size: 12px;
      padding: 8px;
      border-radius: 4px;
    }
    .frame {
      border: 1px solid #ddd;
      background: rgba(0,0,0,0.02);
    }
    .text-node {
      font-size: 14px;
      color: #333;
    }
  </style>
</head>
<body>
  <div class="layout-container">
${this.generateChildrenHTML(layoutData.children || [], 2)}
  </div>
</body>
</html>`;
  }

  /**
   * Generate HTML for children nodes (recursive)
   * @param {Array} children - Child nodes
   * @param {number} indent - Indentation level
   * @returns {string} HTML string
   */
  generateChildrenHTML(children, indent = 0) {
    const spaces = '  '.repeat(indent);

    return children.map(child => {
      if (child.componentRef || child.type === 'INSTANCE') {
        const name = child.componentRef?.name || child.name;
        const width = child.width || child.absoluteBoundingBox?.width || 100;
        const height = child.height || child.absoluteBoundingBox?.height || 50;
        return `${spaces}<div class="component-placeholder" style="width: ${width}px; height: ${height}px;">
${spaces}  ${name}
${spaces}</div>`;
      } else if (child.type === 'FRAME' && child.children) {
        const frameStyle = this.extractFrameStyle(child);
        const styleAttr = Object.entries(frameStyle)
          .map(([k, v]) => `${this.camelToKebab(k)}: ${v}`)
          .join('; ');
        return `${spaces}<div class="frame" style="${styleAttr}">
${this.generateChildrenHTML(child.children, indent + 1)}
${spaces}</div>`;
      } else if (child.type === 'TEXT') {
        const text = child.characters || child.name || '';
        return `${spaces}<span class="text-node">${this.escapeHtml(text)}</span>`;
      } else if (child.type === 'RECTANGLE' || child.type === 'ELLIPSE') {
        const width = child.width || 100;
        const height = child.height || 100;
        const fills = child.fills || [];
        let bgColor = '#e0e0e0';
        if (fills.length > 0 && fills[0].type === 'SOLID' && fills[0].color) {
          const { r, g, b } = fills[0].color;
          bgColor = `rgb(${Math.round(r*255)}, ${Math.round(g*255)}, ${Math.round(b*255)})`;
        }
        const borderRadius = child.type === 'ELLIPSE' ? '50%' : (child.cornerRadius ? `${child.cornerRadius}px` : '0');
        return `${spaces}<div style="width: ${width}px; height: ${height}px; background: ${bgColor}; border-radius: ${borderRadius};"></div>`;
      }
      return '';
    }).filter(Boolean).join('\n');
  }

  /**
   * Escape HTML special characters
   */
  escapeHtml(str) {
    if (typeof str !== 'string') return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  /**
   * Save reference HTML to layout directory
   * @param {Object} layoutData - Layout data
   * @param {string} outputDir - Output directory
   * @returns {Object} Save result
   */
  saveReferenceHTML(layoutData, outputDir) {
    const html = this.generateReferenceHTML(layoutData);
    const htmlPath = path.join(outputDir, 'reference.html');

    if (!fs.existsSync(outputDir)) {
      fs.mkdirSync(outputDir, { recursive: true });
    }

    fs.writeFileSync(htmlPath, html);

    return {
      success: true,
      path: htmlPath,
      html
    };
  }

  // ============================================================================
  // Utility Methods
  // ============================================================================

  extractFrameStyle(node) {
    const style = {};

    if (node.layoutMode) {
      style.display = 'flex';
      style.flexDirection = node.layoutMode === 'VERTICAL' ? 'column' : 'row';
    }
    if (node.itemSpacing) {
      style.gap = `${node.itemSpacing}px`;
    }
    if (node.paddingTop || node.paddingRight || node.paddingBottom || node.paddingLeft) {
      style.padding = `${node.paddingTop || 0}px ${node.paddingRight || 0}px ${node.paddingBottom || 0}px ${node.paddingLeft || 0}px`;
    }

    return style;
  }

  cssObjectToString(css, indentLevel = 0) {
    const indent = '  '.repeat(indentLevel);
    return Object.entries(css)
      .map(([key, value]) => `${indent}${this.camelToKebab(key)}: ${value};`)
      .join('\n');
  }

  camelToKebab(str) {
    return str.replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase();
  }

  pascalCase(str) {
    return str
      .replace(/[^a-zA-Z0-9]/g, ' ')
      .split(' ')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
      .join('');
  }

  escapeJsx(str) {
    if (typeof str !== 'string') return '';
    return str.replace(/[{}<>]/g, c => ({ '{': '&#123;', '}': '&#125;', '<': '&lt;', '>': '&gt;' }[c]));
  }

  flutterMainAxis(justify) {
    const map = {
      'flex-start': 'start',
      'flex-end': 'end',
      'center': 'center',
      'space-between': 'spaceBetween',
      'space-around': 'spaceAround',
      'space-evenly': 'spaceEvenly'
    };
    return map[justify] || 'start';
  }

  flutterCrossAxis(align) {
    const map = {
      'flex-start': 'start',
      'flex-end': 'end',
      'center': 'center',
      'stretch': 'stretch'
    };
    return map[align] || 'start';
  }

  swiftUIAlignment(align) {
    const map = {
      'flex-start': 'leading',
      'flex-end': 'trailing',
      'center': 'center',
      'stretch': 'center'
    };
    return map[align] || 'center';
  }

  composeAlignment(align) {
    const map = {
      'flex-start': 'Start',
      'flex-end': 'End',
      'center': 'CenterHorizontally',
      'stretch': 'CenterHorizontally'
    };
    return map[align] || 'CenterHorizontally';
  }

  // ============================================================================
  // Main Transform Method
  // ============================================================================

  /**
   * Transform a layout to framework-specific code
   * @param {Object} layoutData - Layout JSON data
   * @param {Object} validatedStructure - Validated HTML structure with CSS
   * @param {Object} options - Transform options
   * @returns {Object} Transform result
   */
  async transform(layoutData, validatedStructure, options = {}) {
    const framework = options.framework || this.framework;
    const components = this.extractComponentRefs(layoutData);

    // Check which components are available
    const componentStatus = components.map(comp => ({
      ...comp,
      import: this.getComponentImport(comp.name)
    }));

    const missingComponents = componentStatus.filter(c => !c.import.exists);

    let code;
    switch (framework) {
      case 'react':
        code = this.generateReactLayout(layoutData, validatedStructure, components);
        break;
      case 'vue':
        code = this.generateVueLayout(layoutData, validatedStructure, components);
        break;
      case 'react-native':
        code = this.generateRNLayout(layoutData, validatedStructure, components);
        break;
      case 'flutter':
        code = this.generateFlutterLayout(layoutData, validatedStructure, components);
        break;
      case 'swiftui':
        code = this.generateSwiftUILayout(layoutData, validatedStructure, components);
        break;
      case 'jetpack-compose':
        code = this.generateComposeLayout(layoutData, validatedStructure, components);
        break;
      default:
        code = this.generateReactLayout(layoutData, validatedStructure, components);
    }

    // Determine output path
    const layoutName = this.pascalCase(layoutData.name || 'Layout');
    const ext = this.getFileExtension(framework);
    const outputDir = path.join(
      this.projectPath,
      '.design',
      'extracted-code',
      framework,
      'layouts'
    );
    const outputPath = path.join(outputDir, `${layoutName}${ext}`);

    // Write output
    if (!fs.existsSync(outputDir)) {
      fs.mkdirSync(outputDir, { recursive: true });
    }
    fs.writeFileSync(outputPath, code);

    // Update layout manifest with code-generated stage (stage 5)
    const safeName = layoutData.name
      ? layoutData.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
      : 'layout';

    try {
      // Check if layout exists in manifest, register if not
      const existingLayout = this.designStructure.getLayout(layoutData.name);
      if (!existingLayout) {
        this.designStructure.registerLayout({
          name: layoutData.name || 'Layout',
          safeName,
          dimensions: {
            width: layoutData.width || 0,
            height: layoutData.height || 0
          },
          stage: 5,
          status: 'code-generated'
        });
      } else {
        // Update existing layout to code-generated stage
        this.designStructure.updateLayoutStage(layoutData.name, 5, {
          outputPaths: {
            [framework]: outputPath
          }
        });
      }

      // Update barrel exports for layouts
      this.designStructure.updateBarrelExport(framework, 'layouts');
    } catch (manifestError) {
      // Don't fail the transform if manifest update fails
      console.warn(`Warning: Could not update layout manifest: ${manifestError.message}`);
    }

    return {
      success: true,
      framework,
      layoutName,
      outputPath,
      relativePath: `.design/extracted-code/${framework}/layouts/${layoutName}${ext}`,
      code,
      components: componentStatus,
      missingComponents,
      warnings: missingComponents.length > 0
        ? [`${missingComponents.length} component(s) not yet transformed: ${missingComponents.map(c => c.name).join(', ')}`]
        : []
    };
  }

  getFileExtension(framework) {
    const extensions = {
      'react': '.tsx',
      'vue': '.vue',
      'svelte': '.svelte',
      'angular': '.component.ts',
      'react-native': '.tsx',
      'flutter': '.dart',
      'swiftui': '.swift',
      'jetpack-compose': '.kt',
      'web-components': '.ts'
    };
    return extensions[framework] || '.tsx';
  }
}

module.exports = LayoutTransformer;
