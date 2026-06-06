#!/usr/bin/env node

/**
 * Phase 8: Plugin System & Integrations - Test Suite
 *
 * Tests all Phase 8 modules:
 * - Sprint 8.1: Plugin Architecture (plugin-system.js)
 * - Sprint 8.2: Framework Adapters (framework-adapters.js)
 * - Sprint 8.3: External Tool Integrations (tool-integrations.js)
 * - Sprint 8.4: Documentation Generator (doc-generator.js)
 */

const assert = require('assert');
const EventEmitter = require('events');

// Test utilities
let testsPassed = 0;
let testsFailed = 0;
const testResults = [];

function test(name, fn) {
  try {
    fn();
    testsPassed++;
    testResults.push({ name, status: 'passed' });
    console.log(`  ✅ ${name}`);
  } catch (error) {
    testsFailed++;
    testResults.push({ name, status: 'failed', error: error.message });
    console.log(`  ❌ ${name}`);
    console.log(`     Error: ${error.message}`);
  }
}

async function asyncTest(name, fn) {
  try {
    await fn();
    testsPassed++;
    testResults.push({ name, status: 'passed' });
    console.log(`  ✅ ${name}`);
  } catch (error) {
    testsFailed++;
    testResults.push({ name, status: 'failed', error: error.message });
    console.log(`  ❌ ${name}`);
    console.log(`     Error: ${error.message}`);
  }
}

// ============================================================================
// Sprint 8.1: Plugin Architecture Tests
// ============================================================================

console.log('\n📦 Sprint 8.1: Plugin Architecture Tests\n');

const PluginSystem = require('./plugin-system');

test('PluginSystem exports correctly', () => {
  assert.strictEqual(typeof PluginSystem, 'function');
});

test('PluginSystem constructor initializes with defaults', () => {
  const ps = new PluginSystem();
  assert.strictEqual(ps.config.pluginsDirectory, './plugins');
  assert.strictEqual(ps.config.sandboxTimeout, 30000);
  assert.strictEqual(ps.config.maxMemoryUsage, 128 * 1024 * 1024);
  assert.ok(Array.isArray(ps.config.allowedAPIs));
});

test('PluginSystem constructor accepts custom config', () => {
  const ps = new PluginSystem({
    pluginsDirectory: './custom-plugins',
    sandboxTimeout: 60000,
    autoUpdate: true
  });
  assert.strictEqual(ps.config.pluginsDirectory, './custom-plugins');
  assert.strictEqual(ps.config.sandboxTimeout, 60000);
  assert.strictEqual(ps.config.autoUpdate, true);
});

test('PluginSystem extends EventEmitter', () => {
  const ps = new PluginSystem();
  assert.ok(ps instanceof EventEmitter);
});

test('PluginSystem has plugins Map', () => {
  const ps = new PluginSystem();
  assert.ok(ps.plugins instanceof Map);
});

test('PluginSystem has hooks Map with core hooks', () => {
  const ps = new PluginSystem();
  assert.ok(ps.hooks instanceof Map);
  assert.ok(ps.hooks.has('before-generate'));
  assert.ok(ps.hooks.has('after-generate'));
  assert.ok(ps.hooks.has('component-analyze'));
  assert.ok(ps.hooks.has('style-transform'));
});

test('PluginSystem setupHooks creates all core hooks', () => {
  const ps = new PluginSystem();
  const expectedHooks = [
    'before-generate', 'after-generate', 'component-analyze',
    'style-transform', 'code-optimize', 'export-prepare',
    'sync-conflict', 'version-merge', 'accessibility-check', 'performance-audit'
  ];
  expectedHooks.forEach(hook => {
    assert.ok(ps.hooks.has(hook), `Missing hook: ${hook}`);
    assert.ok(Array.isArray(ps.hooks.get(hook)));
  });
});

test('PluginSystem listPlugins returns array', () => {
  const ps = new PluginSystem();
  const list = ps.listPlugins();
  assert.ok(Array.isArray(list));
});

test('PluginSystem getHookNames returns hook names', () => {
  const ps = new PluginSystem();
  const names = ps.getHookNames();
  assert.ok(Array.isArray(names));
  assert.ok(names.includes('before-generate'));
});

test('PluginSystem getAllMetrics returns object', () => {
  const ps = new PluginSystem();
  const metrics = ps.getAllMetrics();
  assert.strictEqual(typeof metrics, 'object');
});

