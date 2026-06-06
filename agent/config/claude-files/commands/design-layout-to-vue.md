---
name: design-layout-to-vue
description: Transform Figma layouts to Vue 3 SFC with scoped styles, Composition API, and flexbox/grid layouts
allowed-tools: Read, Write, Bash
instructions: design-layout-to-vue-principles.md
---

# design-layout-to-vue - Transform Figma Layouts to Vue Components

Generate production-ready Vue 3 Single File Components (SFC) from extracted Figma layout data.

**Design Principles**: This skill follows Vue 3-specific layout design principles including 8px CSS grid, scoped styles performance, :deep() selectors, Composition API patterns, and touch targets. See `~/.claude/instructions/design-layout-to-vue-principles.md` for complete guidelines.

## Purpose

Convert Figma layouts into Vue 3 components with:
- Vue 3 Composition API or Options API
- Scoped CSS styles
- TypeScript support
- Design system component imports
- Production-ready .vue files

## Prerequisites

- Layout data extracted from Figma (`.design/layouts/`)
- Component registry populated (`.design/componentRegistry.json`)
- Design system components available for imports
- Vue 3 project setup

## Usage

### Transform Single Layout (Composition API)

```bash
node ~/.claude/shared-modules/design-system/layout-to-vue-transformer.js \
  --layout=PricingPage \
  --composition-api \
  --typescript
```

### Transform Single Layout (Options API)

```bash
node ~/.claude/shared-modules/design-system/layout-to-vue-transformer.js \
  --layout=PricingPage \
  --no-composition-api
```

### Transform All Layouts

```bash
for layout in .design/layouts/*.json; do
  node ~/.claude/shared-modules/design-system/layout-to-vue-transformer.js \
    --layout=$(basename "$layout" .json) \
    --composition-api \
    --typescript
done
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--layout` | (required) | Layout name or file path |
| `--typescript` | `true` | Generate TypeScript |
| `--composition-api` | `true` | Use Composition API (vs Options API) |
| `--output-dir` | `.design/extracted-code/vue/layouts` | Output directory |

## Output

### File Structure

```
.design/extracted-code/vue/layouts/
├── PricingPage.vue
├── Homepage.vue
└── DashboardLayout.vue
```

### Generated Component Example (Composition API)

```vue
<!--
  PricingPage Layout Component
  Generated from Figma layout extraction

  This component uses transformed design system components.
  Generated: 2026-01-08T...
-->

<template>
  <div class="frame-0-0">
    <pricing-tier />
    <pricing-tier />
    <pricing-tier />
  </div>
</template>

<script lang="ts" setup>
import PricingTier from './PricingTier.vue';

interface Props {
  // Add custom props here if needed
}

const props = defineProps<Props>();
</script>

<style scoped>
.frame-0-0 {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  gap: 32px;
  padding: 64px 32px 64px 32px;
}
</style>
```

### Generated Component Example (Options API)

```vue
<!--
  PricingPage Layout Component
  Generated from Figma layout extraction
-->

<template>
  <div class="frame-0-0">
    <pricing-tier />
    <pricing-tier />
    <pricing-tier />
  </div>
</template>

<script lang="ts">
import { defineComponent } from 'vue';
import PricingTier from './PricingTier.vue';

export default defineComponent({
  name: 'PricingPage',
  components: {
    PricingTier
  },
  props: {
    // Add custom props here if needed
  },
  setup(props) {
    // Component logic here
    return {};
  }
});
</script>

<style scoped>
.frame-0-0 {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  gap: 32px;
  padding: 64px 32px 64px 32px;
}
</style>
```

## Key Features

### Vue 3 Composition API

Modern, TypeScript-friendly approach:

```vue
<script setup lang="ts">
import { ref, computed } from 'vue';
import Button from './Button.vue';

interface Props {
  title?: string;
}

const props = defineProps<Props>();
const count = ref(0);
const doubled = computed(() => count.value * 2);
</script>
```

### Scoped Styles

CSS that only applies to this component:

```vue
<style scoped>
.frame-0-0 {
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding: 16px;
}

/* Global selector */
:global(.some-global-class) {
  color: red;
}
</style>
```

### Component Registration

```vue
<script setup>
// Automatic registration with script setup
import PricingTier from './PricingTier.vue';
</script>

<template>
  <!-- Use kebab-case in template -->
  <pricing-tier />
</template>
```

