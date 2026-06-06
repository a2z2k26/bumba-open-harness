/**
 * Session Start Hook
 *
 * Runs when Claude Code session starts. Detects BUMBA-Notion projects,
 * checks sync staleness, and prompts user to sync if needed.
 *
 * @module hooks/session-start
 */

const fs = require('fs');
const path = require('path');

// Debounce queue to prevent duplicate syncs
// Adapted from BUMBA CLI /home/operator/BUMBA-CLI-1.0/src/core/github/issue-bridge.js
const syncQueue = new Map();
const DEBOUNCE_WINDOW = 5000; // 5 seconds

/**
 * Queue a sync operation with debouncing
 *
 * @param {string} projectSlug - Project identifier
 * @param {Function} syncFn - Function to execute after debounce
 */
function queueSync(projectSlug, syncFn) {
  // Clear existing timer if present
  if (syncQueue.has(projectSlug)) {
    clearTimeout(syncQueue.get(projectSlug));
  }

  // Set new timer
  const timerId = setTimeout(() => {
    syncFn();
    syncQueue.delete(projectSlug);
  }, DEBOUNCE_WINDOW);

  syncQueue.set(projectSlug, timerId);
}

/**
 * Session start hook main function
 *
 * @param {Object} context - Hook context
 * @param {string} context.workingDirectory - Current working directory
 * @param {Object} context.mcpTools - Available MCP tools
 */
module.exports = async ({ workingDirectory, mcpTools }) => {
  try {
    // Check if project has .bumba-notion-plugin/
    const pluginDir = path.join(workingDirectory, '.bumba-notion-plugin');

    if (!fs.existsSync(pluginDir)) {
      // Not a BUMBA-Notion project, exit silently
      return;
    }

    // Load sync state
    const stateDir = path.join(pluginDir, 'state');
    const stateFile = path.join(stateDir, 'sync-state.json');

    let syncState = {};
    if (fs.existsSync(stateFile)) {
      try {
        const stateContent = fs.readFileSync(stateFile, 'utf8');
        syncState = JSON.parse(stateContent);
      } catch (error) {
        console.error('⚠️  Failed to parse sync state:', error.message);
        console.error('');
        console.error('   Next steps:');
        console.error('   1. Delete the corrupted file: .bumba-notion-plugin/state/sync-state.json');
        console.error('   2. Run /sync-github to create a fresh sync state');
        console.error('');
        console.error('   See docs/TROUBLESHOOTING.md for more help');
        syncState = {};
      }
    }

    // Load workspace mapping to get project info
    const configFile = path.join(pluginDir, 'config', 'workspace-mapping.json');
    let config = {};

    if (fs.existsSync(configFile)) {
      try {
        const configContent = fs.readFileSync(configFile, 'utf8');
        config = JSON.parse(configContent);
      } catch (error) {
        console.error('⚠️  Failed to parse workspace mapping:', error.message);
        console.error('');
        console.error('   Next steps:');
        console.error('   1. Check .bumba-notion-plugin/config/workspace-mapping.json for syntax errors');
        console.error('   2. Run /project-init to reinitialize the project');
        console.error('');
        console.error('   See docs/TROUBLESHOOTING.md for more help');
      }
    }

    // Display sync status
    console.log('');
    console.log('📊 BUMBA-Notion Project Detected');
    console.log('━'.repeat(50));
    console.log('');

    if (syncState.lastSync) {
      const lastSyncTime = new Date(syncState.lastSync);
      const hoursSinceSync = (Date.now() - lastSyncTime.getTime()) / (1000 * 60 * 60);

      console.log(`📅 Last sync: ${lastSyncTime.toLocaleString()}`);
      console.log(`📋 Tasks synced: ${syncState.totalIssuesCreated || syncState.issuesSynced || 0}`);

      if (syncState.projectName) {
        console.log(`🎯 Project: ${syncState.projectName}`);
      }

      // Auto-sync if stale (>1 hour)
      if (hoursSinceSync > 1) {
        console.log('');
        console.log('⚠️  Sync is stale (>1 hour old)');
        console.log('');
        console.log('💡 Recommended: Run /sync-github to update tasks from GitHub');

        // Queue sync with debounce (prevents duplicate syncs if multiple session events fire)
        const projectSlug = syncState.projectSlug || 'default';
        queueSync(projectSlug, () => {
          console.log('🔄 Auto-sync triggered...');
          // In actual implementation, this would invoke /sync-github command
          // For now, just log the intent
        });
      } else {
        console.log('✅ Sync is fresh (synced within last hour)');
      }
    } else {
      console.log('📭 No previous sync found');
      console.log('');
      console.log('💡 To get started: Run /sync-github to sync GitHub issues');
    }

    console.log('');
    console.log('━'.repeat(50));
    console.log('');

  } catch (error) {
    // Catch-all error handler - don't block session start
    console.error('⚠️  Session start hook error:', error.message);
    console.error('');
    console.error('   This is a non-blocking error. Your session will continue normally.');
    console.error('');
    console.error('   To fix:');
    console.error('   1. Check ~/.claude/plugins/bumba-notion/hooks/session-start.js for errors');
    console.error('   2. Verify .bumba-notion-plugin/ directory structure');
    console.error('   3. See docs/TROUBLESHOOTING.md for common issues');
    // Silent exit - don't prevent session from starting
  }
};
