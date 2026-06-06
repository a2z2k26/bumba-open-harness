# SwiftUI Layout Design Principles

## Overview

This document provides SwiftUI-specific layout theory and best practices for iOS/macOS application design. Use these principles when generating, transforming, or validating SwiftUI layout code.

---

## 1. Apple's 8-Point Grid System

### iOS Spacing Foundation

SwiftUI and iOS use the **8-point grid** as the foundation for all spacing.

**Core Principle**: All spacing values use increments of 8 points (8, 16, 24, 32, 40, 48, 56, 64)

**SwiftUI Implementation**:
```swift
VStack(spacing: 8) { }   // Tight spacing
VStack(spacing: 16) { }  // Standard spacing
VStack(spacing: 24) { }  // Comfortable spacing
VStack(spacing: 32) { }  // Section spacing
```

**Padding Values**:
```swift
.padding(8)          // Compact
.padding(16)         // Standard
.padding(.horizontal, 20)  // Apple's default horizontal padding
.padding(.vertical, 32)    // Section padding
```

---

## 2. iOS Safe Areas & Layout Guides

### Safe Area Insets

SwiftUI automatically respects safe areas (notch, home indicator, status bar).

**Default Behavior**:
```swift
// ✅ Automatic safe area respect
VStack {
    Text("Content")
}
// Content avoids notch and home indicator

// ❌ Ignore safe area (use sparingly)
VStack {
    Text("Content")
}
.ignoresSafeArea()
```

**Partial Ignoring**:
```swift
// Ignore top only (full-bleed headers)
.ignoresSafeArea(edges: .top)

// Ignore horizontal only (full-width backgrounds)
.ignoresSafeArea(edges: .horizontal)
```

### Layout Margins

iOS has standard layout margins that vary by device size:

- **iPhone Portrait**: 20pt horizontal margins
- **iPhone Landscape**: 44pt horizontal margins
- **iPad**: 20-44pt contextual margins

**Access via Environment**:
```swift
@Environment(\.horizontalSizeClass) var sizeClass

var horizontalPadding: CGFloat {
    sizeClass == .compact ? 20 : 44
}
```

---

## 3. Adaptive Layout with Size Classes

### Size Class System

Apple's size classes define layout contexts:

**Horizontal**:
- `.compact`: iPhone portrait, iPhone landscape (smaller models)
- `.regular`: iPad, iPhone landscape (larger models)

**Vertical**:
- `.compact`: iPhone landscape
- `.regular`: iPhone portrait, iPad

**Responsive Pattern**:
```swift
@Environment(\.horizontalSizeClass) var sizeClass

var body: some View {
    if sizeClass == .compact {
        VStack { compactLayout() }
    } else {
        HStack { regularLayout() }
    }
}
```

**iOS 16+ Layout Protocol**:
```swift
let layout = sizeClass == .compact
    ? AnyLayout(VStackLayout())
    : AnyLayout(HStackLayout())

layout {
    ProfileImage()
    UserInfo()
}
```

---

## 4. Typography & Dynamic Type

### iOS Type System

**Standard Text Styles**:
```swift
.font(.largeTitle)     // 34pt (iOS 17)
.font(.title)          // 28pt
.font(.title2)         // 22pt
.font(.title3)         // 20pt
.font(.headline)       // 17pt semibold
.font(.body)           // 17pt (default)
.font(.callout)        // 16pt
.font(.subheadline)    // 15pt
.font(.footnote)       // 13pt
.font(.caption)        // 12pt
.font(.caption2)       // 11pt
```

**Dynamic Type Support**:
```swift
// ✅ Scales automatically with user preferences
Text("Content").font(.body)

// ❌ Fixed size, doesn't scale
Text("Content").font(.system(size: 17))
```

**Line Spacing**:
```swift
Text("Long content...")
    .lineSpacing(8)  // Additional spacing between lines
```

---

## 5. Spacing Patterns for SwiftUI

### Stack Spacing

```swift
// Uniform spacing between all children
VStack(spacing: 16) {
    Text("Item 1")
    Text("Item 2")
    Text("Item 3")
}

// Variable spacing with Spacer
VStack(spacing: 0) {
    Text("Top")
    Spacer()  // Flexible space
    Text("Bottom")
}

// Custom spacing for specific items
VStack {
    Text("Item 1")
        .padding(.bottom, 8)  // Custom spacing after this item
    Text("Item 2")
}
```

### Padding vs Spacing

**Spacing**: Between stack children (inside container)
**Padding**: Around view edges (outside boundary)

```swift
VStack(spacing: 16) {         // Space between items
    Text("Content")
}
.padding(24)                  // Space around VStack
```

---

## 6. Touch Targets & Tap Areas

### Apple Human Interface Guidelines

**Minimum Touch Target**: 44×44 points

**Implementation**:
```swift
// ❌ Too small for comfortable tapping
Button("Tap") { }
    .frame(width: 24, height: 24)

// ✅ Meets 44×44 minimum
Button("Tap") { }
    .frame(minWidth: 44, minHeight: 44)

// ✅ Expand tap area without visual size
Image(systemName: "heart")
    .frame(width: 24, height: 24)
    .contentShape(Rectangle())
    .frame(width: 44, height: 44)
```

**Navigation Bar Items**: Automatically 44×44 tap area
**Tab Bar Items**: Automatically 49pt height

---

## 7. Visual Hierarchy with Modifiers

### Layer Order

SwiftUI modifiers create layers in order applied:

```swift
Text("Hello")
    .background(Color.blue)      // Layer 1: Behind text
    .padding(16)                 // Layer 2: Space around blue bg
    .background(Color.red)       // Layer 3: Behind padding
    .cornerRadius(8)             // Layer 4: Rounds entire stack
```

