/**
 * Animation Export System
 * Extract animations from Figma and convert to CSS/JS
 * Sprint 60-62: Animation System + Visual Testing + Component Marketplace
 */

const EventEmitter = require('events');

class AnimationExport extends EventEmitter {
  constructor(options = {}) {
    super();
    this.format = options.format || 'css'; // css, js, gsap, framer-motion
    this.optimize = options.optimize !== false;

    this.statistics = {
      exported: 0,
      formats: new Map(),
      totalDuration: 0
    };

    this.easingFunctions = {
      linear: 'linear',
      easeIn: 'cubic-bezier(0.4, 0, 1, 1)',
      easeOut: 'cubic-bezier(0, 0, 0.2, 1)',
      easeInOut: 'cubic-bezier(0.4, 0, 0.2, 1)',
      spring: 'cubic-bezier(0.68, -0.55, 0.265, 1.55)'
    };
  }

  /**
   * Extract and export animations
   * @param {Object} component - Design component
   * @param {Object} animations - Animation data from Figma
   * @param {string} format - Export format
   * @returns {Object} Exported animation code
   */
  exportAnimations(component, animations, format = this.format) {
    this.statistics.exported++;
    this.statistics.formats.set(format, (this.statistics.formats.get(format) || 0) + 1);

    const exported = {
      component: component.id,
      format,
      animations: [],
      code: ''
    };

    if (!animations || animations.length === 0) {
      // Generate default animations based on component type
      animations = this.generateDefaultAnimations(component);
    }

    animations.forEach(anim => {
      const converted = this.convertAnimation(anim, format);
      exported.animations.push(converted);
      this.statistics.totalDuration += anim.duration || 0;
    });

    exported.code = this.generateCode(exported.animations, format, component);

    this.emit('animation:exported', exported);
    return exported;
  }

  /**
   * Generate default animations for component
   * @param {Object} component - Design component
   * @returns {Array} Default animations
   */
  generateDefaultAnimations(component) {
    const defaults = [];

    // Fade in animation
    defaults.push({
      name: 'fadeIn',
      type: 'opacity',
      from: 0,
      to: 1,
      duration: 300,
      easing: 'easeOut'
    });

    // For buttons - hover effect
    if (component.type === 'BUTTON' || component.name?.toLowerCase().includes('button')) {
      defaults.push({
        name: 'hoverScale',
        type: 'scale',
        from: 1,
        to: 1.05,
        duration: 200,
        easing: 'easeInOut',
        trigger: 'hover'
      });
    }

    // For modals - slide in
    if (component.name?.toLowerCase().includes('modal')) {
      defaults.push({
        name: 'slideIn',
        type: 'transform',
        from: 'translateY(100%)',
        to: 'translateY(0)',
        duration: 400,
        easing: 'spring'
      });
    }

    return defaults;
  }

  /**
   * Convert animation to target format
   * @param {Object} animation - Animation data
   * @param {string} format - Target format
   * @returns {Object} Converted animation
   */
  convertAnimation(animation, format) {
    switch (format) {
      case 'css':
        return this.convertToCSS(animation);
      case 'js':
        return this.convertToJS(animation);
      case 'gsap':
        return this.convertToGSAP(animation);
      case 'framer-motion':
        return this.convertToFramerMotion(animation);
      default:
        return this.convertToCSS(animation);
    }
  }

  convertToCSS(animation) {
    const { name, type, from, to, duration, easing, trigger } = animation;
    const easingFunc = this.easingFunctions[easing] || this.easingFunctions.easeInOut;

    return {
      name,
      keyframes: `
@keyframes ${name} {
  from {
    ${type === 'opacity' ? `opacity: ${from};` : ''}
    ${type === 'transform' ? `transform: ${from};` : ''}
    ${type === 'scale' ? `transform: scale(${from});` : ''}
  }
  to {
    ${type === 'opacity' ? `opacity: ${to};` : ''}
    ${type === 'transform' ? `transform: ${to};` : ''}
    ${type === 'scale' ? `transform: scale(${to});` : ''}
  }
}`,
      className: `
.${name} {
  animation: ${name} ${duration}ms ${easingFunc};
}`,
      trigger: trigger || 'mount'
    };
  }

  convertToJS(animation) {
    const { name, type, from, to, duration, easing } = animation;

    return {
      name,
      code: `
function ${name}(element) {
  element.animate([
    { ${type}: '${from}' },
    { ${type}: '${to}' }
  ], {
    duration: ${duration},
    easing: '${this.easingFunctions[easing] || 'ease-in-out'}',
    fill: 'forwards'
  });
}`
    };
  }

  convertToGSAP(animation) {
    const { name, type, from, to, duration, easing } = animation;

    return {
      name,
      code: `
gsap.to(element, {
  ${type}: '${to}',
  duration: ${duration / 1000},
  ease: '${easing || 'power2.out'}'
});`
    };
  }

  convertToFramerMotion(animation) {
    const { name, type, from, to, duration, easing } = animation;

    return {
      name,
      code: `
const ${name}Variant = {
  initial: { ${type}: ${from} },
  animate: { ${type}: ${to} },
  transition: {
    duration: ${duration / 1000},
    ease: '${easing || 'easeInOut'}'
  }
};`
    };
  }

  /**
   * Generate animation code
   * @param {Array} animations - Converted animations
   * @param {string} format - Export format
   * @param {Object} component - Component data
   * @returns {string} Generated code
   */
  generateCode(animations, format, component) {
    switch (format) {
      case 'css':
        return this.generateCSSCode(animations);
      case 'js':
        return this.generateJSCode(animations, component);
      case 'gsap':
        return this.generateGSAPCode(animations);
      case 'framer-motion':
        return this.generateFramerMotionCode(animations, component);
      default:
        return this.generateCSSCode(animations);
    }
  }

  generateCSSCode(animations) {
    let code = '/* Generated Animations */\n\n';

    animations.forEach(anim => {
      code += anim.keyframes + '\n\n';
      code += anim.className + '\n\n';
    });

    return code;
  }

  generateJSCode(animations, component) {
    let code = `// Animations for ${component.name}\n\n`;

    animations.forEach(anim => {
      code += anim.code + '\n\n';
    });

    return code;
  }

  generateGSAPCode(animations) {
    let code = '// GSAP Animations\nimport { gsap } from "gsap";\n\n';

    animations.forEach(anim => {
      code += anim.code + '\n\n';
    });

    return code;
  }

  generateFramerMotionCode(animations, component) {
    let code = `// Framer Motion Animations\nimport { motion } from "framer-motion";\n\n`;

    animations.forEach(anim => {
      code += anim.code + '\n\n';
    });

    code += `\nexport default function ${component.name}() {
  return (
    <motion.div
      variants={${animations[0]?.name}Variant}
      initial="initial"
      animate="animate"
    >
      {/* Component content */}
    </motion.div>
  );
}`;

    return code;
  }

  /**
   * Get statistics
   * @returns {Object} Export statistics
   */
  getStatistics() {
    return {
      ...this.statistics,
      formats: Object.fromEntries(this.statistics.formats),
      averageDuration: this.statistics.exported > 0
        ? this.statistics.totalDuration / this.statistics.exported
        : 0
    };
  }
}

// Singleton instance
let instance = null;

function getAnimationExport(options) {
  if (!instance) {
    instance = new AnimationExport(options);
  }
  return instance;
}

module.exports = { AnimationExport, getAnimationExport };
