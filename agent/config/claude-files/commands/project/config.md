---
name: config
description: Manage project configuration
---

# /config Command

Manages Bumba Sandbox Orchestrator configuration including modes, strategies, hooks, budgets, and all system settings.

## Usage

```
/config <action> [key] [value]
```

## Actions

- `show`: Display all configuration settings
- `get <key>`: Get specific configuration value
- `set <key> <value>`: Set configuration value
- `reset [key]`: Reset to defaults (all or specific key)
- `validate`: Validate current configuration

## Parameters

- `<key>`: Configuration key (dot notation: `parallel.defaultStrategy`)
- `<value>`: New value for the key

## Configuration Categories

### Mode Settings

```json
{
  "defaultMode": "auto",
  "autoModeRules": {
    "backend": "sandbox",
    "frontend": "local",
    "database": "sandbox",
    "docs": "local"
  }
}
```

### Sandbox Settings

```json
{
  "sandboxDefaults": {
    "template": "node-typescript",
    "maxConcurrent": 10,
    "timeout": 86400,
    "autoCleanup": true,
    "cleanupDelay": 3600
  }
}
```

### Hook Configuration

```json
{
  "hookConfig": {
    "enabled": ["PreToolUse", "PostToolUse", "Stop"],
    "pathRestrictions": ["temp/"],
    "allowedLocalTools": ["files_read", "files_write"],
    "deniedTools": ["execute_command"]
  }
}
```

### Cost Management

```json
{
  "costManagement": {
    "budgetLimit": 100,
    "alertThresholds": [50, 75, 90],
    "autoStop": false,
    "optimizeAutomatically": true
  }
}
```

### Parallel Execution

```json
{
  "parallel": {
    "defaultStrategy": "balanced",
    "maxConcurrent": 10,
    "defaultMode": "auto",
    "autoSpawn": true,
    "monitorInterval": 30
  }
}
```

## Examples

### Example 1: Show All Config
```
/config show
```

### Example 2: Get Specific Value
```
/config get parallel.defaultStrategy
```
Output: `balanced`

### Example 3: Set Budget Limit
```
/config set costManagement.budgetLimit 150
```

### Example 4: Enable Hook
```
/config set hookConfig.enabled PreToolUse,PostToolUse,Stop,UserPromptSubmit
```

### Example 5: Reset to Defaults
```
/config reset
```

### Example 6: Validate Configuration
```
/config validate
```

### Example 7: Update Multiple Settings
```
/config set parallel.maxConcurrent 15
/config set costManagement.budgetLimit 200
/config set sandboxDefaults.template my-custom-template
```

### Example 8: View Specific Category
```
/config get parallel
```
Output:
```json
{
  "defaultStrategy": "balanced",
  "maxConcurrent": 10,
  "defaultMode": "auto",
  "autoSpawn": true,
  "monitorInterval": 30,
  "keepFailedSandboxes": true
}
```

### Example 9: Disable Auto-Cleanup
```
/config set sandboxDefaults.autoCleanup false
```

### Example 10: Configure Alert Thresholds
```
/config set costManagement.alertThresholds 60,80,95
```

## Common Configuration Scenarios

### Scenario 1: Cost-Conscious Setup
For users who want to minimize costs:
```bash
/config set parallel.defaultStrategy cost-optimized
/config set costManagement.budgetLimit 50
/config set costManagement.autoStop true
/config set costManagement.alertThresholds 40,60,80
/config set sandboxDefaults.autoCleanup true
/config set sandboxDefaults.cleanupDelay 1800  # 30 minutes
```

### Scenario 2: Maximum Performance Setup
For users who prioritize speed over cost:
```bash
/config set parallel.defaultStrategy max-speed
/config set parallel.maxConcurrent 20
/config set sandboxDefaults.maxConcurrent 20
/config set costManagement.budgetLimit 500
/config set parallel.autoSpawn true
```

### Scenario 3: Balanced Production Setup
Recommended for most production use:
```bash
/config set parallel.defaultStrategy balanced
/config set parallel.maxConcurrent 10
/config set costManagement.budgetLimit 150
/config set sandboxDefaults.autoCleanup true
/config set hookConfig.enabled PreToolUse,PostToolUse,Stop,UserPromptSubmit
/config set notifications.enabled true
```

### Scenario 4: Development/Testing Setup
For local development and testing:
```bash
/config set defaultMode local
/config set parallel.maxConcurrent 3
/config set costManagement.budgetLimit 25
/config set sandboxDefaults.template development
/config set hookConfig.enabled PreToolUse,PostToolUse
```

## Complete Configuration Reference

```json
{
  "defaultMode": "auto",
  "autoModeRules": {
    "backend": "sandbox",
    "frontend": "local",
    "database": "sandbox",
    "security": "sandbox",
    "docs": "local"
  },
  "sandboxDefaults": {
    "template": "node-typescript",
    "maxConcurrent": 10,
    "timeout": 86400,
    "autoCleanup": true,
    "cleanupDelay": 3600
  },
  "hookConfig": {
    "enabled": ["PreToolUse", "PostToolUse", "Stop"],
    "pathRestrictions": ["temp/"],
    "allowedLocalTools": ["files_read", "files_write", "files_list"],
    "deniedTools": []
  },
  "costManagement": {
    "budgetLimit": 100,
    "alertThresholds": [50, 75, 90],
    "autoStop": false,
    "optimizeAutomatically": true
  },
  "parallel": {
    "defaultStrategy": "balanced",
    "maxConcurrent": 10,
    "defaultMode": "auto",
    "autoSpawn": true,
    "monitorInterval": 30,
    "keepFailedSandboxes": true
  },
  "cleanup": {
    "idleThreshold": 1,
    "autoCleanup": false,
    "autoCleanupInterval": 3600,
    "syncBeforeCleanup": true,
    "archiveLogs": true,
    "criteria": "smart"
  },
  "orchestrator": {
    "stateFile": ".claude/config/orchestrator-state.json",
    "autoSave": true,
    "saveInterval": 30,
    "maxEventLog": 1000
  },
  "notifications": {
    "enabled": true,
    "channels": ["console"],
    "events": ["completion", "failure", "budgetAlert"]
  }
}
```

