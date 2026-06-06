"""Memory write-ahead log — Sprint 03.06.

A higher-level **memory-mutation** WAL that sits in front of the canonical
memory store. Each long-term memory mutation is appended to an on-disk JSONL
log *before* the canonical write fires. On successful canonical write the
matching WAL entry is drained. If the bridge dies between append and drain,
the next session start replays the WAL through an applier callback so no
mutation is lost.

This is **not** the same WAL that SQLite runs internally
(``PRAGMA journal_mode = WAL``). SQLite's WAL is a low-level transaction
journal that protects single statements; this module is a higher-level
durability log for the *memory subsystem* that lets us recover mutations
across a process crash even when the SQLite write itself never landed.

Concept-only port from the egregore audit (MIT). No verbatim code.

The WAL is feature-flagged: when ``BridgeConfig.memory_wal_enabled`` is False
(the default) the public methods short-circuit so this module is inert until
the operator flips it on (Plan 03.10 territory).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Bounds — spec 03.06 §4
WAL_WARN_BYTES = 10 * 1024 * 1024  # 10 MB — log warning
WAL_FORCE_DRAIN_BYTES = 100 * 1024 * 1024  # 100 MB — force-drain

Applier = Callable[[dict[str, Any]], Awaitable[bool]]


def _utcnow_iso() -> str:
    """Return current UTC time as ISO-8601 string (Z-suffixed)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _compute_write_id(payload: Any, target_store: str, ts: str) -> str:
    """Deterministic write_id for idempotency.

    ``write_id = sha256(json(payload) + target_store + ts)``.
    """
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256()
    digest.update(encoded.encode("utf-8"))
    digest.update(target_store.encode("utf-8"))
    digest.update(ts.encode("utf-8"))
    return digest.hexdigest()


