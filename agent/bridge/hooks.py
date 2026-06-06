"""Per-session hook registry (#18 — session behavioral modifiers).

Sprint 01.08b removed the file-based ``HookDispatcher`` after the
2026-04-25 Mac mini audit (see
``docs/audits/2026-04-24-activation-plans/plan-01-hooks-audit.md``)
showed that the production hooks directory ``/opt/bumba-harness/.claude/hooks/``
contained zero scripts targeting the bridge's 6 lifecycle events. Every
``HookDispatcher.dispatch(...)`` call had been silently no-op in production;
worse, activating a glob to "fix" it would have caught files owned by
Claude Code CLI and Bumba Design Bridge sharing the same directory.

If file-based bridge lifecycle hooks become desirable in the future, they
should live in their own dedicated directory (e.g.
``~/.claude/bumba-bridge-hooks/<event>/``) — never the shared
``~/.claude/hooks/`` — to avoid the cross-tool collision pattern that
audit surfaced.

``SessionHookRegistry`` below is unrelated to file-based hooks. It tracks
per-session behavioral modifiers activated by operator commands (e.g.
``/careful``, ``/freeze``) and is wired into ``CommandHandler`` via the
WIRING_MANIFEST's ``set_session_hooks`` entry (Sprint 01.02, ``required=True``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-session hook registry (#18 — session behavioral modifiers)
# ---------------------------------------------------------------------------

class SessionHookRegistry:
    """Per-session behavioral modifiers activated/deactivated via operator commands.

    Hooks registered here are ephemeral — they reset when a session expires.
    Each hook has optional on_activate/on_deactivate callbacks and a description.
    """

    def __init__(self) -> None:
        self._hooks: dict[str, dict] = {}  # name -> {description, on_activate, on_deactivate}
        self._active: set[str] = set()

    def register(
        self,
        name: str,
        description: str,
        on_activate: Callable[[], None] | None = None,
        on_deactivate: Callable[[], None] | None = None,
    ) -> None:
        """Register a named hook with optional callbacks. No-op if already registered."""
        if name in self._hooks:
            return
        self._hooks[name] = {
            "description": description,
            "on_activate": on_activate,
            "on_deactivate": on_deactivate,
        }

    def activate(self, name: str) -> bool:
        """Activate a registered hook. Returns True on success, False if callback raises."""
        if name not in self._hooks:
            return False
        if name in self._active:
            return True  # already active
        self._active.add(name)
        cb = self._hooks[name].get("on_activate")
        if cb:
            try:
                cb()
            except Exception as e:
                self._active.discard(name)
                logger.warning("Hook %s on_activate failed, rolled back: %s", name, e)
                return False
        logger.info("Session hook activated: %s", name)
        return True

    def deactivate(self, name: str) -> bool:
        """Deactivate a hook. Returns True if it was active and deactivation succeeded."""
        if name not in self._active:
            return False
        self._active.discard(name)
        cb = self._hooks[name].get("on_deactivate")
        if cb:
            try:
                cb()
            except Exception as e:
                self._active.add(name)
                logger.warning("Hook %s on_deactivate failed, rolled back: %s", name, e)
                return False
        logger.info("Session hook deactivated: %s", name)
        return True

    def is_active(self, name: str) -> bool:
        return name in self._active

    def get_active(self) -> list[str]:
        return sorted(self._active)

    def list_available(self) -> list[dict]:
        return [
            {"name": name, "description": info["description"], "active": name in self._active}
            for name, info in sorted(self._hooks.items())
        ]

    def reset(self) -> None:
        """Deactivate all hooks (called on session expiry)."""
        for name in list(self._active):
            self.deactivate(name)
        logger.info("All session hooks reset")

    def reset_all(self) -> None:
        """Alias for reset() — deactivate all hooks."""
        self.reset()
