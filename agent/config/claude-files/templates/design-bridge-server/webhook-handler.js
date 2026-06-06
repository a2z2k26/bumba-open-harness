/**
 * Design Bridge Webhook Handler
 * Sprint 32: Auto-sync webhook trigger for Figma events
 *
 * Handles incoming webhooks from Figma to trigger automatic component regeneration
 */

const EventEmitter = require('events');
const crypto = require('crypto');
const path = require('path');
const fs = require('fs');

class WebhookHandler extends EventEmitter {
  constructor(options = {}) {
    super();
    this.name = 'WebhookHandler';
    this.version = '1.0.0';

    // Configuration
    this.config = {
      secret: options.secret || process.env.FIGMA_WEBHOOK_SECRET || '',
      autoSync: options.autoSync !== false,
      debounceMs: options.debounceMs || 2000, // Debounce rapid webhook calls
      outputDir: options.outputDir || './src/components',
      framework: options.framework || 'react',
      projectPath: options.projectPath || process.cwd()
    };

    // Debounce timers per component
    this.pendingUpdates = new Map();

    // Statistics
    this.stats = {
      webhooksReceived: 0,
      componentsRegenerated: 0,
      errors: 0,
      lastWebhook: null
    };

    // Generator reference (injected or loaded)
    this.generator = options.generator || null;
    this.storyGenerator = options.storyGenerator || null;

    console.log('✓ WebhookHandler initialized');
  }

  /**
   * Set the code generator instance
   */
  setGenerator(generator) {
    this.generator = generator;
  }

  /**
   * Set the story generator instance
   */
  setStoryGenerator(storyGenerator) {
    this.storyGenerator = storyGenerator;
  }

  /**
   * Verify webhook signature from Figma
   */
  verifySignature(payload, signature) {
    if (!this.config.secret) {
      console.warn('⚠ No webhook secret configured - skipping signature verification');
      return true;
    }

    const expectedSignature = crypto
      .createHmac('sha256', this.config.secret)
      .update(payload)
      .digest('hex');

    return crypto.timingSafeEqual(
      Buffer.from(signature),
      Buffer.from(expectedSignature)
    );
  }

  /**
   * Handle incoming webhook from Figma
   * @param {Object} event - Figma webhook event
   * @param {string} signature - X-Figma-Signature header
   * @returns {Object} Response status
   */
  async handleWebhook(event, signature = '') {
    this.stats.webhooksReceived++;
    this.stats.lastWebhook = new Date().toISOString();

    try {
      // Verify signature if configured
      if (this.config.secret && signature) {
        const payload = JSON.stringify(event);
        if (!this.verifySignature(payload, signature)) {
          this.stats.errors++;
          this.emit('webhook:invalid', { reason: 'Invalid signature' });
          return { success: false, error: 'Invalid signature' };
        }
      }

      // Parse event type
      const eventType = event.event_type || event.type;
      const fileKey = event.file_key || event.fileKey;
      const timestamp = event.timestamp || new Date().toISOString();

      console.log(`📨 Webhook received: ${eventType} for file ${fileKey}`);

      // Handle different event types
      switch (eventType) {
        case 'FILE_UPDATE':
        case 'LIBRARY_PUBLISH':
          return await this.handleFileUpdate(event);

        case 'FILE_VERSION_UPDATE':
          return await this.handleVersionUpdate(event);

        case 'FILE_COMMENT':
          // Comments don't trigger regeneration
          this.emit('webhook:comment', event);
          return { success: true, action: 'none', reason: 'Comment event ignored' };

        case 'PING':
          // Health check from Figma
          this.emit('webhook:ping', event);
          return { success: true, action: 'pong' };

        default:
          console.log(`⚠ Unknown webhook event type: ${eventType}`);
          return { success: true, action: 'none', reason: `Unknown event: ${eventType}` };
      }
    } catch (error) {
      this.stats.errors++;
      console.error('❌ Webhook handling error:', error.message);
      this.emit('webhook:error', { error });
      return { success: false, error: error.message };
    }
  }

  /**
   * Handle file update events - trigger component regeneration
   */
  async handleFileUpdate(event) {
    const fileKey = event.file_key || event.fileKey;
    const modifiedComponents = event.modified_components || [];

    // If no specific components, regenerate all
    if (modifiedComponents.length === 0) {
      return await this.triggerFullRegeneration(fileKey);
    }

    // Debounced regeneration per component
    for (const component of modifiedComponents) {
      this.scheduleRegeneration(component.id || component, component.name || component);
    }

    return {
      success: true,
      action: 'scheduled',
      componentsScheduled: modifiedComponents.length
    };
  }

  /**
   * Handle version update events
   */
  async handleVersionUpdate(event) {
    const fileKey = event.file_key || event.fileKey;
    const versionId = event.version_id || event.versionId;

    console.log(`📦 New version published: ${versionId} for file ${fileKey}`);

    // Version updates usually mean significant changes - do full regen
    return await this.triggerFullRegeneration(fileKey);
  }

