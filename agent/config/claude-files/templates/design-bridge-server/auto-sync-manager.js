/**
 * Auto-Sync Manager
 * Sprint 39-41: Automatic synchronization with Figma on webhook events
 *
 * Manages automatic token extraction and catalog updates when Figma files change.
 * Includes debouncing, error handling, conflict resolution, and sync history tracking.
 *
 * v4.0.0 Integration:
 * - Added RegistryManager support for unified registry operations
 * - O(1) component/token/layout lookups via sourceMapping
 * - Dependency tracking for cascade syncs
 * - Backward compatible with legacy registries
 *
 * @version 2.0.0
 */

const EventEmitter = require('events');
const path = require('path');
const fs = require('fs').promises;
const fsSync = require('fs');

// Make chalk optional (graceful degradation)
let chalk;
try {
  chalk = require('chalk');
} catch (e) {
  // Provide a no-op chalk implementation if not installed
  chalk = new Proxy({}, {
    get: () => (str) => str
  });
}

// Make logger optional
let logger;
try {
  logger = require('../logging').logger;
} catch (e) {
  // Provide a basic console logger if not available
  logger = {
    info: (...args) => console.log('[INFO]', ...args),
    error: (...args) => console.error('[ERROR]', ...args),
    warn: (...args) => console.warn('[WARN]', ...args),
    debug: () => {}
  };
}

const ConflictResolver = require('./conflict-resolver');
const SyncHistoryManager = require('./sync-history');
const { SyncCascade, CASCADE_DEFAULTS } = require('./sync-cascade');

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
 * Sync Status
 */
const SyncStatus = {
  IDLE: 'idle',
  PENDING: 'pending',
  SYNCING: 'syncing',
  SUCCESS: 'success',
  FAILED: 'failed',
  DEBOUNCING: 'debouncing'
};

/**
 * Sync Trigger Types
 */
const TriggerType = {
  WEBHOOK: 'webhook',
  MANUAL: 'manual',
  SCHEDULED: 'scheduled',
  RETRY: 'retry'
};

/**
 * Auto-Sync Manager
 * Handles automatic synchronization when Figma files change
 */
class AutoSyncManager extends EventEmitter {
  constructor(options = {}) {
    super();

    this.designBridge = options.designBridge;
    this.catalogOrchestrator = options.catalogOrchestrator;
    this.outputDir = options.outputDir || '.design';

    // Conflict resolution
    this.conflictResolver = new ConflictResolver({
      defaultStrategy: options.conflictStrategy || 'last_write_wins',
      autoResolve: options.autoResolveConflicts !== false
    });

    // Sync history tracking (Sprint 41)
    this.historyManager = new SyncHistoryManager({
      storageDir: path.join(this.outputDir, 'history'),
      retentionDays: options.historyRetentionDays || 30,
      autoSave: options.autoSaveHistory !== false,
      autoCleanup: options.autoCleanupHistory !== false
    });

    // Cascade sync (Phase 4: Two-State Auto-Sync)
    // Pass existing instances to SyncCascade for dependency injection
    this.cascadeEnabled = options.cascadeEnabled !== false;
    this.syncCascade = new SyncCascade({
      projectPath: options.projectPath || process.cwd(),
      conflictResolver: this.conflictResolver,  // Pass existing instance
      optimizerRegistry: options.optimizerRegistry || {},
      config: options.cascadeConfig
    });

    // Forward cascade events to AutoSyncManager
    this.syncCascade.on('cascade:started', (data) => this.emit('cascade:started', data));
    this.syncCascade.on('cascade:completed', (data) => this.emit('cascade:completed', data));
    this.syncCascade.on('cascade:failed', (data) => this.emit('cascade:failed', data));
    this.syncCascade.on('cascade:warning', (data) => this.emit('cascade:warning', data));
    this.syncCascade.on('cascade:rollback', (data) => this.emit('cascade:rollback', data));
    this.syncCascade.on('cascade:step', (data) => this.emit('cascade:step', data));

    // Wire up conflict events
    this.conflictResolver.on('conflict:detected', (conflict) => {
      console.log(chalk.yellow(`⚠️  Conflict detected: ${conflict.type}`));
      this.emit('conflict:detected', conflict);
    });

    this.conflictResolver.on('conflict:resolved', (resolution) => {
      console.log(chalk.green(`✓ Conflict auto-resolved: ${resolution.strategy}`));
      this.emit('conflict:resolved', resolution);
    });

    this.conflictResolver.on('conflict:requires_user', (resolution) => {
      console.log(chalk.red(`❗ Conflict requires user input: ${resolution.conflictId}`));
      this.emit('conflict:requires_user', resolution);
    });

    // Debouncing configuration
    this.debounceDelay = options.debounceDelay || 5000; // 5 seconds
    this.debounceTimers = new Map();

    // Rate limiting
    this.maxSyncsPerMinute = options.maxSyncsPerMinute || 12;
    this.syncHistory = []; // Kept for backward compatibility
    this.syncHistoryRetention = 3600000; // 1 hour

    // Retry configuration
    this.maxRetries = options.maxRetries || 3;
    this.retryDelay = options.retryDelay || 10000; // 10 seconds
    this.retryBackoffMultiplier = options.retryBackoffMultiplier || 2;

    // Current state
    this.currentSyncs = new Map();
    this.pendingSyncs = new Set();
    this.enabled = true;
    this.initialized = false;

    // Statistics
    this.stats = {
      totalSyncs: 0,
      successfulSyncs: 0,
      failedSyncs: 0,
      debouncedEvents: 0,
      rateLimitedEvents: 0,
      conflictsDetected: 0,
      conflictsResolved: 0,
      averageSyncDuration: 0
    };

    // v4.0.0 Registry Integration
    this._registryManager = null;
    this._v4Available = null;
    this.projectPath = options.projectPath || process.cwd();
    this.designPath = path.join(this.projectPath, '.design');
  }

