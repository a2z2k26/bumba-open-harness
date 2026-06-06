/**
 * story-generator.js
 * Core story generation engine for Design Bridge
 *
 * Combines:
 * - Extracted BUMBA story generation logic (story-generator-base.js)
 * - Template-based file generation
 * - Framework-specific adaptations
 *
 * Enhanced with P1-P5 gap fixes:
 * - P1: StoryVariants integrated into main generateStoryFile flow
 * - P2: Auto-generates variants from enum props
 * - P3: Figma URL passed through from componentRegistry
 * - P4: Uses componentRegistry for path resolution
 * - P5: Props validation before story generation
 */

const fs = require('fs');
const path = require('path');
const { StoryGeneratorBase } = require('./story-generator-base');
const { StoryVariants } = require('./story-variants');
const { FileConflictDetector, ConflictType } = require('./file-conflict-detector');

/**
 * Template file extensions by framework
 */
const TEMPLATE_EXTENSIONS = {
  // Web frameworks
  'react': '.tsx',
  'vue': '.ts',
  'angular': '.ts',
  'svelte': '.ts',
  // Mobile frameworks
  'react-native': '.tsx',
  'flutter': '.dart',
  'swiftui': '.swift',
  'jetpack-compose': '.kt',
};

/**
 * Story output file extensions by framework
 */
const STORY_EXTENSIONS = {
  // Web frameworks
  'react': '.stories.tsx',
  'vue': '.stories.ts',
  'angular': '.stories.ts',
  'svelte': '.stories.ts',
  // Mobile frameworks
  'react-native': '.stories.tsx',
  'flutter': '_story.dart',
  'swiftui': '_Previews.swift',
  'jetpack-compose': 'Previews.kt',
};

class StoryGenerator extends StoryGeneratorBase {
  constructor(options = {}) {
    super(options);

    this.templateCache = new Map();
    this.templateExtensions = TEMPLATE_EXTENSIONS;
    this.storyExtensions = STORY_EXTENSIONS;

    // Sprint 5.1: Advanced story variants support
    this.variantsGenerator = new StoryVariants(options.variants || {});

    // Sprint 6.4: File conflict detection
    this.conflictDetector = options.conflictDetector || null;
    this.conflictStrategy = options.conflictStrategy || 'prompt'; // 'prompt', 'overwrite', 'skip'

    // P3 & P4: Component registry reference
    this.componentRegistry = null;
    this.projectPath = options.projectPath || null;

    // P1: Enable rich variants by default
    this.enableRichVariants = options.enableRichVariants !== false;

    // P2: Auto-generate variants from enum props
    this.autoEnumVariants = options.autoEnumVariants !== false;
  }

  // ============================================================
  // P4: Component Registry Integration
  // ============================================================

  /**
   * Load component registry from project
   * @param {string} projectPath - Path to project root
   * @returns {Object|null} Component registry or null
   */
  loadComponentRegistry(projectPath) {
    const registryPath = path.join(projectPath, '.design/componentRegistry.json');

    if (!fs.existsSync(registryPath)) {
      return null;
    }

    try {
      this.componentRegistry = JSON.parse(fs.readFileSync(registryPath, 'utf8'));
      this.projectPath = projectPath;
      return this.componentRegistry;
    } catch (error) {
      console.warn('Failed to load component registry:', error.message);
      return null;
    }
  }

  /**
   * Lookup component in registry by name
   * @param {string} componentName - Component name
   * @returns {Object|null} Registry entry or null
   */
  lookupComponent(componentName) {
    if (!this.componentRegistry?.components) return null;

    return this.componentRegistry.components.find(
      c => c.name === componentName || c.id === componentName
    ) || null;
  }

  /**
   * Get component path from registry (P4)
   * @param {string} componentName - Component name
   * @param {string} framework - Target framework
   * @returns {string|null} Component path or null
   */
  getComponentPath(componentName, framework) {
    const entry = this.lookupComponent(componentName);
    if (!entry?.outputPaths?.[framework]) return null;

    return path.join(this.projectPath, entry.outputPaths[framework]);
  }

  /**
   * Get Figma URL from registry (P3)
   * @param {string} componentName - Component name
   * @returns {string} Figma URL or empty string
   */
  getFigmaUrl(componentName) {
    const entry = this.lookupComponent(componentName);
    return entry?.figmaUrl || entry?.metadata?.figmaUrl || '';
  }

