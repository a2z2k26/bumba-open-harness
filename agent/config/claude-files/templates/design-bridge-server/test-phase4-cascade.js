#!/usr/bin/env node
/**
 * Phase 4: Cascade Sync - Comprehensive Test Suite
 *
 * Tests all Phase 4 implementations for completion, operability, and integration fidelity.
 */

const path = require('path');
const fs = require('fs');

// Test results tracking
const results = {
  passed: 0,
  failed: 0,
  errors: []
};

function test(name, fn) {
  try {
    fn();
    results.passed++;
    console.log(`  ✅ ${name}`);
  } catch (error) {
    results.failed++;
    results.errors.push({ name, error: error.message });
    console.log(`  ❌ ${name}: ${error.message}`);
  }
}

function assertEqual(actual, expected, msg) {
  if (actual !== expected) {
    throw new Error(`${msg}: expected ${expected}, got ${actual}`);
  }
}

function assertExists(value, msg) {
  if (value === undefined || value === null) {
    throw new Error(`${msg}: value is ${value}`);
  }
}

function assertType(value, type, msg) {
  if (typeof value !== type) {
    throw new Error(`${msg}: expected ${type}, got ${typeof value}`);
  }
}

console.log('\n=== Phase 4: Cascade Sync Test Suite ===\n');

// =====================================================
// TEST 1: SyncCascade Module Imports and Exports
// =====================================================
console.log('1. SyncCascade Module Imports and Exports');

test('sync-cascade.js exists', () => {
  const filePath = path.join(__dirname, 'sync-cascade.js');
  if (!fs.existsSync(filePath)) {
    throw new Error('File not found');
  }
});

let SyncCascade, CASCADE_EVENTS, CASCADE_DEFAULTS;
test('SyncCascade exports correctly', () => {
  const exports = require('./sync-cascade');
  SyncCascade = exports.SyncCascade;
  CASCADE_EVENTS = exports.CASCADE_EVENTS;
  CASCADE_DEFAULTS = exports.CASCADE_DEFAULTS;

  assertExists(SyncCascade, 'SyncCascade class');
  assertExists(CASCADE_EVENTS, 'CASCADE_EVENTS');
  assertExists(CASCADE_DEFAULTS, 'CASCADE_DEFAULTS');
});

test('SyncCascade is a class/constructor', () => {
  assertType(SyncCascade, 'function', 'SyncCascade');
});

test('CASCADE_DEFAULTS has required properties', () => {
  assertExists(CASCADE_DEFAULTS.enabled, 'enabled');
  assertExists(CASCADE_DEFAULTS.regenerateCode, 'regenerateCode');
  assertExists(CASCADE_DEFAULTS.regenerateStory, 'regenerateStory');
  assertExists(CASCADE_DEFAULTS.preserveUserModifications, 'preserveUserModifications');
  assertExists(CASCADE_DEFAULTS.maxCascadesPerSync, 'maxCascadesPerSync');
  assertExists(CASCADE_DEFAULTS.cascadeTimeout, 'cascadeTimeout');
});

test('CASCADE_DEFAULTS has correct default values', () => {
  assertEqual(CASCADE_DEFAULTS.enabled, true, 'enabled');
  assertEqual(CASCADE_DEFAULTS.maxCascadesPerSync, 10, 'maxCascadesPerSync');
  assertEqual(CASCADE_DEFAULTS.cascadeTimeout, 30000, 'cascadeTimeout');
});

// =====================================================
// TEST 2: SyncCascade Instantiation
// =====================================================
console.log('\n2. SyncCascade Instantiation');

let cascadeInstance;
test('SyncCascade instantiates without errors', () => {
  cascadeInstance = new SyncCascade({
    projectPath: __dirname
  });
  assertExists(cascadeInstance, 'instance');
});

test('SyncCascade has required methods', () => {
  assertType(cascadeInstance.cascade, 'function', 'cascade method');
  assertType(cascadeInstance.updateRegistry, 'function', 'updateRegistry method');
  assertType(cascadeInstance.shouldRegenerateCode, 'function', 'shouldRegenerateCode method');
  assertType(cascadeInstance.regenerateCode, 'function', 'regenerateCode method');
  assertType(cascadeInstance.shouldRegenerateStory, 'function', 'shouldRegenerateStory method');
  assertType(cascadeInstance.regenerateStory, 'function', 'regenerateStory method');
  assertType(cascadeInstance.rollback, 'function', 'rollback method');
});

