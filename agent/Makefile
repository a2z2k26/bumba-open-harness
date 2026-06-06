.PHONY: check-migrate-stickiness

# Sprint 08.13 — migrate-stickiness gate (Issue #791).
# Mirrors .github/workflows/migrate-stickiness.yml for local pre-flight.
# Runs from agent/, so paths in the allowlist (relative to repo root) are
# resolved by prepending "../".
check-migrate-stickiness:
	@bash -c 'set -e; \
	missing=0; dupes_found=0; \
	while IFS= read -r path; do \
	  [ -z "$$path" ] && continue; \
	  case "$$path" in \#*) continue ;; esac; \
	  if [ ! -f "../$$path" ]; then \
	    echo "MISSING: $$path"; \
	    missing=$$((missing + 1)); \
	    continue; \
	  fi; \
	  basename=$$(basename "$$path"); \
	  dupes=$$(find .. -name "$$basename" \
	    -not -path "../$$path" \
	    -not -path "*/.git/*" \
	    -not -path "*/.venv/*" \
	    -not -path "*/.claude/*" \
	    -not -path "*/__pycache__/*" \
	    -not -path "*/node_modules/*" \
	    2>/dev/null || true); \
	  if [ -n "$$dupes" ]; then \
	    echo "DUPLICATE of $$basename:"; \
	    echo "$$dupes"; \
	    dupes_found=$$((dupes_found + 1)); \
	  fi; \
	done < tests/.migrate-stickiness.txt; \
	if [ "$$missing" -gt 0 ] || [ "$$dupes_found" -gt 0 ]; then \
	  echo "FAIL: $$missing missing, $$dupes_found duplicates."; \
	  exit 1; \
	fi; \
	echo "OK: all canonical test paths present and unique."'

.PHONY: dod-check
# Sprint 08.12 — locally invoke the DoD-enforcement check for one issue.
# Usage: make dod-check ISSUE=<N>
# Mirrors .github/workflows/dod-enforcement.yml — see
# ../docs/testing/dod-enforcement.md for the rationale and override path.
dod-check:
	@if [ -z "$(ISSUE)" ]; then echo "Usage: make dod-check ISSUE=<N>"; exit 2; fi
	python3 ../scripts/dod_check.py --issue $(ISSUE)

.PHONY: coverage
# 1.0-Q3 (#1111) — bridge-core coverage gate.
#
# Threshold MUST stay in sync with .github/workflows/coverage.yml
# (--cov-fail-under flag). If you ratchet it here, ratchet there too.
# Behavior-critical-module coverage notes: docs/testing/coverage-map.md.
#
# Sprint R3.1 (#1897): includes `job_search/tests/` to match the CI workflow
# exactly. Without those tests, modules like `job_search.tools.scoring`
# report 0% coverage despite being fully tested in `job_search/tests/`,
# and the total drops below 80% — i.e. the local pre-flight disagrees with
# CI. The two commands MUST stay identical except for environment-specific
# paths.
#
# `--deselect tests/test_integration_performance.py` mirrors the CI workflow:
# pytest-cov instrumentation adds 10-30% overhead which pushes the wall-clock
# perf budgets (e.g. test_pipeline_1000_rows_under_2s, 2s) over the cliff.
# Those tests still run in test-offline.yml without instrumentation.
coverage:
	python3 -m pytest tests/ job_search/tests/ -m "not live and not perf" \
		--deselect tests/test_integration_performance.py \
		--cov=bridge --cov=teams --cov=job_search \
		--cov-report=html --cov-report=term-missing \
		--cov-fail-under=80
	@echo "HTML report at agent/htmlcov/index.html"

.PHONY: lint-types
# Sprint 02.07a — mypy config + dev dep added (issue #981).
# Runs mypy against the bridge package using the venv at the repo root.
# Lenient config (strict=false, ignore_missing_imports=true); 02.07b
# wires this into the experiment-loop quality gate.
lint-types:
	cd agent && .venv/bin/python -m mypy bridge/

.PHONY: check-mypy-baseline
# Sprint S3.1 (#2340) — mypy baseline ratchet.
# Fails on net-new mypy errors against agent/mypy-baseline.txt; passes
# when errors only stay flat or decrease. Refresh the baseline after
# intentional debt burndown with `--update-baseline`.
# Policy doc: docs/testing/type-checking.md.
check-mypy-baseline:
	.venv/bin/python scripts/check_mypy_baseline.py

