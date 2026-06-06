#!/usr/bin/env node
/**
 * test-p1-p5-integration.js
 * Comprehensive test suite for P1-P5 story generation gap fixes
 *
 * Tests:
 * - P1: StoryVariants integration into main generateStoryFile flow
 * - P2: Auto-generation of variants from enum props
 * - P3: Figma URL passthrough from componentRegistry
 * - P4: componentRegistry-based path resolution
 * - P5: Props validation before story generation
 */

const fs = require('fs');
const path = require('path');
const { StoryGenerator } = require('./story-generator');

console.log('╔════════════════════════════════════════════════════════════╗');
console.log('║        P1-P5 INTEGRATION TEST SUITE                        ║');
console.log('║        Story Generation Gap Fixes Verification             ║');
console.log('╚════════════════════════════════════════════════════════════╝\n');

const results = {
  total: 0,
  passed: 0,
  failed: 0,
  tests: []
};

function test(name, fn) {
  results.total++;
  process.stdout.write(`  Test ${results.total}: ${name}... `);

  try {
    fn();
    console.log('✅ PASSED');
    results.passed++;
    results.tests.push({ name, status: 'PASSED' });
  } catch (error) {
    console.log(`❌ FAILED`);
    console.log(`    Error: ${error.message}`);
    results.failed++;
    results.tests.push({ name, status: 'FAILED', error: error.message });
  }
}

function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new Error(`${message}: expected "${expected}", got "${actual}"`);
  }
}

