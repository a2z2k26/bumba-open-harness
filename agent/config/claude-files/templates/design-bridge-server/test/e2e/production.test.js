/**
 * Production Hardening Test Suite
 * Phase 3 - Sprints 177-180: Health Checks & Graceful Degradation
 */

const path = require('path');
const fs = require('fs');

// Modules under test
const {
  HealthStatus,
  ComponentType,
  CircuitBreaker,
  HealthCheck,
  HealthCheckRegistry,
  DegradationManager,
  createMemoryCheck,
  createFileSystemCheck,
  createModuleCheck,
  getHealthRegistry,
  getDegradationManager,
  resetHealthSystem
} = require('../../health-check');

// Test configuration
const ROOT_DIR = path.join(__dirname, '..', '..');
const TEST_DIR = path.join(ROOT_DIR, '.test-health');

// Results tracking
const results = {
  passed: 0,
  failed: 0,
  tests: []
};

// ANSI colors
const colors = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  red: '\x1b[31m',
  cyan: '\x1b[36m',
  dim: '\x1b[2m',
  bold: '\x1b[1m'
};

/**
 * Test runner helper
 */
function test(name, fn) {
  try {
    const result = fn();
    if (result === true || result === undefined) {
      results.passed++;
      results.tests.push({ name, status: 'PASS' });
      console.log(`  ${colors.green}✓${colors.reset} ${name}`);
    } else {
      results.failed++;
      results.tests.push({ name, status: 'FAIL', error: `Returned: ${JSON.stringify(result)}` });
      console.log(`  ${colors.red}✗${colors.reset} ${name}`);
    }
  } catch (error) {
    results.failed++;
    results.tests.push({ name, status: 'FAIL', error: error.message });
    console.log(`  ${colors.red}✗${colors.reset} ${name}`);
    console.log(`    ${colors.dim}Error: ${error.message}${colors.reset}`);
  }
}

/**
 * Async test runner
 */
async function testAsync(name, fn) {
  try {
    const result = await fn();
    if (result === true || result === undefined) {
      results.passed++;
      results.tests.push({ name, status: 'PASS' });
      console.log(`  ${colors.green}✓${colors.reset} ${name}`);
    } else {
      results.failed++;
      results.tests.push({ name, status: 'FAIL', error: `Returned: ${JSON.stringify(result)}` });
      console.log(`  ${colors.red}✗${colors.reset} ${name}`);
    }
  } catch (error) {
    results.failed++;
    results.tests.push({ name, status: 'FAIL', error: error.message });
    console.log(`  ${colors.red}✗${colors.reset} ${name}`);
    console.log(`    ${colors.dim}Error: ${error.message}${colors.reset}`);
  }
}

// =============================================================================
// HEALTH STATUS TESTS
// =============================================================================

function runHealthStatusTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 1: Health Status Types${colors.reset}                      ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  test('HealthStatus has correct values', () => {
    return HealthStatus.HEALTHY === 'healthy' &&
           HealthStatus.DEGRADED === 'degraded' &&
           HealthStatus.UNHEALTHY === 'unhealthy';
  });

  test('ComponentType has correct values', () => {
    return ComponentType.CORE === 'core' &&
           ComponentType.CACHE === 'cache' &&
           ComponentType.FILESYSTEM === 'filesystem' &&
           ComponentType.EXTERNAL === 'external';
  });
}

// =============================================================================
// CIRCUIT BREAKER TESTS
// =============================================================================

