/**
 * Pattern Library
 * Detects common UI patterns from Figma designs and provides templates
 * Sprint 53: Pattern Library Building
 */

const EventEmitter = require('events');

class PatternLibrary extends EventEmitter {
  constructor() {
    super();
    this.patterns = new Map();
    this.detectionRules = new Map();
    this.statistics = {
      patternsDetected: 0,
      patternsUsed: 0,
      detectionTime: 0
    };

    this.initializePatterns();
    this.initializeDetectionRules();
  }

  /**
   * Initialize common UI patterns
   */
  initializePatterns() {
    // Form patterns
    this.patterns.set('form', {
      type: 'form',
      name: 'Form Pattern',
      description: 'Input form with fields and submit button',
      components: ['input', 'label', 'button', 'form'],
      template: this.getFormTemplate(),
      variations: ['login', 'signup', 'contact', 'search']
    });

    // Navigation patterns
    this.patterns.set('navigation', {
      type: 'navigation',
      name: 'Navigation Pattern',
      description: 'Navigation menu with links',
      components: ['nav', 'link', 'menu', 'header'],
      template: this.getNavigationTemplate(),
      variations: ['horizontal', 'vertical', 'sidebar', 'tabs', 'breadcrumb']
    });

    // List patterns
    this.patterns.set('list', {
      type: 'list',
      name: 'List Pattern',
      description: 'List of items with optional actions',
      components: ['list', 'item', 'ul', 'li'],
      template: this.getListTemplate(),
      variations: ['simple', 'interactive', 'avatar', 'icon', 'action']
    });

    // Card patterns
    this.patterns.set('card', {
      type: 'card',
      name: 'Card Pattern',
      description: 'Content card with image, title, and description',
      components: ['card', 'image', 'heading', 'text', 'button'],
      template: this.getCardTemplate(),
      variations: ['product', 'profile', 'article', 'pricing', 'feature']
    });

    // Modal patterns
    this.patterns.set('modal', {
      type: 'modal',
      name: 'Modal Pattern',
      description: 'Dialog overlay with content and actions',
      components: ['modal', 'overlay', 'dialog', 'header', 'footer'],
      template: this.getModalTemplate(),
      variations: ['alert', 'confirm', 'form', 'lightbox']
    });

    // Button patterns
    this.patterns.set('button', {
      type: 'button',
      name: 'Button Pattern',
      description: 'Interactive button component',
      components: ['button'],
      template: this.getButtonTemplate(),
      variations: ['primary', 'secondary', 'outline', 'ghost', 'link']
    });
  }

  /**
   * Initialize pattern detection rules
   */
  initializeDetectionRules() {
    // Form detection: multiple inputs + submit button
    this.detectionRules.set('form', (component) => {
      const hasInputs = this.countChildrenOfType(component, 'INPUT') >= 2;
      const hasButton = this.hasChildOfType(component, 'BUTTON');
      const hasFormSemantics = component.name?.toLowerCase().includes('form') ||
                              component.type === 'FRAME' && hasInputs && hasButton;
      return hasFormSemantics && hasInputs && hasButton;
    });

    // Navigation detection: horizontal/vertical list of links
    this.detectionRules.set('navigation', (component) => {
      const hasLinks = this.countChildrenOfType(component, 'TEXT') >= 3;
      const isHorizontal = component.layoutMode === 'HORIZONTAL';
      const hasNavSemantics = component.name?.toLowerCase().includes('nav') ||
                             component.name?.toLowerCase().includes('menu') ||
                             component.name?.toLowerCase().includes('header');
      return hasNavSemantics || (hasLinks && isHorizontal);
    });

    // List detection: repeating items in vertical layout
    this.detectionRules.set('list', (component) => {
      const hasRepeatingChildren = this.hasRepeatingPattern(component);
      const isVertical = component.layoutMode === 'VERTICAL';
      const hasListSemantics = component.name?.toLowerCase().includes('list');
      return hasListSemantics || (hasRepeatingChildren && isVertical);
    });

    // Card detection: image + text + optional button
    this.detectionRules.set('card', (component) => {
      const hasImage = this.hasChildOfType(component, 'RECTANGLE') ||
                      this.hasChildOfType(component, 'IMAGE');
      const hasText = this.countChildrenOfType(component, 'TEXT') >= 2;
      const hasCardSemantics = component.name?.toLowerCase().includes('card');
      return hasCardSemantics || (hasImage && hasText);
    });

    // Modal detection: overlay with centered content
    this.detectionRules.set('modal', (component) => {
      const hasOverlay = component.fills && component.fills.some(f => f.opacity < 1);
      const hasDialog = this.hasChildOfType(component, 'FRAME');
      const hasModalSemantics = component.name?.toLowerCase().includes('modal') ||
                               component.name?.toLowerCase().includes('dialog') ||
                               component.name?.toLowerCase().includes('popup');
      return hasModalSemantics || (hasOverlay && hasDialog);
    });

    // Button detection: interactive button component
    this.detectionRules.set('button', (component) => {
      const isButton = component.type === 'BUTTON' ||
                      component.name?.toLowerCase().includes('button') ||
                      component.name?.toLowerCase().includes('btn');
      const hasButtonSemantics = component.properties?.backgroundColor ||
                                component.properties?.borderRadius !== undefined;
      return isButton && hasButtonSemantics;
    });
  }

