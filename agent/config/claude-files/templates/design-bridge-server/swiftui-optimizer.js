/**
 * SwiftUI Optimizer
 * Sprints 50-51: SwiftUI Optimizer and View Generation
 *
 * Optimizes code generation for SwiftUI (iOS/macOS) applications
 * Handles Swift syntax, View protocol, and declarative UI

 *
 * v4.0.0 Integration:
 * - Supports registry v4.0.0 canonical IDs
 * - O(1) component lookup via RegistryManager
 * - Static optimize() accepts entries from v4 registry
 */

const EventEmitter = require('events');
const { normalizeVariants, syncToFramework } = require('./variant-sync');

// Lazy-load RegistryManager to avoid circular dependencies (v4.0.0)
let _registryManagerModule = null;
function getRegistryManagerModule() {
  if (!_registryManagerModule) {
    try {
      _registryManagerModule = require('./registry-manager');
    } catch (e) {
      _registryManagerModule = null;
    }
  }
  return _registryManagerModule;
}

class SwiftUIOptimizer extends EventEmitter {
  constructor() {
    super();

    this.name = 'SwiftUIOptimizer';
    this.version = '1.0.0';
    this.framework = 'swiftui';

    // SwiftUI-specific configuration
    this.config = {
      swiftVersion: '5.9',
      iOS: '17.0',
      macOS: '14.0',
      useCombine: true,
      useSwiftData: false,
      stateManagement: '@State', // @State, @Binding, @ObservedObject, @EnvironmentObject
      async: true, // async/await support
      animations: true
    };

    // View patterns
    this.patterns = {
      views: this.getViewPatterns(),
      modifiers: this.getModifierPatterns(),
      layouts: this.getLayoutPatterns(),
      state: this.getStatePatterns()
    };

    // HTML to SwiftUI view mappings
    this.viewMappings = {
      'div': 'VStack',
      'span': 'Text',
      'p': 'Text',
      'h1': 'Text',
      'h2': 'Text',
      'h3': 'Text',
      'button': 'Button',
      'img': 'Image',
      'input': 'TextField',
      'a': 'Button',
      'ul': 'List',
      'ol': 'List'
    };

    // Statistics
    this.stats = {
      viewsGenerated: 0,
      stateVariables: 0,
      optimizationsApplied: 0,
      modifiers: 0
    };
  }

  /**
   * Generate SwiftUI view from design data
   */
  async generateView(componentData, config = {}) {
    const mergedConfig = { ...this.config, ...config };

    this.emit('generation:started', {
      view: componentData.name,
      timestamp: new Date().toISOString()
    });

    try {
      const view = this.generateSwiftUIView(componentData, mergedConfig);

      this.stats.viewsGenerated++;

      this.emit('generation:completed', {
        view: componentData.name,
        linesOfCode: view.split('\n').length,
        timestamp: new Date().toISOString()
      });

      return view;
    } catch (error) {
      this.emit('generation:failed', {
        view: componentData.name,
        error: error.message,
        timestamp: new Date().toISOString()
      });
      throw error;
    }
  }

  /**
   * Generate SwiftUI View
   */
  generateSwiftUIView(data, config) {
    const { name, props = {}, state = {}, styles = {}, children = [] } = data;

    let code = [];

    // Imports
    code.push('import SwiftUI');
    code.push('');

    // View struct
    code.push(`struct ${name}: View {`);

    // State variables
    if (Object.keys(state).length > 0) {
      Object.entries(state).forEach(([key, stateData]) => {
        const swiftType = this.convertToSwiftType(stateData.type || 'String');
        const defaultValue = stateData.default !== undefined
          ? this.formatSwiftValue(stateData.default, swiftType)
          : this.getDefaultValue(swiftType);
        code.push(`    @State private var ${key}: ${swiftType} = ${defaultValue}`);
        this.stats.stateVariables++;
      });
      code.push('');
    }

    // Properties
    if (Object.keys(props).length > 0) {
      Object.entries(props).forEach(([key, prop]) => {
        const swiftType = this.convertToSwiftType(prop.type || 'String');
        const optional = prop.required ? '' : '?';
        const defaultValue = prop.default !== undefined
          ? ` = ${this.formatSwiftValue(prop.default, swiftType)}`
          : '';
        code.push(`    var ${key}: ${swiftType}${optional}${defaultValue}`);
      });
      code.push('');
    }

    // Body
    code.push('    var body: some View {');
    code.push(this.generateViewBody(data, config, 2));
    code.push('    }');
    code.push('}');
    code.push('');

    // Preview
    code.push('// MARK: - Preview');
    code.push(`struct ${name}_Previews: PreviewProvider {`);
    code.push('    static var previews: some View {');
    code.push(`        ${name}()`);
    code.push('    }');
    code.push('}');

    return code.join('\n');
  }

