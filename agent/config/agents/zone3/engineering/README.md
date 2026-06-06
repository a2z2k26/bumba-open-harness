# Zone 3 engineering agent definitions

Canonical agent prompt files live at
`agent/config/claude-files/agents/engineering-*.md` (resolved by the Zone 3
config at `agent/config/zone3/engineering.yaml` and by the SubagentExecutor
prompt resolver).

Zone 3 engineering **governance bundles** (CLAUDE.md / SOUL.md / ARTIFACTS.md
per agent) live at `agent/config/governance/zone3/engineering/<agent-name>/`
and are loaded by `agent/zone3/engineering_prompts.py`.

This directory is the owned-path anchor declared by sprint Z3-04
(`plan:2026-05-21-team-operability`). It intentionally does not duplicate the
prompt or governance content above; it points at the single sources of truth to
prevent drift.
