/**
 * Registry-to-Code Pipeline End-to-End Tests
 *
 * Tests the complete pipeline:
 * 1. Registry Reader - reads componentRegistry.json
 * 2. Raw Source Loading - loads component source data
 * 3. Enriched Input - builds input with registry metadata
 * 4. Optimizer Transform - generates framework code
 * 5. Code Output - writes generated code
 */

const IntegrationTestRunner = require('./test-runner');
const TestUtils = require('./test-utils');
const path = require('path');
const fs = require('fs').promises;

// Import registry reader
const {
  readComponentRegistry,
  getComponentById,
  getComponentsByCategory,
  getAllComponentIds,
  resolveRawFilePath,
  resolveCodeOutputPath,
  loadRawSource,
  invalidateCache,
  createEmptyRegistry,
  getRegistryStats
} = require('../../registry-reader');

// Import optimizers
const ReactOptimizer = require('../../react-optimizer');
const VueOptimizer = require('../../vue-optimizer');
const SvelteOptimizer = require('../../svelte-optimizer');
const AngularOptimizer = require('../../angular-optimizer');
const WebComponentsOptimizer = require('../../web-components-optimizer');
const ReactNativeOptimizer = require('../../react-native-optimizer');
const FlutterOptimizer = require('../../flutter-optimizer');
const SwiftUIOptimizer = require('../../swiftui-optimizer');
const JetpackComposeOptimizer = require('../../jetpack-compose-optimizer');

const runner = new IntegrationTestRunner();

// Test fixture directory
const FIXTURE_DIR = path.join(__dirname, 'fixtures', 'registry-test');

/**
 * Create test fixtures
 */
async function setupTestFixtures() {
  // Create fixture directories
  await fs.mkdir(path.join(FIXTURE_DIR, '.design', 'source', 'components'), { recursive: true });

  // Create test registry
  const testRegistry = {
    version: '2.0.0',
    metadata: {
      lastUpdated: new Date().toISOString(),
      source: 'test'
    },
    components: {
      'btn-001': {
        name: 'PrimaryButton',
        category: 'buttons',
        source: { type: 'figma-plugin', fileKey: 'test123' },
        paths: {
          rawSource: '.design/source/components/primary-button.json'
        },
        tokenDependencies: {
          colors: ['primary', 'white'],
          spacing: ['md', 'lg'],
          typography: ['button']
        },
        interactiveStates: {
          hover: { backgroundColor: '#2563EB' },
          pressed: { backgroundColor: '#1D4ED8' },
          disabled: { opacity: 0.5 }
        },
        variants: [
          { name: 'primary', styles: { backgroundColor: '#3B82F6' } },
          { name: 'secondary', styles: { backgroundColor: '#6B7280' } },
          { name: 'outline', styles: { backgroundColor: 'transparent', border: '1px solid #3B82F6' } }
        ]
      },
      'card-002': {
        name: 'InfoCard',
        category: 'cards',
        source: { type: 'figma-mcp', fileKey: 'test456' },
        paths: {
          rawSource: '.design/source/components/info-card.json'
        },
        tokenDependencies: {
          colors: ['surface', 'text'],
          spacing: ['lg', 'xl'],
          borderRadius: ['md']
        },
        interactiveStates: {},
        variants: []
      }
    }
  };

  await fs.writeFile(
    path.join(FIXTURE_DIR, '.design', 'componentRegistry.json'),
    JSON.stringify(testRegistry, null, 2)
  );

  // Create raw source files
  const buttonSource = {
    id: '1:234',
    name: 'PrimaryButton',
    type: 'COMPONENT',
    absoluteBoundingBox: { x: 0, y: 0, width: 120, height: 44 },
    fills: [{ type: 'SOLID', color: { r: 0.231, g: 0.510, b: 0.965, a: 1 } }],
    strokes: [],
    effects: [],
    cornerRadius: 8,
    children: [
      {
        id: '1:235',
        name: 'Label',
        type: 'TEXT',
        characters: 'Click Me',
        style: {
          fontFamily: 'Inter',
          fontSize: 14,
          fontWeight: 500,
          textAlignHorizontal: 'CENTER'
        },
        fills: [{ type: 'SOLID', color: { r: 1, g: 1, b: 1, a: 1 } }]
      }
    ],
    componentPropertyDefinitions: {
      variant: { type: 'VARIANT', defaultValue: 'primary' },
      label: { type: 'TEXT', defaultValue: 'Click Me' }
    }
  };

  await fs.writeFile(
    path.join(FIXTURE_DIR, '.design', 'source', 'components', 'primary-button.json'),
    JSON.stringify(buttonSource, null, 2)
  );

  const cardSource = {
    id: '2:345',
    name: 'InfoCard',
    type: 'COMPONENT',
    absoluteBoundingBox: { x: 0, y: 0, width: 320, height: 200 },
    fills: [{ type: 'SOLID', color: { r: 1, g: 1, b: 1, a: 1 } }],
    strokes: [],
    effects: [{ type: 'DROP_SHADOW', color: { r: 0, g: 0, b: 0, a: 0.1 }, offset: { x: 0, y: 2 }, radius: 4 }],
    cornerRadius: 12,
    children: [
      {
        id: '2:346',
        name: 'Title',
        type: 'TEXT',
        characters: 'Card Title',
        style: { fontFamily: 'Inter', fontSize: 18, fontWeight: 600 },
        fills: [{ type: 'SOLID', color: { r: 0.1, g: 0.1, b: 0.1, a: 1 } }]
      },
      {
        id: '2:347',
        name: 'Description',
        type: 'TEXT',
        characters: 'Card description goes here',
        style: { fontFamily: 'Inter', fontSize: 14, fontWeight: 400 },
        fills: [{ type: 'SOLID', color: { r: 0.4, g: 0.4, b: 0.4, a: 1 } }]
      }
    ]
  };

  await fs.writeFile(
    path.join(FIXTURE_DIR, '.design', 'source', 'components', 'info-card.json'),
    JSON.stringify(cardSource, null, 2)
  );
}