  /**
   * Initialize - load sync history
   */
  async initialize() {
    if (this.initialized) {
      return;
    }

    try {
      await this.historyManager.initialize();
      this.initialized = true;
      logger.info('Auto-sync manager initialized with persistent history');
    } catch (error) {
      logger.error('Failed to initialize sync history:', error);
      // Continue without history tracking
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // v4.0.0 Registry Integration Methods
  // ═══════════════════════════════════════════════════════════════════════════

  /**
   * Check if v4.0.0 registry is available
   * @returns {boolean} True if registry-index.json exists
   */
  hasV4Registry() {
    if (this._v4Available === null) {
      const indexPath = path.join(this.designPath, 'registry-index.json');
      this._v4Available = fsSync.existsSync(indexPath);
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
   * Find components affected by a sync using v4.0.0 registry
   * Uses O(1) sourceMapping lookup instead of iterating all components
   * @param {string} fileKey - Figma file key
   * @returns {Promise<Array<{componentId: string, componentData: Object}>>}
   */
  async findAffectedComponentsV4(fileKey) {
    const rm = await this.getRegistryManager();
    if (!rm) {
      return [];
    }

    const affected = [];

    try {
      // Use O(1) sourceMapping lookup
      const sourceKey = `figma:${fileKey}`;
      const componentIds = rm.getEntriesBySource?.(sourceKey) || [];

      for (const canonicalId of componentIds) {
        const entry = rm.getById(canonicalId);
        if (!entry) continue;

        // Only cascade to transformed components
        if (entry.state !== 'transformed') continue;

        affected.push({
          componentId: canonicalId,
          componentData: entry
        });
      }

      logger.debug(`v4.0.0: Found ${affected.length} affected components for cascade via sourceMapping`);
    } catch (error) {
      logger.warn('v4.0.0 component lookup failed:', error.message);
    }

    return affected;
  }

  /**
   * Get dependencies for cascade impact analysis
   * Uses the dependency graph from registry-index.json
   * @param {string} entryId - Entry ID to check dependencies for
   * @returns {Promise<{dependents: string[], dependencies: string[]}>}
   */
  async getDependencies(entryId) {
    const rm = await this.getRegistryManager();
    if (!rm) {
      return { dependents: [], dependencies: [] };
    }

    return {
      dependents: rm.getDependents?.(entryId) || [],
      dependencies: rm.getDependencies?.(entryId) || []
    };
  }

  /**
   * Get v4.0.0 sync statistics
   * @returns {Promise<Object>} Registry statistics relevant to sync
   */
  async getV4Stats() {
    const rm = await this.getRegistryManager();
    if (!rm) {
      return { available: false };
    }

    const stats = rm.getStats?.() || {};
    return {
      available: true,
      totalEntries: stats.totalEntries || 0,
      transformedComponents: stats.byState?.transformed || 0,
      tokenCount: stats.byType?.token || 0,
      componentCount: stats.byType?.component || 0,
      layoutCount: stats.byType?.layout || 0
    };
  }

  /**
   * Invalidate v4.0.0 cache (call after sync completes)
   */
  invalidateV4Cache() {
    this._registryManager = null;
    this._v4Available = null;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Standard Methods
  // ═══════════════════════════════════════════════════════════════════════════

  /**
   * Enable auto-sync
   */
  enable() {
    this.enabled = true;
    console.log(chalk.green('✅ Auto-sync enabled'));
    this.emit('enabled');
  }

  /**
   * Disable auto-sync
   */
  disable() {
    this.enabled = false;

    // Clear all pending debounce timers
    for (const timer of this.debounceTimers.values()) {
      clearTimeout(timer);
    }
    this.debounceTimers.clear();

    console.log(chalk.yellow('🔇 Auto-sync disabled'));
    this.emit('disabled');
  }

  /**
   * Trigger sync for a Figma file
   */
  async triggerSync(fileKey, options = {}) {
    if (!this.enabled) {
      logger.warn('Auto-sync is disabled, ignoring trigger');
      return { success: false, reason: 'disabled' };
    }

    const {
      trigger = TriggerType.WEBHOOK,
      eventType = 'FILE_UPDATE',
      force = false,
      metadata = {}
    } = options;

    // Check rate limiting (unless forced)
    if (!force && this.isRateLimited(fileKey)) {
      logger.warn(`Sync rate limited for file: ${fileKey}`);
      this.stats.rateLimitedEvents++;
      this.emit('sync:rate_limited', { fileKey, trigger });
      return { success: false, reason: 'rate_limited' };
    }

    // Check if sync already in progress
    if (this.currentSyncs.has(fileKey)) {
      logger.info(`Sync already in progress for file: ${fileKey}`);
      return { success: false, reason: 'already_syncing' };
    }

    // Apply debouncing (unless forced)
    if (!force && this.shouldDebounce(trigger)) {
      this.debounceSync(fileKey, trigger, eventType, metadata);
      return { success: true, reason: 'debounced' };
    }

    // Execute sync
    return await this.executeSync(fileKey, trigger, eventType, metadata);
  }

  /**
   * Check if sync should be rate limited
   */
  isRateLimited(fileKey) {
    const now = Date.now();
    const cutoff = now - 60000; // Last minute

    // Clean old history
    this.syncHistory = this.syncHistory.filter(s => s.timestamp > cutoff);

    // Count syncs for this file in last minute
    const recentSyncs = this.syncHistory.filter(
      s => s.fileKey === fileKey && s.timestamp > cutoff
    );

    return recentSyncs.length >= this.maxSyncsPerMinute;
  }

  /**
   * Check if trigger type should be debounced
   */
  shouldDebounce(trigger) {
    // Don't debounce manual or retry triggers
    return trigger !== TriggerType.MANUAL && trigger !== TriggerType.RETRY;
  }

  /**
   * Debounce sync - delay execution until changes stop
   */
  debounceSync(fileKey, trigger, eventType, metadata) {
    // Clear existing timer if any
    if (this.debounceTimers.has(fileKey)) {
      clearTimeout(this.debounceTimers.get(fileKey));
      this.stats.debouncedEvents++;
    }

    // Set new timer
    const timer = setTimeout(async () => {
      this.debounceTimers.delete(fileKey);
      await this.executeSync(fileKey, trigger, eventType, metadata);
    }, this.debounceDelay);

    this.debounceTimers.set(fileKey, timer);

    // Mark as pending
    this.pendingSyncs.add(fileKey);

    logger.info(`Sync debounced for ${this.debounceDelay}ms: ${fileKey}`);
    this.emit('sync:debounced', { fileKey, delay: this.debounceDelay });
  }

  /**
   * Execute sync operation
   */
  async executeSync(fileKey, trigger, eventType, metadata, retryCount = 0) {
    const syncId = `sync_${Date.now()}_${fileKey}`;
    const startTime = Date.now();

    // Record sync event start in history
    let historyEvent = null;
    if (this.initialized && this.historyManager) {
      try {
        historyEvent = await this.historyManager.recordEvent({
          id: syncId,
          fileKey,
          trigger,
          eventType,
          status: 'started',
          retryCount,
          metadata
        });
      } catch (error) {
        logger.warn('Failed to record sync event in history:', error);
      }
    }

    // Mark as syncing
    this.currentSyncs.set(fileKey, {
      syncId,
      fileKey,
      trigger,
      eventType,
      startTime,
      status: SyncStatus.SYNCING,
      retryCount,
      historyEvent
    });

    this.pendingSyncs.delete(fileKey);
    this.emit('sync:started', { syncId, fileKey, trigger, eventType });

    console.log(chalk.blue(`\n🔄 Syncing file: ${fileKey}`));
    console.log(chalk.gray(`   Trigger: ${trigger}`));
    console.log(chalk.gray(`   Event: ${eventType}`));
    if (retryCount > 0) {
      console.log(chalk.yellow(`   Retry: ${retryCount}/${this.maxRetries}`));
    }

    try {
      // Extract tokens from Figma
      if (!this.designBridge) {
        throw new Error('Design Bridge not initialized');
      }

      const result = await this.designBridge.extractFromFigma(fileKey, {
        includeMetadata: true,
        includeComponents: true
      });

      // Prepare remote data
      const remoteData = result.tokens;

      // Check for conflicts with local data
      const catalogDataPath = path.join(this.outputDir, 'catalog-data.json');
      let finalData = remoteData;
      let conflictResolutions = [];

      try {
        // Read local catalog data if it exists
        const localDataStr = await fs.readFile(catalogDataPath, 'utf8');
        const localData = JSON.parse(localDataStr);

        // Detect conflicts
        const conflicts = await this.conflictResolver.detectConflicts(
          localData,
          remoteData,
          fileKey
        );

        if (conflicts.length > 0) {
          console.log(chalk.yellow(`   ⚠️  ${conflicts.length} conflict(s) detected`));
          this.stats.conflictsDetected += conflicts.length;

          // Resolve conflicts
          const resolution = await this.conflictResolver.resolveConflicts(
            localData,
            remoteData,
            conflicts,
            fileKey
          );

          finalData = resolution.data;
          conflictResolutions = resolution.conflicts;

          const resolvedCount = conflictResolutions.filter(r => r.status === 'resolved').length;
          console.log(chalk.green(`   ✓ ${resolvedCount} conflict(s) auto-resolved`));
          this.stats.conflictsResolved += resolvedCount;
        }

      } catch (error) {
        // Local data doesn't exist or is corrupted - use remote data as-is
        if (error.code !== 'ENOENT') {
          logger.warn('Error reading local catalog data:', error.message);
        }
      }

      // Save final resolved data to catalog
      await fs.mkdir(path.dirname(catalogDataPath), { recursive: true });
      await fs.writeFile(catalogDataPath, JSON.stringify(finalData, null, 2));

      // Also save to tokens directory for backward compatibility
      const tokenFile = path.join(this.outputDir, 'tokens', 'design-tokens.json');
      await fs.mkdir(path.dirname(tokenFile), { recursive: true });
      await fs.writeFile(tokenFile, JSON.stringify(finalData, null, 2));

      // Phase 4: Cascade sync to transformed components
      let cascadeResults = [];
      if (this.cascadeEnabled && this.syncCascade) {
        try {
          // Get cascade configuration
          const cascadeConfig = this.getCascadeConfig();

          // Find components affected by this sync
          // v4.0.0: Prefer O(1) lookup via sourceMapping, fallback to legacy scan
          let affectedComponents = [];
          if (this.hasV4Registry()) {
            affectedComponents = await this.findAffectedComponentsV4(fileKey);
          }
          if (affectedComponents.length === 0) {
            // Fallback to legacy method
            affectedComponents = this.findAffectedComponents(fileKey, finalData);
          }

          // Apply maxCascadesPerSync limit
          if (affectedComponents.length > cascadeConfig.maxCascadesPerSync) {
            console.log(chalk.yellow(`   ⚠ Limiting cascade to ${cascadeConfig.maxCascadesPerSync} components (${affectedComponents.length} affected)`));
            affectedComponents = affectedComponents.slice(0, cascadeConfig.maxCascadesPerSync);
          }

          if (affectedComponents.length > 0) {
            console.log(chalk.blue(`   📦 Cascading to ${affectedComponents.length} component(s)...`));

            for (const componentInfo of affectedComponents) {
              const { componentId, componentData } = componentInfo;
              try {
                // Apply cascade timeout
                const timeoutPromise = new Promise((_, reject) =>
                  setTimeout(() => reject(new Error('Cascade timeout')), cascadeConfig.cascadeTimeout)
                );

                const cascadeResult = await Promise.race([
                  this.syncCascade.cascade(componentId, componentData),
                  timeoutPromise
                ]);

                cascadeResults.push(cascadeResult);

                if (cascadeResult.success) {
                  console.log(chalk.green(`      ✓ ${componentId} cascade complete`));
                } else {
                  console.log(chalk.yellow(`      ⚠ ${componentId} cascade had issues`));
                }
              } catch (cascadeErr) {
                const errorMsg = cascadeErr.message === 'Cascade timeout'
                  ? `Cascade timeout (>${cascadeConfig.cascadeTimeout}ms)`
                  : cascadeErr.message;
                console.log(chalk.red(`      ✗ ${componentId} cascade failed: ${errorMsg}`));
                cascadeResults.push({ componentId, success: false, error: errorMsg });
              }
            }

            const succeeded = cascadeResults.filter(r => r.success).length;
            const failed = cascadeResults.filter(r => !r.success).length;
            console.log(chalk.gray(`   Cascade complete: ${succeeded} succeeded, ${failed} failed`));
          }
        } catch (cascadeError) {
          logger.warn('Cascade sync encountered error:', cascadeError.message);
          // Cascade errors should not fail the main sync
        }
      }

      // Calculate duration
      const duration = Date.now() - startTime;

      // Update stats
      this.stats.totalSyncs++;
      this.stats.successfulSyncs++;
      this.updateAverageDuration(duration);

      // Update history event with completion
      if (historyEvent && this.historyManager) {
        try {
          historyEvent.complete(duration, result.changes || {});
          if (conflictResolutions.length > 0) {
            historyEvent.addConflictInfo(
              conflictResolutions.length,
              conflictResolutions.filter(r => r.status === 'resolved').length
            );
          }
          await this.historyManager.updateEvent(syncId, historyEvent.toJSON());
        } catch (error) {
          logger.warn('Failed to update sync event in history:', error);
        }
      }

      // Record in legacy in-memory history (backward compatibility)
      this.recordSync({
        syncId,
        fileKey,
        trigger,
        eventType,
        status: SyncStatus.SUCCESS,
        duration,
        timestamp: Date.now(),
        changes: result.changes || {},
        metadata
      });

      // Remove from current syncs
      this.currentSyncs.delete(fileKey);

      // v4.0.0: Invalidate registry cache after sync (data may have changed)
      this.invalidateV4Cache();

      console.log(chalk.green(`   ✓ Sync completed (${duration}ms)`));
      if (result.changes) {
        console.log(chalk.gray(`   Changes: ${JSON.stringify(result.changes)}`));
      }

      this.emit('sync:completed', {
        syncId,
        fileKey,
        trigger,
        duration,
        changes: result.changes,
        cascadeResults: cascadeResults.length > 0 ? cascadeResults : undefined
      });

      return {
        success: true,
        syncId,
        duration,
        changes: result.changes,
        cascadeResults: cascadeResults.length > 0 ? cascadeResults : undefined
      };

    } catch (error) {
      logger.error(`Sync failed for ${fileKey}:`, error);

      const duration = Date.now() - startTime;

      // Check if should retry
      if (retryCount < this.maxRetries) {
        console.log(chalk.yellow(`   ⚠️  Sync failed, will retry...`));

        // Schedule retry with exponential backoff
        const retryDelay = this.retryDelay * Math.pow(this.retryBackoffMultiplier, retryCount);

        setTimeout(async () => {
          await this.executeSync(fileKey, TriggerType.RETRY, eventType, metadata, retryCount + 1);
        }, retryDelay);

        this.emit('sync:retry_scheduled', {
          syncId,
          fileKey,
          retryCount: retryCount + 1,
          retryDelay
        });

      } else {
        // Max retries reached
        console.log(chalk.red(`   ✗ Sync failed after ${retryCount} retries`));

        this.stats.totalSyncs++;
        this.stats.failedSyncs++;

        // Update history event with failure
        if (historyEvent && this.historyManager) {
          try {
            historyEvent.fail(error.message, duration);
            await this.historyManager.updateEvent(syncId, historyEvent.toJSON());
          } catch (updateError) {
            logger.warn('Failed to update sync event in history:', updateError);
          }
        }

        // Record failure in legacy in-memory history
        this.recordSync({
          syncId,
          fileKey,
          trigger,
          eventType,
          status: SyncStatus.FAILED,
          duration,
          timestamp: Date.now(),
          error: error.message,
          metadata
        });

        this.currentSyncs.delete(fileKey);

        this.emit('sync:failed', {
          syncId,
          fileKey,
          trigger,
          error: error.message,
          retries: retryCount
        });
      }

      return {
        success: false,
        syncId,
        error: error.message,
        retryCount
      };
    }
  }

  /**
   * Record sync in history
   */
  recordSync(syncData) {
    this.syncHistory.push(syncData);

    // Limit history size
    const maxHistory = 1000;
    if (this.syncHistory.length > maxHistory) {
      this.syncHistory = this.syncHistory.slice(-maxHistory);
    }

    // Clean old entries
    const cutoff = Date.now() - this.syncHistoryRetention;
    this.syncHistory = this.syncHistory.filter(s => s.timestamp > cutoff);
  }

  /**
   * Update average sync duration
   */
  updateAverageDuration(newDuration) {
    const { successfulSyncs, averageSyncDuration } = this.stats;

    if (successfulSyncs === 1) {
      this.stats.averageSyncDuration = newDuration;
    } else {
      this.stats.averageSyncDuration =
        ((averageSyncDuration * (successfulSyncs - 1)) + newDuration) / successfulSyncs;
    }
  }

  /**
   * Get sync status for a file
   */
  getSyncStatus(fileKey) {
    if (this.currentSyncs.has(fileKey)) {
      return this.currentSyncs.get(fileKey);
    }

    if (this.pendingSyncs.has(fileKey)) {
      return {
        fileKey,
        status: SyncStatus.DEBOUNCING,
        message: 'Sync pending (debounced)'
      };
    }

    return {
      fileKey,
      status: SyncStatus.IDLE,
      message: 'No active sync'
    };
  }

  /**
   * Get sync history for a file
   */
  getSyncHistory(fileKey, limit = 10) {
    return this.syncHistory
      .filter(s => s.fileKey === fileKey)
      .slice(-limit)
      .reverse();
  }

  /**
   * Get all sync history
   */
  getAllSyncHistory(limit = 50) {
    return this.syncHistory
      .slice(-limit)
      .reverse();
  }

  /**
   * Get statistics
   */
  getStatistics() {
    return {
      ...this.stats,
      enabled: this.enabled,
      currentSyncs: this.currentSyncs.size,
      pendingSyncs: this.pendingSyncs.size,
      historySize: this.syncHistory.length,
      successRate: this.stats.totalSyncs > 0
        ? ((this.stats.successfulSyncs / this.stats.totalSyncs) * 100).toFixed(2) + '%'
        : '0%'
    };
  }

  /**
   * Clear sync history
   */
  clearHistory() {
    this.syncHistory = [];
    console.log(chalk.gray('Sync history cleared'));
    this.emit('history:cleared');
  }

  /**
   * Cancel pending sync
   */
  cancelSync(fileKey) {
    if (this.debounceTimers.has(fileKey)) {
      clearTimeout(this.debounceTimers.get(fileKey));
      this.debounceTimers.delete(fileKey);
      this.pendingSyncs.delete(fileKey);

      console.log(chalk.yellow(`⏹️  Cancelled pending sync for: ${fileKey}`));
      this.emit('sync:cancelled', { fileKey });

      return true;
    }

    return false;
  }

  /**
   * Cancel all pending syncs
   */
  cancelAllSyncs() {
    const count = this.debounceTimers.size;

    for (const timer of this.debounceTimers.values()) {
      clearTimeout(timer);
    }

    this.debounceTimers.clear();
    this.pendingSyncs.clear();

    console.log(chalk.yellow(`⏹️  Cancelled ${count} pending sync(s)`));
    this.emit('syncs:cancelled_all', { count });

    return count;
  }

  /**
   * Phase 8: Trigger manual sync (from UI "Sync Now" button)
   * Bypasses debouncing and resets the interval timer
   * @param {string} fileKey - Figma file key
   * @returns {Promise<Object>} Sync result
   */
  async triggerManualSync(fileKey) {
    console.log(chalk.cyan(`🔄 Manual sync triggered for: ${fileKey}`));

    // Clear any pending debounce for this file
    if (this.debounceTimers.has(fileKey)) {
      clearTimeout(this.debounceTimers.get(fileKey));
      this.debounceTimers.delete(fileKey);
      this.pendingSyncs.delete(fileKey);
    }

    // Reset the interval timer
    this.resetIntervalTimer(fileKey);

    // Execute sync immediately with manual trigger type
    const result = await this.executeSync(fileKey, TriggerType.MANUAL, 'MANUAL_TRIGGER', {
      manual: true,
      triggeredAt: new Date().toISOString()
    });

    // Emit manual sync event
    this.emit('sync:manual', { fileKey, result });

    return result;
  }

  /**
   * Phase 8: Reset the interval timer for a file
   * Called after manual sync to restart the auto-sync countdown
   * @param {string} fileKey - Figma file key
   */
  resetIntervalTimer(fileKey) {
    // Clear existing interval if any
    if (this.intervals && this.intervals.has(fileKey)) {
      clearInterval(this.intervals.get(fileKey));
    }

    // Only restart if auto-sync is enabled
    if (!this.enabled) {
      return;
    }

    // Start fresh interval (if intervals Map exists)
    if (!this.intervals) {
      this.intervals = new Map();
    }

    const intervalMs = this.syncIntervalMs || 15 * 60 * 1000; // Default 15 minutes

    const interval = setInterval(() => {
      this.triggerSync(fileKey, { trigger: TriggerType.SCHEDULED });
    }, intervalMs);

    this.intervals.set(fileKey, interval);

    console.log(chalk.gray(`⏱️  Timer reset - next auto-sync in ${intervalMs / 60000} minutes for: ${fileKey}`));
  }

  /**
   * Find components affected by a sync (Phase 4: Two-State Auto-Sync)
   * Looks up component registry to find components from this file that are in 'transformed' state
   * v4.0.0: Prefers v4 registry with O(1) lookup, falls back to legacy scan
   * @param {string} fileKey - Figma file key
   * @param {Object} extractedData - Data extracted from Figma
   * @returns {Array<{componentId: string, componentData: Object}>}
   */
  findAffectedComponents(fileKey, extractedData) {
    // v4.0.0: Try async v4 lookup first (called from async context)
    // Note: This method is sync for backward compat, but v4 uses async
    // For v4 usage, call findAffectedComponentsV4 directly
    const affectedComponents = [];

    try {
      // Try to read the component registry
      const { readComponentRegistry } = require('./registry-reader');
      const projectPath = this.syncCascade?.projectPath || process.cwd();

      // readComponentRegistry is async in some versions, sync in others
      // Use synchronous file read for simplicity here
      const registryPath = path.join(projectPath, '.design', 'componentRegistry.json');

      let registry;
      try {
        const registryData = require('fs').readFileSync(registryPath, 'utf8');
        registry = JSON.parse(registryData);
      } catch (readError) {
        // No registry exists yet - nothing to cascade
        logger.debug('No component registry found, skipping cascade');
        return [];
      }

      if (!registry || !registry.components) {
        return [];
      }

      // Find components that:
      // 1. Come from this Figma file (by fileKey)
      // 2. Are in 'transformed' state
      const components = registry.components;

      // Handle both object and array formats
      const componentEntries = Array.isArray(components)
        ? components.map(c => [c.id, c])
        : Object.entries(components);

      for (const [componentId, component] of componentEntries) {
        // Check if component is from this file
        const sourceFileKey = component.source?.fileKey
          || component.figmaUrl?.match(/file\/([a-zA-Z0-9]+)/)?.[1]
          || component.sourceFileKey;

        if (sourceFileKey !== fileKey) {
          continue;
        }

        // Check if component is in transformed state
        if (component.state !== 'transformed') {
          continue;
        }

        // Extract component-specific data from the synced data
        const componentData = this.extractComponentData(extractedData, componentId, component);

        affectedComponents.push({
          componentId,
          componentData
        });
      }

      logger.debug(`Found ${affectedComponents.length} affected components for cascade`);
      return affectedComponents;

    } catch (error) {
      logger.warn('Error finding affected components:', error.message);
      return [];
    }
  }

  /**
   * Get cascade configuration from project config or defaults
   * Priority: SyncCascade instance config > project config file > defaults
   * @returns {Object} Merged cascade configuration
   */
  getCascadeConfig() {
    // Start with defaults
    let config = { ...CASCADE_DEFAULTS };

    // Try to load project-specific config from file
    try {
      const projectConfigPath = path.join(this.outputDir, 'config.json');
      if (require('fs').existsSync(projectConfigPath)) {
        const projectConfig = JSON.parse(require('fs').readFileSync(projectConfigPath, 'utf8'));
        if (projectConfig.cascade) {
          config = { ...config, ...projectConfig.cascade };
        }
      }
    } catch (error) {
      logger.debug('Could not load project cascade config, using defaults');
    }

    // Override with SyncCascade instance config (highest priority)
    if (this.syncCascade && this.syncCascade.config) {
      config = { ...config, ...this.syncCascade.config };
    }

    return config;
  }

  /**
   * Set cascade enabled state (for CLI --no-cascade flag)
   * @param {boolean} enabled - Whether cascade should be enabled
   */
  setCascadeEnabled(enabled) {
    this.cascadeEnabled = enabled;
    if (this.syncCascade) {
      this.syncCascade.updateConfig({ enabled });
    }
    logger.info(`Cascade sync ${enabled ? 'enabled' : 'disabled'}`);
  }

  /**
   * Extract component-specific data from synced design data
   * @param {Object} extractedData - Full extracted data from Figma
   * @param {string} componentId - Component ID to extract data for
   * @param {Object} registryEntry - Component's registry entry
   * @returns {Object} Component-specific data for cascade
   */
  extractComponentData(extractedData, componentId, registryEntry) {
    // Build component data object with relevant tokens and metadata
    const componentData = {
      id: componentId,
      name: registryEntry.name,
      source: registryEntry.source,
      // Include token dependencies from the extracted data
      tokens: {},
      styles: {}
    };

    // If extracted data has components section, look for this component
    if (extractedData.components) {
      const componentTokens = extractedData.components[componentId]
        || extractedData.components[registryEntry.name];

      if (componentTokens) {
        componentData.tokens = componentTokens;
      }
    }

    // Include relevant design tokens based on component's tokenDependencies
    if (registryEntry.tokenDependencies && extractedData.tokens) {
      const deps = registryEntry.tokenDependencies;

      // Map token categories to extracted data
      for (const [category, tokenRefs] of Object.entries(deps)) {
        if (extractedData.tokens[category]) {
          componentData.tokens[category] = {};

          // If tokenRefs is an array, extract only those tokens
          if (Array.isArray(tokenRefs)) {
            for (const ref of tokenRefs) {
              if (extractedData.tokens[category][ref]) {
                componentData.tokens[category][ref] = extractedData.tokens[category][ref];
              }
            }
          } else {
            // Otherwise include the whole category
            componentData.tokens[category] = extractedData.tokens[category];
          }
        }
      }
    }

    // Include styles if available
    if (extractedData.styles) {
      componentData.styles = extractedData.styles;
    }

    return componentData;
  }

  /**
   * Shutdown - clean up resources
   */
  async shutdown() {
    this.disable();
    this.cancelAllSyncs();

    // Wait for active syncs to complete (max 30 seconds)
    const timeout = 30000;
    const start = Date.now();

    while (this.currentSyncs.size > 0 && Date.now() - start < timeout) {
      await new Promise(resolve => setTimeout(resolve, 100));
    }

    // Shutdown history manager
    if (this.historyManager) {
      await this.historyManager.shutdown();
    }

    console.log(chalk.gray('Auto-sync manager shutdown complete'));
    this.emit('shutdown');
  }
}

module.exports = AutoSyncManager;
module.exports.SyncStatus = SyncStatus;
module.exports.TriggerType = TriggerType;
