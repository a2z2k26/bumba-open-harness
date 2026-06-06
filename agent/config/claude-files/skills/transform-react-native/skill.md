# /transform-react-native - Transform Components to React Native

Transform Figma components from the registry into production-ready React Native code.

## Purpose

This skill reads components from `.design/componentRegistry.json` and transforms them into React Native components with:
- Full content extraction from Figma JSON
- Canonical naming conventions (PascalCase)
- TypeScript with React Native types
- Automatic registry tracking
- StyleSheet definitions
- Multi-framework support

## Prerequisites

- `.design/componentRegistry.json` exists and is populated
- Component raw data files exist in `.design/components/`

## Quick Start

```bash
# Transform single component
node ~/.claude/wrappers/transform-react-native.js --component=Button

# Transform all components
node ~/.claude/wrappers/transform-react-native.js --all

# Force re-transform
node ~/.claude/wrappers/transform-react-native.js --component=Button --force
```

## Output

- **File naming**: `Button.tsx` (PascalCase)
- **Location**: `src/design-system/components/`
- **Format**: React Native component with StyleSheet

## Cross-Framework

Same component can be transformed for multiple frameworks:
- React: `Button.tsx` (web)
- React Native: `Button.tsx` (mobile)
- Flutter: `button.dart`

## Sync-Cascade Integration

Integrates with `/design:sync-cascade` for automatic component updates.

### CLI Options

```bash
# Basic transform
node ~/.claude/wrappers/transform-react-native.js --component=Button

# Replace mode with story updates
node ~/.claude/wrappers/transform-react-native.js --component=Button --mode=replace --update-storybook

# Batch mode
node ~/.claude/wrappers/transform-react-native.js --batch=Button,Card,Modal --mode=replace
```

**Replace mode features:**
- Automatic backups to `.design/backups/TIMESTAMP/`
- Replaces existing components
- Updates Storybook stories with `--update-storybook`
- Batch processing with `--batch=Component1,Component2`

## Related Skills

- `/design:sync-cascade` - Orchestrate automatic updates
- `/design:sync-monitor` - Monitor Figma sync
- `/transform-react` - Transform to React (web)
- `/transform-flutter` - Transform to Flutter
- `/extract-design` - Extract from Figma
