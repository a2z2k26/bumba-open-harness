/**
 * BUMBA Design Bridge Core
 * Central orchestrator for design-to-code transformation
 */

const { EventEmitter } = require('events');
const { logger } = require('../logging/bumba-logger');
const { WebSocketServer } = require('../websocket/websocket-server');
const dotenv = require('dotenv');
const path = require('path');
const fs = require('fs');

class DesignBridge extends EventEmitter {
  constructor(config = {}) {
    super();

    // Load project-specific .env file
    const projectEnvPath = path.join(process.cwd(), '.env');
    if (fs.existsSync(projectEnvPath)) {
      dotenv.config({ path: projectEnvPath });
    }

    // Config with .env overrides (env takes precedence)
    this.config = {
      ...config, // Base config first
      wsPort: process.env.DESIGN_BRIDGE_PORT || config.wsPort || 3004,
      autoConnect: process.env.DESIGN_BRIDGE_AUTO_CONNECT === 'false' ? false : config.autoConnect !== false,
      figmaToken: process.env.FIGMA_ACCESS_TOKEN || config.figmaToken,
      transformers: config.transformers || []
    };

    this.wsServer = null;
    this.activeConnections = new Map();
    this.designCache = new Map();
    this.transformers = new Map();

    // Register default transformers
    this.registerDefaultTransformers();
  }

  /**
   * Initialize the Design Bridge
   */
  async initialize() {
    try {
      // Start WebSocket server
      if (this.config.autoConnect) {
        this.wsServer = new WebSocketServer({ port: this.config.wsPort });
        await this.wsServer.start();

        // Setup WebSocket event handlers
        this.setupWebSocketHandlers();
      }

      logger.info('🌉 Design Bridge initialized');
      this.emit('initialized');

    } catch (error) {
      logger.error('Failed to initialize Design Bridge:', error);
      throw error;
    }
  }

  /**
   * Setup WebSocket event handlers
   */
  setupWebSocketHandlers() {
    this.wsServer.on('client:connected', ({ clientId, metadata }) => {
      this.activeConnections.set(clientId, {
        id: clientId,
        metadata,
        connectedAt: Date.now()
      });
      this.emit('designer:connected', { clientId });
    });

    this.wsServer.on('client:disconnected', ({ clientId }) => {
      this.activeConnections.delete(clientId);
      this.emit('designer:disconnected', { clientId });
    });

    this.wsServer.on('figma:design-update', ({ clientId, data }) => {
      this.handleDesignUpdate(clientId, data);
    });

    this.wsServer.on('figma:selection', ({ clientId, selection }) => {
      this.handleSelectionChange(clientId, selection);
    });

    this.wsServer.on('figma:export', ({ clientId, nodes }) => {
      this.handleExportRequest(clientId, nodes);
    });
  }

  /**
   * Handle design update from Figma
   */
  async handleDesignUpdate(clientId, data) {
    // Input validation
    if (!clientId) {
      logger.warn('handleDesignUpdate called with invalid clientId:', clientId);
      this.emit('design:error', {
        error: new Error('Invalid clientId provided'),
        clientId: null
      });
      return;
    }

    if (!data || typeof data !== 'object') {
      logger.warn('handleDesignUpdate called with invalid data:', { clientId, data });
      this.emit('design:error', {
        error: new Error('Invalid or missing design data'),
        clientId
      });
      return;
    }

    try {
      // Cache the design data
      this.designCache.set(data.id || 'latest', {
        data,
        timestamp: Date.now(),
        source: clientId
      });

      // Transform the design data
      const transformed = await this.transform(data);

      // Emit transformed result
      this.emit('design:transformed', {
        original: data,
        transformed,
        clientId
      });

      // Send result back to client
      if (this.wsServer) {
        this.wsServer.send(clientId, {
          type: 'transform:result',
          data: transformed
        });
      }

    } catch (error) {
      logger.error('Failed to handle design update:', error);
      this.emit('design:error', { error, clientId });
    }
  }

