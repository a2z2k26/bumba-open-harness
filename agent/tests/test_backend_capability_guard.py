"""P1.02 — BackendRegistry.require_capabilities guard + CapabilityError.

The guard resolves an agent_role and asserts the backend supports every
requested capability (the P1.01 predicate methods), else raises
CapabilityError — failing loud instead of silently no-op'ing unsupported
flags (the Codex build_command no-op pattern). Wiring into dispatch is P1.03.

Placed as a flat tests/test_backend_capability_guard.py (the repo's backend
tests are flat; no tests/test_backends/ package exists).
"""
from __future__ import annotations

import pytest

from bridge.backends import BackendProtocol
from bridge.backends._errors import CapabilityError
from bridge.backends._protocol import StreamEvent
from bridge.backends.registry import BackendRegistry


class _Cfg:
    backends_main = "claude"
    backends_chiefs_default = "claude"
    backends_specialists_default = "codex"
    backends_specialists_overrides: dict[str, str] = {}


class _FakeBackend:
    """Structural backend stub — only the capability methods matter here."""

    def __init__(self, **caps: bool) -> None:
        self._caps = caps

    @property
    def transport(self) -> str:
        return "subprocess"

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
            "claude": claude,  # all True
            "codex": codex,
        },
    )


def test_require_capabilities_passes_for_capable_backend():
    reg = _registry()
    backend = reg.require_capabilities("main", ["tool_calling", "mcp_config"])
    assert backend is reg.resolve("main")


def test_require_capabilities_raises_for_missing_capability():
    reg = _registry()
    with pytest.raises(CapabilityError) as exc:
        reg.require_capabilities("specialist", ["mcp_config"], specialist="code-reviewer")
    msg = str(exc.value)
    assert "codex" in msg
    assert "mcp_config" in msg
    assert "specialist" in msg


def test_require_capabilities_reports_all_missing():
    reg = _registry()
    with pytest.raises(CapabilityError) as exc:
        reg.require_capabilities("specialist", ["system_prompt", "tool_preauth", "tool_calling"])
    # Check the structured `missing` field, not the rendered string — the
    # message echoes `required` (which includes tool_calling), so a substring
    # check would be a false positive. tool_calling is SUPPORTED, so it must
    # not appear in `missing`.
    assert set(exc.value.missing) == {"system_prompt", "tool_preauth"}
    assert "tool_calling" not in exc.value.missing


def test_require_capabilities_rejects_unknown_capability_name():
    reg = _registry()
    with pytest.raises(ValueError):
        reg.require_capabilities("main", ["teleportation"])


def test_capability_error_carries_structured_fields():
    """P1.03 will assemble its operator message from these fields without
    re-parsing the string — lock the contract."""
    err = CapabilityError(
        agent_role="specialist",
        backend_name="codex",
        missing=["mcp_config"],
        required=["mcp_config", "tool_calling"],
    )
    assert err.agent_role == "specialist"
    assert err.backend_name == "codex"
    assert err.missing == ("mcp_config",)
    assert err.required == ("mcp_config", "tool_calling")
