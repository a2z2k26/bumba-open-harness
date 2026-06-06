/**
 * nlp-token-inference.test.js
 * Unit tests for NLP token inference
 */

const {
  inferTokenDependencies,
  inferColors,
  inferTypography,
  inferSpacing,
  inferBorderRadius,
  inferShadows,
  formatTokensForOutput,
  getCategoryColorDefaults,
  getCategoryTypographyDefaults,
  getCategorySpacingDefaults,
  colorMappings,
  typographyMappings,
  spacingMappings,
  radiusMappings
} = require('./nlp-token-inference');

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

function runTests() {
  console.log('\n=== NLP Token Inference Tests ===\n');

  // Test: Mappings exist
  console.log('--- Mappings ---');
  test('colorMappings exists', typeof colorMappings === 'object');
  test('has primary color', colorMappings.primary === 'Primary/500');
  test('has secondary color', colorMappings.secondary === 'Secondary/500');
  test('has semantic colors', colorMappings.success && colorMappings.error && colorMappings.warning);
  test('has neutral colors', colorMappings.white && colorMappings.black && colorMappings.gray);

  test('typographyMappings exists', typeof typographyMappings === 'object');
  test('has size mappings', typographyMappings.small && typographyMappings.large);
  test('has element mappings', typographyMappings.heading && typographyMappings.body);
  test('has weight mappings', typographyMappings.bold && typographyMappings.semibold);

  test('spacingMappings exists', typeof spacingMappings === 'object');
  test('has descriptive spacing', spacingMappings.tight && spacingMappings.spacious);
  test('has size spacing', spacingMappings.sm && spacingMappings.lg);

  test('radiusMappings exists', typeof radiusMappings === 'object');
  test('has shape radius', radiusMappings.sharp && radiusMappings.rounded);
  test('has pill/circle radius', radiusMappings.pill && radiusMappings.circle);

  // Test: inferColors - explicit mentions
  console.log('\n--- inferColors ---');
  const blueDesc = inferColors('a blue button', 'button');
  test('infers blue as Primary/500', blueDesc.some(c => c.name === 'Primary/500'));
  test('tracks source', blueDesc.some(c => c.source === 'blue'));

  const redDesc = inferColors('a red error state', 'feedback');
  test('infers red as Error/500', redDesc.some(c => c.name === 'Error/500'));

  const multiColor = inferColors('primary background with white text', 'button');
  test('infers multiple colors', multiColor.length >= 2);
  test('has primary', multiColor.some(c => c.name === 'Primary/500'));
  test('has white', multiColor.some(c => c.name === 'White'));
  test('has background', multiColor.some(c => c.name === 'Background'));

  // Test: inferColors - defaults
  const defaultColors = inferColors('a simple component', 'button');
  test('provides default colors', defaultColors.length >= 2);
  test('default has Primary/500', defaultColors.some(c => c.name === 'Primary/500'));

  // Test: getCategoryColorDefaults
  console.log('\n--- getCategoryColorDefaults ---');
  const buttonDefaults = getCategoryColorDefaults('button');
  test('button has Primary/500', buttonDefaults.includes('Primary/500'));
  test('button has White', buttonDefaults.includes('White'));

  const cardDefaults = getCategoryColorDefaults('card');
  test('card has Background', cardDefaults.includes('Background'));
  test('card has Border', cardDefaults.includes('Border'));

  const feedbackDefaults = getCategoryColorDefaults('feedback');
  test('feedback has semantic colors', feedbackDefaults.includes('Error/500'));

  const unknownDefaults = getCategoryColorDefaults('unknown');
  test('unknown uses default category', unknownDefaults.includes('Primary/500'));

  // Test: inferTypography
  console.log('\n--- inferTypography ---');
  const headingTypo = inferTypography('a heading with large text', 'card');
  test('infers heading typography', headingTypo.some(t => t.name === 'text-xl'));
  test('infers font-bold', headingTypo.some(t => t.name === 'font-bold'));
  test('infers large', headingTypo.some(t => t.name === 'text-lg'));

  const smallTypo = inferTypography('small label text', 'input');
  test('infers small text', smallTypo.some(t => t.name === 'text-sm'));
  test('infers label weight', smallTypo.some(t => t.name === 'font-medium'));

  const defaultTypo = inferTypography('a component', 'button');
  test('provides default typography', defaultTypo.length >= 2);

  // Test: getCategoryTypographyDefaults
  console.log('\n--- getCategoryTypographyDefaults ---');
  const buttonTypoDefaults = getCategoryTypographyDefaults('button');
  test('button has text-sm', buttonTypoDefaults.includes('text-sm'));
  test('button has font-medium', buttonTypoDefaults.includes('font-medium'));

  const cardTypoDefaults = getCategoryTypographyDefaults('card');
  test('card has multiple sizes', cardTypoDefaults.length >= 3);

  // Test: inferSpacing
  console.log('\n--- inferSpacing ---');
  const spaciousSpacing = inferSpacing('a spacious card with tight items', 'card');
  test('infers spacious', spaciousSpacing.some(s => s.name === '16'));
  test('infers tight', spaciousSpacing.some(s => s.name === '2'));

  const sizeSpacing = inferSpacing('sm padding with lg margins', 'button');
  test('infers sm', sizeSpacing.some(s => s.name === '4'));
  test('infers lg', sizeSpacing.some(s => s.name === '16'));

  const defaultSpacing = inferSpacing('a component', 'card');
  test('provides default spacing', defaultSpacing.length >= 2);

  // Test: getCategorySpacingDefaults
  console.log('\n--- getCategorySpacingDefaults ---');
  const buttonSpacingDefaults = getCategorySpacingDefaults('button');
  test('button has 4', buttonSpacingDefaults.includes('4'));
  test('button has 8', buttonSpacingDefaults.includes('8'));

  const cardSpacingDefaults = getCategorySpacingDefaults('card');
  test('card has 16', cardSpacingDefaults.includes('16'));
  test('card has 24', cardSpacingDefaults.includes('24'));

  // Test: inferBorderRadius
  console.log('\n--- inferBorderRadius ---');
  const roundedRadius = inferBorderRadius('a rounded button', 'button');
  test('infers rounded as md', roundedRadius.some(r => r.name === 'md'));
  test('tracks source', roundedRadius.some(r => r.source === 'rounded'));

  const pillRadius = inferBorderRadius('a pill shaped badge', 'button');
  test('infers pill as full', pillRadius.some(r => r.name === 'full'));

  const squareRadius = inferBorderRadius('a sharp square card', 'card');
  test('infers sharp as none', squareRadius.some(r => r.name === 'none'));
  test('infers square as none', squareRadius.filter(r => r.name === 'none').length >= 1);

  const defaultRadius = inferBorderRadius('a component', 'button');
  test('default radius is md', defaultRadius.some(r => r.name === 'md'));
  test('default source is default', defaultRadius.some(r => r.source === 'default'));

  // Test: inferShadows
  console.log('\n--- inferShadows ---');
  const shadowDesc = inferShadows('a card with shadow', 'card');
  test('infers shadow-md', shadowDesc.some(s => s.name === 'shadow-md'));
  test('tracks shadow source', shadowDesc.some(s => s.source === 'shadow'));

  const elevatedDesc = inferShadows('an elevated panel', 'component');
  test('infers elevated shadow', elevatedDesc.some(s => s.name === 'shadow-md'));

  const floatingDesc = inferShadows('a floating button', 'button');
  test('infers floating shadow', floatingDesc.some(s => s.name === 'shadow-md'));

  const cardNoShadow = inferShadows('a flat card', 'card');
  test('card gets default shadow', cardNoShadow.some(s => s.name === 'shadow-sm'));
  test('card shadow source is category-default', cardNoShadow.some(s => s.source === 'category-default'));

  const overlayDefault = inferShadows('a modal', 'overlay');
  test('overlay gets default shadow', overlayDefault.some(s => s.name === 'shadow-sm'));

  const buttonNoShadow = inferShadows('a flat button', 'button');
  test('button has no shadow by default', buttonNoShadow.length === 0);

  // Test: inferTokenDependencies - complete
  console.log('\n--- inferTokenDependencies ---');
  const buttonTokens = inferTokenDependencies('A primary rounded button with shadow', 'button');
  test('returns colors array', Array.isArray(buttonTokens.colors));
  test('returns typography array', Array.isArray(buttonTokens.typography));
  test('returns spacing array', Array.isArray(buttonTokens.spacing));
  test('returns borderRadius array', Array.isArray(buttonTokens.borderRadius));
  test('returns shadows array', Array.isArray(buttonTokens.shadows));
  test('has primary color', buttonTokens.colors.some(c => c.name === 'Primary/500'));
  test('has rounded radius', buttonTokens.borderRadius.some(r => r.name === 'md'));
  test('has shadow', buttonTokens.shadows.length > 0);

  const cardTokens = inferTokenDependencies('A card with title, description, and white background', 'card');
  test('card has white color', cardTokens.colors.some(c => c.name === 'White'));
  test('card has title typography', cardTokens.typography.some(t => t.name === 'text-lg'));

  // Test: formatTokensForOutput
  console.log('\n--- formatTokensForOutput ---');
  const tokens = {
    colors: [{ name: 'Primary/500', source: 'primary' }, { name: 'White', source: 'white' }],
    typography: [{ name: 'text-sm', source: 'small' }],
    spacing: [{ name: '8', source: 'normal' }],
    borderRadius: [{ name: 'md', source: 'rounded' }],
    shadows: [{ name: 'shadow-md', source: 'shadow' }]
  };
  const formatted = formatTokensForOutput(tokens);
  test('formats colors', Array.isArray(formatted.colors) && formatted.colors[0] === 'Primary/500');
  test('formats typography', Array.isArray(formatted.typography) && formatted.typography[0] === 'text-sm');
  test('formats spacing', Array.isArray(formatted.spacing) && formatted.spacing[0] === '8');
  test('formats borderRadius', Array.isArray(formatted.borderRadius) && formatted.borderRadius[0] === 'md');
  test('formats shadows', Array.isArray(formatted.shadows) && formatted.shadows[0] === 'shadow-md');
  test('removes source info', !formatted.colors[0].source);

  // Test: edge cases
  console.log('\n--- Edge Cases ---');
  const emptyDesc = inferTokenDependencies('', 'button');
  test('empty desc still returns tokens', emptyDesc.colors.length > 0);

  const unknownCategory = inferTokenDependencies('a component', 'unknown');
  test('unknown category uses defaults', unknownCategory.colors.length > 0);

  const greySpelling = inferColors('grey text on dark background', 'card');
  test('handles grey spelling', greySpelling.some(c => c.name === 'Neutral/500'));
  test('handles dark', greySpelling.some(c => c.name === 'Neutral/900'));

  // Test: deduplication
  console.log('\n--- Deduplication ---');
  const dupeDesc = inferColors('primary blue button with blue border', 'button');
  const primaryCount = dupeDesc.filter(c => c.name === 'Primary/500').length;
  test('deduplicates colors', primaryCount === 1);

  // Print results
  console.log('\n=== Test Results ===');
  console.log(`Passed: ${passed}`);
  console.log(`Failed: ${failed}`);
  console.log(`Total: ${passed + failed}`);

  return { passed, failed };
}

// Run if executed directly
if (require.main === module) {
  runTests();
}

module.exports = { runTests };
