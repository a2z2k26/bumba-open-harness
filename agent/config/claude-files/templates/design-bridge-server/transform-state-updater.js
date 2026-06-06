/**
 * TransformStateUpdater - Orchestrates transformation state tracking
 *
 * This module coordinates state updates when components are transformed,
 * using existing infrastructure:
 * - ContentHasher for hash calculations
 * - StoryHashRegistry for file tracking
 * - registry-reader for component registry access
 *
 * @module transform-state-updater
 * @version 1.0.0
 * @phase Phase 3 - Transform State Tracking
 */

const fs = require('fs').promises;
const fsSync = require('fs');
const path = require('path');

// Use existing infrastructure - DO NOT reimplement
const { ContentHasher, hashFile, hasFileChanged } = require('./content-hasher');
const { StoryHashRegistry } = require('./story-hash-registry');
const { readComponentRegistry, writeComponentRegistry } = require('./registry-reader');

// ============================================================================
// TransformStateUpdater Class
// ============================================================================

class TransformStateUpdater {
  /**
   * Create a new TransformStateUpdater instance
   * @param {Object} options - Configuration options
   * @param {string} options.projectPath - Path to the project root
   * @param {boolean} [options.emitEvents=false] - Whether to emit events
   */
  constructor(options = {}) {
    if (!options.projectPath) {
      throw new Error('projectPath is required');
    }

    this.projectPath = options.projectPath;
    this.emitEvents = options.emitEvents || false;

    // USE existing modules - don't recreate functionality
    this.contentHasher = new ContentHasher();
    this.fileRegistry = new StoryHashRegistry(this.projectPath);
  }

  /**
   * Mark a component as transformed
   * Updates registry state and registers generated files for tracking
   *
   * @param {string} componentId - Component registry ID
   * @param {Object} transformInfo - Transformation details
   * @param {string} transformInfo.framework - Target framework (react, vue, etc.)
   * @param {string} [transformInfo.codePath] - Relative path to generated code
   * @param {string} [transformInfo.storyPath] - Relative path to generated story
   * @returns {Promise<Object>} Result with success status and updated component
   */
  async markTransformed(componentId, transformInfo) {
    const registry = await readComponentRegistry(this.projectPath);
    const component = registry.components[componentId];

    if (!component) {
      return {
        success: false,
        error: `Component "${componentId}" not found in registry`
      };
    }

    // Calculate hashes using EXISTING content-hasher
    let codeHash = null;
    if (transformInfo.codePath) {
      const fullCodePath = path.join(this.projectPath, transformInfo.codePath);
      if (fsSync.existsSync(fullCodePath)) {
        codeHash = await hashFile(fullCodePath);
      }
    }

    // Update transformation state
    component.transformation = {
      state: 'transformed',
      framework: transformInfo.framework,
      transformedAt: new Date().toISOString(),
      codePath: transformInfo.codePath || null,
      storyPath: transformInfo.storyPath || null,
      codeHash,
      version: (component.transformation?.version || 0) + 1
    };

    // Register code file in EXISTING file registry
    if (transformInfo.codePath) {
      const fullCodePath = path.join(this.projectPath, transformInfo.codePath);
      if (fsSync.existsSync(fullCodePath)) {
        const codeContent = await fs.readFile(fullCodePath, 'utf8');
        await this.fileRegistry.registerCodeFile(
          transformInfo.codePath,
          codeContent,
          { framework: transformInfo.framework, componentId }
        );
      }
    }

    // Story hash is tracked separately by story-generator via StoryHashRegistry
    // We just store the path reference here

    await writeComponentRegistry(this.projectPath, registry);

    console.log(`[TransformStateUpdater] Marked ${componentId} as transformed (${transformInfo.framework})`);

    return {
      success: true,
      componentId,
      transformation: component.transformation
    };
  }

  /**
   * Update paths for a component's generated files
   *
   * @param {string} componentId - Component registry ID
   * @param {Object} paths - New paths
   * @param {string} [paths.codePath] - New code path
   * @param {string} [paths.storyPath] - New story path
   * @returns {Promise<Object>} Result with success status
   */
  async updatePaths(componentId, paths) {
    const registry = await readComponentRegistry(this.projectPath);
    const component = registry.components[componentId];

    if (!component) {
      return {
        success: false,
        error: `Component "${componentId}" not found in registry`
      };
    }

    if (!component.transformation) {
      return {
        success: false,
        error: `Component "${componentId}" has not been transformed yet`
      };
    }

    // Update paths
    if (paths.codePath !== undefined) {
      component.transformation.codePath = paths.codePath;
    }
    if (paths.storyPath !== undefined) {
      component.transformation.storyPath = paths.storyPath;
    }

    await writeComponentRegistry(this.projectPath, registry);

    return {
      success: true,
      componentId,
      paths: {
        codePath: component.transformation.codePath,
        storyPath: component.transformation.storyPath
      }
    };
  }

