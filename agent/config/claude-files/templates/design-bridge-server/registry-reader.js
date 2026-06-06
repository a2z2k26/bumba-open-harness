/**
 * Registry Reader - Utility for reading, writing, and querying componentRegistry.json
 *
 * Provides cached access to component registry with query utilities
 * for looking up components by ID, category, or other criteria.
 *
 * Schema versions:
 * - v1.0.0: Original schema
 * - v2.0.0: Added source, tokenDependencies, variants
 * - v3.0.0: Added transformation state + syncMetadata (Two-State Architecture)
 * - v4.0.0: Unified RegistryManager with coordinator pattern (NEW)
 *
 * NOTE: This module now delegates to RegistryManager internally for v4.0.0+ projects.
 * Legacy functions are maintained for backward compatibility but will show deprecation warnings.
 */
const fs = require('fs').promises;
const fsSync = require('fs');
const path = require('path');

// Import new RegistryManager
const { getRegistryManager, clearRegistryManager } = require('./registry-manager');

// Current schema version
const CURRENT_SCHEMA_VERSION = '3.0.0';

// In-memory cache
let registryCache = {
  data: null,
  timestamp: 0,
  path: null
};

/**
 * Read the component registry from a project
 * @param {string} projectPath - Project root directory
 * @param {Object} options - Read options
 * @param {boolean} options.forceRefresh - Bypass cache
 * @returns {Promise<Object>} Registry object
 */
async function readComponentRegistry(projectPath, options = {}) {
  const registryPath = path.join(projectPath, '.design', 'componentRegistry.json');

  try {
    const stat = await fs.stat(registryPath);

    // Check cache validity
    if (!options.forceRefresh &&
        registryCache.path === registryPath &&
        registryCache.timestamp >= stat.mtimeMs) {
      return registryCache.data;
    }

    // Read and parse
    const content = await fs.readFile(registryPath, 'utf8');
    const registry = JSON.parse(content);

    // Validate basic structure
    validateRegistrySchema(registry);

    // Update cache
    registryCache = {
      data: registry,
      timestamp: stat.mtimeMs,
      path: registryPath
    };

    return registry;

  } catch (error) {
    if (error.code === 'ENOENT') {
      // Return empty registry if file doesn't exist
      console.warn('[registry-reader] Registry not found, returning empty');
      return createEmptyRegistry();
    }
    throw new Error(`Failed to read component registry: ${error.message}`);
  }
}

/**
 * Write the component registry to disk with atomic write pattern
 * Uses temp file + rename for crash safety (following story-hash-registry.js pattern)
 *
 * @param {string} projectPath - Project root directory
 * @param {Object} registry - Registry object to write
 * @param {Object} options - Write options
 * @param {boolean} options.createBackup - Create .bak file before write (default: true)
 * @param {boolean} options.skipValidation - Skip schema validation (default: false)
 * @returns {Promise<{success: boolean, path: string}>}
 */
async function writeComponentRegistry(projectPath, registry, options = {}) {
  const { createBackup = true, skipValidation = false } = options;
  const registryPath = path.join(projectPath, '.design', 'componentRegistry.json');
  const tempPath = registryPath + '.tmp';
  const backupPath = registryPath + '.bak';

  // Validate before writing (unless skipped)
  if (!skipValidation) {
    validateRegistrySchema(registry);
  }

  // Ensure directory exists
  const registryDir = path.dirname(registryPath);
  await fs.mkdir(registryDir, { recursive: true });

  // Update metadata timestamp
  if (registry.metadata) {
    registry.metadata.lastUpdated = new Date().toISOString();
  }

  // Create backup of existing file (if it exists and backup requested)
  if (createBackup) {
    try {
      await fs.access(registryPath);
      await fs.copyFile(registryPath, backupPath);
    } catch (err) {
      // File doesn't exist yet, no backup needed
    }
  }

  // Atomic write: temp file + rename
  await fs.writeFile(tempPath, JSON.stringify(registry, null, 2), 'utf8');
  await fs.rename(tempPath, registryPath);

  // Invalidate cache so next read gets fresh data
  invalidateCache();

  console.log(`[registry-reader] Registry written to ${registryPath}`);
  return { success: true, path: registryPath };
}

/**
 * Validate registry has required structure
 * Supports v1.0.0, v2.0.0, and v3.0.0 schemas
 *
 * @param {Object} registry - Registry object to validate
 * @throws {Error} If registry is invalid
 */
