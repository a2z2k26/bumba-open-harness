/**
 * Pattern Compatibility Matrix
 *
 * Maps Figma design patterns to framework support levels.
 * Enables informed decision-making when transformations might fail
 * or produce suboptimal results.
 *
 * Key Principle: Make failures observable and recoverable, not silent and destructive.
 *
 * @module pattern-compatibility
 */

'use strict';

// =============================================================================
// CONSTANTS
// =============================================================================

/**
 * List of all supported target frameworks
 */
const FRAMEWORK_LIST = [
  'react',
  'vue',
  'svelte',
  'angular',
  'react-native',
  'flutter',
  'swiftui',
  'jetpack-compose',
  'web-components'
];

/**
 * Support level enumeration
 */
const SUPPORT_LEVELS = {
  FULL: 'full',           // Direct mapping, no workarounds needed
  PARTIAL: 'partial',     // Works with limitations or workarounds
  NONE: 'none',           // Not supported, requires alternative approach
  EXPERIMENTAL: 'experimental'  // Support uncertain, needs testing
};

/**
 * Pattern categories for organization and filtering
 */
const PATTERN_CATEGORIES = {
  layout: {
    name: 'Layout',
    description: 'Structural and positioning patterns',
    patterns: [
      'auto-layout',
      'constraints',
      'absolute-positioning',
      'grid-layout',
      'stack-layout'
    ]
  },
  visual: {
    name: 'Visual',
    description: 'Fills, strokes, effects, and blend modes',
    patterns: [
      'solid-fill',
      'linear-gradient',
      'radial-gradient',
      'angular-gradient',
      'image-fill',
      'stroke',
      'drop-shadow',
      'inner-shadow',
      'layer-blur',
      'background-blur',
      'blend-mode'
    ]
  },
  interaction: {
    name: 'Interaction',
    description: 'Interactive states and variants',
    patterns: [
      'hover-state',
      'pressed-state',
      'disabled-state',
      'focus-state',
      'component-variants',
      'component-sets'
    ]
  },
  content: {
    name: 'Content',
    description: 'Text, images, vectors, and masks',
    patterns: [
      'text-styles',
      'text-auto-resize',
      'raster-images',
      'vector-graphics',
      'boolean-operations',
      'masks',
      'clips'
    ]
  },
  advanced: {
    name: 'Advanced',
    description: 'Complex patterns requiring special handling',
    patterns: [
      'nested-components',
      'component-props',
      'auto-layout-wrap',
      'variable-bindings',
      'responsive-constraints'
    ]
  }
};

/**
 * Get all pattern names as a flat array
 * @returns {string[]} All pattern names
 */
function getAllPatterns() {
  return Object.values(PATTERN_CATEGORIES)
    .flatMap(category => category.patterns);
}

/**
 * Get category for a given pattern
 * @param {string} pattern - Pattern name
 * @returns {string|null} Category name or null if not found
 */
function getCategoryForPattern(pattern) {
  for (const [categoryName, category] of Object.entries(PATTERN_CATEGORIES)) {
    if (category.patterns.includes(pattern)) {
      return categoryName;
    }
  }
  return null;
}

// =============================================================================
// COMPATIBILITY MATRIX
// =============================================================================

/**
 * Full compatibility matrix mapping patterns to framework support
 * Each entry includes support level, notes, and optional fallback approach
 */
