# Zone 4 Governance Bundles

This directory holds compact per-agent governance bundles for Zone 4 chiefs
and specialists.

These files are not loaded by prompt assembly yet. Z4-08 establishes the file
contract and one complete golden example. Z4-09 wires the loader.

## Layout

```text
agent/config/governance/zone4/
  <department>/
    <agent-name>/
      CLAUDE.md
      SOUL.md
      ARTIFACTS.md
```

## Roles

- `CLAUDE.md`: operational rules for the agent's work loop.
- `SOUL.md`: identity, standards, and judgment constraints.
- `ARTIFACTS.md`: rules for durable outputs, memory pointers, and blockers.

Keep every file under 120 lines. Governance is a precision layer, not another
place to pour the global prompt.
