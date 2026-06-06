/**
 * Sync Verifier
 *
 * Verifies synchronization between Figma designs and generated code.
 * Detects drift, validates mappings, and ensures consistency across
 * the design-to-code pipeline.
 *
 * Key Principle: Make failures observable and recoverable, not silent and destructive.
 *
 * @module sync-verifier
 */

'use strict';

const crypto = require('crypto');

// =============================================================================
// CONSTANTS
// =============================================================================

/**
 * Verification result statuses
 */
const VERIFICATION_STATUS = {
  SYNCED: 'synced',           // Fully synchronized
  DRIFTED: 'drifted',         // Content has changed
  MISSING: 'missing',         // Expected item not found
  ADDED: 'added',             // New item not in baseline
  CONFLICT: 'conflict',       // Conflicting changes
  UNKNOWN: 'unknown'          // Cannot determine status
};

/**
 * Verification severity levels
 */
const SEVERITY = {
  INFO: 'info',
  WARNING: 'warning',
  ERROR: 'error',
  CRITICAL: 'critical'
};

/**
 * What aspects to verify
 */
const VERIFY_ASPECTS = {
  STRUCTURE: 'structure',     // Node tree structure
  STYLING: 'styling',         // Style properties
  CONTENT: 'content',         // Text and content
  LAYOUT: 'layout',           // Layout properties
  ASSETS: 'assets',           // Images and assets
  BINDINGS: 'bindings',       // Component bindings
  ALL: 'all'
};

/**
 * Default verification options
 */
const DEFAULT_OPTIONS = {
  aspects: [VERIFY_ASPECTS.ALL],
  tolerances: {
    position: 1,              // Pixel tolerance for position
    dimension: 1,             // Pixel tolerance for dimensions
    color: 0.01,              // Color difference tolerance
    opacity: 0.01             // Opacity tolerance
  },
  ignoreHidden: true,
  ignoreInternalNodes: true,
  deepCompare: true,
  maxDepth: 50,
  reportLimit: 100
};

// =============================================================================
// CONTENT HASHER
// =============================================================================

/**
 * Creates content hashes for comparison
 */
class ContentHasher {
  /**
   * Create a content hasher
   * @param {Object} options - Hasher options
   */
  constructor(options = {}) {
    this.options = {
      algorithm: 'sha256',
      hashLength: 16,
      ...options
    };
  }

  /**
   * Create hash from input
   * @param {*} input - Input to hash
   * @returns {string} Hash string
   */
  hash(input) {
    const data = typeof input === 'string' ? input : JSON.stringify(input);
    return crypto
      .createHash(this.options.algorithm)
      .update(data)
      .digest('hex')
      .substring(0, this.options.hashLength);
  }

  /**
   * Hash node structure
   * @param {Object} node - Node to hash
   * @returns {string} Structure hash
   */
  hashStructure(node) {
    const structure = this._extractStructure(node);
    return this.hash(structure);
  }

  /**
   * Hash node styling
   * @param {Object} node - Node to hash
   * @returns {string} Styling hash
   */
  hashStyling(node) {
    const styling = this._extractStyling(node);
    return this.hash(styling);
  }

  /**
   * Hash node content
   * @param {Object} node - Node to hash
   * @returns {string} Content hash
   */
  hashContent(node) {
    const content = this._extractContent(node);
    return this.hash(content);
  }

  /**
   * Hash node layout
   * @param {Object} node - Node to hash
   * @returns {string} Layout hash
   */
  hashLayout(node) {
    const layout = this._extractLayout(node);
    return this.hash(layout);
  }

  /**
   * Create composite hash of all aspects
   * @param {Object} node - Node to hash
   * @returns {Object} Hashes for each aspect
   */
  hashAll(node) {
    return {
      structure: this.hashStructure(node),
      styling: this.hashStyling(node),
      content: this.hashContent(node),
      layout: this.hashLayout(node),
      combined: this.hash({
        structure: this._extractStructure(node),
        styling: this._extractStyling(node),
        content: this._extractContent(node),
        layout: this._extractLayout(node)
      })
    };
  }

