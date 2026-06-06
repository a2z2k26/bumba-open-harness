# Vue 3 Layout Design Principles

## Overview

This document provides Vue 3-specific layout theory and best practices for web application design. Use these principles when generating, transforming, or validating Vue Single File Component (SFC) layout code.

---

## 1. CSS Grid System with Scoped Styles

### Spacing Foundation

Vue 3 uses standard CSS with scoped styles. Follow an 8px grid system for consistency.

**Core Principle**: All spacing values use increments of 8px (8, 16, 24, 32, 48, 64)

**Vue SFC Implementation**:
```vue
<template>
  <div class="container">
    <div class="item">Item 1</div>
    <div class="item">Item 2</div>
  </div>
</template>

<style scoped>
.container {
  display: flex;
  flex-direction: column;
  gap: 8px;   /* Tight spacing */
  gap: 16px;  /* Standard spacing */
  gap: 24px;  /* Comfortable spacing */
  gap: 32px;  /* Section spacing */
}
</style>
```

**Padding Values**:
```css
.compact { padding: 8px; }
.standard { padding: 16px; }
.comfortable {
  padding: 20px 16px;  /* Vertical 20px, horizontal 16px */
}
.section { padding: 32px; }
```

---

## 2. Viewport Units & Container Queries

### Safe Area Support

Vue apps respect viewport safe areas using CSS environment variables:

```vue
<template>
  <div class="app-container">
    <header class="header">Header</header>
    <main class="content">Content</main>
  </div>
</template>

<style scoped>
.app-container {
  /* Respect iOS safe areas */
  padding-top: env(safe-area-inset-top);
  padding-bottom: env(safe-area-inset-bottom);
  padding-left: env(safe-area-inset-left);
  padding-right: env(safe-area-inset-right);
}

/* Full-bleed header */
.header {
  margin-top: calc(-1 * env(safe-area-inset-top));
  padding-top: env(safe-area-inset-top);
}
</style>
```

### Container Queries (Modern CSS)

```vue
<template>
  <div class="card-container">
    <div class="card">
      <h3 class="card-title">Title</h3>
      <p class="card-body">Description</p>
    </div>
  </div>
</template>

<style scoped>
.card-container {
  container-type: inline-size;
  container-name: card;
}

/* Responds to container width, not viewport */
@container card (min-width: 400px) {
  .card {
    display: flex;
    gap: 16px;
  }

  .card-title {
    font-size: 1.25rem;
  }
}
</style>
```

---

## 3. Responsive Design with Media Queries

### Standard Breakpoints

**Breakpoint System**:
- Mobile: < 640px
- Tablet: 640px - 1024px
- Desktop: ≥ 1024px

**Mobile-First Pattern**:
```vue
<template>
  <div class="responsive-layout">
    <aside class="sidebar">Sidebar</aside>
    <main class="main">Main</main>
  </div>
</template>

<style scoped>
/* Mobile first - column layout */
.responsive-layout {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Tablet and up - row layout */
@media (min-width: 640px) {
  .responsive-layout {
    flex-direction: row;
    gap: 24px;
  }

  .sidebar {
    width: 200px;
  }

  .main {
    flex: 1;
  }
}

/* Desktop - larger gaps */
@media (min-width: 1024px) {
  .responsive-layout {
    gap: 32px;
  }

  .sidebar {
    width: 250px;
  }
}
</style>
```

**Composition API Reactive Breakpoints**:
```vue
<script setup>
import { ref, onMounted, onUnmounted } from 'vue';

const isMobile = ref(false);
const isTablet = ref(false);

function updateBreakpoint() {
  const width = window.innerWidth;
  isMobile.value = width < 640;
  isTablet.value = width >= 640 && width < 1024;
}

onMounted(() => {
  updateBreakpoint();
  window.addEventListener('resize', updateBreakpoint);
});

onUnmounted(() => {
  window.removeEventListener('resize', updateBreakpoint);
});
</script>

<template>
  <div v-if="isMobile" class="mobile-layout">
  <div v-else-if="isTablet" class="tablet-layout">
  <div v-else class="desktop-layout">
</template>
```

