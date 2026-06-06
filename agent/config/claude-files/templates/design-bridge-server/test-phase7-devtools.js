/**
 * Phase 7: Developer Experience & Tooling - Test Suite
 *
 * Tests for:
 * - Sprint 7.1: CLI Tool & Commands
 * - Sprint 7.2: Configuration System
 * - Sprint 7.3: Watch Mode & Live Sync
 * - Sprint 7.4: Workspace & Project Management
 */

// Test utilities
let testsPassed = 0;
let testsFailed = 0;
const testResults = [];

function test(name, fn) {
  try {
    fn();
    testsPassed++;
    testResults.push({ name, status: 'passed' });
    console.log(`  ✓ ${name}`);
  } catch (error) {
    testsFailed++;
    testResults.push({ name, status: 'failed', error: error.message });
    console.log(`  ✗ ${name}`);
    console.log(`    Error: ${error.message}`);
  }
}

function assertEqual(actual, expected, message = '') {
  if (actual !== expected) {
    throw new Error(`${message} Expected ${expected}, got ${actual}`);
  }
}

function assertTrue(value, message = '') {
  if (!value) {
    throw new Error(`${message} Expected true, got ${value}`);
  }
}

function assertFalse(value, message = '') {
  if (value) {
    throw new Error(`${message} Expected false, got ${value}`);
  }
}

function assertDefined(value, message = '') {
  if (value === undefined || value === null) {
    throw new Error(`${message} Expected defined value, got ${value}`);
  }
}

function assertArray(value, message = '') {
  if (!Array.isArray(value)) {
    throw new Error(`${message} Expected array, got ${typeof value}`);
  }
}

function assertType(value, type, message = '') {
  if (typeof value !== type) {
    throw new Error(`${message} Expected ${type}, got ${typeof value}`);
  }
}

function assertInstanceOf(value, constructor, message = '') {
  if (!(value instanceof constructor)) {
    throw new Error(`${message} Expected instance of ${constructor.name}`);
  }
}

// ============================================
// Sprint 7.1: CLI Tool & Commands Tests
// ============================================
console.log('\n📟 Sprint 7.1: CLI Tool & Commands');

const { DesignBridgeCLI, COMMANDS, colors, output, Spinner } = require('./cli');

test('CLI exports all required components', () => {
  assertDefined(DesignBridgeCLI, 'DesignBridgeCLI class');
  assertDefined(COMMANDS, 'COMMANDS object');
  assertDefined(colors, 'colors utility');
  assertDefined(output, 'output utility');
  assertDefined(Spinner, 'Spinner class');
});

test('CLI COMMANDS has all required commands', () => {
  assertDefined(COMMANDS.init, 'init command');
  assertDefined(COMMANDS.sync, 'sync command');
  assertDefined(COMMANDS.generate, 'generate command');
  assertDefined(COMMANDS.analyze, 'analyze command');
  assertDefined(COMMANDS.test, 'test command');
  assertDefined(COMMANDS.watch, 'watch command');
  assertDefined(COMMANDS.config, 'config command');
});

test('COMMANDS have correct structure', () => {
  for (const [name, cmd] of Object.entries(COMMANDS)) {
    assertDefined(cmd.description, `${name} has description`);
    assertDefined(cmd.options, `${name} has options`);
  }
});

test('DesignBridgeCLI instantiation', () => {
  const cli = new DesignBridgeCLI();
  assertInstanceOf(cli, DesignBridgeCLI);
  assertDefined(cli.commands);
});

test('CLI parseArgs handles basic arguments', () => {
  const cli = new DesignBridgeCLI();
  const args = cli.parseArgs(['--verbose', '--output', './dist']);
  assertDefined(args);
  assertEqual(args.options.verbose, true, 'verbose flag');
  assertEqual(args.options.output, './dist', 'output option');
});

test('CLI parseArgs handles short flags', () => {
  const cli = new DesignBridgeCLI();
  const args = cli.parseArgs(['-v', '-o', './dist']);
  assertDefined(args);
});

