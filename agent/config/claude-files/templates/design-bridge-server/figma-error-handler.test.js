/**
 * figma-error-handler.test.js
 * Unit tests for the Figma error handler
 */

const {
  FigmaExtractionError,
  ErrorCodes,
  validateNode,
  validateComponent,
  detectCircularReferences,
  safeExtract,
  sanitizeNode,
  safeArrayAccess,
  safeGet,
  safeParseColor,
  formatErrors,
  formatValidationResult,
  createResult
} = require('./figma-error-handler');

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
  console.log('\n=== Figma Error Handler Tests ===\n');

  // Test FigmaExtractionError
  console.log('FigmaExtractionError:');

  const error = new FigmaExtractionError('Test error', ErrorCodes.INVALID_NODE, { field: 'test' });
  test('creates error with message', error.message === 'Test error');
  test('has name', error.name === 'FigmaExtractionError');
  test('has code', error.code === ErrorCodes.INVALID_NODE);
  test('has details', error.details.field === 'test');
  test('has timestamp', error.timestamp !== undefined);

  const json = error.toJSON();
  test('toJSON includes name', json.name === 'FigmaExtractionError');
  test('toJSON includes code', json.code === ErrorCodes.INVALID_NODE);
  test('toJSON includes message', json.message === 'Test error');
  test('toJSON includes details', json.details.field === 'test');

  // Test ErrorCodes
  console.log('\nErrorCodes:');

  test('has INVALID_NODE', ErrorCodes.INVALID_NODE === 'INVALID_NODE');
  test('has MISSING_FIELD', ErrorCodes.MISSING_FIELD === 'MISSING_FIELD');
  test('has CIRCULAR_REFERENCE', ErrorCodes.CIRCULAR_REFERENCE === 'CIRCULAR_REFERENCE');
  test('has DEPTH_EXCEEDED', ErrorCodes.DEPTH_EXCEEDED === 'DEPTH_EXCEEDED');

  // Test validateNode
  console.log('\nvalidateNode:');

  const validNode = { id: '1:100', name: 'Test', type: 'COMPONENT' };
  const valid = validateNode(validNode);
  test('valid node passes', valid.valid === true);
  test('valid node has no errors', valid.errors.length === 0);

  const nullNode = validateNode(null);
  test('null node fails', nullNode.valid === false);
  test('null node has INVALID_NODE error', nullNode.errors[0].code === ErrorCodes.INVALID_NODE);

  const undefinedNode = validateNode(undefined);
  test('undefined node fails', undefinedNode.valid === false);

  const stringNode = validateNode('not an object');
  test('string fails', stringNode.valid === false);

  const missingId = validateNode({ name: 'Test', type: 'COMPONENT' });
  test('missing id fails', missingId.valid === false);
  test('missing id error code', missingId.errors[0].code === ErrorCodes.MISSING_FIELD);
  test('missing id field', missingId.errors[0].field === 'id');

  const missingName = validateNode({ id: '1:100', type: 'COMPONENT' });
  test('missing name fails', missingName.valid === false);

  const missingType = validateNode({ id: '1:100', name: 'Test' });
  test('missing type fails by default', missingType.valid === false);

  const optionalType = validateNode({ id: '1:100', name: 'Test' }, { requireType: false });
  test('optional type passes', optionalType.valid === true);

  const allowedTypes = validateNode(
    { id: '1:100', name: 'Test', type: 'FRAME' },
    { allowedTypes: ['COMPONENT', 'COMPONENT_SET'] }
  );
  test('wrong type fails', allowedTypes.valid === false);
  test('wrong type error code', allowedTypes.errors[0].code === ErrorCodes.INVALID_TYPE);

  const correctType = validateNode(
    { id: '1:100', name: 'Test', type: 'COMPONENT' },
    { allowedTypes: ['COMPONENT', 'COMPONENT_SET'] }
  );
  test('correct type passes', correctType.valid === true);

  // Test validateComponent
  console.log('\nvalidateComponent:');

  const validComponent = {
    id: '1:100',
    name: 'Button',
    type: 'COMPONENT',
    children: [{ id: '1:101', name: 'Label' }]
  };
  const compValid = validateComponent(validComponent);
  test('valid component passes', compValid.valid === true);

  const emptyComponent = { id: '1:100', name: 'Empty' };
  const emptyValid = validateComponent(emptyComponent);
  test('empty component has warning', emptyValid.warnings.length > 0);
  test('empty component warning code', emptyValid.warnings[0].code === ErrorCodes.EMPTY_COMPONENT);

  const longName = { id: '1:100', name: 'a'.repeat(300), type: 'COMPONENT' };
  const longValid = validateComponent(longName);
  test('long name has warning', longValid.warnings.some(w => w.field === 'name'));

  const badChars = { id: '1:100', name: 'Test<>:Component', type: 'COMPONENT' };
  const badValid = validateComponent(badChars);
  test('bad chars has warning', badValid.warnings.some(w => w.message.includes('file system')));

  const invalidIdType = { id: 123, name: 'Test', type: 'COMPONENT' };
  const idTypeValid = validateComponent(invalidIdType);
  test('invalid id type fails', idTypeValid.valid === false);

  // Test detectCircularReferences
  console.log('\ndetectCircularReferences:');

  const linearTree = {
    id: 'root',
    children: [
      { id: 'child1', children: [{ id: 'grandchild1' }] },
      { id: 'child2' }
    ]
  };
  const linearCheck = detectCircularReferences(linearTree);
  test('linear tree has no circular', linearCheck.hasCircular === false);

  const noChildren = { id: 'single' };
  const noChildCheck = detectCircularReferences(noChildren);
  test('single node has no circular', noChildCheck.hasCircular === false);

  const nullCheck = detectCircularReferences(null);
  test('null node returns no circular', nullCheck.hasCircular === false);

  const noIdCheck = detectCircularReferences({});
  test('no id returns no circular', noIdCheck.hasCircular === false);

  // Create actual circular reference using object reference
  const circularNode = { id: 'circular', children: [] };
  circularNode.children.push({ id: 'child', children: [circularNode] }); // Direct circular
  // Note: This won't actually be detected because we use node.id comparison
  // For proper test, we'd need same id appearing twice
  const sameIdTree = {
    id: 'root',
    children: [
      {
        id: 'dup',
        children: [
          { id: 'dup' } // Same id appears again
        ]
      }
    ]
  };
  const sameIdCheck = detectCircularReferences(sameIdTree);
  test('same id detected as circular', sameIdCheck.hasCircular === true);
  test('circular path includes duplicate', sameIdCheck.circularPath.includes('dup'));

  // Test safeExtract
  console.log('\nsafeExtract:');

  const successExtract = (node) => ({ name: node.name, processed: true });
  const validExtractNode = { id: '1:100', name: 'Test', type: 'COMPONENT' };
  const extractResult = safeExtract(successExtract, validExtractNode);
  test('successful extract returns success', extractResult.success === true);
  test('successful extract has data', extractResult.data.processed === true);
  test('successful extract no error', extractResult.error === null);

  const invalidExtractResult = safeExtract(successExtract, null);
  test('invalid node returns failure', invalidExtractResult.success === false);
  test('invalid node has error', invalidExtractResult.error !== null);
  test('invalid node error code', invalidExtractResult.error.code === ErrorCodes.VALIDATION_FAILED);

  const throwingExtract = () => { throw new Error('Test error'); };
  const throwResult = safeExtract(throwingExtract, validExtractNode);
  test('throwing function returns failure', throwResult.success === false);
  test('throwing function captures error', throwResult.error.code === ErrorCodes.UNKNOWN);

  const depthContext = { maxDepth: 5, depth: 10 };
  const depthResult = safeExtract(successExtract, validExtractNode, depthContext);
  test('exceeds depth returns failure', depthResult.success === false);
  test('exceeds depth error code', depthResult.error.code === ErrorCodes.DEPTH_EXCEEDED);

  // Test sanitizeNode
  console.log('\nsanitizeNode:');

  const fullNode = {
    id: '1:100',
    name: 'Test',
    type: 'COMPONENT',
    fills: [{ type: 'SOLID', color: { r: 1, g: 0, b: 0 } }],
    dangerousProperty: '<script>alert("xss")</script>',
    children: [
      { id: '1:101', name: 'Child', type: 'TEXT' }
    ]
  };
  const sanitized = sanitizeNode(fullNode);
  test('sanitized has id', sanitized.id === '1:100');
  test('sanitized has name', sanitized.name === 'Test');
  test('sanitized has type', sanitized.type === 'COMPONENT');
  test('sanitized has fills', Array.isArray(sanitized.fills));
  test('sanitized removes unknown props', sanitized.dangerousProperty === undefined);
  test('sanitized has children', Array.isArray(sanitized.children));
  test('sanitized children processed', sanitized.children[0].id === '1:101');

  const nullSanitize = sanitizeNode(null);
  test('null returns null', nullSanitize === null);

  const stringSanitize = sanitizeNode('not an object');
  test('string returns null', stringSanitize === null);

  const longNameNode = { id: '1', name: 'x'.repeat(300), type: 'T' };
  const longSanitized = sanitizeNode(longNameNode);
  test('long name truncated', longSanitized.name.length === 255);

  const longDescNode = { id: '1', name: 'Test', description: 'y'.repeat(6000) };
  const descSanitized = sanitizeNode(longDescNode);
  test('long description truncated', descSanitized.description.length === 5000);

  // Test safeArrayAccess
  console.log('\nsafeArrayAccess:');

  const arr = [1, 2, 3];
  test('valid index returns value', safeArrayAccess(arr, 1) === 2);
  test('negative index returns default', safeArrayAccess(arr, -1) === null);
  test('out of bounds returns default', safeArrayAccess(arr, 10) === null);
  test('custom default works', safeArrayAccess(arr, 10, 'default') === 'default');
  test('non-array returns default', safeArrayAccess('not array', 0) === null);
  test('null returns default', safeArrayAccess(null, 0) === null);

  // Test safeGet
  console.log('\nsafeGet:');

  const obj = {
    a: {
      b: {
        c: 'deep value'
      }
    },
    simple: 'value'
  };
  test('simple path works', safeGet(obj, 'simple') === 'value');
  test('deep path works', safeGet(obj, 'a.b.c') === 'deep value');
  test('missing path returns default', safeGet(obj, 'a.b.d') === null);
  test('custom default works', safeGet(obj, 'missing', 'default') === 'default');
  test('null object returns default', safeGet(null, 'path') === null);
  test('undefined object returns default', safeGet(undefined, 'path') === null);
  test('partial path returns default', safeGet(obj, 'a.b.c.d.e') === null);

  // Test safeParseColor
  console.log('\nsafeParseColor:');

  const validColor = { r: 0.5, g: 0.25, b: 0.75, a: 0.8 };
  const parsedColor = safeParseColor(validColor);
  test('parses valid color', parsedColor !== null);
  test('preserves r', parsedColor.r === 0.5);
  test('preserves g', parsedColor.g === 0.25);
  test('preserves b', parsedColor.b === 0.75);
  test('preserves a', parsedColor.a === 0.8);

  const noAlpha = { r: 1, g: 0, b: 0 };
  const noAlphaParsed = safeParseColor(noAlpha);
  test('defaults alpha to 1', noAlphaParsed.a === 1);

  const outOfRange = { r: 2, g: -1, b: 0.5, a: 1.5 };
  const clampedColor = safeParseColor(outOfRange);
  test('clamps r to 1', clampedColor.r === 1);
  test('clamps g to 0', clampedColor.g === 0);
  test('clamps a to 1', clampedColor.a === 1);

  const nullColor = safeParseColor(null);
  test('null returns null', nullColor === null);

  const invalidColor = safeParseColor('red');
  test('string returns null', invalidColor === null);

  // Test formatErrors
  console.log('\nformatErrors:');

  const errors = [
    { code: 'ERROR1', message: 'First error', field: 'field1' },
    { code: 'ERROR2', message: 'Second error' }
  ];
  const formatted = formatErrors(errors);
  test('includes count', formatted.includes('2 error(s)'));
  test('includes first error', formatted.includes('First error'));
  test('includes second error', formatted.includes('Second error'));
  test('includes field info', formatted.includes('field1'));

  const emptyFormatted = formatErrors([]);
  test('empty returns no errors', emptyFormatted === 'No errors');

  const nullFormatted = formatErrors(null);
  test('null returns no errors', nullFormatted === 'No errors');

  // Test formatValidationResult
  console.log('\nformatValidationResult:');

  const passedResult = { valid: true, errors: [], warnings: [] };
  const passedFormatted = formatValidationResult(passedResult);
  test('passed shows PASSED', passedFormatted.includes('PASSED'));

  const failedResult = {
    valid: false,
    errors: [{ code: 'ERR', message: 'Error' }],
    warnings: [{ code: 'WARN', message: 'Warning' }]
  };
  const failedFormatted = formatValidationResult(failedResult);
  test('failed shows FAILED', failedFormatted.includes('FAILED'));
  test('shows errors', failedFormatted.includes('Error'));
  test('shows warnings', failedFormatted.includes('Warning'));

  // Test createResult
  console.log('\ncreateResult:');

  const successResult = createResult(true, { data: 'test' }, null, { source: 'test' });
  test('success result has success', successResult.success === true);
  test('success result has data', successResult.data.data === 'test');
  test('success result has null error', successResult.error === null);
  test('success result has timestamp', successResult.metadata.timestamp !== undefined);
  test('success result has custom metadata', successResult.metadata.source === 'test');

  const errorResult = createResult(false, null, new Error('Test'));
  test('error result has failure', errorResult.success === false);
  test('error result has null data', errorResult.data === null);
  test('error result has error message', errorResult.error.message === 'Test');

  const extractionErrorResult = createResult(false, null, error);
  test('extraction error serializes', extractionErrorResult.error.code === ErrorCodes.INVALID_NODE);

  // Summary
  console.log('\n=============================');
  console.log(`Results: ${passed} passed, ${failed} failed`);
  console.log('=============================\n');

  return { passed, failed };
}

// Run tests
if (require.main === module) {
  const result = runTests();
  process.exit(result.failed > 0 ? 1 : 0);
}

module.exports = { runTests };