---

## 4. Typography System

### Font Sizing with rem Units

**Standard Text Styles**:
```vue
<style scoped>
.text-display {
  font-size: 3.5rem;    /* 56px */
  line-height: 1.1;
}

.text-h1 {
  font-size: 2.5rem;    /* 40px */
  line-height: 1.2;
}

.text-h2 {
  font-size: 2rem;      /* 32px */
  line-height: 1.25;
}

.text-h3 {
  font-size: 1.5rem;    /* 24px */
  line-height: 1.3;
}

.text-body-lg {
  font-size: 1.125rem;  /* 18px */
  line-height: 1.5;
}

.text-body {
  font-size: 1rem;      /* 16px (default) */
  line-height: 1.5;
}

.text-small {
  font-size: 0.875rem;  /* 14px */
  line-height: 1.4;
}

.text-caption {
  font-size: 0.75rem;   /* 12px */
  line-height: 1.3;
}
</style>
```

**Font Weight Classes**:
```css
.font-light { font-weight: 300; }
.font-normal { font-weight: 400; }
.font-medium { font-weight: 500; }
.font-semibold { font-weight: 600; }
.font-bold { font-weight: 700; }
```

**Responsive Typography**:
```vue
<style scoped>
.heading {
  font-size: 1.5rem;  /* 24px mobile */
}

@media (min-width: 640px) {
  .heading {
    font-size: 2rem;  /* 32px tablet */
  }
}

@media (min-width: 1024px) {
  .heading {
    font-size: 2.5rem;  /* 40px desktop */
  }
}
</style>
```

---

## 5. Flexbox Layout Patterns

### Flex Direction & Gap

```vue
<template>
  <div class="flex-container">
    <div>Item 1</div>
    <div>Item 2</div>
    <div>Item 3</div>
  </div>
</template>

<style scoped>
/* Horizontal layout */
.flex-container {
  display: flex;
  flex-direction: row;
  gap: 16px;
}

/* Vertical layout */
.flex-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Wrap on overflow */
.flex-container {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}
</style>
```

### Justify & Align

```vue
<style scoped>
/* Main axis alignment */
.justify-start { justify-content: flex-start; }
.justify-center { justify-content: center; }
.justify-end { justify-content: flex-end; }
.justify-between { justify-content: space-between; }
.justify-around { justify-content: space-around; }

/* Cross axis alignment */
.items-start { align-items: flex-start; }
.items-center { align-items: center; }
.items-end { align-items: flex-end; }
.items-stretch { align-items: stretch; }
</style>
```

---

## 6. CSS Grid Layout

### Grid Template Columns

```vue
<template>
  <div class="grid-container">
    <div class="grid-item">1</div>
    <div class="grid-item">2</div>
    <div class="grid-item">3</div>
  </div>
</template>

<style scoped>
/* Fixed columns */
.grid-container {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

/* Responsive columns */
.grid-container {
  display: grid;
  grid-template-columns: 1fr;  /* Mobile: 1 column */
  gap: 16px;
}

@media (min-width: 640px) {
  .grid-container {
    grid-template-columns: repeat(2, 1fr);  /* Tablet: 2 columns */
    gap: 24px;
  }
}

@media (min-width: 1024px) {
  .grid-container {
    grid-template-columns: repeat(3, 1fr);  /* Desktop: 3 columns */
    gap: 32px;
  }
}

/* Auto-fit columns */
.grid-container {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 24px;
}
</style>
```

### Grid Spanning

```vue
<style scoped>
/* 12-column grid */
.grid-12 {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 16px;
}

.span-4 { grid-column: span 4; }   /* 4 columns */
.span-6 { grid-column: span 6; }   /* 6 columns */
.span-8 { grid-column: span 8; }   /* 8 columns */
.span-12 { grid-column: span 12; } /* Full width */

/* Responsive spanning */
.card {
  grid-column: span 12;  /* Full width mobile */
}

@media (min-width: 640px) {
  .card {
    grid-column: span 6;  /* Half width tablet */
  }
}

@media (min-width: 1024px) {
  .card {
    grid-column: span 4;  /* Third width desktop */
  }
}
</style>
```