  /**
   * Handle selection change in Figma
   */
  handleSelectionChange(clientId, selection) {
    // Input validation
    if (!clientId) {
      logger.warn('handleSelectionChange called with invalid clientId:', clientId);
      return;
    }

    this.emit('selection:changed', {
      selection,
      clientId,
      timestamp: Date.now()
    });

    // Process selected nodes if any
    if (selection && selection.nodes && selection.nodes.length > 0) {
      this.processSelectedNodes(selection.nodes, clientId);
    }
  }

  /**
   * Handle export request from Figma
   */
  async handleExportRequest(clientId, nodes) {
    try {
      const results = [];

      for (const node of nodes) {
        const result = await this.exportNode(node);
        results.push(result);
      }

      // Send results back to client
      if (this.wsServer) {
        this.wsServer.send(clientId, {
          type: 'export:complete',
          results
        });
      }

      this.emit('export:complete', {
        nodes,
        results,
        clientId
      });

    } catch (error) {
      logger.error('Failed to handle export request:', error);
      this.emit('export:error', { error, clientId });
    }
  }

  /**
   * Transform design data through pipeline
   */
  async transform(data) {
    const results = {
      components: [],
      tokens: {},
      assets: [],
      styles: {},
      metadata: {}
    };

    // Run through transformation pipeline
    for (const [name, transformer] of this.transformers) {
      try {
        const transformed = await transformer(data, results);
        Object.assign(results, transformed);
      } catch (error) {
        logger.error(`Transformer ${name} failed:`, error);
      }
    }

    return results;
  }

  /**
   * Export a design node to code
   */
  async exportNode(node) {
    const result = {
      id: node.id,
      name: node.name,
      type: node.type,
      code: null,
      assets: [],
      error: null
    };

    try {
      // Determine export strategy based on node type
      switch (node.type) {
        case 'COMPONENT':
        case 'COMPONENT_SET':
          result.code = await this.exportComponent(node);
          break;

        case 'FRAME':
          result.code = await this.exportFrame(node);
          break;

        case 'TEXT':
          result.code = await this.exportText(node);
          break;

        case 'VECTOR':
        case 'RECTANGLE':
        case 'ELLIPSE':
          result.assets.push(await this.exportAsset(node));
          break;

        default:
          result.code = await this.exportGeneric(node);
      }

    } catch (error) {
      result.error = error.message;
      logger.error(`Failed to export node ${node.id}:`, error);
    }

    return result;
  }

  /**
   * Export component to code
   */
  async exportComponent(node) {
    return {
      jsx: this.generateJSX(node),
      css: this.generateCSS(node),
      props: this.extractProps(node),
      imports: this.generateImports(node)
    };
  }

  /**
   * Export frame to code
   */
  async exportFrame(node) {
    return {
      jsx: this.generateFrameJSX(node),
      css: this.generateFrameCSS(node),
      layout: this.extractLayout(node)
    };
  }

  /**
   * Export text node
   */
  async exportText(node) {
    return {
      content: node.characters || '',
      styles: this.extractTextStyles(node)
    };
  }

  /**
   * Export asset
   */
  async exportAsset(node) {
    return {
      id: node.id,
      name: node.name,
      type: 'svg',
      data: node.svgData || null,
      dimensions: {
        width: node.width,
        height: node.height
      }
    };
  }

  /**
   * Export generic node
   */
  async exportGeneric(node) {
    return {
      type: node.type,
      properties: this.extractProperties(node)
    };
  }

  /**
   * Process selected nodes
   */
  async processSelectedNodes(nodes, clientId) {
    const processed = [];

    for (const node of nodes) {
      try {
        const result = await this.exportNode(node);
        processed.push(result);
      } catch (error) {
        logger.error(`Failed to process node ${node.id}:`, error);
      }
    }

    this.emit('nodes:processed', {
      nodes,
      results: processed,
      clientId
    });
  }