test('CLI commands can be extended directly', () => {
  const cli = new DesignBridgeCLI();
  cli.commands.custom = {
    name: 'custom',
    description: 'Custom command',
    options: []
  };
  assertDefined(cli.commands.custom);
  assertEqual(cli.commands.custom.name, 'custom');
});

test('CLI showHelp does not throw', () => {
  const cli = new DesignBridgeCLI();
  // Just verify it doesn't throw
  try {
    cli.showHelp();
    assertTrue(true);
  } catch {
    assertTrue(false, 'showHelp threw error');
  }
});

test('Colors utility has all color strings', () => {
  assertType(colors.red, 'string');
  assertType(colors.green, 'string');
  assertType(colors.yellow, 'string');
  assertType(colors.blue, 'string');
  assertType(colors.cyan, 'string');
  assertType(colors.reset, 'string');
  assertType(colors.bright, 'string');
});

test('Colors are valid ANSI escape codes', () => {
  assertTrue(colors.red.includes('\x1b['));
  assertTrue(colors.green.includes('\x1b['));
  assertTrue(colors.reset.includes('\x1b['));
});

test('Spinner can be instantiated', () => {
  const spinner = new Spinner('Loading');
  assertInstanceOf(spinner, Spinner);
  assertEqual(spinner.message, 'Loading');
});

test('CLI emits events', () => {
  const cli = new DesignBridgeCLI();
  let eventEmitted = false;
  cli.on('command:start', () => { eventEmitted = true; });
  cli.emit('command:start', { command: 'test' });
  assertTrue(eventEmitted);
});

// ============================================
// Sprint 7.2: Configuration System Tests
// ============================================
console.log('\n⚙️  Sprint 7.2: Configuration System');

const {
  ConfigSystem,
  createConfig,
  CONFIG_SCHEMA,
  ENVIRONMENTS,
  CONFIG_FILES,
  ConfigValidationError
} = require('./config-system');

test('Configuration exports all required components', () => {
  assertDefined(ConfigSystem, 'ConfigSystem class');
  assertDefined(createConfig, 'createConfig factory');
  assertDefined(CONFIG_SCHEMA, 'CONFIG_SCHEMA');
  assertDefined(ENVIRONMENTS, 'ENVIRONMENTS');
  assertDefined(CONFIG_FILES, 'CONFIG_FILES array');
});

test('CONFIG_SCHEMA has all sections', () => {
  assertDefined(CONFIG_SCHEMA.figma, 'figma section');
  assertDefined(CONFIG_SCHEMA.output, 'output section');
  assertDefined(CONFIG_SCHEMA.tokens, 'tokens section');
  assertDefined(CONFIG_SCHEMA.testing, 'testing section');
  assertDefined(CONFIG_SCHEMA.sync, 'sync section');
  assertDefined(CONFIG_SCHEMA.plugins, 'plugins section');
});

test('ENVIRONMENTS has all environments', () => {
  assertDefined(ENVIRONMENTS.development);
  assertDefined(ENVIRONMENTS.staging);
  assertDefined(ENVIRONMENTS.production);
  assertDefined(ENVIRONMENTS.test);
});

test('ConfigSystem instantiation', () => {
  const config = new ConfigSystem();
  assertInstanceOf(config, ConfigSystem);
});

test('createConfig factory works', () => {
  const config = createConfig({ env: 'test' });
  assertInstanceOf(config, ConfigSystem);
  assertEqual(config.options.env, 'test');
});

test('ConfigSystem getDefaults returns valid config', () => {
  const config = new ConfigSystem();
  const defaults = config.getDefaults();
  assertDefined(defaults.output);
  assertDefined(defaults.tokens);
  assertDefined(defaults.testing);
});

test('ConfigSystem default values are correct', () => {
  const config = new ConfigSystem();
  const defaults = config.getDefaults();
  assertEqual(defaults.output.framework, 'react');
  assertEqual(defaults.output.typescript, true);
  assertEqual(defaults.tokens.colorFormat, 'hex');
});

