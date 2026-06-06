/**
 * Hook: on-component-extract
 * Triggers after a component is extracted from Figma
 * Post-processes newly extracted component data
 */
const fs = require('fs').promises;
const path = require('path');

module.exports = {
  name: 'on-component-extract',
  watch: '.design/components/**/*.json',
  debounce: 300,
  enabled: true,
  priority: 50,

  async execute(event) {
    process.stderr.write('[on-component-extract] Component extraction detected\n');

    try {
      // Read the extracted component data
      const componentPath = event.path;
      let componentData;

      try {
        const content = await fs.readFile(componentPath, 'utf8');
        componentData = JSON.parse(content);
      } catch (readError) {
        if (readError.code === 'ENOENT') {
          process.stderr.write('[on-component-extract] Component file not found (may have been removed)\n');
          return {
            success: true,
            message: 'Component file removed',
            action: 'removed'
          };
        }
        throw readError;
      }

      // Extract component metadata
      const componentId = componentData.id || path.basename(componentPath, '.json');
      const componentName = componentData.name || componentId;

      process.stderr.write(`[on-component-extract] Processing: ${componentName} (${componentId})\n`);

      // Validate component structure
      const validation = this.validateComponent(componentData);
      if (!validation.valid) {
        process.stderr.write(`[on-component-extract] Validation warnings: ${validation.warnings.join(', ')}\n`);
      }

      // Analyze component properties
      const analysis = this.analyzeComponent(componentData);

      // Log analysis summary
      process.stderr.write(`[on-component-extract] Properties: ${analysis.propertyCount}, Variants: ${analysis.variantCount}\n`);

      if (analysis.tokenDependencies.length > 0) {
        process.stderr.write(`[on-component-extract] Token dependencies: ${analysis.tokenDependencies.join(', ')}\n`);
      }

      return {
        success: true,
        message: `Processed component: ${componentName}`,
        componentId,
        componentName,
        analysis,
        validation
      };

    } catch (error) {
      process.stderr.write('[on-component-extract] Error: ' + error.message + '\n');
      return {
        success: false,
        message: error.message,
        error
      };
    }
  },

  /**
   * Validate component data structure
   * @param {Object} componentData - Extracted component data
   * @returns {Object} Validation result with valid flag and warnings
   */
  validateComponent(componentData) {
    const warnings = [];

    if (!componentData.name) {
      warnings.push('Missing component name');
    }

    if (!componentData.type) {
      warnings.push('Missing component type');
    }

    if (!componentData.properties && !componentData.variants) {
      warnings.push('No properties or variants defined');
    }

    if (componentData.styles && typeof componentData.styles !== 'object') {
      warnings.push('Invalid styles format');
    }

    return {
      valid: warnings.length === 0,
      warnings
    };
  },

  /**
   * Analyze component to extract useful metadata
   * @param {Object} componentData - Extracted component data
   * @returns {Object} Analysis results
   */
  analyzeComponent(componentData) {
    const analysis = {
      propertyCount: 0,
      variantCount: 0,
      tokenDependencies: [],
      hasChildren: false,
      complexity: 'simple'
    };

    // Count properties
    if (componentData.properties) {
      analysis.propertyCount = Object.keys(componentData.properties).length;
    }

    // Count variants
    if (componentData.variants) {
      analysis.variantCount = Array.isArray(componentData.variants)
        ? componentData.variants.length
        : Object.keys(componentData.variants).length;
    }

    // Find token dependencies in styles
    if (componentData.styles) {
      analysis.tokenDependencies = this.extractTokenReferences(componentData.styles);
    }

    // Check for children
    if (componentData.children && componentData.children.length > 0) {
      analysis.hasChildren = true;
    }

    // Determine complexity
    if (analysis.propertyCount > 10 || analysis.variantCount > 5) {
      analysis.complexity = 'complex';
    } else if (analysis.propertyCount > 5 || analysis.variantCount > 2) {
      analysis.complexity = 'moderate';
    }

    return analysis;
  },

  /**
   * Extract token references from styles object
   * @param {Object} styles - Component styles
   * @returns {string[]} Array of token names
   */
  extractTokenReferences(styles) {
    const tokens = new Set();

    const extractFromValue = (value) => {
      if (typeof value === 'string') {
        // Match token references like {colors.primary} or $colors.primary
        const tokenMatches = value.match(/[{$]([a-zA-Z0-9_.]+)[}]?/g);
        if (tokenMatches) {
          tokenMatches.forEach(match => {
            const tokenName = match.replace(/[{$}]/g, '');
            tokens.add(tokenName);
          });
        }
      } else if (typeof value === 'object' && value !== null) {
        Object.values(value).forEach(extractFromValue);
      }
    };

    extractFromValue(styles);
    return Array.from(tokens);
  }
};
