/**
 * Component Pattern Identifier
 * Identifies and categorizes component patterns in design systems
 * Sprint 7: Component Pattern Identifier
 */

const EventEmitter = require('events');

class ComponentAnalyzer extends EventEmitter {
  constructor() {
    super();
    this.name = 'ComponentAnalyzer';
    this.version = '1.0.0';

    // Analysis configuration
    this.config = {
      similarityThreshold: 0.85,
      minComponentSize: 10,
      maxAnalysisDepth: 10,
      categorizeByAtomic: true,
      detectRelationships: true
    };

    // Component patterns
    this.patterns = {
      atomic: {
        atoms: new Map(),
        molecules: new Map(),
        organisms: new Map(),
        templates: new Map(),
        pages: new Map()
      },
      categories: new Map(),
      relationships: [],
      hierarchy: new Map()
    };

    // Common component types
    this.componentTypes = {
      navigation: ['nav', 'menu', 'breadcrumb', 'tabs', 'pagination'],
      forms: ['form', 'input', 'field', 'select', 'checkbox', 'radio', 'toggle'],
      content: ['card', 'article', 'post', 'list', 'table', 'grid'],
      feedback: ['alert', 'notification', 'toast', 'message', 'error', 'success'],
      overlay: ['modal', 'dialog', 'popup', 'drawer', 'tooltip', 'popover'],
      media: ['image', 'video', 'audio', 'gallery', 'carousel', 'slider'],
      action: ['button', 'link', 'cta', 'fab'],
      layout: ['container', 'section', 'header', 'footer', 'sidebar', 'main']
    };
  }

  /**
   * Analyze components in design file
   */
  async analyzeComponents(designFile, options = {}) {
    const config = { ...this.config, ...options };

    try {
      const analysis = {
        id: this.generateAnalysisId(),
        timestamp: new Date().toISOString(),
        file: designFile.name || 'untitled',
        components: {
          total: 0,
          categorized: {},
          atomic: {},
          patterns: [],
          relationships: [],
          hierarchy: {},
          similarity: [],
          variants: new Map()
        },
        metrics: {},
        recommendations: []
      };

      // Extract and analyze components
      const components = this.extractComponents(designFile);
      analysis.components.total = components.length;

      // Categorize components
      analysis.components.categorized = await this.categorizeComponents(components, config);

      // Atomic design classification
      if (config.categorizeByAtomic) {
        analysis.components.atomic = await this.classifyByAtomicDesign(components, config);
      }

      // Detect patterns
      analysis.components.patterns = await this.detectComponentPatterns(components, config);

      // Find relationships
      if (config.detectRelationships) {
        analysis.components.relationships = await this.findComponentRelationships(components, config);
      }

      // Build hierarchy
      analysis.components.hierarchy = await this.buildComponentHierarchy(components, config);

      // Find similar components
      analysis.components.similarity = await this.findSimilarComponents(components, config);

      // Detect variants
      analysis.components.variants = await this.detectComponentVariants(components, config);

      // Calculate metrics
      analysis.metrics = this.calculateComponentMetrics(analysis.components);

      // Generate recommendations
      analysis.recommendations = this.generateRecommendations(analysis);

      // Store patterns
      this.storePatterns(analysis.components);

      // Emit analysis complete
      this.emit('components:analyzed', analysis);

      return analysis;
    } catch (error) {
      this.emit('components:error', { designFile, error });
      throw error;
    }
  }

  /**
   * Extract components from design file
   */
  extractComponents(designFile) {
    const components = [];

    // Extract from components array
    if (designFile.components) {
      for (const component of designFile.components) {
        components.push(this.normalizeComponent(component));
      }
    }

    // Extract from document tree
    if (designFile.document) {
      this.extractComponentsFromNode(designFile.document, components);
    }

    // Extract from pages
    if (designFile.pages) {
      for (const page of designFile.pages) {
        if (page.children) {
          for (const child of page.children) {
            this.extractComponentsFromNode(child, components);
          }
        }
      }
    }

    return components;
  }

