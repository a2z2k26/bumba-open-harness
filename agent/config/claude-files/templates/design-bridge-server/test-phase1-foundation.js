/**
 * Phase 1 Foundation & Schema Test Suite
 *
 * Tests all Sprint 1.1-1.8 deliverables:
 * - Registry Reader extensions (v3.0.0 schema)
 * - Schema migration
 * - Atomic writes with backup
 * - AutoRegistrar module
 */

const path = require('path');
const fs = require('fs').promises;
const fsSync = require('fs');

// Modules under test
const {
  readComponentRegistry,
  writeComponentRegistry,
  readAndMigrateRegistry,
  validateRegistrySchema,
  migrateRegistrySchema,
  createEmptyRegistry,
  getComponentById,
  CURRENT_SCHEMA_VERSION,
  invalidateCache
} = require('./registry-reader');

const { AutoRegistrar } = require('./auto-registrar');
const { ContentHasher } = require('./content-hasher');

// Test directory
const TEST_DIR = path.join(__dirname, '.test-phase1-' + Date.now());
const REGISTRY_PATH = path.join(TEST_DIR, '.design', 'componentRegistry.json');

// Test results tracking
const results = {
  passed: 0,
  failed: 0,
  tests: []
};

// ============================================================================
// Test Utilities
// ============================================================================

function test(name, fn) {
  return { name, fn };
}

async function runTest(testCase) {
  const startTime = Date.now();
  try {
    await testCase.fn();
    results.passed++;
    results.tests.push({ name: testCase.name, status: 'PASS', time: Date.now() - startTime });
    console.log(`  ✅ ${testCase.name}`);
    return true;
  } catch (error) {
    results.failed++;
    results.tests.push({ name: testCase.name, status: 'FAIL', error: error.message, time: Date.now() - startTime });
    console.log(`  ❌ ${testCase.name}`);
    console.log(`     Error: ${error.message}`);
    return false;
  }
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message || 'Assertion failed');
  }
}

function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new Error(`${message || 'Assertion failed'}: expected "${expected}", got "${actual}"`);
  }
}

function assertExists(value, message) {
  if (value === undefined || value === null) {
    throw new Error(`${message || 'Value should exist'}: got ${value}`);
  }
}

// ============================================================================
// Setup / Teardown
// ============================================================================

async function setup() {
  // Create test directory
  await fs.mkdir(path.join(TEST_DIR, '.design'), { recursive: true });
  invalidateCache();
}

async function teardown() {
  // Clean up test directory
  try {
    await fs.rm(TEST_DIR, { recursive: true, force: true });
  } catch (e) {
    // Ignore cleanup errors
  }
}

// ============================================================================
// Test Suites
// ============================================================================

const schemaTests = [
  test('CURRENT_SCHEMA_VERSION is 3.0.0', async () => {
    assertEqual(CURRENT_SCHEMA_VERSION, '3.0.0', 'Schema version mismatch');
  }),

  test('createEmptyRegistry() returns v3.0.0 schema', async () => {
    const empty = createEmptyRegistry();
    assertEqual(empty.version, '3.0.0', 'Version should be 3.0.0');
    assertExists(empty.metadata.schemaVersion, 'Should have schemaVersion in metadata');
    assertEqual(empty.metadata.schemaVersion, '3.0.0', 'Metadata schemaVersion should be 3.0.0');
    assertExists(empty.metadata.createdAt, 'Should have createdAt');
    assert(typeof empty.components === 'object', 'Should have components object');
  }),

  test('validateRegistrySchema() accepts valid v3 registry', async () => {
    const registry = {
      version: '3.0.0',
      components: {
        'test-button-123': {
          name: 'Test Button',
          transformation: {
            state: 'imported'
          }
        }
      }
    };
    // Should not throw
    validateRegistrySchema(registry);
  }),

  test('validateRegistrySchema() warns on invalid transformation state', async () => {
    const registry = {
      version: '3.0.0',
      components: {
        'test-button-123': {
          name: 'Test Button',
          transformation: {
            state: 'invalid-state'
          }
        }
      }
    };
    // Should not throw (just warn)
    validateRegistrySchema(registry);
  }),

  test('validateRegistrySchema() rejects missing components', async () => {
    const registry = { version: '3.0.0' };
    let threw = false;
    try {
      validateRegistrySchema(registry);
    } catch (e) {
      threw = true;
    }
    assert(threw, 'Should throw for missing components');
  })
];

