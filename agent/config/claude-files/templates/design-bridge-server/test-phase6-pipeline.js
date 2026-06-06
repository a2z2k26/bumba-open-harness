#!/usr/bin/env node
/**
 * test-phase6-pipeline.js
 * Phase 6: Full Pipeline Integration Tests
 *
 * Tests the complete workflow from:
 * - Figma extraction → Registry → Code Generation
 * - ShadCN import → Registry → Story Generation
 * - NLP prompt → Registry → Component Creation
 * - Cross-source linking and dependency tracking
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
const testDir = path.join(os.tmpdir(), `pipeline-test-${Date.now()}`);
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

console.log('\n═══════════════════════════════════════════════════════════');
console.log('   PHASE 6: Full Pipeline Integration Tests');
console.log('═══════════════════════════════════════════════════════════\n');

// ═══════════════════════════════════════════════════════════════════════════
// Section 1: Figma → Registry Pipeline
// ═══════════════════════════════════════════════════════════════════════════

console.log('─── Figma → Registry Pipeline ───\n');

setupTestDir();

test('Figma component extraction to registry', async () => {
  const { getRegistryManager, clearRegistryManager } = require('./registry-manager');
  const figmaIntegration = require('./figma-registry-integration');

  clearRegistryManager();
  figmaIntegration.invalidateV4Cache();

  // Initialize registry
  const manager = await getRegistryManager(designDir);

  // Simulate Figma extraction
  const figmaComponent = {
    name: 'Button',
    figmaId: '123:456',
    type: 'COMPONENT',
    description: 'A primary button from Figma',
    variants: [
      { name: 'variant', values: ['primary', 'secondary'] },
      { name: 'size', values: ['sm', 'md', 'lg'] }
    ],
    tokenDependencies: {
      colors: ['primary-500', 'primary-600'],
      typography: ['button-text'],
      spacing: ['spacing-4', 'spacing-8']
    }
  };

  // Generate canonical ID
  const canonicalId = figmaIntegration.generateV4CanonicalId(figmaComponent);

  // Add to registry
  const entry = {
    id: canonicalId,
    name: figmaComponent.name,
    type: figmaComponent.type,
    category: 'button',
    description: figmaComponent.description,
    variants: figmaComponent.variants,
    tokenDependencies: figmaComponent.tokenDependencies,
    source: {
      type: 'figma',
      nodeId: figmaComponent.figmaId,
      fileKey: 'test-file-key'
    }
  };

  const result = manager.addEntry(entry, 'component');

  assert(result.id, 'Should create entry');
  assert(result.id.startsWith('figma-component-'), 'Should have figma prefix');

  // Verify entry
  const found = manager.findById(result.id);
  assert(found.tokenDependencies.colors.length === 2, 'Should have color tokens');
  assert(found.variants.length === 2, 'Should have 2 variant types');
});

test('Figma tokens to registry', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  // Simulate token extraction
  const tokens = [
    { name: 'primary-500', value: '#3B82F6', type: 'COLOR', styleId: 'S:color1' },
    { name: 'primary-600', value: '#2563EB', type: 'COLOR', styleId: 'S:color2' },
    { name: 'button-text', value: { fontFamily: 'Inter', fontSize: 14 }, type: 'TEXT', styleId: 'S:text1' }
  ];

  for (const token of tokens) {
    manager.addEntry({
      name: token.name,
      type: token.type,
      category: token.type === 'COLOR' ? 'colors' : 'typography',
      value: token.value,
      source: { type: 'figma', styleId: token.styleId }
    }, 'token');
  }

  manager.saveIndex();

  // Verify tokens
  const allTokens = manager.getAllEntries('token');
  assert(allTokens.length === 3, 'Should have 3 tokens');

  const colorToken = manager.findByStyleId('S:color1');
  assert(colorToken, 'Should find by style ID');
  assert(colorToken.value === '#3B82F6', 'Should have correct value');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 2: ShadCN → Registry Pipeline
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── ShadCN → Registry Pipeline ───\n');

test('ShadCN component import to registry', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const shadcnIntegration = require('./shadcn-registry-integration');

  shadcnIntegration.invalidateV4Cache();
  const manager = await getRegistryManager(designDir);

  // Simulate ShadCN component
  const shadcnComponent = {
    name: 'Button',
    type: 'COMPONENT',
    category: 'button',
    description: 'ShadCN button component',
    variants: {
      variant: ['default', 'destructive', 'outline', 'secondary', 'ghost', 'link'],
      size: ['default', 'sm', 'lg', 'icon']
    },
    props: ['asChild', 'disabled', 'className']
  };

  const canonicalId = shadcnIntegration.generateV4CanonicalId('Button', '@shadcn');

  const entry = {
    id: canonicalId,
    name: shadcnComponent.name,
    type: shadcnComponent.type,
    category: shadcnComponent.category,
    description: shadcnComponent.description,
    variants: shadcnComponent.variants,
    props: shadcnComponent.props,
    source: {
      type: 'shadcn',
      registry: '@shadcn'
    }
  };

  const result = manager.addEntry(entry, 'component');

  assert(result.id === 'shadcn-component-shadcn-button', 'Should have correct ID');

  const found = manager.findById(result.id);
  assert(found.variants.variant.length === 6, 'Should have 6 variants');
});

test('ShadCN to Figma component linking', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  // Get both Button components
  const figmaButton = manager.findBySource('figma').find(c => c.name === 'Button');
  const shadcnButton = manager.findById('shadcn-component-shadcn-button');

  assert(figmaButton, 'Figma Button should exist');
  assert(shadcnButton, 'ShadCN Button should exist');

  // Link them
  manager.updateEntry(figmaButton.id, {
    linkedComponents: [shadcnButton.id]
  }, 'component');

  manager.updateEntry(shadcnButton.id, {
    linkedComponents: [figmaButton.id]
  }, 'component');

  // Verify bidirectional linking
  const updatedFigma = manager.findById(figmaButton.id);
  const updatedShadcn = manager.findById(shadcnButton.id);

  assert(updatedFigma.linkedComponents?.includes(shadcnButton.id), 'Figma should link to ShadCN');
  assert(updatedShadcn.linkedComponents?.includes(figmaButton.id), 'ShadCN should link to Figma');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 3: NLP → Registry Pipeline
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── NLP → Registry Pipeline ───\n');

test('NLP prompt to registry', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const nlpIntegration = require('./nlp-registry-integration');

  nlpIntegration.invalidateV4Cache();
  const manager = await getRegistryManager(designDir);

  // Simulate NLP-generated component
  const nlpComponent = {
    name: 'HeroSection',
    type: 'LAYOUT',
    category: 'hero',
    description: 'A hero section with title, subtitle, and CTA',
    prompt: 'Create a hero section with a large heading, subtext, and a call-to-action button'
  };

  const canonicalId = nlpIntegration.generateV4CanonicalId(nlpComponent);

  const entry = {
    id: canonicalId,
    name: nlpComponent.name,
    type: nlpComponent.type,
    category: nlpComponent.category,
    description: nlpComponent.description,
    source: {
      type: 'nlp',
      prompt: nlpComponent.prompt
    }
  };

  const result = manager.addEntry(entry, 'layout');

  assert(result.id.startsWith('nlp-'), 'Should have nlp prefix');

  const found = manager.findById(result.id);
  assert(found.source.prompt, 'Should preserve prompt');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 4: Dependency Graph Pipeline
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── Dependency Graph Pipeline ───\n');

test('Component dependencies tracked', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  // Create a Card component that depends on Button
  const card = manager.addEntry({
    name: 'Card',
    type: 'COMPONENT',
    category: 'card',
    source: { type: 'figma', nodeId: '200:300' }
  }, 'component');

  const figmaButton = manager.findBySource('figma').find(c => c.name === 'Button');

  // Set Card depends on Button
  manager.updateDependencies(card.id, [figmaButton.id]);

  // Verify
  const deps = manager.findDependencies(card.id);
  assert(deps.includes(figmaButton.id), 'Card should depend on Button');

  const dependents = manager.findDependents(figmaButton.id);
  assert(dependents.includes(card.id), 'Button should have Card as dependent');
});

test('Token dependencies tracked', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const figmaButton = manager.findBySource('figma').find(c => c.name === 'Button');
  const colorToken = manager.findByStyleId('S:color1');

  if (figmaButton && colorToken) {
    // Set Button depends on color token
    manager.updateDependencies(figmaButton.id, [colorToken.id]);

    const deps = manager.findDependencies(figmaButton.id);
    assert(deps.includes(colorToken.id), 'Button should depend on color token');
  }
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 5: Query Pipeline
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── Query Pipeline ───\n');

test('Query components by multiple criteria', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  // Query all buttons
  const buttons = manager.findByCategory('button');
  assert(buttons.length >= 2, 'Should have multiple buttons');

  // Query by source
  const figmaButtons = buttons.filter(b => b.source?.type === 'figma');
  const shadcnButtons = buttons.filter(b => b.source?.type === 'shadcn');

  assert(figmaButtons.length >= 1, 'Should have Figma buttons');
  assert(shadcnButtons.length >= 1, 'Should have ShadCN buttons');
});

test('Query layouts', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const layouts = manager.getAllEntries('layout');
  assert(layouts.length >= 1, 'Should have layouts');

  const heroes = layouts.filter(l => l.category === 'hero');
  assert(heroes.length >= 1, 'Should have hero layouts');
});

test('Query tokens by category', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const allTokens = manager.getAllEntries('token');
  const colorTokens = allTokens.filter(t => t.category === 'colors');
  const typographyTokens = allTokens.filter(t => t.category === 'typography');

  assert(colorTokens.length >= 2, 'Should have color tokens');
  assert(typographyTokens.length >= 1, 'Should have typography tokens');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 6: Persistence Pipeline
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── Persistence Pipeline ───\n');

test('Registry persists and reloads', async () => {
  const { getRegistryManager, clearRegistryManager } = require('./registry-manager');

  // Get current state
  let manager = await getRegistryManager(designDir);
  const componentCountBefore = manager.getAllEntries('component').length;
  const tokenCountBefore = manager.getAllEntries('token').length;

  // Save and clear singleton
  manager.saveIndex();
  clearRegistryManager();

  // Reload
  manager = await getRegistryManager(designDir);
  const componentCountAfter = manager.getAllEntries('component').length;
  const tokenCountAfter = manager.getAllEntries('token').length;

  assert(componentCountAfter === componentCountBefore, 'Component count should match');
  assert(tokenCountAfter === tokenCountBefore, 'Token count should match');
});

test('Index remains consistent after reload', async () => {
  const { getRegistryManager, clearRegistryManager } = require('./registry-manager');
  clearRegistryManager();

  const manager = await getRegistryManager(designDir);

  // Find by various methods should still work
  const byId = manager.findById('shadcn-component-shadcn-button');
  assert(byId, 'Should find by ID after reload');

  const byNodeId = manager.findByNodeId('123:456');
  assert(byNodeId, 'Should find by node ID after reload');

  const byStyleId = manager.findByStyleId('S:color1');
  assert(byStyleId, 'Should find by style ID after reload');
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 7: Stats and Reporting
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n─── Stats and Reporting ───\n');

test('Registry stats accurate', async () => {
  const { getRegistryManager } = require('./registry-manager');
  const manager = await getRegistryManager(designDir);

  const stats = manager.getStats();

  assert(typeof stats.totalEntries === 'number', 'Should have total entries');
  assert(typeof stats.components === 'number', 'Should have component count');
  assert(typeof stats.tokens === 'number', 'Should have token count');
  assert(typeof stats.layouts === 'number', 'Should have layout count');

  console.log(`     Total entries: ${stats.totalEntries}`);
  console.log(`     Components: ${stats.components}`);
  console.log(`     Tokens: ${stats.tokens}`);
  console.log(`     Layouts: ${stats.layouts}`);
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
  console.log('\n\x1b[32m✅ ALL PIPELINE INTEGRATION TESTS PASSED\x1b[0m');
  process.exit(0);
}