test('SyncCascade has config methods', () => {
  assertType(cascadeInstance.updateConfig, 'function', 'updateConfig method');
  assertType(cascadeInstance.isEnabled, 'function', 'isEnabled method');
});

test('SyncCascade isEnabled returns boolean', () => {
  const enabled = cascadeInstance.isEnabled();
  assertType(enabled, 'boolean', 'isEnabled return');
});

test('SyncCascade updateConfig works', () => {
  cascadeInstance.updateConfig({ enabled: false });
  assertEqual(cascadeInstance.isEnabled(), false, 'isEnabled after disable');
  cascadeInstance.updateConfig({ enabled: true });
  assertEqual(cascadeInstance.isEnabled(), true, 'isEnabled after enable');
});

test('SyncCascade is an EventEmitter', () => {
  assertType(cascadeInstance.on, 'function', 'on method');
  assertType(cascadeInstance.emit, 'function', 'emit method');
});

// =====================================================
// TEST 3: AutoSyncManager Integration
// =====================================================
console.log('\n3. AutoSyncManager Integration');

let AutoSyncManager;
test('auto-sync-manager.js exists', () => {
  const filePath = path.join(__dirname, 'auto-sync-manager.js');
  if (!fs.existsSync(filePath)) {
    throw new Error('File not found');
  }
});

test('AutoSyncManager imports correctly', () => {
  AutoSyncManager = require('./auto-sync-manager');
  assertExists(AutoSyncManager, 'AutoSyncManager');
});

test('AutoSyncManager exports SyncStatus and TriggerType', () => {
  assertExists(AutoSyncManager.SyncStatus, 'SyncStatus');
  assertExists(AutoSyncManager.TriggerType, 'TriggerType');
});

let autoSyncInstance;
test('AutoSyncManager instantiates with cascade', () => {
  autoSyncInstance = new AutoSyncManager({
    outputDir: '.design',
    cascadeEnabled: true
  });
  assertExists(autoSyncInstance, 'instance');
});

test('AutoSyncManager has syncCascade instance', () => {
  assertExists(autoSyncInstance.syncCascade, 'syncCascade property');
});

test('AutoSyncManager has cascadeEnabled flag', () => {
  assertExists(autoSyncInstance.cascadeEnabled, 'cascadeEnabled');
  assertEqual(autoSyncInstance.cascadeEnabled, true, 'cascadeEnabled value');
});

test('AutoSyncManager has getCascadeConfig method', () => {
  assertType(autoSyncInstance.getCascadeConfig, 'function', 'getCascadeConfig');
});

test('AutoSyncManager has setCascadeEnabled method', () => {
  assertType(autoSyncInstance.setCascadeEnabled, 'function', 'setCascadeEnabled');
});

test('AutoSyncManager has findAffectedComponents method', () => {
  assertType(autoSyncInstance.findAffectedComponents, 'function', 'findAffectedComponents');
});

test('AutoSyncManager has extractComponentData method', () => {
  assertType(autoSyncInstance.extractComponentData, 'function', 'extractComponentData');
});

// =====================================================
// TEST 4: getCascadeConfig Method
// =====================================================
console.log('\n4. getCascadeConfig Method');

test('getCascadeConfig returns object', () => {
  const config = autoSyncInstance.getCascadeConfig();
  assertType(config, 'object', 'config type');
});

test('getCascadeConfig has CASCADE_DEFAULTS values', () => {
  const config = autoSyncInstance.getCascadeConfig();
  assertEqual(config.enabled, CASCADE_DEFAULTS.enabled, 'enabled');
  assertEqual(config.maxCascadesPerSync, CASCADE_DEFAULTS.maxCascadesPerSync, 'maxCascadesPerSync');
  assertEqual(config.cascadeTimeout, CASCADE_DEFAULTS.cascadeTimeout, 'cascadeTimeout');
});

// =====================================================
// TEST 5: setCascadeEnabled Method
// =====================================================
console.log('\n5. setCascadeEnabled Method');

test('setCascadeEnabled disables cascade', () => {
  autoSyncInstance.setCascadeEnabled(false);
  assertEqual(autoSyncInstance.cascadeEnabled, false, 'cascadeEnabled after disable');
});