function validateRegistrySchema(registry) {
  if (!registry || typeof registry !== 'object') {
    throw new Error('Registry must be an object');
  }

  if (!registry.components || typeof registry.components !== 'object') {
    throw new Error('Registry must have components object');
  }

  // Validate each component entry
  for (const [id, entry] of Object.entries(registry.components)) {
    if (!entry.name) {
      console.warn(`[registry-reader] Component ${id} missing name`);
    }

    // v3.0.0 specific validation (optional fields, just warn if malformed)
    if (entry.transformation) {
      const validStates = ['imported', 'transformed'];
      if (entry.transformation.state && !validStates.includes(entry.transformation.state)) {
        console.warn(`[registry-reader] Component ${id} has invalid transformation.state: ${entry.transformation.state}`);
      }
    }
  }
}

/**
 * Migrate registry to current schema version (v3.0.0)
 * ADDITIVE migration - preserves all existing fields, adds new ones
 *
 * @param {Object} registry - Registry object to migrate
 * @returns {Object} Migrated registry (mutates original)
 */
function migrateRegistrySchema(registry) {
  const currentVersion = registry.version || registry.metadata?.schemaVersion || '1.0.0';

  // Already at current version
  if (currentVersion === CURRENT_SCHEMA_VERSION) {
    return registry;
  }

  console.log(`[registry-reader] Migrating registry from ${currentVersion} to ${CURRENT_SCHEMA_VERSION}`);

  // Ensure metadata exists
  registry.metadata = registry.metadata || {};
  registry.metadata.schemaVersion = CURRENT_SCHEMA_VERSION;
  registry.metadata.migratedAt = new Date().toISOString();
  registry.metadata.previousVersion = currentVersion;

  // Update version field
  registry.version = CURRENT_SCHEMA_VERSION;

  // Migrate each component to v3.0.0 schema
  for (const [id, component] of Object.entries(registry.components || {})) {
    // Add transformation field if missing (Two-State Architecture)
    if (!component.transformation) {
      // Derive initial state from existing data
      const hasTransformedTo = component.transformedTo && component.transformedTo.length > 0;
      const framework = hasTransformedTo ? component.transformedTo[0] : null;
      const codePath = framework && component.outputPaths ? component.outputPaths[framework] : null;

      component.transformation = {
        state: hasTransformedTo ? 'transformed' : 'imported',
        framework: framework,
        codePath: codePath,
        storyPath: null,
        codeHash: null,
        storyHash: null,
        transformedAt: hasTransformedTo ? (component.updatedAt || new Date().toISOString()) : null,
        version: 1
      };
    }

    // Add syncMetadata field if missing
    if (!component.syncMetadata) {
      component.syncMetadata = {
        lastFigmaSync: component.updatedAt || null,
        figmaModifiedAt: component.metadata?.lastModified || null,
        localModifiedAt: null,
        syncCount: 0,
        userModified: false
      };
    }
  }

  return registry;
}

/**
 * Read registry and auto-migrate to latest schema if needed
 *
 * @param {string} projectPath - Project root directory
 * @param {Object} options - Read options
 * @param {boolean} options.autoMigrate - Auto-migrate to latest schema (default: true)
 * @param {boolean} options.saveMigration - Save migrated registry to disk (default: false)
 * @returns {Promise<Object>} Registry object (migrated if needed)
 */
async function readAndMigrateRegistry(projectPath, options = {}) {
  const { autoMigrate = true, saveMigration = false } = options;

  const registry = await readComponentRegistry(projectPath, options);

  if (autoMigrate) {
    const wasMigrated = registry.version !== CURRENT_SCHEMA_VERSION;
    migrateRegistrySchema(registry);

    if (wasMigrated && saveMigration) {
      await writeComponentRegistry(projectPath, registry, { createBackup: true });
      console.log(`[registry-reader] Migrated registry saved to disk`);
    }
  }

  return registry;
}

/**
 * Create empty registry structure (v3.0.0 schema)
 * @returns {Object} Empty registry object with Two-State Architecture support
 */
function createEmptyRegistry() {
  return {
    version: CURRENT_SCHEMA_VERSION,
    metadata: {
      schemaVersion: CURRENT_SCHEMA_VERSION,
      lastUpdated: new Date().toISOString(),
      createdAt: new Date().toISOString()
    },
    components: {}
  };
}

/**
 * Get a component by its ID
 * @param {Object} registry - Registry object
 * @param {string} id - Component ID
 * @param {Object} options - Query options
 * @param {boolean} options.caseInsensitive - Case-insensitive matching
 * @returns {Object|null} Component entry or null
 */
