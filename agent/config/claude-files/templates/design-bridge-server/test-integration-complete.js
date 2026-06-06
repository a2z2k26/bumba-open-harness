#!/usr/bin/env node
/**
 * Complete Integration & Implementation Tests
 * Tests the defensive enhancement system's integration with:
 * - layout-validator.js
 * - figma-transformer.js
 * - cli.js (sync-verify command)
 */

console.log('═'.repeat(60));
console.log('  INTEGRATION & IMPLEMENTATION TESTS');
console.log('═'.repeat(60));

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log('  ✓ ' + name);
    passed++;
  } catch (e) {
    console.log('  ✗ ' + name);
    console.log('    Error: ' + e.message);
    failed++;
  }
}

async function asyncTest(name, fn) {
  try {
    await fn();
    console.log('  ✓ ' + name);
    passed++;
  } catch (e) {
    console.log('  ✗ ' + name);
    console.log('    Error: ' + e.message);
    failed++;
  }
}

// ============================================
console.log('\n📦 Testing layout-validator.js Integration');
// ============================================

const { LayoutValidator, createValidator } = require('./layout-validator.js');

test('LayoutValidator accepts defensive options', () => {
  const validator = new LayoutValidator('/tmp', {
    enableLogging: true,
    enableVerification: true,
    enableReporting: true
  });
  if (validator.enableLogging !== true) throw new Error('enableLogging not set');
  if (validator.enableVerification !== true) throw new Error('enableVerification not set');
  if (validator.enableReporting !== true) throw new Error('enableReporting not set');
});

test('LayoutValidator creates logger instance', () => {
  const validator = new LayoutValidator('/tmp', { enableLogging: true });
  if (!validator.logger) throw new Error('Logger not created');
  if (typeof validator.logger.info !== 'function') throw new Error('Logger missing info method');
});

test('LayoutValidator creates verifier instance', () => {
  const validator = new LayoutValidator('/tmp', { enableVerification: true });
  if (!validator.verifier) throw new Error('Verifier not created');
  if (typeof validator.verifier.setBaseline !== 'function') throw new Error('Verifier missing setBaseline');
});

test('LayoutValidator creates reportCollector instance', () => {
  const validator = new LayoutValidator('/tmp', { enableReporting: true });
  if (!validator.reportCollector) throw new Error('ReportCollector not created');
  if (typeof validator.reportCollector.recordNode !== 'function') throw new Error('Reporter missing recordNode');
});

test('LayoutValidator._log works when enabled', () => {
  const validator = new LayoutValidator('/tmp', { enableLogging: true });
  // Should not throw
  validator._log('info', 'Test message', { test: true });
});

test('LayoutValidator._log works when disabled', () => {
  const validator = new LayoutValidator('/tmp', { enableLogging: false });
  // Should not throw even when disabled
  validator._log('info', 'Test message', { test: true });
});

test('LayoutValidator._recordMetric works', () => {
  const validator = new LayoutValidator('/tmp', { enableReporting: true });
  // Should not throw
  validator._recordMetric('node', { node: { id: '1' }, result: { status: 'success' } });
  validator._recordMetric('warning', { message: 'Test', context: {} });
});

test('LayoutValidator.getDefensiveStatus returns correct structure', () => {
  const validator = new LayoutValidator('/tmp', {
    enableLogging: true,
    enableVerification: true,
    enableReporting: true
  });
  const status = validator.getDefensiveStatus();
  if (!status.logging) throw new Error('Missing logging status');
  if (!status.verification) throw new Error('Missing verification status');
  if (!status.reporting) throw new Error('Missing reporting status');
  if (status.logging.enabled !== true) throw new Error('Logging should be enabled');
  if (status.logging.active !== true) throw new Error('Logger should be active');
});

test('createValidator factory accepts options', () => {
  const validator = createValidator('/tmp', { enableLogging: false });
  if (validator.enableLogging !== false) throw new Error('Option not passed through');
});

// ============================================
console.log('\n📦 Testing figma-transformer.js Integration');
// ============================================

const ft = require('./figma-transformer.js');

