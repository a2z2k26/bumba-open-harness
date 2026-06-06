---
name: new-skill
description: Scaffold a new Claude Code skill manifest with correct frontmatter and operator checklist
allowed-tools: Bash, Read, Write
---

# new-skill — Skill Scaffolding

Scaffold a new Claude Code skill manifest at `agent/config/skills/` in one command.
Produces a stubbed `.md` file (or directory-form `SKILL.md`) with validated frontmatter,
a body template, and an operator checklist.

## Usage

```
python3 -m scripts.new_skill <name> [--description "..."] [--directory]
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `name` | Yes | Skill name in kebab-case (e.g. `my-skill`) |
| `--description` | No | One-line description for frontmatter (default: placeholder) |
| `--directory` | No | Use directory form (`<name>/SKILL.md`) instead of standalone |

## Examples

```bash
# Standalone skill (default)
python3 -m scripts.new_skill my-skill --description "Does something useful for operators"

# Directory form (for skills with adjacent files)
python3 -m scripts.new_skill my-skill --description "Does something useful" --directory
```

## What it produces

- `agent/config/skills/<name>.md` (standalone) or `agent/config/skills/<name>/SKILL.md` (directory)
- Operator checklist printed to stdout + saved to `agent/data/scaffolding/<name>-skill-checklist.md`

## Error codes

| Exit | Cause |
|------|-------|
| 0 | Success |
| 1 | Name collision (skill already exists) |
| 1 | Frontmatter validation failure (template bug) |
