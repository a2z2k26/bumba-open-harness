"""Bounded Zone 4 artifact writing tools."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from bridge.run_artifacts import create_run_workspace
from teams._factory import (
    TEXT_ARTIFACT_MAX_BYTES,
    _safe_artifact_relpath,
    build_employee_agents,
    build_manager_agent,
)
from teams._types import AgentSpec, BridgeDeps, DepartmentConfig
from tests.test_teams.conftest import make_deps


def _config() -> DepartmentConfig:
    return DepartmentConfig(
        name="strategy",
        zone=4,
        description="Strategy",
        manager=AgentSpec(
            name="strategy-product-chief",
            model="test",
        ),
        employees=(
            AgentSpec(
                name="strategy-business-analyst",
                model="test",
            ),
        ),
    )


def _deps(run_dir: Path | None = None) -> BridgeDeps:
    deps = make_deps(session_id="s1", department="strategy")
    if run_dir is None:
        return deps
    return replace(deps, run_artifact_dir=run_dir)


def _workspace(tmp_path: Path):
    return create_run_workspace(
        tmp_path / "zone4-runs",
        session_id="s1",
        department="strategy",
        directive_id="dir-123",
        chief="strategy-product-chief",
        entropy="unit-test",
    )


def test_safe_artifact_relpath_namespaces_by_agent_and_kind() -> None:
    rel = _safe_artifact_relpath(
        "strategy-business-analyst",
        "result",
        "notes.md",
    )

    assert rel == Path("strategy-business-analyst/result/notes.md")


@pytest.mark.parametrize(
    ("filename", "kind"),
    [
        ("../escape.md", "result"),
        ("/tmp/escape.md", "result"),
        ("notes.md", "../kind"),
    ],
)
def test_safe_artifact_relpath_blocks_workspace_escape(
    filename: str,
    kind: str,
) -> None:
    with pytest.raises(ValueError, match="inside the run workspace"):
        _safe_artifact_relpath(
            "strategy-business-analyst",
            kind,
            filename,
        )


def test_artifact_tool_is_registered_for_specialists_and_chiefs() -> None:
    config = _config()
    employees = build_employee_agents(config)
    manager = build_manager_agent(config, employees)

    assert "write_artifact" in employees["strategy-business-analyst"]._function_toolset.tools
    assert "write_artifact" in manager._function_toolset.tools


@pytest.mark.asyncio
async def test_write_artifact_tool_writes_file_and_updates_manifest(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    employees = build_employee_agents(_config())
    tool = employees["strategy-business-analyst"]._function_toolset.tools["write_artifact"]

    class _Ctx:
        deps = _deps(workspace.run_dir)

    result = await tool.function(
        _Ctx(),
        kind="result",
        filename="notes.md",
        content="alpha\n",
    )

    assert result == "strategy-business-analyst/result/notes.md"
    artifact_path = workspace.run_dir / result
    assert artifact_path.read_text(encoding="utf-8") == "alpha\n"

    manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    assert manifest["artifacts"] == [
        {
            "agent": "strategy-business-analyst",
            "bytes": 6,
            "kind": "result",
            "path": "strategy-business-analyst/result/notes.md",
            "sha256": hashlib.sha256(b"alpha\n").hexdigest(),
        }
    ]


@pytest.mark.asyncio
async def test_write_artifact_tool_blocks_escape_before_touching_disk(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    employees = build_employee_agents(_config())
    tool = employees["strategy-business-analyst"]._function_toolset.tools["write_artifact"]

    class _Ctx:
        deps = _deps(workspace.run_dir)

    with pytest.raises(ValueError, match="inside the run workspace"):
        await tool.function(
            _Ctx(),
            kind="result",
            filename="../escape.md",
            content="bad",
        )

    assert not (workspace.run_dir / "escape.md").exists()
    manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    assert manifest["artifacts"] == []


@pytest.mark.asyncio
async def test_write_artifact_tool_enforces_text_size_cap(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    employees = build_employee_agents(_config())
    tool = employees["strategy-business-analyst"]._function_toolset.tools["write_artifact"]

    class _Ctx:
        deps = _deps(workspace.run_dir)

    with pytest.raises(ValueError, match="exceeds 200000 bytes"):
        await tool.function(
            _Ctx(),
            kind="result",
            filename="too-large.md",
            content="x" * (TEXT_ARTIFACT_MAX_BYTES + 1),
        )

    assert not (workspace.run_dir / "strategy-business-analyst/result/too-large.md").exists()


@pytest.mark.asyncio
async def test_write_artifact_tool_requires_run_artifact_dir() -> None:
    employees = build_employee_agents(_config())
    tool = employees["strategy-business-analyst"]._function_toolset.tools["write_artifact"]

    class _Ctx:
        deps = _deps()

    with pytest.raises(RuntimeError, match="run artifact directory is not available"):
        await tool.function(
            _Ctx(),
            kind="result",
            filename="notes.md",
            content="alpha",
        )


@pytest.mark.asyncio
async def test_write_artifact_tool_requires_manifest_before_write(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-without-manifest"
    run_dir.mkdir()
    employees = build_employee_agents(_config())
    tool = employees["strategy-business-analyst"]._function_toolset.tools["write_artifact"]

    class _Ctx:
        deps = _deps(run_dir)

    with pytest.raises(RuntimeError, match="run artifact manifest is not available"):
        await tool.function(
            _Ctx(),
            kind="result",
            filename="notes.md",
            content="alpha",
        )

    assert not (run_dir / "strategy-business-analyst/result/notes.md").exists()
