const fs = require('fs').promises;
const fsSync = require('fs');
const path = require('path');
const { getComponentPageRouter } = require('../../../design-catalog/component-page-router');
const { getPatternLibrary } = require('./pattern-library');

/**
 * Design Catalog Data Bridge (Phase 10)
 *
 * DATA CONVERTER APPROACH
 * - Reads .bumba/design-data.json (Figma format from plugin/MCPs)
 * - Converts to .design/catalog-data.json (catalog format)
 * - Client-side catalog-updater.js reads catalog-data.json and renders dynamically
 * - Routes components to appropriate pages using ComponentPageRouter
 *
 * Source-agnostic: Works with Figma Plugin, MCPs, or manual edits
 */
class CatalogGenerator {
  /**
   * Generate catalog data from design data
   * This is a DATA BRIDGE - it converts formats, not HTML
   */
  async generate({ projectDir, data, routeComponents = true }) {
    const catalogDir = path.join(projectDir, '.design');

    // Verify catalog exists
    if (!fsSync.existsSync(catalogDir)) {
      console.error('Design catalog not found. Run bumba init first.');
      return;
    }

    // Convert Figma format to catalog format
    const catalogData = this.convertToCatalogFormat(data);

    // Write to catalog-data.json (client-side will read this)
    const catalogDataPath = path.join(catalogDir, 'catalog-data.json');
    await fs.writeFile(catalogDataPath, JSON.stringify(catalogData, null, 2));

    console.log('✓ Catalog data updated:', catalogDataPath);

    // Route components to pages (NEW!)
    if (routeComponents && data.components && data.components.length > 0) {
      await this.routeComponentsToPages(data.components, { projectDir });
    }
  }

  /**
   * Route components to appropriate catalog pages
   * Uses Pattern Library + Component Page Router
   * @param {Array} components - Array of components
   * @param {Object} options - Routing options
   * @returns {Promise<Object>} Routing summary
   */
  async routeComponentsToPages(components, options = {}) {
    const router = getComponentPageRouter({ catalogDir: options.catalogDir });
    const patternLibrary = getPatternLibrary();

    const results = {
      routed: 0,
      created: 0,
      variants: 0,
      failed: 0,
      details: []
    };

    console.log(`\n📍 Routing ${components.length} component(s) to catalog pages...\n`);

    for (const component of components) {
      try {
        // Detect pattern type
        const detectedPatterns = patternLibrary.detectPatterns(component);
        const patternType = detectedPatterns[0]?.type || 'unknown';

        // Route to page
        const result = await router.route(component, patternType, {
          autoCreate: true // Allow auto-creating new pages
        });

        if (result.success) {
          switch (result.action) {
            case 'routed':
              results.routed++;
              console.log(`  ✓ ${component.name} → ${result.page}`);
              break;
            case 'created':
              results.created++;
              console.log(`  ✨ Created ${result.page} → Added ${component.name}`);
              break;
            case 'added-variant':
              results.variants++;
              console.log(`  🔄 ${component.name} v${result.existingVersion + 1} → ${result.page}`);
              break;
          }
        } else {
          results.failed++;
          console.log(`  ✗ Failed to route ${component.name}: ${result.error}`);
        }

        results.details.push(result);
      } catch (error) {
        results.failed++;
        console.log(`  ✗ Error routing ${component.name}: ${error.message}`);
      }
    }

    // Summary
    console.log(`\n📊 Routing Summary:`);
    console.log(`   Routed to existing pages: ${results.routed}`);
    console.log(`   Created new pages: ${results.created}`);
    console.log(`   Added as variants: ${results.variants}`);
    console.log(`   Failed: ${results.failed}`);
    console.log('');

    return results;
  }

