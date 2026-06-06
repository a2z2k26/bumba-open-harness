/**
 * Phase 9 - Sprint 9.3: Incremental Processing & Diffing
 *
 * Provides efficient change detection, diffing, and incremental
 * processing to minimize redundant work and improve performance.
 */

const { EventEmitter } = require('events');
const crypto = require('crypto');

// Import ContentHasher from standalone module (Option C - Sprint 1.2 refactor)
const { ContentHasher } = require('./content-hasher');

// ============================================================================
// Constants
// ============================================================================

const DIFF_TYPES = {
  ADDED: 'added',
  REMOVED: 'removed',
  MODIFIED: 'modified',
  UNCHANGED: 'unchanged',
  MOVED: 'moved'
};

const CHANGE_OPERATIONS = {
  CREATE: 'create',
  UPDATE: 'update',
  DELETE: 'delete',
  RENAME: 'rename',
  MOVE: 'move'
};

const PROCESSOR_EVENTS = {
  DIFF_COMPUTED: 'diff:computed',
  SNAPSHOT_CREATED: 'snapshot:created',
  SNAPSHOT_RESTORED: 'snapshot:restored',
  CHANGES_DETECTED: 'changes:detected',
  PROCESSING_START: 'processing:start',
  PROCESSING_COMPLETE: 'processing:complete',
  MERGE_COMPLETE: 'merge:complete'
};

// ============================================================================
// DiffEngine - Compute differences between objects
// ============================================================================

class DiffEngine extends EventEmitter {
  constructor(options = {}) {
    super();
    this.hasher = new ContentHasher(options.hasher);
    this.options = {
      ignoreKeys: options.ignoreKeys || [],
      deepCompare: options.deepCompare !== false,
      detectMoves: options.detectMoves || false,
      ...options
    };
  }

  /**
   * Diff two objects
   */
  diff(oldObj, newObj, options = {}) {
    const opts = { ...this.options, ...options };
    const changes = [];

    // Handle null/undefined
    if (oldObj === null || oldObj === undefined) {
      if (newObj === null || newObj === undefined) {
        return { changes: [], hasChanges: false };
      }
      return {
        changes: [{ type: DIFF_TYPES.ADDED, path: '', value: newObj }],
        hasChanges: true
      };
    }

    if (newObj === null || newObj === undefined) {
      return {
        changes: [{ type: DIFF_TYPES.REMOVED, path: '', value: oldObj }],
        hasChanges: true
      };
    }

    // Compare objects
    this._compareObjects(oldObj, newObj, '', changes, opts);

    const result = {
      changes,
      hasChanges: changes.length > 0,
      summary: this._summarize(changes)
    };

    this.emit(PROCESSOR_EVENTS.DIFF_COMPUTED, result);
    return result;
  }

  /**
   * Diff arrays with move detection
   */
  diffArray(oldArr, newArr, keyFn = null) {
    const changes = [];
    const keyFunc = keyFn || ((item, i) => i);

    // Build index maps
    const oldMap = new Map();
    const newMap = new Map();

    oldArr.forEach((item, i) => oldMap.set(keyFunc(item, i), { item, index: i }));
    newArr.forEach((item, i) => newMap.set(keyFunc(item, i), { item, index: i }));

    // Find removed items
    for (const [key, { item, index }] of oldMap) {
      if (!newMap.has(key)) {
        changes.push({
          type: DIFF_TYPES.REMOVED,
          key,
          index,
          value: item
        });
      }
    }

    // Find added items
    for (const [key, { item, index }] of newMap) {
      if (!oldMap.has(key)) {
        changes.push({
          type: DIFF_TYPES.ADDED,
          key,
          index,
          value: item
        });
      }
    }

    // Find modified/moved items
    for (const [key, { item: newItem, index: newIndex }] of newMap) {
      if (oldMap.has(key)) {
        const { item: oldItem, index: oldIndex } = oldMap.get(key);

        // Check if modified
        if (JSON.stringify(oldItem) !== JSON.stringify(newItem)) {
          changes.push({
            type: DIFF_TYPES.MODIFIED,
            key,
            oldIndex,
            newIndex,
            oldValue: oldItem,
            newValue: newItem
          });
        } else if (oldIndex !== newIndex && this.options.detectMoves) {
          changes.push({
            type: DIFF_TYPES.MOVED,
            key,
            oldIndex,
            newIndex,
            value: newItem
          });
        }
      }
    }

    return {
      changes,
      hasChanges: changes.length > 0,
      added: changes.filter(c => c.type === DIFF_TYPES.ADDED).length,
      removed: changes.filter(c => c.type === DIFF_TYPES.REMOVED).length,
      modified: changes.filter(c => c.type === DIFF_TYPES.MODIFIED).length,
      moved: changes.filter(c => c.type === DIFF_TYPES.MOVED).length
    };
  }