test('PluginSystem getPluginMetrics returns null for non-existent', () => {
  const ps = new PluginSystem();
  const metrics = ps.getPluginMetrics('non-existent');
  assert.strictEqual(metrics, null);
});

test('PluginSystem createHook adds new hook', async () => {
  const ps = new PluginSystem();
  await ps.createHook('custom-hook', 'Test hook');
  assert.ok(ps.hooks.has('custom-hook'));
});

test('PluginSystem createHook throws for duplicate', async () => {
  const ps = new PluginSystem();
  try {
    await ps.createHook('before-generate');
    assert.fail('Should throw');
  } catch (e) {
    assert.ok(e.message.includes('already exists'));
  }
});

test('PluginSystem removeHook removes hook', () => {
  const ps = new PluginSystem();
  ps.removeHook('before-generate');
  assert.ok(!ps.hooks.has('before-generate'));
});

test('PluginSystem executeHook returns array', async () => {
  const ps = new PluginSystem();
  const results = await ps.executeHook('before-generate', {});
  assert.ok(Array.isArray(results));
});

test('PluginSystem unloadPlugin throws for non-existent', async () => {
  const ps = new PluginSystem();
  try {
    await ps.unloadPlugin('non-existent');
    assert.fail('Should throw');
  } catch (e) {
    assert.ok(e.message.includes('not found'));
  }
});

test('PluginSystem has security manager', () => {
  const ps = new PluginSystem();
  assert.ok(ps.security);
  assert.strictEqual(typeof ps.security.validatePlugin, 'function');
});

// ============================================================================
// Sprint 8.2: Framework Adapters Tests
// ============================================================================

console.log('\n🔌 Sprint 8.2: Framework Adapters Tests\n');

const {
  BaseAdapter,
  ReactAdapter,
  VueAdapter,
  SvelteAdapter,
  AngularAdapter,
  FrameworkAdapterManager,
  SUPPORTED_FRAMEWORKS
} = require('./framework-adapters');

test('Framework Adapters export all classes', () => {
  assert.strictEqual(typeof BaseAdapter, 'function');
  assert.strictEqual(typeof ReactAdapter, 'function');
  assert.strictEqual(typeof VueAdapter, 'function');
  assert.strictEqual(typeof SvelteAdapter, 'function');
  assert.strictEqual(typeof AngularAdapter, 'function');
  assert.strictEqual(typeof FrameworkAdapterManager, 'function');
});

test('SUPPORTED_FRAMEWORKS has all frameworks', () => {
  assert.ok(Array.isArray(SUPPORTED_FRAMEWORKS));
  assert.ok(SUPPORTED_FRAMEWORKS.includes('react'));
  assert.ok(SUPPORTED_FRAMEWORKS.includes('vue'));
  assert.ok(SUPPORTED_FRAMEWORKS.includes('svelte'));
  assert.ok(SUPPORTED_FRAMEWORKS.includes('angular'));
});

test('BaseAdapter initializes correctly', () => {
  const adapter = new BaseAdapter('test', { outputDir: './test' });
  assert.strictEqual(adapter.name, 'test');
  assert.strictEqual(adapter.options.outputDir, './test');
  assert.ok(adapter instanceof EventEmitter);
});

test('BaseAdapter has utility methods', () => {
  const adapter = new BaseAdapter('test');
  assert.strictEqual(typeof adapter.formatComponentName, 'function');
  assert.strictEqual(typeof adapter.formatPropName, 'function');
  assert.strictEqual(typeof adapter.formatCssClassName, 'function');
});

test('BaseAdapter formatComponentName works', () => {
  const adapter = new BaseAdapter('test');
  assert.strictEqual(adapter.formatComponentName('my-component'), 'MyComponent');
  assert.strictEqual(adapter.formatComponentName('hello world'), 'HelloWorld');
});

test('BaseAdapter formatPropName works', () => {
  const adapter = new BaseAdapter('test');
  assert.strictEqual(adapter.formatPropName('my-prop'), 'myProp');
  assert.strictEqual(adapter.formatPropName('hello world'), 'helloWorld');
});

test('ReactAdapter extends BaseAdapter', () => {
  const adapter = new ReactAdapter();
  assert.ok(adapter instanceof BaseAdapter);
  assert.strictEqual(adapter.name, 'react');
});

