#!/usr/bin/env node
/**
 * Design Bridge Test Harness
 *
 * Comprehensive test suite for validating the entire design workflow:
 * - Hook loading and execution
 * - Server module availability
 * - Event routing and property passing
 * - End-to-end workflow simulation
 *
 * Usage: node design-bridge-test-harness.js [--verbose] [--fix]
 */

const fs = require('fs').promises;
const path = require('path');

// Test results collector
const results = {
  passed: [],
  failed: [],
  warnings: [],
  fixes: []
};

// Configuration
const CONFIG = {
  hooksDir: path.join(__dirname, '..'),
  serverPaths: [
    '/home/operator/Bumba-Design/Bumba - Design Components/server',
    '/home/operator/.claude/server'
  ],
  verbose: process.argv.includes('--verbose'),
  autoFix: process.argv.includes('--fix')
};

// Color helpers for terminal output
const colors = {
  red: (s) => `\x1b[31m${s}\x1b[0m`,
  green: (s) => `\x1b[32m${s}\x1b[0m`,
  yellow: (s) => `\x1b[33m${s}\x1b[0m`,
  blue: (s) => `\x1b[34m${s}\x1b[0m`,
  dim: (s) => `\x1b[2m${s}\x1b[0m`,
  bold: (s) => `\x1b[1m${s}\x1b[0m`
};

function log(msg) { console.log(msg); }
function pass(test, msg) { results.passed.push({ test, msg }); log(`  ${colors.green('✓')} ${test}`); }
function fail(test, msg, fix) { results.failed.push({ test, msg, fix }); log(`  ${colors.red('✗')} ${test}: ${msg}`); }
function warn(test, msg) { results.warnings.push({ test, msg }); log(`  ${colors.yellow('⚠')} ${test}: ${msg}`); }

// ============================================================================
// TEST CATEGORIES
// ============================================================================

/**
 * Test 1: Hook Registry Loading
 */
async function testHookRegistryLoading() {
  log('\n' + colors.bold('1. Hook Registry Loading'));
  log(colors.dim('─'.repeat(50)));

  try {
    const registryPath = path.join(CONFIG.hooksDir, 'design-bridge-hook-registry.js');

    // Clear require cache
    delete require.cache[require.resolve(registryPath)];

    const registry = require(registryPath);

    if (typeof registry.loadHooks !== 'function') {
      fail('registry-exports', 'loadHooks is not a function');
      return;
    }

    const loadResult = registry.loadHooks();

    if (loadResult.loaded > 0) {
      pass('registry-load', `Loaded ${loadResult.loaded} hooks`);
    } else {
      fail('registry-load', 'No hooks were loaded');
    }

    if (loadResult.failed > 0) {
      fail('registry-errors', `${loadResult.failed} hooks failed to load`);
    } else {
      pass('registry-no-errors', 'All hooks loaded without errors');
    }

    // Check that key functions exist
    const requiredFunctions = ['trigger', 'getStatus', 'listHooks'];
    for (const fn of requiredFunctions) {
      if (typeof registry[fn] === 'function') {
        pass(`registry-${fn}`, `${fn}() exists`);
      } else {
        fail(`registry-${fn}`, `${fn}() is missing`);
      }
    }

  } catch (error) {
    fail('registry-load', `Failed to load registry: ${error.message}`);
  }
}

/**
 * Test 2: Individual Hook Validation
 */