/**
 * Clean up test fixtures
 */
async function cleanupTestFixtures() {
  try {
    await fs.rm(FIXTURE_DIR, { recursive: true, force: true });
  } catch (e) {
    // Ignore cleanup errors
  }
  invalidateCache();
}

// ==================== Registry Reader Tests ====================

runner.test('Registry Reader: readComponentRegistry loads registry', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);

    TestUtils.assertTrue(registry !== null, 'Registry should not be null');
    TestUtils.assertTrue(registry.components !== undefined, 'Registry should have components');
    TestUtils.assertEqual(Object.keys(registry.components).length, 2, 'Should have 2 components');
  } finally {
    await cleanupTestFixtures();
  }
});

runner.test('Registry Reader: getComponentById returns correct component', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const button = getComponentById(registry, 'btn-001');

    TestUtils.assertTrue(button !== null, 'Button should be found');
    TestUtils.assertEqual(button.name, 'PrimaryButton', 'Name should match');
    TestUtils.assertEqual(button.category, 'buttons', 'Category should match');
  } finally {
    await cleanupTestFixtures();
  }
});

runner.test('Registry Reader: getComponentsByCategory filters correctly', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const buttons = getComponentsByCategory(registry, 'buttons');

    TestUtils.assertEqual(buttons.length, 1, 'Should find 1 button');
    TestUtils.assertEqual(buttons[0].name, 'PrimaryButton', 'Should be PrimaryButton');
  } finally {
    await cleanupTestFixtures();
  }
});

runner.test('Registry Reader: getAllComponentIds returns all IDs', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const ids = getAllComponentIds(registry);

    TestUtils.assertEqual(ids.length, 2, 'Should have 2 IDs');
    TestUtils.assertTrue(ids.includes('btn-001'), 'Should include btn-001');
    TestUtils.assertTrue(ids.includes('card-002'), 'Should include card-002');
  } finally {
    await cleanupTestFixtures();
  }
});

runner.test('Registry Reader: loadRawSource loads component source', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const entry = getComponentById(registry, 'btn-001');
    const rawData = await loadRawSource(FIXTURE_DIR, entry);

    TestUtils.assertTrue(rawData !== null, 'Raw data should not be null');
    TestUtils.assertEqual(rawData.name, 'PrimaryButton', 'Name should match');
    TestUtils.assertEqual(rawData.type, 'COMPONENT', 'Type should be COMPONENT');
  } finally {
    await cleanupTestFixtures();
  }
});

