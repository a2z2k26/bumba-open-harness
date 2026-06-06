---
name: design-layout-to-tailwind
description: Transform Figma layouts to Tailwind CSS with utility classes, mobile-first responsive design, and gap utilities
allowed-tools: Read, Write, Bash
instructions: design-layout-to-tailwind-principles.md
---

# design-layout-to-tailwind - Transform Figma Layouts to Tailwind CSS

Generate production-ready HTML/React with Tailwind CSS utility classes from extracted Figma layout data.

**Design Principles**: This skill follows Tailwind CSS-specific layout design principles including 4px (0.25rem) spacing scale, mobile-first breakpoints, flexbox/grid utilities, purge configuration, and touch targets. See `~/.claude/instructions/design-layout-to-tailwind-principles.md` for complete guidelines.

## Purpose

Convert Figma layouts into code with Tailwind CSS:
- Tailwind utility classes instead of inline styles
- Semantic spacing scale mapping
- HTML or React/JSX output
- Design system component imports
- Production-ready code
- .html or .tsx/.jsx output files

## Prerequisites

- Layout data extracted from Figma (`.design/layouts/`)
- Component registry populated (`.design/componentRegistry.json`)
- Tailwind CSS configured in your project

## Usage

### Transform Single Layout to HTML

```bash
node ~/.claude/shared-modules/design-system/layout-to-tailwind-transformer.js \
  --layout=PricingPage \
  --format=html
```

### Transform Single Layout to React/JSX

```bash
node ~/.claude/shared-modules/design-system/layout-to-tailwind-transformer.js \
  --layout=PricingPage \
  --format=jsx \
  --typescript
```

### Transform All Layouts

```bash
for layout in .design/layouts/*.json; do
  node ~/.claude/shared-modules/design-system/layout-to-tailwind-transformer.js \
    --layout=$(basename "$layout" .json) \
    --format=jsx
done
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--layout` | (required) | Layout name or file path |
| `--format` | `html` | Output format: `html` or `jsx` |
| `--typescript` | `true` | Generate TypeScript (.tsx) when format=jsx |
| `--import-path` | `'../components'` | Path to design system components (jsx only) |
| `--export-default` | `true` | Use default export (jsx only) |
| `--output-dir` | `.design/extracted-code/tailwind/layouts` | Output directory |

## Output

### File Structure

```
.design/extracted-code/tailwind/layouts/
├── pricing-page.html
├── PricingPage.tsx
├── Homepage.tsx
└── dashboard-layout.html
```

### Generated HTML Example

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PricingPage - Tailwind Layout</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50 p-5">
  <h1 class="text-base font-semibold mb-3 text-gray-900">
    PricingPage
  </h1>

  <div class="layout-container bg-white rounded-lg shadow">
    <div class="flex flex-col items-center justify-center gap-8 py-16 px-8">
      <div class="w-[280px] h-[120px] border-2 border-dashed border-indigo-500 bg-indigo-50 flex items-center justify-center rounded text-xs font-medium text-indigo-600" data-component="PricingTier">
        PricingTier
      </div>
      <div class="w-[280px] h-[120px] border-2 border-dashed border-indigo-500 bg-indigo-50 flex items-center justify-center rounded text-xs font-medium text-indigo-600" data-component="PricingTier">
        PricingTier
      </div>
    </div>
  </div>
</body>
</html>
```

### Generated React/TSX Example

```tsx
/**
 * PricingPage Layout Component
 * Generated from Figma layout extraction with Tailwind CSS
 *
 * This component uses Tailwind utility classes for styling.
 * Generated: 2026-01-08T...
 */

import React from 'react';
import { PricingTier } from '../components/PricingTier';

export interface PricingPageProps {
  // Add custom props here if needed
}

const PricingPage: React.FC<PricingPageProps> = (props) => {
  return (
    <div className="flex flex-col items-center justify-center gap-8 py-16 px-8">
      <PricingTier />
      <PricingTier />
      <PricingTier />
    </div>
  );
};

PricingPage.displayName = 'PricingPage';

export default PricingPage;
```

## Key Features

### Tailwind Utility Classes

Figma auto-layout properties convert to Tailwind classes:

```html
<!-- Vertical layout with center alignment and gap -->
<div class="flex flex-col items-center gap-6">
  <!-- children -->
</div>

<!-- Horizontal layout with space-between -->
<div class="flex flex-row justify-between items-center gap-4">
  <!-- children -->
</div>
```

### Spacing Scale Mapping

Figma pixel values map to Tailwind's spacing scale:

| Figma (px) | Tailwind | Value |
|------------|----------|-------|
| 0-2 | `0.5` | 2px |
| 4 | `1` | 4px |
| 8 | `2` | 8px |
| 16 | `4` | 16px |
| 24 | `6` | 24px |
| 32 | `8` | 32px |
| 48 | `12` | 48px |
| 64 | `16` | 64px |

```html
<!-- Gap of 24px → gap-6 -->
<div class="flex gap-6">

