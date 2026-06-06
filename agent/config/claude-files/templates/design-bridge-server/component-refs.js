/**
 * Component Reference System
 * Enables cross-source component references
 */

const fs = require('fs');
const path = require('path');

// Reference format patterns
const REF_PATTERNS = {
  // Full reference: @ref:ComponentName
  full: /^@ref:([A-Za-z][A-Za-z0-9]*(?:\/[A-Za-z][A-Za-z0-9]*)?)$/,
  // With props: @ref:ComponentName{prop1:"value", prop2:123}
  withProps: /^@ref:([A-Za-z][A-Za-z0-9]*(?:\/[A-Za-z][A-Za-z0-9]*)?)\{(.+)\}$/,
  // Inline reference in structure
  inline: /\$\{ref:([A-Za-z][A-Za-z0-9]*(?:\/[A-Za-z][A-Za-z0-9]*)?)\}/g
};

class ComponentRefResolver {
  constructor(registryPath) {
    this.registryPath = registryPath;
    this.componentsCache = null;
    this.resolvedRefs = new Map();
  }

  /**
   * Load all components from registry
   */
  loadComponents() {
    if (this.componentsCache) return this.componentsCache;

    const registryFile = path.join(this.registryPath, 'components', 'registry.json');
    if (!fs.existsSync(registryFile)) {
      this.componentsCache = {};
      return this.componentsCache;
    }

    try {
      const registry = JSON.parse(fs.readFileSync(registryFile, 'utf-8'));
      this.componentsCache = registry.components || {};
    } catch (err) {
      console.error('[component-refs] Failed to load registry:', err.message);
      this.componentsCache = {};
    }

    return this.componentsCache;
  }

  /**
   * Find component by name (case-insensitive, supports path)
   * @param {string} refName - Component name or path
   * @returns {object|null} - Component data or null
   */
  findComponent(refName) {
    const components = this.loadComponents();
    const lowerName = refName.toLowerCase();

    // Try exact match first
    for (const [id, component] of Object.entries(components)) {
      if (component.name === refName || component.name.toLowerCase() === lowerName) {
        return { id, ...component };
      }
    }

    // Try path match (Category/ComponentName)
    if (refName.includes('/')) {
      const [category, name] = refName.split('/');
      for (const [id, component] of Object.entries(components)) {
        if (
          component.category?.toLowerCase() === category.toLowerCase() &&
          component.name.toLowerCase() === name.toLowerCase()
        ) {
          return { id, ...component };
        }
      }
    }

    return null;
  }