runner.test('Registry Reader: resolveCodeOutputPath generates correct paths', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const entry = getComponentById(registry, 'btn-001');

    const reactPath = resolveCodeOutputPath(FIXTURE_DIR, entry, 'react');
    TestUtils.assertTrue(reactPath.endsWith('.tsx'), 'React path should end with .tsx');

    const vuePath = resolveCodeOutputPath(FIXTURE_DIR, entry, 'vue');
    TestUtils.assertTrue(vuePath.endsWith('.vue'), 'Vue path should end with .vue');

    const flutterPath = resolveCodeOutputPath(FIXTURE_DIR, entry, 'flutter');
    TestUtils.assertTrue(flutterPath.endsWith('.dart'), 'Flutter path should end with .dart');
  } finally {
    await cleanupTestFixtures();
  }
});

runner.test('Registry Reader: getRegistryStats returns statistics', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const stats = getRegistryStats(registry);

    TestUtils.assertEqual(stats.totalComponents, 2, 'Should have 2 total');
    TestUtils.assertEqual(stats.byCategory['buttons'], 1, 'Should have 1 button');
    TestUtils.assertEqual(stats.byCategory['cards'], 1, 'Should have 1 card');
    TestUtils.assertEqual(stats.withTokens, 2, 'Both should have tokens');
    TestUtils.assertEqual(stats.withVariants, 1, 'Only button has variants');
  } finally {
    await cleanupTestFixtures();
  }
});

// ==================== Enriched Input Tests ====================

runner.test('Enriched Input: Build correct input structure', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const entry = getComponentById(registry, 'btn-001');
    const rawData = await loadRawSource(FIXTURE_DIR, entry);

    // Build enriched input (as wrappers do)
    const enrichedInput = {
      raw: rawData,
      registry: {
        id: 'btn-001',
        name: entry.name,
        source: entry.source,
        tokenDependencies: entry.tokenDependencies || {},
        interactiveStates: entry.interactiveStates || {},
        variants: entry.variants || [],
        category: entry.category
      },
      options: {
        framework: 'react',
        typescript: true,
        includeStyles: true,
        generateStory: false
      }
    };

    TestUtils.assertTrue(enrichedInput.raw !== undefined, 'Should have raw data');
    TestUtils.assertTrue(enrichedInput.registry !== undefined, 'Should have registry metadata');
    TestUtils.assertEqual(enrichedInput.registry.id, 'btn-001', 'Registry ID should match');
    TestUtils.assertEqual(enrichedInput.registry.variants.length, 3, 'Should have 3 variants');
    TestUtils.assertTrue(enrichedInput.registry.tokenDependencies.colors.includes('primary'), 'Should have color token');
  } finally {
    await cleanupTestFixtures();
  }
});

// ==================== Optimizer Tests (Static optimize method) ====================

runner.test('React Optimizer: Static optimize accepts enriched input', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const entry = getComponentById(registry, 'btn-001');
    const rawData = await loadRawSource(FIXTURE_DIR, entry);

    const input = {
      raw: rawData,
      registry: {
        id: 'btn-001',
        name: entry.name,
        source: entry.source,
        tokenDependencies: entry.tokenDependencies || {},
        interactiveStates: entry.interactiveStates || {},
        variants: entry.variants || [],
        category: entry.category
      },
      options: { framework: 'react', typescript: true }
    };

    const result = await ReactOptimizer.optimize(input);

    TestUtils.assertTrue(result.success, 'Transform should succeed');
    TestUtils.assertTrue(result.code.length > 0, 'Should generate code');
    TestUtils.assertContains(result.code, 'PrimaryButton', 'Code should contain component name');
  } finally {
    await cleanupTestFixtures();
  }
});

runner.test('Vue Optimizer: Static optimize accepts enriched input', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const entry = getComponentById(registry, 'btn-001');
    const rawData = await loadRawSource(FIXTURE_DIR, entry);

    const input = {
      raw: rawData,
      registry: {
        id: 'btn-001',
        name: entry.name,
        source: entry.source,
        tokenDependencies: entry.tokenDependencies || {},
        interactiveStates: entry.interactiveStates || {},
        variants: entry.variants || [],
        category: entry.category
      },
      options: { framework: 'vue', composition: true }
    };

    const result = await VueOptimizer.optimize(input);

    TestUtils.assertTrue(result.success, 'Transform should succeed');
    TestUtils.assertTrue(result.code.length > 0, 'Should generate code');
  } finally {
    await cleanupTestFixtures();
  }
});

