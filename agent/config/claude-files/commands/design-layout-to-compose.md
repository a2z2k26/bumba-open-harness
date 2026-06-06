---
name: design-layout-to-compose
description: Transform Figma layouts to Jetpack Compose with Column/Row, Arrangement.spacedBy, and Modifier chains
allowed-tools: Read, Write, Bash
instructions: design-layout-to-compose-principles.md
---

# design-layout-to-compose - Transform Figma Layouts to Jetpack Compose

Generate production-ready Jetpack Compose/Kotlin composables from extracted Figma layout data.

**Design Principles**: This skill follows Jetpack Compose-specific layout design principles including Material Design 4dp grid, Modifier order (critical!), Arrangement patterns, LazyColumn performance, and touch targets. See `~/.claude/instructions/design-layout-to-compose-principles.md` for complete guidelines.

## Purpose

Convert Figma layouts into Jetpack Compose code with:
- Column and Row composables
- Arrangement and Alignment
- Modifier chains for styling
- Design system component imports
- Production-ready Kotlin code
- .kt output files

## Prerequisites

- Layout data extracted from Figma (`.design/layouts/`)
- Component registry populated (`.design/componentRegistry.json`)
- Design system components available for imports

## Usage

### Transform Single Layout

```bash
node ~/.claude/shared-modules/design-system/layout-to-compose-transformer.js \
  --layout=PricingPage
```

### Transform All Layouts

```bash
for layout in .design/layouts/*.json; do
  node ~/.claude/shared-modules/design-system/layout-to-compose-transformer.js \
    --layout=$(basename "$layout" .json)
done
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--layout` | (required) | Layout name or file path |
| `--output-dir` | `.design/extracted-code/compose/layouts` | Output directory |

## Output

### File Structure

```
.design/extracted-code/compose/layouts/
├── PricingPage.kt
├── Homepage.kt
└── DashboardLayout.kt
```

### Generated Composable Example

```kotlin
/**
 * PricingPage Layout Composable
 * Generated from Figma layout extraction
 *
 * This composable uses transformed design system components.
 * Generated: 2026-01-08T...
 */

package com.example.layouts

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp

@Composable
fun PricingPage() {
    Column(
        modifier = Modifier
            .padding(horizontal = 32.dp, vertical = 64.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(32.dp, Alignment.CenterVertically)
    ) {
        PricingTier()
        PricingTier()
        PricingTier()
    }
}

@Preview(showBackground = true)
@Composable
fun PricingPagePreview() {
    PricingPage()
}
```

## Key Features

### Compose Layout Composables

Figma auto-layout properties convert to Compose:

```kotlin
// Vertical layout → Column
Column(
    modifier = Modifier.padding(16.dp),
    horizontalAlignment = Alignment.Start,
    verticalArrangement = Arrangement.spacedBy(16.dp)
) {
    Text("Title")
    Button(onClick = {}) { Text("Action") }
}

// Horizontal layout → Row
Row(
    modifier = Modifier.padding(16.dp),
    verticalAlignment = Alignment.CenterVertically,
    horizontalArrangement = Arrangement.spacedBy(24.dp)
) {
    Icon(Icons.Default.Menu, contentDescription = null)
    Text("Menu")
}
```

### Arrangement (Spacing & Alignment)

```kotlin
// Primary axis with spacing
Arrangement.spacedBy(24.dp)
Arrangement.spacedBy(16.dp, Alignment.CenterVertically)

// Without spacing
Arrangement.Start
Arrangement.Center
Arrangement.End
Arrangement.SpaceBetween
```

### Alignment (Cross Axis)

```kotlin
// Column horizontal alignment
Alignment.Start          // Left
Alignment.CenterHorizontally
Alignment.End            // Right

// Row vertical alignment
Alignment.Top
Alignment.CenterVertically
Alignment.Bottom
```

### Modifier Chains

```kotlin
Modifier
    .size(width = 200.dp, height = 100.dp)
    .padding(horizontal = 16.dp, vertical = 24.dp)
    .padding(start = 8.dp, top = 4.dp, end = 8.dp, bottom = 4.dp)
```

### Component References

```kotlin
// Component imports (add manually)
// import com.example.components.PricingTier
// import com.example.components.Button

// Usage with props
PricingTier(primary = true)
Button(text = "Get Started")
```

## Differences from Other Formats

