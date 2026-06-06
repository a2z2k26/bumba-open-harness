/**
 * nlp-variant-generator.test.js
 * Unit tests for NLP variant generation
 */

const {
  generateVariants,
  parseVariantsFromDescription,
  generateVariantDefinitions,
  getVariantStyles,
  getVariantTokenOverrides,
  generateCompoundVariants,
  generateDefaultVariants,
  variantPatterns
} = require('./nlp-variant-generator');

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
  console.log('\n=== NLP Variant Generator Tests ===\n');

  // Test: variantPatterns exist
  console.log('--- Variant Patterns ---');
  test('variantPatterns exists', typeof variantPatterns === 'object');
  test('has appearance pattern', variantPatterns.appearance && variantPatterns.appearance.pattern);
  test('has size pattern', variantPatterns.size && variantPatterns.size.pattern);
  test('has state pattern', variantPatterns.state && variantPatterns.state.pattern);
  test('has style pattern', variantPatterns.style && variantPatterns.style.pattern);

  // Test: parseVariantsFromDescription
  console.log('\n--- parseVariantsFromDescription ---');

  const buttonDesc = parseVariantsFromDescription('a primary button with hover state');
  test('parses primary variant', buttonDesc.variant.includes('primary'));
  test('parses hover state', buttonDesc.state.includes('hover'));

  const sizeDesc = parseVariantsFromDescription('small and large sizes available');
  test('parses small as sm', sizeDesc.size.includes('sm'));
  test('parses large as lg', sizeDesc.size.includes('lg'));

  const multiVariant = parseVariantsFromDescription('primary, secondary, and outline variants');
  test('parses primary', multiVariant.variant.includes('primary'));
  test('parses secondary', multiVariant.variant.includes('secondary'));
  test('parses outline', multiVariant.variant.includes('outline'));

  const stateDesc = parseVariantsFromDescription('default, hover, disabled, and loading states');
  test('parses default state', stateDesc.state.includes('default'));
  test('parses hover state', stateDesc.state.includes('hover'));
  test('parses disabled state', stateDesc.state.includes('disabled'));
  test('parses loading state', stateDesc.state.includes('loading'));

  // Test: Normalization
  console.log('\n--- Normalization ---');

  const dangerDesc = parseVariantsFromDescription('danger button');
  test('normalizes danger to destructive', dangerDesc.variant.includes('destructive'));

  const filledDesc = parseVariantsFromDescription('filled button');
  test('normalizes filled to primary', filledDesc.variant.includes('primary'));

  const flatDesc = parseVariantsFromDescription('flat button');
  test('normalizes flat to ghost', flatDesc.variant.includes('ghost'));

  const smallSizeDesc = parseVariantsFromDescription('small button');
  test('normalizes small to sm', smallSizeDesc.size.includes('sm'));

  const mediumSizeDesc = parseVariantsFromDescription('medium size');
  test('normalizes medium to md', mediumSizeDesc.size.includes('md'));

  const largeSizeDesc = parseVariantsFromDescription('large size');
  test('normalizes large to lg', largeSizeDesc.size.includes('lg'));

  const extraLargeDesc = parseVariantsFromDescription('extra-large button');
  test('normalizes extra-large to xl', extraLargeDesc.size.includes('xl'));

  // Test: generateVariants
  console.log('\n--- generateVariants ---');

  const explicitVariants = generateVariants('a button component', ['primary', 'secondary']);
  test('generates variants from explicit list', explicitVariants.variant !== undefined);
  test('has primary variant', explicitVariants.variant && explicitVariants.variant.primary);
  test('has secondary variant', explicitVariants.variant && explicitVariants.variant.secondary);

  const implicitVariants = generateVariants('a primary outlined button with sm and lg sizes', []);
  test('generates implicit variants', implicitVariants.variant !== undefined);
  test('has outline variant', implicitVariants.variant && implicitVariants.variant.outline);
  test('generates implicit sizes', implicitVariants.size !== undefined);
  test('has sm size', implicitVariants.size && implicitVariants.size.sm);
  test('has lg size', implicitVariants.size && implicitVariants.size.lg);

  const mergedVariants = generateVariants('a primary button', ['secondary', 'ghost']);
  test('merges implicit and explicit', Object.keys(mergedVariants.variant || {}).length >= 3);

  // Test: generateVariantDefinitions
  console.log('\n--- generateVariantDefinitions ---');

  const variantDefs = generateVariantDefinitions('variant', ['primary', 'secondary']);
  test('generates definition object', typeof variantDefs === 'object');
  test('has primary definition', variantDefs.primary !== undefined);
  test('has secondary definition', variantDefs.secondary !== undefined);
  test('primary has properties', variantDefs.primary && variantDefs.primary.properties);
  test('primary has styles', variantDefs.primary && variantDefs.primary.styles);
  test('primary has tokenOverrides', variantDefs.primary && variantDefs.primary.tokenOverrides);
  test('primary properties.variant is primary',
    variantDefs.primary && variantDefs.primary.properties && variantDefs.primary.properties.variant === 'primary');

  const sizeDefs = generateVariantDefinitions('size', ['sm', 'md', 'lg']);
  test('generates size definitions', sizeDefs.sm && sizeDefs.md && sizeDefs.lg);
  test('sm has correct height', sizeDefs.sm && sizeDefs.sm.styles && sizeDefs.sm.styles.height === '32px');
  test('md has correct height', sizeDefs.md && sizeDefs.md.styles && sizeDefs.md.styles.height === '40px');
  test('lg has correct height', sizeDefs.lg && sizeDefs.lg.styles && sizeDefs.lg.styles.height === '48px');

  // Test: getVariantStyles
  console.log('\n--- getVariantStyles ---');

  const primaryStyles = getVariantStyles('variant', 'primary');
  test('primary has backgroundColor', primaryStyles.backgroundColor !== undefined);
  test('primary has color', primaryStyles.color !== undefined);
  test('primary uses var(--primary)', primaryStyles.backgroundColor === 'var(--primary)');

  const outlineStyles = getVariantStyles('variant', 'outline');
  test('outline has transparent background', outlineStyles.backgroundColor === 'transparent');
  test('outline has border', outlineStyles.border !== undefined);

  const ghostStyles = getVariantStyles('variant', 'ghost');
  test('ghost has transparent background', ghostStyles.backgroundColor === 'transparent');
  test('ghost has no border', ghostStyles.border === 'none');

  const smStyles = getVariantStyles('size', 'sm');
  test('sm has correct height', smStyles.height === '32px');
  test('sm has correct padding', smStyles.padding === '0 12px');
  test('sm has correct fontSize', smStyles.fontSize === '14px');

  const lgStyles = getVariantStyles('size', 'lg');
  test('lg has correct height', lgStyles.height === '48px');

  const disabledStyles = getVariantStyles('state', 'disabled');
  test('disabled has opacity', disabledStyles.opacity === '0.5');
  test('disabled has pointerEvents none', disabledStyles.pointerEvents === 'none');

  const hoverStyles = getVariantStyles('state', 'hover');
  test('hover has filter', hoverStyles.filter !== undefined);

  const focusStyles = getVariantStyles('state', 'focus');
  test('focus has outline', focusStyles.outline !== undefined);

  // Test: getVariantTokenOverrides
  console.log('\n--- getVariantTokenOverrides ---');

  const primaryTokens = getVariantTokenOverrides('variant', 'primary');
  test('primary has backgroundColor token', primaryTokens.backgroundColor === 'Primary/500');
  test('primary has textColor token', primaryTokens.textColor === 'White');

  const destructiveTokens = getVariantTokenOverrides('variant', 'destructive');
  test('destructive has Error/500', destructiveTokens.backgroundColor === 'Error/500');

  const outlineTokens = getVariantTokenOverrides('variant', 'outline');
  test('outline has borderColor', outlineTokens.borderColor === 'Primary/500');

  const smTokens = getVariantTokenOverrides('size', 'sm');
  test('sm has padding token', smTokens.padding === '4');
  test('sm has fontSize token', smTokens.fontSize === 'text-sm');

  const lgTokens = getVariantTokenOverrides('size', 'lg');
  test('lg has padding token', lgTokens.padding === '12');
  test('lg has fontSize token', lgTokens.fontSize === 'text-lg');

  // Test: generateCompoundVariants
  console.log('\n--- generateCompoundVariants ---');

  const compoundsWithIcon = generateCompoundVariants({
    variant: { primary: {}, secondary: {} },
    size: { icon: {}, md: {} }
  });
  test('generates compound variants for icon', compoundsWithIcon.length > 0);
  test('icon compound has conditions', compoundsWithIcon[0] && compoundsWithIcon[0].conditions);
  test('icon compound has size: icon', compoundsWithIcon[0] && compoundsWithIcon[0].conditions.size === 'icon');
  test('icon compound has width style', compoundsWithIcon[0] && compoundsWithIcon[0].styles.width === '40px');

  const noIconCompounds = generateCompoundVariants({
    variant: { primary: {} },
    size: { sm: {}, md: {} }
  });
  test('no compounds without icon size', noIconCompounds.length === 0);

  // Test: generateDefaultVariants
  console.log('\n--- generateDefaultVariants ---');

  const defaultsWithVariant = generateDefaultVariants({
    variant: { primary: {}, secondary: {} }
  });
  test('defaults to primary variant', defaultsWithVariant.variant === 'primary');

  const defaultsWithSize = generateDefaultVariants({
    size: { sm: {}, md: {}, lg: {} }
  });
  test('defaults to md size', defaultsWithSize.size === 'md');

  const defaultsWithSmOnly = generateDefaultVariants({
    size: { sm: {}, lg: {} }
  });
  test('defaults to first size if no md', defaultsWithSmOnly.size === 'sm');

  const defaultsWithBoth = generateDefaultVariants({
    variant: { primary: {}, ghost: {} },
    size: { xs: {}, sm: {}, md: {} }
  });
  test('defaults both variant and size', defaultsWithBoth.variant === 'primary' && defaultsWithBoth.size === 'md');

  // Test: Edge cases
  console.log('\n--- Edge Cases ---');

  const emptyDesc = parseVariantsFromDescription('');
  test('empty description returns empty arrays',
    emptyDesc.variant.length === 0 && emptyDesc.size.length === 0 && emptyDesc.state.length === 0);

  const noVariants = generateVariants('a simple component', []);
  test('no variants when nothing specified', Object.keys(noVariants).length === 0);

  const caseInsensitive = parseVariantsFromDescription('PRIMARY Secondary OUTLINE');
  test('case insensitive parsing',
    caseInsensitive.variant.includes('primary') &&
    caseInsensitive.variant.includes('secondary') &&
    caseInsensitive.variant.includes('outline'));

  // Test: Deduplication
  console.log('\n--- Deduplication ---');

  const dupeDesc = parseVariantsFromDescription('primary primary button with small small sizes');
  const primaryCount = dupeDesc.variant.filter(v => v === 'primary').length;
  const smCount = dupeDesc.size.filter(s => s === 'sm').length;
  test('deduplicates variant mentions', primaryCount === 1);
  test('deduplicates size mentions', smCount === 1);

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
