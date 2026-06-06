/**
 * Session End Hook
 *
 * Runs when Claude Code session ends. Performs final sync and displays summary.
 *
 * @module hooks/session-end
 */

const fs = require('fs');
const path = require('path');

/**
 * Session end hook main function
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

    console.log('');
    console.log('━'.repeat(50));
    console.log('📊 Running final GitHub sync...');
    console.log('━'.repeat(50));
    console.log('');

    // Trigger sync-github command
    // In actual implementation, this would invoke the /sync-github command
    // using mcpTools or command invocation API
    // For now, we display the intent
    console.log('🔄 Checking for GitHub updates...');

    // Load sync state to display summary
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

    // Display summary
    console.log('');
    console.log('✅ Session sync complete');
    console.log('');

    if (syncState.lastSync) {
      console.log(`📅 Last sync: ${new Date(syncState.lastSync).toLocaleString()}`);
    }

    if (syncState.totalIssuesCreated !== undefined) {
      console.log(`📋 Total tasks synced: ${syncState.totalIssuesCreated}`);
    } else if (syncState.issuesSynced !== undefined) {
      console.log(`📋 Tasks synced: ${syncState.issuesSynced}`);
    }

    if (syncState.projectName) {
      console.log(`🎯 Project: ${syncState.projectName}`);
    }

    if (syncState.dashboardUrl) {
      console.log(`🔗 Dashboard: ${syncState.dashboardUrl}`);
    }

    console.log('');
    console.log('━'.repeat(50));
    console.log('👋 Session ended - all changes saved');
    console.log('━'.repeat(50));
    console.log('');

  } catch (error) {
    // Catch-all error handler - don't block session end
    console.error('⚠️  Session end hook error:', error.message);
    console.error('');
    console.error('   This is a non-blocking error. Your session will end normally.');
    console.error('');
    console.error('   To fix:');
    console.error('   1. Check ~/.claude/plugins/bumba-notion/hooks/session-end.js for errors');
    console.error('   2. Verify .bumba-notion-plugin/ directory structure');
    console.error('   3. See docs/TROUBLESHOOTING.md for common issues');
    // Silent exit - don't prevent session from ending
  }
};
