# Jetpack Compose Layout Design Principles

## Overview

This document provides Jetpack Compose-specific layout theory and best practices for Android application design. Use these principles when generating, transforming, or validating Compose/Kotlin layout code.

---

## 1. Material Design's 4dp Grid System

### Android Spacing Foundation

Jetpack Compose uses Material Design's **4dp grid** as the foundation for all spacing.

**Core Principle**: All spacing values use increments of 4 density-independent pixels (4, 8, 12, 16, 24, 32, 40, 48)

**Compose Implementation**:
```kotlin
Column(
    verticalArrangement = Arrangement.spacedBy(8.dp)  // Tight spacing
) {
    Text("Item 1")
    Text("Item 2")
}

Column(
    verticalArrangement = Arrangement.spacedBy(16.dp) // Standard spacing
) {
    Text("Item 1")
    Text("Item 2")
}

Column(
    verticalArrangement = Arrangement.spacedBy(24.dp) // Comfortable spacing
) {
    Text("Item 1")
    Text("Item 2")
}
```

**Padding Values**:
```kotlin
Box(modifier = Modifier.padding(8.dp))          // Compact
Box(modifier = Modifier.padding(16.dp))         // Standard
Box(modifier = Modifier.padding(horizontal = 20.dp, vertical = 32.dp)) // Section padding
```

---

## 2. Android System Insets & Window Insets

### System Bars & Cutouts

Compose provides WindowInsets APIs to handle status bars, navigation bars, and display cutouts.

**Default Behavior**:
```kotlin
// ✅ Automatic system bar respect
Scaffold { innerPadding ->
    Column(
        modifier = Modifier.padding(innerPadding)
    ) {
        Text("Content")
    }
}
// Content avoids system bars

// ❌ Ignore system bars (use sparingly)
Column(
    modifier = Modifier
        .fillMaxSize()
        .windowInsetsPadding(WindowInsets(0.dp))
) {
    Text("Content")
}
```

**Partial Ignoring**:
```kotlin
// Ignore top only (full-bleed headers)
Box(
    modifier = Modifier
        .fillMaxWidth()
        .windowInsetsPadding(WindowInsets.statusBars.only(WindowInsetsSides.Bottom))
)

// Ignore horizontal only (full-width backgrounds)
Box(
    modifier = Modifier
        .fillMaxWidth()
        .windowInsetsPadding(WindowInsets.systemBars.only(WindowInsetsSides.Vertical))
)
```

### Layout Margins

Material Design has standard layout margins for Android:

- **Phone**: 16dp horizontal margins
- **Tablet (< 600dp)**: 16dp horizontal margins
- **Tablet (≥ 600dp)**: 24dp horizontal margins
- **Desktop**: 32dp+ horizontal margins

**Access via BoxWithConstraints**:
```kotlin
BoxWithConstraints {
    val horizontalPadding = when {
        maxWidth < 600.dp -> 16.dp
        maxWidth < 1240.dp -> 24.dp
        else -> 32.dp
    }

    Column(
        modifier = Modifier.padding(horizontal = horizontalPadding)
    ) {
        // content
    }
}
```

---

## 3. Responsive Layout with Window Size Classes

### Material Design Window Size Classes

Compose uses WindowSizeClass for responsive layouts:

**Size Classes**:
- **Compact**: < 600dp width (phone portrait)
- **Medium**: 600-839dp width (tablet portrait, phone landscape)
- **Expanded**: ≥ 840dp width (tablet landscape, desktop)

**Responsive Pattern**:
```kotlin
@Composable
fun AdaptiveLayout(
    windowSizeClass: WindowSizeClass
) {
    when (windowSizeClass.widthSizeClass) {
        WindowWidthSizeClass.Compact -> {
            Column { CompactLayout() }
        }
        WindowWidthSizeClass.Medium -> {
            Row { MediumLayout() }
        }
        WindowWidthSizeClass.Expanded -> {
            Row { ExpandedLayout() }
        }
    }
}
```

