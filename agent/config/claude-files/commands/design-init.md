---
name: design-init
description: Initialize the standardized Design Bridge folder structure with tokens, components, layouts, and Storybook configuration
allowed-tools: Read, Write, Bash, AskUserQuestion
---

# /design-init - Initialize Design Bridge Structure

Initialize the standardized `.design/` directory structure in the current project.

## Architecture

This command uses a **two-phase architecture** for reliability:

1. **Phase 1 (This Command)**: Interactive configuration - gather user preferences
2. **Phase 2 (Hook)**: Deterministic execution - `on-design-init-complete.js` handles all file operations

When you write `config.json`, the hook automatically:
- Creates all directories
- Installs BUMBA Design Catalog
- Installs Storybook theme (if enabled)
- Generates registry files
- Creates README.md and .gitignore
- Updates package.json scripts
- Verifies structure

## Usage

```
/design-init
```

---

## Step 1: Detect Project Context

Analyze the current project before prompting:

### Framework Detection

```bash
# Check package.json for frameworks
[ -f package.json ] && cat package.json | head -50
```

Detection rules:
- `next.config.*` exists → **Next.js** (use "nextjs", not "react")
- `"react"` in dependencies → **React**
- `"vue"` in dependencies → **Vue**
- `"@angular/core"` in dependencies → **Angular**
- `"svelte"` in dependencies → **Svelte**
- No match → **React** (default)

### TypeScript Detection

```bash
# Check for TypeScript
[ -f tsconfig.json ] && echo "TypeScript detected"
```

### Existing Structure

```bash
# Check if .design/ exists
[ -d .design ] && echo "EXISTS"
```

---

## Step 2: Handle Existing .design/

**If `.design/` exists**, use AskUserQuestion:

**Question**: "A .design/ directory already exists. What would you like to do?"

Options:
- **Reinitialize** - Backup existing and create fresh structure
- **Update Config** - Keep existing data, only update configuration
- **Cancel** - Abort initialization

If **Reinitialize**:
```bash
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mv .design ".design-backup-$TIMESTAMP"
```

If **Cancel**: Exit with message "Initialization cancelled."

---

## Step 3: Interactive Configuration

Use AskUserQuestion for each prompt. Record answers for config.json.

### Prompt 1: Framework

**Question**: "Which framework are you using?"

Options:
- **React** - React library for building user interfaces
- **Next.js** - React framework with App Router (Recommended if detected)
- **Vue** - Progressive JavaScript framework
- **Angular** - Platform for building web applications
- **Svelte** - Cybernetically enhanced web apps
- **React Native** - Build native mobile apps
- **Flutter** - Google's UI toolkit
- **SwiftUI** - Apple's declarative UI
- **Jetpack Compose** - Android's modern UI toolkit

Store as: `framework` (lowercase: react, nextjs, vue, angular, svelte, react-native, flutter, swiftui, jetpack-compose)

### Prompt 1b: Next.js Options (only if nextjs selected)

**Question**: "Which Next.js router are you using?"

Options:
- **App Router** - Modern Next.js 14+ with Server Components (Recommended)
- **Pages Router** - Classic Next.js routing

Store as: `nextjsRouter` (app | pages)

### Prompt 2: TypeScript

**Question**: "Are you using TypeScript?"

Options:
- **Yes** - TypeScript for type safety (Recommended if tsconfig.json exists)
- **No** - Plain JavaScript

Store as: `typescript` (true | false)

### Prompt 3: Output Path

**Question**: "Where should transformed design system code be output?"

Options:
- **src/design-system** - Standard location (Recommended)
- **src/components/design-system** - Within components directory
- **lib/design-system** - In lib directory

Store as: `outputPath`

### Prompt 4: Features (multi-select)

**Question**: "Which features do you want to enable?"

Options:
- **Auto-sync** - Automatically sync with Figma when changes detected
- **Storybook** - Generate Storybook stories with BUMBA theme

Store as: `autoSync` (true | false), `storybook` (true | false)

