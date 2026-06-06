/**
 * Health Check Module
 * Phase 3 - Sprints 177-180: Production Hardening
 *
 * Provides:
 * - System health checks
 * - Dependency status
 * - Graceful degradation
 * - Circuit breaker pattern
 */

const fs = require('fs');
const path = require('path');
const { createLogger } = require('./unified-logger');

const logger = createLogger('health-check');

// =============================================================================
// HEALTH STATUS TYPES
// =============================================================================

const HealthStatus = {
  HEALTHY: 'healthy',
  DEGRADED: 'degraded',
  UNHEALTHY: 'unhealthy'
};

const ComponentType = {
  CORE: 'core',
  CACHE: 'cache',
  FILESYSTEM: 'filesystem',
  EXTERNAL: 'external'
};

// =============================================================================
// CIRCUIT BREAKER
// =============================================================================

/**
 * Circuit breaker for fault tolerance
 */
class CircuitBreaker {
  constructor(options = {}) {
    this.name = options.name || 'default';
    this.threshold = options.threshold || 5;
    this.timeout = options.timeout || 30000;
    this.resetTimeout = options.resetTimeout || 60000;

    this.failures = 0;
    this.successes = 0;
    this.state = 'CLOSED'; // CLOSED, OPEN, HALF_OPEN
    this.lastFailure = null;
    this.lastSuccess = null;
    this.openedAt = null;
  }

  async execute(fn, fallback = null) {
    if (this.state === 'OPEN') {
      if (Date.now() - this.openedAt >= this.resetTimeout) {
        this.state = 'HALF_OPEN';
        logger.info('Circuit breaker half-open', { name: this.name });
      } else {
        if (fallback) {
          return typeof fallback === 'function' ? fallback() : fallback;
        }
        throw new Error(`Circuit breaker open: ${this.name}`);
      }
    }

    try {
      const result = await Promise.race([
        fn(),
        new Promise((_, reject) =>
          setTimeout(() => reject(new Error('Timeout')), this.timeout)
        )
      ]);

      this._onSuccess();
      return result;
    } catch (error) {
      this._onFailure(error);

      if (fallback) {
        return typeof fallback === 'function' ? fallback(error) : fallback;
      }
      throw error;
    }
  }

  _onSuccess() {
    this.failures = 0;
    this.successes++;
    this.lastSuccess = Date.now();

    if (this.state === 'HALF_OPEN') {
      this.state = 'CLOSED';
      logger.info('Circuit breaker closed', { name: this.name });
    }
  }

  _onFailure(error) {
    this.failures++;
    this.lastFailure = Date.now();

    if (this.failures >= this.threshold) {
      this.state = 'OPEN';
      this.openedAt = Date.now();
      logger.warn('Circuit breaker opened', {
        name: this.name,
        failures: this.failures,
        error: error.message
      });
    }
  }

  getStats() {
    return {
      name: this.name,
      state: this.state,
      failures: this.failures,
      successes: this.successes,
      lastFailure: this.lastFailure,
      lastSuccess: this.lastSuccess
    };
  }

  reset() {
    this.failures = 0;
    this.successes = 0;
    this.state = 'CLOSED';
    this.openedAt = null;
  }
}

// =============================================================================
// HEALTH CHECK REGISTRY
// =============================================================================

/**
 * Health check for a single component
 */
class HealthCheck {
  constructor(name, checkFn, options = {}) {
    this.name = name;
    this.checkFn = checkFn;
    this.type = options.type || ComponentType.CORE;
    this.critical = options.critical !== false;
    this.timeout = options.timeout || 5000;
    this.interval = options.interval || 30000;
    this.lastCheck = null;
    this.lastResult = null;
  }

  async check() {
    const start = Date.now();

    try {
      const result = await Promise.race([
        this.checkFn(),
        new Promise((_, reject) =>
          setTimeout(() => reject(new Error('Health check timeout')), this.timeout)
        )
      ]);

      const duration = Date.now() - start;

      this.lastCheck = Date.now();
      this.lastResult = {
        status: HealthStatus.HEALTHY,
        duration,
        details: result || {},
        timestamp: new Date().toISOString()
      };

      return this.lastResult;
    } catch (error) {
      const duration = Date.now() - start;

      this.lastCheck = Date.now();
      this.lastResult = {
        status: HealthStatus.UNHEALTHY,
        duration,
        error: error.message,
        timestamp: new Date().toISOString()
      };

      return this.lastResult;
    }
  }
}

/**
 * Health check registry and aggregator
 */
class HealthCheckRegistry {
  constructor() {
    this.checks = new Map();
    this.intervals = new Map();
  }

  register(name, checkFn, options = {}) {
    const check = new HealthCheck(name, checkFn, options);
    this.checks.set(name, check);

    // Start periodic checking if interval specified
    if (options.interval) {
      this.startPeriodicCheck(name);
    }

    return this;
  }

  unregister(name) {
    this.stopPeriodicCheck(name);
    this.checks.delete(name);
    return this;
  }