### Props Binding

```vue
<template>
  <!-- String props -->
  <button text="Click me" />

  <!-- Dynamic props with : or v-bind -->
  <button :primary="true" />
  <button :count="42" />

  <!-- Boolean props (shorthand) -->
  <button primary />
</template>
```

### Flexbox Layout

Figma auto-layout converts to CSS flexbox:

```css
.frame {
  display: flex;
  flex-direction: column;  /* or row */
  justify-content: center; /* primary axis */
  align-items: center;     /* cross axis */
  gap: 24px;              /* spacing between items */
  padding: 16px 24px 16px 24px;
}
```

## Differences from Other Formats

| Aspect | React | Vue |
|--------|-------|-----|
| Component | `.tsx`/`.jsx` | `.vue` SFC |
| Styling | Inline styles / CSS-in-JS | Scoped CSS |
| Template | JSX | Template syntax |
| Props | TypeScript interface | `defineProps` |
| Reactivity | `useState` | `ref`, `reactive` |

## Workflow

### 1. Extract Layout from Figma

```
Figma Plugin → Extract Layout
→ Saves to .design/layouts/pricing-page.json
```

### 2. Transform to Vue

```bash
node ~/.claude/shared-modules/design-system/layout-to-vue-transformer.js \
  --layout=pricing-page \
  --composition-api \
  --typescript
```

### 3. Import in Vue App

```vue
<script setup lang="ts">
import PricingPage from '@/layouts/PricingPage.vue';
</script>

<template>
  <PricingPage />
</template>
```

### 4. Customize as Needed

- Add reactive state with `ref`, `reactive`
- Add computed properties
- Add watchers
- Connect to stores (Pinia/Vuex)
- Add lifecycle hooks
- Add emits for events

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

```vue
<button :primary="true" text="Get Started" />
```

## Programmatic API

### transformLayoutToVue

```javascript
const { transformLayoutToVue } = require('layout-to-vue-transformer');

const result = await transformLayoutToVue(layoutData, {
  outputDir: '.design/extracted-code/vue/layouts',
  typescript: true,
  compositionAPI: true
});

// result = {
//   success: true,
//   layoutName: 'PricingPage',
//   componentName: 'PricingPage',
//   outputPath: '.design/extracted-code/vue/layouts/PricingPage.vue',
//   fileExtension: 'vue',
//   dependencies: ['Button', 'Card', 'PricingTier'],
//   typescript: true,
//   compositionAPI: true
// }
```

## Troubleshooting

### Component Not Registered

**Problem**: Component not found in template

**Solution**: Import and register component:

```vue
<script setup>
import PricingTier from './PricingTier.vue';
</script>
```

### Style Not Scoped

**Problem**: Styles leaking to other components

**Solution**: Ensure `scoped` attribute is present:

```vue
<style scoped>
/* ... */
</style>
```

### TypeScript Errors

**Problem**: Type errors in script section

**Solution**: Ensure proper type definitions:

```vue
<script lang="ts" setup>
interface Props {
  title?: string;
  count?: number;
}

const props = defineProps<Props>();
</script>
```

### Props Not Reactive

**Problem**: Props not updating in template

**Solution**: Use `:` for dynamic binding:

```vue
<!-- Wrong: static string -->
<button primary="true" />

<!-- Right: dynamic boolean -->
<button :primary="true" />
```

### CSS Class Naming Conflicts

**Problem**: Class names conflict across layouts

**Solution**: Classes are auto-generated as `frame-depth-index`. Consider using CSS modules or renaming:

```vue
<style scoped>
.pricing-page-container {
  /* More semantic naming */
}
</style>
```

## Vue 3 Best Practices

### Use Composition API

```vue
<script setup lang="ts">
// More concise, better TypeScript support
import { ref, computed } from 'vue';

const count = ref(0);
const doubled = computed(() => count.value * 2);
</script>
```

### Define Props with Types

```vue
<script setup lang="ts">
interface Props {
  title: string;
  count?: number;
}

const props = defineProps<Props>();
</script>
```

### Define Emits

```vue
<script setup lang="ts">
const emit = defineEmits<{
  update: [value: string];
  close: [];
}>();

function handleClick() {
  emit('update', 'new value');
}
</script>
```

### Use Provide/Inject for Deep Nesting

```vue
<script setup>
import { provide } from 'vue';

provide('theme', 'dark');
</script>
```

