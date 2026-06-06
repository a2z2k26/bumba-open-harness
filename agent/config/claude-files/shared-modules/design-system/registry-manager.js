/**
 * RegistryManager - Unified coordinator for all Design Bridge registries
 *
 * Provides:
 * - Centralized registry access (tokens, components, layouts)
 * - ID index for O(1) lookups
 * - Dependency graph for impact analysis
 * - Source mapping for Figma ID <-> Canonical ID resolution
 *
 * Schema Version: 4.0.0
 *
 * @module registry-manager
 */

const fs = require('fs').promises;
const path = require('path');
const EventEmitter = require('events');

// Constants
const INDEX_SCHEMA_VERSION = '4.0.0';
const INDEX_VERSION = '1.0.0';
const REGISTRY_TYPES = ['tokens', 'components', 'layouts'];
const ID_SOURCES = ['figma-plugin', 'figma-mcp', 'manual', 'shadcn', 'nlp'];
const ID_TYPES = ['component', 'token', 'layout'];

/**
 * RegistryManager - Unified coordinator for all Design Bridge registries
 *
 * @class RegistryManager
 * @extends EventEmitter
 *
 * @example
 * const manager = new RegistryManager('/path/to/project/.design');
 * await manager.initialize();
 *
 * // Add a component
 * const id = await manager.addEntry('components', {
 *   name: 'Button',
 *   source: { type: 'figma-plugin', nodeId: '123:456' }
 * });
 *
 * // Find by ID
 * const component = await manager.findById(id);
 *
 * // Find by Figma node ID
 * const entry = await manager.findByNodeId('123:456');
 */
class RegistryManager extends EventEmitter {
  /**
   * Creates a new RegistryManager instance
   *
   * @param {string} designRoot - Path to the .design directory
   */
  constructor(designRoot) {
    super();

    this.designRoot = designRoot;
    this.indexPath = path.join(designRoot, 'registry-index.json');
    this.registriesPath = path.join(designRoot, 'registries');

    // In-memory state (loaded on initialize)
    this.index = null;
    this.registries = {
      tokens: null,
      components: null,
      layouts: null
    };

    this._initialized = false;
  }

  // ==========================================================================
  // INITIALIZATION
  // ==========================================================================

  /**
   * Initializes the registry manager
   * Creates directories and loads/creates registries
   *
   * @returns {Promise<void>}
   */
  async initialize() {
    if (this._initialized) return;

    // Ensure directories exist
    await this.ensureDirectories();

    // Load or create the index
    this.index = await this.loadOrCreateIndex();

    this._initialized = true;
    this.emit('initialized');
  }

  /**
   * Ensures required directories exist
   *
   * @returns {Promise<void>}
   */
  async ensureDirectories() {
    // Create .design directory if it doesn't exist
    await fs.mkdir(this.designRoot, { recursive: true });

    // Create registries subdirectory
    await fs.mkdir(this.registriesPath, { recursive: true });
  }

  // ==========================================================================
  // INDEX OPERATIONS (Sprint 1.2)
  // ==========================================================================

  /**
   * Creates an empty index structure with v4.0.0 schema
   *
   * @returns {Object} Empty index structure
   */
  createEmptyIndex() {
    return {
      version: INDEX_VERSION,
      schemaVersion: INDEX_SCHEMA_VERSION,
      lastUpdated: new Date().toISOString(),
      registries: {
        tokens: { path: '.design/registries/tokens.json', count: 0, lastModified: null },
        components: { path: '.design/registries/components.json', count: 0, lastModified: null },
        layouts: { path: '.design/registries/layouts.json', count: 0, lastModified: null }
      },
      idIndex: {},        // canonicalId -> { type, registryPath }
      sourceMapping: {},  // nodeId/styleId -> canonicalId
      dependencyGraph: {} // id -> { usedBy: { components: [], layouts: [], tokens: [] } }
    };
  }

  /**
   * Loads existing index or creates a new one
   *
   * @returns {Promise<Object>} Index object
   */
  async loadOrCreateIndex() {
    const exists = await this.fileExists(this.indexPath);

    if (exists) {
      const data = await this.readJSON(this.indexPath);
      // Validate and upgrade if needed
      return this.upgradeIndexIfNeeded(data);
    }

    const emptyIndex = this.createEmptyIndex();
    await this.saveIndex(emptyIndex);
    return emptyIndex;
  }

