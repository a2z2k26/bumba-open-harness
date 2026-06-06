/**
 * extract-figma-mcp.js
 * Skill wrapper for Figma MCP extraction
 *
 * This module extracts design components from Figma using MCP Server tools
 * without requiring the Figma Plugin to be running.
 */

const fs = require('fs');
const path = require('path');

// Import utilities from @design-bridge/server
const { parseFigmaUrl } = require('../../packages/@design-bridge/server/figma-url-parser');
const { transformMcpResponse } = require('../../packages/@design-bridge/server/figma-transformer');

// Phase 2: Auto-registration support (Two-State Architecture)
const { AutoRegistrar } = require('../../packages/@design-bridge/server/auto-registrar');

/**
 * Main extraction function
 * @param {Object} options - Extraction options
 * @param {string} options.url - Figma URL to extract from
 * @param {string} options.projectRoot - Project root directory
 * @param {Object} options.mcpClient - MCP client for tool calls
 * @param {Object} options.config - Additional configuration
 * @returns {Object} Extraction result
 */
async function extractFromFigmaMcp(options) {
  const {
    url,
    projectRoot = process.cwd(),
    mcpClient,
    config = {}
  } = options;

  const startTime = Date.now();
  const log = [];

  try {
    // Step 1: Parse URL
    log.push('Parsing Figma URL...');
    const parsed = parseFigmaUrl(url);

    if (!parsed.valid) {
      throw new Error(`Invalid Figma URL: ${parsed.error}`);
    }

    const { fileKey, nodeId } = parsed;
    log.push(`✓ Parsed: fileKey=${fileKey}, nodeId=${nodeId || 'file-level'}`);

    // Step 2: Fetch Node Data
    log.push('Fetching node data via MCP...');

    let nodeResponse;
    if (nodeId) {
      nodeResponse = await mcpClient.call('mcp__mcp-figma__get_file_nodes', {
        fileKey: fileKey,
        node_ids: [nodeId],
        depth: config.depth || 4
      });
    } else {
      nodeResponse = await mcpClient.call('mcp__mcp-figma__get_file', {
        fileKey: fileKey,
        depth: config.depth || 2
      });
    }

    if (!nodeResponse) {
      throw new Error('No response from Figma MCP');
    }

    log.push(`✓ Fetched node data: "${nodeResponse.name}"`);

    // Step 3: Fetch Styles
    log.push('Fetching file styles...');

    let stylesResponse;
    try {
      stylesResponse = await mcpClient.call('mcp__mcp-figma__get_file_styles', {
        fileKey: fileKey
      });
      const styleCount = stylesResponse?.meta?.styles?.length || 0;
      log.push(`✓ Fetched ${styleCount} styles`);
    } catch (styleError) {
      log.push(`⚠ Could not fetch styles: ${styleError.message}`);
      stylesResponse = { meta: { styles: [] } };
    }

    // Step 4: Transform
    log.push('Transforming to Design Bridge format...');

    const components = transformMcpResponse(nodeResponse, fileKey);

    if (components.length === 0) {
      throw new Error('No components found in response');
    }

    log.push(`✓ Transformed ${components.length} component(s)`);

    // Step 5: Detect Interactive States
    log.push('Detecting interactive states...');

    for (const component of components) {
      if (component.type === 'COMPONENT_SET' && component.children) {
        const states = detectInteractiveStates(component);
        if (Object.keys(states).length > 0) {
          component.interactiveStates = states;
          log.push(`✓ Detected states: ${Object.keys(states).join(', ')}`);
        }
      }
    }

    // Step 6: Write Output
    log.push('Writing source files...');

    const designDir = path.join(projectRoot, '.design');
    const sourceDir = path.join(designDir, 'source', 'components');

    // Ensure directories exist
    if (!fs.existsSync(sourceDir)) {
      fs.mkdirSync(sourceDir, { recursive: true });
    }

    const writtenFiles = [];
    for (const component of components) {
      const fileName = `${component.name.toLowerCase().replace(/\s+/g, '-')}.json`;
      const filePath = path.join(sourceDir, fileName);

      fs.writeFileSync(filePath, JSON.stringify(component, null, 2));
      writtenFiles.push(filePath);
      log.push(`✓ Written: ${path.relative(projectRoot, filePath)}`);
    }

    // Step 7: Auto-register components (Phase 2: Two-State Architecture)
    log.push('Registering components...');

    const autoRegistrar = new AutoRegistrar({
      projectPath: projectRoot,
      autoRegisterOnImport: true,
      emitEvents: false // No events needed for batch extraction
    });

    const registrationResults = [];
    for (const component of components) {
      try {
        const relativePath = path.relative(projectRoot, path.join(sourceDir, `${component.name.toLowerCase().replace(/\s+/g, '-')}.json`));

        const result = await autoRegistrar.registerComponent(
          {
            name: component.name,
            type: component.type,
            variants: component.variants || [],
            props: component.props || [],
            tokenDependencies: component.tokenDependencies || {},
            interactiveStates: component.interactiveStates || {},
            figmaId: component.figmaId,
            figmaUrl: url
          },
          {
            type: 'figma-mcp',
            projectPath: projectRoot,
            fileKey: fileKey,
            nodeId: component.figmaId,
            figmaModifiedAt: component.lastModified || null,
            rawDataPath: relativePath
          }
        );

        registrationResults.push(result);
        log.push(`✓ Registered: ${result.id} (${result.isNew ? 'new' : 'updated'})`);
      } catch (regError) {
        log.push(`⚠ Registration failed for ${component.name}: ${regError.message}`);
      }
    }

    log.push(`✓ Registry updated with ${registrationResults.length} component(s)`);

    const duration = Date.now() - startTime;

    return {
      success: true,
      components: components.map((c, i) => ({
        // Use actual registered ID from AutoRegistrar when available
        id: registrationResults[i]?.id || `figma-mcp-${c.figmaId.replace(':', '-')}`,
        name: c.name,
        type: c.type,
        tokenCount: {
          colors: c.tokenDependencies?.colors?.length || 0,
          typography: c.tokenDependencies?.typography?.length || 0
        },
        hasStates: Object.keys(c.interactiveStates || {}).length > 0,
        registered: registrationResults[i]?.success || false,
        isNew: registrationResults[i]?.isNew || false
      })),
      files: writtenFiles,
      duration: duration,
      log: log
    };

  } catch (error) {
    return {
      success: false,
      error: error.message,
      log: log
    };
  }
}

