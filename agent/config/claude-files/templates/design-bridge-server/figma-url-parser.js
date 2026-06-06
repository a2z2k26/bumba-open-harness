/**
 * figma-url-parser.js
 * Parses Figma URLs to extract fileKey and nodeId
 *
 * Used by the extract-figma-mcp skill for Claude Code
 */

/**
 * URL patterns supported:
 * - https://www.figma.com/file/{fileKey}/{fileName}?node-id={nodeId}
 * - https://www.figma.com/design/{fileKey}/{fileName}?node-id={nodeId}
 * - https://figma.com/file/{fileKey}
 * - figma.com/design/{fileKey}/{fileName}
 */

const FIGMA_URL_PATTERNS = [
  // Full URL with node-id
  /(?:https?:\/\/)?(?:www\.)?figma\.com\/(?:file|design)\/([a-zA-Z0-9]+)(?:\/([^?]+))?(?:\?.*node-id=([0-9]+(?:%3A|:|-)[0-9]+))?/i,
  // Multiple node-ids (comma separated)
  /(?:https?:\/\/)?(?:www\.)?figma\.com\/(?:file|design)\/([a-zA-Z0-9]+)(?:\/[^?]+)?(?:\?.*node-id=([0-9,:%3A-]+))?/i
];

/**
 * Normalize node ID format
 * Handles: "123:456", "123-456", "123%3A456"
 * @param {string} nodeId - Raw node ID from URL
 * @returns {string|null} Normalized node ID or null
 */
function normalizeNodeId(nodeId) {
  if (!nodeId) return null;

  // Decode URL encoding
  let decoded = decodeURIComponent(nodeId);

  // Convert dash format to colon format
  decoded = decoded.replace(/-/g, ':');

  // Validate format
  if (!/^\d+:\d+$/.test(decoded)) {
    return null;
  }

  return decoded;
}

/**
 * Parse a Figma URL and extract components
 * @param {string} url - Figma file or design URL
 * @returns {Object} Parsed URL components or error
 */
function parseFigmaUrl(url) {
  if (!url || typeof url !== 'string') {
    return {
      valid: false,
      error: 'URL is required and must be a string'
    };
  }

  // Clean up the URL
  const cleanUrl = url.trim();

  // Try each pattern
  for (const pattern of FIGMA_URL_PATTERNS) {
    const match = cleanUrl.match(pattern);

    if (match) {
      const fileKey = match[1];
      const fileName = match[2] ? decodeURIComponent(match[2]) : null;
      const rawNodeId = match[3];

      const result = {
        valid: true,
        fileKey: fileKey,
        fileName: fileName,
        nodeId: normalizeNodeId(rawNodeId),
        originalUrl: url
      };

      // Add helpful info
      result.isFileLevel = !result.nodeId;
      result.mcpReady = {
        fileKey: result.fileKey,
        node_ids: result.nodeId ? [result.nodeId] : null
      };

      return result;
    }
  }

  // No pattern matched
  return {
    valid: false,
    error: 'Invalid Figma URL format',
    hint: 'Expected: figma.com/file/{fileKey} or figma.com/design/{fileKey}?node-id={id}',
    received: url
  };
}

/**
 * Parse multiple node IDs from a URL
 * Handles: ?node-id=123:456,789:012
 * @param {string} url - Figma URL with potentially multiple node IDs
 * @returns {Object} Parsed result with nodeIds array
 */
function parseMultipleNodes(url) {
  const parsed = parseFigmaUrl(url);
  if (!parsed.valid) return parsed;

  // Check for comma-separated node IDs in URL
  const nodeIdMatch = url.match(/node-id=([0-9,:%3A-]+)/i);
  if (nodeIdMatch) {
    const rawIds = decodeURIComponent(nodeIdMatch[1]);
    const nodeIds = rawIds.split(',')
      .map(id => normalizeNodeId(id))
      .filter(Boolean);

    return {
      ...parsed,
      nodeIds: nodeIds,
      mcpReady: {
        fileKey: parsed.fileKey,
        node_ids: nodeIds
      }
    };
  }

  return parsed;
}

/**
 * Validate that a fileKey looks correct
 * @param {string} fileKey - Figma file key
 * @returns {boolean} True if valid format
 */
function validateFileKey(fileKey) {
  // Figma file keys are alphanumeric, typically 8+ characters
  return /^[a-zA-Z0-9]{8,}$/.test(fileKey);
}

/**
 * Build a Figma URL from components
 * @param {string} fileKey - Figma file key
 * @param {string|null} nodeId - Optional node ID
 * @param {string} fileName - Optional file name
 * @returns {string} Constructed Figma URL
 */
function buildFigmaUrl(fileKey, nodeId = null, fileName = 'Untitled') {
  let url = `https://www.figma.com/design/${fileKey}/${encodeURIComponent(fileName)}`;
  if (nodeId) {
    url += `?node-id=${nodeId.replace(':', '%3A')}`;
  }
  return url;
}

/**
 * Extract file key directly from various inputs
 * Accepts: full URL, bare file key, or partial path
 * @param {string} input - URL or file key
 * @returns {string|null} Extracted file key or null
 */
function extractFileKey(input) {
  if (!input || typeof input !== 'string') return null;

  const trimmed = input.trim();

  // Check if it's already a bare file key
  if (/^[a-zA-Z0-9]{8,}$/.test(trimmed)) {
    return trimmed;
  }

  // Try to parse as URL
  const parsed = parseFigmaUrl(trimmed);
  return parsed.valid ? parsed.fileKey : null;
}

module.exports = {
  parseFigmaUrl,
  parseMultipleNodes,
  normalizeNodeId,
  validateFileKey,
  buildFigmaUrl,
  extractFileKey,
  FIGMA_URL_PATTERNS
};
