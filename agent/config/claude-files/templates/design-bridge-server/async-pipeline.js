/**
 * Async Pipeline Module
 * Phase 3 - Sprints 159-164: Async Operations & Parallel Processing
 *
 * Provides utilities for:
 * - Parallel batch processing
 * - Rate limiting
 * - Retry with exponential backoff
 * - Progress tracking
 * - Cancellation support
 */

const { EventEmitter } = require('events');
const { createLogger } = require('./unified-logger');

const logger = createLogger('async-pipeline');

// =============================================================================
// ASYNC UTILITIES
// =============================================================================

/**
 * Sleep for specified milliseconds
 */
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Create a deferred promise
 */
function createDeferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/**
 * Timeout wrapper for promises
 */
function withTimeout(promise, ms, message = 'Operation timed out') {
  return Promise.race([
    promise,
    new Promise((_, reject) =>
      setTimeout(() => reject(new Error(message)), ms)
    )
  ]);
}

/**
 * Retry with exponential backoff
 */
async function retry(fn, options = {}) {
  const {
    maxAttempts = 3,
    baseDelay = 1000,
    maxDelay = 30000,
    factor = 2,
    shouldRetry = () => true,
    onRetry = () => {}
  } = options;

  let lastError;

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      return await fn(attempt);
    } catch (error) {
      lastError = error;

      if (attempt === maxAttempts || !shouldRetry(error, attempt)) {
        throw error;
      }

      const delay = Math.min(baseDelay * Math.pow(factor, attempt - 1), maxDelay);
      logger.debug('Retry attempt', { attempt, maxAttempts, delay, error: error.message });
      onRetry(error, attempt, delay);

      await sleep(delay);
    }
  }

  throw lastError;
}

// =============================================================================
// RATE LIMITER
// =============================================================================

/**
 * Token bucket rate limiter
 */
class RateLimiter {
  constructor(options = {}) {
    this.tokensPerInterval = options.tokensPerInterval || 10;
    this.interval = options.interval || 1000; // 1 second
    this.maxTokens = options.maxTokens || this.tokensPerInterval;

    this.tokens = this.maxTokens;
    this.lastRefill = Date.now();
    this.queue = [];
    this.processing = false;
  }

  _refillTokens() {
    const now = Date.now();
    const elapsed = now - this.lastRefill;
    const tokensToAdd = Math.floor(elapsed / this.interval) * this.tokensPerInterval;

    if (tokensToAdd > 0) {
      this.tokens = Math.min(this.maxTokens, this.tokens + tokensToAdd);
      this.lastRefill = now;
    }
  }

  async acquire(tokens = 1) {
    return new Promise((resolve) => {
      this.queue.push({ tokens, resolve });
      this._processQueue();
    });
  }

  async _processQueue() {
    if (this.processing) return;
    this.processing = true;

    while (this.queue.length > 0) {
      this._refillTokens();

      const { tokens, resolve } = this.queue[0];

      if (this.tokens >= tokens) {
        this.tokens -= tokens;
        this.queue.shift();
        resolve();
      } else {
        // Wait for next refill
        const waitTime = Math.ceil((tokens - this.tokens) / this.tokensPerInterval * this.interval);
        await sleep(waitTime);
      }
    }

    this.processing = false;
  }

  getStats() {
    return {
      tokens: this.tokens,
      maxTokens: this.maxTokens,
      queueLength: this.queue.length
    };
  }
}

// =============================================================================
// BATCH PROCESSOR
// =============================================================================

/**
 * Parallel batch processor with concurrency control
 */
class BatchProcessor extends EventEmitter {
  constructor(options = {}) {
    super();

    this.concurrency = options.concurrency || 5;
    this.rateLimiter = options.rateLimiter || null;
    this.stopOnError = options.stopOnError || false;
    this.retryOptions = options.retry || null;

    this.active = 0;
    this.completed = 0;
    this.failed = 0;
    this.cancelled = false;
    this.results = [];
    this.errors = [];

    // Prevent unhandled 'error' event crash
    this.on('error', () => {});
  }

  /**
   * Process items in parallel batches
   */
  async process(items, processFn) {
    this.cancelled = false;
    this.completed = 0;
    this.failed = 0;
    this.results = [];
    this.errors = [];

    const total = items.length;
    const queue = [...items.entries()];

    logger.info('Batch processing started', { total, concurrency: this.concurrency });
    this.emit('start', { total });

    const workers = [];
    for (let i = 0; i < this.concurrency; i++) {
      workers.push(this._worker(queue, processFn, total));
    }

    await Promise.all(workers);

    const summary = {
      total,
      completed: this.completed,
      failed: this.failed,
      cancelled: this.cancelled
    };

    logger.info('Batch processing completed', summary);
    this.emit('complete', summary);

    return {
      results: this.results,
      errors: this.errors,
      summary
    };
  }

