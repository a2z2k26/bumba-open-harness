# Flutter Layout Design Principles

## Overview

This document provides Flutter-specific layout theory and best practices for cross-platform application design. Use these principles when generating, transforming, or validating Flutter/Dart layout code.

---

## 1. Flutter's 4dp Grid System

### Material Design Spacing Foundation

Flutter uses Material Design's **4dp grid** as the foundation for all spacing.

**Core Principle**: All spacing values use increments of 4 density-independent pixels (4, 8, 12, 16, 24, 32, 40, 48)

**Flutter Implementation**:
```dart
Column(
  children: [
    Text('Title'),
    SizedBox(height: 8),   // Tight spacing
    Text('Subtitle'),
    SizedBox(height: 16),  // Standard spacing
    Text('Body'),
    SizedBox(height: 24),  // Comfortable spacing
  ],
)
```

**Padding Values**:
```dart
Padding(
  padding: EdgeInsets.all(8),              // Compact
  child: Widget(),
)

Padding(
  padding: EdgeInsets.all(16),             // Standard
  child: Widget(),
)

Padding(
  padding: EdgeInsets.symmetric(
    horizontal: 20,  // Material's default horizontal
    vertical: 32,    // Section padding
  ),
  child: Widget(),
)
```

---

## 2. Material Design Layout Guidelines

### Safe Area Insets

Flutter automatically handles safe areas on iOS and Android notches/status bars.

**Default Behavior**:
```dart
// ✅ Automatic safe area respect
Scaffold(
  body: Column(
    children: [
      Text('Content'),
    ],
  ),
)
// Content avoids notch and navigation

// ❌ Ignore safe area (use sparingly)
Scaffold(
  body: SafeArea(
    top: false,
    child: Column(
      children: [
        Text('Content'),
      ],
    ),
  ),
)
```

**Partial Ignoring**:
```dart
// Ignore top only (full-bleed headers)
SafeArea(
  top: false,
  child: Widget(),
)

// Ignore specific sides
SafeArea(
  left: false,
  right: false,
  child: Widget(),
)
```

### Material Layout Margins

Material Design has standard layout margins:

- **Mobile Portrait**: 16dp horizontal margins
- **Mobile Landscape**: 16dp horizontal margins
- **Tablet**: 24dp horizontal margins
- **Desktop**: 24dp+ contextual margins

**Access via MediaQuery**:
```dart
final screenWidth = MediaQuery.of(context).size.width;

double horizontalPadding() {
  if (screenWidth < 600) return 16;  // Mobile
  if (screenWidth < 1240) return 24; // Tablet
  return 32;                          // Desktop
}
```

---

## 3. Responsive Layout with Breakpoints

### Material Design Breakpoints

Flutter uses Material Design breakpoints for responsive layouts:

**Standard Breakpoints**:
- **Compact**: 0-599dp (phone portrait)
- **Medium**: 600-839dp (tablet portrait, phone landscape)
- **Expanded**: 840dp+ (tablet landscape, desktop)

**Responsive Pattern**:
```dart
Widget build(BuildContext context) {
  final width = MediaQuery.of(context).size.width;

  if (width < 600) {
    return Column(children: compactLayout());
  } else if (width < 840) {
    return Row(children: mediumLayout());
  } else {
    return Row(children: expandedLayout());
  }
}
```

**LayoutBuilder Pattern**:
```dart
LayoutBuilder(
  builder: (context, constraints) {
    if (constraints.maxWidth < 600) {
      return MobileLayout();
    } else {
      return TabletLayout();
    }
  },
)
```

---

## 4. Typography & Text Scaling

### Material Text Styles

**Standard Text Styles**:
```dart
Text('Display Large',
  style: Theme.of(context).textTheme.displayLarge)   // 57sp

Text('Headline Large',
  style: Theme.of(context).textTheme.headlineLarge)  // 32sp

Text('Title Large',
  style: Theme.of(context).textTheme.titleLarge)     // 22sp

Text('Body Large',
  style: Theme.of(context).textTheme.bodyLarge)      // 16sp

Text('Body Medium',
  style: Theme.of(context).textTheme.bodyMedium)     // 14sp (default)

Text('Label Small',
  style: Theme.of(context).textTheme.labelSmall)     // 11sp
```

**Text Scaling Support**:
```dart
// ✅ Scales automatically with user preferences
Text('Content',
  style: Theme.of(context).textTheme.bodyMedium)

// ❌ Fixed size, doesn't scale
Text('Content',
  style: TextStyle(fontSize: 14))
```

**Line Height**:
```dart
Text(
  'Long content...',
  style: TextStyle(
    fontSize: 16,
    height: 1.5,  // Line height multiplier (1.5 = 24sp)
  ),
)
```

---

## 5. Spacing Patterns for Flutter

### Widget Spacing

