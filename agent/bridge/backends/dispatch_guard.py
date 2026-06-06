"""Dispatch-time capability guard.

Phase 1 / D2 (capability honesty): the thin seam the dispatch path calls when
``backends_enabled`` is live. It resolves the backend for a role and asserts
the requested capabilities via ``BackendRegistry.require_capabilities``
(P1.02), and — on failure — emits a loud operator-facing ERROR log line BEFORE
re-raising the ``CapabilityError``. This is the fail-loud boundary that
prevents a silent misroute (e.g. a tool-requiring turn landing on Codex, whose
mcp_config/system_prompt/tool_preauth flags are no-ops at codex.py:378-390).

Co-located with the registry (not at the call site) so the loud-error contract
has a single home, mirroring the boot-time validator pattern in
``bridge.app._validate_codex_oauth``.
"""

from __future__ import annotations

import logging

from ._errors import CapabilityError
from ._protocol import BackendProtocol
from .registry import BackendRegistry

logger = logging.getLogger(__name__)


def resolve_backend_for_dispatch(
    registry: BackendRegistry,
    *,
    agent_role: str,
    required: list[str],
    specialist: str | None = None,
) -> BackendProtocol:
    """Resolve + capability-check the backend for a dispatch.

    Returns the capable ``BackendProtocol`` on success. On a capability
    mismatch, logs a loud ERROR (so the failure is visible in the operator's
    bridge-stderr log even if the caller swallows the exception) and re-raises
    the ``CapabilityError`` — the runtime never silently misroutes.

    Raises:
        ValueError: a name in ``required`` is not a known capability (from
            ``require_capabilities``).
        CapabilityError: the resolved backend lacks a requested capability.
    """
    try:
        return registry.require_capabilities(
            agent_role, required, specialist=specialist
        )
    except CapabilityError as err:
        logger.error(
            "CAPABILITY MISROUTE BLOCKED: backend %r (role=%r, specialist=%r) "
            "missing %s — required %s. Refusing dispatch (fail-loud, D2).",
            err.backend_name,
            err.agent_role,
            specialist,
            sorted(err.missing),
            sorted(err.required),
        )
        raise
