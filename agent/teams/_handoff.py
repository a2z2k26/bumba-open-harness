"""Structured handoff envelopes for cross-department transfers.

When one department needs to pass work to another, it writes a HandoffEnvelope
to shared memory under `handoff:{correlation_id}`. The receiving department
reads the envelope directly instead of relying on the orchestrator's retelling.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any



log = logging.getLogger(__name__)

@dataclass(frozen=True)
class HandoffEnvelope:
    """Immutable artifact representing a cross-department work transfer.

    Stored in shared memory under ``handoff:{correlation_id}``.

    TTL / expiry (sprint B-S.1)
    ---------------------------
    Each envelope has a ``ttl_hours`` field (default 24 h) and a derived
    ``expires_at`` timestamp computed in ``__post_init__``.
    ``continue_handoff`` rejects expired envelopes.
    ``list_pending_handoffs`` filters them out automatically.
    """

    from_department: str
    to_department: str
    task: str
    findings: str = ""
    context_files: tuple[str, ...] = field(default_factory=tuple)
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    ttl_hours: float = 24.0
    """Time-to-live in hours. Default 24 h. Envelope is rejected after expiry."""
    expires_at: str = field(init=False, default="")
    """ISO 8601 UTC timestamp at which the envelope expires. Computed from created_at + ttl_hours."""

    def __post_init__(self) -> None:
        """Compute ``expires_at`` from ``created_at + ttl_hours``.

        frozen=True prevents direct attribute assignment, so we use
        ``object.__setattr__`` which bypasses the frozen guard.
        """
        created = datetime.fromisoformat(self.created_at)
        # Ensure tz-aware
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        expires = created + timedelta(hours=self.ttl_hours)
        object.__setattr__(self, "expires_at", expires.isoformat())

    def is_expired(self) -> bool:
        """Return True if the current UTC time is past ``expires_at``."""
        expires = datetime.fromisoformat(self.expires_at)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > expires

    def to_json(self) -> str:
        """Serialize the envelope to a JSON string."""
        d = asdict(self)
        d["context_files"] = list(d["context_files"])  # tuple → list for JSON
        return json.dumps(d)

    @classmethod
    def from_json(cls, raw: str) -> "HandoffEnvelope":
        """Deserialize a HandoffEnvelope from a JSON string.

        ``expires_at`` is a computed field; it is stripped before passing
        kwargs to ``__init__`` so ``__post_init__`` can recompute it cleanly.
        """
        d = json.loads(raw)
        d["context_files"] = tuple(d.get("context_files", []))
        # expires_at is computed in __post_init__; remove it so we don't pass
        # it as an init arg (it's init=False and would cause a TypeError)
        d.pop("expires_at", None)
        return cls(**d)


def _emit(event_type: str, payload: dict, event_bus: Any) -> None:
    """Best-effort event emission — never raises."""
    if event_bus is None:
        return
    try:
        event_bus.publish(event_type, payload)
    except Exception:  # noqa: BLE001
        pass


async def store_handoff(
    envelope: HandoffEnvelope,
    memory_store: Any,
    event_bus: Any = None,
) -> None:
    """Write a handoff envelope to shared memory under ``handoff:{correlation_id}``.

    Publishes ``z4.handoff.created`` on the event bus (best-effort).
    No-op if memory_store is None (graceful degradation).
    """
    if memory_store is None:
        return
    await memory_store.set(f"handoff:{envelope.correlation_id}", envelope.to_json())
    _emit(
        "z4.handoff.created",
        {
            "correlation_id": envelope.correlation_id,
            "from": envelope.from_department,
            "to": envelope.to_department,
            "expires_at": envelope.expires_at,
        },
        event_bus,
    )


async def load_handoff(
    correlation_id: str,
    memory_store: Any,
    event_bus: Any = None,
) -> HandoffEnvelope | None:
    """Read and deserialize a handoff envelope from shared memory.

    Publishes ``z4.handoff.consumed`` or ``z4.handoff.expired`` depending on
    expiry state. Publishes ``z4.handoff.failed`` if deserialisation fails.

    Returns None if not found or memory_store is None.
    """
    if memory_store is None:
        return None
    raw = await memory_store.get(f"handoff:{correlation_id}")
    if raw is None:
        return None
    try:
        envelope = HandoffEnvelope.from_json(str(raw))
    except Exception as exc:  # noqa: BLE001
        _emit(
            "z4.handoff.failed",
            {
                "correlation_id": correlation_id,
                "reason": str(exc),
            },
            event_bus,
        )
        return None

    if envelope.is_expired():
        _emit(
            "z4.handoff.expired",
            {
                "correlation_id": envelope.correlation_id,
                "from": envelope.from_department,
                "to": envelope.to_department,
                "expires_at": envelope.expires_at,
            },
            event_bus,
        )
    else:
        _emit(
            "z4.handoff.consumed",
            {
                "correlation_id": envelope.correlation_id,
                "from": envelope.from_department,
                "to": envelope.to_department,
            },
            event_bus,
        )
    return envelope


async def list_pending_handoffs(
    memory_store: Any,
    department: str,
) -> list[HandoffEnvelope]:
    """Return all non-expired HandoffEnvelopes addressed to *department*.

    Enumerates keys via ``memory_store.list_prefix("handoff:")``, deserializes
    each envelope, and returns only those matching ``to_department`` that have
    not yet expired.

    Returns an empty list if memory_store is None, if the store doesn't support
    ``list_prefix``, or if no pending handoffs exist for the department.

    Sprint B-S.2.
    """
    if memory_store is None:
        return []

    try:
        keys: list[str] = await memory_store.list_prefix("handoff:")
    except AttributeError:
        log.warning(
            "list_pending_handoffs: memory_store %r lacks list_prefix — "
            "returning empty list.  Add MemoryKVAdapter.list_prefix to fix this gap.",
            type(memory_store).__name__,
        )
        return []

    results: list[HandoffEnvelope] = []
    for key in keys:
        try:
            raw = await memory_store.get(key)
            if raw is None:
                continue
            envelope = HandoffEnvelope.from_json(str(raw))
            if envelope.to_department == department and not envelope.is_expired():
                results.append(envelope)
        except Exception:  # noqa: BLE001
            # Skip malformed or unreadable entries
            continue

    return results