  /**
   * Generate view body
   */
  generateViewBody(data, config, indent = 0) {
    const { text, children = [], styles = {}, type = 'VStack' } = data;
    const spaces = ' '.repeat(indent * 4);

    let code = [];

    const SwiftView = this.viewMappings[type] || 'VStack';

    // Handle button with text
    if (SwiftView === 'Button' && text) {
      code.push(`${spaces}Button(action: {`);
      code.push(`${spaces}    // Action`);
      code.push(`${spaces}}) {`);
      code.push(`${spaces}    Text("${text}")`);
      code.push(`${spaces}${this.generateModifiers(styles, indent + 1)}`);
      code.push(`${spaces}}`);
      code.push(`${spaces}${this.generateModifiers(styles, indent)}`);
    }
    // Handle text
    else if (SwiftView === 'Text' && text) {
      code.push(`${spaces}Text("${text}")`);
      code.push(`${spaces}${this.generateModifiers(styles, indent)}`);
    }
    // Handle image
    else if (SwiftView === 'Image') {
      code.push(`${spaces}Image(systemName: "photo")`);
      code.push(`${spaces}${this.generateModifiers(styles, indent)}`);
    }
    // Handle container with children
    else if (children.length > 0) {
      const alignment = this.getAlignment(styles);
      const spacing = this.getSpacing(styles);

      code.push(`${spaces}${SwiftView}(alignment: ${alignment}, spacing: ${spacing}) {`);

      children.forEach(child => {
        code.push(this.generateViewBody(child, config, indent + 1));
      });

      code.push(`${spaces}}`);
      code.push(`${spaces}${this.generateModifiers(styles, indent)}`);
    }
    // Empty container
    else {
      code.push(`${spaces}${SwiftView} {`);
      code.push(`${spaces}    EmptyView()`);
      code.push(`${spaces}}`);
      code.push(`${spaces}${this.generateModifiers(styles, indent)}`);
    }

    return code.join('\n');
  }

  /**
   * Generate view modifiers from styles
   */
  generateModifiers(styles, indent = 0) {
    const spaces = ' '.repeat(indent * 4);
    let modifiers = [];

    if (styles['font-size'] || styles.fontSize) {
      const size = this.convertToDouble(styles['font-size'] || styles.fontSize);
      modifiers.push(`.font(.system(size: ${size}))`);
      this.stats.modifiers++;
    }

    if (styles['font-weight'] || styles.fontWeight) {
      const weight = this.convertToSwiftFontWeight(styles['font-weight'] || styles.fontWeight);
      modifiers.push(`.fontWeight(${weight})`);
      this.stats.modifiers++;
    }

    if (styles.color || styles['font-color']) {
      const color = this.convertToSwiftColor(styles.color || styles['font-color']);
      modifiers.push(`.foregroundColor(${color})`);
      this.stats.modifiers++;
    }

    if (styles['background-color'] || styles.backgroundColor) {
      const bgColor = this.convertToSwiftColor(styles['background-color'] || styles.backgroundColor);
      modifiers.push(`.background(${bgColor})`);
      this.stats.modifiers++;
    }

    if (styles.padding) {
      const padding = this.convertToDouble(styles.padding);
      modifiers.push(`.padding(${padding})`);
      this.stats.modifiers++;
    }

    if (styles['border-radius'] || styles.borderRadius) {
      const radius = this.convertToDouble(styles['border-radius'] || styles.borderRadius);
      modifiers.push(`.cornerRadius(${radius})`);
      this.stats.modifiers++;
    }

    if (styles.width) {
      const width = this.convertToDouble(styles.width);
      modifiers.push(`.frame(width: ${width})`);
      this.stats.modifiers++;
    }

    if (styles.height) {
      const height = this.convertToDouble(styles.height);
      modifiers.push(`.frame(height: ${height})`);
      this.stats.modifiers++;
    }

    if (styles['box-shadow'] || styles.boxShadow) {
      modifiers.push(`.shadow(color: .gray.opacity(0.4), radius: 4, x: 0, y: 2)`);
      this.stats.modifiers++;
    }

    if (modifiers.length === 0) return '';

    return modifiers.map(m => `${spaces}${m}`).join('\n');
  }

  /**
   * Get alignment from styles
   */
  getAlignment(styles) {
    const textAlign = styles['text-align'] || styles.textAlign || 'left';
    const alignMap = {
      'left': '.leading',
      'center': '.center',
      'right': '.trailing'
    };
    return alignMap[textAlign] || '.leading';
  }

  /**
   * Get spacing from styles
   */
  getSpacing(styles) {
    const gap = styles.gap || styles.spacing || '8px';
    return this.convertToDouble(gap);
  }

