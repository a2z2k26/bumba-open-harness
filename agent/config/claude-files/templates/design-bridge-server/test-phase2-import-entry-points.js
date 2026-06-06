#!/usr/bin/env node
/**
 * Phase 2 Test: Import Entry Point Integration
 *
 * Tests that AutoRegistrar is properly integrated into all import entry points:
 * - plugin-bridge.js (processComponents)
 * - extract-figma-mcp.js
 * - cli.js (updateComponentRegistry)
 * - extract-shadcn.js
 * - nlp-registry-integration.js
 *
 * Part of Two-State Architecture implementation
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

// Test results tracking
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
    console.log(`  ✓ ${name}`);
  } catch (error) {
    results.failed++;
    results.tests.push({ name, status: 'FAIL', error: error.message });
    console.log(`  ✗ ${name}`);
    console.log(`    Error: ${error.message}`);
  }
}

async function asyncTest(name, fn) {
  try {
    await fn();
    results.passed++;
    results.tests.push({ name, status: 'PASS' });
    console.log(`  ✓ ${name}`);
  } catch (error) {
    results.failed++;
    results.tests.push({ name, status: 'FAIL', error: error.message });
    console.log(`  ✗ ${name}`);
    console.log(`    Error: ${error.message}`);
  }
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message || 'Assertion failed');
  }
}

// ============================================================================
// Test Setup
// ============================================================================

function createTestProject() {
  const testDir = path.join(os.tmpdir(), `design-bridge-phase2-test-${Date.now()}`);
  const designDir = path.join(testDir, '.design');
  const sourceDir = path.join(designDir, 'source', 'components');

  fs.mkdirSync(sourceDir, { recursive: true });

  // Create initial registry
  const registry = {
    version: '3.0.0',
    metadata: {
      schemaVersion: '3.0.0',
      lastUpdated: new Date().toISOString(),
      createdAt: new Date().toISOString()
    },
    components: {}
  };

  fs.writeFileSync(
    path.join(designDir, 'componentRegistry.json'),
    JSON.stringify(registry, null, 2)
  );

  return testDir;
}

function cleanup(testDir) {
  if (testDir && fs.existsSync(testDir)) {
    fs.rmSync(testDir, { recursive: true, force: true });
  }
}

// ============================================================================
// Test Suites
// ============================================================================

console.log('\n========================================');
console.log('Phase 2: Import Entry Point Integration');
console.log('========================================\n');

// ---------------------------------------------------------------------------
// Suite 1: AutoRegistrar Import Verification
// ---------------------------------------------------------------------------

console.log('Suite 1: AutoRegistrar Import Verification');
console.log('------------------------------------------');

test('plugin-bridge.js has AutoRegistrar import', () => {
  const content = fs.readFileSync(
    path.join(__dirname, 'plugin-bridge.js'),
    'utf8'
  );
  assert(
    content.includes("require('./auto-registrar')"),
    'Missing AutoRegistrar import in plugin-bridge.js'
  );
});

test('cli.js has AutoRegistrar import', () => {
  const content = fs.readFileSync(
    path.join(__dirname, 'cli.js'),
    'utf8'
  );
  assert(
    content.includes("require('./auto-registrar')"),
    'Missing AutoRegistrar import in cli.js'
  );
});

test('nlp-registry-integration.js has AutoRegistrar import', () => {
  const content = fs.readFileSync(
    path.join(__dirname, 'nlp-registry-integration.js'),
    'utf8'
  );
  assert(
    content.includes("require('./auto-registrar')"),
    'Missing AutoRegistrar import in nlp-registry-integration.js'
  );
});

test('extract-figma-mcp.js has AutoRegistrar import', () => {
  // Correct path: design-feature/.claude/wrappers/extract-figma-mcp.js
  const wrapperPath = path.join(__dirname, '../../../.claude/wrappers/extract-figma-mcp.js');
  if (!fs.existsSync(wrapperPath)) {
    throw new Error(`extract-figma-mcp.js not found at expected path: ${wrapperPath}`);
  }
  const content = fs.readFileSync(wrapperPath, 'utf8');
  assert(
    content.includes('auto-registrar'),
    'Missing AutoRegistrar import in extract-figma-mcp.js'
  );
});

test('extract-shadcn.js has AutoRegistrar import', () => {
  // Correct path: design-feature/.claude/wrappers/extract-shadcn.js
  const wrapperPath = path.join(__dirname, '../../../.claude/wrappers/extract-shadcn.js');
  if (!fs.existsSync(wrapperPath)) {
    throw new Error(`extract-shadcn.js not found at expected path: ${wrapperPath}`);
  }
  const content = fs.readFileSync(wrapperPath, 'utf8');
  assert(
    content.includes('auto-registrar'),
    'Missing AutoRegistrar import in extract-shadcn.js'
  );
});

// ---------------------------------------------------------------------------
// Suite 2: AutoRegistrar Integration Points
// ---------------------------------------------------------------------------

console.log('\nSuite 2: AutoRegistrar Integration Points');
console.log('------------------------------------------');

test('plugin-bridge uses AutoRegistrar in processComponents', () => {
  const content = fs.readFileSync(
    path.join(__dirname, 'plugin-bridge.js'),
    'utf8'
  );
  // Check for shouldAutoRegister and getAutoRegistrar methods
  assert(
    content.includes('shouldAutoRegister'),
    'Missing shouldAutoRegister method in plugin-bridge.js'
  );
  assert(
    content.includes('getAutoRegistrar'),
    'Missing getAutoRegistrar method in plugin-bridge.js'
  );
  // Check for registration call in processComponents
  assert(
    content.includes('registerComponent') && content.includes('processComponents'),
    'Missing registerComponent call in processComponents'
  );
});

test('cli.js updateComponentRegistry uses AutoRegistrar', () => {
  const content = fs.readFileSync(
    path.join(__dirname, 'cli.js'),
    'utf8'
  );
  // Check that updateComponentRegistry creates AutoRegistrar
  const funcMatch = content.match(/function updateComponentRegistry[\s\S]*?{[\s\S]*?new AutoRegistrar/);
  assert(
    funcMatch,
    'updateComponentRegistry should create AutoRegistrar instance'
  );
});

test('nlp-registry uses AutoRegistrar in updateComponentRegistry', () => {
  const content = fs.readFileSync(
    path.join(__dirname, 'nlp-registry-integration.js'),
    'utf8'
  );
  const funcMatch = content.match(/function updateComponentRegistry[\s\S]*?{[\s\S]*?new AutoRegistrar/);
  assert(
    funcMatch,
    'NLP updateComponentRegistry should create AutoRegistrar instance'
  );
});

test('extract-figma-mcp uses registerComponent', () => {
  const wrapperPath = path.join(__dirname, '../../../.claude/wrappers/extract-figma-mcp.js');
  const content = fs.readFileSync(wrapperPath, 'utf8');
  assert(
    content.includes('autoRegistrar.registerComponent'),
    'extract-figma-mcp should call autoRegistrar.registerComponent'
  );
});

test('extract-shadcn uses registerComponent', () => {
  const wrapperPath = path.join(__dirname, '../../../.claude/wrappers/extract-shadcn.js');
  const content = fs.readFileSync(wrapperPath, 'utf8');
  assert(
    content.includes('autoRegistrar.registerComponent'),
    'extract-shadcn should call autoRegistrar.registerComponent'
  );
});

// ---------------------------------------------------------------------------
// Suite 3: AutoRegistrar Functional Tests
// ---------------------------------------------------------------------------

console.log('\nSuite 3: AutoRegistrar Functional Tests');
console.log('---------------------------------------');

(async () => {
  const { AutoRegistrar } = require('./auto-registrar');
  let testDir = null;

  try {
    testDir = createTestProject();

    await asyncTest('AutoRegistrar registers component with figma-plugin source', async () => {
      const registrar = new AutoRegistrar({
        projectPath: testDir,
        autoRegisterOnImport: true,
        emitEvents: false
      });

      const result = await registrar.registerComponent(
        {
          name: 'TestButton',
          type: 'COMPONENT',
          category: 'actions',
          variants: [],
          props: [{ name: 'onClick', type: 'function' }],
          tokenDependencies: { colors: ['primary'] }
        },
        {
          type: 'figma-plugin',
          projectPath: testDir,
          fileKey: 'abc123',
          nodeId: '1:23',
          rawDataPath: '.design/source/components/test-button.json'
        }
      );

      assert(result.success, 'Registration should succeed');
      assert(result.id.includes('figma-plugin'), 'ID should include source type');
      assert(result.entry.transformation.state === 'imported', 'State should be imported');
    });

    await asyncTest('AutoRegistrar registers component with shadcn source', async () => {
      const registrar = new AutoRegistrar({
        projectPath: testDir,
        autoRegisterOnImport: true,
        emitEvents: false
      });

      const result = await registrar.registerComponent(
        {
          name: 'ShadcnButton',
          type: 'COMPONENT',
          category: 'actions',
          variants: [{ name: 'variant', options: ['default', 'outline'] }],
          tokenDependencies: {}
        },
        {
          type: 'shadcn',
          projectPath: testDir,
          fileKey: '@shadcn',
          rawDataPath: '.design/source/components/shadcn-button.json'
        }
      );

      assert(result.success, 'Registration should succeed');
      assert(result.id.includes('shadcn'), 'ID should include source type');
    });

    await asyncTest('AutoRegistrar registers component with nlp source', async () => {
      const registrar = new AutoRegistrar({
        projectPath: testDir,
        autoRegisterOnImport: true,
        emitEvents: false
      });

      const result = await registrar.registerComponent(
        {
          name: 'NlpCard',
          type: 'COMPONENT',
          category: 'containers',
          variants: [],
          props: [{ name: 'children', type: 'ReactNode' }]
        },
        {
          type: 'nlp',
          projectPath: testDir,
          rawDataPath: '.design/source/components/nlp-card.json'
        }
      );

      assert(result.success, 'Registration should succeed');
      assert(result.id.includes('nlp'), 'ID should include source type');
    });

    await asyncTest('AutoRegistrar registers component with figma-mcp source', async () => {
      const registrar = new AutoRegistrar({
        projectPath: testDir,
        autoRegisterOnImport: true,
        emitEvents: false
      });

      const result = await registrar.registerComponent(
        {
          name: 'McpInput',
          type: 'COMPONENT',
          category: 'inputs',
          figmaId: '45:67'
        },
        {
          type: 'figma-mcp',
          projectPath: testDir,
          fileKey: 'xyz789',
          nodeId: '45:67'
        }
      );

      assert(result.success, 'Registration should succeed');
      assert(result.id.includes('figma-mcp'), 'ID should include source type');
    });

    await asyncTest('Registry contains all registered components', async () => {
      const { readComponentRegistry } = require('./registry-reader');
      const registry = await readComponentRegistry(testDir);

      assert(
        Object.keys(registry.components).length >= 4,
        `Expected at least 4 components, got ${Object.keys(registry.components).length}`
      );

      // Check each source type is represented
      const sources = Object.values(registry.components).map(c => c.source?.type);
      assert(sources.includes('figma-plugin'), 'Should have figma-plugin component');
      assert(sources.includes('shadcn'), 'Should have shadcn component');
      assert(sources.includes('nlp'), 'Should have nlp component');
      assert(sources.includes('figma-mcp'), 'Should have figma-mcp component');
    });

    await asyncTest('Registry entries have v3.0.0 schema fields', async () => {
      const { readComponentRegistry } = require('./registry-reader');
      const registry = await readComponentRegistry(testDir);

      for (const [id, entry] of Object.entries(registry.components)) {
        assert(entry.transformation, `Component ${id} missing transformation field`);
        assert(entry.syncMetadata, `Component ${id} missing syncMetadata field`);
        assert(
          entry.transformation.state === 'imported' || entry.transformation.state === 'transformed',
          `Component ${id} has invalid transformation.state: ${entry.transformation.state}`
        );
      }
    });

  } finally {
    cleanup(testDir);
  }

  // ---------------------------------------------------------------------------
  // Suite 4: Backward Compatibility
  // ---------------------------------------------------------------------------

  console.log('\nSuite 4: Backward Compatibility');
  console.log('--------------------------------');

  test('plugin-bridge still exports PluginBridge class', () => {
    // plugin-bridge.js exports the class directly (not as named export)
    const PluginBridge = require('./plugin-bridge');
    assert(typeof PluginBridge === 'function', 'PluginBridge should be a constructor');
    assert(
      PluginBridge.prototype.processComponents,
      'PluginBridge should have processComponents method'
    );
  });

  test('cli.js updateComponentRegistry is async-compatible', () => {
    const content = fs.readFileSync(
      path.join(__dirname, 'cli.js'),
      'utf8'
    );
    // Check function signature allows async usage
    assert(
      content.includes('async function updateComponentRegistry'),
      'updateComponentRegistry should be async'
    );
  });

  test('nlp-registry updateComponentRegistry is async-compatible', () => {
    const content = fs.readFileSync(
      path.join(__dirname, 'nlp-registry-integration.js'),
      'utf8'
    );
    assert(
      content.includes('async function updateComponentRegistry'),
      'NLP updateComponentRegistry should be async'
    );
  });

  test('All modules have graceful fallback on error', () => {
    // Check cli.js has fallback
    const cliContent = fs.readFileSync(path.join(__dirname, 'cli.js'), 'utf8');
    assert(
      cliContent.includes('AutoRegistrar failed') && cliContent.includes('fallback'),
      'cli.js should have graceful fallback'
    );

    // Check nlp-registry has fallback
    const nlpContent = fs.readFileSync(path.join(__dirname, 'nlp-registry-integration.js'), 'utf8');
    assert(
      nlpContent.includes('AutoRegistrar failed') && nlpContent.includes('fallback'),
      'nlp-registry should have graceful fallback'
    );
  });

  // ---------------------------------------------------------------------------
  // Print Summary
  // ---------------------------------------------------------------------------

  console.log('\n========================================');
  console.log('Phase 2 Test Results');
  console.log('========================================');
  console.log(`Total: ${results.passed + results.failed}`);
  console.log(`Passed: ${results.passed}`);
  console.log(`Failed: ${results.failed}`);

  if (results.failed > 0) {
    console.log('\nFailed Tests:');
    results.tests
      .filter(t => t.status === 'FAIL')
      .forEach(t => console.log(`  - ${t.name}: ${t.error}`));
  }

  console.log('\n');

  process.exit(results.failed > 0 ? 1 : 0);
})();
