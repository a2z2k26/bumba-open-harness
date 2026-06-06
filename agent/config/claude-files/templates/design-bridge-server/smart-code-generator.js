/**
 * Smart Code Generator
 * Base class for intelligent, framework-specific code generation
 * Sprint 13: Framework Optimizer Base
 * Sprint 28: Generator-Optimizer Pipeline Integration
 */

const EventEmitter = require('events');
const path = require('path');
const { getOptimizerRegistry } = require('./optimizer-registry');
const TokenSystemIntegrator = require('./token-system-integrator');
const ComponentSchemaValidator = require('./component-schema-validator');
const { FileConflictDetector, ConflictType } = require('./file-conflict-detector');
const { getAccessibilityAutomation } = require('./accessibility-automation');

class SmartCodeGenerator extends EventEmitter {
  constructor(options = {}) {
    super();
    this.name = 'SmartCodeGenerator';
    this.version = '1.0.0';

    // Code generation configuration
    this.config = {
      framework: options.framework || 'react', // Default framework
      typescript: options.typescript !== false,
      styleFormat: options.styleFormat || 'css-modules', // css, scss, styled-components, emotion
      componentFormat: options.componentFormat || 'functional', // functional, class
      stateManagement: options.stateManagement || 'hooks', // hooks, redux, mobx, context
      testingFramework: options.testingFramework || 'jest', // jest, vitest, mocha
      accessibility: options.accessibility || 'wcag-aa', // wcag-a, wcag-aa, wcag-aaa
      // Sprint 32: Flexible validation - can disable for varied Figma data formats
      validateSchema: options.validateSchema !== false,
      optimization: {
        treeshaking: true,
        lazyLoading: true,
        codeSplitting: true,
        minification: true
      }
    };

    // Sprint 28: Get optimizer registry
    this.optimizerRegistry = getOptimizerRegistry();

    // Sprint 30: Initialize Token System Integrator
    this.tokenSystem = new TokenSystemIntegrator({
      autoSync: true,
      validateOnExtract: true,
      cacheTokens: true,
      validationPreset: this.config.accessibility
    });

    // Sprint 31: Initialize Component Schema Validator
    // Sprint 32: Allow flexible/lenient validation for varied Figma exports
    this.schemaValidator = new ComponentSchemaValidator({
      strictMode: options.strictMode !== undefined ? options.strictMode : !options.validateSchema === false,
      allowAdditionalProps: true
    });

    // Sprint 6.5: File conflict detection
    this.conflictDetector = null;
    this.conflictStrategy = 'prompt'; // 'prompt', 'overwrite', 'skip'

    // Sprint 105-110: Initialize Accessibility Automation
    this.accessibilityAutomation = getAccessibilityAutomation({
      wcagLevel: this.config.accessibility === 'wcag-aaa' ? 'AAA' :
                 this.config.accessibility === 'wcag-a' ? 'A' : 'AA',
      autoFix: true
    });

    // Framework optimizers registry (legacy - now using OptimizerRegistry)
    this.optimizers = new Map();

    // Code generation templates
    this.templates = new Map();

    // Generated components registry
    this.generatedComponents = new Map();

    // Initialize default optimizers
    this.initializeOptimizers();
  }

  /**
   * Initialize framework optimizers
   * Sprint 28: Updated to use OptimizerRegistry
   */
  initializeOptimizers() {
    // Base optimizers will be registered by specific framework classes
    this.optimizers.set('base', {
      name: 'BaseOptimizer',
      optimize: this.baseOptimization.bind(this)
    });

    // Sprint 28: Load all framework optimizers from registry
    const frameworks = this.optimizerRegistry.getSupportedFrameworks();
    frameworks.forEach(framework => {
      const optimizer = this.optimizerRegistry.getOptimizer(framework);
      this.optimizers.set(framework, optimizer);
    });

    console.log(`✓ SmartCodeGenerator initialized with ${this.optimizers.size} optimizers`);
  }

  /**
   * Generate optimized code from design components
   */
  async generateCode(designComponent, options = {}) {
    const config = { ...this.config, ...options };

    try {
      // Prepare component data
      const componentData = await this.prepareComponentData(designComponent, config);

      // Sprint 31: Validate component schema
      // Sprint 32: More lenient validation - log warnings instead of throwing
      if (config.validateSchema !== false) {
        try {
          const schemaValidation = this.schemaValidator.autoValidate(componentData);
          componentData.schemaValidation = schemaValidation;

          if (!schemaValidation.valid) {
            // Log warning but continue - don't block generation
            console.warn(`⚠ Schema validation warnings for ${componentData.name}:`,
              schemaValidation.errors?.map(e => e.message).join(', ') || 'validation issues');
          }
        } catch (validationError) {
          // If validator itself fails, just log and continue
          console.warn(`⚠ Schema validator error for ${componentData.name}: ${validationError.message}`);
          componentData.schemaValidation = { valid: false, skipped: true };
        }
      }

      // Sprint 30: Inject design tokens into component data
      if (options.figmaData && !componentData.designTokens) {
        const tokenResult = await this.tokenSystem.processTokens(options.figmaData);
        componentData.designTokens = tokenResult.tokens;
        componentData.tokenValidation = tokenResult.validation;
      } else if (!componentData.designTokens) {
        // Use cached tokens if available
        componentData.designTokens = this.tokenSystem.getAllTokens();
      }

      // Select appropriate optimizer
      const optimizer = this.selectOptimizer(config.framework);

      // Generate base code structure
      const baseCode = await this.generateBaseCode(componentData, config);

      // Apply framework-specific optimizations
      const optimizedCode = await optimizer.optimize(baseCode, componentData, config);

      // Apply post-processing
      const finalCode = await this.postProcess(optimizedCode, config);

      // Sprint 105-110: Run accessibility audit and apply auto-fixes
      const accessibilityAudit = await this.accessibilityAutomation.audit(componentData, finalCode);
      let accessibleCode = finalCode;

      // Apply auto-fixes if violations found
      if (accessibilityAudit.autoFixes && accessibilityAudit.autoFixes.length > 0) {
        accessibleCode = this.applyAccessibilityFixes(finalCode, accessibilityAudit.autoFixes, componentData);
      }

      // Generate supporting files
      const supportingFiles = await this.generateSupportingFiles(componentData, config);

      // Create component package
      const componentPackage = {
        id: componentData.id,
        name: componentData.name,
        framework: config.framework,
        code: accessibleCode,
        files: supportingFiles,
        metadata: this.generateMetadata(componentData, config),
        imports: this.extractImports(accessibleCode),
        exports: this.extractExports(accessibleCode),
        dependencies: this.analyzeDependencies(accessibleCode, config),
        // Sprint 105-110: Include accessibility audit results
        accessibility: {
          audit: accessibilityAudit,
          score: accessibilityAudit.score,
          wcagLevel: accessibilityAudit.wcagLevel,
          violations: accessibilityAudit.violations.length,
          warnings: accessibilityAudit.warnings.length,
          autoFixesApplied: accessibilityAudit.autoFixes?.length || 0
        }
      };

      // Register generated component
      this.generatedComponents.set(componentData.id, componentPackage);

      // Emit generation event
      this.emit('code:generated', componentPackage);

      return componentPackage;
    } catch (error) {
      this.emit('generation:error', { designComponent, error });
      throw error;
    }
  }

  /**
   * Prepare component data for code generation
   * Sprint 13-22: Added _figma reference for variant extraction
   */
  async prepareComponentData(designComponent, config) {
    return {
      id: designComponent.id || this.generateComponentId(designComponent),
      name: this.sanitizeComponentName(designComponent.name),
      type: this.detectComponentType(designComponent),
      props: await this.extractProps(designComponent),
      state: await this.extractState(designComponent),
      styles: await this.extractStyles(designComponent),
      variants: await this.extractVariants(designComponent),
      interactions: await this.extractInteractions(designComponent),
      accessibility: await this.extractAccessibility(designComponent),
      responsive: await this.extractResponsive(designComponent),
      children: await this.extractChildren(designComponent),
      // Sprint 13-22: Preserve original Figma component for variant extraction
      _figma: designComponent
    };
  }

  /**
   * Generate base code structure
   */
  async generateBaseCode(componentData, config) {
    const template = this.selectTemplate(config);

    const baseStructure = {
      imports: this.generateImports(componentData, config),
      component: this.generateComponentStructure(componentData, config),
      styles: this.generateStyles(componentData, config),
      exports: this.generateExports(componentData, config)
    };

    return this.assembleCode(baseStructure, template);
  }

  /**
   * Select appropriate optimizer
   */
  selectOptimizer(framework) {
    if (this.optimizers.has(framework)) {
      return this.optimizers.get(framework);
    }

    // Fall back to base optimizer
    return this.optimizers.get('base');
  }

  /**
   * Base optimization logic
   */
  async baseOptimization(code, componentData, config) {
    let optimizedCode = code;

    // Apply general optimizations
    if (config.optimization.treeshaking) {
      optimizedCode = this.applyTreeshaking(optimizedCode);
    }

    if (config.optimization.lazyLoading) {
      optimizedCode = this.applyLazyLoading(optimizedCode, componentData);
    }

    if (config.optimization.codeSplitting) {
      optimizedCode = this.applyCodeSplitting(optimizedCode, componentData);
    }

    if (config.optimization.minification) {
      optimizedCode = this.applyMinification(optimizedCode);
    }

    return optimizedCode;
  }

  /**
   * Post-process generated code
   */
  async postProcess(code, config) {
    let processedCode = code;

    // Format code
    processedCode = this.formatCode(processedCode, config);

    // Add comments and documentation
    processedCode = this.addDocumentation(processedCode, config);

    // Validate syntax
    await this.validateSyntax(processedCode, config);

    return processedCode;
  }

  /**
   * Sprint 105-110: Apply accessibility auto-fixes to generated code
   * @param {string} code - Generated code
   * @param {Array} autoFixes - Auto-fixes from accessibility audit
   * @param {Object} componentData - Component data
   * @returns {string} Code with accessibility fixes applied
   */
  applyAccessibilityFixes(code, autoFixes, componentData) {
    let fixedCode = code;

    for (const fix of autoFixes) {
      switch (fix.type) {
        case 'add-aria-label':
          // Add aria-label to the main component element
          fixedCode = this.injectARIALabel(fixedCode, fix.value, componentData);
          break;

        case 'add-role':
          // Add role attribute
          fixedCode = this.injectRole(fixedCode, fix.value, componentData);
          break;

        case 'add-alt-text':
          // Add alt text to images
          fixedCode = this.injectAltText(fixedCode, fix.value, componentData);
          break;

        default:
          // Log unhandled fix type
          console.warn(`Unhandled accessibility fix type: ${fix.type}`);
      }
    }

    return fixedCode;
  }

