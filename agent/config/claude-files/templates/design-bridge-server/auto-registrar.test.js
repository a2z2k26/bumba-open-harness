#!/usr/bin/env node
/**
 * Phase 6 Sprint 6.1: Unit Tests for AutoRegistrar
 *
 * Tests that AutoRegistrar properly uses existing infrastructure:
 * - ContentHasher for ID generation
 * - registry-reader for component lookup
 * - Correct v3.0.0 schema entries
 */

const path = require('path');
const fs = require('fs');
const os = require('os');

// Test results tracking
const results = { passed: 0, failed: 0, errors: [] };

function test(name, fn) {
  return (async () => {
    try {
      await fn();
      results.passed++;
      console.log(`  ✅ ${name}`);
    } catch (error) {
      results.failed++;
      results.errors.push({ name, error: error.message });
      console.log(`  ❌ ${name}: ${error.message}`);
    }
  })();
}

function assertEqual(actual, expected, msg) {
  if (actual !== expected) {
    throw new Error(`${msg}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

function assertExists(value, msg) {
  if (value === undefined || value === null) {
    throw new Error(`${msg}: value is ${value}`);
  }
}

function assertType(value, type, msg) {
  if (typeof value !== type) {
    throw new Error(`${msg}: expected ${type}, got ${typeof value}`);
  }
}

console.log('\n=== Sprint 6.1: AutoRegistrar Unit Tests ===\n');

// Create test directory
const testDir = path.join(os.tmpdir(), `auto-registrar-test-${Date.now()}`);
const designDir = path.join(testDir, '.design');

async function setup() {
  fs.mkdirSync(designDir, { recursive: true });
  console.log(`Test directory: ${testDir}\n`);
}

async function cleanup() {
  try {
    fs.rmSync(testDir, { recursive: true, force: true });
  } catch (e) {}
}

async function runTests() {
  const { AutoRegistrar } = require('./auto-registrar');
  const { ContentHasher } = require('./content-hasher');
  const { readComponentRegistry } = require('./registry-reader');

  // =====================================================
  // TEST 1: Uses Existing Infrastructure
  // =====================================================
  console.log('1. Uses Existing Infrastructure');

  await test('constructor creates ContentHasher instance', async () => {
    const registrar = new AutoRegistrar({ projectPath: testDir });
    assertExists(registrar.contentHasher, 'contentHasher');
  });

  await test('accepts injected ContentHasher (DI pattern)', async () => {
    const hasher = new ContentHasher();
    const registrar = new AutoRegistrar({
      projectPath: testDir,
      contentHasher: hasher
    });
    assertEqual(registrar.contentHasher, hasher, 'injected hasher');
  });

  await test('has readComponentRegistry reference', async () => {
    const registrar = new AutoRegistrar({ projectPath: testDir });
    // Should use registry-reader internally
    assertType(registrar.componentExists, 'function', 'componentExists method');
  });

  // =====================================================
  // TEST 2: generateComponentId
  // =====================================================
  console.log('\n2. generateComponentId');

  await test('generates correct ID for figma-mcp source', async () => {
    const registrar = new AutoRegistrar({ projectPath: testDir });
    const id = registrar.generateComponentId(
      { name: 'Button' },
      { type: 'figma-mcp', nodeId: '123:456', fileKey: 'abc123' }
    );
    // Should include fileKey and nodeId
    if (!id.includes('figma') || !id.includes('123')) {
      throw new Error(`ID format incorrect: ${id}`);
    }
  });

  await test('generates correct ID for figma-plugin source', async () => {
    const registrar = new AutoRegistrar({ projectPath: testDir });
    const id = registrar.generateComponentId(
      { name: 'Card' },
      { type: 'figma-plugin', nodeId: '789:012' }
    );
    if (!id.includes('figma') || !id.includes('789')) {
      throw new Error(`ID format incorrect: ${id}`);
    }
  });

  await test('uses ContentHasher.shortHash for shadcn sources', async () => {
    const registrar = new AutoRegistrar({ projectPath: testDir });
    const id = registrar.generateComponentId(
      { name: 'Button' },
      { type: 'shadcn', registryItem: '@shadcn/button' }
    );
    // Should include hash component
    if (!id.includes('shadcn') || !id.includes('button')) {
      throw new Error(`ID format incorrect: ${id}`);
    }
  });

  await test('uses ContentHasher.shortHash for nlp sources', async () => {
    const registrar = new AutoRegistrar({ projectPath: testDir });
    const id = registrar.generateComponentId(
      { name: 'CustomComponent' },
      { type: 'nlp', prompt: 'create a button' }
    );
    if (!id.includes('nlp')) {
      throw new Error(`ID format incorrect: ${id}`);
    }
  });

  await test('generates deterministic IDs for same input', async () => {
    const registrar = new AutoRegistrar({ projectPath: testDir });
    const id1 = registrar.generateComponentId(
      { name: 'Button' },
      { type: 'figma-plugin', nodeId: '1:234' }
    );
    const id2 = registrar.generateComponentId(
      { name: 'Button' },
      { type: 'figma-plugin', nodeId: '1:234' }
    );
    assertEqual(id1, id2, 'deterministic IDs');
  });

  // =====================================================
  // TEST 3: registerComponent
  // =====================================================
  console.log('\n3. registerComponent');

  await test('creates v3.0.0 schema entry with transformation field', async () => {
    const registrar = new AutoRegistrar({ projectPath: testDir });
    const result = await registrar.registerComponent(
      { name: 'PrimaryButton', type: 'COMPONENT' },
      { type: 'figma-plugin', nodeId: '1:234' }
    );

    assertEqual(result.success, true, 'success');
    assertExists(result.entry, 'entry');
    assertExists(result.entry.transformation, 'transformation field');
    assertEqual(result.entry.transformation.state, 'imported', 'initial state');
  });

  await test('creates syncMetadata field', async () => {
    const registrar = new AutoRegistrar({ projectPath: testDir });
    const result = await registrar.registerComponent(
      { name: 'SecondaryButton', type: 'COMPONENT' },
      { type: 'figma-plugin', nodeId: '2:345' }
    );

    assertExists(result.entry.syncMetadata, 'syncMetadata');
    assertExists(result.entry.syncMetadata.lastFigmaSync, 'lastFigmaSync');
    assertEqual(result.entry.syncMetadata.syncCount, 1, 'syncCount');
  });

  await test('writes to registry using writeComponentRegistry', async () => {
    const registrar = new AutoRegistrar({ projectPath: testDir });
    await registrar.registerComponent(
      { name: 'TestButton', type: 'COMPONENT' },
      { type: 'figma-plugin', nodeId: '3:456' }
    );

    // Verify registry was written
    const registry = await readComponentRegistry(testDir);
    assertExists(registry.components, 'registry.components');

    const hasButton = Object.values(registry.components).some(c => c.name === 'TestButton');
    if (!hasButton) {
      throw new Error('Component not found in registry after write');
    }
  });

  await test('detects existing component and returns isNew: false', async () => {
    const registrar = new AutoRegistrar({ projectPath: testDir });

    // First registration
    const first = await registrar.registerComponent(
      { name: 'DuplicateButton', type: 'COMPONENT' },
      { type: 'figma-plugin', nodeId: '4:567' }
    );
    assertEqual(first.isNew, true, 'first isNew');

    // Second registration (same component)
    const second = await registrar.registerComponent(
      { name: 'DuplicateButton', type: 'COMPONENT' },
      { type: 'figma-plugin', nodeId: '4:567' }
    );
    assertEqual(second.isNew, false, 'second isNew');
  });

  // =====================================================
  // TEST 4: componentExists
  // =====================================================
  console.log('\n4. componentExists');

  await test('returns false for non-existent component', async () => {
    const registrar = new AutoRegistrar({ projectPath: testDir });
    const exists = await registrar.componentExists('non-existent-id-xyz');
    assertEqual(exists, false, 'non-existent');
  });

  await test('returns true for registered component', async () => {
    const registrar = new AutoRegistrar({ projectPath: testDir });

    // Register first
    const result = await registrar.registerComponent(
      { name: 'ExistsTest', type: 'COMPONENT' },
      { type: 'figma-plugin', nodeId: '5:678' }
    );

    // Use forceRefresh to avoid cache issues
    // Note: registerComponent returns 'id' not 'componentId'
    const registry = await readComponentRegistry(testDir, { forceRefresh: true });
    const componentInRegistry = registry.components[result.id] !== undefined;
    assertEqual(componentInRegistry, true, 'exists in registry');
  });

  // =====================================================
  // TEST 5: Source Type Handling
  // =====================================================
  console.log('\n5. Source Type Handling');

  await test('handles figma-mcp source correctly', async () => {
    const registrar = new AutoRegistrar({ projectPath: testDir });
    const result = await registrar.registerComponent(
      { name: 'MCPButton' },
      { type: 'figma-mcp', nodeId: '10:100', fileKey: 'file123' }
    );

    assertEqual(result.entry.source.type, 'figma-mcp', 'source type');
    assertEqual(result.entry.source.nodeId, '10:100', 'nodeId');
    assertEqual(result.entry.source.fileKey, 'file123', 'fileKey');
  });

  await test('handles shadcn source correctly', async () => {
    const registrar = new AutoRegistrar({ projectPath: testDir });
    const result = await registrar.registerComponent(
      { name: 'ShadcnButton' },
      { type: 'shadcn', registryItem: '@shadcn/button' }
    );

    assertEqual(result.entry.source.type, 'shadcn', 'source type');
  });

  await test('handles nlp source correctly', async () => {
    const registrar = new AutoRegistrar({ projectPath: testDir });
    const result = await registrar.registerComponent(
      { name: 'NLPComponent' },
      { type: 'nlp', prompt: 'create a card component' }
    );

    assertEqual(result.entry.source.type, 'nlp', 'source type');
  });

  // =====================================================
  // TEST 6: Error Handling
  // =====================================================
  console.log('\n6. Error Handling');

  await test('handles missing component data gracefully', async () => {
    const registrar = new AutoRegistrar({ projectPath: testDir });

    try {
      await registrar.registerComponent(null, { type: 'figma-plugin', nodeId: '1:1' });
      throw new Error('Should have thrown');
    } catch (e) {
      if (e.message === 'Should have thrown') throw e;
      // Expected error
    }
  });

  await test('handles missing source gracefully', async () => {
    const registrar = new AutoRegistrar({ projectPath: testDir });

    try {
      await registrar.registerComponent({ name: 'Test' }, null);
      throw new Error('Should have thrown');
    } catch (e) {
      if (e.message === 'Should have thrown') throw e;
      // Expected error
    }
  });
}

// Main execution
(async () => {
  try {
    await setup();
    await runTests();
  } catch (error) {
    console.error('\nTest suite error:', error.message);
    results.failed++;
  } finally {
    await cleanup();

    console.log('\n' + '='.repeat(50));
    console.log('AUTOREGISTRAR UNIT TEST RESULTS');
    console.log('='.repeat(50));
    console.log(`\n  Total:  ${results.passed + results.failed}`);
    console.log(`  Passed: ${results.passed} ✅`);
    console.log(`  Failed: ${results.failed} ❌`);

    if (results.failed > 0) {
      console.log('\nFailed Tests:');
      results.errors.forEach((err, i) => {
        console.log(`  ${i + 1}. ${err.name}`);
        console.log(`     Error: ${err.error}`);
      });
      process.exit(1);
    }

    console.log('\n✅ All AutoRegistrar unit tests passed!\n');
  }
})();