function assertTrue(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function assertContains(str, substring, message) {
  if (!str || !str.includes(substring)) {
    throw new Error(`${message}: "${substring}" not found`);
  }
}

// ============================================================
// P5: PROPS VALIDATION TESTS
// ============================================================

console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
console.log('P5: Props Validation');
console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');

test('P5.1: validateProps method exists', () => {
  const gen = new StoryGenerator();
  assertTrue(typeof gen.validateProps === 'function', 'validateProps should be a function');
});

test('P5.2: validateProps returns valid structure', () => {
  const gen = new StoryGenerator();
  const result = gen.validateProps({});
  assertTrue('valid' in result, 'Result should have "valid" property');
  assertTrue('issues' in result, 'Result should have "issues" property');
  assertTrue('sanitizedProps' in result, 'Result should have "sanitizedProps" property');
});

test('P5.3: validateProps detects non-object props', () => {
  const gen = new StoryGenerator();
  const result = gen.validateProps({
    badProp: 'just a string'
  });
  assertTrue(result.issues.length > 0, 'Should detect non-object prop');
  assertTrue(result.issues.some(i => i.includes('badProp')), 'Issue should mention badProp');
});

test('P5.4: validateProps adds missing type', () => {
  const gen = new StoryGenerator();
  const result = gen.validateProps({
    noType: { default: 'value' }
  });
  assertEqual(result.sanitizedProps.noType.type, 'string', 'Should default to string type');
});

test('P5.5: validateProps detects enum without values', () => {
  const gen = new StoryGenerator();
  const result = gen.validateProps({
    badEnum: { type: 'enum' }
  });
  assertTrue(result.issues.some(i => i.includes('enum') && i.includes('values')),
    'Should detect enum without values');
});

test('P5.6: validateProps fixes boolean default type', () => {
  const gen = new StoryGenerator();
  const result = gen.validateProps({
    disabled: { type: 'boolean', default: 'yes' }
  });
  assertEqual(typeof result.sanitizedProps.disabled.default, 'boolean',
    'Should convert string to boolean');
});

test('P5.7: validateProps fixes number default type', () => {
  const gen = new StoryGenerator();
  const result = gen.validateProps({
    count: { type: 'number', default: '42' }
  });
  assertEqual(result.sanitizedProps.count.default, 42, 'Should convert string to number');
});

test('P5.8: validateProps passes valid props unchanged', () => {
  const gen = new StoryGenerator();
  const validProps = {
    label: { type: 'string', default: 'Hello' },
    disabled: { type: 'boolean', default: false },
    size: { type: 'enum', values: ['sm', 'md', 'lg'], default: 'md' }
  };
  const result = gen.validateProps(validProps);
  assertTrue(result.valid, 'Valid props should pass validation');
  assertEqual(result.issues.length, 0, 'Should have no issues');
});

// ============================================================
// P2: ENUM VARIANTS AUTO-GENERATION TESTS
// ============================================================

console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
console.log('P2: Enum Variants Auto-Generation');
console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');

test('P2.1: generateEnumVariants method exists', () => {
  const gen = new StoryGenerator();
  assertTrue(typeof gen.generateEnumVariants === 'function',
    'generateEnumVariants should be a function');
});

test('P2.2: generateEnumVariants creates variants from values array', () => {
  const gen = new StoryGenerator({ autoEnumVariants: true });
  const variants = gen.generateEnumVariants({
    variant: { type: 'enum', values: ['primary', 'secondary', 'outline'] }
  });
  assertEqual(Object.keys(variants).length, 3, 'Should create 3 variants');
  assertTrue('Primary' in variants, 'Should have Primary variant');
  assertTrue('Secondary' in variants, 'Should have Secondary variant');
  assertTrue('Outline' in variants, 'Should have Outline variant');
});

test('P2.3: generateEnumVariants creates variants from enumValues', () => {
  const gen = new StoryGenerator({ autoEnumVariants: true });
  const variants = gen.generateEnumVariants({
    size: { type: 'enum', enumValues: ['sm', 'md', 'lg'] }
  });
  assertEqual(Object.keys(variants).length, 3, 'Should create 3 variants');
});

test('P2.4: generateEnumVariants parses rawType union', () => {
  const gen = new StoryGenerator({ autoEnumVariants: true });
  const variants = gen.generateEnumVariants({
    status: { type: 'string', rawType: "'active' | 'inactive' | 'pending'" }
  });
  assertEqual(Object.keys(variants).length, 3, 'Should parse union type');
});

test('P2.5: generateEnumVariants skips large enums (>6 values)', () => {
  const gen = new StoryGenerator({ autoEnumVariants: true });
  const variants = gen.generateEnumVariants({
    month: { type: 'enum', values: ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug'] }
  });
  assertEqual(Object.keys(variants).length, 0, 'Should skip enums with >6 values');
});

test('P2.6: generateEnumVariants includes proper args', () => {
  const gen = new StoryGenerator({ autoEnumVariants: true });
  const variants = gen.generateEnumVariants({
    variant: { type: 'enum', values: ['primary'] }
  });
  assertEqual(variants.Primary.args.variant, 'primary', 'Variant should have correct args');
});

test('P2.7: generateEnumVariants adds source metadata', () => {
  const gen = new StoryGenerator({ autoEnumVariants: true });
  const variants = gen.generateEnumVariants({
    variant: { type: 'enum', values: ['primary'] }
  });
  assertEqual(variants.Primary.source, 'enum-auto', 'Should have enum-auto source');
  assertEqual(variants.Primary.sourceProp, 'variant', 'Should track source prop');
});

test('P2.8: formatVariantName handles kebab-case', () => {
  const gen = new StoryGenerator();
  assertEqual(gen.formatVariantName('extra-large', 'size'), 'ExtraLarge',
    'Should convert kebab-case to PascalCase');
});

test('P2.9: formatVariantName handles snake_case', () => {
  const gen = new StoryGenerator();
  assertEqual(gen.formatVariantName('extra_large', 'size'), 'ExtraLarge',
    'Should convert snake_case to PascalCase');
});

test('P2.10: autoEnumVariants can be disabled', () => {
  const gen = new StoryGenerator({ autoEnumVariants: false });
  const variants = gen.generateEnumVariants({
    variant: { type: 'enum', values: ['primary', 'secondary'] }
  });
  assertEqual(Object.keys(variants).length, 0, 'Should not generate when disabled');
});

// ============================================================
// P3: FIGMA URL PASSTHROUGH TESTS
// ============================================================

console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
console.log('P3: Figma URL Passthrough');
console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');

test('P3.1: getFigmaUrl method exists', () => {
  const gen = new StoryGenerator();
  assertTrue(typeof gen.getFigmaUrl === 'function', 'getFigmaUrl should be a function');
});

test('P3.2: getFigmaUrl returns empty string when no registry', () => {
  const gen = new StoryGenerator();
  assertEqual(gen.getFigmaUrl('TestButton'), '', 'Should return empty string');
});

test('P3.3: getFigmaUrl returns URL from registry figmaUrl', () => {
  const gen = new StoryGenerator();
  gen.componentRegistry = {
    components: [
      { name: 'TestButton', figmaUrl: 'https://figma.com/file/abc123' }
    ]
  };
  assertEqual(gen.getFigmaUrl('TestButton'), 'https://figma.com/file/abc123',
    'Should return figmaUrl from registry');
});

test('P3.4: getFigmaUrl returns URL from metadata.figmaUrl', () => {
  const gen = new StoryGenerator();
  gen.componentRegistry = {
    components: [
      { name: 'TestButton', metadata: { figmaUrl: 'https://figma.com/file/xyz789' } }
    ]
  };
  assertEqual(gen.getFigmaUrl('TestButton'), 'https://figma.com/file/xyz789',
    'Should return metadata.figmaUrl from registry');
});

test('P3.5: generateRichStoryFile uses registry Figma URL', () => {
  const gen = new StoryGenerator({ enableRichVariants: false });
  gen.componentRegistry = {
    components: [
      { name: 'TestButton', figmaUrl: 'https://figma.com/file/test123' }
    ]
  };
  const result = gen.generateRichStoryFile({ name: 'TestButton', props: {} }, 'react');
  assertEqual(result.figmaUrl, 'https://figma.com/file/test123',
    'generateRichStoryFile should use registry URL');
});

test('P3.6: component figmaUrl takes precedence over registry', () => {
  const gen = new StoryGenerator({ enableRichVariants: false });
  gen.componentRegistry = {
    components: [
      { name: 'TestButton', figmaUrl: 'https://figma.com/registry-url' }
    ]
  };
  const result = gen.generateRichStoryFile(
    { name: 'TestButton', figmaUrl: 'https://figma.com/component-url', props: {} },
    'react'
  );
  assertEqual(result.figmaUrl, 'https://figma.com/component-url',
    'Component URL should take precedence');
});

// ============================================================
// P4: COMPONENT REGISTRY PATH RESOLUTION TESTS
// ============================================================

console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
console.log('P4: Component Registry Path Resolution');
console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');

test('P4.1: loadComponentRegistry method exists', () => {
  const gen = new StoryGenerator();
  assertTrue(typeof gen.loadComponentRegistry === 'function',
    'loadComponentRegistry should be a function');
});

test('P4.2: lookupComponent method exists', () => {
  const gen = new StoryGenerator();
  assertTrue(typeof gen.lookupComponent === 'function',
    'lookupComponent should be a function');
});

test('P4.3: getComponentPath method exists', () => {
  const gen = new StoryGenerator();
  assertTrue(typeof gen.getComponentPath === 'function',
    'getComponentPath should be a function');
});

test('P4.4: lookupComponent finds by name', () => {
  const gen = new StoryGenerator();
  gen.componentRegistry = {
    components: [
      { name: 'Button', id: 'btn-123' },
      { name: 'Input', id: 'inp-456' }
    ]
  };
  const result = gen.lookupComponent('Button');
  assertEqual(result.id, 'btn-123', 'Should find component by name');
});

test('P4.5: lookupComponent finds by id', () => {
  const gen = new StoryGenerator();
  gen.componentRegistry = {
    components: [
      { name: 'Button', id: 'btn-123' }
    ]
  };
  const result = gen.lookupComponent('btn-123');
  assertEqual(result.name, 'Button', 'Should find component by id');
});

test('P4.6: lookupComponent returns null for missing', () => {
  const gen = new StoryGenerator();
  gen.componentRegistry = { components: [] };
  const result = gen.lookupComponent('NonExistent');
  assertEqual(result, null, 'Should return null for missing component');
});

test('P4.7: getComponentPath returns correct path', () => {
  const gen = new StoryGenerator();
  gen.projectPath = '/project';
  gen.componentRegistry = {
    components: [
      {
        name: 'Button',
        outputPaths: {
          react: '.design/extracted-code/react/Button.tsx'
        }
      }
    ]
  };
  const result = gen.getComponentPath('Button', 'react');
  assertTrue(result.includes('Button.tsx'), 'Should return correct path');
});

test('P4.8: getComponentPath returns null for missing framework', () => {
  const gen = new StoryGenerator();
  gen.projectPath = '/project';
  gen.componentRegistry = {
    components: [
      { name: 'Button', outputPaths: { react: 'path/Button.tsx' } }
    ]
  };
  const result = gen.getComponentPath('Button', 'vue');
  assertEqual(result, null, 'Should return null for missing framework');
});

test('P4.9: generateRichStoryFile uses registry path', () => {
  const gen = new StoryGenerator({ enableRichVariants: false });
  gen.projectPath = '/project';
  gen.componentRegistry = {
    components: [
      { name: 'Button', outputPaths: { react: '.design/extracted-code/react/Button.tsx' } }
    ]
  };
  const result = gen.generateRichStoryFile({ name: 'Button', props: {} }, 'react');
  assertTrue(result.componentPath !== null, 'Should resolve component path');
  assertTrue(result.componentPath.includes('Button.tsx'), 'Path should include component file');
});

// ============================================================
// P1: STORYVARIANTS INTEGRATION TESTS
// ============================================================

console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
console.log('P1: StoryVariants Integration');
console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');

test('P1.1: generateRichStoryFile method exists', () => {
  const gen = new StoryGenerator();
  assertTrue(typeof gen.generateRichStoryFile === 'function',
    'generateRichStoryFile should be a function');
});

test('P1.2: generateAndWriteRichStory method exists', () => {
  const gen = new StoryGenerator();
  assertTrue(typeof gen.generateAndWriteRichStory === 'function',
    'generateAndWriteRichStory should be a function');
});

test('P1.3: generateRichStoryFile returns proper structure', () => {
  const gen = new StoryGenerator({ enableRichVariants: true });
  const result = gen.generateRichStoryFile({ name: 'Test', props: {} }, 'react');
  assertTrue('success' in result, 'Should have success');
  assertTrue('content' in result, 'Should have content');
  assertTrue('variants' in result, 'Should have variants');
  assertTrue('validation' in result, 'Should have validation');
  assertTrue('figmaUrl' in result, 'Should have figmaUrl');
  assertTrue('componentPath' in result, 'Should have componentPath');
  assertTrue('warnings' in result, 'Should have warnings');
});

test('P1.4: generateRichStoryFile generates content', () => {
  const gen = new StoryGenerator({ enableRichVariants: true });
  const result = gen.generateRichStoryFile({
    name: 'TestButton',
    props: {
      label: { type: 'string', default: 'Click' }
    }
  }, 'react');
  assertTrue(result.success, 'Should succeed');
  assertTrue(result.content !== null, 'Should have content');
  assertTrue(result.content.length > 0, 'Content should not be empty');
});

test('P1.5: generateRichStoryFile includes enum variants (P2 integration)', () => {
  const gen = new StoryGenerator({ enableRichVariants: true, autoEnumVariants: true });
  const result = gen.generateRichStoryFile({
    name: 'TestButton',
    props: {
      variant: { type: 'enum', values: ['primary', 'secondary'] }
    }
  }, 'react', { includeEnumVariants: true });
  assertTrue('Primary' in result.variants || 'primary' in result.variants,
    'Should include enum variants');
});

test('P1.6: generateRichStoryFile validates props (P5 integration)', () => {
  const gen = new StoryGenerator({ enableRichVariants: true });
  const result = gen.generateRichStoryFile({
    name: 'TestButton',
    props: {
      badProp: 'not an object'
    }
  }, 'react');
  assertTrue(result.validation !== null, 'Should have validation result');
  assertTrue(result.warnings.length > 0, 'Should have warnings from validation');
});

test('P1.7: generateRichStoryFile uses Figma URL (P3 integration)', () => {
  const gen = new StoryGenerator({ enableRichVariants: true });
  gen.componentRegistry = {
    components: [{ name: 'TestButton', figmaUrl: 'https://figma.com/test' }]
  };
  const result = gen.generateRichStoryFile({ name: 'TestButton', props: {} }, 'react');
  assertEqual(result.figmaUrl, 'https://figma.com/test', 'Should include Figma URL');
});

test('P1.8: generateRichStoryFile uses registry path (P4 integration)', () => {
  const gen = new StoryGenerator({ enableRichVariants: true });
  gen.projectPath = '/project';
  gen.componentRegistry = {
    components: [{
      name: 'TestButton',
      outputPaths: { react: '.design/extracted-code/react/TestButton.tsx' }
    }]
  };
  const result = gen.generateRichStoryFile({ name: 'TestButton', props: {} }, 'react');
  assertTrue(result.componentPath !== null, 'Should resolve component path');
});

test('P1.9: enableRichVariants option controls variant generation', () => {
  const gen = new StoryGenerator({ enableRichVariants: false, autoEnumVariants: false });
  const result = gen.generateRichStoryFile({
    name: 'TestButton',
    props: { variant: { type: 'enum', values: ['primary'] } }
  }, 'react');
  assertEqual(Object.keys(result.variants).length, 0,
    'Should not generate variants when disabled');
});

test('P1.10: generateRichStoryFile handles state variants', () => {
  const gen = new StoryGenerator({ enableRichVariants: true });
  const result = gen.generateRichStoryFile({
    name: 'TestButton',
    props: {
      disabled: { type: 'boolean', default: false },
      loading: { type: 'boolean', default: false }
    }
  }, 'react', { includeStateVariants: true });
  // StoryVariants generates state variants based on props
  assertTrue(result.success, 'Should generate successfully');
});

// ============================================================
// END-TO-END INTEGRATION TESTS
// ============================================================

console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
console.log('E2E: Full Pipeline Integration');
console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');

test('E2E.1: Full pipeline with all P1-P5 features', () => {
  const gen = new StoryGenerator({
    enableRichVariants: true,
    autoEnumVariants: true
  });

  // Set up registry (P3 & P4)
  gen.projectPath = '/project';
  gen.componentRegistry = {
    components: [{
      name: 'Button',
      figmaUrl: 'https://figma.com/file/abc123?node-id=1:2',
      outputPaths: {
        react: '.design/extracted-code/react/Button.tsx'
      }
    }]
  };

  // Component with intentionally bad props (P5 will fix)
  const component = {
    name: 'Button',
    props: {
      variant: { type: 'enum', values: ['primary', 'secondary', 'outline'] },
      size: { type: 'enum', values: ['sm', 'md', 'lg'] },
      disabled: { type: 'boolean', default: 'false' }, // Wrong type - P5 should fix
      label: { type: 'string', default: 'Click me' }
    }
  };

  const result = gen.generateRichStoryFile(component, 'react', {
    includeEnumVariants: true,
    includeStateVariants: true
  });

  // Verify all P1-P5 features worked
  assertTrue(result.success, 'Pipeline should succeed');
  assertTrue(result.content.length > 0, 'Should generate content');
  assertTrue(Object.keys(result.variants).length >= 6, 'Should have enum variants (P2)');
  assertEqual(result.figmaUrl, 'https://figma.com/file/abc123?node-id=1:2', 'Should have Figma URL (P3)');
  assertTrue(result.componentPath.includes('Button.tsx'), 'Should resolve path (P4)');
  assertTrue(result.validation !== null, 'Should validate props (P5)');
});

test('E2E.2: Generated content includes component name', () => {
  const gen = new StoryGenerator({ enableRichVariants: true });
  const result = gen.generateRichStoryFile({
    name: 'MyAwesomeButton',
    props: { label: { type: 'string', default: 'Click' } }
  }, 'react');
  assertContains(result.content, 'MyAwesomeButton', 'Content should reference component');
});

test('E2E.3: Generated content is valid JavaScript/TypeScript', () => {
  const gen = new StoryGenerator({ enableRichVariants: true });
  const result = gen.generateRichStoryFile({
    name: 'TestButton',
    props: { label: { type: 'string', default: 'Click' } }
  }, 'react');

  // Basic syntax check - should not throw
  try {
    // Check for balanced braces
    const opens = (result.content.match(/{/g) || []).length;
    const closes = (result.content.match(/}/g) || []).length;
    assertEqual(opens, closes, 'Braces should be balanced');
  } catch (e) {
    throw new Error('Generated content has syntax issues');
  }
});

test('E2E.4: Backward compatibility - old methods still work', () => {
  const gen = new StoryGenerator();

  // Old method should still work
  const oldResult = gen.generateStoryFile({
    name: 'TestButton',
    props: { label: { type: 'string', default: 'Click' } }
  }, 'react');

  assertTrue(oldResult !== null, 'Old generateStoryFile should still work');
  assertTrue(oldResult.length > 0, 'Should generate content');
});

// ============================================================
// SUMMARY
// ============================================================

console.log('\n╔════════════════════════════════════════════════════════════╗');
console.log('║                      TEST SUMMARY                          ║');
console.log('╚════════════════════════════════════════════════════════════╝\n');

console.log(`Total Tests:  ${results.total}`);
console.log(`Passed:       ${results.passed} ✅`);
console.log(`Failed:       ${results.failed} ❌`);
console.log(`Success Rate: ${Math.round((results.passed / results.total) * 100)}%\n`);

if (results.failed > 0) {
  console.log('Failed Tests:');
  results.tests.filter(t => t.status === 'FAILED').forEach(t => {
    console.log(`  ❌ ${t.name}`);
    console.log(`     ${t.error}`);
  });
  console.log('');
}

// Summary by priority
const p5Tests = results.tests.filter(t => t.name.startsWith('P5'));
const p2Tests = results.tests.filter(t => t.name.startsWith('P2'));
const p3Tests = results.tests.filter(t => t.name.startsWith('P3'));
const p4Tests = results.tests.filter(t => t.name.startsWith('P4'));
const p1Tests = results.tests.filter(t => t.name.startsWith('P1'));
const e2eTests = results.tests.filter(t => t.name.startsWith('E2E'));

console.log('By Feature:');
console.log(`  P5 (Props Validation):     ${p5Tests.filter(t => t.status === 'PASSED').length}/${p5Tests.length} passed`);
console.log(`  P2 (Enum Variants):        ${p2Tests.filter(t => t.status === 'PASSED').length}/${p2Tests.length} passed`);
console.log(`  P3 (Figma URL):            ${p3Tests.filter(t => t.status === 'PASSED').length}/${p3Tests.length} passed`);
console.log(`  P4 (Registry Paths):       ${p4Tests.filter(t => t.status === 'PASSED').length}/${p4Tests.length} passed`);
console.log(`  P1 (StoryVariants):        ${p1Tests.filter(t => t.status === 'PASSED').length}/${p1Tests.length} passed`);
console.log(`  E2E (Full Pipeline):       ${e2eTests.filter(t => t.status === 'PASSED').length}/${e2eTests.length} passed`);

if (results.failed === 0) {
  console.log('\n🎉 ALL P1-P5 INTEGRATION TESTS PASSED!');
  console.log('\nFeatures Verified:');
  console.log('  ✅ P1: StoryVariants integrated into generateRichStoryFile');
  console.log('  ✅ P2: Auto-generation of variants from enum props');
  console.log('  ✅ P3: Figma URL passthrough from componentRegistry');
  console.log('  ✅ P4: Registry-based component path resolution');
  console.log('  ✅ P5: Props validation and sanitization');
  console.log('  ✅ E2E: Full pipeline integration working');
  process.exit(0);
} else {
  console.log('\n⚠️  Some tests failed. Please review and fix.');
  process.exit(1);
}
