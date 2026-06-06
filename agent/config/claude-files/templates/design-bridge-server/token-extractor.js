/**
 * BUMBA Token Extractor
 * Extracts design tokens from Figma designs
 */

const { logger } = require('../logging/bumba-logger');

class TokenExtractor {
  constructor(config = {}) {
    this.config = {
      precision: config.precision || 2,
      units: config.units || 'px',
      colorFormat: config.colorFormat || 'hex',
      ...config
    };

    this.tokens = {
      colors: {},
      typography: {},
      spacing: {},
      shadows: {},
      borders: {},
      radii: {},
      breakpoints: {},
      animations: {},
      gradients: {},      // Sprint 7.2: Gradient tokens
      variables: {},      // Sprint 7.3: Figma Variables
      variableModes: {},  // Sprint 7.3: Mode-specific values (light/dark)
      componentVars: {},  // Sprint 7.4: Component-variable associations
      grids: {}           // Sprint 7.5: Full grid definitions
    };
  }

  /**
   * Extract all tokens from Figma data
   */
  extract(figmaData) {
    try {
      this.reset();

      // Extract from different sources
      if (figmaData.styles) {
        this.extractFromStyles(figmaData.styles);
      }

      if (figmaData.document) {
        this.extractFromDocument(figmaData.document);
      }

      if (figmaData.components) {
        this.extractFromComponents(figmaData.components, figmaData.variables);
      }

      // Sprint 7.3: Extract Figma Variables
      if (figmaData.variables) {
        this.extractVariables(figmaData.variables);
      }

      return this.formatTokens();

    } catch (error) {
      logger.error('Failed to extract tokens:', error);
      throw error;
    }
  }

  /**
   * Extract tokens from Figma styles
   */
  extractFromStyles(styles) {
    // Extract color styles
    if (styles.colors) {
      Object.entries(styles.colors).forEach(([name, style]) => {
        this.tokens.colors[this.formatTokenName(name)] = this.extractColorValue(style);
      });
    }

    // Extract text styles
    if (styles.text) {
      Object.entries(styles.text).forEach(([name, style]) => {
        this.tokens.typography[this.formatTokenName(name)] = this.extractTextStyle(style);
      });
    }

    // Extract effect styles (shadows, blurs)
    if (styles.effects) {
      Object.entries(styles.effects).forEach(([name, style]) => {
        const effect = this.extractEffect(style);
        if (effect.type === 'shadow') {
          this.tokens.shadows[this.formatTokenName(name)] = effect.value;
        }
      });
    }

    // Extract grid styles (Sprint 7.5: Store in grids token, not spacing)
    if (styles.grids) {
      Object.entries(styles.grids).forEach(([name, style]) => {
        const gridData = this.extractGridStyle(style, name);
        if (gridData) {
          this.tokens.grids[this.formatTokenName(name)] = gridData;
        }
      });
    }

    // Sprint 7.2: Extract gradient styles from fill styles
    if (styles.fills) {
      Object.entries(styles.fills).forEach(([name, style]) => {
        if (style.fills && Array.isArray(style.fills)) {
          style.fills.forEach(fill => {
            if (fill.type && fill.type.startsWith('GRADIENT_')) {
              const gradient = this.extractGradient(fill);
              if (gradient) {
                this.tokens.gradients[this.formatTokenName(name)] = gradient;
              }
            }
          });
        }
      });
    }
  }

