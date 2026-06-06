"""Z4-05 run relay tests for artifact and memory pointers."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from bridge.database import Database
from bridge.directive_store import insert_directive, new_directive_id
from bridge.run_artifacts import ArtifactEntry, RunManifest, write_manifest
from bridge.surface_store import list_by_correlation
from teams._team import DepartmentTeam, build_run_memory_note
from teams._types import (
    AgentSpec,
    Constraints,
    DepartmentConfig,
    Directive,
    SurfaceKind,
    TeamResult,
)
from tests.test_teams.conftest import make_chief_direct_answer_model, make_deps


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test-run-relay.db")
    await database.connect()
    await database.migrate()
    yield database
    await database.close()


def _config() -> DepartmentConfig:
    return DepartmentConfig(
        name="dept-s",
        zone=4,
        description="",
        manager=AgentSpec(
            name="s-chief",
            model="anthropic:claude-opus-4-6",
            role="chief",
        ),
        employees=(
            AgentSpec(
                name="alpha",
                model="anthropic:claude-sonnet-4-6",
                role="alpha",
            ),
        ),
        constraints=Constraints(cost_limit_usd=1.0, timeout_seconds=60),
    )


async def _seed_directive(db: Database) -> str:
    directive = Directive(
        directive_id=new_directive_id(),
        from_agent="main",
        to_chief="s-chief",
        intent="parent",
        constraints=(),
        deadline_utc=None,
        priority="p1",
        issued_at_utc=datetime.now(timezone.utc),
        context={},
        operator_id="op",
    )
    await insert_directive(db, directive)
    return directive.directive_id


def test_build_run_memory_note_truncates_summary_and_lists_artifact_paths(
    tmp_path: Path,
) -> None:
    artifact_body = "SECRET ARTIFACT BODY SHOULD STAY ON DISK"
    artifact_path = tmp_path / "specialists" / "alpha" / "result.md"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(artifact_body, encoding="utf-8")
    entry = ArtifactEntry(
        path="specialists/alpha/result.md",
        kind="specialist_result",
        agent="alpha",
        bytes=len(artifact_body.encode("utf-8")),
        sha256="a" * 64,
    )
    manifest_path = write_manifest(
        tmp_path,
        RunManifest(
            schema_version=1,
            run_id="run-20260521-140610-dept-s-a1b2c3",
            session_id="session-1",
            department="dept-s",
            directive_id=None,
            started_at_utc="2026-05-21T14:06:10Z",
            completed_at_utc="2026-05-21T14:07:10Z",
            chief="s-chief",
            status="success",
            artifacts=(entry,),
        ),
    )
    result = TeamResult(
        department="dept-s",
        manager_output="x" * 2_000,
        success=True,
    )

    note = build_run_memory_note(result, manifest_path)

    assert "Zone4 run: dept-s" in note
    assert f"Manifest: {manifest_path}" in note
    assert "specialists/alpha/result.md" in note
    assert artifact_body not in note
    assert len(note) < 4_000


@pytest.mark.asyncio
async def test_team_run_relays_manifest_and_memory_pointer_to_main(
    db: Database,
    tmp_path: Path,
) -> None:
    config = _config()
    directive_id = await _seed_directive(db)
    memory_store = AsyncMock()
    memory_store.get = AsyncMock(return_value=None)
    memory_store.set = AsyncMock(return_value=None)
    deps = replace(
        make_deps(
            session_id="session-1",
            department="dept-s",
            memory_store=memory_store,
        ),
        database=db,
        directive_id=directive_id,
        artifact_root=tmp_path / "zone4-runs",
        project_root=tmp_path / "target-project",
    )
    team = DepartmentTeam(config=config, lazy_build=False)

    with team.manager.override(model=make_chief_direct_answer_model("synth answer")):
        result = await team.run("task", deps=deps, directive_id=directive_id)

    assert result.success is True
    assert result.run_id is not None
    assert result.manifest_path is not None
    assert result.memory_ref == f"memory:zone4/dept-s/{result.run_id}"
    assert "Run artifacts:" in result.manager_output
    assert result.manifest_path in result.manager_output

    manifest_path = Path(result.manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_id"] == result.run_id
    assert manifest["status"] == "success"
    assert manifest["project_root"] == str(tmp_path / "target-project")
    assert result.surface_id in manifest["surfaces"]

    memory_store.set.assert_awaited_once()
    memory_ref, note = memory_store.set.await_args.args
    assert memory_ref == result.memory_ref
    assert str(manifest_path) in note
    assert "synth answer" in note

    surfaces = await list_by_correlation(db, directive_id)
    chief_to_main = [
        s
        for s in surfaces
        if s.from_agent == "s-chief"
        and s.to_agent == "main"
        and s.kind == SurfaceKind.RESULT
    ]
    assert len(chief_to_main) == 1
    payload = chief_to_main[0].payload
    assert payload["manifest_path"] == str(manifest_path)
    assert payload["memory_ref"] == result.memory_ref
    assert payload["artifact_count"] == 0
    assert payload["open_blockers"] == []