  /**
   * Check if a component needs re-transformation
   * Uses existing hash infrastructure to detect changes
   *
   * @param {string} componentId - Component registry ID
   * @returns {Promise<Object>} Result indicating if retransform is needed
   */
  async needsRetransform(componentId) {
    const registry = await readComponentRegistry(this.projectPath);
    const component = registry.components[componentId];

    if (!component) {
      return { needs: false, reason: 'Component not found' };
    }

    if (component.transformation?.state !== 'transformed') {
      return { needs: false, reason: 'Not yet transformed' };
    }

    const { codePath, codeHash } = component.transformation;

    if (!codePath) {
      return { needs: false, reason: 'No code path recorded' };
    }

    const fullCodePath = path.join(this.projectPath, codePath);

    // Check if file exists
    if (!fsSync.existsSync(fullCodePath)) {
      return { needs: true, reason: 'Code file missing' };
    }

    // USE EXISTING hasFileChanged() method
    const isModified = await hasFileChanged(fullCodePath, codeHash);

    if (isModified) {
      return {
        needs: false,  // Don't overwrite user changes
        reason: 'User modified code',
        userModified: true
      };
    }

    // Check if source is newer than transform
    const { syncMetadata } = component;
    if (syncMetadata?.lastFigmaSync) {
      const lastSync = new Date(syncMetadata.lastFigmaSync);
      const lastTransform = new Date(component.transformation.transformedAt);

      if (lastSync > lastTransform) {
        return { needs: true, reason: 'Source updated since transform' };
      }
    }

    return { needs: false, reason: 'Up to date' };
  }

  /**
   * Get transformation state for a component
   *
   * @param {string} componentId - Component registry ID
   * @returns {Promise<Object|null>} Transformation state or null
   */
  async getTransformState(componentId) {
    const registry = await readComponentRegistry(this.projectPath);
    const component = registry.components[componentId];

    if (!component) {
      return null;
    }

    return component.transformation || null;
  }

  /**
   * List all transformed components
   *
   * @param {Object} [options={}] - Filter options
   * @param {string} [options.framework] - Filter by framework
   * @returns {Promise<Array>} Array of transformed component info
   */
  async listTransformed(options = {}) {
    const registry = await readComponentRegistry(this.projectPath);
    const transformed = [];

    for (const [id, component] of Object.entries(registry.components)) {
      if (component.transformation?.state === 'transformed') {
        if (options.framework && component.transformation.framework !== options.framework) {
          continue;
        }

        transformed.push({
          id,
          name: component.name,
          framework: component.transformation.framework,
          transformedAt: component.transformation.transformedAt,
          codePath: component.transformation.codePath,
          storyPath: component.transformation.storyPath
        });
      }
    }

    return transformed;
  }

  /**
   * List components that need re-transformation
   *
   * @returns {Promise<Array>} Array of components needing retransform
   */
  async listNeedsRetransform() {
    const registry = await readComponentRegistry(this.projectPath);
    const needsRetransform = [];

    for (const id of Object.keys(registry.components)) {
      const check = await this.needsRetransform(id);
      if (check.needs) {
        needsRetransform.push({
          id,
          reason: check.reason
        });
      }
    }

    return needsRetransform;
  }

  /**
   * Reset transformation state (mark as imported)
   *
   * @param {string} componentId - Component registry ID
   * @returns {Promise<Object>} Result with success status
   */
  async resetTransformState(componentId) {
    const registry = await readComponentRegistry(this.projectPath);
    const component = registry.components[componentId];

    if (!component) {
      return {
        success: false,
        error: `Component "${componentId}" not found in registry`
      };
    }

    // Reset to imported state
    component.transformation = {
      state: 'imported',
      framework: null,
      transformedAt: null,
      codePath: null,
      storyPath: null,
      codeHash: null,
      version: 0
    };

    await writeComponentRegistry(this.projectPath, registry);

    return {
      success: true,
      componentId
    };
  }

  /**
   * Get statistics about transformation states
   *
   * @returns {Promise<Object>} Statistics
   */
  async getStats() {
    const registry = await readComponentRegistry(this.projectPath);
    const stats = {
      total: 0,
      imported: 0,
      transformed: 0,
      byFramework: {}
    };

    for (const component of Object.values(registry.components)) {
      stats.total++;

      const state = component.transformation?.state || 'imported';
      if (state === 'imported') {
        stats.imported++;
      } else if (state === 'transformed') {
        stats.transformed++;
        const fw = component.transformation.framework || 'unknown';
        stats.byFramework[fw] = (stats.byFramework[fw] || 0) + 1;
      }
    }

    return stats;
  }
}

// ============================================================================
// Standalone Utility Functions
// ============================================================================

/**
 * Find component ID by name
 * @param {string} componentName - Component name to find
 * @param {string} projectPath - Project path
 * @returns {Promise<string|null>} Component ID or null
 */
async function findComponentIdByName(componentName, projectPath) {
  const registry = await readComponentRegistry(projectPath);

  for (const [id, component] of Object.entries(registry.components)) {
    if (component.name === componentName ||
        component.name.toLowerCase() === componentName.toLowerCase()) {
      return id;
    }
  }

  return null;
}

/**
 * Quick helper to mark a component as transformed
 * @param {string} projectPath - Project path
 * @param {string} componentId - Component ID
 * @param {Object} transformInfo - Transform info
 * @returns {Promise<Object>} Result
 */
async function markComponentTransformed(projectPath, componentId, transformInfo) {
  const updater = new TransformStateUpdater({ projectPath });
  return updater.markTransformed(componentId, transformInfo);
}

/**
 * Quick helper to check if retransform is needed
 * @param {string} projectPath - Project path
 * @param {string} componentId - Component ID
 * @returns {Promise<Object>} Check result
 */
async function checkNeedsRetransform(projectPath, componentId) {
  const updater = new TransformStateUpdater({ projectPath });
  return updater.needsRetransform(componentId);
}

// ============================================================================
// Exports
// ============================================================================

module.exports = {
  // Class
  TransformStateUpdater,

  // Utility functions
  findComponentIdByName,
  markComponentTransformed,
  checkNeedsRetransform
};
