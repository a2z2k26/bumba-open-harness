#!/usr/bin/env node
/**
 * Phase 6 Sprint 6.9: End-to-End Test - Full Pipeline
 *
 * Tests the complete design-to-code pipeline using all existing infrastructure:
 * - AutoRegistrar (uses ContentHasher, registry-reader)
 * - TransformStateUpdater (uses ContentHasher, StoryHashRegistry)
 * - SyncCascade (uses DiffEngine, SnapshotManager, ConflictResolver)
 *
 * This verifies that new two-state modules properly integrate with
 * existing Design Bridge infrastructure.
 */

const path = require('path');
const fs = require('fs');
const os = require('os');

// Test results tracking
const results = { passed: 0, failed: 0, tests: [] };

function check(name, condition) {
  if (condition) {
    results.passed++;
    results.tests.push({ name, status: 'passed' });
    console.log(`  ✅ ${name}`);
  } else {
    results.failed++;
    results.tests.push({ name, status: 'failed' });
    console.log(`  ❌ ${name}`);
  }
}

function createTestDirectory() {
  const testDir = path.join(os.tmpdir(), `e2e-pipeline-test-${Date.now()}`);
  fs.mkdirSync(path.join(testDir, '.design', 'extracted-code', 'react'), { recursive: true });
  fs.mkdirSync(path.join(testDir, '.design', 'stories'), { recursive: true });
  fs.mkdirSync(path.join(testDir, '.design', 'components'), { recursive: true });
  fs.mkdirSync(path.join(testDir, '.design', 'snapshots'), { recursive: true });
  return testDir;
}

function cleanupTestDirectory(testDir) {
  try {
    fs.rmSync(testDir, { recursive: true, force: true });
  } catch (e) {}
}

console.log('\n' + '═'.repeat(60));
console.log('  E2E TEST: Full Design-to-Code Pipeline');
console.log('  (Verifies existing infrastructure integration)');
console.log('═'.repeat(60) + '\n');

