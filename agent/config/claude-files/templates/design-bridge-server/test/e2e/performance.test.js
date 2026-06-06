/**
 * Performance Optimization Test Suite
 * Phase 3 - Sprints 153-164: Caching and Async Operations
 */

const path = require('path');

// Modules under test
const {
  LRUCache,
  FileCache,
  CacheManager,
  ComponentCache,
  TokenCache,
  FigmaCache,
  getCacheManager,
  resetCacheManager
} = require('../../cache-manager');

const {
  sleep,
  createDeferred,
  withTimeout,
  retry,
  RateLimiter,
  BatchProcessor,
  AsyncQueue,
  Pipeline,
  PipelineStage,
  parallel,
  mapAsync,
  filterAsync,
  reduceAsync,
  withFallback,
  debounceAsync,
  throttleAsync
} = require('../../async-pipeline');

// Test configuration
const ROOT_DIR = path.join(__dirname, '..', '..');
const TEST_CACHE_DIR = path.join(ROOT_DIR, '.test-cache');

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
// LRU CACHE TESTS
// =============================================================================

function runLRUCacheTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 1: LRU Cache${colors.reset}                                  ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  test('LRUCache instantiates correctly', () => {
    const cache = new LRUCache(10);
    return cache.maxSize === 10 && cache.size() === 0;
  });

  test('LRUCache set and get work', () => {
    const cache = new LRUCache(10);
    cache.set('key1', 'value1');
    const entry = cache.get('key1');
    return entry && entry.value === 'value1';
  });

  test('LRUCache respects maxSize', () => {
    const cache = new LRUCache(3);
    cache.set('a', 1);
    cache.set('b', 2);
    cache.set('c', 3);
    cache.set('d', 4); // Should evict 'a'
    return cache.size() === 3 && !cache.has('a') && cache.has('d');
  });

  test('LRUCache updates access order', () => {
    const cache = new LRUCache(3);
    cache.set('a', 1);
    cache.set('b', 2);
    cache.set('c', 3);
    cache.get('a'); // Access 'a', making it most recent
    cache.set('d', 4); // Should evict 'b' (least recently used)
    return cache.has('a') && !cache.has('b');
  });

  test('LRUCache TTL expiration works', () => {
    const cache = new LRUCache(10);
    cache.set('expire', 'soon', 1); // 1ms TTL
    const before = cache.has('expire');
    // Wait for expiration
    const start = Date.now();
    while (Date.now() - start < 10) {} // Busy wait
    const after = cache.has('expire');
    return before === true && after === false;
  });

  test('LRUCache tracks hits and misses', () => {
    const cache = new LRUCache(10);
    cache.set('key', 'value');
    cache.get('key'); // Hit
    cache.get('key'); // Hit
    cache.get('missing'); // Miss
    const stats = cache.getStats();
    return stats.hits === 2 && stats.misses === 1;
  });

  test('LRUCache prune removes expired entries', () => {
    const cache = new LRUCache(10);
    cache.set('keep', 'value', 10000);
    cache.set('expire1', 'value', 1);
    cache.set('expire2', 'value', 1);
    // Wait for expiration
    const start = Date.now();
    while (Date.now() - start < 10) {}
    const pruned = cache.prune();
    return pruned === 2 && cache.size() === 1;
  });

  test('LRUCache clear works', () => {
    const cache = new LRUCache(10);
    cache.set('a', 1);
    cache.set('b', 2);
    cache.clear();
    return cache.size() === 0;
  });
}

// =============================================================================
// CACHE MANAGER TESTS
// =============================================================================

function runCacheManagerTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 2: Cache Manager${colors.reset}                              ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  // Reset singleton before tests
  resetCacheManager();

  test('CacheManager instantiates correctly', () => {
    const cache = new CacheManager({ name: 'test' });
    cache.destroy();
    return cache.name === 'test';
  });

  test('CacheManager.generateKey creates consistent keys', () => {
    const key1 = CacheManager.generateKey('prefix', 'arg1', { foo: 'bar' });
    const key2 = CacheManager.generateKey('prefix', 'arg1', { foo: 'bar' });
    const key3 = CacheManager.generateKey('prefix', 'arg2', { foo: 'bar' });
    return key1 === key2 && key1 !== key3 && key1.startsWith('prefix:');
  });

  test('CacheManager get/set work', () => {
    const cache = new CacheManager({ name: 'test', useFileCache: false });
    cache.set('key', 'value');
    const result = cache.get('key');
    cache.destroy();
    return result === 'value';
  });

  test('CacheManager has method works', () => {
    const cache = new CacheManager({ name: 'test', useFileCache: false });
    cache.set('exists', true);
    const has = cache.has('exists');
    const notHas = cache.has('missing');
    cache.destroy();
    return has === true && notHas === false;
  });

  test('CacheManager delete works', () => {
    const cache = new CacheManager({ name: 'test', useFileCache: false });
    cache.set('key', 'value');
    cache.delete('key');
    cache.destroy();
    return cache.has('key') === false;
  });

  test('CacheManager getStats returns correct structure', () => {
    const cache = new CacheManager({ name: 'test', useFileCache: false });
    cache.set('key', 'value');
    const stats = cache.getStats();
    cache.destroy();
    return stats.name === 'test' && stats.memory !== undefined;
  });

  test('getCacheManager returns singleton', () => {
    resetCacheManager();
    const cache1 = getCacheManager();
    const cache2 = getCacheManager();
    resetCacheManager();
    return cache1 === cache2;
  });
}

// =============================================================================
// SPECIALIZED CACHE TESTS
// =============================================================================

function runSpecializedCacheTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 3: Specialized Caches${colors.reset}                         ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  test('ComponentCache instantiates correctly', () => {
    const cache = new ComponentCache();
    cache.destroy();
    return cache.name === 'component-cache';
  });

  test('ComponentCache getComponentKey generates key', () => {
    const cache = new ComponentCache();
    const key = cache.getComponentKey('btn-123', 'react', { variant: 'primary' });
    cache.destroy();
    return key.includes('component:');
  });

  test('ComponentCache get/set component work', () => {
    const cache = new ComponentCache();
    cache.setComponent('btn-123', 'react', '<Button />', {});
    const code = cache.getComponent('btn-123', 'react', {});
    cache.destroy();
    return code === '<Button />';
  });

  test('TokenCache instantiates correctly', () => {
    const cache = new TokenCache();
    cache.destroy();
    return cache.name === 'token-cache';
  });

  test('TokenCache get/set token work', () => {
    const cache = new TokenCache();
    cache.setToken('colors.primary', '#3b82f6', 'css');
    const value = cache.getToken('colors.primary', 'css');
    cache.destroy();
    return value === '#3b82f6';
  });

  test('FigmaCache instantiates correctly', () => {
    const cache = new FigmaCache();
    cache.destroy();
    return cache.name === 'figma-cache';
  });

  test('FigmaCache get/set node work', () => {
    const cache = new FigmaCache();
    cache.setNode('abc123', '1:2', { name: 'Button' });
    const data = cache.getNode('abc123', '1:2');
    cache.destroy();
    return data && data.name === 'Button';
  });
}

// =============================================================================
// ASYNC UTILITIES TESTS
// =============================================================================

async function runAsyncUtilitiesTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 4: Async Utilities${colors.reset}                            ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  await testAsync('sleep delays execution', async () => {
    const start = Date.now();
    await sleep(50);
    const elapsed = Date.now() - start;
    return elapsed >= 45; // Allow some tolerance
  });

  await testAsync('createDeferred creates resolvable promise', async () => {
    const deferred = createDeferred();
    setTimeout(() => deferred.resolve('done'), 10);
    const result = await deferred.promise;
    return result === 'done';
  });

  await testAsync('withTimeout resolves before timeout', async () => {
    const result = await withTimeout(
      Promise.resolve('success'),
      1000
    );
    return result === 'success';
  });

  await testAsync('withTimeout rejects on timeout', async () => {
    try {
      await withTimeout(
        new Promise(() => {}), // Never resolves
        50,
        'Custom timeout'
      );
      return false;
    } catch (error) {
      return error.message === 'Custom timeout';
    }
  });

  await testAsync('retry succeeds on first attempt', async () => {
    let attempts = 0;
    const result = await retry(async () => {
      attempts++;
      return 'success';
    });
    return result === 'success' && attempts === 1;
  });

  await testAsync('retry retries on failure', async () => {
    let attempts = 0;
    const result = await retry(async () => {
      attempts++;
      if (attempts < 3) throw new Error('fail');
      return 'success';
    }, { maxAttempts: 5, baseDelay: 10 });
    return result === 'success' && attempts === 3;
  });

  await testAsync('retry throws after max attempts', async () => {
    let attempts = 0;
    try {
      await retry(async () => {
        attempts++;
        throw new Error('always fails');
      }, { maxAttempts: 3, baseDelay: 10 });
      return false;
    } catch (error) {
      return attempts === 3 && error.message === 'always fails';
    }
  });
}