  /**
   * Extract tokens from document
   */
  extractFromDocument(document) {
    this.traverseNode(document, (node) => {
      // Extract colors from fills
      if (node.fills && Array.isArray(node.fills)) {
        node.fills.forEach(fill => {
          if (fill.type === 'SOLID') {
            const colorKey = this.generateColorKey(fill.color);
            this.tokens.colors[colorKey] = this.extractColorValue(fill.color);
          }

          // Sprint 7.2: Extract gradient fills
          if (fill.type && fill.type.startsWith('GRADIENT_')) {
            const gradient = this.extractGradient(fill);
            if (gradient) {
              const gradientKey = this.generateGradientKey(gradient);
              this.tokens.gradients[gradientKey] = gradient;
            }
          }
        });
      }

      // Extract typography from text nodes
      if (node.type === 'TEXT') {
        this.extractTextNode(node);
      }

      // Extract spacing from auto-layout
      if (node.layoutMode) {
        this.extractLayoutSpacing(node);
      }

      // Extract border radius
      if (node.cornerRadius !== undefined) {
        const radiusKey = `radius-${Math.round(node.cornerRadius)}`;
        this.tokens.radii[radiusKey] = `${node.cornerRadius}${this.config.units}`;
      }

      // Extract borders from strokes
      if (node.strokes && node.strokeWeight) {
        this.extractBorder(node);
      }

      // Sprint 7.5: Extract grids from frames
      if (node.layoutGrids && node.layoutGrids.length > 0) {
        const nodeGrids = this.extractGridsFromNode(node);
        if (nodeGrids) {
          Object.assign(this.tokens.grids, nodeGrids);
        }
      }
    });
  }

  /**
   * Extract tokens from components
   * Sprint 7.4: Added variablesData parameter for component-variable binding extraction
   */
  extractFromComponents(components, variablesData = null) {
    components.forEach(component => {
      // Extract component-specific tokens
      if (component.name && component.properties) {
        this.extractComponentTokens(component);
      }

      // Sprint 7.4: Extract component variable bindings
      if (variablesData) {
        this.extractComponentVariables(component, variablesData);
      }
    });
  }

  /**
   * Extract color value
   */
  extractColorValue(color) {
    if (!color) return null;

    const r = Math.round((color.r || 0) * 255);
    const g = Math.round((color.g || 0) * 255);
    const b = Math.round((color.b || 0) * 255);
    const a = color.a !== undefined ? color.a : 1;

    switch (this.config.colorFormat) {
      case 'hex':
        return a === 1
          ? `#${this.toHex(r)}${this.toHex(g)}${this.toHex(b)}`
          : `#${this.toHex(r)}${this.toHex(g)}${this.toHex(b)}${this.toHex(Math.round(a * 255))}`;

      case 'rgb':
        return a === 1
          ? `rgb(${r}, ${g}, ${b})`
          : `rgba(${r}, ${g}, ${b}, ${a})`;

      case 'hsl':
        const hsl = this.rgbToHsl(r, g, b);
        return a === 1
          ? `hsl(${hsl.h}, ${hsl.s}%, ${hsl.l}%)`
          : `hsla(${hsl.h}, ${hsl.s}%, ${hsl.l}%, ${a})`;

      default:
        return `#${this.toHex(r)}${this.toHex(g)}${this.toHex(b)}`;
    }
  }

  /**
   * Extract gradient value from Figma gradient fill
   * Sprint 7.2: Handles GRADIENT_LINEAR, GRADIENT_RADIAL, GRADIENT_ANGULAR, GRADIENT_DIAMOND
   */
  extractGradient(fill) {
    if (!fill || !fill.gradientStops) return null;

    const gradientTypeMap = {
      'GRADIENT_LINEAR': 'linear',
      'GRADIENT_RADIAL': 'radial',
      'GRADIENT_ANGULAR': 'conic',
      'GRADIENT_DIAMOND': 'radial'  // CSS doesn't have diamond, fallback to radial
    };

    const type = gradientTypeMap[fill.type] || 'linear';

    // Extract gradient stops
    const stops = fill.gradientStops.map(stop => ({
      color: this.extractColorValue(stop.color),
      position: Math.round(stop.position * 100) // Convert 0-1 to percentage
    }));

    // Calculate angle for linear gradients
    let angle = 0;
    if (fill.gradientHandlePositions && fill.gradientHandlePositions.length >= 2) {
      const [start, end] = fill.gradientHandlePositions;
      angle = Math.round(
        Math.atan2(end.y - start.y, end.x - start.x) * (180 / Math.PI) + 90
      );
      // Normalize to 0-360
      if (angle < 0) angle += 360;
    }

    // Build CSS gradient string
    const stopsCSS = stops.map(s => `${s.color} ${s.position}%`).join(', ');

    let cssValue;
    switch (type) {
      case 'linear':
        cssValue = `linear-gradient(${angle}deg, ${stopsCSS})`;
        break;
      case 'radial':
        cssValue = `radial-gradient(circle, ${stopsCSS})`;
        break;
      case 'conic':
        cssValue = `conic-gradient(from ${angle}deg, ${stopsCSS})`;
        break;
      default:
        cssValue = `linear-gradient(${stopsCSS})`;
    }

    return {
      type,
      angle,
      stops,
      css: cssValue,
      figmaType: fill.type
    };
  }

