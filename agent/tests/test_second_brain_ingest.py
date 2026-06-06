"""Tests for ``bridge.second_brain.ingest`` — Sprint 05.06.

Covers:

- ``classify_note``: every path prefix → correct kind; frontmatter
  ``source`` → bumba_staging fallback; baseline match → grandfathered.
- ``extract_title``: H1 wins; first non-empty line falls back; empty
  body → relpath stem.
- ``extract_backlinks``: ``[[Link]]`` and ``[[Link|alias]]`` parsed,
  duplicates collapsed, escaped ``\\[[`` ignored.
- ``hash_body``: stable across runs; known input → known sha256.
- ``summarize_note`` happy path: returns runner output.
- ``summarize_note`` per-call cost cap exceeded → fallback.
- ``summarize_note`` runner raises → fallback (no exception escapes).
- ``ingest_vault`` on a tmp vault with mixed notes → counts correct.
- ``ingest_vault`` is idempotent (sha256 stability).
- ``summarize_canonical_only=True`` only invokes runner on canonical.
- ``ingest_vault`` enforces the global cost cap.
- ``ingest_vault`` continues past unreadable / malformed files.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.second_brain.baseline import ingest_baseline
from bridge.second_brain.ingest import (
    IngestNote,
    IngestSummary,
    classify_note,
    extract_backlinks,
    extract_title,
    hash_body,
    ingest_vault,
    summarize_note,
)
from bridge.second_brain.wiki_repo import (
    CURATED_PREFIX,
    STAGING_PREFIX,
    WikiReadResult,
)


# ---------------- helpers ---------------- #


def _make_vault(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def _wrr(
    relpath: str,
    body: str,
    *,
    frontmatter: dict | None = None,
    is_grandfathered: bool = False,
) -> WikiReadResult:
    return WikiReadResult(
        relpath=relpath,
        body=body,
        frontmatter=frontmatter or {},
        is_grandfathered=is_grandfathered,
    )


def _run(coro):
    """Tiny asyncio.run shim — pytest-asyncio is not enabled here, and
    the rest of the suite uses :func:`asyncio.run` for one-shot async
    tests, so we keep things consistent."""
    return asyncio.run(coro)


# ---------------- classify_note ---------------- #


def test_classify_note_staging_prefix():
    rr = _wrr(STAGING_PREFIX + "draft.md", "body")
    assert classify_note(rr) == "bumba_staging"


def test_classify_note_curated_prefix():
    rr = _wrr(CURATED_PREFIX + "promoted.md", "body")
    assert classify_note(rr) == "bumba_curated"


def test_classify_note_frontmatter_source_field_falls_back_to_staging():
    rr = _wrr("notes/foo.md", "body", frontmatter={"source": "ingest"})
    assert classify_note(rr) == "bumba_staging"


def test_classify_note_grandfathered_flag_wins():
    rr = _wrr("notes/legacy.md", "body", is_grandfathered=True)
    assert classify_note(rr) == "grandfathered"


def test_classify_note_default_is_operator_canonical():
    rr = _wrr("notes/today.md", "body")
    assert classify_note(rr) == "operator_canonical"


# ---------------- extract_title ---------------- #


def test_extract_title_returns_h1():
    body = "# My Note\n\nIntro paragraph."
    assert extract_title(body, fallback="fallback") == "My Note"


def test_extract_title_first_nonempty_line_when_no_h1():
    body = "\n\nNot a heading\nfollowing line"
    assert extract_title(body, fallback="fallback") == "Not a heading"


def test_extract_title_skips_subheadings_and_returns_first_real_line():
    body = "## Section heading\n### Sub\nactual content"
    assert extract_title(body, fallback="fallback") == "actual content"


def test_extract_title_empty_body_falls_back():
    assert extract_title("", fallback="my-relpath-stem") == "my-relpath-stem"


def test_extract_title_only_headings_falls_back():
    assert extract_title("## Only sub\n### only sub", fallback="stem") == "stem"


# ---------------- extract_backlinks ---------------- #


def test_extract_backlinks_simple_link():
    assert extract_backlinks("See [[Foo]] for details") == ("Foo",)


def test_extract_backlinks_aliased_link_drops_alias():
    assert extract_backlinks("Hello [[Bar|the alias]]") == ("Bar",)


def test_extract_backlinks_deduplicates():
    body = "[[A]] then [[B]] then [[A]] again"
    assert extract_backlinks(body) == ("A", "B")


def test_extract_backlinks_ignores_escaped():
    body = r"Literal: \[[NotALink]] but [[RealLink]] is real"
    assert extract_backlinks(body) == ("RealLink",)


def test_extract_backlinks_empty_body():
    assert extract_backlinks("") == ()


def test_extract_backlinks_preserves_internal_whitespace():
    assert extract_backlinks("[[Some Page]]") == ("Some Page",)


# ---------------- hash_body ---------------- #


def test_hash_body_known_value_stable():
    expected = hashlib.sha256(b"hello").hexdigest()
    assert hash_body("hello") == expected


def test_hash_body_idempotent():
    assert hash_body("repeat me") == hash_body("repeat me")


def test_hash_body_differs_on_different_input():
    assert hash_body("a") != hash_body("b")


# ---------------- summarize_note ---------------- #


def test_summarize_note_happy_path_returns_runner_output():
    async def runner(prompt: str) -> tuple[str, float]:
        return "A summary line.", 0.001

    summary, cost = _run(
        summarize_note("Body text.", dream_agent_runner=runner, cost_cap_usd=0.05),
    )
    assert summary == "A summary line."
    assert cost == pytest.approx(0.001)


def test_summarize_note_no_runner_falls_back_to_first_paragraph():
    body = "First paragraph.\nstill first.\n\nSecond paragraph."
    summary, cost = _run(summarize_note(body))
    assert summary == "First paragraph. still first."
    assert cost == 0.0


def test_summarize_note_per_call_cost_cap_exceeded_fallback():
    async def runner(prompt: str) -> tuple[str, float]:
        return "expensive line", 0.99

    body = "First paragraph here.\n\nSecond."
    summary, cost = _run(
        summarize_note(body, dream_agent_runner=runner, cost_cap_usd=0.05),
    )
    # Cost is still tallied so the global cap is honest.
    assert cost == pytest.approx(0.99)
    # Runner output discarded; summary is first-paragraph fallback.
    assert summary == "First paragraph here."


def test_summarize_note_runner_raises_fallback(caplog):
    async def runner(prompt: str) -> tuple[str, float]:
        raise RuntimeError("boom")

    body = "Real content here."
    with caplog.at_level(logging.WARNING, logger="bridge.second_brain.ingest"):
        summary, cost = _run(
            summarize_note(body, dream_agent_runner=runner, cost_cap_usd=0.05),
        )
    assert summary == "Real content here."
    assert cost == 0.0
    assert any("dream_agent_runner raised" in rec.message for rec in caplog.records)


def test_summarize_note_empty_body():
    summary, cost = _run(summarize_note(""))
    assert summary == ""
    assert cost == 0.0


# ---------------- ingest_vault ---------------- #


def _build_mixed_vault(tmp_path: Path) -> Path:
    """Vault with one note of each kind plus one malformed file.

    Layout:
      vault/
        canonical.md          → operator_canonical
        legacy.md             → grandfathered (after baseline ingest)
        bumba-contributions/staging/draft.md  → bumba_staging
        bumba-contributions/curated/keep.md   → bumba_curated
        bad.md                → unreadable (we'll patch read to raise)
    """
    return _make_vault(
        tmp_path / "vault",
        {
            "canonical.md": (
                "# Canonical Title\n\n"
                "First paragraph for canonical.\n\n"
                "Second paragraph references [[Other]].\n"
            ),
            "legacy.md": (
                "# Legacy Title\n\n"
                "Operator wrote this before baseline.\n"
            ),
            "bumba-contributions/staging/draft.md": (
                "---\nsource: ingest\nsession_id: s1\n"
                "authored_at: 2026-05-01\nprovenance: ingest\n"
                "schema_version: 1\n---\n# Staged Draft\nDraft body.\n"
            ),
            "bumba-contributions/curated/keep.md": (
                "---\nsource: ingest\nsession_id: s2\n"
                "authored_at: 2026-05-01\nprovenance: ingest\n"
                "schema_version: 1\n---\n# Curated Keep\nCurated body.\n"
            ),
            "bad.md": "ok content; we'll force a read error in the test\n",
        },
    )


def test_ingest_vault_classifies_all_kinds(tmp_path):
    vault = _build_mixed_vault(tmp_path)
    baseline_jsonl = tmp_path / "baseline.jsonl"
    # Baseline only legacy.md so it becomes grandfathered. We do this by
    # ingesting the vault, then adding canonical.md afterwards. Build
    # baseline from a stripped vault first.
    legacy_only_vault = tmp_path / "legacy_only"
    legacy_only_vault.mkdir()
    (legacy_only_vault / "legacy.md").write_text(
        (vault / "legacy.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    ingest_baseline(legacy_only_vault, output=baseline_jsonl)
    # Patch the recorded path to the real vault location so the
    # baseline matches when ingest_vault runs.
    baseline_text = baseline_jsonl.read_text(encoding="utf-8")
    baseline_jsonl.write_text(
        baseline_text.replace(str(legacy_only_vault), str(vault)),
        encoding="utf-8",
    )

    notes, summary = _run(
        ingest_vault(vault, baseline_path=baseline_jsonl),
    )

    by_relpath = {n.relpath: n for n in notes}
    assert by_relpath["canonical.md"].kind == "operator_canonical"
    assert by_relpath["legacy.md"].kind == "grandfathered"
    assert (
        by_relpath["bumba-contributions/staging/draft.md"].kind == "bumba_staging"
    )
    assert (
        by_relpath["bumba-contributions/curated/keep.md"].kind == "bumba_curated"
    )
    # No skipped files in the happy path (bad.md is well-formed UTF-8).
    assert summary.skipped_count == 0
    assert summary.total_notes == 5
    # canonical.md and bad.md both classify as operator_canonical
    # (bad.md is well-formed UTF-8 here; the unreadable case is
    # exercised separately).
    assert summary.operator_canonical_count == 2
    assert summary.grandfathered_count == 1
    assert summary.bumba_staging_count == 1
    assert summary.bumba_curated_count == 1


def test_ingest_vault_idempotent_sha256s(tmp_path):
    vault = _build_mixed_vault(tmp_path)
    baseline_jsonl = tmp_path / "baseline.jsonl"
    ingest_baseline(vault, output=baseline_jsonl)

    first, _ = _run(ingest_vault(vault, baseline_path=baseline_jsonl))
    second, _ = _run(ingest_vault(vault, baseline_path=baseline_jsonl))

    first_by_path = {n.relpath: n.sha256 for n in first}
    second_by_path = {n.relpath: n.sha256 for n in second}
    assert first_by_path == second_by_path
    # Backlink + frontmatter + word_count stability is also implied.
    first_meta = {(n.relpath, n.kind, n.title, n.backlinks) for n in first}
    second_meta = {(n.relpath, n.kind, n.title, n.backlinks) for n in second}
    assert first_meta == second_meta


def test_ingest_vault_summarize_canonical_only(tmp_path):
    vault = _build_mixed_vault(tmp_path)
    baseline_jsonl = tmp_path / "baseline.jsonl"
    ingest_baseline(vault, output=baseline_jsonl)
    invocation_paths: list[str] = []

    async def runner(prompt: str) -> tuple[str, float]:
        # Use the body suffix as a poor-man's path tag.
        invocation_paths.append(prompt[-80:])
        return "summary line", 0.001

    notes, summary = _run(
        ingest_vault(
            vault,
            baseline_path=baseline_jsonl,
            dream_agent_runner=runner,
            summarize_canonical_only=True,
        ),
    )
    # Only canonical.md should have been summarised. legacy.md is
    # grandfathered, the bumba-contributions notes are bumba-authored,
    # and bad.md is well-formed but classifies as operator_canonical
    # too — so we expect exactly TWO invocations (canonical.md +
    # bad.md, both classified as operator_canonical).
    canonical_count = sum(
        1 for n in notes if n.kind == "operator_canonical"
    )
    assert len(invocation_paths) == canonical_count
    assert summary.summarized_count == canonical_count
    assert summary.cost_usd == pytest.approx(0.001 * canonical_count)


def test_ingest_vault_global_cost_cap(tmp_path):
    vault = _build_mixed_vault(tmp_path)
    baseline_jsonl = tmp_path / "baseline.jsonl"
    ingest_baseline(vault, output=baseline_jsonl)

    invocations: list[int] = []

    async def runner(prompt: str) -> tuple[str, float]:
        invocations.append(1)
        return "ok", 10.0  # absurdly expensive — first call blows the cap

    _, summary = _run(
        ingest_vault(
            vault,
            baseline_path=baseline_jsonl,
            dream_agent_runner=runner,
            summarize_canonical_only=False,
            cost_cap_total_usd=1.0,
        ),
    )
    # First note hits the runner; cost (10.0) immediately exceeds the
    # 1.0 global cap, so all subsequent notes use first-paragraph
    # fallback (zero further runner invocations).
    assert len(invocations) == 1
    assert summary.summarized_count == 1
    assert summary.cost_usd == pytest.approx(10.0)


def test_ingest_vault_continues_past_unreadable_file(tmp_path, caplog):
    vault = _build_mixed_vault(tmp_path)
    baseline_jsonl = tmp_path / "baseline.jsonl"
    ingest_baseline(vault, output=baseline_jsonl)

    real_read = __import__(
        "bridge.second_brain.wiki_repo", fromlist=["WikiRepo"],
    ).WikiRepo.read

    def flaky_read(self, relpath):
        if relpath == "bad.md":
            raise OSError("simulated read failure")
        return real_read(self, relpath)

    with patch(
        "bridge.second_brain.wiki_repo.WikiRepo.read",
        new=flaky_read,
    ):
        with caplog.at_level(
            logging.WARNING, logger="bridge.second_brain.ingest",
        ):
            notes, summary = _run(
                ingest_vault(vault, baseline_path=baseline_jsonl),
            )

    # bad.md skipped, the other 4 notes still emitted.
    assert summary.skipped_count == 1
    assert summary.total_notes == 4
    assert "bad.md" not in {n.relpath for n in notes}
    assert any("unreadable note" in rec.message for rec in caplog.records)


def test_ingest_vault_returns_immutable_tuples(tmp_path):
    vault = _make_vault(tmp_path / "vault", {"a.md": "# A\n\nbody"})
    notes, summary = _run(ingest_vault(vault))
    assert isinstance(notes, tuple)
    assert isinstance(summary, IngestSummary)
    assert all(isinstance(n, IngestNote) for n in notes)
    # Frozen dataclass — assignment must fail.
    with pytest.raises(Exception):
        notes[0].kind = "bumba_staging"  # type: ignore[misc]
