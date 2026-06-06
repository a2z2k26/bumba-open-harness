/**
 * Conflict Resolver
 * Sprint 40: Conflict detection and resolution for concurrent modifications
 *
 * Handles scenarios where catalog data is modified locally while remote
 * Figma changes occur, preventing data loss and maintaining consistency.
 */

const EventEmitter = require('events');
const crypto = require('crypto');

// Make chalk optional (graceful degradation)
let chalk;
try {
  chalk = require('chalk');
} catch (e) {
  chalk = new Proxy({}, {
    get: () => (str) => str
  });
}

// Make logger optional
let logger;
try {
  logger = require('../logging').logger;
} catch (e) {
  logger = {
    info: (...args) => console.log('[INFO]', ...args),
    error: (...args) => console.error('[ERROR]', ...args),
    warn: (...args) => console.warn('[WARN]', ...args),
    debug: () => {}
  };
}

/**
 * Conflict Types
 */
const ConflictType = {
  CONCURRENT_MODIFICATION: 'concurrent_modification',
  RAPID_UPDATES: 'rapid_updates',
  NETWORK_OUTAGE: 'network_outage',
  VERSION_MISMATCH: 'version_mismatch',
  DATA_CORRUPTION: 'data_corruption'
};

/**
 * Resolution Strategies
 */
const ResolutionStrategy = {
  LAST_WRITE_WINS: 'last_write_wins',
  MERGE: 'merge',
  PROMPT_USER: 'prompt_user',
  KEEP_LOCAL: 'keep_local',
  KEEP_REMOTE: 'keep_remote',
  MANUAL: 'manual'
};

/**
 * Conflict Status
 */
const ConflictStatus = {
  DETECTED: 'detected',
  RESOLVED: 'resolved',
  PENDING_USER: 'pending_user',
  FAILED: 'failed'
};

/**
 * Conflict Resolution Result
 */
class ConflictResolution {
  constructor(data = {}) {
    this.conflictId = data.conflictId || `conflict_${Date.now()}`;
    this.type = data.type;
    this.strategy = data.strategy;
    this.status = data.status || ConflictStatus.DETECTED;
    this.local = data.local;
    this.remote = data.remote;
    this.resolved = data.resolved || null;
    this.timestamp = data.timestamp || new Date().toISOString();
    this.fieldsAffected = data.fieldsAffected || [];
    this.resolutionDetails = data.resolutionDetails || {};
  }

  toJSON() {
    return {
      conflictId: this.conflictId,
      type: this.type,
      strategy: this.strategy,
      status: this.status,
      local: this.local,
      remote: this.remote,
      resolved: this.resolved,
      timestamp: this.timestamp,
      fieldsAffected: this.fieldsAffected,
      resolutionDetails: this.resolutionDetails
    };
  }
}

/**
 * Conflict Resolver
 * Detects and resolves conflicts in catalog data
 */
class ConflictResolver extends EventEmitter {
  constructor(options = {}) {
    super();

    this.defaultStrategy = options.defaultStrategy || ResolutionStrategy.LAST_WRITE_WINS;
    this.autoResolve = options.autoResolve !== false; // Default true
    this.strategyRules = options.strategyRules || this.getDefaultStrategyRules();

    // Conflict history
    this.conflicts = [];
    this.maxHistorySize = options.maxHistorySize || 100;

    // Statistics
    this.stats = {
      totalConflicts: 0,
      autoResolved: 0,
      manualResolved: 0,
      failed: 0,
      byType: {},
      byStrategy: {}
    };
  }

  /**
   * Get default strategy rules for different data types
   */
  getDefaultStrategyRules() {
    return {
      colors: ResolutionStrategy.LAST_WRITE_WINS,
      typography: ResolutionStrategy.LAST_WRITE_WINS,
      spacing: ResolutionStrategy.LAST_WRITE_WINS,
      components: ResolutionStrategy.MERGE,
      metadata: ResolutionStrategy.KEEP_REMOTE,
      history: ResolutionStrategy.MERGE
    };
  }