async function runCircuitBreakerTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 2: Circuit Breaker${colors.reset}                           ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  test('CircuitBreaker instantiates correctly', () => {
    const breaker = new CircuitBreaker({ name: 'test', threshold: 3 });
    return breaker.name === 'test' && breaker.threshold === 3 && breaker.state === 'CLOSED';
  });

  await testAsync('CircuitBreaker executes successful operations', async () => {
    const breaker = new CircuitBreaker({ name: 'test' });
    const result = await breaker.execute(async () => 'success');
    return result === 'success' && breaker.successes === 1;
  });

  await testAsync('CircuitBreaker opens after threshold failures', async () => {
    const breaker = new CircuitBreaker({ name: 'test', threshold: 2 });

    try {
      await breaker.execute(async () => { throw new Error('fail'); });
    } catch (e) {}

    try {
      await breaker.execute(async () => { throw new Error('fail'); });
    } catch (e) {}

    return breaker.state === 'OPEN' && breaker.failures === 2;
  });

  await testAsync('CircuitBreaker uses fallback when open', async () => {
    const breaker = new CircuitBreaker({ name: 'test', threshold: 1, resetTimeout: 10000 });

    try {
      await breaker.execute(async () => { throw new Error('fail'); });
    } catch (e) {}

    const result = await breaker.execute(
      async () => 'success',
      'fallback'
    );

    return result === 'fallback';
  });

  await testAsync('CircuitBreaker resets on success in half-open', async () => {
    const breaker = new CircuitBreaker({ name: 'test', threshold: 1, resetTimeout: 10 });

    try {
      await breaker.execute(async () => { throw new Error('fail'); });
    } catch (e) {}

    // Wait for reset timeout
    await new Promise(r => setTimeout(r, 20));

    await breaker.execute(async () => 'success');

    return breaker.state === 'CLOSED';
  });

  test('CircuitBreaker getStats returns correct structure', () => {
    const breaker = new CircuitBreaker({ name: 'test' });
    const stats = breaker.getStats();
    return stats.name === 'test' && stats.state === 'CLOSED' &&
           stats.failures === 0 && stats.successes === 0;
  });

  test('CircuitBreaker reset clears state', () => {
    const breaker = new CircuitBreaker({ name: 'test' });
    breaker.failures = 5;
    breaker.state = 'OPEN';
    breaker.reset();
    return breaker.failures === 0 && breaker.state === 'CLOSED';
  });
}

// =============================================================================
// HEALTH CHECK TESTS
// =============================================================================

async function runHealthCheckTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 3: Health Check${colors.reset}                               ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  await testAsync('HealthCheck runs and returns healthy', async () => {
    const check = new HealthCheck('test', async () => ({ ok: true }));
    const result = await check.check();
    return result.status === HealthStatus.HEALTHY &&
           result.details.ok === true;
  });

  await testAsync('HealthCheck returns unhealthy on error', async () => {
    const check = new HealthCheck('test', async () => { throw new Error('failed'); });
    const result = await check.check();
    return result.status === HealthStatus.UNHEALTHY &&
           result.error === 'failed';
  });

  await testAsync('HealthCheck respects timeout', async () => {
    const check = new HealthCheck('test', async () => {
      await new Promise(r => setTimeout(r, 200));
      return { ok: true };
    }, { timeout: 50 });

    const result = await check.check();
    return result.status === HealthStatus.UNHEALTHY &&
           result.error === 'Health check timeout';
  });

  await testAsync('HealthCheck stores last result', async () => {
    const check = new HealthCheck('test', async () => ({ value: 42 }));
    await check.check();
    return check.lastResult !== null &&
           check.lastResult.details.value === 42;
  });
}

// =============================================================================
// HEALTH REGISTRY TESTS
// =============================================================================

