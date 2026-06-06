/**
 * Component Registry Manager
 *
 * Universal registry system to prevent duplicate component transformations
 * and ensure consistent component reuse across all frameworks
 *
 * Used by ALL design-transform-* skills (React, Vue, Angular, Flutter, etc.)
 */

const fs = require('fs');
const path = require('path');

class ComponentRegistryManager {
  constructor(projectPath) {
    this.projectPath = projectPath;
    this.registryPath = path.join(projectPath, '.design/componentRegistry.json');
    this.registry = this.loadRegistry();
  }

  /**
   * Load registry from disk
   */
  loadRegistry() {
    if (!fs.existsSync(this.registryPath)) {
      return this.createEmptyRegistry();
    }

    try {
      const content = fs.readFileSync(this.registryPath, 'utf8');
      return JSON.parse(content);
    } catch (error) {
      console.warn(`Failed to load registry: ${error.message}`);
      return this.createEmptyRegistry();
    }
  }

  /**
   * Create empty registry structure
   */
  createEmptyRegistry() {
    return {
      version: '3.0.0',
      metadata: {
        schemaVersion: '3.0.0',
        lastUpdated: new Date().toISOString(),
        createdAt: new Date().toISOString()
      },
      components: {}
    };
  }

  /**
   * Save registry to disk
   */
  saveRegistry() {
    this.registry.metadata.lastUpdated = new Date().toISOString();

    const dir = path.dirname(this.registryPath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    fs.writeFileSync(this.registryPath, JSON.stringify(this.registry, null, 2));
  }

  /**
   * Check if component exists in registry
   *
   * @param {string} componentName - Canonical component name (e.g., "Button", "AiChatBox")
   * @param {string} framework - Framework (e.g., "react", "vue", "angular")
   * @returns {Object|null} Component entry or null if not found
   */
  findComponent(componentName, framework = null) {
    // Hybrid schema support: Keys are plugin IDs, need to search by canonical name
    const normalizedName = this.normalizeComponentName(componentName);

    for (const [key, comp] of Object.entries(this.registry.components)) {

      // Match by canonical name (new schema)
      if (comp.canonicalName && this.normalizeComponentName(comp.canonicalName) === normalizedName) {
        if (framework) {
          if (this.isTransformedForFramework(comp, framework)) {
            return comp;
          }
        } else {
          return comp;
        }
      }

      // Match by figmaName
      if (comp.figmaName && this.normalizeComponentName(comp.figmaName) === normalizedName) {
        if (framework) {
          if (this.isTransformedForFramework(comp, framework)) {
            return comp;
          }
        } else {
          return comp;
        }
      }

      // Old schema compatibility
      if (comp.name && this.normalizeComponentName(comp.name) === normalizedName) {
        if (framework && comp.transformation && comp.transformation.framework !== framework) {
          continue;
        }

        if (this.isTransformed(comp)) {
          return comp;
        }
      }
    }

    return null;
  }

  /**
   * Check if component is already transformed for a specific framework (new schema)
   *
   * @param {Object} component - Component entry
   * @param {string} framework - Framework name
   * @returns {boolean}
   */
  isTransformedForFramework(component, framework) {
    if (!component.transformations || !component.transformations[framework]) {
      return false;
    }

    const transformation = component.transformations[framework];
    const validStates = ['code-generated', 'verified', 'production'];
    return validStates.includes(transformation.state);
  }

  /**
   * Check if component is already transformed (old schema compatibility)
   *
   * @param {Object} component - Component entry
   * @returns {boolean}
   */
  isTransformed(component) {
    // New schema: check if ANY framework is transformed
    if (component.transformations) {
      for (const fw of Object.values(component.transformations)) {
        if (fw && fw.state) {
          const validStates = ['code-generated', 'verified', 'production'];
          if (validStates.includes(fw.state)) {
            return true;
          }
        }
      }
      return false;
    }

    // Old schema
    if (!component.transformation) return false;

    const validStates = ['code-generated', 'verified', 'production'];
    return validStates.includes(component.transformation.state);
  }

  /**
   * Get component code path
   *
   * @param {string} componentName - Component name
   * @param {string} framework - Framework
   * @returns {string|null} Path to component code or null
   */
  getComponentPath(componentName, framework = null) {
    const component = this.findComponent(componentName, framework);

    if (!component) {
      return null;
    }

    let codePath;

    // New schema: Get framework-specific path
    if (component.transformations && framework && component.transformations[framework]) {
      codePath = component.transformations[framework].codePath;
    }
    // Old schema
    else if (component.transformation && component.transformation.codePath) {
      codePath = component.transformation.codePath;
    }
    else {
      return null;
    }

    // Return absolute path
    const absolutePath = path.join(this.projectPath, codePath);

    // Verify file exists
    if (fs.existsSync(absolutePath)) {
      return absolutePath;
    }

    return null;
  }

  /**
   * Get component story path
   *
   * @param {string} componentName - Component name
   * @param {string} framework - Framework
   * @returns {string|null} Path to story or null
   */
  getStoryPath(componentName, framework = null) {
    const component = this.findComponent(componentName, framework);

    if (!component) {
      return null;
    }

    let storyPathRel;

    // New schema: Get framework-specific path
    if (component.transformations && framework && component.transformations[framework]) {
      storyPathRel = component.transformations[framework].storyPath;
    }
    // Old schema
    else if (component.transformation && component.transformation.storyPath) {
      storyPathRel = component.transformation.storyPath;
    }

    if (!storyPathRel) {
      return null;
    }

    const storyPath = path.join(this.projectPath, storyPathRel);

    if (fs.existsSync(storyPath)) {
      return storyPath;
    }

    return null;
  }

  /**
   * Get all transformed components for a framework
   *
   * @param {string} framework - Framework (optional)
   * @returns {Array} Array of transformed components
   */
  getTransformedComponents(framework = null) {
    const transformed = [];

    for (const [id, component] of Object.entries(this.registry.components)) {
      if (this.isTransformed(component)) {
        if (!framework || component.transformation.framework === framework) {
          transformed.push({
            id,
            name: component.name,
            path: component.transformation.codePath,
            storyPath: component.transformation.storyPath,
            framework: component.transformation.framework
          });
        }
      }
    }

    return transformed;
  }

  /**
   * Get missing components (needed but not transformed)
   *
   * @param {Array} requiredComponents - List of component names needed
   * @param {string} framework - Target framework
   * @returns {Array} List of missing component names
   */
  getMissingComponents(requiredComponents, framework) {
    const missing = [];

    for (const componentName of requiredComponents) {
      const component = this.findComponent(componentName, framework);

      if (!component) {
        missing.push(componentName);
      }
    }

    return missing;
  }

  /**
   * Get component import statement
   *
   * @param {string} componentName - Component name
   * @param {string} framework - Framework
   * @param {string} fromPath - Path importing from (for relative imports)
   * @returns {string|null} Import statement or null
   */
  getImportStatement(componentName, framework, fromPath = null) {
    const component = this.findComponent(componentName, framework);

    if (!component) {
      return null;
    }

    let componentPath;

    // New schema: Get framework-specific path
    if (component.transformations && framework && component.transformations[framework]) {
      componentPath = component.transformations[framework].codePath;
    }
    // Old schema
    else if (component.transformation && component.transformation.codePath) {
      componentPath = component.transformation.codePath;
    }

    if (!componentPath) {
      return null;
    }

    // Use canonicalName (already PascalCase) or fallback to converting name/figmaName
    const pascalName = component.canonicalName || this.toPascalCase(component.name || component.figmaName);

    // Generate relative import path if fromPath provided
    if (fromPath) {
      const fromDir = path.dirname(fromPath);
      const toPath = path.join(this.projectPath, componentPath);
      const relativePath = path.relative(fromDir, toPath).replace(/\.tsx?$/, '');

      // Ensure it starts with ./
      const importPath = relativePath.startsWith('.') ? relativePath : `./${relativePath}`;

      return `import { ${pascalName} } from '${importPath}';`;
    }

    // Absolute import from project root
    const importPath = componentPath.replace(/\.tsx?$/, '').replace(/^src\//, '../');
    return `import { ${pascalName} } from '${importPath}';`;
  }

  /**
   * Get all import statements for multiple components
   *
   * @param {Array} componentNames - List of component names
   * @param {string} framework - Framework
   * @param {string} fromPath - Path importing from
   * @returns {Array} Array of import statements
   */
  getImportStatements(componentNames, framework, fromPath = null) {
    const imports = [];
    const seen = new Set();

    for (const componentName of componentNames) {
      const normalized = this.normalizeComponentName(componentName);

      if (seen.has(normalized)) {
        continue;
      }

      const importStmt = this.getImportStatement(componentName, framework, fromPath);

      if (importStmt) {
        imports.push(importStmt);
        seen.add(normalized);
      }
    }

    return imports;
  }

  /**
   * Generate statistics about component coverage
   *
   * @param {string} framework - Framework (optional)
   * @returns {Object} Statistics
   */
  getStatistics(framework = null) {
    const stats = {
      total: 0,
      transformed: 0,
      pending: 0,
      byFramework: {},
      byCategory: {}
    };

    for (const [id, component] of Object.entries(this.registry.components)) {
      stats.total++;

      // Framework filter
      if (framework && component.transformation.framework !== framework) {
        continue;
      }

      // Count by state
      if (this.isTransformed(component)) {
        stats.transformed++;
      } else {
        stats.pending++;
      }

      // Count by framework
      const fw = component.transformation.framework || 'unknown';
      stats.byFramework[fw] = (stats.byFramework[fw] || 0) + 1;

      // Count by category
      const cat = component.category || 'uncategorized';
      stats.byCategory[cat] = (stats.byCategory[cat] || 0) + 1;
    }

    return stats;
  }

  /**
   * Normalize component name for comparison
   */
  normalizeComponentName(name) {
    return name.toLowerCase().replace(/[^a-z0-9]/g, '');
  }

  /**
   * Convert to PascalCase
   */
  toPascalCase(str) {
    return str
      .replace(/[^a-zA-Z0-9]+/g, ' ')
      .split(' ')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
      .join('');
  }

  /**
   * Validate that component exists and is usable
   *
   * @param {string} componentName - Component name
   * @param {string} framework - Framework
   * @returns {Object} Validation result
   */
  validateComponent(componentName, framework) {
    const component = this.findComponent(componentName, framework);

    if (!component) {
      return {
        valid: false,
        reason: 'not_found',
        message: `Component "${componentName}" not found in registry`,
        suggestion: `Run /design-transform-${framework} to create it`
      };
    }

    // Check if transformed for this framework (new schema)
    if (component.transformations) {
      if (!this.isTransformedForFramework(component, framework)) {
        const transformation = component.transformations[framework];
        return {
          valid: false,
          reason: 'not_transformed',
          message: `Component "${componentName}" exists but is not transformed for ${framework}`,
          state: transformation ? transformation.state : null,
          suggestion: `Run /design-transform-${framework} ${componentName}`
        };
      }
    }
    // Old schema
    else if (!this.isTransformed(component)) {
      return {
        valid: false,
        reason: 'not_transformed',
        message: `Component "${componentName}" exists but is not transformed`,
        state: component.transformation ? component.transformation.state : null,
        suggestion: `Complete transformation for ${componentName}`
      };
    }

    const codePath = this.getComponentPath(componentName, framework);
    if (!codePath) {
      let expectedPath;
      if (component.transformations && component.transformations[framework]) {
        expectedPath = component.transformations[framework].codePath;
      } else if (component.transformation) {
        expectedPath = component.transformation.codePath;
      }

      return {
        valid: false,
        reason: 'file_missing',
        message: `Component "${componentName}" is registered but code file is missing`,
        expectedPath,
        suggestion: `Re-run transformation for ${componentName}`
      };
    }

    return {
      valid: true,
      component,
      codePath,
      storyPath: this.getStoryPath(componentName, framework),
      import: this.getImportStatement(componentName, framework)
    };
  }

  /**
   * Bulk validate multiple components
   *
   * @param {Array} componentNames - List of component names
   * @param {string} framework - Framework
   * @returns {Object} Validation results
   */
  validateComponents(componentNames, framework) {
    const results = {
      valid: [],
      invalid: [],
      missing: []
    };

    for (const name of componentNames) {
      const validation = this.validateComponent(name, framework);

      if (validation.valid) {
        results.valid.push({ name, ...validation });
      } else if (validation.reason === 'not_found') {
        results.missing.push({ name, ...validation });
      } else {
        results.invalid.push({ name, ...validation });
      }
    }

    return results;
  }
}

module.exports = ComponentRegistryManager;
