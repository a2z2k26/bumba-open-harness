"""
Shared conversation log for Zone 4 department architecture.

Provides thread-safe JSONL-based logging of inter-agent messages
(delegations, results, broadcasts, errors) with read-back and
filtering utilities for chiefs and orchestrators.
"""

from __future__ import annotations

import fcntl
import json

from .memory_writes import MemoryWriteReceipt, emit as _emit_write_receipt
import logging
import time
import uuid
import warnings
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    """Type of inter-agent conversation message."""

    DELEGATION = "DELEGATION"
    RESULT = "RESULT"
    BROADCAST = "BROADCAST"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ConversationMessage:
    """Immutable record of a single inter-agent message.

    Frozen prevents attribute reassignment.  Callers must not mutate
    any mutable objects stored inside (e.g. if metadata were a dict),
    but all fields here are plain scalars or strings so true
    immutability is guaranteed.
    """

    message_id: str
    message_type: MessageType
    from_agent: str
    content: str
    timestamp: float
    to_agent: str = ""
    session_id: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict representation."""
        return {
            "message_id": self.message_id,
            "message_type": self.message_type.value,
            "from_agent": self.from_agent,
            "content": self.content,
            "timestamp": self.timestamp,
            "to_agent": self.to_agent,
            "session_id": self.session_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConversationMessage":
        """Reconstruct from a plain dict (as parsed from JSON)."""
        return cls(
            message_id=data["message_id"],
            message_type=MessageType(data["message_type"]),
            from_agent=data["from_agent"],
            content=data["content"],
            timestamp=float(data["timestamp"]),
            to_agent=data.get("to_agent", ""),
            session_id=data.get("session_id", ""),
        )


class ConversationLogger:
    """Thread-safe JSONL writer for inter-agent conversation messages.

    Each call to :meth:`log` appends a single JSON line to the file
    protected by an exclusive ``fcntl`` advisory lock so concurrent
    writers from multiple threads or processes never interleave partial
    lines.
    """

    def __init__(self, log_path: Path) -> None:
        self._path = log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Touch the file so readers can open it immediately.
        log_path.touch(exist_ok=True)

    # ------------------------------------------------------------------
    # Core write primitive
    # ------------------------------------------------------------------

    def log(self, message: ConversationMessage) -> None:
        """Append *message* as a single JSON line (thread-safe)."""
        line = json.dumps(message.to_dict(), separators=(",", ":")) + "\n"
        with open(self._path, "a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                fh.write(line)
                fh.flush()
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
        # D2.3 — emit write receipt for operator observability
        try:
            _emit_write_receipt(MemoryWriteReceipt.now(
                subsystem="z4_conversation_log", op="insert",
                key=f"{message.from_agent}->{message.to_agent}",
                payload_bytes=len(line.encode("utf-8")),
                actor=f"agent:{message.from_agent}",
            ))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------

    def log_delegation(
        self,
        from_agent: str,
        to_agent: str,
        task: str,
        session_id: str = "",
    ) -> ConversationMessage:
        """Record a task delegation from one agent to another."""
        msg = ConversationMessage(
            message_id=str(uuid.uuid4()),
            message_type=MessageType.DELEGATION,
            from_agent=from_agent,
            to_agent=to_agent,
            content=task,
            timestamp=time.time(),
            session_id=session_id,
        )
        self.log(msg)
        return msg

    def log_result(
        self,
        from_agent: str,
        to_agent: str,
        summary: str,
        session_id: str = "",
    ) -> ConversationMessage:
        """Record the result returned by an agent."""
        msg = ConversationMessage(
            message_id=str(uuid.uuid4()),
            message_type=MessageType.RESULT,
            from_agent=from_agent,
            to_agent=to_agent,
            content=summary,
            timestamp=time.time(),
            session_id=session_id,
        )
        self.log(msg)
        return msg

    def log_broadcast(
        self,
        from_agent: str,
        content: str,
        session_id: str = "",
    ) -> ConversationMessage:
        """Record a broadcast (no specific recipient)."""
        msg = ConversationMessage(
            message_id=str(uuid.uuid4()),
            message_type=MessageType.BROADCAST,
            from_agent=from_agent,
            to_agent="",
            content=content,
            timestamp=time.time(),
            session_id=session_id,
        )
        self.log(msg)
        return msg

    def log_error(
        self,
        from_agent: str,
        error: str,
        session_id: str = "",
    ) -> ConversationMessage:
        """Record an error emitted by an agent."""
        msg = ConversationMessage(
            message_id=str(uuid.uuid4()),
            message_type=MessageType.ERROR,
            from_agent=from_agent,
            to_agent="",
            content=error,
            timestamp=time.time(),
            session_id=session_id,
        )
        self.log(msg)
        return msg


class ConversationReader:
    """Read and filter messages from a JSONL conversation log file."""

    def __init__(self, log_path: Path) -> None:
        self._path = log_path

    # ------------------------------------------------------------------
    # Read primitives
    # ------------------------------------------------------------------

    def read_all(self) -> list[ConversationMessage]:
        """Parse every valid line in the log; skip and warn on bad lines."""
        if not self._path.exists():
            return []

        messages: list[ConversationMessage] = []
        with open(self._path, encoding="utf-8") as fh:
            for lineno, raw in enumerate(fh, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                    messages.append(ConversationMessage.from_dict(data))
                except (json.JSONDecodeError, KeyError, ValueError) as exc:
                    warnings.warn(
                        f"conversation_log: skipping malformed line {lineno}: {exc}",
                        stacklevel=2,
                    )
        return messages

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------

    def filter_by_agent(self, agent: str) -> list[ConversationMessage]:
        """Return messages where *agent* is the sender OR recipient."""
        return [
            m
            for m in self.read_all()
            if m.from_agent == agent or m.to_agent == agent
        ]

    def filter_by_type(
        self, message_type: MessageType
    ) -> list[ConversationMessage]:
        """Return messages whose type matches *message_type*."""
        return [m for m in self.read_all() if m.message_type == message_type]

    def filter_by_time_range(
        self, start: float, end: float
    ) -> list[ConversationMessage]:
        """Return messages whose timestamp falls within [start, end]."""
        return [m for m in self.read_all() if start <= m.timestamp <= end]

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def format_for_agent(self, messages: list[ConversationMessage]) -> str:
        """Return a concise human-readable summary of *messages*.

        Each line is formatted as::

            [TYPE] from_agent → to_agent: content (truncated to 100 chars)
        """
        lines: list[str] = []
        for m in messages:
            content_preview = m.content[:100]
            recipient = m.to_agent if m.to_agent else "(broadcast)"
            lines.append(
                f"[{m.message_type.value}] {m.from_agent} → {recipient}: {content_preview}"
            )
        return "\n".join(lines)
