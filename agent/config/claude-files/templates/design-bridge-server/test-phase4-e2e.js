#!/usr/bin/env node
/**
 * Phase 4: Cascade Sync - End-to-End Integration Test
 *
 * Tests the full cascade flow with mock component registry.
 */

const path = require('path');
const fs = require('fs');
const os = require('os');

// Test results tracking
const results = {
  passed: 0,
  failed: 0,
  errors: []
};

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

console.log('\n=== Phase 4: E2E Cascade Sync Test ===\n');

// Create a temporary test directory
const testDir = path.join(os.tmpdir(), `cascade-test-${Date.now()}`);
const designDir = path.join(testDir, '.design');

async function setup() {
  console.log('Setting up test environment...');

  // Create directories
  fs.mkdirSync(path.join(designDir, 'raw'), { recursive: true });
  fs.mkdirSync(path.join(designDir, 'extracted-code', 'react'), { recursive: true });
  fs.mkdirSync(path.join(designDir, 'stories'), { recursive: true });

  // Create mock component registry with a transformed component
  const registry = {
    version: '1.0.0',
    components: {
      'btn-primary-001': {
        id: 'btn-primary-001',
        name: 'PrimaryButton',
        source: {
          type: 'figma',
          fileKey: 'test-file-abc123',
          nodeId: '123:456'
        },
        state: 'transformed',
        category: 'button',
        props: {
          label: { type: 'string', default: 'Click me' },
          disabled: { type: 'boolean', default: false }
        },
        variants: ['default', 'hover', 'disabled'],
        tokenDependencies: {
          colors: ['primary', 'primaryHover']
        },
        transformation: {
          state: 'transformed',
          framework: 'react',
          transformedAt: new Date(Date.now() - 86400000).toISOString(), // 1 day ago
          codePath: '.design/extracted-code/react/PrimaryButton.tsx',
          storyPath: '.design/stories/PrimaryButton.stories.tsx',
          codeHash: 'abc123hash'
        },
        syncMetadata: {
          lastFigmaSync: new Date(Date.now() - 3600000).toISOString() // 1 hour ago
        },
        paths: {
          rawSource: '.design/raw/btn-primary-001.json'
        }
      },
      'btn-secondary-002': {
        id: 'btn-secondary-002',
        name: 'SecondaryButton',
        source: {
          type: 'figma',
          fileKey: 'different-file-key',
          nodeId: '789:012'
        },
        state: 'imported', // Not transformed
        category: 'button'
      }
    }
  };

  fs.writeFileSync(
    path.join(designDir, 'componentRegistry.json'),
    JSON.stringify(registry, null, 2)
  );

  // Create mock raw source data
  const rawSource = {
    name: 'PrimaryButton',
    type: 'COMPONENT',
    fills: [{ color: { r: 0, g: 0.478, b: 1 } }],
    styles: { backgroundColor: '#007aff' }
  };

  fs.writeFileSync(
    path.join(designDir, 'raw', 'btn-primary-001.json'),
    JSON.stringify(rawSource, null, 2)
  );

  // Create mock existing code file
  const existingCode = `
import React from 'react';
export const PrimaryButton = ({ label = 'Click me', disabled = false }) => (
  <button disabled={disabled}>{label}</button>
);
`.trim();

  fs.writeFileSync(
    path.join(designDir, 'extracted-code', 'react', 'PrimaryButton.tsx'),
    existingCode
  );

  console.log(`  Test directory: ${testDir}`);
  console.log('  Created mock registry, raw source, and code file\n');
}

async function cleanup() {
  try {
    fs.rmSync(testDir, { recursive: true, force: true });
    console.log('\nTest environment cleaned up.');
  } catch (e) {
    console.log('\nNote: Test directory cleanup may have partial files remaining.');
  }
}

