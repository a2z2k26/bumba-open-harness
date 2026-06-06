---
name: design-layout-to-swiftui
description: Transform Figma layouts to SwiftUI views with VStack/HStack, spacing, and modifiers
allowed-tools: Read, Write, Bash
instructions: design-layout-to-swiftui-principles.md
---

# design-layout-to-swiftui - Transform Figma Layouts to SwiftUI Views

Generate production-ready SwiftUI views from extracted Figma layout data.

**Design Principles**: This skill follows SwiftUI-specific layout design principles including 8-point grid, safe areas, size classes, modifier order, and touch targets. See `~/.claude/instructions/design-layout-to-swiftui-principles.md` for complete guidelines.

## Purpose

Convert Figma layouts into native SwiftUI code with:
- VStack and HStack containers
- SwiftUI spacing and alignment
- SwiftUI padding modifiers
- Design system component imports
- Production-ready Swift code
- .swift output files

## Prerequisites

- Layout data extracted from Figma (`.design/layouts/`)
- Component registry populated (`.design/componentRegistry.json`)
- Design system components available for imports

## Usage

### Transform Single Layout

```bash
node ~/.claude/shared-modules/design-system/layout-to-swiftui-transformer.js \
  --layout=PricingPage
```

### Transform All Layouts

```bash
for layout in .design/layouts/*.json; do
  node ~/.claude/shared-modules/design-system/layout-to-swiftui-transformer.js \
    --layout=$(basename "$layout" .json)
done
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--layout` | (required) | Layout name or file path |
| `--output-dir` | `.design/extracted-code/swiftui/layouts` | Output directory |

## Output

### File Structure

```
.design/extracted-code/swiftui/layouts/
├── PricingPage.swift
├── Homepage.swift
└── DashboardLayout.swift
```

### Generated View Example

```swift
/**
 * PricingPage Layout View
 * Generated from Figma layout extraction
 *
 * This view uses transformed design system components.
 * Generated: 2026-01-08T...
 */

import SwiftUI

struct PricingPage: View {
    var body: some View {
        VStack(alignment: .center, spacing: 32) {
            PricingTier()
            PricingTier()
            PricingTier()
        }
        .padding(.vertical, 64)
        .padding(.horizontal, 32)
    }
}

#Preview {
    PricingPage()
}
```

## Key Features

### SwiftUI Stacks

Figma auto-layout properties convert to SwiftUI stacks:

```swift
// Vertical layout → VStack
VStack(alignment: .center, spacing: 16) {
    Text("Title")
    Button("Action")
}

// Horizontal layout → HStack
HStack(alignment: .center, spacing: 24) {
    Image("icon")
    Text("Label")
}
```

### Spacing and Alignment

```swift
// Gap between items
VStack(spacing: 24) { ... }

// Alignment
VStack(alignment: .leading) { ... }
HStack(alignment: .top) { ... }
```

### Padding Modifiers

```swift
// Uniform padding
.padding(16)

// Edge-specific padding
.padding([.vertical, 48])
.padding(.horizontal, 32)

// Individual edges
.padding(.top, 24)
.padding(.leading, 16)
```

### Component References

Nested components are imported and used:

```swift
// Component imports (add manually)
// import PricingTier
// import Button
// import Card

// Usage
VStack {
    PricingTier()
    Button()
    Card()
}
```

## Differences from Other Formats

| Aspect | HTML | React/JSX | SwiftUI |
|--------|------|-----------|---------|
| Container | `<div>` | `<div>` | `VStack/HStack` |
| Styling | CSS | Inline styles | Modifiers |
| Spacing | `gap` | `gap` | `spacing:` parameter |
| Padding | `padding` | `padding` | `.padding()` modifier |
| Platform | Web | Web | iOS/macOS |

## Workflow

### 1. Extract Layout from Figma

Use the Figma plugin to extract layout data:

```
Figma Plugin → Extract Layout
→ Saves to .design/layouts/pricing-page.json
```

### 2. Transform to SwiftUI

```bash
node ~/.claude/shared-modules/design-system/layout-to-swiftui-transformer.js \
  --layout=pricing-page
```

### 3. Import in Xcode Project

```swift
import SwiftUI

struct ContentView: View {
    var body: some View {
        PricingPage()
    }
}
```

### 4. Customize as Needed

The generated view is a starting point. You can:
- Add state management with `@State`, `@Binding`
- Add custom props/parameters
- Connect to view models
- Add animations
- Handle user interactions

## Component Resolution

The transformer resolves component references from the registry:

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

```swift
Button(primary: true, text: "Get Started")
```

## Programmatic API

### transformLayoutToSwiftUI

```javascript
const { transformLayoutToSwiftUI } = require('layout-to-swiftui-transformer');

const result = await transformLayoutToSwiftUI(layoutData, {
  outputDir: '.design/extracted-code/swiftui/layouts'
});

// result = {
//   success: true,
//   layoutName: 'PricingPage',
//   viewName: 'PricingPage',
//   outputPath: '.design/extracted-code/swiftui/layouts/PricingPage.swift',
//   fileExtension: 'swift',
//   dependencies: ['Button', 'Card', 'PricingTier']
// }
```

### transformLayoutFile

```javascript
const { transformLayoutFile } = require('layout-to-swiftui-transformer');

const result = await transformLayoutFile(
  '.design/layouts/pricing-page.json',
  {}
);
```

