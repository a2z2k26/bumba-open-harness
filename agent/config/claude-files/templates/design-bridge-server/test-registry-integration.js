#!/usr/bin/env node
/**
 * Phase 6 Sprint 6.4: Integration Test - Registry Infrastructure
 *
 * Tests that new registry functions integrate correctly with existing
 * registry-reader.js infrastructure.
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
  const testDir = path.join(os.tmpdir(), `registry-integration-test-${Date.now()}`);
  fs.mkdirSync(path.join(testDir, '.design'), { recursive: true });
  return testDir;
}

function cleanupTestDirectory(testDir) {
  try {
    fs.rmSync(testDir, { recursive: true, force: true });
  } catch (e) {}
}

console.log('\n=== Sprint 6.4: Registry Infrastructure Integration Test ===\n');

async function testRegistryIntegration() {
  const {
    readComponentRegistry,
    writeComponentRegistry,
    migrateRegistrySchema,
    createEmptyRegistry,
    invalidateCache,
    CURRENT_SCHEMA_VERSION
  } = require('./registry-reader');

  const testDir = createTestDirectory();
  console.log(`Test directory: ${testDir}\n`);

  try {
    // 1. Create empty v3 registry
    console.log('1. Empty Registry Creation');
    const empty = createEmptyRegistry();
    check('Empty registry has correct version', empty.version === CURRENT_SCHEMA_VERSION);
    check('Empty registry has components object', typeof empty.components === 'object');
    check('Empty registry has metadata', typeof empty.metadata === 'object');

    // 2. Write registry
    console.log('\n2. Write Registry');
    await writeComponentRegistry(testDir, empty);
    const registryPath = path.join(testDir, '.design', 'componentRegistry.json');
    check('Registry file created', fs.existsSync(registryPath));

    // 3. Read back
    console.log('\n3. Read Registry');
    invalidateCache(); // Ensure fresh read
    const read = await readComponentRegistry(testDir);
    check('Read matches write version', read.version === CURRENT_SCHEMA_VERSION);

    // 4. Verify backup created on subsequent write
    console.log('\n4. Backup on Subsequent Write');
    empty.components['test-1'] = {
      id: 'test-1',
      name: 'TestComponent',
      transformation: { state: 'imported' }
    };
    await writeComponentRegistry(testDir, empty, { createBackup: true });
    const backupPath = path.join(testDir, '.design', 'componentRegistry.json.bak');
    check('Backup file created (.bak)', fs.existsSync(backupPath));

    // 5. Test migration of v2 registry
    console.log('\n5. Schema Migration');
    const v2Registry = {
      version: '2.0.0',
      components: {
        'old-1': {
          id: 'old-1',
          name: 'OldComponent',
          source: { type: 'figma' }
        }
      }
    };
    const migrated = migrateRegistrySchema(v2Registry);
    check('Migration updates version to v3', migrated.version === CURRENT_SCHEMA_VERSION);
    check('Migration adds transformation field', migrated.components['old-1'].transformation !== undefined);
    check('Migration sets initial state to imported', migrated.components['old-1'].transformation.state === 'imported');
    check('Migration adds syncMetadata', migrated.components['old-1'].syncMetadata !== undefined);

    // 6. Read-write cycle maintains data integrity
    console.log('\n6. Data Integrity');
    invalidateCache();
    const finalRead = await readComponentRegistry(testDir, { forceRefresh: true });
    check('Component still exists after re-read', finalRead.components['test-1'] !== undefined);
    check('Component name preserved', finalRead.components['test-1'].name === 'TestComponent');

  } finally {
    cleanupTestDirectory(testDir);
  }

  console.log('\n' + '='.repeat(50));
  console.log('REGISTRY INTEGRATION TEST RESULTS');
  console.log('='.repeat(50));
  console.log(`\n  Total:  ${results.passed + results.failed}`);
  console.log(`  Passed: ${results.passed} ✅`);
  console.log(`  Failed: ${results.failed} ❌`);

  if (results.failed > 0) {
    process.exit(1);
  }
  console.log('\n✅ Registry infrastructure integration test passed!\n');
}

testRegistryIntegration().catch(err => {
  console.error('Test error:', err);
  process.exit(1);
});