  // ============================================================
  // P5: Props Validation
  // ============================================================

  /**
   * Validate props before story generation
   * @param {Object} props - Component props
   * @returns {Object} Validation result with issues and sanitized props
   */
  validateProps(props) {
    const issues = [];
    const sanitizedProps = {};

    if (!props || typeof props !== 'object') {
      return { valid: false, issues: ['Props must be an object'], sanitizedProps: {} };
    }

    Object.entries(props).forEach(([key, prop]) => {
      // Validate prop structure
      if (typeof prop !== 'object') {
        issues.push(`Prop "${key}" is not an object, converting to {type: 'string'}`);
        sanitizedProps[key] = { type: 'string', default: String(prop) };
        return;
      }

      const sanitized = { ...prop };

      // Ensure type exists
      if (!sanitized.type) {
        issues.push(`Prop "${key}" missing type, defaulting to 'string'`);
        sanitized.type = 'string';
      }

      // Validate enum values
      if (sanitized.type === 'enum' && (!sanitized.values || !Array.isArray(sanitized.values))) {
        issues.push(`Prop "${key}" is enum but missing values array`);
        sanitized.values = [];
      }

      // Ensure default matches type
      if (sanitized.default !== undefined) {
        const defaultType = typeof sanitized.default;
        if (sanitized.type === 'boolean' && defaultType !== 'boolean') {
          issues.push(`Prop "${key}" default should be boolean, got ${defaultType}`);
          sanitized.default = Boolean(sanitized.default);
        } else if (sanitized.type === 'number' && defaultType !== 'number') {
          issues.push(`Prop "${key}" default should be number, got ${defaultType}`);
          sanitized.default = Number(sanitized.default) || 0;
        }
      }

      sanitizedProps[key] = sanitized;
    });

    return {
      valid: issues.length === 0,
      issues,
      sanitizedProps
    };
  }

  // ============================================================
  // P2: Auto-generate variants from enum props
  // ============================================================