runner.test('Svelte Optimizer: Static optimize accepts enriched input', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const entry = getComponentById(registry, 'btn-001');
    const rawData = await loadRawSource(FIXTURE_DIR, entry);

    const input = {
      raw: rawData,
      registry: {
        id: 'btn-001',
        name: entry.name,
        source: entry.source,
        tokenDependencies: entry.tokenDependencies || {},
        interactiveStates: entry.interactiveStates || {},
        variants: entry.variants || [],
        category: entry.category
      },
      options: { framework: 'svelte', svelte5: true }
    };

    const result = await SvelteOptimizer.optimize(input);

    TestUtils.assertTrue(result.success, 'Transform should succeed');
    TestUtils.assertTrue(result.code.length > 0, 'Should generate code');
  } finally {
    await cleanupTestFixtures();
  }
});

runner.test('Angular Optimizer: Static optimize accepts enriched input', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const entry = getComponentById(registry, 'btn-001');
    const rawData = await loadRawSource(FIXTURE_DIR, entry);

    const input = {
      raw: rawData,
      registry: {
        id: 'btn-001',
        name: entry.name,
        source: entry.source,
        tokenDependencies: entry.tokenDependencies || {},
        interactiveStates: entry.interactiveStates || {},
        variants: entry.variants || [],
        category: entry.category
      },
      options: { framework: 'angular', standalone: true }
    };

    const result = await AngularOptimizer.optimize(input);

    TestUtils.assertTrue(result.success, 'Transform should succeed');
    TestUtils.assertTrue(result.code.length > 0, 'Should generate code');
  } finally {
    await cleanupTestFixtures();
  }
});

runner.test('Web Components Optimizer: Static optimize accepts enriched input', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const entry = getComponentById(registry, 'btn-001');
    const rawData = await loadRawSource(FIXTURE_DIR, entry);

    const input = {
      raw: rawData,
      registry: {
        id: 'btn-001',
        name: entry.name,
        source: entry.source,
        tokenDependencies: entry.tokenDependencies || {},
        interactiveStates: entry.interactiveStates || {},
        variants: entry.variants || [],
        category: entry.category
      },
      options: { framework: 'web-components', typescript: true }
    };

    const result = await WebComponentsOptimizer.optimize(input);

    TestUtils.assertTrue(result.success, 'Transform should succeed');
    TestUtils.assertTrue(result.code.length > 0, 'Should generate code');
  } finally {
    await cleanupTestFixtures();
  }
});

runner.test('React Native Optimizer: Static optimize accepts enriched input', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const entry = getComponentById(registry, 'btn-001');
    const rawData = await loadRawSource(FIXTURE_DIR, entry);

    const input = {
      raw: rawData,
      registry: {
        id: 'btn-001',
        name: entry.name,
        source: entry.source,
        tokenDependencies: entry.tokenDependencies || {},
        interactiveStates: entry.interactiveStates || {},
        variants: entry.variants || [],
        category: entry.category
      },
      options: { framework: 'react-native', expo: true }
    };

    const result = await ReactNativeOptimizer.optimize(input);

    TestUtils.assertTrue(result.success, 'Transform should succeed');
    TestUtils.assertTrue(result.code.length > 0, 'Should generate code');
  } finally {
    await cleanupTestFixtures();
  }
});

runner.test('Flutter Optimizer: Static optimize accepts enriched input', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const entry = getComponentById(registry, 'btn-001');
    const rawData = await loadRawSource(FIXTURE_DIR, entry);

    const input = {
      raw: rawData,
      registry: {
        id: 'btn-001',
        name: entry.name,
        source: entry.source,
        tokenDependencies: entry.tokenDependencies || {},
        interactiveStates: entry.interactiveStates || {},
        variants: entry.variants || [],
        category: entry.category
      },
      options: { framework: 'flutter', nullSafety: true }
    };

    const result = await FlutterOptimizer.optimize(input);

    TestUtils.assertTrue(result.success, 'Transform should succeed');
    TestUtils.assertTrue(result.code.length > 0, 'Should generate code');
  } finally {
    await cleanupTestFixtures();
  }
});

