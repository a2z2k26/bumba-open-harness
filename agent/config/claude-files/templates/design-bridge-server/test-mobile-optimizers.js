/**
 * Test Mobile Optimizer Registration
 * Sprint 1.6 Validation
 */
const { getOptimizerRegistry } = require('./optimizer-registry');

function testMobileOptimizers() {
  const registry = getOptimizerRegistry();

  const testCases = [
    // React Native
    { key: 'react-native', expectedName: 'ReactNativeOptimizer' },
    { key: 'reactnative', expectedName: 'ReactNativeOptimizer' },
    // Flutter
    { key: 'flutter', expectedName: 'FlutterOptimizer' },
    // SwiftUI
    { key: 'swiftui', expectedName: 'SwiftUIOptimizer' },
    { key: 'swift-ui', expectedName: 'SwiftUIOptimizer' },
    { key: 'swift', expectedName: 'SwiftUIOptimizer' },
    // Jetpack Compose
    { key: 'jetpack-compose', expectedName: 'JetpackComposeOptimizer' },
    { key: 'jetpackcompose', expectedName: 'JetpackComposeOptimizer' },
    { key: 'compose', expectedName: 'JetpackComposeOptimizer' },
    { key: 'android', expectedName: 'JetpackComposeOptimizer' }
  ];

  let passed = 0;
  let failed = 0;

  console.log('\n=== Mobile Optimizer Registration Test ===\n');

  for (const test of testCases) {
    const optimizer = registry.getOptimizer(test.key);
    const actualName = optimizer?.name || 'null';
    const success = actualName === test.expectedName;

    if (success) {
      console.log(`✅ PASS: '${test.key}' → ${actualName}`);
      passed++;
    } else {
      console.log(`❌ FAIL: '${test.key}' → ${actualName} (expected ${test.expectedName})`);
      failed++;
    }
  }

  console.log(`\n=== Results: ${passed}/${testCases.length} passed ===\n`);

  return failed === 0;
}

// Run if executed directly
if (require.main === module) {
  const success = testMobileOptimizers();
  process.exit(success ? 0 : 1);
}

module.exports = { testMobileOptimizers };