const migrationTests = [
  test('migrateRegistrySchema() migrates v2 to v3', async () => {
    const v2Registry = {
      version: '2.0.0',
      metadata: { lastUpdated: '2024-01-01T00:00:00.000Z' },
      components: {
        'old-button': {
          name: 'Old Button',
          transformedTo: ['react'],
          outputPaths: { react: 'src/components/OldButton.tsx' },
          updatedAt: '2024-01-01T00:00:00.000Z'
        }
      }
    };

    const migrated = migrateRegistrySchema(v2Registry);

    assertEqual(migrated.version, '3.0.0', 'Should upgrade to 3.0.0');
    assertExists(migrated.metadata.migratedAt, 'Should have migratedAt');
    assertEqual(migrated.metadata.previousVersion, '2.0.0', 'Should track previous version');

    const component = migrated.components['old-button'];
    assertExists(component.transformation, 'Should have transformation');
    assertEqual(component.transformation.state, 'transformed', 'Should infer transformed state');
    assertEqual(component.transformation.framework, 'react', 'Should infer framework');
    assertExists(component.syncMetadata, 'Should have syncMetadata');
  }),

  test('migrateRegistrySchema() handles v1 registry', async () => {
    const v1Registry = {
      components: {
        'simple-button': {
          name: 'Simple Button'
        }
      }
    };

    const migrated = migrateRegistrySchema(v1Registry);

    assertEqual(migrated.version, '3.0.0', 'Should upgrade to 3.0.0');
    const component = migrated.components['simple-button'];
    assertEqual(component.transformation.state, 'imported', 'Should default to imported');
  }),

  test('migrateRegistrySchema() is idempotent for v3', async () => {
    const v3Registry = {
      version: '3.0.0',
      metadata: { schemaVersion: '3.0.0' },
      components: {
        'v3-button': {
          name: 'V3 Button',
          transformation: { state: 'transformed', framework: 'react' },
          syncMetadata: { syncCount: 5 }
        }
      }
    };

    const migrated = migrateRegistrySchema(v3Registry);

    // Should be unchanged
    assertEqual(migrated.components['v3-button'].syncMetadata.syncCount, 5, 'Should not modify existing v3 data');
  })
];

const writeTests = [
  test('writeComponentRegistry() creates file atomically', async () => {
    const registry = createEmptyRegistry();
    registry.components['test-1'] = { name: 'Test Component 1' };

    await writeComponentRegistry(TEST_DIR, registry);

    // Verify file exists
    const stat = await fs.stat(REGISTRY_PATH);
    assert(stat.isFile(), 'Registry file should exist');

    // Verify content
    const content = JSON.parse(await fs.readFile(REGISTRY_PATH, 'utf8'));
    assertEqual(content.version, '3.0.0', 'Should have correct version');
    assertExists(content.components['test-1'], 'Should have component');
  }),

  test('writeComponentRegistry() creates backup on update', async () => {
    const registry = createEmptyRegistry();
    registry.components['test-1'] = { name: 'Original' };
    await writeComponentRegistry(TEST_DIR, registry);

    // Update
    registry.components['test-1'].name = 'Updated';
    await writeComponentRegistry(TEST_DIR, registry, { createBackup: true });

    // Verify backup exists
    const backupPath = REGISTRY_PATH + '.bak';
    const backupStat = await fs.stat(backupPath);
    assert(backupStat.isFile(), 'Backup file should exist');

    // Verify backup has original content
    const backup = JSON.parse(await fs.readFile(backupPath, 'utf8'));
    assertEqual(backup.components['test-1'].name, 'Original', 'Backup should have original content');
  }),

  test('writeComponentRegistry() invalidates cache', async () => {
    invalidateCache();

    const registry = createEmptyRegistry();
    registry.components['cache-test'] = { name: 'Cache Test' };
    await writeComponentRegistry(TEST_DIR, registry);

    // Read should get fresh data
    const read1 = await readComponentRegistry(TEST_DIR);
    assertExists(read1.components['cache-test'], 'Should find component after write');

    // Update
    registry.components['cache-test-2'] = { name: 'Cache Test 2' };
    await writeComponentRegistry(TEST_DIR, registry);

    // Read should get updated data (cache invalidated)
    const read2 = await readComponentRegistry(TEST_DIR, { forceRefresh: true });
    assertExists(read2.components['cache-test-2'], 'Should find new component after update');
  }),

  test('writeComponentRegistry() creates directory if needed', async () => {
    const newDir = path.join(TEST_DIR, 'subdir');
    const registry = createEmptyRegistry();

    await writeComponentRegistry(newDir, registry);

    const stat = await fs.stat(path.join(newDir, '.design', 'componentRegistry.json'));
    assert(stat.isFile(), 'Should create registry in new directory');
  })
];

