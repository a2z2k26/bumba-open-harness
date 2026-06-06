#!/usr/bin/env node

/**
 * Design Bridge Performance Monitor
 * Phase 9 - Sprint 9.4: Performance Monitoring & Metrics
 *
 * Features:
 * - Real-time performance monitoring
 * - Memory usage tracking
 * - CPU utilization analysis
 * - Response time measurement
 * - Throughput analysis
 * - Bottleneck detection
 * - Performance alerts
 * - Optimization recommendations
 * - Metrics collection & aggregation
 * - Code profiling
 * - Alert thresholds
 */

const EventEmitter = require('events');
const { performance } = require('perf_hooks');
const os = require('os');

// ============================================================================
// Constants
// ============================================================================

const METRIC_TYPES = {
  COUNTER: 'counter',
  GAUGE: 'gauge',
  HISTOGRAM: 'histogram',
  TIMER: 'timer',
  RATE: 'rate'
};

const AGGREGATION_TYPES = {
  SUM: 'sum',
  AVG: 'avg',
  MIN: 'min',
  MAX: 'max',
  COUNT: 'count',
  P50: 'p50',
  P90: 'p90',
  P95: 'p95',
  P99: 'p99'
};

const MONITOR_EVENTS = {
  METRIC_RECORDED: 'metric:recorded',
  THRESHOLD_EXCEEDED: 'threshold:exceeded',
  PROFILE_COMPLETE: 'profile:complete',
  REPORT_GENERATED: 'report:generated',
  ALERT_TRIGGERED: 'alert:triggered',
  MEMORY_WARNING: 'memory:warning'
};

const ALERT_LEVELS = {
  INFO: 'info',
  WARNING: 'warning',
  ERROR: 'error',
  CRITICAL: 'critical'
};

// ============================================================================
// Timer - High-resolution timing utility
// ============================================================================

class Timer {
  constructor(name) {
    this.name = name;
    this.startTime = null;
    this.endTime = null;
    this.marks = [];
    this.running = false;
  }

  start() {
    this.startTime = process.hrtime.bigint();
    this.running = true;
    return this;
  }

  stop() {
    if (!this.running) return this;
    this.endTime = process.hrtime.bigint();
    this.running = false;
    return this;
  }

  mark(label) {
    this.marks.push({ label, time: process.hrtime.bigint() });
    return this;
  }

  elapsed() {
    const end = this.endTime || process.hrtime.bigint();
    return Number(end - this.startTime) / 1_000_000;
  }

  getMarks() {
    return this.marks.map((mark, i) => {
      const prevTime = i === 0 ? this.startTime : this.marks[i - 1].time;
      return {
        label: mark.label,
        elapsed: Number(mark.time - this.startTime) / 1_000_000,
        delta: Number(mark.time - prevTime) / 1_000_000
      };
    });
  }
}

// ============================================================================
// MetricsCollector - Collect and aggregate metrics
// ============================================================================

class MetricsCollector extends EventEmitter {
  constructor(options = {}) {
    super();
    this.options = {
      maxDataPoints: options.maxDataPoints || 1000,
      retentionPeriod: options.retentionPeriod || 3600000,
      ...options
    };
    this.metrics = new Map();
    this.timeSeries = new Map();
  }

  define(name, type, options = {}) {
    this.metrics.set(name, {
      name, type,
      description: options.description || '',
      value: type === METRIC_TYPES.COUNTER ? 0 : null,
      samples: [],
      createdAt: Date.now()
    });
    return this;
  }

  increment(name, value = 1) {
    const metric = this._getOrCreate(name, METRIC_TYPES.COUNTER);
    metric.value += value;
    this._record(name, metric.value);
    return this;
  }

  gauge(name, value) {
    const metric = this._getOrCreate(name, METRIC_TYPES.GAUGE);
    metric.value = value;
    this._record(name, value);
    return this;
  }

  histogram(name, value) {
    const metric = this._getOrCreate(name, METRIC_TYPES.HISTOGRAM);
    metric.samples.push({ value, timestamp: Date.now() });
    if (metric.samples.length > this.options.maxDataPoints) {
      metric.samples = metric.samples.slice(-this.options.maxDataPoints);
    }
    this._record(name, value);
    return this;
  }

  timing(name, duration) {
    return this.histogram(name, duration);
  }

