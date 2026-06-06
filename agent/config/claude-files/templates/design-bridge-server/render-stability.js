/**
 * Render Stability Utilities
 *
 * Provides mechanisms to detect when renders have stabilized before
 * proceeding with synchronization. Prevents race conditions and ensures
 * consistent transformation results.
 *
 * Key Principle: Make failures observable and recoverable, not silent and destructive.
 *
 * @module render-stability
 */

'use strict';

// =============================================================================
// CONSTANTS
// =============================================================================

/**
 * Default configuration
 */
const DEFAULT_CONFIG = {
  // Time without mutations to consider stable (ms)
  stabilityThreshold: 100,
  // Maximum time to wait for stability (ms)
  timeout: 5000,
  // Minimum wait time regardless of mutations (ms)
  minWaitTime: 50,
  // Check interval for non-DOM environments (ms)
  pollInterval: 50,
  // Whether to observe attributes
  observeAttributes: true,
  // Whether to observe character data
  observeCharacterData: true,
  // Whether to observe child list changes
  observeChildList: true,
  // Whether to observe subtree
  observeSubtree: true,
  // Attribute filter (null = all attributes)
  attributeFilter: null,
  // Debug mode
  debug: false
};

/**
 * Stability states
 */
const STABILITY_STATES = {
  IDLE: 'idle',
  OBSERVING: 'observing',
  STABILIZING: 'stabilizing',
  STABLE: 'stable',
  TIMEOUT: 'timeout',
  ERROR: 'error'
};

// =============================================================================
// RENDER STABILITY OBSERVER
// =============================================================================

/**
 * Observer for detecting render stability
 */
class RenderStabilityObserver {
  /**
   * Create a render stability observer
   * @param {Object} options - Configuration options
   */
  constructor(options = {}) {
    this.config = { ...DEFAULT_CONFIG, ...options };
    this.state = STABILITY_STATES.IDLE;

    // Timing
    this.lastMutationTime = 0;
    this.observeStartTime = 0;
    this.stabilityStartTime = 0;

    // Mutation tracking
    this.mutationCount = 0;
    this.mutationBatches = [];

    // Observer references
    this._observer = null;
    this._timeoutId = null;
    this._checkIntervalId = null;
    this._resolvers = [];

    // Stats
    this.stats = {
      totalMutations: 0,
      totalBatches: 0,
      timeToStable: 0,
      timedOut: false
    };
  }

  /**
   * Log debug message if debug mode enabled
   * @param {string} message - Message to log
   * @param {Object} data - Additional data
   * @private
   */
  _debug(message, data = {}) {
    if (this.config.debug) {
      console.log(`[RenderStability] ${message}`, data);
    }
  }

  /**
   * Check if MutationObserver is available
   * @returns {boolean} True if available
   */
  static isAvailable() {
    return typeof MutationObserver !== 'undefined';
  }

  /**
   * Create MutationObserver configuration
   * @returns {Object} Observer config
   * @private
   */
  _createObserverConfig() {
    const config = {
      childList: this.config.observeChildList,
      attributes: this.config.observeAttributes,
      characterData: this.config.observeCharacterData,
      subtree: this.config.observeSubtree
    };

    if (this.config.attributeFilter) {
      config.attributeFilter = this.config.attributeFilter;
    }

    return config;
  }

  /**
   * Handle mutation batch
   * @param {MutationRecord[]} mutations - Mutation records
   * @private
   */
  _handleMutations(mutations) {
    const now = Date.now();

    this.mutationCount += mutations.length;
    this.mutationBatches.push({
      timestamp: now,
      count: mutations.length,
      types: mutations.map(m => m.type)
    });

    this.lastMutationTime = now;
    this.state = STABILITY_STATES.OBSERVING;

    this._debug(`Mutations detected: ${mutations.length}`, {
      types: mutations.map(m => m.type)
    });

    // Reset stability timer
    this._scheduleStabilityCheck();
  }

  /**
   * Schedule stability check
   * @private
   */
  _scheduleStabilityCheck() {
    // Clear existing check
    if (this._checkIntervalId) {
      clearInterval(this._checkIntervalId);
    }

    // Set up periodic check
    this._checkIntervalId = setInterval(() => {
      this._checkStability();
    }, this.config.pollInterval);
  }

