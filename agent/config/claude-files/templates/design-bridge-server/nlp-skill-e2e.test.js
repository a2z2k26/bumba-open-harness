/**
 * nlp-skill-e2e.test.js
 * End-to-end tests for the NLP Prompting Skill
 * Tests the complete pipeline from NLP description to component generation
 */

const fs = require('fs');
const path = require('path');

// Import all modules
const inputSchema = require('./nlp-input-schema');
const prompts = require('./nlp-prompts');
const structureGenerator = require('./nlp-structure-generator');
const tokenInference = require('./nlp-token-inference');
const variantGenerator = require('./nlp-variant-generator');
const propsInference = require('./nlp-props-inference');
const registryIntegration = require('./nlp-registry-integration');

let passed = 0;
let failed = 0;

// Test output directories
const TEST_OUTPUT_DIR = path.join(__dirname, '.test-nlp-output');
const TEST_REGISTRY_PATH = path.join(TEST_OUTPUT_DIR, 'componentRegistry.json');
const TEST_COMPONENTS_DIR = path.join(TEST_OUTPUT_DIR, 'components');

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
    if (fs.existsSync(TEST_OUTPUT_DIR)) {
      fs.rmSync(TEST_OUTPUT_DIR, { recursive: true });
    }
  } catch (e) {
    // Ignore cleanup errors
  }
}

function setup() {
  cleanup();
  fs.mkdirSync(TEST_OUTPUT_DIR, { recursive: true });
  fs.mkdirSync(TEST_COMPONENTS_DIR, { recursive: true });
}

/**
 * Generate a component from NLP description (simplified version of wrapper)
 */
function generateComponent(input) {
  const result = {
    success: false,
    component: null,
    errors: []
  };

  try {
    // Step 1: Validate and normalize input
    const validation = inputSchema.validateInput(input);
    if (!validation.valid) {
      throw new Error(`Invalid input: ${validation.errors.join(', ')}`);
    }
    const normalizedInput = inputSchema.normalizeInput(input);

    // Step 2: Generate structure
    const structure = structureGenerator.generateStructure(
      normalizedInput.description,
      normalizedInput.name
    );

    // Step 3: Infer tokens
    const tokens = tokenInference.inferTokenDependencies(
      normalizedInput.description,
      normalizedInput.category
    );

    // Step 4: Generate variants
    const variants = variantGenerator.generateVariants(
      normalizedInput.description,
      normalizedInput.variants || []
    );

    // Step 5: Infer props
    const props = propsInference.inferProps(
      normalizedInput.description,
      normalizedInput.category,
      variants
    );

    // Step 6: Build component
    const timestamp = Date.now();
    const component = {
      id: `nlp-${normalizedInput.name.toLowerCase().replace(/\s+/g, '-')}-${timestamp}`,
      name: normalizedInput.name,
      type: 'COMPONENT',
      category: normalizedInput.category,
      description: normalizedInput.description,
      source: {
        type: 'nlp-prompt',
        extractedAt: new Date().toISOString(),
        prompt: normalizedInput.description,
        generationParams: {
          category: normalizedInput.category,
          framework: normalizedInput.framework,
          variants: normalizedInput.variants,
          sizes: normalizedInput.sizes,
          states: normalizedInput.states
        }
      },
      structure: structure,
      tokenDependencies: tokenInference.formatTokensForOutput(tokens),
      variants: variants,
      props: props,
      interactiveStates: normalizedInput.states || ['default', 'hover', 'disabled']
    };

    result.success = true;
    result.component = component;

  } catch (error) {
    result.errors.push(error.message);
  }

  return result;
}

/**
 * Save component and update registry
 */
function saveAndRegister(component) {
  const fileName = `${component.name}.json`;
  const filePath = path.join(TEST_COMPONENTS_DIR, fileName);

  // Save component file
  fs.writeFileSync(filePath, JSON.stringify(component, null, 2));

  // Create registry entry and update
  const entry = registryIntegration.createRegistryEntry(component, filePath);
  const updateResult = registryIntegration.updateComponentRegistry(entry, TEST_REGISTRY_PATH);

  return {
    filePath,
    entry,
    updateResult
  };
}