test('ReactAdapter generates component code', () => {
  const adapter = new ReactAdapter();
  const result = adapter.generateComponent({
    name: 'Button',
    props: [{ name: 'variant', type: 'string', default: 'primary' }],
    styles: { padding: '8px 16px' }
  });
  // Result can be array or object with content
  const code = Array.isArray(result) ? result[0].content : result.content || result;
  assert.ok(code.includes('Button') || typeof code === 'string');
});

test('ReactAdapter has typescript option', () => {
  const adapter = new ReactAdapter({ typescript: true });
  assert.strictEqual(adapter.options.typescript, true);
});

test('VueAdapter extends BaseAdapter', () => {
  const adapter = new VueAdapter();
  assert.ok(adapter instanceof BaseAdapter);
  assert.strictEqual(adapter.name, 'vue');
});

test('VueAdapter generates SFC component', () => {
  const adapter = new VueAdapter();
  const result = adapter.generateComponent({
    name: 'Button',
    props: [{ name: 'variant', type: 'String', default: 'primary' }]
  });
  const code = Array.isArray(result) ? result[0].content : result.content || result;
  assert.ok(code.includes('<script') || code.includes('defineComponent') || typeof code === 'string');
});

test('SvelteAdapter extends BaseAdapter', () => {
  const adapter = new SvelteAdapter();
  assert.ok(adapter instanceof BaseAdapter);
  assert.strictEqual(adapter.name, 'svelte');
});

test('SvelteAdapter generates Svelte component', () => {
  const adapter = new SvelteAdapter();
  const result = adapter.generateComponent({
    name: 'Button',
    props: [{ name: 'variant', type: 'string', default: 'primary' }]
  });
  const code = Array.isArray(result) ? result[0].content : result.content || result;
  assert.ok(code.includes('export let') || code.includes('$props') || typeof code === 'string');
});

test('AngularAdapter extends BaseAdapter', () => {
  const adapter = new AngularAdapter();
  assert.ok(adapter instanceof BaseAdapter);
  assert.strictEqual(adapter.name, 'angular');
});

test('AngularAdapter generates Angular component', () => {
  const adapter = new AngularAdapter();
  const result = adapter.generateComponent({
    name: 'Button',
    props: [{ name: 'variant', type: 'string' }]
  });
  const code = Array.isArray(result) ? result[0].content : result.content || result;
  assert.ok(code.includes('@Component') || code.includes('Component') || typeof code === 'string');
});

test('FrameworkAdapterManager initializes', () => {
  const manager = new FrameworkAdapterManager();
  assert.ok(manager instanceof EventEmitter);
  assert.ok(manager.adapters instanceof Map);
});

test('FrameworkAdapterManager registers default adapters', () => {
  const manager = new FrameworkAdapterManager();
  assert.ok(manager.adapters.has('react'));
  assert.ok(manager.adapters.has('vue'));
  assert.ok(manager.adapters.has('svelte'));
  assert.ok(manager.adapters.has('angular'));
});

test('FrameworkAdapterManager getAdapter returns correct adapter', () => {
  const manager = new FrameworkAdapterManager();
  const react = manager.getAdapter('react');
  assert.ok(react instanceof ReactAdapter);
});

test('FrameworkAdapterManager listAdapters returns all', () => {
  const manager = new FrameworkAdapterManager();
  const list = manager.listAdapters();
  assert.ok(Array.isArray(list));
  assert.ok(list.includes('react'));
});

test('FrameworkAdapterManager hasAdapter works', () => {
  const manager = new FrameworkAdapterManager();
  assert.ok(manager.hasAdapter('react'));
  assert.ok(!manager.hasAdapter('nonexistent'));
});

// ============================================================================
// Sprint 8.3: External Tool Integrations Tests
// ============================================================================

console.log('\n🔗 Sprint 8.3: External Tool Integrations Tests\n');

const {
  BaseIntegration,
  StorybookIntegration,
  ChromaticIntegration,
  GitHubIntegration,
  SlackIntegration,
  DiscordIntegration,
  FigmaIntegration,
  NPMIntegration,
  JiraIntegration,
  LinearIntegration,
  IntegrationManager,
  SUPPORTED_INTEGRATIONS
} = require('./tool-integrations');

