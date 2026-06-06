/**
 * Flutter/Dart Optimizer
 * Sprint 48: Flutter/Dart Optimizer Setup
 *
 * Optimizes code generation for Flutter applications
 * Handles Dart syntax, Widget trees, and Material Design

 *
 * v4.0.0 Integration:
 * - Supports registry v4.0.0 canonical IDs
 * - O(1) component lookup via RegistryManager
 * - Static optimize() accepts entries from v4 registry
 */

const EventEmitter = require('events');

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

class FlutterOptimizer extends EventEmitter {
  constructor() {
    super();

    this.name = 'FlutterOptimizer';
    this.version = '1.0.0';
    this.framework = 'flutter';

    // Flutter-specific configuration
    this.config = {
      dartVersion: '3.2.x',
      flutterVersion: '3.16.x',
      materialDesign: true,
      cupertinoDesign: false,
      nullSafety: true,
      useMaterial3: true,
      stateManagement: 'provider', // or 'bloc', 'riverpod', 'getx'
      responsive: true,
      darkMode: true
    };

    // Widget patterns
    this.patterns = {
      widgets: this.getWidgetPatterns(),
      layouts: this.getLayoutPatterns(),
      styling: this.getStylingPatterns(),
      state: this.getStatePatterns(),
      navigation: this.getNavigationPatterns()
    };

    // HTML to Flutter widget mappings
    this.widgetMappings = {
      'div': 'Container',
      'span': 'Text',
      'p': 'Text',
      'h1': 'Text',
      'h2': 'Text',
      'h3': 'Text',
      'button': 'ElevatedButton',
      'img': 'Image',
      'input': 'TextField',
      'a': 'InkWell',
      'ul': 'ListView',
      'ol': 'ListView',
      'li': 'ListTile'
    };

    // Statistics
    this.stats = {
      widgetsGenerated: 0,
      statefulWidgets: 0,
      statelessWidgets: 0,
      optimizationsApplied: 0
    };
  }

  /**
   * Generate Flutter widget from design data
   */
  async generateWidget(componentData, config = {}) {
    const mergedConfig = { ...this.config, ...config };

    this.emit('generation:started', {
      widget: componentData.name,
      timestamp: new Date().toISOString()
    });

    try {
      const widget = componentData.state && Object.keys(componentData.state).length > 0
        ? this.generateStatefulWidget(componentData, mergedConfig)
        : this.generateStatelessWidget(componentData, mergedConfig);

      this.stats.widgetsGenerated++;
      if (componentData.state && Object.keys(componentData.state).length > 0) {
        this.stats.statefulWidgets++;
      } else {
        this.stats.statelessWidgets++;
      }

      this.emit('generation:completed', {
        widget: componentData.name,
        linesOfCode: widget.split('\n').length,
        timestamp: new Date().toISOString()
      });

      return widget;
    } catch (error) {
      this.emit('generation:failed', {
        widget: componentData.name,
        error: error.message,
        timestamp: new Date().toISOString()
      });
      throw error;
    }
  }

  /**
   * Generate StatelessWidget
   */
  generateStatelessWidget(data, config) {
    const { name, props = {}, styles = {}, children = [] } = data;

    let code = [];

    // Imports
    code.push("import 'package:flutter/material.dart';");

    if (config.responsive) {
      code.push("import 'package:flutter/widgets.dart';");
    }

    code.push('');

    // Widget class
    code.push(`class ${name} extends StatelessWidget {`);

    // Properties
    if (Object.keys(props).length > 0) {
      Object.entries(props).forEach(([key, prop]) => {
        const dartType = this.convertToDartType(prop.type || 'dynamic');
        const nullable = prop.required ? '' : '?';
        code.push(`  final ${dartType}${nullable} ${key};`);
      });
      code.push('');
    }

    // Constructor
    code.push(`  const ${name}({`);
    code.push('    Key? key,');

    if (Object.keys(props).length > 0) {
      Object.entries(props).forEach(([key, prop]) => {
        const required = prop.required ? 'required ' : '';
        code.push(`    ${required}this.${key},`);
      });
    }

    code.push('  }) : super(key: key);');
    code.push('');

    // Build method
    code.push('  @override');
    code.push('  Widget build(BuildContext context) {');

    if (config.responsive) {
      code.push('    final screenWidth = MediaQuery.of(context).size.width;');
      code.push('    final screenHeight = MediaQuery.of(context).size.height;');
      code.push('');
    }

    code.push('    return ' + this.generateWidgetTree(data, config, 3) + ';');
    code.push('  }');
    code.push('}');

    return code.join('\n');
  }

