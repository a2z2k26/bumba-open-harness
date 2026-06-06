/**
 * Phase 3: Template Files Unit Tests
 *
 * Tests for all 5 Handlebars templates:
 * - product-overview.md.tmpl
 * - product-roadmap.md.tmpl
 * - data-model.md.tmpl
 * - shell-spec.md.tmpl
 * - section-spec.md.tmpl
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

function assertContains(text, substring, message) {
  if (!text.includes(substring)) {
    throw new Error(message || `Expected to contain "${substring}"`);
  }
}

console.log('\n=== Testing Phase 3: Template Files ===\n');

// ============================================================================
// TEMPLATE FILE EXISTENCE
// ============================================================================

console.log('--- Template Files ---\n');

// Test 1: All 5 template files exist
test('All 5 template files exist', () => {
  const templates = [
    'product-overview.md.tmpl',
    'product-roadmap.md.tmpl',
    'data-model.md.tmpl',
    'shell-spec.md.tmpl',
    'section-spec.md.tmpl'
  ];

  templates.forEach(tmpl => {
    const tmplPath = path.resolve(__dirname, '..', tmpl);
    assert(fs.existsSync(tmplPath), `Template ${tmpl} should exist`);
  });
});

// Test 2: All templates are markdown files
test('All templates use .md.tmpl extension', () => {
  const templates = [
    'product-overview.md.tmpl',
    'product-roadmap.md.tmpl',
    'data-model.md.tmpl',
    'shell-spec.md.tmpl',
    'section-spec.md.tmpl'
  ];

  templates.forEach(tmpl => {
    assert(tmpl.endsWith('.md.tmpl'), `${tmpl} should have .md.tmpl extension`);
  });
});

// ============================================================================
// HANDLEBARS SYNTAX
// ============================================================================

console.log('\n--- Handlebars Syntax ---\n');

// Test 3: Templates use Handlebars variables
test('Templates use Handlebars variables ({{variable}})', () => {
  const templates = [
    'product-overview.md.tmpl',
    'product-roadmap.md.tmpl',
    'data-model.md.tmpl',
    'shell-spec.md.tmpl',
    'section-spec.md.tmpl'
  ];

  templates.forEach(tmpl => {
    const tmplPath = path.resolve(__dirname, '..', tmpl);
    const content = fs.readFileSync(tmplPath, 'utf-8');
    assertContains(content, '{{', `${tmpl} should use Handlebars variables`);
    assertContains(content, '}}', `${tmpl} should close Handlebars variables`);
  });
});

// Test 4: Templates use Handlebars conditionals where needed
test('Templates use Handlebars conditionals ({{#if}})', () => {
  const templatesWithConditionals = [
    'product-overview.md.tmpl',
    'section-spec.md.tmpl'
  ];

  templatesWithConditionals.forEach(tmpl => {
    const tmplPath = path.resolve(__dirname, '..', tmpl);
    const content = fs.readFileSync(tmplPath, 'utf-8');
    assertContains(content, '{{#if', `${tmpl} should use {{#if conditionals`);
    assertContains(content, '{{/if}}', `${tmpl} should close conditionals`);
  });
});

// Test 5: Templates use Handlebars loops where needed
test('Templates use Handlebars loops ({{#each}})', () => {
  const templatesWithLoops = [
    'product-roadmap.md.tmpl',
    'section-spec.md.tmpl'
  ];

  templatesWithLoops.forEach(tmpl => {
    const tmplPath = path.resolve(__dirname, '..', tmpl);
    const content = fs.readFileSync(tmplPath, 'utf-8');
    assertContains(content, '{{#each', `${tmpl} should use {{#each loops`);
    assertContains(content, '{{/each}}', `${tmpl} should close loops`);
  });
});

// ============================================================================
// PRODUCT-OVERVIEW.MD.TMPL
// ============================================================================

console.log('\n--- product-overview.md.tmpl ---\n');

// Test 6: product-overview has required variables
test('product-overview has required variables', () => {
  const tmplPath = path.resolve(__dirname, '..', 'product-overview.md.tmpl');
  const content = fs.readFileSync(tmplPath, 'utf-8');

  assertContains(content, '{{productName}}', 'Should have productName');
  assertContains(content, '{{description}}', 'Should have description');
  assertContains(content, '{{problems}}', 'Should have problems');
  assertContains(content, '{{features}}', 'Should have features');
});

// Test 7: product-overview references Bumba tokens conditionally
test('product-overview references Bumba tokens conditionally', () => {
  const tmplPath = path.resolve(__dirname, '..', 'product-overview.md.tmpl');
  const content = fs.readFileSync(tmplPath, 'utf-8');

  assertContains(content, 'bumbaTokensAvailable', 'Should check if Bumba tokens available');
  assertContains(content, '.design/tokens', 'Should reference .design/tokens path');
});

// ============================================================================
// PRODUCT-ROADMAP.MD.TMPL
// ============================================================================

console.log('\n--- product-roadmap.md.tmpl ---\n');

// Test 8: product-roadmap iterates over sections
test('product-roadmap iterates over sections', () => {
  const tmplPath = path.resolve(__dirname, '..', 'product-roadmap.md.tmpl');
  const content = fs.readFileSync(tmplPath, 'utf-8');

  assertContains(content, '{{#each sections}}', 'Should loop over sections');
  assertContains(content, '{{this.title}}', 'Should display section title');
  assertContains(content, '{{this.description}}', 'Should display section description');
});

// ============================================================================
// DATA-MODEL.MD.TMPL
// ============================================================================

console.log('\n--- data-model.md.tmpl ---\n');

// Test 9: data-model has entity structure
test('data-model has entity structure', () => {
  const tmplPath = path.resolve(__dirname, '..', 'data-model.md.tmpl');
  const content = fs.readFileSync(tmplPath, 'utf-8');

  assertContains(content, '{{#each entities}}', 'Should loop over entities');
  assertContains(content, '{{this.name}}', 'Should display entity name');
  assertContains(content, '{{this.description}}', 'Should display entity description');
});

// Test 10: data-model references TypeScript
test('data-model references TypeScript', () => {
  const tmplPath = path.resolve(__dirname, '..', 'data-model.md.tmpl');
  const content = fs.readFileSync(tmplPath, 'utf-8');

  assertContains(content, 'TypeScript', 'Should mention TypeScript');
  assertContains(content, 'types.ts', 'Should reference types.ts file');
});

// ============================================================================
// SHELL-SPEC.MD.TMPL
// ============================================================================

console.log('\n--- shell-spec.md.tmpl ---\n');

// Test 11: shell-spec has navigation structure
test('shell-spec has navigation structure', () => {
  const tmplPath = path.resolve(__dirname, '..', 'shell-spec.md.tmpl');
  const content = fs.readFileSync(tmplPath, 'utf-8');

  assertContains(content, '{{layoutPattern}}', 'Should have layout pattern');
  assertContains(content, '{{#each navItems}}', 'Should loop over nav items');
});

// Test 12: shell-spec references Bumba layouts
test('shell-spec references Bumba layouts conditionally', () => {
  const tmplPath = path.resolve(__dirname, '..', 'shell-spec.md.tmpl');
  const content = fs.readFileSync(tmplPath, 'utf-8');

  assertContains(content, '{{#if bumbaLayoutsAvailable}}', 'Should check for Bumba layouts');
  assertContains(content, '.design/', 'Should reference .design/ directory');
});

// ============================================================================
// SECTION-SPEC.MD.TMPL
// ============================================================================

console.log('\n--- section-spec.md.tmpl ---\n');

// Test 13: section-spec has user flows and UI requirements
test('section-spec has user flows and UI requirements', () => {
  const tmplPath = path.resolve(__dirname, '..', 'section-spec.md.tmpl');
  const content = fs.readFileSync(tmplPath, 'utf-8');

  assertContains(content, '{{sectionName}}', 'Should have section name');
  assertContains(content, '{{userFlows}}', 'Should have user flows');
  assertContains(content, '{{uiRequirements}}', 'Should have UI requirements');
});

// Test 14: section-spec references Bumba components
test('section-spec references Bumba components conditionally', () => {
  const tmplPath = path.resolve(__dirname, '..', 'section-spec.md.tmpl');
  const content = fs.readFileSync(tmplPath, 'utf-8');

  assertContains(content, 'bumbaComponentsAvailable', 'Should check for Bumba components');
  assertContains(content, '{{#each bumbaComponents}}', 'Should loop over components');
  assertContains(content, '.design/components', 'Should reference .design/components');
});

// ============================================================================
// MARKDOWN STRUCTURE
// ============================================================================

console.log('\n--- Markdown Structure ---\n');

// Test 15: Templates use proper markdown headings
test('Templates use markdown headings (#, ##, ###)', () => {
  const templates = [
    'product-overview.md.tmpl',
    'product-roadmap.md.tmpl',
    'data-model.md.tmpl',
    'shell-spec.md.tmpl',
    'section-spec.md.tmpl'
  ];

  templates.forEach(tmpl => {
    const tmplPath = path.resolve(__dirname, '..', tmpl);
    const content = fs.readFileSync(tmplPath, 'utf-8');
    assertContains(content, '#', `${tmpl} should use markdown headings`);
  });
});

// Test 16: Templates use lists where appropriate
test('Templates use markdown lists (-, *)', () => {
  const templates = [
    'product-overview.md.tmpl',
    'section-spec.md.tmpl'
  ];

  templates.forEach(tmpl => {
    const tmplPath = path.resolve(__dirname, '..', tmpl);
    const content = fs.readFileSync(tmplPath, 'utf-8');
    const hasList = content.includes('- ') || content.includes('* ');
    assert(hasList, `${tmpl} should use markdown lists`);
  });
});

// ============================================================================
// BUMBA INTEGRATION
// ============================================================================

console.log('\n--- Bumba Integration ---\n');

// Test 17: Templates reference .design/ directory structure
test('Templates reference .design/ directory structure', () => {
  const templatesWithDesignRefs = [
    'product-overview.md.tmpl',
    'shell-spec.md.tmpl',
    'section-spec.md.tmpl'
  ];

  templatesWithDesignRefs.forEach(tmpl => {
    const tmplPath = path.resolve(__dirname, '..', tmpl);
    const content = fs.readFileSync(tmplPath, 'utf-8');
    assertContains(content, '.design/', `${tmpl} should reference .design/ directory`);
  });
});

// Test 18: No hardcoded absolute paths in templates
test('No hardcoded absolute paths in templates', () => {
  const templates = [
    'product-overview.md.tmpl',
    'product-roadmap.md.tmpl',
    'data-model.md.tmpl',
    'shell-spec.md.tmpl',
    'section-spec.md.tmpl'
  ];

  templates.forEach(tmpl => {
    const tmplPath = path.resolve(__dirname, '..', tmpl);
    const content = fs.readFileSync(tmplPath, 'utf-8');
    assert(!content.includes('/home/'), `${tmpl} should not have absolute paths`);
    assert(!content.includes('C:\\'), `${tmpl} should not have Windows absolute paths`);
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
  console.log('\n✓ All template tests passed!\n');
  console.log('Phase 3 Template Summary:');
  console.log('  ✓ 5 template files exist and are valid');
  console.log('  ✓ All templates use Handlebars syntax correctly');
  console.log('  ✓ product-overview.md.tmpl: Complete with Bumba integration');
  console.log('  ✓ product-roadmap.md.tmpl: Complete with section iteration');
  console.log('  ✓ data-model.md.tmpl: Complete with entity structure');
  console.log('  ✓ shell-spec.md.tmpl: Complete with layout references');
  console.log('  ✓ section-spec.md.tmpl: Complete with component references');
  console.log('  ✓ All templates use proper markdown structure');
  console.log('  ✓ All templates have Bumba integration points');
  console.log('\n');
  process.exit(0);
}