**BoxWithConstraints Pattern**:
```kotlin
BoxWithConstraints {
    if (maxWidth < 600.dp) {
        CompactLayout()
    } else if (maxWidth < 840.dp) {
        MediumLayout()
    } else {
        ExpandedLayout()
    }
}
```

---

## 4. Typography & Material Theme

### Material 3 Type System

**Standard Text Styles**:
```kotlin
Text("Display Large",
    style = MaterialTheme.typography.displayLarge)    // 57sp

Text("Headline Large",
    style = MaterialTheme.typography.headlineLarge)   // 32sp

Text("Title Large",
    style = MaterialTheme.typography.titleLarge)      // 22sp

Text("Body Large",
    style = MaterialTheme.typography.bodyLarge)       // 16sp

Text("Body Medium",
    style = MaterialTheme.typography.bodyMedium)      // 14sp (default)

Text("Label Small",
    style = MaterialTheme.typography.labelSmall)      // 11sp
```

**Font Scaling Support**:
```kotlin
// ✅ Scales automatically with user preferences
Text("Content",
    style = MaterialTheme.typography.bodyMedium)

// ❌ Fixed size, doesn't scale
Text("Content",
    style = TextStyle(fontSize = 14.sp))
```

**Line Height**:
```kotlin
Text(
    text = "Long content...",
    style = MaterialTheme.typography.bodyLarge.copy(
        lineHeight = 24.sp
    )
)
```

---

## 5. Spacing Patterns for Compose

### Arrangement & Spacing

```kotlin
// Uniform spacing between all children
Column(
    verticalArrangement = Arrangement.spacedBy(16.dp)
) {
    Text("Item 1")
    Text("Item 2")
    Text("Item 3")
}

// Variable spacing with Spacer
Column {
    Text("Top")
    Spacer(modifier = Modifier.weight(1f))  // Flexible space
    Text("Bottom")
}

// Conditional spacing
Column {
    Text("Item 1")
    if (showItem2) {
        Spacer(modifier = Modifier.height(8.dp))
        Text("Item 2")
    }
}
```

### Padding in Modifier Chains

**Padding**: Applied via Modifier chain

```kotlin
Column(
    modifier = Modifier
        .fillMaxWidth()
        .padding(24.dp)                 // Padding around Column
) {
    Text("Content")
}

// Individual edge padding
Box(
    modifier = Modifier
        .padding(start = 16.dp, top = 8.dp, end = 16.dp, bottom = 8.dp)
)
```

---

## 6. Touch Targets & Tap Areas

### Material Design Guidelines

**Minimum Touch Target**: 48×48 dp

**Implementation**:
```kotlin
// ❌ Too small for comfortable tapping
Box(
    modifier = Modifier
        .size(24.dp)
        .clickable { }
) {
    Icon(Icons.Default.Favorite, contentDescription = null)
}

// ✅ Meets 48×48 minimum
IconButton(
    onClick = { }
) {
    Icon(
        Icons.Default.Favorite,
        contentDescription = "Favorite",
        modifier = Modifier.size(24.dp)
    )
}  // IconButton auto-sizes to 48×48

// ✅ Expand tap area without visual size
Box(
    modifier = Modifier
        .size(48.dp)
        .clickable { },
    contentAlignment = Alignment.Center
) {
    Icon(
        Icons.Default.Favorite,
        contentDescription = "Favorite",
        modifier = Modifier.size(24.dp)
    )
}
```

**Material Component Standards**:
- **TopAppBar**: 64dp height (default)
- **NavigationBar**: 80dp height
- **FAB**: 56×56 dp (default)

---

## 7. Visual Hierarchy with Modifier Order

### Layer Order & Z-Index

Composables render in code order, with later items on top:

```kotlin
Box {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Blue)
    )  // Layer 1: Bottom

    Box(
        modifier = Modifier
            .size(100.dp)
            .background(Color.Red)
    )  // Layer 2: Middle (on top of blue)

    Text("Top")  // Layer 3: Top (on top of red)
}
```

**Modifier Order Matters**:
```kotlin
Text("Hello")
    .background(Color.Blue)      // Layer 1: Behind text
    .padding(16.dp)              // Layer 2: Space around blue bg
    .background(Color.Red)       // Layer 3: Behind padding
```

