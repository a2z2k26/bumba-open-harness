/**
 * Catalog Auto-Organizer
 * Sprint 33: Smart component organization
 *
 * Automatically organizes design components into:
 * - Categories (Forms, Layout, Navigation, etc.)
 * - Types (Buttons, Inputs, Cards, etc.)
 * - Hierarchical page structure
 */

const EventEmitter = require('events');

class CatalogAutoOrganizer extends EventEmitter {
  constructor(options = {}) {
    super();

    this.options = {
      allowCustomCategories: options.allowCustomCategories !== false,
      autoDetectTypes: options.autoDetectTypes !== false,
      ...options
    };

    // Define organization rules
    this.categoryRules = this.defineCategoryRules();
    this.typeRules = this.defineTypeRules();

    // Catalog structure
    this.catalog = {
      categories: {},
      types: {},
      pages: [],
      navigation: {}
    };

    // Statistics
    this.stats = {
      totalComponents: 0,
      categorized: 0,
      uncategorized: 0,
      categories: 0,
      types: 0
    };
  }

  /**
   * Define category rules
   */
  defineCategoryRules() {
    return {
      'Forms': {
        types: ['input', 'textarea', 'select', 'checkbox', 'radio', 'form', 'field'],
        keywords: ['input', 'form', 'field', 'select', 'checkbox', 'radio', 'submit'],
        priority: 1
      },
      'Buttons': {
        types: ['button'],
        keywords: ['button', 'btn', 'submit', 'action'],
        priority: 2
      },
      'Layout': {
        types: ['container', 'grid', 'flex', 'layout', 'section'],
        keywords: ['container', 'grid', 'flex', 'layout', 'wrapper', 'section'],
        priority: 3
      },
      'Navigation': {
        types: ['nav', 'navbar', 'menu', 'sidebar', 'tabs', 'breadcrumb'],
        keywords: ['nav', 'menu', 'sidebar', 'tab', 'breadcrumb', 'link'],
        priority: 4
      },
      'Data Display': {
        types: ['table', 'list', 'card', 'avatar', 'badge', 'tag'],
        keywords: ['table', 'list', 'card', 'avatar', 'badge', 'tag', 'label'],
        priority: 5
      },
      'Feedback': {
        types: ['alert', 'notification', 'toast', 'modal', 'dialog', 'snackbar'],
        keywords: ['alert', 'notification', 'toast', 'modal', 'dialog', 'message'],
        priority: 6
      },
      'Typography': {
        types: ['heading', 'text', 'paragraph', 'label'],
        keywords: ['heading', 'title', 'text', 'paragraph', 'label', 'typography'],
        priority: 7
      },
      'Media': {
        types: ['image', 'video', 'icon', 'avatar'],
        keywords: ['image', 'img', 'video', 'icon', 'avatar', 'media'],
        priority: 8
      },
      'Other': {
        types: [],
        keywords: [],
        priority: 99 // Catch-all
      }
    };
  }

  /**
   * Define type detection rules
   */
  defineTypeRules() {
    return [
      { type: 'button', patterns: ['button', 'btn'], requiredProps: [] },
      { type: 'input', patterns: ['input', 'field', 'textbox'], requiredProps: [] },
      { type: 'select', patterns: ['select', 'dropdown'], requiredProps: [] },
      { type: 'checkbox', patterns: ['checkbox', 'check'], requiredProps: [] },
      { type: 'radio', patterns: ['radio'], requiredProps: [] },
      { type: 'form', patterns: ['form'], requiredProps: [] },
      { type: 'card', patterns: ['card'], requiredProps: [] },
      { type: 'modal', patterns: ['modal', 'dialog'], requiredProps: [] },
      { type: 'alert', patterns: ['alert', 'notification', 'toast'], requiredProps: [] },
      { type: 'nav', patterns: ['nav', 'navbar', 'navigation'], requiredProps: [] },
      { type: 'menu', patterns: ['menu'], requiredProps: [] },
      { type: 'table', patterns: ['table', 'datagrid'], requiredProps: [] },
      { type: 'list', patterns: ['list'], requiredProps: [] },
      { type: 'container', patterns: ['container', 'wrapper', 'box'], requiredProps: [] },
      { type: 'grid', patterns: ['grid'], requiredProps: [] },
      { type: 'heading', patterns: ['heading', 'title', 'h1', 'h2', 'h3'], requiredProps: [] },
      { type: 'text', patterns: ['text', 'paragraph', 'p'], requiredProps: [] },
      { type: 'icon', patterns: ['icon'], requiredProps: [] },
      { type: 'image', patterns: ['image', 'img', 'picture'], requiredProps: [] }
    ];
  }