  async _worker(queue, processFn, total) {
    while (queue.length > 0 && !this.cancelled) {
      const entry = queue.shift();
      if (!entry) break;

      const [index, item] = entry;
      this.active++;

      try {
        // Rate limiting
        if (this.rateLimiter) {
          await this.rateLimiter.acquire();
        }

        // Process with optional retry
        let result;
        if (this.retryOptions) {
          result = await retry(() => processFn(item, index), this.retryOptions);
        } else {
          result = await processFn(item, index);
        }

        this.results[index] = result;
        this.completed++;

        this.emit('progress', {
          index,
          completed: this.completed,
          failed: this.failed,
          total,
          percent: Math.round((this.completed + this.failed) / total * 100)
        });

      } catch (error) {
        this.errors.push({ index, item, error });
        this.failed++;

        this.emit('error', { index, item, error });

        if (this.stopOnError) {
          this.cancel();
        }
      } finally {
        this.active--;
      }
    }
  }

  cancel() {
    this.cancelled = true;
    this.emit('cancelled');
  }

  getProgress() {
    return {
      active: this.active,
      completed: this.completed,
      failed: this.failed,
      cancelled: this.cancelled
    };
  }
}

// =============================================================================
// ASYNC QUEUE
// =============================================================================

/**
 * Priority async queue
 */
class AsyncQueue extends EventEmitter {
  constructor(options = {}) {
    super();

    this.concurrency = options.concurrency || 1;
    this.paused = false;
    this.queue = [];
    this.active = 0;
    this.processed = 0;
  }

  /**
   * Add task to queue
   */
  push(task, priority = 0) {
    return new Promise((resolve, reject) => {
      this.queue.push({
        task,
        priority,
        resolve,
        reject,
        addedAt: Date.now()
      });

      // Sort by priority (higher first)
      this.queue.sort((a, b) => b.priority - a.priority);

      this._process();
    });
  }

  /**
   * Add multiple tasks
   */
  pushAll(tasks, priority = 0) {
    return Promise.all(tasks.map(task => this.push(task, priority)));
  }

  async _process() {
    if (this.paused) return;
    if (this.active >= this.concurrency) return;
    if (this.queue.length === 0) return;

    const item = this.queue.shift();
    this.active++;

    try {
      const result = await item.task();
      item.resolve(result);
      this.processed++;
      this.emit('completed', { result, processed: this.processed });
    } catch (error) {
      item.reject(error);
      this.emit('error', { error });
    } finally {
      this.active--;
      this._process();
    }
  }

  pause() {
    this.paused = true;
    this.emit('paused');
  }

  resume() {
    this.paused = false;
    this.emit('resumed');
    this._process();
  }

  clear() {
    const cleared = this.queue.length;
    this.queue.forEach(item => item.reject(new Error('Queue cleared')));
    this.queue = [];
    return cleared;
  }

  getStats() {
    return {
      queued: this.queue.length,
      active: this.active,
      processed: this.processed,
      paused: this.paused
    };
  }
}

// =============================================================================
// PIPELINE STAGES
// =============================================================================

/**
 * Pipeline stage for chaining async operations
 */
class PipelineStage {
  constructor(name, handler, options = {}) {
    this.name = name;
    this.handler = handler;
    this.timeout = options.timeout || 30000;
    this.retryOptions = options.retry || null;
    this.onError = options.onError || null;
  }

  async execute(input, context = {}) {
    const start = Date.now();

    try {
      let result;

      if (this.retryOptions) {
        result = await retry(
          () => withTimeout(this.handler(input, context), this.timeout),
          this.retryOptions
        );
      } else {
        result = await withTimeout(this.handler(input, context), this.timeout);
      }

      const duration = Date.now() - start;
      logger.debug('Pipeline stage completed', { stage: this.name, duration });

      return result;

    } catch (error) {
      const duration = Date.now() - start;
      logger.error('Pipeline stage failed', { stage: this.name, duration, error: error.message });

      if (this.onError) {
        return this.onError(error, input, context);
      }

      throw error;
    }
  }
}

/**
 * Multi-stage async pipeline
 */
class Pipeline extends EventEmitter {
  constructor(name, options = {}) {
    super();

    this.name = name;
    this.stages = [];
    this.middleware = [];
    this.errorHandlers = [];
  }

  /**
   * Add a stage to the pipeline
   */
  addStage(name, handler, options = {}) {
    this.stages.push(new PipelineStage(name, handler, options));
    return this;
  }

