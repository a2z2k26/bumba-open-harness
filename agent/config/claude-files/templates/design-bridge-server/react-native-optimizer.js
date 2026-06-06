/**
 * React Native Optimizer
 * Sprint 46: React Native Optimizer Setup
 *
 * Optimizes code generation for React Native mobile applications
 * Handles StyleSheet API, platform-specific code, and native components

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

class ReactNativeOptimizer extends EventEmitter {
  constructor() {
    super();

    this.name = 'ReactNativeOptimizer';
    this.version = '1.0.0';
    this.framework = 'react-native';

    // React Native-specific configuration
    this.config = {
      version: '0.73.x',
      useHooks: true,
      useTypeScript: true,
      platformSpecific: true,
      useStyleSheet: true,
      useNativeComponents: true,
      safeAreaInsets: true,
      navigationLibrary: 'react-navigation',
      stateManagement: 'context', // or 'redux', 'mobx'
      animations: 'reanimated', // or 'animated'
      touchFeedback: true, // Add visual feedback for touches
      gestureHandling: true // Add gesture recognizers
    };

    // React Native patterns
    this.patterns = {
      components: this.getNativeComponentPatterns(),
      styling: this.getStylePatterns(),
      platform: this.getPlatformPatterns(),
      performance: this.getPerformancePatterns(),
      navigation: this.getNavigationPatterns()
    };

    // Native component mappings
    this.componentMappings = {
      'div': 'View',
      'span': 'Text',
      'p': 'Text',
      'h1': 'Text',
      'h2': 'Text',
      'h3': 'Text',
      'button': 'TouchableOpacity',
      'img': 'Image',
      'input': 'TextInput',
      'a': 'TouchableOpacity',
      'ul': 'FlatList',
      'ol': 'FlatList',
      'li': 'View'
    };

    // Statistics
    this.stats = {
      componentsGenerated: 0,
      optimizationsApplied: 0,
      platformSpecificCode: 0,
      styleSheets: 0
    };
  }

  /**
   * Generate React Native component from design data
   */
  async generateComponent(componentData, config = {}) {
    const mergedConfig = { ...this.config, ...config };

    this.emit('generation:started', {
      component: componentData.name,
      timestamp: new Date().toISOString()
    });

    try {
      const component = mergedConfig.useTypeScript
        ? this.generateTypeScriptComponent(componentData, mergedConfig)
        : this.generateJavaScriptComponent(componentData, mergedConfig);

      this.stats.componentsGenerated++;

      this.emit('generation:completed', {
        component: componentData.name,
        linesOfCode: component.split('\n').length,
        timestamp: new Date().toISOString()
      });

      return component;
    } catch (error) {
      this.emit('generation:failed', {
        component: componentData.name,
        error: error.message,
        timestamp: new Date().toISOString()
      });
      throw error;
    }
  }

  /**
   * Generate TypeScript React Native component
   */
  generateTypeScriptComponent(data, config) {
    const { name, props = {}, state = {}, styles = {}, children = [] } = data;

    let code = [];

    // Imports
    code.push("import React, { useState, useEffect, useMemo, useCallback } from 'react';");
    code.push("import {");
    code.push("  View,");
    code.push("  Text,");
    code.push("  StyleSheet,");
    code.push("  TouchableOpacity,");
    code.push("  Platform,");
    code.push("  Dimensions,");
    code.push("} from 'react-native';");

    if (config.safeAreaInsets) {
      code.push("import { SafeAreaView } from 'react-native-safe-area-context';");
    }

    if (config.animations === 'reanimated') {
      code.push("import Animated, { useAnimatedStyle, useSharedValue, withSpring, withTiming } from 'react-native-reanimated';");
    }

    if (config.gestureHandling) {
      code.push("import { GestureHandlerRootView } from 'react-native-gesture-handler';");
    }

    code.push('');

    // Type definitions
    code.push(this.generateTypeDefinitions(data));
    code.push('');

    // Component
    code.push(`const ${name}: React.FC<${name}Props> = ({`);

    // Props with defaults
    const propsList = Object.entries(props).map(([key, prop]) => {
      return prop.default ? `  ${key} = ${JSON.stringify(prop.default)}` : `  ${key}`;
    });

    if (propsList.length > 0) {
      code.push(propsList.join(',\n'));
    }

    code.push('}) => {');

    // State hooks
    if (Object.keys(state).length > 0) {
      code.push('  // State');
      Object.entries(state).forEach(([key, stateData]) => {
        const defaultValue = stateData.default !== undefined
          ? JSON.stringify(stateData.default)
          : 'null';
        code.push(`  const [${key}, set${this.capitalize(key)}] = useState<${stateData.type || 'any'}>(${defaultValue});`);
      });
      code.push('');
    }

    // Dimensions hook for responsive design
    if (config.platformSpecific) {
      code.push('  // Screen dimensions');
      code.push('  const { width: screenWidth, height: screenHeight } = Dimensions.get("window");');
      code.push('');
    }

    // Animation values
    if (config.animations === 'reanimated') {
      code.push('  // Animation values');
      code.push('  const scale = useSharedValue(1);');
      code.push('  const opacity = useSharedValue(1);');
      code.push('');
      code.push('  // Animated styles');
      code.push('  const animatedStyle = useAnimatedStyle(() => ({');
      code.push('    transform: [{ scale: scale.value }],');
      code.push('    opacity: opacity.value,');
      code.push('  }));');
      code.push('');
    }

    // Touch handlers
    if (config.touchFeedback) {
      code.push('  // Touch handlers');
      code.push('  const handlePressIn = useCallback(() => {');
      if (config.animations === 'reanimated') {
        code.push('    scale.value = withSpring(0.95);');
        code.push('    opacity.value = withTiming(0.8, { duration: 150 });');
      }
      code.push('  }, []);');
      code.push('');
      code.push('  const handlePressOut = useCallback(() => {');
      if (config.animations === 'reanimated') {
        code.push('    scale.value = withSpring(1);');
        code.push('    opacity.value = withTiming(1, { duration: 150 });');
      }
      code.push('  }, []);');
      code.push('');
    }

    // Render
    code.push('  return (');

    const RootComponent = config.safeAreaInsets ? 'SafeAreaView' : 'View';
    code.push(`    <${RootComponent} style={styles.container}>`);

    // Generate component tree
    code.push(this.generateComponentTree(data, config, 3));

    code.push(`    </${RootComponent}>`);
    code.push('  );');
    code.push('};');
    code.push('');

    // StyleSheet
    code.push(this.generateStyleSheet(data, config));
    code.push('');

    // Export
    code.push(`export default ${name};`);

    return code.join('\n');
  }

  /**
   * Generate JavaScript React Native component
   */
  generateJavaScriptComponent(data, config) {
    const { name, props = {}, state = {}, styles = {} } = data;

    let code = [];

    // Imports
    code.push("import React, { useState, useEffect, useMemo, useCallback } from 'react';");
    code.push("import {");
    code.push("  View,");
    code.push("  Text,");
    code.push("  StyleSheet,");
    code.push("  TouchableOpacity,");
    code.push("  Platform,");
    code.push("  Dimensions,");
    code.push("} from 'react-native';");
    code.push('');

    // Component
    code.push(`const ${name} = ({`);

    const propsList = Object.entries(props).map(([key, prop]) => {
      return prop.default ? `  ${key} = ${JSON.stringify(prop.default)}` : `  ${key}`;
    });

    if (propsList.length > 0) {
      code.push(propsList.join(',\n'));
    }

    code.push('}) => {');

    // State
    if (Object.keys(state).length > 0) {
      code.push('  // State');
      Object.entries(state).forEach(([key, stateData]) => {
        const defaultValue = stateData.default !== undefined
          ? JSON.stringify(stateData.default)
          : 'null';
        code.push(`  const [${key}, set${this.capitalize(key)}] = useState(${defaultValue});`);
      });
      code.push('');
    }

    // Render
    code.push('  return (');
    code.push('    <View style={styles.container}>');
    code.push(this.generateComponentTree(data, config, 3));
    code.push('    </View>');
    code.push('  );');
    code.push('};');
    code.push('');

    // StyleSheet
    code.push(this.generateStyleSheet(data, config));
    code.push('');

    // Export
    code.push(`export default ${name};`);

    return code.join('\n');
  }

  /**
   * Generate TypeScript type definitions
   */
  generateTypeDefinitions(data) {
    const { name, props = {} } = data;

    let code = [];

    code.push(`interface ${name}Props {`);

    Object.entries(props).forEach(([key, prop]) => {
      const optional = prop.required ? '' : '?';
      const type = prop.type || 'any';
      code.push(`  ${key}${optional}: ${type};`);
    });

    code.push('}');

    return code.join('\n');
  }

  /**
   * Generate component tree from design data
   */
  generateComponentTree(data, config, indent = 0) {
    const { children = [], text, type = 'View' } = data;
    const spaces = ' '.repeat(indent * 2);

    let code = [];

    if (text) {
      code.push(`${spaces}<Text style={styles.text}>`);
      code.push(`${spaces}  {${JSON.stringify(text)}}`);
      code.push(`${spaces}</Text>`);
    }

    children.forEach((child, index) => {
      const NativeComponent = this.componentMappings[child.type] || 'View';

      if (child.text) {
        code.push(`${spaces}<Text style={styles.text${index}}>`);
        code.push(`${spaces}  {${JSON.stringify(child.text)}}`);
        code.push(`${spaces}</Text>`);
      } else if (child.children && child.children.length > 0) {
        code.push(`${spaces}<${NativeComponent} style={styles.child${index}}>`);
        code.push(this.generateComponentTree(child, config, indent + 1));
        code.push(`${spaces}</${NativeComponent}>`);
      } else {
        code.push(`${spaces}<${NativeComponent} style={styles.child${index}} />`);
      }
    });

    return code.join('\n');
  }

  /**
   * Generate React Native StyleSheet
   */
  generateStyleSheet(data, config) {
    const { name, styles = {}, children = [] } = data;

    let code = [];

    code.push('const styles = StyleSheet.create({');
    code.push('  container: {');

    // Convert web CSS to React Native styles
    const containerStyles = this.convertStylesToRN(styles.container || {});
    Object.entries(containerStyles).forEach(([key, value]) => {
      code.push(`    ${key}: ${JSON.stringify(value)},`);
    });

    code.push('  },');

    // Text styles
    if (styles.text || data.text) {
      code.push('  text: {');
      const textStyles = this.convertStylesToRN(styles.text || {});
      Object.entries(textStyles).forEach(([key, value]) => {
        code.push(`    ${key}: ${JSON.stringify(value)},`);
      });
      code.push('  },');
    }

    // Child styles
    children.forEach((child, index) => {
      code.push(`  child${index}: {`);
      const childStyles = this.convertStylesToRN(child.styles || {});
      Object.entries(childStyles).forEach(([key, value]) => {
        code.push(`    ${key}: ${JSON.stringify(value)},`);
      });
      code.push('  },');
    });

    code.push('});');

    this.stats.styleSheets++;

    return code.join('\n');
  }

  /**
   * Convert web CSS styles to React Native StyleSheet format
   */
  convertStylesToRN(webStyles) {
    const rnStyles = {};

    Object.entries(webStyles).forEach(([key, value]) => {
      // Convert kebab-case to camelCase
      const rnKey = key.replace(/-([a-z])/g, (g) => g[1].toUpperCase());

      // Convert specific values
      if (typeof value === 'string') {
        // Remove 'px' suffix
        if (value.endsWith('px')) {
          rnStyles[rnKey] = parseInt(value.replace('px', ''));
        }
        // Keep other values as is
        else {
          rnStyles[rnKey] = value;
        }
      } else {
        rnStyles[rnKey] = value;
      }
    });

    return rnStyles;
  }

  /**
   * Add platform-specific code
   */
  addPlatformSpecificCode(code, ios, android) {
    this.stats.platformSpecificCode++;

    return `Platform.select({
  ios: ${ios},
  android: ${android},
})`;
  }

  /**
   * Get native component patterns
   */
  getNativeComponentPatterns() {
    return {
      view: { component: 'View', description: 'Container component' },
      text: { component: 'Text', description: 'Text display' },
      button: { component: 'TouchableOpacity', description: 'Pressable button' },
      image: { component: 'Image', description: 'Image display' },
      input: { component: 'TextInput', description: 'Text input field' },
      scroll: { component: 'ScrollView', description: 'Scrollable container' },
      list: { component: 'FlatList', description: 'Optimized list' },
      safeArea: { component: 'SafeAreaView', description: 'Safe area container' }
    };
  }

  /**
   * Get style patterns
   */
  getStylePatterns() {
    return {
      flexbox: {
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'flex-start',
        alignItems: 'stretch'
      },
      shadow: {
        ios: {
          shadowColor: '#000',
          shadowOffset: { width: 0, height: 2 },
          shadowOpacity: 0.25,
          shadowRadius: 3.84
        },
        android: {
          elevation: 5
        }
      }
    };
  }

  /**
   * Get platform-specific patterns
   */
  getPlatformPatterns() {
    return {
      statusBar: {
        ios: 44,
        android: 0
      },
      shadow: {
        ios: 'shadowColor, shadowOffset, shadowOpacity, shadowRadius',
        android: 'elevation'
      },
      fonts: {
        ios: 'System',
        android: 'Roboto'
      }
    };
  }

  /**
   * Get performance patterns
   */
  getPerformancePatterns() {
    return {
      flatList: {
        initialNumToRender: 10,
        maxToRenderPerBatch: 10,
        windowSize: 5,
        removeClippedSubviews: true
      },
      image: {
        resizeMode: 'cover',
        cache: 'force-cache'
      }
    };
  }

  /**
   * Get navigation patterns
   */
  getNavigationPatterns() {
    return {
      stack: 'createStackNavigator',
      tab: 'createBottomTabNavigator',
      drawer: 'createDrawerNavigator'
    };
  }

  /**
   * Optimize component for React Native
   */
  async optimize(code, componentData, config) {
    let optimizedCode = code;

    // Apply React Native optimizations
    optimizedCode = this.optimizeImports(optimizedCode);
    optimizedCode = this.optimizeStyles(optimizedCode);
    optimizedCode = this.optimizePlatformCode(optimizedCode);
    optimizedCode = this.optimizePerformance(optimizedCode);

    this.stats.optimizationsApplied++;

    return optimizedCode;
  }

  /**
   * Optimize imports
   */
  optimizeImports(code) {
    // Remove duplicate imports
    // Sort imports alphabetically
    // Group by source
    return code;
  }

  /**
   * Optimize styles
   */
  optimizeStyles(code) {
    // Extract inline styles to StyleSheet
    // Remove duplicate styles
    // Optimize style calculations
    return code;
  }

  /**
   * Optimize platform-specific code
   */
  optimizePlatformCode(code) {
    // Use Platform.select for platform differences
    // Add platform-specific optimizations
    return code;
  }

  /**
   * Optimize performance
   */
  optimizePerformance(code) {
    // Add useMemo for expensive calculations
    // Add useCallback for event handlers
    // Optimize FlatList rendering
    return code;
  }

  /**
   * Capitalize first letter
   */
  capitalize(str) {
    return str.charAt(0).toUpperCase() + str.slice(1);
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
   * Test React Native generation
   */
  async testGeneration() {
    console.log('🧪 Testing React Native code generation...\n');

    const sampleComponent = {
      name: 'MyButton',
      type: 'button',
      props: {
        title: { type: 'string', required: true },
        onPress: { type: '() => void', required: true },
        disabled: { type: 'boolean', default: false }
      },
      state: {},
      styles: {
        container: {
          'background-color': '#007AFF',
          'padding': '12px',
          'border-radius': '8px',
          'align-items': 'center'
        },
        text: {
          'color': '#FFFFFF',
          'font-size': '16px',
          'font-weight': 'bold'
        }
      },
      text: 'Button',
      children: []
    };

    try {
      console.log('1️⃣ Generating TypeScript component...');
      const tsComponent = await this.generateComponent(sampleComponent, { useTypeScript: true });
      console.log(`   ✓ Generated ${tsComponent.split('\n').length} lines of TypeScript\n`);

      console.log('2️⃣ Generating JavaScript component...');
      const jsComponent = await this.generateComponent(sampleComponent, { useTypeScript: false });
      console.log(`   ✓ Generated ${jsComponent.split('\n').length} lines of JavaScript\n`);

      console.log('3️⃣ Checking statistics...');
      const stats = this.getStats();
      console.log(`   ✓ Components generated: ${stats.componentsGenerated}`);
      console.log(`   ✓ StyleSheets created: ${stats.styleSheets}\n`);

      console.log('✅ React Native generation test complete!\n');

      return {
        success: true,
        tsComponent,
        jsComponent,
        stats
      };

    } catch (error) {
      console.error('❌ React Native test failed:', error.message);
      throw error;
    }
  }

  /**
   * Static transform method for wrapper compatibility
   * Transforms design tokens into React Native code
   */
  static async transform(tokens, options = {}) {
    const fs = require('fs');
    const path = require('path');

    const instance = new ReactNativeOptimizer();
    const files = [];
    const outputPath = options.outputPath || './output';

    // Create output directories
    const tokensDir = path.join(outputPath, 'tokens');
    const themeDir = path.join(outputPath, 'theme');
    fs.mkdirSync(tokensDir, { recursive: true });
    fs.mkdirSync(themeDir, { recursive: true });

    // Generate color tokens as StyleSheet-compatible object
    if (tokens.colors) {
      const colorTokens = instance.generateColorTokens(tokens.colors, options);
      const colorFile = path.join(tokensDir, options.typescript ? 'colors.ts' : 'colors.js');
      fs.writeFileSync(colorFile, colorTokens);
      files.push(colorFile);
    }

    // Generate typography tokens
    if (tokens.typography) {
      const typographyTokens = instance.generateTypographyTokens(tokens.typography, options);
      const typographyFile = path.join(tokensDir, options.typescript ? 'typography.ts' : 'typography.js');
      fs.writeFileSync(typographyFile, typographyTokens);
      files.push(typographyFile);
    }

    // Generate spacing tokens
    if (tokens.spacing) {
      const spacingTokens = instance.generateSpacingTokens(tokens.spacing, options);
      const spacingFile = path.join(tokensDir, options.typescript ? 'spacing.ts' : 'spacing.js');
      fs.writeFileSync(spacingFile, spacingTokens);
      files.push(spacingFile);
    }

    // Generate theme provider
    const themeProvider = instance.generateThemeProvider(tokens, options);
    const themeFile = path.join(themeDir, options.typescript ? 'ThemeProvider.tsx' : 'ThemeProvider.js');
    fs.writeFileSync(themeFile, themeProvider);
    files.push(themeFile);

    // Generate token index
    const indexContent = instance.generateTokenIndex(options);
    const indexFile = path.join(tokensDir, options.typescript ? 'index.ts' : 'index.js');
    fs.writeFileSync(indexFile, indexContent);
    files.push(indexFile);

    return { files, framework: 'react-native' };
  }

  /**
   * Generate React Native color tokens
   */
  generateColorTokens(colors, options) {
    const lines = [];

    if (options.typescript) {
      lines.push('// Auto-generated React Native color tokens');
      lines.push('export const colors = {');
    } else {
      lines.push('// Auto-generated React Native color tokens');
      lines.push('export const colors = {');
    }

    Object.entries(colors).forEach(([key, value]) => {
      if (typeof value === 'object' && value !== null) {
        Object.entries(value).forEach(([subKey, subValue]) => {
          const tokenName = `${key}${subKey.charAt(0).toUpperCase() + subKey.slice(1)}`;
          lines.push(`  ${tokenName}: '${subValue}',`);
        });
      } else {
        lines.push(`  ${key}: '${value}',`);
      }
    });

    lines.push('};');
    lines.push('');
    lines.push('export default colors;');

    return lines.join('\n');
  }

  /**
   * Generate React Native typography tokens
   */
  generateTypographyTokens(typography, options) {
    const lines = [];

    lines.push('// Auto-generated React Native typography tokens');
    lines.push("import { StyleSheet } from 'react-native';");
    lines.push('');
    lines.push('export const typography = StyleSheet.create({');

    Object.entries(typography).forEach(([key, value]) => {
      lines.push(`  ${key}: {`);
      if (value.fontSize) {
        const size = typeof value.fontSize === 'string' ? parseInt(value.fontSize) : value.fontSize;
        lines.push(`    fontSize: ${size},`);
      }
      if (value.fontWeight) {
        lines.push(`    fontWeight: '${value.fontWeight}',`);
      }
      if (value.lineHeight) {
        const lineHeight = typeof value.lineHeight === 'string' ? parseInt(value.lineHeight) : value.lineHeight;
        lines.push(`    lineHeight: ${lineHeight},`);
      }
      if (value.letterSpacing) {
        const letterSpacing = typeof value.letterSpacing === 'string' ? parseFloat(value.letterSpacing) : value.letterSpacing;
        lines.push(`    letterSpacing: ${letterSpacing},`);
      }
      lines.push('  },');
    });

    lines.push('});');
    lines.push('');
    lines.push('export default typography;');

    return lines.join('\n');
  }

  /**
   * Generate React Native spacing tokens
   */
  generateSpacingTokens(spacing, options) {
    const lines = [];

    lines.push('// Auto-generated React Native spacing tokens');
    lines.push('export const spacing = {');

    Object.entries(spacing).forEach(([key, value]) => {
      const numValue = typeof value === 'string' ? parseInt(value) : value;
      lines.push(`  ${key}: ${numValue},`);
    });

    lines.push('};');
    lines.push('');
    lines.push('export default spacing;');

    return lines.join('\n');
  }

  /**
   * Generate React Native theme provider
   */
  generateThemeProvider(tokens, options) {
    const lines = [];
    const ext = options.typescript ? 'ts' : 'js';

    lines.push('// Auto-generated React Native Theme Provider');
    lines.push("import React, { createContext, useContext } from 'react';");
    lines.push(`import { colors } from '../tokens/colors';`);
    lines.push(`import { typography } from '../tokens/typography';`);
    lines.push(`import { spacing } from '../tokens/spacing';`);
    lines.push('');

    if (options.typescript) {
      lines.push('interface Theme {');
      lines.push('  colors: typeof colors;');
      lines.push('  typography: typeof typography;');
      lines.push('  spacing: typeof spacing;');
      lines.push('}');
      lines.push('');
    }

    lines.push('const theme = { colors, typography, spacing };');
    lines.push('');
    lines.push('const ThemeContext = createContext(theme);');
    lines.push('');
    lines.push('export const useTheme = () => useContext(ThemeContext);');
    lines.push('');
    lines.push('export const ThemeProvider = ({ children }) => (');
    lines.push('  <ThemeContext.Provider value={theme}>');
    lines.push('    {children}');
    lines.push('  </ThemeContext.Provider>');
    lines.push(');');
    lines.push('');
    lines.push('export default ThemeProvider;');

    return lines.join('\n');
  }

  /**
   * Generate token index file
   */
  generateTokenIndex(options) {
    const lines = [];

    lines.push('// Auto-generated token index');
    lines.push("export * from './colors';");
    lines.push("export * from './typography';");
    lines.push("export * from './spacing';");

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
    const instance = new ReactNativeOptimizer();
    const warnings = [];

    // Build component data from raw + registry
    const componentData = instance.buildComponentData(raw, registry);

    // Generate component with enriched data
    const config = {
      ...instance.config,
      useTypeScript: options.typescript !== false,
      safeAreaInsets: options.safeAreaInsets !== false,
      animations: options.animations || 'reanimated',
      touchFeedback: options.touchFeedback !== false,
      gestureHandling: options.gestureHandling !== false,
      ...options
    };

    let code;
    try {
      code = await instance.generateComponent(componentData, config);

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

    // Generate preview component if requested
    let preview = null;
    if (options.generatePreview) {
      try {
        preview = instance.generatePreview(componentData, registry, config);
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
      name: registry.name || raw.name || 'Component',
      type: raw.type || 'View',
      props: this.extractProps(raw),
      state: this.extractState(raw),
      styles: {
        container: this.extractContainerStyles(raw),
        text: this.extractTextStyles(raw)
      },
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
   * Extract container styles from raw data
   */
  extractContainerStyles(raw) {
    const styles = {};
    if (raw.fills && raw.fills.length > 0) {
      const fill = raw.fills[0];
      if (fill.color) {
        const { r, g, b, a = 1 } = fill.color;
        styles.backgroundColor = `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${a})`;
      }
    }
    if (raw.cornerRadius) styles.borderRadius = raw.cornerRadius;
    if (raw.paddingLeft) styles.paddingLeft = raw.paddingLeft;
    if (raw.paddingRight) styles.paddingRight = raw.paddingRight;
    if (raw.paddingTop) styles.paddingTop = raw.paddingTop;
    if (raw.paddingBottom) styles.paddingBottom = raw.paddingBottom;
    if (raw.itemSpacing) styles.gap = raw.itemSpacing;
    if (raw.absoluteBoundingBox) {
      styles.width = raw.absoluteBoundingBox.width;
      styles.height = raw.absoluteBoundingBox.height;
    }
    return styles;
  }

  /**
   * Extract text styles from raw data
   */
  extractTextStyles(raw) {
    const styles = {};
    if (raw.style) {
      if (raw.style.fontSize) styles.fontSize = raw.style.fontSize;
      if (raw.style.fontWeight) styles.fontWeight = String(raw.style.fontWeight);
      if (raw.style.lineHeightPx) styles.lineHeight = raw.style.lineHeightPx;
      if (raw.style.letterSpacing) styles.letterSpacing = raw.style.letterSpacing;
    }
    if (raw.fills && raw.fills.length > 0) {
      const fill = raw.fills[0];
      if (fill.color) {
        const { r, g, b, a = 1 } = fill.color;
        styles.color = `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${a})`;
      }
    }
    return styles;
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
        tokenImports.push(`import { ${tokens.join(', ')} } from '../tokens/colors';`);
      } else if (category === 'typography') {
        tokenImports.push(`import { ${tokens.join(', ')} } from '../tokens/typography';`);
      } else if (category === 'spacing') {
        tokenImports.push(`import { ${tokens.join(', ')} } from '../tokens/spacing';`);
      }
    });

    if (tokenImports.length > 0) {
      // Insert after react-native imports
      const importIndex = updatedCode.indexOf("} from 'react-native';");
      if (importIndex !== -1) {
        const insertPoint = importIndex + "} from 'react-native';".length;
        updatedCode = updatedCode.slice(0, insertPoint) + '\n' + tokenImports.join('\n') + updatedCode.slice(insertPoint);
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
    const stateHandlers = [];

    if (interactiveStates.pressed || interactiveStates.active) {
      stateHandlers.push(`const [isPressed, setIsPressed] = useState(false);`);
    }

    if (interactiveStates.focused || interactiveStates.focus) {
      stateHandlers.push(`const [isFocused, setIsFocused] = useState(false);`);
    }

    if (interactiveStates.disabled) {
      stateHandlers.push(`// Handle disabled prop for visual state`);
    }

    if (stateHandlers.length > 0) {
      // Insert state handlers after existing useState declarations
      const stateIndex = updatedCode.indexOf('// State');
      if (stateIndex !== -1) {
        const insertPoint = updatedCode.indexOf('\n', stateIndex + 10);
        updatedCode = updatedCode.slice(0, insertPoint) + '\n  // Interactive states\n  ' + stateHandlers.join('\n  ') + updatedCode.slice(insertPoint);
      }
    }

    return updatedCode;
  }

  /**
   * Apply variants to generated code
   */
  applyVariants(code, variants, config) {
    let updatedCode = code;

    // Add variant prop and styles
    const variantStyles = variants.map(variant => {
      return `  ${variant.name}: ${JSON.stringify(variant.styles || {})}`;
    }).join(',\n');

    if (variantStyles) {
      // Add variant styles object
      const stylesIndex = updatedCode.indexOf('const styles = StyleSheet.create({');
      if (stylesIndex !== -1) {
        const variantStylesObj = `\nconst variantStyles = {\n${variantStyles}\n};\n\n`;
        updatedCode = updatedCode.slice(0, stylesIndex) + variantStylesObj + updatedCode.slice(stylesIndex);
      }
    }

    return updatedCode;
  }

  /**
   * Generate preview component for React Native
   */
  generatePreview(componentData, registry, config) {
    const { name } = componentData;
    const lines = [];

    lines.push(`// Preview component for ${name}`);
    lines.push(`import React from 'react';`);
    lines.push(`import { View, ScrollView } from 'react-native';`);
    lines.push(`import ${name} from './${name}';`);
    lines.push('');
    lines.push(`export const ${name}Preview = () => {`);
    lines.push('  return (');
    lines.push('    <ScrollView style={{ flex: 1, padding: 16 }}>');
    lines.push(`      <${name} />`);

    // Add variant previews
    if (registry.variants && registry.variants.length > 0) {
      registry.variants.forEach(variant => {
        lines.push(`      <View style={{ marginTop: 16 }} />`);
        lines.push(`      <${name} variant="${variant.name}" />`);
      });
    }

    lines.push('    </ScrollView>');
    lines.push('  );');
    lines.push('};');
    lines.push('');
    lines.push(`export default ${name}Preview;`);

    return lines.join('\n');
  }
}

module.exports = ReactNativeOptimizer;
