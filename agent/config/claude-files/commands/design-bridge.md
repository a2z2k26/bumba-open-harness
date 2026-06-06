---
name: design-bridge
description: Control the Bumba Design server for Figma plugin connectivity (start, stop, status, restart)
allowed-tools: Read, Bash
---

# Design Bridge Server Control

Control the Bumba Design server for Figma plugin connectivity.

## Server Location
The server is located at `./server/` in the project root.

## Available Actions

Based on user request, perform ONE of the following:

### Start Server
```bash
cd server && node start-test-server.js
```
- Starts on HTTP port 9001
- WebSocket on port 9002
- Verify with: `curl http://localhost:9001/health`

### Stop Server
```bash
pkill -f "node.*start-test-server" || pkill -f "node.*design-bridge"
```

### Check Status
```bash
curl -s http://localhost:9001/health 2>/dev/null && echo " Server is running" || echo "Server is NOT running"
```

### Restart Server
Stop then start the server.

## Endpoints Reference
- `GET /health` - Health check
- `POST /api/bind` - Bind Figma file to project
- `POST /api/unbind` - Unbind project
- `POST /api/tokens` - Receive extracted tokens
- `GET /api/sync/status` - Get sync status

## Usage Examples
- "start the design bridge server"
- "stop design bridge"
- "check if design bridge is running"
- "restart the design bridge server"

When starting, run in background and confirm it's healthy. When stopping, confirm the process is terminated.
