/**
 * Accessibility Automation
 * Automated ARIA generation, alt text, keyboard navigation, contrast checking
 * Sprint 56: Accessibility Automation
 */

const EventEmitter = require('events');

class AccessibilityAutomation extends EventEmitter {
  constructor(options = {}) {
    super();
    this.wcagLevel = options.wcagLevel || 'AA'; // A, AA, or AAA
    this.autoFix = options.autoFix !== false;

    this.statistics = {
      audited: 0,
      violations: 0,
      warnings: 0,
      autoFixed: 0,
      ariaGenerated: 0,
      altTextGenerated: 0
    };

    this.contrastRatios = {
      'A': { normal: 3, large: 3 },
      'AA': { normal: 4.5, large: 3 },
      'AAA': { normal: 7, large: 4.5 }
    };
  }

  /**
   * Audit component for accessibility
   * @param {Object} component - Design component
   * @param {string} code - Generated code (optional)
   * @returns {Promise<Object>} Accessibility audit results
   */
  async audit(component, code = null) {
    this.statistics.audited++;

    const audit = {
      component: component.id || component.name,
      timestamp: new Date().toISOString(),
      wcagLevel: this.wcagLevel,
      violations: [],
      warnings: [],
      passed: [],
      suggestions: [],
      score: 100,
      autoFixes: []
    };

    try {
      // ARIA attributes audit
      const ariaAudit = await this.auditARIA(component, code);
      this.mergeAudit(audit, ariaAudit);

      // Alt text audit
      const altTextAudit = await this.auditAltText(component, code);
      this.mergeAudit(audit, altTextAudit);

      // Keyboard navigation audit
      const keyboardAudit = await this.auditKeyboardNavigation(component, code);
      this.mergeAudit(audit, keyboardAudit);

      // Color contrast audit
      const contrastAudit = await this.auditColorContrast(component);
      this.mergeAudit(audit, contrastAudit);

      // Focus management audit
      const focusAudit = await this.auditFocusManagement(component, code);
      this.mergeAudit(audit, focusAudit);

      // Calculate final score
      audit.score = this.calculateScore(audit);

      this.statistics.violations += audit.violations.length;
      this.statistics.warnings += audit.warnings.length;

      this.emit('audit:complete', audit);
      return audit;

    } catch (error) {
      console.error('Accessibility audit failed:', error);
      audit.error = error.message;
      return audit;
    }
  }

  /**
   * Audit ARIA attributes
   * @param {Object} component - Design component
   * @param {string} code - Generated code
   * @returns {Promise<Object>} ARIA audit results
   */
  async auditARIA(component, code) {
    const audit = {
      violations: [],
      warnings: [],
      passed: [],
      suggestions: [],
      autoFixes: []
    };

    const componentType = (component.type || '').toUpperCase();
    const componentName = (component.name || '').toLowerCase();

    // Check for interactive elements without ARIA
    if (this.isInteractive(component)) {
      const hasAriaLabel = code && (
        code.includes('aria-label') ||
        code.includes('aria-labelledby') ||
        code.includes('aria-describedby')
      );

      if (!hasAriaLabel) {
        audit.violations.push({
          rule: 'aria-label-required',
          severity: 'error',
          message: 'Interactive element missing ARIA label',
          wcag: '4.1.2',
          element: component.name
        });

        // Generate auto-fix
        const ariaLabel = this.generateARIALabel(component);
        audit.autoFixes.push({
          type: 'add-aria-label',
          attribute: 'aria-label',
          value: ariaLabel,
          code: `aria-label="${ariaLabel}"`
        });

        this.statistics.ariaGenerated++;
      } else {
        audit.passed.push('Interactive element has ARIA label');
      }
    }

    // Check for button roles
    if (componentType === 'BUTTON' || componentName.includes('button')) {
      if (code && !code.includes('role="button"') && !code.includes('<button')) {
        audit.warnings.push({
          rule: 'button-role',
          severity: 'warning',
          message: 'Consider using <button> element or role="button"',
          wcag: '4.1.2',
          element: component.name
        });

        audit.autoFixes.push({
          type: 'add-role',
          attribute: 'role',
          value: 'button',
          code: 'role="button"'
        });
      }
    }

    // Check for form elements
    if (componentType === 'INPUT' || componentName.includes('input') || componentName.includes('field')) {
      audit.suggestions.push({
        type: 'form-accessibility',
        suggestions: [
          'Associate input with label using htmlFor/id',
          'Add aria-required for required fields',
          'Add aria-invalid for validation errors',
          'Include error messages with aria-describedby'
        ]
      });
    }

    // Check for headings
    if (componentName.includes('heading') || componentName.includes('title')) {
      audit.suggestions.push({
        type: 'heading-structure',
        suggestions: [
          'Use semantic heading tags (h1-h6)',
          'Maintain logical heading hierarchy',
          'Ensure only one h1 per page'
        ]
      });
    }

    return audit;
  }

