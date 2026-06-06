/**
 * Story Hash Registry - Unit Tests
 * @phase Option C - Sprint 1.13
 */

const path = require('path');
const fs = require('fs').promises;
const os = require('os');

// Import the module under test
const {
  StoryHashRegistry,
  loadRegistry,
  isStoryModified,
  registerStory,
  REGISTRY_FILENAME,
  REGISTRY_VERSION
} = require('./story-hash-registry');

// Test helpers
let testDir;
let testProjectPath;

async function createTestProject() {
  testDir = await fs.mkdtemp(path.join(os.tmpdir(), 'story-hash-test-'));
  testProjectPath = testDir;
  await fs.mkdir(path.join(testProjectPath, '.design'), { recursive: true });
  return testProjectPath;
}

async function cleanupTestProject() {
  if (testDir) {
    await fs.rm(testDir, { recursive: true, force: true });
    testDir = null;
    testProjectPath = null;
  }
}

async function createTestStory(name, content) {
  const storyPath = path.join(testProjectPath, '.design', 'extracted-code', 'react', `${name}.stories.tsx`);
  await fs.mkdir(path.dirname(storyPath), { recursive: true });
  await fs.writeFile(storyPath, content, 'utf8');
  return storyPath;
}

// Test suite
const tests = [];
let passed = 0;
let failed = 0;

function test(name, fn) {
  tests.push({ name, fn });
}

async function runTests() {
  console.log('\n=== Story Hash Registry Unit Tests ===\n');

  for (const { name, fn } of tests) {
    try {
      await createTestProject();
      await fn();
      console.log(`✓ ${name}`);
      passed++;
    } catch (error) {
      console.log(`✗ ${name}`);
      console.log(`  Error: ${error.message}`);
      failed++;
    } finally {
      await cleanupTestProject();
    }
  }

  console.log(`\n=== Results: ${passed} passed, ${failed} failed ===\n`);
  return { passed, failed };
}

// ============================================================================
// Test Cases
// ============================================================================

test('StoryHashRegistry - creates new registry if none exists', async () => {
  const registry = new StoryHashRegistry(testProjectPath);
  await registry.load();

  if (!registry.registry) throw new Error('Registry not initialized');
  if (registry.registry.version !== REGISTRY_VERSION) throw new Error('Invalid version');
  if (typeof registry.registry.stories !== 'object') throw new Error('Stories not initialized');
});

test('StoryHashRegistry - registerStory creates entry', async () => {
  const registry = new StoryHashRegistry(testProjectPath);
  const storyPath = path.join(testProjectPath, 'Button.stories.tsx');
  const content = 'export default { title: "Button" }';

  const hash = await registry.registerStory(storyPath, content);

  if (!hash) throw new Error('No hash returned');
  if (hash.length !== 64) throw new Error('Invalid hash length (expected SHA-256)');

  const entry = await registry.getEntry(storyPath);
  if (!entry) throw new Error('Entry not found after registration');
  if (entry.generatedHash !== hash) throw new Error('Hash mismatch in entry');
});

test('StoryHashRegistry - checkStoryModified returns false for unmodified', async () => {
  const registry = new StoryHashRegistry(testProjectPath);
  const content = 'export default { title: "Card" }';
  const storyPath = await createTestStory('Card', content);

  // Register the story
  await registry.registerStory(storyPath, content);

  // Check modification (should be false - content matches)
  const result = await registry.checkStoryModified(storyPath);

  if (result.isModified) throw new Error('Story incorrectly marked as modified');
  if (result.reason !== 'unchanged') throw new Error(`Wrong reason: ${result.reason}`);
});

test('StoryHashRegistry - checkStoryModified returns true after file edit', async () => {
  const registry = new StoryHashRegistry(testProjectPath);
  const originalContent = 'export default { title: "Modal" }';
  const storyPath = await createTestStory('Modal', originalContent);

  // Register the story
  await registry.registerStory(storyPath, originalContent);

  // Modify the file
  const modifiedContent = 'export default { title: "Modal", description: "User added" }';
  await fs.writeFile(storyPath, modifiedContent, 'utf8');

  // Check modification (should be true - content changed)
  const result = await registry.checkStoryModified(storyPath);

  if (!result.isModified) throw new Error('Story not detected as modified');
  if (result.reason !== 'content-changed') throw new Error(`Wrong reason: ${result.reason}`);
});

test('StoryHashRegistry - checkStoryModified returns not-registered for unknown story', async () => {
  const registry = new StoryHashRegistry(testProjectPath);
  const unknownPath = path.join(testProjectPath, 'Unknown.stories.tsx');

  // Check without registering
  const result = await registry.checkStoryModified(unknownPath);

  if (!result.isModified) throw new Error('Unknown story should be treated as modified');
  if (result.reason !== 'not-registered') throw new Error(`Wrong reason: ${result.reason}`);
});