  /**
   * Saves the index to disk atomically
   *
   * @param {Object} [indexData] - Index data (uses this.index if not provided)
   * @returns {Promise<void>}
   */
  async saveIndex(indexData = null) {
    const data = indexData || this.index;
    data.lastUpdated = new Date().toISOString();
    await this.writeJSON(this.indexPath, data);
  }

  /**
   * Upgrades index schema if needed
   *
   * @param {Object} data - Index data
   * @returns {Object} Upgraded index
   */
  upgradeIndexIfNeeded(data) {
    // If already at current version, return as-is
    if (data.schemaVersion === INDEX_SCHEMA_VERSION) {
      return data;
    }

    // Upgrade from older versions
    const upgraded = { ...this.createEmptyIndex() };

    // Preserve existing data where possible
    if (data.idIndex) upgraded.idIndex = data.idIndex;
    if (data.sourceMapping) upgraded.sourceMapping = data.sourceMapping;
    if (data.dependencyGraph) upgraded.dependencyGraph = data.dependencyGraph;
    if (data.registries) {
      for (const type of REGISTRY_TYPES) {
        if (data.registries[type]) {
          upgraded.registries[type] = {
            ...upgraded.registries[type],
            ...data.registries[type]
          };
        }
      }
    }

    upgraded.schemaVersion = INDEX_SCHEMA_VERSION;
    return upgraded;
  }

  // ==========================================================================
  // ID GENERATION (Sprint 1.3)
  // ==========================================================================

  /**
   * Generates a canonical ID in the format: {source}-{type}-{name-slug}-{unique-suffix}
   *
   * @param {string} source - Source type (figma-plugin, figma-mcp, manual, shadcn, nlp)
   * @param {string} type - Entry type (component, token, layout)
   * @param {string} name - Human-readable name
   * @param {string} [nodeId] - Optional Figma node ID or style ID for uniqueness
   * @returns {string} Canonical ID
   *
   * @example
   * generateCanonicalId('figma-plugin', 'component', 'Button Primary', '123:456')
   * // Returns: 'figma-plugin-component-button-primary-123-456'
   */
  generateCanonicalId(source, type, name, nodeId = null) {
    // Validate source
    if (!ID_SOURCES.includes(source)) {
      throw new Error(`Invalid source: ${source}. Must be one of: ${ID_SOURCES.join(', ')}`);
    }

    // Validate type
    if (!ID_TYPES.includes(type)) {
      throw new Error(`Invalid type: ${type}. Must be one of: ${ID_TYPES.join(', ')}`);
    }

    const slug = this.slugify(name);
    const suffix = this.extractIdSuffix(nodeId);

    if (suffix) {
      return `${source}-${type}-${slug}-${suffix}`;
    }

    // If no nodeId, generate a random suffix for uniqueness
    const randomSuffix = Math.random().toString(36).substring(2, 8);
    return `${source}-${type}-${slug}-${randomSuffix}`;
  }

  /**
   * Converts a name to a URL-safe slug
   *
   * @param {string} name - Name to slugify
   * @returns {string} Slugified name (lowercase, hyphens, max 30 chars)
   */
  slugify(name) {
    if (!name) return 'unnamed';

    return name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')  // Replace non-alphanumeric with hyphens
      .replace(/^-+|-+$/g, '')       // Remove leading/trailing hyphens
      .substring(0, 30);              // Max 30 characters
  }

  /**
   * Extracts a unique suffix from a Figma node ID or style ID
   *
   * @param {string} nodeId - Figma node ID (e.g., "123:456") or style ID (e.g., "S:abc123...")
   * @returns {string|null} Extracted suffix or null
   */
  extractIdSuffix(nodeId) {
    if (!nodeId) return null;

    // Handle style IDs like "S:774a6223930fe22b2d4644eb0630dc965e65da59,"
    if (nodeId.startsWith('S:')) {
      // Extract first 7 chars after S:
      return nodeId.substring(2, 9);
    }

    // Handle node IDs like "123:456" -> "123-456"
    if (nodeId.includes(':')) {
      return nodeId.replace(/:/g, '-');
    }

    // Handle node IDs like "123-456" (already formatted)
    if (nodeId.includes('-')) {
      return nodeId;
    }

    // Return as-is if it's a simple ID
    return nodeId.substring(0, 12);
  }

