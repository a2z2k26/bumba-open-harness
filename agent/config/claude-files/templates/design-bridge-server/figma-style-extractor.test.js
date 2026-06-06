/**
 * figma-style-extractor.test.js
 * Unit tests for the Figma style extractor
 */

const {
  transformColorStyle,
  transformTextStyle,
  transformEffectStyle,
  parseTokenPath,
  generateCssVariableName,
  groupTokensByGroup,
  formatStyleResults
} = require('./figma-style-extractor');

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

// Mock style metadata
const mockColorStyle = {
  key: 'abc123',
  name: 'Primary/500',
  node_id: '1:100',
  style_type: 'FILL',
  description: 'Main brand color'
};

const mockTextStyle = {
  key: 'def456',
  name: 'Heading/H1',
  node_id: '2:200',
  style_type: 'TEXT',
  description: 'Main heading style'
};

const mockEffectStyle = {
  key: 'ghi789',
  name: 'Shadow/Card/Medium',
  node_id: '3:300',
  style_type: 'EFFECT',
  description: 'Card elevation shadow'
};

function runTests() {
  console.log('\n=== Figma Style Extractor Tests ===\n');

  // Test parseTokenPath
  console.log('parseTokenPath:');

  const simple = parseTokenPath('Primary/500');
  test('parses simple path', simple.path.length === 2);
  test('extracts group', simple.group === 'Primary');
  test('extracts variant', simple.variant === '500');

  const deep = parseTokenPath('Button/Primary/Default');
  test('parses deep path', deep.path.length === 3);
  test('deep path group is first', deep.group === 'Button');
  test('deep path variant is last', deep.variant === 'Default');

  const single = parseTokenPath('Primary');
  test('parses single name', single.path.length === 1);
  test('single name group', single.group === 'Primary');
  test('single name no variant', single.variant === null);

  const withSpaces = parseTokenPath('Primary Color / Light 100');
  test('handles spaces', withSpaces.path.length === 2);
  test('trims spaces', withSpaces.path[0] === 'Primary Color');

  // Test transformColorStyle
  console.log('\ntransformColorStyle:');

  const colorToken = transformColorStyle(mockColorStyle);

  test('sets id with prefix', colorToken.id.startsWith('color-'));
  test('preserves name', colorToken.name === 'Primary/500');
  test('sets category', colorToken.category === 'colors');
  test('sets path', colorToken.path.length === 2);
  test('sets group', colorToken.group === 'Primary');
  test('sets variant', colorToken.variant === '500');
  test('preserves description', colorToken.description === 'Main brand color');
  test('sets source type', colorToken.source.type === 'figma-mcp');
  test('preserves styleKey', colorToken.figmaStyleKey === 'abc123');

  // Test transformTextStyle
  console.log('\ntransformTextStyle:');

  const textToken = transformTextStyle(mockTextStyle);

  test('sets typography id', textToken.id.startsWith('typography-'));
  test('sets typography category', textToken.category === 'typography');
  test('sets typography path', textToken.path[0] === 'Heading');
  test('sets typography variant', textToken.variant === 'H1');

  // Test transformEffectStyle
  console.log('\ntransformEffectStyle:');

  const effectToken = transformEffectStyle(mockEffectStyle);

  test('sets effect id', effectToken.id.startsWith('effect-'));
  test('sets effect category', effectToken.category === 'effects');
  test('sets effect path', effectToken.path.length === 3);
  test('sets effect group', effectToken.group === 'Shadow');
  test('sets effect variant', effectToken.variant === 'Medium');

  // Test generateCssVariableName
  console.log('\ngenerateCssVariableName:');

  test('color variable', generateCssVariableName(colorToken) === '--color-primary-500');
  test('typography variable', generateCssVariableName(textToken) === '--font-heading-h1');
  test('effect variable', generateCssVariableName(effectToken) === '--shadow-shadow-card-medium');

  const withSpecialChars = {
    category: 'colors',
    path: ['Primary (Brand)', '500!']
  };
  const cssVar = generateCssVariableName(withSpecialChars);
  test('sanitizes special chars', !cssVar.includes('(') && !cssVar.includes('!'));

  // Test groupTokensByGroup
  console.log('\ngroupTokensByGroup:');

  const tokens = [
    { group: 'Primary', name: 'Primary/100' },
    { group: 'Primary', name: 'Primary/500' },
    { group: 'Secondary', name: 'Secondary/100' },
    { group: 'Primary', name: 'Primary/900' }
  ];

  const grouped = groupTokensByGroup(tokens);

  test('groups by group property', Object.keys(grouped).length === 2);
  test('Primary group has 3 items', grouped['Primary'].length === 3);
  test('Secondary group has 1 item', grouped['Secondary'].length === 1);

  const noGroup = groupTokensByGroup([{ name: 'Test' }]);
  test('defaults to Other group', noGroup['Other'] !== undefined);

  // Test formatStyleResults
  console.log('\nformatStyleResults:');

  const results = {
    colors: [colorToken, colorToken],
    typography: [textToken],
    effects: [effectToken],
    extracted: 4,
    errors: []
  };

  const formatted = formatStyleResults(results);

  test('includes completion message', formatted.includes('Style Extraction Complete'));
  test('includes color count', formatted.includes('Colors: 2'));
  test('includes typography count', formatted.includes('Typography: 1'));
  test('includes effects count', formatted.includes('Effects: 1'));
  test('includes total count', formatted.includes('Total: 4'));

  const withErrors = {
    colors: [],
    typography: [],
    effects: [],
    extracted: 0,
    errors: [{ styleId: '1:1', error: 'Test error' }]
  };

  const errorFormatted = formatStyleResults(withErrors);
  test('includes error count', errorFormatted.includes('Errors: 1'));
  test('includes error message', errorFormatted.includes('Test error'));

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
