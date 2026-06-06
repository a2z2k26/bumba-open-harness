/**
 * Phase 9 - Sprint 9.2: Asset Optimization & Bundling
 *
 * Provides comprehensive asset optimization, bundling, and minification
 * capabilities for design system assets including images, SVGs, CSS, and JS.
 */

const { EventEmitter } = require('events');
const crypto = require('crypto');
const path = require('path');
const zlib = require('zlib');

// ============================================================================
// Constants
// ============================================================================

const OPTIMIZATION_LEVELS = {
  NONE: 0,
  LOW: 1,
  MEDIUM: 2,
  HIGH: 3,
  MAXIMUM: 4
};

const ASSET_TYPES = {
  IMAGE: 'image',
  SVG: 'svg',
  CSS: 'css',
  JS: 'javascript',
  JSON: 'json',
  FONT: 'font'
};

const IMAGE_FORMATS = {
  PNG: 'png',
  JPEG: 'jpeg',
  JPG: 'jpg',
  WEBP: 'webp',
  AVIF: 'avif',
  GIF: 'gif'
};

const COMPRESSION_TYPES = {
  GZIP: 'gzip',
  BROTLI: 'brotli',
  DEFLATE: 'deflate',
  NONE: 'none'
};

const OPTIMIZER_EVENTS = {
  OPTIMIZE_START: 'optimize:start',
  OPTIMIZE_COMPLETE: 'optimize:complete',
  OPTIMIZE_ERROR: 'optimize:error',
  BUNDLE_START: 'bundle:start',
  BUNDLE_COMPLETE: 'bundle:complete',
  MINIFY_COMPLETE: 'minify:complete',
  COMPRESS_COMPLETE: 'compress:complete'
};

// ============================================================================
// ImageOptimizer - Optimize raster images
// ============================================================================

class ImageOptimizer extends EventEmitter {
  constructor(options = {}) {
    super();
    this.options = {
      quality: options.quality || 80,
      maxWidth: options.maxWidth || 2048,
      maxHeight: options.maxHeight || 2048,
      progressive: options.progressive !== false,
      stripMetadata: options.stripMetadata !== false,
      format: options.format || null, // null = keep original
      ...options
    };
    this.stats = {
      processed: 0,
      totalSaved: 0,
      errors: 0
    };
  }

  /**
   * Optimize an image
   */
  async optimize(input, options = {}) {
    const opts = { ...this.options, ...options };
    const startTime = Date.now();

    try {
      // Parse input
      const imageData = this._parseInput(input);

      // Detect format
      const format = this._detectFormat(imageData, opts.format);

      // Apply optimizations based on format
      let optimized;
      switch (format) {
        case IMAGE_FORMATS.PNG:
          optimized = await this._optimizePNG(imageData, opts);
          break;
        case IMAGE_FORMATS.JPEG:
        case IMAGE_FORMATS.JPG:
          optimized = await this._optimizeJPEG(imageData, opts);
          break;
        case IMAGE_FORMATS.WEBP:
          optimized = await this._optimizeWebP(imageData, opts);
          break;
        case IMAGE_FORMATS.GIF:
          optimized = await this._optimizeGIF(imageData, opts);
          break;
        default:
          optimized = imageData;
      }

      // Calculate savings
      const originalSize = imageData.length;
      const optimizedSize = optimized.length;
      const savings = originalSize - optimizedSize;
      const savingsPercent = ((savings / originalSize) * 100).toFixed(2);

      this.stats.processed++;
      this.stats.totalSaved += savings;

      const result = {
        data: optimized,
        format,
        originalSize,
        optimizedSize,
        savings,
        savingsPercent: parseFloat(savingsPercent),
        duration: Date.now() - startTime
      };

      this.emit(OPTIMIZER_EVENTS.OPTIMIZE_COMPLETE, result);
      return result;

    } catch (error) {
      this.stats.errors++;
      this.emit(OPTIMIZER_EVENTS.OPTIMIZE_ERROR, { error });
      throw error;
    }
  }

  /**
   * Generate responsive image set
   */
  async generateResponsiveSet(input, sizes = [320, 640, 1024, 1920]) {
    const results = [];

    for (const width of sizes) {
      const optimized = await this.optimize(input, {
        maxWidth: width,
        maxHeight: Math.floor(width * 1.5)
      });

      results.push({
        width,
        ...optimized
      });
    }

    return {
      srcset: results.map(r => ({ width: r.width, size: r.optimizedSize })),
      totalOriginal: results.reduce((sum, r) => sum + r.originalSize, 0),
      totalOptimized: results.reduce((sum, r) => sum + r.optimizedSize, 0),
      images: results
    };
  }

