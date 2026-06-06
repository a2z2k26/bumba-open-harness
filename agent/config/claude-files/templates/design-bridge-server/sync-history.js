/**
 * Sync History Manager
 * Sprint 41: Persistent sync history tracking and analysis
 *
 * Tracks all sync operations with detailed metadata, provides querying,
 * filtering, export capabilities, and retention management.
 */

const fs = require('fs').promises;
const path = require('path');
const EventEmitter = require('events');
const crypto = require('crypto');

// Make chalk optional (graceful degradation for environments without chalk)
let chalk;
try {
  chalk = require('chalk');
} catch (e) {
  // Create a no-op proxy that returns input string for any color method
  chalk = new Proxy({}, {
    get: () => (str) => str
  });
}

// Make logger optional (graceful degradation)
let logger;
try {
  logger = require('../logging').logger;
} catch (e) {
  // Fallback to console-based logger
  logger = {
    info: (...args) => console.log('[INFO]', ...args),
    error: (...args) => console.error('[ERROR]', ...args),
    warn: (...args) => console.warn('[WARN]', ...args),
    debug: () => {} // Silent debug by default
  };
}

/**
 * Sync Event Status
 */
const SyncEventStatus = {
  STARTED: 'started',
  COMPLETED: 'completed',
  FAILED: 'failed',
  DEBOUNCED: 'debounced',
  RATE_LIMITED: 'rate_limited',
  CANCELLED: 'cancelled',
  RETRY_SCHEDULED: 'retry_scheduled'
};

/**
 * Sync Event Trigger Type
 */
const SyncTriggerType = {
  WEBHOOK: 'webhook',
  MANUAL: 'manual',
  SCHEDULED: 'scheduled',
  RETRY: 'retry',
  SYSTEM: 'system'
};

/**
 * Sync Event
 * Represents a single sync operation
 */
