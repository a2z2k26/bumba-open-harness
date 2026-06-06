/**
 * nlp-registry-integration.js
 * Registry integration for NLP-generated components
 *
 * v4.0.0 Integration:
 * - Uses RegistryManager for O(1) lookups via canonical IDs
 * - Generates v4 canonical IDs: nlp-component-{name-slug}-{timestamp}
 * - Maintains backward compatibility with legacy componentRegistry.json
 * - Supports refinement tracking and prompt history
 */

const fs = require('fs');
const path = require('path');

// Phase 2: Auto-registration support (Two-State Architecture)
const { AutoRegistrar } = require('./auto-registrar');

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
 * NLP registry entry schema
 */
const nlpEntrySchema = {
  required: ['name', 'type', 'category', 'source'],
  properties: {
    name: { type: 'string', description: 'Component name' },
    type: { type: 'string', enum: ['COMPONENT', 'COMPONENT_SET'], description: 'Component type' },
    category: { type: 'string', description: 'Component category (button, input, card, etc.)' },
    description: { type: 'string', description: 'Component description' },
    source: {
      type: 'object',
      required: ['type', 'extractedAt', 'prompt'],
      properties: {
        type: { type: 'string', const: 'nlp-prompt' },
        extractedAt: { type: 'string', format: 'date-time' },
        prompt: { type: 'string', description: 'Original NLP prompt' },
        previousVersion: { type: 'string', description: 'Previous version ID for refinements' },
        refinementFeedback: { type: 'string', description: 'Refinement feedback' },
        generationParams: { type: 'object', description: 'Generation parameters used' }
      }
    },
    tokenDependencies: { type: 'object', description: 'Token dependencies' },
    variants: { type: 'object', description: 'Component variants' },
    props: { type: 'array', description: 'Component props' },
    paths: { type: 'object', description: 'File paths' },
    metadata: { type: 'object', description: 'Metadata' }
  }
};

/**
 * Create registry entry from NLP-generated component
 * @param {Object} component - NLP-generated component
 * @param {string} sourcePath - Path to source JSON file
 * @returns {Object} Registry entry
 */
function createRegistryEntry(component, sourcePath) {
  const timestamp = new Date().toISOString();

  return {
    id: component.id || generateComponentId(component),
    name: component.name,
    type: component.type || 'COMPONENT',
    category: component.category,
    description: component.description || '',

    source: {
      type: 'nlp-prompt',
      extractedAt: component.source?.extractedAt || timestamp,
      prompt: component.source?.prompt || component.description,
      previousVersion: component.source?.previousVersion || null,
      refinementFeedback: component.source?.refinementFeedback || null,
      generationParams: component.source?.generationParams || {}
    },

    tokenDependencies: component.tokenDependencies || {
      colors: [],
      typography: [],
      spacing: [],
      effects: [],
      borderRadius: []
    },

    variants: Object.keys(component.variants || {}),
    variantDefinitions: component.variants || {},

    props: component.props || [],

    paths: {
      rawSource: sourcePath,
      codeOutput: `src/components/${pascalCase(component.name)}.tsx`,
      storyOutput: `src/components/${pascalCase(component.name)}.stories.tsx`
    },

    metadata: {
      createdAt: timestamp,
      updatedAt: timestamp,
      version: 1,
      refinementCount: 0
    }
  };
}

/**
 * Update component registry with NLP component
 * Phase 2: Now uses AutoRegistrar for Two-State Architecture consistency
 *
 * @param {Object} entry - Registry entry
 * @param {string} registryPath - Path to registry file
 * @param {Object} options - Update options
 * @returns {Promise<Object>} Update result
 */