function getComponentById(registry, id, options = {}) {
  if (!registry?.components) return null;

  // Direct lookup first
  if (registry.components[id]) {
    return registry.components[id];
  }

  // Case-insensitive fallback
  if (options.caseInsensitive) {
    const lowerSearchId = id.toLowerCase();
    for (const [componentId, entry] of Object.entries(registry.components)) {
      if (componentId.toLowerCase() === lowerSearchId) {
        return entry;
      }
    }
  }

  return null;
}

/**
 * Get components by category
 * @param {Object} registry - Registry object
 * @param {string} category - Category to filter by
 * @returns {Array} Array of {id, entry} objects
 */
function getComponentsByCategory(registry, category) {
  if (!registry?.components) return [];

  const results = [];
  const lowerCategory = category.toLowerCase();

  for (const [id, entry] of Object.entries(registry.components)) {
    const entryCategory = (entry.category || '').toLowerCase();
    if (entryCategory === lowerCategory) {
      results.push({ id, ...entry });
    }
  }

  return results;
}

/**
 * Get components by source type
 * @param {Object} registry - Registry object
 * @param {string} sourceType - Source type (figma-plugin, figma-mcp, shadcn, etc.)
 * @returns {Array} Array of {id, entry} objects
 */
function getComponentsBySource(registry, sourceType) {
  if (!registry?.components) return [];

  const results = [];

  for (const [id, entry] of Object.entries(registry.components)) {
    if (entry.source?.type === sourceType) {
      results.push({ id, ...entry });
    }
  }

  return results;
}

/**
 * Resolve the raw source file path for a component
 * @param {string} projectPath - Project root directory
 * @param {Object} entry - Component registry entry
 * @returns {string} Absolute path to raw source file
 */
function resolveRawFilePath(projectPath, entry) {
  // Use explicit path if available
  if (entry.paths?.rawSource) {
    const rawPath = entry.paths.rawSource;
    // Handle relative paths
    if (rawPath.startsWith('.')) {
      return path.join(projectPath, rawPath);
    }
    return rawPath;
  }

  // Fall back to computed path
  const sanitizedName = sanitizeName(entry.name || 'component');
  return path.join(
    projectPath,
    '.design',
    'source',
    'components',
    `${sanitizedName}.json`
  );
}

/**
 * Resolve the code output path for a component
 * @param {string} projectPath - Project root directory
 * @param {Object} entry - Component registry entry
 * @param {string} framework - Target framework (react, vue, etc.)
 * @returns {string} Absolute path for code output
 */
function resolveCodeOutputPath(projectPath, entry, framework = 'react') {
  // Use explicit path if available
  if (entry.paths?.codeOutput) {
    const codePath = entry.paths.codeOutput;
    if (codePath.startsWith('.')) {
      return path.join(projectPath, codePath);
    }
    return codePath;
  }

  // Generate path based on framework
  const pascalName = toPascalCase(entry.name || 'Component');
  const extensions = {
    react: '.tsx',
    vue: '.vue',
    svelte: '.svelte',
    angular: '.component.ts',
    'react-native': '.tsx',
    flutter: '.dart',
    swiftui: '.swift',
    'jetpack-compose': '.kt',
    'web-components': '.ts'
  };

  const ext = extensions[framework] || '.tsx';

  return path.join(
    projectPath,
    'src',
    'components',
    `${pascalName}${ext}`
  );
}

/**
 * Load raw source data for a component
 * @param {string} projectPath - Project root directory
 * @param {Object} entry - Component registry entry
 * @returns {Promise<Object>} Raw component data
 */
async function loadRawSource(projectPath, entry) {
  const rawPath = resolveRawFilePath(projectPath, entry);

  try {
    const content = await fs.readFile(rawPath, 'utf8');
    return JSON.parse(content);
  } catch (error) {
    if (error.code === 'ENOENT') {
      throw new Error(`Raw source not found: ${rawPath}`);
    }
    throw new Error(`Failed to load raw source: ${error.message}`);
  }
}

/**
 * Get all component IDs from registry
 * @param {Object} registry - Registry object
 * @returns {Array<string>} Array of component IDs
 */
function getAllComponentIds(registry) {
  if (!registry?.components) return [];
  return Object.keys(registry.components);
}

/**
 * Search components by name (fuzzy)
 * @param {Object} registry - Registry object
 * @param {string} searchTerm - Search term
 * @returns {Array} Matching components
 */