class SyncEvent {
  constructor(data = {}) {
    this.id = data.id || `sync_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    this.fileKey = data.fileKey;
    this.trigger = data.trigger || SyncTriggerType.MANUAL;
    this.eventType = data.eventType;
    this.status = data.status || SyncEventStatus.STARTED;
    this.startedAt = data.startedAt || new Date().toISOString();
    this.completedAt = data.completedAt || null;
    this.duration = data.duration || null;
    this.retryCount = data.retryCount || 0;

    // Results
    this.changes = data.changes || null;
    this.error = data.error || null;
    this.conflictsDetected = data.conflictsDetected || 0;
    this.conflictsResolved = data.conflictsResolved || 0;

    // Metadata
    this.metadata = data.metadata || {};
    this.user = data.user || 'system';
    this.version = data.version || '1.0';
  }

  toJSON() {
    return {
      id: this.id,
      fileKey: this.fileKey,
      trigger: this.trigger,
      eventType: this.eventType,
      status: this.status,
      startedAt: this.startedAt,
      completedAt: this.completedAt,
      duration: this.duration,
      retryCount: this.retryCount,
      changes: this.changes,
      error: this.error,
      conflictsDetected: this.conflictsDetected,
      conflictsResolved: this.conflictsResolved,
      metadata: this.metadata,
      user: this.user,
      version: this.version
    };
  }

  /**
   * Mark event as completed
   */
  complete(duration, changes = null) {
    this.status = SyncEventStatus.COMPLETED;
    this.completedAt = new Date().toISOString();
    this.duration = duration;
    this.changes = changes;
    return this;
  }

  /**
   * Mark event as failed
   */
  fail(error, duration = null) {
    this.status = SyncEventStatus.FAILED;
    this.completedAt = new Date().toISOString();
    this.duration = duration;
    this.error = error;
    return this;
  }

  /**
   * Add conflict information
   */
  addConflictInfo(detected, resolved) {
    this.conflictsDetected = detected;
    this.conflictsResolved = resolved;
    return this;
  }
}

/**
 * Sync History Manager
 * Manages persistent storage and querying of sync events
 */
class SyncHistoryManager extends EventEmitter {
  constructor(options = {}) {
    super();

    this.storageDir = options.storageDir || '.design/history';
    this.storageFile = path.join(this.storageDir, 'sync-history.json');
    this.maxMemoryEvents = options.maxMemoryEvents || 1000;
    this.retentionDays = options.retentionDays || 30;
    this.autoSave = options.autoSave !== false; // Default true
    this.autoCleanup = options.autoCleanup !== false; // Default true

    // In-memory cache
    this.events = [];
    this.eventIndex = new Map(); // id -> event

    // Statistics
    this.stats = {
      totalEvents: 0,
      successfulSyncs: 0,
      failedSyncs: 0,
      totalDuration: 0,
      totalConflicts: 0,
      totalConflictsResolved: 0,
      byTrigger: {},
      byFileKey: {},
      lastSync: null
    };

    this.isLoaded = false;
  }

  /**
   * Initialize - load history from disk
   */
  async initialize() {
    logger.info('Initializing sync history manager');

    try {
      // Ensure storage directory exists
      await fs.mkdir(this.storageDir, { recursive: true });

      // Load existing history
      await this.load();

      // Start auto-cleanup if enabled
      if (this.autoCleanup) {
        this.startAutoCleanup();
      }

      this.isLoaded = true;
      logger.info(`Sync history loaded: ${this.events.length} events`);

    } catch (error) {
      logger.error('Failed to initialize sync history:', error);
      throw error;
    }
  }

  /**
   * Load history from disk
   */
  async load() {
    try {
      const data = await fs.readFile(this.storageFile, 'utf8');
      const parsed = JSON.parse(data);

      this.events = parsed.events.map(e => new SyncEvent(e));
      this.stats = parsed.stats || this.stats;

      // Build index
      this.eventIndex.clear();
      for (const event of this.events) {
        this.eventIndex.set(event.id, event);
      }

      logger.debug(`Loaded ${this.events.length} sync events from disk`);

    } catch (error) {
      if (error.code === 'ENOENT') {
        // File doesn't exist yet
        logger.debug('No existing sync history file found, starting fresh');
        this.events = [];
      } else {
        logger.error('Error loading sync history:', error);
        throw error;
      }
    }
  }

  /**
   * Save history to disk
   */
  async save() {
    try {
      const data = {
        version: '1.0',
        savedAt: new Date().toISOString(),
        events: this.events.map(e => e.toJSON()),
        stats: this.stats
      };

      await fs.writeFile(
        this.storageFile,
        JSON.stringify(data, null, 2),
        'utf8'
      );

      logger.debug('Sync history saved to disk');

    } catch (error) {
      logger.error('Error saving sync history:', error);
      throw error;
    }
  }

  /**
   * Record a new sync event
   */
  async recordEvent(eventData) {
    const event = new SyncEvent(eventData);

    // Add to memory
    this.events.push(event);
    this.eventIndex.set(event.id, event);

    // Update statistics
    this.updateStats(event);

    // Trim memory if needed
    this.trimMemory();

    // Auto-save if enabled
    if (this.autoSave) {
      await this.save();
    }

    this.emit('event:recorded', event);

    return event;
  }

  /**
   * Update an existing event
   */
  async updateEvent(eventId, updates) {
    const event = this.eventIndex.get(eventId);

    if (!event) {
      throw new Error(`Event not found: ${eventId}`);
    }

    // Apply updates
    Object.assign(event, updates);

    // Update statistics if status changed
    if (updates.status) {
      this.updateStats(event);
    }

    // Auto-save if enabled
    if (this.autoSave) {
      await this.save();
    }

    this.emit('event:updated', event);

    return event;
  }

  /**
   * Get event by ID
   */
  getEvent(eventId) {
    return this.eventIndex.get(eventId);
  }

  /**
   * Get events with optional filtering
   */
  getEvents(options = {}) {
    const {
      fileKey = null,
      trigger = null,
      status = null,
      startDate = null,
      endDate = null,
      limit = 50,
      offset = 0,
      sortBy = 'startedAt',
      sortOrder = 'desc'
    } = options;

    let filtered = [...this.events];

    // Apply filters
    if (fileKey) {
      filtered = filtered.filter(e => e.fileKey === fileKey);
    }

    if (trigger) {
      filtered = filtered.filter(e => e.trigger === trigger);
    }

    if (status) {
      filtered = filtered.filter(e => e.status === status);
    }

    if (startDate) {
      const start = new Date(startDate).getTime();
      filtered = filtered.filter(e => new Date(e.startedAt).getTime() >= start);
    }

    if (endDate) {
      const end = new Date(endDate).getTime();
      filtered = filtered.filter(e => new Date(e.startedAt).getTime() <= end);
    }

    // Sort
    filtered.sort((a, b) => {
      const aVal = a[sortBy];
      const bVal = b[sortBy];

      if (sortOrder === 'desc') {
        return aVal > bVal ? -1 : aVal < bVal ? 1 : 0;
      } else {
        return aVal < bVal ? -1 : aVal > bVal ? 1 : 0;
      }
    });

    // Paginate
    const paginated = filtered.slice(offset, offset + limit);

    return {
      events: paginated,
      total: filtered.length,
      limit,
      offset
    };
  }

  /**
   * Get recent events
   */
  getRecentEvents(limit = 10) {
    return this.events
      .slice(-limit)
      .reverse()
      .map(e => e.toJSON());
  }

  /**
   * Get events for a specific file
   */
  getFileEvents(fileKey, limit = 20) {
    return this.events
      .filter(e => e.fileKey === fileKey)
      .slice(-limit)
      .reverse()
      .map(e => e.toJSON());
  }

  /**
   * Get failed events
   */
  getFailedEvents(limit = 50) {
    return this.events
      .filter(e => e.status === SyncEventStatus.FAILED)
      .slice(-limit)
      .reverse()
      .map(e => e.toJSON());
  }

  /**
   * Get statistics
   */
  getStatistics(options = {}) {
    const { fileKey = null, startDate = null, endDate = null } = options;

    if (!fileKey && !startDate && !endDate) {
      // Return global stats
      return {
        ...this.stats,
        averageDuration: this.stats.successfulSyncs > 0
          ? Math.round(this.stats.totalDuration / this.stats.successfulSyncs)
          : 0,
        successRate: this.stats.totalEvents > 0
          ? ((this.stats.successfulSyncs / this.stats.totalEvents) * 100).toFixed(2) + '%'
          : '0%',
        conflictResolutionRate: this.stats.totalConflicts > 0
          ? ((this.stats.totalConflictsResolved / this.stats.totalConflicts) * 100).toFixed(2) + '%'
          : '0%'
      };
    }

    // Calculate stats for filtered events
    let filtered = [...this.events];

    if (fileKey) {
      filtered = filtered.filter(e => e.fileKey === fileKey);
    }

    if (startDate) {
      const start = new Date(startDate).getTime();
      filtered = filtered.filter(e => new Date(e.startedAt).getTime() >= start);
    }

    if (endDate) {
      const end = new Date(endDate).getTime();
      filtered = filtered.filter(e => new Date(e.startedAt).getTime() <= end);
    }

    // Calculate filtered stats
    const stats = {
      totalEvents: filtered.length,
      successfulSyncs: filtered.filter(e => e.status === SyncEventStatus.COMPLETED).length,
      failedSyncs: filtered.filter(e => e.status === SyncEventStatus.FAILED).length,
      totalDuration: filtered.reduce((sum, e) => sum + (e.duration || 0), 0),
      totalConflicts: filtered.reduce((sum, e) => sum + (e.conflictsDetected || 0), 0),
      totalConflictsResolved: filtered.reduce((sum, e) => sum + (e.conflictsResolved || 0), 0)
    };

    stats.averageDuration = stats.successfulSyncs > 0
      ? Math.round(stats.totalDuration / stats.successfulSyncs)
      : 0;

    stats.successRate = stats.totalEvents > 0
      ? ((stats.successfulSyncs / stats.totalEvents) * 100).toFixed(2) + '%'
      : '0%';

    stats.conflictResolutionRate = stats.totalConflicts > 0
      ? ((stats.totalConflictsResolved / stats.totalConflicts) * 100).toFixed(2) + '%'
      : '0%';

    return stats;
  }

  /**
   * Update statistics
   */
  updateStats(event) {
    this.stats.totalEvents = this.events.length;
    this.stats.lastSync = event.startedAt;

    if (event.status === SyncEventStatus.COMPLETED) {
      this.stats.successfulSyncs++;
      if (event.duration) {
        this.stats.totalDuration += event.duration;
      }
    } else if (event.status === SyncEventStatus.FAILED) {
      this.stats.failedSyncs++;
    }

    if (event.conflictsDetected > 0) {
      this.stats.totalConflicts += event.conflictsDetected;
      this.stats.totalConflictsResolved += event.conflictsResolved || 0;
    }

    // Track by trigger
    if (!this.stats.byTrigger[event.trigger]) {
      this.stats.byTrigger[event.trigger] = 0;
    }
    this.stats.byTrigger[event.trigger]++;

    // Track by file
    if (event.fileKey) {
      if (!this.stats.byFileKey[event.fileKey]) {
        this.stats.byFileKey[event.fileKey] = 0;
      }
      this.stats.byFileKey[event.fileKey]++;
    }
  }

  /**
   * Cleanup old events (retention policy)
   */
  async cleanup() {
    const cutoff = Date.now() - (this.retentionDays * 24 * 60 * 60 * 1000);
    const before = this.events.length;

    this.events = this.events.filter(e => {
      const eventTime = new Date(e.startedAt).getTime();
      return eventTime >= cutoff;
    });

    // Rebuild index
    this.eventIndex.clear();
    for (const event of this.events) {
      this.eventIndex.set(event.id, event);
    }

    const removed = before - this.events.length;

    if (removed > 0) {
      logger.info(`Cleaned up ${removed} old sync events (retention: ${this.retentionDays} days)`);
      await this.save();
    }

    return removed;
  }

  /**
   * Start automatic cleanup (daily)
   */
  startAutoCleanup() {
    // Run cleanup every 24 hours
    this.cleanupInterval = setInterval(async () => {
      try {
        await this.cleanup();
      } catch (error) {
        logger.error('Error during auto-cleanup:', error);
      }
    }, 24 * 60 * 60 * 1000);

    logger.debug('Auto-cleanup started (daily)');
  }

  /**
   * Stop automatic cleanup
   */
  stopAutoCleanup() {
    if (this.cleanupInterval) {
      clearInterval(this.cleanupInterval);
      this.cleanupInterval = null;
      logger.debug('Auto-cleanup stopped');
    }
  }

  /**
   * Trim in-memory events to max size
   */
  trimMemory() {
    if (this.events.length > this.maxMemoryEvents) {
      const removed = this.events.length - this.maxMemoryEvents;
      const trimmed = this.events.slice(0, removed);

      // Remove from index
      for (const event of trimmed) {
        this.eventIndex.delete(event.id);
      }

      this.events = this.events.slice(removed);

      logger.debug(`Trimmed ${removed} events from memory (max: ${this.maxMemoryEvents})`);
    }
  }

  /**
   * Export history to JSON
   */
  async exportToJSON(filePath, options = {}) {
    const events = this.getEvents(options);

    const exportData = {
      version: '1.0',
      exportedAt: new Date().toISOString(),
      filter: options,
      stats: this.getStatistics(options),
      events: events.events.map(e => e.toJSON())
    };

    await fs.writeFile(filePath, JSON.stringify(exportData, null, 2), 'utf8');

    logger.info(`Exported ${events.events.length} events to ${filePath}`);

    return exportData;
  }

  /**
   * Export history to CSV
   */
  async exportToCSV(filePath, options = {}) {
    const events = this.getEvents(options);

    // CSV header
    const headers = [
      'ID',
      'File Key',
      'Trigger',
      'Event Type',
      'Status',
      'Started At',
      'Completed At',
      'Duration (ms)',
      'Retry Count',
      'Conflicts Detected',
      'Conflicts Resolved',
      'Error'
    ];

    // CSV rows
    const rows = events.events.map(e => [
      e.id,
      e.fileKey || '',
      e.trigger,
      e.eventType || '',
      e.status,
      e.startedAt,
      e.completedAt || '',
      e.duration || '',
      e.retryCount,
      e.conflictsDetected,
      e.conflictsResolved,
      e.error || ''
    ]);

    // Build CSV
    const csv = [
      headers.join(','),
      ...rows.map(row => row.map(cell => `"${cell}"`).join(','))
    ].join('\n');

    await fs.writeFile(filePath, csv, 'utf8');

    logger.info(`Exported ${events.events.length} events to ${filePath}`);

    return csv;
  }

  /**
   * Clear all history
   */
  async clear() {
    this.events = [];
    this.eventIndex.clear();
    this.stats = {
      totalEvents: 0,
      successfulSyncs: 0,
      failedSyncs: 0,
      totalDuration: 0,
      totalConflicts: 0,
      totalConflictsResolved: 0,
      byTrigger: {},
      byFileKey: {},
      lastSync: null
    };

    await this.save();

    logger.info('Sync history cleared');
    this.emit('history:cleared');
  }

  /**
   * Shutdown - cleanup and save
   */
  async shutdown() {
    this.stopAutoCleanup();
    await this.save();
    logger.info('Sync history manager shutdown complete');
  }

  /**
   * Calculate hash for data object (used for checksum comparison)
   */
  calculateHash(data) {
    if (data === null || data === undefined) {
      return crypto.createHash('sha256').update('null').digest('hex');
    }

    // Helper to recursively sort object keys
    const sortObject = (obj) => {
      if (obj === null || obj === undefined) return obj;
      if (Array.isArray(obj)) {
        return obj.map(item => sortObject(item));
      }
      if (typeof obj === 'object') {
        const sorted = {};
        Object.keys(obj).sort().forEach(key => {
          sorted[key] = sortObject(obj[key]);
        });
        return sorted;
      }
      return obj;
    };

    let str;
    if (typeof data === 'object' && !Array.isArray(data)) {
      // Recursively sort all keys for consistent hashing
      const sorted = sortObject(data);
      str = JSON.stringify(sorted);
    } else if (Array.isArray(data)) {
      // Sort arrays too for consistency
      str = JSON.stringify(data.map(item => sortObject(item)));
    } else {
      // Direct stringify for primitives
      str = JSON.stringify(data);
    }

    return crypto.createHash('sha256').update(str).digest('hex');
  }

  /**
   * Detect changes between current and previous data using checksums
   * Sprint 5-6: Implement checksum-based diff detection
   */
  detectChanges(currentData, previousData) {
    const changes = {
      added: [],
      modified: [],
      removed: [],
      unchanged: [],
      summary: {
        totalComponents: 0,
        addedCount: 0,
        modifiedCount: 0,
        removedCount: 0,
        unchangedCount: 0
      }
    };

    // Handle null/undefined cases
    if (!previousData || !previousData.tokens) {
      // Everything is new
      if (currentData && currentData.tokens) {
        const components = currentData.components || [];
        changes.added = components.map(c => ({
          id: c.id,
          name: c.name,
          type: c.type,
          checksum: this.calculateHash(c)
        }));
        changes.summary.totalComponents = components.length;
        changes.summary.addedCount = components.length;
      }
      return changes;
    }

    if (!currentData || !currentData.tokens) {
      // Everything is removed
      const components = previousData.components || [];
      changes.removed = components.map(c => ({
        id: c.id,
        name: c.name,
        type: c.type,
        checksum: this.calculateHash(c)
      }));
      changes.summary.totalComponents = 0;
      changes.summary.removedCount = components.length;
      return changes;
    }

    // Build maps for comparison
    const currentComponents = currentData.components || [];
    const previousComponents = previousData.components || [];

    const currentMap = new Map();
    const previousMap = new Map();
    const currentChecksums = new Map();
    const previousChecksums = new Map();

    // Calculate checksums for current components
    currentComponents.forEach(component => {
      const checksum = this.calculateHash(component);
      currentMap.set(component.id, component);
      currentChecksums.set(component.id, checksum);
    });

    // Calculate checksums for previous components
    previousComponents.forEach(component => {
      const checksum = this.calculateHash(component);
      previousMap.set(component.id, component);
      previousChecksums.set(component.id, checksum);
    });

    // Detect changes
    currentComponents.forEach(component => {
      const id = component.id;
      const currentChecksum = currentChecksums.get(id);
      const previousChecksum = previousChecksums.get(id);

      if (!previousMap.has(id)) {
        // New component
        changes.added.push({
          id,
          name: component.name,
          type: component.type,
          checksum: currentChecksum
        });
      } else if (currentChecksum !== previousChecksum) {
        // Modified component
        changes.modified.push({
          id,
          name: component.name,
          type: component.type,
          previousChecksum,
          currentChecksum,
          changes: this.detectFieldChanges(component, previousMap.get(id))
        });
      } else {
        // Unchanged component
        changes.unchanged.push({
          id,
          name: component.name,
          type: component.type,
          checksum: currentChecksum
        });
      }
    });

    // Detect removed components
    previousComponents.forEach(component => {
      if (!currentMap.has(component.id)) {
        changes.removed.push({
          id: component.id,
          name: component.name,
          type: component.type,
          checksum: previousChecksums.get(component.id)
        });
      }
    });

    // Also check token changes
    const tokenChanges = this.detectTokenChanges(
      currentData.tokens,
      previousData.tokens
    );

    // Merge token changes into the response
    if (tokenChanges.hasChanges) {
      changes.tokenChanges = tokenChanges;
    }

    // Update summary
    changes.summary = {
      totalComponents: currentComponents.length,
      addedCount: changes.added.length,
      modifiedCount: changes.modified.length,
      removedCount: changes.removed.length,
      unchangedCount: changes.unchanged.length,
      hasTokenChanges: tokenChanges.hasChanges || false
    };

    return changes;
  }

  /**
   * Detect specific field changes within a component
   */
  detectFieldChanges(current, previous) {
    const fieldChanges = [];
    const allKeys = new Set([
      ...Object.keys(current || {}),
      ...Object.keys(previous || {})
    ]);

    allKeys.forEach(key => {
      // Skip id field
      if (key === 'id') return;

      const currentValue = current ? current[key] : undefined;
      const previousValue = previous ? previous[key] : undefined;

      const currentHash = this.calculateHash(currentValue);
      const previousHash = this.calculateHash(previousValue);

      if (currentHash !== previousHash) {
        fieldChanges.push({
          field: key,
          previousValue: previousValue,
          currentValue: currentValue
        });
      }
    });

    return fieldChanges;
  }

  /**
   * Detect token changes (colors, typography, spacing, etc.)
   */
  detectTokenChanges(currentTokens, previousTokens) {
    const tokenChanges = {
      hasChanges: false,
      colors: { added: [], modified: [], removed: [] },
      typography: { added: [], modified: [], removed: [] },
      spacing: { added: [], modified: [], removed: [] },
      effects: { added: [], modified: [], removed: [] }
    };

    if (!previousTokens) {
      tokenChanges.hasChanges = true;
      return tokenChanges;
    }

    // Check each token category
    ['colors', 'typography', 'spacing', 'effects'].forEach(category => {
      const current = currentTokens ? currentTokens[category] : {};
      const previous = previousTokens ? previousTokens[category] : {};

      // Handle nested values (like spacing.values) - check both exist before accessing
      const currentValues = (category === 'spacing' && current && current.values) ? current.values : current || {};
      const previousValues = (category === 'spacing' && previous && previous.values) ? previous.values : previous || {};

      if (typeof currentValues === 'object' && typeof previousValues === 'object') {
        const currentKeys = Object.keys(currentValues || {});
        const previousKeys = Object.keys(previousValues || {});
        const allKeys = new Set([...currentKeys, ...previousKeys]);

        allKeys.forEach(key => {
          const currentHash = this.calculateHash(currentValues[key]);
          const previousHash = this.calculateHash(previousValues[key]);

          if (!previousValues.hasOwnProperty(key)) {
            tokenChanges[category].added.push(key);
            tokenChanges.hasChanges = true;
          } else if (!currentValues.hasOwnProperty(key)) {
            tokenChanges[category].removed.push(key);
            tokenChanges.hasChanges = true;
          } else if (currentHash !== previousHash) {
            tokenChanges[category].modified.push(key);
            tokenChanges.hasChanges = true;
          }
        });
      }
    });

    return tokenChanges;
  }

  /**
   * Store checksums for future comparison
   */
  async storeChecksums(data) {
    const checksums = {
      timestamp: new Date().toISOString(),
      tokens: {},
      components: {}
    };

    // Store token checksums
    if (data.tokens) {
      ['colors', 'typography', 'spacing', 'effects'].forEach(category => {
        if (data.tokens[category]) {
          checksums.tokens[category] = this.calculateHash(data.tokens[category]);
        }
      });
    }

    // Store component checksums
    if (data.components) {
      data.components.forEach(component => {
        checksums.components[component.id] = this.calculateHash(component);
      });
    }

    // Save to disk
    const checksumFile = path.join(this.storageDir, 'checksums.json');
    await fs.writeFile(checksumFile, JSON.stringify(checksums, null, 2), 'utf8');

    return checksums;
  }

  /**
   * Load previous checksums
   */
  async loadChecksums() {
    try {
      const checksumFile = path.join(this.storageDir, 'checksums.json');
      const data = await fs.readFile(checksumFile, 'utf8');
      return JSON.parse(data);
    } catch (error) {
      // No previous checksums
      return null;
    }
  }
}

module.exports = SyncHistoryManager;
module.exports.SyncEvent = SyncEvent;
module.exports.SyncEventStatus = SyncEventStatus;
module.exports.SyncTriggerType = SyncTriggerType;
