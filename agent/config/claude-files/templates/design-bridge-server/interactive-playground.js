/**
 * interactive-playground.js
 * Sprint 5.2: Interactive Examples & Playgrounds
 *
 * Generates interactive component playgrounds with:
 * - Live prop editing
 * - Code preview
 * - Multiple example configurations
 * - Copy-to-clipboard support
 */

const EventEmitter = require('events');

/**
 * Playground configuration presets
 */
const PLAYGROUND_PRESETS = {
  minimal: {
    showCode: false,
    showProps: true,
    editable: true,
    layout: 'vertical'
  },
  full: {
    showCode: true,
    showProps: true,
    editable: true,
    layout: 'horizontal'
  },
  showcase: {
    showCode: false,
    showProps: false,
    editable: false,
    layout: 'centered'
  },
  developer: {
    showCode: true,
    showProps: true,
    editable: true,
    showSourcePanel: true,
    layout: 'horizontal'
  }
};

/**
 * Code template generators by framework
 */
const CODE_TEMPLATES = {
  react: (component, props) => {
    const propsStr = formatPropsForJSX(props);
    return `import { ${component.name} } from '@design-system/components';

function Example() {
  return (
    <${component.name}${propsStr ? `\n      ${propsStr}` : ''} />
  );
}`;
  },

  vue: (component, props) => {
    const propsStr = formatPropsForVue(props);
    return `<template>
  <${component.name}${propsStr ? `\n    ${propsStr}` : ''} />
</template>

<script setup>
import { ${component.name} } from '@design-system/components';
</script>`;
  },

  angular: (component, props) => {
    const propsStr = formatPropsForAngular(props);
    return `<app-${toKebabCase(component.name)}${propsStr ? `\n  ${propsStr}` : ''}></app-${toKebabCase(component.name)}>`;
  },

  svelte: (component, props) => {
    const propsStr = formatPropsForSvelte(props);
    return `<script>
  import { ${component.name} } from '@design-system/components';
</script>

<${component.name}${propsStr ? `\n  ${propsStr}` : ''} />`;
  }
};

class InteractivePlayground extends EventEmitter {
  constructor(options = {}) {
    super();

    this.presets = { ...PLAYGROUND_PRESETS, ...options.presets };
    this.codeTemplates = { ...CODE_TEMPLATES, ...options.codeTemplates };
    this.defaultFramework = options.framework || 'react';

    this.stats = {
      playgroundsGenerated: 0,
      examplesCreated: 0,
      codeSnippetsGenerated: 0
    };
  }

  /**
   * Generate a playground configuration for a component
   * @param {Object} component - Component data
   * @param {Object} options - Playground options
   * @returns {Object} Playground configuration
   */
  generatePlayground(component, options = {}) {
    const {
      preset = 'full',
      framework = this.defaultFramework,
      examples = [],
      customConfig = {}
    } = options;

    const baseConfig = this.presets[preset] || this.presets.full;
    const props = component.props || {};

    // Generate examples if none provided
    const generatedExamples = examples.length > 0
      ? examples
      : this.generateDefaultExamples(component);

    const playground = {
      component: component.name,
      framework,
      config: { ...baseConfig, ...customConfig },
      props: this.generatePropControls(props),
      examples: generatedExamples,
      codeSnippets: this.generateCodeSnippets(component, generatedExamples, framework),
      metadata: {
        generatedAt: new Date().toISOString(),
        version: '1.0.0'
      }
    };

    this.stats.playgroundsGenerated++;
    this.emit('playground:generated', { component: component.name });

    return playground;
  }

  /**
   * Generate prop controls for interactive editing
   * @param {Object} props - Component props definition
   * @returns {Object} Prop controls configuration
   */
  generatePropControls(props) {
    const controls = {};

    Object.entries(props).forEach(([name, config]) => {
      controls[name] = {
        type: this.getControlType(config),
        label: this.formatLabel(name),
        description: config.description || '',
        defaultValue: config.default,
        required: config.required || false,
        ...this.getControlConfig(config)
      };
    });

    return controls;
  }

  /**
   * Get control type based on prop config
   */
  getControlType(config) {
    const type = config.type?.toLowerCase() || 'text';

    // Handle enum/options
    if (config.options || config.enum) {
      return 'select';
    }

    const typeMap = {
      'string': 'text',
      'number': 'number',
      'boolean': 'boolean',
      'array': 'array',
      'object': 'object',
      'function': 'action',
      '() => void': 'action'
    };

    return typeMap[type] || 'text';
  }

