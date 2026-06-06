/**
 * Canonical ID System
 *
 * Provides stable, content-based identification for design elements.
 * Creates deterministic IDs that survive refactoring and Figma ID changes,
 * enabling reliable sync and tracking across transformations.
 *
 * Key Principle: Make failures observable and recoverable, not silent and destructive.
 *
 * v4.0.0 Integration:
 * - Added REGISTRY_V4 strategy for RegistryManager-compatible IDs
 * - Format: {source}-{type}-{name-slug}-{suffix}
 * - Full integration with RegistryManager sourceMapping and idIndex
 *
 * @module canonical-id
 */

'use strict';

const crypto = require('crypto');
const path = require('path');
const fs = require('fs');

// Lazy-load RegistryManager to avoid circular dependencies
let _registryManagerModule = null;
function getRegistryManagerModule() {
  if (!_registryManagerModule) {
    _registryManagerModule = require('./registry-manager');
  }
  return _registryManagerModule;
}

// =============================================================================
// CONSTANTS
// =============================================================================

/**
 * ID generation strategies
 */
const ID_STRATEGIES = {
  CONTENT_HASH: 'content-hash',     // Hash of node content/structure
  PATH_BASED: 'path-based',         // Based on node path in tree
  SEMANTIC: 'semantic',             // Based on semantic meaning
  COMPOSITE: 'composite',           // Combination of multiple strategies
  FIGMA_STABLE: 'figma-stable',     // Normalized Figma ID
  CUSTOM: 'custom',                 // User-defined strategy
  REGISTRY_V4: 'registry-v4'        // v4.0.0 format: {source}-{type}-{name-slug}-{suffix}
};

/**
 * Valid sources for v4.0.0 canonical IDs
 */
const V4_SOURCES = ['figma-plugin', 'shadcn-mcp', 'nlp-prompt', 'manual', 'migration'];

/**
 * Valid types for v4.0.0 canonical IDs
 */
const V4_TYPES = ['component', 'token', 'layout'];

/**
 * Hash algorithms available
 */
const HASH_ALGORITHMS = {
  SHA256: 'sha256',
  SHA1: 'sha1',
  MD5: 'md5'
};

/**
 * Default configuration
 */
const DEFAULT_CONFIG = {
  strategy: ID_STRATEGIES.COMPOSITE,
  hashAlgorithm: HASH_ALGORITHMS.SHA256,
  hashLength: 12,
  includeType: true,
  includeName: true,
  includePosition: false,
  includeDimensions: true,
  caseNormalize: true,
  separator: '-'
};

// =============================================================================
// ID GENERATOR
// =============================================================================

/**
 * Generator for canonical IDs
 */
class CanonicalIdGenerator {
  /**
   * Create an ID generator
   * @param {Object} options - Configuration options
   */
  constructor(options = {}) {
    this.config = { ...DEFAULT_CONFIG, ...options };
    this.customStrategies = new Map();
    this.generatedIds = new Map();
    this.collisionCount = 0;
  }

  /**
   * Generate a hash from input
   * @param {string} input - Input string
   * @param {number} length - Desired hash length
   * @returns {string} Hash string
   * @private
   */
  _hash(input, length = this.config.hashLength) {
    const hash = crypto
      .createHash(this.config.hashAlgorithm)
      .update(input)
      .digest('hex');
    return hash.substring(0, length);
  }

  /**
   * Normalize a string for ID generation
   * @param {string} str - Input string
   * @returns {string} Normalized string
   * @private
   */
  _normalize(str) {
    if (!str) return '';

    let normalized = str
      .replace(/[^a-zA-Z0-9\s-_]/g, '')  // Remove special chars
      .replace(/\s+/g, '-')               // Replace spaces with separator
      .replace(/-+/g, '-')                // Collapse multiple separators
      .trim();

    if (this.config.caseNormalize) {
      normalized = normalized.toLowerCase();
    }

    return normalized;
  }