.PHONY: check-resource-warning-baseline
# Sprint S6.1 (#2351) — ResourceWarning baseline ratchet.
# Same shape as check-mypy-baseline, different signal: runs the offline
# pytest lane with -W default::ResourceWarning, normalizes the resulting
# warning set (memory addresses + pytest tmp paths stripped), and fails
# on net-new entries against agent/resource-warning-baseline.txt.
# Refresh after intentional debt burndown (target sprint: S6.2) via
# `--update-baseline`.
# Policy doc: docs/testing/resource-warnings.md.
check-resource-warning-baseline:
	.venv/bin/python scripts/check_resource_warning_baseline.py

.PHONY: check-flags
# Sprint E1.1 (#1711) — feature-flag drift gate (local mirror of CI).
# Mirrors .github/workflows/feature-flag-drift.yml so operators can
# pre-flight the gate before pushing.
check-flags:
	.venv/bin/python scripts/check_feature_flags.py

.PHONY: new-team
# D7.13 #1425 — frictionless team scaffolding (golden path).
#
# Usage: make new-team NAME=<kebab-case-name>
#
# Chains: scaffold_zone4 chief-specialist <name>  →  validate_team_yaml <name>
#         →  pytest -k <name>. The whole chain should complete in <60s
#         from cold for an empty new team.
#
# This wraps the existing scaffolding tools (scaffold_zone4 / new_team /
# new_specialist / new_skill) — it does NOT replace them. The Makefile
# target is the operator-facing one-shot; the Python scripts remain the
# composable building blocks.
new-team:
	@if [ -z "$(NAME)" ]; then echo "Usage: make new-team NAME=<kebab-case-name>"; exit 2; fi
	@echo "[new-team] 1/3 scaffolding chief-specialist team '$(NAME)'..."
	.venv/bin/python -m scripts.scaffold_zone4 chief-specialist $(NAME)
	@echo "[new-team] 2/3 validating $(NAME).yaml..."
	.venv/bin/python -m scripts.validate_team_yaml $(NAME)
	@echo "[new-team] 3/3 running pytest -k $(NAME)..."
	.venv/bin/python -m pytest tests/ -m "not live" -k "$(NAME)" -q
	@echo "[new-team] OK — team '$(NAME)' is first-run-ready."

.PHONY: validate-teams
# D7.13 #1425 — validate every team YAML in agent/config/teams/.
# Advisory by default (missing expertise/system_prompt files are warnings).
# Pass STRICT=1 to promote them to errors.
validate-teams:
	@if [ "$(STRICT)" = "1" ]; then \
		.venv/bin/python -m scripts.validate_team_yaml --all --strict; \
	else \
		.venv/bin/python -m scripts.validate_team_yaml --all; \
	fi

.PHONY: test test-offline test-socket live-smoke codex-live-smoke
# Sprint P0.3 — authoritative test lanes.
# Sprint R3.2 (#1898) — formal taxonomy: docs/testing/test-taxonomy.md.
#
# Four lanes, increasing in side-effect surface:
#   `make test`         — DEFAULT. Sandbox-safe: no live APIs, no socket binds.
#                         Mirrors what CI runs by default (test-offline.yml).
#                         Equivalent to: pytest -m "not live and not socket"
#   `make test-offline` — Alias for `make test`. Kept for backwards-compat
#                         with existing docs/CI that already reference it.
#   `make test-socket`  — Adds the socket-binding lane (aiohttp TestServer
#                         API tests). Use locally when networking is
#                         unrestricted. Still excludes `live`.
#                         May need elevated sandbox permissions under Codex
#                         — see docs/testing/test-taxonomy.md.
#   `make test-warnings`— Same selection as `make test` plus
#                         -W default::ResourceWarning so latent unclosed-
#                         resource warnings surface. Project-code coroutine
#                         + collection warnings are already promoted to
#                         errors via pyproject.toml filterwarnings (R2.4).
#                         Policy: docs/testing/warning-policy.md.
#   `make live-smoke`   — Runs every @pytest.mark.live test against the real
#                         Anthropic / OpenRouter APIs. Requires ANTHROPIC_API_KEY.
#                         Per-test cost cap defaults to $0.50; override via
#                         LIVE_COST_CAP=<usd>.
test test-offline:
	.venv/bin/python -m pytest tests/ job_search/tests/ -m "not live and not socket" -q

test-socket:
	.venv/bin/python -m pytest tests/ job_search/tests/ -m "not live" -q

