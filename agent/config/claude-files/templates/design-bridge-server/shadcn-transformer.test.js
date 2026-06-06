/**
 * shadcn-transformer.test.js
 * Unit tests for ShadCN to Design Bridge transformation
 */

const {
  transformShadcnComponent,
  transformMultipleComponents,
  parseComponentSource,
  mergeExamples,
  inferCategory,
  sanitizeFileName,
  pascalCase,
  formatComponentSummary
} = require('./shadcn-transformer');

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

// Mock component data
const mockButtonData = {
  componentName: 'button',
  registryName: '@shadcn',
  sourceCode: `
import { cva, type VariantProps } from "class-variance-authority"

const buttonVariants = cva("inline-flex items-center", {
  variants: {
    variant: { default: "bg-primary", destructive: "bg-destructive" },
    size: { default: "h-9", sm: "h-8", lg: "h-10" }
  }
})

export function Button({ className, variant, size, ...props }) {
  return <button className={buttonVariants({ variant, size, className })} {...props} />
}
`,
  examples: [
    { name: 'button-demo', code: '<Button>Click me</Button>', description: 'Default button' }
  ],
  dependencies: ['@radix-ui/react-slot', 'class-variance-authority']
};

const mockDialogData = {
  componentName: 'dialog',
  registryName: '@shadcn',
  sourceCode: `export function Dialog({ children }) { return <div>{children}</div> }`,
  examples: [],
  dependencies: ['@radix-ui/react-dialog']
};

