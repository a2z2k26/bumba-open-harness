/**
 * Export Formatters - Format-specific token transformation classes
 * Each formatter handles conversion to specific output formats
 */

class BaseFormatter {
  constructor() {
    this.name = 'base';
  }

  async format(tokens, options = {}) {
    throw new Error('Format method must be implemented by subclass');
  }

  sanitizeName(name, options = {}) {
    return name.replace(/[^a-zA-Z0-9-_]/g, '-');
  }

  flattenTokens(tokens, prefix = '', separator = '.') {
    const flattened = {};

    const flatten = (obj, currentPrefix) => {
      Object.entries(obj).forEach(([key, value]) => {
        const newKey = currentPrefix ? `${currentPrefix}${separator}${key}` : key;

        if (typeof value === 'object' && value !== null && !Array.isArray(value) && !this.isTokenValue(value)) {
          flatten(value, newKey);
        } else {
          flattened[newKey] = value;
        }
      });
    };

    flatten(tokens, prefix);
    return flattened;
  }

  isTokenValue(value) {
    // Check if value is a token (has properties like rgb, hex, px, etc.)
    return value && typeof value === 'object' && (
      value.hasOwnProperty('rgb') ||
      value.hasOwnProperty('hex') ||
      value.hasOwnProperty('px') ||
      value.hasOwnProperty('rem') ||
      value.hasOwnProperty('value')
    );
  }

  formatValue(value) {
    if (typeof value === 'string') return value;
    if (typeof value === 'number') return value.toString();
    if (value && typeof value === 'object') {
      if (value.hex) return value.hex;
      if (value.rgb) return `rgb(${value.rgb.r}, ${value.rgb.g}, ${value.rgb.b})`;
      if (value.px) return `${value.px}px`;
      if (value.rem) return `${value.rem}rem`;
      if (value.value) return this.formatValue(value.value);
    }
    return String(value);
  }
}

class CSSFormatter extends BaseFormatter {
  constructor() {
    super();
    this.name = 'css';
  }

  async format(tokens, options = {}) {
    const {
      prefix = '--',
      selector = ':root',
      mediaQueries = false,
      customProperties = true
    } = options;

    const flattened = this.flattenTokens(tokens, '', '-');
    let css = '';

    // Generate main CSS custom properties
    if (customProperties) {
      css += `${selector} {\n`;

      Object.entries(flattened).forEach(([name, value]) => {
        const cssName = this.sanitizeCSSName(name);
        const cssValue = this.formatCSSValue(value);
        css += `  ${prefix}${cssName}: ${cssValue};\n`;
      });

      css += '}\n\n';
    }

    // Generate utility classes
    css += this.generateUtilityClasses(flattened, options);

    // Generate media queries if enabled
    if (mediaQueries && tokens.breakpoints) {
      css += this.generateMediaQueries(tokens.breakpoints, flattened, options);
    }

    return {
      content: css,
      metadata: {
        format: 'css',
        variableCount: Object.keys(flattened).length,
        hasMediaQueries: mediaQueries && tokens.breakpoints
      }
    };
  }

  sanitizeCSSName(name) {
    return name.toLowerCase().replace(/[^a-z0-9-]/g, '-').replace(/-+/g, '-');
  }

  formatCSSValue(value) {
    if (typeof value === 'string') return value;
    if (typeof value === 'number') return value.toString();
    if (value && typeof value === 'object') {
      if (value.hex) return value.hex;
      if (value.rgb) {
        const { r, g, b, a } = value.rgb;
        return a !== undefined ? `rgba(${r}, ${g}, ${b}, ${a})` : `rgb(${r}, ${g}, ${b})`;
      }
      if (value.hsl) {
        const { h, s, l, a } = value.hsl;
        return a !== undefined ? `hsla(${h}, ${s}%, ${l}%, ${a})` : `hsl(${h}, ${s}%, ${l}%)`;
      }
      if (value.px) return `${value.px}px`;
      if (value.rem) return `${value.rem}rem`;
      if (value.em) return `${value.em}em`;
      if (value.value) return this.formatCSSValue(value.value);
    }
    return String(value);
  }

  generateUtilityClasses(flattened, options) {
    let utilities = '/* Utility Classes */\n';

    // Color utilities
    Object.entries(flattened).forEach(([name, value]) => {
      if (this.isColorValue(value)) {
        const className = this.sanitizeCSSName(name);
        utilities += `.text-${className} { color: var(--${className}); }\n`;
        utilities += `.bg-${className} { background-color: var(--${className}); }\n`;
        utilities += `.border-${className} { border-color: var(--${className}); }\n`;
      }
    });

    utilities += '\n';
    return utilities;
  }

  generateMediaQueries(breakpoints, flattened, options) {
    let mediaQueries = '/* Media Queries */\n';

    Object.entries(breakpoints).forEach(([name, size]) => {
      const sizeValue = this.formatCSSValue(size);
      mediaQueries += `@media (min-width: ${sizeValue}) {\n`;
      mediaQueries += `  .${name}\\: {\n`;
      mediaQueries += `    /* ${name} styles */\n`;
      mediaQueries += `  }\n`;
      mediaQueries += '}\n\n';
    });

    return mediaQueries;
  }

  isColorValue(value) {
    if (typeof value === 'string') {
      return /^#[0-9a-f]{3,8}$/i.test(value) ||
             /^rgb/.test(value) ||
             /^hsl/.test(value);
    }
    if (value && typeof value === 'object') {
      return value.hex || value.rgb || value.hsl;
    }
    return false;
  }
}