<!-- Padding of 16px → p-4 -->
<div class="p-4">

<!-- Padding top 32px, horizontal 16px → pt-8 px-4 -->
<div class="pt-8 px-4">
```

### Exact Values with Brackets

For non-standard sizes, use bracket notation:

```html
<!-- Exact width 280px -->
<div class="w-[280px]">

<!-- Exact height 375px -->
<div class="h-[375px]">
```

### Layout Classes

```html
<!-- Flexbox -->
<div class="flex">              <!-- display: flex -->
<div class="flex-col">          <!-- flex-direction: column -->
<div class="flex-row">          <!-- flex-direction: row -->

<!-- Justify Content -->
<div class="justify-start">     <!-- justify-content: flex-start -->
<div class="justify-center">    <!-- justify-content: center -->
<div class="justify-end">       <!-- justify-content: flex-end -->
<div class="justify-between">   <!-- justify-content: space-between -->

<!-- Align Items -->
<div class="items-start">       <!-- align-items: flex-start -->
<div class="items-center">      <!-- align-items: center -->
<div class="items-end">         <!-- align-items: flex-end -->
<div class="items-stretch">     <!-- align-items: stretch -->

<!-- Gap -->
<div class="gap-4">             <!-- gap: 16px -->
<div class="gap-6">             <!-- gap: 24px -->

<!-- Padding -->
<div class="p-4">               <!-- padding: 16px -->
<div class="px-4 py-6">         <!-- padding: 24px 16px -->
<div class="pt-4 pr-6 pb-4 pl-6"> <!-- individual edges -->
```

## Differences from Other Formats

| Aspect | Inline Styles | Tailwind |
|--------|---------------|----------|
| Styling | `style={{gap: '24px'}}` | `class="gap-6"` |
| Maintenance | Hard to maintain | Easy to scan/modify |
| Bundle size | All styles in JS | Purged CSS |
| Design system | Custom values | Standardized scale |
| Readability | Verbose | Concise |

## Workflow

### 1. Extract Layout from Figma

```
Figma Plugin → Extract Layout
→ Saves to .design/layouts/pricing-page.json
```

### 2. Transform to Tailwind

```bash
node ~/.claude/shared-modules/design-system/layout-to-tailwind-transformer.js \
  --layout=pricing-page \
  --format=jsx \
  --typescript
```

### 3. Import in Application

```tsx
import PricingPage from '@/components/layouts/PricingPage';

export default function Pricing() {
  return <PricingPage />;
}
```

### 4. Customize as Needed

- Add custom Tailwind classes
- Override with arbitrary values `[...]`
- Use Tailwind variants: `hover:`, `focus:`, `md:`, `dark:`
- Extract repeated patterns to components

## Tailwind Configuration

Ensure your `tailwind.config.js` includes the output directory:

```javascript
module.exports = {
  content: [
    './src/**/*.{js,jsx,ts,tsx}',
    '.design/extracted-code/tailwind/**/*.{js,jsx,ts,tsx}'
  ],
  theme: {
    extend: {
      // Add custom design tokens here
    },
  },
  plugins: [],
}
```

## Component Resolution

```json
{
  "type": "INSTANCE",
  "componentRef": {
    "name": "Button",
    "props": {
      "primary": true
    }
  }
}
```

Becomes (JSX):

```tsx
<Button primary={true} />
```

Becomes (HTML):

```html
<div class="w-[120px] h-[40px] border-2 border-dashed border-indigo-500 bg-indigo-50 flex items-center justify-center rounded text-xs font-medium text-indigo-600" data-component="Button">
  Button
</div>
```

## Programmatic API

### transformLayoutToTailwind

```javascript
const { transformLayoutToTailwind } = require('layout-to-tailwind-transformer');

const result = await transformLayoutToTailwind(layoutData, {
  outputDir: '.design/extracted-code/tailwind/layouts',
  format: 'jsx',
  typescript: true
});

// result = {
//   success: true,
//   layoutName: 'PricingPage',
//   componentName: 'PricingPage',
//   outputPath: '.design/extracted-code/tailwind/layouts/PricingPage.tsx',
//   format: 'jsx',
//   fileExtension: 'tsx',
//   dependencies: ['Button', 'Card', 'PricingTier']
// }
```

## Troubleshooting

### Classes Not Applying

**Problem**: Tailwind classes not taking effect

**Solution**: Ensure Tailwind is configured and content paths are correct:

```javascript
// tailwind.config.js
content: [
  '.design/extracted-code/tailwind/**/*.{html,tsx,jsx}'
]
```

### Spacing Doesn't Match Figma

**Problem**: Gap/padding values slightly off

**Solution**: Use exact values with brackets:

```html
<!-- Instead of gap-6 (24px) -->
<div class="gap-[28px]">
```

### Component Imports Not Found

**Problem**: Component imports fail

**Solution**: Adjust import path:

```bash
node transformer.js --layout=pricing-page --import-path="@/components"
```

### Responsive Issues

**Problem**: Layout doesn't adapt to screen size

**Solution**: Add responsive classes:

```html
<div class="flex flex-col md:flex-row gap-4 md:gap-8">
```

## Tailwind Best Practices & Edge Cases

### Spacing Scale Mapping Strategy

[Tailwind uses a 0.25rem (4px) based scale](https://v2.tailwindcss.com/docs/customizing-spacing) for consistency:

```html
<!-- Figma 24px → gap-6 (closest: 24px) -->
<div class="flex gap-6">

