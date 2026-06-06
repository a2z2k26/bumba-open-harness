# /transform-jetpack-compose - Transform Components to Jetpack Compose

Transform Figma components from the registry into production-ready Jetpack Compose code.

## Purpose

This skill reads components from `.design/componentRegistry.json` and transforms them into Jetpack Compose composables with:
- Full content extraction from Figma JSON
- Canonical naming conventions (PascalCase)
- Kotlin with @Composable functions
- Automatic registry tracking
- Material3 theming
- Multi-framework support

## Prerequisites

- `.design/componentRegistry.json` exists and is populated
- Component raw data files exist in `.design/components/`

## Quick Start

```bash
# Transform single component
node ~/.claude/wrappers/transform-jetpack-compose.js --component=Button

# Transform all components
node ~/.claude/wrappers/transform-jetpack-compose.js --all

# Force re-transform
node ~/.claude/wrappers/transform-jetpack-compose.js --component=Button --force
```

## Output

- **File naming**: `Button.kt` (PascalCase)
- **Location**: `app/src/main/java/com/yourapp/designsystem/components/`
- **Format**: Kotlin @Composable function with Material3

## Cross-Framework

Same component can be transformed for multiple frameworks:
- SwiftUI: `Button.swift` (iOS native)
- Jetpack Compose: `Button.kt` (Android native)
- Flutter: `button.dart` (mobile cross-platform)

## Sync-Cascade Integration

Integrates with `/design:sync-cascade` for automatic component updates.

### CLI Options

```bash
# Basic transform
node ~/.claude/wrappers/transform-jetpack-compose.js --component=Button

# Replace mode with preview updates
node ~/.claude/wrappers/transform-jetpack-compose.js --component=Button --mode=replace --update-storybook

# Batch mode
node ~/.claude/wrappers/transform-jetpack-compose.js --batch=Button,Card,Modal --mode=replace
```

**Replace mode features:**
- Automatic backups to `.design/backups/TIMESTAMP/`
- Replaces existing components
- Updates @Preview composables with `--update-storybook`
- Batch processing with `--batch=Component1,Component2`

## Related Skills

- `/design:sync-cascade` - Orchestrate automatic updates
- `/design:sync-monitor` - Monitor Figma sync
- `/transform-swiftui` - Transform to SwiftUI (iOS)
- `/transform-flutter` - Transform to Flutter
- `/extract-design` - Extract from Figma
