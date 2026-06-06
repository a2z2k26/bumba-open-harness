/**
 * shadcn-example-handler.test.js
 * Unit tests for ShadCN example parsing and story generation
 */

const {
  parseExamplesFromMcp,
  parseExample,
  extractImports,
  extractComponentUsage,
  parsePropsString,
  extractPropsFromUsage,
  generateStoryEntries,
  formatStoryName,
  extractStoryArgs,
  groupExamplesByVariant,
  generateDocsFromExamples,
  formatExamplesSummary
} = require('./shadcn-example-handler');

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

// Mock MCP response
const mockMcpResponse = {
  examples: [
    {
      name: 'button',
      type: 'registry:ui',
      code: `import { Button } from "@/components/ui/button"

export function ButtonDemo() {
  return <Button variant="default">Click me</Button>
}`
    },
    {
      name: 'button-demo',
      type: 'registry:example',
      code: `import { Button } from "@/components/ui/button"

export function ButtonDemo() {
  return <Button>Default Button</Button>
}`
    },
    {
      name: 'button-destructive',
      type: 'registry:example',
      code: `import { Button } from "@/components/ui/button"

export function ButtonDestructive() {
  return <Button variant="destructive">Delete</Button>
}`
    },
    {
      name: 'button-with-icon',
      type: 'registry:example',
      code: `import { Button } from "@/components/ui/button"
import { Mail } from "lucide-react"

export function ButtonWithIcon() {
  return <Button><Mail className="mr-2 h-4 w-4" />Login with Email</Button>
}`
    }
  ]
};

// Complex example code for testing
const complexExampleCode = `
import { Button } from "@/components/ui/button"
import { Card, CardHeader, CardContent } from "@/components/ui/card"
import { Mail, User } from "lucide-react"

/**
 * Example showing multiple component usage
 */
export function ComplexExample() {
  return (
    <Card className="w-[350px]">
      <CardHeader>
        <Button variant="outline" size="sm" disabled>
          Header Button
        </Button>
      </CardHeader>
      <CardContent>
        <Button variant="default" size="lg">
          <Mail className="mr-2" />
          Primary Action
        </Button>
        <Button variant="secondary">Secondary</Button>
      </CardContent>
    </Card>
  )
}
`;