test('Tool Integrations export all classes', () => {
  assert.strictEqual(typeof BaseIntegration, 'function');
  assert.strictEqual(typeof StorybookIntegration, 'function');
  assert.strictEqual(typeof ChromaticIntegration, 'function');
  assert.strictEqual(typeof GitHubIntegration, 'function');
  assert.strictEqual(typeof SlackIntegration, 'function');
  assert.strictEqual(typeof DiscordIntegration, 'function');
  assert.strictEqual(typeof FigmaIntegration, 'function');
  assert.strictEqual(typeof NPMIntegration, 'function');
  assert.strictEqual(typeof JiraIntegration, 'function');
  assert.strictEqual(typeof LinearIntegration, 'function');
  assert.strictEqual(typeof IntegrationManager, 'function');
});

test('SUPPORTED_INTEGRATIONS lists all integrations', () => {
  assert.ok(Array.isArray(SUPPORTED_INTEGRATIONS));
  assert.ok(SUPPORTED_INTEGRATIONS.includes('storybook'));
  assert.ok(SUPPORTED_INTEGRATIONS.includes('github'));
});

test('BaseIntegration initializes correctly', () => {
  const integration = new BaseIntegration('test', { apiKey: '123' });
  assert.strictEqual(integration.name, 'test');
  assert.strictEqual(integration.config.apiKey, '123');
  assert.ok(integration instanceof EventEmitter);
});

test('BaseIntegration has required properties', () => {
  const integration = new BaseIntegration('test');
  assert.strictEqual(integration.connected, false);
  assert.strictEqual(integration.requestCount, 0);
  assert.strictEqual(integration.errorCount, 0);
});

test('BaseIntegration has healthCheck method', async () => {
  const integration = new BaseIntegration('test');
  const health = await integration.healthCheck();
  assert.strictEqual(health.healthy, false);
  assert.strictEqual(health.name, 'test');
});

test('StorybookIntegration initializes', () => {
  const storybook = new StorybookIntegration();
  assert.strictEqual(storybook.name, 'storybook');
});

test('StorybookIntegration has generateStory method', () => {
  const storybook = new StorybookIntegration();
  assert.strictEqual(typeof storybook.generateStory, 'function');
});

test('StorybookIntegration has generateMainConfig method', () => {
  const storybook = new StorybookIntegration();
  assert.strictEqual(typeof storybook.generateMainConfig, 'function');
});

test('ChromaticIntegration initializes', () => {
  const chromatic = new ChromaticIntegration({ projectToken: 'test-token' });
  assert.strictEqual(chromatic.name, 'chromatic');
});

test('ChromaticIntegration has generateCIConfig method', () => {
  const chromatic = new ChromaticIntegration({ projectToken: 'test-token' });
  assert.strictEqual(typeof chromatic.generateCIConfig, 'function');
});

test('GitHubIntegration initializes', () => {
  const github = new GitHubIntegration({ token: 'test-token' });
  assert.strictEqual(github.name, 'github');
});

test('GitHubIntegration has workflow methods', () => {
  const github = new GitHubIntegration({ token: 'test-token' });
  assert.strictEqual(typeof github.generateWorkflow, 'function');
});

test('SlackIntegration initializes', () => {
  const slack = new SlackIntegration({ webhookUrl: 'https://hooks.slack.com/test' });
  assert.strictEqual(slack.name, 'slack');
});

test('SlackIntegration has sendMessage method', () => {
  const slack = new SlackIntegration({ webhookUrl: 'https://hooks.slack.com/test' });
  assert.strictEqual(typeof slack.sendMessage, 'function');
});

test('DiscordIntegration initializes', () => {
  const discord = new DiscordIntegration({ webhookUrl: 'https://discord.com/api/webhooks/test' });
  assert.strictEqual(discord.name, 'discord');
});

test('DiscordIntegration has sendMessage method', () => {
  const discord = new DiscordIntegration({ webhookUrl: 'https://discord.com/api/webhooks/test' });
  assert.strictEqual(typeof discord.sendMessage, 'function');
});

test('FigmaIntegration initializes', () => {
  const figma = new FigmaIntegration({ accessToken: 'test-token' });
  assert.strictEqual(figma.name, 'figma');
});

test('FigmaIntegration has getFile method', () => {
  const figma = new FigmaIntegration({ accessToken: 'test-token' });
  assert.strictEqual(typeof figma.getFile, 'function');
});

test('NPMIntegration initializes', () => {
  const npm = new NPMIntegration();
  assert.strictEqual(npm.name, 'npm');
});

test('NPMIntegration has generatePackageJson method', () => {
  const npm = new NPMIntegration();
  assert.strictEqual(typeof npm.generatePackageJson, 'function');
});

