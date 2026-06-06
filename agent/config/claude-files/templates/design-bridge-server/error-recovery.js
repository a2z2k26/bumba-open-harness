/**
 * Error Recovery System
 * Sprint 21: Robust error recovery for design bridge operations
 *
 * Features:
 * - Automatic retry with exponential backoff
 * - Partial sync fallback
 * - Cache restoration
 * - Error categorization and logging
 * - Recovery strategy selection
 */

const EventEmitter = require('events');
const fs = require('fs').promises;
const path = require('path');

/**
 * Error Categories
 */
const ErrorCategory = {
  NETWORK: 'network',
  VALIDATION: 'validation',
  FILESYSTEM: 'filesystem',
  PROCESSING: 'processing',
  TIMEOUT: 'timeout',
  UNKNOWN: 'unknown'
};

/**
 * Recovery Strategies
 */
const RecoveryStrategy = {
  RETRY: 'retry',
  PARTIAL_SYNC: 'partial_sync',
  CACHE_RESTORE: 'cache_restore',
  MANUAL_INTERVENTION: 'manual_intervention',
  SKIP: 'skip'
};

class ErrorRecoverySystem extends EventEmitter {
  constructor(options = {}) {
    super();

    this.config = {
      maxRetries: options.maxRetries || 3,
      retryDelay: options.retryDelay || 1000, // 1 second
      backoffMultiplier: options.backoffMultiplier || 2,
      enableCaching: options.enableCaching !== false,
      cacheDir: options.cacheDir || '.design/cache',
      ...options
    };

    // Error tracking
    this.errorLog = [];
    this.recoveryAttempts = new Map();
    this.failedOperations = new Map();
  }

  /**
   * Execute operation with error recovery
   */
  async executeWithRecovery(operation, context = {}) {
    const operationId = context.id || `op_${Date.now()}`;
    let lastError = null;
    let retryCount = 0;

    while (retryCount <= this.config.maxRetries) {
      try {
        // Track attempt
        this.trackAttempt(operationId, retryCount);

        // Execute operation
        const result = await operation();

        // Clear any previous failures for this operation
        this.clearFailure(operationId);

        // Emit success
        this.emit('recovery:success', {
          operationId,
          retries: retryCount,
          context
        });

        return { success: true, result, retries: retryCount };

      } catch (error) {
        lastError = error;
        const category = this.categorizeError(error);

        // Log error
        this.logError(operationId, error, category, retryCount);

        // Determine recovery strategy
        const strategy = this.selectRecoveryStrategy(error, category, retryCount);

        // Emit error event
        this.emit('recovery:error', {
          operationId,
          error,
          category,
          strategy,
          retry: retryCount,
          context
        });

        // Apply recovery strategy
        const recovered = await this.applyRecoveryStrategy(
          strategy,
          operation,
          error,
          context,
          retryCount
        );

        if (recovered) {
          return recovered;
        }

        // If not recovered and strategy is not retry, bail out
        if (strategy !== RecoveryStrategy.RETRY) {
          break;
        }

        // Wait before retry with exponential backoff
        if (retryCount < this.config.maxRetries) {
          const delay = this.calculateBackoffDelay(retryCount);
          await this.sleep(delay);
          retryCount++;
        } else {
          break;
        }
      }
    }

    // All recovery attempts failed
    this.recordFailure(operationId, lastError, context);

    this.emit('recovery:failed', {
      operationId,
      error: lastError,
      retries: retryCount,
      context
    });

    return {
      success: false,
      error: lastError,
      retries: retryCount,
      requiresManualIntervention: true
    };
  }

  /**
   * Categorize error type
   */
  categorizeError(error) {
    const message = error.message?.toLowerCase() || '';
    const code = error.code?.toLowerCase() || '';

    if (code.includes('enotfound') || code.includes('econnrefused') || message.includes('network')) {
      return ErrorCategory.NETWORK;
    }

    if (message.includes('timeout')) {
      return ErrorCategory.TIMEOUT;
    }

    if (code.includes('enoent') || code.includes('eacces') || message.includes('file')) {
      return ErrorCategory.FILESYSTEM;
    }

    if (message.includes('validation') || message.includes('invalid')) {
      return ErrorCategory.VALIDATION;
    }

    if (message.includes('process') || message.includes('transform')) {
      return ErrorCategory.PROCESSING;
    }

    return ErrorCategory.UNKNOWN;
  }

  /**
   * Select appropriate recovery strategy
   */
  selectRecoveryStrategy(error, category, retryCount) {
    // Network errors: retry with backoff
    if (category === ErrorCategory.NETWORK || category === ErrorCategory.TIMEOUT) {
      return retryCount < this.config.maxRetries
        ? RecoveryStrategy.RETRY
        : RecoveryStrategy.MANUAL_INTERVENTION;
    }

    // Validation errors: no retry, manual intervention
    if (category === ErrorCategory.VALIDATION) {
      return RecoveryStrategy.MANUAL_INTERVENTION;
    }

    // Filesystem errors: try cache restore
    if (category === ErrorCategory.FILESYSTEM && this.config.enableCaching) {
      return RecoveryStrategy.CACHE_RESTORE;
    }

    // Processing errors: partial sync fallback
    if (category === ErrorCategory.PROCESSING) {
      return RecoveryStrategy.PARTIAL_SYNC;
    }

    // Default: retry
    return retryCount < this.config.maxRetries
      ? RecoveryStrategy.RETRY
      : RecoveryStrategy.MANUAL_INTERVENTION;
  }

