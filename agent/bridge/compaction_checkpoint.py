"""Compaction checkpoint capture and restore.

Captures workflow state before compaction so it can be injected back
after conversation is summarized. Prevents the "where was I?" problem
when context is compressed.

Integration:
    - pre-compact.sh calls capture_checkpoint()
    - post-compact.sh calls restore_checkpoint() + format_restored_context()
    - ContextPressureMonitor triggers these via EventBus

PreCompact externalization (Sprint 03.05, issue #995, MIT — egregore,
concept-only port; nothing copied verbatim):

    Compaction throws away tokens to free context. Even good summarization
    loses fidelity, especially around the most-recent reasoning steps that
    happen to be the load-bearing ones. The externalization hook here fires
    immediately *before* compaction kicks in (signal: compound pressure
    crosses threshold per :func:`bridge.compound_pressure.should_auto_compact`)
    and writes the highest-value subset of the live transcript to a durable
    side-file. Reload happens on next session start via the existing
    SessionContextBuilder / staleness machinery.

    Selection rule (documented here so callers don't have to grep for it):

      1. Always include any message tagged ``<important>`` (case-insensitive).
      2. Always include any message whose ``timestamp`` (epoch seconds, float)
         is within the last 5 minutes.
      3. Otherwise keep the last N=20 messages by tail position.

    Privacy: ``<private>...</private>`` spans are stripped from every
    externalized message body via :func:`bridge.tag_parser.strip_private_spans`
    before write. This mirrors the redaction guarantee shipped in Sprint
    03.01 (PR #1086) — externalization MUST NOT bypass it.

    Atomicity: writes go to ``<file>.tmp`` then ``os.replace`` to the final
    path. Partial writes never leave a half-readable side-file on disk.

    Feature flag: ``BridgeConfig.precompact_externalization_enabled``
    (TOML key ``memory.precompact_externalization_enabled``). Default OFF.
    When OFF, :func:`externalize_before_compact` is a no-op returning
    ``None`` and existing checkpoint behavior is unchanged.

Capsule schema v1 (Sprint E1.2, issue #1234):

    The on-disk capsule at <checkpoint_dir>/<session_id>.json carries
    a v1 envelope of named fields the next session's
    SessionContextBuilder (E1.3) injects verbatim. Schema:

      {
        "capsule_version": 1,                # int — bump on schema change
        "session_id": str,                   # the same id as the file stem
        "created_at": str,                   # UTC ISO-8601
        "active_sprint": str,                # e.g. "E1.2" (empty if none)
        "active_pr": int,                    # e.g. 1162 (0 if none)
        "active_tasks": list[str],           # task titles in flight
        "files_in_flight": list[str],        # files modified this session
        "workflow_state": dict[str, Any],    # arbitrary state bag
        "recent_decisions": list[str],       # decision-log strings
        "open_questions": list[str],         # pending operator-decision text
        "tool_usage": dict[str, int],        # tool name -> call count
        "permission_summary": list[str],     # permission decisions summary
        "last_handoff_reason": str,          # e.g. "context_pressure_compact_now"
        "message_count_before": int,         # for back-compat with v0 reads
        "estimated_tokens_before": int,      # for back-compat with v0 reads
      }

    Loaders MUST read capsule_version first and dispatch. v1 loaders
    treat unknown extra fields as forward-compatible no-ops; v2 loaders
    must accept v1 by mapping the v1 field set to v2's shape.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bridge.tag_parser import strip_private_spans

logger = logging.getLogger(__name__)

# Capsule schema version — bump on schema change (E1.2).
CAPSULE_VERSION: int = 1

# Default externalization parameters. Callers may override per-call.
DEFAULT_KEEP_LAST_N: int = 20
DEFAULT_RECENT_WINDOW_SECONDS: float = 300.0  # 5 minutes
_IMPORTANT_TAG_OPEN = "<important"  # case-insensitive substring match


@dataclass(frozen=True)
class CompactionCheckpoint:
    """Snapshot of critical state before compaction (v1 schema, E1.2)."""

    session_id: str
    message_count_before: int
    estimated_tokens_before: int
    active_tasks: tuple[str, ...]
    workflow_state: dict[str, Any]
    permission_summary: tuple[str, ...]
    tool_usage: dict[str, int]
    created_at: str
    # NEW v1 fields (E1.2, issue #1234)
    active_sprint: str
    active_pr: int
    files_in_flight: tuple[str, ...]
    recent_decisions: tuple[str, ...]
    open_questions: tuple[str, ...]
    last_handoff_reason: str

    def __init__(
        self,
        session_id: str,
        message_count_before: int,
        estimated_tokens_before: int,
        active_tasks: tuple[str, ...] | list[str] = (),
        workflow_state: dict[str, Any] | None = None,
        permission_summary: tuple[str, ...] | list[str] = (),
        tool_usage: dict[str, int] | None = None,
        created_at: str = "",
        # NEW v1 kwargs (E1.2) — all default to v0 behavior when omitted
        active_sprint: str = "",
        active_pr: int = 0,
        files_in_flight: tuple[str, ...] | list[str] = (),
        recent_decisions: tuple[str, ...] | list[str] = (),
        open_questions: tuple[str, ...] | list[str] = (),
        last_handoff_reason: str = "",
    ) -> None:
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "message_count_before", message_count_before)
        object.__setattr__(self, "estimated_tokens_before", estimated_tokens_before)
        object.__setattr__(self, "active_tasks", tuple(active_tasks))
        object.__setattr__(self, "workflow_state", workflow_state or {})
        object.__setattr__(self, "permission_summary", tuple(permission_summary))
        object.__setattr__(self, "tool_usage", tool_usage or {})
        object.__setattr__(
            self, "created_at",
            created_at or datetime.now(timezone.utc).isoformat(),
        )
        # v1 fields
        object.__setattr__(self, "active_sprint", active_sprint)
        object.__setattr__(self, "active_pr", active_pr)
        object.__setattr__(self, "files_in_flight", tuple(files_in_flight))
        object.__setattr__(self, "recent_decisions", tuple(recent_decisions))
        object.__setattr__(self, "open_questions", tuple(open_questions))
        object.__setattr__(self, "last_handoff_reason", last_handoff_reason)


def format_capsule_json(
    checkpoint: CompactionCheckpoint,
    *,
    extra_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render a CompactionCheckpoint as a v1 capsule dict.

    Pure function: returns a NEW dict, never mutates the checkpoint or
    extra_state. Tuples are converted to lists for JSON-serializability.
    extra_state is shallow-merged into workflow_state (extra wins on key
    collision) so the runner can inject hard-stop-time facts (pressure
    score, etc.) without modifying the checkpoint.

    The returned dict matches the v1 schema documented in the module
    docstring. Every field is present; callers MUST NOT assume any field
    is absent.
    """
    workflow = {**checkpoint.workflow_state, **(extra_state or {})}
    return {
        "capsule_version": CAPSULE_VERSION,
        "session_id": checkpoint.session_id,
        "created_at": checkpoint.created_at,
        "active_sprint": checkpoint.active_sprint,
        "active_pr": checkpoint.active_pr,
        "active_tasks": list(checkpoint.active_tasks),
        "files_in_flight": list(checkpoint.files_in_flight),
        "workflow_state": workflow,
        "recent_decisions": list(checkpoint.recent_decisions),
        "open_questions": list(checkpoint.open_questions),
        "tool_usage": dict(checkpoint.tool_usage),
        "permission_summary": list(checkpoint.permission_summary),
        "last_handoff_reason": checkpoint.last_handoff_reason,
        "message_count_before": checkpoint.message_count_before,
        "estimated_tokens_before": checkpoint.estimated_tokens_before,
    }


