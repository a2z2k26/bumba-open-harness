/**
 * Webhook Manager for Figma Real-time Updates
 * Handles webhook registration, validation, and event processing
 */

const crypto = require('crypto');
const EventEmitter = require('events');
const chalk = require('chalk');

class WebhookManager extends EventEmitter {
  constructor(options = {}) {
    super();

    this.secret = options.secret || process.env.FIGMA_WEBHOOK_SECRET;
    this.endpoint = options.endpoint || '/webhooks/figma';
    this.passcode = options.passcode || this.generatePasscode();
    this.retryAttempts = options.retryAttempts || 3;
    this.retryDelay = options.retryDelay || 5000;

    this.activeWebhooks = new Map();
    this.eventQueue = [];
    this.processing = false;
  }

  /**
   * Register webhook with Figma
   */
  async register(fileKey, eventTypes = ['FILE_UPDATE', 'FILE_VERSION_UPDATE']) {
    console.log(chalk.blue('📡 Registering Figma webhook...'));

    try {
      // In production, this would call Figma API:
      // POST https://api.figma.com/v2/webhooks
      const webhook = {
        id: `webhook_${Date.now()}`,
        event_type: eventTypes,
        team_id: process.env.FIGMA_TEAM_ID,
        status: 'ACTIVE',
        client_id: process.env.FIGMA_CLIENT_ID,
        endpoint: `${process.env.APP_URL}${this.endpoint}`,
        passcode: this.passcode,
        created_at: new Date().toISOString(),
        description: `BUMBA Design Bridge webhook for ${fileKey}`
      };

      this.activeWebhooks.set(webhook.id, webhook);

      console.log(chalk.green('✅ Webhook registered:'), webhook.id);

      return webhook;
    } catch (error) {
      console.error(chalk.red('❌ Webhook registration failed:'), error.message);
      throw error;
    }
  }

  /**
   * Validate incoming webhook request
   */
  validateRequest(req) {
    const signature = req.headers['x-figma-signature'];
    const timestamp = req.headers['x-figma-timestamp'];
    const payload = JSON.stringify(req.body);

    // Verify timestamp is recent (within 5 minutes)
    const currentTime = Math.floor(Date.now() / 1000);
    if (Math.abs(currentTime - parseInt(timestamp)) > 300) {
      throw new Error('Webhook timestamp too old');
    }

    // Verify signature
    const expectedSignature = this.generateSignature(timestamp, payload);
    if (signature !== expectedSignature) {
      throw new Error('Invalid webhook signature');
    }

    // Verify passcode
    if (req.body.passcode !== this.passcode) {
      throw new Error('Invalid webhook passcode');
    }

    return true;
  }

  /**
   * Process incoming webhook event
   */
  async processEvent(event) {
    console.log(chalk.yellow('⚡ Processing webhook event:'), event.event_type);

    try {
      // Add to queue
      this.eventQueue.push({
        ...event,
        received_at: new Date().toISOString(),
        status: 'pending'
      });

      // Process queue if not already processing
      if (!this.processing) {
        await this.processQueue();
      }

      return { success: true, queued: true };
    } catch (error) {
      console.error(chalk.red('❌ Event processing failed:'), error.message);
      throw error;
    }
  }

  /**
   * Process event queue
   */
  async processQueue() {
    if (this.processing || this.eventQueue.length === 0) return;

    this.processing = true;

    while (this.eventQueue.length > 0) {
      const event = this.eventQueue.shift();

      try {
        await this.handleEvent(event);
        event.status = 'completed';
        this.emit('event:processed', event);
      } catch (error) {
        event.status = 'failed';
        event.error = error.message;
        event.retries = (event.retries || 0) + 1;

        if (event.retries < this.retryAttempts) {
          // Retry later
          setTimeout(() => {
            event.status = 'pending';
            this.eventQueue.push(event);
            this.processQueue();
          }, this.retryDelay * event.retries);
        } else {
          this.emit('event:failed', event);
        }
      }
    }

    this.processing = false;
  }

  /**
   * Handle specific event types
   */
  async handleEvent(event) {
    const handlers = {
      'FILE_UPDATE': this.handleFileUpdate.bind(this),
      'FILE_VERSION_UPDATE': this.handleVersionUpdate.bind(this),
      'FILE_DELETE': this.handleFileDelete.bind(this),
      'COMMENT': this.handleComment.bind(this),
      'LIBRARY_PUBLISH': this.handleLibraryPublish.bind(this)
    };

    const handler = handlers[event.event_type];
    if (!handler) {
      console.warn(chalk.yellow('⚠️  Unknown event type:'), event.event_type);
      return;
    }

    await handler(event);
  }

  /**
   * Handle file update event
   */
  async handleFileUpdate(event) {
    console.log(chalk.blue('📝 File updated:'), event.file_key);

    const changeData = {
      file_key: event.file_key,
      file_name: event.file_name,
      timestamp: event.timestamp,
      triggered_by: event.triggered_by,
      changes: []
    };

    // Emit for processing
    this.emit('file:update', changeData);

    // Trigger token re-extraction
    this.emit('tokens:stale', { file_key: event.file_key });
  }

