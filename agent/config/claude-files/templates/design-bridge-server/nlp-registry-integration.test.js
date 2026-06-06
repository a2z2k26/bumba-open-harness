/**
 * nlp-registry-integration.test.js
 * Unit tests for NLP registry integration
 */

const fs = require('fs');
const path = require('path');
const {
  nlpEntrySchema,
  createRegistryEntry,
  updateComponentRegistry,
  loadRegistry,
  saveRegistry,
  createEmptyRegistry,
  getNlpComponents,
  getRefinementHistory,
  findByName,
  findByCategory,
  removeFromRegistry,
  getNlpStats,
  validateEntry,
  generateComponentId,
  sanitizeFileName,
  pascalCase,
  formatResult
} = require('./nlp-registry-integration');

let passed = 0;
let failed = 0;

// Test registry path (temporary)
const TEST_REGISTRY_PATH = path.join(__dirname, '.test-registry.json');

function test(name, condition) {
  if (condition) {
    console.log(`  [PASS] ${name}`);
    passed++;
  } else {
    console.log(`  [FAIL] ${name}`);
    failed++;
  }
}

function cleanup() {
  // Remove test registry file
  try {
    if (fs.existsSync(TEST_REGISTRY_PATH)) {
      fs.unlinkSync(TEST_REGISTRY_PATH);
    }
  } catch (e) {
    // Ignore cleanup errors
  }
}

