/**
 * Sync Logger
 *
 * Comprehensive logging system for design-to-code synchronization.
 * Captures transformation events with timestamps, enables debugging,
 * and provides audit trails for sync operations.
 *
 * Key Principle: Make failures observable and recoverable, not silent and destructive.
 *
 * @module sync-logger
 */

'use strict';

const fs = require('fs');
const path = require('path');

// =============================================================================
// LOG LEVELS AND CATEGORIES
// =============================================================================

/**
 * Log levels with numeric severity (lower = more severe)
 */
const LOG_LEVELS = {
  ERROR: { name: 'error', severity: 0, color: '\x1b[31m' },    // Red
  WARN: { name: 'warn', severity: 1, color: '\x1b[33m' },      // Yellow
  INFO: { name: 'info', severity: 2, color: '\x1b[36m' },      // Cyan
  DEBUG: { name: 'debug', severity: 3, color: '\x1b[90m' },    // Gray
  TRACE: { name: 'trace', severity: 4, color: '\x1b[90m' }     // Gray
};

/**
 * Log categories for filtering
 */
const LOG_CATEGORIES = {
  SYNC: 'sync',           // Sync lifecycle events
  TRANSFORM: 'transform', // Transformation operations
  EXTRACT: 'extract',     // Design extraction
  VALIDATE: 'validate',   // Validation operations
  FILE: 'file',           // File system operations
  NETWORK: 'network',     // Network/API calls
  CACHE: 'cache',         // Caching operations
  RENDER: 'render',       // Render stability
  ERROR: 'error',         // Error handling
  PERF: 'perf'            // Performance metrics
};

/**
 * Reset ANSI color
 */
const COLOR_RESET = '\x1b[0m';

// =============================================================================
// SYNC LOGGER CLASS
// =============================================================================

/**
 * Logger for sync operations with session support
 */
class SyncLogger {
  /**
   * Create a new sync logger
   * @param {Object} options - Logger options
   * @param {string} options.sessionId - Unique session identifier
   * @param {string} options.level - Minimum log level (default: 'info')
   * @param {string[]} options.categories - Categories to capture (default: all)
   * @param {boolean} options.console - Log to console (default: true)
   * @param {boolean} options.color - Use colors in console (default: true)
   * @param {string} options.logDir - Directory for log files (default: null)
   * @param {number} options.maxEntries - Max in-memory entries (default: 1000)
   * @param {boolean} options.includeStackTrace - Include stack traces (default: false)
   */
  constructor(options = {}) {
    this.sessionId = options.sessionId || this._generateSessionId();
    this.level = options.level || 'info';
    this.categories = options.categories || Object.values(LOG_CATEGORIES);
    this.logToConsole = options.console !== false;
    this.useColors = options.color !== false;
    this.logDir = options.logDir || null;
    this.maxEntries = options.maxEntries || 1000;
    this.includeStackTrace = options.includeStackTrace || false;

    // In-memory log storage
    this.entries = [];

    // Session metadata
    this.startTime = Date.now();
    this.metadata = {
      startedAt: new Date().toISOString(),
      sessionId: this.sessionId,
      options: {
        level: this.level,
        categories: this.categories
      }
    };

    // Active spans for timing
    this.activeSpans = new Map();

    // Counters per level
    this.counters = {
      error: 0,
      warn: 0,
      info: 0,
      debug: 0,
      trace: 0
    };

    // File handle (lazy initialized)
    this._fileHandle = null;
    this._fileBuffer = [];
    this._flushInterval = null;

    // Initialize file logging if directory specified
    if (this.logDir) {
      this._initFileLogging();
    }
  }

  /**
   * Generate unique session ID
   * @returns {string} Session ID
   * @private
   */
  _generateSessionId() {
    const timestamp = Date.now().toString(36);
    const random = Math.random().toString(36).substring(2, 8);
    return `sync-${timestamp}-${random}`;
  }

