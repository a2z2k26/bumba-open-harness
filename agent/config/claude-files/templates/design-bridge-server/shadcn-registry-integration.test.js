/**
 * shadcn-registry-integration.test.js
 * Unit tests for ShadCN registry integration
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

const {
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
  DEFAULT_REGISTRY
} = require('./shadcn-registry-integration');

let passed = 0;
let failed = 0;
let testDir = '';

function test(name, condition) {
  if (condition) {
    console.log(`  [PASS] ${name}`);
    passed++;
  } else {
    console.log(`  [FAIL] ${name}`);
    failed++;
  }
}

function setup() {
  // Create temporary test directory
  testDir = path.join(os.tmpdir(), `shadcn-test-${Date.now()}`);
  fs.mkdirSync(testDir, { recursive: true });
  return testDir;
}

function cleanup() {
  // Remove test directory
  if (testDir && fs.existsSync(testDir)) {
    fs.rmSync(testDir, { recursive: true, force: true });
  }
}

function runTests() {
  console.log('\n=== ShadCN Registry Integration Tests ===\n');

  setup();

  try {
    // Test: getRegistryPath
    console.log('--- getRegistryPath ---');
    const registryPath = getRegistryPath(testDir);
    test('returns correct path', registryPath === path.join(testDir, '.design', 'componentRegistry.json'));

    // Test: loadRegistry - no existing file
    console.log('\n--- loadRegistry (new) ---');
    const newRegistry = loadRegistry(testDir);
    test('returns default registry for new project', newRegistry.version === DEFAULT_REGISTRY.version);
    test('has empty components', Object.keys(newRegistry.components).length === 0);
    test('has metadata', !!newRegistry.metadata);

    // Test: saveRegistry
    console.log('\n--- saveRegistry ---');
    const testRegistry = {
      version: '2.0.0',
      components: { 'test-component': { name: 'Test' } },
      metadata: { createdAt: new Date().toISOString() }
    };
    saveRegistry(testDir, testRegistry);
    test('creates registry file', fs.existsSync(getRegistryPath(testDir)));

    const savedRegistry = loadRegistry(testDir);
    test('saves and loads registry correctly', savedRegistry.components['test-component'].name === 'Test');
    test('updates lastUpdated', !!savedRegistry.metadata.lastUpdated);

    // Test: generateComponentId
    console.log('\n--- generateComponentId ---');
    test('generates button ID', generateComponentId('button', 'shadcn') === 'shadcn-button');
    test('generates Button ID (lowercase)', generateComponentId('Button', 'shadcn') === 'shadcn-button');
    test('handles spaces', generateComponentId('Button Group', 'shadcn') === 'shadcn-button-group');
    test('handles special chars', generateComponentId('Alert@Dialog!', 'shadcn') === 'shadcn-alertdialog');

    // Test: addShadcnComponent
    console.log('\n--- addShadcnComponent ---');
    const buttonResult = addShadcnComponent({
      projectRoot: testDir,
      component: { name: 'Button', type: 'COMPONENT', category: 'button' },
      tokens: {
        colors: ['bg-primary', 'text-white'],
        typography: ['text-sm'],
        spacing: ['px-4', 'py-2'],
        effects: ['shadow-xs']
      },
      variants: [
        { name: 'variant', type: 'variant', default: 'default', options: ['default', 'destructive'] },
        { name: 'size', type: 'variant', default: 'default', options: ['sm', 'default', 'lg'] }
      ],
      examples: [{ name: 'demo', code: '<Button>Click</Button>' }],
      dependencies: ['@radix-ui/react-slot']
    });

    test('returns component ID', buttonResult.id === 'shadcn-button');
    test('returns entry', !!buttonResult.entry);
    test('isUpdate is false for new component', buttonResult.isUpdate === false);

    const buttonEntry = buttonResult.entry;
    test('entry has name', buttonEntry.name === 'Button');
    test('entry has source type', buttonEntry.source.type === 'shadcn');
    test('entry has variants', buttonEntry.variants.length === 2);
    test('entry has token dependencies', buttonEntry.tokenDependencies.colors === 2);
    test('entry has paths', !!buttonEntry.paths);
    test('entry has metadata version', buttonEntry.metadata.version === 1);

    // Test: addShadcnComponent - update existing
    console.log('\n--- addShadcnComponent (update) ---');
    const updateResult = addShadcnComponent({
      projectRoot: testDir,
      component: { name: 'Button', type: 'COMPONENT', category: 'button' },
      tokens: { colors: ['bg-primary', 'text-white', 'hover:bg-primary/90'] },
      variants: []
    });

    test('isUpdate is true for existing', updateResult.isUpdate === true);
    test('version incremented', updateResult.entry.metadata.version === 2);
    test('preserves firstExtractedAt', !!updateResult.entry.source.firstExtractedAt);

    // Test: getComponent
    console.log('\n--- getComponent ---');
    const retrieved = getComponent(testDir, 'shadcn-button');
    test('retrieves component by ID', retrieved && retrieved.name === 'Button');

    const notFound = getComponent(testDir, 'shadcn-nonexistent');
    test('returns null for non-existent', notFound === null);

    // Test: queryComponents
    console.log('\n--- queryComponents ---');
    // Add more components for querying
    addShadcnComponent({
      projectRoot: testDir,
      component: { name: 'Dialog', type: 'COMPONENT', category: 'modal' },
      variants: []
    });
    addShadcnComponent({
      projectRoot: testDir,
      component: { name: 'Card', type: 'COMPONENT', category: 'card' },
      variants: []
    });

    const allComponents = queryComponents(testDir);
    test('returns all components', allComponents.length >= 3);

    const shadcnOnly = queryComponents(testDir, { sourceType: 'shadcn' });
    test('filters by source type', shadcnOnly.every(c => c.source.type === 'shadcn'));

    const buttonCategory = queryComponents(testDir, { category: 'button' });
    test('filters by category', buttonCategory.length >= 1);
    test('category filter correct', buttonCategory[0].category === 'button');

    const patternResults = queryComponents(testDir, { namePattern: 'but' });
    test('filters by name pattern', patternResults.some(c => c.name.toLowerCase().includes('but')));

    const withVariants = queryComponents(testDir, { hasVariants: true });
    test('filters by hasVariants', withVariants.every(c => c.variants && c.variants.length > 0));

    // Test: getShadcnComponents
    console.log('\n--- getShadcnComponents ---');
    const shadcnComponents = getShadcnComponents(testDir);
    test('returns shadcn components', shadcnComponents.length >= 3);
    test('all are shadcn source', shadcnComponents.every(c => c.source.type === 'shadcn'));

    // Test: getRegistryStats
    console.log('\n--- getRegistryStats ---');
    const stats = getRegistryStats(testDir);
    test('returns total components', stats.totalComponents >= 3);
    test('has bySource stats', !!stats.bySource.shadcn);
    test('has byCategory stats', Object.keys(stats.byCategory).length > 0);
    test('counts variants', typeof stats.totalVariants === 'number');
    test('counts token dependencies', typeof stats.totalTokenDependencies === 'number');

    // Test: analyzeComponentMerge
    console.log('\n--- analyzeComponentMerge ---');
    // Add a mock Figma component for merge analysis
    const registry = loadRegistry(testDir);
    registry.components['figma-button'] = {
      name: 'Button',
      source: { type: 'figma-mcp' },
      category: 'button'
    };
    registry.components['figma-card'] = {
      name: 'Card Component',
      source: { type: 'figma' },
      category: 'card'
    };
    saveRegistry(testDir, registry);

    const mergeAnalysis = analyzeComponentMerge(testDir);
    test('counts shadcn components', mergeAnalysis.shadcnCount >= 3);
    test('counts figma components', mergeAnalysis.figmaCount >= 2);
    test('finds potential merges', Array.isArray(mergeAnalysis.potentialMerges));

    // Test: linkComponents
    console.log('\n--- linkComponents ---');
    const linkResult = linkComponents(testDir, 'shadcn-button', 'figma-button');
    test('links shadcn to figma', linkResult.shadcn.linkedTo.includes('figma-button'));
    test('links figma to shadcn', linkResult.figma.linkedTo.includes('shadcn-button'));

    // Verify error handling
    let linkError = false;
    try {
      linkComponents(testDir, 'shadcn-nonexistent', 'figma-button');
    } catch (e) {
      linkError = true;
    }
    test('throws error for non-existent component', linkError);

    // Test: removeComponent
    console.log('\n--- removeComponent ---');
    const removeSuccess = removeComponent(testDir, 'shadcn-dialog');
    test('removes existing component', removeSuccess === true);

    const removeFail = removeComponent(testDir, 'shadcn-nonexistent');
    test('returns false for non-existent', removeFail === false);

    const afterRemove = getComponent(testDir, 'shadcn-dialog');
    test('component actually removed', afterRemove === null);

    // Test: exportRegistry - JSON
    console.log('\n--- exportRegistry (JSON) ---');
    const jsonExport = exportRegistry(testDir, 'json');
    test('exports valid JSON', JSON.parse(jsonExport));

    // Test: exportRegistry - CSV
    console.log('\n--- exportRegistry (CSV) ---');
    const csvExport = exportRegistry(testDir, 'csv');
    test('exports CSV with headers', csvExport.includes('ID,Name,Type'));
    test('exports CSV with data rows', csvExport.split('\n').length > 1);

    // Test: exportRegistry - Markdown
    console.log('\n--- exportRegistry (Markdown) ---');
    const mdExport = exportRegistry(testDir, 'markdown');
    test('exports markdown with title', mdExport.includes('# Component Registry'));
    test('exports markdown table', mdExport.includes('| Name | Type |'));

    // Edge cases
    console.log('\n--- Edge Cases ---');
    const invalidRegistry = { components: null };
    fs.writeFileSync(getRegistryPath(testDir), 'invalid json{');
    const fallbackRegistry = loadRegistry(testDir);
    test('handles corrupted registry file', fallbackRegistry.version === DEFAULT_REGISTRY.version);

  } finally {
    cleanup();
  }

  // Print results
  console.log('\n=== Test Results ===');
  console.log(`Passed: ${passed}`);
  console.log(`Failed: ${failed}`);
  console.log(`Total: ${passed + failed}`);

  return { passed, failed };
}

// Run if executed directly
if (require.main === module) {
  runTests();
}

module.exports = { runTests };
