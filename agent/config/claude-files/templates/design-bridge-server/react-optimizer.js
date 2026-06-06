/**
 * React Optimizer
 * Optimizes code generation specifically for React applications
 * Sprint 14: React Optimizer
 *
 * v4.0.0 Integration:
 * - Supports registry v4.0.0 canonical IDs
 * - O(1) component lookup via RegistryManager
 * - Static optimize() accepts entries from v4 registry
 *
 * @version 2.0.0
 */

const SmartCodeGenerator = require('./smart-code-generator');

// Lazy-load RegistryManager to avoid circular dependencies (v4.0.0)
let _registryManagerModule = null;
function getRegistryManagerModule() {
  if (!_registryManagerModule) {
    try {
      _registryManagerModule = require('./registry-manager');
    } catch (e) {
      _registryManagerModule = null;
    }
  }
  return _registryManagerModule;
}


class ReactOptimizer {
  constructor() {
    this.name = 'ReactOptimizer';
    this.version = '1.0.0';
    this.framework = 'react';

    // React-specific configuration
    this.config = {
      version: '18.x',
      useHooks: true,
      useTypeScript: true,
      useMemo: true,
      useCallback: true,
      useContext: true,
      lazyComponents: true,
      errorBoundaries: true,
      suspense: true,
      strictMode: true,
      customHooks: true
    };

    // React patterns
    this.patterns = {
      hooks: this.getHookPatterns(),
      performance: this.getPerformancePatterns(),
      stateManagement: this.getStatePatterns(),
      composition: this.getCompositionPatterns()
    };
  }

  /**
   * Static optimize method for registry-based transformation
   * Accepts enriched input with raw data + registry metadata
   * @param {Object} input - Enriched input { raw, registry, options }
   * @returns {Object} Result with code, story, warnings
  
 *
 * v4.0.0 Integration:
 * - Supports registry v4.0.0 canonical IDs
 * - O(1) component lookup via RegistryManager
 * - Static optimize() accepts entries from v4 registry
 */
  static async optimize(input) {
    const { raw, registry, options = {} } = input;
    const instance = new ReactOptimizer();
    const warnings = [];

    // Build component data from raw + registry
    const componentData = instance.buildComponentData(raw, registry);

    // Generate component with enriched data
    const config = {
      ...instance.config,
      useTypeScript: options.typescript !== false,
      includeStyles: options.includeStyles !== false,
      ...options
    };

    let code;
    try {
      code = await instance.generateComponent(componentData, config);

      // Apply registry-aware optimizations
      if (registry.tokenDependencies) {
        code = instance.applyTokenDependencies(code, registry.tokenDependencies, config);
      }
      if (registry.interactiveStates) {
        code = instance.applyInteractiveStates(code, registry.interactiveStates, config);
      }
      if (registry.variants && registry.variants.length > 0) {
        code = instance.applyVariants(code, registry.variants, config);
      }
    } catch (error) {
      return { success: false, error: error.message, warnings };
    }

    // Generate story if requested
    let story = null;
    if (options.generateStory) {
      try {
        story = instance.generateStory(componentData, registry, config);
      } catch (error) {
        warnings.push(`Story generation failed: ${error.message}`);
      }
    }

    return {
      success: true,
      code,
      story,
      output: code, // Alias for compatibility
      warnings
    };
  }

  /**
   * Build component data from raw source and registry metadata
   */
  buildComponentData(raw, registry) {
    return {
      id: registry.id,
      name: registry.name || raw.name || 'Component',
      type: raw.type || 'component',
      props: this.extractProps(raw, registry),
      state: this.extractState(raw, registry),
      styles: this.extractStylesFromRaw(raw),
      children: raw.children || [],
      variants: registry.variants || [],
      category: registry.category
    };
  }

  /**
   * Extract visual styles from raw Figma data
   * Handles multiple data formats from different extraction sources
   */
  extractStylesFromRaw(raw) {
    // Priority 1: Visual properties from figma-component-extractor
    if (raw.visual) {
      return {
        fills: raw.visual.fills || [],
        strokes: raw.visual.strokes || [],
        effects: raw.visual.effects || [],
        cornerRadius: raw.visual.cornerRadius,
        opacity: raw.visual.opacity,
        absoluteBoundingBox: raw.visual.absoluteBoundingBox || raw.absoluteBoundingBox
      };
    }

    // Priority 2: Direct Figma properties (from raw extraction)
    if (raw.fills || raw.strokes || raw.effects) {
      return {
        fills: raw.fills || [],
        strokes: raw.strokes || [],
        effects: raw.effects || [],
        cornerRadius: raw.cornerRadius,
        opacity: raw.opacity,
        absoluteBoundingBox: raw.absoluteBoundingBox
      };
    }

    // Priority 3: _figma data from NLP or other sources
    if (raw._figma) {
      return {
        fills: raw._figma.fills || [],
        strokes: raw._figma.strokes || [],
        effects: raw._figma.effects || [],
        cornerRadius: raw._figma.cornerRadius,
        opacity: raw._figma.opacity,
        absoluteBoundingBox: raw._figma.absoluteBoundingBox || raw.absoluteBoundingBox
      };
    }

    // Priority 4: Existing styles object
    if (raw.styles && typeof raw.styles === 'object') {
      return raw.styles;
    }

    // Fallback: Return bounding box dimensions as minimal style info
    return {
      fills: [],
      strokes: [],
      effects: [],
      absoluteBoundingBox: raw.absoluteBoundingBox || {}
    };
  }

