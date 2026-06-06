"""P1.03 — dispatch-time capability guard.

resolve_backend_for_dispatch resolves + capability-checks the backend for a
dispatch via require_capabilities (P1.02), emits a loud operator-facing ERROR
log on mismatch, and re-raises CapabilityError — the fail-loud boundary that
prevents a silent misroute. The seam is dormant until backends_enabled flips.
"""
from __future__ import annotations

import logging

import pytest

from bridge.backends import BackendProtocol
from bridge.backends._errors import CapabilityError
from bridge.backends._protocol import StreamEvent
from bridge.backends.dispatch_guard import resolve_backend_for_dispatch
from bridge.backends.registry import BackendRegistry


class _Cfg:
    backends_main = "claude"
    backends_chiefs_default = "claude"
    backends_specialists_default = "codex"
    backends_specialists_overrides: dict[str, str] = {}


class _FakeBackend:
    def __init__(self, *, transport: str = "subprocess", **caps: bool) -> None:
        self._transport = transport
        self._caps = caps

    @property
    def transport(self) -> str:
        return self._transport

    def resolve_binary(self) -> str:
        return "/bin/fake"

    def build_command(self, **kw) -> list[str]:  # noqa: ANN003 — test fake
        return ["/bin/fake"]

    def parse_event(self, line: str) -> StreamEvent | None:
        return None

    def parse_cost(self, event):
        from bridge.cost_tracker import CostMeasurement

        return CostMeasurement(source="not_applicable", amount_usd=None)

    def auth_env(self) -> dict[str, str]:
        return {}

    def shutdown(self) -> None:
        return None

    def supports_tool_calling(self) -> bool:
        return self._caps.get("tool_calling", True)

    def supports_system_prompt(self) -> bool:
        return self._caps.get("system_prompt", True)

    def supports_mcp_config(self) -> bool:
        return self._caps.get("mcp_config", True)

    def supports_tool_preauth(self) -> bool:
        return self._caps.get("tool_preauth", True)


def _registry() -> BackendRegistry:
    claude = _FakeBackend()
    codex = _FakeBackend(mcp_config=False, system_prompt=False, tool_preauth=False)
    assert isinstance(claude, BackendProtocol)
    assert isinstance(codex, BackendProtocol)
    return BackendRegistry(
        _Cfg(),
        {
            "claude": claude,
            "codex": codex,
        },
    )


class _OpenRouterCfg:
    backends_main = "openrouter"
    backends_chiefs_default = "openrouter"
    backends_specialists_default = "openrouter"
    backends_specialists_overrides: dict[str, str] = {}


def _openrouter_registry() -> BackendRegistry:
    openrouter = _FakeBackend(
        transport="http",
        tool_calling=False,
        mcp_config=False,
        system_prompt=False,
        tool_preauth=False,
    )
    claude = _FakeBackend()
    assert isinstance(openrouter, BackendProtocol)
    assert isinstance(claude, BackendProtocol)
    return BackendRegistry(
        _OpenRouterCfg(),
        {
            "openrouter": openrouter,
            "claude": claude,
        },
    )


def test_dispatch_guard_returns_backend_when_capable():
    reg = _registry()
    backend = resolve_backend_for_dispatch(
        reg, agent_role="main", required=["tool_calling", "mcp_config"]
    )
    assert backend is reg.resolve("main")


def test_dispatch_guard_raises_and_logs_loud(caplog):
    reg = _registry()
    with caplog.at_level(logging.ERROR):
        with pytest.raises(CapabilityError) as exc:
            resolve_backend_for_dispatch(
                reg,
                agent_role="specialist",
                required=["mcp_config"],
                specialist="code-reviewer",
            )
    # The CapabilityError must propagate (fail loud, never silent misroute)…
    assert "codex" in str(exc.value)
    assert "mcp_config" in str(exc.value)
    # …and a loud operator-facing ERROR log line must be emitted at the seam.
    assert any(
        record.levelno == logging.ERROR
        and "codex" in record.getMessage()
        and "mcp_config" in record.getMessage()
        for record in caplog.records
    )


def test_dispatch_guard_propagates_value_error_for_bad_capability():
    reg = _registry()
    with pytest.raises(ValueError):
        resolve_backend_for_dispatch(reg, agent_role="main", required=["nope"])


def test_dispatch_guard_allows_openrouter_text_only_matrix_route():
    reg = _openrouter_registry()

    backend = resolve_backend_for_dispatch(reg, agent_role="main", required=[])

    assert backend is reg.resolve("main")
    assert backend.transport == "http"


@pytest.mark.parametrize(
    ("agent_role", "required", "specialist", "expected_missing"),
    [
        (
            "main",
            ["tool_calling", "mcp_config"],
            None,
            {"tool_calling", "mcp_config"},
        ),
        (
            "chief",
            ["tool_calling"],
            None,
            {"tool_calling"},
        ),
        (
            "specialist",
            ["tool_calling", "mcp_config", "tool_preauth"],
            "code-reviewer",
            {"tool_calling", "mcp_config", "tool_preauth"},
        ),
    ],
)
def test_dispatch_guard_blocks_openrouter_tool_required_matrix_routes(
    agent_role: str,
    required: list[str],
    specialist: str | None,
    expected_missing: set[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    reg = _openrouter_registry()

    with caplog.at_level(logging.ERROR):
        with pytest.raises(CapabilityError) as exc:
            resolve_backend_for_dispatch(
                reg,
                agent_role=agent_role,
                required=required,
                specialist=specialist,
            )

    assert exc.value.backend_name == "openrouter"
    assert exc.value.agent_role == agent_role
    assert set(exc.value.missing) == expected_missing
    assert any(
        record.levelno == logging.ERROR
        and "openrouter" in record.getMessage()
        and "CAPABILITY MISROUTE BLOCKED" in record.getMessage()
        for record in caplog.records
    )
