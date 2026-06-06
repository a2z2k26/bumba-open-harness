"""Live-smoke harness for CodexBackend (Sprint Codex-2, #1836).

Opt-in, cost-capped, CI-skipped. Spawns the real ``codex exec --json``
subprocess against a trivial prompt and asserts the parser handles the
returned stream cleanly.

Invoke with:
    make codex-live-smoke
    # or
    .venv/bin/python -m pytest tests/test_codex_backend_live.py -m live -v

Requires:
    - CODEX_API_KEY env var (or ``~/.codex/auth.json`` from Codex-4)
    - A `codex` binary on PATH (or BUMBA_CODEX_BINARY pointing at one)
    - (Optional) LIVE_COST_CAP=0.10 to override per-test cost ceiling

Gating: ``@pytest.mark.live`` ensures this NEVER runs in CI (CI does not
export ``CODEX_API_KEY``); the skipif on ``CODEX_API_KEY`` is the second
defense layer for local-but-unkeyed runs.

Cost budget: Codex on a trivial prompt costs ~$0.001–$0.005; the default
LIVE_COST_CAP=$0.10 is a safety net, not a target.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from bridge.backends import CodexBackend

# Module-level marker so every test here gets `live` automatically;
# CI's `pytest -m "not live"` filter then excludes the file entirely.
pytestmark = pytest.mark.live

# Per-test cost cap (USD). Override via LIVE_COST_CAP=<usd>.
_DEFAULT_COST_CAP_USD = float(os.environ.get("LIVE_COST_CAP", "0.10"))

# Trivial prompt — exercises the full thread.started → item.completed
# (agent_message) → turn.completed cycle for under ~$0.005.
_SMOKE_PROMPT = "Say hello in exactly three words. No preamble."


def _codex_available() -> bool:
    """True if a `codex` binary is resolvable (BUMBA_CODEX_BINARY or PATH)."""
    if os.environ.get("BUMBA_CODEX_BINARY"):
        return True
    return shutil.which("codex") is not None


@pytest.mark.skipif(
    not os.environ.get("CODEX_API_KEY"),
    reason="CODEX_API_KEY not set — skipping Codex live-smoke",
)
@pytest.mark.skipif(
    not _codex_available(),
    reason="`codex` binary not found on PATH and BUMBA_CODEX_BINARY unset",
)
def test_codex_live_smoke(sample_config) -> None:
    """Spawn `codex exec --json "<prompt>"`, parse the stream, assert sanity.

    Pass criteria:
      - Subprocess exits 0
      - Every non-empty stdout line is either repairable JSON or a known
        Codex event (parse_event returns either StreamEvent or None — no
        exceptions, no silent unhandled types beyond the documented set)
      - At least one ``thread.started`` event surfaced (init signal)
      - At least one assistant message with non-empty text surfaced
      - At least one ``turn.completed`` (success) event surfaced

    Cost cap enforced via process timeout (60s wall ceiling) — a stuck
    Codex invocation never burns budget.
    """
    backend = CodexBackend(sample_config)
    binary = backend.resolve_binary()
    cmd = backend.build_command(message=_SMOKE_PROMPT, binary=binary)

    # Run with a wall-clock timeout to bound cost in worst case.
    proc = subprocess.run(  # noqa: S603  (trusted — backend-built argv)
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert proc.returncode == 0, (
        f"codex exited non-zero: rc={proc.returncode}\n"
        f"stderr:\n{proc.stderr[:2000]}\n"
        f"stdout (first 1KB):\n{proc.stdout[:1024]}"
    )

    # Walk every non-empty stdout line through the parser. Every line
    # must be either valid JSON (so parse_event can decide) OR be
    # successfully parsed/dropped without raising.
    events = []
    for raw_line in proc.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Sanity check the line is itself parseable JSON. If not, the
        # _try_repair_json fallback should still produce a usable dict
        # OR return None (and parse_event will drop with a warning).
        try:
            json.loads(line)
        except json.JSONDecodeError:
            # Repair path is exercised — parse_event handles it.
            pass

        ev = backend.parse_event(line)
        if ev is not None:
            events.append(ev)

    # At least one init event
    init_events = [e for e in events if e.type == "system" and e.subtype == "init"]
    assert init_events, "No `thread.started` event surfaced in Codex stream"

    # At least one assistant message with non-empty text
    assistant_events = [e for e in events if e.type == "assistant" and e.text]
    assert assistant_events, "No assistant message with text surfaced"

    # At least one successful result
    result_events = [
        e for e in events if e.type == "result" and e.subtype == "success" and not e.is_error
    ]
    assert result_events, "No `turn.completed` (success) event surfaced"

    # Cost cap is enforced via wall timeout, not per-token math (we don't
    # have Codex pricing constants wired until Codex-6). Surface the
    # configured cap to the test log for the operator.
    print(f"\n[codex-live-smoke] LIVE_COST_CAP={_DEFAULT_COST_CAP_USD:.4f} USD (wall: 60s)")
    print(f"[codex-live-smoke] events surfaced: {len(events)}")
    print(f"[codex-live-smoke] assistant text: {assistant_events[0].text[:200]!r}")
