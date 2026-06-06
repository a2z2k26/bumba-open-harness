/**
 * Design Bridge - Watch Mode & Live Sync
 * Phase 7, Sprint 7.3
 *
 * Provides real-time file watching and synchronization:
 * - File system watching with debouncing
 * - Figma webhook integration
 * - Live reload capabilities
 * - Incremental sync
 * - Change detection and diff
 */

const EventEmitter = require('events');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');

// Watch event types
const WATCH_EVENTS = {
  FILE_ADDED: 'file:added',
  FILE_CHANGED: 'file:changed',
  FILE_DELETED: 'file:deleted',
  DIR_ADDED: 'dir:added',
  DIR_DELETED: 'dir:deleted',
  FIGMA_UPDATE: 'figma:update',
  SYNC_STARTED: 'sync:started',
  SYNC_COMPLETE: 'sync:complete',
  SYNC_ERROR: 'sync:error'
};

// Default watch options
const DEFAULT_OPTIONS = {
  debounceMs: 300,
  ignorePatterns: [
    '**/node_modules/**',
    '**/.git/**',
    '**/dist/**',
    '**/build/**',
    '**/*.log',
    '**/.DS_Store'
  ],
  persistent: true,
  recursive: true,
  followSymlinks: false,
  atomicWrites: true,
  pollInterval: 1000,
  usePolling: false
};

// File types to watch
const WATCHABLE_EXTENSIONS = [
  '.js', '.jsx', '.ts', '.tsx',
  '.vue', '.svelte',
  '.css', '.scss', '.less',
  '.json', '.yaml', '.yml'
];

/**
 * File change tracker
 */
class ChangeTracker {
  constructor() {
    this.changes = new Map();
    this.hashes = new Map();
  }

  /**
   * Track a file change
   */
  track(filePath, eventType, stats = null) {
    const existing = this.changes.get(filePath) || { events: [], firstSeen: Date.now() };
    existing.events.push({ type: eventType, timestamp: Date.now() });
    existing.lastSeen = Date.now();
    existing.stats = stats;
    this.changes.set(filePath, existing);
  }

  /**
   * Get pending changes
   */
  getPending() {
    return Array.from(this.changes.entries()).map(([path, data]) => ({
      path,
      ...data,
      latestEvent: data.events[data.events.length - 1]
    }));
  }

  /**
   * Clear tracked changes
   */
  clear() {
    this.changes.clear();
  }

  /**
   * Compute file hash
   */
  computeHash(filePath) {
    try {
      const content = fs.readFileSync(filePath);
      return crypto.createHash('md5').update(content).digest('hex');
    } catch {
      return null;
    }
  }

  /**
   * Check if file content changed
   */
  hasContentChanged(filePath) {
    const newHash = this.computeHash(filePath);
    if (!newHash) return true;

    const oldHash = this.hashes.get(filePath);
    this.hashes.set(filePath, newHash);

    return oldHash !== newHash;
  }

  /**
   * Get change summary
   */
  getSummary() {
    const summary = { added: 0, changed: 0, deleted: 0, total: 0 };

    for (const [, data] of this.changes) {
      const event = data.events[data.events.length - 1].type;
      if (event === WATCH_EVENTS.FILE_ADDED) summary.added++;
      else if (event === WATCH_EVENTS.FILE_CHANGED) summary.changed++;
      else if (event === WATCH_EVENTS.FILE_DELETED) summary.deleted++;
      summary.total++;
    }

    return summary;
  }
}

/**
 * Debouncer utility
 */
class Debouncer {
  constructor(delay = 300) {
    this.delay = delay;
    this.timers = new Map();
  }

  /**
   * Debounce a function call
   */
  debounce(key, fn) {
    if (this.timers.has(key)) {
      clearTimeout(this.timers.get(key));
    }

    const timer = setTimeout(() => {
      this.timers.delete(key);
      fn();
    }, this.delay);

    this.timers.set(key, timer);
  }

  /**
   * Cancel pending debounce
   */
  cancel(key) {
    if (this.timers.has(key)) {
      clearTimeout(this.timers.get(key));
      this.timers.delete(key);
    }
  }

  /**
   * Cancel all pending
   */
  cancelAll() {
    for (const timer of this.timers.values()) {
      clearTimeout(timer);
    }
    this.timers.clear();
  }
}

/**
 * Watch Mode Manager
 */
class WatchMode extends EventEmitter {
  constructor(options = {}) {
    super();

    this.options = { ...DEFAULT_OPTIONS, ...options };
    this.watchers = new Map();
    this.changeTracker = new ChangeTracker();
    this.debouncer = new Debouncer(this.options.debounceMs);
    this.isWatching = false;
    this.syncQueue = [];
    this.isSyncing = false;
    this.stats = {
      filesWatched: 0,
      changesDetected: 0,
      syncsCompleted: 0,
      errors: 0,
      startTime: null
    };
  }

