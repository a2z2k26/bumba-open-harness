/**
 * Phase 9, Sprint 9.1: Caching Layer & Memoization
 *
 * Multi-tier caching system with LRU eviction, TTL expiration,
 * memoization utilities, and cache statistics.
 */

const { EventEmitter } = require('events');
const fs = require('fs').promises;
const path = require('path');
const crypto = require('crypto');

// Cache tier types
const CACHE_TIERS = {
  MEMORY: 'memory',
  FILE: 'file',
  DISTRIBUTED: 'distributed'
};

// Default TTL values (in milliseconds)
const DEFAULT_TTL = {
  SHORT: 60 * 1000,           // 1 minute
  MEDIUM: 5 * 60 * 1000,      // 5 minutes
  LONG: 30 * 60 * 1000,       // 30 minutes
  HOUR: 60 * 60 * 1000,       // 1 hour
  DAY: 24 * 60 * 60 * 1000    // 24 hours
};

// Cache events
const CACHE_EVENTS = {
  HIT: 'cache:hit',
  MISS: 'cache:miss',
  SET: 'cache:set',
  DELETE: 'cache:delete',
  EXPIRE: 'cache:expire',
  EVICT: 'cache:evict',
  CLEAR: 'cache:clear',
  ERROR: 'cache:error'
};

/**
 * LRU (Least Recently Used) Cache Node
 */
class LRUNode {
  constructor(key, value, ttl = null) {
    this.key = key;
    this.value = value;
    this.ttl = ttl;
    this.createdAt = Date.now();
    this.accessedAt = Date.now();
    this.accessCount = 0;
    this.prev = null;
    this.next = null;
  }

  isExpired() {
    if (!this.ttl) return false;
    return Date.now() > this.createdAt + this.ttl;
  }

  touch() {
    this.accessedAt = Date.now();
    this.accessCount++;
  }
}

/**
 * LRU Cache Implementation
 * Double-linked list + HashMap for O(1) operations
 */
class LRUCache extends EventEmitter {
  constructor(options = {}) {
    super();
    this.maxSize = options.maxSize || 1000;
    this.defaultTTL = options.defaultTTL || null;
    this.name = options.name || 'lru-cache';

    // HashMap for O(1) lookup
    this.cache = new Map();

    // Doubly linked list for LRU ordering
    this.head = null; // Most recently used
    this.tail = null; // Least recently used

    // Statistics
    this.stats = {
      hits: 0,
      misses: 0,
      sets: 0,
      deletes: 0,
      evictions: 0,
      expirations: 0
    };

    // Start expiration checker if TTL is used
    if (this.defaultTTL) {
      this.startExpirationChecker();
    }
  }

  /**
   * Get value from cache
   */
  get(key) {
    const node = this.cache.get(key);

    if (!node) {
      this.stats.misses++;
      this.emit(CACHE_EVENTS.MISS, { key, cache: this.name });
      return undefined;
    }

    // Check expiration
    if (node.isExpired()) {
      this.delete(key);
      this.stats.expirations++;
      this.emit(CACHE_EVENTS.EXPIRE, { key, cache: this.name });
      return undefined;
    }

    // Move to head (most recently used)
    this.moveToHead(node);
    node.touch();

    this.stats.hits++;
    this.emit(CACHE_EVENTS.HIT, { key, cache: this.name });

    return node.value;
  }

  /**
   * Set value in cache
   */
  set(key, value, ttl = this.defaultTTL) {
    let node = this.cache.get(key);

    if (node) {
      // Update existing node
      node.value = value;
      node.ttl = ttl;
      node.createdAt = Date.now();
      this.moveToHead(node);
    } else {
      // Create new node
      node = new LRUNode(key, value, ttl);
      this.cache.set(key, node);
      this.addToHead(node);

      // Evict if over capacity
      if (this.cache.size > this.maxSize) {
        this.evictLRU();
      }
    }

    this.stats.sets++;
    this.emit(CACHE_EVENTS.SET, { key, cache: this.name });

    return this;
  }

  /**
   * Delete value from cache
   */
  delete(key) {
    const node = this.cache.get(key);
    if (!node) return false;

    this.removeNode(node);
    this.cache.delete(key);

    this.stats.deletes++;
    this.emit(CACHE_EVENTS.DELETE, { key, cache: this.name });

    return true;
  }

  /**
   * Check if key exists
   */
  has(key) {
    const node = this.cache.get(key);
    if (!node) return false;
    if (node.isExpired()) {
      this.delete(key);
      return false;
    }
    return true;
  }