## Vue 3 Best Practices & Edge Cases

### Scoped CSS Performance

[Prefer class selectors over element selectors](https://vuejs.org/api/sfc-css-features.html) in scoped styles:

```vue
<style scoped>
/* ❌ Slow: Element-attribute selectors */
div[data-v-123] { }
p[data-v-123] { }

/* ✅ Fast: Class-attribute selectors */
.container[data-v-123] { }
.text[data-v-123] { }
</style>
```

**Rule**: [Large numbers of element selectors are slow](https://vuejs.org/v2/style-guide/) - always use classes in scoped styles.

### Parent-Child Scoping Edge Case

[Child root node affected by both parent and child scoped CSS](https://vue-loader.vuejs.org/guide/scoped-css.html):

```vue
<!-- Parent.vue -->
<style scoped>
.child-component {
  margin: 20px;  /* Affects child root! */
}
</style>

<!-- Child.vue (root element gets parent's styles) -->
<template>
  <div class="child-root">...</div>
</template>
```

**By design**: Parent can style child root element for layout purposes.

### Deep Selectors for Child Components

[Use ::v-deep for styling nested components](https://vuejs.org/api/sfc-css-features.html):

```vue
<style scoped>
/* ❌ Won't reach child component internals */
.wrapper .child-button {
  color: red;
}

/* ✅ Reaches into child components */
.wrapper ::v-deep(.child-button) {
  color: red;
}
</style>
```

### Composition API Feature Order

[Establish consistent ordering](https://medium.com/@davisaac8/design-patterns-and-best-practices-with-the-composition-api-in-vue-3-77ba95cb4d63):

```vue
<script setup lang="ts">
// 1. Imports
import { ref, computed, onMounted } from 'vue';

// 2. Props & Emits
interface Props { ... }
const props = defineProps<Props>();
const emit = defineEmits<{ ... }>();

// 3. Refs & Reactive
const count = ref(0);

// 4. Computed
const doubled = computed(() => count.value * 2);

// 5. Methods
function increment() { count.value++; }

// 6. Lifecycle Hooks
onMounted(() => { ... });
</script>
```

**Rule**: Maintain team-wide consistency in feature ordering for readability.

### Scoping Strategy by Component Type

[Apply scoping based on component purpose](https://vuejs.org/v2/style-guide/):

```vue
<!-- ✅ Top-level App.vue: Global styles OK -->
<style>
body { margin: 0; }
</style>

<!-- ✅ Layout components: Global or scoped -->
<style>
.main-layout { ... }
</style>

<!-- ✅ All other components: Always scoped -->
<style scoped>
.pricing-card { ... }
</style>
```

### Common Mistakes

1. **Element selectors in scoped styles**: [Considerably slower than class selectors](https://vuejs.org/api/sfc-css-features.html)

2. **Missing scoped attribute**: [Styles leak to entire app](https://icreatorstudio.com/blog/vue-component-best-practices-with-examples) without `<style scoped>`

3. **Options API in new projects**: [Composition API provides better TypeScript support](https://vuejs.org/guide/extras/composition-api-faq) and organization

4. **Incorrect v-bind syntax**: Static strings don't react - use `:prop` for dynamic values

## Related Commands

- `/design-extract` - Extract components and layouts from Figma
- `/design-layout-to-html` - Generate HTML reference files
- `/design-layout-to-jsx` - Generate React components
- `/design-transform-vue` - Transform individual components

## Notes

- Generated components are production-ready but should be reviewed
- Use Volar/Vue Language Features extension in VS Code
- **Scoped styles** provide component isolation
- **Composition API recommended** for new projects with better TypeScript support
- **Use class selectors** in scoped styles for performance
- Maintain consistent feature ordering across components
- Consider using Pinia for state management
- Use Vue DevTools for debugging

## References

- [SFC CSS Features](https://vuejs.org/api/sfc-css-features.html)
- [Vue Style Guide](https://vuejs.org/v2/style-guide/)
- [Scoped CSS](https://vue-loader.vuejs.org/guide/scoped-css.html)
- [Composition API Best Practices](https://medium.com/@davisaac8/design-patterns-and-best-practices-with-the-composition-api-in-vue-3-77ba95cb4d63)
- [Vue Component Best Practices](https://icreatorstudio.com/blog/vue-component-best-practices-with-examples)
