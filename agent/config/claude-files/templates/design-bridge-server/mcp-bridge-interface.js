/**
 * MCP Bridge Interface
 * Integration layer between Design Bridge and MCP servers
 */

const { EventEmitter } = require('events');
const path = require('path');

class MCPBridgeInterface extends EventEmitter {
  constructor(mcpManager) {
    super();
    this.mcpManager = mcpManager;
    this.integrationPoints = this.defineIntegrationPoints();
  }

  /**
   * Define all MCP server integration touchpoints
   */
  defineIntegrationPoints() {
    return {
      // Memory Server - Store design tokens and state
      memory: {
        server: 'memory',
        operations: [
          'storeTokens',
          'retrieveTokens',
          'storeComponentRegistry',
          'trackChanges',
          'maintainHistory'
        ],
        dataFlow: 'bidirectional',
        persistence: true,
        usage: {
          storeTokens: async (tokens) => {
            return await this.callMCP('memory', 'store', {
              key: 'design-tokens',
              value: tokens,
              timestamp: Date.now()
            });
          },
          retrieveTokens: async () => {
            return await this.callMCP('memory', 'retrieve', {
              key: 'design-tokens'
            });
          },
          storeComponentRegistry: async (components) => {
            return await this.callMCP('memory', 'store', {
              key: 'component-registry',
              value: components
            });
          },
          trackChanges: async (changes) => {
            return await this.callMCP('memory', 'append', {
              key: 'design-changes',
              value: changes
            });
          }
        }
      },

      // Filesystem Server - Save extracted data
      filesystem: {
        server: 'filesystem',
        operations: [
          'saveTokenFile',
          'saveComponentFile',
          'saveCatalog',
          'readConfiguration',
          'watchChanges'
        ],
        dataFlow: 'bidirectional',
        persistence: true,
        usage: {
          saveTokenFile: async (tokens) => {
            const tokenPath = '.design/tokens/tokens.json';
            return await this.callMCP('filesystem', 'write', {
              path: tokenPath,
              content: JSON.stringify(tokens, null, 2)
            });
          },
          readConfiguration: async () => {
            const configPath = '.design/config.json';
            return await this.callMCP('filesystem', 'read', {
              path: configPath
            });
          },
          watchChanges: async (directory) => {
            return await this.callMCP('filesystem', 'watch', {
              path: directory,
              events: ['change', 'add', 'unlink']
            });
          }
        }
      },

      // Sequential Thinking - Analyze design changes
      sequentialThinking: {
        server: 'sequential-thinking',
        operations: [
          'analyzeChangeImpact',
          'generateUpdateStrategy',
          'validateDesignConsistency',
          'suggestImprovements'
        ],
        dataFlow: 'unidirectional',
        persistence: false,
        usage: {
          analyzeChangeImpact: async (before, after) => {
            return await this.callMCP('sequential-thinking', 'analyze', {
              task: 'impact-analysis',
              before,
              after,
              context: 'design-system-change'
            });
          },
          generateUpdateStrategy: async (changes) => {
            return await this.callMCP('sequential-thinking', 'reason', {
              task: 'update-strategy',
              changes,
              constraints: ['safety', 'backward-compatibility']
            });
          }
        }
      },

      // GitHub - Automate version control
      github: {
        server: 'github',
        operations: [
          'createBranch',
          'commitChanges',
          'createPullRequest',
          'addReviewers',
          'mergeApprovedChanges'
        ],
        dataFlow: 'bidirectional',
        persistence: true,
        usage: {
          createBranch: async (branchName) => {
            return await this.callMCP('github', 'branch:create', {
              name: branchName,
              from: 'main'
            });
          },
          commitChanges: async (files, message) => {
            return await this.callMCP('github', 'commit', {
              files,
              message,
              branch: 'design-system-update'
            });
          },
          createPullRequest: async (title, description) => {
            return await this.callMCP('github', 'pr:create', {
              title,
              body: description,
              base: 'main',
              head: 'design-system-update'
            });
          }
        }
      },

      // Figma MCP - Enhanced Figma operations
      figma: {
        server: 'figma',
        operations: [
          'extractAdvancedData',
          'monitorFileChanges',
          'exportAssets',
          'syncLibraries'
        ],
        dataFlow: 'unidirectional',
        persistence: false,
        usage: {
          extractAdvancedData: async (fileKey) => {
            return await this.callMCP('figma', 'extract:advanced', {
              fileKey,
              includePrivate: true,
              depth: 'full'
            });
          },
          monitorFileChanges: async (fileKey) => {
            return await this.callMCP('figma', 'monitor', {
              fileKey,
              interval: 30000
            });
          }
        }
      },

      // Context7 - Documentation search
      context7: {
        server: 'context7',
        operations: [
          'searchDocumentation',
          'findSimilarPatterns',
          'suggestImplementations'
        ],
        dataFlow: 'unidirectional',
        persistence: false,
        usage: {
          searchDocumentation: async (query) => {
            return await this.callMCP('context7', 'search', {
              query,
              context: 'design-systems'
            });
          },
          findSimilarPatterns: async (component) => {
            return await this.callMCP('context7', 'similar', {
              component,
              limit: 5
            });
          }
        }
      },

      // Pinecone - Vector search for components
      pinecone: {
        server: 'pinecone',
        operations: [
          'indexComponents',
          'searchComponents',
          'findSimilarDesigns',
          'clusterPatterns'
        ],
        dataFlow: 'bidirectional',
        persistence: true,
        usage: {
          indexComponents: async (components) => {
            return await this.callMCP('pinecone', 'index', {
              namespace: 'design-components',
              vectors: components
            });
          },
          searchComponents: async (query) => {
            return await this.callMCP('pinecone', 'search', {
              namespace: 'design-components',
              query,
              topK: 10
            });
          }
        }
      },

      // Talk-to-Figma - Real-time Figma plugin communication
      talkToFigma: {
        server: 'talk-to-figma',
        operations: [
          // Document operations
          'getDocument',
          'getDocumentInfo',
          'getSelection',
          'getNodeById',
          'getNodesByType',
          'getNodes',
          'setSelection',
          'zoomToFit',
          'zoomToNode',
          'getCatalogMetadata',
          // Creation operations
          'createFrame',
          'createRectangle',
          'createEllipse',
          'createText',
          'createLine',
          'createPolygon',
          'createStar',
          'createVector',
          'createImage',
          'createGroup',
          'createComponentInstance',
          // Modification operations
          'setFillColor',
          'setStrokeColor',
          'setStrokeWeight',
          'setCornerRadius',
          'moveNode',
          'resizeNode',
          'deleteNode',
          'duplicateNode',
          'renameNode',
          // Text operations
          'setTextContent',
          'setFontFamily',
          'setFontSize',
          'setFontWeight',
          'setTextAlignment',
          'setTextColor',
          'setLineHeight',
          'setLetterSpacing',
          'getTextContent',
          'getTextStyles',
          'setMultipleTextContents',
          'scanTextNodes'
        ],
        dataFlow: 'bidirectional',
        persistence: false,
        usage: {
          getDocument: async () => {
            return await this.callMCP('talk-to-figma', 'get_document', {});
          },
          getSelection: async () => {
            return await this.callMCP('talk-to-figma', 'get_selection', {});
          },
          createFrame: async (name, x, y, width, height, parentId) => {
            return await this.callMCP('talk-to-figma', 'create_frame', {
              name, x, y, width, height, parentId
            });
          },
          createText: async (text, x, y, options = {}) => {
            return await this.callMCP('talk-to-figma', 'create_text', {
              text, x, y, ...options
            });
          },
          setFillColor: async (nodeId, color) => {
            return await this.callMCP('talk-to-figma', 'set_fill_color', {
              nodeId, ...color
            });
          },
          setTextContent: async (nodeId, text) => {
            return await this.callMCP('talk-to-figma', 'set_text_content', {
              nodeId, text
            });
          },
          getTextContent: async (nodeId) => {
            return await this.callMCP('talk-to-figma', 'get_text_content', {
              nodeId
            });
          },
          scanTextNodes: async (scope, options = {}) => {
            return await this.callMCP('talk-to-figma', 'scan_text_nodes', {
              scope, ...options
            });
          }
        }
      }
    };
  }

