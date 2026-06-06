/**
 * Semantic Markup Enhancer for AI Recognition
 * Adds semantic HTML and ARIA attributes for better AI understanding
 */

class SemanticMarkupEnhancer {
  constructor() {
    this.semanticRoles = this.initializeSemanticRoles();
    this.ariaPatterns = this.initializeAriaPatterns();
    this.microdata = this.initializeMicrodata();
  }

  /**
   * Initialize semantic role mappings
   */
  initializeSemanticRoles() {
    return {
      // Navigation patterns
      navigation: {
        tag: 'nav',
        role: 'navigation',
        attributes: {
          'aria-label': 'Main navigation',
          'data-ai-purpose': 'primary-navigation',
          'data-ai-pattern': 'sidebar-nav'
        }
      },
      breadcrumb: {
        tag: 'nav',
        role: 'navigation',
        attributes: {
          'aria-label': 'Breadcrumb',
          'data-ai-purpose': 'breadcrumb-navigation',
          'data-ai-pattern': 'hierarchical-nav'
        }
      },

      // Content patterns
      main: {
        tag: 'main',
        role: 'main',
        attributes: {
          'aria-label': 'Main content',
          'data-ai-purpose': 'primary-content',
          'data-ai-pattern': 'content-area'
        }
      },
      article: {
        tag: 'article',
        role: 'article',
        attributes: {
          'data-ai-purpose': 'standalone-content',
          'data-ai-pattern': 'article-content'
        }
      },

      // Component patterns
      button: {
        tag: 'button',
        role: 'button',
        attributes: {
          'data-ai-component': 'button',
          'data-ai-interactive': 'true',
          'data-ai-action': 'click'
        }
      },
      input: {
        tag: 'input',
        attributes: {
          'data-ai-component': 'input',
          'data-ai-interactive': 'true',
          'data-ai-validation': 'required'
        }
      },
      card: {
        tag: 'article',
        role: 'region',
        attributes: {
          'data-ai-component': 'card',
          'data-ai-pattern': 'content-container',
          'data-ai-semantic': 'grouped-content'
        }
      },
      dialog: {
        tag: 'dialog',
        role: 'dialog',
        attributes: {
          'aria-modal': 'true',
          'data-ai-component': 'dialog',
          'data-ai-pattern': 'modal-overlay',
          'data-ai-focus': 'trapped'
        }
      }
    };
  }

  /**
   * Initialize ARIA patterns for complex components
   */
  initializeAriaPatterns() {
    return {
      accordion: {
        container: {
          role: 'region',
          'data-ai-pattern': 'accordion',
          'data-ai-expandable': 'true'
        },
        trigger: {
          role: 'button',
          'aria-expanded': 'false',
          'aria-controls': 'panel-id',
          'data-ai-trigger': 'expand-collapse'
        },
        panel: {
          role: 'region',
          'aria-hidden': 'true',
          'data-ai-content': 'collapsible'
        }
      },

      tabs: {
        list: {
          role: 'tablist',
          'data-ai-pattern': 'tabs',
          'data-ai-navigation': 'horizontal'
        },
        tab: {
          role: 'tab',
          'aria-selected': 'false',
          'aria-controls': 'tabpanel-id',
          'data-ai-trigger': 'tab-switch'
        },
        panel: {
          role: 'tabpanel',
          'aria-hidden': 'true',
          'data-ai-content': 'tab-content'
        }
      },

      combobox: {
        input: {
          role: 'combobox',
          'aria-expanded': 'false',
          'aria-autocomplete': 'list',
          'aria-controls': 'listbox-id',
          'data-ai-component': 'combobox',
          'data-ai-search': 'filterable'
        },
        listbox: {
          role: 'listbox',
          'data-ai-dropdown': 'true',
          'data-ai-selectable': 'single'
        },
        option: {
          role: 'option',
          'aria-selected': 'false',
          'data-ai-value': 'option-value'
        }
      }
    };
  }

