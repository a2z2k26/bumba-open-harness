/**
 * Webhook Activator
 * Sprint 35: Webhook System Activation
 *
 * Activates webhook notifications for design bridge events:
 * - Sync events (started, completed, failed)
 * - Token events (extracted, validated, changed)
 * - Generation events (started, completed, failed)
 * - Export events (started, completed)
 * - Validation events (schema, token)
 */

const EventEmitter = require('events');
const axios = require('axios');
const crypto = require('crypto');

class WebhookActivator extends EventEmitter {
  constructor(options = {}) {
    super();

    this.options = {
      enableWebhooks: options.enableWebhooks !== false,
      secret: options.secret || process.env.WEBHOOK_SECRET || this.generateSecret(),
      maxRetries: options.maxRetries || 3,
      retryDelay: options.retryDelay || 2000,
      timeout: options.timeout || 10000,
      ...options
    };

    // Registered webhooks
    this.webhooks = new Map();

    // Event-to-webhook mappings
    this.eventMappings = this.initializeEventMappings();

    // Delivery queue
    this.deliveryQueue = [];
    this.processing = false;

    // Statistics
    this.stats = {
      totalDeliveries: 0,
      successfulDeliveries: 0,
      failedDeliveries: 0,
      totalRetries: 0
    };
  }

  /**
   * Initialize event-to-webhook mappings
   */
  initializeEventMappings() {
    return {
      // Sync events
      'sync:started': { enabled: true, priority: 1 },
      'sync:completed': { enabled: true, priority: 1 },
      'sync:failed': { enabled: true, priority: 2 },

      // Token events
      'tokens:extracted': { enabled: true, priority: 1 },
      'tokens:normalized': { enabled: false, priority: 3 },
      'tokens:validated': { enabled: true, priority: 1 },
      'tokens:changed': { enabled: true, priority: 1 },

      // Generation events
      'generation:started': { enabled: true, priority: 1 },
      'generation:completed': { enabled: true, priority: 1 },
      'generation:failed': { enabled: true, priority: 2 },

      // Multi-framework generation
      'multi-framework:started': { enabled: true, priority: 1 },
      'multi-framework:completed': { enabled: true, priority: 1 },

      // Export events
      'export:started': { enabled: false, priority: 3 },
      'export:completed': { enabled: true, priority: 1 },

      // Validation events
      'validation:failed': { enabled: true, priority: 2 },
      'schema:invalid': { enabled: true, priority: 2 },

      // State events
      'state:changed': { enabled: false, priority: 4 },
      'state:snapshot': { enabled: false, priority: 4 }
    };
  }