  /**
   * Extract components from node tree
   */
  extractComponentsFromNode(node, components, depth = 0) {
    if (depth > this.config.maxAnalysisDepth) return;

    // Check if node is a component
    if (node.type === 'COMPONENT' || node.type === 'COMPONENT_SET' || node.type === 'INSTANCE') {
      components.push(this.normalizeComponent(node));
    }

    // Recursively check children
    if (node.children) {
      for (const child of node.children) {
        this.extractComponentsFromNode(child, components, depth + 1);
      }
    }
  }

  /**
   * Normalize component data
   */
  normalizeComponent(component) {
    return {
      id: component.id,
      name: component.name || 'Unnamed',
      type: component.type,
      category: null,
      atomicLevel: null,
      properties: this.extractComponentProperties(component),
      children: component.children?.length || 0,
      depth: this.calculateDepth(component),
      complexity: this.calculateComplexity(component),
      signature: this.generateSignature(component),
      metadata: {
        width: component.width,
        height: component.height,
        x: component.x,
        y: component.y,
        visible: component.visible !== false,
        locked: component.locked === true
      }
    };
  }

  /**
   * Extract component properties
   */
  extractComponentProperties(component) {
    return {
      fills: component.fills || [],
      strokes: component.strokes || [],
      effects: component.effects || [],
      constraints: component.constraints || {},
      layoutMode: component.layoutMode,
      padding: component.padding,
      spacing: component.itemSpacing,
      cornerRadius: component.cornerRadius,
      opacity: component.opacity
    };
  }

  /**
   * Calculate component depth
   */
  calculateDepth(component, depth = 0) {
    if (!component.children || component.children.length === 0) {
      return depth;
    }

    let maxDepth = depth;
    for (const child of component.children) {
      const childDepth = this.calculateDepth(child, depth + 1);
      maxDepth = Math.max(maxDepth, childDepth);
    }

    return maxDepth;
  }

  /**
   * Calculate component complexity
   */
  calculateComplexity(component) {
    let complexity = 0;

    // Factor in children count
    complexity += (component.children?.length || 0) * 0.2;

    // Factor in property count
    const props = Object.keys(component).length;
    complexity += props * 0.1;

    // Factor in depth
    const depth = this.calculateDepth(component);
    complexity += depth * 0.15;

    // Factor in visual properties
    if (component.fills?.length > 0) complexity += 0.1;
    if (component.strokes?.length > 0) complexity += 0.1;
    if (component.effects?.length > 0) complexity += 0.15;

    // Factor in layout complexity
    if (component.layoutMode) complexity += 0.2;
    if (component.constraints) complexity += 0.1;

    return Math.min(complexity, 1);
  }

  /**
   * Generate component signature
   */
  generateSignature(component) {
    const parts = [
      component.type,
      component.children?.length || 0,
      component.layoutMode || 'none',
      component.fills?.length || 0,
      component.strokes?.length || 0
    ];

    return parts.join('-');
  }

  /**
   * Categorize components by type
   */
  async categorizeComponents(components, config) {
    const categories = {};

    for (const component of components) {
      const category = this.detectComponentCategory(component);
      component.category = category;

      if (!categories[category]) {
        categories[category] = [];
      }
      categories[category].push(component);
    }

    return categories;
  }

  /**
   * Detect component category
   */
  detectComponentCategory(component) {
    const name = component.name.toLowerCase();

    // Check against known types
    for (const [category, keywords] of Object.entries(this.componentTypes)) {
      for (const keyword of keywords) {
        if (name.includes(keyword)) {
          return category;
        }
      }
    }

    // Fallback categorization based on properties
    if (component.children === 0) {
      if (name.includes('icon')) return 'media';
      if (name.includes('text')) return 'content';
      return 'atoms';
    }

    if (component.complexity < 0.3) return 'atoms';
    if (component.complexity < 0.6) return 'molecules';
    if (component.complexity < 0.8) return 'organisms';

    return 'templates';
  }