  /**
   * Generate variants from enum props
   * @param {Object} props - Component props
   * @returns {Object} Variants object keyed by variant name
   */
  generateEnumVariants(props) {
    const variants = {};

    if (!props || !this.autoEnumVariants) return variants;

    Object.entries(props).forEach(([propName, prop]) => {
      // Check if prop is an enum type with values
      const enumValues = prop.values || prop.enumValues ||
        (prop.rawType?.includes('|') ? prop.rawType.split('|').map(v => v.trim().replace(/['"]/g, '')) : null);

      if (!enumValues || !Array.isArray(enumValues)) return;

      // Skip if too many values (would create too many stories)
      if (enumValues.length > 6) {
        console.log(`Skipping auto-variants for "${propName}" (${enumValues.length} values, max 6)`);
        return;
      }

      // Generate a variant for each enum value
      enumValues.forEach(value => {
        const variantName = this.formatVariantName(value, propName);

        variants[variantName] = {
          name: variantName,
          args: { [propName]: value },
          source: 'enum-auto',
          sourceProp: propName,
          parameters: {
            docs: {
              description: {
                story: `${propName} set to "${value}"`
              }
            }
          }
        };
      });
    });

    return variants;
  }

  /**
   * Format variant name from enum value
   * @param {string} value - Enum value
   * @param {string} propName - Prop name (for context)
   * @returns {string} Formatted variant name
   */
  formatVariantName(value, propName) {
    // Capitalize first letter
    let name = value.charAt(0).toUpperCase() + value.slice(1);

    // Handle kebab-case
    name = name.replace(/-([a-z])/g, (_, char) => char.toUpperCase());

    // Handle snake_case
    name = name.replace(/_([a-z])/g, (_, char) => char.toUpperCase());

    return name;
  }

  /**
   * Initialize conflict detector for a project (Sprint 6.4)
   * @param {string} projectPath - Path to project root
   */
  async initConflictDetector(projectPath) {
    this.conflictDetector = new FileConflictDetector();
    await this.conflictDetector.initialize(projectPath);
    return this.conflictDetector;
  }

  /**
   * Generate story file with advanced variants (Sprint 5.1)
   * @param {Object} component - Component data
   * @param {string} framework - Framework name
   * @param {Object} variantOptions - Variant generation options
   * @returns {string} Story file content with all variants
   */
  generateStoryWithVariants(component, framework = 'react', variantOptions = {}) {
    const variants = this.variantsGenerator.generateAllVariants(component, variantOptions);
    return this.variantsGenerator.generateStoryCode(component, variants, framework);
  }

  // ============================================================
  // P1: Unified Rich Story Generation (integrates P2-P5)
  // ============================================================

  /**
   * Generate a rich story file with full integration of all P1-P5 features
   *
   * This is the RECOMMENDED method for story generation as it:
   * - P1: Integrates StoryVariants (state/responsive/theme variants)
   * - P2: Auto-generates variants from enum props
   * - P3: Pulls Figma URL from componentRegistry
   * - P4: Uses componentRegistry for path resolution
   * - P5: Validates and sanitizes props before generation
   *
   * @param {Object} component - Component data
   * @param {string} framework - Framework name
   * @param {Object} options - Generation options
   * @param {boolean} options.includeStateVariants - Include loading/error/disabled states
   * @param {boolean} options.includeResponsiveVariants - Include mobile/tablet/desktop
   * @param {boolean} options.includeThemeVariants - Include light/dark themes
   * @param {boolean} options.includeEnumVariants - Auto-generate from enum props
   * @returns {Object} Result with content, variants, and validation info
   */
  generateRichStoryFile(component, framework = 'react', options = {}) {
    const result = {
      success: false,
      content: null,
      variants: {},
      validation: null,
      figmaUrl: null,
      componentPath: null,
      warnings: []
    };

    // P5: Validate props first
    if (component.props) {
      result.validation = this.validateProps(component.props);
      if (result.validation.issues.length > 0) {
        result.warnings.push(...result.validation.issues);
        // Use sanitized props going forward
        component = { ...component, props: result.validation.sanitizedProps };
      }
    }

    // P3: Get Figma URL from registry if not on component
    if (!component.figmaUrl && this.componentRegistry) {
      const registryFigmaUrl = this.getFigmaUrl(component.name);
      if (registryFigmaUrl) {
        component = { ...component, figmaUrl: registryFigmaUrl };
        result.figmaUrl = registryFigmaUrl;
      }
    } else {
      result.figmaUrl = component.figmaUrl || null;
    }

    // P4: Get component path from registry
    if (this.componentRegistry) {
      result.componentPath = this.getComponentPath(component.name, framework);
    }

    // Collect all variants
    const allVariants = {};

    // P2: Auto-generate enum variants
    if (options.includeEnumVariants !== false && this.autoEnumVariants) {
      const enumVariants = this.generateEnumVariants(component.props || {});
      Object.assign(allVariants, enumVariants);
    }

    // P1: Generate advanced variants using StoryVariants
    if (this.enableRichVariants) {
      const variantOptions = {
        includeStates: options.includeStateVariants !== false,
        includeResponsive: options.includeResponsiveVariants === true,
        includeThemes: options.includeThemeVariants === true
      };

      const advancedVariants = this.variantsGenerator.generateAllVariants(component, variantOptions);

      // Merge advanced variants (don't overwrite enum variants)
      Object.entries(advancedVariants).forEach(([name, variant]) => {
        if (!allVariants[name]) {
          allVariants[name] = variant;
        }
      });
    }

    result.variants = allVariants;

    // Generate the story code with all variants
    try {
      if (Object.keys(allVariants).length > 0) {
        // Use StoryVariants to generate code with all collected variants
        result.content = this.variantsGenerator.generateStoryCode(component, allVariants, framework);
      } else {
        // Fallback to basic story generation
        result.content = this.generateStoryFile(component, framework);
      }

      result.success = result.content !== null;
    } catch (error) {
      result.success = false;
      result.warnings.push(`Story generation error: ${error.message}`);
    }

    return result;
  }

  /**
   * Generate and write a rich story file with full P1-P5 integration
   *
   * @param {Object} component - Component data
   * @param {string} framework - Framework name
   * @param {Object} options - Generation options
   * @returns {Object} Result with path, variants, and validation info
   */
  generateAndWriteRichStory(component, framework = 'react', options = {}) {
    const result = this.generateRichStoryFile(component, framework, options);

    if (!result.success || !result.content) {
      return { ...result, path: null };
    }

    // Determine output path
    let storyPath;
    if (result.componentPath) {
      // P4: Use registry-resolved path
      const ext = path.extname(result.componentPath);
      storyPath = result.componentPath.replace(ext, this.getStoryExtension(framework));
    } else if (options.outputPath) {
      storyPath = options.outputPath;
    } else {
      // Fallback: construct path from component name
      const ext = this.storyExtensions[framework] || '.stories.tsx';
      storyPath = path.join(
        this.projectPath || process.cwd(),
        '.design/extracted-code',
        framework,
        `${component.name}${ext}`
      );
    }

    // Ensure directory exists
    const storyDir = path.dirname(storyPath);
    if (!fs.existsSync(storyDir)) {
      fs.mkdirSync(storyDir, { recursive: true });
    }

    // Write the story file
    fs.writeFileSync(storyPath, result.content, 'utf8');

    this.emit('story:written', {
      component: component.name,
      path: storyPath,
      variants: Object.keys(result.variants),
      figmaUrl: result.figmaUrl
    });

    return { ...result, path: storyPath };
  }

  /**
   * Get variants generator instance
   * @returns {StoryVariants} The variants generator
   */
  getVariantsGenerator() {
    return this.variantsGenerator;
  }

  /**
   * Generate story file content from template
   *
   * @param {Object} component - Component data
   * @param {string} framework - Framework name
   * @returns {string} Story file content
   */
  generateStoryFile(component, framework = 'react') {
    // Get story metadata from base class
    const storyData = this.generateStory(component);
    if (!storyData) return null;

    // Load template
    const template = this.loadTemplate(framework);
    if (!template) {
      throw new Error(`No template found for framework: ${framework}`);
    }

    // Prepare template variables
    const templateVars = {
      COMPONENT_NAME: component.name,
      STORY_TITLE: storyData.title,
      FIGMA_URL: component.figmaUrl || '',
      LAYOUT: component.layout || 'centered',
      ARG_TYPES: this.formatArgTypes(storyData.argTypes),
      DEFAULT_ARGS: this.formatDefaultArgs(this.generateDefaultArgs(component.props || {})),
      VARIANT_NAME: 'Default'
    };

    // Simple template replacement (no Handlebars dependency)
    let content = template;
    Object.entries(templateVars).forEach(([key, value]) => {
      const regex = new RegExp(`{{${key}}}`, 'g');
      content = content.replace(regex, value);
    });

    // Handle conditional blocks (Figma URL)
    if (!templateVars.FIGMA_URL) {
      content = content.replace(/{{#if FIGMA_URL}}[\s\S]*?{{\/if}}/g, '');
    } else {
      content = content.replace(/{{#if FIGMA_URL}}/g, '');
      content = content.replace(/{{\/if}}/g, '');
    }

    return content;
  }

  /**
   * Load story template for framework
   *
   * @param {string} framework - Framework name
   * @returns {string} Template content
   */
  loadTemplate(framework) {
    // Check cache
    if (this.templateCache.has(framework)) {
      return this.templateCache.get(framework);
    }

    // Get extension for framework (default to .tsx for unknown frameworks)
    const ext = this.templateExtensions[framework] || '.tsx';

    // Load template from file
    const templatePath = path.join(__dirname, 'story-templates', `${framework}.story.template${ext}`);

    if (!fs.existsSync(templatePath)) {
      console.warn(`Template not found: ${templatePath}`);
      return null;
    }

    const template = fs.readFileSync(templatePath, 'utf8');
    this.templateCache.set(framework, template);

    return template;
  }

  /**
   * Get supported frameworks
   * @returns {string[]} Array of supported framework names
   */
  getSupportedFrameworks() {
    return Object.keys(this.templateExtensions);
  }

  /**
   * Get story file extension for framework
   * @param {string} framework - Framework name
   * @returns {string} Story file extension
   */
  getStoryExtension(framework) {
    return this.storyExtensions[framework] || '.stories.tsx';
  }

  /**
   * Format argTypes for template
   * Enhanced Sprint 4.2: Support action type for event handlers
   *
   * @param {Object} argTypes - ArgTypes object
   * @returns {string} Formatted argTypes
   */
  formatArgTypes(argTypes) {
    if (!argTypes || Object.keys(argTypes).length === 0) {
      return '';
    }

    return Object.entries(argTypes).map(([key, config]) => {
      const parts = [];

      // Sprint 4.2: Handle action type for event handlers (onClick, onChange, etc.)
      if (config.action) {
        parts.push(`action: '${config.action}'`);
      } else if (config.control) {
        parts.push(`control: '${config.control}'`);
      }

      if (config.options) {
        parts.push(`options: ${JSON.stringify(config.options)}`);
      }

      if (config.description) {
        parts.push(`description: '${config.description.replace(/'/g, "\\'")}'`);
      }

      return `${key}: { ${parts.join(', ')} }`;
    }).join(',\n    ');
  }

  /**
   * Format default args for template
   *
   * @param {Object} args - Default args object
   * @returns {string} Formatted args
   */
  formatDefaultArgs(args) {
    if (!args || Object.keys(args).length === 0) {
      return '';
    }

    return Object.entries(args).map(([key, value]) => {
      // Format value based on type
      let formattedValue;
      if (typeof value === 'string') {
        formattedValue = `'${value.replace(/'/g, "\\'")}'`;
      } else if (typeof value === 'boolean' || typeof value === 'number') {
        formattedValue = value;
      } else if (value === null || value === undefined) {
        formattedValue = 'undefined';
      } else {
        formattedValue = JSON.stringify(value);
      }

      return `${key}: ${formattedValue}`;
    }).join(',\n    ');
  }

  /**
   * Generate story file and write to disk
   *
   * @param {Object} component - Component data
   * @param {string} componentPath - Path to component file
   * @param {string} framework - Framework name
   * @returns {string} Path to generated story file
   */
  generateAndWriteStory(component, componentPath, framework = 'react') {
    const storyContent = this.generateStoryFile(component, framework);
    if (!storyContent) return null;

    // Determine story file path
    const ext = path.extname(componentPath); // .tsx, .vue, .ts, etc.
    const storyPath = componentPath.replace(ext, `.stories${ext}`);

    // Write story file
    fs.writeFileSync(storyPath, storyContent, 'utf8');

    this.emit('story:written', { component: component.name, path: storyPath });

    return storyPath;
  }

  /**
   * Generate story file with conflict detection (Sprint 6.4)
   *
   * @param {Object} component - Component data
   * @param {string} componentPath - Path to component file
   * @param {string} framework - Framework name
   * @param {Object} options - Options including conflict handling
   * @returns {Object} Result with path and conflict info
   */
  async generateAndWriteStoryWithConflictCheck(component, componentPath, framework = 'react', options = {}) {
    const storyContent = this.generateStoryFile(component, framework);
    if (!storyContent) return { success: false, error: 'No story content generated' };

    // Determine story file path
    const ext = path.extname(componentPath);
    const storyPath = componentPath.replace(ext, `.stories${ext}`);

    // Check for conflicts if detector is available
    if (this.conflictDetector) {
      const conflict = await this.conflictDetector.detectConflict(storyPath, storyContent);

      if (conflict.hasConflict) {
        const strategy = options.conflictStrategy || this.conflictStrategy;

        this.emit('story:conflict', { component: component.name, path: storyPath, conflict });

        if (strategy === 'skip') {
          return { success: false, skipped: true, conflict, path: storyPath };
        }

        if (strategy === 'prompt') {
          // Return conflict info for user resolution
          return { success: false, needsResolution: true, conflict, content: storyContent, path: storyPath };
        }

        // strategy === 'overwrite' - continue to write
      }
    }

    // Write story file
    fs.writeFileSync(storyPath, storyContent, 'utf8');

    // Update hash registry if detector available
    if (this.conflictDetector) {
      await this.conflictDetector.storeHash(storyPath, storyContent, {
        framework,
        componentName: component.name,
        figmaNodeId: component.figmaId || component.id
      });
    }

    this.emit('story:written', { component: component.name, path: storyPath });

    return { success: true, path: storyPath };
  }
}

module.exports = { StoryGenerator, generateStory, StoryVariants };

/**
 * Convenience function for generating a single story
 *
 * @param {Object} component - Component data
 * @param {string} framework - Framework name
 * @returns {string} Story file content
 */
function generateStory(component, framework = 'react') {
  const generator = new StoryGenerator({ framework });
  return generator.generateStoryFile(component, framework);
}