async function updateComponentRegistry(entry, registryPath, options = {}) {
  const { overwrite = true, trackRefinement = true, projectPath } = options;

  // Determine project path from registryPath if not provided
  const effectiveProjectPath = projectPath || path.dirname(path.dirname(registryPath));

  // Phase 2: Use AutoRegistrar for Two-State Architecture
  const autoRegistrar = new AutoRegistrar({
    projectPath: effectiveProjectPath,
    autoRegisterOnImport: true,
    emitEvents: false
  });

  try {
    // Check for existing entry to track refinement history
    let existingEntry = null;
    let previousVersion = null;
    let refinementCount = 0;

    if (trackRefinement) {
      try {
        const existing = await autoRegistrar.getComponent(entry.id);
        if (existing && existing.source?.type === 'nlp') {
          existingEntry = existing;
          previousVersion = existing.id;
          refinementCount = (existing.metadata?.refinementCount || 0) + 1;
        }
      } catch (e) {
        // Component doesn't exist yet - that's fine
      }
    }

    // Build component data for AutoRegistrar
    const result = await autoRegistrar.registerComponent(
      {
        name: entry.name,
        type: entry.type || 'COMPONENT',
        category: entry.category,
        variants: entry.variants || [],
        props: entry.props || [],
        tokenDependencies: entry.tokenDependencies || {},
        interactiveStates: entry.interactiveStates || {}
      },
      {
        type: 'nlp',
        projectPath: effectiveProjectPath,
        fileKey: null,
        nodeId: null,
        figmaModifiedAt: null,
        rawDataPath: entry.paths?.rawSource || null
      }
    );

    // Preserve NLP-specific metadata (refinement tracking)
    if (result.success && result.entry) {
      result.entry.source = result.entry.source || {};
      result.entry.source.prompt = entry.source?.prompt;
      result.entry.source.previousVersion = previousVersion;
      result.entry.source.refinementFeedback = entry.source?.refinementFeedback;
      result.entry.source.generationParams = entry.source?.generationParams;

      result.entry.metadata = result.entry.metadata || {};
      result.entry.metadata.refinementCount = refinementCount;
    }

    return {
      updated: true,
      componentId: result.id,
      entry: result.entry,
      isRefinement: previousVersion !== null,
      isNew: result.isNew
    };

  } catch (error) {
    console.warn(`[nlp-registry] AutoRegistrar failed, using fallback: ${error.message}`);

    // Fallback to legacy array-based approach
    const registry = loadRegistry(registryPath);

    // Check for existing entry by name
    const existingIndex = registry.components.findIndex(c => c.name === entry.name);

    if (existingIndex >= 0) {
      const existing = registry.components[existingIndex];

      if (!overwrite) {
        return {
          updated: false,
          reason: 'exists',
          componentId: existing.id
        };
      }

      // Track refinement history
      if (trackRefinement && existing.source?.type === 'nlp-prompt') {
        entry.source.previousVersion = existing.id;
        entry.metadata.refinementCount = (existing.metadata?.refinementCount || 0) + 1;
        entry.metadata.createdAt = existing.metadata?.createdAt || entry.metadata.createdAt;
      }

      entry.metadata.updatedAt = new Date().toISOString();
      entry.metadata.version = (existing.metadata?.version || 0) + 1;

      registry.components[existingIndex] = entry;
    } else {
      registry.components.push(entry);
    }

    // Update registry metadata
    registry.metadata = registry.metadata || {};
    registry.metadata.lastUpdated = new Date().toISOString();

    if (!registry.metadata.extractionSources) {
      registry.metadata.extractionSources = [];
    }
    if (!registry.metadata.extractionSources.includes('nlp-prompt')) {
      registry.metadata.extractionSources.push('nlp-prompt');
    }

    saveRegistry(registry, registryPath);

    return {
      updated: true,
      componentId: entry.id,
      entry: entry,
      isRefinement: entry.source.previousVersion !== null
    };
  }
}

/**
 * Load registry from file
 * @param {string} registryPath - Path to registry file
 * @returns {Object} Registry object
 */
function loadRegistry(registryPath) {
  try {
    if (fs.existsSync(registryPath)) {
      return JSON.parse(fs.readFileSync(registryPath, 'utf-8'));
    }
  } catch (e) {
    console.warn(`[nlp-registry] Could not load registry: ${e.message}`);
  }

  return createEmptyRegistry();
}

/**
 * Save registry to file
 * @param {Object} registry - Registry object
 * @param {string} registryPath - Path to registry file
 */
function saveRegistry(registry, registryPath) {
  const dir = path.dirname(registryPath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  fs.writeFileSync(registryPath, JSON.stringify(registry, null, 2));
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
    components: []
  };
}

/**
 * Get all NLP-generated components from registry
 * @param {string} registryPath - Path to registry file
 * @returns {Array} NLP components
 */
function getNlpComponents(registryPath) {
  const registry = loadRegistry(registryPath);

  return registry.components.filter(c =>
    c.source && c.source.type === 'nlp-prompt'
  );
}