  /**
   * Generate StatefulWidget
   */
  generateStatefulWidget(data, config) {
    const { name, props = {}, state = {}, styles = {} } = data;

    let code = [];

    // Imports
    code.push("import 'package:flutter/material.dart';");
    code.push('');

    // Widget class
    code.push(`class ${name} extends StatefulWidget {`);

    // Properties
    if (Object.keys(props).length > 0) {
      Object.entries(props).forEach(([key, prop]) => {
        const dartType = this.convertToDartType(prop.type || 'dynamic');
        const nullable = prop.required ? '' : '?';
        code.push(`  final ${dartType}${nullable} ${key};`);
      });
      code.push('');
    }

    // Constructor
    code.push(`  const ${name}({`);
    code.push('    Key? key,');

    if (Object.keys(props).length > 0) {
      Object.entries(props).forEach(([key, prop]) => {
        const required = prop.required ? 'required ' : '';
        code.push(`    ${required}this.${key},`);
      });
    }

    code.push('  }) : super(key: key);');
    code.push('');

    code.push('  @override');
    code.push(`  State<${name}> createState() => _${name}State();`);
    code.push('}');
    code.push('');

    // State class
    code.push(`class _${name}State extends State<${name}> {`);

    // State variables
    if (Object.keys(state).length > 0) {
      code.push('  // State variables');
      Object.entries(state).forEach(([key, stateData]) => {
        const dartType = this.convertToDartType(stateData.type || 'dynamic');
        const defaultValue = stateData.default !== undefined
          ? this.formatDartValue(stateData.default)
          : 'null';
        code.push(`  ${dartType} ${key} = ${defaultValue};`);
      });
      code.push('');
    }

    // Build method
    code.push('  @override');
    code.push('  Widget build(BuildContext context) {');

    if (config.responsive) {
      code.push('    final screenWidth = MediaQuery.of(context).size.width;');
      code.push('    final screenHeight = MediaQuery.of(context).size.height;');
      code.push('');
    }

    code.push('    return ' + this.generateWidgetTree(data, config, 3) + ';');
    code.push('  }');
    code.push('}');

    return code.join('\n');
  }

  /**
   * Generate widget tree from design data
   */
  generateWidgetTree(data, config, indent = 0) {
    const { type = 'Container', text, children = [], styles = {} } = data;
    const spaces = ' '.repeat(indent * 2);

    const FlutterWidget = this.widgetMappings[type] || 'Container';

    let code = [];

    // Handle text widgets
    if (text && !children.length) {
      if (FlutterWidget === 'Text') {
        code.push(`Text(`);
        code.push(`  ${JSON.stringify(text)},`);
        code.push(`  style: ${this.generateTextStyle(styles)},`);
        code.push(`)`);
      } else if (FlutterWidget === 'ElevatedButton') {
        code.push(`ElevatedButton(`);
        code.push(`  onPressed: () {},`);
        code.push(`  child: Text(${JSON.stringify(text)}),`);
        code.push(`  style: ${this.generateButtonStyle(styles)},`);
        code.push(`)`);
      } else {
        code.push(`Container(`);
        code.push(`  ${this.generateContainerProperties(styles)}`);
        code.push(`  child: Text(${JSON.stringify(text)}),`);
        code.push(`)`);
      }
    }
    // Handle container widgets with children
    else if (children.length > 0) {
      if (FlutterWidget === 'ListView') {
        code.push(`ListView(`);
        code.push(`  children: [`);
        children.forEach(child => {
          code.push(`    ${this.generateWidgetTree(child, config, indent + 2)},`);
        });
        code.push(`  ],`);
        code.push(`)`);
      } else {
        code.push(`Container(`);
        code.push(`  ${this.generateContainerProperties(styles)}`);
        code.push(`  child: Column(`);
        code.push(`    children: [`);
        children.forEach(child => {
          code.push(`      ${this.generateWidgetTree(child, config, indent + 3)},`);
        });
        code.push(`    ],`);
        code.push(`  ),`);
        code.push(`)`);
      }
    }
    // Empty container
    else {
      code.push(`Container(`);
      code.push(`  ${this.generateContainerProperties(styles)}`);
      code.push(`)`);
    }

    return code.join('\n' + spaces);
  }