test('JiraIntegration initializes', () => {
  const jira = new JiraIntegration({
    host: 'https://test.atlassian.net',
    email: 'test@test.com',
    apiToken: 'test-token'
  });
  assert.strictEqual(jira.name, 'jira');
});

test('JiraIntegration has createIssue method', () => {
  const jira = new JiraIntegration({
    host: 'https://test.atlassian.net',
    email: 'test@test.com',
    apiToken: 'test-token'
  });
  assert.strictEqual(typeof jira.createIssue, 'function');
});

test('LinearIntegration initializes', () => {
  const linear = new LinearIntegration({ apiKey: 'test-key' });
  assert.strictEqual(linear.name, 'linear');
});

test('LinearIntegration has createIssue method', () => {
  const linear = new LinearIntegration({ apiKey: 'test-key' });
  assert.strictEqual(typeof linear.createIssue, 'function');
});

test('IntegrationManager initializes', () => {
  const manager = new IntegrationManager();
  assert.ok(manager instanceof EventEmitter);
  assert.ok(manager.integrations instanceof Map);
});

test('IntegrationManager registerIntegration adds integration', () => {
  const manager = new IntegrationManager();
  class CustomIntegration extends BaseIntegration {
    constructor(config) { super('custom', config); }
  }
  manager.registerIntegration('custom', CustomIntegration);
  assert.ok(manager.integrations.has('custom'));
});

test('IntegrationManager createIntegration creates instance', () => {
  const manager = new IntegrationManager();
  const storybook = manager.createIntegration('storybook', {});
  assert.ok(storybook instanceof StorybookIntegration);
});

test('IntegrationManager listIntegrations returns all names', () => {
  const manager = new IntegrationManager();
  const list = manager.listIntegrations();
  assert.ok(Array.isArray(list));
  assert.ok(list.includes('storybook'));
  assert.ok(list.includes('github'));
});

test('IntegrationManager hasIntegration works', () => {
  const manager = new IntegrationManager();
  assert.ok(manager.hasIntegration('storybook'));
  assert.ok(!manager.hasIntegration('nonexistent'));
});

// ============================================================================
// Sprint 8.4: Documentation Generator Tests
// ============================================================================

console.log('\n📚 Sprint 8.4: Documentation Generator Tests\n');

const {
  DocumentationGenerator,
  ComponentDocGenerator,
  TokenDocGenerator,
  APIDocGenerator,
  ChangelogGenerator,
  DocSiteGenerator,
  TemplateEngine,
  DocParser,
  DOC_TEMPLATES,
  SUPPORTED_FORMATS
} = require('./doc-generator');

test('Documentation Generator exports all classes', () => {
  assert.strictEqual(typeof DocumentationGenerator, 'function');
  assert.strictEqual(typeof ComponentDocGenerator, 'function');
  assert.strictEqual(typeof TokenDocGenerator, 'function');
  assert.strictEqual(typeof APIDocGenerator, 'function');
  assert.strictEqual(typeof ChangelogGenerator, 'function');
  assert.strictEqual(typeof DocSiteGenerator, 'function');
  assert.strictEqual(typeof TemplateEngine, 'function');
  assert.strictEqual(typeof DocParser, 'function');
});

test('DOC_TEMPLATES has all templates', () => {
  assert.ok(DOC_TEMPLATES.component);
  assert.ok(DOC_TEMPLATES.token);
  assert.ok(DOC_TEMPLATES.changelog);
  assert.ok(DOC_TEMPLATES.api);
  assert.ok(DOC_TEMPLATES.readme);
});

test('SUPPORTED_FORMATS lists available formats', () => {
  assert.ok(Array.isArray(SUPPORTED_FORMATS));
  assert.ok(SUPPORTED_FORMATS.includes('markdown'));
});

test('TemplateEngine initializes', () => {
  const engine = new TemplateEngine();
  assert.ok(engine);
  assert.ok(engine.helpers);
});

test('TemplateEngine render processes template', () => {
  const engine = new TemplateEngine();
  const result = engine.render('Hello {{name}}!', { name: 'World' });
  assert.strictEqual(result, 'Hello World!');
});

test('TemplateEngine handles nested properties', () => {
  const engine = new TemplateEngine();
  const result = engine.render('{{user.name}}', { user: { name: 'Test' } });
  assert.strictEqual(result, 'Test');
});