  /**
   * Generate content-based hash ID
   * @param {Object} node - Node to generate ID for
   * @returns {string} Content hash ID
   * @private
   */
  _generateContentHash(node) {
    const content = [];

    if (this.config.includeType && node.type) {
      content.push(`type:${node.type}`);
    }

    if (this.config.includeName && node.name) {
      content.push(`name:${this._normalize(node.name)}`);
    }

    if (this.config.includeDimensions) {
      if (node.width !== undefined) content.push(`w:${Math.round(node.width)}`);
      if (node.height !== undefined) content.push(`h:${Math.round(node.height)}`);
    }

    if (this.config.includePosition) {
      if (node.x !== undefined) content.push(`x:${Math.round(node.x)}`);
      if (node.y !== undefined) content.push(`y:${Math.round(node.y)}`);
    }

    // Include relevant properties for stability
    if (node.componentId) {
      content.push(`comp:${node.componentId}`);
    }

    if (node.characters) {
      // For text nodes, include truncated text
      content.push(`text:${this._hash(node.characters, 8)}`);
    }

    return this._hash(content.join('|'));
  }

  /**
   * Generate path-based ID
   * @param {Object} node - Node to generate ID for
   * @param {string[]} ancestors - Ancestor names
   * @returns {string} Path-based ID
   * @private
   */
  _generatePathBased(node, ancestors = []) {
    const pathParts = [
      ...ancestors.map(a => this._normalize(a)),
      this._normalize(node.name || node.type || 'node')
    ];

    // Limit path depth
    const limitedPath = pathParts.slice(-4);
    const pathString = limitedPath.join('/');

    return this._hash(pathString);
  }

  /**
   * Generate semantic ID
   * @param {Object} node - Node to generate ID for
   * @returns {string} Semantic ID
   * @private
   */
  _generateSemantic(node) {
    const parts = [];

    // Type prefix
    const typePrefix = this._getTypePrefix(node.type);
    if (typePrefix) {
      parts.push(typePrefix);
    }

    // Normalized name
    const name = this._normalize(node.name || '');
    if (name) {
      parts.push(name.substring(0, 30)); // Limit length
    }

    // Add uniqueness suffix if needed
    const suffix = this._hash(`${node.id || ''}${Date.now()}`, 6);
    parts.push(suffix);

    return parts.join(this.config.separator);
  }

  /**
   * Get type prefix for semantic IDs
   * @param {string} type - Node type
   * @returns {string} Type prefix
   * @private
   */
  _getTypePrefix(type) {
    const prefixes = {
      FRAME: 'frm',
      GROUP: 'grp',
      COMPONENT: 'cmp',
      COMPONENT_SET: 'set',
      INSTANCE: 'ins',
      TEXT: 'txt',
      RECTANGLE: 'rec',
      ELLIPSE: 'ell',
      VECTOR: 'vec',
      IMAGE: 'img',
      LINE: 'lin',
      BOOLEAN_OPERATION: 'bool',
      SECTION: 'sec'
    };
    return prefixes[type] || 'elm';
  }

  /**
   * Generate composite ID using multiple strategies
   * @param {Object} node - Node to generate ID for
   * @param {string[]} ancestors - Ancestor names
   * @returns {string} Composite ID
   * @private
   */
  _generateComposite(node, ancestors = []) {
    const parts = [];

    // Type prefix
    parts.push(this._getTypePrefix(node.type));

    // Short name component
    const name = this._normalize(node.name || '');
    if (name) {
      parts.push(name.substring(0, 20));
    }

    // Content hash for uniqueness
    const contentHash = this._generateContentHash(node);
    parts.push(contentHash.substring(0, 8));

    return parts.join(this.config.separator);
  }

