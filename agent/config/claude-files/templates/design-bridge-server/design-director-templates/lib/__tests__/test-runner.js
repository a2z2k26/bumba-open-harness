/**
 * Test Runner for Design Director Phase 1-3
 *
 * Tests utilities and templates for completeness, operability, and implementation fidelity
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

console.log('\n=== Testing Phase 1-3: Utilities & Templates ===\n');

// ============================================================================
// Test 1: Directory Structure
// ============================================================================

test('Directory structure exists', () => {
  const dirs = [
    '../../lib',
    '../../templates',
    '../../.claude/commands',
    '../../.claude/skills',
    '../../.claude/hooks'
  ];

  dirs.forEach(dir => {
    const fullPath = path.resolve(__dirname, dir);
    assert(fs.existsSync(fullPath), `Directory ${dir} should exist`);
  });
});

// ============================================================================
// Test 2: Utility Files Exist
// ============================================================================

test('All utility files exist', () => {
  const files = [
    '../bumba-reader.js',
    '../spec-generator.js',
    '../type-generator.js',
    '../export-builder.js'
  ];

  files.forEach(file => {
    const fullPath = path.resolve(__dirname, file);
    assert(fs.existsSync(fullPath), `File ${file} should exist`);
  });
});

// ============================================================================
// Test 3: Template Files Exist
// ============================================================================

test('All template files exist', () => {
  const templates = [
    'product-overview.md.tmpl',
    'product-roadmap.md.tmpl',
    'data-model.md.tmpl',
    'shell-spec.md.tmpl',
    'section-spec.md.tmpl'
  ];

  templates.forEach(template => {
    const fullPath = path.resolve(__dirname, '../../templates', template);
    assert(fs.existsSync(fullPath), `Template ${template} should exist`);
  });
});

// ============================================================================
// Test 4: bumba-reader.js - Module Exports
// ============================================================================

test('bumba-reader.js exports all required functions', () => {
  const reader = require('../bumba-reader.js');

  assert(typeof reader.readBumbaConfig === 'function', 'readBumbaConfig should be a function');
  assert(typeof reader.readBumbaTokens === 'function', 'readBumbaTokens should be a function');
  assert(typeof reader.readBumbaComponents === 'function', 'readBumbaComponents should be a function');
  assert(typeof reader.getFramework === 'function', 'getFramework should be a function');
  assert(typeof reader.getBumbaContext === 'function', 'getBumbaContext should be a function');
  assert(typeof reader.validateConfig === 'function', 'validateConfig should be a function');
});

// ============================================================================
// Test 5: bumba-reader.js - Config Validation
// ============================================================================

test('validateConfig validates correctly', () => {
  const { validateConfig } = require('../bumba-reader.js');

  // Valid config
  assert(validateConfig({
    version: '1.0.0',
    project: 'test',
    transformers: { enabled: ['react'] }
  }), 'Valid config should pass validation');

  // Invalid configs
  assert(!validateConfig({}), 'Empty config should fail validation');
  assert(!validateConfig({ version: '1.0.0' }), 'Config without project should fail');
  assert(!validateConfig({ version: '1.0.0', project: 'test' }), 'Config without transformers should fail');
});

// ============================================================================
// Test 6: bumba-reader.js - Framework Detection
// ============================================================================

test('getFramework returns correct framework', () => {
  const { getFramework } = require('../bumba-reader.js');

  // No config - should default to react
  assertEqual(getFramework(null), 'react', 'Should default to react when no config');

  // Config with preferred framework
  assertEqual(
    getFramework({ transformers: { preferred: 'vue' } }),
    'vue',
    'Should return preferred framework'
  );

  // Config with enabled frameworks
  assertEqual(
    getFramework({ transformers: { enabled: ['angular', 'react'] } }),
    'angular',
    'Should return first enabled framework'
  );

  // Config with both preferred and enabled
  assertEqual(
    getFramework({ transformers: { preferred: 'svelte', enabled: ['react'] } }),
    'svelte',
    'Should prefer preferred over enabled'
  );
});

// ============================================================================
// Test 7: bumba-reader.js - getBumbaContext Structure
// ============================================================================

test('getBumbaContext returns correct structure', () => {
  const { getBumbaContext } = require('../bumba-reader.js');

  const context = getBumbaContext();

  assert(typeof context === 'object', 'Context should be an object');
  assert('config' in context, 'Context should have config property');
  assert('tokens' in context, 'Context should have tokens property');
  assert('components' in context, 'Context should have components property');
  assert('framework' in context, 'Context should have framework property');
  assert('hasConfig' in context, 'Context should have hasConfig boolean');
  assert('hasTokens' in context, 'Context should have hasTokens boolean');
  assert('hasComponents' in context, 'Context should have hasComponents boolean');

  assert(typeof context.hasConfig === 'boolean', 'hasConfig should be boolean');
  assert(typeof context.hasTokens === 'boolean', 'hasTokens should be boolean');
  assert(typeof context.hasComponents === 'boolean', 'hasComponents should be boolean');
  assert(typeof context.framework === 'string', 'framework should be string');
});

// ============================================================================
// Test 8: spec-generator.js - Module Exports
// ============================================================================

test('spec-generator.js exports all required functions', () => {
  const generator = require('../spec-generator.js');

  assert(typeof generator.loadTemplate === 'function', 'loadTemplate should be a function');
  assert(typeof generator.generateProductOverview === 'function', 'generateProductOverview should be a function');
  assert(typeof generator.generateProductRoadmap === 'function', 'generateProductRoadmap should be a function');
  assert(typeof generator.generateDataModelSpec === 'function', 'generateDataModelSpec should be a function');
  assert(typeof generator.generateShellSpec === 'function', 'generateShellSpec should be a function');
  assert(typeof generator.generateSectionSpec === 'function', 'generateSectionSpec should be a function');
});

// ============================================================================
// Test 9: spec-generator.js - Template Loading
// ============================================================================

test('loadTemplate loads templates correctly', () => {
  const { loadTemplate } = require('../spec-generator.js');

  const template = loadTemplate('product-overview.md');
  assert(typeof template === 'function', 'Loaded template should be a function');

  // Test that template function works
  const result = template({ productName: 'Test', description: 'Test desc' });
  assert(typeof result === 'string', 'Template should return string');
  assert(result.includes('Test'), 'Template should include provided data');
});

// ============================================================================
// Test 10: spec-generator.js - Template Error Handling
// ============================================================================

test('loadTemplate throws on missing template', () => {
  const { loadTemplate } = require('../spec-generator.js');

  let errorThrown = false;
  try {
    loadTemplate('nonexistent-template.md');
  } catch (error) {
    errorThrown = true;
    assert(error.message.includes('Template not found'), 'Should throw template not found error');
  }
  assert(errorThrown, 'Should throw error for missing template');
});

// ============================================================================
// Test 11: type-generator.js - Module Exports
// ============================================================================

test('type-generator.js exports all required functions', () => {
  const typeGen = require('../type-generator.js');

  assert(typeof typeGen.generateDataModelTypes === 'function', 'generateDataModelTypes should be a function');
  assert(typeof typeGen.generateSectionTypes === 'function', 'generateSectionTypes should be a function');
  assert(typeof typeGen.inferTypeFromValue === 'function', 'inferTypeFromValue should be a function');
  assert(typeof typeGen.generateInterfaceFromJSON === 'function', 'generateInterfaceFromJSON should be a function');
});

// ============================================================================
// Test 12: type-generator.js - Type Inference
// ============================================================================

test('inferTypeFromValue infers types correctly', () => {
  const { inferTypeFromValue } = require('../type-generator.js');

  assertEqual(inferTypeFromValue('hello'), 'string', 'Should infer string');
  assertEqual(inferTypeFromValue(42), 'number', 'Should infer number');
  assertEqual(inferTypeFromValue(true), 'boolean', 'Should infer boolean');
  assertEqual(inferTypeFromValue(null), 'any', 'Should infer any for null');
  assertEqual(inferTypeFromValue(undefined), 'any', 'Should infer any for undefined');

  // Array inference
  assert(inferTypeFromValue([1, 2, 3]).includes('[]'), 'Should infer array type');

  // Date string inference
  const dateType = inferTypeFromValue('2024-01-01');
  assert(dateType.includes('Date'), 'Should infer Date for date strings');
});

// ============================================================================
// Test 13: type-generator.js - Interface Generation
// ============================================================================

test('generateInterfaceFromJSON generates valid TypeScript', () => {
  const { generateInterfaceFromJSON } = require('../type-generator.js');

  const json = {
    id: '123',
    name: 'Test',
    age: 25,
    active: true
  };

  const result = generateInterfaceFromJSON(json, 'TestInterface');

  assert(typeof result === 'string', 'Should return string');
  assert(result.includes('export interface TestInterface'), 'Should include interface declaration');
  assert(result.includes('id: string'), 'Should include id property');
  assert(result.includes('name: string'), 'Should include name property');
  assert(result.includes('age: number'), 'Should include age property');
  assert(result.includes('active: boolean'), 'Should include active property');
});

// ============================================================================
// Test 14: export-builder.js - Module Exports
// ============================================================================

test('export-builder.js exports all required functions', () => {
  const builder = require('../export-builder.js');

  assert(typeof builder.buildExportPackage === 'function', 'buildExportPackage should be a function');
  assert(typeof builder.generateExportREADME === 'function', 'generateExportREADME should be a function');
  assert(typeof builder.generatePrompts === 'function', 'generatePrompts should be a function');
  assert(typeof builder.generateInstructions === 'function', 'generateInstructions should be a function');
  assert(typeof builder.copySpecifications === 'function', 'copySpecifications should be a function');
});

// ============================================================================
// Test 15: Templates - Handlebars Syntax Validity
// ============================================================================

test('All templates have valid Handlebars syntax', () => {
  const Handlebars = require('handlebars');
  const templates = [
    'product-overview.md.tmpl',
    'product-roadmap.md.tmpl',
    'data-model.md.tmpl',
    'shell-spec.md.tmpl',
    'section-spec.md.tmpl'
  ];

  templates.forEach(template => {
    const templatePath = path.resolve(__dirname, '../../templates', template);
    const templateSource = fs.readFileSync(templatePath, 'utf-8');

    try {
      Handlebars.compile(templateSource);
    } catch (error) {
      throw new Error(`Template ${template} has invalid Handlebars syntax: ${error.message}`);
    }
  });
});

// ============================================================================
// Test 16: Templates - Required Placeholders
// ============================================================================

test('Templates contain required placeholders', () => {
  const templateChecks = [
    {
      file: 'product-overview.md.tmpl',
      required: ['{{productName}}', '{{description}}', '{{problems}}', '{{features}}', '{{framework}}']
    },
    {
      file: 'product-roadmap.md.tmpl',
      required: ['{{#each sections}}', '{{this.title}}', '{{this.id}}', '{{this.description}}']
    },
    {
      file: 'data-model.md.tmpl',
      required: ['{{#each entities}}', '{{this.name}}', '{{this.description}}', '{{#each this.attributes}}']
    },
    {
      file: 'shell-spec.md.tmpl',
      required: ['{{layoutPattern}}', '{{#each navItems}}', '{{framework}}']
    },
    {
      file: 'section-spec.md.tmpl',
      required: ['{{sectionName}}', '{{userFlows}}', '{{uiRequirements}}', '{{framework}}']
    }
  ];

  templateChecks.forEach(check => {
    const templatePath = path.resolve(__dirname, '../../templates', check.file);
    const content = fs.readFileSync(templatePath, 'utf-8');

    check.required.forEach(placeholder => {
      assert(content.includes(placeholder), `Template ${check.file} should contain ${placeholder}`);
    });
  });
});

// ============================================================================
// Test 17: Templates - Conditional Logic
// ============================================================================

test('Templates contain Bumba integration conditionals', () => {
  const productOverview = fs.readFileSync(
    path.resolve(__dirname, '../../templates/product-overview.md.tmpl'),
    'utf-8'
  );

  assert(productOverview.includes('{{#if bumbaTokensAvailable}}'), 'Should have tokens conditional');
  assert(productOverview.includes('{{else}}'), 'Should have else clause');

  const sectionSpec = fs.readFileSync(
    path.resolve(__dirname, '../../templates/section-spec.md.tmpl'),
    'utf-8'
  );

  assert(sectionSpec.includes('{{#if bumbaComponentsAvailable}}'), 'Should have components conditional');
});

// ============================================================================
// Test 18: No Stubs or TODO Comments
// ============================================================================

test('No stub implementations or TODO comments in utilities', () => {
  const files = [
    '../bumba-reader.js',
    '../spec-generator.js',
    '../type-generator.js',
    '../export-builder.js'
  ];

  files.forEach(file => {
    const fullPath = path.resolve(__dirname, file);
    const content = fs.readFileSync(fullPath, 'utf-8');

    assert(!content.includes('TODO:'), `${file} should not contain TODO comments`);
    assert(!content.includes('FIXME:'), `${file} should not contain FIXME comments`);
    assert(!content.includes('throw new Error(\'Not implemented\')'), `${file} should not have stub implementations`);
    assert(!content.includes('// stub'), `${file} should not have stub markers`);
  });
});

// ============================================================================
// Test 19: Proper Error Handling
// ============================================================================

test('Utilities have proper error handling', () => {
  const files = [
    { path: '../bumba-reader.js', shouldHave: ['try', 'catch', 'console.error', 'console.warn'] },
    { path: '../spec-generator.js', shouldHave: ['throw new Error'] },
    { path: '../type-generator.js', shouldHave: ['typeof'] },
    { path: '../export-builder.js', shouldHave: ['fs.mkdirSync', 'recursive: true'] }
  ];

  files.forEach(file => {
    const fullPath = path.resolve(__dirname, file.path);
    const content = fs.readFileSync(fullPath, 'utf-8');

    file.shouldHave.forEach(pattern => {
      assert(content.includes(pattern), `${file.path} should include ${pattern} for error handling`);
    });
  });
});

// ============================================================================
// Test 20: Module.exports Completeness
// ============================================================================

test('All modules export their functions', () => {
  const modules = [
    { path: '../bumba-reader.js', exports: 6 },
    { path: '../spec-generator.js', exports: 6 },
    { path: '../type-generator.js', exports: 4 },
    { path: '../export-builder.js', exports: 5 }
  ];

  modules.forEach(mod => {
    const fullPath = path.resolve(__dirname, mod.path);
    const content = fs.readFileSync(fullPath, 'utf-8');

    assert(content.includes('module.exports'), `${mod.path} should have module.exports`);

    const exported = require(mod.path);
    const exportCount = Object.keys(exported).length;

    assertEqual(exportCount, mod.exports, `${mod.path} should export ${mod.exports} functions, got ${exportCount}`);
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
    console.log(`  ✗ ${t.name}: ${t.error}`);
  });
  process.exit(1);
} else {
  console.log('\n✓ All tests passed!\n');
  process.exit(0);
}