  // ==========================================================================
  // REGISTRY CRUD (Sprint 1.4)
  // ==========================================================================

  /**
   * Creates an empty registry structure with v4.0.0 schema
   *
   * @param {string} type - Registry type (tokens, components, layouts)
   * @returns {Object} Empty registry structure
   */
  createEmptyRegistry(type) {
    if (!REGISTRY_TYPES.includes(type)) {
      throw new Error(`Invalid registry type: ${type}. Must be one of: ${REGISTRY_TYPES.join(', ')}`);
    }

    return {
      version: INDEX_SCHEMA_VERSION,
      type: type,
      metadata: {
        schemaVersion: INDEX_SCHEMA_VERSION,
        createdAt: new Date().toISOString(),
        lastUpdated: new Date().toISOString(),
        entryCount: 0
      },
      entries: {}
    };
  }

  /**
   * Gets the file path for a registry type
   *
   * @param {string} type - Registry type
   * @returns {string} File path
   */
  getRegistryPath(type) {
    if (!REGISTRY_TYPES.includes(type)) {
      throw new Error(`Invalid registry type: ${type}`);
    }
    return path.join(this.registriesPath, `${type}.json`);
  }

  /**
   * Loads a registry from disk (with caching)
   *
   * @param {string} type - Registry type
   * @param {boolean} [forceReload=false] - Force reload from disk
   * @returns {Promise<Object>} Registry object
   */
  async loadRegistry(type, forceReload = false) {
    if (!REGISTRY_TYPES.includes(type)) {
      throw new Error(`Invalid registry type: ${type}`);
    }

    // Return cached if available and not forcing reload
    if (!forceReload && this.registries[type]) {
      return this.registries[type];
    }

    const registryPath = this.getRegistryPath(type);
    const exists = await this.fileExists(registryPath);

    if (exists) {
      this.registries[type] = await this.readJSON(registryPath);
    } else {
      this.registries[type] = this.createEmptyRegistry(type);
      await this.saveRegistry(type);
    }

    return this.registries[type];
  }

  /**
   * Saves a registry to disk atomically
   *
   * @param {string} type - Registry type
   * @returns {Promise<void>}
   */
  async saveRegistry(type) {
    if (!REGISTRY_TYPES.includes(type)) {
      throw new Error(`Invalid registry type: ${type}`);
    }

    const registry = this.registries[type];
    if (!registry) {
      throw new Error(`Registry ${type} not loaded`);
    }

    // Update metadata
    registry.metadata.lastUpdated = new Date().toISOString();
    registry.metadata.entryCount = Object.keys(registry.entries).length;

    // Save registry file
    const registryPath = this.getRegistryPath(type);
    await this.writeJSON(registryPath, registry);

    // Update index
    if (this.index) {
      this.index.registries[type].count = registry.metadata.entryCount;
      this.index.registries[type].lastModified = registry.metadata.lastUpdated;
      await this.saveIndex();
    }
  }

  // ==========================================================================
  // ENTRY OPERATIONS (Sprint 1.5)
  // ==========================================================================

  /**
   * Creates the base entry structure for a new entry
   *
   * @param {string} type - Entry type (component, token, layout)
   * @returns {Object} Base entry structure
   */
  createBaseEntry(type) {
    const now = new Date().toISOString();

    return {
      id: null,
      name: '',
      displayName: '',
      category: null,
      source: {
        type: null,
        fileKey: null,
        nodeId: null,
        styleId: null,
        extractedAt: now,
        rawDataPath: null
      },
      transformation: {
        state: 'raw', // raw, transforming, transformed, error
        framework: null,
        codePath: null,
        storyPath: null,
        codeHash: null,
        transformedAt: null,
        version: 1
      },
      dependencies: {
        tokens: [],
        components: []
      },
      sync: {
        lastFigmaSync: now,
        figmaModifiedAt: null,
        localModifiedAt: null,
        userModified: false,
        syncCount: 1
      }
    };
  }