  /**
   * Schedule component regeneration with debouncing
   */
  scheduleRegeneration(componentId, componentName) {
    // Clear existing timer
    if (this.pendingUpdates.has(componentId)) {
      clearTimeout(this.pendingUpdates.get(componentId));
    }

    // Schedule new regeneration
    const timer = setTimeout(async () => {
      this.pendingUpdates.delete(componentId);
      await this.regenerateComponent(componentId, componentName);
    }, this.config.debounceMs);

    this.pendingUpdates.set(componentId, timer);
    console.log(`⏱ Scheduled regeneration for ${componentName} (${componentId})`);
  }

  /**
   * Regenerate a specific component
   */
  async regenerateComponent(componentId, componentName) {
    if (!this.generator) {
      console.error('❌ No generator configured - cannot regenerate');
      return { success: false, error: 'No generator configured' };
    }

    try {
      console.log(`🔄 Regenerating component: ${componentName}`);

      // Load component data from Figma cache
      const componentData = await this.loadComponentData(componentId, componentName);
      if (!componentData) {
        return { success: false, error: 'Component data not found' };
      }

      // Generate code
      const result = await this.generator.generateCode(componentData, {
        framework: this.config.framework,
        typescript: true,
        validateSchema: false
      });

      // Write files
      await this.writeGeneratedFiles(componentName, result);

      // Generate story if story generator available
      if (this.storyGenerator) {
        const story = this.storyGenerator.generateStoryFile(componentData, this.config.framework);
        await this.writeStoryFile(componentName, story);
      }

      this.stats.componentsRegenerated++;
      this.emit('component:regenerated', { componentId, componentName, result });

      console.log(`✅ Regenerated: ${componentName}`);
      return { success: true, component: componentName };

    } catch (error) {
      this.stats.errors++;
      console.error(`❌ Failed to regenerate ${componentName}:`, error.message);
      this.emit('component:error', { componentId, componentName, error });
      return { success: false, error: error.message };
    }
  }

  /**
   * Trigger full regeneration of all components
   */
  async triggerFullRegeneration(fileKey) {
    console.log(`🔄 Full regeneration triggered for file: ${fileKey}`);

    // Emit event for external handling (CLI can listen to this)
    this.emit('regenerate:full', { fileKey });

    return {
      success: true,
      action: 'full-regeneration',
      fileKey
    };
  }

  /**
   * Load component data from local Figma cache
   */
  async loadComponentData(componentId, componentName) {
    const figmaDir = path.join(this.config.projectPath, '.design', 'figma', 'components');
    const possibleFiles = [
      path.join(figmaDir, `${componentName}.json`),
      path.join(figmaDir, `${componentId}.json`),
      path.join(figmaDir, `${componentName.replace(/\s+/g, '')}.json`)
    ];

    for (const filePath of possibleFiles) {
      if (fs.existsSync(filePath)) {
        const content = fs.readFileSync(filePath, 'utf-8');
        return JSON.parse(content);
      }
    }

    return null;
  }

  /**
   * Write generated component files
   */
  async writeGeneratedFiles(componentName, result) {
    const sanitizedName = componentName.replace(/\s+/g, '');
    const componentDir = path.join(this.config.projectPath, this.config.outputDir, sanitizedName);

    // Ensure directory exists
    if (!fs.existsSync(componentDir)) {
      fs.mkdirSync(componentDir, { recursive: true });
    }

    // Write component file
    const ext = this.config.framework === 'vue' ? 'vue' :
                this.config.framework === 'svelte' ? 'svelte' : 'tsx';
    const componentPath = path.join(componentDir, `${sanitizedName}.${ext}`);
    fs.writeFileSync(componentPath, result.code);

    // Write index.ts
    const indexPath = path.join(componentDir, 'index.ts');
    const indexContent = `export { ${sanitizedName}, default } from './${sanitizedName}';\nexport type { ${sanitizedName}Props } from './${sanitizedName}';\n`;
    fs.writeFileSync(indexPath, indexContent);
  }

  /**
   * Write story file
   */
  async writeStoryFile(componentName, storyContent) {
    const sanitizedName = componentName.replace(/\s+/g, '');
    const componentDir = path.join(this.config.projectPath, this.config.outputDir, sanitizedName);
    const storyPath = path.join(componentDir, `${sanitizedName}.stories.tsx`);

    if (storyContent && storyContent.content) {
      fs.writeFileSync(storyPath, storyContent.content);
    }
  }

  /**
   * Create Express middleware for webhook endpoint
   */
  createMiddleware() {
    return async (req, res) => {
      const signature = req.headers['x-figma-signature'] || '';
      const result = await this.handleWebhook(req.body, signature);

      if (result.success) {
        res.status(200).json(result);
      } else {
        res.status(400).json(result);
      }
    };
  }

  /**
   * Get handler statistics
   */
  getStats() {
    return {
      ...this.stats,
      pendingUpdates: this.pendingUpdates.size,
      config: {
        autoSync: this.config.autoSync,
        debounceMs: this.config.debounceMs,
        framework: this.config.framework
      }
    };
  }
}

module.exports = WebhookHandler;