  /**
   * Initialize microdata for structured data
   */
  initializeMicrodata() {
    return {
      designSystem: {
        itemscope: true,
        itemtype: 'https://schema.org/SoftwareApplication',
        properties: {
          name: 'BUMBA CLI 1.0',
          applicationCategory: 'DesignTool',
          operatingSystem: 'Web',
          offers: {
            itemtype: 'https://schema.org/Offer',
            price: '0',
            priceCurrency: 'USD'
          }
        }
      },

      component: {
        itemscope: true,
        itemtype: 'https://schema.org/WebComponent',
        properties: {
          name: 'component-name',
          description: 'component-description',
          version: '1.0.0',
          documentation: 'component-docs-url'
        }
      },

      token: {
        itemscope: true,
        itemtype: 'https://schema.org/Property',
        properties: {
          name: 'token-name',
          value: 'token-value',
          category: 'token-category'
        }
      }
    };
  }

  /**
   * Enhance HTML with semantic markup
   */
  enhanceHTML(html, context = {}) {
    let enhanced = html;

    // Add semantic HTML5 tags
    enhanced = this.addSemanticTags(enhanced, context);

    // Add ARIA attributes
    enhanced = this.addAriaAttributes(enhanced, context);

    // Add AI-specific data attributes
    enhanced = this.addAIDataAttributes(enhanced, context);

    // Add microdata
    enhanced = this.addMicrodata(enhanced, context);

    return enhanced;
  }

  /**
   * Add semantic HTML5 tags
   */
  addSemanticTags(html, context) {
    // Replace generic divs with semantic tags
    const replacements = [
      { from: /<div class="sidebar">/g, to: '<nav class="sidebar" role="navigation" aria-label="Main navigation">' },
      { from: /<div class="content">/g, to: '<main class="content" role="main" aria-label="Main content">' },
      { from: /<div class="card">/g, to: '<article class="card" role="region" data-ai-component="card">' },
      { from: /<div class="header">/g, to: '<header class="header" role="banner">' },
      { from: /<div class="footer">/g, to: '<footer class="footer" role="contentinfo">' }
    ];

    let result = html;
    for (const replacement of replacements) {
      result = result.replace(replacement.from, replacement.to);
    }

    return result;
  }

