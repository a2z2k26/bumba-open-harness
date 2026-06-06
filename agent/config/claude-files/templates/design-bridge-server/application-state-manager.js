/**
 * Application State Manager
 * Sprint 34: Central application state management
 *
 * Manages global application state with:
 * - State persistence
 * - Subscriptions
 * - History tracking
 * - Snapshots
 * - Time-travel debugging
 *
 * Note: Different from component-level StateManager (Sprint 3)
 * This manages application-wide state for the design bridge
 */

const EventEmitter = require('events');
const fs = require('fs').promises;
const path = require('path');

class ApplicationStateManager extends EventEmitter {
  constructor(options = {}) {
    super();

    this.options = {
      persistState: options.persistState !== false,
      stateFile: options.stateFile || path.join(process.cwd(), '.design/application-state.json'),
      maxHistorySize: options.maxHistorySize || 50,
      enableSnapshots: options.enableSnapshots !== false,
      ...options
    };

    // Current state
    this.state = this.initializeState();

    // State history for time-travel
    this.history = [];
    this.historyIndex = -1;

    // Subscribers
    this.subscribers = new Map();

    // Snapshots
    this.snapshots = new Map();

    // Load persisted state
    if (this.options.persistState) {
      this.loadState().catch(err => {
        console.warn('Failed to load persisted state:', err.message);
      });
    }
  }

  /**
   * Initialize default state structure
   */
  initializeState() {
    return {
      // Design data
      design: {
        tokens: {},
        components: [],
        catalog: {},
        lastSync: null
      },

      // Generation state
      generation: {
        inProgress: false,
        currentFramework: null,
        progress: 0,
        results: []
      },

      // Validation state
      validation: {
        schemaValid: true,
        tokenValid: true,
        errors: [],
        warnings: []
      },

      // Export state
      export: {
        format: 'typescript',
        outputDir: null,
        lastExport: null
      },

      // UI state
      ui: {
        selectedComponent: null,
        selectedCategory: null,
        view: 'catalog'
      },

      // Settings
      settings: {
        framework: 'react',
        styleFormat: 'css',
        typescript: true,
        validation: 'standard'
      },

      // Metadata
      metadata: {
        version: '1.0.0',
        lastUpdated: new Date().toISOString(),
        sessionId: this.generateSessionId()
      }
    };
  }

  /**
   * Get current state
   */
  getState(path) {
    if (!path) return { ...this.state };

    const parts = path.split('.');
    let value = this.state;

    for (const part of parts) {
      if (value && typeof value === 'object') {
        value = value[part];
      } else {
        return undefined;
      }
    }

    return value;
  }

  /**
   * Set state
   */
  setState(path, value, options = {}) {
    const oldState = { ...this.state };

    // Update state
    if (typeof path === 'string') {
      this.setNestedValue(this.state, path, value);
    } else {
      // Merge object
      this.state = { ...this.state, ...path };
    }

    // Update metadata
    this.state.metadata.lastUpdated = new Date().toISOString();

    // Add to history
    if (!options.skipHistory) {
      this.addToHistory(oldState);
    }

    // Emit state change
    this.emit('state:changed', {
      path,
      value,
      oldState,
      newState: this.state,
      timestamp: new Date().toISOString()
    });

    // Notify subscribers
    this.notifySubscribers(path, value, oldState);

    // Persist state
    if (this.options.persistState && !options.skipPersist) {
      this.persistState().catch(err => {
        console.error('Failed to persist state:', err);
      });
    }

    return this.state;
  }

  /**
   * Update state (partial update)
   */
  updateState(path, updates) {
    const currentValue = this.getState(path);

    if (typeof currentValue === 'object' && !Array.isArray(currentValue)) {
      return this.setState(path, { ...currentValue, ...updates });
    }

    throw new Error(`Cannot update non-object value at path: ${path}`);
  }

  /**
   * Reset state to initial
   */
  resetState() {
    const oldState = { ...this.state };
    this.state = this.initializeState();

    this.emit('state:reset', {
      oldState,
      newState: this.state,
      timestamp: new Date().toISOString()
    });

    this.history = [];
    this.historyIndex = -1;

    return this.state;
  }

