/**
 * PreToolUse Hook: Ensure Design System Modules
 *
 * Automatically ensures layout transformation tools are available in project
 * when design-layout-to-html skill is invoked.
 *
 * Architecture: Symlink Approach
 * - Canonical source: ~/.claude/shared-modules/design-system/
 * - Project location: <project>/server/
 * - Method: Symlinks for automatic update propagation
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

// Hook configuration
const HOOK_NAME = 'ensure-design-system-modules';
const TRIGGER_SKILLS = ['design-layout-to-html', 'design-init'];

// Canonical module location
const CLAUDE_HOME = path.join(os.homedir(), '.claude');
const SHARED_MODULES_DIR = path.join(CLAUDE_HOME, 'shared-modules', 'design-system');

// Required modules
const REQUIRED_MODULES = [
  'layout-validator.js',
  'layout-to-html-transformer.js',
  'layout-transformer.js',
  'design-structure.js',
  'registry-manager.js',
  'component-content-extractor.js',
  'enhanced-component-transformer.js',
  'react-component-transformer.js'
];

/**
 * Check if current tool use is for a design skill that needs these modules
 */
function shouldActivate(toolUse) {
  // Check if it's a Skill tool invocation
  if (toolUse.tool !== 'Skill') {
    return false;
  }

  // Check if it's one of our trigger skills
  const skillName = toolUse.parameters?.skill || '';
  return TRIGGER_SKILLS.some(trigger => skillName.includes(trigger));
}

/**
 * Ensure a symlink exists, create if missing
 */
function ensureSymlink(sourcePath, targetPath) {
  const targetDir = path.dirname(targetPath);

  // Ensure target directory exists
  if (!fs.existsSync(targetDir)) {
    fs.mkdirSync(targetDir, { recursive: true });
  }

  // Check if symlink already exists and is valid
  if (fs.existsSync(targetPath)) {
    try {
      const stats = fs.lstatSync(targetPath);
      if (stats.isSymbolicLink()) {
        const linkTarget = fs.readlinkSync(targetPath);
        if (linkTarget === sourcePath) {
          // Valid symlink already exists
          return { created: false, existed: true, path: targetPath };
        } else {
          // Symlink points to wrong location, remove it
          fs.unlinkSync(targetPath);
        }
      } else {
        // Regular file exists, back it up
        const backupPath = `${targetPath}.backup-${Date.now()}`;
        fs.renameSync(targetPath, backupPath);
        process.stderr.write(`[${HOOK_NAME}] Backed up existing file: ${path.basename(targetPath)} → ${path.basename(backupPath)}\n`);
      }
    } catch (error) {
      process.stderr.write(`[${HOOK_NAME}] Error checking existing file: ${error.message}\n`);
    }
  }

  // Create symlink
  try {
    fs.symlinkSync(sourcePath, targetPath);
    return { created: true, existed: false, path: targetPath };
  } catch (error) {
    throw new Error(`Failed to create symlink: ${error.message}`);
  }
}

/**
 * Main hook execution
 */
function execute(context) {
  const { toolUse, workingDirectory } = context;

  // Check if we should activate for this tool use
  if (!shouldActivate(toolUse)) {
    return {
      proceed: true,
      message: null
    };
  }

  process.stderr.write(`[${HOOK_NAME}] Ensuring design system modules are available...\n`);

  // Verify shared modules exist
  if (!fs.existsSync(SHARED_MODULES_DIR)) {
    return {
      proceed: false,
      message: `Shared modules directory not found: ${SHARED_MODULES_DIR}\nRun setup to create it.`
    };
  }

  // Determine project root (look for server/ directory)
  let projectRoot = workingDirectory;
  let serverDir = path.join(projectRoot, 'server');

  // If no server/ dir, check parent directories (up to 3 levels)
  for (let i = 0; i < 3 && !fs.existsSync(serverDir); i++) {
    projectRoot = path.dirname(projectRoot);
    serverDir = path.join(projectRoot, 'server');
  }

  if (!fs.existsSync(serverDir)) {
    // No server directory found, create it
    fs.mkdirSync(serverDir, { recursive: true });
    process.stderr.write(`[${HOOK_NAME}] Created server directory: ${serverDir}\n`);
  }

  // Ensure symlinks for all required modules
  const results = {
    created: [],
    existed: [],
    failed: []
  };

  for (const moduleName of REQUIRED_MODULES) {
    const sourcePath = path.join(SHARED_MODULES_DIR, moduleName);
    const targetPath = path.join(serverDir, moduleName);

    // Verify source exists
    if (!fs.existsSync(sourcePath)) {
      results.failed.push({
        module: moduleName,
        reason: `Source not found: ${sourcePath}`
      });
      continue;
    }

    try {
      const result = ensureSymlink(sourcePath, targetPath);
      if (result.created) {
        results.created.push(moduleName);
      } else if (result.existed) {
        results.existed.push(moduleName);
      }
    } catch (error) {
      results.failed.push({
        module: moduleName,
        reason: error.message
      });
    }
  }

  // Report results
  if (results.created.length > 0) {
    process.stderr.write(`[${HOOK_NAME}] ✓ Created symlinks: ${results.created.join(', ')}\n`);
  }

  if (results.existed.length > 0) {
    process.stderr.write(`[${HOOK_NAME}] ✓ Existing symlinks valid: ${results.existed.join(', ')}\n`);
  }

  if (results.failed.length > 0) {
    const failedDetails = results.failed.map(f => `${f.module}: ${f.reason}`).join('\n  ');
    return {
      proceed: false,
      message: `Failed to ensure some modules:\n  ${failedDetails}`
    };
  }

  process.stderr.write(`[${HOOK_NAME}] All design system modules ready\n`);

  return {
    proceed: true,
    message: null
  };
}

module.exports = execute;
