/**
 * Phase 1-3 Integration Verification Test
 * Tests that all files updated with v4.0.0 integration load correctly
 * and have the required methods/properties
 */

const fs = require('fs');
const path = require('path');

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log('✅', name);
    passed++;
  } catch (err) {
    console.log('❌', name + ':', err.message);
    failed++;
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message || 'Assertion failed');
}

console.log('\n═══════════════════════════════════════════════════════════');
console.log('   PHASE 1: RegistryManager Foundation Tests');
console.log('═══════════════════════════════════════════════════════════\n');

test('RegistryManager module loads', () => {
  const rm = require('./registry-manager');
  assert(rm.RegistryManager, 'RegistryManager class exists');
  assert(rm.getRegistryManager, 'getRegistryManager function exists');
  assert(rm.clearRegistryManager, 'clearRegistryManager function exists');
});

test('RegistryManager has required methods', () => {
  const { RegistryManager } = require('./registry-manager');
  const proto = RegistryManager.prototype;
  // Check for actual method names
  const required = ['saveIndex', 'addEntry', 'updateEntry', 'getStats', 'findById', 'findByNodeId'];
  for (const method of required) {
    assert(typeof proto[method] === 'function', method + ' method exists');
  }
});

console.log('\n═══════════════════════════════════════════════════════════');
console.log('   PHASE 2: Migration Module Tests');
console.log('═══════════════════════════════════════════════════════════\n');

test('registry-migration module loads', () => {
  const rm = require('./registry-migration');
  assert(rm.RegistryMigration, 'RegistryMigration class exists');
  assert(typeof rm.createMigration === 'function', 'createMigration function exists');
});

console.log('\n═══════════════════════════════════════════════════════════');
console.log('   PHASE 3: Integration Files - v4.0.0 Methods');
console.log('═══════════════════════════════════════════════════════════\n');

// registry-reader.js
test('registry-reader.js has v4.0.0 methods', () => {
  const mod = require('./registry-reader');
  assert(typeof mod.hasV4Registry === 'function', 'hasV4Registry exists');
  assert(typeof mod.getRegistryManager === 'function', 'getRegistryManager exists');
});

// canonical-id.js
test('canonical-id.js has v4.0.0 exports', () => {
  const mod = require('./canonical-id');
  assert(typeof mod.generateCanonicalId === 'function', 'generateCanonicalId exists');
  assert(typeof mod.generateV4CanonicalId === 'function', 'generateV4CanonicalId exists');
  assert(typeof mod.isV4CanonicalId === 'function', 'isV4CanonicalId exists');
});

// auto-registrar.js
test('auto-registrar.js has v4.0.0 methods', () => {
  const { AutoRegistrar } = require('./auto-registrar');
  const ar = new AutoRegistrar(process.cwd());
  assert(typeof ar.hasV4Registry === 'function', 'hasV4Registry exists');
  assert(typeof ar.getRegistryManager === 'function', 'getRegistryManager exists');
});

// design-structure.js
test('design-structure.js has v4.0.0 methods', () => {
  const mod = require('./design-structure');
  // DesignStructure class has v4 methods
  assert(mod.DesignStructure, 'DesignStructure class exists');
  assert(typeof mod.initializeDesignStructure === 'function', 'initializeDesignStructure exists');
});

// layout-transformer.js
test('layout-transformer.js has v4.0.0 methods', () => {
  const LayoutTransformer = require('./layout-transformer');
  const lt = new LayoutTransformer(process.cwd());
  assert(typeof lt.hasV4Registry === 'function', 'hasV4Registry exists');
  assert(typeof lt.getRegistryManager === 'function', 'getRegistryManager exists');
  assert(typeof lt.findComponentByNodeId === 'function', 'findComponentByNodeId exists');
});

// auto-sync-manager.js
test('auto-sync-manager.js has v4.0.0 methods', () => {
  const AutoSyncManager = require('./auto-sync-manager');
  const asm = new AutoSyncManager({ projectPath: process.cwd() });
  assert(typeof asm.hasV4Registry === 'function', 'hasV4Registry exists');
  assert(typeof asm.getRegistryManager === 'function', 'getRegistryManager exists');
  assert(typeof asm.findAffectedComponentsV4 === 'function', 'findAffectedComponentsV4 exists');
});

// sync-cascade.js
test('sync-cascade.js has v4.0.0 methods', () => {
  const { SyncCascade } = require('./sync-cascade');
  const sc = new SyncCascade({ projectPath: process.cwd() });
  assert(typeof sc.hasV4Registry === 'function', 'hasV4Registry exists');
  assert(typeof sc.getRegistryManager === 'function', 'getRegistryManager exists');
  assert(typeof sc.getComponentV4 === 'function', 'getComponentV4 exists');
  assert(typeof sc.getCascadeImpact === 'function', 'getCascadeImpact exists');
});

// cli.js
test('cli.js has v4.0.0 methods', () => {
  const { cli } = require('./cli');
  assert(typeof cli.hasV4Registry === 'function', 'hasV4Registry exists');
  assert(typeof cli.getRegistryManager === 'function', 'getRegistryManager exists');
  assert(typeof cli.getV4Stats === 'function', 'getV4Stats exists');
  assert(cli.version === '2.0.0', 'Version is 2.0.0');
});

console.log('\n═══════════════════════════════════════════════════════════');
console.log('   PHASE 3: Framework Optimizers');
console.log('═══════════════════════════════════════════════════════════\n');

const optimizers = [
  'react-optimizer', 'vue-optimizer', 'angular-optimizer', 'svelte-optimizer',
  'flutter-optimizer', 'swiftui-optimizer', 'jetpack-compose-optimizer',
  'react-native-optimizer', 'web-components-optimizer'
];

for (const name of optimizers) {
  test(name + '.js loads with v4.0.0', () => {
    const content = fs.readFileSync(path.join(__dirname, name + '.js'), 'utf8');
    assert(content.includes('v4.0.0 Integration'), 'Has v4.0.0 header');
    assert(content.includes('getRegistryManagerModule'), 'Has lazy-load function');
    require('./' + name); // Ensure it loads without error
  });
}

console.log('\n═══════════════════════════════════════════════════════════');
console.log('   RESULTS');
console.log('═══════════════════════════════════════════════════════════');
console.log(`   Total:  ${passed + failed}`);
console.log(`   Passed: ${passed}`);
console.log(`   Failed: ${failed}`);
console.log('═══════════════════════════════════════════════════════════');

if (failed > 0) {
  console.log('\n❌ SOME TESTS FAILED');
  process.exit(1);
} else {
  console.log('\n✅ ALL PHASE 1-3 INTEGRATION TESTS PASSED');
}