async function runHealthRegistryTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 4: Health Check Registry${colors.reset}                     ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  // Reset before tests
  resetHealthSystem();

  test('HealthCheckRegistry instantiates correctly', () => {
    const registry = new HealthCheckRegistry();
    return registry.checks.size === 0;
  });

  test('HealthCheckRegistry register adds check', () => {
    const registry = new HealthCheckRegistry();
    registry.register('test', async () => ({}));
    return registry.checks.size === 1 && registry.checks.has('test');
  });

  test('HealthCheckRegistry unregister removes check', () => {
    const registry = new HealthCheckRegistry();
    registry.register('test', async () => ({}));
    registry.unregister('test');
    return registry.checks.size === 0;
  });

  await testAsync('HealthCheckRegistry checkOne runs specific check', async () => {
    const registry = new HealthCheckRegistry();
    registry.register('test', async () => ({ value: 123 }));
    const result = await registry.checkOne('test');
    registry.destroy();
    return result.status === HealthStatus.HEALTHY && result.details.value === 123;
  });

  await testAsync('HealthCheckRegistry checkAll runs all checks', async () => {
    const registry = new HealthCheckRegistry();
    registry.register('check1', async () => ({ id: 1 }));
    registry.register('check2', async () => ({ id: 2 }));
    const results = await registry.checkAll();
    registry.destroy();
    return results.check1 !== undefined && results.check2 !== undefined;
  });

  await testAsync('HealthCheckRegistry getOverallStatus aggregates', async () => {
    const registry = new HealthCheckRegistry();
    registry.register('healthy', async () => ({}));
    registry.register('failing', async () => { throw new Error('fail'); }, { critical: false });

    const status = await registry.getOverallStatus();
    registry.destroy();

    return status.status === HealthStatus.DEGRADED &&
           status.summary.healthy === 1 &&
           status.summary.unhealthy === 1;
  });

  await testAsync('HealthCheckRegistry critical failure = unhealthy', async () => {
    const registry = new HealthCheckRegistry();
    registry.register('critical', async () => { throw new Error('fail'); }, { critical: true });

    const status = await registry.getOverallStatus();
    registry.destroy();

    return status.status === HealthStatus.UNHEALTHY;
  });

  test('getHealthRegistry returns singleton', () => {
    resetHealthSystem();
    const reg1 = getHealthRegistry();
    const reg2 = getHealthRegistry();
    resetHealthSystem();
    return reg1 === reg2;
  });
}

// =============================================================================
// BUILT-IN CHECKS TESTS
// =============================================================================

async function runBuiltInChecksTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 5: Built-in Health Checks${colors.reset}                    ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  await testAsync('createMemoryCheck returns memory stats', async () => {
    const check = createMemoryCheck();
    const result = await check();
    return result.heapUsed !== undefined &&
           result.heapTotal !== undefined &&
           result.rss !== undefined;
  });

  await testAsync('createFileSystemCheck verifies write/read', async () => {
    // Ensure test directory exists
    if (!fs.existsSync(TEST_DIR)) {
      fs.mkdirSync(TEST_DIR, { recursive: true });
    }

    const check = createFileSystemCheck(TEST_DIR);
    const result = await check();

    // Cleanup
    try { fs.rmdirSync(TEST_DIR); } catch (e) {}

    return result.writable === true && result.readable === true;
  });

  await testAsync('createModuleCheck verifies module loading', async () => {
    const modulePath = path.join(ROOT_DIR, 'unified-logger');
    const check = createModuleCheck(modulePath);
    const result = await check();
    return result.loaded === true && result.exports > 0;
  });

  await testAsync('createModuleCheck fails for missing module', async () => {
    const check = createModuleCheck('./nonexistent-module-xyz');
    try {
      await check();
      return false;
    } catch (error) {
      return error.message.includes('Module check failed');
    }
  });
}

// =============================================================================
// DEGRADATION MANAGER TESTS
// =============================================================================

