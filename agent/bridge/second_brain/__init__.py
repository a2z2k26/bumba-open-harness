"""Second-brain subsystem — operator's Obsidian vault as Bumba's persistent wiki.

This package will host the second-brain subsystem per Plan 05 of the
2026-04-25 reference-audit bundle. It targets the operator's existing
Obsidian vault (ADR Decision 1, signed 2026-05-01 — see
``agent/docs/architecture/second-brain.md``).

Sprint 05.0a ships the **baseline ingest** — a one-shot walk over the
operator's vault that records existing notes as "grandfathered" so
day-1 lint (Sprint 05.09) does not flood the operator with hundreds of
"fix me" alerts on every pre-existing page.

Sprint 05.0b ships **daily vault-backup primitives** so a clean
rollback target always exists before any Bumba write session begins.

Sprint 05.04 ships the ``SecondBrainContributor`` Protocol and the
``bumba-contributions/`` quarantine subtree (ADR Decision 3, signed
2026-05-01 — Bumba never writes to canonical pages directly).

Public surface:

- ``BaselineRecord`` — frozen dataclass, one entry per .md file at
  ingest time (path + sha256 + mtime + grandfathered_at).
- ``ingest_baseline`` — walk a vault root, write
  ``agent/data/second-brain-baseline.jsonl`` (idempotent).
- ``is_grandfathered`` — query the baseline for a single path.
- ``load_baseline`` — read the baseline JSONL into a path→record map.
- ``snapshot_vault`` — create a tar.gz snapshot of the operator's vault.
- ``ensure_snapshot_today`` — idempotent: returns today's snapshot path,
  creating it if needed.
- ``latest_snapshot`` — most recent snapshot path, or None.
- ``prune_old_snapshots`` — remove snapshots older than ``keep_days``.
- ``Contribution`` — frozen dataclass for a proposed wiki note.
- ``SecondBrainContributor`` — runtime-checkable Protocol implemented
  by any module that wants to contribute to the wiki.
- ``ContributorRegistry`` — in-memory registry with stable iteration.
- ``ensure_subtree`` — idempotently create
  ``bumba-contributions/{staging,curated}/`` + README.

This subsystem is read-only with respect to operator-canonical content.
Concept-only — no third-party source copied (Karpathy gist informs the
markdown-wiki shape; nothing copied verbatim).
"""

from __future__ import annotations

from .backup import (
    DEFAULT_BACKUP_DIRNAME,
    DEFAULT_KEEP_DAYS,
    EXCLUDED_DIR_NAMES,
    ensure_snapshot_today,
    latest_snapshot,
    prune_old_snapshots,
    snapshot_vault,
)
from .baseline import (
    BaselineRecord,
    ingest_baseline,
    is_grandfathered,
    load_baseline,
)
from .contributor import (
    Contribution,
    ContributorDestination,
    ContributorRegistry,
    ContributorSource,
    SecondBrainContributor,
    ensure_subtree,
)
from .contributors import (
    ConsolidationContributor,
    DailyLogContributor,
    ReflectionContributor,
)
from .ingest import (
    IngestNote,
    IngestSummary,
    NoteKind,
    classify_note,
    extract_backlinks,
    extract_title,
    hash_body,
    ingest_vault,
    summarize_note,
)
from .lint import (
    LintFinding,
    LintReport,
    LintRule,
    LintSeverity,
    lint_duplicate_filenames,
    lint_frontmatter,
    lint_orphaned,
    lint_vault,
    lint_wikilinks,
)
from .promote import (
    PromoteResult,
    RejectResult,
    promote_note,
    reject_note,
    strip_frontmatter,
)
from .query import (
    QueryResponse,
    QueryResult,
    QueryStrategy,
    RetrievalSource,
    merge_results,
    query,
    query_hybrid,
    query_index,
    score_index_match,
)
from .wiki_repo import (
    CURATED_PREFIX,
    STAGING_PREFIX,
    WikiNote,
    WikiReadResult,
    WikiRepo,
)

__all__ = [
    "BaselineRecord",
    "CURATED_PREFIX",
    "ConsolidationContributor",
    "Contribution",
    "ContributorDestination",
    "ContributorRegistry",
    "ContributorSource",
    "DEFAULT_BACKUP_DIRNAME",
    "DEFAULT_KEEP_DAYS",
    "DailyLogContributor",
    "EXCLUDED_DIR_NAMES",
    "IngestNote",
    "IngestSummary",
    "LintFinding",
    "LintReport",
    "LintRule",
    "LintSeverity",
    "NoteKind",
    "PromoteResult",
    "QueryResponse",
    "QueryResult",
    "QueryStrategy",
    "ReflectionContributor",
    "RejectResult",
    "RetrievalSource",
    "STAGING_PREFIX",
    "SecondBrainContributor",
    "WikiNote",
    "WikiReadResult",
    "WikiRepo",
    "classify_note",
    "ensure_snapshot_today",
    "ensure_subtree",
    "extract_backlinks",
    "extract_title",
    "hash_body",
    "ingest_baseline",
    "ingest_vault",
    "is_grandfathered",
    "latest_snapshot",
    "lint_duplicate_filenames",
    "lint_frontmatter",
    "lint_orphaned",
    "lint_vault",
    "lint_wikilinks",
    "load_baseline",
    "merge_results",
    "promote_note",
    "prune_old_snapshots",
    "query",
    "query_hybrid",
    "query_index",
    "reject_note",
    "score_index_match",
    "snapshot_vault",
    "strip_frontmatter",
    "summarize_note",
]
