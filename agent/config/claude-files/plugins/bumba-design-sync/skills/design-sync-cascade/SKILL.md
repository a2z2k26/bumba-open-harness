---
name: sync-cascade
description: Orchestrates automatic re-transformation and replacement of changed components in codebase and Storybook
trigger: Automatically triggered by sync-monitor hook after Figma sync detects changes
auto_invoke: false
---

# Design Sync Cascade

This skill orchestrates the automatic update pipeline after design changes are synced from Figma. It routes changed components to the appropriate transform skills to update both the codebase and Storybook.

## When to Use

This skill is triggered when:
- **Automatically**: After sync-monitor detects changes (hook creates trigger file)
- **Manually**: User runs `/design:sync-cascade` to process pending changes
- **On-demand**: User specifies components to update with arguments

## How to Invoke

**Automatic (from hook):**
When sync-monitor completes, check for trigger file:
```bash
cat .design/logs/triggers/cascade-trigger.json
```

**Manual with trigger data:**
```bash
# User runs: /design:sync-cascade
# You should check for and read the trigger file
```

**Manual with specific components:**
```bash
# User runs: /design:sync-cascade Button Card Modal
# Process only the specified components
```

## What This Skill Does

1. **Receives Change List**: Gets changed components/tokens from sync-monitor
2. **Detects Project Framework**: Identifies the target language (React, Vue, Angular, etc.)
3. **Routes to Transform Skills**: Calls appropriate transform skill with replace mode
4. **Validates Updates**: Ensures transformed components replaced legacy versions
5. **Reports Results**: Summarizes what was updated in codebase and Storybook

## Task Workflow

### 1. Receive Changed Components
Input from sync-monitor hook or manual invocation. Check for trigger file first:

```bash
# Check if trigger file exists from sync-monitor hook
if [ -f .design/logs/triggers/cascade-trigger.json ]; then
  cat .design/logs/triggers/cascade-trigger.json
fi
```

Expected JSON format:
```json
{
  "skill": "design:sync-cascade",
  "changedComponents": ["button-primary", "card-default"],
  "newComponents": ["modal-dialog"],
  "changedTokens": ["colors", "spacing"],
  "timestamp": "2026-01-09T04:27:00.150Z"
}
```

### 2. Detect Project Framework
Check project configuration and structure:
```bash
# Check package.json for framework
cat package.json | grep -E "(react|vue|angular|svelte|flutter)"

# Check .design/config.json for target framework
cat .design/config.json | grep "targetFramework"

# Fallback: detect from src directory structure
ls -la src/components/*.tsx 2>/dev/null && echo "React/TypeScript"
ls -la src/components/*.vue 2>/dev/null && echo "Vue"
```

### 3. Determine Transform Skill to Use
Based on detected framework, map to transform skill:
- **React**: `design-transform-react`
- **Vue**: `design-transform-vue`
- **Angular**: `design-transform-angular`
- **Svelte**: `design-transform-svelte`
- **React Native**: `design-transform-react-native`
- **Flutter**: `design-transform-flutter`
- **Swift UI**: `design-transform-swiftui`
- **Jetpack Compose**: `design-transform-jetpack-compose`
- **Web Components**: `design-transform-web-components`

### 4. Route to Transform Skill (Replace Mode)
For changed/new components, invoke the appropriate transform skill using the Skill tool:

**For React projects:**
```bash
# Single component
node ~/.claude/wrappers/transform-react.js --component=button-primary --mode=replace --update-storybook

# Batch mode (preferred for multiple components)
node ~/.claude/wrappers/transform-react.js --batch=button-primary,card-default,modal-dialog --mode=replace --update-storybook
```

**For other frameworks**, use the same pattern:
- Vue: `transform-vue.js`
- Angular: `transform-angular.js`
- Svelte: `transform-svelte.js`
- React Native: `transform-react-native.js`
- Flutter: `transform-flutter.js`
- SwiftUI: `transform-swiftui.js`
- Jetpack Compose: `transform-jetpack-compose.js`

**The transform process:**
1. Creates backup to `.design/backups/TIMESTAMP/`
2. Transforms component from `.design/components/{component}.json`
3. Replaces existing file in `src/design-system/components/`
4. Updates corresponding Storybook story (or preview/test file)
5. Updates registry with transformation timestamp

