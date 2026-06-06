---
name: deploy-manifest-schema
description: JSON schema for deploy request manifests used by the deploy helper daemon
---

# Deploy Manifest Schema

Deploy manifests are JSON files written to `data/deploy-requests/` by the agent. The deploy helper daemon watches this directory and processes manifests automatically.

## Schema

```json
{
  "id": "uuid-v4",
  "tier": "A|B|C",
  "description": "Human-readable description of what this deploy does",
  "files": [
    {
      "src": "/absolute/path/to/source/file",
      "dst": "/absolute/path/to/destination/file",
      "owner": "bumba-agent:staff",
      "mode": "644"
    }
  ],
  "pre_commands": [
    "mkdir -p /opt/bumba-harness/data/some-dir"
  ],
  "post_commands": [
    "chmod 600 /opt/bumba-harness/agent-flat/agent/.mcp.json"
  ],
  "requires_baseline_regen": false,
  "requires_restart": false,
  "status": "pending",
  "created_at": "2026-03-05T14:30:00Z",
  "completed_at": null,
  "error": null
}
```

## Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | UUID v4 | yes | Unique identifier for this deploy |
| `tier` | enum | auto | Set by tier classifier: A, B, or C |
| `description` | string | yes | What this deploy does (shown in approval messages) |
| `files` | array | yes | Files to copy from src to dst |
| `files[].src` | path | yes | Absolute source path |
| `files[].dst` | path | yes | Absolute destination path |
| `files[].owner` | string | yes | `user:group` for chown |
| `files[].mode` | string | yes | Octal permissions for chmod |
| `pre_commands` | array | no | Shell commands to run before file copy |
| `post_commands` | array | no | Shell commands to run after file copy |
| `requires_baseline_regen` | bool | no | Whether to regenerate kernel-baseline.json |
| `requires_restart` | bool | no | Whether to restart the bridge LaunchDaemon |
| `status` | enum | yes | `pending`, `approved`, `rejected`, `completed`, `failed` |
| `created_at` | ISO 8601 | yes | When the manifest was created |
| `completed_at` | ISO 8601 | no | When the deploy completed (set by helper) |
| `error` | string | no | Error message if status is `failed` |

## Tier Classification

Tier is auto-classified based on destination paths:

### Tier A — Auto-approve (agent-writable content)
- `config/claude-files/**` — commands, skills, docs
- `data/**` — project registries, state files
- `docs/**` — documentation
- `tools/**` — CLI tools (design-bridge, etc.)
- `mcp-servers/**` — MCP server code
- `config/notion-bridge/**` — integration configs

### Tier B — Require Discord approval (kernel-adjacent)
- `config/system-prompt.md`
- `config/hooks/**`
- `config/bridge.toml`
- `.mcp.json`

### Tier C — Reject (operator-only kernel files)
- `bridge/*.py` — core bridge code
- `*.plist` — LaunchDaemon definitions
- `data/kernel-baseline.json` — baseline itself

## Status Lifecycle

```
pending → approved → completed
                   → failed

pending → rejected (Tier B: operator rejected via Discord)

pending → rejected (Tier C: auto-rejected by helper)
```

Tier A manifests skip `approved` — go directly from `pending` to `completed`/`failed`.

## Safety Rules

1. All `dst` paths must be within `/opt/bumba-harness/agent-flat/agent/` or `/opt/bumba-harness/data/`
2. No path traversal (`..`) allowed in any path
3. `pre_commands` and `post_commands` are restricted to: `mkdir`, `chmod`, `chown`, `rm -f` (halt flag only)
4. `src` paths must exist and be readable
5. Manifests with invalid fields are rejected with `status: failed`
