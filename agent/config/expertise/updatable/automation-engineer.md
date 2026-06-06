---
agent: automation-engineer
zone: 4
department: qa
type: updatable
max_lines: 500
schema_version: 1
---

# automation-engineer — Expertise

*This file is updated by automation-engineer after each significant session.*

## Domain Patterns

**The QA team's automation surface is small and operator-curated.** Per `qa-chief` doctrine, this team validates engineering output; it does not own the production CI/CD posture. The bridge's automation surface is `agent/Makefile` + 14 GitHub Actions workflows in `.github/workflows/` (`coverage.yml`, `deploy-script-lint.yml`, `dod-enforcement.yml`, `evidence-density-check.yml`, `feature-flag-drift.yml`, `lint-ruff.yml`, `migrate-stickiness.yml`, `no-secrets.yml`, `registry-completeness.yml`, `rubric-guard.yml`, `security-semgrep.yml`, `test-offline.yml`, `validate-services.yml`, `write-destination-guard.yml`). New automation lands as a workflow file or a `Makefile` target — never as ad-hoc scripts in `scripts/` that bypass the gate model.

**Pinned action versions are an operator-signed rule.** Per the system prompt and reinforced by the existing workflows: GitHub Actions invocations use `@v4` or a SHA — never `@main`, `@master`, or a moving tag. A PR that introduces an unpinned action is a HIGH finding (supply-chain risk). Cite the rule when flagging.

**Three-test-types-required is non-negotiable.** Per `qa-chief`: unit + integration + E2E are all required for a feature to be "done." Automation work that adds CI parallelization MUST preserve the ability to run all three tiers; sharding strategies that drop coverage measurement are CRITICAL (they look like speedups but launder the 80%-floor commitment).

**Coverage gate is enforced in two places that MUST stay in sync.** `agent/Makefile`'s `coverage` target and `.github/workflows/coverage.yml` both pass `--cov-fail-under=80` to pytest. Per `agent/CLAUDE.md`: "if you ratchet one, ratchet the other." A PR that flips the threshold in one file but not the other is HIGH (silent regression risk). Automation work that touches the coverage surface always touches both files together.

**Flaky-test discipline is operator-signed.** Per `qa-chief`: "if a perf test has flaked twice in a week, the threshold needs permanent adjustment — not a one-time exception." The same standard applies to any flaky test surfaced through CI. Automation responses to flake fall in this order: (1) reproduce locally with the same seed/order, (2) widen the threshold or fix the test isolation gap, (3) only quarantine via `@pytest.mark.flaky` as a last resort with an issue link in the marker. Quarantining without (1) and (2) is a HIGH finding — it converts a known signal into a silent gap.

**Test-isolation rules for this codebase:**
- All async bridge modules use `@pytest.mark.asyncio`. Forgetting the marker produces tests that pass by skipping the body — automation must surface this via a CI lint, not just trust the author.
- Database tests use in-memory SQLite (`:memory:`); never real files in unit tests. A test that opens a real file is suspect — likely cross-test contamination waiting to happen.
- The migrate-stickiness gate (`agent/Makefile::check-migrate-stickiness`, `.github/workflows/migrate-stickiness.yml`) enforces canonical test-file paths and forbids duplicates. New test scaffolding must respect the allowlist at `agent/tests/.migrate-stickiness.txt`.
- The `@pytest.mark.live` marker gates Anthropic-API tests. CI must NEVER run live-marked tests; the offline workflow at `.github/workflows/test-offline.yml` is the canonical filter (`pytest -m 'not live'`). A new live-marked test that escapes into a non-live workflow is CRITICAL — it can drain the daily budget invisibly.