---

## 7. Spacing System

### Padding & Margin Utilities

```vue
<style scoped>
/* Padding */
.p-1 { padding: 8px; }
.p-2 { padding: 16px; }
.p-3 { padding: 24px; }
.p-4 { padding: 32px; }

/* Directional padding */
.px-2 { padding-left: 16px; padding-right: 16px; }
.py-2 { padding-top: 16px; padding-bottom: 16px; }

.pt-2 { padding-top: 16px; }
.pr-2 { padding-right: 16px; }
.pb-2 { padding-bottom: 16px; }
.pl-2 { padding-left: 16px; }

/* Margin (same pattern) */
.m-1 { margin: 8px; }
.m-2 { margin: 16px; }
.mx-auto { margin-left: auto; margin-right: auto; }
</style>
```

---

## 8. Touch Targets & Interactive Elements

### Minimum Touch Target Size

**Guideline**: Minimum 44×44px for touch targets

```vue
<template>
  <!-- ❌ Too small -->
  <button class="btn-small">
    <icon-heart class="icon-sm" />
  </button>

  <!-- ✅ Meets 44×44px minimum -->
  <button class="btn-standard">
    <icon-heart class="icon-sm" />
  </button>
</template>

<style scoped>
.btn-small {
  width: 24px;
  height: 24px;
  padding: 0;
}

.btn-standard {
  min-width: 44px;
  min-height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.icon-sm {
  width: 24px;
  height: 24px;
}
</style>
```

---

## 9. Visual Hierarchy

### Z-Index Layering

```vue
<template>
  <div class="container">
    <div class="layer-base">Base</div>
    <div class="layer-middle">Middle</div>
    <div class="layer-top">Top</div>
  </div>
</template>

<style scoped>
.container {
  position: relative;
}

.layer-base {
  position: absolute;
  z-index: 0;
}

.layer-middle {
  position: absolute;
  z-index: 10;
}

.layer-top {
  position: absolute;
  z-index: 20;
}
</style>
```

### Box Shadows & Elevation

```vue
<style scoped>
/* Subtle elevation */
.shadow-sm {
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
}

/* Card elevation */
.shadow-md {
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

/* Prominent elevation */
.shadow-lg {
  box-shadow: 0 10px 15px rgba(0, 0, 0, 0.15);
}

.shadow-xl {
  box-shadow: 0 20px 25px rgba(0, 0, 0, 0.15);
}
</style>
```

---

## 10. Scoped Styles Best Practices

### Component Style Isolation

```vue
<template>
  <div class="card">
    <h3 class="card-title">{{ title }}</h3>
    <p class="card-body">{{ body }}</p>
  </div>
</template>

<style scoped>
/* ✅ Scoped: Only affects this component */
.card {
  padding: 16px;
  border-radius: 8px;
  background: white;
}

.card-title {
  font-size: 1.25rem;
  margin-bottom: 8px;
}

.card-body {
  color: #666;
}
</style>
```

### Deep Selectors for Child Components

```vue
<template>
  <div class="parent">
    <child-component />
  </div>
</template>

<style scoped>
/* ❌ Won't reach child component internals */
.parent .child-button {
  color: red;
}

/* ✅ Reaches into child components */
.parent :deep(.child-button) {
  color: red;
}

/* ✅ Global selector (use sparingly) */
:global(.some-global-class) {
  color: blue;
}
</style>
```

---

## 11. Common Layout Patterns

### Card Component
```vue
<template>
  <div class="card">
    <h3 class="card-title">{{ title }}</h3>
    <p class="card-description">{{ description }}</p>
    <button class="card-button" @click="handleClick">
      Action
    </button>
  </div>
</template>

<style scoped>
.card {
  background: white;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.card-title {
  font-size: 1.25rem;
  font-weight: 600;
  margin: 0;
}

.card-description {
  color: #666;
  margin: 0;
}

.card-button {
  align-self: flex-start;
  padding: 8px 16px;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}

.card-button:hover {
  background: #2563eb;
}
</style>
```