  /**
   * Start watching directories
   */
  start(directories = []) {
    if (this.isWatching) {
      return this;
    }

    this.stats.startTime = Date.now();
    this.isWatching = true;

    for (const dir of directories) {
      this.watchDirectory(dir);
    }

    this.emit('watch:started', {
      directories,
      options: this.options
    });

    return this;
  }

  /**
   * Watch a single directory
   */
  watchDirectory(directory) {
    const resolvedDir = path.resolve(directory);

    if (this.watchers.has(resolvedDir)) {
      return;
    }

    try {
      const watcher = fs.watch(
        resolvedDir,
        {
          persistent: this.options.persistent,
          recursive: this.options.recursive
        },
        (eventType, filename) => {
          if (filename) {
            this.handleFileEvent(resolvedDir, filename, eventType);
          }
        }
      );

      watcher.on('error', (error) => {
        this.emit('watch:error', { directory: resolvedDir, error });
        this.stats.errors++;
      });

      this.watchers.set(resolvedDir, watcher);
      this.stats.filesWatched++;

      this.emit('watch:directory-added', { directory: resolvedDir });
    } catch (error) {
      this.emit('watch:error', { directory: resolvedDir, error });
      this.stats.errors++;
    }
  }

  /**
   * Handle file system event
   */
  handleFileEvent(directory, filename, eventType) {
    const filePath = path.join(directory, filename);

    // Check if should ignore
    if (this.shouldIgnore(filePath)) {
      return;
    }

    // Check extension
    const ext = path.extname(filePath);
    if (WATCHABLE_EXTENSIONS.length > 0 && !WATCHABLE_EXTENSIONS.includes(ext)) {
      return;
    }

    // Debounce the event
    this.debouncer.debounce(filePath, () => {
      this.processFileEvent(filePath, eventType);
    });
  }

  /**
   * Process a file event after debouncing
   */
  processFileEvent(filePath, eventType) {
    let watchEvent;
    let stats = null;

    try {
      const exists = fs.existsSync(filePath);

      if (!exists) {
        watchEvent = WATCH_EVENTS.FILE_DELETED;
      } else {
        stats = fs.statSync(filePath);

        if (stats.isDirectory()) {
          watchEvent = WATCH_EVENTS.DIR_ADDED;
        } else {
          // Check if content actually changed
          if (!this.changeTracker.hasContentChanged(filePath)) {
            return; // No actual content change
          }

          watchEvent = eventType === 'rename'
            ? WATCH_EVENTS.FILE_ADDED
            : WATCH_EVENTS.FILE_CHANGED;
        }
      }
    } catch (error) {
      watchEvent = WATCH_EVENTS.FILE_DELETED;
    }

    // Track the change
    this.changeTracker.track(filePath, watchEvent, stats);
    this.stats.changesDetected++;

    // Emit event
    this.emit(watchEvent, { filePath, stats });
    this.emit('change', { type: watchEvent, filePath, stats });

    // Queue for sync if auto-sync enabled
    if (this.options.autoSync) {
      this.queueSync(filePath, watchEvent);
    }
  }

  /**
   * Check if path should be ignored
   */
  shouldIgnore(filePath) {
    for (const pattern of this.options.ignorePatterns) {
      if (this.matchPattern(filePath, pattern)) {
        return true;
      }
    }
    return false;
  }

