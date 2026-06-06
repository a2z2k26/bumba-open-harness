/**
 * figma-registry-integration.test.js
 * Unit tests for the Figma registry integration
 */

const fs = require('fs');
const path = require('path');
const {
  updateRegistry,
  batchUpdateRegistry,
  createEmptyRegistry,
  generateComponentId,
  findDuplicates,
  inferCategory,
  sanitizeFileName,
  pascalCase,
  formatRegistryResult
} = require('./figma-registry-integration');

let passed = 0;
let failed = 0;

function test(name, condition) {
  if (condition) {
    console.log(`  [PASS] ${name}`);
    passed++;
  } else {
    console.log(`  [FAIL] ${name}`);
    failed++;
  }
}

// Test file path for registry
const testRegistryPath = path.join(__dirname, 'test-registry-temp.json');

// Clean up test registry before and after tests
function cleanupTestRegistry() {
  try {
    if (fs.existsSync(testRegistryPath)) {
      fs.unlinkSync(testRegistryPath);
    }
  } catch (e) {
    // Ignore cleanup errors
  }
}

// Mock component data
const mockButton = {
  id: '1:100',
  name: 'Primary Button',
  type: 'COMPONENT_SET',
  description: 'A primary action button',
  tokenDependencies: {
    colors: ['Primary/500', 'White'],
    typography: ['Body/Medium'],
    spacing: ['16px'],
    effects: ['Shadow/Small'],
    borderRadius: ['8px']
  },
  interactiveStates: {
    hover: { backgroundColor: '#3366CC' },
    pressed: { opacity: 0.9 }
  },
  variants: [
    { name: 'Size', type: 'variant', options: ['Small', 'Medium', 'Large'] }
  ],
  props: [
    { name: 'size', type: "'Small' | 'Medium' | 'Large'" }
  ]
};

const mockCard = {
  id: '2:200',
  name: 'Product Card',
  type: 'COMPONENT',
  description: 'Displays product information'
};

const mockIcon = {
  id: '3:300',
  name: 'Icon/Arrow',
  type: 'COMPONENT'
};

const mockNavigation = {
  id: '4:400',
  name: 'Main Navigation',
  type: 'FRAME'
};

