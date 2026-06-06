/**
 * SyncCascade - Cascade Sync Orchestrator
 *
 * Orchestrates cascade sync logic so design changes automatically propagate
 * to transformed code and stories.
 *
 * DESIGN PRINCIPLE: This module ORCHESTRATES existing systems, it does NOT replace them.
 * All operations delegate to existing infrastructure via dependency injection.
 *
 * Existing Systems Used:
 * - ContentHasher: File content hashing for modification detection
 * - StoryHashRegistry: Story file modification tracking
 * - ConflictResolver: Conflict detection and resolution
 * - DiffEngine: Object diffing and patching
 * - SnapshotManager: Snapshot creation and rollback
 * - TransformStateUpdater: Component state transitions
 *
 * v4.0.0 Integration:
 * - Added RegistryManager support for unified registry operations
 * - Dependency graph traversal for cascade impact analysis
 * - O(1) component lookups via canonical IDs
 * - Backward compatible with legacy componentRegistry.json
 *
 * @module sync-cascade
 * @version 2.0.0
 */

const EventEmitter = require('events');
const path = require('path');
const fs = require('fs');

// IMPORT existing modules - DO NOT RECREATE
const { ContentHasher, hashFile, hasFileChanged } = require('./content-hasher');
const { StoryHashRegistry } = require('./story-hash-registry');
const { ConflictResolver } = require('./conflict-resolver');
const { DiffEngine, SnapshotManager } = require('./incremental-processor');
const { TransformStateUpdater } = require('./transform-state-updater');
const { readComponentRegistry, writeComponentRegistry } = require('./registry-reader');

// Lazy-load RegistryManager to avoid circular dependencies (v4.0.0)
let _registryManagerModule = null;
function getRegistryManagerModule() {
  if (!_registryManagerModule) {
    try {
      _registryManagerModule = require('./registry-manager');
    } catch (e) {
      // Registry manager not available
      _registryManagerModule = null;
    }
  }
  return _registryManagerModule;
}

/**
 * SyncCascade events
 * @constant {Object}
 */
const CASCADE_EVENTS = {
  STARTED: 'cascade:started',
  COMPLETED: 'cascade:completed',
  FAILED: 'cascade:failed',
  STEP: 'cascade:step',
  WARNING: 'cascade:warning',
  ROLLBACK: 'cascade:rollback'
};

/**
 * Default cascade configuration
 * @constant {Object}
 */
const CASCADE_DEFAULTS = {
  enabled: true,
  regenerateCode: true,
  regenerateStory: true,
  preserveUserModifications: true,
  maxCascadesPerSync: 10,
  cascadeTimeout: 30000
};

/**
 * SyncCascade - Orchestrates cascade sync operations
 *
 * @extends EventEmitter
 */
class SyncCascade extends EventEmitter {
  /**
   * Create a SyncCascade instance
   *
   * @param {Object} options - Configuration options
   * @param {string} options.projectPath - Project root path
   * @param {ContentHasher} [options.contentHasher] - Injected hasher (creates new if not provided)
   * @param {StoryHashRegistry} [options.storyHashRegistry] - Injected story registry
   * @param {ConflictResolver} [options.conflictResolver] - Injected conflict resolver
   * @param {DiffEngine} [options.diffEngine] - Injected diff engine
   * @param {SnapshotManager} [options.snapshotManager] - Injected snapshot manager
   * @param {Object} [options.optimizerRegistry] - Framework optimizer registry
   * @param {Object} [options.config] - Cascade configuration overrides
   */
  constructor(options = {}) {
    super();
    this.projectPath = options.projectPath || process.cwd();

    // INJECT existing systems - prefer passed instances, fallback to new instances
    this.contentHasher = options.contentHasher || new ContentHasher();
    // StoryHashRegistry constructor takes projectPath directly (string), not options object
    this.storyHashRegistry = options.storyHashRegistry || new StoryHashRegistry(this.projectPath);
    this.conflictResolver = options.conflictResolver || new ConflictResolver();
    this.diffEngine = options.diffEngine || new DiffEngine();

    // IMPORTANT: SnapshotManager is separate from DiffEngine
    // SnapshotManager constructor takes options object with projectPath
    this.snapshotManager = options.snapshotManager || new SnapshotManager({ projectPath: this.projectPath });

    // State updater for registry transitions
    this.stateUpdater = new TransformStateUpdater({ projectPath: this.projectPath });

    // Optimizer registry for code regeneration (framework -> optimizer mapping)
    this.optimizerRegistry = options.optimizerRegistry || {};

    // Merge configuration with defaults
    this.config = { ...CASCADE_DEFAULTS, ...options.config };

    // v4.0.0 Registry Integration
    this._registryManager = null;
    this._v4Available = null;
    this.designPath = path.join(this.projectPath, '.design');
  }