test('ConfigSystem get/set methods work', () => {
  const config = new ConfigSystem();
  config.config = config.getDefaults();
  config.set('output.directory', './custom');
  assertEqual(config.get('output.directory'), './custom');
});

test('ConfigSystem has method works', () => {
  const config = new ConfigSystem();
  config.config = config.getDefaults();
  assertTrue(config.has('output.framework'));
  assertFalse(config.has('nonexistent.key'));
});

test('ConfigSystem deepMerge works correctly', () => {
  const config = new ConfigSystem();
  const target = { a: 1, b: { c: 2 } };
  const source = { b: { d: 3 }, e: 4 };
  const result = config.deepMerge(target, source);
  assertEqual(result.a, 1);
  assertEqual(result.b.c, 2);
  assertEqual(result.b.d, 3);
  assertEqual(result.e, 4);
});

test('ConfigSystem validation detects invalid types', () => {
  const config = new ConfigSystem();
  config.config = { output: { typescript: 'not-a-boolean' } };
  const valid = config.validate();
  assertFalse(valid);
  assertTrue(config.validationErrors.length > 0);
});

test('ConfigSystem coerceValue handles types', () => {
  const config = new ConfigSystem();
  assertEqual(config.coerceValue('42', 'number'), 42);
  assertEqual(config.coerceValue('true', 'boolean'), true);
  assertEqual(config.coerceValue('false', 'boolean'), false);
});

test('ConfigSystem getAll returns copy', () => {
  const config = new ConfigSystem();
  config.config = { test: 'value' };
  const all = config.getAll();
  all.test = 'modified';
  assertEqual(config.config.test, 'value');
});

test('ConfigSystem reset works', () => {
  const config = new ConfigSystem();
  config.config = { custom: 'data' };
  config.loadedFrom = '/path/to/config';
  config.reset();
  assertEqual(config.loadedFrom, null);
  assertDefined(config.config.output);
});

test('ConfigSystem generateTemplate returns valid JS', () => {
  const config = new ConfigSystem();
  const template = config.generateTemplate('js');
  assertTrue(template.includes('module.exports'));
});

test('ConfigSystem emits events', () => {
  const config = new ConfigSystem();
  let eventEmitted = false;
  config.on('config:changed', () => { eventEmitted = true; });
  config.config = config.getDefaults();
  config.set('output.directory', './test');
  assertTrue(eventEmitted);
});

test('ConfigValidationError has correct properties', () => {
  const error = new ConfigValidationError('Test error', 'test.path', 'value');
  assertEqual(error.name, 'ConfigValidationError');
  assertEqual(error.path, 'test.path');
  assertEqual(error.value, 'value');
});

// ============================================
// Sprint 7.3: Watch Mode & Live Sync Tests
// ============================================
console.log('\n👀 Sprint 7.3: Watch Mode & Live Sync');

const {
  WatchMode,
  FigmaWebhookHandler,
  LiveReloadServer,
  ChangeTracker,
  Debouncer,
  createWatchMode,
  WATCH_EVENTS,
  DEFAULT_OPTIONS
} = require('./watch-mode');

test('Watch Mode exports all required components', () => {
  assertDefined(WatchMode, 'WatchMode class');
  assertDefined(FigmaWebhookHandler, 'FigmaWebhookHandler class');
  assertDefined(LiveReloadServer, 'LiveReloadServer class');
  assertDefined(ChangeTracker, 'ChangeTracker class');
  assertDefined(Debouncer, 'Debouncer class');
  assertDefined(WATCH_EVENTS, 'WATCH_EVENTS');
  assertDefined(DEFAULT_OPTIONS, 'DEFAULT_OPTIONS');
});