class SCSSFormatter extends BaseFormatter {
  constructor() {
    super();
    this.name = 'scss';
  }

  async format(tokens, options = {}) {
    const {
      prefix = '$',
      maps = true,
      functions = true,
      mixins = true
    } = options;

    let scss = '';

    // Generate SCSS variables
    scss += '// SCSS Variables\n';
    const flattened = this.flattenTokens(tokens, '', '-');

    Object.entries(flattened).forEach(([name, value]) => {
      const scssName = this.sanitizeSCSSName(name);
      const scssValue = this.formatSCSSValue(value);
      scss += `${prefix}${scssName}: ${scssValue};\n`;
    });

    scss += '\n';

    // Generate SCSS maps if enabled
    if (maps) {
      scss += this.generateSCSSMaps(tokens, options);
    }

    // Generate SCSS functions if enabled
    if (functions) {
      scss += this.generateSCSSFunctions(tokens, options);
    }

    // Generate SCSS mixins if enabled
    if (mixins) {
      scss += this.generateSCSSMixins(tokens, options);
    }

    return {
      content: scss,
      metadata: {
        format: 'scss',
        variableCount: Object.keys(flattened).length,
        hasMaps: maps,
        hasFunctions: functions,
        hasMixins: mixins
      }
    };
  }

  sanitizeSCSSName(name) {
    return name.toLowerCase().replace(/[^a-z0-9-_]/g, '-').replace(/-+/g, '-');
  }

  formatSCSSValue(value) {
    return this.formatValue(value);
  }

  generateSCSSMaps(tokens, options) {
    let maps = '// SCSS Maps\n';

    // Generate color map
    if (tokens.colors) {
      maps += '$colors: (\n';
      Object.entries(tokens.colors).forEach(([name, value]) => {
        const scssName = this.sanitizeSCSSName(name);
        const scssValue = this.formatSCSSValue(value);
        maps += `  '${scssName}': ${scssValue},\n`;
      });
      maps += ');\n\n';
    }

    // Generate spacing map
    if (tokens.spacing) {
      maps += '$spacing: (\n';
      Object.entries(tokens.spacing).forEach(([name, value]) => {
        const scssName = this.sanitizeSCSSName(name);
        const scssValue = this.formatSCSSValue(value);
        maps += `  '${scssName}': ${scssValue},\n`;
      });
      maps += ');\n\n';
    }

    return maps;
  }

  generateSCSSFunctions(tokens, options) {
    let functions = '// SCSS Functions\n';

    // Color function
    functions += `@function color($name) {
  @if map-has-key($colors, $name) {
    @return map-get($colors, $name);
  }
  @warn "Color '\#{$name}' not found in $colors map.";
  @return null;
}\n\n`;

    // Spacing function
    functions += `@function spacing($name) {
  @if map-has-key($spacing, $name) {
    @return map-get($spacing, $name);
  }
  @warn "Spacing '\#{$name}' not found in $spacing map.";
  @return null;
}\n\n`;

    return functions;
  }

  generateSCSSMixins(tokens, options) {
    let mixins = '// SCSS Mixins\n';

    // Typography mixin
    if (tokens.typography) {
      mixins += `@mixin typography($name) {
  @if map-has-key($typography, $name) {
    $type: map-get($typography, $name);
    font-family: map-get($type, 'font-family');
    font-size: map-get($type, 'font-size');
    font-weight: map-get($type, 'font-weight');
    line-height: map-get($type, 'line-height');
  } @else {
    @warn "Typography '\#{$name}' not found.";
  }
}\n\n`;
    }

    // Shadow mixin
    if (tokens.shadows) {
      mixins += `@mixin shadow($name) {
  @if map-has-key($shadows, $name) {
    box-shadow: map-get($shadows, $name);
  } @else {
    @warn "Shadow '\#{$name}' not found.";
  }
}\n\n`;
    }

    return mixins;
  }
}

class TypeScriptFormatter extends BaseFormatter {
  constructor() {
    super();
    this.name = 'typescript';
  }

  async format(tokens, options = {}) {
    const {
      interface: generateInterface = true,
      enums = true,
      namespace = 'DesignTokens',
      exportType = 'const'
    } = options;

    let typescript = '';

    // Generate TypeScript interfaces
    if (generateInterface) {
      typescript += this.generateInterfaces(tokens, options);
    }

    // Generate TypeScript enums
    if (enums) {
      typescript += this.generateEnums(tokens, options);
    }

    // Generate TypeScript constants
    typescript += this.generateConstants(tokens, options);

    // Wrap in namespace if specified
    if (namespace) {
      typescript = `export namespace ${namespace} {\n${this.indentCode(typescript)}\n}\n`;
    }

    return {
      content: typescript,
      metadata: {
        format: 'typescript',
        hasInterface: generateInterface,
        hasEnums: enums,
        namespace
      },
      additionalFiles: {
        'design-tokens.d.ts': this.generateTypeDefinitions(tokens, options)
      }
    };
  }

  generateInterfaces(tokens, options) {
    let interfaces = '// TypeScript Interfaces\n';

    // Generate main tokens interface
    interfaces += 'export interface DesignTokens {\n';
    interfaces += this.generateInterfaceProperties(tokens, 1);
    interfaces += '}\n\n';

    // Generate specific interfaces for each category
    Object.entries(tokens).forEach(([category, categoryTokens]) => {
      if (typeof categoryTokens === 'object' && categoryTokens !== null) {
        const interfaceName = this.capitalizeFirst(category);
        interfaces += `export interface ${interfaceName}Tokens {\n`;
        interfaces += this.generateInterfaceProperties(categoryTokens, 1);
        interfaces += '}\n\n';
      }
    });

    return interfaces;
  }

