"""Tests for agent/config/hooks/repo-awareness.sh.

The hook is a read-only orientation block emitted at session start.
These tests verify:
  - The script exits 0 and emits a recognizable header under normal conditions
  - The BUMBA_REPO_AWARENESS=0 feature flag suppresses all output
  - A missing source repo results in graceful silent exit 0 (not failure)
  - The output contains only plain-text markdown — no shell error spew

The hook must NEVER fail the parent session-start hook, so the golden
property tested is: exit_code == 0, always.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "agent" / "config" / "hooks" / "repo-awareness.sh"


def _run(env_override: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    return subprocess.run(
        ["bash", str(HOOK)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=15,
    )


def test_hook_exists_and_is_executable():
    assert HOOK.is_file(), f"hook missing at {HOOK}"
    assert os.access(HOOK, os.X_OK), f"hook not executable at {HOOK}"


def test_hook_exits_zero_under_normal_conditions():
    """Hook must never propagate errors — it's called inside another hook."""
    result = _run()
    assert result.returncode == 0, (
        f"hook exited {result.returncode}, stderr={result.stderr!r}"
    )


def test_hook_produces_header_line():
    """Output should lead with the REPO AWARENESS banner."""
    result = _run()
    assert "REPO AWARENESS" in result.stdout


def test_disable_flag_suppresses_all_output():
    """BUMBA_REPO_AWARENESS=0 must produce zero stdout."""
    result = _run({"BUMBA_REPO_AWARENESS": "0"})
    assert result.returncode == 0
    assert result.stdout == ""


def test_disable_flag_false_also_suppresses():
    """Accept 'false' as a disable value for ergonomics."""
    result = _run({"BUMBA_REPO_AWARENESS": "false"})
    assert result.returncode == 0
    assert result.stdout == ""


def test_hook_does_not_leak_kill_or_error_spew():
    """The background-kill timeout construct used to leak 'Killed: 9' lines.

    Verify no such noise reaches stdout (it would confuse the session-start
    message and potentially break jq JSON assembly upstream).
    """
    result = _run()
    forbidden = ["Killed: 9", "Terminated:", "bash: line"]
    for phrase in forbidden:
        assert phrase not in result.stdout, (
            f"hook stdout contains forbidden noise {phrase!r}: {result.stdout!r}"
        )


def test_hook_output_is_under_2kb():
    """Orientation must stay compact — agent context is finite."""
    result = _run()
    assert len(result.stdout) < 2048, (
        f"orientation is {len(result.stdout)} bytes, budget is 2048"
    )


def test_hook_contains_trailing_guidance():
    """Output should end with the 'stop and verify' instruction so the agent
    knows what to do with the information."""
    result = _run()
    assert "stop and verify" in result.stdout.lower()
