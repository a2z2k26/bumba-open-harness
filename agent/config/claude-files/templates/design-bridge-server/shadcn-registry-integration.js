/**
 * shadcn-registry-integration.js
 * Manage componentRegistry.json integration for ShadCN components
 *
 * v4.0.0 Integration:
 * - Uses RegistryManager for O(1) lookups via canonical IDs
 * - Generates v4 canonical IDs: shadcn-component-{name-slug}
 * - Maintains backward compatibility with legacy componentRegistry.json
 * - Supports dependency tracking and cross-source linking
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
 * Default registry structure
 */
const DEFAULT_REGISTRY = {
  version: '2.0.0',
  components: {},
  metadata: {
    createdAt: new Date().toISOString(),
    lastUpdated: new Date().toISOString(),
    extractionSources: []
  }
};

/**
 * Load or create component registry
 * @param {string} projectRoot - Project root directory
 * @returns {Object} Registry object
 */
function loadRegistry(projectRoot) {
  const registryPath = getRegistryPath(projectRoot);

  if (fs.existsSync(registryPath)) {
    try {
      const content = fs.readFileSync(registryPath, 'utf-8');
      return JSON.parse(content);
    } catch (error) {
      console.warn(`Could not parse registry: ${error.message}`);
      return { ...DEFAULT_REGISTRY };
    }
  }

  return { ...DEFAULT_REGISTRY };
}

/**
 * Save registry to disk
 * @param {string} projectRoot - Project root directory
 * @param {Object} registry - Registry object
 */
function saveRegistry(projectRoot, registry) {
  const registryPath = getRegistryPath(projectRoot);
  const designDir = path.dirname(registryPath);

  // Ensure directory exists
  if (!fs.existsSync(designDir)) {
    fs.mkdirSync(designDir, { recursive: true });
  }

  // Update metadata
  registry.metadata = registry.metadata || {};
  registry.metadata.lastUpdated = new Date().toISOString();

  fs.writeFileSync(registryPath, JSON.stringify(registry, null, 2));
}

/**
 * Get registry file path
 * @param {string} projectRoot - Project root
 * @returns {string} Registry path
 */
function getRegistryPath(projectRoot) {
  return path.join(projectRoot, '.design', 'componentRegistry.json');
}

/**
 * Add or update a ShadCN component in the registry
 * @param {Object} options - Options
 * @param {string} options.projectRoot - Project root
 * @param {Object} options.component - Component data from extraction
 * @param {Object} options.tokens - Token dependencies
 * @param {Array} options.variants - Variants
 * @param {Array} options.examples - Examples
 * @returns {Object} Updated registry entry
 */
function addShadcnComponent(options) {
  const {
    projectRoot,
    component,
    tokens = {},
    variants = [],
    examples = [],
    dependencies = []
  } = options;

  const registry = loadRegistry(projectRoot);
  const componentId = generateComponentId(component.name, 'shadcn');

  // Check for existing entry
  const existing = registry.components[componentId];

  const entry = {
    name: component.name,
    type: component.type || 'COMPONENT',
    category: component.category || 'component',

    source: {
      type: 'shadcn',
      registry: component.source?.registry || '@shadcn',
      extractedAt: new Date().toISOString(),
      ...(existing?.source?.firstExtractedAt && {
        firstExtractedAt: existing.source.firstExtractedAt
      }),
      ...(!existing && {
        firstExtractedAt: new Date().toISOString()
      })
    },

    variants: variants.map(v => ({
      name: v.name,
      type: v.type || 'variant',
      default: v.default,
      options: v.options
    })),

    tokenDependencies: {
      colors: tokens.colors?.length || 0,
      typography: tokens.typography?.length || 0,
      spacing: tokens.spacing?.length || 0,
      effects: tokens.effects?.length || 0,
      borderRadius: tokens.borderRadius?.length || 0,
      // Keep full token lists if under threshold
      ...(tokens.colors?.length <= 20 && { colorTokens: tokens.colors }),
      ...(tokens.cssVariables?.length > 0 && { cssVariables: tokens.cssVariables })
    },

    dependencies: dependencies,
    exampleCount: examples.length,

    paths: {
      rawSource: `.design/source/components/${sanitizeFileName(component.name)}.json`,
      codeOutput: `src/components/${pascalCase(component.name)}.tsx`,
      storyOutput: `src/components/${pascalCase(component.name)}.stories.tsx`
    },

    metadata: {
      version: (existing?.metadata?.version || 0) + 1,
      createdAt: existing?.metadata?.createdAt || new Date().toISOString(),
      updatedAt: new Date().toISOString()
    }
  };

  registry.components[componentId] = entry;

  // Update extraction sources
  if (!registry.metadata.extractionSources) {
    registry.metadata.extractionSources = [];
  }
  if (!registry.metadata.extractionSources.includes('shadcn')) {
    registry.metadata.extractionSources.push('shadcn');
  }

  saveRegistry(projectRoot, registry);

  return {
    id: componentId,
    entry: entry,
    isUpdate: !!existing
  };
}

