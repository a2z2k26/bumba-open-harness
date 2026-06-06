#!/usr/bin/env node
/**
 * React Native Transformation Wrapper
 *
 * Wraps the BUMBA react-native optimizer for use with Claude Code skills.
 *
 * This wrapper supports two modes:
 *
 * Mode 1 - Token-based (legacy):
 * 1. Reads .design/config.json
 * 2. Loads design tokens from .design/tokens/
 * 3. Calls the react-native optimizer
 * 4. Writes output to .design/extracted-code/react-native/
 * 5. Updates metadata
 *
 * Mode 2 - Registry-based (new):
 * 1. Reads component from registry by ID
 * 2. Loads raw source data
 * 3. Enriches optimizer input with registry metadata
 * 4. Transforms component with full context
 * 5. Writes output to configured path
 */

const fs = require('fs');
const path = require('path');

// Import shared utilities
const { readDesignConfig } = require('../scripts/read-design-config');
const { loadDesignTokens } = require('../scripts/load-design-tokens');
const { updateMetadata } = require('../scripts/update-metadata');

// Import the framework transformer
const ReactNativeComponentTransformer = require('../shared-modules/design-system/react-native-component-transformer');

// Import registry reader for component lookup
const {
  readComponentRegistry,
  getComponentById,
  loadRawSource,
  resolveCodeOutputPath,
  getAllComponentIds
} = require('../../packages/@design-bridge/server/registry-reader');

// Import post-transform hook for auto-story generation (Option C)
// Note: React Native is a preview-only framework - hook logs but skips story generation
const onComponentTransform = require('../hooks/on-component-transform');

// Phase 3: Transform state tracking (Two-State Architecture)
const { TransformStateUpdater } = require('../../packages/@design-bridge/server/transform-state-updater');

async function transform() {
  const projectPath = process.cwd();

  console.log('=== React Native Transformation ===\n');

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
  if (config.project.framework !== 'react-native') {
    console.error(`❌ Error: Project configured for ${config.project.framework}, not react-native`);
    console.error('Update .design/config.json or use the correct transform skill.\n');
    process.exit(1);
  }

  console.log(`✓ Configuration loaded (framework: react-native)\n`);

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
  console.log('Executing React Native transformation...');

  const outputPath = path.join(projectPath, '.design', 'extracted-code', 'react-native');

  // Ensure output directory exists
  fs.mkdirSync(outputPath, { recursive: true });

  let result;
  try {
    // Get framework-specific options from config
    const frameworkOptions = config.transformers?.options?.['react-native'] || {};

    result = await reactNativeOptimizer.transform(tokens, {
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
      framework: 'react-native',
      timestamp: new Date().toISOString(),
      filesGenerated: generatedFiles.length,
      tokensProcessed: tokenCount
    });
    console.log('✓ Metadata updated\n');
  } catch (error) {
    console.warn('⚠ Warning: Could not update metadata:', error.message);
  }

  // Step 7: Report results
  console.log('=== ✅ React Native Transformation Complete ===\n');
  console.log(`Generated Files: ${generatedFiles.length}`);
  console.log(`Output Location: .design/extracted-code/react-native/`);
  console.log('');
  console.log('Next Steps:');
  console.log('  - Review tokens: .design/extracted-code/react-native/tokens/');
  console.log('  - Run iOS: npx react-native run-ios');
  console.log('  - Run Android: npx react-native run-android');
  console.log('');
}

/**
 * Transform a single component by its registry ID
 * @param {string} componentId - Component ID from registry
 * @param {Object} options - Transform options
 * @returns {Promise<Object>} Transform result
 */
