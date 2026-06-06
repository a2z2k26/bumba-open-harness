#!/usr/bin/env node
/**
 * Phase 6 Sprint 6.6: Integration Test - Transform Flow
 *
 * Tests complete import -> transform -> state tracking flow.
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
  const testDir = path.join(os.tmpdir(), `transform-integration-test-${Date.now()}`);
  fs.mkdirSync(path.join(testDir, '.design', 'extracted-code', 'react'), { recursive: true });
  fs.mkdirSync(path.join(testDir, '.design', 'stories'), { recursive: true });
  return testDir;
}

function cleanupTestDirectory(testDir) {
  try {
    fs.rmSync(testDir, { recursive: true, force: true });
  } catch (e) {}
}

console.log('\n=== Sprint 6.6: Transform Flow Integration Test ===\n');

async function testTransformFlow() {
  const { AutoRegistrar } = require('./auto-registrar');
  const { TransformStateUpdater } = require('./transform-state-updater');
  const { readComponentRegistry, invalidateCache } = require('./registry-reader');

  const testDir = createTestDirectory();
  console.log(`Test directory: ${testDir}\n`);

  try {
    // 1. Import a component
    console.log('1. Import Component');
    const registrar = new AutoRegistrar({ projectPath: testDir });
    const importResult = await registrar.registerComponent(
      { name: 'TestButton', type: 'COMPONENT' },
      { type: 'figma-plugin', nodeId: '1:234' }
    );

    check('Import succeeded', importResult.success);
    const componentId = importResult.id;
    check('Has component ID', componentId !== undefined);

    // 2. Check initial state is 'imported'
    console.log('\n2. Verify Initial State');
    let registry = await readComponentRegistry(testDir, { forceRefresh: true });
    let component = registry.components[componentId];

    check('Component found in registry', component !== undefined);
    check('Initial state is imported', component?.transformation?.state === 'imported');

    // 3. Create code file (simulating transform output)
    console.log('\n3. Simulate Transform Output');
    const codePath = '.design/extracted-code/react/TestButton.tsx';
    const fullCodePath = path.join(testDir, codePath);
    const codeContent = `export const TestButton = ({ label }) => <button>{label}</button>;`;
    fs.writeFileSync(fullCodePath, codeContent);

    check('Code file created', fs.existsSync(fullCodePath));

    // 4. Mark as transformed using TransformStateUpdater
    console.log('\n4. Mark as Transformed');
    const updater = new TransformStateUpdater({ projectPath: testDir });
    const transformResult = await updater.markTransformed(componentId, {
      framework: 'react',
      codePath
    });

    check('Transform marking succeeded', transformResult.success);
    check('State is now transformed', transformResult.transformation?.state === 'transformed');
    check('Framework is react', transformResult.transformation?.framework === 'react');
    check('Code hash calculated', transformResult.transformation?.codeHash !== null);

    // 5. Verify registry updated
    console.log('\n5. Verify Registry Update');
    invalidateCache();
    registry = await readComponentRegistry(testDir, { forceRefresh: true });
    component = registry.components[componentId];

    check('Component still in registry', component !== undefined);
    check('Registry shows transformed state', component?.transformation?.state === 'transformed');
    check('Registry has codePath', component?.transformation?.codePath === codePath);
    check('Registry has codeHash', component?.transformation?.codeHash !== null);

    // 6. Test needsRetransform (should be false - up to date)
    console.log('\n6. Check needsRetransform');
    const retransformCheck = await updater.needsRetransform(componentId);

    check('needsRetransform returns object', typeof retransformCheck === 'object');
    check('Does not need retransform (up to date)', retransformCheck.needs === false);

    // 7. Test getTransformState
    console.log('\n7. Get Transform State');
    const state = await updater.getTransformState(componentId);

    check('getTransformState returns state', state !== null);
    check('State matches registry', state?.state === 'transformed');

    // 8. Test listTransformed
    console.log('\n8. List Transformed Components');
    const transformed = await updater.listTransformed();

    check('listTransformed returns array', Array.isArray(transformed));
    check('Contains our component', transformed.some(c => c.id === componentId));

    // 9. Test getStats
    console.log('\n9. Get Statistics');
    const stats = await updater.getStats();

    check('Stats has total count', stats.total >= 1);
    check('Stats has transformed count', stats.transformed >= 1);
    check('Stats by framework has react', stats.byFramework.react >= 1);

  } finally {
    cleanupTestDirectory(testDir);
  }

  console.log('\n' + '='.repeat(50));
  console.log('TRANSFORM FLOW INTEGRATION TEST RESULTS');
  console.log('='.repeat(50));
  console.log(`\n  Total:  ${results.passed + results.failed}`);
  console.log(`  Passed: ${results.passed} ✅`);
  console.log(`  Failed: ${results.failed} ❌`);

  if (results.failed > 0) {
    process.exit(1);
  }
  console.log('\n✅ Transform flow integration test passed!\n');
}

testTransformFlow().catch(err => {
  console.error('Test error:', err);
  process.exit(1);
});
