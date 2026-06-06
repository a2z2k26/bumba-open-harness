/**
 * notifier.js
 * Cross-platform desktop notification system for Design Bridge
 *
 * Provides notifications for:
 * - Token changes detected
 * - Transformation complete
 * - Story generation complete
 * - Errors during regeneration
 */

const path = require('path');
const EventEmitter = require('events');

class Notifier extends EventEmitter {
  constructor(options = {}) {
    super();

    this.enabled = options.enabled !== false;
    this.silent = options.silent || false;
    this.appName = options.appName || 'Design Bridge';

    // Lazy load node-notifier only when needed
    this._notifier = null;
  }

  /**
   * Get notifier instance (lazy loaded)
   */
  get notifier() {
    if (!this._notifier && this.enabled) {
      try {
        this._notifier = require('node-notifier');
      } catch (error) {
        if (!this.silent) {
          console.warn('⚠️  node-notifier not available, notifications disabled');
        }
        this.enabled = false;
      }
    }
    return this._notifier;
  }

  /**
   * Send a notification
   *
   * @param {Object} options - Notification options
   * @param {string} options.title - Notification title
   * @param {string} options.message - Notification message
   * @param {string} [options.type='info'] - Notification type (info, success, warn, error)
   * @param {string} [options.sound] - Sound to play
   * @param {number} [options.timeout=5] - Timeout in seconds
   */
  notify({ title, message, type = 'info', sound = false, timeout = 5 }) {
    if (!this.enabled || !this.notifier) {
      return;
    }

    const icons = {
      info: '💡',
      success: '✅',
      warn: '⚠️',
      error: '❌'
    };

    const icon = icons[type] || icons.info;

    this.notifier.notify({
      title: `${icon} ${title}`,
      message: message,
      sound: sound || false,
      timeout: timeout,
      appName: this.appName,
      wait: false
    }, (err, response, metadata) => {
      if (err && !this.silent) {
        console.warn('Notification error:', err.message);
      }

      this.emit('notification:sent', { title, message, type, response, metadata });
    });
  }

  /**
   * Token change notification
   */
  tokenChanged(fileName, eventType) {
    this.notify({
      title: 'Token Changed',
      message: `${fileName} was ${eventType}`,
      type: 'info'
    });
  }

  /**
   * Transformation started notification
   */
  transformationStarted(framework) {
    this.notify({
      title: 'Transformation Started',
      message: `Regenerating ${framework} design system...`,
      type: 'info'
    });
  }

  /**
   * Transformation complete notification
   */
  transformationComplete(framework, filesGenerated) {
    this.notify({
      title: 'Transformation Complete',
      message: `${framework}: Generated ${filesGenerated} files`,
      type: 'success',
      sound: 'Ping'
    });
  }

  /**
   * Story generation complete notification
   */
  storiesGenerated(count) {
    this.notify({
      title: 'Stories Generated',
      message: `Created ${count} Storybook stories`,
      type: 'success'
    });
  }

  /**
   * Error notification
   */
  error(title, message) {
    this.notify({
      title: title || 'Error',
      message: message,
      type: 'error',
      sound: 'Basso',
      timeout: 10
    });
  }

  /**
   * Warning notification
   */
  warn(title, message) {
    this.notify({
      title: title || 'Warning',
      message: message,
      type: 'warn',
      timeout: 8
    });
  }

  /**
   * Success notification
   */
  success(title, message) {
    this.notify({
      title: title || 'Success',
      message: message,
      type: 'success',
      sound: 'Glass'
    });
  }

  /**
   * Info notification
   */
  info(title, message) {
    this.notify({
      title: title || 'Info',
      message: message,
      type: 'info'
    });
  }

  /**
   * Enable notifications
   */
  enable() {
    this.enabled = true;
  }

  /**
   * Disable notifications
   */
  disable() {
    this.enabled = false;
  }

  /**
   * Check if notifications are enabled
   */
  isEnabled() {
    return this.enabled && !!this.notifier;
  }
}

/**
 * Create a notifier instance
 *
 * @param {Object} options - Notifier options
 * @returns {Notifier} Notifier instance
 */
function createNotifier(options = {}) {
  return new Notifier(options);
}

/**
 * Default notifier instance (singleton)
 */
let defaultNotifier = null;

/**
 * Get default notifier instance
 *
 * @returns {Notifier} Default notifier
 */
function getDefaultNotifier() {
  if (!defaultNotifier) {
    defaultNotifier = createNotifier({
      enabled: process.env.DESIGN_BRIDGE_NOTIFICATIONS !== 'false',
      silent: true
    });
  }
  return defaultNotifier;
}

module.exports = {
  Notifier,
  createNotifier,
  getDefaultNotifier
};