  /**
   * Audit alt text for images
   * @param {Object} component - Design component
   * @param {string} code - Generated code
   * @returns {Promise<Object>} Alt text audit results
   */
  async auditAltText(component, code) {
    const audit = {
      violations: [],
      warnings: [],
      passed: [],
      autoFixes: []
    };

    const componentType = (component.type || '').toUpperCase();
    const componentName = (component.name || '').toLowerCase();

    // Check for images without alt text
    if (this.isImage(component)) {
      const hasAltText = code && (
        code.includes('alt=') ||
        code.includes('aria-label=')
      );

      if (!hasAltText) {
        audit.violations.push({
          rule: 'img-alt-required',
          severity: 'error',
          message: 'Image missing alt text',
          wcag: '1.1.1',
          element: component.name
        });

        // Generate auto-fix
        const altText = this.generateAltText(component);
        audit.autoFixes.push({
          type: 'add-alt-text',
          attribute: 'alt',
          value: altText,
          code: `alt="${altText}"`
        });

        this.statistics.altTextGenerated++;
      } else {
        audit.passed.push('Image has alt text');
      }

      // Check for empty alt on decorative images
      if (componentName.includes('decorative') || componentName.includes('icon')) {
        audit.suggestions.push({
          type: 'decorative-image',
          suggestions: [
            'Consider using alt="" for purely decorative images',
            'Use aria-hidden="true" if image is purely visual'
          ]
        });
      }
    }

    return audit;
  }

  /**
   * Audit keyboard navigation
   * @param {Object} component - Design component
   * @param {string} code - Generated code
   * @returns {Promise<Object>} Keyboard navigation audit results
   */
  async auditKeyboardNavigation(component, code) {
    const audit = {
      violations: [],
      warnings: [],
      passed: [],
      suggestions: []
    };

    if (this.isInteractive(component)) {
      // Check for tabIndex
      const hasTabIndex = code && (
        code.includes('tabIndex') ||
        code.includes('tabindex') ||
        code.includes('<button') ||
        code.includes('<a href')
      );

      if (!hasTabIndex) {
        audit.warnings.push({
          rule: 'keyboard-accessible',
          severity: 'warning',
          message: 'Interactive element may not be keyboard accessible',
          wcag: '2.1.1',
          element: component.name
        });

        audit.suggestions.push({
          type: 'keyboard-navigation',
          suggestions: [
            'Ensure element is keyboard accessible with Tab key',
            'Add tabIndex="0" for custom interactive elements',
            'Implement Enter/Space key handlers for buttons',
            'Add Escape key handler for modals/dialogs'
          ]
        });
      } else {
        audit.passed.push('Element is keyboard accessible');
      }

      // Check for keyboard event handlers
      if (code && code.includes('onClick') && !code.includes('onKeyDown') && !code.includes('onKeyPress')) {
        audit.warnings.push({
          rule: 'keyboard-event-handlers',
          severity: 'warning',
          message: 'onClick without corresponding keyboard handler',
          wcag: '2.1.1',
          element: component.name
        });
      }
    }

    return audit;
  }

