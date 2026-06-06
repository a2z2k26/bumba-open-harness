/**
 * Enhanced Component Transformer (Base Class)
 *
 * Framework-agnostic component transformation with full content extraction
 * All framework-specific transformers extend this base class
 *
 * Features:
 * - Deep content extraction from Figma JSON
 * - Nested component resolution and import generation
 * - Automatic dependency detection
 * - Complete prop mapping from Figma data
 * - Text, image, and style extraction
 */

const fs = require('fs');
const path = require('path');
const ComponentContentExtractor = require('./component-content-extractor');
const ComponentRegistryManager = require('./component-registry-manager');
const NamingNormalizer = require('./naming-normalizer');

class EnhancedComponentTransformer {
  constructor(projectPath, framework, options = {}) {
    this.projectPath = projectPath;
    this.framework = framework;
    this.options = {
      fullContent: true,
      resolveNestedComponents: true,
      generateImports: true,
      extractText: true,
      extractImages: true,
      extractVariants: true,
      ...options
    };

    // Load registry
    this.registryPath = path.join(projectPath, '.design', 'componentRegistry.json');
    this.registry = this._loadRegistry();

    // Initialize naming normalizer
    this.normalizer = new NamingNormalizer();

    // Initialize registry manager
    this.registryManager = new ComponentRegistryManager(projectPath);

    // Initialize content extractor
    this.extractor = new ComponentContentExtractor(projectPath, this.registry);
  }

  /**
   * Transform a single component with full content extraction
   *
   * @param {string} componentNameOrId - Component name (e.g., "header") or ID (e.g., "figma-plugin-...")
   * @param {Object} options - Transformation options
   * @returns {Object} Transformation result
   */
  async transformComponent(componentNameOrId, options = {}) {
    const opts = { ...this.options, ...options };

    console.log(`[${this.framework}] Transforming: ${componentNameOrId}`);

    // 0. Resolve component from registry
    const registryEntry = this._resolveComponent(componentNameOrId);

    if (!registryEntry) {
      throw new Error(`Component not found in registry: ${componentNameOrId}`);
    }

    const canonicalName = registryEntry.canonicalName;
    const figmaName = registryEntry.figmaName;

    // Validate canonical name for framework
    const nameValidation = this.normalizer.validateForFramework(canonicalName, this.framework);
    if (!nameValidation.valid) {
      throw new Error(
        `Canonical name "${canonicalName}" is invalid for ${this.framework}:\n  ${nameValidation.errors.join('\n  ')}`
      );
    }

    // 1. Check registry first - skip if already transformed
    // Reload registry to ensure we have latest state (important for cross-framework transforms)
    this.registryManager.registry = this.registryManager.loadRegistry();
    const registryCheck = this.registryManager.validateComponent(canonicalName, this.framework);

    if (registryCheck.valid && !opts.forceRetransform) {
      console.log(`  ✓ Component already exists in registry`);
      console.log(`  → Using existing: ${registryCheck.codePath}`);

      return {
        success: true,
        componentName: canonicalName,
        figmaName: figmaName,
        outputPath: registryCheck.codePath,
        skipped: true,
        reason: 'already-transformed',
        existingComponent: registryCheck.component
      };
    }

    if (registryCheck.reason === 'not_found') {
      console.log(`  → Component not in registry, proceeding with transformation...`);
    } else if (opts.forceRetransform) {
      console.log(`  → Force re-transform enabled, overriding registry check`);
    } else {
      console.log(`  → ${registryCheck.message}`);
      console.log(`  → Proceeding with transformation...`);
    }

    // 2. Load component JSON from registry path
    const componentJson = this._loadComponentFromRegistry(registryEntry);
    if (!componentJson) {
      throw new Error(`Component data not found: ${componentName} (${registryEntry.source?.rawDataPath || 'no path'})`);
    }

    // 2. Extract full content tree
    console.log(`  → Extracting content tree...`);
    const extractedContent = this.extractor.extractContent(componentJson, {
      depth: opts.depth || Infinity,
      includeText: opts.extractText,
      includeImages: opts.extractImages,
      includeVariants: opts.extractVariants,
      resolveNestedComponents: opts.resolveNestedComponents
    });

    // 3. Generate dependency report
    const dependencies = this.extractor.generateDependencyReport(extractedContent);

    // 4. Check for missing dependencies
    if (dependencies.missingTransformations.length > 0) {
      console.warn(`  ⚠️  Missing transformations:`);
      dependencies.missingTransformations.forEach(dep => {
        console.warn(`     - ${dep.name} (state: ${dep.state})`);
      });

      if (!opts.allowIncomplete) {
        throw new Error(
          `Cannot transform ${componentName}: ${dependencies.missingTransformations.length} nested components not yet transformed`
        );
      }
    }

    // 5. Generate framework-specific code
    console.log(`  → Generating ${this.framework} code...`);
    const code = this.generateCode(canonicalName, extractedContent, dependencies);

    // 6. Get framework-specific file name and write output file
    const fileName = this.normalizer.getFileName(canonicalName, this.framework);
    const outputPath = path.join(
      this.projectPath,
      'src',
      'design-system',
      'components',
      fileName
    );

    this._ensureDirectoryExists(path.dirname(outputPath));
    fs.writeFileSync(outputPath, code);

    console.log(`  ✓ Generated: ${outputPath}`);

    // 7. Update registry
    this._updateRegistry(canonicalName, outputPath, dependencies);

    return {
      success: true,
      componentName: canonicalName,
      figmaName: figmaName,
      outputPath,
      dependencies: {
        resolved: dependencies.resolved.length,
        missing: dependencies.missingTransformations.length,
        unresolved: dependencies.unresolved.length
      },
      extractedContent
    };
  }

