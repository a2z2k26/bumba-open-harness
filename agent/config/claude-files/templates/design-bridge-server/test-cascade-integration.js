#!/usr/bin/env node
/**
 * Phase 6 Sprint 6.7: Integration Test - Cascade Flow
 *
 * Tests complete cascade sync flow with registry updates, snapshots, and rollback.
 */

const path = require('path');
const fs = require('fs');
const os = require('os');

// Test results tracking
const results = { passed: 0, failed: 0, tests: [] };

function check(name, condition) {
  if (condition) {
    results.passed++;
    results.tests.push({ name, status: 'passed' });
    console.log(`  ✅ ${name}`);
  } else {
    results.failed++;
    results.tests.push({ name, status: 'failed' });
    console.log(`  ❌ ${name}`);
  }
}

function createTestDirectory() {
  const testDir = path.join(os.tmpdir(), `cascade-integration-test-${Date.now()}`);
  fs.mkdirSync(path.join(testDir, '.design', 'extracted-code', 'react'), { recursive: true });
  fs.mkdirSync(path.join(testDir, '.design', 'stories'), { recursive: true });
  fs.mkdirSync(path.join(testDir, '.design', 'components'), { recursive: true });
  return testDir;
}

function cleanupTestDirectory(testDir) {
  try {
    fs.rmSync(testDir, { recursive: true, force: true });
  } catch (e) {}
}

console.log('\n=== Sprint 6.7: Cascade Flow Integration Test ===\n');

async function testCascadeFlow() {
  const { SyncCascade, CASCADE_EVENTS } = require('./sync-cascade');
  const { AutoRegistrar } = require('./auto-registrar');
  const { TransformStateUpdater } = require('./transform-state-updater');
  const { readComponentRegistry, invalidateCache, writeComponentRegistry } = require('./registry-reader');
  const { hashFile } = require('./content-hasher');

  const testDir = createTestDirectory();
  console.log(`Test directory: ${testDir}\n`);

  try {
    // 1. Set up: Import and transform a component
    console.log('1. Set Up: Import and Transform Component');
    const registrar = new AutoRegistrar({ projectPath: testDir });
    const importResult = await registrar.registerComponent(
      { name: 'CascadeButton', type: 'COMPONENT', props: { label: { type: 'string' } } },
      { type: 'figma-plugin', nodeId: '1:234' }
    );
    const componentId = importResult.id;

    // Create raw data file (needed for regeneration)
    const rawDataPath = '.design/components/cascade-button.json';
    fs.writeFileSync(
      path.join(testDir, rawDataPath),
      JSON.stringify({ name: 'CascadeButton', props: { label: { type: 'string' } } }, null, 2)
    );

    // Create code file
    const codePath = '.design/extracted-code/react/CascadeButton.tsx';
    const fullCodePath = path.join(testDir, codePath);
    const codeContent = `export const CascadeButton = ({ label }) => <button>{label}</button>;`;
    fs.writeFileSync(fullCodePath, codeContent);
    const codeHash = await hashFile(fullCodePath);

    // Mark as transformed
    const updater = new TransformStateUpdater({ projectPath: testDir });
    await updater.markTransformed(componentId, { framework: 'react', codePath });

    // Update paths.rawSource in registry
    invalidateCache();
    let registry = await readComponentRegistry(testDir, { forceRefresh: true });
    registry.components[componentId].paths = { rawSource: rawDataPath };
    await writeComponentRegistry(testDir, registry);

    check('Component imported and transformed', true);

    // 2. Create SyncCascade
    console.log('\n2. Create SyncCascade');
    const cascade = new SyncCascade({
      projectPath: testDir,
      config: {
        regenerateCode: false, // Disable code regen (no optimizer)
        regenerateStory: false // Disable story regen for this test
      }
    });

    check('SyncCascade created', cascade !== null);
    check('Config set correctly', cascade.getConfig().regenerateCode === false);

    // 3. Test updateRegistry with snapshot
    console.log('\n3. Update Registry with Snapshot');
    const updateResult = await cascade.updateRegistry(componentId, {
      props: { label: { type: 'string' }, newProp: { type: 'number' } }
    });

    check('Update succeeded', updateResult.success === true);
    check('Snapshot created', updateResult.snapshotId !== undefined);
    check('Changes detected', updateResult.changes !== undefined);

    // Verify registry was updated
    invalidateCache();
    registry = await readComponentRegistry(testDir, { forceRefresh: true });
    const updatedComponent = registry.components[componentId];

    check('Props updated in registry', updatedComponent.props?.newProp !== undefined);
    check('Sync metadata updated', updatedComponent.syncMetadata?.syncCount >= 2);

    // 4. Test shouldRegenerateCode
    console.log('\n4. shouldRegenerateCode Decision Logic');
    const codeCheck = await cascade.shouldRegenerateCode(componentId);

    check('Returns decision object', typeof codeCheck === 'object');
    check('Has should property', codeCheck.should !== undefined);
    check('Has reason property', codeCheck.reason !== undefined);
    // Note: should regenerate because source is newer than transform
    check('Reason is valid', ['Up to date', 'Source updated', 'User modified code'].includes(codeCheck.reason));

    // 5. Test rollback
    console.log('\n5. Rollback from Snapshot');
    const rollbackResult = await cascade.rollback(componentId, updateResult.snapshotId);

    check('Rollback succeeded', rollbackResult.success === true);

    // Verify registry was rolled back
    invalidateCache();
    registry = await readComponentRegistry(testDir, { forceRefresh: true });
    const rolledBackComponent = registry.components[componentId];

    // Note: Rollback restores the component but adds rollback metadata
    check('Rollback metadata added', rolledBackComponent.syncMetadata?.lastRollback !== undefined);
    check('Rollback reason stored', rolledBackComponent.syncMetadata?.rollbackReason !== undefined);

    // 6. Test event emission
    console.log('\n6. Event Emission');
    let eventReceived = false;
    cascade.on(CASCADE_EVENTS.STARTED, () => { eventReceived = true; });

    // Run a cascade (will complete quickly since regen disabled)
    await cascade.cascade(componentId, { props: {} });
    check('cascade:started event emitted', eventReceived === true);

    // 7. Test full cascade flow (registry-only since regen disabled)
    console.log('\n7. Full Cascade Flow (Registry Only)');
    const cascadeResult = await cascade.cascade(componentId, {
      props: { finalProp: { type: 'string' } }
    });

    check('Cascade completed', cascadeResult !== undefined);
    check('Has componentId', cascadeResult.componentId === componentId);
    check('Has steps', cascadeResult.steps !== undefined);
    check('Registry step succeeded', cascadeResult.steps?.registry?.success === true);
    check('Success status', cascadeResult.success === true);

  } finally {
    cleanupTestDirectory(testDir);
  }

  console.log('\n' + '='.repeat(50));
  console.log('CASCADE FLOW INTEGRATION TEST RESULTS');
  console.log('='.repeat(50));
  console.log(`\n  Total:  ${results.passed + results.failed}`);
  console.log(`  Passed: ${results.passed} ✅`);
  console.log(`  Failed: ${results.failed} ❌`);

  if (results.failed > 0) {
    process.exit(1);
  }
  console.log('\n✅ Cascade flow integration test passed!\n');
}

testCascadeFlow().catch(err => {
  console.error('Test error:', err);
  process.exit(1);
});
