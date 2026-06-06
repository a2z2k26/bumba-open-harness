#!/usr/bin/env node

/**
 * Design Bridge Plugin System
 * Sprint 19: Extensible Plugin Architecture
 *
 * Features:
 * - Dynamic plugin loading and unloading
 * - Secure plugin sandbox execution
 * - Plugin dependency management
 * - Hook-based extension points
 * - Plugin marketplace integration
 * - Performance monitoring
 * - Security validation
 */

const EventEmitter = require('events');
const fs = require('fs').promises;
const path = require('path');
const vm = require('vm');
const crypto = require('crypto');

class PluginSystem extends EventEmitter {
  constructor(config = {}) {
    super();

    this.config = {
      pluginsDirectory: config.pluginsDirectory || './plugins',
      sandboxTimeout: config.sandboxTimeout || 30000,
      maxMemoryUsage: config.maxMemoryUsage || 128 * 1024 * 1024, // 128MB
      allowedAPIs: config.allowedAPIs || ['fs', 'path', 'crypto', 'events'],
      marketplaceUrl: config.marketplaceUrl || 'https://design-bridge-plugins.dev',
      trustedPublishers: config.trustedPublishers || [],
      autoUpdate: config.autoUpdate || false,
      enableTelemetry: config.enableTelemetry || true,
      ...config
    };

    this.plugins = new Map();
    this.hooks = new Map();
    this.dependencies = new Map();
    this.sandboxes = new Map();
    this.metrics = new Map();
    this.security = new PluginSecurityManager(this.config);

    this.initialized = false;
    this.setupHooks();
  }

  setupHooks() {
    // Core extension points
    const coreHooks = [
      'before-generate',
      'after-generate',
      'component-analyze',
      'style-transform',
      'code-optimize',
      'export-prepare',
      'sync-conflict',
      'version-merge',
      'accessibility-check',
      'performance-audit'
    ];

    coreHooks.forEach(hook => {
      this.hooks.set(hook, []);
    });
  }

  async initialize() {
    if (this.initialized) return;

    console.log('Initializing Plugin System...');

    try {
      await this.ensurePluginsDirectory();
      await this.loadInstalledPlugins();
      await this.validateDependencies();

      if (this.config.autoUpdate) {
        await this.checkForUpdates();
      }

      this.initialized = true;
      this.emit('system-initialized');
      console.log(`✅ Plugin System initialized with ${this.plugins.size} plugins`);

    } catch (error) {
      console.error('❌ Plugin System initialization failed:', error);
      throw error;
    }
  }

  async ensurePluginsDirectory() {
    try {
      await fs.mkdir(this.config.pluginsDirectory, { recursive: true });
    } catch (error) {
      if (error.code !== 'EEXIST') {
        throw error;
      }
    }
  }

  async loadInstalledPlugins() {
    const pluginDirs = await fs.readdir(this.config.pluginsDirectory, { withFileTypes: true });

    for (const dirent of pluginDirs) {
      if (dirent.isDirectory()) {
        try {
          await this.loadPlugin(dirent.name);
        } catch (error) {
          console.warn(`⚠️ Failed to load plugin ${dirent.name}:`, error.message);
        }
      }
    }
  }

  async loadPlugin(pluginName) {
    const pluginPath = path.join(this.config.pluginsDirectory, pluginName);
    const manifestPath = path.join(pluginPath, 'plugin.json');

    try {
      const manifestContent = await fs.readFile(manifestPath, 'utf8');
      const manifest = JSON.parse(manifestContent);

      // Security validation
      await this.security.validatePlugin(manifest, pluginPath);

      // Load plugin code
      const mainPath = path.join(pluginPath, manifest.main || 'index.js');
      const pluginCode = await fs.readFile(mainPath, 'utf8');

      // Create sandbox
      const sandbox = this.createPluginSandbox(manifest, pluginPath);
      const context = vm.createContext(sandbox);

      // Execute plugin in sandbox
      const script = new vm.Script(pluginCode, { filename: mainPath });
      const pluginModule = script.runInContext(context, {
        timeout: this.config.sandboxTimeout,
        breakOnSigint: true
      });

      // Initialize plugin
      const plugin = {
        name: pluginName,
        manifest,
        instance: pluginModule,
        sandbox,
        context,
        loaded: Date.now(),
        metrics: {
          executions: 0,
          totalTime: 0,
          errors: 0,
          lastExecution: null
        }
      };

      // Register plugin hooks
      await this.registerPluginHooks(plugin);

      // Store plugin
      this.plugins.set(pluginName, plugin);
      this.emit('plugin-loaded', plugin);

      console.log(`✅ Loaded plugin: ${pluginName} v${manifest.version}`);
      return plugin;

    } catch (error) {
      console.error(`❌ Failed to load plugin ${pluginName}:`, error);
      throw error;
    }
  }

