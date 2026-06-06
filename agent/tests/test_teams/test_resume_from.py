"""WS2.5 — resume_from kwarg on DepartmentTeam.run.

When ``resume_from`` names a prior run directory under ``deps.artifact_root``,
``DepartmentTeam.run`` loads the checkpoint and resumes:

* missing checkpoint -> failure TeamResult (failure_class='checkpoint_missing'),
  manager NOT called;
* checkpoint with resumable=False -> failure TeamResult
  (failure_class='checkpoint_unresumable'), manager NOT called;
* resumable checkpoint -> message_history.json is reloaded and threaded into the
  manager.run call; completed_specialists pre-seed the run collector so Gate 8
  counts prior work; the next checkpoint write increments ``attempt``.

SEAM AUDIT: the writer (WS2.3 ``serialize_message_history``) and this loader
round-trip through ``message_history.json``; ``RECOVERABLE_FAILURE_CLASSES`` is
the single source of resume eligibility (recorded as ``record.resumable``).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel

from bridge.run_artifacts import (
    CheckpointRecord,
    CheckpointSpecialist,
    MESSAGE_HISTORY_FILENAME,
    load_checkpoint,
    write_checkpoint,
    write_manifest,
    RunManifest,
    SCHEMA_VERSION,
)
from teams._team import DepartmentTeam
from teams._types import (
    AgentSpec,
    BridgeDeps,
    Constraints,
    DepartmentConfig,
)
from tests.test_teams.conftest import make_deps


def _config(*, expected_min: int = 0) -> DepartmentConfig:
    return DepartmentConfig(
        name="qa",
        zone=4,
        description="QA",
        manager=AgentSpec(name="qa-chief", model="anthropic:claude-opus-4-6"),
        employees=(
            AgentSpec(name="qa-engineer", model="anthropic:claude-sonnet-4-6"),
        ),
        constraints=Constraints(expected_min_specialists=expected_min),
    )


def _deps_with_artifact_root(tmp_path: Path) -> BridgeDeps:
    deps = make_deps(session_id="s1", department="qa")
    return dataclasses.replace(deps, artifact_root=tmp_path / "zone4-runs")


def _seed_checkpoint_run(
    tmp_path: Path,
    *,
    run_id: str = "run-prior",
    resumable: bool,
    attempt: int = 1,
    specialists: tuple[CheckpointSpecialist, ...] = (),
    with_history: bool = True,
) -> Path:
    """Create a prior run dir with a checkpoint (+ optional message history)."""
    run_dir = tmp_path / "zone4-runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    # A real resumed run dir carries the original run's manifest.json — the
    # finalize seam reads + rewrites it before the checkpoint is written.
    write_manifest(
        run_dir,
        RunManifest(
            schema_version=SCHEMA_VERSION,
            run_id=run_id,
            session_id="s1",
            department="qa",
            directive_id=None,
            started_at_utc="2026-06-03T00:00:00Z",
            chief="qa-chief",
        ),
    )
    record = CheckpointRecord(
        schema_version=1,
        run_id=run_id,
        department="qa",
        chief="qa-chief",
        task="rescue this",
        directive_id=None,
        checkpoint_at_utc="2026-06-03T00:00:00Z",
        failure_class="timeout" if resumable else "fatal",
        resumable=resumable,
        completed_specialists=specialists,
        message_history_ref=MESSAGE_HISTORY_FILENAME if with_history else None,
        attempt=attempt,
    )
    write_checkpoint(run_dir, record)
    if with_history:
        msgs = [
            ModelRequest(parts=[UserPromptPart(content="original task")]),
            ModelResponse(parts=[TextPart(content="partial progress")]),
        ]
        (run_dir / MESSAGE_HISTORY_FILENAME).write_bytes(
            ModelMessagesTypeAdapter.dump_json(msgs)
        )
    return run_dir


@pytest.mark.asyncio
async def test_resume_preloads_history(tmp_path: Path) -> None:
    """A resumable checkpoint reloads message_history.json and threads it into
    the manager.run call as the ``message_history`` kwarg."""
    _seed_checkpoint_run(tmp_path, resumable=True)
    deps = _deps_with_artifact_root(tmp_path)
    team = DepartmentTeam(config=_config(), lazy_build=False)

    captured: dict[str, object] = {}
    real_run = team.manager.run

    async def _capturing_run(task: str, **kwargs: object):
        captured["message_history"] = kwargs.get("message_history")
        return await real_run(task, **kwargs)

    test_model = TestModel(custom_output_args={"answer": "done"}, call_tools=[])
    with team.manager.override(model=test_model):
        import unittest.mock as mock

        with mock.patch.object(team.manager, "run", side_effect=_capturing_run):
            result = await team.run(
                "rescue this", deps=deps, resume_from="run-prior"
            )

    assert result.success is True
    history = captured["message_history"]
    assert history is not None
    assert len(history) == 2  # the two reloaded messages


@pytest.mark.asyncio
async def test_resume_rejects_unresumable(tmp_path: Path) -> None:
    """A checkpoint with resumable=False short-circuits: failure TeamResult,
    manager never called."""
    _seed_checkpoint_run(tmp_path, resumable=False)
    deps = _deps_with_artifact_root(tmp_path)
    team = DepartmentTeam(config=_config(), lazy_build=False)

    import unittest.mock as mock

    with mock.patch.object(team.manager, "run", new=AsyncMock()) as mocked_run:
        result = await team.run(
            "rescue this", deps=deps, resume_from="run-prior"
        )

    assert result.success is False
    assert result.telemetry is not None
    assert result.telemetry.failure_class == "checkpoint_unresumable"
    mocked_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_unknown_run_id(tmp_path: Path) -> None:
    """An unknown run_id (no checkpoint on disk) short-circuits: failure
    TeamResult, manager never called."""
    deps = _deps_with_artifact_root(tmp_path)
    (tmp_path / "zone4-runs").mkdir(parents=True, exist_ok=True)
    team = DepartmentTeam(config=_config(), lazy_build=False)

    import unittest.mock as mock

    with mock.patch.object(team.manager, "run", new=AsyncMock()) as mocked_run:
        result = await team.run(
            "rescue this", deps=deps, resume_from="run-does-not-exist"
        )

    assert result.success is False
    assert result.telemetry is not None
    assert result.telemetry.failure_class == "checkpoint_missing"
    mocked_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_preseeds_gate8(tmp_path: Path) -> None:
    """completed_specialists from the checkpoint pre-seed the run collector so
    Gate 8 (expected_min_specialists) counts prior work — a resume that adds no
    new specialists still passes the floor."""
    _seed_checkpoint_run(
        tmp_path,
        resumable=True,
        specialists=(
            CheckpointSpecialist(
                name="qa-engineer",
                success=True,
                output_sha256="abc",
                error=None,
            ),
        ),
    )
    deps = _deps_with_artifact_root(tmp_path)
    # Gate 8 floor of 1; the resumed run delegates to nobody new, but the
    # pre-seeded specialist satisfies the floor.
    team = DepartmentTeam(config=_config(expected_min=1), lazy_build=False)

    test_model = TestModel(custom_output_args={"answer": "done"}, call_tools=[])
    with team.manager.override(model=test_model):
        result = await team.run(
            "rescue this", deps=deps, resume_from="run-prior"
        )

    # Gate 8 would FAIL (0 < 1) without the pre-seed; it passes because the
    # checkpoint's completed_specialists are carried into employee_results.
    assert result.success is True
    assert any(
        er.employee_name == "qa-engineer" for er in result.employee_results
    )


@pytest.mark.asyncio
async def test_resume_increments_attempt(tmp_path: Path) -> None:
    """The next checkpoint write after a resume records attempt = prior + 1."""
    run_dir = _seed_checkpoint_run(tmp_path, resumable=True, attempt=2)
    deps = _deps_with_artifact_root(tmp_path)
    team = DepartmentTeam(config=_config(), lazy_build=False)

    # Force a recoverable failure so should_checkpoint fires and a new
    # checkpoint is written into the SAME run dir.
    import asyncio

    async def _slow(*args: object, **kwargs: object):
        await asyncio.sleep(5)

    tight = dataclasses.replace(
        _config(), constraints=Constraints(timeout_seconds=1)
    )
    team = DepartmentTeam(config=tight, lazy_build=False)

    import unittest.mock as mock

    with mock.patch.object(team.manager, "run", side_effect=_slow):
        result = await team.run(
            "rescue this", deps=deps, resume_from="run-prior"
        )

    assert result.success is False
    record = load_checkpoint(run_dir)
    assert record is not None
    assert record.attempt == 3  # prior attempt was 2
