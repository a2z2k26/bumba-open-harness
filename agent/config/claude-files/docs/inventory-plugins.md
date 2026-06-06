# Claude Code Plugins Inventory

This document catalogs all custom plugins built for Claude Code. Plugins are self-contained extensions that bundle commands, agents, skills, and hooks into cohesive functionality packages.

## Overview

- **Total Plugins**: 8 active plugins (+ 1 backup)
- **Location**: `/opt/bumba-harness/.claude/plugins/`
- **Categories**: Design Bridge Integration (6), E2B Orchestration (1), Frontend Design (1)

---

## Design Bridge Plugins

Design Bridge plugins provide comprehensive design-to-code automation workflows.

### bumba-design-sync
**Directory**: `bumba-design-sync/`
**Version**: 1.0.0
**Status**: Active

Automated design synchronization and cascade transformation for Bumba Design Bridge.

**Skills**:
- `design-sync-monitor`: Monitor design changes from Figma and update registries
- `design-sync-cascade`: Orchestrate automatic re-transformation of changed components

**Workflow**:
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

**Hook Integration**:
- `on-sync-changes.js`: Triggers cascade when changes detected
- `on-tokens-updated.js`: Regenerates STYLES.md

**Requirements**:
- `.design/` directory structure (via `/design-init`)
- Design Bridge server running
- Component registry and tokens from Figma

---

### bumba-frontend-design
**Directory**: `bumba-frontend-design/`
**Status**: Active

Frontend design creation and code generation plugin. Focuses on building production-grade frontend interfaces with high design quality.

**Purpose**: Generate distinctive frontend code that avoids generic AI aesthetics.

**Integration**: Works with Design Bridge system for component and layout management.

---

### bumba-nlp-design
**Directory**: `bumba-nlp-design/`
**Status**: Active

Natural language to design component generation. Converts text descriptions into design components.

**Features**:
- NLP-based component generation
- Natural language design specifications
- Integration with component registry

**Use Case**: Quickly create components from descriptions without Figma

---

### design-explorer-ui
**Directory**: `design-explorer-ui/`
**Version**: Latest
**Status**: Active

UI design exploration using parallel E2B sandboxes. Creates 4 divergent UI directions.

**Directions**:
1. **Conservative**: Standard patterns, WCAG AA
2. **Refined**: Polished, elevated
3. **Expressive**: Bold, dynamic
4. **Experimental**: Boundary-pushing

**E2B Template**: design-ui-template

**Agents**:
- Phase 1: design-visual-designer
- Phase 2: design-ui-designer

**Output**: 4 git worktrees with complete implementations

---

### design-explorer-ux
**Directory**: `design-explorer-ux/`
**Version**: Latest
**Status**: Active

UX design exploration using parallel E2B sandboxes. Similar to design-explorer-ui but focuses on UX patterns and user flows.

**E2B Template**: design-ux-template

**Focus Areas**:
- User flows
- Interaction patterns
- Navigation design
- User journey mapping

---

### frontend-design
**Directory**: `frontend-design/`
**Status**: Active

General frontend design utilities and helpers.

---

## E2B Orchestration Plugins

### e2b-design-orchestrator
**Directory**: `e2b-design-orchestrator/`
**Status**: Active

Orchestrates E2B sandbox creation and management for design exploration workflows.

**Features**:
- Multi-sandbox orchestration
- Cost management
- Resource optimization
- Template management

**Integration**: Works with design-explorer-ui and design-explorer-ux plugins

---

## Backup Plugins

### design-explorer-BACKUP-20260111-131227
**Directory**: `design-explorer-BACKUP-20260111-131227/`
**Status**: Backup
**Backup Date**: 2026-01-11 13:12:27

Backup of design-explorer plugin before major refactoring.

**Note**: Can be safely removed after verifying new implementation works correctly.

---

## Plugin Structure

Claude Code plugins follow this structure:

```
plugin-name/
├── .claude-plugin/
│   ├── plugin.json          # Plugin manifest
│   ├── commands/            # Slash commands
│   │   └── command-name.md
│   ├── agents/              # Specialized agents
│   │   └── agent-name.md
│   ├── skills/              # Reusable skills
│   │   └── skill-name.md
│   ├── hooks/               # Event hooks
│   │   └── hook-name.js
│   └── instructions/        # Additional instructions
│       └── readme.md
├── README.md                # Plugin documentation
├── lib/                     # Shared libraries
├── scripts/                 # Utility scripts
└── tests/                   # Plugin tests
```

