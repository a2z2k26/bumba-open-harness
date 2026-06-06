# Zone 4 Governance Bundle Schema

Each bundle directory describes one Zone 4 agent.

Required files:

- `CLAUDE.md`
- `SOUL.md`
- `ARTIFACTS.md`

Each file must:

- be UTF-8 Markdown;
- be non-empty;
- stay under 120 lines;
- be scoped to one agent;
- avoid copying global doctrine or full system prompt text.

Recommended content:

- `CLAUDE.md`: run loop, delegation policy, cost/context guardrails.
- `SOUL.md`: role identity, standards, judgment constraints.
- `ARTIFACTS.md`: when to write artifacts, what to put in memory, how to
  surface blockers.

Do not put secrets, provider credentials, browser profiles, or runtime-only
paths here unless the path is a policy reference rather than a write target.
