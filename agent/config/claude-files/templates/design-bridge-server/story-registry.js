/**
 * story-registry.js
 * Tracks generated stories and their metadata
 */

const fs = require('fs');
const path = require('path');

/**
 * Update story registry with generated stories
 *
 * @param {string} projectPath - Project root path
 * @param {Array} stories - Array of story data
 * @returns {Object} Updated registry
 */
function updateStoryRegistry(projectPath, stories) {
  const registryPath = path.join(projectPath, '.design/storybook/story-index.json');
  const registryDir = path.dirname(registryPath);

  // Ensure directory exists
  if (!fs.existsSync(registryDir)) {
    fs.mkdirSync(registryDir, { recursive: true });
  }

  // Load existing registry or create new
  let registry = {
    version: '1.0.0',
    stories: {},
    lastUpdated: null,
    statistics: {
      total: 0,
      byFramework: {}
    }
  };

  if (fs.existsSync(registryPath)) {
    try {
      registry = JSON.parse(fs.readFileSync(registryPath, 'utf8'));
    } catch (error) {
      console.warn('Failed to load existing registry, creating new one');
    }
  }

  // Update with new stories
  stories.forEach(story => {
    registry.stories[story.component] = {
      storyPath: story.path,
      generatedAt: story.generatedAt || new Date().toISOString(),
      framework: story.framework,
      variants: story.variants || ['Default'],
      componentPath: story.componentPath || '',
      hasProps: story.hasProps || false,
      propsCount: story.propsCount || 0
    };

    // Update statistics
    if (!registry.statistics.byFramework[story.framework]) {
      registry.statistics.byFramework[story.framework] = 0;
    }
    registry.statistics.byFramework[story.framework]++;
  });

  // Update metadata
  registry.lastUpdated = new Date().toISOString();
  registry.statistics.total = Object.keys(registry.stories).length;

  // Write registry
  fs.writeFileSync(registryPath, JSON.stringify(registry, null, 2), 'utf8');

  return registry;
}

/**
 * Get story registry
 *
 * @param {string} projectPath - Project root path
 * @returns {Object|null} Registry or null if doesn't exist
 */
function getStoryRegistry(projectPath) {
  const registryPath = path.join(projectPath, '.design/storybook/story-index.json');

  if (!fs.existsSync(registryPath)) {
    return null;
  }

  try {
    return JSON.parse(fs.readFileSync(registryPath, 'utf8'));
  } catch (error) {
    console.error('Failed to read story registry:', error.message);
    return null;
  }
}

/**
 * Check if story exists in registry
 *
 * @param {string} projectPath - Project root path
 * @param {string} componentName - Component name
 * @returns {boolean} Whether story exists
 */
function storyExists(projectPath, componentName) {
  const registry = getStoryRegistry(projectPath);
  return registry && registry.stories[componentName];
}

module.exports = {
  updateStoryRegistry,
  getStoryRegistry,
  storyExists
};
