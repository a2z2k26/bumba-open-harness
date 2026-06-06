/**
 * figma-style-extractor.js
 * Extract design tokens from Figma styles
 *
 * This module provides detailed token extraction from Figma styles,
 * complementing the basic style transformation in figma-transformer.js
 *
 * v2.0.0: Added unified registry integration via AutoRegistrar
 * - Tokens are now registered in .design/registries/tokens.json
 * - Enables O(1) token lookups and dependency tracking
 */

const fs = require('fs');
const path = require('path');

// Lazy-load AutoRegistrar to avoid circular dependencies
let _autoRegistrar = null;
function getAutoRegistrar(projectPath) {
  if (!_autoRegistrar) {
    const { AutoRegistrar } = require('./auto-registrar');
    _autoRegistrar = new AutoRegistrar({ projectPath });
  }
  return _autoRegistrar;
}

/**
 * Extract and transform Figma styles to Design Bridge tokens
 * @param {Object} mcpClient - MCP client for API calls
 * @param {string} fileKey - Figma file key
 * @param {string} outputDir - Output directory for token files
 * @returns {Object} Extraction results
 */
async function extractFigmaStyles(mcpClient, fileKey, outputDir) {
  const results = {
    colors: [],
    typography: [],
    effects: [],
    extracted: 0,
    errors: []
  };

  try {
    // Fetch styles from file
    const stylesResponse = await mcpClient.call('mcp__mcp-figma__get_file_styles', {
      fileKey: fileKey
    });

    const styles = stylesResponse?.meta?.styles || [];

    for (const styleMeta of styles) {
      try {
        switch (styleMeta.style_type) {
          case 'FILL':
            results.colors.push(transformColorStyle(styleMeta));
            results.extracted++;
            break;
          case 'TEXT':
            results.typography.push(transformTextStyle(styleMeta));
            results.extracted++;
            break;
          case 'EFFECT':
            results.effects.push(transformEffectStyle(styleMeta));
            results.extracted++;
            break;
        }
      } catch (err) {
        results.errors.push({ styleId: styleMeta.node_id, error: err.message });
      }
    }

    // Write token files
    if (outputDir) {
      await writeTokenFiles(results, outputDir);
    }

    return results;

  } catch (error) {
    results.errors.push({ error: error.message });
    return results;
  }
}

/**
 * Transform Figma color style to Design Bridge token
 * @param {Object} styleMeta - Figma style metadata
 * @returns {Object} Design Bridge color token
 */
function transformColorStyle(styleMeta) {
  const parsed = parseTokenPath(styleMeta.name);

  return {
    id: `color-${styleMeta.node_id.replace(':', '-')}`,
    name: styleMeta.name,
    category: 'colors',
    path: parsed.path,
    group: parsed.group,
    variant: parsed.variant,
    description: styleMeta.description || '',
    source: {
      type: 'figma-mcp',
      styleKey: styleMeta.key,
      nodeId: styleMeta.node_id,
      extractedAt: new Date().toISOString()
    },
    // Note: Full color value requires get_file_nodes call with the style node
    figmaStyleKey: styleMeta.key
  };
}

/**
 * Transform Figma text style to Design Bridge token
 * @param {Object} styleMeta - Figma style metadata
 * @returns {Object} Design Bridge typography token
 */
function transformTextStyle(styleMeta) {
  const parsed = parseTokenPath(styleMeta.name);

  return {
    id: `typography-${styleMeta.node_id.replace(':', '-')}`,
    name: styleMeta.name,
    category: 'typography',
    path: parsed.path,
    group: parsed.group,
    variant: parsed.variant,
    description: styleMeta.description || '',
    source: {
      type: 'figma-mcp',
      styleKey: styleMeta.key,
      nodeId: styleMeta.node_id,
      extractedAt: new Date().toISOString()
    },
    figmaStyleKey: styleMeta.key
  };
}

/**
 * Transform Figma effect style to Design Bridge token
 * @param {Object} styleMeta - Figma style metadata
 * @returns {Object} Design Bridge effect token
 */
function transformEffectStyle(styleMeta) {
  const parsed = parseTokenPath(styleMeta.name);

  return {
    id: `effect-${styleMeta.node_id.replace(':', '-')}`,
    name: styleMeta.name,
    category: 'effects',
    path: parsed.path,
    group: parsed.group,
    variant: parsed.variant,
    description: styleMeta.description || '',
    source: {
      type: 'figma-mcp',
      styleKey: styleMeta.key,
      nodeId: styleMeta.node_id,
      extractedAt: new Date().toISOString()
    },
    figmaStyleKey: styleMeta.key
  };
}