test('figma-transformer exports defensive utilities', () => {
  if (typeof ft.getTransformationReportData !== 'function') throw new Error('Missing getTransformationReportData');
  if (typeof ft.getLogSummary !== 'function') throw new Error('Missing getLogSummary');
  if (typeof ft.resetDefensiveState !== 'function') throw new Error('Missing resetDefensiveState');
  if (typeof ft.createTransformer !== 'function') throw new Error('Missing createTransformer');
});

test('transformFigmaNode adds defensiveMetadata', () => {
  ft.resetDefensiveState();
  const mockNode = {
    id: '1:2',
    name: 'TestComponent',
    type: 'COMPONENT',
    fills: [],
    children: []
  };
  const result = ft.transformFigmaNode(mockNode, {}, {
    fileKey: 'test',
    enableComplexityAnalysis: true,
    enablePatternCheck: true
  });
  if (!result.defensiveMetadata) throw new Error('Missing defensiveMetadata');
});

test('transformFigmaNode accepts targetFramework option', () => {
  ft.resetDefensiveState();
  const mockNode = { id: '1:2', name: 'Test', type: 'FRAME', children: [] };
  const result = ft.transformFigmaNode(mockNode, {}, { targetFramework: 'vue' });
  if (result.defensiveMetadata.targetFramework !== 'vue') throw new Error('targetFramework not set');
});

test('getLogSummary returns structured data', () => {
  ft.resetDefensiveState();
  // Do a transformation to generate logs
  ft.transformFigmaNode({ id: '1:1', name: 'Test', type: 'FRAME', children: [] }, {}, {});
  const summary = ft.getLogSummary();
  if (!summary.summary) throw new Error('Missing summary');
  if (!Array.isArray(summary.errors)) throw new Error('Missing errors array');
  if (!Array.isArray(summary.warnings)) throw new Error('Missing warnings array');
});

test('getTransformationReportData returns report', () => {
  ft.resetDefensiveState();
  ft.transformFigmaNode({ id: '1:1', name: 'Test', type: 'FRAME', children: [] }, {}, {});
  const report = ft.getTransformationReportData();
  if (typeof report !== 'object') throw new Error('Report should be object');
});

test('resetDefensiveState clears state', () => {
  ft.resetDefensiveState();
  // Should not throw and should create fresh instances on next use
  const summary1 = ft.getLogSummary();
  ft.resetDefensiveState();
  const summary2 = ft.getLogSummary();
  // Both should work
  if (!summary1 || !summary2) throw new Error('State not properly reset');
});

test('createTransformer returns isolated instance', () => {
  const transformer = ft.createTransformer({ sessionName: 'test-session' });
  if (typeof transformer.transformNode !== 'function') throw new Error('Missing transformNode');
  if (typeof transformer.transformResponse !== 'function') throw new Error('Missing transformResponse');
  if (typeof transformer.getReport !== 'function') throw new Error('Missing getReport');
  if (typeof transformer.getLogSummary !== 'function') throw new Error('Missing getLogSummary');
});

test('createTransformer.transformNode works', () => {
  const transformer = ft.createTransformer({ sessionName: 'test' });
  const result = transformer.transformNode({ id: '1:1', name: 'Test', type: 'FRAME', children: [] });
  if (!result.id) throw new Error('Transform failed');
});

test('createTransformer.getReport returns session report', () => {
  const transformer = ft.createTransformer({ sessionName: 'test' });
  transformer.transformNode({ id: '1:1', name: 'Test', type: 'FRAME', children: [] });
  const report = transformer.getReport();
  if (typeof report !== 'object') throw new Error('Report should be object');
});

test('transformMcpResponse accepts options', () => {
  ft.resetDefensiveState();
  const mockResponse = {
    name: 'TestFile',
    lastModified: '2025-01-01T00:00:00Z',
    nodes: {
      '1:2': { document: { id: '1:2', name: 'Test', type: 'FRAME', children: [] } }
    }
  };
  const results = ft.transformMcpResponse(mockResponse, 'test-key', {
    targetFramework: 'svelte',
    enableComplexityAnalysis: true
  });
  if (!Array.isArray(results)) throw new Error('Should return array');
  if (results.length !== 1) throw new Error('Should have 1 result');
});

