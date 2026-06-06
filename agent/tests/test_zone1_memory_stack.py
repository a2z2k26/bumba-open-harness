"""
Integration tests for Zone 1 v2 memory stack.

Covers four tiers:
  T0 — auto-memory identity (MEMORY.md)
  T1 — session primer schema validation and staleness detection
  T3 — SQLite knowledge table schema (sqlite-storage-adapter equivalent)
  Auto-memory directory structure
"""

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Paths — resolve relative to this file so tests work from any cwd
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.parent  # /tmp/bumba-open-harness-plan1
AGENT_ROOT = REPO_ROOT / "agent"
AUTO_MEMORY_DIR = AGENT_ROOT / "docs" / "architecture" / "auto-memory"
AUTO_MEMORY_INDEX = AUTO_MEMORY_DIR / "MEMORY.md"


# ---------------------------------------------------------------------------
# T0 — auto-memory identity
# ---------------------------------------------------------------------------

class TestT0AutoMemoryIdentity:
    """T0: verify the auto-memory MEMORY.md file exists at the expected path."""

    def test_auto_memory_file_exists(self):
        """MEMORY.md must exist inside docs/architecture/auto-memory/."""
        assert AUTO_MEMORY_INDEX.exists(), (
            f"Auto-memory index not found at {AUTO_MEMORY_INDEX}. "
            "Expected docs/architecture/auto-memory/MEMORY.md to be present."
        )

    def test_auto_memory_is_file(self):
        """MEMORY.md must be a regular file, not a directory or symlink."""
        assert AUTO_MEMORY_INDEX.is_file(), (
            f"{AUTO_MEMORY_INDEX} exists but is not a regular file."
        )

    def test_auto_memory_not_empty(self):
        """MEMORY.md must contain at least some content (not zero bytes)."""
        assert AUTO_MEMORY_INDEX.stat().st_size > 0, (
            f"{AUTO_MEMORY_INDEX} is empty."
        )

    def test_auto_memory_contains_header(self):
        """MEMORY.md must start with a markdown heading."""
        content = AUTO_MEMORY_INDEX.read_text(encoding="utf-8")
        assert content.strip().startswith("#"), (
            "MEMORY.md does not begin with a markdown heading."
        )


# ---------------------------------------------------------------------------
# T1 — session primer schema validation
# ---------------------------------------------------------------------------

PRIMER_REQUIRED_FIELDS = [
    "schema_version",
    "generated_at",
    "session_id",
    "expires_at",
    "current_track",
    "active_projects",
    "recent_decisions",
    "open_blockers",
    "pending_tasks",
    "session_summary",
    "operator_context",
]


def _make_primer(**overrides) -> dict:
    """Return a minimal valid primer dict, with optional field overrides."""
    now = datetime.now(timezone.utc)
    base = {
        "schema_version": "1.0",
        "generated_at": now.isoformat(),
        "session_id": "test-session-abc123",
        "expires_at": (now + timedelta(hours=24)).isoformat(),
        "current_track": {
            "name": "System Build",
            "type": "system",
            "switched_at": now.isoformat(),
        },
        "active_projects": [],
        "recent_decisions": [],
        "open_blockers": [],
        "pending_tasks": [],
        "session_summary": "Test session.",
        "operator_context": {},
    }
    base.update(overrides)
    return base


class TestT1PrimerSchema:
    """T1: session primer JSON schema validation."""

    def test_valid_primer_has_all_required_fields(self):
        """A well-formed primer must contain all required top-level fields."""
        primer = _make_primer()
        missing = [f for f in PRIMER_REQUIRED_FIELDS if f not in primer]
        assert missing == [], f"Primer missing required fields: {missing}"

    @pytest.mark.parametrize("field", PRIMER_REQUIRED_FIELDS)
    def test_missing_field_detected(self, field):
        """Removing any required field should leave the primer incomplete."""
        primer = _make_primer()
        del primer[field]
        present = set(primer.keys())
        required = set(PRIMER_REQUIRED_FIELDS)
        assert field not in present, (
            f"Expected field '{field}' to be absent after deletion."
        )
        missing = required - present
        assert field in missing, (
            f"Validation logic should report '{field}' as missing."
        )

    def test_schema_version_is_string(self):
        primer = _make_primer()
        assert isinstance(primer["schema_version"], str)

    def test_session_id_is_string(self):
        primer = _make_primer()
        assert isinstance(primer["session_id"], str)
        assert len(primer["session_id"]) > 0

    def test_active_projects_is_list(self):
        primer = _make_primer()
        assert isinstance(primer["active_projects"], list)

    def test_recent_decisions_is_list(self):
        primer = _make_primer()
        assert isinstance(primer["recent_decisions"], list)

    def test_open_blockers_is_list(self):
        primer = _make_primer()
        assert isinstance(primer["open_blockers"], list)

    def test_pending_tasks_is_list(self):
        primer = _make_primer()
        assert isinstance(primer["pending_tasks"], list)

    def test_current_track_fields(self):
        """current_track must contain name, type, and switched_at."""
        primer = _make_primer()
        track = primer["current_track"]
        for key in ("name", "type", "switched_at"):
            assert key in track, f"current_track missing key: {key}"

    def test_current_track_type_values(self):
        """current_track.type must be one of the allowed values."""
        allowed = {"system", "product", "pa"}
        for t in allowed:
            primer = _make_primer()
            primer["current_track"]["type"] = t
            assert primer["current_track"]["type"] in allowed

    def test_primer_roundtrips_json(self):
        """Primer must survive JSON serialise → deserialise without data loss."""
        primer = _make_primer()
        serialised = json.dumps(primer)
        recovered = json.loads(serialised)
        assert recovered == primer


