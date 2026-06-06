#!/usr/bin/env node
/**
 * Phase 5: /design-init v4.0.0 Integration Tests
 *
 * Comprehensive tests for:
 * - design-init command v4.0.0 support
 * - Template v4.0.0 registry configuration
 * - init-storybook.js v4.0.0 registry initialization
 * - Design structure v4.0.0 integration
 */

const fs = require('fs');
const path = require('path');

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log('\x1b[32m✅\x1b[0m', name);
    passed++;
  } catch (err) {
    console.log('\x1b[31m❌\x1b[0m', name + ':', err.message);
    failed++;
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message || 'Assertion failed');
}

// Base paths
const serverDir = __dirname;
const designFeatureRoot = path.resolve(serverDir, '../../..');
const templatesDir = path.join(designFeatureRoot, '.claude/templates/design-init');
const scriptsDir = path.join(designFeatureRoot, '.claude/scripts');

console.log('\n═══════════════════════════════════════════════════════════');
console.log('   PHASE 5: /design-init v4.0.0 Integration Tests');
console.log('═══════════════════════════════════════════════════════════\n');

// ═══════════════════════════════════════════════════════════════════════════
// Section 1: Template v4.0.0 Configuration Tests
// ═══════════════════════════════════════════════════════════════════════════

console.log('─── Template v4.0.0 Configuration ───\n');

const templateFiles = [
  'react-ts-storybook.json',
  'angular-ts.json',
  'vue-composition.json',
  'svelte-ts.json'
];