  // ==========================================================================
  // v4.0.0 Registry Integration Methods
  // ==========================================================================

  /**
   * Check if v4.0.0 registry is available
   * @returns {boolean} True if registry-index.json exists
   */
  hasV4Registry() {
    if (this._v4Available === null) {
      const indexPath = path.join(this.designPath, 'registry-index.json');
      this._v4Available = fs.existsSync(indexPath);
    }
    return this._v4Available;
  }

  /**
   * Get RegistryManager instance (lazy-loaded)
   * @returns {Promise<RegistryManager|null>} RegistryManager or null if unavailable
   */
  async getRegistryManager() {
    if (!this._registryManager && this.hasV4Registry()) {
      const module = getRegistryManagerModule();
      if (module) {
        const { getRegistryManager } = module;
        this._registryManager = await getRegistryManager(this.designPath);
      }
    }
    return this._registryManager;
  }

  /**
   * Get component by ID using v4.0.0 registry with O(1) lookup
   * Falls back to legacy registry if v4 unavailable
   * @param {string} componentId - Component ID (canonical or legacy)
   * @returns {Promise<Object|null>} Component entry or null
   */
  async getComponentV4(componentId) {
    const rm = await this.getRegistryManager();
    if (rm) {
      return rm.getById(componentId) || null;
    }
    // Fallback to legacy
    const registry = await readComponentRegistry(this.projectPath);
    return registry?.components?.[componentId] || null;
  }

  /**
   * Get all dependents of a component (for cascade impact analysis)
   * @param {string} componentId - Component ID
   * @returns {Promise<string[]>} Array of dependent component IDs
   */
  async getDependents(componentId) {
    const rm = await this.getRegistryManager();
    if (rm) {
      return rm.getDependents?.(componentId) || [];
    }
    return [];
  }

  /**
   * Get cascade impact analysis for a component
   * Shows what will be affected if this component changes
   * @param {string} componentId - Component ID
   * @returns {Promise<Object>} Impact analysis
   */
  async getCascadeImpact(componentId) {
    const rm = await this.getRegistryManager();
    if (!rm) {
      return { available: false, dependents: [], depth: 0 };
    }

    const visited = new Set();
    const queue = [{ id: componentId, depth: 0 }];
    const impacts = [];

    while (queue.length > 0) {
      const { id, depth } = queue.shift();
      if (visited.has(id)) continue;
      visited.add(id);

      const dependents = rm.getDependents?.(id) || [];
      for (const depId of dependents) {
        if (!visited.has(depId)) {
          impacts.push({ id: depId, depth: depth + 1 });
          queue.push({ id: depId, depth: depth + 1 });
        }
      }
    }

    return {
      available: true,
      root: componentId,
      dependents: impacts,
      totalAffected: impacts.length,
      maxDepth: Math.max(0, ...impacts.map(i => i.depth))
    };
  }

  /**
   * Invalidate v4.0.0 cache
   */
  invalidateV4Cache() {
    this._registryManager = null;
    this._v4Available = null;
  }

  // ==========================================================================
  // Main Cascade Entry Point
  // ==========================================================================