  /**
   * Generate patch from diff
   */
  createPatch(diff) {
    return diff.changes.map(change => {
      switch (change.type) {
        case DIFF_TYPES.ADDED:
          return { op: 'add', path: change.path, value: change.newValue };
        case DIFF_TYPES.REMOVED:
          return { op: 'remove', path: change.path };
        case DIFF_TYPES.MODIFIED:
          return { op: 'replace', path: change.path, value: change.newValue };
        default:
          return null;
      }
    }).filter(Boolean);
  }

  /**
   * Apply patch to object
   */
  applyPatch(obj, patch) {
    const result = JSON.parse(JSON.stringify(obj));

    for (const op of patch) {
      const pathParts = op.path.split('.').filter(Boolean);

      if (op.op === 'add' || op.op === 'replace') {
        this._setAtPath(result, pathParts, op.value);
      } else if (op.op === 'remove') {
        this._deleteAtPath(result, pathParts);
      }
    }

    return result;
  }

  _compareObjects(oldObj, newObj, path, changes, opts) {
    const allKeys = new Set([...Object.keys(oldObj), ...Object.keys(newObj)]);

    for (const key of allKeys) {
      if (opts.ignoreKeys.includes(key)) continue;

      const currentPath = path ? `${path}.${key}` : key;
      const oldVal = oldObj[key];
      const newVal = newObj[key];

      if (!(key in oldObj)) {
        changes.push({
          type: DIFF_TYPES.ADDED,
          path: currentPath,
          newValue: newVal
        });
      } else if (!(key in newObj)) {
        changes.push({
          type: DIFF_TYPES.REMOVED,
          path: currentPath,
          oldValue: oldVal
        });
      } else if (opts.deepCompare && typeof oldVal === 'object' && typeof newVal === 'object' &&
                 oldVal !== null && newVal !== null && !Array.isArray(oldVal) && !Array.isArray(newVal)) {
        this._compareObjects(oldVal, newVal, currentPath, changes, opts);
      } else if (JSON.stringify(oldVal) !== JSON.stringify(newVal)) {
        changes.push({
          type: DIFF_TYPES.MODIFIED,
          path: currentPath,
          oldValue: oldVal,
          newValue: newVal
        });
      }
    }
  }

  _setAtPath(obj, path, value) {
    let current = obj;
    for (let i = 0; i < path.length - 1; i++) {
      if (!(path[i] in current)) {
        current[path[i]] = {};
      }
      current = current[path[i]];
    }
    current[path[path.length - 1]] = value;
  }

  _deleteAtPath(obj, path) {
    let current = obj;
    for (let i = 0; i < path.length - 1; i++) {
      if (!(path[i] in current)) return;
      current = current[path[i]];
    }
    delete current[path[path.length - 1]];
  }

  _summarize(changes) {
    return {
      added: changes.filter(c => c.type === DIFF_TYPES.ADDED).length,
      removed: changes.filter(c => c.type === DIFF_TYPES.REMOVED).length,
      modified: changes.filter(c => c.type === DIFF_TYPES.MODIFIED).length,
      total: changes.length
    };
  }
}

// ============================================================================
// ChangeSet - Track and manage sets of changes
// ============================================================================

class ChangeSet {
  constructor(id = null) {
    this.id = id || crypto.randomUUID();
    this.changes = [];
    this.metadata = {
      createdAt: new Date().toISOString(),
      source: null,
      description: null
    };
  }

  /**
   * Add a change to the set
   */
  add(change) {
    this.changes.push({
      ...change,
      timestamp: Date.now(),
      id: crypto.randomUUID()
    });
    return this;
  }

  /**
   * Add multiple changes
   */
  addAll(changes) {
    for (const change of changes) {
      this.add(change);
    }
    return this;
  }

  /**
   * Get changes by type
   */
  getByType(type) {
    return this.changes.filter(c => c.type === type);
  }

  /**
   * Get changes by path pattern
   */
  getByPath(pattern) {
    const regex = new RegExp(pattern);
    return this.changes.filter(c => regex.test(c.path));
  }

  /**
   * Filter changes
   */
  filter(predicate) {
    return this.changes.filter(predicate);
  }

