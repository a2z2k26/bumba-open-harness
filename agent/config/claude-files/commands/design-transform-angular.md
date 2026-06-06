---
name: design-transform-angular
description: Transform design tokens into Angular services with injectable theme and SCSS utilities
allowed-tools: Read, Write, Bash, Glob
---

# /transform-angular - Transform Design Tokens to Angular

Transform extracted design tokens into production-ready Angular services and style utilities.

## Purpose

This command transforms your `.design/tokens/` into Angular-compatible code:
- Injectable theme service
- SCSS/CSS variables
- TypeScript interfaces
- Angular Material theme integration (optional)

## Usage

Basic usage (requires `.design/` to be initialized):
```
/transform-angular
```

With Angular Material:
```
/transform-angular --material
```

With options:
```
/transform-angular --scss --standalone
```

## Command Options

| Option | Description | Default |
|--------|-------------|---------|
| `--material` | Generate Angular Material theme | false |
| `--standalone` | Use standalone components | Auto-detected (v17+) |
| `--scss` | Generate SCSS variables | true |
| `--css` | Generate CSS custom properties only | false |
| `--output <path>` | Custom output directory | ./src/design-system |
| `--force` | Regenerate even if tokens unchanged | false |
| `--storybook` | Generate Storybook stories | true |

---

## ⭐ Enhanced Transformation Pipeline (v2.0)

This skill uses an **enhanced transformation pipeline** with four key improvements:

### 1. Hybrid Token System 🆕
**Manual tokens take PRIORITY** over extracted tokens with graceful fallback:

```
Order: Manual Tokens (priority) → Component Extraction (fallback) → Merge → Transform
```

**How it works:**
- Checks `.design/tokens/` for manually created JSON files
- Extracts tokens from components (as fallback)
- Merges with manual tokens taking priority
- Warns about overrides and conflicts

Create `.design/tokens/colors.json` with YOUR brand colors and they'll always be used!

### 2. Token-First Architecture
Tokens are **always** extracted and transformed BEFORE components.

### 3. Identifier Sanitization
Converts Figma names to valid Angular/TypeScript identifiers with camelCase for @Input properties.

### 4. Smart Variant Detection ⭐⭐⭐
Automatically detects semantic property names: "Property 1" with primary/secondary → `variant` prop.

---

## Prerequisites

Before running this command:

1. **Initialize Design Bridge**: Run `/design-init` first
2. **Extract Tokens**: Ensure `.design/tokens/` contains extracted tokens
3. **Verify Config**: Check `.design/config.json` has `framework: "angular"`

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

Run the Angular transformation wrapper:

```bash
node .claude/wrappers/transform-angular.js
```

### Output Files

```
src/design-system/
├── tokens/
│   ├── colors.ts          # Color token constants
│   ├── typography.ts      # Typography tokens
│   ├── spacing.ts         # Spacing tokens
│   └── index.ts           # Barrel export
├── services/
│   ├── theme.service.ts   # Injectable theme service
│   └── tokens.service.ts  # Token access service
├── styles/
│   ├── _variables.scss    # SCSS variables
│   ├── _mixins.scss       # SCSS mixins
│   ├── _typography.scss   # Typography styles
│   └── tokens.css         # CSS custom properties
├── interfaces/
│   └── theme.interface.ts # TypeScript interfaces
└── design-system.module.ts # NgModule (or standalone exports)
```

---

## Example Output

### services/theme.service.ts
```typescript
import { Injectable, signal, computed } from '@angular/core';
import { colors } from '../tokens/colors';
import { typography } from '../tokens/typography';

@Injectable({ providedIn: 'root' })
export class ThemeService {
  private isDark = signal(false);

  theme = computed(() => ({
    colors: this.isDark() ? colors.dark : colors.light,
    typography,
  }));

  toggleTheme(): void {
    this.isDark.update(v => !v);
  }

  setDarkMode(dark: boolean): void {
    this.isDark.set(dark);
  }
}
```

### _variables.scss
```scss
// Colors
$color-primary: #007AFF;
$color-secondary: #5856D6;
$color-background: #FFFFFF;

// Typography
$font-family-base: 'Inter', sans-serif;
$font-size-base: 16px;
$font-weight-regular: 400;
$font-weight-bold: 700;

// Spacing
$spacing-xs: 4px;
$spacing-sm: 8px;
$spacing-md: 16px;
$spacing-lg: 24px;
```

---

## Angular Material Integration

When using `--material`, additional files are generated:

```
src/design-system/
├── material/
│   ├── custom-theme.scss  # Material theme overrides
│   ├── palette.ts         # Material color palette
│   └── typography.ts      # Material typography config
```

---

## Troubleshooting

### "Error: .design/ directory not found"
Run `/design-init` to initialize the Design Bridge structure.

### "Error: Angular CLI not detected"
Ensure you're in an Angular project with `angular.json`.

---

## Related Commands

- `/design-init` - Initialize Design Bridge structure
- `/design-extract` - Extract tokens from Figma
- `/transform-react` - Transform to React
- `/transform-vue` - Transform to Vue