  /**
   * Initialize file logging
   * @private
   */
  _initFileLogging() {
    try {
      if (!fs.existsSync(this.logDir)) {
        fs.mkdirSync(this.logDir, { recursive: true });
      }

      const logFile = path.join(
        this.logDir,
        `sync-${this.sessionId}.log`
      );

      this._logFilePath = logFile;

      // Periodic flush
      this._flushInterval = setInterval(() => {
        this._flushToFile();
      }, 5000);
    } catch (err) {
      console.error('Failed to initialize file logging:', err.message);
      this.logDir = null;
    }
  }

  /**
   * Flush buffer to file
   * @private
   */
  _flushToFile() {
    if (!this._logFilePath || this._fileBuffer.length === 0) return;

    try {
      const content = this._fileBuffer.map(e => JSON.stringify(e)).join('\n') + '\n';
      fs.appendFileSync(this._logFilePath, content);
      this._fileBuffer = [];
    } catch (err) {
      console.error('Failed to write to log file:', err.message);
    }
  }

  /**
   * Check if a level should be logged
   * @param {string} level - Level to check
   * @returns {boolean} True if should log
   * @private
   */
  _shouldLog(level) {
    const levelConfig = LOG_LEVELS[level.toUpperCase()];
    const minLevelConfig = LOG_LEVELS[this.level.toUpperCase()];

    if (!levelConfig || !minLevelConfig) return true;
    return levelConfig.severity <= minLevelConfig.severity;
  }

  /**
   * Check if a category should be logged
   * @param {string} category - Category to check
   * @returns {boolean} True if should log
   * @private
   */
  _shouldLogCategory(category) {
    return this.categories.includes(category);
  }

  /**
   * Format log entry for console
   * @param {Object} entry - Log entry
   * @returns {string} Formatted string
   * @private
   */
  _formatConsole(entry) {
    const levelConfig = LOG_LEVELS[entry.level.toUpperCase()] || LOG_LEVELS.INFO;
    const color = this.useColors ? levelConfig.color : '';
    const reset = this.useColors ? COLOR_RESET : '';

    const timestamp = entry.timestamp.split('T')[1].split('.')[0];
    const level = entry.level.toUpperCase().padEnd(5);
    const category = entry.category ? `[${entry.category}]` : '';

    let output = `${color}${timestamp} ${level}${reset} ${category} ${entry.message}`;

    // Add context if present
    if (entry.context && Object.keys(entry.context).length > 0) {
      const contextStr = JSON.stringify(entry.context);
      if (contextStr.length < 100) {
        output += ` ${this.useColors ? '\x1b[90m' : ''}${contextStr}${reset}`;
      }
    }

    // Add duration if present
    if (entry.durationMs !== undefined) {
      output += ` ${this.useColors ? '\x1b[33m' : ''}(${entry.durationMs}ms)${reset}`;
    }

    return output;
  }

  /**
   * Create and store a log entry
   * @param {string} level - Log level
   * @param {string} category - Log category
   * @param {string} message - Log message
   * @param {Object} context - Additional context
   * @returns {Object} The created entry
   * @private
   */
  _log(level, category, message, context = {}) {
    if (!this._shouldLog(level)) return null;
    if (category && !this._shouldLogCategory(category)) return null;

    const entry = {
      timestamp: new Date().toISOString(),
      sessionId: this.sessionId,
      level: level.toLowerCase(),
      category,
      message,
      context: { ...context }
    };

    // Add stack trace if configured and error
    if (this.includeStackTrace && level === 'error') {
      entry.stack = new Error().stack.split('\n').slice(3).join('\n');
    }

    // Update counters
    if (this.counters[entry.level] !== undefined) {
      this.counters[entry.level]++;
    }

    // Store in memory (with limit)
    this.entries.push(entry);
    if (this.entries.length > this.maxEntries) {
      this.entries.shift();
    }

    // Store for file write
    if (this.logDir) {
      this._fileBuffer.push(entry);
    }

    // Console output
    if (this.logToConsole) {
      console.log(this._formatConsole(entry));
    }

    return entry;
  }

  // -------------------------------------------------------------------------
  // Public Logging Methods
  // -------------------------------------------------------------------------