async function testFullPipeline() {
  // Import all required modules
  const { AutoRegistrar } = require('./auto-registrar');
  const { TransformStateUpdater } = require('./transform-state-updater');
  const { SyncCascade, CASCADE_EVENTS } = require('./sync-cascade');
  const { readComponentRegistry, writeComponentRegistry, invalidateCache, CURRENT_SCHEMA_VERSION } = require('./registry-reader');
  const { hashFile, hasFileChanged } = require('./content-hasher');
  const { StoryHashRegistry } = require('./story-hash-registry');

  const testDir = createTestDirectory();
  console.log(`Test directory: ${testDir}\n`);

  try {
    // ══════════════════════════════════════════════════════════════════
    // PHASE 1: Verify Existing Infrastructure Available
    // ══════════════════════════════════════════════════════════════════
    console.log('PHASE 1: Verify Existing Infrastructure\n');

    check('ContentHasher hashFile available', typeof hashFile === 'function');
    check('ContentHasher hasFileChanged available', typeof hasFileChanged === 'function');
    check('StoryHashRegistry available', typeof StoryHashRegistry === 'function');
    check('readComponentRegistry available', typeof readComponentRegistry === 'function');
    check('writeComponentRegistry available', typeof writeComponentRegistry === 'function');
    check('Current schema version is 3.0.0', CURRENT_SCHEMA_VERSION === '3.0.0');

    // ══════════════════════════════════════════════════════════════════
    // PHASE 2: Import from Multiple Sources
    // ══════════════════════════════════════════════════════════════════
    console.log('\nPHASE 2: Import Components from Multiple Sources\n');

    const registrar = new AutoRegistrar({ projectPath: testDir });

    // Import from Figma Plugin
    const figmaPluginResult = await registrar.registerComponent(
      {
        name: 'PrimaryButton',
        type: 'COMPONENT',
        props: { label: { type: 'string' }, variant: { type: 'string' } }
      },
      { type: 'figma-plugin', nodeId: '1:234' }
    );

    check('Figma Plugin import succeeded', figmaPluginResult.success === true);
    check('Figma Plugin component has ID', figmaPluginResult.id !== undefined);
    check('Figma Plugin state is imported', figmaPluginResult.entry?.transformation?.state === 'imported');
    const primaryButtonId = figmaPluginResult.id;

    // Import from Figma MCP
    const figmaMcpResult = await registrar.registerComponent(
      {
        name: 'IconButton',
        type: 'COMPONENT',
        props: { icon: { type: 'string' }, size: { type: 'number' } }
      },
      { type: 'figma-mcp', nodeId: '2:567', fileKey: 'fileKey123' }
    );

    check('Figma MCP import succeeded', figmaMcpResult.success === true);
    check('Figma MCP has fileKey stored', figmaMcpResult.entry?.source?.fileKey === 'fileKey123');
    const iconButtonId = figmaMcpResult.id;

    // Import from ShadCN
    const shadcnResult = await registrar.registerComponent(
      {
        name: 'Card',
        type: 'COMPONENT',
        props: { children: { type: 'ReactNode' } }
      },
      { type: 'shadcn', registryItem: '@shadcn/card' }
    );

    check('ShadCN import succeeded', shadcnResult.success === true);
    check('ShadCN source type stored', shadcnResult.entry?.source?.type === 'shadcn');
    const cardId = shadcnResult.id;

    // Import from NLP prompt
    const nlpResult = await registrar.registerComponent(
      {
        name: 'AlertDialog',
        type: 'COMPONENT',
        props: { title: { type: 'string' }, message: { type: 'string' } }
      },
      { type: 'nlp-prompt', prompt: 'Create an alert dialog component' }
    );

    check('NLP import succeeded', nlpResult.success === true);
    const alertDialogId = nlpResult.id;

    // Verify registry has all components
    invalidateCache();
    let registry = await readComponentRegistry(testDir, { forceRefresh: true });
    check('Registry has 4 components', Object.keys(registry.components).length === 4);
    check('All components have imported state',
      Object.values(registry.components).every(c => c.transformation?.state === 'imported'));

    // ══════════════════════════════════════════════════════════════════
    // PHASE 3: Transform Components (Multiple Frameworks)
    // ══════════════════════════════════════════════════════════════════
    console.log('\nPHASE 3: Transform Components to Code\n');

    const updater = new TransformStateUpdater({ projectPath: testDir });

    // Create React code files
    const reactCodePath = '.design/extracted-code/react/PrimaryButton.tsx';
    const fullReactCodePath = path.join(testDir, reactCodePath);
    const reactCode = `// Generated by Design Bridge
import React from 'react';

export interface PrimaryButtonProps {
  label: string;
  variant?: 'primary' | 'secondary';
}

export const PrimaryButton: React.FC<PrimaryButtonProps> = ({
  label,
  variant = 'primary'
}) => (
  <button className={\`btn btn-\${variant}\`}>{label}</button>
);`;
    fs.writeFileSync(fullReactCodePath, reactCode);

    // Create story file
    const storyPath = '.design/stories/PrimaryButton.stories.tsx';
    const fullStoryPath = path.join(testDir, storyPath);
    const storyContent = `// Generated by Design Bridge
import { PrimaryButton } from '../extracted-code/react/PrimaryButton';
import type { Meta, StoryObj } from '@storybook/react';

const meta: Meta<typeof PrimaryButton> = {
  title: 'Components/PrimaryButton',
  component: PrimaryButton,
};
export default meta;

export const Default: StoryObj<typeof PrimaryButton> = {
  args: { label: 'Click me', variant: 'primary' }
};`;
    fs.writeFileSync(fullStoryPath, storyContent);

    // Mark PrimaryButton as transformed
    const transformResult = await updater.markTransformed(primaryButtonId, {
      framework: 'react',
      codePath: reactCodePath,
      storyPath: storyPath
    });

    check('Transform marking succeeded', transformResult.success === true);
    check('State is now transformed', transformResult.transformation?.state === 'transformed');
    check('Framework is react', transformResult.transformation?.framework === 'react');
    check('Code hash calculated', transformResult.transformation?.codeHash !== null);

    // Verify hash matches existing ContentHasher
    const expectedHash = await hashFile(fullReactCodePath);
    check('Hash matches ContentHasher', transformResult.transformation?.codeHash === expectedHash);

    // Create Vue code file for IconButton
    fs.mkdirSync(path.join(testDir, '.design', 'extracted-code', 'vue'), { recursive: true });
    const vueCodePath = '.design/extracted-code/vue/IconButton.vue';
    const fullVueCodePath = path.join(testDir, vueCodePath);
    const vueCode = `<!-- Generated by Design Bridge -->
<template>
  <button :class="['icon-btn', size]">
    <icon :name="icon" />
  </button>
</template>

<script setup lang="ts">
defineProps<{ icon: string; size?: 'sm' | 'md' | 'lg' }>();
</script>`;
    fs.writeFileSync(fullVueCodePath, vueCode);

    // Mark IconButton as transformed
    await updater.markTransformed(iconButtonId, {
      framework: 'vue',
      codePath: vueCodePath
    });

    // Verify stats
    const stats = await updater.getStats();
    check('Stats shows 2 transformed', stats.transformed === 2);
    check('Stats shows 2 imported (Card, AlertDialog)', stats.imported === 2);
    check('Stats by framework has react', stats.byFramework.react === 1);
    check('Stats by framework has vue', stats.byFramework.vue === 1);

    // ══════════════════════════════════════════════════════════════════
    // PHASE 4: Cascade Sync Flow
    // ══════════════════════════════════════════════════════════════════
    console.log('\nPHASE 4: Cascade Sync Flow\n');

    // Create raw data file for cascade
    const rawDataPath = '.design/components/primary-button.json';
    fs.writeFileSync(
      path.join(testDir, rawDataPath),
      JSON.stringify({ name: 'PrimaryButton', props: { label: {}, variant: {} } }, null, 2)
    );

    // Update registry with raw source path
    invalidateCache();
    registry = await readComponentRegistry(testDir, { forceRefresh: true });
    registry.components[primaryButtonId].paths = { rawSource: rawDataPath };
    await writeComponentRegistry(testDir, registry);

    // Create cascade with code/story regeneration disabled (no optimizer in test)
    const cascade = new SyncCascade({
      projectPath: testDir,
      config: {
        regenerateCode: false,
        regenerateStory: false
      }
    });

    // Track events
    const eventsReceived = [];
    cascade.on(CASCADE_EVENTS.STARTED, (data) => eventsReceived.push('started'));
    cascade.on(CASCADE_EVENTS.STEP, (data) => eventsReceived.push(`step:${data.step}`));
    cascade.on(CASCADE_EVENTS.COMPLETED, (data) => eventsReceived.push('completed'));

    // Run cascade with updated props
    const cascadeResult = await cascade.cascade(primaryButtonId, {
      props: { label: { type: 'string' }, variant: { type: 'string' }, disabled: { type: 'boolean' } }
    });

    check('Cascade succeeded', cascadeResult.success === true);
    check('Cascade has componentId', cascadeResult.componentId === primaryButtonId);
    check('Registry step succeeded', cascadeResult.steps?.registry?.success === true);
    check('Events emitted correctly', eventsReceived.includes('started') && eventsReceived.includes('completed'));

    // Verify registry updated
    invalidateCache();
    registry = await readComponentRegistry(testDir, { forceRefresh: true });
    const updatedComponent = registry.components[primaryButtonId];
    check('Props updated in registry', updatedComponent.props?.disabled !== undefined);
    check('Sync count incremented', updatedComponent.syncMetadata?.syncCount >= 2);

    // ══════════════════════════════════════════════════════════════════
    // PHASE 5: User Modification Preservation
    // ══════════════════════════════════════════════════════════════════
    console.log('\nPHASE 5: User Modification Preservation\n');

    // Store original hash
    const hashBeforeModification = updatedComponent.transformation.codeHash;

    // Simulate user modification
    let currentCode = fs.readFileSync(fullReactCodePath, 'utf8');
    currentCode += `\n// USER CUSTOMIZATION: Added custom hover effect
export const PrimaryButtonWithHover = (props: PrimaryButtonProps) => (
  <PrimaryButton {...props} className="hover:scale-105" />
);`;
    fs.writeFileSync(fullReactCodePath, currentCode);

    // Verify ContentHasher detects modification
    const isModified = await hasFileChanged(fullReactCodePath, hashBeforeModification);
    check('ContentHasher detects user modification', isModified === true);

    // Check shouldRegenerateCode
    const codeCheck = await cascade.shouldRegenerateCode(primaryButtonId);
    check('shouldRegenerateCode detects user modification', codeCheck.userModified === true);
    check('shouldRegenerateCode advises preservation', codeCheck.should === false);
    check('Action is preserve', codeCheck.action === 'preserve');

    // Run cascade again with regenerateCode enabled - should preserve user changes but emit warning
    let warningReceived = false;
    let warningType = null;
    cascade.on(CASCADE_EVENTS.WARNING, (data) => {
      warningReceived = true;
      warningType = data.type;
    });

    // Enable regenerateCode to trigger warning emission path
    cascade.updateConfig({ regenerateCode: true });

    await cascade.cascade(primaryButtonId, {
      props: { label: { type: 'string' }, variant: { type: 'string' }, size: { type: 'string' } }
    });

    // Verify user modification preserved
    const codeAfterCascade = fs.readFileSync(fullReactCodePath, 'utf8');
    check('User customization preserved', codeAfterCascade.includes('USER CUSTOMIZATION'));
    check('Warning emitted for preserved code', warningReceived === true && warningType === 'code_preserved');

    // Reset config for subsequent tests
    cascade.updateConfig({ regenerateCode: false });

    // ══════════════════════════════════════════════════════════════════
    // PHASE 6: Snapshot and Rollback
    // ══════════════════════════════════════════════════════════════════
    console.log('\nPHASE 6: Snapshot and Rollback\n');

    // Get current state
    invalidateCache();
    registry = await readComponentRegistry(testDir, { forceRefresh: true });
    const propsBeforeUpdate = { ...registry.components[primaryButtonId].props };

    // Run cascade with snapshot (enabled by default)
    const cascadeWithSnapshot = await cascade.cascade(primaryButtonId, {
      props: { newProp: { type: 'string' } }
    });

    check('Cascade created snapshot', cascadeWithSnapshot.steps?.registry?.snapshotId !== undefined);
    const snapshotId = cascadeWithSnapshot.steps.registry.snapshotId;

    // Verify props changed
    invalidateCache();
    registry = await readComponentRegistry(testDir, { forceRefresh: true });
    check('Props updated after cascade', registry.components[primaryButtonId].props?.newProp !== undefined);

    // Rollback to snapshot
    const rollbackResult = await cascade.rollback(primaryButtonId, snapshotId);

    check('Rollback succeeded', rollbackResult.success === true);

    // Verify rollback metadata
    invalidateCache();
    registry = await readComponentRegistry(testDir, { forceRefresh: true });
    check('Rollback metadata recorded', registry.components[primaryButtonId].syncMetadata?.lastRollback !== undefined);

    // ══════════════════════════════════════════════════════════════════
    // PHASE 7: Multi-Component Workflow
    // ══════════════════════════════════════════════════════════════════
    console.log('\nPHASE 7: Multi-Component Workflow\n');

    // Transform Card component
    const cardCodePath = '.design/extracted-code/react/Card.tsx';
    const fullCardCodePath = path.join(testDir, cardCodePath);
    const cardCode = `export const Card = ({ children }: { children: React.ReactNode }) => (
  <div className="card">{children}</div>
);`;
    fs.writeFileSync(fullCardCodePath, cardCode);

    await updater.markTransformed(cardId, { framework: 'react', codePath: cardCodePath });

    // List all transformed
    const transformed = await updater.listTransformed();
    check('listTransformed returns correct count', transformed.length === 3);
    check('All frameworks tracked', transformed.some(c => c.framework === 'vue'));

    // Verify needsRetransform for all
    const primaryNeedsRetransform = await updater.needsRetransform(primaryButtonId);
    check('needsRetransform returns object', typeof primaryNeedsRetransform === 'object');
    check('needsRetransform handles user-modified code', primaryNeedsRetransform.userModified === true);

    // Final stats
    const finalStats = await updater.getStats();
    check('Final stats: 3 transformed', finalStats.transformed === 3);
    check('Final stats: 1 imported', finalStats.imported === 1);

    // ══════════════════════════════════════════════════════════════════
    // PHASE 8: Re-import Sync (Update Existing)
    // ══════════════════════════════════════════════════════════════════
    console.log('\nPHASE 8: Re-import Sync\n');

    // Re-import PrimaryButton with updated data
    const reImportResult = await registrar.registerComponent(
      {
        name: 'PrimaryButton',
        type: 'COMPONENT',
        props: { label: { type: 'string' }, variant: { type: 'string' }, loading: { type: 'boolean' } }
      },
      { type: 'figma-plugin', nodeId: '1:234' }
    );

    check('Re-import succeeded', reImportResult.success === true);
    check('Re-import is not new', reImportResult.isNew === false);
    check('Sync count incremented on re-import', reImportResult.entry?.syncMetadata?.syncCount >= 3);

    // Verify transformation state preserved on re-import
    check('Transformation state preserved', reImportResult.entry?.transformation?.state === 'transformed');
    check('Framework preserved', reImportResult.entry?.transformation?.framework === 'react');

    // ══════════════════════════════════════════════════════════════════
    // PHASE 9: Error Recovery
    // ══════════════════════════════════════════════════════════════════
    console.log('\nPHASE 9: Error Recovery\n');

    // Test getTransformState for non-existent component
    const nonExistentState = await updater.getTransformState('non-existent-id');
    check('Non-existent component returns null', nonExistentState === null);

    // Test componentExists
    const existsCheck = await registrar.componentExists(primaryButtonId);
    check('componentExists returns true for existing', existsCheck === true);

    const notExistsCheck = await registrar.componentExists('non-existent-id');
    check('componentExists returns false for non-existing', notExistsCheck === false);

    // Test cascade for non-existent - should return failure result (graceful error handling)
    const nonExistentCascadeResult = await cascade.cascade('non-existent-id', {});
    check('Cascade for non-existent returns failure', nonExistentCascadeResult.success === false);
    check('Error message indicates component not found',
      nonExistentCascadeResult.errors?.some(e => e.includes('not found')));

  } finally {
    cleanupTestDirectory(testDir);
  }

  // Print final results
  console.log('\n' + '═'.repeat(60));
  console.log('  E2E FULL PIPELINE TEST RESULTS');
  console.log('═'.repeat(60));
  console.log(`\n  Total:  ${results.passed + results.failed}`);
  console.log(`  Passed: ${results.passed} ✅`);
  console.log(`  Failed: ${results.failed} ❌`);

  if (results.failed > 0) {
    console.log('\n  Failed tests:');
    results.tests
      .filter(t => t.status === 'failed')
      .forEach(t => console.log(`    - ${t.name}`));
    process.exit(1);
  }

  console.log('\n═'.repeat(60));
  console.log('  ✅ E2E FULL PIPELINE TEST PASSED!');
  console.log('  All existing infrastructure properly integrated:');
  console.log('    - ContentHasher for ID generation and file hashing');
  console.log('    - registry-reader for registry read/write');
  console.log('    - StoryHashRegistry for story tracking');
  console.log('    - SnapshotManager for rollback support');
  console.log('═'.repeat(60) + '\n');
}

testFullPipeline().catch(err => {
  console.error('E2E Test error:', err);
  process.exit(1);
});