  /**
   * Sprint 105-110: Inject aria-label into component code
   */
  injectARIALabel(code, label, componentData) {
    const componentType = (componentData.type || '').toLowerCase();

    // Find the main element opening tag and add aria-label
    // Handles React/Vue/Angular patterns
    const patterns = [
      // Button patterns
      { regex: /(<button\s+)(?!.*aria-label)/gi, replacement: `$1aria-label="${label}" ` },
      // Generic div that should be a button
      { regex: /(<div\s+(?:[^>]*?className="[^"]*button[^"]*"[^>]*?)>)/gi, replacement: `<div role="button" aria-label="${label}" $1` },
      // Interactive elements
      { regex: /(<a\s+)(?!.*aria-label)/gi, replacement: `$1aria-label="${label}" ` },
      // Input elements (use aria-label for inputs without visible labels)
      { regex: /(<input\s+)(?!.*aria-label)(?!.*id=)/gi, replacement: `$1aria-label="${label}" ` }
    ];

    let result = code;
    for (const pattern of patterns) {
      if (pattern.regex.test(result)) {
        result = result.replace(pattern.regex, pattern.replacement);
        break; // Apply only first matching pattern
      }
    }

    return result;
  }

  /**
   * Sprint 105-110: Inject role attribute into component code
   */
  injectRole(code, role, componentData) {
    // Find divs that act as interactive elements but lack proper role
    const regex = /(<div\s+(?:[^>]*?onClick[^>]*?))(?!.*role=)/gi;
    return code.replace(regex, `$1 role="${role}"`);
  }

  /**
   * Sprint 105-110: Inject alt text into image elements
   */
  injectAltText(code, altText, componentData) {
    // Add alt text to images without it
    const patterns = [
      { regex: /(<img\s+)(?!.*alt=)/gi, replacement: `$1alt="${altText}" ` },
      // React Native Image
      { regex: /(<Image\s+)(?!.*accessibilityLabel)/gi, replacement: `$1accessibilityLabel="${altText}" ` }
    ];

    let result = code;
    for (const pattern of patterns) {
      result = result.replace(pattern.regex, pattern.replacement);
    }

    return result;
  }

  /**
   * Generate supporting files
   */
  async generateSupportingFiles(componentData, config) {
    const files = {};

    // Generate test file
    if (config.testingFramework) {
      files.test = await this.generateTestFile(componentData, config);
    }

    // Generate story file (for Storybook)
    files.story = await this.generateStoryFile(componentData, config);

    // Generate documentation
    files.documentation = await this.generateDocumentation(componentData, config);

    // Generate type definitions (if TypeScript)
    if (config.typescript) {
      files.types = await this.generateTypeDefinitions(componentData, config);
    }

    // Generate style file (if separate)
    if (this.requiresSeparateStyleFile(config)) {
      files.styles = await this.generateStyleFile(componentData, config);
    }

    // Sprint 11-12: Generate tokens file if design tokens are available
    if (componentData.designTokens) {
      files.tokens = this.generateTokensFile(componentData.designTokens, config);
    }

    return files;
  }

  /**
   * Sprint 11-12: Generate tokens.ts file from design tokens
   */
  generateTokensFile(designTokens, config) {
    const isTS = config.typescript !== false;
    const ext = isTS ? 'ts' : 'js';

    let code = `/**
 * Design Tokens - Auto-generated from Figma
 * Do not edit manually - regenerate from design source
 */

`;

    // Color tokens
    if (designTokens.colors && Object.keys(designTokens.colors).length > 0) {
      code += `export const colors = {\n`;
      Object.entries(designTokens.colors).forEach(([name, token]) => {
        const value = token.value || token.rgb || token;
        code += `  '${name}': '${value}',\n`;
      });
      code += `}${isTS ? ' as const' : ''};\n\n`;
    }

    // Typography tokens
    if (designTokens.typography && Object.keys(designTokens.typography).length > 0) {
      code += `export const typography = {\n`;
      Object.entries(designTokens.typography).forEach(([name, token]) => {
        code += `  '${name}': {\n`;
        code += `    fontFamily: '${token.fontFamily || 'inherit'}',\n`;
        code += `    fontWeight: ${token.fontWeight || 400},\n`;
        code += `    fontSize: '${token.fontSize || '16px'}',\n`;
        code += `    lineHeight: '${token.lineHeight || 'normal'}',\n`;
        code += `  },\n`;
      });
      code += `}${isTS ? ' as const' : ''};\n\n`;
    }

    // Spacing tokens
    if (designTokens.spacing && Object.keys(designTokens.spacing).length > 0) {
      code += `export const spacing = {\n`;
      Object.entries(designTokens.spacing).forEach(([name, value]) => {
        code += `  '${name}': '${value}',\n`;
      });
      code += `}${isTS ? ' as const' : ''};\n\n`;
    }

    // Border radius tokens
    if (designTokens.borderRadius && Object.keys(designTokens.borderRadius).length > 0) {
      code += `export const borderRadius = {\n`;
      Object.entries(designTokens.borderRadius).forEach(([name, value]) => {
        code += `  '${name}': '${value}',\n`;
      });
      code += `}${isTS ? ' as const' : ''};\n\n`;
    }

    // Effects/shadows tokens
    if (designTokens.effects && Object.keys(designTokens.effects).length > 0) {
      code += `export const effects = {\n`;
      Object.entries(designTokens.effects).forEach(([name, effectList]) => {
        if (Array.isArray(effectList)) {
          const shadowValue = effectList.map(e =>
            `${e.x || '0px'} ${e.y || '0px'} ${e.blur || '0px'} ${e.spread || '0px'} ${e.color || 'rgba(0,0,0,0.25)'}`
          ).join(', ');
          code += `  '${name}': '${shadowValue}',\n`;
        }
      });
      code += `}${isTS ? ' as const' : ''};\n\n`;
    }

    // Combined tokens object
    code += `export const tokens = {\n`;
    if (designTokens.colors) code += `  colors,\n`;
    if (designTokens.typography) code += `  typography,\n`;
    if (designTokens.spacing) code += `  spacing,\n`;
    if (designTokens.borderRadius) code += `  borderRadius,\n`;
    if (designTokens.effects) code += `  effects,\n`;
    code += `};\n\n`;

    // CSS custom properties generator
    code += `/**
 * Generate CSS custom properties from tokens
 */
export const cssVariables = \`:root {
\${Object.entries(colors || {}).map(([k, v]) => \`  --color-\${k}: \${v};\`).join('\\n')}
\${Object.entries(spacing || {}).map(([k, v]) => \`  --spacing-\${k}: \${v};\`).join('\\n')}
\${Object.entries(borderRadius || {}).map(([k, v]) => \`  --radius-\${k}: \${v};\`).join('\\n')}
}\`;

export default tokens;
`;

    return {
      filename: `tokens.${ext}`,
      content: code
    };
  }

  /**
   * Register a framework optimizer
   */
  registerOptimizer(framework, optimizer) {
    this.optimizers.set(framework, optimizer);
    this.emit('optimizer:registered', { framework, optimizer });
  }

  /**
   * Register a code template
   */
  registerTemplate(name, template) {
    this.templates.set(name, template);
    this.emit('template:registered', { name, template });
  }

  /**
   * Helper: Generate component ID
   */
  generateComponentId(component) {
    const name = component.name || 'component';
    const timestamp = Date.now();
    const random = Math.random().toString(36).substr(2, 9);
    return `${name}-${timestamp}-${random}`.replace(/\s+/g, '-').toLowerCase();
  }

  /**
   * Helper: Sanitize component name
   * Sprint 4.3: Enhanced to handle Figma variant format like "Property 1=primary"
   * @param {string} name - Raw component name from Figma
   * @param {string} parentName - Optional parent component name for variant context
   */
  sanitizeComponentName(name, parentName = null) {
    if (!name) return 'Component';

    // Handle Figma variant format: "Property 1=primary" or "variant=secondary"
    if (name.includes('=')) {
      const [, variant] = name.split('=');
      const baseName = parentName
        ? this.toPascalCase(parentName.replace(/-/g, ' '))
        : 'Component';
      return baseName + this.toPascalCase(variant);
    }

    // Strip common Figma prefixes
    let cleaned = name
      .replace(/^Property\s*\d*[=:]?\s*/i, '')  // Remove "Property 1=" prefix
      .replace(/^variant[=:]?\s*/i, '')          // Remove "variant=" prefix
      .replace(/[^a-zA-Z0-9\s-]/g, ' ')          // Clean special chars (keep hyphen for split)
      .trim();

    // If nothing left after cleaning, use original
    if (!cleaned) {
      cleaned = name.replace(/[^a-zA-Z0-9\s-]/g, ' ').trim() || 'Component';
    }

    return this.toPascalCase(cleaned);
  }

  /**
   * Helper: Convert string to PascalCase
   * Sprint 4.3: Extracted for reuse
   */
  toPascalCase(str) {
    if (!str) return '';
    return str
      .split(/[\s-_]+/)
      .filter(word => word.length > 0)
      .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
      .join('');
  }

  /**
   * Helper: Detect component type
   * Sprint 23-34: Enhanced semantic HTML detection
   */
  detectComponentType(component) {
    const name = (component.name || '').toLowerCase();

    // Detect buttons - multiple patterns
    if (name.includes('button') || name.includes('btn') || name.includes('cta')) {
      return 'button';
    }

    // Detect links
    if (name.includes('link') || name.includes('anchor')) {
      return 'link';
    }

    // Detect inputs - multiple patterns
    if (name.includes('input') || name.includes('field') || name.includes('textfield') ||
        name.includes('text-field') || name.includes('search')) {
      return 'input';
    }

    // Detect textarea
    if (name.includes('textarea') || name.includes('text-area') || name.includes('textbox')) {
      return 'textarea';
    }

    // Detect select/dropdown
    if (name.includes('select') || name.includes('dropdown') || name.includes('picker')) {
      return 'select';
    }

    // Detect checkbox
    if (name.includes('checkbox') || name.includes('check-box')) {
      return 'checkbox';
    }

    // Detect radio
    if (name.includes('radio')) {
      return 'radio';
    }

    // Detect toggle/switch
    if (name.includes('toggle') || name.includes('switch')) {
      return 'toggle';
    }

    // Detect card
    if (name.includes('card')) {
      return 'card';
    }

    // Detect modal/dialog
    if (name.includes('modal') || name.includes('dialog') || name.includes('popup')) {
      return 'modal';
    }

    // Detect navigation
    if (name.includes('nav') || name.includes('menu') || name.includes('sidebar')) {
      return 'navigation';
    }

    // Detect list/table
    if (name.includes('list') || name.includes('table')) {
      return 'list';
    }

    // Detect form
    if (name.includes('form')) {
      return 'form';
    }

    // Detect header elements
    if (name.includes('header') || name.includes('heading') || name.includes('title')) {
      return 'header';
    }

    // Detect footer
    if (name.includes('footer')) {
      return 'footer';
    }

    // Detect section
    if (name.includes('section') || name.includes('article')) {
      return 'section';
    }

    // Detect image
    if (name.includes('image') || name.includes('img') || name.includes('photo') || name.includes('avatar')) {
      return 'image';
    }

    // Detect icon
    if (name.includes('icon')) {
      return 'icon';
    }

    // Detect badge/tag/chip
    if (name.includes('badge') || name.includes('tag') || name.includes('chip') || name.includes('label')) {
      return 'badge';
    }

    // Detect alert/notification
    if (name.includes('alert') || name.includes('notification') || name.includes('toast')) {
      return 'alert';
    }

    // Detect tabs
    if (name.includes('tab')) {
      return 'tabs';
    }

    // Detect accordion
    if (name.includes('accordion') || name.includes('collapse') || name.includes('expand')) {
      return 'accordion';
    }

    return 'container';
  }

