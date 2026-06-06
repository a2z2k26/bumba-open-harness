"""Output channel classifier and destination router.

Sprint 4.8 — Phase 4B (Dialogue-First Communication Architecture).

Classifies every agent output chunk into one of three channels —
`dialogue`, `milestone`, `trace` — and routes each to a distinct
destination. The agent does not choose the channel; the harness
classifies deterministically by chunk shape and content. In autonomous
mode, `trace` is suppressed from operator-visible channels entirely
and streamed only to disk.

This module is the bedrock of the dialogue-first communication
architecture. The subsequent sprints (4.9 operator inbox, 4.10
tool-call gate) depend on this channel separation existing so that
operator-facing dialogue output is not diluted by tool-trace noise.

Design principle:
    Natural-language conversation with the operator is the agent's
    default mode of existence. Tool-level traces are a debugging
    aid, not a user interface. The harness decides routing; the
    agent only decides what to say.

Integration:
    - stream_coalescer.py and claude_runner.py call `OutputRouter.dispatch()`
      with every output chunk they produce.
    - Configuration comes from bridge.toml [output_channels] section.
    - Trace output is persisted to .harness/traces/{session_id}.jsonl.
"""
from __future__ import annotations

import enum
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol
from bridge.dispatch_metrics import increment_module_counter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Channel & destination enums
# ---------------------------------------------------------------------------


class OutputChannel(enum.Enum):
    """The three output channels every chunk is classified into."""

    DIALOGUE = "dialogue"
    """Natural-language responses to the operator. The default ground
    state. Answers, explanations, questions, acknowledgments."""

    MILESTONE = "milestone"
    """Progress rollups, sprint completions, PR links. Sparse by
    design — only at real checkpoints."""

    TRACE = "trace"
    """Tool-call lifecycle events, file edits, subprocess output.
    Automatic by-product of tool use. In autonomous mode, never
    operator-visible by default."""


class OutputDestinationName(enum.Enum):
    """Symbolic names for built-in destinations. Used in config routing."""

    TERMINAL = "terminal"
    DISCORD = "discord"
    DISK_LOG = "disk_log"


# ---------------------------------------------------------------------------
# Output chunk data model
# ---------------------------------------------------------------------------


VALID_CHUNK_TYPES = frozenset(
    {
        "assistant_text",
        "tool_start",
        "tool_result",
        "tool_error",
        "system",
        "user",
    }
)


@dataclass(frozen=True)
class OutputChunk:
    """One unit of agent output, produced by the streaming subprocess.

    Attributes:
        type: The kind of chunk. Tool-lifecycle events (``tool_start``,
            ``tool_result``, ``tool_error``) are always classified as TRACE.
            ``assistant_text`` is classified by content. Other types default
            to DIALOGUE.
        content: The text or JSON-serializable payload of the chunk.
        session_id: The session this chunk belongs to. Used by DISK_LOG
            destination to choose the output file.
        metadata: Arbitrary extra key/value pairs — tool name, tool args,
            latency, etc. Not used in classification but persisted in
            traces.
    """

    type: str
    content: str
    session_id: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


# Milestone markers. Any assistant-text chunk whose content matches one of
# these patterns is classified as MILESTONE instead of DIALOGUE.
#
# Patterns are intentionally narrow — we want high precision (a milestone
# must really be a milestone) and accept lower recall (the agent can always
# add an explicit [MILESTONE] tag if automatic detection misses).
_MILESTONE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"^#{1,3}\s*(Finished|Complete|Completed|Milestone|Sprint\s+\d)", re.MULTILINE | re.IGNORECASE),
    re.compile(r"\[MILESTONE\]", re.IGNORECASE),
    re.compile(r"^\*\*Sprint\s+[\d.]+\s+(complete|shipped|done)\*\*", re.MULTILINE | re.IGNORECASE),
    re.compile(r"PR\s*#\d+\s+(opened|merged|ready|shipped)", re.IGNORECASE),
    re.compile(r"^✅\s+Sprint\s+[\d.]+", re.MULTILINE),
)


def _has_milestone_marker(text: str) -> bool:
    """True if the text matches any milestone pattern."""
    if not text:
        return False
    return any(p.search(text) for p in _MILESTONE_PATTERNS)


