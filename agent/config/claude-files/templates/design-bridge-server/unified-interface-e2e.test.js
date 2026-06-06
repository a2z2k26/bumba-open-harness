/**
 * unified-interface-e2e.test.js
 * End-to-End Tests for the Unified Extraction Interface
 * Validates all extraction methods produce consistent output
 */

const path = require('path');
const fs = require('fs');

// Import unified interface module
const {
  ExtractionMethods,
  SHADCN_COMPONENTS,
  normalizeInput,
  detectMethodFromTarget,
  createUnifiedOutput,
  isFigmaUrl,
  isShadcnComponent,
  isJsonSpec,
  validateOutput,
  validateInput,
  countNormalizedFields,
  countTokens,
  getMethodDisplayName,
  getAllMethods
} = require('./unified-interface');

// Test output directory
const TEST_DIR = path.join(__dirname, '.test-unified-interface');

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

function cleanup() {
  try {
    if (fs.existsSync(TEST_DIR)) {
      fs.rmSync(TEST_DIR, { recursive: true });
    }
  } catch (e) {
    // Ignore cleanup errors
  }
}

function setup() {
  cleanup();
  fs.mkdirSync(TEST_DIR, { recursive: true });
  fs.mkdirSync(path.join(TEST_DIR, '.design'), { recursive: true });
}

/**
 * Mock extraction results for each method
 */
const mockExtractionResults = {
  'figma-mcp': {
    success: true,
    id: 'figma-button-abc123',
    name: 'Button',
    type: 'COMPONENT_SET',
    source: {
      type: 'figma-mcp',
      url: 'https://figma.com/file/abc123',
      nodeId: '1:2'
    },
    tokenDependencies: {
      colors: ['Primary/500', 'White'],
      typography: ['Body/Medium']
    },
    variants: [
      { name: 'primary', property: 'variant', value: 'primary' },
      { name: 'secondary', property: 'variant', value: 'secondary' }
    ],
    children: [
      { name: 'label', type: 'TEXT' }
    ],
    paths: {
      rawSource: '.design/source/Button.json',
      component: '.design/components/Button.json'
    }
  },

  'shadcn': {
    success: true,
    id: 'shadcn-button-def456',
    name: 'Button',
    type: 'COMPONENT',
    source: {
      type: 'shadcn',
      component: 'button',
      registry: '@shadcn'
    },
    tokenDependencies: {
      colors: ['--primary', '--primary-foreground']
    },
    variants: [
      { name: 'default' },
      { name: 'destructive' },
      { name: 'outline' }
    ],
    children: [],
    paths: {
      rawSource: '.design/source/Button.json',
      component: '.design/components/Button.json'
    }
  },

  'nlp-prompt': {
    success: true,
    id: 'nlp-button-ghi789',
    name: 'Button',
    type: 'COMPONENT',
    source: {
      type: 'nlp-prompt',
      prompt: 'A button component'
    },
    tokenDependencies: {
      colors: ['primary', 'white'],
      spacing: ['padding-sm', 'padding-md']
    },
    variants: [{ name: 'default', isDefault: true }],
    children: [{ name: 'content', type: 'slot' }],
    paths: {
      rawSource: '.design/source/Button.json'
    }
  },

  'manual': {
    success: true,
    id: 'manual-button-jkl012',
    name: 'Button',
    type: 'COMPONENT_SET',
    source: {
      type: 'manual',
      author: 'test'
    },
    tokenDependencies: {
      colors: ['Primary/500'],
      typography: ['Body/Medium']
    },
    variants: [
      { name: 'primary' },
      { name: 'secondary' }
    ],
    props: [
      { name: 'children', type: 'ReactNode', required: true }
    ],
    paths: {
      rawSource: '.design/source/Button.json',
      component: '.design/components/Button.json'
    }
  }
};