  /**
   * Clear entire cache
   */
  clear() {
    this.cache.clear();
    this.head = null;
    this.tail = null;
    this.emit(CACHE_EVENTS.CLEAR, { cache: this.name });
  }

  /**
   * Get cache size
   */
  get size() {
    return this.cache.size;
  }

  /**
   * Get all keys
   */
  keys() {
    return Array.from(this.cache.keys());
  }

  /**
   * Get all values
   */
  values() {
    return Array.from(this.cache.values()).map(node => node.value);
  }

  /**
   * Get cache statistics
   */
  getStats() {
    const total = this.stats.hits + this.stats.misses;
    return {
      ...this.stats,
      size: this.cache.size,
      maxSize: this.maxSize,
      hitRate: total > 0 ? (this.stats.hits / total * 100).toFixed(2) + '%' : '0%'
    };
  }

  /**
   * Reset statistics
   */
  resetStats() {
    this.stats = {
      hits: 0,
      misses: 0,
      sets: 0,
      deletes: 0,
      evictions: 0,
      expirations: 0
    };
  }

  // Internal: Add node to head of list
  addToHead(node) {
    node.prev = null;
    node.next = this.head;

    if (this.head) {
      this.head.prev = node;
    }

    this.head = node;

    if (!this.tail) {
      this.tail = node;
    }
  }

  // Internal: Remove node from list
  removeNode(node) {
    if (node.prev) {
      node.prev.next = node.next;
    } else {
      this.head = node.next;
    }

    if (node.next) {
      node.next.prev = node.prev;
    } else {
      this.tail = node.prev;
    }
  }

  // Internal: Move node to head
  moveToHead(node) {
    this.removeNode(node);
    this.addToHead(node);
  }

  // Internal: Evict least recently used item
  evictLRU() {
    if (!this.tail) return;

    const key = this.tail.key;
    this.removeNode(this.tail);
    this.cache.delete(key);

    this.stats.evictions++;
    this.emit(CACHE_EVENTS.EVICT, { key, cache: this.name });
  }

  // Internal: Start expiration checker interval
  startExpirationChecker() {
    this.expirationInterval = setInterval(() => {
      const now = Date.now();
      for (const [key, node] of this.cache) {
        if (node.isExpired()) {
          this.delete(key);
          this.stats.expirations++;
          this.emit(CACHE_EVENTS.EXPIRE, { key, cache: this.name });
        }
      }
    }, Math.min(this.defaultTTL, 60000)); // Check at least every minute
  }

  /**
   * Stop cache and cleanup
   */
  destroy() {
    if (this.expirationInterval) {
      clearInterval(this.expirationInterval);
    }
    this.clear();
  }
}

/**
 * File-based Cache
 * Persists cache to filesystem for durability
 */
class FileCache extends EventEmitter {
  constructor(options = {}) {
    super();
    this.cacheDir = options.cacheDir || '.cache';
    this.defaultTTL = options.defaultTTL || DEFAULT_TTL.HOUR;
    this.name = options.name || 'file-cache';
    this.indexFile = path.join(this.cacheDir, '_index.json');
    this.index = new Map();
    this.initialized = false;

    this.stats = {
      hits: 0,
      misses: 0,
      sets: 0,
      deletes: 0
    };
  }

  /**
   * Initialize file cache
   */
  async init() {
    try {
      await fs.mkdir(this.cacheDir, { recursive: true });
      await this.loadIndex();
      this.initialized = true;
    } catch (error) {
      this.emit(CACHE_EVENTS.ERROR, { error, cache: this.name });
      throw error;
    }
  }

  /**
   * Generate cache key hash
   */
  hashKey(key) {
    return crypto.createHash('md5').update(key).digest('hex');
  }

  /**
   * Get file path for key
   */
  getFilePath(key) {
    const hash = this.hashKey(key);
    // Use subdirectories for better filesystem performance
    const subdir = hash.substring(0, 2);
    return path.join(this.cacheDir, subdir, `${hash}.json`);
  }

  /**
   * Get value from file cache
   */
  async get(key) {
    if (!this.initialized) await this.init();

    const meta = this.index.get(key);

    if (!meta) {
      this.stats.misses++;
      this.emit(CACHE_EVENTS.MISS, { key, cache: this.name });
      return undefined;
    }

    // Check expiration
    if (meta.expiresAt && Date.now() > meta.expiresAt) {
      await this.delete(key);
      this.emit(CACHE_EVENTS.EXPIRE, { key, cache: this.name });
      return undefined;
    }

    try {
      const filePath = this.getFilePath(key);
      const content = await fs.readFile(filePath, 'utf8');
      const data = JSON.parse(content);

      this.stats.hits++;
      this.emit(CACHE_EVENTS.HIT, { key, cache: this.name });

      return data.value;
    } catch (error) {
      this.stats.misses++;
      this.index.delete(key);
      await this.saveIndex();
      return undefined;
    }
  }

