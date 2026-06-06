/**
 * Plugin Bridge - Communication layer between Figma Plugin and BUMBA CLI
 * Handles real-time sync and token exchange
 *
 * v2.0.0: Added unified registry integration for tokens
 * - Tokens are now registered in .design/registries/tokens.json via AutoRegistrar
 * - Enables O(1) token lookups and component dependency tracking
 *
 * @fires PluginBridge#tokens:received - When tokens are received from Figma
 * @fires PluginBridge#tokens:registered - When tokens are registered in unified registry
 * @fires PluginBridge#transform:started - When auto-transform begins
 * @fires PluginBridge#transform:completed - When auto-transform succeeds
 * @fires PluginBridge#transform:failed - When auto-transform fails
 *
 * @example
 * const bridge = new PluginBridge();
 *
 * bridge.on('transform:started', (data) => {
 *   console.log(`Transforming ${data.tokenCount} tokens to ${data.framework}`);
 * });
 *
 * bridge.on('transform:completed', (data) => {
 *   console.log(`Generated ${data.componentsGenerated} components`);
 * });
 *
 * bridge.on('transform:failed', (data) => {
 *   console.error(`Transform failed: ${data.error}`);
 * });
 */

const { EventEmitter } = require('events');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

// Lazy-load AutoRegistrar to avoid circular dependencies
let _autoRegistrar = null;
function getAutoRegistrar(projectPath) {
  if (!_autoRegistrar) {
    try {
      const { AutoRegistrar } = require('./auto-registrar');
      _autoRegistrar = new AutoRegistrar({ projectPath });
    } catch (e) {
      console.warn('[PluginBridge] AutoRegistrar not available:', e.message);
      return null;
    }
  }
  return _autoRegistrar;
}

// Lazy load generators to avoid circular dependencies
let MultiFrameworkGenerator, getOptimizerRegistry;

// Auto-registration support (Phase 2: Two-State Architecture)
const { AutoRegistrar } = require('./auto-registrar');
// Optional dependencies - fallback for testing without express/ws
let express, cors, WebSocket;
try {
  express = require('express');
  cors = require('cors');
  WebSocket = require('ws');
} catch (e) {
  // Fallback for testing
}

// Chat handler for Claude Code CLI integration
let chatHandler;
try {
  chatHandler = require('./mcp/utils/chat-handler');
} catch (e) {
  console.warn('[PluginBridge] Chat handler not available:', e.message);
}

class PluginBridge extends EventEmitter {
  constructor(options = {}) {
    super();
    this.port = options.port || 9001;
    this.wsPort = options.wsPort || 9002;
    this.app = express ? express() : null;
    this.server = null;
    this.wsServer = null;
    this.connectedPlugins = new Map();
    this.sessionToken = this.generateSessionToken();
    this.generator = null; // Lazy-initialized generator for auto-transform
    this.lastSyncTime = null; // Last successful sync timestamp

    // Auto-registration config (Phase 2: Two-State Architecture)
    this.autoRegisterOnImport = options.autoRegisterOnImport !== false;
    this.autoRegistrar = null; // Lazily initialized when project is bound

    // Chat handler for Create tab integration
    this.chatHandler = null;

    if (express) {
      this.setupExpress();
      this.setupWebSocket();
    }
  }

  /**
   * Initialize or get AutoRegistrar instance
   * @returns {AutoRegistrar|null} Registrar instance or null if no project bound
   */
  getAutoRegistrar() {
    if (!this.boundProject?.path) {
      return null;
    }

    if (!this.autoRegistrar || this.autoRegistrar.projectPath !== this.boundProject.path) {
      this.autoRegistrar = new AutoRegistrar({
        projectPath: this.boundProject.path,
        autoRegisterOnImport: this.autoRegisterOnImport,
        emitEvents: true
      });

      // Forward registration events
      this.autoRegistrar.onRegistered((result) => {
        console.log(`[PluginBridge] Auto-registered: ${result.id}`);
        this.emit('component:registered', result);
      });

      this.autoRegistrar.onError((error) => {
        console.error(`[PluginBridge] Registration error:`, error.error?.message || error);
      });
    }

    return this.autoRegistrar;
  }

  /**
   * Check if auto-registration should occur
   * @returns {boolean}
   */
  shouldAutoRegister() {
    return this.autoRegisterOnImport && this.boundProject?.path;
  }

  // ==========================================
  // Chat Handler - Claude Code CLI Integration
  // ==========================================

  /**
   * Initialize the chat handler for Claude Code CLI integration
   * This enables the Create tab to trigger Claude for design tasks
   */
  initializeChatHandler() {
    if (!chatHandler) {
      console.warn('[PluginBridge] Chat handler module not available');
      return;
    }

    // Find MCP config path
    const mcpConfigPath = this.findMcpConfigPath();

    if (mcpConfigPath) {
      chatHandler.setMcpConfigPath(mcpConfigPath);
      console.log(`[PluginBridge] Chat handler using MCP config: ${mcpConfigPath}`);
    } else {
      console.warn('[PluginBridge] MCP config not found - chat may not work correctly');
    }

    // Set working directory to bound project or current directory
    const workingDir = this.boundProject?.path || process.cwd();
    chatHandler.setWorkingDirectory(workingDir);

    // Set up status callback to broadcast to WebSocket clients
    chatHandler.setStatusCallback((status) => {
      this.broadcastToPlugins({
        type: 'chat:status',
        payload: status
      });
    });

    this.chatHandler = chatHandler;
    console.log('[PluginBridge] Chat handler initialized');
  }

  /**
   * Find the MCP configuration file path
   * @returns {string|null} Path to MCP config or null if not found
   */
  findMcpConfigPath() {
    const possiblePaths = [
      // Project-level MCP config
      this.boundProject?.path ? path.join(this.boundProject.path, '.mcp.json') : null,
      this.boundProject?.path ? path.join(this.boundProject.path, 'mcp.json') : null,
      // Server-level MCP config
      path.join(__dirname, 'mcp', 'mcp-config.json'),
      path.join(__dirname, 'mcp.json'),
      // User-level MCP config
      path.join(process.env.HOME || '', '.claude', 'mcp.json'),
    ].filter(Boolean);

    for (const configPath of possiblePaths) {
      if (fs.existsSync(configPath)) {
        return configPath;
      }
    }

    return null;
  }

  // ==========================================
  // Naming Utility - Single source of truth
  // ==========================================