// =============================================================================
// RATE LIMITER TESTS
// =============================================================================

async function runRateLimiterTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 5: Rate Limiter${colors.reset}                               ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  test('RateLimiter instantiates correctly', () => {
    const limiter = new RateLimiter({ tokensPerInterval: 5, interval: 1000 });
    return limiter.tokens === 5;
  });

  await testAsync('RateLimiter allows requests within limit', async () => {
    const limiter = new RateLimiter({ tokensPerInterval: 10, interval: 1000 });
    const start = Date.now();

    // Should complete quickly
    for (let i = 0; i < 5; i++) {
      await limiter.acquire();
    }

    const elapsed = Date.now() - start;
    return elapsed < 100; // Should be fast
  });

  test('RateLimiter getStats returns correct structure', () => {
    const limiter = new RateLimiter({ tokensPerInterval: 10, interval: 1000 });
    const stats = limiter.getStats();
    return stats.tokens === 10 && stats.maxTokens === 10 && stats.queueLength === 0;
  });
}

// =============================================================================
// BATCH PROCESSOR TESTS
// =============================================================================

async function runBatchProcessorTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 6: Batch Processor${colors.reset}                            ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  await testAsync('BatchProcessor processes all items', async () => {
    const processor = new BatchProcessor({ concurrency: 3 });
    const items = [1, 2, 3, 4, 5];

    const result = await processor.process(items, async (item) => item * 2);

    return result.summary.completed === 5 &&
           result.summary.failed === 0 &&
           result.results.length === 5;
  });

  await testAsync('BatchProcessor handles errors', async () => {
    const processor = new BatchProcessor({ concurrency: 2 });
    const items = [1, 2, 3];

    const result = await processor.process(items, async (item) => {
      if (item === 2) throw new Error('fail');
      return item;
    });

    return result.summary.completed === 2 &&
           result.summary.failed === 1 &&
           result.errors.length === 1;
  });

  await testAsync('BatchProcessor emits progress events', async () => {
    const processor = new BatchProcessor({ concurrency: 1 });
    const items = [1, 2, 3];
    let progressCount = 0;

    processor.on('progress', () => progressCount++);

    await processor.process(items, async (item) => item);

    return progressCount === 3;
  });

  await testAsync('BatchProcessor can be cancelled', async () => {
    const processor = new BatchProcessor({ concurrency: 1 });
    const items = [1, 2, 3, 4, 5];

    processor.on('progress', ({ completed }) => {
      if (completed >= 2) processor.cancel();
    });

    const result = await processor.process(items, async (item) => {
      await sleep(10);
      return item;
    });

    return result.summary.cancelled === true && result.summary.completed < 5;
  });
}

// =============================================================================
// ASYNC QUEUE TESTS
// =============================================================================

async function runAsyncQueueTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 7: Async Queue${colors.reset}                                ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  await testAsync('AsyncQueue processes tasks in order', async () => {
    const queue = new AsyncQueue({ concurrency: 1 });
    const order = [];

    queue.push(async () => { order.push(1); return 1; });
    queue.push(async () => { order.push(2); return 2; });
    const result = await queue.push(async () => { order.push(3); return 3; });

    // Wait for all to complete
    await sleep(50);

    return result === 3 && order.join(',') === '1,2,3';
  });

  await testAsync('AsyncQueue respects priority', async () => {
    const queue = new AsyncQueue({ concurrency: 1 });
    queue.pause(); // Pause to add all items first

    const order = [];

    queue.push(async () => { order.push('low'); }, 0);
    queue.push(async () => { order.push('high'); }, 10);
    queue.push(async () => { order.push('medium'); }, 5);

    queue.resume();
    await sleep(100);

    return order[0] === 'high' && order[1] === 'medium' && order[2] === 'low';
  });

  test('AsyncQueue getStats returns correct structure', () => {
    const queue = new AsyncQueue({ concurrency: 2 });
    const stats = queue.getStats();
    return stats.queued === 0 && stats.active === 0 && stats.processed === 0;
  });
}