### Elevation & Shadows

```kotlin
// Subtle elevation
Surface(
    shadowElevation = 2.dp,
    content = { /* content */ }
)

// Card elevation
Surface(
    shadowElevation = 4.dp,
    content = { /* content */ }
)

// Prominent elevation
Surface(
    shadowElevation = 8.dp,
    content = { /* content */ }
)

// Custom shadow (less common)
Box(
    modifier = Modifier.shadow(
        elevation = 4.dp,
        shape = RoundedCornerShape(8.dp)
    )
)
```

---

## 8. Grid Layouts in Compose

### LazyVerticalGrid

```kotlin
LazyVerticalGrid(
    columns = GridCells.Fixed(3),           // 3 columns
    contentPadding = PaddingValues(16.dp),
    horizontalArrangement = Arrangement.spacedBy(16.dp),
    verticalArrangement = Arrangement.spacedBy(16.dp)
) {
    items(items) { item ->
        CardView(item = item)
    }
}
```

**Grid Cell Types**:
- `GridCells.Fixed(count)`: Fixed number of columns
- `GridCells.Adaptive(minSize)`: As many columns as fit
- `GridCells.FixedSize(size)`: Fixed size columns

**Responsive Grid Pattern**:
```kotlin
BoxWithConstraints {
    val columns = when {
        maxWidth < 600.dp -> 1      // Mobile: full width
        maxWidth < 840.dp -> 2      // Tablet: 2 columns
        else -> 3                    // Desktop: 3 columns
    }

    LazyVerticalGrid(
        columns = GridCells.Fixed(columns),
        horizontalArrangement = Arrangement.spacedBy(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        items(items) { item ->
            ItemCard(item)
        }
    }
}
```

---

## 9. Accessibility Considerations

### Semantics & TalkBack

**Reading Order**: Composables read in tree order by default.

```kotlin
// ✅ Logical tree order
Column {
    Text("Title")          // Read first
    Text("Description")    // Read second
    Button(onClick = {}) {
        Text("Action")      // Read third
    }
}

// ❌ Visual reordering breaks reading order
Box {
    Text(
        "Title",
        modifier = Modifier.align(Alignment.BottomCenter)  // Positioned last
    )  // Read first
    Text(
        "Description",
        modifier = Modifier.align(Alignment.TopCenter)
    )  // Read second
}
```

**Content Descriptions**:
```kotlin
Icon(
    Icons.Default.Favorite,
    contentDescription = "Favorite"
)

IconButton(
    onClick = { },
    modifier = Modifier.semantics {
        contentDescription = "Delete"
    }
) {
    Icon(Icons.Default.Delete, contentDescription = null)
}
```

### Font Scaling

```kotlin
// ✅ Responds to user text size preferences
Text(
    text = "Content",
    style = MaterialTheme.typography.bodyMedium
)

// Allow text to scale beyond default limits
CompositionLocalProvider(
    LocalDensity provides Density(
        density = LocalDensity.current.density,
        fontScale = LocalDensity.current.fontScale.coerceIn(1f, 2f)
    )
) {
    Text("Limited scaling")
}
```

---

## 10. Performance Considerations

### LazyColumn vs Column

```kotlin
// ❌ Poor performance: Renders all 1000 items immediately
Column(
    modifier = Modifier.verticalScroll(rememberScrollState())
) {
    repeat(1000) { i ->
        RowItem(index = i)
    }
}

// ✅ Good performance: Lazy loading
LazyColumn {
    items(1000) { i ->
        RowItem(index = i)
    }
}
```

**Rule**: Use `LazyColumn`/`LazyRow` for scrolling lists with many items.

### Recomposition Optimization

```kotlin
// ❌ Recomposes frequently
@Composable
fun Counter(count: Int) {
    Text("Count: $count")
    Text("Static text")  // Recomposes unnecessarily
}

// ✅ Minimized recomposition scope
@Composable
fun Counter(count: Int) {
    Text("Count: $count")
}

@Composable
fun StaticText() {
    Text("Static text")  // Won't recompose
}
```

