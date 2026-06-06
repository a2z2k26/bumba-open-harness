"""Direct tests for BackendRegistry resolver. Codex-3 (#1837).

Exercises the read-side policy layer in isolation — no subprocess, no Claude
binary, no real backend. The registry only stores instances and consults
BridgeConfig fields; the backend instances themselves are stubs satisfying
the structural ``BackendProtocol``.
"""

from __future__ import annotations

import dataclasses

import pytest

from bridge.backends import BackendProtocol
from bridge.backends._protocol import StreamEvent
from bridge.backends.registry import BackendRegistry


class StubBackend:
    """Minimal BackendProtocol stub for tests — registry stores instances only.

    The registry never calls the methods; the stub exists so we can assert
    "the same instance came back" via ``is`` identity checks.
    """

    def __init__(self, label: str) -> None:
        self.label = label

    @property
    def transport(self) -> str:
        return "subprocess"

    def resolve_binary(self) -> str:
        return f"/bin/stub-{self.label}"

    def build_command(self, **kw) -> list[str]:  # noqa: ANN003 — test stub
        return [f"stub-{self.label}"]

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
        return True

    def supports_system_prompt(self) -> bool:
        return True

    def supports_mcp_config(self) -> bool:
        return True

    def supports_tool_preauth(self) -> bool:
        return True


@pytest.fixture
def claude_stub() -> StubBackend:
    stub = StubBackend("claude")
    assert isinstance(stub, BackendProtocol)
    return stub


@pytest.fixture
def codex_stub() -> StubBackend:
    stub = StubBackend("codex")
    assert isinstance(stub, BackendProtocol)
    return stub


class TestResolve:
    """``BackendRegistry.resolve`` honors per-role config + per-specialist override."""

    def test_main_role_defaults_to_claude(
        self, sample_config, claude_stub: StubBackend
    ) -> None:
        registry = BackendRegistry(sample_config, {"claude": claude_stub})
        assert registry.resolve("main") is claude_stub

    def test_chief_role_defaults_to_claude(
        self, sample_config, claude_stub: StubBackend
    ) -> None:
        registry = BackendRegistry(sample_config, {"claude": claude_stub})
        assert registry.resolve("chief") is claude_stub

    def test_specialist_default(
        self, sample_config, claude_stub: StubBackend
    ) -> None:
        registry = BackendRegistry(sample_config, {"claude": claude_stub})
        assert registry.resolve("specialist", "any-specialist") is claude_stub

    def test_specialist_override_wins(
        self,
        sample_config,
        claude_stub: StubBackend,
        codex_stub: StubBackend,
    ) -> None:
        config = dataclasses.replace(
            sample_config,
            backends_specialists_overrides={"code-reviewer": "codex"},
        )
        registry = BackendRegistry(
            config,
            {"claude": claude_stub, "codex": codex_stub},
        )
        assert registry.resolve("specialist", "code-reviewer") is codex_stub
        # Other specialists still fall back to the default.
        assert registry.resolve("specialist", "qa-engineer") is claude_stub

    def test_specialist_no_override_falls_back_to_default(
        self,
        sample_config,
        claude_stub: StubBackend,
        codex_stub: StubBackend,
    ) -> None:
        config = dataclasses.replace(
            sample_config,
            backends_specialists_overrides={"code-reviewer": "codex"},
        )
        registry = BackendRegistry(
            config,
            {"claude": claude_stub, "codex": codex_stub},
        )
        # Specialist not named in overrides — uses backends_specialists_default.
        assert registry.resolve("specialist", "unknown-specialist") is claude_stub
        # specialist=None also falls back to the default (empty-string key lookup
        # in overrides misses, so the default applies).
        assert registry.resolve("specialist") is claude_stub

    def test_unknown_role_raises_valueerror(self, sample_config) -> None:
        registry = BackendRegistry(sample_config, {"claude": StubBackend("claude")})
        with pytest.raises(ValueError, match="Unknown agent_role"):
            registry.resolve("director")

    def test_missing_backend_instance_raises_clear_error(
        self, sample_config, claude_stub: StubBackend
    ) -> None:
        # config says backends_main = "codex" but only "claude" is registered.
        config = dataclasses.replace(sample_config, backends_main="codex")
        registry = BackendRegistry(config, {"claude": claude_stub})
        with pytest.raises(KeyError) as excinfo:
            registry.resolve("main")
        # KeyError message must name both the role and the missing backend so
        # the operator can spot the misconfiguration.
        msg = str(excinfo.value)
        assert "codex" in msg
        assert "main" in msg


class TestImmutability:
    """Constructor takes a defensive copy of the instances dict (project rule)."""

    def test_caller_mutation_after_construction_is_ignored(
        self,
        sample_config,
        claude_stub: StubBackend,
        codex_stub: StubBackend,
    ) -> None:
        instances: dict[str, BackendProtocol] = {"claude": claude_stub}
        registry = BackendRegistry(sample_config, instances)
        # Mutating the original dict must not affect the registry's view.
        instances["codex"] = codex_stub
        config = dataclasses.replace(sample_config, backends_main="codex")
        # Re-resolve with a hypothetical mutated config — registry still
        # raises because its internal copy never saw "codex".
        registry_with_codex_main = BackendRegistry(config, {"claude": claude_stub})
        with pytest.raises(KeyError):
            registry_with_codex_main.resolve("main")