  /**
   * Log error message
   * @param {string} message - Error message
   * @param {Object} context - Additional context
   */
  error(message, context = {}) {
    return this._log('error', context.category || LOG_CATEGORIES.ERROR, message, context);
  }

  /**
   * Log warning message
   * @param {string} message - Warning message
   * @param {Object} context - Additional context
   */
  warn(message, context = {}) {
    return this._log('warn', context.category, message, context);
  }

  /**
   * Log info message
   * @param {string} message - Info message
   * @param {Object} context - Additional context
   */
  info(message, context = {}) {
    return this._log('info', context.category, message, context);
  }

  /**
   * Log debug message
   * @param {string} message - Debug message
   * @param {Object} context - Additional context
   */
  debug(message, context = {}) {
    return this._log('debug', context.category, message, context);
  }

  /**
   * Log trace message
   * @param {string} message - Trace message
   * @param {Object} context - Additional context
   */
  trace(message, context = {}) {
    return this._log('trace', context.category, message, context);
  }

  // -------------------------------------------------------------------------
  // Sync-Specific Logging Methods
  // -------------------------------------------------------------------------

  /**
   * Log sync start
   * @param {Object} details - Sync details
   */
  syncStart(details = {}) {
    return this._log('info', LOG_CATEGORIES.SYNC, 'Sync started', {
      sourceType: details.sourceType,
      targetFramework: details.targetFramework,
      nodeCount: details.nodeCount,
      ...details
    });
  }

  /**
   * Log sync completion
   * @param {Object} details - Completion details
   */
  syncComplete(details = {}) {
    const duration = Date.now() - this.startTime;
    return this._log('info', LOG_CATEGORIES.SYNC, 'Sync completed', {
      durationMs: duration,
      componentsGenerated: details.componentsGenerated,
      warnings: details.warnings,
      ...details
    });
  }

  /**
   * Log sync failure
   * @param {Error|string} error - Error object or message
   * @param {Object} context - Additional context
   */
  syncFailed(error, context = {}) {
    const message = error instanceof Error ? error.message : String(error);
    const entry = this._log('error', LOG_CATEGORIES.SYNC, `Sync failed: ${message}`, {
      error: message,
      stack: error instanceof Error ? error.stack : undefined,
      ...context
    });
    return entry;
  }

  /**
   * Log transformation event
   * @param {string} action - Transformation action
   * @param {Object} details - Transformation details
   */
  transform(action, details = {}) {
    return this._log('info', LOG_CATEGORIES.TRANSFORM, `Transform: ${action}`, details);
  }

  /**
   * Log extraction event
   * @param {string} source - Source type (figma, shadcn, nlp)
   * @param {Object} details - Extraction details
   */
  extract(source, details = {}) {
    return this._log('info', LOG_CATEGORIES.EXTRACT, `Extract from ${source}`, details);
  }

  /**
   * Log validation event
   * @param {string} type - Validation type
   * @param {boolean} passed - Whether validation passed
   * @param {Object} details - Validation details
   */
  validate(type, passed, details = {}) {
    const level = passed ? 'info' : 'warn';
    return this._log(level, LOG_CATEGORIES.VALIDATE,
      `Validation [${type}]: ${passed ? 'passed' : 'failed'}`, details);
  }

  /**
   * Log file operation
   * @param {string} operation - Operation type (read, write, delete)
   * @param {string} filePath - File path
   * @param {Object} details - Operation details
   */
  file(operation, filePath, details = {}) {
    return this._log('debug', LOG_CATEGORIES.FILE,
      `File ${operation}: ${filePath}`, details);
  }

  /**
   * Log network operation
   * @param {string} method - HTTP method
   * @param {string} url - Request URL
   * @param {Object} details - Request details
   */
  network(method, url, details = {}) {
    return this._log('debug', LOG_CATEGORIES.NETWORK,
      `${method.toUpperCase()} ${url}`, details);
  }

  /**
   * Log cache operation
   * @param {string} operation - Cache operation (hit, miss, set, invalidate)
   * @param {string} key - Cache key
   * @param {Object} details - Cache details
   */
  cache(operation, key, details = {}) {
    const level = operation === 'miss' ? 'debug' : 'trace';
    return this._log(level, LOG_CATEGORIES.CACHE,
      `Cache ${operation}: ${key}`, details);
  }

