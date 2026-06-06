# Workflow: Figma to React Code

Complete workflow for transforming Figma designs into production React code.

## Steps

### 1. Initialize Design Bridge
```bash
/design-init
```
Creates `.design/` structure, component registry, token definitions.

### 2. Extract from Figma
Use Figma plugin to sync designs to Design Bridge server.
Components and layouts are automatically extracted to `.design/components/` and `.design/layouts/`.

### 3. Transform Layout to React
```bash
/design-layout-to-jsx
```
Converts Figma layout to React/JSX with proper component structure.

**Output**: `.design/extracted-code/react/layouts/YourLayout.tsx`

### 4. Transform Tokens to React
```bash
/design-transform-react
```
Converts design tokens to React theme provider and styled-components.

**Output**: `.design/extracted-code/react/theme.ts`

### 5. Auto-Generated Storybook
Hook `on-component-transform.js` automatically generates Storybook stories.

**Output**: `.design/stories/YourLayout.stories.tsx`

### 6. Refine Visual Parity
```bash
/design-layout-refine
```
Iteratively improves layout until 98%+ visual match with Figma.

### 7. Promote to Production
```bash
/design-promote
```
Moves finalized components from `.design/extracted-code/` to `src/` directory.

## Hooks That Run Automatically

- `on-component-extract.js` - Updates registry when Figma syncs
- `on-component-transform.js` - Generates Storybook stories
- `on-layout-transform-complete.js` - Validates output
- `on-sync-changes.js` - Detects Figma changes

## Expected Duration

- First time: ~15 minutes (includes setup)
- Subsequent layouts: ~5 minutes per layout

## Common Issues

**Issue**: Storybook stories not generating
**Fix**: Check `on-component-transform.js` hook is enabled

**Issue**: Visual parity < 95%
**Fix**: Run `/design-layout-refine` for iterative improvement

## Related Workflows

- [Vue Version](./design-figma-to-vue.md)
- [Angular Version](./design-figma-to-angular.md)
- [Design System Setup](./design-system-setup.md)
