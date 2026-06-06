/**
 * registry-manager.test.js
 * Unit tests for RegistryManager class
 *
 * Run with: node registry-manager.test.js
 */

const fs = require('fs').promises;
const path = require('path');
const os = require('os');

const {
  RegistryManager,
  getRegistryManager,
  clearRegistryManager,
  INDEX_SCHEMA_VERSION,
  REGISTRY_TYPES,
  ID_SOURCES,
  ID_TYPES
} = require('./registry-manager');

// Test utilities
let testDir;
let testCount = 0;
let passCount = 0;
let failCount = 0;

async function setup() {
  testDir = path.join(os.tmpdir(), `registry-test-${Date.now()}`);
  await fs.mkdir(testDir, { recursive: true });
  clearRegistryManager();
}

async function teardown() {
  try {
    await fs.rm(testDir, { recursive: true, force: true });
  } catch {}
  clearRegistryManager();
}

function test(name, fn) {
  return async () => {
    testCount++;
    try {
      await fn();
      passCount++;
      console.log(`  ✅ ${name}`);
    } catch (error) {
      failCount++;
      console.log(`  ❌ ${name}`);
      console.log(`     Error: ${error.message}`);
    }
  };
}

function assertEqual(actual, expected, message = '') {
  const actualStr = JSON.stringify(actual);
  const expectedStr = JSON.stringify(expected);
  if (actualStr !== expectedStr) {
    throw new Error(`${message}\nExpected: ${expectedStr}\nActual: ${actualStr}`);
  }
}

function assertTrue(value, message = 'Expected true') {
  if (!value) throw new Error(message);
}

function assertFalse(value, message = 'Expected false') {
  if (value) throw new Error(message);
}

function assertContains(str, substr, message = '') {
  if (!str.includes(substr)) {
    throw new Error(`${message}\nExpected "${str}" to contain "${substr}"`);
  }
}

function assertNotNull(value, message = 'Expected non-null value') {
  if (value === null || value === undefined) throw new Error(message);
}

function assertNull(value, message = 'Expected null value') {
  if (value !== null && value !== undefined) throw new Error(message);
}

function assertGreaterThan(actual, expected, message = '') {
  if (actual <= expected) {
    throw new Error(`${message}\nExpected ${actual} > ${expected}`);
  }
}

// ==========================================================================
// TEST SUITES
// ==========================================================================

async function runInitializationTests() {
  console.log('\n📦 Initialization Tests');

  await test('constructor sets correct paths', async () => {
    const manager = new RegistryManager(testDir);
    assertEqual(manager.designRoot, testDir);
    assertContains(manager.indexPath, 'registry-index.json');
    assertContains(manager.registriesPath, 'registries');
  })();

  await test('initialize creates directories', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const registriesDir = path.join(testDir, 'registries');
    const stat = await fs.stat(registriesDir);
    assertTrue(stat.isDirectory(), 'registries directory should exist');
  })();

  await test('initialize creates empty index', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const indexPath = path.join(testDir, 'registry-index.json');
    const indexData = JSON.parse(await fs.readFile(indexPath, 'utf8'));

    assertEqual(indexData.schemaVersion, INDEX_SCHEMA_VERSION);
    assertNotNull(indexData.registries);
    assertNotNull(indexData.idIndex);
    assertNotNull(indexData.sourceMapping);
    assertNotNull(indexData.dependencyGraph);
  })();

  await test('initialize loads existing index', async () => {
    // Create existing index
    const existingIndex = {
      version: '1.0.0',
      schemaVersion: INDEX_SCHEMA_VERSION,
      lastUpdated: new Date().toISOString(),
      registries: {
        tokens: { path: 'test', count: 5, lastModified: null },
        components: { path: 'test', count: 3, lastModified: null },
        layouts: { path: 'test', count: 2, lastModified: null }
      },
      idIndex: { 'test-id': { type: 'components' } },
      sourceMapping: { '123:456': 'test-id' },
      dependencyGraph: {}
    };

    const indexPath = path.join(testDir, 'registry-index.json');
    await fs.writeFile(indexPath, JSON.stringify(existingIndex));

    clearRegistryManager();
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    assertEqual(Object.keys(manager.index.idIndex).length, 1);
    assertEqual(manager.index.sourceMapping['123:456'], 'test-id');
  })();

  await test('double initialize is safe', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();
    await manager.initialize(); // Should not throw
    assertTrue(manager._initialized);
  })();
}