  /**
   * Helper: Extract props - Sprint 32: Enhanced Figma prop inference
   */
  async extractProps(component) {
    const props = {};

    // 1. Extract from Figma componentProperties (modern format)
    if (component.componentProperties) {
      Object.entries(component.componentProperties).forEach(([key, prop]) => {
        const propName = this.sanitizePropName(key);
        props[propName] = this.inferPropFromFigma(key, prop);
      });
    }

    // 2. Extract from Figma componentPropertyDefinitions (variant props)
    if (component.componentPropertyDefinitions) {
      Object.entries(component.componentPropertyDefinitions).forEach(([key, def]) => {
        const propName = this.sanitizePropName(key);
        if (!props[propName]) {
          props[propName] = this.inferPropFromDefinition(key, def);
        }
      });
    }

    // 3. Extract from variantProperties (component set variants)
    if (component.variantProperties) {
      Object.entries(component.variantProperties).forEach(([key, value]) => {
        const propName = this.sanitizePropName(key);
        if (!props[propName]) {
          props[propName] = {
            type: 'string',
            default: value,
            required: false,
            description: `Variant: ${key}`
          };
        }
      });
    }

    // 4. Extract from children with special names (text content, icons)
    if (component.children) {
      this.extractPropsFromChildren(component.children, props);
    }

    // 5. Add common props based on component type
    const type = this.detectComponentType(component);
    const commonProps = this.getCommonPropsForType(type);

    return { ...commonProps, ...props };
  }

