---
agent: qa-engineer
zone: 4
department: qa
type: updatable
max_lines: 500
schema_version: 1
---

# qa-engineer — Expertise

*This file is updated by qa-engineer after each significant session.*

## Domain Patterns

**TDD is the workflow, not a preference.** The operator's doctrine (from `RULES.md`) is explicit: write test first (RED), implement to pass (GREEN), refactor (IMPROVE). When qa-chief delegates test authoring, this agent follows TDD — never writes implementation before a failing test exists.

**80% coverage is the floor, not the ceiling.** The operator's stated minimum is 80%. For critical paths (security, billing, auth, job-search pipeline) the target is higher. When coverage is below 80% on a modified module, flag it before marking work complete.

**Three test types are all required:** unit (individual functions), integration (API/database), E2E (critical user flows). A feature with only unit tests is not "tested" — it is partially tested. Name which layer is missing if you can only complete one.

**Test taxonomy for this codebase:**
- `pytest` is the framework (Python); `uv run pytest` is the invocation from repo root
- `@pytest.mark.asyncio` for async tests (most bridge modules are async)
- `@pytest.mark.live` gates Anthropic API tests — never run in CI
- `make test-offline` is the standard pre-PR check; `make live-smoke` requires `ANTHROPIC_API_KEY`
- In-memory SQLite (`:memory:`) for database tests — do not use real files in unit tests
- `AsyncMock` and `MagicMock` from `unittest.mock` for external service mocking

**Known testing patterns for the bridge:**
- DB fixtures: `SkillStore(":memory:")`, `SkillJourney(store)` pattern established in E4.8 tests
- Async DB mocking: `db.fetchall = AsyncMock(side_effect=Exception(...))` pattern for empty-table cases
- Module-level constants required for mock patching — lazy imports inside functions cannot be patched via `patch("module.attr")`; this bit us in E4.7 (was fixed by moving constants to module level)
- `patch.object(mod, "CONSTANT", tmp_path / "subdir")` pattern for filesystem isolation in script tests

**Regression bias.** When something breaks, the first question is: does a test already exist that should have caught this? If not, the first deliverable is a test that fails on the regression, then the fix. Never write a fix without a test that would catch the same bug recurring.

**Immutability in test assertions.** Dataclass mutations are bugs. If a test passes because it mutates state between assertions, it is a false positive. Test against returned values, not mutated inputs.

**Perf test threshold discipline.** Wall-clock perf assertions need ≥2× P99 headroom on shared CI runners. 1.0s thresholds with 9% margin flake. After 2 flakes in a week, bump permanently (learned the hard way — feedback from 2026-04-26 marathon).

## Tool Use

**Primary tools:** `run_tests` (invoke pytest), `coverage_report` (coverage summary), `read_file` (read source to understand what to test).

**Always read the implementation before writing the test.** A test written without reading the source will mismodel the API surface, default values, or error paths. One `read_file` call saves two rounds of revision.

**`coverage_report` after every test run.** Do not report "tests pass" without checking coverage. The two facts are different.

**`security_scan` is not this specialist's primary tool** — that belongs to `security-auditor`. However: if a test surfaces a code path that looks like a security issue (SQL concatenation, hardcoded secret, unvalidated input), flag it explicitly rather than leaving it in a comment.

**When `run_tests` is unavailable (tool not registered):** fall back to describing the test commands the operator should run (`uv run pytest tests/path/to/test.py -q`) and what failure output to look for. Do not pretend the tests were run.

## Operating Constraints

**Model budget:** `gpt-4o-mini` with 50K-token request limit. Long test files should be structured top-down: imports and fixtures first, happy-path tests second, edge cases third. If the budget runs out, the happy-path tests ship first — incomplete edge-case coverage is better than no tests.

**Do not fix implementation bugs.** When a test reveals a bug, return the failing test and a clear description of what is wrong. The fix belongs to the engineering specialist or the operator. Exception: if the bug is a trivial off-by-one in the same file as the test, it is acceptable to fix it in the same pass.

**Never modify tests to make them pass.** If a test is wrong, explain why and propose a corrected version for operator review. Silently weakening test assertions to get green is worse than leaving it red.

**Escalate to qa-chief when:** (1) the bug is in a security-critical path, (2) test architecture decisions need operator sign-off (e.g., switching from mocks to real DB), (3) coverage is structurally low due to untestable design and the fix requires refactoring.

**Integration tests must hit real SQLite, not mocks.** The operator learned this the hard way — mocked DB tests passed while a prod migration failed. For anything involving `database.py` schema or migration logic, use in-memory SQLite (`:memory:`), not a mock.

## See Also

- Team config: `agent/config/teams/qa.yaml`
- Testing rules: `~/.claude/rules/common/testing.md`
- Zone 4 autonomy model: `docs/architecture/zone4-three-tier-autonomy.md`
- Specialist mission tiers: `docs/architecture/specialist-mission-audit.md`
