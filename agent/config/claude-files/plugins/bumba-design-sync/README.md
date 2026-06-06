# Bumba Design Sync Plugin

Automated design synchronization and cascade transformation for Bumba Design Bridge.

## Skills

### design-sync-monitor
Monitor design changes from Figma and update registries automatically.

**Usage**: `/design-sync-monitor`

**What it does**:
- Detects changes in `.design/tokens/` and `.design/components/`
- Compares timestamps between files and registry
- Generates change reports
- Creates `last-sync-changes.json` for cascade processing

### design-sync-cascade
Orchestrates automatic re-transformation of changed components.

**Usage**: `/design-sync-cascade`

**What it does**:
- Reads change data from sync-monitor
- Detects project framework (React, Vue, Angular, etc.)
- Routes to appropriate transform skill
- Creates backups before replacement
- Updates components and Storybook

## Workflow

```
Figma Change → Plugin Sync → Design Bridge Server
    ↓
/design-sync-monitor (detect changes)
    ↓
last-sync-changes.json created
    ↓
on-sync-changes.js hook triggers
    ↓
cascade-trigger.json created
    ↓
/design-sync-cascade (transform code)
    ↓
Updated components in src/
```

## Requirements

- `.design/` directory structure (initialized via `/design-init`)
- Design Bridge server running
- Component registry and tokens extracted from Figma

## Installation

Already installed as part of your global Claude configuration.

Enabled in `~/.claude/settings.json`:
```json
{
  "enabledPlugins": {
    "bumba-design-sync": true
  }
}
```

## Hook Integration

This plugin works with the hook system:
- `on-sync-changes.js` - Triggers cascade when changes detected
- `on-tokens-updated.js` - Regenerates STYLES.md

## Version

1.0.0

## License

MIT
