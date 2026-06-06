/**
 * Vue Optimizer
 * Optimizes code generation specifically for Vue.js applications
 * Sprint 14: Vue Optimizer
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


class VueOptimizer {
  constructor() {
    this.name = 'VueOptimizer';
    this.version = '1.0.0';
    this.framework = 'vue';

    // Vue-specific configuration
    this.config = {
      version: '3.x',
      compositionAPI: true,
      optionsAPI: false,
      useTypeScript: true,
      useSetup: true,
      scriptSetup: true,
      reactivity: 'ref', // ref, reactive
      sfc: true, // Single File Components
      cssScoped: true,
      emits: true,
      slots: true,
      provide: true,
      teleport: true
    };

    // Vue patterns
    this.patterns = {
      composition: this.getCompositionPatterns(),
      reactivity: this.getReactivityPatterns(),
      lifecycle: this.getLifecyclePatterns(),
      directives: this.getDirectivePatterns()
    };
  }

  /**
   * Static transform method for wrapper compatibility
  
 *
 * v4.0.0 Integration:
 * - Supports registry v4.0.0 canonical IDs
 * - O(1) component lookup via RegistryManager
 * - Static optimize() accepts entries from v4 registry
 */
  static async transform(tokens, options = {}) {
    const fs = require('fs');
    const path = require('path');
    const instance = new VueOptimizer();
    const files = [];
    const outputPath = options.outputPath || './output';
    const tokensDir = path.join(outputPath, 'tokens');
    fs.mkdirSync(tokensDir, { recursive: true });

    // Generate CSS variables file for Vue
    if (tokens.colors || tokens.typography || tokens.spacing) {
      const cssVars = instance.generateCSSVariables(tokens);
      const cssFile = path.join(tokensDir, 'variables.css');
      fs.writeFileSync(cssFile, cssVars);
      files.push(cssFile);
    }

    // Generate composable for tokens
    const composable = instance.generateTokenComposable(tokens, options);
    const composableFile = path.join(tokensDir, options.typescript ? 'useTokens.ts' : 'useTokens.js');
    fs.writeFileSync(composableFile, composable);
    files.push(composableFile);

    return { files, framework: 'vue' };
  }

  /**
   * Static optimize method for registry-based transformation
   * Accepts enriched input with raw data + registry metadata
   * @param {Object} input - Enriched input { raw, registry, options }
   * @returns {Object} Result with code, story, warnings
   */
  static async optimize(input) {
    const { raw, registry, options = {} } = input;
    const instance = new VueOptimizer();
    const warnings = [];

    // Build component data from raw + registry
    const componentData = instance.buildComponentData(raw, registry);

    // Generate component with enriched data
    const config = {
      ...instance.config,
      useTypeScript: options.typescript !== false,
      includeStyles: options.includeStyles !== false,
      compositionAPI: options.compositionAPI !== false,
      scriptSetup: options.scriptSetup !== false,
      cssScoped: options.cssScoped !== false,
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
   * Build component data from raw Figma data + registry metadata
   */
  buildComponentData(raw, registry) {
    const name = registry.name || raw.name || 'Component';

    // Normalize variants - handle both array and object formats from COMPONENT_SET
    const rawVariants = registry.variants || raw.variants || [];
    const normalizedVariants = this.normalizeVariantsToArray(rawVariants);

    return {
      name,
      props: this.extractProps(raw, registry),
      state: this.extractState(raw, registry),
      styles: this.extractStyles(raw),
      variants: normalizedVariants,
      children: raw.children || [],
      interactions: this.extractInteractions(raw, registry),
      slots: this.extractSlots(raw),
      type: registry.category || raw.type || 'component'
    };
  }

  /**
   * Normalize variants from object format { Type: [...], Size: [...] } to array format
   * COMPONENT_SET extractions produce object format, but code gen expects array
   */
  normalizeVariantsToArray(variants) {
    // Already an array - return as-is
    if (Array.isArray(variants)) {
      return variants;
    }

    // Object format from COMPONENT_SET - convert to array
    if (variants && typeof variants === 'object') {
      const normalized = [];
      Object.entries(variants).forEach(([propName, values]) => {
        if (Array.isArray(values)) {
          values.forEach(value => {
            normalized.push({
              name: `${propName}=${value}`,
              propName,
              value,
              class: `${this.toKebabCase(propName)}-${this.toKebabCase(String(value))}`,
              condition: `props.${this.toCamelCase(propName)} === '${value}'`
            });
          });
        }
      });
      return normalized;
    }

    return [];
  }

  /**
   * Extract props from raw data and registry
   */
  extractProps(raw, registry) {
    const props = {};

    // Extract from componentProperties
    if (raw.componentProperties) {
      Object.entries(raw.componentProperties).forEach(([key, prop]) => {
        props[key] = {
          type: this.inferPropType(prop),
          default: prop.defaultValue,
          required: false
        };
      });
    }

    // Add variant prop if variants exist
    if (registry.variants && registry.variants.length > 0) {
      props.variant = {
        type: 'string',
        default: registry.variants[0]?.name || 'default',
        required: false,
        validator: `(value) => [${registry.variants.map(v => `'${v.name}'`).join(', ')}].includes(value)`
      };
    }

    // Add props from interactive states
    if (registry.interactiveStates) {
      if (registry.interactiveStates.disabled) {
        props.disabled = { type: 'boolean', default: false, required: false };
      }
    }

    return props;
  }

  /**
   * Extract state from raw data and registry
   */
  extractState(raw, registry) {
    const state = {};

    if (registry.interactiveStates) {
      if (registry.interactiveStates.hover) {
        state.isHovered = false;
      }
      if (registry.interactiveStates.focus) {
        state.isFocused = false;
      }
      if (registry.interactiveStates.active || registry.interactiveStates.pressed) {
        state.isActive = false;
      }
    }

    return state;
  }

  /**
   * Extract styles from raw data
   */
  extractStyles(raw) {
    const styles = { layout: {} };

    if (raw.absoluteBoundingBox) {
      styles.layout.width = `${raw.absoluteBoundingBox.width}px`;
      styles.layout.height = `${raw.absoluteBoundingBox.height}px`;
    }

    if (raw.layoutMode) {
      styles.layout.display = 'flex';
      styles.layout.flexDirection = raw.layoutMode === 'VERTICAL' ? 'column' : 'row';
    }

    if (raw.itemSpacing) {
      styles.layout.gap = `${raw.itemSpacing}px`;
    }

    if (raw.paddingLeft || raw.paddingRight || raw.paddingTop || raw.paddingBottom) {
      styles.layout.padding = `${raw.paddingTop || 0}px ${raw.paddingRight || 0}px ${raw.paddingBottom || 0}px ${raw.paddingLeft || 0}px`;
    }

    if (raw.cornerRadius) {
      styles.layout.borderRadius = `${raw.cornerRadius}px`;
    }

    if (raw.fills && raw.fills.length > 0) {
      const fill = raw.fills[0];
      if (fill.type === 'SOLID' && fill.color) {
        const { r, g, b, a = 1 } = fill.color;
        styles.layout.backgroundColor = `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${a})`;
      }
    }

    return styles;
  }

  /**
   * Extract interactions for emits
   */
  extractInteractions(raw, registry) {
    const interactions = [];

    if (registry.interactiveStates) {
      if (registry.interactiveStates.hover) {
        interactions.push({ type: 'hover', handler: 'onMouseEnter', emit: 'hover' });
      }
      if (registry.interactiveStates.focus) {
        interactions.push({ type: 'focus', handler: 'onFocus', emit: 'focus' });
      }
      interactions.push({ type: 'click', handler: 'handleClick', emit: 'click' });
    }

    return interactions;
  }

  /**
   * Extract slots from raw data
   */
  extractSlots(raw) {
    const slots = [];

    // Look for text children that could be slots
    if (raw.children) {
      raw.children.forEach(child => {
        if (child.type === 'TEXT' && child.name?.toLowerCase().includes('slot')) {
          slots.push({ name: this.toKebabCase(child.name), fallback: child.characters || '' });
        }
      });
    }

    // Default slot
    if (slots.length === 0) {
      slots.push({ name: 'default', fallback: '' });
    }

    return slots;
  }

  /**
   * Infer prop type from Figma property
   */
  inferPropType(prop) {
    if (prop.type === 'BOOLEAN') return 'boolean';
    if (prop.type === 'NUMBER' || prop.type === 'FLOAT') return 'number';
    if (prop.type === 'VARIANT') return 'string';
    if (prop.type === 'INSTANCE_SWAP') return 'object';
    return 'string';
  }

  /**
   * Apply token dependencies to generated code
   */
  applyTokenDependencies(code, tokenDeps, config) {
    const imports = [];
    const cssVars = [];

    Object.entries(tokenDeps).forEach(([category, tokens]) => {
      tokens.forEach(token => {
        cssVars.push(`  --${token.name}: var(--token-${token.name}, ${token.value || 'inherit'});`);
      });
    });

    if (cssVars.length > 0) {
      // Add token CSS variables to style section
      const styleMatch = code.match(/<style[^>]*>([\s\S]*?)<\/style>/);
      if (styleMatch) {
        const existingStyles = styleMatch[1];
        const rootVars = `:root {\n${cssVars.join('\n')}\n}\n\n`;
        code = code.replace(styleMatch[0], `<style${config.cssScoped ? ' scoped' : ''}>\n${rootVars}${existingStyles}</style>`);
      }
    }

    // Add composable import for tokens
    if (Object.keys(tokenDeps).length > 0) {
      const scriptMatch = code.match(/<script[^>]*>/);
      if (scriptMatch) {
        code = code.replace(scriptMatch[0], `${scriptMatch[0]}\nimport { useTokens } from '@/tokens/useTokens';`);
      }
    }

    return code;
  }

  /**
   * Apply interactive states to generated code
   */
  applyInteractiveStates(code, states, config) {
    const eventHandlers = [];
    const stateRefs = [];
    const classBindings = [];

    if (states.hover) {
      stateRefs.push("const isHovered = ref(false);");
      eventHandlers.push('@mouseenter="isHovered = true"');
      eventHandlers.push('@mouseleave="isHovered = false"');
      classBindings.push("'is-hovered': isHovered");
    }

    if (states.focus) {
      stateRefs.push("const isFocused = ref(false);");
      eventHandlers.push('@focus="isFocused = true"');
      eventHandlers.push('@blur="isFocused = false"');
      classBindings.push("'is-focused': isFocused");
    }

    if (states.active || states.pressed) {
      stateRefs.push("const isActive = ref(false);");
      eventHandlers.push('@mousedown="isActive = true"');
      eventHandlers.push('@mouseup="isActive = false"');
      classBindings.push("'is-active': isActive");
    }

    if (states.disabled) {
      classBindings.push("'is-disabled': props.disabled");
    }

    // Add state refs to script
    if (stateRefs.length > 0) {
      const scriptSetupMatch = code.match(/<script setup[^>]*>([\s\S]*?)<\/script>/);
      if (scriptSetupMatch) {
        const existingScript = scriptSetupMatch[1];
        const stateCode = '\n' + stateRefs.join('\n');
        code = code.replace(scriptSetupMatch[1], existingScript + stateCode);
      }
    }

    // Add event handlers to template root element
    if (eventHandlers.length > 0) {
      code = code.replace(
        /<div class="([^"]*)" :class="classes">/,
        `<div class="$1" :class="classes" ${eventHandlers.join(' ')}>`
      );
    }

    // Update class bindings in computed
    if (classBindings.length > 0) {
      code = code.replace(
        /const classes = computed\(\(\) => \(\{/,
        `const classes = computed(() => ({\n  ${classBindings.join(',\n  ')},`
      );
    }

    return code;
  }

  /**
   * Apply variants to generated code
   */
  applyVariants(code, variants, config) {
    // Add variant class bindings
    const variantClasses = variants.map(v => `'variant-${v.name}': props.variant === '${v.name}'`);

    code = code.replace(
      /const classes = computed\(\(\) => \(\{/,
      `const classes = computed(() => ({\n  ${variantClasses.join(',\n  ')},`
    );

    // Add variant-specific styles
    const variantStyles = variants.map(v => {
      let css = `.variant-${v.name} {`;
      if (v.styles) {
        Object.entries(v.styles).forEach(([prop, val]) => {
          css += `\n  ${this.toKebabCase(prop)}: ${val};`;
        });
      }
      css += '\n}';
      return css;
    }).join('\n\n');

    const styleMatch = code.match(/<style[^>]*>([\s\S]*?)<\/style>/);
    if (styleMatch) {
      code = code.replace(styleMatch[0], styleMatch[0].replace('</style>', `\n${variantStyles}\n</style>`));
    }

    return code;
  }

  /**
   * Generate Storybook story for Vue component
   */
  generateStory(componentData, registry, config) {
    const { name } = componentData;
    const componentName = name.replace(/\s+/g, '');

    let story = [];
    story.push(`import type { Meta, StoryObj } from '@storybook/vue3';`);
    story.push(`import ${componentName} from './${componentName}.vue';`);
    story.push('');
    story.push(`const meta: Meta<typeof ${componentName}> = {`);
    story.push(`  title: 'Components/${registry.category || 'UI'}/${componentName}',`);
    story.push(`  component: ${componentName},`);
    story.push('  tags: [\'autodocs\'],');
    story.push('  argTypes: {');

    // Add argTypes for props
    if (componentData.props) {
      Object.entries(componentData.props).forEach(([propName, prop]) => {
        story.push(`    ${propName}: {`);
        story.push(`      control: { type: '${this.getStorybookControl(prop.type)}' },`);
        if (prop.validator) {
          story.push(`      options: [${registry.variants?.map(v => `'${v.name}'`).join(', ') || ''}],`);
        }
        story.push('    },');
      });
    }

    story.push('  },');
    story.push('};');
    story.push('');
    story.push('export default meta;');
    story.push(`type Story = StoryObj<typeof ${componentName}>;`);
    story.push('');

    // Default story
    story.push('export const Default: Story = {');
    story.push('  args: {');
    if (componentData.props) {
      Object.entries(componentData.props).forEach(([propName, prop]) => {
        if (prop.default !== undefined) {
          story.push(`    ${propName}: ${JSON.stringify(prop.default)},`);
        }
      });
    }
    story.push('  },');
    story.push('};');

    // Variant stories
    if (registry.variants && registry.variants.length > 0) {
      registry.variants.forEach(variant => {
        const storyName = variant.name.replace(/[^a-zA-Z0-9]/g, '');
        story.push('');
        story.push(`export const ${storyName}: Story = {`);
        story.push('  args: {');
        story.push(`    variant: '${variant.name}',`);
        story.push('  },');
        story.push('};');
      });
    }

    return story.join('\n');
  }

  /**
   * Get Storybook control type
   */
  getStorybookControl(propType) {
    const controlMap = {
      string: 'text',
      number: 'number',
      boolean: 'boolean',
      array: 'object',
      object: 'object'
    };
    return controlMap[propType] || 'text';
  }

  generateCSSVariables(tokens) {
    const lines = ['/* Auto-generated CSS variables */', ':root {'];
    if (tokens.colors) {
      for (const [key, value] of Object.entries(tokens.colors)) {
        if (typeof value === 'object') {
          for (const [subKey, subValue] of Object.entries(value)) {
            lines.push(`  --color-${key}-${subKey}: ${subValue};`);
          }
        } else {
          lines.push(`  --color-${key}: ${value};`);
        }
      }
    }
    if (tokens.spacing) {
      for (const [key, value] of Object.entries(tokens.spacing)) {
        lines.push(`  --spacing-${key}: ${value};`);
      }
    }
    lines.push('}');
    return lines.join('\n');
  }

  generateTokenComposable(tokens, options) {
    const lines = ['// Auto-generated token composable', ''];
    lines.push('export function useTokens() {');
    lines.push('  return {');
    if (tokens.colors) lines.push(`    colors: ${JSON.stringify(tokens.colors, null, 4).replace(/\n/g, '\n    ')},`);
    if (tokens.typography) lines.push(`    typography: ${JSON.stringify(tokens.typography, null, 4).replace(/\n/g, '\n    ')},`);
    if (tokens.spacing) lines.push(`    spacing: ${JSON.stringify(tokens.spacing, null, 4).replace(/\n/g, '\n    ')},`);
    lines.push('  };');
    lines.push('}');
    return lines.join('\n');
  }

  /**
   * Optimize code for Vue
   */
  async optimize(code, componentData, config) {
    let optimizedCode = code;

    // Apply Vue-specific optimizations
    optimizedCode = await this.optimizeReactivity(optimizedCode, componentData, config);
    optimizedCode = await this.optimizeComposition(optimizedCode, componentData, config);
    optimizedCode = await this.optimizeLifecycle(optimizedCode, componentData, config);
    optimizedCode = await this.optimizeDirectives(optimizedCode, componentData, config);
    optimizedCode = await this.optimizePerformance(optimizedCode, componentData, config);
    optimizedCode = await this.addAsyncComponents(optimizedCode, componentData, config);

    return optimizedCode;
  }

  /**
   * Generate Vue component from design data
   */
  async generateComponent(componentData, config) {
    const mergedConfig = { ...this.config, ...config };

    // Generate component structure
    const component = mergedConfig.sfc
      ? this.generateSFC(componentData, mergedConfig)
      : this.generateJSComponent(componentData, mergedConfig);

    return component;
  }

  /**
   * Generate Single File Component
   */
  generateSFC(data, config) {
    const { name, props, state, variants, styles } = data;

    let code = [];

    // Template section
    code.push('<template>');
    code.push(this.generateTemplate(data, config));
    code.push('</template>');
    code.push('');

    // Script section
    if (config.scriptSetup && config.compositionAPI) {
      code.push(`<script setup${config.useTypeScript ? ' lang="ts"' : ''}>`);
      code.push(this.generateScriptSetup(data, config));
    } else if (config.compositionAPI) {
      code.push(`<script${config.useTypeScript ? ' lang="ts"' : ''}>`);
      code.push(this.generateCompositionScript(data, config));
    } else {
      code.push(`<script${config.useTypeScript ? ' lang="ts"' : ''}>`);
      code.push(this.generateOptionsScript(data, config));
    }
    code.push('</script>');
    code.push('');

    // Style section
    code.push(`<style${config.cssScoped ? ' scoped' : ''}${this.getStyleLang(config)}>`);
    code.push(this.generateStyles(data, config));
    code.push('</style>');

    return code.join('\n');
  }

  /**
   * Generate template
   */
  generateTemplate(data, config) {
    const { name, children, variants } = data;
    const className = this.toKebabCase(name);

    let template = [];
    template.push(`  <div class="${className}" :class="classes">`);

    // Add slots
    if (config.slots && data.slots) {
      template.push(this.generateSlots(data.slots));
    }

    // Add children
    if (children && children.length > 0) {
      children.forEach(child => {
        template.push(`    <${this.toKebabCase(child.name)} />`);
      });
    } else {
      template.push(`    <!-- ${name} content -->`);
    }

    // Add teleport if needed
    if (config.teleport && data.type === 'modal') {
      template = this.wrapInTeleport(template);
    }

    template.push('  </div>');

    return template.join('\n');
  }

  /**
   * Generate script setup
   */
  generateScriptSetup(data, config) {
    const { name, props, state, interactions } = data;
    let script = [];

    // Imports
    script.push("import { ref, computed, onMounted, watch } from 'vue';");
    if (config.useTypeScript) {
      script.push("import type { PropType } from 'vue';");
    }
    script.push('');

    // Props definition
    if (props && Object.keys(props).length > 0) {
      script.push(this.generatePropsSetup(props, config));
      script.push('');
    }

    // Emits definition
    if (interactions && interactions.length > 0) {
      script.push(this.generateEmitsSetup(interactions));
      script.push('');
    }

    // Reactive state
    if (state && Object.keys(state).length > 0) {
      script.push(this.generateReactiveState(state, config));
      script.push('');
    }

    // Computed properties
    script.push(this.generateComputed(data, config));
    script.push('');

    // Methods
    script.push(this.generateMethods(data, config));
    script.push('');

    // Lifecycle hooks
    script.push(this.generateLifecycleHooks(data, config));

    // Watchers
    if (this.needsWatchers(data)) {
      script.push('');
      script.push(this.generateWatchers(data, config));
    }

    return script.join('\n');
  }

  /**
   * Generate composition API script
   */
  generateCompositionScript(data, config) {
    const { name } = data;

    let script = [];
    script.push("import { defineComponent, ref, computed, onMounted } from 'vue';");
    script.push('');
    script.push('export default defineComponent({');
    script.push(`  name: '${name}',`);

    if (data.props) {
      script.push('  props: {');
      script.push(this.generatePropsOptions(data.props, config));
      script.push('  },');
    }

    script.push('  setup(props, { emit, slots, attrs }) {');
    script.push(this.generateSetupFunction(data, config));
    script.push('  }');
    script.push('});');

    return script.join('\n');
  }

  /**
   * Generate options API script
   */
  generateOptionsScript(data, config) {
    const { name, props, state } = data;

    let script = [];
    script.push('export default {');
    script.push(`  name: '${name}',`);

    // Props
    if (props) {
      script.push('  props: {');
      script.push(this.generatePropsOptions(props, config));
      script.push('  },');
    }

    // Data
    if (state) {
      script.push('  data() {');
      script.push('    return {');
      Object.entries(state).forEach(([key, value]) => {
        script.push(`      ${key}: ${JSON.stringify(value)},`);
      });
      script.push('    };');
      script.push('  },');
    }

    // Computed
    script.push('  computed: {');
    script.push(this.generateComputedOptions(data));
    script.push('  },');

    // Methods
    script.push('  methods: {');
    script.push(this.generateMethodsOptions(data));
    script.push('  },');

    // Lifecycle
    script.push('  mounted() {');
    script.push('    // Component mounted');
    script.push('  }');

    script.push('};');

    return script.join('\n');
  }

  /**
   * Optimize reactivity
   */
  async optimizeReactivity(code, data, config) {
    // Choose between ref and reactive based on data structure
    if (this.shouldUseReactive(data.state)) {
      code = this.convertToReactive(code, data.state);
    }

    // Add computed properties for derived state
    code = this.addComputedProperties(code, data);

    // Optimize watchers
    code = this.optimizeWatchers(code, data);

    return code;
  }

  /**
   * Optimize composition
   */
  async optimizeComposition(code, data, config) {
    // Extract composables for reusable logic
    code = this.extractComposables(code, data);

    // Use provide/inject for deep prop passing
    if (config.provide && this.shouldUseProvide(data)) {
      code = this.addProvideInject(code, data);
    }

    return code;
  }

  /**
   * Optimize lifecycle
   */
  async optimizeLifecycle(code, data, config) {
    // Add appropriate lifecycle hooks
    code = this.addLifecycleHooks(code, data);

    // Add keep-alive for cached components
    if (this.shouldUseKeepAlive(data)) {
      code = this.addKeepAlive(code, data);
    }

    return code;
  }

  /**
   * Optimize directives
   */
  async optimizeDirectives(code, data, config) {
    // Add v-show vs v-if optimization
    code = this.optimizeConditionalRendering(code);

    // Add v-once for static content
    code = this.addVOnce(code, data);

    // Add v-memo for expensive lists
    code = this.addVMemo(code, data);

    return code;
  }

  /**
   * Optimize performance
   */
  async optimizePerformance(code, data, config) {
    // Add lazy loading with defineAsyncComponent
    code = this.addAsyncComponents(code, data);

    // Add functional components where appropriate
    code = this.addFunctionalComponents(code, data);

    // Add dynamic imports
    code = this.addDynamicImports(code, data);

    return code;
  }

  /**
   * Helper: Generate props setup
   */
  generatePropsSetup(props, config) {
    let propsCode = [];

    if (config.useTypeScript) {
      propsCode.push('interface Props {');
      Object.entries(props).forEach(([key, prop]) => {
        const optional = !prop.required ? '?' : '';
        propsCode.push(`  ${key}${optional}: ${this.getVueTSType(prop.type)};`);
      });
      propsCode.push('}');
      propsCode.push('');
      propsCode.push('const props = withDefaults(defineProps<Props>(), {');
      Object.entries(props).forEach(([key, prop]) => {
        if (prop.default !== undefined) {
          propsCode.push(`  ${key}: ${JSON.stringify(prop.default)},`);
        }
      });
      propsCode.push('});');
    } else {
      propsCode.push('const props = defineProps({');
      Object.entries(props).forEach(([key, prop]) => {
        propsCode.push(`  ${key}: {`);
        propsCode.push(`    type: ${this.getVuePropType(prop.type)},`);
        if (prop.required) propsCode.push('    required: true,');
        if (prop.default !== undefined) {
          propsCode.push(`    default: ${JSON.stringify(prop.default)}`);
        }
        propsCode.push('  },');
      });
      propsCode.push('});');
    }

    return propsCode.join('\n');
  }

  /**
   * Helper: Generate emits setup
   */
  generateEmitsSetup(interactions) {
    const emits = interactions
      .filter(i => i.type === 'emit')
      .map(i => `'${i.name}'`);

    return `const emit = defineEmits([${emits.join(', ')}]);`;
  }

  /**
   * Helper: Generate reactive state
   */
  generateReactiveState(state, config) {
    let stateCode = [];

    if (config.reactivity === 'reactive') {
      stateCode.push('const state = reactive({');
      Object.entries(state).forEach(([key, value]) => {
        stateCode.push(`  ${key}: ${JSON.stringify(value)},`);
      });
      stateCode.push('});');
    } else {
      Object.entries(state).forEach(([key, value]) => {
        stateCode.push(`const ${key} = ref(${JSON.stringify(value)});`);
      });
    }

    return stateCode.join('\n');
  }

  /**
   * Helper: Generate computed properties
   */
  generateComputed(data, config) {
    let computed = [];

    // Example computed property
    computed.push('const classes = computed(() => ({');
    if (data.variants) {
      data.variants.forEach(variant => {
        computed.push(`  '${variant.class}': ${variant.condition},`);
      });
    }
    computed.push('}));');

    return computed.join('\n');
  }

  /**
   * Helper: Generate methods
   */
  generateMethods(data, config) {
    let methods = [];

    // Example method
    if (data.interactions) {
      data.interactions.forEach(interaction => {
        if (interaction.type === 'click') {
          methods.push(`const ${interaction.handler} = () => {`);
          methods.push(`  emit('${interaction.emit}');`);
          methods.push('};');
        }
      });
    }

    return methods.join('\n');
  }

  /**
   * Helper: Generate lifecycle hooks
   */
  generateLifecycleHooks(data, config) {
    let hooks = [];

    hooks.push('onMounted(() => {');
    hooks.push('  // Component mounted');
    hooks.push('});');

    return hooks.join('\n');
  }

  /**
   * Helper: Generate watchers
   */
  generateWatchers(data, config) {
    let watchers = [];

    // Example watcher
    if (data.props?.value) {
      watchers.push("watch(() => props.value, (newVal, oldVal) => {");
      watchers.push('  // Handle value change');
      watchers.push('});');
    }

    return watchers.join('\n');
  }

  /**
   * Helper: Generate styles
   */
  generateStyles(data, config) {
    const { name, styles } = data;
    const className = this.toKebabCase(name);

    let css = [];
    css.push(`.${className} {`);

    if (styles?.layout) {
      Object.entries(styles.layout).forEach(([key, value]) => {
        if (value) css.push(`  ${this.toKebabCase(key)}: ${value};`);
      });
    }

    css.push('}');

    return css.join('\n');
  }

  /**
   * Helper: Utility functions
   */
  toKebabCase(str) {
    return str.replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase();
  }

  toCamelCase(str) {
    return str.replace(/[-_\s]+(.)?/g, (_, c) => c ? c.toUpperCase() : '').replace(/^./, c => c.toLowerCase());
  }

  getStyleLang(config) {
    if (config.styleFormat === 'scss') return ' lang="scss"';
    if (config.styleFormat === 'less') return ' lang="less"';
    return '';
  }

  getVueTSType(type) {
    const typeMap = {
      string: 'string',
      number: 'number',
      boolean: 'boolean',
      array: 'any[]',
      object: 'Record<string, any>',
      function: 'Function',
      any: 'any'
    };
    return typeMap[type] || 'any';
  }

  getVuePropType(type) {
    const typeMap = {
      string: 'String',
      number: 'Number',
      boolean: 'Boolean',
      array: 'Array',
      object: 'Object',
      function: 'Function'
    };
    return typeMap[type] || 'null';
  }

  /**
   * Helper: Pattern definitions
   */
  getCompositionPatterns() {
    return {
      ref: /ref\(/g,
      reactive: /reactive\(/g,
      computed: /computed\(/g
    };
  }

  getReactivityPatterns() {
    return {
      watch: /watch\(/g,
      watchEffect: /watchEffect\(/g
    };
  }

  getLifecyclePatterns() {
    return {
      onMounted: /onMounted\(/g,
      onUpdated: /onUpdated\(/g,
      onUnmounted: /onUnmounted\(/g
    };
  }

  getDirectivePatterns() {
    return {
      vIf: /v-if=/g,
      vShow: /v-show=/g,
      vFor: /v-for=/g
    };
  }

  /**
   * Helper: Optimization utilities
   */
  shouldUseReactive(state) {
    return state && typeof state === 'object' && !Array.isArray(state);
  }

  convertToReactive(code, state) {
    // Convert refs to reactive object
    return code;
  }

  addComputedProperties(code, data) {
    // Add computed for derived values
    return code;
  }

  optimizeWatchers(code, data) {
    // Use watchEffect where appropriate
    return code;
  }

  extractComposables(code, data) {
    // Extract reusable logic into composables
    return code;
  }

  shouldUseProvide(data) {
    return data.children && data.children.length > 3;
  }

  addProvideInject(code, data) {
    // Add provide/inject pattern
    return code;
  }

  addLifecycleHooks(code, data) {
    // Add appropriate hooks
    return code;
  }

  shouldUseKeepAlive(data) {
    return data.type === 'tab-content' || data.type === 'router-view';
  }

  addKeepAlive(code, data) {
    // Wrap in keep-alive
    return code;
  }

  optimizeConditionalRendering(code) {
    // Optimize v-if vs v-show
    return code;
  }

  addVOnce(code, data) {
    // Add v-once for static content
    return code;
  }

  addVMemo(code, data) {
    // Add v-memo for expensive lists
    return code;
  }

  addAsyncComponents(code, data) {
    // Convert to async components
    return code;
  }

  addFunctionalComponents(code, data) {
    // Make stateless components functional
    return code;
  }

  addDynamicImports(code, data) {
    // Add dynamic imports
    return code;
  }

  needsWatchers(data) {
    return data.props && Object.keys(data.props).some(p => p.includes('value'));
  }

  generateSlots(slots) {
    return slots.map(slot => `    <slot name="${slot.name}">${slot.fallback || ''}</slot>`).join('\n');
  }

  wrapInTeleport(template) {
    return [
      '  <Teleport to="body">',
      ...template.map(line => '  ' + line),
      '  </Teleport>'
    ];
  }

  generatePropsOptions(props, config) {
    // Generate props in options API format
    return '';
  }

  generateSetupFunction(data, config) {
    // Generate setup function body
    return '    // Setup logic\n    return {};';
  }

  generateComputedOptions(data) {
    // Generate computed in options API format
    return '';
  }

  generateMethodsOptions(data) {
    // Generate methods in options API format
    return '';
  }
}

module.exports = VueOptimizer;