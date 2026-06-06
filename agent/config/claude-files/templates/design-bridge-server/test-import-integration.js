#!/usr/bin/env node
/**
 * Phase 6 Sprint 6.5: Integration Test - Import Flow
 *
 * Tests complete import -> auto-registration flow using existing infrastructure.
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
  const testDir = path.join(os.tmpdir(), `import-integration-test-${Date.now()}`);
  fs.mkdirSync(path.join(testDir, '.design'), { recursive: true });
  return testDir;
}

function cleanupTestDirectory(testDir) {
  try {
    fs.rmSync(testDir, { recursive: true, force: true });
  } catch (e) {}
}

console.log('\n=== Sprint 6.5: Import Flow Integration Test ===\n');

async function testImportFlow() {
  const { AutoRegistrar } = require('./auto-registrar');
  const { readComponentRegistry, invalidateCache } = require('./registry-reader');

  const testDir = createTestDirectory();
  console.log(`Test directory: ${testDir}\n`);

  try {
    // 1. Create registrar with project path
    console.log('1. AutoRegistrar Creation');
    const registrar = new AutoRegistrar({ projectPath: testDir });
    check('AutoRegistrar instance created', registrar !== null);
    check('Has correct projectPath', registrar.projectPath === testDir);

    // 2. Register a component from figma-plugin source
    console.log('\n2. Register Figma Plugin Component');
    const figmaPluginResult = await registrar.registerComponent(
      { name: 'PrimaryButton', type: 'COMPONENT' },
      { type: 'figma-plugin', nodeId: '1:234' }
    );

    check('Figma plugin registration succeeded', figmaPluginResult.success);
    check('Is new component', figmaPluginResult.isNew === true);
    check('Has component ID', figmaPluginResult.id !== undefined);
    check('Has transformation field', figmaPluginResult.entry?.transformation !== undefined);
    check('State is imported', figmaPluginResult.entry?.transformation?.state === 'imported');

    // 3. Register a component from figma-mcp source
    console.log('\n3. Register Figma MCP Component');
    const figmaMcpResult = await registrar.registerComponent(
      { name: 'SecondaryButton', type: 'COMPONENT' },
      { type: 'figma-mcp', nodeId: '2:345', fileKey: 'abc123' }
    );

    check('Figma MCP registration succeeded', figmaMcpResult.success);
    check('Source type is figma-mcp', figmaMcpResult.entry?.source?.type === 'figma-mcp');
    check('FileKey stored', figmaMcpResult.entry?.source?.fileKey === 'abc123');

    // 4. Register a component from shadcn source
    console.log('\n4. Register ShadCN Component');
    const shadcnResult = await registrar.registerComponent(
      { name: 'Card', type: 'COMPONENT' },
      { type: 'shadcn', registryItem: '@shadcn/card' }
    );

    check('ShadCN registration succeeded', shadcnResult.success);
    check('Source type is shadcn', shadcnResult.entry?.source?.type === 'shadcn');

    // 5. Verify registry using existing reader
    console.log('\n5. Verify Registry Contents');
    invalidateCache();
    const registry = await readComponentRegistry(testDir, { forceRefresh: true });

    check('Registry has components', registry.components !== undefined);
    check('Has 3 components', Object.keys(registry.components).length === 3);

    // 6. Re-registration updates sync metadata
    console.log('\n6. Re-registration Updates Sync Metadata');
    const reRegisterResult = await registrar.registerComponent(
      { name: 'PrimaryButton', type: 'COMPONENT' },
      { type: 'figma-plugin', nodeId: '1:234' }
    );

    check('Re-registration succeeded', reRegisterResult.success);
    check('Is NOT new (already exists)', reRegisterResult.isNew === false);
    check('Sync count incremented', reRegisterResult.entry?.syncMetadata?.syncCount === 2);

  } finally {
    cleanupTestDirectory(testDir);
  }

  console.log('\n' + '='.repeat(50));
  console.log('IMPORT FLOW INTEGRATION TEST RESULTS');
  console.log('='.repeat(50));
  console.log(`\n  Total:  ${results.passed + results.failed}`);
  console.log(`  Passed: ${results.passed} ✅`);
  console.log(`  Failed: ${results.failed} ❌`);

  if (results.failed > 0) {
    process.exit(1);
  }
  console.log('\n✅ Import flow integration test passed!\n');
}

testImportFlow().catch(err => {
  console.error('Test error:', err);
  process.exit(1);
});