async function runIdGenerationTests() {
  console.log('\n🆔 ID Generation Tests');

  await test('generateCanonicalId produces correct format', async () => {
    const manager = new RegistryManager(testDir);
    const id = manager.generateCanonicalId('figma-plugin', 'component', 'Button Primary', '123:456');
    assertEqual(id, 'figma-plugin-component-button-primary-123-456');
  })();

  await test('generateCanonicalId handles style IDs', async () => {
    const manager = new RegistryManager(testDir);
    const id = manager.generateCanonicalId('figma-plugin', 'token', 'Primary 500', 'S:774a6223930fe22b');
    assertContains(id, 'figma-plugin-token-primary-500-774a622');
  })();

  await test('slugify handles special characters', async () => {
    const manager = new RegistryManager(testDir);
    assertEqual(manager.slugify('Button/Primary'), 'button-primary');
    assertEqual(manager.slugify('Button  Primary'), 'button-primary');
    assertEqual(manager.slugify('Button@#$Primary'), 'button-primary');
  })();

  await test('slugify truncates long names', async () => {
    const manager = new RegistryManager(testDir);
    const longName = 'this-is-a-very-long-component-name-that-should-be-truncated';
    const slug = manager.slugify(longName);
    assertTrue(slug.length <= 30, `Slug length ${slug.length} should be <= 30`);
  })();

  await test('slugify handles empty/null input', async () => {
    const manager = new RegistryManager(testDir);
    assertEqual(manager.slugify(''), 'unnamed');
    assertEqual(manager.slugify(null), 'unnamed');
  })();

  await test('extractIdSuffix handles node ID format', async () => {
    const manager = new RegistryManager(testDir);
    assertEqual(manager.extractIdSuffix('123:456'), '123-456');
    assertEqual(manager.extractIdSuffix('1:2'), '1-2');
  })();

  await test('extractIdSuffix handles style ID format', async () => {
    const manager = new RegistryManager(testDir);
    const suffix = manager.extractIdSuffix('S:774a6223930fe22b2d4644eb');
    assertEqual(suffix, '774a622');
  })();

  await test('extractIdSuffix handles null', async () => {
    const manager = new RegistryManager(testDir);
    assertNull(manager.extractIdSuffix(null));
  })();

  await test('generateCanonicalId validates source', async () => {
    const manager = new RegistryManager(testDir);
    try {
      manager.generateCanonicalId('invalid-source', 'component', 'Test', '123:456');
      throw new Error('Should have thrown');
    } catch (error) {
      assertContains(error.message, 'Invalid source');
    }
  })();

  await test('generateCanonicalId validates type', async () => {
    const manager = new RegistryManager(testDir);
    try {
      manager.generateCanonicalId('figma-plugin', 'invalid-type', 'Test', '123:456');
      throw new Error('Should have thrown');
    } catch (error) {
      assertContains(error.message, 'Invalid type');
    }
  })();

  await test('IDs are unique for different inputs', async () => {
    const manager = new RegistryManager(testDir);
    const id1 = manager.generateCanonicalId('figma-plugin', 'component', 'Button', '123:456');
    const id2 = manager.generateCanonicalId('figma-plugin', 'component', 'Button', '123:457');
    assertTrue(id1 !== id2, 'IDs should be different');
  })();

  await test('IDs are consistent for same inputs', async () => {
    const manager = new RegistryManager(testDir);
    const id1 = manager.generateCanonicalId('figma-plugin', 'component', 'Button', '123:456');
    const id2 = manager.generateCanonicalId('figma-plugin', 'component', 'Button', '123:456');
    assertEqual(id1, id2);
  })();
}

