#!/usr/bin/env node
/**
 * load-design-tokens.js
 * Helper script to load design tokens from .design/tokens/
 *
 * Usage:
 *   const { loadDesignTokens } = require('./.claude/scripts/load-design-tokens');
 *   const tokens = loadDesignTokens(projectPath);
 */

const fs = require('fs');
const path = require('path');

/**
 * Normalize tokens to flat format
 * Handles both flat format ("primary": "#2563EB") and rich format ("primary": { value: "#2563EB", ... })
 * This ensures compatibility between Figma plugin exports and transform skills
 * @param {object} data - Token data (can be flat or rich format)
 * @returns {object} Normalized flat tokens
 */
function normalizeTokens(data) {
  if (!data || typeof data !== 'object') {
    return data;
  }

  // Handle rich metadata wrapper format: { metadata: {...}, tokens: {...} }
  if (data.tokens && typeof data.tokens === 'object') {
    const result = {};
    Object.entries(data.tokens).forEach(([category, categoryTokens]) => {
      result[category] = normalizeTokens(categoryTokens);
    });
    return result;
  }

  const normalized = {};

  Object.entries(data).forEach(([key, value]) => {
    if (value === null || value === undefined) {
      return;
    }

    // If value is an object with a 'value' property, extract it (rich format)
    if (typeof value === 'object' && !Array.isArray(value) && 'value' in value) {
      normalized[key] = value.value;
    }
    // If value is a nested object (like typography with fontFamily, fontSize, etc.), keep it
    else if (typeof value === 'object' && !Array.isArray(value)) {
      // Check if it's a typography-style nested object (has common typography properties)
      const typographyProps = ['fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'letterSpacing'];
      const hasTypographyProps = typographyProps.some(prop => prop in value);

      if (hasTypographyProps) {
        // Keep typography objects as-is
        normalized[key] = value;
      } else {
        // Recursively normalize nested objects
        normalized[key] = normalizeTokens(value);
      }
    }
    // Flat format - keep as-is
    else {
      normalized[key] = value;
    }
  });

  return normalized;
}

/**
 * Load all design tokens from .design/tokens/ directory
 * @param {string} projectPath - Path to project root
 * @returns {object} Combined tokens object
 * @throws {Error} If tokens directory not found
 */
function loadDesignTokens(projectPath = process.cwd()) {
  const tokensDir = path.join(projectPath, '.design', 'tokens');

  // Check if tokens directory exists
  if (!fs.existsSync(tokensDir)) {
    throw new Error(
      `.design/tokens/ directory not found at ${tokensDir}\n` +
      `Run /design-init to initialize Design Bridge structure.`
    );
  }

  // Find all JSON files in tokens directory (using built-in fs.readdirSync)
  const tokenFiles = [];

  function findJsonFiles(dir) {
    const entries = fs.readdirSync(dir, { withFileTypes: true });

    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);

      if (entry.isDirectory()) {
        findJsonFiles(fullPath);
      } else if (entry.isFile() && entry.name.endsWith('.json') && entry.name !== 'index.json') {
        tokenFiles.push(fullPath);
      }
    }
  }

  findJsonFiles(tokensDir);

  if (tokenFiles.length === 0) {
    console.warn(
      `Warning: No token files found in ${tokensDir}\n` +
      `Extract tokens from Figma using the Design Bridge plugin.`
    );
    return {};
  }

  // Load and merge all token files
  const tokens = {};

  tokenFiles.forEach(file => {
    try {
      const content = fs.readFileSync(file, 'utf8');
      const data = JSON.parse(content);

      // Get category from filename (e.g., colors.json -> colors)
      const filename = path.basename(file, '.json');
      const category = getCategoryFromFilename(filename);

      // Normalize tokens (extract .value from rich format)
      const normalizedData = normalizeTokens(data);

      // Merge into tokens object
      if (tokens[category]) {
        tokens[category] = { ...tokens[category], ...normalizedData };
      } else {
        tokens[category] = normalizedData;
      }
    } catch (error) {
      console.error(`Error loading ${file}: ${error.message}`);
    }
  });

  return tokens;
}

