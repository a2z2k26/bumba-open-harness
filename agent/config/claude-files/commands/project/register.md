---
name: register
description: Register a new project in the YAML registry
---

# /project/register — Register a Project

Creates a YAML project registry file in `data/projects/` following the canonical schema from zone-plan.md.

## Usage

```
/project/register <name> [--repo <url>]
```

## Parameters

- `<name>` (required): Project name (lowercase, hyphenated — e.g., `bumba-open-harness`, `my-saas-app`)
- `--repo <url>` (optional): GitHub repository URL

## Workflow

### Step 1: Validate Name

- Must be lowercase alphanumeric + hyphens only
- Must not already exist in `data/projects/`
- Check: `ls data/projects/<name>.yaml` — if exists, abort with "Project already registered"

### Step 2: Gather Information

Use AskUserQuestion for missing details:

**Question 1 — Description:**
"Describe this project in 1-2 sentences."

**Question 2 — Stack:**
"What's the tech stack?" (e.g., `Python 3.13, discord.py, aiosqlite`)

### Step 3: Create Registry File

Write YAML to `data/projects/<name>.yaml`:

```yaml
project: <name>
status: active
stack: <stack string>
description: <1-2 sentence description>
last_worked: <today's date, YYYY-MM-DD>
where_we_left_off: "Initial registration"
next_steps:
  - "Define project goals"
  - "Set up development environment"
key_files: []
decisions: []
```

### Step 4: Create Directory

```bash
mkdir -p data/projects
```

This directory is owned by `bumba-agent:staff` — the agent has write access.

### Step 5: Confirm

Display:
```
Project registered: <name>
Registry: data/projects/<name>.yaml
Status: active

Switch to this project with: "Switch to <name>"
View all projects with: /project/status
```

## Schema Reference

Per zone-plan.md (lines 62-71):

| Field | Type | Description |
|-------|------|-------------|
| `project` | string | Unique project identifier |
| `status` | enum | `active`, `suspended`, `deprecated` |
| `stack` | string | Technology stack summary |
| `description` | string | 1-2 sentence project description |
| `last_worked` | date | YYYY-MM-DD of last activity |
| `where_we_left_off` | string | Current state description |
| `next_steps` | list | Ordered list of next actions |
| `key_files` | list | Important file paths |
| `decisions` | list | Architectural decisions log |

## Notes

- Registry files live in `data/projects/` (agent-writable, Tier A)
- One YAML file per project
- Use `/project/config` to edit fields after registration
- Use `/project/status` to view all registered projects