const autoRegistrarTests = [
  test('AutoRegistrar instantiates correctly', async () => {
    const registrar = new AutoRegistrar({ projectPath: TEST_DIR });
    assertExists(registrar, 'Should create instance');
    assertEqual(registrar.projectPath, TEST_DIR, 'Should have correct project path');
    assert(registrar.autoRegisterOnImport === true, 'Should default autoRegisterOnImport to true');
    assert(registrar.emitEvents === true, 'Should default emitEvents to true');
  }),

  test('generateComponentId() creates correct format for Figma', async () => {
    const registrar = new AutoRegistrar({ projectPath: TEST_DIR });

    const id = registrar.generateComponentId(
      { name: 'Primary Button' },
      { type: 'figma-plugin', nodeId: '1234:5678' }
    );

    assertEqual(id, 'figma-plugin-primary-button-1234-5678', 'Should generate correct ID format');
  }),

  test('generateComponentId() creates hash-based ID for non-Figma', async () => {
    const registrar = new AutoRegistrar({ projectPath: TEST_DIR });

    const id = registrar.generateComponentId(
      { name: 'ShadCN Button' },
      { type: 'shadcn' }
    );

    assert(id.startsWith('shadcn-shadcn-button-'), 'Should have correct prefix');
    assert(id.length > 20, 'Should include hash suffix');
  }),

  test('createRegistryEntry() creates v3.0.0 compliant entry', async () => {
    const registrar = new AutoRegistrar({ projectPath: TEST_DIR });

    const entry = registrar.createRegistryEntry(
      { name: 'Test Card', type: 'COMPONENT', category: 'containers' },
      { type: 'figma-mcp', nodeId: '9999:1111', fileKey: 'abc123' }
    );

    // Check structure
    assertExists(entry.id, 'Should have id');
    assertEqual(entry.name, 'Test Card', 'Should have name');
    assertEqual(entry.category, 'containers', 'Should preserve category');

    // Check source
    assertExists(entry.source, 'Should have source');
    assertEqual(entry.source.type, 'figma-mcp', 'Should have source type');
    assertEqual(entry.source.fileKey, 'abc123', 'Should have file key');

    // Check v3.0.0 fields
    assertExists(entry.transformation, 'Should have transformation');
    assertEqual(entry.transformation.state, 'imported', 'Should start as imported');
    assert(entry.transformation.framework === null, 'Framework should be null initially');

    assertExists(entry.syncMetadata, 'Should have syncMetadata');
    assertExists(entry.syncMetadata.lastFigmaSync, 'Should have lastFigmaSync');
    assertEqual(entry.syncMetadata.syncCount, 1, 'Should start with syncCount 1');
    assert(entry.syncMetadata.userModified === false, 'userModified should be false');

    // Check metadata
    assertExists(entry.metadata, 'Should have metadata');
    assertExists(entry.metadata.createdAt, 'Should have createdAt');
    assertEqual(entry.metadata.schemaVersion, '3.0.0', 'Should have schema version');
  }),

  test('registerComponent() registers new component', async () => {
    invalidateCache();
    const registrar = new AutoRegistrar({ projectPath: TEST_DIR });

    // Create empty registry first
    await writeComponentRegistry(TEST_DIR, createEmptyRegistry());

    const result = await registrar.registerComponent(
      { name: 'New Button', type: 'COMPONENT' },
      { type: 'figma-plugin', nodeId: '111:222' }
    );

    assert(result.success, 'Should succeed');
    assert(result.isNew, 'Should be new');
    assertExists(result.id, 'Should have ID');
    assertExists(result.entry, 'Should have entry');
    assertEqual(result.entry.transformation.state, 'imported', 'Should be imported state');
  }),

  test('registerComponent() updates existing component', async () => {
    invalidateCache();
    const registrar = new AutoRegistrar({ projectPath: TEST_DIR });

    // Create registry with existing component
    const registry = createEmptyRegistry();
    registry.components['figma-plugin-existing-button-333-444'] = {
      name: 'Existing Button',
      syncMetadata: { syncCount: 1, lastFigmaSync: '2024-01-01T00:00:00.000Z' },
      metadata: { updatedAt: '2024-01-01T00:00:00.000Z' }
    };
    await writeComponentRegistry(TEST_DIR, registry);

    const result = await registrar.registerComponent(
      { name: 'Existing Button' },
      { type: 'figma-plugin', nodeId: '333:444' }
    );

    assert(result.success, 'Should succeed');
    assert(!result.isNew, 'Should not be new');
    assertEqual(result.entry.syncMetadata.syncCount, 2, 'Should increment sync count');
  }),

  test('registerComponent() emits events', async () => {
    invalidateCache();
    const registrar = new AutoRegistrar({ projectPath: TEST_DIR, emitEvents: true });

    await writeComponentRegistry(TEST_DIR, createEmptyRegistry());

    let eventFired = false;
    let eventData = null;

    registrar.onRegistered((data) => {
      eventFired = true;
      eventData = data;
    });

    await registrar.registerComponent(
      { name: 'Event Test' },
      { type: 'figma-plugin', nodeId: '555:666' }
    );

    assert(eventFired, 'Should fire registered event');
    assertExists(eventData.id, 'Event should have id');
    assert(eventData.isNew, 'Event should indicate new component');
  }),

  test('componentExists() checks registry correctly', async () => {
    invalidateCache();
    const registrar = new AutoRegistrar({ projectPath: TEST_DIR });

    const registry = createEmptyRegistry();
    registry.components['existing-id'] = { name: 'Existing' };
    await writeComponentRegistry(TEST_DIR, registry);

    const exists = await registrar.componentExists('existing-id');
    const notExists = await registrar.componentExists('non-existing-id');

    assert(exists, 'Should find existing component');
    assert(!notExists, 'Should not find non-existing component');
  }),

  test('_determineCategory() infers categories correctly', async () => {
    const registrar = new AutoRegistrar({ projectPath: TEST_DIR });

    assertEqual(registrar._determineCategory({ name: 'Submit Button' }), 'actions', 'Button should be actions');
    assertEqual(registrar._determineCategory({ name: 'Email Input' }), 'inputs', 'Input should be inputs');
    assertEqual(registrar._determineCategory({ name: 'User Card' }), 'containers', 'Card should be containers');
    assertEqual(registrar._determineCategory({ name: 'Main Nav' }), 'navigation', 'Nav should be navigation');
    assertEqual(registrar._determineCategory({ name: 'Random Thing' }), 'ui-elements', 'Unknown should be ui-elements');
    assertEqual(registrar._determineCategory({ name: 'Test', category: 'custom' }), 'custom', 'Should preserve explicit category');
  })
];

