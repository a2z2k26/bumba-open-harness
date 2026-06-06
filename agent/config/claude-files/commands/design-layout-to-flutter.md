---
name: design-layout-to-flutter
description: Transform Figma layouts to Flutter widgets with Column/Row, SizedBox spacing, and const constructors
allowed-tools: Read, Write, Bash
instructions: design-layout-to-flutter-principles.md
---

# design-layout-to-flutter - Transform Figma Layouts to Flutter Widgets

Generate production-ready Flutter/Dart widgets from extracted Figma layout data.

**Design Principles**: This skill follows Flutter-specific layout design principles including Material Design 4dp grid, Column/Row patterns, const constructors, ListView performance, and touch targets. See `~/.claude/instructions/design-layout-to-flutter-principles.md` for complete guidelines.

## Purpose

Convert Figma layouts into Flutter widgets with:
- Column and Row widgets
- SizedBox for spacing
- EdgeInsets for padding
- Design system component imports
- Production-ready Dart code
- .dart output files

## Prerequisites

- Layout data extracted from Figma (`.design/layouts/`)
- Component registry populated (`.design/componentRegistry.json`)
- Design system components available for imports

## Usage

### Transform Single Layout

```bash
node ~/.claude/shared-modules/design-system/layout-to-flutter-transformer.js \
  --layout=PricingPage
```

### Transform All Layouts

```bash
for layout in .design/layouts/*.json; do
  node ~/.claude/shared-modules/design-system/layout-to-flutter-transformer.js \
    --layout=$(basename "$layout" .json)
done
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--layout` | (required) | Layout name or file path |
| `--output-dir` | `.design/extracted-code/flutter/layouts` | Output directory |

## Output

### File Structure

```
.design/extracted-code/flutter/layouts/
├── pricing_page.dart
├── homepage.dart
└── dashboard_layout.dart
```

### Generated Widget Example

```dart
/**
 * PricingPage Layout Widget
 * Generated from Figma layout extraction
 *
 * This widget uses transformed design system components.
 * Generated: 2026-01-08T...
 */

import 'package:flutter/material.dart';

class PricingPage extends StatelessWidget {
  const PricingPage({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.symmetric(vertical: 64, horizontal: 32),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          PricingTier(),
          SizedBox(height: 32),
          PricingTier(),
          SizedBox(height: 32),
          PricingTier()
        ]
      )
    );
  }
}
```

## Key Features

### Flutter Layout Widgets

Figma auto-layout properties convert to Flutter widgets:

```dart
// Vertical layout → Column
Column(
  mainAxisAlignment: MainAxisAlignment.center,
  crossAxisAlignment: CrossAxisAlignment.start,
  children: [
    Text('Title'),
    SizedBox(height: 16),
    Button()
  ]
)

// Horizontal layout → Row
Row(
  mainAxisAlignment: MainAxisAlignment.spaceBetween,
  crossAxisAlignment: CrossAxisAlignment.center,
  children: [
    Icon(Icons.menu),
    SizedBox(width: 24),
    Text('Menu')
  ]
)
```

### Spacing with SizedBox

```dart
// Vertical spacing
SizedBox(height: 24)

// Horizontal spacing
SizedBox(width: 16)

// Both dimensions
SizedBox(width: 200, height: 100)
```

### Padding with EdgeInsets

```dart
// Uniform padding
Padding(
  padding: EdgeInsets.all(16),
  child: ...
)

// Symmetric padding
Padding(
  padding: EdgeInsets.symmetric(vertical: 24, horizontal: 16),
  child: ...
)

// Individual edges
Padding(
  padding: EdgeInsets.only(top: 24, left: 16, bottom: 24, right: 16),
  child: ...
)
```

### Alignment Options

```dart
// MainAxisAlignment (primary axis)
MainAxisAlignment.start
MainAxisAlignment.center
MainAxisAlignment.end
MainAxisAlignment.spaceBetween

// CrossAxisAlignment (cross axis)
CrossAxisAlignment.start
CrossAxisAlignment.center
CrossAxisAlignment.end
CrossAxisAlignment.stretch
```

### Component References

```dart
// Component imports (add manually)
// import 'pricing_tier.dart';
// import 'button.dart';

// Usage with props
PricingTier(primary: true)
Button(text: 'Get Started')
```

## Differences from Other Formats

| Aspect | HTML | React | SwiftUI | Flutter |
|--------|------|-------|---------|---------|
| Container | `<div>` | `<div>` | `VStack/HStack` | `Column/Row` |
| Spacing | `gap` | `gap` | `spacing:` | `SizedBox` |
| Padding | `padding` | `padding` | `.padding()` | `Padding` widget |
| Platform | Web | Web | iOS/macOS | Cross-platform |

## Workflow

### 1. Extract Layout from Figma

```
Figma Plugin → Extract Layout
→ Saves to .design/layouts/pricing-page.json
```

### 2. Transform to Flutter

```bash
node ~/.claude/shared-modules/design-system/layout-to-flutter-transformer.js \
  --layout=pricing-page
```

### 3. Import in Flutter App

```dart
import 'package:myapp/layouts/pricing_page.dart';

class MyApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      home: Scaffold(
        body: PricingPage(),
      ),
    );
  }
}
```

### 4. Customize as Needed

- Add state management with `StatefulWidget`
- Connect to providers or BLoC
- Add gesture detectors
- Apply theme data
- Add animations

## Component Resolution

```json
{
  "type": "INSTANCE",
  "componentRef": {
    "name": "Button",
    "props": {
      "primary": true,
      "text": "Get Started"
    }
  }
}
```

Becomes:

```dart
Button(primary: true, text: 'Get Started')
```

## Programmatic API

### transformLayoutToFlutter

