"""Append-only MEMORY.md writer capped at 200 lines / 25 kB.

Originally introduced in Sprint 11 (issue #143) as ``bridge.memory_index`` /
``MemoryIndex``. Renamed in Sprint 05.06 of Plan 05 to ``bridge.memory_file`` /
``MemoryFile`` to resolve a naming-vs-behavior drift: callers in
``bridge/health.py`` and ``bridge/workorder_ingest.py`` were treating this
class as if it were a vector index (``.upsert()``, ``._count``), which it is
not. This module is, and only is, a size-capped MEMORY.md file writer used to
inject distilled long-term memory into the system prompt.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .memory_writes import MemoryWriteReceipt, emit as _emit_write_receipt

logger = logging.getLogger(__name__)


@dataclass
class MemoryEntry:
    """A single entry to be written into MEMORY.md."""

    key: str
    value: str
    category: str = "general"


class MemoryFile:
    """Manages MEMORY.md — the distilled knowledge index loaded into every session.

    Caps content at MAX_LINES lines and MAX_BYTES bytes.  Every call to
    :meth:`update` enforces these limits via :meth:`truncate_if_needed`.
    """

    MAX_LINES: int = 200
    MAX_BYTES: int = 25_000

    def __init__(self, memory_dir: Path) -> None:
        self._memory_dir = memory_dir
        self._path = memory_dir / "MEMORY.md"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_dir(self) -> None:
        """Create the memory directory (and any parents) if absent."""
        self._memory_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        """Absolute path to the MEMORY.md file (may not exist on disk)."""
        return self._path

    @property
    def exists(self) -> bool:
        """True iff MEMORY.md has been written at least once."""
        return self._path.exists()

    @property
    def file_size_bytes(self) -> int:
        """Size of MEMORY.md in bytes, or 0 if the file does not exist."""
        if not self._path.exists():
            return 0
        return self._path.stat().st_size

    def read(self) -> str:
        """Return MEMORY.md content, or empty string if the file is missing."""
        if not self._path.exists():
            return ""
        return self._path.read_text(encoding="utf-8")

    def update(self, entries: list[MemoryEntry]) -> None:
        """Write *entries* to MEMORY.md, then enforce size limits."""
        self._ensure_dir()
        lines: list[str] = ["# Memory Index\n"]
        for entry in entries:
            lines.append(f"## {entry.category}: {entry.key}\n{entry.value}\n")
        self._path.write_text("\n".join(lines), encoding="utf-8")
        self.truncate_if_needed()
        # D2.3 — emit write receipt for operator observability
        try:
            _emit_write_receipt(MemoryWriteReceipt.now(
                subsystem="memory_file", op="update",
                key="MEMORY.md", payload_bytes=self._path.stat().st_size if self._path.exists() else 0,
                actor="agent",
            ))
        except Exception as exc:
            logger.warning("memory_file write-receipt emit failed: %s", exc)

    def truncate_if_needed(self) -> bool:
        """Enforce line and byte limits on MEMORY.md.

        Returns True if the file was truncated, False otherwise.
        The file is left unchanged when it is within both limits.
        """
        if not self._path.exists():
            return False

        content = self._path.read_text(encoding="utf-8")
        raw_lines = content.splitlines(keepends=True)
        truncated = False

        # --- byte limit (checked first so we don't re-introduce bytes via
        #     the line-limit path when both limits are exceeded) ---
        if len(content.encode("utf-8")) > self.MAX_BYTES:
            while raw_lines and len("".join(raw_lines).encode("utf-8")) > self.MAX_BYTES:
                raw_lines.pop()
            truncated = True

        # --- line limit ---
        if len(raw_lines) > self.MAX_LINES:
            raw_lines = raw_lines[: self.MAX_LINES]
            truncated = True

        if truncated:
            self._path.write_text("".join(raw_lines), encoding="utf-8")

        return truncated

    def get_memory_context(self) -> str:
        """Return MEMORY.md content for system-prompt injection, capped at MAX_BYTES.

        If the stored content is over-size (e.g. written by an external tool),
        we trim at the byte boundary rather than raising an error.
        """
        content = self.read()
        encoded = content.encode("utf-8")
        if len(encoded) > self.MAX_BYTES:
            content = encoded[: self.MAX_BYTES].decode("utf-8", errors="ignore")
        return content