  /**
   * Organize components into catalog
   */
  organize(components) {
    this.stats.totalComponents = components.length;

    const organized = {
      categories: {},
      types: {},
      metadata: {
        total: components.length,
        timestamp: new Date().toISOString()
      }
    };

    // Categorize each component
    components.forEach(component => {
      // Detect type
      const detectedType = this.detectType(component);
      component.detectedType = detectedType;

      // Detect category
      const category = this.detectCategory(component, detectedType);
      component.category = category;

      // Add to categories
      if (!organized.categories[category]) {
        organized.categories[category] = [];
      }
      organized.categories[category].push(component);

      // Add to types
      if (!organized.types[detectedType]) {
        organized.types[detectedType] = [];
      }
      organized.types[detectedType].push(component);

      if (category !== 'Other') {
        this.stats.categorized++;
      } else {
        this.stats.uncategorized++;
      }
    });

    this.stats.categories = Object.keys(organized.categories).length;
    this.stats.types = Object.keys(organized.types).length;

    this.catalog = organized;

    this.emit('organization:completed', {
      categories: this.stats.categories,
      types: this.stats.types,
      categorized: this.stats.categorized,
      timestamp: new Date().toISOString()
    });

    return organized;
  }

  /**
   * Detect component type
   */
  detectType(component) {
    const name = (component.name || '').toLowerCase();
    const type = (component.type || '').toLowerCase();

    // Check explicit type first
    if (type) {
      const rule = this.typeRules.find(r => r.type === type);
      if (rule) return type;
    }

    // Check name patterns
    for (const rule of this.typeRules) {
      for (const pattern of rule.patterns) {
        if (name.includes(pattern)) {
          return rule.type;
        }
      }
    }

    // Default to component name or 'component'
    return type || 'component';
  }