async function runRegistryCrudTests() {
  console.log('\n📝 Registry CRUD Tests');

  await test('createEmptyRegistry has correct structure', async () => {
    const manager = new RegistryManager(testDir);
    const registry = manager.createEmptyRegistry('components');

    assertEqual(registry.version, INDEX_SCHEMA_VERSION);
    assertEqual(registry.type, 'components');
    assertNotNull(registry.metadata);
    assertEqual(registry.metadata.entryCount, 0);
    assertNotNull(registry.entries);
  })();

  await test('createEmptyRegistry validates type', async () => {
    const manager = new RegistryManager(testDir);
    try {
      manager.createEmptyRegistry('invalid');
      throw new Error('Should have thrown');
    } catch (error) {
      assertContains(error.message, 'Invalid registry type');
    }
  })();

  await test('loadRegistry creates if not exists', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const registry = await manager.loadRegistry('components');
    assertNotNull(registry);
    assertEqual(registry.type, 'components');
  })();

  await test('loadRegistry caches after first load', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const reg1 = await manager.loadRegistry('components');
    const reg2 = await manager.loadRegistry('components');
    assertTrue(reg1 === reg2, 'Should return same cached instance');
  })();

  await test('loadRegistry forceReload bypasses cache', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    await manager.loadRegistry('components');
    manager.registries.components.test = true;

    const fresh = await manager.loadRegistry('components', true);
    assertFalse(fresh.test, 'Should have fresh data');
  })();

  await test('saveRegistry updates metadata', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const registry = await manager.loadRegistry('components');
    registry.entries['test-id'] = { name: 'Test' };

    await manager.saveRegistry('components');

    const registryPath = manager.getRegistryPath('components');
    const saved = JSON.parse(await fs.readFile(registryPath, 'utf8'));

    assertEqual(saved.metadata.entryCount, 1);
    assertNotNull(saved.metadata.lastUpdated);
  })();

  await test('saveRegistry updates index', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const registry = await manager.loadRegistry('tokens');
    registry.entries['test-token'] = { name: 'Test Token' };
    await manager.saveRegistry('tokens');

    assertEqual(manager.index.registries.tokens.count, 1);
  })();
}

async function runEntryOperationsTests() {
  console.log('\n📄 Entry Operations Tests');

  await test('addEntry generates canonical ID', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const id = await manager.addEntry('components', {
      name: 'Button',
      source: { type: 'figma-plugin', nodeId: '123:456' }
    });

    assertContains(id, 'figma-plugin-component-button-');
  })();

  await test('addEntry uses provided ID', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const id = await manager.addEntry('components', {
      id: 'custom-id-123',
      name: 'Custom Button',
      source: { type: 'figma-plugin', nodeId: '789:012' }
    });

    assertEqual(id, 'custom-id-123');
  })();

  await test('addEntry updates idIndex', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const id = await manager.addEntry('components', {
      name: 'Card',
      source: { type: 'figma-plugin', nodeId: '111:222' }
    });

    assertNotNull(manager.index.idIndex[id]);
    assertEqual(manager.index.idIndex[id].type, 'components');
  })();

  await test('addEntry updates sourceMapping for nodeId', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const id = await manager.addEntry('components', {
      name: 'Modal',
      source: { type: 'figma-plugin', nodeId: '333:444' }
    });

    assertEqual(manager.index.sourceMapping['333:444'], id);
  })();

  await test('addEntry updates sourceMapping for styleId', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const id = await manager.addEntry('tokens', {
      name: 'Primary Color',
      source: { type: 'figma-plugin', styleId: 'S:abc123' }
    });

    assertEqual(manager.index.sourceMapping['S:abc123'], id);
  })();

  await test('addEntry emits entry-added event', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    let emittedEvent = null;
    manager.on('entry-added', (event) => { emittedEvent = event; });

    const id = await manager.addEntry('components', {
      name: 'EventTest',
      source: { type: 'figma-plugin', nodeId: '555:666' }
    });

    assertNotNull(emittedEvent);
    assertEqual(emittedEvent.id, id);
    assertEqual(emittedEvent.type, 'components');
  })();

  await test('updateEntry merges without overwriting', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const id = await manager.addEntry('components', {
      name: 'MergeTest',
      category: 'buttons',
      source: { type: 'figma-plugin', nodeId: '777:888' }
    });

    await manager.updateEntry('components', id, {
      category: 'forms'
    });

    const entry = await manager.findById(id);
    assertEqual(entry.name, 'MergeTest'); // Preserved
    assertEqual(entry.category, 'forms'); // Updated
  })();

  await test('updateEntry throws for missing ID', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    try {
      await manager.updateEntry('components', 'nonexistent-id', { name: 'Test' });
      throw new Error('Should have thrown');
    } catch (error) {
      assertContains(error.message, 'Entry not found');
    }
  })();

  await test('updateEntry emits entry-updated event', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const id = await manager.addEntry('components', {
      name: 'UpdateEventTest',
      source: { type: 'figma-plugin', nodeId: '999:000' }
    });

    let emittedEvent = null;
    manager.on('entry-updated', (event) => { emittedEvent = event; });

    await manager.updateEntry('components', id, { category: 'updated' });

    assertNotNull(emittedEvent);
    assertEqual(emittedEvent.id, id);
  })();

  await test('removeEntry cleans up all indexes', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const id = await manager.addEntry('components', {
      name: 'ToRemove',
      source: { type: 'figma-plugin', nodeId: 'remove:me' }
    });

    await manager.removeEntry('components', id);

    assertNull(manager.index.idIndex[id]);
    assertNull(manager.index.sourceMapping['remove:me']);

    const entry = await manager.findById(id);
    assertNull(entry);
  })();

  await test('removeEntry emits entry-removed event', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const id = await manager.addEntry('components', {
      name: 'RemoveEventTest',
      source: { type: 'figma-plugin', nodeId: 'event:remove' }
    });

    let emittedEvent = null;
    manager.on('entry-removed', (event) => { emittedEvent = event; });

    await manager.removeEntry('components', id);

    assertNotNull(emittedEvent);
    assertEqual(emittedEvent.id, id);
  })();

  await test('removeEntry returns false for missing ID', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const result = await manager.removeEntry('components', 'nonexistent');
    assertFalse(result);
  })();
}