const integrationTests = [
  test('Full workflow: create, register, migrate, read', async () => {
    invalidateCache();

    // 1. Start with empty registry
    const emptyReg = createEmptyRegistry();
    await writeComponentRegistry(TEST_DIR, emptyReg);

    // 2. Register components
    const registrar = new AutoRegistrar({ projectPath: TEST_DIR });

    await registrar.registerComponent(
      { name: 'Header', type: 'FRAME' },
      { type: 'figma-plugin', nodeId: '1:1' }
    );

    await registrar.registerComponent(
      { name: 'Footer', type: 'FRAME' },
      { type: 'figma-plugin', nodeId: '1:2' }
    );

    // 3. Read and verify
    const registry = await readComponentRegistry(TEST_DIR);

    const componentIds = Object.keys(registry.components);
    assertEqual(componentIds.length, 2, 'Should have 2 components');

    // 4. Verify both components have v3 fields
    for (const id of componentIds) {
      const comp = registry.components[id];
      assertExists(comp.transformation, `${id} should have transformation`);
      assertExists(comp.syncMetadata, `${id} should have syncMetadata`);
    }
  }),

  test('readAndMigrateRegistry() auto-migrates old registries', async () => {
    invalidateCache();

    // Write v2 registry directly
    const v2Registry = {
      version: '2.0.0',
      metadata: { lastUpdated: new Date().toISOString() },
      components: {
        'legacy-component': {
          name: 'Legacy Component',
          transformedTo: ['vue'],
          outputPaths: { vue: 'src/components/Legacy.vue' }
        }
      }
    };

    await fs.mkdir(path.join(TEST_DIR, '.design'), { recursive: true });
    await fs.writeFile(REGISTRY_PATH, JSON.stringify(v2Registry, null, 2));

    // Read with migration
    const migrated = await readAndMigrateRegistry(TEST_DIR, { autoMigrate: true });

    assertEqual(migrated.version, '3.0.0', 'Should be migrated to 3.0.0');
    const comp = migrated.components['legacy-component'];
    assertExists(comp.transformation, 'Should have transformation after migration');
    assertEqual(comp.transformation.state, 'transformed', 'Should infer transformed state');
    assertEqual(comp.transformation.framework, 'vue', 'Should infer framework');
  })
];

