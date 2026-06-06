/**
 * story-variants.js
 * Sprint 5.1: Advanced Story Variants
 *
 * Generates advanced story variants including:
 * - State variants (Loading, Error, Success, Disabled, etc.)
 * - Responsive variants (Mobile, Tablet, Desktop viewports)
 * - Theme variants (Light, Dark, custom themes)
 */

const EventEmitter = require('events');

/**
 * Predefined viewport sizes for responsive variants
 */
const VIEWPORT_SIZES = {
  mobile: { width: 375, height: 667, label: 'Mobile' },
  tablet: { width: 768, height: 1024, label: 'Tablet' },
  desktop: { width: 1280, height: 800, label: 'Desktop' },
  wide: { width: 1920, height: 1080, label: 'Wide Desktop' }
};

/**
 * Common component state patterns
 */
const STATE_PATTERNS = {
  // Data states
  loading: { isLoading: true, data: null, error: null },
  success: { isLoading: false, data: {}, error: null },
  error: { isLoading: false, data: null, error: 'An error occurred' },
  empty: { isLoading: false, data: [], error: null },

  // Interactive states
  disabled: { disabled: true },
  readonly: { readonly: true },
  focused: { autoFocus: true },

  // Button states
  primary: { variant: 'primary' },
  secondary: { variant: 'secondary' },
  outline: { variant: 'outline' },
  ghost: { variant: 'ghost' },

  // Size variants
  small: { size: 'sm' },
  medium: { size: 'md' },
  large: { size: 'lg' },

  // Form states
  valid: { isValid: true, errorMessage: null },
  invalid: { isValid: false, errorMessage: 'This field is required' },
  touched: { isTouched: true }
};

/**
 * Theme configurations
 */
const THEME_CONFIGS = {
  light: {
    backgrounds: { default: '#ffffff' },
    parameters: { theme: 'light' }
  },
  dark: {
    backgrounds: { default: '#1a1a2e' },
    parameters: { theme: 'dark' }
  },
  highContrast: {
    backgrounds: { default: '#000000' },
    parameters: { theme: 'high-contrast' }
  }
};

class StoryVariants extends EventEmitter {
  constructor(options = {}) {
    super();

    this.viewports = { ...VIEWPORT_SIZES, ...options.viewports };
    this.statePatterns = { ...STATE_PATTERNS, ...options.statePatterns };
    this.themes = { ...THEME_CONFIGS, ...options.themes };

    this.stats = {
      variantsGenerated: 0,
      stateVariants: 0,
      responsiveVariants: 0,
      themeVariants: 0
    };
  }

  /**
   * Generate state variants for a component
   * @param {Object} component - Component data
   * @param {string[]} states - Array of state names to generate
   * @returns {Object} State variants object
   */
  generateStateVariants(component, states = ['default', 'loading', 'error', 'disabled']) {
    const variants = {};
    const props = component.props || {};

    states.forEach(stateName => {
      const stateProps = this.statePatterns[stateName] || {};
      const variantName = this.formatVariantName(stateName);

      // Merge component props with state props
      const mergedArgs = { ...this.getDefaultArgs(props), ...stateProps };

      variants[variantName] = {
        name: variantName,
        args: mergedArgs,
        parameters: {
          docs: {
            description: {
              story: `${component.name} in ${stateName} state`
            }
          }
        }
      };

      this.stats.stateVariants++;
    });

    this.stats.variantsGenerated += Object.keys(variants).length;
    this.emit('variants:state', { component: component.name, count: Object.keys(variants).length });

    return variants;
  }