/**
 * Remove a component from the registry
 * @param {string} projectRoot - Project root
 * @param {string} componentId - Component ID
 * @returns {boolean} Success
 */
function removeComponent(projectRoot, componentId) {
  const registry = loadRegistry(projectRoot);

  if (registry.components[componentId]) {
    delete registry.components[componentId];
    saveRegistry(projectRoot, registry);
    return true;
  }

  return false;
}

/**
 * Get component by ID
 * @param {string} projectRoot - Project root
 * @param {string} componentId - Component ID
 * @returns {Object|null} Component entry
 */
function getComponent(projectRoot, componentId) {
  const registry = loadRegistry(projectRoot);
  return registry.components[componentId] || null;
}

/**
 * Query components by criteria
 * @param {string} projectRoot - Project root
 * @param {Object} query - Query criteria
 * @returns {Array} Matching components
 */
function queryComponents(projectRoot, query = {}) {
  const registry = loadRegistry(projectRoot);
  let results = Object.entries(registry.components);

  // Filter by source type
  if (query.sourceType) {
    results = results.filter(([_, comp]) =>
      comp.source?.type === query.sourceType
    );
  }

  // Filter by category
  if (query.category) {
    results = results.filter(([_, comp]) =>
      comp.category === query.category
    );
  }

  // Filter by name pattern
  if (query.namePattern) {
    const pattern = new RegExp(query.namePattern, 'i');
    results = results.filter(([_, comp]) =>
      pattern.test(comp.name)
    );
  }

  // Filter by having variants
  if (query.hasVariants) {
    results = results.filter(([_, comp]) =>
      comp.variants && comp.variants.length > 0
    );
  }

  // Filter by having specific variant
  if (query.variantName) {
    results = results.filter(([_, comp]) =>
      comp.variants?.some(v => v.name === query.variantName)
    );
  }

  return results.map(([id, comp]) => ({
    id,
    ...comp
  }));
}

/**
 * Get all ShadCN components
 * @param {string} projectRoot - Project root
 * @returns {Array} ShadCN components
 */
function getShadcnComponents(projectRoot) {
  return queryComponents(projectRoot, { sourceType: 'shadcn' });
}

/**
 * Get registry statistics
 * @param {string} projectRoot - Project root
 * @returns {Object} Statistics
 */
function getRegistryStats(projectRoot) {
  const registry = loadRegistry(projectRoot);
  const components = Object.values(registry.components);

  const stats = {
    totalComponents: components.length,
    bySource: {},
    byCategory: {},
    totalVariants: 0,
    totalTokenDependencies: 0,
    lastUpdated: registry.metadata?.lastUpdated
  };

  for (const comp of components) {
    // By source
    const source = comp.source?.type || 'unknown';
    stats.bySource[source] = (stats.bySource[source] || 0) + 1;

    // By category
    const category = comp.category || 'unknown';
    stats.byCategory[category] = (stats.byCategory[category] || 0) + 1;

    // Variants
    stats.totalVariants += comp.variants?.length || 0;

    // Token dependencies
    const tokens = comp.tokenDependencies || {};
    stats.totalTokenDependencies += (
      (tokens.colors || 0) +
      (tokens.typography || 0) +
      (tokens.spacing || 0) +
      (tokens.effects || 0)
    );
  }

  return stats;
}

/**
 * Merge Figma and ShadCN components
 * Creates mappings between similar components from different sources
 * @param {string} projectRoot - Project root
 * @returns {Object} Merge analysis
 */
