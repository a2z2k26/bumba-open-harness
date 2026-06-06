/**
 * Hook: on-sync-changes
 * Automatically triggers sync-cascade when design changes are detected
 *
 * Triggers on:
 * - .design/logs/last-sync-changes.json is written by sync-monitor
 *
 * This hook reads the change data and creates a cascade trigger for the
 * sync-cascade skill to process the updates.
 *
 * @version 1.0.0
 */

const path = require('path');
const fs = require('fs');

module.exports = {
  name: 'on-sync-changes',
  version: '1.0.0',
  description: 'Trigger cascade when sync-monitor detects changes',
  watch: '.design/logs/last-sync-changes.json',
  debounce: 500, // Wait 500ms after write
  enabled: true,
  priority: 90, // Run early (lower priority number = higher priority)

  /**
   * Execute the hook when last-sync-changes.json is written
   * @param {Object} event - File change event
   * @returns {Object} Hook result
   */
  async execute(event) {
    const { filePath, changeType, projectPath } = event;

    process.stderr.write(`[on-sync-changes] Detected sync changes: ${filePath}\n`);

    try {
      // Read the change data
      const changeDataPath = path.join(projectPath || process.cwd(), '.design/logs/last-sync-changes.json');

      if (!fs.existsSync(changeDataPath)) {
        return {
          success: false,
          message: 'Change data file not found',
          action: 'skipped'
        };
      }

      const changeData = JSON.parse(fs.readFileSync(changeDataPath, 'utf8'));

      // Check if cascade is enabled
      const configPath = path.join(projectPath || process.cwd(), '.design/config.json');
      let cascadeEnabled = true;

      if (fs.existsSync(configPath)) {
        const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
        cascadeEnabled = config.cascade?.enabled !== false;
      }

      if (!cascadeEnabled) {
        process.stderr.write(`[on-sync-changes] Cascade disabled in config\n`);
        return {
          success: true,
          message: 'Cascade disabled',
          action: 'skipped-disabled'
        };
      }

      // Count total changes
      const changedCount = (changeData.changedComponents || []).length;
      const newCount = (changeData.newComponents || []).length;
      const tokenChanges = (changeData.changedTokens || []).length;
      const totalChanges = changedCount + newCount;

      if (totalChanges === 0 && tokenChanges === 0) {
        process.stderr.write(`[on-sync-changes] No changes to cascade\n`);
        return {
          success: true,
          message: 'No changes detected',
          action: 'skipped-no-changes'
        };
      }

      // Create cascade trigger file
      const triggerDir = path.join(projectPath || process.cwd(), '.design/logs/triggers');
      if (!fs.existsSync(triggerDir)) {
        fs.mkdirSync(triggerDir, { recursive: true });
      }

      const triggerData = {
        skill: 'design:sync-cascade',
        timestamp: new Date().toISOString(),
        changedComponents: changeData.changedComponents || [],
        newComponents: changeData.newComponents || [],
        changedTokens: changeData.changedTokens || [],
        tokenDetails: changeData.tokenDetails || {}
      };

      const triggerPath = path.join(triggerDir, 'cascade-trigger.json');
      fs.writeFileSync(triggerPath, JSON.stringify(triggerData, null, 2));

      // Log cascade information
      process.stderr.write(`\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n`);
      process.stderr.write(`🔄 DESIGN SYNC DETECTED\n`);
      process.stderr.write(`━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n`);
      process.stderr.write(`\n`);
      process.stderr.write(`Changes detected: ${totalChanges} component(s), ${tokenChanges} token(s)\n`);

      if (changedCount > 0) {
        process.stderr.write(`Changed: ${changeData.changedComponents.join(', ')}\n`);
      }
      if (newCount > 0) {
        process.stderr.write(`New: ${changeData.newComponents.join(', ')}\n`);
      }
      if (tokenChanges > 0) {
        process.stderr.write(`Tokens: ${changeData.changedTokens.join(', ')}\n`);
      }

      process.stderr.write(`\n`);
      process.stderr.write(`⚡ Next Step:\n`);
      process.stderr.write(`Claude will automatically process these changes.\n`);
      process.stderr.write(`Or manually run: /design:sync-cascade\n`);
      process.stderr.write(`\n`);
      process.stderr.write(`Trigger data: ${triggerPath}\n`);
      process.stderr.write(`━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n`);

      return {
        success: true,
        message: `Cascade triggered for ${totalChanges} components and ${tokenChanges} tokens`,
        action: 'cascade-triggered',
        triggerPath,
        stats: {
          changedComponents: changedCount,
          newComponents: newCount,
          changedTokens: tokenChanges
        }
      };

    } catch (error) {
      process.stderr.write(`[on-sync-changes] Error: ${error.message}\n`);
      return {
        success: false,
        message: error.message,
        action: 'error',
        error
      };
    }
  }
};
