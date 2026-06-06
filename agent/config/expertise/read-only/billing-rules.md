---
agent: billing-rules
zone: 4
department: operations
type: read-only
max_lines: 500
created: 2026-04-03
last_updated: 2026-04-03
schema_version: 1
---

## Domain Patterns

- Daily budget enforcement: hard limit enforced by `budget.py`; agents must check budget before spawning sub-agents
- Model tiers: Haiku (~$0.002/1K tokens input), Sonnet (~$0.015), Opus (~$0.075) — route by complexity, not habit
- Cost attribution: every Claude invocation must carry a `session_id` so costs can be tracked per session
- Batch work: consolidate multiple small tasks into single larger invocations to reduce per-call overhead

## Known Risks

- Unbounded loops: agents that retry without a turn cap can exhaust the daily budget in minutes
- Opus by default: defaulting to Opus for all tasks is a budget anti-pattern — use it only for architecture/strategy
- Missing budget check: spawning sub-agents without checking `budget.py` state can cause mid-session halts

## Decision Log

- 2026-04-03: Daily budget cap set at $2/day for experiment loop, separate from bridge operational budget
- 2026-04-03: Cost tracker logs per-model USD with daily and weekly rollups (`cost_tracker.py`)

## Cross-Agent Notes

- Always check `BudgetManager.check()` before spawning additional agents
- Report estimated cost in delegation results so the chief can track spend
- If budget is at >80%, prefer Haiku unless the task explicitly requires reasoning depth