  /**
   * Convert extracted Figma styles to CSS properties
   * @param {Object} styles - Extracted styles from extractStylesFromRaw()
   * @returns {Object} CSS properties object
   */
  stylesToCSS(styles) {
    const css = {};

    if (!styles) return css;

    // Convert fills to backgroundColor/background
    if (styles.fills && styles.fills.length > 0) {
      const visibleFills = styles.fills.filter(f => f.visible !== false);
      if (visibleFills.length > 0) {
        const fill = visibleFills[0];
        if (fill.type === 'SOLID' && fill.color) {
          const { r, g, b } = fill.color;
          const alpha = fill.opacity !== undefined ? fill.opacity : 1;
          if (alpha < 1) {
            css.backgroundColor = `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${alpha})`;
          } else {
            css.backgroundColor = `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
          }
        } else if (fill.type === 'GRADIENT_LINEAR' && fill.gradientStops) {
          const stops = fill.gradientStops.map(stop => {
            const { r, g, b } = stop.color;
            return `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}) ${Math.round(stop.position * 100)}%`;
          }).join(', ');
          css.background = `linear-gradient(${stops})`;
        }
      }
    }

    // Convert cornerRadius to borderRadius
    if (styles.cornerRadius !== undefined && styles.cornerRadius !== null) {
      css.borderRadius = `${styles.cornerRadius}px`;
    }

    // Convert strokes to border
    if (styles.strokes && styles.strokes.length > 0) {
      const visibleStrokes = styles.strokes.filter(s => s.visible !== false);
      if (visibleStrokes.length > 0) {
        const stroke = visibleStrokes[0];
        if (stroke.color) {
          const { r, g, b } = stroke.color;
          const width = styles.strokeWeight || 1;
          css.border = `${width}px solid rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
        }
      }
    }

    // Convert effects to box-shadow
    if (styles.effects && styles.effects.length > 0) {
      const shadows = styles.effects.filter(e =>
        (e.type === 'DROP_SHADOW' || e.type === 'INNER_SHADOW') && e.visible !== false
      );
      if (shadows.length > 0) {
        const shadowStrings = shadows.map(shadow => {
          const x = shadow.offset?.x || 0;
          const y = shadow.offset?.y || 0;
          const blur = shadow.radius || 0;
          const spread = shadow.spread || 0;
          const color = shadow.color || { r: 0, g: 0, b: 0, a: 0.25 };
          const rgba = `rgba(${Math.round(color.r * 255)}, ${Math.round(color.g * 255)}, ${Math.round(color.b * 255)}, ${color.a || 0.25})`;
          const inset = shadow.type === 'INNER_SHADOW' ? 'inset ' : '';
          return `${inset}${x}px ${y}px ${blur}px ${spread}px ${rgba}`;
        });
        css.boxShadow = shadowStrings.join(', ');
      }
    }

    // Convert opacity
    if (styles.opacity !== undefined && styles.opacity !== null && styles.opacity < 1) {
      css.opacity = styles.opacity;
    }

    // Convert dimensions from absoluteBoundingBox
    if (styles.absoluteBoundingBox) {
      const { width, height } = styles.absoluteBoundingBox;
      if (width !== undefined) css.width = `${width}px`;
      if (height !== undefined) css.height = `${height}px`;
    }