  /**
   * Generate v4.0.0 Registry-compatible canonical ID
   * Format: {source}-{type}-{name-slug}-{suffix}
   * @param {Object} node - Node to generate ID for
   * @param {Object} context - Context with source and type info
   * @returns {string} v4.0.0 canonical ID
   * @private
   */
  _generateRegistryV4(node, context = {}) {
    const {
      source = 'figma-plugin',
      type = 'component'
    } = context;

    // Validate source
    if (!V4_SOURCES.includes(source)) {
      throw new Error(`Invalid v4.0.0 source: ${source}. Must be one of: ${V4_SOURCES.join(', ')}`);
    }

    // Validate type
    if (!V4_TYPES.includes(type)) {
      throw new Error(`Invalid v4.0.0 type: ${type}. Must be one of: ${V4_TYPES.join(', ')}`);
    }

    // Generate slug from name
    const slug = this._slugifyV4(node.name || 'unnamed');

    // Extract suffix from node ID
    const suffix = this._extractIdSuffix(node.id);

    if (suffix) {
      return `${source}-${type}-${slug}-${suffix}`;
    }
    return `${source}-${type}-${slug}`;
  }

  /**
   * Convert name to URL-safe slug for v4.0.0 IDs
   * @param {string} name - Name to slugify
   * @returns {string} URL-safe slug
   * @private
   */
  _slugifyV4(name) {
    return name
      .toLowerCase()
      .replace(/[^a-z0-9\s-]/g, '')  // Remove special chars
      .replace(/\s+/g, '-')           // Spaces to hyphens
      .replace(/-+/g, '-')            // Collapse multiple hyphens
      .replace(/^-|-$/g, '')          // Trim hyphens
      .substring(0, 50)               // Limit length
      || 'unnamed';
  }

  /**
   * Extract ID suffix from Figma node ID
   * @param {string} nodeId - Figma node ID (e.g., "123:456" or "I123:456;789:012")
   * @returns {string} Extracted suffix
   * @private
   */
  _extractIdSuffix(nodeId) {
    if (!nodeId) return '';

    // Handle instance IDs: "I123:456;789:012" -> "123-456-789-012"
    // Handle regular IDs: "123:456" -> "123-456"
    return nodeId
      .replace(/^I/, '')              // Remove instance prefix
      .replace(/:/g, '-')             // Replace colons with hyphens
      .replace(/;/g, '-');            // Replace semicolons with hyphens
  }

  /**
   * Normalize Figma ID for stability
   * @param {string} figmaId - Original Figma ID
   * @returns {string} Normalized ID
   * @private
   */
  _normalizeFigmaId(figmaId) {
    if (!figmaId) return '';

    // Figma IDs can have format: "1:234" or "I1:234;5:678"
    // Normalize to consistent format
    return figmaId
      .replace(/:/g, '-')
      .replace(/;/g, '_')
      .toLowerCase();
  }

  /**
   * Generate canonical ID for a node
   * @param {Object} node - Node to generate ID for
   * @param {Object} context - Generation context
   * @returns {string} Canonical ID
   */
  generate(node, context = {}) {
    const { ancestors = [], strategy = this.config.strategy } = context;

    let id;

    switch (strategy) {
      case ID_STRATEGIES.CONTENT_HASH:
        id = this._generateContentHash(node);
        break;

      case ID_STRATEGIES.PATH_BASED:
        id = this._generatePathBased(node, ancestors);
        break;

      case ID_STRATEGIES.SEMANTIC:
        id = this._generateSemantic(node);
        break;

      case ID_STRATEGIES.FIGMA_STABLE:
        id = this._normalizeFigmaId(node.id);
        break;

      case ID_STRATEGIES.CUSTOM:
        if (this.customStrategies.has(context.customStrategy)) {
          id = this.customStrategies.get(context.customStrategy)(node, context);
        } else {
          id = this._generateComposite(node, ancestors);
        }
        break;

      case ID_STRATEGIES.REGISTRY_V4:
        id = this._generateRegistryV4(node, context);
        break;

      case ID_STRATEGIES.COMPOSITE:
      default:
        id = this._generateComposite(node, ancestors);
    }

    // Check for collision
    if (this.generatedIds.has(id)) {
      const existing = this.generatedIds.get(id);
      if (existing.originalId !== node.id) {
        this.collisionCount++;
        // Add disambiguation suffix
        id = `${id}${this.config.separator}${this.collisionCount}`;
      }
    }

    // Record generated ID
    this.generatedIds.set(id, {
      originalId: node.id,
      nodeName: node.name,
      nodeType: node.type,
      timestamp: Date.now()
    });

    return id;
  }

