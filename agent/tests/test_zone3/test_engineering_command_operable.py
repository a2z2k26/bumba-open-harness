"""#2437 — operability proof for the /engineering command path.

The Zone 3 dojo (claude_p executor + governance prompt + artifact capture) is
only *operable* if a substantive ``/engineering`` task actually reaches the
executor. These tests drive the real ``CommandHandler._cmd_engineering`` through
the real ``EngineeringDispatcher.route()`` and the real ``ClaudePExecutor``,
with only the lowest-level process ``spawn`` replaced by a fake. If the
executor's injected spawn is invoked, the dojo is live — not merely "code
wired".
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence

from bridge.commands import CommandHandler


class _FakeProc:
    """Minimal asyncio-subprocess stand-in: communicate() + returncode."""

    returncode = 0

    async def communicate(self, _stdin: bytes | None = None):
        return (b"specialist output", b"")


def _bare_handler() -> CommandHandler:
    """A CommandHandler with only the attributes _cmd_engineering reads."""
    handler = CommandHandler.__new__(CommandHandler)
    handler._claude_runner = None  # forces _engineering_cwd() to os.getcwd()
    handler._dispatcher = None
    handler._start_time = time.monotonic()
    return handler


async def test_substantive_engineering_task_invokes_executor(monkeypatch) -> None:
    """A substantive /engineering task must reach the claude_p executor.

    We inject a fake ``spawn`` into the production ClaudePExecutor adapter so
    no real Claude process starts, then assert the spawn was actually called —
    proving route() -> executor.run() -> spawn fired on the live path.
    """
    spawn_calls: list[dict[str, object]] = []

    async def fake_spawn(
        argv: Sequence[str],
        *,
        cwd: str,
        env: Mapping[str, str] | None,
    ):
        spawn_calls.append({"argv": list(argv), "cwd": cwd})
        return _FakeProc()

    # Force the production adapter to use the fake spawn whenever the command
    # handler constructs it.
    import zone3.claude_p_executor as cpe

    real_init = cpe.ClaudePExecutor.__init__

    def patched_init(self, *, claude_binary="claude", model=None, spawn=None):
        real_init(self, claude_binary=claude_binary, model=model, spawn=fake_spawn)

    monkeypatch.setattr(cpe.ClaudePExecutor, "__init__", patched_init)

    handler = _bare_handler()
    # "review the latest diff" is substantive (not readiness, not cross-zone).
    response = await handler._cmd_engineering("chat-1", "review the latest diff")

    assert spawn_calls, "executor spawn was never invoked — dojo is not operable"
    # The argv must be a real `claude -p` invocation built by the executor.
    assert spawn_calls[0]["argv"][:2][-1] == "-p"
    assert "specialist output" in response


async def test_readiness_task_does_not_invoke_executor(monkeypatch) -> None:
    """Readiness short-circuits — it must NOT spawn the executor."""
    spawn_calls: list[object] = []

    async def fake_spawn(argv, *, cwd, env):
        spawn_calls.append(argv)
        return _FakeProc()

    import zone3.claude_p_executor as cpe

    real_init = cpe.ClaudePExecutor.__init__

    def patched_init(self, *, claude_binary="claude", model=None, spawn=None):
        real_init(self, claude_binary=claude_binary, model=model, spawn=fake_spawn)

    monkeypatch.setattr(cpe.ClaudePExecutor, "__init__", patched_init)

    handler = _bare_handler()
    response = await handler._cmd_engineering("chat-1", "ready to work?")

    assert not spawn_calls, "readiness must not spawn Claude"
    assert "Zone 3" in response


async def test_cross_zone_handoff_does_not_invoke_executor(monkeypatch) -> None:
    """A QA-coverage ask produces a handoff, not an executor spawn."""
    spawn_calls: list[object] = []

    async def fake_spawn(argv, *, cwd, env):
        spawn_calls.append(argv)
        return _FakeProc()

    import zone3.claude_p_executor as cpe

    real_init = cpe.ClaudePExecutor.__init__

    def patched_init(self, *, claude_binary="claude", model=None, spawn=None):
        real_init(self, claude_binary=claude_binary, model=model, spawn=fake_spawn)

    monkeypatch.setattr(cpe.ClaudePExecutor, "__init__", patched_init)

    handler = _bare_handler()
    response = await handler._cmd_engineering(
        "chat-1", "verify this needs broader QA coverage"
    )

    assert not spawn_calls
    assert "handoff" in response.lower()
    assert "qa" in response.lower()


async def test_falls_back_to_workorder_when_dispatcher_unavailable(monkeypatch) -> None:
    """If the EngineeringDispatcher can't be built, fall back gracefully.

    When _build_engineering_dispatcher returns None AND no legacy _dispatcher
    is wired, the handler delegates to _cmd_dispatch — never crashes.
    """
    handler = _bare_handler()
    monkeypatch.setattr(handler, "_build_engineering_dispatcher", lambda: None)

    called: list[str] = []

    async def fake_cmd_dispatch(chat_id: str, task: str) -> str:
        called.append(task)
        return "fell back to /dispatch"

    monkeypatch.setattr(handler, "_cmd_dispatch", fake_cmd_dispatch)

    response = await handler._cmd_engineering("chat-1", "review the latest diff")

    assert called == ["review the latest diff"]
    assert response == "fell back to /dispatch"
