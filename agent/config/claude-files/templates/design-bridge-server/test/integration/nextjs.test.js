/**
 * Next.js Transformation Integration Test
 * Tests Next.js-specific code generation features
 */

const IntegrationTestRunner = require('./test-runner');
const TestUtils = require('./test-utils');
const path = require('path');
const fs = require('fs');

const runner = new IntegrationTestRunner();

// Test component data
const clientComponent = TestUtils.createMockComponent({
  name: 'InteractiveCard',
  props: {
    title: { type: 'string', required: true },
    onClick: { type: 'function' }
  },
  state: {
    isExpanded: false
  }
});

const serverComponent = TestUtils.createMockComponent({
  name: 'DataDisplay',
  props: {
    data: { type: 'object', required: true }
  },
  state: {} // No client state
});

// ============================================
// TEST: NextOptimizer Exists
// ============================================
runner.test('NextOptimizer file exists', async () => {
  const optimizerPath = path.join(__dirname, '../../next-optimizer.js');
  const exists = fs.existsSync(optimizerPath);

  TestUtils.assertTrue(exists, 'next-optimizer.js should exist');

  console.log('   NextOptimizer file found');
});

// ============================================
// TEST: NextOptimizer Loads
// ============================================
runner.test('NextOptimizer loads correctly', async () => {
  const NextOptimizer = require('../../next-optimizer');
  TestUtils.assertTrue(NextOptimizer, 'NextOptimizer should be importable');

  const optimizer = new NextOptimizer();
  TestUtils.assertTrue(optimizer, 'Optimizer instance should be created');

  console.log('   NextOptimizer loads');
});

// ============================================
// TEST: NextOptimizer Has Required Methods
// ============================================
runner.test('NextOptimizer has required methods', async () => {
  const NextOptimizer = require('../../next-optimizer');
  const optimizer = new NextOptimizer();

  TestUtils.assertTrue(
    typeof optimizer.generateComponent === 'function',
    'Should have generateComponent method'
  );

  TestUtils.assertTrue(
    typeof optimizer.needsClientDirective === 'function',
    'Should have needsClientDirective method'
  );

  console.log('   NextOptimizer methods available');
});

// ============================================
// TEST: Client Component Detection
// ============================================
runner.test('Client component detection works', async () => {
  const NextOptimizer = require('../../next-optimizer');
  const optimizer = new NextOptimizer();

  // Component with onClick should need client directive
  const needsClient = optimizer.needsClientDirective(clientComponent);
  TestUtils.assertTrue(needsClient, 'Component with onClick should need client directive');

  // Component without state/handlers should not need it
  const serverCheck = optimizer.needsClientDirective(serverComponent);
  TestUtils.assertEqual(serverCheck, false, 'Server component should not need client directive');

  console.log('   Client detection works');
});

// ============================================
// TEST: 'use client' Directive Generation
// ============================================
runner.test("'use client' directive added correctly", async () => {
  const NextOptimizer = require('../../next-optimizer');
  const optimizer = new NextOptimizer();

  const code = await optimizer.generateComponent(clientComponent, {
    appRouter: true
  });

  // First line should be 'use client'
  const lines = code.split('\n');
  const firstNonEmptyLine = lines.find(l => l.trim().length > 0);

  TestUtils.assertTrue(
    firstNonEmptyLine.includes("'use client'") || firstNonEmptyLine.includes('"use client"'),
    "First line should be 'use client'"
  );

  console.log('   use client directive present');
});

// ============================================
// TEST: Server Component Generation
// ============================================
runner.test('Server component has no use client', async () => {
  const NextOptimizer = require('../../next-optimizer');
  const optimizer = new NextOptimizer();

  const code = await optimizer.generateComponent(serverComponent, {
    appRouter: true,
    forceServer: true
  });

  TestUtils.assertTrue(
    !code.includes("'use client'") && !code.includes('"use client"'),
    'Server component should not have use client directive'
  );

  console.log('   Server component correct');
});

// ============================================
// TEST: Next.js Registered in Registry
// ============================================
runner.test('Next.js optimizer registered in registry', async () => {
  const { getOptimizerRegistry } = require('../../optimizer-registry');
  const registry = getOptimizerRegistry();

  const optimizer = registry.getOptimizer('nextjs');
  TestUtils.assertTrue(optimizer, 'Next.js optimizer should be registered');

  console.log('   Next.js registered in registry');
});

// ============================================
// TEST: App Router Mode Works
// ============================================
runner.test('App Router mode generates correct structure', async () => {
  const NextOptimizer = require('../../next-optimizer');
  const optimizer = new NextOptimizer();

  const code = await optimizer.generateComponent(clientComponent, {
    appRouter: true
  });

  // Should have React import
  TestUtils.assertContains(code, 'React');
  // Should have component export
  TestUtils.assertContains(code, 'export');

  console.log('   App Router structure valid');
});

// ============================================
// TEST: Pages Router Mode Works
// ============================================
runner.test('Pages Router mode generates correct structure', async () => {
  const NextOptimizer = require('../../next-optimizer');
  const optimizer = new NextOptimizer();

  const code = await optimizer.generateComponent(clientComponent, {
    appRouter: false
  });

  // Should NOT have 'use client' in pages router mode
  TestUtils.assertTrue(
    !code.includes("'use client'"),
    'Pages router should not have use client'
  );

  console.log('   Pages Router structure valid');
});

// Run tests
if (require.main === module) {
  runner.run().then(results => {
    process.exit(results.failed > 0 ? 1 : 0);
  });
}

module.exports = runner;