const COMPATIBILITY_MATRIX = {
  // ----- Layout Patterns -----
  'auto-layout': {
    react: { level: 'full', notes: 'Direct flexbox mapping via CSS' },
    vue: { level: 'full', notes: 'Direct flexbox mapping via CSS' },
    svelte: { level: 'full', notes: 'Direct flexbox mapping via CSS' },
    angular: { level: 'full', notes: 'Direct flexbox mapping via CSS' },
    'react-native': { level: 'full', notes: 'Flexbox native support' },
    flutter: { level: 'full', notes: 'Column/Row/Flex widgets' },
    swiftui: { level: 'full', notes: 'VStack/HStack/ZStack' },
    'jetpack-compose': { level: 'full', notes: 'Column/Row composables' },
    'web-components': { level: 'full', notes: 'Direct flexbox mapping via CSS' }
  },

  'constraints': {
    react: { level: 'partial', notes: 'Requires CSS positioning/flexbox combinations', fallback: 'Use responsive CSS utilities' },
    vue: { level: 'partial', notes: 'Requires CSS positioning/flexbox combinations', fallback: 'Use responsive CSS utilities' },
    svelte: { level: 'partial', notes: 'Requires CSS positioning/flexbox combinations', fallback: 'Use responsive CSS utilities' },
    angular: { level: 'partial', notes: 'Requires CSS positioning/flexbox combinations', fallback: 'Use responsive CSS utilities' },
    'react-native': { level: 'partial', notes: 'Limited to flexbox constraints', fallback: 'Use onLayout for dynamic sizing' },
    flutter: { level: 'full', notes: 'Align widget handles constraints well' },
    swiftui: { level: 'full', notes: 'Native constraint system' },
    'jetpack-compose': { level: 'full', notes: 'ConstraintLayout composable' },
    'web-components': { level: 'partial', notes: 'Requires CSS positioning/flexbox combinations', fallback: 'Use responsive CSS utilities' }
  },

  'absolute-positioning': {
    react: { level: 'full', notes: 'CSS position: absolute' },
    vue: { level: 'full', notes: 'CSS position: absolute' },
    svelte: { level: 'full', notes: 'CSS position: absolute' },
    angular: { level: 'full', notes: 'CSS position: absolute' },
    'react-native': { level: 'full', notes: 'position: absolute supported' },
    flutter: { level: 'full', notes: 'Positioned widget in Stack' },
    swiftui: { level: 'partial', notes: 'Use offset or position modifiers', fallback: 'GeometryReader for complex cases' },
    'jetpack-compose': { level: 'full', notes: 'Modifier.offset or Box with alignment' },
    'web-components': { level: 'full', notes: 'CSS position: absolute' }
  },

  'grid-layout': {
    react: { level: 'full', notes: 'CSS Grid' },
    vue: { level: 'full', notes: 'CSS Grid' },
    svelte: { level: 'full', notes: 'CSS Grid' },
    angular: { level: 'full', notes: 'CSS Grid' },
    'react-native': { level: 'partial', notes: 'No native grid, use FlatList numColumns', fallback: 'Third-party grid libraries' },
    flutter: { level: 'full', notes: 'GridView widget' },
    swiftui: { level: 'full', notes: 'LazyVGrid/LazyHGrid' },
    'jetpack-compose': { level: 'full', notes: 'LazyVerticalGrid/LazyHorizontalGrid' },
    'web-components': { level: 'full', notes: 'CSS Grid' }
  },

  'stack-layout': {
    react: { level: 'full', notes: 'CSS z-index stacking' },
    vue: { level: 'full', notes: 'CSS z-index stacking' },
    svelte: { level: 'full', notes: 'CSS z-index stacking' },
    angular: { level: 'full', notes: 'CSS z-index stacking' },
    'react-native': { level: 'full', notes: 'Views stack by default or use zIndex' },
    flutter: { level: 'full', notes: 'Stack widget' },
    swiftui: { level: 'full', notes: 'ZStack' },
    'jetpack-compose': { level: 'full', notes: 'Box with stacking' },
    'web-components': { level: 'full', notes: 'CSS z-index stacking' }
  },

  // ----- Visual Patterns -----
  'solid-fill': {
    react: { level: 'full', notes: 'background-color CSS' },
    vue: { level: 'full', notes: 'background-color CSS' },
    svelte: { level: 'full', notes: 'background-color CSS' },
    angular: { level: 'full', notes: 'background-color CSS' },
    'react-native': { level: 'full', notes: 'backgroundColor style' },
    flutter: { level: 'full', notes: 'Color class' },
    swiftui: { level: 'full', notes: 'Color modifier' },
    'jetpack-compose': { level: 'full', notes: 'Modifier.background' },
    'web-components': { level: 'full', notes: 'background-color CSS' }
  },

  'linear-gradient': {
    react: { level: 'full', notes: 'CSS linear-gradient()' },
    vue: { level: 'full', notes: 'CSS linear-gradient()' },
    svelte: { level: 'full', notes: 'CSS linear-gradient()' },
    angular: { level: 'full', notes: 'CSS linear-gradient()' },
    'react-native': { level: 'partial', notes: 'Requires react-native-linear-gradient', fallback: 'expo-linear-gradient' },
    flutter: { level: 'full', notes: 'LinearGradient in BoxDecoration' },
    swiftui: { level: 'full', notes: 'LinearGradient view' },
    'jetpack-compose': { level: 'full', notes: 'Brush.linearGradient' },
    'web-components': { level: 'full', notes: 'CSS linear-gradient()' }
  },

  'radial-gradient': {
    react: { level: 'full', notes: 'CSS radial-gradient()' },
    vue: { level: 'full', notes: 'CSS radial-gradient()' },
    svelte: { level: 'full', notes: 'CSS radial-gradient()' },
    angular: { level: 'full', notes: 'CSS radial-gradient()' },
    'react-native': { level: 'none', notes: 'Not natively supported', fallback: 'Use SVG or react-native-svg' },
    flutter: { level: 'full', notes: 'RadialGradient in BoxDecoration' },
    swiftui: { level: 'full', notes: 'RadialGradient view' },
    'jetpack-compose': { level: 'full', notes: 'Brush.radialGradient' },
    'web-components': { level: 'full', notes: 'CSS radial-gradient()' }
  },

  'angular-gradient': {
    react: { level: 'full', notes: 'CSS conic-gradient()' },
    vue: { level: 'full', notes: 'CSS conic-gradient()' },
    svelte: { level: 'full', notes: 'CSS conic-gradient()' },
    angular: { level: 'full', notes: 'CSS conic-gradient()' },
    'react-native': { level: 'none', notes: 'Not natively supported', fallback: 'Use SVG' },
    flutter: { level: 'full', notes: 'SweepGradient' },
    swiftui: { level: 'full', notes: 'AngularGradient view' },
    'jetpack-compose': { level: 'full', notes: 'Brush.sweepGradient' },
    'web-components': { level: 'full', notes: 'CSS conic-gradient()' }
  },

  'image-fill': {
    react: { level: 'full', notes: 'background-image CSS with object-fit' },
    vue: { level: 'full', notes: 'background-image CSS with object-fit' },
    svelte: { level: 'full', notes: 'background-image CSS with object-fit' },
    angular: { level: 'full', notes: 'background-image CSS with object-fit' },
    'react-native': { level: 'full', notes: 'ImageBackground component or Image with resizeMode' },
    flutter: { level: 'full', notes: 'DecorationImage in BoxDecoration' },
    swiftui: { level: 'full', notes: 'Image with resizable and aspectRatio' },
    'jetpack-compose': { level: 'full', notes: 'Image composable with contentScale' },
    'web-components': { level: 'full', notes: 'background-image CSS with object-fit' }
  },

  'stroke': {
    react: { level: 'full', notes: 'border CSS property' },
    vue: { level: 'full', notes: 'border CSS property' },
    svelte: { level: 'full', notes: 'border CSS property' },
    angular: { level: 'full', notes: 'border CSS property' },
    'react-native': { level: 'full', notes: 'borderWidth/borderColor styles' },
    flutter: { level: 'full', notes: 'Border in BoxDecoration' },
    swiftui: { level: 'full', notes: 'stroke modifier or overlay' },
    'jetpack-compose': { level: 'full', notes: 'Modifier.border' },
    'web-components': { level: 'full', notes: 'border CSS property' }
  },

  'drop-shadow': {
    react: { level: 'full', notes: 'box-shadow CSS or filter: drop-shadow()' },
    vue: { level: 'full', notes: 'box-shadow CSS or filter: drop-shadow()' },
    svelte: { level: 'full', notes: 'box-shadow CSS or filter: drop-shadow()' },
    angular: { level: 'full', notes: 'box-shadow CSS or filter: drop-shadow()' },
    'react-native': { level: 'partial', notes: 'iOS shadowX props, Android elevation', fallback: 'react-native-shadow-2 for consistency' },
    flutter: { level: 'full', notes: 'BoxShadow in BoxDecoration' },
    swiftui: { level: 'full', notes: 'shadow modifier' },
    'jetpack-compose': { level: 'partial', notes: 'Modifier.shadow (limited control)', fallback: 'Custom shadow drawing' },
    'web-components': { level: 'full', notes: 'box-shadow CSS or filter: drop-shadow()' }
  },

  'inner-shadow': {
    react: { level: 'full', notes: 'box-shadow with inset keyword' },
    vue: { level: 'full', notes: 'box-shadow with inset keyword' },
    svelte: { level: 'full', notes: 'box-shadow with inset keyword' },
    angular: { level: 'full', notes: 'box-shadow with inset keyword' },
    'react-native': { level: 'none', notes: 'Not natively supported', fallback: 'SVG or custom gradient overlay' },
    flutter: { level: 'partial', notes: 'Requires custom painting', fallback: 'CustomPainter with shader' },
    swiftui: { level: 'partial', notes: 'Requires custom overlay approach', fallback: 'Inner shadow via overlay' },
    'jetpack-compose': { level: 'none', notes: 'Not natively supported', fallback: 'Custom Canvas drawing' },
    'web-components': { level: 'full', notes: 'box-shadow with inset keyword' }
  },

  'layer-blur': {
    react: { level: 'full', notes: 'filter: blur() CSS' },
    vue: { level: 'full', notes: 'filter: blur() CSS' },
    svelte: { level: 'full', notes: 'filter: blur() CSS' },
    angular: { level: 'full', notes: 'filter: blur() CSS' },
    'react-native': { level: 'partial', notes: 'iOS UIBlurEffect via native module', fallback: '@react-native-community/blur' },
    flutter: { level: 'full', notes: 'BackdropFilter with ImageFilter.blur' },
    swiftui: { level: 'full', notes: 'blur modifier' },
    'jetpack-compose': { level: 'partial', notes: 'RenderEffect API (Android 12+)', fallback: 'Bitmap blur for older versions' },
    'web-components': { level: 'full', notes: 'filter: blur() CSS' }
  },

  'background-blur': {
    react: { level: 'full', notes: 'backdrop-filter: blur() CSS' },
    vue: { level: 'full', notes: 'backdrop-filter: blur() CSS' },
    svelte: { level: 'full', notes: 'backdrop-filter: blur() CSS' },
    angular: { level: 'full', notes: 'backdrop-filter: blur() CSS' },
    'react-native': { level: 'partial', notes: 'Platform-specific implementation', fallback: '@react-native-community/blur BlurView' },
    flutter: { level: 'full', notes: 'BackdropFilter widget' },
    swiftui: { level: 'full', notes: 'Material or ultraThinMaterial' },
    'jetpack-compose': { level: 'partial', notes: 'Limited native support', fallback: 'Custom blur effect' },
    'web-components': { level: 'full', notes: 'backdrop-filter: blur() CSS' }
  },

  'blend-mode': {
    react: { level: 'full', notes: 'mix-blend-mode CSS' },
    vue: { level: 'full', notes: 'mix-blend-mode CSS' },
    svelte: { level: 'full', notes: 'mix-blend-mode CSS' },
    angular: { level: 'full', notes: 'mix-blend-mode CSS' },
    'react-native': { level: 'none', notes: 'Not supported', fallback: 'Pre-render blended images or use SVG' },
    flutter: { level: 'full', notes: 'BlendMode enum' },
    swiftui: { level: 'partial', notes: 'blendMode modifier (limited modes)', fallback: 'CoreImage filters' },
    'jetpack-compose': { level: 'partial', notes: 'BlendMode in DrawScope', fallback: 'Custom blend via Porter-Duff' },
    'web-components': { level: 'full', notes: 'mix-blend-mode CSS' }
  },

  // ----- Interaction Patterns -----
  'hover-state': {
    react: { level: 'full', notes: 'CSS :hover or onMouseEnter/Leave' },
    vue: { level: 'full', notes: 'CSS :hover or @mouseenter/@mouseleave' },
    svelte: { level: 'full', notes: 'CSS :hover or on:mouseenter/leave' },
    angular: { level: 'full', notes: 'CSS :hover or (mouseenter)/(mouseleave)' },
    'react-native': { level: 'none', notes: 'Touch devices have no hover', fallback: 'Use Pressable with web hover detection' },
    flutter: { level: 'partial', notes: 'MouseRegion for desktop/web', fallback: 'InkWell for touch ripple' },
    swiftui: { level: 'partial', notes: 'onHover modifier (macOS/iPadOS)', fallback: 'Not applicable on iPhone' },
    'jetpack-compose': { level: 'partial', notes: 'Modifier.hoverable (desktop)', fallback: 'Not applicable on mobile' },
    'web-components': { level: 'full', notes: 'CSS :hover' }
  },

  'pressed-state': {
    react: { level: 'full', notes: 'CSS :active or onClick state' },
    vue: { level: 'full', notes: 'CSS :active or @click state' },
    svelte: { level: 'full', notes: 'CSS :active or on:click state' },
    angular: { level: 'full', notes: 'CSS :active or (click) state' },
    'react-native': { level: 'full', notes: 'Pressable onPressIn/onPressOut' },
    flutter: { level: 'full', notes: 'GestureDetector or InkWell' },
    swiftui: { level: 'full', notes: 'ButtonStyle with isPressed' },
    'jetpack-compose': { level: 'full', notes: 'InteractionSource with isPressed' },
    'web-components': { level: 'full', notes: 'CSS :active' }
  },

  'disabled-state': {
    react: { level: 'full', notes: 'disabled attribute + CSS :disabled' },
    vue: { level: 'full', notes: ':disabled binding + CSS :disabled' },
    svelte: { level: 'full', notes: 'disabled attribute + CSS :disabled' },
    angular: { level: 'full', notes: '[disabled] + CSS :disabled' },
    'react-native': { level: 'full', notes: 'disabled prop on Pressable/TouchableX' },
    flutter: { level: 'full', notes: 'enabled: false on buttons' },
    swiftui: { level: 'full', notes: '.disabled() modifier' },
    'jetpack-compose': { level: 'full', notes: 'enabled = false parameter' },
    'web-components': { level: 'full', notes: 'disabled attribute + CSS :disabled' }
  },

  'focus-state': {
    react: { level: 'full', notes: 'CSS :focus/:focus-visible' },
    vue: { level: 'full', notes: 'CSS :focus/:focus-visible' },
    svelte: { level: 'full', notes: 'CSS :focus/:focus-visible' },
    angular: { level: 'full', notes: 'CSS :focus/:focus-visible' },
    'react-native': { level: 'partial', notes: 'onFocus/onBlur for TextInput', fallback: 'Custom focus management for other elements' },
    flutter: { level: 'full', notes: 'FocusNode and Focus widget' },
    swiftui: { level: 'full', notes: '@FocusState property wrapper' },
    'jetpack-compose': { level: 'full', notes: 'FocusRequester and Modifier.focusable' },
    'web-components': { level: 'full', notes: 'CSS :focus/:focus-visible' }
  },

  'component-variants': {
    react: { level: 'full', notes: 'Props-based conditional rendering' },
    vue: { level: 'full', notes: 'Props-based conditional rendering' },
    svelte: { level: 'full', notes: 'Props-based conditional rendering' },
    angular: { level: 'full', notes: '@Input() based conditional rendering' },
    'react-native': { level: 'full', notes: 'Props-based conditional rendering' },
    flutter: { level: 'full', notes: 'Constructor parameters for variants' },
    swiftui: { level: 'full', notes: 'Enum-based view variants' },
    'jetpack-compose': { level: 'full', notes: 'Parameter-based composable variants' },
    'web-components': { level: 'full', notes: 'Attribute-based conditional rendering' }
  },

  'component-sets': {
    react: { level: 'full', notes: 'Component composition patterns' },
    vue: { level: 'full', notes: 'Component composition patterns' },
    svelte: { level: 'full', notes: 'Component composition patterns' },
    angular: { level: 'full', notes: 'Component composition patterns' },
    'react-native': { level: 'full', notes: 'Component composition patterns' },
    flutter: { level: 'full', notes: 'Widget composition patterns' },
    swiftui: { level: 'full', notes: 'View composition patterns' },
    'jetpack-compose': { level: 'full', notes: 'Composable composition patterns' },
    'web-components': { level: 'full', notes: 'Element composition patterns' }
  },

  // ----- Content Patterns -----
  'text-styles': {
    react: { level: 'full', notes: 'CSS typography properties' },
    vue: { level: 'full', notes: 'CSS typography properties' },
    svelte: { level: 'full', notes: 'CSS typography properties' },
    angular: { level: 'full', notes: 'CSS typography properties' },
    'react-native': { level: 'full', notes: 'Text style properties' },
    flutter: { level: 'full', notes: 'TextStyle class' },
    swiftui: { level: 'full', notes: 'Font and text modifiers' },
    'jetpack-compose': { level: 'full', notes: 'TextStyle class' },
    'web-components': { level: 'full', notes: 'CSS typography properties' }
  },

  'text-auto-resize': {
    react: { level: 'partial', notes: 'Requires JavaScript measurement', fallback: 'CSS clamp() or viewport units' },
    vue: { level: 'partial', notes: 'Requires JavaScript measurement', fallback: 'CSS clamp() or viewport units' },
    svelte: { level: 'partial', notes: 'Requires JavaScript measurement', fallback: 'CSS clamp() or viewport units' },
    angular: { level: 'partial', notes: 'Requires JavaScript measurement', fallback: 'CSS clamp() or viewport units' },
    'react-native': { level: 'partial', notes: 'adjustsFontSizeToFit (iOS) or numberOfLines', fallback: 'react-native-auto-size-text' },
    flutter: { level: 'full', notes: 'FittedBox or AutoSizeText package' },
    swiftui: { level: 'full', notes: 'minimumScaleFactor modifier' },
    'jetpack-compose': { level: 'partial', notes: 'autoSize in TextStyle (limited)', fallback: 'Custom measurement logic' },
    'web-components': { level: 'partial', notes: 'Requires JavaScript measurement', fallback: 'CSS clamp() or viewport units' }
  },

  'raster-images': {
    react: { level: 'full', notes: '<img> element or CSS background' },
    vue: { level: 'full', notes: '<img> element or CSS background' },
    svelte: { level: 'full', notes: '<img> element or CSS background' },
    angular: { level: 'full', notes: '<img> element or CSS background' },
    'react-native': { level: 'full', notes: 'Image component' },
    flutter: { level: 'full', notes: 'Image widget' },
    swiftui: { level: 'full', notes: 'Image or AsyncImage' },
    'jetpack-compose': { level: 'full', notes: 'Image composable with painterResource/coil' },
    'web-components': { level: 'full', notes: '<img> element or CSS background' }
  },

  'vector-graphics': {
    react: { level: 'full', notes: 'Inline SVG or SVG files' },
    vue: { level: 'full', notes: 'Inline SVG or SVG files' },
    svelte: { level: 'full', notes: 'Inline SVG or SVG files' },
    angular: { level: 'full', notes: 'Inline SVG or SVG files' },
    'react-native': { level: 'partial', notes: 'Requires react-native-svg', fallback: 'Convert to PNG for simple cases' },
    flutter: { level: 'full', notes: 'flutter_svg package or CustomPaint' },
    swiftui: { level: 'partial', notes: 'Shape protocol or SVGKit', fallback: 'Convert to PDF for vector assets' },
    'jetpack-compose': { level: 'partial', notes: 'vector drawables or Compose Canvas', fallback: 'Convert to Android Vector Drawable' },
    'web-components': { level: 'full', notes: 'Inline SVG or SVG files' }
  },

  'boolean-operations': {
    react: { level: 'full', notes: 'SVG clipPath and mask operations' },
    vue: { level: 'full', notes: 'SVG clipPath and mask operations' },
    svelte: { level: 'full', notes: 'SVG clipPath and mask operations' },
    angular: { level: 'full', notes: 'SVG clipPath and mask operations' },
    'react-native': { level: 'partial', notes: 'react-native-svg supports some operations', fallback: 'Pre-flatten in Figma' },
    flutter: { level: 'full', notes: 'Path.combine with PathOperation' },
    swiftui: { level: 'partial', notes: 'Limited Shape composition', fallback: 'Pre-flatten complex operations' },
    'jetpack-compose': { level: 'partial', notes: 'Path operations in Canvas', fallback: 'Pre-flatten complex operations' },
    'web-components': { level: 'full', notes: 'SVG clipPath and mask operations' }
  },

  'masks': {
    react: { level: 'full', notes: 'CSS mask-image or SVG mask' },
    vue: { level: 'full', notes: 'CSS mask-image or SVG mask' },
    svelte: { level: 'full', notes: 'CSS mask-image or SVG mask' },
    angular: { level: 'full', notes: 'CSS mask-image or SVG mask' },
    'react-native': { level: 'partial', notes: 'MaskedView component', fallback: 'react-native-masked-view' },
    flutter: { level: 'full', notes: 'ClipPath or ShaderMask' },
    swiftui: { level: 'full', notes: 'mask modifier' },
    'jetpack-compose': { level: 'partial', notes: 'clipToOutline or graphicsLayer', fallback: 'Custom Canvas masking' },
    'web-components': { level: 'full', notes: 'CSS mask-image or SVG mask' }
  },

  'clips': {
    react: { level: 'full', notes: 'CSS overflow: hidden or clip-path' },
    vue: { level: 'full', notes: 'CSS overflow: hidden or clip-path' },
    svelte: { level: 'full', notes: 'CSS overflow: hidden or clip-path' },
    angular: { level: 'full', notes: 'CSS overflow: hidden or clip-path' },
    'react-native': { level: 'full', notes: 'overflow: hidden style' },
    flutter: { level: 'full', notes: 'ClipRect, ClipRRect, ClipOval' },
    swiftui: { level: 'full', notes: 'clipShape or clipped modifier' },
    'jetpack-compose': { level: 'full', notes: 'Modifier.clip' },
    'web-components': { level: 'full', notes: 'CSS overflow: hidden or clip-path' }
  },

  // ----- Advanced Patterns -----
  'nested-components': {
    react: { level: 'full', notes: 'Component composition and children prop' },
    vue: { level: 'full', notes: 'Component composition and slots' },
    svelte: { level: 'full', notes: 'Component composition and slots' },
    angular: { level: 'full', notes: 'Component composition and ng-content' },
    'react-native': { level: 'full', notes: 'Component composition and children prop' },
    flutter: { level: 'full', notes: 'Widget composition and child/children' },
    swiftui: { level: 'full', notes: 'View composition and ViewBuilder' },
    'jetpack-compose': { level: 'full', notes: 'Composable composition and content lambdas' },
    'web-components': { level: 'full', notes: 'Element composition and slots' }
  },

  'component-props': {
    react: { level: 'full', notes: 'Props interface/type' },
    vue: { level: 'full', notes: 'defineProps with TypeScript' },
    svelte: { level: 'full', notes: 'export let declarations' },
    angular: { level: 'full', notes: '@Input() decorators' },
    'react-native': { level: 'full', notes: 'Props interface/type' },
    flutter: { level: 'full', notes: 'Widget constructor parameters' },
    swiftui: { level: 'full', notes: 'View init parameters' },
    'jetpack-compose': { level: 'full', notes: 'Composable function parameters' },
    'web-components': { level: 'full', notes: 'Observed attributes and properties' }
  },

  'auto-layout-wrap': {
    react: { level: 'full', notes: 'CSS flex-wrap: wrap' },
    vue: { level: 'full', notes: 'CSS flex-wrap: wrap' },
    svelte: { level: 'full', notes: 'CSS flex-wrap: wrap' },
    angular: { level: 'full', notes: 'CSS flex-wrap: wrap' },
    'react-native': { level: 'full', notes: 'flexWrap: wrap style' },
    flutter: { level: 'full', notes: 'Wrap widget' },
    swiftui: { level: 'partial', notes: 'Requires custom FlowLayout', fallback: 'Use LazyVGrid with flexible columns' },
    'jetpack-compose': { level: 'full', notes: 'FlowRow/FlowColumn (experimental)' },
    'web-components': { level: 'full', notes: 'CSS flex-wrap: wrap' }
  },

  'variable-bindings': {
    react: { level: 'experimental', notes: 'Figma variables to CSS custom properties', fallback: 'Manual token extraction' },
    vue: { level: 'experimental', notes: 'Figma variables to CSS custom properties', fallback: 'Manual token extraction' },
    svelte: { level: 'experimental', notes: 'Figma variables to CSS custom properties', fallback: 'Manual token extraction' },
    angular: { level: 'experimental', notes: 'Figma variables to CSS custom properties', fallback: 'Manual token extraction' },
    'react-native': { level: 'experimental', notes: 'Figma variables to theme constants', fallback: 'Manual token extraction' },
    flutter: { level: 'experimental', notes: 'Figma variables to ThemeData', fallback: 'Manual token extraction' },
    swiftui: { level: 'experimental', notes: 'Figma variables to SwiftUI Environment', fallback: 'Manual token extraction' },
    'jetpack-compose': { level: 'experimental', notes: 'Figma variables to MaterialTheme', fallback: 'Manual token extraction' },
    'web-components': { level: 'experimental', notes: 'Figma variables to CSS custom properties', fallback: 'Manual token extraction' }
  },

  'responsive-constraints': {
    react: { level: 'partial', notes: 'CSS media queries and container queries', fallback: 'JavaScript resize observers' },
    vue: { level: 'partial', notes: 'CSS media queries and container queries', fallback: 'JavaScript resize observers' },
    svelte: { level: 'partial', notes: 'CSS media queries and container queries', fallback: 'JavaScript resize observers' },
    angular: { level: 'partial', notes: 'CSS media queries and container queries', fallback: 'BreakpointObserver service' },
    'react-native': { level: 'partial', notes: 'Dimensions API and useWindowDimensions', fallback: 'react-native-responsive-screen' },
    flutter: { level: 'full', notes: 'LayoutBuilder and MediaQuery' },
    swiftui: { level: 'full', notes: 'GeometryReader and size classes' },
    'jetpack-compose': { level: 'full', notes: 'BoxWithConstraints' },
    'web-components': { level: 'partial', notes: 'CSS media queries and container queries', fallback: 'ResizeObserver API' }
  }
};

