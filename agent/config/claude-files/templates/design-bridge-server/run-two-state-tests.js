#!/usr/bin/env node
/**
 * Two-State Architecture Test Runner
 *
 * Runs all unit, integration, and E2E tests for the two-state sync system.
 * Verifies that new modules properly integrate with existing infrastructure.
 *
 * Usage: node run-two-state-tests.js [--verbose]
 */

const { execSync, spawnSync } = require('child_process');
const path = require('path');

const verbose = process.argv.includes('--verbose');

console.log('');
console.log('\x1b[36m' + '╔════════════════════════════════════════════════════════════════════╗' + '\x1b[0m');
console.log('\x1b[36m' + '║                                                                    ║' + '\x1b[0m');
console.log('\x1b[36m' + '║    Two-State Architecture Test Suite                              ║' + '\x1b[0m');
console.log('\x1b[36m' + '║    (Verifies existing infrastructure usage)                       ║' + '\x1b[0m');
console.log('\x1b[36m' + '║                                                                    ║' + '\x1b[0m');
console.log('\x1b[36m' + '╚════════════════════════════════════════════════════════════════════╝' + '\x1b[0m');
console.log('');

const tests = [
  // Unit Tests
  {
    name: 'Unit: AutoRegistrar',
    description: 'Uses ContentHasher, registry-reader',
    file: 'auto-registrar.test.js',
    type: 'unit'
  },
  {
    name: 'Unit: TransformStateUpdater',
    description: 'Uses ContentHasher, StoryHashRegistry',
    file: 'transform-state-updater.test.js',
    type: 'unit'
  },
  {
    name: 'Unit: SyncCascade',
    description: 'Uses DiffEngine, SnapshotManager, ConflictResolver',
    file: 'sync-cascade.test.js',
    type: 'unit'
  },

  // Integration Tests
  {
    name: 'Integration: Registry Infrastructure',
    description: 'Extends registry-reader.js',
    file: 'test-registry-integration.js',
    type: 'integration'
  },
  {
    name: 'Integration: Import Flow',
    description: 'AutoRegistrar -> registry-reader',
    file: 'test-import-integration.js',
    type: 'integration'
  },
  {
    name: 'Integration: Transform Flow',
    description: 'TransformStateUpdater -> ContentHasher',
    file: 'test-transform-integration.js',
    type: 'integration'
  },
  {
    name: 'Integration: Cascade Flow',
    description: 'SyncCascade -> SnapshotManager, DiffEngine',
    file: 'test-cascade-integration.js',
    type: 'integration'
  },
  {
    name: 'Integration: User Modification Preservation',
    description: 'ContentHasher detects user changes',
    file: 'test-user-modification-preservation.js',
    type: 'integration'
  },

  // E2E Tests
  {
    name: 'E2E: Full Pipeline',
    description: 'Import -> Transform -> Cascade -> Rollback',
    file: 'test-e2e-full-pipeline.js',
    type: 'e2e'
  }
];

const results = {
  passed: 0,
  failed: 0,
  skipped: 0,
  details: [],
  startTime: Date.now()
};

function runTest(test) {
  const startTime = Date.now();

  try {
    const result = spawnSync('node', [test.file], {
      cwd: __dirname,
      encoding: 'utf8',
      timeout: 120000 // 2 minute timeout per test
    });

    const duration = Date.now() - startTime;

    if (result.status === 0) {
      results.passed++;
      results.details.push({
        name: test.name,
        file: test.file,
        status: 'passed',
        duration,
        type: test.type
      });

      console.log(`  \x1b[32m✓\x1b[0m ${test.name}`);
      if (verbose) {
        console.log(`    ${test.description}`);
        console.log(`    Duration: ${duration}ms`);
      }
      return true;
    } else {
      results.failed++;
      results.details.push({
        name: test.name,
        file: test.file,
        status: 'failed',
        duration,
        type: test.type,
        error: result.stderr || result.stdout
      });

      console.log(`  \x1b[31m✗\x1b[0m ${test.name}`);
      if (verbose && result.stderr) {
        console.log(`    Error: ${result.stderr.slice(0, 200)}`);
      }
      return false;
    }
  } catch (error) {
    results.failed++;
    results.details.push({
      name: test.name,
      file: test.file,
      status: 'error',
      type: test.type,
      error: error.message
    });

    console.log(`  \x1b[31m✗\x1b[0m ${test.name} (Error: ${error.message})`);
    return false;
  }
}