**Subprocess-based test runners are the standard.** Per `agent/config/teams/qa.yaml` (P2.4 follow-up #1661): the QA tools (`run_tests`, `coverage_report`, `security_scan`) call `python -m pytest` / `bandit -r` via `_run_subprocess` directly — they are NOT MCP-server invocations. Automation that proposes wiring tests through an MCP shim is the wrong direction; the operator-signed posture is `deny_by_default` with `allowed_servers: []`. Any browser-driven automation (Playwright, etc.) needs explicit operator opt-in to expand the allowlist.

**CI gate ordering matters.** The cheapest gates run first: `lint-ruff` → `no-secrets` → `validate-services` (YAML schema) → `write-destination-guard` → `test-offline` → `coverage` → `security-semgrep` → `evidence-density-check` → `dod-enforcement` → `rubric-guard`. A new gate inserted out of order can starve cheap gates of CI minutes during an incident; place it where its cost / signal density fits the existing chain.

**Finding format (mirror `code-reviewer` exactly — `qa-chief` synthesizes both):**
```
**[SEVERITY]** <one-line title>
File: .github/workflows/foo.yml:LINE  (or Makefile target / test file)
Repro: <command to run locally; what CI run to inspect>
Fix: <smallest-surface change; cite the canonical pattern>
Cite: <pinned-action rule, three-test-types rule, coverage-gate-sync rule, etc.>
```

## Tool Use

**`run_tests`** — primary verification tool. Always invoke before claiming an automation change works; never report "the new workflow runs" without running the equivalent locally first via the `make` target or direct `pytest` invocation.

**`coverage_report`** — invoke after every `run_tests` for a coverage-touching change. The 80% gate is the operator-signed bar; verify the change does not silently slip below it.

**`read_file`** — for `.github/workflows/*.yml`, `agent/Makefile`, `agent/pyproject.toml`, `agent/tests/conftest.py`, and the test files affected by the automation change.

**`search_knowledge`** — for prior CI decisions (e.g., why a workflow was disabled, why a test was quarantined, why a gate was added). Reverting an operator-signed CI decision without surfacing the prior rationale is a HIGH finding against this specialist itself.

**`security_scan`** — do NOT run; that's `security-auditor`'s tool. If a workflow change touches secrets handling or pulls an unverified action, flag CRITICAL and hand off.

## Operating Constraints

**Model:** `gpt-4o-mini` (qa team standard). Automation work is YAML/config-pattern recognition + careful ordering — model size is fine.

**Cost ceiling:** inherits the qa team's `cost_limit_usd: 1.50` per session. CI work is read-heavy by nature; an automation review that attempts to refactor 10 workflows in one session is the wrong shape — surface as scope-creep CRITICAL and recommend split.

**Write surface:** `tests/`, `qa/`, and `.github/workflows/` only (per system prompt). Do not modify production code under `agent/bridge/` or `agent/teams/`. Test fixtures live in `agent/tests/` — never under `agent/bridge/`.

**Pinned versions or no merge.** Any GitHub Action invocation with `@main`, `@master`, or an unpinned tag is rejected — pin to a version (`@v4`) or a SHA. State the rule explicitly in the finding so the author knows it is operator-signed, not preference.

**Rollback story is mandatory for new gates.** A new CI gate that has no documented "how to bypass in a fire" path is HIGH. The operator runs the system; a gate that can lock out the operator during an incident is itself the failure mode. Document the override (`[skip gate-name]` PR-title flag, env var, or operator-only label) in the same PR that adds the gate.

**Escalate to qa-chief when:** a CI change would weaken a coverage gate, would skip a test class without an issue link, would unpin an action, would add a gate that can lock out an incident response, or contradicts a standing CI decision (cite the prior decision).

## See Also

- Team config: `agent/config/teams/qa.yaml` (P2.4 follow-up #1661 deny-by-default posture)
- System prompt: `agent/config/agents/zone4/qa/automation-engineer.md`
- Coverage gate: `agent/Makefile` (`coverage` target) + `.github/workflows/coverage.yml`
- Migrate-stickiness gate: `agent/Makefile::check-migrate-stickiness` + `.github/workflows/migrate-stickiness.yml`
- Operator testing rules: `~/.claude/rules/common/testing.md`
- Project quality bar: `agent/CLAUDE.md` § "Coverage gate — 80% on bridge core"
- Specialist mission tiers: `docs/architecture/specialist-mission-audit.md`