function searchComponentsByName(registry, searchTerm) {
  if (!registry?.components) return [];

  const lowerSearch = searchTerm.toLowerCase();
  const results = [];

  for (const [id, entry] of Object.entries(registry.components)) {
    const name = (entry.name || '').toLowerCase();
    if (name.includes(lowerSearch)) {
      results.push({ id, ...entry, matchScore: name === lowerSearch ? 1 : 0.5 });
    }
  }

  // Sort by match score (exact matches first)
  return results.sort((a, b) => b.matchScore - a.matchScore);
}

/**
 * Get components that depend on specific tokens
 * @param {Object} registry - Registry object
 * @param {string} tokenCategory - Token category (colors, typography, etc.)
 * @param {string} tokenName - Token name to search for
 * @returns {Array} Components using the specified token
 */
function getComponentsByTokenDependency(registry, tokenCategory, tokenName) {
  if (!registry?.components) return [];

  const results = [];

  for (const [id, entry] of Object.entries(registry.components)) {
    const tokens = entry.tokenDependencies?.[tokenCategory] || [];
    if (tokens.includes(tokenName)) {
      results.push({ id, ...entry });
    }
  }

  return results;
}

/**
 * Get registry statistics
 * @param {Object} registry - Registry object
 * @returns {Object} Statistics about the registry
 */
function getRegistryStats(registry) {
  if (!registry?.components) {
    return {
      totalComponents: 0,
      byCategory: {},
      bySource: {},
      withTokens: 0,
      withVariants: 0
    };
  }

  const stats = {
    totalComponents: Object.keys(registry.components).length,
    byCategory: {},
    bySource: {},
    withTokens: 0,
    withVariants: 0
  };

  for (const entry of Object.values(registry.components)) {
    // Count by category
    const category = entry.category || 'uncategorized';
    stats.byCategory[category] = (stats.byCategory[category] || 0) + 1;

    // Count by source
    const source = entry.source?.type || 'unknown';
    stats.bySource[source] = (stats.bySource[source] || 0) + 1;

    // Count with tokens
    if (entry.tokenDependencies && Object.keys(entry.tokenDependencies).length > 0) {
      stats.withTokens++;
    }

    // Count with variants
    if (entry.variants && entry.variants.length > 0) {
      stats.withVariants++;
    }
  }

  return stats;
}

/**
 * Invalidate registry cache
 */
function invalidateCache() {
  registryCache = {
    data: null,
    timestamp: 0,
    path: null
  };
}

// Utility functions
function sanitizeName(name) {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
}

function toPascalCase(name) {
  return name
    .split(/[^a-zA-Z0-9]+/)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join('');
}

// ==========================================================================
// NEW v4.0.0 REGISTRY MANAGER INTEGRATION
// ==========================================================================

/**
 * Check if a project uses v4.0.0 registry format
 * @param {string} projectPath - Project root directory
 * @returns {Promise<boolean>} True if v4.0.0 registry-index.json exists
 */
async function hasV4Registry(projectPath) {
  const indexPath = path.join(projectPath, '.design', 'registry-index.json');
  try {
    await fs.access(indexPath);
    return true;
  } catch {
    return false;
  }
}

/**
 * Get RegistryManager for a project (preferred v4.0.0 API)
 * @param {string} projectPath - Project root directory
 * @returns {Promise<RegistryManager>} Initialized RegistryManager
 */
async function getManager(projectPath) {
  const designRoot = path.join(projectPath, '.design');
  return getRegistryManager(designRoot);
}

/**
 * Read components registry using new RegistryManager
 * @param {string} projectPath - Project root directory
 * @returns {Promise<Object>} Components in v3.0.0-compatible format
 */
async function readComponentsV4(projectPath) {
  const manager = await getManager(projectPath);
  const registry = await manager.loadRegistry('components');

  // Convert to legacy format for backward compatibility
  return {
    version: '3.0.0',
    metadata: {
      schemaVersion: '4.0.0',
      lastUpdated: registry.metadata.lastUpdated,
      createdAt: registry.metadata.createdAt
    },
    components: registry.entries
  };
}

/**
 * Read tokens registry using new RegistryManager
 * @param {string} projectPath - Project root directory
 * @returns {Promise<Object>} Tokens in legacy-compatible format
 */