  /**
   * Generate framework-specific code (MUST be overridden by subclasses)
   */
  generateCode(componentName, extractedContent, dependencies) {
    throw new Error('generateCode() must be implemented by framework-specific transformer');
  }

  /**
   * Generate imports for nested components
   */
  generateImports(dependencies) {
    if (!dependencies.resolved || dependencies.resolved.length === 0) {
      return '';
    }

    const imports = dependencies.resolved.map(dep => {
      // Framework-specific import format (override in subclass)
      return this.generateImport(dep.name, dep.importPath);
    });

    return imports.join('\n');
  }

  /**
   * Generate single import statement (override in subclass)
   */
  generateImport(componentName, importPath) {
    // Default ES6 import
    return `import { ${componentName} } from '${importPath}';`;
  }

  /**
   * Generate component props interface/type
   */
  generatePropsInterface(componentName, extractedContent) {
    // Override in subclass for framework-specific prop types
    return '';
  }

  /**
   * Generate component structure from extracted content
   */
  generateStructure(node, indent = 0) {
    // Override in subclass for framework-specific rendering
    return '';
  }

  /**
   * Generate styles from extracted styles
   */
  generateStyles(styles) {
    // Override in subclass for framework-specific styling
    return '';
  }

  /**
   * Convert PascalCase component name
   */
  toPascalCase(str) {
    return str
      .replace(/[-_\s]([a-z])/g, (_, letter) => letter.toUpperCase())
      .replace(/^[a-z]/, letter => letter.toUpperCase());
  }

  /**
   * Convert camelCase prop name
   */
  toCamelCase(str) {
    return str
      .replace(/[-_\s]([a-z])/g, (_, letter) => letter.toUpperCase())
      .replace(/^[A-Z]/, letter => letter.toLowerCase());
  }

  /**
   * Load component JSON from .design/components/
   */
  /**
   * Resolve component from registry by plugin ID, canonical name, Figma name, or node ID
   * Supports hybrid schema (v3.0.0 plugin IDs + canonical naming)
   *
   * @param {string} nameOrId - Plugin ID, canonical name, Figma name, or node ID
   * @returns {Object|null} Registry entry with canonical name and source
   */
  _resolveComponent(nameOrId) {
    const registry = this._loadRegistry();

    // Strategy 1: Try as plugin ID (v3.0.0 format: figma-plugin-{name}-{nodeId})
    if (registry.components[nameOrId]) {
      const component = registry.components[nameOrId];

      // Get canonical name (prefer canonicalName field, fallback to converting name)
      let canonicalName = component.canonicalName;
      if (!canonicalName && component.name) {
        try {
          canonicalName = this.normalizer.figmaToCanonical(component.name);
        } catch (error) {
          canonicalName = component.name;
        }
      }

      return {
        canonicalName,
        ...component
      };
    }

    // Strategy 2: Search by canonicalName, figmaName, figmaId, or nodeId
    for (const [key, component] of Object.entries(registry.components)) {
      let matched = false;

      // Match by canonical name (exact, case-sensitive)
      if (component.canonicalName === nameOrId) {
        matched = true;
      }

      // Match by Figma name (case-insensitive)
      if (!matched && component.figmaName && component.figmaName.toLowerCase() === nameOrId.toLowerCase()) {
        matched = true;
      }

      // Match by old name field (v3.0.0 compatibility)
      if (!matched && component.name && component.name.toLowerCase() === nameOrId.toLowerCase()) {
        matched = true;
      }

      // Match by Figma node ID
      if (!matched && (component.figmaId === nameOrId || component.source?.nodeId === nameOrId)) {
        matched = true;
      }

      // Match by plugin ID in component.id field
      if (!matched && component.id === nameOrId) {
        matched = true;
      }

      // If matched, return with proper canonical name
      if (matched) {
        let canonicalName = component.canonicalName;
        if (!canonicalName && component.name) {
          try {
            canonicalName = this.normalizer.figmaToCanonical(component.name);
          } catch (error) {
            canonicalName = component.name;
          }
        }

        return {
          canonicalName,
          ...component
        };
      }
    }

    // Strategy 3: Try normalizing input to canonical name and search
    try {
      const normalizedCanonical = this.normalizer.figmaToCanonical(nameOrId);

      // Search for matching canonical name
      for (const [key, component] of Object.entries(registry.components)) {
        if (component.canonicalName === normalizedCanonical) {
          return {
            canonicalName: component.canonicalName,
            ...component
          };
        }
      }
    } catch (error) {
      // Normalization failed, continue
    }

    return null;
  }