```dart
// Uniform spacing with SizedBox
Column(
  children: [
    Text('Item 1'),
    SizedBox(height: 16),
    Text('Item 2'),
    SizedBox(height: 16),
    Text('Item 3'),
  ],
)

// Variable spacing with Spacer
Column(
  children: [
    Text('Top'),
    Spacer(),  // Flexible space
    Text('Bottom'),
  ],
)

// Conditional spacing
Column(
  children: [
    Text('Item 1'),
    if (showItem2) ...[
      SizedBox(height: 8),
      Text('Item 2'),
    ],
  ],
)
```

### Padding vs Margin

**Padding**: Inside widget boundaries
**Margin**: Outside widget boundaries (via Container)

```dart
// Padding: Space inside container
Container(
  padding: EdgeInsets.all(24),  // Space inside
  child: Text('Content'),
)

// Margin: Space outside container
Container(
  margin: EdgeInsets.all(24),   // Space outside
  child: Text('Content'),
)
```

---

## 6. Touch Targets & Tap Areas

### Material Design Guidelines

**Minimum Touch Target**: 48×48 dp

**Implementation**:
```dart
// ❌ Too small for comfortable tapping
GestureDetector(
  onTap: () {},
  child: Container(
    width: 24,
    height: 24,
    child: Icon(Icons.favorite),
  ),
)

// ✅ Meets 48×48 minimum
IconButton(
  iconSize: 24,
  icon: Icon(Icons.favorite),
  onPressed: () {},
)  // IconButton auto-sizes to 48×48

// ✅ Expand tap area without visual size
GestureDetector(
  onTap: () {},
  child: Container(
    width: 48,
    height: 48,
    alignment: Alignment.center,
    child: Container(
      width: 24,
      height: 24,
      child: Icon(Icons.favorite, size: 24),
    ),
  ),
)
```

**Material Component Standards**:
- **AppBar**: 56dp height (default)
- **BottomNavigationBar**: 56dp height
- **FAB**: 56×56 dp (default)

---

## 7. Visual Hierarchy with Widget Tree

### Layer Order

Flutter builds widgets in tree order:

```dart
Stack(
  children: [
    Container(color: Colors.blue),      // Layer 1: Bottom
    Positioned(
      top: 20,
      left: 20,
      child: Container(color: Colors.red), // Layer 2: Middle
    ),
    Positioned(
      top: 40,
      left: 40,
      child: Text('Top'),              // Layer 3: Top
    ),
  ],
)
```

### Elevation & Shadows

```dart
// Subtle elevation
Container(
  decoration: BoxDecoration(
    boxShadow: [
      BoxShadow(
        color: Colors.black.withOpacity(0.1),
        blurRadius: 4,
        offset: Offset(0, 2),
      ),
    ],
  ),
)

// Material elevation (recommended)
Material(
  elevation: 2,   // Subtle
  elevation: 4,   // Card
  elevation: 8,   // Prominent
  child: Widget(),
)
```

---

## 8. Grid Layouts in Flutter

### GridView

```dart
GridView.builder(
  gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
    crossAxisCount: 3,           // 3 columns
    crossAxisSpacing: 16,        // Horizontal gap
    mainAxisSpacing: 16,         // Vertical gap
    childAspectRatio: 1.0,       // Square items
  ),
  itemCount: items.length,
  itemBuilder: (context, index) {
    return CardWidget(item: items[index]);
  },
)
```

**Grid Types**:
- `FixedCrossAxisCount`: Fixed number of columns
- `MaxCrossAxisExtent`: Maximum width per item
- `SliverGridDelegate`: Custom grid logic

**12-Column Grid Pattern**:
```dart
// Responsive column count
int getColumnCount(double width) {
  if (width < 600) return 1;      // Mobile: full width
  if (width < 840) return 2;      // Tablet: 6 columns each
  return 3;                        // Desktop: 4 columns each
}

LayoutBuilder(
  builder: (context, constraints) {
    return GridView.builder(
      gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: getColumnCount(constraints.maxWidth),
        crossAxisSpacing: 16,
        mainAxisSpacing: 16,
      ),
      itemBuilder: (context, index) => ItemWidget(),
    );
  },
)
```

---

## 9. Accessibility Considerations

### Semantics & Screen Readers

**Reading Order**: Widgets read in tree order by default.

```dart
// ✅ Logical tree order
Column(
  children: [
    Text('Title'),          // Read first
    Text('Description'),    // Read second
    ElevatedButton(
      onPressed: () {},
      child: Text('Action'), // Read third
    ),
  ],
)

// ❌ Visual reordering breaks reading order
Stack(
  children: [
    Positioned(
      bottom: 0,
      child: Text('Title'),  // Read first but positioned last
    ),
    Positioned(
      top: 0,
      child: Text('Description'),
    ),
  ],
)
```

**Semantic Labels**:
```dart
Semantics(
  label: 'Favorite',
  child: Icon(Icons.favorite),
)

IconButton(
  icon: Icon(Icons.delete),
  tooltip: 'Delete',  // Auto-creates semantic label
  onPressed: () {},
)
```