  generateInterfaceProperties(obj, indentLevel = 0) {
    let properties = '';
    const indent = '  '.repeat(indentLevel);

    Object.entries(obj).forEach(([key, value]) => {
      const safeKey = this.sanitizeTypeScriptName(key);

      if (typeof value === 'object' && value !== null && !this.isTokenValue(value)) {
        properties += `${indent}${safeKey}: {\n`;
        properties += this.generateInterfaceProperties(value, indentLevel + 1);
        properties += `${indent}};\n`;
      } else {
        const type = this.inferTypeScriptType(value);
        properties += `${indent}${safeKey}: ${type};\n`;
      }
    });

    return properties;
  }

  generateEnums(tokens, options) {
    let enums = '// TypeScript Enums\n';

    // Generate color enum
    if (tokens.colors) {
      enums += 'export enum Colors {\n';
      Object.keys(tokens.colors).forEach(colorName => {
        const enumKey = this.sanitizeEnumKey(colorName);
        enums += `  ${enumKey} = '${colorName}',\n`;
      });
      enums += '}\n\n';
    }

    // Generate spacing enum
    if (tokens.spacing) {
      enums += 'export enum Spacing {\n';
      Object.keys(tokens.spacing).forEach(spacingName => {
        const enumKey = this.sanitizeEnumKey(spacingName);
        enums += `  ${enumKey} = '${spacingName}',\n`;
      });
      enums += '}\n\n';
    }

    return enums;
  }

  generateConstants(tokens, options) {
    const { exportType } = options;
    let constants = '// TypeScript Constants\n';

    const flattened = this.flattenTokens(tokens, '', '.');

    constants += `export ${exportType} tokens = {\n`;

    Object.entries(flattened).forEach(([name, value]) => {
      const safeKey = this.sanitizeTypeScriptName(name);
      const formattedValue = this.formatTypeScriptValue(value);
      constants += `  ${safeKey}: ${formattedValue},\n`;
    });

    constants += '} as const;\n\n';

    // Generate typed accessors
    constants += this.generateTypedAccessors(tokens, options);

    return constants;
  }

  generateTypedAccessors(tokens, options) {
    let accessors = '// Typed Accessors\n';

    accessors += `export function getToken<T extends keyof typeof tokens>(key: T): typeof tokens[T] {
  return tokens[key];
}\n\n`;

    return accessors;
  }

  generateTypeDefinitions(tokens, options) {
    let typeDefs = '// Type Definitions\n';

    typeDefs += 'declare module "design-tokens" {\n';
    typeDefs += '  export * from "./design-tokens";\n';
    typeDefs += '}\n';

    return typeDefs;
  }

  sanitizeTypeScriptName(name) {
    // Convert to camelCase and ensure valid TypeScript identifier
    const camelCase = name.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    return /^[a-zA-Z_$][a-zA-Z0-9_$]*$/.test(camelCase) ? camelCase : `"${name}"`;
  }

  sanitizeEnumKey(name) {
    return name.toUpperCase().replace(/[^A-Z0-9_]/g, '_');
  }

  inferTypeScriptType(value) {
    if (typeof value === 'string') return 'string';
    if (typeof value === 'number') return 'number';
    if (typeof value === 'boolean') return 'boolean';
    if (Array.isArray(value)) return 'any[]';
    if (value && typeof value === 'object') {
      if (value.hex || value.rgb || value.hsl) return 'string';
      if (value.px || value.rem || value.em) return 'string';
      return 'any';
    }
    return 'any';
  }

  formatTypeScriptValue(value) {
    if (typeof value === 'string') return `'${value.replace(/'/g, "\\'")}'`;
    if (typeof value === 'number') return value.toString();
    if (typeof value === 'boolean') return value.toString();
    if (value && typeof value === 'object') {
      if (value.hex) return `'${value.hex}'`;
      if (value.rgb) return `'rgb(${value.rgb.r}, ${value.rgb.g}, ${value.rgb.b})'`;
      if (value.px) return `'${value.px}px'`;
      if (value.rem) return `'${value.rem}rem'`;
      if (value.value) return this.formatTypeScriptValue(value.value);
      return JSON.stringify(value);
    }
    return JSON.stringify(value);
  }

  capitalizeFirst(str) {
    return str.charAt(0).toUpperCase() + str.slice(1);
  }

  indentCode(code) {
    return code.split('\n').map(line => line ? `  ${line}` : line).join('\n');
  }
}

class JSONFormatter extends BaseFormatter {
  constructor() {
    super();
    this.name = 'json';
  }

  async format(tokens, options = {}) {
    const {
      indent = 2,
      sortKeys = false,
      metadata = false
    } = options;

    let processedTokens = { ...tokens };

    // Sort keys if requested
    if (sortKeys) {
      processedTokens = this.sortObjectKeys(processedTokens);
    }

    // Add metadata if requested
    if (metadata) {
      processedTokens._metadata = {
        generated: new Date().toISOString(),
        format: 'json',
        version: '1.0.0'
      };
    }

    const content = JSON.stringify(processedTokens, null, indent);

    return {
      content,
      metadata: {
        format: 'json',
        size: content.length,
        hasMetadata: metadata
      }
    };
  }

