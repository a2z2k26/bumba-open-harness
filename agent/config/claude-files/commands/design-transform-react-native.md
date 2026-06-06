---
name: design-transform-react-native
description: Transform design tokens into React Native StyleSheet definitions and theme provider
allowed-tools: Read, Write, Bash, Glob
---

# /transform-react-native - Transform Design Tokens to React Native

Transform extracted design tokens into production-ready React Native StyleSheet and theme utilities.

## Purpose

This command transforms your `.design/tokens/` into React Native-compatible code:
- StyleSheet.create() definitions
- React Native Paper theme (optional)
- Expo-compatible structure
- TypeScript type definitions
- Context-based ThemeProvider

## Usage

Basic usage (requires `.design/` to be initialized):
```
/transform-react-native
```

With React Native Paper:
```
/transform-react-native --paper
```

For Expo projects:
```
/transform-react-native --expo
```

## Command Options

| Option | Description | Default |
|--------|-------------|---------|
| `--typescript` | Generate TypeScript definitions | Auto-detected |
| `--paper` | Generate React Native Paper theme | false |
| `--expo` | Expo-compatible structure | Auto-detected |
| `--styled-components` | Use styled-components/native | false |
| `--output <path>` | Custom output directory | ./src/design-system |
| `--force` | Regenerate even if tokens unchanged | false |

---

## ⭐ Enhanced Transformation Pipeline (v2.0)

**Hybrid Token System 🆕** - Manual tokens in `.design/tokens/*.json` take PRIORITY over extracted tokens. Automatic merging with smart variant detection and React Native identifier conventions.

---

## Prerequisites

Before running this command:

1. **Initialize Design Bridge**: Run `/design-init` first
2. **Extract Tokens**: Ensure `.design/tokens/` contains extracted tokens
3. **Verify Config**: Check `.design/config.json` has `framework: "react-native"`

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

Run the React Native transformation wrapper:

```bash
node .claude/wrappers/transform-react-native.js
```

### Output Files

```
src/design-system/
├── tokens/
│   ├── colors.ts          # Color constants
│   ├── typography.ts      # Typography StyleSheet
│   ├── spacing.ts         # Spacing constants
│   └── index.ts           # Barrel export
├── theme/
│   ├── ThemeProvider.tsx  # Context provider
│   ├── theme.ts           # Complete theme object
│   ├── useTheme.ts        # Theme hook
│   └── types.ts           # TypeScript types
├── styles/
│   ├── globalStyles.ts    # Global StyleSheet
│   └── mixins.ts          # Style mixins
└── index.ts               # Main entry point
```

---

## Example Output

### tokens/colors.ts
```typescript
export const colors = {
  primary: '#007AFF',
  secondary: '#5856D6',
  background: '#FFFFFF',
  surface: '#F2F2F7',
  text: {
    primary: '#000000',
    secondary: '#8E8E93',
  },
  error: '#FF3B30',
  success: '#34C759',
} as const;

export type ColorToken = keyof typeof colors;
```

### tokens/typography.ts
```typescript
import { StyleSheet } from 'react-native';

export const typography = StyleSheet.create({
  h1: {
    fontFamily: 'Inter-Bold',
    fontSize: 32,
    lineHeight: 40,
    fontWeight: '700',
  },
  h2: {
    fontFamily: 'Inter-SemiBold',
    fontSize: 24,
    lineHeight: 32,
    fontWeight: '600',
  },
  body: {
    fontFamily: 'Inter-Regular',
    fontSize: 16,
    lineHeight: 24,
    fontWeight: '400',
  },
  caption: {
    fontFamily: 'Inter-Regular',
    fontSize: 12,
    lineHeight: 16,
    fontWeight: '400',
  },
});
```

### theme/ThemeProvider.tsx
```typescript
import React, { createContext, useContext, useState } from 'react';
import { colors } from '../tokens/colors';
import { typography } from '../tokens/typography';
import { spacing } from '../tokens/spacing';

interface Theme {
  colors: typeof colors;
  typography: typeof typography;
  spacing: typeof spacing;
  isDark: boolean;
}

const ThemeContext = createContext<Theme | undefined>(undefined);

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [isDark, setIsDark] = useState(false);

  const theme: Theme = {
    colors,
    typography,
    spacing,
    isDark,
  };

  return (
    <ThemeContext.Provider value={theme}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within ThemeProvider');
  }
  return context;
};
```

---

## Platform-Specific Considerations

### iOS
- Font weights map to system fonts
- Safe area insets included in spacing

### Android
- Elevation values for shadows
- Ripple effect colors

---

## Troubleshooting

### "Error: .design/ directory not found"
Run `/design-init` to initialize the Design Bridge structure.

### "Font not loading"
Ensure fonts are linked in your React Native project.

---

## Related Commands

- `/design-init` - Initialize Design Bridge structure
- `/design-extract` - Extract tokens from Figma
- `/transform-flutter` - Transform to Flutter
- `/transform-react` - Transform to React (web)