async function runQueryOperationsTests() {
  console.log('\n🔍 Query Operations Tests');

  await test('findById returns correct entry', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const id = await manager.addEntry('components', {
      name: 'FindMe',
      source: { type: 'figma-plugin', nodeId: 'find:me' }
    });

    const entry = await manager.findById(id);
    assertEqual(entry.name, 'FindMe');
  })();

  await test('findById returns null for missing ID', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const entry = await manager.findById('nonexistent-id');
    assertNull(entry);
  })();

  await test('findByNodeId resolves via sourceMapping', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    await manager.addEntry('components', {
      name: 'NodeIdTest',
      source: { type: 'figma-plugin', nodeId: 'node:123' }
    });

    const entry = await manager.findByNodeId('node:123');
    assertEqual(entry.name, 'NodeIdTest');
  })();

  await test('findByStyleId resolves via sourceMapping', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    await manager.addEntry('tokens', {
      name: 'StyleIdTest',
      source: { type: 'figma-plugin', styleId: 'S:style123' }
    });

    const entry = await manager.findByStyleId('S:style123');
    assertEqual(entry.name, 'StyleIdTest');
  })();

  await test('findByName finds partial matches', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    await manager.addEntry('components', {
      name: 'Button Primary',
      source: { type: 'figma-plugin', nodeId: 'btn:1' }
    });
    await manager.addEntry('components', {
      name: 'Button Secondary',
      source: { type: 'figma-plugin', nodeId: 'btn:2' }
    });
    await manager.addEntry('components', {
      name: 'Card',
      source: { type: 'figma-plugin', nodeId: 'card:1' }
    });

    const results = await manager.findByName('button');
    assertEqual(results.length, 2);
  })();

  await test('findByName is case insensitive', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    await manager.addEntry('components', {
      name: 'CaseSensitive',
      source: { type: 'figma-plugin', nodeId: 'case:1' }
    });

    const lower = await manager.findByName('casesensitive');
    const upper = await manager.findByName('CASESENSITIVE');

    assertEqual(lower.length, 1);
    assertEqual(upper.length, 1);
  })();

  await test('findByCategory filters correctly', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    await manager.addEntry('components', {
      name: 'Cat1',
      category: 'buttons',
      source: { type: 'figma-plugin', nodeId: 'cat:1' }
    });
    await manager.addEntry('components', {
      name: 'Cat2',
      category: 'forms',
      source: { type: 'figma-plugin', nodeId: 'cat:2' }
    });

    const buttons = await manager.findByCategory('buttons');
    assertEqual(buttons.length, 1);
    assertEqual(buttons[0].name, 'Cat1');
  })();

  await test('findBySource filters by source type', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    await manager.addEntry('components', {
      name: 'FromFigma',
      source: { type: 'figma-plugin', nodeId: 'src:1' }
    });
    await manager.addEntry('components', {
      name: 'FromShadcn',
      source: { type: 'shadcn', nodeId: 'src:2' }
    });

    const figma = await manager.findBySource('figma-plugin');
    const shadcn = await manager.findBySource('shadcn');

    assertGreaterThan(figma.length, 0);
    assertEqual(figma.filter(e => e.name === 'FromFigma').length, 1);
    assertEqual(shadcn.filter(e => e.name === 'FromShadcn').length, 1);
  })();

  await test('pagination works correctly', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    // Add 10 entries
    for (let i = 0; i < 10; i++) {
      await manager.addEntry('components', {
        name: `Item${i}`,
        source: { type: 'figma-plugin', nodeId: `page:${i}` }
      });
    }

    const page1 = await manager.findByName('Item', 'components', { offset: 0, limit: 3 });
    const page2 = await manager.findByName('Item', 'components', { offset: 3, limit: 3 });

    assertEqual(page1.length, 3);
    assertEqual(page2.length, 3);
  })();

  await test('getAllEntries returns all entries', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    await manager.addEntry('tokens', {
      name: 'Token1',
      source: { type: 'figma-plugin', styleId: 'all:1' }
    });
    await manager.addEntry('tokens', {
      name: 'Token2',
      source: { type: 'figma-plugin', styleId: 'all:2' }
    });

    const all = await manager.getAllEntries('tokens');
    assertGreaterThan(all.length, 0);
  })();
}