```javascript
const { transformLayoutToFlutter } = require('layout-to-flutter-transformer');

const result = await transformLayoutToFlutter(layoutData, {
  outputDir: '.design/extracted-code/flutter/layouts'
});

// result = {
//   success: true,
//   layoutName: 'PricingPage',
//   widgetName: 'PricingPage',
//   outputPath: '.design/extracted-code/flutter/layouts/pricing_page.dart',
//   fileExtension: 'dart',
//   dependencies: ['Button', 'Card', 'PricingTier']
// }
```

## Troubleshooting

### Missing Component Imports

**Problem**: References to undefined components

**Solution**: Add imports manually:

```dart
import 'package:myapp/components/pricing_tier.dart';
import 'package:myapp/components/button.dart';
```

### Overflow Issues

**Problem**: Layout overflows on small screens

**Solution**: Wrap in `SingleChildScrollView`:

```dart
SingleChildScrollView(
  child: PricingPage(),
)
```

### Spacing Issues

**Problem**: Spacing doesn't match Figma

**Solution**: Adjust `SizedBox` heights/widths:

```dart
SizedBox(height: 32)  // Increase/decrease as needed
```

## Flutter Best Practices & Edge Cases

### Use const Constructors for Performance 🚀

[const widgets are reused instead of rebuilt](https://docs.flutter.dev/perf/best-practices), providing significant performance gains:

```dart
// ❌ Without const: Rebuilds every time
Column(
  children: [
    Text('Title'),
    Button(),
  ]
)

// ✅ With const: Built once, reused
const Column(
  children: [
    Text('Title'),
    Button(),
  ]
)
```

**Rule**: [Mark widgets with const whenever possible](https://dev.to/pedromassango/flutter-performance-tips-1-const-constructors-4j41). Enable `prefer_const_constructors` linter rule to catch missed opportunities.

**Cascade Effect**: [When the top widget uses const, inner widgets automatically use const](https://medium.com/@calvin.kamardi/why-use-const-in-flutter-dart-34f3496baaf9) - no need to add const everywhere.

### Alignment Edge Cases

[Baseline alignment produces better visual results](https://api.flutter.dev/flutter/rendering/CrossAxisAlignment.html) for text with different font metrics:

```dart
// For text with different sizes
Row(
  crossAxisAlignment: CrossAxisAlignment.baseline,
  textBaseline: TextBaseline.alphabetic,
  children: [
    Text('Large', style: TextStyle(fontSize: 24)),
    Text('Small', style: TextStyle(fontSize: 12)),
  ]
)
```

**BoxConstraints Error**: [CrossAxisAlignment.stretch requires constrained width/height](https://docs.flutter.dev/ui/layout) from parent:

```dart
// ❌ Error: Parent has no constraints
Column(
  crossAxisAlignment: CrossAxisAlignment.stretch,
  children: [...],
)

// ✅ Works: Parent provides constraints
SizedBox(
  width: 300,
  child: Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [...],
  ),
)
```

### Overflow Handling

[Yellow/black stripes indicate overflow](https://docs.flutter.dev/ui/layout):

```dart
// ❌ Overflows on small screens
Column(
  children: [
    LargeWidget(),
    AnotherLargeWidget(),
  ]
)

// ✅ Scrolls when content exceeds screen
SingleChildScrollView(
  child: Column(
    children: [
      LargeWidget(),
      AnotherLargeWidget(),
    ]
  ),
)
```

### ListView vs Column for Lists

[Use ListView for better performance](https://docs.flutter.dev/ui/layout) with many items:

```dart
// ❌ Poor performance with many items
SingleChildScrollView(
  child: Column(
    children: List.generate(1000, (i) => Item(i)),
  ),
)

// ✅ Lazy loading, better performance
ListView.builder(
  itemCount: 1000,
  itemBuilder: (context, index) => Item(index),
)
```

**Rule**: Use `Column` for small, known sets of children. Use `ListView.builder` for large or dynamic lists.

### TextDirection Dependency

[CrossAxisAlignment.start requires TextDirection](https://api.flutter.dev/flutter/rendering/CrossAxisAlignment.html):

```dart
// Wrap in Directionality if TextDirection not available
Directionality(
  textDirection: TextDirection.ltr,
  child: Row(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [...],
  ),
)
```

### Common Mistakes

1. **Forgetting const**: [Widgets without const rebuild unnecessarily](https://medium.com/@Ruben.Aster/better-performance-with-const-widgets-in-flutter-50d60d9fe482), wasting CPU and causing jank

2. **setState() Rebuilds**: [const widgets won't rebuild during setState()](https://www.dhiwise.com/post/why-flutter-prefer-const-with-constant-constructor) - use for static content

3. **Lazy Builder Timing**: [Use lazy builders for large lists](https://docs.flutter.dev/perf/best-practices) - only visible portions built at startup

## Related Commands

- `/design-extract` - Extract components and layouts from Figma
- `/design-layout-to-html` - Generate HTML reference files
- `/design-layout-to-jsx` - Generate React/JSX components
- `/design-transform-flutter` - Transform individual components

## Notes

- Generated widgets are production-ready but should be reviewed
- File names follow Dart conventions (snake_case)
- Use Flutter DevTools for layout debugging
- Test on multiple screen sizes and orientations
- Consider responsive design for tablets
- **Always use const constructors** when possible for performance

## References

- [Flutter Performance Best Practices](https://docs.flutter.dev/perf/best-practices)
- [const Constructors Performance](https://dev.to/pedromassango/flutter-performance-tips-1-const-constructors-4j41)
- [Flutter Layout Fundamentals](https://docs.flutter.dev/ui/layout)
- [CrossAxisAlignment API](https://api.flutter.dev/flutter/rendering/CrossAxisAlignment.html)
