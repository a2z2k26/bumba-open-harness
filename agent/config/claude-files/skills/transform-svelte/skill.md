# /transform-svelte - Transform Components to Svelte

Transform Figma components from the registry into production-ready Svelte code.

## Purpose

This skill reads components from `.design/componentRegistry.json` and transforms them into Svelte components with:
- Full content extraction from Figma JSON
- Canonical naming conventions (kebab-case for files, PascalCase for components)
- TypeScript support
- Automatic registry tracking
- Scoped styles
- Multi-framework support

## Prerequisites

- `.design/componentRegistry.json` exists and is populated
- Component raw data files exist in `.design/components/`

## Quick Start

```bash
# Transform single component
node ~/.claude/wrappers/transform-svelte.js --component=Button

# Transform all components
node ~/.claude/wrappers/transform-svelte.js --all

# Force re-transform
node ~/.claude/wrappers/transform-svelte.js --component=Button --force
```

## Output

- **File naming**: `button.svelte` (kebab-case)
- **Location**: `src/design-system/components/`
- **Format**: Svelte component with TypeScript and scoped styles

## Cross-Framework

Same component can be transformed for multiple frameworks:
- React: `Button.tsx` (PascalCase)
- Vue: `button.vue` (kebab-case)
- Svelte: `button.svelte` (kebab-case)

## Sync-Cascade Integration

Integrates with `/design:sync-cascade` for automatic component updates.

### CLI Options

```bash
# Basic transform
node ~/.claude/wrappers/transform-svelte.js --component=Button

# Replace mode with story updates
node ~/.claude/wrappers/transform-svelte.js --component=Button --mode=replace --update-storybook

# Batch mode
node ~/.claude/wrappers/transform-svelte.js --batch=Button,Card,Modal --mode=replace
```

**Replace mode features:**
- Automatic backups to `.design/backups/TIMESTAMP/`
- Replaces existing components
- Updates Storybook stories with `--update-storybook`
- Batch processing with `--batch=Component1,Component2`

## Related Skills

- `/design:sync-cascade` - Orchestrate automatic updates
- `/design:sync-monitor` - Monitor Figma sync
- `/transform-react` - Transform to React
- `/transform-vue` - Transform to Vue
- `/extract-design` - Extract from Figma