  /**
   * Set value in file cache
   */
  async set(key, value, ttl = this.defaultTTL) {
    if (!this.initialized) await this.init();

    const filePath = this.getFilePath(key);
    const dir = path.dirname(filePath);

    const meta = {
      key,
      createdAt: Date.now(),
      expiresAt: ttl ? Date.now() + ttl : null
    };

    const data = {
      key,
      value,
      meta
    };

    try {
      await fs.mkdir(dir, { recursive: true });
      await fs.writeFile(filePath, JSON.stringify(data, null, 2));

      this.index.set(key, meta);
      await this.saveIndex();

      this.stats.sets++;
      this.emit(CACHE_EVENTS.SET, { key, cache: this.name });
    } catch (error) {
      this.emit(CACHE_EVENTS.ERROR, { error, key, cache: this.name });
      throw error;
    }
  }

  /**
   * Delete value from file cache
   */
  async delete(key) {
    if (!this.initialized) await this.init();

    const filePath = this.getFilePath(key);

    try {
      await fs.unlink(filePath);
    } catch (error) {
      // Ignore file not found errors
    }

    this.index.delete(key);
    await this.saveIndex();

    this.stats.deletes++;
    this.emit(CACHE_EVENTS.DELETE, { key, cache: this.name });

    return true;
  }

  /**
   * Check if key exists
   */
  async has(key) {
    if (!this.initialized) await this.init();

    const meta = this.index.get(key);
    if (!meta) return false;

    if (meta.expiresAt && Date.now() > meta.expiresAt) {
      await this.delete(key);
      return false;
    }

    return true;
  }

  /**
   * Clear entire cache
   */
  async clear() {
    if (!this.initialized) await this.init();

    // Delete all cache files
    for (const key of this.index.keys()) {
      try {
        await fs.unlink(this.getFilePath(key));
      } catch (error) {
        // Ignore errors
      }
    }

    this.index.clear();
    await this.saveIndex();

    this.emit(CACHE_EVENTS.CLEAR, { cache: this.name });
  }

  /**
   * Get cache size
   */
  get size() {
    return this.index.size;
  }

  /**
   * Get all keys
   */
  keys() {
    return Array.from(this.index.keys());
  }

  /**
   * Get cache statistics
   */
  getStats() {
    const total = this.stats.hits + this.stats.misses;
    return {
      ...this.stats,
      size: this.index.size,
      hitRate: total > 0 ? (this.stats.hits / total * 100).toFixed(2) + '%' : '0%'
    };
  }

  // Internal: Load index from disk
  async loadIndex() {
    try {
      const content = await fs.readFile(this.indexFile, 'utf8');
      const data = JSON.parse(content);
      this.index = new Map(data);
    } catch (error) {
      this.index = new Map();
    }
  }

  // Internal: Save index to disk
  async saveIndex() {
    const data = Array.from(this.index.entries());
    await fs.writeFile(this.indexFile, JSON.stringify(data, null, 2));
  }
}

/**
 * Multi-tier Cache Manager
 * Coordinates multiple cache layers
 */
class CacheManager extends EventEmitter {
  constructor(options = {}) {
    super();
    this.tiers = new Map();
    this.tierOrder = [];
    this.options = options;

    this.stats = {
      totalHits: 0,
      totalMisses: 0,
      tierHits: {}
    };
  }

  /**
   * Add a cache tier
   */
  addTier(name, cache, priority = 0) {
    this.tiers.set(name, { cache, priority });
    this.tierOrder = Array.from(this.tiers.entries())
      .sort((a, b) => a[1].priority - b[1].priority)
      .map(([name]) => name);

    this.stats.tierHits[name] = 0;

    // Forward events
    cache.on(CACHE_EVENTS.HIT, (data) => this.emit(CACHE_EVENTS.HIT, { ...data, tier: name }));
    cache.on(CACHE_EVENTS.MISS, (data) => this.emit(CACHE_EVENTS.MISS, { ...data, tier: name }));
    cache.on(CACHE_EVENTS.ERROR, (data) => this.emit(CACHE_EVENTS.ERROR, { ...data, tier: name }));

    return this;
  }