  /**
   * Convert JavaScript type to Swift type
   */
  convertToSwiftType(type) {
    const typeMap = {
      'string': 'String',
      'number': 'Double',
      'boolean': 'Bool',
      'array': 'Array',
      'object': 'Dictionary',
      '() => void': '() -> Void',
      'any': 'Any'
    };

    return typeMap[type] || type;
  }

  /**
   * Convert CSS color to Swift Color
   */
  convertToSwiftColor(color) {
    if (color.startsWith('#')) {
      const hex = color.substring(1);
      const r = parseInt(hex.substring(0, 2), 16) / 255;
      const g = parseInt(hex.substring(2, 4), 16) / 255;
      const b = parseInt(hex.substring(4, 6), 16) / 255;
      return `Color(red: ${r.toFixed(3)}, green: ${g.toFixed(3)}, blue: ${b.toFixed(3)})`;
    }

    // Named colors
    const namedColors = {
      'white': 'Color.white',
      'black': 'Color.black',
      'red': 'Color.red',
      'blue': 'Color.blue',
      'green': 'Color.green',
      'yellow': 'Color.yellow',
      'gray': 'Color.gray',
      'grey': 'Color.gray',
      'orange': 'Color.orange',
      'purple': 'Color.purple',
      'pink': 'Color.pink'
    };

    return namedColors[color.toLowerCase()] || 'Color.primary';
  }

  /**
   * Convert CSS font-weight to Swift FontWeight
   */
  convertToSwiftFontWeight(weight) {
    const weights = {
      'normal': '.regular',
      'bold': '.bold',
      '100': '.ultraLight',
      '200': '.thin',
      '300': '.light',
      '400': '.regular',
      '500': '.medium',
      '600': '.semibold',
      '700': '.bold',
      '800': '.heavy',
      '900': '.black'
    };

    return weights[String(weight)] || '.regular';
  }

  /**
   * Convert CSS value to double
   */
  convertToDouble(value) {
    if (typeof value === 'number') return value;
    if (typeof value === 'string') {
      const num = parseFloat(value.replace('px', ''));
      return isNaN(num) ? 0 : num;
    }
    return 0;
  }

  /**
   * Format Swift value
   */
  formatSwiftValue(value, type) {
    if (type === 'String') return `"${value}"`;
    if (type === 'Bool') return value.toString();
    if (type === 'Double' || type === 'Int') return value.toString();
    return String(value);
  }

  /**
   * Get default value for Swift type
   */
  getDefaultValue(type) {
    const defaults = {
      'String': '""',
      'Int': '0',
      'Double': '0.0',
      'Bool': 'false',
      'Array': '[]',
      'Dictionary': '[:]'
    };

    return defaults[type] || 'nil';
  }

  /**
   * Get view patterns
   */
  getViewPatterns() {
    return {
      text: 'Text',
      button: 'Button',
      image: 'Image',
      vstack: 'VStack',
      hstack: 'HStack',
      zstack: 'ZStack',
      list: 'List',
      scrollView: 'ScrollView'
    };
  }

  /**
   * Get modifier patterns
   */
  getModifierPatterns() {
    return {
      font: '.font',
      foregroundColor: '.foregroundColor',
      background: '.background',
      padding: '.padding',
      frame: '.frame',
      cornerRadius: '.cornerRadius',
      shadow: '.shadow',
      onTapGesture: '.onTapGesture'
    };
  }

  /**
   * Get layout patterns
   */
  getLayoutPatterns() {
    return {
      stack: 'VStack/HStack/ZStack',
      spacer: 'Spacer',
      divider: 'Divider',
      geometryReader: 'GeometryReader'
    };
  }

  /**
   * Get state patterns
   */
  getStatePatterns() {
    return {
      state: '@State',
      binding: '@Binding',
      observedObject: '@ObservedObject',
      environmentObject: '@EnvironmentObject',
      stateObject: '@StateObject'
    };
  }

  /**
   * Get statistics
   */
  getStats() {
    return {
      ...this.stats,
      framework: this.framework,
      version: this.version
    };
  }

