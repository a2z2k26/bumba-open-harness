# Design Bridge Hooks

## Overview

Hooks are JavaScript modules that execute in response to file system events. They enable automatic workflow triggers when design files change, creating a seamless design-to-code pipeline.

## Hook Lifecycle

1. File change detected
2. Debounce timer starts (prevents rapid re-triggers)
3. Hook `execute()` function called with change event
4. Hook returns result (success/failure)
5. Result logged to console

## Creating a New Hook

Export an object with these properties:

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `name` | string | Yes | Unique hook identifier |
| `watch` | string | Yes | File or glob pattern to watch (relative to project root) |
| `debounce` | number | No | Milliseconds to wait before triggering (default: 500) |
| `enabled` | boolean | No | Whether hook is active (default: true) |
| `priority` | number | No | Execution order - lower runs first (default: 100) |
| `execute` | async function | Yes | Function receiving change event |

## Hook Template

```javascript
/**
 * Hook: [hook-name]
 * Triggers when: [description of trigger condition]
 */
const fs = require('fs').promises;
const path = require('path');

module.exports = {
  name: 'hook-name',
  watch: '.design/componentRegistry.json',
  debounce: 500,
  enabled: true,
  priority: 100,

  async execute(event) {
    console.log(`[${this.name}] Triggered by: ${event.path}`);

    try {
      // Hook logic here

      return {
        success: true,
        message: 'Hook completed successfully',
        data: {} // Optional result data
      };
    } catch (error) {
      return {
        success: false,
        message: error.message,
        error
      };
    }
  }
};
```

## Event Object

The `execute()` function receives an event object:

```javascript
{
  type: 'change' | 'add' | 'unlink',
  path: '/absolute/path/to/file',
  data: { /* Parsed file contents (if JSON) */ },
  previous: { /* Previous file contents (if available) */ }
}
```

## Hook Naming Convention

- Pattern: `on-{event}-{target}.js`
- Examples:
  - `on-registry-change.js` - Triggers on component registry updates
  - `on-token-change.js` - Triggers on design token updates
  - `on-component-extract.js` - Triggers after component extraction
  - `on-layout-extract.js` - Triggers after layout extraction

## Available Hooks

| Hook | Watch Pattern | Purpose |
|------|---------------|---------|
| `on-registry-change` | `.design/componentRegistry.json` | Queue components for transformation when registry changes |
| `on-token-change` | `.design/tokens/index.json` | Find and update dependent components when tokens change |
| `on-component-extract` | `.design/components/**/*.json` | Post-process newly extracted components |
| `on-layout-extract` | `.design/layouts/**/*.json` | Post-process newly extracted layouts |

## Usage

### Loading Hooks

```javascript
const { loadHooks, trigger, getStatus } = require('./.claude/hooks');

// Load all hooks from directory
loadHooks();

// Check what's loaded
console.log(getStatus());
```

### Triggering Hooks

```javascript
// Trigger specific hook
await trigger('on-registry-change', {
  type: 'change',
  path: '/path/to/componentRegistry.json',
  data: { /* new registry */ },
  previous: { /* old registry */ }
});
```

### Enabling/Disabling Hooks

```javascript
const { setEnabled } = require('./.claude/hooks');

// Disable a hook
setEnabled('on-token-change', false);

// Re-enable
setEnabled('on-token-change', true);
```

## Execution Order

Hooks are executed in priority order (lower priority number = runs first):

1. `on-token-change` (priority: 5) - Token changes may affect multiple components
2. `on-registry-change` (priority: 10) - Component registry updates
3. `on-component-extract` (priority: 50) - Post-extraction processing
4. `on-layout-extract` (priority: 50) - Layout post-processing

## Error Handling

- Hooks are executed in isolation - one hook's failure doesn't stop others
- All errors are caught and logged
- Failed hooks return `{ success: false, message: error.message }`
- Check hook status with `getStatus()` to see last run results

## Best Practices

1. **Idempotent**: Hooks should be safe to run multiple times with the same input
2. **Fast**: Keep hook execution under 5 seconds when possible
3. **Isolated**: Don't depend on side effects from other hooks
4. **Logged**: Use console.log with hook name prefix for debugging
5. **Graceful**: Always handle errors and return structured results

## Testing Hooks

Run the test script from project root:

```bash
node .claude/hooks/test-hooks.js
```

This will:
1. Load all hooks
2. Validate hook structure
3. Trigger with mock events
4. Report results