function analyzeComponentMerge(projectRoot) {
  const registry = loadRegistry(projectRoot);
  const components = Object.entries(registry.components);

  const shadcn = components.filter(([_, c]) => c.source?.type === 'shadcn');
  const figma = components.filter(([_, c]) => c.source?.type?.includes('figma'));

  const potentialMerges = [];

  // Look for similar names
  for (const [shadcnId, shadcnComp] of shadcn) {
    for (const [figmaId, figmaComp] of figma) {
      const similarity = calculateNameSimilarity(
        shadcnComp.name.toLowerCase(),
        figmaComp.name.toLowerCase()
      );

      if (similarity > 0.7) {
        potentialMerges.push({
          shadcn: { id: shadcnId, name: shadcnComp.name },
          figma: { id: figmaId, name: figmaComp.name },
          similarity: similarity,
          recommendation: similarity > 0.9 ? 'auto-merge' : 'review'
        });
      }
    }
  }

  return {
    shadcnCount: shadcn.length,
    figmaCount: figma.length,
    potentialMerges: potentialMerges,
    totalPotentialMerges: potentialMerges.length
  };
}

/**
 * Link a ShadCN component to a Figma component
 * @param {string} projectRoot - Project root
 * @param {string} shadcnId - ShadCN component ID
 * @param {string} figmaId - Figma component ID
 * @returns {Object} Updated entry
 */
function linkComponents(projectRoot, shadcnId, figmaId) {
  const registry = loadRegistry(projectRoot);

  if (!registry.components[shadcnId]) {
    throw new Error(`ShadCN component not found: ${shadcnId}`);
  }

  if (!registry.components[figmaId]) {
    throw new Error(`Figma component not found: ${figmaId}`);
  }

  // Add links to both components
  registry.components[shadcnId].linkedTo = registry.components[shadcnId].linkedTo || [];
  if (!registry.components[shadcnId].linkedTo.includes(figmaId)) {
    registry.components[shadcnId].linkedTo.push(figmaId);
  }

  registry.components[figmaId].linkedTo = registry.components[figmaId].linkedTo || [];
  if (!registry.components[figmaId].linkedTo.includes(shadcnId)) {
    registry.components[figmaId].linkedTo.push(shadcnId);
  }

  saveRegistry(projectRoot, registry);

  return {
    shadcn: registry.components[shadcnId],
    figma: registry.components[figmaId]
  };
}

/**
 * Export registry to various formats
 * @param {string} projectRoot - Project root
 * @param {string} format - Export format (json, csv, markdown)
 * @returns {string} Exported content
 */
function exportRegistry(projectRoot, format = 'json') {
  const registry = loadRegistry(projectRoot);

  switch (format) {
    case 'csv':
      return exportToCsv(registry);
    case 'markdown':
      return exportToMarkdown(registry);
    case 'json':
    default:
      return JSON.stringify(registry, null, 2);
  }
}

/**
 * Export to CSV format
 * @param {Object} registry - Registry object
 * @returns {string} CSV content
 */
function exportToCsv(registry) {
  const headers = ['ID', 'Name', 'Type', 'Category', 'Source', 'Variants', 'Colors', 'Typography'];
  const rows = [headers.join(',')];

  for (const [id, comp] of Object.entries(registry.components)) {
    rows.push([
      id,
      `"${comp.name}"`,
      comp.type,
      comp.category,
      comp.source?.type,
      comp.variants?.length || 0,
      comp.tokenDependencies?.colors || 0,
      comp.tokenDependencies?.typography || 0
    ].join(','));
  }

  return rows.join('\n');
}

/**
 * Export to Markdown format
 * @param {Object} registry - Registry object
 * @returns {string} Markdown content
 */
function exportToMarkdown(registry) {
  const lines = [
    '# Component Registry',
    '',
    `Last Updated: ${registry.metadata?.lastUpdated || 'N/A'}`,
    '',
    '## Components',
    '',
    '| Name | Type | Category | Source | Variants |',
    '|------|------|----------|--------|----------|'
  ];

  for (const [id, comp] of Object.entries(registry.components)) {
    lines.push(
      `| ${comp.name} | ${comp.type} | ${comp.category} | ${comp.source?.type} | ${comp.variants?.length || 0} |`
    );
  }

  return lines.join('\n');
}

// Utility functions
function generateComponentId(name, source) {
  return `${source}-${sanitizeFileName(name)}`;
}

function sanitizeFileName(name) {
  return name
    .toLowerCase()
    .replace(/\s+/g, '-')
    .replace(/[^a-z0-9-]/g, '')
    .replace(/-+/g, '-');
}

function pascalCase(name) {
  return name
    .split(/[\s-_]+/)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join('');
}