  /**
   * Sprint 32: Sanitize prop name to valid JS identifier
   */
  sanitizePropName(name) {
    // Remove hash prefix from Figma (e.g., "#1234:name" -> "name")
    let clean = name.replace(/^#\d+:/, '');
    // Convert spaces and special chars to camelCase
    clean = clean.replace(/[^a-zA-Z0-9]+(.)/g, (_, char) => char.toUpperCase());
    // Ensure starts with lowercase
    clean = clean.charAt(0).toLowerCase() + clean.slice(1);
    // Remove any remaining invalid chars
    clean = clean.replace(/[^a-zA-Z0-9]/g, '');
    return clean || 'prop';
  }

  /**
   * Sprint 32: Infer prop details from Figma component property
   */
  inferPropFromFigma(key, prop) {
    // Handle object format: { type: 'TEXT', value: 'Button' }
    if (typeof prop === 'object' && prop !== null) {
      const figmaType = prop.type || prop.propertyType;

      switch (figmaType) {
        case 'TEXT':
          return {
            type: 'string',
            default: prop.value || prop.defaultValue || '',
            required: false,
            description: `Text content for ${key}`
          };
        case 'BOOLEAN':
          return {
            type: 'boolean',
            default: prop.value !== undefined ? prop.value : (prop.defaultValue || false),
            required: false,
            description: `Toggle for ${key}`
          };
        case 'INSTANCE_SWAP':
          return {
            type: 'object', // React node or component
            default: null,
            required: false,
            description: `Swappable component for ${key}`
          };
        case 'VARIANT':
          return {
            type: 'string',
            default: prop.value || prop.defaultValue || '',
            required: false,
            options: prop.variantOptions || [],
            description: `Variant option for ${key}`
          };
        default:
          return {
            type: this.inferPropType(prop.value),
            default: prop.value,
            required: false
          };
      }
    }

    // Handle primitive value
    return {
      type: this.inferPropType(prop),
      default: prop,
      required: false
    };
  }

  /**
   * Sprint 32: Infer prop from Figma componentPropertyDefinition
   */
  inferPropFromDefinition(key, def) {
    const type = def.type || 'VARIANT';

    switch (type) {
      case 'VARIANT':
        return {
          type: 'string',
          default: def.defaultValue || '',
          required: false,
          options: def.variantOptions || [],
          description: `Variant: ${key}`
        };
      case 'BOOLEAN':
        return {
          type: 'boolean',
          default: def.defaultValue || false,
          required: false
        };
      case 'TEXT':
        return {
          type: 'string',
          default: def.defaultValue || '',
          required: false
        };
      case 'INSTANCE_SWAP':
        return {
          type: 'object',
          default: null,
          required: false,
          description: `Slot for ${key}`
        };
      default:
        return {
          type: 'any',
          default: def.defaultValue,
          required: false
        };
    }
  }

  /**
   * Sprint 32: Extract props from Figma children (text nodes, icons)
   */
  extractPropsFromChildren(children, props) {
    children.forEach(child => {
      const name = (child.name || '').toLowerCase();

      // Text nodes become string props
      if (child.type === 'TEXT' && child.characters) {
        const propName = this.sanitizePropName(child.name);
        if (!props[propName] && propName !== 'prop') {
          props[propName] = {
            type: 'string',
            default: child.characters,
            required: false,
            description: `Text content: ${child.name}`
          };
        }
      }

      // Icon/image placeholders
      if (name.includes('icon') || name.includes('image') || name.includes('avatar')) {
        const propName = this.sanitizePropName(child.name);
        if (!props[propName]) {
          props[propName] = {
            type: 'object', // React.ReactNode
            default: null,
            required: false,
            description: `Icon/image slot: ${child.name}`
          };
        }
      }

      // Recurse into children
      if (child.children) {
        this.extractPropsFromChildren(child.children, props);
      }
    });
  }

  /**
   * Helper: Extract state
   */
  async extractState(component) {
    const state = {};

    // Extract interactive states
    if (component.interactions) {
      component.interactions.forEach(interaction => {
        if (interaction.trigger && interaction.action) {
          state[interaction.trigger] = interaction.action;
        }
      });
    }

    return state;
  }

  /**
   * Helper: Extract styles
   */
  async extractStyles(component) {
    return {
      layout: this.extractLayoutStyles(component),
      typography: this.extractTypographyStyles(component),
      colors: this.extractColorStyles(component),
      effects: this.extractEffectStyles(component),
      responsive: this.extractResponsiveStyles(component)
    };
  }

  /**
   * Helper: Extract variants
   * Sprint 13-22: Enhanced to parse COMPONENT_SET children for variant info
   */
  async extractVariants(component) {
    // If variants already exist, use them
    if (component.variants && component.variants.length > 0) {
      return component.variants;
    }

    // For COMPONENT_SET, parse variants from children names
    if (component.type === 'COMPONENT_SET' && component.children?.length > 0) {
      const variantMap = new Map(); // Track unique variant properties

      component.children.forEach(child => {
        // Parse variant name like "Property 1=primary" or "State=hover, Size=large"
        const parts = child.name.split(',').map(p => p.trim());

        parts.forEach(part => {
          const match = part.match(/^(.+?)=(.+)$/);
          if (match) {
            const [, propName, propValue] = match;
            const cleanPropName = this.sanitizeVariantPropName(propName);

            if (!variantMap.has(cleanPropName)) {
              variantMap.set(cleanPropName, {
                name: cleanPropName,
                values: new Set(),
                defaultValue: null
              });
            }

            variantMap.get(cleanPropName).values.add(propValue.trim());

            // First value becomes default
            if (!variantMap.get(cleanPropName).defaultValue) {
              variantMap.get(cleanPropName).defaultValue = propValue.trim();
            }
          }
        });
      });

      // Convert to array with proper structure
      return Array.from(variantMap.values()).map(variant => ({
        name: variant.name,
        type: 'enum',
        values: Array.from(variant.values),
        defaultValue: variant.defaultValue,
        required: false
      }));
    }

    return [];
  }

  /**
   * Sprint 13-22: Sanitize variant property name
   * Converts "Property 1" to "variant" or meaningful name
   */
  sanitizeVariantPropName(propName) {
    // Handle generic "Property N" format
    if (/^Property\s*\d*$/i.test(propName.trim())) {
      return 'variant';
    }

    // Convert to camelCase
    return propName
      .toLowerCase()
      .replace(/[^a-z0-9]+(.)/g, (_, chr) => chr.toUpperCase())
      .replace(/^./, c => c.toLowerCase())
      .replace(/[^a-zA-Z0-9]/g, '');
  }

  /**
   * Sprint 13-22: Extract variant-specific styles
   * Returns a map of variant value -> styles
   */
  extractVariantStyles(component) {
    const variantStyles = {};

    if (component.type !== 'COMPONENT_SET' || !component.children?.length) {
      return variantStyles;
    }

    component.children.forEach(child => {
      // Parse variant value from name
      const match = child.name.match(/=(.+)$/);
      if (!match) return;

      const variantValue = match[1].trim();

      // Extract styles for this variant
      variantStyles[variantValue] = {
        colors: this.extractColorStyles({ ...child, type: 'COMPONENT' }),
        effects: this.extractEffectStyles({ ...child, type: 'COMPONENT' }),
        typography: this.extractTypographyStyles({ ...child, type: 'COMPONENT' })
      };
    });

    return variantStyles;
  }

  /**
   * Sprint 13-22: Generate variant style map for React component
   */
  generateVariantStyleMap(variantStyles) {
    if (!variantStyles || Object.keys(variantStyles).length === 0) {
      return '';
    }

    let code = `const variantStyles = {\n`;
    Object.entries(variantStyles).forEach(([variantValue, styles]) => {
      code += `  '${variantValue}': {\n`;

      // Merge all style objects
      const mergedStyles = {
        ...styles.colors,
        ...styles.effects,
        ...styles.typography
      };

      Object.entries(mergedStyles).forEach(([prop, value]) => {
        // Handle different value types
        if (typeof value === 'number') {
          code += `    ${prop}: ${value},\n`;
        } else {
          // Escape single quotes in string values
          const escapedValue = String(value).replace(/'/g, "\\'");
          code += `    ${prop}: '${escapedValue}',\n`;
        }
      });

      code += `  },\n`;
    });
    code += `} as const;\n\n`;

    return code;
  }

  /**
   * Helper: Extract interactions
   */
  async extractInteractions(component) {
    return component.interactions || [];
  }

  /**
   * Helper: Extract accessibility
   */
  async extractAccessibility(component) {
    return {
      role: component.role || this.inferRole(component),
      ariaLabel: component.ariaLabel || component.name,
      tabIndex: component.tabIndex || 0,
      keyboardSupport: true
    };
  }

  /**
   * Helper: Extract responsive
   */
  async extractResponsive(component) {
    return {
      mobile: component.mobile || {},
      tablet: component.tablet || {},
      desktop: component.desktop || {}
    };
  }

  /**
   * Helper: Extract children
   */
  async extractChildren(component) {
    if (!component.children) return [];

    return component.children.map(child => ({
      id: child.id,
      name: child.name,
      type: child.type
    }));
  }

  /**
   * Helper: Generate imports
   */
  generateImports(componentData, config) {
    const imports = [];

    // Framework imports
    if (config.framework === 'react') {
      imports.push("import React from 'react';");
      if (config.componentFormat === 'functional' && componentData.state) {
        imports.push("import { useState, useEffect } from 'react';");
      }
    }

    // Style imports
    if (config.styleFormat === 'styled-components') {
      imports.push("import styled from 'styled-components';");
    }

    return imports.join('\n');
  }

  /**
   * Helper: Generate component structure
   * Sprint 32: Enhanced to pass full componentData for richer generation
   */
  generateComponentStructure(componentData, config) {
    const { name, props, state } = componentData;

    if (config.framework === 'react' && config.componentFormat === 'functional') {
      return this.generateReactFunctionalComponent(name, props, state, config, componentData);
    }

    // Vue support (Sprint 32 enhancement - multi-framework)
    if (config.framework === 'vue') {
      return this.generateVueComponent(componentData, config);
    }

    // Svelte support
    if (config.framework === 'svelte') {
      return this.generateSvelteComponent(componentData, config);
    }

    return `// Component structure for ${name}`;
  }

  /**
   * Helper: Generate React functional component
   * Sprint 32: Enhanced with inline styles and richer structure
   * Sprint 13-22: Enhanced with variant support
   */
  generateReactFunctionalComponent(name, props, state, config, componentData = {}) {
    // Sprint 13-22: Extract variants from source component
    const sourceComponent = componentData._figma || componentData;
    const variantStyles = this.extractVariantStyles(sourceComponent);
    const hasVariants = Object.keys(variantStyles).length > 0;

    // Add variant prop if component has variants
    const propsWithVariants = { ...props };
    if (hasVariants) {
      const variantValues = Object.keys(variantStyles);
      propsWithVariants.variant = {
        type: 'enum',
        values: variantValues,
        defaultValue: variantValues[0],
        required: false
      };
    }

    const propsString = Object.keys(propsWithVariants).length > 0
      ? `{ ${Object.keys(propsWithVariants).join(', ')} }`
      : '';

    // Generate TypeScript interface if needed
    let interfaceCode = '';
    if (config.typescript && Object.keys(propsWithVariants).length > 0) {
      interfaceCode = this.generatePropsInterfaceWithVariants(name, propsWithVariants, variantStyles);
    }

    // Sprint 13-22: Add variant styles map before component
    let variantStylesCode = '';
    if (hasVariants) {
      variantStylesCode = this.generateVariantStyleMap(variantStyles);
    }

    let component = config.typescript
      ? `const ${name}: React.FC<${name}Props> = (${propsString}) => {\n`
      : `const ${name} = (${propsString}) => {\n`;

    // Add state hooks
    if (state && Object.keys(state).length > 0) {
      Object.entries(state).forEach(([key, value]) => {
        component += `  const [${key}, set${this.capitalize(key)}] = useState(${JSON.stringify(value)});\n`;
      });
      component += '\n';
    }

    // Build inline styles from component data
    const inlineStyles = this.buildInlineStyles(componentData);
    const hasInlineStyles = Object.keys(inlineStyles).length > 0 || hasVariants;

    // Generate component JSX based on type
    const componentType = componentData.type || 'container';
    const className = this.toKebabCase(name);

    component += `  return (\n`;
    component += this.generateJSXForComponentType(componentType, name, className, propsWithVariants, inlineStyles, hasInlineStyles, hasVariants);
    component += `  );\n`;
    component += `};\n`;

    // Export with named export for tree-shaking
    const namedExport = `export { ${name} };`;

    return interfaceCode + variantStylesCode + component + '\n' + namedExport;
  }

  /**
   * Sprint 13-22: Generate props interface with variant type
   */
  generatePropsInterfaceWithVariants(name, props, variantStyles) {
    let code = `export interface ${name}Props {\n`;

    Object.entries(props).forEach(([propName, propDef]) => {
      const required = propDef.required ? '' : '?';

      if (propName === 'variant' && variantStyles) {
        // Generate union type for variant values
        const variantUnion = Object.keys(variantStyles).map(v => `'${v}'`).join(' | ');
        code += `  ${propName}${required}: ${variantUnion};\n`;
      } else {
        const type = this.mapPropTypeToTS(propDef.type);
        code += `  ${propName}${required}: ${type};\n`;
      }
    });

    code += `}\n\n`;
    return code;
  }

  /**
   * Sprint 32: Generate TypeScript props interface
   */
  generatePropsInterface(name, props) {
    let code = `export interface ${name}Props {\n`;

    Object.entries(props).forEach(([propName, propDef]) => {
      const required = propDef.required ? '' : '?';
      const type = this.mapPropTypeToTS(propDef.type);
      code += `  ${propName}${required}: ${type};\n`;
    });

    code += `}\n\n`;
    return code;
  }

  /**
   * Sprint 32: Map prop types to TypeScript types
   */
  mapPropTypeToTS(type) {
    const typeMap = {
      'string': 'string',
      'number': 'number',
      'boolean': 'boolean',
      'array': 'any[]',
      'object': 'Record<string, any>',
      'function': '(...args: any[]) => void',
      'any': 'any'
    };
    return typeMap[type] || 'any';
  }

  /**
   * Sprint 32: Build inline styles object from component data
   */
  buildInlineStyles(componentData) {
    const styles = {};

    if (!componentData.styles) return styles;

    // Merge all style categories
    const { layout, typography, colors, effects } = componentData.styles;

    Object.assign(styles, layout || {}, typography || {}, colors || {}, effects || {});

    return styles;
  }

  /**
   * Sprint 32: Generate JSX based on component type
   * Sprint 13-22: Enhanced with variant style support
   */
  generateJSXForComponentType(type, name, className, props, inlineStyles, hasInlineStyles, hasVariants = false) {
    // Generate style attribute - merge base styles with variant styles
    let styleAttr = '';
    if (hasInlineStyles) {
      if (hasVariants) {
        // Merge base styles with variant-specific styles
        const baseStyleStr = Object.keys(inlineStyles).length > 0
          ? this.styleObjectToString(inlineStyles)
          : '{}';
        styleAttr = ` style={{ ...${baseStyleStr}, ...variantStyles[variant] }}`;
      } else {
        styleAttr = ` style={${this.styleObjectToString(inlineStyles)}}`;
      }
    }

    switch (type) {
      case 'button':
        return this.generateButtonJSX(className, props, styleAttr, hasVariants);
      case 'link':
        return this.generateLinkJSX(className, props, styleAttr);
      case 'input':
        return this.generateInputJSX(className, props, styleAttr);
      case 'textarea':
        return this.generateTextareaJSX(className, props, styleAttr);
      case 'select':
        return this.generateSelectJSX(className, props, styleAttr);
      case 'checkbox':
        return this.generateCheckboxJSX(className, props, styleAttr);
      case 'radio':
        return this.generateRadioJSX(className, props, styleAttr);
      case 'toggle':
        return this.generateToggleJSX(className, props, styleAttr);
      case 'card':
        return this.generateCardJSX(className, props, styleAttr);
      case 'modal':
        return this.generateModalJSX(className, props, styleAttr);
      case 'navigation':
        return this.generateNavigationJSX(className, props, styleAttr);
      case 'header':
        return this.generateHeaderJSX(className, props, styleAttr);
      case 'footer':
        return this.generateFooterJSX(className, props, styleAttr);
      case 'section':
        return this.generateSectionJSX(className, props, styleAttr);
      case 'image':
        return this.generateImageJSX(className, props, styleAttr);
      case 'badge':
        return this.generateBadgeJSX(className, props, styleAttr);
      case 'alert':
        return this.generateAlertJSX(className, props, styleAttr);
      case 'tabs':
        return this.generateTabsJSX(className, props, styleAttr);
      default:
        return this.generateContainerJSX(className, props, styleAttr);
    }
  }

  /**
   * Sprint 13-22: Enhanced button JSX with variant support
   */
  generateButtonJSX(className, props, styleAttr, hasVariants = false) {
    const hasLabel = props.label || props.children;
    const hasIcon = props.icon;

    let jsx = `    <button\n`;
    if (hasVariants) {
      jsx += `      className={\`${className} ${className}--\${variant}\`}\n`;
    } else {
      jsx += `      className="${className}"\n`;
    }
    jsx += `      onClick={onClick}\n`;
    jsx += `      disabled={disabled}\n`;
    jsx += `      type="button"\n`;
    if (styleAttr) jsx += `     ${styleAttr.trim()}\n`;
    jsx += `    >\n`;
    if (hasIcon) jsx += `      {icon && <span className="${className}__icon">{icon}</span>}\n`;
    jsx += `      {label}\n`;
    jsx += `    </button>\n`;
    return jsx;
  }

  generateInputJSX(className, props, styleAttr) {
    let jsx = `    <div className="${className}"${styleAttr}>\n`;
    if (props.label) {
      jsx += `      {label && <label className="${className}__label">{label}</label>}\n`;
    }
    jsx += `      <input\n`;
    jsx += `        className="${className}__input"\n`;
    jsx += `        type={type || 'text'}\n`;
    jsx += `        value={value}\n`;
    jsx += `        onChange={onChange}\n`;
    jsx += `        placeholder={placeholder}\n`;
    jsx += `        disabled={disabled}\n`;
    jsx += `      />\n`;
    if (props.error) {
      jsx += `      {error && <span className="${className}__error">{error}</span>}\n`;
    }
    jsx += `    </div>\n`;
    return jsx;
  }

  generateCardJSX(className, props, styleAttr) {
    let jsx = `    <div className="${className}"${styleAttr}>\n`;
    jsx += `      {title && <div className="${className}__header">\n`;
    jsx += `        <h3 className="${className}__title">{title}</h3>\n`;
    jsx += `      </div>}\n`;
    jsx += `      <div className="${className}__body">\n`;
    jsx += `        {children}\n`;
    jsx += `      </div>\n`;
    jsx += `    </div>\n`;
    return jsx;
  }

  generateModalJSX(className, props, styleAttr) {
    let jsx = `    <div className="${className}__overlay" onClick={onClose}>\n`;
    jsx += `      <div className="${className}"${styleAttr} onClick={(e) => e.stopPropagation()}>\n`;
    jsx += `        <div className="${className}__header">\n`;
    jsx += `          {title && <h2 className="${className}__title">{title}</h2>}\n`;
    jsx += `          <button className="${className}__close" onClick={onClose}>&times;</button>\n`;
    jsx += `        </div>\n`;
    jsx += `        <div className="${className}__content">\n`;
    jsx += `          {children}\n`;
    jsx += `        </div>\n`;
    jsx += `      </div>\n`;
    jsx += `    </div>\n`;
    return jsx;
  }

  generateContainerJSX(className, props, styleAttr) {
    let jsx = `    <div className="${className}"${styleAttr}>\n`;
    jsx += `      {children}\n`;
    jsx += `    </div>\n`;
    return jsx;
  }

  /**
   * Sprint 23-34: Semantic link element
   */
  generateLinkJSX(className, props, styleAttr) {
    let jsx = `    <a\n`;
    jsx += `      className="${className}"\n`;
    jsx += `      href={href || '#'}\n`;
    jsx += `      onClick={onClick}\n`;
    if (styleAttr) jsx += `     ${styleAttr.trim()}\n`;
    jsx += `    >\n`;
    jsx += `      {children || label}\n`;
    jsx += `    </a>\n`;
    return jsx;
  }

  /**
   * Sprint 23-34: Textarea element
   */
  generateTextareaJSX(className, props, styleAttr) {
    let jsx = `    <div className="${className}"${styleAttr}>\n`;
    jsx += `      {label && <label className="${className}__label" htmlFor={id}>{label}</label>}\n`;
    jsx += `      <textarea\n`;
    jsx += `        id={id}\n`;
    jsx += `        className="${className}__textarea"\n`;
    jsx += `        value={value}\n`;
    jsx += `        onChange={onChange}\n`;
    jsx += `        placeholder={placeholder}\n`;
    jsx += `        disabled={disabled}\n`;
    jsx += `        rows={rows || 4}\n`;
    jsx += `        aria-describedby={error ? \`\${id}-error\` : undefined}\n`;
    jsx += `      />\n`;
    jsx += `      {error && <span id={\`\${id}-error\`} className="${className}__error" role="alert">{error}</span>}\n`;
    jsx += `    </div>\n`;
    return jsx;
  }

  /**
   * Sprint 23-34: Select/dropdown element
   */
  generateSelectJSX(className, props, styleAttr) {
    let jsx = `    <div className="${className}"${styleAttr}>\n`;
    jsx += `      {label && <label className="${className}__label" htmlFor={id}>{label}</label>}\n`;
    jsx += `      <select\n`;
    jsx += `        id={id}\n`;
    jsx += `        className="${className}__select"\n`;
    jsx += `        value={value}\n`;
    jsx += `        onChange={onChange}\n`;
    jsx += `        disabled={disabled}\n`;
    jsx += `        aria-describedby={error ? \`\${id}-error\` : undefined}\n`;
    jsx += `      >\n`;
    jsx += `        {options?.map((opt) => (\n`;
    jsx += `          <option key={opt.value} value={opt.value}>{opt.label}</option>\n`;
    jsx += `        ))}\n`;
    jsx += `      </select>\n`;
    jsx += `      {error && <span id={\`\${id}-error\`} className="${className}__error" role="alert">{error}</span>}\n`;
    jsx += `    </div>\n`;
    return jsx;
  }

  /**
   * Sprint 23-34: Checkbox element with proper accessibility
   */
  generateCheckboxJSX(className, props, styleAttr) {
    let jsx = `    <label className="${className}"${styleAttr}>\n`;
    jsx += `      <input\n`;
    jsx += `        type="checkbox"\n`;
    jsx += `        className="${className}__input"\n`;
    jsx += `        checked={checked}\n`;
    jsx += `        onChange={onChange}\n`;
    jsx += `        disabled={disabled}\n`;
    jsx += `        aria-checked={checked}\n`;
    jsx += `      />\n`;
    jsx += `      <span className="${className}__checkmark" />\n`;
    jsx += `      {label && <span className="${className}__label">{label}</span>}\n`;
    jsx += `    </label>\n`;
    return jsx;
  }

  /**
   * Sprint 23-34: Radio button element
   */
  generateRadioJSX(className, props, styleAttr) {
    let jsx = `    <label className="${className}"${styleAttr}>\n`;
    jsx += `      <input\n`;
    jsx += `        type="radio"\n`;
    jsx += `        className="${className}__input"\n`;
    jsx += `        name={name}\n`;
    jsx += `        value={value}\n`;
    jsx += `        checked={checked}\n`;
    jsx += `        onChange={onChange}\n`;
    jsx += `        disabled={disabled}\n`;
    jsx += `      />\n`;
    jsx += `      <span className="${className}__circle" />\n`;
    jsx += `      {label && <span className="${className}__label">{label}</span>}\n`;
    jsx += `    </label>\n`;
    return jsx;
  }

  /**
   * Sprint 23-34: Toggle/switch element with accessibility
   */
  generateToggleJSX(className, props, styleAttr) {
    let jsx = `    <label className="${className}"${styleAttr}>\n`;
    jsx += `      <input\n`;
    jsx += `        type="checkbox"\n`;
    jsx += `        className="${className}__input"\n`;
    jsx += `        checked={checked}\n`;
    jsx += `        onChange={onChange}\n`;
    jsx += `        disabled={disabled}\n`;
    jsx += `        role="switch"\n`;
    jsx += `        aria-checked={checked}\n`;
    jsx += `      />\n`;
    jsx += `      <span className="${className}__track">\n`;
    jsx += `        <span className="${className}__thumb" />\n`;
    jsx += `      </span>\n`;
    jsx += `      {label && <span className="${className}__label">{label}</span>}\n`;
    jsx += `    </label>\n`;
    return jsx;
  }

  /**
   * Sprint 23-34: Navigation element with semantic nav
   */
  generateNavigationJSX(className, props, styleAttr) {
    let jsx = `    <nav className="${className}" aria-label={ariaLabel || 'Navigation'}${styleAttr}>\n`;
    jsx += `      {children}\n`;
    jsx += `    </nav>\n`;
    return jsx;
  }

  /**
   * Sprint 23-34: Header element
   */
  generateHeaderJSX(className, props, styleAttr) {
    let jsx = `    <header className="${className}"${styleAttr}>\n`;
    jsx += `      {title && <h1 className="${className}__title">{title}</h1>}\n`;
    jsx += `      {children}\n`;
    jsx += `    </header>\n`;
    return jsx;
  }

  /**
   * Sprint 23-34: Footer element
   */
  generateFooterJSX(className, props, styleAttr) {
    let jsx = `    <footer className="${className}"${styleAttr}>\n`;
    jsx += `      {children}\n`;
    jsx += `    </footer>\n`;
    return jsx;
  }

  /**
   * Sprint 23-34: Section element
   */
  generateSectionJSX(className, props, styleAttr) {
    let jsx = `    <section className="${className}" aria-label={ariaLabel}${styleAttr}>\n`;
    jsx += `      {title && <h2 className="${className}__title">{title}</h2>}\n`;
    jsx += `      {children}\n`;
    jsx += `    </section>\n`;
    return jsx;
  }

  /**
   * Sprint 23-34: Image element with alt text
   */
  generateImageJSX(className, props, styleAttr) {
    let jsx = `    <img\n`;
    jsx += `      className="${className}"\n`;
    jsx += `      src={src}\n`;
    jsx += `      alt={alt || ''}\n`;
    jsx += `      loading={loading || 'lazy'}\n`;
    if (styleAttr) jsx += `     ${styleAttr.trim()}\n`;
    jsx += `    />\n`;
    return jsx;
  }

  /**
   * Sprint 23-34: Badge/tag element
   */
  generateBadgeJSX(className, props, styleAttr) {
    let jsx = `    <span className="${className}"${styleAttr}>\n`;
    jsx += `      {children || label}\n`;
    jsx += `    </span>\n`;
    return jsx;
  }

  /**
   * Sprint 23-34: Alert/notification element with proper role
   */
  generateAlertJSX(className, props, styleAttr) {
    let jsx = `    <div\n`;
    jsx += `      className="${className}"\n`;
    jsx += `      role="alert"\n`;
    jsx += `      aria-live={type === 'error' ? 'assertive' : 'polite'}\n`;
    if (styleAttr) jsx += `     ${styleAttr.trim()}\n`;
    jsx += `    >\n`;
    jsx += `      {title && <div className="${className}__title">{title}</div>}\n`;
    jsx += `      <div className="${className}__message">{message || children}</div>\n`;
    jsx += `      {onClose && <button className="${className}__close" onClick={onClose} aria-label="Close">&times;</button>}\n`;
    jsx += `    </div>\n`;
    return jsx;
  }

  /**
   * Sprint 35-50: Extract interactive states from variant names
   * Detects patterns like "State=hover", "disabled=true", etc.
   */
  extractInteractiveStates(component) {
    const states = {
      default: null,
      hover: null,
      focus: null,
      active: null,
      disabled: null,
      loading: null
    };

    if (component.type !== 'COMPONENT_SET' || !component.children?.length) {
      return states;
    }

    // State-related keywords to look for
    const statePatterns = {
      hover: /hover|hovered/i,
      focus: /focus|focused/i,
      active: /active|pressed|click/i,
      disabled: /disabled|inactive/i,
      loading: /loading|spinner/i,
      default: /default|normal|rest|idle/i
    };

    component.children.forEach(child => {
      const name = child.name.toLowerCase();

      // Check each state pattern
      Object.entries(statePatterns).forEach(([state, pattern]) => {
        if (pattern.test(name)) {
          // Extract styles for this state
          states[state] = {
            colors: this.extractColorStyles({ ...child, type: 'COMPONENT' }),
            effects: this.extractEffectStyles({ ...child, type: 'COMPONENT' })
          };
        }
      });
    });

    return states;
  }

  /**
   * Sprint 35-50: Generate CSS for interactive states
   */
  generateInteractiveStateStyles(className, states) {
    let css = '';

    if (states.hover) {
      css += `.${className}:hover {\n`;
      Object.entries({ ...states.hover.colors, ...states.hover.effects }).forEach(([prop, value]) => {
        const kebabProp = prop.replace(/([A-Z])/g, '-$1').toLowerCase();
        css += `  ${kebabProp}: ${value};\n`;
      });
      css += `}\n\n`;
    }

    if (states.focus) {
      css += `.${className}:focus {\n`;
      Object.entries({ ...states.focus.colors, ...states.focus.effects }).forEach(([prop, value]) => {
        const kebabProp = prop.replace(/([A-Z])/g, '-$1').toLowerCase();
        css += `  ${kebabProp}: ${value};\n`;
      });
      // Ensure focus ring for accessibility
      css += `  outline: 2px solid currentColor;\n`;
      css += `  outline-offset: 2px;\n`;
      css += `}\n\n`;
    }

    if (states.active) {
      css += `.${className}:active {\n`;
      Object.entries({ ...states.active.colors, ...states.active.effects }).forEach(([prop, value]) => {
        const kebabProp = prop.replace(/([A-Z])/g, '-$1').toLowerCase();
        css += `  ${kebabProp}: ${value};\n`;
      });
      css += `}\n\n`;
    }

    if (states.disabled) {
      css += `.${className}:disabled,\n`;
      css += `.${className}[aria-disabled="true"] {\n`;
      Object.entries({ ...states.disabled.colors, ...states.disabled.effects }).forEach(([prop, value]) => {
        const kebabProp = prop.replace(/([A-Z])/g, '-$1').toLowerCase();
        css += `  ${kebabProp}: ${value};\n`;
      });
      css += `  cursor: not-allowed;\n`;
      css += `  opacity: 0.6;\n`;
      css += `}\n\n`;
    }

    return css;
  }

  /**
   * Sprint 35-50: Generate default interactive state styles
   * Used when no specific state variants are found in Figma
   */
  generateDefaultInteractiveStyles(className, componentType) {
    let css = '';

    // Only add interactive styles for interactive components
    const interactiveTypes = ['button', 'link', 'input', 'checkbox', 'radio', 'toggle', 'select', 'textarea'];
    if (!interactiveTypes.includes(componentType)) {
      return css;
    }

    // Default hover state
    css += `.${className}:hover:not(:disabled) {\n`;
    css += `  filter: brightness(1.1);\n`;
    css += `  cursor: pointer;\n`;
    css += `}\n\n`;

    // Default focus state with accessible focus ring
    css += `.${className}:focus-visible {\n`;
    css += `  outline: 2px solid #0066cc;\n`;
    css += `  outline-offset: 2px;\n`;
    css += `}\n\n`;

    // Default active/pressed state
    css += `.${className}:active:not(:disabled) {\n`;
    css += `  transform: scale(0.98);\n`;
    css += `}\n\n`;

    // Default disabled state
    css += `.${className}:disabled,\n`;
    css += `.${className}[aria-disabled="true"] {\n`;
    css += `  opacity: 0.5;\n`;
    css += `  cursor: not-allowed;\n`;
    css += `  pointer-events: none;\n`;
    css += `}\n\n`;

    return css;
  }

  /**
   * Sprint 23-34: Tabs element with accessibility
   */
  generateTabsJSX(className, props, styleAttr) {
    let jsx = `    <div className="${className}"${styleAttr}>\n`;
    jsx += `      <div className="${className}__list" role="tablist">\n`;
    jsx += `        {tabs?.map((tab, index) => (\n`;
    jsx += `          <button\n`;
    jsx += `            key={tab.id || index}\n`;
    jsx += `            className={\`${className}__tab \${activeTab === (tab.id || index) ? '${className}__tab--active' : ''}\`}\n`;
    jsx += `            role="tab"\n`;
    jsx += `            aria-selected={activeTab === (tab.id || index)}\n`;
    jsx += `            onClick={() => onTabChange?.(tab.id || index)}\n`;
    jsx += `          >\n`;
    jsx += `            {tab.label}\n`;
    jsx += `          </button>\n`;
    jsx += `        ))}\n`;
    jsx += `      </div>\n`;
    jsx += `      <div className="${className}__panel" role="tabpanel">\n`;
    jsx += `        {children}\n`;
    jsx += `      </div>\n`;
    jsx += `    </div>\n`;
    return jsx;
  }

  /**
   * Sprint 32: Convert style object to JSX inline style string
   * Sprint 13-22: Fixed quote escaping for string values
   */
  styleObjectToString(styles) {
    const entries = Object.entries(styles)
      .filter(([, value]) => value !== undefined && value !== null)
      .map(([key, value]) => {
        // Convert kebab-case to camelCase for React
        const camelKey = key.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
        // Quote string values, escape single quotes, keep numbers/objects as-is
        if (typeof value === 'string') {
          const escapedValue = value.replace(/'/g, "\\'");
          return `${camelKey}: '${escapedValue}'`;
        }
        return `${camelKey}: ${value}`;
      });

    return `{ ${entries.join(', ')} }`;
  }

  /**
   * Helper: Generate styles
   */
  generateStyles(componentData, config) {
    const { name, styles } = componentData;
    const className = this.toKebabCase(name);

    if (config.styleFormat === 'css-modules') {
      return this.generateCSSModules(className, styles);
    }

    return '';
  }

  /**
   * Helper: Generate CSS modules - Sprint 32: Enhanced with all style types
   */
  generateCSSModules(className, styles) {
    let css = `.${className} {\n`;

    // Collect all styles from all categories
    const allStyles = {
      ...styles.layout,
      ...styles.typography,
      ...styles.colors,
      ...styles.effects
    };

    // Write all style properties
    Object.entries(allStyles).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        css += `  ${this.toKebabCase(key)}: ${value};\n`;
      }
    });

    // Add base styling if no styles extracted
    if (Object.keys(allStyles).length === 0) {
      css += `  /* Add component styles */\n`;
    }

    css += `}\n`;

    // Generate responsive media queries
    if (styles.responsive) {
      if (styles.responsive.mobile && Object.keys(styles.responsive.mobile).length > 0) {
        css += `\n@media (max-width: 767px) {\n  .${className} {\n`;
        Object.entries(styles.responsive.mobile).forEach(([key, value]) => {
          if (value) css += `    ${this.toKebabCase(key)}: ${value};\n`;
        });
        css += `  }\n}\n`;
      }
      if (styles.responsive.tablet && Object.keys(styles.responsive.tablet).length > 0) {
        css += `\n@media (min-width: 768px) and (max-width: 1023px) {\n  .${className} {\n`;
        Object.entries(styles.responsive.tablet).forEach(([key, value]) => {
          if (value) css += `    ${this.toKebabCase(key)}: ${value};\n`;
        });
        css += `  }\n}\n`;
      }
    }

    return css;
  }