  /**
   * Convert design-data.json (Figma format) to catalog-data.json (catalog format)
   */
  convertToCatalogFormat(data) {
    const { tokens, components, metadata } = data;

    return {
      metadata: {
        projectName: metadata?.projectName || metadata?.fileName || 'Design System',
        lastUpdated: new Date().toISOString(),
        tokenCount: this.countTokens(tokens),
        componentCount: components?.length || 0,
        source: metadata?.source || 'unknown',
        version: metadata?.version || '1.0.0'
      },
      tokens: {
        colors: this.convertColors(tokens?.colors || {}),
        typography: this.convertTypography(tokens?.typography || {}),
        spacing: this.convertSpacing(tokens?.spacing || {}),
        effects: this.convertEffects(tokens?.effects || {}),
        borders: this.convertBorders(tokens?.borders || {})
      },
      components: this.convertComponents(components || [])
    };
  }

  /**
   * Convert colors from Figma format to catalog format
   *
   * INPUT (Figma): { "primary-500": { paints: [{ type: "SOLID", color: { r, g, b } }] } }
   * OUTPUT (Catalog): { "primary-500": "#3366CC" }
   */
  convertColors(figmaColors) {
    const catalogColors = {};

    for (const [name, colorData] of Object.entries(figmaColors)) {
      // If already in simple format (from manual edit or MCP)
      if (typeof colorData === 'string') {
        catalogColors[name] = colorData;
        continue;
      }

      // Handle Figma format with paints array
      if (colorData.paints && colorData.paints[0]) {
        const paint = colorData.paints[0];
        if (paint.type === 'SOLID' && paint.color) {
          catalogColors[name] = this.rgbToHex(paint.color);
          continue;
        }
      }

      // Handle direct RGB object
      if (colorData.r !== undefined) {
        catalogColors[name] = this.rgbToHex(colorData);
        continue;
      }

      // Fallback
      catalogColors[name] = '#CCCCCC';
    }

    return catalogColors;
  }

  /**
   * Convert typography from Figma format to catalog format
   *
   * INPUT (Figma): { fontSize: 32, fontName: { family: "Inter" }, fontWeight: 700 }
   * OUTPUT (Catalog): { fontFamily: "Inter", fontSize: "32px", fontWeight: "700" }
   */
  convertTypography(figmaTypography) {
    const catalogTypography = {};

    for (const [name, typeData] of Object.entries(figmaTypography)) {
      catalogTypography[name] = {
        fontFamily: typeData.fontName?.family || typeData.fontFamily || 'Inter',
        fontSize: this.ensurePixels(typeData.fontSize),
        fontWeight: String(typeData.fontWeight || '400'),
        lineHeight: this.ensureLineHeight(typeData.lineHeight)
      };
    }

    return catalogTypography;
  }

  /**
   * Convert spacing from Figma format to catalog format
   *
   * INPUT (Figma): { values: { "space-4": 16 } } or { "space-4": 16 }
   * OUTPUT (Catalog): { "space-4": "16px" }
   */
  convertSpacing(figmaSpacing) {
    const catalogSpacing = {};

    // Handle nested values object
    const spacingValues = figmaSpacing.values || figmaSpacing;

    for (const [name, value] of Object.entries(spacingValues)) {
      catalogSpacing[name] = this.ensurePixels(value);
    }

    return catalogSpacing;
  }

  /**
   * Convert effects (shadows) from Figma format to catalog format
   *
   * INPUT (Figma): { effects: [{ type: "DROP_SHADOW", offset: { x, y }, radius, color }] }
   * OUTPUT (Catalog): { "shadow-name": "0px 4px 8px rgba(0,0,0,0.15)" }
   */
  convertEffects(figmaEffects) {
    const catalogEffects = {};

    for (const [name, effectData] of Object.entries(figmaEffects)) {
      // If already in CSS format
      if (typeof effectData === 'string') {
        catalogEffects[name] = effectData;
        continue;
      }

      // Handle Figma effects array
      if (effectData.effects && effectData.effects[0]) {
        const effect = effectData.effects[0];
        if (effect.type === 'DROP_SHADOW') {
          catalogEffects[name] = this.shadowToCSS(effect);
          continue;
        }
      }

      // Handle direct effect object
      if (effectData.type === 'DROP_SHADOW' || effectData.offset) {
        catalogEffects[name] = this.shadowToCSS(effectData);
        continue;
      }

      // Fallback
      catalogEffects[name] = '0px 2px 4px rgba(0,0,0,0.1)';
    }

    return catalogEffects;
  }