  sortObjectKeys(obj) {
    if (Array.isArray(obj)) {
      return obj.map(item => this.sortObjectKeys(item));
    }

    if (obj && typeof obj === 'object') {
      const sorted = {};
      Object.keys(obj).sort().forEach(key => {
        sorted[key] = this.sortObjectKeys(obj[key]);
      });
      return sorted;
    }

    return obj;
  }
}

// Additional formatters would be implemented similarly...
class SwiftFormatter extends BaseFormatter {
  constructor() {
    super();
    this.name = 'swift';
  }

  async format(tokens, options = {}) {
    const { struct: useStruct = true, namespace = 'DesignTokens' } = options;

    let swift = '// Swift Design Tokens\nimport UIKit\n\n';

    if (useStruct) {
      swift += `struct ${namespace} {\n`;
      swift += this.generateSwiftStructContent(tokens, options);
      swift += '}\n';
    }

    return { content: swift, metadata: { format: 'swift' } };
  }

  generateSwiftStructContent(tokens, options) {
    let content = '';

    if (tokens.colors) {
      content += '  struct Colors {\n';
      Object.entries(tokens.colors).forEach(([name, value]) => {
        const swiftName = this.sanitizeSwiftName(name);
        const swiftValue = this.formatSwiftColor(value);
        content += `    static let ${swiftName} = ${swiftValue}\n`;
      });
      content += '  }\n\n';
    }

    return content;
  }

  sanitizeSwiftName(name) {
    return name.replace(/[^a-zA-Z0-9]/g, '').replace(/^[0-9]/, '_$&');
  }

  formatSwiftColor(value) {
    if (value.hex) {
      return `UIColor(hex: "${value.hex}")`;
    }
    if (value.rgb) {
      const { r, g, b, a = 1 } = value.rgb;
      return `UIColor(red: ${r/255}, green: ${g/255}, blue: ${b/255}, alpha: ${a})`;
    }
    return `UIColor.black`;
  }
}

// YAML Formatter implementation
class YAMLFormatter extends BaseFormatter {
  constructor() {
    super();
    this.name = 'yaml';
  }

  async format(tokens, options = {}) {
    const { comments = true, indent = 2 } = options;

    let yaml = '';
    if (comments) {
      yaml += '# Design Tokens YAML\n';
      yaml += `# Generated: ${new Date().toISOString()}\n`;
      yaml += '# Version: 1.0.0\n\n';
    }

    yaml += 'tokens:\n';
    yaml += this.objectToYAML(tokens, 1, indent);

    return {
      content: yaml,
      metadata: {
        format: 'yaml',
        size: yaml.length
      }
    };
  }

  objectToYAML(obj, level = 0, indentSize = 2) {
    let yaml = '';
    const indent = ' '.repeat(level * indentSize);

    Object.entries(obj).forEach(([key, value]) => {
      yaml += `${indent}${key}:`;

      if (value === null) {
        yaml += ' null\n';
      } else if (value === undefined) {
        yaml += ' null\n';
      } else if (typeof value === 'boolean') {
        yaml += ` ${value}\n`;
      } else if (typeof value === 'number') {
        yaml += ` ${value}\n`;
      } else if (typeof value === 'string') {
        // Quote strings that need it
        if (value.includes(':') || value.includes('#') || value.includes('"') || value.includes("'")) {
          yaml += ` "${value.replace(/"/g, '\\"')}"\n`;
        } else {
          yaml += ` ${value}\n`;
        }
      } else if (Array.isArray(value)) {
        yaml += '\n';
        value.forEach(item => {
          yaml += `${' '.repeat((level + 1) * indentSize)}- `;
          if (typeof item === 'object' && item !== null) {
            yaml += '\n' + this.objectToYAML(item, level + 2, indentSize);
          } else {
            yaml += `${item}\n`;
          }
        });
      } else if (typeof value === 'object' && value !== null) {
        yaml += '\n';
        yaml += this.objectToYAML(value, level + 1, indentSize);
      }
    });

    return yaml;
  }
}

// JavaScript Formatter implementation
class JavaScriptFormatter extends BaseFormatter {
  constructor() {
    super();
    this.name = 'javascript';
  }

  async format(tokens, options = {}) {
    const { esModules = true, namespace = 'designTokens' } = options;

    let js = '// JavaScript Design Tokens\n';
    js += `// Generated: ${new Date().toISOString()}\n\n`;

    if (esModules) {
      // ES Modules format
      js += this.generateESModules(tokens, namespace);
    } else {
      // CommonJS format
      js += this.generateCommonJS(tokens, namespace);
    }

    return {
      content: js,
      metadata: {
        format: 'javascript',
        moduleType: esModules ? 'esm' : 'commonjs'
      }
    };
  }

  generateESModules(tokens, namespace) {
    let js = '';

    // Export individual token categories
    Object.entries(tokens).forEach(([category, values]) => {
      if (typeof values === 'object' && values !== null) {
        js += `export const ${category} = ${this.objectToJS(values)};\n\n`;
      }
    });

    // Export all tokens
    js += `export const ${namespace} = {\n`;
    Object.keys(tokens).forEach((key, index, array) => {
      js += `  ${key}${index < array.length - 1 ? ',' : ''}\n`;
    });
    js += '};\n\n';

    // Default export
    js += `export default ${namespace};\n`;

    return js;
  }

  generateCommonJS(tokens, namespace) {
    let js = `const ${namespace} = ${this.objectToJS(tokens)};\n\n`;

    // Export individual categories
    Object.keys(tokens).forEach(category => {
      js += `module.exports.${category} = ${namespace}.${category};\n`;
    });

    // Export all
    js += `\nmodule.exports.${namespace} = ${namespace};\n`;
    js += `module.exports = ${namespace};\n`;

    return js;
  }