  /**
   * Simple glob pattern matching
   */
  matchPattern(filePath, pattern) {
    // Convert glob to regex
    const regex = pattern
      .replace(/\*\*/g, '{{GLOBSTAR}}')
      .replace(/\*/g, '[^/]*')
      .replace(/{{GLOBSTAR}}/g, '.*')
      .replace(/\//g, '\\/');

    return new RegExp(regex).test(filePath);
  }

  /**
   * Queue a file for sync
   */
  queueSync(filePath, eventType) {
    this.syncQueue.push({ filePath, eventType, timestamp: Date.now() });

    // Process queue
    this.processSyncQueue();
  }

  /**
   * Process sync queue
   */
  async processSyncQueue() {
    if (this.isSyncing || this.syncQueue.length === 0) {
      return;
    }

    this.isSyncing = true;
    this.emit(WATCH_EVENTS.SYNC_STARTED, { queueLength: this.syncQueue.length });

    try {
      const batch = [...this.syncQueue];
      this.syncQueue = [];

      await this.syncFiles(batch);

      this.stats.syncsCompleted++;
      this.emit(WATCH_EVENTS.SYNC_COMPLETE, {
        filesProcessed: batch.length,
        timestamp: Date.now()
      });
    } catch (error) {
      this.stats.errors++;
      this.emit(WATCH_EVENTS.SYNC_ERROR, { error });
    } finally {
      this.isSyncing = false;

      // Check if more items were queued during sync
      if (this.syncQueue.length > 0) {
        this.processSyncQueue();
      }
    }
  }

  /**
   * Sync files (to be overridden or configured)
   */
  async syncFiles(files) {
    // Default implementation - emit events for each file
    for (const file of files) {
      this.emit('sync:file', file);
    }

    // Simulate async operation
    return new Promise(resolve => setTimeout(resolve, 100));
  }

  /**
   * Set custom sync handler
   */
  setSyncHandler(handler) {
    this.syncFiles = handler.bind(this);
    return this;
  }

  /**
   * Stop watching
   */
  stop() {
    this.isWatching = false;
    this.debouncer.cancelAll();

    for (const [dir, watcher] of this.watchers) {
      watcher.close();
      this.emit('watch:directory-removed', { directory: dir });
    }

    this.watchers.clear();

    this.emit('watch:stopped', {
      stats: this.getStats()
    });

    return this;
  }

  /**
   * Pause watching (keep watchers but ignore events)
   */
  pause() {
    this.isWatching = false;
    this.emit('watch:paused');
    return this;
  }

  /**
   * Resume watching
   */
  resume() {
    this.isWatching = true;
    this.emit('watch:resumed');
    return this;
  }

  /**
   * Get watch statistics
   */
  getStats() {
    return {
      ...this.stats,
      uptime: this.stats.startTime ? Date.now() - this.stats.startTime : 0,
      directoriesWatched: this.watchers.size,
      pendingChanges: this.changeTracker.getPending().length,
      pendingSyncs: this.syncQueue.length,
      changeSummary: this.changeTracker.getSummary()
    };
  }

  /**
   * Get pending changes
   */
  getPendingChanges() {
    return this.changeTracker.getPending();
  }

  /**
   * Clear pending changes
   */
  clearPendingChanges() {
    this.changeTracker.clear();
    return this;
  }

  /**
   * Force sync all pending changes
   */
  async forceSyncAll() {
    const pending = this.changeTracker.getPending();

    for (const change of pending) {
      this.queueSync(change.path, change.latestEvent.type);
    }

    this.changeTracker.clear();

    return this.processSyncQueue();
  }

  /**
   * Add ignore pattern
   */
  addIgnorePattern(pattern) {
    if (!this.options.ignorePatterns.includes(pattern)) {
      this.options.ignorePatterns.push(pattern);
    }
    return this;
  }

  /**
   * Remove ignore pattern
   */
  removeIgnorePattern(pattern) {
    const index = this.options.ignorePatterns.indexOf(pattern);
    if (index > -1) {
      this.options.ignorePatterns.splice(index, 1);
    }
    return this;
  }

  /**
   * Reset statistics
   */
  resetStats() {
    this.stats = {
      filesWatched: this.watchers.size,
      changesDetected: 0,
      syncsCompleted: 0,
      errors: 0,
      startTime: this.isWatching ? Date.now() : null
    };
    return this;
  }
}

/**
 * Figma Webhook Handler
 */
class FigmaWebhookHandler extends EventEmitter {
  constructor(options = {}) {
    super();

    this.options = {
      secret: options.secret || '',
      events: options.events || ['FILE_UPDATE', 'FILE_DELETE', 'FILE_VERSION_UPDATE'],
      ...options
    };

    this.lastUpdate = null;
    this.pendingUpdates = [];
  }

  /**
   * Handle incoming webhook
   */
  handleWebhook(payload, signature = null) {
    // Verify signature if secret provided
    if (this.options.secret && signature) {
      if (!this.verifySignature(payload, signature)) {
        this.emit('webhook:invalid-signature');
        return { success: false, error: 'Invalid signature' };
      }
    }

    // Parse payload
    const data = typeof payload === 'string' ? JSON.parse(payload) : payload;

    // Check if we handle this event
    if (!this.options.events.includes(data.event_type)) {
      return { success: true, ignored: true };
    }

    // Track update
    this.lastUpdate = Date.now();
    this.pendingUpdates.push(data);

    // Emit event
    this.emit(WATCH_EVENTS.FIGMA_UPDATE, {
      eventType: data.event_type,
      fileKey: data.file_key,
      timestamp: data.timestamp,
      triggeredBy: data.triggered_by
    });

    return { success: true, processed: true };
  }