  /**
   * Adds a new entry to a registry
   *
   * @param {string} registryType - Registry type (tokens, components, layouts)
   * @param {Object} entryData - Entry data
   * @returns {Promise<string>} Canonical ID of the added entry
   *
   * @emits entry-added
   */
  async addEntry(registryType, entryData) {
    await this.ensureInitialized();

    // Map registry type to ID type
    const idTypeMap = { tokens: 'token', components: 'component', layouts: 'layout' };
    const idType = idTypeMap[registryType];

    // Load registry
    const registry = await this.loadRegistry(registryType);

    // Generate or use provided ID
    let canonicalId = entryData.id;
    if (!canonicalId) {
      const sourceType = entryData.source?.type || 'manual';
      const nodeId = entryData.source?.nodeId || entryData.source?.styleId;
      canonicalId = this.generateCanonicalId(sourceType, idType, entryData.name, nodeId);
    }

    // Create entry with base structure merged with provided data
    const entry = this.mergeDeep(this.createBaseEntry(idType), entryData);
    entry.id = canonicalId;
    entry.displayName = entry.displayName || entry.name;

    // Add to registry
    registry.entries[canonicalId] = entry;

    // Update ID index
    this.index.idIndex[canonicalId] = { type: registryType, registryPath: this.getRegistryPath(registryType) };

    // Update source mapping (for nodeId and styleId)
    if (entry.source?.nodeId) {
      this.index.sourceMapping[entry.source.nodeId] = canonicalId;
    }
    if (entry.source?.styleId) {
      this.index.sourceMapping[entry.source.styleId] = canonicalId;
    }

    // Save changes
    await this.saveRegistry(registryType);

    // Emit event
    this.emit('entry-added', { type: registryType, id: canonicalId, entry });

    return canonicalId;
  }

  /**
   * Updates an existing entry (merges with existing data)
   *
   * @param {string} registryType - Registry type
   * @param {string} id - Canonical ID
   * @param {Object} updates - Partial entry data to merge
   * @returns {Promise<void>}
   *
   * @emits entry-updated
   */
  async updateEntry(registryType, id, updates) {
    await this.ensureInitialized();

    const registry = await this.loadRegistry(registryType);

    if (!registry.entries[id]) {
      throw new Error(`Entry not found: ${id} in ${registryType}`);
    }

    // Merge updates into existing entry
    registry.entries[id] = this.mergeDeep(registry.entries[id], updates);

    // Update source mapping if nodeId/styleId changed
    if (updates.source?.nodeId) {
      this.index.sourceMapping[updates.source.nodeId] = id;
    }
    if (updates.source?.styleId) {
      this.index.sourceMapping[updates.source.styleId] = id;
    }

    // Save changes
    await this.saveRegistry(registryType);

    // Emit event
    this.emit('entry-updated', { type: registryType, id, updates });
  }

  /**
   * Removes an entry from a registry
   *
   * @param {string} registryType - Registry type
   * @param {string} id - Canonical ID
   * @returns {Promise<boolean>} True if entry was removed
   *
   * @emits entry-removed
   */
  async removeEntry(registryType, id) {
    await this.ensureInitialized();

    const registry = await this.loadRegistry(registryType);

    if (!registry.entries[id]) {
      return false;
    }

    const entry = registry.entries[id];

    // Clean up source mapping
    if (entry.source?.nodeId && this.index.sourceMapping[entry.source.nodeId] === id) {
      delete this.index.sourceMapping[entry.source.nodeId];
    }
    if (entry.source?.styleId && this.index.sourceMapping[entry.source.styleId] === id) {
      delete this.index.sourceMapping[entry.source.styleId];
    }

    // Clean up ID index
    delete this.index.idIndex[id];

    // Clean up dependency graph
    this.clearDependenciesFromGraph(id);

    // Remove from registry
    delete registry.entries[id];

    // Save changes
    await this.saveRegistry(registryType);

    // Emit event
    this.emit('entry-removed', { type: registryType, id });

    return true;
  }