  /**
   * Check if change set is empty
   */
  isEmpty() {
    return this.changes.length === 0;
  }

  /**
   * Get change count
   */
  size() {
    return this.changes.length;
  }

  /**
   * Merge with another change set
   */
  merge(other) {
    const merged = new ChangeSet();
    merged.addAll(this.changes);
    merged.addAll(other.changes);
    merged.metadata.description = `Merged: ${this.id} + ${other.id}`;
    return merged;
  }

  /**
   * Serialize change set
   */
  toJSON() {
    return {
      id: this.id,
      changes: this.changes,
      metadata: this.metadata,
      summary: this.getSummary()
    };
  }

  /**
   * Deserialize change set
   */
  static fromJSON(json) {
    const cs = new ChangeSet(json.id);
    cs.changes = json.changes || [];
    cs.metadata = json.metadata || {};
    return cs;
  }

  /**
   * Get summary
   */
  getSummary() {
    const byType = {};
    for (const change of this.changes) {
      byType[change.type] = (byType[change.type] || 0) + 1;
    }
    return {
      total: this.changes.length,
      byType,
      timespan: this.changes.length > 0
        ? {
            first: this.changes[0].timestamp,
            last: this.changes[this.changes.length - 1].timestamp
          }
        : null
    };
  }
}

// ============================================================================
// SnapshotManager - Save and restore state snapshots
// ============================================================================

class SnapshotManager extends EventEmitter {
  constructor(options = {}) {
    super();
    this.snapshots = new Map();
    this.hasher = new ContentHasher();
    this.options = {
      maxSnapshots: options.maxSnapshots || 100,
      compressSnapshots: options.compressSnapshots || false,
      ...options
    };
  }

  /**
   * Create a snapshot
   */
  create(state, metadata = {}) {
    const id = crypto.randomUUID();
    const hash = this.hasher.hash(state);

    const snapshot = {
      id,
      hash,
      state: JSON.parse(JSON.stringify(state)),
      metadata: {
        ...metadata,
        createdAt: new Date().toISOString()
      }
    };

    // Enforce max snapshots
    if (this.snapshots.size >= this.options.maxSnapshots) {
      const oldest = this.snapshots.keys().next().value;
      this.snapshots.delete(oldest);
    }

    this.snapshots.set(id, snapshot);
    this.emit(PROCESSOR_EVENTS.SNAPSHOT_CREATED, { id, hash });

    return id;
  }

  /**
   * Get a snapshot by ID
   */
  get(id) {
    return this.snapshots.get(id);
  }

  /**
   * Get latest snapshot
   */
  getLatest() {
    const ids = Array.from(this.snapshots.keys());
    if (ids.length === 0) return null;
    return this.snapshots.get(ids[ids.length - 1]);
  }

  /**
   * Restore state from snapshot
   */
  restore(id) {
    const snapshot = this.snapshots.get(id);
    if (!snapshot) {
      throw new Error(`Snapshot not found: ${id}`);
    }

    this.emit(PROCESSOR_EVENTS.SNAPSHOT_RESTORED, { id });
    return JSON.parse(JSON.stringify(snapshot.state));
  }

  /**
   * Compare two snapshots
   */
  compare(id1, id2) {
    const s1 = this.snapshots.get(id1);
    const s2 = this.snapshots.get(id2);

    if (!s1 || !s2) {
      throw new Error('One or both snapshots not found');
    }

    const diffEngine = new DiffEngine();
    return diffEngine.diff(s1.state, s2.state);
  }

  /**
   * List all snapshots
   */
  list() {
    return Array.from(this.snapshots.values()).map(s => ({
      id: s.id,
      hash: s.hash,
      metadata: s.metadata
    }));
  }

  /**
   * Delete a snapshot
   */
  delete(id) {
    return this.snapshots.delete(id);
  }

  /**
   * Clear all snapshots
   */
  clear() {
    this.snapshots.clear();
  }

  /**
   * Check if state has changed from snapshot
   */
  hasChanged(id, currentState) {
    const snapshot = this.snapshots.get(id);
    if (!snapshot) return true;

    const currentHash = this.hasher.hash(currentState);
    return snapshot.hash !== currentHash;
  }
}

// ============================================================================
// IncrementalProcessor - Process only changed items
// ============================================================================

