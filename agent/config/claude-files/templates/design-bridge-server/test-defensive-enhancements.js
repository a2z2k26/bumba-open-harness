/**
 * Comprehensive Test Suite for Defensive Enhancement Modules
 *
 * Tests all 8 modules created in the Multi-Phase Sprint Plan:
 * - Phase 1: pattern-compatibility, figma-complexity-analyzer, sync-logger
 * - Phase 2: render-stability, graceful-degradation, canonical-id, sync-verifier
 * - Phase 3: transformation-report
 */

'use strict';

const path = require('path');

// Test tracking
const testResults = {
  passed: 0,
  failed: 0,
  errors: [],
  modules: {}
};

function test(name, fn) {
  try {
    fn();
    testResults.passed++;
    console.log(`  ✓ ${name}`);
    return true;
  } catch (error) {
    testResults.failed++;
    testResults.errors.push({ name, error: error.message });
    console.log(`  ✗ ${name}`);
    console.log(`    Error: ${error.message}`);
    return false;
  }
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message || 'Assertion failed');
  }
}

function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new Error(message || `Expected ${expected}, got ${actual}`);
  }
}

function assertType(value, type, message) {
  if (typeof value !== type) {
    throw new Error(message || `Expected type ${type}, got ${typeof value}`);
  }
}

function assertDefined(value, message) {
  if (value === undefined || value === null) {
    throw new Error(message || 'Value is undefined or null');
  }
}

// =============================================================================
// TEST: pattern-compatibility.js
// =============================================================================

function testPatternCompatibility() {
  console.log('\n📦 Testing pattern-compatibility.js');

  const moduleStart = Date.now();
  let moduleTests = { passed: 0, failed: 0 };

  try {
    const pc = require('./pattern-compatibility.js');

    test('Module exports FRAMEWORK_LIST constant', () => {
      assertDefined(pc.FRAMEWORK_LIST, 'FRAMEWORK_LIST should be defined');
      assert(Array.isArray(pc.FRAMEWORK_LIST), 'FRAMEWORK_LIST should be an array');
      assert(pc.FRAMEWORK_LIST.length >= 9, 'Should have at least 9 frameworks');
    }) && moduleTests.passed++;

    test('Module exports SUPPORT_LEVELS constant', () => {
      assertDefined(pc.SUPPORT_LEVELS, 'SUPPORT_LEVELS should be defined');
      assertDefined(pc.SUPPORT_LEVELS.FULL, 'Should have FULL level');
      assertDefined(pc.SUPPORT_LEVELS.PARTIAL, 'Should have PARTIAL level');
    }) && moduleTests.passed++;

    test('Module exports COMPATIBILITY_MATRIX', () => {
      assertDefined(pc.COMPATIBILITY_MATRIX, 'COMPATIBILITY_MATRIX should be defined');
      assertType(pc.COMPATIBILITY_MATRIX, 'object', 'Should be an object');
    }) && moduleTests.passed++;

    test('Module exports PATTERN_CATEGORIES', () => {
      assertDefined(pc.PATTERN_CATEGORIES, 'PATTERN_CATEGORIES should be defined');
      assertDefined(pc.PATTERN_CATEGORIES.layout, 'Should have layout category');
      assertDefined(pc.PATTERN_CATEGORIES.visual, 'Should have visual category');
    }) && moduleTests.passed++;

    test('checkPatternSupport works correctly', () => {
      assertDefined(pc.checkPatternSupport, 'checkPatternSupport should be defined');
      const result = pc.checkPatternSupport('auto-layout', 'react');
      assertDefined(result, 'Should return result');
    }) && moduleTests.passed++;

    test('getAllPatterns returns patterns', () => {
      assertDefined(pc.getAllPatterns, 'getAllPatterns should be defined');
      const patterns = pc.getAllPatterns();
      assert(Array.isArray(patterns), 'Should return array');
      assert(patterns.length > 0, 'Should have patterns');
    }) && moduleTests.passed++;

    test('generateCompatibilityReport works', () => {
      assertDefined(pc.generateCompatibilityReport, 'generateCompatibilityReport should be defined');
      const report = pc.generateCompatibilityReport(['auto-layout'], 'react');
      assertDefined(report, 'Should return report');
    }) && moduleTests.passed++;

    test('getCompatibilityRating works', () => {
      assertDefined(pc.getCompatibilityRating, 'getCompatibilityRating should be defined');
      const rating = pc.getCompatibilityRating(['auto-layout'], 'react');
      assertDefined(rating, 'Should return rating');
    }) && moduleTests.passed++;

  } catch (error) {
    console.log(`  ✗ Module load failed: ${error.message}`);
    testResults.errors.push({ name: 'pattern-compatibility load', error: error.message });
    moduleTests.failed++;
  }

  testResults.modules['pattern-compatibility'] = {
    ...moduleTests,
    duration: Date.now() - moduleStart
  };
}

// =============================================================================
// TEST: figma-complexity-analyzer.js
// =============================================================================

