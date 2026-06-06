/**
 * Responsive Design System
 * Breakpoints, media queries, fluid typography, responsive layouts
 * Sprint 57-59: Responsive Design System + Animation + Theme Customization
 */

const EventEmitter = require('events');

class ResponsiveDesignSystem extends EventEmitter {
  constructor(options = {}) {
    super();

    this.breakpoints = options.breakpoints || {
      xs: 0,
      sm: 640,
      md: 768,
      lg: 1024,
      xl: 1280,
      '2xl': 1536
    };

    this.containerMaxWidths = {
      sm: '640px',
      md: '768px',
      lg: '1024px',
      xl: '1280px',
      '2xl': '1536px'
    };

    this.fluidTypeScale = {
      base: { min: 16, max: 18 },
      sm: { min: 14, max: 16 },
      lg: { min: 18, max: 20 },
      xl: { min: 20, max: 24 },
      '2xl': { min: 24, max: 30 },
      '3xl': { min: 30, max: 36 }
    };

    this.gridSystem = {
      columns: 12,
      gutter: '1rem',
      breakpoints: this.breakpoints
    };

    this.statistics = {
      componentsProcessed: 0,
      breakpointsGenerated: 0,
      mediaQueriesCreated: 0
    };
  }

  /**
   * Generate responsive code for component
   * @param {Object} component - Design component
   * @param {string} framework - Target framework
   * @returns {Object} Responsive code and styles
   */
  generateResponsiveCode(component, framework = 'react') {
    this.statistics.componentsProcessed++;

    const responsive = {
      component,
      framework,
      breakpoints: this.generateBreakpoints(component),
      mediaQueries: this.generateMediaQueries(component),
      fluidTypography: this.generateFluidTypography(component),
      layout: this.generateResponsiveLayout(component),
      containerQueries: this.generateContainerQueries(component),
      aspectRatios: this.calculateAspectRatios(component)
    };

    // Generate framework-specific code
    responsive.code = this.generateFrameworkCode(responsive, framework);
    responsive.styles = this.generateStyles(responsive);

    this.statistics.breakpointsGenerated += responsive.breakpoints.length;
    this.statistics.mediaQueriesCreated += responsive.mediaQueries.length;

    this.emit('responsive:generated', responsive);

    return responsive;
  }

  /**
   * Generate breakpoints for component
   * @param {Object} component - Design component
   * @returns {Array} Breakpoint configurations
   */
  generateBreakpoints(component) {
    const breakpoints = [];

    for (const [name, width] of Object.entries(this.breakpoints)) {
      breakpoints.push({
        name,
        width,
        minWidth: `${width}px`,
        styles: this.getBreakpointStyles(component, name, width)
      });
    }

    return breakpoints;
  }

  getBreakpointStyles(component, breakpoint, width) {
    const styles = {};

    // Adjust padding/margins
    if (component.properties) {
      const { padding, margin } = component.properties;

      if (padding) {
        styles.padding = this.scaleSpacing(padding, breakpoint);
      }

      if (margin) {
        styles.margin = this.scaleSpacing(margin, breakpoint);
      }

      // Adjust font sizes
      if (component.properties.fontSize) {
        styles.fontSize = this.scaleTypography(component.properties.fontSize, breakpoint);
      }
    }

    // Layout adjustments
    if (component.children && component.children.length > 0) {
      styles.flexDirection = width < 768 ? 'column' : 'row';
      styles.gap = this.scaleSpacing('1rem', breakpoint);
    }

    return styles;
  }

  scaleSpacing(base, breakpoint) {
    const baseValue = parseFloat(base);
    const scales = {
      xs: 0.75,
      sm: 0.875,
      md: 1,
      lg: 1.125,
      xl: 1.25,
      '2xl': 1.5
    };

    const scale = scales[breakpoint] || 1;
    return `${baseValue * scale}rem`;
  }

  scaleTypography(base, breakpoint) {
    const baseValue = parseFloat(base);
    const scales = {
      xs: 0.875,
      sm: 0.9375,
      md: 1,
      lg: 1.0625,
      xl: 1.125,
      '2xl': 1.25
    };

    const scale = scales[breakpoint] || 1;
    return `${baseValue * scale}px`;
  }