async function testIndividualHooks() {
  log('\n' + colors.bold('2. Individual Hook Validation'));
  log(colors.dim('─'.repeat(50)));

  const hookFiles = [
    'on-component-extract.js',
    'on-layout-extract.js',
    'on-registry-change.js',
    'on-token-change.js',
    'on-design-init-complete.js',
    'on-tokens-updated.js',
    'on-cascade-complete.js',
    'on-component-transform.js'
  ];

  for (const hookFile of hookFiles) {
    const hookPath = path.join(CONFIG.hooksDir, hookFile);
    const hookName = hookFile.replace('.js', '');

    try {
      // Check file exists
      await fs.access(hookPath);

      // Clear require cache
      delete require.cache[require.resolve(hookPath)];

      const hook = require(hookPath);

      // Validate structure
      if (!hook.name) {
        fail(`${hookName}-name`, 'Missing name property');
        continue;
      }

      if (!hook.execute || typeof hook.execute !== 'function') {
        fail(`${hookName}-execute`, 'Missing or invalid execute function');
        continue;
      }

      // Check event property expectations
      const executeStr = hook.execute.toString();
      const usesFilePath = executeStr.includes('event.filePath') || executeStr.includes('filePath }');
      const usesPath = executeStr.includes('event.path') || /\{\s*path\s*\}/.test(executeStr);
      const usesProjectPath = executeStr.includes('event.projectPath') || executeStr.includes('projectPath }');

      if (usesFilePath && !usesPath) {
        warn(`${hookName}-props`, 'Uses event.filePath but not event.path (may need fallback)');
      }

      if (usesProjectPath) {
        // Check if hook derives projectPath or requires it
        const derivesProjectPath = executeStr.includes('path.dirname') || executeStr.includes('substring');
        if (!derivesProjectPath) {
          warn(`${hookName}-projectPath`, 'Requires projectPath but does not derive it');
        }
      }

      pass(`${hookName}-valid`, 'Hook structure valid');

    } catch (error) {
      if (error.code === 'ENOENT') {
        fail(`${hookName}-exists`, 'Hook file not found');
      } else if (error.code === 'MODULE_NOT_FOUND') {
        fail(`${hookName}-deps`, `Missing dependency: ${error.message}`);
      } else {
        fail(`${hookName}-load`, `Load error: ${error.message}`);
      }
    }
  }
}

/**
 * Test 3: Server Module Availability
 */
async function testServerModules() {
  log('\n' + colors.bold('3. Server Module Availability'));
  log(colors.dim('─'.repeat(50)));

  const requiredModules = [
    'story-generator.js',
    'styles-md-generator.js',
    'transform-state-updater.js',
    'story-hash-registry.js',
    'registry-reader.js'
  ];

  // Find which server path has the modules
  let serverPath = null;
  for (const testPath of CONFIG.serverPaths) {
    try {
      await fs.access(testPath);
      serverPath = testPath;
      break;
    } catch {
      continue;
    }
  }

  if (!serverPath) {
    fail('server-path', 'No server directory found in expected locations');
    for (const p of CONFIG.serverPaths) {
      log(colors.dim(`    Checked: ${p}`));
    }
    return;
  }

  pass('server-path', `Server directory found: ${serverPath}`);

  // Check hooks reference the correct server path
  const hooksDir = CONFIG.hooksDir;
  const expectedRelPath = path.relative(hooksDir, serverPath);

  // Read a hook that uses server modules
  const transformHookPath = path.join(hooksDir, 'on-component-transform.js');
  try {
    const transformHookContent = await fs.readFile(transformHookPath, 'utf8');
    const serverPathMatch = transformHookContent.match(/path\.resolve\(__dirname,\s*['"]([^'"]+)['"]\)/);

    if (serverPathMatch) {
      const hookRelPath = serverPathMatch[1];
      const resolvedPath = path.resolve(hooksDir, hookRelPath);

      try {
        await fs.access(resolvedPath);
        pass('server-hook-path', `Hook server path resolves correctly`);
      } catch {
        fail('server-hook-path', `Hook references non-existent path: ${resolvedPath}`,
          `Update server path in hooks to: ${expectedRelPath}`);
      }
    }
  } catch (error) {
    warn('server-hook-check', `Could not check hook server paths: ${error.message}`);
  }

  // Check each required module
  for (const module of requiredModules) {
    const modulePath = path.join(serverPath, module);
    try {
      await fs.access(modulePath);

      // Try to require it
      delete require.cache[require.resolve(modulePath)];
      const mod = require(modulePath);

      pass(`server-${module}`, 'Module loads successfully');

    } catch (error) {
      if (error.code === 'ENOENT') {
        fail(`server-${module}`, 'Module file not found');
      } else if (error.code === 'MODULE_NOT_FOUND') {
        fail(`server-${module}`, `Dependency missing: ${error.message}`);
      } else {
        fail(`server-${module}`, `Load error: ${error.message}`);
      }
    }
  }
}