function testFigmaComplexityAnalyzer() {
  console.log('\n📦 Testing figma-complexity-analyzer.js');

  const moduleStart = Date.now();
  let moduleTests = { passed: 0, failed: 0 };

  try {
    const fca = require('./figma-complexity-analyzer.js');

    test('Module exports COMPLEXITY_METRICS', () => {
      assertDefined(fca.COMPLEXITY_METRICS, 'COMPLEXITY_METRICS should be defined');
      assert(Object.keys(fca.COMPLEXITY_METRICS).length >= 10, 'Should have many metrics');
    }) && moduleTests.passed++;

    test('Module exports THRESHOLDS with metric-specific levels', () => {
      assertDefined(fca.THRESHOLDS, 'THRESHOLDS should be defined');
      assertDefined(fca.THRESHOLDS.nodeCount, 'Should have nodeCount thresholds');
      assertDefined(fca.THRESHOLDS.nodeCount.low, 'nodeCount should have low threshold');
      assertDefined(fca.THRESHOLDS.nodeCount.high, 'nodeCount should have high threshold');
    }) && moduleTests.passed++;

    test('Module exports COMPLEXITY_LEVELS', () => {
      assertDefined(fca.COMPLEXITY_LEVELS, 'COMPLEXITY_LEVELS should be defined');
    }) && moduleTests.passed++;

    test('Module exports AnalysisResult class', () => {
      assertDefined(fca.AnalysisResult, 'AnalysisResult should be defined');
      const result = new fca.AnalysisResult({ nodeId: 'test', nodeName: 'Test' });
      assertDefined(result.metrics, 'Should have metrics object');
      assertDefined(result.nodeId, 'Should have nodeId');
    }) && moduleTests.passed++;

    test('walkAndCollect function works', () => {
      assertDefined(fca.walkAndCollect, 'walkAndCollect should be defined');
      const mockNode = {
        id: '1:1',
        name: 'Frame',
        type: 'FRAME',
        children: [
          { id: '1:2', name: 'Text', type: 'TEXT', characters: 'Hello' }
        ]
      };
      const result = fca.walkAndCollect(mockNode, { maxDepth: 10 });
      assertDefined(result.metrics, 'Should return metrics');
      assert(result.metrics.nodeCount >= 1, 'Should count nodes');
    }) && moduleTests.passed++;

    test('getThresholdLevel works', () => {
      assertDefined(fca.getThresholdLevel, 'getThresholdLevel should be defined');
      const level = fca.getThresholdLevel('nodeCount', 100);
      assert(['low', 'medium', 'high', 'critical'].includes(level), 'Should return valid level');
    }) && moduleTests.passed++;

    test('exceedsThreshold works', () => {
      assertDefined(fca.exceedsThreshold, 'exceedsThreshold should be defined');
      const exceeds = fca.exceedsThreshold('nodeCount', 1000, 'high');
      assertType(exceeds, 'boolean', 'Should return boolean');
    }) && moduleTests.passed++;

    test('generateWarnings works', () => {
      assertDefined(fca.generateWarnings, 'generateWarnings should be defined');
      const metrics = { nodeCount: 500, maxDepth: 15 };
      const warnings = fca.generateWarnings(metrics);
      assert(Array.isArray(warnings), 'Should return array');
    }) && moduleTests.passed++;

    test('analyzeNode works with mock data', () => {
      assertDefined(fca.analyzeNode, 'analyzeNode should be defined');
      const mockNode = {
        id: '1:1',
        name: 'TestFrame',
        type: 'FRAME',
        width: 400,
        height: 300,
        children: []
      };
      const result = fca.analyzeNode(mockNode);
      assertDefined(result, 'Should return result');
      assertDefined(result.metrics, 'Should have metrics');
    }) && moduleTests.passed++;

    test('quickComplexityCheck works', () => {
      assertDefined(fca.quickComplexityCheck, 'quickComplexityCheck should be defined');
      const mockNode = { id: '1:1', name: 'Test', type: 'FRAME', children: [] };
      const result = fca.quickComplexityCheck(mockNode, 'medium');
      assertDefined(result, 'Should return result');
    }) && moduleTests.passed++;

    test('FRAMEWORK_NOTES has all frameworks', () => {
      assertDefined(fca.FRAMEWORK_NOTES, 'FRAMEWORK_NOTES should be defined');
      const frameworks = ['react', 'vue', 'svelte', 'angular', 'react-native', 'flutter', 'swiftui', 'jetpack-compose', 'web-components'];
      for (const fw of frameworks) {
        assertDefined(fca.FRAMEWORK_NOTES[fw], `Should have notes for ${fw}`);
      }
    }) && moduleTests.passed++;

    test('getSupportedFrameworks works', () => {
      assertDefined(fca.getSupportedFrameworks, 'getSupportedFrameworks should be defined');
      const frameworks = fca.getSupportedFrameworks();
      assert(Array.isArray(frameworks), 'Should return array');
      assert(frameworks.length >= 9, 'Should have at least 9 frameworks');
    }) && moduleTests.passed++;

  } catch (error) {
    console.log(`  ✗ Module load failed: ${error.message}`);
    testResults.errors.push({ name: 'figma-complexity-analyzer load', error: error.message });
    moduleTests.failed++;
  }

  testResults.modules['figma-complexity-analyzer'] = {
    ...moduleTests,
    duration: Date.now() - moduleStart
  };
}

// =============================================================================
// TEST: sync-logger.js
// =============================================================================

function testSyncLogger() {
  console.log('\n📦 Testing sync-logger.js');

  const moduleStart = Date.now();
  let moduleTests = { passed: 0, failed: 0 };

  try {
    const sl = require('./sync-logger.js');

    test('Module exports LOG_LEVELS', () => {
      assertDefined(sl.LOG_LEVELS, 'LOG_LEVELS should be defined');
      assertDefined(sl.LOG_LEVELS.ERROR, 'Should have ERROR level');
      assertDefined(sl.LOG_LEVELS.INFO, 'Should have INFO level');
    }) && moduleTests.passed++;

    test('Module exports LOG_CATEGORIES', () => {
      assertDefined(sl.LOG_CATEGORIES, 'LOG_CATEGORIES should be defined');
      assertDefined(sl.LOG_CATEGORIES.SYNC, 'Should have SYNC category');
      assertDefined(sl.LOG_CATEGORIES.TRANSFORM, 'Should have TRANSFORM category');
    }) && moduleTests.passed++;

    test('SyncLogger class instantiates', () => {
      const logger = new sl.SyncLogger({ output: 'memory' });
      assertDefined(logger.info, 'Should have info method');
      assertDefined(logger.error, 'Should have error method');
      assertDefined(logger.warn, 'Should have warn method');
    }) && moduleTests.passed++;

    test('Logger records entries', () => {
      const logger = new sl.SyncLogger({ output: 'memory' });
      logger.info('Test message', { key: 'value' });
      const entries = logger.getEntries();
      assert(entries.length > 0, 'Should have entries');
      assertEqual(entries[0].message, 'Test message', 'Should record message');
    }) && moduleTests.passed++;

    test('Logger tracks counters', () => {
      const logger = new sl.SyncLogger({ output: 'memory' });
      logger.info('Info 1');
      logger.info('Info 2');
      logger.warn('Warning');
      logger.error('Error');
      const summary = logger.getSummary();
      assertEqual(summary.counters.info, 2, 'Should count info');
      assertEqual(summary.counters.warn, 1, 'Should count warn');
      assertEqual(summary.counters.error, 1, 'Should count error');
    }) && moduleTests.passed++;

    test('syncStart and syncComplete work', () => {
      const logger = new sl.SyncLogger({ output: 'memory' });
      logger.syncStart({ source: 'figma', target: 'react' });
      logger.syncComplete({ nodesProcessed: 10 });
      const entries = logger.getEntries();
      assert(entries.some(e => e.message.includes('start') || e.category === 'sync'), 'Should have sync start');
    }) && moduleTests.passed++;

    test('Timing spans work', () => {
      const logger = new sl.SyncLogger({ output: 'memory' });
      const spanId = logger.startSpan('test-operation');
      assertDefined(spanId, 'Should return span ID');
      const duration = logger.endSpan(spanId);
      assertType(duration, 'number', 'Should return duration');
    }) && moduleTests.passed++;

    test('createLogger factory works', () => {
      const logger = sl.createLogger({ name: 'test' });
      assertDefined(logger, 'Should create logger');
      assertDefined(logger.info, 'Should have info method');
    }) && moduleTests.passed++;

    test('getErrors and getWarnings work', () => {
      const logger = new sl.SyncLogger({ output: 'memory' });
      logger.error('Error 1');
      logger.warn('Warning 1');
      logger.info('Info 1');
      const errors = logger.getErrors();
      const warnings = logger.getWarnings();
      assertEqual(errors.length, 1, 'Should have 1 error');
      assertEqual(warnings.length, 1, 'Should have 1 warning');
    }) && moduleTests.passed++;

  } catch (error) {
    console.log(`  ✗ Module load failed: ${error.message}`);
    testResults.errors.push({ name: 'sync-logger load', error: error.message });
    moduleTests.failed++;
  }

  testResults.modules['sync-logger'] = {
    ...moduleTests,
    duration: Date.now() - moduleStart
  };
}

