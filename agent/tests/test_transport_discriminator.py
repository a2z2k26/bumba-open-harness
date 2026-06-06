"""P3.01 — transport discriminator on BackendProtocol + CLI backends.

Adds a ``transport`` member to BackendProtocol so HTTP vs subprocess backends
can be told apart without an isinstance-by-concrete-class check. Both CLI
backends (Claude, Codex) report "subprocess"; the HTTP backend added in P3.02
will report "http".

runtime_checkable note (spec gap fixed here): the original issue implemented
``transport`` on ClaudeBackend ONLY. Because BackendProtocol is
@runtime_checkable and matches by member name, adding ``transport`` to the
Protocol drops CodexBackend (and any stub lacking it) out of the isinstance
check. This sprint therefore implements ``transport`` on BOTH CLI backends and
updates the stub fixtures — verified by the both-backends conformance test.

Placed flat (tests/test_transport_discriminator.py); no tests/test_backends/
package exists in the tree.
"""
from __future__ import annotations

from bridge.backends._protocol import BackendProtocol
from bridge.backends.claude import ClaudeBackend
from bridge.backends.codex import CodexBackend


class _StubConfig:
    claude_binary = ""
    codex_binary = ""
    claude_output_format = "stream-json"
    claude_max_turns = 30
    security_disallowed_tools: list[str] = []


def test_protocol_declares_transport_member() -> None:
    assert "transport" in BackendProtocol.__annotations__ or hasattr(
        BackendProtocol, "transport"
    )


def test_claude_backend_reports_subprocess_transport() -> None:
    backend = ClaudeBackend(_StubConfig())  # type: ignore[arg-type]
    assert backend.transport == "subprocess"


def test_codex_backend_reports_subprocess_transport() -> None:
    backend = CodexBackend(_StubConfig())  # type: ignore[arg-type]
    assert backend.transport == "subprocess"


def test_both_cli_backends_still_satisfy_protocol() -> None:
    # runtime_checkable matches by member name; adding `transport` must NOT
    # drop either CLI backend out of the structural check.
    assert isinstance(ClaudeBackend(_StubConfig()), BackendProtocol)  # type: ignore[arg-type]
    assert isinstance(CodexBackend(_StubConfig()), BackendProtocol)  # type: ignore[arg-type]
