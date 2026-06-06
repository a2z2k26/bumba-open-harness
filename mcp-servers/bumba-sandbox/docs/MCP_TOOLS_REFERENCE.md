# Bumba Sandbox Orchestrator MCP Tools Reference

**Server**: bumba-sandbox v1.0.0
**Total Tools**: 24
**Transport**: Stdio (Claude Desktop compatible)

## Tool Categories

### 1. Lifecycle Management (5 tools)
Manage E2B sandbox creation, connection, and termination.

### 2. File Operations (10 tools)
Complete file management within sandboxes.

### 3. Command Execution (1 tool)
Execute commands in sandboxes with full control.

### 4. Orchestration (8 tools)
Multi-agent orchestration, dependency analysis, resource allocation.

---

## Lifecycle Management Tools

### `sandbox_init`
Initialize a new sandbox with optional template.

**Parameters**:
- `template` (string, optional): Sandbox template (node, python, base, go, rust, java)
- `timeout` (number, optional): Timeout in seconds (default: 3600)

**Returns**:
```json
{
  "sandboxId": "string",
  "template": "string",
  "status": "running",
  "url": null
}
```

### `sandbox_create`
Create sandbox with advanced configuration.

**Parameters**:
- `template` (string, optional): Sandbox template
- `timeout` (number, optional): Timeout in seconds
- `metadata` (object, optional): Custom metadata
- `env` (object, optional): Environment variables

**Returns**:
```json
{
  "sandboxId": "string",
  "template": "string",
  "status": "running",
  "metadata": {},
  "createdAt": "ISO 8601 timestamp"
}
```

### `sandbox_connect`
Connect to existing sandbox by ID.

**Parameters**:
- `sandboxId` (string, required): Existing sandbox ID

**Returns**:
```json
{
  "sandboxId": "string",
  "status": "running",
  "connected": true,
  "message": "string"
}
```

### `sandbox_kill`
Terminate and cleanup sandbox.

**Parameters**:
- `sandboxId` (string, required): Sandbox ID to terminate

**Returns**:
```json
{
  "sandboxId": "string",
  "status": "terminated",
  "terminated": true,
  "message": "string"
}
```

### `sandbox_status`
Get sandbox status and health information.

**Parameters**:
- `sandboxId` (string, required): Sandbox ID

**Returns**:
```json
{
  "sandboxId": "string",
  "status": "running | unknown",
  "registered": true | false,
  "template": "string"
}
```

---

## File Operation Tools

### `files_list`
List files and directories in sandbox path.

**Parameters**:
- `sandboxId` (string, required)
- `path` (string, optional): Directory path (default: "/")

**Returns**:
```json
{
  "path": "string",
  "entries": [
    {
      "name": "string",
      "path": "string",
      "type": "file | directory",
      "size": number
    }
  ],
  "count": number
}
```

### `files_read`
Read text file from sandbox.

**Parameters**:
- `sandboxId` (string, required)
- `path` (string, required): File path

**Returns**:
```json
{
  "path": "string",
  "content": "string",
  "size": number
}
```

### `files_write`
Write text file to sandbox.

**Parameters**:
- `sandboxId` (string, required)
- `path` (string, required): File path
- `content` (string, required): File content

**Returns**:
```json
{
  "path": "string",
  "size": number,
  "success": true
}
```

### `files_upload`
Upload binary file to sandbox.

**Parameters**:
- `sandboxId` (string, required)
- `path` (string, required): File path
- `content` (string, required): Base64 encoded binary data

**Returns**:
```json
{
  "path": "string",
  "size": number,
  "success": true
}
```

### `files_download`
Download binary file from sandbox.

**Parameters**:
- `sandboxId` (string, required)
- `path` (string, required): File path

**Returns**:
```json
{
  "path": "string",
  "content": "base64 string",
  "size": number
}
```

### `file_exists`
Check if file or directory exists.

**Parameters**:
- `sandboxId` (string, required)
- `path` (string, required): Path to check

**Returns**:
```json
{
  "path": "string",
  "exists": true | false
}
```

### `file_info`
Get file or directory metadata.

**Parameters**:
- `sandboxId` (string, required)
- `path` (string, required): Path to inspect

**Returns**:
```json
{
  "path": "string",
  "exists": true | false,
  "type": "file | directory",
  "size": number
}
```

### `file_remove`
Remove file or directory.

**Parameters**:
- `sandboxId` (string, required)
- `path` (string, required): Path to remove

**Returns**:
```json
{
  "path": "string",
  "removed": true,
  "message": "string"
}
```

### `file_rename`
Rename or move file.

**Parameters**:
- `sandboxId` (string, required)
- `oldPath` (string, required): Current path
- `newPath` (string, required): New path

**Returns**:
```json
{
  "oldPath": "string",
  "newPath": "string",
  "renamed": true,
  "message": "string"
}
```

### `make_directory`
Create directory (including parent directories).

**Parameters**:
- `sandboxId` (string, required)
- `path` (string, required): Directory path to create

**Returns**:
```json
{
  "path": "string",
  "created": true,
  "message": "string"
}
```

---

## Command Execution Tool

### `execute_command`
Execute command in sandbox with full control.

