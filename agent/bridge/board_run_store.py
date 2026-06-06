"""Board-run persistence + outcome tracking (Board Phase 2 WS4 #2391, Phase 3 WS2 #2392).

A file-based store under ``data/board-runs/`` that closes the loop between
what the strategy board recommends and what actually ships:

- **Run records** ``data/board-runs/<date>-<session_id>.json`` — the full
  synthesis of a board deliberation, written when a ``/board`` run completes.
- **Outcome records** ``data/board-runs/<run_id>-outcomes.json`` — appended
  when an issue tagged with this run's ``board_run_id`` closes.

The store is deliberately decoupled from the board run path: callers hand it a
finished result; it never invokes the board. This keeps the seam shallow (a
board run can fail without ever touching this store) and avoids any coupling to
the Zone 4 run machinery owned elsewhere.

Acceptance contracts honored:
- #2391 WS4: full synthesis persisted; ``list_recent`` powers ``/board-history``;
  every run carries a stable ``board_run_id`` issues can link back to.
- #2392 WS2: issue closure writes an outcome record keyed by ``board_run_id``;
  ``compute_implementation_rate`` aggregates generated/closed/avg-close-time per
  run for the monthly CEO review; ``outcome_summary_for_prompt`` renders a short
  context block to inject into the next board deliberation.

All timestamps are ISO-8601 UTC. All file writes are atomic (temp + rename) so a
crash mid-write never leaves a half-JSON record the dashboard or CEO review can
choke on. Reads are defensive: a corrupt file is skipped, never fatal.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

# A board_run_id is "board-<YYYYMMDD>-<8hex>". The date prefix makes the run
# file sortable by name; the hex suffix guarantees uniqueness within a day.
_RUN_ID_RE = re.compile(r"^board-\d{8}-[0-9a-f]{8}$")


def new_board_run_id(now: datetime | None = None) -> str:
    """Generate a stable, sortable board run id."""
    now = now or datetime.now(timezone.utc)
    return f"board-{now.strftime('%Y%m%d')}-{uuid4().hex[:8]}"


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON atomically (temp file + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    os.replace(tmp, path)


@dataclass(frozen=True)
class BoardRunRecord:
    """One persisted board deliberation. Immutable once written."""

    board_run_id: str
    session_id: str
    question: str
    synthesis: str
    success: bool
    member_count: int
    duration_seconds: float
    cost_usd: float
    phase: str | None
    created_at: str
    linked_issues: tuple[int, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "board_run_id": self.board_run_id,
            "session_id": self.session_id,
            "question": self.question,
            "synthesis": self.synthesis,
            "success": self.success,
            "member_count": self.member_count,
            "duration_seconds": self.duration_seconds,
            "cost_usd": self.cost_usd,
            "phase": self.phase,
            "created_at": self.created_at,
            "linked_issues": list(self.linked_issues),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BoardRunRecord":
        return cls(
            board_run_id=str(data.get("board_run_id", "")),
            session_id=str(data.get("session_id", "")),
            question=str(data.get("question", "")),
            synthesis=str(data.get("synthesis", "")),
            success=bool(data.get("success", False)),
            member_count=int(data.get("member_count", 0) or 0),
            duration_seconds=float(data.get("duration_seconds", 0.0) or 0.0),
            cost_usd=float(data.get("cost_usd", 0.0) or 0.0),
            phase=data.get("phase"),
            created_at=str(data.get("created_at", "")),
            linked_issues=tuple(int(i) for i in (data.get("linked_issues") or [])),
        )


class BoardRunStore:
    """File-based store for board runs and their downstream outcomes."""

    def __init__(self, base_dir: str | Path) -> None:
        self._dir = Path(base_dir) / "board-runs"

    @property
    def directory(self) -> Path:
        return self._dir

    # ------------------------------------------------------------------
    # Run persistence (#2391 WS4)
    # ------------------------------------------------------------------

    def _run_path(self, record: BoardRunRecord) -> Path:
        date = (record.created_at or "")[:10] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._dir / f"{date}-{record.session_id}.json"

    def record_run(
        self,
        *,
        session_id: str,
        question: str,
        synthesis: str,
        success: bool,
        member_count: int = 0,
        duration_seconds: float = 0.0,
        cost_usd: float = 0.0,
        phase: str | None = None,
        board_run_id: str | None = None,
    ) -> BoardRunRecord:
        """Persist a finished board run and return its immutable record."""
        now = datetime.now(timezone.utc)
        record = BoardRunRecord(
            board_run_id=board_run_id or new_board_run_id(now),
            session_id=session_id,
            question=question,
            synthesis=synthesis,
            success=success,
            member_count=member_count,
            duration_seconds=duration_seconds,
            cost_usd=cost_usd,
            phase=phase,
            created_at=now.isoformat(),
        )
        _atomic_write_json(self._run_path(record), record.to_dict())
        # Index file keyed by run id so outcomes can resolve the run file
        # without scanning. One small pointer file per run.
        _atomic_write_json(
            self._dir / f"{record.board_run_id}-index.json",
            {"run_file": self._run_path(record).name},
        )
        return record

    def _iter_run_files(self) -> list[Path]:
        if not self._dir.exists():
            return []
        # Run files are "<date>-<session>.json"; exclude *-outcomes.json and
        # *-index.json bookkeeping files.
        files = [
            p for p in self._dir.glob("*.json")
            if not p.name.endswith("-outcomes.json")
            and not p.name.endswith("-index.json")
        ]
        return sorted(files, key=lambda p: p.name, reverse=True)

    def list_recent(self, limit: int = 10) -> list[BoardRunRecord]:
        """Most-recent board runs first (powers ``/board-history``)."""
        records: list[BoardRunRecord] = []
        for path in self._iter_run_files():
            try:
                records.append(BoardRunRecord.from_dict(json.loads(path.read_text())))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("board_run_store: skipping corrupt run %s: %s", path.name, exc)
            if len(records) >= limit:
                break
        return records

    def get_run(self, board_run_id: str) -> BoardRunRecord | None:
        if not _RUN_ID_RE.match(board_run_id):
            return None
        for path in self._iter_run_files():
            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if data.get("board_run_id") == board_run_id:
                return BoardRunRecord.from_dict(data)
        return None

    def link_issue(self, board_run_id: str, issue_number: int) -> bool:
        """Record that an issue was generated from this board run.

        Rewrites the run file with the issue appended to ``linked_issues``.
        Returns False if the run is unknown. Idempotent on the issue number.
        """
        record = self.get_run(board_run_id)
        if record is None:
            return False
        if issue_number in record.linked_issues:
            return True
        updated = BoardRunRecord(
            board_run_id=record.board_run_id,
            session_id=record.session_id,
            question=record.question,
            synthesis=record.synthesis,
            success=record.success,
            member_count=record.member_count,
            duration_seconds=record.duration_seconds,
            cost_usd=record.cost_usd,
            phase=record.phase,
            created_at=record.created_at,
            linked_issues=record.linked_issues + (issue_number,),
        )
        _atomic_write_json(self._run_path(updated), updated.to_dict())
        return True

    # ------------------------------------------------------------------
    # Outcome tracking (#2392 WS2)
    # ------------------------------------------------------------------

    def _outcomes_path(self, board_run_id: str) -> Path:
        return self._dir / f"{board_run_id}-outcomes.json"

    def record_issue_closed(
        self,
        board_run_id: str,
        issue_number: int,
        *,
        opened_at: str | None = None,
        closed_at: str | None = None,
    ) -> None:
        """Append an issue-close outcome to the run's outcomes file.

        Idempotent on ``issue_number`` — re-recording a close updates the
        existing entry rather than duplicating it.
        """
        if not _RUN_ID_RE.match(board_run_id):
            logger.warning("board_run_store: bad board_run_id %r on close", board_run_id)
            return
        path = self._outcomes_path(board_run_id)
        outcomes: dict = {"board_run_id": board_run_id, "closed_issues": []}
        if path.exists():
            try:
                outcomes = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                outcomes = {"board_run_id": board_run_id, "closed_issues": []}
        closed = [c for c in outcomes.get("closed_issues", []) if c.get("issue") != issue_number]
        closed.append({
            "issue": issue_number,
            "opened_at": opened_at,
            "closed_at": closed_at or datetime.now(timezone.utc).isoformat(),
        })
        outcomes["closed_issues"] = closed
        _atomic_write_json(path, outcomes)

    def get_outcomes(self, board_run_id: str) -> dict:
        path = self._outcomes_path(board_run_id)
        if not path.exists():
            return {"board_run_id": board_run_id, "closed_issues": []}
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {"board_run_id": board_run_id, "closed_issues": []}

    # ------------------------------------------------------------------
    # Aggregation for the monthly CEO review (#2392 WS2)
    # ------------------------------------------------------------------

    def compute_implementation_rate(self, limit: int = 50) -> dict:
        """Per-run generated/closed/avg-close-time across recent board runs."""
        per_run: list[dict] = []
        total_generated = 0
        total_closed = 0
        for record in self.list_recent(limit=limit):
            generated = len(record.linked_issues)
            outcomes = self.get_outcomes(record.board_run_id)
            closed_entries = outcomes.get("closed_issues", [])
            closed = len(closed_entries)
            close_times = _close_durations_hours(closed_entries)
            avg_close = round(sum(close_times) / len(close_times), 2) if close_times else None
            total_generated += generated
            total_closed += closed
            per_run.append({
                "board_run_id": record.board_run_id,
                "phase": record.phase,
                "member_count": record.member_count,
                "cost_usd": round(record.cost_usd, 6),
                "issues_generated": generated,
                "issues_closed": closed,
                "avg_close_hours": avg_close,
            })
        rate = round(total_closed / total_generated, 3) if total_generated else None
        return {
            "runs": per_run,
            "total_generated": total_generated,
            "total_closed": total_closed,
            "implementation_rate": rate,
        }

    def outcome_summary_for_prompt(self, limit: int = 5) -> str:
        """Short text block to inject into the next board deliberation (#2392 WS2)."""
        stats = self.compute_implementation_rate(limit=limit)
        if not stats["runs"]:
            return ""
        lines = ["Prior board-run outcomes (for context):"]
        for r in stats["runs"]:
            lines.append(
                f"- {r['board_run_id']}: {r['issues_closed']}/{r['issues_generated']} "
                f"issues closed"
                + (f", avg close {r['avg_close_hours']}h" if r["avg_close_hours"] else "")
            )
        if stats["implementation_rate"] is not None:
            lines.append(f"Overall implementation rate: {stats['implementation_rate']:.0%}")
        return "\n".join(lines)


def _close_durations_hours(closed_entries: list[dict]) -> list[float]:
    """Hours between open and close for entries that carry both timestamps."""
    durations: list[float] = []
    for entry in closed_entries:
        opened = entry.get("opened_at")
        closed = entry.get("closed_at")
        if not opened or not closed:
            continue
        try:
            o = datetime.fromisoformat(opened)
            c = datetime.fromisoformat(closed)
        except (ValueError, TypeError):
            continue
        durations.append(max(0.0, (c - o).total_seconds() / 3600.0))
    return durations
