/**
 * nlp-prompts.test.js
 * Unit tests for NLP prompt templates and compilation
 */

const {
  componentGenerationPrompt,
  structurePrompt,
  tokenInferencePrompt,
  variantPrompt,
  propsPrompt,
  accessibilityPrompt,
  compilePrompt,
  toKebabCase,
  getAllPrompts,
  createGenerationContext
} = require('./nlp-prompts');

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
  console.log('\n=== NLP Prompts Tests ===\n');

  // Test: Prompt templates exist
  console.log('--- Prompt Templates ---');
  test('componentGenerationPrompt exists', typeof componentGenerationPrompt === 'string');
  test('componentGenerationPrompt has name placeholder', componentGenerationPrompt.includes('{{name}}'));
  test('componentGenerationPrompt has description placeholder', componentGenerationPrompt.includes('{{description}}'));
  test('componentGenerationPrompt has category placeholder', componentGenerationPrompt.includes('{{category}}'));
  test('componentGenerationPrompt has conditional variants', componentGenerationPrompt.includes('{{#if variants}}'));
  test('componentGenerationPrompt has JSON structure example', componentGenerationPrompt.includes('"source"'));

  test('structurePrompt exists', typeof structurePrompt === 'string');
  test('structurePrompt has description placeholder', structurePrompt.includes('{{description}}'));
  test('structurePrompt mentions FRAME type', structurePrompt.includes('FRAME'));
  test('structurePrompt mentions TEXT type', structurePrompt.includes('TEXT'));
  test('structurePrompt mentions IMAGE type', structurePrompt.includes('IMAGE'));

  test('tokenInferencePrompt exists', typeof tokenInferencePrompt === 'string');
  test('tokenInferencePrompt has description placeholder', tokenInferencePrompt.includes('{{description}}'));
  test('tokenInferencePrompt mentions colors', tokenInferencePrompt.includes('colors'));
  test('tokenInferencePrompt mentions typography', tokenInferencePrompt.includes('typography'));
  test('tokenInferencePrompt mentions spacing', tokenInferencePrompt.includes('spacing'));

  test('variantPrompt exists', typeof variantPrompt === 'string');
  test('variantPrompt has name placeholder', variantPrompt.includes('{{name}}'));
  test('variantPrompt has variants placeholder', variantPrompt.includes('{{variants}}'));
  test('variantPrompt mentions tokenOverrides', variantPrompt.includes('tokenOverrides'));

  test('propsPrompt exists', typeof propsPrompt === 'string');
  test('propsPrompt has name placeholder', propsPrompt.includes('{{name}}'));
  test('propsPrompt mentions TypeScript types', propsPrompt.includes('TypeScript'));
  test('propsPrompt has props example', propsPrompt.includes('"props"'));

  test('accessibilityPrompt exists', typeof accessibilityPrompt === 'string');
  test('accessibilityPrompt has name placeholder', accessibilityPrompt.includes('{{name}}'));
  test('accessibilityPrompt mentions ARIA', accessibilityPrompt.includes('ARIA'));
  test('accessibilityPrompt mentions keyboard', accessibilityPrompt.includes('keyboard'));

  // Test: toKebabCase
  console.log('\n--- toKebabCase ---');
  test('converts PascalCase', toKebabCase('MyButton') === 'my-button');
  test('converts camelCase', toKebabCase('myButton') === 'my-button');
  test('handles spaces', toKebabCase('My Button') === 'my-button');
  test('handles multiple words', toKebabCase('MyNavBarItem') === 'my-nav-bar-item');
  test('already lowercase', toKebabCase('button') === 'button');
  test('handles empty string', toKebabCase('') === '');
  test('handles single char', toKebabCase('A') === 'a');
  test('handles mixed case with numbers', toKebabCase('Button2Icon') === 'button2-icon');

  // Test: compilePrompt - simple replacements
  console.log('\n--- compilePrompt (simple) ---');
  const simpleTemplate = 'Component: {{name}}, Description: {{description}}';
  const simpleContext = { name: 'Button', description: 'A clickable button' };
  const simpleResult = compilePrompt(simpleTemplate, simpleContext);
  test('replaces name', simpleResult.includes('Button'));
  test('replaces description', simpleResult.includes('A clickable button'));
  test('no leftover placeholders', !simpleResult.includes('{{'));

  // Test: compilePrompt - missing values
  console.log('\n--- compilePrompt (missing values) ---');
  const missingTemplate = 'Name: {{name}}, Category: {{category}}';
  const missingContext = { name: 'Card' };
  const missingResult = compilePrompt(missingTemplate, missingContext);
  test('replaces available value', missingResult.includes('Card'));
  test('missing value becomes empty', missingResult.includes('Category: '));

  // Test: compilePrompt - conditionals
  console.log('\n--- compilePrompt (conditionals) ---');
  const conditionalTemplate = 'Name: {{name}}{{#if variants}} Variants: {{variants}}{{/if}}';

  const withVariants = compilePrompt(conditionalTemplate, {
    name: 'Button',
    variants: ['primary', 'secondary']
  });
  test('includes conditional when present', withVariants.includes('Variants:'));
  test('array joined with comma', withVariants.includes('primary, secondary'));

  const withoutVariants = compilePrompt(conditionalTemplate, {
    name: 'Button',
    variants: []
  });
  test('excludes conditional when empty array', !withoutVariants.includes('Variants:'));

  const withNullVariants = compilePrompt(conditionalTemplate, {
    name: 'Button',
    variants: null
  });
  test('excludes conditional when null', !withNullVariants.includes('Variants:'));

  // Test: compilePrompt - kebabCase helper
  console.log('\n--- compilePrompt (kebabCase helper) ---');
  const kebabTemplate = 'ID: {{kebabCase name}}';
  const kebabResult = compilePrompt(kebabTemplate, { name: 'MyNavBar' });
  test('applies kebabCase helper', kebabResult.includes('my-nav-bar'));

  // Test: compilePrompt - timestamp helpers
  console.log('\n--- compilePrompt (timestamp helpers) ---');
  const timestampTemplate = 'Time: {{timestamp}}, ISO: {{isoTimestamp}}';
  const timestampResult = compilePrompt(timestampTemplate, {});
  test('replaces timestamp', /Time: \d+/.test(timestampResult));
  test('replaces isoTimestamp', /ISO: \d{4}-\d{2}-\d{2}T/.test(timestampResult));

  // Test: compilePrompt - complex example
  console.log('\n--- compilePrompt (complex) ---');
  const complexResult = compilePrompt(componentGenerationPrompt, {
    name: 'Button',
    description: 'A primary button with hover effect',
    category: 'button',
    framework: 'react',
    variants: ['primary', 'secondary'],
    sizes: ['sm', 'md', 'lg'],
    states: []
  });
  test('complex: includes component name', complexResult.includes('Button'));
  test('complex: includes description', complexResult.includes('primary button'));
  test('complex: includes category', complexResult.includes('button'));
  test('complex: includes framework', complexResult.includes('react'));
  test('complex: includes variants', complexResult.includes('primary, secondary'));
  test('complex: includes sizes', complexResult.includes('sm, md, lg'));
  test('complex: excludes empty states conditional', !complexResult.includes('Requested States:'));

  // Test: getAllPrompts
  console.log('\n--- getAllPrompts ---');
  const allPrompts = getAllPrompts();
  test('returns object', typeof allPrompts === 'object');
  test('has componentGeneration', typeof allPrompts.componentGeneration === 'string');
  test('has structure', typeof allPrompts.structure === 'string');
  test('has tokenInference', typeof allPrompts.tokenInference === 'string');
  test('has variant', typeof allPrompts.variant === 'string');
  test('has props', typeof allPrompts.props === 'string');
  test('has accessibility', typeof allPrompts.accessibility === 'string');

  // Test: createGenerationContext
  console.log('\n--- createGenerationContext ---');
  const input = {
    name: 'Card',
    description: 'A card component',
    category: 'card',
    framework: 'vue',
    variants: ['default', 'outlined'],
    sizes: ['sm', 'lg']
  };
  const context = createGenerationContext(input);
  test('context has name', context.name === 'Card');
  test('context has description', context.description === 'A card component');
  test('context has category', context.category === 'card');
  test('context has framework', context.framework === 'vue');
  test('context has variants', Array.isArray(context.variants) && context.variants.length === 2);
  test('context has sizes', Array.isArray(context.sizes) && context.sizes.length === 2);
  test('context has states (empty default)', Array.isArray(context.states));

  const minimalInput = { name: 'Button', description: 'A button', category: 'button' };
  const minimalContext = createGenerationContext(minimalInput);
  test('minimal: defaults framework to react', minimalContext.framework === 'react');
  test('minimal: defaults variants to empty array', Array.isArray(minimalContext.variants));
  test('minimal: defaults sizes to empty array', Array.isArray(minimalContext.sizes));
  test('minimal: defaults states to empty array', Array.isArray(minimalContext.states));

  // Test: Prompt output structure hints
  console.log('\n--- Prompt Output Structure ---');
  test('componentGenerationPrompt mentions source.type', componentGenerationPrompt.includes('"type": "nlp-prompt"'));
  test('componentGenerationPrompt mentions tokenDependencies', componentGenerationPrompt.includes('tokenDependencies'));
  test('componentGenerationPrompt mentions interactiveStates', componentGenerationPrompt.includes('interactiveStates'));
  test('structurePrompt mentions layout options', structurePrompt.includes('flex-row') && structurePrompt.includes('flex-col'));
  test('variantPrompt mentions properties key', variantPrompt.includes('"properties"'));
  test('propsPrompt mentions required field', propsPrompt.includes('"required"'));
  test('accessibilityPrompt mentions focusManagement', accessibilityPrompt.includes('focusManagement'));

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