  /**
   * Register a custom ID generation strategy
   * @param {string} name - Strategy name
   * @param {Function} generator - Generator function (node, context) => id
   */
  registerStrategy(name, generator) {
    this.customStrategies.set(name, generator);
  }

  /**
   * Get generation statistics
   * @returns {Object} Statistics
   */
  getStats() {
    return {
      totalGenerated: this.generatedIds.size,
      collisions: this.collisionCount,
      customStrategies: this.customStrategies.size
    };
  }

  /**
   * Clear generated ID cache
   */
  clear() {
    this.generatedIds.clear();
    this.collisionCount = 0;
  }
}

// =============================================================================
// ID MAPPING STORE
// =============================================================================

/**
 * Persistent storage for ID mappings
 */
class IdMappingStore {
  /**
   * Create an ID mapping store
   * @param {Object} options - Store options
   */
  constructor(options = {}) {
    this.options = {
      storePath: options.storePath || '.design/id-mappings.json',
      autoSave: options.autoSave !== false,
      saveDebounce: options.saveDebounce || 1000,
      ...options
    };

    // In-memory mappings
    this.mappings = {
      figmaToCanonical: new Map(),
      canonicalToFigma: new Map(),
      history: []
    };

    this._saveTimeout = null;
    this._loaded = false;
  }

  /**
   * Load mappings from disk
   * @returns {boolean} True if loaded successfully
   */
  load() {
    try {
      const fullPath = path.resolve(this.options.storePath);

      if (!fs.existsSync(fullPath)) {
        this._loaded = true;
        return true;
      }

      const data = JSON.parse(fs.readFileSync(fullPath, 'utf8'));

      this.mappings.figmaToCanonical = new Map(Object.entries(data.figmaToCanonical || {}));
      this.mappings.canonicalToFigma = new Map(Object.entries(data.canonicalToFigma || {}));
      this.mappings.history = data.history || [];

      this._loaded = true;
      return true;
    } catch (error) {
      console.error('[IdMappingStore] Failed to load mappings:', error.message);
      this._loaded = true;
      return false;
    }
  }

