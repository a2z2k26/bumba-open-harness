/**
 * Real-time Sync Engine
 * Enables real-time synchronization between design tools and code
 * Sprint 17: Real-time Sync
 */

const EventEmitter = require('events');
const WebSocket = require('ws');
const crypto = require('crypto');

class RealtimeSync extends EventEmitter {
  constructor() {
    super();
    this.name = 'RealtimeSync';
    this.version = '1.0.0';

    // Connection state
    this.connections = new Map();
    this.subscriptions = new Map();
    this.pendingChanges = new Map();

    // Configuration
    this.config = {
      syncInterval: 100, // ms
      batchSize: 50,
      retryAttempts: 3,
      retryDelay: 1000,
      heartbeatInterval: 30000,
      compression: true,
      encryption: true,
      conflictResolution: 'last-write-wins', // last-write-wins, merge, manual
      offlineSupport: true,
      maxQueueSize: 1000
    };

    // Sync state
    this.syncState = {
      isOnline: true,
      isSyncing: false,
      lastSyncTime: null,
      pendingCount: 0,
      errorCount: 0,
      totalSynced: 0
    };

    // Change tracking
    this.changeBuffer = [];
    this.syncTimer = null;
    this.offlineQueue = [];

    // Initialize
    this.initialize();
  }

  /**
   * Initialize real-time sync
   */
  initialize() {
    // Setup change batching
    this.setupChangeBatching();

    // Setup heartbeat
    this.setupHeartbeat();

    // Setup offline detection
    this.setupOfflineDetection();

    // Setup conflict resolution
    this.setupConflictResolution();

    this.initialized = true;
    console.log('✅ Real-time sync initialized');
    return this;
  }

  isInitialized() {
    return this.initialized === true;
  }

  /**
   * Connect to sync server
   */
  async connect(serverUrl, options = {}) {
    try {
      const connectionId = this.generateConnectionId();

      // Create WebSocket connection
      const ws = new WebSocket(serverUrl, {
        ...options,
        perMessageDeflate: this.config.compression
      });

      // Setup connection handlers
      this.setupConnectionHandlers(ws, connectionId);

      // Store connection
      this.connections.set(connectionId, {
        ws,
        url: serverUrl,
        status: 'connecting',
        createdAt: new Date(),
        lastActivity: new Date(),
        metadata: options.metadata || {}
      });

      // Wait for connection
      await this.waitForConnection(connectionId);

      // Authenticate if needed
      if (options.auth) {
        await this.authenticate(connectionId, options.auth);
      }

      // Subscribe to channels
      if (options.channels) {
        await this.subscribeToChannels(connectionId, options.channels);
      }

      this.emit('connected', { connectionId, serverUrl });
      return connectionId;

    } catch (error) {
      this.emit('connection:error', error);
      throw error;
    }
  }

  /**
   * Disconnect from sync server
   */
  async disconnect(connectionId) {
    const connection = this.connections.get(connectionId);
    if (!connection) return;

    // Close WebSocket
    if (connection.ws) {
      connection.ws.close();
    }

    // Clean up subscriptions
    this.subscriptions.delete(connectionId);

    // Remove connection
    this.connections.delete(connectionId);

    this.emit('disconnected', { connectionId });
  }

  /**
   * Subscribe to design changes
   */
  async subscribeToDesignChanges(designId, callback) {
    const subscriptionId = this.generateSubscriptionId();

    const subscription = {
      id: subscriptionId,
      designId,
      callback,
      createdAt: new Date(),
      eventCount: 0
    };

    // Store subscription
    if (!this.subscriptions.has(designId)) {
      this.subscriptions.set(designId, []);
    }
    this.subscriptions.get(designId).push(subscription);

    // Send subscription request to all connections
    this.broadcastToConnections({
      type: 'subscribe',
      designId,
      subscriptionId
    });

    this.emit('subscribed', { designId, subscriptionId });
    return subscriptionId;
  }

  /**
   * Unsubscribe from design changes
   */
  async unsubscribeFromDesignChanges(subscriptionId) {
    // Find and remove subscription
    for (const [designId, subs] of this.subscriptions) {
      const index = subs.findIndex(s => s.id === subscriptionId);
      if (index !== -1) {
        subs.splice(index, 1);

        // Send unsubscribe request
        this.broadcastToConnections({
          type: 'unsubscribe',
          designId,
          subscriptionId
        });

        this.emit('unsubscribed', { designId, subscriptionId });
        return true;
      }
    }
    return false;
  }

