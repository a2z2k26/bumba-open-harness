#!/usr/bin/env node
/**
 * update-metadata.js
 * Helper script to update .design/metadata.json
 *
 * Usage:
 *   const { updateMetadata } = require('./.claude/scripts/update-metadata');
 *   await updateMetadata(projectPath, { type: 'transformation', ... });
 */

const fs = require('fs');
const path = require('path');

/**
 * Update design metadata with new event
 * @param {string} projectPath - Path to project root
 * @param {object} event - Event data to record
 * @returns {Promise<object>} Updated metadata
 */
async function updateMetadata(projectPath = process.cwd(), event) {
  const metadataPath = path.join(projectPath, '.design', 'metadata.json');

  // Load existing metadata
  let metadata;
  try {
    const content = fs.readFileSync(metadataPath, 'utf8');
    metadata = JSON.parse(content);
  } catch (error) {
    // Create new metadata if doesn't exist
    metadata = createDefaultMetadata();
  }

  // Update metadata based on event type
  switch (event.type) {
    case 'sync':
      await handleSyncEvent(metadata, event);
      break;
    case 'transformation':
      await handleTransformEvent(metadata, event);
      break;
    case 'figma-bind':
      await handleFigmaBindEvent(metadata, event);
      break;
    default:
      console.warn(`Unknown event type: ${event.type}`);
  }

  // Update version
  metadata.version = metadata.version || '1.0.0';

  // Write updated metadata
  fs.writeFileSync(metadataPath, JSON.stringify(metadata, null, 2));

  return metadata;
}

/**
 * Handle token sync event
 */
async function handleSyncEvent(metadata, event) {
  metadata.lastSync = new Date().toISOString();

  if (event.figmaVersion) {
    metadata.figmaVersion = event.figmaVersion;
  }

  if (event.tokensExtracted) {
    metadata.tokens = {
      ...metadata.tokens,
      ...event.tokensExtracted
    };
  }

  // Add to sync history
  if (!metadata.syncHistory) {
    metadata.syncHistory = [];
  }

  metadata.syncHistory.push({
    timestamp: new Date().toISOString(),
    tokensCount: event.tokensCount || 0,
    success: event.success !== false,
    error: event.error || null
  });

  // Keep only last 50 sync events
  if (metadata.syncHistory.length > 50) {
    metadata.syncHistory = metadata.syncHistory.slice(-50);
  }
}

/**
 * Handle transformation event
 */
async function handleTransformEvent(metadata, event) {
  if (!metadata.transformHistory) {
    metadata.transformHistory = [];
  }

  metadata.transformHistory.push({
    timestamp: new Date().toISOString(),
    framework: event.framework,
    filesGenerated: event.filesGenerated || 0,
    tokensProcessed: event.tokensProcessed || 0,
    success: event.success !== false,
    error: event.error || null
  });

  // Update components if provided
  if (event.components) {
    metadata.components = {
      ...metadata.components,
      ...event.components
    };
  }

  // Keep only last 50 transform events
  if (metadata.transformHistory.length > 50) {
    metadata.transformHistory = metadata.transformHistory.slice(-50);
  }
}

/**
 * Handle Figma binding event
 */
async function handleFigmaBindEvent(metadata, event) {
  metadata.figmaFileKey = event.fileKey || metadata.figmaFileKey;
  metadata.figmaFileName = event.fileName || metadata.figmaFileName;
  metadata.figmaVersion = event.version || metadata.figmaVersion;
  metadata.boundAt = new Date().toISOString();
}

/**
 * Create default metadata structure
 */
function createDefaultMetadata() {
  return {
    version: '1.0.0',
    figmaFileKey: null,
    figmaFileName: null,
    figmaVersion: null,
    lastSync: null,
    createdAt: new Date().toISOString(),
    initializedBy: 'design-init command',
    tokens: {},
    components: {},
    syncHistory: [],
    transformHistory: []
  };
}

/**
 * Get metadata statistics
 */
function getMetadataStats(projectPath = process.cwd()) {
  const metadataPath = path.join(projectPath, '.design', 'metadata.json');

  if (!fs.existsSync(metadataPath)) {
    return { exists: false };
  }

  const metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf8'));

  return {
    exists: true,
    lastSync: metadata.lastSync,
    totalSyncs: metadata.syncHistory?.length || 0,
    totalTransforms: metadata.transformHistory?.length || 0,
    tokenCount: Object.keys(metadata.tokens || {}).length,
    componentCount: Object.keys(metadata.components || {}).length,
    figmaBound: !!metadata.figmaFileKey
  };
}

/**
 * Clear history (keep only last N events)
 */
function clearHistory(projectPath = process.cwd(), keepLast = 10) {
  const metadataPath = path.join(projectPath, '.design', 'metadata.json');
  const metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf8'));

  if (metadata.syncHistory) {
    metadata.syncHistory = metadata.syncHistory.slice(-keepLast);
  }

  if (metadata.transformHistory) {
    metadata.transformHistory = metadata.transformHistory.slice(-keepLast);
  }

  fs.writeFileSync(metadataPath, JSON.stringify(metadata, null, 2));
}

// CLI usage
if (require.main === module) {
  const command = process.argv[2];
  const projectPath = process.argv[3] || process.cwd();

  if (command === 'stats') {
    const stats = getMetadataStats(projectPath);
    console.log('\nMetadata Statistics:');
    console.log(JSON.stringify(stats, null, 2));
  } else if (command === 'clear') {
    const keepLast = parseInt(process.argv[4]) || 10;
    clearHistory(projectPath, keepLast);
    console.log(`\nCleared history, kept last ${keepLast} events`);
  } else {
    console.log('Usage:');
    console.log('  node update-metadata.js stats [projectPath]');
    console.log('  node update-metadata.js clear [projectPath] [keepLast]');
  }
}

module.exports = {
  updateMetadata,
  getMetadataStats,
  clearHistory,
  createDefaultMetadata
};