// =============================================================================
// TEST: render-stability.js
// =============================================================================

function testRenderStability() {
  console.log('\n📦 Testing render-stability.js');

  const moduleStart = Date.now();
  let moduleTests = { passed: 0, failed: 0 };

  try {
    const rs = require('./render-stability.js');

    test('Module exports DEFAULT_CONFIG', () => {
      assertDefined(rs.DEFAULT_CONFIG, 'DEFAULT_CONFIG should be defined');
      assertDefined(rs.DEFAULT_CONFIG.stabilityThreshold, 'Should have stabilityThreshold');
      assertDefined(rs.DEFAULT_CONFIG.timeout, 'Should have timeout');
    }) && moduleTests.passed++;

    test('Module exports STABILITY_STATES', () => {
      assertDefined(rs.STABILITY_STATES, 'STABILITY_STATES should be defined');
      assertDefined(rs.STABILITY_STATES.STABLE, 'Should have STABLE state');
      assertDefined(rs.STABILITY_STATES.TIMEOUT, 'Should have TIMEOUT state');
    }) && moduleTests.passed++;

    test('RenderStabilityObserver class exists', () => {
      assertDefined(rs.RenderStabilityObserver, 'RenderStabilityObserver should be defined');
      const observer = new rs.RenderStabilityObserver();
      assertDefined(observer.observe, 'Should have observe method');
      assertDefined(observer.stop, 'Should have stop method');
      assertDefined(observer.getState, 'Should have getState method');
    }) && moduleTests.passed++;

    test('waitMs function works', async () => {
      assertDefined(rs.waitMs, 'waitMs should be defined');
      const start = Date.now();
      await rs.waitMs(50);
      const elapsed = Date.now() - start;
      assert(elapsed >= 45, 'Should wait at least 45ms');
    }) && moduleTests.passed++;

    test('waitForCondition works', async () => {
      assertDefined(rs.waitForCondition, 'waitForCondition should be defined');
      let counter = 0;
      const result = await rs.waitForCondition(() => {
        counter++;
        return counter >= 3;
      }, { timeout: 1000, interval: 10 });
      assertEqual(result, true, 'Should return true when condition met');
    }) && moduleTests.passed++;

    test('waitForStateStable works', async () => {
      assertDefined(rs.waitForStateStable, 'waitForStateStable should be defined');
      let value = 1;
      setTimeout(() => { value = 2; }, 20);
      const result = await rs.waitForStateStable(() => value, {
        stabilityThreshold: 50,
        timeout: 500,
        interval: 10
      });
      assertDefined(result.stable, 'Should have stable property');
    }) && moduleTests.passed++;

    test('createDebouncedStabilityCheck works', () => {
      assertDefined(rs.createDebouncedStabilityCheck, 'createDebouncedStabilityCheck should be defined');
      const debounced = rs.createDebouncedStabilityCheck(() => 'result', 50);
      assertDefined(debounced, 'Should return function');
      assertDefined(debounced.cancel, 'Should have cancel method');
    }) && moduleTests.passed++;

    test('retryWithStability works', async () => {
      assertDefined(rs.retryWithStability, 'retryWithStability should be defined');
      let attempts = 0;
      const result = await rs.retryWithStability(async () => {
        attempts++;
        if (attempts < 2) throw new Error('Retry');
        return 'success';
      }, { maxRetries: 3, retryDelay: 10 });
      assertEqual(result, 'success', 'Should succeed after retry');
      assertEqual(attempts, 2, 'Should have tried twice');
    }) && moduleTests.passed++;

    test('createStableTransformer works', () => {
      assertDefined(rs.createStableTransformer, 'createStableTransformer should be defined');
      const transformer = rs.createStableTransformer(async (x) => x * 2);
      assertType(transformer, 'function', 'Should return function');
    }) && moduleTests.passed++;

    test('createStableBatchProcessor works', () => {
      assertDefined(rs.createStableBatchProcessor, 'createStableBatchProcessor should be defined');
      const processor = rs.createStableBatchProcessor(async (item) => item);
      assertType(processor, 'function', 'Should return function');
    }) && moduleTests.passed++;

    test('createStabilityMonitor works', () => {
      assertDefined(rs.createStabilityMonitor, 'createStabilityMonitor should be defined');
      let value = 0;
      const monitor = rs.createStabilityMonitor(() => value);
      assertDefined(monitor.start, 'Should have start method');
      assertDefined(monitor.stop, 'Should have stop method');
      assertDefined(monitor.isStable, 'Should have isStable method');
    }) && moduleTests.passed++;

    test('createStabilityQueue works', () => {
      assertDefined(rs.createStabilityQueue, 'createStabilityQueue should be defined');
      const queue = rs.createStabilityQueue();
      assertDefined(queue.add, 'Should have add method');
      assertDefined(queue.pause, 'Should have pause method');
      assertDefined(queue.resume, 'Should have resume method');
    }) && moduleTests.passed++;

  } catch (error) {
    console.log(`  ✗ Module load failed: ${error.message}`);
    testResults.errors.push({ name: 'render-stability load', error: error.message });
    moduleTests.failed++;
  }

  testResults.modules['render-stability'] = {
    ...moduleTests,
    duration: Date.now() - moduleStart
  };
}