## Error Handling

### Common Errors

**Invalid Configuration Key**:
```
❌ Error: Invalid configuration key

Key: parallel.invalidSetting

Valid keys in 'parallel' category:
  - parallel.defaultStrategy
  - parallel.maxConcurrent
  - parallel.defaultMode
  - parallel.autoSpawn
  - parallel.monitorInterval
  - parallel.keepFailedSandboxes

All valid configuration keys:
  Run: /config show

Suggestion: Did you mean 'parallel.defaultStrategy'?
```

**Invalid Value Type**:
```
❌ Error: Invalid value type

Key: parallel.maxConcurrent
Expected: number (integer)
Received: "ten" (string)

Valid examples:
  /config set parallel.maxConcurrent 10
  /config set parallel.maxConcurrent 5

Constraints:
  - Must be an integer
  - Range: 1-50
  - Default: 10
```

**Value Out of Range**:
```
❌ Error: Value out of valid range

Key: parallel.maxConcurrent
Value: 100
Valid range: 1-50

Explanation:
  Maximum concurrent sandboxes is limited to 50 to prevent
  resource exhaustion and excessive costs.

Recommended values:
  - Small projects: 3-5
  - Medium projects: 5-10
  - Large projects: 10-20
  - Maximum: 50

Try: /config set parallel.maxConcurrent 20
```

**Invalid Strategy Name**:
```
❌ Error: Invalid strategy value

Key: parallel.defaultStrategy
Value: "super-fast"

Valid strategies:
  - max-speed: Maximum parallelism, highest cost
  - balanced: Optimal time/cost ratio (recommended)
  - cost-optimized: Sequential execution, lowest cost

Example:
  /config set parallel.defaultStrategy balanced
```

**Configuration File Corrupted**:
```
❌ Error: Cannot read configuration file

File: .claude/config/bumba-sandbox-config.json
Error: Unexpected token in JSON at position 145

Recovery options:
  [1] Reset to defaults (recommended)
  [2] Restore from backup
  [3] Manually edit file
  [4] Cancel

Select option (1-4): _

If you select [1] Reset to defaults:
  ✓ Configuration reset to factory defaults
  ⚠️  Custom settings will be lost
  ✓ File will be regenerated

Backup saved to: .claude/config/bumba-sandbox-config.json.backup
```

**File Permission Error**:
```
❌ Error: Cannot write to configuration file

File: .claude/config/bumba-sandbox-config.json
Error: EACCES: permission denied

Cause: No write permission for configuration file

Solutions:
  1. Check file permissions:
     ls -l .claude/config/bumba-sandbox-config.json

  2. Fix permissions:
     chmod 644 .claude/config/bumba-sandbox-config.json

  3. Check directory permissions:
     ls -ld .claude/config/

Configuration change NOT saved.
Current settings remain unchanged.
```

**Validation Errors**:
```
❌ Configuration validation failed

Found 3 issues:

1. costManagement.budgetLimit
   Problem: Cannot be negative
   Current: -50
   Fix: Set to positive number or 0 for unlimited

2. hookConfig.enabled
   Problem: Invalid hook type "InvalidHook"
   Current: ["PreToolUse", "InvalidHook"]
   Valid: PreToolUse, PostToolUse, Stop, UserPromptSubmit, SubagentStop, PreCompact

3. parallel.maxConcurrent
   Problem: Exceeds sandboxDefaults.maxConcurrent
   Current: parallel.maxConcurrent = 20, sandboxDefaults.maxConcurrent = 10
   Fix: Ensure parallel.maxConcurrent <= sandboxDefaults.maxConcurrent

Run '/config validate' to see all validation errors.
Configuration NOT saved due to validation errors.
```

**Missing Required Value**:
```
❌ Error: Missing required value

Command: /config set costManagement.budgetLimit

Usage: /config set <key> <value>

Example:
  /config set costManagement.budgetLimit 100

To view current value:
  /config get costManagement.budgetLimit

To reset to default:
  /config reset costManagement.budgetLimit
```

### Recovery Actions

**Automatic Recovery**:
- Creates backup before changes
- Validates all changes before saving
- Rolls back on validation failure
- Preserves existing config on errors
- Provides helpful error messages

**Manual Recovery**:
```bash
# View current configuration
cat .claude/config/bumba-sandbox-config.json

# Restore from backup (if exists)
cp .claude/config/bumba-sandbox-config.json.backup .claude/config/bumba-sandbox-config.json

# Reset specific key
/config reset costManagement.budgetLimit

# Reset all settings
/config reset

# Manually edit (advanced)
vim .claude/config/bumba-sandbox-config.json

# Validate after manual edits
/config validate
```

**Validation Failures**:
If validation fails:
1. Configuration is NOT saved
2. Previous settings remain active
3. Detailed error messages explain issues
4. Suggested fixes provided
5. No need to restore from backup

## Notes

- Configuration stored in `.claude/config/bumba-sandbox-config.json`
- Changes take effect immediately
- Invalid values are rejected with helpful error messages
- Validation ensures type safety
- Reset restores defaults without confirmation
- Automatic backup created before each change
- Supports dot notation for nested keys (e.g., `parallel.maxConcurrent`)
- All changes are validated before being saved
- Configuration persists across sessions