  /**
   * Helper: Generate exports
   */
  generateExports(componentData, config) {
    return `export default ${componentData.name};`;
  }

  /**
   * Helper: Select template
   */
  selectTemplate(config) {
    const templateKey = `${config.framework}-${config.componentFormat}`;
    return this.templates.get(templateKey) || this.templates.get('base');
  }

  /**
   * Helper: Assemble code
   */
  assembleCode(structure, template) {
    return [
      structure.imports,
      '',
      structure.component,
      '',
      structure.exports
    ].filter(Boolean).join('\n');
  }

  /**
   * Helper: Utility functions
   */
  capitalize(str) {
    return str.charAt(0).toUpperCase() + str.slice(1);
  }

  toKebabCase(str) {
    return str.replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase();
  }

  inferPropType(value) {
    if (typeof value === 'string') return 'string';
    if (typeof value === 'number') return 'number';
    if (typeof value === 'boolean') return 'boolean';
    if (Array.isArray(value)) return 'array';
    if (typeof value === 'object') return 'object';
    return 'any';
  }

  getCommonPropsForType(type) {
    const commonProps = {
      button: {
        onClick: { type: 'function', required: false },
        disabled: { type: 'boolean', required: false },
        variant: { type: 'string', required: false }
      },
      input: {
        value: { type: 'string', required: true },
        onChange: { type: 'function', required: true },
        placeholder: { type: 'string', required: false }
      }
    };

    return commonProps[type] || {};
  }