| Aspect | HTML | React | SwiftUI | Flutter | Compose |
|--------|------|-------|---------|---------|---------|
| Container | `<div>` | `<div>` | `VStack/HStack` | `Column/Row` | `Column/Row` |
| Spacing | `gap` | `gap` | `spacing:` | `SizedBox` | `Arrangement.spacedBy` |
| Padding | `padding` | `padding` | `.padding()` | `Padding` | `Modifier.padding()` |
| Platform | Web | Web | iOS/macOS | Cross-platform | Android |

## Workflow

### 1. Extract Layout from Figma

```
Figma Plugin → Extract Layout
→ Saves to .design/layouts/pricing-page.json
```

### 2. Transform to Compose

```bash
node ~/.claude/shared-modules/design-system/layout-to-compose-transformer.js \
  --layout=pricing-page
```

### 3. Import in Android App

```kotlin
import com.example.layouts.PricingPage

@Composable
fun MyApp() {
    MaterialTheme {
        Surface {
            PricingPage()
        }
    }
}
```

### 4. Customize as Needed

- Add state with `remember`, `mutableStateOf`
- Connect to ViewModels
- Add click handlers
- Apply Material Design theme
- Add animations with `animateXAsState`

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

```kotlin
Button(primary = true, text = "Get Started")
```

## Programmatic API

### transformLayoutToCompose

```javascript
const { transformLayoutToCompose } = require('layout-to-compose-transformer');

const result = await transformLayoutToCompose(layoutData, {
  outputDir: '.design/extracted-code/compose/layouts'
});

// result = {
//   success: true,
//   layoutName: 'PricingPage',
//   composableName: 'PricingPage',
//   outputPath: '.design/extracted-code/compose/layouts/PricingPage.kt',
//   fileExtension: 'kt',
//   dependencies: ['Button', 'Card', 'PricingTier']
// }
```

## Troubleshooting

### Missing Component Imports

**Problem**: Unresolved references to components

**Solution**: Add imports:

```kotlin
import com.example.components.PricingTier
import com.example.components.Button
```

### Layout Issues

**Problem**: Layout doesn't match Figma exactly

**Solution**: Adjust arrangement and alignment:

```kotlin
Column(
    horizontalAlignment = Alignment.Start,  // Change alignment
    verticalArrangement = Arrangement.spacedBy(32.dp)  // Adjust spacing
)
```

### Preview Not Showing

**Problem**: Preview doesn't render

**Solution**: Ensure Preview annotation is present:

```kotlin
@Preview(showBackground = true, showSystemUi = true)
@Composable
fun PricingPagePreview() {
    MaterialTheme {
        PricingPage()
    }
}
```

### Modifier Order

**Problem**: Modifiers not applying correctly

**Solution**: Check modifier order (order matters!):

```kotlin
Modifier
    .size(200.dp)      // Size first
    .padding(16.dp)    // Padding affects size
    .background(Color.Red)  // Background after padding
```

## Jetpack Compose Best Practices & Edge Cases

### Modifier Order is Critical ⚠️

