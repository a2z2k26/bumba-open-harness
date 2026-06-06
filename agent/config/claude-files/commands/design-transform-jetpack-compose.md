---
name: design-transform-jetpack-compose
description: Transform design tokens into Kotlin/Jetpack Compose Material 3 theme composables
allowed-tools: Read, Write, Bash, Glob
---

# /transform-jetpack-compose - Transform Design Tokens to Jetpack Compose

Transform extracted design tokens into production-ready Kotlin/Jetpack Compose theme classes.

## Purpose

This command transforms your `.design/tokens/` into Jetpack Compose-compatible code:
- Material 3 Theme composables
- Color scheme definitions
- Typography with TextStyle
- Spacing composables
- KMP (Kotlin Multiplatform) support (optional)

## Usage

Basic usage (requires `.design/` to be initialized):
```
/transform-jetpack-compose
```

With Material 3:
```
/transform-jetpack-compose --material3
```

For Kotlin Multiplatform:
```
/transform-jetpack-compose --kmp
```

## Command Options

| Option | Description | Default |
|--------|-------------|---------|
| `--material3` | Use Material 3 theming | true |
| `--kmp` | Kotlin Multiplatform support | false |
| `--package <name>` | Package name | Auto-detected |
| `--output <path>` | Custom output directory | ./app/src/main/kotlin/ui/theme |
| `--force` | Regenerate even if tokens unchanged | false |

---

## ⭐ Enhanced Transformation Pipeline (v2.0)

**Hybrid Token System 🆕** - Manual tokens in `.design/tokens/*.json` take PRIORITY over extracted tokens. Automatic merging with smart variant detection and identifier sanitization for Kotlin/Compose.

---

## Prerequisites

Before running this command:

1. **Initialize Design Bridge**: Run `/design-init` first
2. **Extract Tokens**: Ensure `.design/tokens/` contains extracted tokens
3. **Verify Config**: Check `.design/config.json` has `framework: "jetpack-compose"`

---

## Step 1: Validate Environment

```javascript
const designDir = path.join(process.cwd(), '.design');
if (!fs.existsSync(designDir)) {
  console.error('Error: .design/ directory not found');
  process.exit(1);
}
```

---

## Step 2: Load Design Tokens

Load all token files from `.design/tokens/`.

---

## Step 3: Execute Transformation

Run the Jetpack Compose transformation wrapper:

```bash
node .claude/wrappers/transform-jetpack-compose.js
```

### Output Files

```
app/src/main/kotlin/ui/theme/
├── Color.kt               # Color definitions
├── Type.kt                # Typography definitions
├── Spacing.kt             # Spacing object
├── Shape.kt               # Shape definitions
├── Theme.kt               # Main theme composable
└── Dimens.kt              # Dimension resources
```

---

## Example Output

### Color.kt
```kotlin
package com.example.app.ui.theme

import androidx.compose.ui.graphics.Color

// Primary colors
val Primary = Color(0xFF007AFF)
val PrimaryLight = Color(0xFF5AC8FA)
val PrimaryDark = Color(0xFF0051A8)

// Secondary colors
val Secondary = Color(0xFF5856D6)

// Semantic colors
val Background = Color(0xFFFFFFFF)
val Surface = Color(0xFFF2F2F7)
val Error = Color(0xFFFF3B30)
val Success = Color(0xFF34C759)

// Text colors
val TextPrimary = Color(0xFF000000)
val TextSecondary = Color(0xFF8E8E93)

// Dark theme colors
val DarkBackground = Color(0xFF000000)
val DarkSurface = Color(0xFF1C1C1E)
val DarkTextPrimary = Color(0xFFFFFFFF)
val DarkTextSecondary = Color(0xFF8E8E93)
```

### Type.kt
```kotlin
package com.example.app.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

val InterFontFamily = FontFamily(
    Font(R.font.inter_regular, FontWeight.Normal),
    Font(R.font.inter_medium, FontWeight.Medium),
    Font(R.font.inter_semibold, FontWeight.SemiBold),
    Font(R.font.inter_bold, FontWeight.Bold)
)

val H1Style = TextStyle(
    fontFamily = InterFontFamily,
    fontWeight = FontWeight.Bold,
    fontSize = 32.sp,
    lineHeight = 40.sp
)

val H2Style = TextStyle(
    fontFamily = InterFontFamily,
    fontWeight = FontWeight.SemiBold,
    fontSize = 24.sp,
    lineHeight = 32.sp
)

val BodyStyle = TextStyle(
    fontFamily = InterFontFamily,
    fontWeight = FontWeight.Normal,
    fontSize = 16.sp,
    lineHeight = 24.sp
)

val CaptionStyle = TextStyle(
    fontFamily = InterFontFamily,
    fontWeight = FontWeight.Normal,
    fontSize = 12.sp,
    lineHeight = 16.sp
)

val AppTypography = Typography(
    displayLarge = H1Style,
    displayMedium = H2Style,
    bodyLarge = BodyStyle,
    bodySmall = CaptionStyle
)
```

### Spacing.kt
```kotlin
package com.example.app.ui.theme

import androidx.compose.ui.unit.dp

object Spacing {
    val xs = 4.dp
    val sm = 8.dp
    val md = 16.dp
    val lg = 24.dp
    val xl = 32.dp
    val xxl = 48.dp
}
```

### Theme.kt
```kotlin
package com.example.app.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable

private val LightColorScheme = lightColorScheme(
    primary = Primary,
    secondary = Secondary,
    background = Background,
    surface = Surface,
    error = Error,
    onPrimary = Color.White,
    onSecondary = Color.White,
    onBackground = TextPrimary,
    onSurface = TextPrimary,
    onError = Color.White
)

private val DarkColorScheme = darkColorScheme(
    primary = PrimaryLight,
    secondary = Secondary,
    background = DarkBackground,
    surface = DarkSurface,
    error = Error,
    onPrimary = Color.Black,
    onSecondary = Color.White,
    onBackground = DarkTextPrimary,
    onSurface = DarkTextPrimary,
    onError = Color.White
)

@Composable
fun AppTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit
) {
    val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme

    MaterialTheme(
        colorScheme = colorScheme,
        typography = AppTypography,
        content = content
    )
}
```

---

## Usage in Compose App

```kotlin
import com.example.app.ui.theme.AppTheme
import com.example.app.ui.theme.Spacing

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            AppTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    Column(
                        modifier = Modifier.padding(Spacing.md)
                    ) {
                        Text(
                            text = "Hello, World!",
                            style = MaterialTheme.typography.displayLarge
                        )
                    }
                }
            }
        }
    }
}
```

---

## Troubleshooting

### "Error: .design/ directory not found"
Run `/design-init` to initialize the Design Bridge structure.

### "Font resource not found"
Add font files to `res/font/` directory.

---

## Related Commands

- `/design-init` - Initialize Design Bridge structure
- `/design-extract` - Extract tokens from Figma
- `/transform-flutter` - Transform to Flutter
- `/transform-swiftui` - Transform to SwiftUI
