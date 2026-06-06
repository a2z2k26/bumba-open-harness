---
name: design-transform-swiftui
description: Transform design tokens into SwiftUI Color extensions and view modifiers
allowed-tools: Read, Write, Bash, Glob
---

# /transform-swiftui - Transform Design Tokens to SwiftUI

Transform extracted design tokens into production-ready SwiftUI extensions and theme utilities.

## Purpose

This command transforms your `.design/tokens/` into SwiftUI-compatible code:
- Color extensions
- Font/Typography extensions
- Spacing constants
- EnvironmentKey-based theming
- Swift Package Manager compatible structure

## Usage

Basic usage (requires `.design/` to be initialized):
```
/transform-swiftui
```

As Swift Package:
```
/transform-swiftui --package
```

With options:
```
/transform-swiftui --ios-min 15.0 --macos
```

## Command Options

| Option | Description | Default |
|--------|-------------|---------|
| `--package` | Generate as Swift Package | false |
| `--ios-min <version>` | Minimum iOS version | 14.0 |
| `--macos` | Include macOS support | false |
| `--watchos` | Include watchOS support | false |
| `--output <path>` | Custom output directory | ./Sources/DesignTokens |
| `--force` | Regenerate even if tokens unchanged | false |

---

## ⭐ Enhanced Transformation Pipeline (v2.0)

**Hybrid Token System 🆕** - Manual tokens in `.design/tokens/*.json` take PRIORITY over extracted tokens. Automatic merging with smart variant detection and Swift identifier conventions.

---

## Prerequisites

Before running this command:

1. **Initialize Design Bridge**: Run `/design-init` first
2. **Extract Tokens**: Ensure `.design/tokens/` contains extracted tokens
3. **Verify Config**: Check `.design/config.json` has `framework: "swiftui"`

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

Run the SwiftUI transformation wrapper:

```bash
node .claude/wrappers/transform-swiftui.js
```

### Output Files

```
Sources/DesignTokens/
├── Colors.swift           # Color extensions
├── Typography.swift       # Font extensions
├── Spacing.swift          # Spacing constants
├── Theme.swift            # Theme environment
├── Shadows.swift          # Shadow definitions
└── DesignTokens.swift     # Main export
```

---

## Example Output

### Colors.swift
```swift
import SwiftUI

public extension Color {
    // Primary colors
    static let primary = Color(hex: "007AFF")
    static let primaryLight = Color(hex: "5AC8FA")
    static let primaryDark = Color(hex: "0051A8")

    // Secondary colors
    static let secondary = Color(hex: "5856D6")

    // Semantic colors
    static let background = Color(hex: "FFFFFF")
    static let surface = Color(hex: "F2F2F7")
    static let error = Color(hex: "FF3B30")
    static let success = Color(hex: "34C759")

    // Text colors
    static let textPrimary = Color(hex: "000000")
    static let textSecondary = Color(hex: "8E8E93")
}

// Color initializer from hex
extension Color {
    init(hex: String) {
        let hex = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var int: UInt64 = 0
        Scanner(string: hex).scanHexInt64(&int)
        let a, r, g, b: UInt64
        switch hex.count {
        case 6:
            (a, r, g, b) = (255, int >> 16, int >> 8 & 0xFF, int & 0xFF)
        case 8:
            (a, r, g, b) = (int >> 24, int >> 16 & 0xFF, int >> 8 & 0xFF, int & 0xFF)
        default:
            (a, r, g, b) = (255, 0, 0, 0)
        }
        self.init(
            .sRGB,
            red: Double(r) / 255,
            green: Double(g) / 255,
            blue: Double(b) / 255,
            opacity: Double(a) / 255
        )
    }
}
```

### Typography.swift
```swift
import SwiftUI

public struct Typography {
    public static let h1 = Font.system(size: 32, weight: .bold)
    public static let h2 = Font.system(size: 24, weight: .semibold)
    public static let h3 = Font.system(size: 20, weight: .semibold)
    public static let body = Font.system(size: 16, weight: .regular)
    public static let bodyBold = Font.system(size: 16, weight: .bold)
    public static let caption = Font.system(size: 12, weight: .regular)
    public static let small = Font.system(size: 11, weight: .regular)

    // Custom font support
    public static func custom(_ name: String, size: CGFloat, weight: Font.Weight = .regular) -> Font {
        Font.custom(name, size: size).weight(weight)
    }
}

// Font extension for easy access
public extension Font {
    static var h1: Font { Typography.h1 }
    static var h2: Font { Typography.h2 }
    static var h3: Font { Typography.h3 }
    static var bodyText: Font { Typography.body }
    static var caption: Font { Typography.caption }
}
```

### Theme.swift
```swift
import SwiftUI

public struct Theme {
    public let colors: ThemeColors
    public let typography: ThemeTypography
    public let spacing: ThemeSpacing

    public static let light = Theme(
        colors: .light,
        typography: .default,
        spacing: .default
    )

    public static let dark = Theme(
        colors: .dark,
        typography: .default,
        spacing: .default
    )
}

// Environment key for theme
private struct ThemeKey: EnvironmentKey {
    static let defaultValue: Theme = .light
}

public extension EnvironmentValues {
    var theme: Theme {
        get { self[ThemeKey.self] }
        set { self[ThemeKey.self] = newValue }
    }
}

// View extension for theme
public extension View {
    func theme(_ theme: Theme) -> some View {
        environment(\.theme, theme)
    }
}
```

---

## Usage in SwiftUI App

```swift
import SwiftUI
import DesignTokens

@main
struct MyApp: App {
    @State private var isDark = false

    var body: some Scene {
        WindowGroup {
            ContentView()
                .theme(isDark ? .dark : .light)
        }
    }
}

struct ContentView: View {
    @Environment(\.theme) var theme

    var body: some View {
        Text("Hello, World!")
            .font(.h1)
            .foregroundColor(.textPrimary)
            .padding(Spacing.md)
    }
}
```

---

## Troubleshooting

### "Error: .design/ directory not found"
Run `/design-init` to initialize the Design Bridge structure.

---

## Related Commands

- `/design-init` - Initialize Design Bridge structure
- `/design-extract` - Extract tokens from Figma
- `/transform-flutter` - Transform to Flutter
- `/transform-jetpack-compose` - Transform to Jetpack Compose