  /**
   * Convert component name to consistent naming formats
   * @param {string} rawName - Original component name (e.g., "button-primary", "Card Header")
   * @returns {Object} { fileName, componentName, cssClassName }
   *
   * Examples:
   *   "button-primary" => { fileName: "buttonprimary", componentName: "ButtonPrimary", cssClassName: "button-primary" }
   *   "Card Header"    => { fileName: "cardheader", componentName: "CardHeader", cssClassName: "card-header" }
   *   "MyComponent"    => { fileName: "mycomponent", componentName: "MyComponent", cssClassName: "my-component" }
   */
  getComponentNames(rawName) {
    // Sanitize: keep only alphanumeric, dashes, underscores, spaces
    const sanitized = (rawName || 'Component').replace(/[^a-zA-Z0-9-_\s]/g, '');

    // Normalize separators: convert spaces and underscores to dashes
    const normalized = sanitized.replace(/[\s_]+/g, '-').toLowerCase();

    // Split on dashes for word boundaries
    const parts = normalized.split('-').filter(p => p.length > 0);

    // PascalCase: capitalize first letter of each part
    const componentName = parts
      .map(part => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
      .join('');

    // fileName: lowercase, no separators (for file system)
    const fileName = parts.join('').toLowerCase();

    // cssClassName: lowercase with dashes (for CSS/HTML)
    const cssClassName = parts.join('-').toLowerCase();

    return {
      fileName,       // "buttonprimary" - for file paths
      componentName,  // "ButtonPrimary" - for React exports/imports
      cssClassName    // "button-primary" - for CSS classes
    };
  }

  setupExpress() {
    // Middleware
    // CORS: Allow all origins for Figma plugin (runs in sandboxed iframe with null origin)
    this.app.use(cors({
      origin: true,  // Reflect request origin (allows null origin from Figma iframe)
      credentials: true,
      methods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
      allowedHeaders: ['Content-Type', 'X-Figma-Signature', 'X-Session-Id']
    }));
    this.app.use(express.json({ limit: '10mb' }));

    // Request logging middleware
    this.app.use((req, res, next) => {
      const timestamp = new Date().toISOString();
      console.log(`[${timestamp}] ${req.method} ${req.path} - Origin: ${req.headers.origin || 'none'}`);
      next();
    });

    // Health check
    this.app.get('/health', (req, res) => {
      res.json({
        status: 'running',
        version: '1.0.0',
        timestamp: new Date().toISOString(),
        connectedPlugins: this.connectedPlugins.size
      });
    });

    // Token submission endpoint
    this.app.post('/api/tokens', async (req, res) => {
      try {
        const { tokens, components, metadata, sessionId } = req.body;

        if (!this.validateSession(sessionId)) {
          return res.status(401).json({ error: 'Invalid session' });
        }

        // Process tokens through MCP bridge
        const result = await this.processTokens(tokens, metadata);

        // Process components if provided
        if (components && components.length > 0) {
          await this.processComponents(components, metadata);
        }

        // Update registry sync metadata (for manual sync from /api/tokens)
        const syncTimestamp = new Date().toISOString();
        this.lastSyncTime = syncTimestamp;
        await this.updateRegistrySyncMetadata(syncTimestamp);

        res.json({
          success: true,
          processed: result.processed,
          stored: result.stored,
          indexed: result.indexed,
          timestamp: syncTimestamp
        });

        // Emit event for other systems
        this.emit('tokens:received', { tokens, metadata, result });

        // Auto-transform if enabled (non-blocking)
        try {
          await this.autoTransformIfEnabled({ tokens, metadata, result });
        } catch (transformError) {
          console.error('Auto-transform error (non-blocking):', transformError.message);
          // Don't fail the token endpoint - auto-transform is optional
        }

      } catch (error) {
        console.error('Token processing error:', error);
        res.status(500).json({
          error: 'Token processing failed',
          message: error.message
        });
      }
    });

    // Sync status endpoint
    this.app.get('/api/sync/status', (req, res) => {
      res.json({
        status: 'connected',
        lastSync: this.lastSyncTime,
        pendingChanges: this.getPendingChanges(),
        cliVersion: this.getCLIVersion()
      });
    });

    // Sync trigger endpoint - handles manual and auto sync requests
    this.app.post('/api/sync', async (req, res) => {
      try {
        const { sessionId, components, tokens, metadata } = req.body;
        console.log(`[PluginBridge] Sync request received - components: ${components?.length || 0}, tokens: ${tokens?.length || 0}`);

        // Process components if provided
        let syncedComponents = 0;
        let syncedTokens = 0;

        if (components && components.length > 0) {
          for (const component of components) {
            try {
              await this.processComponents([component], metadata);
              syncedComponents++;
            } catch (err) {
              console.warn(`[PluginBridge] Failed to sync component ${component.name}: ${err.message}`);
            }
          }
        }

        // Process tokens if provided
        if (tokens && tokens.length > 0) {
          try {
            const result = await this.processTokens(tokens, metadata);
            syncedTokens = result.processed || tokens.length;
          } catch (err) {
            console.warn(`[PluginBridge] Failed to sync tokens: ${err.message}`);
          }
        }

        // Update last sync time
        this.lastSyncTime = new Date().toISOString();

        // Update registry sync metadata for all components
        await this.updateRegistrySyncMetadata(this.lastSyncTime);

        // Broadcast sync complete to connected WebSocket clients
        this.broadcastToPlugins({
          type: 'sync:complete',
          data: {
            syncedComponents,
            syncedTokens,
            timestamp: this.lastSyncTime
          }
        });

        res.json({
          success: true,
          syncedComponents,
          syncedTokens,
          timestamp: this.lastSyncTime
        });

      } catch (error) {
        console.error('[PluginBridge] Sync error:', error);
        res.status(500).json({
          success: false,
          error: error.message,
          timestamp: new Date().toISOString()
        });
      }
    });

    // Component extraction endpoints (singular for one component, plural for all)
    this.app.post('/api/component', async (req, res) => {
      try {
        const { components, metadata } = req.body;
        console.log(`[PluginBridge] Single component extraction - ${components?.length || 0} component(s)`);

        if (!components || components.length === 0) {
          return res.status(400).json({ error: 'No components provided' });
        }

        const results = await this.processComponents(components, metadata) || [];
        const syncTimestamp = new Date().toISOString();
        this.lastSyncTime = syncTimestamp;
        await this.updateRegistrySyncMetadata(syncTimestamp);

        res.json({
          success: true,
          components: results,
          timestamp: syncTimestamp
        });
      } catch (error) {
        console.error('[PluginBridge] Component extraction error:', error);
        res.status(500).json({ error: error.message });
      }
    });

    this.app.post('/api/components', async (req, res) => {
      try {
        const { components, metadata } = req.body;
        console.log(`[PluginBridge] All components extraction - ${components?.length || 0} component(s)`);

        if (!components || components.length === 0) {
          return res.status(400).json({ error: 'No components provided' });
        }

        const results = await this.processComponents(components, metadata) || [];
        const syncTimestamp = new Date().toISOString();
        this.lastSyncTime = syncTimestamp;
        await this.updateRegistrySyncMetadata(syncTimestamp);

        res.json({
          success: true,
          components: results,
          count: results.length,
          timestamp: syncTimestamp
        });
      } catch (error) {
        console.error('[PluginBridge] Components extraction error:', error);
        res.status(500).json({ error: error.message });
      }
    });

    // Full page extraction (tokens + components)
    this.app.post('/api/page', async (req, res) => {
      try {
        const { tokens, components, metadata } = req.body;
        console.log(`[PluginBridge] Full page extraction - tokens: ${tokens ? 'YES' : 'NO'}, components: ${components?.length || 0}`);

        let tokenResult = null;
        let componentResults = [];

        // Process tokens if provided
        if (tokens) {
          tokenResult = await this.processTokens(tokens, metadata);
        }

        // Process components if provided
        if (components && components.length > 0) {
          componentResults = await this.processComponents(components, metadata) || [];
        }

        const syncTimestamp = new Date().toISOString();
        this.lastSyncTime = syncTimestamp;
        await this.updateRegistrySyncMetadata(syncTimestamp);

        res.json({
          success: true,
          tokens: tokenResult,
          components: componentResults,
          stats: {
            tokensProcessed: tokenResult?.processed || 0,
            componentsProcessed: componentResults.length
          },
          timestamp: syncTimestamp
        });
      } catch (error) {
        console.error('[PluginBridge] Page extraction error:', error);
        res.status(500).json({ error: error.message });
      }
    });

    // Layout extraction endpoint
    this.app.post('/api/layouts', async (req, res) => {
      try {
        const { layout, screenshot, metadata } = req.body;
        console.log(`[PluginBridge] Layout extraction - ${layout?.name || 'unknown'}`);

        if (!layout) {
          return res.status(400).json({ error: 'No layout provided' });
        }

        // Save layout to .design/layouts directory
        if (this.boundProject) {
          const layoutsPath = path.join(this.boundProject.designPath, 'layouts');
          if (!fs.existsSync(layoutsPath)) {
            fs.mkdirSync(layoutsPath, { recursive: true });
          }

          const names = this.getComponentNames(layout.name);
          const layoutFile = path.join(layoutsPath, `${names.fileName}.json`);

          fs.writeFileSync(layoutFile, JSON.stringify({
            layout,
            screenshot,
            metadata,
            extractedAt: new Date().toISOString()
          }, null, 2));

          console.log(`[PluginBridge] Layout saved: ${layoutFile}`);
        }

        res.json({
          success: true,
          layout: layout.name,
          timestamp: new Date().toISOString()
        });
      } catch (error) {
        console.error('[PluginBridge] Layout extraction error:', error);
        res.status(500).json({ error: error.message });
      }
    });

    // Plugin registration
    this.app.post('/api/register', (req, res) => {
      const { pluginId, version, capabilities } = req.body;
      const sessionId = this.generateSessionToken();

      this.connectedPlugins.set(pluginId, {
        sessionId,
        version,
        capabilities,
        connectedAt: new Date(),
        lastActivity: new Date()
      });

      // Read project config to get user's autoSync preference
      const projectConfig = this.readProjectConfig();
      const figmaConfig = projectConfig?.figma || {};

      res.json({
        sessionId,
        endpoints: this.getEndpoints(),
        wsUrl: `ws://localhost:${this.wsPort}`,
        config: {
          autoSync: figmaConfig.autoSync === true,  // Explicit boolean, defaults to false if not set
          syncInterval: figmaConfig.syncInterval || 300000,
          framework: projectConfig?.project?.framework || 'react',
          typescript: projectConfig?.project?.typescript || false,
          outputPath: projectConfig?.project?.outputPath || 'src/design-system'
        }
      });

      this.emit('plugin:connected', { pluginId, version, capabilities });
    });

    // Component search endpoint
    this.app.get('/api/components/search', async (req, res) => {
      try {
        const { query, limit = 10 } = req.query;

        // Use MCP Pinecone integration for component search
        const results = await this.searchComponents(query, limit);

        res.json({
          results,
          total: results.length,
          query
        });
      } catch (error) {
        res.status(500).json({ error: error.message });
      }
    });

    // Project binding endpoint
    this.app.post('/api/bind', async (req, res) => {
      try {
        const { path: projectPath } = req.body;

        if (!projectPath) {
          return res.status(400).json({ error: 'Project path is required' });
        }

        // Validate path exists
        if (!fs.existsSync(projectPath)) {
          return res.status(400).json({
            error: 'Path does not exist',
            path: projectPath
          });
        }

        // Check/create .design folder
        const designPath = path.join(projectPath, '.design');
        if (!fs.existsSync(designPath)) {
          fs.mkdirSync(designPath, { recursive: true });
        }

        // Create tokens folder
        const tokensPath = path.join(designPath, 'tokens');
        if (!fs.existsSync(tokensPath)) {
          fs.mkdirSync(tokensPath, { recursive: true });
        }

        // Store binding
        this.boundProject = {
          path: projectPath,
          designPath,
          tokensPath,
          boundAt: new Date().toISOString()
        };

        // Detect framework (basic detection)
        let framework = 'unknown';
        if (fs.existsSync(path.join(projectPath, 'package.json'))) {
          try {
            const pkg = JSON.parse(fs.readFileSync(path.join(projectPath, 'package.json'), 'utf8'));
            if (pkg.dependencies?.react || pkg.devDependencies?.react) framework = 'react';
            else if (pkg.dependencies?.vue || pkg.devDependencies?.vue) framework = 'vue';
            else if (pkg.dependencies?.svelte || pkg.devDependencies?.svelte) framework = 'svelte';
            else if (pkg.dependencies?.['@angular/core']) framework = 'angular';
          } catch (e) {}
        }

        res.json({
          success: true,
          project: {
            path: projectPath,
            designPath,
            framework,
            boundAt: this.boundProject.boundAt
          }
        });

        this.emit('project:bound', this.boundProject);

      } catch (error) {
        console.error('Bind error:', error);
        res.status(500).json({ error: error.message });
      }
    });

    // Get bound project
    this.app.get('/api/bind', (req, res) => {
      if (this.boundProject) {
        res.json({ bound: true, project: this.boundProject });
      } else {
        res.json({ bound: false });
      }
    });

    // Unbind project (DELETE /api/bind)
    this.app.delete('/api/bind', (req, res) => {
      if (this.boundProject) {
        const oldProject = this.boundProject;
        this.boundProject = null;
        res.json({ success: true, unbound: oldProject.path });
      } else {
        res.json({ success: true, message: 'No project was bound' });
      }
    });

    // Conflict resolution endpoint (POST /api/conflicts/resolve)
    this.app.post('/api/conflicts/resolve', async (req, res) => {
      try {
        const { resolutions } = req.body;

        if (!resolutions || !Array.isArray(resolutions)) {
          return res.status(400).json({
            success: false,
            error: 'Invalid request: resolutions array required'
          });
        }

        console.log(`[PluginBridge] Conflict resolution request: ${resolutions.length} conflict(s)`);

        // Log each resolution
        resolutions.forEach((resolution, idx) => {
          console.log(`  [${idx + 1}] Conflict ${resolution.conflictId}: ${resolution.resolution}`);
        });

        // Emit event for conflict resolution
        this.emit('conflicts:resolved', {
          resolutions,
          count: resolutions.length,
          timestamp: Date.now()
        });

        res.json({
          success: true,
          message: 'Conflicts resolved successfully',
          resolved: resolutions.length,
          timestamp: Date.now()
        });
      } catch (error) {
        console.error('[PluginBridge] Conflict resolution error:', error);
        res.status(500).json({
          success: false,
          error: 'Conflict resolution failed',
          details: error.message
        });
      }
    });

    // Chat endpoint - triggers Claude Code CLI for design tasks
    this.app.post('/api/chat', async (req, res) => {
      try {
        const { prompt } = req.body;

        if (!prompt || typeof prompt !== 'string' || prompt.trim().length === 0) {
          return res.status(400).json({
            success: false,
            message: 'Prompt is required'
          });
        }

        // Check if already processing
        if (this.chatHandler && this.chatHandler.isActive()) {
          return res.status(409).json({
            success: false,
            message: 'Another task is currently in progress'
          });
        }

        // Initialize chat handler if needed
        if (!this.chatHandler) {
          this.initializeChatHandler();
        }

        // Process the prompt
        const result = await this.chatHandler.processPrompt(prompt.trim());

        res.json(result);

      } catch (error) {
        console.error('Chat processing error:', error);
        res.status(500).json({
          success: false,
          message: error.message || 'Chat processing failed'
        });
      }
    });

    // Chat status endpoint
    this.app.get('/api/chat/status', (req, res) => {
      if (this.chatHandler) {
        res.json(this.chatHandler.getStatus());
      } else {
        res.json({
          isProcessing: false,
          hasActiveProcess: false,
          initialized: false
        });
      }
    });

    // Cancel active chat
    this.app.post('/api/chat/cancel', (req, res) => {
      if (this.chatHandler && this.chatHandler.isActive()) {
        const cancelled = this.chatHandler.cancel();
        res.json({ success: cancelled, message: cancelled ? 'Task cancelled' : 'No active task to cancel' });
      } else {
        res.json({ success: false, message: 'No active task to cancel' });
      }
    });
  }

  setupWebSocket() {
    this.wsServer = new WebSocket.Server({
      port: this.wsPort,
      cors: {
        origin: '*'
      }
    });

    this.wsServer.on('connection', (ws, req) => {
      console.log('Plugin WebSocket connected');

      ws.on('message', async (message) => {
        try {
          const data = JSON.parse(message);
          await this.handleWebSocketMessage(ws, data);
        } catch (error) {
          ws.send(JSON.stringify({
            type: 'error',
            error: error.message
          }));
        }
      });

      ws.on('close', () => {
        console.log('Plugin WebSocket disconnected');
      });

      // Send welcome message
      ws.send(JSON.stringify({
        type: 'connected',
        sessionToken: this.sessionToken,
        serverTime: new Date().toISOString()
      }));
    });
  }

  /**
   * Broadcast a message to all connected WebSocket clients
   * @param {Object} message - Message to broadcast
   */
  broadcastToPlugins(message) {
    if (!this.wsServer) return;

    const payload = JSON.stringify(message);
    this.wsServer.clients.forEach((client) => {
      if (client.readyState === WebSocket.OPEN) {
        client.send(payload);
      }
    });
  }

  async handleWebSocketMessage(ws, data) {
    const { type, payload } = data;

    switch (type) {
      case 'ping':
        ws.send(JSON.stringify({ type: 'pong', timestamp: Date.now() }));
        break;

      case 'tokens:stream':
        // Handle streaming token updates
        await this.streamTokens(payload);
        ws.send(JSON.stringify({
          type: 'tokens:processed',
          count: payload.tokens?.length || 0
        }));
        break;

      case 'file:watch':
        // Start watching Figma file for changes
        this.watchFigmaFile(payload.fileKey, ws);
        break;

      case 'export:request':
        // Handle export requests
        const exportResult = await this.handleExportRequest(payload);
        ws.send(JSON.stringify({
          type: 'export:complete',
          result: exportResult
        }));
        break;

      default:
        ws.send(JSON.stringify({
          type: 'error',
          error: `Unknown message type: ${type}`
        }));
    }
  }

  async processTokens(tokens, metadata = {}) {
    let stored = false;
    let indexed = false;
    let registered = false;
    let registrationResults = null;

    // Try to save to bound project first (direct filesystem)
    if (this.boundProject && this.boundProject.tokensPath) {
      try {
        const fileName = (metadata && metadata.fileName) || (metadata && metadata.component) || 'tokens';
        const filePath = path.join(this.boundProject.tokensPath, `${fileName}.json`);

        // Ensure directory exists
        if (!fs.existsSync(this.boundProject.tokensPath)) {
          fs.mkdirSync(this.boundProject.tokensPath, { recursive: true });
        }

        // Write tokens to file
        fs.writeFileSync(filePath, JSON.stringify({ tokens, metadata, savedAt: new Date().toISOString() }, null, 2));
        console.log(`Tokens saved to: ${filePath}`);
        stored = true;

        // ============================================================
        // v2.0.0: Register tokens in unified registry
        // ============================================================
        registrationResults = await this.registerTokensInRegistry(tokens, metadata);
        registered = registrationResults && registrationResults.totalRegistered > 0;

        if (registered) {
          this.emit('tokens:registered', {
            count: registrationResults.totalRegistered,
            updated: registrationResults.totalUpdated,
            fileKey: metadata.fileKey
          });
        }
      } catch (error) {
        console.error('Direct file save failed:', error.message);
      }
    }

    // Try MCP Bridge as secondary option (for memory storage and indexing)
    try {
      const mcpBridge = require('./mcp-bridge-interface');

      // Store in memory
      await mcpBridge.callMCP('memory', 'store', {
        key: `tokens:${metadata.fileKey}`,
        value: { tokens, metadata, timestamp: Date.now() }
      });

      // Index for search if Pinecone is available
      try {
        const tokenArray = Array.isArray(tokens) ? tokens : Object.entries(tokens).map(([k, v]) => ({ name: k, ...v }));
        await mcpBridge.callMCP('pinecone', 'index', {
          namespace: 'design-tokens',
          vectors: this.tokensToVectors(tokenArray)
        });
        indexed = true;
      } catch (error) {
        console.warn('Pinecone indexing failed:', error.message);
      }
    } catch (error) {
      console.log('MCP Bridge not initialized, using fallback');
    }

    return {
      processed: typeof tokens === 'object' && tokens ? Object.keys(tokens).length : 0,
      stored,
      indexed,
      registered,
      registrationResults
    };
  }

  /**
   * Register tokens in the unified registry
   * @param {Object} tokens - Token data (can be categorized or flat)
   * @param {Object} metadata - Extraction metadata
   * @returns {Promise<Object>} Registration results
   */
  async registerTokensInRegistry(tokens, metadata = {}) {
    if (!this.boundProject || !this.boundProject.path) {
      console.log('[PluginBridge] No bound project, skipping token registration');
      return null;
    }

    const registrar = getAutoRegistrar(this.boundProject.path);
    if (!registrar) {
      console.log('[PluginBridge] AutoRegistrar not available, skipping token registration');
      return null;
    }

    const source = {
      type: 'figma-plugin',
      fileKey: metadata.fileKey || null
    };

    const results = {
      totalRegistered: 0,
      totalUpdated: 0,
      totalFailed: 0,
      byCategory: {}
    };

    try {
      // Handle categorized tokens (colors, typography, spacing, effects)
      const categories = ['colors', 'typography', 'spacing', 'effects', 'shadows', 'radii', 'gradients'];

      for (const category of categories) {
        if (tokens[category] && (Array.isArray(tokens[category]) ? tokens[category].length > 0 : Object.keys(tokens[category]).length > 0)) {
          const tokenArray = Array.isArray(tokens[category])
            ? tokens[category]
            : Object.entries(tokens[category]).map(([name, value]) => ({
                name,
                value: typeof value === 'object' ? value : { value }
              }));

          const categoryResult = await registrar.registerTokenBatch(tokenArray, category, source);
          results.byCategory[category] = categoryResult;
          results.totalRegistered += categoryResult.registered || 0;
          results.totalUpdated += categoryResult.updated || 0;
          results.totalFailed += categoryResult.failed || 0;
        }
      }

      // Handle flat token structure (legacy format)
      if (results.totalRegistered === 0 && results.totalUpdated === 0) {
        const tokenArray = Array.isArray(tokens)
          ? tokens
          : Object.entries(tokens).map(([name, value]) => ({
              name,
              value: typeof value === 'object' ? value : { value }
            }));

        if (tokenArray.length > 0) {
          const flatResult = await registrar.registerTokenBatch(tokenArray, 'mixed', source);
          results.byCategory.mixed = flatResult;
          results.totalRegistered += flatResult.registered || 0;
          results.totalUpdated += flatResult.updated || 0;
          results.totalFailed += flatResult.failed || 0;
        }
      }

      console.log(`[PluginBridge] Tokens registered: ${results.totalRegistered} new, ${results.totalUpdated} updated`);

    } catch (error) {
      console.warn(`[PluginBridge] Token registration failed: ${error.message}`);
      results.error = error.message;
    }

    return results;
  }

  /**
   * Update registry sync metadata for all components from Figma source
   * Increments syncCount, updates lastFigmaSync, and syncs source.extractedAt from raw JSON
   * This enables auto-detection of design changes for cascade sync
   */
  async updateRegistrySyncMetadata(syncTimestamp) {
    if (!this.boundProject) {
      console.log('[PluginBridge] No bound project, skipping registry sync metadata update');
      return;
    }

    const registryPath = path.join(this.boundProject.path, '.design', 'componentRegistry.json');
    const componentsPath = path.join(this.boundProject.path, '.design', 'components');

    if (!fs.existsSync(registryPath)) {
      console.log('[PluginBridge] No registry found, skipping sync metadata update');
      return;
    }

    try {
      const registry = JSON.parse(fs.readFileSync(registryPath, 'utf-8'));
      let updatedCount = 0;
      let extractedAtUpdated = 0;

      // Update syncMetadata for all figma-plugin sourced components
      for (const componentId of Object.keys(registry.components || {})) {
        const component = registry.components[componentId];

        // Only update components from figma-plugin source
        if (component.source?.type === 'figma-plugin') {
          component.syncMetadata = component.syncMetadata || {};
          component.syncMetadata.lastFigmaSync = syncTimestamp;
          component.syncMetadata.syncCount = (component.syncMetadata.syncCount || 0) + 1;
          component.metadata = component.metadata || {};
          component.metadata.updatedAt = syncTimestamp;
          updatedCount++;

          // CASCADE SYNC: Update source.extractedAt from raw JSON file
          // This enables auto-detection of design changes
          const rawDataPath = component.source?.rawDataPath || component.paths?.rawSource;
          if (rawDataPath) {
            const fullRawPath = path.join(this.boundProject.path, rawDataPath);
            if (fs.existsSync(fullRawPath)) {
              try {
                const rawData = JSON.parse(fs.readFileSync(fullRawPath, 'utf-8'));
                const rawExtractedAt = rawData.source?.extractedAt;
                if (rawExtractedAt && rawExtractedAt !== component.source.extractedAt) {
                  component.source.extractedAt = rawExtractedAt;
                  extractedAtUpdated++;
                  console.log(`[PluginBridge] Updated extractedAt for ${componentId}: ${rawExtractedAt}`);
                }
              } catch (parseError) {
                // Ignore parse errors for individual raw files
              }
            }
          }
        }
      }

      // Update registry lastUpdated
      registry.lastUpdated = syncTimestamp;
      if (registry.metadata) {
        registry.metadata.lastUpdated = syncTimestamp;
      }

      // Write back to file
      fs.writeFileSync(registryPath, JSON.stringify(registry, null, 2));
      console.log(`[PluginBridge] Updated sync metadata for ${updatedCount} components (${extractedAtUpdated} with new extractedAt)`);
    } catch (error) {
      console.error('[PluginBridge] Error updating registry sync metadata:', error.message);
    }
  }

  async processComponents(components, metadata) {
    if (!this.boundProject) {
      console.warn('No bound project for component processing');
      return;
    }

    const componentsPath = path.join(this.boundProject.designPath, 'components');
    if (!fs.existsSync(componentsPath)) {
      fs.mkdirSync(componentsPath, { recursive: true });
    }

    const results = [];

    for (const component of components) {
      try {
        // Use centralized naming utility for consistent casing
        const names = this.getComponentNames(component.name);

        // Save component JSON only - TSX/stories are generated during transform step
        const jsonPath = path.join(componentsPath, `${names.fileName}.json`);
        fs.writeFileSync(jsonPath, JSON.stringify(component, null, 2));
        console.log(`Component extracted: ${jsonPath}`);

        // Phase 2: Auto-register component in registry (Two-State Architecture)
        let registrationResult = null;
        if (this.shouldAutoRegister()) {
          try {
            const registrar = this.getAutoRegistrar();
            if (registrar) {
              // Convert relative path for storage
              const relativePath = path.relative(this.boundProject.path, jsonPath);

              registrationResult = await registrar.registerComponent(
                {
                  name: component.name,
                  type: component.type || 'COMPONENT',
                  category: component.category,
                  variants: component.variants || [],
                  tokenDependencies: component.tokenDependencies || {},
                  interactiveStates: component.interactiveStates || {},
                  figmaId: component.id || component.figmaId,
                  figmaUrl: component.figmaUrl
                },
                {
                  type: 'figma-plugin',
                  projectPath: this.boundProject.path,
                  fileKey: metadata?.fileKey || null,
                  nodeId: component.id || component.figmaId || null,
                  figmaModifiedAt: component.lastModified || metadata?.lastModified || null,
                  rawDataPath: relativePath
                }
              );

              console.log(`[PluginBridge] Registered: ${registrationResult.id} (${registrationResult.isNew ? 'new' : 'updated'})`);
            }
          } catch (regError) {
            // Don't fail the whole import, just log registration error
            console.error(`[PluginBridge] Registration failed for ${component.name}:`, regError.message);
          }
        }

        // Emit extraction event (not generation - that happens during transform)
        this.emit('component:extracted', {
          fileName: names.fileName,
          componentName: names.componentName,
          jsonPath,
          registryId: registrationResult?.id || null
        });

        results.push({
          name: component.name,
          fileName: names.fileName,
          jsonPath,
          registryId: registrationResult?.id || null
        });

      } catch (error) {
        console.error(`Error processing component ${component.name}:`, error.message);
        results.push({
          name: component.name,
          error: error.message
        });
      }
    }

    return results;
  }

  generateReactComponent(component, names = null) {
    // Use passed names or derive from component.name using utility
    const { componentName: name } = names || this.getComponentNames(component.name);

    const variants = component.variants || [];
    const variantProps = component.variantGroupProperties || {};
    const propNames = Object.keys(variantProps);

    // Check if this component has variants
    if (variants.length > 0 && propNames.length > 0) {
      // Extract variant names for the type union
      const variantValues = variantProps[propNames[0]]?.values || [];
      const variantType = variantValues.map(v => `'${v}'`).join(' | ') || "'default'";

      // Build variant styles object from Figma data
      const variantStylesEntries = variants.map(variant => {
        const variantName = variant.variantProperties?.[propNames[0]] || 'default';
        let bgColor = '#000000';
        let textColor = 'white';

        // Extract background from variant fills
        if (variant.fills?.[0]?.color) {
          const c = variant.fills[0].color;
          bgColor = `rgb(${Math.round(c.r * 255)}, ${Math.round(c.g * 255)}, ${Math.round(c.b * 255)})`;
        }

        // Extract text color from children
        if (variant.children?.[0]?.fills?.[0]?.color) {
          const tc = variant.children[0].fills[0].color;
          textColor = `rgb(${Math.round(tc.r * 255)}, ${Math.round(tc.g * 255)}, ${Math.round(tc.b * 255)})`;
        }

        return `    ${variantName}: {\n      backgroundColor: '${bgColor}',\n      color: '${textColor}',\n    }`;
      }).join(',\n');

      // Get common styles from first variant
      const cornerRadius = variants[0]?.cornerRadius || 8;
      const fontSize = variants[0]?.children?.[0]?.fontSize || 16;

      return `import React from 'react';

interface ${name}Props {
  children?: React.ReactNode;
  className?: string;
  variant?: ${variantType};
}

/**
 * ${name} Component
 * Auto-generated from Figma design
 * Generated at: ${new Date().toISOString()}
 */
export const ${name}: React.FC<${name}Props> = ({
  children,
  className,
  variant = '${variantValues[0] || 'default'}'
}) => {
  const variantStyles: Record<string, React.CSSProperties> = {
${variantStylesEntries}
  };

  return (
    <button
      className={className}
      style={{
        ...variantStyles[variant],
        padding: '16px 40px',
        borderRadius: ${cornerRadius},
        border: 'none',
        fontSize: ${fontSize},
        fontWeight: 500,
        cursor: 'pointer',
      }}
    >
      {children || 'Button'}
    </button>
  );
};

export default ${name};
`;
    }

    // Fallback for non-variant components
    const styles = component.styles || {};
    return `import React from 'react';

interface ${name}Props {
  children?: React.ReactNode;
  className?: string;
}

/**
 * ${name} Component
 * Auto-generated from Figma design
 * Generated at: ${new Date().toISOString()}
 */
export const ${name}: React.FC<${name}Props> = ({ children, className }) => {
  return (
    <div
      className={className}
      style={{
        ${styles.backgroundColor ? `backgroundColor: '${styles.backgroundColor}',` : ''}
        ${styles.color ? `color: '${styles.color}',` : ''}
        ${styles.borderRadius ? `borderRadius: ${styles.borderRadius},` : ''}
        ${styles.padding ? `padding: ${styles.padding},` : ''}
      }}
    >
      {children || '${name}'}
    </div>
  );
};

export default ${name};
`;
  }

  generateStorybookStory(component, names = null) {
    // Use passed names or derive from component.name using utility
    const resolvedNames = names || this.getComponentNames(component.name);
    const { fileName, componentName: name } = resolvedNames;

    const variants = component.variants || [];
    const variantProps = component.variantGroupProperties || {};
    const propNames = Object.keys(variantProps);

    // Check if component has variants
    if (variants.length > 0 && propNames.length > 0) {
      const variantValues = variantProps[propNames[0]]?.values || [];

      // Generate variant stories with proper variant prop
      const variantStories = variants.map(variant => {
        const variantName = variant.variantProperties?.[propNames[0]] || 'default';
        const storyName = variantName.charAt(0).toUpperCase() + variantName.slice(1);

        return `
export const ${storyName}: Story = {
  args: {
    children: '${storyName} Button',
    variant: '${variantName}',
  },
};`;
      }).join('\n');

      return `import type { Meta, StoryObj } from '@storybook/react';
import { ${name} } from './${fileName}';

/**
 * ${name} Component Stories
 * Auto-generated from Figma design
 * Generated at: ${new Date().toISOString()}
 */
const meta: Meta<typeof ${name}> = {
  title: 'Components/${name}',
  component: ${name},
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
  argTypes: {
    children: { control: 'text' },
    className: { control: 'text' },
    variant: {
      control: 'select',
      options: [${variantValues.map(v => `'${v}'`).join(', ')}],
    },
  },
};

export default meta;
type Story = StoryObj<typeof meta>;
${variantStories}
`;
    }

    // Fallback for non-variant components
    return `import type { Meta, StoryObj } from '@storybook/react';
import { ${name} } from './${fileName}';

/**
 * ${name} Component Stories
 * Auto-generated from Figma design
 * Generated at: ${new Date().toISOString()}
 */
const meta: Meta<typeof ${name}> = {
  title: 'Components/${name}',
  component: ${name},
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
  argTypes: {
    children: { control: 'text' },
    className: { control: 'text' },
  },
};

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    children: '${name}',
    className: '',
  },
};
`;
  }

  async searchComponents(query, limit) {
    const mcpBridge = require('./mcp-bridge-interface');

    try {
      const results = await mcpBridge.callMCP('pinecone', 'search', {
        namespace: 'design-components',
        query,
        topK: limit
      });

      return results.matches || [];
    } catch (error) {
      console.warn('Component search failed:', error.message);
      return [];
    }
  }

  async streamTokens(payload) {
    // Handle real-time token streaming
    const { tokens, incremental, fileKey } = payload;

    if (incremental) {
      // Merge with existing tokens
      const existing = await this.getExistingTokens(fileKey);
      const merged = this.mergeTokens(existing, tokens);
      await this.processTokens(merged, { fileKey, incremental: true });
    } else {
      await this.processTokens(tokens, { fileKey });
    }

    this.emit('tokens:updated', { fileKey, tokens, incremental });
  }

  watchFigmaFile(fileKey, ws) {
    // Set up file watching (would integrate with Figma webhooks in production)
    console.log(`Watching Figma file: ${fileKey}`);

    // Simulate file change detection
    const checkInterval = setInterval(async () => {
      try {
        // In real implementation, this would check Figma API for changes
        const hasChanges = await this.checkForChanges(fileKey);

        if (hasChanges) {
          ws.send(JSON.stringify({
            type: 'file:changed',
            fileKey,
            timestamp: new Date().toISOString()
          }));
        }
      } catch (error) {
        console.error('File watch error:', error);
      }
    }, 30000); // Check every 30 seconds

    // Store interval for cleanup
    if (!this.fileWatchers) this.fileWatchers = new Map();
    this.fileWatchers.set(fileKey, checkInterval);
  }

  tokensToVectors(tokens) {
    // Convert design tokens to vectors for search indexing
    return tokens.map(token => ({
      id: token.id || crypto.randomUUID(),
      values: this.tokenToVector(token),
      metadata: {
        type: token.type,
        name: token.name,
        description: token.description
      }
    }));
  }

  tokenToVector(token) {
    // Simple vectorization (would use proper embedding in production)
    const features = [];

    // Basic feature extraction
    if (token.type === 'color') {
      features.push(...this.colorToFeatures(token));
    } else if (token.type === 'typography') {
      features.push(...this.typographyToFeatures(token));
    }

    // Pad or truncate to consistent length
    while (features.length < 128) features.push(0);
    return features.slice(0, 128);
  }

  colorToFeatures(token) {
    const { rgb } = token;
    return [
      rgb.r / 255,
      rgb.g / 255,
      rgb.b / 255,
      rgb.a || 1
    ];
  }

  typographyToFeatures(token) {
    const { value } = token;
    return [
      value.fontSize?.px || 16,
      value.fontWeight || 400,
      value.lineHeight?.unitless || 1.4
    ];
  }

  generateSessionToken() {
    return crypto.randomBytes(32).toString('hex');
  }

  validateSession(sessionId) {
    // In development/testing mode, allow all tokens
    if (process.env.NODE_ENV !== 'production') {
      return true;
    }
    // In development mode, allow tokens when a project is bound
    if (this.boundProject) {
      return true;
    }
    return Array.from(this.connectedPlugins.values())
      .some(plugin => plugin.sessionId === sessionId);
  }

  getEndpoints() {
    return {
      tokens: `http://localhost:${this.port}/api/tokens`,
      status: `http://localhost:${this.port}/api/sync/status`,
      search: `http://localhost:${this.port}/api/components/search`,
      health: `http://localhost:${this.port}/health`
    };
  }

  async start() {
    return new Promise((resolve, reject) => {
      this.server = this.app.listen(this.port, (err) => {
        if (err) {
          reject(err);
          return;
        }

        console.log(`Plugin Bridge running on port ${this.port}`);
        console.log(`WebSocket server running on port ${this.wsPort}`);

        this.emit('started');
        resolve();
      });
    });
  }

  async stop() {
    if (this.server) {
      this.server.close();
    }
    if (this.wsServer) {
      this.wsServer.close();
    }

    // Clean up file watchers
    if (this.fileWatchers) {
      this.fileWatchers.forEach(interval => clearInterval(interval));
      this.fileWatchers.clear();
    }

    this.emit('stopped');
  }

  // Helper methods
  async getExistingTokens(fileKey) {
    // Implementation would fetch from MCP memory
    return [];
  }

  mergeTokens(existing, updates) {
    // Implementation would intelligently merge token sets
    return [...existing, ...updates];
  }

  async checkForChanges(fileKey) {
    // Implementation would check Figma API for file modifications
    return false;
  }

  getPendingChanges() {
    // Implementation would return pending changes count
    return 0;
  }

  getCLIVersion() {
    // Implementation would return actual CLI version
    return '1.0.0';
  }

  async handleExportRequest(payload) {
    // Implementation would handle various export formats
    return { success: true, format: payload.format };
  }

  // ==========================================
  // Sprint 5.2: Config Reader Methods
  // ==========================================

  /**
   * Read project configuration from .design/config.json
   * @param {string} projectRoot - Root directory of the project
   * @returns {Object|null} Configuration object or null if not found
   */
  readProjectConfig(projectRoot = process.cwd()) {
    const configPath = path.join(projectRoot, '.design', 'config.json');

    try {
      if (!fs.existsSync(configPath)) {
        return null;
      }

      const configContent = fs.readFileSync(configPath, 'utf8');
      const config = JSON.parse(configContent);

      // Validate and provide defaults
      return {
        framework: config.framework || 'react',
        autoTransformOnSync: config.autoTransformOnSync ?? false,
        outputDir: config.outputDir || 'src/components',
        features: config.features || {},
        generatorOptions: config.generatorOptions || {},
        ...config
      };
    } catch (error) {
      console.error('Error reading config:', error.message);
      return null;
    }
  }

  /**
   * Check if auto-transform is enabled
   * @param {string} projectRoot - Project root directory
   * @returns {boolean}
   */
  isAutoTransformEnabled(projectRoot = process.cwd()) {
    const config = this.readProjectConfig(projectRoot);
    return config?.autoTransformOnSync === true;
  }

  /**
   * Get target framework from config
   * @param {string} projectRoot - Project root directory
   * @returns {string}
   */
  getTargetFramework(projectRoot = process.cwd()) {
    const config = this.readProjectConfig(projectRoot);
    return config?.framework || 'react';
  }

  // ==========================================
  // Sprint 5.3: Generator Initialization
  // ==========================================

  /**
   * Initialize generators lazily
   * @returns {Object} Generator instance
   */
  initializeGenerators() {
    if (!this.generator) {
      // Lazy load to avoid circular dependencies
      if (!MultiFrameworkGenerator) {
        MultiFrameworkGenerator = require('./multi-framework-generator');
        const registryModule = require('./optimizer-registry');
        getOptimizerRegistry = registryModule.getOptimizerRegistry;
      }

      // Initialize generator with registry
      const registry = getOptimizerRegistry();
      this.generator = new MultiFrameworkGenerator({
        optimizerRegistry: registry
      });

      console.log('✓ Generator initialized for auto-transform');
    }

    return this.generator;
  }

  /**
   * Get optimizer registry
   * @returns {OptimizerRegistry}
   */
  getRegistry() {
    if (!getOptimizerRegistry) {
      const registryModule = require('./optimizer-registry');
      getOptimizerRegistry = registryModule.getOptimizerRegistry;
    }
    return getOptimizerRegistry();
  }

  // ==========================================
  // Sprint 5.4: Auto-Transform Trigger
  // ==========================================

  /**
   * Convert tokens to design component format for generator
   * @param {Array} tokens - Array of design tokens
   * @returns {Array} Array of design components
   */
  tokensToDesignComponents(tokens) {
    if (!Array.isArray(tokens)) {
      return [];
    }

    // Filter and transform component-type tokens
    return tokens
      .filter(token => token.type === 'component' || token.type === 'COMPONENT')
      .map(token => ({
        id: token.id || `component_${Date.now()}`,
        name: token.name || 'Component',
        type: 'component',
        props: token.props || token.properties || {},
        state: token.state || {},
        variants: token.variants || [],
        styles: token.styles || token.css || {},
        children: token.children || []
      }));
  }

  /**
   * Automatically transform tokens to code if enabled
   * @param {Object} data - Token data from sync
   * @param {string} projectRoot - Project root directory
   * @returns {Object|null} Transform result or null if disabled
   */
  async autoTransformIfEnabled(data, projectRoot = process.cwd()) {
    // Check if auto-transform is enabled
    const config = this.readProjectConfig(projectRoot);

    if (!config?.autoTransformOnSync) {
      return null;
    }

    const framework = config.framework || 'react';
    const tokens = data.tokens || [];

    // Convert tokens to design components
    const designComponents = this.tokensToDesignComponents(tokens);

    if (designComponents.length === 0) {
      console.log('No component tokens found for auto-transform');
      return { components: [], skipped: true };
    }

    console.log(`Auto-transform enabled. Generating ${framework} components for ${designComponents.length} component(s)...`);

    try {
      // Emit start event
      this.emit('transform:started', {
        framework,
        tokenCount: tokens.length,
        componentCount: designComponents.length,
        timestamp: Date.now()
      });

      // Initialize generator
      const generator = this.initializeGenerators();
      const generatedComponents = [];

      // Generate code for each design component
      for (const designComponent of designComponents) {
        try {
          const result = await generator.generateForFramework(
            designComponent,
            framework,
            {
              outputDir: config.outputDir || 'src/components',
              ...config.generatorOptions
            }
          );

          generatedComponents.push({
            name: designComponent.name,
            framework,
            result
          });
        } catch (componentError) {
          console.warn(`Warning: Failed to generate ${designComponent.name}:`, componentError.message);
          generatedComponents.push({
            name: designComponent.name,
            framework,
            error: componentError.message
          });
        }
      }

      const result = {
        components: generatedComponents,
        framework,
        outputDir: config.outputDir || 'src/components',
        successful: generatedComponents.filter(c => !c.error).length,
        failed: generatedComponents.filter(c => c.error).length
      };

      // Emit completion event
      this.emit('transform:completed', {
        framework,
        componentsGenerated: result.successful,
        componentsFailed: result.failed,
        outputDir: result.outputDir,
        timestamp: Date.now()
      });

      console.log(`✓ Auto-transform complete: ${result.successful}/${designComponents.length} components generated`);

      return result;

    } catch (error) {
      // Emit failure event
      this.emit('transform:failed', {
        framework,
        error: error.message,
        timestamp: Date.now()
      });

      console.error('Auto-transform failed:', error.message);
      throw error;
    }
  }
}

module.exports = PluginBridge;