### Text Scaling

```dart
// ✅ Responds to user text size preferences
Text('Content',
  style: Theme.of(context).textTheme.bodyMedium,
)

// Allow text to scale beyond default limits
MediaQuery(
  data: MediaQuery.of(context).copyWith(
    textScaleFactor: MediaQuery.of(context).textScaleFactor.clamp(1.0, 2.0),
  ),
  child: Text('Limited scaling'),
)
```

---

## 10. Performance Considerations

### ListView vs Column

```dart
// ❌ Poor performance: Renders all 1000 widgets immediately
SingleChildScrollView(
  child: Column(
    children: List.generate(1000, (i) => RowWidget(index: i)),
  ),
)

// ✅ Good performance: Lazy loading
ListView.builder(
  itemCount: 1000,
  itemBuilder: (context, index) {
    return RowWidget(index: index);
  },
)
```

**Rule**: Use `ListView.builder` for scrolling lists with many items.

### Const Constructors

```dart
// ❌ Rebuilds on every parent rebuild
Column(
  children: [
    Text('Title'),
    Text('Subtitle'),
  ],
)

// ✅ Built once, reused
const Column(
  children: [
    Text('Title'),
    Text('Subtitle'),
  ],
)
```

### Widget Identity & Keys

```dart
// Stable identity for list items
ListView.builder(
  itemCount: items.length,
  itemBuilder: (context, index) {
    return ItemWidget(
      key: ValueKey(items[index].id),
      item: items[index],
    );
  },
)
```

---

## 11. Common Layout Patterns

### Scaffold Layout
```dart
Scaffold(
  appBar: AppBar(
    title: Text('Title'),
  ),
  body: SingleChildScrollView(
    padding: EdgeInsets.all(20),
    child: Column(
      spacing: 24,
      children: [
        content,
      ],
    ),
  ),
  floatingActionButton: FloatingActionButton(
    onPressed: () {},
    child: Icon(Icons.add),
  ),
)
```

### Card Layout
```dart
Card(
  elevation: 4,
  shape: RoundedRectangleBorder(
    borderRadius: BorderRadius.circular(12),
  ),
  child: Padding(
    padding: EdgeInsets.all(16),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Title',
          style: Theme.of(context).textTheme.titleLarge,
        ),
        SizedBox(height: 8),
        Text(
          'Description',
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
            color: Colors.grey[600],
          ),
        ),
        SizedBox(height: 16),
        ElevatedButton(
          onPressed: () {},
          child: Text('Action'),
        ),
      ],
    ),
  ),
)
```

### Form Layout
```dart
Form(
  child: Column(
    children: [
      TextFormField(
        decoration: InputDecoration(
          labelText: 'Name',
          border: OutlineInputBorder(),
        ),
      ),
      SizedBox(height: 16),
      TextFormField(
        decoration: InputDecoration(
          labelText: 'Email',
          border: OutlineInputBorder(),
        ),
      ),
      SizedBox(height: 24),
      ElevatedButton(
        onPressed: () {},
        child: Text('Submit'),
      ),
    ],
  ),
)
```

---

## 12. Material Design Platform Conventions

### AppBar Heights
- **Standard**: 56dp
- **Prominent (with large title)**: 128dp

### Navigation Heights
- **BottomNavigationBar**: 56dp
- **NavigationRail**: 72dp width (default)

### Standard Corners
- **Cards**: 12-16dp corner radius
- **Buttons**: 4-8dp corner radius
- **Bottom Sheets**: 16-28dp top corners
- **Dialogs**: 28dp corner radius

### Standard Animations
```dart
AnimatedContainer(
  duration: Duration(milliseconds: 300),
  curve: Curves.easeInOut,
  // properties
)

AnimatedOpacity(
  duration: Duration(milliseconds: 200),
  opacity: isVisible ? 1.0 : 0.0,
  child: Widget(),
)
```

---

## Quick Reference Checklist

### Flutter Layout Validation

- [ ] Uses 4dp spacing scale (4, 8, 12, 16, 24, 32, 48)
- [ ] Respects safe areas (notches, navigation bars)
- [ ] Touch targets minimum 48×48 dp
- [ ] Uses Theme.of(context).textTheme for text (not fixed sizes)
- [ ] Responsive layout with LayoutBuilder or MediaQuery
- [ ] ListView.builder for scrolling lists (performance)
- [ ] Const constructors where possible
- [ ] Logical tree order for screen readers
- [ ] Semantic labels for icons and images
- [ ] Consistent corner radii (12-16dp for cards)
- [ ] Keys for list items (ValueKey or ObjectKey)
- [ ] Material elevation for depth

---

## Sources

- **Material Design Guidelines** (Material 3)
- **Flutter Documentation**: Layout & Composition
- **Flutter Performance Best Practices**
- **Flutter Accessibility Guide**
- **Material Design Layout Guide**

**Last Updated**: January 2026