  // ==========================================================================
  // QUERY OPERATIONS (Sprint 1.6)
  // ==========================================================================

  /**
   * Finds an entry by its canonical ID (O(1) via idIndex)
   *
   * @param {string} id - Canonical ID
   * @returns {Promise<Object|null>} Entry or null if not found
   */
  async findById(id) {
    await this.ensureInitialized();

    const indexEntry = this.index.idIndex[id];
    if (!indexEntry) return null;

    const registry = await this.loadRegistry(indexEntry.type);
    return registry.entries[id] || null;
  }

  /**
   * Finds an entry by Figma node ID (O(1) via sourceMapping)
   *
   * @param {string} nodeId - Figma node ID
   * @returns {Promise<Object|null>} Entry or null if not found
   */
  async findByNodeId(nodeId) {
    await this.ensureInitialized();

    const canonicalId = this.index.sourceMapping[nodeId];
    if (!canonicalId) return null;

    return this.findById(canonicalId);
  }

  /**
   * Finds an entry by Figma style ID (O(1) via sourceMapping)
   *
   * @param {string} styleId - Figma style ID
   * @returns {Promise<Object|null>} Entry or null if not found
   */
  async findByStyleId(styleId) {
    await this.ensureInitialized();

    const canonicalId = this.index.sourceMapping[styleId];
    if (!canonicalId) return null;

    return this.findById(canonicalId);
  }

  /**
   * Finds entries by name (partial match, case-insensitive)
   *
   * @param {string} name - Name to search for
   * @param {string} [registryType] - Optional registry type to filter
   * @param {Object} [options] - Pagination options
   * @param {number} [options.offset=0] - Start offset
   * @param {number} [options.limit=100] - Max results
   * @returns {Promise<Object[]>} Matching entries
   */
  async findByName(name, registryType = null, options = {}) {
    await this.ensureInitialized();

    const { offset = 0, limit = 100 } = options;
    const searchName = name.toLowerCase();
    const results = [];

    const typesToSearch = registryType ? [registryType] : REGISTRY_TYPES;

    for (const type of typesToSearch) {
      const registry = await this.loadRegistry(type);

      for (const entry of Object.values(registry.entries)) {
        const entryName = (entry.name || '').toLowerCase();
        const displayName = (entry.displayName || '').toLowerCase();

        if (entryName.includes(searchName) || displayName.includes(searchName)) {
          results.push(entry);
        }
      }
    }

    return results.slice(offset, offset + limit);
  }

  /**
   * Finds entries by category
   *
   * @param {string} category - Category to filter by
   * @param {string} [registryType] - Optional registry type to filter
   * @param {Object} [options] - Pagination options
   * @returns {Promise<Object[]>} Matching entries
   */
  async findByCategory(category, registryType = null, options = {}) {
    await this.ensureInitialized();

    const { offset = 0, limit = 100 } = options;
    const results = [];

    const typesToSearch = registryType ? [registryType] : REGISTRY_TYPES;

    for (const type of typesToSearch) {
      const registry = await this.loadRegistry(type);

      for (const entry of Object.values(registry.entries)) {
        if (entry.category === category) {
          results.push(entry);
        }
      }
    }

    return results.slice(offset, offset + limit);
  }

  /**
   * Finds entries by source type
   *
   * @param {string} sourceType - Source type (figma-plugin, shadcn, etc.)
   * @param {string} [registryType] - Optional registry type to filter
   * @param {Object} [options] - Pagination options
   * @returns {Promise<Object[]>} Matching entries
   */
  async findBySource(sourceType, registryType = null, options = {}) {
    await this.ensureInitialized();

    const { offset = 0, limit = 100 } = options;
    const results = [];

    const typesToSearch = registryType ? [registryType] : REGISTRY_TYPES;

    for (const type of typesToSearch) {
      const registry = await this.loadRegistry(type);

      for (const entry of Object.values(registry.entries)) {
        if (entry.source?.type === sourceType) {
          results.push(entry);
        }
      }
    }

    return results.slice(offset, offset + limit);
  }