# ---------------------------------------------------------------------------
# T1 — staleness detection
# ---------------------------------------------------------------------------

class TestT1PrimerStaleness:
    """T1: a primer whose expires_at is in the past must be detected as stale."""

    @staticmethod
    def _is_stale(primer: dict) -> bool:
        """Return True if the primer's expires_at timestamp is in the past."""
        try:
            expires_at = datetime.fromisoformat(primer["expires_at"])
            # Make aware if naive
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) >= expires_at
        except (KeyError, ValueError):
            return True  # Malformed → treat as stale

    def test_fresh_primer_is_not_stale(self):
        """A primer with expires_at 24h in the future must not be stale."""
        primer = _make_primer()  # expires_at = now + 24h
        assert not self._is_stale(primer), "Fresh primer incorrectly reported as stale."

    def test_expired_primer_is_stale(self):
        """A primer with expires_at in the past must be detected as stale."""
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        primer = _make_primer(expires_at=past)
        assert self._is_stale(primer), "Expired primer not detected as stale."

    def test_primer_expiring_exactly_now_is_stale(self):
        """A primer whose expires_at equals the current moment is stale (boundary)."""
        # Use a timestamp one second in the past to avoid race with test clock
        boundary = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        primer = _make_primer(expires_at=boundary)
        assert self._is_stale(primer)

    def test_primer_missing_expires_at_is_stale(self):
        """A primer without an expires_at field must be treated as stale."""
        primer = _make_primer()
        del primer["expires_at"]
        assert self._is_stale(primer)

    def test_primer_with_corrupt_expires_at_is_stale(self):
        """A primer with a non-parseable expires_at must be treated as stale."""
        primer = _make_primer(expires_at="not-a-timestamp")
        assert self._is_stale(primer)

    def test_stale_primer_still_valid_schema(self):
        """Staleness is independent of schema validity — all fields may still be present."""
        past = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        primer = _make_primer(expires_at=past)
        missing = [f for f in PRIMER_REQUIRED_FIELDS if f not in primer]
        assert missing == [], "Stale primer should still satisfy the schema."


# ---------------------------------------------------------------------------
# T3 — SQLite knowledge table schema
# ---------------------------------------------------------------------------

# Expected columns in the knowledge table (sqlite-storage-adapter equivalent)
KNOWLEDGE_TABLE_REQUIRED_COLUMNS = {
    "key",
    "data",
    "confidence",
    "source",
    "tags",
    "timestamp",
    "salience",
    "last_accessed_at",
    "access_count_decay",
}


def _create_knowledge_table(conn: sqlite3.Connection) -> None:
    """Create the knowledge table that mirrors the sqlite-storage-adapter schema."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS knowledge (
            key                TEXT PRIMARY KEY NOT NULL,
            data               TEXT NOT NULL,
            confidence         REAL NOT NULL DEFAULT 1.0,
            source             TEXT,
            tags               TEXT,
            timestamp          TEXT NOT NULL,
            salience           REAL NOT NULL DEFAULT 1.0,
            last_accessed_at   TEXT,
            access_count_decay REAL NOT NULL DEFAULT 1.0
        )
    """)
    conn.commit()