**Parameters**:
- `sandboxId` (string, required): Sandbox ID
- `command` (string, required): Command to execute
- `shell` (string, optional): Shell to use (default: /bin/bash)
- `root` (boolean, optional): Run with sudo
- `env` (object, optional): Environment variables
- `cwd` (string, optional): Working directory
- `timeout` (number, optional): Timeout in seconds (default: 60)
- `background` (boolean, optional): Run in background

**Returns**:
```json
{
  "stdout": "string",
  "stderr": "string",
  "exitCode": number,
  "success": boolean,
  "duration": number
}
```

---

## Orchestration Tools

### `analyze_dependencies`
Analyze GitHub issue dependencies and build dependency graph.

**Parameters**:
- `owner` (string, required): GitHub repository owner
- `repo` (string, required): GitHub repository name
- `issues` (array, required): Array of issue numbers

**Returns**:
```json
{
  "graph": {
    "nodes": {
      "issueNumber": {
        "issueNumber": number,
        "title": "string",
        "status": "ready | blocked | completed | failed",
        "dependencies": [number],
        "blockedBy": [number],
        "labels": ["string"]
      }
    },
    "edges": [
      { "from": number, "to": number }
    ]
  },
  "ready": [number],
  "blocked": [number],
  "circular": [[number]] | undefined
}
```

### `plan_sandbox_allocation`
Plan sandbox allocation with different strategies.

**Parameters**:
- `readyIssues` (array, required): Array of ready issue numbers
- `maxConcurrent` (number, required): Max concurrent sandboxes
- `budgetLimit` (number, required): Budget limit in dollars
- `strategy` (string, optional): max-speed | cost-optimized | balanced

**Returns**:
```json
{
  "strategy": "string",
  "immediate": [number],
  "queued": [number],
  "deferred": [number],
  "estimatedCost": number,
  "estimatedTime": number
}
```

### `spawn_sandbox_agent`
Spawn sandbox agent for an issue (placeholder).

**Parameters**:
- `issueNumber` (number, required): Issue number
- `worktreePath` (string, optional): Git worktree path
- `template` (string, optional): Sandbox template

**Returns**:
```json
{
  "agentId": "string",
  "sandboxId": "string",
  "issueNumber": number,
  "status": "string",
  "message": "string"
}
```

### `monitor_agents`
Monitor all active agents and get summary statistics.

**Parameters**:
- `filter` (object, optional): Filter options

**Returns**:
```json
{
  "agents": [
    {
      "agentId": "string",
      "issueNumber": number,
      "status": "string",
      "progress": number,
      "cost": number,
      "uptime": number
    }
  ],
  "summary": {
    "total": number,
    "active": number,
    "completed": number,
    "failed": number,
    "averageProgress": number,
    "totalCost": number
  }
}
```

### `handle_agent_event`
Handle agent events and trigger auto-spawn (placeholder).

**Parameters**:
- `agentId` (string, required): Agent ID
- `event` (object, required): Event data

**Returns**:
```json
{
  "handled": boolean,
  "actions": ["string"],
  "message": "string"
}
```

### `optimize_resources`
Analyze resource usage and provide optimization recommendations.

**Parameters**:
- `criteria` (string, optional): cost | performance | balanced

**Returns**:
```json
{
  "recommendations": ["string"],
  "potentialSavings": number,
  "idleSandboxes": ["string"]
}
```

### `get_cost_tracking`
Get cost tracking information from hook logs.

**Parameters**: None

**Returns**:
```json
{
  "totalCost": number,
  "breakdown": {
    "sandboxCosts": number,
    "apiCosts": number
  },
  "budgetUsed": number,
  "budgetRemaining": number
}
```

---

## Configuration

### Environment Variables
- `E2B_API_KEY`: E2B API key (required for sandbox operations)
- `GITHUB_TOKEN`: GitHub Personal Access Token (required for analyze_dependencies)
- `ANTHROPIC_API_KEY`: Anthropic API key (for agent spawning)

### Server Registration (Claude Desktop)

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "bumba-sandbox": {
      "command": "node",
      "args": [
        "/path/to/project/dist/mcp-servers/bumba-sandbox.js"
      ],
      "env": {
        "E2B_API_KEY": "your-e2b-api-key",
        "GITHUB_TOKEN": "your-github-token"
      }
    }
  }
}
```

---

## Implementation Status

**Fully Implemented**:
- All 5 lifecycle tools ✓
- All 10 file operation tools ✓
- Command execution tool ✓
- analyze_dependencies (with circular dependency detection) ✓
- plan_sandbox_allocation (3 strategies) ✓

**Placeholder/Simplified**:
- spawn_sandbox_agent (needs E2B sandbox creation + hook integration)
- monitor_agents (needs hook log querying)
- handle_agent_event (needs auto-spawn cascade logic)
- optimize_resources (needs sandbox metrics collection)
- get_cost_tracking (needs Stop hook integration)

---

## Next Steps for Full Implementation

1. **spawn_sandbox_agent**: Integrate with E2B SDK to create sandboxes, upload worktrees, register hooks
2. **monitor_agents**: Query hook logs using Phase 1 logging system
3. **handle_agent_event**: Implement auto-cascading logic based on dependency graph
4. **optimize_resources**: Collect sandbox metrics from E2B API
5. **get_cost_tracking**: Parse Stop hook logs for token usage and calculate costs

All foundation pieces (Phase 1: logging, hooks, configuration) are in place and ready for integration.
