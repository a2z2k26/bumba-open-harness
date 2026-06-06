---
name: deploy
description: Create a deploy manifest for the deploy helper daemon
---

# /deploy — Self-Deploy via Deploy Helper

Creates a deploy manifest JSON file that the deploy helper daemon picks up and executes. Eliminates the need for operator `sudo bash` for most deploys.

## Usage

```
/deploy [--description "what this deploys"]
/deploy status <manifest-id>
/deploy approve <manifest-id>
/deploy reject <manifest-id>
```

## Workflow

### Step 1: Collect Files to Deploy

Identify all files that need deploying. For each file, determine:
- `src`: absolute path in source directory (`/home/bumba/Documents/bumba-open-harness/agent/...`)
- `dst`: absolute path in deploy target (`/opt/bumba-harness/agent-flat/agent/...`)
- `owner`: typically `bumba-agent:staff`
- `mode`: typically `644` (or `600` for files with secrets)

### Step 2: Auto-Classify Tier

For each destination path, classify:

**Tier A (auto-execute):**
- `config/claude-files/**` — commands, skills, docs, templates
- `data/**` — project registries, state files
- `docs/**` — documentation
- `tools/**` — CLI tools
- `mcp-servers/**` — MCP server code

**Tier B (needs approval):**
- `config/system-prompt.md`
- `config/hooks/**`
- `config/bridge.toml`
- `.mcp.json`

**Tier C (rejected — operator only):**
- `bridge/*.py` — core bridge code
- `*.plist` — LaunchDaemon definitions
- `data/kernel-baseline.json`

The manifest tier = highest tier among all files.

### Step 3: Display Classification

Show the operator what will happen:
```
Deploy Classification: Tier A (auto-execute)

Files:
  [A] config/claude-files/commands/project/register.md
  [A] config/claude-files/skills/track-switching/SKILL.md

No approval needed — deploy helper will execute automatically.
```

Or for Tier B:
```
Deploy Classification: Tier B (requires Discord approval)

Files:
  [A] config/claude-files/commands/deploy.md
  [B] config/system-prompt.md    ← triggers approval

You'll receive a Discord message to approve/reject.
```

Or for Tier C:
```
Deploy Classification: Tier C (BLOCKED)

Files:
  [C] bridge/app.py    ← kernel file, operator-only

Cannot self-deploy kernel files. Request operator: sudo bash /tmp/deploy-xyz.sh
```

### Step 4: Write Manifest

Generate UUID, write manifest to `data/deploy-requests/<uuid>.json`:

```json
{
  "id": "<uuid>",
  "tier": "A",
  "description": "Deploy project registry commands and track switching skill",
  "files": [...],
  "pre_commands": ["mkdir -p /opt/bumba-harness/data/projects"],
  "post_commands": [],
  "requires_baseline_regen": false,
  "requires_restart": false,
  "status": "pending",
  "created_at": "2026-03-05T14:30:00Z",
  "completed_at": null,
  "error": null
}
```

### Step 5: Monitor Status

Poll the manifest file for status changes:
```bash
cat data/deploy-requests/<uuid>.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['status'])"
```

Report final status:
```
Deploy completed successfully.
```
or
```
Deploy failed: <error message>
```

## Subcommands

### `/deploy status <id>`
Check the status of a deploy manifest.

### `/deploy approve <id>`
Write approval response (used by operator via Discord or directly):
```json
{"action": "approved"}
```
Written to `data/deploy-requests/<id>.response`.

### `/deploy reject <id>`
Write rejection response:
```json
{"action": "rejected"}
```

## Integration

- Run `/validate` before deploying to ensure tests pass
- Tier A deploys complete in ~10 seconds (next poll cycle)
- Tier B deploys require Discord approval (1 hour timeout)
- Tier C deploys are auto-rejected — create a `/tmp/deploy-*.sh` script instead

## Notes

- Deploy helper must be running (`com.bumba.deploy-helper` LaunchDaemon)
- Manifests persist in `data/deploy-requests/` for audit trail
- Set `requires_baseline_regen: true` if deploying kernel-adjacent files (Tier B)
- Set `requires_restart: true` if deploying bridge code changes
