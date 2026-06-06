/**
 * Cache Manager Module
 * Phase 3 - Sprints 153-158: Performance Optimization
 *
 * Provides multi-layer caching for expensive operations:
 * - Memory cache (LRU) for hot data
 * - File cache for persistent data
 * - TTL-based expiration
 * - Cache invalidation strategies
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { createLogger } = require('./unified-logger');

const logger = createLogger('cache-manager');

// =============================================================================
// LRU CACHE IMPLEMENTATION
// =============================================================================

/**
 * Least Recently Used (LRU) Cache
 */
class LRUCache {
  constructor(maxSize = 100) {
    this.maxSize = maxSize;
    this.cache = new Map();
    this.hits = 0;
    this.misses = 0;
  }

  get(key) {
    if (!this.cache.has(key)) {
      this.misses++;
      return undefined;
    }

    // Move to end (most recently used)
    const value = this.cache.get(key);
    this.cache.delete(key);
    this.cache.set(key, value);
    this.hits++;

    return value;
  }

  set(key, value, ttl = null) {
    // Remove if exists to update position
    if (this.cache.has(key)) {
      this.cache.delete(key);
    }

    // Evict oldest if at capacity
    if (this.cache.size >= this.maxSize) {
      const firstKey = this.cache.keys().next().value;
      this.cache.delete(firstKey);
    }

    const entry = {
      value,
      createdAt: Date.now(),
      expiresAt: ttl ? Date.now() + ttl : null
    };

    this.cache.set(key, entry);
    return this;
  }

  has(key) {
    if (!this.cache.has(key)) return false;

    const entry = this.cache.get(key);
    if (entry.expiresAt && Date.now() > entry.expiresAt) {
      this.cache.delete(key);
      return false;
    }

    return true;
  }

  delete(key) {
    return this.cache.delete(key);
  }

  clear() {
    this.cache.clear();
    this.hits = 0;
    this.misses = 0;
  }

  size() {
    return this.cache.size;
  }

  getStats() {
    const total = this.hits + this.misses;
    return {
      size: this.cache.size,
      maxSize: this.maxSize,
      hits: this.hits,
      misses: this.misses,
      hitRate: total > 0 ? (this.hits / total * 100).toFixed(2) + '%' : '0%'
    };
  }

  // Clean expired entries
  prune() {
    const now = Date.now();
    let pruned = 0;

    for (const [key, entry] of this.cache.entries()) {
      if (entry.expiresAt && now > entry.expiresAt) {
        this.cache.delete(key);
        pruned++;
      }
    }

    return pruned;
  }
}

// =============================================================================
// FILE CACHE IMPLEMENTATION
// =============================================================================

/**
 * File-based persistent cache
 */
class FileCache {
  constructor(cacheDir, options = {}) {
    this.cacheDir = cacheDir;
    this.defaultTTL = options.defaultTTL || 3600000; // 1 hour
    this.maxFiles = options.maxFiles || 1000;

    this._ensureCacheDir();
  }

  _ensureCacheDir() {
    if (!fs.existsSync(this.cacheDir)) {
      fs.mkdirSync(this.cacheDir, { recursive: true });
    }
  }

  _getFilePath(key) {
    const hash = crypto.createHash('md5').update(key).digest('hex');
    return path.join(this.cacheDir, `${hash}.cache`);
  }

  get(key) {
    const filePath = this._getFilePath(key);

    if (!fs.existsSync(filePath)) {
      return undefined;
    }

    try {
      const content = fs.readFileSync(filePath, 'utf8');
      const entry = JSON.parse(content);

      // Check expiration
      if (entry.expiresAt && Date.now() > entry.expiresAt) {
        fs.unlinkSync(filePath);
        return undefined;
      }

      return entry.value;
    } catch (err) {
      logger.warn('File cache read error', { key, error: err.message });
      return undefined;
    }
  }

  set(key, value, ttl = null) {
    const filePath = this._getFilePath(key);
    const entry = {
      key,
      value,
      createdAt: Date.now(),
      expiresAt: ttl ? Date.now() + ttl : Date.now() + this.defaultTTL
    };

    try {
      fs.writeFileSync(filePath, JSON.stringify(entry, null, 2));
      return true;
    } catch (err) {
      logger.warn('File cache write error', { key, error: err.message });
      return false;
    }
  }

  has(key) {
    return this.get(key) !== undefined;
  }

  delete(key) {
    const filePath = this._getFilePath(key);

    if (fs.existsSync(filePath)) {
      fs.unlinkSync(filePath);
      return true;
    }

    return false;
  }

  clear() {
    try {
      const files = fs.readdirSync(this.cacheDir);
      for (const file of files) {
        if (file.endsWith('.cache')) {
          fs.unlinkSync(path.join(this.cacheDir, file));
        }
      }
      return true;
    } catch (err) {
      logger.error('File cache clear error', { error: err.message });
      return false;
    }
  }