  objectToJS(obj, indent = 0) {
    const spaces = '  '.repeat(indent);
    const innerSpaces = '  '.repeat(indent + 1);

    if (obj === null) return 'null';
    if (obj === undefined) return 'undefined';
    if (typeof obj === 'boolean') return obj.toString();
    if (typeof obj === 'number') return obj.toString();
    if (typeof obj === 'string') return `'${obj.replace(/'/g, "\\'")}'`;

    if (Array.isArray(obj)) {
      if (obj.length === 0) return '[]';
      let js = '[\n';
      obj.forEach((item, index) => {
        js += innerSpaces + this.objectToJS(item, indent + 1);
        js += index < obj.length - 1 ? ',\n' : '\n';
      });
      js += spaces + ']';
      return js;
    }

    if (typeof obj === 'object') {
      const keys = Object.keys(obj);
      if (keys.length === 0) return '{}';

      let js = '{\n';
      keys.forEach((key, index) => {
        const safeName = /^[a-zA-Z_$][a-zA-Z0-9_$]*$/.test(key) ? key : `'${key}'`;
        js += `${innerSpaces}${safeName}: ${this.objectToJS(obj[key], indent + 1)}`;
        js += index < keys.length - 1 ? ',\n' : '\n';
      });
      js += spaces + '}';
      return js;
    }

    return '{}';
  }
}

// Kotlin Formatter implementation
class KotlinFormatter extends BaseFormatter {
  constructor() {
    super();
    this.name = 'kotlin';
  }

  async format(tokens, options = {}) {
    const { packageName = 'com.example.designtokens', objectName = 'DesignTokens' } = options;

    let kotlin = '// Kotlin Design Tokens\n';
    kotlin += `// Generated: ${new Date().toISOString()}\n\n`;
    kotlin += `package ${packageName}\n\n`;
    kotlin += 'import androidx.compose.ui.graphics.Color\n';
    kotlin += 'import androidx.compose.ui.unit.dp\n';
    kotlin += 'import androidx.compose.ui.unit.sp\n\n';

    kotlin += `object ${objectName} {\n`;

    // Generate colors
    if (tokens.colors) {
      kotlin += '  object Colors {\n';
      Object.entries(tokens.colors).forEach(([name, value]) => {
        const kotlinName = this.toKotlinName(name);
        const kotlinColor = this.formatKotlinColor(value);
        kotlin += `    val ${kotlinName} = ${kotlinColor}\n`;
      });
      kotlin += '  }\n\n';
    }

    // Generate spacing
    if (tokens.spacing) {
      kotlin += '  object Spacing {\n';
      Object.entries(tokens.spacing).forEach(([name, value]) => {
        const kotlinName = this.toKotlinName(name);
        const dpValue = this.formatKotlinDp(value);
        kotlin += `    val ${kotlinName} = ${dpValue}\n`;
      });
      kotlin += '  }\n\n';
    }

    // Generate typography sizes
    if (tokens.typography) {
      kotlin += '  object Typography {\n';
      Object.entries(tokens.typography).forEach(([name, value]) => {
        if (value.fontSize) {
          const kotlinName = this.toKotlinName(name);
          const spValue = this.formatKotlinSp(value.fontSize);
          kotlin += `    val ${kotlinName}Size = ${spValue}\n`;
        }
      });
      kotlin += '  }\n';
    }

    kotlin += '}\n';

    return {
      content: kotlin,
      metadata: {
        format: 'kotlin',
        platform: 'android-compose'
      }
    };
  }

  toKotlinName(name) {
    // Convert to camelCase and ensure it starts with lowercase
    const camelCase = name.replace(/-([a-z])/g, (g) => g[1].toUpperCase());
    return camelCase.charAt(0).toLowerCase() + camelCase.slice(1);
  }

  formatKotlinColor(value) {
    if (typeof value === 'string') {
      if (value.startsWith('#')) {
        const hex = value.replace('#', '');
        if (hex.length === 6) {
          return `Color(0xFF${hex.toUpperCase()})`;
        } else if (hex.length === 8) {
          return `Color(0x${hex.toUpperCase()})`;
        }
      }
    } else if (value.hex) {
      return this.formatKotlinColor(value.hex);
    } else if (value.rgb) {
      const { r, g, b, a = 1 } = value.rgb;
      return `Color(${r}, ${g}, ${b}, ${(a * 255).toFixed(0)})`;
    }
    return 'Color.Black';
  }

  formatKotlinDp(value) {
    if (typeof value === 'number') {
      return `${value}.dp`;
    } else if (typeof value === 'string') {
      const numValue = parseFloat(value);
      if (!isNaN(numValue)) {
        return `${numValue}.dp`;
      }
    }
    return '0.dp';
  }

  formatKotlinSp(value) {
    if (typeof value === 'number') {
      return `${value}.sp`;
    } else if (typeof value === 'string') {
      const numValue = parseFloat(value);
      if (!isNaN(numValue)) {
        return `${numValue}.sp`;
      }
    }
    return '14.sp';
  }
}

// Dart/Flutter Formatter implementation
class LESSFormatter extends BaseFormatter {
  constructor() {
    super();
    this.name = 'less';
  }