  /**
   * Detect component category
   */
  detectCategory(component, detectedType) {
    const name = (component.name || '').toLowerCase();

    // Check each category rule
    const matches = [];

    Object.entries(this.categoryRules).forEach(([category, rule]) => {
      let score = 0;

      // Check type match
      if (rule.types.includes(detectedType)) {
        score += 10;
      }

      // Check keyword match
      rule.keywords.forEach(keyword => {
        if (name.includes(keyword)) {
          score += 1;
        }
      });

      if (score > 0) {
        matches.push({ category, score, priority: rule.priority });
      }
    });

    // Sort by score (highest first), then priority (lowest first)
    matches.sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      return a.priority - b.priority;
    });

    return matches.length > 0 ? matches[0].category : 'Other';
  }

  /**
   * Create navigation structure
   */
  createNavigation() {
    const navigation = {
      main: [],
      categories: {},
      breadcrumbs: []
    };

    // Create category navigation
    Object.keys(this.catalog.categories || {}).forEach(category => {
      const components = this.catalog.categories[category];

      navigation.categories[category] = {
        name: category,
        count: components.length,
        items: components.map(c => ({
          id: c.id,
          name: c.name,
          type: c.detectedType
        }))
      };

      navigation.main.push({
        name: category,
        href: `#${this.slugify(category)}`,
        count: components.length
      });
    });

    // Sort main navigation by category priority
    navigation.main.sort((a, b) => {
      const priorityA = this.categoryRules[a.name]?.priority || 99;
      const priorityB = this.categoryRules[b.name]?.priority || 99;
      return priorityA - priorityB;
    });

    this.catalog.navigation = navigation;

    return navigation;
  }

  /**
   * Create page structure
   */
  createPageStructure() {
    const pages = [];

    // Create index page
    pages.push({
      path: 'index.html',
      title: 'Design Catalog',
      type: 'index',
      content: {
        categories: Object.keys(this.catalog.categories || {}).length,
        components: this.stats.totalComponents,
        navigation: this.catalog.navigation
      }
    });

    // Create category pages
    Object.entries(this.catalog.categories || {}).forEach(([category, components]) => {
      pages.push({
        path: `${this.slugify(category)}.html`,
        title: category,
        type: 'category',
        category,
        content: {
          components,
          count: components.length
        }
      });
    });

    // Create component detail pages
    Object.values(this.catalog.categories || {}).flat().forEach(component => {
      pages.push({
        path: `components/${this.slugify(component.name)}.html`,
        title: component.name,
        type: 'component',
        component,
        content: component
      });
    });

    this.catalog.pages = pages;

    return pages;
  }

  /**
   * Add custom category
   */
  addCategory(name, rule) {
    if (!this.options.allowCustomCategories) {
      throw new Error('Custom categories are not allowed');
    }

    this.categoryRules[name] = {
      types: rule.types || [],
      keywords: rule.keywords || [],
      priority: rule.priority || 50
    };

    this.emit('category:added', { name, rule });

    return true;
  }

  /**
   * Get organization summary
   */
  getSummary() {
    return {
      stats: this.stats,
      categories: Object.keys(this.catalog.categories || {}).map(category => ({
        name: category,
        count: this.catalog.categories[category].length,
        priority: this.categoryRules[category]?.priority
      })),
      types: Object.keys(this.catalog.types || {}).map(type => ({
        name: type,
        count: this.catalog.types[type].length
      })),
      pages: this.catalog.pages?.length || 0
    };
  }

  /**
   * Get components by category
   */
  getByCategory(category) {
    return this.catalog.categories?.[category] || [];
  }

  /**
   * Get components by type
   */
  getByType(type) {
    return this.catalog.types?.[type] || [];
  }

  /**
   * Search components
   */
  search(query) {
    const results = [];
    const lowercaseQuery = query.toLowerCase();

    Object.values(this.catalog.categories || {}).flat().forEach(component => {
      if (
        component.name.toLowerCase().includes(lowercaseQuery) ||
        component.detectedType.toLowerCase().includes(lowercaseQuery) ||
        component.category.toLowerCase().includes(lowercaseQuery)
      ) {
        results.push(component);
      }
    });

    return results;
  }

  /**
   * Helper: Slugify string
   */
  slugify(str) {
    return str
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
  }

  /**
   * Get catalog statistics
   */
  getStats() {
    return {
      ...this.stats,
      categoriesAvailable: Object.keys(this.categoryRules).length,
      typesAvailable: this.typeRules.length
    };
  }

  /**
   * Test organization
   */
  testOrganization() {
    console.log('🧪 Testing catalog auto-organization...\n');

    const testComponents = [
      { id: '1', name: 'PrimaryButton', type: 'button' },
      { id: '2', name: 'EmailInput', type: 'input' },
      { id: '3', name: 'UserCard', type: 'card' },
      { id: '4', name: 'MainNavigation', type: 'nav' },
      { id: '5', name: 'SuccessAlert', type: 'alert' },
      { id: '6', name: 'DataTable', type: 'table' },
      { id: '7', name: 'PageHeading', type: 'heading' }
    ];

    const organized = this.organize(testComponents);
    const navigation = this.createNavigation();
    const pages = this.createPageStructure();

    console.log('Organization Results:');
    console.log(`  Total Components: ${this.stats.totalComponents}`);
    console.log(`  Categories: ${this.stats.categories}`);
    console.log(`  Types: ${this.stats.types}`);
    console.log(`  Categorized: ${this.stats.categorized}`);
    console.log(`  Uncategorized: ${this.stats.uncategorized}\n`);

    console.log('Categories:');
    Object.keys(organized.categories).forEach(category => {
      console.log(`  - ${category}: ${organized.categories[category].length} components`);
    });

    console.log(`\nNavigation Items: ${navigation.main.length}`);
    console.log(`Pages Created: ${pages.length}\n`);

    console.log('✅ Organization test complete!\n');
  }
}

module.exports = CatalogAutoOrganizer;