def capture_checkpoint(
    session_id: str,
    message_count: int,
    estimated_tokens: int,
    active_task_titles: list[str] | None = None,
    workflow_state: dict[str, Any] | None = None,
    checkpoint_dir: str | Path = "",
    *,
    # NEW v1 kwargs (E1.2) — all default to v0 behavior when omitted
    active_sprint: str = "",
    active_pr: int = 0,
    files_in_flight: list[str] | None = None,
    recent_decisions: list[str] | None = None,
    open_questions: list[str] | None = None,
    last_handoff_reason: str = "",
) -> CompactionCheckpoint:
    """Capture current state as a v1 compaction capsule.

    Persists to checkpoint_dir/{session_id}.json (v1 JSON shape via
    :func:`format_capsule_json`) if checkpoint_dir is provided. Callers
    that omit the new v1 kwargs receive the documented defaults — existing
    call sites require no changes.
    """
    checkpoint = CompactionCheckpoint(
        session_id=session_id,
        message_count_before=message_count,
        estimated_tokens_before=estimated_tokens,
        active_tasks=active_task_titles or [],
        workflow_state=workflow_state or {},
        active_sprint=active_sprint,
        active_pr=active_pr,
        files_in_flight=files_in_flight or [],
        recent_decisions=recent_decisions or [],
        open_questions=open_questions or [],
        last_handoff_reason=last_handoff_reason,
    )

    if checkpoint_dir:
        cp_dir = Path(checkpoint_dir)
        cp_dir.mkdir(parents=True, exist_ok=True)
        cp_path = cp_dir / f"{session_id}.json"
        # Persist via the v1 emitter so the on-disk shape matches what
        # E1.3's loader expects (format_capsule_json → includes capsule_version).
        cp_path.write_text(json.dumps(format_capsule_json(checkpoint), indent=2))
        logger.info("Capsule v1 saved: %s", cp_path)

        # D7.8 — operator-visible signal. Write a single-document
        # last_compaction.json next to the capsule so /compact-status
        # can read the most-recent fire without scanning the directory.
        last_path = cp_dir / "last_compaction.json"
        last_path.write_text(json.dumps({
            "session_id": session_id,
            "fired_at_utc": datetime.now(timezone.utc).isoformat(),
            "message_count_before": message_count,
            "estimated_tokens_before": estimated_tokens,
            "active_sprint": active_sprint,
            "active_tasks": active_task_titles or [],
            "last_handoff_reason": last_handoff_reason,
            "capsule_path": str(cp_path),
        }, indent=2))

    return checkpoint