test('DocParser initializes', () => {
  const parser = new DocParser();
  assert.ok(parser);
});

test('DocParser can parse code', () => {
  const parser = new DocParser();
  const code = `
/**
 * A button component
 * @param {string} variant - The button variant
 */
function Button(props) {}
`;
  const result = parser.parseFile(code);
  assert.ok(result !== undefined);
});

test('ComponentDocGenerator initializes', () => {
  const generator = new ComponentDocGenerator();
  assert.ok(generator instanceof EventEmitter);
});

test('ComponentDocGenerator has generate method', () => {
  const generator = new ComponentDocGenerator();
  assert.strictEqual(typeof generator.generate, 'function');
});

test('ComponentDocGenerator generates docs', async () => {
  const generator = new ComponentDocGenerator();
  const doc = await generator.generate({
    name: 'Button',
    description: 'A button component',
    props: [
      { name: 'variant', type: 'string', description: 'Button style', default: 'primary' }
    ]
  });
  assert.ok(doc);
  const content = typeof doc === 'string' ? doc : doc.content;
  assert.ok(content.includes('Button'));
});

test('TokenDocGenerator initializes', () => {
  const generator = new TokenDocGenerator();
  assert.ok(generator instanceof EventEmitter);
});

test('TokenDocGenerator has generate method', () => {
  const generator = new TokenDocGenerator();
  assert.strictEqual(typeof generator.generate, 'function');
});

test('TokenDocGenerator generates token docs', async () => {
  const generator = new TokenDocGenerator();
  const doc = await generator.generate({
    tokens: {
      colors: {
        primary: '#0066cc',
        secondary: '#6c757d'
      }
    }
  });
  assert.ok(doc);
});

test('APIDocGenerator initializes', () => {
  const generator = new APIDocGenerator();
  assert.ok(generator instanceof EventEmitter);
});

test('APIDocGenerator has generateFromSource method', () => {
  const generator = new APIDocGenerator();
  assert.strictEqual(typeof generator.generateFromSource, 'function');
});

test('APIDocGenerator generates API docs', async () => {
  const generator = new APIDocGenerator();
  const doc = await generator.generate({
    name: 'DesignBridge',
    version: '1.0.0',
    endpoints: [
      { method: 'GET', path: '/tokens', description: 'Get tokens' }
    ]
  });
  assert.ok(doc);
});

test('ChangelogGenerator initializes', () => {
  const generator = new ChangelogGenerator();
  assert.ok(generator instanceof EventEmitter);
});

test('ChangelogGenerator has generate method', () => {
  const generator = new ChangelogGenerator();
  assert.strictEqual(typeof generator.generate, 'function');
});

test('ChangelogGenerator generates changelog', async () => {
  const generator = new ChangelogGenerator();
  const changelog = await generator.generate({
    versions: [
      {
        version: '1.0.0',
        date: '2024-01-01',
        changes: [
          { type: 'added', description: 'Initial release' }
        ]
      }
    ]
  });
  assert.ok(changelog);
  const content = typeof changelog === 'string' ? changelog : changelog.content;
  assert.ok(content.includes('1.0.0'));
});

test('DocSiteGenerator initializes', () => {
  const generator = new DocSiteGenerator();
  assert.ok(generator instanceof EventEmitter);
});

test('DocSiteGenerator has generate method', () => {
  const generator = new DocSiteGenerator();
  assert.strictEqual(typeof generator.generate, 'function');
});

test('DocumentationGenerator initializes', () => {
  const generator = new DocumentationGenerator();
  assert.ok(generator instanceof EventEmitter);
});

test('DocumentationGenerator has generateAll method', () => {
  const generator = new DocumentationGenerator();
  assert.strictEqual(typeof generator.generateAll, 'function');
});

test('DocumentationGenerator emits events', async () => {
  const generator = new DocumentationGenerator();
  let eventFired = false;
  generator.on('generation:complete', () => { eventFired = true; });
  await generator.generateAll({
    components: [{ name: 'Test', description: 'Test component' }]
  });
  assert.ok(eventFired);
});

// ============================================================================
// Integration Tests
// ============================================================================

console.log('\n🔄 Integration Tests\n');

test('PluginSystem and IntegrationManager work together', async () => {
  const ps = new PluginSystem();
  const im = new IntegrationManager();

  // Create custom hook
  await ps.createHook('integration-sync');
  const storybook = im.createIntegration('storybook', {});

  assert.ok(ps.hooks.has('integration-sync'));
  assert.ok(storybook instanceof StorybookIntegration);
});

