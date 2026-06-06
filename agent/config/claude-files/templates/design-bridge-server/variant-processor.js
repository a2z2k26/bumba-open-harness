/**
 * Variant Processor
 * Handles extraction and management of component variants and states
 * Sprint 2: Variant Processor Foundation
 */

const EventEmitter = require('events');

class VariantProcessor extends EventEmitter {
  constructor() {
    super();
    this.name = 'VariantProcessor';
    this.version = '1.0.0';

    // Variant extraction configuration
    this.config = {
      extractStates: true,
      extractSizes: true,
      extractThemes: true,
      extractBreakpoints: true,
      maxDepth: 5
    };

    // Standard state definitions
    this.standardStates = {
      interactive: ['default', 'hover', 'active', 'focus', 'disabled'],
      validation: ['valid', 'invalid', 'warning', 'info'],
      loading: ['idle', 'loading', 'success', 'error'],
      selection: ['unselected', 'selected', 'indeterminate']
    };

    // Size definitions
    this.standardSizes = ['xs', 'sm', 'md', 'lg', 'xl', '2xl'];

    // Theme definitions
    this.standardThemes = ['light', 'dark', 'high-contrast'];

    // Component variant registry
    this.variantRegistry = new Map();
  }

  /**
   * Extract all variants from a component
   */
  async extractAllVariants(component, options = {}) {
    const config = { ...this.config, ...options };

    try {
      const variants = {
        id: component.id || this.generateId(component),
        name: component.name,
        type: this.detectComponentType(component),
        states: config.extractStates ? await this.extractStates(component) : {},
        sizes: config.extractSizes ? await this.extractSizes(component) : {},
        themes: config.extractThemes ? await this.extractThemes(component) : {},
        breakpoints: config.extractBreakpoints ? await this.extractBreakpoints(component) : {},
        combinations: [],
        properties: {},
        constraints: {},
        metadata: {}
      };

      // Generate variant combinations
      variants.combinations = this.generateCombinations(variants);

      // Extract variant-specific properties
      variants.properties = await this.extractVariantProperties(component);

      // Detect constraints and rules
      variants.constraints = this.detectConstraints(variants);

      // Add metadata
      variants.metadata = this.generateMetadata(component, variants);

      // Register variant
      this.variantRegistry.set(variants.id, variants);

      // Emit extraction event
      this.emit('variant:extracted', variants);

      return variants;
    } catch (error) {
      this.emit('variant:error', { component, error });
      throw error;
    }
  }

  /**
   * Extract component states
   */
  async extractStates(component) {
    const states = {};

    // Check for explicit variant properties
    if (component.variantProperties) {
      for (const [property, values] of Object.entries(component.variantProperties)) {
        if (this.isStateProperty(property)) {
          states[property] = values;
        }
      }
    }

    // Auto-detect common states
    const detectedStates = this.autoDetectStates(component);

    // Merge explicit and detected states
    return { ...detectedStates, ...states };
  }

  /**
   * Extract size variants
   */
  async extractSizes(component) {
    const sizes = {};

    // Check for size-related properties
    if (component.variantProperties?.size) {
      sizes.defined = component.variantProperties.size;
    }

    // Auto-detect sizes from naming conventions
    const detectedSizes = this.detectSizesFromNaming(component);

    // Extract dimensional variants
    const dimensionalSizes = this.extractDimensionalSizes(component);

    return {
      defined: sizes.defined || [],
      detected: detectedSizes,
      dimensional: dimensionalSizes
    };
  }

  /**
   * Extract theme variants
   */
  async extractThemes(component) {
    const themes = {};

    // Check for theme properties
    if (component.variantProperties?.theme) {
      themes.defined = component.variantProperties.theme;
    }

    // Detect color scheme variants
    const colorSchemes = this.detectColorSchemes(component);

    // Detect mode variants (light/dark)
    const modes = this.detectModes(component);

    return {
      defined: themes.defined || [],
      colorSchemes,
      modes,
      customThemes: this.detectCustomThemes(component)
    };
  }

  /**
   * Extract breakpoint variants
   */
  async extractBreakpoints(component) {
    return {
      mobile: this.extractBreakpointVariant(component, 'mobile'),
      tablet: this.extractBreakpointVariant(component, 'tablet'),
      desktop: this.extractBreakpointVariant(component, 'desktop'),
      widescreen: this.extractBreakpointVariant(component, 'widescreen'),
      custom: this.extractCustomBreakpoints(component)
    };
  }

