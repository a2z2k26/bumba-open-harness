"""Protocol contract tests for ``bridge.backends.BackendProtocol``.

Codex-1 (#1835): exercises the structural Protocol surface via a stub
backend so we know the interface is satisfiable without coupling to a
specific implementation. Each test asserts one observable: the stub
satisfies ``isinstance(stub, BackendProtocol)`` at runtime (Protocol is
``@runtime_checkable``), the six methods are callable with the spec
signatures, and ``StreamEvent`` round-trips through ``parse_event``.
"""

from __future__ import annotations

import pytest

from bridge.backends import BackendProtocol, ClaudeBackend, StreamEvent
from bridge.backends._protocol import BackendProtocol as ProtocolDirect
from bridge.cost_tracker import CostMeasurement


class StubBackend:
    """Minimal in-memory backend satisfying ``BackendProtocol`` structurally.

    Captures call arguments for assertion without spawning any subprocess.
    Used to exercise the protocol contract independent of ``ClaudeBackend``.
    """

    def __init__(self, binary: str = "/stub/bin/echo") -> None:
        self._binary = binary
        self._shutdown_called = False
        self.last_build_kwargs: dict = {}

    # P3.01 transport discriminator — required for @runtime_checkable
    # conformance now that BackendProtocol declares it.
    @property
    def transport(self) -> str:
        return "subprocess"

    def resolve_binary(self) -> str | list[str]:
        return self._binary

    def build_command(
        self,
        *,
        message: str,
        session_id: str | None = None,
        system_prompt_file: str | None = None,
        model: str | None = None,
        mcp_config_path: str | None = None,
        permission_mode: str = "bypassPermissions",
    ) -> list[str]:
        self.last_build_kwargs = {
            "message": message,
            "session_id": session_id,
            "system_prompt_file": system_prompt_file,
            "model": model,
            "mcp_config_path": mcp_config_path,
            "permission_mode": permission_mode,
        }
        return [self._binary, "--message", message]

    def parse_event(self, line: str) -> StreamEvent | None:
        line = line.strip()
        if not line:
            return None
        ev = StreamEvent()
        ev.type = "stub"
        ev.text = line
        return ev

    def parse_cost(self, event: dict[str, object]) -> CostMeasurement:
        event_id = event.get("id")
        return CostMeasurement(
            amount_usd=None,
            source="not_applicable",
            backend="stub",
            raw_usage_id=event_id if isinstance(event_id, str) else None,
        )

    def auth_env(self) -> dict[str, str]:
        return {"STUB_API_KEY": "stub"}

    def shutdown(self) -> None:
        self._shutdown_called = True

    # P1.01 capability methods — required for @runtime_checkable conformance
    # now that BackendProtocol declares them.
    def supports_tool_calling(self) -> bool:
        return True

    def supports_system_prompt(self) -> bool:
        return True

    def supports_mcp_config(self) -> bool:
        return True

    def supports_tool_preauth(self) -> bool:
        return True


