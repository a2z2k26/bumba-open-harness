---
name: scaffold-zone4
description: Scaffold a Zone 4 department in one command — single-agent, chief-specialist, or agent-team
allowed-tools: Bash, Read, Write
---

# scaffold-zone4 — Zone 4 Department Scaffolding

Scaffold a complete Zone 4 department in under 5 seconds with one command.
Dispatches to the correct bundle family based on `<kind>`.

## Usage

```
python3 -m scripts.scaffold_zone4 <kind> <name> [--config YAML]
```

Or via the bumba skill runner:

```
/bumba:scaffold-zone4 <kind> <name>
```

## Kinds

| Kind | Files | When to use |
|------|-------|-------------|
| `single-agent` | 3 | One agent handles all tasks — no delegation needed |
| `chief-specialist` | 5 | Chief coordinates one named specialist |
| `agent-team` | N+3 | Full team with chief + N workers (interactive or `--config`) |

## Examples

### Single agent (solo)

```bash
python3 -m scripts.scaffold_zone4 single-agent prompt-archaeologist
```

Produces:
- `agent/config/expertise/updatable/prompt-archaeologist.md`
- `agent/config/agents/zone4/prompt-archaeologist/prompt-archaeologist.md`
- `agent/config/teams/prompt-archaeologist.yaml` (chief = worker, no delegation)

### Chief + one specialist

```bash
python3 -m scripts.scaffold_zone4 chief-specialist qa-lite
```

Produces (5 files):
- `agent/config/expertise/updatable/qa-lite-chief.md`
- `agent/config/agents/zone4/qa-lite/qa-lite-chief.md`
- `agent/config/expertise/updatable/qa-lite-specialist.md`
- `agent/config/agents/zone4/qa-lite/qa-lite-specialist.md`
- `agent/config/teams/qa-lite.yaml`

### Full team (interactive)

```bash
python3 -m scripts.scaffold_zone4 agent-team observability
```

Starts the interactive `bumba new-team` wizard. Press Ctrl-C to abort.

### Full team (non-interactive via config file)

```bash
python3 -m scripts.scaffold_zone4 agent-team observability --config /tmp/obs-spec.yaml
```

Config YAML format (passed to `new_team.py`):

```yaml
prefix: obs
description: Observability and monitoring department.
chief_role: Leads observability initiatives.
chief_mission: Ensure the system is always observable.
workers:
  - name: metrics-collector
    role: Collects and aggregates runtime metrics.
  - name: alert-router
    role: Routes alerts to the right channels.
```

## Post-scaffold steps

1. Open the generated files and fill in all `<!-- ... REQUIRED ... -->` placeholders.
2. Run `DepartmentRegistry().team("<name>")` to verify discovery (or check the scaffold output).
3. Add routing keywords to `bridge/departments.py` if you want the team reachable by keyword.
4. Run `make test-offline` to confirm the placeholder test passes.

## Error codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Validation failure (bad kind, collision, name format, discovery failure) |
| 2 | Unexpected I/O error |

## Companion tools (D7.13 #1425)

The scaffold-zone4 surface is paired with three frictionless-setup helpers:

- **Golden-path template:** `agent/config/teams/_template.yaml` — the
  single canonical input documenting every required and optional field
  with one-line comments. The `_` prefix means `DepartmentRegistry`
  skips it during discovery, so it ships in the teams dir without
  becoming a runnable team.
- **Validator:** `python -m scripts.validate_team_yaml <name>` —
  schema check (delegating to `teams._config.load_department_config`)
  plus cross-reference checks (per-employee tool keys, expertise/
  system_prompt path existence). Pass `--strict` to promote
  missing-file warnings to errors. `--all` validates every team.
- **Doctor:** `python -m scripts.scaffold_doctor <name>` — diagnoses
  first-run readiness. Wraps the validator in `--strict` mode, diffs
  the team against the golden template's required field set, and
  emits actionable shell fix commands for each gap.

Operator one-shot — chains scaffold + validate + pytest:

```bash
make new-team NAME=<kebab-case-name>
```

Reaches green from a cold scaffold in under 4 seconds for an empty new
team. The make target is the operator-facing wrapper; the underlying
Python scripts remain composable building blocks.