  /**
   * Execute cascade sync for a component
   *
   * This is the main orchestrator method that:
   * 1. Updates the registry with new data
   * 2. Checks if code regeneration is needed
   * 3. Regenerates code if source changed and code wasn't manually modified
   * 4. Checks if story regeneration is needed
   * 5. Regenerates story if needed
   * 6. Rolls back on failure
   *
   * @param {string} componentId - Component ID from registry
   * @param {Object} updatedData - Updated component data from design source
   * @returns {Promise<Object>} Cascade result with steps and status
   */
  async cascade(componentId, updatedData) {
    const results = {
      componentId,
      startedAt: new Date().toISOString(),
      steps: {},
      success: true,
      errors: []
    };

    this.emit(CASCADE_EVENTS.STARTED, { componentId });

    let snapshotId = null;

    try {
      // Step 1: Update registry (creates snapshot via SnapshotManager for rollback)
      const registryResult = await this.updateRegistry(componentId, updatedData);
      results.steps.registry = registryResult;
      snapshotId = registryResult.snapshotId;

      // Step 2: Check if code should be regenerated
      if (this.config.regenerateCode !== false) {
        const codeCheck = await this.shouldRegenerateCode(componentId);
        results.steps.codeCheck = codeCheck;

        if (codeCheck.should) {
          results.steps.code = await this.regenerateCode(componentId);
        } else if (codeCheck.userModified) {
          this.emit(CASCADE_EVENTS.WARNING, {
            componentId,
            type: 'code_preserved',
            message: 'Code modified by user - preserved'
          });
        }
      }

      // Step 3: Check if story should be regenerated
      if (this.config.regenerateStory !== false) {
        const storyCheck = await this.shouldRegenerateStory(componentId);
        results.steps.storyCheck = storyCheck;

        if (storyCheck.should) {
          results.steps.story = await this.regenerateStory(componentId);
        } else if (storyCheck.userModified) {
          this.emit(CASCADE_EVENTS.WARNING, {
            componentId,
            type: 'story_preserved',
            message: 'Story modified by user - preserved'
          });
        }
      }

      results.completedAt = new Date().toISOString();
      this.emit(CASCADE_EVENTS.COMPLETED, results);

    } catch (error) {
      results.success = false;
      results.errors.push(error.message);
      results.failedAt = new Date().toISOString();

      this.emit(CASCADE_EVENTS.FAILED, { componentId, error: error.message });

      // Rollback using SnapshotManager (NOT DiffEngine)
      if (snapshotId) {
        try {
          await this.rollback(componentId, snapshotId);
          results.rollback = { success: true };
        } catch (rollbackError) {
          results.rollback = { success: false, error: rollbackError.message };
        }
      }
    }

    return results;
  }

  // ==========================================================================
  // Registry Operations (Sprint 4.3)
  // ==========================================================================

  /**
   * Update component in registry with new data
   *
   * Uses:
   * - SnapshotManager.create() for rollback snapshot
   * - DiffEngine.diff() to compute changes
   *
   * @param {string} componentId - Component ID
   * @param {Object} updatedData - New component data
   * @returns {Promise<Object>} Update result with snapshotId and changes
   */
  async updateRegistry(componentId, updatedData) {
    this.emit(CASCADE_EVENTS.STEP, { step: 'registry', componentId, status: 'starting' });

    // Read current registry
    const registry = await readComponentRegistry(this.projectPath);
    const component = registry.components?.[componentId];

    if (!component) {
      throw new Error(
        `Component "${componentId}" not found in registry. ` +
        `Run "design-bridge status" to see registered components, or ` +
        `run "design-bridge extract" to import the component.`
      );
    }

    // USE EXISTING SnapshotManager to create snapshot for rollback
    // NOTE: create() is synchronous and returns ID
    const snapshotId = this.snapshotManager.create(component, { componentId });

    // USE EXISTING DiffEngine to compute what changed
    const changes = this.diffEngine.diff(component, updatedData);

    // Apply updates to component - only update fields that were provided
    if (updatedData.props !== undefined) {
      component.props = updatedData.props;
    }
    if (updatedData.variants !== undefined) {
      component.variants = updatedData.variants;
    }
    if (updatedData.tokenDependencies !== undefined) {
      component.tokenDependencies = updatedData.tokenDependencies;
    }
    if (updatedData.styles !== undefined) {
      component.styles = updatedData.styles;
    }
    if (updatedData.interactiveStates !== undefined) {
      component.interactiveStates = updatedData.interactiveStates;
    }

    // Update sync metadata to track this sync
    component.syncMetadata = component.syncMetadata || {};
    component.syncMetadata.lastFigmaSync = new Date().toISOString();
    component.syncMetadata.figmaModifiedAt = updatedData.figmaModifiedAt || null;
    component.syncMetadata.syncCount = (component.syncMetadata.syncCount || 0) + 1;

    // Write updated registry
    await writeComponentRegistry(this.projectPath, registry);

    this.emit(CASCADE_EVENTS.STEP, { step: 'registry', componentId, status: 'completed', changes });

    return { success: true, snapshotId, changes };
  }

