/**
 * Token Validation System
 * Validates design tokens against schema and business rules
 */

const path = require('path');
const fs = require('fs');

class TokenValidator {
  constructor(schemaPath, presetName = 'standard') {
    // Simple validation without external dependencies
    this.schema = this.loadSchema(schemaPath || './token-schema.json');
    this.businessRules = this.defineBusinessRules();
    this.rulePresets = this.defineRulePresets();
    this.activePreset = presetName;
  }

  /**
   * Define validation rule presets for different use cases
   */
  defineRulePresets() {
    // Get all available rule names from businessRules
    const allRules = {};
    Object.values(this.businessRules).forEach(ruleCategory => {
      ruleCategory.forEach(rule => {
        allRules[rule.name] = true;
      });
    });

    return {
      'wcag-aa': {
        // Accessibility focused - WCAG AA compliance
        'wcag-compliance': true,
        'color-naming': true,
        'line-height': true,
        'typography-hierarchy': true,
        'component-completeness': false,
        'spacing-usage': false
      },
      'wcag-aaa': {
        // Accessibility focused - WCAG AAA compliance (stricter)
        'wcag-compliance': true,
        'color-naming': true,
        'color-consistency': true,
        'line-height': true,
        'typography-hierarchy': true,
        'component-completeness': true
      },
      'standard': {
        // Balanced validation - recommended for most projects
        'wcag-compliance': true,
        'color-naming': true,
        'color-consistency': true,
        'font-scale': true,
        'line-height': true,
        'typography-hierarchy': true,
        'spacing-scale': true,
        'component-consistency': true
      },
      'strict': {
        // All rules enabled - comprehensive validation
        ...allRules
      },
      'minimal': {
        // Only critical errors - fast validation
        'wcag-compliance': true,
        'typography-hierarchy': true
      },
      'design-system': {
        // Design system maturity focused
        'color-naming': true,
        'color-consistency': true,
        'font-scale': true,
        'typography-hierarchy': true,
        'spacing-scale': true,
        'component-completeness': true,
        'component-consistency': true
      },
      'performance': {
        // Quick validation for CI/CD pipelines
        'color-naming': false,
        'wcag-compliance': true,
        'typography-hierarchy': true,
        'spacing-scale': false
      }
    };
  }

  /**
   * Get active preset configuration
   */
  getActivePreset() {
    return this.rulePresets[this.activePreset] || this.rulePresets['standard'];
  }

  /**
   * Set validation preset
   */
  setPreset(presetName) {
    if (!this.rulePresets[presetName]) {
      throw new Error(`Unknown preset: ${presetName}. Available: ${Object.keys(this.rulePresets).join(', ')}`);
    }
    this.activePreset = presetName;
  }

  /**
   * Get available presets
   */
  getAvailablePresets() {
    return Object.keys(this.rulePresets).map(name => ({
      name,
      description: this.getPresetDescription(name),
      rules: this.rulePresets[name]
    }));
  }

  /**
   * Get preset description
   */
  getPresetDescription(presetName) {
    const descriptions = {
      'wcag-aa': 'WCAG AA accessibility compliance - recommended for public websites',
      'wcag-aaa': 'WCAG AAA accessibility compliance - highest accessibility standard',
      'standard': 'Balanced validation - recommended for most projects',
      'strict': 'All validation rules enabled - comprehensive analysis',
      'minimal': 'Critical errors only - fastest validation',
      'design-system': 'Design system maturity and consistency focused',
      'performance': 'Optimized for CI/CD pipelines - fast execution'
    };
    return descriptions[presetName] || 'Custom preset';
  }

  loadSchema(schemaPath) {
    try {
      const fullPath = path.resolve(__dirname, schemaPath);
      const schemaContent = fs.readFileSync(fullPath, 'utf8');
      return JSON.parse(schemaContent);
    } catch (error) {
      console.error('Failed to load token schema:', error);
      throw new Error(`Schema loading failed: ${error.message}`);
    }
  }