for (const templateFile of templateFiles) {
  const templatePath = path.join(templatesDir, templateFile);

  test(`${templateFile} exists`, () => {
    assert(fs.existsSync(templatePath), `Template not found: ${templatePath}`);
  });

  test(`${templateFile} has v4.0.0 version`, () => {
    const template = JSON.parse(fs.readFileSync(templatePath, 'utf8'));
    assert(template.version === '4.0.0', `Version is ${template.version}, expected 4.0.0`);
  });

  test(`${templateFile} has registry configuration`, () => {
    const template = JSON.parse(fs.readFileSync(templatePath, 'utf8'));
    assert(template.registry, 'Missing registry configuration');
    assert(template.registry.version === '4.0.0', 'Registry version should be 4.0.0');
    assert(template.registry.useUnifiedRegistry === true, 'useUnifiedRegistry should be true');
  });

  test(`${templateFile} has correct registry paths`, () => {
    const template = JSON.parse(fs.readFileSync(templatePath, 'utf8'));
    assert(template.registry.registryPath === '.design/registry-index.json', 'Incorrect registryPath');
    assert(template.registry.separateRegistries, 'Missing separateRegistries');
    assert(template.registry.separateRegistries.components === '.design/registries/components.json', 'Incorrect components path');
    assert(template.registry.separateRegistries.tokens === '.design/registries/tokens.json', 'Incorrect tokens path');
    assert(template.registry.separateRegistries.layouts === '.design/registries/layouts.json', 'Incorrect layouts path');
  });

  test(`${templateFile} has canonical ID format`, () => {
    const template = JSON.parse(fs.readFileSync(templatePath, 'utf8'));
    assert(template.registry.canonicalIdFormat === '{source}-{type}-{name-slug}-{suffix}', 'Incorrect canonical ID format');
  });

  test(`${templateFile} has tracking options`, () => {
    const template = JSON.parse(fs.readFileSync(templatePath, 'utf8'));
    assert(template.registry.enableDependencyTracking === true, 'enableDependencyTracking should be true');
    assert(template.registry.enableSourceMapping === true, 'enableSourceMapping should be true');
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// Section 2: init-storybook.js v4.0.0 Integration Tests
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── init-storybook.js v4.0.0 Integration ───\n');

const initStorybookPath = path.join(scriptsDir, 'init-storybook.js');

test('init-storybook.js exists', () => {
  assert(fs.existsSync(initStorybookPath), 'init-storybook.js not found');
});

test('init-storybook.js has v4.0.0 header', () => {
  const content = fs.readFileSync(initStorybookPath, 'utf8');
  assert(content.includes('v4.0.0 Integration'), 'Missing v4.0.0 Integration header');
});

test('init-storybook.js has getDesignStructure function', () => {
  const content = fs.readFileSync(initStorybookPath, 'utf8');
  assert(content.includes('function getDesignStructure()'), 'Missing getDesignStructure function');
});

test('init-storybook.js has initializeV4Registry function', () => {
  const content = fs.readFileSync(initStorybookPath, 'utf8');
  assert(content.includes('async function initializeV4Registry'), 'Missing initializeV4Registry function');
});

test('init-storybook.js exports initializeV4Registry', () => {
  const content = fs.readFileSync(initStorybookPath, 'utf8');
  assert(content.includes('initializeV4Registry'), 'initializeV4Registry not exported');
});

test('init-storybook.js supports --skip-registry flag', () => {
  const content = fs.readFileSync(initStorybookPath, 'utf8');
  assert(content.includes('--skip-registry'), 'Missing --skip-registry flag support');
});

test('init-storybook.js module loads', () => {
  const mod = require(initStorybookPath);
  assert(mod, 'Module failed to load');
  assert(typeof mod.initStorybook === 'function', 'initStorybook function missing');
  assert(typeof mod.copyCanonicalTheme === 'function', 'copyCanonicalTheme function missing');
  assert(typeof mod.initializeV4Registry === 'function', 'initializeV4Registry function missing');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 3: design-init.md v4.0.0 Documentation Tests
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── design-init.md v4.0.0 Documentation ───\n');

const designInitMdPath = path.join(designFeatureRoot, '.claude/commands/design-init.md');

test('design-init.md exists', () => {
  assert(fs.existsSync(designInitMdPath), 'design-init.md not found');
});

test('design-init.md has Step 5.5 for v4.0.0 registry', () => {
  const content = fs.readFileSync(designInitMdPath, 'utf8');
  assert(content.includes('Step 5.5'), 'Missing Step 5.5');
  assert(content.includes('v4.0.0'), 'Missing v4.0.0 reference');
});

test('design-init.md documents registry-index.json', () => {
  const content = fs.readFileSync(designInitMdPath, 'utf8');
  assert(content.includes('registry-index.json'), 'Missing registry-index.json documentation');
});

test('design-init.md documents canonical ID format', () => {
  const content = fs.readFileSync(designInitMdPath, 'utf8');
  assert(content.includes('Canonical ID'), 'Missing Canonical ID documentation');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 4: Design Structure v4.0.0 Integration Tests
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── design-structure.js v4.0.0 Integration ───\n');

const designStructurePath = path.join(serverDir, 'design-structure.js');

test('design-structure.js exists', () => {
  assert(fs.existsSync(designStructurePath), 'design-structure.js not found');
});

test('design-structure.js has v4Registries configuration', () => {
  const content = fs.readFileSync(designStructurePath, 'utf8');
  assert(content.includes('v4Registries'), 'Missing v4Registries configuration');
});

test('design-structure.js has initializeV4Registry method', () => {
  const content = fs.readFileSync(designStructurePath, 'utf8');
  assert(content.includes('initializeV4Registry'), 'Missing initializeV4Registry method');
});

test('design-structure.js has hasV4Registry method', () => {
  const content = fs.readFileSync(designStructurePath, 'utf8');
  assert(content.includes('hasV4Registry'), 'Missing hasV4Registry method');
});

test('design-structure.js module loads', () => {
  const mod = require(designStructurePath);
  assert(mod, 'Module failed to load');
  assert(mod.DesignStructure, 'DesignStructure class missing');
  assert(mod.STRUCTURE, 'STRUCTURE export missing');
});

test('design-structure.js STRUCTURE has v4Registries paths', () => {
  const { STRUCTURE } = require(designStructurePath);
  assert(STRUCTURE.v4Registries, 'Missing v4Registries in STRUCTURE');
  assert(STRUCTURE.v4Registries.index === '.design/registry-index.json', 'Incorrect index path');
  assert(STRUCTURE.v4Registries.components === '.design/registries/components.json', 'Incorrect components path');
  assert(STRUCTURE.v4Registries.tokens === '.design/registries/tokens.json', 'Incorrect tokens path');
  assert(STRUCTURE.v4Registries.layouts === '.design/registries/layouts.json', 'Incorrect layouts path');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 5: DesignStructure Class v4.0.0 Methods Tests
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── DesignStructure Class v4.0.0 Methods ───\n');

test('DesignStructure class has v4.0.0 methods', () => {
  const { DesignStructure } = require(designStructurePath);

  // Create a temporary path for testing
  const tmpPath = '/tmp/design-structure-test-' + Date.now();

  const structure = new DesignStructure(tmpPath);

  assert(typeof structure.initializeV4Registry === 'function', 'Missing initializeV4Registry method');
  assert(typeof structure.hasV4Registry === 'function', 'Missing hasV4Registry method');
  assert(typeof structure.getRegistryManager === 'function', 'Missing getRegistryManager method');
  assert(typeof structure.getV4RegistryStats === 'function', 'Missing getV4RegistryStats method');
});

test('DesignStructure.hasV4Registry returns false for non-existent registry', () => {
  const { DesignStructure } = require(designStructurePath);
  const tmpPath = '/tmp/non-existent-design-' + Date.now();
  const structure = new DesignStructure(tmpPath);
  assert(structure.hasV4Registry() === false, 'Should return false for non-existent registry');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 6: Cross-File Consistency Tests
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── Cross-File Consistency ───\n');

test('All templates have consistent v4.0.0 registry schema', () => {
  const schemas = [];

  for (const templateFile of templateFiles) {
    const templatePath = path.join(templatesDir, templateFile);
    const template = JSON.parse(fs.readFileSync(templatePath, 'utf8'));
    schemas.push(JSON.stringify(template.registry));
  }

  // All schemas should be identical
  const uniqueSchemas = [...new Set(schemas)];
  assert(uniqueSchemas.length === 1, `Found ${uniqueSchemas.length} different registry schemas across templates`);
});

test('Template registry paths match STRUCTURE.v4Registries', () => {
  const { STRUCTURE } = require(designStructurePath);
  const template = JSON.parse(fs.readFileSync(path.join(templatesDir, 'react-ts-storybook.json'), 'utf8'));

  assert(template.registry.registryPath === STRUCTURE.v4Registries.index, 'registryPath mismatch');
  assert(template.registry.separateRegistries.components === STRUCTURE.v4Registries.components, 'components path mismatch');
  assert(template.registry.separateRegistries.tokens === STRUCTURE.v4Registries.tokens, 'tokens path mismatch');
  assert(template.registry.separateRegistries.layouts === STRUCTURE.v4Registries.layouts, 'layouts path mismatch');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 7: Source Integration v4.0.0 Compatibility Tests
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── Source Integration v4.0.0 Compatibility ───\n');

const sourceIntegrations = [
  'figma-registry-integration.js',
  'shadcn-registry-integration.js',
  'nlp-registry-integration.js'
];

for (const file of sourceIntegrations) {
  test(`${file} has v4.0.0 methods`, () => {
    const mod = require(path.join(serverDir, file));
    assert(typeof mod.hasV4Registry === 'function', 'hasV4Registry missing');
    assert(typeof mod.getRegistryManager === 'function', 'getRegistryManager missing');
    assert(typeof mod.generateV4CanonicalId === 'function', 'generateV4CanonicalId missing');
    assert(typeof mod.invalidateV4Cache === 'function', 'invalidateV4Cache missing');
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// Results
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n═══════════════════════════════════════════════════════════');
console.log('   RESULTS');
console.log('═══════════════════════════════════════════════════════════');
console.log(`   Total:  ${passed + failed}`);
console.log(`   Passed: ${passed}`);
console.log(`   Failed: ${failed}`);
console.log('═══════════════════════════════════════════════════════════');

if (failed > 0) {
  console.log('\n\x1b[31m❌ SOME TESTS FAILED\x1b[0m');
  process.exit(1);
} else {
  console.log('\n\x1b[32m✅ ALL PHASE 5 /design-init TESTS PASSED\x1b[0m');
}