  /**
   * Check if stable
   * @private
   */
  _checkStability() {
    const now = Date.now();
    const timeSinceLastMutation = now - this.lastMutationTime;
    const totalTime = now - this.observeStartTime;

    // Check timeout
    if (totalTime >= this.config.timeout) {
      this._handleTimeout();
      return;
    }

    // Check if stable
    if (this.lastMutationTime > 0 &&
        timeSinceLastMutation >= this.config.stabilityThreshold &&
        totalTime >= this.config.minWaitTime) {

      this._handleStable();
    }
  }

  /**
   * Handle timeout
   * @private
   */
  _handleTimeout() {
    this._debug('Timeout reached', {
      totalMutations: this.mutationCount,
      elapsed: Date.now() - this.observeStartTime
    });

    this.state = STABILITY_STATES.TIMEOUT;
    this.stats.timedOut = true;
    this.stats.totalMutations = this.mutationCount;
    this.stats.totalBatches = this.mutationBatches.length;
    this.stats.timeToStable = Date.now() - this.observeStartTime;

    this._cleanup();
    this._resolveAll({ stable: false, reason: 'timeout', stats: this.stats });
  }

  /**
   * Handle stable state
   * @private
   */
  _handleStable() {
    this._debug('Stable state reached', {
      totalMutations: this.mutationCount,
      elapsed: Date.now() - this.observeStartTime
    });

    this.state = STABILITY_STATES.STABLE;
    this.stats.timedOut = false;
    this.stats.totalMutations = this.mutationCount;
    this.stats.totalBatches = this.mutationBatches.length;
    this.stats.timeToStable = Date.now() - this.observeStartTime;

    this._cleanup();
    this._resolveAll({ stable: true, reason: 'stable', stats: this.stats });
  }

  /**
   * Resolve all pending promises
   * @param {Object} result - Result object
   * @private
   */
  _resolveAll(result) {
    for (const resolver of this._resolvers) {
      resolver(result);
    }
    this._resolvers = [];
  }

  /**
   * Cleanup observer and timers
   * @private
   */
  _cleanup() {
    if (this._observer) {
      this._observer.disconnect();
      this._observer = null;
    }

    if (this._timeoutId) {
      clearTimeout(this._timeoutId);
      this._timeoutId = null;
    }

    if (this._checkIntervalId) {
      clearInterval(this._checkIntervalId);
      this._checkIntervalId = null;
    }
  }

  /**
   * Start observing a target element
   * @param {Element} target - DOM element to observe
   * @returns {Promise<Object>} Resolves when stable or timeout
   */
  observe(target) {
    return new Promise((resolve) => {
      // Store resolver
      this._resolvers.push(resolve);

      // Already observing? Just add resolver
      if (this.state === STABILITY_STATES.OBSERVING) {
        return;
      }

      // Reset state
      this.mutationCount = 0;
      this.mutationBatches = [];
      this.lastMutationTime = Date.now();
      this.observeStartTime = Date.now();
      this.state = STABILITY_STATES.OBSERVING;

      // Check if MutationObserver available
      if (!RenderStabilityObserver.isAvailable()) {
        this._debug('MutationObserver not available, using polling');
        this._pollForStability(resolve);
        return;
      }

      // Create observer
      this._observer = new MutationObserver((mutations) => {
        this._handleMutations(mutations);
      });

      // Start observing
      this._observer.observe(target, this._createObserverConfig());

      // Initial mutation to start tracking
      this.lastMutationTime = Date.now();

      // Schedule checks
      this._scheduleStabilityCheck();

      this._debug('Started observing', { target: target.nodeName });
    });
  }

  /**
   * Poll-based stability check (for non-DOM environments)
   * @param {Function} resolve - Promise resolver
   * @private
   */
  _pollForStability(resolve) {
    const startTime = Date.now();
    let lastCheckTime = startTime;

    const check = () => {
      const now = Date.now();
      const elapsed = now - startTime;

      if (elapsed >= this.config.timeout) {
        this.state = STABILITY_STATES.TIMEOUT;
        resolve({ stable: false, reason: 'timeout', stats: { timedOut: true } });
        return;
      }

      if (elapsed >= this.config.minWaitTime &&
          now - lastCheckTime >= this.config.stabilityThreshold) {
        this.state = STABILITY_STATES.STABLE;
        resolve({ stable: true, reason: 'poll', stats: { timedOut: false } });
        return;
      }

      lastCheckTime = now;
      setTimeout(check, this.config.pollInterval);
    };

    check();
  }