  defineBusinessRules() {
    return {
      colorRules: [
        {
          name: 'wcag-compliance',
          description: 'Colors must meet WCAG contrast requirements',
          validator: this.validateWCAGCompliance.bind(this)
        },
        {
          name: 'color-naming',
          description: 'Colors should follow semantic naming conventions',
          validator: this.validateColorNaming.bind(this)
        },
        {
          name: 'color-consistency',
          description: 'Colors should maintain consistent hue relationships',
          validator: this.validateColorConsistency.bind(this)
        }
      ],

      typographyRules: [
        {
          name: 'font-scale',
          description: 'Typography should follow a consistent scale',
          validator: this.validateTypographyScale.bind(this)
        },
        {
          name: 'line-height',
          description: 'Line heights should be within reasonable ranges',
          validator: this.validateLineHeight.bind(this)
        },
        {
          name: 'typography-hierarchy',
          description: 'Typography should establish clear hierarchy',
          validator: this.validateTypographyHierarchy.bind(this)
        }
      ],

      spacingRules: [
        {
          name: 'spacing-scale',
          description: 'Spacing should follow a consistent scale',
          validator: this.validateSpacingScale.bind(this)
        },
        {
          name: 'spacing-usage',
          description: 'Spacing values should be purposeful',
          validator: this.validateSpacingUsage.bind(this)
        }
      ],

      componentRules: [
        {
          name: 'component-completeness',
          description: 'Components should have all required variants',
          validator: this.validateComponentCompleteness.bind(this)
        },
        {
          name: 'component-consistency',
          description: 'Components should use consistent tokens',
          validator: this.validateComponentConsistency.bind(this)
        }
      ]
    };
  }

  validateSchema(tokens) {
    try {
      // Basic schema validation without external dependencies
      const validation = this.validateBasicStructure(tokens);

      if (!validation.valid) {
        return {
          valid: false,
          errors: validation.errors
        };
      }

      // Additional schema checks
      const schemaErrors = [];

      // Check required fields
      if (!tokens.tokens) {
        schemaErrors.push({
          type: 'schema',
          message: 'Missing required "tokens" property',
          path: 'root'
        });
      }

      // Check token structure
      if (tokens.tokens) {
        for (const [category, categoryTokens] of Object.entries(tokens.tokens)) {
          if (typeof categoryTokens !== 'object') {
            schemaErrors.push({
              type: 'schema',
              message: `Category "${category}" must be an object`,
              path: `tokens.${category}`
            });
          }
        }
      }

      return {
        valid: schemaErrors.length === 0,
        errors: schemaErrors
      };
    } catch (error) {
      return {
        valid: false,
        errors: [{
          type: 'schema',
          message: `Schema validation error: ${error.message}`,
          path: 'root'
        }]
      };
    }
  }

  async validateTokens(tokens) {
    const results = {
      isValid: true,
      results: null,
      errors: [],
      warnings: [],
      metadata: {
        totalTokens: 0,
        validatedTokens: 0,
        validationTime: new Date().toISOString()
      }
    };

    try {
      // Basic structure validation
      const structureValid = this.validateBasicStructure(tokens);
      if (!structureValid.valid) {
        results.isValid = false;
        results.errors.push(...structureValid.errors);
      }

      // Count tokens
      results.metadata.totalTokens = this.countTokens(tokens);

      // Business rules validation
      const businessResults = await this.validateBusinessRules(tokens);
      results.errors.push(...businessResults.errors);
      results.warnings.push(...businessResults.warnings);

      // Accessibility validation
      const a11yResults = await this.validateAccessibility(tokens);
      results.errors.push(...a11yResults.errors);
      results.warnings.push(...a11yResults.warnings);

      // Consistency validation
      const consistencyResults = await this.validateConsistency(tokens);
      results.warnings.push(...consistencyResults.warnings);

      results.isValid = results.errors.length === 0;
      results.metadata.validatedTokens = results.metadata.totalTokens -
        results.errors.filter(e => e.severity === 'error').length;
      results.results = results; // For compatibility

      return results;

    } catch (error) {
      results.errors.push({
        type: 'system',
        severity: 'error',
        message: `Validation system error: ${error.message}`,
        path: 'system',
        timestamp: new Date().toISOString()
      });
      results.isValid = false;

      return results;
    }
  }

