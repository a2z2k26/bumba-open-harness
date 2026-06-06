/**
 * Hook: on-cascade-complete
 * Triggered after a cascade sync completes for a component
 *
 * @version 1.0.0
 * @phase Phase 5 - Two-State Architecture Integration
 *
 * USES existing infrastructure:
 * - SyncCascade events from Phase 4
 * - Registry reader for component data
 *
 * This hook is event-driven (not file-watch based) and subscribes to
 * cascade:completed events from SyncCascade.
 */
const EventEmitter = require('events');
const path = require('path');
const net = require('net');

module.exports = {
  name: 'on-cascade-complete',
  version: '1.0.0',
  description: 'Handles cascade sync completion events (Phase 5)',
  watch: null, // Event-driven, not file-watch
  debounce: 0,
  enabled: true,
  priority: 300, // After transform hooks

  // Internal event emitter for notifications
  _emitter: new EventEmitter(),

  /**
   * Subscribe to events from this hook
   * @param {string} event - Event name
   * @param {Function} listener - Event listener
   */
  on(event, listener) {
    this._emitter.on(event, listener);
  },

  /**
   * Emit events from this hook
   * @param {string} event - Event name
   * @param {Object} data - Event data
   */
  emit(event, data) {
    this._emitter.emit(event, data);
  },

  /**
   * Execute the hook after a cascade sync completes
   * @param {Object} event - Cascade completion event data
   * @param {string} event.componentId - ID of the synced component
   * @param {Object} event.results - Cascade results
   * @param {string} event.projectPath - Project root path
   * @returns {Object} Hook result with success status
   */
  async execute(event) {
    const { componentId, results, projectPath } = event;

    if (!componentId) {
      return {
        success: false,
        message: 'Missing componentId in cascade event',
        action: 'error'
      };
    }

    process.stderr.write(`[on-cascade-complete] Cascade complete for: ${componentId}\n`);

    try {
      // Get component name from results or registry
      const componentName = results?.componentName || componentId;

      // Log what was updated
      this.logCascadeResults(componentId, results);

      // Check if Storybook is running for hot-reload notification
      const storybookRunning = await this.isStorybookRunning();
      if (storybookRunning) {
        process.stderr.write('[on-cascade-complete] Storybook detected - HMR will auto-reload\n');
      }

      // Emit notification event for UI clients
      this.emit('cascade:notification', {
        componentId,
        componentName,
        message: `Component "${componentName}" synced from Figma`,
        timestamp: new Date().toISOString(),
        results: {
          codeRegenerated: results?.steps?.code?.success || false,
          storyRegenerated: results?.steps?.story?.success || false,
          registryUpdated: results?.steps?.registry?.success || false
        }
      });

      // Track cascade completion for statistics
      await this.trackCascadeCompletion(componentId, results, projectPath);

      return {
        success: true,
        message: `Cascade complete: ${componentName}`,
        action: 'completed',
        componentId,
        componentName,
        storybookNotified: storybookRunning
      };

    } catch (error) {
      process.stderr.write(`[on-cascade-complete] Error: ${error.message}\n`);
      return {
        success: false,
        message: error.message,
        action: 'error',
        error
      };
    }
  },

  /**
   * Log cascade results to console
   * @param {string} componentId - Component ID
   * @param {Object} results - Cascade results
   */
  logCascadeResults(componentId, results) {
    if (!results || !results.steps) {
      process.stderr.write(`[on-cascade-complete] No detailed results for ${componentId}\n`);
      return;
    }

    const steps = results.steps;

    if (steps.registry?.success) {
      process.stderr.write(`  [registry] Updated\n`);
    }

    if (steps.code?.success) {
      const codePath = steps.code.codePath || 'unknown';
      process.stderr.write(`  [code] Regenerated: ${codePath}\n`);
    } else if (steps.code?.skipped) {
      process.stderr.write(`  [code] Skipped: ${steps.code.reason || 'user modifications preserved'}\n`);
    }

    if (steps.story?.success) {
      const storyPath = steps.story.storyPath || 'unknown';
      process.stderr.write(`  [story] Regenerated: ${storyPath}\n`);
    } else if (steps.story?.skipped) {
      process.stderr.write(`  [story] Skipped: ${steps.story.reason || 'user modifications preserved'}\n`);
    }

    // Log timing if available
    if (results.duration) {
      process.stderr.write(`  [timing] ${results.duration}ms\n`);
    }
  },

  /**
   * Check if Storybook is running on default port
   * Uses HMR - files changing will trigger auto-reload
   * @returns {Promise<boolean>} True if Storybook is running
   */
  async isStorybookRunning() {
    return new Promise((resolve) => {
      const client = new net.Socket();
      client.setTimeout(200);

      client.connect(6006, '127.0.0.1', () => {
        client.destroy();
        resolve(true);
      });

      client.on('error', () => {
        client.destroy();
        resolve(false);
      });

      client.on('timeout', () => {
        client.destroy();
        resolve(false);
      });
    });
  },

  /**
   * Track cascade completion for statistics
   * Writes to .design/cascadeStats.json
   * @param {string} componentId - Component ID
   * @param {Object} results - Cascade results
   * @param {string} projectPath - Project root path
   */
  async trackCascadeCompletion(componentId, results, projectPath) {
    try {
      const fs = require('fs').promises;
      const statsPath = path.join(projectPath, '.design', 'cascadeStats.json');

      // Load or create stats
      let stats = {
        version: '1.0.0',
        totalCascades: 0,
        successfulCascades: 0,
        failedCascades: 0,
        lastCascade: null,
        componentStats: {}
      };

      try {
        const existing = await fs.readFile(statsPath, 'utf8');
        stats = JSON.parse(existing);
      } catch {
        // Create new stats file
      }

      // Update stats
      stats.totalCascades++;

      if (results?.success !== false) {
        stats.successfulCascades++;
      } else {
        stats.failedCascades++;
      }

      stats.lastCascade = {
        componentId,
        timestamp: new Date().toISOString(),
        success: results?.success !== false,
        duration: results?.duration || null
      };

      // Track per-component stats
      if (!stats.componentStats[componentId]) {
        stats.componentStats[componentId] = {
          cascadeCount: 0,
          lastCascade: null
        };
      }
      stats.componentStats[componentId].cascadeCount++;
      stats.componentStats[componentId].lastCascade = new Date().toISOString();

      // Save stats
      await fs.mkdir(path.dirname(statsPath), { recursive: true });
      await fs.writeFile(statsPath, JSON.stringify(stats, null, 2), 'utf8');

    } catch (error) {
      // Don't fail hook if stats tracking fails
      process.stderr.write(`[on-cascade-complete] Stats tracking failed: ${error.message}\n`);
    }
  }
};