  prune() {
    let pruned = 0;
    const now = Date.now();

    try {
      const files = fs.readdirSync(this.cacheDir);

      for (const file of files) {
        if (!file.endsWith('.cache')) continue;

        const filePath = path.join(this.cacheDir, file);
        try {
          const content = fs.readFileSync(filePath, 'utf8');
          const entry = JSON.parse(content);

          if (entry.expiresAt && now > entry.expiresAt) {
            fs.unlinkSync(filePath);
            pruned++;
          }
        } catch (err) {
          // Corrupted cache file, remove it
          fs.unlinkSync(filePath);
          pruned++;
        }
      }
    } catch (err) {
      logger.error('File cache prune error', { error: err.message });
    }

    return pruned;
  }

  getStats() {
    try {
      const files = fs.readdirSync(this.cacheDir).filter(f => f.endsWith('.cache'));
      let totalSize = 0;

      for (const file of files) {
        const stat = fs.statSync(path.join(this.cacheDir, file));
        totalSize += stat.size;
      }

      return {
        files: files.length,
        maxFiles: this.maxFiles,
        totalSize: totalSize,
        totalSizeMB: (totalSize / 1024 / 1024).toFixed(2) + 'MB'
      };
    } catch (err) {
      return { files: 0, maxFiles: this.maxFiles, totalSize: 0, error: err.message };
    }
  }
}

// =============================================================================
// MULTI-LAYER CACHE MANAGER
// =============================================================================

/**
 * Multi-layer cache with memory and file backends
 */
class CacheManager {
  constructor(options = {}) {
    this.name = options.name || 'default';
    this.memoryCache = new LRUCache(options.memoryCacheSize || 100);
    this.fileCache = options.cacheDir
      ? new FileCache(options.cacheDir, { defaultTTL: options.fileTTL })
      : null;
    this.defaultTTL = options.defaultTTL || 300000; // 5 minutes
    this.useFileCache = options.useFileCache !== false && this.fileCache !== null;

    // Auto-prune interval
    if (options.autoPrune !== false) {
      this.pruneInterval = setInterval(() => {
        this.prune();
      }, options.pruneInterval || 60000); // Every minute
    }

    logger.debug('CacheManager initialized', {
      name: this.name,
      memoryCacheSize: options.memoryCacheSize || 100,
      useFileCache: this.useFileCache
    });
  }

  /**
   * Generate cache key from function arguments
   */
  static generateKey(prefix, ...args) {
    const argsHash = crypto
      .createHash('md5')
      .update(JSON.stringify(args))
      .digest('hex');
    return `${prefix}:${argsHash}`;
  }

  /**
   * Get value from cache (memory first, then file)
   */
  get(key) {
    // Check memory cache first
    if (this.memoryCache.has(key)) {
      const entry = this.memoryCache.get(key);
      if (entry && !this._isExpired(entry)) {
        return entry.value;
      }
    }

    // Fall back to file cache
    if (this.useFileCache) {
      const value = this.fileCache.get(key);
      if (value !== undefined) {
        // Promote to memory cache
        this.memoryCache.set(key, value, this.defaultTTL);
        return value;
      }
    }

    return undefined;
  }

  /**
   * Set value in cache
   */
  set(key, value, options = {}) {
    const ttl = options.ttl || this.defaultTTL;

    // Always set in memory cache
    this.memoryCache.set(key, value, ttl);

    // Optionally set in file cache for persistence
    if (this.useFileCache && options.persist !== false) {
      this.fileCache.set(key, value, options.fileTTL || ttl * 2);
    }

    return this;
  }

  /**
   * Check if key exists
   */
  has(key) {
    return this.memoryCache.has(key) ||
           (this.useFileCache && this.fileCache.has(key));
  }

  /**
   * Delete from all cache layers
   */
  delete(key) {
    this.memoryCache.delete(key);
    if (this.useFileCache) {
      this.fileCache.delete(key);
    }
    return this;
  }

  /**
   * Clear all caches
   */
  clear() {
    this.memoryCache.clear();
    if (this.useFileCache) {
      this.fileCache.clear();
    }
    return this;
  }

  /**
   * Prune expired entries
   */
  prune() {
    const memoryPruned = this.memoryCache.prune();
    const filePruned = this.useFileCache ? this.fileCache.prune() : 0;

    if (memoryPruned > 0 || filePruned > 0) {
      logger.debug('Cache pruned', { memoryPruned, filePruned });
    }

    return { memoryPruned, filePruned };
  }

  /**
   * Get cache statistics
   */
  getStats() {
    return {
      name: this.name,
      memory: this.memoryCache.getStats(),
      file: this.useFileCache ? this.fileCache.getStats() : null
    };
  }