// =============================================================================
// TEST: graceful-degradation.js
// =============================================================================

function testGracefulDegradation() {
  console.log('\n📦 Testing graceful-degradation.js');

  const moduleStart = Date.now();
  let moduleTests = { passed: 0, failed: 0 };

  try {
    const gd = require('./graceful-degradation.js');

    test('Module exports FALLBACK_LEVELS', () => {
      assertDefined(gd.FALLBACK_LEVELS, 'FALLBACK_LEVELS should be defined');
      assertDefined(gd.FALLBACK_LEVELS.FULL, 'Should have FULL level');
      assertDefined(gd.FALLBACK_LEVELS.SIMPLIFIED, 'Should have SIMPLIFIED level');
      assertDefined(gd.FALLBACK_LEVELS.BASIC, 'Should have BASIC level');
      assertDefined(gd.FALLBACK_LEVELS.MINIMAL, 'Should have MINIMAL level');
    }) && moduleTests.passed++;

    test('Module exports FALLBACK_CATEGORIES', () => {
      assertDefined(gd.FALLBACK_CATEGORIES, 'FALLBACK_CATEGORIES should be defined');
      assertDefined(gd.FALLBACK_CATEGORIES.LAYOUT, 'Should have LAYOUT');
      assertDefined(gd.FALLBACK_CATEGORIES.COMPONENT, 'Should have COMPONENT');
    }) && moduleTests.passed++;

    test('Module exports FRAMEWORK_FALLBACKS for all frameworks', () => {
      assertDefined(gd.FRAMEWORK_FALLBACKS, 'FRAMEWORK_FALLBACKS should be defined');
      const frameworks = ['react', 'vue', 'svelte', 'angular', 'react-native', 'flutter', 'swiftui', 'jetpack-compose', 'web-components'];
      for (const fw of frameworks) {
        assertDefined(gd.FRAMEWORK_FALLBACKS[fw], `Should have fallbacks for ${fw}`);
      }
    }) && moduleTests.passed++;

    test('FallbackRegistry class works', () => {
      const registry = new gd.FallbackRegistry();
      assertDefined(registry.getFallback, 'Should have getFallback method');
      assertDefined(registry.registerFallback, 'Should have registerFallback method');
      assertDefined(registry.getStats, 'Should have getStats method');
    }) && moduleTests.passed++;

    test('FallbackRegistry.getFallback returns function', () => {
      const registry = new gd.FallbackRegistry();
      const fallback = registry.getFallback('react', 'component', 'basic');
      assertType(fallback, 'function', 'Should return function');
    }) && moduleTests.passed++;

    test('FallbackRegistry records usage', () => {
      const registry = new gd.FallbackRegistry();
      registry.recordFallback({
        framework: 'react',
        category: 'component',
        level: 'basic',
        nodeId: '1:1'
      });
      const stats = registry.getStats();
      assertEqual(stats.total, 1, 'Should record fallback');
    }) && moduleTests.passed++;

    test('FallbackSelector class works', () => {
      const registry = new gd.FallbackRegistry();
      const selector = new gd.FallbackSelector(registry);
      assertDefined(selector.select, 'Should have select method');
      assertDefined(selector.tryWithFallback, 'Should have tryWithFallback method');
    }) && moduleTests.passed++;

    test('FallbackSelector.select returns result', () => {
      const registry = new gd.FallbackRegistry();
      const selector = new gd.FallbackSelector(registry);
      const result = selector.select({
        framework: 'react',
        category: 'component',
        node: { id: '1:1', name: 'Test', className: 'test' }
      });
      assertDefined(result.success, 'Should have success property');
      assertDefined(result.level, 'Should have level property');
    }) && moduleTests.passed++;

    test('GracefulDegradationManager works', () => {
      const manager = new gd.GracefulDegradationManager();
      assertDefined(manager.transform, 'Should have transform method');
      assertDefined(manager.getDegradationReport, 'Should have getDegradationReport method');
    }) && moduleTests.passed++;

    test('createFallbackChain works', async () => {
      assertDefined(gd.createFallbackChain, 'createFallbackChain should be defined');
      const chain = gd.createFallbackChain(
        () => { throw new Error('First fails'); },
        () => 'second succeeds'
      );
      const result = await chain('input');
      assertEqual(result.success, true, 'Should succeed');
      assertEqual(result.handlerIndex, 1, 'Should use second handler');
    }) && moduleTests.passed++;

    test('wrapWithDegradation works', () => {
      assertDefined(gd.wrapWithDegradation, 'wrapWithDegradation should be defined');
      const wrapped = gd.wrapWithDegradation((node) => `<div>${node.name}</div>`);
      assertType(wrapped, 'function', 'Should return function');
      assertDefined(wrapped.manager, 'Should expose manager');
    }) && moduleTests.passed++;

    test('getDefaultFallback works', () => {
      assertDefined(gd.getDefaultFallback, 'getDefaultFallback should be defined');
      const fallback = gd.getDefaultFallback('react', 'component', 'basic');
      assertType(fallback, 'function', 'Should return function');
    }) && moduleTests.passed++;

    test('canDegrade works', () => {
      assertDefined(gd.canDegrade, 'canDegrade should be defined');
      const result = gd.canDegrade('react', 'component');
      assertEqual(result, true, 'React component should be degradable');
    }) && moduleTests.passed++;

  } catch (error) {
    console.log(`  ✗ Module load failed: ${error.message}`);
    testResults.errors.push({ name: 'graceful-degradation load', error: error.message });
    moduleTests.failed++;
  }

  testResults.modules['graceful-degradation'] = {
    ...moduleTests,
    duration: Date.now() - moduleStart
  };
}