  async format(tokens, options = {}) {
    const output = [];

    // LESS variables
    if (tokens.colors) {
      output.push('// Colors');
      Object.entries(tokens.colors).forEach(([name, value]) => {
        const varName = `@color-${this.sanitizeName(name)}`;
        output.push(`${varName}: ${value};`);
      });
      output.push('');
    }

    if (tokens.spacing) {
      output.push('// Spacing');
      Object.entries(tokens.spacing).forEach(([name, value]) => {
        const varName = `@spacing-${this.sanitizeName(name)}`;
        output.push(`${varName}: ${value};`);
      });
      output.push('');
    }

    if (tokens.typography) {
      output.push('// Typography');
      Object.entries(tokens.typography).forEach(([name, styles]) => {
        const mixinName = `.text-${this.sanitizeName(name)}`;
        output.push(`${mixinName} {`);

        if (styles.fontSize) output.push(`  font-size: ${styles.fontSize};`);
        if (styles.fontWeight) output.push(`  font-weight: ${styles.fontWeight};`);
        if (styles.lineHeight) output.push(`  line-height: ${styles.lineHeight};`);
        if (styles.fontFamily) output.push(`  font-family: ${styles.fontFamily};`);

        output.push('}');
      });
    }

    return output.join('\n');
  }
}

class StylusFormatter extends BaseFormatter {
  constructor() {
    super();
    this.name = 'stylus';
  }

  async format(tokens, options = {}) {
    const output = [];

    // Stylus variables
    if (tokens.colors) {
      output.push('// Colors');
      Object.entries(tokens.colors).forEach(([name, value]) => {
        const varName = `$color-${this.sanitizeName(name)}`;
        output.push(`${varName} = ${value}`);
      });
      output.push('');
    }

    if (tokens.spacing) {
      output.push('// Spacing');
      Object.entries(tokens.spacing).forEach(([name, value]) => {
        const varName = `$spacing-${this.sanitizeName(name)}`;
        output.push(`${varName} = ${value}`);
      });
      output.push('');
    }

    if (tokens.typography) {
      output.push('// Typography');
      Object.entries(tokens.typography).forEach(([name, styles]) => {
        const mixinName = `text-${this.sanitizeName(name)}()`;
        output.push(mixinName);

        if (styles.fontSize) output.push(`  font-size ${styles.fontSize}`);
        if (styles.fontWeight) output.push(`  font-weight ${styles.fontWeight}`);
        if (styles.lineHeight) output.push(`  line-height ${styles.lineHeight}`);
        if (styles.fontFamily) output.push(`  font-family ${styles.fontFamily}`);

        output.push('');
      });
    }

    return output.join('\n');
  }
}

class DartFormatter extends BaseFormatter {
  constructor() {
    super();
    this.name = 'dart';
  }

  async format(tokens, options = {}) {
    const { className = 'DesignTokens' } = options;

    let dart = '// Dart/Flutter Design Tokens\n';
    dart += `// Generated: ${new Date().toISOString()}\n\n`;
    dart += 'import \'package:flutter/material.dart\';\n\n';

    dart += `class ${className} {\n`;
    dart += `  ${className}._();\n\n`;

    // Generate colors
    if (tokens.colors) {
      dart += '  // Colors\n';
      Object.entries(tokens.colors).forEach(([name, value]) => {
        const dartName = this.toDartName(name);
        const dartColor = this.formatDartColor(value);
        dart += `  static const Color ${dartName} = ${dartColor};\n`;
      });
      dart += '\n';
    }

    // Generate spacing
    if (tokens.spacing) {
      dart += '  // Spacing\n';
      Object.entries(tokens.spacing).forEach(([name, value]) => {
        const dartName = this.toDartName(name);
        const doubleValue = this.formatDartDouble(value);
        dart += `  static const double ${dartName} = ${doubleValue};\n`;
      });
      dart += '\n';
    }

    // Generate typography
    if (tokens.typography) {
      dart += '  // Typography\n';
      Object.entries(tokens.typography).forEach(([name, value]) => {
        if (value.fontSize) {
          const dartName = this.toDartName(name) + 'Size';
          const sizeValue = this.formatDartDouble(value.fontSize);
          dart += `  static const double ${dartName} = ${sizeValue};\n`;
        }
        if (value.fontWeight) {
          const dartName = this.toDartName(name) + 'Weight';
          const weightValue = this.formatDartFontWeight(value.fontWeight);
          dart += `  static const FontWeight ${dartName} = ${weightValue};\n`;
        }
      });
    }

    dart += '}\n';

    return {
      content: dart,
      metadata: {
        format: 'dart',
        platform: 'flutter'
      }
    };
  }

  toDartName(name) {
    // Convert to camelCase
    const parts = name.split(/[-_]/);
    return parts.map((part, index) => {
      if (index === 0) {
        return part.toLowerCase();
      }
      return part.charAt(0).toUpperCase() + part.slice(1).toLowerCase();
    }).join('');
  }

  formatDartColor(value) {
    if (typeof value === 'string') {
      if (value.startsWith('#')) {
        const hex = value.replace('#', '');
        if (hex.length === 6) {
          return `Color(0xFF${hex.toUpperCase()})`;
        } else if (hex.length === 8) {
          return `Color(0x${hex.toUpperCase()})`;
        }
      }
    } else if (value.hex) {
      return this.formatDartColor(value.hex);
    } else if (value.rgb) {
      const { r, g, b, a = 1 } = value.rgb;
      return `Color.fromRGBO(${r}, ${g}, ${b}, ${a})`;
    }
    return 'Colors.black';
  }

  formatDartDouble(value) {
    if (typeof value === 'number') {
      return value.toString();
    } else if (typeof value === 'string') {
      const numValue = parseFloat(value);
      if (!isNaN(numValue)) {
        return numValue.toString();
      }
    }
    return '0.0';
  }