def restore_checkpoint(
    session_id: str,
    checkpoint_dir: str | Path,
) -> CompactionCheckpoint | None:
    """Load a checkpoint from disk. Returns None if not found.

    Back-compat: v0 files (no capsule_version key) are loaded gracefully;
    missing v1 fields default to their documented empty values.
    Unknown extra keys in the JSON are ignored (forward-compatible no-op).
    """
    cp_path = Path(checkpoint_dir) / f"{session_id}.json"
    if not cp_path.exists():
        return None

    try:
        data = json.loads(cp_path.read_text())
        return CompactionCheckpoint(
            session_id=data["session_id"],
            message_count_before=data["message_count_before"],
            estimated_tokens_before=data["estimated_tokens_before"],
            active_tasks=data.get("active_tasks", []),
            workflow_state=data.get("workflow_state", {}),
            permission_summary=data.get("permission_summary", []),
            tool_usage=data.get("tool_usage", {}),
            created_at=data.get("created_at", ""),
            # v1 fields — default to empty for v0 files
            active_sprint=data.get("active_sprint", ""),
            active_pr=data.get("active_pr", 0),
            files_in_flight=data.get("files_in_flight", []),
            recent_decisions=data.get("recent_decisions", []),
            open_questions=data.get("open_questions", []),
            last_handoff_reason=data.get("last_handoff_reason", ""),
        )
    except (json.JSONDecodeError, KeyError, OSError) as e:
        logger.warning("Failed to restore checkpoint %s: %s", cp_path, e)
        return None


