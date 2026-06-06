/**
 * Hook: on-tokens-updated
 * Automatically regenerates STYLES.md when tokens or components change
 *
 * Triggers on:
 * - Token file changes in .design/tokens/
 * - Component file changes in .design/components/
 *
 * @version 1.0.0
 */

const path = require('path');
const fs = require('fs');

module.exports = {
  name: 'on-tokens-updated',
  version: '1.0.0',
  description: 'Auto-regenerate STYLES.md when tokens or components change',
  watch: [
    '.design/tokens/**/*.json',
    '.design/components/**/*.json'
  ],
  debounce: 1000, // Wait 1 second after last change
  enabled: true,
  priority: 50,

  /**
   * Execute the hook when tokens or components change
   * @param {Object} event - File change event
   * @returns {Object} Hook result
   */
  async execute(event) {
    const { filePath, changeType, projectPath } = event;

    process.stderr.write(`[on-tokens-updated] Detected ${changeType}: ${filePath}\n`);

    try {
      // Load the generator
      const serverPath = '/home/operator/Bumba-Design/Bumba - Design Components/server';
      const { StylesMdGenerator } = require(path.join(serverPath, 'styles-md-generator.js'));

      // Generate STYLES.md
      const generator = new StylesMdGenerator({ projectPath });
      const result = await generator.generate();

      if (result.success) {
        process.stderr.write(`[on-tokens-updated] Regenerated STYLES.md\n`);
        process.stderr.write(`  Colors: ${result.stats.colors}, Typography: ${result.stats.typography}\n`);
        process.stderr.write(`  Components: ${result.stats.components}\n`);

        return {
          success: true,
          message: 'STYLES.md regenerated successfully',
          action: 'regenerated',
          path: result.path,
          stats: result.stats,
          trigger: {
            file: filePath,
            type: changeType
          }
        };
      } else {
        process.stderr.write(`[on-tokens-updated] Generation failed: ${result.error}\n`);
        return {
          success: false,
          message: result.error,
          action: 'failed'
        };
      }
    } catch (error) {
      process.stderr.write(`[on-tokens-updated] Error: ${error.message}\n`);
      return {
        success: false,
        message: error.message,
        action: 'error',
        error
      };
    }
  },

  /**
   * Check if this hook should run for the given file
   * @param {string} filePath - Path to changed file
   * @returns {boolean} True if hook should run
   */
  shouldTrigger(filePath) {
    const normalizedPath = filePath.replace(/\\/g, '/');

    // Check if it's a token or component file
    const isTokenFile = normalizedPath.includes('.design/tokens/') && normalizedPath.endsWith('.json');
    const isComponentFile = normalizedPath.includes('.design/components/') && normalizedPath.endsWith('.json');

    return isTokenFile || isComponentFile;
  }
};
