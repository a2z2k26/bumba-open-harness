/**
 * Phase 1 Comprehensive Test Suite
 * Tests all code generation fixes implemented in Sprints 1-50
 */

const fs = require('fs');
const path = require('path');

// Load the SmartCodeGenerator
const SmartCodeGenerator = require('./smart-code-generator.js');

// Test data paths (relative to project root)
const projectRoot = path.join(__dirname, '..');
const COMPONENTS_DIR = path.join(projectRoot, '.design/components');
const TOKENS_PATH = path.join(projectRoot, '.design/tokens/Bumba-Test.json');

// Test results tracking
const results = {
  passed: 0,
  failed: 0,
  errors: []
};

function test(name, fn) {
  try {
    const result = fn();
    if (result === true) {
      console.log(`  ✓ ${name}`);
      results.passed++;
    } else {
      console.log(`  ✗ ${name}`);
      console.log(`    Expected: true, Got: ${JSON.stringify(result)}`);
      results.failed++;
      results.errors.push({ test: name, result });
    }
  } catch (err) {
    console.log(`  ✗ ${name}`);
    console.log(`    Error: ${err.message}`);
    results.failed++;
    results.errors.push({ test: name, error: err.message });
  }
}

function testAsync(name, fn) {
  return fn().then(result => {
    if (result === true) {
      console.log(`  ✓ ${name}`);
      results.passed++;
    } else {
      console.log(`  ✗ ${name}`);
      console.log(`    Expected: true, Got: ${JSON.stringify(result)}`);
      results.failed++;
      results.errors.push({ test: name, result });
    }
  }).catch(err => {
    console.log(`  ✗ ${name}`);
    console.log(`    Error: ${err.message}`);
    results.failed++;
    results.errors.push({ test: name, error: err.message });
  });
}

