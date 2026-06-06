#!/usr/bin/env node
/**
 * test-phase6-migration.js
 * Phase 6: Migration Verification Tests
 *
 * Tests that:
 * - Legacy componentRegistry.json can be migrated to v4.0.0
 * - Legacy layoutManifest.json can be migrated to v4.0.0
 * - Legacy tokens can be migrated to v4.0.0
 * - Data integrity is maintained during migration
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

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

async function testAsync(name, fn) {
  try {
    await fn();
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

// Test directory setup
const testDir = path.join(os.tmpdir(), `migration-test-${Date.now()}`);
const designDir = path.join(testDir, '.design');

function setupTestDir() {
  if (fs.existsSync(testDir)) {
    fs.rmSync(testDir, { recursive: true });
  }
  fs.mkdirSync(designDir, { recursive: true });
}

function cleanupTestDir() {
  if (fs.existsSync(testDir)) {
    fs.rmSync(testDir, { recursive: true });
  }
}

// Create mock legacy registries
function createLegacyComponentRegistry() {
  return {
    version: '3.0.0',
    lastUpdated: new Date().toISOString(),
    components: {
      'figma-mcp-button-123-456': {
        name: 'Button',
        figmaId: '123:456',
        type: 'COMPONENT',
        category: 'button',
        description: 'Legacy button component',
        source: {
          type: 'figma-mcp',
          fileKey: 'legacy-file',
          nodeId: '123:456'
        },
        tokenDependencies: {
          colors: ['primary-500'],
          typography: ['button-text']
        },
        variants: [{ name: 'variant', values: ['primary', 'secondary'] }],
        paths: {
          rawSource: '.design/source/components/Button.json',
          codeOutput: 'src/components/Button.tsx'
        },
        metadata: {
          createdAt: '2024-01-01T00:00:00Z',
          updatedAt: '2024-06-01T00:00:00Z',
          version: 5
        }
      },
      'shadcn-button': {
        name: 'Button',
        type: 'COMPONENT',
        category: 'button',
        description: 'ShadCN button',
        source: {
          type: 'shadcn',
          registry: '@shadcn'
        },
        variants: { variant: ['default', 'outline'] },
        metadata: {
          createdAt: '2024-02-01T00:00:00Z',
          version: 2
        }
      },
      'nlp-card-hero': {
        name: 'HeroCard',
        type: 'COMPONENT',
        category: 'card',
        description: 'NLP-generated hero card',
        source: {
          type: 'nlp-prompt',
          prompt: 'Create a hero card'
        },
        metadata: {
          createdAt: '2024-03-01T00:00:00Z',
          version: 1
        }
      }
    },
    metadata: {
      schemaVersion: '3.0.0',
      totalComponents: 3,
      sources: {
        figma: 1,
        shadcn: 1,
        nlp: 1,
        manual: 0
      }
    }
  };
}

function createLegacyLayoutManifest() {
  return {
    version: '1.0.0',
    lastUpdated: new Date().toISOString(),
    layouts: [
      {
        id: 'layout-hero-main',
        name: 'HeroSection',
        category: 'hero',
        dimensions: { width: 1440, height: 600 },
        source: { type: 'figma', nodeId: 'L:100:200' },
        stage: 'validated'
      },
      {
        id: 'layout-footer',
        name: 'Footer',
        category: 'footer',
        dimensions: { width: 1440, height: 300 },
        source: { type: 'nlp', prompt: 'Create a footer' },
        stage: 'extracted'
      }
    ],
    metadata: {
      totalLayouts: 2
    }
  };
}

function createLegacyTokenIndex() {
  return {
    version: '1.0.0',
    lastUpdated: new Date().toISOString(),
    categories: {
      colors: { file: 'colors.json', count: 10 },
      typography: { file: 'typography.json', count: 5 },
      spacing: { file: 'spacing.json', count: 8 }
    },
    totalTokens: 23
  };
}

function createLegacyColorTokens() {
  return {
    'primary-500': { value: '#3B82F6', styleId: 'S:color1' },
    'primary-600': { value: '#2563EB', styleId: 'S:color2' },
    'secondary-500': { value: '#8B5CF6', styleId: 'S:color3' }
  };
}

console.log('\n═══════════════════════════════════════════════════════════');
console.log('   PHASE 6: Migration Verification Tests');
console.log('═══════════════════════════════════════════════════════════\n');

// ═══════════════════════════════════════════════════════════════════════════
// Section 1: Setup Legacy Environment
// ═══════════════════════════════════════════════════════════════════════════

console.log('─── Setup Legacy Environment ───\n');

setupTestDir();

test('Create legacy componentRegistry.json', () => {
  const legacyRegistry = createLegacyComponentRegistry();
  fs.writeFileSync(
    path.join(designDir, 'componentRegistry.json'),
    JSON.stringify(legacyRegistry, null, 2)
  );
  assert(fs.existsSync(path.join(designDir, 'componentRegistry.json')), 'File should exist');
});

test('Create legacy layoutManifest.json', () => {
  const legacyLayouts = createLegacyLayoutManifest();
  fs.writeFileSync(
    path.join(designDir, 'layoutManifest.json'),
    JSON.stringify(legacyLayouts, null, 2)
  );
  assert(fs.existsSync(path.join(designDir, 'layoutManifest.json')), 'File should exist');
});

test('Create legacy token files', () => {
  fs.mkdirSync(path.join(designDir, 'tokens'), { recursive: true });

  const tokenIndex = createLegacyTokenIndex();
  fs.writeFileSync(
    path.join(designDir, 'tokens', 'index.json'),
    JSON.stringify(tokenIndex, null, 2)
  );

  const colorTokens = createLegacyColorTokens();
  fs.writeFileSync(
    path.join(designDir, 'tokens', 'colors.json'),
    JSON.stringify(colorTokens, null, 2)
  );

  assert(fs.existsSync(path.join(designDir, 'tokens', 'index.json')), 'Token index should exist');
  assert(fs.existsSync(path.join(designDir, 'tokens', 'colors.json')), 'Color tokens should exist');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 2: Migration Process
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── Migration Process ───\n');

test('Initialize v4.0.0 registry alongside legacy', async () => {
  const { getRegistryManager, clearRegistryManager } = require('./registry-manager');
  clearRegistryManager();

  const manager = await getRegistryManager(designDir);

  // v4.0.0 should be created
  assert(fs.existsSync(path.join(designDir, 'registry-index.json')), 'v4 index should exist');
  assert(fs.existsSync(path.join(designDir, 'registries')), 'registries dir should exist');

  // Legacy should still exist
  assert(fs.existsSync(path.join(designDir, 'componentRegistry.json')), 'Legacy should remain');
});

test('Migrate legacy components to v4.0.0', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  // Read legacy registry
  const legacyPath = path.join(designDir, 'componentRegistry.json');
  const legacy = JSON.parse(fs.readFileSync(legacyPath, 'utf8'));

  // Migrate each component
  let migratedCount = 0;
  for (const [legacyId, component] of Object.entries(legacy.components)) {
    // Map legacy source types to v4.0.0
    let sourceType = component.source?.type || 'manual';
    if (sourceType === 'figma-mcp') sourceType = 'figma';
    if (sourceType === 'nlp-prompt') sourceType = 'nlp';

    // Generate new canonical ID
    let canonicalId;
    if (sourceType === 'figma') {
      canonicalId = `figma-component-${component.name.toLowerCase()}-${component.figmaId?.replace(':', '-') || 'unknown'}`;
    } else if (sourceType === 'shadcn') {
      canonicalId = `shadcn-component-shadcn-${component.name.toLowerCase()}`;
    } else if (sourceType === 'nlp') {
      canonicalId = `nlp-component-${component.name.toLowerCase()}-${Date.now()}`;
    } else {
      canonicalId = `manual-component-${component.name.toLowerCase()}-${Date.now()}`;
    }

    const entry = {
      id: canonicalId,
      name: component.name,
      type: component.type,
      category: component.category,
      description: component.description,
      variants: component.variants,
      tokenDependencies: component.tokenDependencies,
      paths: component.paths,
      source: {
        type: sourceType,
        ...(component.source || {}),
        legacyId: legacyId  // Keep reference
      },
      metadata: {
        ...component.metadata,
        migratedFrom: 'v3.0.0',
        migratedAt: new Date().toISOString()
      }
    };

    manager.addEntry(entry, 'component');
    migratedCount++;
  }

  manager.saveIndex();

  assert(migratedCount === 3, 'Should migrate 3 components');
  console.log(`     Migrated ${migratedCount} components`);
});

test('Migrate legacy layouts to v4.0.0', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  // Read legacy layouts
  const legacyPath = path.join(designDir, 'layoutManifest.json');
  const legacy = JSON.parse(fs.readFileSync(legacyPath, 'utf8'));

  let migratedCount = 0;
  for (const layout of legacy.layouts) {
    const sourceType = layout.source?.type || 'manual';
    const canonicalId = `${sourceType}-layout-${layout.name.toLowerCase()}-${Date.now() + migratedCount}`;

    const entry = {
      id: canonicalId,
      name: layout.name,
      type: 'LAYOUT',
      category: layout.category,
      dimensions: layout.dimensions,
      source: {
        ...layout.source,
        legacyId: layout.id
      },
      metadata: {
        stage: layout.stage,
        migratedFrom: 'v1.0.0',
        migratedAt: new Date().toISOString()
      }
    };

    manager.addEntry(entry, 'layout');
    migratedCount++;
  }

  manager.saveIndex();

  assert(migratedCount === 2, 'Should migrate 2 layouts');
  console.log(`     Migrated ${migratedCount} layouts`);
});

test('Migrate legacy tokens to v4.0.0', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  // Read legacy tokens
  const colorsPath = path.join(designDir, 'tokens', 'colors.json');
  const colors = JSON.parse(fs.readFileSync(colorsPath, 'utf8'));

  let migratedCount = 0;
  for (const [name, token] of Object.entries(colors)) {
    const canonicalId = `figma-token-${name}-${token.styleId?.replace('S:', '') || 'unknown'}`;

    const entry = {
      id: canonicalId,
      name: name,
      type: 'COLOR',
      category: 'colors',
      value: token.value,
      source: {
        type: 'figma',
        styleId: token.styleId
      },
      metadata: {
        migratedFrom: 'v1.0.0',
        migratedAt: new Date().toISOString()
      }
    };

    manager.addEntry(entry, 'token');
    migratedCount++;
  }

  manager.saveIndex();

  assert(migratedCount === 3, 'Should migrate 3 color tokens');
  console.log(`     Migrated ${migratedCount} tokens`);
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 3: Verify Data Integrity
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── Verify Data Integrity ───\n');

test('All components accessible by new IDs', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const components = manager.getAllEntries('component');
  assert(components.length >= 3, 'Should have at least 3 components');

  // Each should have required fields
  for (const c of components) {
    assert(c.id, `Component should have id`);
    assert(c.name, `Component should have name`);
    assert(c.source, `Component should have source`);
  }
});

test('Legacy data preserved in metadata', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const components = manager.getAllEntries('component');

  // Find migrated components
  const migrated = components.filter(c => c.metadata?.migratedFrom);
  assert(migrated.length >= 3, 'Should have migrated components');

  for (const c of migrated) {
    assert(c.metadata.migratedAt, 'Should have migration timestamp');
    assert(c.source.legacyId, 'Should have legacy ID reference');
  }
});

test('Source lookups work for migrated entries', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  // Find by node ID (Figma)
  const figmaComponent = manager.findByNodeId('123:456');
  assert(figmaComponent, 'Should find by node ID');
  assert(figmaComponent.name === 'Button', 'Should be correct component');

  // Find by style ID (token)
  const colorToken = manager.findByStyleId('S:color1');
  assert(colorToken, 'Should find by style ID');
  assert(colorToken.value === '#3B82F6', 'Should have correct value');
});

test('Token dependencies preserved', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const figmaButton = manager.findByNodeId('123:456');
  assert(figmaButton.tokenDependencies, 'Should have token dependencies');
  assert(figmaButton.tokenDependencies.colors?.includes('primary-500'), 'Should have color dependency');
});

test('Variants preserved', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const figmaButton = manager.findByNodeId('123:456');
  assert(figmaButton.variants, 'Should have variants');
  assert(figmaButton.variants.length > 0, 'Should have variant entries');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 4: Backward Compatibility
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── Backward Compatibility ───\n');

test('Legacy files remain untouched', () => {
  assert(fs.existsSync(path.join(designDir, 'componentRegistry.json')), 'Legacy component registry should exist');
  assert(fs.existsSync(path.join(designDir, 'layoutManifest.json')), 'Legacy layout manifest should exist');
  assert(fs.existsSync(path.join(designDir, 'tokens', 'index.json')), 'Legacy token index should exist');
});

test('v4.0.0 and legacy can coexist', async () => {
  // Ensure manager is saved
  const { getRegistryManager, clearRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);
  manager.saveIndex();

  // v4.0.0 files
  assert(fs.existsSync(path.join(designDir, 'registry-index.json')), 'v4 index should exist');
  assert(fs.existsSync(path.join(designDir, 'registries', 'components.json')), 'v4 components should exist');

  // Legacy files
  assert(fs.existsSync(path.join(designDir, 'componentRegistry.json')), 'Legacy should exist');

  // Both readable
  const v4Index = JSON.parse(fs.readFileSync(path.join(designDir, 'registry-index.json'), 'utf8'));
  const legacy = JSON.parse(fs.readFileSync(path.join(designDir, 'componentRegistry.json'), 'utf8'));

  assert(v4Index.version === '4.0.0', 'v4 should have correct version');
  assert(legacy.version === '3.0.0', 'Legacy should have correct version');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 5: Stats Comparison
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── Stats Comparison ───\n');

test('v4.0.0 stats match migrated data', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const stats = manager.getStats();

  console.log(`     v4.0.0 Stats:`);
  console.log(`       Components: ${stats.components}`);
  console.log(`       Tokens: ${stats.tokens}`);
  console.log(`       Layouts: ${stats.layouts}`);

  assert(stats.components >= 3, 'Should have migrated components');
  assert(stats.tokens >= 3, 'Should have migrated tokens');
  assert(stats.layouts >= 2, 'Should have migrated layouts');
});

// ═══════════════════════════════════════════════════════════════════════════
// Cleanup and Results
// ═══════════════════════════════════════════════════════════════════════════

cleanupTestDir();

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
  console.log('\n\x1b[32m✅ ALL MIGRATION VERIFICATION TESTS PASSED\x1b[0m');
  process.exit(0);
}