  /**
   * Apply recovery strategy
   */
  async applyRecoveryStrategy(strategy, operation, error, context, retryCount) {
    switch (strategy) {
      case RecoveryStrategy.RETRY:
        // Will be handled by outer loop
        return null;

      case RecoveryStrategy.PARTIAL_SYNC:
        return await this.attemptPartialSync(context);

      case RecoveryStrategy.CACHE_RESTORE:
        return await this.attemptCacheRestore(context);

      case RecoveryStrategy.SKIP:
        return { success: true, skipped: true, reason: 'Error skipped by strategy' };

      case RecoveryStrategy.MANUAL_INTERVENTION:
        // Emit event for manual handling
        this.emit('recovery:manual_required', {
          error,
          context,
          retryCount
        });
        return null;

      default:
        return null;
    }
  }

  /**
   * Attempt partial sync (fallback to essential data only)
   */
  async attemptPartialSync(context) {
    try {
      // If original operation has partial data available
      if (context.partialData) {
        console.log('⚠️  Attempting partial sync with available data');

        return {
          success: true,
          result: context.partialData,
          partial: true,
          message: 'Partial sync completed with available data'
        };
      }

      return null;
    } catch (error) {
      console.error('Partial sync failed:', error);
      return null;
    }
  }

  /**
   * Attempt cache restore
   */
  async attemptCacheRestore(context) {
    if (!this.config.enableCaching) {
      return null;
    }

    try {
      const cacheKey = context.cacheKey || context.id;
      const cachePath = path.join(this.config.cacheDir, `${cacheKey}.json`);

      const cacheData = await fs.readFile(cachePath, 'utf8');
      const cachedResult = JSON.parse(cacheData);

      console.log('✓ Restored from cache:', cacheKey);

      return {
        success: true,
        result: cachedResult,
        fromCache: true,
        message: 'Restored from cache'
      };

    } catch (error) {
      console.log('Cache restore failed:', error.message);
      return null;
    }
  }

  /**
   * Calculate exponential backoff delay
   */
  calculateBackoffDelay(retryCount) {
    return this.config.retryDelay * Math.pow(this.config.backoffMultiplier, retryCount);
  }

  /**
   * Sleep helper
   */
  sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  /**
   * Track recovery attempt
   */
  trackAttempt(operationId, retryCount) {
    if (!this.recoveryAttempts.has(operationId)) {
      this.recoveryAttempts.set(operationId, []);
    }

    this.recoveryAttempts.get(operationId).push({
      attempt: retryCount,
      timestamp: new Date().toISOString()
    });
  }

  /**
   * Log error
   */
  logError(operationId, error, category, retryCount) {
    const errorEntry = {
      operationId,
      error: {
        message: error.message,
        code: error.code,
        stack: error.stack
      },
      category,
      retryCount,
      timestamp: new Date().toISOString()
    };

    this.errorLog.push(errorEntry);

    // Limit log size
    if (this.errorLog.length > 1000) {
      this.errorLog = this.errorLog.slice(-500);
    }
  }

  /**
   * Record operation failure
   */
  recordFailure(operationId, error, context) {
    this.failedOperations.set(operationId, {
      error: {
        message: error.message,
        code: error.code
      },
      context,
      timestamp: new Date().toISOString()
    });
  }

  /**
   * Clear operation failure
   */
  clearFailure(operationId) {
    this.failedOperations.delete(operationId);
    this.recoveryAttempts.delete(operationId);
  }

  /**
   * Get error statistics
   */
  getErrorStats() {
    const stats = {
      totalErrors: this.errorLog.length,
      byCategory: {},
      recentErrors: this.errorLog.slice(-10),
      failedOperations: this.failedOperations.size,
      recoveryAttempts: this.recoveryAttempts.size
    };

    // Count by category
    for (const entry of this.errorLog) {
      stats.byCategory[entry.category] = (stats.byCategory[entry.category] || 0) + 1;
    }

    return stats;
  }

  /**
   * Get failed operations
   */
  getFailedOperations() {
    return Array.from(this.failedOperations.entries()).map(([id, data]) => ({
      id,
      ...data
    }));
  }

  /**
   * Clear error log
   */
  clearErrorLog() {
    this.errorLog = [];
    this.failedOperations.clear();
    this.recoveryAttempts.clear();
  }
}

module.exports = ErrorRecoverySystem;
module.exports.ErrorCategory = ErrorCategory;
module.exports.RecoveryStrategy = RecoveryStrategy;