  // ==========================================================================
  // Code Regeneration (Sprints 4.4-4.5)
  // ==========================================================================

  /**
   * Determine if code should be regenerated
   *
   * Uses:
   * - hasFileChanged() to detect manual modifications
   *
   * Logic:
   * - Not transformed? Skip
   * - No code path? Skip
   * - Code file missing? Regenerate
   * - User modified code? Preserve (don't regenerate)
   * - Source newer than transform? Regenerate
   * - Otherwise? Skip (up to date)
   *
   * @param {string} componentId - Component ID
   * @returns {Promise<Object>} Decision with { should: boolean, reason: string, action: string }
   */
  async shouldRegenerateCode(componentId) {
    const registry = await readComponentRegistry(this.projectPath);
    const component = registry.components?.[componentId];

    if (!component) {
      return { should: false, reason: 'Component not found', action: 'skip' };
    }

    // Not transformed - nothing to regenerate
    if (component.transformation?.state !== 'transformed') {
      return { should: false, reason: 'Not transformed', action: 'skip' };
    }

    const { codePath, codeHash } = component.transformation;

    if (!codePath) {
      return { should: false, reason: 'No code path', action: 'skip' };
    }

    const fullPath = path.join(this.projectPath, codePath);

    // File missing - regenerate
    if (!fs.existsSync(fullPath)) {
      return { should: true, reason: 'Code file missing', action: 'regenerate' };
    }

    // USE EXISTING hasFileChanged() to detect user modifications
    const isModified = await hasFileChanged(fullPath, codeHash);

    if (isModified) {
      // File was modified by user - respect their changes
      if (this.config.preserveUserModifications) {
        return {
          should: false,
          reason: 'User modified code',
          action: 'preserve',
          userModified: true
        };
      }
    }

    // Check if source is newer than last transform
    const lastSync = component.syncMetadata?.lastFigmaSync;
    const lastTransform = component.transformation?.transformedAt;

    if (lastSync && lastTransform && new Date(lastSync) > new Date(lastTransform)) {
      return { should: true, reason: 'Source updated', action: 'regenerate' };
    }

    return { should: false, reason: 'Up to date', action: 'skip' };
  }

  /**
   * Regenerate component code
   *
   * Uses:
   * - Optimizer from optimizerRegistry
   * - hashFile() to update hash
   *
   * @param {string} componentId - Component ID
   * @returns {Promise<Object>} Result with { success: boolean, codePath: string, hash: string }
   */
  async regenerateCode(componentId) {
    this.emit(CASCADE_EVENTS.STEP, { step: 'code', componentId, status: 'starting' });

    const registry = await readComponentRegistry(this.projectPath);
    const component = registry.components?.[componentId];

    if (!component) {
      throw new Error(
        `Component "${componentId}" not found. ` +
        `Run "design-bridge status" to see registered components.`
      );
    }

    const { framework, codePath } = component.transformation || {};

    if (!framework || !codePath) {
      throw new Error(
        `Component "${componentId}" has not been transformed yet. ` +
        `Run "design-bridge transform --component ${componentId} --framework <framework>" first.`
      );
    }

    // Get optimizer from registry (injected)
    const optimizer = this.optimizerRegistry?.[framework];
    if (!optimizer) {
      throw new Error(
        `No code optimizer for framework "${framework}". ` +
        `Supported frameworks: react, vue, angular, svelte, flutter, react-native, swiftui, jetpack-compose.`
      );
    }

    // Load raw source data for re-transformation
    const rawDataPath = component.paths?.rawSource;
    if (!rawDataPath) {
      throw new Error(
        `Component "${componentId}" is missing raw design data. ` +
        `Re-import from the original source (Figma, ShadCN, etc.).`
      );
    }

    const fullRawPath = path.join(this.projectPath, rawDataPath);
    if (!fs.existsSync(fullRawPath)) {
      throw new Error(
        `Raw source file not found at "${rawDataPath}". ` +
        `Re-import the component from its original source.`
      );
    }

    const rawData = JSON.parse(fs.readFileSync(fullRawPath, 'utf8'));

    // Run EXISTING optimizer
    let result;
    try {
      if (typeof optimizer.optimize === 'function') {
        result = await optimizer.optimize({
          raw: rawData,
          registry: component,
          options: { typescript: true, includeStyles: true }
        });
      } else if (typeof optimizer.transform === 'function') {
        result = await optimizer.transform(rawData, {
          typescript: true,
          includeStyles: true
        });
      } else {
        throw new Error(`Optimizer for ${framework} has no optimize() or transform() method`);
      }
    } catch (err) {
      throw new Error(`Optimizer failed: ${err.message}`);
    }

    if (result && !result.success && result.error) {
      throw new Error(`Optimizer failed: ${result.error}`);
    }

    const code = result.code || result.output || '';
    if (!code) {
      throw new Error('Optimizer returned empty code');
    }

    // Write code
    const fullCodePath = path.join(this.projectPath, codePath);
    fs.mkdirSync(path.dirname(fullCodePath), { recursive: true });
    fs.writeFileSync(fullCodePath, code, 'utf8');

    // Update hash using EXISTING hashFile
    const newHash = await hashFile(fullCodePath);
    component.transformation.codeHash = newHash;
    component.transformation.transformedAt = new Date().toISOString();

    await writeComponentRegistry(this.projectPath, registry);

    this.emit(CASCADE_EVENTS.STEP, { step: 'code', componentId, status: 'completed' });

    return { success: true, codePath, hash: newHash };
  }