/**
 * Test 4: Trigger Script Event Routing
 */
async function testTriggerEventRouting() {
  log('\n' + colors.bold('4. Trigger Script Event Routing'));
  log(colors.dim('─'.repeat(50)));

  const triggerPath = path.join(CONFIG.hooksDir, 'trigger-design-hooks.js');

  try {
    const triggerContent = await fs.readFile(triggerPath, 'utf8');

    // Check for required event mappings
    const eventMappings = [
      { pattern: 'config.json', event: 'on-design-init-complete' },
      { pattern: 'componentRegistry.json', event: 'on-registry-change' },
      { pattern: '/tokens/', event: 'on-token-change' },
      { pattern: '/source/components/', event: 'on-component-extract' },
      { pattern: '/source/layouts/', event: 'on-layout-extract' }
    ];

    for (const { pattern, event } of eventMappings) {
      if (triggerContent.includes(pattern) && triggerContent.includes(event)) {
        pass(`route-${event}`, `${pattern} → ${event}`);
      } else if (triggerContent.includes(pattern)) {
        warn(`route-${event}`, `Pattern ${pattern} found but event ${event} not linked`);
      } else {
        fail(`route-${event}`, `Missing route: ${pattern} → ${event}`);
      }
    }

    // Check for correct property passing
    const requiredProps = ['filePath', 'projectPath', 'changeType'];
    for (const prop of requiredProps) {
      if (triggerContent.includes(prop + ':')) {
        pass(`prop-${prop}`, `Property ${prop} is passed to hooks`);
      } else {
        fail(`prop-${prop}`, `Property ${prop} not passed to hooks`);
      }
    }

  } catch (error) {
    fail('trigger-load', `Could not read trigger script: ${error.message}`);
  }
}

/**
 * Test 5: Hook Registry Pattern Matching
 */
async function testPatternMatching() {
  log('\n' + colors.bold('5. Pattern Matching Logic'));
  log(colors.dim('─'.repeat(50)));

  const registryPath = path.join(CONFIG.hooksDir, 'design-bridge-hook-registry.js');

  try {
    const registryContent = await fs.readFile(registryPath, 'utf8');

    // Check for glob pattern support
    if (registryContent.includes('globToRegex') || registryContent.includes('minimatch')) {
      pass('pattern-glob', 'Glob pattern matching supported');
    } else if (registryContent.includes('**') || registryContent.includes('*.')) {
      fail('pattern-glob', 'Glob patterns used but no glob matching logic found');
    } else {
      warn('pattern-glob', 'No glob pattern matching detected');
    }

    // Check for array pattern support
    if (registryContent.includes('Array.isArray') && registryContent.includes('watch')) {
      pass('pattern-array', 'Array watch patterns supported');
    } else {
      fail('pattern-array', 'Array watch patterns not supported');
    }

    // Simulate pattern matching
    delete require.cache[require.resolve(registryPath)];
    const registry = require(registryPath);
    registry.loadHooks();

    // Test pattern matching function if exposed
    if (typeof registry.matchesWatchPattern === 'function') {
      // Test cases
      const tests = [
        { path: '/project/.design/tokens/colors.json', pattern: '.design/tokens/**/*.json', expected: true },
        { path: '/project/.design/config.json', pattern: 'config.json', expected: true },
        { path: '/project/.design/components/Button.json', pattern: ['.design/tokens/**/*.json', '.design/components/**/*.json'], expected: true },
      ];

      for (const test of tests) {
        const result = registry.matchesWatchPattern(test.path, test.pattern);
        if (result === test.expected) {
          pass(`match-${test.path.split('/').pop()}`, 'Pattern matched correctly');
        } else {
          fail(`match-${test.path.split('/').pop()}`, `Expected ${test.expected}, got ${result}`);
        }
      }
    }

  } catch (error) {
    fail('pattern-test', `Pattern test failed: ${error.message}`);
  }
}

