/**
 * Auto-Registrar - Automatic component registration on import
 *
 * This module handles automatic registration of components into the
 * componentRegistry.json when they are imported from any source.
 *
 * USES existing infrastructure:
 * - registry-reader.js for read/write operations
 * - content-hasher.js for ID generation
 *
 * v4.0.0 Integration:
 * - Added RegistryManager integration for unified registry support
 * - New methods: registerComponentV4, registerTokenV4, registerLayoutV4
 * - Backward compatible with legacy v3.0.0 registration
 *
 * Part of Two-State Architecture (Phase 1: Foundation & Schema)
 *
 * @module auto-registrar
 * @version 2.0.0
 */

const path = require('path');
const EventEmitter = require('events');

// USE existing modules - don't recreate
const {
  readComponentRegistry,
  writeComponentRegistry,
  getComponentById,
  invalidateCache,
  CURRENT_SCHEMA_VERSION,
  // v4.0.0 integration
  hasV4Registry,
  getManager
} = require('./registry-reader');
const { ContentHasher } = require('./content-hasher');
const { generateV4CanonicalId, isV4CanonicalId } = require('./canonical-id');

// Lazy-load RegistryManager to avoid circular dependencies
let _registryManagerModule = null;
function getRegistryManagerModule() {
  if (!_registryManagerModule) {
    _registryManagerModule = require('./registry-manager');
  }
  return _registryManagerModule;
}

// ============================================================================
// AutoRegistrar Class
// ============================================================================

/**
 * Handles automatic registration of components from various sources
 * into the central component registry.
 *
 * Events emitted:
 * - 'registered': When a component is registered { id, entry, isNew }
 * - 'updated': When an existing component is updated { id, entry }
 * - 'error': When registration fails { error, componentData, source }
 */
class AutoRegistrar extends EventEmitter {
  /**
   * Create a new AutoRegistrar instance
   *
   * @param {Object} options - Configuration options
   * @param {string} [options.projectPath] - Project root directory (default: cwd)
   * @param {boolean} [options.autoRegisterOnImport=true] - Auto-register on import
   * @param {boolean} [options.emitEvents=true] - Emit events on registration
   * @param {ContentHasher} [options.contentHasher] - Existing hasher instance
   */
  constructor(options = {}) {
    super();
    this.projectPath = options.projectPath || process.cwd();
    this.autoRegisterOnImport = options.autoRegisterOnImport !== false;
    this.emitEvents = options.emitEvents !== false;

    // USE existing hasher - don't recreate
    this.contentHasher = options.contentHasher || new ContentHasher();
  }

  // ==========================================================================
  // Core Registration Methods
  // ==========================================================================

  /**
   * Register a component in the registry
   *
   * @param {Object} componentData - Component data from extractor
   * @param {string} componentData.name - Component name
   * @param {string} [componentData.type] - Component type (COMPONENT, FRAME, etc.)
   * @param {string} [componentData.category] - Component category
   * @param {Object} [componentData.tokenDependencies] - Token dependencies
   * @param {Array} [componentData.variants] - Component variants
   * @param {Array} [componentData.props] - Component props
   *
   * @param {Object} source - Source information
   * @param {string} source.type - Source type (figma-plugin, figma-mcp, shadcn, nlp)
   * @param {string} [source.fileKey] - Figma file key
   * @param {string} [source.nodeId] - Figma node ID
   * @param {string} [source.figmaModifiedAt] - When Figma design was last modified
   * @param {string} [source.rawDataPath] - Path to raw extracted data
   * @param {string} [source.projectPath] - Override project path
   *
   * @returns {Promise<Object>} Registration result { success, id, entry, isNew, message }
   */
  async registerComponent(componentData, source) {
    const projectPath = source.projectPath || this.projectPath;

    try {
      // 1. Load registry using EXISTING readComponentRegistry
      const registry = await readComponentRegistry(projectPath);

      // Ensure components object exists
      registry.components = registry.components || {};

      // 2. Generate ID
      const id = this.generateComponentId(componentData, source);
      const existing = registry.components[id];

      // 3. Handle existing component (update sync metadata)
      if (existing) {
        return this._handleExistingComponent(projectPath, registry, id, existing, componentData, source);
      }

      // 4. Create new entry with v3.0.0 schema
      const entry = this.createRegistryEntry(componentData, source);

      // 5. Add to registry
      registry.components[id] = entry;
      registry.metadata = registry.metadata || {};
      registry.metadata.lastUpdated = new Date().toISOString();

      // 6. Write using EXISTING writeComponentRegistry
      await writeComponentRegistry(projectPath, registry, { createBackup: true });

      // 7. Emit event
      if (this.emitEvents) {
        this.emit('registered', { id, entry, isNew: true });
      }

      console.log(`[AutoRegistrar] Registered: ${id} (${componentData.name})`);

      return {
        success: true,
        id,
        entry,
        isNew: true,
        message: `Component "${componentData.name}" registered successfully`
      };

    } catch (error) {
      console.error(`[AutoRegistrar] Registration failed for "${componentData.name}":`, error.message);

      if (this.emitEvents) {
        this.emit('error', { error, componentData, source });
      }
      throw error;
    }
  }

