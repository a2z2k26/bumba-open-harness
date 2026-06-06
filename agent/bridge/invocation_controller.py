"""Unified invocation state for one-shot and warm Claude paths.

Sprint P1.1 (2026-05-11 harness audit, finding C1).

The bridge has two invocation paths to Claude:
- One-shot: ``ClaudeRunner.invoke()`` spawns ``claude -p`` per message.
- Warm: ``WarmClaudeProcess.send_message()`` reuses a persistent
  subprocess for haiku/sonnet traffic (the default fast path).

Operator-interrupt detection at ``app.py`` historically checked only
``self._claude._lock.locked()`` — the one-shot runner's lock. When a
message arrived while the *warm* path was mid-invocation, the check
returned False, the inbox-receive call was skipped, and the operator
message queued normally instead of preempting the in-flight run. The
dialogue-first guarantee was silently bypassed on the default path.

This module is the shared source of truth. Both paths call ``start()``
when they begin an invocation and ``finish()`` when they end. App-level
interrupt logic asks ``active()`` and gets a single answer regardless
of which path is running.

Design — explicit snapshot dataclass instead of a bare counter:

    Future work may want to discriminate operator response policy based
    on which path is in-flight (warm has different cancel semantics than
    one-shot — see ``ClaudeRunner._kill_process()`` vs the warm process
    state machine). Returning a structured snapshot keeps that door open
    without forcing changes to today's callers, which only need to ask
    "is anything running?".

Concurrency: an ``asyncio.Lock`` protects ``_active``. Multiple
concurrent invocations are NOT supported — the bridge serializes
message handling, and the warm process itself takes its own internal
lock around ``send_message``. The controller's role is to surface the
*existence* of an in-flight invocation, not to coordinate concurrency.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Literal

InvocationPath = Literal["warm", "one_shot"]


@dataclass(frozen=True)
class InvocationSnapshot:
    """Immutable record of a single in-flight Claude invocation."""

    invocation_id: str
    path: InvocationPath
    session_id: str | None
    chat_id: str | None
    started_at: float


class InvocationController:
    """Shared lifecycle hook for warm and one-shot Claude invocations.

    Lifecycle:
        async with controller.track(path=..., session_id=..., chat_id=...):
            # call into Claude here
            ...
        # snapshot cleared automatically on exit, even on exception

    Or manually:
        snap = await controller.start(path=..., session_id=..., chat_id=...)
        try:
            ...
        finally:
            await controller.finish(snap.invocation_id)
    """

    def __init__(self) -> None:
        self._active: InvocationSnapshot | None = None
        self._lock = asyncio.Lock()
        self._counter = 0

    async def start(
        self,
        *,
        path: InvocationPath,
        session_id: str | None = None,
        chat_id: str | None = None,
    ) -> InvocationSnapshot:
        """Record the start of a new invocation. Returns the snapshot.

        Re-entrancy: if an invocation is already active, the new snapshot
        replaces it. This matches the bridge's actual concurrency model
        (one in-flight call at a time on each path) and avoids
        constraining future paths that might overlap briefly.
        """
        async with self._lock:
            self._counter += 1
            snap = InvocationSnapshot(
                invocation_id=f"inv_{int(time.time() * 1000)}_{self._counter}",
                path=path,
                session_id=session_id,
                chat_id=chat_id,
                started_at=time.monotonic(),
            )
            self._active = snap
            return snap

    async def finish(self, invocation_id: str) -> None:
        """Clear the active snapshot if its id matches.

        Idempotent: calling with a stale or unknown id is a silent no-op.
        Callers don't need to wrap in try/except for benign races.
        """
        async with self._lock:
            if self._active is not None and self._active.invocation_id == invocation_id:
                self._active = None

    async def active(self) -> InvocationSnapshot | None:
        """Return a snapshot of the currently-active invocation, if any."""
        async with self._lock:
            return self._active

    def track(
        self,
        *,
        path: InvocationPath,
        session_id: str | None = None,
        chat_id: str | None = None,
    ) -> "_InvocationTracker":
        """Async context manager that pairs start() and finish() automatically."""
        return _InvocationTracker(
            controller=self,
            path=path,
            session_id=session_id,
            chat_id=chat_id,
        )


class _InvocationTracker:
    """Internal helper — pairs ``start()`` + ``finish()`` via ``async with``."""

    def __init__(
        self,
        *,
        controller: InvocationController,
        path: InvocationPath,
        session_id: str | None,
        chat_id: str | None,
    ) -> None:
        self._controller = controller
        self._path = path
        self._session_id = session_id
        self._chat_id = chat_id
        self._snapshot: InvocationSnapshot | None = None

    async def __aenter__(self) -> InvocationSnapshot:
        self._snapshot = await self._controller.start(
            path=self._path,
            session_id=self._session_id,
            chat_id=self._chat_id,
        )
        return self._snapshot

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._snapshot is not None:
            await self._controller.finish(self._snapshot.invocation_id)