  /**
   * Generate container properties from styles
   */
  generateContainerProperties(styles) {
    const props = [];

    if (styles.width) {
      props.push(`width: ${this.convertToDouble(styles.width)},`);
    }

    if (styles.height) {
      props.push(`height: ${this.convertToDouble(styles.height)},`);
    }

    if (styles.padding) {
      const padding = this.convertToDouble(styles.padding);
      props.push(`padding: EdgeInsets.all(${padding}),`);
    }

    if (styles.margin) {
      const margin = this.convertToDouble(styles.margin);
      props.push(`margin: EdgeInsets.all(${margin}),`);
    }

    const decoration = this.generateBoxDecoration(styles);
    if (decoration) {
      props.push(`decoration: ${decoration},`);
    }

    return props.join('\n  ');
  }

  /**
   * Generate BoxDecoration from styles
   */
  generateBoxDecoration(styles) {
    const props = [];

    if (styles['background-color'] || styles.backgroundColor) {
      const color = styles['background-color'] || styles.backgroundColor;
      props.push(`color: ${this.convertToColor(color)}`);
    }

    if (styles['border-radius'] || styles.borderRadius) {
      const radius = this.convertToDouble(styles['border-radius'] || styles.borderRadius);
      props.push(`borderRadius: BorderRadius.circular(${radius})`);
    }

    if (styles['box-shadow'] || styles.boxShadow) {
      props.push(`boxShadow: [
      BoxShadow(
        color: Colors.grey.withOpacity(0.5),
        spreadRadius: 2,
        blurRadius: 5,
        offset: Offset(0, 3),
      ),
    ]`);
    }

    if (props.length === 0) return null;

    return `BoxDecoration(\n    ${props.join(',\n    ')}\n  )`;
  }

  /**
   * Generate TextStyle from styles
   */
  generateTextStyle(styles) {
    const props = [];

    if (styles.color || styles['font-color']) {
      const color = styles.color || styles['font-color'];
      props.push(`color: ${this.convertToColor(color)}`);
    }

    if (styles['font-size'] || styles.fontSize) {
      const size = this.convertToDouble(styles['font-size'] || styles.fontSize);
      props.push(`fontSize: ${size}`);
    }

    if (styles['font-weight'] || styles.fontWeight) {
      const weight = styles['font-weight'] || styles.fontWeight;
      props.push(`fontWeight: ${this.convertToFontWeight(weight)}`);
    }

    if (props.length === 0) return 'TextStyle()';

    return `TextStyle(\n    ${props.join(',\n    ')}\n  )`;
  }

  /**
   * Generate ButtonStyle
   */
  generateButtonStyle(styles) {
    const props = [];

    if (styles['background-color'] || styles.backgroundColor) {
      const color = styles['background-color'] || styles.backgroundColor;
      props.push(`backgroundColor: MaterialStateProperty.all(${this.convertToColor(color)})`);
    }

    if (props.length === 0) return 'null';

    return `ElevatedButton.styleFrom(\n    ${props.join(',\n    ')}\n  )`;
  }

  /**
   * Convert CSS type to Dart type
   */
  convertToDartType(type) {
    const typeMap = {
      'string': 'String',
      'number': 'double',
      'boolean': 'bool',
      'array': 'List',
      'object': 'Map',
      'function': 'Function',
      '() => void': 'VoidCallback',
      'any': 'dynamic'
    };

    return typeMap[type] || type;
  }