  startPeriodicCheck(name) {
    const check = this.checks.get(name);
    if (!check) return;

    this.stopPeriodicCheck(name);

    const interval = setInterval(() => {
      check.check().catch(err => {
        logger.error('Periodic health check failed', { name, error: err.message });
      });
    }, check.interval);

    this.intervals.set(name, interval);
  }

  stopPeriodicCheck(name) {
    const interval = this.intervals.get(name);
    if (interval) {
      clearInterval(interval);
      this.intervals.delete(name);
    }
  }

  async checkOne(name) {
    const check = this.checks.get(name);
    if (!check) {
      throw new Error(`Unknown health check: ${name}`);
    }
    return check.check();
  }

  async checkAll() {
    const results = {};

    await Promise.all(
      Array.from(this.checks.entries()).map(async ([name, check]) => {
        results[name] = await check.check();
      })
    );

    return results;
  }

  async getOverallStatus() {
    const results = await this.checkAll();
    const checks = Object.entries(results);

    let status = HealthStatus.HEALTHY;
    const unhealthy = [];
    const degraded = [];

    for (const [name, result] of checks) {
      const check = this.checks.get(name);

      if (result.status === HealthStatus.UNHEALTHY) {
        if (check.critical) {
          status = HealthStatus.UNHEALTHY;
        } else if (status !== HealthStatus.UNHEALTHY) {
          status = HealthStatus.DEGRADED;
        }
        unhealthy.push(name);
      } else if (result.status === HealthStatus.DEGRADED) {
        if (status === HealthStatus.HEALTHY) {
          status = HealthStatus.DEGRADED;
        }
        degraded.push(name);
      }
    }

    return {
      status,
      timestamp: new Date().toISOString(),
      checks: results,
      summary: {
        total: checks.length,
        healthy: checks.length - unhealthy.length - degraded.length,
        unhealthy: unhealthy.length,
        degraded: degraded.length
      },
      unhealthy,
      degraded
    };
  }

  getLastResults() {
    const results = {};

    for (const [name, check] of this.checks.entries()) {
      results[name] = check.lastResult || { status: 'unknown' };
    }

    return results;
  }

  destroy() {
    for (const name of this.intervals.keys()) {
      this.stopPeriodicCheck(name);
    }
    this.checks.clear();
  }
}

// =============================================================================
// BUILT-IN HEALTH CHECKS
// =============================================================================

/**
 * Memory usage check
 */
function createMemoryCheck(options = {}) {
  const maxHeapUsage = options.maxHeapUsage || 0.9; // 90%

  return async () => {
    const usage = process.memoryUsage();
    const heapUsed = usage.heapUsed / usage.heapTotal;

    return {
      heapUsed: Math.round(heapUsed * 100) + '%',
      heapTotal: Math.round(usage.heapTotal / 1024 / 1024) + 'MB',
      rss: Math.round(usage.rss / 1024 / 1024) + 'MB',
      external: Math.round(usage.external / 1024 / 1024) + 'MB',
      warning: heapUsed > maxHeapUsage
    };
  };
}

/**
 * Disk space check
 */
function createDiskCheck(targetPath, options = {}) {
  const minFreeSpace = options.minFreeSpace || 100 * 1024 * 1024; // 100MB

  return async () => {
    try {
      const stats = fs.statfsSync(targetPath);
      const freeSpace = stats.bfree * stats.bsize;

      return {
        path: targetPath,
        freeSpace: Math.round(freeSpace / 1024 / 1024) + 'MB',
        sufficient: freeSpace >= minFreeSpace
      };
    } catch (error) {
      throw new Error(`Cannot check disk: ${error.message}`);
    }
  };
}

/**
 * File system write check
 */
function createFileSystemCheck(testPath) {
  return async () => {
    const testFile = path.join(testPath, '.health-check-' + Date.now());

    try {
      // Ensure directory exists
      if (!fs.existsSync(testPath)) {
        fs.mkdirSync(testPath, { recursive: true });
      }

      // Write test
      fs.writeFileSync(testFile, 'health-check');

      // Read test
      const content = fs.readFileSync(testFile, 'utf8');

      // Cleanup
      fs.unlinkSync(testFile);

      return {
        writable: true,
        readable: content === 'health-check'
      };
    } catch (error) {
      throw new Error(`Filesystem check failed: ${error.message}`);
    }
  };
}

/**
 * Registry accessibility check
 */
function createRegistryCheck(registryPath) {
  return async () => {
    try {
      if (!fs.existsSync(registryPath)) {
        return { exists: false, readable: false };
      }

      const content = fs.readFileSync(registryPath, 'utf8');
      const data = JSON.parse(content);

      return {
        exists: true,
        readable: true,
        version: data.version || 'unknown',
        componentCount: data.components?.length || 0
      };
    } catch (error) {
      throw new Error(`Registry check failed: ${error.message}`);
    }
  };
}

/**
 * Module availability check
 */
function createModuleCheck(modulePath) {
  return async () => {
    try {
      const module = require(modulePath);
      return {
        loaded: true,
        exports: Object.keys(module).length
      };
    } catch (error) {
      throw new Error(`Module check failed: ${error.message}`);
    }
  };
}

// =============================================================================
// GRACEFUL DEGRADATION
// =============================================================================