class IncrementalProcessor extends EventEmitter {
  constructor(options = {}) {
    super();
    this.hasher = new ContentHasher();
    this.diffEngine = new DiffEngine(options.diff);
    this.snapshotManager = new SnapshotManager(options.snapshot);
    this.options = {
      batchSize: options.batchSize || 50,
      parallelism: options.parallelism || 4,
      ...options
    };

    this.state = {
      hashes: new Map(),
      lastProcessed: null,
      processing: false
    };

    this.stats = {
      totalProcessed: 0,
      skipped: 0,
      batches: 0
    };
  }

  /**
   * Process items incrementally
   */
  async process(items, processor, options = {}) {
    const opts = { ...this.options, ...options };
    this.state.processing = true;
    this.emit(PROCESSOR_EVENTS.PROCESSING_START, { count: items.length });

    const results = [];
    const changed = [];
    const skipped = [];

    // Identify changed items
    for (const item of items) {
      const id = this._getItemId(item, opts.idKey);
      const hash = this.hasher.hash(item);
      const previousHash = this.state.hashes.get(id);

      if (previousHash !== hash) {
        changed.push({ item, id, hash });
        this.state.hashes.set(id, hash);
      } else {
        skipped.push({ item, id });
        this.stats.skipped++;
      }
    }

    this.emit(PROCESSOR_EVENTS.CHANGES_DETECTED, {
      changed: changed.length,
      skipped: skipped.length
    });

    // Process changed items in batches
    for (let i = 0; i < changed.length; i += opts.batchSize) {
      const batch = changed.slice(i, i + opts.batchSize);
      this.stats.batches++;

      const batchResults = await Promise.all(
        batch.map(async ({ item, id, hash }) => {
          try {
            const result = await processor(item);
            this.stats.totalProcessed++;
            return { id, result, success: true };
          } catch (error) {
            return { id, error: error.message, success: false };
          }
        })
      );

      results.push(...batchResults);
    }

    this.state.lastProcessed = Date.now();
    this.state.processing = false;

    const summary = {
      processed: changed.length,
      skipped: skipped.length,
      successful: results.filter(r => r.success).length,
      failed: results.filter(r => !r.success).length
    };

    this.emit(PROCESSOR_EVENTS.PROCESSING_COMPLETE, summary);

    return {
      results,
      summary,
      skippedIds: skipped.map(s => s.id)
    };
  }

  /**
   * Process with dependency tracking
   */
  async processWithDependencies(items, processor, dependencyGraph) {
    const processed = new Set();
    const results = [];

    const processItem = async (item) => {
      const id = this._getItemId(item);
      if (processed.has(id)) return;

      // Process dependencies first
      const deps = dependencyGraph.get(id) || [];
      for (const depId of deps) {
        const depItem = items.find(i => this._getItemId(i) === depId);
        if (depItem) {
          await processItem(depItem);
        }
      }

      // Process this item
      const result = await processor(item);
      processed.add(id);
      results.push({ id, result });
    };

    for (const item of items) {
      await processItem(item);
    }

    return results;
  }

  /**
   * Invalidate cached hash for item
   */
  invalidate(id) {
    return this.state.hashes.delete(id);
  }

  /**
   * Invalidate multiple items
   */
  invalidateMany(ids) {
    let count = 0;
    for (const id of ids) {
      if (this.state.hashes.delete(id)) count++;
    }
    return count;
  }

  /**
   * Invalidate by pattern
   */
  invalidateByPattern(pattern) {
    const regex = new RegExp(pattern);
    let count = 0;

    for (const id of this.state.hashes.keys()) {
      if (regex.test(id)) {
        this.state.hashes.delete(id);
        count++;
      }
    }

    return count;
  }

  /**
   * Clear all state
   */
  reset() {
    this.state.hashes.clear();
    this.state.lastProcessed = null;
    this.stats = { totalProcessed: 0, skipped: 0, batches: 0 };
  }

  /**
   * Create a checkpoint
   */
  checkpoint(label = null) {
    return this.snapshotManager.create(
      { hashes: Object.fromEntries(this.state.hashes) },
      { label, stats: { ...this.stats } }
    );
  }

  /**
   * Restore from checkpoint
   */
  restoreCheckpoint(id) {
    const snapshot = this.snapshotManager.restore(id);
    this.state.hashes = new Map(Object.entries(snapshot.hashes));
    return true;
  }

  _getItemId(item, idKey = 'id') {
    if (typeof item === 'string') return item;
    if (item[idKey]) return item[idKey];
    if (item.name) return item.name;
    return this.hasher.shortHash(item);
  }