/**
 * Get refinement history for a component
 * @param {string} componentName - Component name
 * @param {string} registryPath - Path to registry file
 * @returns {Array} Refinement history (newest first)
 */
function getRefinementHistory(componentName, registryPath) {
  const registry = loadRegistry(registryPath);
  const history = [];

  // Find current component
  const current = registry.components.find(c => c.name === componentName);
  if (!current) {
    return history;
  }

  history.push({
    id: current.id,
    version: current.metadata?.version || 1,
    prompt: current.source?.prompt,
    extractedAt: current.source?.extractedAt,
    feedback: current.source?.refinementFeedback
  });

  // Follow previousVersion chain
  let previousId = current.source?.previousVersion;
  const visited = new Set([current.id]);

  while (previousId && !visited.has(previousId)) {
    visited.add(previousId);

    // Look in archived components or history (if stored)
    // For now, we track by ID pattern
    const versionMatch = previousId.match(/nlp-[\w-]+-(\d+)$/);
    if (versionMatch) {
      history.push({
        id: previousId,
        version: parseInt(versionMatch[1], 10) || history.length + 1
      });
    }

    // Stop if we can't find more history
    break;
  }

  return history;
}

/**
 * Remove component from registry
 * @param {string} componentName - Component name
 * @param {string} registryPath - Path to registry file
 * @returns {Object} Removal result
 */
function removeFromRegistry(componentName, registryPath) {
  const registry = loadRegistry(registryPath);

  const index = registry.components.findIndex(c => c.name === componentName);

  if (index < 0) {
    return {
      removed: false,
      reason: 'not_found'
    };
  }

  const removed = registry.components.splice(index, 1)[0];

  registry.metadata.lastUpdated = new Date().toISOString();
  saveRegistry(registry, registryPath);

  return {
    removed: true,
    componentId: removed.id,
    component: removed
  };
}

/**
 * Get statistics for NLP components
 * @param {string} registryPath - Path to registry file
 * @returns {Object} Statistics
 */
function getNlpStats(registryPath) {
  const nlpComponents = getNlpComponents(registryPath);

  const categoryCount = {};
  const variantCount = {};
  let totalRefinements = 0;
  let totalVariants = 0;
  let totalProps = 0;

  nlpComponents.forEach(component => {
    // Count by category
    const category = component.category || 'unknown';
    categoryCount[category] = (categoryCount[category] || 0) + 1;

    // Count variants
    const variants = Array.isArray(component.variants) ? component.variants : Object.keys(component.variants || {});
    totalVariants += variants.length;
    variants.forEach(v => {
      variantCount[v] = (variantCount[v] || 0) + 1;
    });

    // Count props
    totalProps += (component.props || []).length;

    // Count refinements
    totalRefinements += component.metadata?.refinementCount || 0;
  });

  return {
    totalComponents: nlpComponents.length,
    byCategory: categoryCount,
    byVariant: variantCount,
    averageVariantsPerComponent: nlpComponents.length > 0
      ? (totalVariants / nlpComponents.length).toFixed(2)
      : 0,
    averagePropsPerComponent: nlpComponents.length > 0
      ? (totalProps / nlpComponents.length).toFixed(2)
      : 0,
    totalRefinements: totalRefinements
  };
}

/**
 * Find component by name
 * @param {string} componentName - Component name
 * @param {string} registryPath - Path to registry file
 * @returns {Object|null} Component or null
 */
function findByName(componentName, registryPath) {
  const registry = loadRegistry(registryPath);
  return registry.components.find(c =>
    c.name.toLowerCase() === componentName.toLowerCase()
  ) || null;
}

/**
 * Find components by category
 * @param {string} category - Category name
 * @param {string} registryPath - Path to registry file
 * @returns {Array} Matching components
 */
function findByCategory(category, registryPath) {
  const registry = loadRegistry(registryPath);
  return registry.components.filter(c =>
    c.category === category && c.source?.type === 'nlp-prompt'
  );
}

/**
 * Validate registry entry against schema
 * @param {Object} entry - Entry to validate
 * @returns {Object} Validation result
 */
function validateEntry(entry) {
  const errors = [];

  // Check required fields
  nlpEntrySchema.required.forEach(field => {
    if (!entry[field]) {
      errors.push(`Missing required field: ${field}`);
    }
  });

  // Check source
  if (entry.source) {
    if (entry.source.type !== 'nlp-prompt') {
      errors.push(`Invalid source type: ${entry.source.type} (expected 'nlp-prompt')`);
    }
    if (!entry.source.extractedAt) {
      errors.push('Missing source.extractedAt');
    }
    if (!entry.source.prompt) {
      errors.push('Missing source.prompt');
    }
  }

  return {
    valid: errors.length === 0,
    errors
  };
}