### Form Layout
```vue
<template>
  <form @submit.prevent="handleSubmit" class="form">
    <div class="form-group">
      <label for="name" class="form-label">Name</label>
      <input
        id="name"
        v-model="form.name"
        type="text"
        class="form-input"
      />
    </div>

    <div class="form-group">
      <label for="email" class="form-label">Email</label>
      <input
        id="email"
        v-model="form.email"
        type="email"
        class="form-input"
      />
    </div>

    <button type="submit" class="form-submit">
      Submit
    </button>
  </form>
</template>

<style scoped>
.form {
  display: flex;
  flex-direction: column;
  gap: 24px;
  max-width: 400px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-label {
  font-size: 0.875rem;
  font-weight: 500;
  color: #374151;
}

.form-input {
  padding: 10px 12px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 1rem;
}

.form-input:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.form-submit {
  padding: 10px 16px;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 1rem;
  cursor: pointer;
}

.form-submit:hover {
  background: #2563eb;
}
</style>
```

### Navigation Layout
```vue
<template>
  <nav class="nav">
    <div class="nav-container">
      <div class="nav-content">
        <a href="#" class="nav-logo">Logo</a>
        <div class="nav-links">
          <a href="#" class="nav-link">Home</a>
          <a href="#" class="nav-link">About</a>
          <a href="#" class="nav-link">Contact</a>
        </div>
      </div>
      <button class="nav-menu" @click="toggleMenu">
        Menu
      </button>
    </div>
  </nav>
</template>

<style scoped>
.nav {
  background: white;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.nav-container {
  max-width: 1280px;
  margin: 0 auto;
  padding: 0 16px;
}

.nav-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
}

.nav-logo {
  font-size: 1.25rem;
  font-weight: 700;
  text-decoration: none;
  color: #111;
}

.nav-links {
  display: none;
  gap: 24px;
}

@media (min-width: 768px) {
  .nav-links {
    display: flex;
  }
}

.nav-link {
  text-decoration: none;
  color: #666;
  font-weight: 500;
}

.nav-link:hover {
  color: #111;
}

.nav-menu {
  display: block;
  padding: 8px;
  background: none;
  border: none;
  cursor: pointer;
}

@media (min-width: 768px) {
  .nav-menu {
    display: none;
  }
}
</style>
```

---

## 12. Performance Considerations

### Scoped Style Performance

Use class selectors instead of element selectors in scoped styles:

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

### CSS Custom Properties

```vue
<script setup>
import { ref } from 'vue';

const theme = ref({
  primary: '#3b82f6',
  spacing: '16px',
});
</script>

<template>
  <div
    class="themed"
    :style="{
      '--color-primary': theme.primary,
      '--spacing': theme.spacing,
    }"
  >
    Content
  </div>
</template>

<style scoped>
.themed {
  color: var(--color-primary);
  padding: var(--spacing);
}
</style>
```

---

## Quick Reference Checklist

### Vue Layout Validation

- [ ] Uses 8px spacing scale (8, 16, 24, 32, 48, 64)
- [ ] Scoped styles for component isolation
- [ ] Mobile-first responsive design
- [ ] Touch targets minimum 44×44px
- [ ] Uses rem units for font sizes (scalable)
- [ ] Proper use of :deep() for child component styling
- [ ] Semantic HTML structure
- [ ] Accessible form labels and ARIA attributes
- [ ] Flexbox gap for spacing (modern browsers)
- [ ] Consistent corner radii (8-12px for cards)
- [ ] Z-index system for layering
- [ ] CSS custom properties for theming

---

## Sources

- **Vue.js Official Documentation**
- **Vue 3 Composition API Guide**
- **MDN Web Docs**: CSS Flexbox & Grid
- **Web Content Accessibility Guidelines (WCAG)**
- **Material Design Guidelines** (for spacing principles)

**Last Updated**: January 2026