/**
 * Test 6: Simulate Design Init Workflow
 */
async function testDesignInitWorkflow() {
  log('\n' + colors.bold('6. Design Init Workflow Simulation'));
  log(colors.dim('─'.repeat(50)));

  const testProjectPath = '/tmp/design-bridge-test-' + Date.now();

  try {
    // Create test project structure
    await fs.mkdir(testProjectPath, { recursive: true });
    await fs.mkdir(path.join(testProjectPath, '.design'), { recursive: true });

    // Create mock config.json
    const mockConfig = {
      version: '1.0.0',
      framework: 'react',
      storybook: { enabled: true }
    };

    await fs.writeFile(
      path.join(testProjectPath, '.design', 'config.json'),
      JSON.stringify(mockConfig, null, 2)
    );

    pass('workflow-setup', 'Test project created');

    // Load registry and trigger
    const registryPath = path.join(CONFIG.hooksDir, 'design-bridge-hook-registry.js');
    delete require.cache[require.resolve(registryPath)];
    const registry = require(registryPath);
    registry.loadHooks();

    // Simulate the trigger
    const eventData = {
      filePath: path.join(testProjectPath, '.design', 'config.json'),
      path: path.join(testProjectPath, '.design', 'config.json'),
      projectPath: testProjectPath,
      changeType: 'modified',
      timestamp: new Date().toISOString()
    };

    const results = await registry.trigger('on-design-init-complete', eventData);

    if (results.length > 0) {
      pass('workflow-trigger', `Triggered ${results.length} hook(s)`);

      for (const result of results) {
        if (result.success) {
          pass(`workflow-${result.hook}`, result.message || 'Completed');
        } else {
          fail(`workflow-${result.hook}`, result.message || 'Failed');
        }
      }
    } else {
      fail('workflow-trigger', 'No hooks were triggered for on-design-init-complete');
    }

    // Cleanup
    await fs.rm(testProjectPath, { recursive: true, force: true });

  } catch (error) {
    fail('workflow-simulation', `Workflow simulation failed: ${error.message}`);

    // Cleanup on error
    try {
      await fs.rm(testProjectPath, { recursive: true, force: true });
    } catch {}
  }
}

/**
 * Test 7: Slash Command Validation
 */
async function testSlashCommands() {
  log('\n' + colors.bold('7. Design Slash Commands'));
  log(colors.dim('─'.repeat(50)));

  const commandsDir = '/home/operator/.claude/commands';
  const designCommands = [
    'design-init.md',
    'design-bridge.md',
    'design-promote.md',
    'design-search.md',
    'design-generate-styles.md',
    'design-nlp.md',
    'design-explore-ui.md',
    'design-explore-ux.md',
    'design-transform-react.md',
    'design-transform-vue.md',
    'design-transform-angular.md',
    'design-transform-svelte.md',
    'design-transform-flutter.md',
    'design-transform-swiftui.md',
    'design-transform-react-native.md',
    'design-transform-jetpack-compose.md',
    'design-transform-web-components.md'
  ];

  for (const cmd of designCommands) {
    const cmdPath = path.join(commandsDir, cmd);
    const cmdName = cmd.replace('.md', '');

    try {
      const content = await fs.readFile(cmdPath, 'utf8');

      // Check for basic validity
      if (content.length < 50) {
        fail(`cmd-${cmdName}`, 'Command file appears empty or too short');
        continue;
      }

      // Check for frontmatter
      if (!content.startsWith('---')) {
        warn(`cmd-${cmdName}`, 'No YAML frontmatter detected');
      }

      // Check for required elements in init command
      if (cmdName === 'design-init') {
        const requiredPaths = ['.design/', 'tokens/', 'components/', 'layouts/', 'config.json'];
        for (const reqPath of requiredPaths) {
          if (!content.includes(reqPath)) {
            fail(`cmd-init-${reqPath}`, `Missing reference to ${reqPath}`);
          }
        }

        // Check for Storybook setup
        if (content.includes('.storybook') || content.includes('storybook')) {
          pass(`cmd-init-storybook`, 'Storybook setup included');
        } else {
          fail(`cmd-init-storybook`, 'Storybook setup missing from init');
        }
      }

      pass(`cmd-${cmdName}`, 'Command file exists');

    } catch (error) {
      if (error.code === 'ENOENT') {
        fail(`cmd-${cmdName}`, 'Command file not found');
      } else {
        fail(`cmd-${cmdName}`, `Error: ${error.message}`);
      }
    }
  }
}