  /**
   * Generate media queries
   * @param {Object} component - Design component
   * @returns {Array} Media query configurations
   */
  generateMediaQueries(component) {
    const queries = [];

    // Mobile-first approach
    for (const [name, width] of Object.entries(this.breakpoints)) {
      if (width === 0) continue; // Skip xs (base styles)

      const query = {
        breakpoint: name,
        query: `@media (min-width: ${width}px)`,
        styles: this.getBreakpointStyles(component, name, width)
      };

      queries.push(query);
    }

    // Add max-width queries for specific scenarios
    if (component.type === 'MODAL' || component.name?.toLowerCase().includes('modal')) {
      queries.push({
        breakpoint: 'mobile-modal',
        query: '@media (max-width: 767px)',
        styles: {
          width: '100%',
          height: '100%',
          borderRadius: 0
        }
      });
    }

    return queries;
  }

  /**
   * Generate fluid typography
   * @param {Object} component - Design component
   * @returns {Object} Fluid typography configuration
   */
  generateFluidTypography(component) {
    if (!component.properties || !component.properties.fontSize) {
      return null;
    }

    const baseFontSize = component.properties.fontSize;

    // Determine scale based on font size
    let scale = 'base';
    if (baseFontSize < 16) scale = 'sm';
    else if (baseFontSize >= 24) scale = '2xl';
    else if (baseFontSize >= 20) scale = 'xl';
    else if (baseFontSize >= 18) scale = 'lg';

    const { min, max } = this.fluidTypeScale[scale];

    return {
      scale,
      minSize: `${min}px`,
      maxSize: `${max}px`,
      minViewport: `${this.breakpoints.sm}px`,
      maxViewport: `${this.breakpoints.xl}px`,
      clamp: `clamp(${min}px, ${min}px + (${max} - ${min}) * ((100vw - ${this.breakpoints.sm}px) / (${this.breakpoints.xl} - ${this.breakpoints.sm})), ${max}px)`
    };
  }

  /**
   * Generate responsive layout
   * @param {Object} component - Design component
   * @returns {Object} Responsive layout configuration
   */
  generateResponsiveLayout(component) {
    const layout = {
      type: 'responsive',
      grid: null,
      flex: null,
      container: null
    };

    // Grid layout
    if (component.children && component.children.length > 2) {
      layout.grid = {
        columns: this.gridSystem.columns,
        breakpoints: {
          xs: 1,
          sm: 2,
          md: 3,
          lg: 4,
          xl: component.children.length <= 6 ? component.children.length : 6
        },
        gap: this.gridSystem.gutter
      };
    }

    // Flex layout
    layout.flex = {
      direction: {
        xs: 'column',
        sm: 'column',
        md: 'row',
        lg: 'row',
        xl: 'row'
      },
      wrap: true,
      gap: this.gridSystem.gutter
    };

    // Container
    layout.container = {
      maxWidth: this.containerMaxWidths,
      padding: {
        xs: '1rem',
        sm: '1.5rem',
        md: '2rem',
        lg: '2.5rem',
        xl: '3rem'
      },
      margin: '0 auto'
    };

    return layout;
  }

  /**
   * Generate container queries
   * @param {Object} component - Design component
   * @returns {Array} Container query configurations
   */
  generateContainerQueries(component) {
    const queries = [];

    // Container query for card-like components
    if (component.type === 'CARD' || component.name?.toLowerCase().includes('card')) {
      queries.push({
        container: 'card',
        query: '@container (min-width: 400px)',
        styles: {
          flexDirection: 'row',
          gap: '1.5rem'
        }
      });
    }

    return queries;
  }

  /**
   * Calculate aspect ratios
   * @param {Object} component - Design component
   * @returns {Object} Aspect ratio configuration
   */
  calculateAspectRatios(component) {
    if (!component.width || !component.height) {
      return null;
    }

    const gcd = this.findGCD(component.width, component.height);
    const aspectWidth = component.width / gcd;
    const aspectHeight = component.height / gcd;

    // Common aspect ratios
    const commonRatios = {
      '16/9': 16 / 9,
      '4/3': 4 / 3,
      '1/1': 1,
      '3/2': 3 / 2,
      '21/9': 21 / 9
    };

    const calculatedRatio = aspectWidth / aspectHeight;
    let closestRatio = `${aspectWidth}/${aspectHeight}`;

    // Find closest common ratio
    let minDiff = Infinity;
    for (const [ratio, value] of Object.entries(commonRatios)) {
      const diff = Math.abs(calculatedRatio - value);
      if (diff < minDiff && diff < 0.1) {
        minDiff = diff;
        closestRatio = ratio;
      }
    }

    return {
      calculated: `${aspectWidth}/${aspectHeight}`,
      suggested: closestRatio,
      decimal: calculatedRatio,
      css: `aspect-ratio: ${closestRatio}`
    };
  }