  /**
   * Load component JSON from registry entry
   * @param {Object} registryEntry - Registry entry with source.rawDataPath
   * @returns {Object|null} Component JSON data
   */
  _loadComponentFromRegistry(registryEntry) {
    if (!registryEntry.source || !registryEntry.source.rawDataPath) {
      return null;
    }

    const jsonPath = path.join(this.projectPath, registryEntry.source.rawDataPath);

    if (!fs.existsSync(jsonPath)) {
      return null;
    }

    return JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
  }

  /**
   * Legacy: Load component JSON by name
   * @deprecated Use _loadComponentFromRegistry instead
   */
  _loadComponentJson(componentName) {
    const jsonPath = path.join(
      this.projectPath,
      '.design',
      'components',
      `${componentName}.json`
    );

    if (!fs.existsSync(jsonPath)) {
      return null;
    }

    return JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
  }

  /**
   * Load component registry
   */
  _loadRegistry() {
    if (!fs.existsSync(this.registryPath)) {
      return { components: {} };
    }

    return JSON.parse(fs.readFileSync(this.registryPath, 'utf8'));
  }

  /**
   * Get output path for transformed component
   */
  _getOutputPath(componentName) {
    const pascalName = this.toPascalCase(componentName);
    const extension = this.getFileExtension();

    return path.join(
      this.projectPath,
      'src',
      'design-system',
      'components',
      `${pascalName}${extension}`
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
   * Update component registry with transformation result
   * Supports hybrid schema (updates both v3.0.0 and new fields)
   */
  _updateRegistry(canonicalName, outputPath, dependencies) {
    const registry = this._loadRegistry();

    // Find registry entry by canonical name
    let registryEntry = null;
    let entryKey = null;

    // Search for entry by canonical name
    for (const [key, component] of Object.entries(registry.components)) {
      if (component.canonicalName === canonicalName) {
        registryEntry = component;
        entryKey = key;
        break;
      }
    }

    if (!registryEntry) {
      console.warn(`  ⚠️  Component not found in registry: ${canonicalName}`);
      return;
    }

    const relativeCodePath = outputPath.replace(this.projectPath + '/', '');
    const timestamp = new Date().toISOString();

    // Update v3.0.0 transformation field (for plugin compatibility)
    // Only update if this is the first transformation OR if it matches current framework
    if (!registryEntry.transformation || !registryEntry.transformation.state || registryEntry.transformation.framework === this.framework) {
      registryEntry.transformation = {
        state: 'code-generated',
        framework: this.framework,
        transformedAt: timestamp,
        codePath: relativeCodePath,
        storyPath: null, // Set by subclasses if generated
        fullContent: true,
        dependencies: {
          resolved: dependencies.resolved.map(d => d.name),
          missing: dependencies.missingTransformations.map(d => d.name)
        }
      };
    }

    // Update new multi-framework transformations field
    if (!registryEntry.transformations) {
      registryEntry.transformations = {};
    }

    registryEntry.transformations[this.framework] = {
      state: 'code-generated',
      transformedAt: timestamp,
      codePath: relativeCodePath,
      storyPath: null, // Set by subclasses if generated
      fullContent: true,
      dependencies: {
        resolved: dependencies.resolved.map(d => d.name),
        missing: dependencies.missingTransformations.map(d => d.name)
      }
    };

    // Save registry
    fs.writeFileSync(this.registryPath, JSON.stringify(registry, null, 2));
  }
}

module.exports = EnhancedComponentTransformer;