  /**
   * Gets all entries from a registry
   *
   * @param {string} registryType - Registry type
   * @param {Object} [options] - Pagination options
   * @returns {Promise<Object[]>} All entries
   */
  async getAllEntries(registryType, options = {}) {
    await this.ensureInitialized();

    const { offset = 0, limit = 1000 } = options;
    const registry = await this.loadRegistry(registryType);

    return Object.values(registry.entries).slice(offset, offset + limit);
  }

  // ==========================================================================
  // DEPENDENCY GRAPH (Sprint 1.7)
  // ==========================================================================

  /**
   * Updates dependencies for an entry and maintains bidirectional graph
   *
   * @param {string} id - Canonical ID of the entry
   * @param {Object} dependencies - Dependencies object { tokens: [], components: [] }
   * @returns {Promise<void>}
   */
  async updateDependencies(id, dependencies) {
    await this.ensureInitialized();

    // Get entry to update its dependencies field
    const entry = await this.findById(id);
    if (!entry) {
      throw new Error(`Entry not found: ${id}`);
    }

    // Clear old dependencies from graph first
    this.clearDependenciesFromGraph(id);

    // Add new dependencies to graph
    const allDeps = [
      ...(dependencies.tokens || []),
      ...(dependencies.components || [])
    ];

    for (const depId of allDeps) {
      if (!this.index.dependencyGraph[depId]) {
        this.index.dependencyGraph[depId] = {
          usedBy: { components: [], layouts: [], tokens: [] }
        };
      }

      // Determine which category the current entry belongs to
      const indexEntry = this.index.idIndex[id];
      if (indexEntry) {
        const category = indexEntry.type; // tokens, components, or layouts
        if (!this.index.dependencyGraph[depId].usedBy[category].includes(id)) {
          this.index.dependencyGraph[depId].usedBy[category].push(id);
        }
      }
    }

    // Update the entry's dependencies field
    const indexEntry = this.index.idIndex[id];
    if (indexEntry) {
      const registry = await this.loadRegistry(indexEntry.type);
      if (registry.entries[id]) {
        registry.entries[id].dependencies = {
          tokens: dependencies.tokens || [],
          components: dependencies.components || []
        };
        await this.saveRegistry(indexEntry.type);
      }
    }

    // Save index with updated graph
    await this.saveIndex();
  }

  /**
   * Removes an entry from all dependency graph references
   *
   * @param {string} id - Canonical ID to remove from graph
   */
  clearDependenciesFromGraph(id) {
    // Remove from all usedBy arrays
    for (const depId of Object.keys(this.index.dependencyGraph)) {
      const node = this.index.dependencyGraph[depId];

      for (const category of ['components', 'layouts', 'tokens']) {
        const idx = node.usedBy[category].indexOf(id);
        if (idx !== -1) {
          node.usedBy[category].splice(idx, 1);
        }
      }

      // Clean up empty nodes
      const totalUsedBy = node.usedBy.components.length +
                          node.usedBy.layouts.length +
                          node.usedBy.tokens.length;
      if (totalUsedBy === 0) {
        delete this.index.dependencyGraph[depId];
      }
    }

    // Also remove this id's own entry in the graph if it exists
    delete this.index.dependencyGraph[id];
  }

  /**
   * Finds all entries that depend on a given entry ("what uses this?")
   *
   * @param {string} id - Canonical ID
   * @returns {Promise<Object>} Dependents object { components: [], layouts: [], tokens: [] }
   */
  async findDependents(id) {
    await this.ensureInitialized();

    const graphNode = this.index.dependencyGraph[id];

    if (!graphNode) {
      return { components: [], layouts: [], tokens: [] };
    }

    return { ...graphNode.usedBy };
  }

  /**
   * Finds all entries that a given entry depends on ("what does this use?")
   *
   * @param {string} id - Canonical ID
   * @returns {Promise<Object>} Dependencies object { tokens: [], components: [] }
   */
  async findDependencies(id) {
    await this.ensureInitialized();

    const entry = await this.findById(id);

    if (!entry || !entry.dependencies) {
      return { tokens: [], components: [] };
    }

    return { ...entry.dependencies };
  }

