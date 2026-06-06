/**
 * Pattern Recognition Markers for AI Understanding
 * Provides pattern detection and marking for design system components
 */

class PatternRecognitionMarkers {
  constructor() {
    this.patterns = this.initializePatterns();
    this.markers = this.initializeMarkers();
    this.relationships = this.initializeRelationships();
  }

  /**
   * Initialize UI patterns for recognition
   */
  initializePatterns() {
    return {
      // Layout Patterns
      layout: {
        dashboard: {
          signature: ['sidebar', 'header', 'main-content', 'widgets'],
          markers: ['data-pattern="dashboard"', 'role="application"'],
          components: ['Sidebar', 'Header', 'Card', 'Chart'],
          description: 'Multi-panel dashboard layout with navigation and data widgets'
        },
        splitView: {
          signature: ['left-panel', 'right-panel', 'divider'],
          markers: ['data-pattern="split-view"', 'role="region"'],
          components: ['Resizable', 'ScrollArea'],
          description: 'Two-panel layout with resizable divider'
        },
        singleColumn: {
          signature: ['container', 'content', 'max-width'],
          markers: ['data-pattern="single-column"', 'role="main"'],
          components: ['Container', 'Article'],
          description: 'Centered single column for content'
        }
      },

      // Form Patterns
      forms: {
        login: {
          signature: ['email-input', 'password-input', 'submit-button', 'remember-checkbox'],
          markers: ['data-pattern="login-form"', 'data-ai-intent="authentication"'],
          components: ['Input', 'Button', 'Checkbox', 'Form'],
          validation: ['email', 'required'],
          description: 'User authentication form'
        },
        registration: {
          signature: ['email', 'password', 'confirm-password', 'terms', 'submit'],
          markers: ['data-pattern="registration-form"', 'data-ai-intent="user-signup"'],
          components: ['Input', 'Checkbox', 'Button', 'Form'],
          validation: ['email', 'password-strength', 'match', 'required'],
          description: 'New user registration form'
        },
        settings: {
          signature: ['sections', 'toggles', 'inputs', 'save-button'],
          markers: ['data-pattern="settings-form"', 'data-ai-intent="configuration"'],
          components: ['Tabs', 'Switch', 'Input', 'Select', 'Button'],
          description: 'Application settings configuration'
        }
      },

      // Data Display Patterns
      dataDisplay: {
        dataTable: {
          signature: ['header-row', 'data-rows', 'pagination', 'sorting'],
          markers: ['data-pattern="data-table"', 'role="table"'],
          components: ['Table', 'Pagination', 'Button', 'Input'],
          features: ['sort', 'filter', 'select', 'paginate'],
          description: 'Tabular data with interactions'
        },
        cardGrid: {
          signature: ['grid-container', 'cards', 'spacing'],
          markers: ['data-pattern="card-grid"', 'role="list"'],
          components: ['Card', 'Grid', 'Image', 'Button'],
          description: 'Grid layout of content cards'
        },
        listView: {
          signature: ['list-container', 'list-items', 'actions'],
          markers: ['data-pattern="list-view"', 'role="list"'],
          components: ['List', 'ListItem', 'Avatar', 'Button'],
          description: 'Vertical list of items with actions'
        }
      },

      // Navigation Patterns
      navigation: {
        topNav: {
          signature: ['logo', 'nav-links', 'user-menu'],
          markers: ['data-pattern="top-nav"', 'role="navigation"'],
          components: ['NavigationMenu', 'Link', 'DropdownMenu'],
          description: 'Horizontal top navigation bar'
        },
        sideNav: {
          signature: ['nav-sections', 'nav-items', 'collapse-button'],
          markers: ['data-pattern="side-nav"', 'role="navigation"'],
          components: ['Sidebar', 'Collapsible', 'Link'],
          description: 'Vertical sidebar navigation'
        },
        breadcrumb: {
          signature: ['breadcrumb-list', 'separators', 'links'],
          markers: ['data-pattern="breadcrumb"', 'aria-label="Breadcrumb"'],
          components: ['Breadcrumb', 'Link'],
          description: 'Hierarchical navigation path'
        }
      },

      // Feedback Patterns
      feedback: {
        notification: {
          signature: ['icon', 'title', 'description', 'actions'],
          markers: ['data-pattern="notification"', 'role="alert"'],
          components: ['Toast', 'Alert', 'Button'],
          variants: ['success', 'error', 'warning', 'info'],
          description: 'User feedback messages'
        },
        confirmation: {
          signature: ['title', 'description', 'cancel', 'confirm'],
          markers: ['data-pattern="confirmation"', 'role="alertdialog"'],
          components: ['AlertDialog', 'Button'],
          description: 'Action confirmation dialog'
        },
        progress: {
          signature: ['progress-bar', 'percentage', 'label'],
          markers: ['data-pattern="progress"', 'role="progressbar"'],
          components: ['Progress', 'Label'],
          description: 'Task progress indicator'
        }
      }
    };
  }

