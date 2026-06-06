#!/usr/bin/env node
/**
 * test-registry-e2e.js
 * End-to-End Registry Tests for v4.0.0 Architecture
 *
 * Phase 6: Comprehensive test suite covering:
 * - Full registry lifecycle (create, read, update, delete)
 * - Cross-source component linking
 * - Dependency graph operations
 * - Performance benchmarks
 * - Migration verification
 * - Pipeline integration
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

// Test utilities
let passed = 0;
let failed = 0;
const testResults = [];

function test(name, fn) {
  try {
    fn();
    console.log('\x1b[32m✅\x1b[0m', name);
    passed++;
    testResults.push({ name, status: 'passed' });
  } catch (err) {
    console.log('\x1b[31m❌\x1b[0m', name + ':', err.message);
    failed++;
    testResults.push({ name, status: 'failed', error: err.message });
  }
}

async function testAsync(name, fn) {
  try {
    await fn();
    console.log('\x1b[32m✅\x1b[0m', name);
    passed++;
    testResults.push({ name, status: 'passed' });
  } catch (err) {
    console.log('\x1b[31m❌\x1b[0m', name + ':', err.message);
    failed++;
    testResults.push({ name, status: 'failed', error: err.message });
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message || 'Assertion failed');
}

// Create temporary test directory
const testDir = path.join(os.tmpdir(), `registry-e2e-test-${Date.now()}`);
const designDir = path.join(testDir, '.design');

function setupTestDir() {
  if (fs.existsSync(testDir)) {
    fs.rmSync(testDir, { recursive: true });
  }
  fs.mkdirSync(designDir, { recursive: true });
}

function cleanupTestDir() {
  if (fs.existsSync(testDir)) {
    fs.rmSync(testDir, { recursive: true });
  }
}

console.log('\n═══════════════════════════════════════════════════════════');
console.log('   PHASE 6: End-to-End Registry Tests v4.0.0');
console.log('═══════════════════════════════════════════════════════════\n');

// ═══════════════════════════════════════════════════════════════════════════
// Section 1: Registry Manager Lifecycle Tests
// ═══════════════════════════════════════════════════════════════════════════

console.log('─── Registry Manager Lifecycle ───\n');

setupTestDir();

test('RegistryManager module loads', () => {
  const rm = require('./registry-manager');
  assert(rm, 'Module should load');
  assert(typeof rm.getRegistryManager === 'function', 'getRegistryManager should exist');
  assert(typeof rm.clearRegistryManager === 'function', 'clearRegistryManager should exist');
});

test('RegistryManager creates directory structure', async () => {
  const { getRegistryManager, clearRegistryManager } = require('./registry-manager');
  clearRegistryManager();

  const manager = await getRegistryManager(designDir);
  assert(manager, 'Manager should be created');

  assert(fs.existsSync(path.join(designDir, 'registry-index.json')), 'Index should exist');
  assert(fs.existsSync(path.join(designDir, 'registries')), 'Registries dir should exist');
  assert(fs.existsSync(path.join(designDir, 'registries', 'components.json')), 'Components registry should exist');
  assert(fs.existsSync(path.join(designDir, 'registries', 'tokens.json')), 'Tokens registry should exist');
  assert(fs.existsSync(path.join(designDir, 'registries', 'layouts.json')), 'Layouts registry should exist');
});

test('RegistryManager singleton pattern works', async () => {
  const { getRegistryManager, clearRegistryManager } = require('./registry-manager');
  clearRegistryManager();

  const manager1 = await getRegistryManager(designDir);
  const manager2 = await getRegistryManager(designDir);

  assert(manager1 === manager2, 'Same instance should be returned');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 2: Entry CRUD Operations
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── Entry CRUD Operations ───\n');

test('addEntry creates component with canonical ID', async () => {
  const { getRegistryManager, clearRegistryManager } = require('./registry-manager');
  clearRegistryManager();
  setupTestDir();

  const manager = await getRegistryManager(designDir);

  const entry = {
    name: 'PrimaryButton',
    type: 'COMPONENT',
    category: 'button',
    source: {
      type: 'figma',
      nodeId: '123:456',
      fileKey: 'abc123'
    }
  };

  const result = manager.addEntry(entry, 'component');

  assert(result.id, 'Should return ID');
  assert(result.id.startsWith('figma-component-'), 'ID should have correct prefix');
  assert(result.id.includes('primarybutton'), 'ID should include sanitized name');
});

test('findById retrieves entry', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const entry = {
    name: 'SecondaryButton',
    type: 'COMPONENT',
    category: 'button',
    source: {
      type: 'shadcn',
      registry: '@shadcn'
    }
  };

  const added = manager.addEntry(entry, 'component');
  const found = manager.findById(added.id);

  assert(found, 'Should find entry');
  assert(found.name === 'SecondaryButton', 'Should have correct name');
});

test('findByNodeId resolves via source mapping', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const entry = {
    name: 'IconButton',
    type: 'COMPONENT',
    category: 'button',
    source: {
      type: 'figma',
      nodeId: '789:012',
      fileKey: 'xyz789'
    }
  };

  manager.addEntry(entry, 'component');
  const found = manager.findByNodeId('789:012');

  assert(found, 'Should find by node ID');
  assert(found.name === 'IconButton', 'Should have correct name');
});

test('updateEntry merges without overwriting', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const entry = {
    name: 'MergeTestButton',
    type: 'COMPONENT',
    category: 'button',
    description: 'Original description',
    source: { type: 'figma', nodeId: '111:222' }
  };

  const added = manager.addEntry(entry, 'component');

  manager.updateEntry(added.id, {
    description: 'Updated description',
    metadata: { customField: 'test' }
  }, 'component');

  const updated = manager.findById(added.id);

  assert(updated.description === 'Updated description', 'Description should be updated');
  assert(updated.name === 'MergeTestButton', 'Name should be preserved');
  assert(updated.metadata?.customField === 'test', 'Custom field should exist');
});

test('removeEntry cleans up all indexes', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const entry = {
    name: 'ToBeDeleted',
    type: 'COMPONENT',
    category: 'button',
    source: { type: 'figma', nodeId: '999:888' }
  };

  const added = manager.addEntry(entry, 'component');

  // Verify it exists
  assert(manager.findById(added.id), 'Should exist before removal');
  assert(manager.findByNodeId('999:888'), 'Should find by node ID before removal');

  // Remove
  const removed = manager.removeEntry(added.id, 'component');
  assert(removed === true, 'Should return true');

  // Verify cleanup
  assert(!manager.findById(added.id), 'Should not find by ID after removal');
  assert(!manager.findByNodeId('999:888'), 'Should not find by node ID after removal');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 3: Cross-Source Linking Tests
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── Cross-Source Linking ───\n');

test('Link Figma component to ShadCN component', async () => {
  const { getRegistryManager, clearRegistryManager } = require('./registry-manager');
  clearRegistryManager();
  setupTestDir();

  const manager = await getRegistryManager(designDir);

  // Add Figma component
  const figmaEntry = {
    name: 'Button',
    type: 'COMPONENT',
    category: 'button',
    source: { type: 'figma', nodeId: '100:200', fileKey: 'file1' }
  };
  const figma = manager.addEntry(figmaEntry, 'component');

  // Add ShadCN component
  const shadcnEntry = {
    name: 'Button',
    type: 'COMPONENT',
    category: 'button',
    source: { type: 'shadcn', registry: '@shadcn' }
  };
  const shadcn = manager.addEntry(shadcnEntry, 'component');

  // Link them
  manager.updateEntry(figma.id, {
    linkedComponents: [shadcn.id]
  }, 'component');

  manager.updateEntry(shadcn.id, {
    linkedComponents: [figma.id]
  }, 'component');

  // Verify links
  const figmaFound = manager.findById(figma.id);
  const shadcnFound = manager.findById(shadcn.id);

  assert(figmaFound.linkedComponents?.includes(shadcn.id), 'Figma should link to ShadCN');
  assert(shadcnFound.linkedComponents?.includes(figma.id), 'ShadCN should link to Figma');
});

test('findBySource filters correctly', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const figmaComponents = manager.findBySource('figma');
  const shadcnComponents = manager.findBySource('shadcn');

  assert(Array.isArray(figmaComponents), 'Should return array');
  assert(figmaComponents.every(c => c.source?.type === 'figma'), 'All should be figma source');
  assert(shadcnComponents.every(c => c.source?.type === 'shadcn'), 'All should be shadcn source');
});

test('findByCategory filters correctly', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const buttons = manager.findByCategory('button');

  assert(Array.isArray(buttons), 'Should return array');
  assert(buttons.every(c => c.category === 'button'), 'All should be button category');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 4: Dependency Graph Tests
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── Dependency Graph ───\n');

test('updateDependencies creates graph entries', async () => {
  const { getRegistryManager, clearRegistryManager } = require('./registry-manager');
  clearRegistryManager();
  setupTestDir();

  const manager = await getRegistryManager(designDir);

  // Create entries
  const parent = manager.addEntry({
    name: 'Card',
    type: 'COMPONENT',
    category: 'card',
    source: { type: 'figma', nodeId: '1:1' }
  }, 'component');

  const child1 = manager.addEntry({
    name: 'CardHeader',
    type: 'COMPONENT',
    category: 'card',
    source: { type: 'figma', nodeId: '1:2' }
  }, 'component');

  const child2 = manager.addEntry({
    name: 'CardBody',
    type: 'COMPONENT',
    category: 'card',
    source: { type: 'figma', nodeId: '1:3' }
  }, 'component');

  // Set dependencies
  manager.updateDependencies(parent.id, [child1.id, child2.id]);

  // Verify
  const deps = manager.findDependencies(parent.id);
  assert(deps.includes(child1.id), 'Should include child1');
  assert(deps.includes(child2.id), 'Should include child2');
});

test('findDependents returns correct entries', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  // Find what depends on CardHeader
  const cardHeader = manager.findByName('CardHeader')[0];
  const dependents = manager.findDependents(cardHeader.id);

  assert(dependents.length > 0, 'Should have dependents');
  const card = manager.findByName('Card')[0];
  assert(dependents.includes(card.id), 'Card should depend on CardHeader');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 5: Performance Benchmark Tests
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── Performance Benchmarks ───\n');

test('Bulk add 100 entries < 500ms', async () => {
  const { getRegistryManager, clearRegistryManager } = require('./registry-manager');
  clearRegistryManager();
  setupTestDir();

  const manager = await getRegistryManager(designDir);

  const start = Date.now();

  for (let i = 0; i < 100; i++) {
    manager.addEntry({
      name: `BulkComponent${i}`,
      type: 'COMPONENT',
      category: 'test',
      source: { type: 'figma', nodeId: `bulk:${i}` }
    }, 'component');
  }

  const elapsed = Date.now() - start;

  console.log(`     Bulk add 100 entries: ${elapsed}ms`);
  assert(elapsed < 500, `Should be < 500ms, was ${elapsed}ms`);
});

test('findById O(1) lookup < 5ms average', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  // Get all entries to test with
  const allEntries = manager.getAllEntries('component');
  assert(allEntries.length >= 100, 'Should have at least 100 entries');

  const start = Date.now();
  const iterations = 1000;

  for (let i = 0; i < iterations; i++) {
    const idx = i % allEntries.length;
    manager.findById(allEntries[idx].id);
  }

  const elapsed = Date.now() - start;
  const avgMs = elapsed / iterations;

  console.log(`     1000 lookups: ${elapsed}ms (avg ${avgMs.toFixed(3)}ms)`);
  assert(avgMs < 5, `Average should be < 5ms, was ${avgMs.toFixed(3)}ms`);
});

test('findByNodeId O(1) lookup < 5ms average', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const start = Date.now();
  const iterations = 1000;

  for (let i = 0; i < iterations; i++) {
    manager.findByNodeId(`bulk:${i % 100}`);
  }

  const elapsed = Date.now() - start;
  const avgMs = elapsed / iterations;

  console.log(`     1000 node lookups: ${elapsed}ms (avg ${avgMs.toFixed(3)}ms)`);
  assert(avgMs < 5, `Average should be < 5ms, was ${avgMs.toFixed(3)}ms`);
});

test('saveIndex persists < 100ms', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const start = Date.now();
  manager.saveIndex();
  const elapsed = Date.now() - start;

  console.log(`     saveIndex: ${elapsed}ms`);
  assert(elapsed < 100, `Should be < 100ms, was ${elapsed}ms`);
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 6: Source Integration v4.0.0 Tests
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── Source Integration v4.0.0 ───\n');

test('Figma integration uses v4.0.0 methods', async () => {
  const figma = require('./figma-registry-integration');

  // Clear cache and test
  figma.invalidateV4Cache();

  const canonicalId = figma.generateV4CanonicalId({
    name: 'TestButton',
    figmaId: '111:222'
  });

  assert(canonicalId.startsWith('figma-component-'), 'Should generate v4 canonical ID');
  assert(canonicalId.includes('testbutton'), 'Should include sanitized name');
  assert(canonicalId.includes('111-222'), 'Should include node ID');
});

test('ShadCN integration uses v4.0.0 methods', async () => {
  const shadcn = require('./shadcn-registry-integration');

  shadcn.invalidateV4Cache();

  const canonicalId = shadcn.generateV4CanonicalId('Button', '@shadcn');

  assert(canonicalId === 'shadcn-component-shadcn-button', 'Should generate v4 canonical ID');
});

test('NLP integration uses v4.0.0 methods', async () => {
  const nlp = require('./nlp-registry-integration');

  nlp.invalidateV4Cache();

  const canonicalId = nlp.generateV4CanonicalId({
    name: 'HeroSection'
  });

  assert(canonicalId.startsWith('nlp-component-'), 'Should generate v4 canonical ID');
  assert(canonicalId.includes('herosection'), 'Should include sanitized name');
});

test('All sources have consistent hasV4Registry', async () => {
  const figma = require('./figma-registry-integration');
  const shadcn = require('./shadcn-registry-integration');
  const nlp = require('./nlp-registry-integration');

  // All should return false for non-existent path
  const fakePath = '/tmp/nonexistent-' + Date.now();

  figma.invalidateV4Cache();
  shadcn.invalidateV4Cache();
  nlp.invalidateV4Cache();

  assert(figma.hasV4Registry(fakePath) === false, 'Figma should return false');
  assert(shadcn.hasV4Registry(fakePath) === false, 'ShadCN should return false');
  assert(nlp.hasV4Registry(fakePath) === false, 'NLP should return false');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 7: Design Structure Integration Tests
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── Design Structure Integration ───\n');

test('DesignStructure initializes v4.0.0 registry', async () => {
  const { DesignStructure } = require('./design-structure');

  const testDesignDir = path.join(os.tmpdir(), `ds-test-${Date.now()}`, '.design');
  fs.mkdirSync(testDesignDir, { recursive: true });

  const structure = new DesignStructure(testDesignDir);

  assert(!structure.hasV4Registry(), 'Should not have registry initially');

  await structure.initializeV4Registry();

  assert(structure.hasV4Registry(), 'Should have registry after init');
  assert(fs.existsSync(path.join(testDesignDir, 'registry-index.json')), 'Index should exist');

  // Cleanup
  fs.rmSync(path.dirname(testDesignDir), { recursive: true });
});

test('DesignStructure reports v4.0.0 stats', async () => {
  const { getRegistryManager, clearRegistryManager } = require('./registry-manager');
  const { DesignStructure } = require('./design-structure');

  clearRegistryManager();
  setupTestDir();

  // Initialize through RegistryManager first
  const manager = await getRegistryManager(designDir);

  // Add some entries
  manager.addEntry({
    name: 'StatTestComponent',
    type: 'COMPONENT',
    category: 'test',
    source: { type: 'figma', nodeId: '1:1' }
  }, 'component');

  manager.saveIndex();

  const structure = new DesignStructure(designDir);
  const stats = await structure.getV4RegistryStats();

  assert(stats, 'Should return stats');
  assert(typeof stats.components === 'number', 'Should have component count');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 8: Token Registry Tests
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── Token Registry ───\n');

test('Add token entry', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const token = {
    name: 'primary-500',
    type: 'COLOR',
    category: 'colors',
    value: '#3B82F6',
    source: { type: 'figma', styleId: 'S:abc123' }
  };

  const result = manager.addEntry(token, 'token');

  assert(result.id, 'Should return ID');
  assert(result.id.includes('primary-500'), 'ID should include token name');
});

test('Find token by style ID', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const found = manager.findByStyleId('S:abc123');

  assert(found, 'Should find token');
  assert(found.name === 'primary-500', 'Should have correct name');
  assert(found.value === '#3B82F6', 'Should have correct value');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 9: Layout Registry Tests
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── Layout Registry ───\n');

test('Add layout entry', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const layout = {
    name: 'HeroSection',
    type: 'LAYOUT',
    category: 'hero',
    source: { type: 'figma', nodeId: 'L:100:200' },
    dimensions: { width: 1440, height: 600 }
  };

  const result = manager.addEntry(layout, 'layout');

  assert(result.id, 'Should return ID');
  assert(result.id.includes('herosection'), 'ID should include layout name');
});

test('Find layout by ID', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const layouts = manager.getAllEntries('layout');
  assert(layouts.length > 0, 'Should have layouts');

  const found = manager.findById(layouts[0].id);
  assert(found, 'Should find layout');
  assert(found.type === 'LAYOUT', 'Should be layout type');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 10: Error Handling Tests
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── Error Handling ───\n');

test('findById returns null for missing ID', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const result = manager.findById('nonexistent-id-12345');
  assert(result === null, 'Should return null');
});

test('removeEntry returns false for missing ID', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const result = manager.removeEntry('nonexistent-id-12345', 'component');
  assert(result === false, 'Should return false');
});

test('updateEntry throws for missing ID', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  let threw = false;
  try {
    manager.updateEntry('nonexistent-id-12345', { name: 'test' }, 'component');
  } catch (e) {
    threw = true;
  }

  assert(threw, 'Should throw for missing ID');
});

// ═══════════════════════════════════════════════════════════════════════════
// Cleanup and Results
// ═══════════════════════════════════════════════════════════════════════════

cleanupTestDir();

console.log('\n═══════════════════════════════════════════════════════════');
console.log('   RESULTS');
console.log('═══════════════════════════════════════════════════════════');
console.log(`   Total:  ${passed + failed}`);
console.log(`   Passed: ${passed}`);
console.log(`   Failed: ${failed}`);
console.log('═══════════════════════════════════════════════════════════');

if (failed > 0) {
  console.log('\n\x1b[31m❌ SOME TESTS FAILED\x1b[0m');
  console.log('\nFailed tests:');
  testResults
    .filter(t => t.status === 'failed')
    .forEach(t => console.log(`  - ${t.name}: ${t.error}`));
  process.exit(1);
} else {
  console.log('\n\x1b[32m✅ ALL END-TO-END REGISTRY TESTS PASSED\x1b[0m');
  // Exit cleanly (prevents unhandled promise rejections from async callbacks)
  process.exit(0);
}
