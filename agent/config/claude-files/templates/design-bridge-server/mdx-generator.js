/**
 * mdx-generator.js
 * Sprint 5.3: MDX Documentation Integration
 *
 * Generates MDX documentation files with:
 * - Component API documentation
 * - Interactive examples
 * - Usage guidelines
 * - Props tables
 * - Design tokens reference
 */

const EventEmitter = require('events');

/**
 * MDX documentation sections
 */
const MDX_SECTIONS = {
  overview: true,
  installation: true,
  usage: true,
  props: true,
  examples: true,
  accessibility: true,
  designTokens: true,
  changelog: false
};

/**
 * MDX template blocks
 */
const MDX_TEMPLATES = {
  header: (component) => `import { Meta, Story, Canvas, ArgsTable, Description } from '@storybook/blocks';
import * as ${component.name}Stories from './${component.name}.stories';

<Meta of={${component.name}Stories} />

# ${component.name}

${component.description || `A reusable ${component.name} component.`}
`,

  canvas: (storyName) => `<Canvas of={${storyName}} />`,

  argsTable: (component) => `## Props

<ArgsTable of={${component.name}Stories} />`,

  codeBlock: (code, language = 'tsx') => `\`\`\`${language}
${code}
\`\`\``,

  callout: (type, content) => `<div className="sb-unstyled">
  <div className="callout callout-${type}">
    ${content}
  </div>
</div>`,

  table: (headers, rows) => {
    const headerRow = `| ${headers.join(' | ')} |`;
    const separator = `| ${headers.map(() => '---').join(' | ')} |`;
    const dataRows = rows.map(row => `| ${row.join(' | ')} |`).join('\n');
    return `${headerRow}\n${separator}\n${dataRows}`;
  }
};

class MDXGenerator extends EventEmitter {
  constructor(options = {}) {
    super();

    this.sections = { ...MDX_SECTIONS, ...options.sections };
    this.templates = { ...MDX_TEMPLATES, ...options.templates };
    this.framework = options.framework || 'react';

    this.stats = {
      docsGenerated: 0,
      sectionsGenerated: 0,
      examplesIncluded: 0
    };
  }

  /**
   * Generate complete MDX documentation for a component
   * @param {Object} component - Component data
   * @param {Object} options - Generation options
   * @returns {string} MDX content
   */
  generateMDX(component, options = {}) {
    const {
      stories = [],
      designTokens = null,
      accessibility = null,
      changelog = null
    } = options;

    const sections = [];

    // Header with imports
    sections.push(this.templates.header(component));

    // Overview section
    if (this.sections.overview) {
      sections.push(this.generateOverview(component));
    }

    // Installation section
    if (this.sections.installation) {
      sections.push(this.generateInstallation(component));
    }

    // Usage section with primary example
    if (this.sections.usage) {
      sections.push(this.generateUsage(component, stories));
    }

    // Props table
    if (this.sections.props) {
      sections.push(this.generatePropsSection(component));
    }

    // Examples section
    if (this.sections.examples && stories.length > 0) {
      sections.push(this.generateExamples(component, stories));
    }

    // Accessibility section
    if (this.sections.accessibility && accessibility) {
      sections.push(this.generateAccessibility(component, accessibility));
    }

    // Design tokens section
    if (this.sections.designTokens && designTokens) {
      sections.push(this.generateDesignTokens(component, designTokens));
    }

    // Changelog section
    if (this.sections.changelog && changelog) {
      sections.push(this.generateChangelog(changelog));
    }

    this.stats.docsGenerated++;
    this.emit('mdx:generated', { component: component.name });

    return sections.join('\n\n');
  }

  /**
   * Generate overview section
   */
  generateOverview(component) {
    this.stats.sectionsGenerated++;

    let overview = `## Overview

${component.description || `The ${component.name} component is a reusable UI element designed for consistent use across your application.`}
`;

    // Add features if available
    if (component.features && component.features.length > 0) {
      overview += `\n### Features\n\n`;
      component.features.forEach(feature => {
        overview += `- ${feature}\n`;
      });
    }

    return overview;
  }