  /**
   * Register webhook endpoint
   */
  registerWebhook(name, url, events = [], options = {}) {
    const webhookId = `webhook_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

    const webhook = {
      id: webhookId,
      name,
      url,
      events: events.length > 0 ? events : Object.keys(this.eventMappings),
      active: options.active !== false,
      secret: options.secret || this.options.secret,
      headers: options.headers || {},
      retryConfig: {
        maxRetries: options.maxRetries || this.options.maxRetries,
        retryDelay: options.retryDelay || this.options.retryDelay
      },
      createdAt: new Date().toISOString(),
      lastTriggered: null,
      deliveryCount: 0,
      failureCount: 0
    };

    this.webhooks.set(webhookId, webhook);

    this.emit('webhook:registered', {
      id: webhookId,
      name,
      events: webhook.events.length
    });

    return webhook;
  }

  /**
   * Unregister webhook
   */
  unregisterWebhook(webhookId) {
    const removed = this.webhooks.delete(webhookId);

    if (removed) {
      this.emit('webhook:unregistered', { id: webhookId });
    }

    return removed;
  }

  /**
   * Trigger webhook for event
   */
  async triggerWebhook(eventName, payload) {
    if (!this.options.enableWebhooks) {
      return { delivered: 0, skipped: 'webhooks disabled' };
    }

    const eventConfig = this.eventMappings[eventName];

    if (!eventConfig || !eventConfig.enabled) {
      return { delivered: 0, skipped: 'event not enabled' };
    }

    // Find webhooks subscribed to this event
    const subscribedWebhooks = Array.from(this.webhooks.values()).filter(
      webhook => webhook.active && webhook.events.includes(eventName)
    );

    if (subscribedWebhooks.length === 0) {
      return { delivered: 0, skipped: 'no subscribers' };
    }

    // Queue deliveries
    const deliveries = subscribedWebhooks.map(webhook =>
      this.queueDelivery(webhook, eventName, payload, eventConfig.priority)
    );

    // Process delivery queue
    if (!this.processing) {
      this.processDeliveryQueue();
    }

    return {
      delivered: deliveries.length,
      webhooks: subscribedWebhooks.map(w => w.id)
    };
  }

  /**
   * Queue webhook delivery
   */
  queueDelivery(webhook, eventName, payload, priority = 3) {
    const delivery = {
      id: `delivery_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      webhookId: webhook.id,
      webhook,
      eventName,
      payload: this.preparePayload(eventName, payload),
      priority,
      attempts: 0,
      maxAttempts: webhook.retryConfig.maxRetries,
      status: 'queued',
      queuedAt: new Date().toISOString()
    };

    this.deliveryQueue.push(delivery);

    // Sort queue by priority (lower number = higher priority)
    this.deliveryQueue.sort((a, b) => a.priority - b.priority);

    this.emit('delivery:queued', {
      id: delivery.id,
      webhook: webhook.name,
      event: eventName
    });

