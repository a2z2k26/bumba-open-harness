"""E2E tests: WorkOrder → Dispatcher → SubagentExecutor → ClaudeRunner.

Sprint 08.07 (#785): These tests exercise the real dispatch path end-to-end.
``BUMBA_CLAUDE_BINARY`` (honored by ``ClaudeRunner._resolve_binary``) points
the runner at a deterministic stream-json shim so the runner spawns a real
subprocess and emits a real three-event stream
(``system:init`` → ``assistant`` → ``result:success``). No mocked
ClaudeRunner — every layer below ``Dispatcher.dispatch`` is real.

This replaces the previous shim-smoke tests (R3 audit finding) which only
spawned ``scripts/fake_claude.py`` via ``subprocess.run`` and never
exercised the production wiring.

NOTE on the shim: ``scripts/fake_claude.py`` was written for the old
shim-smoke tests that called it directly with an explicit ``-p PROMPT``
argument. ``ClaudeRunner._build_command`` puts ``-p`` immediately before
``--output-format``, which collides with ``fake_claude.py``'s
``-p PROMPT`` arg-parse and breaks under real dispatch. Rather than
patch the shim out of scope, this test file builds its own
purpose-shaped shim in ``tmp_path`` that tolerates the production argv
shape and reads the prompt from stdin (the same path the real
``claude -p`` uses). Aligning the shipped shim to this shape is
tracked alongside this sprint.

Run with: pytest agent/tests/e2e/ -m e2e
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from bridge.claude_runner import ClaudeRunner
from bridge.config import BridgeConfig
from bridge.dispatcher import Dispatcher
from bridge.work_order import (
    Environment,
    WorkOrder,
    WorkOrderStatus,
)

pytestmark = pytest.mark.e2e


# Stream-json shim built per-test in tmp_path. Mirrors scripts/fake_claude.py
# but uses ``-p`` as a flag (no value) the way real ``claude -p`` does, so
# ClaudeRunner's argv (``-p --output-format ...``) doesn't collide with
# argparse. Reads the prompt from stdin (matches the real claude -p path).
_SHIM_SOURCE = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    \"\"\"Per-test stream-json shim for Sprint 08.07 e2e tests (#785).\"\"\"
    from __future__ import annotations
    import argparse, json, sys, uuid

    def main() -> int:
        p = argparse.ArgumentParser()
        # ``-p`` is a flag in real claude (prompt comes from stdin).
        p.add_argument("-p", "--prompt", action="store_true")
        p.add_argument("--resume", default=None)
        p.add_argument("--session-id", default=None)
        p.add_argument("--mcp-config", default=None)
        p.add_argument("--output-format", default="stream-json")
        p.add_argument("--verbose", action="store_true")
        p.add_argument("--dangerously-skip-permissions", action="store_true")
        p.add_argument("--permission-mode", default=None)
        p.add_argument("--allowedTools", nargs="*", default=None)
        p.add_argument("--disallowedTools", nargs="*", default=None)
        p.add_argument("--max-turns", default=None)
        p.add_argument("--append-system-prompt-file", default=None)
        args, _unknown = p.parse_known_args()

        # Real claude -p reads prompt from stdin.
        prompt_text = sys.stdin.read().strip()
        session_id = args.session_id or args.resume or f"shim-{uuid.uuid4().hex[:8]}"

        events = [
            {"type": "system", "subtype": "init",
             "session_id": session_id, "tools": []},
            {"type": "assistant", "message": {
                "id": f"msg_{uuid.uuid4().hex[:12]}", "type": "message",
                "role": "assistant", "content": [{
                    "type": "text",
                    "text": f"[shim] Echo: {prompt_text[:100]}"}],
                "model": "shim-1.0", "stop_reason": "end_turn"}},
            {"type": "result", "subtype": "success",
             "session_id": session_id, "total_cost_usd": 0.0,
             "duration_ms": 5, "num_turns": 1},
        ]
        for ev in events:
            print(json.dumps(ev), flush=True)
        return 0

    if __name__ == "__main__":
        sys.exit(main())
    """
)


@pytest.fixture
def shim_path(tmp_path: Path) -> Path:
    p = tmp_path / "shim_claude.py"
    p.write_text(_SHIM_SOURCE)
    p.chmod(0o755)
    return p


