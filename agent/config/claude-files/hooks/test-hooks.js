/**
 * Test script for hook system
 * Run from project root: node .claude/hooks/test-hooks.js
 */
const path = require('path');
const fs = require('fs');

// Import hook registry
const { loadHooks, trigger, getStatus, setEnabled, reloadHooks } = require('./index');

async function runTests() {
  console.log('╔════════════════════════════════════════╗');
  console.log('║      Hook System Test Suite            ║');
  console.log('╚════════════════════════════════════════╝\n');

  let passed = 0;
  let failed = 0;

  // Test 1: Load hooks
  console.log('Test 1: Loading hooks...');
  try {
    const loadResult = loadHooks();
    console.log(`  Loaded: ${loadResult.loaded}`);
    console.log(`  Disabled: ${loadResult.disabled}`);
    console.log(`  Failed: ${loadResult.failed}`);

    if (loadResult.loaded >= 4) {
      console.log('  ✓ Hooks loaded successfully\n');
      passed++;
    } else {
      console.log('  ✗ Expected at least 4 hooks\n');
      failed++;
    }
  } catch (error) {
    console.log(`  ✗ Error loading hooks: ${error.message}\n`);
    failed++;
  }

  // Test 2: Get status
  console.log('Test 2: Getting hook status...');
  try {
    const status = getStatus();
    console.log(`  Total hooks: ${status.summary.total}`);
    console.log(`  Enabled: ${status.summary.enabled}`);
    console.log(`  Disabled: ${status.summary.disabled}`);

    if (status.hooks && status.hooks.length > 0) {
      console.log('  Registered hooks:');
      for (const hook of status.hooks) {
        console.log(`    - ${hook.name} (watch: ${hook.watch}, priority: ${hook.priority})`);
      }
    }

    console.log('  ✓ Status retrieved successfully\n');
    passed++;
  } catch (error) {
    console.log(`  ✗ Error getting status: ${error.message}\n`);
    failed++;
  }

  // Test 3: Trigger registry change hook with mock event
  console.log('Test 3: Triggering on-registry-change hook...');
  try {
    const projectRoot = path.resolve(__dirname, '../..');
    const mockEvent = {
      type: 'change',
      path: path.join(projectRoot, '.design', 'componentRegistry.json'),
      data: {
        components: {
          'test-component-123': {
            name: 'TestButton',
            framework: 'react',
            source: { extractedAt: new Date().toISOString() }
          },
          'test-component-456': {
            name: 'TestCard',
            framework: 'react',
            source: { extractedAt: new Date().toISOString() }
          }
        }
      }
    };

    const results = await trigger('on-registry-change', mockEvent);

    if (results.length > 0) {
      for (const result of results) {
        console.log(`  Hook: ${result.hook}`);
        console.log(`  Success: ${result.success}`);
        console.log(`  Duration: ${result.duration}ms`);
        if (result.queue) {
          console.log(`  Queued: ${result.queue.length} components`);
        }
      }
      console.log('  ✓ Registry change hook triggered\n');
      passed++;
    } else {
      console.log('  ✗ No hooks triggered\n');
      failed++;
    }
  } catch (error) {
    console.log(`  ✗ Error triggering hook: ${error.message}\n`);
    failed++;
  }

  // Test 4: Trigger token change hook with mock event
  console.log('Test 4: Triggering on-token-change hook...');
  try {
    const projectRoot = path.resolve(__dirname, '../..');
    const mockEvent = {
      type: 'change',
      path: path.join(projectRoot, '.design', 'tokens', 'index.json'),
      data: {
        categories: {
          colors: {
            tokens: [
              { name: 'primary', value: '#007AFF' },
              { name: 'secondary', value: '#5856D6' }
            ]
          },
          spacing: {
            tokens: [
              { name: 'sm', value: '8px' },
              { name: 'md', value: '16px' }
            ]
          }
        }
      }
    };

    const results = await trigger('on-token-change', mockEvent);

    if (results.length > 0) {
      for (const result of results) {
        console.log(`  Hook: ${result.hook}`);
        console.log(`  Success: ${result.success}`);
        console.log(`  Duration: ${result.duration}ms`);
        if (result.totalChanges !== undefined) {
          console.log(`  Total changes: ${result.totalChanges}`);
        }
      }
      console.log('  ✓ Token change hook triggered\n');
      passed++;
    } else {
      console.log('  ✗ No hooks triggered\n');
      failed++;
    }
  } catch (error) {
    console.log(`  ✗ Error triggering hook: ${error.message}\n`);
    failed++;
  }

  // Test 5: Enable/Disable hook
  console.log('Test 5: Testing enable/disable...');
  try {
    setEnabled('on-registry-change', false);
    let status = getStatus();
    const disabledHook = status.hooks.find(h => h.name === 'on-registry-change');

    if (disabledHook && !disabledHook.enabled) {
      console.log('  ✓ Hook disabled successfully');
    } else {
      console.log('  ✗ Failed to disable hook');
      failed++;
    }

    setEnabled('on-registry-change', true);
    status = getStatus();
    const enabledHook = status.hooks.find(h => h.name === 'on-registry-change');

    if (enabledHook && enabledHook.enabled) {
      console.log('  ✓ Hook re-enabled successfully\n');
      passed++;
    } else {
      console.log('  ✗ Failed to re-enable hook\n');
      failed++;
    }
  } catch (error) {
    console.log(`  ✗ Error toggling hook: ${error.message}\n`);
    failed++;
  }

  // Test 6: Reload hooks
  console.log('Test 6: Testing hot reload...');
  try {
    const reloadResult = reloadHooks();
    console.log(`  Reloaded: ${reloadResult.loaded} hooks`);

    if (reloadResult.loaded >= 4) {
      console.log('  ✓ Hot reload successful\n');
      passed++;
    } else {
      console.log('  ✗ Reload returned fewer hooks than expected\n');
      failed++;
    }
  } catch (error) {
    console.log(`  ✗ Error reloading hooks: ${error.message}\n`);
    failed++;
  }

  // Test 7: Verify hook isolation (one failure shouldn't stop others)
  console.log('Test 7: Testing error isolation...');
  try {
    // This should not throw even if file doesn't exist
    const results = await trigger('on-registry-change', {
      type: 'change',
      path: '/nonexistent/path/componentRegistry.json',
      data: {}
    });

    // Hook should handle the error gracefully
    if (results.length > 0) {
      console.log('  ✓ Hook handled missing file gracefully\n');
      passed++;
    } else {
      console.log('  ✓ No hooks matched (expected)\n');
      passed++;
    }
  } catch (error) {
    console.log(`  ✗ Error should have been caught: ${error.message}\n`);
    failed++;
  }

  // Summary
  console.log('╔════════════════════════════════════════╗');
  console.log('║           Test Results                 ║');
  console.log('╚════════════════════════════════════════╝');
  console.log(`  Passed: ${passed}`);
  console.log(`  Failed: ${failed}`);
  console.log(`  Total:  ${passed + failed}`);
  console.log('');

  if (failed === 0) {
    console.log('✓ All tests passed!');
    process.exit(0);
  } else {
    console.log('✗ Some tests failed');
    process.exit(1);
  }
}

// Run tests
runTests().catch(error => {
  console.error('Test suite crashed:', error);
  process.exit(1);
});