  /**
   * Audit color contrast
   * @param {Object} component - Design component
   * @returns {Promise<Object>} Color contrast audit results
   */
  async auditColorContrast(component) {
    const audit = {
      violations: [],
      warnings: [],
      passed: [],
      suggestions: []
    };

    if (!component.properties) return audit;

    const { backgroundColor, color, fontSize } = component.properties;

    if (backgroundColor && color) {
      const contrast = this.calculateContrastRatio(color, backgroundColor);
      const isLargeText = fontSize && fontSize >= 18;
      const required = isLargeText
        ? this.contrastRatios[this.wcagLevel].large
        : this.contrastRatios[this.wcagLevel].normal;

      if (contrast < required) {
        audit.violations.push({
          rule: 'color-contrast',
          severity: 'error',
          message: `Insufficient color contrast: ${contrast.toFixed(2)}:1 (requires ${required}:1)`,
          wcag: '1.4.3',
          element: component.name,
          details: {
            foreground: color,
            background: backgroundColor,
            contrast: contrast.toFixed(2),
            required
          }
        });

        audit.suggestions.push({
          type: 'contrast-improvement',
          suggestions: [
            `Darken foreground color to improve contrast`,
            `Lighten background color`,
            `Increase to ${required}:1 ratio for WCAG ${this.wcagLevel}`
          ]
        });
      } else {
        audit.passed.push(`Color contrast meets WCAG ${this.wcagLevel}: ${contrast.toFixed(2)}:1`);
      }
    }

    return audit;
  }

  /**
   * Audit focus management
   * @param {Object} component - Design component
   * @param {string} code - Generated code
   * @returns {Promise<Object>} Focus management audit results
   */
  async auditFocusManagement(component, code) {
    const audit = {
      violations: [],
      warnings: [],
      passed: [],
      suggestions: []
    };

    if (this.isInteractive(component)) {
      // Check for visible focus indicator
      const hasFocusStyle = code && (
        code.includes(':focus') ||
        code.includes('focus:') ||
        code.includes('onFocus')
      );

      if (!hasFocusStyle) {
        audit.warnings.push({
          rule: 'focus-visible',
          severity: 'warning',
          message: 'No visible focus indicator defined',
          wcag: '2.4.7',
          element: component.name
        });

        audit.suggestions.push({
          type: 'focus-management',
          suggestions: [
            'Add visible focus indicator (outline or border)',
            'Use :focus-visible for keyboard-only focus styles',
            'Ensure focus indicator has sufficient contrast',
            'Do not remove default focus styles without replacement'
          ]
        });
      } else {
        audit.passed.push('Element has focus indicator');
      }
    }

    // Check for modals/dialogs
    const componentName = (component.name || '').toLowerCase();
    if (componentName.includes('modal') || componentName.includes('dialog')) {
      audit.suggestions.push({
        type: 'modal-focus',
        suggestions: [
          'Trap focus within modal when open',
          'Return focus to trigger element on close',
          'Set initial focus to first focusable element',
          'Handle Escape key to close modal'
        ]
      });
    }

    return audit;
  }

  // Helper methods

  isInteractive(component) {
    const type = (component.type || '').toUpperCase();
    const name = (component.name || '').toLowerCase();

    const interactiveTypes = ['BUTTON', 'INPUT', 'SELECT', 'LINK'];
    const interactiveNames = ['button', 'link', 'input', 'select', 'checkbox', 'radio', 'toggle', 'switch'];

    return interactiveTypes.includes(type) ||
           interactiveNames.some(keyword => name.includes(keyword));
  }

  isImage(component) {
    const type = (component.type || '').toUpperCase();
    const name = (component.name || '').toLowerCase();

    return type === 'IMAGE' ||
           type === 'RECTANGLE' && (name.includes('image') || name.includes('img') || name.includes('photo')) ||
           name.includes('icon') ||
           name.includes('logo');
  }

  generateARIALabel(component) {
    const name = component.name || 'Component';

    // Clean up name for aria-label
    let label = name
      .replace(/[-_]/g, ' ')
      .replace(/([A-Z])/g, ' $1')
      .trim()
      .toLowerCase();

    // Capitalize first letter
    label = label.charAt(0).toUpperCase() + label.slice(1);

    // Add context based on component type
    const type = (component.type || '').toLowerCase();
    if (type === 'button') {
      if (!label.includes('button')) {
        label += ' button';
      }
    } else if (type === 'input') {
      if (!label.includes('field') && !label.includes('input')) {
        label += ' field';
      }
    }

    return label;
  }

  generateAltText(component) {
    const name = component.name || 'Image';

    // Clean up name for alt text
    let alt = name
      .replace(/[-_]/g, ' ')
      .replace(/([A-Z])/g, ' $1')
      .replace(/\b(img|image|photo|picture|icon)\b/gi, '')
      .trim();

    // Capitalize first letter
    alt = alt.charAt(0).toUpperCase() + alt.slice(1);

    return alt || 'Decorative image';
  }