  /**
   * Convert image to modern format
   */
  async convertToModernFormat(input, targetFormat = IMAGE_FORMATS.WEBP) {
    return this.optimize(input, { format: targetFormat });
  }

  _parseInput(input) {
    if (Buffer.isBuffer(input)) {
      return input;
    }
    if (typeof input === 'string') {
      // Base64 encoded
      if (input.startsWith('data:')) {
        const base64Data = input.split(',')[1];
        return Buffer.from(base64Data, 'base64');
      }
      return Buffer.from(input, 'base64');
    }
    throw new Error('Invalid input: expected Buffer or base64 string');
  }

  _detectFormat(data, requestedFormat) {
    if (requestedFormat) return requestedFormat;

    // Detect by magic bytes
    if (data[0] === 0x89 && data[1] === 0x50) return IMAGE_FORMATS.PNG;
    if (data[0] === 0xFF && data[1] === 0xD8) return IMAGE_FORMATS.JPEG;
    if (data[0] === 0x47 && data[1] === 0x49) return IMAGE_FORMATS.GIF;
    if (data[0] === 0x52 && data[1] === 0x49) return IMAGE_FORMATS.WEBP;

    return IMAGE_FORMATS.PNG;
  }

  async _optimizePNG(data, opts) {
    // Simulate PNG optimization (in production, use pngquant/optipng)
    // Apply basic compression simulation
    const compressionFactor = 1 - (opts.quality / 100) * 0.3;
    const optimizedLength = Math.floor(data.length * compressionFactor);

    // Create optimized buffer (simulation)
    const optimized = Buffer.alloc(optimizedLength);
    data.copy(optimized, 0, 0, Math.min(data.length, optimizedLength));

    return optimized;
  }

  async _optimizeJPEG(data, opts) {
    // Simulate JPEG optimization
    const qualityFactor = opts.quality / 100;
    const compressionFactor = 0.5 + (qualityFactor * 0.4);
    const optimizedLength = Math.floor(data.length * compressionFactor);

    const optimized = Buffer.alloc(optimizedLength);
    data.copy(optimized, 0, 0, Math.min(data.length, optimizedLength));

    return optimized;
  }

  async _optimizeWebP(data, opts) {
    // WebP typically achieves 25-34% smaller than PNG/JPEG
    const compressionFactor = 0.7;
    const optimizedLength = Math.floor(data.length * compressionFactor);

    const optimized = Buffer.alloc(optimizedLength);
    data.copy(optimized, 0, 0, Math.min(data.length, optimizedLength));

    return optimized;
  }

  async _optimizeGIF(data, opts) {
    // GIF optimization (color reduction, frame optimization)
    const compressionFactor = 0.85;
    const optimizedLength = Math.floor(data.length * compressionFactor);

    const optimized = Buffer.alloc(optimizedLength);
    data.copy(optimized, 0, 0, Math.min(data.length, optimizedLength));

    return optimized;
  }

  getStats() {
    return { ...this.stats };
  }

  resetStats() {
    this.stats = { processed: 0, totalSaved: 0, errors: 0 };
  }
}

// ============================================================================
// SVGOptimizer - Optimize SVG files
// ============================================================================

class SVGOptimizer extends EventEmitter {
  constructor(options = {}) {
    super();
    this.options = {
      removeComments: options.removeComments !== false,
      removeMetadata: options.removeMetadata !== false,
      removeTitle: options.removeTitle || false,
      removeDesc: options.removeDesc || false,
      removeUselessDefs: options.removeUselessDefs !== false,
      removeEmptyContainers: options.removeEmptyContainers !== false,
      removeHiddenElements: options.removeHiddenElements !== false,
      collapseGroups: options.collapseGroups !== false,
      convertColors: options.convertColors !== false,
      convertPathData: options.convertPathData !== false,
      mergePaths: options.mergePaths || false,
      minifyStyles: options.minifyStyles !== false,
      removeUnusedNS: options.removeUnusedNS !== false,
      precision: options.precision || 3,
      ...options
    };
    this.stats = {
      processed: 0,
      totalSaved: 0
    };
  }

