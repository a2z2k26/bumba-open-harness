---
name: new-team
description: >
  Scaffold a complete new Zone 4 department (8-12 files) in under 5 seconds.
  Interactive mode prompts for prefix, chief role/mission, and specialist roster.
  Non-interactive mode reads from a YAML config file.
  Invoke as: bumba new-team <name>
args:
  - name: name
    description: New team name in kebab-case (e.g. data-science, customer-success). Must not already exist in agent/config/teams/.
    required: true
  - name: --config
    description: Optional path to a YAML spec file for non-interactive mode.
    required: false
user-invokable: true
---

# new-team

Scaffold a complete Zone 4 department in under 5 seconds. Writes 8-12 files
atomically and aborts (exit 1) before touching anything if a name collision
is detected or input is invalid.

## Usage

### Interactive mode

```bash
python -m agent.scripts.new_team data-science
```

Prompts for:
1. Department prefix (e.g. `ds`) — used to name chief and workers
2. Department description (1-2 sentences)
3. Chief role (one sentence)
4. Chief mission (3-5 sentences)
5. Specialist roster — name + role per worker (1–8 workers)

### Non-interactive mode

```bash
python -m agent.scripts.new_team data-science --config /path/to/spec.yaml
```

YAML spec schema:

```yaml
prefix: ds
description: "Data science department. Owns ML pipelines, analytics, and predictive models."
chief_role: "Orchestrates data science work; delegates modelling, analysis, and data-eng tasks."
chief_mission: "Deliver reliable ML models and data insights that inform product decisions."
workers:
  - name: ml-engineer         # becomes ds-ml-engineer
    role: "ML model training, evaluation, deployment, and MLflow tracking"
  - name: data-analyst
    role: "SQL analysis, Looker dashboards, cohort analysis, A/B result interpretation"
```

## What gets written

| File | Purpose |
|------|---------|
| `agent/config/teams/<name>.yaml` | Full team YAML — chief + worker roster |
| `agent/config/expertise/updatable/<prefix>-chief.md` | Chief expertise stub |
| `agent/config/agents/zone4/<name>/<prefix>-chief.md` | Chief system-prompt scaffold with `{{ROSTER}}` placeholder |
| `agent/config/expertise/updatable/<prefix>-<worker>.md` | Worker expertise stub (one per specialist) |
| `agent/config/agents/zone4/<name>/<prefix>-<worker>.md` | Worker system-prompt scaffold (one per specialist) |
| `agent/data/scaffolding/<name>-team-checklist.md` | Operator fill-in checklist |

## Idempotency

The script aborts with **exit 1** if:
- `agent/config/teams/<name>.yaml` already exists
- Any target expertise or system-prompt file already exists
- Two workers share the same name

No partial writes occur — either all files are created or none are.

## Auto-discovery

`DepartmentRegistry.prewarm()` scans `agent/config/teams/*.yaml` on startup.
Dropping the generated team YAML is sufficient for the new department to be
discoverable — no manual registry update required.

## Chief system prompt — `{{ROSTER}}` placeholder

The generated chief system prompt contains a literal `{{ROSTER}}` placeholder.
`DepartmentRegistry.prewarm()` injects the live specialist list at runtime.
Do **not** remove or rename this placeholder.

## After scaffolding

1. Open `agent/data/scaffolding/<name>-team-checklist.md`
2. Complete the required fields in the team YAML (escalation triggers, domain write paths)
3. Fill in chief and worker mission paragraphs
4. Run verification:

```bash
python3 -c "import yaml; yaml.safe_load(open('agent/config/teams/<name>.yaml'))"
python3 -m pytest agent/tests/test_teams/ -m offline -v -k <name>
```

## Notes

- Default worker model is `openrouter:openai/gpt-4o-mini`. Override per-worker after profiling.
- Maximum 8 workers per scaffold call; add more later with `bumba new-specialist`.
- The generated `{{ROSTER}}` placeholder follows the same convention as existing teams.
- This skill writes *structure*, not substance. The operator owns role missions, domain paths, and expertise content.
