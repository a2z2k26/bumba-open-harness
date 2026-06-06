/**
 * Layout to HTML Reference Transformer
 *
 * Converts extracted Figma layout data into browser-renderable HTML
 * for visual reference and iterative refinement. This is NOT production
 * code - it's a reference artifact for comparing against screenshots.
 */

const fs = require('fs');
const path = require('path');

/**
 * Convert Figma auto-layout properties to CSS flexbox
 */
function convertAutoLayoutToCSS(layout) {
  const css = {
    display: 'flex'
  };

  // Direction
  if (layout.layoutMode === 'VERTICAL') {
    css['flex-direction'] = 'column';
  } else if (layout.layoutMode === 'HORIZONTAL') {
    css['flex-direction'] = 'row';
  }

  // Primary axis alignment (justify-content)
  const primaryAxisMap = {
    'MIN': 'flex-start',
    'CENTER': 'center',
    'MAX': 'flex-end',
    'SPACE_BETWEEN': 'space-between'
  };
  if (layout.primaryAxisAlignItems && primaryAxisMap[layout.primaryAxisAlignItems]) {
    css['justify-content'] = primaryAxisMap[layout.primaryAxisAlignItems];
  }

  // Counter axis alignment (align-items)
  const counterAxisMap = {
    'MIN': 'flex-start',
    'CENTER': 'center',
    'MAX': 'flex-end',
    'STRETCH': 'stretch'
  };
  if (layout.counterAxisAlignItems && counterAxisMap[layout.counterAxisAlignItems]) {
    css['align-items'] = counterAxisMap[layout.counterAxisAlignItems];
  }

  // Gap (itemSpacing)
  if (layout.itemSpacing && layout.itemSpacing > 0) {
    css['gap'] = `${layout.itemSpacing}px`;
  }

  // Padding
  const paddingParts = [];
  const pt = layout.paddingTop || 0;
  const pr = layout.paddingRight || 0;
  const pb = layout.paddingBottom || 0;
  const pl = layout.paddingLeft || 0;

  if (pt || pr || pb || pl) {
    css['padding'] = `${pt}px ${pr}px ${pb}px ${pl}px`;
  }

  // Sizing
  if (layout.width) {
    css['width'] = `${layout.width}px`;
  }
  if (layout.height) {
    css['height'] = `${layout.height}px`;
  }

  return css;
}

/**
 * Convert CSS object to inline style string
 */
function cssToString(cssObj) {
  return Object.entries(cssObj)
    .map(([key, value]) => `${key}: ${value}`)
    .join('; ');
}

/**
 * Generate HTML for a component reference placeholder
 */
function generateComponentPlaceholder(node, options = {}) {
  const name = node.componentRef?.name || node.name || 'Unknown';
  const width = node.width || 100;
  const height = node.height || 40;
  const id = node.componentRef?.mainComponentId || node.id || '';

  const style = `width: ${width}px; height: ${height}px;`;

  return `    <div class="component-ref"
         data-component="${escapeHtml(name)}"
         data-component-id="${escapeHtml(id)}"
         style="${style}">
      ${escapeHtml(name)}
    </div>`;
}

/**
 * Generate HTML for a layout frame and its children
 */
function generateFrameHTML(node, depth = 0) {
  const indent = '  '.repeat(depth + 1);
  const css = convertAutoLayoutToCSS(node);
  const styleStr = cssToString(css);

  let childrenHTML = '';

  if (node.children && node.children.length > 0) {
    const childLines = node.children.map(child => {
      if (child.type === 'INSTANCE' || child.componentRef) {
        return generateComponentPlaceholder(child);
      } else if (child.type === 'FRAME' || child.children) {
        return generateFrameHTML(child, depth + 1);
      } else if (child.type === 'TEXT') {
        return `${indent}  <div class="text-node" style="width: ${child.width}px;">${escapeHtml(child.characters || child.name)}</div>`;
      } else {
        return `${indent}  <div class="node" data-type="${child.type}" style="width: ${child.width || 0}px; height: ${child.height || 0}px;"></div>`;
      }
    });
    childrenHTML = '\n' + childLines.join('\n') + '\n' + indent;
  }

  return `${indent}<div class="layout-frame" data-figma-id="${escapeHtml(node.id || '')}" data-name="${escapeHtml(node.name || '')}" style="${styleStr}">${childrenHTML}</div>`;
}

/**
 * Escape HTML special characters
 */
function escapeHtml(str) {
  if (typeof str !== 'string') return '';
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Generate complete HTML document from layout data
 */
function generateHTML(layout, options = {}) {
  const layoutName = layout.name || 'Untitled Layout';
  const frameHTML = generateFrameHTML(layout, 0);

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="layout-name" content="${escapeHtml(layoutName)}">
  <meta name="source" content="figma-extraction">
  <meta name="generator" content="design-bridge-layout-to-html">
  <title>${escapeHtml(layoutName)} - Layout Reference</title>
  <style>
    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      font-family: system-ui, -apple-system, sans-serif;
      background: #f5f5f5;
      padding: 20px;
    }

    .layout-container {
      background: white;
      border-radius: 8px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.1);
      overflow: hidden;
    }

    .layout-frame {
      background: #ffffff;
    }

    .component-ref {
      border: 2px dashed #6366f1;
      background: rgba(99, 102, 241, 0.08);
      display: flex;
      align-items: center;
      justify-content: center;
      font-family: system-ui, sans-serif;
      font-size: 11px;
      font-weight: 500;
      color: #6366f1;
      border-radius: 4px;
      position: relative;
    }

    .component-ref::before {
      content: attr(data-component);
      position: absolute;
      top: -8px;
      left: 4px;
      font-size: 9px;
      background: #6366f1;
      color: white;
      padding: 1px 4px;
      border-radius: 2px;
    }

    .text-node {
      font-size: 14px;
      color: #333;
    }

    .node {
      background: rgba(0,0,0,0.05);
      border: 1px solid rgba(0,0,0,0.1);
    }

    /* Reference comparison mode */
    .comparison-container {
      display: flex;
      gap: 20px;
      margin-top: 20px;
    }

    .screenshot-ref {
      border: 1px solid #ddd;
      border-radius: 8px;
      overflow: hidden;
    }

    .screenshot-ref img {
      max-width: 100%;
      display: block;
    }

    .reference-label {
      background: #333;
      color: white;
      padding: 8px 12px;
      font-size: 12px;
      font-weight: 500;
    }
  </style>
