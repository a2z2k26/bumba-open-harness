/**
 * figma-component-extractor.test.js
 * Unit tests for the Figma component extractor
 */

const {
  extractComponent,
  extractVisualProperties,
  extractLayoutProperties,
  extractVariantDefinitions,
  extractPropsFromVariants,
  extractCornerRadius,
  extractTokenDependencies,
  aggregateChildTokens,
  toCamelCase,
  formatComponentResult
} = require('./figma-component-extractor');

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

// Mock Figma nodes
const mockFrameNode = {
  id: '1:100',
  name: 'Card',
  type: 'FRAME',
  description: 'A card component',
  absoluteBoundingBox: { x: 0, y: 0, width: 320, height: 200 },
  opacity: 1,
  blendMode: 'NORMAL',
  visible: true,
  fills: [
    { type: 'SOLID', visible: true, color: { r: 1, g: 1, b: 1 }, opacity: 1 }
  ],
  strokes: [
    { type: 'SOLID', visible: true, color: { r: 0.8, g: 0.8, b: 0.8 } }
  ],
  strokeWeight: 1,
  effects: [
    { type: 'DROP_SHADOW', visible: true, color: { r: 0, g: 0, b: 0, a: 0.1 }, offset: { x: 0, y: 2 }, radius: 4 }
  ],
  cornerRadius: 8,
  layoutMode: 'VERTICAL',
  itemSpacing: 16,
  paddingTop: 24,
  paddingRight: 24,
  paddingBottom: 24,
  paddingLeft: 24,
  primaryAxisSizingMode: 'AUTO',
  counterAxisSizingMode: 'FIXED',
  primaryAxisAlignItems: 'MIN',
  counterAxisAlignItems: 'CENTER'
};

const mockComponentSet = {
  id: '2:200',
  name: 'Button',
  type: 'COMPONENT_SET',
  description: 'Button component with variants',
  componentPropertyDefinitions: {
    'Size': {
      type: 'VARIANT',
      variantOptions: ['Small', 'Medium', 'Large'],
      defaultValue: 'Medium'
    },
    'State': {
      type: 'VARIANT',
      variantOptions: ['Default', 'Hover', 'Pressed', 'Disabled'],
      defaultValue: 'Default'
    },
    'HasIcon': {
      type: 'BOOLEAN',
      defaultValue: false
    },
    'Label': {
      type: 'TEXT',
      defaultValue: 'Click me'
    },
    'Icon': {
      type: 'INSTANCE_SWAP',
      preferredValues: [{ type: 'COMPONENT', key: 'icon-1' }]
    }
  },
  children: []
};

const mockTextNode = {
  id: '3:300',
  name: 'Label',
  type: 'TEXT',
  styles: { text: 'style-123' }
};

const mockNodeWithIndividualCorners = {
  id: '4:400',
  name: 'Rounded Frame',
  type: 'FRAME',
  rectangleCornerRadii: [8, 8, 0, 0]
};