  /**
   * Communication Protocol with MCP servers
   */
  async callMCP(serverName, operation, params) {
    try {
      // Ensure server is running
      if (!this.mcpManager.isServerRunning(serverName)) {
        await this.mcpManager.startServer(serverName);
      }

      // Send message to MCP server
      const response = await this.mcpManager.sendMessage(serverName, {
        method: operation,
        params
      });

      this.emit('mcp:response', {
        server: serverName,
        operation,
        success: true
      });

      return response;
    } catch (error) {
      this.emit('mcp:error', {
        server: serverName,
        operation,
        error: error.message
      });
      throw error;
    }
  }

  /**
   * Data Flow Orchestration
   */
  async orchestrateDataFlow(flowType, data) {
    const flows = {
      // Token extraction flow
      tokenExtraction: async (tokens) => {
        // 1. Store in memory
        await this.integrationPoints.memory.usage.storeTokens(tokens);
        
        // 2. Save to filesystem
        await this.integrationPoints.filesystem.usage.saveTokenFile(tokens);
        
        // 3. Index for search
        if (this.mcpManager.isServerEnabled('pinecone')) {
          await this.integrationPoints.pinecone.usage.indexComponents(tokens);
        }
        
        return { stored: true, indexed: true };
      },

      // Change propagation flow
      changePropagation: async (changes) => {
        // 1. Analyze impact
        const impact = await this.integrationPoints.sequentialThinking
          .usage.analyzeChangeImpact(changes.before, changes.after);
        
        // 2. Track in memory
        await this.integrationPoints.memory.usage.trackChanges({
          ...changes,
          impact
        });
        
        // 3. Create git branch and commit
        if (impact.requiresUpdate) {
          await this.integrationPoints.github.usage.createBranch(
            `design-update-${Date.now()}`
          );
          await this.integrationPoints.github.usage.commitChanges(
            changes.files,
            `Design system update: ${changes.summary}`
          );
        }
        
        return { impact, propagated: impact.requiresUpdate };
      },

      // Documentation generation flow
      documentationGeneration: async (designData) => {
        // 1. Search for similar patterns
        const similar = await this.integrationPoints.context7
          .usage.findSimilarPatterns(designData);
        
        // 2. Generate catalog files
        const catalog = await this.generateCatalog(designData, similar);
        
        // 3. Save to filesystem
        await this.integrationPoints.filesystem.usage.saveCatalog(catalog);
        
        return { catalog, similar };
      }
    };

    if (flows[flowType]) {
      return await flows[flowType](data);
    }
    
    throw new Error(`Unknown flow type: ${flowType}`);
  }

