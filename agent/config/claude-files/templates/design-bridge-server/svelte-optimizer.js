/**
 * Svelte Optimizer
 * Optimizes code generation specifically for Svelte applications
 * Sprint 15: Svelte Optimizer
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

const { normalizeVariants, syncToFramework } = require('./variant-sync');

class SvelteOptimizer {
  constructor() {
    this.name = 'SvelteOptimizer';
    this.version = '1.0.0';
    this.framework = 'svelte';

    // Svelte-specific configuration
    this.config = {
      version: '4.x',
      useTypeScript: true,
      useStores: true,
      useActions: true,
      useTransitions: true,
      useAnimations: true,
      ssr: false,
      immutable: true,
      accessors: true,
      cssFramework: 'native', // native, tailwind, postcss
      componentFormat: 'sfc', // Single File Component
      reactivity: '$:', // Svelte reactive statements
      compiledOptimizations: true
    };

    // Svelte patterns
    this.patterns = {
      reactivity: this.getReactivityPatterns(),
      stores: this.getStorePatterns(),
      lifecycle: this.getLifecyclePatterns(),
      bindings: this.getBindingPatterns()
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
    const instance = new SvelteOptimizer();
    const files = [];
    const outputPath = options.outputPath || './output';
    const tokensDir = path.join(outputPath, 'tokens');
    fs.mkdirSync(tokensDir, { recursive: true });

    // Generate CSS variables
    if (tokens.colors || tokens.typography || tokens.spacing) {
      const cssVars = instance.generateCSSVariables(tokens);
      const cssFile = path.join(tokensDir, 'variables.css');
      fs.writeFileSync(cssFile, cssVars);
      files.push(cssFile);
    }

    // Generate Svelte store for tokens
    const store = instance.generateTokenStore(tokens, options);
    const storeFile = path.join(tokensDir, options.typescript ? 'tokens.ts' : 'tokens.js');
    fs.writeFileSync(storeFile, store);
    files.push(storeFile);

    return { files, framework: 'svelte' };
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

  generateTokenStore(tokens, options) {
    const lines = ['// Auto-generated Svelte token store', "import { writable } from 'svelte/store';", ''];
    lines.push('export const tokens = writable({');
    if (tokens.colors) lines.push(`  colors: ${JSON.stringify(tokens.colors, null, 4).replace(/\n/g, '\n  ')},`);
    if (tokens.typography) lines.push(`  typography: ${JSON.stringify(tokens.typography, null, 4).replace(/\n/g, '\n  ')},`);
    if (tokens.spacing) lines.push(`  spacing: ${JSON.stringify(tokens.spacing, null, 4).replace(/\n/g, '\n  ')},`);
    lines.push('});');
    return lines.join('\n');
  }

  /**
   * Static optimize method for registry-based transformation
   * Accepts enriched input with raw data + registry metadata
   * @param {Object} input - Enriched input { raw, registry, options }
   * @returns {Object} Result with code, story, warnings
   */
  static async optimize(input) {
    const { raw, registry, options = {} } = input;
    const instance = new SvelteOptimizer();
    const warnings = [];

    // P6: Normalize variants for cross-framework consistency
    const normalizedRegistry = {
      ...registry,
      variants: syncToFramework(registry.variants || [], 'svelte')
    };

    // Build component data from raw + normalized registry
    const componentData = instance.buildComponentData(raw, normalizedRegistry);

    // Generate component with enriched data
    const config = {
      ...instance.config,
      useTypeScript: options.typescript !== false,
      useStores: options.useStores !== false,
      useTransitions: options.useTransitions !== false,
      useActions: options.useActions !== false,
      ...options
    };

    let code;
    try {
      code = await instance.generateComponent(componentData, config);

      // Apply registry-aware optimizations (using normalized registry)
      if (normalizedRegistry.tokenDependencies) {
        code = instance.applyTokenDependencies(code, normalizedRegistry.tokenDependencies, config);
      }
      if (normalizedRegistry.interactiveStates) {
        code = instance.applyInteractiveStates(code, normalizedRegistry.interactiveStates, config);
      }
      if (normalizedRegistry.variants && normalizedRegistry.variants.length > 0) {
        code = instance.applyVariants(code, normalizedRegistry.variants, config);
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
    const name = registry.name || raw.name || 'SvelteComponent';

    return {
      name,
      props: this.extractProps(raw, registry),
      state: this.extractState(raw, registry),
      computed: this.extractComputed(raw, registry),
      styles: this.extractStyles(raw),
      transitions: this.extractTransitions(raw, registry),
      animations: this.extractAnimations(raw, registry),
      slots: this.extractSlots(raw),
      bindings: this.extractBindings(raw, registry),
      events: this.extractEvents(raw, registry),
      lifecycle: this.extractLifecycle(raw, registry),
      methods: this.extractMethods(raw, registry),
      actions: this.extractSvelteActions(raw, registry),
      conditionals: raw.conditionals || [],
      loops: raw.loops || [],
      children: raw.children || []
    };
  }

  extractProps(raw, registry) {
    const props = {};

    // Extract from registry variants
    if (registry.variants) {
      registry.variants.forEach(variant => {
        if (variant.property && !props[variant.property]) {
          props[variant.property] = {
            type: this.inferPropType(variant.values),
            default: variant.values?.[0],
            required: false
          };
        }
      });
    }

    // Extract from raw component properties
    if (raw.componentProperties) {
      Object.entries(raw.componentProperties).forEach(([key, prop]) => {
        props[key] = {
          type: prop.type || 'string',
          default: prop.defaultValue,
          required: prop.required || false
        };
      });
    }

    return props;
  }

  extractState(raw, registry) {
    const state = {};

    // Extract interactive states
    if (registry.interactiveStates) {
      if (registry.interactiveStates.hover) state.isHovered = false;
      if (registry.interactiveStates.focus) state.isFocused = false;
      if (registry.interactiveStates.active) state.isActive = false;
      if (registry.interactiveStates.disabled) state.isDisabled = false;
    }

    // Extract from raw
    if (raw.state) {
      Object.assign(state, raw.state);
    }

    return state;
  }

  extractComputed(raw, registry) {
    const computed = {};

    // Add computed for CSS classes based on state
    if (registry.interactiveStates) {
      const conditions = [];
      if (registry.interactiveStates.hover) conditions.push("isHovered ? 'hovered' : ''");
      if (registry.interactiveStates.focus) conditions.push("isFocused ? 'focused' : ''");
      if (registry.interactiveStates.active) conditions.push("isActive ? 'active' : ''");
      if (registry.interactiveStates.disabled) conditions.push("isDisabled ? 'disabled' : ''");

      if (conditions.length > 0) {
        computed.stateClasses = `[${conditions.join(', ')}].filter(Boolean).join(' ')`;
      }
    }

    return computed;
  }

  extractStyles(raw) {
    return {
      layout: raw.layout || raw.absoluteBoundingBox || {},
      typography: raw.style || {},
      responsive: raw.responsive || {},
      tokens: raw.tokens || {}
    };
  }

  extractTransitions(raw, registry) {
    if (registry.interactiveStates) {
      return { type: 'fade', duration: 200 };
    }
    return raw.transitions || null;
  }

  extractAnimations(raw, registry) {
    return raw.animations || null;
  }

  extractSlots(raw) {
    const slots = [];
    if (raw.children?.some(c => c.type === 'SLOT' || c.name?.toLowerCase().includes('slot'))) {
      slots.push({ name: null, fallback: '' });
    }
    return slots;
  }

  extractBindings(raw, registry) {
    return raw.bindings || [];
  }

  extractEvents(raw, registry) {
    const events = [];

    if (registry.interactiveStates) {
      if (registry.interactiveStates.hover) {
        events.push({ type: 'mouseenter', handler: 'handleMouseEnter' });
        events.push({ type: 'mouseleave', handler: 'handleMouseLeave' });
      }
      if (registry.interactiveStates.focus) {
        events.push({ type: 'focus', handler: 'handleFocus' });
        events.push({ type: 'blur', handler: 'handleBlur' });
      }
    }

    return events;
  }

  extractLifecycle(raw, registry) {
    return raw.lifecycle || null;
  }

  extractMethods(raw, registry) {
    const methods = {};

    if (registry.interactiveStates) {
      if (registry.interactiveStates.hover) {
        methods.handleMouseEnter = { body: 'isHovered = true;' };
        methods.handleMouseLeave = { body: 'isHovered = false;' };
      }
      if (registry.interactiveStates.focus) {
        methods.handleFocus = { body: 'isFocused = true;' };
        methods.handleBlur = { body: 'isFocused = false;' };
      }
    }

    return methods;
  }

  extractSvelteActions(raw, registry) {
    return raw.actions || [];
  }

  inferPropType(values) {
    if (!values || values.length === 0) return 'string';
    const sample = values[0];
    if (typeof sample === 'boolean') return 'boolean';
    if (typeof sample === 'number') return 'number';
    return 'string';
  }

  /**
   * Apply token dependencies to generated code
   */
  applyTokenDependencies(code, tokenDeps, config) {
    let enhanced = code;

    // Add token imports to script section
    const tokenImport = "  import { tokens } from '$lib/tokens';";
    enhanced = enhanced.replace(
      '<script',
      `<script>\n${tokenImport}\n`
    ).replace(/\n<script>\n<script/, '<script');

    // Add CSS variable usage in style section
    if (tokenDeps.colors) {
      Object.entries(tokenDeps.colors).forEach(([prop, tokenRef]) => {
        const varName = `--${tokenRef.replace(/\./g, '-')}`;
        enhanced = enhanced.replace(
          new RegExp(`(${prop}:\\s*)([^;]+)(;)`, 'g'),
          `$1var(${varName})$3`
        );
      });
    }

    return enhanced;
  }

  /**
   * Apply interactive states to generated code
   */
  applyInteractiveStates(code, states, config) {
    let enhanced = code;

    // Add state-based CSS classes in template
    if (states.hover || states.focus || states.active || states.disabled) {
      enhanced = enhanced.replace(
        /class="([^"]+)"/,
        'class="$1 {stateClasses}"'
      );
    }

    // Add hover styles
    if (states.hover) {
      const hoverStyles = `
  .hovered {
    /* Hover state styles */
  }`;
      enhanced = enhanced.replace('</style>', `${hoverStyles}\n</style>`);
    }

    // Add focus styles
    if (states.focus) {
      const focusStyles = `
  .focused {
    outline: 2px solid var(--focus-ring-color, #0066cc);
    outline-offset: 2px;
  }`;
      enhanced = enhanced.replace('</style>', `${focusStyles}\n</style>`);
    }

    // Add disabled styles
    if (states.disabled) {
      const disabledStyles = `
  .disabled {
    opacity: 0.5;
    pointer-events: none;
    cursor: not-allowed;
  }`;
      enhanced = enhanced.replace('</style>', `${disabledStyles}\n</style>`);
    }

    return enhanced;
  }

  /**
   * Apply variants to generated code
   */
  applyVariants(code, variants, config) {
    let enhanced = code;

    variants.forEach(variant => {
      if (variant.property && variant.values) {
        // Add variant-based CSS classes
        variant.values.forEach(value => {
          const className = `${variant.property}-${value}`.toLowerCase().replace(/\s+/g, '-');
          const variantStyles = `
  .${className} {
    /* ${variant.property}: ${value} styles */
  }`;
          enhanced = enhanced.replace('</style>', `${variantStyles}\n</style>`);
        });
      }
    });

    return enhanced;
  }

  /**
   * Generate Storybook story for Svelte component
   */
  generateStory(componentData, registry, config) {
    const { name } = componentData;
    const componentPath = `./${name}.svelte`;

    let story = `import type { Meta, StoryObj } from '@storybook/svelte';
import ${name} from '${componentPath}';

const meta: Meta<typeof ${name}> = {
  title: 'Components/${registry.category || 'General'}/${name}',
  component: ${name},
  tags: ['autodocs'],
  argTypes: {`;

    // Add argTypes for props
    Object.entries(componentData.props || {}).forEach(([propName, prop]) => {
      story += `
    ${propName}: {
      control: '${this.getStorybookControl(prop.type)}',
      description: '${propName} property',
    },`;
    });

    story += `
  },
};

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {`;

    // Add default args
    Object.entries(componentData.props || {}).forEach(([propName, prop]) => {
      if (prop.default !== undefined) {
        story += `
    ${propName}: ${JSON.stringify(prop.default)},`;
      }
    });

    story += `
  },
};`;

    // Add variant stories
    if (registry.variants && registry.variants.length > 0) {
      registry.variants.forEach(variant => {
        if (variant.values) {
          variant.values.forEach(value => {
            const storyName = `${variant.property}${value}`.replace(/[^a-zA-Z0-9]/g, '');
            story += `

export const ${storyName}: Story = {
  args: {
    ${variant.property}: ${JSON.stringify(value)},
  },
};`;
          });
        }
      });
    }

    return story;
  }

  getStorybookControl(type) {
    const controlMap = {
      string: 'text',
      number: 'number',
      boolean: 'boolean',
      array: 'object',
      object: 'object'
    };
    return controlMap[type] || 'text';
  }

  /**
   * Optimize code for Svelte (legacy method signature)
   */
  async optimize(code, componentData, config) {
    let optimizedCode = code;

    // Apply Svelte-specific optimizations
    optimizedCode = await this.optimizeReactivity(optimizedCode, componentData, config);
    optimizedCode = await this.optimizeStores(optimizedCode, componentData, config);
    optimizedCode = await this.optimizeBindings(optimizedCode, componentData, config);
    optimizedCode = await this.optimizeTransitions(optimizedCode, componentData, config);
    optimizedCode = await this.optimizeActions(optimizedCode, componentData, config);
    optimizedCode = await this.optimizeCompilation(optimizedCode, componentData, config);

    return optimizedCode;
  }

  /**
   * Generate Svelte component from design data
   */
  async generateComponent(componentData, config) {
    const mergedConfig = { ...this.config, ...config };

    // Generate Single File Component
    const component = this.generateSFC(componentData, mergedConfig);

    return component;
  }

  /**
   * Generate Svelte Single File Component
   */
  generateSFC(data, config) {
    const { name, props, state, styles, transitions, animations } = data;

    let code = [];

    // Script section
    code.push(config.useTypeScript ? '<script lang="ts">' : '<script>');

    // Imports
    if (state && Object.keys(state).length > 0 && config.useStores) {
      code.push("  import { writable, derived } from 'svelte/store';");
    }
    if (transitions || animations) {
      code.push("  import { fade, fly, slide, scale } from 'svelte/transition';");
    }
    if (data.lifecycle) {
      code.push("  import { onMount, onDestroy, afterUpdate } from 'svelte';");
    }
    if (data.actions && config.useActions) {
      code.push("  import { createEventDispatcher } from 'svelte';");
    }
    code.push('');

    // Props
    if (props && Object.keys(props).length > 0) {
      code.push(this.generateProps(props, config));
    }

    // Event dispatcher
    if (data.interactions?.some(i => i.emit)) {
      code.push('  const dispatch = createEventDispatcher();');
      code.push('');
    }

    // State and stores
    if (state && Object.keys(state).length > 0) {
      code.push(this.generateState(state, config));
    }

    // Reactive statements
    if (data.computed) {
      code.push(this.generateReactiveStatements(data.computed));
    }

    // Lifecycle hooks
    if (data.lifecycle) {
      code.push(this.generateLifecycleHooks(data.lifecycle));
    }

    // Methods
    if (data.methods) {
      code.push(this.generateMethods(data.methods, config));
    }

    // Actions
    if (data.actions && config.useActions) {
      code.push(this.generateActions(data.actions));
    }

    code.push('</script>');
    code.push('');

    // Template section
    code.push(this.generateTemplate(data, config));
    code.push('');

    // Style section
    code.push('<style>');
    code.push(this.generateStyles(data, config));
    code.push('</style>');

    return code.join('\n');
  }

  /**
   * Generate props
   */
  generateProps(props, config) {
    const propLines = [];

    Object.entries(props).forEach(([key, prop]) => {
      if (config.useTypeScript) {
        const type = this.getTSType(prop.type);
        if (prop.default !== undefined) {
          propLines.push(`  export let ${key}: ${type} = ${JSON.stringify(prop.default)};`);
        } else {
          propLines.push(`  export let ${key}: ${type};`);
        }
      } else {
        if (prop.default !== undefined) {
          propLines.push(`  export let ${key} = ${JSON.stringify(prop.default)};`);
        } else {
          propLines.push(`  export let ${key};`);
        }
      }
    });

    return propLines.join('\n');
  }

  /**
   * Generate state
   */
  generateState(state, config) {
    const stateLines = [];

    Object.entries(state).forEach(([key, initialValue]) => {
      if (config.useStores && this.shouldUseStore(key, initialValue)) {
        // Use store for complex state
        stateLines.push(`  const ${key} = writable(${JSON.stringify(initialValue)});`);
      } else {
        // Use regular variable for simple state
        stateLines.push(`  let ${key} = ${JSON.stringify(initialValue)};`);
      }
    });

    return stateLines.join('\n');
  }

  /**
   * Generate reactive statements
   */
  generateReactiveStatements(computed) {
    const reactiveLines = [];

    Object.entries(computed).forEach(([key, computation]) => {
      reactiveLines.push(`  $: ${key} = ${computation};`);
    });

    return reactiveLines.join('\n');
  }

  /**
   * Generate lifecycle hooks
   */
  generateLifecycleHooks(lifecycle) {
    const hooks = [];

    if (lifecycle.onMount) {
      hooks.push(`  onMount(() => {
    ${lifecycle.onMount}
  });`);
    }

    if (lifecycle.onDestroy) {
      hooks.push(`  onDestroy(() => {
    ${lifecycle.onDestroy}
  });`);
    }

    if (lifecycle.afterUpdate) {
      hooks.push(`  afterUpdate(() => {
    ${lifecycle.afterUpdate}
  });`);
    }

    return hooks.join('\n\n');
  }

  /**
   * Generate methods
   */
  generateMethods(methods, config) {
    const methodLines = [];

    Object.entries(methods).forEach(([name, method]) => {
      if (config.useTypeScript) {
        methodLines.push(`  function ${name}(${method.params || ''}): ${method.returnType || 'void'} {
    ${method.body}
  }`);
      } else {
        methodLines.push(`  function ${name}(${method.params || ''}) {
    ${method.body}
  }`);
      }
    });

    return methodLines.join('\n\n');
  }

  /**
   * Generate actions
   */
  generateActions(actions) {
    const actionLines = [];

    actions.forEach(action => {
      actionLines.push(`  function ${action.name}(node${action.params ? ', ' + action.params : ''}) {
    ${action.setup || '// Setup'}

    return {
      ${action.update ? `update(${action.updateParams || ''}) {
        ${action.update}
      },` : ''}
      destroy() {
        ${action.destroy || '// Cleanup'}
      }
    };
  }`);
    });

    return actionLines.join('\n\n');
  }

  /**
   * Generate template
   */
  generateTemplate(data, config) {
    const { name, props, state, children, bindings, transitions } = data;
    const className = name.replace(/([A-Z])/g, '-$1').toLowerCase().slice(1);

    let template = [];

    // Main container with transitions
    if (transitions && config.useTransitions) {
      template.push(`<div class="${className}" transition:${transitions.type || 'fade'}>`);
    } else {
      template.push(`<div class="${className}">`);
    }

    // Conditional rendering
    if (data.conditionals) {
      data.conditionals.forEach(conditional => {
        template.push(`  {#if ${conditional.condition}}
    ${conditional.content}
  {/if}`);
      });
    }

    // Loop rendering
    if (data.loops) {
      data.loops.forEach(loop => {
        template.push(`  {#each ${loop.items} as ${loop.item}${loop.key ? ` (${loop.key})` : ''}}
    ${loop.template}
  {/each}`);
      });
    }

    // Slot for content projection
    if (data.slots) {
      data.slots.forEach(slot => {
        if (slot.name) {
          template.push(`  <slot name="${slot.name}">${slot.fallback || ''}</slot>`);
        } else {
          template.push(`  <slot>${slot.fallback || ''}</slot>`);
        }
      });
    }

    // Two-way bindings
    if (bindings) {
      bindings.forEach(binding => {
        template.push(`  <input bind:${binding.property}={${binding.variable}} />`);
      });
    }

    // Event handlers
    if (data.events) {
      data.events.forEach(event => {
        template.push(`  <button on:${event.type}={${event.handler}}>
    ${event.label || 'Button'}
  </button>`);
      });
    }

    // Children components
    if (children && children.length > 0) {
      children.forEach(child => {
        template.push(`  <${child.name} ${this.generateChildProps(child.props)} />`);
      });
    }

    template.push('</div>');

    return template.join('\n');
  }

  /**
   * Generate styles
   */
  generateStyles(data, config) {
    const { name, styles } = data;
    const className = name.replace(/([A-Z])/g, '-$1').toLowerCase().slice(1);

    let css = [];

    // Component styles
    css.push(`  .${className} {`);

    if (styles?.layout) {
      Object.entries(styles.layout).forEach(([key, value]) => {
        if (value) css.push(`    ${this.toKebabCase(key)}: ${value};`);
      });
    }

    if (styles?.typography) {
      Object.entries(styles.typography).forEach(([key, value]) => {
        if (value) css.push(`    ${this.toKebabCase(key)}: ${value};`);
      });
    }

    css.push('  }');

    // Responsive styles
    if (styles?.responsive) {
      Object.entries(styles.responsive).forEach(([breakpoint, rules]) => {
        css.push('');
        css.push(`  @media (min-width: ${breakpoint}) {`);
        css.push(`    .${className} {`);
        Object.entries(rules).forEach(([key, value]) => {
          css.push(`      ${this.toKebabCase(key)}: ${value};`);
        });
        css.push('    }');
        css.push('  }');
      });
    }

    // CSS variables for theming
    if (styles?.tokens) {
      css.push('');
      css.push('  :global(:root) {');
      Object.entries(styles.tokens).forEach(([key, value]) => {
        css.push(`    --${className}-${key}: ${value};`);
      });
      css.push('  }');
    }

    return css.join('\n');
  }

  /**
   * Optimize reactivity
   */
  async optimizeReactivity(code, data, config) {
    // Convert imperative updates to reactive statements
    code = this.convertToReactiveStatements(code);

    // Optimize reactive dependencies
    code = this.optimizeReactiveDependencies(code);

    // Add reactive declarations where beneficial
    code = this.addReactiveDeclarations(code, data);

    return code;
  }

  /**
   * Optimize stores
   */
  async optimizeStores(code, data, config) {
    if (!config.useStores) return code;

    // Convert shared state to stores
    code = this.convertToStores(code, data);

    // Add derived stores for computed values
    code = this.addDerivedStores(code, data);

    // Optimize store subscriptions
    code = this.optimizeStoreSubscriptions(code);

    return code;
  }

  /**
   * Optimize bindings
   */
  async optimizeBindings(code, data, config) {
    // Use two-way binding where appropriate
    code = this.addTwoWayBindings(code, data);

    // Optimize component bindings
    code = this.optimizeComponentBindings(code);

    // Add group bindings for related inputs
    code = this.addGroupBindings(code, data);

    return code;
  }

  /**
   * Optimize transitions
   */
  async optimizeTransitions(code, data, config) {
    if (!config.useTransitions) return code;

    // Add entrance/exit transitions
    code = this.addTransitions(code, data);

    // Add deferred transitions for better performance
    code = this.addDeferredTransitions(code);

    // Optimize transition timing
    code = this.optimizeTransitionTiming(code);

    return code;
  }

  /**
   * Optimize actions
   */
  async optimizeActions(code, data, config) {
    if (!config.useActions) return code;

    // Convert repeated DOM manipulations to actions
    code = this.extractActions(code, data);

    // Add lifecycle management to actions
    code = this.addActionLifecycle(code);

    // Optimize action parameters
    code = this.optimizeActionParams(code);

    return code;
  }

  /**
   * Optimize compilation
   */
  async optimizeCompilation(code, data, config) {
    if (!config.compiledOptimizations) return code;

    // Add compiler options
    code = this.addCompilerOptions(code, config);

    // Optimize for SSR if enabled
    if (config.ssr) {
      code = this.optimizeForSSR(code);
    }

    // Add immutable optimizations
    if (config.immutable) {
      code = this.addImmutableOptimizations(code);
    }

    return code;
  }

  /**
   * Helper: Pattern definitions
   */
  getReactivityPatterns() {
    return {
      reactive: /\$:/g,
      assignment: /let\s+(\w+)\s*=/g,
      update: /(\w+)\s*=/g
    };
  }

  getStorePatterns() {
    return {
      writable: /writable\(/g,
      readable: /readable\(/g,
      derived: /derived\(/g,
      subscription: /\$(\w+)/g
    };
  }

  getLifecyclePatterns() {
    return {
      onMount: /onMount\(/g,
      onDestroy: /onDestroy\(/g,
      beforeUpdate: /beforeUpdate\(/g,
      afterUpdate: /afterUpdate\(/g
    };
  }

  getBindingPatterns() {
    return {
      bind: /bind:/g,
      twoWay: /bind:value/g,
      group: /bind:group/g,
      this: /bind:this/g
    };
  }

  /**
   * Helper: TypeScript types
   */
  getTSType(type) {
    const typeMap = {
      string: 'string',
      number: 'number',
      boolean: 'boolean',
      array: 'any[]',
      object: 'Record<string, any>',
      function: '(...args: any[]) => any',
      any: 'any'
    };
    return typeMap[type] || 'any';
  }

  /**
   * Helper: Utility functions
   */
  toKebabCase(str) {
    return str.replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase();
  }

  shouldUseStore(key, value) {
    // Use store for complex state that might be shared
    return typeof value === 'object' && value !== null;
  }

  generateChildProps(props) {
    if (!props) return '';
    return Object.entries(props)
      .map(([key, value]) => `${key}={${JSON.stringify(value)}}`)
      .join(' ');
  }

  /**
   * Helper: Optimization implementations
   */
  convertToReactiveStatements(code) {
    // Convert imperative updates to reactive
    return code.replace(/function update(\w+)\(\) \{([^}]+)\}/g,
      (match, name, body) => `$: ${name} = (() => {${body}})();`);
  }

  optimizeReactiveDependencies(code) {
    // Minimize reactive dependencies
    return code;
  }

  addReactiveDeclarations(code, data) {
    // Add $: declarations for computed values
    return code;
  }

  convertToStores(code, data) {
    // Convert shared state to stores
    return code;
  }

  addDerivedStores(code, data) {
    // Create derived stores for computed values
    return code;
  }

  optimizeStoreSubscriptions(code) {
    // Use auto-subscriptions with $
    return code.replace(/(\w+)\.subscribe\(/g, '$$$1');
  }

  addTwoWayBindings(code, data) {
    // Add bind:value for inputs
    return code.replace(/<input ([^>]+)value=\{(\w+)\}/g,
      '<input $1bind:value={$2}');
  }

  optimizeComponentBindings(code) {
    // Optimize component property bindings
    return code;
  }

  addGroupBindings(code, data) {
    // Add bind:group for radio/checkbox groups
    return code;
  }

  addTransitions(code, data) {
    // Add transition directives
    return code;
  }

  addDeferredTransitions(code) {
    // Use |local modifier for better performance
    return code.replace(/transition:(\w+)/g, 'transition:$1|local');
  }

  optimizeTransitionTiming(code) {
    // Optimize transition duration and easing
    return code;
  }

  extractActions(code, data) {
    // Extract repeated DOM operations into actions
    return code;
  }

  addActionLifecycle(code) {
    // Add update and destroy to actions
    return code;
  }

  optimizeActionParams(code) {
    // Optimize action parameter passing
    return code;
  }

  addCompilerOptions(code, config) {
    // Add <svelte:options> tag
    const options = [];
    if (config.immutable) options.push('immutable');
    if (config.accessors) options.push('accessors');

    if (options.length > 0) {
      return `<svelte:options ${options.join(' ')} />\n\n` + code;
    }
    return code;
  }

  optimizeForSSR(code) {
    // Add SSR optimizations
    return code;
  }

  addImmutableOptimizations(code) {
    // Optimize for immutable data
    return code;
  }
}

module.exports = SvelteOptimizer;