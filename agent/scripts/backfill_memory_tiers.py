"""Backfill memory tiers — re-classify rows currently tiered ``context`` that
look like ``preference`` or ``decision`` by content.

Sprint Mem-8 (Memory-Tier Architecture, issue #1849).

Idempotent: re-running on a fully-classified DB makes no changes.
Resumable: progress is persisted to a JSON state file; ``--resume`` picks up
from the last processed key. By default a stale state file is archived with a
UTC timestamp before a fresh run starts.

Scope-reality note: Migration 14 declares ``tier TEXT DEFAULT 'context'
NOT NULL`` and seeds ``user:%`` → preference / ``decision:%`` → decision
on schema apply. There are NO ``tier IS NULL`` rows in the live DB. The
backfill's primary job is **re-classification** — rows currently sitting
on ``context`` whose content (per ``classify_intent``) maps to
``preference`` or ``decision``.

Usage:
    python3 -m agent.scripts.backfill_memory_tiers --db /path/to/memory.db
    python3 -m agent.scripts.backfill_memory_tiers --db ... --dry-run
    python3 -m agent.scripts.backfill_memory_tiers --db ... --resume
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add agent/ to sys.path so ``from bridge.memory_enhancement import ...``
# resolves whether the script is run via ``python3 -m
# agent.scripts.backfill_memory_tiers`` or as a plain file path.
_SCRIPT = Path(__file__).resolve()
_AGENT_ROOT = _SCRIPT.parent.parent
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from bridge.memory_enhancement import classify_intent  # noqa: E402

log = logging.getLogger("backfill_memory_tiers")

DEFAULT_BATCH = 1000
DEFAULT_STATE_FILE = Path("data/backfill_memory_tiers_state.json")

# Tier string constants — match ``MemoryTier.value`` (see bridge.memory_tiers).
TIER_PREFERENCE = "preference"
TIER_DECISION = "decision"
TIER_CONTEXT = "context"

# Intents that map to non-CONTEXT tiers. Anything else (``fact``,
# ``instruction``, ``context``) collapses to CONTEXT and the row stays put.
_INTENT_TO_TIER: dict[str, str] = {
    "preference": TIER_PREFERENCE,
    "decision": TIER_DECISION,
}


def _initial_state() -> dict:
    """Build a fresh state dict.

    Kept as a function so ``_load_state`` and the ``--resume`` re-init path
    share the same shape (no drift between fresh and resumed runs).
    """
    return {
        "last_processed_key": "",
        "rows_classified": 0,
        "rows_unchanged": 0,
        "started_at": None,
        "completed_at": None,
    }


def _load_state(path: Path) -> dict:
    """Return persisted state, or a fresh dict when the file is absent."""
    if not path.exists():
        return _initial_state()
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("state file %s unreadable (%s) — starting fresh", path, exc)
        return _initial_state()


def _save_state(path: Path, state: dict) -> None:
    """Persist *state* atomically (write to .tmp then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(path)


def backfill(
    db_path: Path,
    *,
    dry_run: bool,
    batch_size: int,
    state_path: Path,
) -> dict:
    """Walk ``knowledge`` re-classifying ``tier='context'`` rows.

    Returns the final state dict (also persisted to ``state_path``).
    """
    state = _load_state(state_path)
    if state["started_at"] is None:
        state["started_at"] = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        while True:
            rows = conn.execute(
                """SELECT key, value, tier FROM knowledge
                   WHERE tier = ? AND key > ?
                   ORDER BY key
                   LIMIT ?""",
                (TIER_CONTEXT, state["last_processed_key"], batch_size),
            ).fetchall()

            if not rows:
                break

            updates: list[tuple[str, str]] = []
            for row in rows:
                key = row["key"]
                value = row["value"] or ""
                current_tier = row["tier"]
                try:
                    intent = classify_intent(value)
                except Exception as exc:  # noqa: BLE001 — never raise from the loop
                    log.warning(
                        "classify_intent failed for key=%r: %s — skipping",
                        key, exc,
                    )
                    state["rows_unchanged"] += 1
                    continue

                new_tier = _INTENT_TO_TIER.get(intent, TIER_CONTEXT)
                if new_tier != current_tier:
                    updates.append((new_tier, key))
                    state["rows_classified"] += 1
                else:
                    state["rows_unchanged"] += 1

            if updates and not dry_run:
                conn.executemany(
                    "UPDATE knowledge SET tier = ? WHERE key = ?",
                    updates,
                )
                conn.commit()

            state["last_processed_key"] = rows[-1]["key"]
            _save_state(state_path, state)

            log.info(
                "Batch processed: %d rows; classified=%d unchanged=%d last_key=%r",
                len(rows),
                len(updates),
                len(rows) - len(updates),
                rows[-1]["key"],
            )

        state["completed_at"] = datetime.now(timezone.utc).isoformat()
        _save_state(state_path, state)
    finally:
        conn.close()

    return state


def _archive_stale_state(state_path: Path) -> Path | None:
    """When *state_path* exists, rename it with a UTC timestamp suffix.

    Returns the archive path on rename, or None when there was nothing to
    archive. Keeps ``--resume`` unambiguous: by default a fresh run starts
    with a clean slate.
    """
    if not state_path.exists():
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archived = state_path.with_suffix(f".{ts}.bak.json")
    state_path.rename(archived)
    return archived


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path, required=True,
        help="Path to memory.db",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Walk the rows and tally classifications but issue no UPDATEs.",
    )
    parser.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH,
        help=f"Rows per batch (default {DEFAULT_BATCH}).",
    )
    parser.add_argument(
        "--state-file", type=Path, default=DEFAULT_STATE_FILE,
        help="Where to persist progress (default data/backfill_memory_tiers_state.json).",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from --state-file. Default: archive stale state and start fresh.",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="DEBUG-level logging.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not args.resume:
        archived = _archive_stale_state(args.state_file)
        if archived is not None:
            log.info("Archived previous state to %s", archived)

    state = backfill(
        args.db,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        state_path=args.state_file,
    )

    print(json.dumps(state, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