  // ==========================================================================
  // Story Regeneration (Sprints 4.6-4.7)
  // ==========================================================================

  /**
   * Determine if story should be regenerated
   *
   * Uses:
   * - StoryHashRegistry.checkStoryModified() to detect manual modifications
   *
   * Logic similar to code:
   * - Not transformed? Skip
   * - No story path? Skip (mobile frameworks)
   * - Story file missing? Regenerate
   * - User modified story? Preserve
   * - Source newer than transform? Regenerate
   *
   * @param {string} componentId - Component ID
   * @returns {Promise<Object>} Decision with { should: boolean, reason: string }
   */
  async shouldRegenerateStory(componentId) {
    const registry = await readComponentRegistry(this.projectPath);
    const component = registry.components?.[componentId];

    if (!component) {
      return { should: false, reason: 'Component not found' };
    }

    if (component.transformation?.state !== 'transformed') {
      return { should: false, reason: 'Not transformed' };
    }

    const { storyPath } = component.transformation;

    // No story path - mobile frameworks use native previews, not Storybook
    if (!storyPath) {
      return { should: false, reason: 'No story path (mobile framework?)' };
    }

    const fullPath = path.join(this.projectPath, storyPath);

    // File missing - regenerate
    if (!fs.existsSync(fullPath)) {
      return { should: true, reason: 'Story file missing' };
    }

    // USE EXISTING StoryHashRegistry.checkStoryModified()
    // Returns { isModified, reason, message, originalHash?, currentHash? }
    const modCheck = await this.storyHashRegistry.checkStoryModified(storyPath);

    if (modCheck.isModified && modCheck.reason === 'content-changed') {
      // File was modified by user - respect their changes
      if (this.config.preserveUserModifications) {
        return {
          should: false,
          reason: 'User modified story',
          userModified: true
        };
      }
    }

    // Check if source is newer than last transform
    const lastSync = component.syncMetadata?.lastFigmaSync;
    const lastTransform = component.transformation?.transformedAt;

    if (lastSync && lastTransform && new Date(lastSync) > new Date(lastTransform)) {
      return { should: true, reason: 'Source updated' };
    }

    return { should: false, reason: 'Up to date' };
  }

