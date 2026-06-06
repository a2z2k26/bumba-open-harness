/**
 * figma-skill-e2e.test.js
 * End-to-End tests for the complete Figma MCP Skill workflow
 *
 * Tests the integrated flow of:
 * 1. Token extraction from styles
 * 2. Component extraction with visual properties
 * 3. Interactive state detection
 * 4. Registry integration
 * 5. Error handling throughout
 */

const fs = require('fs');
const path = require('path');

// Import all modules
const { extractComponent, formatComponentResult } = require('./figma-component-extractor');
const { detectInteractiveStates, generateStateCss, formatStateResults } = require('./figma-state-detector');
const { updateRegistry, batchUpdateRegistry, createEmptyRegistry, formatRegistryResult } = require('./figma-registry-integration');
const {
  FigmaExtractionError,
  ErrorCodes,
  validateNode,
  validateComponent,
  safeExtract,
  sanitizeNode,
  createResult
} = require('./figma-error-handler');

let passed = 0;
let failed = 0;

function test(name, condition) {
  if (condition) {
    console.log(`  [PASS] ${name}`);
    passed++;
  } else {
    console.log(`  [FAIL] ${name}`);
    failed++;
  }
}

// Test registry path
const testRegistryPath = path.join(__dirname, 'e2e-test-registry.json');

// Cleanup function
function cleanup() {
  try {
    if (fs.existsSync(testRegistryPath)) {
      fs.unlinkSync(testRegistryPath);
    }
  } catch (e) {
    // Ignore
  }
}

/**
 * Mock Figma data representing a realistic design system extraction
 */