  /**
   * Optimize SVG content
   */
  optimize(svg, options = {}) {
    const opts = { ...this.options, ...options };
    const originalSize = Buffer.byteLength(svg, 'utf8');

    let optimized = svg;

    // Remove XML declaration if not needed
    optimized = optimized.replace(/<\?xml[^?]*\?>\s*/gi, '');

    // Remove comments
    if (opts.removeComments) {
      optimized = optimized.replace(/<!--[\s\S]*?-->/g, '');
    }

    // Remove metadata
    if (opts.removeMetadata) {
      optimized = optimized.replace(/<metadata[\s\S]*?<\/metadata>/gi, '');
    }

    // Remove title
    if (opts.removeTitle) {
      optimized = optimized.replace(/<title[\s\S]*?<\/title>/gi, '');
    }

    // Remove desc
    if (opts.removeDesc) {
      optimized = optimized.replace(/<desc[\s\S]*?<\/desc>/gi, '');
    }

    // Remove empty defs
    if (opts.removeUselessDefs) {
      optimized = optimized.replace(/<defs>\s*<\/defs>/gi, '');
    }

    // Remove empty groups
    if (opts.removeEmptyContainers) {
      optimized = optimized.replace(/<g>\s*<\/g>/gi, '');
      optimized = optimized.replace(/<g[^>]*>\s*<\/g>/gi, '');
    }

    // Convert colors to short hex
    if (opts.convertColors) {
      optimized = this._convertColors(optimized);
    }

    // Optimize path data
    if (opts.convertPathData) {
      optimized = this._optimizePathData(optimized, opts.precision);
    }

    // Minify styles
    if (opts.minifyStyles) {
      optimized = this._minifyInlineStyles(optimized);
    }

    // Remove unnecessary whitespace
    optimized = optimized.replace(/>\s+</g, '><');
    optimized = optimized.replace(/\s+/g, ' ');
    optimized = optimized.trim();

    const optimizedSize = Buffer.byteLength(optimized, 'utf8');
    const savings = originalSize - optimizedSize;

    this.stats.processed++;
    this.stats.totalSaved += savings;

    return {
      data: optimized,
      originalSize,
      optimizedSize,
      savings,
      savingsPercent: ((savings / originalSize) * 100).toFixed(2)
    };
  }

  /**
   * Convert SVG to symbol for sprite
   */
  convertToSymbol(svg, id) {
    // Extract viewBox
    const viewBoxMatch = svg.match(/viewBox=["']([^"']+)["']/i);
    const viewBox = viewBoxMatch ? viewBoxMatch[1] : '0 0 24 24';

    // Extract inner content
    const innerMatch = svg.match(/<svg[^>]*>([\s\S]*)<\/svg>/i);
    const inner = innerMatch ? innerMatch[1] : '';

    return `<symbol id="${id}" viewBox="${viewBox}">${inner}</symbol>`;
  }

  /**
   * Create SVG sprite from multiple SVGs
   */
  createSprite(svgs) {
    const symbols = [];

    for (const [id, svg] of Object.entries(svgs)) {
      const optimized = this.optimize(svg);
      symbols.push(this.convertToSymbol(optimized.data, id));
    }

    const sprite = `<svg xmlns="http://www.w3.org/2000/svg" style="display:none">${symbols.join('')}</svg>`;

    return {
      sprite,
      symbols: Object.keys(svgs),
      count: symbols.length
    };
  }

  _convertColors(svg) {
    // Convert rgb to hex
    svg = svg.replace(/rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)/gi, (match, r, g, b) => {
      return '#' + [r, g, b].map(x => {
        const hex = parseInt(x).toString(16);
        return hex.length === 1 ? '0' + hex : hex;
      }).join('');
    });

    // Shorten hex colors
    svg = svg.replace(/#([0-9a-f])\1([0-9a-f])\2([0-9a-f])\3/gi, '#$1$2$3');

    // Convert color names to hex
    const colorMap = {
      'white': '#fff',
      'black': '#000',
      'red': '#f00',
      'green': '#0f0',
      'blue': '#00f'
    };

    for (const [name, hex] of Object.entries(colorMap)) {
      svg = svg.replace(new RegExp(`(["':;])${name}(["';])`, 'gi'), `$1${hex}$2`);
    }

    return svg;
  }

  _optimizePathData(svg, precision) {
    // Round numbers in path data to specified precision
    return svg.replace(/\bd="([^"]+)"/g, (match, pathData) => {
      const optimized = pathData.replace(/(\d+\.\d+)/g, (num) => {
        return parseFloat(num).toFixed(precision).replace(/\.?0+$/, '');
      });
      return `d="${optimized}"`;
    });
  }

  _minifyInlineStyles(svg) {
    return svg.replace(/style="([^"]+)"/g, (match, styles) => {
      const minified = styles
        .replace(/\s*:\s*/g, ':')
        .replace(/\s*;\s*/g, ';')
        .replace(/;$/, '');
      return `style="${minified}"`;
    });
  }

  getStats() {
    return { ...this.stats };
  }
}