  /**
   * Generate gradient key for naming
   * Sprint 7.2
   */
  generateGradientKey(gradient) {
    const colors = gradient.stops.slice(0, 2).map(s =>
      s.color.replace('#', '').slice(0, 3)
    ).join('-');
    return `gradient-${gradient.type}-${colors}`;
  }

  /**
   * Extract Figma Variables
   * Sprint 7.3: Handles variable collections and modes
   */
  extractVariables(variablesData) {
    if (!variablesData) return;

    const { collections, variables } = variablesData;

    if (!collections || !variables) {
      console.warn('No variables data found');
      return;
    }

    // Process each collection
    collections.forEach(collection => {
      const collectionName = this.formatTokenName(collection.name);

      // Get modes for this collection
      const modes = collection.modes || [];
      const defaultModeId = modes[0]?.modeId;

      // Process each variable in collection
      collection.variableIds?.forEach(varId => {
        const variable = variables[varId];
        if (!variable) return;

        const varName = this.formatTokenName(variable.name);
        const fullKey = `${collectionName}-${varName}`;

        // Extract based on type
        const extractedVar = this.extractVariableValue(variable, defaultModeId);

        if (extractedVar) {
          this.tokens.variables[fullKey] = {
            name: variable.name,
            type: variable.resolvedType,
            collection: collection.name,
            value: extractedVar.value,
            css: extractedVar.css
          };

          // Extract mode-specific values
          if (modes.length > 1) {
            modes.forEach(mode => {
              const modeValue = this.extractVariableValue(variable, mode.modeId);

              if (modeValue) {
                if (!this.tokens.variableModes[mode.name]) {
                  this.tokens.variableModes[mode.name] = {};
                }
                this.tokens.variableModes[mode.name][fullKey] = {
                  ...modeValue,
                  modeName: mode.name
                };
              }
            });
          }
        }
      });
    });
  }

  /**
   * Extract value from a Figma variable for a specific mode
   * Sprint 7.3
   */
  extractVariableValue(variable, modeId) {
    const value = variable.valuesByMode?.[modeId];
    if (value === undefined) return null;

    switch (variable.resolvedType) {
      case 'COLOR':
        return {
          value: value,
          css: this.extractColorValue(value),
          type: 'color'
        };

      case 'FLOAT':
        return {
          value: value,
          css: `${value}${this.config.units}`,
          type: 'number'
        };

      case 'STRING':
        return {
          value: value,
          css: `"${value}"`,
          type: 'string'
        };

      case 'BOOLEAN':
        return {
          value: value,
          css: value ? '1' : '0',
          type: 'boolean'
        };

      default:
        return {
          value: value,
          css: String(value),
          type: 'unknown'
        };
    }
  }