function calculateNameSimilarity(str1, str2) {
  // Simple Levenshtein-based similarity
  const longer = str1.length > str2.length ? str1 : str2;
  const shorter = str1.length > str2.length ? str2 : str1;

  if (longer.length === 0) return 1.0;

  const editDistance = levenshteinDistance(longer, shorter);
  return (longer.length - editDistance) / longer.length;
}

function levenshteinDistance(str1, str2) {
  const matrix = [];

  for (let i = 0; i <= str1.length; i++) {
    matrix[i] = [i];
  }

  for (let j = 0; j <= str2.length; j++) {
    matrix[0][j] = j;
  }

  for (let i = 1; i <= str1.length; i++) {
    for (let j = 1; j <= str2.length; j++) {
      if (str1[i - 1] === str2[j - 1]) {
        matrix[i][j] = matrix[i - 1][j - 1];
      } else {
        matrix[i][j] = Math.min(
          matrix[i - 1][j - 1] + 1,
          matrix[i][j - 1] + 1,
          matrix[i - 1][j] + 1
        );
      }
    }
  }

  return matrix[str1.length][str2.length];
}

// ═══════════════════════════════════════════════════════════════════════════
// v4.0.0 Registry Integration Methods
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Check if v4.0.0 registry is available
 * @param {string} projectRoot - Project root path
 * @returns {boolean} True if v4 registry exists
 */
function hasV4Registry(projectRoot) {
  if (_v4Available !== null) return _v4Available;

  const rmModule = getRegistryManagerModule();
  if (!rmModule) {
    _v4Available = false;
    return false;
  }

  const indexPath = path.join(projectRoot, '.design', 'registry-index.json');
  _v4Available = fs.existsSync(indexPath);
  return _v4Available;
}

/**
 * Get or create RegistryManager instance
 * @param {string} projectRoot - Project root path
 * @returns {Object|null} RegistryManager instance
 */
function getRegistryManager(projectRoot) {
  if (_registryManager) return _registryManager;

  const rmModule = getRegistryManagerModule();
  if (!rmModule || !hasV4Registry(projectRoot)) return null;

  try {
    _registryManager = rmModule.getRegistryManager(projectRoot);
    return _registryManager;
  } catch (e) {
    return null;
  }
}

/**
 * Generate v4.0.0 canonical ID for ShadCN component
 * @param {string} componentName - Component name
 * @param {string} registry - Registry name (default: @shadcn)
 * @returns {string} Canonical ID
 */
function generateV4CanonicalId(componentName, registry = '@shadcn') {
  const baseName = sanitizeFileName(componentName);
  const registrySlug = registry.replace('@', '').toLowerCase();
  return `shadcn-component-${registrySlug}-${baseName}`;
}

/**
 * Add or update ShadCN component using v4.0.0 RegistryManager
 * @param {Object} options - Options
 * @returns {Object|null} Result or null if v4 not available
 */
