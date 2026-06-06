/**
 * Component Content Extractor
 *
 * Framework-agnostic deep content extraction from Figma component JSON
 * Extracts full component tree including nested components, text, images, and props
 *
 * Used by ALL design-transform-* skills to ensure complete content extraction
 */

const fs = require('fs');
const path = require('path');

class ComponentContentExtractor {
  constructor(projectPath, registry) {
    this.projectPath = projectPath;
    this.registry = registry;
    this.extractedContent = new Map();
  }

  /**
   * Extract complete content tree from component JSON
   *
   * @param {Object} componentJson - Figma component JSON
   * @param {Object} options - Extraction options
   * @returns {Object} Extracted content structure
   */
  extractContent(componentJson, options = {}) {
    const {
      depth = Infinity,
      includeText = true,
      includeImages = true,
      includeVariants = true,
      resolveNestedComponents = true
    } = options;

    return this._traverseNode(componentJson, {
      depth,
      currentDepth: 0,
      includeText,
      includeImages,
      includeVariants,
      resolveNestedComponents
    });
  }

  /**
   * Traverse component node tree recursively
   */
  _traverseNode(node, context) {
    if (context.currentDepth >= context.depth) {
      return null;
    }

    const extracted = {
      id: node.id,
      name: node.name,
      type: node.type,
      visible: node.visible !== false,
      dimensions: {
        width: node.width,
        height: node.height,
        x: node.x || 0,
        y: node.y || 0
      },
      styles: this._extractStyles(node),
      content: null,
      children: []
    };

    // Extract text content
    if (context.includeText && node.type === 'TEXT') {
      extracted.content = {
        type: 'text',
        value: node.characters || '',
        style: this._extractTextStyle(node)
      };
    }

    // Extract image content
    if (context.includeImages && (node.type === 'RECTANGLE' || node.type === 'FRAME')) {
      const imageFill = this._extractImageFill(node);
      if (imageFill) {
        extracted.content = {
          type: 'image',
          ...imageFill
        };
      }
    }

    // Handle component instances
    if (node.type === 'INSTANCE' && context.resolveNestedComponents) {
      const nestedComponent = this._resolveNestedComponent(node);
      if (nestedComponent) {
        extracted.nestedComponent = nestedComponent;
      }
    }

    // Extract variants
    if (context.includeVariants && node.componentProperties) {
      extracted.variants = this._extractVariants(node.componentProperties);
    }

    // Recursively extract children
    if (node.children && Array.isArray(node.children)) {
      extracted.children = node.children
        .map(child => this._traverseNode(child, {
          ...context,
          currentDepth: context.currentDepth + 1
        }))
        .filter(child => child !== null && child.visible);
    }

    return extracted;
  }

  /**
   * Extract style properties (fills, strokes, effects, layout)
   */
  _extractStyles(node) {
    const styles = {};

    // Layout properties
    if (node.layoutMode) {
      styles.layout = {
        mode: node.layoutMode, // HORIZONTAL, VERTICAL, NONE
        primaryAxisAlignItems: node.primaryAxisAlignItems,
        counterAxisAlignItems: node.counterAxisAlignItems,
        primaryAxisSizingMode: node.primaryAxisSizingMode,
        counterAxisSizingMode: node.counterAxisSizingMode,
        itemSpacing: node.itemSpacing,
        padding: {
          top: node.paddingTop || 0,
          right: node.paddingRight || 0,
          bottom: node.paddingBottom || 0,
          left: node.paddingLeft || 0
        }
      };
    }

    // Fills (background colors, gradients, images)
    if (node.fills && Array.isArray(node.fills)) {
      styles.fills = node.fills
        .filter(fill => fill.visible !== false)
        .map(fill => this._extractFill(fill));
    }

    // Strokes (borders)
    if (node.strokes && Array.isArray(node.strokes)) {
      styles.strokes = node.strokes
        .filter(stroke => stroke.visible !== false)
        .map(stroke => this._extractFill(stroke));
      styles.strokeWeight = node.strokeWeight;
    }

    // Effects (shadows, blurs)
    if (node.effects && Array.isArray(node.effects)) {
      styles.effects = node.effects
        .filter(effect => effect.visible !== false)
        .map(effect => this._extractEffect(effect));
    }

    // Border radius
    if (node.cornerRadius !== undefined) {
      styles.borderRadius = node.cornerRadius;
    }

    // Opacity
    if (node.opacity !== undefined && node.opacity !== 1) {
      styles.opacity = node.opacity;
    }

    return styles;
  }

  /**
   * Extract fill properties (solid, gradient, image)
   */
  _extractFill(fill) {
    const extracted = {
      type: fill.type, // SOLID, GRADIENT_LINEAR, GRADIENT_RADIAL, IMAGE
      opacity: fill.opacity !== undefined ? fill.opacity : 1
    };

    if (fill.type === 'SOLID' && fill.color) {
      extracted.color = this._rgbaToHex(fill.color, fill.opacity);
    } else if (fill.type.startsWith('GRADIENT') && fill.gradientStops) {
      extracted.gradient = {
        type: fill.type,
        stops: fill.gradientStops.map(stop => ({
          position: stop.position,
          color: this._rgbaToHex(stop.color, 1)
        }))
      };
    } else if (fill.type === 'IMAGE' && fill.imageRef) {
      extracted.imageRef = fill.imageRef;
      extracted.scaleMode = fill.scaleMode;
    }

    return extracted;
  }