### Elevation & Shadows

```swift
// Subtle elevation
.shadow(color: .black.opacity(0.1), radius: 4, y: 2)

// Card elevation
.shadow(color: .black.opacity(0.15), radius: 8, y: 4)

// Prominent elevation
.shadow(color: .black.opacity(0.2), radius: 16, y: 8)
```

---

## 8. Grid Layouts in SwiftUI

### LazyVGrid / LazyHGrid

```swift
let columns = [
    GridItem(.flexible(), spacing: 16),
    GridItem(.flexible(), spacing: 16),
    GridItem(.flexible(), spacing: 16)
]

LazyVGrid(columns: columns, spacing: 16) {
    ForEach(items) { item in
        CardView(item: item)
    }
}
.padding(.horizontal, 20)
```

**Grid Item Types**:
- `.flexible()`: Expands to fill available space
- `.adaptive(minimum: 100)`: Creates as many columns as fit
- `.fixed(100)`: Fixed width column

**12-Column Grid Pattern**:
```swift
let twelveColumnGrid = Array(repeating: GridItem(.flexible(), spacing: 8), count: 12)

// Span multiple columns
GridItem(.flexible(), spacing: 8, span: 4)  // Spans 4 columns
```

---

## 9. Accessibility Considerations

### VoiceOver & Semantic Hierarchy

**Reading Order**: Views read top-to-bottom, left-to-right by default.

```swift
// ✅ Logical source order
VStack {
    Text("Title")          // Read first
    Text("Description")    // Read second
    Button("Action") { }   // Read third
}

// ❌ Visual reordering breaks reading order
ZStack {
    VStack {
        Text("Description")
        Button("Action") { }
    }
    .offset(y: 100)
    Text("Title")
}
```

**Accessibility Labels**:
```swift
Image(systemName: "heart")
    .accessibilityLabel("Favorite")

Button { } label: {
    Image(systemName: "trash")
}
.accessibilityLabel("Delete")
```

### Dynamic Type Scaling

```swift
// ✅ Responds to user text size preferences
Text("Content")
    .font(.body)

// Allow text to scale beyond default limits
Text("Large content")
    .font(.body)
    .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
```

---

## 10. Performance Considerations

### LazyStacks vs Stacks

```swift
// ❌ Poor performance: Renders all 1000 views immediately
ScrollView {
    VStack {
        ForEach(0..<1000) { i in
            RowView(index: i)
        }
    }
}

// ✅ Good performance: Lazy loading
ScrollView {
    LazyVStack {
        ForEach(0..<1000) { i in
            RowView(index: i)
        }
    }
}
```

**Rule**: Use `LazyVStack`/`LazyHStack` for scrolling lists with many items.

### View Identity & Animation

```swift
// Stable identity for list items
ForEach(items, id: \.id) { item in
    ItemView(item: item)
}
.id(item.id)  // Explicit identity
```

---

## 11. Common Layout Patterns

### Navigation Layout
```swift
NavigationStack {
    ScrollView {
        VStack(spacing: 24) {
            content
        }
        .padding(.horizontal, 20)
    }
    .navigationTitle("Title")
}
```

### Card Layout
```swift
VStack(alignment: .leading, spacing: 12) {
    Text("Title")
        .font(.headline)
    Text("Description")
        .font(.body)
        .foregroundColor(.secondary)
    Button("Action") { }
}
.padding(16)
.background(Color(.systemBackground))
.cornerRadius(12)
.shadow(color: .black.opacity(0.1), radius: 8, y: 4)
```

### Form Layout
```swift
Form {
    Section("Profile") {
        TextField("Name", text: $name)
        TextField("Email", text: $email)
    }
    Section("Settings") {
        Toggle("Notifications", isOn: $notifications)
        Picker("Theme", selection: $theme) {
            Text("Light").tag(Theme.light)
            Text("Dark").tag(Theme.dark)
        }
    }
}
```

---

## 12. iOS Platform Conventions

### Navigation Bar Height
- **Compact**: 44pt
- **Regular**: 44pt (with large title: 96pt)

### Tab Bar Height
- **iPhone**: 49pt (83pt with safe area)
- **iPad**: 50pt

### Standard Corners
- **Cards**: 12-16pt corner radius
- **Buttons**: 8-10pt corner radius
- **Modals**: 16-20pt corner radius

### Standard Animations
```swift
.animation(.easeInOut, value: isExpanded)
.animation(.spring(response: 0.3), value: offset)
```

---

## Quick Reference Checklist

### SwiftUI Layout Validation

- [ ] Uses 8-point spacing scale (8, 16, 24, 32, 48)
- [ ] Respects safe areas (notch, home indicator)
- [ ] Touch targets minimum 44×44 points
- [ ] Uses Dynamic Type for text (`.font(.body)`, not fixed sizes)
- [ ] Adaptive layout with size classes for iPad support
- [ ] LazyVStack for scrolling lists (performance)
- [ ] Logical source order for VoiceOver
- [ ] Accessibility labels for icons and images
- [ ] Modifier order: size → padding → background
- [ ] Consistent corner radii (12-16pt for cards)
- [ ] Proper use of spacing vs Spacer
- [ ] View identity for lists (`.id()` or `id: \.id`)

---

## Sources

- **Apple Human Interface Guidelines** (iOS 17)
- **WWDC Sessions**: Layout & Composition, SwiftUI Performance
- **Swift by Sundell**: Layout system guides
- **Hacking with Swift**: SwiftUI best practices
- **SwiftUI Field Guide**: Alignment & layout patterns

**Last Updated**: January 2026