  /**
   * Generate responsive variants for different viewport sizes
   * @param {Object} component - Component data
   * @param {string[]} viewportNames - Array of viewport names
   * @returns {Object} Responsive variants object
   */
  generateResponsiveVariants(component, viewportNames = ['mobile', 'tablet', 'desktop']) {
    const variants = {};
    const props = component.props || {};

    viewportNames.forEach(viewportName => {
      const viewport = this.viewports[viewportName];
      if (!viewport) {
        console.warn(`Unknown viewport: ${viewportName}`);
        return;
      }

      const variantName = viewport.label.replace(/\s+/g, '');

      variants[variantName] = {
        name: variantName,
        args: this.getDefaultArgs(props),
        parameters: {
          viewport: {
            defaultViewport: viewportName
          },
          docs: {
            description: {
              story: `${component.name} at ${viewport.label} (${viewport.width}x${viewport.height})`
            }
          }
        }
      };

      this.stats.responsiveVariants++;
    });

    this.stats.variantsGenerated += Object.keys(variants).length;
    this.emit('variants:responsive', { component: component.name, count: Object.keys(variants).length });

    return variants;
  }

  /**
   * Generate theme variants (light, dark, etc.)
   * @param {Object} component - Component data
   * @param {string[]} themeNames - Array of theme names
   * @returns {Object} Theme variants object
   */
  generateThemeVariants(component, themeNames = ['light', 'dark']) {
    const variants = {};
    const props = component.props || {};

    themeNames.forEach(themeName => {
      const theme = this.themes[themeName];
      if (!theme) {
        console.warn(`Unknown theme: ${themeName}`);
        return;
      }

      const variantName = this.formatVariantName(themeName) + 'Theme';

      variants[variantName] = {
        name: variantName,
        args: this.getDefaultArgs(props),
        parameters: {
          backgrounds: theme.backgrounds,
          ...theme.parameters,
          docs: {
            description: {
              story: `${component.name} with ${themeName} theme`
            }
          }
        }
      };

      this.stats.themeVariants++;
    });

    this.stats.variantsGenerated += Object.keys(variants).length;
    this.emit('variants:theme', { component: component.name, count: Object.keys(variants).length });

    return variants;
  }

  /**
   * Generate all variant types for a component
   * @param {Object} component - Component data
   * @param {Object} options - Generation options
   * @returns {Object} All variants combined
   */
  generateAllVariants(component, options = {}) {
    const {
      states = ['default', 'loading', 'error', 'disabled'],
      viewports = ['mobile', 'tablet', 'desktop'],
      themes = ['light', 'dark'],
      includeStates = true,
      includeResponsive = true,
      includeThemes = true
    } = options;

    const variants = {
      Default: {
        name: 'Default',
        args: this.getDefaultArgs(component.props || {}),
        parameters: {}
      }
    };

    if (includeStates && states.length > 0) {
      Object.assign(variants, this.generateStateVariants(component, states));
    }

    if (includeResponsive && viewports.length > 0) {
      Object.assign(variants, this.generateResponsiveVariants(component, viewports));
    }

    if (includeThemes && themes.length > 0) {
      Object.assign(variants, this.generateThemeVariants(component, themes));
    }

    this.emit('variants:all', { component: component.name, count: Object.keys(variants).length });

    return variants;
  }

  /**
   * Generate story code with all variants
   * @param {Object} component - Component data
   * @param {Object} variants - Variants object
   * @param {string} framework - Target framework
   * @returns {string} Generated story code
   */
  generateStoryCode(component, variants, framework = 'react') {
    switch (framework) {
      case 'react':
      case 'react-native':
        return this.generateReactStoryCode(component, variants);
      case 'vue':
        return this.generateVueStoryCode(component, variants);
      case 'angular':
        return this.generateAngularStoryCode(component, variants);
      case 'svelte':
        return this.generateSvelteStoryCode(component, variants);
      default:
        return this.generateReactStoryCode(component, variants);
    }
  }