  validateBasicStructure(tokens) {
    const validation = { valid: true, errors: [] };

    if (!tokens || typeof tokens !== 'object') {
      validation.valid = false;
      validation.errors.push({
        type: 'structure',
        message: 'Tokens must be a valid object',
        severity: 'error'
      });
    }

    // Check for circular references
    try {
      JSON.stringify(tokens);
    } catch (error) {
      validation.valid = false;
      validation.errors.push({
        type: 'circular_reference',
        message: 'Tokens contain circular references',
        severity: 'error'
      });
    }

    return validation;
  }

  formatSchemaErrors(errors) {
    return errors.map(error => ({
      type: 'schema',
      severity: 'error',
      message: `${error.instancePath || 'root'}: ${error.message}`,
      path: error.instancePath,
      schemaPath: error.schemaPath,
      allowedValues: error.schema?.enum,
      timestamp: new Date().toISOString()
    }));
  }

  countTokens(tokens) {
    if (!tokens.tokens) return 0;

    return Object.values(tokens.tokens).reduce((count, category) => {
      return count + (typeof category === 'object' ? Object.keys(category).length : 0);
    }, 0);
  }

  async validateBusinessRules(tokens) {
    const results = { errors: [], warnings: [] };

    for (const [category, rules] of Object.entries(this.businessRules)) {
      for (const rule of rules) {
        try {
          const ruleResults = await rule.validator(tokens, category);
          results.errors.push(...ruleResults.errors);
          results.warnings.push(...ruleResults.warnings);
        } catch (error) {
          results.errors.push({
            type: 'business-rule',
            severity: 'error',
            rule: rule.name,
            message: `Rule validation failed: ${error.message}`,
            timestamp: new Date().toISOString()
          });
        }
      }
    }

    return results;
  }

  // Color validation rules
  async validateWCAGCompliance(tokens) {
    const results = { errors: [], warnings: [] };
    const colors = tokens.tokens?.colors || {};

    for (const [name, color] of Object.entries(colors)) {
      if (color.semantic?.wcag) {
        const { level, contrastRatio } = color.semantic.wcag;

        if (level === 'FAIL') {
          results.errors.push({
            type: 'accessibility',
            severity: 'error',
            message: `Color "${name}" fails WCAG contrast requirements (${contrastRatio?.toFixed(2)})`,
            path: `tokens.colors.${name}`,
            suggestion: 'Adjust color lightness to improve contrast',
            timestamp: new Date().toISOString()
          });
        } else if (level === 'AA' && contrastRatio < 7) {
          results.warnings.push({
            type: 'accessibility',
            severity: 'warning',
            message: `Color "${name}" meets AA but not AAA standards (${contrastRatio?.toFixed(2)})`,
            path: `tokens.colors.${name}`,
            suggestion: 'Consider improving contrast for AAA compliance',
            timestamp: new Date().toISOString()
          });
        }
      }
    }

    return results;
  }

  async validateColorNaming(tokens) {
    const results = { errors: [], warnings: [] };
    const colors = tokens.tokens?.colors || {};

    const semanticPrefixes = ['primary', 'secondary', 'accent', 'neutral', 'semantic', 'surface'];
    const badPatterns = ['color1', 'color2', 'untitled', 'copy'];

    for (const [name, color] of Object.entries(colors)) {
      const lowercaseName = name.toLowerCase();

      // Check for bad naming patterns
      if (badPatterns.some(pattern => lowercaseName.includes(pattern))) {
        results.warnings.push({
          type: 'naming',
          severity: 'warning',
          message: `Color "${name}" uses generic naming`,
          path: `tokens.colors.${name}`,
          suggestion: 'Use semantic or descriptive color names',
          timestamp: new Date().toISOString()
        });
      }

      // Check for semantic prefix
      const hasSemanticPrefix = semanticPrefixes.some(prefix =>
        lowercaseName.startsWith(prefix)
      );

      if (!hasSemanticPrefix && !color.semantic?.role) {
        results.warnings.push({
          type: 'naming',
          severity: 'warning',
          message: `Color "${name}" lacks semantic context`,
          path: `tokens.colors.${name}`,
          suggestion: 'Add semantic role or use semantic naming',
          timestamp: new Date().toISOString()
        });
      }
    }

    return results;
  }