### Keys for List Items

```kotlin
LazyColumn {
    items(
        items = items,
        key = { item -> item.id }  // Stable identity
    ) { item ->
        ItemComposable(item = item)
    }
}
```

---

## 11. Common Layout Patterns

### Scaffold Layout
```kotlin
Scaffold(
    topBar = {
        TopAppBar(
            title = { Text("Title") }
        )
    },
    floatingActionButton = {
        FloatingActionButton(onClick = { }) {
            Icon(Icons.Default.Add, contentDescription = "Add")
        }
    }
) { innerPadding ->
    Column(
        modifier = Modifier
            .padding(innerPadding)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp),
        verticalArrangement = Arrangement.spacedBy(24.dp)
    ) {
        // content
    }
}
```

### Card Layout
```kotlin
Card(
    modifier = Modifier
        .fillMaxWidth()
        .padding(16.dp),
    elevation = CardDefaults.cardElevation(defaultElevation = 4.dp),
    shape = RoundedCornerShape(12.dp)
) {
    Column(
        modifier = Modifier.padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text(
            text = "Title",
            style = MaterialTheme.typography.titleLarge
        )
        Text(
            text = "Description",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Button(onClick = { }) {
            Text("Action")
        }
    }
}
```

### Form Layout
```kotlin
Column(
    modifier = Modifier
        .fillMaxWidth()
        .padding(16.dp),
    verticalArrangement = Arrangement.spacedBy(16.dp)
) {
    OutlinedTextField(
        value = name,
        onValueChange = { name = it },
        label = { Text("Name") },
        modifier = Modifier.fillMaxWidth()
    )

    OutlinedTextField(
        value = email,
        onValueChange = { email = it },
        label = { Text("Email") },
        modifier = Modifier.fillMaxWidth()
    )

    Spacer(modifier = Modifier.height(8.dp))

    Button(
        onClick = { },
        modifier = Modifier.fillMaxWidth()
    ) {
        Text("Submit")
    }
}
```

---

## 12. Material Design Platform Conventions

### AppBar Heights
- **TopAppBar**: 64dp (small)
- **MediumTopAppBar**: 112dp
- **LargeTopAppBar**: 152dp

### Navigation Heights
- **NavigationBar**: 80dp
- **NavigationRail**: 80dp width (default)

### Standard Corners
- **Cards**: 12dp corner radius
- **Buttons**: 20dp corner radius (fully rounded)
- **Bottom Sheets**: 28dp top corners
- **Dialogs**: 28dp corner radius

### Standard Animations
```kotlin
val alpha by animateFloatAsState(
    targetValue = if (visible) 1f else 0f,
    animationSpec = tween(durationMillis = 300)
)

val offset by animateDpAsState(
    targetValue = if (expanded) 0.dp else 100.dp,
    animationSpec = spring(
        dampingRatio = Spring.DampingRatioMediumBouncy,
        stiffness = Spring.StiffnessLow
    )
)
```

---

## Quick Reference Checklist

### Compose Layout Validation

- [ ] Uses 4dp spacing scale (4, 8, 12, 16, 24, 32, 48)
- [ ] Respects system bars via WindowInsets or Scaffold padding
- [ ] Touch targets minimum 48×48 dp
- [ ] Uses MaterialTheme.typography for text (not fixed sizes)
- [ ] Responsive layout with BoxWithConstraints or WindowSizeClass
- [ ] LazyColumn/LazyRow for scrolling lists (performance)
- [ ] Keys for list items with stable IDs
- [ ] Logical tree order for TalkBack
- [ ] Content descriptions for icons and images
- [ ] Modifier order: size → padding → background
- [ ] Consistent corner radii (12dp for cards)
- [ ] Material elevation for depth (2dp, 4dp, 8dp)

---

## Sources

- **Material Design 3 Guidelines**
- **Jetpack Compose Documentation**: Layout & Modifiers
- **Android Developers**: Compose Performance
- **Material Design Layout Guide**
- **Compose Accessibility Guide**

**Last Updated**: January 2026