  inferRole(component) {
    const type = this.detectComponentType(component);
    const roles = {
      button: 'button',
      input: 'textbox',
      navigation: 'navigation',
      list: 'list',
      modal: 'dialog'
    };
    return roles[type] || 'region';
  }

  /**
   * Optimization helpers (placeholders for now)
   */
  applyTreeshaking(code) { return code; }
  applyLazyLoading(code, data) { return code; }
  applyCodeSplitting(code, data) { return code; }
  applyMinification(code) { return code; }
  formatCode(code, config) { return code; }
  addDocumentation(code, config) { return code; }
  async validateSyntax(code, config) { return true; }

  async generateTestFile(data, config) { return '// Test file'; }
  async generateStoryFile(data, config) { return '// Story file'; }
  async generateDocumentation(data, config) { return '// Documentation'; }
  async generateTypeDefinitions(data, config) { return '// Type definitions'; }

  /**
   * Sprint 35-50: Enhanced style file generation with interactive states
   */
  async generateStyleFile(data, config) {
    const className = this.toKebabCase(data.name);
    const componentType = data.type || 'container';
    let css = `/* Styles for ${data.name} */\n\n`;

    // Base styles
    if (data.styles) {
      css += `.${className} {\n`;
      const allStyles = {
        ...data.styles.layout,
        ...data.styles.typography,
        ...data.styles.colors,
        ...data.styles.effects
      };

      Object.entries(allStyles).forEach(([prop, value]) => {
        const kebabProp = prop.replace(/([A-Z])/g, '-$1').toLowerCase();
        css += `  ${kebabProp}: ${value};\n`;
      });
      css += `}\n\n`;
    }

    // Extract interactive states from source component if available
    if (data._figma) {
      const interactiveStates = this.extractInteractiveStates(data._figma);
      const hasExplicitStates = Object.values(interactiveStates).some(s => s !== null);

      if (hasExplicitStates) {
        css += `/* Interactive states from Figma */\n`;
        css += this.generateInteractiveStateStyles(className, interactiveStates);
      } else {
        css += `/* Default interactive states */\n`;
        css += this.generateDefaultInteractiveStyles(className, componentType);
      }
    } else {
      css += `/* Default interactive states */\n`;
      css += this.generateDefaultInteractiveStyles(className, componentType);
    }

    // Variant styles if component has variants
    if (data._figma && data._figma.type === 'COMPONENT_SET') {
      const variantStyles = this.extractVariantStyles(data._figma);
      if (Object.keys(variantStyles).length > 0) {
        css += `/* Variant styles */\n`;
        Object.entries(variantStyles).forEach(([variantName, styles]) => {
          css += `.${className}--${variantName} {\n`;
          const mergedStyles = { ...styles.colors, ...styles.effects };
          Object.entries(mergedStyles).forEach(([prop, value]) => {
            const kebabProp = prop.replace(/([A-Z])/g, '-$1').toLowerCase();
            css += `  ${kebabProp}: ${value};\n`;
          });
          css += `}\n\n`;
        });
      }
    }

    return {
      filename: `${className}.css`,
      content: css
    };
  }

