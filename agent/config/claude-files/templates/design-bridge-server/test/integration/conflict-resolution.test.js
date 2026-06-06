/**
 * Conflict Resolution Integration Test
 * Tests conflict detection and resolution strategies
 */

const IntegrationTestRunner = require('./test-runner');
const TestUtils = require('./test-utils');
const fs = require('fs').promises;
const path = require('path');

const runner = new IntegrationTestRunner();
let testDir;

// ============================================
// TEST: Setup Test Environment
// ============================================
runner.test('Setup Test Environment', async () => {
  testDir = await TestUtils.createFixtureDir('conflict-test-' + Date.now());
  TestUtils.assertTrue(testDir, 'Test directory should be created');
  console.log('   Test dir:', testDir);
});

// ============================================
// TEST: FileConflictDetector Exists
// ============================================
runner.test('FileConflictDetector class exists', async () => {
  const { FileConflictDetector } = require('../../file-conflict-detector');
  TestUtils.assertTrue(FileConflictDetector, 'FileConflictDetector should exist');

  const detector = new FileConflictDetector();
  TestUtils.assertTrue(detector, 'Detector instance should be created');

  console.log('   FileConflictDetector available');
});

// ============================================
// TEST: ConflictType Enum Exists
// ============================================
runner.test('ConflictType enum exists', async () => {
  const { ConflictType } = require('../../file-conflict-detector');
  TestUtils.assertTrue(ConflictType, 'ConflictType should exist');
  TestUtils.assertTrue(ConflictType.NONE !== undefined, 'ConflictType.NONE should exist');
  TestUtils.assertTrue(ConflictType.MODIFIED_LOCALLY !== undefined, 'ConflictType.MODIFIED_LOCALLY should exist');

  console.log('   ConflictType enum available');
});

// ============================================
// TEST: Hash Computation
// ============================================
runner.test('Hash computation works', async () => {
  const { FileConflictDetector } = require('../../file-conflict-detector');
  const detector = new FileConflictDetector();

  const hash1 = detector.computeHash('test content');
  const hash2 = detector.computeHash('test content');
  const hash3 = detector.computeHash('different content');

  TestUtils.assertEqual(hash1, hash2, 'Same content should produce same hash');
  TestUtils.assertTrue(hash1 !== hash3, 'Different content should produce different hash');
  TestUtils.assertEqual(hash1.length, 64, 'Hash should be 64 characters (SHA-256)');

  console.log('   Hash computation valid');
});

// ============================================
// TEST: New File Detection
// ============================================
runner.test('New file detected correctly', async () => {
  const { FileConflictDetector, ConflictType } = require('../../file-conflict-detector');
  const detector = new FileConflictDetector();
  await detector.initialize(testDir);

  const filePath = path.join(testDir, 'NewComponent.tsx');
  const content = 'export const NewComponent = () => <div>New</div>;';

  const result = await detector.detectConflict(filePath, content);

  TestUtils.assertEqual(result.conflictType, ConflictType.NEW_FILE, 'Should detect as new file');

  console.log('   New file detection works');
});

// ============================================
// TEST: Identical Content - No Conflict
// ============================================
runner.test('Identical content has no conflict', async () => {
  const { FileConflictDetector, ConflictType } = require('../../file-conflict-detector');
  const detector = new FileConflictDetector();
  await detector.initialize(testDir);

  const filePath = path.join(testDir, 'Identical.tsx');
  const content = 'export const Identical = () => <div>Same</div>;';

  // Create file and store hash
  await fs.writeFile(filePath, content);
  await detector.storeHash(filePath, content, { framework: 'react' });

  // Check with same content
  const result = await detector.detectConflict(filePath, content);

  TestUtils.assertEqual(result.conflictType, ConflictType.NONE, 'Same content should have no conflict');

  console.log('   Identical content - no conflict');
});

// ============================================
// TEST: Modified Content - Conflict Detected
// ============================================
runner.test('Modified content detected as conflict', async () => {
  const { FileConflictDetector, ConflictType } = require('../../file-conflict-detector');
  const detector = new FileConflictDetector();
  await detector.initialize(testDir);

  const filePath = path.join(testDir, 'Modified.tsx');
  const originalContent = 'export const Modified = () => <div>Original</div>;';
  const modifiedContent = 'export const Modified = () => <div>User Modified</div>;';

  // Create file with original and store hash
  await fs.writeFile(filePath, originalContent);
  await detector.storeHash(filePath, originalContent, { framework: 'react' });

  // Modify file locally
  await fs.writeFile(filePath, modifiedContent);

  // Detect conflict with new generated content
  const result = await detector.detectConflict(filePath, originalContent);

  TestUtils.assertEqual(result.conflictType, ConflictType.MODIFIED_LOCALLY, 'Should detect local modification');

  console.log('   Local modification detected');
});

// ============================================
// TEST: ConflictUserHandler Exists
// ============================================
runner.test('ConflictUserHandler class exists', async () => {
  const { ConflictUserHandler } = require('../../conflict-user-handler');
  TestUtils.assertTrue(ConflictUserHandler, 'ConflictUserHandler should exist');

  const handler = new ConflictUserHandler({ interactive: false });
  TestUtils.assertTrue(handler, 'Handler instance should be created');

  console.log('   ConflictUserHandler available');
});

// ============================================
// TEST: UserChoice Enum Exists
// ============================================
runner.test('UserChoice enum exists', async () => {
  const { UserChoice } = require('../../conflict-user-handler');
  TestUtils.assertTrue(UserChoice, 'UserChoice should exist');
  TestUtils.assertTrue(UserChoice.KEEP_LOCAL !== undefined, 'UserChoice.KEEP_LOCAL should exist');
  TestUtils.assertTrue(UserChoice.USE_GENERATED !== undefined, 'UserChoice.USE_GENERATED should exist');
  TestUtils.assertTrue(UserChoice.SKIP !== undefined, 'UserChoice.SKIP should exist');

  console.log('   UserChoice enum available');
});

// ============================================
// TEST: Non-Interactive Mode Returns Default
// ============================================
runner.test('Non-interactive mode returns default choice', async () => {
  const { ConflictUserHandler, UserChoice } = require('../../conflict-user-handler');
  const handler = new ConflictUserHandler({
    interactive: false,
    defaultChoice: UserChoice.SKIP
  });

  const conflict = {
    filePath: '/test/file.js',
    conflictType: 'MODIFIED_LOCALLY',
    message: 'Test conflict'
  };

  const result = await handler.promptForResolution(conflict);
  TestUtils.assertEqual(result.choice, UserChoice.SKIP, 'Should return default choice');

  console.log('   Non-interactive mode works');
});

// ============================================
// TEST: Cleanup Test Environment
// ============================================
runner.test('Cleanup Test Environment', async () => {
  await TestUtils.cleanupFixture(testDir);
  console.log('   Test directory cleaned up');
});

// Run tests
if (require.main === module) {
  runner.run().then(results => {
    process.exit(results.failed > 0 ? 1 : 0);
  });
}

module.exports = runner;