  /**
   * Extract variables bound to components
   * Sprint 7.4: Links variables to their component usage
   */
  extractComponentVariables(component, variablesData) {
    if (!component || !variablesData) return;

    const componentName = this.formatTokenName(component.name);
    const boundVariables = [];

    // Check fills for variable bindings
    if (component.fills) {
      component.fills.forEach((fill, index) => {
        if (fill.boundVariables?.color) {
          const varId = fill.boundVariables.color.id;
          const variable = variablesData.variables?.[varId];

          if (variable) {
            boundVariables.push({
              property: `fill.${index}.color`,
              variableId: varId,
              variableName: variable.name,
              variableType: variable.resolvedType
            });
          }
        }
      });
    }

    // Check strokes for variable bindings
    if (component.strokes) {
      component.strokes.forEach((stroke, index) => {
        if (stroke.boundVariables?.color) {
          const varId = stroke.boundVariables.color.id;
          const variable = variablesData.variables?.[varId];

          if (variable) {
            boundVariables.push({
              property: `stroke.${index}.color`,
              variableId: varId,
              variableName: variable.name,
              variableType: variable.resolvedType
            });
          }
        }
      });
    }

    // Check effects for variable bindings
    if (component.effects) {
      component.effects.forEach((effect, index) => {
        if (effect.boundVariables) {
          Object.entries(effect.boundVariables).forEach(([prop, binding]) => {
            const varId = binding.id;
            const variable = variablesData.variables?.[varId];

            if (variable) {
              boundVariables.push({
                property: `effect.${index}.${prop}`,
                variableId: varId,
                variableName: variable.name,
                variableType: variable.resolvedType
              });
            }
          });
        }
      });
    }

    // Check dimension bindings (width, height, padding, etc.)
    const dimensionProps = ['width', 'height', 'paddingTop', 'paddingRight',
                            'paddingBottom', 'paddingLeft', 'itemSpacing',
                            'cornerRadius'];

    dimensionProps.forEach(prop => {
      if (component.boundVariables?.[prop]) {
        const varId = component.boundVariables[prop].id;
        const variable = variablesData.variables?.[varId];

        if (variable) {
          boundVariables.push({
            property: prop,
            variableId: varId,
            variableName: variable.name,
            variableType: variable.resolvedType
          });
        }
      }
    });

    // Store if component has bound variables
    if (boundVariables.length > 0) {
      this.tokens.componentVars[componentName] = {
        componentId: component.id,
        componentName: component.name,
        boundVariables,
        variableCount: boundVariables.length
      };
    }
  }

  /**
   * Extract text style
   */
  extractTextStyle(style) {
    return {
      fontFamily: style.fontName?.family || 'sans-serif',
      fontWeight: this.normalizeFontWeight(style.fontName?.style),
      fontSize: `${style.fontSize || 16}${this.config.units}`,
      lineHeight: style.lineHeight ? `${style.lineHeight.value}${style.lineHeight.unit === 'PERCENT' ? '%' : this.config.units}` : 'normal',
      letterSpacing: style.letterSpacing ? `${style.letterSpacing.value}${style.letterSpacing.unit === 'PERCENT' ? '%' : this.config.units}` : 'normal',
      textTransform: style.textCase || 'none',
      textDecoration: style.textDecoration || 'none'
    };
  }

  /**
   * Extract effect (shadow/blur)
   */
  extractEffect(effect) {
    if (effect.type === 'DROP_SHADOW' || effect.type === 'INNER_SHADOW') {
      return {
        type: 'shadow',
        value: `${effect.offset?.x || 0}${this.config.units} ${effect.offset?.y || 0}${this.config.units} ${effect.radius || 0}${this.config.units} ${this.extractColorValue(effect.color)}`
      };
    }

    if (effect.type === 'LAYER_BLUR' || effect.type === 'BACKGROUND_BLUR') {
      return {
        type: 'blur',
        value: `${effect.radius || 0}${this.config.units}`
      };
    }

    return { type: 'unknown', value: null };
  }

