"""Approval Snapshot — Z2-S2.3 (HIGHEST STAKES).

Computes a deterministic SHA-256 hash of an outreach send-payload at
approval time, persists it, and verifies byte-for-byte match at send time.

Disaster scenario prevented
----------------------------
1. Agent drafts outreach at 09:00, stages in Notion.
2. Operator approves at 11:00.
3. Agent or another process edits the body at 13:00.
4. EXECUTE fires at 14:00 and would silently send the EDITED version.

With this module: step 4 raises SnapshotMismatch, marks the listing
``snapshot_drift`` in Notion, fires a Discord DM, and does NOT send.

Core invariant
--------------
- Same payload content  → same hash regardless of dict insertion order.
- Any byte-level change → different hash.
- Hash is computed from a canonical JSON representation (sorted keys,
  no insignificant whitespace).

Storage
-------
Snapshots are stored in ``<data_dir>/service_state/send_snapshots.json``
keyed by Notion page_id::

    {
      "<page_id>": {
        "hash":         "<sha256hex>",
        "payload":      { ... },   // full payload at approval time
        "approved_at":  "<iso>",
        "sent_at":      "<iso>",   // null until sent
        "status":       "approved" | "sent" | "snapshot_drift"
      }
    }

Usage
-----
    from job_search.snapshot import SnapshotStore, SnapshotMismatch, canonical_hash

    store = SnapshotStore(data_dir)

    # At approval time (PREPARE / staging):
    store.record_approval(page_id, payload)

    # At send time (EXECUTE):
    store.verify_or_raise(page_id, current_payload)   # raises SnapshotMismatch on drift
    store.mark_sent(page_id)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_SNAPSHOT_FILE = "send_snapshots.json"


# ---------------------------------------------------------------------------
# Core hash primitive
# ---------------------------------------------------------------------------

def canonical_hash(payload: dict) -> str:
    """Return the SHA-256 hex digest of a canonical JSON serialisation.

    Canonical means: keys sorted at every nesting level, no insignificant
    whitespace.  Two dicts with the same content but different insertion
    order produce the same hash.  Any value change produces a different hash.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class SnapshotMismatch(Exception):
    """Raised when the current payload hash differs from the approval hash.

    Attributes
    ----------
    page_id:        The Notion page that drifted.
    approved_hash:  Hash captured at approval time.
    current_hash:   Hash of the payload at send time.
    """

    def __init__(self, page_id: str, approved_hash: str, current_hash: str) -> None:
        self.page_id = page_id
        self.approved_hash = approved_hash
        self.current_hash = current_hash
        super().__init__(
            f"Snapshot drift for page {page_id}: "
            f"approved={approved_hash[:12]}… current={current_hash[:12]}…"
        )


# ---------------------------------------------------------------------------
# Snapshot store
# ---------------------------------------------------------------------------

class SnapshotStore:
    """Persistent approval-snapshot store.

    All writes are atomic (tempfile + os.replace) to survive crashes.
    """

    def __init__(self, data_dir: Path | str) -> None:
        self._state_dir = Path(data_dir) / "service_state"
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._state_dir / _SNAPSHOT_FILE

    # ------------------------------------------------------------------
    # Write side
    # ------------------------------------------------------------------

    def record_approval(self, page_id: str, payload: dict) -> str:
        """Capture *payload* as the approved version for *page_id*.

        Returns the SHA-256 hash so the caller can log it.
        Idempotent: calling again with the same page_id overwrites the record.
        """
        h = canonical_hash(payload)
        data = self._load()
        data[page_id] = {
            "hash": h,
            "payload": payload,
            "approved_at": _now_iso(),
            "sent_at": None,
            "status": "approved",
        }
        self._save(data)
        log.info("Approval snapshot recorded for page %s — hash=%s…", page_id, h[:12])
        return h

    def mark_sent(self, page_id: str) -> None:
        """Record that the approved payload was sent without drift."""
        data = self._load()
        if page_id in data:
            data[page_id]["sent_at"] = _now_iso()
            data[page_id]["status"] = "sent"
            self._save(data)
        log.info("Snapshot marked sent for page %s", page_id)

    def mark_drift(self, page_id: str) -> None:
        """Record that a drift was detected for *page_id*."""
        data = self._load()
        if page_id in data:
            data[page_id]["status"] = "snapshot_drift"
            self._save(data)
        log.warning("Snapshot drift recorded for page %s", page_id)

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify_or_raise(self, page_id: str, current_payload: dict) -> None:
        """Assert that *current_payload* matches the approved snapshot.

        Raises SnapshotMismatch if:
        - No snapshot exists for *page_id* (treat as drift — unknown approval).
        - The hash of *current_payload* differs from the stored hash.

        On mismatch, automatically calls mark_drift() before raising.
        """
        data = self._load()
        record = data.get(page_id)

        if record is None:
            log.error(
                "No approval snapshot found for page %s — treating as drift", page_id
            )
            self.mark_drift(page_id)
            current_hash = canonical_hash(current_payload)
            raise SnapshotMismatch(page_id, approved_hash="(no record)", current_hash=current_hash)

        approved_hash = record["hash"]
        current_hash = canonical_hash(current_payload)

        if approved_hash != current_hash:
            self.mark_drift(page_id)
            raise SnapshotMismatch(page_id, approved_hash, current_hash)

    def get_record(self, page_id: str) -> dict | None:
        """Return the raw snapshot record for *page_id*, or None."""
        return self._load().get(page_id)

    # ------------------------------------------------------------------
    # Audit helpers
    # ------------------------------------------------------------------

    def audit_query(self) -> dict[str, list[str]]:
        """Return a summary grouping page_ids by status.

        Returns::
            {
                "approved":       [...],
                "sent":           [...],
                "snapshot_drift": [...],
            }
        """
        data = self._load()
        result: dict[str, list[str]] = {
            "approved": [],
            "sent": [],
            "snapshot_drift": [],
        }
        for page_id, record in data.items():
            status = record.get("status", "approved")
            result.setdefault(status, []).append(page_id)
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text())
            return raw if isinstance(raw, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: dict) -> None:
        fd, tmp = tempfile.mkstemp(dir=self._state_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2, sort_keys=True)
            os.replace(tmp, self._path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