  /**
   * Extract structure data from node
   * @param {Object} node - Source node
   * @returns {Object} Structure data
   * @private
   */
  _extractStructure(node) {
    return {
      type: node.type,
      name: node.name,
      childCount: node.children?.length || 0,
      childTypes: (node.children || []).map(c => c.type)
    };
  }

  /**
   * Extract styling data from node
   * @param {Object} node - Source node
   * @returns {Object} Styling data
   * @private
   */
  _extractStyling(node) {
    return {
      fills: node.fills,
      strokes: node.strokes,
      effects: node.effects,
      opacity: node.opacity,
      blendMode: node.blendMode,
      cornerRadius: node.cornerRadius
    };
  }

  /**
   * Extract content data from node
   * @param {Object} node - Source node
   * @returns {Object} Content data
   * @private
   */
  _extractContent(node) {
    return {
      characters: node.characters,
      textStyle: node.style,
      componentId: node.componentId,
      mainComponent: node.mainComponent?.id
    };
  }

  /**
   * Extract layout data from node
   * @param {Object} node - Source node
   * @returns {Object} Layout data
   * @private
   */
  _extractLayout(node) {
    return {
      x: Math.round(node.x || 0),
      y: Math.round(node.y || 0),
      width: Math.round(node.width || 0),
      height: Math.round(node.height || 0),
      layoutMode: node.layoutMode,
      layoutAlign: node.layoutAlign,
      primaryAxisSizingMode: node.primaryAxisSizingMode,
      counterAxisSizingMode: node.counterAxisSizingMode,
      paddingTop: node.paddingTop,
      paddingRight: node.paddingRight,
      paddingBottom: node.paddingBottom,
      paddingLeft: node.paddingLeft,
      itemSpacing: node.itemSpacing
    };
  }
}

// =============================================================================
// SYNC BASELINE
// =============================================================================

/**
 * Stores baseline state for comparison
 */
class SyncBaseline {
  /**
   * Create a sync baseline
   */
  constructor() {
    this.entries = new Map();
    this.createdAt = Date.now();
    this.hasher = new ContentHasher();
  }

  /**
   * Add a node to the baseline
   * @param {string} id - Node ID
   * @param {Object} node - Node data
   * @param {Object} metadata - Additional metadata
   */
  add(id, node, metadata = {}) {
    this.entries.set(id, {
      hashes: this.hasher.hashAll(node),
      metadata: {
        name: node.name,
        type: node.type,
        addedAt: Date.now(),
        ...metadata
      },
      snapshot: this._createSnapshot(node)
    });
  }

  /**
   * Create a minimal snapshot of node state
   * @param {Object} node - Node to snapshot
   * @returns {Object} Snapshot
   * @private
   */
  _createSnapshot(node) {
    return {
      type: node.type,
      name: node.name,
      width: node.width,
      height: node.height,
      childCount: node.children?.length || 0,
      hasText: !!node.characters,
      isComponent: node.type === 'COMPONENT' || node.type === 'INSTANCE'
    };
  }

  /**
   * Get baseline entry
   * @param {string} id - Entry ID
   * @returns {Object|null} Entry or null
   */
  get(id) {
    return this.entries.get(id) || null;
  }

  /**
   * Check if baseline has entry
   * @param {string} id - Entry ID
   * @returns {boolean} True if exists
   */
  has(id) {
    return this.entries.has(id);
  }

  /**
   * Remove entry from baseline
   * @param {string} id - Entry ID
   * @returns {boolean} True if removed
   */
  remove(id) {
    return this.entries.delete(id);
  }

  /**
   * Get all entry IDs
   * @returns {string[]} Entry IDs
   */
  getIds() {
    return Array.from(this.entries.keys());
  }

