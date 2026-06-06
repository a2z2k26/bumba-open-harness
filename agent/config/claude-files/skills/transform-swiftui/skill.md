# /transform-swiftui - Transform Components to SwiftUI

Transform Figma components from the registry into production-ready SwiftUI code.

## Purpose

This skill reads components from `.design/componentRegistry.json` and transforms them into SwiftUI views with:
- Full content extraction from Figma JSON
- Canonical naming conventions (PascalCase)
- Swift with SwiftUI View protocol
- Automatic registry tracking
- ViewModifiers for styling
- Multi-framework support

## Prerequisites

- `.design/componentRegistry.json` exists and is populated
- Component raw data files exist in `.design/components/`

## Quick Start

```bash
# Transform single component
node ~/.claude/wrappers/transform-swiftui.js --component=Button

# Transform all components
node ~/.claude/wrappers/transform-swiftui.js --all

# Force re-transform
node ~/.claude/wrappers/transform-swiftui.js --component=Button --force
```

## Output

- **File naming**: `Button.swift` (PascalCase)
- **Location**: `DesignSystem/Components/`
- **Format**: SwiftUI View conforming to View protocol

## Cross-Framework

Same component can be transformed for multiple frameworks:
- React Native: `Button.tsx` (mobile cross-platform)
- SwiftUI: `Button.swift` (iOS/macOS native)
- Flutter: `button.dart` (mobile cross-platform)

## Sync-Cascade Integration

Integrates with `/design:sync-cascade` for automatic component updates.

### CLI Options

```bash
# Basic transform
node ~/.claude/wrappers/transform-swiftui.js --component=Button

# Replace mode with preview updates
node ~/.claude/wrappers/transform-swiftui.js --component=Button --mode=replace --update-storybook

# Batch mode
node ~/.claude/wrappers/transform-swiftui.js --batch=Button,Card,Modal --mode=replace
```

**Replace mode features:**
- Automatic backups to `.design/backups/TIMESTAMP/`
- Replaces existing components
- Updates SwiftUI previews with `--update-storybook`
- Batch processing with `--batch=Component1,Component2`

## Related Skills

- `/design:sync-cascade` - Orchestrate automatic updates
- `/design:sync-monitor` - Monitor Figma sync
- `/transform-flutter` - Transform to Flutter
- `/transform-jetpack-compose` - Transform to Jetpack Compose (Android)
- `/extract-design` - Extract from Figma