  async validateColorConsistency(tokens) {
    const results = { errors: [], warnings: [] };
    const colors = tokens.tokens?.colors || {};

    const colorsByHue = this.groupColorsByHue(colors);

    for (const [hue, hueColors] of colorsByHue.entries()) {
      if (hueColors.length < 2) continue;

      // Check for consistent saturation/lightness progression
      const saturations = hueColors.map(c => c.hsl.s).sort((a, b) => a - b);
      const lightnesses = hueColors.map(c => c.hsl.l).sort((a, b) => a - b);

      const saturationGaps = this.findInconsistentGaps(saturations);
      const lightnessGaps = this.findInconsistentGaps(lightnesses);

      if (saturationGaps.length > 0) {
        results.warnings.push({
          type: 'consistency',
          severity: 'warning',
          message: `Inconsistent saturation progression in hue ${hue}°`,
          path: `tokens.colors`,
          suggestion: 'Consider using consistent saturation steps',
          timestamp: new Date().toISOString()
        });
      }

      if (lightnessGaps.length > 0) {
        results.warnings.push({
          type: 'consistency',
          severity: 'warning',
          message: `Inconsistent lightness progression in hue ${hue}°`,
          path: `tokens.colors`,
          suggestion: 'Consider using consistent lightness steps',
          timestamp: new Date().toISOString()
        });
      }
    }

    return results;
  }

  // Typography validation rules
  async validateTypographyScale(tokens) {
    const results = { errors: [], warnings: [] };
    const typography = tokens.tokens?.typography || {};

    const fontSizes = Object.values(typography)
      .map(t => t.fontSize?.px)
      .filter(size => typeof size === 'number')
      .sort((a, b) => a - b);

    if (fontSizes.length < 2) return results;

    // Check for consistent scale ratio
    const ratios = [];
    for (let i = 1; i < fontSizes.length; i++) {
      ratios.push(fontSizes[i] / fontSizes[i - 1]);
    }

    const avgRatio = ratios.reduce((sum, ratio) => sum + ratio, 0) / ratios.length;
    const inconsistentRatios = ratios.filter(ratio =>
      Math.abs(ratio - avgRatio) > 0.3
    );

    if (inconsistentRatios.length > 0) {
      results.warnings.push({
        type: 'scale',
        severity: 'warning',
        message: 'Typography scale lacks consistency',
        path: 'tokens.typography',
        suggestion: `Consider using a consistent scale ratio (current avg: ${avgRatio.toFixed(2)})`,
        timestamp: new Date().toISOString()
      });
    }

    return results;
  }

  async validateLineHeight(tokens) {
    const results = { errors: [], warnings: [] };
    const typography = tokens.tokens?.typography || {};

    for (const [name, typo] of Object.entries(typography)) {
      const lineHeight = typo.lineHeight;

      if (lineHeight?.unitless) {
        if (lineHeight.unitless < 1.0 || lineHeight.unitless > 3.0) {
          results.warnings.push({
            type: 'typography',
            severity: 'warning',
            message: `Line height for "${name}" is outside recommended range (${lineHeight.unitless})`,
            path: `tokens.typography.${name}`,
            suggestion: 'Use line height between 1.0 and 3.0',
            timestamp: new Date().toISOString()
          });
        }
      }

      if (lineHeight?.percentage) {
        if (lineHeight.percentage < 100 || lineHeight.percentage > 300) {
          results.warnings.push({
            type: 'typography',
            severity: 'warning',
            message: `Line height percentage for "${name}" is outside recommended range`,
            path: `tokens.typography.${name}`,
            suggestion: 'Use line height between 100% and 300%',
            timestamp: new Date().toISOString()
          });
        }
      }
    }

    return results;
  }