runner.test('SwiftUI Optimizer: Static optimize accepts enriched input', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const entry = getComponentById(registry, 'btn-001');
    const rawData = await loadRawSource(FIXTURE_DIR, entry);

    const input = {
      raw: rawData,
      registry: {
        id: 'btn-001',
        name: entry.name,
        source: entry.source,
        tokenDependencies: entry.tokenDependencies || {},
        interactiveStates: entry.interactiveStates || {},
        variants: entry.variants || [],
        category: entry.category
      },
      options: { framework: 'swiftui' }
    };

    const result = await SwiftUIOptimizer.optimize(input);

    TestUtils.assertTrue(result.success, 'Transform should succeed');
    TestUtils.assertTrue(result.code.length > 0, 'Should generate code');
  } finally {
    await cleanupTestFixtures();
  }
});

runner.test('Jetpack Compose Optimizer: Static optimize accepts enriched input', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const entry = getComponentById(registry, 'btn-001');
    const rawData = await loadRawSource(FIXTURE_DIR, entry);

    const input = {
      raw: rawData,
      registry: {
        id: 'btn-001',
        name: entry.name,
        source: entry.source,
        tokenDependencies: entry.tokenDependencies || {},
        interactiveStates: entry.interactiveStates || {},
        variants: entry.variants || [],
        category: entry.category
      },
      options: { framework: 'jetpack-compose', material3: true }
    };

    const result = await JetpackComposeOptimizer.optimize(input);

    TestUtils.assertTrue(result.success, 'Transform should succeed');
    TestUtils.assertTrue(result.code.length > 0, 'Should generate code');
  } finally {
    await cleanupTestFixtures();
  }
});

// ==================== Story Generation Tests ====================

runner.test('Story Generation: React generates CSF3 with argTypes and default args', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const entry = getComponentById(registry, 'btn-001');
    const rawData = await loadRawSource(FIXTURE_DIR, entry);

    // Create enriched input with props for story generation
    const input = {
      raw: rawData,
      registry: {
        id: 'btn-001',
        name: entry.name,
        source: entry.source,
        tokenDependencies: entry.tokenDependencies || {},
        interactiveStates: entry.interactiveStates || {},
        variants: entry.variants || [],
        category: entry.category
      },
      options: {
        framework: 'react',
        typescript: true,
        generateStory: true
      }
    };

    const result = await ReactOptimizer.optimize(input);

    TestUtils.assertTrue(result.success, 'Transform should succeed');
    TestUtils.assertTrue(result.story !== undefined, 'Should generate story');
    TestUtils.assertTrue(result.story.length > 0, 'Story should not be empty');

    // CSF3 format checks
    TestUtils.assertContains(result.story, 'Meta<typeof', 'Should use CSF3 Meta type');
    TestUtils.assertContains(result.story, 'StoryObj', 'Should use CSF3 StoryObj');
    TestUtils.assertContains(result.story, 'autodocs', 'Should have autodocs tag');
    TestUtils.assertContains(result.story, 'argTypes', 'Should have argTypes');
    TestUtils.assertContains(result.story, 'export default meta', 'Should export meta');

  } finally {
    await cleanupTestFixtures();
  }
});

runner.test('Story Generation: argTypes correctly map prop types to controls', async () => {
  // Test with mock component data that has typed props
  const optimizer = new ReactOptimizer();

  const mockProps = {
    variant: { type: 'enum', values: ['primary', 'secondary'] },
    disabled: { type: 'boolean', default: false },
    size: { type: 'number', default: 16 },
    label: { type: 'string', default: 'Click me' }
  };

  const argTypes = optimizer.generateArgTypes(mockProps);

  TestUtils.assertEqual(argTypes.variant.control, 'select', 'Enum should map to select');
  TestUtils.assertTrue(argTypes.variant.options.includes('primary'), 'Should have enum options');
  TestUtils.assertEqual(argTypes.disabled.control, 'boolean', 'Boolean should map to boolean');
  TestUtils.assertEqual(argTypes.size.control, 'number', 'Number should map to number');
  TestUtils.assertEqual(argTypes.label.control, 'text', 'String should map to text');
});

runner.test('Story Generation: default args populated from prop defaults', async () => {
  const optimizer = new ReactOptimizer();

  const mockProps = {
    variant: { type: 'string', default: 'primary' },
    disabled: { type: 'boolean', default: false },
    count: { type: 'number', default: 5 },
    label: { type: 'string' }  // No default
  };

  const defaultArgs = optimizer.generateDefaultArgs(mockProps);

  TestUtils.assertEqual(defaultArgs.variant, 'primary', 'Should use prop default');
  TestUtils.assertEqual(defaultArgs.disabled, false, 'Should use boolean default');
  TestUtils.assertEqual(defaultArgs.count, 5, 'Should use number default');
  TestUtils.assertEqual(defaultArgs.label, '', 'String without default should be empty string');
});