  /**
   * Save mappings to disk
   * @returns {boolean} True if saved successfully
   */
  save() {
    try {
      const fullPath = path.resolve(this.options.storePath);
      const dir = path.dirname(fullPath);

      // Ensure directory exists
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }

      const data = {
        figmaToCanonical: Object.fromEntries(this.mappings.figmaToCanonical),
        canonicalToFigma: Object.fromEntries(this.mappings.canonicalToFigma),
        history: this.mappings.history.slice(-100), // Keep last 100 history entries
        savedAt: new Date().toISOString()
      };

      fs.writeFileSync(fullPath, JSON.stringify(data, null, 2));
      return true;
    } catch (error) {
      console.error('[IdMappingStore] Failed to save mappings:', error.message);
      return false;
    }
  }

  /**
   * Schedule a debounced save
   * @private
   */
  _scheduleSave() {
    if (!this.options.autoSave) return;

    if (this._saveTimeout) {
      clearTimeout(this._saveTimeout);
    }

    this._saveTimeout = setTimeout(() => {
      this.save();
    }, this.options.saveDebounce);
  }

  /**
   * Set a mapping
   * @param {string} figmaId - Original Figma ID
   * @param {string} canonicalId - Canonical ID
   * @param {Object} metadata - Optional metadata
   */
  set(figmaId, canonicalId, metadata = {}) {
    if (!this._loaded) {
      this.load();
    }

    // Update both directions
    this.mappings.figmaToCanonical.set(figmaId, {
      canonicalId,
      ...metadata,
      updatedAt: Date.now()
    });

    this.mappings.canonicalToFigma.set(canonicalId, {
      figmaId,
      ...metadata,
      updatedAt: Date.now()
    });

    // Record history
    this.mappings.history.push({
      action: 'set',
      figmaId,
      canonicalId,
      timestamp: Date.now()
    });

    this._scheduleSave();
  }

  /**
   * Get canonical ID for a Figma ID
   * @param {string} figmaId - Figma ID
   * @returns {Object|null} Mapping or null
   */
  getByFigmaId(figmaId) {
    if (!this._loaded) {
      this.load();
    }
    return this.mappings.figmaToCanonical.get(figmaId) || null;
  }

  /**
   * Get Figma ID for a canonical ID
   * @param {string} canonicalId - Canonical ID
   * @returns {Object|null} Mapping or null
   */
  getByCanonicalId(canonicalId) {
    if (!this._loaded) {
      this.load();
    }
    return this.mappings.canonicalToFigma.get(canonicalId) || null;
  }

  /**
   * Check if a Figma ID has a mapping
   * @param {string} figmaId - Figma ID
   * @returns {boolean} True if mapped
   */
  hasFigmaId(figmaId) {
    if (!this._loaded) {
      this.load();
    }
    return this.mappings.figmaToCanonical.has(figmaId);
  }

  /**
   * Check if a canonical ID exists
   * @param {string} canonicalId - Canonical ID
   * @returns {boolean} True if exists
   */
  hasCanonicalId(canonicalId) {
    if (!this._loaded) {
      this.load();
    }
    return this.mappings.canonicalToFigma.has(canonicalId);
  }

  /**
   * Remove a mapping by Figma ID
   * @param {string} figmaId - Figma ID
   * @returns {boolean} True if removed
   */
  removeByFigmaId(figmaId) {
    if (!this._loaded) {
      this.load();
    }

    const mapping = this.mappings.figmaToCanonical.get(figmaId);
    if (!mapping) return false;

    this.mappings.figmaToCanonical.delete(figmaId);
    this.mappings.canonicalToFigma.delete(mapping.canonicalId);

    this.mappings.history.push({
      action: 'remove',
      figmaId,
      canonicalId: mapping.canonicalId,
      timestamp: Date.now()
    });

    this._scheduleSave();
    return true;
  }

  /**
   * Get all mappings
   * @returns {Object} All mappings
   */
  getAll() {
    if (!this._loaded) {
      this.load();
    }

    return {
      figmaToCanonical: Object.fromEntries(this.mappings.figmaToCanonical),
      canonicalToFigma: Object.fromEntries(this.mappings.canonicalToFigma)
    };
  }

  /**
   * Get mapping statistics
   * @returns {Object} Statistics
   */
  getStats() {
    if (!this._loaded) {
      this.load();
    }

    return {
      totalMappings: this.mappings.figmaToCanonical.size,
      historyLength: this.mappings.history.length,
      loaded: this._loaded
    };
  }

  /**
   * Clear all mappings
   * @param {boolean} persist - Whether to persist the clear
   */
  clear(persist = false) {
    this.mappings.figmaToCanonical.clear();
    this.mappings.canonicalToFigma.clear();
    this.mappings.history = [];

    if (persist) {
      this.save();
    }
  }

  /**
   * Export mappings to object
   * @returns {Object} Exported data
   */
  export() {
    return {
      mappings: this.getAll(),
      stats: this.getStats(),
      exportedAt: new Date().toISOString()
    };
  }

  /**
   * Import mappings from object
   * @param {Object} data - Import data
   * @returns {number} Number of mappings imported
   */
  import(data) {
    if (!data.mappings) return 0;

    let count = 0;

    if (data.mappings.figmaToCanonical) {
      for (const [figmaId, mapping] of Object.entries(data.mappings.figmaToCanonical)) {
        this.set(figmaId, mapping.canonicalId, mapping);
        count++;
      }
    }

    return count;
  }
}

// =============================================================================
// ID RESOLVER
// =============================================================================

/**
 * Resolves IDs between different systems
 */
class IdResolver {
  /**
   * Create an ID resolver
   * @param {CanonicalIdGenerator} generator - ID generator
   * @param {IdMappingStore} store - Mapping store
   */
  constructor(generator, store) {
    this.generator = generator;
    this.store = store;
    this.resolveCache = new Map();
  }

