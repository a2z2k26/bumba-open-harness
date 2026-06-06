/**
 * figma-transformer.test.js
 * Unit tests for the Figma-to-Bridge transformer
 */

const {
  transformFigmaNode,
  transformMcpResponse,
  transformStyles,
  transformComponentsList,
  extractColorFromFill,
  extractTypography,
  extractLayout,
  extractEffects,
  extractVariantProperties,
  extractInteractiveStates,
  TYPE_MAPPING,
  rgbToHex
} = require('./figma-transformer');

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

// Mock Figma node fixtures
const mockComponentNode = {
  id: '123:456',
  name: 'Button',
  type: 'COMPONENT',
  description: 'A primary button component',
  fills: [{ type: 'SOLID', color: { r: 0.2, g: 0.4, b: 0.8, a: 1 } }],
  strokes: [],
  effects: [
    {
      type: 'DROP_SHADOW',
      visible: true,
      color: { r: 0, g: 0, b: 0, a: 0.25 },
      offset: { x: 0, y: 4 },
      radius: 8,
      spread: 0
    }
  ],
  cornerRadius: 8,
  absoluteBoundingBox: { width: 120, height: 40 },
  layoutMode: 'HORIZONTAL',
  itemSpacing: 8,
  paddingTop: 12,
  paddingRight: 16,
  paddingBottom: 12,
  paddingLeft: 16,
  primaryAxisAlignItems: 'CENTER',
  counterAxisAlignItems: 'CENTER'
};

const mockTextNode = {
  id: '789:012',
  name: 'Label',
  type: 'TEXT',
  characters: 'Click me',
  style: {
    fontFamily: 'Inter',
    fontWeight: 500,
    fontSize: 14,
    lineHeightPx: 20,
    letterSpacing: 0.1
  },
  textAlignHorizontal: 'CENTER'
};

const mockComponentSet = {
  id: '111:222',
  name: 'Button',
  type: 'COMPONENT_SET',
  description: 'Button component set with variants',
  componentPropertyDefinitions: {
    'Size': {
      type: 'VARIANT',
      variantOptions: ['sm', 'md', 'lg'],
      defaultValue: 'md'
    },
    'State': {
      type: 'VARIANT',
      variantOptions: ['default', 'hover', 'pressed', 'disabled'],
      defaultValue: 'default'
    }
  },
  children: []
};

