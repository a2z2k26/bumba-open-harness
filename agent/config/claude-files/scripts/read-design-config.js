#!/usr/bin/env node
/**
 * read-design-config.js
 * Helper script to read and validate .design/config.json
 *
 * Usage:
 *   const { readDesignConfig } = require('./.claude/scripts/read-design-config');
 *   const config = readDesignConfig(projectPath);
 */

const fs = require('fs');
const path = require('path');

/**
 * Read design configuration from .design/config.json
 * @param {string} projectPath - Path to project root
 * @returns {object} Configuration object
 * @throws {Error} If config file not found or invalid
 */
function readDesignConfig(projectPath = process.cwd()) {
  const configPath = path.join(projectPath, '.design', 'config.json');

  // Check if config exists
  if (!fs.existsSync(configPath)) {
    throw new Error(
      `.design/config.json not found at ${configPath}\n` +
      `Run /design-init to initialize Design Bridge structure.`
    );
  }

  // Read and parse config
  try {
    const configContent = fs.readFileSync(configPath, 'utf8');
    const config = JSON.parse(configContent);

    // Validate required fields
    validateConfig(config);

    return config;
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new Error(
        `Invalid JSON in .design/config.json:\n${error.message}`
      );
    }
    throw error;
  }
}

/**
 * Validate configuration object
 * @param {object} config - Configuration to validate
 * @throws {Error} If config is invalid
 */
function validateConfig(config) {
  const errors = [];

  // Check version
  if (!config.version) {
    errors.push('Missing config.version');
  }

  // Check project section
  if (!config.project) {
    errors.push('Missing config.project section');
  } else {
    if (!config.project.framework) {
      errors.push('Missing config.project.framework');
    }
    if (config.project.typescript === undefined) {
      errors.push('Missing config.project.typescript');
    }
    if (!config.project.outputPath) {
      errors.push('Missing config.project.outputPath');
    }
  }

  // Check figma section
  if (!config.figma) {
    errors.push('Missing config.figma section');
  }

  // Check transformers section
  if (!config.transformers) {
    errors.push('Missing config.transformers section');
  }

  if (errors.length > 0) {
    throw new Error(
      `Invalid configuration:\n${errors.map(e => `  - ${e}`).join('\n')}`
    );
  }
}

/**
 * Get framework-specific configuration
 * @param {object} config - Full configuration
 * @returns {object} Framework-specific config
 */
function getFrameworkConfig(config) {
  const framework = config.project.framework;
  return config.transformers.options[framework] || {};
}

/**
 * Check if feature is enabled
 * @param {object} config - Full configuration
 * @param {string} feature - Feature name (e.g., 'autoSync', 'storybook')
 * @returns {boolean} Whether feature is enabled
 */
function isFeatureEnabled(config, feature) {
  switch (feature) {
    case 'autoSync':
      return config.figma?.autoSync || false;
    case 'storybook':
      return config.storybook?.enabled || false;
    case 'backups':
      return config.output?.createBackups || false;
    case 'tests':
      const frameworkConfig = getFrameworkConfig(config);
      return frameworkConfig?.generateTests || false;
    default:
      return false;
  }
}

// CLI usage
if (require.main === module) {
  const projectPath = process.argv[2] || process.cwd();

  try {
    const config = readDesignConfig(projectPath);
    console.log(JSON.stringify(config, null, 2));
  } catch (error) {
    console.error(`Error: ${error.message}`);
    process.exit(1);
  }
}

module.exports = {
  readDesignConfig,
  validateConfig,
  getFrameworkConfig,
  isFeatureEnabled
};