  /**
   * Detect patterns in design component
   * @param {Object} component - Design component to analyze
   * @returns {Array} Detected patterns
   */
  detectPatterns(component) {
    const startTime = Date.now();
    const detected = [];

    for (const [patternType, detectionRule] of this.detectionRules.entries()) {
      try {
        if (detectionRule(component)) {
          const pattern = this.patterns.get(patternType);
          detected.push({
            type: patternType,
            pattern,
            component,
            confidence: this.calculateConfidence(component, patternType)
          });
        }
      } catch (error) {
        console.warn(`Pattern detection failed for ${patternType}:`, error.message);
      }
    }

    this.statistics.patternsDetected += detected.length;
    this.statistics.detectionTime += Date.now() - startTime;

    this.emit('patterns:detected', { component, patterns: detected });

    return detected;
  }

  /**
   * Get pattern template by type
   * @param {string} type - Pattern type
   * @param {string} variation - Pattern variation
   * @returns {Object} Pattern template
   */
  getPattern(type, variation = 'default') {
    const pattern = this.patterns.get(type);
    if (!pattern) {
      throw new Error(`Pattern type '${type}' not found`);
    }

    return {
      ...pattern,
      variation,
      timestamp: new Date().toISOString()
    };
  }

  /**
   * Get all patterns
   * @returns {Array} All available patterns
   */
  getAllPatterns() {
    return Array.from(this.patterns.values());
  }

  /**
   * Calculate confidence score for pattern detection
   * @param {Object} component - Component
   * @param {string} patternType - Pattern type
   * @returns {number} Confidence score (0-1)
   */
  calculateConfidence(component, patternType) {
    let score = 0.5; // Base confidence

    // Name match increases confidence
    if (component.name?.toLowerCase().includes(patternType)) {
      score += 0.3;
    }

    // Specific pattern checks
    switch (patternType) {
      case 'form':
        if (this.countChildrenOfType(component, 'INPUT') >= 3) score += 0.1;
        if (this.hasChildOfType(component, 'LABEL')) score += 0.1;
        break;
      case 'navigation':
        if (component.layoutMode === 'HORIZONTAL') score += 0.2;
        break;
      case 'card':
        if (component.cornerRadius > 0) score += 0.1;
        if (component.effects?.length > 0) score += 0.1;
        break;
    }

    return Math.min(score, 1.0);
  }

  // Helper methods for pattern detection

  countChildrenOfType(component, type) {
    if (!component.children) return 0;
    return component.children.filter(child => child.type === type).length;
  }

  hasChildOfType(component, type) {
    if (!component.children) return false;
    return component.children.some(child => child.type === type);
  }

  hasRepeatingPattern(component) {
    if (!component.children || component.children.length < 3) return false;

    const firstChild = component.children[0];
    const similarChildren = component.children.filter(child =>
      child.type === firstChild.type &&
      Math.abs(child.width - firstChild.width) < 10 &&
      Math.abs(child.height - firstChild.height) < 10
    );

    return similarChildren.length >= 3;
  }

  // Pattern Templates

