/**
 * Hook: on-registry-change
 * Triggers when componentRegistry.json is modified
 * Queues affected components for re-transformation
 */
const fs = require('fs').promises;
const path = require('path');

// In-memory cache for previous state
let previousRegistry = null;

module.exports = {
  name: 'on-registry-change',
  watch: '.design/componentRegistry.json',
  debounce: 500,
  enabled: true,
  priority: 10,

  async execute(event) {
    process.stderr.write('[on-registry-change] Registry change detected\n');

    try {
      // Read current registry
      const registryPath = event.path;
      let currentRegistry;

      try {
        const content = await fs.readFile(registryPath, 'utf8');
        currentRegistry = JSON.parse(content);
      } catch (readError) {
        // If file doesn't exist or is invalid, treat as empty
        if (readError.code === 'ENOENT') {
          process.stderr.write('[on-registry-change] Registry file not found, treating as empty\n');
          currentRegistry = { components: {} };
        } else {
          throw readError;
        }
      }

      // Determine what changed
      const changes = this.getChangedComponents(previousRegistry, currentRegistry);

      // Update cache for next comparison
      previousRegistry = JSON.parse(JSON.stringify(currentRegistry));

      // Log changes
      const hasChanges = changes.added.length > 0 ||
                         changes.modified.length > 0 ||
                         changes.removed.length > 0;

      if (changes.added.length > 0) {
        process.stderr.write(`[on-registry-change] Added: ${changes.added.join(', ')}\n`);
      }
      if (changes.modified.length > 0) {
        process.stderr.write(`[on-registry-change] Modified: ${changes.modified.join(', ')}\n`);
      }
      if (changes.removed.length > 0) {
        process.stderr.write(`[on-registry-change] Removed: ${changes.removed.join(', ')}\n`);
      }

      // Queue transformations for added and modified components
      const toTransform = [...changes.added, ...changes.modified];

      if (toTransform.length === 0) {
        return {
          success: true,
          message: hasChanges ? 'Only removals detected' : 'No transformable changes detected',
          changes
        };
      }

      // Build transformation queue
      const queue = toTransform.map(id => ({
        id,
        name: currentRegistry.components[id]?.name || id,
        framework: currentRegistry.components[id]?.framework || 'react',
        paths: currentRegistry.components[id]?.paths || {}
      }));

      process.stderr.write(`[on-registry-change] Queuing ${queue.length} components for transformation\n`);

      return {
        success: true,
        message: `Queued ${queue.length} components`,
        changes,
        queue
      };

    } catch (error) {
      process.stderr.write('[on-registry-change] Error: ' + error.message + '\n');
      return {
        success: false,
        message: error.message,
        error
      };
    }
  },

  /**
   * Compare previous and current registry to find changes
   * @param {Object} previous - Previous registry state
   * @param {Object} current - Current registry state
   * @returns {Object} Changes object with added, modified, removed arrays
   */
  getChangedComponents(previous, current) {
    const changes = {
      added: [],
      modified: [],
      removed: []
    };

    const prevIds = Object.keys(previous?.components || {});
    const currIds = Object.keys(current?.components || {});

    // Find added
    for (const id of currIds) {
      if (!prevIds.includes(id)) {
        changes.added.push(id);
      }
    }

    // Find removed
    for (const id of prevIds) {
      if (!currIds.includes(id)) {
        changes.removed.push(id);
      }
    }

    // Find modified
    for (const id of currIds) {
      if (prevIds.includes(id)) {
        const prevEntry = previous.components[id];
        const currEntry = current.components[id];

        // Compare extractedAt timestamps
        const prevTime = prevEntry?.source?.extractedAt;
        const currTime = currEntry?.source?.extractedAt;

        if (prevTime !== currTime) {
          changes.modified.push(id);
        } else {
          // Also check for other property changes
          const prevHash = JSON.stringify(prevEntry);
          const currHash = JSON.stringify(currEntry);
          if (prevHash !== currHash) {
            changes.modified.push(id);
          }
        }
      }
    }

    return changes;
  },

  /**
   * Reset the previous registry cache (useful for testing)
   */
  resetCache() {
    previousRegistry = null;
  }
};