  /**
   * Generate all possible variant combinations
   */
  generateCombinations(variants) {
    const combinations = [];

    // Get all variant dimensions
    const dimensions = [];

    if (variants.states && Object.keys(variants.states).length > 0) {
      dimensions.push({ type: 'state', values: this.flattenStates(variants.states) });
    }

    if (variants.sizes?.defined?.length > 0) {
      dimensions.push({ type: 'size', values: variants.sizes.defined });
    }

    if (variants.themes?.defined?.length > 0) {
      dimensions.push({ type: 'theme', values: variants.themes.defined });
    }

    // Generate cartesian product of dimensions
    if (dimensions.length > 0) {
      const cartesian = this.cartesianProduct(dimensions);

      for (const combo of cartesian) {
        combinations.push({
          id: this.generateComboId(combo),
          variant: combo,
          exists: this.checkVariantExists(variants, combo),
          generated: !this.checkVariantExists(variants, combo)
        });
      }
    }

    return combinations;
  }

  /**
   * Extract variant-specific properties
   */
  async extractVariantProperties(component) {
    const properties = {};

    // Extract visual properties
    properties.visual = {
      fills: this.extractFills(component),
      strokes: this.extractStrokes(component),
      effects: this.extractEffects(component),
      opacity: component.opacity || 1,
      blendMode: component.blendMode || 'NORMAL'
    };

    // Extract layout properties
    properties.layout = {
      width: component.width,
      height: component.height,
      padding: this.extractPadding(component),
      margin: this.extractMargin(component),
      gap: this.extractGap(component)
    };

    // Extract typography properties (if text component)
    if (this.isTextComponent(component)) {
      properties.typography = this.extractTypography(component);
    }

    // Extract interaction properties
    properties.interactions = this.extractInteractions(component);

    return properties;
  }

  /**
   * Detect constraints and rules for variants
   */
  detectConstraints(variants) {
    return {
      mutuallyExclusive: this.findMutuallyExclusiveVariants(variants),
      dependencies: this.findVariantDependencies(variants),
      required: this.findRequiredVariants(variants),
      conditional: this.findConditionalVariants(variants),
      validCombinations: this.findValidCombinations(variants)
    };
  }

  /**
   * Helper: Auto-detect states from component
   */
  autoDetectStates(component) {
    const states = {};

    // Check component name for state indicators
    const name = (component.name || '').toLowerCase();

    for (const [category, stateList] of Object.entries(this.standardStates)) {
      const detected = stateList.filter(state =>
        name.includes(state) ||
        this.hasStateIndicator(component, state)
      );

      if (detected.length > 0) {
        states[category] = detected;
      }
    }

    return states;
  }

  /**
   * Helper: Check if component has state indicator
   */
  hasStateIndicator(component, state) {
    // Check various component properties for state indicators
    const indicators = [
      component.name,
      component.description,
      component.key,
      ...(component.tags || [])
    ];

    return indicators.some(indicator =>
      indicator && indicator.toLowerCase().includes(state.toLowerCase())
    );
  }

  /**
   * Helper: Detect sizes from naming
   */
  detectSizesFromNaming(component) {
    const name = (component.name || '').toLowerCase();
    const detected = [];

    for (const size of this.standardSizes) {
      if (name.includes(size)) {
        detected.push(size);
      }
    }

    return detected;
  }

  /**
   * Helper: Extract dimensional sizes
   */
  extractDimensionalSizes(component) {
    return {
      width: component.width,
      height: component.height,
      minWidth: component.minWidth,
      minHeight: component.minHeight,
      maxWidth: component.maxWidth,
      maxHeight: component.maxHeight
    };
  }

  /**
   * Helper: Detect color schemes
   */
  detectColorSchemes(component) {
    // Simplified implementation
    return [];
  }

  /**
   * Helper: Detect modes
   */
  detectModes(component) {
    const name = (component.name || '').toLowerCase();
    const modes = [];

    if (name.includes('light')) modes.push('light');
    if (name.includes('dark')) modes.push('dark');

    return modes;
  }

  /**
   * Helper: Detect custom themes
   */
  detectCustomThemes(component) {
    return [];
  }

  /**
   * Helper: Extract breakpoint variant
   */
  extractBreakpointVariant(component, breakpoint) {
    return null;
  }

  /**
   * Helper: Extract custom breakpoints
   */
  extractCustomBreakpoints(component) {
    return [];
  }

  /**
   * Helper: Extract fills
   */
  extractFills(component) {
    return component.fills || [];
  }

  /**
   * Helper: Extract strokes
   */
  extractStrokes(component) {
    return component.strokes || [];
  }

  /**
   * Helper: Extract effects
   */
  extractEffects(component) {
    return component.effects || [];
  }

  /**
   * Helper: Extract padding
   */
  extractPadding(component) {
    return component.padding || { top: 0, right: 0, bottom: 0, left: 0 };
  }

