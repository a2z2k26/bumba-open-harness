/**
 * composition-patterns.js
 * Sprint 5.4: Component Composition Patterns
 *
 * Generates stories showing how components work together:
 * - Parent-child relationships
 * - Compound components
 * - Layout compositions
 * - Real-world usage patterns
 */

const EventEmitter = require('events');

/**
 * Common composition patterns
 */
const COMPOSITION_PATTERNS = {
  // Layout patterns
  cardWithActions: {
    name: 'Card with Actions',
    description: 'Card component with action buttons',
    components: ['Card', 'Button'],
    layout: 'container'
  },
  formWithValidation: {
    name: 'Form with Validation',
    description: 'Form layout with input fields and validation',
    components: ['Form', 'Input', 'Button', 'Alert'],
    layout: 'form'
  },
  listWithItems: {
    name: 'List with Items',
    description: 'List container with multiple item components',
    components: ['List', 'ListItem', 'Avatar', 'Badge'],
    layout: 'list'
  },
  modalWithContent: {
    name: 'Modal with Content',
    description: 'Modal dialog with header, body, and footer',
    components: ['Modal', 'Button', 'Text'],
    layout: 'modal'
  },
  navWithLinks: {
    name: 'Navigation with Links',
    description: 'Navigation bar with menu items',
    components: ['Nav', 'NavItem', 'Icon'],
    layout: 'horizontal'
  },

  // Compound patterns
  accordion: {
    name: 'Accordion',
    description: 'Collapsible accordion with multiple sections',
    components: ['Accordion', 'AccordionItem', 'AccordionHeader', 'AccordionContent'],
    layout: 'vertical'
  },
  tabs: {
    name: 'Tabs',
    description: 'Tab container with panels',
    components: ['Tabs', 'TabList', 'Tab', 'TabPanel'],
    layout: 'tabbed'
  },
  dropdown: {
    name: 'Dropdown Menu',
    description: 'Dropdown with menu items',
    components: ['Dropdown', 'DropdownTrigger', 'DropdownMenu', 'DropdownItem'],
    layout: 'menu'
  },

  // Data display patterns
  tableWithPagination: {
    name: 'Table with Pagination',
    description: 'Data table with pagination controls',
    components: ['Table', 'TableRow', 'TableCell', 'Pagination'],
    layout: 'table'
  },
  dataGrid: {
    name: 'Data Grid',
    description: 'Grid layout with data cards',
    components: ['Grid', 'Card', 'Badge', 'Avatar'],
    layout: 'grid'
  }
};

/**
 * Layout generators for different patterns
 */
const LAYOUT_GENERATORS = {
  container: (components, props) => ({
    wrapper: components[0],
    children: components.slice(1),
    layout: 'padded'
  }),

  form: (components, props) => ({
    wrapper: 'form',
    children: components,
    layout: 'stacked'
  }),

  list: (components, props) => ({
    wrapper: components[0],
    children: components.slice(1),
    layout: 'vertical',
    repeat: props.itemCount || 3
  }),

  modal: (components, props) => ({
    wrapper: components[0],
    sections: ['header', 'body', 'footer'],
    children: components.slice(1)
  }),

  horizontal: (components, props) => ({
    wrapper: 'div',
    children: components,
    layout: 'flex-row'
  }),

  vertical: (components, props) => ({
    wrapper: 'div',
    children: components,
    layout: 'flex-col'
  }),

  tabbed: (components, props) => ({
    wrapper: components[0],
    tabs: props.tabs || ['Tab 1', 'Tab 2', 'Tab 3'],
    children: components.slice(1)
  }),

  menu: (components, props) => ({
    trigger: components[1],
    menu: components[2],
    items: components.slice(3)
  }),

  table: (components, props) => ({
    wrapper: components[0],
    rows: props.rows || 5,
    columns: props.columns || 4,
    pagination: components[components.length - 1]
  }),

  grid: (components, props) => ({
    wrapper: components[0],
    columns: props.columns || 3,
    children: components.slice(1),
    repeat: props.itemCount || 6
  })
};

class CompositionPatterns extends EventEmitter {
  constructor(options = {}) {
    super();

    this.patterns = { ...COMPOSITION_PATTERNS, ...options.patterns };
    this.layoutGenerators = { ...LAYOUT_GENERATORS, ...options.layoutGenerators };
    this.framework = options.framework || 'react';

    this.stats = {
      compositionsGenerated: 0,
      patternsUsed: new Set(),
      componentsComposed: 0
    };
  }