  getStats() {
    return {
      ...this.stats,
      trackedItems: this.state.hashes.size,
      lastProcessed: this.state.lastProcessed,
      processing: this.state.processing
    };
  }
}

// ============================================================================
// MergeEngine - Merge changes intelligently
// ============================================================================

class MergeEngine extends EventEmitter {
  constructor(options = {}) {
    super();
    this.options = {
      conflictStrategy: options.conflictStrategy || 'newer', // newer, older, manual
      arrayMerge: options.arrayMerge || 'concat', // concat, replace, union
      ...options
    };
  }

  /**
   * Merge two objects
   */
  merge(base, source, options = {}) {
    const opts = { ...this.options, ...options };
    const result = JSON.parse(JSON.stringify(base));
    const conflicts = [];

    this._mergeObjects(result, source, '', conflicts, opts);

    this.emit(PROCESSOR_EVENTS.MERGE_COMPLETE, {
      conflicts: conflicts.length
    });

    return {
      result,
      conflicts,
      hasConflicts: conflicts.length > 0
    };
  }

  /**
   * Three-way merge
   */
  threeWayMerge(base, ours, theirs) {
    const diffEngine = new DiffEngine();

    const ourChanges = diffEngine.diff(base, ours);
    const theirChanges = diffEngine.diff(base, theirs);

    const conflicts = this._findConflicts(ourChanges.changes, theirChanges.changes);
    const result = JSON.parse(JSON.stringify(base));

    // Apply non-conflicting changes from ours
    for (const change of ourChanges.changes) {
      if (!conflicts.some(c => c.path === change.path)) {
        this._applyChange(result, change);
      }
    }

    // Apply non-conflicting changes from theirs
    for (const change of theirChanges.changes) {
      if (!conflicts.some(c => c.path === change.path)) {
        this._applyChange(result, change);
      }
    }

    return {
      result,
      conflicts,
      ourChanges: ourChanges.changes.length,
      theirChanges: theirChanges.changes.length
    };
  }

  /**
   * Resolve conflict
   */
  resolveConflict(conflict, resolution) {
    return {
      path: conflict.path,
      resolved: true,
      value: resolution === 'ours' ? conflict.ours : conflict.theirs,
      resolution
    };
  }

  _mergeObjects(target, source, path, conflicts, opts) {
    for (const key of Object.keys(source)) {
      const currentPath = path ? `${path}.${key}` : key;
      const targetVal = target[key];
      const sourceVal = source[key];

      if (!(key in target)) {
        // Key doesn't exist in target, add it
        target[key] = sourceVal;
      } else if (Array.isArray(targetVal) && Array.isArray(sourceVal)) {
        // Array merge
        target[key] = this._mergeArrays(targetVal, sourceVal, opts.arrayMerge);
      } else if (typeof targetVal === 'object' && typeof sourceVal === 'object' &&
                 targetVal !== null && sourceVal !== null) {
        // Recursive object merge
        this._mergeObjects(targetVal, sourceVal, currentPath, conflicts, opts);
      } else if (targetVal !== sourceVal) {
        // Conflict
        if (opts.conflictStrategy === 'newer') {
          target[key] = sourceVal;
        } else if (opts.conflictStrategy === 'manual') {
          conflicts.push({
            path: currentPath,
            ours: targetVal,
            theirs: sourceVal
          });
        }
        // 'older' strategy: keep target value (do nothing)
      }
    }
  }

  _mergeArrays(target, source, strategy) {
    switch (strategy) {
      case 'concat':
        return [...target, ...source];
      case 'replace':
        return source;
      case 'union':
        return [...new Set([...target, ...source])];
      default:
        return source;
    }
  }

  _findConflicts(changes1, changes2) {
    const conflicts = [];

    for (const c1 of changes1) {
      for (const c2 of changes2) {
        if (c1.path === c2.path && c1.type !== DIFF_TYPES.UNCHANGED && c2.type !== DIFF_TYPES.UNCHANGED) {
          if (JSON.stringify(c1.newValue) !== JSON.stringify(c2.newValue)) {
            conflicts.push({
              path: c1.path,
              ours: c1.newValue,
              theirs: c2.newValue
            });
          }
        }
      }
    }

    return conflicts;
  }