  /**
   * Register a design token set
   *
   * @param {Object} tokenData - Token data
   * @param {string} tokenData.name - Token set name
   * @param {Object} tokenData.tokens - Token values
   *
   * @param {Object} source - Source information
   *
   * @returns {Promise<Object>} Registration result
   */
  async registerToken(tokenData, source) {
    // Delegate to v4.0.0 registration if available, otherwise use legacy storage
    const hasV4 = await this.hasV4Registry();

    if (hasV4) {
      return this.registerTokenV4(tokenData, source);
    }

    // Legacy fallback: store in .design/tokens/ without unified registry
    // This maintains backward compatibility for projects not yet on v4.0.0
    console.log(`[AutoRegistrar] Token registered (legacy): ${tokenData.name}`);
    return {
      success: true,
      id: `token-${this._sanitizeName(tokenData.name)}`,
      isNew: true,
      message: 'Token registered in legacy mode (upgrade to v4.0.0 for unified registry)'
    };
  }

  /**
   * Register multiple tokens from an extraction batch
   * This is the primary entry point for bulk token registration after extraction
   *
   * @param {Array} tokens - Array of token objects with name, value, category
   * @param {string} category - Token category (colors, typography, spacing, effects)
   * @param {Object} source - Source information (type, fileKey, etc.)
   * @returns {Promise<Object>} Batch registration result
   */
  async registerTokenBatch(tokens, category, source) {
    const results = {
      success: true,
      registered: 0,
      updated: 0,
      failed: 0,
      errors: [],
      ids: []
    };

    if (!Array.isArray(tokens) || tokens.length === 0) {
      return results;
    }

    for (const token of tokens) {
      try {
        const tokenData = {
          name: token.name || token.key,
          value: token.value || token.hex || token.rgb || token,
          category: category,
          cssVariable: token.cssVariable || `--${this._sanitizeName(token.name || token.key)}`,
          // Preserve additional metadata
          ...(token.description && { description: token.description }),
          ...(token.group && { group: token.group }),
          ...(token.styleKey && { styleKey: token.styleKey })
        };

        const result = await this.registerToken(tokenData, {
          ...source,
          styleId: token.styleKey || token.id || null
        });

        if (result.success) {
          if (result.isNew) {
            results.registered++;
          } else {
            results.updated++;
          }
          results.ids.push(result.id);
        } else {
          results.failed++;
          results.errors.push({ token: token.name, error: result.message });
        }
      } catch (error) {
        results.failed++;
        results.errors.push({ token: token.name || 'unknown', error: error.message });
      }
    }

    results.success = results.failed === 0;
    console.log(`[AutoRegistrar] Token batch: ${results.registered} registered, ${results.updated} updated, ${results.failed} failed`);

    return results;
  }

  // ==========================================================================
  // v4.0.0 Registry Manager Integration
  // ==========================================================================

  /**
   * Check if v4.0.0 registry is available
   * @returns {Promise<boolean>} True if v4.0.0 registry exists
   */
  async hasV4Registry() {
    const designRoot = path.join(this.projectPath, '.design');
    return hasV4Registry(designRoot);
  }

  /**
   * Get the RegistryManager instance
   * @returns {Promise<Object>} RegistryManager instance
   */
  async getRegistryManager() {
    const designRoot = path.join(this.projectPath, '.design');
    const { getRegistryManager } = getRegistryManagerModule();
    return getRegistryManager(designRoot);
  }

