/**
 * Progress Tracker
 * Sprint 27: Real-time progress tracking for long operations
 *
 * Features:
 * - Progress percentage tracking
 * - Step-based progress updates
 * - WebSocket event broadcasting
 * - Operation metadata tracking
 * - Completion callbacks
 */

const EventEmitter = require('events');

/**
 * Operation Status
 */
const OperationStatus = {
  PENDING: 'pending',
  IN_PROGRESS: 'in_progress',
  COMPLETED: 'completed',
  FAILED: 'failed',
  CANCELLED: 'cancelled'
};

/**
 * Progress Tracker
 * Tracks and broadcasts progress for long-running operations
 */
class ProgressTracker extends EventEmitter {
  constructor(options = {}) {
    super();

    this.wsManager = options.wsManager;
    this.operations = new Map();
    this.broadcastInterval = options.broadcastInterval || 100; // ms throttle
    this.lastBroadcast = new Map();
  }

  /**
   * Start tracking an operation
   */
  startOperation(operationId, config = {}) {
    const operation = {
      id: operationId,
      type: config.type || 'unknown',
      description: config.description || '',
      totalSteps: config.totalSteps || 100,
      currentStep: 0,
      percentage: 0,
      status: OperationStatus.PENDING,
      metadata: config.metadata || {},
      startedAt: new Date().toISOString(),
      completedAt: null,
      error: null
    };

    this.operations.set(operationId, operation);

    // Broadcast operation started
    this.broadcastProgress(operationId, {
      event: 'operation-started'
    });

    this.emit('operation:started', operation);

    return operation;
  }

  /**
   * Update operation progress
   */
  updateProgress(operationId, step, message = '') {
    const operation = this.operations.get(operationId);
    if (!operation) {
      console.warn(`Operation not found: ${operationId}`);
      return;
    }

    // Update status to in_progress if pending
    if (operation.status === OperationStatus.PENDING) {
      operation.status = OperationStatus.IN_PROGRESS;
    }

    // Update step and percentage
    operation.currentStep = step;
    operation.percentage = Math.min(100, Math.round((step / operation.totalSteps) * 100));
    operation.currentMessage = message;

    // Throttled broadcast
    this.throttledBroadcast(operationId, {
      event: 'operation-progress',
      message
    });

    this.emit('operation:progress', {
      operationId,
      step,
      percentage: operation.percentage,
      message
    });
  }

  /**
   * Complete an operation
   */
  completeOperation(operationId, result = {}) {
    const operation = this.operations.get(operationId);
    if (!operation) {
      console.warn(`Operation not found: ${operationId}`);
      return;
    }

    operation.status = OperationStatus.COMPLETED;
    operation.percentage = 100;
    operation.currentStep = operation.totalSteps;
    operation.completedAt = new Date().toISOString();
    operation.result = result;

    // Calculate duration
    const duration = new Date(operation.completedAt) - new Date(operation.startedAt);
    operation.duration = duration;

    // Broadcast completion
    this.broadcastProgress(operationId, {
      event: 'operation-completed',
      result,
      duration
    });

    this.emit('operation:completed', operation);

    // Clean up after delay
    setTimeout(() => {
      this.operations.delete(operationId);
      this.lastBroadcast.delete(operationId);
    }, 60000); // Keep for 1 minute
  }

  /**
   * Fail an operation
   */
  failOperation(operationId, error) {
    const operation = this.operations.get(operationId);
    if (!operation) {
      console.warn(`Operation not found: ${operationId}`);
      return;
    }

    operation.status = OperationStatus.FAILED;
    operation.completedAt = new Date().toISOString();
    operation.error = {
      message: error.message,
      code: error.code,
      stack: error.stack
    };

    // Calculate duration
    const duration = new Date(operation.completedAt) - new Date(operation.startedAt);
    operation.duration = duration;

    // Broadcast failure
    this.broadcastProgress(operationId, {
      event: 'operation-failed',
      error: {
        message: error.message,
        code: error.code
      },
      duration
    });

    this.emit('operation:failed', operation);

    // Clean up after delay
    setTimeout(() => {
      this.operations.delete(operationId);
      this.lastBroadcast.delete(operationId);
    }, 60000); // Keep for 1 minute
  }

  /**
   * Cancel an operation
   */
  cancelOperation(operationId) {
    const operation = this.operations.get(operationId);
    if (!operation) {
      console.warn(`Operation not found: ${operationId}`);
      return;
    }

    operation.status = OperationStatus.CANCELLED;
    operation.completedAt = new Date().toISOString();

    // Broadcast cancellation
    this.broadcastProgress(operationId, {
      event: 'operation-cancelled'
    });

    this.emit('operation:cancelled', operation);

    // Clean up
    this.operations.delete(operationId);
    this.lastBroadcast.delete(operationId);
  }

  /**
   * Broadcast progress with throttling
   */
  throttledBroadcast(operationId, data = {}) {
    const now = Date.now();
    const lastBroadcastTime = this.lastBroadcast.get(operationId) || 0;

    // Throttle broadcasts
    if (now - lastBroadcastTime < this.broadcastInterval) {
      return;
    }

    this.broadcastProgress(operationId, data);
    this.lastBroadcast.set(operationId, now);
  }

  /**
   * Broadcast progress to WebSocket clients
   */
  broadcastProgress(operationId, data = {}) {
    const operation = this.operations.get(operationId);
    if (!operation || !this.wsManager) {
      return;
    }

    this.wsManager.broadcastAuthenticated({
      type: 'operation-progress',
      ...data,
      operation: {
        id: operation.id,
        type: operation.type,
        description: operation.description,
        status: operation.status,
        percentage: operation.percentage,
        currentStep: operation.currentStep,
        totalSteps: operation.totalSteps,
        currentMessage: operation.currentMessage,
        metadata: operation.metadata
      },
      timestamp: new Date().toISOString()
    });
  }

  /**
   * Get operation status
   */
  getOperation(operationId) {
    return this.operations.get(operationId);
  }

  /**
   * Get all operations
   */
  getAllOperations() {
    return Array.from(this.operations.values());
  }

  /**
   * Get active operations
   */
  getActiveOperations() {
    return Array.from(this.operations.values()).filter(op =>
      op.status === OperationStatus.PENDING || op.status === OperationStatus.IN_PROGRESS
    );
  }

  /**
   * Helper: Create step tracker for an operation
   */
  createStepTracker(operationId, totalSteps) {
    let currentStep = 0;

    return {
      next: (message = '') => {
        currentStep++;
        this.updateProgress(operationId, currentStep, message);
        return currentStep;
      },
      jump: (step, message = '') => {
        currentStep = step;
        this.updateProgress(operationId, step, message);
        return currentStep;
      },
      complete: (result) => {
        this.completeOperation(operationId, result);
      },
      fail: (error) => {
        this.failOperation(operationId, error);
      },
      getCurrentStep: () => currentStep,
      getTotalSteps: () => totalSteps
    };
  }
}

module.exports = ProgressTracker;
module.exports.OperationStatus = OperationStatus;
