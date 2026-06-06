#!/usr/bin/env node
/**
 * Test Server for Figma Plugin Testing (Phase 10)
 * Starts PluginBridge server for Figma plugin communication
 */

const path = require('path');

// Check for required dependencies
let hasExpress = true;
let hasWs = true;

try {
  require.resolve('express');
} catch (e) {
  hasExpress = false;
}

try {
  require.resolve('ws');
} catch (e) {
  hasWs = false;
}

console.log('========================================');
console.log('  BUMBA Design Bridge - Test Server');
console.log('  Phase 10: Figma Plugin Testing');
console.log('========================================\n');

// Check dependencies
console.log('Checking dependencies...');
console.log(`  express: ${hasExpress ? '✓ installed' : '✗ missing'}`);
console.log(`  ws:      ${hasWs ? '✓ installed' : '✗ missing'}`);
console.log(`  cors:    checking...`);

if (!hasExpress || !hasWs) {
  console.log('\n⚠️  Missing dependencies. Install with:');
  console.log('   npm install express ws cors\n');

  // Run in mock mode for testing
  console.log('Starting in MOCK MODE (no actual server)...\n');

  // Create mock server info
  const mockServer = {
    port: 9001,
    wsPort: 9002,
    status: 'mock'
  };

  console.log('Mock Server Info:');
  console.log(`  HTTP:      http://localhost:${mockServer.port}`);
  console.log(`  WebSocket: ws://localhost:${mockServer.wsPort}`);
  console.log(`  Status:    ${mockServer.status}`);
  console.log('\nTo run actual server, install dependencies first.');

  process.exit(0);
}

// Load and start PluginBridge
try {
  const PluginBridge = require('./plugin-bridge');

  const bridge = new PluginBridge({
    port: 9001,
    wsPort: 9002
  });

  // Start server
  bridge.start().then(() => {
    console.log('\n✓ Server started successfully!\n');
    console.log('Server Info:');
    console.log(`  HTTP:      http://localhost:${bridge.port}`);
    console.log(`  WebSocket: ws://localhost:${bridge.wsPort}`);
    console.log(`  Health:    http://localhost:${bridge.port}/health`);
    console.log('\nEndpoints:');
    console.log(`  POST /api/tokens     - Receive tokens from Figma`);
    console.log(`  POST /api/sync       - Manual sync trigger`);
    console.log(`  GET  /api/status     - Connection status`);
    console.log('\nListening for Figma plugin connections...');
    console.log('Press Ctrl+C to stop.\n');

    // Event logging
    bridge.on('tokens:received', (data) => {
      console.log(`[${new Date().toISOString()}] Tokens received:`, data.metadata?.component || 'unknown');
    });

    bridge.on('transform:started', (data) => {
      console.log(`[${new Date().toISOString()}] Transform started: ${data.framework}`);
    });

    bridge.on('transform:completed', (data) => {
      console.log(`[${new Date().toISOString()}] Transform completed: ${data.componentsGenerated} components`);
    });

    bridge.on('transform:failed', (data) => {
      console.error(`[${new Date().toISOString()}] Transform failed:`, data.error);
    });

  }).catch(err => {
    console.error('Failed to start server:', err.message);
    process.exit(1);
  });

} catch (err) {
  console.error('Error loading PluginBridge:', err.message);
  console.log('\nTrying alternative startup...');

  // Alternative: Direct express server
  const express = require('express');
  const cors = require('cors');

  const app = express();
  app.use(cors());
  app.use(express.json({ limit: '10mb' }));

  app.get('/health', (req, res) => {
    res.json({
      status: 'running',
      version: '1.0.0',
      timestamp: new Date().toISOString()
    });
  });

  app.post('/api/tokens', (req, res) => {
    console.log('[Tokens received]', Object.keys(req.body));
    res.json({ success: true, received: true });
  });

  // Plugin registration endpoint
  app.post('/api/register', (req, res) => {
    const { pluginId, version, metadata } = req.body;
    console.log(`[Plugin registered] ${pluginId || 'unknown'} v${version || '?'}`);
    res.json({
      success: true,
      sessionId: `session-${Date.now()}`,
      message: 'Plugin registered successfully'
    });
  });

  const PORT = 9001;
  app.listen(PORT, () => {
    console.log(`\n✓ Fallback server running on http://localhost:${PORT}`);
    console.log('Press Ctrl+C to stop.\n');
  });
}