  _applyChange(obj, change) {
    const pathParts = change.path.split('.').filter(Boolean);

    if (change.type === DIFF_TYPES.REMOVED) {
      let current = obj;
      for (let i = 0; i < pathParts.length - 1; i++) {
        if (!(pathParts[i] in current)) return;
        current = current[pathParts[i]];
      }
      delete current[pathParts[pathParts.length - 1]];
    } else if (change.type === DIFF_TYPES.ADDED || change.type === DIFF_TYPES.MODIFIED) {
      let current = obj;
      for (let i = 0; i < pathParts.length - 1; i++) {
        if (!(pathParts[i] in current)) {
          current[pathParts[i]] = {};
        }
        current = current[pathParts[i]];
      }
      current[pathParts[pathParts.length - 1]] = change.newValue;
    }
  }
}

// ============================================================================
// DependencyTracker - Track dependencies between items
// ============================================================================

class DependencyTracker {
  constructor() {
    this.dependencies = new Map(); // id -> Set of dependency ids
    this.dependents = new Map();   // id -> Set of dependent ids
  }

  /**
   * Add a dependency
   */
  addDependency(id, dependsOn) {
    if (!this.dependencies.has(id)) {
      this.dependencies.set(id, new Set());
    }
    this.dependencies.get(id).add(dependsOn);

    if (!this.dependents.has(dependsOn)) {
      this.dependents.set(dependsOn, new Set());
    }
    this.dependents.get(dependsOn).add(id);
  }

  /**
   * Get dependencies for an item
   */
  getDependencies(id) {
    return Array.from(this.dependencies.get(id) || []);
  }

  /**
   * Get dependents (items that depend on this)
   */
  getDependents(id) {
    return Array.from(this.dependents.get(id) || []);
  }

  /**
   * Get all affected items (cascade)
   */
  getAffected(id, visited = new Set()) {
    if (visited.has(id)) return [];
    visited.add(id);

    const affected = [id];
    const dependents = this.getDependents(id);

    for (const dep of dependents) {
      affected.push(...this.getAffected(dep, visited));
    }

    return affected;
  }

  /**
   * Get topological order for processing
   */
  getProcessingOrder(ids) {
    const visited = new Set();
    const order = [];

    const visit = (id) => {
      if (visited.has(id)) return;
      visited.add(id);

      const deps = this.getDependencies(id);
      for (const dep of deps) {
        if (ids.includes(dep)) {
          visit(dep);
        }
      }

      order.push(id);
    };

    for (const id of ids) {
      visit(id);
    }

    return order;
  }

  /**
   * Detect circular dependencies
   */
  hasCircularDependency(id, visited = new Set(), path = []) {
    if (path.includes(id)) {
      return { hasCircular: true, cycle: [...path, id] };
    }

    if (visited.has(id)) {
      return { hasCircular: false };
    }

    visited.add(id);
    path.push(id);

    const deps = this.getDependencies(id);
    for (const dep of deps) {
      const result = this.hasCircularDependency(dep, visited, [...path]);
      if (result.hasCircular) return result;
    }

    return { hasCircular: false };
  }

  /**
   * Remove an item and its relationships
   */
  remove(id) {
    // Remove from dependencies
    this.dependencies.delete(id);

    // Remove from all dependents lists
    for (const [, deps] of this.dependencies) {
      deps.delete(id);
    }

    // Remove from dependents map
    this.dependents.delete(id);

    // Remove from all dependencies lists
    for (const [, deps] of this.dependents) {
      deps.delete(id);
    }
  }

  /**
   * Clear all tracking
   */
  clear() {
    this.dependencies.clear();
    this.dependents.clear();
  }

  /**
   * Get graph representation
   */
  toGraph() {
    const nodes = new Set();
    const edges = [];

    for (const [id, deps] of this.dependencies) {
      nodes.add(id);
      for (const dep of deps) {
        nodes.add(dep);
        edges.push({ from: id, to: dep });
      }
    }

    return {
      nodes: Array.from(nodes),
      edges
    };
  }
}

// ============================================================================
// Factory Functions
// ============================================================================

function createIncrementalProcessor(options = {}) {
  return new IncrementalProcessor(options);
}

function createDiffEngine(options = {}) {
  return new DiffEngine(options);
}

function createMergeEngine(options = {}) {
  return new MergeEngine(options);
}

// ============================================================================
// Exports
// ============================================================================

module.exports = {
  // Main classes
  IncrementalProcessor,
  DiffEngine,
  MergeEngine,
  ContentHasher,
  ChangeSet,
  SnapshotManager,
  DependencyTracker,

  // Factory functions
  createIncrementalProcessor,
  createDiffEngine,
  createMergeEngine,

  // Constants
  DIFF_TYPES,
  CHANGE_OPERATIONS,
  PROCESSOR_EVENTS
};