  /**
   * Log performance metric
   * @param {string} metric - Metric name
   * @param {number} value - Metric value
   * @param {string} unit - Value unit (ms, bytes, count)
   * @param {Object} context - Additional context
   */
  perf(metric, value, unit = 'ms', context = {}) {
    return this._log('debug', LOG_CATEGORIES.PERF,
      `${metric}: ${value}${unit}`, context);
  }

  // -------------------------------------------------------------------------
  // Span/Timing Methods
  // -------------------------------------------------------------------------

  /**
   * Start a timing span
   * @param {string} name - Span name
   * @param {Object} context - Span context
   * @returns {Object} Span object with end() method
   */
  startSpan(name, context = {}) {
    const spanId = `${name}-${Date.now()}`;
    const span = {
      id: spanId,
      name,
      startTime: Date.now(),
      context
    };

    this.activeSpans.set(spanId, span);

    this._log('debug', context.category || LOG_CATEGORIES.PERF,
      `Span started: ${name}`, context);

    return {
      id: spanId,
      end: (endContext = {}) => this.endSpan(spanId, endContext)
    };
  }

  /**
   * End a timing span
   * @param {string} spanId - Span ID from startSpan
   * @param {Object} context - End context
   * @returns {number} Duration in milliseconds
   */
  endSpan(spanId, context = {}) {
    const span = this.activeSpans.get(spanId);
    if (!span) {
      this.warn(`Unknown span: ${spanId}`);
      return 0;
    }

    const duration = Date.now() - span.startTime;
    this.activeSpans.delete(spanId);

    this._log('debug', span.context.category || LOG_CATEGORIES.PERF,
      `Span ended: ${span.name}`, {
        ...span.context,
        ...context,
        durationMs: duration
      });

    return duration;
  }

  /**
   * Time an async function
   * @param {string} name - Operation name
   * @param {Function} fn - Async function to time
   * @param {Object} context - Context
   * @returns {Promise<*>} Function result
   */
  async time(name, fn, context = {}) {
    const span = this.startSpan(name, context);
    try {
      const result = await fn();
      span.end({ success: true });
      return result;
    } catch (error) {
      span.end({ success: false, error: error.message });
      throw error;
    }
  }

  // -------------------------------------------------------------------------
  // Session Management
  // -------------------------------------------------------------------------

  /**
   * Add metadata to the session
   * @param {string} key - Metadata key
   * @param {*} value - Metadata value
   */
  addMetadata(key, value) {
    this.metadata[key] = value;
  }

  /**
   * Get session summary
   * @returns {Object} Session summary
   */
  getSummary() {
    return {
      sessionId: this.sessionId,
      duration: Date.now() - this.startTime,
      entries: this.entries.length,
      counters: { ...this.counters },
      metadata: { ...this.metadata },
      hasErrors: this.counters.error > 0,
      hasWarnings: this.counters.warn > 0
    };
  }

  /**
   * Get all entries
   * @param {Object} filter - Filter options
   * @param {string} filter.level - Filter by level
   * @param {string} filter.category - Filter by category
   * @param {number} filter.limit - Limit results
   * @returns {Object[]} Filtered entries
   */
  getEntries(filter = {}) {
    let entries = [...this.entries];

    if (filter.level) {
      entries = entries.filter(e => e.level === filter.level);
    }
    if (filter.category) {
      entries = entries.filter(e => e.category === filter.category);
    }
    if (filter.limit) {
      entries = entries.slice(-filter.limit);
    }

    return entries;
  }

  /**
   * Get errors only
   * @returns {Object[]} Error entries
   */
  getErrors() {
    return this.getEntries({ level: 'error' });
  }

  /**
   * Get warnings only
   * @returns {Object[]} Warning entries
   */
  getWarnings() {
    return this.getEntries({ level: 'warn' });
  }