  async validateTypographyHierarchy(tokens) {
    const results = { errors: [], warnings: [] };
    const typography = tokens.tokens?.typography || {};

    const headings = Object.values(typography)
      .filter(t => t.category === 'heading')
      .sort((a, b) => (a.fontSize?.px || 0) - (b.fontSize?.px || 0));

    if (headings.length < 3) {
      results.warnings.push({
        type: 'hierarchy',
        severity: 'warning',
        message: 'Insufficient typography hierarchy (less than 3 heading levels)',
        path: 'tokens.typography',
        suggestion: 'Consider adding more heading levels for better hierarchy',
        timestamp: new Date().toISOString()
      });
    }

    // Check for font size hierarchy
    for (let i = 1; i < headings.length; i++) {
      const current = headings[i].fontSize?.px || 0;
      const previous = headings[i - 1].fontSize?.px || 0;

      if (current <= previous) {
        results.errors.push({
          type: 'hierarchy',
          severity: 'error',
          message: 'Typography hierarchy violation: larger headings should have larger font sizes',
          path: 'tokens.typography',
          suggestion: 'Ensure heading font sizes decrease with hierarchy level',
          timestamp: new Date().toISOString()
        });
        break;
      }
    }

    return results;
  }

  // Spacing validation rules
  async validateSpacingScale(tokens) {
    const results = { errors: [], warnings: [] };
    const spacing = tokens.tokens?.spacing || {};

    const spacingValues = Object.values(spacing)
      .map(s => s.px || s.value)
      .filter(val => typeof val === 'number')
      .sort((a, b) => a - b);

    if (spacingValues.length < 3) return results;

    // Check for geometric progression (common in design systems)
    const isGeometric = this.checkGeometricProgression(spacingValues);

    if (!isGeometric) {
      results.warnings.push({
        type: 'scale',
        severity: 'warning',
        message: 'Spacing values do not follow a consistent scale',
        path: 'tokens.spacing',
        suggestion: 'Consider using a geometric progression (e.g., 4, 8, 16, 32)',
        timestamp: new Date().toISOString()
      });
    }

    return results;
  }

  async validateSpacingUsage(tokens) {
    const results = { errors: [], warnings: [] };
    const spacing = tokens.tokens?.spacing || {};

    for (const [name, space] of Object.entries(spacing)) {
      if (!space.usage || space.usage.length === 0) {
        results.warnings.push({
          type: 'usage',
          severity: 'warning',
          message: `Spacing token "${name}" lacks usage definition`,
          path: `tokens.spacing.${name}`,
          suggestion: 'Add usage array to specify intended use cases',
          timestamp: new Date().toISOString()
        });
      }
    }

    return results;
  }

  // Component validation rules
  async validateComponentCompleteness(tokens) {
    const results = { errors: [], warnings: [] };
    const components = tokens.tokens?.components || {};

    for (const [name, component] of Object.entries(components)) {
      if (!component.variants || component.variants.length === 0) {
        results.warnings.push({
          type: 'completeness',
          severity: 'warning',
          message: `Component "${name}" has no variants defined`,
          path: `tokens.components.${name}`,
          suggestion: 'Consider defining component variants',
          timestamp: new Date().toISOString()
        });
      }

      if (!component.properties || Object.keys(component.properties).length === 0) {
        results.warnings.push({
          type: 'completeness',
          severity: 'warning',
          message: `Component "${name}" has no properties defined`,
          path: `tokens.components.${name}`,
          suggestion: 'Define component properties for better documentation',
          timestamp: new Date().toISOString()
        });
      }
    }

    return results;
  }

  async validateComponentConsistency(tokens) {
    const results = { errors: [], warnings: [] };
    // Implementation would check token usage consistency across components
    return results;
  }

  // Accessibility validation
  async validateAccessibility(tokens) {
    const results = { errors: [], warnings: [] };

    // Color accessibility already handled in color rules
    // Add other accessibility checks here

    return results;
  }

  // Consistency validation
  async validateConsistency(tokens) {
    const results = { errors: [], warnings: [] };

    // Check for duplicate values
    const duplicates = this.findDuplicateValues(tokens);
    for (const duplicate of duplicates) {
      results.warnings.push({
        type: 'consistency',
        severity: 'warning',
        message: `Duplicate value found: ${duplicate.value}`,
        path: duplicate.paths.join(', '),
        suggestion: 'Consider consolidating duplicate tokens',
        timestamp: new Date().toISOString()
      });
    }

    return results;
  }