function runTests() {
  console.log('\n=== ShadCN Example Handler Tests ===\n');

  // Test: parseExamplesFromMcp
  console.log('--- parseExamplesFromMcp ---');
  const parsed = parseExamplesFromMcp(mockMcpResponse, 'button');

  test('parses main component', parsed.main !== null);
  test('main component is button', parsed.main && parsed.main.name === 'button');
  test('finds demo examples', parsed.demos.length >= 1);
  test('collects all examples', parsed.all.length === 4);

  const nullParsed = parseExamplesFromMcp(null, 'button');
  test('handles null response', nullParsed.main === null);
  test('null response has empty demos', nullParsed.demos.length === 0);

  // Test: parseExample
  console.log('\n--- parseExample ---');
  const example = parseExample(mockMcpResponse.examples[0]);

  test('parses example name', example.name === 'button');
  test('parses example type', example.type === 'registry:ui');
  test('has code property', typeof example.code === 'string');
  test('extracts imports', Array.isArray(example.imports));
  test('extracts component usage', Array.isArray(example.componentUsage));
  test('detects variant usage', example.hasVariants === true);
  test('generates description', typeof example.description === 'string');

  // Test: extractImports
  console.log('\n--- extractImports ---');
  const imports = extractImports(complexExampleCode);

  test('extracts Button import', imports.some(i => i.source === '@/components/ui/button'));
  test('extracts Card import', imports.some(i => i.source === '@/components/ui/card'));
  test('extracts lucide-react import', imports.some(i => i.source === 'lucide-react'));
  test('has specifiers', imports.length > 0 && imports[0].specifiers);

  // Test: extractComponentUsage
  console.log('\n--- extractComponentUsage ---');
  const usages = extractComponentUsage(complexExampleCode);

  test('finds Button usages', usages.some(u => u.component === 'Button'));
  test('finds Card usage', usages.some(u => u.component === 'Card'));
  test('finds CardHeader usage', usages.some(u => u.component === 'CardHeader'));
  test('finds CardContent usage', usages.some(u => u.component === 'CardContent'));
  test('finds Mail icon usage', usages.some(u => u.component === 'Mail'));

  const buttonUsages = usages.filter(u => u.component === 'Button');
  test('finds multiple Button instances', buttonUsages.length >= 3);

  // Test: parsePropsString
  console.log('\n--- parsePropsString ---');
  const props1 = parsePropsString('variant="outline" size="sm" disabled');
  test('parses string prop variant', props1.variant === 'outline');
  test('parses string prop size', props1.size === 'sm');
  test('parses boolean prop disabled', props1.disabled === true);

  const props2 = parsePropsString('className="mr-2 h-4 w-4"');
  test('parses className prop', props2.className === 'mr-2 h-4 w-4');

  const props3 = parsePropsString('onClick={handleClick} count={5}');
  test('parses expression onClick', props3.onClick === '{handleClick}');
  test('parses expression count', props3.count === '{5}');

  // Test: extractPropsFromUsage
  console.log('\n--- extractPropsFromUsage ---');
  const propsFromCode = extractPropsFromUsage(complexExampleCode);

  test('extracts Button props', Array.isArray(propsFromCode['Button']));
  test('Button has variant prop', propsFromCode['Button'] && propsFromCode['Button'].includes('variant'));
  test('Button has size prop', propsFromCode['Button'] && propsFromCode['Button'].includes('size'));

  // Test: generateStoryEntries
  console.log('\n--- generateStoryEntries ---');
  const stories = generateStoryEntries(parsed.all.map(e => parseExample(e)), 'button');

  test('generates story entries', stories.length > 0);
  test('story has name', stories[0].name);
  test('story has exportName', stories[0].exportName);
  test('story has description', 'description' in stories[0]);
  test('story has code', stories[0].code);
  test('story has args', 'args' in stories[0]);

  // Test: formatStoryName
  console.log('\n--- formatStoryName ---');
  test('button -> Default', formatStoryName('button', 'button') === 'Default');
  test('button-demo -> Default', formatStoryName('button-demo', 'button') === 'Default');
  test('button-destructive -> Destructive', formatStoryName('button-destructive', 'button') === 'Destructive');
  test('button-with-icon -> WithIcon', formatStoryName('button-with-icon', 'button') === 'WithIcon');
  test('card-example -> Default', formatStoryName('card-example', 'card') === 'Default');

  // Test: extractStoryArgs
  console.log('\n--- extractStoryArgs ---');
  const destructiveExample = parseExample(mockMcpResponse.examples[2]);
  const args = extractStoryArgs(destructiveExample);

  test('extracts variant arg', args.variant === 'destructive');

  // Test with size
  const sizeExampleCode = '<Button variant="outline" size="lg">Large</Button>';
  const sizeExample = parseExample({ name: 'test', code: sizeExampleCode });
  const sizeArgs = extractStoryArgs(sizeExample);
  test('extracts size arg', sizeArgs.size === 'lg');

  // Test: groupExamplesByVariant
  console.log('\n--- groupExamplesByVariant ---');
  const parsedExamples = parsed.all.map(e => parseExample(e));
  const groups = groupExamplesByVariant(parsedExamples);

  test('has default group', Array.isArray(groups.default));
  test('has variants group', typeof groups.variants === 'object');
  test('has compositions group', Array.isArray(groups.compositions));
  test('icon example in compositions', groups.compositions.some(e => e.name.includes('icon')));

  // Test: generateDocsFromExamples
  console.log('\n--- generateDocsFromExamples ---');
  const docs = generateDocsFromExamples(parsedExamples, 'Button');

  test('generates docs with title', docs.title === 'Button');
  test('has description', typeof docs.description === 'string');
  test('has sections array', Array.isArray(docs.sections));
  test('sections have titles', docs.sections.length > 0 && docs.sections[0].title);

  // Test: formatExamplesSummary
  console.log('\n--- formatExamplesSummary ---');
  const summary = formatExamplesSummary(parsed);

  test('formats summary string', typeof summary === 'string');
  test('summary includes Main Component', summary.includes('Main Component'));
  test('summary includes Demo Examples', summary.includes('Demo Examples'));
  test('summary includes Total Examples', summary.includes('Total Examples'));

  // Edge cases
  console.log('\n--- Edge Cases ---');
  const emptyParsed = parseExamplesFromMcp({ examples: [] }, 'test');
  test('handles empty examples array', emptyParsed.all.length === 0);

  const emptyImports = extractImports('const x = 1;');
  test('handles code without imports', emptyImports.length === 0);

  const noComponentUsage = extractComponentUsage('const x = 1;');
  test('handles code without components', noComponentUsage.length === 0);

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
