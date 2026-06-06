"""Operator notification hook for upward Surface events.

Sprint 22 PR B (Phase 5C). PR A persisted Surfaces; this module pushes
the high-urgency ones into Discord so the operator hears about
``BLOCKER``, ``POLICY_Q``, ``CROSS_TEAM``, and ``SCOPE_REQUEST`` surfaces
addressed to ``main`` in real time.

Notification matrix:

+----------------+--------+-------------+-------------+
| kind \\ urgency | FYI    | ATTENTION   | IMMEDIATE   |
+================+========+=============+=============+
| RESULT         | silent | silent      | silent      |
| FLAG           | silent | silent      | silent      |
| BLOCKER        | silent | DM          | DM @op      |
| POLICY_Q       | silent | DM          | DM @op      |
| CROSS_TEAM     | silent | DM          | DM @op      |
| SCOPE_REQUEST  | silent | DM          | DM @op      |
+----------------+--------+-------------+-------------+

Only surfaces with ``to_agent == "main"`` are evaluated. Specialist→chief
surfaces never page the operator — the chief is the gatekeeper.

This module is best-effort. Discord failures are caught and logged so a
flapping bot can never break a department run. The surface row is
persisted before notification is attempted, so the operator can always
find it via ``/surfaces unread`` even if the DM never arrives.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from teams._types import Surface, SurfaceKind, Urgency

log = logging.getLogger(__name__)


# Kinds that are eligible for operator notification. RESULT and FLAG are
# intentionally absent — RESULT is the work product (read via /surfaces),
# FLAG is informational only. The four below all imply the operator may
# need to take action: unblock, answer a policy question, authorize
# cross-team work, or expand scope.
_NOTIFIABLE_KINDS: frozenset[SurfaceKind] = frozenset({
    SurfaceKind.BLOCKER,
    SurfaceKind.POLICY_Q,
    SurfaceKind.CROSS_TEAM,
    SurfaceKind.SCOPE_REQUEST,
})


def should_notify(surface: Surface) -> bool:
    """Pure predicate: does this surface warrant a Discord notification?

    Decoupled from the Discord-dispatch path so call sites and tests can
    check the policy without needing a BridgeApp. The dispatcher
    (``maybe_notify_operator``) calls this first; tests can call it
    directly to verify the decision matrix.
    """
    if surface.to_agent != "main":
        return False
    if surface.urgency == Urgency.FYI:
        return False
    return surface.kind in _NOTIFIABLE_KINDS


def _format_message(surface: Surface) -> str:
    """Render the Discord message body for a notifiable surface.

    Layout intentionally compact — one line of header for the chief's
    glance, one line of summary, one line of footer with the /ack hint.
    The ``@operator`` mention is included for IMMEDIATE so the message
    body carries a visual signal even though the DM itself bypasses
    do-not-disturb regardless.
    """
    kind = surface.kind.value if hasattr(surface.kind, "value") else surface.kind
    urgency = (
        surface.urgency.value
        if hasattr(surface.urgency, "value")
        else surface.urgency
    )
    mention = "@operator " if surface.urgency == Urgency.IMMEDIATE else ""
    summary = surface.payload.get("summary", "(no summary)")
    correlation = surface.correlation_id or "(no correlation)"
    return (
        f"{mention}**{kind.upper()}** [{urgency}] from `{surface.from_agent}` "
        f"(directive `{correlation}`):\n"
        f"{summary}\n"
        f"`/ack {surface.surface_id}` when handled"
    )


async def maybe_notify_operator(
    surface: Surface, app: Optional[Any]
) -> bool:
    """Send a Discord DM to the operator if ``surface`` warrants it.

    Returns True if a notification was dispatched, False otherwise (silent
    by policy, or unable to reach Discord). Never raises.

    The ``app`` argument is duck-typed BridgeApp — we look for an attribute
    ``_discord`` exposing ``send_message(chat_id, text)`` and a config
    attribute carrying ``operator_discord_id``. Either ``app=None`` (test
    fixtures, cron context) or any missing piece of that path is treated
    as "Discord unavailable" → log + return False.
    """
    if not should_notify(surface):
        return False

    if app is None:
        log.debug(
            "surface_notify.skipped id=%s reason=no-app",
            surface.surface_id,
        )
        return False

    discord = getattr(app, "_discord", None)
    if discord is None:
        log.debug(
            "surface_notify.skipped id=%s reason=no-discord-client",
            surface.surface_id,
        )
        return False

    # Resolve the operator chat_id from the bridge config. Two attribute
    # paths are accepted to mirror the existing code in app.py: the
    # canonical ``app._config.operator_discord_id`` and the alt
    # ``app.config.operator.chat_id`` used elsewhere. Either being
    # missing is a silent skip.
    operator_chat_id: Optional[str] = None
    cfg = getattr(app, "_config", None) or getattr(app, "config", None)
    if cfg is not None:
        operator_chat_id = (
            getattr(cfg, "operator_discord_id", None)
            or getattr(getattr(cfg, "operator", None), "chat_id", None)
        )
    if not operator_chat_id:
        log.debug(
            "surface_notify.skipped id=%s reason=no-operator-chat-id",
            surface.surface_id,
        )
        return False

    msg = _format_message(surface)
    try:
        await discord.send_message(operator_chat_id, msg)
        log.info(
            "surface_notify.sent id=%s kind=%s urgency=%s from=%s",
            surface.surface_id, surface.kind, surface.urgency, surface.from_agent,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "surface_notify.discord_failed id=%s error=%s",
            surface.surface_id, exc,
        )
        return False
