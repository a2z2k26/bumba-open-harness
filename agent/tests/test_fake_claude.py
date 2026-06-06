"""Unit tests for scripts/fake_claude.py shim."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Absolute path: agent/tests/ → agent/ → repo root → scripts/
SHIM = Path(__file__).resolve().parent.parent.parent / "scripts" / "fake_claude.py"


@pytest.fixture
def shim() -> Path:
    if not SHIM.exists():
        pytest.skip(f"fake_claude.py shim not found at {SHIM}")
    return SHIM


def test_shim_exits_zero(shim: Path) -> None:
    """Shim returns exit code 0 on normal invocation."""
    r = subprocess.run(
        [sys.executable, str(shim), "-p", "test"],
        capture_output=True,
        timeout=5,
    )
    assert r.returncode == 0


def test_shim_emits_result_event(shim: Path) -> None:
    """Shim output contains a 'result' type event."""
    r = subprocess.run(
        [sys.executable, str(shim), "-p", "test"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    events = [json.loads(line) for line in r.stdout.strip().split("\n") if line]
    types = {ev["type"] for ev in events}
    assert "result" in types


def test_shim_result_is_success(shim: Path) -> None:
    """The result event carries subtype='success'."""
    r = subprocess.run(
        [sys.executable, str(shim), "-p", "hello"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    events = [json.loads(line) for line in r.stdout.strip().split("\n") if line]
    result = next((ev for ev in events if ev["type"] == "result"), None)
    assert result is not None, "No result event emitted"
    assert result["subtype"] == "success"


def test_shim_echoes_prompt_in_response(shim: Path) -> None:
    """The assistant event text contains the input prompt (up to 100 chars)."""
    probe = "unique_prompt_xyz_12345"
    r = subprocess.run(
        [sys.executable, str(shim), "-p", probe],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert r.returncode == 0
    assert probe in r.stdout, f"Expected probe text in shim output; got:\n{r.stdout}"


def test_shim_emits_system_init_event(shim: Path) -> None:
    """Shim emits a system/init event as the first stream event."""
    r = subprocess.run(
        [sys.executable, str(shim), "-p", "hello"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    events = [json.loads(line) for line in r.stdout.strip().split("\n") if line]
    assert events, "No events emitted"
    first = events[0]
    assert first["type"] == "system"
    assert first["subtype"] == "init"
    assert "session_id" in first


def test_shim_resume_flag_echoes_session_id(shim: Path) -> None:
    """Shim propagates the --resume session ID into stream events."""
    session = "sess-test-abc"
    r = subprocess.run(
        [sys.executable, str(shim), "--resume", session, "-p", "hi"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert r.returncode == 0
    events = [json.loads(line) for line in r.stdout.strip().split("\n") if line]
    result = next((ev for ev in events if ev["type"] == "result"), None)
    assert result is not None
    assert result.get("session_id") == session