## Troubleshooting

### Missing Component Imports

**Problem**: Generated SwiftUI references components that don't exist

**Solution**: Transform missing components first or add imports manually

```swift
// Add these imports at the top
import PricingTier
import Button
import Card
```

### Alignment Issues

**Problem**: Alignment doesn't match Figma exactly

**Solution**: Adjust alignment parameters:

```swift
// For Column (VStack)
VStack(alignment: .leading)  // Left align
VStack(alignment: .center)   // Center align
VStack(alignment: .trailing) // Right align

// For Row (HStack)
HStack(alignment: .top)      // Top align
HStack(alignment: .center)   // Center align
HStack(alignment: .bottom)   // Bottom align
```

### Spacing Issues

**Problem**: Spacing between items doesn't match Figma

**Solution**: Adjust spacing value:

```swift
VStack(spacing: 24) { ... }  // 24pt gap between items
```

## SwiftUI Best Practices & Edge Cases

### Modifier Order Matters ⚠️

[SwiftUI renders your view after every single modifier](https://www.hackingwithswift.com/books/ios-swiftui/why-modifier-order-matters), with each modifier wrapping the previous view. Order affects the final result:

```swift
// ❌ Wrong: Small red background around text only
Text("Hello")
    .background(.red)
    .frame(width: 200, height: 200)

// ✅ Correct: Full 200x200 red background
Text("Hello")
    .frame(width: 200, height: 200)
    .background(.red)
```

**Rule**: Apply sizing modifiers (`.frame()`) before visual modifiers (`.background()`, `.border()`).

### Alignment Edge Cases

[Alignment guides can be confusing](https://www.swiftuifieldguide.com/layout/alignment/) when containers are "tight" (sized to content):

```swift
// ❌ No effect: Container is tight, no extra space to align
Text("Hello")
    .frame(alignment: .leading)

// ✅ Works: Container has extra space
Text("Hello")
    .frame(width: 200, alignment: .leading)
```

**Cross-axis alignment only works when there's extra space** to distribute. Use [`.frame()` with explicit dimensions](https://www.swiftbysundell.com/articles/swiftui-frame-modifier/) or flexible containers.

### Spacer vs Spacing

```swift
// Use spacing: for uniform gaps between all items
VStack(spacing: 16) {
    Text("Item 1")
    Text("Item 2")
    Text("Item 3")
}

// Use Spacer(): for flexible space in specific locations
VStack {
    Text("Top")
    Spacer()  // Pushes to top/bottom
    Text("Bottom")
}
```

**Convention**: [Use spacing parameter](https://medium.com/ios-lab/swiftui-layout-basics-mastering-vstack-hstack-and-zstack-c2a5b209e500) for lists/repeating items. Use `Spacer()` for one-off flexible spacing.

### Responsive Layout Switching

For adaptive layouts, [use size classes or iOS 16+ Layout protocol](https://www.swiftbysundell.com/articles/switching-between-swiftui-hstack-vstack/):

```swift
// iOS 16+: Smooth animated transitions
@Environment(\.horizontalSizeClass) var sizeClass

var body: some View {
    let layout = sizeClass == .compact ? AnyLayout(VStackLayout()) : AnyLayout(HStackLayout())

    layout {
        ProfileImage()
        UserInfo()
    }
}
```

### Nesting Stacks

[Nest stacks freely](https://medium.com/swift-pal/swiftui-layout-guide-vstack-hstack-zstack-grids-explained-2025-edition-285fb89b5de5) without performance concerns - SwiftUI handles deep hierarchies efficiently:

```swift
VStack {
    HStack {
        VStack {
            Text("Title")
            Text("Subtitle")
        }
        Spacer()
        Image("icon")
    }
}
```

### Common Mistakes

1. **Baseline Alignment**: [Text views with different sizes have different baselines](https://www.hackingwithswift.com/books/ios-swiftui/alignment-and-alignment-guides) - use `.alignmentGuide()` for custom alignment

2. **Offset vs Alignment**: [`.offset()` doesn't change view dimensions](https://swiftui-lab.com/alignment-guides/), while alignment guides do - affects parent container sizing

3. **Tight Containers**: [VStack/HStack size to content by default](https://www.w3tutorials.net/blog/swiftui-view-is-in-the-middle-instead-of-in-the-top/) - add `.frame(maxWidth: .infinity)` to fill available space

## Related Commands

- `/design-extract` - Extract components and layouts from Figma
- `/design-layout-to-html` - Generate HTML reference files
- `/design-layout-to-jsx` - Generate React/JSX components
- `/design-transform-swiftui` - Transform individual components

## Notes

- Generated views are production-ready but should be reviewed
- Add component imports manually based on your project structure
- Consider using SwiftUI preview for rapid iteration
- Test on different screen sizes and orientations
- Use SwiftUI modifiers to add animations and interactions

## References

- [SwiftUI Layout System Guide](https://www.swiftbysundell.com/articles/swiftui-layout-system-guide-part-1/)
- [Why Modifier Order Matters](https://www.hackingwithswift.com/books/ios-swiftui/why-modifier-order-matters)
- [Alignment Guides](https://swiftui-lab.com/alignment-guides/)
- [SwiftUI Frame Modifier](https://www.swiftbysundell.com/articles/swiftui-frame-modifier/)
