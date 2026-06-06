# /transform-vue - Transform Components to Vue

Transform Figma components from the registry into production-ready Vue 3 code.

## Purpose

This skill reads components from `.design/componentRegistry.json` and transforms them into Vue 3 Composition API code with:
- Full content extraction from Figma JSON
- Canonical naming conventions (kebab-case for files, PascalCase for components)
- TypeScript support with `<script setup lang="ts">`
- Automatic registry tracking
- Scoped styles
- Multi-framework support (same component → multiple frameworks)

## Prerequisites

- `.design/componentRegistry.json` exists and is populated
- Component raw data files exist in `.design/components/`

## Quick Start

```bash
# Transform single component
node ~/.claude/wrappers/transform-vue.js --component=Button

# Transform all components
node ~/.claude/wrappers/transform-vue.js --all

# Force re-transform
node ~/.claude/wrappers/transform-vue.js --component=Button --force
```

## Output

- **File naming**: `button.vue` (kebab-case)
- **Location**: `src/design-system/components/`
- **Format**: Vue 3 SFC with TypeScript and scoped styles

## Cross-Framework

Same component can be transformed for multiple frameworks:
- React: `Button.tsx` (PascalCase)
- Vue: `button.vue` (kebab-case)
- Angular: `button.component.ts` (kebab-case)

## Sync-Cascade Integration

This skill integrates with the `/design:sync-cascade` workflow for automatic component updates when Figma designs change.

### Replace Mode

When invoked with `--mode=replace`, the transformer:
1. **Creates automatic backup** to `.design/backups/TIMESTAMP/` before any changes
2. **Replaces existing component** files instead of skipping if already exists
3. **Updates associated stories** if `--update-storybook` flag is provided
4. **Preserves user modifications** in separate files

```bash
# Replace mode example (called by sync-cascade)
node ~/.claude/wrappers/transform-vue.js --component=Button --mode=replace --update-storybook
```

### Batch Processing

Process multiple components in a single invocation:

```bash
# Batch transform changed components
node ~/.claude/wrappers/transform-vue.js --batch=Button,Card,Modal --mode=replace --update-storybook
```

### CLI Options

```bash
# Single component transform
node ~/.claude/wrappers/transform-vue.js --component=Button

# Replace mode with Storybook update
node ~/.claude/wrappers/transform-vue.js --component=Button --mode=replace --update-storybook

# Batch mode
node ~/.claude/wrappers/transform-vue.js --batch=Button,Card,Modal --mode=replace

# Disable backup (not recommended)
node ~/.claude/wrappers/transform-vue.js --component=Button --mode=replace --no-backup
```

## Related Skills

- `/design:sync-cascade` - Orchestrate automatic component updates
- `/design:sync-monitor` - Monitor Figma sync status
- `/transform-react` - Transform to React
- `/transform-angular` - Transform to Angular
- `/extract-design` - Extract from Figma