  /**
   * Push design changes
   */
  async pushChanges(changes) {
    // Add to change buffer
    this.changeBuffer.push(...changes);

    // Mark as syncing
    this.syncState.isSyncing = true;
    this.syncState.pendingCount = this.changeBuffer.length;

    // Process immediately if urgent
    if (changes.some(c => c.urgent)) {
      await this.processSyncBatch();
    }

    // Return success status
    return {
      success: true,
      queued: changes.length,
      totalPending: this.changeBuffer.length
    };

    this.emit('changes:queued', { count: changes.length });
  }

  /**
   * Pull latest changes
   */
  async pullChanges(designId, since = null) {
    const request = {
      type: 'pull',
      designId,
      since: since || this.syncState.lastSyncTime
    };

    // Request from all connections
    const responses = await this.requestFromConnections(request);

    // Merge responses
    const changes = this.mergeChanges(responses);

    // Apply changes
    await this.applyChanges(changes);

    return changes;
  }

  /**
   * Handle incoming message
   */
  handleMessage(connectionId, message) {
    const connection = this.connections.get(connectionId);
    if (!connection) return;

    // Update activity
    connection.lastActivity = new Date();

    // Parse message
    const data = this.parseMessage(message);

    switch (data.type) {
      case 'changes':
        this.handleIncomingChanges(data.changes);
        break;

      case 'sync-request':
        this.handleSyncRequest(connectionId, data);
        break;

      case 'conflict':
        this.handleConflict(data);
        break;

      case 'heartbeat':
        this.handleHeartbeat(connectionId);
        break;

      case 'error':
        this.handleError(connectionId, data);
        break;

      default:
        this.emit('message', { connectionId, data });
    }
  }

  /**
   * Handle incoming changes
   */
  async handleIncomingChanges(changes) {
    // Validate changes
    const validChanges = this.validateChanges(changes);

    // Check for conflicts
    const conflicts = await this.detectConflicts(validChanges);

    if (conflicts.length > 0) {
      // Resolve conflicts
      const resolved = await this.resolveConflicts(conflicts);
      validChanges.push(...resolved);
    }

    // Apply changes
    await this.applyChanges(validChanges);

    // Notify subscribers
    this.notifySubscribers(validChanges);

    // Update sync state
    this.syncState.lastSyncTime = new Date();
    this.syncState.totalSynced += validChanges.length;

    this.emit('changes:received', { count: validChanges.length });
  }

  /**
   * Apply changes to local state
   */
  async applyChanges(changes) {
    const results = [];

    for (const change of changes) {
      try {
        const result = await this.applyChange(change);
        results.push({ success: true, change, result });
      } catch (error) {
        results.push({ success: false, change, error });
        this.emit('change:error', { change, error });
      }
    }

    return results;
  }

  /**
   * Apply single change
   */
  async applyChange(change) {
    const { type, target, data, timestamp } = change;

    switch (type) {
      case 'create':
        return this.handleCreate(target, data);

      case 'update':
        return this.handleUpdate(target, data);

      case 'delete':
        return this.handleDelete(target);

      case 'move':
        return this.handleMove(target, data);

      case 'batch':
        return this.handleBatch(data);

      default:
        throw new Error(`Unknown change type: ${type}`);
    }
  }

  /**
   * Setup change batching
   */
  setupChangeBatching() {
    this.syncTimer = setInterval(async () => {
      if (this.changeBuffer.length > 0 && !this.syncState.isSyncing) {
        await this.processSyncBatch();
      }
    }, this.config.syncInterval);
  }

  /**
   * Process sync batch
   */
  async processSyncBatch() {
    if (this.changeBuffer.length === 0) return;

    // Get batch
    const batch = this.changeBuffer.splice(0, this.config.batchSize);

    try {
      // Send batch to connections
      await this.broadcastToConnections({
        type: 'changes',
        changes: batch,
        timestamp: new Date()
      });

      // Clear from offline queue if successful
      if (this.syncState.isOnline) {
        this.offlineQueue = [];
      }

      this.syncState.pendingCount = this.changeBuffer.length;
      this.emit('batch:synced', { count: batch.length });

    } catch (error) {
      // Add back to buffer on error
      this.changeBuffer.unshift(...batch);

      // Add to offline queue if offline
      if (!this.syncState.isOnline) {
        this.offlineQueue.push(...batch);
      }

      this.syncState.errorCount++;
      this.emit('batch:error', error);
    }

    this.syncState.isSyncing = this.changeBuffer.length > 0;
  }

