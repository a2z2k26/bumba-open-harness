"""Tests for ``bridge.second_brain.baseline`` — Sprint 05.0a.

Covers:
- ``ingest_baseline`` walks a tmp vault, hashes ``.md`` files, writes JSONL.
- Idempotent on re-run: zero new records when nothing changed.
- ``is_grandfathered`` returns True for unmodified file, False after edit.
- ``is_grandfathered`` returns False for files not in baseline.
- Empty vault yields zero records, no error.
- Only ``.md`` files — ``.txt`` / ``.json`` ignored.
- Skips dot-files and dot-directories (``.git/``, ``.obsidian/``, ...).
- ``load_baseline`` round-trips records.
- Atomic writes (no ``.tmp`` left behind on success).
- Re-running on extended vault appends only the delta.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bridge.second_brain.baseline import (
    BaselineRecord,
    ingest_baseline,
    is_grandfathered,
    load_baseline,
)


# ---------- helpers ----------


def _make_vault(root: Path, files: dict[str, str]) -> Path:
    """Create a tmp vault with the given relative path → content map."""
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


# ---------- ingest_baseline ----------


def test_ingest_walks_vault_recursively_and_writes_jsonl(tmp_path):
    vault = _make_vault(
        tmp_path / "vault",
        {
            "alpha.md": "# Alpha\n\nSome content.\n",
            "subfolder/beta.md": "# Beta\n",
            "subfolder/nested/gamma.md": "# Gamma\n",
        },
    )
    out = tmp_path / "baseline.jsonl"

    count = ingest_baseline(vault, output=out)

    assert count == 3
    assert out.is_file()
    lines = [l for l in out.read_text().splitlines() if l.strip()]
    assert len(lines) == 3
    paths = {json.loads(l)["path"] for l in lines}
    assert str(vault / "alpha.md") in paths
    assert str(vault / "subfolder" / "beta.md") in paths
    assert str(vault / "subfolder" / "nested" / "gamma.md") in paths


def test_ingest_records_have_sha256_mtime_and_grandfathered_at(tmp_path):
    vault = _make_vault(tmp_path / "vault", {"only.md": "hello\n"})
    out = tmp_path / "baseline.jsonl"

    ingest_baseline(vault, output=out)

    record = json.loads(out.read_text().splitlines()[0])
    assert record["path"] == str(vault / "only.md")
    assert len(record["sha256"]) == 64  # hex sha256
    assert isinstance(record["mtime"], (int, float))
    # ISO 8601 with timezone — round-trips through datetime.fromisoformat
    parsed = datetime.fromisoformat(record["grandfathered_at"])
    assert parsed.tzinfo is not None


def test_ingest_idempotent_on_rerun(tmp_path):
    vault = _make_vault(
        tmp_path / "vault",
        {"a.md": "alpha\n", "b.md": "beta\n"},
    )
    out = tmp_path / "baseline.jsonl"

    first = ingest_baseline(vault, output=out)
    assert first == 2

    first_bytes = out.read_bytes()

    second = ingest_baseline(vault, output=out)
    assert second == 0
    # File should be untouched on a no-op re-run (same bytes).
    assert out.read_bytes() == first_bytes


def test_ingest_appends_only_new_files_on_extended_vault(tmp_path):
    vault = _make_vault(tmp_path / "vault", {"a.md": "alpha\n"})
    out = tmp_path / "baseline.jsonl"

    assert ingest_baseline(vault, output=out) == 1

    # Operator adds a new note. Re-running grandfathers JUST the new file.
    (vault / "b.md").write_text("beta\n", encoding="utf-8")
    delta = ingest_baseline(vault, output=out)
    assert delta == 1

    records = load_baseline(out)
    assert (vault / "a.md") in records
    assert (vault / "b.md") in records


def test_ingest_only_md_files(tmp_path):
    vault = _make_vault(
        tmp_path / "vault",
        {
            "note.md": "# Markdown\n",
            "data.txt": "plain text\n",
            "config.json": "{}",
            "image.png": "fake-png-bytes",
        },
    )
    out = tmp_path / "baseline.jsonl"

    count = ingest_baseline(vault, output=out)
    assert count == 1

    records = load_baseline(out)
    assert (vault / "note.md") in records
    assert (vault / "data.txt") not in records
    assert (vault / "config.json") not in records
    assert (vault / "image.png") not in records


def test_ingest_skips_dot_files_and_dot_directories(tmp_path):
    vault = _make_vault(
        tmp_path / "vault",
        {
            "real.md": "# Real\n",
            ".obsidian/workspace.md": "# Hidden config\n",
            ".git/HEAD": "ref: refs/heads/main\n",
            ".git/objects/aa/bb.md": "# Should be skipped\n",
            "subdir/.hidden.md": "# Hidden file\n",
            "subdir/visible.md": "# Visible\n",
        },
    )
    out = tmp_path / "baseline.jsonl"

    count = ingest_baseline(vault, output=out)
    assert count == 2

    records = load_baseline(out)
    assert (vault / "real.md") in records
    assert (vault / "subdir" / "visible.md") in records
    # Dot-directory contents excluded.
    assert (vault / ".obsidian" / "workspace.md") not in records
    assert (vault / ".git" / "objects" / "aa" / "bb.md") not in records
    # Dot-files (even with .md suffix) excluded.
    assert (vault / "subdir" / ".hidden.md") not in records


def test_ingest_empty_vault_returns_zero_no_error(tmp_path):
    vault = tmp_path / "empty-vault"
    vault.mkdir()
    out = tmp_path / "baseline.jsonl"

    count = ingest_baseline(vault, output=out)

    assert count == 0
    # First-run with zero matches: do not write the JSONL since there's
    # nothing to grandfather. (Output file should NOT exist.)
    assert not out.exists()


def test_ingest_missing_vault_raises(tmp_path):
    out = tmp_path / "baseline.jsonl"
    with pytest.raises(FileNotFoundError):
        ingest_baseline(tmp_path / "does-not-exist", output=out)


def test_ingest_vault_is_file_raises(tmp_path):
    not_a_dir = tmp_path / "actually-a-file.md"
    not_a_dir.write_text("just a file\n")
    out = tmp_path / "baseline.jsonl"
    with pytest.raises(NotADirectoryError):
        ingest_baseline(not_a_dir, output=out)


def test_ingest_atomic_write_no_tmp_left_behind(tmp_path):
    vault = _make_vault(tmp_path / "vault", {"a.md": "alpha\n"})
    out = tmp_path / "baseline.jsonl"

    ingest_baseline(vault, output=out)

    leftovers = [p for p in out.parent.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


# ---------- is_grandfathered ----------


def test_is_grandfathered_true_for_unmodified_file(tmp_path):
    vault = _make_vault(tmp_path / "vault", {"a.md": "alpha\n"})
    out = tmp_path / "baseline.jsonl"
    ingest_baseline(vault, output=out)

    assert is_grandfathered(vault / "a.md", baseline=out) is True


def test_is_grandfathered_false_after_edit(tmp_path):
    vault = _make_vault(tmp_path / "vault", {"a.md": "alpha\n"})
    out = tmp_path / "baseline.jsonl"
    ingest_baseline(vault, output=out)

    # Operator edits the note post-baseline — sha256 drifts.
    (vault / "a.md").write_text("alpha (edited)\n", encoding="utf-8")

    assert is_grandfathered(vault / "a.md", baseline=out) is False


def test_is_grandfathered_false_for_unknown_file(tmp_path):
    vault = _make_vault(tmp_path / "vault", {"a.md": "alpha\n"})
    out = tmp_path / "baseline.jsonl"
    ingest_baseline(vault, output=out)

    assert is_grandfathered(vault / "never-existed.md", baseline=out) is False


def test_is_grandfathered_false_when_file_deleted(tmp_path):
    vault = _make_vault(tmp_path / "vault", {"a.md": "alpha\n"})
    out = tmp_path / "baseline.jsonl"
    ingest_baseline(vault, output=out)

    (vault / "a.md").unlink()
    assert is_grandfathered(vault / "a.md", baseline=out) is False


def test_is_grandfathered_false_when_baseline_missing(tmp_path):
    vault = _make_vault(tmp_path / "vault", {"a.md": "alpha\n"})
    # No ingest performed.
    assert (
        is_grandfathered(vault / "a.md", baseline=tmp_path / "nope.jsonl")
        is False
    )


# ---------- load_baseline ----------


def test_load_baseline_round_trips(tmp_path):
    vault = _make_vault(
        tmp_path / "vault", {"a.md": "alpha\n", "b.md": "beta\n"},
    )
    out = tmp_path / "baseline.jsonl"
    ingest_baseline(vault, output=out)

    records = load_baseline(out)

    assert set(records.keys()) == {vault / "a.md", vault / "b.md"}
    for rec in records.values():
        assert isinstance(rec, BaselineRecord)
        assert len(rec.sha256) == 64
        assert rec.grandfathered_at.tzinfo is not None


def test_load_baseline_returns_empty_when_missing(tmp_path):
    assert load_baseline(tmp_path / "no-such-baseline.jsonl") == {}


def test_load_baseline_skips_malformed_lines(tmp_path):
    vault = _make_vault(tmp_path / "vault", {"a.md": "alpha\n"})
    out = tmp_path / "baseline.jsonl"
    ingest_baseline(vault, output=out)

    # Append a junk line — load_baseline should warn-and-skip.
    with out.open("a", encoding="utf-8") as fh:
        fh.write("this is not json\n")

    records = load_baseline(out)
    assert len(records) == 1
    assert (vault / "a.md") in records


# ---------- BaselineRecord ----------


def test_baseline_record_is_frozen():
    rec = BaselineRecord(
        path=Path("/tmp/x.md"),
        sha256="0" * 64,
        mtime=0.0,
        grandfathered_at=datetime.now(timezone.utc),
    )
    with pytest.raises((AttributeError, Exception)):
        rec.sha256 = "1" * 64  # type: ignore[misc]


# ---------- second_brain_baseline_enabled gate (D1.10 #1182) ----------


def test_ingest_baseline_disabled_returns_zero_without_reading_vault(tmp_path):
    """When enabled=False, ingest_baseline() is a no-op — returns 0 and
    writes nothing, even if vault_root has markdown files."""
    from bridge.second_brain.baseline import ingest_baseline

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# Hello")
    out = tmp_path / "baseline.jsonl"

    result = ingest_baseline(vault, output=out, enabled=False)

    assert result == 0
    assert not out.exists()


def test_ingest_baseline_enabled_true_behaves_normally(tmp_path):
    """enabled=True (default) runs the full baseline walk."""
    from bridge.second_brain.baseline import ingest_baseline

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# Hello")
    out = tmp_path / "baseline.jsonl"

    result = ingest_baseline(vault, output=out, enabled=True)

    assert result >= 1
    assert out.exists()