def classify_chunk(chunk: OutputChunk) -> OutputChannel:
    increment_module_counter("output_router.classify_chunk", tier=2)
    """Deterministically classify an output chunk into a channel.

    Rules (applied in order):
    1. Tool-lifecycle events (``tool_start``, ``tool_result``, ``tool_error``)
       are always TRACE — regardless of content.
    2. Assistant text whose content matches a milestone pattern is MILESTONE.
    3. Assistant text without a milestone marker is DIALOGUE.
    4. Unknown or unclassifiable chunk types default to DIALOGUE — the
       safest option (operator-visible, so nothing is silently hidden).

    Args:
        chunk: The output chunk to classify.

    Returns:
        The channel this chunk belongs on.
    """
    if chunk.type in ("tool_start", "tool_result", "tool_error"):
        return OutputChannel.TRACE

    if chunk.type == "assistant_text":
        if _has_milestone_marker(chunk.content):
            return OutputChannel.MILESTONE
        return OutputChannel.DIALOGUE

    # Unknown type → default to dialogue so we don't silently swallow it.
    return OutputChannel.DIALOGUE


# ---------------------------------------------------------------------------
# Destinations
# ---------------------------------------------------------------------------


class OutputDestination(Protocol):
    """A sink for output chunks.

    Implementations may write to stdout, a file, a remote service, etc.
    The router calls ``write()`` for every chunk routed to this
    destination. Implementations must be tolerant of arbitrary chunk
    types — classification is the router's job, not the destination's.
    """

    name: OutputDestinationName

    def write(self, chunk: OutputChunk) -> None:
        """Persist or display the chunk. Must not raise for well-formed input."""
        ...


class TerminalDestination:
    """Writes operator-visible chunks to stdout."""

    name = OutputDestinationName.TERMINAL

    def __init__(self, stream=None) -> None:
        self._stream = stream if stream is not None else sys.stdout

    def write(self, chunk: OutputChunk) -> None:
        # Terminal destination writes the content verbatim, followed by a
        # newline. Tool-trace chunks in supervised mode may include extra
        # metadata in the display; we keep it simple here and emit just
        # the content.
        try:
            self._stream.write(chunk.content)
            if not chunk.content.endswith("\n"):
                self._stream.write("\n")
            self._stream.flush()
        except Exception as e:
            logger.warning("TerminalDestination failed to write chunk: %s", e)


class DiscordDestination:
    """Stub destination — delegates to a provided async sink callable.

    The real Discord integration lives in ``discord_bot.py``. This class
    exists so the router has a consistent ``OutputDestination`` interface
    regardless of the actual delivery mechanism. In production, the bridge
    app injects a sink function that enqueues the chunk for Discord delivery.

    For testing and for environments without a Discord sink configured,
    this destination silently records chunks to an in-memory buffer.
    """

    name = OutputDestinationName.DISCORD

    def __init__(self, sink=None) -> None:
        self._sink = sink
        self._buffer: list[OutputChunk] = []

    def write(self, chunk: OutputChunk) -> None:
        if self._sink is not None:
            try:
                self._sink(chunk)
            except Exception as e:
                logger.warning("DiscordDestination sink failed: %s", e)
        else:
            self._buffer.append(chunk)

    @property
    def buffered_chunks(self) -> list[OutputChunk]:
        """Return chunks buffered while no sink was attached. Test helper."""
        return list(self._buffer)