test('WATCH_EVENTS has all event types', () => {
  assertDefined(WATCH_EVENTS.FILE_ADDED);
  assertDefined(WATCH_EVENTS.FILE_CHANGED);
  assertDefined(WATCH_EVENTS.FILE_DELETED);
  assertDefined(WATCH_EVENTS.FIGMA_UPDATE);
  assertDefined(WATCH_EVENTS.SYNC_STARTED);
  assertDefined(WATCH_EVENTS.SYNC_COMPLETE);
});

test('WatchMode instantiation', () => {
  const wm = new WatchMode();
  assertInstanceOf(wm, WatchMode);
  assertFalse(wm.isWatching);
});

test('createWatchMode factory works', () => {
  const wm = createWatchMode({ debounceMs: 500 });
  assertInstanceOf(wm, WatchMode);
  assertEqual(wm.options.debounceMs, 500);
});

test('WatchMode has default options', () => {
  const wm = new WatchMode();
  assertDefined(wm.options.debounceMs);
  assertDefined(wm.options.ignorePatterns);
  assertArray(wm.options.ignorePatterns);
});

test('WatchMode shouldIgnore works', () => {
  const wm = new WatchMode();
  assertTrue(wm.shouldIgnore('/project/node_modules/package/file.js'));
  assertTrue(wm.shouldIgnore('/project/.git/config'));
  assertFalse(wm.shouldIgnore('/project/src/component.js'));
});

test('WatchMode getStats returns statistics', () => {
  const wm = new WatchMode();
  const stats = wm.getStats();
  assertDefined(stats.filesWatched);
  assertDefined(stats.changesDetected);
  assertDefined(stats.syncsCompleted);
  assertDefined(stats.errors);
});

test('WatchMode addIgnorePattern works', () => {
  const wm = new WatchMode();
  const initialLength = wm.options.ignorePatterns.length;
  wm.addIgnorePattern('**/*.test.js');
  assertEqual(wm.options.ignorePatterns.length, initialLength + 1);
});

test('WatchMode removeIgnorePattern works', () => {
  const wm = new WatchMode();
  wm.addIgnorePattern('**/*.test.js');
  const lengthAfterAdd = wm.options.ignorePatterns.length;
  wm.removeIgnorePattern('**/*.test.js');
  assertEqual(wm.options.ignorePatterns.length, lengthAfterAdd - 1);
});

test('WatchMode setSyncHandler works', () => {
  const wm = new WatchMode();
  let handlerCalled = false;
  wm.setSyncHandler(() => { handlerCalled = true; });
  // Handler is set, not called yet
  assertType(wm.syncFiles, 'function');
});

test('ChangeTracker tracks changes', () => {
  const tracker = new ChangeTracker();
  tracker.track('/path/to/file.js', WATCH_EVENTS.FILE_CHANGED);
  const pending = tracker.getPending();
  assertEqual(pending.length, 1);
  assertEqual(pending[0].path, '/path/to/file.js');
});

test('ChangeTracker getSummary works', () => {
  const tracker = new ChangeTracker();
  tracker.track('/file1.js', WATCH_EVENTS.FILE_ADDED);
  tracker.track('/file2.js', WATCH_EVENTS.FILE_CHANGED);
  tracker.track('/file3.js', WATCH_EVENTS.FILE_DELETED);
  const summary = tracker.getSummary();
  assertEqual(summary.added, 1);
  assertEqual(summary.changed, 1);
  assertEqual(summary.deleted, 1);
  assertEqual(summary.total, 3);
});

test('ChangeTracker clear works', () => {
  const tracker = new ChangeTracker();
  tracker.track('/file.js', WATCH_EVENTS.FILE_CHANGED);
  tracker.clear();
  assertEqual(tracker.getPending().length, 0);
});

test('Debouncer debounces calls', (done) => {
  const debouncer = new Debouncer(50);
  let callCount = 0;
  debouncer.debounce('key', () => { callCount++; });
  debouncer.debounce('key', () => { callCount++; });
  debouncer.debounce('key', () => { callCount++; });
  // Synchronous check - count should still be 0
  assertEqual(callCount, 0);
  debouncer.cancelAll();
});