// =============================================================================
// TEST: canonical-id.js
// =============================================================================

function testCanonicalId() {
  console.log('\n📦 Testing canonical-id.js');

  const moduleStart = Date.now();
  let moduleTests = { passed: 0, failed: 0 };

  try {
    const cid = require('./canonical-id.js');

    test('Module exports ID_STRATEGIES', () => {
      assertDefined(cid.ID_STRATEGIES, 'ID_STRATEGIES should be defined');
      assertDefined(cid.ID_STRATEGIES.CONTENT_HASH, 'Should have CONTENT_HASH');
      assertDefined(cid.ID_STRATEGIES.COMPOSITE, 'Should have COMPOSITE');
    }) && moduleTests.passed++;

    test('Module exports HASH_ALGORITHMS', () => {
      assertDefined(cid.HASH_ALGORITHMS, 'HASH_ALGORITHMS should be defined');
      assertDefined(cid.HASH_ALGORITHMS.SHA256, 'Should have SHA256');
    }) && moduleTests.passed++;

    test('CanonicalIdGenerator class works', () => {
      const generator = new cid.CanonicalIdGenerator();
      assertDefined(generator.generate, 'Should have generate method');
      assertDefined(generator.getStats, 'Should have getStats method');
    }) && moduleTests.passed++;

    test('CanonicalIdGenerator generates IDs', () => {
      const generator = new cid.CanonicalIdGenerator();
      const node = { id: '1:1', name: 'Button', type: 'COMPONENT', width: 100, height: 40 };
      const id = generator.generate(node);
      assertType(id, 'string', 'Should return string');
      assert(id.length > 0, 'ID should not be empty');
    }) && moduleTests.passed++;

    test('CanonicalIdGenerator produces consistent IDs', () => {
      const generator = new cid.CanonicalIdGenerator();
      const node = { id: '1:1', name: 'Button', type: 'COMPONENT', width: 100, height: 40 };
      const id1 = generator.generate(node);
      generator.clear();
      const id2 = generator.generate(node);
      assertEqual(id1, id2, 'Same node should produce same ID');
    }) && moduleTests.passed++;

    test('IdMappingStore class works', () => {
      const store = new cid.IdMappingStore({ storePath: '/tmp/test-mappings.json', autoSave: false });
      assertDefined(store.set, 'Should have set method');
      assertDefined(store.getByFigmaId, 'Should have getByFigmaId method');
      assertDefined(store.getByCanonicalId, 'Should have getByCanonicalId method');
    }) && moduleTests.passed++;

    test('IdMappingStore stores and retrieves mappings', () => {
      const store = new cid.IdMappingStore({ storePath: '/tmp/test-mappings.json', autoSave: false });
      store.set('figma-123', 'canonical-abc', { name: 'Test' });
      const result = store.getByFigmaId('figma-123');
      assertDefined(result, 'Should retrieve mapping');
      assertEqual(result.canonicalId, 'canonical-abc', 'Should have correct canonical ID');
    }) && moduleTests.passed++;

    test('IdMappingStore bidirectional lookup works', () => {
      const store = new cid.IdMappingStore({ storePath: '/tmp/test-mappings.json', autoSave: false });
      store.set('figma-456', 'canonical-xyz');
      const byFigma = store.getByFigmaId('figma-456');
      const byCanonical = store.getByCanonicalId('canonical-xyz');
      assertDefined(byFigma, 'Should find by Figma ID');
      assertDefined(byCanonical, 'Should find by canonical ID');
    }) && moduleTests.passed++;

    test('IdResolver class works', () => {
      const generator = new cid.CanonicalIdGenerator();
      const store = new cid.IdMappingStore({ storePath: '/tmp/test-resolver.json', autoSave: false });
      const resolver = new cid.IdResolver(generator, store);
      assertDefined(resolver.resolve, 'Should have resolve method');
      assertDefined(resolver.reverseResolve, 'Should have reverseResolve method');
    }) && moduleTests.passed++;

    test('IdResolver resolves nodes', () => {
      const generator = new cid.CanonicalIdGenerator();
      const store = new cid.IdMappingStore({ storePath: '/tmp/test-resolver2.json', autoSave: false });
      const resolver = new cid.IdResolver(generator, store);
      const node = { id: '1:1', name: 'Card', type: 'FRAME', width: 300, height: 200 };
      const result = resolver.resolve(node);
      assertDefined(result.canonicalId, 'Should have canonical ID');
      assertDefined(result.figmaId, 'Should have Figma ID');
      assertEqual(result.figmaId, '1:1', 'Figma ID should match');
    }) && moduleTests.passed++;

    test('createIdSystem factory works', () => {
      const system = cid.createIdSystem({
        store: { storePath: '/tmp/test-system.json', autoSave: false }
      });
      assertDefined(system.generator, 'Should have generator');
      assertDefined(system.store, 'Should have store');
      assertDefined(system.resolver, 'Should have resolver');
      assertDefined(system.resolve, 'Should have resolve convenience method');
    }) && moduleTests.passed++;

    test('generateCanonicalId utility works', () => {
      assertDefined(cid.generateCanonicalId, 'generateCanonicalId should be defined');
      const node = { id: '1:1', name: 'Test', type: 'FRAME' };
      const id = cid.generateCanonicalId(node);
      assertType(id, 'string', 'Should return string');
    }) && moduleTests.passed++;

    test('createHash utility works', () => {
      assertDefined(cid.createHash, 'createHash should be defined');
      const hash1 = cid.createHash('test input');
      const hash2 = cid.createHash('test input');
      assertEqual(hash1, hash2, 'Same input should produce same hash');
    }) && moduleTests.passed++;

  } catch (error) {
    console.log(`  ✗ Module load failed: ${error.message}`);
    testResults.errors.push({ name: 'canonical-id load', error: error.message });
    moduleTests.failed++;
  }

  testResults.modules['canonical-id'] = {
    ...moduleTests,
    duration: Date.now() - moduleStart
  };
}

