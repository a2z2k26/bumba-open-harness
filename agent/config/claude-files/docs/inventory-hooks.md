# Claude Code Hooks Inventory

This document catalogs all custom hooks built for Claude Code. Hooks are event-driven automation scripts that execute in response to specific events or file changes.

## Overview

- **Total Hooks**: 23 files
- **Location**: `/opt/bumba-harness/.claude/hooks/`
- **Types**: JavaScript hooks (.js), Shell scripts (.sh)
- **Categories**: Design Bridge (14), Memory (3), Registry Management (3), Infrastructure (3)

---

## Hook System Infrastructure

### design-bridge-hook-registry.js
**Type**: Registry system
**Version**: Latest

Central hook management system for loading, registering, and triggering hooks.

**Functions**:
- `loadHooks()`: Load all hooks from hooks directory
- `trigger(hookName, data)`: Trigger specific hook with data
- `getStatus()`: Get hook status and load summary

**Status Tracking**:
- Loaded hooks
- Failed hooks
- Disabled hooks
- Last run timestamps

---

### design-bridge-hook-index.js
**Type**: Hook orchestrator
**Version**: Latest

Main entry point for the Design Bridge hook system. Manages hook lifecycle and coordination.

---

### index.js
**Type**: Hook system entry point

Main hook index for Claude Code hook system.

---

### trigger-design-hooks.js
**Type**: Hook trigger utility

Utility for manually triggering Design Bridge hooks for testing and debugging.

---

## Design Bridge Hooks

Design Bridge hooks automate the workflow for design token extraction, component transformation, and code generation.

### Component Lifecycle Hooks

#### on-component-extract.js
**Event**: Component extracted from design source
**Watch**: Design extraction events
**Priority**: High

Triggered when a component is extracted from Figma, ShadCN, or NLP source. Updates component registry and prepares for transformation.

**Actions**:
- Updates component registry
- Validates extraction
- Prepares transformation queue

---

#### on-component-transform.js
**Event**: Component transformed to framework code
**Watch**: `.design/extracted-code/**/*`
**Debounce**: 500ms
**Version**: 2.0.0
**Priority**: 100

Auto-generates Storybook stories after component transformation with checksum guard for conflict detection.

**Features**:
- Two-state architecture integration
- Story hash registry for modification detection
- Storybook story generation (React, Vue, Svelte, Angular, Web Components)
- Preview-only mode for Flutter, SwiftUI, Jetpack Compose, React Native
- Cascade sync detection to avoid duplicates

**Actions**:
- Generates Storybook stories
- Updates story hash registry
- Updates transform state
- Validates component output

---

### Layout Lifecycle Hooks

#### on-layout-extract.js
**Event**: Layout extracted from Figma
**Watch**: Layout extraction events

Triggered when a layout is extracted from Figma. Captures layout structure and screenshot.

**Actions**:
- Updates layout manifest
- Saves layout JSON
- Captures screenshot
- Prepares for transformation

---

#### on-layout-transform-complete.js
**Event**: Layout code generation complete
**Watch**: Layout transformation events
**Version**: Latest

Triggered after layout is transformed to framework code. Validates output and updates manifest.

**Actions**:
- Validates generated code
- Updates layout manifest status
- Triggers visual validation
- Updates transformation state

---

### Token Management Hooks

#### on-token-change.js
**Event**: Design token file changed
**Watch**: `.design/tokens/**/*`

Triggered when design tokens are modified. Propagates changes to dependent systems.

**Actions**:
- Validates token changes
- Updates token registry
- Triggers cascade updates
- Notifies dependent components

---

#### on-tokens-updated.js
**Event**: Token update complete
**Watch**: Token transformation events
**Version**: Latest

Triggered after tokens are transformed to framework format. Updates generated code.

**Actions**:
- Updates theme files
- Regenerates component styles
- Updates Storybook themes
- Validates token integration

---

### Registry Management Hooks

#### on-registry-change.js
**Event**: Component registry modified
**Watch**: `.design/componentRegistry.json`

Triggered when component registry is updated. Maintains consistency across the system.

**Actions**:
- Validates registry changes
- Updates dependent files
- Triggers cascade sync
- Maintains registry integrity

---

#### on-cascade-complete.js
**Event**: Cascade sync operation complete

Triggered after cascade sync finishes updating all related files.

**Actions**:
- Validates cascade sync results
- Updates state tracking
- Clears processing flags
- Generates sync report

---

### Sync Monitoring Hooks

#### on-sync-changes.js
**Event**: Design sync detected changes
**Watch**: Figma sync events
**Version**: Latest

Monitors design changes from Figma and triggers appropriate update workflows.

**Actions**:
- Detects component changes
- Detects layout changes
- Detects token changes
- Triggers update workflows

---

#### post-sync-monitor.sh
**Type**: Shell script
**Event**: Post-sync monitoring

Shell script for monitoring sync operations and cleanup.

**Actions**:
- Monitors sync status
- Cleanup temporary files
- Validates sync results
- Logs sync operations

---