async function runDegradationTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 6: Degradation Manager${colors.reset}                       ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  test('DegradationManager instantiates correctly', () => {
    const manager = new DegradationManager();
    return manager.features.size === 0;
  });

  test('DegradationManager registerFeature works', () => {
    const manager = new DegradationManager();
    manager.registerFeature('feature1');
    return manager.features.has('feature1') && manager.isEnabled('feature1') === true;
  });

  test('DegradationManager disable/enable work', () => {
    const manager = new DegradationManager();
    manager.registerFeature('feature1');
    manager.disable('feature1', 'Testing');
    const disabled = manager.isEnabled('feature1');
    manager.enable('feature1');
    const enabled = manager.isEnabled('feature1');
    return disabled === false && enabled === true;
  });

  test('DegradationManager override takes precedence', () => {
    const manager = new DegradationManager();
    manager.registerFeature('feature1');
    manager.override('feature1', false);
    return manager.isEnabled('feature1') === false;
  });

  test('DegradationManager clearOverride restores original', () => {
    const manager = new DegradationManager();
    manager.registerFeature('feature1');
    manager.override('feature1', false);
    manager.clearOverride('feature1');
    return manager.isEnabled('feature1') === true;
  });

  await testAsync('DegradationManager execute runs enabled feature', async () => {
    const manager = new DegradationManager();
    manager.registerFeature('feature1');

    const result = await manager.execute('feature1', async () => 'success');
    return result === 'success';
  });

  await testAsync('DegradationManager execute uses fallback when disabled', async () => {
    const manager = new DegradationManager();
    manager.registerFeature('feature1', { fallback: 'fallback-value' });
    manager.disable('feature1');

    const result = await manager.execute('feature1', async () => 'success');
    return result === 'fallback-value';
  });

  await testAsync('DegradationManager execute uses fallback on error', async () => {
    const manager = new DegradationManager();
    manager.registerFeature('feature1', { fallback: () => 'recovered' });

    const result = await manager.execute(
      'feature1',
      async () => { throw new Error('fail'); }
    );
    return result === 'recovered';
  });

  test('DegradationManager getStatus returns all features', () => {
    const manager = new DegradationManager();
    manager.registerFeature('feature1');
    manager.registerFeature('feature2');
    manager.disable('feature2');

    const status = manager.getStatus();
    return status.feature1.enabled === true &&
           status.feature2.enabled === false;
  });

  test('getDegradationManager returns singleton', () => {
    resetHealthSystem();
    const mgr1 = getDegradationManager();
    const mgr2 = getDegradationManager();
    resetHealthSystem();
    return mgr1 === mgr2;
  });
}

// =============================================================================
// MAIN TEST RUNNER
// =============================================================================

async function runAllTests() {
  console.log(`${colors.bold}${colors.cyan}`);
  console.log('╔═══════════════════════════════════════════════════════════╗');
  console.log('║     PRODUCTION HARDENING TEST SUITE                       ║');
  console.log('║              Phase 3: Sprints 177-180                     ║');
  console.log('╚═══════════════════════════════════════════════════════════╝');
  console.log(`${colors.reset}`);

  const startTime = Date.now();

  // Run all test suites
  runHealthStatusTests();
  await runCircuitBreakerTests();
  await runHealthCheckTests();
  await runHealthRegistryTests();
  await runBuiltInChecksTests();
  await runDegradationTests();

  const duration = Date.now() - startTime;

  // Cleanup
  resetHealthSystem();
  try { fs.rmdirSync(TEST_DIR, { recursive: true }); } catch (e) {}

  // Summary
  console.log(`\n${colors.cyan}╔═══════════════════════════════════════════════════════════╗${colors.reset}`);
  console.log(`${colors.cyan}║${colors.reset}${colors.bold}                    TEST SUMMARY                           ${colors.reset}${colors.cyan}║${colors.reset}`);
  console.log(`${colors.cyan}╚═══════════════════════════════════════════════════════════╝${colors.reset}`);
  console.log('');
  console.log(`  ${colors.bold}Total Tests:${colors.reset}   ${results.passed + results.failed}`);
  console.log(`  ${colors.green}Passed:${colors.reset}        ${results.passed}`);
  console.log(`  ${colors.red}Failed:${colors.reset}        ${results.failed}`);
  console.log(`  ${colors.dim}Duration:${colors.reset}      ${duration}ms`);
  console.log('');

  if (results.failed === 0) {
    console.log(`  ${colors.green}${colors.bold}✓ All production tests passed!${colors.reset}`);
  } else {
    console.log(`  ${colors.red}${colors.bold}✗ ${results.failed} test(s) failed${colors.reset}`);
    console.log('');
    console.log(`  ${colors.dim}Failed tests:${colors.reset}`);
    results.tests
      .filter(t => t.status === 'FAIL')
      .forEach(t => console.log(`    - ${t.name}: ${t.error}`));
  }

  console.log('');

  return {
    passed: results.passed,
    failed: results.failed,
    total: results.passed + results.failed,
    duration
  };
}

// Export for use as module
module.exports = { run: runAllTests, runAllTests };

// Run if called directly
if (require.main === module) {
  runAllTests()
    .then(results => {
      process.exit(results.failed > 0 ? 1 : 0);
    })
    .catch(err => {
      console.error(`${colors.red}Fatal error:${colors.reset}`, err);
      process.exit(1);
    });
}