  createPluginSandbox(manifest, pluginPath) {
    const sandbox = {
      console: {
        log: (...args) => console.log(`[${manifest.name}]`, ...args),
        error: (...args) => console.error(`[${manifest.name}]`, ...args),
        warn: (...args) => console.warn(`[${manifest.name}]`, ...args)
      },
      setTimeout,
      clearTimeout,
      setInterval,
      clearInterval,
      Buffer,
      process: {
        env: process.env,
        nextTick: process.nextTick
      },
      __dirname: pluginPath,
      __filename: path.join(pluginPath, manifest.main || 'index.js'),
      require: this.createSafeRequire(pluginPath, manifest),
      module: { exports: {} },
      exports: {}
    };

    // Add allowed Node.js APIs
    if (this.config.allowedAPIs.includes('fs')) {
      sandbox.fs = require('fs');
    }
    if (this.config.allowedAPIs.includes('path')) {
      sandbox.path = require('path');
    }
    if (this.config.allowedAPIs.includes('crypto')) {
      sandbox.crypto = require('crypto');
    }
    if (this.config.allowedAPIs.includes('events')) {
      sandbox.EventEmitter = EventEmitter;
    }

    return sandbox;
  }

  createSafeRequire(pluginPath, manifest) {
    return (id) => {
      // Allow relative requires within plugin directory
      if (id.startsWith('./') || id.startsWith('../')) {
        const fullPath = path.resolve(pluginPath, id);
        if (!fullPath.startsWith(pluginPath)) {
          throw new Error('Plugin cannot require files outside its directory');
        }
        return require(fullPath);
      }

      // Allow declared dependencies
      if (manifest.dependencies && manifest.dependencies[id]) {
        return require(id);
      }

      // Allow core Node.js modules if permitted
      const coreModules = ['events', 'util', 'path', 'crypto'];
      if (coreModules.includes(id) && this.config.allowedAPIs.includes(id)) {
        return require(id);
      }

      throw new Error(`Plugin cannot require '${id}': not in allowed dependencies`);
    };
  }

  async registerPluginHooks(plugin) {
    const { manifest, instance } = plugin;

    if (manifest.hooks && typeof instance.registerHooks === 'function') {
      for (const hookName of manifest.hooks) {
        if (this.hooks.has(hookName)) {
          const hookHandler = {
            plugin: plugin.name,
            handler: instance[`on${hookName.replace(/-./g, x => x[1].toUpperCase())}`],
            priority: manifest.priority || 0
          };

          if (typeof hookHandler.handler === 'function') {
            this.hooks.get(hookName).push(hookHandler);
            // Sort by priority (higher first)
            this.hooks.get(hookName).sort((a, b) => b.priority - a.priority);
          }
        }
      }
    }
  }

  async executeHook(hookName, context = {}) {
    const handlers = this.hooks.get(hookName) || [];
    const results = [];

    for (const handler of handlers) {
      try {
        const startTime = Date.now();
        const plugin = this.plugins.get(handler.plugin);

        if (!plugin) continue;

        const result = await handler.handler.call(plugin.instance, context);

        // Update metrics
        const duration = Date.now() - startTime;
        plugin.metrics.executions++;
        plugin.metrics.totalTime += duration;
        plugin.metrics.lastExecution = Date.now();

        results.push({
          plugin: handler.plugin,
          result,
          duration
        });

        this.emit('hook-executed', {
          hook: hookName,
          plugin: handler.plugin,
          duration,
          success: true
        });

      } catch (error) {
        const plugin = this.plugins.get(handler.plugin);
        if (plugin) {
          plugin.metrics.errors++;
        }

        console.error(`Hook ${hookName} failed in plugin ${handler.plugin}:`, error);

        this.emit('hook-error', {
          hook: hookName,
          plugin: handler.plugin,
          error: error.message
        });
      }
    }

    return results;
  }

  async installPlugin(pluginName, source = 'marketplace') {
    console.log(`Installing plugin: ${pluginName}...`);

    try {
      let pluginData;

      if (source === 'marketplace') {
        pluginData = await this.downloadFromMarketplace(pluginName);
      } else if (source.startsWith('http://') || source.startsWith('https://')) {
        pluginData = await this.downloadFromUrl(source);
      } else {
        pluginData = await this.loadFromLocal(source);
      }

      // Validate plugin
      await this.security.validatePlugin(pluginData.manifest, pluginData.path);

      // Install dependencies
      if (pluginData.manifest.dependencies) {
        await this.installDependencies(pluginData.manifest.dependencies);
      }

      // Extract plugin
      const pluginPath = path.join(this.config.pluginsDirectory, pluginName);
      await this.extractPlugin(pluginData, pluginPath);

      // Load plugin
      await this.loadPlugin(pluginName);

      console.log(`✅ Plugin ${pluginName} installed successfully`);
      this.emit('plugin-installed', { name: pluginName, source });

    } catch (error) {
      console.error(`❌ Failed to install plugin ${pluginName}:`, error);
      throw error;
    }
  }