  calculateContrastRatio(foreground, background) {
    // Convert hex to RGB
    const fgRGB = this.hexToRGB(foreground);
    const bgRGB = this.hexToRGB(background);

    if (!fgRGB || !bgRGB) return 21; // Assume passing if we can't calculate

    // Calculate relative luminance
    const fgLum = this.relativeLuminance(fgRGB);
    const bgLum = this.relativeLuminance(bgRGB);

    // Calculate contrast ratio
    const lighter = Math.max(fgLum, bgLum);
    const darker = Math.min(fgLum, bgLum);

    return (lighter + 0.05) / (darker + 0.05);
  }

  hexToRGB(hex) {
    // Remove # if present
    hex = hex.replace('#', '');

    if (hex.length === 3) {
      hex = hex.split('').map(h => h + h).join('');
    }

    if (hex.length !== 6) return null;

    const r = parseInt(hex.substring(0, 2), 16);
    const g = parseInt(hex.substring(2, 4), 16);
    const b = parseInt(hex.substring(4, 6), 16);

    return { r, g, b };
  }

  relativeLuminance(rgb) {
    // Convert RGB to relative luminance (WCAG formula)
    const rsRGB = rgb.r / 255;
    const gsRGB = rgb.g / 255;
    const bsRGB = rgb.b / 255;

    const r = rsRGB <= 0.03928 ? rsRGB / 12.92 : Math.pow((rsRGB + 0.055) / 1.055, 2.4);
    const g = gsRGB <= 0.03928 ? gsRGB / 12.92 : Math.pow((gsRGB + 0.055) / 1.055, 2.4);
    const b = bsRGB <= 0.03928 ? bsRGB / 12.92 : Math.pow((bsRGB + 0.055) / 1.055, 2.4);

    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }

  mergeAudit(mainAudit, subAudit) {
    mainAudit.violations.push(...subAudit.violations);
    mainAudit.warnings.push(...subAudit.warnings);
    mainAudit.passed.push(...subAudit.passed);
    if (subAudit.suggestions) {
      mainAudit.suggestions.push(...subAudit.suggestions);
    }
    if (subAudit.autoFixes) {
      mainAudit.autoFixes.push(...subAudit.autoFixes);
    }
  }

  calculateScore(audit) {
    const violations = audit.violations.length;
    const warnings = audit.warnings.length;

    // Start with 100, deduct points for issues
    let score = 100;
    score -= violations * 10; // -10 points per violation
    score -= warnings * 5; // -5 points per warning

    return Math.max(score, 0);
  }

  /**
   * Generate accessibility report
   * @param {Object} audit - Audit results
   * @returns {string} Formatted report
   */
  generateReport(audit) {
    let report = `\n=== ACCESSIBILITY AUDIT REPORT ===\n`;
    report += `Component: ${audit.component}\n`;
    report += `WCAG Level: ${audit.wcagLevel}\n`;
    report += `Score: ${audit.score}/100\n\n`;

    if (audit.violations.length > 0) {
      report += `VIOLATIONS (${audit.violations.length}):\n`;
      audit.violations.forEach((v, i) => {
        report += `  ${i + 1}. [${v.severity.toUpperCase()}] ${v.message} (WCAG ${v.wcag})\n`;
      });
      report += `\n`;
    }

    if (audit.warnings.length > 0) {
      report += `WARNINGS (${audit.warnings.length}):\n`;
      audit.warnings.forEach((w, i) => {
        report += `  ${i + 1}. ${w.message} (WCAG ${w.wcag})\n`;
      });
      report += `\n`;
    }

    if (audit.passed.length > 0) {
      report += `PASSED (${audit.passed.length}):\n`;
      audit.passed.forEach((p, i) => {
        report += `  ✓ ${p}\n`;
      });
      report += `\n`;
    }

    if (audit.autoFixes && audit.autoFixes.length > 0) {
      report += `AUTO-FIXES AVAILABLE (${audit.autoFixes.length}):\n`;
      audit.autoFixes.forEach((fix, i) => {
        report += `  ${i + 1}. ${fix.type}: ${fix.code}\n`;
      });
    }

    return report;
  }

  /**
   * Get statistics
   * @returns {Object} Automation statistics
   */
  getStatistics() {
    return { ...this.statistics };
  }
}

// Singleton instance
let instance = null;

function getAccessibilityAutomation(options) {
  if (!instance) {
    instance = new AccessibilityAutomation(options);
  }
  return instance;
}

module.exports = { AccessibilityAutomation, getAccessibilityAutomation };