const mockFigmaFile = {
  fileKey: 'abc123XYZ',
  originalUrl: 'https://figma.com/design/abc123XYZ/Design-System',
  styles: {
    'S:color-primary': { name: 'Colors/Primary/500', styleType: 'FILL' },
    'S:color-secondary': { name: 'Colors/Secondary/500', styleType: 'FILL' },
    'S:text-body': { name: 'Typography/Body/Medium', styleType: 'TEXT' },
    'S:shadow-sm': { name: 'Effects/Shadow/Small', styleType: 'EFFECT' }
  },
  components: [
    // Button Component Set with states
    {
      id: '100:1',
      name: 'Button',
      type: 'COMPONENT_SET',
      description: 'Primary action button with multiple states and sizes',
      absoluteBoundingBox: { x: 0, y: 0, width: 200, height: 48 },
      componentPropertyDefinitions: {
        Size: { type: 'VARIANT', variantOptions: ['Small', 'Medium', 'Large'], defaultValue: 'Medium' },
        State: { type: 'VARIANT', variantOptions: ['Default', 'Hover', 'Pressed', 'Disabled'], defaultValue: 'Default' },
        'Has Icon': { type: 'BOOLEAN', defaultValue: false }
      },
      children: [
        {
          id: '100:2',
          name: 'Size=Medium, State=Default, Has Icon=false',
          type: 'COMPONENT',
          fills: [{ type: 'SOLID', color: { r: 0.2, g: 0.4, b: 0.8 }, visible: true }],
          strokes: [],
          effects: [],
          cornerRadius: 8,
          opacity: 1,
          layoutMode: 'HORIZONTAL',
          itemSpacing: 8,
          paddingTop: 12,
          paddingRight: 24,
          paddingBottom: 12,
          paddingLeft: 24,
          primaryAxisSizingMode: 'AUTO',
          counterAxisSizingMode: 'FIXED',
          children: [
            {
              id: '100:3',
              name: 'Label',
              type: 'TEXT',
              fills: [{ type: 'SOLID', color: { r: 1, g: 1, b: 1 } }],
              styles: { text: 'S:text-body' }
            }
          ]
        },
        {
          id: '100:4',
          name: 'Size=Medium, State=Hover, Has Icon=false',
          type: 'COMPONENT',
          fills: [{ type: 'SOLID', color: { r: 0.3, g: 0.5, b: 0.9 }, visible: true }],
          effects: [{ type: 'DROP_SHADOW', radius: 4, offset: { x: 0, y: 2 }, spread: 0, color: { r: 0, g: 0, b: 0, a: 0.15 }, visible: true }],
          cornerRadius: 8,
          opacity: 1
        },
        {
          id: '100:5',
          name: 'Size=Medium, State=Pressed, Has Icon=false',
          type: 'COMPONENT',
          fills: [{ type: 'SOLID', color: { r: 0.15, g: 0.35, b: 0.7 }, visible: true }],
          effects: [],
          cornerRadius: 8,
          opacity: 0.95
        },
        {
          id: '100:6',
          name: 'Size=Medium, State=Disabled, Has Icon=false',
          type: 'COMPONENT',
          fills: [{ type: 'SOLID', color: { r: 0.6, g: 0.6, b: 0.6 }, visible: true }],
          effects: [],
          cornerRadius: 8,
          opacity: 0.5
        }
      ]
    },

    // Card Component
    {
      id: '200:1',
      name: 'Product Card',
      type: 'COMPONENT',
      description: 'Card for displaying product information',
      absoluteBoundingBox: { x: 300, y: 0, width: 320, height: 400 },
      fills: [{ type: 'SOLID', color: { r: 1, g: 1, b: 1 }, visible: true }],
      strokes: [{ type: 'SOLID', color: { r: 0.9, g: 0.9, b: 0.9 } }],
      strokeWeight: 1,
      effects: [{ type: 'DROP_SHADOW', radius: 8, offset: { x: 0, y: 4 }, spread: 0, color: { r: 0, g: 0, b: 0, a: 0.1 }, visible: true }],
      cornerRadius: 12,
      layoutMode: 'VERTICAL',
      itemSpacing: 16,
      paddingTop: 0,
      paddingRight: 0,
      paddingBottom: 16,
      paddingLeft: 0,
      children: [
        {
          id: '200:2',
          name: 'Image',
          type: 'RECTANGLE',
          fills: [{ type: 'IMAGE', imageRef: 'img:product-placeholder' }],
          absoluteBoundingBox: { x: 300, y: 0, width: 320, height: 200 }
        },
        {
          id: '200:3',
          name: 'Content',
          type: 'FRAME',
          layoutMode: 'VERTICAL',
          itemSpacing: 8,
          paddingLeft: 16,
          paddingRight: 16,
          children: [
            { id: '200:4', name: 'Title', type: 'TEXT' },
            { id: '200:5', name: 'Price', type: 'TEXT' },
            { id: '200:6', name: 'Description', type: 'TEXT' }
          ]
        }
      ]
    },

    // Icon Component
    {
      id: '300:1',
      name: 'Icon/Arrow/Right',
      type: 'COMPONENT',
      description: 'Right arrow icon',
      absoluteBoundingBox: { x: 700, y: 0, width: 24, height: 24 },
      fills: [{ type: 'SOLID', color: { r: 0, g: 0, b: 0 }, visible: true }]
    },

    // Input Component Set
    {
      id: '400:1',
      name: 'Text Input',
      type: 'COMPONENT_SET',
      componentPropertyDefinitions: {
        State: { type: 'VARIANT', variantOptions: ['Default', 'Focus', 'Error', 'Disabled'], defaultValue: 'Default' },
        'Has Label': { type: 'BOOLEAN', defaultValue: true },
        Placeholder: { type: 'TEXT', defaultValue: 'Enter text...' }
      },
      children: [
        {
          id: '400:2',
          name: 'State=Default, Has Label=true',
          type: 'COMPONENT',
          fills: [{ type: 'SOLID', color: { r: 1, g: 1, b: 1 }, visible: true }],
          strokes: [{ type: 'SOLID', color: { r: 0.8, g: 0.8, b: 0.8 } }],
          strokeWeight: 1,
          cornerRadius: 4,
          opacity: 1
        },
        {
          id: '400:3',
          name: 'State=Focus, Has Label=true',
          type: 'COMPONENT',
          fills: [{ type: 'SOLID', color: { r: 1, g: 1, b: 1 }, visible: true }],
          strokes: [{ type: 'SOLID', color: { r: 0.2, g: 0.4, b: 0.8 } }],
          strokeWeight: 2,
          cornerRadius: 4,
          opacity: 1,
          effects: [{ type: 'DROP_SHADOW', radius: 0, offset: { x: 0, y: 0 }, spread: 2, color: { r: 0.2, g: 0.4, b: 0.8, a: 0.3 }, visible: true }]
        }
      ]
    }
  ]
};