  /**
   * Stop observing
   */
  stop() {
    this._debug('Stopping observer');
    this.state = STABILITY_STATES.IDLE;
    this._cleanup();
    this._resolveAll({ stable: false, reason: 'stopped', stats: this.stats });
  }

  /**
   * Get current state
   * @returns {string} Current state
   */
  getState() {
    return this.state;
  }

  /**
   * Get mutation statistics
   * @returns {Object} Mutation stats
   */
  getStats() {
    return { ...this.stats };
  }

  /**
   * Get mutation batches
   * @returns {Object[]} Mutation batch details
   */
  getMutationBatches() {
    return [...this.mutationBatches];
  }
}

// =============================================================================
// CONVENIENCE FUNCTIONS
// =============================================================================

/**
 * Wait for an element's render to stabilize
 * @param {Element} element - DOM element to observe
 * @param {Object} options - Configuration options
 * @returns {Promise<Object>} Stability result
 */
function waitForStableRender(element, options = {}) {
  const observer = new RenderStabilityObserver(options);
  return observer.observe(element);
}

/**
 * Wait for document render to stabilize
 * @param {Object} options - Configuration options
 * @returns {Promise<Object>} Stability result
 */
function waitForDocumentStable(options = {}) {
  if (typeof document === 'undefined') {
    return Promise.resolve({ stable: true, reason: 'no-document' });
  }
  return waitForStableRender(document.body, options);
}

/**
 * Simple delay-based wait (fallback for non-DOM environments)
 * @param {number} ms - Milliseconds to wait
 * @returns {Promise<void>} Resolves after delay
 */
function waitMs(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Wait for a condition to be true
 * @param {Function} condition - Condition function returning boolean
 * @param {Object} options - Wait options
 * @param {number} options.timeout - Maximum wait time (ms)
 * @param {number} options.interval - Check interval (ms)
 * @returns {Promise<boolean>} True if condition met, false if timeout
 */
async function waitForCondition(condition, options = {}) {
  const { timeout = 5000, interval = 50 } = options;
  const startTime = Date.now();

  while (Date.now() - startTime < timeout) {
    try {
      if (await condition()) {
        return true;
      }
    } catch (e) {
      // Condition threw, continue waiting
    }
    await waitMs(interval);
  }

  return false;
}

/**
 * Wait for multiple elements to stabilize
 * @param {Element[]} elements - Array of elements
 * @param {Object} options - Configuration options
 * @returns {Promise<Object[]>} Array of stability results
 */
async function waitForAllStable(elements, options = {}) {
  const results = await Promise.all(
    elements.map(el => waitForStableRender(el, options))
  );
  return results;
}

// =============================================================================
// NODE.JS COMPATIBLE UTILITIES
// =============================================================================

/**
 * Create a stability check for non-DOM scenarios (like virtual DOM)
 * @param {Function} getState - Function returning current state
 * @param {Object} options - Options
 * @returns {Promise<Object>} Stability result
 */
async function waitForStateStable(getState, options = {}) {
  const {
    stabilityThreshold = 100,
    timeout = 5000,
    interval = 50,
    equalityFn = (a, b) => JSON.stringify(a) === JSON.stringify(b)
  } = options;

  const startTime = Date.now();
  let lastState = null;
  let lastChangeTime = startTime;
  let stateChanges = 0;

  while (Date.now() - startTime < timeout) {
    const currentState = await getState();

    if (lastState === null || !equalityFn(lastState, currentState)) {
      lastState = currentState;
      lastChangeTime = Date.now();
      stateChanges++;
    }

    const timeSinceLastChange = Date.now() - lastChangeTime;
    if (timeSinceLastChange >= stabilityThreshold) {
      return {
        stable: true,
        reason: 'stable',
        stats: { stateChanges, timeToStable: Date.now() - startTime }
      };
    }

    await waitMs(interval);
  }

  return {
    stable: false,
    reason: 'timeout',
    stats: { stateChanges, timedOut: true }
  };
}

/**
 * Debounced stability check
 * Creates a function that waits for calls to stop before executing
 * @param {Function} fn - Function to debounce
 * @param {number} wait - Wait time (ms)
 * @returns {Function} Debounced function with promise support
 */
function createDebouncedStabilityCheck(fn, wait = 100) {
  let timeoutId = null;
  let resolver = null;

  const debounced = (...args) => {
    if (timeoutId) {
      clearTimeout(timeoutId);
    }

    return new Promise((resolve) => {
      resolver = resolve;

      timeoutId = setTimeout(async () => {
        try {
          const result = await fn(...args);
          resolve({ stable: true, result });
        } catch (error) {
          resolve({ stable: false, error: error.message });
        }
      }, wait);
    });
  };

  debounced.cancel = () => {
    if (timeoutId) {
      clearTimeout(timeoutId);
      timeoutId = null;
    }
    if (resolver) {
      resolver({ stable: false, reason: 'cancelled' });
    }
  };

  return debounced;
}

/**
 * Retry with stability check
 * @param {Function} fn - Async function to retry
 * @param {Object} options - Retry options
 * @returns {Promise<*>} Function result
 */
async function retryWithStability(fn, options = {}) {
  const {
    maxRetries = 3,
    retryDelay = 100,
    stabilityWait = 50,
    onRetry = null
  } = options;

  let lastError = null;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      // Wait for stability before attempt
      if (attempt > 0) {
        await waitMs(stabilityWait);
      }

      const result = await fn();
      return result;
    } catch (error) {
      lastError = error;

      if (onRetry) {
        onRetry(error, attempt);
      }

      if (attempt < maxRetries) {
        await waitMs(retryDelay * (attempt + 1));
      }
    }
  }

  throw lastError;
}

