# /transform-react - Transform Components to React

Transform Figma components from the registry into production-ready React code.

## Purpose

This skill reads components from `.design/componentRegistry.json` and transforms them into React/TypeScript code with:
- Full content extraction from Figma JSON
- Canonical naming conventions (PascalCase)
- TypeScript type definitions
- Automatic registry tracking
- Optional Storybook stories
- Multi-framework support (same component → multiple frameworks)

## Prerequisites

Before running this skill, ensure:
- `.design/componentRegistry.json` exists and is populated
- Component raw data files exist in `.design/components/`
- Project has been initialized with design system structure

## Instructions

### Step 1: Verify Registry and Components

Check that the registry is populated:

```bash
# Check registry exists
ls -la .design/componentRegistry.json

# Count components in registry
cat .design/componentRegistry.json | jq '.components | length'

# List available components
cat .design/componentRegistry.json | jq -r '.components | to_entries[] | .value.canonicalName' | head -20
```

If registry is empty or missing, user needs to run the Figma plugin to extract components first.

### Step 2: Choose Component to Transform

Ask user which component they want to transform, or offer to transform all components.

User can specify component by:
- **Canonical name** (e.g., "Button", "AiChatBox")
- **Figma name** (e.g., "AI Chat Box")
- **Plugin ID** (e.g., "figma-plugin-button-4185:3778")
- **Node ID** (e.g., "4185:3778")

### Step 3: Execute Transformation

Call the React transformation wrapper:

```bash
# Transform single component by canonical name
node ~/.claude/wrappers/transform-react.js --component=Button

# Transform single component by plugin ID
node ~/.claude/wrappers/transform-react.js --component=figma-plugin-button-4185:3778

# Transform all components in registry
node ~/.claude/wrappers/transform-react.js --all

# Replace mode - for sync-cascade automatic updates
node ~/.claude/wrappers/transform-react.js --component=Button --mode=replace --update-storybook

# Batch mode - process multiple components at once
node ~/.claude/wrappers/transform-react.js --batch=Button,Card,Modal --mode=replace
```

The wrapper will:
1. Resolve component from registry (supports all ID formats)
2. Create backup if in replace mode (to `.design/backups/TIMESTAMP/`)
3. Load raw Figma JSON data
4. Extract full content tree with nested components
5. Generate React/TypeScript code with canonical naming
6. Write output to `src/design-system/components/{CanonicalName}.tsx`
7. Update registry with transformation state
8. Generate/update Storybook story (if `--storybook` or `--update-storybook` enabled)

### Step 4: Verify Output

Check generated files:

```bash
# List generated components
ls -la src/design-system/components/*.tsx

# Check specific component
cat src/design-system/components/Button.tsx

# Verify registry updated
cat .design/componentRegistry.json | jq '.components | to_entries[] | select(.value.canonicalName == "Button") | .value.transformations.react'
```

### Step 5: Handle Registry Check (Skip Logic)

The transformer automatically checks the registry before transforming:

- **First transform:** Component transformed, files created
- **Second transform:** Skipped (already exists in registry)
- **Force re-transform:** Use `--force` flag to override

```bash
# Skip if already transformed (default behavior)
node ~/.claude/wrappers/transform-react.js --component=Button

# Force re-transform (override registry check)
node ~/.claude/wrappers/transform-react.js --component=Button --force
```

### Step 6: Cross-Framework Support

The same component can be transformed for multiple frameworks:

```bash
# Transform Button for React
node ~/.claude/wrappers/transform-react.js --component=Button
# → Creates: src/design-system/components/Button.tsx

# Transform same Button for Vue
node ~/.claude/wrappers/transform-vue.js --component=Button
# → Creates: src/design-system/components/button.vue

# Check registry - both tracked separately
cat .design/componentRegistry.json | jq '.components | to_entries[] | select(.value.canonicalName == "Button") | .value.transformations'
# {
#   "react": { "state": "code-generated", "codePath": "src/design-system/components/Button.tsx", ... },
#   "vue": { "state": "code-generated", "codePath": "src/design-system/components/button.vue", ... }
# }
```

### Step 7: Report Results

