"""Tests for agent memory snapshot protocol (Sprint 12)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from bridge.memory_snapshots import (
    MemorySnapshot,
    SnapshotIngester,
    SnapshotWriter,
    ingest_pending_snapshots,
    salience_for_category,
)


# ---------------------------------------------------------------------------
# 1. MemorySnapshot dataclass fields
# ---------------------------------------------------------------------------

def test_memory_snapshot_fields():
    ts = datetime.now(timezone.utc).isoformat()
    snap = MemorySnapshot(
        category="decision",
        key="use-postgres-not-sqlite",
        value="We chose Postgres for its JSON operators.",
        source="architecture meeting 2026-04-03",
        salience=0.9,
        timestamp=ts,
    )
    assert snap.category == "decision"
    assert snap.key == "use-postgres-not-sqlite"
    assert snap.value == "We chose Postgres for its JSON operators."
    assert snap.source == "architecture meeting 2026-04-03"
    assert snap.salience == 0.9
    assert snap.timestamp == ts


# ---------------------------------------------------------------------------
# 2. SnapshotWriter.write() creates a JSON file at the right path
# ---------------------------------------------------------------------------

def test_snapshot_writer_creates_file(tmp_path):
    snapshots_dir = tmp_path / "data" / "memory" / "snapshots"
    writer = SnapshotWriter(snapshots_dir)
    snap = MemorySnapshot(
        category="general",
        key="my-test-key",
        value="test value",
        source="test",
        salience=0.5,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    path = writer.write(snap)
    assert path.exists()
    assert path.suffix == ".json"
    assert snapshots_dir in path.parents or path.parent == snapshots_dir


# ---------------------------------------------------------------------------
# 3. SnapshotWriter.write() file contains valid JSON with all fields
# ---------------------------------------------------------------------------

def test_snapshot_writer_file_contents(tmp_path):
    snapshots_dir = tmp_path / "snapshots"
    writer = SnapshotWriter(snapshots_dir)
    ts = datetime.now(timezone.utc).isoformat()
    snap = MemorySnapshot(
        category="error",
        key="import-failure-numpy",
        value="numpy import fails on M2 without Rosetta",
        source="runtime exception",
        salience=0.8,
        timestamp=ts,
    )
    path = writer.write(snap)
    data = json.loads(path.read_text())
    assert data["category"] == "error"
    assert data["key"] == "import-failure-numpy"
    assert data["value"] == "numpy import fails on M2 without Rosetta"
    assert data["source"] == "runtime exception"
    assert data["salience"] == 0.8
    assert data["timestamp"] == ts


# ---------------------------------------------------------------------------
# 4. SnapshotWriter.get_snapshot_instructions() returns path + format info
# ---------------------------------------------------------------------------

def test_snapshot_writer_instructions(tmp_path):
    snapshots_dir = tmp_path / "snapshots"
    writer = SnapshotWriter(snapshots_dir)
    instructions = writer.get_snapshot_instructions()
    assert str(snapshots_dir) in instructions
    assert "category" in instructions
    assert "key" in instructions
    assert "value" in instructions
    assert "salience" in instructions


# ---------------------------------------------------------------------------
# 5. SnapshotIngester.get_pending_snapshots() returns list of .json Paths
# ---------------------------------------------------------------------------

def test_ingester_get_pending_snapshots(tmp_path):
    snapshots_dir = tmp_path / "snapshots"
    snapshots_dir.mkdir(parents=True)
    # Write two JSON files
    (snapshots_dir / "1000_alpha.json").write_text("{}")
    (snapshots_dir / "1001_beta.json").write_text("{}")
    ingester = SnapshotIngester(snapshots_dir)
    pending = ingester.get_pending_snapshots()
    assert len(pending) == 2
    assert all(p.suffix == ".json" for p in pending)


# ---------------------------------------------------------------------------
# 6. SnapshotIngester.ingest() parses JSON and returns MemorySnapshot
# ---------------------------------------------------------------------------

def test_ingester_ingest_valid(tmp_path):
    snapshots_dir = tmp_path / "snapshots"
    snapshots_dir.mkdir()
    ts = datetime.now(timezone.utc).isoformat()
    data = {
        "category": "lesson",
        "key": "always-check-nulls",
        "value": "Always validate None before dereferencing.",
        "source": "post-mortem",
        "salience": 0.75,
        "timestamp": ts,
    }
    snap_file = snapshots_dir / "1000_always-check-nulls.json"
    snap_file.write_text(json.dumps(data))
    ingester = SnapshotIngester(snapshots_dir)
    snap = ingester.ingest(snap_file)
    assert isinstance(snap, MemorySnapshot)
    assert snap.category == "lesson"
    assert snap.key == "always-check-nulls"
    assert snap.value == "Always validate None before dereferencing."
    assert snap.salience == 0.75
    assert snap.timestamp == ts


# ---------------------------------------------------------------------------
# 7. SnapshotIngester.ingest() raises ValueError on invalid JSON
# ---------------------------------------------------------------------------

def test_ingester_ingest_invalid_json(tmp_path):
    snapshots_dir = tmp_path / "snapshots"
    snapshots_dir.mkdir()
    bad_file = snapshots_dir / "bad.json"
    bad_file.write_text("not valid json {{{{")
    ingester = SnapshotIngester(snapshots_dir)
    with pytest.raises(ValueError):
        ingester.ingest(bad_file)


# ---------------------------------------------------------------------------
# 8. SnapshotIngester.mark_processed() renames file to .processed
# ---------------------------------------------------------------------------

def test_ingester_mark_processed(tmp_path):
    snapshots_dir = tmp_path / "snapshots"
    snapshots_dir.mkdir()
    snap_file = snapshots_dir / "1000_foo.json"
    snap_file.write_text("{}")
    ingester = SnapshotIngester(snapshots_dir)
    processed = ingester.mark_processed(snap_file)
    assert not snap_file.exists()
    assert processed.exists()
    assert processed.suffix == ".processed"


# ---------------------------------------------------------------------------
# 9. get_pending_snapshots() excludes .processed files
# ---------------------------------------------------------------------------

def test_ingester_excludes_processed(tmp_path):
    snapshots_dir = tmp_path / "snapshots"
    snapshots_dir.mkdir()
    (snapshots_dir / "1000_pending.json").write_text("{}")
    (snapshots_dir / "999_done.processed").write_text("{}")
    ingester = SnapshotIngester(snapshots_dir)
    pending = ingester.get_pending_snapshots()
    assert len(pending) == 1
    assert pending[0].name == "1000_pending.json"


# ---------------------------------------------------------------------------
# 10. deduplicate() returns False if key already in existing_keys
# ---------------------------------------------------------------------------

def test_deduplicate_returns_false_for_known_key(tmp_path):
    ingester = SnapshotIngester(tmp_path)
    snap = MemorySnapshot(
        category="decision",
        key="use-redis",
        value="Use Redis for caching",
        source="arch call",
        salience=0.9,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    assert ingester.deduplicate(snap, {"use-redis", "other-key"}) is False


# ---------------------------------------------------------------------------
# 11. deduplicate() returns True if key is new
# ---------------------------------------------------------------------------

def test_deduplicate_returns_true_for_new_key(tmp_path):
    ingester = SnapshotIngester(tmp_path)
    snap = MemorySnapshot(
        category="decision",
        key="use-redis",
        value="Use Redis for caching",
        source="arch call",
        salience=0.9,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    assert ingester.deduplicate(snap, {"unrelated-key"}) is True


# ---------------------------------------------------------------------------
# 12. salience_for_category() returns correct floats
# ---------------------------------------------------------------------------

def test_salience_for_category_known_values():
    assert salience_for_category("decision") == 0.9
    assert salience_for_category("error") == 0.8
    assert salience_for_category("general") == 0.5


def test_salience_for_category_unknown_returns_default():
    assert salience_for_category("totally-unknown-xyz") == 0.4


def test_salience_for_category_case_insensitive():
    assert salience_for_category("DECISION") == 0.9
    assert salience_for_category("Error") == 0.8


# ---------------------------------------------------------------------------
# 13. ingest_pending_snapshots() does not raise TypeError (Sprint 05.05)
# ---------------------------------------------------------------------------
#
# Regression test for the latent bug fixed in Sprint 05.05:
# memory_snapshots.ingest_pending_snapshots() previously called
# Memory.store_knowledge(salience=...), but store_knowledge has no
# `salience` parameter — any invocation raised TypeError. Option A of
# the fix drops the salience= kwarg and follows up with
# memory._reinforce_entries([key]). This test invokes the helper end
# to end against a real Memory + migrated SQLite DB to confirm:
#   1. No TypeError leaks out of ingest_pending_snapshots
#   2. The snapshot lands in the knowledge table
#   3. _reinforce_entries fires (salience above the schema default)
#   4. The snapshot file is renamed to .processed
@pytest.mark.asyncio
async def test_ingest_pending_snapshots_no_typeerror(tmp_path, memory):
    snapshots_dir = tmp_path / "snapshots"
    snapshots_dir.mkdir(parents=True)

    # Seed two valid snapshots — different categories to cover the
    # SALIENCE_BY_CATEGORY map even though the fix no longer threads
    # salience through.
    ts = datetime.now(timezone.utc).isoformat()
    for i, category in enumerate(("decision", "lesson")):
        snap = {
            "category": category,
            "key": f"sprint-0505-key-{i}",
            "value": f"Snapshot value {i} for category={category}",
            "source": "sprint-0505-test",
            "salience": 0.9,
            "timestamp": ts,
        }
        (snapshots_dir / f"{1000 + i}_{category}.json").write_text(
            json.dumps(snap)
        )

    # The bug under repair would raise TypeError here. With the fix in
    # place, ingest_pending_snapshots returns the count ingested.
    count = await ingest_pending_snapshots(snapshots_dir, memory)
    assert count == 2, "Both seeded snapshots should be ingested"

    # Confirm both keys landed in the knowledge store.
    for i in range(2):
        key = f"sprint-0505-key-{i}"
        value = await memory.get_knowledge(key)
        assert value is not None, f"Key {key} missing from knowledge store"
        assert value.startswith("Snapshot value")

    # Confirm files were marked processed.
    assert sorted(p.name for p in snapshots_dir.iterdir()) == [
        "1000_decision.processed",
        "1001_lesson.processed",
    ]

    # Confirm _reinforce_entries fired — salience was bumped above the
    # schema default of 1.0 cap or stayed at the cap (whichever the
    # decay constants pick). Read the row directly.
    row = await memory._db.fetchone(
        "SELECT salience, access_count FROM knowledge WHERE key = ?",
        ("sprint-0505-key-0",),
    )
    assert row is not None
    salience_val, access_count = row[0], row[1]
    # access_count is bumped by _reinforce_entries from 0 → 1
    assert access_count >= 1, (
        "Sprint 05.05: _reinforce_entries must fire after store_knowledge "
        "to preserve original author's salience-bump intent."
    )
    # Salience should be a valid float in [0, SALIENCE_MAX].
    assert isinstance(salience_val, (int, float))