  async time(name, fn) {
    const timer = new Timer(name);
    timer.start();
    try {
      const result = await fn();
      timer.stop();
      this.timing(name, timer.elapsed());
      return result;
    } catch (error) {
      timer.stop();
      this.timing(name, timer.elapsed());
      throw error;
    }
  }

  get(name) {
    const metric = this.metrics.get(name);
    if (!metric) return null;
    if (metric.type === METRIC_TYPES.HISTOGRAM) {
      return this._calculateHistogramStats(metric);
    }
    return { name: metric.name, type: metric.type, value: metric.value };
  }

  getAll() {
    const result = {};
    for (const [name, metric] of this.metrics) {
      result[name] = metric.type === METRIC_TYPES.HISTOGRAM
        ? this._calculateHistogramStats(metric)
        : { type: metric.type, value: metric.value };
    }
    return result;
  }

  _getOrCreate(name, type) {
    if (!this.metrics.has(name)) this.define(name, type);
    return this.metrics.get(name);
  }

  _record(name, value) {
    if (!this.timeSeries.has(name)) this.timeSeries.set(name, []);
    const series = this.timeSeries.get(name);
    series.push({ value, timestamp: Date.now() });
    const cutoff = Date.now() - this.options.retentionPeriod;
    this.timeSeries.set(name, series.filter(p => p.timestamp >= cutoff));
    this.emit(MONITOR_EVENTS.METRIC_RECORDED, { name, value });
  }

  _calculateHistogramStats(metric) {
    const values = metric.samples.map(s => s.value);
    if (values.length === 0) return { type: METRIC_TYPES.HISTOGRAM, count: 0 };
    values.sort((a, b) => a - b);
    return {
      type: METRIC_TYPES.HISTOGRAM,
      count: values.length,
      min: values[0],
      max: values[values.length - 1],
      avg: values.reduce((a, b) => a + b, 0) / values.length,
      p50: values[Math.floor(values.length * 0.5)],
      p95: values[Math.floor(values.length * 0.95)],
      p99: values[Math.floor(values.length * 0.99)]
    };
  }
}

// ============================================================================
// Profiler - Profile code execution
// ============================================================================

class Profiler extends EventEmitter {
  constructor(options = {}) {
    super();
    this.profiles = new Map();
    this.activeProfiles = new Map();
    this.options = { maxProfiles: options.maxProfiles || 100, ...options };
  }

  start(name) {
    this.activeProfiles.set(name, {
      name,
      startTime: process.hrtime.bigint(),
      memory: { start: process.memoryUsage() },
      calls: []
    });
    return this;
  }

  end(name) {
    const profile = this.activeProfiles.get(name);
    if (!profile) return null;
    profile.endTime = process.hrtime.bigint();
    profile.memory.end = process.memoryUsage();
    profile.duration = Number(profile.endTime - profile.startTime) / 1_000_000;
    profile.memoryDelta = {
      heapUsed: profile.memory.end.heapUsed - profile.memory.start.heapUsed
    };
    this.profiles.set(name, profile);
    this.activeProfiles.delete(name);
    if (this.profiles.size > this.options.maxProfiles) {
      const oldest = this.profiles.keys().next().value;
      this.profiles.delete(oldest);
    }
    this.emit(MONITOR_EVENTS.PROFILE_COMPLETE, profile);
    return profile;
  }

  async profile(name, fn) {
    this.start(name);
    try {
      const result = await fn();
      this.end(name);
      return result;
    } catch (error) {
      this.end(name);
      throw error;
    }
  }

  wrap(fn, name) {
    const profiler = this;
    return async function(...args) {
      const timer = new Timer(name);
      timer.start();
      try {
        const result = await fn.apply(this, args);
        timer.stop();
        return result;
      } catch (error) {
        timer.stop();
        throw error;
      }
    };
  }

  getProfile(name) { return this.profiles.get(name); }
  getAllProfiles() { return Array.from(this.profiles.values()); }
  clear() { this.profiles.clear(); this.activeProfiles.clear(); }
}

// ============================================================================
// AlertThresholdManager - Manage alert thresholds
// ============================================================================

class AlertThresholdManager extends EventEmitter {
  constructor(options = {}) {
    super();
    this.thresholds = new Map();
    this.alerts = [];
    this.lastAlertTime = new Map();
    this.options = { cooldownPeriod: options.cooldownPeriod || 60000, maxAlerts: options.maxAlerts || 100 };
  }