// =============================================================================
// QUERY API
// =============================================================================

/**
 * Check pattern support for a specific framework
 * @param {string} pattern - Pattern name to check
 * @param {string} framework - Target framework
 * @returns {Object} Support information with level, notes, and fallback
 */
function checkPatternSupport(pattern, framework) {
  // Input validation
  if (!pattern || typeof pattern !== 'string') {
    return {
      supported: false,
      level: SUPPORT_LEVELS.NONE,
      notes: 'Invalid pattern: pattern name must be a non-empty string',
      fallback: null,
      error: 'INVALID_PATTERN'
    };
  }

  if (!framework || typeof framework !== 'string') {
    return {
      supported: false,
      level: SUPPORT_LEVELS.NONE,
      notes: 'Invalid framework: framework name must be a non-empty string',
      fallback: null,
      error: 'INVALID_FRAMEWORK'
    };
  }

  // Normalize inputs
  const normalizedPattern = pattern.toLowerCase().trim();
  const normalizedFramework = framework.toLowerCase().trim();

  // Check if framework exists
  if (!FRAMEWORK_LIST.includes(normalizedFramework)) {
    return {
      supported: false,
      level: SUPPORT_LEVELS.EXPERIMENTAL,
      notes: `Unknown framework: ${framework}. Support level is uncertain.`,
      fallback: 'Consider using a supported framework or manual implementation',
      error: 'UNKNOWN_FRAMEWORK'
    };
  }

  // Check if pattern exists in matrix
  const patternEntry = COMPATIBILITY_MATRIX[normalizedPattern];
  if (!patternEntry) {
    return {
      supported: true, // Assume supported if unknown
      level: SUPPORT_LEVELS.EXPERIMENTAL,
      notes: `Unknown pattern: ${pattern}. Support level needs verification.`,
      fallback: null,
      error: 'UNKNOWN_PATTERN'
    };
  }

  // Get framework-specific support
  const support = patternEntry[normalizedFramework];
  if (!support) {
    return {
      supported: false,
      level: SUPPORT_LEVELS.EXPERIMENTAL,
      notes: `No compatibility data for ${pattern} on ${framework}`,
      fallback: null,
      error: 'NO_DATA'
    };
  }

  // Determine if supported based on level
  const isSupported = support.level === SUPPORT_LEVELS.FULL ||
                      support.level === SUPPORT_LEVELS.PARTIAL;

  return {
    supported: isSupported,
    level: support.level,
    notes: support.notes,
    fallback: support.fallback || null,
    error: null
  };
}