def format_restored_context(checkpoint: CompactionCheckpoint) -> str:
    """Format a restored checkpoint as context for injection after compaction.

    This text is injected as a systemMessage via the PostCompact hook.
    Kept for backward compatibility — the prose output is unchanged from
    pre-E1.2. The structured JSON path (E1.3) uses format_capsule_json()
    instead; this function remains for any callers (post-compact.sh, etc.)
    that consume the prose block.
    """
    parts = [
        "POST-COMPACTION CONTEXT RESTORE:",
        f"Session: {checkpoint.session_id}",
        f"Before compaction: {checkpoint.message_count_before} messages, ~{checkpoint.estimated_tokens_before} tokens",
    ]

    if checkpoint.active_tasks:
        parts.append("\nACTIVE TASKS (in progress before compaction):")
        for task in checkpoint.active_tasks:
            parts.append(f"  - {task}")

    if checkpoint.workflow_state:
        parts.append("\nWORKFLOW STATE:")
        for key, value in checkpoint.workflow_state.items():
            parts.append(f"  - {key}: {value}")

    if checkpoint.tool_usage:
        top_tools = sorted(checkpoint.tool_usage.items(), key=lambda x: -x[1])[:5]
        parts.append("\nTOP TOOLS USED THIS SESSION:")
        for tool, count in top_tools:
            parts.append(f"  - {tool}: {count}x")

    return "\n".join(parts)


# -- PreCompact externalization (Sprint 03.05, #995) -----------------------

def _has_important_tag(content: str) -> bool:
    """Return True if message content carries an ``<important>`` tag.

    Case-insensitive substring check; intentionally tolerant of attributes
    (e.g. ``<important reason="...">``).
    """
    if not content:
        return False
    return _IMPORTANT_TAG_OPEN in content.lower()


def _select_externalization_payload(
    transcript: list[dict[str, Any]],
    keep_last_n: int = DEFAULT_KEEP_LAST_N,
    recent_window_seconds: float = DEFAULT_RECENT_WINDOW_SECONDS,
    now: float | None = None,
) -> list[dict[str, Any]]:
    """Pick the high-value subset of ``transcript`` to externalize.

    Pure function. The returned list is a NEW list; messages are NEW dicts
    (no mutation of input). Each message body has ``<private>`` spans
    stripped via :func:`strip_private_spans`.

    Selection rule (see module docstring for rationale):

      - Keep any message tagged ``<important>`` (case-insensitive).
      - Keep any message with a ``timestamp`` (epoch seconds) within the
        last ``recent_window_seconds``.
      - Otherwise, keep the last ``keep_last_n`` messages by position.

    Order is preserved relative to the input.
    """
    if not transcript:
        return []

    cutoff = (now if now is not None else time.time()) - recent_window_seconds
    total = len(transcript)
    tail_start = max(0, total - keep_last_n)

    selected: list[dict[str, Any]] = []
    for idx, message in enumerate(transcript):
        content = message.get("content", "") or ""
        ts = message.get("timestamp")

        keep = False
        if idx >= tail_start:
            keep = True
        elif _has_important_tag(content):
            keep = True
        elif isinstance(ts, (int, float)) and ts >= cutoff:
            keep = True

        if not keep:
            continue

        # Build a NEW dict with redacted content; never mutate the caller's
        # transcript. `strip_private_spans` is a pure function that returns
        # a new string.
        redacted = {**message, "content": strip_private_spans(content)}
        selected.append(redacted)

    return selected


def _externalization_dir(data_dir: str | Path, session_id: str) -> Path:
    """Resolve the per-session directory for externalized side-files."""
    return Path(data_dir) / "precompact" / session_id