  /**
   * Classify by atomic design
   */
  async classifyByAtomicDesign(components, config) {
    const atomic = {
      atoms: [],
      molecules: [],
      organisms: [],
      templates: [],
      pages: []
    };

    for (const component of components) {
      const level = this.determineAtomicLevel(component);
      component.atomicLevel = level;
      atomic[level].push(component);
    }

    return atomic;
  }

  /**
   * Determine atomic level
   */
  determineAtomicLevel(component) {
    const { children, complexity, depth } = component;

    // Atoms: Basic building blocks
    if (children === 0 || (complexity < 0.2 && depth === 0)) {
      return 'atoms';
    }

    // Molecules: Simple combinations
    if (children <= 3 || (complexity < 0.4 && depth <= 1)) {
      return 'molecules';
    }

    // Organisms: Complex components
    if (children <= 10 || (complexity < 0.7 && depth <= 3)) {
      return 'organisms';
    }

    // Templates: Layout structures
    if (component.name.toLowerCase().includes('template') ||
        component.name.toLowerCase().includes('layout')) {
      return 'templates';
    }

    // Pages: Full page designs
    if (component.name.toLowerCase().includes('page') ||
        component.name.toLowerCase().includes('screen')) {
      return 'pages';
    }

    // Default to organisms for complex components
    return 'organisms';
  }

  /**
   * Detect component patterns
   */
  async detectComponentPatterns(components, config) {
    const patterns = [];

    // Group by signature
    const signatureGroups = {};
    for (const component of components) {
      if (!signatureGroups[component.signature]) {
        signatureGroups[component.signature] = [];
      }
      signatureGroups[component.signature].push(component);
    }

    // Find recurring patterns
    for (const [signature, group] of Object.entries(signatureGroups)) {
      if (group.length >= 2) {
        patterns.push({
          type: 'recurring',
          signature,
          instances: group.length,
          components: group.map(c => ({ id: c.id, name: c.name })),
          commonProperties: this.findCommonProperties(group)
        });
      }
    }

    // Find compositional patterns
    const compositionalPatterns = this.findCompositionalPatterns(components);
    patterns.push(...compositionalPatterns);

    // Find behavioral patterns
    const behavioralPatterns = this.findBehavioralPatterns(components);
    patterns.push(...behavioralPatterns);

    return patterns;
  }

  /**
   * Find common properties
   */
  findCommonProperties(components) {
    if (components.length === 0) return {};

    const common = {};
    const firstProps = components[0].properties;

    for (const [key, value] of Object.entries(firstProps)) {
      const isCommon = components.every(c =>
        JSON.stringify(c.properties[key]) === JSON.stringify(value)
      );

      if (isCommon) {
        common[key] = value;
      }
    }

    return common;
  }

  /**
   * Find compositional patterns
   */
  findCompositionalPatterns(components) {
    const patterns = [];

    // Find container patterns
    const containers = components.filter(c => c.children > 0);
    const containerPatterns = {};

    for (const container of containers) {
      const childPattern = this.getChildPattern(container);
      if (!containerPatterns[childPattern]) {
        containerPatterns[childPattern] = [];
      }
      containerPatterns[childPattern].push(container);
    }

    for (const [pattern, group] of Object.entries(containerPatterns)) {
      if (group.length >= 2) {
        patterns.push({
          type: 'compositional',
          pattern,
          instances: group.length,
          components: group.map(c => ({ id: c.id, name: c.name }))
        });
      }
    }

    return patterns;
  }

  /**
   * Get child pattern
   */
  getChildPattern(component) {
    // Simplified child pattern detection
    return `children:${component.children}-depth:${component.depth}`;
  }