/**
 * Graceful degradation manager
 */
class DegradationManager {
  constructor() {
    this.features = new Map();
    this.overrides = new Map();
  }

  registerFeature(name, options = {}) {
    this.features.set(name, {
      name,
      enabled: true,
      fallback: options.fallback || null,
      dependencies: options.dependencies || [],
      priority: options.priority || 0
    });
    return this;
  }

  isEnabled(name) {
    if (this.overrides.has(name)) {
      return this.overrides.get(name);
    }

    const feature = this.features.get(name);
    return feature ? feature.enabled : true;
  }

  disable(name, reason = null) {
    const feature = this.features.get(name);
    if (feature) {
      feature.enabled = false;
      feature.disabledReason = reason;
      feature.disabledAt = new Date().toISOString();
      logger.warn('Feature disabled', { name, reason });
    }
    return this;
  }

  enable(name) {
    const feature = this.features.get(name);
    if (feature) {
      feature.enabled = true;
      delete feature.disabledReason;
      delete feature.disabledAt;
      logger.info('Feature enabled', { name });
    }
    return this;
  }

  override(name, enabled) {
    this.overrides.set(name, enabled);
    return this;
  }

  clearOverride(name) {
    this.overrides.delete(name);
    return this;
  }

  getFallback(name) {
    const feature = this.features.get(name);
    return feature?.fallback || null;
  }

  async execute(name, fn, fallbackFn = null) {
    if (!this.isEnabled(name)) {
      const fallback = fallbackFn || this.getFallback(name);
      if (fallback) {
        return typeof fallback === 'function' ? fallback() : fallback;
      }
      throw new Error(`Feature disabled: ${name}`);
    }

    try {
      return await fn();
    } catch (error) {
      const fallback = fallbackFn || this.getFallback(name);
      if (fallback) {
        logger.warn('Feature degraded to fallback', { name, error: error.message });
        return typeof fallback === 'function' ? fallback(error) : fallback;
      }
      throw error;
    }
  }

  getStatus() {
    const status = {};

    for (const [name, feature] of this.features.entries()) {
      status[name] = {
        enabled: this.isEnabled(name),
        hasOverride: this.overrides.has(name),
        hasFallback: !!feature.fallback,
        disabledReason: feature.disabledReason,
        disabledAt: feature.disabledAt
      };
    }

    return status;
  }
}

// =============================================================================
// SINGLETON & FACTORY
// =============================================================================

let defaultRegistry = null;
let defaultDegradation = null;

function getHealthRegistry() {
  if (!defaultRegistry) {
    defaultRegistry = new HealthCheckRegistry();
  }
  return defaultRegistry;
}

function getDegradationManager() {
  if (!defaultDegradation) {
    defaultDegradation = new DegradationManager();
  }
  return defaultDegradation;
}

function resetHealthSystem() {
  if (defaultRegistry) {
    defaultRegistry.destroy();
    defaultRegistry = null;
  }
  defaultDegradation = null;
}

// =============================================================================
// EXPRESS MIDDLEWARE (if needed)
// =============================================================================

/**
 * Express health check endpoint middleware
 */
function healthCheckMiddleware(registry = null) {
  const reg = registry || getHealthRegistry();

  return async (req, res) => {
    try {
      const health = await reg.getOverallStatus();

      const statusCode =
        health.status === HealthStatus.HEALTHY ? 200 :
        health.status === HealthStatus.DEGRADED ? 200 :
        503;

      res.status(statusCode).json(health);
    } catch (error) {
      res.status(500).json({
        status: HealthStatus.UNHEALTHY,
        error: error.message
      });
    }
  };
}

/**
 * Liveness probe (is the process running?)
 */
function livenessMiddleware() {
  return (req, res) => {
    res.status(200).json({ status: 'alive', timestamp: new Date().toISOString() });
  };
}

/**
 * Readiness probe (is the service ready to accept traffic?)
 */
function readinessMiddleware(registry = null) {
  const reg = registry || getHealthRegistry();

  return async (req, res) => {
    try {
      const health = await reg.getOverallStatus();

      if (health.status === HealthStatus.UNHEALTHY) {
        res.status(503).json({
          ready: false,
          reason: 'Critical components unhealthy',
          unhealthy: health.unhealthy
        });
      } else {
        res.status(200).json({
          ready: true,
          status: health.status
        });
      }
    } catch (error) {
      res.status(503).json({ ready: false, error: error.message });
    }
  };
}

// =============================================================================
// EXPORTS
// =============================================================================

module.exports = {
  // Status types
  HealthStatus,
  ComponentType,

  // Circuit breaker
  CircuitBreaker,

  // Health checks
  HealthCheck,
  HealthCheckRegistry,

  // Built-in checks
  createMemoryCheck,
  createDiskCheck,
  createFileSystemCheck,
  createRegistryCheck,
  createModuleCheck,

  // Graceful degradation
  DegradationManager,

  // Singletons
  getHealthRegistry,
  getDegradationManager,
  resetHealthSystem,

  // Middleware
  healthCheckMiddleware,
  livenessMiddleware,
  readinessMiddleware
};
