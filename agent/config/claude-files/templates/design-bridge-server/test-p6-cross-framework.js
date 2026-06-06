/**
 * test-p6-cross-framework.js
 * P6.3: Cross-Framework Variant Synchronization Tests
 *
 * Verifies that all 9 framework optimizers receive and process variants consistently.
 * Each framework should see the same variant values regardless of the source format.
 */

const { normalizeVariants, syncToFramework } = require('./variant-sync');

// Simulate a typical Figma-extracted component registry entry
const MOCK_REGISTRY = {
  id: 'button-component',
  name: 'Button',
  description: 'Primary action button',
  variants: [
    {
      name: 'size',
      type: 'variant',
      options: ['sm', 'md', 'lg'],
      default: 'md'
    },
    {
      name: 'variant',
      type: 'variant',
      options: ['primary', 'secondary', 'outline', 'ghost'],
      default: 'primary'
    },
    {
      name: 'disabled',
      type: 'boolean',
      options: ['true', 'false'],
      default: 'false'
    }
  ],
  props: {
    size: { type: "'sm' | 'md' | 'lg'", default: "'md'" },
    variant: { type: "'primary' | 'secondary' | 'outline' | 'ghost'", default: "'primary'" },
    disabled: { type: 'boolean', default: false }
  }
};

// All framework targets
const FRAMEWORKS = [
  // Group 1: Uses variant.name
  'react',
  'vue',
  'flutter',
  'react-native',
  'web-components',
  // Group 2: Uses variant.property + variant.values
  'angular',
  'svelte',
  'swiftui',
  'jetpack-compose'
];

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log(`✅ ${name}`);
    passed++;
  } catch (error) {
    console.log(`❌ ${name}`);
    console.log(`   Error: ${error.message}`);
    failed++;
  }
}