  /**
   * Detect conflicts between local and remote data
   */
  async detectConflicts(localData, remoteData, fileKey) {
    logger.info('Detecting conflicts between local and remote data');

    const conflicts = [];

    // Check timestamps
    const localTimestamp = new Date(localData.generatedAt).getTime();
    const remoteTimestamp = new Date(remoteData.generatedAt).getTime();

    // Calculate data hashes
    const localHash = this.calculateHash(localData);
    const remoteHash = this.calculateHash(remoteData);

    // No conflict if data is identical
    if (localHash === remoteHash) {
      logger.info('No conflicts: data is identical');
      return [];
    }

    // Conflict detected
    const conflict = {
      type: ConflictType.CONCURRENT_MODIFICATION,
      fileKey,
      local: {
        timestamp: localData.generatedAt,
        hash: localHash,
        version: localData.version
      },
      remote: {
        timestamp: remoteData.generatedAt,
        hash: remoteHash,
        version: remoteData.version
      },
      fieldsAffected: this.findAffectedFields(localData, remoteData)
    };

    // Check for specific conflict types
    if (Math.abs(localTimestamp - remoteTimestamp) < 10000) {
      // Within 10 seconds = concurrent modification
      conflict.type = ConflictType.CONCURRENT_MODIFICATION;
    } else if (localTimestamp > remoteTimestamp) {
      // Local is newer = possible network outage recovery
      conflict.type = ConflictType.NETWORK_OUTAGE;
    } else if (remoteData.version !== localData.version) {
      // Version mismatch
      conflict.type = ConflictType.VERSION_MISMATCH;
    }

    conflicts.push(conflict);

    this.stats.totalConflicts++;
    this.stats.byType[conflict.type] = (this.stats.byType[conflict.type] || 0) + 1;

    logger.warn('Conflict detected:', {
      type: conflict.type,
      fieldsAffected: conflict.fieldsAffected.length
    });

    return conflicts;
  }

  /**
   * Resolve conflicts using configured strategies
   */
  async resolveConflicts(localData, remoteData, conflicts, fileKey) {
    if (conflicts.length === 0) {
      return { data: remoteData, conflicts: [] };
    }

    logger.info(`Resolving ${conflicts.length} conflict(s)`);

    const resolutions = [];

    for (const conflict of conflicts) {
      const resolution = await this.resolveConflict(localData, remoteData, conflict);
      resolutions.push(resolution);

      // Track resolution
      this.conflicts.push(resolution);
      this.trimHistory();

      // Emit events
      this.emit('conflict:detected', conflict);

      if (resolution.status === ConflictStatus.RESOLVED) {
        this.emit('conflict:resolved', resolution);
      } else if (resolution.status === ConflictStatus.PENDING_USER) {
        this.emit('conflict:requires_user', resolution);
      }
    }

    // Merge all resolutions
    const resolvedData = this.mergeResolutions(localData, remoteData, resolutions);

    return {
      data: resolvedData,
      conflicts: resolutions
    };
  }

  /**
   * Resolve a single conflict
   */
  async resolveConflict(localData, remoteData, conflict) {
    const resolution = new ConflictResolution({
      type: conflict.type,
      local: conflict.local,
      remote: conflict.remote,
      fieldsAffected: conflict.fieldsAffected
    });

    // Determine strategy for each affected field
    const fieldStrategies = this.determineStrategies(conflict.fieldsAffected);

    try {
      // Apply resolution strategies
      const resolvedData = {};

      for (const field of conflict.fieldsAffected) {
        const strategy = fieldStrategies[field];
        const fieldResult = this.applyStrategy(
          strategy,
          field,
          localData[field],
          remoteData[field]
        );

        resolvedData[field] = fieldResult.data;
        resolution.resolutionDetails[field] = {
          strategy,
          action: fieldResult.action,
          itemsAdded: fieldResult.itemsAdded || 0,
          itemsRemoved: fieldResult.itemsRemoved || 0,
          itemsModified: fieldResult.itemsModified || 0
        };
      }

      resolution.resolved = resolvedData;
      resolution.status = ConflictStatus.RESOLVED;
      resolution.strategy = 'mixed'; // Multiple strategies used

      this.stats.autoResolved++;
      this.stats.byStrategy[resolution.strategy] =
        (this.stats.byStrategy[resolution.strategy] || 0) + 1;

      logger.info('Conflict auto-resolved:', {
        conflictId: resolution.conflictId,
        fieldsAffected: conflict.fieldsAffected.length
      });

    } catch (error) {
      logger.error('Conflict resolution failed:', error);

      resolution.status = ConflictStatus.FAILED;
      resolution.resolutionDetails.error = error.message;

      this.stats.failed++;
    }

    return resolution;
  }

  /**
   * Determine resolution strategy for each field
   */
  determineStrategies(fields) {
    const strategies = {};

    for (const field of fields) {
      strategies[field] = this.strategyRules[field] || this.defaultStrategy;
    }

    return strategies;
  }

