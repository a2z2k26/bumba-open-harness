"""E2E test configuration — points ClaudeRunner at fake_claude.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Absolute path to the fake claude shim (scripts/ lives at repo root)
FAKE_CLAUDE = str(Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "fake_claude.py")


@pytest.fixture(autouse=True)
def use_fake_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect all ClaudeRunner invocations to the fake shim.

    Sprint 08.07: ClaudeRunner._resolve_binary honors BUMBA_CLAUDE_BINARY
    as a test-harness override, so the e2e harness sets that env var to a
    space-separated invocation ("<python> <fake_claude.py>"). The runner
    splits on whitespace and threads the resulting argv through the real
    Dispatcher → Executor → ClaudeRunner chain (no shim-smoke shortcut).

    BUMBA_FAKE_CLAUDE=1 is a separate signal that lets integration
    harnesses detect the fake environment without coupling to
    ClaudeRunner internals.
    """
    monkeypatch.setenv("BUMBA_CLAUDE_BINARY", f"{sys.executable} {FAKE_CLAUDE}")
    monkeypatch.setenv("BUMBA_FAKE_CLAUDE", "1")
    yield