function runTests() {
  console.log('\n=== Unified Interface End-to-End Tests ===\n');

  setup();

  // Test Group 1: ExtractionMethods enum
  console.log('--- Test 1: ExtractionMethods enum ---');

  test('has FIGMA_PLUGIN method', ExtractionMethods.FIGMA_PLUGIN === 'figma-plugin');
  test('has FIGMA_MCP method', ExtractionMethods.FIGMA_MCP === 'figma-mcp');
  test('has SHADCN method', ExtractionMethods.SHADCN === 'shadcn');
  test('has NLP_PROMPT method', ExtractionMethods.NLP_PROMPT === 'nlp-prompt');
  test('has MANUAL method', ExtractionMethods.MANUAL === 'manual');

  // Test Group 2: Method Detection - Figma URLs
  console.log('\n--- Test 2: isFigmaUrl detection ---');

  test('detects figma.com/file URL', isFigmaUrl('https://figma.com/file/abc123'));
  test('detects figma.com/design URL', isFigmaUrl('https://figma.com/design/abc123'));
  test('detects figma.com/proto URL', isFigmaUrl('https://figma.com/proto/abc123'));
  test('detects URL with query params', isFigmaUrl('https://figma.com/file/abc123?node-id=1:2'));
  test('rejects non-Figma URL', !isFigmaUrl('https://github.com/something'));
  test('rejects plain text', !isFigmaUrl('hello world'));
  test('rejects null', !isFigmaUrl(null));
  test('rejects number', !isFigmaUrl(123));

  // Test Group 3: ShadCN Component Detection
  console.log('\n--- Test 3: isShadcnComponent detection ---');

  test('detects button component', isShadcnComponent('button'));
  test('detects card component', isShadcnComponent('card'));
  test('detects dropdown-menu component', isShadcnComponent('dropdown-menu'));
  test('detects data-table component', isShadcnComponent('data-table'));
  test('detects short identifier', isShadcnComponent('my-component'));
  test('rejects long descriptive text', !isShadcnComponent('A beautiful button component with multiple variants'));
  test('rejects mixed case with spaces', !isShadcnComponent('My Component'));
  test('handles SHADCN_COMPONENTS list', SHADCN_COMPONENTS.length > 40);

  // Test Group 4: JSON Spec Detection
  console.log('\n--- Test 4: isJsonSpec detection ---');

  test('detects JSON object', isJsonSpec({ name: 'Test' }));
  test('detects JSON string', isJsonSpec('{"name": "Test"}'));
  test('rejects plain text', !isJsonSpec('hello'));
  test('rejects invalid JSON', !isJsonSpec('{name: Test}'));
  test('rejects JSON without name', !isJsonSpec('{"type": "COMPONENT"}'));

  // Test Group 5: detectMethodFromTarget
  console.log('\n--- Test 5: detectMethodFromTarget ---');

  const figmaDetect = detectMethodFromTarget('https://figma.com/file/abc123');
  test('detects figma-mcp from Figma URL', figmaDetect.method === 'figma-mcp');
  test('preserves Figma URL as target', figmaDetect.target === 'https://figma.com/file/abc123');

  const shadcnDetect = detectMethodFromTarget('button');
  test('detects shadcn from component name', shadcnDetect.method === 'shadcn');
  test('preserves component name as target', shadcnDetect.target === 'button');

  const nlpDetect = detectMethodFromTarget('A card component with an image header and action buttons');
  test('detects nlp-prompt from description', nlpDetect.method === 'nlp-prompt');

  const manualDetect = detectMethodFromTarget({ name: 'TestComponent' });
  test('detects manual from JSON object', manualDetect.method === 'manual');

  const jsonStringDetect = detectMethodFromTarget('{"name": "TestComponent", "type": "COMPONENT"}');
  test('detects manual from JSON string', jsonStringDetect.method === 'manual');

  // Test Group 6: normalizeInput - string input (returns method/target only)
  console.log('\n--- Test 6: normalizeInput string input ---');

  const normFigma = normalizeInput('https://figma.com/file/abc123');
  test('normalizes Figma URL to figma-mcp', normFigma.method === 'figma-mcp');
  test('preserves target URL', normFigma.target === 'https://figma.com/file/abc123');

  const normShadcn = normalizeInput('button');
  test('normalizes component to shadcn', normShadcn.method === 'shadcn');
  test('preserves target component', normShadcn.target === 'button');

  const normNlp = normalizeInput('A beautiful blue button with rounded corners');
  test('normalizes description to nlp-prompt', normNlp.method === 'nlp-prompt');
  test('preserves target description', normNlp.target === 'A beautiful blue button with rounded corners');

  // Test Group 7: normalizeInput - object input
  console.log('\n--- Test 7: normalizeInput object input ---');

  const normObj = normalizeInput({
    target: 'card',
    options: {
      framework: 'vue',
      generateStory: true
    }
  });
  test('auto-detects method from target', normObj.method === 'shadcn');
  test('preserves framework option', normObj.options.framework === 'vue');
  test('preserves generateStory option', normObj.options.generateStory === true);
  test('applies default generateCode', normObj.options.generateCode === true);

  const normExplicit = normalizeInput({
    method: 'nlp-prompt',
    target: 'button',
    options: { outputDir: './components' }
  });
  test('preserves explicit method', normExplicit.method === 'nlp-prompt');
  test('preserves custom outputDir', normExplicit.options.outputDir === './components');

  // Test Group 8: normalizeInput error handling
  console.log('\n--- Test 8: normalizeInput error handling ---');

  let errorThrown = false;
  try {
    normalizeInput(null);
  } catch (e) {
    errorThrown = true;
  }
  test('throws on null input', errorThrown);

  errorThrown = false;
  try {
    normalizeInput({});
  } catch (e) {
    errorThrown = true;
  }
  test('throws on empty object', errorThrown);

  // Test Group 9: validateInput
  console.log('\n--- Test 9: validateInput ---');

  const validInput1 = validateInput({ method: 'shadcn', target: 'button' });
  test('validates correct input', validInput1.valid === true);
  test('has no errors for valid input', validInput1.errors.length === 0);

  const validInput2 = validateInput({ target: 'button' });
  test('validates input with only target', validInput2.valid === true);

  const invalidInput1 = validateInput(null);
  test('invalidates null input', invalidInput1.valid === false);

  const invalidInput2 = validateInput({ method: 'invalid-method' });
  test('invalidates unknown method', invalidInput2.valid === false);
  test('includes error message for invalid method', invalidInput2.errors.some(e => e.includes('Invalid method')));

  const invalidInput3 = validateInput({ method: 'shadcn', options: { framework: 'invalid' } });
  test('invalidates unknown framework', invalidInput3.valid === false);

  // Test Group 10: createUnifiedOutput
  console.log('\n--- Test 10: createUnifiedOutput ---');

  const startTime = Date.now();
  const unifiedOutput = createUnifiedOutput(mockExtractionResults['shadcn'], 'shadcn', startTime);

  test('creates success field', typeof unifiedOutput.success === 'boolean');
  test('sets success to true', unifiedOutput.success === true);
  test('sets correct method', unifiedOutput.method === 'shadcn');
  test('creates timestamp', typeof unifiedOutput.timestamp === 'string');
  test('creates component object', unifiedOutput.component !== null);
  test('component has id', unifiedOutput.component.id === 'shadcn-button-def456');
  test('component has name', unifiedOutput.component.name === 'Button');
  test('component has type', unifiedOutput.component.type === 'COMPONENT');
  test('component has source', unifiedOutput.component.source !== null);
  test('source has type', unifiedOutput.component.source.type === 'shadcn');
  test('source has extractedAt', typeof unifiedOutput.component.source.extractedAt === 'string');
  test('creates warnings array', Array.isArray(unifiedOutput.warnings));
  test('creates errors array', Array.isArray(unifiedOutput.errors));
  test('creates metadata object', typeof unifiedOutput.metadata === 'object');
  test('metadata has duration', typeof unifiedOutput.metadata.duration === 'number');

  // Test Group 11: createUnifiedOutput - all methods
  console.log('\n--- Test 11: createUnifiedOutput all methods ---');

  for (const [method, mockResult] of Object.entries(mockExtractionResults)) {
    const output = createUnifiedOutput(mockResult, method, Date.now());

    test(`${method}: creates valid output`, output.success === true);
    test(`${method}: has component`, output.component !== null);
    test(`${method}: has source.type`, output.component.source.type === method);
  }

  // Test Group 12: validateOutput
  console.log('\n--- Test 12: validateOutput ---');

  const validOutput = createUnifiedOutput(mockExtractionResults['shadcn'], 'shadcn', Date.now());
  const validation1 = validateOutput(validOutput);
  test('validates correct output', validation1.valid === true);
  test('has no validation errors', validation1.errors.length === 0);

  const validation2 = validateOutput({});
  test('invalidates empty output', validation2.valid === false);
  test('catches missing success', validation2.errors.some(e => e.includes('success')));

  const validation3 = validateOutput({ success: true, method: 'test' });
  test('catches missing component on success', validation3.errors.some(e => e.includes('component')));

  const validation4 = validateOutput({
    success: true,
    method: 'test',
    timestamp: new Date().toISOString(),
    component: { id: '1', name: 'Test', source: { type: 'test' } },
    warnings: [],
    errors: []
  });
  test('validates complete output', validation4.valid === true);

  // Test Group 13: countNormalizedFields
  console.log('\n--- Test 13: countNormalizedFields ---');

  const fieldCount1 = countNormalizedFields(mockExtractionResults['shadcn']);
  test('counts fields in extraction result', fieldCount1 > 0);
  test('counts expected fields', fieldCount1 >= 5);

  const fieldCount2 = countNormalizedFields({ component: mockExtractionResults['figma-mcp'] });
  test('counts fields from nested component', fieldCount2 > 0);

  const fieldCount3 = countNormalizedFields({});
  test('returns 0 for empty result', fieldCount3 === 0);

  // Test Group 14: countTokens
  console.log('\n--- Test 14: countTokens ---');

  const tokenCount1 = countTokens(mockExtractionResults['figma-mcp']);
  test('counts tokens from tokenDependencies', tokenCount1 === 3); // 2 colors + 1 typography

  const tokenCount2 = countTokens(mockExtractionResults['nlp-prompt']);
  test('counts tokens across categories', tokenCount2 === 4); // 2 colors + 2 spacing

  const tokenCount3 = countTokens({});
  test('returns 0 for no tokens', tokenCount3 === 0);

  // Test Group 15: getMethodDisplayName
  console.log('\n--- Test 15: getMethodDisplayName ---');

  test('displays Figma Plugin', getMethodDisplayName('figma-plugin') === 'Figma Plugin');
  test('displays Figma MCP', getMethodDisplayName('figma-mcp') === 'Figma MCP');
  test('displays ShadCN Registry', getMethodDisplayName('shadcn') === 'ShadCN Registry');
  test('displays NLP Prompting', getMethodDisplayName('nlp-prompt') === 'NLP Prompting');
  test('displays Manual Specification', getMethodDisplayName('manual') === 'Manual Specification');
  test('returns key for unknown method', getMethodDisplayName('unknown') === 'unknown');

  // Test Group 16: getAllMethods
  console.log('\n--- Test 16: getAllMethods ---');

  const allMethods = getAllMethods();
  test('returns array', Array.isArray(allMethods));
  test('has 5 methods', allMethods.length === 5);
  test('each method has key', allMethods.every(m => typeof m.key === 'string'));
  test('each method has value', allMethods.every(m => typeof m.value === 'string'));
  test('each method has displayName', allMethods.every(m => typeof m.displayName === 'string'));

  // Test Group 17: Output Structure Consistency
  console.log('\n--- Test 17: Output structure consistency ---');

  const outputs = [];
  for (const [method, mockResult] of Object.entries(mockExtractionResults)) {
    const output = createUnifiedOutput(mockResult, method, Date.now());
    outputs.push(output);
  }

  // Check all outputs have same top-level keys
  const keys0 = Object.keys(outputs[0]).sort().join(',');
  const allSameKeys = outputs.every(o => Object.keys(o).sort().join(',') === keys0);
  test('all methods produce same top-level keys', allSameKeys);

  // Check all outputs pass validation
  const allValid = outputs.every(o => validateOutput(o).valid);
  test('all method outputs pass validation', allValid);

  // Test Group 18: Edge Cases
  console.log('\n--- Test 18: Edge cases ---');

  // Empty arrays
  const emptyWarnings = createUnifiedOutput({
    success: true,
    id: 'test',
    name: 'Test',
    type: 'COMPONENT',
    source: { type: 'test' },
    paths: {}
  }, 'test', Date.now());
  test('handles missing warnings array', Array.isArray(emptyWarnings.warnings));
  test('handles missing errors array', Array.isArray(emptyWarnings.errors));

  // Failure output
  const failureResult = {
    success: false,
    errors: ['Failed to extract'],
    warnings: ['Connection issue']
  };
  const failureOutput = createUnifiedOutput(failureResult, 'test', Date.now());
  test('handles failure result', failureOutput.success === false);
  test('failure has null component', failureOutput.component === null);
  test('preserves errors on failure', failureOutput.errors.length > 0);
  test('preserves warnings on failure', failureOutput.warnings.length > 0);

  // Nested component structure
  const nestedResult = {
    success: true,
    component: {
      id: 'nested-id',
      name: 'Nested',
      type: 'COMPONENT',
      source: { type: 'nested-test' }
    }
  };
  const nestedOutput = createUnifiedOutput(nestedResult, 'test', Date.now());
  test('handles nested component', nestedOutput.component.id === 'nested-id');

  // Test Group 19: Round-trip validation
  console.log('\n--- Test 19: Round-trip validation ---');

  for (const [method, mockResult] of Object.entries(mockExtractionResults)) {
    // Create output
    const output = createUnifiedOutput(mockResult, method, Date.now());

    // Validate it
    const validation = validateOutput(output);

    // Check it's valid
    test(`${method}: round-trip creates valid output`, validation.valid === true);

    // Check original data is preserved
    test(`${method}: preserves component name`, output.component.name === mockResult.name);
    test(`${method}: preserves component id`, output.component.id === mockResult.id);
  }

  // Test Group 20: Extraction flow simulation
  console.log('\n--- Test 20: Full extraction flow simulation ---');

  // Simulate: user provides input -> normalize -> extract -> create output -> validate
  const testInputs = [
    'https://figma.com/file/abc123?node-id=1:2',
    'button',
    'A modern card component with shadow and rounded corners',
    '{"name": "CustomComponent", "type": "COMPONENT"}'
  ];

  for (const input of testInputs) {
    // 1. Normalize input
    const normalized = normalizeInput(input);
    test(`flow: normalizes "${input.substring(0, 30)}..."`, normalized.method !== undefined);

    // 2. Validate input
    const inputValidation = validateInput(normalized);
    test(`flow: input valid for "${input.substring(0, 30)}..."`, inputValidation.valid === true);

    // 3. Get mock result for method
    const mockResult = mockExtractionResults[normalized.method] || mockExtractionResults['nlp-prompt'];

    // 4. Create unified output
    const output = createUnifiedOutput(mockResult, normalized.method, Date.now());

    // 5. Validate output
    const outputValidation = validateOutput(output);
    test(`flow: output valid for "${input.substring(0, 30)}..."`, outputValidation.valid === true);
  }

  // Cleanup
  cleanup();

  // Print results
  console.log('\n=== Test Results ===');
  console.log(`Passed: ${passed}`);
  console.log(`Failed: ${failed}`);
  console.log(`Total: ${passed + failed}`);

  if (failed === 0) {
    console.log('\n✓ All Unified Interface E2E tests passed!');
  } else {
    console.log(`\n✗ ${failed} test(s) failed.`);
  }

  // Print method comparison matrix
  console.log('\n=== Method Comparison Matrix ===');
  console.log('─'.repeat(60));
  console.log('| Method      | Fields | Tokens | Variants | Valid |');
  console.log('|-------------|--------|--------|----------|-------|');

  for (const [method, mockResult] of Object.entries(mockExtractionResults)) {
    const output = createUnifiedOutput(mockResult, method, Date.now());
    const validation = validateOutput(output);
    const tokenCount = countTokens(mockResult);
    const variantCount = mockResult.variants?.length || 0;
    const fieldCount = countNormalizedFields(mockResult);

    console.log(`| ${method.padEnd(11)} | ${String(fieldCount).padEnd(6)} | ${String(tokenCount).padEnd(6)} | ${String(variantCount).padEnd(8)} | ${validation.valid ? '  ✓  ' : '  ✗  '} |`);
  }

  console.log('─'.repeat(60));

  return { passed, failed };
}

// Run if executed directly
if (require.main === module) {
  runTests();
}

module.exports = { runTests };