  /**
   * Handle version update event
   */
  async handleVersionUpdate(event) {
    console.log(chalk.blue('🔄 Version updated:'), event.file_key);

    const versionData = {
      file_key: event.file_key,
      version_id: event.version_id,
      label: event.label,
      description: event.description,
      created_at: event.created_at,
      created_by: event.created_by
    };

    this.emit('version:update', versionData);

    // Check if this is a major version
    if (this.isMajorVersion(event.label)) {
      this.emit('version:major', versionData);
    }
  }

  /**
   * Handle file delete event
   */
  async handleFileDelete(event) {
    console.log(chalk.red('🗑️  File deleted:'), event.file_key);

    this.emit('file:delete', {
      file_key: event.file_key,
      deleted_at: event.timestamp
    });
  }

  /**
   * Handle comment event
   */
  async handleComment(event) {
    console.log(chalk.blue('💬 New comment:'), event.comment.message);

    const commentData = {
      file_key: event.file_key,
      comment_id: event.comment.id,
      message: event.comment.message,
      user: event.comment.user,
      created_at: event.comment.created_at,
      resolved: event.comment.resolved
    };

    this.emit('comment:added', commentData);

    // Check for design review mentions
    if (this.isDesignReview(event.comment.message)) {
      this.emit('review:requested', commentData);
    }
  }

  /**
   * Handle library publish event
   */
  async handleLibraryPublish(event) {
    console.log(chalk.green('📚 Library published:'), event.library_name);

    const publishData = {
      file_key: event.file_key,
      library_name: event.library_name,
      description: event.description,
      published_at: event.timestamp,
      components_count: event.created_components?.length || 0,
      styles_count: event.created_styles?.length || 0
    };

    this.emit('library:publish', publishData);

    // Trigger full sync for library updates
    this.emit('sync:required', {
      file_key: event.file_key,
      reason: 'library_publish'
    });
  }

  /**
   * Unregister webhook
   */
  async unregister(webhookId) {
    console.log(chalk.yellow('🔌 Unregistering webhook:'), webhookId);

    try {
      // In production, this would call Figma API:
      // DELETE https://api.figma.com/v2/webhooks/{webhook_id}

      this.activeWebhooks.delete(webhookId);

      console.log(chalk.green('✅ Webhook unregistered'));

      return { success: true };
    } catch (error) {
      console.error(chalk.red('❌ Unregistration failed:'), error.message);
      throw error;
    }
  }

  /**
   * List active webhooks
   */
  async listWebhooks() {
    return Array.from(this.activeWebhooks.values());
  }

  /**
   * Test webhook endpoint
   */
  async testWebhook(webhookId) {
    const webhook = this.activeWebhooks.get(webhookId);
    if (!webhook) {
      throw new Error('Webhook not found');
    }

    const testEvent = {
      event_type: 'PING',
      passcode: this.passcode,
      timestamp: Math.floor(Date.now() / 1000),
      file_key: 'test',
      webhook_id: webhookId
    };

    console.log(chalk.blue('🏓 Sending test ping...'));

    // Simulate webhook delivery
    await this.processEvent(testEvent);

    return { success: true, tested_at: new Date().toISOString() };
  }

  /**
   * Setup Express routes for webhook endpoint
   */
  setupRoutes(app) {
    // Webhook endpoint
    app.post(this.endpoint, async (req, res) => {
      try {
        // Validate request
        this.validateRequest(req);

        // Process event
        const result = await this.processEvent(req.body);

        // Respond quickly to Figma
        res.status(200).json({
          success: true,
          received_at: new Date().toISOString()
        });
      } catch (error) {
        console.error(chalk.red('Webhook error:'), error.message);
        res.status(400).json({
          error: error.message
        });
      }
    });

    // Webhook management endpoints
    app.get(`${this.endpoint}/list`, async (req, res) => {
      const webhooks = await this.listWebhooks();
      res.json({ webhooks });
    });

    app.post(`${this.endpoint}/test/:id`, async (req, res) => {
      try {
        const result = await this.testWebhook(req.params.id);
        res.json(result);
      } catch (error) {
        res.status(400).json({ error: error.message });
      }
    });

    console.log(chalk.green('✅ Webhook routes configured'));
  }

  // Helper methods
  generatePasscode() {
    return crypto.randomBytes(32).toString('hex');
  }

  generateSignature(timestamp, payload) {
    const message = `${timestamp}.${payload}`;
    return crypto
      .createHmac('sha256', this.secret)
      .update(message)
      .digest('hex');
  }

  isMajorVersion(label) {
    return /^v?\d+\.0\.0/i.test(label);
  }

  isDesignReview(message) {
    const reviewKeywords = ['review', 'approve', 'feedback', 'lgtm', 'approved'];
    return reviewKeywords.some(keyword =>
      message.toLowerCase().includes(keyword)
    );
  }

  /**
   * Get webhook statistics
   */
  getStatistics() {
    return {
      active_webhooks: this.activeWebhooks.size,
      queued_events: this.eventQueue.length,
      processing: this.processing,
      events: {
        total: this.eventQueue.filter(e => e.status === 'completed').length,
        pending: this.eventQueue.filter(e => e.status === 'pending').length,
        failed: this.eventQueue.filter(e => e.status === 'failed').length
      }
    };
  }
}

module.exports = WebhookManager;