"""Tests for ``bridge.second_brain.promote`` — Sprint 05.10 (issue #1020).

Covers the contract documented in
``agent/docs/architecture/second-brain.md`` (ADR Decision 3) and the
schema in ``agent/config/second-brain-schema.md``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bridge.second_brain import (
    CURATED_PREFIX,
    STAGING_PREFIX,
    WikiNote,
    WikiRepo,
)
from bridge.second_brain.promote import (
    PromoteResult,
    RejectResult,
    promote_note,
    reject_note,
    strip_frontmatter,
)


# ---------------- helpers ---------------- #


def _vault(tmp_path: Path) -> Path:
    """Minimal vault layout."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / STAGING_PREFIX).mkdir(parents=True)
    (vault / CURATED_PREFIX).mkdir(parents=True)
    return vault


def _stage(repo: WikiRepo, relpath: str, body: str) -> None:
    """Write a Bumba-authored note to the staging tree."""
    repo.write(
        WikiNote(
            relpath=relpath,
            content_body=body,
            source="daily_log",
            session_id="sess-test",
            authored_at="2026-05-01T12:00:00Z",
            provenance="promote-test",
        )
    )


# ---------------- strip_frontmatter ---------------- #


class TestStripFrontmatter:
    def test_removes_leading_yaml_block(self):
        text = (
            "---\n"
            "source: daily_log\n"
            "session_id: abc\n"
            "---\n"
            "Body line one.\nBody line two.\n"
        )
        assert strip_frontmatter(text) == "Body line one.\nBody line two.\n"

    def test_no_frontmatter_returns_input_unchanged(self):
        plain = "# Heading\n\nJust a markdown body.\n"
        assert strip_frontmatter(plain) == plain

    def test_unterminated_frontmatter_returns_input(self):
        text = "---\nsource: daily_log\nno closing fence ever\n"
        # No "\n---" closer — preserve the input rather than dropping it.
        assert strip_frontmatter(text) == text

    def test_fence_without_newline_returns_input(self):
        # "---" without a following newline is not a valid block.
        assert strip_frontmatter("---no newline here") == "---no newline here"

    def test_handles_crlf_line_endings(self):
        text = "---\r\nsource: daily_log\r\n---\r\nBody\r\n"
        assert strip_frontmatter(text) == "Body\r\n"

    def test_empty_string_returns_empty(self):
        assert strip_frontmatter("") == ""


# ---------------- promote_note ---------------- #


class TestPromoteHappyPath:
    def test_writes_destination_removes_source_logs(self, tmp_path):
        vault = _vault(tmp_path)
        repo = WikiRepo(vault)
        rel = STAGING_PREFIX + "promote-me.md"
        _stage(repo, rel, "Body to promote.\n")

        result = promote_note(repo, source_relpath=rel)

        assert isinstance(result, PromoteResult)
        assert result.source_relpath == rel
        assert result.destination_relpath == "promote-me.md"
        assert result.already_promoted is False
        assert result.bytes_written == len(b"Body to promote.\n")
        # Destination written without frontmatter.
        dest = vault / "promote-me.md"
        assert dest.is_file()
        assert dest.read_text(encoding="utf-8") == "Body to promote.\n"
        # Source removed.
        assert not (vault / rel).exists()
        # Log appended.
        log_text = (vault / "log.md").read_text(encoding="utf-8")
        assert "promoted:" in log_text
        assert rel in log_text
        assert "promote-me.md" in log_text

    def test_explicit_destination_relpath(self, tmp_path):
        vault = _vault(tmp_path)
        repo = WikiRepo(vault)
        rel = STAGING_PREFIX + "anywhere.md"
        _stage(repo, rel, "Hello.")

        result = promote_note(
            repo,
            source_relpath=rel,
            destination_relpath="projects/hello.md",
        )

        assert result.destination_relpath == "projects/hello.md"
        assert (vault / "projects" / "hello.md").is_file()
        assert (vault / "projects" / "hello.md").read_text(
            encoding="utf-8"
        ) == "Hello.\n"

    def test_derives_destination_from_subdir_in_staging(self, tmp_path):
        # Subdirectory inside staging propagates to vault root.
        vault = _vault(tmp_path)
        (vault / STAGING_PREFIX / "projects").mkdir(parents=True)
        repo = WikiRepo(vault)
        rel = STAGING_PREFIX + "projects/sub.md"
        _stage(repo, rel, "Sub body.")

        result = promote_note(repo, source_relpath=rel)

        assert result.destination_relpath == "projects/sub.md"
        assert (vault / "projects" / "sub.md").is_file()

    def test_promote_from_curated_works(self, tmp_path):
        vault = _vault(tmp_path)
        repo = WikiRepo(vault)
        rel = CURATED_PREFIX + "curated-note.md"
        _stage(repo, rel, "Curated body.")

        result = promote_note(repo, source_relpath=rel)

        assert result.destination_relpath == "curated-note.md"
        assert (vault / "curated-note.md").is_file()


class TestPromoteAlreadyPromoted:
    def test_destination_identical_content_no_op(self, tmp_path):
        vault = _vault(tmp_path)
        repo = WikiRepo(vault)
        rel = STAGING_PREFIX + "dup.md"
        body = "Identical body.\n"
        _stage(repo, rel, body)
        # Pre-place a destination with byte-identical content.
        (vault / "dup.md").write_text(body, encoding="utf-8")

        result = promote_note(repo, source_relpath=rel)

        assert result.already_promoted is True
        assert result.bytes_written == 0
        # Destination still readable, byte-identical.
        assert (vault / "dup.md").read_text(encoding="utf-8") == body
        # Source removed (idempotent: future /promote can't double-stage).
        assert not (vault / rel).exists()
        # Log entry mentions no-op.
        log_text = (vault / "log.md").read_text(encoding="utf-8")
        assert "no-op" in log_text


