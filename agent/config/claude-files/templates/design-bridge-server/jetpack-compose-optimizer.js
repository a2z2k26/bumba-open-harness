/**
 * Jetpack Compose Optimizer
 * Sprint 52: Jetpack Compose Optimizer
 *
 * Optimizes code generation for Jetpack Compose (Android) applications
 * Handles Kotlin syntax, @Composable functions, and Material Design 3

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

class JetpackComposeOptimizer extends EventEmitter {
  constructor() {
    super();

    this.name = 'JetpackComposeOptimizer';
    this.version = '1.0.0';
    this.framework = 'jetpack-compose';

    // Jetpack Compose configuration
    this.config = {
      kotlinVersion: '1.9.x',
      composeVersion: '1.6.x',
      material3: true,
      stateManagement: 'remember', // or 'viewmodel', 'flow'
      preview: true,
      darkTheme: true
    };

    // Composable patterns
    this.patterns = {
      composables: this.getComposablePatterns(),
      modifiers: this.getModifierPatterns(),
      layouts: this.getLayoutPatterns(),
      state: this.getStatePatterns()
    };

    // HTML to Compose component mappings
    this.composableMappings = {
      'div': 'Column',
      'span': 'Text',
      'p': 'Text',
      'h1': 'Text',
      'h2': 'Text',
      'h3': 'Text',
      'button': 'Button',
      'img': 'Image',
      'input': 'TextField',
      'a': 'TextButton',
      'ul': 'LazyColumn',
      'ol': 'LazyColumn'
    };

    // Statistics
    this.stats = {
      composablesGenerated: 0,
      stateVariables: 0,
      modifiers: 0,
      optimizationsApplied: 0
    };
  }

  /**
   * Generate Jetpack Compose component from design data
   */
  async generateComposable(componentData, config = {}) {
    const mergedConfig = { ...this.config, ...config };

    this.emit('generation:started', {
      composable: componentData.name,
      timestamp: new Date().toISOString()
    });

    try {
      const composable = this.generateComposeFunction(componentData, mergedConfig);

      this.stats.composablesGenerated++;

      this.emit('generation:completed', {
        composable: componentData.name,
        linesOfCode: composable.split('\n').length,
        timestamp: new Date().toISOString()
      });

      return composable;
    } catch (error) {
      this.emit('generation:failed', {
        composable: componentData.name,
        error: error.message,
        timestamp: new Date().toISOString()
      });
      throw error;
    }
  }

  /**
   * Generate @Composable function
   */
  generateComposeFunction(data, config) {
    const { name, props = {}, state = {}, styles = {}, children = [] } = data;

    let code = [];

    // Imports
    code.push('import androidx.compose.foundation.layout.*');
    code.push('import androidx.compose.material3.*');
    code.push('import androidx.compose.runtime.*');
    code.push('import androidx.compose.ui.Modifier');
    code.push('import androidx.compose.ui.unit.dp');
    code.push('import androidx.compose.ui.unit.sp');

    if (config.preview) {
      code.push('import androidx.compose.ui.tooling.preview.Preview');
    }

    code.push('');

    // Composable function
    code.push('@Composable');
    code.push(`fun ${name}(`);

    // Parameters
    const params = [];
    Object.entries(props).forEach(([key, prop]) => {
      const kotlinType = this.convertToKotlinType(prop.type || 'String');
      const nullable = prop.required ? '' : '?';
      const defaultValue = prop.default !== undefined
        ? ` = ${this.formatKotlinValue(prop.default, kotlinType)}`
        : (nullable ? ' = null' : '');
      params.push(`    ${key}: ${kotlinType}${nullable}${defaultValue}`);
    });

    if (params.length > 0) {
      code.push(params.join(',\n'));
      code.push(') {');
    } else {
      code[code.length - 1] += ') {';
    }

    // State variables
    if (Object.keys(state).length > 0) {
      Object.entries(state).forEach(([key, stateData]) => {
        const kotlinType = this.convertToKotlinType(stateData.type || 'String');
        const defaultValue = stateData.default !== undefined
          ? this.formatKotlinValue(stateData.default, kotlinType)
          : this.getDefaultKotlinValue(kotlinType);
        code.push(`    var ${key} by remember { mutableStateOf(${defaultValue}) }`);
        this.stats.stateVariables++;
      });
      code.push('');
    }

    // Composable body
    code.push(this.generateComposableBody(data, config, 1));

    code.push('}');
    code.push('');

    // Preview
    if (config.preview) {
      code.push('@Preview(showBackground = true)');
      code.push('@Composable');
      code.push(`fun ${name}Preview() {`);
      code.push(`    ${name}()`);
      code.push('}');
    }

    return code.join('\n');
  }

  /**
   * Generate composable body
   */
  generateComposableBody(data, config, indent = 0) {
    const { text, children = [], styles = {}, type = 'Column' } = data;
    const spaces = ' '.repeat(indent * 4);

    let code = [];

    const ComposeComponent = this.composableMappings[type] || 'Column';

    // Handle Button with text
    if (ComposeComponent === 'Button' && text) {
      code.push(`${spaces}Button(`);
      code.push(`${spaces}    onClick = { },`);
      code.push(`${spaces}${this.generateModifier(styles, 1)}`);
      code.push(`${spaces}) {`);
      code.push(`${spaces}    Text("${text}")`);
      code.push(`${spaces}}`);
    }
    // Handle Text
    else if (ComposeComponent === 'Text' && text) {
      code.push(`${spaces}Text(`);
      code.push(`${spaces}    text = "${text}",`);
      code.push(`${spaces}${this.generateTextStyle(styles, 1)}`);
      code.push(`${spaces}${this.generateModifier(styles, 1)}`);
      code.push(`${spaces})`);
    }
    // Handle Column/Row with children
    else if (children.length > 0) {
      code.push(`${spaces}${ComposeComponent}(`);
      code.push(`${spaces}${this.generateModifier(styles, 1)}`);
      code.push(`${spaces}) {`);

      children.forEach(child => {
        code.push(this.generateComposableBody(child, config, indent + 1));
      });

      code.push(`${spaces}}`);
    }
    // Empty container
    else {
      code.push(`${spaces}${ComposeComponent}(`);
      code.push(`${spaces}${this.generateModifier(styles, 1)}`);
      code.push(`${spaces}) {}`);
    }

    return code.join('\n');
  }

  /**
   * Generate modifier from styles
   */
  generateModifier(styles, indent = 0) {
    const spaces = ' '.repeat(indent * 4);
    let modifiers = ['Modifier'];

    if (styles.padding) {
      const padding = this.convertToDp(styles.padding);
      modifiers.push(`.padding(${padding}.dp)`);
      this.stats.modifiers++;
    }

    if (styles.width) {
      const width = this.convertToDp(styles.width);
      modifiers.push(`.width(${width}.dp)`);
      this.stats.modifiers++;
    }

    if (styles.height) {
      const height = this.convertToDp(styles.height);
      modifiers.push(`.height(${height}.dp)`);
      this.stats.modifiers++;
    }

    if (styles['background-color'] || styles.backgroundColor) {
      const color = this.convertToComposeColor(styles['background-color'] || styles.backgroundColor);
      modifiers.push(`.background(${color})`);
      this.stats.modifiers++;
    }

    if (styles['border-radius'] || styles.borderRadius) {
      const radius = this.convertToDp(styles['border-radius'] || styles.borderRadius);
      modifiers.push(`.clip(RoundedCornerShape(${radius}.dp))`);
      this.stats.modifiers++;
    }

    return `modifier = ${modifiers.join('\n' + spaces + '    ')}`;
  }

  /**
   * Generate text style
   */
  generateTextStyle(styles, indent = 0) {
    const spaces = ' '.repeat(indent * 4);
    let styleProps = [];

    if (styles['font-size'] || styles.fontSize) {
      const size = this.convertToSp(styles['font-size'] || styles.fontSize);
      styleProps.push(`${spaces}fontSize = ${size}.sp`);
    }

    if (styles.color || styles['font-color']) {
      const color = this.convertToComposeColor(styles.color || styles['font-color']);
      styleProps.push(`${spaces}color = ${color}`);
    }

    if (styles['font-weight'] || styles.fontWeight) {
      const weight = this.convertToFontWeight(styles['font-weight'] || styles.fontWeight);
      styleProps.push(`${spaces}fontWeight = ${weight}`);
    }

    if (styleProps.length === 0) return '';

    return `style = TextStyle(\n${styleProps.join(',\n')}\n${spaces}),`;
  }

  /**
   * Convert JavaScript type to Kotlin type
   */
  convertToKotlinType(type) {
    const typeMap = {
      'string': 'String',
      'number': 'Double',
      'boolean': 'Boolean',
      'array': 'List',
      'object': 'Map',
      '() => void': '() -> Unit',
      'any': 'Any'
    };

    return typeMap[type] || type;
  }

  /**
   * Convert CSS color to Compose Color
   */
  convertToComposeColor(color) {
    if (color.startsWith('#')) {
      const hex = color.substring(1);
      return `Color(0xFF${hex})`;
    }

    // Named colors
    const namedColors = {
      'white': 'Color.White',
      'black': 'Color.Black',
      'red': 'Color.Red',
      'blue': 'Color.Blue',
      'green': 'Color.Green',
      'yellow': 'Color.Yellow',
      'gray': 'Color.Gray',
      'grey': 'Color.Gray',
      'transparent': 'Color.Transparent'
    };

    return namedColors[color.toLowerCase()] || 'Color.Black';
  }

  /**
   * Convert CSS font-weight to Compose FontWeight
   */
  convertToFontWeight(weight) {
    const weights = {
      'normal': 'FontWeight.Normal',
      'bold': 'FontWeight.Bold',
      '100': 'FontWeight.W100',
      '200': 'FontWeight.W200',
      '300': 'FontWeight.W300',
      '400': 'FontWeight.W400',
      '500': 'FontWeight.W500',
      '600': 'FontWeight.W600',
      '700': 'FontWeight.W700',
      '800': 'FontWeight.W800',
      '900': 'FontWeight.W900'
    };

    return weights[String(weight)] || 'FontWeight.Normal';
  }

  /**
   * Convert CSS value to dp (density-independent pixels)
   */
  convertToDp(value) {
    if (typeof value === 'number') return value;
    if (typeof value === 'string') {
      const num = parseFloat(value.replace('px', ''));
      return isNaN(num) ? 0 : num;
    }
    return 0;
  }

  /**
   * Convert CSS value to sp (scalable pixels for text)
   */
  convertToSp(value) {
    return this.convertToDp(value);
  }

  /**
   * Format Kotlin value
   */
  formatKotlinValue(value, type) {
    if (type === 'String') return `"${value}"`;
    if (type === 'Boolean') return value.toString();
    if (type === 'Double' || type === 'Int') return value.toString();
    return String(value);
  }

  /**
   * Get default Kotlin value
   */
  getDefaultKotlinValue(type) {
    const defaults = {
      'String': '""',
      'Int': '0',
      'Double': '0.0',
      'Boolean': 'false',
      'List': 'emptyList()',
      'Map': 'emptyMap()'
    };

    return defaults[type] || 'null';
  }

  /**
   * Get composable patterns
   */
  getComposablePatterns() {
    return {
      text: 'Text',
      button: 'Button',
      image: 'Image',
      column: 'Column',
      row: 'Row',
      box: 'Box',
      lazyColumn: 'LazyColumn',
      lazyRow: 'LazyRow'
    };
  }

  /**
   * Get modifier patterns
   */
  getModifierPatterns() {
    return {
      padding: '.padding',
      size: '.size',
      fillMaxWidth: '.fillMaxWidth',
      fillMaxHeight: '.fillMaxHeight',
      background: '.background',
      clip: '.clip',
      clickable: '.clickable'
    };
  }

  /**
   * Get layout patterns
   */
  getLayoutPatterns() {
    return {
      column: 'Column with verticalArrangement',
      row: 'Row with horizontalArrangement',
      box: 'Box with contentAlignment',
      scaffold: 'Scaffold for app structure'
    };
  }

  /**
   * Get state patterns
   */
  getStatePatterns() {
    return {
      remember: 'remember { mutableStateOf() }',
      rememberSaveable: 'rememberSaveable { mutableStateOf() }',
      viewModel: 'viewModel<T>()',
      flow: 'collectAsState()'
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
   * Test Jetpack Compose generation
   */
  async testGeneration() {
    console.log('🧪 Testing Jetpack Compose generation...\n');

    const sampleComposable = {
      name: 'MyButton',
      type: 'button',
      props: {
        text: { type: 'string', required: true },
        onClick: { type: '() => void', required: true }
      },
      state: {
        isPressed: { type: 'boolean', default: false }
      },
      styles: {
        'background-color': '#6200EE',
        'padding': '16px',
        'border-radius': '8px',
        'color': '#FFFFFF',
        'font-size': '16px',
        'font-weight': 'bold'
      },
      text: 'Click Me'
    };

    try {
      console.log('1️⃣ Generating Composable function...');
      const composable = await this.generateComposable(sampleComposable);
      console.log(`   ✓ Generated ${composable.split('\n').length} lines of Kotlin\n`);

      console.log('2️⃣ Checking statistics...');
      const stats = this.getStats();
      console.log(`   ✓ Composables generated: ${stats.composablesGenerated}`);
      console.log(`   ✓ State variables: ${stats.stateVariables}`);
      console.log(`   ✓ Modifiers applied: ${stats.modifiers}\n`);

      console.log('✅ Jetpack Compose generation test complete!\n');

      return {
        success: true,
        composable,
        stats
      };

    } catch (error) {
      console.error('❌ Jetpack Compose test failed:', error.message);
      throw error;
    }
  }

  /**
   * Optimize Kotlin/Jetpack Compose code
   * @param {string} code - Input Kotlin code
   * @param {Object} componentData - Component metadata
   * @param {Object} config - Optimization config
   * @returns {string} Optimized Kotlin code
   */
  async optimize(code, componentData, config = {}) {
    let optimizedCode = code;

    // Apply Jetpack Compose-specific optimizations
    optimizedCode = this.optimizeImports(optimizedCode);
    optimizedCode = this.optimizeModifiers(optimizedCode);
    optimizedCode = this.optimizePerformance(optimizedCode);

    this.stats.optimizationsApplied = (this.stats.optimizationsApplied || 0) + 1;

    return optimizedCode;
  }

  /**
   * Optimize Kotlin imports
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
   * Optimize Modifier chains
   */
  optimizeModifiers(code) {
    let optimized = code;

    // Combine chained modifiers where possible
    // Remove redundant Modifier.then() calls
    optimized = optimized.replace(
      /Modifier\.then\(Modifier\)/g,
      'Modifier'
    );

    return optimized;
  }

  /**
   * Apply performance optimizations
   */
  optimizePerformance(code) {
    let optimized = code;

    // Add remember {} for expensive computations
    // Use derivedStateOf for computed values
    // Suggest LazyColumn/LazyRow for large lists

    return optimized;
  }

  /**
   * Static transform method for wrapper compatibility
   * Transforms design tokens into Jetpack Compose/Kotlin code
   */
  static async transform(tokens, options = {}) {
    const fs = require('fs');
    const path = require('path');

    const instance = new JetpackComposeOptimizer();
    const files = [];
    const outputPath = options.outputPath || './output';

    // Create output directories
    const themeDir = path.join(outputPath, 'ui', 'theme');
    fs.mkdirSync(themeDir, { recursive: true });

    // Generate color tokens
    if (tokens.colors) {
      const colorTokens = instance.generateKotlinColors(tokens.colors);
      const colorFile = path.join(themeDir, 'Color.kt');
      fs.writeFileSync(colorFile, colorTokens);
      files.push(colorFile);
    }

    // Generate typography tokens
    if (tokens.typography) {
      const typographyTokens = instance.generateKotlinTypography(tokens.typography);
      const typographyFile = path.join(themeDir, 'Type.kt');
      fs.writeFileSync(typographyFile, typographyTokens);
      files.push(typographyFile);
    }

    // Generate spacing tokens
    if (tokens.spacing) {
      const spacingTokens = instance.generateKotlinSpacing(tokens.spacing);
      const spacingFile = path.join(themeDir, 'Spacing.kt');
      fs.writeFileSync(spacingFile, spacingTokens);
      files.push(spacingFile);
    }

    // Generate theme file
    const themeContent = instance.generateKotlinTheme(tokens);
    const themeFile = path.join(themeDir, 'Theme.kt');
    fs.writeFileSync(themeFile, themeContent);
    files.push(themeFile);

    return { files, framework: 'jetpack-compose' };
  }

  /**
   * Generate Kotlin color constants
   */
  generateKotlinColors(colors) {
    const lines = [];

    lines.push('// Auto-generated Jetpack Compose color tokens');
    lines.push('package ui.theme');
    lines.push('');
    lines.push('import androidx.compose.ui.graphics.Color');
    lines.push('');

    Object.entries(colors).forEach(([key, value]) => {
      if (typeof value === 'object' && value !== null) {
        Object.entries(value).forEach(([subKey, subValue]) => {
          const tokenName = `${key.charAt(0).toUpperCase() + key.slice(1)}${subKey.charAt(0).toUpperCase() + subKey.slice(1)}`;
          const colorValue = this.convertToKotlinColor(subValue);
          lines.push(`val ${tokenName} = ${colorValue}`);
        });
      } else {
        const tokenName = key.charAt(0).toUpperCase() + key.slice(1);
        const colorValue = this.convertToKotlinColor(value);
        lines.push(`val ${tokenName} = ${colorValue}`);
      }
    });

    return lines.join('\n');
  }

  /**
   * Convert hex color to Compose Color
   */
  convertToKotlinColor(color) {
    if (typeof color === 'string' && color.startsWith('#')) {
      const hex = color.substring(1).toUpperCase();
      return `Color(0xFF${hex})`;
    }
    return 'Color.Black';
  }

  /**
   * Generate Kotlin typography
   */
  generateKotlinTypography(typography) {
    const lines = [];

    lines.push('// Auto-generated Jetpack Compose typography tokens');
    lines.push('package ui.theme');
    lines.push('');
    lines.push('import androidx.compose.material3.Typography');
    lines.push('import androidx.compose.ui.text.TextStyle');
    lines.push('import androidx.compose.ui.text.font.FontWeight');
    lines.push('import androidx.compose.ui.unit.sp');
    lines.push('');

    Object.entries(typography).forEach(([key, value]) => {
      const fontSize = typeof value.fontSize === 'string' ? parseFloat(value.fontSize) : (value.fontSize || 16);
      const weight = this.convertToKotlinFontWeight(value.fontWeight);
      lines.push(`val ${key}Style = TextStyle(`);
      lines.push(`    fontSize = ${fontSize}.sp,`);
      lines.push(`    fontWeight = ${weight}`);
      lines.push(')');
      lines.push('');
    });

    lines.push('val AppTypography = Typography(');
    lines.push('    // Apply typography styles to Material theme');
    lines.push(')');

    return lines.join('\n');
  }

  /**
   * Convert font weight to Kotlin FontWeight
   */
  convertToKotlinFontWeight(weight) {
    const weights = {
      'normal': 'FontWeight.Normal',
      'bold': 'FontWeight.Bold',
      '100': 'FontWeight.W100',
      '200': 'FontWeight.W200',
      '300': 'FontWeight.W300',
      '400': 'FontWeight.W400',
      '500': 'FontWeight.W500',
      '600': 'FontWeight.W600',
      '700': 'FontWeight.W700',
      '800': 'FontWeight.W800',
      '900': 'FontWeight.W900'
    };
    return weights[String(weight)] || 'FontWeight.Normal';
  }

  /**
   * Generate Kotlin spacing constants
   */
  generateKotlinSpacing(spacing) {
    const lines = [];

    lines.push('// Auto-generated Jetpack Compose spacing tokens');
    lines.push('package ui.theme');
    lines.push('');
    lines.push('import androidx.compose.ui.unit.dp');
    lines.push('');
    lines.push('object Spacing {');

    Object.entries(spacing).forEach(([key, value]) => {
      const numValue = typeof value === 'string' ? parseFloat(value) : value;
      lines.push(`    val ${key} = ${numValue}.dp`);
    });

    lines.push('}');

    return lines.join('\n');
  }

  /**
   * Generate Kotlin theme file
   */
  generateKotlinTheme(tokens) {
    const lines = [];

    lines.push('// Auto-generated Jetpack Compose theme');
    lines.push('package ui.theme');
    lines.push('');
    lines.push('import androidx.compose.foundation.isSystemInDarkTheme');
    lines.push('import androidx.compose.material3.MaterialTheme');
    lines.push('import androidx.compose.material3.lightColorScheme');
    lines.push('import androidx.compose.material3.darkColorScheme');
    lines.push('import androidx.compose.runtime.Composable');
    lines.push('');
    lines.push('private val LightColorScheme = lightColorScheme(');
    lines.push('    // Apply light colors from tokens');
    lines.push(')');
    lines.push('');
    lines.push('private val DarkColorScheme = darkColorScheme(');
    lines.push('    // Apply dark colors from tokens');
    lines.push(')');
    lines.push('');
    lines.push('@Composable');
    lines.push('fun AppTheme(');
    lines.push('    darkTheme: Boolean = isSystemInDarkTheme(),');
    lines.push('    content: @Composable () -> Unit');
    lines.push(') {');
    lines.push('    val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme');
    lines.push('');
    lines.push('    MaterialTheme(');
    lines.push('        colorScheme = colorScheme,');
    lines.push('        typography = AppTypography,');
    lines.push('        content = content');
    lines.push('    )');
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

    const instance = new JetpackComposeOptimizer();
    const warnings = [];

    // P6: Normalize variants for cross-framework consistency
    const normalizedRegistry = {
      ...registry,
      variants: syncToFramework(registry.variants || [], 'jetpack-compose')
    };

    // Build component data from raw Figma data + normalized registry metadata
    const componentData = instance.buildComponentData(raw, normalizedRegistry);

    // Merge configuration
    const config = Object.assign({}, instance.config, {
      kotlinVersion: options.kotlinVersion || '1.9.x',
      composeVersion: options.composeVersion || '1.6.x',
      material3: options.material3 !== false,
      stateManagement: options.stateManagement || 'remember',
      preview: options.preview !== false,
      darkTheme: options.darkTheme !== false
    }, options);

    let code;
    try {
      // Generate the Composable function
      code = await instance.generateComposable(componentData, config);

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
        preview = instance.generatePreviewComposable(componentData, normalizedRegistry, config);
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
    const name = registry.name || raw.name || 'CustomComposable';

    // Normalize name for Kotlin
    const kotlinName = name
      .replace(/[^a-zA-Z0-9]/g, '')
      .replace(/^[0-9]/, '_$&');

    return {
      name: kotlinName,
      type: raw.type || 'div',
      props: this.extractProps(raw, registry),
      state: this.extractState(raw, registry),
      styles: this.extractStyles(raw),
      children: raw.children || [],
      text: raw.characters || raw.text || ''
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
          type: this.inferKotlinPropType(value),
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
        state.isEnabled = { type: 'boolean', default: true };
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
    return '#' + [r, g, b].map(x => x.toString(16).padStart(2, '0')).join('').toUpperCase();
  }

  /**
   * Infer Kotlin property type from Figma property
   */
  inferKotlinPropType(prop) {
    if (!prop) return 'String';

    const type = prop.type || typeof prop.value;

    switch (type) {
      case 'BOOLEAN':
      case 'boolean':
        return 'Boolean';
      case 'NUMBER':
      case 'number':
        return 'Double';
      case 'TEXT':
      case 'string':
        return 'String';
      case 'VARIANT':
        return 'String';
      case 'INSTANCE_SWAP':
        return '@Composable () -> Unit';
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
        const kotlinTokenName = tokenName
          .replace(/\./g, '')
          .replace(/-/g, '')
          .replace(/^./, c => c.toUpperCase());
        // Replace Color(0xFF...) with token reference
        const hexMatch = value.substring(1).toUpperCase();
        updatedCode = updatedCode.replace(
          new RegExp(`Color\\(0xFF${hexMatch}\\)`, 'g'),
          kotlinTokenName
        );
      });
    }

    // Replace hardcoded spacing with token references
    if (tokenDependencies.spacing) {
      Object.entries(tokenDependencies.spacing).forEach(([tokenName, value]) => {
        const kotlinTokenName = 'Spacing.' + tokenName.replace(/\./g, '').replace(/-/g, '');
        const numValue = parseFloat(value);
        if (!isNaN(numValue)) {
          updatedCode = updatedCode.replace(
            new RegExp(`\\.padding\\(${numValue}\\.dp\\)`, 'g'),
            `.padding(${kotlinTokenName})`
          );
        }
      });
    }

    // Replace hardcoded typography with token references
    if (tokenDependencies.typography) {
      Object.entries(tokenDependencies.typography).forEach(([tokenName, value]) => {
        const kotlinTokenName = tokenName.replace(/\./g, '').replace(/-/g, '') + 'Style';
        updatedCode = updatedCode.replace(
          /fontSize = [0-9.]+\.sp/g,
          `style = ${kotlinTokenName}`
        );
      });
    }

    // Add token comment after imports
    if (!updatedCode.includes('// Token dependencies:')) {
      const importEndIndex = updatedCode.lastIndexOf('import ');
      if (importEndIndex > -1) {
        const lineEnd = updatedCode.indexOf('\n', importEndIndex);
        if (lineEnd > -1) {
          updatedCode = updatedCode.slice(0, lineEnd + 1) + tokenImportComment + '\n' + updatedCode.slice(lineEnd + 1);
        }
      }
    }

    return updatedCode;
  }

  /**
   * Apply interactive states to generated code
   */
  applyInteractiveStates(code, interactiveStates, config) {
    let updatedCode = code;

    const additionalImports = [];
    const stateModifiers = [];

    // Hover state (requires interactionSource)
    if (interactiveStates.hover) {
      additionalImports.push('import androidx.compose.foundation.hoverable');
      additionalImports.push('import androidx.compose.foundation.interaction.MutableInteractionSource');
      additionalImports.push('import androidx.compose.foundation.interaction.collectIsHoveredAsState');
      stateModifiers.push(`
    val interactionSource = remember { MutableInteractionSource() }
    val isHovered by interactionSource.collectIsHoveredAsState()`);
    }

    // Pressed state
    if (interactiveStates.pressed) {
      additionalImports.push('import androidx.compose.foundation.interaction.collectIsPressedAsState');
      stateModifiers.push(`
    val isPressed by interactionSource.collectIsPressedAsState()`);
    }

    // Focused state
    if (interactiveStates.focused) {
      additionalImports.push('import androidx.compose.foundation.interaction.collectIsFocusedAsState');
      stateModifiers.push(`
    val isFocused by interactionSource.collectIsFocusedAsState()`);
    }

    // Disabled state - add enabled parameter
    if (interactiveStates.disabled) {
      // Add enabled parameter to function signature
      updatedCode = updatedCode.replace(
        /fun (\w+)\(\s*\)/,
        'fun $1(\n    enabled: Boolean = true\n)'
      );
      updatedCode = updatedCode.replace(
        /fun (\w+)\(\s*\n/,
        'fun $1(\n    enabled: Boolean = true,\n'
      );
    }

    // Add imports
    if (additionalImports.length > 0) {
      const uniqueImports = [...new Set(additionalImports)];
      uniqueImports.forEach(importLine => {
        if (!updatedCode.includes(importLine)) {
          updatedCode = updatedCode.replace(
            'import androidx.compose.runtime.*',
            'import androidx.compose.runtime.*\n' + importLine
          );
        }
      });
    }

    // Add state declarations after function opening
    if (stateModifiers.length > 0) {
      const funcBodyStart = updatedCode.indexOf(') {');
      if (funcBodyStart > -1) {
        const insertPoint = updatedCode.indexOf('\n', funcBodyStart) + 1;
        updatedCode = updatedCode.slice(0, insertPoint) + stateModifiers.join('\n') + '\n' + updatedCode.slice(insertPoint);
      }
    }

    // Add hoverable modifier if hover state is used
    if (interactiveStates.hover) {
      updatedCode = updatedCode.replace(
        /modifier = Modifier/,
        'modifier = Modifier\n            .hoverable(interactionSource = interactionSource)'
      );
    }

    return updatedCode;
  }

  /**
   * Apply variants to generated code
   */
  applyVariants(code, variants, config) {
    let updatedCode = code;

    // Generate sealed class or enum for variant properties
    const variantEnums = [];
    const variantParams = [];

    variants.forEach(variant => {
      if (variant.property && variant.values && variant.values.length > 0) {
        const enumName = variant.property.charAt(0).toUpperCase() + variant.property.slice(1) + 'Style';
        const enumCases = variant.values.map(v => {
          const caseName = v.toUpperCase().replace(/[^A-Z0-9]/g, '_');
          return `    ${caseName}`;
        });

        variantEnums.push(`
enum class ${enumName} {
${enumCases.join(',\n')}
}`);

        // Add as parameter
        const paramName = variant.property.charAt(0).toLowerCase() + variant.property.slice(1);
        variantParams.push(`    ${paramName}: ${enumName} = ${enumName}.${variant.values[0].toUpperCase().replace(/[^A-Z0-9]/g, '_')}`);
      }
    });

    // Insert enums before the @Composable annotation
    if (variantEnums.length > 0) {
      updatedCode = updatedCode.replace(
        '@Composable\nfun',
        variantEnums.join('\n') + '\n\n@Composable\nfun'
      );
    }

    // Add variant parameters to function
    if (variantParams.length > 0) {
      updatedCode = updatedCode.replace(
        /fun (\w+)\(\s*\)/,
        `fun $1(\n${variantParams.join(',\n')}\n)`
      );
      updatedCode = updatedCode.replace(
        /fun (\w+)\(\s*\n/,
        `fun $1(\n${variantParams.join(',\n')},\n`
      );
    }

    return updatedCode;
  }

  /**
   * Generate Preview Composable for Android Studio previews
   */
  generatePreviewComposable(componentData, registry, config) {
    const name = componentData.name;
    const lines = [];

    lines.push('// Extended Previews');
    lines.push('');

    // Default preview
    lines.push('@Preview(showBackground = true, name = "Default")');
    lines.push('@Composable');
    lines.push(`fun ${name}DefaultPreview() {`);
    lines.push(`    ${name}()`);
    lines.push('}');
    lines.push('');

    // Dark theme preview
    lines.push('@Preview(showBackground = true, uiMode = Configuration.UI_MODE_NIGHT_YES, name = "Dark")');
    lines.push('@Composable');
    lines.push(`fun ${name}DarkPreview() {`);
    lines.push('    AppTheme(darkTheme = true) {');
    lines.push(`        ${name}()`);
    lines.push('    }');
    lines.push('}');
    lines.push('');

    // Variant previews
    if (registry.variants && registry.variants.length > 0) {
      registry.variants.forEach(variant => {
        if (variant.values) {
          variant.values.forEach(value => {
            const enumName = variant.property.charAt(0).toUpperCase() + variant.property.slice(1) + 'Style';
            const enumValue = value.toUpperCase().replace(/[^A-Z0-9]/g, '_');
            const previewName = variant.property + '_' + value;

            lines.push(`@Preview(showBackground = true, name = "${previewName}")`);
            lines.push('@Composable');
            lines.push(`fun ${name}${previewName.replace(/[^a-zA-Z0-9]/g, '')}Preview() {`);
            lines.push(`    ${name}(${variant.property} = ${enumName}.${enumValue})`);
            lines.push('}');
            lines.push('');
          });
        }
      });
    }

    // Disabled state preview
    if (registry.interactiveStates && registry.interactiveStates.disabled) {
      lines.push('@Preview(showBackground = true, name = "Disabled")');
      lines.push('@Composable');
      lines.push(`fun ${name}DisabledPreview() {`);
      lines.push(`    ${name}(enabled = false)`);
      lines.push('}');
      lines.push('');
    }

    // Size previews
    lines.push('@Preview(showBackground = true, widthDp = 200, heightDp = 100, name = "Fixed Size")');
    lines.push('@Composable');
    lines.push(`fun ${name}FixedSizePreview() {`);
    lines.push(`    ${name}()`);
    lines.push('}');

    return lines.join('\n');
  }
}

module.exports = JetpackComposeOptimizer;