  /**
   * Setup heartbeat
   */
  setupHeartbeat() {
    setInterval(() => {
      this.broadcastToConnections({ type: 'heartbeat' });
    }, this.config.heartbeatInterval);
  }

  /**
   * Setup offline detection
   */
  setupOfflineDetection() {
    // Monitor connection status
    setInterval(() => {
      const hasActiveConnection = Array.from(this.connections.values())
        .some(c => c.status === 'connected');

      const wasOnline = this.syncState.isOnline;
      this.syncState.isOnline = hasActiveConnection;

      // Handle online/offline transitions
      if (!wasOnline && this.syncState.isOnline) {
        this.handleComeOnline();
      } else if (wasOnline && !this.syncState.isOnline) {
        this.handleGoOffline();
      }
    }, 1000);
  }

  /**
   * Handle coming online
   */
  async handleComeOnline() {
    this.emit('online');

    // Process offline queue
    if (this.offlineQueue.length > 0) {
      this.changeBuffer.unshift(...this.offlineQueue);
      this.offlineQueue = [];
      await this.processSyncBatch();
    }
  }

  /**
   * Handle going offline
   */
  handleGoOffline() {
    this.emit('offline');

    // Save current changes to offline queue
    if (this.changeBuffer.length > 0) {
      this.offlineQueue.push(...this.changeBuffer);
    }
  }

  /**
   * Setup conflict resolution
   */
  setupConflictResolution() {
    this.conflictResolvers = {
      'last-write-wins': this.resolveLastWriteWins.bind(this),
      'merge': this.resolveMerge.bind(this),
      'manual': this.resolveManual.bind(this)
    };
  }

  /**
   * Detect conflicts
   */
  async detectConflicts(changes) {
    const conflicts = [];

    for (const change of changes) {
      const localVersion = await this.getLocalVersion(change.target);

      if (localVersion && localVersion.timestamp > change.timestamp) {
        conflicts.push({
          incoming: change,
          local: localVersion
        });
      }
    }

    return conflicts;
  }

  /**
   * Resolve conflicts
   */
  async resolveConflicts(conflicts) {
    const resolver = this.conflictResolvers[this.config.conflictResolution];
    return resolver(conflicts);
  }

  /**
   * Resolve using last-write-wins
   */
  async resolveLastWriteWins(conflicts) {
    return conflicts.map(c =>
      c.incoming.timestamp > c.local.timestamp ? c.incoming : c.local
    );
  }

  /**
   * Resolve using merge
   */
  async resolveMerge(conflicts) {
    const resolved = [];

    for (const conflict of conflicts) {
      const merged = await this.mergeChanges([conflict.incoming, conflict.local]);
      resolved.push(merged);
    }

    return resolved;
  }

  /**
   * Resolve manually
   */
  async resolveManual(conflicts) {
    this.emit('conflicts:detected', conflicts);

    // Wait for manual resolution
    return new Promise(resolve => {
      this.once('conflicts:resolved', resolve);
    });
  }

  /**
   * Helper methods
   */
  generateConnectionId() {
    return crypto.randomBytes(16).toString('hex');
  }