async function runDependencyGraphTests() {
  console.log('\n🕸️ Dependency Graph Tests');

  await test('updateDependencies creates graph entries', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const tokenId = await manager.addEntry('tokens', {
      name: 'Primary',
      source: { type: 'figma-plugin', styleId: 'dep:token' }
    });

    const buttonId = await manager.addEntry('components', {
      name: 'Button',
      source: { type: 'figma-plugin', nodeId: 'dep:btn' }
    });

    await manager.updateDependencies(buttonId, { tokens: [tokenId] });

    assertNotNull(manager.index.dependencyGraph[tokenId]);
    assertTrue(
      manager.index.dependencyGraph[tokenId].usedBy.components.includes(buttonId),
      'Token should be used by button component'
    );
  })();

  await test('findDependents returns correct entries', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const tokenId = await manager.addEntry('tokens', {
      name: 'DepToken',
      source: { type: 'figma-plugin', styleId: 'find:dep:token' }
    });

    const btn1 = await manager.addEntry('components', {
      name: 'Btn1',
      source: { type: 'figma-plugin', nodeId: 'find:dep:1' }
    });

    const btn2 = await manager.addEntry('components', {
      name: 'Btn2',
      source: { type: 'figma-plugin', nodeId: 'find:dep:2' }
    });

    await manager.updateDependencies(btn1, { tokens: [tokenId] });
    await manager.updateDependencies(btn2, { tokens: [tokenId] });

    const dependents = await manager.findDependents(tokenId);

    assertEqual(dependents.components.length, 2);
    assertTrue(dependents.components.includes(btn1));
    assertTrue(dependents.components.includes(btn2));
  })();

  await test('findDependencies returns correct entries', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const token1 = await manager.addEntry('tokens', {
      name: 'T1',
      source: { type: 'figma-plugin', styleId: 'deps:t1' }
    });

    const token2 = await manager.addEntry('tokens', {
      name: 'T2',
      source: { type: 'figma-plugin', styleId: 'deps:t2' }
    });

    const btn = await manager.addEntry('components', {
      name: 'BtnDeps',
      source: { type: 'figma-plugin', nodeId: 'deps:btn' }
    });

    await manager.updateDependencies(btn, { tokens: [token1, token2] });

    const dependencies = await manager.findDependencies(btn);

    assertEqual(dependencies.tokens.length, 2);
    assertTrue(dependencies.tokens.includes(token1));
    assertTrue(dependencies.tokens.includes(token2));
  })();

  await test('updateDependencies clears old dependencies', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const oldToken = await manager.addEntry('tokens', {
      name: 'OldToken',
      source: { type: 'figma-plugin', styleId: 'clear:old' }
    });

    const newToken = await manager.addEntry('tokens', {
      name: 'NewToken',
      source: { type: 'figma-plugin', styleId: 'clear:new' }
    });

    const btn = await manager.addEntry('components', {
      name: 'ClearBtn',
      source: { type: 'figma-plugin', nodeId: 'clear:btn' }
    });

    // First dependency
    await manager.updateDependencies(btn, { tokens: [oldToken] });

    // Update to new dependency
    await manager.updateDependencies(btn, { tokens: [newToken] });

    const oldDeps = await manager.findDependents(oldToken);
    const newDeps = await manager.findDependents(newToken);

    assertEqual(oldDeps.components.length, 0);
    assertTrue(newDeps.components.includes(btn));
  })();

  await test('rebuildDependencyGraph reconstructs from entries', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const token = await manager.addEntry('tokens', {
      name: 'RebuildToken',
      source: { type: 'figma-plugin', styleId: 'rebuild:token' }
    });

    const btn = await manager.addEntry('components', {
      name: 'RebuildBtn',
      source: { type: 'figma-plugin', nodeId: 'rebuild:btn' },
      dependencies: { tokens: [token], components: [] }
    });

    // Corrupt the graph
    manager.index.dependencyGraph = {};

    // Rebuild
    await manager.rebuildDependencyGraph();

    // Verify reconstruction
    const dependents = await manager.findDependents(token);
    assertTrue(dependents.components.includes(btn));
  })();

  await test('dependency graph persists after save', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    const token = await manager.addEntry('tokens', {
      name: 'PersistToken',
      source: { type: 'figma-plugin', styleId: 'persist:token' }
    });

    const btn = await manager.addEntry('components', {
      name: 'PersistBtn',
      source: { type: 'figma-plugin', nodeId: 'persist:btn' }
    });

    await manager.updateDependencies(btn, { tokens: [token] });

    // Reload manager
    clearRegistryManager();
    const manager2 = new RegistryManager(testDir);
    await manager2.initialize();

    const dependents = await manager2.findDependents(token);
    assertTrue(dependents.components.includes(btn));
  })();
}

