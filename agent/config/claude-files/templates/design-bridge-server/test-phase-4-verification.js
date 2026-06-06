/**
 * Phase 4 Source Integrations Verification Test
 * Tests that all source integration files have v4.0.0 methods
 * and work correctly with the RegistryManager
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

console.log('\n═══════════════════════════════════════════════════════════');
console.log('   PHASE 4: Figma Registry Integration v4.0.0 Tests');
console.log('═══════════════════════════════════════════════════════════\n');

// Test figma-registry-integration.js
test('figma-registry-integration.js loads', () => {
  const mod = require('./figma-registry-integration');
  assert(mod, 'Module loads');
});

test('figma-registry-integration.js has v4.0.0 header', () => {
  const content = fs.readFileSync(path.join(__dirname, 'figma-registry-integration.js'), 'utf8');
  assert(content.includes('v4.0.0 Integration'), 'Has v4.0.0 header');
  assert(content.includes('getRegistryManagerModule'), 'Has lazy-load function');
});

test('figma-registry-integration.js has v4.0.0 exports', () => {
  const mod = require('./figma-registry-integration');
  assert(typeof mod.hasV4Registry === 'function', 'hasV4Registry exists');
  assert(typeof mod.getRegistryManager === 'function', 'getRegistryManager exists');
  assert(typeof mod.generateV4CanonicalId === 'function', 'generateV4CanonicalId exists');
  assert(typeof mod.updateRegistryV4 === 'function', 'updateRegistryV4 exists');
  assert(typeof mod.findByNodeIdV4 === 'function', 'findByNodeIdV4 exists');
  assert(typeof mod.findByIdV4 === 'function', 'findByIdV4 exists');
  assert(typeof mod.getFigmaComponentsV4 === 'function', 'getFigmaComponentsV4 exists');
  assert(typeof mod.getV4Stats === 'function', 'getV4Stats exists');
  assert(typeof mod.invalidateV4Cache === 'function', 'invalidateV4Cache exists');
});

test('figma-registry-integration.js generates correct canonical IDs', () => {
  const mod = require('./figma-registry-integration');
  const component = { name: 'Button Primary', figmaId: '123:456' };
  const id = mod.generateV4CanonicalId(component);
  assert(id.startsWith('figma-component-'), 'ID starts with figma-component-');
  assert(id.includes('button-primary'), 'ID includes sanitized name');
  assert(id.includes('123-456'), 'ID includes nodeId');
});

test('figma-registry-integration.js preserves legacy exports', () => {
  const mod = require('./figma-registry-integration');
  assert(typeof mod.updateRegistry === 'function', 'updateRegistry exists');
  assert(typeof mod.batchUpdateRegistry === 'function', 'batchUpdateRegistry exists');
  assert(typeof mod.createEmptyRegistry === 'function', 'createEmptyRegistry exists');
  assert(typeof mod.generateComponentId === 'function', 'generateComponentId exists');
  assert(typeof mod.findDuplicates === 'function', 'findDuplicates exists');
  assert(typeof mod.inferCategory === 'function', 'inferCategory exists');
});

console.log('\n═══════════════════════════════════════════════════════════');
console.log('   PHASE 4: ShadCN Registry Integration v4.0.0 Tests');
console.log('═══════════════════════════════════════════════════════════\n');

// Test shadcn-registry-integration.js
test('shadcn-registry-integration.js loads', () => {
  const mod = require('./shadcn-registry-integration');
  assert(mod, 'Module loads');
});

test('shadcn-registry-integration.js has v4.0.0 header', () => {
  const content = fs.readFileSync(path.join(__dirname, 'shadcn-registry-integration.js'), 'utf8');
  assert(content.includes('v4.0.0 Integration'), 'Has v4.0.0 header');
  assert(content.includes('getRegistryManagerModule'), 'Has lazy-load function');
});

test('shadcn-registry-integration.js has v4.0.0 exports', () => {
  const mod = require('./shadcn-registry-integration');
  assert(typeof mod.hasV4Registry === 'function', 'hasV4Registry exists');
  assert(typeof mod.getRegistryManager === 'function', 'getRegistryManager exists');
  assert(typeof mod.generateV4CanonicalId === 'function', 'generateV4CanonicalId exists');
  assert(typeof mod.addShadcnComponentV4 === 'function', 'addShadcnComponentV4 exists');
  assert(typeof mod.findByIdV4 === 'function', 'findByIdV4 exists');
  assert(typeof mod.getShadcnComponentsV4 === 'function', 'getShadcnComponentsV4 exists');
  assert(typeof mod.queryComponentsV4 === 'function', 'queryComponentsV4 exists');
  assert(typeof mod.linkComponentsV4 === 'function', 'linkComponentsV4 exists');
  assert(typeof mod.getV4Stats === 'function', 'getV4Stats exists');
  assert(typeof mod.invalidateV4Cache === 'function', 'invalidateV4Cache exists');
});

test('shadcn-registry-integration.js generates correct canonical IDs', () => {
  const mod = require('./shadcn-registry-integration');
  const id1 = mod.generateV4CanonicalId('Button', '@shadcn');
  assert(id1 === 'shadcn-component-shadcn-button', 'Default registry ID: ' + id1);

  const id2 = mod.generateV4CanonicalId('Card', '@acme');
  assert(id2 === 'shadcn-component-acme-card', 'Custom registry ID: ' + id2);
});

test('shadcn-registry-integration.js preserves legacy exports', () => {
  const mod = require('./shadcn-registry-integration');
  assert(typeof mod.loadRegistry === 'function', 'loadRegistry exists');
  assert(typeof mod.saveRegistry === 'function', 'saveRegistry exists');
  assert(typeof mod.addShadcnComponent === 'function', 'addShadcnComponent exists');
  assert(typeof mod.removeComponent === 'function', 'removeComponent exists');
  assert(typeof mod.getComponent === 'function', 'getComponent exists');
  assert(typeof mod.queryComponents === 'function', 'queryComponents exists');
  assert(typeof mod.getShadcnComponents === 'function', 'getShadcnComponents exists');
  assert(typeof mod.getRegistryStats === 'function', 'getRegistryStats exists');
  assert(typeof mod.analyzeComponentMerge === 'function', 'analyzeComponentMerge exists');
  assert(typeof mod.linkComponents === 'function', 'linkComponents exists');
});

console.log('\n═══════════════════════════════════════════════════════════');
console.log('   PHASE 4: NLP Registry Integration v4.0.0 Tests');
console.log('═══════════════════════════════════════════════════════════\n');

// Test nlp-registry-integration.js
test('nlp-registry-integration.js loads', () => {
  const mod = require('./nlp-registry-integration');
  assert(mod, 'Module loads');
});

test('nlp-registry-integration.js has v4.0.0 header', () => {
  const content = fs.readFileSync(path.join(__dirname, 'nlp-registry-integration.js'), 'utf8');
  assert(content.includes('v4.0.0 Integration'), 'Has v4.0.0 header');
  assert(content.includes('getRegistryManagerModule'), 'Has lazy-load function');
});

test('nlp-registry-integration.js has v4.0.0 exports', () => {
  const mod = require('./nlp-registry-integration');
  assert(typeof mod.hasV4Registry === 'function', 'hasV4Registry exists');
  assert(typeof mod.getRegistryManager === 'function', 'getRegistryManager exists');
  assert(typeof mod.generateV4CanonicalId === 'function', 'generateV4CanonicalId exists');
  assert(typeof mod.updateRegistryV4 === 'function', 'updateRegistryV4 exists');
  assert(typeof mod.findByIdV4 === 'function', 'findByIdV4 exists');
  assert(typeof mod.findByNameV4 === 'function', 'findByNameV4 exists');
  assert(typeof mod.getNlpComponentsV4 === 'function', 'getNlpComponentsV4 exists');
  assert(typeof mod.getRefinementHistoryV4 === 'function', 'getRefinementHistoryV4 exists');
  assert(typeof mod.getV4Stats === 'function', 'getV4Stats exists');
  assert(typeof mod.invalidateV4Cache === 'function', 'invalidateV4Cache exists');
});

test('nlp-registry-integration.js generates correct canonical IDs', () => {
  const mod = require('./nlp-registry-integration');
  const component = { name: 'Hero Section' };
  const id = mod.generateV4CanonicalId(component);
  assert(id.startsWith('nlp-component-'), 'ID starts with nlp-component-');
  assert(id.includes('hero-section'), 'ID includes sanitized name');
  // Timestamp should be a number at the end
  const timestamp = id.split('-').pop();
  assert(!isNaN(parseInt(timestamp)), 'ID ends with timestamp');
});

test('nlp-registry-integration.js preserves legacy exports', () => {
  const mod = require('./nlp-registry-integration');
  assert(mod.nlpEntrySchema, 'nlpEntrySchema exists');
  assert(typeof mod.createRegistryEntry === 'function', 'createRegistryEntry exists');
  assert(typeof mod.updateComponentRegistry === 'function', 'updateComponentRegistry exists');
  assert(typeof mod.loadRegistry === 'function', 'loadRegistry exists');
  assert(typeof mod.saveRegistry === 'function', 'saveRegistry exists');
  assert(typeof mod.getNlpComponents === 'function', 'getNlpComponents exists');
  assert(typeof mod.getRefinementHistory === 'function', 'getRefinementHistory exists');
  assert(typeof mod.findByName === 'function', 'findByName exists');
  assert(typeof mod.findByCategory === 'function', 'findByCategory exists');
  assert(typeof mod.removeFromRegistry === 'function', 'removeFromRegistry exists');
  assert(typeof mod.getNlpStats === 'function', 'getNlpStats exists');
  assert(typeof mod.validateEntry === 'function', 'validateEntry exists');
});

console.log('\n═══════════════════════════════════════════════════════════');
console.log('   PHASE 4: Cross-Source Integration Tests');
console.log('═══════════════════════════════════════════════════════════\n');

// Test that all sources use consistent patterns
test('All sources use consistent hasV4Registry pattern', () => {
  const figma = require('./figma-registry-integration');
  const shadcn = require('./shadcn-registry-integration');
  const nlp = require('./nlp-registry-integration');

  // All should return false for non-existent registry (no .design folder here)
  const testPath = '/tmp/non-existent-project';

  // Clear caches first
  figma.invalidateV4Cache();
  shadcn.invalidateV4Cache();
  nlp.invalidateV4Cache();

  assert(figma.hasV4Registry(testPath) === false, 'Figma returns false for missing registry');

  // Reset cache again for next test
  shadcn.invalidateV4Cache();
  assert(shadcn.hasV4Registry(testPath) === false, 'ShadCN returns false for missing registry');

  nlp.invalidateV4Cache();
  assert(nlp.hasV4Registry(testPath) === false, 'NLP returns false for missing registry');
});

test('All sources have invalidateV4Cache method', () => {
  const figma = require('./figma-registry-integration');
  const shadcn = require('./shadcn-registry-integration');
  const nlp = require('./nlp-registry-integration');

  // Should not throw
  figma.invalidateV4Cache();
  shadcn.invalidateV4Cache();
  nlp.invalidateV4Cache();
  assert(true, 'All invalidateV4Cache methods work');
});

test('Canonical ID formats are distinct per source', () => {
  const figma = require('./figma-registry-integration');
  const shadcn = require('./shadcn-registry-integration');
  const nlp = require('./nlp-registry-integration');

  const figmaId = figma.generateV4CanonicalId({ name: 'Test', figmaId: '1:2' });
  const shadcnId = shadcn.generateV4CanonicalId('Test');
  const nlpId = nlp.generateV4CanonicalId({ name: 'Test' });

  assert(figmaId.startsWith('figma-'), 'Figma ID prefix: ' + figmaId);
  assert(shadcnId.startsWith('shadcn-'), 'ShadCN ID prefix: ' + shadcnId);
  assert(nlpId.startsWith('nlp-'), 'NLP ID prefix: ' + nlpId);

  // Ensure they're all different
  assert(figmaId !== shadcnId, 'Figma and ShadCN IDs are different');
  assert(figmaId !== nlpId, 'Figma and NLP IDs are different');
  assert(shadcnId !== nlpId, 'ShadCN and NLP IDs are different');
});

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
  console.log('\n\x1b[32m✅ ALL PHASE 4 SOURCE INTEGRATION TESTS PASSED\x1b[0m');
}