function runTests() {
  console.log('\n=== ShadCN Transformer Tests ===\n');

  // Test: transformShadcnComponent - basic transform
  console.log('--- transformShadcnComponent ---');
  const button = transformShadcnComponent(mockButtonData);

  test('transforms component name', button.name === 'button');
  test('sets type to COMPONENT', button.type === 'COMPONENT');
  test('infers category as button', button.category === 'button');
  test('includes source info', button.source.type === 'shadcn');
  test('includes registry name', button.source.registry === '@shadcn');
  test('has extractedAt timestamp', !!button.source.extractedAt);
  test('includes dependencies', Array.isArray(button.dependencies) && button.dependencies.length === 2);
  test('includes examples', Array.isArray(button.examples) && button.examples.length === 1);
  test('has paths object', !!button.paths);
  test('has metadata with version', button.metadata.version === 1);

  // Test: paths generation
  console.log('\n--- Paths Generation ---');
  test('rawSource path correct', button.paths.rawSource === '.design/source/components/button.json');
  test('codeOutput path correct', button.paths.codeOutput === 'src/components/Button.tsx');
  test('storyOutput path correct', button.paths.storyOutput === 'src/components/Button.stories.tsx');

  // Test: dialog component
  console.log('\n--- Dialog Component ---');
  const dialog = transformShadcnComponent(mockDialogData);

  test('dialog category is modal', dialog.category === 'modal');
  test('dialog has correct name', dialog.name === 'dialog');
  test('dialog has one dependency', dialog.dependencies.length === 1);

  // Test: parseComponentSource
  console.log('\n--- parseComponentSource ---');
  const parsed = parseComponentSource(mockButtonData.sourceCode);

  test('detects CVA usage', parsed.hasCva === true);
  test('extracts exports', parsed.exports.includes('Button'));

  const noCvaParsed = parseComponentSource(mockDialogData.sourceCode);
  test('handles no CVA', noCvaParsed.hasCva === false);

  const nullParsed = parseComponentSource(null);
  test('handles null source', nullParsed.hasCva === false);

  // Test: inferCategory
  console.log('\n--- inferCategory ---');
  test('button -> button', inferCategory('button') === 'button');
  test('Button -> button', inferCategory('Button') === 'button');
  test('dialog -> modal', inferCategory('dialog') === 'modal');
  test('alert-dialog -> modal', inferCategory('alert-dialog') === 'modal');
  test('sheet -> modal', inferCategory('sheet') === 'modal');
  test('drawer -> modal', inferCategory('drawer') === 'modal');
  test('input -> input', inferCategory('input') === 'input');
  test('textarea -> input', inferCategory('textarea') === 'input');
  test('select -> input', inferCategory('select') === 'input');
  test('checkbox -> input', inferCategory('checkbox') === 'input');
  test('switch -> input', inferCategory('switch') === 'input');
  test('slider -> input', inferCategory('slider') === 'input');
  test('card -> card', inferCategory('card') === 'card');
  test('tabs -> navigation', inferCategory('tabs') === 'navigation');
  test('breadcrumb -> navigation', inferCategory('breadcrumb') === 'navigation');
  test('dropdown-menu -> navigation', inferCategory('dropdown-menu') === 'navigation');
  test('accordion -> layout', inferCategory('accordion') === 'layout');
  test('collapsible -> layout', inferCategory('collapsible') === 'layout');
  test('toast -> feedback', inferCategory('toast') === 'feedback');
  test('alert -> feedback', inferCategory('alert') === 'feedback');
  test('progress -> feedback', inferCategory('progress') === 'feedback');
  test('skeleton -> feedback', inferCategory('skeleton') === 'feedback');
  test('popover -> overlay', inferCategory('popover') === 'overlay');
  test('tooltip -> overlay', inferCategory('tooltip') === 'overlay');
  test('table -> data', inferCategory('table') === 'data');
  test('calendar -> data', inferCategory('calendar') === 'data');
  test('avatar -> display', inferCategory('avatar') === 'display');
  test('badge -> display', inferCategory('badge') === 'display');
  test('carousel -> display', inferCategory('carousel') === 'display');
  test('form -> form', inferCategory('form') === 'form');
  test('label -> form', inferCategory('label') === 'form');
  test('unknown -> component', inferCategory('unknown-component') === 'component');

  // Test: sanitizeFileName
  console.log('\n--- sanitizeFileName ---');
  test('lowercase conversion', sanitizeFileName('Button') === 'button');
  test('replaces spaces with hyphens', sanitizeFileName('Button Group') === 'button-group');
  test('removes special chars', sanitizeFileName('button@test!') === 'buttontest');
  test('removes multiple hyphens', sanitizeFileName('button--test') === 'button-test');

  // Test: pascalCase
  console.log('\n--- pascalCase ---');
  test('button -> Button', pascalCase('button') === 'Button');
  test('button-group -> ButtonGroup', pascalCase('button-group') === 'ButtonGroup');
  test('alert_dialog -> AlertDialog', pascalCase('alert_dialog') === 'AlertDialog');
  test('date picker -> DatePicker', pascalCase('date picker') === 'DatePicker');

  // Test: transformMultipleComponents
  console.log('\n--- transformMultipleComponents ---');
  const multiple = transformMultipleComponents([mockButtonData, mockDialogData]);

  test('transforms multiple components', multiple.length === 2);
  test('first is button', multiple[0].name === 'button');
  test('second is dialog', multiple[1].name === 'dialog');

  // Test: mergeExamples
  console.log('\n--- mergeExamples ---');
  const baseComponent = transformShadcnComponent({
    componentName: 'test',
    registryName: '@shadcn',
    sourceCode: '',
    examples: [],
    dependencies: []
  });

  const extraExamples = [
    { name: 'example1', code: '<Test />', description: 'Example 1' },
    { name: 'example2', code: '<Test variant="alt" />' }
  ];

  const merged = mergeExamples(baseComponent, extraExamples);
  test('merges examples into component', merged.examples.length === 2);
  test('example has name', merged.examples[0].name === 'example1');
  test('example has code', merged.examples[0].code === '<Test />');
  test('example has description', merged.examples[0].description === 'Example 1');
  test('missing description defaults to empty', merged.examples[1].description === '');

  const noMerge = mergeExamples(baseComponent, null);
  test('handles null examples', noMerge.examples.length === 0);

  const emptyMerge = mergeExamples(baseComponent, []);
  test('handles empty examples array', emptyMerge.examples.length === 0);

  // Test: formatComponentSummary
  console.log('\n--- formatComponentSummary ---');
  const summary = formatComponentSummary(button);

  test('formats summary string', typeof summary === 'string');
  test('summary includes component name', summary.includes('Component: button'));
  test('summary includes category', summary.includes('Category: button'));
  test('summary includes source type', summary.includes('shadcn'));
  test('summary includes registry', summary.includes('@shadcn'));

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