  /**
   * Initialize recognition markers
   */
  initializeMarkers() {
    return {
      // Structural markers
      structural: {
        container: 'data-ai-structure="container"',
        section: 'data-ai-structure="section"',
        group: 'data-ai-structure="group"',
        item: 'data-ai-structure="item"'
      },

      // Semantic markers
      semantic: {
        primary: 'data-ai-semantic="primary"',
        secondary: 'data-ai-semantic="secondary"',
        tertiary: 'data-ai-semantic="tertiary"',
        content: 'data-ai-semantic="content"',
        metadata: 'data-ai-semantic="metadata"'
      },

      // Interactive markers
      interactive: {
        clickable: 'data-ai-interactive="click"',
        draggable: 'data-ai-interactive="drag"',
        editable: 'data-ai-interactive="edit"',
        selectable: 'data-ai-interactive="select"',
        expandable: 'data-ai-interactive="expand"'
      },

      // State markers
      state: {
        loading: 'data-ai-state="loading"',
        error: 'data-ai-state="error"',
        success: 'data-ai-state="success"',
        disabled: 'data-ai-state="disabled"',
        active: 'data-ai-state="active"'
      },

      // Purpose markers
      purpose: {
        navigation: 'data-ai-purpose="navigation"',
        form: 'data-ai-purpose="form"',
        display: 'data-ai-purpose="display"',
        feedback: 'data-ai-purpose="feedback"',
        control: 'data-ai-purpose="control"'
      }
    };
  }

  /**
   * Initialize pattern relationships
   */
  initializeRelationships() {
    return {
      // Component combinations
      combinations: {
        'Form + Card': 'Contained form pattern',
        'Table + Pagination': 'Paginated data pattern',
        'Tabs + Forms': 'Multi-step form pattern',
        'Dialog + Form': 'Modal form pattern',
        'Sidebar + Navigation': 'App navigation pattern'
      },

      // Pattern hierarchy
      hierarchy: {
        page: ['layout', 'sections', 'components'],
        section: ['header', 'content', 'footer'],
        component: ['elements', 'props', 'state']
      },

      // Pattern flow
      flow: {
        authentication: ['login', 'validate', 'redirect'],
        dataManagement: ['list', 'filter', 'sort', 'paginate'],
        formSubmission: ['input', 'validate', 'submit', 'feedback']
      }
    };
  }

  /**
   * Detect patterns in HTML/JSX
   */
  detectPatterns(code) {
    const detectedPatterns = [];

    for (const [category, patterns] of Object.entries(this.patterns)) {
      for (const [patternName, pattern] of Object.entries(patterns)) {
        const confidence = this.calculatePatternConfidence(code, pattern);
        if (confidence > 0.6) {
          detectedPatterns.push({
            category,
            name: patternName,
            confidence,
            pattern,
            markers: this.extractMarkers(code, pattern)
          });
        }
      }
    }

    return detectedPatterns.sort((a, b) => b.confidence - a.confidence);
  }

  /**
   * Calculate pattern confidence score
   */
  calculatePatternConfidence(code, pattern) {
    let matches = 0;
    let total = pattern.signature.length;

    // Check for signature elements
    for (const signature of pattern.signature) {
      if (code.toLowerCase().includes(signature.toLowerCase())) {
        matches++;
      }
    }

    // Check for component usage
    if (pattern.components) {
      for (const component of pattern.components) {
        if (code.includes(`<${component}`) || code.includes(`{${component}`)) {
          matches += 0.5;
          total += 0.5;
        }
      }
    }

    // Check for markers
    if (pattern.markers) {
      for (const marker of pattern.markers) {
        if (code.includes(marker)) {
          matches += 0.3;
          total += 0.3;
        }
      }
    }

    return total > 0 ? matches / total : 0;
  }

  /**
   * Extract markers from code
   */
  extractMarkers(code, pattern) {
    const markers = [];

    // Extract data attributes
    const dataAttrPattern = /data-[a-z-]+="[^"]+"/g;
    const dataAttrs = code.match(dataAttrPattern) || [];
    markers.push(...dataAttrs);