Inform user of transformation results:

**Success Message:**
```
✅ React Transformation Complete

Component: {CanonicalName}
Output: src/design-system/components/{CanonicalName}.tsx
Story: src/stories/{CanonicalName}.stories.tsx (if enabled)

Registry State: code-generated
Dependencies: {resolvedCount} resolved, {missingCount} missing

Next Steps:
1. Review generated component
2. Import in your application: import { {CanonicalName} } from './design-system/components/{CanonicalName}';
3. View in Storybook (if enabled): npm run storybook
```

## Expected Output

### Component File Structure

```
src/design-system/components/
├── Button.tsx              (PascalCase for React)
├── AiChatBox.tsx           (Canonical naming preserved)
└── ButtonDanger.tsx

src/stories/
├── Button.stories.tsx      (if Storybook enabled)
└── AiChatBox.stories.tsx
```

### Generated Code Example

```typescript
/**
 * Button Component
 * Generated from Figma Design System with full content extraction
 * Extracted: 2026-01-08T...
 */

import React from 'react';

export interface ButtonProps {
  variant?: 'primary' | 'secondary' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  disabled?: boolean;
  onClick?: () => void;
  children?: React.ReactNode;
}

const Button: React.FC<ButtonProps> = ({
  variant = 'primary',
  size = 'md',
  disabled = false,
  onClick,
  children
}) => {
  return (
    <button
      className={`button button-${variant} button-${size}`}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
};

Button.displayName = 'Button';

export default Button;
```

### Registry Update

After transformation, registry tracks state per framework:

```json
{
  "components": {
    "figma-plugin-button-4185:3778": {
      "id": "figma-plugin-button-4185:3778",
      "figmaId": "4185:3778",
      "figmaName": "Button",
      "canonicalName": "Button",
      "source": {
        "type": "figma-plugin",
        "nodeId": "4185:3778",
        "rawDataPath": ".design/components/button.json"
      },
      "transformations": {
        "react": {
          "state": "code-generated",
          "transformedAt": "2026-01-08T15:30:00Z",
          "codePath": "src/design-system/components/Button.tsx",
          "storyPath": "src/stories/Button.stories.tsx",
          "fullContent": true,
          "dependencies": {
            "resolved": [],
            "missing": []
          }
        },
        "vue": null,
        "angular": null
      }
    }
  }
}
```

## Naming Conventions

The system uses **canonical naming** as the single source of truth:

### Input Formats Supported
- Canonical: `Button`, `AiChatBox`, `ButtonDanger`
- Figma: `"Button"`, `"AI Chat Box"`, `"Button Danger"`
- Plugin ID: `figma-plugin-button-4185:3778`
- Node ID: `4185:3778`

### Output File Names (Framework-Specific)
- **React/Next.js**: `Button.tsx` (PascalCase)
- **Vue**: `button.vue` (kebab-case)
- **Angular**: `button.component.ts` (kebab-case)
- **Flutter**: `button.dart` (snake_case)
- **SwiftUI**: `Button.swift` (PascalCase)
- **Jetpack Compose**: `Button.kt` (PascalCase)

## Wrapper Script CLI

The wrapper script supports these options:

```bash
# Single component transform
node ~/.claude/wrappers/transform-react.js --component={name|id}

# Transform all components
node ~/.claude/wrappers/transform-react.js --all

# Force re-transform (override registry check)
node ~/.claude/wrappers/transform-react.js --component=Button --force

# Replace mode - backup and replace existing components (for sync-cascade)
node ~/.claude/wrappers/transform-react.js --component=Button --mode=replace

# Update Storybook stories when replacing
node ~/.claude/wrappers/transform-react.js --component=Button --mode=replace --update-storybook

# Batch transform multiple components from comma-separated list
node ~/.claude/wrappers/transform-react.js --batch=Button,Card,Modal --mode=replace

# Disable automatic backup before replacement (not recommended)
node ~/.claude/wrappers/transform-react.js --component=Button --mode=replace --no-backup

# With TypeScript (default: true)
node ~/.claude/wrappers/transform-react.js --component=Button --typescript

# With Storybook stories
node ~/.claude/wrappers/transform-react.js --component=Button --storybook

# With styled-components
node ~/.claude/wrappers/transform-react.js --component=Button --styled-components
```