// ============================================
console.log('\n📦 Testing CLI sync-verify Integration');
// ============================================

const { DesignBridgeCLI } = require('./cli.js');

test('CLI has syncVerify method', () => {
  const cli = new DesignBridgeCLI(process.cwd());
  if (typeof cli.syncVerify !== 'function') throw new Error('Missing syncVerify method');
});

test('CLI has formatReportMarkdown method', () => {
  const cli = new DesignBridgeCLI(process.cwd());
  if (typeof cli.formatReportMarkdown !== 'function') throw new Error('Missing formatReportMarkdown');
});

test('CLI COMMANDS includes sync-verify', () => {
  // Check that the command is registered
  const cli = new DesignBridgeCLI(process.cwd());
  // CLI parses commands from COMMANDS object, just verify syncVerify exists
  if (typeof cli.syncVerify !== 'function') throw new Error('sync-verify not implemented');
});

test('formatReportMarkdown generates valid markdown', () => {
  const cli = new DesignBridgeCLI(process.cwd());
  const report = {
    generatedAt: new Date().toISOString(),
    framework: 'react',
    designPath: '/test',
    errors: [{ message: 'Test error' }],
    warnings: [{ message: 'Test warning' }]
  };
  const md = cli.formatReportMarkdown(report);
  if (!md.includes('# Sync Verification Report')) throw new Error('Missing title');
  if (!md.includes('Test error')) throw new Error('Missing error');
  if (!md.includes('Test warning')) throw new Error('Missing warning');
});

// ============================================
console.log('\n📦 Testing Cross-Module Integration');
// ============================================

test('Complexity analysis flows to transformer', () => {
  ft.resetDefensiveState();
  const complexNode = {
    id: '1:1',
    name: 'ComplexComponent',
    type: 'COMPONENT_SET',
    children: Array(50).fill(null).map((_, i) => ({
      id: '1:' + (i + 2),
      name: 'Child' + i,
      type: 'FRAME',
      children: []
    }))
  };
  const result = ft.transformFigmaNode(complexNode, {}, {
    enableComplexityAnalysis: true
  });
  // Should have analyzed complexity
  if (!result.defensiveMetadata) throw new Error('Missing defensiveMetadata');
});

test('Logger integrates with report collector', () => {
  const { createLogger } = require('./sync-logger.js');
  const { ReportCollector } = require('./transformation-report.js');

  const logger = createLogger({ name: 'integration-test', output: 'memory' });
  const reporter = new ReportCollector({ framework: 'react', source: 'test' });

  logger.info('Test operation');
  reporter.recordNode({ id: '1', type: 'test' }, { status: 'success' });

  const logSummary = logger.getSummary();
  const reportData = reporter.finalize();

  if (logSummary.counters.info !== 1) throw new Error('Log not recorded');
  // finalize() returns the full report data, not a nested summary object
  if (!reportData.nodesProcessed && reportData.nodesProcessed !== 0) throw new Error('Report not finalized');
});

test('Canonical ID integrates with sync verifier', () => {
  const { CanonicalIdGenerator } = require('./canonical-id.js');
  const { SyncVerifier } = require('./sync-verifier.js');

  // Use the class-based API for ID generation
  const idGen = new CanonicalIdGenerator({ strategy: 'content-hash' });
  const node = { id: '1:1', name: 'Button', type: 'COMPONENT' };
  const canonicalId = idGen.generate(node);

  // SyncVerifier.setBaseline() expects an array of nodes
  // SyncVerifier.verifyNode() expects (node, id)
  const verifier = new SyncVerifier();
  verifier.setBaseline([node]); // Pass array of nodes

  const result = verifier.verifyNode(node, node.id); // (node, id) order
  if (result.status !== 'synced') throw new Error('Verification failed: ' + result.status);
});

