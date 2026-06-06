"""Structured orientation document — agent's current focus + priorities + win criteria.

The orientation file gives the proactive tick (and any future caller) a stable,
operator-curated answer to "what does the operator consider important right now."
Without it, the tick fires against generic context (recent log lines, pending
tasks) and the agent has no internalized direction to reason against.

Persistence: JSON file at agent/state/orientation.json
Pattern: follows plan_state.py (frozen dataclasses, mutators return new instances,
atomic write via tmp + os.replace, missing-file fallback returns empty Orientation).

Integration:
    - Seed populated by operator (this sprint, E3.1)
    - Read by tick_manager / tick_context (E3.2)
    - Updated by event-triggered writers (E3.3)
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_ORIENTATION_PATH = Path("agent/state/orientation.json")
ORIENTATION_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Priority:
    """A single ranked priority entry."""

    rank: int
    title: str
    rationale: str
    plan_ref: str | None = None


@dataclass(frozen=True)
class WinCriterion:
    """One observable signal that means 'this counts as a win'."""

    label: str
    description: str


@dataclass(frozen=True)
class Orientation:
    """Immutable snapshot of agent orientation. Mutations return new instances."""

    schema_version: int
    current_focus: str
    priorities: tuple[Priority, ...]
    win_criteria: tuple[WinCriterion, ...]
    updated_at: str
    pending_focus_change: str | None = None  # E3.3 — staged redirect, not yet confirmed

    def __init__(
        self,
        schema_version: int = ORIENTATION_SCHEMA_VERSION,
        current_focus: str = "",
        priorities: tuple[Priority, ...] | list[Priority] = (),
        win_criteria: tuple[WinCriterion, ...] | list[WinCriterion] = (),
        updated_at: str = "",
        pending_focus_change: str | None = None,
    ) -> None:
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "current_focus", current_focus)
        object.__setattr__(self, "priorities", tuple(priorities))
        object.__setattr__(self, "win_criteria", tuple(win_criteria))
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "pending_focus_change", pending_focus_change)

    @classmethod
    def empty(cls) -> Orientation:
        """Return an empty orientation at the current schema version."""
        return cls(
            schema_version=ORIENTATION_SCHEMA_VERSION,
            current_focus="",
            priorities=(),
            win_criteria=(),
            updated_at="",
            pending_focus_change=None,
        )

    @classmethod
    def load(cls, path: Path | str = DEFAULT_ORIENTATION_PATH) -> Orientation:
        """Load orientation from disk.

        Returns an empty Orientation if the file is missing, unreadable, or
        contains malformed JSON. Schema-version mismatch is logged at WARNING
        and a best-effort load is attempted (unknown fields are ignored,
        missing fields fall back to dataclass defaults).
        """
        p = Path(path)
        if not p.exists():
            return cls.empty()
        try:
            data = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read orientation %s: %s", p, exc)
            return cls.empty()
        return cls.from_dict(data)

    def write(self, path: Path | str = DEFAULT_ORIENTATION_PATH) -> None:
        """Persist orientation to disk atomically (tmp file + os.replace).

        Creates the parent directory if it does not exist.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=p.name + ".",
            suffix=".tmp",
            dir=str(p.parent),
        )
        try:
            with os.fdopen(tmp_fd, "w") as fh:
                json.dump(self.to_dict(), fh, indent=2)
                fh.write("\n")
            os.replace(tmp_name, p)
        except Exception:
            # Clean up the tmp file on failure; never leave it lying around.
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def to_dict(self) -> dict[str, Any]:
        """Serialize orientation to a JSON-compatible dict."""
        d: dict[str, Any] = {
            "schema_version": self.schema_version,
            "current_focus": self.current_focus,
            "priorities": [
                {
                    "rank": p.rank,
                    "title": p.title,
                    "rationale": p.rationale,
                    "plan_ref": p.plan_ref,
                }
                for p in self.priorities
            ],
            "win_criteria": [
                {"label": w.label, "description": w.description}
                for w in self.win_criteria
            ],
            "updated_at": self.updated_at,
        }
        if self.pending_focus_change is not None:
            d["pending_focus_change"] = self.pending_focus_change
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Orientation:
        """Deserialize orientation from a dict (as produced by to_dict).

        Tolerates schema-version mismatch with a WARNING and a best-effort load.
        Missing or malformed nested entries are dropped (logged) rather than
        raising — orientation must always load to *something* so the tick path
        never crashes on a bad write.
        """
        schema_version = int(data.get("schema_version", ORIENTATION_SCHEMA_VERSION))
        if schema_version != ORIENTATION_SCHEMA_VERSION:
            logger.warning(
                "Orientation schema version mismatch: file=%s expected=%s — best-effort load",
                schema_version,
                ORIENTATION_SCHEMA_VERSION,
            )

        priorities: list[Priority] = []
        for raw in data.get("priorities", []) or []:
            try:
                priorities.append(
                    Priority(
                        rank=int(raw["rank"]),
                        title=str(raw["title"]),
                        rationale=str(raw["rationale"]),
                        plan_ref=raw.get("plan_ref"),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Dropping malformed priority entry %r: %s", raw, exc)

        win_criteria: list[WinCriterion] = []
        for raw in data.get("win_criteria", []) or []:
            try:
                win_criteria.append(
                    WinCriterion(
                        label=str(raw["label"]),
                        description=str(raw["description"]),
                    )
                )
            except (KeyError, TypeError) as exc:
                logger.warning("Dropping malformed win_criterion entry %r: %s", raw, exc)

        pending = data.get("pending_focus_change")
        return cls(
            schema_version=schema_version,
            current_focus=str(data.get("current_focus", "")),
            priorities=tuple(priorities),
            win_criteria=tuple(win_criteria),
            updated_at=str(data.get("updated_at", "")),
            pending_focus_change=str(pending) if pending is not None else None,
        )

    def with_focus(self, focus: str) -> Orientation:
        """Return new orientation with `current_focus` replaced."""
        return replace(
            self,
            current_focus=focus,
            updated_at=_now_iso(),
        )

    def with_priorities(self, priorities: tuple[Priority, ...] | list[Priority]) -> Orientation:
        """Return new orientation with `priorities` replaced."""
        return replace(
            self,
            priorities=tuple(priorities),
            updated_at=_now_iso(),
        )

    def with_win_criteria(
        self, criteria: tuple[WinCriterion, ...] | list[WinCriterion]
    ) -> Orientation:
        """Return new orientation with `win_criteria` replaced."""
        return replace(
            self,
            win_criteria=tuple(criteria),
            updated_at=_now_iso(),
        )

    def with_pending_focus(self, focus: str | None) -> Orientation:
        """Return new orientation with `pending_focus_change` set (E3.3 staging)."""
        return replace(self, pending_focus_change=focus, updated_at=_now_iso())

    def promote_pending_focus(self) -> Orientation:
        """Promote staged focus change to current_focus and clear the pending field."""
        if self.pending_focus_change is None:
            return self
        return replace(
            self,
            current_focus=self.pending_focus_change,
            pending_focus_change=None,
            updated_at=_now_iso(),
        )


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# E3.3 — Redirect classifier
# ---------------------------------------------------------------------------

_REDIRECT_RE = re.compile(
    r"^(redirect|focus|instead|new\s+focus)\s*:\s*",
    re.IGNORECASE,
)

_CONFIRM_RE = re.compile(
    r"^\s*(yes|confirm|go)\s*[.!]?\s*$",
    re.IGNORECASE,
)


def is_redirect_message(content: str) -> bool:
    """Return True if the message starts with a redirect prefix."""
    return bool(_REDIRECT_RE.match(content.strip()))


def is_confirm_message(content: str) -> bool:
    """Return True if the message is a bare confirm acknowledgement."""
    return bool(_CONFIRM_RE.match(content.strip()))


# ---------------------------------------------------------------------------
# E3.3 — Event-triggered orientation update functions
# ---------------------------------------------------------------------------

_DECISION_SUMMARY_MAX = 120


def update_on_step_completed(
    plan_step_id: str,
    plan_id: str,
    path: Path | str = DEFAULT_ORIENTATION_PATH,
) -> None:
    """Refresh the rationale on matching priorities when a plan step completes."""
    try:
        o = Orientation.load(path)
        new_priorities = []
        for p in o.priorities:
            if p.plan_ref and plan_id in p.plan_ref:
                new_priorities.append(
                    replace(p, rationale=f"{p.rationale} (last completed: {plan_step_id})")
                )
            else:
                new_priorities.append(p)
        o.with_priorities(tuple(new_priorities)).write(path)
    except Exception as exc:
        logger.warning("update_on_step_completed failed: %s", exc)


def update_on_decision_logged(
    decision_summary: str,
    path: Path | str = DEFAULT_ORIENTATION_PATH,
) -> None:
    """Append a short decision tag to current_focus when a decision is logged."""
    try:
        o = Orientation.load(path)
        truncated = decision_summary[:_DECISION_SUMMARY_MAX]
        new_focus = f"{o.current_focus} | recent decision: {truncated}"
        o.with_focus(new_focus).write(path)
    except Exception as exc:
        logger.warning("update_on_decision_logged failed: %s", exc)


def update_on_operator_redirect(
    redirect_content: str,
    path: Path | str = DEFAULT_ORIENTATION_PATH,
) -> None:
    """Stage a focus change from an operator redirect message.

    Strips the leading prefix (redirect:/focus:/etc.) and stores the remainder
    in pending_focus_change. Does NOT overwrite current_focus — the operator
    must follow up with a confirm message to promote the staged change.
    """
    try:
        cleaned = _REDIRECT_RE.sub("", redirect_content.strip()).strip()
        if not cleaned:
            return
        o = Orientation.load(path)
        o.with_pending_focus(cleaned).write(path)
    except Exception as exc:
        logger.warning("update_on_operator_redirect failed: %s", exc)


def promote_pending_focus_if_confirmed(
    message_content: str,
    path: Path | str = DEFAULT_ORIENTATION_PATH,
) -> bool:
    """If message is a confirm and a pending focus change exists, promote it.

    Returns True if a promotion happened, False otherwise.
    """
    try:
        if not is_confirm_message(message_content):
            return False
        o = Orientation.load(path)
        if o.pending_focus_change is None:
            return False
        o.promote_pending_focus().write(path)
        return True
    except Exception as exc:
        logger.warning("promote_pending_focus_if_confirmed failed: %s", exc)
        return False
