---
name: design-sync-monitor
description: Monitor design changes from Figma and automatically update registries
allowed-tools: Read, Bash, Edit, Glob, Grep
---

# Design Sync Monitor

Monitor design changes from Figma syncs and ensure all registries are properly updated.

## When to Use

- After syncing designs from Figma (via plugin or manual sync)
- When asking "what changed?" or "what was updated?" after a design sync
- To validate that registries are in sync with component files
- To generate a summary of design changes

## What This Command Does

1. **Detects Design Changes**: Monitors `.design/components/` for timestamp changes
2. **Updates Registries**: Ensures `componentRegistry.json` and registry files are in sync
3. **Generates Change Reports**: Creates human-readable summaries of what changed
4. **Validates Sync**: Checks that all components are properly registered
5. **Triggers Cascade**: Optionally triggers sync-cascade for automatic re-transformation

## Task Workflow

### 1. Check Recent Sync Activity
```bash
# Check design system logs for recent sync events
tail -50 .design/logs/*.log 2>/dev/null | grep -E "(Component changed|New component|Processed.*components|sync)"
```

### 2. Scan Component Files for Changes
```bash
# List recently modified components (last 5 minutes)
find .design/components -name "*.json" -mmin -5 -type f
```

### 3. Compare Timestamps
For each component file found:
- Read the component JSON from `.design/components/`
- Extract `source.extractedAt` timestamp
- Compare with registry entry's `source.extractedAt` in `.design/componentRegistry.json`
- Flag mismatches as "needs registry update"

### 4. Update Registry if Needed
If mismatches found:
- Read `.design/componentRegistry.json`
- Update `source.extractedAt` for changed components
- Increment `syncMetadata.syncCount`
- Update `syncMetadata.lastFigmaSync`
- Write back to registry

### 5. Generate Change Report
Create a summary showing:
- ✨ New components (not in registry)
- 🔄 Updated components (extractedAt changed)
- ✅ Unchanged components
- Token changes (colors, typography, spacing, effects)

### 6. Validate Registry Consistency
- Ensure all component files have registry entries
- Check that all `source.extractedAt` timestamps match
- Verify `tokenDependencies` are valid
- Check `.design/layouts/` for layout changes
- Verify `.design/tokens/` for token updates

### 7. Trigger Cascade Hook (If Enabled)
After completing registry updates, create trigger file for cascade:
- Write changed component list to `.design/logs/triggers/cascade-trigger.json`
- Include: changedComponents, newComponents, changedTokens, timestamp
- Cascade hook can automatically invoke sync-cascade skill if configured

## Example Output

```
Design Sync Summary (2026-01-09 04:27:00)

Components:
  🔄 button-primary (updated)
     Old: 2026-01-09T04:00:27.901Z
     New: 2026-01-09T04:27:00.150Z
     Changes: variant colors updated

Tokens:
  ✅ 6 colors (no changes)
  ✅ 3 typography tokens (no changes)
  ✅ 2 spacing tokens (no changes)
  ✅ 2 effects (no changes)

Registry Status:
  ✅ All components registered
  ✅ All timestamps in sync
  ⚠️  1 component needs re-transformation
```

## Folder Structure References

This command monitors the standard Design Bridge folder structure:
- `.design/components/` - Component definitions
- `.design/tokens/` - Design tokens
- `.design/layouts/` - Layout definitions
- `.design/componentRegistry.json` - Component registry
- `.design/layoutManifest.json` - Layout manifest
- `.design/logs/` - Sync and transformation logs
- `.design/metadata.json` - Project metadata

## Usage Examples
- "run design sync monitor"
- "check what changed in the last sync"
- "update registries after sync"
- "validate design sync status"