  /**
   * Get baseline statistics
   * @returns {Object} Statistics
   */
  getStats() {
    return {
      entryCount: this.entries.size,
      createdAt: this.createdAt,
      ageMs: Date.now() - this.createdAt
    };
  }

  /**
   * Export baseline to JSON
   * @returns {Object} Exported data
   */
  export() {
    const entries = {};
    for (const [id, entry] of this.entries) {
      entries[id] = entry;
    }
    return {
      entries,
      createdAt: this.createdAt,
      exportedAt: Date.now()
    };
  }

  /**
   * Import baseline from JSON
   * @param {Object} data - Import data
   */
  import(data) {
    if (data.entries) {
      for (const [id, entry] of Object.entries(data.entries)) {
        this.entries.set(id, entry);
      }
    }
    if (data.createdAt) {
      this.createdAt = data.createdAt;
    }
  }

  /**
   * Clear all entries
   */
  clear() {
    this.entries.clear();
    this.createdAt = Date.now();
  }
}

// =============================================================================
// SYNC VERIFIER
// =============================================================================

/**
 * Main verifier for sync operations
 */
class SyncVerifier {
  /**
   * Create a sync verifier
   * @param {Object} options - Verifier options
   */
  constructor(options = {}) {
    this.options = { ...DEFAULT_OPTIONS, ...options };
    this.hasher = new ContentHasher();
    this.baseline = new SyncBaseline();
    this.verificationHistory = [];
  }

  /**
   * Set baseline from current state
   * @param {Object[]} nodes - Nodes to baseline
   * @param {Function} idGetter - Function to get ID from node
   */
  setBaseline(nodes, idGetter = (n) => n.id) {
    this.baseline.clear();

    for (const node of nodes) {
      const id = idGetter(node);
      this.baseline.add(id, node);
    }
  }

  /**
   * Verify a single node against baseline
   * @param {Object} node - Node to verify
   * @param {string} id - Node ID (or derived)
   * @returns {Object} Verification result
   */
  verifyNode(node, id) {
    const baselineEntry = this.baseline.get(id);

    if (!baselineEntry) {
      return {
        id,
        status: VERIFICATION_STATUS.ADDED,
        severity: SEVERITY.INFO,
        message: 'New node not in baseline',
        node: { name: node.name, type: node.type }
      };
    }

    const currentHashes = this.hasher.hashAll(node);
    const diffs = this._compareHashes(baselineEntry.hashes, currentHashes);

    if (diffs.length === 0) {
      return {
        id,
        status: VERIFICATION_STATUS.SYNCED,
        severity: SEVERITY.INFO,
        message: 'Node is synchronized',
        node: { name: node.name, type: node.type }
      };
    }

    return {
      id,
      status: VERIFICATION_STATUS.DRIFTED,
      severity: this._getSeverity(diffs),
      message: `Node has drifted: ${diffs.join(', ')}`,
      diffs,
      node: { name: node.name, type: node.type },
      baseline: baselineEntry.snapshot
    };
  }

  /**
   * Compare hash objects
   * @param {Object} baseline - Baseline hashes
   * @param {Object} current - Current hashes
   * @returns {string[]} List of differing aspects
   * @private
   */
  _compareHashes(baseline, current) {
    const diffs = [];

    for (const aspect of Object.keys(baseline)) {
      if (aspect === 'combined') continue;

      if (this._shouldVerifyAspect(aspect) && baseline[aspect] !== current[aspect]) {
        diffs.push(aspect);
      }
    }

    return diffs;
  }

  /**
   * Check if aspect should be verified
   * @param {string} aspect - Aspect name
   * @returns {boolean} True if should verify
   * @private
   */
  _shouldVerifyAspect(aspect) {
    if (this.options.aspects.includes(VERIFY_ASPECTS.ALL)) {
      return true;
    }
    return this.options.aspects.includes(aspect);
  }

