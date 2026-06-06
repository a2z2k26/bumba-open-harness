# /transform-flutter - Transform Components to Flutter

Transform Figma components from the registry into production-ready Flutter/Dart code.

## Purpose

This skill reads components from `.design/componentRegistry.json` and transforms them into Flutter widgets with:
- Full content extraction from Figma JSON
- Canonical naming conventions (snake_case for files, PascalCase for classes)
- Dart StatelessWidget/StatefulWidget
- Automatic registry tracking
- Material Design integration
- Multi-framework support

## Prerequisites

- `.design/componentRegistry.json` exists and is populated
- Component raw data files exist in `.design/components/`

## Quick Start

```bash
# Transform single component
node ~/.claude/wrappers/transform-flutter.js --component=Button

# Transform all components
node ~/.claude/wrappers/transform-flutter.js --all

# Force re-transform
node ~/.claude/wrappers/transform-flutter.js --component=Button --force
```

## Output

- **File naming**: `button.dart` (snake_case)
- **Location**: `lib/design_system/components/`
- **Format**: Flutter StatelessWidget with Material Design

## Cross-Framework

Same component can be transformed for multiple frameworks:
- React: `Button.tsx` (PascalCase)
- Flutter: `button.dart` (snake_case)
- SwiftUI: `Button.swift` (PascalCase)

## Sync-Cascade Integration

Integrates with `/design:sync-cascade` for automatic component updates.

### CLI Options

```bash
# Basic transform
node ~/.claude/wrappers/transform-flutter.js --component=Button

# Replace mode with story updates
node ~/.claude/wrappers/transform-flutter.js --component=Button --mode=replace --update-storybook

# Batch mode
node ~/.claude/wrappers/transform-flutter.js --batch=Button,Card,Modal --mode=replace
```

**Replace mode features:**
- Automatic backups to `.design/backups/TIMESTAMP/`
- Replaces existing components
- Updates widget tests with `--update-storybook`
- Batch processing with `--batch=Component1,Component2`

## Related Skills

- `/design:sync-cascade` - Orchestrate automatic updates
- `/design:sync-monitor` - Monitor Figma sync
- `/transform-react-native` - Transform to React Native
- `/transform-swiftui` - Transform to SwiftUI
- `/extract-design` - Extract from Figma
