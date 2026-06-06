#!/usr/bin/env node
/**
 * Phase 6 Sprint 6.3: Unit Tests for SyncCascade
 *
 * Tests that SyncCascade properly uses existing infrastructure:
 * - ContentHasher for file modification detection
 * - StoryHashRegistry for story tracking
 * - ConflictResolver for conflict detection
 * - DiffEngine for computing changes
 * - SnapshotManager for rollback (separate from DiffEngine!)
 * - TransformStateUpdater for state transitions
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

console.log('\n=== Sprint 6.3: SyncCascade Unit Tests ===\n');

// Create test directory
const testDir = path.join(os.tmpdir(), `sync-cascade-test-${Date.now()}`);
const designDir = path.join(testDir, '.design');

async function setup() {
  fs.mkdirSync(path.join(designDir, 'extracted-code', 'react'), { recursive: true });
  fs.mkdirSync(path.join(designDir, 'components'), { recursive: true });
  fs.mkdirSync(path.join(designDir, 'stories'), { recursive: true });

  // Create initial component registry with test components
  const registry = {
    version: '3.0.0',
    components: {
      'test-btn-001': {
        id: 'test-btn-001',
        name: 'TestButton',
        type: 'COMPONENT',
        source: { type: 'figma-plugin', nodeId: '1:234', originalUrl: 'https://figma.com/file/abc' },
        transformation: {
          state: 'transformed',
          framework: 'react',
          transformedAt: new Date(Date.now() - 3600000).toISOString(),
          codePath: '.design/extracted-code/react/TestButton.tsx',
          storyPath: '.design/stories/TestButton.stories.tsx',
          codeHash: null, // Will be calculated
          version: 1
        },
        paths: {
          rawSource: '.design/components/test-btn-001.json'
        },
        syncMetadata: {
          lastFigmaSync: new Date(Date.now() - 7200000).toISOString(),
          syncCount: 1
        },
        props: { label: { type: 'string' }, disabled: { type: 'boolean' } }
      },
      'imported-only-002': {
        id: 'imported-only-002',
        name: 'ImportedCard',
        transformation: {
          state: 'imported',
          framework: null
        },
        syncMetadata: {}
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

  // Create test code file
  const codeContent = `export const TestButton = ({ label, disabled }) => (
  <button disabled={disabled}>{label}</button>
);`;
  fs.writeFileSync(
    path.join(designDir, 'extracted-code', 'react', 'TestButton.tsx'),
    codeContent
  );

  // Create test story file
  const storyContent = `import { TestButton } from './TestButton';
export default { title: 'TestButton' };
export const Default = () => <TestButton label="Click me" />;`;
  fs.writeFileSync(
    path.join(designDir, 'stories', 'TestButton.stories.tsx'),
    storyContent
  );

  // Create raw component data file
  const rawData = {
    name: 'TestButton',
    type: 'COMPONENT',
    props: { label: { type: 'string' } }
  };
  fs.writeFileSync(
    path.join(designDir, 'components', 'test-btn-001.json'),
    JSON.stringify(rawData, null, 2)
  );

  console.log(`Test directory: ${testDir}\n`);
}

async function cleanup() {
  try {
    fs.rmSync(testDir, { recursive: true, force: true });
  } catch (e) {}
}

async function runTests() {
  const { SyncCascade, CASCADE_EVENTS, CASCADE_DEFAULTS } = require('./sync-cascade');
  const { ContentHasher, hashFile, hasFileChanged } = require('./content-hasher');
  const { StoryHashRegistry } = require('./story-hash-registry');
  const { ConflictResolver } = require('./conflict-resolver');
  const { DiffEngine, SnapshotManager } = require('./incremental-processor');

  // =====================================================
  // TEST 1: Uses Existing Infrastructure
  // =====================================================
  console.log('1. Uses Existing Infrastructure');

  await test('constructor uses default projectPath', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });
    assertEqual(cascade.projectPath, testDir, 'projectPath');
  });

  await test('constructor creates ContentHasher instance', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });
    assertExists(cascade.contentHasher, 'contentHasher');
    assertEqual(cascade.contentHasher instanceof ContentHasher, true, 'is ContentHasher');
  });

  await test('constructor creates StoryHashRegistry instance', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });
    assertExists(cascade.storyHashRegistry, 'storyHashRegistry');
    assertEqual(cascade.storyHashRegistry instanceof StoryHashRegistry, true, 'is StoryHashRegistry');
  });

  await test('constructor creates ConflictResolver instance', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });
    assertExists(cascade.conflictResolver, 'conflictResolver');
    assertEqual(cascade.conflictResolver instanceof ConflictResolver, true, 'is ConflictResolver');
  });

  await test('constructor creates DiffEngine instance', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });
    assertExists(cascade.diffEngine, 'diffEngine');
    assertEqual(cascade.diffEngine instanceof DiffEngine, true, 'is DiffEngine');
  });

  await test('constructor creates SnapshotManager instance (separate from DiffEngine)', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });
    assertExists(cascade.snapshotManager, 'snapshotManager');
    assertEqual(cascade.snapshotManager instanceof SnapshotManager, true, 'is SnapshotManager');
    // Verify they are separate instances
    if (cascade.diffEngine === cascade.snapshotManager) {
      throw new Error('DiffEngine and SnapshotManager should be separate');
    }
  });

  await test('accepts dependency injection for all modules', async () => {
    const hasher = new ContentHasher();
    const storyRegistry = new StoryHashRegistry(testDir);
    const resolver = new ConflictResolver();
    const diffEngine = new DiffEngine();
    const snapshotManager = new SnapshotManager({ projectPath: testDir });

    const cascade = new SyncCascade({
      projectPath: testDir,
      contentHasher: hasher,
      storyHashRegistry: storyRegistry,
      conflictResolver: resolver,
      diffEngine: diffEngine,
      snapshotManager: snapshotManager
    });

    assertEqual(cascade.contentHasher, hasher, 'injected hasher');
    assertEqual(cascade.storyHashRegistry, storyRegistry, 'injected storyRegistry');
    assertEqual(cascade.conflictResolver, resolver, 'injected resolver');
    assertEqual(cascade.diffEngine, diffEngine, 'injected diffEngine');
    assertEqual(cascade.snapshotManager, snapshotManager, 'injected snapshotManager');
  });

  // =====================================================
  // TEST 2: Configuration
  // =====================================================
  console.log('\n2. Configuration');

  await test('exports CASCADE_DEFAULTS', async () => {
    assertExists(CASCADE_DEFAULTS, 'CASCADE_DEFAULTS');
    assertEqual(CASCADE_DEFAULTS.enabled, true, 'enabled');
    assertEqual(CASCADE_DEFAULTS.regenerateCode, true, 'regenerateCode');
    assertEqual(CASCADE_DEFAULTS.regenerateStory, true, 'regenerateStory');
    assertEqual(CASCADE_DEFAULTS.preserveUserModifications, true, 'preserveUserModifications');
  });

  await test('exports CASCADE_EVENTS', async () => {
    assertExists(CASCADE_EVENTS, 'CASCADE_EVENTS');
    assertExists(CASCADE_EVENTS.STARTED, 'STARTED');
    assertExists(CASCADE_EVENTS.COMPLETED, 'COMPLETED');
    assertExists(CASCADE_EVENTS.FAILED, 'FAILED');
    assertExists(CASCADE_EVENTS.STEP, 'STEP');
    assertExists(CASCADE_EVENTS.WARNING, 'WARNING');
    assertExists(CASCADE_EVENTS.ROLLBACK, 'ROLLBACK');
  });

  await test('getConfig returns configuration', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });
    const config = cascade.getConfig();
    assertExists(config.enabled, 'enabled');
    assertExists(config.regenerateCode, 'regenerateCode');
  });

  await test('updateConfig merges new configuration', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });
    cascade.updateConfig({ regenerateCode: false });
    assertEqual(cascade.getConfig().regenerateCode, false, 'updated regenerateCode');
    assertEqual(cascade.getConfig().regenerateStory, true, 'other config preserved');
  });

  await test('isEnabled returns enabled state', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });
    assertEqual(cascade.isEnabled(), true, 'default enabled');

    cascade.updateConfig({ enabled: false });
    assertEqual(cascade.isEnabled(), false, 'after disable');
  });

  // =====================================================
  // TEST 3: shouldRegenerateCode
  // =====================================================
  console.log('\n3. shouldRegenerateCode');

  await test('returns skip for non-existent component', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });
    const result = await cascade.shouldRegenerateCode('non-existent');
    assertEqual(result.should, false, 'should');
    assertEqual(result.reason, 'Component not found', 'reason');
  });

  await test('returns skip for non-transformed component', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });
    const result = await cascade.shouldRegenerateCode('imported-only-002');
    assertEqual(result.should, false, 'should');
    assertEqual(result.reason, 'Not transformed', 'reason');
  });

  await test('returns regenerate when code file missing', async () => {
    // First, create a component with a non-existent code path
    const { writeComponentRegistry, readComponentRegistry } = require('./registry-reader');
    const registry = await readComponentRegistry(testDir, { forceRefresh: true });
    registry.components['missing-code-comp'] = {
      transformation: {
        state: 'transformed',
        framework: 'react',
        codePath: '.design/extracted-code/react/MissingCode.tsx',
        codeHash: 'abc123'
      }
    };
    await writeComponentRegistry(testDir, registry);

    const cascade = new SyncCascade({ projectPath: testDir });
    const result = await cascade.shouldRegenerateCode('missing-code-comp');

    assertEqual(result.should, true, 'should regenerate');
    assertEqual(result.reason, 'Code file missing', 'reason');
  });

  await test('detects user modifications via hasFileChanged', async () => {
    // Create a component with known hash, then modify the file
    const codePath = '.design/extracted-code/react/ModifyTest.tsx';
    const fullPath = path.join(testDir, codePath);
    const originalContent = 'export const ModifyTest = () => <div>Original</div>;';
    fs.writeFileSync(fullPath, originalContent);

    const originalHash = await hashFile(fullPath);

    const { writeComponentRegistry, readComponentRegistry } = require('./registry-reader');
    const registry = await readComponentRegistry(testDir, { forceRefresh: true });
    registry.components['modify-test'] = {
      transformation: {
        state: 'transformed',
        framework: 'react',
        codePath,
        codeHash: originalHash,
        transformedAt: new Date().toISOString()
      },
      syncMetadata: {}
    };
    await writeComponentRegistry(testDir, registry);

    // Modify the file
    fs.writeFileSync(fullPath, 'export const ModifyTest = () => <div>USER MODIFIED</div>;');

    const cascade = new SyncCascade({ projectPath: testDir });
    const result = await cascade.shouldRegenerateCode('modify-test');

    assertEqual(result.should, false, 'should NOT regenerate (preserve user changes)');
    assertEqual(result.userModified, true, 'userModified flag');
  });

  await test('returns regenerate when source is newer than transform', async () => {
    const codePath = '.design/extracted-code/react/NewerSource.tsx';
    const fullPath = path.join(testDir, codePath);
    const content = 'export const NewerSource = () => <div>Test</div>;';
    fs.writeFileSync(fullPath, content);

    const hash = await hashFile(fullPath);

    // Set up: lastFigmaSync is newer than transformedAt
    const { writeComponentRegistry, readComponentRegistry } = require('./registry-reader');
    const registry = await readComponentRegistry(testDir, { forceRefresh: true });
    registry.components['newer-source'] = {
      transformation: {
        state: 'transformed',
        framework: 'react',
        codePath,
        codeHash: hash,
        transformedAt: new Date(Date.now() - 3600000).toISOString() // 1 hour ago
      },
      syncMetadata: {
        lastFigmaSync: new Date().toISOString() // now (newer)
      }
    };
    await writeComponentRegistry(testDir, registry);

    const cascade = new SyncCascade({ projectPath: testDir });
    const result = await cascade.shouldRegenerateCode('newer-source');

    assertEqual(result.should, true, 'should regenerate');
    assertEqual(result.reason, 'Source updated', 'reason');
  });

  // =====================================================
  // TEST 4: shouldRegenerateStory
  // =====================================================
  console.log('\n4. shouldRegenerateStory');

  await test('returns skip for non-existent component', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });
    const result = await cascade.shouldRegenerateStory('non-existent');
    assertEqual(result.should, false, 'should');
  });

  await test('returns skip for component without storyPath', async () => {
    const { writeComponentRegistry, readComponentRegistry } = require('./registry-reader');
    const registry = await readComponentRegistry(testDir, { forceRefresh: true });
    registry.components['no-story-path'] = {
      transformation: {
        state: 'transformed',
        framework: 'react',
        storyPath: null // No story (like mobile frameworks)
      }
    };
    await writeComponentRegistry(testDir, registry);

    const cascade = new SyncCascade({ projectPath: testDir });
    const result = await cascade.shouldRegenerateStory('no-story-path');

    assertEqual(result.should, false, 'should');
    if (!result.reason.includes('No story path')) {
      throw new Error(`Expected 'No story path' in reason, got: ${result.reason}`);
    }
  });

  await test('returns regenerate when story file missing', async () => {
    const { writeComponentRegistry, readComponentRegistry } = require('./registry-reader');
    const registry = await readComponentRegistry(testDir, { forceRefresh: true });
    registry.components['missing-story'] = {
      transformation: {
        state: 'transformed',
        framework: 'react',
        storyPath: '.design/stories/MissingStory.stories.tsx'
      }
    };
    await writeComponentRegistry(testDir, registry);

    const cascade = new SyncCascade({ projectPath: testDir });
    const result = await cascade.shouldRegenerateStory('missing-story');

    assertEqual(result.should, true, 'should regenerate');
    assertEqual(result.reason, 'Story file missing', 'reason');
  });

  // =====================================================
  // TEST 5: updateRegistry
  // =====================================================
  console.log('\n5. updateRegistry');

  await test('creates snapshot using SnapshotManager', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });

    const result = await cascade.updateRegistry('test-btn-001', {
      props: { label: { type: 'string' }, newProp: { type: 'number' } }
    });

    assertEqual(result.success, true, 'success');
    assertExists(result.snapshotId, 'snapshotId created');
  });

  await test('computes changes using DiffEngine', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });

    const result = await cascade.updateRegistry('test-btn-001', {
      props: { label: { type: 'string' }, anotherProp: { type: 'boolean' } }
    });

    assertEqual(result.success, true, 'success');
    assertExists(result.changes, 'changes computed');
  });

  await test('throws error for non-existent component', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });

    try {
      await cascade.updateRegistry('non-existent-id', { props: {} });
      throw new Error('Should have thrown');
    } catch (e) {
      if (e.message === 'Should have thrown') throw e;
      // Expected error
    }
  });

  // =====================================================
  // TEST 6: rollback
  // =====================================================
  console.log('\n6. rollback');

  await test('uses SnapshotManager.restore for rollback', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });

    // Create a snapshot first
    const updateResult = await cascade.updateRegistry('test-btn-001', {
      props: { label: { type: 'string' }, rollbackTestProp: { type: 'boolean' } }
    });

    // Now rollback
    const rollbackResult = await cascade.rollback('test-btn-001', updateResult.snapshotId);

    assertEqual(rollbackResult.success, true, 'rollback success');
  });

  await test('rollback returns error for non-existent snapshot', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });
    const result = await cascade.rollback('test-btn-001', 'non-existent-snapshot-id');

    assertEqual(result.success, false, 'should fail');
    assertExists(result.error, 'error message');
  });

  // =====================================================
  // TEST 7: Event Emission
  // =====================================================
  console.log('\n7. Event Emission');

  await test('emits cascade:started event', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });
    let startedEmitted = false;

    cascade.on(CASCADE_EVENTS.STARTED, (data) => {
      startedEmitted = true;
      assertExists(data.componentId, 'componentId in event');
    });

    // Trigger cascade (will fail since no optimizer, but event should fire)
    try {
      await cascade.cascade('test-btn-001', { props: {} });
    } catch (e) {
      // Expected
    }

    assertEqual(startedEmitted, true, 'started event emitted');
  });

  await test('emits cascade:step events', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });
    const steps = [];

    cascade.on(CASCADE_EVENTS.STEP, (data) => {
      steps.push(data.step);
    });

    // Run updateRegistry which emits step events
    await cascade.updateRegistry('test-btn-001', { props: {} });

    if (!steps.includes('registry')) {
      throw new Error('Expected registry step event');
    }
  });

  // =====================================================
  // TEST 8: Cascade Orchestration
  // =====================================================
  console.log('\n8. Cascade Orchestration');

  await test('cascade returns structured result', async () => {
    // Disable code/story regeneration to test orchestration only
    const cascade = new SyncCascade({
      projectPath: testDir,
      config: { regenerateCode: false, regenerateStory: false }
    });

    const result = await cascade.cascade('test-btn-001', {
      props: { label: { type: 'string' }, cascadeProp: { type: 'number' } }
    });

    assertExists(result.componentId, 'componentId');
    assertExists(result.startedAt, 'startedAt');
    assertExists(result.steps, 'steps');
    assertExists(result.steps.registry, 'registry step');
    assertEqual(result.success, true, 'success');
  });

  await test('cascade handles failure and attempts rollback', async () => {
    // Create cascade with config that will fail (no optimizer for code regeneration)
    const cascade = new SyncCascade({
      projectPath: testDir,
      config: { regenerateCode: true, regenerateStory: false }
    });

    // Set up a component that needs code regeneration
    const { writeComponentRegistry, readComponentRegistry } = require('./registry-reader');
    const registry = await readComponentRegistry(testDir, { forceRefresh: true });
    registry.components['fail-cascade'] = {
      name: 'FailCascade',
      transformation: {
        state: 'transformed',
        framework: 'react',
        codePath: '.design/extracted-code/react/NonExistent.tsx',
        transformedAt: new Date(Date.now() - 3600000).toISOString()
      },
      syncMetadata: {
        lastFigmaSync: new Date().toISOString()
      },
      paths: {}
    };
    await writeComponentRegistry(testDir, registry);

    const result = await cascade.cascade('fail-cascade', { props: {} });

    // Should fail because code file is missing and there's no optimizer
    assertEqual(result.success, false, 'should fail');
    if (result.errors.length === 0) {
      throw new Error('Expected errors in result');
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
    console.log('SYNCCASCADE UNIT TEST RESULTS');
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

    console.log('\n✅ All SyncCascade unit tests passed!\n');
  }
})();