  // Helper methods
  groupColorsByHue(colors) {
    const groups = new Map();

    for (const [name, color] of Object.entries(colors)) {
      if (color.hsl?.h !== undefined) {
        const hue = Math.round(color.hsl.h / 10) * 10; // Group by 10-degree segments
        if (!groups.has(hue)) {
          groups.set(hue, []);
        }
        groups.get(hue).push({ name, ...color });
      }
    }

    return groups;
  }

  findInconsistentGaps(values) {
    if (values.length < 3) return [];

    const gaps = [];
    for (let i = 1; i < values.length; i++) {
      gaps.push(values[i] - values[i - 1]);
    }

    const avgGap = gaps.reduce((sum, gap) => sum + gap, 0) / gaps.length;
    return gaps.filter(gap => Math.abs(gap - avgGap) > avgGap * 0.5);
  }

  checkGeometricProgression(values) {
    if (values.length < 3) return true;

    const ratios = [];
    for (let i = 1; i < values.length; i++) {
      ratios.push(values[i] / values[i - 1]);
    }

    const avgRatio = ratios.reduce((sum, ratio) => sum + ratio, 0) / ratios.length;
    const variance = ratios.reduce((sum, ratio) => sum + Math.pow(ratio - avgRatio, 2), 0) / ratios.length;

    return variance < 0.5; // Threshold for acceptable variance
  }

  findDuplicateValues(tokens) {
    const valueMap = new Map();
    const duplicates = [];

    const checkCategory = (category, categoryName) => {
      for (const [name, token] of Object.entries(category)) {
        const value = this.extractComparableValue(token);
        if (value !== null) {
          const key = JSON.stringify(value);
          if (!valueMap.has(key)) {
            valueMap.set(key, []);
          }
          valueMap.get(key).push(`${categoryName}.${name}`);
        }
      }
    };

    if (tokens.tokens) {
      for (const [categoryName, category] of Object.entries(tokens.tokens)) {
        if (typeof category === 'object') {
          checkCategory(category, categoryName);
        }
      }
    }

    for (const [value, paths] of valueMap.entries()) {
      if (paths.length > 1) {
        duplicates.push({
          value: JSON.parse(value),
          paths
        });
      }
    }

    return duplicates;
  }

  extractComparableValue(token) {
    if (token.hex) return token.hex;
    if (token.value !== undefined) return token.value;
    if (token.fontSize) return token.fontSize;
    return null;
  }

  // Main validation method
  async validate(tokens, rules = {}) {
    const results = {
      valid: true,
      errors: [],
      warnings: [],
      metadata: {
        totalTokens: 0,
        validatedTokens: 0,
        timestamp: new Date().toISOString(),
        preset: this.activePreset
      }
    };

    // If rules is a string, treat it as a preset name
    if (typeof rules === 'string') {
      this.setPreset(rules);
      rules = this.getActivePreset();
    }

    // If no rules provided, use active preset
    if (Object.keys(rules).length === 0) {
      rules = this.getActivePreset();
    }

    // Count total tokens
    for (const category of Object.values(tokens)) {
      if (typeof category === 'object') {
        results.metadata.totalTokens += Object.keys(category).length;
      }
    }

    // Run color validations
    if (tokens.colors) {
      for (const rule of this.businessRules.colorRules) {
        if (rules[rule.name] === true) {
          const ruleResults = await rule.validator({ tokens });
          results.errors.push(...(ruleResults.errors || []));
          results.warnings.push(...(ruleResults.warnings || []));
        }
      }
    }

    // Run typography validations
    if (tokens.typography) {
      for (const rule of this.businessRules.typographyRules) {
        if (rules[rule.name] === true) {
          const ruleResults = await rule.validator({ tokens });
          results.errors.push(...(ruleResults.errors || []));
          results.warnings.push(...(ruleResults.warnings || []));
        }
      }
    }

    // Run spacing validations
    if (tokens.spacing) {
      for (const rule of this.businessRules.spacingRules) {
        if (rules[rule.name] === true) {
          const ruleResults = await rule.validator({ tokens });
          results.errors.push(...(ruleResults.errors || []));
          results.warnings.push(...(ruleResults.warnings || []));
        }
      }
    }

    // Run component validations
    if (tokens.components) {
      for (const rule of this.businessRules.componentRules) {
        if (rules[rule.name] === true) {
          const ruleResults = await rule.validator({ tokens });
          results.errors.push(...(ruleResults.errors || []));
          results.warnings.push(...(ruleResults.warnings || []));
        }
      }
    }

    // Set valid flag
    results.valid = results.errors.length === 0;
    results.metadata.validatedTokens = results.metadata.totalTokens - results.errors.length;
    results.metadata.rulesApplied = Object.keys(rules).filter(k => rules[k] === true).length;

    return results;
  }