/**
 * Generate component ID
 * @param {Object} component - Component data
 * @returns {string} Component ID
 */
function generateComponentId(component) {
  const baseName = sanitizeFileName(component.name);
  const timestamp = Date.now();
  return `nlp-${baseName}-${timestamp}`;
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
  // Split on spaces, dashes, underscores, and camelCase boundaries
  return name
    .replace(/([a-z])([A-Z])/g, '$1 $2')  // Split camelCase
    .split(/[\s-_]+/)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join('');
}

/**
 * Format registry update result
 * @param {Object} result - Update result
 * @returns {string} Formatted output
 */
function formatResult(result) {
  if (result.updated) {
    const lines = [
      `✓ Registry updated: ${result.componentId}`,
      `  Version: ${result.entry?.metadata?.version || 1}`
    ];
    if (result.isRefinement) {
      lines.push(`  Refinement of: ${result.entry?.source?.previousVersion}`);
    }
    return lines.join('\n');
  }

  return `✗ Registry not updated: ${result.reason}`;
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
 * Generate v4.0.0 canonical ID for NLP component
 * @param {Object} component - Component data
 * @returns {string} Canonical ID
 */
function generateV4CanonicalId(component) {
  const baseName = sanitizeFileName(component.name);
  const timestamp = Date.now();
  return `nlp-component-${baseName}-${timestamp}`;
}

/**
 * Update registry using v4.0.0 RegistryManager
 * @param {Object} entry - Registry entry
 * @param {string} projectPath - Project path
 * @param {Object} options - Options
 * @returns {Object|null} Result or null if v4 not available
 */
function updateRegistryV4(entry, projectPath, options = {}) {
  const rm = getRegistryManager(projectPath);
  if (!rm) return null;

  const { overwrite = true, trackRefinement = true } = options;

  // Generate or use existing canonical ID
  const canonicalId = entry.id || generateV4CanonicalId(entry);

  // Check for existing by name (NLP components may not have stable IDs)
  let existing = rm.findById(canonicalId);
  if (!existing) {
    // Search by name for NLP components
    const nlpComponents = rm.findBySource('nlp');
    existing = nlpComponents.find(c =>
      c.name.toLowerCase() === entry.name.toLowerCase()
    );
  }

  if (existing && !overwrite) {
    return { updated: false, reason: 'exists', componentId: existing.id };
  }

  // Track refinement history
  let previousVersion = null;
  let refinementCount = 0;

  if (trackRefinement && existing && existing.source?.type === 'nlp') {
    previousVersion = existing.id;
    refinementCount = (existing.metadata?.refinementCount || 0) + 1;
  }

  // Create v4 entry
  const v4Entry = {
    id: existing?.id || canonicalId,
    name: entry.name,
    type: entry.type || 'COMPONENT',
    category: entry.category,
    description: entry.description || '',

    source: {
      type: 'nlp',
      extractedAt: entry.source?.extractedAt || new Date().toISOString(),
      prompt: entry.source?.prompt || entry.description,
      previousVersion: previousVersion,
      refinementFeedback: entry.source?.refinementFeedback || null,
      generationParams: entry.source?.generationParams || {}
    },

    tokenDependencies: entry.tokenDependencies || {
      colors: [],
      typography: [],
      spacing: [],
      effects: [],
      borderRadius: []
    },

    variants: entry.variants || [],
    variantDefinitions: entry.variantDefinitions || {},
    props: entry.props || [],

    paths: entry.paths || {
      rawSource: `.design/source/components/${sanitizeFileName(entry.name)}.json`,
      codeOutput: `src/components/${pascalCase(entry.name)}.tsx`,
      storyOutput: `src/components/${pascalCase(entry.name)}.stories.tsx`
    },

    metadata: {
      createdAt: existing?.metadata?.createdAt || new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      version: (existing?.metadata?.version || 0) + 1,
      refinementCount: refinementCount
    }
  };

  // Use RegistryManager to add/update
  if (existing) {
    rm.updateEntry(existing.id, v4Entry);
  } else {
    rm.addEntry(v4Entry);
  }

  rm.saveIndex();

  return {
    updated: true,
    componentId: v4Entry.id,
    entry: v4Entry,
    isRefinement: previousVersion !== null,
    usedV4: true
  };
}

/**
 * Find NLP component by canonical ID using v4 O(1) lookup
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
 * Find NLP component by name using v4 registry
 * @param {string} componentName - Component name
 * @param {string} projectPath - Project path
 * @returns {Object|null} Component entry
 */
function findByNameV4(componentName, projectPath) {
  const rm = getRegistryManager(projectPath);
  if (!rm) return null;

  const nlpComponents = rm.findBySource('nlp');
  return nlpComponents.find(c =>
    c.name.toLowerCase() === componentName.toLowerCase()
  ) || null;
}

/**
 * Get all NLP components using v4 registry
 * @param {string} projectPath - Project path
 * @returns {Array} NLP components
 */
function getNlpComponentsV4(projectPath) {
  const rm = getRegistryManager(projectPath);
  if (!rm) return [];

  return rm.findBySource('nlp');
}

/**
 * Get refinement history using v4 registry
 * @param {string} componentName - Component name
 * @param {string} projectPath - Project path
 * @returns {Array} Refinement history
 */
function getRefinementHistoryV4(componentName, projectPath) {
  const rm = getRegistryManager(projectPath);
  if (!rm) return [];

  const component = findByNameV4(componentName, projectPath);
  if (!component) return [];

  const history = [{
    id: component.id,
    version: component.metadata?.version || 1,
    prompt: component.source?.prompt,
    extractedAt: component.source?.extractedAt,
    feedback: component.source?.refinementFeedback
  }];

  // Follow previousVersion chain via dependency graph
  let previousId = component.source?.previousVersion;
  const visited = new Set([component.id]);

  while (previousId && !visited.has(previousId)) {
    visited.add(previousId);
    const prev = rm.findById(previousId);
    if (prev) {
      history.push({
        id: prev.id,
        version: prev.metadata?.version || history.length + 1,
        prompt: prev.source?.prompt,
        extractedAt: prev.source?.extractedAt,
        feedback: prev.source?.refinementFeedback
      });
      previousId = prev.source?.previousVersion;
    } else {
      break;
    }
  }

  return history;
}

/**
 * Get v4 registry statistics for NLP components
 * @param {string} projectPath - Project path
 * @returns {Object} Statistics
 */
function getV4Stats(projectPath) {
  const rm = getRegistryManager(projectPath);
  if (!rm) return null;

  const stats = rm.getStats();
  const nlpComponents = rm.findBySource('nlp');

  const categoryCount = {};
  let totalRefinements = 0;
  let totalVariants = 0;
  let totalProps = 0;

  nlpComponents.forEach(component => {
    const category = component.category || 'unknown';
    categoryCount[category] = (categoryCount[category] || 0) + 1;

    const variants = Array.isArray(component.variants)
      ? component.variants
      : Object.keys(component.variants || {});
    totalVariants += variants.length;
    totalProps += (component.props || []).length;
    totalRefinements += component.metadata?.refinementCount || 0;
  });

  return {
    ...stats,
    nlpComponents: nlpComponents.length,
    byCategory: categoryCount,
    averageVariantsPerComponent: nlpComponents.length > 0
      ? (totalVariants / nlpComponents.length).toFixed(2)
      : 0,
    averagePropsPerComponent: nlpComponents.length > 0
      ? (totalProps / nlpComponents.length).toFixed(2)
      : 0,
    totalRefinements: totalRefinements,
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
  // Schema
  nlpEntrySchema,

  // Core functions
  createRegistryEntry,
  updateComponentRegistry,
  loadRegistry,
  saveRegistry,
  createEmptyRegistry,

  // Query functions
  getNlpComponents,
  getRefinementHistory,
  findByName,
  findByCategory,

  // Management functions
  removeFromRegistry,
  getNlpStats,

  // Validation
  validateEntry,

  // Utilities
  generateComponentId,
  sanitizeFileName,
  pascalCase,
  formatResult,

  // v4.0.0 exports
  hasV4Registry,
  getRegistryManager,
  generateV4CanonicalId,
  updateRegistryV4,
  findByIdV4,
  findByNameV4,
  getNlpComponentsV4,
  getRefinementHistoryV4,
  getV4Stats,
  invalidateV4Cache
};
