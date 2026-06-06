/**
 * extract-figma-mcp.test.js
 * Unit tests for the Figma MCP extraction skill wrapper
 */

const {
  extractFromFigmaMcp,
  detectInteractiveStates,
  diffVariantStyles,
  formatExtractionResult
} = require('./extract-figma-mcp');

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

// Mock MCP client
function createMockMcpClient(responses = {}) {
  return {
    call: async (method, params) => {
      if (responses[method]) {
        return responses[method](params);
      }
      throw new Error(`Mock not found for ${method}`);
    }
  };
}

// Mock component set with variants
const mockComponentSetVariants = [
  {
    name: 'State=Default, Size=Medium',
    figmaProperties: {
      fills: [{ type: 'SOLID', color: { r: 0.2, g: 0.4, b: 0.8 } }],
      effects: [],
      opacity: 1
    }
  },
  {
    name: 'State=Hover, Size=Medium',
    figmaProperties: {
      fills: [{ type: 'SOLID', color: { r: 0.3, g: 0.5, b: 0.9 } }],
      effects: [{ type: 'DROP_SHADOW', radius: 4 }],
      opacity: 1
    }
  },
  {
    name: 'State=Pressed, Size=Medium',
    figmaProperties: {
      fills: [{ type: 'SOLID', color: { r: 0.1, g: 0.3, b: 0.7 } }],
      effects: [],
      opacity: 0.9
    }
  },
  {
    name: 'State=Disabled, Size=Medium',
    figmaProperties: {
      fills: [{ type: 'SOLID', color: { r: 0.5, g: 0.5, b: 0.5 } }],
      effects: [],
      opacity: 0.5
    }
  }
];

function runTests() {
  console.log('\n=== Figma MCP Skill Wrapper Tests ===\n');

  // Test detectInteractiveStates
  console.log('detectInteractiveStates:');

  const componentSet = {
    type: 'COMPONENT_SET',
    children: mockComponentSetVariants
  };

  const states = detectInteractiveStates(componentSet);

  test('detects hover state', states.hover !== undefined);
  test('detects pressed state', states.pressed !== undefined);
  test('detects disabled state', states.disabled !== undefined);

  test('hover has fill changes', states.hover?.fills !== undefined);
  test('hover has effect changes', states.hover?.effects !== undefined);
  test('pressed has opacity change', states.pressed?.opacity !== undefined);
  test('disabled has opacity change', states.disabled?.opacity !== undefined);

  const emptySet = { type: 'COMPONENT_SET', children: [] };
  test('returns empty for no children', Object.keys(detectInteractiveStates(emptySet)).length === 0);

  const nullSet = { type: 'COMPONENT_SET' };
  test('returns empty for null children', Object.keys(detectInteractiveStates(nullSet)).length === 0);

  // Test diffVariantStyles
  console.log('\ndiffVariantStyles:');

  const defaultV = {
    figmaProperties: {
      fills: [{ type: 'SOLID', color: { r: 1, g: 0, b: 0 } }],
      effects: [],
      opacity: 1
    }
  };

  const hoverV = {
    figmaProperties: {
      fills: [{ type: 'SOLID', color: { r: 0, g: 1, b: 0 } }],
      effects: [{ type: 'DROP_SHADOW' }],
      opacity: 0.8
    }
  };

  const diff = diffVariantStyles(defaultV, hoverV);

  test('detects fill change', diff.fills !== undefined);
  test('detects effect change', diff.effects !== undefined);
  test('detects opacity change', diff.opacity === 0.8);

  const sameFills = diffVariantStyles(defaultV, defaultV);
  test('no diff for same variant', Object.keys(sameFills).length === 0);

  // Test formatExtractionResult
  console.log('\nformatExtractionResult:');

  const successResult = {
    success: true,
    components: [
      {
        id: 'figma-mcp-123-456',
        name: 'Button',
        type: 'COMPONENT_SET',
        tokenCount: { colors: 3, typography: 1 },
        hasStates: true
      }
    ],
    files: ['.design/source/components/button.json'],
    duration: 1234,
    log: ['Step 1', 'Step 2']
  };

  const formatted = formatExtractionResult(successResult);

  test('formats success result', formatted.includes('Extraction complete!'));
  test('includes component name', formatted.includes('Button'));
  test('includes token counts', formatted.includes('3 colors'));
  test('includes duration', formatted.includes('1234ms'));
  test('includes log', formatted.includes('Step 1'));

  const failResult = {
    success: false,
    error: 'Test error',
    log: ['Failed at step']
  };

  const failFormatted = formatExtractionResult(failResult);
  test('formats failure result', failFormatted.includes('Extraction failed'));
  test('includes error message', failFormatted.includes('Test error'));

  // Test extractFromFigmaMcp with mock client
  console.log('\nextractFromFigmaMcp (URL validation):');

  async function testUrlValidation() {
    const mockClient = createMockMcpClient();

    const result = await extractFromFigmaMcp({
      url: 'invalid-url',
      mcpClient: mockClient,
      projectRoot: '/tmp/test'
    });

    test('fails on invalid URL', result.success === false);
    test('includes error message', result.error.includes('Invalid Figma URL'));
  }

  // Run async test
  testUrlValidation().then(() => {
    // Summary
    console.log('\n=============================');
    console.log(`Results: ${passed} passed, ${failed} failed`);
    console.log('=============================\n');

    process.exit(failed > 0 ? 1 : 0);
  }).catch(err => {
    console.error('Test error:', err);
    process.exit(1);
  });
}

// Run tests
if (require.main === module) {
  runTests();
} else {
  module.exports = { runTests };
}
