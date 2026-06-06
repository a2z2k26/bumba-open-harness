/**
 * ContentHasher - Standalone content hashing module
 *
 * Provides efficient content hashing for change detection, story checksum guards,
 * and incremental processing throughout the design-bridge system.
 *
 * @module content-hasher
 * @version 1.0.0
 * @phase Option C - Sprint 1.2
 */

const crypto = require('crypto');
const fs = require('fs').promises;

// ============================================================================
// Constants
// ============================================================================

const HASH_ALGORITHM = 'sha256';
const DEFAULT_ENCODING = 'hex';
const DEFAULT_SHORT_LENGTH = 8;

// ============================================================================
// ContentHasher Class
// ============================================================================

/**
 * Generate content hashes for change detection and checksum comparison
 */
class ContentHasher {
  /**
   * Create a new ContentHasher instance
   * @param {Object} options - Configuration options
   * @param {string} [options.algorithm='sha256'] - Hash algorithm to use
   * @param {string} [options.encoding='hex'] - Output encoding (hex, base64)
   * @param {number} [options.shortHashLength=8] - Length of short hashes
   */
  constructor(options = {}) {
    this.algorithm = options.algorithm || HASH_ALGORITHM;
    this.encoding = options.encoding || DEFAULT_ENCODING;
    this.shortHashLength = options.shortHashLength || DEFAULT_SHORT_LENGTH;
    this.cache = new Map();
    this.stats = {
      computed: 0,
      cached: 0
    };
  }

  /**
   * Generate hash for content
   * @param {string|Object} content - Content to hash (strings or objects)
   * @param {Object} [options] - Hash options
   * @param {boolean} [options.noCache=false] - Skip cache lookup/storage
   * @returns {string} Hex-encoded hash
   */
  hash(content, options = {}) {
    const key = typeof content === 'string' ? content : JSON.stringify(content);

    // Check cache
    if (!options.noCache && this.cache.has(key)) {
      this.stats.cached++;
      return this.cache.get(key);
    }

    const hash = crypto
      .createHash(this.algorithm)
      .update(key)
      .digest(this.encoding);

    this.stats.computed++;

    // Cache result
    if (!options.noCache) {
      this.cache.set(key, hash);
    }

    return hash;
  }

  /**
   * Generate short hash (first N characters)
   * @param {string|Object} content - Content to hash
   * @returns {string} Short hash
   */
  shortHash(content) {
    return this.hash(content).slice(0, this.shortHashLength);
  }

  /**
   * Hash object properties recursively
   * @param {Object} obj - Object to hash
   * @returns {Object} Object with property hashes and root hash
   */
  hashObject(obj) {
    const hashes = {};

    const processValue = (value, path) => {
      if (value === null || value === undefined) {
        return this.hash('null');
      }

      if (typeof value === 'object' && !Array.isArray(value)) {
        const childHashes = {};
        for (const [key, val] of Object.entries(value)) {
          childHashes[key] = processValue(val, `${path}.${key}`);
        }
        return this.hash(JSON.stringify(childHashes));
      }

      return this.hash(JSON.stringify(value));
    };

    for (const [key, value] of Object.entries(obj)) {
      hashes[key] = processValue(value, key);
    }

    return {
      properties: hashes,
      root: this.hash(JSON.stringify(hashes))
    };
  }

  /**
   * Hash file content with metadata
   * @param {string} content - File content
   * @param {Object} [metadata={}] - Additional metadata to include in hash
   * @returns {Object} Content hash, metadata hash, and combined hash
   */
  hashFileContent(content, metadata = {}) {
    const contentHash = this.hash(content);
    const metaHash = this.hash(JSON.stringify(metadata));

    return {
      content: contentHash,
      metadata: metaHash,
      combined: this.hash(contentHash + metaHash)
    };
  }

  /**
   * Compare two hashes for equality
   * @param {string} hash1 - First hash
   * @param {string} hash2 - Second hash
   * @returns {boolean} True if hashes match
   */
  compare(hash1, hash2) {
    return hash1 === hash2;
  }

  /**
   * Clear the hash cache
   */
  clearCache() {
    this.cache.clear();
  }

  /**
   * Get hashing statistics
   * @returns {Object} Stats including computed count, cached count, and hit rate
   */
  getStats() {
    const total = this.stats.computed + this.stats.cached;
    return {
      ...this.stats,
      cacheSize: this.cache.size,
      hitRate: total > 0 ? this.stats.cached / total : 0
    };
  }
}

// ============================================================================
// Standalone Utility Functions
// ============================================================================

/**
 * Calculate SHA-256 hash of content (simple, no caching)
 * @param {string} content - Content to hash
 * @param {string} [encoding='hex'] - Output encoding
 * @returns {string} Hash string
 */
function calculateHash(content, encoding = DEFAULT_ENCODING) {
  return crypto
    .createHash(HASH_ALGORITHM)
    .update(content, 'utf8')
    .digest(encoding);
}

/**
 * Calculate hash of a file's contents
 * @param {string} filePath - Path to file
 * @param {string} [encoding='hex'] - Output encoding
 * @returns {Promise<string>} Hash string
 * @throws {Error} If file cannot be read
 */
async function hashFile(filePath, encoding = DEFAULT_ENCODING) {
  const content = await fs.readFile(filePath, 'utf8');
  return calculateHash(content, encoding);
}

/**
 * Compare file content to an expected hash
 * @param {string} filePath - Path to file
 * @param {string} expectedHash - Expected hash value
 * @returns {Promise<boolean>} True if file matches expected hash
 */
async function compareFileHash(filePath, expectedHash) {
  try {
    const currentHash = await hashFile(filePath);
    return currentHash === expectedHash;
  } catch {
    // File doesn't exist or can't be read
    return false;
  }
}

/**
 * Check if a file has been modified since hash was generated
 * @param {string} filePath - Path to file
 * @param {string} originalHash - Hash when file was generated
 * @returns {Promise<boolean>} True if file has been modified
 */
async function hasFileChanged(filePath, originalHash) {
  try {
    const currentHash = await hashFile(filePath);
    return currentHash !== originalHash;
  } catch {
    // File doesn't exist - consider it changed
    return true;
  }
}

// ============================================================================
// Exports
// ============================================================================

module.exports = {
  // Class
  ContentHasher,

  // Utility functions
  calculateHash,
  hashFile,
  compareFileHash,
  hasFileChanged,

  // Constants
  HASH_ALGORITHM,
  DEFAULT_ENCODING
};
