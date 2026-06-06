/**
 * Layout Generator with Component Registry Integration
 *
 * Generates page layouts using existing transformed components from the registry
 * Ensures components are reused instead of recreated
 *
 * Universal system for all frameworks (React, Vue, Angular, Flutter, etc.)
 */

const fs = require('fs');
const path = require('path');
const ComponentRegistryManager = require('./component-registry-manager');

class LayoutGenerator {
  constructor(projectPath, framework, options = {}) {
    this.projectPath = projectPath;
    this.framework = framework;
    this.options = options;

    // Initialize registry manager
    this.registryManager = new ComponentRegistryManager(projectPath);
  }

  /**
   * Generate layout from Figma layout.json
   *
   * @param {string} layoutName - Layout name (e.g., "Examples-Pricing")
   * @param {Object} options - Generation options
   * @returns {Object} Generation result
   */
  async generateLayout(layoutName, options = {}) {
    console.log(`[LayoutGenerator] Generating layout: ${layoutName}`);

    // 1. Load layout JSON
    const layoutJson = this._loadLayoutJson(layoutName);
    if (!layoutJson) {
      throw new Error(`Layout JSON not found: ${layoutName}`);
    }

    console.log(`  → Layout loaded: ${layoutJson.name || layoutName}`);

    // 2. Extract component usage from layout
    const componentUsage = this._extractComponentUsage(layoutJson);
    console.log(`  → Found ${componentUsage.length} component instances`);

    // 3. Validate all components exist in registry
    const componentNames = [...new Set(componentUsage.map(c => c.name))];
    const validation = this.registryManager.validateComponents(componentNames, this.framework);

    console.log(`  → Registry validation:`);
    console.log(`     ✓ Valid: ${validation.valid.length}`);
    console.log(`     ⚠ Missing: ${validation.missing.length}`);
    console.log(`     ⚠ Invalid: ${validation.invalid.length}`);

    // 4. Handle missing components
    if (validation.missing.length > 0) {
      console.warn(`  ⚠️  Missing components from registry:`);
      validation.missing.forEach(c => {
        console.warn(`     - ${c.name}: ${c.message}`);
        console.warn(`       ${c.suggestion}`);
      });

      if (!options.allowMissing) {
        throw new Error(
          `Cannot generate layout: ${validation.missing.length} components not found in registry. ` +
          `Run transformations first or use allowMissing: true`
        );
      }
    }

    // 5. Handle invalid components
    if (validation.invalid.length > 0) {
      console.warn(`  ⚠️  Invalid components (transformation incomplete):`);
      validation.invalid.forEach(c => {
        console.warn(`     - ${c.name}: ${c.message}`);
        console.warn(`       ${c.suggestion}`);
      });

      if (!options.allowInvalid) {
        throw new Error(
          `Cannot generate layout: ${validation.invalid.length} components have incomplete transformations`
        );
      }
    }

    // 6. Generate layout code using registry components
    console.log(`  → Generating ${this.framework} layout code...`);
    const layoutCode = this.generateLayoutCode(
      layoutName,
      layoutJson,
      componentUsage,
      validation.valid
    );

    // 7. Write output file
    const outputPath = this._getLayoutOutputPath(layoutName);
    this._ensureDirectoryExists(path.dirname(outputPath));
    fs.writeFileSync(outputPath, layoutCode);

    console.log(`  ✓ Layout generated: ${outputPath}`);

    return {
      success: true,
      layoutName,
      outputPath,
      componentsUsed: validation.valid.length,
      componentsMissing: validation.missing.length,
      componentsInvalid: validation.invalid.length,
      validation
    };
  }

  /**
   * Generate framework-specific layout code
   * Override in framework-specific subclasses
   */
  generateLayoutCode(layoutName, layoutJson, componentUsage, validComponents) {
    throw new Error('generateLayoutCode() must be implemented by framework-specific generator');
  }

  /**
   * Extract component usage from layout JSON
   */
  _extractComponentUsage(layoutJson, parentPath = '') {
    const components = [];

    const traverse = (node, path = '', depth = 0) => {
      // Check if node is a component instance
      // Figma instances have type === 'INSTANCE' and may have mainComponent or mainComponentId
      if (node.type === 'INSTANCE' && (node.mainComponent || node.mainComponentId)) {
        const componentName = node.mainComponent?.name || node.name;

        // Only include top-level component instances (depth <= 2)
        // This avoids including nested instances within components
        if (depth <= 2) {
          components.push({
            name: componentName,
            instanceName: node.name,
            id: node.id,
            mainComponentId: node.mainComponentId,
            path,
            variants: this._extractVariants(node),
            position: { x: node.x || 0, y: node.y || 0 },
            size: { width: node.width, height: node.height }
          });
        }
      }

      // Traverse children
      if (node.children && Array.isArray(node.children)) {
        node.children.forEach((child, index) => {
          traverse(child, `${path}/${child.name || index}`, depth + 1);
        });
      }
    };

    traverse(layoutJson, '', 0);
    return components;
  }

  /**
   * Extract variant properties from Figma node
   */
  _extractVariants(node) {
    const variants = {};

    // Check for component properties (Figma variants)
    if (node.componentProperties) {
      for (const [key, value] of Object.entries(node.componentProperties)) {
        if (value.value !== undefined) {
          variants[key] = value.value;
        }
      }
    }

    return variants;
  }

  /**
   * Generate import statements for all valid components
   */
  generateImports(validComponents, fromPath) {
    const imports = this.registryManager.getImportStatements(
      validComponents.map(c => c.name),
      this.framework,
      fromPath
    );

    return imports.join('\n');
  }

  /**
   * Load layout JSON from .design/layouts/
   */
  _loadLayoutJson(layoutName) {
    const jsonPath = path.join(
      this.projectPath,
      '.design',
      'layouts',
      layoutName,
      'layout.json'
    );

    if (!fs.existsSync(jsonPath)) {
      return null;
    }

    return JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
  }

  /**
   * Get output path for generated layout
   */
  _getLayoutOutputPath(layoutName) {
    const extension = this.getFileExtension();

    return path.join(
      this.projectPath,
      'pages',
      `${layoutName.toLowerCase()}${extension}`
    );
  }

  /**
   * Get file extension for framework (override in subclass)
   */
  getFileExtension() {
    return '.tsx'; // Default for React/TypeScript
  }

  /**
   * Ensure directory exists
   */
  _ensureDirectoryExists(dir) {
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
  }

  /**
   * Get registry statistics
   */
  getRegistryStats() {
    return this.registryManager.getStatistics(this.framework);
  }
}

module.exports = LayoutGenerator;