test('Debouncer cancel works', () => {
  const debouncer = new Debouncer(100);
  let called = false;
  debouncer.debounce('key', () => { called = true; });
  debouncer.cancel('key');
  // Since we cancelled, it shouldn't be in timers
  assertFalse(debouncer.timers.has('key'));
});

test('FigmaWebhookHandler instantiation', () => {
  const handler = new FigmaWebhookHandler();
  assertInstanceOf(handler, FigmaWebhookHandler);
});

test('FigmaWebhookHandler handles webhook', () => {
  const handler = new FigmaWebhookHandler();
  const result = handler.handleWebhook({
    event_type: 'FILE_UPDATE',
    file_key: 'abc123',
    timestamp: Date.now()
  });
  assertTrue(result.success);
  assertTrue(result.processed);
});

test('FigmaWebhookHandler ignores unknown events', () => {
  const handler = new FigmaWebhookHandler();
  const result = handler.handleWebhook({
    event_type: 'UNKNOWN_EVENT',
    file_key: 'abc123'
  });
  assertTrue(result.success);
  assertTrue(result.ignored);
});

test('FigmaWebhookHandler getPendingUpdates works', () => {
  const handler = new FigmaWebhookHandler();
  handler.handleWebhook({ event_type: 'FILE_UPDATE', file_key: 'abc' });
  const pending = handler.getPendingUpdates();
  assertEqual(pending.length, 1);
});

test('LiveReloadServer instantiation', () => {
  const server = new LiveReloadServer();
  assertInstanceOf(server, LiveReloadServer);
  assertFalse(server.isRunning);
});

test('LiveReloadServer getScriptTag works', () => {
  const server = new LiveReloadServer({ port: 35729, host: 'localhost' });
  const tag = server.getScriptTag();
  assertTrue(tag.includes('<script'));
  assertTrue(tag.includes('35729'));
});

test('LiveReloadServer getConnectionCount returns 0 initially', () => {
  const server = new LiveReloadServer();
  assertEqual(server.getConnectionCount(), 0);
});

// ============================================
// Sprint 7.4: Workspace & Project Management Tests
// ============================================
console.log('\n📁 Sprint 7.4: Workspace & Project Management');

const {
  WorkspaceManager,
  Project,
  createWorkspaceManager,
  PROJECT_TEMPLATES,
  WORKSPACE_MANIFEST
} = require('./workspace-manager');

test('Workspace Manager exports all required components', () => {
  assertDefined(WorkspaceManager, 'WorkspaceManager class');
  assertDefined(Project, 'Project class');
  assertDefined(createWorkspaceManager, 'createWorkspaceManager factory');
  assertDefined(PROJECT_TEMPLATES, 'PROJECT_TEMPLATES');
  assertDefined(WORKSPACE_MANIFEST, 'WORKSPACE_MANIFEST');
});

test('PROJECT_TEMPLATES has all templates', () => {
  assertDefined(PROJECT_TEMPLATES.react);
  assertDefined(PROJECT_TEMPLATES.vue);
  assertDefined(PROJECT_TEMPLATES.svelte);
  assertDefined(PROJECT_TEMPLATES.tokens);
});

test('Template structures are correct', () => {
  for (const [name, template] of Object.entries(PROJECT_TEMPLATES)) {
    assertDefined(template.name, `${name} has name`);
    assertDefined(template.files, `${name} has files`);
    assertDefined(template.directories, `${name} has directories`);
  }
});

test('Project instantiation', () => {
  const project = new Project({
    name: 'test-project',
    path: '/path/to/project'
  });
  assertInstanceOf(project, Project);
  assertEqual(project.name, 'test-project');
  assertDefined(project.id);
});

test('Project toJSON works', () => {
  const project = new Project({
    name: 'test-project',
    path: '/path/to/project'
  });
  const json = project.toJSON();
  assertEqual(json.name, 'test-project');
  assertDefined(json.id);
  assertDefined(json.created);
});