/**
 * Get token category from filename
 * @param {string} filename - Token filename
 * @returns {string} Category name
 */
function getCategoryFromFilename(filename) {
  // Handle Figma-exported filenames like "figma-colors-2023-11-20"
  if (filename.startsWith('figma-')) {
    const parts = filename.split('-');
    if (parts.length >= 2) {
      return parts[1]; // Extract "colors" from "figma-colors-..."
    }
  }

  // Handle standard filenames
  const categoryMap = {
    'colors': 'colors',
    'colour': 'colors',
    'color': 'colors',
    'typography': 'typography',
    'type': 'typography',
    'fonts': 'typography',
    'spacing': 'spacing',
    'space': 'spacing',
    'effects': 'effects',
    'shadows': 'effects',
    'radius': 'borderRadius',
    'radii': 'borderRadius',
    'border-radius': 'borderRadius'
  };

  for (const [key, value] of Object.entries(categoryMap)) {
    if (filename.toLowerCase().includes(key)) {
      return value;
    }
  }

  return 'other';
}

/**
 * Load tokens for specific category
 * @param {string} projectPath - Path to project root
 * @param {string} category - Token category (colors, typography, etc.)
 * @returns {object} Tokens for that category
 */
function loadTokenCategory(projectPath = process.cwd(), category) {
  const allTokens = loadDesignTokens(projectPath);
  return allTokens[category] || {};
}

/**
 * Get token statistics
 * @param {string} projectPath - Path to project root
 * @returns {object} Token statistics
 */
function getTokenStats(projectPath = process.cwd()) {
  const tokens = loadDesignTokens(projectPath);
  const stats = {
    categories: Object.keys(tokens).length,
    totalTokens: 0,
    breakdown: {}
  };

  Object.entries(tokens).forEach(([category, categoryTokens]) => {
    const count = Object.keys(categoryTokens).length;
    stats.breakdown[category] = count;
    stats.totalTokens += count;
  });

  return stats;
}

/**
 * Validate tokens structure
 * @param {object} tokens - Tokens to validate
 * @returns {object} Validation result
 */
function validateTokens(tokens) {
  const errors = [];
  const warnings = [];

  if (!tokens || typeof tokens !== 'object') {
    errors.push('Tokens must be an object');
    return { valid: false, errors, warnings };
  }

  if (Object.keys(tokens).length === 0) {
    warnings.push('No tokens found - extract from Figma first');
  }

  // Validate each category
  Object.entries(tokens).forEach(([category, categoryTokens]) => {
    if (typeof categoryTokens !== 'object') {
      errors.push(`Category '${category}' must be an object`);
    }

    // Check for empty categories
    if (Object.keys(categoryTokens).length === 0) {
      warnings.push(`Category '${category}' is empty`);
    }
  });

  return {
    valid: errors.length === 0,
    errors,
    warnings
  };
}

// CLI usage
if (require.main === module) {
  const projectPath = process.argv[2] || process.cwd();
  const category = process.argv[3];

  try {
    if (category) {
      const tokens = loadTokenCategory(projectPath, category);
      console.log(`\n${category} tokens:`);
      console.log(JSON.stringify(tokens, null, 2));
    } else {
      const tokens = loadDesignTokens(projectPath);
      const stats = getTokenStats(projectPath);

      console.log('\nToken Statistics:');
      console.log(`  Total categories: ${stats.categories}`);
      console.log(`  Total tokens: ${stats.totalTokens}`);
      console.log('\nBreakdown:');
      Object.entries(stats.breakdown).forEach(([cat, count]) => {
        console.log(`  ${cat}: ${count}`);
      });

      console.log('\nAll tokens:');
      console.log(JSON.stringify(tokens, null, 2));
    }
  } catch (error) {
    console.error(`Error: ${error.message}`);
    process.exit(1);
  }
}

module.exports = {
  loadDesignTokens,
  loadTokenCategory,
  getTokenStats,
  validateTokens,
  getCategoryFromFilename,
  normalizeTokens
};