<!-- Figma 28px → gap-[28px] (exact with brackets) -->
<div class="flex gap-[28px]">
```

**Rule**: Use standard scale (`gap-4`, `gap-6`) for consistency. Use brackets (`gap-[28px]`) for exact Figma values.

### Gap Browser Support Edge Case

[gap with flexbox not supported in older browsers](https://tailkits.com/blog/tailwind-gap-utility-guide/):

```html
<!-- ❌ Doesn't work in IE11 -->
<div class="flex gap-4">

<!-- ✅ Fallback with margins -->
<div class="flex -mx-2">
  <div class="px-2">Item</div>
  <div class="px-2">Item</div>
</div>
```

**Modern projects**: Use `gap` freely. **Legacy support**: Use margin-based spacing.

### Responsive Design (Mobile-First)

[Tailwind is mobile-first](https://tailwindcss.com/docs/gap) - unprefixed styles apply to all sizes:

```html
<!-- ❌ Wrong: Desktop-first thinking -->
<div class="gap-8 md:gap-4">

<!-- ✅ Correct: Mobile-first approach -->
<div class="gap-4 md:gap-8">
```

**Rule**: Start with mobile, add `md:`, `lg:`, `xl:` for larger screens.

### Design Tokens with v4

[Tailwind v4 uses CSS-first tokens](https://walidezzat.hashnode.dev/tailwind-css-v4-complete-guide):

```css
@theme {
  --space-1: 0.25rem;
  --space-4: 1rem;
  --space-6: 1.5rem;
}
```

[Define tokens in tailwind.config.js with semantic names](https://www.frontendtools.tech/blog/tailwind-css-best-practices-design-system-patterns) for design system consistency.

### Nested Container Gap Issues

[Gap only affects direct children](https://blog.opinly.ai/tailwind-grid-vs-flex/):

```html
<!-- ❌ Gap won't apply to deeply nested items -->
<div class="flex gap-4">
  <div>
    <span>Nested</span>  <!-- No gap here -->
  </div>
</div>

<!-- ✅ Apply gap at correct level -->
<div class="flex gap-4">
  <span>Direct child</span>  <!-- Gap applies -->
  <span>Direct child</span>
</div>
```

### Touch Target Padding Edge Case

[Combining gap with margins can cause unexpected spacing](https://tailkits.com/blog/tailwind-gap-utility-guide/):

```html
<!-- ❌ Double spacing: gap + margin -->
<div class="flex gap-4">
  <button class="m-2">Click</button>  <!-- 16px gap + 8px margin -->
</div>

<!-- ✅ Use gap OR margin, not both -->
<div class="flex gap-4">
  <button>Click</button>  <!-- Just 16px gap -->
</div>
```

### Common Mistakes

1. **Gap on non-flex/grid**: [gap only works on flex or grid containers](https://windframe.dev/tailwind/classes/tailwind-gap)

2. **Purge configuration**: [Ensure content paths include all template files](https://www.bootstrapdash.com/blog/tailwind-css-best-practices) to avoid purging used classes

3. **Arbitrary values everywhere**: Overusing `[28px]` defeats the design system - prefer standard scale

## Related Commands

- `/design-extract` - Extract components and layouts from Figma
- `/design-layout-to-html` - Generate HTML reference files
- `/design-layout-to-jsx` - Generate React with inline styles
- `/design-transform-react` - Transform individual components

## Notes

- Generated code is production-ready but should be reviewed
- Tailwind uses mobile-first responsive design
- Use Tailwind IntelliSense extension for autocomplete
- Consider extracting repeated patterns to `@apply` in CSS
- Purge unused classes in production with proper content configuration
- **Use standard spacing scale** for consistency, brackets for exact values

## References

- [Tailwind Gap Utility](https://tailwindcss.com/docs/gap)
- [Customizing Spacing](https://v2.tailwindcss.com/docs/customizing-spacing)
- [Tailwind CSS Best Practices 2025](https://www.frontendtools.tech/blog/tailwind-css-best-practices-design-system-patterns)
- [Gap vs Space Utilities](https://blog.opinly.ai/tailwind-grid-vs-flex/)