// ============================================================================
// Main Test Runner
// ============================================================================

async function runAllTests() {
  console.log('\n╔════════════════════════════════════════════════════════════════╗');
  console.log('║     PHASE 1: FOUNDATION & SCHEMA TEST SUITE                    ║');
  console.log('╚════════════════════════════════════════════════════════════════╝\n');

  const allTests = [
    { name: 'Schema Tests (Sprint 1.2)', tests: schemaTests },
    { name: 'Migration Tests (Sprint 1.4)', tests: migrationTests },
    { name: 'Write Tests (Sprint 1.3)', tests: writeTests },
    { name: 'AutoRegistrar Tests (Sprints 1.5-1.8)', tests: autoRegistrarTests },
    { name: 'Integration Tests', tests: integrationTests }
  ];

  const startTime = Date.now();

  for (const suite of allTests) {
    console.log(`\n📋 ${suite.name}`);
    console.log('─'.repeat(50));

    await setup();

    for (const testCase of suite.tests) {
      await runTest(testCase);
    }

    await teardown();
  }

  const totalTime = Date.now() - startTime;

  // Summary
  console.log('\n' + '═'.repeat(60));
  console.log('\n📊 TEST SUMMARY\n');
  console.log(`   Total:  ${results.passed + results.failed}`);
  console.log(`   Passed: ${results.passed} ✅`);
  console.log(`   Failed: ${results.failed} ❌`);
  console.log(`   Time:   ${totalTime}ms`);

  if (results.failed > 0) {
    console.log('\n❌ FAILED TESTS:');
    results.tests
      .filter(t => t.status === 'FAIL')
      .forEach(t => console.log(`   • ${t.name}: ${t.error}`));
  }

  console.log('\n' + '═'.repeat(60));

  if (results.failed === 0) {
    console.log('\n✅ PHASE 1 COMPLETE - All tests passed!\n');
    console.log('Ready to proceed to Phase 2: Import Entry Point Integration\n');
  } else {
    console.log('\n⚠️  Some tests failed. Please fix issues before proceeding.\n');
    process.exitCode = 1;
  }

  return results;
}

// Run if called directly
if (require.main === module) {
  runAllTests().catch(err => {
    console.error('Test runner error:', err);
    process.exitCode = 1;
  });
}

module.exports = { runAllTests, results };
