/**
 * Phase 8: Manual Sync UI - Integration Test
 * Tests all components of the "Sync Now" button feature
 */

const fs = require('fs');
const path = require('path');

console.log('\n' + '='.repeat(60));
console.log('  PHASE 8: Manual Sync UI - Integration Test');
console.log('='.repeat(60) + '\n');

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log('✅ ' + name);
    passed++;
  } catch (err) {
    console.log('❌ ' + name + ': ' + err.message);
    failed++;
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

// Paths
const serverDir = __dirname;
const pluginDir = path.join(serverDir, '../figma-plugin');
const uiHtmlPath = path.join(pluginDir, 'src/ui.html');
const codeTsPath = path.join(pluginDir, 'code.ts');
const autoSyncPath = path.join(serverDir, 'auto-sync-manager.js');

// Load file contents
const uiHtml = fs.readFileSync(uiHtmlPath, 'utf8');
const codeTs = fs.readFileSync(codeTsPath, 'utf8');
const autoSyncJs = fs.readFileSync(autoSyncPath, 'utf8');

console.log('--- AutoSyncManager Tests ---\n');

test('AutoSyncManager exports correctly', () => {
  const AutoSyncManager = require('./auto-sync-manager');
  assert(typeof AutoSyncManager === 'function', 'Should be a constructor');
});

test('AutoSyncManager.prototype.triggerManualSync exists', () => {
  const AutoSyncManager = require('./auto-sync-manager');
  assert(typeof AutoSyncManager.prototype.triggerManualSync === 'function', 'Should be a function');
});

test('AutoSyncManager.prototype.resetIntervalTimer exists', () => {
  const AutoSyncManager = require('./auto-sync-manager');
  assert(typeof AutoSyncManager.prototype.resetIntervalTimer === 'function', 'Should be a function');
});

test('AutoSyncManager instantiates correctly', () => {
  const AutoSyncManager = require('./auto-sync-manager');
  const manager = new AutoSyncManager({ projectPath: '/tmp/test-project' });
  assert(manager !== null, 'Should instantiate');
  assert(typeof manager.triggerManualSync === 'function', 'Should have triggerManualSync');
  assert(typeof manager.resetIntervalTimer === 'function', 'Should have resetIntervalTimer');
});

test('TriggerType.MANUAL is defined', () => {
  assert(autoSyncJs.includes('MANUAL:'), 'Should have MANUAL trigger type');
});

test('AutoSyncManager emits sync:manual event', () => {
  assert(autoSyncJs.includes("emit('sync:manual'"), 'Should emit sync:manual event');
});

test('triggerManualSync calls resetIntervalTimer', () => {
  const match = autoSyncJs.match(/async triggerManualSync[\s\S]*?resetIntervalTimer/);
  assert(match, 'Should call resetIntervalTimer in triggerManualSync');
});

console.log('\n--- UI HTML Structure Tests ---\n');

test('UI HTML has sync-now-btn button', () => {
  assert(uiHtml.includes('id="sync-now-btn"'), 'Should have sync-now-btn element');
});

test('UI HTML has sync-now-button CSS class', () => {
  assert(uiHtml.includes('.sync-now-button'), 'Should have .sync-now-button CSS');
});

test('UI HTML has sync-now-button hover state', () => {
  assert(uiHtml.includes('.sync-now-button:hover'), 'Should have hover state');
});

test('UI HTML has sync-now-button syncing state', () => {
  assert(uiHtml.includes('.sync-now-button.syncing'), 'Should have syncing state');
});

test('UI has disabled button styles', () => {
  assert(uiHtml.includes('.sync-now-button:disabled'), 'Should have :disabled styles');
});

test('UI button has sync icon SVG', () => {
  assert(uiHtml.includes('class="sync-icon"'), 'Should have sync-icon class');
});

test('UI button has countdown span', () => {
  assert(uiHtml.includes('class="sync-countdown"'), 'Should have sync-countdown span');
});

console.log('\n--- UI JavaScript Function Tests ---\n');

test('UI has updateSyncNowButtonState function', () => {
  assert(uiHtml.includes('function updateSyncNowButtonState()'), 'Should have updateSyncNowButtonState');
});

test('UI has handleManualSyncComplete function', () => {
  assert(uiHtml.includes('function handleManualSyncComplete()'), 'Should have handleManualSyncComplete');
});

test('UI has handleManualSyncFailed function', () => {
  assert(uiHtml.includes('function handleManualSyncFailed'), 'Should have handleManualSyncFailed');
});

test('UI has click handler for sync-now-btn', () => {
  assert(uiHtml.includes("getElementById('sync-now-btn')?.addEventListener('click'"), 'Should have click handler');
});

test('UI checks connection state for button enable/disable', () => {
  assert(uiHtml.includes("data-state') === 'connected'"), 'Should check connected state');
});

console.log('\n--- UI Message Handler Tests ---\n');

test('UI handles manual-sync-completed message', () => {
  assert(uiHtml.includes("case 'manual-sync-completed':"), 'Should handle manual-sync-completed');
});

test('UI handles manual-sync-failed message', () => {
  assert(uiHtml.includes("case 'manual-sync-failed':"), 'Should handle manual-sync-failed');
});

console.log('\n--- Plugin code.ts Tests ---\n');

test('Plugin code.ts has manual-sync-trigger handler', () => {
  assert(codeTs.includes("case 'manual-sync-trigger':"), 'Should have manual-sync-trigger handler');
});

test('Plugin sends manual-sync-completed message', () => {
  assert(codeTs.includes("type: 'manual-sync-completed'"), 'Should send manual-sync-completed');
});

test('Plugin sends manual-sync-failed message', () => {
  assert(codeTs.includes("type: 'manual-sync-failed'"), 'Should send manual-sync-failed');
});

test('Plugin sets manual: true in metadata', () => {
  assert(codeTs.includes('manual: true'), 'Should set manual: true');
});

console.log('\n' + '='.repeat(60));
console.log(`  Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(60) + '\n');

if (failed > 0) {
  process.exit(1);
} else {
  console.log('✅ All Phase 8 tests passed!\n');
}
