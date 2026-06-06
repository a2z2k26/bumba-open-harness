#!/usr/bin/env node
/**
 * {FRAMEWORK} Transformation Wrapper
 *
 * Wraps the BUMBA {FRAMEWORK} optimizer for use with Claude Code skills.
 *
 * This wrapper:
 * 1. Reads .design/config.json
 * 2. Loads design tokens from .design/tokens/
 * 3. Calls the {FRAMEWORK} optimizer
 * 4. Writes output to .design/extracted-code/{FRAMEWORK}/
 * 5. Updates metadata
 */

const fs = require('fs');
const path = require('path');

// Import shared utilities
const { readDesignConfig } = require('../scripts/read-design-config');
const { loadDesignTokens } = require('../scripts/load-design-tokens');
const { updateMetadata } = require('../scripts/update-metadata');

// Import the framework optimizer
const {FRAMEWORK}Optimizer = require('../../packages/@design-bridge/transformers/optimizers/{FRAMEWORK}-optimizer');

async function transform() {
  const projectPath = process.cwd();

  console.log('=== {FRAMEWORK_DISPLAY} Transformation ===\n');

  // Step 1: Verify .design/ structure exists
  const designDir = path.join(projectPath, '.design');
  if (!fs.existsSync(designDir)) {
    console.error('❌ Error: .design/ directory not found');
    console.error('Please run /design-init first to initialize the Design Bridge structure.\n');
    process.exit(1);
  }

  // Step 2: Read configuration
  console.log('Reading configuration...');
  let config;
  try {
    config = readDesignConfig(projectPath);
  } catch (error) {
    console.error('❌ Error reading configuration:', error.message);
    process.exit(1);
  }

  // Verify framework matches
  if (config.project.framework !== '{FRAMEWORK}') {
    console.error(`❌ Error: Project configured for ${config.project.framework}, not {FRAMEWORK}`);
    console.error('Update .design/config.json or use the correct transform skill.\n');
    process.exit(1);
  }

  console.log(`✓ Configuration loaded (framework: {FRAMEWORK})\n`);

  // Step 3: Load design tokens
  console.log('Loading design tokens...');
  let tokens;
  try {
    tokens = loadDesignTokens(projectPath);
  } catch (error) {
    console.error('❌ Error loading tokens:', error.message);
    console.error('Ensure tokens exist in .design/tokens/\n');
    process.exit(1);
  }

  const tokenCount = Object.keys(tokens).length;
  console.log(`✓ Loaded ${tokenCount} token categories\n`);

  // Step 4: Execute transformation
  console.log('Executing {FRAMEWORK_DISPLAY} transformation...');

  const outputPath = path.join(projectPath, '.design', 'extracted-code', '{FRAMEWORK}');

  // Ensure output directory exists
  fs.mkdirSync(outputPath, { recursive: true });

  let result;
  try {
    // Get framework-specific options from config
    const frameworkOptions = config.transformers?.options?.['{FRAMEWORK}'] || {};

    result = await {FRAMEWORK}Optimizer.transform(tokens, {
      typescript: config.project.typescript,
      outputPath: outputPath,
      ...frameworkOptions
    });
  } catch (error) {
    console.error('❌ Transformation failed:', error.message);
    console.error('Check .design/logs/ for details\n');
    process.exit(1);
  }

  console.log(`✓ Transformation complete\n`);

  // Step 5: Verify output
  console.log('Verifying output...');
  const generatedFiles = result.files || [];
  console.log(`✓ Generated ${generatedFiles.length} files\n`);

  // Step 6: Update metadata
  console.log('Updating metadata...');
  try {
    await updateMetadata(projectPath, {
      type: 'transformation',
      framework: '{FRAMEWORK}',
      timestamp: new Date().toISOString(),
      filesGenerated: generatedFiles.length,
      tokensProcessed: tokenCount
    });
    console.log('✓ Metadata updated\n');
  } catch (error) {
    console.warn('⚠ Warning: Could not update metadata:', error.message);
  }

  // Step 7: Report results
  console.log('=== ✅ {FRAMEWORK_DISPLAY} Transformation Complete ===\n');
  console.log(`Generated Files: ${generatedFiles.length}`);
  console.log(`Output Location: .design/extracted-code/{FRAMEWORK}/`);
  console.log('');
  console.log('Next Steps:');
  console.log({NEXT_STEPS_CODE});
  console.log('');
}

// Run transformation
transform().catch(error => {
  console.error('❌ Unexpected error:', error);
  process.exit(1);
});
