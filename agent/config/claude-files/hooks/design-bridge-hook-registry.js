/**
 * Hook Registry - Central hook management system
 *
 * Usage:
 *   const { loadHooks, trigger, getStatus } = require('./.claude/hooks/design-bridge-hook-registry');
 *   loadHooks();
 *   await trigger('on-registry-change', { path: '...', data: {...} });
 */
const fs = require('fs');
const path = require('path');

// Registered hooks
const hooks = {};

// Hook status tracking
const status = {
  loaded: [],
  failed: [],
  disabled: [],
  lastRun: {}
};

/**
 * Load all hooks from the hooks directory
 * @returns {Object} Load summary
 */
function loadHooks() {
  const hookDir = __dirname;

  // Reset status
  status.loaded = [];
  status.failed = [];
  status.disabled = [];

  // Scan for hook files (exclude utility/index files)
  const excludeFiles = [
    'design-bridge-hook-registry.js',
    'design-bridge-hook-index.js',
    'test-hooks.js',
    'trigger-design-hooks.js',
    'on-design-server-setup.js',  // Standalone script, not a hook module
    'index.js'
  ];
  const files = fs.readdirSync(hookDir)
    .filter(f => f.endsWith('.js') && !excludeFiles.includes(f) && !f.startsWith('test'));

  process.stderr.write(`[HookRegistry] Found ${files.length} hook files\n`);

  for (const file of files) {
    const hookPath = path.join(hookDir, file);

    try {
      // Clear require cache for hot reload
      delete require.cache[require.resolve(hookPath)];

      const hook = require(hookPath);

      // Validate hook structure
      validateHook(hook, file);

      // Register hook
      hooks[hook.name] = hook;

      if (hook.enabled === false) {
        status.disabled.push(hook.name);
        process.stderr.write(`[HookRegistry] Loaded (disabled): ${hook.name}\n`);
      } else {
        status.loaded.push(hook.name);
        process.stderr.write(`[HookRegistry] Loaded: ${hook.name}\n`);
      }

    } catch (error) {
      status.failed.push({ file, error: error.message });
      process.stderr.write(`[HookRegistry] Failed to load ${file}: ${error.message}\n`);
    }
  }

  return {
    loaded: status.loaded.length,
    disabled: status.disabled.length,
    failed: status.failed.length
  };
}

/**
 * Validate hook has required properties and structure
 */
function validateHook(hook, filename) {
  if (!hook.name) {
    throw new Error(`Missing 'name' property`);
  }

  // watch can be null for event-driven hooks (not file-watch based)
  // So we only check if execute exists

  if (!hook.execute) {
    throw new Error(`Missing 'execute' property`);
  }

  if (typeof hook.execute !== 'function') {
    throw new Error(`'execute' must be a function`);
  }
}

/**
 * Convert glob pattern to regex for matching
 * @param {string} pattern - Glob pattern (e.g., .design/tokens/wildcard/wildcard.json)
 * @returns {RegExp} Regular expression for matching
 */