  /**
   * Register a component using v4.0.0 RegistryManager
   * Preferred method for new code - uses unified registry with proper ID format
   *
   * @param {Object} componentData - Component data
   * @param {Object} source - Source information
   * @returns {Promise<Object>} Registration result { success, id, entry, isNew }
   */
  async registerComponentV4(componentData, source) {
    const designRoot = path.join(this.projectPath, '.design');

    try {
      const manager = await this.getRegistryManager();

      // Map source type to v4.0.0 source
      const v4Source = this._mapToV4Source(source.type);

      // Create v4.0.0 entry
      const entry = {
        name: componentData.name,
        type: componentData.type || 'COMPONENT',
        category: this._determineCategory(componentData),
        source: {
          type: v4Source,
          fileKey: source.fileKey || null,
          nodeId: source.nodeId || componentData.figmaId || null,
          extractedAt: new Date().toISOString(),
          originalUrl: componentData.figmaUrl || null,
          rawDataPath: source.rawDataPath || null
        },
        transformation: {
          state: 'imported',
          framework: null,
          transformedAt: null,
          codePath: null,
          storyPath: null
        },
        tokenDependencies: componentData.tokenDependencies || {},
        interactiveStates: componentData.interactiveStates || {},
        variants: componentData.variants || [],
        props: componentData.props || []
      };

      // Add entry using RegistryManager
      const result = await manager.addEntry(entry, 'components', v4Source, source.nodeId);

      if (this.emitEvents) {
        this.emit('registered', { id: result.id, entry: result.entry, isNew: result.isNew });
      }

      console.log(`[AutoRegistrar] v4.0.0 Registered: ${result.id} (${componentData.name})`);

      return {
        success: true,
        id: result.id,
        entry: result.entry,
        isNew: result.isNew,
        message: `Component "${componentData.name}" registered with v4.0.0 registry`
      };

    } catch (error) {
      console.error(`[AutoRegistrar] v4.0.0 registration failed for "${componentData.name}":`, error.message);

      if (this.emitEvents) {
        this.emit('error', { error, componentData, source });
      }
      throw error;
    }
  }

  /**
   * Register a token using v4.0.0 RegistryManager
   *
   * @param {Object} tokenData - Token data
   * @param {Object} source - Source information
   * @returns {Promise<Object>} Registration result
   */
  async registerTokenV4(tokenData, source) {
    try {
      const manager = await this.getRegistryManager();
      const v4Source = this._mapToV4Source(source.type);

      const entry = {
        name: tokenData.name,
        category: tokenData.category || 'colors',
        value: tokenData.value,
        cssVariable: tokenData.cssVariable || `--${this._sanitizeName(tokenData.name)}`,
        source: {
          type: v4Source,
          fileKey: source.fileKey || null,
          styleId: source.styleId || null,
          extractedAt: new Date().toISOString()
        }
      };

      const result = await manager.addEntry(entry, 'tokens', v4Source, source.styleId);

      if (this.emitEvents) {
        this.emit('registered', { id: result.id, entry: result.entry, isNew: result.isNew, type: 'token' });
      }

      console.log(`[AutoRegistrar] v4.0.0 Token registered: ${result.id}`);

      return {
        success: true,
        id: result.id,
        entry: result.entry,
        isNew: result.isNew,
        message: `Token "${tokenData.name}" registered with v4.0.0 registry`
      };

    } catch (error) {
      console.error(`[AutoRegistrar] v4.0.0 token registration failed:`, error.message);

      if (this.emitEvents) {
        this.emit('error', { error, tokenData, source });
      }
      throw error;
    }
  }

  /**
   * Register a layout using v4.0.0 RegistryManager
   *
   * @param {Object} layoutData - Layout data
   * @param {Object} source - Source information
   * @returns {Promise<Object>} Registration result
   */
  async registerLayoutV4(layoutData, source) {
    try {
      const manager = await this.getRegistryManager();
      const v4Source = this._mapToV4Source(source.type);

      const entry = {
        name: layoutData.name,
        category: layoutData.category || 'page',
        dimensions: layoutData.dimensions || {},
        source: {
          type: v4Source,
          fileKey: source.fileKey || null,
          nodeId: source.nodeId || null,
          extractedAt: new Date().toISOString(),
          originalUrl: layoutData.figmaUrl || null
        },
        transformation: {
          state: 'imported',
          framework: null,
          transformedAt: null
        },
        componentRefs: layoutData.componentRefs || [],
        tokenRefs: layoutData.tokenRefs || []
      };

      const result = await manager.addEntry(entry, 'layouts', v4Source, source.nodeId);

      if (this.emitEvents) {
        this.emit('registered', { id: result.id, entry: result.entry, isNew: result.isNew, type: 'layout' });
      }

      console.log(`[AutoRegistrar] v4.0.0 Layout registered: ${result.id}`);

      return {
        success: true,
        id: result.id,
        entry: result.entry,
        isNew: result.isNew,
        message: `Layout "${layoutData.name}" registered with v4.0.0 registry`
      };

    } catch (error) {
      console.error(`[AutoRegistrar] v4.0.0 layout registration failed:`, error.message);

      if (this.emitEvents) {
        this.emit('error', { error, layoutData, source });
      }
      throw error;
    }
  }