async function readTokensV4(projectPath) {
  const manager = await getManager(projectPath);
  const registry = await manager.loadRegistry('tokens');

  // Group tokens by category for legacy format compatibility
  const categories = {};
  for (const entry of Object.values(registry.entries)) {
    const category = entry.category || 'uncategorized';
    if (!categories[category]) {
      categories[category] = { count: 0, tokens: [] };
    }
    categories[category].tokens.push({
      name: entry.name,
      value: entry.value,
      rawPath: entry.source?.rawDataPath,
      source: {
        type: entry.source?.type,
        styleId: entry.source?.styleId,
        styleName: entry.displayName,
        extractedAt: entry.source?.extractedAt
      }
    });
    categories[category].count++;
  }

  return {
    version: '1.0.0',
    sources: [],
    categories
  };
}

/**
 * Read layouts registry using new RegistryManager
 * @param {string} projectPath - Project root directory
 * @returns {Promise<Object>} Layouts in legacy-compatible format
 */
async function readLayoutsV4(projectPath) {
  const manager = await getManager(projectPath);
  const registry = await manager.loadRegistry('layouts');

  // Convert to legacy format
  const layouts = Object.values(registry.entries).map(entry => ({
    id: entry.source?.nodeId || entry.id,
    name: entry.name,
    path: entry.transformation?.codePath,
    rawPath: entry.source?.rawDataPath,
    screenshot: entry.screenshot,
    source: entry.source,
    componentDependencies: entry.dependencies?.components || [],
    tokenDependencies: {},
    dependencyStatus: entry.dependencyStatus || { resolved: [], missing: [], outdated: [] },
    framework: entry.transformation?.framework || 'react',
    figmaUrl: entry.figmaUrl,
    dimensions: entry.dimensions,
    behavior: entry.behavior,
    lastSynced: entry.sync?.lastFigmaSync,
    canGenerate: entry.canGenerate !== false,
    errors: []
  }));

  return {
    version: '1.0.0',
    layouts
  };
}

/**
 * Find component by Figma node ID using new RegistryManager
 * @param {string} projectPath - Project root directory
 * @param {string} nodeId - Figma node ID
 * @returns {Promise<Object|null>} Component entry or null
 */
async function findComponentByNodeId(projectPath, nodeId) {
  const manager = await getManager(projectPath);
  return manager.findByNodeId(nodeId);
}

/**
 * Find token by Figma style ID using new RegistryManager
 * @param {string} projectPath - Project root directory
 * @param {string} styleId - Figma style ID
 * @returns {Promise<Object|null>} Token entry or null
 */
async function findTokenByStyleId(projectPath, styleId) {
  const manager = await getManager(projectPath);
  return manager.findByStyleId(styleId);
}

/**
 * Get all dependents of an entry (what uses this?)
 * @param {string} projectPath - Project root directory
 * @param {string} id - Canonical ID
 * @returns {Promise<Object>} { components: [], layouts: [], tokens: [] }
 */
async function getDependents(projectPath, id) {
  const manager = await getManager(projectPath);
  return manager.findDependents(id);
}

/**
 * Get all dependencies of an entry (what does this use?)
 * @param {string} projectPath - Project root directory
 * @param {string} id - Canonical ID
 * @returns {Promise<Object>} { tokens: [], components: [] }
 */
async function getDependencies(projectPath, id) {
  const manager = await getManager(projectPath);
  return manager.findDependencies(id);
}

/**
 * Get unified registry stats using new RegistryManager
 * @param {string} projectPath - Project root directory
 * @returns {Promise<Object>} Registry statistics
 */
async function getUnifiedStats(projectPath) {
  const manager = await getManager(projectPath);
  return manager.getStats();
}

module.exports = {
  // Core read/write operations (legacy - maintained for backward compatibility)
  readComponentRegistry,
  writeComponentRegistry,
  readAndMigrateRegistry,

  // Schema management
  validateRegistrySchema,
  migrateRegistrySchema,
  createEmptyRegistry,
  CURRENT_SCHEMA_VERSION,

  // Query functions (legacy)
  getComponentById,
  getComponentsByCategory,
  getComponentsBySource,
  getComponentsByTokenDependency,
  getAllComponentIds,
  searchComponentsByName,
  getRegistryStats,

  // Path resolution
  resolveRawFilePath,
  resolveCodeOutputPath,
  loadRawSource,

  // Cache management
  invalidateCache,

  // NEW v4.0.0 API (preferred)
  hasV4Registry,
  getManager,
  readComponentsV4,
  readTokensV4,
  readLayoutsV4,
  findComponentByNodeId,
  findTokenByStyleId,
  getDependents,
  getDependencies,
  getUnifiedStats,

  // Re-export RegistryManager utilities
  getRegistryManager,
  clearRegistryManager
};