  /**
   * Determine severity based on diffs
   * @param {string[]} diffs - List of diffs
   * @returns {string} Severity level
   * @private
   */
  _getSeverity(diffs) {
    if (diffs.includes('structure')) return SEVERITY.ERROR;
    if (diffs.includes('content')) return SEVERITY.WARNING;
    if (diffs.includes('layout')) return SEVERITY.WARNING;
    if (diffs.includes('styling')) return SEVERITY.INFO;
    return SEVERITY.INFO;
  }

  /**
   * Verify multiple nodes
   * @param {Object[]} nodes - Nodes to verify
   * @param {Function} idGetter - Function to get ID from node
   * @returns {Object} Verification results
   */
  verifyAll(nodes, idGetter = (n) => n.id) {
    const results = [];
    const currentIds = new Set();

    // Verify each current node
    for (const node of nodes) {
      const id = idGetter(node);
      currentIds.add(id);
      results.push(this.verifyNode(node, id));
    }

    // Check for missing nodes (in baseline but not current)
    for (const baselineId of this.baseline.getIds()) {
      if (!currentIds.has(baselineId)) {
        const entry = this.baseline.get(baselineId);
        results.push({
          id: baselineId,
          status: VERIFICATION_STATUS.MISSING,
          severity: SEVERITY.ERROR,
          message: 'Node in baseline not found in current state',
          baseline: entry.snapshot
        });
      }
    }

    // Compile summary
    const summary = this._compileSummary(results);

    // Record in history
    this.verificationHistory.push({
      timestamp: Date.now(),
      summary,
      resultCount: results.length
    });

    return {
      results: results.slice(0, this.options.reportLimit),
      summary,
      truncated: results.length > this.options.reportLimit
    };
  }

  /**
   * Compile verification summary
   * @param {Object[]} results - Verification results
   * @returns {Object} Summary
   * @private
   */
  _compileSummary(results) {
    const byStatus = {};
    const bySeverity = {};

    for (const result of results) {
      byStatus[result.status] = (byStatus[result.status] || 0) + 1;
      bySeverity[result.severity] = (bySeverity[result.severity] || 0) + 1;
    }

    const total = results.length;
    const synced = byStatus[VERIFICATION_STATUS.SYNCED] || 0;

    return {
      total,
      synced,
      drifted: byStatus[VERIFICATION_STATUS.DRIFTED] || 0,
      missing: byStatus[VERIFICATION_STATUS.MISSING] || 0,
      added: byStatus[VERIFICATION_STATUS.ADDED] || 0,
      byStatus,
      bySeverity,
      syncPercentage: total > 0 ? (synced / total) * 100 : 100,
      hasErrors: (bySeverity[SEVERITY.ERROR] || 0) > 0,
      hasCritical: (bySeverity[SEVERITY.CRITICAL] || 0) > 0
    };
  }

  /**
   * Quick sync check - returns simple pass/fail
   * @param {Object[]} nodes - Nodes to check
   * @param {Function} idGetter - ID getter function
   * @returns {Object} Quick check result
   */
  quickCheck(nodes, idGetter = (n) => n.id) {
    let synced = 0;
    let drifted = 0;
    let missing = 0;
    const currentIds = new Set();

    for (const node of nodes) {
      const id = idGetter(node);
      currentIds.add(id);

      const entry = this.baseline.get(id);
      if (!entry) {
        continue; // New nodes are OK for quick check
      }

      const currentHash = this.hasher.hashAll(node).combined;
      if (entry.hashes.combined === currentHash) {
        synced++;
      } else {
        drifted++;
      }
    }

    // Count missing
    for (const baselineId of this.baseline.getIds()) {
      if (!currentIds.has(baselineId)) {
        missing++;
      }
    }

    const total = synced + drifted + missing;
    const passed = drifted === 0 && missing === 0;

    return {
      passed,
      synced,
      drifted,
      missing,
      total,
      syncRate: total > 0 ? (synced / total) * 100 : 100
    };
  }

