/**
 * variant-sync.test.js
 * Tests for P6 Cross-Framework Variant Synchronization
 */

const {
  normalizeVariant,
  normalizeVariants,
  syncToFramework,
  validateVariants,
  mergeVariants,
  inferTypeFromValues,
  toTitleCase,
  toEnumCase
} = require('./variant-sync');

// Test data representing different source formats
const FIGMA_VARIANT_DEF = {
  name: 'Size',
  type: 'variant',
  options: ['sm', 'md', 'lg'],
  default: 'md'
};

const FIGMA_PROP_STYLE = {
  name: 'size',
  type: "'sm' | 'md' | 'lg'",
  values: ['sm', 'md', 'lg'],
  required: false,
  default: "'md'"
};

const ANGULAR_STYLE_VARIANT = {
  property: 'size',
  values: ['small', 'medium', 'large']
};

const REACT_NAME_ONLY = {
  name: 'variant',
  props: { primary: true }
};

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

console.log('\\n=== P6 Variant Sync Tests ===\\n');

// Test 1: Normalize Figma variant definition
test('P6.1: normalizeVariant handles Figma variant definition', () => {
  const result = normalizeVariant(FIGMA_VARIANT_DEF);

  assertTrue(result.name === 'Size', 'name should be Size');
  assertTrue(result.property === 'Size', 'property should mirror name');
  assertEqual(result.values, ['sm', 'md', 'lg'], 'values should come from options');
  assertEqual(result.options, ['sm', 'md', 'lg'], 'options should be preserved');
  assertTrue(result.default === 'md', 'default should be md');
});

// Test 2: Normalize Figma props format (P7 style)
test('P6.2: normalizeVariant handles P7 props format with values array', () => {
  const result = normalizeVariant(FIGMA_PROP_STYLE);

  assertTrue(result.name === 'size', 'name should be size');
  assertTrue(result.property === 'size', 'property should mirror name');
  assertEqual(result.values, ['sm', 'md', 'lg'], 'values should be extracted');
  assertTrue(result.default === 'md', 'default should strip quotes');
});

// Test 3: Normalize Angular/Svelte property format
test('P6.3: normalizeVariant handles Angular property+values format', () => {
  const result = normalizeVariant(ANGULAR_STYLE_VARIANT);

  assertTrue(result.name === 'size', 'name should come from property');
  assertTrue(result.property === 'size', 'property should be size');
  assertEqual(result.values, ['small', 'medium', 'large'], 'values should be preserved');
  assertTrue(result.default === 'small', 'default should be first value');
});

// Test 4: Handle minimal React format
test('P6.4: normalizeVariant handles minimal React format', () => {
  const result = normalizeVariant(REACT_NAME_ONLY);

  assertTrue(result.name === 'variant', 'name should be variant');
  assertTrue(result.property === 'variant', 'property should mirror name');
  assertEqual(result.values, [], 'values should be empty array');
  assertEqual(result.props, { primary: true }, 'props should be preserved');
});

// Test 5: normalizeVariants array processing
test('P6.5: normalizeVariants processes array correctly', () => {
  const result = normalizeVariants([FIGMA_VARIANT_DEF, ANGULAR_STYLE_VARIANT]);

  assertTrue(result.length === 2, 'should have 2 variants');
  assertTrue(result[0].name === 'Size', 'first variant should be Size');
  assertTrue(result[1].name === 'size', 'second variant should be size');
});

// Test 6: Handle null/undefined/invalid input
test('P6.6: normalizeVariant handles edge cases gracefully', () => {
  assertTrue(normalizeVariant(null) === null, 'null returns null');
  assertTrue(normalizeVariant(undefined) === null, 'undefined returns null');
  assertEqual(normalizeVariants([]), [], 'empty array returns empty array');
  assertEqual(normalizeVariants(null), [], 'null array returns empty array');
});

// Test 7: syncToFramework for React (Group 1)
test('P6.7: syncToFramework for React preserves normalized format', () => {
  const variants = [FIGMA_VARIANT_DEF];
  const result = syncToFramework(variants, 'react');

  assertTrue(result.length === 1, 'should have 1 variant');
  assertTrue(result[0].name === 'Size', 'name should be Size');
  assertTrue(result[0].property === 'Size', 'property should be Size');
});

