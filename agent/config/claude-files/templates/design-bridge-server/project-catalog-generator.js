const fs = require('fs').promises;
const fsSync = require('fs');
const path = require('path');

/**
 * Project Catalog Data Bridge (Phase 10)
 *
 * DATA CONVERTER APPROACH (same as .design/ catalog)
 * - Reads .bumba/design-data.json (Figma format from plugin/MCPs)
 * - Converts to design-catalog/catalog-data.json (catalog format)
 * - Client-side JavaScript reads catalog-data.json and renders dynamically
 *
 * Source-agnostic: Works with Figma Plugin, MCPs, or manual edits
 */
class ProjectCatalogGenerator {
  /**
   * Generate catalog data from design data
   * This is a DATA BRIDGE - it converts formats, not HTML
   */
  async generate({ projectDir, data }) {
    const catalogDir = path.join(projectDir, 'design-catalog');

    // Verify catalog exists
    if (!fsSync.existsSync(catalogDir)) {
      console.error('Project catalog not found. Run bumba init first.');
      return;
    }

    // Convert Figma format to catalog format (reuse the same conversion logic)
    const catalogData = this.convertToCatalogFormat(data);

    // Write to catalog-data.json (client-side will read this)
    const catalogDataPath = path.join(catalogDir, 'catalog-data.json');
    await fs.writeFile(catalogDataPath, JSON.stringify(catalogData, null, 2));

    console.log('✓ Project catalog data updated:', catalogDataPath);
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
   */
  convertColors(figmaColors) {
    const catalogColors = {};

    for (const [name, colorData] of Object.entries(figmaColors)) {
      if (typeof colorData === 'string') {
        catalogColors[name] = colorData;
        continue;
      }

      if (colorData.paints && colorData.paints[0]) {
        const paint = colorData.paints[0];
        if (paint.type === 'SOLID' && paint.color) {
          catalogColors[name] = this.rgbToHex(paint.color);
          continue;
        }
      }

      if (colorData.r !== undefined) {
        catalogColors[name] = this.rgbToHex(colorData);
        continue;
      }

      catalogColors[name] = '#CCCCCC';
    }

    return catalogColors;
  }

  /**
   * Convert RGB (0-1) to hex
   */
  rgbToHex(rgb) {
    const r = Math.round((rgb.r || 0) * 255);
    const g = Math.round((rgb.g || 0) * 255);
    const b = Math.round((rgb.b || 0) * 255);
    return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`.toUpperCase();
  }

  /**
   * Convert typography
   */
  convertTypography(figmaTypography) {
    const catalogTypography = {};

    for (const [name, style] of Object.entries(figmaTypography)) {
      catalogTypography[name] = {
        fontFamily: style.fontName?.family || style.fontFamily || 'Inter',
        fontSize: style.fontSize ? `${style.fontSize}px` : '16px',
        fontWeight: style.fontWeight || '400',
        lineHeight: style.lineHeight || '1.5'
      };
    }

    return catalogTypography;
  }

  /**
   * Convert spacing
   */
  convertSpacing(figmaSpacing) {
    const catalogSpacing = {};
    const spacingValues = figmaSpacing?.values || figmaSpacing || {};

    for (const [name, value] of Object.entries(spacingValues)) {
      if (typeof value === 'number') {
        catalogSpacing[name] = `${value}px`;
      } else if (typeof value === 'string') {
        catalogSpacing[name] = value;
      }
    }

    return catalogSpacing;
  }

  /**
   * Convert effects (shadows)
   */
  convertEffects(figmaEffects) {
    const catalogEffects = {};

    for (const [name, effect] of Object.entries(figmaEffects)) {
      if (typeof effect === 'string') {
        catalogEffects[name] = effect;
        continue;
      }

      if (effect.effects && effect.effects[0] && effect.effects[0].type === 'DROP_SHADOW') {
        const e = effect.effects[0];
        const x = e.offset?.x || 0;
        const y = e.offset?.y || 0;
        const blur = e.radius || 0;
        const color = e.color;
        
        if (color) {
          const r = Math.round((color.r || 0) * 255);
          const g = Math.round((color.g || 0) * 255);
          const b = Math.round((color.b || 0) * 255);
          const a = color.a !== undefined ? color.a : 1;
          catalogEffects[name] = `${x}px ${y}px ${blur}px rgba(${r}, ${g}, ${b}, ${a})`;
        }
      } else {
        catalogEffects[name] = '0 0 0 rgba(0,0,0,0)';
      }
    }

    return catalogEffects;
  }

  /**
   * Convert borders
   */
  convertBorders(figmaBorders) {
    const catalogBorders = {};

    for (const [name, border] of Object.entries(figmaBorders)) {
      if (typeof border === 'string') {
        catalogBorders[name] = border;
      } else if (border.width && border.color) {
        const color = this.rgbToHex(border.color);
        catalogBorders[name] = `${border.width}px solid ${color}`;
      }
    }

    return catalogBorders;
  }

  /**
   * Convert components
   */
  convertComponents(figmaComponents) {
    return figmaComponents.map(comp => ({
      name: comp.name,
      type: comp.type,
      variants: comp.variants || {},
      bounds: comp.bounds || {}
    }));
  }

  /**
   * Count tokens
   */
  countTokens(tokens) {
    if (!tokens) return 0;
    
    return Object.keys(tokens.colors || {}).length +
           Object.keys(tokens.typography || {}).length +
           Object.keys(tokens.spacing?.values || tokens.spacing || {}).length +
           Object.keys(tokens.effects || {}).length +
           Object.keys(tokens.borders || {}).length;
  }
}

module.exports = new ProjectCatalogGenerator();