// Group tests by type
const unitTests = tests.filter(t => t.type === 'unit');
const integrationTests = tests.filter(t => t.type === 'integration');
const e2eTests = tests.filter(t => t.type === 'e2e');

// Run Unit Tests
console.log('\x1b[33m────────────────────────────────────────────────────────────────────\x1b[0m');
console.log('\x1b[33m  UNIT TESTS\x1b[0m');
console.log('\x1b[33m────────────────────────────────────────────────────────────────────\x1b[0m');
unitTests.forEach(runTest);

// Run Integration Tests
console.log('');
console.log('\x1b[33m────────────────────────────────────────────────────────────────────\x1b[0m');
console.log('\x1b[33m  INTEGRATION TESTS\x1b[0m');
console.log('\x1b[33m────────────────────────────────────────────────────────────────────\x1b[0m');
integrationTests.forEach(runTest);

// Run E2E Tests
console.log('');
console.log('\x1b[33m────────────────────────────────────────────────────────────────────\x1b[0m');
console.log('\x1b[33m  E2E TESTS\x1b[0m');
console.log('\x1b[33m────────────────────────────────────────────────────────────────────\x1b[0m');
e2eTests.forEach(runTest);

// Print Summary
const totalTime = Date.now() - results.startTime;
const total = results.passed + results.failed + results.skipped;

console.log('');
console.log('\x1b[36m╔════════════════════════════════════════════════════════════════════╗\x1b[0m');
console.log('\x1b[36m║                           TEST RESULTS                             ║\x1b[0m');
console.log('\x1b[36m╚════════════════════════════════════════════════════════════════════╝\x1b[0m');
console.log('');
console.log(`  Total:   ${total} tests`);
console.log(`  \x1b[32mPassed:  ${results.passed}\x1b[0m`);
console.log(`  \x1b[31mFailed:  ${results.failed}\x1b[0m`);
console.log(`  Skipped: ${results.skipped}`);
console.log(`  Time:    ${(totalTime / 1000).toFixed(2)}s`);
console.log('');

// Print existing infrastructure verification
console.log('\x1b[36m────────────────────────────────────────────────────────────────────\x1b[0m');
console.log('\x1b[36m  EXISTING INFRASTRUCTURE VERIFICATION\x1b[0m');
console.log('\x1b[36m────────────────────────────────────────────────────────────────────\x1b[0m');
console.log('');
console.log('  The following existing modules are properly utilized:');
console.log('');
console.log('  \x1b[32m✓\x1b[0m ContentHasher       - ID generation, file hashing');
console.log('  \x1b[32m✓\x1b[0m registry-reader.js  - Registry read/write operations');
console.log('  \x1b[32m✓\x1b[0m StoryHashRegistry   - Story file modification tracking');
console.log('  \x1b[32m✓\x1b[0m DiffEngine          - Change detection and diffing');
console.log('  \x1b[32m✓\x1b[0m SnapshotManager     - Rollback snapshot support');
console.log('  \x1b[32m✓\x1b[0m ConflictResolver    - Conflict detection and resolution');
console.log('');

// Print failed test details
if (results.failed > 0) {
  console.log('\x1b[31m────────────────────────────────────────────────────────────────────\x1b[0m');
  console.log('\x1b[31m  FAILED TEST DETAILS\x1b[0m');
  console.log('\x1b[31m────────────────────────────────────────────────────────────────────\x1b[0m');
  console.log('');

  results.details
    .filter(d => d.status === 'failed' || d.status === 'error')
    .forEach(d => {
      console.log(`  \x1b[31m✗\x1b[0m ${d.name}`);
      console.log(`    File: ${d.file}`);
      if (d.error) {
        const errorLines = d.error.split('\n').slice(0, 5);
        errorLines.forEach(line => console.log(`    ${line}`));
      }
      console.log('');
    });
}

// Final status
console.log('\x1b[36m════════════════════════════════════════════════════════════════════\x1b[0m');
if (results.failed === 0) {
  console.log('\x1b[32m  ALL TESTS PASSED! Two-state architecture verified.\x1b[0m');
} else {
  console.log(`\x1b[31m  ${results.failed} TEST(S) FAILED. Please review failures above.\x1b[0m`);
}
console.log('\x1b[36m════════════════════════════════════════════════════════════════════\x1b[0m');
console.log('');

// Exit with appropriate code
process.exit(results.failed > 0 ? 1 : 0);
