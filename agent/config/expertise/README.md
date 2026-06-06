# Expertise Files — Format Reference

Agent expertise files encode domain knowledge accumulated over multiple sessions. They are injected into agent system prompts at spawn time so agents build on prior experience rather than starting from zero.

## Directory Layout

```
config/expertise/
  README.md           — this file
  updatable/          — agents may write to these files
    <agent-name>.md
  read-only/          — loaded but never written by agents
    billing-rules.md
    deployment-procedures.md
    security-requirements.md
```

## File Format

Each expertise file is Markdown with a YAML frontmatter header:

```markdown
---
agent: security-auditor
zone: 4
department: qa
type: updatable        # or "read-only"
max_lines: 500
created: 2026-04-03
last_updated: 2026-04-03
schema_version: 1
---

## Domain Patterns
Recurring patterns observed in this agent's domain.

## Known Risks
Risks encountered; keep brief, update as new ones surface.

## Decision Log
Key decisions made and rationale.

## Cross-Agent Notes
Information useful for other agents or the chief.
```

## Rules

- All four `##` sections are required. Missing sections cause a validation error.
- `max_lines` defaults to 500 if omitted. Over-limit files load with a warning.
- `type: read-only` files are loaded into context but agents must not write them.
- `schema_version: 1` is the current version.
- Missing files return `None` (first session — not an error).
- Malformed files raise `ValueError` and block agent spawn.

## Loading

Expertise injection is performed by `_load_expertise(spec: AgentSpec) -> str` in
[`agent/teams/_factory.py`](../../teams/_factory.py). It is called from
`build_manager_agent` during agent construction (chief + specialist tiers); the
returned string is appended to the agent's system prompt under an `## Expertise`
heading. The legacy pre-pydantic-ai `bridge/expertise_loader.py` module was
deprecated as part of the Zone 4 skeleton cleanup (see
`docs/system-audit-2026-04-11-factcheck.md` §Z4.5) and is no longer the loader.

Behaviour:

- `AgentSpec.expertise_path` is captured from the team YAML at config-load time;
  if absent or empty, `_load_expertise` returns `""` and no expertise is injected.
- Missing files log a warning and return `""` — expertise is enhancement, not
  requirement. The agent still spawns.
- Non-empty content is wrapped: `f"## Expertise\n\n{content}"`.

```python
# In agent/teams/_factory.py (called from build_manager_agent):
expertise = _load_expertise(spec)
# expertise is "" or "## Expertise\n\n<file contents>"
```

## Creating a New File

Author the file directly in `config/expertise/updatable/` (or `read-only/` for
agents that should not write back). Use the frontmatter + four-section template
above. Then set `expertise_path` in the agent's team YAML to point at the new
file — `AgentSpec.expertise_path` is what `_load_expertise` reads.