# Sprint R2.4 (#1896) — strict warning gate.
# Same selection as `make test`, but with -W default::ResourceWarning so
# latent unclosed-resource warnings surface (Python's default would hide
# them). The error-promotion rules in pyproject.toml's filterwarnings
# stay active for project-code coroutine + collection warnings.
#
# Full policy + rationale: docs/testing/warning-policy.md.
#
# This target is the operator's periodic audit for warning regressions
# — it is NOT in `make readiness` yet. Promote there only after a clean
# week.
.PHONY: test-warnings
test-warnings:
	.venv/bin/python -m pytest tests/ job_search/tests/ \
		-m "not live and not socket" -q \
		-W default::ResourceWarning

live-smoke:
	@if [ -z "$$ANTHROPIC_API_KEY" ]; then \
		echo "ANTHROPIC_API_KEY not set — refusing to run live tests."; \
		echo "Export the key first: export ANTHROPIC_API_KEY=<anthropic-api-key>"; \
		exit 2; \
	fi
	.venv/bin/python -m pytest tests/ -m live -v

# Codex-2 (#1836) — Codex CLI live-smoke. Gated on CODEX_API_KEY so it never
# runs in CI (CI does not export the key). Per-test cost cap defaults to
# $0.10 (Codex is cheap on small prompts); override via LIVE_COST_CAP=<usd>.
codex-live-smoke:
	@if [ -z "$$CODEX_API_KEY" ]; then \
		echo "CODEX_API_KEY not set — refusing to run Codex live-smoke."; \
		echo "Export the key first: export CODEX_API_KEY=sk-..."; \
		exit 2; \
	fi
	.venv/bin/python -m pytest tests/test_codex_backend_live.py -m live -v

# Mem-11 (#1852) — E2E acceptance harness for the memory-tier-architecture epic.
# Runs the integration tests, the Mem-6 A/B harness against a synthetic seeded
# DB, and the feature-flag registry drift check. Exit 0 + a clean A/B report
# is the operator's green light to flip `memory_tiers_enabled = true`. See
# docs/operator/memory-tiers-runbook.md for the surrounding choreography.
.PHONY: memory-tier-e2e
memory-tier-e2e:
	@bash scripts/run_memory_tier_e2e.sh

# Issue #2537 — local readiness gate for the dormant Dark Factory activation
# path. This stays fully offline: tests mock GitHub/Claude subprocess seams and
# never touch LaunchDaemon state, live credentials, production flags, or the Mac
# Mini runtime.
.PHONY: factory-readiness
factory-readiness:
	.venv/bin/python -m pytest \
		tests/test_factory_orchestrator.py \
		tests/test_factory_soak_harness.py \
		tests/test_factory_operator_commands.py \
		tests/test_service_runner.py \
		-q

# Issue #2545 — local readiness gate for the default-off VAPI voice surface.
# This is the green-lane, no-socket subset: it uses mocks/fixtures only and
# never calls VAPI, telephony, Discord, live credentials, or the Mac Mini
# runtime. The socket-bound webhook route matrix remains in `make test-socket`
# and the broader production readiness gate.
.PHONY: vapi-readiness
vapi-readiness:
	.venv/bin/python -m pytest \
		tests/test_config.py::TestD17aVapiConfigScaffold \
		tests/test_config.py::TestBridgeConfigCrossFieldValidate::test_voice_enabled_requires_vapi_api_key \
		tests/test_config.py::TestBridgeConfigCrossFieldValidate::test_voice_enabled_with_whitespace_only_vapi_key_fails \
		tests/test_config.py::TestBridgeConfigCrossFieldValidate::test_voice_disabled_with_empty_vapi_key_passes \
		tests/test_config.py::TestBridgeConfigCrossFieldValidate::test_voice_enabled_with_vapi_key_passes \
		tests/test_vapi_webhook_auth.py::test_start_raises_when_voice_enabled_and_secret_empty \
		tests/test_vapi_webhook_auth.py::test_config_default_vapi_webhook_secret_is_empty \
		tests/test_vapi_client.py \
		tests/test_voice_commands.py \
		tests/test_vapi_route_registry.py \
		tests/test_vapi_squad.py \
		tests/test_vapi_squad_integration.py \
		tests/test_voice_department_tools.py \
		tests/test_department_commands.py \
		-q

# Sprint audit-2026-05-15.D.03 (#2005) — clean-worktree test ergonomics.
# Documented in agent/README-test.md; motivation in the 2026-05-15 audit §M-3.
.PHONY: test-clean-worktree
test-clean-worktree:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest agent/tests -q

.PHONY: test-async
test-async:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTEST_PLUGINS=pytest_asyncio python3 -m pytest agent/tests -q

.PHONY: test-all
test-all: test-clean-worktree test-async
	@echo "All test suites green."
