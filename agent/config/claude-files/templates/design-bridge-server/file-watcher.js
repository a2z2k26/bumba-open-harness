/**
 * file-watcher.js
 * File watching for auto-regeneration
 *
 * Note: Requires chokidar package
 * Install: npm install chokidar
 */

const path = require('path');

/**
 * Watch design tokens directory for changes
 *
 * @param {string} projectPath - Project root path
 * @param {Function} callback - Callback function (event, path)
 * @returns {Object} Watcher instance
 */
function watchTokens(projectPath, callback) {
  const tokensPath = path.join(projectPath, '.design/tokens');

  console.log(`👀 Watching: ${tokensPath}\n`);

  // Try to load chokidar
  let chokidar;
  try {
    chokidar = require('chokidar');
  } catch (error) {
    console.error('❌ chokidar not installed');
    console.error('Install with: npm install chokidar\n');
    throw new Error('chokidar package required for file watching');
  }

  const watcher = chokidar.watch(tokensPath, {
    persistent: true,
    ignoreInitial: true,
    awaitWriteFinish: {
      stabilityThreshold: 1000,
      pollInterval: 100
    }
  });

  watcher
    .on('add', (filePath) => callback('add', filePath))
    .on('change', (filePath) => callback('change', filePath))
    .on('unlink', (filePath) => callback('unlink', filePath));

  return watcher;
}

/**
 * Watch components directory for changes
 *
 * @param {string} projectPath - Project root path
 * @param {string} framework - Framework name
 * @param {Function} callback - Callback function (event, path)
 * @returns {Object} Watcher instance
 */
function watchComponents(projectPath, framework, callback) {
  const componentsPath = path.join(projectPath, '.design/extracted-code', framework, 'components');

  // Try to load chokidar
  let chokidar;
  try {
    chokidar = require('chokidar');
  } catch (error) {
    throw new Error('chokidar package required for file watching');
  }

  const watcher = chokidar.watch(componentsPath, {
    persistent: true,
    ignoreInitial: true,
    ignored: /\.stories\./,
    awaitWriteFinish: {
      stabilityThreshold: 1000,
      pollInterval: 100
    }
  });

  watcher
    .on('add', (filePath) => callback('add', filePath))
    .on('change', (filePath) => callback('change', filePath))
    .on('unlink', (filePath) => callback('unlink', filePath));

  return watcher;
}

module.exports = {
  watchTokens,
  watchComponents
};