    // Extract ARIA attributes
    const ariaPattern = /aria-[a-z-]+="[^"]+"/g;
    const ariaAttrs = code.match(ariaPattern) || [];
    markers.push(...ariaAttrs);

    // Extract role attributes
    const rolePattern = /role="[^"]+"/g;
    const roleAttrs = code.match(rolePattern) || [];
    markers.push(...roleAttrs);

    return [...new Set(markers)];
  }

  /**
   * Add pattern markers to code
   */
  addPatternMarkers(code, patternName) {
    const pattern = this.findPattern(patternName);
    if (!pattern) return code;

    let markedCode = code;

    // Add pattern markers
    if (pattern.markers) {
      for (const marker of pattern.markers) {
        if (!markedCode.includes(marker)) {
          // Add to root element
          markedCode = markedCode.replace(
            /(<[^>]+)(>)/,
            `$1 ${marker}$2`
          );
        }
      }
    }

    // Add AI metadata
    const aiMetadata = {
      pattern: patternName,
      category: this.findPatternCategory(patternName),
      timestamp: new Date().toISOString(),
      version: '1.0.0'
    };

    const metadataComment = `<!-- AI Pattern: ${JSON.stringify(aiMetadata)} -->`;
    markedCode = `${metadataComment}\n${markedCode}`;

    return markedCode;
  }

  /**
   * Find pattern by name
   */
  findPattern(patternName) {
    for (const patterns of Object.values(this.patterns)) {
      if (patterns[patternName]) {
        return patterns[patternName];
      }
    }
    return null;
  }

  /**
   * Find pattern category
   */
  findPatternCategory(patternName) {
    for (const [category, patterns] of Object.entries(this.patterns)) {
      if (patterns[patternName]) {
        return category;
      }
    }
    return null;
  }

  /**
   * Generate pattern documentation
   */
  generatePatternDoc(patternName) {
    const pattern = this.findPattern(patternName);
    if (!pattern) return null;

    return {
      name: patternName,
      category: this.findPatternCategory(patternName),
      description: pattern.description,
      signature: pattern.signature,
      components: pattern.components,
      markers: pattern.markers,
      example: this.generatePatternExample(patternName, pattern),
      implementation: this.generatePatternImplementation(patternName, pattern),
      accessibility: this.generatePatternA11y(pattern),
      variations: this.generatePatternVariations(patternName)
    };
  }

  /**
   * Generate pattern example
   */
  generatePatternExample(patternName, pattern) {
    const examples = {
      login: `<form data-pattern="login-form">
  <Input type="email" name="email" placeholder="Email" required />
  <Input type="password" name="password" placeholder="Password" required />
  <Checkbox name="remember">Remember me</Checkbox>
  <Button type="submit">Sign In</Button>
</form>`,
      dataTable: `<div data-pattern="data-table">
  <Table>
    <TableHeader>
      <TableRow>
        <TableHead>Name</TableHead>
        <TableHead>Status</TableHead>
        <TableHead>Actions</TableHead>
      </TableRow>
    </TableHeader>
    <TableBody>
      {data.map(item => (
        <TableRow key={item.id}>
          <TableCell>{item.name}</TableCell>
          <TableCell>{item.status}</TableCell>
          <TableCell>
            <Button size="sm">Edit</Button>
          </TableCell>
        </TableRow>
      ))}
    </TableBody>
  </Table>
  <Pagination />
</div>`
    };

    return examples[patternName] || '// Pattern example';
  }

  /**
   * Generate pattern implementation
   */
  generatePatternImplementation(patternName, pattern) {
    return {
      requiredComponents: pattern.components,
      requiredProps: this.extractRequiredProps(pattern),
      stateManagement: this.suggestStateManagement(pattern),
      eventHandlers: this.suggestEventHandlers(pattern),
      validation: pattern.validation || []
    };
  }

  /**
   * Extract required props for pattern
   */
  extractRequiredProps(pattern) {
    const props = [];

    if (pattern.signature.includes('submit')) {
      props.push('onSubmit');
    }
    if (pattern.signature.includes('input')) {
      props.push('value', 'onChange');
    }
    if (pattern.features?.includes('sort')) {
      props.push('onSort');
    }
    if (pattern.features?.includes('filter')) {
      props.push('onFilter');
    }

    return props;
  }

  /**
   * Suggest state management for pattern
   */
  suggestStateManagement(pattern) {
    const states = [];

    if (pattern.components?.includes('Form')) {
      states.push('formData', 'errors', 'isSubmitting');
    }
    if (pattern.components?.includes('Table')) {
      states.push('data', 'sortColumn', 'sortDirection', 'currentPage');
    }
    if (pattern.features?.includes('filter')) {
      states.push('filters', 'filteredData');
    }

    return states;
  }

  /**
   * Suggest event handlers for pattern
   */
  suggestEventHandlers(pattern) {
    const handlers = [];

    if (pattern.components?.includes('Button')) {
      handlers.push('onClick', 'onFocus', 'onBlur');
    }
    if (pattern.components?.includes('Input')) {
      handlers.push('onChange', 'onBlur', 'onKeyDown');
    }
    if (pattern.components?.includes('Form')) {
      handlers.push('onSubmit', 'onReset');
    }

    return handlers;
  }

  /**
   * Generate pattern accessibility
   */
  generatePatternA11y(pattern) {
    return {
      roles: pattern.markers?.filter(m => m.startsWith('role=')) || [],
      ariaAttributes: pattern.markers?.filter(m => m.startsWith('aria-')) || [],
      keyboardNavigation: this.suggestKeyboardNav(pattern),
      screenReaderSupport: this.suggestScreenReaderSupport(pattern)
    };
  }

  /**
   * Suggest keyboard navigation
   */
  suggestKeyboardNav(pattern) {
    const navigation = [];

    if (pattern.components?.includes('Form')) {
      navigation.push('Tab through fields', 'Enter to submit');
    }
    if (pattern.components?.includes('Table')) {
      navigation.push('Arrow keys for navigation', 'Space to select');
    }
    if (pattern.components?.includes('Dialog')) {
      navigation.push('Escape to close', 'Tab trap within dialog');
    }

    return navigation;
  }

  /**
   * Suggest screen reader support
   */
  suggestScreenReaderSupport(pattern) {
    const support = [];

    if (pattern.markers?.includes('role="alert"')) {
      support.push('Announces immediately');
    }
    if (pattern.markers?.includes('aria-label')) {
      support.push('Descriptive labels provided');
    }
    if (pattern.components?.includes('Form')) {
      support.push('Form validation announced');
    }

    return support;
  }

  /**
   * Generate pattern variations
   */
  generatePatternVariations(patternName) {
    const variations = {
      login: ['With social login', 'With 2FA', 'With password recovery'],
      dataTable: ['With inline editing', 'With bulk actions', 'With export'],
      cardGrid: ['Masonry layout', 'Fixed grid', 'Responsive columns']
    };

    return variations[patternName] || [];
  }

  /**
   * Analyze pattern relationships
   */
  analyzeRelationships(patterns) {
    const relationships = [];

    for (let i = 0; i < patterns.length; i++) {
      for (let j = i + 1; j < patterns.length; j++) {
        const relationship = this.findRelationship(patterns[i], patterns[j]);
        if (relationship) {
          relationships.push({
            from: patterns[i].name,
            to: patterns[j].name,
            type: relationship
          });
        }
      }
    }

    return relationships;
  }

  /**
   * Find relationship between patterns
   */
  findRelationship(pattern1, pattern2) {
    // Check for parent-child relationship
    if (pattern1.category === 'layout' && pattern2.category === 'forms') {
      return 'contains';
    }

    // Check for complementary patterns
    const combination = `${pattern1.name} + ${pattern2.name}`;
    if (this.relationships.combinations[combination]) {
      return 'complements';
    }

    // Check for sequential patterns
    if (this.relationships.flow[pattern1.name]?.includes(pattern2.name)) {
      return 'follows';
    }

    return null;
  }

  /**
   * Validate pattern implementation
   */
  validatePattern(code, patternName) {
    const pattern = this.findPattern(patternName);
    if (!pattern) return { valid: false, errors: ['Pattern not found'] };

    const errors = [];
    const warnings = [];

    // Check for required components
    for (const component of pattern.components || []) {
      if (!code.includes(`<${component}`)) {
        warnings.push(`Missing component: ${component}`);
      }
    }

    // Check for required markers
    for (const marker of pattern.markers || []) {
      if (!code.includes(marker)) {
        warnings.push(`Missing marker: ${marker}`);
      }
    }

    // Check for signature elements
    for (const signature of pattern.signature) {
      if (!code.toLowerCase().includes(signature.toLowerCase())) {
        errors.push(`Missing signature element: ${signature}`);
      }
    }

    return {
      valid: errors.length === 0,
      errors,
      warnings,
      confidence: this.calculatePatternConfidence(code, pattern)
    };
  }
}

module.exports = PatternRecognitionMarkers;