---
name: sync-monitor
description: Monitor design changes from Figma and automatically update registries
trigger: When users sync designs from Figma or ask about design changes
auto_invoke: true
---

# Design Sync Monitor

This skill monitors design changes from Figma syncs and ensures all registries are properly updated.

## When to Use

Use this skill automatically when:
- User syncs designs from Figma (via plugin or manual sync)
- User asks "what changed?" or "what was updated?" after a design sync
- Design Bridge server receives component/token updates
- User wants to see a summary of design changes

## What This Skill Does

1. **Detects Design Changes**: Monitors `.design/components/` for timestamp changes
2. **Updates Registries**: Ensures `componentRegistry.json` and registry files are in sync
3. **Generates Change Reports**: Creates human-readable summaries of what changed
4. **Validates Sync**: Checks that all components are properly registered

## Task Workflow

When invoked, follow these steps:

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
After completing registry updates, trigger the cascade hook:
- Write changed component list to `.design/logs/last-sync-changes.json`
- Hook will automatically invoke `sync-cascade` skill if configured
- Pass change summary to cascade for transformation routing

## Example Output

When changes are detected:

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

## Implementation Notes

- **Non-blocking**: Don't stop user workflow
- **Automatic**: Run in background after syncs
- **Fast**: Quick timestamp comparisons
- **Reliable**: Always validate before reporting success
- **Generic**: Works with any project using `.design/` folder structure

## Folder Structure References

This skill monitors the standard Design Bridge folder structure:
- `.design/components/` - Component definitions
- `.design/tokens/` - Design tokens
- `.design/layouts/` - Layout definitions
- `.design/componentRegistry.json` - Component registry
- `.design/layoutManifest.json` - Layout manifest
- `.design/logs/` - Sync and transformation logs
- `.design/metadata.json` - Project metadata

## Integration with Auto-Sync

The Design Bridge server:
1. Accepts both `tokens` and `components` in `/api/tokens` endpoint
2. Detects changes by comparing `extractedAt` timestamps
3. Logs change types: new, updated, unchanged
4. Updates registry metadata automatically
5. Stores sync events in `.design/logs/`

## Hook Integration

This skill triggers a PostToolUse hook that can automatically invoke sync-cascade:

**Hook File**: `.claude/hooks/post-sync-monitor.sh` or equivalent

**Change Data File**: `.design/logs/last-sync-changes.json`

Example change data structure:
```json
{
  "timestamp": "2026-01-09T04:27:00.150Z",
  "changedComponents": ["button-primary", "card-default"],
  "newComponents": ["badge-new"],
  "changedTokens": ["colors", "spacing"],
  "syncMetadata": {
    "syncCount": 15,
    "lastFigmaSync": "2026-01-09T04:27:00.150Z"
  }
}
```

The hook can read this file and invoke sync-cascade with the appropriate parameters.

## Future Enhancements

- [ ] Visual diff of component changes
- [ ] Slack/Discord notifications for design changes
- [ ] Change history tracking
- [ ] Rollback capability
