/**
 * Unified Logger Module
 * Phase 3 - Sprint 125: Centralized logging infrastructure
 *
 * Replaces scattered console.log/warn/error calls with structured,
 * configurable logging with log levels, context, and formatting.
 */

const fs = require('fs');
const path = require('path');
const { EventEmitter } = require('events');

// Log levels with numeric priority
const LOG_LEVELS = {
  TRACE: 0,
  DEBUG: 1,
  INFO: 2,
  WARN: 3,
  ERROR: 4,
  FATAL: 5,
  SILENT: 99
};

// ANSI color codes
const COLORS = {
  reset: '\x1b[0m',
  dim: '\x1b[2m',
  bright: '\x1b[1m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  magenta: '\x1b[35m',
  cyan: '\x1b[36m',
  white: '\x1b[37m'
};

// Level colors
const LEVEL_COLORS = {
  TRACE: COLORS.dim,
  DEBUG: COLORS.cyan,
  INFO: COLORS.green,
  WARN: COLORS.yellow,
  ERROR: COLORS.red,
  FATAL: COLORS.bright + COLORS.red
};

// Level symbols
const LEVEL_SYMBOLS = {
  TRACE: '○',
  DEBUG: '●',
  INFO: '✓',
  WARN: '⚠',
  ERROR: '✗',
  FATAL: '✖'
};

/**
 * Format timestamp for log output
 */
function formatTimestamp(date = new Date()) {
  return date.toISOString();
}

/**
 * Format duration for performance logging
 */
function formatDuration(ms) {
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(2)}s`;
  return `${(ms / 60000).toFixed(2)}m`;
}

/**
 * Safe JSON stringify with circular reference handling
 */
function safeStringify(obj, indent = 2) {
  const seen = new WeakSet();
  return JSON.stringify(obj, (key, value) => {
    if (typeof value === 'object' && value !== null) {
      if (seen.has(value)) {
        return '[Circular]';
      }
      seen.add(value);
    }
    if (value instanceof Error) {
      return {
        name: value.name,
        message: value.message,
        stack: value.stack,
        code: value.code
      };
    }
    return value;
  }, indent);
}

/**
 * Logger instance for a specific module/component
 */
class Logger extends EventEmitter {
  constructor(options = {}) {
    super();

    this.name = options.name || 'app';
    this.level = LOG_LEVELS[options.level?.toUpperCase()] ?? LOG_LEVELS.INFO;
    this.colorize = options.colorize !== false;
    this.includeTimestamp = options.includeTimestamp !== false;
    this.includeLevel = options.includeLevel !== false;
    this.includeName = options.includeName !== false;
    this.logFile = options.logFile || null;
    this.maxFileSize = options.maxFileSize || 10 * 1024 * 1024; // 10MB default
    this.context = options.context || {};
    this.parent = options.parent || null;

    // Metrics tracking
    this.metrics = {
      logged: { TRACE: 0, DEBUG: 0, INFO: 0, WARN: 0, ERROR: 0, FATAL: 0 },
      lastError: null,
      startTime: Date.now()
    };

    // File stream for persistent logging
    if (this.logFile) {
      this._initFileLogging();
    }
  }

  /**
   * Initialize file logging
   */
  _initFileLogging() {
    try {
      const logDir = path.dirname(this.logFile);
      if (!fs.existsSync(logDir)) {
        fs.mkdirSync(logDir, { recursive: true });
      }
      this.fileStream = fs.createWriteStream(this.logFile, { flags: 'a' });
    } catch (err) {
      console.error(`Failed to initialize log file: ${err.message}`);
      this.fileStream = null;
    }
  }

  /**
   * Set log level
   */
  setLevel(level) {
    this.level = LOG_LEVELS[level.toUpperCase()] ?? this.level;
    return this;
  }

  /**
   * Create child logger with inherited settings
   */
  child(options = {}) {
    return new Logger({
      name: options.name || `${this.name}:child`,
      level: Object.keys(LOG_LEVELS).find(k => LOG_LEVELS[k] === this.level),
      colorize: this.colorize,
      includeTimestamp: this.includeTimestamp,
      includeLevel: this.includeLevel,
      includeName: this.includeName,
      logFile: this.logFile,
      context: { ...this.context, ...options.context },
      parent: this
    });
  }

  /**
   * Core log method
   */
  _log(level, message, data = {}) {
    const levelNum = LOG_LEVELS[level];

    // Skip if below current log level
    if (levelNum < this.level) {
      return;
    }

    // Update metrics
    this.metrics.logged[level]++;
    if (level === 'ERROR' || level === 'FATAL') {
      this.metrics.lastError = { level, message, data, timestamp: new Date() };
    }

    // Build log entry
    const entry = {
      timestamp: formatTimestamp(),
      level,
      name: this.name,
      message,
      ...this.context,
      ...data
    };

    // Format for console
    const consoleOutput = this._formatConsole(entry);

    // Output to console
    if (level === 'ERROR' || level === 'FATAL') {
      console.error(consoleOutput);
    } else if (level === 'WARN') {
      console.warn(consoleOutput);
    } else {
      console.log(consoleOutput);
    }

    // Output to file if configured
    if (this.fileStream) {
      this.fileStream.write(JSON.stringify(entry) + '\n');
    }

    // Emit event for log aggregation
    this.emit('log', entry);

    return entry;
  }

  /**
   * Format log entry for console output
   */
  _formatConsole(entry) {
    const parts = [];

    // Timestamp
    if (this.includeTimestamp) {
      if (this.colorize) {
        parts.push(`${COLORS.dim}${entry.timestamp}${COLORS.reset}`);
      } else {
        parts.push(entry.timestamp);
      }
    }

    // Level
    if (this.includeLevel) {
      const symbol = LEVEL_SYMBOLS[entry.level] || entry.level;
      if (this.colorize) {
        const color = LEVEL_COLORS[entry.level] || '';
        parts.push(`${color}${symbol}${COLORS.reset}`);
      } else {
        parts.push(`[${entry.level}]`);
      }
    }

    // Logger name
    if (this.includeName) {
      if (this.colorize) {
        parts.push(`${COLORS.magenta}[${entry.name}]${COLORS.reset}`);
      } else {
        parts.push(`[${entry.name}]`);
      }
    }

    // Message
    parts.push(entry.message);

    // Additional data (excluding standard fields)
    const extraData = { ...entry };
    delete extraData.timestamp;
    delete extraData.level;
    delete extraData.name;
    delete extraData.message;

    if (Object.keys(extraData).length > 0) {
      // Format extra data
      if (this.colorize) {
        parts.push(`${COLORS.dim}${safeStringify(extraData, 0)}${COLORS.reset}`);
      } else {
        parts.push(safeStringify(extraData, 0));
      }
    }

    return parts.join(' ');
  }

  // Convenience methods for each log level

  trace(message, data) {
    return this._log('TRACE', message, data);
  }

  debug(message, data) {
    return this._log('DEBUG', message, data);
  }

  info(message, data) {
    return this._log('INFO', message, data);
  }

  warn(message, data) {
    return this._log('WARN', message, data);
  }

  error(message, data) {
    // Handle Error objects specially
    if (message instanceof Error) {
      return this._log('ERROR', message.message, {
        ...data,
        error: {
          name: message.name,
          message: message.message,
          stack: message.stack,
          code: message.code
        }
      });
    }
    return this._log('ERROR', message, data);
  }

  fatal(message, data) {
    if (message instanceof Error) {
      return this._log('FATAL', message.message, {
        ...data,
        error: {
          name: message.name,
          message: message.message,
          stack: message.stack,
          code: message.code
        }
      });
    }
    return this._log('FATAL', message, data);
  }

  /**
   * Log with timing measurement
   */
  time(label) {
    const start = Date.now();
    return {
      end: (message, data = {}) => {
        const duration = Date.now() - start;
        this.debug(message || `${label} completed`, {
          ...data,
          duration: formatDuration(duration),
          durationMs: duration
        });
        return duration;
      }
    };
  }

  /**
   * Log operation with automatic timing
   */
  async timed(label, fn, data = {}) {
    const start = Date.now();
    try {
      const result = await fn();
      const duration = Date.now() - start;
      this.debug(`${label} completed`, {
        ...data,
        duration: formatDuration(duration),
        durationMs: duration,
        success: true
      });
      return result;
    } catch (err) {
      const duration = Date.now() - start;
      this.error(`${label} failed`, {
        ...data,
        duration: formatDuration(duration),
        durationMs: duration,
        error: err.message
      });
      throw err;
    }
  }

  /**
   * Get logger metrics
   */
  getMetrics() {
    return {
      ...this.metrics,
      uptime: Date.now() - this.metrics.startTime,
      totalLogged: Object.values(this.metrics.logged).reduce((a, b) => a + b, 0)
    };
  }

  /**
   * Close file stream
   */
  close() {
    if (this.fileStream) {
      this.fileStream.end();
      this.fileStream = null;
    }
  }
}

// Singleton logger factory
let defaultLogger = null;

/**
 * Get or create the default logger
 */
function getLogger(options = {}) {
  if (!defaultLogger) {
    defaultLogger = new Logger({
      name: 'design-bridge',
      level: process.env.LOG_LEVEL || 'INFO',
      colorize: process.stdout.isTTY,
      ...options
    });
  }
  return defaultLogger;
}

/**
 * Create a named logger
 */
function createLogger(name, options = {}) {
  return new Logger({
    name,
    level: process.env.LOG_LEVEL || 'INFO',
    colorize: process.stdout.isTTY,
    ...options
  });
}

/**
 * Reset the default logger (for testing)
 */
function resetLogger() {
  if (defaultLogger) {
    defaultLogger.close();
    defaultLogger = null;
  }
}

module.exports = {
  Logger,
  getLogger,
  createLogger,
  resetLogger,
  LOG_LEVELS,
  formatDuration,
  formatTimestamp,
  safeStringify
};