/**
 * Get all limitations for a specific framework
 * @param {string} framework - Target framework
 * @returns {Object[]} Array of patterns with partial/none support, sorted by severity
 */
function getFrameworkLimitations(framework) {
  if (!framework || typeof framework !== 'string') {
    return [];
  }

  const normalizedFramework = framework.toLowerCase().trim();

  if (!FRAMEWORK_LIST.includes(normalizedFramework)) {
    return [{
      pattern: 'all',
      level: SUPPORT_LEVELS.EXPERIMENTAL,
      notes: `Unknown framework: ${framework}`,
      category: 'unknown'
    }];
  }

  const limitations = [];

  for (const [pattern, frameworkSupport] of Object.entries(COMPATIBILITY_MATRIX)) {
    const support = frameworkSupport[normalizedFramework];
    if (support && (support.level === SUPPORT_LEVELS.PARTIAL ||
                    support.level === SUPPORT_LEVELS.NONE ||
                    support.level === SUPPORT_LEVELS.EXPERIMENTAL)) {
      limitations.push({
        pattern,
        level: support.level,
        notes: support.notes,
        fallback: support.fallback || null,
        category: getCategoryForPattern(pattern)
      });
    }
  }

  // Sort by severity: none > partial > experimental
  const severityOrder = {
    [SUPPORT_LEVELS.NONE]: 0,
    [SUPPORT_LEVELS.PARTIAL]: 1,
    [SUPPORT_LEVELS.EXPERIMENTAL]: 2
  };

  return limitations.sort((a, b) =>
    severityOrder[a.level] - severityOrder[b.level]
  );
}

