/**
 * Hook: on-token-change
 * Triggers when tokens/index.json is modified
 * Finds and queues dependent components for re-transformation
 */
const fs = require('fs').promises;
const path = require('path');

let previousTokens = null;

module.exports = {
  name: 'on-token-change',
  watch: '.design/tokens/index.json',
  debounce: 1000, // Longer debounce for token changes (they often come in batches)
  enabled: true,
  priority: 5, // Higher priority than component registry (runs first)

  async execute(event) {
    process.stderr.write('[on-token-change] Token change detected\n');

    try {
      // Read current tokens
      const tokensPath = event.path;
      let currentTokens;

      try {
        const content = await fs.readFile(tokensPath, 'utf8');
        currentTokens = JSON.parse(content);
      } catch (readError) {
        if (readError.code === 'ENOENT') {
          process.stderr.write('[on-token-change] Token file not found, treating as empty\n');
          currentTokens = { categories: {} };
        } else {
          throw readError;
        }
      }

      // Categorize changes
      const changes = this.categorizeTokenChanges(previousTokens, currentTokens);

      // Update cache
      previousTokens = JSON.parse(JSON.stringify(currentTokens));

      // Log changes by category
      let totalChanges = 0;
      for (const [category, categoryChanges] of Object.entries(changes)) {
        const count = categoryChanges.added.length +
                      categoryChanges.modified.length +
                      categoryChanges.removed.length;
        if (count > 0) {
          process.stderr.write(`[on-token-change] ${category}: +${categoryChanges.added.length} ~${categoryChanges.modified.length} -${categoryChanges.removed.length}\n`);
          totalChanges += count;
        }
      }

      if (totalChanges === 0) {
        return {
          success: true,
          message: 'No token changes detected',
          changes
        };
      }

      // Find dependent components
      const projectRoot = path.dirname(path.dirname(tokensPath));
      const registryPath = path.join(projectRoot, 'componentRegistry.json');

      let dependentComponents = [];
      try {
        dependentComponents = await this.findDependentComponents(changes, registryPath);
      } catch (error) {
        process.stderr.write('[on-token-change] Could not check component dependencies: ' + error.message + '\n');
      }

      if (dependentComponents.length > 0) {
        process.stderr.write(`[on-token-change] ${dependentComponents.length} components depend on changed tokens\n`);
        process.stderr.write(`[on-token-change] Affected: ${dependentComponents.join(', ')}\n`);
      }

      return {
        success: true,
        message: `Token changes detected, ${dependentComponents.length} components affected`,
        changes,
        dependentComponents,
        totalChanges
      };

    } catch (error) {
      process.stderr.write('[on-token-change] Error: ' + error.message + '\n');
      return {
        success: false,
        message: error.message,
        error
      };
    }
  },

  /**
   * Categorize token changes by category
   * @param {Object} previous - Previous tokens state
   * @param {Object} current - Current tokens state
   * @returns {Object} Changes by category
   */
  categorizeTokenChanges(previous, current) {
    const categories = ['colors', 'typography', 'spacing', 'effects', 'borderRadius', 'shadows'];
    const changes = {};

    for (const category of categories) {
      const prevTokens = previous?.categories?.[category]?.tokens || [];
      const currTokens = current?.categories?.[category]?.tokens || [];

      const prevMap = new Map(prevTokens.map(t => [t.name, t]));
      const currMap = new Map(currTokens.map(t => [t.name, t]));

      changes[category] = {
        added: [],
        modified: [],
        removed: []
      };

      // Find added and modified
      for (const [name, token] of currMap) {
        if (!prevMap.has(name)) {
          changes[category].added.push(name);
        } else {
          const prevToken = prevMap.get(name);
          if (JSON.stringify(prevToken) !== JSON.stringify(token)) {
            changes[category].modified.push(name);
          }
        }
      }

      // Find removed
      for (const [name] of prevMap) {
        if (!currMap.has(name)) {
          changes[category].removed.push(name);
        }
      }
    }

    return changes;
  },

  /**
   * Find components that depend on changed tokens
   * @param {Object} changedTokens - Token changes by category
   * @param {string} registryPath - Path to component registry
   * @returns {Promise<string[]>} Array of dependent component IDs
   */
  async findDependentComponents(changedTokens, registryPath) {
    let content;
    try {
      content = await fs.readFile(registryPath, 'utf8');
    } catch (error) {
      // Registry doesn't exist yet
      return [];
    }

    const registry = JSON.parse(content);
    const dependentComponents = new Set();

    for (const [id, entry] of Object.entries(registry.components || {})) {
      const deps = entry.tokenDependencies || {};

      for (const [category, categoryChanges] of Object.entries(changedTokens)) {
        const componentTokens = deps[category] || [];
        const allChanged = [
          ...categoryChanges.added,
          ...categoryChanges.modified,
          ...categoryChanges.removed
        ];

        for (const tokenName of allChanged) {
          if (componentTokens.includes(tokenName)) {
            dependentComponents.add(id);
            break;
          }
        }
      }
    }

    return Array.from(dependentComponents);
  },

  /**
   * Reset the previous tokens cache (useful for testing)
   */
  resetCache() {
    previousTokens = null;
  }
};
