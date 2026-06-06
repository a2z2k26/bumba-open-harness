"""Backend capability errors.

Phase 1 / D2 (capability honesty): ``CapabilityError`` is raised when a caller
routes work that needs a capability to a resolved backend that lacks it. The
runtime fails loud here instead of silently no-op'ing the flag (the Codex
build_command no-op pattern at codex.py:378-390 is exactly what this prevents
from misrouting silently).
"""

from __future__ import annotations


class CapabilityError(RuntimeError):
    """Raised when a resolved backend lacks a capability the caller requires.

    Carries the structured fields so a loud operator-facing message can be
    assembled at the dispatch boundary (P1.03) without re-parsing the string.
    """

    def __init__(
        self,
        *,
        agent_role: str,
        backend_name: str,
        missing: list[str],
        required: list[str],
    ) -> None:
        self.agent_role = agent_role
        self.backend_name = backend_name
        # Immutable snapshots — never alias the caller's lists.
        self.missing = tuple(missing)
        self.required = tuple(required)
        super().__init__(
            f"Backend {backend_name!r} (resolved for agent_role "
            f"{agent_role!r}) lacks required capabilities {sorted(self.missing)}; "
            f"caller requested {sorted(self.required)}. Route this work to a "
            f"capable backend or change [backends] policy — refusing to "
            f"silently no-op the unsupported flags."
        )