function globToRegex(pattern) {
  // Normalize the pattern - remove leading ./ or ./
  let normalized = pattern.replace(/^\.\//, '').replace(/^\.design\//, '');

  // Escape special regex characters except * and **
  let regexStr = normalized
    .replace(/[.+^${}()|[\]\\]/g, '\\$&')  // Escape special chars
    .replace(/\*\*/g, '{{GLOBSTAR}}')       // Temp placeholder for **
    .replace(/\*/g, '[^/]*')                // * matches anything except /
    .replace(/\{\{GLOBSTAR\}\}/g, '.*');    // ** matches anything including /

  return new RegExp(regexStr);
}

/**
 * Check if a file path matches a watch pattern (supports globs)
 * @param {string} filePath - File path to check
 * @param {string|string[]} watchPattern - Pattern or array of patterns
 * @returns {boolean} True if path matches any pattern
 */
function matchesWatchPattern(filePath, watchPattern) {
  if (!filePath || !watchPattern) return false;

  // Normalize the file path
  const normalizedPath = filePath.replace(/\\/g, '/');

  // Handle array of patterns
  const patterns = Array.isArray(watchPattern) ? watchPattern : [watchPattern];

  for (const pattern of patterns) {
    // Simple string check first (for exact paths like 'config.json')
    const simplePattern = pattern.replace(/^\.\//, '').replace(/^\.design\//, '');
    if (normalizedPath.includes(simplePattern) || normalizedPath.endsWith(simplePattern)) {
      return true;
    }

    // Glob pattern matching
    if (pattern.includes('*')) {
      const regex = globToRegex(pattern);
      if (regex.test(normalizedPath)) {
        return true;
      }
    }
  }

  return false;
}

/**
 * Trigger hooks matching an event name
 * @param {string} eventName - Event name or hook name to trigger
 * @param {Object} data - Event data to pass to hooks
 * @returns {Promise<Array>} Results from all triggered hooks
 */
async function trigger(eventName, data) {
  // Find matching hooks
  const matchingHooks = Object.values(hooks)
    .filter(h => {
      // Exact match
      if (h.name === eventName) return true;
      // Prefix match (e.g., 'on-registry' matches 'on-registry-change')
      if (h.name.startsWith(eventName + '-')) return true;
      // Watch pattern match (supports arrays and globs)
      if (data.path && h.watch) {
        if (matchesWatchPattern(data.path, h.watch)) {
          return true;
        }
      }
      return false;
    })
    .filter(h => h.enabled !== false)
    .sort((a, b) => (a.priority || 100) - (b.priority || 100));

  if (matchingHooks.length === 0) {
    process.stderr.write(`[HookRegistry] No hooks matched event: ${eventName}\n`);
    return [];
  }

  process.stderr.write(`[HookRegistry] Triggering ${matchingHooks.length} hook(s) for: ${eventName}\n`);

  const results = [];

  for (const hook of matchingHooks) {
    const startTime = Date.now();

    try {
      const result = await hook.execute(data);
      const duration = Date.now() - startTime;

      status.lastRun[hook.name] = {
        timestamp: new Date().toISOString(),
        duration,
        success: result.success
      };

      results.push({
        hook: hook.name,
        duration,
        ...result
      });

    } catch (error) {
      const duration = Date.now() - startTime;

      status.lastRun[hook.name] = {
        timestamp: new Date().toISOString(),
        duration,
        success: false,
        error: error.message
      };

      results.push({
        hook: hook.name,
        duration,
        success: false,
        message: error.message,
        error
      });

      // Log but don't stop other hooks
      process.stderr.write(`[HookRegistry] Hook ${hook.name} failed: ${error.message}\n`);
    }
  }

  return results;
}

/**
 * Enable or disable a hook
 * @param {string} hookName - Name of hook to toggle
 * @param {boolean} enabled - Whether to enable or disable
 */
function setEnabled(hookName, enabled) {
  const hook = hooks[hookName];
  if (!hook) {
    throw new Error(`Hook not found: ${hookName}`);
  }

  hook.enabled = enabled;
  process.stderr.write(`[HookRegistry] ${hookName} ${enabled ? 'enabled' : 'disabled'}\n`);
}

/**
 * Get current status of all hooks
 * @returns {Object} Status summary
 */
function getStatus() {
  return {
    hooks: Object.keys(hooks).map(name => ({
      name,
      enabled: hooks[name].enabled !== false,
      watch: hooks[name].watch,
      debounce: hooks[name].debounce,
      priority: hooks[name].priority || 100,
      lastRun: status.lastRun[name] || null
    })),
    summary: {
      total: Object.keys(hooks).length,
      enabled: Object.values(hooks).filter(h => h.enabled !== false).length,
      disabled: Object.values(hooks).filter(h => h.enabled === false).length
    },
    loadStatus: {
      loaded: status.loaded,
      failed: status.failed,
      disabled: status.disabled
    }
  };
}

/**
 * Get a specific hook by name
 * @param {string} name - Hook name
 * @returns {Object|null} Hook object or null
 */
function getHook(name) {
  return hooks[name] || null;
}

/**
 * Reload all hooks (hot reload)
 */
function reloadHooks() {
  process.stderr.write('[HookRegistry] Reloading all hooks...\n');

  // Clear existing hooks
  for (const name of Object.keys(hooks)) {
    delete hooks[name];
  }

  return loadHooks();
}

/**
 * List all registered hook names
 * @returns {string[]} Array of hook names
 */
function listHooks() {
  return Object.keys(hooks);
}

module.exports = {
  loadHooks,
  reloadHooks,
  trigger,
  setEnabled,
  getStatus,
  getHook,
  listHooks,
  hooks
};