  /**
   * Resolve or create canonical ID for a node
   * @param {Object} node - Node to resolve
   * @param {Object} context - Resolution context
   * @returns {Object} Resolution result
   */
  resolve(node, context = {}) {
    const { forceRegenerate = false, ancestors = [] } = context;

    // Check cache first
    if (!forceRegenerate && this.resolveCache.has(node.id)) {
      return this.resolveCache.get(node.id);
    }

    // Check store for existing mapping
    if (!forceRegenerate) {
      const existing = this.store.getByFigmaId(node.id);
      if (existing) {
        const result = {
          canonicalId: existing.canonicalId,
          figmaId: node.id,
          source: 'store',
          cached: false
        };
        this.resolveCache.set(node.id, result);
        return result;
      }
    }

    // Generate new canonical ID
    const canonicalId = this.generator.generate(node, { ancestors });

    // Store the mapping
    this.store.set(node.id, canonicalId, {
      nodeName: node.name,
      nodeType: node.type,
      strategy: this.generator.config.strategy
    });

    const result = {
      canonicalId,
      figmaId: node.id,
      source: 'generated',
      cached: false
    };

    this.resolveCache.set(node.id, result);
    return result;
  }

  /**
   * Resolve multiple nodes
   * @param {Object[]} nodes - Nodes to resolve
   * @param {Object} context - Resolution context
   * @returns {Object[]} Resolution results
   */
  resolveMany(nodes, context = {}) {
    return nodes.map((node, index) => {
      const nodeContext = {
        ...context,
        index
      };
      return this.resolve(node, nodeContext);
    });
  }

  /**
   * Reverse resolve: find Figma ID from canonical ID
   * @param {string} canonicalId - Canonical ID
   * @returns {Object|null} Resolution result or null
   */
  reverseResolve(canonicalId) {
    const mapping = this.store.getByCanonicalId(canonicalId);
    if (!mapping) return null;

    return {
      canonicalId,
      figmaId: mapping.figmaId,
      source: 'store'
    };
  }

  /**
   * Validate that a canonical ID still maps to the expected node
   * @param {string} canonicalId - Canonical ID to validate
   * @param {Object} node - Node to validate against
   * @returns {Object} Validation result
   */
  validate(canonicalId, node) {
    const mapping = this.store.getByCanonicalId(canonicalId);

    if (!mapping) {
      return {
        valid: false,
        reason: 'Mapping not found',
        canonicalId
      };
    }

    if (mapping.figmaId !== node.id) {
      return {
        valid: false,
        reason: 'Figma ID mismatch',
        expected: mapping.figmaId,
        actual: node.id,
        canonicalId
      };
    }

    // Regenerate to check if content changed significantly
    const regenerated = this.generator.generate(node, { strategy: ID_STRATEGIES.CONTENT_HASH });
    const original = this.generator._generateContentHash({ id: mapping.figmaId });

    const contentMatch = regenerated === original;

    return {
      valid: true,
      contentMatch,
      canonicalId,
      figmaId: node.id,
      warning: contentMatch ? null : 'Content has changed significantly'
    };
  }

  /**
   * Clear resolution cache
   */
  clearCache() {
    this.resolveCache.clear();
  }

  /**
   * Get resolver statistics
   * @returns {Object} Statistics
   */
  getStats() {
    return {
      cacheSize: this.resolveCache.size,
      generatorStats: this.generator.getStats(),
      storeStats: this.store.getStats()
    };
  }
}

// =============================================================================
// CONVENIENCE FUNCTIONS
// =============================================================================

/**
 * Create a complete ID system
 * @param {Object} options - System options
 * @returns {Object} ID system with generator, store, and resolver
 */
function createIdSystem(options = {}) {
  const generator = new CanonicalIdGenerator(options.generator);
  const store = new IdMappingStore(options.store);
  const resolver = new IdResolver(generator, store);

  return {
    generator,
    store,
    resolver,
    // Convenience methods
    resolve: (node, context) => resolver.resolve(node, context),
    generate: (node, context) => generator.generate(node, context),
    getCanonicalId: (figmaId) => store.getByFigmaId(figmaId)?.canonicalId,
    getFigmaId: (canonicalId) => store.getByCanonicalId(canonicalId)?.figmaId
  };
}