  /**
   * Generate a composition story
   * @param {string} patternName - Name of the pattern
   * @param {Object} components - Map of component data
   * @param {Object} options - Generation options
   * @returns {Object} Composition configuration
   */
  generateComposition(patternName, components, options = {}) {
    const pattern = this.patterns[patternName];

    if (!pattern) {
      throw new Error(`Unknown composition pattern: ${patternName}`);
    }

    const { props = {}, framework = this.framework } = options;

    // Get layout configuration
    const layoutFn = this.layoutGenerators[pattern.layout] || this.layoutGenerators.container;
    const layoutConfig = layoutFn(pattern.components, props);

    // Build composition
    const composition = {
      name: pattern.name,
      description: pattern.description,
      pattern: patternName,
      components: pattern.components,
      layout: layoutConfig,
      props: this.mergeComponentProps(pattern.components, components, props),
      code: this.generateCompositionCode(pattern, components, layoutConfig, framework),
      storyCode: this.generateCompositionStory(pattern, components, layoutConfig, framework)
    };

    this.stats.compositionsGenerated++;
    this.stats.patternsUsed.add(patternName);
    this.stats.componentsComposed += pattern.components.length;

    this.emit('composition:generated', {
      pattern: patternName,
      components: pattern.components.length
    });

    return composition;
  }

  /**
   * Merge props from multiple components
   */
  mergeComponentProps(componentNames, components, overrideProps) {
    const merged = {};

    componentNames.forEach(name => {
      const component = components[name];
      if (component && component.props) {
        merged[name] = { ...this.getDefaultProps(component.props), ...overrideProps[name] };
      } else {
        merged[name] = overrideProps[name] || {};
      }
    });

    return merged;
  }

  /**
   * Get default props values
   */
  getDefaultProps(props) {
    const defaults = {};

    Object.entries(props || {}).forEach(([name, config]) => {
      if (config.default !== undefined) {
        defaults[name] = config.default;
      }
    });

    return defaults;
  }

  /**
   * Generate composition code
   */
  generateCompositionCode(pattern, components, layoutConfig, framework) {
    switch (framework) {
      case 'react':
        return this.generateReactComposition(pattern, components, layoutConfig);
      case 'vue':
        return this.generateVueComposition(pattern, components, layoutConfig);
      case 'angular':
        return this.generateAngularComposition(pattern, components, layoutConfig);
      case 'svelte':
        return this.generateSvelteComposition(pattern, components, layoutConfig);
      default:
        return this.generateReactComposition(pattern, components, layoutConfig);
    }
  }

  /**
   * Generate React composition code
   */
  generateReactComposition(pattern, components, layoutConfig) {
    const imports = pattern.components
      .map(c => `import { ${c} } from '@design-system/components';`)
      .join('\n');

    let jsx = '';

    switch (pattern.layout) {
      case 'container':
        jsx = this.generateContainerJSX(pattern, layoutConfig);
        break;
      case 'form':
        jsx = this.generateFormJSX(pattern, layoutConfig);
        break;
      case 'list':
        jsx = this.generateListJSX(pattern, layoutConfig);
        break;
      case 'modal':
        jsx = this.generateModalJSX(pattern, layoutConfig);
        break;
      case 'tabbed':
        jsx = this.generateTabbedJSX(pattern, layoutConfig);
        break;
      default:
        jsx = this.generateDefaultJSX(pattern, layoutConfig);
    }

    return `${imports}

function ${pattern.name.replace(/\s+/g, '')}Example() {
  return (
${jsx}
  );
}`;
  }

  /**
   * Generate container layout JSX
   */
  generateContainerJSX(pattern, layoutConfig) {
    const [wrapper, ...children] = pattern.components;
    const childrenJSX = children.map(c => `      <${c} />`).join('\n');

    return `    <${wrapper}>
${childrenJSX}
    </${wrapper}>`;
  }

  /**
   * Generate form layout JSX
   */
  generateFormJSX(pattern, layoutConfig) {
    const components = pattern.components;

    return `    <form className="space-y-4">
      <${components[1] || 'Input'} label="Name" placeholder="Enter your name" />
      <${components[1] || 'Input'} label="Email" type="email" placeholder="Enter your email" />
      <${components[2] || 'Button'} type="submit">Submit</${components[2] || 'Button'}>
    </form>`;
  }

  /**
   * Generate list layout JSX
   */
  generateListJSX(pattern, layoutConfig) {
    const [List, ListItem, ...extras] = pattern.components;
    const repeat = layoutConfig.repeat || 3;

    const items = Array(repeat).fill(0)
      .map((_, i) => `      <${ListItem} key={${i}}>Item ${i + 1}</${ListItem}>`)
      .join('\n');

    return `    <${List}>
${items}
    </${List}>`;
  }