### Prompt 5: Layout Extraction

**Question**: "Do you want to enable layout extraction from Figma?"

Options:
- **Yes** - Enable layout extraction (full page/screen designs)
- **No** - Components and tokens only

Store as: `layoutsEnabled` (true | false)

### Prompt 5b-5d (only if layouts enabled)

**5b - Layout Framework**:
- **Same as components** - Use the same framework
- **Different framework** - Select different framework for layouts

**5c - Screenshot Scale**:
- **2x scale** - High quality for retina (Recommended)
- **1x scale** - Standard resolution
- **3x scale** - Maximum quality

**5d - Assets Location**:
- **public/design-assets** - Standard public location (Recommended)
- **assets/design** - Assets directory
- **static/design-assets** - Static files directory

Store as: `layoutFramework`, `screenshotScale`, `assetsDir`

---

## Step 4: Generate config.json

Build configuration from collected answers and write to `.design/config.json`.

**CRITICAL**: Writing this file triggers the `on-design-init-complete` hook which handles all file system operations.

### Create .design directory first

```bash
mkdir -p .design
```

### Configuration Template

```json
{
  "version": "1.0.0",
  "project": {
    "name": "{{projectName from package.json or directory name}}",
    "framework": "{{framework}}",
    "typescript": {{typescript}},
    "outputPath": "{{outputPath}}"
  },
  "figma": {
    "fileKey": null,
    "fileName": null,
    "boundAt": null,
    "autoSync": {{autoSync}},
    "syncInterval": 300000
  },
  "transformers": {
    "enabled": ["{{framework}}"],
    "options": {
      "{{framework}}": {
        "useStyledComponents": {{framework === 'react' || framework === 'nextjs'}},
        "useTailwind": false,
        "generateStories": {{storybook}}
      }
    }
  },
  "output": {
    "extractedCodePath": ".design/extracted-code",
    "finalOutputPath": "{{outputPath}}",
    "overwriteExisting": false
  },
  "versioning": {
    "enabled": true,
    "trackChanges": true,
    "preventOverwrites": true
  },
  "storybook": {
    "enabled": {{storybook}},
    "autoGenerate": true,
    "themePath": ".storybook/bumba-storybook-theme.ts",
    "outputPath": ".storybook",
    "categories": {
      "tokens": "Tokens",
      "components": "Components",
      "layouts": "Layouts"
    },
    "layoutDecorators": {{layoutsEnabled}}
  },
  "layouts": {
    "enabled": {{layoutsEnabled}},
    "framework": "{{layoutFramework || framework}}",
    "outputDir": "{{outputPath}}/layouts",
    "assetsDir": "{{assetsDir}}/layouts",
    "screenshotScale": {{screenshotScale || 2}},
    "includeInStorybook": {{layoutsEnabled && storybook}},
    "generateReadme": true
  },
  "assetManagement": {
    "strategy": "local",
    "useGitLFS": false,
    "maxScreenshotSize": "5MB",
    "compression": true,
    "compressionQuality": 85
  },
  "cascade": {
    "enabled": true,
    "autoBackup": true,
    "targetFramework": "{{framework}}",
    "buildAfterTransform": false,
    "maxBackups": 5,
    "replaceMode": true,
    "updateStorybook": {{storybook}}
  }
}
```

### Write config.json

Use the Write tool to create `.design/config.json` with the built configuration.

**Important**: Use JSON.stringify with 2-space indentation.

---

## Step 5: Wait for Hook Completion

The `on-design-init-complete` hook automatically triggers when config.json is written.

It handles:
- Directory structure creation
- BUMBA Design Catalog installation
- Storybook theme installation (if enabled)
- Registry file generation
- README.md generation
- .gitignore generation
- package.json script and dependency updates
- **Automatic npm/yarn/pnpm install** (if Storybook enabled)
- Structure verification

Wait approximately 30-60 seconds for the hook to complete (includes dependency installation time).

---