async function transformComponent(componentId, options = {}) {
  const projectPath = options.projectPath || process.cwd();

  console.log(`[transform-react-native] Starting transform for: ${componentId}`);

  // Step 0: Instantiate transformer with registry checking built-in
  const transformer = new ReactNativeComponentTransformer(projectPath, {
    typescript: options.typescript !== false
  });

  // Step 1: Transform the component (registry check is automatic)
  let transformResult;
  try {
    transformResult = await transformer.transformComponent(
      componentId,
      {
        forceRetransform: options.force || false
      }
    );
  } catch (error) {
    throw new Error(`Transform failed: ${error.message}`);
  }

  // Handle skipped (already transformed)
  if (transformResult.skipped) {
    console.log(`[transform-react-native] ✓ Component already transformed: ${transformResult.outputPath}`);
    return {
      success: true,
      skipped: true,
      componentId,
      name: transformResult.componentName,
      outputPath: transformResult.outputPath,
      code: null
    };
  }

  // Read generated code for return value
  const code = fs.readFileSync(transformResult.outputPath, 'utf8');

  console.log(`[transform-react-native] ✓ Component transformed: ${transformResult.outputPath}`);
  if (transformResult.storyPath) {
    console.log(`[transform-react-native] ✓ Story generated: ${transformResult.storyPath}`);
  }

  // Phase 3: Update transformation state in registry (Two-State Architecture)
  try {
    const stateUpdater = new TransformStateUpdater({ projectPath });
    const stateResult = await stateUpdater.markTransformed(componentId, {
      framework: 'react-native',
      codePath: path.relative(projectPath, transformResult.outputPath),
      storyPath: transformResult.storyPath ? path.relative(projectPath, transformResult.storyPath) : null
    });

    if (stateResult.success) {
      console.log(`[transform-react-native] Updated state: ${componentId} -> transformed`);
    } else {
      console.warn(`[transform-react-native] State update warning: ${stateResult.error}`);
    }
  } catch (stateError) {
    // State tracking errors should not break the transform
    console.warn(`[transform-react-native] State tracking error (non-fatal): ${stateError.message}`);
  }

  return {
    success: true,
    componentId,
    name: transformResult.componentName,
    code,
    outputPath: transformResult.outputPath,
    storyPath: transformResult.storyPath
  };
}

async function transformComponents(componentIds, options = {}) {
  const results = [];
  for (const id of componentIds) {
    try {
      const result = await transformComponent(id, options);
      results.push(result);
    } catch (error) {
      results.push({ success: false, componentId: id, error: error.message });
    }
  }
  return results;
}

async function transformAll(options = {}) {
  const projectPath = options.projectPath || process.cwd();
  const registry = await readComponentRegistry(projectPath);
  const componentIds = getAllComponentIds(registry);

  console.log(`[transform-react-native] Transforming ${componentIds.length} components...`);
  const results = await transformComponents(componentIds, options);

  const succeeded = results.filter(r => r.success).length;
  const failed = results.filter(r => !r.success).length;

  console.log(`[transform-react-native] Complete: ${succeeded} succeeded, ${failed} failed`);
  return { total: componentIds.length, succeeded, failed, results };
}

module.exports = { transform, transformComponent, transformComponents, transformAll };

if (require.main === module) {
  const args = process.argv.slice(2);
  const componentArg = args.find(a => a.startsWith('--component='));
  const allFlag = args.includes('--all');

  if (componentArg) {
    const componentId = componentArg.split('=')[1];
    transformComponent(componentId)
      .then(result => {
        console.log('\n=== ✅ Transform Complete ===');
        console.log(`Component: ${result.name}`);
        console.log(`Output: ${result.paths.codeOutput}`);
        if (result.warnings.length > 0) console.log(`Warnings: ${result.warnings.join(', ')}`);
      })
      .catch(error => { console.error('❌ Error:', error.message); process.exit(1); });
  } else if (allFlag) {
    transformAll()
      .then(result => {
        console.log('\n=== ✅ Batch Transform Complete ===');
        console.log(`Total: ${result.total}, Succeeded: ${result.succeeded}, Failed: ${result.failed}`);
      })
      .catch(error => { console.error('❌ Error:', error.message); process.exit(1); });
  } else {
    transform().catch(error => { console.error('❌ Unexpected error:', error); process.exit(1); });
  }
}