  /**
   * Find behavioral patterns
   */
  findBehavioralPatterns(components) {
    const patterns = [];

    // Find interactive patterns
    const interactive = components.filter(c =>
      c.name.toLowerCase().includes('hover') ||
      c.name.toLowerCase().includes('active') ||
      c.name.toLowerCase().includes('disabled')
    );

    if (interactive.length > 0) {
      const stateGroups = this.groupByStatePattern(interactive);

      for (const [pattern, group] of Object.entries(stateGroups)) {
        if (group.length >= 2) {
          patterns.push({
            type: 'behavioral',
            subtype: 'state',
            pattern,
            instances: group.length,
            components: group.map(c => ({ id: c.id, name: c.name }))
          });
        }
      }
    }

    return patterns;
  }

  /**
   * Group by state pattern
   */
  groupByStatePattern(components) {
    const groups = {};

    for (const component of components) {
      const baseName = this.extractBaseName(component.name);
      if (!groups[baseName]) {
        groups[baseName] = [];
      }
      groups[baseName].push(component);
    }

    return groups;
  }

  /**
   * Extract base name
   */
  extractBaseName(name) {
    return name
      .replace(/[-_\s](default|hover|active|disabled|focus|selected)/gi, '')
      .replace(/[-_\s](small|medium|large|xs|sm|md|lg|xl)/gi, '')
      .replace(/[-_\s](light|dark)/gi, '')
      .trim();
  }

  /**
   * Find component relationships
   */
  async findComponentRelationships(components, config) {
    const relationships = [];

    for (let i = 0; i < components.length; i++) {
      for (let j = i + 1; j < components.length; j++) {
        const relation = this.analyzeRelationship(components[i], components[j]);

        if (relation.strength >= config.similarityThreshold) {
          relationships.push({
            source: components[i].id,
            target: components[j].id,
            type: relation.type,
            strength: relation.strength,
            details: relation.details
          });
        }
      }
    }

    return relationships;
  }

  /**
   * Analyze relationship between components
   */
  analyzeRelationship(comp1, comp2) {
    const relation = {
      type: 'unknown',
      strength: 0,
      details: {}
    };

    // Check for variant relationship
    const baseName1 = this.extractBaseName(comp1.name);
    const baseName2 = this.extractBaseName(comp2.name);

    if (baseName1 === baseName2) {
      relation.type = 'variant';
      relation.strength = 0.9;
      relation.details = {
        baseName: baseName1,
        variant1: comp1.name,
        variant2: comp2.name
      };
      return relation;
    }

    // Check for parent-child relationship
    if (comp1.name.includes(comp2.name) || comp2.name.includes(comp1.name)) {
      relation.type = 'parent-child';
      relation.strength = 0.8;
      relation.details = {
        parent: comp1.name.length > comp2.name.length ? comp1.name : comp2.name,
        child: comp1.name.length > comp2.name.length ? comp2.name : comp1.name
      };
      return relation;
    }

    // Check for similarity
    const similarity = this.calculateSimilarity(comp1, comp2);
    if (similarity > 0.5) {
      relation.type = 'similar';
      relation.strength = similarity;
      relation.details = {
        similarity,
        commonSignature: comp1.signature === comp2.signature
      };
    }

    return relation;
  }

  /**
   * Calculate similarity between components
   */
  calculateSimilarity(comp1, comp2) {
    let similarity = 0;
    let factors = 0;

    // Compare signatures
    if (comp1.signature === comp2.signature) {
      similarity += 0.3;
    }
    factors++;

    // Compare categories
    if (comp1.category === comp2.category) {
      similarity += 0.2;
    }
    factors++;

    // Compare atomic levels
    if (comp1.atomicLevel === comp2.atomicLevel) {
      similarity += 0.2;
    }
    factors++;

    // Compare complexity
    const complexityDiff = Math.abs(comp1.complexity - comp2.complexity);
    similarity += (1 - complexityDiff) * 0.15;
    factors++;

    // Compare children count
    const childrenDiff = Math.abs(comp1.children - comp2.children);
    const maxChildren = Math.max(comp1.children, comp2.children);
    if (maxChildren > 0) {
      similarity += (1 - childrenDiff / maxChildren) * 0.15;
      factors++;
    }

    return similarity;
  }