// Test 8: syncToFramework for SwiftUI (Group 2)
test('P6.8: syncToFramework for SwiftUI adds enum metadata', () => {
  const variants = [FIGMA_VARIANT_DEF];
  const result = syncToFramework(variants, 'swiftui');

  assertTrue(result.length === 1, 'should have 1 variant');
  assertTrue(result[0].enumName === 'SizeStyle', 'enumName should be SizeStyle');
  assertEqual(result[0].enumCases, ['sm', 'md', 'lg'], 'enumCases should be array');
});

// Test 9: syncToFramework for Flutter
test('P6.9: syncToFramework for Flutter adds enum naming', () => {
  const variants = [FIGMA_VARIANT_DEF];
  const result = syncToFramework(variants, 'flutter');

  assertTrue(result[0].enumName === 'SizeVariant', 'enumName should be SizeVariant');
});

// Test 10: validateVariants
test('P6.10: validateVariants detects missing fields', () => {
  const valid = [{ name: 'Size', values: ['sm', 'md'] }];
  const invalid = [{ styles: {} }]; // missing name/property and values

  const validResult = validateVariants(valid);
  const invalidResult = validateVariants(invalid);

  assertTrue(validResult.valid === true, 'valid variants should pass');
  assertTrue(invalidResult.valid === false, 'invalid variants should fail');
  assertTrue(invalidResult.errors.length > 0, 'should have error messages');
});

// Test 11: mergeVariants deduplication
test('P6.11: mergeVariants merges and deduplicates', () => {
  const source1 = [{ name: 'Size', options: ['sm', 'md'] }];
  const source2 = [{ name: 'Size', options: ['sm', 'md', 'lg', 'xl'] }];
  const source3 = [{ name: 'Color', options: ['red', 'blue'] }];

  const result = mergeVariants(source1, source2, source3);

  assertTrue(result.length === 2, 'should have 2 unique variants');
  const sizeVariant = result.find(v => v.name === 'Size');
  assertTrue(sizeVariant.values.length === 4, 'Size should have 4 values (prefer more complete)');
});

// Test 12: inferTypeFromValues
test('P6.12: inferTypeFromValues generates correct types', () => {
  assertEqual(inferTypeFromValues(['sm', 'md', 'lg']), "'sm' | 'md' | 'lg'", 'union type');
  assertEqual(inferTypeFromValues(['true', 'false']), 'boolean', 'boolean detection');
  assertEqual(inferTypeFromValues([]), 'string', 'empty defaults to string');
});

// Test 13: Type extraction from union string
test('P6.13: normalizeVariant extracts values from type union string', () => {
  const variant = {
    name: 'intent',
    type: "'primary' | 'secondary' | 'danger'"
  };

  const result = normalizeVariant(variant);
  assertEqual(result.values, ['primary', 'secondary', 'danger'], 'values from type string');
});

// Test 14: toEnumCase utility
test('P6.14: toEnumCase generates valid enum identifiers', () => {
  assertEqual(toEnumCase('Small'), 'small', 'lowercase');
  assertEqual(toEnumCase('extra-large'), 'extra_large', 'hyphen to underscore');
  assertEqual(toEnumCase('100%'), '100', 'remove special chars');
  assertEqual(toEnumCase('  spaced  '), 'spaced', 'trim underscores');
});

// Test 15: Cross-framework consistency
test('P6.15: All frameworks receive same variant values', () => {
  const frameworks = ['react', 'vue', 'flutter', 'angular', 'svelte', 'swiftui', 'jetpack-compose'];
  const variants = [FIGMA_VARIANT_DEF];

  const results = frameworks.map(fw => syncToFramework(variants, fw));

  // All should have the same values array
  const allHaveSameValues = results.every(r =>
    JSON.stringify(r[0].values) === JSON.stringify(['sm', 'md', 'lg'])
  );

  assertTrue(allHaveSameValues, 'All frameworks should have identical values array');
});

// Summary
console.log('\\n=== Test Summary ===');
console.log(`Passed: ${passed}`);
console.log(`Failed: ${failed}`);
console.log(`Total: ${passed + failed}\\n`);

if (failed > 0) {
  process.exit(1);
}