  // Validate single token
  validateToken(token, rules = {}) {
    const result = {
      valid: true,
      errors: [],
      warnings: []
    };

    // Basic validation
    if (!token.name) {
      result.errors.push('Token must have a name');
      result.valid = false;
    }

    if (!token.value) {
      result.errors.push('Token must have a value');
      result.valid = false;
    }

    if (!token.type) {
      result.warnings.push('Token should have a type');
    }

    // Type-specific validation
    if (token.type === 'color') {
      if (!this.isValidColor(token.value)) {
        result.errors.push(`Invalid color value: ${token.value}`);
        result.valid = false;
      }
    } else if (token.type === 'spacing') {
      if (!this.isValidSpacing(token.value)) {
        result.errors.push(`Invalid spacing value: ${token.value}`);
        result.valid = false;
      }
    } else if (token.type === 'typography') {
      if (!token.fontSize && !token.fontFamily && !token.fontWeight) {
        result.warnings.push('Typography token should have font properties');
      }
    }

    return result;
  }

  // Helper methods for validation
  isValidColor(value) {
    if (typeof value !== 'string') return false;
    // Check hex colors
    if (/^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$/.test(value)) return true;
    // Check rgb/rgba
    if (/^rgba?\(.*\)$/.test(value)) return true;
    // Check hsl/hsla
    if (/^hsla?\(.*\)$/.test(value)) return true;
    return false;
  }

  isValidSpacing(value) {
    if (typeof value !== 'string') return false;
    // Check pixel values
    if (/^\d+(\.\d+)?px$/.test(value)) return true;
    // Check rem/em values
    if (/^\d+(\.\d+)?(rem|em)$/.test(value)) return true;
    // Check percentage
    if (/^\d+(\.\d+)?%$/.test(value)) return true;
    return false;
  }

  // Validation summary
  generateValidationSummary(results) {
    return {
      summary: {
        valid: results.valid,
        totalErrors: results.errors.length,
        totalWarnings: results.warnings.length,
        coveragePercentage: (results.metadata.validatedTokens / results.metadata.totalTokens) * 100
      },
      byCategory: this.categorizeIssues(results),
      recommendations: this.generateRecommendations(results)
    };
  }

  categorizeIssues(results) {
    const categories = {};

    [...results.errors, ...results.warnings].forEach(issue => {
      if (!categories[issue.type]) {
        categories[issue.type] = { errors: 0, warnings: 0 };
      }
      categories[issue.type][issue.severity === 'error' ? 'errors' : 'warnings']++;
    });

    return categories;
  }

  generateRecommendations(results) {
    const recommendations = [];

    const errorTypes = new Set(results.errors.map(e => e.type));

    if (errorTypes.has('accessibility')) {
      recommendations.push({
        priority: 'high',
        category: 'accessibility',
        message: 'Address color contrast issues for WCAG compliance',
        action: 'Review and adjust colors failing contrast requirements'
      });
    }

    if (errorTypes.has('hierarchy')) {
      recommendations.push({
        priority: 'high',
        category: 'typography',
        message: 'Fix typography hierarchy violations',
        action: 'Ensure font sizes decrease with heading levels'
      });
    }

    const warningTypes = new Set(results.warnings.map(w => w.type));

    if (warningTypes.has('naming')) {
      recommendations.push({
        priority: 'medium',
        category: 'naming',
        message: 'Improve token naming consistency',
        action: 'Adopt semantic naming conventions'
      });
    }

    if (warningTypes.has('scale')) {
      recommendations.push({
        priority: 'medium',
        category: 'consistency',
        message: 'Establish consistent scales',
        action: 'Use geometric progression for spacing and typography'
      });
    }

    return recommendations;
  }
}

module.exports = TokenValidator;