  /**
   * Regenerate component story
   *
   * Uses:
   * - StoryGenerator for story content
   * - StoryHashRegistry.registerStory() to track new story
   *
   * @param {string} componentId - Component ID
   * @returns {Promise<Object>} Result with { success: boolean, storyPath: string, hash: string }
   */
  async regenerateStory(componentId) {
    this.emit(CASCADE_EVENTS.STEP, { step: 'story', componentId, status: 'starting' });

    const registry = await readComponentRegistry(this.projectPath);
    const component = registry.components?.[componentId];

    if (!component) {
      throw new Error(`Component not found: ${componentId}`);
    }

    const { framework, storyPath, codePath } = component.transformation || {};

    if (!framework || !storyPath) {
      throw new Error(`Component "${componentId}" missing framework or storyPath`);
    }

    // USE EXISTING StoryGenerator
    const { StoryGenerator } = require('./story-generator');
    const generator = new StoryGenerator({
      projectPath: this.projectPath,
      framework
    });

    // Build component data for story generation
    const storyComponentData = {
      name: component.name,
      props: component.props || {},
      variants: component.variants || [],
      figmaUrl: component.source?.originalUrl || '',
      componentPath: codePath
    };

    // Generate story content
    const storyContent = generator.generateStoryFile(storyComponentData, framework);

    if (!storyContent) {
      throw new Error('Story generation returned null');
    }

    // Write story
    const fullStoryPath = path.join(this.projectPath, storyPath);
    fs.mkdirSync(path.dirname(fullStoryPath), { recursive: true });
    fs.writeFileSync(fullStoryPath, storyContent, 'utf8');

    // Register in EXISTING StoryHashRegistry
    await this.storyHashRegistry.registerStory(storyPath, storyContent, {
      framework,
      sourceType: component.source?.type || 'figma'
    });

    // Also update component registry with new hash
    const newHash = this.contentHasher.hash(storyContent);
    component.transformation.storyHash = newHash;

    await writeComponentRegistry(this.projectPath, registry);

    this.emit(CASCADE_EVENTS.STEP, { step: 'story', componentId, status: 'completed' });

    return { success: true, storyPath, hash: newHash };
  }

  // ==========================================================================
  // Rollback (Sprint 4.9)
  // ==========================================================================

  /**
   * Rollback component to snapshot state
   *
   * Uses:
   * - SnapshotManager.restore() to retrieve snapshot data
   *
   * @param {string} componentId - Component ID
   * @param {string} snapshotId - Snapshot ID from updateRegistry()
   * @returns {Promise<Object>} Result with { success: boolean }
   */
  async rollback(componentId, snapshotId) {
    this.emit(CASCADE_EVENTS.ROLLBACK, { componentId, status: 'starting' });

    try {
      // USE SnapshotManager.restore() - NOT DiffEngine
      // SnapshotManager handles retrieving and returning the snapshot state
      const restored = this.snapshotManager.restore(snapshotId);

      if (!restored) {
        throw new Error(`Snapshot ${snapshotId} not found`);
      }

      // Get current registry and update with restored component
      const registry = await readComponentRegistry(this.projectPath);

      // Apply restored data
      registry.components[componentId] = restored;

      // Add rollback metadata so we know this was rolled back
      registry.components[componentId].syncMetadata = {
        ...registry.components[componentId].syncMetadata,
        lastRollback: new Date().toISOString(),
        rollbackReason: 'Cascade sync failure',
        restoredFromSnapshot: snapshotId
      };

      await writeComponentRegistry(this.projectPath, registry);

      this.emit(CASCADE_EVENTS.ROLLBACK, { componentId, status: 'completed' });
      return { success: true };

    } catch (rollbackError) {
      this.emit(CASCADE_EVENTS.ROLLBACK, {
        componentId,
        status: 'failed',
        error: rollbackError.message
      });
      console.error(`CRITICAL: Rollback failed for ${componentId}:`, rollbackError);
      return { success: false, error: rollbackError.message };
    }
  }

  // ==========================================================================
  // Helper Methods
  // ==========================================================================

  /**
   * Get current cascade configuration
   * @returns {Object} Current configuration
   */
  getConfig() {
    return { ...this.config };
  }

  /**
   * Update cascade configuration
   * @param {Object} updates - Configuration updates
   */
  updateConfig(updates) {
    this.config = { ...this.config, ...updates };
  }

  /**
   * Check if cascade is enabled
   * @returns {boolean} True if cascade is enabled
   */
  isEnabled() {
    return this.config.enabled !== false;
  }
}

module.exports = {
  SyncCascade,
  CASCADE_EVENTS,
  CASCADE_DEFAULTS
};