  /**
   * Get verification history
   * @param {number} limit - Number of entries
   * @returns {Object[]} History entries
   */
  getHistory(limit = 10) {
    return this.verificationHistory.slice(-limit);
  }

  /**
   * Export current baseline
   * @returns {Object} Exported baseline
   */
  exportBaseline() {
    return this.baseline.export();
  }

  /**
   * Import baseline
   * @param {Object} data - Baseline data
   */
  importBaseline(data) {
    this.baseline.import(data);
  }

  /**
   * Get verifier statistics
   * @returns {Object} Statistics
   */
  getStats() {
    return {
      baseline: this.baseline.getStats(),
      verificationCount: this.verificationHistory.length,
      lastVerification: this.verificationHistory.length > 0
        ? this.verificationHistory[this.verificationHistory.length - 1]
        : null
    };
  }
}

// =============================================================================
// DRIFT DETECTOR
// =============================================================================

/**
 * Specialized detector for design drift
 */
class DriftDetector {
  /**
   * Create a drift detector
   * @param {Object} options - Detector options
   */
  constructor(options = {}) {
    this.options = {
      sensitivityThreshold: 0.1,  // 10% change threshold
      trackHistory: true,
      maxHistory: 100,
      ...options
    };

    this.hasher = new ContentHasher();
    this.snapshots = new Map();
    this.driftHistory = [];
  }

  /**
   * Take a snapshot of current state
   * @param {string} id - Snapshot ID
   * @param {Object[]} nodes - Nodes to snapshot
   * @returns {Object} Snapshot metadata
   */
  snapshot(id, nodes) {
    const hashes = new Map();
    let totalNodes = 0;

    for (const node of nodes) {
      if (node.id) {
        hashes.set(node.id, this.hasher.hashAll(node));
        totalNodes++;
      }
    }

    const snapshotData = {
      id,
      hashes,
      totalNodes,
      timestamp: Date.now()
    };

    this.snapshots.set(id, snapshotData);

    return {
      id,
      totalNodes,
      timestamp: snapshotData.timestamp
    };
  }

  /**
   * Detect drift between two snapshots
   * @param {string} baselineId - Baseline snapshot ID
   * @param {string} currentId - Current snapshot ID
   * @returns {Object} Drift detection result
   */
  detectDrift(baselineId, currentId) {
    const baseline = this.snapshots.get(baselineId);
    const current = this.snapshots.get(currentId);

    if (!baseline || !current) {
      return {
        error: 'Snapshot not found',
        baselineFound: !!baseline,
        currentFound: !!current
      };
    }

    const drifts = [];
    const unchanged = [];
    const added = [];
    const removed = [];

    // Check each baseline node
    for (const [nodeId, baselineHashes] of baseline.hashes) {
      const currentHashes = current.hashes.get(nodeId);

      if (!currentHashes) {
        removed.push(nodeId);
      } else if (baselineHashes.combined !== currentHashes.combined) {
        drifts.push({
          nodeId,
          changedAspects: this._findChangedAspects(baselineHashes, currentHashes)
        });
      } else {
        unchanged.push(nodeId);
      }
    }

    // Check for new nodes
    for (const nodeId of current.hashes.keys()) {
      if (!baseline.hashes.has(nodeId)) {
        added.push(nodeId);
      }
    }

    const result = {
      baselineId,
      currentId,
      driftCount: drifts.length,
      unchangedCount: unchanged.length,
      addedCount: added.length,
      removedCount: removed.length,
      drifts,
      added,
      removed,
      driftPercentage: baseline.totalNodes > 0
        ? (drifts.length / baseline.totalNodes) * 100
        : 0,
      significantDrift: drifts.length / baseline.totalNodes > this.options.sensitivityThreshold
    };

    // Track history
    if (this.options.trackHistory) {
      this.driftHistory.push({
        ...result,
        timestamp: Date.now()
      });

      if (this.driftHistory.length > this.options.maxHistory) {
        this.driftHistory = this.driftHistory.slice(-this.options.maxHistory);
      }
    }

    return result;
  }