  /**
   * Extract grid style with complete metadata (Sprint 7.5)
   * @param {Object} grid - Figma grid configuration
   * @param {string} styleName - Optional style name for naming
   * @returns {Object} Complete grid token with CSS-ready values
   */
  extractGridStyle(grid, styleName = null) {
    const units = this.config.units;

    if (grid.pattern === 'COLUMNS' || grid.pattern === 'ROWS') {
      const count = grid.count || 12;
      const gutterSize = grid.gutterSize || 0;
      const offset = grid.offset || 0;
      const alignment = grid.alignment || 'STRETCH';

      // Calculate total gutter width
      const totalGutterWidth = gutterSize * (count - 1);

      // Generate CSS grid template
      const cssTemplate = grid.pattern === 'COLUMNS'
        ? `repeat(${count}, 1fr)`
        : `repeat(${count}, 1fr)`;

      return {
        pattern: grid.pattern,
        count: count,
        gutterSize: gutterSize,
        gutterSizeValue: `${gutterSize}${units}`,
        offset: offset,
        offsetValue: `${offset}${units}`,
        alignment: alignment,
        totalGutterWidth: `${totalGutterWidth}${units}`,
        cssTemplate: cssTemplate,
        cssGap: `${gutterSize}${units}`,
        // Legacy format for backwards compatibility
        spacing: `${gutterSize}${units}`,
        margin: `${offset}${units}`
      };
    }

    if (grid.pattern === 'GRID') {
      const sectionSize = grid.sectionSize || 8;

      return {
        pattern: 'GRID',
        sectionSize: sectionSize,
        sectionSizeValue: `${sectionSize}${units}`,
        cssTemplate: `repeat(auto-fill, ${sectionSize}${units})`,
        cssGap: `0${units}`,
        // Legacy format
        size: `${sectionSize}${units}`
      };
    }

    return null;
  }

  /**
   * Extract all grids from a node (Sprint 7.5)
   * @param {Object} node - Figma node with layoutGrids
   * @returns {Object} Named grid configurations
   */
  extractGridsFromNode(node) {
    if (!node.layoutGrids || node.layoutGrids.length === 0) {
      return null;
    }

    const grids = {};
    const nodeName = this.formatTokenName(node.name || 'grid');

    node.layoutGrids.forEach((grid, index) => {
      const gridData = this.extractGridStyle(grid, node.name);
      if (gridData) {
        const suffix = node.layoutGrids.length > 1 ? `-${index + 1}` : '';
        const patternSuffix = grid.pattern.toLowerCase();
        const gridName = `${nodeName}-${patternSuffix}${suffix}`;
        grids[gridName] = gridData;
      }
    });

    return Object.keys(grids).length > 0 ? grids : null;
  }

  /**
   * Extract text node tokens
   */
  extractTextNode(node) {
    if (node.fontSize) {
      const sizeKey = `font-size-${Math.round(node.fontSize)}`;
      this.tokens.typography[sizeKey] = `${node.fontSize}${this.config.units}`;
    }

    if (node.fontName) {
      const familyKey = this.formatTokenName(node.fontName.family);
      if (!this.tokens.typography[`font-${familyKey}`]) {
        this.tokens.typography[`font-${familyKey}`] = node.fontName.family;
      }
    }
  }

  /**
   * Extract layout spacing
   */
  extractLayoutSpacing(node) {
    if (node.paddingTop !== undefined) {
      const paddingKey = `padding-${Math.round(node.paddingTop)}`;
      this.tokens.spacing[paddingKey] = `${node.paddingTop}${this.config.units}`;
    }

    if (node.itemSpacing !== undefined) {
      const spacingKey = `gap-${Math.round(node.itemSpacing)}`;
      this.tokens.spacing[spacingKey] = `${node.itemSpacing}${this.config.units}`;
    }
  }

  /**
   * Extract border tokens
   */
  extractBorder(node) {
    const borderKey = `border-${Math.round(node.strokeWeight)}`;
    const borderColor = node.strokes[0] && node.strokes[0].type === 'SOLID'
      ? this.extractColorValue(node.strokes[0].color)
      : 'transparent';

    this.tokens.borders[borderKey] = {
      width: `${node.strokeWeight}${this.config.units}`,
      style: node.strokeDashes ? 'dashed' : 'solid',
      color: borderColor
    };
  }

  /**
   * Extract component-specific tokens
   */
  extractComponentTokens(component) {
    // Extract breakpoints from responsive components
    if (component.name.includes('mobile') || component.name.includes('tablet') || component.name.includes('desktop')) {
      const device = component.name.match(/(mobile|tablet|desktop)/i)?.[1]?.toLowerCase();
      if (device && component.absoluteBoundingBox) {
        this.tokens.breakpoints[device] = `${component.absoluteBoundingBox.width}${this.config.units}`;
      }
    }

    // Extract animation tokens from interactive components
    if (component.interactions && component.interactions.length > 0) {
      component.interactions.forEach(interaction => {
        if (interaction.transition) {
          const animKey = this.formatTokenName(interaction.trigger || 'default');
          this.tokens.animations[animKey] = {
            duration: `${interaction.transition.duration || 0.3}s`,
            easing: interaction.transition.easing || 'ease'
          };
        }
      });
    }
  }

