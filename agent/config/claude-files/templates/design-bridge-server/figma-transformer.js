/**
 * figma-transformer.js
 * Transforms Figma API responses to Design Bridge format
 *
 * Used by the extract-figma-mcp skill for Claude Code
 *
 * Enhanced with Defensive Enhancement System:
 * - Sync logging for all transformation operations
 * - Complexity analysis for Figma nodes
 * - Pattern compatibility checks
 * - Transformation reports for detailed metrics
 *
 * Key Principle: Make failures observable and recoverable, not silent and destructive.
 */

// =============================================================================
// DEFENSIVE ENHANCEMENT INTEGRATIONS
// =============================================================================

// Lazy-load defensive modules to avoid circular dependencies
let _syncLogger = null;
let _complexityAnalyzer = null;
let _patternCompatibility = null;
let _transformationReport = null;

function getSyncLogger() {
  if (!_syncLogger) {
    try {
      _syncLogger = require('./sync-logger.js');
    } catch (e) {
      _syncLogger = {
        createLogger: () => ({
          info: () => {},
          warn: () => {},
          error: () => {},
          debug: () => {},
          startSpan: () => 'span',
          endSpan: () => 0,
          getSummary: () => ({ counters: {} }),
          getErrors: () => [],
          getWarnings: () => []
        })
      };
    }
  }
  return _syncLogger;
}

function getComplexityAnalyzer() {
  if (!_complexityAnalyzer) {
    try {
      _complexityAnalyzer = require('./figma-complexity-analyzer.js');
    } catch (e) {
      _complexityAnalyzer = {
        analyzeNode: () => ({ complexity: 'unknown', score: 0, concerns: [] }),
        analyzeBatch: (nodes) => nodes.map(() => ({ complexity: 'unknown', score: 0, concerns: [] }))
      };
    }
  }
  return _complexityAnalyzer;
}

function getPatternCompatibility() {
  if (!_patternCompatibility) {
    try {
      _patternCompatibility = require('./pattern-compatibility.js');
    } catch (e) {
      _patternCompatibility = {
        checkCompatibility: () => ({ compatible: true, warnings: [] }),
        getFrameworkSupport: () => ({})
      };
    }
  }
  return _patternCompatibility;
}

function getTransformationReport() {
  if (!_transformationReport) {
    try {
      _transformationReport = require('./transformation-report.js');
    } catch (e) {
      _transformationReport = {
        ReportCollector: class {
          recordNode() {}
          recordWarning() {}
          recordError() {}
          recordTiming() {}
          finalize() { return { metrics: {} }; }
          getData() { return {}; }
        }
      };
    }
  }
  return _transformationReport;
}

// Module-level logger and reporter (created on first use)
let _moduleLogger = null;
let _moduleReporter = null;

function getModuleLogger() {
  if (!_moduleLogger) {
    const sl = getSyncLogger();
    _moduleLogger = sl.createLogger({ name: 'figma-transformer', output: 'memory' });
  }
  return _moduleLogger;
}

function getModuleReporter() {
  if (!_moduleReporter) {
    const tr = getTransformationReport();
    _moduleReporter = new tr.ReportCollector({ framework: 'figma', source: 'figma-mcp' });
  }
  return _moduleReporter;
}

/**
 * Figma type to Design Bridge type mapping
 */
const TYPE_MAPPING = {
  'COMPONENT': 'COMPONENT',
  'COMPONENT_SET': 'COMPONENT_SET',
  'FRAME': 'FRAME',
  'GROUP': 'GROUP',
  'TEXT': 'TEXT',
  'RECTANGLE': 'SHAPE',
  'ELLIPSE': 'SHAPE',
  'POLYGON': 'SHAPE',
  'STAR': 'SHAPE',
  'VECTOR': 'VECTOR',
  'INSTANCE': 'INSTANCE',
  'BOOLEAN_OPERATION': 'SHAPE',
  'LINE': 'SHAPE',
  'SECTION': 'SECTION'
};

