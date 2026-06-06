/**
 * cli-extract.test.js
 * Tests for the CLI extract command
 */

const fs = require('fs');
const path = require('path');

// Import CLI module
const extractCmd = require('../cli/commands/extract');

let passed = 0;
let failed = 0;

// Test output directory
const TEST_DIR = path.join(__dirname, '.test-cli-output');

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

function runTests() {
  console.log('\n=== CLI Extract Command Tests ===\n');

  setup();

  // Test 1: parseArgs - basic options
  console.log('--- Test 1: parseArgs basic options ---');

  const args1 = parseArgs(['--help']);
  test('parseArgs recognizes --help', args1.help === true);

  const args2 = parseArgs(['-h']);
  test('parseArgs recognizes -h', args2.help === true);

  const args3 = parseArgs(['-i']);
  test('parseArgs recognizes -i (interactive)', args3.interactive === true);

  const args4 = parseArgs(['--interactive']);
  test('parseArgs recognizes --interactive', args4.interactive === true);

  const args5 = parseArgs(['--history']);
  test('parseArgs recognizes --history', args5.history === true);

  // Test 2: parseArgs - method flags
  console.log('\n--- Test 2: parseArgs method flags ---');

  const args6 = parseArgs(['--url=https://figma.com/file/abc']);
  test('parseArgs sets method to figma-mcp for --url', args6.method === 'figma-mcp');
  test('parseArgs stores URL', args6.url === 'https://figma.com/file/abc');

  const args7 = parseArgs(['--component=button']);
  test('parseArgs sets method to shadcn for --component', args7.method === 'shadcn');
  test('parseArgs stores component name', args7.component === 'button');

  const args8 = parseArgs(['--describe=A blue button']);
  test('parseArgs sets method to nlp-prompt for --describe', args8.method === 'nlp-prompt');
  test('parseArgs stores description', args8.describe === 'A blue button');

  const args9 = parseArgs(['--spec=./component.json']);
  test('parseArgs sets method to manual for --spec', args9.method === 'manual');
  test('parseArgs stores spec path', args9.spec === './component.json');

  // Test 3: parseArgs - general options
  console.log('\n--- Test 3: parseArgs general options ---');

  const args10 = parseArgs(['--framework=vue']);
  test('parseArgs stores framework', args10.framework === 'vue');

  const args11 = parseArgs(['--output=./output']);
  test('parseArgs stores outputDir', args11.outputDir === './output');

  const args12 = parseArgs(['--story']);
  test('parseArgs recognizes --story', args12.generateStory === true);

  const args13 = parseArgs(['--no-code']);
  test('parseArgs recognizes --no-code', args13.generateCode === false);

  const args14 = parseArgs(['--re-extract=Button']);
  test('parseArgs stores reExtract', args14.reExtract === 'Button');

  // Test 4: parseArgs - positional target
  console.log('\n--- Test 4: parseArgs positional target ---');

  const args15 = parseArgs(['button']);
  test('parseArgs stores positional as target', args15.target === 'button');

  const args16 = parseArgs(['--framework=react', 'card']);
  test('parseArgs handles mixed args', args16.framework === 'react' && args16.target === 'card');

  // Test 5: parseArgs - explicit method override
  console.log('\n--- Test 5: parseArgs method override ---');

  const args17 = parseArgs(['--method=nlp-prompt', '--component=button']);
  test('explicit method overrides implicit', args17.method === 'nlp-prompt');

  // Test 6: parseArgs defaults
  console.log('\n--- Test 6: parseArgs defaults ---');

  const args18 = parseArgs([]);
  test('default framework is react', args18.framework === 'react');
  test('default outputDir is .design', args18.outputDir === '.design');
  test('default generateStory is false', args18.generateStory === false);
  test('default generateCode is true', args18.generateCode === true);
  test('default help is false', args18.help === false);
  test('default interactive is false', args18.interactive === false);
  test('default history is false', args18.history === false);

  // Test 7: showHelp
  console.log('\n--- Test 7: showHelp ---');

  // Capture console output
  const originalLog = console.log;
  let helpOutput = '';
  console.log = (msg) => { helpOutput += msg + '\n'; };

  extractCmd.showHelp();

  console.log = originalLog;

  test('showHelp outputs content', helpOutput.length > 100);
  test('showHelp includes USAGE', helpOutput.includes('USAGE:'));
  test('showHelp includes METHODS', helpOutput.includes('METHODS:'));
  test('showHelp includes EXAMPLES', helpOutput.includes('EXAMPLES:'));
  test('showHelp mentions --url', helpOutput.includes('--url'));
  test('showHelp mentions --component', helpOutput.includes('--component'));
  test('showHelp mentions --describe', helpOutput.includes('--describe'));
  test('showHelp mentions --spec', helpOutput.includes('--spec'));

  // Test 8: showHistory - empty
  console.log('\n--- Test 8: showHistory empty ---');

  let historyOutput = '';
  console.log = (msg) => { historyOutput += msg + '\n'; };

  extractCmd.showHistory(TEST_DIR);

  console.log = originalLog;

  test('showHistory handles missing file', historyOutput.includes('No extraction history found'));

  // Test 9: showHistory - with data
  console.log('\n--- Test 9: showHistory with data ---');

  const historyPath = path.join(TEST_DIR, '.design', 'extraction-history.json');
  const testHistory = {
    extractions: [
      {
        timestamp: new Date().toISOString(),
        method: 'nlp-prompt',
        component: 'TestButton',
        success: true,
        duration: 150
      },
      {
        timestamp: new Date().toISOString(),
        method: 'shadcn',
        component: 'Card',
        success: true,
        duration: 200
      }
    ]
  };
  fs.writeFileSync(historyPath, JSON.stringify(testHistory, null, 2));

  historyOutput = '';
  console.log = (msg) => { historyOutput += msg + '\n'; };

  extractCmd.showHistory(TEST_DIR);

  console.log = originalLog;

  test('showHistory shows header', historyOutput.includes('Extraction History'));
  test('showHistory shows method', historyOutput.includes('nlp-prompt'));
  test('showHistory shows component', historyOutput.includes('TestButton'));
  test('showHistory shows duration', historyOutput.includes('ms'));

  // Test 10: logToHistory
  console.log('\n--- Test 10: logToHistory ---');

  const logTestDir = path.join(TEST_DIR, 'log-test');
  fs.mkdirSync(path.join(logTestDir, '.design'), { recursive: true });

  const testOutput = {
    timestamp: new Date().toISOString(),
    method: 'nlp-prompt',
    success: true,
    component: { name: 'LoggedComponent' },
    metadata: { duration: 100 }
  };

  extractCmd.logToHistory(logTestDir, testOutput);

  const loggedHistory = JSON.parse(fs.readFileSync(
    path.join(logTestDir, '.design', 'extraction-history.json'), 'utf8'
  ));

  test('logToHistory creates history file', loggedHistory !== null);
  test('logToHistory adds entry', loggedHistory.extractions.length === 1);
  test('logToHistory stores component name', loggedHistory.extractions[0].component === 'LoggedComponent');
  test('logToHistory stores method', loggedHistory.extractions[0].method === 'nlp-prompt');
  test('logToHistory stores success', loggedHistory.extractions[0].success === true);

  // Test 11: logToHistory - appends
  console.log('\n--- Test 11: logToHistory appends ---');

  const testOutput2 = {
    timestamp: new Date().toISOString(),
    method: 'shadcn',
    success: true,
    component: { name: 'SecondComponent' },
    metadata: { duration: 200 }
  };

  extractCmd.logToHistory(logTestDir, testOutput2);

  const updatedHistory = JSON.parse(fs.readFileSync(
    path.join(logTestDir, '.design', 'extraction-history.json'), 'utf8'
  ));

  test('logToHistory appends entry', updatedHistory.extractions.length === 2);
  test('logToHistory preserves first entry', updatedHistory.extractions[0].component === 'LoggedComponent');
  test('logToHistory adds second entry', updatedHistory.extractions[1].component === 'SecondComponent');

  // Test 12: displayResults - success
  console.log('\n--- Test 12: displayResults success ---');

  const successOutput = {
    success: true,
    method: 'nlp-prompt',
    timestamp: new Date().toISOString(),
    component: {
      name: 'SuccessButton',
      id: 'nlp-success-button-123',
      type: 'COMPONENT',
      source: { type: 'nlp-prompt' },
      paths: {
        component: '.design/components/SuccessButton.json'
      }
    },
    warnings: [],
    errors: [],
    metadata: { duration: 150 }
  };

  let displayOutput = '';
  console.log = (msg) => { displayOutput += msg + '\n'; };

  extractCmd.displayResults(successOutput);

  console.log = originalLog;

  test('displayResults shows success', displayOutput.includes('✓ Extraction successful'));
  test('displayResults shows component name', displayOutput.includes('SuccessButton'));
  test('displayResults shows ID', displayOutput.includes('nlp-success-button-123'));
  test('displayResults shows type', displayOutput.includes('COMPONENT'));
  test('displayResults shows source type', displayOutput.includes('nlp-prompt'));
  test('displayResults shows duration', displayOutput.includes('150ms'));

  // Test 13: displayResults - failure
  console.log('\n--- Test 13: displayResults failure ---');

  const failOutput = {
    success: false,
    method: 'figma-mcp',
    timestamp: new Date().toISOString(),
    component: null,
    warnings: ['Some warning'],
    errors: ['Failed to connect to Figma'],
    metadata: { duration: 50 }
  };

  displayOutput = '';
  console.log = (msg) => { displayOutput += msg + '\n'; };

  extractCmd.displayResults(failOutput);

  console.log = originalLog;

  test('displayResults shows failure', displayOutput.includes('✗ Extraction failed'));
  test('displayResults shows warning', displayOutput.includes('Some warning'));
  test('displayResults shows error', displayOutput.includes('Failed to connect'));

  // Test 14: getExtractor
  console.log('\n--- Test 14: getExtractor ---');

  const nlpExtractor = extractCmd.getExtractor('nlp-prompt', TEST_DIR);
  test('getExtractor returns object for nlp-prompt', nlpExtractor !== null);
  test('getExtractor has extract method', typeof nlpExtractor.extract === 'function');

  const unknownExtractor = extractCmd.getExtractor('unknown-method', TEST_DIR);
  test('getExtractor returns null for unknown method', unknownExtractor === null);

  // Test 15: Module exports
  console.log('\n--- Test 15: Module exports ---');

  test('exports parseArgs', typeof extractCmd.parseArgs === 'function');
  test('exports executeExtraction', typeof extractCmd.executeExtraction === 'function');
  test('exports showHelp', typeof extractCmd.showHelp === 'function');
  test('exports showHistory', typeof extractCmd.showHistory === 'function');
  test('exports runInteractive', typeof extractCmd.runInteractive === 'function');
  test('exports handleReExtract', typeof extractCmd.handleReExtract === 'function');
  test('exports logToHistory', typeof extractCmd.logToHistory === 'function');
  test('exports displayResults', typeof extractCmd.displayResults === 'function');
  test('exports getExtractor', typeof extractCmd.getExtractor === 'function');

  // Cleanup
  cleanup();

  // Print results
  console.log('\n=== Test Results ===');
  console.log(`Passed: ${passed}`);
  console.log(`Failed: ${failed}`);
  console.log(`Total: ${passed + failed}`);

  if (failed === 0) {
    console.log('\n✓ All CLI extract tests passed!');
  } else {
    console.log(`\n✗ ${failed} test(s) failed.`);
  }

  return { passed, failed };
}

// Helper function to call parseArgs
function parseArgs(args) {
  return extractCmd.parseArgs(args);
}

// Run if executed directly
if (require.main === module) {
  runTests();
}

module.exports = { runTests };