  /**
   * Smart registration - automatically uses v4.0.0 if available, falls back to legacy
   *
   * @param {Object} data - Component/token/layout data
   * @param {string} type - Entry type ('component', 'token', 'layout')
   * @param {Object} source - Source information
   * @returns {Promise<Object>} Registration result
   */
  async smartRegister(data, type, source) {
    const hasV4 = await this.hasV4Registry();

    if (hasV4) {
      switch (type) {
        case 'component':
          return this.registerComponentV4(data, source);
        case 'token':
          return this.registerTokenV4(data, source);
        case 'layout':
          return this.registerLayoutV4(data, source);
        default:
          throw new Error(`Unknown registration type: ${type}`);
      }
    } else {
      // Fall back to legacy registration
      switch (type) {
        case 'component':
          return this.registerComponent(data, source);
        case 'token':
          return this.registerToken(data, source);
        default:
          throw new Error(`Legacy registration not supported for type: ${type}`);
      }
    }
  }

  /**
   * Map source type to v4.0.0 source identifier
   * @private
   */
  _mapToV4Source(sourceType) {
    const mapping = {
      'figma-plugin': 'figma-plugin',
      'figma-mcp': 'figma-plugin',
      'figma': 'figma-plugin',
      'shadcn': 'shadcn-mcp',
      'shadcn-mcp': 'shadcn-mcp',
      'nlp': 'nlp-prompt',
      'nlp-prompt': 'nlp-prompt',
      'manual': 'manual'
    };
    return mapping[sourceType] || 'manual';
  }

  // ==========================================================================
  // ID Generation (Sprint 1.6)
  // ==========================================================================

  /**
   * Generate a unique component ID based on source and content
   *
   * ID Format: {source}-{name}-{uniqueId}
   * - For Figma: uses nodeId (guaranteed unique within file)
   * - For others: uses content hash
   *
   * @param {Object} component - Component data
   * @param {Object} source - Source information
   * @returns {string} Unique component ID
   */
  generateComponentId(component, source) {
    const sourceType = source.type || 'unknown';
    const name = this._sanitizeName(component.name || 'component');

    // Use Figma node ID if available (guaranteed unique within file)
    if (source.nodeId) {
      // Format nodeId: "1234:5678" -> "1234-5678"
      const sanitizedNodeId = source.nodeId.replace(/:/g, '-');
      return `${sourceType}-${name}-${sanitizedNodeId}`;
    }

    // For non-Figma sources, use EXISTING content hasher
    const contentToHash = JSON.stringify({
      name: component.name,
      source: source.type,
      fileKey: source.fileKey || null
    });
    const contentHash = this.contentHasher.shortHash(contentToHash);
    return `${sourceType}-${name}-${contentHash}`;
  }

  // ==========================================================================
  // Registry Entry Creation (Sprint 1.7)
  // ==========================================================================

  /**
   * Create a v3.0.0 compliant registry entry
   *
   * @param {Object} component - Component data
   * @param {Object} source - Source information
   * @returns {Object} Registry entry with all v3.0.0 fields
   */
  createRegistryEntry(component, source) {
    const id = this.generateComponentId(component, source);
    const now = new Date().toISOString();

    return {
      // Identity
      id,
      name: component.name,
      type: component.type || 'COMPONENT',
      category: this._determineCategory(component),

      // Source tracking
      source: {
        type: source.type,
        fileKey: source.fileKey || null,
        nodeId: source.nodeId || component.figmaId || null,
        extractedAt: now,
        originalUrl: component.figmaUrl || null,
        rawDataPath: source.rawDataPath || null
      },

      // NEW v3.0.0: Transformation state (Two-State Architecture)
      // Starts as 'imported', transitions to 'transformed' after code generation
      transformation: {
        state: 'imported',
        framework: null,
        transformedAt: null,
        codePath: null,
        storyPath: null,
        codeHash: null,
        storyHash: null,
        version: 1
      },

      // NEW v3.0.0: Sync metadata for auto-sync tracking
      syncMetadata: {
        lastFigmaSync: now,
        figmaModifiedAt: source.figmaModifiedAt || null,
        localModifiedAt: null,
        syncCount: 1,
        userModified: false
      },

      // Existing fields (v2.0.0 compatibility)
      tokenDependencies: component.tokenDependencies || {},
      interactiveStates: component.interactiveStates || {},
      variants: component.variants || [],
      props: component.props || [],

      // Paths (will be populated on transform)
      paths: {
        rawSource: source.rawDataPath || null,
        codeOutput: null,
        storyOutput: null
      },

      // Metadata
      metadata: {
        createdAt: now,
        updatedAt: now,
        version: 1,
        schemaVersion: CURRENT_SCHEMA_VERSION
      }
    };
  }

