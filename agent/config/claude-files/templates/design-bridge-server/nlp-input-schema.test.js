/**
 * nlp-input-schema.test.js
 * Unit tests for NLP input schema validation
 */

const {
  nlpInputSchema,
  validateInput,
  normalizeInput,
  inferCategory,
  parseDescriptionHints,
  formatValidationErrors,
  createExampleInput,
  categoryHints
} = require('./nlp-input-schema');

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
  console.log('\n=== NLP Input Schema Tests ===\n');

  // Test: nlpInputSchema structure
  console.log('--- nlpInputSchema ---');
  test('has required fields', Array.isArray(nlpInputSchema.required));
  test('requires name and description', nlpInputSchema.required.includes('name') && nlpInputSchema.required.includes('description'));
  test('has properties object', typeof nlpInputSchema.properties === 'object');
  test('has name property', !!nlpInputSchema.properties.name);
  test('has description property', !!nlpInputSchema.properties.description);
  test('has category enum', Array.isArray(nlpInputSchema.properties.category.enum));
  test('has framework enum', Array.isArray(nlpInputSchema.properties.framework.enum));

  // Test: validateInput - valid inputs
  console.log('\n--- validateInput (valid) ---');
  const validSimple = validateInput({
    name: 'Button',
    description: 'A primary button with hover effect'
  });
  test('valid simple input', validSimple.valid === true);
  test('no errors for valid input', validSimple.errors.length === 0);

  const validComplex = validateInput({
    name: 'ProductCard',
    description: 'A card with image, title, price, and action buttons',
    category: 'card',
    variants: ['default', 'featured'],
    sizes: ['sm', 'md', 'lg'],
    framework: 'react'
  });
  test('valid complex input', validComplex.valid === true);

  // Test: validateInput - invalid inputs
  console.log('\n--- validateInput (invalid) ---');
  const missingName = validateInput({
    description: 'A button component'
  });
  test('missing name invalid', missingName.valid === false);
  test('missing name error', missingName.errors.some(e => e.includes('name')));

  const missingDesc = validateInput({
    name: 'Button'
  });
  test('missing description invalid', missingDesc.valid === false);
  test('missing description error', missingDesc.errors.some(e => e.includes('description')));

  const invalidName = validateInput({
    name: 'button',
    description: 'A button component'
  });
  test('lowercase name invalid', invalidName.valid === false);
  test('name must be PascalCase', invalidName.errors.some(e => e.includes('PascalCase')));

  const shortDesc = validateInput({
    name: 'Button',
    description: 'Too short'
  });
  test('short description invalid', shortDesc.valid === false);
  test('description too short error', shortDesc.errors.some(e => e.includes('too short')));

  const invalidCategory = validateInput({
    name: 'Button',
    description: 'A button component',
    category: 'invalid-category'
  });
  test('invalid category rejected', invalidCategory.valid === false);
  test('invalid category error', invalidCategory.errors.some(e => e.includes('Invalid category')));

  const invalidFramework = validateInput({
    name: 'Button',
    description: 'A button component',
    framework: 'jquery'
  });
  test('invalid framework rejected', invalidFramework.valid === false);
  test('invalid framework error', invalidFramework.errors.some(e => e.includes('Invalid framework')));

  // Test: inferCategory
  console.log('\n--- inferCategory ---');
  test('infers button', inferCategory('Button', 'A clickable button') === 'button');
  test('infers card', inferCategory('Card', 'A display panel') === 'card');
  test('infers input', inferCategory('TextField', 'A text input field') === 'input');
  test('infers navigation', inferCategory('NavBar', 'Navigation menu') === 'navigation');
  test('infers layout', inferCategory('Container', 'A wrapper component') === 'layout');
  test('infers feedback', inferCategory('Toast', 'A notification alert') === 'feedback');
  test('infers overlay', inferCategory('Modal', 'A dialog popup') === 'overlay');
  test('infers data', inferCategory('Table', 'A data table') === 'data');
  test('infers form', inferCategory('FormField', 'A form with validation fields') === 'form');
  test('defaults to component', inferCategory('Custom', 'Some random thing') === 'component');

  // Test: inferCategory from description
  test('infers from description', inferCategory('Component', 'A button with click action') === 'button');
  test('infers modal from dialog', inferCategory('Popup', 'A modal dialog component') === 'overlay');

  // Test: normalizeInput
  console.log('\n--- normalizeInput ---');
  const normalized = normalizeInput({
    name: 'Button',
    description: 'A primary button'
  });
  test('preserves name', normalized.name === 'Button');
  test('preserves description', normalized.description === 'A primary button');
  test('infers category', normalized.category === 'button');
  test('defaults variants to empty', Array.isArray(normalized.variants) && normalized.variants.length === 0);
  test('defaults sizes to empty', Array.isArray(normalized.sizes) && normalized.sizes.length === 0);
  test('defaults states', normalized.states.includes('default'));
  test('defaults framework to react', normalized.framework === 'react');
  test('defaults refinement to null', normalized.refinement === null);

  const withOverrides = normalizeInput({
    name: 'Card',
    description: 'A card component',
    category: 'data',
    variants: ['primary'],
    framework: 'vue'
  });
  test('respects category override', withOverrides.category === 'data');
  test('respects variants override', withOverrides.variants[0] === 'primary');
  test('respects framework override', withOverrides.framework === 'vue');

  // Test: parseDescriptionHints
  console.log('\n--- parseDescriptionHints ---');
  const hints1 = parseDescriptionHints('A primary button with hover effect and loading spinner');
  test('extracts primary variant', hints1.variants.includes('primary'));
  test('extracts hover state', hints1.states.includes('hover'));
  test('extracts loading state', hints1.states.includes('loading'));

  const hints2 = parseDescriptionHints('A large card with image, title text, and action button');
  test('extracts large size', hints2.sizes.includes('lg'));
  test('extracts image element', hints2.elements.includes('image'));
  test('extracts text element', hints2.elements.includes('text'));
  test('extracts button element', hints2.elements.includes('button'));

  const hints3 = parseDescriptionHints('A small secondary outline button with disabled state');
  test('extracts secondary variant', hints3.variants.includes('secondary'));
  test('extracts outline variant', hints3.variants.includes('outline'));
  test('extracts small size', hints3.sizes.includes('sm'));
  test('extracts disabled state', hints3.states.includes('disabled'));

  const hints4 = parseDescriptionHints('A draggable card that can be dismissed');
  test('extracts draggable interaction', hints4.interactions.includes('draggable'));
  test('extracts dismissible interaction', hints4.interactions.includes('dismissible'));

  // Test: formatValidationErrors
  console.log('\n--- formatValidationErrors ---');
  const formatted = formatValidationErrors(['Error 1', 'Error 2']);
  test('formats errors as string', typeof formatted === 'string');
  test('includes header', formatted.includes('validation failed'));
  test('includes all errors', formatted.includes('Error 1') && formatted.includes('Error 2'));

  const emptyFormat = formatValidationErrors([]);
  test('empty array returns empty string', emptyFormat === '');

  // Test: createExampleInput
  console.log('\n--- createExampleInput ---');
  const buttonExample = createExampleInput('button');
  test('creates button example', buttonExample.name === 'Button');
  test('button has category', buttonExample.category === 'button');
  test('button has variants', Array.isArray(buttonExample.variants));
  test('button has sizes', Array.isArray(buttonExample.sizes));

  const cardExample = createExampleInput('card');
  test('creates card example', cardExample.name === 'Card');
  test('card has category', cardExample.category === 'card');

  const inputExample = createExampleInput('input');
  test('creates input example', inputExample.name === 'Input');

  const modalExample = createExampleInput('modal');
  test('creates modal example', modalExample.name === 'Modal');
  test('modal has overlay category', modalExample.category === 'overlay');

  const unknownExample = createExampleInput('unknown');
  test('defaults to button for unknown', unknownExample.name === 'Button');

  // Test: categoryHints
  console.log('\n--- categoryHints ---');
  test('has button hints', Array.isArray(categoryHints.button));
  test('button includes btn', categoryHints.button.includes('btn'));
  test('has card hints', Array.isArray(categoryHints.card));
  test('has input hints', Array.isArray(categoryHints.input));
  test('has overlay hints', Array.isArray(categoryHints.overlay));
  test('overlay includes modal', categoryHints.overlay.includes('modal'));

  // Edge cases
  console.log('\n--- Edge Cases ---');
  const emptyVariants = validateInput({
    name: 'Button',
    description: 'A button component',
    variants: []
  });
  test('empty variants array valid', emptyVariants.valid === true);

  const emptyColors = validateInput({
    name: 'Button',
    description: 'A button component',
    colors: {}
  });
  test('empty colors object valid', emptyColors.valid === true);

  const withRefinement = validateInput({
    name: 'Button',
    description: 'Update to add loading state',
    refinement: {
      previousId: 'nlp-button-123',
      feedback: 'Add loading spinner',
      keepFields: ['variants']
    }
  });
  test('refinement object valid', withRefinement.valid === true);

  const invalidRefinement = validateInput({
    name: 'Button',
    description: 'A button component',
    refinement: 'not-an-object'
  });
  test('invalid refinement rejected', invalidRefinement.valid === false);

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
