# Design System Shared Modules

**Canonical Location**: `~/.claude/shared-modules/design-system/`

This directory contains the canonical source files for the Bumba Design System layout transformation pipeline. These modules are shared across all projects via symlinks.

## Architecture

### Centralized Module Storage
- **Purpose**: Single source of truth for design system transformation tools
- **Location**: `~/.claude/shared-modules/design-system/`
- **Distribution**: Symlinks in project `server/` directories
- **Benefits**:
  - Updates propagate automatically to all projects
  - No version drift between projects
  - Consistent behavior across workspace

### Auto-Symlinking Hook
- **Hook**: `~/.claude/hooks/PreToolUse/ensure-design-system-modules.js`
- **Triggers**: When `design-layout-to-html` or `design-init` skills are invoked
- **Action**: Ensures required modules are symlinked into project's `server/` directory
- **Behavior**:
  - Creates symlinks if missing
  - Validates existing symlinks
  - Backs up regular files before replacing with symlinks

## Modules

### 1. layout-validator.js (29KB)
**Purpose**: 3-pass visual validation state management

**Responsibilities**:
- Initialize validation sessions
- Track discrepancies and fixes across passes
- Generate validation reports
- Extract validated CSS from reference HTML

**Usage**:
```javascript
const { LayoutValidator } = require('./layout-validator');
const validator = new LayoutValidator(projectPath);
const session = validator.startValidation('LayoutName', { framework: 'react' });
```

### 2. layout-to-html-transformer.js (11KB)
**Purpose**: Generate reference HTML from Figma layout JSON

**Responsibilities**:
- Convert Figma auto-layout to CSS flexbox
- Generate HTML with component placeholders
- Embed screenshot for comparison
- Create validation-ready reference structure

**Usage**:
```javascript
const { transformLayoutFile } = require('./layout-to-html-transformer');
const result = transformLayoutFile(layoutJsonPath, {
  screenshotPath,
  includeScreenshotComparison: true
});
```

### 3. layout-transformer.js (35KB)
**Purpose**: Generate production framework code from validated HTML

**Responsibilities**:
- Read validated CSS structure
- Generate framework-specific code (React, Vue, SwiftUI, etc.)
- Import existing transformed components
- Create layout composition with proper styling

**Usage**:
```javascript
const { transformLayout } = require('./layout-transformer');
const code = transformLayout(layoutData, {
  framework: 'react',
  typescript: true,
  outputPath: 'src/layouts/'
});
```

## Workflow

The layout-to-html pipeline uses these modules in sequence:

```
1. layout-to-html-transformer.js
   ↓ Generates reference.html

2. layout-validator.js (with Chrome DevTools MCP)
   ↓ 3-pass validation loop
   ↓ Generates validation-report.json

3. layout-transformer.js
   ↓ Generates framework code
   ↓ Outputs to .design/extracted-code/{framework}/layouts/
```

## Maintenance

### Updating Modules
To update a module:
```bash
# Edit the canonical version
vim ~/.claude/shared-modules/design-system/layout-validator.js

# Changes automatically propagate to all projects via symlinks
```

### Adding New Modules
To add a new shared module:
```bash
# 1. Add to this directory
cp new-module.js ~/.claude/shared-modules/design-system/

# 2. Update the hook to include it
vim ~/.claude/hooks/PreToolUse/ensure-design-system-modules.js
# Add to REQUIRED_MODULES array

# 3. Future projects will automatically get the module
```

### Verifying Symlinks
To check if a project is using symlinks correctly:
```bash
cd /path/to/project/server
ls -la layout*.js

# Should show symlinks (->):
# lrwxr-xr-x@ ... layout-validator.js -> /home/.../layout-validator.js
```

## Troubleshooting

### Symlink Not Found
If a project shows broken symlink:
```bash
# Remove broken symlink
rm server/layout-validator.js

# Re-run the skill to trigger hook
# Or manually recreate:
cd server
ln -s ~/.claude/shared-modules/design-system/layout-validator.js .
```

### Regular File Instead of Symlink
If you see a regular file instead of symlink:
```bash
# The hook will automatically back it up and replace with symlink
# Backup will be: layout-validator.js.backup-{timestamp}
```

### Module Not Loading
If Node.js can't find the module:
```bash
# Verify symlink target exists
ls -la ~/.claude/shared-modules/design-system/

# Check symlink is valid
readlink server/layout-validator.js

# Verify permissions
ls -la server/layout*.js
```

## Version History

- **2026-01-08**: Initial centralized architecture
  - Created shared-modules/design-system/
  - Implemented PreToolUse hook for auto-symlinking
  - Migrated from per-project copies to symlinks

## Related Files

- Hook: `~/.claude/hooks/PreToolUse/ensure-design-system-modules.js`
- Skill: `~/.claude/commands/design-layout-to-html.md`
- Templates: `~/.claude/templates/design-bridge-server/` (backup)