[Modifiers create an ordered, immutable chain](https://developer.android.com/develop/ui/compose/modifiers) where each modifier wraps the previous one. Order directly affects the result:

```kotlin
// ❌ Wrong: Padding outside background
Text("Hello")
    .padding(16.dp)
    .background(Color.Red)  // Background won't cover padding

// ✅ Correct: Background covers padding
Text("Hello")
    .background(Color.Red)
    .padding(16.dp)  // Padding inside background

// ❌ Wrong: Size after fill
Box(
    modifier = Modifier
        .fillMaxWidth()
        .size(100.dp)  // No effect, already filled
)

// ✅ Correct: Size before fill
Box(
    modifier = Modifier
        .size(100.dp)
        .fillMaxWidth()  // Can expand from fixed size
)
```

**Rule**: [Size/layout modifiers first, then padding, then visual styling](https://developer.android.com/develop/ui/compose/layouts/constraints-modifiers).

### Arrangement.spacedBy Performance

[Use Arrangement.spacedBy on parent layout](https://dladukedev.com/articles/044_spacing_concepts_compose/) for uniform spacing:

```kotlin
// ✅ Efficient: Single arrangement parameter
Column(
    verticalArrangement = Arrangement.spacedBy(16.dp)
) {
    Text("Item 1")
    Text("Item 2")
    Text("Item 3")
}

// ❌ Less efficient: Manual Spacers everywhere
Column {
    Text("Item 1")
    Spacer(modifier = Modifier.height(16.dp))
    Text("Item 2")
    Spacer(modifier = Modifier.height(16.dp))
    Text("Item 3")
}
```

**Edge Case**: [Interactive elements with Arrangement need careful touch target handling](https://dladukedev.com/articles/044_spacing_concepts_compose/) - ripple indicators stop at padding edges.

### Single-Pass Measurement

[Compose measures children only once](https://developer.android.com/develop/ui/compose/layouts/basics) for performance - nest freely without perf concerns:

```kotlin
// No performance penalty for deep nesting
Column {
    Row {
        Column {
            Text("Deeply")
            Text("Nested")
        }
    }
}
```

### LaunchedEffect Mistakes

[Common key mistakes with LaunchedEffect](https://proandroiddev.com/launchedeffect-vs-remembercoroutinescope-in-jetpack-compose-24b5c91106ac):

```kotlin
// ❌ Wrong: Never restarts on userId change
LaunchedEffect(Unit) {
    fetchData(userId)
}

// ✅ Correct: Restarts when userId changes
LaunchedEffect(userId) {
    fetchData(userId)
}

// ❌ Wrong: Restarts too often
LaunchedEffect(timestamp) {  // timestamp changes frequently
    fetchData()
}

// ✅ Correct: Use rememberUpdatedState for values that shouldn't restart effect
LaunchedEffect(key1 = true) {
    val currentCallback = rememberUpdatedState(onTimeout)
    delay(3000)
    currentCallback.value()
}
```

**Rule**: [Pass relevant dependencies as keys](https://developer.android.com/develop/ui/compose/side-effects), not `Unit` or `true`.

### remember vs derivedStateOf

[Use derivedStateOf for frequently changing values](https://medium.com/@riadhysaam/21-common-mistakes-developers-make-with-jetpack-compose-b018b341c38e):

```kotlin
// ❌ Recomposes on every scroll pixel
val isAtTop = remember { scrollState.value == 0 }

// ✅ Buffers changes, only recomposes when result changes
val isAtTop = remember {
    derivedStateOf { scrollState.value == 0 }
}
```

### Tight Container Edge Case

[Column/Row size to content by default](https://dladukedev.com/articles/044_spacing_concepts_compose/) - Arrangement has no effect without extra space:

```kotlin
// ❌ No effect: Container is tight
Column(
    verticalArrangement = Arrangement.SpaceBetween  // No extra space!
) {
    Text("Top")
    Text("Bottom")
}

// ✅ Works: Container has extra space
Column(
    modifier = Modifier.fillMaxHeight(),
    verticalArrangement = Arrangement.SpaceBetween
) {
    Text("Top")
    Text("Bottom")
}
```

### Common Mistakes

1. **Missing remember**: [mutableStateOf without remember creates new state on every recomposition](https://mrmans0n.github.io/compose-rules/rules/)

2. **Expensive computations**: [Avoid sorting/filtering in composable body](https://developer.android.com/develop/ui/compose/performance/bestpractices) - use remember or ViewModel

3. **DisposableEffect cleanup**: [Always clean up resources in onDispose](https://developer.android.com/develop/ui/compose/side-effects)

4. **Wrong side-effect API**: [LaunchedEffect guarantees execution in Composition](https://proandroiddev.com/launchedeffect-vs-remembercoroutinescope-in-jetpack-compose-24b5c91106ac), rememberCoroutineScope doesn't

## Related Commands

- `/design-extract` - Extract components and layouts from Figma
- `/design-layout-to-html` - Generate HTML reference files
- `/design-layout-to-jsx` - Generate React/JSX components
- `/design-transform-compose` - Transform individual components

## Notes

- Generated composables are production-ready but should be reviewed
- Use `@Preview` annotations for rapid development
- Test with different screen sizes and orientations
- Consider dark theme support with Material Theme
- Use Layout Inspector in Android Studio for debugging
- **Modifier order is critical** - size/weight before padding/background
- Use LaunchedEffect with proper keys for side effects

## References

- [Compose Modifiers](https://developer.android.com/develop/ui/compose/modifiers)
- [Constraints and Modifier Order](https://developer.android.com/develop/ui/compose/layouts/constraints-modifiers)
- [Side Effects in Compose](https://developer.android.com/develop/ui/compose/side-effects)
- [Performance Best Practices](https://developer.android.com/develop/ui/compose/performance/bestpractices)
- [Spacing Concepts in Compose](https://dladukedev.com/articles/044_spacing_concepts_compose/)
