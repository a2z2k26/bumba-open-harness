---
name: design-transform-flutter
description: Transform design tokens into Flutter/Dart ThemeData classes and color schemes
allowed-tools: Read, Write, Bash, Glob
---

# /transform-flutter - Transform Design Tokens to Flutter

Transform extracted design tokens into production-ready Flutter/Dart theme classes.

## Purpose

This command transforms your `.design/tokens/` into Flutter-compatible code:
- Dart theme classes with ThemeData
- Material 3 color schemes
- TextTheme definitions
- Extension methods for easy access

## Usage

Basic usage (requires `.design/` to be initialized):
```
/transform-flutter
```

With Material 3:
```
/transform-flutter --material3
```

With options:
```
/transform-flutter --freezed --riverpod
```

## Command Options

| Option | Description | Default |
|--------|-------------|---------|
| `--material3` | Use Material 3 design system | true |
| `--freezed` | Generate Freezed classes | false |
| `--riverpod` | Include Riverpod providers | false |
| `--output <path>` | Custom output directory | ./lib/theme |
| `--force` | Regenerate even if tokens unchanged | false |

---

## ⭐ Enhanced Transformation Pipeline (v2.0)

**Hybrid Token System 🆕** - Manual tokens in `.design/tokens/*.json` take PRIORITY over extracted tokens with graceful fallback. Automatic merging, conflict detection, and warnings included.

**Key Features:**
- Manual tokens always used first
- Component extraction fills gaps
- Smart variant detection (Property 1 → variant)
- Identifier sanitization for Dart

---

## Prerequisites

Before running this command:

1. **Initialize Design Bridge**: Run `/design-init` first
2. **Extract Tokens**: Ensure `.design/tokens/` contains extracted tokens
3. **Verify Config**: Check `.design/config.json` has `framework: "flutter"`

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

Run the Flutter transformation wrapper:

```bash
node .claude/wrappers/transform-flutter.js
```

### Output Files

```
lib/theme/
├── app_colors.dart        # Color constants
├── app_typography.dart    # TextStyle definitions
├── app_spacing.dart       # Spacing constants
├── app_theme.dart         # ThemeData configuration
├── app_shadows.dart       # BoxShadow definitions
└── theme.dart             # Barrel export
```

---

## Example Output

### app_colors.dart
```dart
import 'package:flutter/material.dart';

class AppColors {
  AppColors._();

  // Primary colors
  static const Color primary = Color(0xFF007AFF);
  static const Color primaryLight = Color(0xFF5AC8FA);
  static const Color primaryDark = Color(0xFF0051A8);

  // Secondary colors
  static const Color secondary = Color(0xFF5856D6);

  // Semantic colors
  static const Color background = Color(0xFFFFFFFF);
  static const Color surface = Color(0xFFF2F2F7);
  static const Color error = Color(0xFFFF3B30);
  static const Color success = Color(0xFF34C759);

  // Text colors
  static const Color textPrimary = Color(0xFF000000);
  static const Color textSecondary = Color(0xFF8E8E93);

  // Color scheme for Material 3
  static ColorScheme get lightColorScheme => const ColorScheme.light(
    primary: primary,
    secondary: secondary,
    surface: surface,
    background: background,
    error: error,
  );

  static ColorScheme get darkColorScheme => const ColorScheme.dark(
    primary: primaryLight,
    secondary: secondary,
    surface: Color(0xFF1C1C1E),
    background: Color(0xFF000000),
    error: error,
  );
}
```

### app_typography.dart
```dart
import 'package:flutter/material.dart';

class AppTypography {
  AppTypography._();

  static const String fontFamily = 'Inter';

  static const TextStyle h1 = TextStyle(
    fontFamily: fontFamily,
    fontSize: 32,
    fontWeight: FontWeight.w700,
    height: 1.25,
  );

  static const TextStyle h2 = TextStyle(
    fontFamily: fontFamily,
    fontSize: 24,
    fontWeight: FontWeight.w600,
    height: 1.33,
  );

  static const TextStyle body = TextStyle(
    fontFamily: fontFamily,
    fontSize: 16,
    fontWeight: FontWeight.w400,
    height: 1.5,
  );

  static const TextStyle caption = TextStyle(
    fontFamily: fontFamily,
    fontSize: 12,
    fontWeight: FontWeight.w400,
    height: 1.33,
  );

  static TextTheme get textTheme => const TextTheme(
    displayLarge: h1,
    displayMedium: h2,
    bodyLarge: body,
    bodySmall: caption,
  );
}
```

### app_theme.dart
```dart
import 'package:flutter/material.dart';
import 'app_colors.dart';
import 'app_typography.dart';
import 'app_spacing.dart';

class AppTheme {
  AppTheme._();

  static ThemeData get lightTheme => ThemeData(
    useMaterial3: true,
    colorScheme: AppColors.lightColorScheme,
    textTheme: AppTypography.textTheme,
    scaffoldBackgroundColor: AppColors.background,
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.background,
      foregroundColor: AppColors.textPrimary,
      elevation: 0,
    ),
  );

  static ThemeData get darkTheme => ThemeData(
    useMaterial3: true,
    colorScheme: AppColors.darkColorScheme,
    textTheme: AppTypography.textTheme,
    scaffoldBackgroundColor: const Color(0xFF000000),
    appBarTheme: const AppBarTheme(
      backgroundColor: Color(0xFF000000),
      foregroundColor: Colors.white,
      elevation: 0,
    ),
  );
}
```

---

## Usage in Flutter App

```dart
import 'package:your_app/theme/theme.dart';

void main() {
  runApp(
    MaterialApp(
      theme: AppTheme.lightTheme,
      darkTheme: AppTheme.darkTheme,
      themeMode: ThemeMode.system,
      home: const MyApp(),
    ),
  );
}
```

---

## Troubleshooting

### "Error: .design/ directory not found"
Run `/design-init` to initialize the Design Bridge structure.

### "Font not found"
Add fonts to `pubspec.yaml` under `flutter.fonts`.

---

## Related Commands

- `/design-init` - Initialize Design Bridge structure
- `/design-extract` - Extract tokens from Figma
- `/transform-swiftui` - Transform to SwiftUI
- `/transform-jetpack-compose` - Transform to Jetpack Compose