  /**
   * Register default transformers
   */
  registerDefaultTransformers() {
    // Component transformer
    this.registerTransformer('component', (data, results) => {
      if (data.components) {
        results.components = data.components.map(comp => ({
          id: comp.id,
          name: comp.name,
          props: comp.properties || {},
          children: comp.children || []
        }));
      }
      return results;
    });

    // Token transformer
    this.registerTransformer('tokens', (data, results) => {
      if (data.styles) {
        results.tokens = {
          colors: data.styles.colors || {},
          typography: data.styles.typography || {},
          spacing: data.styles.spacing || {},
          shadows: data.styles.effects || {}
        };
      }
      return results;
    });

    // Asset transformer
    this.registerTransformer('assets', (data, results) => {
      if (data.images) {
        results.assets = data.images.map(img => ({
          id: img.id,
          url: img.url,
          name: img.name
        }));
      }
      return results;
    });
  }

  /**
   * Register a custom transformer
   */
  registerTransformer(name, transformer) {
    this.transformers.set(name, transformer);
  }

  // Helper methods for code generation
  generateJSX(node) {
    return `<div className="${node.name.toLowerCase().replace(/\s+/g, '-')}">
  ${node.children ? node.children.map(child => `  <div>${child.name}</div>`).join('\n') : ''}
</div>`;
  }

  generateCSS(node) {
    return `.${node.name.toLowerCase().replace(/\s+/g, '-')} {
  width: ${node.width}px;
  height: ${node.height}px;
  ${node.fills ? `background: ${this.extractFillColor(node.fills)};` : ''}
}`;
  }

  generateFrameJSX(node) {
    return `<section className="${node.name.toLowerCase().replace(/\s+/g, '-')}">
  ${node.children ? node.children.map(child => `  <div>${child.name}</div>`).join('\n') : ''}
</section>`;
  }

  generateFrameCSS(node) {
    return `.${node.name.toLowerCase().replace(/\s+/g, '-')} {
  display: flex;
  width: ${node.width}px;
  height: ${node.height}px;
}`;
  }

  extractProps(node) {
    return {
      width: node.width,
      height: node.height,
      visible: node.visible !== false
    };
  }

  extractLayout(node) {
    return {
      type: node.layoutMode || 'none',
      padding: node.padding || 0,
      spacing: node.itemSpacing || 0
    };
  }

  extractTextStyles(node) {
    return {
      fontSize: node.fontSize || 16,
      fontFamily: node.fontName?.family || 'sans-serif',
      fontWeight: node.fontName?.style || 'normal',
      color: this.extractFillColor(node.fills)
    };
  }

  extractProperties(node) {
    return {
      x: node.x || 0,
      y: node.y || 0,
      width: node.width || 0,
      height: node.height || 0,
      visible: node.visible !== false
    };
  }

  extractFillColor(fills) {
    if (!fills || fills.length === 0) return 'transparent';
    const fill = fills[0];
    if (fill.type === 'SOLID') {
      const { r, g, b, a = 1 } = fill.color;
      return `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${a})`;
    }
    return 'transparent';
  }

  generateImports(node) {
    const imports = [];
    if (node.children && node.children.length > 0) {
      imports.push("import React from 'react';");
    }
    return imports;
  }

  /**
   * Get bridge statistics
   */
  getStats() {
    return {
      activeConnections: this.activeConnections.size,
      cachedDesigns: this.designCache.size,
      transformers: this.transformers.size,
      clients: Array.from(this.activeConnections.values())
    };
  }

  /**
   * Shutdown the Design Bridge
   */
  async shutdown() {
    if (this.wsServer) {
      await this.wsServer.stop();
    }

    this.activeConnections.clear();
    this.designCache.clear();
    this.removeAllListeners();

    logger.info('🌉 Design Bridge shut down');
  }
}

module.exports = { DesignBridge };