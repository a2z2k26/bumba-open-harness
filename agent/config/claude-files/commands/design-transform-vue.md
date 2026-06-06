---
name: design-transform-vue
description: Transform design tokens into Vue 3 composables with Composition API and scoped styles
allowed-tools: Read, Write, Bash, Glob
---

# /transform-vue - Transform Design Tokens to Vue

Transform extracted design tokens into production-ready Vue 3 composables and style utilities.

## Purpose

This command transforms your `.design/tokens/` into Vue-compatible code:
- Vue 3 Composition API composables
- CSS custom properties with scoped styles
- Pinia store for theme state (optional)
- TypeScript type definitions

## Usage

Basic usage (requires `.design/` to be initialized):
```
/transform-vue
```

With options:
```
/transform-vue --typescript --pinia
```

For Vue 2 projects:
```
/transform-vue --vue2
```

## Command Options

| Option | Description | Default |
|--------|-------------|---------|
| `--typescript` | Generate TypeScript definitions | Auto-detected |
| `--vue2` | Generate Vue 2 compatible code | false (Vue 3) |
| `--pinia` | Include Pinia theme store | false |
| `--scss` | Generate SCSS instead of CSS | false |
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
Tokens are **always** extracted and transformed BEFORE components to prevent missing dependency errors.

```
Complete Flow: Manual Load → Component Extract → Merge → Transform → Composables
```

### 3. Identifier Sanitization
All Figma property names are automatically sanitized to valid Vue prop names:
- Removes spaces and special characters
- Handles reserved keywords
- Ensures proper camelCase for props

**Example:** `"Property 1"` → `variant` (or sanitized identifier)

### 4. Smart Variant Detection ⭐⭐⭐
Automatically detects semantic property names from value patterns:

| Figma Name | Values | Detected Prop |
|------------|--------|---------------|
| Property 1 | primary, secondary, tertiary | `variant` |
| Property 2 | small, medium, large | `size` |
| State | active, disabled, hover | `state` |
| Property 3 | filled, outlined, ghost | `appearance` |

**Benefits:**
- ✅ No more syntax errors from invalid identifiers
- ✅ Meaningful prop names instead of `property1`
- ✅ Automatic validation of token dependencies
- ✅ Clear warnings for missing tokens

### Vue-Specific Output

```vue
<script setup lang="ts">
// Props with smart-detected names
defineProps<{
  variant?: 'primary' | 'secondary' | 'tertiary';  // NOT property1
  size?: 'small' | 'large';                         // NOT property2
}>();
</script>
```

---

## Prerequisites

Before running this command:

1. **Initialize Design Bridge**: Run `/design-init` first
2. **Extract Tokens**: Ensure `.design/tokens/` contains extracted tokens
3. **Verify Config**: Check `.design/config.json` has `framework: "vue"`

---

## Step 1: Validate Environment

Check that all prerequisites are met:

```javascript
const designDir = path.join(process.cwd(), '.design');
if (!fs.existsSync(designDir)) {
  console.error('Error: .design/ directory not found');
  process.exit(1);
}

const config = JSON.parse(fs.readFileSync('.design/config.json'));
if (config.project.framework !== 'vue') {
  console.warn(`Warning: Project configured for ${config.project.framework}`);
}
```

---

## Step 2: Load Design Tokens

Load all token files from `.design/tokens/`:

- `colors.json` - Color palette and semantic colors
- `typography.json` - Font families, sizes, weights
- `spacing.json` - Spacing scale values

---

## Step 3: Execute Transformation

Run the Vue transformation wrapper:

```bash
node .claude/wrappers/transform-vue.js
```

### Output Files

```
src/design-system/
├── tokens/
│   ├── colors.ts          # Color tokens as composable
│   ├── typography.ts      # Typography composable
│   ├── spacing.ts         # Spacing composable
│   └── index.ts           # Barrel export
├── composables/
│   ├── useTheme.ts        # Theme composable
│   ├── useColors.ts       # Color utilities
│   └── useTypography.ts   # Typography utilities
├── styles/
│   ├── variables.css      # CSS custom properties
│   └── base.css           # Base styles
└── index.ts               # Main entry point
```

---

## Step 4: Update Metadata

After successful transformation, update `.design/metadata.json`.

---

## Example Output

### useTheme.ts
```typescript
import { ref, computed } from 'vue';
import { colors } from '../tokens/colors';
import { typography } from '../tokens/typography';

export function useTheme() {
  const isDark = ref(false);

  const theme = computed(() => ({
    colors: isDark.value ? colors.dark : colors.light,
    typography,
  }));

  const toggleTheme = () => {
    isDark.value = !isDark.value;
  };

  return { theme, isDark, toggleTheme };
}
```

### variables.css
```css
:root {
  --color-primary: #007AFF;
  --color-secondary: #5856D6;
  --color-background: #FFFFFF;

  --font-family-base: 'Inter', sans-serif;
  --font-size-base: 16px;

  --spacing-xs: 4px;
  --spacing-sm: 8px;
  --spacing-md: 16px;
}
```

---

## Troubleshooting

### "Error: .design/ directory not found"
Run `/design-init` to initialize the Design Bridge structure.

### "Error: No tokens found"
Extract tokens from Figma using `/design-extract`.

---

## Related Commands

- `/design-init` - Initialize Design Bridge structure
- `/design-extract` - Extract tokens from Figma
- `/transform-react` - Transform to React
- `/transform-nuxt` - Transform to Nuxt (Vue meta-framework)