  /**
   * Remove a cache tier
   */
  removeTier(name) {
    this.tiers.delete(name);
    this.tierOrder = this.tierOrder.filter(t => t !== name);
    delete this.stats.tierHits[name];
    return this;
  }

  /**
   * Get value from cache (checks all tiers)
   */
  async get(key) {
    for (const tierName of this.tierOrder) {
      const { cache } = this.tiers.get(tierName);
      const value = cache.get ? cache.get(key) : await cache.get(key);

      if (value !== undefined) {
        this.stats.totalHits++;
        this.stats.tierHits[tierName]++;

        // Populate higher priority tiers
        await this.populateHigherTiers(key, value, tierName);

        return value;
      }
    }

    this.stats.totalMisses++;
    return undefined;
  }

  /**
   * Set value in all cache tiers
   */
  async set(key, value, ttl) {
    const promises = [];

    for (const tierName of this.tierOrder) {
      const { cache } = this.tiers.get(tierName);
      if (cache.set.constructor.name === 'AsyncFunction') {
        promises.push(cache.set(key, value, ttl));
      } else {
        cache.set(key, value, ttl);
      }
    }

    await Promise.all(promises);
  }

  /**
   * Delete value from all cache tiers
   */
  async delete(key) {
    const promises = [];

    for (const tierName of this.tierOrder) {
      const { cache } = this.tiers.get(tierName);
      if (cache.delete.constructor.name === 'AsyncFunction') {
        promises.push(cache.delete(key));
      } else {
        cache.delete(key);
      }
    }

    await Promise.all(promises);
  }

  /**
   * Clear all cache tiers
   */
  async clear() {
    const promises = [];

    for (const tierName of this.tierOrder) {
      const { cache } = this.tiers.get(tierName);
      if (cache.clear.constructor.name === 'AsyncFunction') {
        promises.push(cache.clear());
      } else {
        cache.clear();
      }
    }

    await Promise.all(promises);
  }

  /**
   * Get statistics from all tiers
   */
  getStats() {
    const tierStats = {};

    for (const [name, { cache }] of this.tiers) {
      tierStats[name] = cache.getStats ? cache.getStats() : {};
    }

    const total = this.stats.totalHits + this.stats.totalMisses;

    return {
      totalHits: this.stats.totalHits,
      totalMisses: this.stats.totalMisses,
      hitRate: total > 0 ? (this.stats.totalHits / total * 100).toFixed(2) + '%' : '0%',
      tierHits: this.stats.tierHits,
      tiers: tierStats
    };
  }

  // Internal: Populate higher priority tiers with value
  async populateHigherTiers(key, value, foundInTier) {
    const foundIndex = this.tierOrder.indexOf(foundInTier);

    for (let i = 0; i < foundIndex; i++) {
      const tierName = this.tierOrder[i];
      const { cache } = this.tiers.get(tierName);

      if (cache.set.constructor.name === 'AsyncFunction') {
        await cache.set(key, value);
      } else {
        cache.set(key, value);
      }
    }
  }
}

/**
 * Memoization utility
 * Caches function results based on arguments
 */
function memoize(fn, options = {}) {
  const {
    cache = new LRUCache({ maxSize: 100 }),
    keyGenerator = (...args) => JSON.stringify(args),
    ttl = null
  } = options;

  const memoized = function(...args) {
    const key = keyGenerator(...args);

    if (cache.has(key)) {
      return cache.get(key);
    }

    const result = fn.apply(this, args);

    // Handle promises
    if (result instanceof Promise) {
      return result.then(value => {
        cache.set(key, value, ttl);
        return value;
      });
    }

    cache.set(key, result, ttl);
    return result;
  };

  // Expose cache for manual management
  memoized.cache = cache;
  memoized.clear = () => cache.clear();

  return memoized;
}

/**
 * Async memoization with deduplication
 * Prevents duplicate in-flight requests
 */
function memoizeAsync(fn, options = {}) {
  const {
    cache = new LRUCache({ maxSize: 100 }),
    keyGenerator = (...args) => JSON.stringify(args),
    ttl = null
  } = options;

  const pending = new Map();

  const memoized = async function(...args) {
    const key = keyGenerator(...args);

    // Check cache first
    if (cache.has(key)) {
      return cache.get(key);
    }

    // Check for pending request
    if (pending.has(key)) {
      return pending.get(key);
    }

    // Start new request
    const promise = fn.apply(this, args).then(value => {
      pending.delete(key);
      cache.set(key, value, ttl);
      return value;
    }).catch(error => {
      pending.delete(key);
      throw error;
    });

    pending.set(key, promise);
    return promise;
  };

  memoized.cache = cache;
  memoized.pending = pending;
  memoized.clear = () => {
    cache.clear();
    pending.clear();
  };

  return memoized;
}

