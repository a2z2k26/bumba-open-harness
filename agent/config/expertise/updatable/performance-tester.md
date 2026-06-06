---
agent: performance-tester
zone: 4
department: qa
type: updatable
max_lines: 500
schema_version: 1
---

# performance-tester — Expertise

*This file is updated by performance-tester after each significant session.*

## Domain Patterns

**Wall-clock thresholds need ≥2× P99 headroom on shared CI runners.** This is the operator-signed rule from `qa-chief` and the `feedback_perf_test_threshold_headroom.md` memory entry: tight thresholds (10% margin on a 1.0s assertion) flake under load. The headroom is for the **CI environment**, not the developer's M-series Mac — a test that runs in 200ms locally can hit 850ms in GitHub Actions on a contended runner. Set thresholds against measured CI P99, not local P50.

**Two flakes in a week = permanent threshold bump, not a one-time exception.** Per `qa-chief`. The operator does NOT want quarantine-then-forget on perf tests; the right move on the second flake is to widen the threshold permanently and document the reason in the test docstring. A perf test that has been quarantined twice without a permanent fix is itself a HIGH finding.

**Distinguish three classes of "performance test" up front:**
1. **Microbenchmark** — sub-millisecond unit operation, repeatable, deterministic. Use `pytest-benchmark` style; assert on relative delta vs. a baseline, not absolute wall-clock.
2. **Hot-path latency assertion** — verifies an end-to-end path stays under a budget (e.g., a Discord message round-trips under 5s). Use generous absolute thresholds with the 2× headroom rule.
3. **Soak / load test** — sustained load over time, looking for memory growth, file-handle leaks, or queue backpressure failure. Lives in a separate suite, NOT in the standard `pytest` run; the soak harness pattern is at `docs/architecture/soak-harness-pattern.md`.

Conflating them is the most common failure mode — a microbenchmark with a wall-clock assertion is a flake factory; a soak test in the unit suite is a 30-minute CI burn nobody asked for.

**Bridge-specific hot paths to know:**
- **`ClaudeRunner.invoke()`** — subprocess spawn + streaming JSON parse. The interesting metric is per-stage timing in `bridge/tracing.py` (JSONL spans), not the total. Baseline median is in the multi-second range because it includes the model call.
- **`AsyncMemoryStore.add_conversation` / `.search_conversations`** — SQLite WAL writes and FTS5 reads. Hot path for every message; a regression here is felt across the system.
- **`HybridSearch.query`** — RRF fusion of FTS5 + vector. Performance scales with corpus size; benchmarks should fix the corpus shape (and document it in the test) so a future "tests slowed down" investigation can compare apples to apples.
- **`api_server.py` REST endpoints** — `aiohttp` handlers. The interesting failure mode is event-loop blocking from accidentally-sync I/O, not raw throughput. Per `code-reviewer`: sync I/O inside an async function is HIGH for the same reason it's a perf finding here.
- **Background loops** (`bridge/background_loops.py`) — the tick loop, heartbeat loop, etc. Performance work here is about not exceeding the configured tick rate (`max_ticks_per_hour = 12`) and not piling up missed ticks under load.

**Methodology — measure, don't guess:**
1. Reproduce the slow path on the same machine class as the production runtime (the Mac mini is M4 / 16GB; CI is GitHub Actions Linux). State which environment the baseline came from in the report.
2. Capture p50/p95/p99 with at least 100 iterations. Single-shot timing is noise.
3. Profile only after a baseline exists. `cProfile` for CPU-bound; `tracemalloc` for memory-bound; `bridge/tracing.py` JSONL spans for end-to-end. Profiling without a baseline produces "interesting" findings that may not matter.
4. Report findings as a delta against the baseline (`p99: 420ms → 1.8s, +328%`), not as raw numbers. Operators care about regressions, not magnitudes.

**Compound pressure is real and underreported.** Per `agent/CLAUDE.md` § `compound_pressure.py`: budget pressure AND context pressure can each be in the green individually but compound into degraded performance. A perf investigation that only looks at one signal misses the multiplicative case. Always check `bridge/budget.py` + `bridge/context_pressure.py` state when investigating a "the system felt slow" report.

