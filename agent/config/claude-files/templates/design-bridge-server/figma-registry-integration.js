/**
 * figma-registry-integration.js
 * Update component registry with Figma MCP extractions
 *
 * v4.0.0 Integration:
 * - Uses RegistryManager for O(1) lookups via canonical IDs
 * - Generates v4 canonical IDs: figma-component-{name-slug}-{nodeId}
 * - Maintains backward compatibility with legacy componentRegistry.json
 * - Supports dependency tracking via registry-index.json
 */

const fs = require('fs');
const path = require('path');

// Lazy-load RegistryManager to avoid circular dependencies (v4.0.0)
let _registryManagerModule = null;
function getRegistryManagerModule() {
  if (!_registryManagerModule) {
    try {
      _registryManagerModule = require('./registry-manager');
    } catch (e) {
      _registryManagerModule = null;
    }
  }
  return _registryManagerModule;
}

// v4.0.0 module-level cache
let _registryManager = null;
let _v4Available = null;

/**
 * Add or update a component in the registry
 * @param {string} registryPath - Path to componentRegistry.json
 * @param {Object} component - Extracted component data
 * @param {Object} options - Update options
 * @returns {Object} Update result
 */
function updateRegistry(registryPath, component, options = {}) {
  const {
    fileKey,
    originalUrl,
    overwrite = false
  } = options;

  // Read existing registry or create new
  let registry;
  try {
    registry = JSON.parse(fs.readFileSync(registryPath, 'utf-8'));
  } catch (e) {
    registry = createEmptyRegistry();
  }

  // Generate component ID
  const componentId = generateComponentId(component);

  // Check for existing entry
  const existing = registry.components[componentId];
  if (existing && !overwrite) {
    // Check if it's from a different source
    if (existing.source?.type !== 'figma-mcp') {
      return { updated: false, reason: 'exists_different_source', componentId };
    }
  }

  // Create registry entry
  const entry = {
    name: component.name,
    figmaId: component.figmaId || component.id,
    type: component.type,
    category: inferCategory(component),
    description: component.description || '',

    source: {
      type: 'figma-mcp',
      fileKey: fileKey,
      nodeId: component.figmaId || component.id,
      extractedAt: new Date().toISOString(),
      originalUrl: originalUrl
    },

    tokenDependencies: component.tokenDependencies || {
      colors: [],
      typography: [],
      spacing: [],
      effects: [],
      borderRadius: []
    },

    interactiveStates: component.interactiveStates || {},

    variants: component.variants || component.variantProperties || [],

    props: component.props || [],

    paths: {
      rawSource: `.design/source/components/${sanitizeFileName(component.name)}.json`,
      codeOutput: `src/components/${pascalCase(component.name)}.tsx`,
      storyOutput: `src/components/${pascalCase(component.name)}.stories.tsx`
    },

    metadata: {
      createdAt: existing?.metadata?.createdAt || new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      version: (existing?.metadata?.version || 0) + 1
    }
  };

  // Update registry
  registry.components[componentId] = entry;

  // Update registry metadata
  registry.metadata = registry.metadata || {};
  registry.metadata.lastUpdated = new Date().toISOString();

  // Track extraction sources
  if (!registry.metadata.extractionSources) {
    registry.metadata.extractionSources = [];
  }
  if (!registry.metadata.extractionSources.includes('figma-mcp')) {
    registry.metadata.extractionSources.push('figma-mcp');
  }

  // Write updated registry
  fs.writeFileSync(registryPath, JSON.stringify(registry, null, 2));

  return {
    updated: true,
    componentId: componentId,
    entry: entry
  };
}

/**
 * Create empty registry structure
 * @returns {Object} Empty registry
 */
function createEmptyRegistry() {
  return {
    version: '2.0.0',
    metadata: {
      lastUpdated: new Date().toISOString(),
      extractionSources: []
    },
    components: {}
  };
}

/**
 * Generate unique component ID
 * @param {Object} component - Component data
 * @returns {string} Component ID
 */
function generateComponentId(component) {
  const baseName = sanitizeFileName(component.name);
  const nodeId = (component.figmaId || component.id || '').replace(':', '-');
  return `figma-mcp-${baseName}-${nodeId}`;
}

/**
 * Sanitize file name
 * @param {string} name - Input name
 * @returns {string} Sanitized name
 */
function sanitizeFileName(name) {
  return name
    .toLowerCase()
    .replace(/\s+/g, '-')
    .replace(/[^a-z0-9-]/g, '')
    .replace(/-+/g, '-');
}