  async unloadPlugin(pluginName) {
    const plugin = this.plugins.get(pluginName);
    if (!plugin) {
      throw new Error(`Plugin ${pluginName} not found`);
    }

    try {
      // Call plugin cleanup
      if (typeof plugin.instance.cleanup === 'function') {
        await plugin.instance.cleanup();
      }

      // Remove from hooks
      for (const [hookName, handlers] of this.hooks) {
        const filtered = handlers.filter(h => h.plugin !== pluginName);
        this.hooks.set(hookName, filtered);
      }

      // Clean up sandbox
      if (plugin.context) {
        plugin.context = null;
      }

      // Remove from plugins
      this.plugins.delete(pluginName);

      console.log(`✅ Plugin ${pluginName} unloaded`);
      this.emit('plugin-unloaded', { name: pluginName });

    } catch (error) {
      console.error(`❌ Failed to unload plugin ${pluginName}:`, error);
      throw error;
    }
  }

  async uninstallPlugin(pluginName) {
    console.log(`Uninstalling plugin: ${pluginName}...`);

    try {
      // Unload first
      if (this.plugins.has(pluginName)) {
        await this.unloadPlugin(pluginName);
      }

      // Remove plugin directory
      const pluginPath = path.join(this.config.pluginsDirectory, pluginName);
      await fs.rm(pluginPath, { recursive: true, force: true });

      console.log(`✅ Plugin ${pluginName} uninstalled`);
      this.emit('plugin-uninstalled', { name: pluginName });

    } catch (error) {
      console.error(`❌ Failed to uninstall plugin ${pluginName}:`, error);
      throw error;
    }
  }

  async validateDependencies() {
    for (const [pluginName, plugin] of this.plugins) {
      const { manifest } = plugin;

      if (manifest.dependencies) {
        for (const [depName, depVersion] of Object.entries(manifest.dependencies)) {
          try {
            require.resolve(depName);
          } catch (error) {
            console.warn(`⚠️ Plugin ${pluginName} missing dependency: ${depName}@${depVersion}`);
          }
        }
      }
    }
  }

  getPluginMetrics(pluginName) {
    const plugin = this.plugins.get(pluginName);
    return plugin ? plugin.metrics : null;
  }

  getAllMetrics() {
    const metrics = {};
    for (const [name, plugin] of this.plugins) {
      metrics[name] = plugin.metrics;
    }
    return metrics;
  }

  listPlugins() {
    return Array.from(this.plugins.entries()).map(([name, plugin]) => ({
      name,
      version: plugin.manifest.version,
      author: plugin.manifest.author,
      description: plugin.manifest.description,
      loaded: new Date(plugin.loaded).toISOString(),
      metrics: plugin.metrics
    }));
  }

  async createHook(name, description = '') {
    if (this.hooks.has(name)) {
      throw new Error(`Hook ${name} already exists`);
    }

    this.hooks.set(name, []);
    this.emit('hook-created', { name, description });
  }

  removeHook(name) {
    this.hooks.delete(name);
    this.emit('hook-removed', { name });
  }

  getHookNames() {
    return Array.from(this.hooks.keys());
  }

  async shutdown() {
    console.log('Shutting down Plugin System...');

    // Unload all plugins
    for (const pluginName of this.plugins.keys()) {
      try {
        await this.unloadPlugin(pluginName);
      } catch (error) {
        console.error(`Error unloading plugin ${pluginName}:`, error);
      }
    }

    this.emit('system-shutdown');
    console.log('✅ Plugin System shutdown complete');
  }
}

class PluginSecurityManager {
  constructor(config) {
    this.config = config;
    this.trustedHashes = new Set();
    this.blacklistedPlugins = new Set();
  }

  async validatePlugin(manifest, pluginPath) {
    // Basic validation
    if (!manifest.name || !manifest.version) {
      throw new Error('Plugin manifest missing required fields');
    }

    // Check blacklist
    if (this.blacklistedPlugins.has(manifest.name)) {
      throw new Error(`Plugin ${manifest.name} is blacklisted`);
    }

    // Validate publisher
    if (manifest.publisher && !this.config.trustedPublishers.includes(manifest.publisher)) {
      console.warn(`⚠️ Plugin from untrusted publisher: ${manifest.publisher}`);
    }

    // Hash verification for trusted plugins
    if (manifest.hash) {
      const calculatedHash = await this.calculatePluginHash(pluginPath);
      if (calculatedHash !== manifest.hash) {
        throw new Error('Plugin integrity check failed');
      }
    }

    // Permissions check
    if (manifest.permissions) {
      this.validatePermissions(manifest.permissions);
    }

    return true;
  }

  validatePermissions(permissions) {
    const dangerousPermissions = ['fs:write', 'network:all', 'process:spawn'];

    for (const permission of permissions) {
      if (dangerousPermissions.includes(permission)) {
        console.warn(`⚠️ Plugin requests dangerous permission: ${permission}`);
      }
    }
  }

  async calculatePluginHash(pluginPath) {
    const hash = crypto.createHash('sha256');

    const files = await fs.readdir(pluginPath, { recursive: true });

    for (const file of files.sort()) {
      const filePath = path.join(pluginPath, file);
      const stat = await fs.stat(filePath);

      if (stat.isFile()) {
        const content = await fs.readFile(filePath);
        hash.update(content);
      }
    }

    return hash.digest('hex');
  }
}

module.exports = PluginSystem;