class TestPromoteConflict:
    def test_destination_different_content_raises(self, tmp_path):
        vault = _vault(tmp_path)
        repo = WikiRepo(vault)
        rel = STAGING_PREFIX + "conflict.md"
        _stage(repo, rel, "Bumba says A.")
        (vault / "conflict.md").write_text(
            "Operator already wrote B here.", encoding="utf-8"
        )

        with pytest.raises(ValueError, match="different content"):
            promote_note(repo, source_relpath=rel)

        # Operator content untouched.
        assert (vault / "conflict.md").read_text(
            encoding="utf-8"
        ) == "Operator already wrote B here."
        # Source still present (no destructive side effect on conflict).
        assert (vault / rel).exists()


class TestPromoteValidation:
    def test_source_outside_quarantine_raises(self, tmp_path):
        vault = _vault(tmp_path)
        repo = WikiRepo(vault)
        with pytest.raises(ValueError, match="bumba-contributions"):
            promote_note(repo, source_relpath="some-file.md")

    def test_source_absolute_path_raises(self, tmp_path):
        vault = _vault(tmp_path)
        repo = WikiRepo(vault)
        with pytest.raises(ValueError, match="absolute"):
            promote_note(repo, source_relpath="/etc/passwd")

    def test_source_empty_raises(self, tmp_path):
        vault = _vault(tmp_path)
        repo = WikiRepo(vault)
        with pytest.raises(ValueError, match="non-empty"):
            promote_note(repo, source_relpath="")

    def test_destination_in_quarantine_raises(self, tmp_path):
        vault = _vault(tmp_path)
        repo = WikiRepo(vault)
        rel = STAGING_PREFIX + "x.md"
        _stage(repo, rel, "x")
        with pytest.raises(ValueError, match="canonical"):
            promote_note(
                repo,
                source_relpath=rel,
                destination_relpath=STAGING_PREFIX + "y.md",
            )

    def test_destination_traversal_raises(self, tmp_path):
        vault = _vault(tmp_path)
        repo = WikiRepo(vault)
        rel = STAGING_PREFIX + "x.md"
        _stage(repo, rel, "x")
        with pytest.raises(ValueError, match=r"\.\."):
            promote_note(
                repo,
                source_relpath=rel,
                destination_relpath="../escape.md",
            )

    def test_source_missing_raises_file_not_found(self, tmp_path):
        vault = _vault(tmp_path)
        repo = WikiRepo(vault)
        with pytest.raises(FileNotFoundError):
            promote_note(
                repo,
                source_relpath=STAGING_PREFIX + "nope.md",
            )


# ---------------- reject_note ---------------- #


class TestRejectHappyPath:
    def test_removes_file_appends_log(self, tmp_path):
        vault = _vault(tmp_path)
        repo = WikiRepo(vault)
        rel = STAGING_PREFIX + "reject-me.md"
        _stage(repo, rel, "Body.")
        assert (vault / rel).exists()

        result = reject_note(repo, source_relpath=rel)

        assert isinstance(result, RejectResult)
        assert result.deleted is True
        assert result.reason is None
        assert not (vault / rel).exists()
        log_text = (vault / "log.md").read_text(encoding="utf-8")
        assert "rejected:" in log_text
        assert rel in log_text

    def test_with_reason_log_includes_reason(self, tmp_path):
        vault = _vault(tmp_path)
        repo = WikiRepo(vault)
        rel = STAGING_PREFIX + "low-quality.md"
        _stage(repo, rel, "Body.")

        result = reject_note(
            repo,
            source_relpath=rel,
            reason="too speculative",
        )

        assert result.reason == "too speculative"
        log_text = (vault / "log.md").read_text(encoding="utf-8")
        assert "too speculative" in log_text

    def test_multiline_reason_is_flattened(self, tmp_path):
        vault = _vault(tmp_path)
        repo = WikiRepo(vault)
        rel = STAGING_PREFIX + "multi.md"
        _stage(repo, rel, "Body.")

        result = reject_note(
            repo,
            source_relpath=rel,
            reason="line one\nline two",
        )

        assert "\n" not in (result.reason or "")
        log_text = (vault / "log.md").read_text(encoding="utf-8")
        # Single line in log_entry.
        assert "line one line two" in log_text


class TestRejectIdempotent:
    def test_absent_file_no_op(self, tmp_path):
        vault = _vault(tmp_path)
        repo = WikiRepo(vault)
        rel = STAGING_PREFIX + "ghost.md"

        result = reject_note(repo, source_relpath=rel)

        assert result.deleted is False
        # Log still appended — operator audit trail wants the attempt.
        log_text = (vault / "log.md").read_text(encoding="utf-8")
        assert "rejected:" in log_text
        assert rel in log_text


class TestRejectValidation:
    def test_source_outside_quarantine_raises(self, tmp_path):
        vault = _vault(tmp_path)
        repo = WikiRepo(vault)
        with pytest.raises(ValueError, match="bumba-contributions"):
            reject_note(repo, source_relpath="canonical.md")