function runTests() {
  console.log('\n=== NLP Skill End-to-End Tests ===\n');

  setup();

  // Test 1: Simple button generation
  console.log('--- Test 1: Simple Button Generation ---');

  const buttonInput = {
    name: 'PrimaryButton',
    description: 'A primary action button with hover and disabled states',
    category: 'button'
  };

  const buttonResult = generateComponent(buttonInput);
  test('button generation succeeds', buttonResult.success === true);
  test('button has no errors', buttonResult.errors.length === 0);
  test('button component created', buttonResult.component !== null);

  if (buttonResult.component) {
    const btn = buttonResult.component;
    test('button has correct name', btn.name === 'PrimaryButton');
    test('button has correct category', btn.category === 'button');
    test('button has source', btn.source && btn.source.type === 'nlp-prompt');
    test('button has structure', btn.structure !== undefined);
    test('button has tokenDependencies', btn.tokenDependencies !== undefined);
    test('button has props', Array.isArray(btn.props));
    test('button has children prop', btn.props.some(p => p.name === 'children'));
    test('button has onClick prop', btn.props.some(p => p.name === 'onClick'));
    test('button has disabled prop', btn.props.some(p => p.name === 'disabled'));
    test('button has interactiveStates', Array.isArray(btn.interactiveStates));

    // Save and register
    const saveResult = saveAndRegister(btn);
    test('button file saved', fs.existsSync(saveResult.filePath));
    test('button registered', saveResult.updateResult.updated === true);
  }

  // Test 2: Input field with variants
  console.log('\n--- Test 2: Input Field with Variants ---');

  const inputFieldInput = {
    name: 'TextField',
    description: 'A text input field with placeholder, validation error display, and required indicator',
    category: 'input',
    variants: ['default', 'error', 'success'],
    sizes: ['sm', 'md', 'lg']
  };

  const inputResult = generateComponent(inputFieldInput);
  test('input generation succeeds', inputResult.success === true);

  if (inputResult.component) {
    const inp = inputResult.component;
    test('input has correct name', inp.name === 'TextField');
    test('input has correct category', inp.category === 'input');
    test('input has value prop', inp.props.some(p => p.name === 'value'));
    test('input has onChange prop', inp.props.some(p => p.name === 'onChange'));
    test('input has placeholder prop', inp.props.some(p => p.name === 'placeholder'));
    test('input inferred error prop', inp.props.some(p => p.name === 'error'));
    test('input inferred required prop', inp.props.some(p => p.name === 'required'));
    test('input has variants', Object.keys(inp.variants).length > 0);

    // Check token inference
    test('input has typography tokens', inp.tokenDependencies.typography && inp.tokenDependencies.typography.length > 0);

    const saveResult = saveAndRegister(inp);
    test('input file saved', fs.existsSync(saveResult.filePath));
  }

  // Test 3: Card component
  console.log('\n--- Test 3: Card Component ---');

  const cardInput = {
    name: 'ContentCard',
    description: 'A card with title, description, image, and click handler for navigation',
    category: 'card'
  };

  const cardResult = generateComponent(cardInput);
  test('card generation succeeds', cardResult.success === true);

  if (cardResult.component) {
    const card = cardResult.component;
    test('card has correct category', card.category === 'card');
    test('card inferred title prop', card.props.some(p => p.name === 'title'));
    test('card inferred description prop', card.props.some(p => p.name === 'description'));
    test('card inferred image prop', card.props.some(p => p.name === 'image'));
    test('card inferred onClick prop', card.props.some(p => p.name === 'onClick'));
    test('card has children prop', card.props.some(p => p.name === 'children'));

    const saveResult = saveAndRegister(card);
    test('card file saved', fs.existsSync(saveResult.filePath));
  }

  // Test 4: Modal overlay
  console.log('\n--- Test 4: Modal Overlay ---');

  const modalInput = {
    name: 'ConfirmDialog',
    description: 'A modal dialog for confirming user actions with close handler',
    category: 'overlay'
  };

  const modalResult = generateComponent(modalInput);
  test('modal generation succeeds', modalResult.success === true);

  if (modalResult.component) {
    const modal = modalResult.component;
    test('modal has correct category', modal.category === 'overlay');
    test('modal has open prop', modal.props.some(p => p.name === 'open'));
    test('modal has onClose prop', modal.props.some(p => p.name === 'onClose'));
    test('modal open is required', modal.props.find(p => p.name === 'open')?.required === true);
    test('modal onClose is required', modal.props.find(p => p.name === 'onClose')?.required === true);

    const saveResult = saveAndRegister(modal);
    test('modal file saved', fs.existsSync(saveResult.filePath));
  }

  // Test 5: Feedback component
  console.log('\n--- Test 5: Feedback Component ---');

  const alertInput = {
    name: 'AlertBanner',
    description: 'An alert banner for displaying info, success, warning, and error messages',
    category: 'feedback'
  };

  const alertResult = generateComponent(alertInput);
  test('alert generation succeeds', alertResult.success === true);

  if (alertResult.component) {
    const alert = alertResult.component;
    test('alert has correct category', alert.category === 'feedback');
    test('alert has message prop', alert.props.some(p => p.name === 'message'));
    test('alert has type prop', alert.props.some(p => p.name === 'type'));
    test('alert inferred error type', alert.props.some(p => p.name === 'error') ||
         alert.props.find(p => p.name === 'type')?.type.includes('error'));

    const saveResult = saveAndRegister(alert);
    test('alert file saved', fs.existsSync(saveResult.filePath));
  }

  // Test 6: Button with icon and loading
  console.log('\n--- Test 6: Icon Button with Loading ---');

  const iconButtonInput = {
    name: 'IconButton',
    description: 'A button with icon, loading spinner, and disabled state',
    category: 'button',
    variants: ['primary', 'secondary', 'ghost'],
    states: ['default', 'hover', 'active', 'disabled', 'loading']
  };

  const iconButtonResult = generateComponent(iconButtonInput);
  test('icon button generation succeeds', iconButtonResult.success === true);

  if (iconButtonResult.component) {
    const iconBtn = iconButtonResult.component;
    test('icon button inferred icon prop', iconBtn.props.some(p => p.name === 'icon'));
    test('icon button inferred loading prop', iconBtn.props.some(p => p.name === 'loading'));
    test('icon button has variants', iconBtn.variants.variant !== undefined);
    test('icon button has primary variant', iconBtn.variants.variant && iconBtn.variants.variant.primary);
    test('icon button has ghost variant', iconBtn.variants.variant && iconBtn.variants.variant.ghost);
    test('icon button has loading state', iconBtn.interactiveStates.includes('loading'));

    const saveResult = saveAndRegister(iconBtn);
    test('icon button file saved', fs.existsSync(saveResult.filePath));
  }

  // Test 7: Registry validation
  console.log('\n--- Test 7: Registry Validation ---');

  const registry = registryIntegration.loadRegistry(TEST_REGISTRY_PATH);
  test('registry has all components', registry.components.length === 6);
  test('registry has nlp-prompt source', registry.metadata.extractionSources.includes('nlp-prompt'));

  const nlpComponents = registryIntegration.getNlpComponents(TEST_REGISTRY_PATH);
  test('getNlpComponents returns all', nlpComponents.length === 6);

  const stats = registryIntegration.getNlpStats(TEST_REGISTRY_PATH);
  test('stats totalComponents is 6', stats.totalComponents === 6);
  test('stats has button category', stats.byCategory.button >= 1);
  test('stats has input category', stats.byCategory.input >= 1);

  // Test 8: Component refinement
  console.log('\n--- Test 8: Component Refinement ---');

  const refinedButtonInput = {
    name: 'PrimaryButton',
    description: 'An enhanced primary action button with icon support and loading state',
    category: 'button'
  };

  const refinedResult = generateComponent(refinedButtonInput);
  test('refined button generation succeeds', refinedResult.success === true);

  if (refinedResult.component) {
    const refinedBtn = refinedResult.component;
    const saveResult = saveAndRegister(refinedBtn);

    test('refinement detected', saveResult.updateResult.isRefinement === true);
    test('refinement incremented version', saveResult.updateResult.entry.metadata.version === 2);

    const updatedRegistry = registryIntegration.loadRegistry(TEST_REGISTRY_PATH);
    test('registry still has 6 components (not duplicated)', updatedRegistry.components.length === 6);
  }

  // Test 9: Find operations
  console.log('\n--- Test 9: Find Operations ---');

  const foundByName = registryIntegration.findByName('TextField', TEST_REGISTRY_PATH);
  test('findByName works', foundByName !== null);
  test('findByName returns correct component', foundByName?.name === 'TextField');

  const buttonCategory = registryIntegration.findByCategory('button', TEST_REGISTRY_PATH);
  test('findByCategory works', buttonCategory.length >= 1);
  test('findByCategory returns buttons', buttonCategory.every(c => c.category === 'button'));

  // Test 10: Remove component
  console.log('\n--- Test 10: Remove Component ---');

  const removeResult = registryIntegration.removeFromRegistry('AlertBanner', TEST_REGISTRY_PATH);
  test('remove succeeds', removeResult.removed === true);

  const afterRemove = registryIntegration.loadRegistry(TEST_REGISTRY_PATH);
  test('registry has 5 components after remove', afterRemove.components.length === 5);

  const removedComponent = registryIntegration.findByName('AlertBanner', TEST_REGISTRY_PATH);
  test('removed component not found', removedComponent === null);

  // Test 11: TypeScript interface generation
  console.log('\n--- Test 11: TypeScript Interface Generation ---');

  const btnComponent = generateComponent({
    name: 'TestButton',
    description: 'A test button',
    category: 'button'
  });

  if (btnComponent.component) {
    const tsInterface = propsInference.generateTypeScriptInterface(
      'TestButton',
      btnComponent.component.props
    );
    test('interface generated', typeof tsInterface === 'string');
    test('interface has export', tsInterface.includes('export interface TestButtonProps'));
    test('interface has children', tsInterface.includes('children'));
    test('interface has onClick', tsInterface.includes('onClick'));
  }

  // Test 12: JSDoc generation
  console.log('\n--- Test 12: JSDoc Generation ---');

  if (btnComponent.component) {
    const jsDoc = propsInference.generateJSDoc(btnComponent.component.props);
    test('JSDoc generated', typeof jsDoc === 'string');
    test('JSDoc has opening', jsDoc.startsWith('/**'));
    test('JSDoc has closing', jsDoc.endsWith(' */'));
    test('JSDoc has @param', jsDoc.includes('@param'));
  }

  // Test 13: Error handling - invalid input
  console.log('\n--- Test 13: Error Handling ---');

  const invalidResult = generateComponent({ description: 'Missing name' });
  test('invalid input fails', invalidResult.success === false);
  test('invalid input has errors', invalidResult.errors.length > 0);

  // Test 14: Prompt generation
  console.log('\n--- Test 14: Prompt Generation ---');

  const allPrompts = prompts.getAllPrompts();
  test('getAllPrompts returns object', typeof allPrompts === 'object');
  test('has componentGeneration prompt', typeof allPrompts.componentGeneration === 'string');
  test('has structure prompt', typeof allPrompts.structure === 'string');
  test('componentGeneration prompt is substantial', allPrompts.componentGeneration.length > 100);

  const generationContext = prompts.createGenerationContext({
    name: 'TestComponent',
    description: 'A test component',
    category: 'button'
  });
  test('createGenerationContext returns object', typeof generationContext === 'object');
  test('context has name', generationContext.name === 'TestComponent');
  test('context has category', generationContext.category === 'button');

  // Test 15: Structure generator
  console.log('\n--- Test 15: Structure Generator ---');

  const structure = structureGenerator.generateStructure(
    'A button with icon and text',
    'IconTextButton'
  );
  test('structure has type', structure.type !== undefined);
  test('structure has name', structure.name !== undefined);

  // Cleanup
  cleanup();

  // Print results
  console.log('\n=== Test Results ===');
  console.log(`Passed: ${passed}`);
  console.log(`Failed: ${failed}`);
  console.log(`Total: ${passed + failed}`);

  if (failed === 0) {
    console.log('\n✓ All end-to-end tests passed!');
  } else {
    console.log(`\n✗ ${failed} test(s) failed.`);
  }

  return { passed, failed };
}

// Run if executed directly
if (require.main === module) {
  runTests();
}

module.exports = { runTests, generateComponent };