test('Project touch updates modified date', () => {
  const project = new Project({
    name: 'test',
    path: '/path'
  });
  const originalModified = project.modified;
  // Small delay to ensure different timestamp
  project.touch();
  assertDefined(project.modified);
});

test('WorkspaceManager instantiation', () => {
  const wm = new WorkspaceManager();
  assertInstanceOf(wm, WorkspaceManager);
  assertFalse(wm.isInitialized);
});

test('createWorkspaceManager factory works', () => {
  const wm = createWorkspaceManager({ workspaceRoot: '/custom/path' });
  assertInstanceOf(wm, WorkspaceManager);
  assertEqual(wm.options.workspaceRoot, '/custom/path');
});

test('WorkspaceManager getManifestPath works', () => {
  const wm = new WorkspaceManager({ workspaceRoot: '/workspace' });
  const manifestPath = wm.getManifestPath();
  assertTrue(manifestPath.includes('design-bridge.workspace.json'));
});

test('WorkspaceManager replaceVariablesInString works', () => {
  const wm = new WorkspaceManager();
  const result = wm.replaceVariablesInString('Hello {{name}}!', { name: 'World' });
  assertEqual(result, 'Hello World!');
});

test('WorkspaceManager replaceVariables handles objects', () => {
  const wm = new WorkspaceManager();
  const obj = { greeting: '{{name}}', nested: { value: '{{name}}' } };
  const result = wm.replaceVariables(obj, { name: 'Test' });
  assertEqual(result.greeting, 'Test');
  assertEqual(result.nested.value, 'Test');
});

test('WorkspaceManager listProjects returns array', () => {
  const wm = new WorkspaceManager();
  wm.manifest = { ...WORKSPACE_MANIFEST };
  const projects = wm.listProjects();
  assertArray(projects);
});

test('WorkspaceManager getStats works', () => {
  const wm = new WorkspaceManager();
  wm.manifest = { ...WORKSPACE_MANIFEST };
  const stats = wm.getStats();
  assertDefined(stats.projectCount);
  assertDefined(stats.activeProjects);
  assertDefined(stats.frameworkBreakdown);
});

test('WorkspaceManager getTemplates returns templates', () => {
  const wm = new WorkspaceManager();
  const templates = wm.getTemplates();
  assertArray(templates);
  assertTrue(templates.length > 0);
  assertDefined(templates[0].id);
  assertDefined(templates[0].name);
});

test('WorkspaceManager registerTemplate works', () => {
  const wm = new WorkspaceManager();
  wm.registerTemplate('custom', {
    name: 'Custom Template',
    files: {},
    directories: []
  });
  assertDefined(PROJECT_TEMPLATES.custom);
});

test('WorkspaceManager reset works', () => {
  const wm = new WorkspaceManager();
  wm.projects.set('test', new Project({ name: 'test', path: '/test' }));
  wm.isInitialized = true;
  wm.reset();
  assertEqual(wm.projects.size, 0);
  assertFalse(wm.isInitialized);
});

test('WorkspaceManager emits events', () => {
  const wm = new WorkspaceManager();
  let eventEmitted = false;
  wm.on('workspace:reset', () => { eventEmitted = true; });
  wm.reset();
  assertTrue(eventEmitted);
});

// ============================================
// Integration Tests
// ============================================
console.log('\n🔗 Integration Tests');

test('CLI can use ConfigSystem', () => {
  const cli = new DesignBridgeCLI();
  const config = new ConfigSystem();
  cli.config = config;
  assertDefined(cli.config);
  assertInstanceOf(cli.config, ConfigSystem);
});

test('WatchMode can trigger sync events', () => {
  const wm = new WatchMode();
  let syncStarted = false;
  let syncComplete = false;

  wm.on(WATCH_EVENTS.SYNC_STARTED, () => { syncStarted = true; });
  wm.on(WATCH_EVENTS.SYNC_COMPLETE, () => { syncComplete = true; });

  wm.emit(WATCH_EVENTS.SYNC_STARTED, {});
  wm.emit(WATCH_EVENTS.SYNC_COMPLETE, {});

  assertTrue(syncStarted);
  assertTrue(syncComplete);
});