  /**
   * Add middleware (runs before each stage)
   */
  use(middleware) {
    this.middleware.push(middleware);
    return this;
  }

  /**
   * Add error handler
   */
  onError(handler) {
    this.errorHandlers.push(handler);
    return this;
  }

  /**
   * Execute the pipeline
   */
  async execute(input, context = {}) {
    let current = input;
    const results = [];
    const pipelineContext = {
      ...context,
      pipeline: this.name,
      startedAt: Date.now()
    };

    logger.info('Pipeline started', { pipeline: this.name, stages: this.stages.length });
    this.emit('start', { input, context: pipelineContext });

    for (let i = 0; i < this.stages.length; i++) {
      const stage = this.stages[i];

      try {
        // Run middleware
        for (const mw of this.middleware) {
          current = await mw(current, stage, pipelineContext);
        }

        // Execute stage
        this.emit('stage:start', { stage: stage.name, input: current });
        current = await stage.execute(current, pipelineContext);
        results.push({ stage: stage.name, result: current });
        this.emit('stage:complete', { stage: stage.name, result: current });

      } catch (error) {
        // Run error handlers
        let handled = false;
        for (const handler of this.errorHandlers) {
          const recovery = await handler(error, stage, current, pipelineContext);
          if (recovery !== undefined) {
            current = recovery;
            handled = true;
            break;
          }
        }

        if (!handled) {
          this.emit('error', { stage: stage.name, error });
          throw error;
        }
      }
    }

    const duration = Date.now() - pipelineContext.startedAt;
    logger.info('Pipeline completed', { pipeline: this.name, duration });
    this.emit('complete', { result: current, results, duration });

    return current;
  }
}

// =============================================================================
// PARALLEL EXECUTION HELPERS
// =============================================================================

/**
 * Execute functions in parallel with concurrency limit
 */
async function parallel(fns, concurrency = 5) {
  const processor = new BatchProcessor({ concurrency });
  const result = await processor.process(fns, fn => fn());
  return result.results;
}

/**
 * Map with concurrency limit
 */
async function mapAsync(items, fn, concurrency = 5) {
  const processor = new BatchProcessor({ concurrency });
  return processor.process(items, fn);
}

/**
 * Filter with async predicate
 */
async function filterAsync(items, predicate, concurrency = 5) {
  const results = await mapAsync(
    items,
    async (item, index) => ({ item, include: await predicate(item, index) }),
    concurrency
  );

  return results.results
    .filter(r => r && r.include)
    .map(r => r.item);
}

/**
 * Reduce with async reducer
 */
async function reduceAsync(items, reducer, initial) {
  let accumulator = initial;

  for (let i = 0; i < items.length; i++) {
    accumulator = await reducer(accumulator, items[i], i);
  }

  return accumulator;
}

/**
 * Execute with timeout and fallback
 */
async function withFallback(fn, fallback, timeout = 5000) {
  try {
    return await withTimeout(fn(), timeout);
  } catch (error) {
    logger.warn('Operation failed, using fallback', { error: error.message });
    return typeof fallback === 'function' ? fallback(error) : fallback;
  }
}

/**
 * Debounce async function
 */
function debounceAsync(fn, wait = 300) {
  let timeout = null;
  let pending = null;

  return function (...args) {
    if (timeout) {
      clearTimeout(timeout);
    }

    if (!pending) {
      pending = createDeferred();
    }

    timeout = setTimeout(async () => {
      try {
        const result = await fn.apply(this, args);
        pending.resolve(result);
      } catch (error) {
        pending.reject(error);
      }
      pending = null;
      timeout = null;
    }, wait);

    return pending.promise;
  };
}

/**
 * Throttle async function
 */
function throttleAsync(fn, limit = 1000) {
  let lastRun = 0;
  let pending = null;

  return async function (...args) {
    const now = Date.now();

    if (now - lastRun >= limit) {
      lastRun = now;
      return fn.apply(this, args);
    }

    if (!pending) {
      pending = new Promise(resolve => {
        setTimeout(async () => {
          lastRun = Date.now();
          pending = null;
          resolve(await fn.apply(this, args));
        }, limit - (now - lastRun));
      });
    }

    return pending;
  };
}

// =============================================================================
// EXPORTS
// =============================================================================

module.exports = {
  // Utilities
  sleep,
  createDeferred,
  withTimeout,
  retry,

  // Rate limiting
  RateLimiter,

  // Batch processing
  BatchProcessor,

  // Queue
  AsyncQueue,

  // Pipeline
  PipelineStage,
  Pipeline,

  // Parallel helpers
  parallel,
  mapAsync,
  filterAsync,
  reduceAsync,
  withFallback,
  debounceAsync,
  throttleAsync
};