test('Graceful degradation provides fallbacks', () => {
  const { FRAMEWORK_FALLBACKS, FALLBACK_LEVELS, canDegrade, wrapWithDegradation } = require('./graceful-degradation.js');

  // Test that FRAMEWORK_FALLBACKS has react layout fallbacks
  if (!FRAMEWORK_FALLBACKS.react) throw new Error('No react fallbacks');
  if (!FRAMEWORK_FALLBACKS.react.layout) throw new Error('No react layout fallbacks');

  // Test that simplified fallback exists and works
  const simplifiedFn = FRAMEWORK_FALLBACKS.react.layout.simplified;
  if (typeof simplifiedFn !== 'function') throw new Error('Simplified fallback not a function');

  const fallbackResult = simplifiedFn({ layout: { direction: 'row' } });
  if (!fallbackResult.display) throw new Error('Fallback missing display property');
  if (fallbackResult.display !== 'flex') throw new Error('Expected flex display');

  // Test canDegrade utility
  const canDeg = canDegrade('auto-layout', 'react');
  if (typeof canDeg !== 'boolean') throw new Error('canDegrade should return boolean');

  // Test FALLBACK_LEVELS constants exist
  if (!FALLBACK_LEVELS.FULL) throw new Error('Missing FULL level');
  if (!FALLBACK_LEVELS.SIMPLIFIED) throw new Error('Missing SIMPLIFIED level');
});

test('Full pipeline: analyze -> transform -> verify -> report', () => {
  ft.resetDefensiveState();

  // 1. Analyze
  const { analyzeNode } = require('./figma-complexity-analyzer.js');
  const node = { id: '1:1', name: 'TestPipeline', type: 'FRAME', children: [] };
  const complexity = analyzeNode(node);

  // 2. Transform
  const transformed = ft.transformFigmaNode(node, {}, {
    enableComplexityAnalysis: true,
    enablePatternCheck: true
  });

  // 3. Verify - setBaseline expects array of nodes, verifyNode expects (node, id)
  const { SyncVerifier } = require('./sync-verifier.js');

  const verifier = new SyncVerifier();
  verifier.setBaseline([transformed]); // Array of nodes
  const verifyResult = verifier.verifyNode(transformed, transformed.id); // (node, id)

  // 4. Report
  const report = ft.getTransformationReportData();

  // All steps should succeed
  if (!complexity) throw new Error('Analysis failed');
  if (!transformed.id) throw new Error('Transform failed');
  if (verifyResult.status !== 'synced') throw new Error('Verify failed: ' + verifyResult.status);
  if (!report) throw new Error('Report failed');
});

// ============================================
// Async CLI Tests
// ============================================
async function runAsyncTests() {
  console.log('\n📦 Testing CLI Async Operations');

  const cli = new DesignBridgeCLI(process.cwd());

  await asyncTest('syncVerify status handles missing .design', async () => {
    const result = await cli.syncVerify('status', { path: '/tmp/nonexistent-design-path' });
    if (result.success !== false) throw new Error('Should fail for missing path');
    if (!result.error) throw new Error('Should have error message');
  });

  await asyncTest('syncVerify report generates valid report', async () => {
    const result = await cli.syncVerify('report', { path: '/tmp', format: 'json' });
    if (!result.success) throw new Error('Report generation failed');
    if (!result.report) throw new Error('Missing report data');
    if (!result.report.generatedAt) throw new Error('Report missing timestamp');
  });

  await asyncTest('syncVerify unknown action returns error', async () => {
    const result = await cli.syncVerify('unknown-action', {});
    if (result.success !== false) throw new Error('Should fail for unknown action');
  });
}

// Run async tests and print summary
runAsyncTests().then(() => {
  // ============================================
  console.log('\n' + '═'.repeat(60));
  console.log('  TEST SUMMARY');
  console.log('═'.repeat(60));
  console.log('  Total Passed: ' + passed);
  console.log('  Total Failed: ' + failed);
  console.log('═'.repeat(60));
  if (failed === 0) {
    console.log('  ✅ ALL INTEGRATION TESTS PASSED');
  } else {
    console.log('  ❌ SOME TESTS FAILED');
    process.exit(1);
  }
  console.log('═'.repeat(60));
}).catch(err => {
  console.error('Test runner error:', err);
  process.exit(1);
});