function runTests() {
  console.log('\n=== Figma Transformer Tests ===\n');

  // Test rgbToHex
  console.log('rgbToHex:');
  test('converts red', rgbToHex(1, 0, 0) === '#FF0000');
  test('converts green', rgbToHex(0, 1, 0) === '#00FF00');
  test('converts blue', rgbToHex(0, 0, 1) === '#0000FF');
  test('converts white', rgbToHex(1, 1, 1) === '#FFFFFF');
  test('converts black', rgbToHex(0, 0, 0) === '#000000');
  test('converts mid-gray', rgbToHex(0.5, 0.5, 0.5) === '#808080');

  // Test TYPE_MAPPING
  console.log('\nTYPE_MAPPING:');
  test('maps COMPONENT', TYPE_MAPPING['COMPONENT'] === 'COMPONENT');
  test('maps RECTANGLE to SHAPE', TYPE_MAPPING['RECTANGLE'] === 'SHAPE');
  test('maps FRAME', TYPE_MAPPING['FRAME'] === 'FRAME');
  test('maps TEXT', TYPE_MAPPING['TEXT'] === 'TEXT');

  // Test extractColorFromFill
  console.log('\nextractColorFromFill:');
  const solidFill = { type: 'SOLID', color: { r: 1, g: 0, b: 0, a: 1 } };
  const colorResult = extractColorFromFill(solidFill, {});
  test('extracts solid fill', colorResult !== null);
  test('returns hex value', colorResult.value === '#FF0000');
  test('returns opacity', colorResult.opacity === 1);

  const gradientFill = { type: 'GRADIENT_LINEAR' };
  test('returns null for gradients', extractColorFromFill(gradientFill, {}) === null);
  test('returns null for null', extractColorFromFill(null, {}) === null);

  // Test extractTypography
  console.log('\nextractTypography:');
  const typography = extractTypography(mockTextNode);
  test('extracts fontFamily', typography.fontFamily === 'Inter');
  test('extracts fontWeight', typography.fontWeight === 500);
  test('extracts fontSize', typography.fontSize === 14);
  test('extracts lineHeight', typography.lineHeight === 20);
  test('extracts textAlign', typography.textAlign === 'CENTER');
  test('returns null for non-TEXT', extractTypography(mockComponentNode) === null);

  // Test extractLayout
  console.log('\nextractLayout:');
  const layout = extractLayout(mockComponentNode);
  test('extracts direction', layout.direction === 'row');
  test('extracts gap', layout.gap === 8);
  test('extracts padding top', layout.padding.top === 12);
  test('extracts padding right', layout.padding.right === 16);
  test('extracts mainAxisAlignment', layout.mainAxisAlignment === 'center');
  test('extracts crossAxisAlignment', layout.crossAxisAlignment === 'center');

  const noLayoutNode = { layoutMode: 'NONE' };
  test('returns null for no layout', extractLayout(noLayoutNode) === null);

  // Test extractEffects
  console.log('\nextractEffects:');
  const effects = extractEffects(mockComponentNode.effects);
  test('extracts effects array', Array.isArray(effects));
  test('extracts shadow type', effects[0].type === 'dropShadow');
  test('extracts shadow color', effects[0].color === '#000000');
  test('extracts shadow blur', effects[0].blur === 8);
  test('extracts shadow y offset', effects[0].y === 4);
  test('returns empty for no effects', extractEffects([]).length === 0);
  test('returns empty for null', extractEffects(null).length === 0);

  // Test extractVariantProperties
  console.log('\nextractVariantProperties:');
  const variants = extractVariantProperties(mockComponentSet);
  test('extracts variants array', Array.isArray(variants));
  test('extracts Size variant', variants.some(v => v.name === 'Size'));
  test('extracts State variant', variants.some(v => v.name === 'State'));
  test('extracts variant values', variants[0].values.length > 0);
  test('returns null for non-COMPONENT_SET', extractVariantProperties(mockComponentNode) === null);

  // Test extractInteractiveStates
  console.log('\nextractInteractiveStates:');
  const states = extractInteractiveStates(mockComponentSet);
  test('extracts interactive states', states !== null);
  test('detects State property', states['State'] !== undefined);
  test('detects hover state', states['State'].detectedStates.includes('hover'));
  test('detects disabled state', states['State'].detectedStates.includes('disabled'));

  // Test transformFigmaNode
  console.log('\ntransformFigmaNode:');
  const transformed = transformFigmaNode(mockComponentNode, {}, { fileKey: 'test123' });
  test('sets id with figma prefix', transformed.id.startsWith('figma-'));
  test('preserves figmaId', transformed.figmaId === '123:456');
  test('maps type', transformed.type === 'COMPONENT');
  test('extracts name', transformed.name === 'Button');
  test('sets source.type', transformed.source.type === 'figma-mcp');
  test('sets source.fileKey', transformed.source.fileKey === 'test123');
  test('extracts dimensions', transformed.dimensions.width === 120);
  test('extracts layout', transformed.layout !== null);
  test('extracts tokenDependencies', transformed.tokenDependencies !== undefined);
  test('extracts figmaProperties', transformed.figmaProperties !== undefined);

  // Test with children
  console.log('\ntransformFigmaNode (with children):');
  const nodeWithChildren = {
    ...mockComponentNode,
    children: [mockTextNode]
  };
  const transformedWithChildren = transformFigmaNode(nodeWithChildren, {}, { fileKey: 'test123' });
  test('transforms children', Array.isArray(transformedWithChildren.children));
  test('children have correct structure', transformedWithChildren.children[0].name === 'Label');

  // Test transformMcpResponse
  console.log('\ntransformMcpResponse:');
  const mcpResponse = {
    name: 'Design File',
    lastModified: '2024-01-15T10:00:00Z',
    nodes: {
      '123:456': { document: mockComponentNode }
    }
  };
  const transformedResponse = transformMcpResponse(mcpResponse, 'fileKey123');
  test('returns array', Array.isArray(transformedResponse));
  test('transforms node from response', transformedResponse.length === 1);
  test('adds fileMetadata', transformedResponse[0].fileMetadata !== undefined);
  test('fileMetadata has fileName', transformedResponse[0].fileMetadata.fileName === 'Design File');

  // Test transformStyles
  console.log('\ntransformStyles:');
  const stylesResponse = {
    meta: {
      styles: [
        { name: 'Primary Blue', style_type: 'FILL', key: 'abc', node_id: '1:1', description: 'Main brand color' },
        { name: 'Heading 1', style_type: 'TEXT', key: 'def', node_id: '2:2', description: 'Main heading' },
        { name: 'Card Shadow', style_type: 'EFFECT', key: 'ghi', node_id: '3:3', description: 'Card elevation' }
      ]
    }
  };
  const tokens = transformStyles(stylesResponse);
  test('extracts colors', tokens.colors['Primary Blue'] !== undefined);
  test('extracts typography', tokens.typography['Heading 1'] !== undefined);
  test('extracts effects', tokens.effects['Card Shadow'] !== undefined);

  // Test transformComponentsList
  console.log('\ntransformComponentsList:');
  const componentsResponse = {
    meta: {
      components: [
        { name: 'Button', node_id: '10:20', key: 'xyz', description: 'Button component', containing_frame: { name: 'Components' } }
      ]
    }
  };
  const entries = transformComponentsList(componentsResponse, 'fileKey123');
  test('returns array', Array.isArray(entries));
  test('extracts component', entries.length === 1);
  test('sets source type', entries[0].source.type === 'figma-mcp');
  test('preserves figmaNodeId', entries[0].figmaNodeId === '10:20');

  // Summary
  console.log('\n=============================');
  console.log(`Results: ${passed} passed, ${failed} failed`);
  console.log('=============================\n');

  return { passed, failed };
}

// Run tests
if (require.main === module) {
  const result = runTests();
  process.exit(result.failed > 0 ? 1 : 0);
}

module.exports = { runTests };