/**
 * Suggest fallback approach for a pattern/framework combination
 * @param {string} pattern - Pattern name
 * @param {string} framework - Target framework
 * @returns {Object} Fallback suggestion with approach and alternatives
 */
function suggestFallback(pattern, framework) {
  const support = checkPatternSupport(pattern, framework);

  // If fully supported, no fallback needed
  if (support.level === SUPPORT_LEVELS.FULL) {
    return {
      needed: false,
      pattern,
      framework,
      originalLevel: support.level,
      suggestion: null,
      alternatives: []
    };
  }

  // Build alternatives list
  const alternatives = [];

  // Find frameworks with full support for this pattern
  const patternEntry = COMPATIBILITY_MATRIX[pattern.toLowerCase().trim()];
  if (patternEntry) {
    for (const [fw, support] of Object.entries(patternEntry)) {
      if (support.level === SUPPORT_LEVELS.FULL) {
        alternatives.push({
          framework: fw,
          notes: support.notes
        });
      }
    }
  }

  // Fallback suggestions by pattern category
  const categoryFallbacks = {
    visual: 'Consider using SVG or pre-rendered images for complex visual effects',
    interaction: 'Implement using framework-native gesture/event handlers',
    content: 'Consider converting to supported format or using third-party library',
    advanced: 'May require custom implementation or simplified design'
  };

  const category = getCategoryForPattern(pattern);

  return {
    needed: true,
    pattern,
    framework,
    originalLevel: support.level,
    suggestion: support.fallback || categoryFallbacks[category] || 'Custom implementation required',
    notes: support.notes,
    alternatives: alternatives.slice(0, 3) // Top 3 alternatives
  };
}