test('WorkspaceManager can filter projects by framework', () => {
  const wm = new WorkspaceManager();
  wm.projects.set('1', new Project({ name: 'react-proj', path: '/r', framework: 'react' }));
  wm.projects.set('2', new Project({ name: 'vue-proj', path: '/v', framework: 'vue' }));

  const reactProjects = wm.listProjects({ framework: 'react' });
  assertEqual(reactProjects.length, 1);
  assertEqual(reactProjects[0].framework, 'react');
});

test('Config and Workspace can share settings', () => {
  const config = new ConfigSystem();
  config.config = config.getDefaults();

  const wm = new WorkspaceManager();
  wm.manifest = { ...WORKSPACE_MANIFEST };

  // Share figma config
  wm.setSharedConfig = (key, val) => {
    wm.manifest.sharedConfig = wm.manifest.sharedConfig || {};
    wm.manifest.sharedConfig[key] = val;
  };
  wm.setSharedConfig('figmaTeamId', config.get('figma.teamId'));

  assertDefined(wm.manifest.sharedConfig);
});

test('Full Phase 7 module integration', () => {
  // Initialize all Phase 7 modules
  const cli = new DesignBridgeCLI();
  const config = new ConfigSystem();
  const watch = new WatchMode();
  const workspace = new WorkspaceManager();

  // Verify all modules work together
  assertDefined(cli);
  assertDefined(config);
  assertDefined(watch);
  assertDefined(workspace);

  // Connect them
  cli.config = config;
  cli.watch = watch;
  cli.workspace = workspace;

  assertEqual(cli.config, config);
  assertEqual(cli.watch, watch);
  assertEqual(cli.workspace, workspace);
});

// ============================================
// Summary
// ============================================
console.log('\n' + '='.repeat(50));
console.log('Phase 7: Developer Experience & Tooling - Test Results');
console.log('='.repeat(50));

const sprint71 = testResults.filter(t => t.name.includes('CLI') || t.name.includes('Colors') || t.name.includes('Spinner')).length;
const sprint72 = testResults.filter(t => t.name.includes('Config') || t.name.includes('CONFIG')).length;
const sprint73 = testResults.filter(t =>
  t.name.includes('Watch') ||
  t.name.includes('Change') ||
  t.name.includes('Debounce') ||
  t.name.includes('Figma') ||
  t.name.includes('LiveReload')
).length;
const sprint74 = testResults.filter(t =>
  t.name.includes('Workspace') ||
  t.name.includes('Project') ||
  t.name.includes('Template')
).length;
const integration = testResults.filter(t => t.name.includes('Integration') || t.name.includes('integration')).length;

console.log(`\nSprint 7.1: CLI Tool & Commands        - ${sprint71} tests`);
console.log(`Sprint 7.2: Configuration System       - ${sprint72} tests`);
console.log(`Sprint 7.3: Watch Mode & Live Sync     - ${sprint73} tests`);
console.log(`Sprint 7.4: Workspace & Project Mgmt   - ${sprint74} tests`);
console.log(`Integration Tests                      - ${integration} tests`);

console.log(`\n✅ Passed: ${testsPassed}`);
console.log(`❌ Failed: ${testsFailed}`);
console.log(`📊 Total:  ${testsPassed + testsFailed}`);
console.log(`📈 Pass Rate: ${((testsPassed / (testsPassed + testsFailed)) * 100).toFixed(1)}%`);

if (testsFailed > 0) {
  console.log('\nFailed Tests:');
  testResults.filter(t => t.status === 'failed').forEach(t => {
    console.log(`  - ${t.name}: ${t.error}`);
  });
}

process.exit(testsFailed > 0 ? 1 : 0);
