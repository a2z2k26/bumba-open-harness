"""Tests for the canonical source territory guard (Sprint S7.2, issue #2354).

The script under test scans a repo root for live files at forbidden shadow
paths and exits non-zero when any are found. These tests build synthetic
trees in ``tmp_path`` and invoke the guard's ``check()`` and ``main()``
entrypoints directly — no real repo modifications.

The real repo is also exercised once in :func:`test_real_repo_is_clean`
as a regression catch: if a shadow file ever lands in main, this test
fires before the operator notices.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Import via path injection — keeps the script invocable as both a module
# and a CLI without forcing a packaging change.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import check_canonical_source_territory as guard  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_clean_tree(root: Path) -> None:
    """Build a minimal clean-tree fixture: agent/ exists, no shadows."""
    (root / "agent" / "bridge").mkdir(parents=True)
    (root / "agent" / "bridge" / "app.py").write_text("# canonical\n")
    (root / "agent" / "pyproject.toml").write_text("[project]\nname='x'\n")
    # Non-shadow top-level dirs that should NOT trigger the guard.
    (root / "docs").mkdir()
    (root / "scripts").mkdir()


def _add_shadow_file(root: Path, rel: str, contents: str = "# shadow\n") -> Path:
    """Create a file at a shadow path inside ``root`` and return its path."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    return path


# ---------------------------------------------------------------------------
# check() — pure-function tests against synthetic trees
# ---------------------------------------------------------------------------


def test_clean_tree_returns_no_violations(tmp_path: Path) -> None:
    """Baseline: a tree with only canonical paths passes."""
    _make_clean_tree(tmp_path)
    assert guard.check(tmp_path) == []


def test_shadow_bridge_py_file_flagged(tmp_path: Path) -> None:
    """A live .py under root bridge/ must be detected."""
    _make_clean_tree(tmp_path)
    _add_shadow_file(tmp_path, "bridge/foo.py")
    violations = guard.check(tmp_path)
    assert violations == ["bridge/foo.py"]


def test_shadow_tests_dir_flagged(tmp_path: Path) -> None:
    """root tests/ — must be detected even for non-Python files."""
    _make_clean_tree(tmp_path)
    _add_shadow_file(tmp_path, "tests/test_foo.py")
    _add_shadow_file(tmp_path, "tests/conftest.py")
    violations = guard.check(tmp_path)
    assert violations == ["tests/conftest.py", "tests/test_foo.py"]


def test_shadow_teams_and_job_search_flagged(tmp_path: Path) -> None:
    """Multiple shadow dirs are all reported together, sorted."""
    _make_clean_tree(tmp_path)
    _add_shadow_file(tmp_path, "teams/engineering.py")
    _add_shadow_file(tmp_path, "job_search/agent.py")
    violations = guard.check(tmp_path)
    assert violations == ["job_search/agent.py", "teams/engineering.py"]


def test_shadow_nested_files_flagged(tmp_path: Path) -> None:
    """Files nested deep inside a shadow dir are still flagged."""
    _make_clean_tree(tmp_path)
    _add_shadow_file(tmp_path, "bridge/services/foo/bar.py")
    violations = guard.check(tmp_path)
    assert violations == ["bridge/services/foo/bar.py"]


def test_root_pyproject_toml_flagged(tmp_path: Path) -> None:
    """Root ``pyproject.toml`` is forbidden (canonical lives at agent/)."""
    _make_clean_tree(tmp_path)
    _add_shadow_file(tmp_path, "pyproject.toml", "[project]\n")
    violations = guard.check(tmp_path)
    assert violations == ["pyproject.toml"]


def test_root_uv_lock_flagged(tmp_path: Path) -> None:
    """Root ``uv.lock`` is forbidden (canonical lives at agent/)."""
    _make_clean_tree(tmp_path)
    _add_shadow_file(tmp_path, "uv.lock", "")
    violations = guard.check(tmp_path)
    assert violations == ["uv.lock"]


def test_agent_subtree_never_flagged(tmp_path: Path) -> None:
    """Files under agent/bridge/, agent/tests/, etc. are canonical."""
    _make_clean_tree(tmp_path)
    (tmp_path / "agent" / "tests").mkdir()
    (tmp_path / "agent" / "tests" / "test_x.py").write_text("# canonical\n")
    (tmp_path / "agent" / "teams").mkdir()
    (tmp_path / "agent" / "teams" / "engineering.py").write_text("# canonical\n")
    (tmp_path / "agent" / "job_search").mkdir()
    (tmp_path / "agent" / "job_search" / "agent.py").write_text("# canonical\n")
    assert guard.check(tmp_path) == []


def test_docs_and_scripts_top_level_never_flagged(tmp_path: Path) -> None:
    """Non-shadow top-level dirs (docs/, scripts/, .github/) are allowed."""
    _make_clean_tree(tmp_path)
    (tmp_path / "scripts" / "deploy.sh").write_text("#!/bin/bash\n")
    (tmp_path / "docs" / "README.md").write_text("# docs\n")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: ci\n")
    assert guard.check(tmp_path) == []


# ---------------------------------------------------------------------------
# main() — exit-code contract
# ---------------------------------------------------------------------------


def test_main_returns_zero_on_clean_tree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_clean_tree(tmp_path)
    rc = guard.main(["--repo-root", str(tmp_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "OK" in captured.out
    assert captured.err == ""


def test_main_returns_one_on_shadow_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_clean_tree(tmp_path)
    _add_shadow_file(tmp_path, "bridge/foo.py")
    rc = guard.main(["--repo-root", str(tmp_path)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "bridge/foo.py" in captured.err
    assert "canonical-write-territory.md" in captured.err


def test_main_returns_two_on_invalid_repo_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Distinct exit code for operator misuse (bad --repo-root)."""
    bogus = tmp_path / "does-not-exist"
    rc = guard.main(["--repo-root", str(bogus)])
    assert rc == 2
    captured = capsys.readouterr()
    assert "is not a directory" in captured.err


# ---------------------------------------------------------------------------
# Real-repo regression catch
# ---------------------------------------------------------------------------


def test_real_repo_is_clean() -> None:
    """The actual repo this test runs in must pass the guard.

    If this fails, a shadow file landed in main — fix it before merging
    anything else.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    violations = guard.check(repo_root)
    assert violations == [], (
        f"Real repo has shadow drift: {violations}. See "
        f"docs/architecture/canonical-write-territory.md."
    )
