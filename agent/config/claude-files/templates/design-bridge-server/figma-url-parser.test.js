/**
 * figma-url-parser.test.js
 * Unit tests for the Figma URL parser
 */

const {
  parseFigmaUrl,
  parseMultipleNodes,
  normalizeNodeId,
  validateFileKey,
  buildFigmaUrl,
  extractFileKey
} = require('./figma-url-parser');

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
  console.log('\n=== Figma URL Parser Tests ===\n');

  // Test normalizeNodeId
  console.log('normalizeNodeId:');
  test('handles colon format', normalizeNodeId('123:456') === '123:456');
  test('handles dash format', normalizeNodeId('123-456') === '123:456');
  test('handles encoded format', normalizeNodeId('123%3A456') === '123:456');
  test('returns null for invalid', normalizeNodeId('invalid') === null);
  test('returns null for empty', normalizeNodeId('') === null);
  test('returns null for null', normalizeNodeId(null) === null);

  // Test parseFigmaUrl - standard file URL
  console.log('\nparseFigmaUrl (standard):');
  const result1 = parseFigmaUrl('https://www.figma.com/file/abc123XYZ/MyDesign?node-id=123:456');
  test('parses standard file URL', result1.valid === true);
  test('extracts fileKey', result1.fileKey === 'abc123XYZ');
  test('extracts nodeId', result1.nodeId === '123:456');
  test('extracts fileName', result1.fileName === 'MyDesign');

  // Test parseFigmaUrl - design URL format
  console.log('\nparseFigmaUrl (design format):');
  const result2 = parseFigmaUrl('https://figma.com/design/xyz789ABC/Button?node-id=1:2');
  test('parses design URL', result2.valid === true);
  test('extracts fileKey from design URL', result2.fileKey === 'xyz789ABC');
  test('extracts nodeId from design URL', result2.nodeId === '1:2');

  // Test parseFigmaUrl - encoded node-id
  console.log('\nparseFigmaUrl (encoded):');
  const result3 = parseFigmaUrl('figma.com/file/abc123ZZ/Name?node-id=123%3A456');
  test('parses encoded node-id', result3.valid === true);
  test('decodes node-id', result3.nodeId === '123:456');

  // Test parseFigmaUrl - dash format node-id
  console.log('\nparseFigmaUrl (dash format):');
  const result4 = parseFigmaUrl('figma.com/file/abc123ZZ/Name?node-id=123-456');
  test('parses dash format', result4.valid === true);
  test('converts dash to colon', result4.nodeId === '123:456');

  // Test parseFigmaUrl - file-level URL
  console.log('\nparseFigmaUrl (file-level):');
  const result5 = parseFigmaUrl('figma.com/file/abc12345/MyFile');
  test('parses file-level URL', result5.valid === true);
  test('isFileLevel is true', result5.isFileLevel === true);
  test('nodeId is null', result5.nodeId === null);

  // Test parseFigmaUrl - minimal URL
  console.log('\nparseFigmaUrl (minimal):');
  const result6 = parseFigmaUrl('figma.com/file/abc12345');
  test('parses minimal URL', result6.valid === true);
  test('fileName is null for minimal', result6.fileName === null);

  // Test parseFigmaUrl - invalid URLs
  console.log('\nparseFigmaUrl (invalid):');
  const invalid1 = parseFigmaUrl('https://google.com');
  test('rejects non-Figma URL', invalid1.valid === false);
  const invalid2 = parseFigmaUrl('');
  test('rejects empty string', invalid2.valid === false);
  const invalid3 = parseFigmaUrl(null);
  test('rejects null', invalid3.valid === false);

  // Test mcpReady format
  console.log('\nmcpReady format:');
  const result7 = parseFigmaUrl('figma.com/file/abc12345/Test?node-id=10:20');
  test('mcpReady has fileKey', result7.mcpReady.fileKey === 'abc12345');
  test('mcpReady has node_ids array', Array.isArray(result7.mcpReady.node_ids));
  test('mcpReady node_ids contains nodeId', result7.mcpReady.node_ids[0] === '10:20');

  // Test validateFileKey
  console.log('\nvalidateFileKey:');
  test('valid long key', validateFileKey('abc123XYZdef456') === true);
  test('valid short key (8 chars)', validateFileKey('abcd1234') === true);
  test('invalid short key (7 chars)', validateFileKey('abcd123') === false);
  test('invalid with special chars', validateFileKey('abc-123') === false);

  // Test buildFigmaUrl
  console.log('\nbuildFigmaUrl:');
  const built1 = buildFigmaUrl('abc123', '1:2', 'MyComponent');
  test('builds URL with nodeId', built1.includes('abc123'));
  test('encodes nodeId in URL', built1.includes('1%3A2'));
  const built2 = buildFigmaUrl('abc123', null, 'Test');
  test('builds URL without nodeId', !built2.includes('node-id'));

  // Test extractFileKey
  console.log('\nextractFileKey:');
  test('extracts from full URL', extractFileKey('figma.com/file/abc12345/Test') === 'abc12345');
  test('returns bare key as-is', extractFileKey('abc12345ZZZ') === 'abc12345ZZZ');
  test('returns null for invalid', extractFileKey('short') === null);

  // Test parseMultipleNodes
  console.log('\nparseMultipleNodes:');
  const multi = parseMultipleNodes('figma.com/file/abc12345/Test?node-id=1:2,3:4,5:6');
  test('parses multiple node IDs', multi.valid === true);
  test('returns nodeIds array', Array.isArray(multi.nodeIds));
  test('has correct count', multi.nodeIds && multi.nodeIds.length === 3);

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