async function runUtilityTests() {
  console.log('\n🔧 Utility Tests');

  await test('fileExists returns true for existing file', async () => {
    const manager = new RegistryManager(testDir);
    const testFile = path.join(testDir, 'test-exists.txt');
    await fs.writeFile(testFile, 'test');

    assertTrue(await manager.fileExists(testFile));
  })();

  await test('fileExists returns false for missing file', async () => {
    const manager = new RegistryManager(testDir);
    assertFalse(await manager.fileExists('/nonexistent/file'));
  })();

  await test('writeJSON creates parent directories', async () => {
    const manager = new RegistryManager(testDir);
    const nestedPath = path.join(testDir, 'a', 'b', 'c', 'test.json');

    await manager.writeJSON(nestedPath, { test: true });

    const data = JSON.parse(await fs.readFile(nestedPath, 'utf8'));
    assertTrue(data.test);
  })();

  await test('writeJSON is atomic (uses temp file)', async () => {
    const manager = new RegistryManager(testDir);
    const targetPath = path.join(testDir, 'atomic-test.json');

    await manager.writeJSON(targetPath, { atomic: true });

    // Temp file should not exist
    const tempPath = `${targetPath}.tmp`;
    assertFalse(await manager.fileExists(tempPath));
  })();

  await test('validateEntry catches missing name', async () => {
    const manager = new RegistryManager(testDir);
    const result = manager.validateEntry('component', { source: { type: 'figma-plugin' } });

    assertFalse(result.valid);
    assertTrue(result.errors.some(e => e.includes('name')));
  })();

  await test('validateEntry catches missing source', async () => {
    const manager = new RegistryManager(testDir);
    const result = manager.validateEntry('component', { name: 'Test' });

    assertFalse(result.valid);
    assertTrue(result.errors.some(e => e.includes('source')));
  })();

  await test('validateEntry passes valid entry', async () => {
    const manager = new RegistryManager(testDir);
    const result = manager.validateEntry('component', {
      name: 'Test',
      source: { type: 'figma-plugin' }
    });

    assertTrue(result.valid);
    assertEqual(result.errors.length, 0);
  })();

  await test('validateIndex detects missing fields', async () => {
    const manager = new RegistryManager(testDir);
    manager.index = {}; // Invalid index

    const result = manager.validateIndex();
    assertFalse(result.valid);
  })();

  await test('getStats returns accurate counts', async () => {
    const manager = new RegistryManager(testDir);
    await manager.initialize();

    await manager.addEntry('components', {
      name: 'StatsBtn',
      source: { type: 'figma-plugin', nodeId: 'stats:1' }
    });

    await manager.addEntry('tokens', {
      name: 'StatsToken',
      source: { type: 'figma-plugin', styleId: 'stats:2' }
    });

    const stats = await manager.getStats();

    assertEqual(stats.schemaVersion, INDEX_SCHEMA_VERSION);
    assertGreaterThan(stats.totals.entries, 0);
    assertGreaterThan(stats.totals.idMappings, 0);
  })();
}