test('setCascadeEnabled enables cascade', () => {
  autoSyncInstance.setCascadeEnabled(true);
  assertEqual(autoSyncInstance.cascadeEnabled, true, 'cascadeEnabled after enable');
});

// =====================================================
// TEST 6: findAffectedComponents Method
// =====================================================
console.log('\n6. findAffectedComponents Method');

test('findAffectedComponents returns array', () => {
  const result = autoSyncInstance.findAffectedComponents('test-file-key', {});
  if (!Array.isArray(result)) {
    throw new Error(`Expected array, got ${typeof result}`);
  }
});

test('findAffectedComponents handles missing registry gracefully', () => {
  // Should not throw, returns empty array
  const result = autoSyncInstance.findAffectedComponents('nonexistent', {});
  assertEqual(result.length, 0, 'empty result for missing registry');
});

// =====================================================
// TEST 7: extractComponentData Method
// =====================================================
console.log('\n7. extractComponentData Method');

test('extractComponentData returns object with expected properties', () => {
  const registryEntry = {
    name: 'TestButton',
    source: { type: 'figma' },
    tokenDependencies: {}
  };
  const result = autoSyncInstance.extractComponentData({}, 'test-id', registryEntry);

  assertType(result, 'object', 'result type');
  assertEqual(result.id, 'test-id', 'id');
  assertEqual(result.name, 'TestButton', 'name');
  assertExists(result.tokens, 'tokens');
  assertExists(result.styles, 'styles');
});

test('extractComponentData extracts tokens from extractedData', () => {
  const extractedData = {
    components: {
      'test-id': { color: '#fff' }
    },
    tokens: {
      colors: { primary: '#007bff' }
    }
  };
  const registryEntry = {
    name: 'TestButton',
    source: { type: 'figma' },
    tokenDependencies: { colors: true }
  };

  const result = autoSyncInstance.extractComponentData(extractedData, 'test-id', registryEntry);
  assertExists(result.tokens.colors, 'extracted colors');
});

// =====================================================
// TEST 8: Event Forwarding
// =====================================================
console.log('\n8. Event Forwarding');

test('AutoSyncManager forwards cascade:started event', (done) => {
  let eventReceived = false;

  autoSyncInstance.once('cascade:started', () => {
    eventReceived = true;
  });

  // Emit from syncCascade
  autoSyncInstance.syncCascade.emit('cascade:started', { componentId: 'test' });

  if (!eventReceived) {
    throw new Error('Event not forwarded');
  }
});

test('AutoSyncManager forwards cascade:completed event', () => {
  let eventReceived = false;

  autoSyncInstance.once('cascade:completed', () => {
    eventReceived = true;
  });

  autoSyncInstance.syncCascade.emit('cascade:completed', { componentId: 'test' });

  if (!eventReceived) {
    throw new Error('Event not forwarded');
  }
});

test('AutoSyncManager forwards cascade:failed event', () => {
  let eventReceived = false;

  autoSyncInstance.once('cascade:failed', () => {
    eventReceived = true;
  });

  autoSyncInstance.syncCascade.emit('cascade:failed', { componentId: 'test', error: 'test error' });

  if (!eventReceived) {
    throw new Error('Event not forwarded');
  }
});

// =====================================================
// TEST 9: CLI Flag Definition
// =====================================================
console.log('\n9. CLI Flag Definition');

test('cli.js exists', () => {
  const filePath = path.join(__dirname, 'cli.js');
  if (!fs.existsSync(filePath)) {
    throw new Error('File not found');
  }
});

test('cli.js contains --no-cascade flag', () => {
  const cliContent = fs.readFileSync(path.join(__dirname, 'cli.js'), 'utf8');
  if (!cliContent.includes('--no-cascade')) {
    throw new Error('--no-cascade flag not found');
  }
});