### 5. Batch Process Changed Components
Group changes for efficient transformation:
- **Components**: Transform all changed components in one batch
- **Tokens**: Re-transform tokens if foundational changes detected
- **Layouts**: Update layouts if they reference changed components

### 6. Validate Replacements
After transformation:
```bash
# Check that files were updated
find src/design-system/components -name "*.tsx" -mmin -2

# Verify Storybook stories updated
find src/design-system/components -name "*.stories.tsx" -mmin -2

# Optional: Run build to catch errors
npm run build 2>&1 | head -20
```

### 7. Create Backup (Safety)
Before replacing files:
```bash
# Backup existing components to .design/backups/
timestamp=$(date +%Y%m%d-%H%M%S)
mkdir -p .design/backups/$timestamp
cp -r src/design-system/components/* .design/backups/$timestamp/
```

## Transform Skill Integration

All transform skills now support these parameters for sync-cascade:
- `--component <name>`: Specific component to transform
- `--mode=replace`: Replace existing file instead of creating new (creates backup first)
- `--update-storybook`: Update corresponding Storybook story/preview/test
- `--batch=Component1,Component2,...`: Process multiple components from comma-separated list
- `--no-backup`: Disable automatic backup (not recommended, default: backup enabled)

**Supported frameworks:**
✅ transform-react
✅ transform-vue
✅ transform-angular
✅ transform-svelte
✅ transform-react-native
✅ transform-flutter
✅ transform-swiftui
✅ transform-jetpack-compose

## Example Output

After successful cascade:

```
Design Cascade Complete (2026-01-09 04:28:15)

Framework Detected: React + TypeScript
Transform Skill: design-transform-react

Components Updated:
  ✅ button-primary
     Transformed: .design/components/button-primary.json
     Replaced: src/design-system/components/Button/ButtonPrimary.tsx
     Story Updated: src/design-system/components/Button/ButtonPrimary.stories.tsx

  ✅ card-default
     Transformed: .design/components/card-default.json
     Replaced: src/design-system/components/Card/Card.tsx
     Story Updated: src/design-system/components/Card/Card.stories.tsx

Tokens Updated:
  ✅ Colors re-exported to theme
  ✅ Spacing tokens updated

Backup Created: .design/backups/20260109-042815/

Build Status:
  ✅ TypeScript compilation passed
  ✅ Storybook build successful
```

## Safety Features

- **Automatic Backups**: Creates timestamped backup before replacement
- **Validation**: Checks that target files exist before replacing
- **Rollback**: Keeps last 5 backups in `.design/backups/`
- **Dry Run**: Can be invoked with `--dry-run` to preview changes
- **Build Verification**: Optional post-transform build check

## Hook Integration

This skill is triggered by a PostToolUse hook after sync-monitor completes:

**Hook Location**: `.claude/hooks/post-sync-monitor.sh`

The hook should:
1. Parse sync-monitor output for changed components
2. Invoke sync-cascade skill with component list
3. Pass through any flags (--dry-run, --no-backup, etc.)

## Configuration

Settings in `.design/config.json`:
```json
{
  "cascade": {
    "enabled": true,
    "autoBackup": true,
    "targetFramework": "react",
    "buildAfterTransform": true,
    "maxBackups": 5
  }
}
```

## Error Handling

If transformation fails:
1. Preserve existing component (don't delete)
2. Log error to `.design/logs/cascade-errors.log`
3. Restore from backup if partial replacement occurred
4. Report failed components to user

## Implementation Notes

- **Non-destructive**: Always backup before replacing
- **Framework-agnostic**: Detects and routes to correct transform skill
- **Efficient**: Batches multiple components when possible
- **Validated**: Runs optional build checks after updates
- **Logged**: All operations logged to `.design/logs/`

## Future Enhancements

- [ ] Dependency analysis (if button changes, update forms using button)
- [ ] Semantic versioning for component changes
- [ ] Git commit integration (auto-commit transformed components)
- [ ] Notification system for transform failures
- [ ] Visual diff preview before replacement