/**
 * Quick ID generation without persistence
 * @param {Object} node - Node to generate ID for
 * @param {Object} options - Generation options
 * @returns {string} Canonical ID
 */
function generateCanonicalId(node, options = {}) {
  const generator = new CanonicalIdGenerator(options);
  return generator.generate(node, options);
}

/**
 * Create a deterministic hash from any input
 * @param {*} input - Input to hash
 * @param {number} length - Hash length
 * @returns {string} Hash string
 */
function createHash(input, length = 12) {
  const stringified = typeof input === 'string' ? input : JSON.stringify(input);
  return crypto
    .createHash('sha256')
    .update(stringified)
    .digest('hex')
    .substring(0, length);
}

/**
 * Check if two canonical IDs refer to the same content
 * @param {string} id1 - First ID
 * @param {string} id2 - Second ID
 * @returns {boolean} True if likely same content
 */
function areIdsSimilar(id1, id2) {
  if (id1 === id2) return true;

  // Extract hash portions (last segment after separator)
  const hash1 = id1.split('-').pop();
  const hash2 = id2.split('-').pop();

  return hash1 === hash2;
}

// =============================================================================
// v4.0.0 REGISTRY INTEGRATION FUNCTIONS
// =============================================================================

/**
 * Generate a v4.0.0 canonical ID without using a generator instance
 * Format: {source}-{type}-{name-slug}-{suffix}
 * @param {string} source - Source system (figma-plugin, shadcn-mcp, nlp-prompt, manual, migration)
 * @param {string} type - Entry type (component, token, layout)
 * @param {string} name - Name to slugify
 * @param {string} nodeId - Optional node ID for suffix
 * @returns {string} v4.0.0 canonical ID
 */
function generateV4CanonicalId(source, type, name, nodeId = null) {
  // Validate source
  if (!V4_SOURCES.includes(source)) {
    throw new Error(`Invalid v4.0.0 source: ${source}. Must be one of: ${V4_SOURCES.join(', ')}`);
  }

  // Validate type
  if (!V4_TYPES.includes(type)) {
    throw new Error(`Invalid v4.0.0 type: ${type}. Must be one of: ${V4_TYPES.join(', ')}`);
  }

  // Generate slug from name
  const slug = slugifyForV4(name || 'unnamed');

  // Extract suffix from node ID
  const suffix = extractV4IdSuffix(nodeId);

  if (suffix) {
    return `${source}-${type}-${slug}-${suffix}`;
  }
  return `${source}-${type}-${slug}`;
}

/**
 * Convert name to URL-safe slug for v4.0.0 IDs
 * @param {string} name - Name to slugify
 * @returns {string} URL-safe slug
 */
function slugifyForV4(name) {
  return (name || '')
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')  // Remove special chars
    .replace(/\s+/g, '-')           // Spaces to hyphens
    .replace(/-+/g, '-')            // Collapse multiple hyphens
    .replace(/^-|-$/g, '')          // Trim hyphens
    .substring(0, 50)               // Limit length
    || 'unnamed';
}

/**
 * Extract ID suffix from Figma node ID for v4.0.0 format
 * @param {string} nodeId - Figma node ID (e.g., "123:456" or "I123:456;789:012")
 * @returns {string} Extracted suffix
 */
function extractV4IdSuffix(nodeId) {
  if (!nodeId) return '';

  // Handle instance IDs: "I123:456;789:012" -> "123-456-789-012"
  // Handle regular IDs: "123:456" -> "123-456"
  return nodeId
    .replace(/^I/, '')              // Remove instance prefix
    .replace(/:/g, '-')             // Replace colons with hyphens
    .replace(/;/g, '-');            // Replace semicolons with hyphens
}

/**
 * Parse a v4.0.0 canonical ID into its components
 * @param {string} canonicalId - v4.0.0 canonical ID
 * @returns {Object|null} Parsed components or null if invalid
 */