/**
 * Parse Figma style name into token path
 * "Primary/500" → { path: ["Primary", "500"], group: "Primary", variant: "500" }
 * "Body/Regular" → { path: ["Body", "Regular"], group: "Body", variant: "Regular" }
 * "Button/Primary/Default" → { path: ["Button", "Primary", "Default"], group: "Button", variant: "Default" }
 * @param {string} name - Figma style name
 * @returns {Object} Parsed token path
 */
function parseTokenPath(name) {
  const parts = name.split('/').map(s => s.trim()).filter(Boolean);

  return {
    path: parts,
    group: parts[0] || name,
    variant: parts.length > 1 ? parts[parts.length - 1] : null
  };
}

/**
 * Generate CSS variable name from token
 * @param {Object} token - Design Bridge token
 * @returns {string} CSS variable name
 */
function generateCssVariableName(token) {
  const prefix = token.category === 'colors' ? 'color' :
                 token.category === 'typography' ? 'font' :
                 token.category === 'effects' ? 'shadow' : 'token';

  const nameParts = token.path.map(p =>
    p.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')
  );

  return `--${prefix}-${nameParts.join('-')}`;
}

/**
 * Write extracted tokens to files AND register in unified registry
 * @param {Object} results - Extraction results
 * @param {string} outputDir - Output directory (project root with .design/)
 * @param {Object} options - Additional options
 * @param {string} options.fileKey - Figma file key for source tracking
 * @param {boolean} options.skipRegistry - Skip unified registry registration (default: false)
 */
async function writeTokenFiles(results, outputDir, options = {}) {
  const tokensDir = path.join(outputDir, 'source', 'tokens');
  const projectPath = outputDir.includes('.design')
    ? path.dirname(outputDir.split('.design')[0] + '.design')
    : outputDir;

  if (!fs.existsSync(tokensDir)) {
    fs.mkdirSync(tokensDir, { recursive: true });
  }

  // Prepare tokens with CSS variables
  const colorTokensWithVars = results.colors.map(c => ({
    ...c,
    cssVariable: generateCssVariableName(c)
  }));

  const typographyTokensWithVars = results.typography.map(t => ({
    ...t,
    cssVariable: generateCssVariableName(t)
  }));

  const effectTokensWithVars = results.effects.map(e => ({
    ...e,
    cssVariable: generateCssVariableName(e)
  }));

  // Write color tokens
  if (results.colors.length > 0) {
    const colorTokens = {
      $type: 'colors',
      extractedAt: new Date().toISOString(),
      count: results.colors.length,
      tokens: colorTokensWithVars
    };

    fs.writeFileSync(
      path.join(tokensDir, 'colors.json'),
      JSON.stringify(colorTokens, null, 2)
    );
  }

  // Write typography tokens
  if (results.typography.length > 0) {
    const typographyTokens = {
      $type: 'typography',
      extractedAt: new Date().toISOString(),
      count: results.typography.length,
      tokens: typographyTokensWithVars
    };

    fs.writeFileSync(
      path.join(tokensDir, 'typography.json'),
      JSON.stringify(typographyTokens, null, 2)
    );
  }

  // Write effect tokens
  if (results.effects.length > 0) {
    const effectTokens = {
      $type: 'effects',
      extractedAt: new Date().toISOString(),
      count: results.effects.length,
      tokens: effectTokensWithVars
    };

    fs.writeFileSync(
      path.join(tokensDir, 'effects.json'),
      JSON.stringify(effectTokens, null, 2)
    );
  }

  // Write combined tokens index
  const tokenIndex = {
    version: '1.0.0',
    extractedAt: new Date().toISOString(),
    source: 'figma-mcp',
    summary: {
      colors: results.colors.length,
      typography: results.typography.length,
      effects: results.effects.length,
      total: results.extracted
    },
    files: []
  };

  if (results.colors.length > 0) tokenIndex.files.push('colors.json');
  if (results.typography.length > 0) tokenIndex.files.push('typography.json');
  if (results.effects.length > 0) tokenIndex.files.push('effects.json');

  fs.writeFileSync(
    path.join(tokensDir, 'index.json'),
    JSON.stringify(tokenIndex, null, 2)
  );

  // ============================================================
  // v2.0.0: Register tokens in unified registry
  // ============================================================
  if (!options.skipRegistry) {
    const registrationResults = await registerExtractedTokens(
      {
        colors: colorTokensWithVars,
        typography: typographyTokensWithVars,
        effects: effectTokensWithVars
      },
      projectPath,
      {
        type: 'figma-mcp',
        fileKey: options.fileKey || null
      }
    );

    // Attach registration results to the token index for reference
    tokenIndex.registrationResults = registrationResults;
  }

  return tokenIndex;
}

