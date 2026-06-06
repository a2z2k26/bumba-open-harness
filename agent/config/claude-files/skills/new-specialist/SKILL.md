---
name: new-specialist
description: >
  Scaffold a new Zone 4 specialist (expertise stub, system-prompt scaffold,
  team YAML worker block, placeholder test, fill-in checklist) in under 3 seconds.
  Invoke as: bumba new-specialist <team> <name>
args:
  - name: team
    description: Existing team name (e.g. design, qa, engineering). Must match a file in agent/config/teams/<team>.yaml.
    required: true
  - name: name
    description: New specialist name in kebab-case (e.g. rust-specialist, api-tester-senior).
    required: true
user-invokable: true
---

# new-specialist

Scaffold a new Zone 4 specialist in under 3 seconds. Writes 5 files atomically
and aborts (exit 1) before touching anything if a name collision is detected.

## Usage

```
bumba new-specialist <team> <name>
```

**Example:**

```bash
python -m agent.scripts.new_specialist design motion-designer
# or via Make:
make new-specialist team=design name=motion-designer
```

## What gets written

| File | Purpose |
|------|---------|
| `agent/config/expertise/updatable/<name>.md` | Expertise stub with single `## Domain Patterns` header |
| `agent/config/agents/zone4/<team>/<name>.md` | System-prompt scaffold with mission placeholder |
| `agent/config/teams/<team>.yaml` | Worker block appended under `workers:` |
| `agent/tests/test_teams/test_specialist_<name>.py` | Offline construction smoke test |
| `agent/data/scaffolding/<name>-checklist.md` | Operator fill-in checklist (saved for later reference) |

## Idempotency

The script aborts with **exit 1** if any target file already exists OR if the
`<name>` worker entry is already present in `<team>.yaml`. No partial writes
occur — either all 5 files are created or none are.

## After scaffolding

Open `agent/data/scaffolding/<name>-checklist.md` and complete the three
required fields:

1. `role:` in the team YAML worker block
2. `domain.write:` paths (narrow to what this specialist actually writes)
3. Mission paragraph in the system-prompt stub

Then run the offline smoke test to confirm wiring:

```bash
python -m pytest agent/tests/test_teams/test_specialist_<name>.py -m offline -v
```

## Notes

- Default model is `openrouter:openai/gpt-4o-mini`. Override in the worker
  block if this specialist warrants Sonnet or Opus.
- `per_employee_tools: {}` is intentionally left empty; narrow after first use.
- This skill writes *structure*, not substance. The operator owns role, mission,
  domain write paths, and domain expertise.
- The generated expertise stub deliberately has **one** `## Domain Patterns`
  header (fixes the duplicate-header bug from A4 §"Structural problems #1").
