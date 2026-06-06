"""Tool-call trace reader — backend for the operator-invoked firehose command.

Sprint 4.14 — Phase 4B (Dialogue-First Communication Architecture).

Sprint 4.8's ``DiskLogDestination`` writes TRACE-channel output chunks
to ``.harness/traces/<session_id>.jsonl``, one JSON line per chunk.
In autonomous mode these are suppressed from operator-visible channels
so the dialogue stream stays clean. This module is the other side of
that trade: when the operator wants to see the trace (for debugging,
auditing, or just curiosity), they invoke a command and the reader
returns a human-readable summary of the last N tool events.

The module is intentionally pure:

- Reads a file path passed in by the caller. No session lookup, no
  command-handler coupling, no global state.
- Returns plain dataclasses and strings. No side effects, no logging
  beyond debug breadcrumbs for malformed lines.
- Safe on missing files (returns an empty list) so the module works
  today — before Sprint 4.8's wiring into the live subprocess
  lifecycle has landed — without any special handling by the caller.

The command-handler glue that looks up the active session's trace
file path and wires the reader into ``commands.py`` is deferred to
the Phase 4B integration sprint, same pattern as Sprints 4.8-4.13.

Command naming — note for the wiring sprint:

    The Sprint 4.14 spec called for an operator command named
    ``/trace``. That name is **already taken** by an existing
    ``_cmd_trace`` handler in ``agent/bridge/commands.py`` that
    shows request-span timing breakdowns from a ``Tracer`` object —
    a completely different feature. Rather than break the existing
    command (which the operator may rely on), this reader is
    intended to be wired up as ``/tooltrace`` when the integration
    sprint happens. If the operator prefers to rename the existing
    ``/trace`` to ``/spans`` and give the tool-call firehose the
    shorter name, that's a cheap change in ``commands.py`` and the
    wiring sprint can do it at the same time.
"""
from __future__ import annotations

import collections
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


DEFAULT_TRACE_COUNT: int = 20
MAX_TRACE_COUNT: int = 500


# ---------------------------------------------------------------------------
# Parsed entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TraceEntry:
    """One parsed trace log entry, ready for formatting.

    Attributes:
        type: The chunk type (``tool_start``, ``tool_result``,
            ``tool_error``, etc.) as recorded by the output router.
        content: The chunk's content field. May be large (file
            contents, bash output); the formatter is responsible for
            truncating when rendering.
        tool_name: Extracted from ``metadata.tool_name`` if present.
        duration_ms: Extracted from ``metadata.duration_ms`` if present
            (typically on ``tool_result`` events).
        exit_code: Extracted from ``metadata.exit_code`` if present
            (typically on ``tool_result`` and ``tool_error`` events).
    """

    type: str
    content: str
    tool_name: str | None = None
    duration_ms: int | None = None
    exit_code: int | None = None


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_trace_count_argument(arg: str) -> int:
    """Parse the ``N`` argument from an operator's ``/tooltrace N`` command.

    Returns ``DEFAULT_TRACE_COUNT`` on empty, whitespace, non-integer,
    zero, or negative input — the operator probably meant "default" in
    all of those cases. Caps the result at ``MAX_TRACE_COUNT`` so a
    command like ``/tooltrace 1000000`` doesn't post a giant Discord
    message.
    """
    stripped = arg.strip()
    if not stripped:
        return DEFAULT_TRACE_COUNT
    try:
        n = int(stripped)
    except ValueError:
        return DEFAULT_TRACE_COUNT
    if n <= 0:
        return DEFAULT_TRACE_COUNT
    return min(n, MAX_TRACE_COUNT)


# ---------------------------------------------------------------------------
# File reader
# ---------------------------------------------------------------------------


def _parse_line_to_entry(line: str) -> TraceEntry | None:
    """Parse a single JSONL line to a TraceEntry. Return None on failure."""
    try:
        obj: Any = json.loads(line)
    except json.JSONDecodeError:
        logger.debug("tool_trace_reader: skipping malformed line: %r", line[:80])
        return None

    if not isinstance(obj, dict):
        logger.debug("tool_trace_reader: skipping non-dict line: %r", type(obj).__name__)
        return None

    metadata = obj.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    return TraceEntry(
        type=str(obj.get("type", "")),
        content=str(obj.get("content", "")),
        tool_name=metadata.get("tool_name"),
        duration_ms=metadata.get("duration_ms"),
        exit_code=metadata.get("exit_code"),
    )


