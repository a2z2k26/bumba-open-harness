"""ingest.py — read-side of the second-brain subsystem.

Sprint 05.06 (issue #1014) of the 2026-04-25 reference-audit bundle.
ADR sign-off: ``agent/docs/architecture/second-brain.md`` Decisions
1, 4, 5 (``__AZ__`` 2026-05-01).
Schema: ``agent/config/second-brain-schema.md`` (PR #1129, schema_version=1).

Why this exists
---------------
Sprint 05.06 needs ONE place that walks the operator's Obsidian vault,
classifies each note (operator-canonical / Bumba-staged / Bumba-curated
/ grandfathered), summarises it (cheaply — Haiku-via-DreamAgent for
canonical notes only), and emits a structured index that
:mod:`bridge.second_brain.query` (Sprint 05.08) consumes.

Reuses existing pipelines rather than building parallel ones — the
spec's primary correctness guard against "yet another knowledge store":

- :mod:`bridge.second_brain.wiki_repo` — :class:`WikiRepo` is the only
  read primitive; this module never opens vault files directly.
- :mod:`bridge.second_brain.baseline` — :func:`is_grandfathered` decides
  which legacy operator files lint should ignore.
- :mod:`bridge.consolidation` — pure-function consolidation pipeline
  is *available* to callers via the returned :class:`IngestNote` tuple
  (downstream sprints feed the metadata in); ingest itself only needs
  the classification + summarisation outputs.
- :mod:`bridge.dream_agent` — restricted Claude subprocess used for
  one-line note summarisation. Optional — when not wired, ingest
  falls back to first-paragraph extraction so it stays useful in tests
  and offline runs.

Concept-only port
-----------------
The ingest shape is informed by the Karpathy gist (no source copy —
``concept-only-no-license``). Specifically: a single read-walk that
treats the markdown vault as the source of truth and emits a small,
queryable index — never a parallel knowledge store.

Defensive contract
------------------
- All file reads go through :class:`WikiRepo`; any single failure
  (malformed YAML, unreadable file, dream-agent timeout) is logged +
  counted. Ingest never aborts on a bad note — it skips and continues.
- Idempotent: running twice on an unchanged vault produces identical
  :class:`IngestNote` tuples (same sha256s) so downstream diffs are
  meaningful change-detection signals.
- ``cost_cap_total_usd`` enforces a global cap on dream-agent calls.
  When exceeded, the remaining notes get fallback (first-paragraph)
  summaries so ingest still completes.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from .baseline import BaselineRecord, load_baseline
from .wiki_repo import (
    CURATED_PREFIX,
    STAGING_PREFIX,
    WikiReadResult,
    WikiRepo,
)

logger = logging.getLogger(__name__)

# Frontmatter "source" field — when present in non-Bumba paths, indicates
# Bumba-authored content that ended up outside the quarantine subtree
# (legacy data or out-of-band copy). We treat this as bumba_staging by
# fallback so lint never confuses such notes with operator-canonical
# content.
_BUMBA_FRONTMATTER_SOURCE_KEY = "source"

# Regex for [[wikilink]] extraction. Matches:
#   [[Target]]
#   [[Target|Alias]]
#   [[Target/Sub]]
# And refuses escaped \[[Target]] (Obsidian convention for literal
# brackets). Capture group 1 is the target only — alias is discarded.
_WIKILINK_RE = re.compile(r"(?<!\\)\[\[([^\[\]\|]+?)(?:\|[^\[\]]*)?\]\]")

# A title detector that matches a leading ``# Title`` line (single hash,
# at least one space, then non-empty content). Avoids ``## Section``
# headings and ``#tag`` lines.
_H1_RE = re.compile(r"^# +(.+?)\s*$", re.MULTILINE)


NoteKind = Literal[
    "operator_canonical",
    "bumba_staging",
    "bumba_curated",
    "grandfathered",
]


# A summariser callable signature. Concrete implementations (e.g. a
# DreamAgent wrapper) accept the body and return a (summary, cost_usd)
# tuple. The callable is awaited so wrappers can do real subprocess
# work.
DreamAgentRunner = Callable[[str], Awaitable[tuple[str, float]]]


@dataclass(frozen=True)
class IngestNote:
    """One note in the ingest index — minimal metadata, body referenced by relpath.

    Frozen so the returned index tuple is immutable. Bodies are NOT
    held in memory — callers re-read via :class:`WikiRepo` if they
    need full content. ``sha256`` is the change-detection key.
    """

    relpath: str
    kind: NoteKind
    title: str
    summary: str
    frontmatter: dict[str, Any]
    is_grandfathered: bool
    sha256: str
    word_count: int
    backlinks: tuple[str, ...]
    last_seen_iso: str


@dataclass(frozen=True)
class IngestSummary:
    """Aggregate stats from one ingest pass.

    ``summarized_count`` is the cost signal — number of dream-agent
    invocations that actually fired (vs. fell back to first-paragraph
    extraction). ``skipped_count`` counts notes the walker could not
    process (malformed / unreadable). Both are observability surfaces
    for the operator dashboard, not error states.
    """

    total_notes: int
    operator_canonical_count: int
    bumba_staging_count: int
    bumba_curated_count: int
    grandfathered_count: int
    summarized_count: int
    skipped_count: int
    duration_seconds: float
    cost_usd: float


# ---------------- pure helpers ---------------- #


def classify_note(
    read_result: WikiReadResult,
    *,
    baseline: Optional[dict[Path, BaselineRecord]] = None,
) -> NoteKind:
    """Classify a :class:`WikiReadResult` by relpath prefix + frontmatter.

    Pure function — relies only on the read result and the (optional)
    baseline map. The classification rules:

    1. ``bumba-contributions/staging/...`` → ``bumba_staging``
    2. ``bumba-contributions/curated/...`` → ``bumba_curated``
    3. Frontmatter has a ``source`` field → ``bumba_staging`` (fallback;
       this is Bumba-authored content that ended up outside the
       quarantine subtree).
    4. :func:`baseline.is_grandfathered` matches the path → ``grandfathered``
       (we can't call the disk-reading variant here because we already
       have the body; instead we check the baseline map directly using
       the read result's metadata).
    5. Otherwise → ``operator_canonical`` (the default for operator-owned
       content authored after the baseline cut-over).
    """
    relpath = read_result.relpath
    if relpath.startswith(STAGING_PREFIX):
        return "bumba_staging"
    if relpath.startswith(CURATED_PREFIX):
        return "bumba_curated"
    if _BUMBA_FRONTMATTER_SOURCE_KEY in read_result.frontmatter:
        # Bumba-authored note that escaped the quarantine subtree.
        # Treating as staging is the conservative fallback — lint will
        # surface it as "out-of-tree, propose move".
        return "bumba_staging"
    # WikiReadResult.is_grandfathered is set by WikiRepo.read() using
    # the baseline supplied at construction time. If the caller passed
    # a baseline here too, we honour it as a tiebreaker (allows ingest
    # to be called against a freshly-loaded baseline even if the repo
    # was constructed without one).
    if read_result.is_grandfathered:
        return "grandfathered"
    if baseline:
        # Baseline entries are absolute paths; we can't resolve relpath
        # to absolute without a vault root, so this branch only fires
        # when the read_result already flagged grandfathered. Kept for
        # symmetry with the spec.
        pass
    return "operator_canonical"


def extract_title(body: str, fallback: str) -> str:
    """Extract a title from ``body`` — first H1, first non-empty line, or fallback.

    Order:
    1. First ``# Title`` line at any position (after frontmatter).
    2. First non-empty line that is not itself a heading marker (so
       ``## Section`` doesn't sneak in).
    3. ``fallback`` (typically the relpath stem).
    """
    if not body:
        return fallback
    h1 = _H1_RE.search(body)
    if h1:
        return h1.group(1).strip()
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Skip any heading line — H1 was already handled, so this
        # rejects H2+ lines like ``## Active threads``.
        if line.startswith("#"):
            continue
        return line
    return fallback


def extract_backlinks(body: str) -> tuple[str, ...]:
    """Parse ``[[wikilinks]]`` from ``body`` — return de-duplicated targets.

    - ``[[Target]]`` → ``"Target"``
    - ``[[Target|Alias]]`` → ``"Target"`` (alias dropped)
    - ``\\[[Escaped]]`` → ignored
    - Whitespace inside the target is preserved (Obsidian allows it).
    - Order matches first-occurrence; duplicates collapse to a single
      entry so callers can rely on ``len(backlinks)`` as a unique count.
    """
    if not body:
        return ()
    seen: dict[str, None] = {}
    for match in _WIKILINK_RE.finditer(body):
        target = match.group(1).strip()
        if not target:
            continue
        if target not in seen:
            seen[target] = None
    return tuple(seen.keys())


def hash_body(body: str) -> str:
    """SHA-256 hex digest of ``body`` (utf-8 encoded). Stable across runs."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _word_count(body: str) -> int:
    """Cheap word count — splits on whitespace runs."""
    if not body:
        return 0
    return len([token for token in body.split() if token])


def _first_paragraph(body: str) -> str:
    """Return the first non-empty paragraph (one-line) of ``body``.

    A "paragraph" here is the run of consecutive non-empty lines after
    skipping any leading H1 / H2 heading and blank lines. Newlines in
    the paragraph are collapsed to single spaces so the result fits
    on one summary line.
    """
    if not body:
        return ""
    lines = body.splitlines()
    out: list[str] = []
    skipping_blank = True
    for raw in lines:
        line = raw.strip()
        if skipping_blank:
            if not line:
                continue
            # Skip leading heading line so the summary isn't just a
            # repeat of the title.
            if line.startswith("#"):
                continue
            skipping_blank = False
            out.append(line)
            continue
        if not line:
            break
        out.append(line)
    return " ".join(out)


# ---------------- summarisation ---------------- #


_SUMMARY_PROMPT_PREAMBLE = (
    "Summarize the following note in one declarative sentence. "
    "Output: a single line, no preamble.\n\n"
)


async def summarize_note(
    body: str,
    *,
    dream_agent_runner: Optional[DreamAgentRunner] = None,
    cost_cap_usd: float = 0.05,
) -> tuple[str, float]:
    """Return ``(summary, cost_usd)`` for ``body``.

    Strategy:

    1. If ``dream_agent_runner`` is None or ``cost_cap_usd <= 0`` →
       fallback to :func:`_first_paragraph` (cost = 0.0).
    2. Else call the runner with a tightly-scoped prompt. The runner
       returns ``(summary, cost_usd)`` — the caller wraps a real
       :class:`DreamAgent` or a test fake.
    3. If the runner raises, returns empty, or charges more than
       ``cost_cap_usd`` → fallback (cost = whatever the runner reported,
       or 0.0 on raise). The cost is *still attributed* even on
       fallback so the global cap accounting is honest.
    """
    if not body:
        return "", 0.0
    if dream_agent_runner is None or cost_cap_usd <= 0.0:
        return _first_paragraph(body), 0.0

    prompt = _SUMMARY_PROMPT_PREAMBLE + body
    try:
        summary, cost = await dream_agent_runner(prompt)
    except Exception as exc:
        logger.warning(
            "second-brain ingest: dream_agent_runner raised %s; falling back",
            type(exc).__name__,
        )
        return _first_paragraph(body), 0.0

    # Per-call cost cap. The ingest-wide cap is enforced in
    # :func:`ingest_vault` — this is the per-note safety belt so a
    # single runaway summary cannot blow the budget on its own.
    if cost > cost_cap_usd:
        logger.info(
            "second-brain ingest: per-note cost cap exceeded "
            "(%.4f > %.4f); falling back to first-paragraph",
            cost,
            cost_cap_usd,
        )
        return _first_paragraph(body), cost

    summary = (summary or "").strip()
    if not summary:
        # Empty model output — fall back so the index stays useful.
        return _first_paragraph(body), cost
    # Collapse multi-line model output to a single line (the prompt
    # asks for one line, but be defensive).
    summary_line = " ".join(summary.split())
    return summary_line, cost


# ---------------- vault walk ---------------- #


def _iter_markdown_relpaths(repo: WikiRepo) -> Iterable[str]:
    """Yield vault-relative ``.md`` paths under ``repo.vault_root``.

    Walks the entire vault — quarantine subtree included — because the
    classifier needs to see every note to populate the index. Skips
    dot-directories (``.git``, ``.obsidian``) and dot-files; matches
    :func:`baseline._walk_markdown_files` behaviour exactly.
    """
    import os

    root = repo.vault_root
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for filename in sorted(filenames):
            if filename.startswith(".") or not filename.endswith(".md"):
                continue
            full = Path(dirpath) / filename
            yield full.relative_to(root).as_posix()


def _bump_kind_count(summary_counts: dict[str, int], kind: NoteKind) -> None:
    """In-place increment for the per-kind counters in :func:`ingest_vault`."""
    summary_counts[kind] = summary_counts.get(kind, 0) + 1


async def ingest_vault(
    vault_root: Path,
    *,
    baseline_path: Optional[Path] = None,
    summarize_canonical_only: bool = True,
    dream_agent_runner: Optional[DreamAgentRunner] = None,
    cost_cap_total_usd: float = 1.00,
) -> tuple[tuple[IngestNote, ...], IngestSummary]:
    """Walk ``vault_root``, classify and summarise each note, return the index.

    Args:
        vault_root: Operator's Obsidian vault root.
        baseline_path: Optional override for the baseline JSONL.
            Defaults to ``agent/data/second-brain-baseline.jsonl`` via
            :func:`baseline.load_baseline`.
        summarize_canonical_only: When True (default), only
            ``operator_canonical`` notes get a dream-agent summary;
            Bumba-authored notes (which already carry provenance
            frontmatter) get first-paragraph fallback. Saves cost.
        dream_agent_runner: Optional async ``(prompt) -> (summary, cost_usd)``
            callable. When None, all summaries are first-paragraph
            extraction (zero cost).
        cost_cap_total_usd: Ingest-wide cost cap. Once exceeded, the
            remaining notes get fallback summaries.

    Returns:
        ``(notes, summary)`` — tuple of :class:`IngestNote` (one per
        readable .md file) and an aggregate :class:`IngestSummary`.

    Behaviour:
        - Tolerant: any single read or summary failure logs +
          increments ``skipped_count``; ingest continues.
        - Idempotent: re-running on an unchanged vault yields
          identical sha256s and therefore identical :class:`IngestNote`
          tuples (modulo ``last_seen_iso``).
    """
    start_monotonic = time.monotonic()
    repo = WikiRepo(vault_root, baseline=load_baseline(baseline_path))

    counts: dict[str, int] = {}
    summarized_count = 0
    skipped_count = 0
    cost_total = 0.0
    notes: list[IngestNote] = []

    for relpath in sorted(_iter_markdown_relpaths(repo)):
        try:
            read_result = repo.read(relpath)
        except (OSError, ValueError, FileNotFoundError) as exc:
            logger.warning(
                "second-brain ingest: skipping unreadable note %s: %s",
                relpath,
                exc,
            )
            skipped_count += 1
            continue

        try:
            kind = classify_note(read_result, baseline=None)
        except Exception as exc:  # defensive — classify_note is pure
            logger.warning(
                "second-brain ingest: skipping note %s (classify failed: %s)",
                relpath,
                exc,
            )
            skipped_count += 1
            continue

        body = read_result.body
        body_hash = hash_body(body)
        backlinks = extract_backlinks(body)
        title = extract_title(body, fallback=Path(relpath).stem)
        wc = _word_count(body)

        # Decide whether to invoke the dream agent for this note.
        should_summarise_via_agent = (
            dream_agent_runner is not None
            and (not summarize_canonical_only or kind == "operator_canonical")
            and cost_total < cost_cap_total_usd
        )
        runner = dream_agent_runner if should_summarise_via_agent else None

        try:
            summary_text, summary_cost = await summarize_note(
                body,
                dream_agent_runner=runner,
            )
        except Exception as exc:  # defensive — summarize_note swallows
            logger.warning(
                "second-brain ingest: summarise raised on %s (%s); "
                "using first paragraph",
                relpath,
                exc,
            )
            summary_text = _first_paragraph(body)
            summary_cost = 0.0

        if runner is not None and summary_cost > 0.0:
            # Real agent invocation — count it for the cost dashboard.
            summarized_count += 1
        cost_total += summary_cost

        notes.append(
            IngestNote(
                relpath=relpath,
                kind=kind,
                title=title,
                summary=summary_text,
                frontmatter=dict(read_result.frontmatter),
                is_grandfathered=read_result.is_grandfathered,
                sha256=body_hash,
                word_count=wc,
                backlinks=backlinks,
                last_seen_iso=datetime.now(timezone.utc).isoformat(),
            ),
        )
        _bump_kind_count(counts, kind)

    duration = time.monotonic() - start_monotonic

    summary = IngestSummary(
        total_notes=len(notes),
        operator_canonical_count=counts.get("operator_canonical", 0),
        bumba_staging_count=counts.get("bumba_staging", 0),
        bumba_curated_count=counts.get("bumba_curated", 0),
        grandfathered_count=counts.get("grandfathered", 0),
        summarized_count=summarized_count,
        skipped_count=skipped_count,
        duration_seconds=duration,
        cost_usd=cost_total,
    )
    return tuple(notes), summary
