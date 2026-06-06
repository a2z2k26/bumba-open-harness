"""lint.py — daily lint pass for the second-brain vault.

Sprint 05.09 (issue #1017) of the 2026-04-25 reference-audit bundle.
ADR sign-off: ``agent/docs/architecture/second-brain.md`` Decision 5
(``__AZ__`` 2026-05-01) — the wiki is the source of truth;
``temporal_knowledge`` is the audit log of detected deltas. Lint
warnings flag schema/integrity issues without blocking writes.

Schema doc: ``agent/config/second-brain-schema.md`` (PR #1129,
schema_version=1) — the five lint rules implemented here are the
canonical contract for what "valid" means in
``bumba-contributions/``.

Why this exists
---------------
After 05.06 ingest classifies the vault and 05.07 contributors stage
content, *something* must check that staged content respects the
schema before the operator promotes it. The lint pass is that check.

Five rules — minimal, schema-aligned:

1. **frontmatter_valid** — YAML present + required fields populated.
2. **no_broken_wikilinks** — every ``[[link]]`` resolves to a vault file.
3. **no_duplicate_filenames** — within ``bumba-contributions/``, no two
   files share a basename.
4. **schema_version_match** — ``schema_version`` matches the current
   integer.
5. **not_orphaned** — file is referenced by ``index.md`` or by another
   note. Pure orphans flag for operator review.

Rules 1, 4, 5 do not apply to baseline-grandfathered files (per schema
doc — operator content predates the schema and is not retroactively
conformed). Rules 2 and 3 always apply.

Defensive contract
------------------
- Read errors (missing files, malformed YAML) emit a finding and
  continue. Lint never crashes the calling service.
- Idempotent: running twice on an unchanged vault produces identical
  findings (tuple ordering is deterministic).
- The lint pass is non-blocking — its outputs are reports, not gates.

Concept-only — no third-party source copied (Karpathy gist informs the
markdown-wiki shape only; ``concept-only-no-license``).
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from .baseline import BaselineRecord
from .ingest import extract_backlinks
from .wiki_repo import (
    WikiReadResult,
    WikiRepo,
)

logger = logging.getLogger(__name__)


LintRule = Literal[
    "frontmatter_valid",
    "no_broken_wikilinks",
    "no_duplicate_filenames",
    "schema_version_match",
    "not_orphaned",
]

LintSeverity = Literal["error", "warning", "info"]


# Required frontmatter fields per second-brain-schema.md#frontmatter.
_REQUIRED_FRONTMATTER_FIELDS: tuple[str, ...] = (
    "source",
    "session_id",
    "authored_at",
    "provenance",
    "schema_version",
)

# Quarantine prefix the operator's vault uses for Bumba-authored notes.
_BUMBA_CONTRIB_PREFIX = "bumba-contributions/"


@dataclass(frozen=True)
class LintFinding:
    """One lint warning emitted during a vault pass.

    Frozen so callers can stash findings in sets / use them as dict keys
    without worrying about mutation. ``message`` is human-readable and
    safe to surface directly on the Discord report.
    """

    relpath: str
    rule: LintRule
    severity: LintSeverity
    message: str


@dataclass(frozen=True)
class LintReport:
    """Aggregate result of one ``lint_vault`` pass.

    ``findings`` is sorted by ``(relpath, rule, message)`` so two
    equivalent passes always produce equal reports — making the lint
    pipeline diffable and idempotent.
    """

    findings: tuple[LintFinding, ...]
    total_notes_scanned: int
    grandfathered_skipped: int
    duration_seconds: float


# ---------------- pure rule functions ---------------- #


def lint_frontmatter(
    read_result: WikiReadResult,
    *,
    schema_version: int = 1,
) -> Optional[LintFinding]:
    """Rule 1 + Rule 4 collapsed.

    Cases:

    - Empty frontmatter → ``error`` ``frontmatter_valid``
      (Bumba-authored note missing the YAML block entirely).
    - Frontmatter present but missing required field(s) → ``error``
      ``frontmatter_valid`` listing what's missing.
    - Frontmatter present + required fields populated, but
      ``schema_version`` does not match the current integer →
      ``warning`` ``schema_version_match`` (a migration pointer, never
      a hard fail per schema doc).
    - Operator-edited transition (frontmatter present, ``source``
      field dropped per schema doc convention) → ``info``
      ``frontmatter_valid`` so the operator can re-classify.

    Returns ``None`` if everything passes.
    """
    fm = read_result.frontmatter
    if not fm:
        return LintFinding(
            relpath=read_result.relpath,
            rule="frontmatter_valid",
            severity="error",
            message="missing frontmatter block (no YAML at file head)",
        )
    missing = [f for f in _REQUIRED_FRONTMATTER_FIELDS if f not in fm]
    # Operator-edit transition: schema doc says when the operator edits a
    # Bumba-authored file they SHOULD drop the ``source`` field; lint
    # then re-classifies. That's an informational signal, not an error.
    if missing == ["source"] and "schema_version" in fm:
        return LintFinding(
            relpath=read_result.relpath,
            rule="frontmatter_valid",
            severity="info",
            message=(
                "operator-edited transition detected: 'source' field "
                "dropped — note will be re-classified as canonical"
            ),
        )
    if missing:
        return LintFinding(
            relpath=read_result.relpath,
            rule="frontmatter_valid",
            severity="error",
            message=(
                "frontmatter missing required field(s): "
                + ", ".join(missing)
            ),
        )
    found_version = fm.get("schema_version")
    # The wiki_repo parser stores schema_version as int when castable,
    # else as the raw string. Anything that does not equal the current
    # integer warrants a migration pointer.
    if found_version != schema_version:
        return LintFinding(
            relpath=read_result.relpath,
            rule="schema_version_match",
            severity="warning",
            message=(
                f"schema_version mismatch: current={schema_version}, "
                f"found={found_version!r} — migration script needed"
            ),
        )
    return None


def _wikilink_resolves(
    target: str,
    *,
    all_relpaths: set[str],
) -> bool:
    """Lenient wikilink resolution.

    Match logic, in order of precedence:

    1. Exact relpath match (``[[bumba-contributions/staging/foo.md]]``).
    2. Exact relpath + ``.md`` (``[[bumba-contributions/staging/foo]]``).
    3. Basename match — the wikilink target's last segment matches any
       relpath's basename, case-insensitive, with-or-without ``.md``.
    4. Suffix match — any relpath ends with ``/<target>`` or
       ``/<target>.md`` (case-insensitive). Catches ``[[Path/Note]]``
       referring to ``staging/Path/Note.md``.

    The lenient logic is intentional — Obsidian wikilinks are loose by
    convention and lint should match Obsidian's resolution behaviour
    rather than invent a stricter contract.
    """
    if not target:
        return False
    target_norm = target.strip()
    # Strip a trailing #anchor / ^block-ref so they don't break resolution.
    for sep in ("#", "^"):
        if sep in target_norm:
            target_norm = target_norm.split(sep, 1)[0].rstrip()
    if not target_norm:
        return False

    if target_norm in all_relpaths:
        return True
    with_md = target_norm if target_norm.endswith(".md") else target_norm + ".md"
    if with_md in all_relpaths:
        return True

    target_lower = target_norm.lower()
    target_lower_md = with_md.lower()
    target_basename_lower = target_lower.rsplit("/", 1)[-1]
    target_basename_md_lower = (
        target_basename_lower
        if target_basename_lower.endswith(".md")
        else target_basename_lower + ".md"
    )

    for rel in all_relpaths:
        rel_lower = rel.lower()
        rel_basename = rel_lower.rsplit("/", 1)[-1]
        if rel_basename == target_basename_md_lower:
            return True
        # Suffix path match: rel ends with /target or /target.md.
        if rel_lower.endswith("/" + target_lower):
            return True
        if rel_lower.endswith("/" + target_lower_md):
            return True
    return False


def lint_wikilinks(
    read_result: WikiReadResult,
    *,
    all_relpaths: set[str],
) -> list[LintFinding]:
    """Rule 2. Returns one finding per broken ``[[wikilink]]`` in body.

    Reuses :func:`bridge.second_brain.ingest.extract_backlinks` so the
    parsing rules stay consistent across the subsystem (escaped links,
    ``[[Target|Alias]]`` aliases, deduping).
    """
    findings: list[LintFinding] = []
    targets = extract_backlinks(read_result.body)
    if not targets:
        return findings
    for target in targets:
        if _wikilink_resolves(target, all_relpaths=all_relpaths):
            continue
        findings.append(
            LintFinding(
                relpath=read_result.relpath,
                rule="no_broken_wikilinks",
                severity="warning",
                message=f"broken wikilink: [[{target}]] does not resolve",
            ),
        )
    return findings


def lint_duplicate_filenames(
    all_relpaths: Iterable[str],
) -> list[LintFinding]:
    """Rule 3. Flags duplicate basenames within ``bumba-contributions/``.

    Operator-canonical content (outside ``bumba-contributions/``) is not
    checked — the operator is free to organise their vault however they
    like. Within the quarantine subtree, basename uniqueness is the
    contract so the operator can navigate by filename alone.

    For each set of N>=2 colliding basenames, one finding per
    participating relpath is emitted (so the operator sees both/all
    sides of the collision).
    """
    by_basename: dict[str, list[str]] = {}
    for rel in all_relpaths:
        if not rel.startswith(_BUMBA_CONTRIB_PREFIX):
            continue
        basename = rel.rsplit("/", 1)[-1]
        by_basename.setdefault(basename, []).append(rel)

    findings: list[LintFinding] = []
    for basename, relpaths in by_basename.items():
        if len(relpaths) < 2:
            continue
        siblings = sorted(relpaths)
        for rel in siblings:
            others = [s for s in siblings if s != rel]
            findings.append(
                LintFinding(
                    relpath=rel,
                    rule="no_duplicate_filenames",
                    severity="warning",
                    message=(
                        f"duplicate basename {basename!r} also at: "
                        + ", ".join(others)
                    ),
                ),
            )
    return findings


def lint_orphaned(
    relpath: str,
    *,
    index_relpaths: set[str],
    backlinked_relpaths: set[str],
) -> Optional[LintFinding]:
    """Rule 5. Returns a finding when ``relpath`` is a pure orphan.

    "Orphan" definition (per schema doc): ``relpath`` lives under
    ``bumba-contributions/`` AND is not referenced by ``index.md`` AND
    is not the target of any other note's wikilink.

    Operator-canonical content is never flagged — the operator owns
    their organisational scheme above ``bumba-contributions/``.
    """
    if not relpath.startswith(_BUMBA_CONTRIB_PREFIX):
        return None
    if relpath in index_relpaths:
        return None
    if relpath in backlinked_relpaths:
        return None
    return LintFinding(
        relpath=relpath,
        rule="not_orphaned",
        severity="warning",
        message=(
            "orphan: not referenced by index.md or any other note "
            "(promote or delete candidate)"
        ),
    )


# ---------------- vault-level orchestration ---------------- #


def _resolve_backlinked_targets(
    *,
    all_relpaths: set[str],
    raw_targets_by_relpath: dict[str, tuple[str, ...]],
) -> set[str]:
    """Resolve every wikilink target to its concrete vault relpath.

    Pure helper used by :func:`lint_vault` to build the set of relpaths
    that *something* in the vault links to. Reuses the same lenient
    matching as :func:`_wikilink_resolves` so a backlink detected here
    is the same one that would resolve elsewhere.
    """
    referenced: set[str] = set()
    for source_rel, targets in raw_targets_by_relpath.items():
        for target in targets:
            target_norm = target.strip()
            for sep in ("#", "^"):
                if sep in target_norm:
                    target_norm = target_norm.split(sep, 1)[0].rstrip()
            if not target_norm:
                continue
            with_md = (
                target_norm
                if target_norm.endswith(".md")
                else target_norm + ".md"
            )
            target_lower = target_norm.lower()
            target_lower_md = with_md.lower()
            target_basename_lower = target_lower.rsplit("/", 1)[-1]
            target_basename_md_lower = (
                target_basename_lower
                if target_basename_lower.endswith(".md")
                else target_basename_lower + ".md"
            )
            # Direct path matches first.
            if target_norm in all_relpaths:
                referenced.add(target_norm)
                continue
            if with_md in all_relpaths:
                referenced.add(with_md)
                continue
            # Otherwise scan for basename / suffix matches and add every
            # candidate that the wikilink could plausibly point at. A
            # wikilink that resolves to two files (duplicate basename)
            # marks both as referenced — neither is orphaned by it.
            for rel in all_relpaths:
                # Don't count a note as referencing itself.
                if rel == source_rel:
                    continue
                rel_lower = rel.lower()
                rel_basename = rel_lower.rsplit("/", 1)[-1]
                if rel_basename == target_basename_md_lower:
                    referenced.add(rel)
                    continue
                if rel_lower.endswith("/" + target_lower):
                    referenced.add(rel)
                    continue
                if rel_lower.endswith("/" + target_lower_md):
                    referenced.add(rel)
    return referenced


def _is_grandfathered(
    relpath: str,
    baseline: dict[Path, BaselineRecord] | None,
    vault_root: Path,
) -> bool:
    """True iff the absolute path for ``relpath`` is in the baseline map.

    The baseline is keyed by absolute :class:`Path`. Resolution mirrors
    :func:`baseline.is_grandfathered` but without re-hashing — at lint
    time, presence in the baseline is enough; the ingest classifier
    (05.06) already used hash-match to decide whether to mark the read
    result grandfathered. We trust that signal here.
    """
    if not baseline:
        return False
    target = (vault_root / relpath).resolve()
    return any(p.resolve() == target for p in baseline)


def lint_vault(
    vault_root: Path,
    *,
    baseline: Optional[dict[Path, BaselineRecord]] = None,
    schema_version: int = 1,
) -> LintReport:
    """Run the full 5-rule lint pass over a vault.

    Walks every ``.md`` under ``bumba-contributions/staging/`` and
    ``bumba-contributions/curated/``. Operator-canonical content
    outside that subtree is read for backlink resolution but is never
    itself the subject of a finding (per ADR Decision 5 — wiki = SoT).

    Args:
        vault_root: Operator's Obsidian vault root.
        baseline: Optional baseline map (output of
            :func:`bridge.second_brain.baseline.load_baseline`). Files
            present here skip rules 1, 4, 5; rules 2 and 3 still apply.
        schema_version: Current schema integer (defaults to 1, matching
            the schema doc).

    Returns:
        :class:`LintReport` — sorted, deterministic, idempotent.

    Behaviour:
        - Defensive: any individual read error emits a finding and
          continues.
        - Idempotent: identical input → identical output (modulo
          ``duration_seconds``).
    """
    start_monotonic = time.monotonic()
    repo = WikiRepo(vault_root, baseline=baseline)

    # Build the universe of relpaths we know about. We scan everything
    # under the vault so wikilinks can resolve to operator-canonical
    # content (e.g. a staging note linking ``[[index]]``).
    all_relpaths: set[str] = set()
    contrib_relpaths: list[str] = []
    other_md_relpaths: list[str] = []

    for dirpath, dirnames, filenames in os.walk(vault_root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for fname in sorted(filenames):
            if fname.startswith(".") or not fname.endswith(".md"):
                continue
            full = Path(dirpath) / fname
            try:
                rel = full.relative_to(vault_root).as_posix()
            except ValueError:
                continue
            all_relpaths.add(rel)
            if rel.startswith(_BUMBA_CONTRIB_PREFIX):
                contrib_relpaths.append(rel)
            else:
                other_md_relpaths.append(rel)

    contrib_relpaths.sort()
    other_md_relpaths.sort()

    findings: list[LintFinding] = []
    grandfathered_skipped = 0

    # Read every md file once — both for rules 1/4 (frontmatter) and to
    # collect every note's outbound wikilinks (rule 5 needs the union
    # of inbound references).
    raw_targets_by_relpath: dict[str, tuple[str, ...]] = {}
    contrib_read_results: dict[str, WikiReadResult] = {}

    for rel in contrib_relpaths:
        try:
            result = repo.read(rel)
        except (OSError, ValueError, FileNotFoundError) as exc:
            logger.warning(
                "second-brain lint: skipping unreadable note %s: %s", rel, exc,
            )
            findings.append(
                LintFinding(
                    relpath=rel,
                    rule="frontmatter_valid",
                    severity="error",
                    message=f"could not read note ({type(exc).__name__})",
                ),
            )
            continue
        contrib_read_results[rel] = result
        # Record outbound links from contrib notes for rule 5.
        try:
            raw_targets_by_relpath[rel] = extract_backlinks(result.body)
        except Exception as exc:  # defensive — extract_backlinks is pure
            logger.warning(
                "second-brain lint: backlink extraction failed for %s: %s",
                rel, exc,
            )
            raw_targets_by_relpath[rel] = ()

    # Also harvest backlinks from operator-canonical notes — a staging
    # note referenced by index.md (or any other operator-owned note) is
    # not orphaned.
    for rel in other_md_relpaths:
        try:
            result = repo.read(rel)
        except (OSError, ValueError, FileNotFoundError):
            # Operator-canonical read failures are not lint findings —
            # we just lose backlink coverage for that file.
            continue
        try:
            raw_targets_by_relpath[rel] = extract_backlinks(result.body)
        except Exception:
            raw_targets_by_relpath[rel] = ()

    # Build the reference set from the entire vault, then carve out
    # index.md membership separately for the schema doc's "referenced
    # by index.md OR another note" wording.
    backlinked = _resolve_backlinked_targets(
        all_relpaths=all_relpaths,
        raw_targets_by_relpath=raw_targets_by_relpath,
    )
    index_targets: tuple[str, ...] = raw_targets_by_relpath.get("index.md", ())
    index_resolved = _resolve_backlinked_targets(
        all_relpaths=all_relpaths,
        raw_targets_by_relpath={"index.md": index_targets},
    )

    # Rule 3 runs once across the contrib subtree.
    findings.extend(lint_duplicate_filenames(contrib_relpaths))

    # Rules 1, 2, 4, 5 — per-note.
    for rel, result in contrib_read_results.items():
        is_gf = result.is_grandfathered or _is_grandfathered(
            rel, baseline, vault_root,
        )
        if is_gf:
            grandfathered_skipped += 1
        # Rule 1 + Rule 4 — skipped for grandfathered.
        if not is_gf:
            fm_finding = lint_frontmatter(result, schema_version=schema_version)
            if fm_finding is not None:
                findings.append(fm_finding)
        # Rule 2 — always applies.
        findings.extend(
            lint_wikilinks(result, all_relpaths=all_relpaths),
        )
        # Rule 5 — skipped for grandfathered.
        if not is_gf:
            orphan = lint_orphaned(
                rel,
                index_relpaths=index_resolved,
                backlinked_relpaths=backlinked,
            )
            if orphan is not None:
                findings.append(orphan)

    # Deterministic ordering — sort by relpath, then rule name.
    findings_sorted = tuple(
        sorted(findings, key=lambda f: (f.relpath, f.rule, f.message)),
    )
    duration = time.monotonic() - start_monotonic

    return LintReport(
        findings=findings_sorted,
        total_notes_scanned=len(contrib_read_results),
        grandfathered_skipped=grandfathered_skipped,
        duration_seconds=duration,
    )