  /**
   * Sprint 32: Vue Component Generator (Multi-framework support)
   */
  generateVueComponent(componentData, config) {
    const { name, props, styles } = componentData;
    const className = this.toKebabCase(name);

    // Build styles for scoped CSS
    const inlineStyles = this.buildInlineStyles(componentData);
    const cssContent = this.generateVueScopedCSS(className, inlineStyles);

    // Generate props definitions
    const propsDefinition = this.generateVuePropsDefinition(props);

    let template = `<template>\n`;
    template += `  <div class="${className}">\n`;
    template += `    <slot></slot>\n`;
    template += `  </div>\n`;
    template += `</template>\n\n`;

    let script = `<script setup${config.typescript ? ' lang="ts"' : ''}>\n`;
    if (config.typescript && Object.keys(props).length > 0) {
      script += this.generateVueTypeScript(name, props);
    }
    script += propsDefinition;
    script += `</script>\n\n`;

    let style = `<style scoped>\n`;
    style += cssContent;
    style += `</style>\n`;

    return template + script + style;
  }

  generateVuePropsDefinition(props) {
    if (Object.keys(props).length === 0) return '';

    let code = `defineProps({\n`;
    Object.entries(props).forEach(([propName, propDef]) => {
      const type = this.mapPropTypeToVue(propDef.type);
      const required = propDef.required ? 'true' : 'false';
      code += `  ${propName}: { type: ${type}, required: ${required} },\n`;
    });
    code += `});\n`;
    return code;
  }

  generateVueTypeScript(name, props) {
    let code = `interface ${name}Props {\n`;
    Object.entries(props).forEach(([propName, propDef]) => {
      const required = propDef.required ? '' : '?';
      const type = this.mapPropTypeToTS(propDef.type);
      code += `  ${propName}${required}: ${type};\n`;
    });
    code += `}\n\n`;
    return code;
  }

