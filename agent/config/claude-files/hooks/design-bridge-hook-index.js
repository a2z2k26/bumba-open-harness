/**
 * Hook Registry - Central hook management system
 *
 * @version 2.0.0
 * @phase Phase 5 - Two-State Architecture Integration
 *
 * Usage:
 *   const { loadHooks, trigger, getStatus } = require('./.claude/hooks');
 *   loadHooks();
 *   await trigger('on-registry-change', { path: '...', data: {...} });
 *
 * Hook Priorities (lower = earlier):
 *   - on-component-extract: 50 (first)
 *   - on-component-transform: 100 (after extract)
 *   - on-cascade-complete: 300 (after cascade sync)
 *   - on-registry-change: 400 (last)
 *
 * Event-driven hooks:
 *   - on-cascade-complete: watch=null, triggered by cascade:completed events
 */
const fs = require('fs');
const path = require('path');

// Hook priority constants for documentation and consistency
const HOOK_PRIORITIES = {
  'on-component-extract': 50,    // First - processes raw extracted data
  'on-component-transform': 100, // After extract - generates stories
  'on-cascade-complete': 300,    // After cascade sync from Phase 4
  'on-registry-change': 400      // Last - responds to registry updates
};

// Registered hooks
const hooks = {};

// Hook status tracking
const status = {
  loaded: [],
  failed: [],
  disabled: [],
  lastRun: {}
};

// Reference to SyncCascade for event subscription (set via connectSyncCascade)
let syncCascadeRef = null;

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

  // Scan for hook files
  const files = fs.readdirSync(hookDir)
    .filter(f => f.endsWith('.js') && f !== 'index.js' && f !== 'test-hooks.js');

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
 * Note: watch can be null for event-driven hooks (e.g., on-cascade-complete)
 */
function validateHook(hook, filename) {
  if (!hook.name) {
    throw new Error(`Missing 'name' property`);
  }

  // watch can be null for event-driven hooks
  if (hook.watch === undefined) {
    throw new Error(`Missing 'watch' property (use null for event-driven hooks)`);
  }

  if (!hook.execute) {
    throw new Error(`Missing 'execute' property`);
  }

  if (typeof hook.execute !== 'function') {
    throw new Error(`'execute' must be a function`);
  }
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
      // Watch pattern match
      if (data.path && h.watch) {
        const watchPattern = h.watch.replace(/^\.\//, '').replace(/^\.design\//, '');
        if (data.path.includes(watchPattern) || data.path.endsWith(watchPattern)) {
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

/**
 * Connect SyncCascade to hook registry for event-driven hooks
 * This allows cascade:completed events to trigger on-cascade-complete hook
 * @param {Object} syncCascade - SyncCascade instance from Phase 4
 */
function connectSyncCascade(syncCascade) {
  if (!syncCascade) {
    process.stderr.write('[HookRegistry] Cannot connect null SyncCascade\n');
    return;
  }

  // Store reference
  syncCascadeRef = syncCascade;

  // Subscribe to cascade events
  syncCascade.on('cascade:completed', async (data) => {
    process.stderr.write('[HookRegistry] Received cascade:completed event\n');
    await trigger('on-cascade-complete', data);
  });

  syncCascade.on('cascade:failed', async (data) => {
    process.stderr.write('[HookRegistry] Received cascade:failed event\n');
    // Optionally trigger hook even on failure for logging/cleanup
    await trigger('on-cascade-complete', { ...data, success: false });
  });

  process.stderr.write('[HookRegistry] Connected to SyncCascade events\n');
}

/**
 * Disconnect from SyncCascade events
 */
function disconnectSyncCascade() {
  if (syncCascadeRef) {
    syncCascadeRef.removeAllListeners('cascade:completed');
    syncCascadeRef.removeAllListeners('cascade:failed');
    syncCascadeRef = null;
    process.stderr.write('[HookRegistry] Disconnected from SyncCascade\n');
  }
}

/**
 * Get connected SyncCascade reference
 * @returns {Object|null} SyncCascade instance or null
 */
function getSyncCascade() {
  return syncCascadeRef;
}

module.exports = {
  loadHooks,
  reloadHooks,
  trigger,
  setEnabled,
  getStatus,
  getHook,
  listHooks,
  connectSyncCascade,
  disconnectSyncCascade,
  getSyncCascade,
  HOOK_PRIORITIES,
  hooks
};
