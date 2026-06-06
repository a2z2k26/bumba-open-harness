#!/usr/bin/env node
/**
 * watch-design.js
 * Auto-regeneration watch mode for Design Bridge
 */

const { watchTokens } = require('/opt/bumba-harness/Bumba - DesignBridge/design-feature/packages/@design-bridge/server/file-watcher');
const { readDesignConfig } = require('/opt/bumba-harness/.claude/scripts/read-design-config');
const { generateStoriesForProject } = require('/opt/bumba-harness/.claude/scripts/generate-stories');
const { getDefaultNotifier } = require('/opt/bumba-harness/Bumba - DesignBridge/design-feature/packages/@design-bridge/server/notifier');
const path = require('path');

async function startWatchMode(projectPath = process.cwd()) {
  console.log('\n🔄 Design Bridge Auto-Regeneration\n');
  console.log('Watching for token changes...\n');

  // Initialize notifier
  const notifier = getDefaultNotifier();

  // Read configuration
  let config;
  try {
    config = readDesignConfig(projectPath);
  } catch (error) {
    console.error('❌ Failed to read config.json');
    console.error('Run /design-init first\n');
    process.exit(1);
  }

  const framework = config.project.framework || 'react';
  let regenerating = false;

  // Check if notifications are enabled
  const notificationsEnabled = notifier.isEnabled();
  if (notificationsEnabled) {
    console.log('🔔 Desktop notifications enabled\n');
  }

  // Watch token files
  const watcher = watchTokens(projectPath, async (event, filePath) => {
    if (regenerating) {
      console.log('⏭️  Skipping (regeneration in progress)...');
      return;
    }

    const fileName = path.basename(filePath);

    console.log(`\n📝 Token ${event}: ${fileName}`);
    console.log('🔄 Regenerating design system...\n');

    // Notify token change
    notifier.tokenChanged(fileName, event);

    regenerating = true;
    let filesGenerated = 0;
    let storiesGenerated = 0;

    try {
      // Get transform function
      const transformFn = getTransformFunction(framework);

      if (transformFn) {
        // Notify transformation started
        notifier.transformationStarted(framework);

        // Re-transform
        console.log(`Running transformation for ${framework}...\n`);
        const transformResult = await transformFn(projectPath);
        filesGenerated = transformResult?.files?.length || 0;

        // Notify transformation complete
        notifier.transformationComplete(framework, filesGenerated);

        // Re-generate stories if enabled
        if (config.transformers?.options?.[framework]?.generateStories) {
          console.log('Regenerating stories...\n');
          const storyResult = await generateStoriesForProject(projectPath, framework);
          storiesGenerated = storyResult?.count || 0;

          // Notify stories generated
          if (storiesGenerated > 0) {
            notifier.storiesGenerated(storiesGenerated);
          }
        }

        console.log('\n✅ Regeneration complete!');
      } else {
        console.warn(`⚠️  No transformer found for ${framework}`);
        notifier.warn('No Transformer', `No transformer found for ${framework}`);
      }
    } catch (error) {
      console.error('\n❌ Regeneration failed:', error.message);
      notifier.error('Regeneration Failed', error.message);
    } finally {
      regenerating = false;
    }
  });

  console.log('✅ Watch mode active');
  console.log('   Press Ctrl+C to stop\n');

  // Handle shutdown
  process.on('SIGINT', () => {
    console.log('\n\n👋 Stopping watch mode...');
    watcher.close();
    process.exit(0);
  });
}

/**
 * Get transform function for framework
 *
 * @param {string} framework - Framework name
 * @returns {Function|null} Transform function
 */
function getTransformFunction(framework) {
  const transformMap = {
    'react': () => require('./transform-react').transformReact,
    'vue': () => require('./transform-vue').transformVue,
    'angular': () => require('./transform-angular').transformAngular,
    'svelte': () => require('./transform-svelte').transformSvelte
  };

  const loader = transformMap[framework];
  if (!loader) return null;

  try {
    return loader();
  } catch (error) {
    console.warn(`Transform function for ${framework} not available`);
    return null;
  }
}

// CLI execution
if (require.main === module) {
  startWatchMode()
    .catch(err => {
      console.error('\n❌ Watch mode error:', err.message);
      process.exit(1);
    });
}

module.exports = { startWatchMode };