  /**
   * Build component hierarchy
   */
  async buildComponentHierarchy(components, config) {
    const hierarchy = {
      root: [],
      levels: {},
      relationships: []
    };

    // Group by atomic level
    for (const component of components) {
      const level = component.atomicLevel || 'unknown';

      if (!hierarchy.levels[level]) {
        hierarchy.levels[level] = [];
      }
      hierarchy.levels[level].push(component);
    }

    // Build relationships between levels
    const levels = ['atoms', 'molecules', 'organisms', 'templates', 'pages'];

    for (let i = 0; i < levels.length - 1; i++) {
      const currentLevel = hierarchy.levels[levels[i]] || [];
      const nextLevel = hierarchy.levels[levels[i + 1]] || [];

      for (const parent of nextLevel) {
        for (const child of currentLevel) {
          if (this.couldContain(parent, child)) {
            hierarchy.relationships.push({
              parent: parent.id,
              child: child.id,
              parentLevel: levels[i + 1],
              childLevel: levels[i]
            });
          }
        }
      }
    }

    // Identify root components
    hierarchy.root = components.filter(c =>
      c.atomicLevel === 'pages' ||
      c.atomicLevel === 'templates'
    );

    return hierarchy;
  }

  /**
   * Check if parent could contain child
   */
  couldContain(parent, child) {
    // Simplified containment check
    return parent.children > 0 && parent.complexity > child.complexity;
  }

  /**
   * Find similar components
   */
  async findSimilarComponents(components, config) {
    const similarGroups = [];
    const processed = new Set();

    for (let i = 0; i < components.length; i++) {
      if (processed.has(i)) continue;

      const group = [components[i]];
      processed.add(i);

      for (let j = i + 1; j < components.length; j++) {
        if (processed.has(j)) continue;

        const similarity = this.calculateSimilarity(components[i], components[j]);

        if (similarity >= config.similarityThreshold) {
          group.push(components[j]);
          processed.add(j);
        }
      }

      if (group.length > 1) {
        similarGroups.push({
          components: group.map(c => ({ id: c.id, name: c.name })),
          similarity: this.calculateGroupSimilarity(group),
          suggestion: this.generateConsolidationSuggestion(group)
        });
      }
    }

    return similarGroups;
  }

  /**
   * Calculate group similarity
   */
  calculateGroupSimilarity(group) {
    let totalSimilarity = 0;
    let comparisons = 0;

    for (let i = 0; i < group.length; i++) {
      for (let j = i + 1; j < group.length; j++) {
        totalSimilarity += this.calculateSimilarity(group[i], group[j]);
        comparisons++;
      }
    }

    return comparisons > 0 ? totalSimilarity / comparisons : 0;
  }

  /**
   * Generate consolidation suggestion
   */
  generateConsolidationSuggestion(group) {
    const baseNames = group.map(c => this.extractBaseName(c.name));
    const uniqueBaseNames = [...new Set(baseNames)];

    if (uniqueBaseNames.length === 1) {
      return {
        type: 'variant-consolidation',
        message: `Consider creating a single component with variants for ${uniqueBaseNames[0]}`,
        components: group.length
      };
    }

    return {
      type: 'similarity-consolidation',
      message: 'Consider consolidating these similar components',
      components: group.length
    };
  }

  /**
   * Detect component variants
   */
  async detectComponentVariants(components, config) {
    const variants = new Map();

    // Group by base name
    const baseGroups = {};
    for (const component of components) {
      const baseName = this.extractBaseName(component.name);

      if (!baseGroups[baseName]) {
        baseGroups[baseName] = [];
      }
      baseGroups[baseName].push(component);
    }

    // Process groups with multiple components
    for (const [baseName, group] of Object.entries(baseGroups)) {
      if (group.length > 1) {
        const variantData = {
          baseName,
          count: group.length,
          variants: [],
          properties: this.extractVariantProperties(group),
          recommendations: []
        };

        // Analyze each variant
        for (const component of group) {
          const variant = {
            id: component.id,
            name: component.name,
            type: this.detectVariantType(component.name, baseName),
            differences: this.findDifferences(component, group[0])
          };
          variantData.variants.push(variant);
        }

        // Generate recommendations
        variantData.recommendations = this.generateVariantRecommendations(variantData);

        variants.set(baseName, variantData);
      }
    }

    return variants;
  }