  /**
   * Apply a resolution strategy to a field
   */
  applyStrategy(strategy, field, localValue, remoteValue) {
    switch (strategy) {
      case ResolutionStrategy.LAST_WRITE_WINS:
        return this.lastWriteWins(field, localValue, remoteValue);

      case ResolutionStrategy.MERGE:
        return this.merge(field, localValue, remoteValue);

      case ResolutionStrategy.KEEP_LOCAL:
        return this.keepLocal(field, localValue, remoteValue);

      case ResolutionStrategy.KEEP_REMOTE:
        return this.keepRemote(field, localValue, remoteValue);

      case ResolutionStrategy.PROMPT_USER:
        return this.promptUser(field, localValue, remoteValue);

      default:
        logger.warn(`Unknown strategy: ${strategy}, using LAST_WRITE_WINS`);
        return this.lastWriteWins(field, localValue, remoteValue);
    }
  }

  /**
   * Last Write Wins strategy
   */
  lastWriteWins(field, localValue, remoteValue) {
    // Remote is always considered newer in webhook sync
    return {
      data: remoteValue,
      action: 'replaced_with_remote',
      strategy: ResolutionStrategy.LAST_WRITE_WINS
    };
  }

  /**
   * Merge strategy (for arrays)
   */
  merge(field, localValue, remoteValue) {
    if (!Array.isArray(localValue) || !Array.isArray(remoteValue)) {
      logger.warn(`Cannot merge non-array field: ${field}`);
      return this.lastWriteWins(field, localValue, remoteValue);
    }

    // Create lookup maps by ID or name
    const localMap = new Map();
    const remoteMap = new Map();

    for (const item of localValue) {
      const key = item.id || item.name || JSON.stringify(item);
      localMap.set(key, item);
    }

    for (const item of remoteValue) {
      const key = item.id || item.name || JSON.stringify(item);
      remoteMap.set(key, item);
    }

    // Merge: remote takes precedence, but keep local-only items
    const merged = [];
    const added = [];
    const modified = [];
    const removed = [];

    // Add all remote items (new and modified)
    for (const [key, item] of remoteMap) {
      merged.push(item);

      if (!localMap.has(key)) {
        added.push(key);
      } else {
        // Check if modified
        const localItem = localMap.get(key);
        if (JSON.stringify(localItem) !== JSON.stringify(item)) {
          modified.push(key);
        }
      }
    }

    // Add local-only items that don't exist in remote
    for (const [key, item] of localMap) {
      if (!remoteMap.has(key)) {
        // Keep local additions
        merged.push(item);
        removed.push(key); // Mark as removed from remote perspective
      }
    }

    return {
      data: merged,
      action: 'merged',
      strategy: ResolutionStrategy.MERGE,
      itemsAdded: added.length,
      itemsModified: modified.length,
      itemsRemoved: 0, // We kept local-only items
      details: { added, modified, kept: removed }
    };
  }

  /**
   * Keep Local strategy
   */
  keepLocal(field, localValue, remoteValue) {
    return {
      data: localValue,
      action: 'kept_local',
      strategy: ResolutionStrategy.KEEP_LOCAL
    };
  }

  /**
   * Keep Remote strategy
   */
  keepRemote(field, localValue, remoteValue) {
    return {
      data: remoteValue,
      action: 'kept_remote',
      strategy: ResolutionStrategy.KEEP_REMOTE
    };
  }

  /**
   * Prompt User strategy (deferred resolution)
   */
  promptUser(field, localValue, remoteValue) {
    // In automated context, default to keeping remote
    logger.warn(`User prompt required for field: ${field}, defaulting to remote`);

    return {
      data: remoteValue,
      action: 'requires_user_input',
      strategy: ResolutionStrategy.PROMPT_USER,
      deferred: true
    };
  }

  /**
   * Find fields that differ between local and remote
   */
  findAffectedFields(localData, remoteData) {
    const affected = [];
    const fieldsToCheck = ['colors', 'typography', 'spacing', 'components', 'metadata'];

    for (const field of fieldsToCheck) {
      // Only check fields that exist in at least one of the data sets
      const hasLocal = localData && localData[field] !== undefined;
      const hasRemote = remoteData && remoteData[field] !== undefined;

      if (hasLocal || hasRemote) {
        const localHash = this.calculateHash(localData ? localData[field] : undefined);
        const remoteHash = this.calculateHash(remoteData ? remoteData[field] : undefined);

        if (localHash !== remoteHash) {
          affected.push(field);
        }
      }
    }

    return affected;
  }