def externalize_before_compact(
    transcript: list[dict[str, Any]],
    session_id: str,
    data_dir: str | Path,
    *,
    enabled: bool = False,
    reason: str = "",
    keep_last_n: int = DEFAULT_KEEP_LAST_N,
    recent_window_seconds: float = DEFAULT_RECENT_WINDOW_SECONDS,
    now: float | None = None,
) -> Path | None:
    """Write a durable side-file with the high-value subset of ``transcript``.

    Intended to fire on the same compound-pressure signal that triggers
    compaction (see :func:`bridge.compound_pressure.should_auto_compact`),
    BEFORE the existing :func:`capture_checkpoint` runs. This way, even if
    summarization drops fidelity, the saved tokens are recoverable via
    :func:`load_precompact_externals` on next session start.

    Atomic on POSIX (``write_text`` to ``<file>.tmp`` then ``os.replace``).

    Args:
        transcript: The live transcript as a list of message dicts. Each
            dict SHOULD have ``content`` (str) and MAY have ``timestamp``
            (epoch seconds, float). Other keys are passed through.
        session_id: Identifier used as the side-file directory name.
        data_dir: Bridge data root (e.g. ``BridgeConfig.data_dir``). The
            side-file lands at
            ``<data_dir>/precompact/<session_id>/<utc-iso>.json``.
        enabled: Feature flag. When False (default), this is a no-op
            returning ``None``. Wire from
            ``BridgeConfig.precompact_externalization_enabled``.
        reason: Free-form note recorded inside the payload (e.g. compound
            pressure level) for post-mortem.
        keep_last_n: Override default tail-window length.
        recent_window_seconds: Override default recency window.
        now: Inject the current epoch timestamp (testing).

    Returns:
        The :class:`pathlib.Path` of the written side-file, or ``None`` if
        ``enabled`` is False or the selected payload is empty.
    """
    if not enabled:
        return None
    if not session_id:
        logger.warning("PreCompact externalization called with empty session_id")
        return None

    selected = _select_externalization_payload(
        transcript,
        keep_last_n=keep_last_n,
        recent_window_seconds=recent_window_seconds,
        now=now,
    )
    if not selected:
        return None

    out_dir = _externalization_dir(data_dir, session_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    final_path = out_dir / f"{stamp}.json"
    tmp_path = final_path.with_suffix(".json.tmp")

    payload = {
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "messages": selected,
        "selection": {
            "keep_last_n": keep_last_n,
            "recent_window_seconds": recent_window_seconds,
            "input_count": len(transcript),
            "kept_count": len(selected),
        },
    }
    tmp_path.write_text(json.dumps(payload, indent=2, default=str))
    os.replace(tmp_path, final_path)
    logger.info(
        "PreCompact externalized %d/%d messages to %s",
        len(selected), len(transcript), final_path,
    )
    return final_path


def load_precompact_externals(
    session_id: str,
    data_dir: str | Path,
) -> list[dict[str, Any]]:
    """Read all externalized side-files for ``session_id`` in time order.

    Returns a flat list of message dicts (each restored from the
    ``messages`` field of the saved payloads), oldest-first. Used by next
    session start to re-inject saved tokens.

    Returns an empty list if the session has no externalized side-files,
    if the directory does not exist, or if every file is unreadable. JSON
    decode errors on individual files are logged and skipped — a single
    corrupt side-file MUST NOT block recovery from the others.
    """
    if not session_id:
        return []

    out_dir = _externalization_dir(data_dir, session_id)
    if not out_dir.exists() or not out_dir.is_dir():
        return []

    restored: list[dict[str, Any]] = []
    for side_file in sorted(out_dir.glob("*.json")):
        try:
            data = json.loads(side_file.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "Skipping unreadable precompact side-file %s: %s",
                side_file, exc,
            )
            continue

        messages = data.get("messages")
        if isinstance(messages, list):
            restored.extend(m for m in messages if isinstance(m, dict))

    return restored