### System Initialization Hooks

#### on-design-init-complete.js
**Event**: Design system initialization complete
**Watch**: Design init events
**Version**: Latest

Triggered after `/design-init` command completes. Sets up Design Bridge infrastructure.

**Actions**:
- Validates directory structure
- Initializes registries
- Configures Storybook
- Sets up git integration

---

#### on-design-server-setup.js
**Event**: Design server setup
**Executable**: Yes

Sets up the Bumba Design server for Figma plugin connectivity.

**Actions**:
- Configures server
- Sets up WebSocket connections
- Initializes plugin communication
- Validates server status

---

### Project Lifecycle Hooks

#### on-project-init-complete.js
**Event**: Project initialization complete
**Watch**: Project init events
**Version**: Latest

Triggered after `/project:init` command completes. Sets up project structure and configuration.

**Actions**:
- Validates project structure
- Initializes configuration
- Sets up git hooks
- Creates documentation templates

---

## Memory Hooks

Memory hooks integrate with the Bumba Memory system for session and context management.

### memory-session-start.sh
**Type**: Shell script
**Event**: Claude Code session start
**Executable**: Yes
**Version**: Latest

Triggered when a Claude Code session starts. Initializes memory context.

**Actions**:
- Loads session context
- Retrieves relevant memories
- Initializes memory store
- Logs session start

---

### memory-session-stop.sh
**Type**: Shell script
**Event**: Claude Code session end
**Executable**: Yes
**Version**: Latest

Triggered when a Claude Code session ends. Saves session context.

**Actions**:
- Saves session context
- Stores new memories
- Cleans up temporary data
- Logs session end

---

### memory-subagent-stop.sh
**Type**: Shell script
**Event**: Subagent stopped
**Executable**: Yes
**Version**: Latest

Triggered when a subagent completes. Captures subagent context and learnings.

**Actions**:
- Saves subagent context
- Captures learnings
- Updates memory store
- Logs subagent completion

---

## PreToolUse Hooks

PreToolUse hooks intercept tool calls before execution for validation and modification.

### PreToolUse/ensure-design-system-modules.js
**Type**: PreToolUse hook
**Event**: Before tool execution

Ensures design system modules are available before executing design-related tools.

**Actions**:
- Validates module availability
- Checks for required dependencies
- Provides helpful error messages
- Suggests installation steps if needed

---

## Hook Structure

JavaScript hooks follow this structure:

```javascript
module.exports = {
  name: 'hook-name',
  version: '1.0.0',
  description: 'Hook description',
  watch: 'file-pattern-to-watch',  // or null for event-driven
  debounce: 500,                    // milliseconds
  enabled: true,
  priority: 100,                    // execution order

  async execute(event) {
    // Hook logic
    return {
      success: true,
      message: 'Hook executed',
      action: 'completed'
    };
  }
};
```

Shell script hooks:
```bash
#!/bin/bash
# Hook: hook-name
# Description: Hook description
# Event: event-trigger

# Hook logic
```

## Hook Events

Hooks can be triggered by:

1. **File Watch Events**: Triggered when watched files change
   - Uses glob patterns
   - Supports debouncing

2. **Explicit Events**: Triggered programmatically
   - Component extraction
   - Component transformation
   - Layout extraction
   - Registry changes
   - Session lifecycle

3. **Tool Use Events**: PreToolUse, PostToolUse hooks
   - Intercept tool calls
   - Validate parameters
   - Modify behavior

## Hook Priority

Hooks execute in priority order (higher priority = earlier execution):
- **Critical system hooks**: 1000+
- **Component lifecycle**: 100-500
- **State management**: 50-99
- **Logging/monitoring**: 1-49

## Hook Execution Flow

1. **Event occurs** (file change, explicit trigger, tool use)
2. **Hook registry matches event** to registered hooks
3. **Hooks execute in priority order**
4. **Each hook returns result** (success/failure, actions taken)
5. **Results aggregated** and logged
6. **Dependent hooks triggered** if configured

## Hook Testing

Test hooks using the design-bridge test harness:

**File**: `hooks/tests/design-bridge-test-harness.js`

```bash
# Test specific hook
node .claude/hooks/tests/design-bridge-test-harness.js on-component-transform

# Test all hooks
node .claude/hooks/tests/design-bridge-test-harness.js --all
```

## Hook Configuration

Hooks can be:
- **Enabled/Disabled**: Set `enabled: true/false`
- **Priority adjusted**: Change `priority` value
- **Debounced**: Set `debounce` milliseconds
- **Watch pattern changed**: Modify `watch` glob pattern

## Related Documentation

- [Agents Inventory](./inventory-agents.md)
- [Commands Inventory](./inventory-commands.md)
- [Skills Inventory](./inventory-skills.md)
- [Plugins Inventory](./inventory-plugins.md)
- [Hook Development Skill](../skills/hook-development/)

---

**Last Updated**: 2026-01-15
**Hook Count**: 23
**Categories**: Design Bridge (14), Memory (3), Registry (3), Infrastructure (3)