/**
 * Register extracted tokens in the unified registry
 * @param {Object} tokensByCategory - Tokens grouped by category
 * @param {string} projectPath - Project root path
 * @param {Object} source - Source information
 * @returns {Promise<Object>} Registration results by category
 */
async function registerExtractedTokens(tokensByCategory, projectPath, source) {
  const results = {
    colors: null,
    typography: null,
    effects: null,
    totalRegistered: 0,
    totalUpdated: 0,
    totalFailed: 0
  };

  try {
    const registrar = getAutoRegistrar(projectPath);

    // Register color tokens
    if (tokensByCategory.colors && tokensByCategory.colors.length > 0) {
      results.colors = await registrar.registerTokenBatch(
        tokensByCategory.colors,
        'colors',
        source
      );
      results.totalRegistered += results.colors.registered || 0;
      results.totalUpdated += results.colors.updated || 0;
      results.totalFailed += results.colors.failed || 0;
    }

    // Register typography tokens
    if (tokensByCategory.typography && tokensByCategory.typography.length > 0) {
      results.typography = await registrar.registerTokenBatch(
        tokensByCategory.typography,
        'typography',
        source
      );
      results.totalRegistered += results.typography.registered || 0;
      results.totalUpdated += results.typography.updated || 0;
      results.totalFailed += results.typography.failed || 0;
    }

    // Register effect tokens
    if (tokensByCategory.effects && tokensByCategory.effects.length > 0) {
      results.effects = await registrar.registerTokenBatch(
        tokensByCategory.effects,
        'effects',
        source
      );
      results.totalRegistered += results.effects.registered || 0;
      results.totalUpdated += results.effects.updated || 0;
      results.totalFailed += results.effects.failed || 0;
    }

    console.log(`[figma-style-extractor] Tokens registered: ${results.totalRegistered} new, ${results.totalUpdated} updated, ${results.totalFailed} failed`);

  } catch (error) {
    console.warn(`[figma-style-extractor] Token registration failed: ${error.message}`);
    results.error = error.message;
  }

  return results;
}

/**
 * Group tokens by their group property
 * @param {Array} tokens - Array of tokens
 * @returns {Object} Grouped tokens
 */
function groupTokensByGroup(tokens) {
  return tokens.reduce((acc, token) => {
    const group = token.group || 'Other';
    if (!acc[group]) {
      acc[group] = [];
    }
    acc[group].push(token);
    return acc;
  }, {});
}

/**
 * Format extraction results for display
 * @param {Object} results - Extraction results
 * @returns {string} Formatted output
 */
function formatStyleResults(results) {
  const lines = [
    'Style Extraction Complete!',
    '',
    `Colors: ${results.colors.length}`,
    `Typography: ${results.typography.length}`,
    `Effects: ${results.effects.length}`,
    `Total: ${results.extracted}`,
    ''
  ];

  if (results.errors.length > 0) {
    lines.push(`Errors: ${results.errors.length}`);
    results.errors.forEach(e => {
      lines.push(`  - ${e.styleId || 'Unknown'}: ${e.error}`);
    });
  }

  // Group by category
  if (results.colors.length > 0) {
    lines.push('', 'Colors by group:');
    const grouped = groupTokensByGroup(results.colors);
    for (const [group, tokens] of Object.entries(grouped)) {
      lines.push(`  ${group}: ${tokens.length}`);
    }
  }

  if (results.typography.length > 0) {
    lines.push('', 'Typography by group:');
    const grouped = groupTokensByGroup(results.typography);
    for (const [group, tokens] of Object.entries(grouped)) {
      lines.push(`  ${group}: ${tokens.length}`);
    }
  }

  return lines.join('\n');
}

module.exports = {
  extractFigmaStyles,
  transformColorStyle,
  transformTextStyle,
  transformEffectStyle,
  parseTokenPath,
  generateCssVariableName,
  writeTokenFiles,
  registerExtractedTokens,
  groupTokensByGroup,
  formatStyleResults
};