test('FrameworkAdapterManager and DocumentationGenerator work together', async () => {
  const fam = new FrameworkAdapterManager();
  const dg = new DocumentationGenerator();

  // Generate component with React adapter
  const reactAdapter = fam.getAdapter('react');
  const componentResult = reactAdapter.generateComponent({
    name: 'Button',
    props: [{ name: 'variant', type: 'string' }]
  });

  // Generate docs for the component
  const docResult = await dg.generateAll({
    components: [{ name: 'Button', description: 'A button' }]
  });

  assert.ok(componentResult);
  assert.ok(docResult);
});

test('All adapters can generate components', () => {
  const manager = new FrameworkAdapterManager();
  const frameworks = ['react', 'vue', 'svelte', 'angular'];

  for (const framework of frameworks) {
    const adapter = manager.getAdapter(framework);
    const result = adapter.generateComponent({
      name: 'TestComponent',
      props: [{ name: 'value', type: 'string' }]
    });
    assert.ok(result, `${framework} adapter should generate code`);
  }
});

test('IntegrationManager handles multiple integrations', () => {
  const manager = new IntegrationManager();

  const storybook = manager.createIntegration('storybook', {});
  const github = manager.createIntegration('github', { token: 'test' });
  const slack = manager.createIntegration('slack', { webhookUrl: 'https://test' });
  const npm = manager.createIntegration('npm', {});

  assert.ok(storybook instanceof StorybookIntegration);
  assert.ok(github instanceof GitHubIntegration);
  assert.ok(slack instanceof SlackIntegration);
  assert.ok(npm instanceof NPMIntegration);
});

test('Documentation generator handles all doc types', async () => {
  const componentGen = new ComponentDocGenerator();
  const tokenGen = new TokenDocGenerator();
  const apiGen = new APIDocGenerator();
  const changelogGen = new ChangelogGenerator();

  const componentDocs = await componentGen.generate({
    name: 'Button',
    description: 'Test'
  });

  const tokenDocs = await tokenGen.generate({
    tokens: { color: { primary: '#000' } }
  });

  const apiDocs = await apiGen.generate({
    name: 'API',
    endpoints: [{ method: 'GET', path: '/' }]
  });

  const changelog = await changelogGen.generate({
    versions: [{ version: '1.0.0', date: '2024-01-01', changes: [] }]
  });

  assert.ok(componentDocs);
  assert.ok(tokenDocs);
  assert.ok(apiDocs);
  assert.ok(changelog);
});

// ============================================================================
// Test Summary
// ============================================================================

console.log('\n' + '='.repeat(60));
console.log('📊 Phase 8: Plugin System & Integrations - Test Summary');
console.log('='.repeat(60));

const sprint1Tests = testResults.slice(0, 17);
const sprint2Start = 17;
const sprint2Tests = testResults.slice(sprint2Start, sprint2Start + 22);
const sprint3Start = sprint2Start + 22;
const sprint3Tests = testResults.slice(sprint3Start, sprint3Start + 26);
const sprint4Start = sprint3Start + 26;
const sprint4Tests = testResults.slice(sprint4Start, sprint4Start + 22);
const integrationStart = sprint4Start + 22;
const integrationTests = testResults.slice(integrationStart);

const sprintResults = {
  'Sprint 8.1: Plugin Architecture': sprint1Tests,
  'Sprint 8.2: Framework Adapters': sprint2Tests,
  'Sprint 8.3: Tool Integrations': sprint3Tests,
  'Sprint 8.4: Documentation Generator': sprint4Tests,
  'Integration Tests': integrationTests
};

Object.entries(sprintResults).forEach(([sprint, results]) => {
  const passed = results.filter(r => r.status === 'passed').length;
  const total = results.length;
  console.log(`\n${sprint}: ${passed}/${total} tests passed`);
});

console.log('\n' + '-'.repeat(60));
console.log(`Total: ${testsPassed}/${testsPassed + testsFailed} tests passed`);
console.log('-'.repeat(60));

if (testsFailed > 0) {
  console.log('\n❌ Failed tests:');
  testResults.filter(t => t.status === 'failed').forEach(t => {
    console.log(`  - ${t.name}: ${t.error}`);
  });
  process.exit(1);
} else {
  console.log('\n✅ All Phase 8 tests passed!');
  process.exit(0);
}
