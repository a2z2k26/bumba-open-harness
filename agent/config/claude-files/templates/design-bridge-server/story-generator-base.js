/**
 * story-generator-base.js
 * Extracted from BUMBA CLI - Sprint 62: Storybook Integration
 *
 * Base story generation logic adapted from:
 * advanced-features-integrator.js (historical reference)
 *
 * Adapted for Design Bridge with:
 * - Path changes (.bumba-design → .design)
 * - Template-based story file generation
 * - Framework-specific adaptations
 */

const EventEmitter = require('events');

class StoryGeneratorBase extends EventEmitter {
  constructor(options = {}) {
    super();

    this.options = {
      enableStorybook: options.enableStorybook !== false,
      framework: options.framework || 'react',
      typescript: options.typescript !== false,
      ...options
    };

    // Story registry (from BUMBA)
    this.storybook = {
      stories: new Map(),
      controls: new Map(),
      docs: new Map(),
      addons: ['controls', 'actions', 'viewport', 'backgrounds']
    };

    this.stats = {
      storiesGenerated: 0
    };
  }

  /**
   * Generate Story Metadata
   * Extracted from BUMBA - Sprint 62
   *
   * @param {Object} component - Component data
   * @returns {Object} Story metadata
   */
  generateStory(component) {
    if (!this.options.enableStorybook) return null;

    const story = {
      title: `Components/${component.name}`,
      component: component.name,
      args: component.props || {},
      argTypes: this.generateArgTypes(component.props || {})
    };

    this.storybook.stories.set(component.name, story);
    this.stats.storiesGenerated++;

    this.emit('story:generated', story);

    return story;
  }

  /**
   * Generate ArgTypes for Storybook Controls
   * Extracted from BUMBA - Sprint 62
   * Enhanced Sprint 4.2: Add action detection for function props
   *
   * @param {Object} props - Component props
   * @returns {Object} ArgTypes configuration
   */
  generateArgTypes(props) {
    if (!props || Object.keys(props).length === 0) return {};

    const argTypes = {};

    Object.entries(props).forEach(([key, prop]) => {
      // Handle different prop type formats
      const propType = prop.type || prop.rawType || 'string';

      // Sprint 4.2: Detect function props for Storybook actions
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
        argTypes[key] = {
          action: actionName
        };
      } else if (propType === 'enum' || (prop.values && Array.isArray(prop.values))) {
        argTypes[key] = {
          control: 'select',
          options: prop.values || []
        };
      } else if (propType === 'boolean') {
        argTypes[key] = {
          control: 'boolean'
        };
      } else if (propType === 'number') {
        argTypes[key] = {
          control: 'number'
        };
      } else if (propType === 'string') {
        argTypes[key] = {
          control: 'text'
        };
      } else if (propType.includes('|')) {
        // Union type - treat as enum
        const values = propType.split('|').map(v => v.trim().replace(/['"]/g, ''));
        argTypes[key] = {
          control: 'select',
          options: values
        };
      } else {
        argTypes[key] = {
          control: 'text'
        };
      }

      // Add description if available
      if (prop.description) {
        argTypes[key].description = prop.description;
      }
    });

    return argTypes;
  }

  /**
   * Generate Default Args from Props
   * New function for Design Bridge
   *
   * @param {Object} props - Component props
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
      } else if (prop.type === 'string') {
        args[key] = '';
      } else if (prop.type === 'number') {
        args[key] = 0;
      }
    });

    return args;
  }

  /**
   * Get Story Registry
   * @returns {Map} Stories registry
   */
  getStories() {
    return this.storybook.stories;
  }

  /**
   * Get Stats
   * @returns {Object} Generation statistics
   */
  getStats() {
    return this.stats;
  }
}

module.exports = { StoryGeneratorBase };