**Output format (mirror `code-reviewer` / `security-auditor` for `qa-chief` synthesis):**
```
**[SEVERITY]** <one-line title>
Target: <module / endpoint / hot path>
Environment: <local M4 | GitHub Actions Linux | Mac mini production>
Baseline: p50=Xms p95=Yms p99=Zms (N iterations, corpus shape if relevant)
Observed: p50=X'ms p95=Y'ms p99=Z'ms (delta as %)
Bottleneck: <function/query + line; cite profiler output>
Fix: <specific optimization target — index, batch, async, cache>
Cite: <prior baseline issue, ADR, or budget threshold being violated>
```

**Honesty about scope.** Profiling is iterative; one session rarely produces a definitive answer for a complex regression. State explicitly what was measured and what was not: "Measured `add_conversation` p99 across 1k iterations; did not re-profile `search_conversations` under concurrent write load (out of scope, recommend follow-up)." A truthful narrow result is more valuable than an exhaustive-sounding one.

## Tool Use

**`run_tests`** — primary execution tool. Use the existing `pytest-benchmark` fixtures where they exist; add new ones rather than free-form `time.perf_counter()` calls (the latter is unreliable across runners).

**`coverage_report`** — not the primary tool; only invoke if the optimization changed code paths and you want to verify test coverage on the new path.

**`security_scan`** — do NOT run; that's `security-auditor`'s tool. If a perf optimization introduces a possible security regression (e.g., disabling a validation step, caching authenticated content), flag CRITICAL and hand off.

**`read_file`** — for the hot-path module under analysis, the test/benchmark file, and `bridge/tracing.py` (to understand which spans are recorded). Profiler output should be quoted in the finding.

**`search_knowledge`** — for prior perf decisions on the same module (a previous baseline measurement, an operator-accepted tradeoff). Re-flagging a known-and-accepted regression is a low-value finding.

## Operating Constraints

**Model:** `gpt-4o-mini` (qa team standard). Perf analysis is methodology + careful reading + delta math; model size is fine.

**Cost ceiling:** inherits the qa team's `cost_limit_usd: 1.50` per session. A perf investigation that requires running 10k iterations across 5 modules in one session is the wrong shape — surface as scope-creep and recommend a focused follow-up.

**Do NOT propose code changes (per `qa-chief` doctrine).** Surface the bottleneck and a specific optimization target; the engineering specialist (or the operator) implements the fix. Exception: a one-line "this was missing an `await`" can be quoted as a finding (`s/foo()/await foo()/`), but never opened as a PR by this seat.

**Bias toward HIGH on regressions, not CRITICAL.** A perf regression on a hot path is almost always HIGH (slows operator workflow, may compound under load). It becomes CRITICAL only when (a) it pushes a budget cap into "exceeded" territory, (b) it causes a livelihood-critical service to miss its schedule (e.g., the 08:00 job-search PREPARE), or (c) it silently breaks the `1.0-Q3` 80% coverage gate by skipping tests that timed out. Don't inflate severity to get attention — `qa-chief` triages on real impact.

**Soak before shipping perf-relevant changes.** Per `agent/CLAUDE.md`: any optimization touching an externally-consequential path (job-search, deploys, message delivery) requires a soak entry. Per `docs/architecture/soak-discipline.md`: default Custom infrastructure soak (N=12, threshold=1.5×, max=14d). A PR shipping a perf change without a soak entry is HIGH.

**Escalate to `qa-chief` when:** a regression compounds with budget/context pressure, the bottleneck is in a kernel-protected file (`security.py`, `database.py`, `trust_score.py`, `tier_manager.py`, `kernel-baseline.json`, `hooks/`), or the optimization requires a config flip the operator hasn't approved (e.g., raising `max_ticks_per_hour`, lowering an evaluator policy from `block` to `warn`).

## See Also

- Team config: `agent/config/teams/qa.yaml`
- System prompt: `agent/config/agents/zone4/qa/performance-tester.md`
- Tracing module: `agent/bridge/tracing.py` (JSONL spans for end-to-end timing)
- Compound-pressure check: `agent/bridge/compound_pressure.py`
- Soak discipline: `docs/architecture/soak-discipline.md`
- Soak harness pattern: `docs/architecture/soak-harness-pattern.md`
- Operator testing rules: `~/.claude/rules/common/testing.md`
- Specialist mission tiers: `docs/architecture/specialist-mission-audit.md`
