"""Tests for project archival workflow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bridge.project_archiver import ProjectArchiver


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    wo_dir = tmp_path / "workorder-outputs" / "wo-001"
    wo_dir.mkdir(parents=True)
    (wo_dir / "result.json").write_text('{"status": "complete"}')

    wo_dir2 = tmp_path / "workorder-outputs" / "wo-002"
    wo_dir2.mkdir(parents=True)
    (wo_dir2 / "result.json").write_text('{"status": "complete"}')

    progress_dir = tmp_path / "project_progress"
    progress_dir.mkdir()
    (progress_dir / "my-project-progress.json").write_text(
        json.dumps({"sessions": [{"date": "2026-04-01"}]})
    )

    (tmp_path / "archive").mkdir()
    return tmp_path


@pytest.fixture
def projects_dir(tmp_path: Path) -> Path:
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "my-project.yaml").write_text(
        "project: my-project\nstatus: deprecated\ndescription: Test project\n"
    )
    return projects


def test_archive_project(data_dir: Path, projects_dir: Path) -> None:
    archiver = ProjectArchiver(data_dir=data_dir, projects_dir=projects_dir)
    result = archiver.archive("my-project")
    assert result.success is True
    assert result.archived_files > 0


def test_archive_creates_archive_dir(data_dir: Path, projects_dir: Path) -> None:
    archiver = ProjectArchiver(data_dir=data_dir, projects_dir=projects_dir)
    archiver.archive("my-project")
    archive_dir = data_dir / "archive" / "my-project"
    assert archive_dir.exists()


def test_archive_preserves_workorder_history(data_dir: Path, projects_dir: Path) -> None:
    archiver = ProjectArchiver(data_dir=data_dir, projects_dir=projects_dir)
    result = archiver.archive("my-project")
    assert result.success is True
    archive_dir = data_dir / "archive" / "my-project"
    assert (archive_dir / "workorder-outputs").exists()
    assert (archive_dir / "manifest.json").exists()


def test_archive_purges_working_files(data_dir: Path, projects_dir: Path) -> None:
    archiver = ProjectArchiver(data_dir=data_dir, projects_dir=projects_dir)
    result = archiver.archive("my-project", purge_working=True)
    assert result.success is True
    wo_dir = data_dir / "workorder-outputs"
    remaining = list(wo_dir.iterdir()) if wo_dir.exists() else []
    assert len(remaining) == 0


def test_archive_updates_project_status(data_dir: Path, projects_dir: Path) -> None:
    archiver = ProjectArchiver(data_dir=data_dir, projects_dir=projects_dir)
    result = archiver.archive("my-project")
    project_file = projects_dir / "my-project.yaml"
    content = project_file.read_text()
    assert "archived" in content


def test_archive_nonexistent_project(data_dir: Path, projects_dir: Path) -> None:
    archiver = ProjectArchiver(data_dir=data_dir, projects_dir=projects_dir)
    result = archiver.archive("nonexistent")
    assert result.success is False