class TestProtocolContract:
    """The protocol surface (six core + four capability methods, P1.01) must
    be callable on any conforming backend."""

    def test_stub_satisfies_protocol_runtime(self) -> None:
        stub = StubBackend()
        assert isinstance(stub, BackendProtocol)
        # The Protocol object imported via __init__ and ._protocol must be
        # the same identity — not a re-defined shadow.
        assert BackendProtocol is ProtocolDirect

    def test_resolve_binary_returns_str_or_list(self) -> None:
        stub = StubBackend("/stub/bin/echo")
        assert stub.resolve_binary() == "/stub/bin/echo"

        list_stub = StubBackend()
        list_stub._binary = ["/usr/bin/python3", "/path/to/shim.py"]
        result = list_stub.resolve_binary()
        assert isinstance(result, list)
        assert result == ["/usr/bin/python3", "/path/to/shim.py"]

    def test_build_command_keyword_only_signature(self) -> None:
        stub = StubBackend()
        cmd = stub.build_command(
            message="hello",
            session_id="sess-1",
            system_prompt_file=None,
            model="haiku",
            mcp_config_path=None,
            permission_mode="bypassPermissions",
        )
        assert "hello" in cmd
        # All six kwargs captured (defaults populate the rest)
        assert stub.last_build_kwargs["message"] == "hello"
        assert stub.last_build_kwargs["session_id"] == "sess-1"
        assert stub.last_build_kwargs["model"] == "haiku"
        assert stub.last_build_kwargs["permission_mode"] == "bypassPermissions"

    def test_build_command_rejects_positional_kwargs(self) -> None:
        """Keyword-only enforcement: positional args other than ``message``
        must raise. Guards future backends from collapsing the kwargs."""
        stub = StubBackend()
        with pytest.raises(TypeError):
            stub.build_command("hello", "sess-1")  # type: ignore[misc]

    def test_parse_event_returns_stream_event_or_none(self) -> None:
        stub = StubBackend()
        ev = stub.parse_event("payload")
        assert ev is not None
        assert isinstance(ev, StreamEvent)
        assert ev.type == "stub"
        assert ev.text == "payload"

        assert stub.parse_event("") is None
        assert stub.parse_event("   ") is None

    def test_parse_cost_returns_cost_measurement(self) -> None:
        stub = StubBackend()
        measurement = stub.parse_cost({"id": "evt-1"})
        assert measurement == CostMeasurement(
            amount_usd=None,
            source="not_applicable",
            backend="stub",
            raw_usage_id="evt-1",
        )

    def test_auth_env_returns_dict(self) -> None:
        stub = StubBackend()
        env = stub.auth_env()
        assert isinstance(env, dict)
        assert env == {"STUB_API_KEY": "stub"}

    def test_shutdown_callable_no_return(self) -> None:
        stub = StubBackend()
        assert stub.shutdown() is None
        assert stub._shutdown_called is True


class TestClaudeBackendConformance:
    """ClaudeBackend itself must satisfy the protocol at runtime."""

    def test_claude_backend_satisfies_protocol(self, sample_config) -> None:
        backend = ClaudeBackend(sample_config)
        assert isinstance(backend, BackendProtocol)

    def test_claude_backend_methods_callable(self, sample_config, monkeypatch) -> None:
        backend = ClaudeBackend(sample_config)
        # auth_env: Claude returns empty (auth flows via .secrets +
        # CLAUDE_CODE_OAUTH_TOKEN injected by the runner)
        assert backend.auth_env() == {}
        # shutdown: no-op
        assert backend.shutdown() is None
        # parse_event: empty line yields None (no malformed-JSON warning)
        assert backend.parse_event("") is None


class TestStreamEventShape:
    """``StreamEvent`` must remain a no-arg-instantiable dataclass.

    The protocol exposes ``StreamEvent`` as the shared return shape; tests
    construct it directly in many places (test_claude_runner.py:_process_events
    fixtures). All fields must have defaults so ``StreamEvent()`` is valid.
    """

    def test_default_construction(self) -> None:
        ev = StreamEvent()
        assert ev.type == ""
        assert ev.subtype == ""
        assert ev.text == ""
        assert ev.tool_name == ""
        assert ev.tool_names == []
        assert ev.session_id == ""
        assert ev.cost_usd == 0.0
        assert ev.num_turns == 0
        assert ev.is_error is False
        assert ev.duration_ms == 0

    def test_tool_names_is_per_instance_list(self) -> None:
        """Regression: ``tool_names`` uses ``field(default_factory=list)`` so
        each instance gets its own list. Catches the classic mutable-default
        bug if a future refactor accidentally inlines ``= []``."""
        a = StreamEvent()
        b = StreamEvent()
        a.tool_names.append("tool-a")
        assert b.tool_names == []