  /**
   * Rebuilds the entire dependency graph from entry data
   *
   * @returns {Promise<void>}
   */
  async rebuildDependencyGraph() {
    await this.ensureInitialized();

    // Clear existing graph
    this.index.dependencyGraph = {};

    // Rebuild from all entries
    for (const type of REGISTRY_TYPES) {
      const registry = await this.loadRegistry(type);

      for (const entry of Object.values(registry.entries)) {
        if (entry.dependencies) {
          const allDeps = [
            ...(entry.dependencies.tokens || []),
            ...(entry.dependencies.components || [])
          ];

          for (const depId of allDeps) {
            if (!this.index.dependencyGraph[depId]) {
              this.index.dependencyGraph[depId] = {
                usedBy: { components: [], layouts: [], tokens: [] }
              };
            }

            if (!this.index.dependencyGraph[depId].usedBy[type].includes(entry.id)) {
              this.index.dependencyGraph[depId].usedBy[type].push(entry.id);
            }
          }
        }
      }
    }

    // Check for circular dependencies (warning only)
    const circularDeps = this.detectCircularDependencies();
    if (circularDeps.length > 0) {
      console.warn('Circular dependencies detected:', circularDeps);
    }

    await this.saveIndex();
  }

  /**
   * Detects circular dependencies in the graph
   *
   * @returns {Array} Array of circular dependency chains
   */
  detectCircularDependencies() {
    const circular = [];
    const visited = new Set();
    const recursionStack = new Set();

    const dfs = (id, path = []) => {
      if (recursionStack.has(id)) {
        circular.push([...path, id]);
        return;
      }

      if (visited.has(id)) return;

      visited.add(id);
      recursionStack.add(id);

      const graphNode = this.index.dependencyGraph[id];
      if (graphNode) {
        const dependents = [
          ...graphNode.usedBy.components,
          ...graphNode.usedBy.layouts,
          ...graphNode.usedBy.tokens
        ];

        for (const depId of dependents) {
          dfs(depId, [...path, id]);
        }
      }

      recursionStack.delete(id);
    };

    for (const id of Object.keys(this.index.dependencyGraph)) {
      dfs(id);
    }

    return circular;
  }

  // ==========================================================================
  // UTILITY METHODS (Sprint 1.8)
  // ==========================================================================