  getFormTemplate() {
    return {
      react: `
export default function Form() {
  return (
    <form>
      <div className="form-group">
        <label htmlFor="input1">Label</label>
        <input type="text" id="input1" />
      </div>
      <button type="submit">Submit</button>
    </form>
  );
}`,
      vue: `
<template>
  <form @submit.prevent="handleSubmit">
    <div class="form-group">
      <label for="input1">Label</label>
      <input type="text" id="input1" v-model="formData.input1" />
    </div>
    <button type="submit">Submit</button>
  </form>
</template>`,
      html: `
<form>
  <div class="form-group">
    <label for="input1">Label</label>
    <input type="text" id="input1" />
  </div>
  <button type="submit">Submit</button>
</form>`
    };
  }

  getNavigationTemplate() {
    return {
      react: `
export default function Navigation() {
  return (
    <nav>
      <ul>
        <li><a href="#home">Home</a></li>
        <li><a href="#about">About</a></li>
        <li><a href="#contact">Contact</a></li>
      </ul>
    </nav>
  );
}`,
      vue: `
<template>
  <nav>
    <ul>
      <li><router-link to="/">Home</router-link></li>
      <li><router-link to="/about">About</router-link></li>
      <li><router-link to="/contact">Contact</router-link></li>
    </ul>
  </nav>
</template>`,
      html: `
<nav>
  <ul>
    <li><a href="#home">Home</a></li>
    <li><a href="#about">About</a></li>
    <li><a href="#contact">Contact</a></li>
  </ul>
</nav>`
    };
  }

  getListTemplate() {
    return {
      react: `
export default function List({ items }) {
  return (
    <ul>
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  );
}`,
      vue: `
<template>
  <ul>
    <li v-for="(item, index) in items" :key="index">
      {{ item }}
    </li>
  </ul>
</template>`,
      html: `
<ul>
  <li>Item 1</li>
  <li>Item 2</li>
  <li>Item 3</li>
</ul>`
    };
  }

  getCardTemplate() {
    return {
      react: `
export default function Card({ title, description, image }) {
  return (
    <div className="card">
      <img src={image} alt={title} />
      <h3>{title}</h3>
      <p>{description}</p>
      <button>Learn More</button>
    </div>
  );
}`,
      vue: `
<template>
  <div class="card">
    <img :src="image" :alt="title" />
    <h3>{{ title }}</h3>
    <p>{{ description }}</p>
    <button>Learn More</button>
  </div>
</template>`,
      html: `
<div class="card">
  <img src="image.jpg" alt="Title" />
  <h3>Title</h3>
  <p>Description</p>
  <button>Learn More</button>
</div>`
    };
  }

  getModalTemplate() {
    return {
      react: `
export default function Modal({ isOpen, onClose, children }) {
  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>×</button>
        {children}
      </div>
    </div>
  );
}`,
      vue: `
<template>
  <div v-if="isOpen" class="modal-overlay" @click="$emit('close')">
    <div class="modal-content" @click.stop>
      <button class="modal-close" @click="$emit('close')">×</button>
      <slot />
    </div>
  </div>
</template>`,
      html: `
<div class="modal-overlay">
  <div class="modal-content">
    <button class="modal-close">×</button>
    <div class="modal-body">
      <!-- Content -->
    </div>
  </div>
</div>`
    };
  }

  getButtonTemplate() {
    return {
      react: `
export default function Button({ children, variant = 'primary', onClick }) {
  return (
    <button className={\`button button-\${variant}\`} onClick={onClick}>
      {children}
    </button>
  );
}`,
      vue: `
<template>
  <button :class="[\`button\`, \`button-\${variant}\`]" @click="$emit('click')">
    <slot />
  </button>
</template>

<script>
export default {
  props: {
    variant: {
      type: String,
      default: 'primary'
    }
  }
}
</script>`,
      html: `
<button class="button button-primary">
  Click me
</button>`
    };
  }

  /**
   * Get statistics
   * @returns {Object} Pattern library statistics
   */
  getStatistics() {
    return {
      ...this.statistics,
      availablePatterns: this.patterns.size,
      averageDetectionTime: this.statistics.patternsDetected > 0
        ? this.statistics.detectionTime / this.statistics.patternsDetected
        : 0
    };
  }
}

// Singleton instance
let instance = null;

function getPatternLibrary() {
  if (!instance) {
    instance = new PatternLibrary();
  }
  return instance;
}

module.exports = { PatternLibrary, getPatternLibrary };