  /**
   * Generate modal layout JSX
   */
  generateModalJSX(pattern, layoutConfig) {
    const [Modal, ...children] = pattern.components;

    return `    <${Modal} isOpen={true} onClose={() => {}}>
      <${Modal}.Header>Modal Title</${Modal}.Header>
      <${Modal}.Body>
        <p>Modal content goes here.</p>
      </${Modal}.Body>
      <${Modal}.Footer>
        <Button variant="secondary">Cancel</Button>
        <Button variant="primary">Confirm</Button>
      </${Modal}.Footer>
    </${Modal}>`;
  }

  /**
   * Generate tabbed layout JSX
   */
  generateTabbedJSX(pattern, layoutConfig) {
    const [Tabs, TabList, Tab, TabPanel] = pattern.components;
    const tabs = layoutConfig.tabs || ['Tab 1', 'Tab 2', 'Tab 3'];

    const tabItems = tabs.map((t, i) => `        <${Tab} key={${i}}>${t}</${Tab}>`).join('\n');
    const panels = tabs.map((t, i) => `      <${TabPanel} key={${i}}>Content for ${t}</${TabPanel}>`).join('\n');

    return `    <${Tabs} defaultValue={0}>
      <${TabList}>
${tabItems}
      </${TabList}>
${panels}
    </${Tabs}>`;
  }

  /**
   * Generate default layout JSX
   */
  generateDefaultJSX(pattern, layoutConfig) {
    const components = pattern.components;
    return `    <div className="flex gap-4">
${components.map(c => `      <${c} />`).join('\n')}
    </div>`;
  }

  /**
   * Generate Vue composition code
   */
  generateVueComposition(pattern, components, layoutConfig) {
    const imports = pattern.components
      .map(c => `  ${c}`)
      .join(',\n');

    return `<template>
  <${pattern.components[0]}>
    <!-- Composition content -->
  </${pattern.components[0]}>
</template>

<script setup>
import {
${imports}
} from '@design-system/components';
</script>`;
  }

  /**
   * Generate Angular composition code
   */
  generateAngularComposition(pattern, components, layoutConfig) {
    const selector = pattern.name.toLowerCase().replace(/\s+/g, '-');

    return `<app-${selector}>
  <!-- Angular composition content -->
</app-${selector}>`;
  }

  /**
   * Generate Svelte composition code
   */
  generateSvelteComposition(pattern, components, layoutConfig) {
    const imports = pattern.components
      .map(c => `  import { ${c} } from '@design-system/components';`)
      .join('\n');

    return `<script>
${imports}
</script>

<${pattern.components[0]}>
  <!-- Svelte composition content -->
</${pattern.components[0]}>`;
  }

  /**
   * Generate composition story code
   */
  generateCompositionStory(pattern, components, layoutConfig, framework) {
    const storyName = pattern.name.replace(/\s+/g, '');
    const imports = pattern.components
      .map(c => c)
      .join(', ');

    return `import type { Meta, StoryObj } from '@storybook/react';
import { ${imports} } from '@design-system/components';

// Composition wrapper component
const ${storyName}Composition = () => {
  return (
    ${this.generateContainerJSX(pattern, layoutConfig)}
  );
};

const meta: Meta<typeof ${storyName}Composition> = {
  title: 'Compositions/${pattern.name}',
  component: ${storyName}Composition,
  parameters: {
    layout: 'padded',
    docs: {
      description: {
        component: '${pattern.description}',
      },
    },
  },
};

export default meta;
type Story = StoryObj<typeof ${storyName}Composition>;

export const Default: Story = {};

export const WithCustomProps: Story = {
  decorators: [
    (Story) => (
      <div className="p-4 bg-gray-100">
        <Story />
      </div>
    ),
  ],
};
`;
  }

  /**
   * Get all available patterns
   */
  getPatterns() {
    return Object.entries(this.patterns).map(([key, pattern]) => ({
      id: key,
      ...pattern
    }));
  }

  /**
   * Add custom pattern
   */
  addPattern(name, config) {
    this.patterns[name] = config;
    return this;
  }

  /**
   * Generate compositions for multiple patterns
   */
  generateMultipleCompositions(patternNames, components, options = {}) {
    const compositions = {};

    patternNames.forEach(patternName => {
      try {
        compositions[patternName] = this.generateComposition(patternName, components, options);
      } catch (error) {
        compositions[patternName] = { error: error.message };
      }
    });

    return compositions;
  }

  /**
   * Get statistics
   */
  getStats() {
    return {
      ...this.stats,
      patternsUsed: Array.from(this.stats.patternsUsed)
    };
  }

  /**
   * Reset statistics
   */
  resetStats() {
    this.stats = {
      compositionsGenerated: 0,
      patternsUsed: new Set(),
      componentsComposed: 0
    };
  }
}

// Export singleton and class
const compositionPatterns = new CompositionPatterns();

module.exports = {
  CompositionPatterns,
  compositionPatterns,
  COMPOSITION_PATTERNS,
  LAYOUT_GENERATORS
};