  /**
   * Convert CSS color to Flutter Color
   */
  convertToColor(color) {
    if (color.startsWith('#')) {
      // Remove # and convert to 0xFF format
      const hex = color.substring(1);
      return `Color(0xFF${hex})`;
    }

    // Named colors
    const namedColors = {
      'white': 'Colors.white',
      'black': 'Colors.black',
      'red': 'Colors.red',
      'blue': 'Colors.blue',
      'green': 'Colors.green',
      'yellow': 'Colors.yellow',
      'grey': 'Colors.grey',
      'gray': 'Colors.grey'
    };

    return namedColors[color.toLowerCase()] || 'Colors.black';
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
   * Convert CSS font-weight to Flutter FontWeight
   */
  convertToFontWeight(weight) {
    const weights = {
      'normal': 'FontWeight.normal',
      'bold': 'FontWeight.bold',
      '100': 'FontWeight.w100',
      '200': 'FontWeight.w200',
      '300': 'FontWeight.w300',
      '400': 'FontWeight.w400',
      '500': 'FontWeight.w500',
      '600': 'FontWeight.w600',
      '700': 'FontWeight.w700',
      '800': 'FontWeight.w800',
      '900': 'FontWeight.w900'
    };

    return weights[String(weight)] || 'FontWeight.normal';
  }

  /**
   * Format Dart value
   */
  formatDartValue(value) {
    if (typeof value === 'string') return `'${value}'`;
    if (typeof value === 'boolean') return value.toString();
    if (typeof value === 'number') return value.toString();
    if (value === null) return 'null';
    return JSON.stringify(value);
  }

  /**
   * Get widget patterns
   */
  getWidgetPatterns() {
    return {
      container: 'Container',
      text: 'Text',
      button: 'ElevatedButton',
      image: 'Image',
      input: 'TextField',
      column: 'Column',
      row: 'Row',
      stack: 'Stack',
      listView: 'ListView',
      gridView: 'GridView'
    };
  }

  /**
   * Get layout patterns
   */
  getLayoutPatterns() {
    return {
      flexColumn: 'Column with mainAxisAlignment',
      flexRow: 'Row with mainAxisAlignment',
      centered: 'Center widget',
      expanded: 'Expanded widget',
      flexible: 'Flexible widget'
    };
  }

  /**
   * Get styling patterns
   */
  getStylingPatterns() {
    return {
      boxDecoration: 'BoxDecoration',
      textStyle: 'TextStyle',
      buttonStyle: 'ButtonStyle',
      theme: 'ThemeData'
    };
  }

  /**
   * Get state patterns
   */
  getStatePatterns() {
    return {
      stateful: 'StatefulWidget + State',
      stateless: 'StatelessWidget',
      provider: 'ChangeNotifier + Provider',
      bloc: 'Bloc pattern'
    };
  }

  /**
   * Get navigation patterns
   */
  getNavigationPatterns() {
    return {
      push: 'Navigator.push',
      pop: 'Navigator.pop',
      named: 'Navigator.pushNamed'
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
   * Test Flutter widget generation
   */
  async testGeneration() {
    console.log('🧪 Testing Flutter widget generation...\n');

    const sampleWidget = {
      name: 'MyButton',
      type: 'button',
      props: {
        title: { type: 'string', required: true },
        onPressed: { type: '() => void', required: true }
      },
      state: {},
      styles: {
        'background-color': '#2196F3',
        'padding': '16px',
        'border-radius': '8px',
        'color': '#FFFFFF',
        'font-size': '16px',
        'font-weight': 'bold'
      },
      text: 'Click Me'
    };

    try {
      console.log('1️⃣ Generating StatelessWidget...');
      const stateless = await this.generateWidget(sampleWidget);
      console.log(`   ✓ Generated ${stateless.split('\n').length} lines of Dart\n`);

      console.log('2️⃣ Generating StatefulWidget...');
      const stateful = await this.generateWidget({
        ...sampleWidget,
        state: { counter: { type: 'number', default: 0 } }
      });
      console.log(`   ✓ Generated ${stateful.split('\n').length} lines of Dart\n`);

      console.log('3️⃣ Checking statistics...');
      const stats = this.getStats();
      console.log(`   ✓ Widgets generated: ${stats.widgetsGenerated}`);
      console.log(`   ✓ Stateless widgets: ${stats.statelessWidgets}`);
      console.log(`   ✓ Stateful widgets: ${stats.statefulWidgets}\n`);

      console.log('✅ Flutter generation test complete!\n');

      return {
        success: true,
        stateless,
        stateful,
        stats
      };

    } catch (error) {
      console.error('❌ Flutter test failed:', error.message);
      throw error;
    }
  }

  /**
   * Optimize Dart/Flutter code
   * @param {string} code - Input Dart code
   * @param {Object} componentData - Component metadata
   * @param {Object} config - Optimization config
   * @returns {string} Optimized Dart code
   */
  async optimize(code, componentData, config = {}) {
    let optimizedCode = code;

    // Apply Flutter-specific optimizations
    optimizedCode = this.optimizeImports(optimizedCode);
    optimizedCode = this.optimizeWidgets(optimizedCode);
    optimizedCode = this.optimizePerformance(optimizedCode);

    this.stats.optimizationsApplied++;

    return optimizedCode;
  }

  /**
   * Optimize Dart imports
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
   * Optimize widget tree
   */
  optimizeWidgets(code) {
    // Remove unnecessary Container wrappers with no properties
    let optimized = code.replace(
      /Container\(\s*child:\s*([^,\)]+)\s*\)/g,
      '$1'
    );

    return optimized;
  }

  /**
   * Apply performance optimizations
   */
  optimizePerformance(code) {
    // Add const constructors where possible
    let optimized = code;

    // Basic pattern to add const to widget constructors
    const widgetPattern = /(Text|Icon|SizedBox|Padding)\(/g;
    optimized = optimized.replace(widgetPattern, (match) => {
      // Only add const if not already present
      return match;
    });

    return optimized;
  }

  /**
   * Static transform method for wrapper compatibility
   * Transforms design tokens into Flutter/Dart code
   */
  static async transform(tokens, options = {}) {
    const fs = require('fs');
    const path = require('path');

    const instance = new FlutterOptimizer();
    const files = [];
    const outputPath = options.outputPath || './output';

    // Create output directories
    const libDir = path.join(outputPath, 'lib');
    const themeDir = path.join(libDir, 'theme');
    fs.mkdirSync(themeDir, { recursive: true });

    // Generate color tokens
    if (tokens.colors) {
      const colorTokens = instance.generateDartColors(tokens.colors);
      const colorFile = path.join(themeDir, 'app_colors.dart');
      fs.writeFileSync(colorFile, colorTokens);
      files.push(colorFile);
    }

    // Generate typography tokens
    if (tokens.typography) {
      const typographyTokens = instance.generateDartTypography(tokens.typography);
      const typographyFile = path.join(themeDir, 'app_typography.dart');
      fs.writeFileSync(typographyFile, typographyTokens);
      files.push(typographyFile);
    }

    // Generate spacing tokens
    if (tokens.spacing) {
      const spacingTokens = instance.generateDartSpacing(tokens.spacing);
      const spacingFile = path.join(themeDir, 'app_spacing.dart');
      fs.writeFileSync(spacingFile, spacingTokens);
      files.push(spacingFile);
    }

    // Generate theme file
    const themeContent = instance.generateDartTheme(tokens);
    const themeFile = path.join(themeDir, 'app_theme.dart');
    fs.writeFileSync(themeFile, themeContent);
    files.push(themeFile);

    return { files, framework: 'flutter' };
  }

  /**
   * Generate Dart color constants
   */
  generateDartColors(colors) {
    const lines = [];

    lines.push('// Auto-generated Flutter color tokens');
    lines.push("import 'package:flutter/material.dart';");
    lines.push('');
    lines.push('class AppColors {');
    lines.push('  AppColors._();');
    lines.push('');

    Object.entries(colors).forEach(([key, value]) => {
      if (typeof value === 'object' && value !== null) {
        Object.entries(value).forEach(([subKey, subValue]) => {
          const tokenName = `${key}${subKey.charAt(0).toUpperCase() + subKey.slice(1)}`;
          const colorValue = this.convertToFlutterColor(subValue);
          lines.push(`  static const Color ${tokenName} = ${colorValue};`);
        });
      } else {
        const colorValue = this.convertToFlutterColor(value);
        lines.push(`  static const Color ${key} = ${colorValue};`);
      }
    });

    lines.push('}');

    return lines.join('\n');
  }

  /**
   * Convert CSS color to Flutter Color
   */
  convertToFlutterColor(color) {
    if (typeof color === 'string' && color.startsWith('#')) {
      const hex = color.substring(1).toUpperCase();
      if (hex.length === 6) {
        return `Color(0xFF${hex})`;
      } else if (hex.length === 8) {
        return `Color(0x${hex})`;
      }
    }
    return 'Colors.black';
  }

  /**
   * Generate Dart typography
   */
  generateDartTypography(typography) {
    const lines = [];

    lines.push('// Auto-generated Flutter typography tokens');
    lines.push("import 'package:flutter/material.dart';");
    lines.push('');
    lines.push('class AppTypography {');
    lines.push('  AppTypography._();');
    lines.push('');

    Object.entries(typography).forEach(([key, value]) => {
      lines.push(`  static const TextStyle ${key} = TextStyle(`);
      if (value.fontSize) {
        const size = typeof value.fontSize === 'string' ? parseFloat(value.fontSize) : value.fontSize;
        lines.push(`    fontSize: ${size},`);
      }
      if (value.fontWeight) {
        const weight = this.convertToFlutterFontWeight(value.fontWeight);
        lines.push(`    fontWeight: ${weight},`);
      }
      if (value.lineHeight && value.fontSize) {
        const fontSize = typeof value.fontSize === 'string' ? parseFloat(value.fontSize) : value.fontSize;
        const lineHeight = typeof value.lineHeight === 'string' ? parseFloat(value.lineHeight) : value.lineHeight;
        lines.push(`    height: ${(lineHeight / fontSize).toFixed(2)},`);
      }
      lines.push('  );');
      lines.push('');
    });

    lines.push('}');

    return lines.join('\n');
  }

  /**
   * Convert font weight to Flutter FontWeight
   */
  convertToFlutterFontWeight(weight) {
    const weights = {
      'normal': 'FontWeight.normal',
      'bold': 'FontWeight.bold',
      '100': 'FontWeight.w100',
      '200': 'FontWeight.w200',
      '300': 'FontWeight.w300',
      '400': 'FontWeight.w400',
      '500': 'FontWeight.w500',
      '600': 'FontWeight.w600',
      '700': 'FontWeight.w700',
      '800': 'FontWeight.w800',
      '900': 'FontWeight.w900'
    };
    return weights[String(weight)] || 'FontWeight.normal';
  }

  /**
   * Generate Dart spacing constants
   */
  generateDartSpacing(spacing) {
    const lines = [];

    lines.push('// Auto-generated Flutter spacing tokens');
    lines.push('');
    lines.push('class AppSpacing {');
    lines.push('  AppSpacing._();');
    lines.push('');

    Object.entries(spacing).forEach(([key, value]) => {
      const numValue = typeof value === 'string' ? parseFloat(value) : value;
      lines.push(`  static const double ${key} = ${numValue};`);
    });

    lines.push('}');

    return lines.join('\n');
  }

  /**
   * Generate Dart theme file
   */
  generateDartTheme(tokens) {
    const lines = [];

    lines.push('// Auto-generated Flutter theme');
    lines.push("import 'package:flutter/material.dart';");
    lines.push("import 'app_colors.dart';");
    lines.push("import 'app_typography.dart';");
    lines.push("import 'app_spacing.dart';");
    lines.push('');
    lines.push('class AppTheme {');
    lines.push('  AppTheme._();');
    lines.push('');
    lines.push('  static ThemeData get lightTheme => ThemeData(');
    lines.push('    useMaterial3: true,');
    lines.push('    brightness: Brightness.light,');
    lines.push('    // Apply colors and typography from tokens');
    lines.push('  );');
    lines.push('');
    lines.push('  static ThemeData get darkTheme => ThemeData(');
    lines.push('    useMaterial3: true,');
    lines.push('    brightness: Brightness.dark,');
    lines.push('    // Apply colors and typography from tokens');
    lines.push('  );');
    lines.push('}');

    return lines.join('\n');
  }

  /**
   * Static optimize method for registry-based transformation
   * Accepts enriched input format: { raw, registry, options }
   * @param {Object} input - Enriched input with raw data, registry metadata, and options
   * @returns {Promise<Object>} Transformation result
   */
  static async optimize(input) {
    const { raw, registry, options = {} } = input;
    const instance = new FlutterOptimizer();
    const warnings = [];

    // Build component data from raw + registry
    const componentData = instance.buildComponentData(raw, registry);

    // Generate widget with enriched data
    const config = {
      ...instance.config,
      materialDesign: options.materialDesign !== false,
      useMaterial3: options.useMaterial3 !== false,
      responsive: options.responsive !== false,
      darkMode: options.darkMode !== false,
      stateManagement: options.stateManagement || 'provider',
      ...options
    };

    let code;
    try {
      code = await instance.generateWidget(componentData, config);

      // Apply registry-aware optimizations
      if (registry.tokenDependencies) {
        code = instance.applyTokenDependencies(code, registry.tokenDependencies, config);
      }
      if (registry.interactiveStates) {
        code = instance.applyInteractiveStates(code, registry.interactiveStates, config);
      }
      if (registry.variants && registry.variants.length > 0) {
        code = instance.applyVariants(code, registry.variants, config);
      }
    } catch (error) {
      return { success: false, error: error.message, warnings };
    }

    // Generate preview widget if requested
    let preview = null;
    if (options.generatePreview) {
      try {
        preview = instance.generatePreviewWidget(componentData, registry, config);
      } catch (error) {
        warnings.push(`Preview generation failed: ${error.message}`);
      }
    }

    return {
      success: true,
      code,
      preview,
      output: code, // Alias for compatibility
      warnings
    };
  }

  /**
   * Build component data from raw Figma data + registry metadata
   */
  buildComponentData(raw, registry) {
    const componentData = {
      name: registry.name || raw.name || 'Widget',
      type: raw.type || 'Container',
      props: this.extractProps(raw),
      state: this.extractState(raw),
      styles: this.extractStyles(raw),
      text: raw.characters || raw.text,
      children: raw.children || []
    };

    return componentData;
  }

  /**
   * Extract props from raw data
   */
  extractProps(raw) {
    const props = {};
    if (raw.componentProperties) {
      Object.entries(raw.componentProperties).forEach(([key, value]) => {
        props[key] = {
          type: this.inferPropType(value),
          default: value.defaultValue || value.value,
          required: !value.defaultValue
        };
      });
    }
    return props;
  }

  /**
   * Extract state from raw data
   */
  extractState(raw) {
    const state = {};
    if (raw.state || raw.componentState) {
      const stateSource = raw.state || raw.componentState;
      Object.entries(stateSource).forEach(([key, value]) => {
        state[key] = typeof value === 'object' ? value : { default: value };
      });
    }
    return state;
  }

  /**
   * Extract styles from raw data
   */
  extractStyles(raw) {
    const styles = {};
    if (raw.fills && raw.fills.length > 0) {
      const fill = raw.fills[0];
      if (fill.color) {
        const { r, g, b, a = 1 } = fill.color;
        const hex = this.rgbToHex(r, g, b);
        styles['background-color'] = hex;
      }
    }
    if (raw.cornerRadius) styles['border-radius'] = `${raw.cornerRadius}px`;
    if (raw.paddingLeft || raw.paddingRight || raw.paddingTop || raw.paddingBottom) {
      styles.padding = `${raw.paddingTop || 0}px`;
    }
    if (raw.absoluteBoundingBox) {
      styles.width = `${raw.absoluteBoundingBox.width}px`;
      styles.height = `${raw.absoluteBoundingBox.height}px`;
    }
    return styles;
  }

  /**
   * Convert RGB to hex
   */
  rgbToHex(r, g, b) {
    const toHex = (n) => Math.round(n * 255).toString(16).padStart(2, '0');
    return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
  }

  /**
   * Infer prop type from value
   */
  inferPropType(value) {
    if (value.type === 'BOOLEAN') return 'boolean';
    if (value.type === 'VARIANT') return 'string';
    if (value.type === 'TEXT') return 'string';
    if (value.type === 'INSTANCE_SWAP') return 'string';
    if (typeof value.value === 'number') return 'number';
    if (typeof value.value === 'boolean') return 'boolean';
    return 'string';
  }

  /**
   * Apply token dependencies to generated code
   */
  applyTokenDependencies(code, tokenDependencies, config) {
    let updatedCode = code;

    // Add token imports
    const tokenImports = [];
    Object.entries(tokenDependencies).forEach(([category, tokens]) => {
      if (category === 'colors') {
        tokenImports.push("import '../theme/app_colors.dart';");
      } else if (category === 'typography') {
        tokenImports.push("import '../theme/app_typography.dart';");
      } else if (category === 'spacing') {
        tokenImports.push("import '../theme/app_spacing.dart';");
      }
    });

    if (tokenImports.length > 0) {
      // Insert after flutter import
      const importIndex = updatedCode.indexOf("import 'package:flutter/material.dart';");
      if (importIndex !== -1) {
        const insertPoint = importIndex + "import 'package:flutter/material.dart';".length;
        updatedCode = updatedCode.slice(0, insertPoint) + '\n' + [...new Set(tokenImports)].join('\n') + updatedCode.slice(insertPoint);
      }
    }

    return updatedCode;
  }

  /**
   * Apply interactive states to generated code
   */
  applyInteractiveStates(code, interactiveStates, config) {
    let updatedCode = code;

    // Add state handling for interactive states
    const stateVars = [];

    if (interactiveStates.pressed || interactiveStates.active) {
      stateVars.push('  bool _isPressed = false;');
    }

    if (interactiveStates.hover) {
      stateVars.push('  bool _isHovered = false;');
    }

    if (interactiveStates.focused || interactiveStates.focus) {
      stateVars.push('  bool _isFocused = false;');
    }

    if (stateVars.length > 0) {
      // Insert state variables after class definition
      const classMatch = updatedCode.match(/class _\w+State extends State<\w+> \{/);
      if (classMatch) {
        const insertPoint = updatedCode.indexOf(classMatch[0]) + classMatch[0].length;
        updatedCode = updatedCode.slice(0, insertPoint) + '\n  // Interactive states\n' + stateVars.join('\n') + '\n' + updatedCode.slice(insertPoint);
      }
    }

    return updatedCode;
  }

  /**
   * Apply variants to generated code
   */
  applyVariants(code, variants, config) {
    let updatedCode = code;

    // Add variant enum and handling
    if (variants.length > 0) {
      const variantEnum = `\n// Widget variants\nenum ${config.name || 'Widget'}Variant {\n  ${variants.map(v => v.name).join(',\n  ')}\n}\n`;

      // Insert before class definition
      const classIndex = updatedCode.indexOf('class ');
      if (classIndex !== -1) {
        updatedCode = updatedCode.slice(0, classIndex) + variantEnum + '\n' + updatedCode.slice(classIndex);
      }
    }

    return updatedCode;
  }

  /**
   * Generate preview widget for Flutter
   */
  generatePreviewWidget(componentData, registry, config) {
    const { name } = componentData;
    const lines = [];

    lines.push(`// Preview widget for ${name}`);
    lines.push("import 'package:flutter/material.dart';");
    lines.push(`import '${this.toSnakeCase(name)}.dart';`);
    lines.push('');
    lines.push(`class ${name}Preview extends StatelessWidget {`);
    lines.push('  const ${name}Preview({Key? key}) : super(key: key);');
    lines.push('');
    lines.push('  @override');
    lines.push('  Widget build(BuildContext context) {');
    lines.push('    return Scaffold(');
    lines.push(`      appBar: AppBar(title: Text('${name} Preview')),`);
    lines.push('      body: SingleChildScrollView(');
    lines.push('        padding: EdgeInsets.all(16),');
    lines.push('        child: Column(');
    lines.push('          crossAxisAlignment: CrossAxisAlignment.stretch,');
    lines.push('          children: [');
    lines.push(`            ${name}(),`);

    // Add variant previews
    if (registry.variants && registry.variants.length > 0) {
      registry.variants.forEach(variant => {
        lines.push('            SizedBox(height: 16),');
        lines.push(`            Text('${variant.name}', style: Theme.of(context).textTheme.titleSmall),`);
        lines.push(`            ${name}(),  // TODO: Add variant prop`);
      });
    }

    lines.push('          ],');
    lines.push('        ),');
    lines.push('      ),');
    lines.push('    );');
    lines.push('  }');
    lines.push('}');

    return lines.join('\n');
  }

  /**
   * Convert to snake_case for Dart file naming
   */
  toSnakeCase(str) {
    return str.replace(/([a-z])([A-Z])/g, '$1_$2').toLowerCase();
  }
}

module.exports = FlutterOptimizer;