  /**
   * Parse a reference string
   * @param {string} refString - Reference string to parse
   * @returns {object} - { name, props, valid }
   */
  parseReference(refString) {
    // Check full reference pattern
    let match = refString.match(REF_PATTERNS.full);
    if (match) {
      return { name: match[1], props: {}, valid: true };
    }

    // Check with props pattern
    match = refString.match(REF_PATTERNS.withProps);
    if (match) {
      try {
        // Parse props (JSON-like syntax)
        const propsStr = `{${match[2]}}`;
        const props = JSON.parse(propsStr.replace(/'/g, '"'));
        return { name: match[1], props, valid: true };
      } catch (err) {
        return { name: match[1], props: {}, valid: false, error: 'Invalid props syntax' };
      }
    }

    return { name: null, props: {}, valid: false, error: 'Invalid reference format' };
  }

  /**
   * Resolve a component reference
   * @param {string} refString - Reference string
   * @returns {object} - Resolution result
   */
  resolveReference(refString) {
    // Check cache
    if (this.resolvedRefs.has(refString)) {
      return this.resolvedRefs.get(refString);
    }

    const parsed = this.parseReference(refString);
    if (!parsed.valid) {
      const result = {
        resolved: false,
        error: parsed.error,
        original: refString
      };
      this.resolvedRefs.set(refString, result);
      return result;
    }

    const component = this.findComponent(parsed.name);
    if (!component) {
      const result = {
        resolved: false,
        error: `Component not found: ${parsed.name}`,
        original: refString,
        suggestions: this.suggestComponents(parsed.name)
      };
      this.resolvedRefs.set(refString, result);
      return result;
    }

    const result = {
      resolved: true,
      component: {
        id: component.id,
        name: component.name,
        category: component.category,
        source: component.source,
        path: component.paths?.codeOutput
      },
      props: parsed.props,
      original: refString
    };

    this.resolvedRefs.set(refString, result);
    return result;
  }

  /**
   * Suggest similar component names
   */
  suggestComponents(name) {
    const components = this.loadComponents();
    const lowerName = name.toLowerCase();
    const suggestions = [];

    for (const component of Object.values(components)) {
      if (
        component.name.toLowerCase().includes(lowerName) ||
        lowerName.includes(component.name.toLowerCase())
      ) {
        suggestions.push(component.name);
      }
    }

    return suggestions.slice(0, 5);
  }

  /**
   * Process structure and resolve all component refs
   * @param {object} structure - Component structure with potential refs
   * @returns {object} - { structure, imports, errors }
   */
  processStructure(structure) {
    const imports = new Set();
    const errors = [];

    const processNode = (node) => {
      if (!node || typeof node !== 'object') return node;

      // Check if node is a component reference
      if (node.type === 'component-ref' && node.ref) {
        const resolution = this.resolveReference(`@ref:${node.ref}`);

        if (resolution.resolved) {
          imports.add(JSON.stringify({
            name: resolution.component.name,
            path: resolution.component.path
          }));

          return {
            type: 'component',
            name: resolution.component.name,
            importFrom: resolution.component.path,
            props: { ...resolution.props, ...node.props }
          };
        } else {
          errors.push({
            ref: node.ref,
            error: resolution.error,
            suggestions: resolution.suggestions
          });

          // Return placeholder
          return {
            type: 'placeholder',
            name: node.ref,
            error: resolution.error
          };
        }
      }

      // Process children
      if (node.children && Array.isArray(node.children)) {
        node.children = node.children.map(child => processNode(child));
      }

      // Process other object properties
      for (const [key, value] of Object.entries(node)) {
        if (typeof value === 'object' && value !== null) {
          node[key] = processNode(value);
        }
      }

      return node;
    };

    const processedStructure = processNode(JSON.parse(JSON.stringify(structure)));

    return {
      structure: processedStructure,
      imports: Array.from(imports).map(s => JSON.parse(s)),
      errors
    };
  }

  /**
   * Generate import statements for resolved references
   * @param {Array} imports - Array of { name, path } objects
   * @param {string} framework - Target framework (react, vue, etc.)
   * @returns {string} - Import statements
   */
  generateImports(imports, framework = 'react') {
    if (imports.length === 0) return '';

    const statements = [];

    // Group by path
    const byPath = new Map();
    for (const imp of imports) {
      if (!byPath.has(imp.path)) {
        byPath.set(imp.path, []);
      }
      byPath.get(imp.path).push(imp.name);
    }

    for (const [importPath, names] of byPath) {
      switch (framework) {
        case 'react':
          statements.push(`import { ${names.join(', ')} } from '${importPath}';`);
          break;
        case 'vue':
          statements.push(`import { ${names.join(', ')} } from '${importPath}';`);
          break;
        case 'svelte':
          statements.push(`import { ${names.join(', ')} } from '${importPath}';`);
          break;
        case 'angular':
          // Angular uses modules
          statements.push(`import { ${names.join(', ')} } from '${importPath}';`);
          break;
        default:
          statements.push(`import { ${names.join(', ')} } from '${importPath}';`);
      }
    }

    return statements.join('\n');
  }

  /**
   * Get all component dependencies (references used by a component)
   * @param {string} componentId - Component ID
   * @returns {Array} - Array of referenced component IDs
   */
  getComponentDependencies(componentId) {
    const components = this.loadComponents();
    const component = components[componentId];

    if (!component || !component.structure) {
      return [];
    }

    const dependencies = new Set();

    const findRefs = (node) => {
      if (!node || typeof node !== 'object') return;

      if (node.type === 'component-ref' && node.ref) {
        const found = this.findComponent(node.ref);
        if (found) {
          dependencies.add(found.id);
        }
      }

      if (node.children && Array.isArray(node.children)) {
        node.children.forEach(findRefs);
      }

      for (const value of Object.values(node)) {
        if (typeof value === 'object' && value !== null) {
          findRefs(value);
        }
      }
    };

    findRefs(component.structure);

    return Array.from(dependencies);
  }

  /**
   * Get all components that depend on a given component
   * @param {string} componentId - Component ID
   * @returns {Array} - Array of component IDs that use this component
   */
  getComponentDependents(componentId) {
    const components = this.loadComponents();
    const component = components[componentId];

    if (!component) return [];

    const dependents = [];

    for (const [id, comp] of Object.entries(components)) {
      if (id === componentId) continue;

      const deps = this.getComponentDependencies(id);
      if (deps.includes(componentId)) {
        dependents.push(id);
      }
    }

    return dependents;
  }

  /**
   * List all components in registry
   */
  listComponents() {
    const components = this.loadComponents();
    return Object.entries(components).map(([id, component]) => ({
      id,
      name: component.name,
      category: component.category,
      source: component.source?.type
    }));
  }

  /**
   * Get component by ID
   */
  getComponentById(componentId) {
    const components = this.loadComponents();
    return components[componentId] || null;
  }

  /**
   * Clear resolution cache
   */
  clearCache() {
    this.componentsCache = null;
    this.resolvedRefs.clear();
  }
}

module.exports = { ComponentRefResolver, REF_PATTERNS };