  /**
   * Verify webhook signature
   */
  verifySignature(payload, signature) {
    const expected = crypto
      .createHmac('sha256', this.options.secret)
      .update(typeof payload === 'string' ? payload : JSON.stringify(payload))
      .digest('hex');

    return crypto.timingSafeEqual(
      Buffer.from(signature),
      Buffer.from(expected)
    );
  }

  /**
   * Get pending Figma updates
   */
  getPendingUpdates() {
    return [...this.pendingUpdates];
  }

  /**
   * Clear pending updates
   */
  clearPendingUpdates() {
    this.pendingUpdates = [];
    return this;
  }

  /**
   * Create Express middleware
   */
  createMiddleware() {
    return (req, res) => {
      const signature = req.headers['x-figma-signature'];
      const result = this.handleWebhook(req.body, signature);

      if (result.success) {
        res.status(200).json(result);
      } else {
        res.status(401).json(result);
      }
    };
  }
}

/**
 * Live Reload Server
 */
class LiveReloadServer extends EventEmitter {
  constructor(options = {}) {
    super();

    this.options = {
      port: options.port || 35729,
      host: options.host || 'localhost',
      ...options
    };

    this.clients = new Set();
    this.server = null;
    this.isRunning = false;
  }

  /**
   * Start live reload server
   */
  start() {
    if (this.isRunning) return this;

    // Create simple HTTP server for SSE
    const http = require('http');

    this.server = http.createServer((req, res) => {
      if (req.url === '/livereload') {
        this.handleSSEClient(req, res);
      } else if (req.url === '/livereload.js') {
        this.serveClientScript(res);
      } else {
        res.writeHead(404);
        res.end('Not found');
      }
    });

    this.server.listen(this.options.port, this.options.host, () => {
      this.isRunning = true;
      this.emit('server:started', {
        port: this.options.port,
        host: this.options.host
      });
    });

    return this;
  }

  /**
   * Handle SSE client connection
   */
  handleSSEClient(req, res) {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
      'Access-Control-Allow-Origin': '*'
    });

    this.clients.add(res);

    // Send initial connection message
    res.write('data: {"type":"connected"}\n\n');

    req.on('close', () => {
      this.clients.delete(res);
    });
  }

  /**
   * Serve client-side script
   */
  serveClientScript(res) {
    const script = `
(function() {
  var source = new EventSource('http://${this.options.host}:${this.options.port}/livereload');

  source.onmessage = function(event) {
    var data = JSON.parse(event.data);

    if (data.type === 'reload') {
      console.log('[LiveReload] Reloading...');
      window.location.reload();
    } else if (data.type === 'css') {
      console.log('[LiveReload] Updating CSS...');
      var links = document.getElementsByTagName('link');
      for (var i = 0; i < links.length; i++) {
        var link = links[i];
        if (link.rel === 'stylesheet') {
          link.href = link.href.replace(/\\?.*$/, '') + '?t=' + Date.now();
        }
      }
    }
  };

  source.onerror = function() {
    console.log('[LiveReload] Connection lost, retrying...');
  };
})();
`;

    res.writeHead(200, { 'Content-Type': 'application/javascript' });
    res.end(script);
  }

  /**
   * Trigger reload for all clients
   */
  reload(type = 'reload', data = {}) {
    const message = JSON.stringify({ type, ...data });

    for (const client of this.clients) {
      try {
        client.write(`data: ${message}\n\n`);
      } catch {
        this.clients.delete(client);
      }
    }

    this.emit('reload:triggered', { type, clientCount: this.clients.size });
  }

  /**
   * Stop server
   */
  stop() {
    if (!this.isRunning) return this;

    // Close all client connections
    for (const client of this.clients) {
      client.end();
    }
    this.clients.clear();

    if (this.server) {
      this.server.close(() => {
        this.isRunning = false;
        this.emit('server:stopped');
      });
    }

    return this;
  }

  /**
   * Get connection count
   */
  getConnectionCount() {
    return this.clients.size;
  }

  /**
   * Get client script tag
   */
  getScriptTag() {
    return `<script src="http://${this.options.host}:${this.options.port}/livereload.js"></script>`;
  }
}

// Factory functions
function createWatchMode(options = {}) {
  return new WatchMode(options);
}

function createFigmaWebhookHandler(options = {}) {
  return new FigmaWebhookHandler(options);
}

function createLiveReloadServer(options = {}) {
  return new LiveReloadServer(options);
}

// Export
module.exports = {
  WatchMode,
  FigmaWebhookHandler,
  LiveReloadServer,
  ChangeTracker,
  Debouncer,
  createWatchMode,
  createFigmaWebhookHandler,
  createLiveReloadServer,
  WATCH_EVENTS,
  DEFAULT_OPTIONS,
  WATCHABLE_EXTENSIONS
};