  formatDartFontWeight(weight) {
    const weightMap = {
      100: 'FontWeight.w100',
      200: 'FontWeight.w200',
      300: 'FontWeight.w300',
      400: 'FontWeight.w400',
      500: 'FontWeight.w500',
      600: 'FontWeight.w600',
      700: 'FontWeight.w700',
      800: 'FontWeight.w800',
      900: 'FontWeight.w900',
      'thin': 'FontWeight.w100',
      'light': 'FontWeight.w300',
      'normal': 'FontWeight.w400',
      'medium': 'FontWeight.w500',
      'bold': 'FontWeight.w700',
      'black': 'FontWeight.w900'
    };

    const key = weight.toString().toLowerCase();
    return weightMap[key] || 'FontWeight.w400';
  }
}

// Export all formatters
module.exports = {
  BaseFormatter,
  CSSFormatter,
  SCSSFormatter,
  LESSFormatter,
  StylusFormatter,
  SassFormatter: SCSSFormatter, // Alias for SCSS formatter
  LessFormatter: LESSFormatter, // Proper LESS formatter
  TypeScriptFormatter,
  JSONFormatter,
  SwiftFormatter,
  YAMLFormatter,
  JavaScriptFormatter,
  KotlinFormatter,
  DartFormatter,
  XMLFormatter: class XMLFormatter {
    format(tokens) {
      let xml = '<?xml version="1.0" encoding="UTF-8"?>\n';
      xml += '<resources>\n';

      // Colors
      if (tokens.colors) {
        xml += '  <!-- Colors -->\n';
        for (const [name, value] of Object.entries(tokens.colors)) {
          xml += `  <color name="${name}">${value}</color>\n`;
        }
      }

      // Dimensions
      if (tokens.spacing) {
        xml += '  <!-- Spacing -->\n';
        for (const [name, value] of Object.entries(tokens.spacing)) {
          xml += `  <dimen name="spacing_${name}">${value}</dimen>\n`;
        }
      }

      // Typography
      if (tokens.typography) {
        xml += '  <!-- Typography -->\n';
        for (const [name, style] of Object.entries(tokens.typography)) {
          xml += `  <style name="Text_${name}">\n`;
          if (style.fontSize) xml += `    <item name="android:textSize">${style.fontSize}</item>\n`;
          if (style.fontWeight) xml += `    <item name="android:textStyle">${style.fontWeight > 500 ? 'bold' : 'normal'}</item>\n`;
          xml += '  </style>\n';
        }
      }

      xml += '</resources>';
      return xml;
    }
  },
  SketchFormatter: class SketchFormatter {
    format(tokens) {
      // Sketch format is a JSON structure
      const sketch = {
        version: 1,
        name: 'Design Tokens',
        colors: [],
        textStyles: [],
        spacing: []
      };

      // Convert colors
      if (tokens.colors) {
        sketch.colors = Object.entries(tokens.colors).map(([name, value]) => ({
          name,
          value: typeof value === 'string' ? value : value.hex || '#000000'
        }));
      }

      // Convert typography
      if (tokens.typography) {
        sketch.textStyles = Object.entries(tokens.typography).map(([name, style]) => ({
          name,
          fontSize: style.fontSize || 16,
          fontFamily: style.fontFamily || 'system-ui',
          fontWeight: style.fontWeight || 400,
          lineHeight: style.lineHeight || 1.5
        }));
      }

      // Convert spacing
      if (tokens.spacing) {
        sketch.spacing = Object.entries(tokens.spacing).map(([name, value]) => ({
          name,
          value: typeof value === 'number' ? value : parseFloat(value) || 0
        }));
      }

      return JSON.stringify(sketch, null, 2);
    }
  },
  PlistFormatter: class PlistFormatter {
    format(tokens) {
      let plist = '<?xml version="1.0" encoding="UTF-8"?>\n';
      plist += '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n';
      plist += '<plist version="1.0">\n';
      plist += '<dict>\n';

      // Add tokens to plist
      if (tokens.colors) {
        plist += '  <key>colors</key>\n';
        plist += '  <dict>\n';
        for (const [name, value] of Object.entries(tokens.colors)) {
          plist += `    <key>${name}</key>\n`;
          plist += `    <string>${value}</string>\n`;
        }
        plist += '  </dict>\n';
      }

      if (tokens.spacing) {
        plist += '  <key>spacing</key>\n';
        plist += '  <dict>\n';
        for (const [name, value] of Object.entries(tokens.spacing)) {
          plist += `    <key>${name}</key>\n`;
          plist += `    <string>${value}</string>\n`;
        }
        plist += '  </dict>\n';
      }

      if (tokens.typography) {
        plist += '  <key>typography</key>\n';
        plist += '  <dict>\n';
        for (const [name, style] of Object.entries(tokens.typography)) {
          plist += `    <key>${name}</key>\n`;
          plist += '    <dict>\n';
          if (style.fontSize) {
            plist += '      <key>fontSize</key>\n';
            plist += `      <string>${style.fontSize}</string>\n`;
          }
          if (style.fontWeight) {
            plist += '      <key>fontWeight</key>\n';
            plist += `      <integer>${style.fontWeight}</integer>\n`;
          }
          if (style.fontFamily) {
            plist += '      <key>fontFamily</key>\n';
            plist += `      <string>${style.fontFamily}</string>\n`;
          }
          plist += '    </dict>\n';
        }
        plist += '  </dict>\n';
      }

      plist += '</dict>\n';
      plist += '</plist>';
      return plist;
    }
  },

  // Figma formatter for compatibility
  FigmaFormatter: class FigmaFormatter extends BaseFormatter {
    format(tokens) {
      const figmaDoc = {
        version: '1.0.0',
        name: 'Design System Tokens',
        lastModified: new Date().toISOString(),
        tokens: {
          colors: {},
          typography: {},
          effects: {},
          grids: {},
          spacing: {}
        }
      };

      // Process colors
      if (tokens.colors) {
        Object.entries(tokens.colors).forEach(([name, value]) => {
          figmaDoc.tokens.colors[name] = {
            value: this.normalizeColor(value),
            type: 'COLOR',
            description: `Color token: ${name}`
          };
        });
      }

      // Process typography
      if (tokens.typography) {
        Object.entries(tokens.typography).forEach(([name, style]) => {
          figmaDoc.tokens.typography[name] = {
            fontFamily: style.fontFamily || 'Inter',
            fontWeight: style.fontWeight || 400,
            fontSize: this.extractNumber(style.fontSize) || 16,
            lineHeight: style.lineHeight || '1.5',
            letterSpacing: style.letterSpacing || '0',
            type: 'TEXT'
          };
        });
      }

      // Process spacing
      if (tokens.spacing) {
        Object.entries(tokens.spacing).forEach(([name, value]) => {
          figmaDoc.tokens.spacing[name] = {
            value: this.extractNumber(value),
            type: 'SPACING',
            unit: 'px'
          };
        });
      }

      // Process effects (shadows, blurs)
      if (tokens.shadows) {
        Object.entries(tokens.shadows).forEach(([name, shadow]) => {
          figmaDoc.tokens.effects[name] = {
            type: 'DROP_SHADOW',
            visible: true,
            color: shadow.color || '#000000',
            blendMode: 'NORMAL',
            offset: {
              x: shadow.x || 0,
              y: shadow.y || 0
            },
            radius: shadow.blur || 0,
            spread: shadow.spread || 0
          };
        });
      }

      return JSON.stringify(figmaDoc, null, 2);
    }
  },

  // Android formatter for native Android development
  AndroidFormatter: class AndroidFormatter extends BaseFormatter {
    format(tokens) {
      let xml = '<?xml version="1.0" encoding="utf-8"?>\n';
      xml += '<resources>\n';

      // Process colors
      if (tokens.colors) {
        xml += '  <!-- Colors -->\n';
        Object.entries(tokens.colors).forEach(([name, value]) => {
          const androidName = this.toAndroidName(name);
          const hexColor = this.normalizeColor(value);
          xml += `  <color name="${androidName}">${hexColor}</color>\n`;
        });
        xml += '\n';
      }

      // Process dimensions (spacing)
      if (tokens.spacing) {
        xml += '  <!-- Dimensions -->\n';
        Object.entries(tokens.spacing).forEach(([name, value]) => {
          const androidName = this.toAndroidName(name);
          const dpValue = this.extractNumber(value);
          xml += `  <dimen name="${androidName}">${dpValue}dp</dimen>\n`;
        });
        xml += '\n';
      }

      // Process text styles
      if (tokens.typography) {
        xml += '  <!-- Text Sizes -->\n';
        Object.entries(tokens.typography).forEach(([name, style]) => {
          if (style.fontSize) {
            const androidName = this.toAndroidName(name + '_size');
            const spValue = this.extractNumber(style.fontSize);
            xml += `  <dimen name="${androidName}">${spValue}sp</dimen>\n`;
          }
        });
        xml += '\n';

        // Font weights as integers
        xml += '  <!-- Font Weights -->\n';
        Object.entries(tokens.typography).forEach(([name, style]) => {
          if (style.fontWeight) {
            const androidName = this.toAndroidName(name + '_weight');
            xml += `  <integer name="${androidName}">${style.fontWeight}</integer>\n`;
          }
        });
      }

      xml += '</resources>';
      return xml;
    }

    toAndroidName(name) {
      // Convert to Android resource naming convention
      return name
        .replace(/([A-Z])/g, '_$1')
        .replace(/[\s\-\.]/g, '_')
        .toLowerCase()
        .replace(/^_/, '')
        .replace(/__+/g, '_');
    }
  }
};

// iOS Swift Formatter (extends SwiftFormatter)
module.exports.iOSFormatter = class iOSFormatter extends module.exports.SwiftFormatter {
  constructor() {
    super();
    this.name = 'iOS Swift';
  }
};

// Flutter Formatter (alias for DartFormatter)
module.exports.FlutterFormatter = class FlutterFormatter extends module.exports.DartFormatter {
  constructor() {
    super();
    this.name = 'Flutter/Dart';
  }
};

// Additional formatters (aliases and variations)
module.exports.ReactNativeFormatter = module.exports.TypeScriptFormatter;
module.exports.SassFormatter = module.exports.SCSSFormatter;
module.exports.LessFormatter = module.exports.LESSFormatter;
module.exports.JSONFormatter = module.exports.JavaScriptFormatter;
module.exports.StyledComponentsFormatter = module.exports.JavaScriptFormatter;
module.exports.EmotionFormatter = module.exports.JavaScriptFormatter;
module.exports.TailwindFormatter = module.exports.CSSFormatter;
module.exports.BootstrapFormatter = module.exports.SCSSFormatter;
module.exports.StyleDictionaryFormatter = module.exports.JavaScriptFormatter;
module.exports.TheorySixFormatter = module.exports.JavaScriptFormatter;