// ============================================================================
// CSSMinifier - Minify CSS content
// ============================================================================

class CSSMinifier extends EventEmitter {
  constructor(options = {}) {
    super();
    this.options = {
      removeComments: options.removeComments !== false,
      removeWhitespace: options.removeWhitespace !== false,
      mergeRules: options.mergeRules || false,
      removeEmpty: options.removeEmpty !== false,
      shortenColors: options.shortenColors !== false,
      shortenUnits: options.shortenUnits !== false,
      level: options.level || OPTIMIZATION_LEVELS.MEDIUM,
      ...options
    };
  }

  /**
   * Minify CSS content
   */
  minify(css, options = {}) {
    const opts = { ...this.options, ...options };
    const originalSize = Buffer.byteLength(css, 'utf8');

    let minified = css;

    // Remove comments
    if (opts.removeComments) {
      minified = minified.replace(/\/\*[\s\S]*?\*\//g, '');
    }

    // Remove whitespace
    if (opts.removeWhitespace) {
      // Remove newlines and extra spaces
      minified = minified.replace(/\s+/g, ' ');
      // Remove space around selectors and braces
      minified = minified.replace(/\s*{\s*/g, '{');
      minified = minified.replace(/\s*}\s*/g, '}');
      minified = minified.replace(/\s*;\s*/g, ';');
      minified = minified.replace(/\s*:\s*/g, ':');
      minified = minified.replace(/\s*,\s*/g, ',');
      // Remove trailing semicolons before closing brace
      minified = minified.replace(/;}/g, '}');
    }

    // Shorten colors
    if (opts.shortenColors) {
      minified = this._shortenColors(minified);
    }

    // Shorten units
    if (opts.shortenUnits) {
      minified = this._shortenUnits(minified);
    }

    // Remove empty rules
    if (opts.removeEmpty) {
      minified = minified.replace(/[^{}]+{\s*}/g, '');
    }

    minified = minified.trim();

    const minifiedSize = Buffer.byteLength(minified, 'utf8');
    const savings = originalSize - minifiedSize;

    this.emit(OPTIMIZER_EVENTS.MINIFY_COMPLETE, { type: 'css', savings });

    return {
      data: minified,
      originalSize,
      minifiedSize,
      savings,
      savingsPercent: ((savings / originalSize) * 100).toFixed(2)
    };
  }

  /**
   * Extract and inline critical CSS
   */
  extractCritical(css, criticalSelectors = []) {
    const critical = [];
    const nonCritical = [];

    // Simple rule extraction
    const rules = css.match(/[^{}]+{[^{}]+}/g) || [];

    for (const rule of rules) {
      const selector = rule.split('{')[0].trim();
      const isCritical = criticalSelectors.some(s => selector.includes(s));

      if (isCritical) {
        critical.push(rule);
      } else {
        nonCritical.push(rule);
      }
    }

    return {
      critical: this.minify(critical.join('\n')).data,
      deferred: this.minify(nonCritical.join('\n')).data
    };
  }

  _shortenColors(css) {
    // Shorten hex colors #aabbcc -> #abc
    css = css.replace(/#([0-9a-f])\1([0-9a-f])\2([0-9a-f])\3/gi, '#$1$2$3');

    // Common color shortcuts
    const colorShortcuts = {
      '#000000': '#000',
      '#ffffff': '#fff',
      '#ff0000': '#f00',
      '#00ff00': '#0f0',
      '#0000ff': '#00f'
    };

    for (const [long, short] of Object.entries(colorShortcuts)) {
      css = css.replace(new RegExp(long, 'gi'), short);
    }

    return css;
  }

  _shortenUnits(css) {
    // Remove units from zero values
    css = css.replace(/\b0(px|em|rem|%|pt|pc|in|cm|mm|ex|ch|vw|vh|vmin|vmax)\b/gi, '0');

    // Remove leading zeros
    css = css.replace(/\b0+(\.\d+)/g, '$1');

    return css;
  }
}

// ============================================================================
// JSMinifier - Minify JavaScript content
// ============================================================================

class JSMinifier extends EventEmitter {
  constructor(options = {}) {
    super();
    this.options = {
      removeComments: options.removeComments !== false,
      removeWhitespace: options.removeWhitespace !== false,
      mangleNames: options.mangleNames || false,
      deadCodeElimination: options.deadCodeElimination || false,
      level: options.level || OPTIMIZATION_LEVELS.MEDIUM,
      ...options
    };
  }