  /**
   * Memoize a function with caching
   */
  memoize(fn, options = {}) {
    const prefix = options.prefix || fn.name || 'memoized';
    const ttl = options.ttl || this.defaultTTL;

    return async (...args) => {
      const key = CacheManager.generateKey(prefix, ...args);

      // Check cache
      const cached = this.get(key);
      if (cached !== undefined) {
        logger.trace('Cache hit', { key, prefix });
        return cached;
      }

      // Execute function
      logger.trace('Cache miss', { key, prefix });
      const result = await fn(...args);

      // Store result
      this.set(key, result, { ttl, persist: options.persist });

      return result;
    };
  }

  /**
   * Invalidate cache entries by pattern
   */
  invalidatePattern(pattern) {
    let invalidated = 0;
    const regex = new RegExp(pattern);

    // Memory cache
    for (const key of this.memoryCache.cache.keys()) {
      if (regex.test(key)) {
        this.memoryCache.delete(key);
        invalidated++;
      }
    }

    // File cache (more expensive, optional)
    // Note: File cache doesn't support pattern invalidation efficiently

    logger.debug('Cache invalidated by pattern', { pattern, invalidated });
    return invalidated;
  }

  _isExpired(entry) {
    return entry.expiresAt && Date.now() > entry.expiresAt;
  }

  /**
   * Stop auto-prune interval
   */
  destroy() {
    if (this.pruneInterval) {
      clearInterval(this.pruneInterval);
    }
  }
}

// =============================================================================
// SPECIALIZED CACHES
// =============================================================================

/**
 * Component cache for generated code
 */
class ComponentCache extends CacheManager {
  constructor(options = {}) {
    super({
      name: 'component-cache',
      memoryCacheSize: 50,
      defaultTTL: 600000, // 10 minutes
      ...options
    });
  }

  getComponentKey(componentId, framework, options = {}) {
    return CacheManager.generateKey(
      'component',
      componentId,
      framework,
      options.variant || 'default',
      options.theme || 'default'
    );
  }

  getComponent(componentId, framework, options = {}) {
    const key = this.getComponentKey(componentId, framework, options);
    return this.get(key);
  }

  setComponent(componentId, framework, code, options = {}) {
    const key = this.getComponentKey(componentId, framework, options);
    return this.set(key, code, { ttl: options.ttl, persist: true });
  }

  invalidateComponent(componentId) {
    return this.invalidatePattern(`component:.*${componentId}.*`);
  }
}

/**
 * Token cache for design tokens
 */
class TokenCache extends CacheManager {
  constructor(options = {}) {
    super({
      name: 'token-cache',
      memoryCacheSize: 200,
      defaultTTL: 300000, // 5 minutes
      ...options
    });
  }

  getTokenKey(tokenPath, format = 'css') {
    return CacheManager.generateKey('token', tokenPath, format);
  }

  getToken(tokenPath, format = 'css') {
    const key = this.getTokenKey(tokenPath, format);
    return this.get(key);
  }

  setToken(tokenPath, value, format = 'css') {
    const key = this.getTokenKey(tokenPath, format);
    return this.set(key, value);
  }

  invalidateAll() {
    return this.invalidatePattern('^token:');
  }
}

/**
 * Figma API response cache
 */
class FigmaCache extends CacheManager {
  constructor(options = {}) {
    super({
      name: 'figma-cache',
      memoryCacheSize: 30,
      defaultTTL: 120000, // 2 minutes (Figma data changes frequently)
      ...options
    });
  }

  getNodeKey(fileKey, nodeId) {
    return CacheManager.generateKey('figma-node', fileKey, nodeId);
  }

  getNode(fileKey, nodeId) {
    const key = this.getNodeKey(fileKey, nodeId);
    return this.get(key);
  }

  setNode(fileKey, nodeId, data) {
    const key = this.getNodeKey(fileKey, nodeId);
    return this.set(key, data, { persist: false }); // Don't persist Figma data
  }

  invalidateFile(fileKey) {
    return this.invalidatePattern(`figma-node:.*${fileKey}.*`);
  }
}

// =============================================================================
// SINGLETON INSTANCES
// =============================================================================

let defaultCacheManager = null;

function getCacheManager(options = {}) {
  if (!defaultCacheManager) {
    defaultCacheManager = new CacheManager(options);
  }
  return defaultCacheManager;
}

function resetCacheManager() {
  if (defaultCacheManager) {
    defaultCacheManager.destroy();
    defaultCacheManager = null;
  }
}

module.exports = {
  // Core classes
  LRUCache,
  FileCache,
  CacheManager,

  // Specialized caches
  ComponentCache,
  TokenCache,
  FigmaCache,

  // Factory functions
  getCacheManager,
  resetCacheManager
};