  /**
   * Helper: Extract margin
   */
  extractMargin(component) {
    return component.margin || { top: 0, right: 0, bottom: 0, left: 0 };
  }

  /**
   * Helper: Extract gap
   */
  extractGap(component) {
    return component.gap || 0;
  }

  /**
   * Helper: Check if text component
   */
  isTextComponent(component) {
    return component.type === 'TEXT' ||
           (component.name && component.name.toLowerCase().includes('text'));
  }

  /**
   * Helper: Extract typography
   */
  extractTypography(component) {
    return {
      fontFamily: component.fontFamily || 'system-ui',
      fontSize: component.fontSize || 16,
      fontWeight: component.fontWeight || 400,
      lineHeight: component.lineHeight || 1.5,
      letterSpacing: component.letterSpacing || 0
    };
  }

  /**
   * Helper: Extract interactions
   */
  extractInteractions(component) {
    return component.interactions || [];
  }

  /**
   * Helper: Find mutually exclusive variants
   */
  findMutuallyExclusiveVariants(variants) {
    return [];
  }

  /**
   * Helper: Find variant dependencies
   */
  findVariantDependencies(variants) {
    return [];
  }

  /**
   * Helper: Find required variants
   */
  findRequiredVariants(variants) {
    return [];
  }

  /**
   * Helper: Find conditional variants
   */
  findConditionalVariants(variants) {
    return [];
  }

  /**
   * Helper: Find valid combinations
   */
  findValidCombinations(variants) {
    return [];
  }

  /**
   * Helper: Generate metadata
   */
  generateMetadata(component, variants) {
    return {
      created: new Date().toISOString(),
      componentType: this.detectComponentType(component),
      variantCount: variants.combinations?.length || 0
    };
  }

  /**
   * Helper: Check if property is a state property
   */
  isStateProperty(property) {
    const stateProperties = ['state', 'status', 'mode', 'variant', 'type'];
    return stateProperties.some(sp => property.toLowerCase().includes(sp));
  }

  /**
   * Helper: Detect component type
   */
  detectComponentType(component) {
    const name = (component.name || '').toLowerCase();

    // Common component types
    const types = {
      button: ['button', 'btn', 'cta'],
      input: ['input', 'field', 'textfield'],
      card: ['card', 'tile', 'panel'],
      modal: ['modal', 'dialog', 'popup'],
      navigation: ['nav', 'menu', 'tabs'],
      list: ['list', 'table', 'grid'],
      form: ['form', 'fieldset'],
      icon: ['icon', 'glyph', 'symbol'],
      badge: ['badge', 'chip', 'tag'],
      alert: ['alert', 'notification', 'toast']
    };

    for (const [type, indicators] of Object.entries(types)) {
      if (indicators.some(indicator => name.includes(indicator))) {
        return type;
      }
    }

    return 'component';
  }

  /**
   * Helper: Generate unique ID for component
   */
  generateId(component) {
    const name = component.name || 'component';
    const timestamp = Date.now();
    const random = Math.random().toString(36).substr(2, 9);
    return `${name}-${timestamp}-${random}`.replace(/\s+/g, '-').toLowerCase();
  }

  /**
   * Helper: Generate combo ID
   */
  generateComboId(combo) {
    return combo.map(c => `${c.type}:${c.value}`).join('-');
  }

  /**
   * Helper: Cartesian product for combinations
   */
  cartesianProduct(dimensions) {
    if (dimensions.length === 0) return [[]];

    const [first, ...rest] = dimensions;
    const restProduct = this.cartesianProduct(rest);

    const result = [];
    for (const value of first.values) {
      for (const restCombo of restProduct) {
        result.push([{ type: first.type, value }, ...restCombo]);
      }
    }

    return result;
  }

  /**
   * Helper: Check if variant exists
   */
  checkVariantExists(variants, combo) {
    // Implementation would check actual Figma data
    // For now, return false (would be implemented with actual API)
    return false;
  }

  /**
   * Helper: Flatten states object
   */
  flattenStates(states) {
    const flat = [];
    for (const category of Object.values(states)) {
      if (Array.isArray(category)) {
        flat.push(...category);
      }
    }
    return flat;
  }

  /**
   * Get variant by ID
   */
  getVariant(id) {
    return this.variantRegistry.get(id);
  }

  /**
   * Get all variants
   */
  getAllVariants() {
    return Array.from(this.variantRegistry.values());
  }

  /**
   * Clear variant registry
   */
  clearRegistry() {
    this.variantRegistry.clear();
    this.emit('registry:cleared');
  }
}

module.exports = VariantProcessor;