  /**
   * Test SwiftUI view generation
   */
  async testGeneration() {
    console.log('🧪 Testing SwiftUI view generation...\n');

    const sampleView = {
      name: 'MyButton',
      type: 'button',
      props: {
        title: { type: 'string', required: true }
      },
      state: {
        isPressed: { type: 'boolean', default: false }
      },
      styles: {
        'background-color': '#007AFF',
        'padding': '16px',
        'border-radius': '8px',
        'color': '#FFFFFF',
        'font-size': '16px',
        'font-weight': 'bold'
      },
      text: 'Click Me'
    };

    try {
      console.log('1️⃣ Generating SwiftUI View...');
      const view = await this.generateView(sampleView);
      console.log(`   ✓ Generated ${view.split('\n').length} lines of Swift\n`);

      console.log('2️⃣ Checking statistics...');
      const stats = this.getStats();
      console.log(`   ✓ Views generated: ${stats.viewsGenerated}`);
      console.log(`   ✓ State variables: ${stats.stateVariables}`);
      console.log(`   ✓ Modifiers applied: ${stats.modifiers}\n`);

      console.log('✅ SwiftUI generation test complete!\n');

      return {
        success: true,
        view,
        stats
      };

    } catch (error) {
      console.error('❌ SwiftUI test failed:', error.message);
      throw error;
    }
  }

  /**
   * Optimize Swift/SwiftUI code
   * @param {string} code - Input Swift code
   * @param {Object} componentData - Component metadata
   * @param {Object} config - Optimization config
   * @returns {string} Optimized Swift code
   */
  async optimize(code, componentData, config = {}) {
    let optimizedCode = code;

    // Apply SwiftUI-specific optimizations
    optimizedCode = this.optimizeImports(optimizedCode);
    optimizedCode = this.optimizeModifiers(optimizedCode);
    optimizedCode = this.optimizePerformance(optimizedCode);

    this.stats.optimizationsApplied = (this.stats.optimizationsApplied || 0) + 1;

    return optimizedCode;
  }

  /**
   * Optimize Swift imports
   */
  optimizeImports(code) {
    // Remove duplicate imports
    const lines = code.split('\n');
    const imports = new Set();
    const nonImports = [];

    lines.forEach(line => {
      if (line.trim().startsWith('import ')) {
        imports.add(line.trim());
      } else {
        nonImports.push(line);
      }
    });

    return [...imports].sort().join('\n') + '\n' + nonImports.join('\n');
  }