async function runSingletonTests() {
  console.log('\n🔄 Singleton Tests');

  await test('getRegistryManager returns same instance for same path', async () => {
    clearRegistryManager();

    const mgr1 = await getRegistryManager(testDir);
    const mgr2 = await getRegistryManager(testDir);

    assertTrue(mgr1 === mgr2, 'Should be same instance');
  })();

  await test('getRegistryManager creates new instance for different path', async () => {
    clearRegistryManager();

    const dir2 = path.join(testDir, 'other');
    await fs.mkdir(dir2, { recursive: true });

    const mgr1 = await getRegistryManager(testDir);
    clearRegistryManager();
    const mgr2 = await getRegistryManager(dir2);

    assertTrue(mgr1 !== mgr2, 'Should be different instances');
  })();

  await test('clearRegistryManager clears the singleton', async () => {
    const mgr1 = await getRegistryManager(testDir);
    clearRegistryManager();
    const mgr2 = await getRegistryManager(testDir);

    assertTrue(mgr1 !== mgr2, 'Should be new instance after clear');
  })();
}

// ==========================================================================
// RUN ALL TESTS
// ==========================================================================

async function runAllTests() {
  console.log('================================================');
  console.log('   RegistryManager Unit Tests');
  console.log('================================================');

  await setup();

  try {
    await runInitializationTests();
    await teardown();
    await setup();

    await runIdGenerationTests();
    await teardown();
    await setup();

    await runRegistryCrudTests();
    await teardown();
    await setup();

    await runEntryOperationsTests();
    await teardown();
    await setup();

    await runQueryOperationsTests();
    await teardown();
    await setup();

    await runDependencyGraphTests();
    await teardown();
    await setup();

    await runUtilityTests();
    await teardown();
    await setup();

    await runSingletonTests();
  } finally {
    await teardown();
  }

  console.log('\n================================================');
  console.log('   Test Results');
  console.log('================================================');
  console.log(`Total:  ${testCount}`);
  console.log(`Passed: ${passCount}`);
  console.log(`Failed: ${failCount}`);
  console.log('');

  if (failCount > 0) {
    console.log('❌ SOME TESTS FAILED');
    process.exit(1);
  } else {
    console.log('✅ ALL TESTS PASSED');
    process.exit(0);
  }
}

// Run tests
runAllTests().catch(error => {
  console.error('Test runner error:', error);
  process.exit(1);
});