/**
 * Check multiple patterns at once
 * @param {string[]} patterns - Array of pattern names
 * @param {string} framework - Target framework
 * @returns {Object} Batch check results with summary
 */
function checkPatternsSupport(patterns, framework) {
  if (!Array.isArray(patterns)) {
    return {
      error: 'INVALID_INPUT',
      message: 'Patterns must be an array',
      results: []
    };
  }

  const results = patterns.map(pattern => ({
    pattern,
    ...checkPatternSupport(pattern, framework)
  }));

  // Calculate summary
  const summary = {
    total: results.length,
    full: results.filter(r => r.level === SUPPORT_LEVELS.FULL).length,
    partial: results.filter(r => r.level === SUPPORT_LEVELS.PARTIAL).length,
    none: results.filter(r => r.level === SUPPORT_LEVELS.NONE).length,
    experimental: results.filter(r => r.level === SUPPORT_LEVELS.EXPERIMENTAL).length
  };

  // Calculate overall compatibility score (0-100)
  const weights = {
    [SUPPORT_LEVELS.FULL]: 100,
    [SUPPORT_LEVELS.PARTIAL]: 60,
    [SUPPORT_LEVELS.EXPERIMENTAL]: 30,
    [SUPPORT_LEVELS.NONE]: 0
  };

  const totalScore = results.reduce((acc, r) => acc + (weights[r.level] || 0), 0);
  summary.score = Math.round(totalScore / results.length);

  return {
    error: null,
    framework,
    results,
    summary
  };
}

// =============================================================================
// REPORT GENERATION
// =============================================================================

/**
 * Generate a comprehensive compatibility report for patterns against a framework
 * @param {string[]} patterns - Array of pattern names to analyze
 * @param {string} framework - Target framework
 * @param {Object} options - Report options
 * @param {boolean} options.includeAlternatives - Include framework alternatives (default: true)
 * @param {boolean} options.includeFallbacks - Include fallback suggestions (default: true)
 * @param {boolean} options.groupByCategory - Group patterns by category (default: true)
 * @returns {Object} Comprehensive compatibility report
 */
function generateCompatibilityReport(patterns, framework, options = {}) {
  const {
    includeAlternatives = true,
    includeFallbacks = true,
    groupByCategory = true
  } = options;

  // Validate inputs
  if (!Array.isArray(patterns) || patterns.length === 0) {
    return {
      error: 'INVALID_INPUT',
      message: 'Patterns must be a non-empty array',
      report: null
    };
  }

  if (!framework || typeof framework !== 'string') {
    return {
      error: 'INVALID_FRAMEWORK',
      message: 'Framework must be a non-empty string',
      report: null
    };
  }

  const normalizedFramework = framework.toLowerCase().trim();
  const timestamp = new Date().toISOString();

  // Build base analysis using checkPatternsSupport
  const batchResult = checkPatternsSupport(patterns, normalizedFramework);

  // Separate results by support level
  const supported = [];
  const partiallySupported = [];
  const unsupported = [];
  const experimental = [];

  for (const result of batchResult.results) {
    const entry = {
      pattern: result.pattern,
      category: getCategoryForPattern(result.pattern),
      notes: result.notes
    };

    if (includeFallbacks && result.fallback) {
      entry.fallback = result.fallback;
    }

    if (includeAlternatives && result.level !== SUPPORT_LEVELS.FULL) {
      const fallbackInfo = suggestFallback(result.pattern, normalizedFramework);
      if (fallbackInfo.alternatives && fallbackInfo.alternatives.length > 0) {
        entry.alternatives = fallbackInfo.alternatives;
      }
    }

    switch (result.level) {
      case SUPPORT_LEVELS.FULL:
        supported.push(entry);
        break;
      case SUPPORT_LEVELS.PARTIAL:
        partiallySupported.push(entry);
        break;
      case SUPPORT_LEVELS.NONE:
        unsupported.push(entry);
        break;
      case SUPPORT_LEVELS.EXPERIMENTAL:
        experimental.push(entry);
        break;
    }
  }

  // Optionally group by category
  let groupedResults = null;
  if (groupByCategory) {
    groupedResults = {};
    for (const categoryKey of Object.keys(PATTERN_CATEGORIES)) {
      const categoryPatterns = batchResult.results.filter(
        r => getCategoryForPattern(r.pattern) === categoryKey
      );
      if (categoryPatterns.length > 0) {
        groupedResults[categoryKey] = {
          name: PATTERN_CATEGORIES[categoryKey].name,
          patterns: categoryPatterns.map(r => ({
            pattern: r.pattern,
            level: r.level,
            notes: r.notes,
            fallback: r.fallback || null
          }))
        };
      }
    }
  }

  // Identify critical issues (unsupported patterns that may break design)
  const criticalIssues = unsupported.filter(p => {
    // Critical patterns that often break layouts or visual appearance
    const criticalPatterns = [
      'auto-layout', 'constraints', 'grid-layout',
      'linear-gradient', 'radial-gradient', 'blend-mode',
      'nested-components', 'component-props'
    ];
    return criticalPatterns.includes(p.pattern);
  });

  // Generate recommendations
  const recommendations = [];

  if (unsupported.length > 0) {
    recommendations.push({
      priority: 'high',
      message: `${unsupported.length} pattern(s) not supported. Consider simplifying design or using fallbacks.`,
      patterns: unsupported.map(p => p.pattern)
    });
  }

  if (partiallySupported.length > 0) {
    recommendations.push({
      priority: 'medium',
      message: `${partiallySupported.length} pattern(s) have partial support. Review implementation notes.`,
      patterns: partiallySupported.map(p => p.pattern)
    });
  }

  if (experimental.length > 0) {
    recommendations.push({
      priority: 'low',
      message: `${experimental.length} pattern(s) have experimental support. Test thoroughly.`,
      patterns: experimental.map(p => p.pattern)
    });
  }

  if (batchResult.summary.score >= 80) {
    recommendations.push({
      priority: 'info',
      message: 'High compatibility score. Design should transform well.',
      patterns: []
    });
  } else if (batchResult.summary.score < 50) {
    recommendations.push({
      priority: 'high',
      message: 'Low compatibility score. Consider reviewing design patterns or choosing a different framework.',
      patterns: []
    });
  }

  // Build final report
  const report = {
    meta: {
      generatedAt: timestamp,
      framework: normalizedFramework,
      patternsAnalyzed: patterns.length,
      version: '1.0.0'
    },
    summary: {
      ...batchResult.summary,
      compatibilityRating: getCompatibilityRating(batchResult.summary.score)
    },
    supported,
    partiallySupported,
    unsupported,
    experimental,
    criticalIssues,
    recommendations,
    ...(groupByCategory && { byCategory: groupedResults })
  };

  return {
    error: null,
    report
  };
}