  /**
   * Subscribe to state changes
   */
  subscribe(path, callback) {
    const subscriptionId = `sub_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

    this.subscribers.set(subscriptionId, {
      path,
      callback,
      createdAt: new Date().toISOString()
    });

    this.emit('subscription:added', { subscriptionId, path });

    // Return unsubscribe function
    return () => this.unsubscribe(subscriptionId);
  }

  /**
   * Unsubscribe from state changes
   */
  unsubscribe(subscriptionId) {
    const removed = this.subscribers.delete(subscriptionId);

    if (removed) {
      this.emit('subscription:removed', { subscriptionId });
    }

    return removed;
  }

  /**
   * Notify subscribers of state changes
   */
  notifySubscribers(path, value, oldState) {
    this.subscribers.forEach((subscription, subscriptionId) => {
      // Notify if subscription matches path or is a parent path
      if (!subscription.path || path.startsWith(subscription.path)) {
        try {
          subscription.callback({
            path,
            value,
            oldValue: this.getNestedValue(oldState, path),
            state: this.state
          });
        } catch (error) {
          console.error(`Subscriber error (${subscriptionId}):`, error);
        }
      }
    });
  }

  /**
   * Add state to history
   */
  addToHistory(state) {
    // Remove future history if we're not at the end
    if (this.historyIndex < this.history.length - 1) {
      this.history = this.history.slice(0, this.historyIndex + 1);
    }

    // Add to history
    this.history.push({
      state: JSON.parse(JSON.stringify(state)),
      timestamp: new Date().toISOString()
    });

    // Limit history size
    if (this.history.length > this.options.maxHistorySize) {
      this.history.shift();
    } else {
      this.historyIndex++;
    }

    this.emit('history:added', {
      size: this.history.length,
      index: this.historyIndex
    });
  }

  /**
   * Undo state change
   */
  undo() {
    if (this.historyIndex > 0) {
      this.historyIndex--;
      const previousState = this.history[this.historyIndex].state;

      this.state = JSON.parse(JSON.stringify(previousState));

      this.emit('state:undo', {
        index: this.historyIndex,
        timestamp: new Date().toISOString()
      });

      return this.state;
    }

    return null;
  }

  /**
   * Redo state change
   */
  redo() {
    if (this.historyIndex < this.history.length - 1) {
      this.historyIndex++;
      const nextState = this.history[this.historyIndex].state;

      this.state = JSON.parse(JSON.stringify(nextState));

      this.emit('state:redo', {
        index: this.historyIndex,
        timestamp: new Date().toISOString()
      });

      return this.state;
    }

    return null;
  }

  /**
   * Create state snapshot
   */
  createSnapshot(name) {
    if (!this.options.enableSnapshots) {
      throw new Error('Snapshots are disabled');
    }

    const snapshotId = name || `snapshot_${Date.now()}`;

    this.snapshots.set(snapshotId, {
      state: JSON.parse(JSON.stringify(this.state)),
      timestamp: new Date().toISOString()
    });

    this.emit('snapshot:created', { id: snapshotId });

    return snapshotId;
  }

  /**
   * Restore state snapshot
   */
  restoreSnapshot(snapshotId) {
    const snapshot = this.snapshots.get(snapshotId);

    if (!snapshot) {
      throw new Error(`Snapshot not found: ${snapshotId}`);
    }

    const oldState = { ...this.state };
    this.state = JSON.parse(JSON.stringify(snapshot.state));

    this.emit('snapshot:restored', {
      id: snapshotId,
      timestamp: new Date().toISOString()
    });

    this.emit('state:changed', {
      path: null,
      value: this.state,
      oldState,
      newState: this.state,
      timestamp: new Date().toISOString()
    });

    return this.state;
  }

  /**
   * List snapshots
   */
  listSnapshots() {
    return Array.from(this.snapshots.entries()).map(([id, snapshot]) => ({
      id,
      timestamp: snapshot.timestamp
    }));
  }

  /**
   * Delete snapshot
   */
  deleteSnapshot(snapshotId) {
    const deleted = this.snapshots.delete(snapshotId);

    if (deleted) {
      this.emit('snapshot:deleted', { id: snapshotId });
    }

    return deleted;
  }

  /**
   * Persist state to file
   */
  async persistState() {
    try {
      const stateDir = path.dirname(this.options.stateFile);
      await fs.mkdir(stateDir, { recursive: true });

      const data = JSON.stringify({
        state: this.state,
        metadata: {
          version: '1.0.0',
          savedAt: new Date().toISOString()
        }
      }, null, 2);

      await fs.writeFile(this.options.stateFile, data, 'utf8');

      this.emit('state:persisted', {
        file: this.options.stateFile,
        timestamp: new Date().toISOString()
      });

      return true;
    } catch (error) {
      this.emit('persist:error', { error: error.message });
      throw error;
    }
  }

  /**
   * Load state from file
   */
  async loadState() {
    try {
      const data = await fs.readFile(this.options.stateFile, 'utf8');
      const loaded = JSON.parse(data);

      this.state = loaded.state;

      this.emit('state:loaded', {
        file: this.options.stateFile,
        timestamp: new Date().toISOString()
      });

      return this.state;
    } catch (error) {
      if (error.code !== 'ENOENT') {
        this.emit('load:error', { error: error.message });
      }
      return null;
    }
  }

  /**
   * Helper: Set nested value
   */
  setNestedValue(obj, path, value) {
    const parts = path.split('.');
    const last = parts.pop();
    let current = obj;

    for (const part of parts) {
      if (!current[part] || typeof current[part] !== 'object') {
        current[part] = {};
      }
      current = current[part];
    }

    current[last] = value;
  }

  /**
   * Helper: Get nested value
   */
  getNestedValue(obj, path) {
    if (!path) return obj;

    const parts = path.split('.');
    let value = obj;

    for (const part of parts) {
      if (value && typeof value === 'object') {
        value = value[part];
      } else {
        return undefined;
      }
    }

    return value;
  }

  /**
   * Helper: Generate session ID
   */
  generateSessionId() {
    return `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }

  /**
   * Get state statistics
   */
  getStats() {
    return {
      historySize: this.history.length,
      historyIndex: this.historyIndex,
      snapshotCount: this.snapshots.size,
      subscriberCount: this.subscribers.size,
      sessionId: this.state.metadata.sessionId,
      lastUpdated: this.state.metadata.lastUpdated
    };
  }
}

// Singleton instance
let applicationStateInstance = null;

function getApplicationStateManager(options = {}) {
  if (!applicationStateInstance) {
    applicationStateInstance = new ApplicationStateManager(options);
  }
  return applicationStateInstance;
}

module.exports = ApplicationStateManager;
module.exports.getApplicationStateManager = getApplicationStateManager;