@dataclass(frozen=True)
class WALEntry:
    """One entry in the memory mutation WAL.

    Frozen so callers can't mutate after construction; the WAL on-disk file
    is the source of truth.
    """

    ts: str
    write_id: str
    target_store: str
    payload_hash: str
    payload: dict[str, Any]
    attempt_count: int = 0
    status: str = "pending"

    def to_json_line(self) -> str:
        return json.dumps(
            {
                "ts": self.ts,
                "write_id": self.write_id,
                "target_store": self.target_store,
                "payload_hash": self.payload_hash,
                "payload": self.payload,
                "attempt_count": self.attempt_count,
                "status": self.status,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WALEntry":
        return cls(
            ts=str(data.get("ts", "")),
            write_id=str(data.get("write_id", "")),
            target_store=str(data.get("target_store", "")),
            payload_hash=str(data.get("payload_hash", "")),
            payload=dict(data.get("payload", {})),
            attempt_count=int(data.get("attempt_count", 0)),
            status=str(data.get("status", "pending")),
        )


@dataclass
class DrainResult:
    """Outcome of a drain pass."""

    drained: int = 0
    retained: int = 0
    skipped_corrupt: int = 0
    failed_apply: list[str] = field(default_factory=list)


class MemoryWAL:
    """Append-only JSONL write-ahead log for memory mutations.

    Public surface (all coroutine-safe via an internal lock):

    - :meth:`enqueue` — append one entry before the canonical write fires.
    - :meth:`drain` — apply all pending entries; remove drained ones.
    - :meth:`recover` — alias of drain semantics, called at bridge restart.

    The WAL is intentionally non-destructive on failure: an applier returning
    ``False`` keeps the entry on disk for the next pass. Corrupt JSON lines
    are skipped (with a warning) and dropped from the rewritten file so the
    log doesn't grow unbounded with garbage.

    The class is **safe to construct even when disabled** — when
    ``enabled=False`` every method is a documented no-op and returns
    quickly without touching the filesystem.
    """

    def __init__(
        self,
        wal_path: Path | str,
        *,
        enabled: bool = False,
        consolidation_lock: Any | None = None,
    ) -> None:
        self._wal_path = Path(wal_path)
        self._enabled = bool(enabled)
        self._consolidation_lock = consolidation_lock
        self._lock = asyncio.Lock()
        self._warned_at_size = False

    # -- Properties --

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def path(self) -> Path:
        return self._wal_path

    # -- Enqueue --

    async def enqueue(
        self,
        target_store: str,
        payload: dict[str, Any],
    ) -> WALEntry | None:
        """Append a pending mutation to the WAL.

        Returns the persisted ``WALEntry`` on success, or ``None`` when the
        WAL is disabled (no-op path). The caller should treat ``None`` as
        "skipped"; the canonical store write must still proceed.
        """
        if not self._enabled:
            return None

        ts = _utcnow_iso()
        write_id = _compute_write_id(payload, target_store, ts)
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        entry = WALEntry(
            ts=ts,
            write_id=write_id,
            target_store=target_store,
            payload_hash=payload_hash,
            payload=dict(payload),
            attempt_count=0,
            status="pending",
        )

        line = entry.to_json_line() + "\n"

        async with self._lock:
            self._wal_path.parent.mkdir(parents=True, exist_ok=True)
            # O_APPEND ensures atomic appends across coroutines; fsync gives
            # durability across crashes.
            fd = os.open(
                str(self._wal_path),
                os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                0o600,
            )
            try:
                os.write(fd, line.encode("utf-8"))
                try:
                    os.fsync(fd)
                except OSError:
                    # fsync can fail on some filesystems (e.g. tmpfs in tests).
                    # The append itself is atomic; surface only the size warn.
                    pass
            finally:
                os.close(fd)

            self._maybe_warn_size_locked()

        return entry

    # -- Drain --

    async def drain(
        self,
        applier: Applier,
        *,
        force: bool = False,
    ) -> DrainResult:
        """Replay pending entries through ``applier`` and remove the drained ones.

        ``applier`` receives the parsed operation dict and returns:
        - ``True``  → drained (removed from WAL)
        - ``False`` → retained (kept on WAL for next pass)

        If a ``consolidation_lock`` was supplied at construction and is
        currently held by another process, drain is a no-op (returns an
        empty :class:`DrainResult`) unless ``force=True``. Lock state
        snapshot only: we don't acquire the lock — consolidation owns it.

        Idempotent: calling drain twice with no new appends is safe.
        """
        if not self._enabled:
            return DrainResult()

        if not self._wal_path.exists():
            return DrainResult()

        # Coordinate with consolidation: don't drain mid-consolidation.
        if not force and self._consolidation_held_by_other():
            log.debug(
                "memory_wal.drain skipped — consolidation lock held by other"
            )
            return DrainResult()

        async with self._lock:
            try:
                raw = self._wal_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                return DrainResult()

            result = DrainResult()
            survivors: list[str] = []

            for line in raw.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    log.warning(
                        "memory_wal: skipping corrupt line in %s",
                        self._wal_path,
                    )
                    result.skipped_corrupt += 1
                    continue

                applied = False
                try:
                    applied = await applier(parsed)
                except Exception as exc:  # applier crashed
                    log.warning(
                        "memory_wal applier raised for write_id=%s: %s",
                        parsed.get("write_id"),
                        exc,
                    )
                    applied = False

                if applied:
                    result.drained += 1
                else:
                    survivors.append(stripped)
                    result.retained += 1
                    result.failed_apply.append(str(parsed.get("write_id", "")))

            # Rewrite WAL atomically (write to temp + rename) with survivors.
            self._rewrite_locked(survivors)

            return result

    async def recover(self, applier: Applier) -> DrainResult:
        """Drain any entries left over from a crashed prior session.

        Called at bridge startup. Identical semantics to :meth:`drain` but
        always force=True so a stale consolidation lock from a dead PID
        doesn't block recovery. The consolidation lock module already
        clears stale locks on its own acquire path, but recovery happens
        before any consolidation can re-run.
        """
        return await self.drain(applier, force=True)

    # Backwards-compatible alias: the spec docstring says ``replay_pending``.
    replay_pending = recover

    # -- Internals --

    def _consolidation_held_by_other(self) -> bool:
        """Return True if a consolidation lock is currently held by another live process."""
        if self._consolidation_lock is None:
            return False
        try:
            # ConsolidationLock exposes try_acquire; if it succeeds we
            # immediately rollback. We do NOT want to actually hold the
            # lock — we just want a snapshot of "is it held?".
            # Instead, peek at the lock file directly.
            lock_path = getattr(self._consolidation_lock, "_lock_path", None)
            if lock_path is None or not Path(lock_path).exists():
                return False
            try:
                holder_pid_text = Path(lock_path).read_text().strip()
                if not holder_pid_text:
                    return False
                holder_pid = int(holder_pid_text)
            except (ValueError, OSError):
                return False
            if holder_pid == os.getpid():
                return False
            # Process alive?
            try:
                os.kill(holder_pid, 0)
                return True
            except (OSError, ProcessLookupError):
                return False
        except Exception:
            return False

    def _maybe_warn_size_locked(self) -> None:
        """Emit a one-shot warning when WAL crosses 10 MB."""
        try:
            size = self._wal_path.stat().st_size
        except OSError:
            return
        if size >= WAL_FORCE_DRAIN_BYTES:
            log.error(
                "memory_wal exceeded %d bytes (%d) — operator should force-drain",
                WAL_FORCE_DRAIN_BYTES,
                size,
            )
        elif size >= WAL_WARN_BYTES and not self._warned_at_size:
            log.warning(
                "memory_wal exceeded %d bytes (%d) — drain pressure rising",
                WAL_WARN_BYTES,
                size,
            )
            self._warned_at_size = True

    def _rewrite_locked(self, lines: list[str]) -> None:
        """Replace the WAL on disk with ``lines`` (atomic via tmp+rename).

        Caller must hold ``self._lock``. Empty list ⇒ truncate to zero bytes
        rather than removing the file (tests/observability rely on the
        file existing after first append).
        """
        tmp_path = self._wal_path.with_suffix(self._wal_path.suffix + ".tmp")
        body = ""
        if lines:
            body = "\n".join(lines) + "\n"
        try:
            self._wal_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(body, encoding="utf-8")
            os.replace(tmp_path, self._wal_path)
            self._warned_at_size = False
        except OSError:
            log.exception("memory_wal: rewrite failed for %s", self._wal_path)
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def size_bytes(self) -> int:
        """Return current WAL file size in bytes (0 if missing)."""
        try:
            return self._wal_path.stat().st_size
        except OSError:
            return 0


__all__ = [
    "DrainResult",
    "MemoryWAL",
    "WALEntry",
    "WAL_FORCE_DRAIN_BYTES",
    "WAL_WARN_BYTES",
]