runner.test('Story Generation: variant stories created from registry variants', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const entry = getComponentById(registry, 'btn-001');
    const rawData = await loadRawSource(FIXTURE_DIR, entry);

    const input = {
      raw: rawData,
      registry: {
        id: 'btn-001',
        name: entry.name,
        source: entry.source,
        tokenDependencies: entry.tokenDependencies || {},
        interactiveStates: entry.interactiveStates || {},
        variants: entry.variants || [],  // Has primary, secondary, outline
        category: entry.category
      },
      options: {
        framework: 'react',
        typescript: true,
        generateStory: true
      }
    };

    const result = await ReactOptimizer.optimize(input);

    TestUtils.assertTrue(result.story !== undefined, 'Should generate story');

    // Check for variant stories (lowercase export names as generated)
    TestUtils.assertContains(result.story, 'export const primary', 'Should have primary variant story');
    TestUtils.assertContains(result.story, 'export const secondary', 'Should have secondary variant story');
    TestUtils.assertContains(result.story, 'export const outline', 'Should have outline variant story');

  } finally {
    await cleanupTestFixtures();
  }
});

// ==================== Full Pipeline Tests ====================

runner.test('Full Pipeline: Registry → Raw → Enriched → React Code', async () => {
  await setupTestFixtures();
  try {
    // Step 1: Read registry
    const registry = await readComponentRegistry(FIXTURE_DIR);
    TestUtils.assertTrue(registry !== null, 'Registry loaded');

    // Step 2: Get component entry
    const entry = getComponentById(registry, 'btn-001');
    TestUtils.assertTrue(entry !== null, 'Component found');

    // Step 3: Load raw source
    const rawData = await loadRawSource(FIXTURE_DIR, entry);
    TestUtils.assertTrue(rawData !== null, 'Raw data loaded');

    // Step 4: Build enriched input
    const enrichedInput = {
      raw: rawData,
      registry: {
        id: 'btn-001',
        name: entry.name,
        source: entry.source,
        tokenDependencies: entry.tokenDependencies || {},
        interactiveStates: entry.interactiveStates || {},
        variants: entry.variants || [],
        category: entry.category
      },
      options: {
        framework: 'react',
        typescript: true,
        includeStyles: true
      }
    };

    // Step 5: Transform
    const result = await ReactOptimizer.optimize(enrichedInput);
    TestUtils.assertTrue(result.success, 'Transform succeeded');
    TestUtils.assertTrue(result.code.length > 100, 'Generated substantial code');

    // Step 6: Verify output contains expected elements
    TestUtils.assertContains(result.code, 'export', 'Should have export');

  } finally {
    await cleanupTestFixtures();
  }
});

runner.test('Full Pipeline: Process multiple components', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const componentIds = getAllComponentIds(registry);

    const results = [];

    for (const id of componentIds) {
      const entry = getComponentById(registry, id);
      const rawData = await loadRawSource(FIXTURE_DIR, entry);

      const input = {
        raw: rawData,
        registry: {
          id,
          name: entry.name,
          source: entry.source,
          tokenDependencies: entry.tokenDependencies || {},
          interactiveStates: entry.interactiveStates || {},
          variants: entry.variants || [],
          category: entry.category
        },
        options: { framework: 'react', typescript: true }
      };

      const result = await ReactOptimizer.optimize(input);
      results.push({ id, success: result.success, codeLength: result.code?.length || 0 });
    }

    TestUtils.assertEqual(results.length, 2, 'Should process 2 components');
    TestUtils.assertTrue(results.every(r => r.success), 'All should succeed');
    TestUtils.assertTrue(results.every(r => r.codeLength > 0), 'All should generate code');

  } finally {
    await cleanupTestFixtures();
  }
});