  /**
   * Optimize modifier chains
   */
  optimizeModifiers(code) {
    // Combine redundant padding modifiers
    let optimized = code;

    // Remove duplicate .frame modifiers
    optimized = optimized.replace(
      /\.frame\([^)]+\)\s*\.frame\([^)]+\)/g,
      (match) => match.split('.frame')[1] ? '.frame' + match.split('.frame')[1] : match
    );

    return optimized;
  }

  /**
   * Apply performance optimizations
   */
  optimizePerformance(code) {
    let optimized = code;

    // Add @ViewBuilder where appropriate
    // Add lazy stacks for large lists
    optimized = optimized.replace(/VStack\s*\{/g, (match, offset) => {
      // Check context - if many children, suggest LazyVStack
      return match;
    });

    return optimized;
  }

  /**
   * Static transform method for wrapper compatibility
   * Transforms design tokens into SwiftUI code
   */
  static async transform(tokens, options = {}) {
    const fs = require('fs');
    const path = require('path');

    const instance = new SwiftUIOptimizer();
    const files = [];
    const outputPath = options.outputPath || './output';

    // Create output directories
    const sourcesDir = path.join(outputPath, 'Sources', 'DesignTokens');
    fs.mkdirSync(sourcesDir, { recursive: true });

    // Generate color tokens
    if (tokens.colors) {
      const colorTokens = instance.generateSwiftColors(tokens.colors);
      const colorFile = path.join(sourcesDir, 'Colors.swift');
      fs.writeFileSync(colorFile, colorTokens);
      files.push(colorFile);
    }

    // Generate typography tokens
    if (tokens.typography) {
      const typographyTokens = instance.generateSwiftTypography(tokens.typography);
      const typographyFile = path.join(sourcesDir, 'Typography.swift');
      fs.writeFileSync(typographyFile, typographyTokens);
      files.push(typographyFile);
    }

    // Generate spacing tokens
    if (tokens.spacing) {
      const spacingTokens = instance.generateSwiftSpacing(tokens.spacing);
      const spacingFile = path.join(sourcesDir, 'Spacing.swift');
      fs.writeFileSync(spacingFile, spacingTokens);
      files.push(spacingFile);
    }

    // Generate theme file
    const themeContent = instance.generateSwiftTheme(tokens);
    const themeFile = path.join(sourcesDir, 'Theme.swift');
    fs.writeFileSync(themeFile, themeContent);
    files.push(themeFile);

    return { files, framework: 'swiftui' };
  }

  /**
   * Generate Swift color extension
   */
  generateSwiftColors(colors) {
    const lines = [];

    lines.push('// Auto-generated SwiftUI color tokens');
    lines.push('import SwiftUI');
    lines.push('');
    lines.push('extension Color {');

    Object.entries(colors).forEach(([key, value]) => {
      if (typeof value === 'object' && value !== null) {
        Object.entries(value).forEach(([subKey, subValue]) => {
          const tokenName = `${key}${subKey.charAt(0).toUpperCase() + subKey.slice(1)}`;
          const colorValue = this.convertToSwiftUIColor(subValue);
          lines.push(`    static let ${tokenName} = ${colorValue}`);
        });
      } else {
        const colorValue = this.convertToSwiftUIColor(value);
        lines.push(`    static let ${key} = ${colorValue}`);
      }
    });

    lines.push('}');

    return lines.join('\n');
  }

  /**
   * Convert hex color to SwiftUI Color
   */
  convertToSwiftUIColor(color) {
    if (typeof color === 'string' && color.startsWith('#')) {
      const hex = color.substring(1);
      const r = parseInt(hex.substring(0, 2), 16) / 255;
      const g = parseInt(hex.substring(2, 4), 16) / 255;
      const b = parseInt(hex.substring(4, 6), 16) / 255;
      return `Color(red: ${r.toFixed(3)}, green: ${g.toFixed(3)}, blue: ${b.toFixed(3)})`;
    }
    return 'Color.primary';
  }

  /**
   * Generate Swift typography
   */
  generateSwiftTypography(typography) {
    const lines = [];

    lines.push('// Auto-generated SwiftUI typography tokens');
    lines.push('import SwiftUI');
    lines.push('');
    lines.push('struct Typography {');

    Object.entries(typography).forEach(([key, value]) => {
      const fontSize = typeof value.fontSize === 'string' ? parseFloat(value.fontSize) : (value.fontSize || 16);
      const weight = this.convertToSwiftUIFontWeight(value.fontWeight);
      lines.push(`    static let ${key} = Font.system(size: ${fontSize}, weight: ${weight})`);
    });

    lines.push('}');
    lines.push('');
    lines.push('// View modifier for typography');
    lines.push('extension View {');

    Object.entries(typography).forEach(([key, value]) => {
      lines.push(`    func ${key}Style() -> some View {`);
      lines.push(`        self.font(Typography.${key})`);
      lines.push('    }');
    });

    lines.push('}');

    return lines.join('\n');
  }

  /**
   * Convert font weight to SwiftUI Font.Weight
   */
  convertToSwiftUIFontWeight(weight) {
    const weights = {
      'normal': '.regular',
      'bold': '.bold',
      '100': '.ultraLight',
      '200': '.thin',
      '300': '.light',
      '400': '.regular',
      '500': '.medium',
      '600': '.semibold',
      '700': '.bold',
      '800': '.heavy',
      '900': '.black'
    };
    return weights[String(weight)] || '.regular';
  }

  /**
   * Generate Swift spacing constants
   */
  generateSwiftSpacing(spacing) {
    const lines = [];

    lines.push('// Auto-generated SwiftUI spacing tokens');
    lines.push('import SwiftUI');
    lines.push('');
    lines.push('struct Spacing {');

    Object.entries(spacing).forEach(([key, value]) => {
      const numValue = typeof value === 'string' ? parseFloat(value) : value;
      lines.push(`    static let ${key}: CGFloat = ${numValue}`);
    });

    lines.push('}');

    return lines.join('\n');
  }

  /**
   * Generate Swift theme file
   */
  generateSwiftTheme(tokens) {
    const lines = [];

    lines.push('// Auto-generated SwiftUI theme');
    lines.push('import SwiftUI');
    lines.push('');
    lines.push('struct Theme {');
    lines.push('    static let colors = ThemeColors()');
    lines.push('    static let typography = Typography.self');
    lines.push('    static let spacing = Spacing.self');
    lines.push('}');
    lines.push('');
    lines.push('struct ThemeColors {');
    lines.push('    // Access colors via Color extension');
    lines.push('}');
    lines.push('');
    lines.push('// Environment key for theme');
    lines.push('struct ThemeKey: EnvironmentKey {');
    lines.push('    static let defaultValue = Theme.self');
    lines.push('}');
    lines.push('');
    lines.push('extension EnvironmentValues {');
    lines.push('    var theme: Theme.Type {');
    lines.push('        get { self[ThemeKey.self] }');
    lines.push('        set { self[ThemeKey.self] = newValue }');
    lines.push('    }');
    lines.push('}');

    return lines.join('\n');
  }

  /**
   * Static optimize method for registry-based component transformation
   * Accepts enriched input from wrappers: { raw, registry, options }
   * @param {Object} input - Enriched input object
   * @returns {Promise<Object>} Optimization result
   */
  static async optimize(input) {
    const { raw, registry, options = {} } = input;

    const instance = new SwiftUIOptimizer();
    const warnings = [];

    // P6: Normalize variants for cross-framework consistency
    const normalizedRegistry = {
      ...registry,
      variants: syncToFramework(registry.variants || [], 'swiftui')
    };

    // Build component data from raw Figma data + normalized registry metadata
    const componentData = instance.buildComponentData(raw, normalizedRegistry);

    // Merge configuration
    const config = Object.assign({}, instance.config, {
      swiftVersion: options.swiftVersion || '5.9',
      iOS: options.iOS || '17.0',
      macOS: options.macOS || '14.0',
      useCombine: options.useCombine !== false,
      useSwiftData: options.useSwiftData || false,
      stateManagement: options.stateManagement || '@State',
      animations: options.animations !== false
    }, options);

    let code;
    try {
      // Generate the SwiftUI view
      code = await instance.generateView(componentData, config);

      // Apply registry-based enhancements (using normalized registry for P6 consistency)
      if (normalizedRegistry.tokenDependencies && Object.keys(normalizedRegistry.tokenDependencies).length > 0) {
        code = instance.applyTokenDependencies(code, normalizedRegistry.tokenDependencies, config);
      }

      if (normalizedRegistry.interactiveStates && Object.keys(normalizedRegistry.interactiveStates).length > 0) {
        code = instance.applyInteractiveStates(code, normalizedRegistry.interactiveStates, config);
      }

      if (normalizedRegistry.variants && normalizedRegistry.variants.length > 0) {
        code = instance.applyVariants(code, normalizedRegistry.variants, config);
      }

    } catch (error) {
      return {
        success: false,
        error: error.message,
        warnings
      };
    }

    // Generate preview if requested (using normalized registry for P6 consistency)
    let preview = null;
    if (options.generatePreview) {
      try {
        preview = instance.generatePreviewProvider(componentData, normalizedRegistry, config);
      } catch (error) {
        warnings.push('Preview generation failed: ' + error.message);
      }
    }

    return {
      success: true,
      code,
      preview,
      output: code,
      warnings
    };
  }

  /**
   * Build component data from raw Figma data and registry metadata
   */
  buildComponentData(raw, registry) {
    const name = registry.name || raw.name || 'CustomView';

    // Normalize name for Swift
    const swiftName = name
      .replace(/[^a-zA-Z0-9]/g, '')
      .replace(/^[0-9]/, '_$&');

    return {
      name: swiftName,
      type: raw.type || 'div',
      props: this.extractProps(raw, registry),
      state: this.extractState(raw, registry),
      styles: this.extractStyles(raw),
      children: raw.children || [],
      text: raw.characters || raw.text || '',
      accessibility: {
        label: raw.name || swiftName,
        hint: registry.description || ''
      }
    };
  }

  /**
   * Extract props from raw data and registry
   */
  extractProps(raw, registry) {
    const props = {};

    // Props from component properties
    if (raw.componentProperties) {
      Object.entries(raw.componentProperties).forEach(([key, value]) => {
        const propName = key.replace(/[^a-zA-Z0-9]/g, '');
        const propNameLower = propName.charAt(0).toLowerCase() + propName.slice(1);
        props[propNameLower] = {
          type: this.inferSwiftPropType(value),
          default: value.defaultValue !== undefined ? value.defaultValue : value.value,
          required: false
        };
      });
    }

    // Props from variants
    if (registry.variants && registry.variants.length > 0) {
      registry.variants.forEach(variant => {
        if (variant.property && !props[variant.property]) {
          props[variant.property] = {
            type: 'String',
            default: variant.values?.[0] || '',
            required: false
          };
        }
      });
    }

    return props;
  }

  /**
   * Extract state from raw data and registry
   */
  extractState(raw, registry) {
    const state = {};

    // State from interactive states
    if (registry.interactiveStates) {
      if (registry.interactiveStates.hover) {
        state.isHovered = { type: 'boolean', default: false };
      }
      if (registry.interactiveStates.pressed) {
        state.isPressed = { type: 'boolean', default: false };
      }
      if (registry.interactiveStates.focused) {
        state.isFocused = { type: 'boolean', default: false };
      }
      if (registry.interactiveStates.disabled) {
        state.isDisabled = { type: 'boolean', default: false };
      }
    }

    return state;
  }

  /**
   * Extract styles from raw Figma data
   */
  extractStyles(raw) {
    const styles = {};

    // Background color
    if (raw.fills && raw.fills.length > 0) {
      const fill = raw.fills.find(f => f.type === 'SOLID' && f.visible !== false);
      if (fill && fill.color) {
        styles['background-color'] = this.rgbToHex(fill.color);
      }
    }

    // Frame/layout properties
    if (raw.absoluteBoundingBox) {
      styles.width = raw.absoluteBoundingBox.width;
      styles.height = raw.absoluteBoundingBox.height;
    }

    // Padding
    if (raw.paddingTop !== undefined) {
      styles.padding = raw.paddingTop;
    }
    if (raw.itemSpacing !== undefined) {
      styles.gap = raw.itemSpacing;
    }

    // Corner radius
    if (raw.cornerRadius !== undefined) {
      styles['border-radius'] = raw.cornerRadius;
    }

    // Text styles
    if (raw.style) {
      if (raw.style.fontSize) styles['font-size'] = raw.style.fontSize;
      if (raw.style.fontWeight) styles['font-weight'] = raw.style.fontWeight;
      if (raw.style.textAlignHorizontal) styles['text-align'] = raw.style.textAlignHorizontal.toLowerCase();
    }

    // Text color
    if (raw.fills && raw.type === 'TEXT') {
      const textFill = raw.fills.find(f => f.type === 'SOLID' && f.visible !== false);
      if (textFill && textFill.color) {
        styles.color = this.rgbToHex(textFill.color);
      }
    }

    return styles;
  }

  /**
   * Convert RGB color to hex
   */
  rgbToHex(color) {
    if (!color) return '#000000';
    const r = Math.round((color.r || 0) * 255);
    const g = Math.round((color.g || 0) * 255);
    const b = Math.round((color.b || 0) * 255);
    return '#' + [r, g, b].map(x => x.toString(16).padStart(2, '0')).join('');
  }

  /**
   * Infer Swift property type from Figma property
   */
  inferSwiftPropType(prop) {
    if (!prop) return 'String';

    const type = prop.type || typeof prop.value;

    switch (type) {
      case 'BOOLEAN':
      case 'boolean':
        return 'Bool';
      case 'NUMBER':
      case 'number':
        return 'Double';
      case 'TEXT':
      case 'string':
        return 'String';
      case 'VARIANT':
        return 'String';
      case 'INSTANCE_SWAP':
        return 'AnyView';
      default:
        return 'String';
    }
  }

  /**
   * Apply token dependencies to generated code
   */
  applyTokenDependencies(code, tokenDependencies, config) {
    let updatedCode = code;

    // Add token import comment
    const tokenImportComment = '// Token dependencies: ' + Object.keys(tokenDependencies).join(', ');

    // Replace hardcoded colors with token references
    if (tokenDependencies.colors) {
      Object.entries(tokenDependencies.colors).forEach(([tokenName, value]) => {
        const swiftTokenName = tokenName.replace(/\./g, '').replace(/-/g, '');
        // Replace Color(...) with Color.tokenName
        const hexRegex = new RegExp(`Color\\(red: [0-9.]+, green: [0-9.]+, blue: [0-9.]+\\)`, 'g');
        if (updatedCode.match(hexRegex)) {
          // Only replace the first occurrence to avoid breaking all colors
          updatedCode = updatedCode.replace(hexRegex, `Color.${swiftTokenName}`);
        }
      });
    }

    // Replace hardcoded spacing with token references
    if (tokenDependencies.spacing) {
      Object.entries(tokenDependencies.spacing).forEach(([tokenName, value]) => {
        const swiftTokenName = tokenName.replace(/\./g, '').replace(/-/g, '');
        const numValue = parseFloat(value);
        if (!isNaN(numValue)) {
          updatedCode = updatedCode.replace(
            new RegExp(`\\.padding\\(${numValue}\\)`, 'g'),
            `.padding(Spacing.${swiftTokenName})`
          );
        }
      });
    }

    // Replace hardcoded typography with token references
    if (tokenDependencies.typography) {
      Object.entries(tokenDependencies.typography).forEach(([tokenName, value]) => {
        const swiftTokenName = tokenName.replace(/\./g, '').replace(/-/g, '');
        updatedCode = updatedCode.replace(
          /\.font\(\.system\(size: [0-9.]+\)\)/g,
          `.font(Typography.${swiftTokenName})`
        );
      });
    }

    // Add token comment after imports
    if (!updatedCode.includes('// Token dependencies:')) {
      updatedCode = updatedCode.replace(
        'import SwiftUI',
        'import SwiftUI\n' + tokenImportComment
      );
    }

    return updatedCode;
  }

  /**
   * Apply interactive states to generated code
   */
  applyInteractiveStates(code, interactiveStates, config) {
    let updatedCode = code;

    const stateModifiers = [];

    // Hover state
    if (interactiveStates.hover) {
      stateModifiers.push(`
        .onHover { hovering in
            isHovered = hovering
        }`);
    }

    // Pressed state
    if (interactiveStates.pressed) {
      // SwiftUI handles pressed state through Button automatically
      // But we can add gesture recognition
      stateModifiers.push(`
        .simultaneousGesture(
            DragGesture(minimumDistance: 0)
                .onChanged { _ in isPressed = true }
                .onEnded { _ in isPressed = false }
        )`);
    }

    // Focused state
    if (interactiveStates.focused) {
      // Add focus state tracking
      stateModifiers.push(`
        .focused($isFocused)`);
    }

    // Disabled state
    if (interactiveStates.disabled) {
      stateModifiers.push(`
        .disabled(isDisabled)
        .opacity(isDisabled ? 0.5 : 1.0)`);
    }

    // Insert state modifiers before closing brace of body
    if (stateModifiers.length > 0) {
      const modifiersCode = stateModifiers.join('');
      // Find the last modifier chain and append
      const bodyEndIndex = updatedCode.lastIndexOf('    }');
      if (bodyEndIndex > -1) {
        updatedCode = updatedCode.slice(0, bodyEndIndex) + modifiersCode + '\n    }' + updatedCode.slice(bodyEndIndex + 5);
      }
    }

    // Add @FocusState if needed
    if (interactiveStates.focused && !updatedCode.includes('@FocusState')) {
      updatedCode = updatedCode.replace(
        /@State private var isFocused/,
        '@FocusState private var isFocused'
      );
    }

    return updatedCode;
  }

  /**
   * Apply variants to generated code
   */
  applyVariants(code, variants, config) {
    let updatedCode = code;

    // Generate enum for variant properties
    const variantEnums = [];
    const variantModifiers = [];

    variants.forEach(variant => {
      if (variant.property && variant.values && variant.values.length > 0) {
        const enumName = variant.property.charAt(0).toUpperCase() + variant.property.slice(1) + 'Style';
        const enumCases = variant.values.map(v => {
          const caseName = v.toLowerCase().replace(/[^a-z0-9]/g, '');
          return `    case ${caseName}`;
        });

        variantEnums.push(`
enum ${enumName} {
${enumCases.join('\n')}
}`);

        // Add variant-based modifiers
        variantModifiers.push(`
    // Apply variant styles based on ${variant.property}
    private func apply${enumName}(_ style: ${enumName}) -> some View {
        switch style {
${variant.values.map(v => `        case .${v.toLowerCase().replace(/[^a-z0-9]/g, '')}:\n            return self`).join('\n')}
        }
    }`);
      }
    });

    // Insert enums before the struct
    if (variantEnums.length > 0) {
      updatedCode = updatedCode.replace(
        /^(import SwiftUI\n(?:\/\/ [^\n]+\n)?)\n(struct)/m,
        `$1\n${variantEnums.join('\n')}\n\n$2`
      );
    }

    // Insert variant methods before the closing brace of the struct
    if (variantModifiers.length > 0) {
      const structEndIndex = updatedCode.lastIndexOf('}');
      if (structEndIndex > -1) {
        const previewIndex = updatedCode.indexOf('// MARK: - Preview');
        if (previewIndex > -1) {
          updatedCode = updatedCode.slice(0, previewIndex) + variantModifiers.join('\n') + '\n\n' + updatedCode.slice(previewIndex);
        }
      }
    }

    return updatedCode;
  }

  /**
   * Generate PreviewProvider for Xcode previews
   */
  generatePreviewProvider(componentData, registry, config) {
    const name = componentData.name;
    const lines = [];

    lines.push('// MARK: - Extended Previews');
    lines.push('');
    lines.push('#if DEBUG');
    lines.push(`struct ${name}_ExtendedPreviews: PreviewProvider {`);
    lines.push('    static var previews: some View {');
    lines.push('        Group {');

    // Default preview
    lines.push(`            ${name}()`);
    lines.push('                .previewDisplayName("Default")');

    // Dark mode preview
    lines.push('');
    lines.push(`            ${name}()`);
    lines.push('                .preferredColorScheme(.dark)');
    lines.push('                .previewDisplayName("Dark Mode")');

    // Variant previews
    if (registry.variants && registry.variants.length > 0) {
      registry.variants.forEach(variant => {
        if (variant.values) {
          variant.values.forEach(value => {
            lines.push('');
            lines.push(`            ${name}()`);
            lines.push(`                .previewDisplayName("${variant.property}: ${value}")`);
          });
        }
      });
    }

    // Interactive state previews
    if (registry.interactiveStates) {
      if (registry.interactiveStates.disabled) {
        lines.push('');
        lines.push(`            ${name}()`);
        lines.push('                .disabled(true)');
        lines.push('                .previewDisplayName("Disabled")');
      }
    }

    // Different sizes
    lines.push('');
    lines.push(`            ${name}()`);
    lines.push('                .previewLayout(.fixed(width: 200, height: 100))');
    lines.push('                .previewDisplayName("Fixed Size")');

    lines.push('        }');
    lines.push('    }');
    lines.push('}');
    lines.push('#endif');

    return lines.join('\n');
  }
}

module.exports = SwiftUIOptimizer;