  generateVueScopedCSS(className, styles) {
    let css = `.${className} {\n`;
    Object.entries(styles).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        css += `  ${this.toKebabCase(key)}: ${value};\n`;
      }
    });
    css += `}\n`;
    return css;
  }

  mapPropTypeToVue(type) {
    const typeMap = {
      'string': 'String',
      'number': 'Number',
      'boolean': 'Boolean',
      'array': 'Array',
      'object': 'Object',
      'function': 'Function',
      'any': null
    };
    return typeMap[type] || 'null';
  }

  /**
   * Sprint 32: Svelte Component Generator (Multi-framework support)
   */
  generateSvelteComponent(componentData, config) {
    const { name, props, styles } = componentData;
    const className = this.toKebabCase(name);

    // Build styles
    const inlineStyles = this.buildInlineStyles(componentData);

    // Generate props
    let script = `<script${config.typescript ? ' lang="ts"' : ''}>\n`;
    Object.entries(props).forEach(([propName, propDef]) => {
      const type = config.typescript ? `: ${this.mapPropTypeToTS(propDef.type)}` : '';
      const defaultValue = propDef.default !== undefined ? ` = ${JSON.stringify(propDef.default)}` : '';
      script += `  export let ${propName}${type}${defaultValue};\n`;
    });
    script += `</script>\n\n`;

    let template = `<div class="${className}">\n`;
    template += `  <slot></slot>\n`;
    template += `</div>\n\n`;

    let style = `<style>\n`;
    style += `.${className} {\n`;
    Object.entries(inlineStyles).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        style += `  ${this.toKebabCase(key)}: ${value};\n`;
      }
    });
    style += `}\n`;
    style += `</style>\n`;

    return script + template + style;
  }

  requiresSeparateStyleFile(config) {
    return config.styleFormat === 'css' || config.styleFormat === 'scss';
  }

  /**
   * Helper: Get the actual component node for style extraction
   * For COMPONENT_SET, returns the first child (default variant)
   * For COMPONENT, returns the component itself
   */
  getStyleSourceNode(component) {
    if (component.type === 'COMPONENT_SET' && component.children?.length > 0) {
      // Return first child as default variant
      return component.children[0];
    }
    return component;
  }

  /**
   * Sprint 11-12: Token resolution helper
   * Resolves token references from tokenDependencies to CSS variable syntax
   */
  resolveTokenReferences(component, tokens = null) {
    const node = this.getStyleSourceNode(component);
    const deps = node.tokenDependencies || {};
    const resolved = {
      colors: {},
      typography: {},
      spacing: {},
      effects: {},
      borderRadius: {}
    };

    // Resolve color tokens
    if (deps.colors?.length > 0 && tokens?.colors) {
      deps.colors.forEach(colorName => {
        const tokenValue = tokens.colors[colorName.toLowerCase()];
        if (tokenValue) {
          resolved.colors[colorName] = {
            variable: `var(--color-${colorName})`,
            value: tokenValue.value || tokenValue.rgb
          };
        }
      });
    }

    // Resolve typography tokens
    if (deps.typography?.length > 0 && tokens?.typography) {
      deps.typography.forEach(typeName => {
        const tokenValue = tokens.typography[typeName.toLowerCase()];
        if (tokenValue) {
          resolved.typography[typeName] = {
            variable: `var(--font-${typeName})`,
            ...tokenValue
          };
        }
      });
    }

    // Resolve borderRadius tokens
    if (deps.borderRadiusValues?.length > 0 && tokens?.borderRadius) {
      // Map pixel values to token names
      const radiusTokens = Object.entries(tokens.borderRadius);
      deps.borderRadiusValues.forEach(({ value }) => {
        const matchingToken = radiusTokens.find(([, v]) => v === `${value}px`);
        if (matchingToken) {
          resolved.borderRadius[value] = {
            variable: `var(--radius-${matchingToken[0]})`,
            value: matchingToken[1]
          };
        }
      });
    }

    return resolved;
  }

  /**
   * Sprint 11-12: Generate CSS variable imports for token usage
   */
  generateTokenImports(tokenDependencies) {
    const imports = [];
    const node = typeof tokenDependencies === 'object' && tokenDependencies.tokenDependencies
      ? tokenDependencies
      : { tokenDependencies };

    const deps = node.tokenDependencies || tokenDependencies || {};

    if (deps.colors?.length > 0) {
      imports.push(`import { tokens } from './tokens';`);
    }

    return imports.join('\n');
  }

  /**
   * Sprint 32: Enhanced style extraction from Figma data
   * Sprint 110: Fixed to read from correct node (children for COMPONENT_SET)
   */
  extractLayoutStyles(component) {
    const node = this.getStyleSourceNode(component);
    const styles = {};
    const figmaStyles = node.styles || node.absoluteBoundingBox || {};

    // Extract dimensions from node
    if (figmaStyles.width || node.width) {
      styles.width = `${figmaStyles.width || node.width}px`;
    }
    if (figmaStyles.height || node.height) {
      styles.height = `${figmaStyles.height || node.height}px`;
    }

    // Extract layout properties from node
    if (node.layoutMode) {
      styles.display = 'flex';
      styles.flexDirection = node.layoutMode === 'VERTICAL' ? 'column' : 'row';
    }
    if (node.itemSpacing) {
      styles.gap = `${node.itemSpacing}px`;
    }

    // Extract padding - check tokenDependencies.spacingValues first (more reliable)
    const spacingValues = node.tokenDependencies?.spacingValues || [];
    if (spacingValues.length > 0) {
      const paddingTop = spacingValues.find(s => s.type === 'padding-top')?.value || 0;
      const paddingRight = spacingValues.find(s => s.type === 'padding-right')?.value || 0;
      const paddingBottom = spacingValues.find(s => s.type === 'padding-bottom')?.value || 0;
      const paddingLeft = spacingValues.find(s => s.type === 'padding-left')?.value || 0;
      const gap = spacingValues.find(s => s.type === 'gap')?.value;

      if (paddingTop || paddingRight || paddingBottom || paddingLeft) {
        styles.padding = `${paddingTop}px ${paddingRight}px ${paddingBottom}px ${paddingLeft}px`;
      }
      if (gap) {
        styles.gap = `${gap}px`;
      }
    } else if (node.paddingLeft || node.paddingTop || node.paddingRight || node.paddingBottom) {
      styles.padding = `${node.paddingTop || 0}px ${node.paddingRight || 0}px ${node.paddingBottom || 0}px ${node.paddingLeft || 0}px`;
    }

    // Alignment
    if (node.primaryAxisAlignItems) {
      const alignMap = { MIN: 'flex-start', CENTER: 'center', MAX: 'flex-end', SPACE_BETWEEN: 'space-between' };
      styles.justifyContent = alignMap[node.primaryAxisAlignItems] || 'flex-start';
    }
    if (node.counterAxisAlignItems) {
      const alignMap = { MIN: 'flex-start', CENTER: 'center', MAX: 'flex-end' };
      styles.alignItems = alignMap[node.counterAxisAlignItems] || 'flex-start';
    }

    return styles;
  }

  extractTypographyStyles(component) {
    const styles = {};
    const node = this.getStyleSourceNode(component);

    // Find TEXT children to extract typography from
    const findTextNode = (n) => {
      if (n.type === 'TEXT') return n;
      if (n.children) {
        for (const child of n.children) {
          const found = findTextNode(child);
          if (found) return found;
        }
      }
      return null;
    };

    const textNode = findTextNode(node);
    if (textNode) {
      // Extract from TEXT node properties
      if (textNode.fontName?.family) {
        styles.fontFamily = `'${textNode.fontName.family}', sans-serif`;
      }
      if (textNode.fontSize) {
        styles.fontSize = `${textNode.fontSize}px`;
      }
      if (textNode.fontName?.style) {
        // Map font style to weight
        const styleToWeight = {
          'Thin': 100, 'ExtraLight': 200, 'Light': 300, 'Regular': 400,
          'Medium': 500, 'SemiBold': 600, 'Bold': 700, 'ExtraBold': 800, 'Black': 900
        };
        styles.fontWeight = styleToWeight[textNode.fontName.style] || 400;
      }
    }

    // Fallback to legacy textStyle property
    const textStyle = node.style || node.textStyle || {};
    if (!styles.fontFamily && textStyle.fontFamily) {
      styles.fontFamily = `'${textStyle.fontFamily}', sans-serif`;
    }
    if (!styles.fontSize && textStyle.fontSize) {
      styles.fontSize = `${textStyle.fontSize}px`;
    }
    if (!styles.fontWeight && textStyle.fontWeight) {
      styles.fontWeight = textStyle.fontWeight;
    }
    if (textStyle.lineHeightPx) {
      styles.lineHeight = `${textStyle.lineHeightPx}px`;
    } else if (textStyle.lineHeightPercent) {
      styles.lineHeight = `${textStyle.lineHeightPercent}%`;
    }
    if (textStyle.letterSpacing) {
      styles.letterSpacing = `${textStyle.letterSpacing}px`;
    }
    if (textStyle.textAlignHorizontal) {
      const alignMap = { LEFT: 'left', CENTER: 'center', RIGHT: 'right', JUSTIFIED: 'justify' };
      styles.textAlign = alignMap[textStyle.textAlignHorizontal] || 'left';
    }
    if (textStyle.textDecoration) {
      styles.textDecoration = textStyle.textDecoration.toLowerCase();
    }

    return styles;
  }

  extractColorStyles(component) {
    const styles = {};
    const node = this.getStyleSourceNode(component);
    const fills = node.fills || [];
    const strokes = node.strokes || [];

    // Background/fill color
    const solidFill = fills.find(f => f.type === 'SOLID' && f.visible !== false);
    if (solidFill?.color) {
      const { r, g, b, a } = solidFill.color;
      const opacity = solidFill.opacity ?? a ?? 1;
      styles.backgroundColor = opacity < 1
        ? `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${opacity})`
        : `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
    }

    // Gradient fills
    const gradientFill = fills.find(f => f.type?.includes('GRADIENT') && f.visible !== false);
    if (gradientFill?.gradientStops) {
      const stops = gradientFill.gradientStops.map(stop => {
        const { r, g, b, a } = stop.color;
        return `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${a || 1}) ${Math.round(stop.position * 100)}%`;
      }).join(', ');

      if (gradientFill.type === 'GRADIENT_LINEAR') {
        styles.background = `linear-gradient(180deg, ${stops})`;
      } else if (gradientFill.type === 'GRADIENT_RADIAL') {
        styles.background = `radial-gradient(circle, ${stops})`;
      }
    }

    // Border/stroke color
    const solidStroke = strokes.find(s => s.type === 'SOLID' && s.visible !== false);
    if (solidStroke?.color) {
      const { r, g, b, a } = solidStroke.color;
      styles.borderColor = `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${a || 1})`;
    }

    // Text color - find TEXT children and extract their fill color
    const findTextNode = (n) => {
      if (n.type === 'TEXT') return n;
      if (n.children) {
        for (const child of n.children) {
          const found = findTextNode(child);
          if (found) return found;
        }
      }
      return null;
    };

    const textNode = findTextNode(node);
    if (textNode?.fills?.length > 0) {
      const textFill = textNode.fills.find(f => f.type === 'SOLID' && f.visible !== false);
      if (textFill?.color) {
        const { r, g, b, a } = textFill.color;
        styles.color = `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${a || 1})`;
      }
    }

    return styles;
  }

  extractEffectStyles(component) {
    const styles = {};
    const node = this.getStyleSourceNode(component);
    const effects = node.effects || [];

    // Box shadow
    const shadows = effects.filter(e => (e.type === 'DROP_SHADOW' || e.type === 'INNER_SHADOW') && e.visible !== false);
    if (shadows.length > 0) {
      styles.boxShadow = shadows.map(shadow => {
        const { r, g, b, a } = shadow.color || { r: 0, g: 0, b: 0, a: 0.25 };
        const inset = shadow.type === 'INNER_SHADOW' ? 'inset ' : '';
        return `${inset}${shadow.offset?.x || 0}px ${shadow.offset?.y || 0}px ${shadow.radius || 0}px ${shadow.spread || 0}px rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${a || 0.25})`;
      }).join(', ');
    }

    // Blur
    const blur = effects.find(e => e.type === 'LAYER_BLUR' && e.visible !== false);
    if (blur?.radius) {
      styles.filter = `blur(${blur.radius}px)`;
    }

    // Background blur
    const bgBlur = effects.find(e => e.type === 'BACKGROUND_BLUR' && e.visible !== false);
    if (bgBlur?.radius) {
      styles.backdropFilter = `blur(${bgBlur.radius}px)`;
    }

    // Border radius - check node and tokenDependencies
    if (node.cornerRadius) {
      styles.borderRadius = `${node.cornerRadius}px`;
    } else if (node.rectangleCornerRadii) {
      const [tl, tr, br, bl] = node.rectangleCornerRadii;
      styles.borderRadius = `${tl}px ${tr}px ${br}px ${bl}px`;
    } else if (node.tokenDependencies?.borderRadiusValues?.length > 0) {
      // Use first borderRadius value from tokenDependencies
      const radiusValue = node.tokenDependencies.borderRadiusValues[0]?.value;
      if (radiusValue) {
        styles.borderRadius = `${radiusValue}px`;
      }
    }

    // Border width
    if (node.strokeWeight) {
      styles.borderWidth = `${node.strokeWeight}px`;
      styles.borderStyle = 'solid';
    }

    // Opacity
    if (node.opacity !== undefined && node.opacity < 1) {
      styles.opacity = node.opacity;
    }

    return styles;
  }

  extractResponsiveStyles(component) {
    // Check for responsive variants or constraints
    const responsive = {
      mobile: {},
      tablet: {},
      desktop: {}
    };

    // Extract from constraints if available
    if (component.constraints) {
      const { horizontal, vertical } = component.constraints;

      if (horizontal === 'SCALE' || horizontal === 'STRETCH') {
        responsive.base = { width: '100%' };
      }
      if (vertical === 'SCALE' || vertical === 'STRETCH') {
        responsive.base = { ...responsive.base, height: '100%' };
      }
    }

    // Extract from component set variants if this is a responsive component
    // Support both array format (legacy) and object format (new COMPONENT_SET extraction)
    if (component.variants) {
      const variantsArray = Array.isArray(component.variants)
        ? component.variants
        : component.children || []; // For object format, use children for responsive checking

      variantsArray.forEach(variant => {
        const variantName = (variant.name || '').toLowerCase();
        if (variantName.includes('mobile')) {
          responsive.mobile = this.extractLayoutStyles(variant);
        } else if (variantName.includes('tablet')) {
          responsive.tablet = this.extractLayoutStyles(variant);
        } else if (variantName.includes('desktop')) {
          responsive.desktop = this.extractLayoutStyles(variant);
        }
      });
    }

    return responsive;
  }

  generateMetadata(data, config) {
    return {
      generated: new Date().toISOString(),
      framework: config.framework,
      version: this.version
    };
  }

  extractImports(code) { return []; }
  extractExports(code) { return []; }
  analyzeDependencies(code, config) { return []; }

  // ============================================
  // Sprint 6.5: File Conflict Detection Methods
  // ============================================

  /**
   * Initialize conflict detector for a project (Sprint 6.5)
   * @param {string} projectPath - Path to project root
   */
  async initConflictDetector(projectPath) {
    this.conflictDetector = new FileConflictDetector();
    await this.conflictDetector.initialize(projectPath);
    this.emit('conflict:detector-initialized', { projectPath });
    return this.conflictDetector;
  }

  /**
   * Set conflict resolution strategy
   * @param {string} strategy - 'prompt', 'overwrite', or 'skip'
   */
  setConflictStrategy(strategy) {
    if (!['prompt', 'overwrite', 'skip'].includes(strategy)) {
      throw new Error(`Invalid conflict strategy: ${strategy}`);
    }
    this.conflictStrategy = strategy;
  }

  /**
   * Generate code with conflict detection (Sprint 6.5)
   * @param {Object} designComponent - Design component data
   * @param {string} outputPath - Target file path for generated code
   * @param {Object} options - Generation options
   * @returns {Object} Result with code, conflict info, and success status
   */
  async generateCodeWithConflictCheck(designComponent, outputPath, options = {}) {
    // Generate the code first
    const componentPackage = await this.generateCode(designComponent, options);

    // If no conflict detector, return standard result
    if (!this.conflictDetector) {
      return {
        success: true,
        componentPackage,
        outputPath
      };
    }

    // Check for conflicts
    const conflict = await this.conflictDetector.detectConflict(outputPath, componentPackage.code);

    if (conflict.hasConflict) {
      const strategy = options.conflictStrategy || this.conflictStrategy;

      this.emit('code:conflict', {
        component: componentPackage.name,
        path: outputPath,
        conflict
      });

      if (strategy === 'skip') {
        return {
          success: false,
          skipped: true,
          conflict,
          componentPackage,
          outputPath
        };
      }

      if (strategy === 'prompt') {
        return {
          success: false,
          needsResolution: true,
          conflict,
          componentPackage,
          outputPath
        };
      }

      // strategy === 'overwrite' - allow write to proceed
    }

    // Return result indicating write can proceed
    return {
      success: true,
      componentPackage,
      outputPath,
      conflictResolved: conflict.hasConflict ? 'overwritten' : null
    };
  }

  /**
   * Update hash after successful file write (Sprint 6.5)
   * @param {string} filePath - Path to the written file
   * @param {string} content - File content that was written
   * @param {Object} metadata - Optional metadata about the file
   */
  async updateFileHash(filePath, content, metadata = {}) {
    if (this.conflictDetector) {
      await this.conflictDetector.storeHash(filePath, content, metadata);
      this.emit('code:hash-updated', { filePath });
    }
  }

  /**
   * Check conflict status for a batch of files (Sprint 6.5)
   * @param {Array} files - Array of {path, content} objects
   * @returns {Object} Batch conflict detection results
   */
  async checkBatchConflicts(files) {
    if (!this.conflictDetector) {
      return { hasConflicts: false, total: files.length, conflicts: 0 };
    }

    return this.conflictDetector.detectConflicts(files);
  }
}

module.exports = SmartCodeGenerator;