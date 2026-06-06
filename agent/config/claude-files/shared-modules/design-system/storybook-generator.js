/**
 * Storybook Story Generator
 *
 * Automatically generates Storybook stories for transformed components
 * Ensures all components have documentation and visual testing
 */

const fs = require('fs');
const path = require('path');

class StorybookGenerator {
  constructor(projectPath) {
    this.projectPath = projectPath;
    this.storiesPath = path.join(projectPath, 'src/stories');

    // Ensure stories directory exists
    if (!fs.existsSync(this.storiesPath)) {
      fs.mkdirSync(this.storiesPath, { recursive: true });
    }
  }

  /**
   * Generate Storybook story for a component
   *
   * @param {string} componentName - Component name (PascalCase)
   * @param {Object} extractedContent - Extracted content from Figma
   * @param {Object} options - Generation options
   * @returns {string} Generated story code
   */
  generateStory(componentName, extractedContent, options = {}) {
    const {
      componentPath = `../design-system/components/${componentName}`,
      category = 'Components',
      includeVariants = true,
      includeControls = true
    } = options;

    const stories = [];

    // Default story
    stories.push(this.generateDefaultStory(componentName, extractedContent));

    // Variant stories
    if (includeVariants && extractedContent.variants) {
      stories.push(...this.generateVariantStories(componentName, extractedContent));
    }

    // With children story (if component accepts children)
    if (this.componentAcceptsChildren(extractedContent)) {
      stories.push(this.generateWithChildrenStory(componentName));
    }

    // Interactive/playground story
    if (includeControls) {
      stories.push(this.generatePlaygroundStory(componentName, extractedContent));
    }

    return `import type { Meta, StoryObj } from '@storybook/react';
import { ${componentName} } from '${componentPath}';

/**
 * ${componentName} Component
 *
 * ${this.generateDescription(extractedContent)}
 *
 * Generated from Figma Design System
 * Extraction Date: ${new Date().toISOString().split('T')[0]}
 */
const meta: Meta<typeof ${componentName}> = {
  title: '${category}/${componentName}',
  component: ${componentName},
  tags: ['autodocs'],
  argTypes: ${this.generateArgTypes(extractedContent)},
};

export default meta;
type Story = StoryObj<typeof ${componentName}>;

${stories.join('\n\n')}
`;
  }

  /**
   * Generate default story
   */
  generateDefaultStory(componentName, extractedContent) {
    const props = this.extractDefaultProps(extractedContent);

    return `/**
 * Default state of ${componentName}
 */
export const Default: Story = {
  args: ${JSON.stringify(props, null, 2)},
};`;
  }

  /**
   * Generate variant stories
   */
  generateVariantStories(componentName, extractedContent) {
    const stories = [];

    if (extractedContent.variants) {
      for (const [variantKey, variantValue] of Object.entries(extractedContent.variants)) {
        const storyName = this.variantToStoryName(variantKey, variantValue);
        const props = { ...this.extractDefaultProps(extractedContent) };
        props[this.toCamelCase(variantKey)] = variantValue;

        stories.push(`/**
 * ${componentName} with ${variantKey}=${variantValue}
 */
export const ${storyName}: Story = {
  args: ${JSON.stringify(props, null, 2)},
};`);
      }
    }

    return stories;
  }

  /**
   * Generate story with children
   */
  generateWithChildrenStory(componentName) {
    return `/**
 * ${componentName} with custom children
 */
export const WithChildren: Story = {
  args: {
    children: 'Custom content goes here',
  },
};`;
  }

  /**
   * Generate playground/interactive story
   */
  generatePlaygroundStory(componentName, extractedContent) {
    const props = this.extractDefaultProps(extractedContent);

    return `/**
 * Interactive playground for ${componentName}
 * Use controls panel to modify props
 */
export const Playground: Story = {
  args: ${JSON.stringify(props, null, 2)},
};`;
  }

  /**
   * Generate argTypes for Storybook controls
   */
  generateArgTypes(extractedContent) {
    const argTypes = {
      className: {
        control: 'text',
        description: 'CSS class name',
      },
    };

    // Add variant controls
    if (extractedContent.variants) {
      for (const [key, value] of Object.entries(extractedContent.variants)) {
        const propName = this.toCamelCase(key);
        argTypes[propName] = {
          control: 'text',
          description: `${key} variant`,
          defaultValue: value,
        };
      }
    }

    // Add children control if applicable
    if (this.componentAcceptsChildren(extractedContent)) {
      argTypes.children = {
        control: 'text',
        description: 'Child content',
      };
    }

    return JSON.stringify(argTypes, null, 2);
  }

  /**
   * Generate component description
   */
  generateDescription(extractedContent) {
    const parts = [];

    if (extractedContent.name) {
      parts.push(`${extractedContent.name} component from Figma design system.`);
    }

    if (extractedContent.dimensions) {
      parts.push(`Dimensions: ${extractedContent.dimensions.width}×${extractedContent.dimensions.height}px`);
    }

    if (extractedContent.variants) {
      const variantCount = Object.keys(extractedContent.variants).length;
      parts.push(`${variantCount} variant${variantCount > 1 ? 's' : ''} available.`);
    }

    return parts.join(' ');
  }

  /**
   * Extract default props from content
   */
  extractDefaultProps(extractedContent) {
    const props = {};

    // Add variant defaults
    if (extractedContent.variants) {
      for (const [key, value] of Object.entries(extractedContent.variants)) {
        props[this.toCamelCase(key)] = value;
      }
    }

    return props;
  }

  /**
   * Check if component accepts children
   */
  componentAcceptsChildren(extractedContent) {
    // If has nested components or text content, it accepts children
    return extractedContent.children && extractedContent.children.length > 0;
  }

  /**
   * Convert variant key/value to story name
   */
  variantToStoryName(key, value) {
    const keyPascal = this.toPascalCase(key);
    const valuePascal = this.toPascalCase(String(value));
    return `${keyPascal}${valuePascal}`;
  }

  /**
   * Convert string to PascalCase
   */
  toPascalCase(str) {
    return str
      .replace(/[^a-zA-Z0-9]+/g, ' ')
      .split(' ')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
      .join('');
  }

  /**
   * Convert string to camelCase
   */
  toCamelCase(str) {
    const pascal = this.toPascalCase(str);
    return pascal.charAt(0).toLowerCase() + pascal.slice(1);
  }

  /**
   * Write story to file
   */
  writeStory(componentName, storyCode) {
    const storyPath = path.join(this.storiesPath, `${componentName}.stories.tsx`);
    fs.writeFileSync(storyPath, storyCode);
    return storyPath;
  }

  /**
   * Generate and write story (convenience method)
   */
  generateAndWrite(componentName, extractedContent, options = {}) {
    const storyCode = this.generateStory(componentName, extractedContent, options);
    const storyPath = this.writeStory(componentName, storyCode);
    return {
      path: storyPath,
      code: storyCode
    };
  }
}

module.exports = StorybookGenerator;