/**
 * Convert compatibility score to human-readable rating
 * @param {number} score - Compatibility score (0-100)
 * @returns {string} Rating string
 */
function getCompatibilityRating(score) {
  if (score >= 90) return 'Excellent';
  if (score >= 75) return 'Good';
  if (score >= 60) return 'Fair';
  if (score >= 40) return 'Poor';
  return 'Critical';
}

/**
 * Format compatibility report as Markdown
 * @param {Object} report - Report object from generateCompatibilityReport
 * @returns {string} Markdown formatted report
 */
function formatReportAsMarkdown(report) {
  if (!report || !report.report) {
    return '# Error\n\nNo valid report data provided.';
  }

  const r = report.report;
  const lines = [];

  // Header
  lines.push(`# Pattern Compatibility Report`);
  lines.push('');
  lines.push(`**Framework:** ${r.meta.framework}`);
  lines.push(`**Generated:** ${r.meta.generatedAt}`);
  lines.push(`**Patterns Analyzed:** ${r.meta.patternsAnalyzed}`);
  lines.push('');

  // Summary
  lines.push('## Summary');
  lines.push('');
  lines.push(`| Metric | Value |`);
  lines.push(`|--------|-------|`);
  lines.push(`| Compatibility Score | ${r.summary.score}/100 (${r.summary.compatibilityRating}) |`);
  lines.push(`| Fully Supported | ${r.summary.full} |`);
  lines.push(`| Partially Supported | ${r.summary.partial} |`);
  lines.push(`| Unsupported | ${r.summary.none} |`);
  lines.push(`| Experimental | ${r.summary.experimental} |`);
  lines.push('');

  // Visual score bar
  const filledBlocks = Math.round(r.summary.score / 10);
  const scoreBar = '█'.repeat(filledBlocks) + '░'.repeat(10 - filledBlocks);
  lines.push(`**Score:** \`[${scoreBar}]\` ${r.summary.score}%`);
  lines.push('');

  // Critical Issues
  if (r.criticalIssues && r.criticalIssues.length > 0) {
    lines.push('## ⚠️ Critical Issues');
    lines.push('');
    lines.push('These patterns are not supported and may break your design:');
    lines.push('');
    for (const issue of r.criticalIssues) {
      lines.push(`- **${issue.pattern}**${issue.category ? ` (${issue.category})` : ''}`);
      if (issue.notes) {
        lines.push(`  - ${issue.notes}`);
      }
      if (issue.fallback) {
        lines.push(`  - *Fallback:* ${issue.fallback}`);
      }
    }
    lines.push('');
  }

  // Recommendations
  if (r.recommendations && r.recommendations.length > 0) {
    lines.push('## Recommendations');
    lines.push('');
    const priorityIcons = { high: '🔴', medium: '🟡', low: '🟢', info: 'ℹ️' };
    for (const rec of r.recommendations) {
      lines.push(`${priorityIcons[rec.priority] || '•'} ${rec.message}`);
      if (rec.patterns && rec.patterns.length > 0 && rec.patterns.length <= 5) {
        lines.push(`  - Patterns: ${rec.patterns.join(', ')}`);
      }
    }
    lines.push('');
  }

  // Supported Patterns
  if (r.supported && r.supported.length > 0) {
    lines.push('## ✅ Fully Supported');
    lines.push('');
    lines.push('| Pattern | Category | Notes |');
    lines.push('|---------|----------|-------|');
    for (const p of r.supported) {
      lines.push(`| ${p.pattern} | ${p.category || '-'} | ${p.notes || '-'} |`);
    }
    lines.push('');
  }

  // Partially Supported Patterns
  if (r.partiallySupported && r.partiallySupported.length > 0) {
    lines.push('## 🟡 Partially Supported');
    lines.push('');
    for (const p of r.partiallySupported) {
      lines.push(`### ${p.pattern}`);
      lines.push(`- **Category:** ${p.category || 'Unknown'}`);
      lines.push(`- **Notes:** ${p.notes || 'No notes'}`);
      if (p.fallback) {
        lines.push(`- **Fallback:** ${p.fallback}`);
      }
      if (p.alternatives && p.alternatives.length > 0) {
        lines.push(`- **Frameworks with full support:** ${p.alternatives.map(a => a.framework).join(', ')}`);
      }
      lines.push('');
    }
  }

  // Unsupported Patterns
  if (r.unsupported && r.unsupported.length > 0) {
    lines.push('## ❌ Unsupported');
    lines.push('');
    for (const p of r.unsupported) {
      lines.push(`### ${p.pattern}`);
      lines.push(`- **Category:** ${p.category || 'Unknown'}`);
      lines.push(`- **Notes:** ${p.notes || 'No notes'}`);
      if (p.fallback) {
        lines.push(`- **Suggested Fallback:** ${p.fallback}`);
      }
      if (p.alternatives && p.alternatives.length > 0) {
        lines.push(`- **Consider these frameworks:** ${p.alternatives.map(a => `${a.framework} (${a.notes})`).join('; ')}`);
      }
      lines.push('');
    }
  }

  // Experimental Patterns
  if (r.experimental && r.experimental.length > 0) {
    lines.push('## 🧪 Experimental');
    lines.push('');
    lines.push('These patterns have uncertain support and require testing:');
    lines.push('');
    for (const p of r.experimental) {
      lines.push(`- **${p.pattern}**: ${p.notes || 'No notes'}`);
      if (p.fallback) {
        lines.push(`  - Fallback: ${p.fallback}`);
      }
    }
    lines.push('');
  }

  // By Category (if available)
  if (r.byCategory) {
    lines.push('## Patterns by Category');
    lines.push('');
    for (const [categoryKey, category] of Object.entries(r.byCategory)) {
      lines.push(`### ${category.name}`);
      lines.push('');
      lines.push('| Pattern | Support | Notes |');
      lines.push('|---------|---------|-------|');
      for (const p of category.patterns) {
        const levelIcon = {
          full: '✅',
          partial: '🟡',
          none: '❌',
          experimental: '🧪'
        }[p.level] || '?';
        lines.push(`| ${p.pattern} | ${levelIcon} ${p.level} | ${p.notes || '-'} |`);
      }
      lines.push('');
    }
  }

  // Footer
  lines.push('---');
  lines.push(`*Report generated by Pattern Compatibility Matrix v${r.meta.version}*`);

  return lines.join('\n');
}