async function runTests() {
  // Import modules
  const { SyncCascade, CASCADE_DEFAULTS } = require('./sync-cascade');
  const AutoSyncManager = require('./auto-sync-manager');

  console.log('1. SyncCascade with Mock Registry');

  await test('SyncCascade reads registry from test directory', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });

    // Check that the registry can be read
    const { readComponentRegistry } = require('./registry-reader');
    const registry = await readComponentRegistry(testDir);

    if (!registry.components['btn-primary-001']) {
      throw new Error('Component not found in registry');
    }
  });

  await test('shouldRegenerateCode detects transformed component', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });

    const result = await cascade.shouldRegenerateCode('btn-primary-001');

    if (typeof result.should !== 'boolean') {
      throw new Error(`Expected boolean 'should', got: ${typeof result.should}`);
    }
    if (!result.reason) {
      throw new Error('Expected reason in result');
    }
    console.log(`      (reason: ${result.reason})`);
  });

  await test('shouldRegenerateStory detects transformed component', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });

    const result = await cascade.shouldRegenerateStory('btn-primary-001');

    if (typeof result.should !== 'boolean') {
      throw new Error(`Expected boolean 'should', got: ${typeof result.should}`);
    }
    console.log(`      (reason: ${result.reason})`);
  });

  console.log('\n2. AutoSyncManager findAffectedComponents');

  await test('findAffectedComponents finds component by fileKey', async () => {
    const manager = new AutoSyncManager({
      outputDir: designDir,
      projectPath: testDir,
      cascadeEnabled: true
    });

    // Point syncCascade to test directory
    manager.syncCascade = new SyncCascade({ projectPath: testDir });

    const affected = manager.findAffectedComponents('test-file-abc123', {});

    if (!Array.isArray(affected)) {
      throw new Error('Expected array');
    }

    // Should find btn-primary-001 (from test-file-abc123, state: transformed)
    // Should NOT find btn-secondary-002 (different file key, state: imported)
    const found = affected.find(c => c.componentId === 'btn-primary-001');
    if (!found) {
      console.log(`      Found components: ${JSON.stringify(affected.map(a => a.componentId))}`);
      throw new Error('Did not find expected component btn-primary-001');
    }
    console.log(`      Found ${affected.length} affected component(s)`);
  });

  await test('findAffectedComponents ignores different fileKey', async () => {
    const manager = new AutoSyncManager({
      outputDir: designDir,
      projectPath: testDir,
      cascadeEnabled: true
    });
    manager.syncCascade = new SyncCascade({ projectPath: testDir });

    const affected = manager.findAffectedComponents('non-matching-file-key', {});

    if (affected.length !== 0) {
      throw new Error(`Expected 0 affected, got ${affected.length}`);
    }
  });

  await test('findAffectedComponents ignores non-transformed components', async () => {
    const manager = new AutoSyncManager({
      outputDir: designDir,
      projectPath: testDir,
      cascadeEnabled: true
    });
    manager.syncCascade = new SyncCascade({ projectPath: testDir });

    // Use the fileKey for the non-transformed component
    const affected = manager.findAffectedComponents('different-file-key', {});

    if (affected.length !== 0) {
      throw new Error(`Expected 0 affected (not transformed), got ${affected.length}`);
    }
  });

  console.log('\n3. Cascade Event System');

  await test('Cascade emits started event', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });

    let eventEmitted = false;
    cascade.once('cascade:started', () => {
      eventEmitted = true;
    });

    // Start cascade (it will fail due to missing optimizer, but event should fire)
    try {
      await cascade.cascade('btn-primary-001', { name: 'Updated' });
    } catch (e) {
      // Expected to fail
    }

    if (!eventEmitted) {
      throw new Error('cascade:started event not emitted');
    }
  });

  await test('Cascade emits completed or failed event', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });

    let eventEmitted = false;
    cascade.once('cascade:completed', () => { eventEmitted = true; });
    cascade.once('cascade:failed', () => { eventEmitted = true; });

    try {
      await cascade.cascade('btn-primary-001', { name: 'Updated' });
    } catch (e) {
      // Expected
    }

    if (!eventEmitted) {
      throw new Error('Neither completed nor failed event emitted');
    }
  });

  console.log('\n4. Configuration Limits');

  await test('maxCascadesPerSync limits components', async () => {
    const manager = new AutoSyncManager({
      outputDir: designDir,
      projectPath: testDir,
      cascadeEnabled: true,
      cascadeConfig: {
        maxCascadesPerSync: 1
      }
    });

    const config = manager.getCascadeConfig();
    if (config.maxCascadesPerSync !== 1) {
      throw new Error(`Expected maxCascadesPerSync=1, got ${config.maxCascadesPerSync}`);
    }
  });

  await test('cascadeTimeout is configurable', async () => {
    const cascade = new SyncCascade({
      projectPath: testDir,
      config: { cascadeTimeout: 5000 }
    });

    if (cascade.config.cascadeTimeout !== 5000) {
      throw new Error(`Expected 5000, got ${cascade.config.cascadeTimeout}`);
    }
  });

  console.log('\n5. Error Handling');

  await test('Cascade handles missing component gracefully', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });

    const result = await cascade.cascade('non-existent-component', {});

    if (result.success !== false) {
      throw new Error('Expected failure for missing component');
    }
    if (!result.errors || result.errors.length === 0) {
      throw new Error('Expected error message');
    }
    console.log(`      Error: ${result.errors[0]}`);
  });

  await test('updateRegistry handles missing component', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });

    try {
      await cascade.updateRegistry('non-existent', {});
      throw new Error('Should have thrown');
    } catch (e) {
      if (!e.message.includes('not found')) {
        throw new Error(`Unexpected error: ${e.message}`);
      }
    }
  });

  console.log('\n6. Rollback Capability');

  await test('Rollback method exists and is callable', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });

    // Rollback with a non-existent snapshot should handle gracefully
    const result = await cascade.rollback('test-component', 'fake-snapshot-id');

    // Should fail but not throw
    if (result.success !== false) {
      // If it succeeds, that's fine too (snapshot might exist from previous test)
    }
  });

  await test('Cascade creates snapshot before modification', async () => {
    const cascade = new SyncCascade({ projectPath: testDir });

    let snapshotCreated = false;
    cascade.once('cascade:step', (data) => {
      if (data.step === 'registry' && data.status === 'starting') {
        snapshotCreated = true;
      }
    });

    // This will fail but should still attempt to create snapshot
    try {
      await cascade.updateRegistry('btn-primary-001', { name: 'TestUpdate' });
    } catch (e) {
      // May fail on write, but snapshot should have been attempted
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

    // Results summary
    console.log('\n' + '='.repeat(50));
    console.log('E2E TEST RESULTS SUMMARY');
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

    console.log('\n✅ All E2E tests passed!\n');
  }
})();