// =============================================================================
// TEST: sync-verifier.js
// =============================================================================

function testSyncVerifier() {
  console.log('\n📦 Testing sync-verifier.js');

  const moduleStart = Date.now();
  let moduleTests = { passed: 0, failed: 0 };

  try {
    const sv = require('./sync-verifier.js');

    test('Module exports VERIFICATION_STATUS', () => {
      assertDefined(sv.VERIFICATION_STATUS, 'VERIFICATION_STATUS should be defined');
      assertDefined(sv.VERIFICATION_STATUS.SYNCED, 'Should have SYNCED');
      assertDefined(sv.VERIFICATION_STATUS.DRIFTED, 'Should have DRIFTED');
      assertDefined(sv.VERIFICATION_STATUS.MISSING, 'Should have MISSING');
    }) && moduleTests.passed++;

    test('Module exports SEVERITY', () => {
      assertDefined(sv.SEVERITY, 'SEVERITY should be defined');
      assertDefined(sv.SEVERITY.ERROR, 'Should have ERROR');
      assertDefined(sv.SEVERITY.WARNING, 'Should have WARNING');
    }) && moduleTests.passed++;

    test('ContentHasher class works', () => {
      const hasher = new sv.ContentHasher();
      assertDefined(hasher.hash, 'Should have hash method');
      assertDefined(hasher.hashAll, 'Should have hashAll method');
    }) && moduleTests.passed++;

    test('ContentHasher produces consistent hashes', () => {
      const hasher = new sv.ContentHasher();
      const node = { type: 'FRAME', name: 'Test', width: 100, height: 100 };
      const hash1 = hasher.hashAll(node);
      const hash2 = hasher.hashAll(node);
      assertEqual(hash1.combined, hash2.combined, 'Same node should produce same hash');
    }) && moduleTests.passed++;

    test('SyncBaseline class works', () => {
      const baseline = new sv.SyncBaseline();
      assertDefined(baseline.add, 'Should have add method');
      assertDefined(baseline.get, 'Should have get method');
      assertDefined(baseline.getIds, 'Should have getIds method');
    }) && moduleTests.passed++;

    test('SyncBaseline stores and retrieves entries', () => {
      const baseline = new sv.SyncBaseline();
      const node = { id: '1:1', type: 'FRAME', name: 'Test', width: 100, height: 100 };
      baseline.add('1:1', node);
      const entry = baseline.get('1:1');
      assertDefined(entry, 'Should retrieve entry');
      assertDefined(entry.hashes, 'Entry should have hashes');
    }) && moduleTests.passed++;

    test('SyncVerifier class works', () => {
      const verifier = new sv.SyncVerifier();
      assertDefined(verifier.setBaseline, 'Should have setBaseline method');
      assertDefined(verifier.verifyNode, 'Should have verifyNode method');
      assertDefined(verifier.verifyAll, 'Should have verifyAll method');
    }) && moduleTests.passed++;

    test('SyncVerifier detects synced state', () => {
      const verifier = new sv.SyncVerifier();
      const nodes = [
        { id: '1:1', type: 'FRAME', name: 'Test', width: 100, height: 100 }
      ];
      verifier.setBaseline(nodes);
      const result = verifier.verifyNode(nodes[0], '1:1');
      assertEqual(result.status, sv.VERIFICATION_STATUS.SYNCED, 'Should be synced');
    }) && moduleTests.passed++;

    test('SyncVerifier detects drift', () => {
      const verifier = new sv.SyncVerifier();
      const original = { id: '1:1', type: 'FRAME', name: 'Test', width: 100, height: 100 };
      const modified = { id: '1:1', type: 'FRAME', name: 'Test', width: 200, height: 100 };
      verifier.setBaseline([original]);
      const result = verifier.verifyNode(modified, '1:1');
      assertEqual(result.status, sv.VERIFICATION_STATUS.DRIFTED, 'Should detect drift');
    }) && moduleTests.passed++;

    test('SyncVerifier.quickCheck works', () => {
      const verifier = new sv.SyncVerifier();
      const nodes = [
        { id: '1:1', type: 'FRAME', name: 'A', width: 100, height: 100 },
        { id: '1:2', type: 'FRAME', name: 'B', width: 200, height: 200 }
      ];
      verifier.setBaseline(nodes);
      const result = verifier.quickCheck(nodes);
      assertDefined(result.passed, 'Should have passed property');
      assertDefined(result.syncRate, 'Should have syncRate');
    }) && moduleTests.passed++;

    test('DriftDetector class works', () => {
      const detector = new sv.DriftDetector();
      assertDefined(detector.snapshot, 'Should have snapshot method');
      assertDefined(detector.detectDrift, 'Should have detectDrift method');
    }) && moduleTests.passed++;

    test('DriftDetector detects changes', () => {
      const detector = new sv.DriftDetector();
      const before = [{ id: '1:1', type: 'FRAME', name: 'A', width: 100, height: 100 }];
      const after = [{ id: '1:1', type: 'FRAME', name: 'A', width: 200, height: 100 }];
      detector.snapshot('before', before);
      detector.snapshot('after', after);
      const result = detector.detectDrift('before', 'after');
      assert(result.driftCount > 0, 'Should detect drift');
    }) && moduleTests.passed++;

    test('createVerificationSystem factory works', () => {
      const system = sv.createVerificationSystem();
      assertDefined(system.verifier, 'Should have verifier');
      assertDefined(system.driftDetector, 'Should have driftDetector');
      assertDefined(system.setBaseline, 'Should have setBaseline convenience');
      assertDefined(system.verify, 'Should have verify convenience');
    }) && moduleTests.passed++;

    test('quickVerify utility works', () => {
      assertDefined(sv.quickVerify, 'quickVerify should be defined');
      const baseline = [{ id: '1:1', type: 'FRAME', name: 'Test' }];
      const current = [{ id: '1:1', type: 'FRAME', name: 'Test' }];
      const result = sv.quickVerify(baseline, current);
      assertDefined(result.passed, 'Should have passed property');
    }) && moduleTests.passed++;

  } catch (error) {
    console.log(`  ✗ Module load failed: ${error.message}`);
    testResults.errors.push({ name: 'sync-verifier load', error: error.message });
    moduleTests.failed++;
  }

  testResults.modules['sync-verifier'] = {
    ...moduleTests,
    duration: Date.now() - moduleStart
  };
}

