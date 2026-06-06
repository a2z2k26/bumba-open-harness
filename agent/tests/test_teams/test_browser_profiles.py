"""Tests for the D5.7 browser-profile loader."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from teams.job_search._browser_profiles import (
    BrowserProfile,
    load_profile_for_board,
    profile_path_for_board,
)


def test_load_profile_returns_none_when_missing(tmp_path: Path) -> None:
    """No file at <root>/<board>.json → None."""
    out = load_profile_for_board("remotive", profiles_root=tmp_path)
    assert out is None


def test_load_profile_returns_browser_profile_when_present(tmp_path: Path) -> None:
    """Existing profile file → BrowserProfile populated from mtime."""
    profile_file = tmp_path / "remotive.json"
    profile_file.write_text("{}")

    out = load_profile_for_board("remotive", profiles_root=tmp_path)

    assert isinstance(out, BrowserProfile)
    assert out.board == "remotive"
    assert out.path == profile_file
    assert out.is_stale is False
    assert out.age_days == 0


def test_load_profile_marks_stale_when_older_than_threshold(tmp_path: Path) -> None:
    """File mtime older than threshold → is_stale=True (still returned)."""
    profile_file = tmp_path / "himalayas.json"
    profile_file.write_text("{}")
    forty_days_ago = time.time() - (40 * 86400)
    os.utime(profile_file, (forty_days_ago, forty_days_ago))

    out = load_profile_for_board(
        "himalayas",
        profiles_root=tmp_path,
        stale_threshold_days=30,
    )

    assert out is not None
    assert out.is_stale is True
    assert out.age_days >= 40


def test_load_profile_fresh_when_threshold_not_exceeded(tmp_path: Path) -> None:
    """File mtime ≤ threshold → is_stale=False."""
    profile_file = tmp_path / "ycombinator.json"
    profile_file.write_text("{}")
    twenty_days_ago = time.time() - (20 * 86400)
    os.utime(profile_file, (twenty_days_ago, twenty_days_ago))

    out = load_profile_for_board(
        "ycombinator",
        profiles_root=tmp_path,
        stale_threshold_days=30,
    )

    assert out is not None
    assert out.is_stale is False


def test_profile_path_for_board_returns_str_when_present(tmp_path: Path) -> None:
    """Helper returns str path for chief to thread into BrowserInput."""
    profile_file = tmp_path / "lever.json"
    profile_file.write_text("{}")

    out = profile_path_for_board("lever", profiles_root=tmp_path)

    assert out == str(profile_file)


def test_profile_path_for_board_returns_none_when_missing(tmp_path: Path) -> None:
    """Missing profile → None so chief can decide anonymous vs skip."""
    out = profile_path_for_board("dice", profiles_root=tmp_path)
    assert out is None


def test_load_profile_emits_staleness_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Stale profile triggers a WARNING-level log mentioning the board."""
    profile_file = tmp_path / "dribbble.json"
    profile_file.write_text("{}")
    sixty_days_ago = time.time() - (60 * 86400)
    os.utime(profile_file, (sixty_days_ago, sixty_days_ago))

    with caplog.at_level("WARNING", logger="teams.job_search._browser_profiles"):
        load_profile_for_board(
            "dribbble",
            profiles_root=tmp_path,
            stale_threshold_days=30,
        )

    assert any("dribbble" in rec.message for rec in caplog.records)
    assert any("re-capture" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# D5.7 — Prompt threading: storage_state_path lands in the BrowserUseSpecialist prompt
# ---------------------------------------------------------------------------

from teams.job_search._specialists import _build_browser_prompt
from teams.job_search._types import BrowserInput


def _make_browser_input(**kwargs) -> BrowserInput:
    defaults = {
        "listing_id": "listing-001",
        "url": "https://example.com/jobs/123",
        "cover_letter": "I am excited to apply.",
        "run_id": "test-run",
        "dry_run": True,
        "max_turns": 40,
    }
    defaults.update(kwargs)
    return BrowserInput(**defaults)


def test_prompt_omits_storage_state_section_when_path_is_none() -> None:
    """No storage_state_path → prompt has no LOGGED-IN SESSION section."""
    prompt = _build_browser_prompt(_make_browser_input(storage_state_path=None))
    assert "LOGGED-IN SESSION" not in prompt
    assert "storageStatePath" not in prompt


def test_prompt_includes_storage_state_path_when_provided() -> None:
    """storage_state_path → prompt instructs the subprocess to load it."""
    path = "/opt/bumba-harness/data/browser-profiles/remotive.json"
    prompt = _build_browser_prompt(_make_browser_input(storage_state_path=path))

    assert "LOGGED-IN SESSION AVAILABLE" in prompt
    assert path in prompt
    assert "storageStatePath" in prompt
    assert "requires_login" in prompt  # fallback instruction present


# ---------------------------------------------------------------------------
# D5.7 — Capture script CLI smoke
# ---------------------------------------------------------------------------

import subprocess
import sys


def test_capture_script_help_runs() -> None:
    """`python -m scripts.capture_browser_profile --help` returns 0 and lists args."""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.capture_browser_profile", "--help"],
        cwd="/home/operator/bumba-open-harness/agent",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "board" in result.stdout
    assert "--url" in result.stdout
    assert "--profiles-root" in result.stdout


def test_capture_script_requires_url() -> None:
    """Missing --url → argparse exits with non-zero."""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.capture_browser_profile", "remotive"],
        cwd="/home/operator/bumba-open-harness/agent",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "url" in result.stderr.lower() or "url" in result.stdout.lower()