  /**
   * Extract variant properties
   */
  extractVariantProperties(group) {
    const properties = {
      states: new Set(),
      sizes: new Set(),
      themes: new Set(),
      custom: new Set()
    };

    for (const component of group) {
      const variantType = this.detectVariantType(component.name, this.extractBaseName(component.name));

      if (variantType.state) properties.states.add(variantType.state);
      if (variantType.size) properties.sizes.add(variantType.size);
      if (variantType.theme) properties.themes.add(variantType.theme);
      if (variantType.custom) properties.custom.add(variantType.custom);
    }

    return {
      states: Array.from(properties.states),
      sizes: Array.from(properties.sizes),
      themes: Array.from(properties.themes),
      custom: Array.from(properties.custom)
    };
  }

  /**
   * Detect variant type
   */
  detectVariantType(name, baseName) {
    const variantPart = name.replace(baseName, '').toLowerCase();
    const type = {};

    // Detect state
    const states = ['default', 'hover', 'active', 'disabled', 'focus', 'selected'];
    for (const state of states) {
      if (variantPart.includes(state)) {
        type.state = state;
        break;
      }
    }

    // Detect size
    const sizes = ['xs', 'sm', 'md', 'lg', 'xl', 'small', 'medium', 'large'];
    for (const size of sizes) {
      if (variantPart.includes(size)) {
        type.size = size;
        break;
      }
    }

    // Detect theme
    const themes = ['light', 'dark'];
    for (const theme of themes) {
      if (variantPart.includes(theme)) {
        type.theme = theme;
        break;
      }
    }

    // Custom variant
    if (!type.state && !type.size && !type.theme && variantPart) {
      type.custom = variantPart.trim();
    }

    return type;
  }

  /**
   * Find differences between components
   */
  findDifferences(comp1, comp2) {
    const differences = [];

    // Compare basic properties
    if (comp1.children !== comp2.children) {
      differences.push({
        property: 'children',
        value1: comp1.children,
        value2: comp2.children
      });
    }

    if (Math.abs(comp1.complexity - comp2.complexity) > 0.1) {
      differences.push({
        property: 'complexity',
        value1: comp1.complexity,
        value2: comp2.complexity
      });
    }

    // Compare visual properties
    const props1 = comp1.properties;
    const props2 = comp2.properties;

    for (const key of Object.keys(props1)) {
      if (JSON.stringify(props1[key]) !== JSON.stringify(props2[key])) {
        differences.push({
          property: key,
          value1: props1[key],
          value2: props2[key]
        });
      }
    }

    return differences;
  }

  /**
   * Generate variant recommendations
   */
  generateVariantRecommendations(variantData) {
    const recommendations = [];

    // Check for missing states
    const expectedStates = ['default', 'hover', 'active', 'disabled'];
    const missingStates = expectedStates.filter(s => !variantData.properties.states.includes(s));

    if (missingStates.length > 0) {
      recommendations.push({
        type: 'missing-states',
        message: `Consider adding ${missingStates.join(', ')} states`,
        priority: 'medium'
      });
    }

    // Check for inconsistent sizing
    if (variantData.properties.sizes.length > 0 && variantData.properties.sizes.length < 3) {
      recommendations.push({
        type: 'incomplete-sizes',
        message: 'Consider adding more size variants (sm, md, lg)',
        priority: 'low'
      });
    }

    // Check for theme support
    if (variantData.properties.themes.length === 1) {
      recommendations.push({
        type: 'single-theme',
        message: 'Consider adding theme variants for better adaptability',
        priority: 'low'
      });
    }

    return recommendations;
  }