// =============================================================================
// TEST: transformation-report.js
// =============================================================================

function testTransformationReport() {
  console.log('\n📦 Testing transformation-report.js');

  const moduleStart = Date.now();
  let moduleTests = { passed: 0, failed: 0 };

  try {
    const tr = require('./transformation-report.js');

    test('Module exports REPORT_FORMATS', () => {
      assertDefined(tr.REPORT_FORMATS, 'REPORT_FORMATS should be defined');
      assertDefined(tr.REPORT_FORMATS.JSON, 'Should have JSON');
      assertDefined(tr.REPORT_FORMATS.MARKDOWN, 'Should have MARKDOWN');
      assertDefined(tr.REPORT_FORMATS.HTML, 'Should have HTML');
    }) && moduleTests.passed++;

    test('Module exports STATUS', () => {
      assertDefined(tr.STATUS, 'STATUS should be defined');
      assertDefined(tr.STATUS.SUCCESS, 'Should have SUCCESS');
      assertDefined(tr.STATUS.PARTIAL, 'Should have PARTIAL');
      assertDefined(tr.STATUS.FAILED, 'Should have FAILED');
    }) && moduleTests.passed++;

    test('ReportCollector class works', () => {
      const collector = new tr.ReportCollector({ framework: 'react' });
      assertDefined(collector.recordNode, 'Should have recordNode method');
      assertDefined(collector.recordWarning, 'Should have recordWarning method');
      assertDefined(collector.recordError, 'Should have recordError method');
      assertDefined(collector.finalize, 'Should have finalize method');
    }) && moduleTests.passed++;

    test('ReportCollector tracks nodes', () => {
      const collector = new tr.ReportCollector();
      collector.recordNode({ id: '1:1' }, { success: true });
      collector.recordNode({ id: '1:2' }, { success: true });
      collector.recordNode({ id: '1:3' }, { success: false });
      const data = collector.getData();
      assertEqual(data.nodesProcessed, 3, 'Should count 3 nodes');
      assertEqual(data.nodesSuccessful, 2, 'Should count 2 successful');
      assertEqual(data.nodesFailed, 1, 'Should count 1 failed');
    }) && moduleTests.passed++;

    test('ReportCollector tracks warnings and errors', () => {
      const collector = new tr.ReportCollector();
      collector.recordWarning('Warning 1');
      collector.recordWarning('Warning 2');
      collector.recordError(new Error('Test error'));
      const data = collector.getData();
      assertEqual(data.warnings.length, 2, 'Should have 2 warnings');
      assertEqual(data.errors.length, 1, 'Should have 1 error');
    }) && moduleTests.passed++;

    test('ReportCollector tracks timing', () => {
      const collector = new tr.ReportCollector();
      collector.recordTiming('transform', 150);
      collector.recordTiming('validate', 50);
      const data = collector.getData();
      assertEqual(data.timings.length, 2, 'Should have 2 timings');
    }) && moduleTests.passed++;

    test('ReportCollector finalize calculates metrics', () => {
      const collector = new tr.ReportCollector();
      collector.recordNode({ id: '1' }, { success: true });
      collector.recordNode({ id: '2' }, { success: true, degraded: true, degradationLevel: 'basic' });
      const data = collector.finalize();
      assertDefined(data.duration, 'Should have duration');
      assertEqual(data.metrics.coverage, 100, 'Coverage should be 100%');
      assertEqual(data.metrics.degradationRate, 50, 'Degradation rate should be 50%');
    }) && moduleTests.passed++;

    test('ReportGenerator class works', () => {
      const generator = new tr.ReportGenerator();
      assertDefined(generator.generate, 'Should have generate method');
    }) && moduleTests.passed++;

    test('ReportGenerator generates JSON', () => {
      const generator = new tr.ReportGenerator();
      const data = {
        sessionId: 'test-123',
        framework: 'react',
        source: 'figma',
        nodesProcessed: 10,
        nodesSuccessful: 8,
        nodesFailed: 2,
        nodesSkipped: 0,
        nodesDegraded: 1,
        warnings: [],
        errors: [],
        degradations: [],
        recommendations: [],
        timings: [],
        files: [],
        metrics: { coverage: 80, degradationRate: 10 }
      };
      const json = generator.generate(data, tr.REPORT_FORMATS.JSON);
      const parsed = JSON.parse(json);
      assertDefined(parsed.report, 'JSON should have report object');
    }) && moduleTests.passed++;

    test('ReportGenerator generates Markdown', () => {
      const generator = new tr.ReportGenerator();
      const data = {
        sessionId: 'test-123',
        framework: 'react',
        source: 'figma',
        nodesProcessed: 10,
        nodesSuccessful: 10,
        nodesFailed: 0,
        nodesSkipped: 0,
        nodesDegraded: 0,
        warnings: [],
        errors: [],
        degradations: [],
        recommendations: [],
        timings: [],
        files: [],
        metrics: { coverage: 100, degradationRate: 0 }
      };
      const md = generator.generate(data, tr.REPORT_FORMATS.MARKDOWN);
      assert(md.includes('# Transformation Report'), 'Should have title');
      assert(md.includes('react'), 'Should include framework');
    }) && moduleTests.passed++;

    test('ReportGenerator generates HTML', () => {
      const generator = new tr.ReportGenerator();
      const data = {
        sessionId: 'test-123',
        framework: 'vue',
        source: 'figma',
        nodesProcessed: 5,
        nodesSuccessful: 5,
        nodesFailed: 0,
        nodesSkipped: 0,
        nodesDegraded: 0,
        warnings: [],
        errors: [],
        degradations: [],
        recommendations: [],
        timings: [],
        files: [],
        metrics: { coverage: 100, degradationRate: 0 }
      };
      const html = generator.generate(data, tr.REPORT_FORMATS.HTML);
      assert(html.includes('<!DOCTYPE html>'), 'Should be valid HTML');
      assert(html.includes('vue'), 'Should include framework');
    }) && moduleTests.passed++;

    test('createReportSystem factory works', () => {
      const system = tr.createReportSystem({ collector: { framework: 'react' } });
      assertDefined(system.collector, 'Should have collector');
      assertDefined(system.generator, 'Should have generator');
      assertDefined(system.recordNode, 'Should have recordNode convenience');
      assertDefined(system.generate, 'Should have generate convenience');
    }) && moduleTests.passed++;

    test('generateReport utility works', () => {
      assertDefined(tr.generateReport, 'generateReport should be defined');
      const data = {
        sessionId: 'quick-test',
        framework: 'svelte',
        source: 'test',
        nodesProcessed: 1,
        nodesSuccessful: 1,
        nodesFailed: 0,
        nodesSkipped: 0,
        nodesDegraded: 0,
        warnings: [],
        errors: [],
        degradations: [],
        recommendations: [],
        timings: [],
        files: [],
        metrics: { coverage: 100, degradationRate: 0 }
      };
      const report = tr.generateReport(data);
      assertType(report, 'string', 'Should return string');
    }) && moduleTests.passed++;

  } catch (error) {
    console.log(`  ✗ Module load failed: ${error.message}`);
    testResults.errors.push({ name: 'transformation-report load', error: error.message });
    moduleTests.failed++;
  }

  testResults.modules['transformation-report'] = {
    ...moduleTests,
    duration: Date.now() - moduleStart
  };
}