  /**
   * Checks if a file exists
   *
   * @param {string} filePath - Path to check
   * @returns {Promise<boolean>} True if file exists
   */
  async fileExists(filePath) {
    try {
      await fs.access(filePath);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Reads and parses a JSON file
   *
   * @param {string} filePath - Path to JSON file
   * @returns {Promise<Object>} Parsed JSON data
   */
  async readJSON(filePath) {
    try {
      const content = await fs.readFile(filePath, 'utf8');
      return JSON.parse(content);
    } catch (error) {
      throw new Error(`Failed to read JSON from ${filePath}: ${error.message}`);
    }
  }

  /**
   * Writes JSON to a file atomically (temp file + rename)
   *
   * @param {string} filePath - Path to write to
   * @param {Object} data - Data to write
   * @returns {Promise<void>}
   */
  async writeJSON(filePath, data) {
    const tempPath = `${filePath}.tmp`;

    try {
      // Ensure directory exists
      await fs.mkdir(path.dirname(filePath), { recursive: true });

      // Write to temp file
      await fs.writeFile(tempPath, JSON.stringify(data, null, 2), 'utf8');

      // Atomic rename
      await fs.rename(tempPath, filePath);
    } catch (error) {
      // Clean up temp file on error
      try {
        await fs.unlink(tempPath);
      } catch {}
      throw new Error(`Failed to write JSON to ${filePath}: ${error.message}`);
    }
  }

  /**
   * Deep merges two objects
   *
   * @param {Object} target - Target object
   * @param {Object} source - Source object
   * @returns {Object} Merged object
   */
  mergeDeep(target, source) {
    const output = { ...target };

    if (isObject(target) && isObject(source)) {
      for (const key of Object.keys(source)) {
        if (isObject(source[key])) {
          if (!(key in target)) {
            Object.assign(output, { [key]: source[key] });
          } else {
            output[key] = this.mergeDeep(target[key], source[key]);
          }
        } else {
          Object.assign(output, { [key]: source[key] });
        }
      }
    }

    return output;
  }

  /**
   * Ensures the manager is initialized before operations
   *
   * @throws {Error} If not initialized
   */
  async ensureInitialized() {
    if (!this._initialized) {
      await this.initialize();
    }
  }

  /**
   * Validates an entry against the schema
   *
   * @param {string} type - Entry type (component, token, layout)
   * @param {Object} entry - Entry to validate
   * @returns {Object} Validation result { valid: boolean, errors: string[] }
   */
  validateEntry(type, entry) {
    const errors = [];

    // Required fields
    if (!entry.name) errors.push('name is required');
    if (!entry.source) errors.push('source is required');
    if (!entry.source?.type) errors.push('source.type is required');

    // ID format validation (if provided)
    if (entry.id) {
      const parts = entry.id.split('-');
      if (parts.length < 4) {
        errors.push('id must follow format: {source}-{type}-{slug}-{suffix}');
      }
    }

    return { valid: errors.length === 0, errors };
  }

  /**
   * Validates the index structure
   *
   * @returns {Object} Validation result { valid: boolean, errors: string[] }
   */
  validateIndex() {
    const errors = [];

    if (!this.index) {
      errors.push('Index not loaded');
      return { valid: false, errors };
    }

    if (this.index.schemaVersion !== INDEX_SCHEMA_VERSION) {
      errors.push(`Schema version mismatch: expected ${INDEX_SCHEMA_VERSION}, got ${this.index.schemaVersion}`);
    }

    if (!this.index.registries) errors.push('registries object missing');
    if (!this.index.idIndex) errors.push('idIndex object missing');
    if (!this.index.sourceMapping) errors.push('sourceMapping object missing');
    if (!this.index.dependencyGraph) errors.push('dependencyGraph object missing');

    return { valid: errors.length === 0, errors };
  }

  /**
   * Gets statistics about the registries
   *
   * @returns {Promise<Object>} Statistics object
   */
  async getStats() {
    await this.ensureInitialized();

    const stats = {
      schemaVersion: INDEX_SCHEMA_VERSION,
      lastUpdated: this.index.lastUpdated,
      registries: {},
      totals: {
        entries: 0,
        idMappings: Object.keys(this.index.idIndex).length,
        sourceMappings: Object.keys(this.index.sourceMapping).length,
        dependencyNodes: Object.keys(this.index.dependencyGraph).length
      }
    };

    for (const type of REGISTRY_TYPES) {
      const registry = await this.loadRegistry(type);
      const count = Object.keys(registry.entries).length;

      stats.registries[type] = {
        count,
        lastModified: registry.metadata.lastUpdated
      };

      stats.totals.entries += count;
    }

    return stats;
  }
}

// Helper function
function isObject(item) {
  return item && typeof item === 'object' && !Array.isArray(item);
}

// Singleton factory function
let _managerInstance = null;
let _managerDesignRoot = null;

/**
 * Gets or creates a RegistryManager instance (singleton per designRoot)
 *
 * @param {string} designRoot - Path to .design directory
 * @returns {Promise<RegistryManager>} Initialized RegistryManager instance
 */
async function getRegistryManager(designRoot) {
  // Normalize path
  const normalizedRoot = path.resolve(designRoot);

  // Return cached instance if same designRoot
  if (_managerInstance && _managerDesignRoot === normalizedRoot) {
    return _managerInstance;
  }

  // Create new instance
  _managerInstance = new RegistryManager(normalizedRoot);
  _managerDesignRoot = normalizedRoot;
  await _managerInstance.initialize();

  return _managerInstance;
}

/**
 * Clears the singleton instance (useful for testing)
 */
function clearRegistryManager() {
  _managerInstance = null;
  _managerDesignRoot = null;
}

// Export
module.exports = RegistryManager;
module.exports.RegistryManager = RegistryManager;
module.exports.getRegistryManager = getRegistryManager;
module.exports.clearRegistryManager = clearRegistryManager;
module.exports.INDEX_SCHEMA_VERSION = INDEX_SCHEMA_VERSION;
module.exports.REGISTRY_TYPES = REGISTRY_TYPES;
module.exports.ID_SOURCES = ID_SOURCES;
module.exports.ID_TYPES = ID_TYPES;