// =============================================================================
// PIPELINE TESTS
// =============================================================================

async function runPipelineTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 8: Pipeline${colors.reset}                                   ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  await testAsync('Pipeline executes stages in order', async () => {
    const pipeline = new Pipeline('test');

    pipeline
      .addStage('stage1', async (input) => input + 1)
      .addStage('stage2', async (input) => input * 2)
      .addStage('stage3', async (input) => input - 3);

    const result = await pipeline.execute(5);

    // (5 + 1) * 2 - 3 = 9
    return result === 9;
  });

  await testAsync('Pipeline handles stage errors', async () => {
    const pipeline = new Pipeline('test');

    pipeline
      .addStage('stage1', async (input) => input + 1)
      .addStage('stage2', async () => { throw new Error('fail'); })
      .on('error', () => {}); // Prevent unhandled error event

    try {
      await pipeline.execute(5);
      return false;
    } catch (error) {
      return error.message === 'fail';
    }
  });

  await testAsync('Pipeline error handler provides recovery', async () => {
    const pipeline = new Pipeline('test');

    pipeline
      .addStage('stage1', async () => { throw new Error('fail'); })
      .addStage('stage2', async (input) => input + 1)
      .onError(async (error, stage) => {
        if (stage.name === 'stage1') return 10; // Recovery value
        return undefined;
      });

    const result = await pipeline.execute(5);

    return result === 11; // 10 + 1
  });

  await testAsync('Pipeline emits events', async () => {
    const pipeline = new Pipeline('test');
    let started = false;
    let completed = false;

    pipeline
      .addStage('stage1', async (input) => input)
      .on('start', () => { started = true; })
      .on('complete', () => { completed = true; });

    await pipeline.execute(5);

    return started && completed;
  });
}

// =============================================================================
// PARALLEL HELPERS TESTS
// =============================================================================

async function runParallelHelpersTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 9: Parallel Helpers${colors.reset}                           ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  await testAsync('parallel executes all functions', async () => {
    const results = await parallel([
      async () => 1,
      async () => 2,
      async () => 3
    ], 2);

    return results.length === 3 && results.includes(1) && results.includes(2) && results.includes(3);
  });

  await testAsync('mapAsync maps items correctly', async () => {
    const result = await mapAsync([1, 2, 3], async (x) => x * 2, 2);

    return result.results.join(',') === '2,4,6';
  });

  await testAsync('filterAsync filters items correctly', async () => {
    const result = await filterAsync([1, 2, 3, 4], async (x) => x % 2 === 0, 2);

    return result.join(',') === '2,4';
  });

  await testAsync('reduceAsync reduces items correctly', async () => {
    const result = await reduceAsync([1, 2, 3, 4], async (acc, x) => acc + x, 0);

    return result === 10;
  });

  await testAsync('withFallback returns fallback on error', async () => {
    const result = await withFallback(
      async () => { throw new Error('fail'); },
      'fallback',
      100
    );

    return result === 'fallback';
  });

  await testAsync('withFallback returns result on success', async () => {
    const result = await withFallback(
      async () => 'success',
      'fallback',
      100
    );

    return result === 'success';
  });
}

// =============================================================================
// MAIN TEST RUNNER
// =============================================================================

async function runAllTests() {
  console.log(`${colors.bold}${colors.cyan}`);
  console.log('╔═══════════════════════════════════════════════════════════╗');
  console.log('║     PERFORMANCE OPTIMIZATION TEST SUITE                   ║');
  console.log('║              Phase 3: Sprints 153-164                     ║');
  console.log('╚═══════════════════════════════════════════════════════════╝');
  console.log(`${colors.reset}`);

  const startTime = Date.now();

  // Run all test suites
  runLRUCacheTests();
  runCacheManagerTests();
  runSpecializedCacheTests();
  await runAsyncUtilitiesTests();
  await runRateLimiterTests();
  await runBatchProcessorTests();
  await runAsyncQueueTests();
  await runPipelineTests();
  await runParallelHelpersTests();

  const duration = Date.now() - startTime;

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
    console.log(`  ${colors.green}${colors.bold}✓ All performance tests passed!${colors.reset}`);
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