## Troubleshooting

**Error: Component not found in registry**
→ Check spelling, or list available components:
  `cat .design/componentRegistry.json | jq -r '.components | to_entries[] | .value.canonicalName'`

**Error: Raw data file not found**
→ Component registered but JSON missing. Re-run Figma plugin extraction.

**Error: Canonical name invalid for react**
→ Component name violates React naming conventions. Check for reserved words or invalid characters.

**Error: Cannot create valid canonical name**
→ Figma component name has invalid characters. Rename in Figma and re-extract.

**Warning: Missing transformations for nested components**
→ Component uses other components that haven't been transformed yet.
   Transform dependencies first, or use `--allow-incomplete` flag.

## Sync-Cascade Integration

This skill integrates with the `/design:sync-cascade` workflow for automatic component updates when Figma designs change.

### Replace Mode

When invoked with `--mode=replace`, the transformer:
1. **Creates automatic backup** to `.design/backups/TIMESTAMP/` before any changes
2. **Replaces existing component** files instead of skipping if already exists
3. **Updates Storybook stories** if `--update-storybook` flag is provided
4. **Preserves user modifications** in separate files (custom logic, additional props)

```bash
# Replace mode example (called by sync-cascade)
node ~/.claude/wrappers/transform-react.js --component=Button --mode=replace --update-storybook
```

### Batch Processing

Process multiple components in a single invocation for efficiency:

```bash
# Batch transform changed components
node ~/.claude/wrappers/transform-react.js --batch=Button,Card,Modal --mode=replace --update-storybook
```

**Batch mode features:**
- Processes components in parallel where possible
- Creates single backup directory for all changes
- Reports success/failure for each component
- Continues processing even if one component fails

### Backup Management

Backups are automatically created before replacement:
- **Location**: `.design/backups/TIMESTAMP/`
- **Content**: Complete copy of replaced component files
- **Retention**: Configurable in `.design/config.json` (default: last 5 backups)
- **Disable**: Use `--no-backup` flag (not recommended)

```bash
# Backup directory structure
.design/backups/
├── 20260109-042815/
│   ├── Button.tsx
│   ├── Button.stories.tsx
│   └── Card.tsx
└── 20260109-031204/
    └── Button.tsx
```

### Integration with sync-monitor Hook

The `post-sync-monitor.sh` hook automatically invokes this skill when Figma changes are detected:

1. sync-monitor detects changed components
2. Hook triggers sync-cascade skill
3. sync-cascade calls transform-react with `--mode=replace --batch={components}`
4. Components updated, Storybook refreshed
5. User notified of changes

## Related Skills

- `/extract-design` - Extract components from Figma
- `/design:sync-cascade` - Orchestrate automatic component updates
- `/design:sync-monitor` - Monitor Figma sync status
- `/transform-vue` - Transform to Vue
- `/transform-angular` - Transform to Angular
- `/transform-flutter` - Transform to Flutter
- Other framework transform skills

## Architecture

```
User runs: /transform-react Button
     ↓
skill.md (this file - instructions for Claude)
     ↓
~/.claude/wrappers/transform-react.js
     ↓
ReactComponentTransformer (uses EnhancedComponentTransformer base)
     ↓
  1. Resolve component from registry (hybrid schema)
  2. Load raw Figma JSON from .design/components/
  3. Extract full content tree (ComponentContentExtractor)
  4. Generate canonical name (NamingNormalizer)
  5. Validate for framework
  6. Check registry (skip if already transformed)
  7. Generate React code
  8. Write to src/design-system/components/
  9. Update registry transformations.react
     ↓
Output: Button.tsx + registry updated
```

## Benefits

- **Canonical Naming**: Single source of truth, framework-agnostic
- **Registry Tracking**: No duplicate transformations
- **Multi-Framework**: Same component → multiple frameworks
- **Full Content**: Complete extraction, nested components resolved
- **Type Safety**: TypeScript by default
- **Production Ready**: Follows React best practices
