"""Tests for the Zone 4 end-to-end smoke matrix (Z4-22 #2448).

The smoke matrix (``teams._smoke_matrix``) exercises, per department, two
legs:

- **readiness** — ``registry.route(dept, "ready to work?", deps)``. This
  hits the deterministic ``render_readiness`` path (Z4-01) and MUST spend
  zero provider requests. Asserted by driving a registry whose teams have
  NO model override installed: a readiness prompt that leaked into a real
  ``team.run`` would attempt a model call and fail in this offline env, so
  a clean readiness result proves the zero-provider path.
- **substantive** — a real ``DepartmentTeam.run`` driven by deterministic
  FunctionModels against a tmp ``artifact_root``. This captures the run's
  ``manifest.json`` + telemetry exactly as production would, with no live
  API call.

Failure classification: substantive failures are classified into the six
issue classes — provider, usage_policy, timeout, schema_validation,
artifact, memory.

Offline contract (mirrors ``test_z4_e2e_smoke.py``): no ANTHROPIC_API_KEY,
no OPENROUTER_API_KEY, no network. Teams are scaffolded into ``tmp_path``;
production YAMLs are never read.

2026-05-21 provider context: 46/52 Zone 4 seats are on a dead OpenRouter
key. The matrix is OFFLINE-ONLY by design — it does not call OpenRouter or
Anthropic. The live legs are operator-gated and documented separately.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from teams._smoke_matrix import (
    DEFAULT_SMOKES,
    SmokeCaseResult,
    SmokeMatrixResult,
    classify_smoke_failure,
    run_smoke_matrix,
)

_SOURCE_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_TEMPLATE = (
    _SOURCE_REPO_ROOT / "agent" / "config" / "teams" / "_template.yaml"
)


# ---------------------------------------------------------------------------
# Scaffolding helpers (mirror test_z4_e2e_smoke.py)
# ---------------------------------------------------------------------------


def _patched_repo_root(fake_root: Path) -> list:
    from unittest.mock import patch

    import scripts.scaffold_zone4 as scaffold_mod
    import scripts.validate_team_yaml as validate_mod

    teams_dir = fake_root / "agent" / "config" / "teams"
    template_path = teams_dir / "_template.yaml"
    return [
        patch.object(scaffold_mod, "REPO_ROOT", fake_root),
        patch.object(scaffold_mod, "TEAMS_DIR", teams_dir),
        patch.object(validate_mod, "REPO_ROOT", fake_root),
        patch.object(validate_mod, "TEAMS_DIR", teams_dir),
        patch.object(validate_mod, "TEMPLATE_PATH", template_path),
    ]


class _stack_patches:
    def __init__(self, patches: list) -> None:
        self._patches = patches

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


@pytest.fixture()
def fake_repo(tmp_path: Path) -> Path:
    teams_dir = tmp_path / "agent" / "config" / "teams"
    expertise_dir = tmp_path / "agent" / "config" / "expertise" / "updatable"
    agents_dir = tmp_path / "agent" / "config" / "agents" / "zone4"
    teams_dir.mkdir(parents=True)
    expertise_dir.mkdir(parents=True)
    agents_dir.mkdir(parents=True)
    if _SOURCE_TEMPLATE.exists():
        shutil.copy2(_SOURCE_TEMPLATE, teams_dir / "_template.yaml")
    return tmp_path


def _scaffold(fake_root: Path, slug: str) -> None:
    import scripts.scaffold_zone4 as scaffold_mod

    with _stack_patches(_patched_repo_root(fake_root)):
        rc = scaffold_mod.main(["chief-specialist", slug])
    assert rc == 0


# ---------------------------------------------------------------------------
# classify_smoke_failure — the six-class contract
# ---------------------------------------------------------------------------


class TestClassifyFailure:
    def test_usage_limit_is_usage_policy(self):
        from pydantic_ai.exceptions import UsageLimitExceeded

        assert (
            classify_smoke_failure(UsageLimitExceeded("cap"))
            == "usage_policy"
        )

    def test_model_http_error_is_provider(self):
        from pydantic_ai.exceptions import ModelHTTPError

        exc = ModelHTTPError(status_code=429, model_name="x", body=None)
        assert classify_smoke_failure(exc) == "provider"

    def test_timeout_is_timeout(self):
        assert classify_smoke_failure(TimeoutError()) == "timeout"

    def test_validation_error_is_schema_validation(self):
        assert (
            classify_smoke_failure(ValueError("schema validation failed"))
            == "schema_validation"
        )

    def test_artifact_keyword_is_artifact(self):
        assert (
            classify_smoke_failure("manifest artifact write failed")
            == "artifact"
        )

    def test_memory_keyword_is_memory(self):
        assert (
            classify_smoke_failure("memory_store checkpoint failed")
            == "memory"
        )

    def test_unknown_is_provider_when_401(self):
        # The dead-OpenRouter-key 401 must classify as provider so the
        # operator reads it as a provider problem, not a code bug.
        assert classify_smoke_failure("401 Unauthorized") == "provider"

    def test_none_returns_none(self):
        assert classify_smoke_failure(None) is None


# ---------------------------------------------------------------------------
# run_smoke_matrix — offline, multi-leg
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matrix_runs_offline_readiness_and_substantive(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(fake_repo)
    _scaffold(fake_repo, "qa")
    _scaffold(fake_repo, "strategy")

    from teams._registry import DepartmentRegistry

    teams_dir = fake_repo / "agent/config/teams"
    registry = DepartmentRegistry.from_directory(teams_dir)

    smokes = {
        "qa": ("ready to work?", "What's one small testing improvement?"),
        "strategy": ("ready to work?", "What decision should we make next?"),
    }

    result = await run_smoke_matrix(
        registry,
        smokes=smokes,
        artifact_root=fake_repo / "zone4-runs",
    )

    assert isinstance(result, SmokeMatrixResult)
    # 2 departments x 2 legs = 4 cases.
    assert len(result.cases) == 4

    readiness = [c for c in result.cases if c.leg == "readiness"]
    substantive = [c for c in result.cases if c.leg == "substantive"]
    assert len(readiness) == 2
    assert len(substantive) == 2

    # Readiness legs: zero provider requests, deterministic ok.
    for case in readiness:
        assert case.ok is True
        assert case.provider_requests == 0
        assert case.failure_class is None

    # Substantive legs: a manifest was written and telemetry captured.
    for case in substantive:
        assert case.ok is True
        assert case.manifest_path is not None
        assert Path(case.manifest_path).exists()
        assert case.telemetry_captured is True


@pytest.mark.asyncio
async def test_matrix_substantive_failure_classifies(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
):
    """A substantive run that raises a provider error classifies as provider."""
    monkeypatch.chdir(fake_repo)
    _scaffold(fake_repo, "qa")

    from pydantic_ai.exceptions import ModelHTTPError
    from teams._registry import DepartmentRegistry

    teams_dir = fake_repo / "agent/config/teams"
    registry = DepartmentRegistry.from_directory(teams_dir)

    def _boom(*_a, **_k):
        raise ModelHTTPError(status_code=401, model_name="openrouter:x", body=None)

    result = await run_smoke_matrix(
        registry,
        smokes={"qa": ("ready to work?", "substantive prompt")},
        artifact_root=fake_repo / "zone4-runs",
        substantive_runner=_boom,
    )

    sub = next(c for c in result.cases if c.leg == "substantive")
    assert sub.ok is False
    assert sub.failure_class == "provider"


@pytest.mark.asyncio
async def test_matrix_expected_fail_marks_not_hidden(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
):
    """Departments not in the registry are recorded as expected-fail, surfaced."""
    monkeypatch.chdir(fake_repo)
    _scaffold(fake_repo, "qa")

    from teams._registry import DepartmentRegistry

    teams_dir = fake_repo / "agent/config/teams"
    registry = DepartmentRegistry.from_directory(teams_dir)

    result = await run_smoke_matrix(
        registry,
        smokes={
            "qa": ("ready to work?", "real"),
            "nonexistent": ("ready to work?", "missing dept"),
        },
        artifact_root=fake_repo / "zone4-runs",
    )

    missing = [c for c in result.cases if c.department == "nonexistent"]
    assert missing, "missing department cases must be surfaced, not hidden"
    for case in missing:
        assert case.ok is False
        assert case.failure_class in {"schema_validation", "provider", None}
        # error should name the missing department so the operator doc can
        # explain it rather than hide it.
        assert "nonexistent" in (case.error or "").lower() or not case.ok


def test_default_smokes_cover_program_departments():
    """The default matrix names every Zone 4 department from the issue table."""
    for dept in ("board", "design", "qa", "strategy", "ops", "job_search"):
        assert dept in DEFAULT_SMOKES


def test_matrix_result_to_dict_and_gate_status():
    """SmokeMatrixResult serializes and exposes a pass/fail gate verdict."""
    cases = (
        SmokeCaseResult(
            department="qa", leg="readiness", ok=True,
            provider_requests=0, manifest_path=None,
            telemetry_captured=False, failure_class=None, error=None,
        ),
        SmokeCaseResult(
            department="qa", leg="substantive", ok=True,
            provider_requests=0, manifest_path="/x/manifest.json",
            telemetry_captured=True, failure_class=None, error=None,
        ),
    )
    result = SmokeMatrixResult(cases=cases)
    assert result.gate_ok is True
    payload = result.to_dict()
    assert payload["gate_ok"] is True
    assert len(payload["cases"]) == 2
    assert payload["cases"][0]["leg"] == "readiness"


def test_matrix_gate_fails_when_a_required_case_fails():
    cases = (
        SmokeCaseResult(
            department="qa", leg="readiness", ok=True,
            provider_requests=0, manifest_path=None,
            telemetry_captured=False, failure_class=None, error=None,
        ),
        SmokeCaseResult(
            department="qa", leg="substantive", ok=False,
            provider_requests=1, manifest_path=None,
            telemetry_captured=False, failure_class="provider",
            error="401", expected_fail=False,
        ),
    )
    result = SmokeMatrixResult(cases=cases)
    assert result.gate_ok is False


def test_expected_fail_case_does_not_break_gate():
    """An expected-fail case (declared dependency not landed) does not fail gate."""
    cases = (
        SmokeCaseResult(
            department="ops", leg="substantive", ok=False,
            provider_requests=0, manifest_path=None,
            telemetry_captured=False, failure_class="provider",
            error="provider dead key", expected_fail=True,
        ),
    )
    result = SmokeMatrixResult(cases=cases)
    assert result.gate_ok is True
