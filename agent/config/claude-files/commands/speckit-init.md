---
description: Initialize a new Spec-Kit SDD project with Bumba integration
allowed-tools: Read, Write, Bash, AskUserQuestion
---

# /speckit-init — Initialize Spec-Kit Project

Set up a new project using Specification-Driven Development (SDD) via GitHub Spec-Kit.

## Usage

```
/speckit-init <project-name> [directory]
```

If `$ARGUMENTS` is empty, ask the user for a project name.

## Steps

### 1. Determine Project Directory

- If a directory is provided in `$ARGUMENTS`, use it
- If only a name is provided, create `~/projects/<name>/` (or ask user for preferred location)
- If directory already exists and contains `.specify/`, warn: project already initialized

### 2. Initialize Spec-Kit

```bash
cd <project-dir>
~/.local/bin/specify init <name> --ai claude --here
```

If `GH_TOKEN` is available (check `~/.secrets` or environment), export it first for higher GitHub API rate limits.

### 3. Verify Initialization

Confirm these were created:
- `.specify/config.yaml`
- `.claude/commands/speckit.constitution.md`
- `.claude/commands/speckit.specify.md`

If missing, report the error and stop.

### 4. Prompt for Constitution

Tell the user:
> Project initialized. Run `/speckit.constitution` next to define your project's governing principles, standards, and constraints.

### 5. Create Zone 3 Project Registry

Create a memory file for this project:

**Path:** `~/.claude/projects/*/memory/projects/<name>.md`

**Content:**
```markdown
# Project: <name>

- **Status:** active
- **Stack:** [ask or detect]
- **Created:** <date>
- **SDD:** initialized (constitution pending)
- **Directory:** <path>
- **Description:** [ask user for 1-2 sentences]

## Where We Left Off
Project initialized with Spec-Kit. Constitution not yet written.

## Next Steps
1. Run `/speckit.constitution` to define project principles
2. Create first specification with `/speckit.specify`

## Decisions
- Using SDD methodology via Spec-Kit
```

### 6. Report Success

Output summary:
- Project directory path
- Files created by Spec-Kit
- Next step: `/speckit.constitution`
- Reminder: The 9 `/speckit.*` commands only work inside this project directory