## Plugin Manifest (plugin.json)

```json
{
  "name": "plugin-name",
  "version": "1.0.0",
  "description": "Plugin description",
  "author": "Author name",
  "license": "MIT",
  "dependencies": [],
  "settings": {
    "enabled": true,
    "autoload": true
  },
  "commands": {
    "command-name": ".claude-plugin/commands/command-name.md"
  },
  "skills": {
    "skill-name": ".claude-plugin/skills/skill-name/"
  },
  "agents": {
    "agent-name": ".claude-plugin/agents/agent-name.md"
  },
  "hooks": {
    "hook-name": ".claude-plugin/hooks/hook-name.js"
  }
}
```

## Plugin Installation

### Global Plugins
Located in `~/.claude/plugins/` and available across all projects.

**Enable in settings.json**:
```json
{
  "enabledPlugins": {
    "bumba-design-sync": true,
    "design-explorer-ui": true
  }
}
```

### Project-Specific Plugins
Located in `{project}/.claude/plugins/` and only available in that project.

## Plugin Development

Create new plugins using the plugin development skills:

1. **command-name** skill: Learn plugin structure
2. **command-development** skill: Create commands
3. **agent-identifier** skill: Create agents
4. **hook-development** skill: Create hooks
5. **mcp-integration** skill: Integrate MCP servers

## Plugin Features

Plugins can provide:

- **Commands**: Slash commands (`/command-name`)
- **Skills**: Reusable knowledge modules
- **Agents**: Specialized AI assistants
- **Hooks**: Event-driven automation
- **MCP Servers**: External integrations
- **Instructions**: Additional context and guidelines
- **Templates**: Code and file templates
- **Scripts**: Utility scripts and tools

## Plugin Lifecycle

1. **Discovery**: Claude Code scans plugin directories
2. **Validation**: Checks plugin.json and structure
3. **Registration**: Registers commands, skills, agents, hooks
4. **Activation**: Loads enabled plugins
5. **Execution**: Commands/skills/hooks available for use
6. **Updates**: Hot-reload when files change

## Plugin Management Commands

```bash
# List installed plugins
ls ~/.claude/plugins/

# Enable plugin
# Edit ~/.claude/settings.json and add to enabledPlugins

# Disable plugin
# Edit ~/.claude/settings.json and set to false

# Remove plugin
rm -rf ~/.claude/plugins/plugin-name
```

## Plugin Dependencies

Plugins can depend on:

- Other plugins
- External npm packages
- System utilities
- MCP servers
- Design Bridge infrastructure

## Plugin Best Practices

1. **Self-contained**: Include all necessary files in plugin directory
2. **Documented**: Comprehensive README.md
3. **Versioned**: Semantic versioning (1.0.0)
4. **Tested**: Include test files and test harnesses
5. **Licensed**: Clear license terms
6. **Configurable**: Support .local.md for per-project config
7. **Modular**: Separate concerns (commands, skills, agents, hooks)
8. **Performant**: Optimize for fast load times

## Plugin Use Cases

- **Design Workflows**: Design-to-code automation
- **Development Workflows**: Code generation and transformation
- **Testing Workflows**: Automated testing and validation
- **Integration Workflows**: External service integration
- **Documentation Workflows**: Auto-generated documentation
- **Deployment Workflows**: CI/CD automation

## Plugin Marketplace

Plugins can be shared via:
- GitHub repositories
- Plugin marketplace (if available)
- Direct installation from path

**Installation from GitHub**:
```bash
cd ~/.claude/plugins/
git clone https://github.com/user/plugin-name
```

## Related Documentation

- [Agents Inventory](./inventory-agents.md)
- [Commands Inventory](./inventory-commands.md)
- [Skills Inventory](./inventory-skills.md)
- [Hooks Inventory](./inventory-hooks.md)
- [Plugin Development Skill](../skills/command-name/)

---

**Last Updated**: 2026-01-15
**Active Plugin Count**: 8
**Categories**: Design Bridge (6), E2B Orchestration (1), Frontend (1)
**Backup Count**: 1
