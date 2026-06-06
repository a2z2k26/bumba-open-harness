/**
 * nlp-props-inference.test.js
 * Unit tests for NLP props inference
 */

const {
  inferProps,
  generatePropDefinition,
  generateTypeScriptInterface,
  generateJSDoc,
  validateProps,
  getPropNames,
  hasChildrenProp,
  getRequiredProps,
  getOptionalProps,
  categoryPropTemplates,
  propPatterns
} = require('./nlp-props-inference');

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
  console.log('\n=== NLP Props Inference Tests ===\n');

  // Test: Constants exist
  console.log('--- Constants ---');
  test('propPatterns exists', typeof propPatterns === 'object');
  test('has onClick pattern', propPatterns.onClick instanceof RegExp);
  test('has onChange pattern', propPatterns.onChange instanceof RegExp);
  test('has disabled pattern', propPatterns.disabled instanceof RegExp);
  test('has loading pattern', propPatterns.loading instanceof RegExp);
  test('has icon pattern', propPatterns.icon instanceof RegExp);

  test('categoryPropTemplates exists', typeof categoryPropTemplates === 'object');
  test('has button template', Array.isArray(categoryPropTemplates.button));
  test('has input template', Array.isArray(categoryPropTemplates.input));
  test('has card template', Array.isArray(categoryPropTemplates.card));
  test('has navigation template', Array.isArray(categoryPropTemplates.navigation));
  test('has overlay template', Array.isArray(categoryPropTemplates.overlay));
  test('has feedback template', Array.isArray(categoryPropTemplates.feedback));

  // Test: inferProps - category defaults
  console.log('\n--- inferProps - Category Defaults ---');

  const buttonProps = inferProps('a simple button', 'button');
  test('button has children prop', buttonProps.some(p => p.name === 'children'));
  test('button has onClick prop', buttonProps.some(p => p.name === 'onClick'));
  test('button has disabled prop', buttonProps.some(p => p.name === 'disabled'));
  test('button has type prop', buttonProps.some(p => p.name === 'type'));
  test('button has className prop', buttonProps.some(p => p.name === 'className'));

  const inputProps = inferProps('a text field', 'input');
  test('input has value prop', inputProps.some(p => p.name === 'value'));
  test('input has onChange prop', inputProps.some(p => p.name === 'onChange'));
  test('input has placeholder prop', inputProps.some(p => p.name === 'placeholder'));
  test('input has type prop', inputProps.some(p => p.name === 'type'));

  const cardProps = inferProps('a content card', 'card');
  test('card has children prop', cardProps.some(p => p.name === 'children'));
  test('card has onClick prop', cardProps.some(p => p.name === 'onClick'));

  const overlayProps = inferProps('a modal dialog', 'overlay');
  test('overlay has open prop', overlayProps.some(p => p.name === 'open'));
  test('overlay has onClose prop', overlayProps.some(p => p.name === 'onClose'));
  test('overlay open is required', overlayProps.find(p => p.name === 'open')?.required === true);

  const feedbackProps = inferProps('an alert message', 'feedback');
  test('feedback has message prop', feedbackProps.some(p => p.name === 'message'));
  test('feedback has type prop', feedbackProps.some(p => p.name === 'type'));
  test('feedback message is required', feedbackProps.find(p => p.name === 'message')?.required === true);

  // Test: inferProps - description patterns
  console.log('\n--- inferProps - Description Patterns ---');

  const iconButtonProps = inferProps('a button with an icon', 'button');
  test('infers icon from "icon"', iconButtonProps.some(p => p.name === 'icon'));

  const loadingButtonProps = inferProps('a button with loading state', 'button');
  test('infers loading from "loading"', loadingButtonProps.some(p => p.name === 'loading'));

  const linkProps = inferProps('a card with a link', 'card');
  test('infers href from "link"', linkProps.some(p => p.name === 'href'));

  const imageCardProps = inferProps('a card with an image', 'card');
  test('infers image from "image"', imageCardProps.some(p => p.name === 'image'));

  const titleDescProps = inferProps('a card with title and description', 'card');
  test('infers title from "title"', titleDescProps.some(p => p.name === 'title'));
  test('infers description from "description"', titleDescProps.some(p => p.name === 'description'));

  const validationProps = inferProps('an input with validation error', 'input');
  test('infers error from "error"', validationProps.some(p => p.name === 'error'));

  const requiredInputProps = inferProps('a required input field', 'input');
  test('infers required from "required"', requiredInputProps.some(p => p.name === 'required'));

  // Test: inferProps - variant props
  console.log('\n--- inferProps - Variant Props ---');

  const variantProps = inferProps('a button', 'button', {
    variant: { primary: {}, secondary: {}, ghost: {} }
  });
  test('adds variant prop from variants', variantProps.some(p => p.name === 'variant'));
  const variantProp = variantProps.find(p => p.name === 'variant');
  test('variant type includes options', variantProp?.type.includes("'primary'"));
  test('variant has default', variantProp?.default !== undefined);

  const sizeProps = inferProps('a button', 'button', {
    size: { sm: {}, md: {}, lg: {} }
  });
  test('adds size prop from variants', sizeProps.some(p => p.name === 'size'));
  const sizeProp = sizeProps.find(p => p.name === 'size');
  test('size type includes options', sizeProp?.type.includes("'md'"));
  test('size defaults to md', sizeProp?.default === "'md'");

  const sizePropsNoMd = inferProps('a button', 'button', {
    size: { sm: {}, lg: {} }
  });
  const sizeNoProp = sizePropsNoMd.find(p => p.name === 'size');
  test('size defaults to first if no md', sizeNoProp?.default === "'sm'");

  // Test: generatePropDefinition
  console.log('\n--- generatePropDefinition ---');

  const onClickDef = generatePropDefinition('onClick');
  test('onClick has name', onClickDef?.name === 'onClick');
  test('onClick has type', onClickDef?.type === '() => void');
  test('onClick has description', onClickDef?.description !== undefined);

  const disabledDef = generatePropDefinition('disabled');
  test('disabled has boolean type', disabledDef?.type === 'boolean');
  test('disabled has default', disabledDef?.default === 'false');

  const loadingDef = generatePropDefinition('loading');
  test('loading has boolean type', loadingDef?.type === 'boolean');

  const errorDef = generatePropDefinition('error');
  test('error has union type', errorDef?.type === 'string | boolean');

  const imageDef = generatePropDefinition('image');
  test('image has object type option', imageDef?.type.includes('{ src: string'));

  const unknownDef = generatePropDefinition('unknownProp');
  test('unknown prop returns undefined', unknownDef === undefined);

  // Test: generateTypeScriptInterface
  console.log('\n--- generateTypeScriptInterface ---');

  const tsInterface = generateTypeScriptInterface('Button', [
    { name: 'children', type: 'React.ReactNode', required: true, description: 'Button content' },
    { name: 'onClick', type: '() => void', required: false, description: 'Click handler' },
    { name: 'disabled', type: 'boolean', required: false, description: 'Disabled state' }
  ]);
  test('starts with interface declaration', tsInterface.startsWith('export interface ButtonProps {'));
  test('ends with closing brace', tsInterface.endsWith('}'));
  test('includes required prop without ?', tsInterface.includes('children: React.ReactNode;'));
  test('includes optional prop with ?', tsInterface.includes('onClick?: () => void;'));
  test('includes JSDoc comments', tsInterface.includes('/** Button content */'));

  // Test: generateJSDoc
  console.log('\n--- generateJSDoc ---');

  const jsDoc = generateJSDoc([
    { name: 'children', type: 'React.ReactNode', required: true, description: 'Button content' },
    { name: 'disabled', type: 'boolean', required: false, default: 'false', description: 'Disabled state' }
  ]);
  test('starts with /**', jsDoc.startsWith('/**'));
  test('ends with */', jsDoc.endsWith(' */'));
  test('includes @param for children', jsDoc.includes('@param {React.ReactNode} children'));
  test('includes (required) tag', jsDoc.includes('(required)'));
  test('includes default value', jsDoc.includes('default: false'));

  // Test: validateProps
  console.log('\n--- validateProps ---');

  const validPropsResult = validateProps([
    { name: 'children', type: 'React.ReactNode' },
    { name: 'onClick', type: '() => void' }
  ]);
  test('valid props return valid: true', validPropsResult.valid === true);
  test('valid props have no errors', validPropsResult.errors.length === 0);

  const missingNameResult = validateProps([
    { type: 'React.ReactNode' }
  ]);
  test('missing name returns valid: false', missingNameResult.valid === false);
  test('missing name reports error', missingNameResult.errors.length > 0);
  test('error mentions missing name', missingNameResult.errors[0].includes('missing name'));

  const missingTypeResult = validateProps([
    { name: 'children' }
  ]);
  test('missing type returns valid: false', missingTypeResult.valid === false);
  test('missing type reports error', missingTypeResult.errors.length > 0);
  test('error mentions missing type', missingTypeResult.errors[0].includes('missing type'));

  // Test: helper functions
  console.log('\n--- Helper Functions ---');

  const testProps = [
    { name: 'children', type: 'React.ReactNode', required: true },
    { name: 'onClick', type: '() => void', required: false },
    { name: 'disabled', type: 'boolean', required: false }
  ];

  const propNames = getPropNames(testProps);
  test('getPropNames returns array', Array.isArray(propNames));
  test('getPropNames contains children', propNames.includes('children'));
  test('getPropNames contains onClick', propNames.includes('onClick'));
  test('getPropNames has correct length', propNames.length === 3);

  const hasChildren = hasChildrenProp(testProps);
  test('hasChildrenProp returns true when present', hasChildren === true);

  const noChildrenProps = [{ name: 'onClick', type: '() => void' }];
  const noChildren = hasChildrenProp(noChildrenProps);
  test('hasChildrenProp returns false when absent', noChildren === false);

  const requiredProps = getRequiredProps(testProps);
  test('getRequiredProps returns only required', requiredProps.length === 1);
  test('getRequiredProps includes children', requiredProps[0].name === 'children');

  const optionalProps = getOptionalProps(testProps);
  test('getOptionalProps returns only optional', optionalProps.length === 2);
  test('getOptionalProps excludes children', !optionalProps.some(p => p.name === 'children'));

  // Test: deduplication
  console.log('\n--- Deduplication ---');

  const dupButtonProps = inferProps('a clickable button with click handler', 'button');
  const onClickCount = dupButtonProps.filter(p => p.name === 'onClick').length;
  test('deduplicates onClick prop', onClickCount === 1);

  const dupDisabledProps = inferProps('a disabled button that is inactive', 'button');
  const disabledCount = dupDisabledProps.filter(p => p.name === 'disabled').length;
  test('deduplicates disabled prop', disabledCount === 1);

  // Test: unknown category
  console.log('\n--- Unknown Category ---');

  const unknownCategoryProps = inferProps('a custom component', 'customUnknown');
  test('unknown category falls back to button template', unknownCategoryProps.some(p => p.name === 'children'));
  test('unknown category has className', unknownCategoryProps.some(p => p.name === 'className'));

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