  /**
   * Merge all resolutions into final data
   */
  mergeResolutions(localData, remoteData, resolutions) {
    const merged = { ...remoteData };

    for (const resolution of resolutions) {
      if (resolution.status === ConflictStatus.RESOLVED && resolution.resolved) {
        Object.assign(merged, resolution.resolved);
      }
    }

    // Add conflict resolution metadata to history
    if (!merged.history) {
      merged.history = [];
    }

    merged.history.push({
      timestamp: new Date().toISOString(),
      changeType: 'conflict:resolved',
      description: `Resolved ${resolutions.length} conflict(s)`,
      conflicts: resolutions.map(r => ({
        id: r.conflictId,
        type: r.type,
        strategy: r.strategy,
        fieldsAffected: r.fieldsAffected
      }))
    });

    return merged;
  }

  /**
   * Calculate hash of data for comparison
   */
  calculateHash(data) {
    if (data === null || data === undefined) {
      return crypto.createHash('sha256').update('null').digest('hex');
    }

    let str;
    if (typeof data === 'object' && !Array.isArray(data)) {
      // Sort keys for consistent hashing of objects
      str = JSON.stringify(data, Object.keys(data).sort());
    } else {
      // Arrays and primitives
      str = JSON.stringify(data);
    }

    return crypto.createHash('sha256').update(str).digest('hex');
  }

  /**
   * Get conflict by ID
   */
  getConflict(conflictId) {
    return this.conflicts.find(c => c.conflictId === conflictId);
  }

  /**
   * Get recent conflicts
   */
  getRecentConflicts(limit = 10) {
    return this.conflicts.slice(-limit).reverse();
  }

  /**
   * Get pending conflicts requiring user input
   */
  getPendingConflicts() {
    return this.conflicts.filter(c => c.status === ConflictStatus.PENDING_USER);
  }

  /**
   * Manually resolve a conflict
   */
  async manualResolve(conflictId, resolution) {
    const conflict = this.getConflict(conflictId);
    if (!conflict) {
      throw new Error(`Conflict not found: ${conflictId}`);
    }

    conflict.status = ConflictStatus.RESOLVED;
    conflict.resolved = resolution;
    conflict.resolutionDetails.manual = true;

    this.stats.manualResolved++;

    this.emit('conflict:manually_resolved', conflict);

    logger.info('Conflict manually resolved:', conflictId);

    return conflict;
  }

  /**
   * Get statistics
   */
  getStatistics() {
    const total = this.stats.totalConflicts;

    return {
      ...this.stats,
      autoResolveRate: total > 0
        ? ((this.stats.autoResolved / total) * 100).toFixed(2) + '%'
        : '0%',
      failureRate: total > 0
        ? ((this.stats.failed / total) * 100).toFixed(2) + '%'
        : '0%',
      pending: this.getPendingConflicts().length,
      historySize: this.conflicts.length
    };
  }

  /**
   * Clear conflict history
   */
  clearHistory() {
    this.conflicts = [];
    logger.info('Conflict history cleared');
    this.emit('history:cleared');
  }

  /**
   * Trim conflict history to max size
   */
  trimHistory() {
    if (this.conflicts.length > this.maxHistorySize) {
      const removed = this.conflicts.length - this.maxHistorySize;
      this.conflicts = this.conflicts.slice(-this.maxHistorySize);
      logger.debug(`Trimmed ${removed} conflicts from history`);
    }
  }

  /**
   * Export conflict for external resolution
   */
  exportConflict(conflictId) {
    const conflict = this.getConflict(conflictId);
    if (!conflict) {
      throw new Error(`Conflict not found: ${conflictId}`);
    }

    return {
      conflict: conflict.toJSON(),
      local: conflict.local,
      remote: conflict.remote,
      diff: this.generateDiff(conflict)
    };
  }

  /**
   * Generate human-readable diff
   */
  generateDiff(conflict) {
    const diff = {
      summary: `${conflict.fieldsAffected.length} field(s) affected`,
      fields: {}
    };

    for (const field of conflict.fieldsAffected) {
      diff.fields[field] = {
        local: conflict.local,
        remote: conflict.remote,
        strategy: conflict.resolutionDetails[field]?.strategy || 'unknown'
      };
    }

    return diff;
  }
}

module.exports = ConflictResolver;
module.exports.ConflictResolver = ConflictResolver;
module.exports.ConflictType = ConflictType;
module.exports.ResolutionStrategy = ResolutionStrategy;
module.exports.ConflictStatus = ConflictStatus;
module.exports.ConflictResolution = ConflictResolution;
