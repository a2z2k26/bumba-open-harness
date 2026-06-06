"""Tests for ``second_brain.wiki_repo`` — Sprint 05.03 (issue #1012).

Covers the contract documented in
``agent/docs/architecture/second-brain.md`` (ADR Decisions 1, 3, 5)
and the schema in ``agent/config/second-brain-schema.md`` (PR #1129).
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from bridge.second_brain import (
    CURATED_PREFIX,
    STAGING_PREFIX,
    WikiNote,
    WikiRepo,
)
from bridge.second_brain.baseline import BaselineRecord


# ---------------- helpers ---------------- #


def _vault(tmp_path: Path) -> Path:
    """Create a minimal vault layout under tmp_path."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / STAGING_PREFIX).mkdir(parents=True)
    (vault / CURATED_PREFIX).mkdir(parents=True)
    return vault


def _note(relpath: str, body: str = "hello world") -> WikiNote:
    return WikiNote(
        relpath=relpath,
        content_body=body,
        source="daily_log",
        session_id="test-session-123",
        authored_at="2026-05-01T12:00:00Z",
        provenance="test write",
    )


# ---------------- write path-validation ---------------- #


def test_write_to_staging_succeeds(tmp_path):
    vault = _vault(tmp_path)
    repo = WikiRepo(vault)
    note = _note(STAGING_PREFIX + "note-1.md")
    written = repo.write(note)
    assert written.is_file()
    text = written.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "source: daily_log" in text
    assert "session_id: test-session-123" in text
    assert "schema_version: 1" in text
    assert text.rstrip().endswith("hello world")
    # No leftover .tmp files in the directory.
    leftovers = [p for p in written.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == [], f"unexpected tmp files: {leftovers}"


def test_write_to_curated_succeeds(tmp_path):
    vault = _vault(tmp_path)
    repo = WikiRepo(vault)
    note = _note(CURATED_PREFIX + "note-1.md", body="curated body")
    written = repo.write(note)
    assert written.is_file()
    assert "curated body" in written.read_text(encoding="utf-8")


def test_write_outside_bumba_contributions_raises(tmp_path):
    vault = _vault(tmp_path)
    repo = WikiRepo(vault)
    with pytest.raises(ValueError, match="bumba-contributions"):
        repo.write(_note("operator-notes/note.md"))


def test_write_with_traversal_raises(tmp_path):
    vault = _vault(tmp_path)
    repo = WikiRepo(vault)
    with pytest.raises(ValueError, match=r"\.\."):
        repo.write(_note(STAGING_PREFIX + "../escape.md"))


def test_write_with_absolute_path_raises(tmp_path):
    vault = _vault(tmp_path)
    repo = WikiRepo(vault)
    with pytest.raises(ValueError, match="absolute"):
        repo.write(_note("/etc/passwd"))


def test_write_through_symlink_outside_vault_raises(tmp_path):
    vault = _vault(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    # Create a symlink inside the quarantine subtree pointing outside.
    link = vault / STAGING_PREFIX / "evil"
    link.symlink_to(outside)
    repo = WikiRepo(vault)
    note = _note(STAGING_PREFIX + "evil/escape.md")
    with pytest.raises(ValueError, match="escapes vault root"):
        repo.write(note)


def test_write_invalid_source_raises(tmp_path):
    vault = _vault(tmp_path)
    repo = WikiRepo(vault)
    bad = WikiNote(
        relpath=STAGING_PREFIX + "n.md",
        content_body="x",
        source="not-an-enum",
        session_id="s",
        authored_at="t",
        provenance="p",
    )
    with pytest.raises(ValueError, match="source must be one of"):
        repo.write(bad)


# ---------------- read path ---------------- #


def test_read_round_trip_preserves_frontmatter(tmp_path):
    vault = _vault(tmp_path)
    repo = WikiRepo(vault)
    repo.write(_note(STAGING_PREFIX + "rt.md", body="round trip body"))
    result = repo.read(STAGING_PREFIX + "rt.md")
    assert result.frontmatter["source"] == "daily_log"
    assert result.frontmatter["session_id"] == "test-session-123"
    assert result.frontmatter["schema_version"] == 1
    assert "round trip body" in result.body
    assert result.is_grandfathered is False


def test_read_missing_file_raises(tmp_path):
    vault = _vault(tmp_path)
    repo = WikiRepo(vault)
    with pytest.raises(FileNotFoundError):
        repo.read(STAGING_PREFIX + "nope.md")


def test_read_grandfathered_via_baseline(tmp_path):
    vault = _vault(tmp_path)
    operator_note = vault / "old-note.md"
    operator_note.write_text("operator content with no frontmatter\n")
    baseline = {
        operator_note: BaselineRecord(
            path=operator_note,
            sha256="deadbeef",
            mtime=operator_note.stat().st_mtime,
            grandfathered_at=datetime.now(),
        ),
    }
    repo = WikiRepo(vault, baseline=baseline)
    result = repo.read("old-note.md")
    assert result.frontmatter == {}
    assert result.is_grandfathered is True


def test_read_no_frontmatter_no_baseline_is_grandfathered(tmp_path):
    """No-frontmatter operator files default to grandfathered when no
    baseline was supplied — keeps lint quiet on opt-out callers."""
    vault = _vault(tmp_path)
    op = vault / "scratch.md"
    op.write_text("just operator notes\n")
    repo = WikiRepo(vault)
    result = repo.read("scratch.md")
    assert result.is_grandfathered is True


# ---------------- list staging / curated ---------------- #


def test_list_staging_and_curated(tmp_path):
    vault = _vault(tmp_path)
    repo = WikiRepo(vault)
    repo.write(_note(STAGING_PREFIX + "a.md"))
    repo.write(_note(STAGING_PREFIX + "sub/b.md"))
    repo.write(_note(CURATED_PREFIX + "c.md"))

    staged = repo.list_staging()
    curated = repo.list_curated()
    assert staged == [
        STAGING_PREFIX + "a.md",
        STAGING_PREFIX + "sub/b.md",
    ]
    assert curated == [CURATED_PREFIX + "c.md"]


def test_list_skips_dotfiles_and_non_md(tmp_path):
    vault = _vault(tmp_path)
    repo = WikiRepo(vault)
    repo.write(_note(STAGING_PREFIX + "real.md"))
    (vault / STAGING_PREFIX / ".hidden.md").write_text("hidden")
    (vault / STAGING_PREFIX / "ignored.txt").write_text("nope")
    assert repo.list_staging() == [STAGING_PREFIX + "real.md"]


# ---------------- append_log ---------------- #


def test_append_log_writes_and_dedups(tmp_path):
    vault = _vault(tmp_path)
    repo = WikiRepo(vault)
    header = WikiRepo.format_session_header(
        "abc-123", when=datetime(2026, 5, 1, 14, 32),
    )
    repo.append_log(header)
    repo.append_log("- Added 3 daily_log notes to staging/")
    # Same line again — should dedup.
    repo.append_log("- Added 3 daily_log notes to staging/")

    log_text = (vault / "log.md").read_text(encoding="utf-8")
    assert log_text.count("- Added 3 daily_log notes to staging/") == 1
    assert "## 2026-05-01 14:32 — session abc-123" in log_text


def test_append_log_rejects_multiline(tmp_path):
    vault = _vault(tmp_path)
    repo = WikiRepo(vault)
    with pytest.raises(ValueError, match="single-line"):
        repo.append_log("line one\nline two")


# ---------------- index.md staging-section update ---------------- #


def test_update_index_creates_when_missing(tmp_path):
    vault = _vault(tmp_path)
    repo = WikiRepo(vault)
    repo.update_index_staging_section([STAGING_PREFIX + "a.md"])
    text = (vault / "index.md").read_text(encoding="utf-8")
    assert "## Bumba contributions (staged for review)" in text
    assert f"[[{STAGING_PREFIX}a.md]]" in text


def test_update_index_preserves_operator_sections(tmp_path):
    vault = _vault(tmp_path)
    initial = (
        "# Vault Index\n"
        "\n"
        "## Active threads\n"
        "- [[thread-x]] — important\n"
        "\n"
        "## Reference docs\n"
        "- [[doc-y]] — keep me\n"
    )
    (vault / "index.md").write_text(initial, encoding="utf-8")
    repo = WikiRepo(vault)
    repo.update_index_staging_section([STAGING_PREFIX + "new.md"])
    text = (vault / "index.md").read_text(encoding="utf-8")
    assert "[[thread-x]] — important" in text
    assert "[[doc-y]] — keep me" in text
    assert "[[" + STAGING_PREFIX + "new.md]]" in text
    # Operator sections appear before the Bumba section.
    bumba_idx = text.index("## Bumba contributions")
    threads_idx = text.index("## Active threads")
    refs_idx = text.index("## Reference docs")
    assert threads_idx < bumba_idx
    assert refs_idx < bumba_idx


def test_update_index_replaces_existing_bumba_section(tmp_path):
    vault = _vault(tmp_path)
    initial = (
        "# Vault Index\n\n"
        "## Active threads\n"
        "- [[thread-x]] — keep\n"
        "\n"
        "## Bumba contributions (staged for review)\n"
        "- [[bumba-contributions/staging/old.md]] — operator review pending\n"
    )
    (vault / "index.md").write_text(initial, encoding="utf-8")
    repo = WikiRepo(vault)
    repo.update_index_staging_section([STAGING_PREFIX + "new.md"])
    text = (vault / "index.md").read_text(encoding="utf-8")
    assert "old.md" not in text
    assert STAGING_PREFIX + "new.md" in text
    assert "[[thread-x]] — keep" in text


def test_update_index_empty_staging_renders_placeholder(tmp_path):
    vault = _vault(tmp_path)
    repo = WikiRepo(vault)
    repo.update_index_staging_section([])
    text = (vault / "index.md").read_text(encoding="utf-8")
    assert "_(no notes pending operator review)_" in text


# ---------------- locking smoke test ---------------- #


def test_concurrent_writes_to_same_file_serialize(tmp_path):
    """Two threads writing the same file should serialize via the
    sentinel flock — the file content matches one of the two writes
    cleanly (no interleaved frontmatter)."""
    vault = _vault(tmp_path)
    repo = WikiRepo(vault)
    relpath = STAGING_PREFIX + "race.md"

    def make_note(label: str) -> WikiNote:
        return WikiNote(
            relpath=relpath,
            content_body=f"BODY-{label}",
            source="daily_log",
            session_id=f"sess-{label}",
            authored_at="2026-05-01T12:00:00Z",
            provenance=f"writer {label}",
        )

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def writer(label: str, sleep: float):
        try:
            barrier.wait()
            time.sleep(sleep)
            repo.write(make_note(label))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=writer, args=("A", 0.0))
    t2 = threading.Thread(target=writer, args=("B", 0.01))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert errors == [], f"writer threads errored: {errors}"
    text = (vault / relpath).read_text(encoding="utf-8")
    # Whichever writer landed last wins, but the file is one consistent
    # frontmatter+body pair — no interleaved fragments.
    assert text.startswith("---\n")
    assert text.count("---\n") >= 2  # opening + closing fences
    # Body is exactly one of the two writers' bodies.
    assert ("BODY-A" in text) ^ ("BODY-B" in text), text
    # No leftover .tmp file — atomic rename completed.
    leftovers = [
        p for p in (vault / STAGING_PREFIX).iterdir()
        if p.name.endswith(".tmp")
    ]
    assert leftovers == [], f"tmp leftovers: {leftovers}"


# ---------------- baseline integration ---------------- #


def test_baseline_does_not_grandfather_bumba_contributions(tmp_path):
    """A note inside ``bumba-contributions/`` is Bumba-authored; even
    if it accidentally lands in the baseline dict, it is never
    grandfathered. Bumba content is always schema-validated."""
    vault = _vault(tmp_path)
    repo = WikiRepo(vault)
    repo.write(_note(STAGING_PREFIX + "fresh.md"))
    target = vault / STAGING_PREFIX / "fresh.md"

    # Construct a baseline that (mistakenly) contains the Bumba file.
    baseline = {
        target: BaselineRecord(
            path=target,
            sha256="x",
            mtime=target.stat().st_mtime,
            grandfathered_at=datetime.now(),
        ),
    }
    repo2 = WikiRepo(vault, baseline=baseline)
    result = repo2.read(STAGING_PREFIX + "fresh.md")
    assert result.is_grandfathered is False


# ---------------- vault_root validation ---------------- #


def test_init_rejects_missing_vault(tmp_path):
    with pytest.raises(FileNotFoundError):
        WikiRepo(tmp_path / "does-not-exist")


def test_init_rejects_non_directory(tmp_path):
    f = tmp_path / "afile.md"
    f.write_text("x")
    with pytest.raises(NotADirectoryError):
        WikiRepo(f)


# ---------------- frontmatter round-trip ---------------- #


def test_frontmatter_round_trip_preserves_all_fields(tmp_path):
    vault = _vault(tmp_path)
    repo = WikiRepo(vault)
    note = WikiNote(
        relpath=STAGING_PREFIX + "rt-full.md",
        content_body="line A\nline B\n",
        source="reflection",
        session_id="uuid-xyz",
        authored_at="2026-05-01T15:30:00Z",
        provenance="weekly retro insight",
    )
    repo.write(note)
    result = repo.read(STAGING_PREFIX + "rt-full.md")
    assert result.frontmatter["source"] == "reflection"
    assert result.frontmatter["session_id"] == "uuid-xyz"
    assert result.frontmatter["authored_at"] == "2026-05-01T15:30:00Z"
    assert result.frontmatter["provenance"] == "weekly retro insight"
    assert result.frontmatter["schema_version"] == 1
    assert "line A" in result.body
    assert "line B" in result.body


def test_format_session_header_format(tmp_path):
    header = WikiRepo.format_session_header(
        "sess-1", when=datetime(2026, 5, 1, 9, 5),
    )
    assert header == "## 2026-05-01 09:05 — session sess-1"


def test_write_creates_subdirectories(tmp_path):
    vault = _vault(tmp_path)
    repo = WikiRepo(vault)
    note = _note(STAGING_PREFIX + "deep/nested/path/n.md")
    written = repo.write(note)
    assert written.is_file()
    assert written.parent.is_dir()


def test_write_overwrites_existing_file(tmp_path):
    """Atomic writes must overwrite cleanly — no append, no corruption."""
    vault = _vault(tmp_path)
    repo = WikiRepo(vault)
    relpath = STAGING_PREFIX + "overwrite.md"
    repo.write(_note(relpath, body="version 1"))
    repo.write(_note(relpath, body="version 2"))
    text = (vault / relpath).read_text(encoding="utf-8")
    assert "version 2" in text
    assert "version 1" not in text
    # Frontmatter still appears exactly once.
    assert text.count("schema_version: 1") == 1


def test_lock_released_on_write_exception(tmp_path, monkeypatch):
    """If the write body raises, the flock must be released so a
    follow-up write succeeds."""
    vault = _vault(tmp_path)
    repo = WikiRepo(vault)

    # Force the first write to fail mid-way by patching os.replace.
    original_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("simulated mid-write failure")
        return original_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)

    with pytest.raises(OSError, match="simulated mid-write failure"):
        repo.write(_note(STAGING_PREFIX + "boom.md"))

    # Lock should be released; second write succeeds.
    monkeypatch.undo()
    repo.write(_note(STAGING_PREFIX + "after.md"))
    assert (vault / STAGING_PREFIX / "after.md").is_file()
