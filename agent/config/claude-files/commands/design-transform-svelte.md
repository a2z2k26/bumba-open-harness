---
name: design-transform-svelte
description: Transform design tokens into Svelte stores with writable theme state and actions
allowed-tools: Read, Write, Bash, Glob
---

# /transform-svelte - Transform Design Tokens to Svelte

Transform extracted design tokens into production-ready Svelte stores and style utilities.

## Purpose

This command transforms your `.design/tokens/` into Svelte-compatible code:
- Svelte writable stores for theme state
- CSS custom properties
- TypeScript type definitions
- SvelteKit-compatible structure (optional)

## Usage

Basic usage (requires `.design/` to be initialized):
```
/transform-svelte
```

With SvelteKit support:
```
/transform-svelte --sveltekit
```

With options:
```
/transform-svelte --typescript --scss
```

## Command Options

| Option | Description | Default |
|--------|-------------|---------|
| `--typescript` | Generate TypeScript definitions | Auto-detected |
| `--sveltekit` | Generate SvelteKit-compatible structure | Auto-detected |
| `--scss` | Generate SCSS instead of CSS | false |
| `--output <path>` | Custom output directory | ./src/lib/design-system |
| `--force` | Regenerate even if tokens unchanged | false |
| `--storybook` | Generate Storybook stories | true |

---

## ⭐ Enhanced Transformation Pipeline (v2.0)

**Hybrid Token System 🆕** - Manual tokens in `.design/tokens/*.json` take PRIORITY over extracted tokens. Automatic merging with smart variant detection and Svelte prop conventions.

---

## Prerequisites

Before running this command:

1. **Initialize Design Bridge**: Run `/design-init` first
2. **Extract Tokens**: Ensure `.design/tokens/` contains extracted tokens
3. **Verify Config**: Check `.design/config.json` has `framework: "svelte"`

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

Run the Svelte transformation wrapper:

```bash
node .claude/wrappers/transform-svelte.js
```

### Output Files

```
src/lib/design-system/
├── tokens/
│   ├── colors.ts          # Color tokens
│   ├── typography.ts      # Typography tokens
│   ├── spacing.ts         # Spacing tokens
│   └── index.ts           # Barrel export
├── stores/
│   ├── theme.ts           # Theme store
│   └── preferences.ts     # User preferences store
├── styles/
│   ├── variables.css      # CSS custom properties
│   ├── global.css         # Global styles
│   └── tokens.scss        # SCSS variables (if --scss)
├── components/
│   └── ThemeProvider.svelte
└── index.ts               # Main entry point
```

---

## Example Output

### stores/theme.ts
```typescript
import { writable, derived } from 'svelte/store';
import { colors } from '../tokens/colors';

export const isDark = writable(false);

export const theme = derived(isDark, ($isDark) => ({
  colors: $isDark ? colors.dark : colors.light,
  mode: $isDark ? 'dark' : 'light',
}));

export function toggleTheme() {
  isDark.update(v => !v);
}
```

### ThemeProvider.svelte
```svelte
<script lang="ts">
  import { theme } from '../stores/theme';
  import '../styles/variables.css';
</script>

<div class="theme-provider" class:dark={$theme.mode === 'dark'}>
  <slot />
</div>

<style>
  .theme-provider {
    min-height: 100%;
  }
</style>
```

---

## Troubleshooting

### "Error: .design/ directory not found"
Run `/design-init` to initialize the Design Bridge structure.

---

## Related Commands

- `/design-init` - Initialize Design Bridge structure
- `/design-extract` - Extract tokens from Figma
- `/transform-react` - Transform to React
- `/transform-vue` - Transform to Vue
