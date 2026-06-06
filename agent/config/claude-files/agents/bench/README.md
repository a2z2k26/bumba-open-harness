# Extended Bench Agents

This directory holds ~120 extended bench agent definitions imported from the
`your-org/Bumba-Agents` archive. These are on-demand specialists that the
Chief Engineer can deploy when the 10-member core team doesn't cover a domain.

## Import Status

**Pending** — The bumba-agents archive at `/home/operator/bumba-agents/archive/`
is not available on the agent machine. Bench agents will be imported when the
operator makes the archive accessible (via repo push or file transfer).

## Import Process

When the archive is available, run:
```bash
python3 agent/scripts/import_bench_agents.py
```

This script:
1. Reads each agent directory from the archive
2. Adapts frontmatter to bumba-open-harness format (adds `color: green`, removes `model:`)
3. Preserves body content as-is
4. Writes to this directory

## Querying Bench Agents

Once imported, agents can be discovered by:
- Filename (e.g., `rust-engineer.md`, `flutter-expert.md`)
- Grep for capabilities in agent descriptions
- The engineering team YAML config at `config/agent-tool-configs/engineering-team.yaml`
  (core team only; bench agents are registered on-demand)