function runTests() {
  console.log('\n=== Figma Component Extractor Tests ===\n');

  // Test toCamelCase
  console.log('toCamelCase:');

  test('converts simple string', toCamelCase('Size') === 'size');
  test('handles spaces', toCamelCase('Has Icon') === 'hasIcon');
  test('handles dashes', toCamelCase('primary-color') === 'primaryColor');
  test('handles underscores', toCamelCase('button_label') === 'buttonLabel');
  test('handles mixed', toCamelCase('Primary Color-Value') === 'primaryColorValue');

  // Test extractCornerRadius
  console.log('\nextractCornerRadius:');

  test('extracts uniform radius', extractCornerRadius(mockFrameNode).all === 8);

  const individualCorners = extractCornerRadius(mockNodeWithIndividualCorners);
  test('extracts individual top-left', individualCorners.topLeft === 8);
  test('extracts individual top-right', individualCorners.topRight === 8);
  test('extracts individual bottom-right', individualCorners.bottomRight === 0);
  test('extracts individual bottom-left', individualCorners.bottomLeft === 0);

  test('returns null for no radius', extractCornerRadius({}) === null);

  // Test extractVisualProperties
  console.log('\nextractVisualProperties:');

  const visual = extractVisualProperties(mockFrameNode);

  test('extracts opacity', visual.opacity === 1);
  test('extracts blendMode', visual.blendMode === 'NORMAL');
  test('extracts visible', visual.visible === true);
  test('extracts fills array', Array.isArray(visual.fills));
  test('extracts fill type', visual.fills[0].type === 'SOLID');
  test('extracts fill color', visual.fills[0].color.r === 1);
  test('extracts strokes array', visual.strokes.length === 1);
  test('extracts stroke weight', visual.strokes[0].weight === 1);
  test('extracts effects array', visual.effects.length === 1);
  test('extracts effect type', visual.effects[0].type === 'DROP_SHADOW');
  test('extracts effect radius', visual.effects[0].radius === 4);
  test('extracts corner radius', visual.cornerRadius.all === 8);

  // Test filtering invisible items
  const nodeWithHiddenFill = {
    fills: [
      { type: 'SOLID', visible: false, color: { r: 0, g: 0, b: 0 } },
      { type: 'SOLID', visible: true, color: { r: 1, g: 1, b: 1 } }
    ]
  };
  const filteredVisual = extractVisualProperties(nodeWithHiddenFill);
  test('filters invisible fills', filteredVisual.fills.length === 1);

  // Test extractLayoutProperties
  console.log('\nextractLayoutProperties:');

  const layout = extractLayoutProperties(mockFrameNode);

  test('extracts layout mode', layout.mode === 'VERTICAL');
  test('converts to CSS direction', layout.direction === 'column');
  test('extracts gap', layout.gap === 16);
  test('extracts padding top', layout.padding.top === 24);
  test('extracts padding right', layout.padding.right === 24);
  test('extracts primary axis sizing', layout.primaryAxisSizing === 'AUTO');
  test('extracts counter axis sizing', layout.counterAxisSizing === 'FIXED');
  test('extracts primary axis alignment', layout.primaryAxisAlignment === 'MIN');
  test('extracts counter axis alignment', layout.counterAxisAlignment === 'CENTER');

  const noLayout = extractLayoutProperties({});
  test('returns null for no layout', noLayout === null);

  const noneLayout = extractLayoutProperties({ layoutMode: 'NONE' });
  test('returns null for NONE layout', noneLayout === null);

  // Test horizontal layout
  const horizontalLayout = extractLayoutProperties({ layoutMode: 'HORIZONTAL' });
  test('converts HORIZONTAL to row', horizontalLayout.direction === 'row');

  // Test extractVariantDefinitions
  console.log('\nextractVariantDefinitions:');

  const variants = extractVariantDefinitions(mockComponentSet);

  test('extracts variant count', variants.length === 5);

  const sizeVariant = variants.find(v => v.name === 'Size');
  test('extracts size variant', sizeVariant !== undefined);
  test('extracts variant options', sizeVariant.options.length === 3);
  test('extracts variant default', sizeVariant.default === 'Medium');
  test('extracts variant type', sizeVariant.type === 'variant');

  const hasIconVariant = variants.find(v => v.name === 'HasIcon');
  test('extracts boolean variant', hasIconVariant.type === 'boolean');
  test('extracts boolean default', hasIconVariant.default === false);

  const labelVariant = variants.find(v => v.name === 'Label');
  test('extracts text variant', labelVariant.type === 'text');
  test('extracts text default', labelVariant.default === 'Click me');

  const iconVariant = variants.find(v => v.name === 'Icon');
  test('extracts slot variant', iconVariant.type === 'slot');

  test('returns null for non-COMPONENT_SET', extractVariantDefinitions({ type: 'FRAME' }) === null);

  // Test extractPropsFromVariants
  console.log('\nextractPropsFromVariants:');

  const props = extractPropsFromVariants(mockComponentSet);

  test('extracts props count', props.length === 5);

  const sizeProp = props.find(p => p.name === 'size');
  test('converts variant to union type', sizeProp.type.includes("'Small'"));
  test('variant type includes all options', sizeProp.type.includes("'Large'"));

  const hasIconProp = props.find(p => p.name === 'hasIcon');
  test('converts boolean to boolean type', hasIconProp.type === 'boolean');

  const labelProp = props.find(p => p.name === 'label');
  test('converts text to string type', labelProp.type === 'string');

  const iconProp = props.find(p => p.name === 'icon');
  test('converts slot to ReactNode type', iconProp.type === 'ReactNode');

  test('returns empty for non-COMPONENT_SET', extractPropsFromVariants({ type: 'FRAME' }).length === 0);

  // Test extractTokenDependencies
  console.log('\nextractTokenDependencies:');

  const deps = {
    colors: [],
    typography: [],
    spacing: [],
    effects: [],
    borderRadius: []
  };

  const mockStyles = {
    'style-123': { name: 'Body/Regular' }
  };

  extractTokenDependencies(mockTextNode, deps, mockStyles);
  test('extracts typography dependency', deps.typography.includes('Body/Regular'));

  extractTokenDependencies(mockFrameNode, deps, {});
  test('extracts corner radius', deps.borderRadius.includes('8px'));
  test('extracts spacing', deps.spacing.includes('16px'));

  // Test aggregateChildTokens
  console.log('\naggregateChildTokens:');

  const parentComponent = {
    tokenDependencies: {
      colors: ['Primary/500'],
      typography: [],
      spacing: [],
      effects: [],
      borderRadius: []
    },
    children: [
      {
        tokenDependencies: {
          colors: ['Secondary/300', 'Primary/500'],
          typography: ['Body/Regular'],
          spacing: [],
          effects: [],
          borderRadius: []
        }
      },
      {
        tokenDependencies: {
          colors: ['Secondary/300'],
          typography: [],
          spacing: ['16px'],
          effects: [],
          borderRadius: []
        }
      }
    ]
  };

  aggregateChildTokens(parentComponent);

  test('aggregates colors from children', parentComponent.tokenDependencies.colors.includes('Secondary/300'));
  test('aggregates typography from children', parentComponent.tokenDependencies.typography.includes('Body/Regular'));
  test('deduplicates colors', parentComponent.tokenDependencies.colors.filter(c => c === 'Primary/500').length === 1);
  test('deduplicates child colors', parentComponent.tokenDependencies.colors.filter(c => c === 'Secondary/300').length === 1);

  // Test extractComponent
  console.log('\nextractComponent:');

  const extracted = extractComponent(mockFrameNode, {});

  test('extracts id', extracted.id === '1:100');
  test('extracts name', extracted.name === 'Card');
  test('extracts type', extracted.type === 'FRAME');
  test('extracts description', extracted.description === 'A card component');
  test('extracts bounds width', extracted.bounds.width === 320);
  test('extracts bounds height', extracted.bounds.height === 200);
  test('extracts visual object', extracted.visual !== undefined);
  test('extracts layout object', extracted.layout !== null);
  test('extracts tokenDependencies', extracted.tokenDependencies !== undefined);
  test('extracts _figma object', extracted._figma !== undefined);
  test('preserves fills in _figma', extracted._figma.fills !== undefined);

  // Test COMPONENT_SET extraction
  const extractedSet = extractComponent(mockComponentSet, {});
  test('extracts variants for COMPONENT_SET', extractedSet.variants !== null);
  test('extracts props for COMPONENT_SET', extractedSet.props.length === 5);

  // Test INSTANCE extraction
  const mockInstance = {
    id: '5:500',
    name: 'Button Instance',
    type: 'INSTANCE',
    componentId: '2:200'
  };
  const extractedInstance = extractComponent(mockInstance, {});
  test('extracts componentRef for INSTANCE', extractedInstance.componentRef !== null);
  test('extracts componentRef id', extractedInstance.componentRef.id === '2:200');

  // Test recursive extraction with maxDepth
  const deepNode = {
    id: '6:600',
    name: 'Deep',
    type: 'FRAME',
    children: [
      {
        id: '6:601',
        name: 'Level 1',
        type: 'FRAME',
        children: [
          {
            id: '6:602',
            name: 'Level 2',
            type: 'FRAME'
          }
        ]
      }
    ]
  };

  const deepExtracted = extractComponent(deepNode, { maxDepth: 1 });
  test('respects maxDepth', deepExtracted.children[0].children === undefined);

  const fullExtracted = extractComponent(deepNode, { maxDepth: 10 });
  test('extracts full depth when allowed', fullExtracted.children[0].children !== undefined);

  // Test formatComponentResult
  console.log('\nformatComponentResult:');

  const formatted = formatComponentResult(extracted);

  test('includes component name', formatted.includes('Card'));
  test('includes type', formatted.includes('FRAME'));
  test('includes size', formatted.includes('320x200'));
  test('includes layout direction', formatted.includes('column'));

  const formattedSet = formatComponentResult(extractedSet);
  test('includes variants', formattedSet.includes('Size'));
  test('includes props', formattedSet.includes('size'));

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