/**
 * Format compatibility report as JSON string
 * @param {Object} report - Report object from generateCompatibilityReport
 * @param {boolean} pretty - Pretty print with indentation (default: true)
 * @returns {string} JSON formatted report
 */
function formatReportAsJSON(report, pretty = true) {
  if (!report) {
    return JSON.stringify({ error: 'No report data provided' }, null, pretty ? 2 : 0);
  }
  return JSON.stringify(report, null, pretty ? 2 : 0);
}

/**
 * Generate a compact summary report (useful for CLI output)
 * @param {string[]} patterns - Array of pattern names
 * @param {string} framework - Target framework
 * @returns {string} Compact text summary
 */
function generateCompactSummary(patterns, framework) {
  const result = generateCompatibilityReport(patterns, framework, {
    includeAlternatives: false,
    includeFallbacks: false,
    groupByCategory: false
  });

  if (result.error) {
    return `Error: ${result.message}`;
  }

  const r = result.report;
  const lines = [];

  lines.push(`Framework: ${r.meta.framework}`);
  lines.push(`Score: ${r.summary.score}/100 (${r.summary.compatibilityRating})`);
  lines.push(`Patterns: ${r.summary.full} full, ${r.summary.partial} partial, ${r.summary.none} none, ${r.summary.experimental} experimental`);

  if (r.unsupported.length > 0) {
    lines.push(`\nUnsupported: ${r.unsupported.map(p => p.pattern).join(', ')}`);
  }

  return lines.join('\n');
}

// =============================================================================
// UNIT TEST STUBS
// =============================================================================

/*
 * Test: generateCompatibilityReport
 * ---------------------------------
 * describe('generateCompatibilityReport', () => {
 *   it('should return error for empty patterns array', () => {
 *     const result = generateCompatibilityReport([], 'react');
 *     expect(result.error).toBe('INVALID_INPUT');
 *   });
 *
 *   it('should return error for invalid framework', () => {
 *     const result = generateCompatibilityReport(['auto-layout'], '');
 *     expect(result.error).toBe('INVALID_FRAMEWORK');
 *   });
 *
 *   it('should generate valid report for known patterns', () => {
 *     const result = generateCompatibilityReport(
 *       ['auto-layout', 'linear-gradient', 'hover-state'],
 *       'react'
 *     );
 *     expect(result.error).toBeNull();
 *     expect(result.report.meta.framework).toBe('react');
 *     expect(result.report.summary.total).toBe(3);
 *   });
 *
 *   it('should correctly categorize patterns by support level', () => {
 *     const result = generateCompatibilityReport(
 *       ['auto-layout', 'radial-gradient', 'hover-state'],
 *       'react-native'
 *     );
 *     expect(result.report.supported.length).toBeGreaterThan(0);
 *     expect(result.report.unsupported.length).toBeGreaterThan(0);
 *   });
 *
 *   it('should include alternatives when option enabled', () => {
 *     const result = generateCompatibilityReport(
 *       ['radial-gradient'],
 *       'react-native',
 *       { includeAlternatives: true }
 *     );
 *     expect(result.report.unsupported[0].alternatives).toBeDefined();
 *   });
 *
 *   it('should group by category when option enabled', () => {
 *     const result = generateCompatibilityReport(
 *       getAllPatterns(),
 *       'react',
 *       { groupByCategory: true }
 *     );
 *     expect(result.report.byCategory).toBeDefined();
 *     expect(result.report.byCategory.layout).toBeDefined();
 *   });
 * });
 *
 * Test: formatReportAsMarkdown
 * ----------------------------
 * describe('formatReportAsMarkdown', () => {
 *   it('should return error message for null input', () => {
 *     const md = formatReportAsMarkdown(null);
 *     expect(md).toContain('Error');
 *   });
 *
 *   it('should generate valid markdown with headers', () => {
 *     const result = generateCompatibilityReport(['auto-layout'], 'react');
 *     const md = formatReportAsMarkdown(result);
 *     expect(md).toContain('# Pattern Compatibility Report');
 *     expect(md).toContain('## Summary');
 *   });
 *
 *   it('should include score visualization', () => {
 *     const result = generateCompatibilityReport(['auto-layout'], 'react');
 *     const md = formatReportAsMarkdown(result);
 *     expect(md).toMatch(/\[█+░*\]/);
 *   });
 * });
 *
 * Test: formatReportAsJSON
 * ------------------------
 * describe('formatReportAsJSON', () => {
 *   it('should return valid JSON string', () => {
 *     const result = generateCompatibilityReport(['auto-layout'], 'react');
 *     const json = formatReportAsJSON(result);
 *     expect(() => JSON.parse(json)).not.toThrow();
 *   });
 *
 *   it('should pretty print by default', () => {
 *     const result = generateCompatibilityReport(['auto-layout'], 'react');
 *     const json = formatReportAsJSON(result);
 *     expect(json).toContain('\n');
 *   });
 *
 *   it('should compact when pretty=false', () => {
 *     const result = generateCompatibilityReport(['auto-layout'], 'react');
 *     const json = formatReportAsJSON(result, false);
 *     expect(json).not.toContain('\n');
 *   });
 * });
 *
 * Test: generateCompactSummary
 * ---------------------------
 * describe('generateCompactSummary', () => {
 *   it('should generate compact text output', () => {
 *     const summary = generateCompactSummary(['auto-layout', 'hover-state'], 'react-native');
 *     expect(summary).toContain('Framework: react-native');
 *     expect(summary).toContain('Score:');
 *   });
 * });
 */

// =============================================================================
// EXPORTS
// =============================================================================

module.exports = {
  // Constants
  FRAMEWORK_LIST,
  SUPPORT_LEVELS,
  PATTERN_CATEGORIES,
  COMPATIBILITY_MATRIX,
  // Utility functions
  getAllPatterns,
  getCategoryForPattern,
  // Query API
  checkPatternSupport,
  getFrameworkLimitations,
  suggestFallback,
  checkPatternsSupport,
  // Report generation
  generateCompatibilityReport,
  formatReportAsMarkdown,
  formatReportAsJSON,
  generateCompactSummary,
  getCompatibilityRating
};