    return css;
  }

  /**
   * Convert CSS object to inline style string
   * @param {Object} cssObj - CSS properties object
   * @returns {string} Inline style string
   */
  cssToStyleString(cssObj) {
    if (!cssObj || Object.keys(cssObj).length === 0) {
      return '';
    }

    return Object.entries(cssObj)
      .map(([key, value]) => {
        // Convert camelCase to kebab-case for CSS
        const cssKey = key.replace(/([A-Z])/g, '-$1').toLowerCase();
        return `${cssKey}: ${value}`;
      })
      .join('; ');
  }

  /**
   * Extract props from raw design data
   */
  extractProps(raw, registry) {
    const props = {};

    // Extract from component properties
    if (raw.componentProperties) {
      Object.entries(raw.componentProperties).forEach(([key, prop]) => {
        props[key] = {
          type: this.inferPropType(prop),
          default: prop.defaultValue,
          required: !prop.defaultValue
        };
      });
    }

    // Add interactive state props
    if (registry.interactiveStates) {
      if (registry.interactiveStates.disabled) {
        props.disabled = { type: 'boolean', default: false };
      }
    }

    return props;
  }

  /**
   * Extract state from raw design data
   */
  extractState(raw, registry) {
    const state = {};

    if (registry.interactiveStates) {
      if (registry.interactiveStates.hover) state.isHovered = false;
      if (registry.interactiveStates.focus) state.isFocused = false;
      if (registry.interactiveStates.active) state.isActive = false;
    }

    return state;
  }

  /**
   * Infer prop type from Figma component property
   */
  inferPropType(prop) {
    if (prop.type === 'BOOLEAN') return 'boolean';
    if (prop.type === 'TEXT') return 'string';
    if (prop.type === 'INSTANCE_SWAP') return 'any';
    if (prop.type === 'VARIANT') return 'string';
    return 'any';
  }

  /**
   * Apply token dependencies to generated code
   */
  applyTokenDependencies(code, tokenDeps, config) {
    // Add token imports at the top
    const tokenCategories = Object.keys(tokenDeps);
    if (tokenCategories.length === 0) return code;

    const imports = tokenCategories.map(cat => cat).join(', ');
    const tokenImport = `import { ${imports} } from '../tokens';\n`;

    // Insert after first import or at top
    if (code.includes('import ')) {
      const lastImportEnd = code.lastIndexOf("';") + 2;
      return code.slice(0, lastImportEnd) + '\n' + tokenImport + code.slice(lastImportEnd);
    }
    return tokenImport + code;
  }

  /**
   * Apply interactive states to generated code
   */
  applyInteractiveStates(code, states, config) {
    let enhanced = code;

    // Add state handlers
    const handlers = [];
    if (states.hover) {
      handlers.push('onMouseEnter={() => setIsHovered(true)}');
      handlers.push('onMouseLeave={() => setIsHovered(false)}');
    }
    if (states.focus) {
      handlers.push('onFocus={() => setIsFocused(true)}');
      handlers.push('onBlur={() => setIsFocused(false)}');
    }

    // Add handlers to root element
    if (handlers.length > 0) {
      enhanced = enhanced.replace(
        /<div className=/,
        `<div ${handlers.join(' ')} className=`
      );
    }

    return enhanced;
  }

  /**
   * Apply variants to generated code
   */
  applyVariants(code, variants, config) {
    // Add variant prop if not present
    if (!code.includes('variant')) {
      code = code.replace(
        /const \[/,
        "  variant = 'default',\n  const ["
      );
    }

    // Add variant-based className logic
    const variantClasses = variants.map(v =>
      `variant === '${v.name}' && '${v.name.toLowerCase()}'`
    ).join(', ');

    if (variantClasses) {
      code = code.replace(
        /className="([^"]+)"/,
        `className={\`$1 \${${variantClasses}}\`}`
      );
    }

    return code;
  }

  /**
   * Generate Storybook story for component (CSF3 format)
   * @param {Object} componentData - Component data with props
   * @param {Object} registry - Registry metadata
   * @param {Object} config - Generation config
   * @returns {string} Story file content
   */
  generateStory(componentData, registry, config) {
    const { name, props = {} } = componentData;

    let story = [];
    story.push(`import type { Meta, StoryObj } from '@storybook/react';`);
    story.push(`import ${name} from './${name}';`);
    story.push('');
    story.push(`const meta: Meta<typeof ${name}> = {`);
    story.push(`  title: '${registry.category || 'Components'}/${name}',`);
    story.push(`  component: ${name},`);
    story.push(`  parameters: {`);
    story.push(`    layout: 'centered',`);
    story.push(`  },`);
    story.push(`  tags: ['autodocs'],`);

    // Generate argTypes from props
    const argTypes = this.generateArgTypes(props);
    if (Object.keys(argTypes).length > 0) {
      story.push(`  argTypes: {`);
      Object.entries(argTypes).forEach(([propName, argType], index, arr) => {
        const isLast = index === arr.length - 1;
        if (argType.options) {
          story.push(`    ${propName}: { control: '${argType.control}', options: ${JSON.stringify(argType.options)} }${isLast ? '' : ','}`);
        } else {
          story.push(`    ${propName}: { control: '${argType.control}' }${isLast ? '' : ','}`);
        }
      });
      story.push(`  },`);
    }

    story.push('};');
    story.push('');
    story.push('export default meta;');
    story.push(`type Story = StoryObj<typeof ${name}>;`);
    story.push('');

    // Generate default args from props
    const defaultArgs = this.generateDefaultArgs(props);
    story.push('export const Default: Story = {');
    if (Object.keys(defaultArgs).length > 0) {
      story.push('  args: {');
      Object.entries(defaultArgs).forEach(([propName, value], index, arr) => {
        const isLast = index === arr.length - 1;
        const formattedValue = typeof value === 'string' ? `'${value}'` : value;
        story.push(`    ${propName}: ${formattedValue}${isLast ? '' : ','}`);
      });
      story.push('  },');
    } else {
      story.push('  args: {},');
    }
    story.push('};');

    // Add variant stories from registry
    if (registry.variants && registry.variants.length > 0) {
      registry.variants.forEach(variant => {
        const variantName = this.sanitizeVariantName(variant.name);
        story.push('');
        story.push(`export const ${variantName}: Story = {`);
        story.push('  args: {');
        // Merge default args with variant-specific props
        const variantArgs = Object.assign({}, defaultArgs, variant.props || {});
        Object.entries(variantArgs).forEach(([propName, value], index, arr) => {
          const isLast = index === arr.length - 1;
          const formattedValue = typeof value === 'string' ? `'${value}'` : value;
          story.push(`    ${propName}: ${formattedValue}${isLast ? '' : ','}`);
        });
        story.push('  },');
        story.push('};');
      });
    }

    return story.join('\n');
  }

  /**
   * Generate argTypes for Storybook controls
   * @param {Object} props - Component props definition
   * @returns {Object} argTypes configuration
   */
  generateArgTypes(props) {
    if (!props || Object.keys(props).length === 0) return {};

    const argTypes = {};
    Object.entries(props).forEach(([key, prop]) => {
      const propType = prop.type || prop.rawType || 'string';

      if (propType === 'enum' || (prop.values && Array.isArray(prop.values))) {
        argTypes[key] = { control: 'select', options: prop.values || [] };
      } else if (propType === 'boolean') {
        argTypes[key] = { control: 'boolean' };
      } else if (propType === 'number') {
        argTypes[key] = { control: 'number' };
      } else if (propType.includes && propType.includes('|')) {
        const values = propType.split('|').map(v => v.trim().replace(/['"]/g, ''));
        argTypes[key] = { control: 'select', options: values };
      } else {
        argTypes[key] = { control: 'text' };
      }
    });
    return argTypes;
  }

  /**
   * Generate default args from props
   * @param {Object} props - Component props definition
   * @returns {Object} Default args
   */
  generateDefaultArgs(props) {
    if (!props || Object.keys(props).length === 0) return {};

    const args = {};
    Object.entries(props).forEach(([key, prop]) => {
      if (prop.default !== undefined) {
        args[key] = prop.default;
      } else if (prop.type === 'boolean') {
        args[key] = false;
      } else if (prop.type === 'number') {
        args[key] = 0;
      } else if (prop.type === 'string') {
        args[key] = '';
      }
    });
    return args;
  }

  /**
   * Sanitize variant name for use as export name
   * @param {string} name - Variant name
   * @returns {string} Safe export name
   */
  sanitizeVariantName(name) {
    return name
      .replace(/[^a-zA-Z0-9]/g, '')
      .replace(/^[0-9]/, '_$&');
  }

  /**
   * Static transform method for wrapper compatibility
   * Transforms design tokens into React code files
   * @param {Object} tokens - Design tokens from .design/tokens/
   * @param {Object} options - Transformation options
   * @returns {Object} Result with generated files list
   */
  static async transform(tokens, options = {}) {
    const fs = require('fs');
    const path = require('path');
    const instance = new ReactOptimizer();
    const files = [];
    const outputPath = options.outputPath || './output';

    // Ensure output directories exist
    const tokensDir = path.join(outputPath, 'tokens');
    const componentsDir = path.join(outputPath, 'components');
    fs.mkdirSync(tokensDir, { recursive: true });
    fs.mkdirSync(componentsDir, { recursive: true });

    // Generate token files
    if (tokens.colors) {
      const colorTokens = instance.generateColorTokens(tokens.colors, options);
      const colorFile = path.join(tokensDir, options.typescript ? 'colors.ts' : 'colors.js');
      fs.writeFileSync(colorFile, colorTokens);
      files.push(colorFile);
    }

    if (tokens.typography) {
      const typographyTokens = instance.generateTypographyTokens(tokens.typography, options);
      const typographyFile = path.join(tokensDir, options.typescript ? 'typography.ts' : 'typography.js');
      fs.writeFileSync(typographyFile, typographyTokens);
      files.push(typographyFile);
    }

    if (tokens.spacing) {
      const spacingTokens = instance.generateSpacingTokens(tokens.spacing, options);
      const spacingFile = path.join(tokensDir, options.typescript ? 'spacing.ts' : 'spacing.js');
      fs.writeFileSync(spacingFile, spacingTokens);
      files.push(spacingFile);
    }

    // Generate index file
    const indexContent = instance.generateTokenIndex(tokens, options);
    const indexFile = path.join(tokensDir, options.typescript ? 'index.ts' : 'index.js');
    fs.writeFileSync(indexFile, indexContent);
    files.push(indexFile);

    // Generate components if component data exists
    if (tokens.components) {
      for (const [name, componentData] of Object.entries(tokens.components)) {
        const component = await instance.generateComponent({ name, ...componentData }, {
          ...instance.config,
          useTypeScript: options.typescript
        });
        const ext = options.typescript ? '.tsx' : '.jsx';
        const componentFile = path.join(componentsDir, name + ext);
        fs.writeFileSync(componentFile, component);
        files.push(componentFile);
      }
    }

    return { files, framework: 'react' };
  }

  /**
   * Generate color tokens file
   */
  generateColorTokens(colors, options) {
    const lines = ['// Auto-generated color tokens', ''];
    if (options.typescript) {
      lines.push('export const colors = {');
    } else {
      lines.push('export const colors = {');
    }

    for (const [key, value] of Object.entries(colors)) {
      if (typeof value === 'object') {
        lines.push(`  ${key}: {`);
        for (const [subKey, subValue] of Object.entries(value)) {
          lines.push(`    ${subKey}: '${subValue}',`);
        }
        lines.push('  },');
      } else {
        lines.push(`  ${key}: '${value}',`);
      }
    }

    lines.push('};');
    return lines.join('\n');
  }

  /**
   * Generate typography tokens file
   */
  generateTypographyTokens(typography, options) {
    const lines = ['// Auto-generated typography tokens', ''];
    lines.push('export const typography = {');

    for (const [key, value] of Object.entries(typography)) {
      if (typeof value === 'object') {
        lines.push(`  ${key}: {`);
        for (const [subKey, subValue] of Object.entries(value)) {
          const formattedValue = typeof subValue === 'string' ? `'${subValue}'` : subValue;
          lines.push(`    ${subKey}: ${formattedValue},`);
        }
        lines.push('  },');
      } else {
        const formattedValue = typeof value === 'string' ? `'${value}'` : value;
        lines.push(`  ${key}: ${formattedValue},`);
      }
    }

    lines.push('};');
    return lines.join('\n');
  }

  /**
   * Generate spacing tokens file
   */
  generateSpacingTokens(spacing, options) {
    const lines = ['// Auto-generated spacing tokens', ''];
    lines.push('export const spacing = {');

    for (const [key, value] of Object.entries(spacing)) {
      const formattedValue = typeof value === 'string' ? `'${value}'` : value;
      lines.push(`  ${key}: ${formattedValue},`);
    }

    lines.push('};');
    return lines.join('\n');
  }

  /**
   * Generate token index file
   */
  generateTokenIndex(tokens, options) {
    const lines = ['// Auto-generated token index', ''];

    if (tokens.colors) lines.push("export { colors } from './colors';");
    if (tokens.typography) lines.push("export { typography } from './typography';");
    if (tokens.spacing) lines.push("export { spacing } from './spacing';");

    return lines.join('\n');
  }

  /**
   * Optimize code for React
   */
  async optimize(code, componentData, config) {
    let optimizedCode = code;

    // Apply React-specific optimizations
    optimizedCode = await this.optimizeHooks(optimizedCode, componentData, config);
    optimizedCode = await this.optimizePerformance(optimizedCode, componentData, config);
    optimizedCode = await this.optimizeStateManagement(optimizedCode, componentData, config);
    optimizedCode = await this.optimizeComposition(optimizedCode, componentData, config);
    optimizedCode = await this.addErrorBoundary(optimizedCode, componentData, config);
    optimizedCode = await this.addSuspense(optimizedCode, componentData, config);

    return optimizedCode;
  }

  /**
   * Generate React component from design data
   */
  async generateComponent(componentData, config) {
    const mergedConfig = { ...this.config, ...config };

    // Generate component structure
    const component = mergedConfig.useTypeScript
      ? this.generateTypeScriptComponent(componentData, mergedConfig)
      : this.generateJavaScriptComponent(componentData, mergedConfig);

    return component;
  }

  /**
   * Generate TypeScript React component
   */
  generateTypeScriptComponent(data, config) {
    const { name, props, state, variants } = data;

    let code = [];

    // Imports
    code.push("import React, { useState, useEffect, useMemo, useCallback } from 'react';");
    if (config.styleFormat === 'styled-components') {
      code.push("import styled from 'styled-components';");
    }
    code.push('');

    // Type definitions
    code.push(this.generateTypeDefinitions(data));
    code.push('');

    // Component
    code.push(`const ${name}: React.FC<${name}Props> = ({`);

    // Props with defaults
    const propsList = Object.entries(props || {}).map(([key, prop]) => {
      return prop.default ? `  ${key} = ${JSON.stringify(prop.default)}` : `  ${key}`;
    });
    code.push(propsList.join(',\n'));
    code.push('}) => {');

    // Hooks
    if (state && Object.keys(state).length > 0) {
      code.push(this.generateStateHooks(state));
    }

    // Custom hooks
    if (config.customHooks) {
      code.push(this.generateCustomHooks(data));
    }

    // Memoized values
    if (config.useMemo) {
      code.push(this.generateMemoizedValues(data));
    }

    // Callbacks
    if (config.useCallback) {
      code.push(this.generateCallbacks(data));
    }

    // Effects
    code.push(this.generateEffects(data));

    // Render
    code.push('  return (');
    code.push(this.generateJSX(data, config));
    code.push('  );');
    code.push('};');
    code.push('');

    // Memoized export
    code.push(`export default React.memo(${name});`);

    return code.join('\n');
  }

  /**
   * Generate JavaScript React component
   */
  generateJavaScriptComponent(data, config) {
    const { name, props, state } = data;

    let code = [];

    // Imports
    code.push("import React, { useState, useEffect, useMemo, useCallback } from 'react';");
    code.push('');

    // Component
    code.push(`const ${name} = ({`);

    // Props
    const propsList = Object.keys(props || {});
    code.push(`  ${propsList.join(', ')}`);
    code.push('}) => {');

    // State
    if (state && Object.keys(state).length > 0) {
      code.push(this.generateStateHooks(state));
    }

    // Render
    code.push('  return (');
    code.push(this.generateJSX(data, config));
    code.push('  );');
    code.push('};');
    code.push('');

    code.push(`export default ${name};`);

    return code.join('\n');
  }

  /**
   * Optimize hooks usage
   */
  async optimizeHooks(code, data, config) {
    if (!config.useHooks) return code;

    // Detect and optimize useState patterns
    code = this.optimizeUseState(code);

    // Detect and optimize useEffect patterns
    code = this.optimizeUseEffect(code);

    // Add custom hooks where beneficial
    if (config.customHooks) {
      code = this.extractCustomHooks(code, data);
    }

    return code;
  }

  /**
   * Optimize performance
   */
  async optimizePerformance(code, data, config) {
    // Add React.memo where appropriate
    code = this.addMemoization(code, data);

    // Add useMemo for expensive computations
    if (config.useMemo) {
      code = this.addUseMemo(code, data);
    }

    // Add useCallback for function props
    if (config.useCallback) {
      code = this.addUseCallback(code, data);
    }

    // Add lazy loading
    if (config.lazyComponents) {
      code = this.addLazyLoading(code, data);
    }

    return code;
  }

  /**
   * Optimize state management
   */
  async optimizeStateManagement(code, data, config) {
    // Detect complex state and suggest useReducer
    if (this.shouldUseReducer(data.state)) {
      code = this.convertToUseReducer(code, data.state);
    }

    // Add context for shared state
    if (config.useContext && this.shouldUseContext(data)) {
      code = this.addContextProvider(code, data);
    }

    return code;
  }

  /**
   * Optimize composition
   */
  async optimizeComposition(code, data, config) {
    // Extract reusable components
    code = this.extractSubComponents(code, data);

    // Add render props where beneficial
    code = this.addRenderProps(code, data);

    // Use composition over inheritance
    code = this.favorComposition(code, data);

    return code;
  }

  /**
   * Add error boundary
   */
  async addErrorBoundary(code, data, config) {
    if (!config.errorBoundaries) return code;

    const errorBoundary = `
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    console.error('Error caught by boundary:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return <div>Something went wrong.</div>;
    }
    return this.props.children;
  }
}`;

    return errorBoundary + '\n\n' + code;
  }

  /**
   * Add Suspense wrapper
   */
  async addSuspense(code, data, config) {
    if (!config.suspense) return code;

    // Wrap lazy components in Suspense
    if (code.includes('React.lazy')) {
      code = code.replace(
        /return \(/,
        'return (\n    <React.Suspense fallback={<div>Loading...</div>}>'
      );
      code = code.replace(
        /\);$/m,
        '    </React.Suspense>\n  );'
      );
    }

    return code;
  }

  /**
   * Helper: Generate type definitions
   */
  generateTypeDefinitions(data) {
    const { name, props } = data;

    let types = [`interface ${name}Props {`];

    Object.entries(props || {}).forEach(([key, prop]) => {
      const isOptional = !prop.required ? '?' : '';
      types.push(`  ${key}${isOptional}: ${this.getTSType(prop.type)};`);
    });

    types.push('}');
    return types.join('\n');
  }

  /**
   * Helper: Generate state hooks
   */
  generateStateHooks(state) {
    const hooks = [];

    Object.entries(state).forEach(([key, initialValue]) => {
      const capitalizedKey = key.charAt(0).toUpperCase() + key.slice(1);
      hooks.push(`  const [${key}, set${capitalizedKey}] = useState(${JSON.stringify(initialValue)});`);
    });

    return hooks.join('\n');
  }

  /**
   * Helper: Generate custom hooks
   */
  generateCustomHooks(data) {
    const hooks = [];

    // Example: useWindowSize hook
    if (data.responsive) {
      hooks.push('  const windowSize = useWindowSize();');
    }

    // Example: useDebounce hook
    if (data.interactions?.some(i => i.type === 'input')) {
      hooks.push('  const debouncedValue = useDebounce(value, 300);');
    }

    return hooks.join('\n');
  }

  /**
   * Helper: Generate memoized values
   */
  generateMemoizedValues(data) {
    const memos = [];

    // Example memoization
    if (data.props?.items) {
      memos.push(`  const processedItems = useMemo(() => {
    return items.filter(item => item.active);
  }, [items]);`);
    }

    return memos.join('\n');
  }

  /**
   * Helper: Generate callbacks
   */
  generateCallbacks(data) {
    const callbacks = [];

    // Example callback
    if (data.props?.onClick) {
      callbacks.push(`  const handleClick = useCallback((event) => {
    event.preventDefault();
    onClick?.(event);
  }, [onClick]);`);
    }

    return callbacks.join('\n');
  }

  /**
   * Helper: Generate effects
   */
  generateEffects(data) {
    const effects = [];

    // Example effect
    if (data.state) {
      effects.push(`  useEffect(() => {
    // Component mount/unmount logic
  }, []);`);
    }

    return effects.join('\n');
  }

  /**
   * Infer semantic HTML element from component name and category
   */
  inferSemanticElement(name, category) {
    const lower = (name || '').toLowerCase();

    // Button patterns
    if (lower.includes('button') || lower.includes('btn') || lower.includes('cta')) {
      return 'button';
    }

    // Input patterns
    if (lower.includes('input') || lower.includes('textfield') || lower.includes('text-field')) {
      return 'input';
    }
    if (lower.includes('textarea') || lower.includes('text-area')) {
      return 'textarea';
    }
    if (lower.includes('checkbox')) {
      return 'input'; // type="checkbox" handled in attributes
    }
    if (lower.includes('radio')) {
      return 'input'; // type="radio" handled in attributes
    }
    if (lower.includes('select') || lower.includes('dropdown')) {
      return 'select';
    }

    // Navigation elements
    if (lower.includes('nav') && !lower.includes('navigate')) {
      return 'nav';
    }
    if (lower.includes('header') || lower.includes('appbar') || lower.includes('app-bar') || lower.includes('topbar')) {
      return 'header';
    }
    if (lower.includes('footer')) {
      return 'footer';
    }
    if (lower.includes('sidebar') || lower.includes('side-bar')) {
      return 'aside';
    }

    // Lists - check BEFORE 'main' which could match 'mainmenu'
    if ((lower.includes('list') || lower.includes('menu')) && !lower.includes('item')) {
      return 'ul';
    }
    if (lower.includes('listitem') || lower.includes('list-item') || lower.includes('menuitem')) {
      return 'li';
    }

    // Content containers
    if (lower.includes('card') || lower.includes('section')) {
      return 'section';
    }
    if (lower.includes('article') || lower.includes('post') || lower.includes('blog')) {
      return 'article';
    }
    if (lower.includes('main') && !lower.includes('maintain') && !lower.includes('menu')) {
      return 'main';
    }

    // Links
    if (lower.includes('link') || lower.includes('anchor')) {
      return 'a';
    }

    // Labels - check BEFORE 'form' which could match 'formlabel'
    if (lower.includes('label')) {
      return 'label';
    }

    // Form
    if (lower.includes('form') && !lower.includes('format') && !lower.includes('label')) {
      return 'form';
    }

    // Images
    if (lower.includes('image') || lower.includes('img') || lower.includes('avatar') || lower.includes('thumbnail')) {
      return 'img';
    }
    if (lower.includes('icon') && !lower.includes('button')) {
      return 'span'; // Icons are typically spans
    }

    // Text elements
    if (lower.includes('heading') || lower.includes('title') || lower.match(/h[1-6]/)) {
      // Try to infer heading level
      const levelMatch = lower.match(/h([1-6])/);
      if (levelMatch) return `h${levelMatch[1]}`;
      if (lower.includes('title') || lower.includes('heading')) return 'h2';
    }
    if (lower.includes('paragraph') || lower.includes('body-text')) {
      return 'p';
    }
    if (lower.includes('label')) {
      return 'label';
    }
    if (lower.includes('caption') || lower.includes('helper') || lower.includes('hint')) {
      return 'span';
    }

    // Table elements
    if (lower.includes('table') && !lower.includes('cell') && !lower.includes('row')) {
      return 'table';
    }

    // Default to div for generic containers
    return 'div';
  }

  /**
   * Get element-specific attributes based on inferred element type
   */
  getElementAttributes(element, name) {
    const lower = (name || '').toLowerCase();
    const attrs = [];

    switch (element) {
      case 'button':
        attrs.push('type="button"');
        attrs.push('onClick={onClick}');
        break;
      case 'input':
        if (lower.includes('checkbox')) {
          attrs.push('type="checkbox"');
          attrs.push('checked={checked}');
          attrs.push('onChange={onChange}');
        } else if (lower.includes('radio')) {
          attrs.push('type="radio"');
          attrs.push('checked={checked}');
          attrs.push('onChange={onChange}');
        } else {
          attrs.push('type="text"');
          attrs.push('value={value}');
          attrs.push('onChange={onChange}');
          attrs.push('placeholder={placeholder}');
        }
        break;
      case 'textarea':
        attrs.push('value={value}');
        attrs.push('onChange={onChange}');
        attrs.push('placeholder={placeholder}');
        break;
      case 'a':
        attrs.push('href={href}');
        break;
      case 'img':
        attrs.push('src={src}');
        attrs.push('alt={alt}');
        break;
      case 'label':
        attrs.push('htmlFor={htmlFor}');
        break;
    }

    return attrs;
  }

  /**
   * Helper: Generate JSX
   */
  generateJSX(data, config) {
    const { name, children, category } = data;
    const className = name.replace(/([A-Z])/g, '-$1').toLowerCase().slice(1);

    // Infer semantic element from component name
    const element = this.inferSemanticElement(name, category);
    const elementAttrs = this.getElementAttributes(element, name);

    // Build attributes string
    const attrsStr = elementAttrs.length > 0
      ? ` ${elementAttrs.join(' ')}`
      : '';

    // Self-closing elements
    const selfClosing = ['input', 'img', 'br', 'hr'].includes(element);

    if (selfClosing) {
      return `    <${element} className="${className}"${attrsStr} />`;
    }

    let jsx = [`    <${element} className="${className}"${attrsStr}>`];

    if (children && children.length > 0) {
      children.forEach(child => {
        jsx.push(`      <${child.name} />`);
      });
    } else if (element === 'button') {
      jsx.push('      {children}');
    } else {
      jsx.push(`      {/* ${name} content */}`);
    }

    jsx.push(`    </${element}>`);

    return jsx.join('\n');
  }

  /**
   * Helper: Get TypeScript type
   */
  getTSType(type) {
    const typeMap = {
      string: 'string',
      number: 'number',
      boolean: 'boolean',
      array: 'any[]',
      object: 'Record<string, any>',
      function: '(event: any) => void',
      any: 'any'
    };
    return typeMap[type] || 'any';
  }

  /**
   * Helper: Pattern definitions
   */
  getHookPatterns() {
    return {
      useState: /const \[(\w+), set\w+\] = useState/g,
      useEffect: /useEffect\(\(\) => \{/g,
      useMemo: /useMemo\(\(\) => \{/g,
      useCallback: /useCallback\(\(/g
    };
  }

  getPerformancePatterns() {
    return {
      memo: /React\.memo\(/g,
      lazy: /React\.lazy\(/g,
      suspense: /<React\.Suspense/g
    };
  }

  getStatePatterns() {
    return {
      reducer: /useReducer\(/g,
      context: /useContext\(/g
    };
  }

  getCompositionPatterns() {
    return {
      renderProp: /render=\{/g,
      children: /children\(/g
    };
  }

  /**
   * Helper: Optimization utilities
   */
  optimizeUseState(code) {
    // Combine related state into single object where appropriate
    return code;
  }

  optimizeUseEffect(code) {
    // Add dependency arrays and cleanup functions
    return code;
  }

  extractCustomHooks(code, data) {
    // Extract repeated logic into custom hooks
    return code;
  }

  addMemoization(code, data) {
    // Wrap component with React.memo if not already wrapped
    if (!code.includes('React.memo')) {
      code = code.replace(/export default (\w+);/, 'export default React.memo($1);');
    }
    return code;
  }

  addUseMemo(code, data) {
    // Add useMemo for expensive computations
    return code;
  }

  addUseCallback(code, data) {
    // Add useCallback for function props
    return code;
  }

  addLazyLoading(code, data) {
    // Convert imports to lazy loading where appropriate
    return code;
  }

  shouldUseReducer(state) {
    // Use reducer for complex state logic
    return state && Object.keys(state).length > 3;
  }

  convertToUseReducer(code, state) {
    // Convert useState to useReducer
    return code;
  }

  shouldUseContext(data) {
    // Use context for deeply nested props
    return data.children && data.children.length > 2;
  }

  addContextProvider(code, data) {
    // Add context provider wrapper
    return code;
  }

  extractSubComponents(code, data) {
    // Extract repeated JSX into sub-components
    return code;
  }

  addRenderProps(code, data) {
    // Add render props pattern where beneficial
    return code;
  }

  favorComposition(code, data) {
    // Use composition patterns over inheritance
    return code;
  }
}

module.exports = ReactOptimizer;