function runTests() {
  console.log('\n=== Figma Registry Integration Tests ===\n');

  cleanupTestRegistry();

  // Test sanitizeFileName
  console.log('sanitizeFileName:');

  test('converts spaces to dashes', sanitizeFileName('Primary Button') === 'primary-button');
  test('lowercases', sanitizeFileName('UPPERCASE') === 'uppercase');
  test('removes special chars', sanitizeFileName('Button!@#$%') === 'button');
  test('collapses multiple dashes', sanitizeFileName('a--b--c') === 'a-b-c');
  test('handles slashes', sanitizeFileName('Icon/Arrow/Right') === 'iconarrowright');

  // Test pascalCase
  console.log('\npascalCase:');

  test('converts simple name', pascalCase('button') === 'Button');
  test('handles spaces', pascalCase('primary button') === 'PrimaryButton');
  test('handles dashes', pascalCase('primary-button') === 'PrimaryButton');
  test('handles underscores', pascalCase('primary_button') === 'PrimaryButton');
  test('handles mixed', pascalCase('primary-Button_Component') === 'PrimaryButtonComponent');

  // Test inferCategory
  console.log('\ninferCategory:');

  test('infers button', inferCategory({ name: 'Primary Button' }) === 'button');
  test('infers card', inferCategory({ name: 'Product Card' }) === 'card');
  test('infers icon', inferCategory({ name: 'Icon/Arrow' }) === 'icon');
  test('infers navigation', inferCategory({ name: 'Main Navigation' }) === 'navigation');
  test('infers input', inferCategory({ name: 'Text Input' }) === 'input');
  test('infers modal', inferCategory({ name: 'Confirm Dialog' }) === 'modal');
  test('infers avatar', inferCategory({ name: 'User Avatar' }) === 'avatar');
  test('infers badge', inferCategory({ name: 'Status Badge' }) === 'badge');
  test('defaults to component', inferCategory({ name: 'Unknown Widget' }) === 'component');

  // Test generateComponentId
  console.log('\ngenerateComponentId:');

  const buttonId = generateComponentId(mockButton);
  test('generates id with prefix', buttonId.startsWith('figma-mcp-'));
  test('includes sanitized name', buttonId.includes('primary-button'));
  test('includes node id', buttonId.includes('1-100'));

  const iconId = generateComponentId(mockIcon);
  test('handles slashes in name', iconId.includes('iconarrow'));

  // Test createEmptyRegistry
  console.log('\ncreateEmptyRegistry:');

  const emptyReg = createEmptyRegistry();
  test('has version', emptyReg.version === '2.0.0');
  test('has metadata', emptyReg.metadata !== undefined);
  test('has components', emptyReg.components !== undefined);
  test('components is empty', Object.keys(emptyReg.components).length === 0);
  test('has lastUpdated', emptyReg.metadata.lastUpdated !== undefined);
  test('has extractionSources', Array.isArray(emptyReg.metadata.extractionSources));

  // Test updateRegistry - create new
  console.log('\nupdateRegistry (create):');

  const createResult = updateRegistry(testRegistryPath, mockButton, {
    fileKey: 'testFileKey123',
    originalUrl: 'https://figma.com/file/testFileKey123'
  });

  test('returns updated true', createResult.updated === true);
  test('returns componentId', createResult.componentId !== undefined);
  test('returns entry', createResult.entry !== undefined);
  test('entry has name', createResult.entry.name === 'Primary Button');
  test('entry has figmaId', createResult.entry.figmaId === '1:100');
  test('entry has category', createResult.entry.category === 'button');
  test('entry source is figma-mcp', createResult.entry.source.type === 'figma-mcp');
  test('entry has fileKey', createResult.entry.source.fileKey === 'testFileKey123');
  test('entry has tokenDependencies', createResult.entry.tokenDependencies !== undefined);
  test('entry has interactiveStates', createResult.entry.interactiveStates !== undefined);
  test('entry has paths', createResult.entry.paths !== undefined);
  test('entry has metadata', createResult.entry.metadata !== undefined);
  test('entry version is 1', createResult.entry.metadata.version === 1);

  // Verify file was written
  test('registry file exists', fs.existsSync(testRegistryPath));

  // Verify registry contents
  const registry = JSON.parse(fs.readFileSync(testRegistryPath, 'utf-8'));
  test('registry has version', registry.version === '2.0.0');
  test('registry has component', registry.components[createResult.componentId] !== undefined);
  test('registry tracks figma-mcp source', registry.metadata.extractionSources.includes('figma-mcp'));

  // Test updateRegistry - update existing
  console.log('\nupdateRegistry (update):');

  const updateResult = updateRegistry(testRegistryPath, {
    ...mockButton,
    description: 'Updated description'
  }, {
    fileKey: 'testFileKey123'
  });

  test('update returns updated true', updateResult.updated === true);
  test('update increments version', updateResult.entry.metadata.version === 2);
  test('update preserves createdAt', updateResult.entry.metadata.createdAt !== undefined);

  // Test updateRegistry - different source
  console.log('\nupdateRegistry (different source):');

  // Manually modify to simulate different source
  const regContent = JSON.parse(fs.readFileSync(testRegistryPath, 'utf-8'));
  const existingId = Object.keys(regContent.components)[0];
  regContent.components[existingId].source.type = 'manual';
  fs.writeFileSync(testRegistryPath, JSON.stringify(regContent, null, 2));

  const diffSourceResult = updateRegistry(testRegistryPath, mockButton, {
    fileKey: 'testFileKey123'
  });

  test('different source not updated', diffSourceResult.updated === false);
  test('different source reason', diffSourceResult.reason === 'exists_different_source');

  // Test with overwrite
  const overwriteResult = updateRegistry(testRegistryPath, mockButton, {
    fileKey: 'testFileKey123',
    overwrite: true
  });

  test('overwrite succeeds', overwriteResult.updated === true);

  // Test findDuplicates
  console.log('\nfindDuplicates:');

  const testReg = JSON.parse(fs.readFileSync(testRegistryPath, 'utf-8'));

  const nameMatch = findDuplicates(testReg, { name: 'Primary Button' });
  test('finds same name', nameMatch.length > 0);
  test('identifies name reason', nameMatch.some(m => m.reason === 'same_name'));

  const idMatch = findDuplicates(testReg, { figmaId: '1:100' });
  test('finds same figma id', idMatch.length > 0);
  test('identifies id reason', idMatch.some(m => m.reason === 'same_figma_id'));

  const noMatch = findDuplicates(testReg, { name: 'Unique Component', figmaId: '99:99' });
  test('no match for unique', noMatch.length === 0);

  // Test batchUpdateRegistry
  console.log('\nbatchUpdateRegistry:');

  cleanupTestRegistry();

  const batchResults = batchUpdateRegistry(testRegistryPath, [mockButton, mockCard, mockIcon], {
    fileKey: 'batchTest123'
  });

  test('batch returns 3 results', batchResults.length === 3);
  test('batch all updated', batchResults.every(r => r.updated));

  const batchReg = JSON.parse(fs.readFileSync(testRegistryPath, 'utf-8'));
  test('batch creates 3 components', Object.keys(batchReg.components).length === 3);

  // Test formatRegistryResult - single
  console.log('\nformatRegistryResult:');

  const singleFormatted = formatRegistryResult(createResult);
  test('single includes componentId', singleFormatted.includes('figma-mcp'));
  test('single includes category', singleFormatted.includes('button'));

  const skippedFormatted = formatRegistryResult({ updated: false, reason: 'exists_different_source' });
  test('skipped includes reason', skippedFormatted.includes('exists_different_source'));

  // Test formatRegistryResult - batch
  const batchFormatted = formatRegistryResult(batchResults);
  test('batch includes complete message', batchFormatted.includes('Registry Update Complete'));
  test('batch includes updated count', batchFormatted.includes('Updated: 3'));
  test('batch includes component names', batchFormatted.includes('Primary Button'));

  // Test paths generation
  console.log('\npaths generation:');

  const pathsEntry = createResult.entry;
  test('rawSource path correct', pathsEntry.paths.rawSource === '.design/source/components/primary-button.json');
  test('codeOutput path correct', pathsEntry.paths.codeOutput === 'src/components/PrimaryButton.tsx');
  test('storyOutput path correct', pathsEntry.paths.storyOutput === 'src/components/PrimaryButton.stories.tsx');

  // Cleanup
  cleanupTestRegistry();

  // Summary
  console.log('\n=============================');
  console.log(`Results: ${passed} passed, ${failed} failed`);
  console.log('=============================\n');

  return { passed, failed };
}

// Run tests
if (require.main === module) {
  const result = runTests();
  process.exit(result.failed > 0 ? 1 : 0);
}

module.exports = { runTests };