  /**
   * Generate React story code with variants
   * Sprint 4.4: Added argTypes generation for proper Storybook controls
   */
  generateReactStoryCode(component, variants) {
    const componentName = component.name;
    const variantEntries = Object.entries(variants);

    // Sprint 4.4: Generate argTypes from component props
    const argTypesBlock = this.generateArgTypesBlock(component.props);

    let code = `import type { Meta, StoryObj } from '@storybook/react';
import { ${componentName} } from './${componentName}';

const meta: Meta<typeof ${componentName}> = {
  title: 'Components/${componentName}',
  component: ${componentName},
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],${argTypesBlock}
};

export default meta;
type Story = StoryObj<typeof ${componentName}>;

`;

    // Generate each variant
    variantEntries.forEach(([name, variant]) => {
      code += `/**
 * ${variant.parameters?.docs?.description?.story || `${componentName} - ${name}`}
 */
export const ${name}: Story = {
  args: ${JSON.stringify(variant.args, null, 4).replace(/"/g, "'")},
${this.formatParameters(variant.parameters)}};

`;
    });

    return code;
  }

  /**
   * Generate Vue story code with variants
   */
  generateVueStoryCode(component, variants) {
    const componentName = component.name;
    const variantEntries = Object.entries(variants);

    let code = `import type { Meta, StoryObj } from '@storybook/vue3';
import ${componentName} from './${componentName}.vue';

const meta: Meta<typeof ${componentName}> = {
  title: 'Components/${componentName}',
  component: ${componentName},
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
};

export default meta;
type Story = StoryObj<typeof ${componentName}>;

`;

    variantEntries.forEach(([name, variant]) => {
      code += `export const ${name}: Story = {
  args: ${JSON.stringify(variant.args, null, 4).replace(/"/g, "'")},
${this.formatParameters(variant.parameters)}};

`;
    });

    return code;
  }

  /**
   * Generate Angular story code with variants
   */
  generateAngularStoryCode(component, variants) {
    const componentName = component.name;
    const variantEntries = Object.entries(variants);

    let code = `import type { Meta, StoryObj } from '@storybook/angular';
import { ${componentName}Component } from './${componentName.toLowerCase()}.component';

const meta: Meta<${componentName}Component> = {
  title: 'Components/${componentName}',
  component: ${componentName}Component,
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
};

export default meta;
type Story = StoryObj<${componentName}Component>;

`;

    variantEntries.forEach(([name, variant]) => {
      code += `export const ${name}: Story = {
  args: ${JSON.stringify(variant.args, null, 4).replace(/"/g, "'")},
${this.formatParameters(variant.parameters)}};

`;
    });

    return code;
  }

  /**
   * Generate Svelte story code with variants
   */
  generateSvelteStoryCode(component, variants) {
    const componentName = component.name;
    const variantEntries = Object.entries(variants);

    let code = `import type { Meta, StoryObj } from '@storybook/svelte';
import ${componentName} from './${componentName}.svelte';

const meta: Meta<typeof ${componentName}> = {
  title: 'Components/${componentName}',
  component: ${componentName},
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
};

export default meta;
type Story = StoryObj<typeof ${componentName}>;

`;

    variantEntries.forEach(([name, variant]) => {
      code += `export const ${name}: Story = {
  args: ${JSON.stringify(variant.args, null, 4).replace(/"/g, "'")},
${this.formatParameters(variant.parameters)}};

`;
    });

    return code;
  }

  /**
   * Format variant name (capitalize first letter)
   */
  formatVariantName(name) {
    return name.charAt(0).toUpperCase() + name.slice(1);
  }

  /**
   * Get default args from props
   */
  getDefaultArgs(props) {
    const args = {};

    Object.entries(props).forEach(([key, prop]) => {
      if (prop.default !== undefined) {
        args[key] = prop.default;
      } else {
        // Generate sensible defaults based on type
        switch (prop.type) {
          case 'string':
            args[key] = '';
            break;
          case 'number':
            args[key] = 0;
            break;
          case 'boolean':
            args[key] = false;
            break;
          case 'array':
            args[key] = [];
            break;
          case 'object':
            args[key] = {};
            break;
        }
      }
    });

    return args;
  }