  /**
   * Convert borders from Figma format to catalog format
   *
   * INPUT (Figma): { strokeWeight: 2, color: { r, g, b } }
   * OUTPUT (Catalog): { "border-name": "2px solid #CCCCCC" }
   */
  convertBorders(figmaBorders) {
    const catalogBorders = {};

    for (const [name, borderData] of Object.entries(figmaBorders)) {
      // If already in CSS format
      if (typeof borderData === 'string') {
        catalogBorders[name] = borderData;
        continue;
      }

      const width = this.ensurePixels(borderData.strokeWeight || borderData.width || 1);
      const style = borderData.style || 'solid';
      const color = borderData.color ? this.rgbToHex(borderData.color) : '#CCCCCC';

      catalogBorders[name] = `${width} ${style} ${color}`;
    }

    return catalogBorders;
  }

  /**
   * Convert components array to catalog format
   */
  convertComponents(figmaComponents) {
    return figmaComponents.map(component => ({
      id: component.id,
      name: component.name,
      type: component.type,
      description: component.description || `A ${component.name} component`,
      variants: component.variants || {},
      metadata: {
        width: component.bounds?.width || component.absoluteBoundingBox?.width || 0,
        height: component.bounds?.height || component.absoluteBoundingBox?.height || 0,
        variantCount: component.variants ? Object.keys(component.variants).length : 0
      }
    }));
  }

  /**
   * HELPER: Convert Figma RGB (0-1) to hex
   */
  rgbToHex(rgb) {
    const r = Math.round((rgb.r || 0) * 255);
    const g = Math.round((rgb.g || 0) * 255);
    const b = Math.round((rgb.b || 0) * 255);

    if (rgb.a !== undefined && rgb.a < 1) {
      return `rgba(${r}, ${g}, ${b}, ${rgb.a})`;
    }

    return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`.toUpperCase();
  }

  /**
   * HELPER: Ensure value is in pixels
   */
  ensurePixels(value) {
    if (typeof value === 'string') {
      return value.includes('px') ? value : `${value}px`;
    }
    if (typeof value === 'number') {
      return `${value}px`;
    }
    return '0px';
  }

  /**
   * HELPER: Ensure line height is formatted
   */
  ensureLineHeight(value) {
    if (!value) return '1.5';
    if (typeof value === 'string') return value;
    if (typeof value === 'number') {
      // If > 10, likely pixels, convert to unitless
      return value > 10 ? String(value / 16) : String(value);
    }
    return '1.5';
  }

  /**
   * HELPER: Convert Figma shadow to CSS box-shadow
   */
  shadowToCSS(effect) {
    const x = effect.offset?.x || effect.x || 0;
    const y = effect.offset?.y || effect.y || 0;
    const blur = effect.radius || effect.blur || 0;
    const spread = effect.spread || 0;
    const color = effect.color ? this.rgbToHex(effect.color) : 'rgba(0,0,0,0.15)';

    return `${x}px ${y}px ${blur}px ${spread}px ${color}`;
  }

  /**
   * HELPER: Count total tokens
   */
  countTokens(tokens) {
    if (!tokens) return 0;

    let count = 0;
    for (const category of Object.values(tokens)) {
      if (typeof category === 'object' && category !== null) {
        // Handle nested values (like spacing.values)
        if (category.values) {
          count += Object.keys(category.values).length;
        } else {
          count += Object.keys(category).length;
        }
      }
    }
    return count;
  }
}

module.exports = new CatalogGenerator();
