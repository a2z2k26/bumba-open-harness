#!/usr/bin/env node
/**
 * Bridge script for triggering hooks from Claude Code native hooks
 *
 * Called by Claude Code PostToolUse hooks when special files are modified.
 * Loads the hook registry and triggers matching hooks.
 *
 * Handles:
 * - .design/ files (Design Bridge hooks)
 * - .claude/project-config.json (Project initialization hook)
 *
 * Usage: node trigger-design-hooks.js <file-path>
 */

const path = require('path');

async function main() {
  const filePath = process.argv[2];

  if (!filePath) {
    process.stderr.write('[trigger-hooks] No file path provided\n');
    process.exit(0);
  }

  // Check if this is a file we should process
  const isDesignFile = filePath.includes('.design/');
  const isProjectConfig = filePath.includes('.claude/project-config.json');

  if (!isDesignFile && !isProjectConfig) {
    process.exit(0);
  }

  process.stderr.write(`[trigger-hooks] Processing: ${filePath}\n`);

  // Extract project path from file path
  let projectPath;
  if (isDesignFile) {
    const designIndex = filePath.indexOf('.design/');
    projectPath = designIndex > 0 ? filePath.substring(0, designIndex) : process.cwd();
  } else if (isProjectConfig) {
    const claudeIndex = filePath.indexOf('.claude/');
    projectPath = claudeIndex > 0 ? filePath.substring(0, claudeIndex) : process.cwd();
  } else {
    projectPath = process.cwd();
  }

  try {
    // Load the hook registry
    const { loadHooks, trigger } = require('./design-bridge-hook-registry.js');

    // Load all hooks
    const loadResult = loadHooks();
    process.stderr.write(`[trigger-design-hooks] Loaded ${loadResult.loaded} hooks\n`);

    // Determine event name based on file path
    let eventName = 'on-file-change';

    if (filePath.includes('.claude/project-config.json')) {
      eventName = 'on-project-init-complete';
    } else if (filePath.endsWith('.design/config.json') || filePath.includes('.design/config.json')) {
      eventName = 'on-design-init-complete';
    } else if (filePath.includes('componentRegistry.json')) {
      eventName = 'on-registry-change';
    } else if (filePath.includes('/tokens/')) {
      eventName = 'on-token-change';
    } else if (filePath.includes('/source/components/')) {
      eventName = 'on-component-extract';
    } else if (filePath.includes('/source/layouts/')) {
      eventName = 'on-layout-extract';
    } else if (filePath.includes('validation-report.json')) {
      eventName = 'on-layout-transform-complete';
    }

    // Trigger matching hooks with correct property names
    const results = await trigger(eventName, {
      filePath: filePath,
      path: filePath,  // Keep for backwards compatibility
      projectPath: projectPath,
      changeType: 'modified',  // Claude Code hooks trigger on Write/Edit which are modifications
      timestamp: new Date().toISOString()
    });

    process.stderr.write(`[trigger-design-hooks] Triggered ${results.length} hook(s)\n`);

    for (const result of results) {
      if (result.success) {
        process.stderr.write(`  ${result.hook}: ${result.message || 'OK'}\n`);
      } else {
        console.error(`  ${result.hook}: FAILED - ${result.message}`);
      }
    }

  } catch (error) {
    console.error(`[trigger-design-hooks] Error: ${error.message}`);
    process.exit(1);
  }
}

main();