/**
 * E2E Test: Complete extraction workflow
 */
function runTests() {
  console.log('\n=== Figma MCP Skill E2E Tests ===\n');

  cleanup();

  // ============================================
  // Test 1: Validate input data
  // ============================================
  console.log('1. Input Validation:');

  const buttonNode = mockFigmaFile.components[0];
  const buttonValidation = validateNode(buttonNode);
  test('Button node validation passes', buttonValidation.valid === true);

  const cardNode = mockFigmaFile.components[1];
  const cardValidation = validateNode(cardNode);
  test('Card node validation passes', cardValidation.valid === true);

  // Test invalid input handling
  const invalidValidation = validateNode(null);
  test('Null node validation fails', invalidValidation.valid === false);

  // ============================================
  // Test 2: Sanitize and prepare nodes
  // ============================================
  console.log('\n2. Node Sanitization:');

  const sanitizedButton = sanitizeNode(buttonNode);
  test('Button sanitized successfully', sanitizedButton !== null);
  test('Sanitized button has id', sanitizedButton.id === '100:1');
  test('Sanitized button has name', sanitizedButton.name === 'Button');
  test('Sanitized button has children', Array.isArray(sanitizedButton.children));

  // ============================================
  // Test 3: Extract components with safe wrapper
  // ============================================
  console.log('\n3. Component Extraction:');

  const buttonExtract = safeExtract(extractComponent, buttonNode, { styles: mockFigmaFile.styles });
  test('Button extraction succeeds', buttonExtract.success === true);
  test('Button has extracted data', buttonExtract.data !== null);
  test('Button name extracted', buttonExtract.data.name === 'Button');
  test('Button type extracted', buttonExtract.data.type === 'COMPONENT_SET');
  test('Button has variants', buttonExtract.data.variants !== null);
  test('Button variants count', buttonExtract.data.variants.length === 3);
  test('Button has props', buttonExtract.data.props.length === 3);
  test('Button has layout', buttonExtract.data.children[0].layout !== null);

  const cardExtract = safeExtract(extractComponent, cardNode, { styles: mockFigmaFile.styles });
  test('Card extraction succeeds', cardExtract.success === true);
  test('Card has visual properties', cardExtract.data.visual !== null);
  test('Card has corner radius', cardExtract.data.visual.cornerRadius !== null);
  test('Card corner radius value', cardExtract.data.visual.cornerRadius.all === 12);
  test('Card has effects', cardExtract.data.visual.effects.length > 0);

  const iconExtract = safeExtract(extractComponent, mockFigmaFile.components[2], {});
  test('Icon extraction succeeds', iconExtract.success === true);
  test('Icon name extracted', iconExtract.data.name === 'Icon/Arrow/Right');

  // ============================================
  // Test 4: Interactive state detection
  // ============================================
  console.log('\n4. Interactive State Detection:');

  const buttonStates = detectInteractiveStates(buttonNode);
  test('Button has hover state', buttonStates.hover !== undefined);
  test('Button has pressed state', buttonStates.pressed !== undefined);
  test('Button has disabled state', buttonStates.disabled !== undefined);

  test('Hover has backgroundColor', buttonStates.hover.backgroundColor !== undefined);
  test('Hover has boxShadow', buttonStates.hover.boxShadow !== undefined);
  test('Disabled has opacity', buttonStates.disabled.opacity === 0.5);

  const inputStates = detectInteractiveStates(mockFigmaFile.components[3]);
  test('Input has focused state', inputStates.focused !== undefined);
  test('Input focused has boxShadow', inputStates.focused.boxShadow !== undefined);

  // Card is not a COMPONENT_SET, should return empty
  const cardStates = detectInteractiveStates(cardNode);
  test('Card returns empty states', Object.keys(cardStates).length === 0);

  // ============================================
  // Test 5: Generate CSS from states
  // ============================================
  console.log('\n5. CSS Generation:');

  const buttonCss = generateStateCss(buttonStates, '.button');
  test('CSS generated for button', buttonCss.length > 0);
  test('CSS has hover selector', buttonCss.includes('.button:hover'));
  test('CSS has active selector', buttonCss.includes('.button:active'));
  test('CSS has disabled selector', buttonCss.includes('.button:disabled'));

  // ============================================
  // Test 6: Component validation before registry
  // ============================================
  console.log('\n6. Component Validation:');

  const buttonComponentValidation = validateComponent(buttonExtract.data);
  test('Extracted button passes validation', buttonComponentValidation.valid === true);

  const cardComponentValidation = validateComponent(cardExtract.data);
  test('Extracted card passes validation', cardComponentValidation.valid === true);

  // ============================================
  // Test 7: Registry integration
  // ============================================
  console.log('\n7. Registry Integration:');

  // Create registry with first component
  const buttonRegistryResult = updateRegistry(testRegistryPath, {
    ...buttonExtract.data,
    figmaId: buttonNode.id,
    interactiveStates: buttonStates
  }, {
    fileKey: mockFigmaFile.fileKey,
    originalUrl: mockFigmaFile.originalUrl
  });

  test('Button added to registry', buttonRegistryResult.updated === true);
  test('Button has componentId', buttonRegistryResult.componentId !== undefined);
  test('Button category is button', buttonRegistryResult.entry.category === 'button');
  test('Button source is figma-mcp', buttonRegistryResult.entry.source.type === 'figma-mcp');
  test('Button has interactiveStates', buttonRegistryResult.entry.interactiveStates !== undefined);

  // Add more components
  const cardRegistryResult = updateRegistry(testRegistryPath, {
    ...cardExtract.data,
    figmaId: cardNode.id
  }, {
    fileKey: mockFigmaFile.fileKey,
    originalUrl: mockFigmaFile.originalUrl
  });

  test('Card added to registry', cardRegistryResult.updated === true);
  test('Card category is card', cardRegistryResult.entry.category === 'card');

  // Verify registry file
  const registry = JSON.parse(fs.readFileSync(testRegistryPath, 'utf-8'));
  test('Registry has 2 components', Object.keys(registry.components).length === 2);
  test('Registry tracks figma-mcp source', registry.metadata.extractionSources.includes('figma-mcp'));

  // ============================================
  // Test 8: Batch update
  // ============================================
  console.log('\n8. Batch Update:');

  cleanup(); // Reset registry

  const batchComponents = mockFigmaFile.components.map(node => {
    const extracted = extractComponent(node, { styles: mockFigmaFile.styles });
    const states = detectInteractiveStates(node);
    return {
      ...extracted,
      figmaId: node.id,
      interactiveStates: states
    };
  });

  const batchResults = batchUpdateRegistry(testRegistryPath, batchComponents, {
    fileKey: mockFigmaFile.fileKey,
    originalUrl: mockFigmaFile.originalUrl
  });

  test('Batch update returns 4 results', batchResults.length === 4);
  test('All batch updates succeeded', batchResults.every(r => r.updated));

  const batchRegistry = JSON.parse(fs.readFileSync(testRegistryPath, 'utf-8'));
  test('Batch registry has 4 components', Object.keys(batchRegistry.components).length === 4);

  // ============================================
  // Test 9: Error handling edge cases
  // ============================================
  console.log('\n9. Error Handling:');

  // Invalid node extraction
  const invalidExtract = safeExtract(extractComponent, null, {});
  test('Invalid extract returns error', invalidExtract.success === false);
  test('Invalid extract has error code', invalidExtract.error.code === ErrorCodes.VALIDATION_FAILED);

  // Depth exceeded check - pass a depth that's already over the limit
  const depthNode = { id: 'depth-test', name: 'Depth Test', type: 'FRAME' };
  const depthExtract = safeExtract(extractComponent, depthNode, { maxDepth: 10, depth: 15 });
  test('Depth exceeded returns failure', depthExtract.success === false);
  test('Depth exceeded error code', depthExtract.error.code === ErrorCodes.DEPTH_EXCEEDED);

  // Deep nesting (handled gracefully by extractComponent - stops at maxDepth)
  let deepNode = { id: 'deep', name: 'Deep', type: 'FRAME', children: [] };
  let current = deepNode;
  for (let i = 0; i < 60; i++) {
    const child = { id: `deep-${i}`, name: `Deep ${i}`, type: 'FRAME', children: [] };
    current.children.push(child);
    current = child;
  }
  const deepExtract = safeExtract(extractComponent, deepNode, { maxDepth: 10 });
  test('Deep nesting handled gracefully', deepExtract.success === true);

  // ============================================
  // Test 10: Result formatting
  // ============================================
  console.log('\n10. Result Formatting:');

  const formattedComponent = formatComponentResult(buttonExtract.data);
  test('Component formatting includes name', formattedComponent.includes('Button'));
  test('Component formatting includes type', formattedComponent.includes('COMPONENT_SET'));
  test('Component formatting includes variants', formattedComponent.includes('Variants'));

  const formattedStates = formatStateResults(buttonStates);
  test('State formatting includes count', formattedStates.includes('3'));
  test('State formatting includes hover', formattedStates.includes('hover'));

  const formattedRegistry = formatRegistryResult(batchResults);
  test('Registry formatting includes complete', formattedRegistry.includes('Complete'));
  test('Registry formatting includes updated count', formattedRegistry.includes('4'));

  // ============================================
  // Test 11: Full workflow result
  // ============================================
  console.log('\n11. Full Workflow Result:');

  const workflowResult = createResult(true, {
    extractedComponents: batchResults.length,
    statesDetected: Object.keys(buttonStates).length,
    registryPath: testRegistryPath
  }, null, {
    fileKey: mockFigmaFile.fileKey,
    totalComponents: mockFigmaFile.components.length
  });

  test('Workflow result is success', workflowResult.success === true);
  test('Workflow has timestamp', workflowResult.metadata.timestamp !== undefined);
  test('Workflow has fileKey', workflowResult.metadata.fileKey === mockFigmaFile.fileKey);
  test('Workflow has extracted count', workflowResult.data.extractedComponents === 4);

  // Cleanup
  cleanup();

  // Summary
  console.log('\n=============================');
  console.log(`E2E Results: ${passed} passed, ${failed} failed`);
  console.log('=============================\n');

  // Print test summary
  console.log('Test Coverage:');
  console.log('  - Input validation');
  console.log('  - Node sanitization');
  console.log('  - Component extraction');
  console.log('  - Interactive state detection');
  console.log('  - CSS generation');
  console.log('  - Component validation');
  console.log('  - Registry integration');
  console.log('  - Batch updates');
  console.log('  - Error handling');
  console.log('  - Result formatting');
  console.log('  - Full workflow integration\n');

  return { passed, failed };
}

// Run tests
if (require.main === module) {
  const result = runTests();
  process.exit(result.failed > 0 ? 1 : 0);
}

module.exports = { runTests };