  defineThreshold(name, options) {
    this.thresholds.set(name, {
      name,
      metric: options.metric,
      operator: options.operator || 'gt',
      value: options.value,
      level: options.level || ALERT_LEVELS.WARNING,
      message: options.message || `Threshold exceeded for ${name}`,
      enabled: options.enabled !== false
    });
    return this;
  }

  check(metric, value) {
    const triggered = [];
    for (const [name, threshold] of this.thresholds) {
      if (!threshold.enabled || threshold.metric !== metric) continue;
      const exceeded = this._checkThreshold(value, threshold);
      if (exceeded && this._shouldAlert(name)) {
        const alert = {
          id: `alert-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          threshold: name,
          level: threshold.level,
          message: threshold.message,
          actualValue: value,
          thresholdValue: threshold.value,
          timestamp: Date.now(),
          resolved: false
        };
        this.alerts.push(alert);
        triggered.push(alert);
        this.lastAlertTime.set(name, Date.now());
        this.emit(MONITOR_EVENTS.ALERT_TRIGGERED, alert);
      }
    }
    if (this.alerts.length > this.options.maxAlerts) {
      this.alerts = this.alerts.slice(-this.options.maxAlerts);
    }
    return triggered;
  }

  getActiveAlerts() { return this.alerts.filter(a => !a.resolved); }
  getAllAlerts(limit = 50) { return this.alerts.slice(-limit); }

  _checkThreshold(value, threshold) {
    switch (threshold.operator) {
      case 'gt': return value > threshold.value;
      case 'lt': return value < threshold.value;
      case 'gte': return value >= threshold.value;
      case 'lte': return value <= threshold.value;
      case 'eq': return value === threshold.value;
      default: return false;
    }
  }

  _shouldAlert(name) {
    const lastTime = this.lastAlertTime.get(name);
    if (!lastTime) return true;
    return Date.now() - lastTime >= this.options.cooldownPeriod;
  }
}

class PerformanceMonitor extends EventEmitter {
  constructor(config = {}) {
    super();

    this.config = {
      monitoringInterval: config.monitoringInterval || 1000,
      alertThresholds: {
        memory: config.alertThresholds?.memory || 0.8, // 80% of available memory
        cpu: config.alertThresholds?.cpu || 0.7, // 70% CPU usage
        responseTime: config.alertThresholds?.responseTime || 5000, // 5 seconds
        errorRate: config.alertThresholds?.errorRate || 0.05 // 5% error rate
      },
      retentionPeriod: config.retentionPeriod || 24 * 60 * 60 * 1000, // 24 hours
      enableProfiling: config.enableProfiling !== false,
      enableAlerting: config.enableAlerting !== false,
      ...config
    };

    // Performance data storage
    this.metrics = new Map();
    this.timeSeries = [];
    this.alerts = [];
    this.profiles = new Map();

    // Monitoring state
    this.isMonitoring = false;
    this.monitoringTimer = null;
    this.startTime = Date.now();

    // Performance counters
    this.counters = {
      requests: 0,
      errors: 0,
      successes: 0,
      totalResponseTime: 0,
      operations: new Map()
    };

    // Memory baseline
    this.baselineMemory = process.memoryUsage();
    this.systemInfo = this.gatherSystemInfo();
  }

  async initialize() {
    console.log('📊 Initializing Performance Monitor...');

    this.startMonitoring();
    this.setupEventListeners();

    console.log('✅ Performance Monitor initialized');
    this.emit('monitor-initialized');
  }

  startMonitoring() {
    if (this.isMonitoring) return;

    this.isMonitoring = true;
    this.monitoringTimer = setInterval(() => {
      this.collectMetrics();
    }, this.config.monitoringInterval);

    console.log(`📈 Performance monitoring started (interval: ${this.config.monitoringInterval}ms)`);
  }

  stopMonitoring() {
    if (!this.isMonitoring) return;

    this.isMonitoring = false;
    if (this.monitoringTimer) {
      clearInterval(this.monitoringTimer);
      this.monitoringTimer = null;
    }

    console.log('📊 Performance monitoring stopped');
  }

  setupEventListeners() {
    // Listen for operation events
    this.on('operation-start', this.handleOperationStart.bind(this));
    this.on('operation-end', this.handleOperationEnd.bind(this));
    this.on('operation-error', this.handleOperationError.bind(this));
  }

  collectMetrics() {
    const timestamp = Date.now();

    // System metrics
    const systemMetrics = {
      timestamp,
      memory: this.getMemoryMetrics(),
      cpu: this.getCpuMetrics(),
      system: this.getSystemMetrics()
    };

    // Application metrics
    const appMetrics = {
      timestamp,
      counters: { ...this.counters },
      uptime: timestamp - this.startTime,
      averageResponseTime: this.counters.requests > 0
        ? this.counters.totalResponseTime / this.counters.requests
        : 0,
      errorRate: this.counters.requests > 0
        ? this.counters.errors / this.counters.requests
        : 0,
      throughput: this.calculateThroughput()
    };

    // Combine metrics
    const metrics = { ...systemMetrics, ...appMetrics };

    // Store metrics
    this.timeSeries.push(metrics);
    this.cleanupOldMetrics();

    // Check for alerts
    if (this.config.enableAlerting) {
      this.checkAlerts(metrics);
    }

    // Emit metrics event
    this.emit('metrics-collected', metrics);
  }

  getMemoryMetrics() {
    const memUsage = process.memoryUsage();
    const systemMem = {
      total: os.totalmem(),
      free: os.freemem(),
      used: os.totalmem() - os.freemem()
    };

    return {
      process: {
        rss: memUsage.rss,
        heapTotal: memUsage.heapTotal,
        heapUsed: memUsage.heapUsed,
        external: memUsage.external,
        arrayBuffers: memUsage.arrayBuffers
      },
      system: {
        ...systemMem,
        usagePercent: systemMem.used / systemMem.total
      },
      baseline: this.baselineMemory
    };
  }

  getCpuMetrics() {
    const cpus = os.cpus();
    const loadAvg = os.loadavg();

    // Calculate CPU usage
    let totalIdle = 0;
    let totalTick = 0;

    cpus.forEach(cpu => {
      for (const type in cpu.times) {
        totalTick += cpu.times[type];
      }
      totalIdle += cpu.times.idle;
    });

    return {
      usage: 1 - (totalIdle / totalTick),
      loadAverage: {
        '1min': loadAvg[0],
        '5min': loadAvg[1],
        '15min': loadAvg[2]
      },
      cores: cpus.length,
      model: cpus[0]?.model || 'Unknown'
    };
  }

  getSystemMetrics() {
    return {
      platform: os.platform(),
      arch: os.arch(),
      hostname: os.hostname(),
      uptime: os.uptime(),
      nodeVersion: process.version
    };
  }

  calculateThroughput() {
    // Calculate requests per second over the last minute
    const oneMinuteAgo = Date.now() - 60000;
    const recentMetrics = this.timeSeries.filter(m => m.timestamp > oneMinuteAgo);

    if (recentMetrics.length < 2) return 0;

    const oldestMetric = recentMetrics[0];
    const newestMetric = recentMetrics[recentMetrics.length - 1];

    const timeDiff = (newestMetric.timestamp - oldestMetric.timestamp) / 1000; // seconds
    const requestDiff = newestMetric.counters.requests - oldestMetric.counters.requests;

    return timeDiff > 0 ? requestDiff / timeDiff : 0;
  }

  handleOperationStart(data) {
    const { operationId, operation, timestamp } = data;

    if (!this.profiles.has(operationId)) {
      this.profiles.set(operationId, {
        operation,
        startTime: timestamp || performance.now(),
        endTime: null,
        duration: null,
        success: null,
        error: null
      });
    }

    // Update operation counter
    const opCount = this.counters.operations.get(operation) || { count: 0, totalTime: 0 };
    opCount.count++;
    this.counters.operations.set(operation, opCount);
  }

  handleOperationEnd(data) {
    const { operationId, success = true, error = null, timestamp } = data;

    const profile = this.profiles.get(operationId);
    if (profile) {
      profile.endTime = timestamp || performance.now();
      profile.duration = profile.endTime - profile.startTime;
      profile.success = success;
      profile.error = error;

      // Update counters
      this.counters.requests++;
      this.counters.totalResponseTime += profile.duration;

      if (success) {
        this.counters.successes++;
      } else {
        this.counters.errors++;
      }

      // Update operation statistics
      const opCount = this.counters.operations.get(profile.operation);
      if (opCount) {
        opCount.totalTime += profile.duration;
      }

      // Clean up profile after processing
      setTimeout(() => {
        this.profiles.delete(operationId);
      }, 1000);
    }
  }

  handleOperationError(data) {
    this.handleOperationEnd({ ...data, success: false });
  }

  checkAlerts(metrics) {
    const alerts = [];

    // Memory usage alert
    if (metrics.memory.system.usagePercent > this.config.alertThresholds.memory) {
      alerts.push({
        type: 'memory',
        severity: 'warning',
        message: `High memory usage: ${(metrics.memory.system.usagePercent * 100).toFixed(1)}%`,
        value: metrics.memory.system.usagePercent,
        threshold: this.config.alertThresholds.memory,
        timestamp: metrics.timestamp
      });
    }

    // CPU usage alert
    if (metrics.cpu.usage > this.config.alertThresholds.cpu) {
      alerts.push({
        type: 'cpu',
        severity: 'warning',
        message: `High CPU usage: ${(metrics.cpu.usage * 100).toFixed(1)}%`,
        value: metrics.cpu.usage,
        threshold: this.config.alertThresholds.cpu,
        timestamp: metrics.timestamp
      });
    }

    // Response time alert
    if (metrics.averageResponseTime > this.config.alertThresholds.responseTime) {
      alerts.push({
        type: 'response-time',
        severity: 'warning',
        message: `High response time: ${metrics.averageResponseTime.toFixed(0)}ms`,
        value: metrics.averageResponseTime,
        threshold: this.config.alertThresholds.responseTime,
        timestamp: metrics.timestamp
      });
    }

    // Error rate alert
    if (metrics.errorRate > this.config.alertThresholds.errorRate) {
      alerts.push({
        type: 'error-rate',
        severity: 'critical',
        message: `High error rate: ${(metrics.errorRate * 100).toFixed(1)}%`,
        value: metrics.errorRate,
        threshold: this.config.alertThresholds.errorRate,
        timestamp: metrics.timestamp
      });
    }

    // Store and emit alerts
    alerts.forEach(alert => {
      this.alerts.push(alert);
      this.emit('performance-alert', alert);
      console.warn(`⚠️ Performance Alert: ${alert.message}`);
    });
  }

  cleanupOldMetrics() {
    const cutoff = Date.now() - this.config.retentionPeriod;
    this.timeSeries = this.timeSeries.filter(m => m.timestamp > cutoff);
    this.alerts = this.alerts.filter(a => a.timestamp > cutoff);
  }

  gatherSystemInfo() {
    return {
      platform: os.platform(),
      arch: os.arch(),
      nodeVersion: process.version,
      totalMemory: os.totalmem(),
      cpus: os.cpus().length,
      hostname: os.hostname()
    };
  }

  // Public API methods

  startOperation(operation, operationId = null) {
    const id = operationId || this.generateOperationId();
    this.emit('operation-start', {
      operationId: id,
      operation,
      timestamp: performance.now()
    });
    return id;
  }

  endOperation(operationId, success = true, error = null) {
    this.emit('operation-end', {
      operationId,
      success,
      error,
      timestamp: performance.now()
    });
  }

  measureAsync(operation, asyncFunction) {
    return async (...args) => {
      const operationId = this.startOperation(operation);
      try {
        const result = await asyncFunction.apply(this, args);
        this.endOperation(operationId, true);
        return result;
      } catch (error) {
        this.endOperation(operationId, false, error);
        throw error;
      }
    };
  }

  measureSync(operation, syncFunction) {
    return (...args) => {
      const operationId = this.startOperation(operation);
      try {
        const result = syncFunction.apply(this, args);
        this.endOperation(operationId, true);
        return result;
      } catch (error) {
        this.endOperation(operationId, false, error);
        throw error;
      }
    };
  }

  getMetrics(timeRange = 'last-hour') {
    let cutoff;
    switch (timeRange) {
      case 'last-minute':
        cutoff = Date.now() - 60 * 1000;
        break;
      case 'last-hour':
        cutoff = Date.now() - 60 * 60 * 1000;
        break;
      case 'last-day':
        cutoff = Date.now() - 24 * 60 * 60 * 1000;
        break;
      default:
        cutoff = Date.now() - 60 * 60 * 1000; // Default to last hour
    }

    const filteredMetrics = this.timeSeries.filter(m => m.timestamp > cutoff);

    if (filteredMetrics.length === 0) {
      return null;
    }

    const latest = filteredMetrics[filteredMetrics.length - 1];

    // Calculate aggregated statistics
    const stats = this.calculateAggregatedStats(filteredMetrics);

    return {
      current: latest,
      aggregated: stats,
      timeRange,
      dataPoints: filteredMetrics.length
    };
  }

  calculateAggregatedStats(metrics) {
    if (metrics.length === 0) return null;

    const responseTimes = metrics.map(m => m.averageResponseTime).filter(rt => rt > 0);
    const errorRates = metrics.map(m => m.errorRate);
    const memoryUsage = metrics.map(m => m.memory.system.usagePercent);
    const cpuUsage = metrics.map(m => m.cpu.usage);

    return {
      responseTime: {
        avg: this.average(responseTimes),
        min: Math.min(...responseTimes),
        max: Math.max(...responseTimes),
        p95: this.percentile(responseTimes, 0.95)
      },
      errorRate: {
        avg: this.average(errorRates),
        min: Math.min(...errorRates),
        max: Math.max(...errorRates)
      },
      memory: {
        avg: this.average(memoryUsage),
        min: Math.min(...memoryUsage),
        max: Math.max(...memoryUsage)
      },
      cpu: {
        avg: this.average(cpuUsage),
        min: Math.min(...cpuUsage),
        max: Math.max(...cpuUsage)
      }
    };
  }

  getOperationStats() {
    const stats = {};

    for (const [operation, data] of this.counters.operations) {
      stats[operation] = {
        count: data.count,
        totalTime: data.totalTime,
        averageTime: data.count > 0 ? data.totalTime / data.count : 0
      };
    }

    return stats;
  }

  getAlerts(severity = null) {
    if (!severity) {
      return this.alerts;
    }

    return this.alerts.filter(alert => alert.severity === severity);
  }

  generateReport() {
    const metrics = this.getMetrics('last-hour');
    const operationStats = this.getOperationStats();
    const alerts = this.getAlerts();

    return {
      timestamp: Date.now(),
      uptime: Date.now() - this.startTime,
      systemInfo: this.systemInfo,
      metrics,
      operations: operationStats,
      alerts: alerts.length,
      criticalAlerts: alerts.filter(a => a.severity === 'critical').length,
      healthScore: this.calculateHealthScore(metrics)
    };
  }

  calculateHealthScore(metrics) {
    if (!metrics?.current) return 100;

    let score = 100;
    const current = metrics.current;

    // Deduct points for high resource usage
    if (current.memory.system.usagePercent > 0.8) score -= 20;
    else if (current.memory.system.usagePercent > 0.6) score -= 10;

    if (current.cpu.usage > 0.8) score -= 20;
    else if (current.cpu.usage > 0.6) score -= 10;

    // Deduct points for high response time
    if (current.averageResponseTime > 5000) score -= 25;
    else if (current.averageResponseTime > 2000) score -= 15;

    // Deduct points for errors
    if (current.errorRate > 0.05) score -= 30;
    else if (current.errorRate > 0.01) score -= 15;

    return Math.max(0, score);
  }

  // Utility methods

  generateOperationId() {
    return `op_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }

  average(numbers) {
    return numbers.length > 0 ? numbers.reduce((sum, n) => sum + n, 0) / numbers.length : 0;
  }

  percentile(numbers, p) {
    if (numbers.length === 0) return 0;
    const sorted = [...numbers].sort((a, b) => a - b);
    const index = Math.ceil(sorted.length * p) - 1;
    return sorted[Math.max(0, index)];
  }

  shutdown() {
    console.log('🛑 Shutting down Performance Monitor...');
    this.stopMonitoring();
    this.emit('monitor-shutdown');
    console.log('✅ Performance Monitor shutdown complete');
  }
}

// Factory functions
function createPerformanceMonitor(options = {}) {
  return new PerformanceMonitor(options);
}

function createMetricsCollector(options = {}) {
  return new MetricsCollector(options);
}

function createProfiler(options = {}) {
  return new Profiler(options);
}

module.exports = {
  // Main class (default export for backward compatibility)
  PerformanceMonitor,

  // Additional classes
  MetricsCollector,
  Profiler,
  Timer,
  AlertThresholdManager,

  // Factory functions
  createPerformanceMonitor,
  createMetricsCollector,
  createProfiler,

  // Constants
  METRIC_TYPES,
  AGGREGATION_TYPES,
  MONITOR_EVENTS,
  ALERT_LEVELS
};

// Default export for backward compatibility
module.exports.default = PerformanceMonitor;