/**
 * Convert RGB (0-1 range) to hex
 * @param {number} r - Red 0-1
 * @param {number} g - Green 0-1
 * @param {number} b - Blue 0-1
 * @returns {string} Hex color
 */
function rgbToHex(r, g, b) {
  const toHex = (n) => {
    const hex = Math.round(n * 255).toString(16);
    return hex.length === 1 ? '0' + hex : hex;
  };
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`.toUpperCase();
}

/**
 * Convert Figma fill to color token reference
 * @param {Object} fill - Figma fill object
 * @param {Object} styles - File styles
 * @returns {Object|string|null} Color info
 */
function extractColorFromFill(fill, styles) {
  if (!fill || fill.type !== 'SOLID') return null;

  const { r, g, b, a = 1 } = fill.color || {};
  if (r === undefined) return null;

  const hex = rgbToHex(r, g, b);

  // Check if this fill uses a style
  if (fill.boundVariables?.color) {
    const styleId = fill.boundVariables.color.id;
    if (styles && styles[styleId]) {
      return styles[styleId].name;
    }
  }

  return {
    value: hex,
    opacity: a
  };
}

/**
 * Extract typography properties from a TEXT node
 * @param {Object} node - Figma node
 * @returns {Object|null} Typography properties
 */
function extractTypography(node) {
  if (node.type !== 'TEXT') return null;

  const style = node.style || {};

  return {
    fontFamily: style.fontFamily,
    fontWeight: style.fontWeight,
    fontSize: style.fontSize,
    lineHeight: style.lineHeightPx || style.lineHeightPercent,
    letterSpacing: style.letterSpacing,
    textCase: style.textCase,
    textDecoration: style.textDecoration,
    textAlign: node.textAlignHorizontal
  };
}

/**
 * Map Figma axis alignment to CSS
 * @param {string} figmaAlign - Figma alignment value
 * @returns {string} CSS alignment
 */
function mapAxisAlignment(figmaAlign) {
  const mapping = {
    'MIN': 'flex-start',
    'CENTER': 'center',
    'MAX': 'flex-end',
    'SPACE_BETWEEN': 'space-between'
  };
  return mapping[figmaAlign] || 'flex-start';
}

/**
 * Extract layout properties from auto-layout frames
 * @param {Object} node - Figma node
 * @returns {Object|null} Layout properties
 */
function extractLayout(node) {
  if (!node.layoutMode || node.layoutMode === 'NONE') {
    return null;
  }

  return {
    direction: node.layoutMode === 'HORIZONTAL' ? 'row' : 'column',
    gap: node.itemSpacing || 0,
    padding: {
      top: node.paddingTop || 0,
      right: node.paddingRight || 0,
      bottom: node.paddingBottom || 0,
      left: node.paddingLeft || 0
    },
    mainAxisSizing: node.primaryAxisSizingMode,
    crossAxisSizing: node.counterAxisSizingMode,
    mainAxisAlignment: mapAxisAlignment(node.primaryAxisAlignItems),
    crossAxisAlignment: mapAxisAlignment(node.counterAxisAlignItems)
  };
}

/**
 * Extract effects (shadows, blur)
 * @param {Array} effects - Figma effects array
 * @returns {Array} Transformed effects
 */
function extractEffects(effects) {
  if (!effects || effects.length === 0) return [];

  return effects.filter(e => e.visible !== false).map(effect => {
    switch (effect.type) {
      case 'DROP_SHADOW':
      case 'INNER_SHADOW':
        return {
          type: effect.type === 'DROP_SHADOW' ? 'dropShadow' : 'innerShadow',
          color: effect.color ? rgbToHex(effect.color.r, effect.color.g, effect.color.b) : '#000000',
          opacity: effect.color?.a || 1,
          x: effect.offset?.x || 0,
          y: effect.offset?.y || 0,
          blur: effect.radius || 0,
          spread: effect.spread || 0
        };
      case 'LAYER_BLUR':
      case 'BACKGROUND_BLUR':
        return {
          type: 'blur',
          radius: effect.radius || 0
        };
      default:
        return { type: effect.type };
    }
  });
}

/**
 * Extract variant properties from COMPONENT_SET
 * @param {Object} node - Figma node
 * @returns {Array|null} Variant properties
 */
function extractVariantProperties(node) {
  if (node.type !== 'COMPONENT_SET') return null;

  const properties = node.componentPropertyDefinitions || {};
  const variants = [];

  for (const [propName, propDef] of Object.entries(properties)) {
    if (propDef.type === 'VARIANT') {
      variants.push({
        name: propName,
        values: propDef.variantOptions || [],
        defaultValue: propDef.defaultValue
      });
    }
  }

  return variants.length > 0 ? variants : null;
}

/**
 * Extract interactive states from component variant naming
 * @param {Object} node - Figma node
 * @returns {Object|null} Interactive states
 */
function extractInteractiveStates(node) {
  if (node.type !== 'COMPONENT_SET') return null;

  const variants = extractVariantProperties(node);
  if (!variants) return null;

  const interactiveStates = {};

  // Common interactive state patterns
  const statePatterns = {
    'State': ['default', 'hover', 'pressed', 'active', 'focus', 'disabled'],
    'state': ['default', 'hover', 'pressed', 'active', 'focus', 'disabled'],
    'Status': ['default', 'hover', 'pressed', 'active', 'focus', 'disabled']
  };

  for (const variant of variants) {
    const patternValues = statePatterns[variant.name];
    if (patternValues) {
      const matchedStates = variant.values.filter(v =>
        patternValues.some(p => v.toLowerCase().includes(p))
      );
      if (matchedStates.length > 0) {
        interactiveStates[variant.name] = {
          values: variant.values,
          detectedStates: matchedStates
        };
      }
    }
  }

  return Object.keys(interactiveStates).length > 0 ? interactiveStates : null;
}

/**
 * Main transformer function
 * @param {Object} node - Figma node
 * @param {Object} fileStyles - File styles
 * @param {Object} options - Transform options
 * @returns {Object} Transformed node
 */
function transformFigmaNode(node, fileStyles = {}, options = {}) {
  const logger = getModuleLogger();
  const reporter = getModuleReporter();

  const {
    fileKey,
    extractedAt = new Date().toISOString(),
    depth = 0,
    maxDepth = 10,
    enableComplexityAnalysis = true,
    enablePatternCheck = true,
    targetFramework = 'react'
  } = options;

  // Start timing span at root level
  const isRootCall = depth === 0;
  const spanId = isRootCall ? logger.startSpan('transformFigmaNode') : null;

  if (isRootCall) {
    logger.info(`Transforming Figma node: ${node.name || node.id}`, {
      nodeId: node.id,
      nodeType: node.type,
      maxDepth,
      targetFramework
    });
  }

  // Run complexity analysis if enabled and at root
  let complexityResult = null;
  if (isRootCall && enableComplexityAnalysis) {
    try {
      const analyzer = getComplexityAnalyzer();
      complexityResult = analyzer.analyzeNode(node);
      logger.debug('Complexity analysis result', {
        nodeId: node.id,
        complexity: complexityResult.complexity,
        score: complexityResult.score
      });

      // Warn about high complexity
      if (complexityResult.complexity === 'high' || complexityResult.complexity === 'extreme') {
        logger.warn(`High complexity node detected: ${node.name}`, {
          nodeId: node.id,
          complexity: complexityResult.complexity,
          concerns: complexityResult.concerns
        });
        reporter.recordWarning(`High complexity: ${complexityResult.complexity}`, {
          nodeId: node.id,
          nodeName: node.name,
          concerns: complexityResult.concerns
        });
      }
    } catch (e) {
      logger.debug('Complexity analysis unavailable', { error: e.message });
    }
  }

  // Run pattern compatibility check if enabled and at root
  let compatibilityResult = null;
  if (isRootCall && enablePatternCheck) {
    try {
      const patternChecker = getPatternCompatibility();
      compatibilityResult = patternChecker.checkCompatibility(node.type, targetFramework);

      if (!compatibilityResult.compatible) {
        logger.warn(`Pattern compatibility issue for ${node.type} -> ${targetFramework}`, {
          nodeId: node.id,
          warnings: compatibilityResult.warnings
        });
        compatibilityResult.warnings.forEach(warning => {
          reporter.recordWarning(warning, { nodeId: node.id, framework: targetFramework });
        });
      }
    } catch (e) {
      logger.debug('Pattern compatibility check unavailable', { error: e.message });
    }
  }

  // Build token dependencies
  const tokenDependencies = {
    colors: [],
    typography: [],
    spacing: [],
    effects: [],
    borderRadius: []
  };

  // Extract colors from fills
  if (node.fills && Array.isArray(node.fills)) {
    node.fills.forEach(fill => {
      const color = extractColorFromFill(fill, fileStyles);
      if (color && typeof color === 'string') {
        tokenDependencies.colors.push(color);
      }
    });
  }

  // Extract border radius
  if (node.cornerRadius) {
    tokenDependencies.borderRadius.push(`${node.cornerRadius}px`);
  }

  // Extract effects
  const effects = extractEffects(node.effects);
  if (effects.length > 0) {
    tokenDependencies.effects = effects;
  }

  // Build the transformed component
  const transformed = {
    id: `figma-${node.id.replace(':', '-')}`,
    figmaId: node.id,
    name: node.name,
    type: TYPE_MAPPING[node.type] || node.type,
    description: node.description || '',

    source: {
      type: 'figma-mcp',
      fileKey: fileKey,
      nodeId: node.id,
      extractedAt: extractedAt,
      figmaType: node.type
    },

    dimensions: node.absoluteBoundingBox ? {
      width: node.absoluteBoundingBox.width,
      height: node.absoluteBoundingBox.height
    } : null,

    layout: extractLayout(node),

    tokenDependencies: tokenDependencies,

    // Typography for TEXT nodes
    typography: extractTypography(node),

    // Variant properties for COMPONENT_SET
    variantProperties: extractVariantProperties(node),

    // Interactive states detected from naming
    interactiveStates: extractInteractiveStates(node),

    // Original Figma properties (for optimizer reference)
    figmaProperties: {
      fills: node.fills,
      strokes: node.strokes,
      effects: node.effects,
      cornerRadius: node.cornerRadius,
      opacity: node.opacity,
      blendMode: node.blendMode,
      constraints: node.constraints
    }
  };

  // Recursively transform children
  if (node.children && depth < maxDepth) {
    transformed.children = node.children.map(child =>
      transformFigmaNode(child, fileStyles, {
        ...options,
        depth: depth + 1
      })
    );

    // Aggregate token dependencies from children
    transformed.children.forEach(child => {
      if (child.tokenDependencies) {
        Object.keys(tokenDependencies).forEach(key => {
          if (Array.isArray(child.tokenDependencies[key])) {
            tokenDependencies[key].push(...child.tokenDependencies[key]);
          }
        });
      }
    });

    // Deduplicate
    Object.keys(tokenDependencies).forEach(key => {
      if (Array.isArray(tokenDependencies[key])) {
        tokenDependencies[key] = [...new Set(tokenDependencies[key].filter(v => typeof v === 'string'))];
      }
    });
  }

  // Add defensive enhancement metadata at root level
  if (isRootCall) {
    transformed.defensiveMetadata = {
      complexityAnalysis: complexityResult,
      patternCompatibility: compatibilityResult,
      targetFramework: targetFramework
    };

    // Record successful transformation in metrics
    reporter.recordNode(
      { id: node.id, type: node.type, name: node.name },
      { status: 'success', childCount: transformed.children?.length || 0 }
    );

    // End timing span
    if (spanId) {
      const duration = logger.endSpan(spanId);
      reporter.recordTiming('transformFigmaNode', duration, {
        nodeId: node.id,
        nodeType: node.type,
        childCount: transformed.children?.length || 0
      });

      logger.info(`Transformation complete for: ${node.name || node.id}`, {
        nodeId: node.id,
        duration,
        childCount: transformed.children?.length || 0
      });
    }
  }

  return transformed;
}

/**
 * Transform complete MCP response
 * @param {Object} mcpResponse - MCP tool response
 * @param {string} fileKey - Figma file key
 * @param {Object} options - Transform options
 * @param {string} options.targetFramework - Target framework (default: 'react')
 * @param {boolean} options.enableComplexityAnalysis - Enable complexity analysis (default: true)
 * @param {boolean} options.enablePatternCheck - Enable pattern compatibility check (default: true)
 * @returns {Array} Transformed nodes
 */
function transformMcpResponse(mcpResponse, fileKey, options = {}) {
  const logger = getModuleLogger();
  const reporter = getModuleReporter();
  const spanId = logger.startSpan('transformMcpResponse');

  const extractedAt = new Date().toISOString();
  const results = [];

  logger.info('Transforming MCP response', {
    fileKey,
    fileName: mcpResponse.name,
    hasNodes: !!mcpResponse.nodes,
    hasDocument: !!mcpResponse.document
  });

  // Get styles from response
  const fileStyles = mcpResponse.styles || {};

  // Merge options with defaults
  const transformOptions = {
    fileKey,
    extractedAt,
    enableComplexityAnalysis: options.enableComplexityAnalysis !== false,
    enablePatternCheck: options.enablePatternCheck !== false,
    targetFramework: options.targetFramework || 'react'
  };

  // Process each requested node
  if (mcpResponse.nodes) {
    const nodeCount = Object.keys(mcpResponse.nodes).length;
    logger.info(`Processing ${nodeCount} nodes from MCP response`, { nodeCount });

    for (const [nodeId, nodeData] of Object.entries(mcpResponse.nodes)) {
      if (nodeData.document) {
        try {
          const transformed = transformFigmaNode(nodeData.document, fileStyles, transformOptions);

          // Add file-level metadata
          transformed.fileMetadata = {
            fileName: mcpResponse.name,
            lastModified: mcpResponse.lastModified
          };

          results.push(transformed);
        } catch (error) {
          logger.error(`Failed to transform node: ${nodeId}`, {
            nodeId,
            error: error.message
          });
          reporter.recordError(error, { nodeId, phase: 'transformation' });
        }
      }
    }
  }

  // Handle single document response (from get_file)
  if (mcpResponse.document && !mcpResponse.nodes) {
    try {
      const transformed = transformFigmaNode(mcpResponse.document, fileStyles, transformOptions);
      transformed.fileMetadata = {
        fileName: mcpResponse.name,
        lastModified: mcpResponse.lastModified
      };
      results.push(transformed);
    } catch (error) {
      logger.error('Failed to transform document', {
        error: error.message
      });
      reporter.recordError(error, { phase: 'document-transformation' });
    }
  }

  // End timing and log results
  const duration = logger.endSpan(spanId);
  reporter.recordTiming('transformMcpResponse', duration, {
    fileKey,
    resultCount: results.length
  });

  logger.info('MCP response transformation complete', {
    fileKey,
    resultCount: results.length,
    duration
  });

  return results;
}

/**
 * Transform Figma styles to Design Bridge token format
 * @param {Object} stylesResponse - get_file_styles response
 * @returns {Object} Transformed styles
 */
function transformStyles(stylesResponse) {
  const tokens = {
    colors: {},
    typography: {},
    effects: {}
  };

  if (!stylesResponse || !stylesResponse.meta || !stylesResponse.meta.styles) {
    return tokens;
  }

  for (const style of stylesResponse.meta.styles) {
    switch (style.style_type) {
      case 'FILL':
        tokens.colors[style.name] = {
          description: style.description,
          styleKey: style.key,
          nodeId: style.node_id
        };
        break;
      case 'TEXT':
        tokens.typography[style.name] = {
          description: style.description,
          styleKey: style.key,
          nodeId: style.node_id
        };
        break;
      case 'EFFECT':
        tokens.effects[style.name] = {
          description: style.description,
          styleKey: style.key,
          nodeId: style.node_id
        };
        break;
    }
  }

  return tokens;
}

/**
 * Transform Figma components list to registry entries
 * @param {Object} componentsResponse - get_file_components response
 * @param {string} fileKey - Figma file key
 * @returns {Array} Registry entries
 */
function transformComponentsList(componentsResponse, fileKey) {
  const entries = [];

  if (!componentsResponse || !componentsResponse.meta || !componentsResponse.meta.components) {
    return entries;
  }

  for (const component of componentsResponse.meta.components) {
    entries.push({
      id: `figma-${component.node_id.replace(':', '-')}`,
      name: component.name,
      description: component.description,
      figmaKey: component.key,
      figmaNodeId: component.node_id,
      containingFrame: component.containing_frame,
      source: {
        type: 'figma-mcp',
        fileKey: fileKey,
        nodeId: component.node_id
      }
    });
  }

  return entries;
}

// =============================================================================
// DEFENSIVE ENHANCEMENT UTILITIES
// =============================================================================

/**
 * Get the current transformation report from the module reporter
 * @returns {Object} Report data with metrics, warnings, errors
 */
function getTransformationReportData() {
  const reporter = getModuleReporter();
  return reporter.finalize();
}

/**
 * Get the current log summary from the module logger
 * @returns {Object} Log summary with counters, errors, warnings
 */
function getLogSummary() {
  const logger = getModuleLogger();
  return {
    summary: logger.getSummary(),
    errors: logger.getErrors(),
    warnings: logger.getWarnings()
  };
}

/**
 * Reset the module-level logger and reporter
 * Useful for starting fresh in a new transformation session
 */
function resetDefensiveState() {
  _moduleLogger = null;
  _moduleReporter = null;
}

/**
 * Create a new transformer instance with isolated logging/reporting
 * @param {Object} options - Options
 * @param {string} options.sessionName - Session name for logging
 * @returns {Object} Transformer instance with isolated state
 */
function createTransformer(options = {}) {
  const sl = getSyncLogger();
  const tr = getTransformationReport();

  const sessionLogger = sl.createLogger({
    name: options.sessionName || 'figma-transformer-session',
    output: 'memory'
  });

  const sessionReporter = new tr.ReportCollector({
    framework: 'figma',
    source: 'figma-mcp'
  });

  return {
    /**
     * Transform a Figma node with isolated logging
     */
    transformNode: (node, fileStyles = {}, transformOptions = {}) => {
      // Use the main function but capture logs separately
      const result = transformFigmaNode(node, fileStyles, transformOptions);
      sessionLogger.info('Node transformed', {
        nodeId: node.id,
        nodeName: node.name
      });
      sessionReporter.recordNode(
        { id: node.id, type: node.type, name: node.name },
        { status: 'success' }
      );
      return result;
    },

    /**
     * Transform an MCP response with isolated logging
     */
    transformResponse: (mcpResponse, fileKey, transformOptions = {}) => {
      sessionLogger.info('Starting MCP response transformation', { fileKey });
      const results = transformMcpResponse(mcpResponse, fileKey, transformOptions);
      sessionLogger.info('MCP response transformation complete', {
        fileKey,
        resultCount: results.length
      });
      return results;
    },

    /**
     * Get this session's report data
     */
    getReport: () => sessionReporter.finalize(),

    /**
     * Get this session's log summary
     */
    getLogSummary: () => ({
      summary: sessionLogger.getSummary(),
      errors: sessionLogger.getErrors(),
      warnings: sessionLogger.getWarnings()
    })
  };
}

module.exports = {
  // Core transformation functions
  transformFigmaNode,
  transformMcpResponse,
  transformStyles,
  transformComponentsList,

  // Extraction utilities
  extractColorFromFill,
  extractTypography,
  extractLayout,
  extractEffects,
  extractVariantProperties,
  extractInteractiveStates,

  // Constants
  TYPE_MAPPING,
  rgbToHex,

  // Defensive enhancement utilities
  getTransformationReportData,
  getLogSummary,
  resetDefensiveState,
  createTransformer
};