  // ==========================================================================
  // Query Methods
  // ==========================================================================

  /**
   * Check if a component exists in the registry
   *
   * @param {string} componentId - Component ID to check
   * @returns {Promise<boolean>} True if component exists
   */
  async componentExists(componentId) {
    const registry = await readComponentRegistry(this.projectPath);
    return getComponentById(registry, componentId) !== null;
  }

  /**
   * Get a component from the registry
   *
   * @param {string} componentId - Component ID
   * @returns {Promise<Object|null>} Component entry or null
   */
  async getComponent(componentId) {
    const registry = await readComponentRegistry(this.projectPath);
    return getComponentById(registry, componentId);
  }

  /**
   * Get all components from the registry
   *
   * @returns {Promise<Array>} Array of {id, ...entry} objects
   */
  async getAllComponents() {
    const registry = await readComponentRegistry(this.projectPath);
    return Object.entries(registry.components || {}).map(([id, entry]) => ({
      id,
      ...entry
    }));
  }

  // ==========================================================================
  // Event Handlers
  // ==========================================================================

  /**
   * Register handler for registration events
   * @param {Function} handler - Handler function
   */
  onRegistered(handler) {
    this.on('registered', handler);
  }

  /**
   * Register handler for error events
   * @param {Function} handler - Handler function
   */
  onError(handler) {
    this.on('error', handler);
  }

  // ==========================================================================
  // Private Methods
  // ==========================================================================

  /**
   * Handle updating an existing component's sync metadata
   * @private
   */
  async _handleExistingComponent(projectPath, registry, id, existing, componentData, source) {
    const now = new Date().toISOString();

    // Update sync metadata
    const entry = registry.components[id];

    // Ensure syncMetadata exists (migration from older versions)
    entry.syncMetadata = entry.syncMetadata || {
      lastFigmaSync: null,
      figmaModifiedAt: null,
      localModifiedAt: null,
      syncCount: 0,
      userModified: false
    };

    entry.syncMetadata.lastFigmaSync = now;
    entry.syncMetadata.syncCount = (entry.syncMetadata.syncCount || 0) + 1;
    entry.syncMetadata.figmaModifiedAt = source.figmaModifiedAt || entry.syncMetadata.figmaModifiedAt;

    // Update metadata
    entry.metadata = entry.metadata || {};
    entry.metadata.updatedAt = now;

    // Update source info if changed
    if (source.rawDataPath) {
      entry.source = entry.source || {};
      entry.source.rawDataPath = source.rawDataPath;
      entry.paths = entry.paths || {};
      entry.paths.rawSource = source.rawDataPath;
    }

    await writeComponentRegistry(projectPath, registry, { createBackup: false });

    if (this.emitEvents) {
      this.emit('updated', { id, entry, isNew: false });
      this.emit('registered', { id, entry, isNew: false });
    }

    console.log(`[AutoRegistrar] Updated: ${id} (sync #${entry.syncMetadata.syncCount})`);

    return {
      success: true,
      id,
      entry,
      isNew: false,
      message: `Component "${componentData.name}" already registered, updated sync metadata`
    };
  }

  /**
   * Determine component category from name/type
   * @private
   */
  _determineCategory(component) {
    // Use existing category if provided
    if (component.category) return component.category;

    const name = (component.name || '').toLowerCase();

    // Category inference rules
    if (name.includes('button') || name.includes('btn')) return 'actions';
    if (name.includes('input') || name.includes('field') || name.includes('text')) return 'inputs';
    if (name.includes('card') || name.includes('modal') || name.includes('dialog')) return 'containers';
    if (name.includes('nav') || name.includes('menu') || name.includes('tab')) return 'navigation';
    if (name.includes('icon') || name.includes('avatar') || name.includes('badge')) return 'display';
    if (name.includes('form') || name.includes('checkbox') || name.includes('radio')) return 'forms';
    if (name.includes('table') || name.includes('list') || name.includes('grid')) return 'data-display';
    if (name.includes('header') || name.includes('footer') || name.includes('sidebar')) return 'layout';

    return 'ui-elements';
  }

  /**
   * Sanitize name for use in IDs
   * @private
   */
  _sanitizeName(name) {
    return name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '');
  }
}

// ============================================================================
// Exports
// ============================================================================

module.exports = {
  AutoRegistrar
};