  /**
   * Calculate component metrics
   */
  calculateComponentMetrics(components) {
    return {
      total: components.total,
      byCategory: this.countByProperty(components.categorized),
      byAtomicLevel: this.countByProperty(components.atomic),
      averageComplexity: this.calculateAverageComplexity(components),
      averageDepth: this.calculateAverageDepth(components),
      patternCoverage: this.calculatePatternCoverage(components),
      variantCoverage: this.calculateVariantCoverage(components),
      consistencyScore: this.calculateConsistencyScore(components)
    };
  }

  /**
   * Count by property
   */
  countByProperty(grouped) {
    const counts = {};
    for (const [key, value] of Object.entries(grouped)) {
      counts[key] = Array.isArray(value) ? value.length : value.size;
    }
    return counts;
  }

  /**
   * Calculate average complexity
   */
  calculateAverageComplexity(components) {
    let total = 0;
    let count = 0;

    // Iterate through all component groups
    for (const group of Object.values(components.categorized)) {
      for (const component of group) {
        total += component.complexity;
        count++;
      }
    }

    return count > 0 ? total / count : 0;
  }

  /**
   * Calculate average depth
   */
  calculateAverageDepth(components) {
    let total = 0;
    let count = 0;

    for (const group of Object.values(components.categorized)) {
      for (const component of group) {
        total += component.depth;
        count++;
      }
    }

    return count > 0 ? total / count : 0;
  }

  /**
   * Calculate pattern coverage
   */
  calculatePatternCoverage(components) {
    const totalComponents = components.total;
    let coveredComponents = 0;

    for (const pattern of components.patterns) {
      coveredComponents += pattern.instances;
    }

    return totalComponents > 0 ? coveredComponents / totalComponents : 0;
  }

  /**
   * Calculate variant coverage
   */
  calculateVariantCoverage(components) {
    let totalVariants = 0;
    let completeVariants = 0;

    for (const [_, variantData] of components.variants) {
      totalVariants++;

      // Check if has essential variants
      if (variantData.properties.states.length >= 3 &&
          variantData.properties.sizes.length >= 2) {
        completeVariants++;
      }
    }

    return totalVariants > 0 ? completeVariants / totalVariants : 0;
  }

  /**
   * Calculate consistency score
   */
  calculateConsistencyScore(components) {
    let score = 100;

    // Deduct for too many unique signatures
    const uniqueSignatures = new Set();
    for (const group of Object.values(components.categorized)) {
      for (const component of group) {
        uniqueSignatures.add(component.signature);
      }
    }

    if (uniqueSignatures.size > components.total * 0.7) {
      score -= 20; // Too much variation
    }

    // Deduct for poor pattern coverage
    const patternCoverage = this.calculatePatternCoverage(components);
    if (patternCoverage < 0.3) {
      score -= 15;
    }

    // Deduct for incomplete variants
    const variantCoverage = this.calculateVariantCoverage(components);
    if (variantCoverage < 0.5) {
      score -= 10;
    }

    return Math.max(0, Math.min(100, score));
  }

  /**
   * Generate recommendations
   */
  generateRecommendations(analysis) {
    const recommendations = [];

    // Check component organization
    if (analysis.metrics.consistencyScore < 70) {
      recommendations.push({
        type: 'consistency',
        priority: 'high',
        message: 'Component library lacks consistency. Consider establishing design patterns.',
        score: analysis.metrics.consistencyScore
      });
    }

    // Check atomic design adoption
    const atomicBalance = this.checkAtomicBalance(analysis.components.atomic);
    if (!atomicBalance.balanced) {
      recommendations.push({
        type: 'atomic-design',
        priority: 'medium',
        message: atomicBalance.message,
        distribution: atomicBalance.distribution
      });
    }

    // Check variant completeness
    if (analysis.metrics.variantCoverage < 0.6) {
      recommendations.push({
        type: 'variants',
        priority: 'medium',
        message: 'Many components lack complete variant sets',
        coverage: analysis.metrics.variantCoverage
      });
    }

    // Check for duplicate patterns
    const duplicates = analysis.components.similarity.filter(g => g.similarity > 0.9);
    if (duplicates.length > 0) {
      recommendations.push({
        type: 'duplicates',
        priority: 'high',
        message: `Found ${duplicates.length} groups of potentially duplicate components`,
        groups: duplicates.length
      });
    }

    return recommendations;
  }

