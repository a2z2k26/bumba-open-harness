"""P1.01 — backend capability methods.

Adds four capability-signalling methods to BackendProtocol so a router can
ask a backend whether a capability is REAL before sending tool-requiring work
to it. ClaudeBackend honours all four (its build_command emits the matching
flags); CodexBackend can call tools but treats system_prompt_file /
mcp_config_path / allowed_tools as no-ops, so it reports those False — the
capability-honesty the sprint exists to surface.

runtime_checkable note: adding methods to the @runtime_checkable Protocol
means BOTH concrete backends must implement all four or the isinstance check
regresses to False. The isinstance assertions below lock that in.
"""
from __future__ import annotations

from bridge.backends._protocol import BackendProtocol
from bridge.backends.claude import ClaudeBackend
from bridge.backends.codex import CodexBackend


class _StubConfig:
    """Minimal config stand-in — backends read these attrs lazily."""

    claude_binary = ""
    codex_binary = ""
    claude_output_format = "stream-json"
    claude_max_turns = 20
    security_disallowed_tools: list[str] = []


_CAP_METHODS = (
    "supports_tool_calling",
    "supports_system_prompt",
    "supports_mcp_config",
    "supports_tool_preauth",
)


def test_protocol_declares_capability_methods():
    for name in _CAP_METHODS:
        assert hasattr(BackendProtocol, name), f"missing protocol method {name}"


def test_claude_backend_all_capabilities_true():
    backend = ClaudeBackend(_StubConfig())
    assert backend.supports_tool_calling() is True
    assert backend.supports_system_prompt() is True
    assert backend.supports_mcp_config() is True
    assert backend.supports_tool_preauth() is True
    assert isinstance(backend, BackendProtocol)


def test_codex_backend_capability_honesty():
    backend = CodexBackend(_StubConfig())
    # Codex CAN call tools (bash/edit/mcp surface in its stream parser), but
    # build_command treats system_prompt_file / mcp_config_path / allowed_tools
    # as no-ops — those must report False.
    assert backend.supports_tool_calling() is True
    assert backend.supports_system_prompt() is False
    assert backend.supports_mcp_config() is False
    assert backend.supports_tool_preauth() is False
    assert isinstance(backend, BackendProtocol)


def test_both_backends_still_satisfy_protocol_after_adding_methods():
    """Regression guard for the runtime_checkable gotcha: a backend missing
    any capability method would fail isinstance. Both must still pass."""
    assert isinstance(ClaudeBackend(_StubConfig()), BackendProtocol)
    assert isinstance(CodexBackend(_StubConfig()), BackendProtocol)