// =============================================================================
// INTEGRATION HELPERS
// =============================================================================

/**
 * Create a stability-aware transformation wrapper
 * Ensures render stability before and after transformation
 * @param {Function} transformFn - Transformation function
 * @param {Object} options - Stability options
 * @returns {Function} Wrapped transformation function
 */
function createStableTransformer(transformFn, options = {}) {
  const {
    preStabilityWait = 50,
    postStabilityWait = 100,
    stabilityThreshold = 100,
    timeout = 5000,
    onPreStability = null,
    onPostStability = null,
    onError = null
  } = options;

  return async function stableTransform(...args) {
    const context = {
      startTime: Date.now(),
      preStabilityResult: null,
      transformResult: null,
      postStabilityResult: null,
      error: null
    };

    try {
      // Pre-transformation stability wait
      await waitMs(preStabilityWait);

      // Check pre-stability if callback provided
      if (onPreStability) {
        context.preStabilityResult = await waitForStateStable(
          () => onPreStability(...args),
          { stabilityThreshold, timeout }
        );
      }

      // Execute transformation
      context.transformResult = await transformFn(...args);

      // Post-transformation stability wait
      await waitMs(postStabilityWait);

      // Check post-stability if callback provided
      if (onPostStability) {
        context.postStabilityResult = await waitForStateStable(
          () => onPostStability(context.transformResult, ...args),
          { stabilityThreshold, timeout }
        );
      }

      context.duration = Date.now() - context.startTime;
      return {
        success: true,
        result: context.transformResult,
        context
      };
    } catch (error) {
      context.error = error;
      context.duration = Date.now() - context.startTime;

      if (onError) {
        onError(error, context);
      }

      return {
        success: false,
        error: error.message,
        context
      };
    }
  };
}

/**
 * Create a batch processor with stability checks between items
 * @param {Function} processFn - Function to process each item
 * @param {Object} options - Batch options
 * @returns {Function} Batch processor function
 */
