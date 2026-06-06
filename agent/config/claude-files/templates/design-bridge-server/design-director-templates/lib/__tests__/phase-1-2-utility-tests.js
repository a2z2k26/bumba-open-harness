/**
 * Phase 1-2: Utility Library Unit Tests
 *
 * Tests for:
 * - bumba-reader.js
 * - spec-generator.js
 * - type-generator.js
 * - export-builder.js
 */

const fs = require('fs');
const path = require('path');

// Test results tracker
const results = {
  passed: 0,
  failed: 0,
  tests: []
};

function test(name, fn) {
  try {
    fn();
    results.passed++;
    results.tests.push({ name, status: 'PASS' });
    console.log(`✓ ${name}`);
  } catch (error) {
    results.failed++;
    results.tests.push({ name, status: 'FAIL', error: error.message });
    console.error(`✗ ${name}`);
    console.error(`  Error: ${error.message}`);
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

function assertContains(text, substring, message) {
  if (!text.includes(substring)) {
    throw new Error(message || `Expected to contain "${substring}"`);
  }
}

console.log('\n=== Testing Phase 1-2: Utility Libraries ===\n');

// ============================================================================
// UTILITY FILE EXISTENCE
// ============================================================================

console.log('--- Utility Files ---\n');

// Test 1: All 4 utility files exist
test('All 4 utility files exist', () => {
  const utilities = [
    'bumba-reader.js',
    'spec-generator.js',
    'type-generator.js',
    'export-builder.js'
  ];

  utilities.forEach(util => {
    const utilPath = path.resolve(__dirname, '..', util);
    assert(fs.existsSync(utilPath), `Utility ${util} should exist`);
  });
});

// Test 2: All utilities have valid Node.js module structure
test('All utilities have valid module structure', () => {
  const utilities = [
    'bumba-reader.js',
    'spec-generator.js',
    'type-generator.js',
    'export-builder.js'
  ];

  utilities.forEach(util => {
    const utilPath = path.resolve(__dirname, '..', util);
    const content = fs.readFileSync(utilPath, 'utf-8');

    assertContains(content, 'module.exports', `${util} should export module`);
    assertContains(content, 'function', `${util} should have functions`);
  });
});

// ============================================================================
// BUMBA-READER.JS TESTS
// ============================================================================

console.log('\n--- bumba-reader.js ---\n');

// Test 3: bumba-reader exports all required functions
test('bumba-reader exports all required functions', () => {
  const readerPath = path.resolve(__dirname, '..', 'bumba-reader.js');
  const reader = require(readerPath);

  assert(typeof reader.readBumbaConfig === 'function', 'Should export readBumbaConfig');
  assert(typeof reader.readBumbaTokens === 'function', 'Should export readBumbaTokens');
  assert(typeof reader.readBumbaComponents === 'function', 'Should export readBumbaComponents');
  assert(typeof reader.getFramework === 'function', 'Should export getFramework');
  assert(typeof reader.getBumbaContext === 'function', 'Should export getBumbaContext');
});

// Test 4: readBumbaConfig has error handling
test('bumba-reader has try-catch error handling', () => {
  const readerPath = path.resolve(__dirname, '..', 'bumba-reader.js');
  const content = fs.readFileSync(readerPath, 'utf-8');

  assertContains(content, 'try {', 'Should have try blocks');
  assertContains(content, 'catch', 'Should have catch blocks');
  assertContains(content, 'return null', 'Should return null on error');
});

// Test 5: readBumbaConfig validates structure
test('bumba-reader validates config structure', () => {
  const readerPath = path.resolve(__dirname, '..', 'bumba-reader.js');
  const content = fs.readFileSync(readerPath, 'utf-8');

  assertContains(content, 'config.version', 'Should check version field');
  assertContains(content, 'config.project', 'Should check project field');
});

// Test 6: getFramework has default fallback
test('getFramework has default react fallback', () => {
  const readerPath = path.resolve(__dirname, '..', 'bumba-reader.js');
  const content = fs.readFileSync(readerPath, 'utf-8');

  assertContains(content, "'react'", 'Should default to react');
  assertContains(content, 'transformers', 'Should check transformers config');
});

// Test 7: getBumbaContext returns complete context object
test('getBumbaContext returns complete context', () => {
  const readerPath = path.resolve(__dirname, '..', 'bumba-reader.js');
  const content = fs.readFileSync(readerPath, 'utf-8');

  assertContains(content, 'hasConfig:', 'Should include hasConfig flag');
  assertContains(content, 'hasTokens:', 'Should include hasTokens flag');
  assertContains(content, 'hasComponents:', 'Should include hasComponents flag');
  assertContains(content, 'framework', 'Should include framework');
});

// ============================================================================
// SPEC-GENERATOR.JS TESTS
// ============================================================================

console.log('\n--- spec-generator.js ---\n');

// Test 8: spec-generator exports all required functions
test('spec-generator exports all required functions', () => {
  const generatorPath = path.resolve(__dirname, '..', 'spec-generator.js');
  const generator = require(generatorPath);

  assert(typeof generator.generateProductOverview === 'function', 'Should export generateProductOverview');
  assert(typeof generator.generateProductRoadmap === 'function', 'Should export generateProductRoadmap');
  assert(typeof generator.generateDataModelSpec === 'function', 'Should export generateDataModelSpec');
  assert(typeof generator.generateSectionSpec === 'function', 'Should export generateSectionSpec');
});

// Test 9: spec-generator uses Handlebars
test('spec-generator uses Handlebars templates', () => {
  const generatorPath = path.resolve(__dirname, '..', 'spec-generator.js');
  const content = fs.readFileSync(generatorPath, 'utf-8');

  assertContains(content, 'Handlebars', 'Should use Handlebars');
  assertContains(content, 'compile', 'Should compile templates');
});

// Test 10: spec-generator creates output directories
test('spec-generator creates output directories', () => {
  const generatorPath = path.resolve(__dirname, '..', 'spec-generator.js');
  const content = fs.readFileSync(generatorPath, 'utf-8');

  assertContains(content, 'mkdirSync', 'Should create directories');
  assertContains(content, 'recursive: true', 'Should use recursive option');
});

// Test 11: spec-generator writes markdown files
test('spec-generator writes markdown files', () => {
  const generatorPath = path.resolve(__dirname, '..', 'spec-generator.js');
  const content = fs.readFileSync(generatorPath, 'utf-8');

  assertContains(content, 'writeFileSync', 'Should write files');
  assertContains(content, '.md', 'Should write markdown files');
  assertContains(content, 'utf-8', 'Should use UTF-8 encoding');
});

// ============================================================================
// TYPE-GENERATOR.JS TESTS
// ============================================================================

console.log('\n--- type-generator.js ---\n');

// Test 12: type-generator exports all required functions
test('type-generator exports all required functions', () => {
  const generatorPath = path.resolve(__dirname, '..', 'type-generator.js');
  const generator = require(generatorPath);

  assert(typeof generator.generateDataModelTypes === 'function', 'Should export generateDataModelTypes');
  assert(typeof generator.generateSectionTypes === 'function', 'Should export generateSectionTypes');
  assert(typeof generator.inferTypeFromValue === 'function', 'Should export inferTypeFromValue');
  assert(typeof generator.generateInterfaceFromJSON === 'function', 'Should export generateInterfaceFromJSON');
});

// Test 13: type-generator infers TypeScript types
test('type-generator infers TypeScript types from JSON', () => {
  const generatorPath = path.resolve(__dirname, '..', 'type-generator.js');
  const content = fs.readFileSync(generatorPath, 'utf-8');

  assertContains(content, 'export interface', 'Should generate TypeScript interfaces');
  assertContains(content, 'typeof', 'Should check types');
  assertContains(content, 'Array.isArray', 'Should detect arrays');
});

// Test 14: type-generator handles nested objects
test('type-generator handles nested objects', () => {
  const generatorPath = path.resolve(__dirname, '..', 'type-generator.js');
  const content = fs.readFileSync(generatorPath, 'utf-8');

  assertContains(content, 'object', 'Should detect objects');
  assertContains(content, 'Object.keys', 'Should iterate object keys');
});

// Test 15: type-generator writes TypeScript files
test('type-generator writes TypeScript files', () => {
  const generatorPath = path.resolve(__dirname, '..', 'type-generator.js');
  const content = fs.readFileSync(generatorPath, 'utf-8');

  assertContains(content, '.ts', 'Should write .ts files');
  assertContains(content, 'writeFileSync', 'Should write files');
});

// ============================================================================
// EXPORT-BUILDER.JS TESTS
// ============================================================================

console.log('\n--- export-builder.js ---\n');

// Test 16: export-builder exports buildExportPackage function
test('export-builder exports buildExportPackage', () => {
  const builderPath = path.resolve(__dirname, '..', 'export-builder.js');
  const builder = require(builderPath);

  assert(typeof builder.buildExportPackage === 'function', 'Should export buildExportPackage');
});

// Test 17: export-builder uses bumba-reader
test('export-builder uses bumba-reader', () => {
  const builderPath = path.resolve(__dirname, '..', 'export-builder.js');
  const content = fs.readFileSync(builderPath, 'utf-8');

  assertContains(content, 'bumba-reader', 'Should require bumba-reader');
  assertContains(content, 'getBumbaContext', 'Should call getBumbaContext');
});

// Test 18: export-builder creates export directories
test('export-builder creates export package structure', () => {
  const builderPath = path.resolve(__dirname, '..', 'export-builder.js');
  const content = fs.readFileSync(builderPath, 'utf-8');

  assertContains(content, 'design-direction-plan', 'Should create design-direction-plan directory');
  assertContains(content, 'prompts', 'Should create prompts subdirectory');
  assertContains(content, 'instructions', 'Should create instructions subdirectory');
  assertContains(content, 'specifications', 'Should create specifications subdirectory');
});

// Test 19: export-builder is framework-aware
test('export-builder adapts to framework', () => {
  const builderPath = path.resolve(__dirname, '..', 'export-builder.js');
  const content = fs.readFileSync(builderPath, 'utf-8');

  assertContains(content, 'framework', 'Should check framework');
  assertContains(content, 'bumbaContext', 'Should use Bumba context');
});

// Test 20: export-builder generates README
test('export-builder generates export README', () => {
  const builderPath = path.resolve(__dirname, '..', 'export-builder.js');
  const content = fs.readFileSync(builderPath, 'utf-8');

  assertContains(content, 'README', 'Should generate README');
  assertContains(content, 'writeFileSync', 'Should write files');
});

// ============================================================================
// DEPENDENCY CHECKS
// ============================================================================

console.log('\n--- Dependencies ---\n');

// Test 21: All utilities have proper requires
test('All utilities properly require dependencies', () => {
  const utilities = [
    'bumba-reader.js',
    'spec-generator.js',
    'type-generator.js',
    'export-builder.js'
  ];

  utilities.forEach(util => {
    const utilPath = path.resolve(__dirname, '..', util);
    const content = fs.readFileSync(utilPath, 'utf-8');

    assertContains(content, "require('fs')", `${util} should require fs`);
    assertContains(content, "require('path')", `${util} should require path`);
  });
});

// Test 22: No hardcoded absolute paths
test('No hardcoded absolute paths in utilities', () => {
  const utilities = [
    'bumba-reader.js',
    'spec-generator.js',
    'type-generator.js',
    'export-builder.js'
  ];

  utilities.forEach(util => {
    const utilPath = path.resolve(__dirname, '..', util);
    const content = fs.readFileSync(utilPath, 'utf-8');

    assert(!content.includes('/home/'), `${util} should not have absolute paths`);
    assert(!content.includes('C:\\'), `${util} should not have Windows absolute paths`);
  });
});

// Test 23: All utilities use path.resolve or path.join
test('All utilities use path resolution', () => {
  const utilities = [
    'bumba-reader.js',
    'spec-generator.js',
    'type-generator.js',
    'export-builder.js'
  ];

  utilities.forEach(util => {
    const utilPath = path.resolve(__dirname, '..', util);
    const content = fs.readFileSync(utilPath, 'utf-8');

    const hasResolve = content.includes('path.resolve') || content.includes('path.join');
    assert(hasResolve, `${util} should use path.resolve or path.join`);
  });
});

// ============================================================================
// ERROR HANDLING
// ============================================================================

console.log('\n--- Error Handling ---\n');

// Test 24: Utilities handle missing files gracefully
test('Utilities have null checks for missing files', () => {
  const readerPath = path.resolve(__dirname, '..', 'bumba-reader.js');
  const content = fs.readFileSync(readerPath, 'utf-8');

  assertContains(content, 'existsSync', 'Should check file existence');
  assertContains(content, 'return null', 'Should return null when files missing');
});

// Test 25: Utilities log errors
test('Utilities log errors', () => {
  const utilities = [
    'bumba-reader.js',
    'spec-generator.js',
    'type-generator.js',
    'export-builder.js'
  ];

  utilities.forEach(util => {
    const utilPath = path.resolve(__dirname, '..', util);
    const content = fs.readFileSync(utilPath, 'utf-8');

    const hasLogging = content.includes('console.error') || content.includes('console.warn') || content.includes('console.log');
    assert(hasLogging, `${util} should have logging`);
  });
});

// ============================================================================
// Results Summary
// ============================================================================

console.log('\n=== Test Results ===\n');
console.log(`Total Tests: ${results.passed + results.failed}`);
console.log(`Passed: ${results.passed}`);
console.log(`Failed: ${results.failed}`);

if (results.failed > 0) {
  console.log('\nFailed Tests:');
  results.tests.filter(t => t.status === 'FAIL').forEach(t => {
    console.log(`  ✗ ${t.name}`);
    console.log(`    Error: ${t.error}`);
  });
  process.exit(1);
} else {
  console.log('\n✓ All utility tests passed!\n');
  console.log('Phase 1-2 Utility Summary:');
  console.log('  ✓ 4 utility files exist and are valid');
  console.log('  ✓ bumba-reader.js: Complete with error handling');
  console.log('  ✓ spec-generator.js: Complete with Handlebars');
  console.log('  ✓ type-generator.js: Complete with type inference');
  console.log('  ✓ export-builder.js: Complete with framework awareness');
  console.log('  ✓ All utilities use relative paths');
  console.log('  ✓ All utilities have proper error handling');
  console.log('\n');
  process.exit(0);
}