  /**
   * Extract image fill from node
   */
  _extractImageFill(node) {
    if (!node.fills) return null;

    const imageFill = node.fills.find(fill => fill.type === 'IMAGE' && fill.visible !== false);
    if (!imageFill) return null;

    return {
      imageRef: imageFill.imageRef,
      scaleMode: imageFill.scaleMode,
      imageHash: imageFill.imageHash
    };
  }

  /**
   * Extract text style properties
   */
  _extractTextStyle(node) {
    return {
      fontFamily: node.fontName?.family,
      fontWeight: node.fontName?.style,
      fontSize: node.fontSize,
      lineHeight: node.lineHeight,
      letterSpacing: node.letterSpacing,
      textAlign: node.textAlignHorizontal,
      textDecoration: node.textDecoration,
      textCase: node.textCase,
      fills: node.fills ? node.fills.map(fill => this._extractFill(fill)) : []
    };
  }

  /**
   * Extract effect properties (shadows, blurs)
   */
  _extractEffect(effect) {
    const extracted = {
      type: effect.type // DROP_SHADOW, INNER_SHADOW, LAYER_BLUR, BACKGROUND_BLUR
    };

    if (effect.type.includes('SHADOW')) {
      extracted.color = this._rgbaToHex(effect.color, 1);
      extracted.offset = effect.offset;
      extracted.radius = effect.radius;
      extracted.spread = effect.spread;
    } else if (effect.type.includes('BLUR')) {
      extracted.radius = effect.radius;
    }

    return extracted;
  }

  /**
   * Extract variant properties
   */
  _extractVariants(componentProperties) {
    const variants = {};

    for (const [key, value] of Object.entries(componentProperties)) {
      variants[key] = value.value;
    }

    return variants;
  }

  /**
   * Resolve nested component from registry
   */
  _resolveNestedComponent(instanceNode) {
    // Try to find component in registry by node ID or name
    const componentName = instanceNode.name;
    const componentId = instanceNode.mainComponent?.id || instanceNode.componentId;

    // Search registry
    const registryEntry = this._findInRegistry(componentName, componentId);

    if (!registryEntry) {
      return {
        name: componentName,
        id: componentId,
        resolved: false,
        reason: 'not_in_registry'
      };
    }

    if (registryEntry.transformation.state !== 'code-generated') {
      return {
        name: componentName,
        id: componentId,
        resolved: false,
        reason: 'not_transformed',
        state: registryEntry.transformation.state
      };
    }

    return {
      name: componentName,
      id: componentId,
      resolved: true,
      registryId: registryEntry.id,
      filePath: registryEntry.transformation.codePath,
      importPath: this._getImportPath(registryEntry.transformation.codePath)
    };
  }

  /**
   * Find component in registry
   */
  _findInRegistry(name, id) {
    if (!this.registry || !this.registry.components) return null;

    const components = Object.values(this.registry.components);

    // Try to find by ID first
    if (id) {
      const byId = components.find(c => c.source?.nodeId === id);
      if (byId) return byId;
    }

    // Fallback to name matching (case-insensitive)
    // Supports hybrid schema: canonicalName, figmaName, or name field
    const normalizedName = name.toLowerCase().replace(/\s+/g, '');
    return components.find(c => {
      // Try canonical name first (hybrid schema)
      if (c.canonicalName) {
        const normalizedCanonical = c.canonicalName.toLowerCase().replace(/\s+/g, '');
        if (normalizedCanonical === normalizedName) return true;
      }

      // Try figmaName (hybrid schema)
      if (c.figmaName) {
        const normalizedFigma = c.figmaName.toLowerCase().replace(/\s+/g, '');
        if (normalizedFigma === normalizedName) return true;
      }

      // Try old name field (v3.0.0 compatibility)
      if (c.name) {
        const normalizedOldName = c.name.toLowerCase().replace(/\s+/g, '');
        if (normalizedOldName === normalizedName) return true;
      }

      return false;
    });
  }

  /**
   * Get import path relative to project
   */
  _getImportPath(filePath) {
    if (!filePath) return null;

    // Extract just the filename without path or extension
    // Components are in the same directory, so use relative import
    const filename = path.basename(filePath, path.extname(filePath));
    return `./${filename}`;
  }

  /**
   * Convert RGBA color to hex
   */
  _rgbaToHex(color, opacity = 1) {
    if (!color) return '#000000';

    const r = Math.round(color.r * 255);
    const g = Math.round(color.g * 255);
    const b = Math.round(color.b * 255);
    const a = opacity !== undefined ? opacity : (color.a !== undefined ? color.a : 1);

    const hex = '#' + [r, g, b]
      .map(x => x.toString(16).padStart(2, '0'))
      .join('');

    return a < 1 ? `${hex}${Math.round(a * 255).toString(16).padStart(2, '0')}` : hex;
  }

  /**
   * Generate dependency report
   */
  generateDependencyReport(extractedContent) {
    const dependencies = {
      resolved: [],
      unresolved: [],
      missingTransformations: []
    };

    const traverse = (node) => {
      if (node.nestedComponent) {
        if (node.nestedComponent.resolved) {
          dependencies.resolved.push(node.nestedComponent);
        } else if (node.nestedComponent.reason === 'not_transformed') {
          dependencies.missingTransformations.push(node.nestedComponent);
        } else {
          dependencies.unresolved.push(node.nestedComponent);
        }
      }

      if (node.children) {
        node.children.forEach(traverse);
      }
    };

    traverse(extractedContent);

    return dependencies;
  }
}

module.exports = ComponentContentExtractor;