  /**
   * Initialize all necessary MCP servers
   */
  async initialize() {
    const requiredServers = ['memory', 'filesystem', 'sequential-thinking'];
    const optionalServers = ['github', 'figma', 'context7', 'pinecone'];
    
    console.log('Initializing MCP Bridge...');
    
    // Start required servers
    for (const server of requiredServers) {
      if (!this.mcpManager.isServerRunning(server)) {
        console.log(`Starting required server: ${server}`);
        await this.mcpManager.startServer(server);
      }
    }
    
    // Check optional servers
    for (const server of optionalServers) {
      if (this.mcpManager.isServerEnabled(server)) {
        console.log(`Optional server available: ${server}`);
      }
    }
    
    this.emit('initialized');
    return true;
  }

  /**
   * Generate catalog helper
   */
  async generateCatalog(designData, similarPatterns) {
    // This will be implemented in catalog generator module
    return {
      tokens: designData.tokens,
      components: designData.components,
      patterns: similarPatterns,
      generated: new Date().toISOString()
    };
  }

  /**
   * Health check for all integrations
   */
  async healthCheck() {
    const health = {};
    
    for (const [name, integration] of Object.entries(this.integrationPoints)) {
      health[name] = {
        server: integration.server,
        available: this.mcpManager.isServerEnabled(integration.server),
        running: this.mcpManager.isServerRunning(integration.server)
      };
    }
    
    return health;
  }
}

// Create a singleton instance for easy use
let mcpBridgeInstance = null;

function createMCPBridge(mcpManager) {
  if (!mcpBridgeInstance) {
    mcpBridgeInstance = new MCPBridgeInterface(mcpManager);
  }
  return mcpBridgeInstance;
}

// TalkToFigma namespace for direct access to Figma-related operations
const talkToFigma = {
  server: 'talk-to-figma',
  operations: [
    'getDocument', 'getDocumentInfo', 'getSelection', 'getNodeById',
    'createFrame', 'createRectangle', 'createEllipse', 'createText',
    'setFillColor', 'setStrokeColor', 'setTextContent', 'scanTextNodes'
  ],
  // Direct command mapping for Talk-to-Figma MCP server
  commands: require('./mcp/config/config').COMMANDS,
  // Reference to the full MCP server module
  mcp: require('./mcp/server')
};

// Export both class and convenience function
module.exports = {
  MCPBridgeInterface,
  createMCPBridge,
  talkToFigma,
  TalkToFigma: talkToFigma, // Alias for consistency
  // Convenience method for simple calls without instantiation
  callMCP: async (serverName, operation, params) => {
    // Fallback implementation when no MCP manager is available
    try {
      if (!mcpBridgeInstance) {
        console.warn('MCP Bridge not initialized, using fallback');
        return { success: false, error: 'MCP not available' };
      }
      return await mcpBridgeInstance.callMCP(serverName, operation, params);
    } catch (error) {
      console.warn('MCP call failed:', error.message);
      return { success: false, error: error.message };
    }
  }
};