function createStableBatchProcessor(processFn, options = {}) {
  const {
    batchSize = 10,
    stabilityWait = 50,
    continueOnError = true,
    onProgress = null,
    onItemComplete = null,
    onItemError = null
  } = options;

  return async function processBatch(items) {
    const results = [];
    const errors = [];
    let processed = 0;

    for (let i = 0; i < items.length; i += batchSize) {
      const batch = items.slice(i, i + batchSize);

      for (const item of batch) {
        try {
          const result = await processFn(item, processed, items.length);
          results.push({ success: true, item, result });

          if (onItemComplete) {
            onItemComplete(item, result, processed);
          }
        } catch (error) {
          const errorInfo = { success: false, item, error: error.message };
          errors.push(errorInfo);
          results.push(errorInfo);

          if (onItemError) {
            onItemError(item, error, processed);
          }

          if (!continueOnError) {
            return {
              completed: false,
              processed,
              total: items.length,
              results,
              errors
            };
          }
        }

        processed++;

        if (onProgress) {
          onProgress(processed, items.length);
        }
      }

      // Stability wait between batches
      if (i + batchSize < items.length) {
        await waitMs(stabilityWait);
      }
    }

    return {
      completed: true,
      processed,
      total: items.length,
      results,
      errors,
      successCount: results.filter(r => r.success).length,
      errorCount: errors.length
    };
  };
}

/**
 * Create a sync operation with automatic retry and stability checks
 * @param {Function} syncFn - Sync function
 * @param {Object} options - Sync options
 * @returns {Function} Stability-aware sync function
 */
function createStableSyncOperation(syncFn, options = {}) {
  const {
    maxRetries = 3,
    retryDelay = 100,
    stabilityThreshold = 100,
    timeout = 5000,
    validateResult = null,
    onRetry = null,
    onSuccess = null,
    onFailure = null
  } = options;

  return async function stableSync(...args) {
    const context = {
      attempts: 0,
      startTime: Date.now(),
      retries: [],
      finalResult: null,
      error: null
    };

    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      context.attempts = attempt + 1;

      try {
        // Stability wait before attempt (except first)
        if (attempt > 0) {
          await waitMs(stabilityThreshold);
        }

        // Execute sync
        const result = await syncFn(...args);

        // Validate result if validator provided
        if (validateResult) {
          const isValid = await validateResult(result);
          if (!isValid) {
            throw new Error('Sync result validation failed');
          }
        }

        // Success
        context.finalResult = result;
        context.duration = Date.now() - context.startTime;

        if (onSuccess) {
          onSuccess(result, context);
        }

        return {
          success: true,
          result,
          context
        };
      } catch (error) {
        context.retries.push({
          attempt,
          error: error.message,
          timestamp: Date.now()
        });

        if (onRetry && attempt < maxRetries) {
          onRetry(error, attempt, context);
        }

        if (attempt < maxRetries) {
          await waitMs(retryDelay * (attempt + 1));
        } else {
          context.error = error;
          context.duration = Date.now() - context.startTime;

          if (onFailure) {
            onFailure(error, context);
          }

          return {
            success: false,
            error: error.message,
            context
          };
        }
      }
    }
  };
}

/**
 * Monitor stability of a value over time
 * @param {Function} getValue - Function returning current value
 * @param {Object} options - Monitor options
 * @returns {Object} Monitor controller
 */
