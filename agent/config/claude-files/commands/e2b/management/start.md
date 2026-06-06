---
name: start
description: Start new E2B sandbox
---

# /sandbox-start Command

Start or restart the Bumba Sandbox orchestrator MCP server.

## Usage

```
/sandbox-start [--rebuild]
```

## Parameters

- `--rebuild` (optional): Rebuild TypeScript before starting

## Workflow

### Step 1: Check Current Server Status

```bash
# Check if server process is running
pgrep -f "bumba-sandbox.js" && echo "Server is running" || echo "Server is not running"
```

### Step 2: Rebuild (if --rebuild flag)

If `--rebuild` is specified:

```bash
cd /home/operator/Bumba-Sandbox-MCP && npm run build
```

### Step 3: Start the Server

```bash
cd /home/operator/Bumba-Sandbox-MCP && npm run mcp-server
```

### Step 4: Verify Server Started

```bash
# Wait briefly then check
sleep 2
pgrep -f "bumba-sandbox.js" && echo "✓ Bumba Sandbox server started" || echo "✗ Failed to start server"
```

## Output

```
🚀 Bumba Sandbox Server
═══════════════════════════════════════════════

Status: Starting...
Location: /home/operator/Bumba-Sandbox-MCP
Script: npm run mcp-server

✓ Server started successfully
  PID: 12345

Note: MCP servers configured in settings.json
auto-start with Claude Code. Use this command
to manually restart after code changes.
```

## Notes

- MCP servers in `~/.claude/settings.json` auto-start with Claude Code
- Use this to restart after modifying server code
- Use `--rebuild` after TypeScript changes
- Check logs with `/sandbox-debug` if issues occur