  /**
   * Get additional control configuration
   */
  getControlConfig(config) {
    const controlConfig = {};

    if (config.options || config.enum) {
      controlConfig.options = config.options || config.enum;
    }

    if (config.min !== undefined) {
      controlConfig.min = config.min;
    }

    if (config.max !== undefined) {
      controlConfig.max = config.max;
    }

    if (config.step !== undefined) {
      controlConfig.step = config.step;
    }

    return controlConfig;
  }

  /**
   * Generate default examples for a component
   * @param {Object} component - Component data
   * @returns {Array} Array of example configurations
   */
  generateDefaultExamples(component) {
    const props = component.props || {};
    const examples = [];

    // Default example
    examples.push({
      name: 'Default',
      description: `Basic ${component.name} example`,
      props: this.getDefaultProps(props)
    });

    // Generate variant examples based on prop types
    Object.entries(props).forEach(([name, config]) => {
      if (config.options || config.enum) {
        const options = config.options || config.enum;
        options.forEach(option => {
          examples.push({
            name: `${this.formatLabel(name)}: ${option}`,
            description: `${component.name} with ${name}="${option}"`,
            props: { ...this.getDefaultProps(props), [name]: option }
          });
        });
      }
    });

    this.stats.examplesCreated += examples.length;
    return examples;
  }

  /**
   * Generate code snippets for examples
   * @param {Object} component - Component data
   * @param {Array} examples - Array of examples
   * @param {string} framework - Target framework
   * @returns {Object} Code snippets by example name
   */
  generateCodeSnippets(component, examples, framework) {
    const snippets = {};
    const templateFn = this.codeTemplates[framework] || this.codeTemplates.react;

    examples.forEach(example => {
      snippets[example.name] = {
        code: templateFn(component, example.props),
        language: this.getLanguage(framework)
      };
      this.stats.codeSnippetsGenerated++;
    });

    return snippets;
  }

  /**
   * Get language identifier for framework
   */
  getLanguage(framework) {
    const languages = {
      react: 'tsx',
      vue: 'vue',
      angular: 'html',
      svelte: 'svelte'
    };
    return languages[framework] || 'tsx';
  }

  /**
   * Generate Storybook story with playground
   * @param {Object} component - Component data
   * @param {string} framework - Target framework
   * @returns {string} Story code with playground
   */
  generatePlaygroundStory(component, framework = 'react') {
    const playground = this.generatePlayground(component, { framework });
    const componentName = component.name;

    let code = '';

    switch (framework) {
      case 'react':
        code = this.generateReactPlaygroundStory(componentName, playground);
        break;
      case 'vue':
        code = this.generateVuePlaygroundStory(componentName, playground);
        break;
      default:
        code = this.generateReactPlaygroundStory(componentName, playground);
    }

    return code;
  }

  /**
   * Generate React playground story
   */
  generateReactPlaygroundStory(componentName, playground) {
    const examples = playground.examples;

    let code = `import type { Meta, StoryObj } from '@storybook/react';
import { ${componentName} } from './${componentName}';

const meta: Meta<typeof ${componentName}> = {
  title: 'Playground/${componentName}',
  component: ${componentName},
  parameters: {
    layout: '${playground.config.layout}',
    docs: {
      description: {
        component: 'Interactive playground for ${componentName} component.',
      },
    },
  },
  tags: ['autodocs'],
  argTypes: ${JSON.stringify(this.convertToArgTypes(playground.props), null, 4)},
};

export default meta;
type Story = StoryObj<typeof ${componentName}>;

`;

    // Generate stories for each example
    examples.forEach(example => {
      const variantName = example.name.replace(/[^a-zA-Z0-9]/g, '');
      code += `/**
 * ${example.description}
 */
export const ${variantName}: Story = {
  args: ${JSON.stringify(example.props, null, 4)},
};

`;
    });

    // Add interactive playground story
    code += `/**
 * Interactive Playground - modify props in the controls panel
 */
export const Playground: Story = {
  args: ${JSON.stringify(examples[0]?.props || {}, null, 4)},
  parameters: {
    controls: { expanded: true },
  },
};
`;

    return code;
  }