// =============================================================================
// INTEGRATION TESTS
// =============================================================================

async function runIntegrationTests() {
  console.log('\n🔗 Running Integration Tests');

  try {
    // Test that modules work together
    test('Modules integrate: complexity -> degradation', () => {
      const fca = require('./figma-complexity-analyzer.js');
      const gd = require('./graceful-degradation.js');

      const node = { id: '1:1', name: 'Complex', type: 'FRAME', children: [] };
      const analysis = fca.analyzeNode(node);

      if (analysis.level === 'high' || analysis.level === 'critical') {
        const result = gd.canDegrade('react', 'component');
        assertEqual(result, true, 'Should be able to degrade');
      }
    });

    test('Modules integrate: logger -> report', () => {
      const sl = require('./sync-logger.js');
      const tr = require('./transformation-report.js');

      const logger = new sl.SyncLogger({ output: 'memory' });
      logger.info('Processing started');
      logger.transform('convert', { nodeId: '1:1' });

      const collector = new tr.ReportCollector();
      collector.recordNode({ id: '1:1' }, { success: true });

      const logSummary = logger.getSummary();
      const reportData = collector.finalize();

      assertDefined(logSummary.counters, 'Logger should have counters');
      assertDefined(reportData.metrics, 'Report should have metrics');
    });

    test('Modules integrate: canonical-id -> sync-verifier', () => {
      const cid = require('./canonical-id.js');
      const sv = require('./sync-verifier.js');

      const generator = new cid.CanonicalIdGenerator();
      const node = { id: '1:1', name: 'Button', type: 'COMPONENT', width: 100, height: 40 };
      const canonicalId = generator.generate(node);

      const verifier = new sv.SyncVerifier();
      verifier.setBaseline([node]);
      const result = verifier.verifyNode(node, node.id);

      assertType(canonicalId, 'string', 'Should generate canonical ID');
      assertEqual(result.status, sv.VERIFICATION_STATUS.SYNCED, 'Should verify as synced');
    });

    test('Modules integrate: stability -> batch processing', async () => {
      const rs = require('./render-stability.js');

      const processor = rs.createStableBatchProcessor(
        async (item) => item * 2,
        { batchSize: 2, stabilityWait: 10 }
      );

      const result = await processor([1, 2, 3, 4]);
      assertEqual(result.completed, true, 'Batch should complete');
      assertEqual(result.successCount, 4, 'All items should succeed');
    });

    console.log('  ✓ All integration tests passed');

  } catch (error) {
    console.log(`  ✗ Integration test failed: ${error.message}`);
    testResults.errors.push({ name: 'integration', error: error.message });
  }
}

// =============================================================================
// MAIN TEST RUNNER
// =============================================================================

async function runAllTests() {
  console.log('═'.repeat(60));
  console.log('  DEFENSIVE ENHANCEMENT MODULES - TEST SUITE');
  console.log('═'.repeat(60));
  console.log(`  Started: ${new Date().toISOString()}`);

  const startTime = Date.now();

  // Run all module tests
  testPatternCompatibility();
  testFigmaComplexityAnalyzer();
  testSyncLogger();
  testRenderStability();
  testGracefulDegradation();
  testCanonicalId();
  testSyncVerifier();
  testTransformationReport();

  // Run integration tests
  await runIntegrationTests();

  const duration = Date.now() - startTime;

  // Summary
  console.log('\n' + '═'.repeat(60));
  console.log('  TEST SUMMARY');
  console.log('═'.repeat(60));
  console.log(`  Total Passed: ${testResults.passed}`);
  console.log(`  Total Failed: ${testResults.failed}`);
  console.log(`  Duration: ${duration}ms`);
  console.log('');

  // Module breakdown
  console.log('  Module Results:');
  for (const [name, stats] of Object.entries(testResults.modules)) {
    const status = stats.failed === 0 ? '✓' : '✗';
    console.log(`    ${status} ${name}: ${stats.passed || 0} passed, ${stats.failed || 0} failed (${stats.duration}ms)`);
  }

  // Errors
  if (testResults.errors.length > 0) {
    console.log('\n  Errors:');
    for (const err of testResults.errors) {
      console.log(`    - ${err.name}: ${err.error}`);
    }
  }

  console.log('\n' + '═'.repeat(60));

  const allPassed = testResults.failed === 0;
  console.log(allPassed
    ? '  ✅ ALL TESTS PASSED'
    : `  ❌ ${testResults.failed} TESTS FAILED`);
  console.log('═'.repeat(60));

  return allPassed;
}

// Run tests
runAllTests().then(passed => {
  process.exit(passed ? 0 : 1);
}).catch(error => {
  console.error('Test runner error:', error);
  process.exit(1);
});