function createStabilityMonitor(getValue, options = {}) {
  const {
    interval = 100,
    stabilityThreshold = 3,
    equalityFn = (a, b) => JSON.stringify(a) === JSON.stringify(b),
    onChange = null,
    onStable = null,
    onUnstable = null
  } = options;

  let lastValue = null;
  let stableCount = 0;
  let isStable = false;
  let intervalId = null;
  let history = [];

  const check = async () => {
    try {
      const currentValue = await getValue();
      const valueChanged = lastValue !== null && !equalityFn(lastValue, currentValue);

      if (valueChanged) {
        stableCount = 0;
        if (isStable) {
          isStable = false;
          if (onUnstable) {
            onUnstable(currentValue, lastValue);
          }
        }
        if (onChange) {
          onChange(currentValue, lastValue);
        }
      } else {
        stableCount++;
        if (!isStable && stableCount >= stabilityThreshold) {
          isStable = true;
          if (onStable) {
            onStable(currentValue, stableCount);
          }
        }
      }

      history.push({
        timestamp: Date.now(),
        value: currentValue,
        stable: isStable,
        stableCount
      });

      // Keep history bounded
      if (history.length > 100) {
        history = history.slice(-100);
      }

      lastValue = currentValue;
    } catch (error) {
      // Error getting value, reset stability
      stableCount = 0;
      if (isStable) {
        isStable = false;
        if (onUnstable) {
          onUnstable(null, lastValue, error);
        }
      }
    }
  };

  return {
    start() {
      if (!intervalId) {
        intervalId = setInterval(check, interval);
        check(); // Initial check
      }
      return this;
    },

    stop() {
      if (intervalId) {
        clearInterval(intervalId);
        intervalId = null;
      }
      return this;
    },

    isRunning() {
      return intervalId !== null;
    },

    isStable() {
      return isStable;
    },

    getStableCount() {
      return stableCount;
    },

    getLastValue() {
      return lastValue;
    },

    getHistory() {
      return [...history];
    },

    async waitForStable(timeout = 5000) {
      if (isStable) {
        return { stable: true, value: lastValue };
      }

      const startTime = Date.now();
      return new Promise((resolve) => {
        const checkInterval = setInterval(() => {
          if (isStable) {
            clearInterval(checkInterval);
            resolve({ stable: true, value: lastValue });
          } else if (Date.now() - startTime >= timeout) {
            clearInterval(checkInterval);
            resolve({ stable: false, reason: 'timeout' });
          }
        }, interval);
      });
    },

    reset() {
      lastValue = null;
      stableCount = 0;
      isStable = false;
      history = [];
      return this;
    }
  };
}

/**
 * Queue operations with stability-aware execution
 * @param {Object} options - Queue options
 * @returns {Object} Queue controller
 */
function createStabilityQueue(options = {}) {
  const {
    concurrency = 1,
    stabilityWait = 50,
    onTaskStart = null,
    onTaskComplete = null,
    onTaskError = null,
    onQueueEmpty = null
  } = options;

  const queue = [];
  let running = 0;
  let paused = false;
  const results = [];

  const processNext = async () => {
    if (paused || running >= concurrency || queue.length === 0) {
      if (queue.length === 0 && running === 0 && onQueueEmpty) {
        onQueueEmpty(results);
      }
      return;
    }

    running++;
    const task = queue.shift();

    if (onTaskStart) {
      onTaskStart(task.id, queue.length);
    }

    try {
      // Stability wait before task
      await waitMs(stabilityWait);

      const result = await task.fn();
      task.resolve({ success: true, result });
      results.push({ id: task.id, success: true, result });

      if (onTaskComplete) {
        onTaskComplete(task.id, result);
      }
    } catch (error) {
      task.reject(error);
      results.push({ id: task.id, success: false, error: error.message });

      if (onTaskError) {
        onTaskError(task.id, error);
      }
    } finally {
      running--;
      processNext();
    }
  };

  let taskIdCounter = 0;

  return {
    add(fn, id = null) {
      const taskId = id || `task-${++taskIdCounter}`;
      return new Promise((resolve, reject) => {
        queue.push({ id: taskId, fn, resolve, reject });
        processNext();
      });
    },

    addAll(fns) {
      return Promise.all(fns.map(fn => this.add(fn)));
    },

    pause() {
      paused = true;
      return this;
    },

    resume() {
      paused = false;
      processNext();
      return this;
    },

    clear() {
      const cleared = queue.length;
      queue.length = 0;
      return cleared;
    },

    getQueueLength() {
      return queue.length;
    },

    getRunningCount() {
      return running;
    },

    isPaused() {
      return paused;
    },

    getResults() {
      return [...results];
    }
  };
}

// =============================================================================
// EXPORTS
// =============================================================================

module.exports = {
  // Classes
  RenderStabilityObserver,
  // Constants
  DEFAULT_CONFIG,
  STABILITY_STATES,
  // Main functions
  waitForStableRender,
  waitForDocumentStable,
  // Utility functions
  waitMs,
  waitForCondition,
  waitForAllStable,
  // Node.js compatible
  waitForStateStable,
  createDebouncedStabilityCheck,
  retryWithStability,
  // Integration helpers
  createStableTransformer,
  createStableBatchProcessor,
  createStableSyncOperation,
  createStabilityMonitor,
  createStabilityQueue
};