runner.test('Full Pipeline: Token dependencies are available to optimizer', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const entry = getComponentById(registry, 'btn-001');
    const rawData = await loadRawSource(FIXTURE_DIR, entry);

    // Verify token dependencies pass through
    const input = {
      raw: rawData,
      registry: {
        id: 'btn-001',
        name: entry.name,
        source: entry.source,
        tokenDependencies: entry.tokenDependencies,
        interactiveStates: entry.interactiveStates,
        variants: entry.variants,
        category: entry.category
      },
      options: { framework: 'react', typescript: true }
    };

    TestUtils.assertTrue(input.registry.tokenDependencies.colors.length > 0, 'Should have color tokens');
    TestUtils.assertTrue(input.registry.tokenDependencies.spacing.length > 0, 'Should have spacing tokens');

    const result = await ReactOptimizer.optimize(input);
    TestUtils.assertTrue(result.success, 'Transform with tokens should succeed');

  } finally {
    await cleanupTestFixtures();
  }
});

runner.test('Full Pipeline: Interactive states are available to optimizer', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const entry = getComponentById(registry, 'btn-001');
    const rawData = await loadRawSource(FIXTURE_DIR, entry);

    const input = {
      raw: rawData,
      registry: {
        id: 'btn-001',
        name: entry.name,
        source: entry.source,
        tokenDependencies: entry.tokenDependencies,
        interactiveStates: entry.interactiveStates,
        variants: entry.variants,
        category: entry.category
      },
      options: { framework: 'react', typescript: true }
    };

    TestUtils.assertTrue(input.registry.interactiveStates.hover !== undefined, 'Should have hover state');
    TestUtils.assertTrue(input.registry.interactiveStates.pressed !== undefined, 'Should have pressed state');
    TestUtils.assertTrue(input.registry.interactiveStates.disabled !== undefined, 'Should have disabled state');

    const result = await ReactOptimizer.optimize(input);
    TestUtils.assertTrue(result.success, 'Transform with states should succeed');

  } finally {
    await cleanupTestFixtures();
  }
});

runner.test('Full Pipeline: Variants are available to optimizer', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const entry = getComponentById(registry, 'btn-001');
    const rawData = await loadRawSource(FIXTURE_DIR, entry);

    const input = {
      raw: rawData,
      registry: {
        id: 'btn-001',
        name: entry.name,
        source: entry.source,
        tokenDependencies: entry.tokenDependencies,
        interactiveStates: entry.interactiveStates,
        variants: entry.variants,
        category: entry.category
      },
      options: { framework: 'react', typescript: true }
    };

    TestUtils.assertEqual(input.registry.variants.length, 3, 'Should have 3 variants');
    TestUtils.assertTrue(input.registry.variants.some(v => v.name === 'primary'), 'Should have primary variant');
    TestUtils.assertTrue(input.registry.variants.some(v => v.name === 'secondary'), 'Should have secondary variant');
    TestUtils.assertTrue(input.registry.variants.some(v => v.name === 'outline'), 'Should have outline variant');

    const result = await ReactOptimizer.optimize(input);
    TestUtils.assertTrue(result.success, 'Transform with variants should succeed');

  } finally {
    await cleanupTestFixtures();
  }
});

// ==================== Error Handling Tests ====================

runner.test('Error Handling: Missing component returns null', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);
    const missing = getComponentById(registry, 'non-existent-id');

    TestUtils.assertTrue(missing === null, 'Should return null for missing component');
  } finally {
    await cleanupTestFixtures();
  }
});

runner.test('Error Handling: Empty registry returns empty stats', async () => {
  const emptyRegistry = createEmptyRegistry();
  const stats = getRegistryStats(emptyRegistry);

  TestUtils.assertEqual(stats.totalComponents, 0, 'Should have 0 components');
  TestUtils.assertEqual(Object.keys(stats.byCategory).length, 0, 'Should have no categories');
});

runner.test('Error Handling: Invalid raw source throws error', async () => {
  await setupTestFixtures();
  try {
    const registry = await readComponentRegistry(FIXTURE_DIR);

    // Create entry with non-existent raw source
    const entry = {
      name: 'NonExistent',
      paths: { rawSource: '.design/source/components/does-not-exist.json' }
    };

    let errorThrown = false;
    try {
      await loadRawSource(FIXTURE_DIR, entry);
    } catch (error) {
      errorThrown = true;
      TestUtils.assertContains(error.message, 'Raw source not found', 'Should indicate missing file');
    }

    TestUtils.assertTrue(errorThrown, 'Should throw error for missing raw source');
  } finally {
    await cleanupTestFixtures();
  }
});

// Run tests if called directly
if (require.main === module) {
  runner.run().then(results => {
    process.exit(results.failed > 0 ? 1 : 0);
  });
}

module.exports = runner;