## Step 6: Verify and Report

### Verify Structure

```bash
ls -la .design/
```

### Display Success Message

**Without Layouts:**
```
Design Bridge Initialized Successfully!

Created structure:
   .design/
   ├── config.json
   ├── metadata.json
   ├── README.md
   ├── tokens/
   ├── components/
   ├── catalog/           # BUMBA Design Catalog
   ├── source/
   ├── extracted-code/{{framework}}/
   └── assets/

   {{outputPath}}/
   └── componentRegistry.json

Configuration:
   Framework: {{framework}}
   TypeScript: {{typescript}}
   Output: {{outputPath}}
   Storybook: {{storybook}}
   Auto-Cascade: enabled

Quick Start:
   npm run catalog        # View design catalog
   npm run storybook      # View in Storybook (ready to use!)

Next Steps:
   1. Install Design Bridge Server
   2. Load Figma plugin
   3. Bind to this project
   4. Extract design tokens
   5. Transform: /transform-{{framework}}

Note: All dependencies are already installed and ready to use!

Auto-Cascade Feature:
   When you sync changes from Figma, the system will automatically:
   - Detect changed components (sync-monitor skill)
   - Re-transform them to {{framework}} code
   - Replace old versions in {{outputPath}}
   - Update Storybook stories
   - Create backups in .design/backups/

   To disable: Set cascade.enabled: false in .design/config.json

For details: .design/README.md
```

**With Layouts:**
```
Design Bridge Initialized Successfully!

Created structure:
   .design/
   ├── config.json
   ├── metadata.json
   ├── README.md
   ├── tokens/
   ├── components/
   ├── layouts/
   ├── catalog/           # BUMBA Design Catalog
   ├── source/
   ├── extracted-code/{{framework}}/
   └── assets/

   {{outputPath}}/
   ├── componentRegistry.json
   └── layoutManifest.json

   {{assetsDir}}/layouts/  # Screenshots

Configuration:
   Framework: {{framework}}
   Layout Framework: {{layoutFramework}}
   TypeScript: {{typescript}}
   Output: {{outputPath}}
   Screenshot Scale: {{screenshotScale}}x
   Storybook: {{storybook}}
   Auto-Cascade: enabled

Quick Start:
   npm run catalog        # View design catalog
   npm run storybook      # View in Storybook (ready to use!)

Next Steps:
   1. Install Design Bridge Server
   2. Load Figma plugin
   3. Extract tokens and components
   4. Extract layouts: /extract-layouts
   5. Transform: /transform-{{framework}}

Note: All dependencies are already installed and ready to use!

Auto-Cascade Feature:
   When you sync changes from Figma, the system will automatically:
   - Detect changed components (sync-monitor skill)
   - Re-transform them to {{framework}} code
   - Replace old versions in {{outputPath}}
   - Update Storybook stories
   - Create backups in .design/backups/

   To disable: Set cascade.enabled: false in .design/config.json

For details: .design/README.md
```

---

## Error Handling

### Permission Errors

If writing fails:
```
Error: Permission denied creating .design/

Solutions:
1. Check permissions: ls -la ./
2. Grant write access: chmod u+w ./
3. Try with sudo (if appropriate)
```

### Hook Not Triggered

If hook doesn't run (structure incomplete after config.json written):

```
Warning: Hook may not have triggered. Running manual fallback...
```

Then manually run the essential commands:
```bash
# Minimal directory creation
mkdir -p .design/tokens .design/components .design/source/tokens .design/source/components

# Minimal files
echo '{"version":"1.0.0","categories":{}}' > .design/tokens/index.json
echo '{"version":"1.0.0","components":{}}' > .design/components/registry.json
```

---

## Related Commands

After initialization:
- `/transform-{{framework}}` - Transform tokens to code
- `/extract-components` - Extract components from Figma
- `/extract-layouts` - Extract layouts from Figma
- `npm run catalog` - Open design catalog
- `npm run storybook` - Open Storybook (if enabled)
