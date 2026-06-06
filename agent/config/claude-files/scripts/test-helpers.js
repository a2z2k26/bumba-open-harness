#!/usr/bin/env node
/**
 * test-helpers.js
 * Test all helper scripts for functionality
 */

const fs = require('fs');
const path = require('path');

console.log('=== HELPER SCRIPTS TEST ===\n');

const results = {
  total: 0,
  passed: 0,
  failed: 0,
  tests: []
};

function runTest(name, testFn) {
  results.total++;
  console.log(`Test: ${name}`);

  try {
    testFn();
    console.log('  ✅ PASSED\n');
    results.passed++;
    results.tests.push({ name, status: 'PASSED' });
  } catch (error) {
    console.log(`  ❌ FAILED: ${error.message}\n`);
    results.failed++;
    results.tests.push({ name, status: 'FAILED', error: error.message });
  }
}

// Test 1: Verify helper scripts exist
runTest('Helper scripts exist', () => {
  const scriptsDir = path.join(__dirname);
  const required = [
    'read-design-config.js',
    'load-design-tokens.js',
    'update-metadata.js'
  ];

  required.forEach(script => {
    const scriptPath = path.join(scriptsDir, script);
    if (!fs.existsSync(scriptPath)) {
      throw new Error(`Missing script: ${script}`);
    }
  });
});

// Test 2: Scripts are executable
runTest('Helper scripts are executable', () => {
  const scriptsDir = path.join(__dirname);
  const scripts = [
    'read-design-config.js',
    'load-design-tokens.js',
    'update-metadata.js'
  ];

  scripts.forEach(script => {
    const scriptPath = path.join(scriptsDir, script);
    const stats = fs.statSync(scriptPath);
    const isExecutable = (stats.mode & 0o111) !== 0;

    if (!isExecutable) {
      throw new Error(`Script not executable: ${script}`);
    }
  });
});

// Test 3: Scripts have valid Node.js shebang
runTest('Scripts have Node.js shebang', () => {
  const scriptsDir = path.join(__dirname);
  const scripts = [
    'read-design-config.js',
    'load-design-tokens.js',
    'update-metadata.js'
  ];

  scripts.forEach(script => {
    const scriptPath = path.join(scriptsDir, script);
    const content = fs.readFileSync(scriptPath, 'utf8');
    const firstLine = content.split('\n')[0];

    if (!firstLine.startsWith('#!/usr/bin/env node')) {
      throw new Error(`Missing or invalid shebang in ${script}`);
    }
  });
});

// Test 4: Scripts can be required as modules
runTest('Scripts export modules correctly', () => {
  const readConfig = require('./read-design-config');
  const loadTokens = require('./load-design-tokens');
  const updateMeta = require('./update-metadata');

  // Check read-design-config exports
  if (typeof readConfig.readDesignConfig !== 'function') {
    throw new Error('read-design-config.js missing readDesignConfig function');
  }
  if (typeof readConfig.validateConfig !== 'function') {
    throw new Error('read-design-config.js missing validateConfig function');
  }

  // Check load-design-tokens exports
  if (typeof loadTokens.loadDesignTokens !== 'function') {
    throw new Error('load-design-tokens.js missing loadDesignTokens function');
  }
  if (typeof loadTokens.getTokenStats !== 'function') {
    throw new Error('load-design-tokens.js missing getTokenStats function');
  }

  // Check update-metadata exports
  if (typeof updateMeta.updateMetadata !== 'function') {
    throw new Error('update-metadata.js missing updateMetadata function');
  }
  if (typeof updateMeta.getMetadataStats !== 'function') {
    throw new Error('update-metadata.js missing getMetadataStats function');
  }
});

// Test 5: Validation functions work correctly
runTest('Config validation works', () => {
  const { validateConfig } = require('./read-design-config');

  // Valid config
  const validConfig = {
    version: '1.0.0',
    project: {
      framework: 'react',
      typescript: true,
      outputPath: 'src/design-system'
    },
    figma: {},
    transformers: {}
  };

  // Should not throw
  validateConfig(validConfig);

  // Invalid config (missing project)
  const invalidConfig = {
    version: '1.0.0'
  };

  let threw = false;
  try {
    validateConfig(invalidConfig);
  } catch (error) {
    threw = true;
  }

  if (!threw) {
    throw new Error('Validation should reject invalid config');
  }
});

// Test 6: Token category detection
runTest('Token category detection works', () => {
  const { getCategoryFromFilename } = require('./load-design-tokens');

  const tests = [
    ['colors.json', 'colors'],
    ['figma-colors-2023.json', 'colors'],
    ['typography.json', 'typography'],
    ['spacing.json', 'spacing'],
    ['effects.json', 'effects'],
    ['border-radius.json', 'borderRadius']
  ];

  tests.forEach(([filename, expected]) => {
    const actual = getCategoryFromFilename(filename.replace('.json', ''));
    if (actual !== expected) {
      throw new Error(`Expected ${expected} for ${filename}, got ${actual}`);
    }
  });
});

// Test 7: Metadata creation
runTest('Default metadata structure is valid', () => {
  const { createDefaultMetadata } = require('./update-metadata');

  const metadata = createDefaultMetadata();

  const required = [
    'version',
    'figmaFileKey',
    'figmaFileName',
    'createdAt',
    'tokens',
    'components',
    'syncHistory',
    'transformHistory'
  ];

  required.forEach(field => {
    if (!(field in metadata)) {
      throw new Error(`Missing field in default metadata: ${field}`);
    }
  });

  // Verify structure
  if (!Array.isArray(metadata.syncHistory)) {
    throw new Error('syncHistory should be an array');
  }
  if (!Array.isArray(metadata.transformHistory)) {
    throw new Error('transformHistory should be an array');
  }
});

// Summary
console.log('=== TEST SUMMARY ===');
console.log(`Total tests: ${results.total}`);
console.log(`Passed: ${results.passed}`);
console.log(`Failed: ${results.failed}`);
console.log(`Success rate: ${Math.round((results.passed / results.total) * 100)}%`);

if (results.failed > 0) {
  console.log('\nFailed tests:');
  results.tests.filter(t => t.status === 'FAILED').forEach(t => {
    console.log(`  - ${t.name}: ${t.error}`);
  });
  process.exit(1);
} else {
  console.log('\n✅ All helper script tests passed!');
  process.exit(0);
}