  /**
   * Find which aspects changed between hashes
   * @param {Object} baseline - Baseline hashes
   * @param {Object} current - Current hashes
   * @returns {string[]} Changed aspects
   * @private
   */
  _findChangedAspects(baseline, current) {
    const changed = [];
    for (const aspect of ['structure', 'styling', 'content', 'layout']) {
      if (baseline[aspect] !== current[aspect]) {
        changed.push(aspect);
      }
    }
    return changed;
  }

  /**
   * Get drift trend over time
   * @returns {Object} Trend analysis
   */
  getDriftTrend() {
    if (this.driftHistory.length < 2) {
      return { trend: 'insufficient-data', dataPoints: this.driftHistory.length };
    }

    const percentages = this.driftHistory.map(h => h.driftPercentage);
    const recent = percentages.slice(-5);
    const earlier = percentages.slice(0, 5);

    const recentAvg = recent.reduce((a, b) => a + b, 0) / recent.length;
    const earlierAvg = earlier.reduce((a, b) => a + b, 0) / earlier.length;

    let trend;
    if (recentAvg > earlierAvg * 1.2) {
      trend = 'increasing';
    } else if (recentAvg < earlierAvg * 0.8) {
      trend = 'decreasing';
    } else {
      trend = 'stable';
    }

    return {
      trend,
      recentAverage: recentAvg,
      earlierAverage: earlierAvg,
      dataPoints: this.driftHistory.length
    };
  }

  /**
   * Clear snapshots and history
   */
  clear() {
    this.snapshots.clear();
    this.driftHistory = [];
  }
}

// =============================================================================
// CONVENIENCE FUNCTIONS
// =============================================================================

/**
 * Create a complete verification system
 * @param {Object} options - System options
 * @returns {Object} Verification system
 */
function createVerificationSystem(options = {}) {
  const verifier = new SyncVerifier(options.verifier);
  const driftDetector = new DriftDetector(options.drift);

  return {
    verifier,
    driftDetector,
    // Convenience methods
    setBaseline: (nodes, idGetter) => verifier.setBaseline(nodes, idGetter),
    verify: (nodes, idGetter) => verifier.verifyAll(nodes, idGetter),
    quickCheck: (nodes, idGetter) => verifier.quickCheck(nodes, idGetter),
    snapshot: (id, nodes) => driftDetector.snapshot(id, nodes),
    detectDrift: (baselineId, currentId) => driftDetector.detectDrift(baselineId, currentId)
  };
}

/**
 * Quick sync verification
 * @param {Object[]} baseline - Baseline nodes
 * @param {Object[]} current - Current nodes
 * @param {Object} options - Verification options
 * @returns {Object} Verification result
 */
function quickVerify(baseline, current, options = {}) {
  const verifier = new SyncVerifier(options);
  verifier.setBaseline(baseline);
  return verifier.quickCheck(current);
}

/**
 * Compare two node sets for drift
 * @param {Object[]} before - Before state
 * @param {Object[]} after - After state
 * @returns {Object} Comparison result
 */
function compareStates(before, after) {
  const detector = new DriftDetector();
  detector.snapshot('before', before);
  detector.snapshot('after', after);
  return detector.detectDrift('before', 'after');
}

// =============================================================================
// EXPORTS
// =============================================================================

module.exports = {
  // Classes
  ContentHasher,
  SyncBaseline,
  SyncVerifier,
  DriftDetector,
  // Constants
  VERIFICATION_STATUS,
  SEVERITY,
  VERIFY_ASPECTS,
  DEFAULT_OPTIONS,
  // Factory functions
  createVerificationSystem,
  // Convenience functions
  quickVerify,
  compareStates
};