def read_recent_trace_entries(path: Path, n: int) -> list[TraceEntry]:
    """Return the last ``n`` valid trace entries from ``path``.

    Returns an empty list if the file doesn't exist, is empty, or
    contains only malformed lines. Malformed lines are skipped with a
    debug log; they do not raise. ``OSError`` on open/read (permission
    denied, I/O failure) is also caught and returns an empty list
    with a warning.

    Entries are returned in chronological order (oldest-of-N first,
    newest last) so the formatter can render them top-to-bottom as a
    timeline.

    Memory discipline: streams the file through a bounded ``deque`` so
    peak memory is O(n) regardless of total log size. Trace logs in
    long autonomous sessions can grow to hundreds of MB; reading them
    with ``readlines()`` would spike memory and latency on every
    command invocation.
    """
    if not path.exists():
        return []

    # The deque max is a small multiplier on ``n`` so we have enough
    # room to drop malformed lines and still end up with ``n`` valid
    # entries in the common case. A 4x cushion is generous; in
    # pathological cases where almost every line is malformed the
    # caller simply gets fewer than n entries, which is the right
    # behavior.
    window_size = max(n * 4, n + 16)

    recent_lines: collections.deque[str] = collections.deque(maxlen=window_size)
    try:
        with path.open("r", encoding="utf-8") as f:
            for raw_line in f:
                stripped = raw_line.strip()
                if stripped:
                    recent_lines.append(stripped)
    except OSError as e:
        logger.warning("tool_trace_reader: cannot read %s: %s", path, e)
        return []

    entries: list[TraceEntry] = []
    for line in recent_lines:
        entry = _parse_line_to_entry(line)
        if entry is not None:
            entries.append(entry)

    return entries[-n:] if n < len(entries) else entries


# ---------------------------------------------------------------------------
# Human-readable formatter
# ---------------------------------------------------------------------------


_CONTENT_PREVIEW_MAX_CHARS: int = 80

# Known secret patterns to redact from content previews before rendering
# them to the operator dialogue channel. This is a heuristic defense —
# a determined leak can still slip through (e.g. an unusual key format),
# but it closes the common vectors. If the operator reports a leak that
# this list misses, add the pattern here.
#
# Each pattern is compiled case-insensitive. A match redacts from the
# match start to the next whitespace (or end-of-string) so the secret
# value is replaced but surrounding context survives.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk_live_\S+", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9_-]{10,}"),  # OpenAI-style (case-sensitive, starts lowercase)
    re.compile(r"ghp_\S+"),
    re.compile(r"gho_\S+"),
    re.compile(r"github_pat_\S+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key ID
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"Authorization:\s*\S+", re.IGNORECASE),
    re.compile(r"password\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"passwd\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"api[_-]?key\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"token\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"secret\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"export\s+\w+\s*=\s*\S+"),
)

_REDACTED_PLACEHOLDER = "[REDACTED]"


def _redact_secrets(text: str) -> str:
    """Redact known secret patterns from a string. Returns the redacted text."""
    if not text:
        return text
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_REDACTED_PLACEHOLDER, text)
    return text


def _format_duration_ms(duration_ms: int | None) -> str:
    if duration_ms is None:
        return ""
    if duration_ms < 1000:
        return f" {duration_ms}ms"
    return f" {duration_ms / 1000:.2f}s"


def _format_content_preview(content: str) -> str:
    """Return a single-line preview of ``content`` suitable for inline rendering.

    Newlines are collapsed, long blobs are truncated with an ellipsis,
    and any matching secret patterns are redacted before truncation so
    the operator sees a human-readable summary rather than a raw arg
    blob with embedded credentials.
    """
    if not content:
        return ""
    redacted = _redact_secrets(content)
    flat = redacted.replace("\n", " ").replace("\r", " ").strip()
    if len(flat) > _CONTENT_PREVIEW_MAX_CHARS:
        flat = flat[:_CONTENT_PREVIEW_MAX_CHARS] + "..."
    return flat


def _format_entry(entry: TraceEntry) -> str:
    """Render a single TraceEntry as one line of the dialogue output."""
    # Visual marker per event type — distinct enough to scan quickly
    if entry.type == "tool_start":
        marker = "  →"
    elif entry.type == "tool_result":
        marker = "  ✓"
    elif entry.type == "tool_error":
        marker = "  ✗ ERROR"
    else:
        marker = f"  [{entry.type}]"

    tool = entry.tool_name or "(unknown)"
    duration = _format_duration_ms(entry.duration_ms)
    exit_str = ""
    if entry.exit_code is not None and entry.exit_code != 0:
        exit_str = f" exit={entry.exit_code}"

    # For tool_start events we show ONLY the arg-blob size, not the
    # content itself. Tool args routinely contain full bash scripts,
    # environment exports, file paths with embedded tokens, and other
    # high-leak-risk material. Rendering a preview of them to the
    # operator dialogue channel re-surfaces the exact risk Sprint 4.8
    # mitigated by routing trace output to disk only. For
    # tool_result/tool_error we still preview (the operator needs to
    # see what came back) but pass through ``_format_content_preview``
    # which redacts known secret patterns.
    if entry.type == "tool_start":
        if entry.content:
            size_str = f" ({len(entry.content)} chars)"
        else:
            size_str = ""
        return f"{marker} {tool}{duration}{exit_str}{size_str}"

    preview = _format_content_preview(entry.content)
    preview_str = f" — {preview}" if preview else ""
    return f"{marker} {tool}{duration}{exit_str}{preview_str}"


def format_trace_entries_for_dialogue(entries: list[TraceEntry]) -> str:
    """Render a list of TraceEntry records as a human-readable message.

    Returns a single multiline string ready to post to the operator's
    dialogue channel. Empty input produces an informative "no trace
    data" message rather than an empty string, so the command's reply
    is always non-empty.
    """
    if not entries:
        return "No trace entries found for this session."

    header = f"**Recent tool trace** — last {len(entries)} event(s)"
    lines = [header, ""]
    for entry in entries:
        lines.append(_format_entry(entry))
    return "\n".join(lines)