    return delivery.id;
  }

  /**
   * Process delivery queue
   */
  async processDeliveryQueue() {
    if (this.processing || this.deliveryQueue.length === 0) {
      return;
    }

    this.processing = true;

    while (this.deliveryQueue.length > 0) {
      const delivery = this.deliveryQueue.shift();

      try {
        await this.deliverWebhook(delivery);
      } catch (error) {
        console.error(`Webhook delivery failed: ${delivery.id}`, error.message);

        // Retry if attempts remain
        if (delivery.attempts < delivery.maxAttempts) {
          this.stats.totalRetries++;

          // Re-queue with delay
          setTimeout(() => {
            this.deliveryQueue.push(delivery);
          }, delivery.webhook.retryConfig.retryDelay);
        } else {
          this.stats.failedDeliveries++;

          this.emit('delivery:failed', {
            id: delivery.id,
            webhook: delivery.webhook.name,
            event: delivery.eventName,
            error: error.message,
            attempts: delivery.attempts
          });
        }
      }
    }

    this.processing = false;
  }

  /**
   * Deliver webhook
   */
  async deliverWebhook(delivery) {
    delivery.attempts++;
    delivery.status = 'delivering';

    const { webhook, eventName, payload } = delivery;

    const signature = this.generateSignature(payload, webhook.secret);
    const timestamp = Math.floor(Date.now() / 1000);

    try {
      const response = await axios.post(webhook.url, payload, {
        headers: {
          'Content-Type': 'application/json',
          'X-Webhook-Signature': signature,
          'X-Webhook-Timestamp': timestamp,
          'X-Webhook-Event': eventName,
          'X-Webhook-Id': delivery.id,
          'X-Webhook-Delivery': delivery.attempts,
          ...webhook.headers
        },
        timeout: this.options.timeout
      });

      // Success
      this.stats.totalDeliveries++;
      this.stats.successfulDeliveries++;

      webhook.deliveryCount++;
      webhook.lastTriggered = new Date().toISOString();

      delivery.status = 'delivered';
      delivery.deliveredAt = new Date().toISOString();
      delivery.responseStatus = response.status;

      this.emit('delivery:success', {
        id: delivery.id,
        webhook: webhook.name,
        event: eventName,
        status: response.status,
        attempts: delivery.attempts
      });

      return response;

    } catch (error) {
      webhook.failureCount++;

      this.emit('delivery:error', {
        id: delivery.id,
        webhook: webhook.name,
        event: eventName,
        error: error.message,
        attempts: delivery.attempts
      });

      throw error;
    }
  }

  /**
   * Prepare webhook payload
   */
  preparePayload(eventName, data) {
    return {
      event: eventName,
      timestamp: new Date().toISOString(),
      data
    };
  }

  /**
   * Generate webhook signature
   */
  generateSignature(payload, secret) {
    const payloadString = typeof payload === 'string'
      ? payload
      : JSON.stringify(payload);

    return crypto
      .createHmac('sha256', secret)
      .update(payloadString)
      .digest('hex');
  }

  /**
   * Verify webhook signature
   */
  verifySignature(payload, signature, secret) {
    const expectedSignature = this.generateSignature(payload, secret);
    return crypto.timingSafeEqual(
      Buffer.from(signature),
      Buffer.from(expectedSignature)
    );
  }

  /**
   * Enable/disable event
   */
  setEventEnabled(eventName, enabled) {
    if (this.eventMappings[eventName]) {
      this.eventMappings[eventName].enabled = enabled;

      this.emit('event:configured', { event: eventName, enabled });

      return true;
    }

    return false;
  }

  /**
   * Get webhook statistics
   */
  getStats() {
    return {
      ...this.stats,
      activeWebhooks: Array.from(this.webhooks.values()).filter(w => w.active).length,
      totalWebhooks: this.webhooks.size,
      queueSize: this.deliveryQueue.length,
      successRate: this.stats.totalDeliveries > 0
        ? ((this.stats.successfulDeliveries / this.stats.totalDeliveries) * 100).toFixed(2) + '%'
        : 'N/A'
    };
  }

  /**
   * List registered webhooks
   */
  listWebhooks() {
    return Array.from(this.webhooks.values()).map(webhook => ({
      id: webhook.id,
      name: webhook.name,
      url: webhook.url,
      events: webhook.events.length,
      active: webhook.active,
      deliveryCount: webhook.deliveryCount,
      failureCount: webhook.failureCount,
      lastTriggered: webhook.lastTriggered
    }));
  }

  /**
   * Get webhook by ID
   */
  getWebhook(webhookId) {
    return this.webhooks.get(webhookId);
  }

  /**
   * Update webhook
   */
  updateWebhook(webhookId, updates) {
    const webhook = this.webhooks.get(webhookId);

    if (!webhook) {
      throw new Error(`Webhook not found: ${webhookId}`);
    }

    Object.assign(webhook, updates);

    this.emit('webhook:updated', { id: webhookId, updates });

    return webhook;
  }

  /**
   * Helper: Generate secret
   */
  generateSecret() {
    return crypto.randomBytes(32).toString('hex');
  }

  /**
   * Test webhook delivery
   */
  async testWebhook(webhookId) {
    const webhook = this.webhooks.get(webhookId);

    if (!webhook) {
      throw new Error(`Webhook not found: ${webhookId}`);
    }

    const testPayload = {
      event: 'webhook:test',
      timestamp: new Date().toISOString(),
      data: {
        message: 'This is a test webhook delivery',
        webhook: {
          id: webhook.id,
          name: webhook.name
        }
      }
    };

    try {
      const delivery = {
        id: `test_${Date.now()}`,
        webhookId: webhook.id,
        webhook,
        eventName: 'webhook:test',
        payload: testPayload,
        priority: 1,
        attempts: 0,
        maxAttempts: 1,
        status: 'testing'
      };

      const result = await this.deliverWebhook(delivery);

      return {
        success: true,
        status: result.status,
        message: 'Webhook test successful'
      };

    } catch (error) {
      return {
        success: false,
        error: error.message,
        message: 'Webhook test failed'
      };
    }
  }
}

module.exports = WebhookActivator;
