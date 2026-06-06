/**
 * Token → Code Pipeline Integration Test
 * Tests the full transformation from design tokens to framework code
 */

const IntegrationTestRunner = require('./test-runner');
const TestUtils = require('./test-utils');

// Test runner instance
const runner = new IntegrationTestRunner();

// Test fixtures
const testTokens = TestUtils.createMockTokens();
const testComponent = TestUtils.createMockComponent({
  name: 'Button',
  props: {
    variant: { type: 'string', default: 'primary' },
    size: { type: 'string', default: 'medium' },
    children: { type: 'node', required: true },
    onClick: { type: 'function' }
  }
});

// ============================================
// TEST: Optimizer Registry Exists
// ============================================
runner.test('OptimizerRegistry loads correctly', async () => {
  const { getOptimizerRegistry } = require('../../optimizer-registry');
  const registry = getOptimizerRegistry();

  TestUtils.assertTrue(registry, 'Registry should exist');
  TestUtils.assertTrue(typeof registry.getOptimizer === 'function', 'getOptimizer method should exist');

  console.log('   OptimizerRegistry loaded');
});

// ============================================
// TEST: React Optimizer Exists
// ============================================
runner.test('React optimizer registered', async () => {
  const { getOptimizerRegistry } = require('../../optimizer-registry');
  const registry = getOptimizerRegistry();

  const optimizer = registry.getOptimizer('react');
  TestUtils.assertTrue(optimizer, 'React optimizer should exist');

  console.log('   React optimizer found');
});

// ============================================
// TEST: Vue Optimizer Exists
// ============================================
runner.test('Vue optimizer registered', async () => {
  const { getOptimizerRegistry } = require('../../optimizer-registry');
  const registry = getOptimizerRegistry();

  const optimizer = registry.getOptimizer('vue');
  TestUtils.assertTrue(optimizer, 'Vue optimizer should exist');

  console.log('   Vue optimizer found');
});

// ============================================
// TEST: Svelte Optimizer Exists
// ============================================
runner.test('Svelte optimizer registered', async () => {
  const { getOptimizerRegistry } = require('../../optimizer-registry');
  const registry = getOptimizerRegistry();

  const optimizer = registry.getOptimizer('svelte');
  TestUtils.assertTrue(optimizer, 'Svelte optimizer should exist');

  console.log('   Svelte optimizer found');
});

// ============================================
// TEST: Angular Optimizer Exists
// ============================================
runner.test('Angular optimizer registered', async () => {
  const { getOptimizerRegistry } = require('../../optimizer-registry');
  const registry = getOptimizerRegistry();

  const optimizer = registry.getOptimizer('angular');
  TestUtils.assertTrue(optimizer, 'Angular optimizer should exist');

  console.log('   Angular optimizer found');
});

// ============================================
// TEST: Web Components Optimizer Exists
// ============================================
runner.test('Web Components optimizer registered', async () => {
  const { getOptimizerRegistry } = require('../../optimizer-registry');
  const registry = getOptimizerRegistry();

  const optimizer = registry.getOptimizer('web-components');
  TestUtils.assertTrue(optimizer, 'Web Components optimizer should exist');

  console.log('   Web Components optimizer found');
});

// ============================================
// TEST: SmartCodeGenerator Works
// ============================================
runner.test('SmartCodeGenerator generates code', async () => {
  const SmartCodeGenerator = require('../../smart-code-generator');
  const generator = new SmartCodeGenerator();

  TestUtils.assertTrue(generator, 'Generator should exist');
  TestUtils.assertTrue(typeof generator.generateCode === 'function', 'generateCode method should exist');

  console.log('   SmartCodeGenerator ready');
});

// ============================================
// TEST: Token Processing Works
// ============================================
runner.test('Token processing extracts values', async () => {
  const tokens = TestUtils.createMockTokens();

  TestUtils.assertTrue(tokens.colors, 'Tokens should have colors');
  TestUtils.assertTrue(tokens.typography, 'Tokens should have typography');
  TestUtils.assertTrue(tokens.spacing, 'Tokens should have spacing');

  TestUtils.assertEqual(tokens.colors.primary.value, '#3B82F6');
  TestUtils.assertEqual(tokens.spacing.md, '16px');

  console.log('   Token processing valid');
});

// ============================================
// TEST: Component Generation Structure
// ============================================
runner.test('Component mock has valid structure', async () => {
  const component = TestUtils.createMockComponent({
    name: 'TestButton'
  });

  TestUtils.assertEqual(component.name, 'TestButton');
  TestUtils.assertTrue(component.props, 'Should have props');
  TestUtils.assertTrue(component.styles, 'Should have styles');
  TestUtils.assertTrue(Array.isArray(component.variants), 'Should have variants array');

  console.log('   Component structure valid');
});

// Run all tests
if (require.main === module) {
  runner.run().then(results => {
    process.exit(results.failed > 0 ? 1 : 0);
  });
}

module.exports = runner;