class DiskLogDestination:
    """Persists chunks to ``.harness/traces/{session_id}.jsonl``.

    Every chunk is appended as a single JSON line. The directory is
    created on demand. This destination is the canonical home for
    TRACE channel output in autonomous mode and is the replay target
    for the ``/trace`` command (Sprint 4.14).
    """

    name = OutputDestinationName.DISK_LOG

    def __init__(self, root: Path | None = None) -> None:
        self._root = root if root is not None else Path(".harness/traces")

    def _path_for_session(self, session_id: str) -> Path:
        safe = session_id or "no_session"
        # Prevent path traversal — session IDs should be opaque tokens
        # from the runner, but we defend against pathological inputs.
        safe = safe.replace("/", "_").replace("..", "_")
        return self._root / f"{safe}.jsonl"

    def write(self, chunk: OutputChunk) -> None:
        path = self._path_for_session(chunk.session_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(chunk.to_dict(), default=str))
                f.write("\n")
        except Exception as e:
            logger.warning("DiskLogDestination failed to write chunk: %s", e)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoutingTable:
    """Maps each channel to an ordered list of destination names.

    Built from the ``[output_channels.autonomous]`` or
    ``[output_channels.supervised]`` section of bridge.toml.
    """

    dialogue: tuple[OutputDestinationName, ...]
    milestone: tuple[OutputDestinationName, ...]
    trace: tuple[OutputDestinationName, ...]

    def destinations_for(self, channel: OutputChannel) -> tuple[OutputDestinationName, ...]:
        if channel == OutputChannel.DIALOGUE:
            return self.dialogue
        if channel == OutputChannel.MILESTONE:
            return self.milestone
        if channel == OutputChannel.TRACE:
            return self.trace
        return ()  # unreachable for valid enum values


# Default routing tables. These match the bridge.toml reference config.
AUTONOMOUS_ROUTING = RoutingTable(
    dialogue=(OutputDestinationName.TERMINAL, OutputDestinationName.DISCORD),
    milestone=(OutputDestinationName.TERMINAL, OutputDestinationName.DISCORD),
    trace=(OutputDestinationName.DISK_LOG,),
)

SUPERVISED_ROUTING = RoutingTable(
    dialogue=(OutputDestinationName.TERMINAL, OutputDestinationName.DISCORD),
    milestone=(OutputDestinationName.TERMINAL, OutputDestinationName.DISCORD),
    trace=(OutputDestinationName.TERMINAL,),
)


def routing_for_mode(mode: str) -> RoutingTable:
    """Return the routing table for a named mode.

    Falls back to AUTONOMOUS routing if the mode is unknown — autonomous
    is safer because it never leaks trace noise to the operator-visible
    channels. Logs a warning on fallback.
    """
    if mode == "autonomous":
        return AUTONOMOUS_ROUTING
    if mode == "supervised":
        return SUPERVISED_ROUTING
    logger.warning(
        "Unknown output_channels mode %r; falling back to autonomous routing",
        mode,
    )
    return AUTONOMOUS_ROUTING


class OutputRouter:
    """Classifies chunks and dispatches them to the configured destinations.

    The router holds a routing table (channel → destination names) and a
    registry of destination instances. On every ``dispatch()`` call it
    classifies the chunk, looks up the destinations for that channel, and
    writes to each in order.

    A destination named in the routing table but missing from the registry
    is logged and silently skipped — this keeps the router resilient to
    partial initialization (e.g., Discord sink not yet connected at startup).
    """

    def __init__(
        self,
        routing: RoutingTable,
        destinations: dict[OutputDestinationName, OutputDestination],
    ) -> None:
        self._routing = routing
        self._destinations = dict(destinations)  # copy; immutable posture
        self._dispatch_count: int = 0
        self._missing_destinations_logged: set[OutputDestinationName] = set()

    def dispatch(self, chunk: OutputChunk) -> OutputChannel:
        """Classify and route a chunk. Returns the channel it was routed to."""
        channel = classify_chunk(chunk)
        destination_names = self._routing.destinations_for(channel)
        for name in destination_names:
            dest = self._destinations.get(name)
            if dest is None:
                if name not in self._missing_destinations_logged:
                    logger.warning(
                        "Destination %s is in routing table but not registered; skipping",
                        name.value,
                    )
                    self._missing_destinations_logged.add(name)
                continue
            dest.write(chunk)
        self._dispatch_count += 1
        return channel

    @property
    def dispatch_count(self) -> int:
        return self._dispatch_count

    @property
    def routing(self) -> RoutingTable:
        return self._routing

    def register_destination(
        self,
        name: OutputDestinationName,
        destination: OutputDestination,
    ) -> None:
        """Attach or replace a destination after construction.

        Used when the bridge wires up a Discord sink later in startup.
        """
        self._destinations[name] = destination
        self._missing_destinations_logged.discard(name)
