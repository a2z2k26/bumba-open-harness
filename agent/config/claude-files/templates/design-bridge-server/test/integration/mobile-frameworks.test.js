/**
 * Mobile Framework Transformations Integration Test
 * Tests React Native, Flutter, SwiftUI, and Jetpack Compose generation
 */

const IntegrationTestRunner = require('./test-runner');
const TestUtils = require('./test-utils');
const path = require('path');
const fs = require('fs');

const runner = new IntegrationTestRunner();

// Test component data
const mobileComponent = TestUtils.createMockComponent({
  name: 'MobileButton',
  type: 'COMPONENT',
  props: {
    title: { type: 'string', required: true },
    variant: { type: 'string', default: 'filled' },
    onPress: { type: 'function' },
    disabled: { type: 'boolean', default: false }
  },
  styles: {
    backgroundColor: '#3B82F6',
    color: '#FFFFFF',
    paddingVertical: 12,
    paddingHorizontal: 24,
    borderRadius: 8,
    fontSize: 16,
    fontWeight: '600'
  }
});

// ============================================
// REACT NATIVE TESTS
// ============================================
runner.test('React Native optimizer exists', async () => {
  const serverDir = path.join(__dirname, '../..');

  // Check if react-native-optimizer.js exists (canonical location)
  const optimizerPath = path.join(serverDir, 'react-native-optimizer.js');
  const exists = fs.existsSync(optimizerPath);

  TestUtils.assertTrue(exists, 'React Native optimizer file should exist');

  console.log('   React Native optimizer found');
});

runner.test('React Native optimizer loads correctly', async () => {
  const ReactNativeOptimizer = require('../../react-native-optimizer');
  TestUtils.assertTrue(ReactNativeOptimizer, 'ReactNativeOptimizer should be importable');

  const optimizer = new ReactNativeOptimizer();
  TestUtils.assertTrue(optimizer, 'Optimizer instance should be created');

  console.log('   React Native optimizer loads');
});

runner.test('React Native has generateComponent method', async () => {
  const ReactNativeOptimizer = require('../../react-native-optimizer');
  const optimizer = new ReactNativeOptimizer();

  TestUtils.assertTrue(
    typeof optimizer.generateComponent === 'function',
    'Should have generateComponent method'
  );

  console.log('   React Native generateComponent available');
});

// ============================================
// FLUTTER TESTS
// ============================================
runner.test('Flutter optimizer exists', async () => {
  const serverDir = path.join(__dirname, '../..');
  const optimizerPath = path.join(serverDir, 'flutter-optimizer.js');
  const exists = fs.existsSync(optimizerPath);

  TestUtils.assertTrue(exists, 'Flutter optimizer file should exist');

  console.log('   Flutter optimizer found');
});

runner.test('Flutter optimizer loads correctly', async () => {
  const FlutterOptimizer = require('../../flutter-optimizer');
  TestUtils.assertTrue(FlutterOptimizer, 'FlutterOptimizer should be importable');

  const optimizer = new FlutterOptimizer();
  TestUtils.assertTrue(optimizer, 'Optimizer instance should be created');

  console.log('   Flutter optimizer loads');
});

runner.test('Flutter has generate method', async () => {
  const FlutterOptimizer = require('../../flutter-optimizer');
  const optimizer = new FlutterOptimizer();

  // Flutter uses generateWidget (widget-based terminology)
  TestUtils.assertTrue(
    typeof optimizer.generateWidget === 'function',
    'Should have generateWidget method'
  );

  console.log('   Flutter generateWidget available');
});

// ============================================
// SWIFTUI TESTS
// ============================================
runner.test('SwiftUI optimizer exists', async () => {
  const serverDir = path.join(__dirname, '../..');
  const optimizerPath = path.join(serverDir, 'swiftui-optimizer.js');
  const exists = fs.existsSync(optimizerPath);

  TestUtils.assertTrue(exists, 'SwiftUI optimizer file should exist');

  console.log('   SwiftUI optimizer found');
});

runner.test('SwiftUI optimizer loads correctly', async () => {
  const SwiftUIOptimizer = require('../../swiftui-optimizer');
  TestUtils.assertTrue(SwiftUIOptimizer, 'SwiftUIOptimizer should be importable');

  const optimizer = new SwiftUIOptimizer();
  TestUtils.assertTrue(optimizer, 'Optimizer instance should be created');

  console.log('   SwiftUI optimizer loads');
});

runner.test('SwiftUI has generate method', async () => {
  const SwiftUIOptimizer = require('../../swiftui-optimizer');
  const optimizer = new SwiftUIOptimizer();

  // SwiftUI uses generateView (View-based terminology)
  TestUtils.assertTrue(
    typeof optimizer.generateView === 'function',
    'Should have generateView method'
  );

  console.log('   SwiftUI generateView available');
});

// ============================================
// JETPACK COMPOSE TESTS
// ============================================
runner.test('Jetpack Compose optimizer exists', async () => {
  const serverDir = path.join(__dirname, '../..');
  const optimizerPath = path.join(serverDir, 'jetpack-compose-optimizer.js');
  const exists = fs.existsSync(optimizerPath);

  TestUtils.assertTrue(exists, 'Compose optimizer file should exist');

  console.log('   Compose optimizer found');
});

runner.test('Jetpack Compose optimizer loads correctly', async () => {
  const ComposeOptimizer = require('../../jetpack-compose-optimizer');
  TestUtils.assertTrue(ComposeOptimizer, 'ComposeOptimizer should be importable');

  const optimizer = new ComposeOptimizer();
  TestUtils.assertTrue(optimizer, 'Optimizer instance should be created');

  console.log('   Compose optimizer loads');
});

runner.test('Jetpack Compose has generate method', async () => {
  const ComposeOptimizer = require('../../jetpack-compose-optimizer');
  const optimizer = new ComposeOptimizer();

  // Jetpack Compose uses generateComposable (Composable-based terminology)
  TestUtils.assertTrue(
    typeof optimizer.generateComposable === 'function',
    'Should have generateComposable method'
  );

  console.log('   Compose generateComposable available');
});

// ============================================
// ALL FRAMEWORKS REGISTERED
// ============================================
runner.test('All mobile frameworks registered in registry', async () => {
  const { getOptimizerRegistry } = require('../../optimizer-registry');
  const registry = getOptimizerRegistry();

  const mobileFrameworks = ['react-native', 'flutter', 'swiftui', 'compose'];
  const missing = [];

  for (const framework of mobileFrameworks) {
    const optimizer = registry.getOptimizer(framework);
    if (!optimizer) {
      missing.push(framework);
    }
  }

  TestUtils.assertEqual(missing.length, 0, `Missing frameworks: ${missing.join(', ')}`);

  console.log('   All 4 mobile frameworks registered');
});

// Run tests
if (require.main === module) {
  runner.run().then(results => {
    process.exit(results.failed > 0 ? 1 : 0);
  });
}

module.exports = runner;