function parseV4CanonicalId(canonicalId) {
  if (!canonicalId || typeof canonicalId !== 'string') {
    return null;
  }

  // v4.0.0 format: {source}-{type}-{name-slug}-{suffix}
  // But name-slug can contain hyphens, so we need to be careful

  // Try to match known sources first
  for (const source of V4_SOURCES) {
    if (canonicalId.startsWith(source + '-')) {
      const rest = canonicalId.substring(source.length + 1);

      // Try to match known types
      for (const type of V4_TYPES) {
        if (rest.startsWith(type + '-')) {
          const slugAndSuffix = rest.substring(type.length + 1);

          // The suffix is typically at the end and looks like: xxx-yyy or xxx-yyy-zzz-www
          // We need to find where the slug ends and suffix begins
          // Suffix pattern: numbers with hyphens (e.g., "123-456" or "123-456-789-012")
          const suffixMatch = slugAndSuffix.match(/-(\d+(?:-\d+)+)$/);

          let slug, suffix;
          if (suffixMatch) {
            suffix = suffixMatch[1];
            slug = slugAndSuffix.substring(0, slugAndSuffix.length - suffix.length - 1);
          } else {
            slug = slugAndSuffix;
            suffix = null;
          }

          return {
            source,
            type,
            slug,
            suffix,
            isV4: true
          };
        }
      }
    }
  }

  // Not a v4.0.0 format ID
  return null;
}

/**
 * Check if a canonical ID is in v4.0.0 format
 * @param {string} canonicalId - ID to check
 * @returns {boolean} True if v4.0.0 format
 */
function isV4CanonicalId(canonicalId) {
  return parseV4CanonicalId(canonicalId) !== null;
}

/**
 * Generate a v4.0.0 canonical ID from a Figma node
 * @param {Object} node - Figma node with id, name, type properties
 * @param {string} entryType - Entry type (component, token, layout)
 * @param {string} source - Source system (default: figma-plugin)
 * @returns {string} v4.0.0 canonical ID
 */
function generateV4IdFromNode(node, entryType = 'component', source = 'figma-plugin') {
  return generateV4CanonicalId(source, entryType, node.name, node.id);
}

/**
 * Resolve a canonical ID using the RegistryManager
 * Returns both the entry and its metadata if found
 * @param {string} designRoot - Path to .design directory
 * @param {string} canonicalId - ID to resolve
 * @returns {Promise<Object|null>} Resolved entry or null
 */
async function resolveV4Id(designRoot, canonicalId) {
  try {
    const { getRegistryManager } = getRegistryManagerModule();
    const manager = await getRegistryManager(designRoot);
    return await manager.findById(canonicalId);
  } catch (error) {
    console.error('[canonical-id] Failed to resolve v4 ID:', error.message);
    return null;
  }
}

/**
 * Resolve a Figma node ID to canonical ID using the RegistryManager
 * @param {string} designRoot - Path to .design directory
 * @param {string} nodeId - Figma node ID
 * @param {string} registryType - Registry type (components, tokens, layouts)
 * @returns {Promise<string|null>} Canonical ID or null
 */
async function resolveNodeIdToCanonical(designRoot, nodeId, registryType = 'components') {
  try {
    const { getRegistryManager } = getRegistryManagerModule();
    const manager = await getRegistryManager(designRoot);
    const entry = await manager.findByNodeId(nodeId, registryType);
    return entry ? entry.id : null;
  } catch (error) {
    console.error('[canonical-id] Failed to resolve node ID:', error.message);
    return null;
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

module.exports = {
  // Classes
  CanonicalIdGenerator,
  IdMappingStore,
  IdResolver,
  // Constants
  ID_STRATEGIES,
  HASH_ALGORITHMS,
  DEFAULT_CONFIG,
  V4_SOURCES,
  V4_TYPES,
  // Factory functions
  createIdSystem,
  // Utility functions (legacy)
  generateCanonicalId,
  createHash,
  areIdsSimilar,
  // v4.0.0 Registry Integration (preferred for new code)
  generateV4CanonicalId,
  slugifyForV4,
  extractV4IdSuffix,
  parseV4CanonicalId,
  isV4CanonicalId,
  generateV4IdFromNode,
  resolveV4Id,
  resolveNodeIdToCanonical
};