/**
 * Convert to PascalCase
 * @param {string} name - Input name
 * @returns {string} PascalCase name
 */
function pascalCase(name) {
  return name
    .split(/[\s-_]+/)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join('');
}

/**
 * Infer component category from name/type
 * @param {Object} component - Component data
 * @returns {string} Category name
 */
function inferCategory(component) {
  const name = component.name.toLowerCase();

  const categories = {
    button: ['button', 'btn', 'cta'],
    input: ['input', 'textfield', 'text-field', 'textarea'],
    card: ['card', 'tile'],
    modal: ['modal', 'dialog', 'popup'],
    navigation: ['nav', 'navigation', 'menu', 'header', 'footer'],
    icon: ['icon', 'svg'],
    avatar: ['avatar', 'profile'],
    badge: ['badge', 'tag', 'chip'],
    list: ['list', 'item'],
    form: ['form', 'field']
  };

  for (const [category, keywords] of Object.entries(categories)) {
    if (keywords.some(kw => name.includes(kw))) {
      return category;
    }
  }

  return 'component';
}

/**
 * Check for duplicate components
 * @param {Object} registry - Registry object
 * @param {Object} component - Component to check
 * @returns {Array} Array of matches
 */
function findDuplicates(registry, component) {
  const matches = [];
  const componentName = component.name || '';
  const componentFigmaId = component.figmaId || component.id;

  for (const [id, entry] of Object.entries(registry.components || {})) {
    // Same name
    if (componentName && entry.name && entry.name.toLowerCase() === componentName.toLowerCase()) {
      matches.push({ id, entry, reason: 'same_name' });
    }
    // Same Figma ID
    if (componentFigmaId && entry.figmaId === componentFigmaId) {
      matches.push({ id, entry, reason: 'same_figma_id' });
    }
  }

  return matches;
}

/**
 * Batch update multiple components
 * @param {string} registryPath - Path to registry
 * @param {Array} components - Array of components
 * @param {Object} options - Update options
 * @returns {Array} Array of results
 */
function batchUpdateRegistry(registryPath, components, options = {}) {
  const results = [];

  for (const component of components) {
    const result = updateRegistry(registryPath, component, options);
    results.push({
      name: component.name,
      ...result
    });
  }

  return results;
}

/**
 * Format registry update result for display
 * @param {Object|Array} result - Update result(s)
 * @returns {string} Formatted output
 */
function formatRegistryResult(result) {
  if (Array.isArray(result)) {
    const updated = result.filter(r => r.updated).length;
    const skipped = result.filter(r => !r.updated).length;

    const lines = [
      `Registry Update Complete`,
      `========================`,
      `Updated: ${updated}`,
      `Skipped: ${skipped}`,
      ``
    ];

    result.forEach(r => {
      const status = r.updated ? '[UPDATED]' : '[SKIPPED]';
      lines.push(`${status} ${r.name}`);
      if (!r.updated && r.reason) {
        lines.push(`         Reason: ${r.reason}`);
      }
    });

    return lines.join('\n');
  }

  // Single result
  if (result.updated) {
    return `Registry updated: ${result.componentId}\n` +
           `  Category: ${result.entry.category}\n` +
           `  Type: ${result.entry.type}\n` +
           `  Version: ${result.entry.metadata.version}`;
  }

  return `Registry not updated: ${result.reason}`;
}

// ═══════════════════════════════════════════════════════════════════════════
// v4.0.0 Registry Integration Methods
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Check if v4.0.0 registry is available
 * @param {string} projectPath - Project path
 * @returns {boolean} True if v4 registry exists
 */
function hasV4Registry(projectPath) {
  if (_v4Available !== null) return _v4Available;

  const rmModule = getRegistryManagerModule();
  if (!rmModule) {
    _v4Available = false;
    return false;
  }

  const indexPath = path.join(projectPath, '.design', 'registry-index.json');
  _v4Available = fs.existsSync(indexPath);
  return _v4Available;
}

/**
 * Get or create RegistryManager instance
 * @param {string} projectPath - Project path
 * @returns {Object|null} RegistryManager instance
 */
function getRegistryManager(projectPath) {
  if (_registryManager) return _registryManager;

  const rmModule = getRegistryManagerModule();
  if (!rmModule || !hasV4Registry(projectPath)) return null;

  try {
    _registryManager = rmModule.getRegistryManager(projectPath);
    return _registryManager;
  } catch (e) {
    return null;
  }
}

/**
 * Generate v4.0.0 canonical ID for Figma component
 * @param {Object} component - Component data
 * @returns {string} Canonical ID
 */