  findGCD(a, b) {
    return b === 0 ? a : this.findGCD(b, a % b);
  }

  /**
   * Generate framework-specific code
   * @param {Object} responsive - Responsive configuration
   * @param {string} framework - Target framework
   * @returns {string} Generated code
   */
  generateFrameworkCode(responsive, framework) {
    switch (framework) {
      case 'react':
        return this.generateReactCode(responsive);
      case 'vue':
        return this.generateVueCode(responsive);
      case 'tailwind':
        return this.generateTailwindCode(responsive);
      default:
        return this.generateCSSCode(responsive);
    }
  }

  generateReactCode(responsive) {
    const { component, fluidTypography } = responsive;
    const componentName = component.name || 'ResponsiveComponent';

    return `
export default function ${componentName}() {
  return (
    <div className="responsive-container">
      ${component.children ? component.children.map((child, i) => `
      <div key={${i}} className="responsive-item">
        {/* ${child.name} */}
      </div>`).join('') : '/* Content */'}
    </div>
  );
}`;
  }

  generateVueCode(responsive) {
    const { component } = responsive;

    return `
<template>
  <div class="responsive-container">
    ${component.children ? component.children.map((child, i) => `
    <div class="responsive-item">
      <!-- ${child.name} -->
    </div>`).join('') : '<!-- Content -->'}
  </div>
</template>

<style scoped>
${this.generateStyles(responsive)}
</style>`;
  }

  generateTailwindCode(responsive) {
    const { layout } = responsive;
    let classes = ['container', 'mx-auto', 'px-4'];

    if (layout.grid) {
      classes.push(
        'grid',
        `grid-cols-1`,
        `sm:grid-cols-${layout.grid.breakpoints.sm}`,
        `md:grid-cols-${layout.grid.breakpoints.md}`,
        `lg:grid-cols-${layout.grid.breakpoints.lg}`,
        'gap-4'
      );
    }

    return `<div className="${classes.join(' ')}">
  {/* Responsive content */}
</div>`;
  }

  generateCSSCode(responsive) {
    return this.generateStyles(responsive);
  }

  /**
   * Generate CSS styles
   * @param {Object} responsive - Responsive configuration
   * @returns {string} Generated CSS
   */
  generateStyles(responsive) {
    const { mediaQueries, fluidTypography, layout, aspectRatios } = responsive;
    let css = '.responsive-container {\n';

    // Base styles
    css += `  max-width: ${this.containerMaxWidths['2xl']};\n`;
    css += `  margin: 0 auto;\n`;
    css += `  padding: 1rem;\n`;

    // Layout
    if (layout.grid) {
      css += `  display: grid;\n`;
      css += `  grid-template-columns: repeat(${layout.grid.breakpoints.xs}, 1fr);\n`;
      css += `  gap: ${layout.grid.gap};\n`;
    }

    // Fluid typography
    if (fluidTypography) {
      css += `  font-size: ${fluidTypography.clamp};\n`;
    }

    // Aspect ratio
    if (aspectRatios) {
      css += `  ${aspectRatios.css};\n`;
    }

    css += '}\n\n';

    // Media queries
    mediaQueries.forEach(mq => {
      css += `${mq.query} {\n`;
      css += '  .responsive-container {\n';

      if (mq.styles.flexDirection) {
        css += `    flex-direction: ${mq.styles.flexDirection};\n`;
      }

      if (mq.styles.fontSize) {
        css += `    font-size: ${mq.styles.fontSize};\n`;
      }

      if (mq.styles.padding) {
        css += `    padding: ${mq.styles.padding};\n`;
      }

      if (layout.grid && layout.grid.breakpoints[mq.breakpoint]) {
        css += `    grid-template-columns: repeat(${layout.grid.breakpoints[mq.breakpoint]}, 1fr);\n`;
      }

      css += '  }\n';
      css += '}\n\n';
    });

    return css;
  }

  /**
   * Get statistics
   * @returns {Object} System statistics
   */
  getStatistics() {
    return { ...this.statistics };
  }
}

// Singleton instance
let instance = null;

function getResponsiveDesignSystem(options) {
  if (!instance) {
    instance = new ResponsiveDesignSystem(options);
  }
  return instance;
}

module.exports = { ResponsiveDesignSystem, getResponsiveDesignSystem };