  /**
   * Format parameters object for story code
   */
  formatParameters(parameters) {
    if (!parameters || Object.keys(parameters).length === 0) {
      return '';
    }

    // Filter out docs descriptions for cleaner output
    const filtered = { ...parameters };
    if (filtered.docs) {
      delete filtered.docs;
    }

    if (Object.keys(filtered).length === 0) {
      return '';
    }

    return `  parameters: ${JSON.stringify(filtered, null, 4).replace(/"/g, "'")},\n`;
  }

  /**
   * Generate argTypes block for Storybook meta
   * Sprint 4.4: Generates proper controls including actions for event handlers
   * @param {Object} props - Component props
   * @returns {string} Formatted argTypes block for meta object
   */
  generateArgTypesBlock(props) {
    if (!props || Object.keys(props).length === 0) {
      return '';
    }

    const argTypes = {};

    Object.entries(props).forEach(([key, prop]) => {
      // Handle different prop type formats
      const propType = prop.type || prop.rawType || 'string';

      // Detect function props for Storybook actions
      // Check if prop name starts with 'on' (onClick, onChange, etc.)
      // or if the type is a function signature
      const isEventHandler = key.startsWith('on') && key.length > 2 && key[2] === key[2].toUpperCase();
      const isFunctionType = propType.includes('() =>') ||
                             propType.includes('=> void') ||
                             propType.includes('Function') ||
                             propType.includes('Event') ||
                             propType === 'function';

      if (isEventHandler || isFunctionType) {
        // Use Storybook action for event handlers
        const actionName = key.startsWith('on')
          ? key.slice(2).charAt(0).toLowerCase() + key.slice(3)
          : key;
        argTypes[key] = { action: actionName };
      } else if (propType === 'enum' || (prop.values && Array.isArray(prop.values))) {
        argTypes[key] = {
          control: 'select',
          options: prop.values || []
        };
      } else if (propType === 'boolean') {
        argTypes[key] = { control: 'boolean' };
      } else if (propType === 'number') {
        argTypes[key] = { control: 'number' };
      } else if (propType === 'string') {
        argTypes[key] = { control: 'text' };
      } else if (propType.includes('|')) {
        // Union type - treat as enum
        const values = propType.split('|').map(v => v.trim().replace(/['\"]/g, ''));
        argTypes[key] = {
          control: 'select',
          options: values
        };
      } else {
        argTypes[key] = { control: 'text' };
      }

      // Add description if available
      if (prop.description) {
        argTypes[key].description = prop.description;
      }
    });

    if (Object.keys(argTypes).length === 0) {
      return '';
    }

    // Format as indented block for meta object
    const formatted = JSON.stringify(argTypes, null, 4)
      .replace(/"/g, "'")
      .split('\n')
      .map((line, i) => i === 0 ? line : '  ' + line)
      .join('\n');

    return `\n  argTypes: ${formatted},`;
  }

  /**
   * Add custom viewport
   */
  addViewport(name, config) {
    this.viewports[name] = config;
    return this;
  }

  /**
   * Add custom state pattern
   */
  addStatePattern(name, props) {
    this.statePatterns[name] = props;
    return this;
  }

  /**
   * Add custom theme
   */
  addTheme(name, config) {
    this.themes[name] = config;
    return this;
  }

  /**
   * Get available viewports
   */
  getViewports() {
    return { ...this.viewports };
  }

  /**
   * Get available state patterns
   */
  getStatePatterns() {
    return { ...this.statePatterns };
  }

  /**
   * Get available themes
   */
  getThemes() {
    return { ...this.themes };
  }

  /**
   * Get generation statistics
   */
  getStats() {
    return { ...this.stats };
  }

  /**
   * Reset statistics
   */
  resetStats() {
    this.stats = {
      variantsGenerated: 0,
      stateVariants: 0,
      responsiveVariants: 0,
      themeVariants: 0
    };
  }
}

// Export singleton instance and class
const storyVariants = new StoryVariants();

module.exports = {
  StoryVariants,
  storyVariants,
  VIEWPORT_SIZES,
  STATE_PATTERNS,
  THEME_CONFIGS
};
