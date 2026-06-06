"""Warm-session isolation policy (Sprint P1.3, #1571).

This module defines the single decision function
``should_use_warm_path()`` that gates whether a given message may be
serviced by the persistent warm Claude process or must spawn a fresh
one-shot subprocess.

Background
----------
Pre-P1.3, the bridge used the warm process for every non-opus message
whenever the warm process was alive. That blends conversations across
sessions through a single persistent Claude context, which is a
mid-conversation context-bleed safety boundary that the 2026-05-11
harness audit flagged as high-risk for tool-bearing / workorder /
code-mutation paths.

The audit-plan offered three options. The operator chose **Option C**:

  > warm only for low-risk chat, one-shot for task/workorder/file-change
  > paths.

Rationale (per ``02-phase-based-sprint-plan.md``): Option C addresses the
actual safety boundary without forcing a multi-sprint warm-process-pool
migration. It keeps the warm-path performance win for the dominant
short-conversational traffic shape. Option A (one warm per session) is a
follow-up if latency requires it.

Critical fail-safe (operator-mandated)
--------------------------------------
If intent classification fails or returns ``None``, the policy returns
``False`` — i.e. **falls through to one-shot, NOT warm**. The dangerous
default would be "we couldn't classify so we defaulted to warm" — we
explicitly reject that. Unknown == treat as risky.

Decision tree
-------------
The function returns ``False`` (use one-shot) for any of:

1. ``model in {"opus", CAREFUL_OPUS_MODEL}`` — opus already routes to
   one-shot; preserved here so the policy is the single source of truth.
2. ``is_workorder`` — workorders carry structured task semantics; never
   blend with the global warm conversation.
3. ``has_tools`` — when the message expects tool use, the warm process's
   per-spawn MCP surface may differ from what the message needs; use
   one-shot to get the right tool surface per message.
4. ``intent is None`` — fail-safe to one-shot (operator-mandated).
5. ``intent in HIGH_RISK_INTENTS`` — code / deploy / security paths
   that mutate state must not blend mid-conversation context.

Otherwise the warm path is permitted.

Pure function: no side effects, no global state, no logging.
"""

from __future__ import annotations

from .model_router import CAREFUL_OPUS_MODEL

# ---------------------------------------------------------------------------
# High-risk intent set
# ---------------------------------------------------------------------------
#
# The audit-plan sketch uses literal strings ``{"code", "deploy",
# "security", "job_search_execute"}`` — these are *aspirational labels*
# the operator named in the spec. The current production intent classifier
# (``bridge.command_router.Intent``) emits a slightly different vocabulary
# (``build``, ``fix``, ``optimize``, ``deploy``, ``ops_diagnose``, etc.).
#
# We include BOTH so the policy is correct against the running classifier
# today AND remains correct if a future classifier emits the audit-plan's
# literal labels.
#
# To extend: append new intent strings here. The set is frozen so callers
# can't mutate it.
# ---------------------------------------------------------------------------
HIGH_RISK_INTENTS: frozenset[str] = frozenset({
    # Audit-plan literal set (operator-mandated names; spec verbatim)
    "code",
    "deploy",
    "security",
    "job_search_execute",
    # Current ``bridge.command_router.Intent`` values that map to these
    # concepts today. Code-mutating intents:
    "build",     # implement / new code
    "fix",       # bug-fix / modify code
    "optimize",  # refactor / modify code
    # Department intents that are security / ops sensitive:
    "ops_diagnose",  # ops / security investigations
})

# Opus models always go one-shot regardless of intent.
# Sourced from ``bridge.model_router`` so we have a single definition.
_OPUS_MODELS: frozenset[str] = frozenset({"opus", CAREFUL_OPUS_MODEL})


def should_use_warm_path(
    *,
    model: str,
    intent: str | None,
    has_tools: bool,
    is_workorder: bool,
) -> bool:
    """Return True iff the message is safe to serve via the warm process.

    Args:
        model: Resolved model tier name (``"haiku"``, ``"sonnet"``,
            ``"opus"``, or the literal ``CAREFUL_OPUS_MODEL`` constant).
        intent: Classified intent string (e.g. ``"build"``, ``"deploy"``,
            ``"unknown"``) or ``None`` if classification failed. **``None``
            forces one-shot** (operator-mandated fail-safe).
        has_tools: True if the message expects tool / MCP-server use.
            Tool-bearing messages always go one-shot.
        is_workorder: True if the message is a structured WorkOrder.
            Workorders always go one-shot.

    Returns:
        True if the warm path is safe; False otherwise. Callers should
        treat False as "spawn a fresh one-shot subprocess for this
        message."
    """
    if model in _OPUS_MODELS:
        return False
    if is_workorder:
        return False
    if has_tools:
        return False
    if intent is None:
        # Operator-mandated fail-safe: unknown classification → one-shot.
        # The dangerous default would be "we couldn't classify so we
        # defaulted to warm" — we explicitly reject that.
        return False
    if intent in HIGH_RISK_INTENTS:
        return False
    return True