test('--no-cascade flag is in sync command options', () => {
  const cliContent = fs.readFileSync(path.join(__dirname, 'cli.js'), 'utf8');
  // Check that it appears in the sync command section
  const syncSectionMatch = cliContent.match(/sync:\s*\{[\s\S]*?options:\s*\[[\s\S]*?--no-cascade[\s\S]*?\]/);
  if (!syncSectionMatch) {
    throw new Error('--no-cascade not in sync command options');
  }
});

// =====================================================
// TEST 10: Dependency Imports in SyncCascade
// =====================================================
console.log('\n10. Dependency Imports in SyncCascade');

test('SyncCascade has ContentHasher dependency', () => {
  assertExists(cascadeInstance.contentHasher, 'contentHasher');
});

test('SyncCascade has StoryHashRegistry dependency', () => {
  assertExists(cascadeInstance.storyHashRegistry, 'storyHashRegistry');
});

test('SyncCascade has ConflictResolver dependency', () => {
  assertExists(cascadeInstance.conflictResolver, 'conflictResolver');
});

test('SyncCascade has DiffEngine dependency', () => {
  assertExists(cascadeInstance.diffEngine, 'diffEngine');
});

test('SyncCascade has SnapshotManager dependency', () => {
  assertExists(cascadeInstance.snapshotManager, 'snapshotManager');
});

test('SyncCascade has TransformStateUpdater dependency', () => {
  assertExists(cascadeInstance.stateUpdater, 'stateUpdater');
});

// =====================================================
// TEST 11: SyncCascade Configuration
// =====================================================
console.log('\n11. SyncCascade Configuration');

test('SyncCascade has config property', () => {
  assertExists(cascadeInstance.config, 'config');
});

test('SyncCascade config has default values', () => {
  assertEqual(cascadeInstance.config.enabled, true, 'enabled');
  assertEqual(cascadeInstance.config.maxCascadesPerSync, 10, 'maxCascadesPerSync');
});

test('SyncCascade accepts config overrides', () => {
  const customCascade = new SyncCascade({
    projectPath: __dirname,
    config: {
      maxCascadesPerSync: 5,
      cascadeTimeout: 60000
    }
  });
  assertEqual(customCascade.config.maxCascadesPerSync, 5, 'custom maxCascadesPerSync');
  assertEqual(customCascade.config.cascadeTimeout, 60000, 'custom cascadeTimeout');
});

// =====================================================
// TEST 12: Integration with Existing Modules
// =====================================================
console.log('\n12. Integration with Existing Modules');

test('content-hasher.js exports required functions', () => {
  const { ContentHasher, hashFile, hasFileChanged } = require('./content-hasher');
  assertExists(ContentHasher, 'ContentHasher');
  assertType(hashFile, 'function', 'hashFile');
  assertType(hasFileChanged, 'function', 'hasFileChanged');
});

test('story-hash-registry.js exports StoryHashRegistry', () => {
  const { StoryHashRegistry } = require('./story-hash-registry');
  assertExists(StoryHashRegistry, 'StoryHashRegistry');
});

test('conflict-resolver.js exports ConflictResolver', () => {
  const ConflictResolver = require('./conflict-resolver');
  assertExists(ConflictResolver, 'ConflictResolver');
});

test('incremental-processor.js exports DiffEngine and SnapshotManager', () => {
  const { DiffEngine, SnapshotManager } = require('./incremental-processor');
  assertExists(DiffEngine, 'DiffEngine');
  assertExists(SnapshotManager, 'SnapshotManager');
});

test('transform-state-updater.js exports TransformStateUpdater', () => {
  const { TransformStateUpdater } = require('./transform-state-updater');
  assertExists(TransformStateUpdater, 'TransformStateUpdater');
});

test('registry-reader.js exports required functions', () => {
  const { readComponentRegistry, writeComponentRegistry } = require('./registry-reader');
  assertType(readComponentRegistry, 'function', 'readComponentRegistry');
  assertType(writeComponentRegistry, 'function', 'writeComponentRegistry');
});

// =====================================================
// RESULTS SUMMARY
// =====================================================
console.log('\n' + '='.repeat(50));
console.log('TEST RESULTS SUMMARY');
console.log('='.repeat(50));
console.log(`\n  Total:  ${results.passed + results.failed}`);
console.log(`  Passed: ${results.passed} ✅`);
console.log(`  Failed: ${results.failed} ❌`);

if (results.failed > 0) {
  console.log('\nFailed Tests:');
  results.errors.forEach((err, i) => {
    console.log(`  ${i + 1}. ${err.name}`);
    console.log(`     Error: ${err.error}`);
  });
}

console.log('\n' + '='.repeat(50));

// Exit with error code if tests failed
if (results.failed > 0) {
  process.exit(1);
}

console.log('\n✅ All Phase 4 tests passed!\n');