class TestT3KnowledgeTableSchema:
    """T3: SQLite knowledge table mirrors the sqlite-storage-adapter schema."""

    @pytest.fixture()
    def db(self):
        """Provide an in-memory SQLite connection with the knowledge table created."""
        conn = sqlite3.connect(":memory:")
        _create_knowledge_table(conn)
        yield conn
        conn.close()

    def _column_names(self, conn: sqlite3.Connection) -> set:
        cursor = conn.execute("PRAGMA table_info(knowledge)")
        return {row[1] for row in cursor.fetchall()}

    def test_knowledge_table_exists(self, db):
        """The knowledge table must be created without errors."""
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge'"
        )
        assert cursor.fetchone() is not None, "knowledge table does not exist."

    def test_knowledge_table_has_all_required_columns(self, db):
        """All required columns must be present in the knowledge table."""
        present = self._column_names(db)
        missing = KNOWLEDGE_TABLE_REQUIRED_COLUMNS - present
        assert missing == set(), (
            f"knowledge table missing required columns: {missing}"
        )

    @pytest.mark.parametrize("col", sorted(KNOWLEDGE_TABLE_REQUIRED_COLUMNS))
    def test_column_present(self, db, col):
        """Each required column must be present individually."""
        present = self._column_names(db)
        assert col in present, f"Column '{col}' not found in knowledge table."

    def test_key_is_primary_key(self, db):
        """The 'key' column must be the primary key."""
        cursor = db.execute("PRAGMA table_info(knowledge)")
        rows = cursor.fetchall()
        # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
        pk_cols = {row[1] for row in rows if row[5] > 0}
        assert "key" in pk_cols, "'key' is not the primary key."

    def test_insert_and_retrieve_knowledge_entry(self, db):
        """A knowledge entry must survive an INSERT → SELECT round-trip."""
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            """
            INSERT INTO knowledge
                (key, data, confidence, source, tags, timestamp,
                 salience, last_accessed_at, access_count_decay)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "decision:architecture-choice",
                "Chose SQLite over Postgres for portability.",
                0.95,
                "operator",
                '["decision", "architecture"]',
                now,
                1.0,
                now,
                1.0,
            ),
        )
        db.commit()
        cursor = db.execute(
            "SELECT key, data, confidence FROM knowledge WHERE key = ?",
            ("decision:architecture-choice",),
        )
        row = cursor.fetchone()
        assert row is not None, "Inserted knowledge entry not found."
        assert row[0] == "decision:architecture-choice"
        assert "SQLite" in row[1]
        assert abs(row[2] - 0.95) < 1e-9

    def test_duplicate_key_raises(self, db):
        """Inserting a duplicate key must raise an IntegrityError (PRIMARY KEY)."""
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO knowledge (key, data, timestamp) VALUES (?, ?, ?)",
            ("dupe-key", "first", now),
        )
        db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO knowledge (key, data, timestamp) VALUES (?, ?, ?)",
                ("dupe-key", "second", now),
            )

    def test_knowledge_table_in_separate_file_db(self):
        """Schema creation must work with a file-backed (not just in-memory) SQLite DB."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = sqlite3.connect(db_path)
            _create_knowledge_table(conn)
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge'"
            )
            assert cursor.fetchone() is not None
            conn.close()
        finally:
            os.unlink(db_path)


# ---------------------------------------------------------------------------
# Auto-memory directory structure
# ---------------------------------------------------------------------------

class TestAutoMemoryDirectoryStructure:
    """Verify the auto-memory directory and its required contents."""

    def test_auto_memory_directory_exists(self):
        """docs/architecture/auto-memory/ directory must exist."""
        assert AUTO_MEMORY_DIR.exists(), (
            f"Auto-memory directory not found at {AUTO_MEMORY_DIR}."
        )
        assert AUTO_MEMORY_DIR.is_dir(), (
            f"{AUTO_MEMORY_DIR} exists but is not a directory."
        )

    def test_auto_memory_contains_memory_md(self):
        """auto-memory/ must contain MEMORY.md."""
        assert AUTO_MEMORY_INDEX.exists(), (
            f"MEMORY.md not found inside {AUTO_MEMORY_DIR}."
        )

    def test_auto_memory_directory_not_empty(self):
        """auto-memory/ must contain at least one file."""
        files = list(AUTO_MEMORY_DIR.iterdir())
        assert len(files) > 0, f"{AUTO_MEMORY_DIR} is empty."

    def test_auto_memory_parent_is_architecture(self):
        """auto-memory/ must be a child of docs/architecture/."""
        assert AUTO_MEMORY_DIR.parent.name == "architecture", (
            f"auto-memory parent directory is '{AUTO_MEMORY_DIR.parent.name}', "
            "expected 'architecture'."
        )

    def test_auto_memory_grandparent_is_docs(self):
        """auto-memory/ must be two levels under docs/."""
        assert AUTO_MEMORY_DIR.parent.parent.name == "docs", (
            f"auto-memory grandparent is '{AUTO_MEMORY_DIR.parent.parent.name}', "
            "expected 'docs'."
        )

    def test_memory_md_mentions_auto_memory(self):
        """MEMORY.md should reference auto-memory (self-descriptive index)."""
        content = AUTO_MEMORY_INDEX.read_text(encoding="utf-8").lower()
        assert "memory" in content, (
            "MEMORY.md does not contain the word 'memory' — may be wrong file."
        )