  /**
   * Check atomic balance
   */
  checkAtomicBalance(atomic) {
    const counts = {
      atoms: atomic.atoms?.length || 0,
      molecules: atomic.molecules?.length || 0,
      organisms: atomic.organisms?.length || 0,
      templates: atomic.templates?.length || 0,
      pages: atomic.pages?.length || 0
    };

    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    const distribution = {};

    for (const [level, count] of Object.entries(counts)) {
      distribution[level] = total > 0 ? count / total : 0;
    }

    // Check for healthy distribution
    const balanced =
      distribution.atoms > 0.2 &&
      distribution.molecules > 0.15 &&
      distribution.organisms > 0.1;

    let message = balanced
      ? 'Atomic design hierarchy is well-balanced'
      : 'Consider building more foundational components (atoms and molecules)';

    return { balanced, distribution, message };
  }

  /**
   * Store patterns
   */
  storePatterns(components) {
    // Store atomic patterns
    for (const [level, items] of Object.entries(components.atomic)) {
      if (this.patterns.atomic[level]) {
        for (const item of items) {
          this.patterns.atomic[level].set(item.id, item);
        }
      }
    }

    // Store categories
    for (const [category, items] of Object.entries(components.categorized)) {
      this.patterns.categories.set(category, items);
    }

    // Store relationships
    this.patterns.relationships.push(...components.relationships);

    // Store hierarchy
    for (const [key, value] of Object.entries(components.hierarchy)) {
      this.patterns.hierarchy.set(key, value);
    }
  }

  /**
   * Generate analysis ID
   */
  generateAnalysisId() {
    return `components-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
  }

  /**
   * Export component analysis
   */
  exportAnalysis(format = 'json') {
    const analysis = {
      atomic: {},
      categories: Object.fromEntries(this.patterns.categories),
      relationships: this.patterns.relationships,
      hierarchy: Object.fromEntries(this.patterns.hierarchy)
    };

    // Convert atomic maps to arrays
    for (const [level, map] of Object.entries(this.patterns.atomic)) {
      analysis.atomic[level] = Array.from(map.values());
    }

    switch (format) {
      case 'json':
        return JSON.stringify(analysis, null, 2);
      case 'markdown':
        return this.exportAsMarkdown(analysis);
      case 'csv':
        return this.exportAsCSV(analysis);
      default:
        return analysis;
    }
  }

  /**
   * Export as Markdown
   */
  exportAsMarkdown(analysis) {
    let md = '# Component Analysis Report\n\n';

    // Atomic design breakdown
    md += '## Atomic Design Structure\n\n';
    for (const [level, components] of Object.entries(analysis.atomic)) {
      md += `### ${level.charAt(0).toUpperCase() + level.slice(1)} (${components.length})\n`;
      for (const comp of components.slice(0, 5)) {
        md += `- ${comp.name}\n`;
      }
      if (components.length > 5) {
        md += `- ...and ${components.length - 5} more\n`;
      }
      md += '\n';
    }

    // Categories
    md += '## Component Categories\n\n';
    for (const [category, components] of Object.entries(analysis.categories)) {
      md += `- **${category}**: ${components.length} components\n`;
    }

    return md;
  }

  /**
   * Export as CSV
   */
  exportAsCSV(analysis) {
    let csv = 'ID,Name,Category,Atomic Level,Complexity,Children,Depth\n';

    for (const components of Object.values(analysis.categories)) {
      for (const comp of components) {
        csv += `${comp.id},"${comp.name}",${comp.category},${comp.atomicLevel},${comp.complexity},${comp.children},${comp.depth}\n`;
      }
    }

    return csv;
  }
}

module.exports = ComponentAnalyzer;