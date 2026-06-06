/**
 * on-layout-transform-complete.js
 *
 * PostToolUse hook that offers Ralph refinement after design-layout-to-* skills
 * complete with parity < 100%.
 *
 * Creates seamless handoff from initial layout transformation to iterative refinement.
 */

const fs = require('fs');
const path = require('path');

module.exports = {
  name: 'on-layout-transform-complete',
  description: 'Offer Ralph refinement after imperfect layout transformation',

  // Watch for validation reports written by design-layout-to-* skills
  watch: '.design/layouts/**/validation-report.json',

  // Priority: Run before other hooks that might process the same files
  priority: 100,

  // Debounce: Wait for file writes to settle
  debounce: 500,

  // Enabled by default
  enabled: true,

  async execute(event) {
    try {
      const reportPath = event.filePath;

      // Read validation report
      if (!fs.existsSync(reportPath)) {
        return { success: true, skipped: true, reason: 'Report file not found' };
      }

      const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));

      // Extract parity percentage
      const finalParity = report.summary?.finalParity;
      if (!finalParity) {
        return { success: true, skipped: true, reason: 'No parity info in report' };
      }

      // Parse parity percentage (e.g., "92%", "100%")
      const parityMatch = finalParity.match(/(\d+)%/);
      if (!parityMatch) {
        return { success: true, skipped: true, reason: 'Could not parse parity percentage' };
      }

      const parity = parseInt(parityMatch[1]);

      // Perfect parity - no refinement needed
      if (parity >= 100) {
        process.stderr.write(`\n✓ Perfect parity achieved: ${report.layoutName} (${parity}%)\n\n`);
        return {
          success: true,
          offerRefinement: false,
          parity,
          layoutName: report.layoutName
        };
      }

      // Parity < 100% - offer Ralph refinement
      const layoutDir = path.dirname(reportPath);
      const baselineScreenshot = path.join(layoutDir, 'screenshot.png');

      // Verify baseline exists
      if (!fs.existsSync(baselineScreenshot)) {
        process.stderr.write(`\n⚠️  Warning: Baseline screenshot not found: ${baselineScreenshot}\n\n`);
        return {
          success: true,
          offerRefinement: false,
          reason: 'Baseline screenshot missing'
        };
      }

      // Create handoff manifest
      const manifest = {
        layoutName: report.layoutName,
        framework: report.framework,
        baselineScreenshot: path.resolve(baselineScreenshot),
        generatedCode: report.outputPath ? path.resolve(report.outputPath) : null,
        validationReport: path.resolve(reportPath),
        currentParity: parity,
        handoffMode: true,
        timestamp: new Date().toISOString(),
        layoutDir: path.resolve(layoutDir)
      };

      // Write handoff manifest
      const handoffPath = '.design/.refine-handoff.json';
      const handoffDir = path.dirname(handoffPath);

      if (!fs.existsSync(handoffDir)) {
        fs.mkdirSync(handoffDir, { recursive: true });
      }

      fs.writeFileSync(handoffPath, JSON.stringify(manifest, null, 2));

      // Display offer to user
      process.stderr.write('\n' + '═'.repeat(80) + '\n');
      process.stderr.write(`⚠️  Layout Parity: ${parity}% (target: 100%)\n`);
      process.stderr.write('═'.repeat(80) + '\n');
      process.stderr.write(`\nLayout: ${report.layoutName}\n`);
      process.stderr.write(`Framework: ${report.framework}\n`);
      process.stderr.write(`\nRalph refinement available!\n`);
      process.stderr.write(`\nRun: /design-layout-refine\n`);
      process.stderr.write(`\nRalph will iteratively refine the code until 98%+ parity is achieved.\n`);
      process.stderr.write('Refinement happens in an isolated git worktree - safe to experiment.\n\n');
      process.stderr.write('═'.repeat(80) + '\n\n');

      return {
        success: true,
        offerRefinement: true,
        parity,
        layoutName: report.layoutName,
        framework: report.framework,
        manifest,
        handoffPath
      };
    } catch (err) {
      process.stderr.write(`Hook error: ${err.message}\n`);
      return {
        success: false,
        error: err.message
      };
    }
  }
};