  /**
   * Traverse node tree
   */
  traverseNode(node, callback) {
    callback(node);

    if (node.children) {
      node.children.forEach(child => {
        this.traverseNode(child, callback);
      });
    }
  }

  /**
   * Format token name
   */
  formatTokenName(name) {
    return name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '');
  }

  /**
   * Generate color key
   */
  generateColorKey(color) {
    const hex = this.extractColorValue(color);
    const name = this.getColorName(hex);
    return name || `color-${hex.replace('#', '')}`;
  }

  /**
   * Get semantic color name
   */
  getColorName(hex) {
    const colorMap = {
      '#000000': 'black',
      '#ffffff': 'white',
      '#ff0000': 'red',
      '#00ff00': 'green',
      '#0000ff': 'blue',
      '#ffff00': 'yellow',
      '#ff00ff': 'magenta',
      '#00ffff': 'cyan'
    };

    return colorMap[hex.toLowerCase()];
  }

  /**
   * Convert to hex
   */
  toHex(value) {
    return value.toString(16).padStart(2, '0');
  }

  /**
   * Convert RGB to HSL
   */
  rgbToHsl(r, g, b) {
    r /= 255;
    g /= 255;
    b /= 255;

    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    let h, s, l = (max + min) / 2;

    if (max === min) {
      h = s = 0;
    } else {
      const d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);

      switch (max) {
        case r:
          h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
          break;
        case g:
          h = ((b - r) / d + 2) / 6;
          break;
        case b:
          h = ((r - g) / d + 4) / 6;
          break;
      }
    }

    return {
      h: Math.round(h * 360),
      s: Math.round(s * 100),
      l: Math.round(l * 100)
    };
  }

  /**
   * Normalize font weight
   */
  normalizeFontWeight(style) {
    const weightMap = {
      'thin': '100',
      'extralight': '200',
      'light': '300',
      'regular': '400',
      'medium': '500',
      'semibold': '600',
      'bold': '700',
      'extrabold': '800',
      'black': '900'
    };

    const normalized = style?.toLowerCase().replace(/[^a-z]/g, '') || 'regular';
    return weightMap[normalized] || '400';
  }

  /**
   * Format tokens for output
   */
  formatTokens() {
    return {
      colors: this.deduplicateTokens(this.tokens.colors),
      typography: this.deduplicateTokens(this.tokens.typography),
      spacing: this.deduplicateTokens(this.tokens.spacing),
      shadows: this.deduplicateTokens(this.tokens.shadows),
      borders: this.deduplicateTokens(this.tokens.borders),
      radii: this.deduplicateTokens(this.tokens.radii),
      breakpoints: this.tokens.breakpoints,
      animations: this.tokens.animations,
      gradients: this.deduplicateTokens(this.tokens.gradients),  // Sprint 7.2
      variables: this.tokens.variables,        // Sprint 7.3: Figma Variables
      variableModes: this.tokens.variableModes, // Sprint 7.3: Mode-specific values
      componentVars: this.tokens.componentVars, // Sprint 7.4: Component-variable bindings
      grids: this.tokens.grids                  // Sprint 7.5: Full grid definitions
    };
  }

  /**
   * Deduplicate tokens
   */
  deduplicateTokens(tokens) {
    const unique = {};
    const valueMap = new Map();

    Object.entries(tokens).forEach(([key, value]) => {
      const valueStr = JSON.stringify(value);
      if (!valueMap.has(valueStr)) {
        valueMap.set(valueStr, key);
        unique[key] = value;
      }
    });

    return unique;
  }

  /**
   * Reset tokens
   */
  reset() {
    this.tokens = {
      colors: {},
      typography: {},
      spacing: {},
      shadows: {},
      borders: {},
      radii: {},
      breakpoints: {},
      animations: {},
      gradients: {},      // Sprint 7.2: Gradient tokens
      variables: {},      // Sprint 7.3: Figma Variables
      variableModes: {},  // Sprint 7.3: Mode-specific values (light/dark)
      componentVars: {},  // Sprint 7.4: Component-variable associations
      grids: {}           // Sprint 7.5: Full grid definitions
    };
  }

  /**
   * Export tokens to various formats
   */
  export(format = 'json') {
    const tokens = this.formatTokens();

    switch (format) {
      case 'css':
        return this.exportToCSS(tokens);
      case 'scss':
        return this.exportToSCSS(tokens);
      case 'js':
        return this.exportToJS(tokens);
      case 'json':
      default:
        return JSON.stringify(tokens, null, 2);
    }
  }

  /**
   * Export to CSS variables
   */
  exportToCSS(tokens) {
    let css = ':root {\n';

    // Colors
    Object.entries(tokens.colors).forEach(([key, value]) => {
      css += `  --color-${key}: ${value};\n`;
    });

    // Typography
    Object.entries(tokens.typography).forEach(([key, value]) => {
      if (typeof value === 'string') {
        css += `  --typography-${key}: ${value};\n`;
      }
    });

    // Spacing
    Object.entries(tokens.spacing).forEach(([key, value]) => {
      css += `  --spacing-${key}: ${value};\n`;
    });

    // Shadows
    Object.entries(tokens.shadows).forEach(([key, value]) => {
      css += `  --shadow-${key}: ${value};\n`;
    });

    // Border radius
    Object.entries(tokens.radii).forEach(([key, value]) => {
      css += `  --${key}: ${value};\n`;
    });

    // Sprint 7.2: Gradients
    Object.entries(tokens.gradients).forEach(([key, gradient]) => {
      css += `  --gradient-${key}: ${gradient.css};\n`;
    });

    // Sprint 7.5: Grids
    Object.entries(tokens.grids).forEach(([key, grid]) => {
      css += `  --grid-${key}-columns: ${grid.count || 'auto'};\n`;
      css += `  --grid-${key}-gap: ${grid.cssGap || grid.spacing || '0px'};\n`;
      css += `  --grid-${key}-template: ${grid.cssTemplate || 'none'};\n`;
      if (grid.offsetValue) {
        css += `  --grid-${key}-margin: ${grid.offsetValue};\n`;
      }
    });

    css += '}';
    return css;
  }

  /**
   * Export to SCSS variables
   */
  exportToSCSS(tokens) {
    let scss = '';

    // Colors
    Object.entries(tokens.colors).forEach(([key, value]) => {
      scss += `$color-${key}: ${value};\n`;
    });

    // Typography
    Object.entries(tokens.typography).forEach(([key, value]) => {
      if (typeof value === 'string') {
        scss += `$typography-${key}: ${value};\n`;
      }
    });

    // Spacing
    Object.entries(tokens.spacing).forEach(([key, value]) => {
      scss += `$spacing-${key}: ${value};\n`;
    });

    // Sprint 7.2: Gradients
    Object.entries(tokens.gradients).forEach(([key, gradient]) => {
      scss += `$gradient-${key}: ${gradient.css};\n`;
    });

    // Sprint 7.5: Grids
    Object.entries(tokens.grids).forEach(([key, grid]) => {
      scss += `$grid-${key}-columns: ${grid.count || 'auto'};\n`;
      scss += `$grid-${key}-gap: ${grid.cssGap || grid.spacing || '0px'};\n`;
      scss += `$grid-${key}-template: ${grid.cssTemplate || 'none'};\n`;
      if (grid.offsetValue) {
        scss += `$grid-${key}-margin: ${grid.offsetValue};\n`;
      }
    });

    return scss;
  }

  /**
   * Export to JavaScript
   */
  exportToJS(tokens) {
    return `export const tokens = ${JSON.stringify(tokens, null, 2)};`;
  }
}

module.exports = { TokenExtractor };