  generateSubscriptionId() {
    return `sub_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }

  setupConnectionHandlers(ws, connectionId) {
    ws.on('open', () => {
      const connection = this.connections.get(connectionId);
      if (connection) {
        connection.status = 'connected';
        this.emit('connection:open', { connectionId });
      }
    });

    ws.on('message', (data) => {
      this.handleMessage(connectionId, data);
    });

    ws.on('error', (error) => {
      this.emit('connection:error', { connectionId, error });
    });

    ws.on('close', () => {
      const connection = this.connections.get(connectionId);
      if (connection) {
        connection.status = 'closed';
        this.emit('connection:close', { connectionId });
      }
    });
  }

  async waitForConnection(connectionId, timeout = 5000) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error('Connection timeout'));
      }, timeout);

      const checkConnection = setInterval(() => {
        const connection = this.connections.get(connectionId);
        if (connection && connection.status === 'connected') {
          clearInterval(checkConnection);
          clearTimeout(timer);
          resolve(connection);
        }
      }, 100);
    });
  }

  async authenticate(connectionId, auth) {
    const connection = this.connections.get(connectionId);
    if (!connection) throw new Error('Connection not found');

    connection.ws.send(JSON.stringify({
      type: 'auth',
      ...auth
    }));
  }

  async subscribeToChannels(connectionId, channels) {
    const connection = this.connections.get(connectionId);
    if (!connection) throw new Error('Connection not found');

    connection.ws.send(JSON.stringify({
      type: 'subscribe',
      channels
    }));
  }

  broadcastToConnections(message) {
    const data = JSON.stringify(message);

    for (const connection of this.connections.values()) {
      if (connection.status === 'connected' && connection.ws) {
        connection.ws.send(data);
      }
    }
  }

  async requestFromConnections(request) {
    const responses = [];

    for (const connection of this.connections.values()) {
      if (connection.status === 'connected' && connection.ws) {
        // Send request and wait for response
        const response = await this.requestFromConnection(connection, request);
        responses.push(response);
      }
    }

    return responses;
  }

  async requestFromConnection(connection, request) {
    return new Promise((resolve) => {
      const requestId = crypto.randomBytes(16).toString('hex');

      // Send request
      connection.ws.send(JSON.stringify({
        ...request,
        requestId
      }));

      // Wait for response
      const handler = (data) => {
        if (data.requestId === requestId) {
          connection.ws.removeListener('message', handler);
          resolve(data);
        }
      };

      connection.ws.on('message', handler);

      // Timeout
      setTimeout(() => {
        connection.ws.removeListener('message', handler);
        resolve(null);
      }, 5000);
    });
  }

  parseMessage(message) {
    try {
      return JSON.parse(message);
    } catch (error) {
      return { type: 'unknown', data: message };
    }
  }

  validateChanges(changes) {
    return changes.filter(change => {
      return change.type && change.target && change.timestamp;
    });
  }

  mergeChanges(responses) {
    const allChanges = [];

    for (const response of responses) {
      if (response && response.changes) {
        allChanges.push(...response.changes);
      }
    }

    // Remove duplicates and sort by timestamp
    const uniqueChanges = Array.from(
      new Map(allChanges.map(c => [c.id || c.target, c])).values()
    );

    return uniqueChanges.sort((a, b) =>
      new Date(a.timestamp) - new Date(b.timestamp)
    );
  }

  notifySubscribers(changes) {
    for (const change of changes) {
      const subs = this.subscriptions.get(change.designId);
      if (subs) {
        subs.forEach(sub => {
          sub.callback(change);
          sub.eventCount++;
        });
      }
    }
  }

  async getLocalVersion(target) {
    // Implement local version checking
    return null;
  }

  async handleCreate(target, data) {
    this.emit('create', { target, data });
    return { success: true };
  }

  async handleUpdate(target, data) {
    this.emit('update', { target, data });
    return { success: true };
  }

  async handleDelete(target) {
    this.emit('delete', { target });
    return { success: true };
  }

  async handleMove(target, data) {
    this.emit('move', { target, data });
    return { success: true };
  }

  async handleBatch(data) {
    for (const change of data) {
      await this.applyChange(change);
    }
    return { success: true };
  }

  handleSyncRequest(connectionId, data) {
    // Handle sync request from peer
    this.emit('sync:request', { connectionId, data });
  }

  handleConflict(data) {
    this.emit('conflict', data);
  }

  handleHeartbeat(connectionId) {
    const connection = this.connections.get(connectionId);
    if (connection) {
      connection.lastActivity = new Date();
    }
  }

  handleError(connectionId, data) {
    this.emit('error', { connectionId, error: data.error });
  }

  /**
   * Cleanup
   */
  async cleanup() {
    // Stop timers
    if (this.syncTimer) {
      clearInterval(this.syncTimer);
    }

    // Close all connections
    for (const connectionId of this.connections.keys()) {
      await this.disconnect(connectionId);
    }

    // Clear buffers
    this.changeBuffer = [];
    this.offlineQueue = [];
  }
}

module.exports = RealtimeSync;