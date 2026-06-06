"""BackendRegistry — agent_role → BackendProtocol resolver.

Codex-3 (issue #1837): runtime policy layer mapping an agent's role (main,
chief, specialist) to a backend implementation. Operator policy lives in
``[backends]`` of bridge.toml; this class is the read-side that ``ClaudeRunner``
(or its successor) consults at dispatch time.

Dormant until ``backends_enabled`` feature flag flips (default false). The
registry is constructed at boot but never consulted while the flag is off —
the legacy ClaudeRunner code path remains live.

Resolution rules (per spec):

    agent_role == "main"        → config.backends_main
    agent_role == "chief"       → config.backends_chiefs_default
    agent_role == "specialist"  → config.backends_specialists_overrides[specialist]
                                  or config.backends_specialists_default
    else                        → ValueError

If the resolved backend name is not registered in the instances dict, the
resolver raises ``KeyError`` naming both the role and the missing backend so
the caller can surface a clear error to the operator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._errors import CapabilityError
from ._protocol import BackendProtocol

if TYPE_CHECKING:
    from ..config import BridgeConfig


class BackendRegistry:
    """Read-only resolver from ``agent_role`` to a ``BackendProtocol`` instance.

    Constructed once at bridge boot from the operator's ``[backends]`` policy
    and the dict of backend instances (typically ``{"claude": ClaudeBackend(...),
    "codex": CodexBackend(...)}``). The resolver does not own instance
    lifecycle — backends are constructed and shut down by their owners; the
    registry only holds references.

    The registry takes a defensive copy of the instances dict on construction
    to satisfy the immutability invariant in the project's coding-style rules.
    """

    def __init__(
        self,
        config: BridgeConfig,
        backend_instances: dict[str, BackendProtocol],
    ) -> None:
        self._config = config
        # Defensive copy — caller cannot mutate the registry post-construction
        # by mutating the original dict they passed in.
        self._instances: dict[str, BackendProtocol] = dict(backend_instances)

    def resolve(
        self,
        agent_role: str,
        specialist: str | None = None,
    ) -> BackendProtocol:
        """Return the ``BackendProtocol`` for ``agent_role``.

        ``specialist`` is only consulted when ``agent_role == "specialist"``;
        it names the specific specialist (e.g. ``"code-reviewer"``) so the
        registry can honor per-specialist overrides from
        ``config.backends_specialists_overrides``.

        Raises:
            ValueError: ``agent_role`` is not one of {"main", "chief",
                "specialist"}.
            KeyError: the resolved backend name is not registered in the
                instances dict. The error message names both the role and the
                missing backend so callers can surface it to the operator.
        """
        if agent_role == "main":
            backend_name = self._config.backends_main
        elif agent_role == "chief":
            backend_name = self._config.backends_chiefs_default
        elif agent_role == "specialist":
            overrides = self._config.backends_specialists_overrides
            backend_name = overrides.get(
                specialist or "",
                self._config.backends_specialists_default,
            )
        else:
            raise ValueError(f"Unknown agent_role: {agent_role!r}")

        if backend_name not in self._instances:
            raise KeyError(
                f"Backend {backend_name!r} not registered for agent_role "
                f"{agent_role!r}; registered backends: "
                f"{sorted(self._instances.keys())}"
            )
        return self._instances[backend_name]

    # Capability methods every BackendProtocol exposes (P1.01). The guard
    # maps a requested capability name to the predicate method on the backend.
    _CAPABILITY_METHODS = {
        "tool_calling": "supports_tool_calling",
        "system_prompt": "supports_system_prompt",
        "mcp_config": "supports_mcp_config",
        "tool_preauth": "supports_tool_preauth",
    }

    def require_capabilities(
        self,
        agent_role: str,
        required: list[str],
        specialist: str | None = None,
    ) -> BackendProtocol:
        """Resolve ``agent_role`` and assert it supports every capability in
        ``required``, else raise ``CapabilityError``.

        Returns the resolved ``BackendProtocol`` on success so call sites can
        ``backend = registry.require_capabilities(role, [...])`` in one step.

        Raises:
            ValueError: a name in ``required`` is not a known capability
                (typo guard — fail loud rather than silently ignore).
            CapabilityError: the resolved backend reports False for one or
                more requested capabilities.
        """
        unknown = [c for c in required if c not in self._CAPABILITY_METHODS]
        if unknown:
            raise ValueError(
                f"Unknown capability name(s): {sorted(unknown)}; "
                f"valid: {sorted(self._CAPABILITY_METHODS)}"
            )
        backend = self.resolve(agent_role, specialist=specialist)
        missing = [
            cap
            for cap in required
            if not getattr(backend, self._CAPABILITY_METHODS[cap])()
        ]
        if missing:
            # Re-derive the resolved backend name for the error (resolve()
            # already validated it is registered).
            backend_name = next(
                name for name, inst in self._instances.items() if inst is backend
            )
            raise CapabilityError(
                agent_role=agent_role,
                backend_name=backend_name,
                missing=missing,
                required=required,
            )
        return backend