async function runTests() {
  console.log('\n' + '='.repeat(60));
  console.log('PHASE 1 COMPREHENSIVE TEST SUITE');
  console.log('='.repeat(60) + '\n');

  // Load test data
  const buttonData = JSON.parse(fs.readFileSync(path.join(COMPONENTS_DIR, 'buttonprimary.json'), 'utf8'));
  const tokensData = JSON.parse(fs.readFileSync(TOKENS_PATH, 'utf8'));

  // Create generator instance
  const generator = new SmartCodeGenerator({});

  // =========================================================================
  // TEST 1: Style Extraction (Sprints 1-10)
  // =========================================================================
  console.log('1. STYLE EXTRACTION (Sprints 1-10)');
  console.log('-'.repeat(40));

  test('getStyleSourceNode returns first child for COMPONENT_SET', () => {
    const node = generator.getStyleSourceNode(buttonData);
    return node.name === 'Property 1=tertiary' && node.type === 'COMPONENT';
  });

  test('getStyleSourceNode returns self for COMPONENT', () => {
    const component = buttonData.children[0];
    const node = generator.getStyleSourceNode(component);
    return node.id === component.id;
  });

  test('extractLayoutStyles returns non-empty object', () => {
    const styles = generator.extractLayoutStyles(buttonData);
    return Object.keys(styles).length > 0;
  });

  test('extractLayoutStyles includes width', () => {
    const styles = generator.extractLayoutStyles(buttonData);
    return styles.width === '132px';
  });

  test('extractLayoutStyles includes height', () => {
    const styles = generator.extractLayoutStyles(buttonData);
    return styles.height === '48px';
  });

  test('extractLayoutStyles includes padding from tokenDependencies', () => {
    const styles = generator.extractLayoutStyles(buttonData);
    return styles.padding === '16px 40px 16px 40px';
  });

  test('extractLayoutStyles includes gap', () => {
    const styles = generator.extractLayoutStyles(buttonData);
    return styles.gap === '10px';
  });

  test('extractColorStyles returns backgroundColor', () => {
    const styles = generator.extractColorStyles(buttonData);
    return styles.backgroundColor && styles.backgroundColor.includes('rgb');
  });

  test('extractColorStyles returns text color', () => {
    const styles = generator.extractColorStyles(buttonData);
    return styles.color && styles.color.includes('rgba');
  });

  test('extractTypographyStyles returns fontFamily', () => {
    const styles = generator.extractTypographyStyles(buttonData);
    return styles.fontFamily && styles.fontFamily.includes('Apertura');
  });

  test('extractTypographyStyles returns fontSize', () => {
    const styles = generator.extractTypographyStyles(buttonData);
    return styles.fontSize === '16px';
  });

  test('extractTypographyStyles returns fontWeight', () => {
    const styles = generator.extractTypographyStyles(buttonData);
    return styles.fontWeight === 500;
  });

  test('extractEffectStyles returns borderRadius', () => {
    const styles = generator.extractEffectStyles(buttonData);
    return styles.borderRadius === '8px';
  });

  // =========================================================================
  // TEST 2: Token Integration (Sprints 11-12)
  // =========================================================================
  console.log('\n2. TOKEN INTEGRATION (Sprints 11-12)');
  console.log('-'.repeat(40));

  test('generateTokensFile returns object with filename and content', () => {
    const result = generator.generateTokensFile(tokensData.tokens, { typescript: true });
    return result.filename === 'tokens.ts' && typeof result.content === 'string';
  });

  test('generateTokensFile includes color tokens', () => {
    const result = generator.generateTokensFile(tokensData.tokens, { typescript: true });
    return result.content.includes("'primary': '#00aa00'");
  });

  test('generateTokensFile includes typography tokens', () => {
    const result = generator.generateTokensFile(tokensData.tokens, { typescript: true });
    return result.content.includes("'body':") && result.content.includes("fontFamily: 'Apertura'");
  });

  test('generateTokensFile includes spacing tokens', () => {
    const result = generator.generateTokensFile(tokensData.tokens, { typescript: true });
    return result.content.includes("export const spacing");
  });

  test('generateTokensFile includes borderRadius tokens', () => {
    const result = generator.generateTokensFile(tokensData.tokens, { typescript: true });
    return result.content.includes("'sm': '8px'");
  });

  test('generateTokensFile includes effects/shadows', () => {
    const result = generator.generateTokensFile(tokensData.tokens, { typescript: true });
    return result.content.includes("'shadow-sm':");
  });

  test('generateTokensFile includes CSS variables generator', () => {
    const result = generator.generateTokensFile(tokensData.tokens, { typescript: true });
    return result.content.includes('cssVariables') && result.content.includes('--color-');
  });

  test('generateTokensFile uses as const for TypeScript', () => {
    const result = generator.generateTokensFile(tokensData.tokens, { typescript: true });
    return result.content.includes('as const');
  });

  test('resolveTokenReferences returns structured object', () => {
    const resolved = generator.resolveTokenReferences(buttonData, tokensData.tokens);
    // Check that it returns an object with the expected structure
    return typeof resolved === 'object' &&
           resolved.hasOwnProperty('colors') &&
           resolved.hasOwnProperty('typography') &&
           resolved.hasOwnProperty('borderRadius');
  });

  // =========================================================================
  // TEST 3: Variant System (Sprints 13-22)
  // =========================================================================
  console.log('\n3. VARIANT SYSTEM (Sprints 13-22)');
  console.log('-'.repeat(40));

  await testAsync('extractVariants returns array with variant info', async () => {
    const variants = await generator.extractVariants(buttonData);
    return Array.isArray(variants) && variants.length > 0;
  });

  await testAsync('extractVariants parses Property 1=X format', async () => {
    const variants = await generator.extractVariants(buttonData);
    return variants[0].name === 'variant';
  });

  await testAsync('extractVariants includes all variant values', async () => {
    const variants = await generator.extractVariants(buttonData);
    const values = variants[0].values;
    return values.includes('primary') && values.includes('secondary') && values.includes('tertiary');
  });

  await testAsync('extractVariants sets defaultValue', async () => {
    const variants = await generator.extractVariants(buttonData);
    return variants[0].defaultValue === 'tertiary';
  });

  test('sanitizeVariantPropName converts "Property 1" to "variant"', () => {
    return generator.sanitizeVariantPropName('Property 1') === 'variant';
  });

  test('sanitizeVariantPropName converts "Property 2" to "variant"', () => {
    return generator.sanitizeVariantPropName('Property 2') === 'variant';
  });

  test('sanitizeVariantPropName preserves meaningful names', () => {
    return generator.sanitizeVariantPropName('Size') === 'size';
  });

  test('extractVariantStyles returns styles for each variant', () => {
    const variantStyles = generator.extractVariantStyles(buttonData);
    const keys = Object.keys(variantStyles);
    return keys.includes('primary') && keys.includes('secondary') && keys.includes('tertiary');
  });

  test('extractVariantStyles primary has green background', () => {
    const variantStyles = generator.extractVariantStyles(buttonData);
    return variantStyles.primary.colors.backgroundColor.includes('0, 170, 0');
  });

  test('extractVariantStyles secondary has orange background', () => {
    const variantStyles = generator.extractVariantStyles(buttonData);
    return variantStyles.secondary.colors.backgroundColor.includes('255, 170, 0');
  });

  test('extractVariantStyles tertiary has red background', () => {
    const variantStyles = generator.extractVariantStyles(buttonData);
    return variantStyles.tertiary.colors.backgroundColor.includes('221, 0, 0');
  });

  test('generateVariantStyleMap produces valid code', () => {
    const variantStyles = generator.extractVariantStyles(buttonData);
    const code = generator.generateVariantStyleMap(variantStyles);
    return code.includes('const variantStyles') && code.includes('as const');
  });

  // =========================================================================
  // TEST 4: Semantic HTML Detection (Sprints 23-34)
  // =========================================================================
  console.log('\n4. SEMANTIC HTML DETECTION (Sprints 23-34)');
  console.log('-'.repeat(40));

  test('detectComponentType identifies button', () => {
    return generator.detectComponentType({ name: 'primary-button' }) === 'button';
  });

  test('detectComponentType identifies btn shorthand', () => {
    return generator.detectComponentType({ name: 'submit-btn' }) === 'button';
  });

  test('detectComponentType identifies cta as button', () => {
    return generator.detectComponentType({ name: 'main-cta' }) === 'button';
  });

  test('detectComponentType identifies link', () => {
    return generator.detectComponentType({ name: 'nav-link' }) === 'link';
  });

  test('detectComponentType identifies input', () => {
    return generator.detectComponentType({ name: 'text-input' }) === 'input';
  });

  test('detectComponentType identifies textarea', () => {
    return generator.detectComponentType({ name: 'comment-textarea' }) === 'textarea';
  });

  test('detectComponentType identifies select', () => {
    return generator.detectComponentType({ name: 'country-select' }) === 'select';
  });

  test('detectComponentType identifies dropdown as select', () => {
    return generator.detectComponentType({ name: 'user-dropdown' }) === 'select';
  });

  test('detectComponentType identifies checkbox', () => {
    return generator.detectComponentType({ name: 'terms-checkbox' }) === 'checkbox';
  });

  test('detectComponentType identifies radio', () => {
    return generator.detectComponentType({ name: 'gender-radio' }) === 'radio';
  });

  test('detectComponentType identifies toggle', () => {
    return generator.detectComponentType({ name: 'dark-mode-toggle' }) === 'toggle';
  });

  test('detectComponentType identifies switch as toggle', () => {
    return generator.detectComponentType({ name: 'notification-switch' }) === 'toggle';
  });

  test('detectComponentType identifies modal', () => {
    return generator.detectComponentType({ name: 'confirm-modal' }) === 'modal';
  });

  test('detectComponentType identifies dialog as modal', () => {
    return generator.detectComponentType({ name: 'alert-dialog' }) === 'modal';
  });

  test('detectComponentType identifies navigation', () => {
    return generator.detectComponentType({ name: 'main-nav' }) === 'navigation';
  });

  test('detectComponentType identifies header', () => {
    return generator.detectComponentType({ name: 'page-header' }) === 'header';
  });

  test('detectComponentType identifies footer', () => {
    return generator.detectComponentType({ name: 'site-footer' }) === 'footer';
  });

  test('detectComponentType identifies section', () => {
    return generator.detectComponentType({ name: 'hero-section' }) === 'section';
  });

  test('detectComponentType identifies image', () => {
    return generator.detectComponentType({ name: 'user-avatar' }) === 'image';
  });

  test('detectComponentType identifies badge', () => {
    return generator.detectComponentType({ name: 'status-badge' }) === 'badge';
  });

  test('detectComponentType identifies alert', () => {
    return generator.detectComponentType({ name: 'error-alert' }) === 'alert';
  });

  test('detectComponentType identifies tabs', () => {
    return generator.detectComponentType({ name: 'settings-tabs' }) === 'tabs';
  });

  test('detectComponentType defaults to container', () => {
    return generator.detectComponentType({ name: 'wrapper' }) === 'container';
  });

  // Test JSX generators exist
  test('generateLinkJSX exists and returns JSX', () => {
    const jsx = generator.generateLinkJSX('test-link', {}, '');
    return jsx.includes('<a') && jsx.includes('href=');
  });

  test('generateTextareaJSX exists and returns JSX', () => {
    const jsx = generator.generateTextareaJSX('test-textarea', {}, '');
    return jsx.includes('<textarea') && jsx.includes('aria-describedby');
  });

  test('generateSelectJSX exists and returns JSX', () => {
    const jsx = generator.generateSelectJSX('test-select', {}, '');
    return jsx.includes('<select') && jsx.includes('options?.map');
  });

  test('generateCheckboxJSX exists and returns JSX', () => {
    const jsx = generator.generateCheckboxJSX('test-checkbox', {}, '');
    return jsx.includes('type="checkbox"') && jsx.includes('aria-checked');
  });

  test('generateToggleJSX exists and returns JSX', () => {
    const jsx = generator.generateToggleJSX('test-toggle', {}, '');
    return jsx.includes('role="switch"') && jsx.includes('aria-checked');
  });

  test('generateNavigationJSX uses semantic nav element', () => {
    const jsx = generator.generateNavigationJSX('test-nav', {}, '');
    return jsx.includes('<nav') && jsx.includes('aria-label');
  });

  test('generateHeaderJSX uses semantic header element', () => {
    const jsx = generator.generateHeaderJSX('test-header', {}, '');
    return jsx.includes('<header') && jsx.includes('<h1');
  });

  test('generateFooterJSX uses semantic footer element', () => {
    const jsx = generator.generateFooterJSX('test-footer', {}, '');
    return jsx.includes('<footer');
  });

  test('generateSectionJSX uses semantic section element', () => {
    const jsx = generator.generateSectionJSX('test-section', {}, '');
    return jsx.includes('<section') && jsx.includes('aria-label');
  });

  test('generateImageJSX includes alt and loading', () => {
    const jsx = generator.generateImageJSX('test-image', {}, '');
    return jsx.includes('<img') && jsx.includes('alt=') && jsx.includes('loading=');
  });

  test('generateAlertJSX includes role and aria-live', () => {
    const jsx = generator.generateAlertJSX('test-alert', {}, '');
    return jsx.includes('role="alert"') && jsx.includes('aria-live');
  });

  test('generateTabsJSX includes tablist and tab roles', () => {
    const jsx = generator.generateTabsJSX('test-tabs', {}, '');
    return jsx.includes('role="tablist"') && jsx.includes('role="tab"') && jsx.includes('aria-selected');
  });

  // =========================================================================
  // TEST 5: Interactive States (Sprints 35-50)
  // =========================================================================
  console.log('\n5. INTERACTIVE STATES (Sprints 35-50)');
  console.log('-'.repeat(40));

  test('extractInteractiveStates returns state object', () => {
    const states = generator.extractInteractiveStates(buttonData);
    return states.hasOwnProperty('hover') && states.hasOwnProperty('focus') &&
           states.hasOwnProperty('disabled') && states.hasOwnProperty('active');
  });

  test('generateDefaultInteractiveStyles generates hover state', () => {
    const css = generator.generateDefaultInteractiveStyles('btn', 'button');
    return css.includes(':hover:not(:disabled)') && css.includes('cursor: pointer');
  });

  test('generateDefaultInteractiveStyles generates focus-visible state', () => {
    const css = generator.generateDefaultInteractiveStyles('btn', 'button');
    return css.includes(':focus-visible') && css.includes('outline:');
  });

  test('generateDefaultInteractiveStyles generates active state', () => {
    const css = generator.generateDefaultInteractiveStyles('btn', 'button');
    return css.includes(':active:not(:disabled)');
  });

  test('generateDefaultInteractiveStyles generates disabled state', () => {
    const css = generator.generateDefaultInteractiveStyles('btn', 'button');
    return css.includes(':disabled') && css.includes('[aria-disabled="true"]');
  });

  test('generateDefaultInteractiveStyles skips non-interactive types', () => {
    const css = generator.generateDefaultInteractiveStyles('section', 'section');
    return css === '';
  });

  test('generateDefaultInteractiveStyles works for input type', () => {
    const css = generator.generateDefaultInteractiveStyles('input', 'input');
    return css.includes(':hover') && css.includes(':focus-visible');
  });

  test('generateDefaultInteractiveStyles works for link type', () => {
    const css = generator.generateDefaultInteractiveStyles('link', 'link');
    return css.includes(':hover') && css.includes('cursor: pointer');
  });

  // =========================================================================
  // TEST 6: End-to-End Generation
  // =========================================================================
  console.log('\n6. END-TO-END GENERATION');
  console.log('-'.repeat(40));

  await testAsync('generateCode produces complete component package', async () => {
    const pkg = await generator.generateCode(buttonData, {
      framework: 'react',
      componentFormat: 'functional',
      typescript: true,
      styleFormat: 'css',
      figmaData: tokensData
    });
    return pkg.id !== undefined &&
           pkg.name !== undefined &&
           typeof pkg.code === 'string' &&
           pkg.code.length > 0 &&
           typeof pkg.files === 'object';
  });

  await testAsync('generated code includes variant props interface', async () => {
    const pkg = await generator.generateCode(buttonData, {
      framework: 'react',
      componentFormat: 'functional',
      typescript: true,
      figmaData: tokensData
    });
    return pkg.code.includes("variant?: 'tertiary' | 'secondary' | 'primary'");
  });

  await testAsync('generated code includes variantStyles map', async () => {
    const pkg = await generator.generateCode(buttonData, {
      framework: 'react',
      componentFormat: 'functional',
      typescript: true,
      figmaData: tokensData
    });
    return pkg.code.includes('const variantStyles = {');
  });

  await testAsync('generated code uses semantic button element', async () => {
    const pkg = await generator.generateCode(buttonData, {
      framework: 'react',
      componentFormat: 'functional',
      typescript: true,
      figmaData: tokensData
    });
    return pkg.code.includes('<button');
  });

  await testAsync('generated code includes onClick and disabled props', async () => {
    const pkg = await generator.generateCode(buttonData, {
      framework: 'react',
      componentFormat: 'functional',
      typescript: true,
      figmaData: tokensData
    });
    return pkg.code.includes('onClick={onClick}') && pkg.code.includes('disabled={disabled}');
  });

  await testAsync('generated files include tokens.ts', async () => {
    const pkg = await generator.generateCode(buttonData, {
      framework: 'react',
      componentFormat: 'functional',
      typescript: true,
      figmaData: tokensData
    });
    return pkg.files.tokens && pkg.files.tokens.filename === 'tokens.ts';
  });

  await testAsync('generated files include CSS with interactive states', async () => {
    const pkg = await generator.generateCode(buttonData, {
      framework: 'react',
      componentFormat: 'functional',
      typescript: true,
      styleFormat: 'css',
      figmaData: tokensData
    });
    return pkg.files.styles &&
           pkg.files.styles.content.includes(':hover') &&
           pkg.files.styles.content.includes(':focus-visible') &&
           pkg.files.styles.content.includes(':disabled');
  });

  await testAsync('generated CSS includes variant modifier classes', async () => {
    const pkg = await generator.generateCode(buttonData, {
      framework: 'react',
      componentFormat: 'functional',
      typescript: true,
      styleFormat: 'css',
      figmaData: tokensData
    });
    return pkg.files.styles &&
           pkg.files.styles.content.includes('.button-primary--primary') &&
           pkg.files.styles.content.includes('.button-primary--secondary') &&
           pkg.files.styles.content.includes('.button-primary--tertiary');
  });

  await testAsync('_figma reference preserved in componentData', async () => {
    const pkg = await generator.generateCode(buttonData, {
      framework: 'react',
      componentFormat: 'functional',
      typescript: true,
      styleFormat: 'css',
      figmaData: tokensData
    });
    // The CSS should have variant styles, which requires _figma reference
    return pkg.files.styles && pkg.files.styles.content.includes('Variant styles');
  });

  // =========================================================================
  // SUMMARY
  // =========================================================================
  console.log('\n' + '='.repeat(60));
  console.log('TEST SUMMARY');
  console.log('='.repeat(60));
  console.log(`\n  Total:  ${results.passed + results.failed}`);
  console.log(`  Passed: ${results.passed} ✓`);
  console.log(`  Failed: ${results.failed} ✗`);
  console.log(`\n  Success Rate: ${((results.passed / (results.passed + results.failed)) * 100).toFixed(1)}%`);

  if (results.errors.length > 0) {
    console.log('\n' + '-'.repeat(40));
    console.log('FAILED TESTS:');
    results.errors.forEach((err, i) => {
      console.log(`\n  ${i + 1}. ${err.test}`);
      if (err.error) console.log(`     Error: ${err.error}`);
      if (err.result !== undefined) console.log(`     Result: ${JSON.stringify(err.result)}`);
    });
  }

  console.log('\n' + '='.repeat(60) + '\n');

  // Exit with appropriate code
  process.exit(results.failed > 0 ? 1 : 0);
}

// Run the tests
runTests().catch(err => {
  console.error('Test suite failed:', err);
  process.exit(1);
});