/**
 * Cache decorator for class methods
 */
function cached(options = {}) {
  return function(target, propertyKey, descriptor) {
    const originalMethod = descriptor.value;
    const cache = new LRUCache({
      maxSize: options.maxSize || 100,
      defaultTTL: options.ttl || null
    });

    descriptor.value = function(...args) {
      const key = options.keyGenerator
        ? options.keyGenerator(...args)
        : JSON.stringify(args);

      if (cache.has(key)) {
        return cache.get(key);
      }

      const result = originalMethod.apply(this, args);

      if (result instanceof Promise) {
        return result.then(value => {
          cache.set(key, value);
          return value;
        });
      }

      cache.set(key, result);
      return result;
    };

    descriptor.value.cache = cache;
    descriptor.value.clearCache = () => cache.clear();

    return descriptor;
  };
}

/**
 * Cache key builder utility
 */
class CacheKeyBuilder {
  constructor(namespace = '') {
    this.namespace = namespace;
    this.parts = [];
  }

  static create(namespace) {
    return new CacheKeyBuilder(namespace);
  }

  add(part) {
    this.parts.push(String(part));
    return this;
  }

  addObject(obj) {
    const sorted = Object.keys(obj).sort().reduce((acc, key) => {
      acc[key] = obj[key];
      return acc;
    }, {});
    this.parts.push(JSON.stringify(sorted));
    return this;
  }

  addHash(data) {
    const hash = crypto.createHash('md5')
      .update(typeof data === 'string' ? data : JSON.stringify(data))
      .digest('hex')
      .substring(0, 8);
    this.parts.push(hash);
    return this;
  }

  build() {
    const key = this.parts.join(':');
    return this.namespace ? `${this.namespace}:${key}` : key;
  }
}

/**
 * Cache invalidation patterns
 */
class CacheInvalidator {
  constructor(cacheManager) {
    this.cacheManager = cacheManager;
    this.patterns = new Map();
    this.tags = new Map(); // tag -> Set<key>
  }

  /**
   * Register a key with tags for group invalidation
   */
  registerTags(key, tags) {
    for (const tag of tags) {
      if (!this.tags.has(tag)) {
        this.tags.set(tag, new Set());
      }
      this.tags.get(tag).add(key);
    }
  }

  /**
   * Invalidate all keys with a specific tag
   */
  async invalidateByTag(tag) {
    const keys = this.tags.get(tag);
    if (!keys) return 0;

    let count = 0;
    for (const key of keys) {
      await this.cacheManager.delete(key);
      count++;
    }

    this.tags.delete(tag);
    return count;
  }

  /**
   * Invalidate keys matching a pattern
   */
  async invalidateByPattern(pattern) {
    const regex = new RegExp(pattern);
    let count = 0;

    for (const [tierName, { cache }] of this.cacheManager.tiers) {
      const keys = cache.keys();
      for (const key of keys) {
        if (regex.test(key)) {
          if (cache.delete.constructor.name === 'AsyncFunction') {
            await cache.delete(key);
          } else {
            cache.delete(key);
          }
          count++;
        }
      }
    }

    return count;
  }

  /**
   * Clear all tags
   */
  clearTags() {
    this.tags.clear();
  }
}

/**
 * Create a configured cache manager with standard tiers
 */
function createCacheManager(options = {}) {
  const manager = new CacheManager();

  // Add memory tier (fastest, smallest)
  const memoryCache = new LRUCache({
    maxSize: options.memoryMaxSize || 500,
    defaultTTL: options.memoryTTL || DEFAULT_TTL.MEDIUM,
    name: 'memory'
  });
  manager.addTier('memory', memoryCache, 0);

  // Add file tier if enabled (slower, persistent)
  if (options.enableFileCache !== false) {
    const fileCache = new FileCache({
      cacheDir: options.cacheDir || '.cache',
      defaultTTL: options.fileTTL || DEFAULT_TTL.HOUR,
      name: 'file'
    });
    manager.addTier('file', fileCache, 1);
  }

  return manager;
}

// Export everything
module.exports = {
  // Core classes
  LRUCache,
  LRUNode,
  FileCache,
  CacheManager,

  // Utilities
  memoize,
  memoizeAsync,
  cached,
  CacheKeyBuilder,
  CacheInvalidator,

  // Factory
  createCacheManager,

  // Constants
  CACHE_TIERS,
  DEFAULT_TTL,
  CACHE_EVENTS
};