function generateV4CanonicalId(component) {
  const baseName = sanitizeFileName(component.name);
  const nodeId = (component.figmaId || component.id || '').replace(':', '-');
  return `figma-component-${baseName}-${nodeId}`;
}

/**
 * Update registry using v4.0.0 RegistryManager
 * @param {string} projectPath - Project path
 * @param {Object} component - Component data
 * @param {Object} options - Options
 * @returns {Object|null} Result or null if v4 not available
 */
function updateRegistryV4(projectPath, component, options = {}) {
  const rm = getRegistryManager(projectPath);
  if (!rm) return null;

  const { fileKey, originalUrl, overwrite = false } = options;

  const canonicalId = generateV4CanonicalId(component);
  const nodeId = component.figmaId || component.id;

  // Check for existing via O(1) lookup
  const existing = rm.findById(canonicalId) || rm.findByNodeId(nodeId);

  if (existing && !overwrite) {
    if (existing.source?.type !== 'figma') {
      return { updated: false, reason: 'exists_different_source', componentId: existing.id };
    }
  }

  // Create v4 entry
  const entry = {
    id: canonicalId,
    name: component.name,
    type: component.type || 'COMPONENT',
    category: inferCategory(component),
    description: component.description || '',

    source: {
      type: 'figma',
      fileKey: fileKey,
      nodeId: nodeId,
      extractedAt: new Date().toISOString(),
      originalUrl: originalUrl
    },

    tokenDependencies: component.tokenDependencies || {
      colors: [],
      typography: [],
      spacing: [],
      effects: [],
      borderRadius: []
    },

    interactiveStates: component.interactiveStates || {},
    variants: component.variants || component.variantProperties || [],
    props: component.props || [],

    paths: {
      rawSource: `.design/source/components/${sanitizeFileName(component.name)}.json`,
      codeOutput: `src/components/${pascalCase(component.name)}.tsx`,
      storyOutput: `src/components/${pascalCase(component.name)}.stories.tsx`
    },

    metadata: {
      createdAt: existing?.metadata?.createdAt || new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      version: (existing?.metadata?.version || 0) + 1
    }
  };

  // Use RegistryManager to add/update
  if (existing) {
    rm.updateEntry(canonicalId, entry);
  } else {
    rm.addEntry(entry);
  }

  rm.saveIndex();

  return {
    updated: true,
    componentId: canonicalId,
    entry: entry,
    usedV4: true
  };
}

/**
 * Find Figma component by node ID using v4 O(1) lookup
 * @param {string} projectPath - Project path
 * @param {string} nodeId - Figma node ID
 * @returns {Object|null} Component entry
 */
function findByNodeIdV4(projectPath, nodeId) {
  const rm = getRegistryManager(projectPath);
  if (!rm) return null;
  return rm.findByNodeId(nodeId);
}

/**
 * Find Figma component by canonical ID using v4 O(1) lookup
 * @param {string} projectPath - Project path
 * @param {string} canonicalId - Canonical ID
 * @returns {Object|null} Component entry
 */
function findByIdV4(projectPath, canonicalId) {
  const rm = getRegistryManager(projectPath);
  if (!rm) return null;
  return rm.findById(canonicalId);
}

/**
 * Get all Figma components using v4 registry
 * @param {string} projectPath - Project path
 * @returns {Array} Figma components
 */
function getFigmaComponentsV4(projectPath) {
  const rm = getRegistryManager(projectPath);
  if (!rm) return [];

  return rm.findBySource('figma');
}

/**
 * Get v4 registry statistics for Figma components
 * @param {string} projectPath - Project path
 * @returns {Object} Statistics
 */
function getV4Stats(projectPath) {
  const rm = getRegistryManager(projectPath);
  if (!rm) return null;

  const stats = rm.getStats();
  return {
    ...stats,
    figmaComponents: rm.findBySource('figma').length,
    v4Available: true
  };
}

/**
 * Invalidate v4 cache
 */
function invalidateV4Cache() {
  _registryManager = null;
  _v4Available = null;
}

module.exports = {
  updateRegistry,
  batchUpdateRegistry,
  createEmptyRegistry,
  generateComponentId,
  findDuplicates,
  inferCategory,
  sanitizeFileName,
  pascalCase,
  formatRegistryResult,

  // v4.0.0 exports
  hasV4Registry,
  getRegistryManager,
  generateV4CanonicalId,
  updateRegistryV4,
  findByNodeIdV4,
  findByIdV4,
  getFigmaComponentsV4,
  getV4Stats,
  invalidateV4Cache
};