  /**
   * Generate Vue playground story
   */
  generateVuePlaygroundStory(componentName, playground) {
    const examples = playground.examples;

    let code = `import type { Meta, StoryObj } from '@storybook/vue3';
import ${componentName} from './${componentName}.vue';

const meta: Meta<typeof ${componentName}> = {
  title: 'Playground/${componentName}',
  component: ${componentName},
  parameters: {
    layout: '${playground.config.layout}',
    docs: {
      description: {
        component: 'Interactive playground for ${componentName} component.',
      },
    },
  },
  tags: ['autodocs'],
};

export default meta;
type Story = StoryObj<typeof ${componentName}>;

`;

    examples.forEach(example => {
      const variantName = example.name.replace(/[^a-zA-Z0-9]/g, '');
      code += `export const ${variantName}: Story = {
  args: ${JSON.stringify(example.props, null, 4)},
};

`;
    });

    return code;
  }

  /**
   * Convert prop controls to Storybook argTypes
   */
  convertToArgTypes(propControls) {
    const argTypes = {};

    Object.entries(propControls).forEach(([name, control]) => {
      argTypes[name] = {
        control: { type: control.type },
        description: control.description,
        table: {
          defaultValue: { summary: control.defaultValue }
        }
      };

      if (control.options) {
        argTypes[name].options = control.options;
        argTypes[name].control = { type: 'select' };
      }
    });

    return argTypes;
  }

  /**
   * Get default props values
   */
  getDefaultProps(props) {
    const defaults = {};

    Object.entries(props).forEach(([name, config]) => {
      if (config.default !== undefined) {
        defaults[name] = config.default;
      }
    });

    return defaults;
  }

  /**
   * Format prop name as label
   */
  formatLabel(name) {
    return name
      .replace(/([A-Z])/g, ' $1')
      .replace(/^./, str => str.toUpperCase())
      .trim();
  }

  /**
   * Add custom preset
   */
  addPreset(name, config) {
    this.presets[name] = config;
    return this;
  }

  /**
   * Get available presets
   */
  getPresets() {
    return { ...this.presets };
  }

  /**
   * Get statistics
   */
  getStats() {
    return { ...this.stats };
  }

  /**
   * Reset statistics
   */
  resetStats() {
    this.stats = {
      playgroundsGenerated: 0,
      examplesCreated: 0,
      codeSnippetsGenerated: 0
    };
  }
}

// Helper functions
function formatPropsForJSX(props) {
  return Object.entries(props)
    .map(([key, value]) => {
      if (typeof value === 'boolean') {
        return value ? key : `${key}={false}`;
      }
      if (typeof value === 'string') {
        return `${key}="${value}"`;
      }
      return `${key}={${JSON.stringify(value)}}`;
    })
    .join('\n      ');
}

function formatPropsForVue(props) {
  return Object.entries(props)
    .map(([key, value]) => {
      if (typeof value === 'boolean') {
        return value ? `:${key}="true"` : `:${key}="false"`;
      }
      if (typeof value === 'string') {
        return `${key}="${value}"`;
      }
      return `:${key}="${JSON.stringify(value)}"`;
    })
    .join('\n    ');
}

function formatPropsForAngular(props) {
  return Object.entries(props)
    .map(([key, value]) => {
      if (typeof value === 'boolean') {
        return `[${key}]="${value}"`;
      }
      if (typeof value === 'string') {
        return `${key}="${value}"`;
      }
      return `[${key}]='${JSON.stringify(value)}'`;
    })
    .join('\n  ');
}

function formatPropsForSvelte(props) {
  return Object.entries(props)
    .map(([key, value]) => {
      if (typeof value === 'boolean') {
        return value ? key : `${key}={false}`;
      }
      if (typeof value === 'string') {
        return `${key}="${value}"`;
      }
      return `${key}={${JSON.stringify(value)}}`;
    })
    .join('\n  ');
}

function toKebabCase(str) {
  return str
    .replace(/([a-z])([A-Z])/g, '$1-$2')
    .toLowerCase();
}

// Export singleton and class
const interactivePlayground = new InteractivePlayground();

module.exports = {
  InteractivePlayground,
  interactivePlayground,
  PLAYGROUND_PRESETS,
  CODE_TEMPLATES
};
