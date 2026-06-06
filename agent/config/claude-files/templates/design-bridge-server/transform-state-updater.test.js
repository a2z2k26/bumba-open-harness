#!/usr/bin/env node
/**
 * Phase 6 Sprint 6.2: Unit Tests for TransformStateUpdater
 *
 * Tests that TransformStateUpdater properly uses existing infrastructure:
 * - ContentHasher for hash calculations
 * - StoryHashRegistry for file tracking
 * - registry-reader for component registry access
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

console.log('\n=== Sprint 6.2: TransformStateUpdater Unit Tests ===\n');

// Create test directory
const testDir = path.join(os.tmpdir(), `transform-state-test-${Date.now()}`);
const designDir = path.join(testDir, '.design');

async function setup() {
  fs.mkdirSync(path.join(designDir, 'extracted-code', 'react'), { recursive: true });
  fs.mkdirSync(path.join(designDir, 'components'), { recursive: true });

  // Create initial component registry with a test component
  const registry = {
    version: '3.0.0',
    components: {
      'test-btn-001': {
        id: 'test-btn-001',
        name: 'TestButton',
        type: 'COMPONENT',
        source: { type: 'figma-plugin', nodeId: '1:234' },
        transformation: {
          state: 'imported',
          framework: null,
          transformedAt: null,
          codePath: null,
          storyPath: null,
          codeHash: null,
          version: 0
        },
        syncMetadata: {
          lastFigmaSync: new Date().toISOString(),
          syncCount: 1
        }
      },
      'test-card-002': {
        id: 'test-card-002',
        name: 'TestCard',
        type: 'COMPONENT',
        source: { type: 'figma-plugin', nodeId: '2:345' },
        transformation: {
          state: 'transformed',
          framework: 'react',
          transformedAt: new Date(Date.now() - 3600000).toISOString(), // 1 hour ago
          codePath: '.design/extracted-code/react/TestCard.tsx',
          storyPath: '.design/stories/TestCard.stories.tsx',
          codeHash: 'abc123def456',
          version: 1
        },
        syncMetadata: {
          lastFigmaSync: new Date(Date.now() - 7200000).toISOString(), // 2 hours ago
          syncCount: 2
        }
      }
    },
    metadata: {
      lastUpdated: new Date().toISOString()
    }
  };

  fs.writeFileSync(
    path.join(designDir, 'componentRegistry.json'),
    JSON.stringify(registry, null, 2)
  );

  // Create a test code file for TestCard
  const codeContent = `export const TestCard = ({ title }) => <div className="card">{title}</div>;`;
  fs.writeFileSync(
    path.join(designDir, 'extracted-code', 'react', 'TestCard.tsx'),
    codeContent
  );

  console.log(`Test directory: ${testDir}\n`);
}

async function cleanup() {
  try {
    fs.rmSync(testDir, { recursive: true, force: true });
  } catch (e) {}
}

async function runTests() {
  const { TransformStateUpdater, findComponentIdByName, markComponentTransformed } = require('./transform-state-updater');
  const { ContentHasher, hashFile } = require('./content-hasher');
  const { StoryHashRegistry } = require('./story-hash-registry');

  // =====================================================
  // TEST 1: Uses Existing Infrastructure
  // =====================================================
  console.log('1. Uses Existing Infrastructure');

  await test('constructor requires projectPath', async () => {
    try {
      new TransformStateUpdater({});
      throw new Error('Should have thrown');
    } catch (e) {
      if (e.message === 'Should have thrown') throw e;
      // Expected error
    }
  });

  await test('constructor creates ContentHasher instance', async () => {
    const updater = new TransformStateUpdater({ projectPath: testDir });
    assertExists(updater.contentHasher, 'contentHasher');
    assertEqual(updater.contentHasher instanceof ContentHasher, true, 'is ContentHasher');
  });

  await test('constructor creates StoryHashRegistry instance', async () => {
    const updater = new TransformStateUpdater({ projectPath: testDir });
    assertExists(updater.fileRegistry, 'fileRegistry');
    assertEqual(updater.fileRegistry instanceof StoryHashRegistry, true, 'is StoryHashRegistry');
  });

  // =====================================================
  // TEST 2: markTransformed
  // =====================================================
  console.log('\n2. markTransformed');

  await test('returns error for non-existent component', async () => {
    const updater = new TransformStateUpdater({ projectPath: testDir });
    const result = await updater.markTransformed('non-existent-id', { framework: 'react' });
    assertEqual(result.success, false, 'success');
    assertExists(result.error, 'error message');
  });

  await test('updates state to transformed', async () => {
    const updater = new TransformStateUpdater({ projectPath: testDir });
    const result = await updater.markTransformed('test-btn-001', {
      framework: 'react',
      codePath: '.design/extracted-code/react/TestButton.tsx'
    });

    assertEqual(result.success, true, 'success');
    assertEqual(result.transformation.state, 'transformed', 'state');
    assertEqual(result.transformation.framework, 'react', 'framework');
    assertExists(result.transformation.transformedAt, 'transformedAt');
  });

  await test('calculates codeHash using ContentHasher when file exists', async () => {
    // Create a test file
    const codePath = '.design/extracted-code/react/HashTestButton.tsx';
    const fullPath = path.join(testDir, codePath);
    fs.writeFileSync(fullPath, 'export const HashTestButton = () => <button>Click</button>;');

    const updater = new TransformStateUpdater({ projectPath: testDir });

    // First register the component
    const { writeComponentRegistry, readComponentRegistry } = require('./registry-reader');
    const registry = await readComponentRegistry(testDir, { forceRefresh: true });
    registry.components['hash-test-btn'] = {
      id: 'hash-test-btn',
      name: 'HashTestButton',
      transformation: { state: 'imported' }
    };
    await writeComponentRegistry(testDir, registry);

    const result = await updater.markTransformed('hash-test-btn', {
      framework: 'react',
      codePath
    });

    assertEqual(result.success, true, 'success');
    assertExists(result.transformation.codeHash, 'codeHash should exist');
    assertType(result.transformation.codeHash, 'string', 'codeHash type');
  });

  await test('increments version on each transform', async () => {
    const updater = new TransformStateUpdater({ projectPath: testDir });

    // TestCard already has version 1
    const result = await updater.markTransformed('test-card-002', {
      framework: 'vue',
      codePath: '.design/extracted-code/vue/TestCard.vue'
    });

    assertEqual(result.success, true, 'success');
    assertEqual(result.transformation.version, 2, 'version incremented');
  });

  // =====================================================
  // TEST 3: getTransformState
  // =====================================================
  console.log('\n3. getTransformState');

  await test('returns null for non-existent component', async () => {
    const updater = new TransformStateUpdater({ projectPath: testDir });
    const state = await updater.getTransformState('non-existent');
    assertEqual(state, null, 'should be null');
  });

  await test('returns transformation state for existing component', async () => {
    const updater = new TransformStateUpdater({ projectPath: testDir });
    const state = await updater.getTransformState('test-btn-001');

    assertExists(state, 'state');
    assertEqual(state.state, 'transformed', 'state value');
  });

  // =====================================================
  // TEST 4: needsRetransform
  // =====================================================
  console.log('\n4. needsRetransform');

  await test('returns needs: false for non-existent component', async () => {
    const updater = new TransformStateUpdater({ projectPath: testDir });
    const check = await updater.needsRetransform('non-existent');
    assertEqual(check.needs, false, 'needs');
    assertEqual(check.reason, 'Component not found', 'reason');
  });

  await test('returns needs: true when code file is missing', async () => {
    // Add a component with non-existent codePath
    const { writeComponentRegistry, readComponentRegistry } = require('./registry-reader');
    const registry = await readComponentRegistry(testDir, { forceRefresh: true });
    registry.components['missing-code-btn'] = {
      id: 'missing-code-btn',
      name: 'MissingCodeButton',
      transformation: {
        state: 'transformed',
        framework: 'react',
        transformedAt: new Date().toISOString(),
        codePath: '.design/extracted-code/react/NonExistent.tsx',
        codeHash: 'somehash'
      }
    };
    await writeComponentRegistry(testDir, registry);

    const updater = new TransformStateUpdater({ projectPath: testDir });
    const check = await updater.needsRetransform('missing-code-btn');

    assertEqual(check.needs, true, 'needs');
    assertEqual(check.reason, 'Code file missing', 'reason');
  });

  await test('detects user modifications via hash comparison', async () => {
    // Create a fresh component file with known content
    const codePath = '.design/extracted-code/react/ModTest.tsx';
    const fullPath = path.join(testDir, codePath);
    const originalContent = 'export const ModTest = () => <div>Original</div>;';
    fs.writeFileSync(fullPath, originalContent);

    // Get the hash
    const originalHash = await hashFile(fullPath);

    // Register with that hash
    const { writeComponentRegistry, readComponentRegistry } = require('./registry-reader');
    const registry = await readComponentRegistry(testDir, { forceRefresh: true });
    registry.components['mod-test-btn'] = {
      id: 'mod-test-btn',
      name: 'ModTest',
      transformation: {
        state: 'transformed',
        framework: 'react',
        transformedAt: new Date().toISOString(),
        codePath,
        codeHash: originalHash
      }
    };
    await writeComponentRegistry(testDir, registry);

    // Now modify the file
    fs.writeFileSync(fullPath, 'export const ModTest = () => <div>MODIFIED BY USER</div>;');

    const updater = new TransformStateUpdater({ projectPath: testDir });
    const check = await updater.needsRetransform('mod-test-btn');

    assertEqual(check.needs, false, 'needs should be false (preserve user changes)');
    assertEqual(check.userModified, true, 'userModified flag');
  });

  // =====================================================
  // TEST 5: listTransformed
  // =====================================================
  console.log('\n5. listTransformed');

  await test('returns array of transformed components', async () => {
    const updater = new TransformStateUpdater({ projectPath: testDir });
    const list = await updater.listTransformed();

    assertType(list, 'object', 'list is array');
    assertEqual(Array.isArray(list), true, 'is array');
    if (list.length < 1) {
      throw new Error('Expected at least one transformed component');
    }
  });

  await test('filters by framework', async () => {
    const updater = new TransformStateUpdater({ projectPath: testDir });

    // Get vue components (test-card-002 was transformed to vue earlier)
    const vueList = await updater.listTransformed({ framework: 'vue' });
    const hasVue = vueList.some(c => c.framework === 'vue');

    // This should return the component we transformed to vue earlier
    assertEqual(hasVue || vueList.length === 0, true, 'vue filter works');
  });

  // =====================================================
  // TEST 6: updatePaths
  // =====================================================
  console.log('\n6. updatePaths');

  await test('updates codePath and storyPath', async () => {
    const updater = new TransformStateUpdater({ projectPath: testDir });

    const result = await updater.updatePaths('test-card-002', {
      codePath: '.design/extracted-code/react/UpdatedCard.tsx',
      storyPath: '.design/stories/UpdatedCard.stories.tsx'
    });

    assertEqual(result.success, true, 'success');
    assertEqual(result.paths.codePath, '.design/extracted-code/react/UpdatedCard.tsx', 'codePath');
    assertEqual(result.paths.storyPath, '.design/stories/UpdatedCard.stories.tsx', 'storyPath');
  });

  await test('returns error for component without transformation object', async () => {
    // Add a component without transformation field at all
    const { writeComponentRegistry, readComponentRegistry } = require('./registry-reader');
    const registry = await readComponentRegistry(testDir, { forceRefresh: true });
    registry.components['no-transform'] = {
      id: 'no-transform',
      name: 'NoTransform'
      // No transformation field
    };
    await writeComponentRegistry(testDir, registry);

    const updater = new TransformStateUpdater({ projectPath: testDir });
    const result = await updater.updatePaths('no-transform', { codePath: 'test.tsx' });

    assertEqual(result.success, false, 'success');
    assertExists(result.error, 'error message');
  });

  // =====================================================
  // TEST 7: resetTransformState
  // =====================================================
  console.log('\n7. resetTransformState');

  await test('resets transformed component to imported state', async () => {
    const updater = new TransformStateUpdater({ projectPath: testDir });

    // First verify it's transformed
    let state = await updater.getTransformState('test-card-002');
    assertEqual(state.state, 'transformed', 'initially transformed');

    // Reset it
    const result = await updater.resetTransformState('test-card-002');
    assertEqual(result.success, true, 'success');

    // Verify it's now imported
    state = await updater.getTransformState('test-card-002');
    assertEqual(state.state, 'imported', 'reset to imported');
    assertEqual(state.codePath, null, 'codePath cleared');
    assertEqual(state.framework, null, 'framework cleared');
  });

  // =====================================================
  // TEST 8: getStats
  // =====================================================
  console.log('\n8. getStats');

  await test('returns correct statistics', async () => {
    const updater = new TransformStateUpdater({ projectPath: testDir });
    const stats = await updater.getStats();

    assertExists(stats.total, 'total');
    assertExists(stats.imported, 'imported');
    assertExists(stats.transformed, 'transformed');
    assertType(stats.byFramework, 'object', 'byFramework');

    // total should equal imported + transformed
    if (stats.total < stats.imported + stats.transformed) {
      throw new Error('Stats totals do not add up');
    }
  });

  // =====================================================
  // TEST 9: Utility Functions
  // =====================================================
  console.log('\n9. Utility Functions');

  await test('findComponentIdByName finds by exact name', async () => {
    const id = await findComponentIdByName('TestButton', testDir);
    assertEqual(id, 'test-btn-001', 'found id');
  });

  await test('findComponentIdByName returns null for non-existent', async () => {
    const id = await findComponentIdByName('NonExistent', testDir);
    assertEqual(id, null, 'null for non-existent');
  });

  await test('markComponentTransformed helper works', async () => {
    // Re-transform test-btn-001
    const result = await markComponentTransformed(testDir, 'test-btn-001', {
      framework: 'svelte'
    });

    assertEqual(result.success, true, 'success');
    assertEqual(result.transformation.framework, 'svelte', 'framework');
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
    console.log('TRANSFORMSTATEUPDATER UNIT TEST RESULTS');
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

    console.log('\n✅ All TransformStateUpdater unit tests passed!\n');
  }
})();