  /**
   * Add ARIA attributes for accessibility and AI understanding
   */
  addAriaAttributes(html, context) {
    const patterns = [
      // Buttons
      {
        pattern: /<button([^>]*)>/g,
        enhance: (match, attrs) => {
          if (!attrs.includes('aria-label')) {
            return `<button${attrs} aria-label="Interactive button" data-ai-interactive="true">`;
          }
          return match;
        }
      },
      // Inputs
      {
        pattern: /<input([^>]*)>/g,
        enhance: (match, attrs) => {
          if (!attrs.includes('aria-label') && !attrs.includes('aria-labelledby')) {
            return `<input${attrs} aria-label="Input field" data-ai-input="true">`;
          }
          return match;
        }
      },
      // Links
      {
        pattern: /<a([^>]*)href="([^"]*)"([^>]*)>/g,
        enhance: (match, before, href, after) => {
          const isExternal = href.startsWith('http');
          if (isExternal) {
            return `<a${before}href="${href}"${after} aria-label="External link" data-ai-link="external">`;
          }
          return `<a${before}href="${href}"${after} data-ai-link="internal">`;
        }
      }
    ];

    let result = html;
    for (const pattern of patterns) {
      result = result.replace(pattern.pattern, pattern.enhance);
    }

    return result;
  }

  /**
   * Add AI-specific data attributes
   */
  addAIDataAttributes(html, context) {
    const componentType = context.componentType || 'generic';
    const patternType = context.patternType || 'standard';

    // Add data attributes for AI recognition
    const aiAttributes = {
      'data-ai-version': '1.0.0',
      'data-ai-framework': 'shadcn-ui',
      'data-ai-component-type': componentType,
      'data-ai-pattern': patternType,
      'data-ai-semantic': 'enhanced',
      'data-ai-context': JSON.stringify({
        timestamp: new Date().toISOString(),
        generator: 'BUMBA CLI 1.0',
        purpose: context.purpose || 'design-system'
      })
    };

    // Insert at the body tag
    const bodyPattern = /<body([^>]*)>/;
    const aiAttrsString = Object.entries(aiAttributes)
      .map(([key, value]) => `${key}="${value}"`)
      .join(' ');

    return html.replace(bodyPattern, `<body$1 ${aiAttrsString}>`);
  }

  /**
   * Add microdata for structured data
   */
  addMicrodata(html, context) {
    if (context.type === 'component') {
      const componentMicrodata = `
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "WebComponent",
          "name": "${context.componentName || 'Component'}",
          "description": "${context.description || 'UI Component'}",
          "version": "1.0.0",
          "author": {
            "@type": "Organization",
            "name": "BUMBA CLI"
          }
        }
        </script>`;

      // Insert before closing head tag
      return html.replace('</head>', `${componentMicrodata}\n</head>`);
    }

    return html;
  }

  /**
   * Generate semantic component wrapper
   */
  generateSemanticWrapper(component, props = {}) {
    const semanticRole = this.semanticRoles[component] || {};
    const tag = semanticRole.tag || 'div';
    const attributes = {
      ...semanticRole.attributes,
      ...props,
      'data-ai-generated': 'true',
      'data-ai-timestamp': new Date().toISOString()
    };

    const attrString = Object.entries(attributes)
      .map(([key, value]) => `${key}="${value}"`)
      .join(' ');

    return {
      open: `<${tag} ${attrString}>`,
      close: `</${tag}>`,
      attributes
    };
  }

  /**
   * Extract semantic information from HTML
   */
  extractSemanticInfo(html) {
    const info = {
      components: [],
      patterns: [],
      tokens: [],
      aria: [],
      microdata: []
    };

    // Extract components
    const componentPattern = /data-ai-component="([^"]*)"/g;
    let match;
    while ((match = componentPattern.exec(html)) !== null) {
      info.components.push(match[1]);
    }

    // Extract patterns
    const patternPattern = /data-ai-pattern="([^"]*)"/g;
    while ((match = patternPattern.exec(html)) !== null) {
      info.patterns.push(match[1]);
    }

    // Extract ARIA roles
    const ariaPattern = /role="([^"]*)"/g;
    while ((match = ariaPattern.exec(html)) !== null) {
      info.aria.push(match[1]);
    }

    return info;
  }

  /**
   * Validate semantic markup
   */
  validateSemanticMarkup(html) {
    const issues = [];

    // Check for missing ARIA labels on interactive elements
    if (html.includes('<button') && !html.includes('aria-label')) {
      issues.push({
        type: 'warning',
        message: 'Button elements should have aria-label attributes'
      });
    }

    // Check for proper heading hierarchy
    const headings = html.match(/<h[1-6]/g) || [];
    const headingLevels = headings.map(h => parseInt(h.charAt(2)));
    for (let i = 1; i < headingLevels.length; i++) {
      if (headingLevels[i] - headingLevels[i-1] > 1) {
        issues.push({
          type: 'warning',
          message: 'Heading hierarchy should not skip levels'
        });
        break;
      }
    }

    // Check for main landmark
    if (!html.includes('role="main"') && !html.includes('<main')) {
      issues.push({
        type: 'warning',
        message: 'Page should have a main landmark'
      });
    }

    return {
      valid: issues.filter(i => i.type === 'error').length === 0,
      issues
    };
  }

  /**
   * Generate AI documentation from semantic markup
   */
  generateAIDocumentation(html) {
    const semanticInfo = this.extractSemanticInfo(html);

    return {
      summary: 'Semantic markup analysis',
      components: {
        count: semanticInfo.components.length,
        list: [...new Set(semanticInfo.components)]
      },
      patterns: {
        count: semanticInfo.patterns.length,
        list: [...new Set(semanticInfo.patterns)]
      },
      accessibility: {
        ariaRoles: [...new Set(semanticInfo.aria)],
        landmarksPresent: semanticInfo.aria.includes('main') || html.includes('<main'),
        navigationPresent: semanticInfo.aria.includes('navigation') || html.includes('<nav')
      },
      aiOptimization: {
        hasDataAttributes: html.includes('data-ai-'),
        hasMicrodata: html.includes('application/ld+json'),
        semanticHTML5: html.includes('<main') || html.includes('<article') || html.includes('<nav')
      }
    };
  }
}

module.exports = SemanticMarkupEnhancer;