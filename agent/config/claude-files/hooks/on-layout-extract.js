/**
 * Hook: on-layout-extract
 * Triggers after a layout is extracted from Figma
 * Post-processes newly extracted layout data
 */
const fs = require('fs').promises;
const path = require('path');

module.exports = {
  name: 'on-layout-extract',
  watch: '.design/layouts/**/*.json',
  debounce: 300,
  enabled: true,
  priority: 50,

  async execute(event) {
    process.stderr.write('[on-layout-extract] Layout extraction detected\n');

    try {
      // Read the extracted layout data
      const layoutPath = event.path;
      let layoutData;

      try {
        const content = await fs.readFile(layoutPath, 'utf8');
        layoutData = JSON.parse(content);
      } catch (readError) {
        if (readError.code === 'ENOENT') {
          process.stderr.write('[on-layout-extract] Layout file not found (may have been removed)\n');
          return {
            success: true,
            message: 'Layout file removed',
            action: 'removed'
          };
        }
        throw readError;
      }

      // Extract layout metadata
      const layoutId = layoutData.id || path.basename(layoutPath, '.json');
      const layoutName = layoutData.name || layoutId;

      process.stderr.write(`[on-layout-extract] Processing: ${layoutName} (${layoutId})\n`);

      // Validate layout structure
      const validation = this.validateLayout(layoutData);
      if (!validation.valid) {
        process.stderr.write(`[on-layout-extract] Validation warnings: ${validation.warnings.join(', ')}\n`);
      }

      // Analyze layout
      const analysis = this.analyzeLayout(layoutData);

      // Log analysis summary
      process.stderr.write(`[on-layout-extract] Type: ${analysis.layoutType}, Sections: ${analysis.sectionCount}\n`);

      if (analysis.componentReferences.length > 0) {
        process.stderr.write(`[on-layout-extract] Component references: ${analysis.componentReferences.length}\n`);
      }

      return {
        success: true,
        message: `Processed layout: ${layoutName}`,
        layoutId,
        layoutName,
        analysis,
        validation
      };

    } catch (error) {
      process.stderr.write('[on-layout-extract] Error: ' + error.message + '\n');
      return {
        success: false,
        message: error.message,
        error
      };
    }
  },

  /**
   * Validate layout data structure
   * @param {Object} layoutData - Extracted layout data
   * @returns {Object} Validation result with valid flag and warnings
   */
  validateLayout(layoutData) {
    const warnings = [];

    if (!layoutData.name) {
      warnings.push('Missing layout name');
    }

    if (!layoutData.type && !layoutData.layoutType) {
      warnings.push('Missing layout type');
    }

    if (!layoutData.children && !layoutData.sections) {
      warnings.push('No children or sections defined');
    }

    if (!layoutData.constraints && !layoutData.layout) {
      warnings.push('No layout constraints defined');
    }

    return {
      valid: warnings.length === 0,
      warnings
    };
  },

  /**
   * Analyze layout to extract useful metadata
   * @param {Object} layoutData - Extracted layout data
   * @returns {Object} Analysis results
   */
  analyzeLayout(layoutData) {
    const analysis = {
      layoutType: 'unknown',
      sectionCount: 0,
      componentReferences: [],
      responsiveBreakpoints: [],
      constraints: {},
      depth: 0
    };

    // Determine layout type
    if (layoutData.layoutType) {
      analysis.layoutType = layoutData.layoutType;
    } else if (layoutData.type) {
      analysis.layoutType = layoutData.type;
    } else if (layoutData.layout) {
      analysis.layoutType = layoutData.layout.mode || 'auto';
    }

    // Count sections
    if (layoutData.sections) {
      analysis.sectionCount = layoutData.sections.length;
    } else if (layoutData.children) {
      analysis.sectionCount = layoutData.children.filter(c =>
        c.type === 'FRAME' || c.type === 'SECTION' || c.type === 'GROUP'
      ).length;
    }

    // Find component references
    analysis.componentReferences = this.findComponentReferences(layoutData);

    // Extract responsive breakpoints if available
    if (layoutData.breakpoints) {
      analysis.responsiveBreakpoints = layoutData.breakpoints;
    }

    // Extract constraints
    if (layoutData.constraints) {
      analysis.constraints = layoutData.constraints;
    } else if (layoutData.layout) {
      analysis.constraints = {
        mode: layoutData.layout.mode,
        direction: layoutData.layout.primaryAxisSizingMode,
        alignment: layoutData.layout.primaryAxisAlignItems
      };
    }

    // Calculate depth
    analysis.depth = this.calculateLayoutDepth(layoutData);

    return analysis;
  },

  /**
   * Find component references in layout
   * @param {Object} layoutData - Layout data
   * @returns {string[]} Array of component IDs/names
   */
  findComponentReferences(layoutData) {
    const references = new Set();

    const traverse = (node) => {
      if (!node) return;

      // Check if node is a component instance
      if (node.type === 'INSTANCE' || node.componentId || node.componentKey) {
        const ref = node.componentId || node.componentKey || node.name;
        if (ref) references.add(ref);
      }

      // Check children
      if (node.children && Array.isArray(node.children)) {
        node.children.forEach(traverse);
      }

      // Check sections
      if (node.sections && Array.isArray(node.sections)) {
        node.sections.forEach(traverse);
      }
    };

    traverse(layoutData);
    return Array.from(references);
  },

  /**
   * Calculate the maximum nesting depth of the layout
   * @param {Object} node - Layout node
   * @param {number} currentDepth - Current depth level
   * @returns {number} Maximum depth
   */
  calculateLayoutDepth(node, currentDepth = 0) {
    if (!node) return currentDepth;

    let maxDepth = currentDepth;

    const children = node.children || node.sections || [];
    for (const child of children) {
      const childDepth = this.calculateLayoutDepth(child, currentDepth + 1);
      maxDepth = Math.max(maxDepth, childDepth);
    }

    return maxDepth;
  }
};