  /**
   * Generate installation section
   */
  generateInstallation(component) {
    this.stats.sectionsGenerated++;

    return `## Installation

${this.templates.codeBlock(`import { ${component.name} } from '@design-system/components';`, 'tsx')}
`;
  }

  /**
   * Generate usage section
   */
  generateUsage(component, stories) {
    this.stats.sectionsGenerated++;

    const defaultStory = stories.find(s => s.name === 'Default') || stories[0];
    const props = component.props || {};

    let usage = `## Basic Usage

`;

    // Add canvas with default story
    if (defaultStory) {
      usage += `<Canvas of={${component.name}Stories.${defaultStory.name || 'Default'}} />\n\n`;
      this.stats.examplesIncluded++;
    }

    // Add code example
    const codeExample = this.generateCodeExample(component, props);
    usage += this.templates.codeBlock(codeExample, 'tsx');

    return usage;
  }

  /**
   * Generate props section
   */
  generatePropsSection(component) {
    this.stats.sectionsGenerated++;

    let propsSection = this.templates.argsTable(component);

    // Add detailed props documentation
    const props = component.props || {};
    if (Object.keys(props).length > 0) {
      propsSection += `\n\n### Props Details\n\n`;

      Object.entries(props).forEach(([name, config]) => {
        propsSection += `#### \`${name}\`\n\n`;
        propsSection += `- **Type:** \`${config.type || 'any'}\`\n`;
        propsSection += `- **Required:** ${config.required ? 'Yes' : 'No'}\n`;

        if (config.default !== undefined) {
          propsSection += `- **Default:** \`${JSON.stringify(config.default)}\`\n`;
        }

        if (config.description) {
          propsSection += `\n${config.description}\n`;
        }

        if (config.options || config.enum) {
          const options = config.options || config.enum;
          propsSection += `\n**Possible values:** ${options.map(o => `\`${o}\``).join(', ')}\n`;
        }

        propsSection += '\n';
      });
    }

    return propsSection;
  }

  /**
   * Generate examples section
   */
  generateExamples(component, stories) {
    this.stats.sectionsGenerated++;

    let examples = `## Examples\n\n`;

    stories.forEach(story => {
      if (story.name === 'Default') return; // Skip default, already shown

      examples += `### ${this.formatStoryName(story.name)}\n\n`;

      if (story.description) {
        examples += `${story.description}\n\n`;
      }

      examples += `<Canvas of={${component.name}Stories.${story.name}} />\n\n`;
      this.stats.examplesIncluded++;
    });

    return examples;
  }

  /**
   * Generate accessibility section
   */
  generateAccessibility(component, accessibility) {
    this.stats.sectionsGenerated++;

    let a11y = `## Accessibility

`;

    if (accessibility.overview) {
      a11y += `${accessibility.overview}\n\n`;
    }

    // Keyboard interactions
    if (accessibility.keyboard && accessibility.keyboard.length > 0) {
      a11y += `### Keyboard Interactions\n\n`;
      a11y += this.templates.table(
        ['Key', 'Action'],
        accessibility.keyboard.map(k => [k.key, k.action])
      );
      a11y += '\n\n';
    }

    // ARIA attributes
    if (accessibility.aria && Object.keys(accessibility.aria).length > 0) {
      a11y += `### ARIA Attributes\n\n`;
      Object.entries(accessibility.aria).forEach(([attr, description]) => {
        a11y += `- \`${attr}\`: ${description}\n`;
      });
      a11y += '\n';
    }

    // Best practices
    if (accessibility.bestPractices && accessibility.bestPractices.length > 0) {
      a11y += `### Best Practices\n\n`;
      accessibility.bestPractices.forEach(practice => {
        a11y += `- ${practice}\n`;
      });
    }

    return a11y;
  }

  /**
   * Generate design tokens section
   */
  generateDesignTokens(component, designTokens) {
    this.stats.sectionsGenerated++;

    let tokens = `## Design Tokens

This component uses the following design tokens from your design system:

`;

    // Colors
    if (designTokens.colors && Object.keys(designTokens.colors).length > 0) {
      tokens += `### Colors\n\n`;
      tokens += this.templates.table(
        ['Token', 'Value', 'Usage'],
        Object.entries(designTokens.colors).map(([name, config]) =>
          [name, config.value || '-', config.usage || '-']
        )
      );
      tokens += '\n\n';
    }

    // Spacing
    if (designTokens.spacing && Object.keys(designTokens.spacing).length > 0) {
      tokens += `### Spacing\n\n`;
      tokens += this.templates.table(
        ['Token', 'Value'],
        Object.entries(designTokens.spacing).map(([name, value]) => [name, value])
      );
      tokens += '\n\n';
    }

    // Typography
    if (designTokens.typography && Object.keys(designTokens.typography).length > 0) {
      tokens += `### Typography\n\n`;
      Object.entries(designTokens.typography).forEach(([name, config]) => {
        tokens += `- **${name}:** ${config.fontFamily}, ${config.fontSize}, ${config.fontWeight}\n`;
      });
    }

    return tokens;
  }

  /**
   * Generate changelog section
   */
  generateChangelog(changelog) {
    this.stats.sectionsGenerated++;

    let log = `## Changelog\n\n`;

    changelog.forEach(entry => {
      log += `### ${entry.version} (${entry.date})\n\n`;

      if (entry.added && entry.added.length > 0) {
        log += `**Added:**\n`;
        entry.added.forEach(item => {
          log += `- ${item}\n`;
        });
        log += '\n';
      }

      if (entry.changed && entry.changed.length > 0) {
        log += `**Changed:**\n`;
        entry.changed.forEach(item => {
          log += `- ${item}\n`;
        });
        log += '\n';
      }

      if (entry.fixed && entry.fixed.length > 0) {
        log += `**Fixed:**\n`;
        entry.fixed.forEach(item => {
          log += `- ${item}\n`;
        });
        log += '\n';
      }
    });

    return log;
  }

  /**
   * Generate code example
   */
  generateCodeExample(component, props) {
    const propsEntries = Object.entries(props);
    const requiredProps = propsEntries.filter(([_, config]) => config.required);

    let propsStr = '';
    if (requiredProps.length > 0) {
      propsStr = requiredProps
        .map(([name, config]) => {
          const value = config.default !== undefined
            ? config.default
            : this.getExampleValue(config.type);
          return `  ${name}={${JSON.stringify(value)}}`;
        })
        .join('\n');
    }

    return `import { ${component.name} } from '@design-system/components';

function Example() {
  return (
    <${component.name}${propsStr ? '\n' + propsStr + '\n    ' : ' '}/>
  );
}`;
  }

  /**
   * Get example value for prop type
   */
  getExampleValue(type) {
    const examples = {
      'string': 'Example text',
      'number': 42,
      'boolean': true,
      'array': [],
      'object': {}
    };
    return examples[type?.toLowerCase()] ?? 'value';
  }

  /**
   * Format story name for display
   */
  formatStoryName(name) {
    return name
      .replace(/([A-Z])/g, ' $1')
      .replace(/^./, str => str.toUpperCase())
      .trim();
  }

  /**
   * Generate MDX file for component docs page
   * @param {Object} component - Component data
   * @param {string} framework - Target framework
   * @returns {Object} MDX file content and metadata
   */
  generateDocsPage(component, framework = 'react') {
    const mdxContent = this.generateMDX(component, { stories: [] });

    return {
      filename: `${component.name}.mdx`,
      content: mdxContent,
      framework,
      component: component.name,
      generatedAt: new Date().toISOString()
    };
  }

  /**
   * Enable/disable sections
   */
  setSections(sections) {
    this.sections = { ...this.sections, ...sections };
    return this;
  }

  /**
   * Get enabled sections
   */
  getSections() {
    return { ...this.sections };
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
      docsGenerated: 0,
      sectionsGenerated: 0,
      examplesIncluded: 0
    };
  }
}

// Export singleton and class
const mdxGenerator = new MDXGenerator();

module.exports = {
  MDXGenerator,
  mdxGenerator,
  MDX_SECTIONS,
  MDX_TEMPLATES
};