function assertEqual(actual, expected, msg = '') {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${msg}\nExpected: ${JSON.stringify(expected)}\nActual: ${JSON.stringify(actual)}`);
  }
}

function assertTrue(condition, msg = 'Assertion failed') {
  if (!condition) {
    throw new Error(msg);
  }
}

console.log('\n=== P6.3 Cross-Framework Variant Tests ===\n');

// Test 1: All frameworks receive the same variant values array
test('P6.3.1: All frameworks see identical variant values', () => {
  const results = {};

  for (const framework of FRAMEWORKS) {
    const synced = syncToFramework(MOCK_REGISTRY.variants, framework);
    results[framework] = synced.map(v => ({
      name: v.name,
      values: v.values
    }));
  }

  // Get React as baseline
  const baseline = results['react'];

  // All others should match React's values
  for (const framework of FRAMEWORKS) {
    const frameworkValues = results[framework];

    for (let i = 0; i < baseline.length; i++) {
      assertEqual(
        frameworkValues[i].values,
        baseline[i].values,
        `${framework} variant[${i}] values mismatch`
      );
    }
  }
});

// Test 2: All variants have both .name and .property after normalization
test('P6.3.2: All variants have both .name and .property fields', () => {
  for (const framework of FRAMEWORKS) {
    const synced = syncToFramework(MOCK_REGISTRY.variants, framework);

    for (const variant of synced) {
      assertTrue(
        variant.name !== undefined,
        `${framework}: variant missing .name`
      );
      assertTrue(
        variant.property !== undefined,
        `${framework}: variant missing .property`
      );
      assertEqual(variant.name, variant.property, `${framework}: name/property mismatch`);
    }
  }
});

// Test 3: All variants have both .values and .options (aliases)
test('P6.3.3: All variants have .values and .options aliases', () => {
  for (const framework of FRAMEWORKS) {
    const synced = syncToFramework(MOCK_REGISTRY.variants, framework);

    for (const variant of synced) {
      assertTrue(
        Array.isArray(variant.values),
        `${framework}: variant.values should be array`
      );
      assertTrue(
        Array.isArray(variant.options),
        `${framework}: variant.options should be array`
      );
      assertEqual(variant.values, variant.options, `${framework}: values/options mismatch`);
    }
  }
});

// Test 4: Default values are preserved
test('P6.3.4: Default values preserved across frameworks', () => {
  for (const framework of FRAMEWORKS) {
    const synced = syncToFramework(MOCK_REGISTRY.variants, framework);

    const sizeVariant = synced.find(v => v.name === 'size');
    assertTrue(sizeVariant.default === 'md', `${framework}: size default should be 'md'`);

    const variantVariant = synced.find(v => v.name === 'variant');
    assertTrue(variantVariant.default === 'primary', `${framework}: variant default should be 'primary'`);
  }
});

// Test 5: SwiftUI and Jetpack Compose add enum metadata
test('P6.3.5: SwiftUI and Jetpack Compose add enum metadata', () => {
  const swiftui = syncToFramework(MOCK_REGISTRY.variants, 'swiftui');
  const jetpack = syncToFramework(MOCK_REGISTRY.variants, 'jetpack-compose');

  // SwiftUI should have enumName and enumCases
  for (const variant of swiftui) {
    assertTrue(variant.enumName !== undefined, 'SwiftUI: missing enumName');
    assertTrue(variant.enumName.endsWith('Style'), 'SwiftUI: enumName should end with Style');
    assertTrue(Array.isArray(variant.enumCases), 'SwiftUI: missing enumCases array');
  }

  // Jetpack Compose should have enumName and enumCases
  for (const variant of jetpack) {
    assertTrue(variant.enumName !== undefined, 'JetpackCompose: missing enumName');
    assertTrue(variant.enumName.endsWith('Style'), 'JetpackCompose: enumName should end with Style');
    assertTrue(Array.isArray(variant.enumCases), 'JetpackCompose: missing enumCases array');
  }
});

// Test 6: Flutter adds variant enum naming
test('P6.3.6: Flutter adds variant enum naming', () => {
  const flutter = syncToFramework(MOCK_REGISTRY.variants, 'flutter');

  for (const variant of flutter) {
    assertTrue(variant.enumName !== undefined, 'Flutter: missing enumName');
    assertTrue(variant.enumName.endsWith('Variant'), 'Flutter: enumName should end with Variant');
  }
});

// Test 7: Group 1 frameworks preserve name-based access
test('P6.3.7: Group 1 frameworks support variant.name access', () => {
  const group1 = ['react', 'vue', 'flutter', 'react-native', 'web-components'];

  for (const framework of group1) {
    const synced = syncToFramework(MOCK_REGISTRY.variants, framework);

    // Simulate Group 1 optimizer code: accessing variant.name
    for (const variant of synced) {
      const name = variant.name; // This is how Group 1 accesses it
      assertTrue(typeof name === 'string' && name.length > 0,
        `${framework}: variant.name should be non-empty string`);
    }
  }
});

// Test 8: Group 2 frameworks support property+values access
test('P6.3.8: Group 2 frameworks support property+values access', () => {
  const group2 = ['angular', 'svelte', 'swiftui', 'jetpack-compose'];

  for (const framework of group2) {
    const synced = syncToFramework(MOCK_REGISTRY.variants, framework);

    // Simulate Group 2 optimizer code: accessing variant.property and variant.values
    for (const variant of synced) {
      const property = variant.property; // This is how Group 2 accesses it
      const values = variant.values;

      assertTrue(typeof property === 'string' && property.length > 0,
        `${framework}: variant.property should be non-empty string`);
      assertTrue(Array.isArray(values),
        `${framework}: variant.values should be array`);
    }
  }
});

// Test 9: TypeScript type string preserved/inferred
test('P6.3.9: Type string preserved or inferred correctly', () => {
  for (const framework of FRAMEWORKS) {
    const synced = syncToFramework(MOCK_REGISTRY.variants, framework);

    const sizeVariant = synced.find(v => v.name === 'size');
    assertTrue(
      sizeVariant.type.includes("'sm'") && sizeVariant.type.includes("'lg'"),
      `${framework}: size type should be union type with 'sm' and 'lg'`
    );
  }
});

// Test 10: Empty variants array handled gracefully
test('P6.3.10: Empty variants array handled gracefully', () => {
  for (const framework of FRAMEWORKS) {
    const synced = syncToFramework([], framework);
    assertTrue(Array.isArray(synced), `${framework}: should return array`);
    assertTrue(synced.length === 0, `${framework}: should return empty array`);
  }
});

// Test 11: Simulate end-to-end preview generation data flow
test('P6.3.11: End-to-end preview data consistency', () => {
  // Simulate what happens when optimizer builds preview
  const buildPreviewData = (framework) => {
    const synced = syncToFramework(MOCK_REGISTRY.variants, framework);

    // All frameworks should be able to build consistent preview knobs
    return synced.map(v => ({
      knobName: v.name || v.property,
      knobOptions: v.values || v.options,
      defaultValue: v.default
    }));
  };

  const reactPreview = buildPreviewData('react');
  const angularPreview = buildPreviewData('angular');
  const swiftuiPreview = buildPreviewData('swiftui');

  // All should produce identical knob structures
  assertEqual(
    reactPreview.map(k => k.knobOptions),
    angularPreview.map(k => k.knobOptions),
    'React and Angular preview knobs mismatch'
  );

  assertEqual(
    reactPreview.map(k => k.knobOptions),
    swiftuiPreview.map(k => k.knobOptions),
    'React and SwiftUI preview knobs mismatch'
  );
});

// Test 12: Variant count matches across all frameworks
test('P6.3.12: Variant count consistent across frameworks', () => {
  const expectedCount = MOCK_REGISTRY.variants.length;

  for (const framework of FRAMEWORKS) {
    const synced = syncToFramework(MOCK_REGISTRY.variants, framework);
    assertTrue(
      synced.length === expectedCount,
      `${framework}: expected ${expectedCount} variants, got ${synced.length}`
    );
  }
});

// Summary
console.log('\n=== Test Summary ===');
console.log(`Passed: ${passed}`);
console.log(`Failed: ${failed}`);
console.log(`Total: ${passed + failed}\n`);

if (failed > 0) {
  process.exit(1);
}