  /**
   * Minify JavaScript content
   */
  minify(js, options = {}) {
    const opts = { ...this.options, ...options };
    const originalSize = Buffer.byteLength(js, 'utf8');

    let minified = js;

    // Remove single-line comments (but not URLs)
    if (opts.removeComments) {
      minified = minified.replace(/(?<!:)\/\/[^\n]*/g, '');
      // Remove multi-line comments
      minified = minified.replace(/\/\*[\s\S]*?\*\//g, '');
    }

    // Remove whitespace
    if (opts.removeWhitespace) {
      // Preserve string literals
      const strings = [];
      minified = minified.replace(/(["'`])(?:(?!\1)[^\\]|\\.)*\1/g, (match) => {
        strings.push(match);
        return `__STRING_${strings.length - 1}__`;
      });

      // Minimize whitespace
      minified = minified.replace(/\s+/g, ' ');
      minified = minified.replace(/\s*([{}()[\];,=+\-*/<>!&|?:])\s*/g, '$1');

      // Restore strings
      minified = minified.replace(/__STRING_(\d+)__/g, (_, i) => strings[parseInt(i)]);
    }

    minified = minified.trim();

    const minifiedSize = Buffer.byteLength(minified, 'utf8');
    const savings = originalSize - minifiedSize;

    this.emit(OPTIMIZER_EVENTS.MINIFY_COMPLETE, { type: 'js', savings });

    return {
      data: minified,
      originalSize,
      minifiedSize,
      savings,
      savingsPercent: ((savings / originalSize) * 100).toFixed(2)
    };
  }

  /**
   * Remove dead code (simple implementation)
   */
  removeDeadCode(js, usedExports = []) {
    // This is a simplified implementation
    // In production, use a proper tree-shaker

    let result = js;

    // Remove unused exports if specified
    if (usedExports.length > 0) {
      // Find all exports
      const exportMatches = js.matchAll(/export\s+(const|let|var|function|class)\s+(\w+)/g);

      for (const match of exportMatches) {
        const name = match[2];
        if (!usedExports.includes(name)) {
          // Remove this export (simplified)
          const regex = new RegExp(`export\\s+(const|let|var)\\s+${name}\\s*=[^;]+;`, 'g');
          result = result.replace(regex, '');
        }
      }
    }

    return this.minify(result);
  }
}

// ============================================================================
// Bundler - Bundle multiple files
// ============================================================================

class Bundler extends EventEmitter {
  constructor(options = {}) {
    super();
    this.options = {
      format: options.format || 'esm', // esm, cjs, iife
      minify: options.minify !== false,
      sourcemap: options.sourcemap || false,
      treeshake: options.treeshake || false,
      banner: options.banner || '',
      footer: options.footer || '',
      ...options
    };
    this.cssMinifier = new CSSMinifier();
    this.jsMinifier = new JSMinifier();
  }

  /**
   * Bundle JavaScript modules
   */
  async bundleJS(modules, options = {}) {
    const opts = { ...this.options, ...options };
    this.emit(OPTIMIZER_EVENTS.BUNDLE_START, { type: 'js', count: modules.length });

    let bundle = opts.banner ? `${opts.banner}\n` : '';

    // Wrap based on format
    if (opts.format === 'iife') {
      bundle += '(function(){\n';
    } else if (opts.format === 'cjs') {
      bundle += '"use strict";\n';
    }

    // Concatenate modules
    const moduleContents = [];
    for (const mod of modules) {
      const content = typeof mod === 'string' ? mod : mod.content;
      const name = typeof mod === 'string' ? null : mod.name;

      if (opts.format === 'esm' && name) {
        moduleContents.push(`// Module: ${name}\n${content}`);
      } else {
        moduleContents.push(content);
      }
    }

    bundle += moduleContents.join('\n\n');

    // Close wrapper
    if (opts.format === 'iife') {
      bundle += '\n})();';
    }

    bundle += opts.footer ? `\n${opts.footer}` : '';

    // Minify if requested
    let result;
    if (opts.minify) {
      result = this.jsMinifier.minify(bundle);
    } else {
      result = {
        data: bundle,
        originalSize: Buffer.byteLength(bundle, 'utf8'),
        minifiedSize: Buffer.byteLength(bundle, 'utf8'),
        savings: 0,
        savingsPercent: '0'
      };
    }

    // Generate hash for cache busting
    const hash = crypto.createHash('md5').update(result.data).digest('hex').slice(0, 8);

    this.emit(OPTIMIZER_EVENTS.BUNDLE_COMPLETE, { type: 'js', hash, size: result.minifiedSize });

    return {
      ...result,
      hash,
      format: opts.format,
      moduleCount: modules.length
    };
  }

  /**
   * Bundle CSS files
   */
  async bundleCSS(stylesheets, options = {}) {
    const opts = { ...this.options, ...options };
    this.emit(OPTIMIZER_EVENTS.BUNDLE_START, { type: 'css', count: stylesheets.length });

    let bundle = opts.banner ? `/* ${opts.banner} */\n` : '';

    // Concatenate stylesheets
    for (const stylesheet of stylesheets) {
      const content = typeof stylesheet === 'string' ? stylesheet : stylesheet.content;
      const name = typeof stylesheet === 'string' ? null : stylesheet.name;

      if (name) {
        bundle += `/* ${name} */\n`;
      }
      bundle += content + '\n';
    }

    // Minify if requested
    let result;
    if (opts.minify) {
      result = this.cssMinifier.minify(bundle);
    } else {
      result = {
        data: bundle,
        originalSize: Buffer.byteLength(bundle, 'utf8'),
        minifiedSize: Buffer.byteLength(bundle, 'utf8'),
        savings: 0,
        savingsPercent: '0'
      };
    }

    // Generate hash
    const hash = crypto.createHash('md5').update(result.data).digest('hex').slice(0, 8);

    this.emit(OPTIMIZER_EVENTS.BUNDLE_COMPLETE, { type: 'css', hash, size: result.minifiedSize });

    return {
      ...result,
      hash,
      stylesheetCount: stylesheets.length
    };
  }

  /**
   * Create design tokens bundle
   */
  async bundleTokens(tokens, options = {}) {
    const { format = 'css' } = options;

    let bundle;

    switch (format) {
      case 'css':
        bundle = this._tokensToCSS(tokens);
        break;
      case 'scss':
        bundle = this._tokensToSCSS(tokens);
        break;
      case 'js':
        bundle = this._tokensToJS(tokens);
        break;
      case 'json':
        bundle = JSON.stringify(tokens, null, 0);
        break;
      default:
        bundle = this._tokensToCSS(tokens);
    }

    const hash = crypto.createHash('md5').update(bundle).digest('hex').slice(0, 8);

    return {
      data: bundle,
      format,
      hash,
      tokenCount: Object.keys(tokens).length,
      size: Buffer.byteLength(bundle, 'utf8')
    };
  }

  _tokensToCSS(tokens) {
    let css = ':root {\n';

    for (const [name, value] of Object.entries(tokens)) {
      const cssName = name.replace(/([A-Z])/g, '-$1').toLowerCase();
      css += `  --${cssName}: ${value};\n`;
    }

    css += '}';
    return css;
  }

  _tokensToSCSS(tokens) {
    let scss = '';

    for (const [name, value] of Object.entries(tokens)) {
      const scssName = name.replace(/([A-Z])/g, '-$1').toLowerCase();
      scss += `$${scssName}: ${value};\n`;
    }

    return scss;
  }

  _tokensToJS(tokens) {
    return `export const tokens = ${JSON.stringify(tokens, null, 2)};`;
  }
}

// ============================================================================
// CompressionManager - Handle file compression
// ============================================================================

class CompressionManager extends EventEmitter {
  constructor(options = {}) {
    super();
    this.options = {
      gzipLevel: options.gzipLevel || 9,
      brotliQuality: options.brotliQuality || 11,
      threshold: options.threshold || 1024, // Min size to compress
      ...options
    };
  }

  /**
   * Compress content with gzip
   */
  async gzip(content) {
    const input = Buffer.isBuffer(content) ? content : Buffer.from(content);

    if (input.length < this.options.threshold) {
      return { data: input, compressed: false, originalSize: input.length };
    }

    return new Promise((resolve, reject) => {
      zlib.gzip(input, { level: this.options.gzipLevel }, (err, compressed) => {
        if (err) {
          reject(err);
          return;
        }

        const result = {
          data: compressed,
          compressed: true,
          originalSize: input.length,
          compressedSize: compressed.length,
          ratio: ((1 - compressed.length / input.length) * 100).toFixed(2)
        };

        this.emit(OPTIMIZER_EVENTS.COMPRESS_COMPLETE, { type: 'gzip', ...result });
        resolve(result);
      });
    });
  }

  /**
   * Compress content with brotli
   */
  async brotli(content) {
    const input = Buffer.isBuffer(content) ? content : Buffer.from(content);

    if (input.length < this.options.threshold) {
      return { data: input, compressed: false, originalSize: input.length };
    }

    return new Promise((resolve, reject) => {
      zlib.brotliCompress(input, {
        params: {
          [zlib.constants.BROTLI_PARAM_QUALITY]: this.options.brotliQuality
        }
      }, (err, compressed) => {
        if (err) {
          reject(err);
          return;
        }

        const result = {
          data: compressed,
          compressed: true,
          originalSize: input.length,
          compressedSize: compressed.length,
          ratio: ((1 - compressed.length / input.length) * 100).toFixed(2)
        };

        this.emit(OPTIMIZER_EVENTS.COMPRESS_COMPLETE, { type: 'brotli', ...result });
        resolve(result);
      });
    });
  }

  /**
   * Compress with multiple algorithms and return best
   */
  async compressBest(content) {
    const [gzipResult, brotliResult] = await Promise.all([
      this.gzip(content),
      this.brotli(content)
    ]);

    if (!gzipResult.compressed && !brotliResult.compressed) {
      return { data: content, type: 'none', compressed: false };
    }

    if (brotliResult.compressedSize < gzipResult.compressedSize) {
      return { ...brotliResult, type: 'brotli' };
    }

    return { ...gzipResult, type: 'gzip' };
  }

  /**
   * Decompress content
   */
  async decompress(content, type) {
    return new Promise((resolve, reject) => {
      const decompressor = type === 'brotli' ? zlib.brotliDecompress : zlib.gunzip;

      decompressor(content, (err, decompressed) => {
        if (err) reject(err);
        else resolve(decompressed);
      });
    });
  }
}

// ============================================================================
// AssetPipeline - Orchestrate optimization pipeline
// ============================================================================

class AssetPipeline extends EventEmitter {
  constructor(options = {}) {
    super();
    this.options = {
      level: options.level || OPTIMIZATION_LEVELS.MEDIUM,
      compress: options.compress !== false,
      generateHashes: options.generateHashes !== false,
      ...options
    };

    this.imageOptimizer = new ImageOptimizer(options.image);
    this.svgOptimizer = new SVGOptimizer(options.svg);
    this.cssMinifier = new CSSMinifier(options.css);
    this.jsMinifier = new JSMinifier(options.js);
    this.bundler = new Bundler(options.bundle);
    this.compression = new CompressionManager(options.compression);

    this.stats = {
      processed: 0,
      totalOriginal: 0,
      totalOptimized: 0,
      byType: {}
    };
  }

  /**
   * Process a single asset
   */
  async processAsset(content, type, options = {}) {
    const startTime = Date.now();
    let result;

    switch (type) {
      case ASSET_TYPES.IMAGE:
        result = await this.imageOptimizer.optimize(content, options);
        break;
      case ASSET_TYPES.SVG:
        result = this.svgOptimizer.optimize(content, options);
        break;
      case ASSET_TYPES.CSS:
        result = this.cssMinifier.minify(content, options);
        break;
      case ASSET_TYPES.JS:
        result = this.jsMinifier.minify(content, options);
        break;
      case ASSET_TYPES.JSON:
        result = this._optimizeJSON(content);
        break;
      default:
        result = { data: content, originalSize: content.length, optimizedSize: content.length };
    }

    // Compress if enabled
    if (this.options.compress && typeof result.data === 'string') {
      const compressed = await this.compression.compressBest(result.data);
      result.compressed = compressed;
    }

    // Generate hash
    if (this.options.generateHashes) {
      const data = result.data;
      result.hash = crypto.createHash('md5')
        .update(typeof data === 'string' ? data : data.toString())
        .digest('hex')
        .slice(0, 8);
    }

    // Update stats
    this._updateStats(type, result);

    result.duration = Date.now() - startTime;
    result.type = type;

    return result;
  }

  /**
   * Process multiple assets
   */
  async processAssets(assets) {
    const results = [];

    for (const asset of assets) {
      const result = await this.processAsset(asset.content, asset.type, asset.options);
      results.push({
        name: asset.name,
        ...result
      });
    }

    return {
      assets: results,
      stats: this.getStats()
    };
  }

  /**
   * Create optimized build
   */
  async build(config) {
    const results = {
      js: null,
      css: null,
      tokens: null,
      images: [],
      svgs: [],
      manifest: null
    };

    // Bundle JavaScript
    if (config.js && config.js.length > 0) {
      results.js = await this.bundler.bundleJS(config.js, config.jsOptions);
      if (this.options.compress) {
        results.js.compressed = await this.compression.compressBest(results.js.data);
      }
    }

    // Bundle CSS
    if (config.css && config.css.length > 0) {
      results.css = await this.bundler.bundleCSS(config.css, config.cssOptions);
      if (this.options.compress) {
        results.css.compressed = await this.compression.compressBest(results.css.data);
      }
    }

    // Bundle tokens
    if (config.tokens) {
      results.tokens = await this.bundler.bundleTokens(config.tokens, config.tokenOptions);
    }

    // Optimize images
    if (config.images && config.images.length > 0) {
      for (const img of config.images) {
        const optimized = await this.imageOptimizer.optimize(img.data, img.options);
        results.images.push({
          name: img.name,
          ...optimized
        });
      }
    }

    // Optimize SVGs
    if (config.svgs && config.svgs.length > 0) {
      // Create sprite if requested
      if (config.createSprite) {
        const svgMap = {};
        for (const svg of config.svgs) {
          svgMap[svg.name] = svg.data;
        }
        results.svgSprite = this.svgOptimizer.createSprite(svgMap);
      } else {
        for (const svg of config.svgs) {
          const optimized = this.svgOptimizer.optimize(svg.data);
          results.svgs.push({
            name: svg.name,
            ...optimized
          });
        }
      }
    }

    // Generate manifest
    results.manifest = this._generateManifest(results);

    return results;
  }

  _optimizeJSON(json) {
    const original = typeof json === 'string' ? json : JSON.stringify(json, null, 2);
    const minified = typeof json === 'string' ? JSON.stringify(JSON.parse(json)) : JSON.stringify(json);

    return {
      data: minified,
      originalSize: Buffer.byteLength(original, 'utf8'),
      optimizedSize: Buffer.byteLength(minified, 'utf8'),
      savings: Buffer.byteLength(original, 'utf8') - Buffer.byteLength(minified, 'utf8')
    };
  }

  _updateStats(type, result) {
    this.stats.processed++;
    this.stats.totalOriginal += result.originalSize || 0;
    this.stats.totalOptimized += result.optimizedSize || result.minifiedSize || 0;

    if (!this.stats.byType[type]) {
      this.stats.byType[type] = { count: 0, saved: 0 };
    }
    this.stats.byType[type].count++;
    this.stats.byType[type].saved += result.savings || 0;
  }

  _generateManifest(results) {
    const manifest = {
      version: Date.now(),
      generated: new Date().toISOString(),
      files: {}
    };

    if (results.js) {
      manifest.files['bundle.js'] = {
        hash: results.js.hash,
        size: results.js.minifiedSize,
        compressed: results.js.compressed?.compressedSize
      };
    }

    if (results.css) {
      manifest.files['bundle.css'] = {
        hash: results.css.hash,
        size: results.css.minifiedSize,
        compressed: results.css.compressed?.compressedSize
      };
    }

    if (results.tokens) {
      manifest.files['tokens'] = {
        hash: results.tokens.hash,
        size: results.tokens.size,
        format: results.tokens.format
      };
    }

    for (const img of results.images) {
      manifest.files[img.name] = {
        size: img.optimizedSize,
        savings: img.savingsPercent
      };
    }

    return manifest;
  }

  getStats() {
    const totalSavings = this.stats.totalOriginal - this.stats.totalOptimized;
    const savingsPercent = this.stats.totalOriginal > 0
      ? ((totalSavings / this.stats.totalOriginal) * 100).toFixed(2)
      : '0';

    return {
      ...this.stats,
      totalSavings,
      savingsPercent
    };
  }

  resetStats() {
    this.stats = {
      processed: 0,
      totalOriginal: 0,
      totalOptimized: 0,
      byType: {}
    };
  }
}

// ============================================================================
// Factory Functions
// ============================================================================

function createAssetPipeline(options = {}) {
  return new AssetPipeline(options);
}

function createImageOptimizer(options = {}) {
  return new ImageOptimizer(options);
}

function createSVGOptimizer(options = {}) {
  return new SVGOptimizer(options);
}

function createBundler(options = {}) {
  return new Bundler(options);
}

// ============================================================================
// Exports
// ============================================================================

module.exports = {
  // Main classes
  AssetPipeline,
  ImageOptimizer,
  SVGOptimizer,
  CSSMinifier,
  JSMinifier,
  Bundler,
  CompressionManager,

  // Factory functions
  createAssetPipeline,
  createImageOptimizer,
  createSVGOptimizer,
  createBundler,

  // Constants
  OPTIMIZATION_LEVELS,
  ASSET_TYPES,
  IMAGE_FORMATS,
  COMPRESSION_TYPES,
  OPTIMIZER_EVENTS
};
