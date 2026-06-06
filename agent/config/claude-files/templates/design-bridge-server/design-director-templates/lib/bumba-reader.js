/**
 * Bumba Reader - Read Bumba Design System context
 *
 * Provides functions to read Bumba config, design tokens, and components
 * from the parent .design/ directory structure.
 */

const fs = require('fs');
const path = require('path');
const { glob } = require('glob');

/**
 * Validate Bumba config structure
 * @param {Object} config - Config object to validate
 * @returns {boolean} - True if valid
 */
function validateConfig(config) {
  if (!config.version || !config.project || !config.transformers) {
    console.warn('[bumba-reader] Config missing required fields (version, project, transformers)');
    return false;
  }
  return true;
}

/**
 * Read Bumba config from .design/config.json
 * @returns {Object|null} - Config object or null if not found
 */
function readBumbaConfig() {
  const configPath = path.resolve(__dirname, '../../config.json');

  if (!fs.existsSync(configPath)) {
    return null;
  }

  try {
    const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
    return validateConfig(config) ? config : null;
  } catch (error) {
    console.error(`[bumba-reader] Failed to read config: ${error.message}`);
    throw error;
  }
}

/**
 * Read Bumba design tokens from .design/tokens/
 * @returns {Object|null} - Token data organized by file name, or null if not found
 */
function readBumbaTokens() {
  const tokensPath = path.resolve(__dirname, '../../tokens/');

  if (!fs.existsSync(tokensPath)) {
    return null;
  }

  try {
    const tokenFiles = glob.sync(path.join(tokensPath, '*.json'));
    const tokens = {};

    tokenFiles.forEach(file => {
      try {
        const fileName = path.basename(file, '.json');
        tokens[fileName] = JSON.parse(fs.readFileSync(file, 'utf-8'));
      } catch (error) {
        console.warn(`[bumba-reader] Failed to read ${file}: ${error.message}`);
      }
    });

    return Object.keys(tokens).length > 0 ? tokens : null;
  } catch (error) {
    console.error(`[bumba-reader] Error reading tokens: ${error.message}`);
    return null;
  }
}

/**
 * Read Bumba components from .design/components/
 * @returns {Array|null} - Array of component metadata, or null if not found
 */
function readBumbaComponents() {
  const componentsPath = path.resolve(__dirname, '../../components/');

  if (!fs.existsSync(componentsPath)) {
    return null;
  }

  try {
    const componentFiles = glob.sync(path.join(componentsPath, '*.json'));
    const components = [];

    componentFiles.forEach(file => {
      try {
        const component = JSON.parse(fs.readFileSync(file, 'utf-8'));
        components.push({
          id: component.id,
          name: component.name,
          type: component.type,
          file: path.basename(file)
        });
      } catch (error) {
        console.warn(`[bumba-reader] Failed to read ${file}: ${error.message}`);
      }
    });

    return components.length > 0 ? components : null;
  } catch (error) {
    console.error(`[bumba-reader] Error reading components: ${error.message}`);
    return null;
  }
}

/**
 * Get framework preference from config
 * @param {Object|null} config - Bumba config object
 * @returns {string} - Framework name (default: 'react')
 */
function getFramework(config) {
  if (!config || !config.transformers) {
    return 'react';
  }

  return config.transformers.preferred ||
         (config.transformers.enabled && config.transformers.enabled[0]) ||
         'react';
}

/**
 * Get complete Bumba context (config, tokens, components, framework)
 * This is the main function to call for getting all Bumba information
 *
 * @returns {Object} - Complete context with boolean flags for availability
 */
function getBumbaContext() {
  const config = readBumbaConfig();
  const tokens = readBumbaTokens();
  const components = readBumbaComponents();
  const framework = getFramework(config);

  return {
    config,
    tokens,
    components,
    framework,
    hasConfig: config !== null,
    hasTokens: tokens !== null,
    hasComponents: components !== null
  };
}

module.exports = {
  readBumbaConfig,
  readBumbaTokens,
  readBumbaComponents,
  getFramework,
  getBumbaContext,
  validateConfig
};