/**
 * Test 8: Hook Chain Dependencies
 */
async function testHookChainDependencies() {
  log('\n' + colors.bold('8. Hook Chain Dependencies'));
  log(colors.dim('─'.repeat(50)));

  // Map out which hooks depend on which
  const hookDependencies = {
    'on-design-init-complete': {
      requires: ['catalog source directory'],
      triggers: ['storybook setup', 'folder creation']
    },
    'on-token-change': {
      requires: ['tokens/index.json'],
      triggers: ['on-tokens-updated', 'component re-transform']
    },
    'on-component-transform': {
      requires: ['story-generator.js', 'transform-state-updater.js', 'story-hash-registry.js'],
      triggers: ['story generation', 'state update']
    },
    'on-tokens-updated': {
      requires: ['styles-md-generator.js'],
      triggers: ['STYLES.md regeneration']
    }
  };

  for (const [hookName, deps] of Object.entries(hookDependencies)) {
    const hookPath = path.join(CONFIG.hooksDir, `${hookName}.js`);

    try {
      const content = await fs.readFile(hookPath, 'utf8');

      // Check for required modules
      for (const req of deps.requires) {
        if (req.endsWith('.js')) {
          // Check if module is imported
          if (content.includes(req) || content.includes(req.replace('.js', ''))) {
            pass(`${hookName}-req-${req}`, `Requires ${req}`);
          } else {
            warn(`${hookName}-req-${req}`, `Expected dependency ${req} not found`);
          }
        }
      }

    } catch (error) {
      fail(`${hookName}-deps`, `Could not analyze: ${error.message}`);
    }
  }
}

// ============================================================================
// MAIN EXECUTION
// ============================================================================

async function runAllTests() {
  console.log(colors.bold('\n╔══════════════════════════════════════════════════════════╗'));
  console.log(colors.bold('║         DESIGN BRIDGE TEST HARNESS                       ║'));
  console.log(colors.bold('╚══════════════════════════════════════════════════════════╝'));

  const startTime = Date.now();

  await testHookRegistryLoading();
  await testIndividualHooks();
  await testServerModules();
  await testTriggerEventRouting();
  await testPatternMatching();
  await testDesignInitWorkflow();
  await testSlashCommands();
  await testHookChainDependencies();

  const duration = ((Date.now() - startTime) / 1000).toFixed(2);

  // Summary
  console.log('\n' + colors.bold('═'.repeat(60)));
  console.log(colors.bold('SUMMARY'));
  console.log('═'.repeat(60));

  console.log(`\n${colors.green('Passed:')} ${results.passed.length}`);
  console.log(`${colors.red('Failed:')} ${results.failed.length}`);
  console.log(`${colors.yellow('Warnings:')} ${results.warnings.length}`);
  console.log(`\nDuration: ${duration}s`);

  if (results.failed.length > 0) {
    console.log('\n' + colors.bold(colors.red('FAILURES:')));
    for (const failure of results.failed) {
      console.log(`  ${colors.red('✗')} ${failure.test}: ${failure.msg}`);
      if (failure.fix) {
        console.log(`    ${colors.blue('Fix:')} ${failure.fix}`);
      }
    }
  }

  if (results.warnings.length > 0) {
    console.log('\n' + colors.bold(colors.yellow('WARNINGS:')));
    for (const warning of results.warnings) {
      console.log(`  ${colors.yellow('⚠')} ${warning.test}: ${warning.msg}`);
    }
  }

  // Exit code
  process.exit(results.failed.length > 0 ? 1 : 0);
}

// Run
runAllTests().catch(error => {
  console.error(colors.red(`\nTest harness crashed: ${error.message}`));
  console.error(error.stack);
  process.exit(1);
});