  /**
   * Clear all entries
   */
  clear() {
    this.entries = [];
    this.counters = { error: 0, warn: 0, info: 0, debug: 0, trace: 0 };
  }

  /**
   * Export log to JSON
   * @returns {Object} Full log export
   */
  toJSON() {
    return {
      session: this.getSummary(),
      entries: this.entries
    };
  }

  /**
   * Export log to string
   * @param {boolean} includeContext - Include context in output
   * @returns {string} Log as string
   */
  toString(includeContext = false) {
    return this.entries.map(entry => {
      let line = `${entry.timestamp} [${entry.level.toUpperCase()}] ${entry.category || '-'}: ${entry.message}`;
      if (includeContext && entry.context && Object.keys(entry.context).length > 0) {
        line += ` | ${JSON.stringify(entry.context)}`;
      }
      return line;
    }).join('\n');
  }

  /**
   * Close the logger and flush any pending writes
   */
  close() {
    if (this._flushInterval) {
      clearInterval(this._flushInterval);
      this._flushInterval = null;
    }

    this._flushToFile();

    // Log session summary
    const summary = this.getSummary();
    this._log('info', LOG_CATEGORIES.SYNC,
      `Session closed: ${summary.entries} entries, ${summary.counters.error} errors, ${summary.counters.warn} warnings`,
      { duration: summary.duration }
    );

    // Final flush
    this._flushToFile();
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a new sync logger instance
 * @param {Object} options - Logger options
 * @returns {SyncLogger} New logger instance
 */
function createLogger(options = {}) {
  return new SyncLogger(options);
}

/**
 * Create a child logger with inherited settings
 * @param {SyncLogger} parent - Parent logger
 * @param {Object} overrides - Setting overrides
 * @returns {SyncLogger} Child logger
 */
function createChildLogger(parent, overrides = {}) {
  return new SyncLogger({
    sessionId: `${parent.sessionId}-child`,
    level: parent.level,
    categories: parent.categories,
    console: parent.logToConsole,
    color: parent.useColors,
    logDir: parent.logDir,
    ...overrides
  });
}

// =============================================================================
// GLOBAL LOGGER (Optional)
// =============================================================================

let _globalLogger = null;

/**
 * Get or create global logger
 * @param {Object} options - Options for initial creation
 * @returns {SyncLogger} Global logger instance
 */
function getGlobalLogger(options = {}) {
  if (!_globalLogger) {
    _globalLogger = new SyncLogger(options);
  }
  return _globalLogger;
}

/**
 * Reset global logger
 */
function resetGlobalLogger() {
  if (_globalLogger) {
    _globalLogger.close();
    _globalLogger = null;
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

module.exports = {
  // Classes
  SyncLogger,
  // Constants
  LOG_LEVELS,
  LOG_CATEGORIES,
  // Factory functions
  createLogger,
  createChildLogger,
  // Global logger
  getGlobalLogger,
  resetGlobalLogger
};

// =============================================================================
// USAGE EXAMPLES (in comments)
// =============================================================================

/*
Basic Usage:

const { createLogger, LOG_CATEGORIES } = require('./sync-logger');

const logger = createLogger({
  sessionId: 'my-sync-001',
  level: 'debug',
  logDir: './.design/logs'
});

logger.syncStart({
  sourceType: 'figma',
  targetFramework: 'react',
  nodeCount: 150
});

const span = logger.startSpan('transform-components');
// ... do work ...
span.end({ componentsProcessed: 42 });

logger.transform('button', { variants: 3 });
logger.validate('layout', true, { nodeId: '123:456' });
logger.warn('Fallback used for blend mode', { category: LOG_CATEGORIES.TRANSFORM });

logger.syncComplete({
  componentsGenerated: 15,
  warnings: 3
});

console.log(logger.getSummary());
logger.close();

---

With Global Logger:

const { getGlobalLogger } = require('./sync-logger');

const logger = getGlobalLogger({ level: 'info' });
logger.info('Application started');

---

Timing Async Operations:

await logger.time('fetch-figma-data', async () => {
  return await figmaApi.getFile(fileKey);
}, { category: LOG_CATEGORIES.NETWORK });
*/