function addShadcnComponentV4(options) {
  const {
    projectRoot,
    component,
    tokens = {},
    variants = [],
    examples = [],
    dependencies = []
  } = options;

  const rm = getRegistryManager(projectRoot);
  if (!rm) return null;

  const registry = component.source?.registry || '@shadcn';
  const canonicalId = generateV4CanonicalId(component.name, registry);

  // Check for existing via O(1) lookup
  const existing = rm.findById(canonicalId);

  // Create v4 entry
  const entry = {
    id: canonicalId,
    name: component.name,
    type: component.type || 'COMPONENT',
    category: component.category || 'component',

    source: {
      type: 'shadcn',
      registry: registry,
      extractedAt: new Date().toISOString(),
      ...(existing?.source?.firstExtractedAt && {
        firstExtractedAt: existing.source.firstExtractedAt
      }),
      ...(!existing && {
        firstExtractedAt: new Date().toISOString()
      })
    },

    variants: variants.map(v => ({
      name: v.name,
      type: v.type || 'variant',
      default: v.default,
      options: v.options
    })),

    tokenDependencies: {
      colors: tokens.colors?.length || 0,
      typography: tokens.typography?.length || 0,
      spacing: tokens.spacing?.length || 0,
      effects: tokens.effects?.length || 0,
      borderRadius: tokens.borderRadius?.length || 0,
      ...(tokens.colors?.length <= 20 && { colorTokens: tokens.colors }),
      ...(tokens.cssVariables?.length > 0 && { cssVariables: tokens.cssVariables })
    },

    dependencies: dependencies,
    exampleCount: examples.length,

    paths: {
      rawSource: `.design/source/components/${sanitizeFileName(component.name)}.json`,
      codeOutput: `src/components/${pascalCase(component.name)}.tsx`,
      storyOutput: `src/components/${pascalCase(component.name)}.stories.tsx`
    },

    metadata: {
      version: (existing?.metadata?.version || 0) + 1,
      createdAt: existing?.metadata?.createdAt || new Date().toISOString(),
      updatedAt: new Date().toISOString()
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
    id: canonicalId,
    entry: entry,
    isUpdate: !!existing,
    usedV4: true
  };
}

/**
 * Find ShadCN component by canonical ID using v4 O(1) lookup
 * @param {string} projectRoot - Project root path
 * @param {string} canonicalId - Canonical ID
 * @returns {Object|null} Component entry
 */
function findByIdV4(projectRoot, canonicalId) {
  const rm = getRegistryManager(projectRoot);
  if (!rm) return null;
  return rm.findById(canonicalId);
}

/**
 * Get all ShadCN components using v4 registry
 * @param {string} projectRoot - Project root path
 * @returns {Array} ShadCN components
 */
function getShadcnComponentsV4(projectRoot) {
  const rm = getRegistryManager(projectRoot);
  if (!rm) return [];

  return rm.findBySource('shadcn');
}

/**
 * Query components using v4 registry
 * @param {string} projectRoot - Project root path
 * @param {Object} query - Query criteria
 * @returns {Array} Matching components
 */
function queryComponentsV4(projectRoot, query = {}) {
  const rm = getRegistryManager(projectRoot);
  if (!rm) return [];

  let results = rm.getAllEntries();

  // Filter by source type
  if (query.sourceType) {
    results = results.filter(comp => comp.source?.type === query.sourceType);
  }

  // Filter by category
  if (query.category) {
    results = results.filter(comp => comp.category === query.category);
  }

  // Filter by name pattern
  if (query.namePattern) {
    const pattern = new RegExp(query.namePattern, 'i');
    results = results.filter(comp => pattern.test(comp.name));
  }

  // Filter by having variants
  if (query.hasVariants) {
    results = results.filter(comp => comp.variants && comp.variants.length > 0);
  }

  return results;
}

/**
 * Link ShadCN and Figma components using v4 registry
 * @param {string} projectRoot - Project root path
 * @param {string} shadcnId - ShadCN component ID
 * @param {string} figmaId - Figma component ID
 * @returns {Object} Link result
 */
function linkComponentsV4(projectRoot, shadcnId, figmaId) {
  const rm = getRegistryManager(projectRoot);
  if (!rm) return null;

  const shadcn = rm.findById(shadcnId);
  const figma = rm.findById(figmaId);

  if (!shadcn) throw new Error(`ShadCN component not found: ${shadcnId}`);
  if (!figma) throw new Error(`Figma component not found: ${figmaId}`);

  // Add dependency links (bidirectional)
  rm.addDependency(shadcnId, figmaId);
  rm.addDependency(figmaId, shadcnId);

  rm.saveIndex();

  return {
    shadcn: shadcn,
    figma: figma,
    linked: true,
    usedV4: true
  };
}

/**
 * Get v4 registry statistics for ShadCN components
 * @param {string} projectRoot - Project root path
 * @returns {Object} Statistics
 */
function getV4Stats(projectRoot) {
  const rm = getRegistryManager(projectRoot);
  if (!rm) return null;

  const stats = rm.getStats();
  const shadcnComponents = rm.findBySource('shadcn');

  return {
    ...stats,
    shadcnComponents: shadcnComponents.length,
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
  loadRegistry,
  saveRegistry,
  getRegistryPath,
  addShadcnComponent,
  removeComponent,
  getComponent,
  queryComponents,
  getShadcnComponents,
  getRegistryStats,
  analyzeComponentMerge,
  linkComponents,
  exportRegistry,
  generateComponentId,
  DEFAULT_REGISTRY,

  // v4.0.0 exports
  hasV4Registry,
  getRegistryManager,
  generateV4CanonicalId,
  addShadcnComponentV4,
  findByIdV4,
  getShadcnComponentsV4,
  queryComponentsV4,
  linkComponentsV4,
  getV4Stats,
  invalidateV4Cache
};