</head>
<body>
  <h1 style="font-size: 16px; font-weight: 600; margin-bottom: 12px; color: #333;">
    ${escapeHtml(layoutName)}
  </h1>
  <p style="font-size: 12px; color: #666; margin-bottom: 20px;">
    Layout Reference - Generated from Figma extraction
  </p>

  <div class="layout-container">
${frameHTML}
  </div>
${options.includeScreenshot && options.screenshotPath ? `
  <div class="comparison-container">
    <div class="screenshot-ref">
      <div class="reference-label">Original Screenshot</div>
      <img src="${escapeHtml(options.screenshotPath)}" alt="Original Figma screenshot">
    </div>
  </div>
` : ''}
</body>
</html>`;

  return html;
}

/**
 * Extract screenshot bytes from layout data and write to file
 * Handles both direct screenshot property and metadata.screenshot
 */
function extractAndWriteScreenshot(layoutData, layoutDir) {
  const screenshotPath = path.join(layoutDir, 'screenshot.png');

  // Check if screenshot.png already exists
  if (fs.existsSync(screenshotPath)) {
    return { exists: true, path: screenshotPath };
  }

  // Try to find screenshot bytes in layout data
  const screenshotData = layoutData.screenshot ||
                         (layoutData.metadata && layoutData.metadata.screenshot);

  if (screenshotData && screenshotData.bytes && Array.isArray(screenshotData.bytes)) {
    const buffer = Buffer.from(screenshotData.bytes);
    fs.writeFileSync(screenshotPath, buffer);
    return { written: true, path: screenshotPath };
  }

  return { exists: false, written: false };
}

/**
 * Transform layout data to HTML and save artifacts
 */
async function transformLayoutToHTML(layoutData, options = {}) {
  const {
    outputDir = '.design/layouts',
    embedStyles = true,
    includeScreenshot = true,
    screenshotPath = null
  } = options;

  const layoutName = layoutData.name || 'untitled';
  const safeName = layoutName.replace(/[^a-zA-Z0-9-_]/g, '-').toLowerCase();
  const layoutDir = path.join(outputDir, safeName);

  // Ensure directory exists
  if (!fs.existsSync(layoutDir)) {
    fs.mkdirSync(layoutDir, { recursive: true });
  }

  // Extract and write screenshot if bytes are embedded in layout data
  let screenshotResult = { exists: false, written: false };
  if (includeScreenshot) {
    screenshotResult = extractAndWriteScreenshot(layoutData, layoutDir);
  }

  // Determine if screenshot is available
  const hasScreenshot = screenshotResult.exists || screenshotResult.written ||
                        fs.existsSync(path.join(layoutDir, 'screenshot.png'));

  // Generate HTML
  const html = generateHTML(layoutData, {
    includeScreenshot: includeScreenshot && hasScreenshot,
    screenshotPath: hasScreenshot ? 'screenshot.png' : null
  });

  // Save files
  const htmlPath = path.join(layoutDir, 'reference.html');
  fs.writeFileSync(htmlPath, html);

  // Save layout JSON if not already there
  const jsonPath = path.join(layoutDir, 'layout.json');
  if (!fs.existsSync(jsonPath)) {
    fs.writeFileSync(jsonPath, JSON.stringify(layoutData, null, 2));
  }

  // Update layout.json with reference path
  const existingData = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
  existingData.htmlReferencePath = 'reference.html';
  existingData.generatedAt = new Date().toISOString();
  if (hasScreenshot) {
    existingData.screenshotPath = 'screenshot.png';
  }
  fs.writeFileSync(jsonPath, JSON.stringify(existingData, null, 2));

  return {
    success: true,
    layoutName,
    outputDir: layoutDir,
    screenshotExtracted: screenshotResult.written,
    hasScreenshot,
    files: {
      html: htmlPath,
      json: jsonPath,
      screenshot: hasScreenshot ? path.join(layoutDir, 'screenshot.png') : null
    }
  };
}

/**
 * Load and transform layout from JSON file
 */
async function transformLayoutFile(layoutJsonPath, options = {}) {
  if (!fs.existsSync(layoutJsonPath)) {
    throw new Error(`Layout file not found: ${layoutJsonPath}`);
  }

  const layoutData = JSON.parse(fs.readFileSync(layoutJsonPath, 'utf8'));

  // Determine output directory from input path if not specified
  if (!options.outputDir) {
    options.outputDir = path.dirname(layoutJsonPath);
  }

  return transformLayoutToHTML(layoutData, options);
}

module.exports = {
  convertAutoLayoutToCSS,
  generateHTML,
  generateFrameHTML,
  generateComponentPlaceholder,
  extractAndWriteScreenshot,
  transformLayoutToHTML,
  transformLayoutFile
};
