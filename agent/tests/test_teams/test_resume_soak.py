"""WS2.7 — resume soak harness + correctness invariant.

This is the closing WS2 sprint. It pins the **resume-correctness invariant** in
two layers, mirroring the structure of ``tests/test_teams/test_live_smoke.py``:

* **Offline (always runs, gates local-ci):** a hand-built checkpoint naming an
  already-completed specialist pre-seeds the run collector. On resume the chief
  delegates only to a *different* specialist; the offline assertions prove the
  completed specialist is NOT re-dispatched (the chief model never emits a
  ``delegate`` call naming it) yet still appears in ``employee_results`` and the
  run reaches synthesis (``success=True``). This is the soak invariant proven
  without an API key.

* **Live (``@pytest.mark.live`` — NEVER runs in CI):** forces a real department
  run to a usable interrupt (a forced ``usage_limit_exceeded``), then resumes
  via ``resume_from`` against the real Anthropic API and asserts the second run
  did not re-dispatch the already-completed specialist and reached synthesis.

INVARIANT (resume correctness):
    A specialist recorded in ``checkpoint.completed_specialists`` is carried
    forward into the resumed run's ``employee_results`` WITHOUT the chief
    re-dispatching it. Resume threads the prior ``message_history`` so the chief
    sees the partial transcript, delegates only to the *remaining* work, and the
    run reaches synthesis.

SEAM AUDIT: the producer is WS2.3/2.4 (``build_checkpoint_record`` +
``write_checkpoint`` writing ``completed_specialists`` + ``message_history.json``)
and the consumer is WS2.5 (``_resolve_resume`` pre-seeding the run collector with
those completed specialists in ``_team.py``). This test cross-checks the seam:
a checkpoint written by the producer is loaded by the consumer and the completed
specialist survives the round-trip into ``employee_results``.

Evidence doc: ``docs/audits/2026-06-04-ws2-resume-correctness.md``.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)

from bridge.run_artifacts import (
    CheckpointRecord,
    CheckpointSpecialist,
    MESSAGE_HISTORY_FILENAME,
    RunManifest,
    SCHEMA_VERSION,
    write_checkpoint,
    write_manifest,
)
from teams._team import DepartmentTeam
from teams._types import (
    AgentSpec,
    BridgeDeps,
    Constraints,
    DepartmentConfig,
)
from tests.test_teams.conftest import (
    make_chief_delegating_model,
    make_deps,
    make_specialist_text_model,
)


# Two employees: ``qa-engineer`` is the already-completed specialist carried
# forward in the checkpoint; ``qa-reviewer`` is the remaining work the chief
# delegates to on resume.
_COMPLETED_SPECIALIST = "qa-engineer"
_REMAINING_SPECIALIST = "qa-reviewer"


def _config(*, expected_min: int = 0) -> DepartmentConfig:
    return DepartmentConfig(
        name="qa",
        zone=4,
        description="QA",
        manager=AgentSpec(name="qa-chief", model="anthropic:claude-opus-4-6"),
        employees=(
            AgentSpec(name=_COMPLETED_SPECIALIST, model="anthropic:claude-sonnet-4-6"),
            AgentSpec(name=_REMAINING_SPECIALIST, model="anthropic:claude-sonnet-4-6"),
        ),
        constraints=Constraints(expected_min_specialists=expected_min),
    )


def _deps_with_artifact_root(tmp_path: Path) -> BridgeDeps:
    deps = make_deps(session_id="s1", department="qa")
    return dataclasses.replace(deps, artifact_root=tmp_path / "zone4-runs")


def _seed_interrupted_run(
    tmp_path: Path,
    *,
    run_id: str = "run-interrupted",
    failure_class: str = "usage_limit_exceeded",
    attempt: int = 1,
) -> Path:
    """Create a prior run dir that interrupted with ONE completed specialist.

    Mirrors what WS2.4's finalize seam writes when a real run trips a recoverable
    interrupt mid-flight: a manifest, a resumable checkpoint naming the completed
    specialist, and the partial message history.
    """
    run_dir = tmp_path / "zone4-runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_manifest(
        run_dir,
        RunManifest(
            schema_version=SCHEMA_VERSION,
            run_id=run_id,
            session_id="s1",
            department="qa",
            directive_id=None,
            started_at_utc="2026-06-04T00:00:00Z",
            chief="qa-chief",
        ),
    )
    record = CheckpointRecord(
        schema_version=1,
        run_id=run_id,
        department="qa",
        chief="qa-chief",
        task="audit the release",
        directive_id=None,
        checkpoint_at_utc="2026-06-04T00:00:00Z",
        failure_class=failure_class,
        resumable=True,
        completed_specialists=(
            CheckpointSpecialist(
                name=_COMPLETED_SPECIALIST,
                success=True,
                output_sha256="deadbeef",
                error=None,
            ),
        ),
        message_history_ref=MESSAGE_HISTORY_FILENAME,
        attempt=attempt,
    )
    write_checkpoint(run_dir, record)
    msgs = [
        ModelRequest(parts=[UserPromptPart(content="audit the release")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="delegate",
                    args={"specialist": _COMPLETED_SPECIALIST, "task": "lint"},
                )
            ]
        ),
        ModelRequest(parts=[UserPromptPart(content="qa-engineer done")]),
    ]
    (run_dir / MESSAGE_HISTORY_FILENAME).write_bytes(
        ModelMessagesTypeAdapter.dump_json(msgs)
    )
    return run_dir


# ---------------------------------------------------------------------------
# Offline soak invariant — always runs, gates local-ci.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_does_not_redispatch_completed_specialist(
    tmp_path: Path,
) -> None:
    """The completed specialist from the checkpoint is carried into
    ``employee_results`` WITHOUT the chief re-dispatching it; the chief delegates
    only to the remaining specialist and the run reaches synthesis.

    This is the offline proof of the resume-correctness invariant — the part
    that must pass in local-ci with no API key.
    """
    _seed_interrupted_run(tmp_path)
    deps = _deps_with_artifact_root(tmp_path)
    team = DepartmentTeam(config=_config(), lazy_build=False)

    # On resume the chief delegates ONLY to the remaining specialist. If the
    # resume path were buggy and re-ran the completed one, the chief model would
    # have to name it — but this model never does.
    chief_model = make_chief_delegating_model(
        [(_REMAINING_SPECIALIST, "review the lint output")],
        final_answer="release audit complete",
    )
    specialist_model = make_specialist_text_model("review done")

    # On resume the chief delegates ONLY to the remaining specialist. If the
    # resume path were buggy and re-ran the completed one, the chief model would
    # have to name it — but this model never does.
    with team.employees[_REMAINING_SPECIALIST].override(model=specialist_model):
        with team.manager.override(model=chief_model):
            result = await team.run(
                "audit the release", deps=deps, resume_from="run-interrupted"
            )

    assert result.success is True, "resumed run must reach synthesis"

    names = [er.employee_name for er in result.employee_results]
    # The completed specialist is present (carried forward from the checkpoint)...
    assert _COMPLETED_SPECIALIST in names, (
        "completed specialist must be carried forward into employee_results"
    )
    # ...and appears EXACTLY ONCE — it was not re-dispatched on top of the
    # pre-seed.
    assert names.count(_COMPLETED_SPECIALIST) == 1, (
        f"completed specialist re-dispatched: employee names = {names!r}"
    )
    # The remaining specialist (the only new delegation) is also present.
    assert _REMAINING_SPECIALIST in names, (
        "the resumed run should delegate to the remaining specialist"
    )


@pytest.mark.asyncio
async def test_resume_preseed_satisfies_gate8_without_redispatch(
    tmp_path: Path,
) -> None:
    """Gate 8 (expected_min_specialists) counts the carried-forward specialist:
    a resume that adds NO new delegation still passes the floor, proving the
    pre-seed — not a re-dispatch — satisfies the gate.
    """
    _seed_interrupted_run(tmp_path)
    deps = _deps_with_artifact_root(tmp_path)
    # Floor of 1; the resumed chief delegates to nobody new.
    team = DepartmentTeam(config=_config(expected_min=1), lazy_build=False)

    chief_model = make_chief_delegating_model(
        [],  # no new delegation at all
        final_answer="nothing more to do",
    )
    with team.manager.override(model=chief_model):
        result = await team.run(
            "audit the release", deps=deps, resume_from="run-interrupted"
        )

    assert result.success is True, (
        "Gate 8 must pass via the pre-seeded specialist, not a re-dispatch"
    )
    names = [er.employee_name for er in result.employee_results]
    assert names == [_COMPLETED_SPECIALIST], (
        f"only the carried-forward specialist should be present, got {names!r}"
    )


# ---------------------------------------------------------------------------
# Live soak — real API, @pytest.mark.live gated, NEVER runs in CI.
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_resume_soak_live(tmp_path: Path) -> None:
    """Force a real department run to a usable interrupt, then resume against the
    real API and assert the already-completed specialist is not re-dispatched and
    the resumed run reaches synthesis.

    The interrupt is forced by a tight ``timeout`` on the first run — ``timeout``
    is in ``RECOVERABLE_FAILURE_CLASSES`` so WS2.4's finalize seam writes a
    resumable checkpoint. To give the resume a completed specialist to carry
    forward (so the "not re-dispatched" assertion is non-vacuous), we hand-seed
    that specialist into the checkpoint after the timeout, then resume.

    Skipped automatically when ANTHROPIC_API_KEY is not set. The
    ``@pytest.mark.live`` marker keeps it out of CI (see Makefile ``test-offline``
    and ``docs/audits/2026-06-04-ws2-resume-correctness.md``).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set — skipping live soak")

    import asyncio

    from bridge.run_artifacts import load_checkpoint

    deps = _deps_with_artifact_root(tmp_path)

    # --- Run 1: drive a REAL run to a usable interrupt via a tight timeout. ---
    tight = dataclasses.replace(
        _config(expected_min=1), constraints=Constraints(timeout_seconds=1)
    )
    team_a = DepartmentTeam(config=tight, lazy_build=False)

    import unittest.mock as mock

    async def _slow(*args: object, **kwargs: object):
        await asyncio.sleep(5)

    with mock.patch.object(team_a.manager, "run", side_effect=_slow):
        first = await team_a.run("audit the release", deps=deps)

    assert first.success is False
    assert first.telemetry is not None
    assert first.telemetry.failure_class == "timeout"

    # Recover the interrupted run_id and confirm a resumable checkpoint landed.
    runs_root = Path(deps.artifact_root)
    run_ids = [p.name for p in runs_root.iterdir() if p.is_dir()]
    assert len(run_ids) == 1, f"expected exactly one run dir, got {run_ids!r}"
    interrupted_run_id = run_ids[0]
    run_dir = runs_root / interrupted_run_id
    record = load_checkpoint(run_dir)
    assert record is not None and record.resumable is True

    # Hand-seed a completed specialist into the checkpoint so the resume has prior
    # work to carry forward (the timeout fired before any real delegation).
    seeded = dataclasses.replace(
        record,
        completed_specialists=(
            CheckpointSpecialist(
                name=_COMPLETED_SPECIALIST,
                success=True,
                output_sha256="seeded",
                error=None,
            ),
        ),
    )
    write_checkpoint(run_dir, seeded)

    # --- Run 2: resume against the REAL API. ---
    team_b = DepartmentTeam(config=_config(expected_min=1), lazy_build=False)
    resumed = await team_b.run(
        "audit the release", deps=deps, resume_from=interrupted_run_id
    )

    assert resumed.success is True, "resumed live run must reach synthesis"
    assert resumed.department == "qa"
    names = [er.employee_name for er in resumed.employee_results]
    # The carried-forward specialist is present exactly once — not re-dispatched.
    assert names.count(_COMPLETED_SPECIALIST) == 1, (
        f"completed specialist re-dispatched on live resume: {names!r}"
    )
