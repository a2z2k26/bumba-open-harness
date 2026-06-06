/**
 * Schema Validation Test Suite
 * Phase 3 - Sprints 141-152: Input/Output Validation
 */

const path = require('path');

// Module under test
const {
  validate,
  assertValid,
  validateWithFallback,
  matches,
  validateFigmaComponent,
  validateTokens,
  validateRegistryEntry,
  validateGeneratedComponent,
  validateStory,
  getSchema,
  listSchemaTypes,
  FIGMA_COMPONENT_SCHEMA,
  TOKEN_SCHEMA
} = require('../../schema-validator');

const { SchemaValidationError } = require('../../error-types');

// Results tracking
const results = {
  passed: 0,
  failed: 0,
  tests: []
};

// ANSI colors
const colors = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  red: '\x1b[31m',
  cyan: '\x1b[36m',
  dim: '\x1b[2m',
  bold: '\x1b[1m'
};

/**
 * Test runner helper
 */
function test(name, fn) {
  try {
    const result = fn();
    if (result === true || result === undefined) {
      results.passed++;
      results.tests.push({ name, status: 'PASS' });
      console.log(`  ${colors.green}✓${colors.reset} ${name}`);
    } else {
      results.failed++;
      results.tests.push({ name, status: 'FAIL', error: `Returned: ${JSON.stringify(result)}` });
      console.log(`  ${colors.red}✗${colors.reset} ${name}`);
    }
  } catch (error) {
    results.failed++;
    results.tests.push({ name, status: 'FAIL', error: error.message });
    console.log(`  ${colors.red}✗${colors.reset} ${name}`);
    console.log(`    ${colors.dim}Error: ${error.message}${colors.reset}`);
  }
}

// =============================================================================
// CORE VALIDATION TESTS
// =============================================================================

function runCoreValidationTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 1: Core Validation Engine${colors.reset}                     ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  test('validate function exists', () => {
    return typeof validate === 'function';
  });

  test('validate returns valid:true for matching data', () => {
    const schema = { type: 'string' };
    const result = validate('hello', schema);
    return result.valid === true && result.errors.length === 0;
  });

  test('validate returns valid:false for non-matching data', () => {
    const schema = { type: 'string' };
    const result = validate(123, schema);
    return result.valid === false && result.errors.length > 0;
  });

  test('validate handles type arrays', () => {
    const schema = { type: ['string', 'number'] };
    return validate('hello', schema).valid && validate(123, schema).valid;
  });

  test('validate enforces required properties', () => {
    const schema = {
      type: 'object',
      required: ['name', 'id']
    };
    const result = validate({ name: 'test' }, schema);
    return !result.valid && result.errors.some(e => e.property === 'id');
  });

  test('validate enforces minLength', () => {
    const schema = { type: 'string', minLength: 5 };
    return !validate('hi', schema).valid && validate('hello', schema).valid;
  });

  test('validate enforces enum', () => {
    const schema = { type: 'string', enum: ['a', 'b', 'c'] };
    return validate('a', schema).valid && !validate('d', schema).valid;
  });

  test('validate enforces minimum/maximum', () => {
    const schema = { type: 'number', minimum: 0, maximum: 100 };
    return validate(50, schema).valid &&
           !validate(-1, schema).valid &&
           !validate(101, schema).valid;
  });

  test('validate handles nested objects', () => {
    const schema = {
      type: 'object',
      properties: {
        user: {
          type: 'object',
          required: ['name'],
          properties: {
            name: { type: 'string' }
          }
        }
      }
    };
    return validate({ user: { name: 'John' } }, schema).valid &&
           !validate({ user: {} }, schema).valid;
  });

  test('validate handles arrays with items', () => {
    const schema = {
      type: 'array',
      items: { type: 'number' }
    };
    return validate([1, 2, 3], schema).valid &&
           !validate([1, 'two', 3], schema).valid;
  });

  test('validate handles null/undefined', () => {
    const schema = { type: 'string' };
    return !validate(null, schema).valid && !validate(undefined, schema).valid;
  });

  test('validate includes path in errors', () => {
    const schema = {
      type: 'object',
      properties: { name: { type: 'string' } }
    };
    const result = validate({ name: 123 }, schema);
    return result.errors[0].path.includes('name');
  });
}

// =============================================================================
// FIGMA COMPONENT VALIDATION TESTS
// =============================================================================

function runFigmaValidationTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 2: Figma Component Validation${colors.reset}                 ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  test('validateFigmaComponent accepts valid component', () => {
    const component = {
      id: '123:456',
      name: 'Button',
      type: 'COMPONENT'
    };
    return validateFigmaComponent(component, { silent: true }).valid;
  });

  test('validateFigmaComponent rejects missing id', () => {
    const component = { name: 'Button', type: 'COMPONENT' };
    return !validateFigmaComponent(component, { silent: true }).valid;
  });

  test('validateFigmaComponent rejects invalid type', () => {
    const component = {
      id: '123:456',
      name: 'Button',
      type: 'INVALID_TYPE'
    };
    return !validateFigmaComponent(component, { silent: true }).valid;
  });

  test('validateFigmaComponent accepts COMPONENT_SET', () => {
    const component = {
      id: '123:456',
      name: 'Button',
      type: 'COMPONENT_SET',
      children: []
    };
    return validateFigmaComponent(component, { silent: true }).valid;
  });

  test('validateFigmaComponent validates nested children', () => {
    const component = {
      id: '123:456',
      name: 'Button',
      type: 'COMPONENT',
      children: [
        { id: '123:457', name: 'Label', type: 'TEXT' }
      ]
    };
    return validateFigmaComponent(component, { silent: true }).valid;
  });

  test('validateFigmaComponent accepts layout properties', () => {
    const component = {
      id: '123:456',
      name: 'Card',
      type: 'FRAME',
      layoutMode: 'VERTICAL',
      itemSpacing: 16,
      paddingTop: 8,
      paddingBottom: 8
    };
    return validateFigmaComponent(component, { silent: true }).valid;
  });
}

// =============================================================================
// TOKEN VALIDATION TESTS
// =============================================================================

function runTokenValidationTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 3: Token Validation${colors.reset}                           ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  test('validateTokens accepts valid tokens', () => {
    const tokens = {
      colors: {
        primary: { value: '#3B82F6', type: 'color' }
      }
    };
    return validateTokens(tokens, { silent: true }).valid;
  });

  test('validateTokens accepts nested token groups', () => {
    const tokens = {
      colors: {
        brand: {
          primary: { value: '#3B82F6' },
          secondary: { value: '#6B7280' }
        }
      }
    };
    return validateTokens(tokens, { silent: true }).valid;
  });

  test('validateTokens accepts numeric values', () => {
    const tokens = {
      spacing: {
        sm: { value: 8, type: 'spacing' },
        md: { value: 16, type: 'spacing' }
      }
    };
    return validateTokens(tokens, { silent: true }).valid;
  });
}

// =============================================================================
// REGISTRY VALIDATION TESTS
// =============================================================================

function runRegistryValidationTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 4: Registry Entry Validation${colors.reset}                  ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  test('validateRegistryEntry accepts valid entry', () => {
    const entry = {
      id: 'btn-primary-001',
      name: 'PrimaryButton',
      source: 'figma'
    };
    return validateRegistryEntry(entry, { silent: true }).valid;
  });

  test('validateRegistryEntry rejects invalid source', () => {
    const entry = {
      id: 'btn-001',
      name: 'Button',
      source: 'invalid-source'
    };
    return !validateRegistryEntry(entry, { silent: true }).valid;
  });

  test('validateRegistryEntry accepts all valid sources', () => {
    const sources = ['figma', 'shadcn', 'nlp', 'manual', 'code'];
    return sources.every(source =>
      validateRegistryEntry({
        id: 'test-001',
        name: 'Test',
        source
      }, { silent: true }).valid
    );
  });

  test('validateRegistryEntry accepts full entry', () => {
    const entry = {
      id: 'btn-001',
      name: 'Button',
      source: 'figma',
      figmaNodeId: '123:456',
      category: 'button',
      transformedTo: ['react', 'vue'],
      outputPaths: {
        react: '.design/components/Button.tsx'
      },
      syncMetadata: {
        lastSynced: new Date().toISOString(),
        version: '1.0.0',
        contentHash: 'abc123'
      }
    };
    return validateRegistryEntry(entry, { silent: true }).valid;
  });
}

// =============================================================================
// GENERATED COMPONENT VALIDATION TESTS
// =============================================================================

function runGeneratedComponentTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 5: Generated Component Validation${colors.reset}             ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  test('validateGeneratedComponent accepts valid output', () => {
    const component = {
      name: 'Button',
      code: 'export const Button = () => <button>Click</button>',
      framework: 'react'
    };
    return validateGeneratedComponent(component, { silent: true }).valid;
  });

  test('validateGeneratedComponent rejects empty code', () => {
    const component = {
      name: 'Button',
      code: '',
      framework: 'react'
    };
    return !validateGeneratedComponent(component, { silent: true }).valid;
  });

  test('validateGeneratedComponent accepts props', () => {
    const component = {
      name: 'Button',
      code: 'export const Button = (props) => <button>{props.label}</button>',
      framework: 'react',
      props: {
        label: { type: 'string', default: 'Click', required: true }
      }
    };
    return validateGeneratedComponent(component, { silent: true }).valid;
  });
}

// =============================================================================
// STORY VALIDATION TESTS
// =============================================================================

function runStoryValidationTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 6: Story Validation${colors.reset}                           ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  test('validateStory accepts valid story', () => {
    const story = {
      componentName: 'Button',
      content: 'export default { title: "Button" };'
    };
    return validateStory(story, { silent: true }).valid;
  });

  test('validateStory accepts full story', () => {
    const story = {
      componentName: 'Button',
      content: 'export default { title: "Button" };',
      framework: 'react',
      argTypes: { variant: { control: 'select' } },
      args: { variant: 'primary' },
      variants: ['primary', 'secondary']
    };
    return validateStory(story, { silent: true }).valid;
  });
}

// =============================================================================
// UTILITY FUNCTION TESTS
// =============================================================================

function runUtilityTests() {
  console.log(`\n${colors.cyan}┌─────────────────────────────────────────────────────┐${colors.reset}`);
  console.log(`${colors.cyan}│${colors.reset} ${colors.bold}Suite 7: Utility Functions${colors.reset}                          ${colors.cyan}│${colors.reset}`);
  console.log(`${colors.cyan}└─────────────────────────────────────────────────────┘${colors.reset}`);

  test('assertValid returns data on success', () => {
    const data = { name: 'test' };
    const schema = { type: 'object' };
    const result = assertValid(data, schema);
    return result === data;
  });

  test('assertValid throws SchemaValidationError on failure', () => {
    const schema = { type: 'string' };
    try {
      assertValid(123, schema);
      return false;
    } catch (e) {
      return e instanceof SchemaValidationError;
    }
  });

  test('validateWithFallback returns data on success', () => {
    const data = 'hello';
    const schema = { type: 'string' };
    const result = validateWithFallback(data, schema, 'default', { silent: true });
    return result.valid && result.data === 'hello';
  });

  test('validateWithFallback returns fallback on failure', () => {
    const schema = { type: 'string' };
    const result = validateWithFallback(123, schema, 'default', { logWarning: false });
    return !result.valid && result.data === 'default';
  });

  test('matches returns boolean', () => {
    const schema = { type: 'string' };
    return matches('hello', schema) === true && matches(123, schema) === false;
  });

  test('getSchema returns correct schema', () => {
    const schema = getSchema('figma-component');
    return schema === FIGMA_COMPONENT_SCHEMA;
  });

  test('getSchema returns null for unknown type', () => {
    return getSchema('unknown-type') === null;
  });

  test('listSchemaTypes returns all types', () => {
    const types = listSchemaTypes();
    return types.includes('figma-component') &&
           types.includes('token') &&
           types.includes('registry-entry');
  });
}

// =============================================================================
// MAIN TEST RUNNER
// =============================================================================

async function runAllTests() {
  console.log(`${colors.bold}${colors.cyan}`);
  console.log('╔═══════════════════════════════════════════════════════════╗');
  console.log('║         SCHEMA VALIDATION TEST SUITE                      ║');
  console.log('║              Phase 3: Sprints 141-152                     ║');
  console.log('╚═══════════════════════════════════════════════════════════╝');
  console.log(`${colors.reset}`);

  const startTime = Date.now();

  // Run all test suites
  runCoreValidationTests();
  runFigmaValidationTests();
  runTokenValidationTests();
  runRegistryValidationTests();
  runGeneratedComponentTests();
  runStoryValidationTests();
  runUtilityTests();

  const duration = Date.now() - startTime;

  // Summary
  console.log(`\n${colors.cyan}╔═══════════════════════════════════════════════════════════╗${colors.reset}`);
  console.log(`${colors.cyan}║${colors.reset}${colors.bold}                    TEST SUMMARY                           ${colors.reset}${colors.cyan}║${colors.reset}`);
  console.log(`${colors.cyan}╚═══════════════════════════════════════════════════════════╝${colors.reset}`);
  console.log('');
  console.log(`  ${colors.bold}Total Tests:${colors.reset}   ${results.passed + results.failed}`);
  console.log(`  ${colors.green}Passed:${colors.reset}        ${results.passed}`);
  console.log(`  ${colors.red}Failed:${colors.reset}        ${results.failed}`);
  console.log(`  ${colors.dim}Duration:${colors.reset}      ${duration}ms`);
  console.log('');

  if (results.failed === 0) {
    console.log(`  ${colors.green}${colors.bold}✓ All validation tests passed!${colors.reset}`);
  } else {
    console.log(`  ${colors.red}${colors.bold}✗ ${results.failed} test(s) failed${colors.reset}`);
    results.tests
      .filter(t => t.status === 'FAIL')
      .forEach(t => console.log(`    - ${t.name}: ${t.error}`));
  }

  console.log('');

  return {
    passed: results.passed,
    failed: results.failed,
    total: results.passed + results.failed,
    duration
  };
}

// Export for use as module
module.exports = { run: runAllTests, runAllTests };

// Run if called directly
if (require.main === module) {
  runAllTests()
    .then(results => {
      process.exit(results.failed > 0 ? 1 : 0);
    })
    .catch(err => {
      console.error(`${colors.red}Fatal error:${colors.reset}`, err);
      process.exit(1);
    });
}