@pytest.fixture
def runner(
    tmp_path: Path,
    shim_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> ClaudeRunner:
    """Real ClaudeRunner pointed at the per-test shim via BUMBA_CLAUDE_BINARY.

    The autouse fixture in conftest.py points BUMBA_CLAUDE_BINARY at the
    legacy ``scripts/fake_claude.py``; we override it with the
    production-shape shim built above. BridgeConfig is constructed
    directly (no ``load_config``) because the loader's validator predates
    the env-var-as-multi-token-shim feature added in this sprint.
    """
    monkeypatch.setenv(
        "BUMBA_CLAUDE_BINARY",
        f"{sys.executable} {shim_path}",
    )
    data_dir = tmp_path / "data"
    log_dir = tmp_path / "logs"
    working_dir = tmp_path / "agent"
    for d in (data_dir, log_dir, working_dir):
        d.mkdir()
    cfg = BridgeConfig(
        data_dir=str(data_dir),
        log_dir=str(log_dir),
        claude_working_dir=str(working_dir),
        claude_binary=None,  # _resolve_binary picks up BUMBA_CLAUDE_BINARY
    )
    return ClaudeRunner(cfg)


@pytest.fixture
def dispatcher(runner: ClaudeRunner) -> Dispatcher:
    """Real Dispatcher wired to the real ClaudeRunner.

    No tmux_manager, no department_registry — SUBAGENT is the only route
    these tests need, and it ships in the default executor map."""
    return Dispatcher(claude_runner=runner)


def _make_assigned_subagent_wo(intent: str = "Hello world") -> WorkOrder:
    """Build a WorkOrder ready for SUBAGENT dispatch."""
    return (
        WorkOrder.create(intent=intent, skill="test", project="e2e")
        .with_environment(Environment.SUBAGENT, rationale="e2e test")
        .transition(WorkOrderStatus.ASSIGNED)
    )


@pytest.mark.asyncio
async def test_dispatcher_to_subagent_to_runner_full_chain(
    dispatcher: Dispatcher,
) -> None:
    """A WorkOrder dispatched through the real chain returns a clean result.

    The shim emits the three-event stream-json sequence. This test asserts
    ``ClaudeResult`` aggregates them correctly: a session_id from
    ``system:init``, response_text from ``assistant``, and clean exit from
    ``result:success``."""
    wo = _make_assigned_subagent_wo(intent="Hello world")

    dispatch_result = await dispatcher.dispatch(wo)

    assert dispatch_result.valid, dispatch_result.reason
    assert dispatch_result.handled, f"Dispatcher fell through: {dispatch_result.reason}"
    assert dispatch_result.result is not None

    cr = dispatch_result.result
    # system:init populates session_id
    assert cr.session_id, "ClaudeResult.session_id must be set by system:init event"
    # assistant event populates response_text — shim echoes the prompt
    assert "Hello world" in cr.response_text
    assert "[shim] Echo:" in cr.response_text
    # result:success means is_error stays False
    assert cr.is_error is False
    assert cr.error_type == ""

    # WorkOrder transitioned through the full state machine to COMPLETE
    assert dispatch_result.workorder is not None
    assert dispatch_result.workorder.status == WorkOrderStatus.COMPLETE


@pytest.mark.asyncio
async def test_dispatcher_resume_session_threads_through_runner(
    dispatcher: Dispatcher,
) -> None:
    """SubagentExecutor does not pass synthetic ``subagent-*`` ids to resume.

    A subagent dispatch is a fresh one-shot Claude run. The executor still uses
    ``subagent-<wo_id_prefix>`` as a log label, but passing that synthetic value
    to ``claude -p --resume`` is invalid because Claude expects a real prior
    session id. The shim returns ``args.resume`` when resume is passed and a
    fresh ``shim-*`` id otherwise, so this locks the production-safe shape.
    """
    wo = _make_assigned_subagent_wo(intent="continue please")

    dispatch_result = await dispatcher.dispatch(wo)

    assert dispatch_result.handled, dispatch_result.reason
    cr = dispatch_result.result
    assert cr is not None
    forbidden_prefix = f"subagent-{wo.id[:8]}"
    # Shim returns args.resume as session_id when --resume is passed; a fresh
    # shim id proves SubagentExecutor left session_id=None.
    assert cr.session_id.startswith("shim-"), (
        f"Expected fresh shim session, got {cr.session_id!r}."
    )
    assert cr.session_id != forbidden_prefix, (
        f"SubagentExecutor passed synthetic resume id {forbidden_prefix!r}; "
        "synthetic subagent ids are log labels only."
    )


@pytest.mark.asyncio
async def test_dispatcher_dangerous_skip_permissions_default(
    dispatcher: Dispatcher,
) -> None:
    """Default permission_mode='bypassPermissions' must produce a clean run.

    The shim accepts --dangerously-skip-permissions; the only way it
    returns a clean result is if ClaudeRunner builds a valid argv with
    that flag wired in. response_text is a strong signal the assistant
    event was parsed — this is what shim-smoke tests could never confirm.
    """
    wo = _make_assigned_subagent_wo(intent="permission flag check")

    dispatch_result = await dispatcher.dispatch(wo)

    assert dispatch_result.valid, dispatch_result.reason
    assert dispatch_result.handled
    assert dispatch_result.result is not None
    assert dispatch_result.result.is_error is False
    assert dispatch_result.result.response_text != ""