test('StoryHashRegistry - registry persists across loads', async () => {
  const content = 'export default { title: "Tooltip" }';
  const storyPath = path.join(testProjectPath, 'Tooltip.stories.tsx');

  // Create and save registry
  const registry1 = new StoryHashRegistry(testProjectPath);
  await registry1.registerStory(storyPath, content);

  // Load registry again
  const registry2 = new StoryHashRegistry(testProjectPath);
  await registry2.load();

  const entry = await registry2.getEntry(storyPath);
  if (!entry) throw new Error('Entry not persisted');
  if (!entry.generatedHash) throw new Error('Hash not persisted');
});

test('StoryHashRegistry - clearStory removes entry', async () => {
  const registry = new StoryHashRegistry(testProjectPath);
  const storyPath = path.join(testProjectPath, 'Alert.stories.tsx');

  // Register and then clear
  await registry.registerStory(storyPath, 'content');
  const removed = await registry.clearStory(storyPath);

  if (!removed) throw new Error('Clear returned false');
  if (await registry.hasStory(storyPath)) throw new Error('Story still exists after clear');
});

test('StoryHashRegistry - hasStory returns correct boolean', async () => {
  const registry = new StoryHashRegistry(testProjectPath);
  const storyPath = path.join(testProjectPath, 'Badge.stories.tsx');

  // Before registration
  if (await registry.hasStory(storyPath)) throw new Error('hasStory true before registration');

  // After registration
  await registry.registerStory(storyPath, 'content');
  if (!(await registry.hasStory(storyPath))) throw new Error('hasStory false after registration');
});

test('StoryHashRegistry - listStories returns all entries', async () => {
  const registry = new StoryHashRegistry(testProjectPath);

  // Register multiple stories
  await registry.registerStory(path.join(testProjectPath, 'A.stories.tsx'), 'a');
  await registry.registerStory(path.join(testProjectPath, 'B.stories.tsx'), 'b');
  await registry.registerStory(path.join(testProjectPath, 'C.stories.tsx'), 'c');

  const stories = await registry.listStories();

  if (stories.length !== 3) throw new Error(`Expected 3 stories, got ${stories.length}`);
});

test('StoryHashRegistry - getStoriesByFramework filters correctly', async () => {
  const registry = new StoryHashRegistry(testProjectPath);

  // Register stories with different frameworks
  await registry.registerStory(path.join(testProjectPath, 'A.stories.tsx'), 'a', { framework: 'react' });
  await registry.registerStory(path.join(testProjectPath, 'B.stories.tsx'), 'b', { framework: 'vue' });
  await registry.registerStory(path.join(testProjectPath, 'C.stories.tsx'), 'c', { framework: 'react' });

  const reactStories = await registry.getStoriesByFramework('react');
  const vueStories = await registry.getStoriesByFramework('vue');

  if (reactStories.length !== 2) throw new Error(`Expected 2 react stories, got ${reactStories.length}`);
  if (vueStories.length !== 1) throw new Error(`Expected 1 vue story, got ${vueStories.length}`);
});

test('StoryHashRegistry - getStats returns correct counts', async () => {
  const registry = new StoryHashRegistry(testProjectPath);

  await registry.registerStory(path.join(testProjectPath, 'A.stories.tsx'), 'a', { framework: 'react' });
  await registry.registerStory(path.join(testProjectPath, 'B.stories.tsx'), 'b', { framework: 'react' });

  const stats = await registry.getStats();

  if (stats.totalStories !== 2) throw new Error(`Expected 2 total, got ${stats.totalStories}`);
  if (stats.byFramework.react !== 2) throw new Error(`Expected 2 react, got ${stats.byFramework.react}`);
  if (stats.version !== REGISTRY_VERSION) throw new Error('Version mismatch');
});

test('Utility: loadRegistry returns usable registry', async () => {
  const registry = await loadRegistry(testProjectPath);

  if (!(registry instanceof StoryHashRegistry)) throw new Error('Wrong type returned');
  if (!registry.registry) throw new Error('Registry not loaded');
});

test('Utility: isStoryModified works standalone', async () => {
  const content = 'export default {}';
  const storyPath = await createTestStory('Test', content);

  // Register first
  await registerStory(testProjectPath, storyPath, content);

  // Check unmodified
  let modified = await isStoryModified(testProjectPath, storyPath);
  if (modified) throw new Error('Should not be modified');

  // Modify file
  await fs.writeFile(storyPath, 'modified content', 'utf8');

  // Check modified
  modified = await isStoryModified(testProjectPath, storyPath);
  if (!modified) throw new Error('Should be modified');
});

test('StoryHashRegistry - handles relative and absolute paths', async () => {
  const registry = new StoryHashRegistry(testProjectPath);
  const relPath = 'components/Button.stories.tsx';
  const absPath = path.join(testProjectPath, relPath);

  // Register with absolute path
  await registry.registerStory(absPath, 'content');

  // Check with relative path
  const hasAbs = await registry.hasStory(absPath);
  const hasRel = await registry.hasStory(relPath);

  if (!hasAbs) throw new Error('Absolute path not found');
  if (!hasRel) throw new Error('Relative path not found');
});

// Run tests if executed directly
if (require.main === module) {
  runTests()
    .then(({ passed, failed }) => process.exit(failed > 0 ? 1 : 0))
    .catch(error => {
      console.error('Test runner error:', error);
      process.exit(1);
    });
}

module.exports = { runTests };