function runTests() {
  console.log('\n=== NLP Registry Integration Tests ===\n');

  // Clean up before tests
  cleanup();

  // Test: nlpEntrySchema
  console.log('--- nlpEntrySchema ---');
  test('schema exists', typeof nlpEntrySchema === 'object');
  test('has required fields', Array.isArray(nlpEntrySchema.required));
  test('required includes name', nlpEntrySchema.required.includes('name'));
  test('required includes type', nlpEntrySchema.required.includes('type'));
  test('required includes category', nlpEntrySchema.required.includes('category'));
  test('required includes source', nlpEntrySchema.required.includes('source'));
  test('has properties', typeof nlpEntrySchema.properties === 'object');

  // Test: Utility functions
  console.log('\n--- Utility Functions ---');

  test('sanitizeFileName basic', sanitizeFileName('Test Component') === 'test-component');
  test('sanitizeFileName special chars', sanitizeFileName('Button@Primary!') === 'buttonprimary');
  test('sanitizeFileName multiple spaces', sanitizeFileName('My   Button') === 'my-button');
  test('sanitizeFileName multiple dashes', sanitizeFileName('my--button') === 'my-button');

  test('pascalCase basic', pascalCase('test component') === 'TestComponent');
  test('pascalCase with dashes', pascalCase('primary-button') === 'PrimaryButton');
  test('pascalCase with underscores', pascalCase('my_button') === 'MyButton');
  test('pascalCase single word', pascalCase('button') === 'Button');

  const testComponent = { name: 'TestButton' };
  const generatedId = generateComponentId(testComponent);
  test('generateComponentId has nlp prefix', generatedId.startsWith('nlp-'));
  test('generateComponentId has component name', generatedId.includes('testbutton'));
  test('generateComponentId has timestamp', /\d+$/.test(generatedId));

  // Test: createEmptyRegistry
  console.log('\n--- createEmptyRegistry ---');

  const emptyRegistry = createEmptyRegistry();
  test('creates registry object', typeof emptyRegistry === 'object');
  test('has version', emptyRegistry.version === '2.0.0');
  test('has metadata', typeof emptyRegistry.metadata === 'object');
  test('has components array', Array.isArray(emptyRegistry.components));
  test('components is empty', emptyRegistry.components.length === 0);
  test('has lastUpdated', emptyRegistry.metadata.lastUpdated !== undefined);
  test('has extractionSources', Array.isArray(emptyRegistry.metadata.extractionSources));

  // Test: createRegistryEntry
  console.log('\n--- createRegistryEntry ---');

  const sampleComponent = {
    id: 'nlp-button-123',
    name: 'PrimaryButton',
    type: 'COMPONENT',
    category: 'button',
    description: 'A primary button component',
    source: {
      type: 'nlp-prompt',
      extractedAt: '2024-01-01T00:00:00.000Z',
      prompt: 'Create a primary button',
      generationParams: { category: 'button', framework: 'react' }
    },
    tokenDependencies: {
      colors: ['Primary/500'],
      typography: ['text-base'],
      spacing: ['8'],
      effects: [],
      borderRadius: ['md']
    },
    variants: {
      variant: { primary: {}, secondary: {} },
      size: { sm: {}, md: {}, lg: {} }
    },
    props: [
      { name: 'children', type: 'React.ReactNode', required: true }
    ]
  };

  const entry = createRegistryEntry(sampleComponent, '.design/source/components/PrimaryButton.json');

  test('entry has id', entry.id === 'nlp-button-123');
  test('entry has name', entry.name === 'PrimaryButton');
  test('entry has type', entry.type === 'COMPONENT');
  test('entry has category', entry.category === 'button');
  test('entry has description', entry.description === 'A primary button component');
  test('entry has source', typeof entry.source === 'object');
  test('entry source type is nlp-prompt', entry.source.type === 'nlp-prompt');
  test('entry has prompt', entry.source.prompt === 'Create a primary button');
  test('entry has tokenDependencies', typeof entry.tokenDependencies === 'object');
  test('entry has variants array', Array.isArray(entry.variants));
  test('entry variants includes variant', entry.variants.includes('variant'));
  test('entry variants includes size', entry.variants.includes('size'));
  test('entry has variantDefinitions', typeof entry.variantDefinitions === 'object');
  test('entry has props', Array.isArray(entry.props));
  test('entry has paths', typeof entry.paths === 'object');
  test('entry has rawSource path', entry.paths.rawSource === '.design/source/components/PrimaryButton.json');
  test('entry has codeOutput path', entry.paths.codeOutput === 'src/components/PrimaryButton.tsx');
  test('entry has metadata', typeof entry.metadata === 'object');
  test('entry has version', entry.metadata.version === 1);
  test('entry has refinementCount', entry.metadata.refinementCount === 0);

  // Test: Load/Save registry
  console.log('\n--- loadRegistry / saveRegistry ---');

  const testRegistry = createEmptyRegistry();
  testRegistry.components.push(entry);
  saveRegistry(testRegistry, TEST_REGISTRY_PATH);

  test('registry file created', fs.existsSync(TEST_REGISTRY_PATH));

  const loadedRegistry = loadRegistry(TEST_REGISTRY_PATH);
  test('loaded registry has version', loadedRegistry.version === '2.0.0');
  test('loaded registry has components', loadedRegistry.components.length === 1);
  test('loaded component matches', loadedRegistry.components[0].name === 'PrimaryButton');

  const nonexistentRegistry = loadRegistry('/nonexistent/path/registry.json');
  test('nonexistent returns empty registry', nonexistentRegistry.components.length === 0);

  // Test: updateComponentRegistry
  console.log('\n--- updateComponentRegistry ---');

  // Clean for fresh test
  cleanup();

  const newComponent = {
    name: 'GhostButton',
    type: 'COMPONENT',
    category: 'button',
    description: 'A ghost button',
    source: {
      type: 'nlp-prompt',
      prompt: 'Create a ghost button'
    },
    variants: { variant: { ghost: {} } },
    props: []
  };

  const newEntry = createRegistryEntry(newComponent, '.design/source/components/GhostButton.json');
  const addResult = updateComponentRegistry(newEntry, TEST_REGISTRY_PATH);

  test('add returns updated true', addResult.updated === true);
  test('add returns componentId', addResult.componentId !== undefined);
  test('add returns entry', addResult.entry !== undefined);
  test('add not a refinement', addResult.isRefinement === false);

  // Verify it was added
  const afterAdd = loadRegistry(TEST_REGISTRY_PATH);
  test('registry has component after add', afterAdd.components.length === 1);
  test('registry has nlp-prompt source', afterAdd.metadata.extractionSources.includes('nlp-prompt'));

  // Update existing component
  const updatedComponent = {
    ...newComponent,
    description: 'An updated ghost button',
    source: {
      type: 'nlp-prompt',
      prompt: 'Update the ghost button to have better styling'
    }
  };
  const updatedEntry = createRegistryEntry(updatedComponent, '.design/source/components/GhostButton.json');
  const updateResult = updateComponentRegistry(updatedEntry, TEST_REGISTRY_PATH);

  test('update returns updated true', updateResult.updated === true);
  test('update is refinement', updateResult.isRefinement === true);
  test('update increments version', updateResult.entry.metadata.version === 2);
  test('update tracks previous version', updateResult.entry.source.previousVersion !== null);

  // Test overwrite = false
  const anotherEntry = createRegistryEntry({
    ...newComponent,
    description: 'Third version'
  }, '.design/source/components/GhostButton.json');
  const noOverwriteResult = updateComponentRegistry(anotherEntry, TEST_REGISTRY_PATH, { overwrite: false });

  test('no overwrite returns updated false', noOverwriteResult.updated === false);
  test('no overwrite reason is exists', noOverwriteResult.reason === 'exists');

  // Test: getNlpComponents
  console.log('\n--- getNlpComponents ---');

  // Add a non-NLP component manually
  const registry = loadRegistry(TEST_REGISTRY_PATH);
  registry.components.push({
    name: 'FigmaButton',
    source: { type: 'figma-mcp' }
  });
  saveRegistry(registry, TEST_REGISTRY_PATH);

  const nlpComponents = getNlpComponents(TEST_REGISTRY_PATH);
  test('getNlpComponents returns array', Array.isArray(nlpComponents));
  test('getNlpComponents filters by source type', nlpComponents.length === 1);
  test('getNlpComponents returns only nlp-prompt', nlpComponents.every(c => c.source.type === 'nlp-prompt'));

  // Test: findByName
  console.log('\n--- findByName ---');

  const foundByName = findByName('GhostButton', TEST_REGISTRY_PATH);
  test('findByName finds existing', foundByName !== null);
  test('findByName returns correct component', foundByName.name === 'GhostButton');

  const notFoundByName = findByName('NonexistentComponent', TEST_REGISTRY_PATH);
  test('findByName returns null for nonexistent', notFoundByName === null);

  const caseInsensitive = findByName('ghostbutton', TEST_REGISTRY_PATH);
  test('findByName is case insensitive', caseInsensitive !== null);

  // Test: findByCategory
  console.log('\n--- findByCategory ---');

  const buttonComponents = findByCategory('button', TEST_REGISTRY_PATH);
  test('findByCategory returns array', Array.isArray(buttonComponents));
  test('findByCategory finds button category', buttonComponents.length >= 1);

  const cardComponents = findByCategory('card', TEST_REGISTRY_PATH);
  test('findByCategory returns empty for no matches', cardComponents.length === 0);

  // Test: getRefinementHistory
  console.log('\n--- getRefinementHistory ---');

  const history = getRefinementHistory('GhostButton', TEST_REGISTRY_PATH);
  test('getRefinementHistory returns array', Array.isArray(history));
  test('getRefinementHistory has current version', history.length >= 1);
  test('getRefinementHistory includes prompt', history[0] && history[0].prompt !== undefined);

  const noHistory = getRefinementHistory('NonexistentComponent', TEST_REGISTRY_PATH);
  test('getRefinementHistory returns empty for nonexistent', noHistory.length === 0);

  // Test: validateEntry
  console.log('\n--- validateEntry ---');

  const validEntry = createRegistryEntry(sampleComponent, '/test/path.json');
  const validResult = validateEntry(validEntry);
  test('valid entry passes validation', validResult.valid === true);
  test('valid entry has no errors', validResult.errors.length === 0);

  const invalidEntry = { name: 'Test' }; // Missing required fields
  const invalidResult = validateEntry(invalidEntry);
  test('invalid entry fails validation', invalidResult.valid === false);
  test('invalid entry has errors', invalidResult.errors.length > 0);

  const wrongSourceType = {
    name: 'Test',
    type: 'COMPONENT',
    category: 'button',
    source: { type: 'figma-mcp', extractedAt: new Date().toISOString() }
  };
  const wrongSourceResult = validateEntry(wrongSourceType);
  test('wrong source type fails validation', wrongSourceResult.valid === false);
  test('reports wrong source type', wrongSourceResult.errors.some(e => e.includes('source type')));

  // Test: getNlpStats
  console.log('\n--- getNlpStats ---');

  const stats = getNlpStats(TEST_REGISTRY_PATH);
  test('stats has totalComponents', typeof stats.totalComponents === 'number');
  test('stats has byCategory', typeof stats.byCategory === 'object');
  test('stats has byVariant', typeof stats.byVariant === 'object');
  test('stats has averageVariantsPerComponent', stats.averageVariantsPerComponent !== undefined);
  test('stats has averagePropsPerComponent', stats.averagePropsPerComponent !== undefined);
  test('stats has totalRefinements', typeof stats.totalRefinements === 'number');
  test('stats counts button category', stats.byCategory.button >= 1);

  // Test: removeFromRegistry
  console.log('\n--- removeFromRegistry ---');

  const removeResult = removeFromRegistry('GhostButton', TEST_REGISTRY_PATH);
  test('remove returns removed true', removeResult.removed === true);
  test('remove returns componentId', removeResult.componentId !== undefined);
  test('remove returns component', removeResult.component !== undefined);

  const afterRemove = loadRegistry(TEST_REGISTRY_PATH);
  const ghostButton = afterRemove.components.find(c => c.name === 'GhostButton');
  test('component removed from registry', ghostButton === undefined);

  const removeNonexistent = removeFromRegistry('NonexistentComponent', TEST_REGISTRY_PATH);
  test('remove nonexistent returns removed false', removeNonexistent.removed === false);
  test('remove nonexistent has reason', removeNonexistent.reason === 'not_found');

  // Test: formatResult
  console.log('\n--- formatResult ---');

  const successResult = {
    updated: true,
    componentId: 'nlp-test-123',
    entry: { metadata: { version: 2 }, source: { previousVersion: 'nlp-test-100' } },
    isRefinement: true
  };
  const successFormatted = formatResult(successResult);
  test('success format includes checkmark', successFormatted.includes('✓'));
  test('success format includes componentId', successFormatted.includes('nlp-test-123'));
  test('success format includes version', successFormatted.includes('Version'));
  test('success format shows refinement', successFormatted.includes('Refinement'));

  const failResult = { updated: false, reason: 'exists' };
  const failFormatted = formatResult(failResult);
  test('fail format includes X mark', failFormatted.includes('✗'));
  test('fail format includes reason', failFormatted.includes('exists'));

  // Test: Edge cases
  console.log('\n--- Edge Cases ---');

  // Empty component name
  const emptyNameComponent = { name: '', type: 'COMPONENT', category: 'button' };
  const emptyNameId = generateComponentId(emptyNameComponent);
  test('handles empty name', emptyNameId.startsWith('nlp-'));

  // Component with minimal data
  const minimalComponent = {
    name: 'MinimalButton',
    type: 'COMPONENT',
    category: 'button'
  };
  const minimalEntry = createRegistryEntry(minimalComponent, '/test/minimal.json');
  test('minimal component has defaults', minimalEntry.tokenDependencies !== undefined);
  test('minimal component has empty arrays', minimalEntry.props.length === 0);

  // Clean up
  cleanup();

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
