"""Structured session knowledge capture.

Called by the memory-session-stop.sh hook at end of each session.
Reads recent conversation from SQLite, extracts structured entries,
and writes them with proper key schema, categories, tags, and salience.

Standalone — no bridge dependencies, no async, runs as a subprocess.

Key schema written:
    session:summary:<session_id>   — what happened, decisions, next steps
    decision:<slug>                — any decisions made (category: decision)
    user:<slug>                    — operator facts/preferences learned
    goal:<slug>                    — new goals surfaced (if any)

Usage:
    python -m bridge.services.session_capture [--session-id <id>] [--db <path>]
    python -m bridge.services.session_capture --recent-only  (last 2h, no session filter)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

def _resolve_data_root() -> Path:
    """Resolve data dir via the canonical helper (#1501 F4)."""
    from bridge.paths import data_root
    return data_root()


DATA_DIR = _resolve_data_root()
DB_PATH = DATA_DIR / "memory.db"

# Salience values matching memory.py conventions
SALIENCE_DECISION = 2.5
SALIENCE_USER_FACT = 3.0
SALIENCE_GOAL = 3.0
SALIENCE_SESSION_SUMMARY = 1.5

# Max chars for stored values (keep entries concise)
MAX_VALUE_LEN = 2000
MAX_SUMMARY_LEN = 1500


# ---------------------------------------------------------------------------
# DB helpers (sync — no asyncio, this runs as a subprocess)
# ---------------------------------------------------------------------------

def _open_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def upsert_knowledge(
    conn: sqlite3.Connection,
    key: str,
    value: str,
    *,
    tags: str | None = None,
    source: str = "agent",
    category: str = "reference",
    salience: float = 1.0,
) -> None:
    """Write a knowledge entry with full field population."""
    value = value[:MAX_VALUE_LEN]
    conn.execute(
        """INSERT INTO knowledge (key, value, tags, source, category, salience)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET
               value = excluded.value,
               tags = excluded.tags,
               source = excluded.source,
               category = excluded.category,
               salience = MAX(knowledge.salience, excluded.salience),
               updated_at = datetime('now')""",
        (key, value, tags, source, category, salience),
    )


def get_recent_messages(
    conn: sqlite3.Connection,
    session_id: str | None,
    hours: int = 2,
) -> list[dict]:
    """Fetch recent conversation messages for analysis."""
    if session_id:
        rows = conn.execute(
            """SELECT role, content, created_at FROM conversations
               WHERE session_id = ?
               ORDER BY created_at ASC""",
            (session_id,),
        ).fetchall()
    else:
        # Use SQLite's datetime('now') for cutoff — avoids local/UTC skew
        rows = conn.execute(
            """SELECT role, content, created_at FROM conversations
               WHERE created_at > datetime('now', ?)
               ORDER BY created_at ASC""",
            (f"-{hours} hours",),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Extraction logic — pattern-based, no Claude call (fast, free, reliable)
# ---------------------------------------------------------------------------

# Patterns Claude uses to signal important content in its responses
_DECISION_PATTERNS = [
    r"(?:decided?|decision|chose|choosing|going with|will use|using)\s+(.{10,120})",
    r"\*\*Decision\*\*[:\s]+(.{10,120})",
    r"(?:approach|strategy|plan)[:\s]+(.{10,200})",
]

_GOAL_PATTERNS = [
    r"(?:goal|objective|target|milestone)[:\s]+(.{10,120})",
    r"(?:need to|must|should|will)\s+(?:build|implement|fix|add|create|deploy)\s+(.{10,100})",
    r"\[ \]\s+(.{10,100})",  # unchecked markdown todo
]

_USER_FACT_PATTERNS = [
    r"(?:operator|operator)\s+(?:prefers?|wants?|needs?|uses?|is|has)\s+(.{10,120})",
    r"(?:always|never)\s+(?:use|do|prefer|want)\s+(.{10,100})",
]

_NEXT_STEPS_PATTERNS = [
    r"(?:next steps?|todo|action items?)[:\s]+(.{10,200})",
    r"(?:tomorrow|next session)[:\s]+(.{10,200})",
    r"- \[ \]\s+(.{10,100})",
]


def _extract_by_patterns(text: str, patterns: list[str], max_matches: int = 3) -> list[str]:
    """Extract matches from text using a list of regex patterns."""
    results = []
    for pattern in patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
            match = m.group(1).strip().rstrip(".,;:")
            if len(match) >= 10 and match not in results:
                results.append(match)
            if len(results) >= max_matches:
                break
        if len(results) >= max_matches:
            break
    return results


def _slugify(text: str, max_len: int = 40) -> str:
    """Convert text to a URL-safe slug."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:max_len]


def _build_session_summary(messages: list[dict]) -> str:
    """Build a concise session summary from conversation messages."""
    if not messages:
        return ""

    user_msgs = [m["content"] for m in messages if m["role"] == "user"]
    asst_msgs = [m["content"] for m in messages if m["role"] == "assistant"]

    if not user_msgs:
        return ""

    # First user message gives the topic
    topic = user_msgs[0][:200].replace("\n", " ")

    # Count turns
    turns = len(user_msgs)

    # Extract what was accomplished from last assistant message
    accomplished = ""
    if asst_msgs:
        last = asst_msgs[-1][:500]
        # Look for completion signals
        for phrase in ["done", "complete", "deployed", "built", "fixed", "added", "created"]:
            if phrase in last.lower():
                # Grab the sentence containing it
                for sentence in last.split("."):
                    if phrase in sentence.lower() and len(sentence) > 20:
                        accomplished = sentence.strip()[:200]
                        break
                if accomplished:
                    break

    # Extract next steps from assistant messages
    next_steps = []
    for msg in asst_msgs[-3:]:  # look at last 3 assistant messages
        next_steps.extend(_extract_by_patterns(msg, _NEXT_STEPS_PATTERNS, max_matches=2))
    next_steps = next_steps[:3]

    parts = [f"Topic: {topic}", f"Turns: {turns}"]
    if accomplished:
        parts.append(f"Accomplished: {accomplished}")
    if next_steps:
        parts.append("Next steps: " + "; ".join(next_steps))

    return "\n".join(parts)[:MAX_SUMMARY_LEN]


def extract_entries(
    messages: list[dict],
    session_id: str | None,
) -> list[dict]:
    """
    Extract structured knowledge entries from conversation messages.

    Returns a list of dicts ready for upsert_knowledge():
        {key, value, tags, category, salience}
    """
    if not messages:
        return []

    entries = []
    now_str = datetime.now().strftime("%Y-%m-%d")

    # Concatenate assistant messages for pattern extraction
    asst_text = "\n".join(m["content"] for m in messages if m["role"] == "assistant")
    user_text = "\n".join(m["content"] for m in messages if m["role"] == "user")

    # 1. Session summary — always write if there's real content
    summary = _build_session_summary(messages)
    if summary and session_id:
        entries.append({
            "key": f"session:summary:{session_id}",
            "value": summary,
            "tags": f"session,{now_str}",
            "category": "process",
            "salience": SALIENCE_SESSION_SUMMARY,
        })

    # 2. Decisions — from assistant messages (where decisions are announced)
    decisions = _extract_by_patterns(asst_text, _DECISION_PATTERNS, max_matches=5)
    for i, decision in enumerate(decisions):
        slug = _slugify(decision)
        entries.append({
            "key": f"decision:{now_str}-{slug}",
            "value": decision,
            "tags": f"decision,{now_str},session",
            "category": "decision",
            "salience": SALIENCE_DECISION,
        })

    # 3. User facts — from both sides (operator shares, agent acknowledges)
    user_facts = _extract_by_patterns(user_text, _USER_FACT_PATTERNS, max_matches=3)
    for fact in user_facts:
        slug = _slugify(fact)
        entries.append({
            "key": f"user:{slug}",
            "value": fact,
            "tags": f"user-fact,{now_str}",
            "category": "preference",
            "salience": SALIENCE_USER_FACT,
        })

    # 4. New goals — from user messages (operator declares goals)
    goals = _extract_by_patterns(user_text, _GOAL_PATTERNS, max_matches=3)
    for goal in goals:
        slug = _slugify(goal)
        # Don't duplicate existing goals — key collision handled by upsert
        entries.append({
            "key": f"goal:{slug}",
            "value": json.dumps({"description": goal, "source": "session-capture", "date": now_str}),
            "tags": f"goal,{now_str}",
            "category": "project",
            "salience": SALIENCE_GOAL,
        })

    # Deduplicate by key (keep first occurrence)
    seen_keys: set[str] = set()
    unique_entries = []
    for entry in entries:
        if entry["key"] not in seen_keys:
            seen_keys.add(entry["key"])
            unique_entries.append(entry)

    return unique_entries


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_capture(
    db_path: Path,
    session_id: str | None = None,
    recent_hours: int = 2,
    dry_run: bool = False,
) -> int:
    """
    Run session capture. Returns count of entries written.
    """
    try:
        conn = _open_db(db_path)
    except Exception as e:
        log.error("Cannot open DB at %s: %s", db_path, e)
        return 0

    try:
        messages = get_recent_messages(conn, session_id, hours=recent_hours)

        if not messages:
            log.info("No messages to capture (session_id=%s, hours=%d)", session_id, recent_hours)
            conn.close()
            return 0

        entries = extract_entries(messages, session_id)

        if not entries:
            log.info("No structured entries extracted from %d messages", len(messages))
            conn.close()
            return 0

        if dry_run:
            for e in entries:
                print(f"  [{e['category']}] {e['key']}: {e['value'][:80]}...")
            conn.close()
            return len(entries)

        written = 0
        for entry in entries:
            try:
                upsert_knowledge(
                    conn,
                    key=entry["key"],
                    value=entry["value"],
                    tags=entry.get("tags"),
                    source="session-capture",
                    category=entry["category"],
                    salience=entry["salience"],
                )
                written += 1
            except Exception as e:
                log.warning("Failed to write entry %s: %s", entry["key"], e)

        conn.commit()
        log.info(
            "Session capture: %d entries written from %d messages (session=%s)",
            written, len(messages), session_id,
        )
        conn.close()
        return written

    except Exception as e:
        log.error("Session capture failed: %s", e)
        try:
            conn.close()
        except Exception:
            pass
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Structured session knowledge capture")
    parser.add_argument("--session-id", help="Claude session ID to capture")
    parser.add_argument("--db", default=str(DB_PATH), help="Path to memory.db")
    parser.add_argument("--hours", type=int, default=2, help="Hours of history if no session-id")
    parser.add_argument("--dry-run", action="store_true", help="Print entries without writing")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [session_capture] %(levelname)s %(message)s",
    )

    count = run_capture(
        db_path=Path(args.db),
        session_id=args.session_id or None,
        recent_hours=args.hours,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        print(f"\n{count} entries would be written")
    else:
        print(f"session_capture: {count} entries written")

    sys.exit(0)


if __name__ == "__main__":
    main()
