/**
 * nlp-structure-generator.test.js
 * Unit tests for NLP structure generator
 */

const {
  generateStructure,
  analyzeDescription,
  inferLayout,
  buildStructure,
  groupElements,
  buildGroupStructure,
  elementToStructure,
  toPascalCase,
  elementPatterns
} = require('./nlp-structure-generator');

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
  console.log('\n=== NLP Structure Generator Tests ===\n');

  // Test: elementPatterns existence
  console.log('--- elementPatterns ---');
  test('has text patterns', typeof elementPatterns.text === 'object');
  test('has media patterns', typeof elementPatterns.media === 'object');
  test('has interactive patterns', typeof elementPatterns.interactive === 'object');
  test('has container patterns', typeof elementPatterns.container === 'object');
  test('text has heading pattern', elementPatterns.text.heading instanceof RegExp);
  test('text has body pattern', elementPatterns.text.body instanceof RegExp);
  test('media has image pattern', elementPatterns.media.image instanceof RegExp);
  test('interactive has button pattern', elementPatterns.interactive.button instanceof RegExp);
  test('container has list pattern', elementPatterns.container.list instanceof RegExp);

  // Test: toPascalCase
  console.log('\n--- toPascalCase ---');
  test('converts single word', toPascalCase('button') === 'Button');
  test('converts two words', toPascalCase('my button') === 'MyButton');
  test('handles dashes', toPascalCase('my-button') === 'MyButton');
  test('handles underscores', toPascalCase('my_button') === 'MyButton');
  test('handles mixed case', toPascalCase('My Button') === 'MyButton');
  test('handles multiple spaces', toPascalCase('my  button') === 'MyButton');
  test('handles empty string', toPascalCase('') === '');
  test('handles single char', toPascalCase('a') === 'A');

  // Test: analyzeDescription - text elements
  console.log('\n--- analyzeDescription (text) ---');
  const textDesc = 'A card with title and description';
  const textElements = analyzeDescription(textDesc);
  test('finds title element', textElements.some(e => e.type === 'heading'));
  test('finds description element', textElements.some(e => e.type === 'body'));
  test('elements have category', textElements.every(e => e.category));
  test('elements have name', textElements.every(e => e.name));
  test('elements have order', textElements.every(e => typeof e.order === 'number'));

  // Test: analyzeDescription - media elements
  console.log('\n--- analyzeDescription (media) ---');
  const mediaDesc = 'A card with header image and icon';
  const mediaElements = analyzeDescription(mediaDesc);
  test('finds image element', mediaElements.some(e => e.type === 'image'));
  test('finds icon element', mediaElements.some(e => e.type === 'icon'));
  test('media category correct', mediaElements.filter(e => e.category === 'media').length >= 2);

  // Test: analyzeDescription - interactive elements
  console.log('\n--- analyzeDescription (interactive) ---');
  const interactiveDesc = 'A form with input field and submit button';
  const interactiveElements = analyzeDescription(interactiveDesc);
  test('finds input element', interactiveElements.some(e => e.type === 'input'));
  test('finds button element', interactiveElements.some(e => e.type === 'button'));
  test('interactive category correct', interactiveElements.filter(e => e.category === 'interactive').length >= 2);

  // Test: analyzeDescription - container elements
  console.log('\n--- analyzeDescription (container) ---');
  const containerDesc = 'A component with list of items in a grid layout';
  const containerElements = analyzeDescription(containerDesc);
  test('finds list element', containerElements.some(e => e.type === 'list'));
  test('finds grid element', containerElements.some(e => e.type === 'grid'));

  // Test: analyzeDescription - complex
  console.log('\n--- analyzeDescription (complex) ---');
  const complexDesc = 'A product card with image, title, description, price label, and action buttons';
  const complexElements = analyzeDescription(complexDesc);
  test('finds multiple elements', complexElements.length >= 4);
  test('preserves order', complexElements[0].order <= complexElements[complexElements.length - 1].order);

  // Test: analyzeDescription - deduplication
  console.log('\n--- analyzeDescription (dedup) ---');
  const dedupDesc = 'A card with title and another title';
  const dedupElements = analyzeDescription(dedupDesc);
  const headingCount = dedupElements.filter(e => e.type === 'heading').length;
  test('deduplicates same element type', headingCount === 1);

  // Test: inferLayout - grid
  console.log('\n--- inferLayout ---');
  const gridElements = [{ type: 'grid', category: 'container' }];
  const gridLayout = inferLayout(gridElements);
  test('detects grid layout', gridLayout.type === 'grid');
  test('grid has columns', gridLayout.columns === 3);

  // Test: inferLayout - list
  const listElements = [{ type: 'list', category: 'container' }];
  const listLayout = inferLayout(listElements);
  test('detects list layout', listLayout.type === 'flex-col');
  test('list has gap', listLayout.gap === 8);

  // Test: inferLayout - multiple buttons
  const buttonElements = [
    { type: 'button', category: 'interactive' },
    { type: 'button', category: 'interactive' }
  ];
  const buttonLayout = inferLayout(buttonElements);
  test('detects action layout', buttonLayout.type === 'flex-row');
  test('action layout has flag', buttonLayout.actionLayout === true);

  // Test: inferLayout - image and text
  const mixedElements = [
    { type: 'image', category: 'media' },
    { type: 'heading', category: 'text' }
  ];
  const mixedLayout = inferLayout(mixedElements);
  test('detects mixed layout', mixedLayout.type === 'flex-col');
  test('mixed layout gap', mixedLayout.gap === 16);

  // Test: inferLayout - default
  const defaultElements = [{ type: 'heading', category: 'text' }];
  const defaultLayout = inferLayout(defaultElements);
  test('default layout type', defaultLayout.type === 'flex-col');
  test('default layout gap', defaultLayout.gap === 8);

  // Test: groupElements
  console.log('\n--- groupElements ---');
  const elementsToGroup = [
    { category: 'media', type: 'image', name: 'Image' },
    { category: 'text', type: 'heading', name: 'Title' },
    { category: 'text', type: 'body', name: 'Description' },
    { category: 'interactive', type: 'button', name: 'Action' }
  ];
  const groups = groupElements(elementsToGroup);
  test('creates groups', groups.length > 0);
  test('groups media separately', groups.some(g => g.type === 'media'));
  test('groups actions', groups.some(g => g.type === 'actions'));

  // Test: groupElements - container handling
  const containerGroupElements = [
    { category: 'text', type: 'heading', name: 'Title' },
    { category: 'container', type: 'list', name: 'List' },
    { category: 'text', type: 'body', name: 'Footer' }
  ];
  const containerGroups = groupElements(containerGroupElements);
  test('splits on container', containerGroups.length >= 2);

  // Test: buildGroupStructure - actions
  console.log('\n--- buildGroupStructure ---');
  const actionsGroup = {
    type: 'actions',
    elements: [
      { category: 'interactive', type: 'button', name: 'Submit' },
      { category: 'interactive', type: 'button', name: 'Cancel' }
    ]
  };
  const actionsStruct = buildGroupStructure(actionsGroup);
  test('actions has FRAME type', actionsStruct.type === 'FRAME');
  test('actions named Actions', actionsStruct.name === 'Actions');
  test('actions layout flex-row', actionsStruct.layout === 'flex-row');
  test('actions has children', actionsStruct.children.length === 2);

  // Test: buildGroupStructure - content
  const contentGroup = {
    type: 'content',
    elements: [
      { category: 'text', type: 'heading', name: 'Title' },
      { category: 'text', type: 'body', name: 'Description' }
    ]
  };
  const contentStruct = buildGroupStructure(contentGroup);
  test('content has FRAME type', contentStruct.type === 'FRAME');
  test('content named Content', contentStruct.name === 'Content');
  test('content layout flex-col', contentStruct.layout === 'flex-col');
  test('content has padding', contentStruct.padding === 16);

  // Test: buildGroupStructure - single element
  const singleGroup = {
    type: 'media',
    elements: [{ category: 'media', type: 'image', name: 'HeaderImage' }]
  };
  const singleStruct = buildGroupStructure(singleGroup);
  test('single returns element directly', singleStruct.type === 'IMAGE');

  // Test: buildGroupStructure - empty
  const emptyGroup = { type: 'content', elements: [] };
  const emptyStruct = buildGroupStructure(emptyGroup);
  test('empty returns null', emptyStruct === null);

  // Test: elementToStructure - text
  console.log('\n--- elementToStructure ---');
  const textElement = { category: 'text', type: 'heading', name: 'Title' };
  const textStruct = elementToStructure(textElement);
  test('text element type TEXT', textStruct.type === 'TEXT');
  test('text element has name', textStruct.name === 'Title');
  test('text element has style', textStruct.style === 'heading');

  // Test: elementToStructure - image
  const imageElement = { category: 'media', type: 'image', name: 'HeaderImage' };
  const imageStruct = elementToStructure(imageElement);
  test('image element type IMAGE', imageStruct.type === 'IMAGE');
  test('image has constraints', imageStruct.constraints !== undefined);
  test('image width fill', imageStruct.constraints.width === 'fill');

  // Test: elementToStructure - icon
  const iconElement = { category: 'media', type: 'icon', name: 'Icon' };
  const iconStruct = elementToStructure(iconElement);
  test('icon element type ICON', iconStruct.type === 'ICON');
  test('icon has size', iconStruct.size === 24);

  // Test: elementToStructure - button
  const buttonElement = { category: 'interactive', type: 'button', name: 'SubmitButton' };
  const buttonStruct = elementToStructure(buttonElement);
  test('button element type COMPONENT', buttonStruct.type === 'COMPONENT');
  test('button has componentRef', buttonStruct.componentRef === 'Button');

  // Test: elementToStructure - input
  const inputElement = { category: 'interactive', type: 'input', name: 'EmailInput' };
  const inputStruct = elementToStructure(inputElement);
  test('input element type COMPONENT', inputStruct.type === 'COMPONENT');
  test('input has componentRef', inputStruct.componentRef === 'Input');

  // Test: elementToStructure - checkbox
  const checkboxElement = { category: 'interactive', type: 'checkbox', name: 'AcceptTerms' };
  const checkboxStruct = elementToStructure(checkboxElement);
  test('checkbox type COMPONENT', checkboxStruct.type === 'COMPONENT');
  test('checkbox ref PascalCase', checkboxStruct.componentRef === 'Checkbox');

  // Test: elementToStructure - default
  const defaultElement = { category: 'unknown', type: 'custom', name: 'Custom' };
  const defaultStruct = elementToStructure(defaultElement);
  test('default element type FRAME', defaultStruct.type === 'FRAME');

  // Test: buildStructure
  console.log('\n--- buildStructure ---');
  const buildElements = [
    { category: 'media', type: 'image', name: 'Image' },
    { category: 'text', type: 'heading', name: 'Title' },
    { category: 'interactive', type: 'button', name: 'Action' }
  ];
  const buildLayout = { type: 'flex-col', gap: 16 };
  const builtStruct = buildStructure(buildElements, 'Card', buildLayout);
  test('buildStructure returns FRAME', builtStruct.type === 'FRAME');
  test('buildStructure has name', builtStruct.name === 'Card');
  test('buildStructure has layout', builtStruct.layout === 'flex-col');
  test('buildStructure has gap', builtStruct.gap === 16);
  test('buildStructure has children', Array.isArray(builtStruct.children));

  // Test: generateStructure - complete flow
  console.log('\n--- generateStructure (complete) ---');
  const cardDesc = 'A card with image, title, description, and action button';
  const cardStruct = generateStructure(cardDesc, 'ProductCard');
  test('generates FRAME root', cardStruct.type === 'FRAME');
  test('root named correctly', cardStruct.name === 'ProductCard');
  test('has layout', cardStruct.layout !== undefined);
  test('has children', cardStruct.children.length > 0);

  // Test: generateStructure - form
  const formDesc = 'A login form with email input, password field, and submit button';
  const formStruct = generateStructure(formDesc, 'LoginForm');
  test('form generates structure', formStruct.type === 'FRAME');
  test('form has children', formStruct.children.length > 0);

  // Test: generateStructure - navigation
  const navDesc = 'A navigation bar with logo, links, and action buttons';
  const navStruct = generateStructure(navDesc, 'NavBar');
  test('nav generates structure', navStruct.type === 'FRAME');
  test('nav named correctly', navStruct.name === 'NavBar');

  // Test: generateStructure - empty description
  const emptyDesc = '';
  const emptyGenStruct = generateStructure(emptyDesc, 'Empty');
  test('empty desc still returns FRAME', emptyGenStruct.type === 'FRAME');
  test('empty desc has name', emptyGenStruct.name === 'Empty');
  test('empty desc children empty', emptyGenStruct.children.length === 0);

  // Test: element name extraction
  console.log('\n--- Element Name Extraction ---');
  const heroDesc = 'A hero section with large hero image and main title';
  const heroElements = analyzeDescription(heroDesc);
  const heroImageEl = heroElements.find(e => e.type === 'image');
  test('extracts hero image name', heroImageEl && heroImageEl.name.toLowerCase().includes('hero'));

  // Test: pattern matching edge cases
  console.log('\n--- Pattern Edge Cases ---');
  const edgeDesc = 'Submit button, checkbox toggle, dropdown select';
  const edgeElements = analyzeDescription(edgeDesc);
  test('finds submit as button', edgeElements.some(e => e.type === 'button'));
  test('finds toggle as checkbox', edgeElements.some(e => e.type === 'checkbox'));
  test('finds select element', edgeElements.some(e => e.type === 'select'));

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