/**
 * Detect interactive states from COMPONENT_SET variants
 * @param {Object} componentSet - Transformed COMPONENT_SET
 * @returns {Object} Detected interactive states with style diffs
 */
function detectInteractiveStates(componentSet) {
  const states = {};

  if (!componentSet.children) return states;

  // Find variants by analyzing names
  const variants = componentSet.children;

  // Look for state-related naming patterns
  const statePatterns = {
    hover: /(?:state=hover|hover|:hover)/i,
    pressed: /(?:state=pressed|pressed|active|:active)/i,
    focused: /(?:state=focus|focus|focused|:focus)/i,
    disabled: /(?:state=disabled|disabled)/i
  };

  // Find default variant
  const defaultVariant = variants.find(v =>
    /(?:state=default|default)/i.test(v.name) ||
    variants.indexOf(v) === 0
  );

  if (!defaultVariant) return states;

  // Compare other variants to default
  for (const variant of variants) {
    for (const [stateName, pattern] of Object.entries(statePatterns)) {
      if (pattern.test(variant.name) && variant !== defaultVariant) {
        states[stateName] = diffVariantStyles(defaultVariant, variant);
      }
    }
  }

  return states;
}

/**
 * Compare two variants and return style differences
 * @param {Object} defaultVariant - Default state variant
 * @param {Object} stateVariant - Alternative state variant
 * @returns {Object} Style differences
 */
function diffVariantStyles(defaultVariant, stateVariant) {
  const diff = {};

  // Compare fills
  if (JSON.stringify(defaultVariant.figmaProperties?.fills) !==
      JSON.stringify(stateVariant.figmaProperties?.fills)) {
    diff.fills = stateVariant.figmaProperties?.fills;
  }

  // Compare effects
  if (JSON.stringify(defaultVariant.figmaProperties?.effects) !==
      JSON.stringify(stateVariant.figmaProperties?.effects)) {
    diff.effects = stateVariant.figmaProperties?.effects;
  }

  // Compare opacity
  if (defaultVariant.figmaProperties?.opacity !== stateVariant.figmaProperties?.opacity) {
    diff.opacity = stateVariant.figmaProperties?.opacity;
  }

  // Compare stroke
  if (JSON.stringify(defaultVariant.figmaProperties?.strokes) !==
      JSON.stringify(stateVariant.figmaProperties?.strokes)) {
    diff.strokes = stateVariant.figmaProperties?.strokes;
  }

  return diff;
}

/**
 * Format extraction result for display
 * @param {Object} result - Extraction result
 * @returns {string} Formatted output
 */
function formatExtractionResult(result) {
  if (!result.success) {
    return `Extraction failed: ${result.error}\n\nLog:\n${result.log.join('\n')}`;
  }

  const lines = [
    'Extraction complete!',
    '',
    `Components: ${result.components.length}`,
  ];

  for (const comp of result.components) {
    lines.push(`  - ${comp.name} (${comp.type})`);
    lines.push(`    Tokens: ${comp.tokenCount.colors} colors, ${comp.tokenCount.typography} typography`);
    if (comp.hasStates) {
      lines.push('    Has interactive states');
    }
  }

  lines.push('');
  lines.push(`Duration: ${result.duration}ms`);
  lines.push('');
  lines.push('Log:');
  result.log.forEach(l => lines.push(`  ${l}`));

  return lines.join('\n');
}

module.exports = {
  extractFromFigmaMcp,
  detectInteractiveStates,
  diffVariantStyles,
  formatExtractionResult
};
