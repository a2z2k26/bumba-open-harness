"""finalize_experiments — group keep iterations into reviewable branches.

Sprint 02.08 / spec ref-audit-02-08 (issue #983). Concept ported from
pi-autoresearch (MIT, paraphrased — no source copied).

After many days of `experiment_loop` iterations, ``main`` accumulates a
flurry of micro-commits flagged ``status=keep``. Reviewing 50-200
commits one-by-one is unwieldy. This script groups them into a small
number of operator-reviewable ``experiment-finalize/<group>`` branches.

Two grouping modes:

- **By files-touched**: greedy clustering by Jaccard similarity on the
  set of files each iteration modified (default threshold 0.5).
- **By topic**: tokenize commit subjects, cluster by Jaccard similarity
  on the top-K keywords. Used when scope-overlap is sparse.

The finalizer reads ``data/experiments.jsonl`` (Sprint 02.03, written
by ``experiment_loop.log_result``), filters to ``status=keep`` records
inside a window (default last 30 days), groups them, and creates one
branch per group at ``experiment-finalize/<name>`` containing that
group's commits via ``git cherry-pick``. A summary markdown report is
written alongside.

Out of scope (explicit per spec):

- The script does not auto-PR. Operator decides what to do with the
  curated branches.
- Cherry-pick conflicts leave the branch in a half-state with prefix
  ``experiment-finalize/CONFLICT-<name>`` and the report flags it; the
  loop keeps making other branches.

Pure helpers (``load_keep_iterations``, ``group_by_files``,
``group_by_topic``, ``write_finalize_report``) take no I/O beyond the
file path they're given so the test suite can drive them with
in-memory data. ``create_finalize_branch`` accepts a ``git`` callable
override so the same tests can drive it with a recorded fake instead
of forking a real ``git`` subprocess.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

GroupingMode = Literal["files", "topic"]
BRANCH_PREFIX = "experiment-finalize/"
CONFLICT_PREFIX = "experiment-finalize/CONFLICT-"

# Stop-words removed from commit subjects before topic clustering.
# Keep small — the goal is to drop scaffolding tokens (prepositions,
# verbs that show up in nearly every commit), not to do real NLP.
_TOPIC_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "and", "the", "to", "of", "for", "in", "on", "at",
    "with", "from", "by", "is", "are", "be", "this", "that",
    "add", "added", "fix", "fixed", "update", "updated", "remove",
    "removed", "refactor", "refactored", "feat", "chore", "docs",
    "test", "tests", "ci", "perf", "iter", "experiment",
})

_TOPIC_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")

# subprocess.run wrapper signature used by ``create_finalize_branch``.
GitCallable = Callable[[list[str], Path], subprocess.CompletedProcess]

log = logging.getLogger("finalize_experiments")


# ── Data model ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class IterationRecord:
    """One ``status=keep`` iteration parsed from ``experiments.jsonl``.

    Fields mirror the JSONL schema written by
    ``experiment_loop.log_result`` (see ``jsonl_record`` in that
    function). ``files_touched`` is parsed out of ``diff_summary`` —
    git's ``--stat`` output. ``commit_subject`` is the first line of
    the iteration's ``description``.
    """

    iter_id: str
    completed_at_iso: str
    files_touched: tuple[str, ...]
    fitness_before: float
    fitness_after: float
    fitness_delta: float
    cost_usd: float
    commit_subject: str
    commit_sha: str


@dataclass(frozen=True)
class IterationGroup:
    """Cluster of iterations that should land on one finalize branch."""

    name: str
    members: tuple[IterationRecord, ...]
    total_fitness_delta: float
    total_cost_usd: float
    union_files_touched: tuple[str, ...]


@dataclass(frozen=True)
class FinalizeReport:
    """Aggregate output of one finalize run."""

    window_start_iso: str
    window_end_iso: str
    grouping_mode: GroupingMode
    total_iterations: int
    groups: tuple[IterationGroup, ...]
    branches_created: tuple[str, ...]
    duration_seconds: float


# ── JSONL loader ───────────────────────────────────────────────────


_DIFF_STAT_FILE_RE = re.compile(r"^\s*([^|]+?)\s*\|", re.MULTILINE)


def _parse_files_from_diff_summary(diff_summary: str | None) -> tuple[str, ...]:
    """Extract changed file paths from a ``git diff --stat`` blob.

    The blob shape (per ``experiment_loop.run_iteration``) is::

        agent/bridge/foo.py | 12 ++++++++----
        agent/tests/test_foo.py | 5 ++++-
         2 files changed, 13 insertions(+), 4 deletions(-)

    We pull the first column up to the ``|``; the trailing summary line
    (``2 files changed, ...``) has no ``|`` so it's silently skipped.
    """
    if not diff_summary:
        return ()
    files: list[str] = []
    for match in _DIFF_STAT_FILE_RE.finditer(diff_summary):
        candidate = match.group(1).strip()
        # Skip git's binary-rename markers / blank lines.
        if not candidate or candidate.startswith("==>"):
            continue
        files.append(candidate)
    return tuple(files)


def _commit_subject(description: str | None) -> str:
    """First non-empty line of ``description`` — used as the commit subject."""
    if not description:
        return ""
    for line in description.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _parse_iso(value: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp the loop writes; returns ``None`` on failure.

    ``experiments.jsonl`` writes ``datetime.now().isoformat(timespec="seconds")``
    (naive). When the value lacks a tz suffix we assume UTC so window
    filtering stays self-consistent.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def load_keep_iterations(
    *,
    jsonl_path: Path,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> list[IterationRecord]:
    """Read ``experiments.jsonl`` and return only ``status=keep`` records.

    The file is one JSON object per line (Sprint 02.03 schema). Lines
    that fail to parse are logged and skipped — the file is operator-
    visible and a single bad line should never poison a finalize run.
    Window filter is half-open: ``since <= completed_at < until``. Both
    ends optional.
    """
    if not jsonl_path.exists():
        return []

    out: list[IterationRecord] = []
    raw = jsonl_path.read_text()
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            log.warning(
                "experiments.jsonl line %d: skipping malformed JSON (%s)",
                lineno, exc,
            )
            continue

        if record.get("status") != "keep":
            continue

        completed_at = record.get("created_at") or ""
        when = _parse_iso(completed_at)
        if since is not None and (when is None or when < since):
            continue
        if until is not None and (when is None or when >= until):
            continue

        snapshot = record.get("notes") or {}
        # ``fitness_snapshot`` style numbers may live under the top-level
        # record or under ``notes``; we accept either to stay forgiving.
        before = float(record.get("fitness_before") or snapshot.get("fitness_before") or 0.0)
        after = float(record.get("fitness_after") or snapshot.get("fitness_after") or 0.0)
        delta = float(record.get("fitness_delta") or 0.0)

        rec = IterationRecord(
            iter_id=str(record.get("iter_id") or ""),
            completed_at_iso=completed_at,
            files_touched=_parse_files_from_diff_summary(record.get("diff_summary")),
            fitness_before=before,
            fitness_after=after,
            fitness_delta=delta,
            cost_usd=float(record.get("cost_usd") or 0.0),
            commit_subject=_commit_subject(record.get("description")),
            commit_sha=str(record.get("commit_hash") or ""),
        )
        out.append(rec)
    return out


# ── Grouping: by files-touched ─────────────────────────────────────


def _jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    """Jaccard similarity on two iterables; 0.0 when both empty."""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    if union == 0:
        return 0.0
    return inter / union


def _common_path_prefix(files: Iterable[str]) -> str:
    """Pick a short, human label for a group from its member files.

    Grabs the deepest directory shared by every file. When no shared
    prefix exists we return the most-common top-level directory, which
    is good enough for a branch slug.
    """
    files = [f for f in files if f]
    if not files:
        return "misc"
    parts_per_file = [f.split("/") for f in files]
    common: list[str] = []
    for col in zip(*parts_per_file):
        first = col[0]
        if all(p == first for p in col):
            common.append(first)
        else:
            break
    if common:
        # Drop the trailing file name if every path landed on the same one.
        if all(len(parts) == len(common) for parts in parts_per_file):
            return "/".join(common[:-1]) or common[0]
        return "/".join(common)
    # No prefix at all — fall back to the most common top-level dir.
    tops = [parts[0] for parts in parts_per_file if parts]
    if not tops:
        return "misc"
    return max(set(tops), key=tops.count)


def _slugify(label: str) -> str:
    """Make a string safe for a git branch suffix."""
    label = label.strip().lower()
    label = re.sub(r"[^a-z0-9._/-]+", "-", label)
    label = label.strip("-/")
    return label or "misc"


def _summarize_group(name: str, members: list[IterationRecord]) -> IterationGroup:
    """Build an ``IterationGroup`` from its members.

    Files touched is the union across members; totals are summed. The
    members tuple stays in input order — callers should sort iterations
    chronologically before clustering so cherry-pick replays history.
    """
    union: list[str] = []
    seen: set[str] = set()
    for m in members:
        for f in m.files_touched:
            if f not in seen:
                seen.add(f)
                union.append(f)
    return IterationGroup(
        name=name,
        members=tuple(members),
        total_fitness_delta=sum(m.fitness_delta for m in members),
        total_cost_usd=sum(m.cost_usd for m in members),
        union_files_touched=tuple(union),
    )


def group_by_files(
    iterations: Iterable[IterationRecord],
    *,
    similarity_threshold: float = 0.5,
) -> list[IterationGroup]:
    """Greedy clustering by Jaccard similarity on ``files_touched``.

    For each iteration in order: assign to the first existing cluster
    whose centroid (cluster's union of files) Jaccard-overlaps the
    iteration above ``similarity_threshold``; otherwise seed a new
    cluster. Pure function — no I/O. Group names are derived from a
    common path prefix across the cluster's union files, slugified.
    """
    iterations = list(iterations)
    if not iterations:
        return []

    clusters: list[list[IterationRecord]] = []
    cluster_unions: list[set[str]] = []

    for rec in iterations:
        files = set(rec.files_touched)
        placed = False
        for idx, union in enumerate(cluster_unions):
            score = _jaccard(files, union)
            if score >= similarity_threshold:
                clusters[idx].append(rec)
                cluster_unions[idx] = union | files
                placed = True
                break
        if not placed:
            clusters.append([rec])
            cluster_unions.append(set(files))

    groups: list[IterationGroup] = []
    used_names: set[str] = set()
    for members in clusters:
        union_files = sorted({f for m in members for f in m.files_touched})
        prefix = _common_path_prefix(union_files) if union_files else "misc"
        base = _slugify(prefix or "misc")
        name = base
        # Disambiguate when multiple clusters resolve to the same prefix.
        suffix = 2
        while name in used_names:
            name = f"{base}-{suffix}"
            suffix += 1
        used_names.add(name)
        groups.append(_summarize_group(name, members))
    return groups


# ── Grouping: by topic (commit-subject keyword overlap) ────────────


def _topic_tokens(subject: str, *, top_n: int) -> tuple[str, ...]:
    """Top-N keyword tokens for a commit subject.

    Naive tokenization: ASCII word-ish runs, lowercased, stop-word
    filtered, deduplicated, truncated to N. Order is insertion order
    (i.e. order of first appearance in the subject) so the leading
    tokens — which usually carry the most subject-specific signal —
    win when N is small.
    """
    if not subject:
        return ()
    tokens: list[str] = []
    seen: set[str] = set()
    for match in _TOPIC_TOKEN_RE.finditer(subject):
        tok = match.group(0).lower()
        if tok in _TOPIC_STOPWORDS:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        tokens.append(tok)
        if len(tokens) >= top_n:
            break
    return tuple(tokens)


def group_by_topic(
    iterations: Iterable[IterationRecord],
    *,
    keyword_top_n: int = 3,
    similarity_threshold: float = 0.34,
) -> list[IterationGroup]:
    """Greedy clustering by Jaccard on top-K commit-subject keywords.

    Each iteration is reduced to its top-K keywords and then clustered
    the same way ``group_by_files`` clusters by files. With K=3 the
    similarity_threshold defaults to 0.34 (≈ "share at least one of
    three"), which clusters `(import, cleanup, lint)` and
    `(import, lint)` together but keeps `(import, cleanup, lint)` and
    `(perf, cache, hotpath)` apart.

    Iterations whose subject yields zero post-filter tokens land in
    their own singleton group named ``topic-untagged-<n>``. Pure
    function.
    """
    iterations = list(iterations)
    if not iterations:
        return []

    clusters: list[list[IterationRecord]] = []
    cluster_keywords: list[set[str]] = []

    for rec in iterations:
        kws = set(_topic_tokens(rec.commit_subject, top_n=keyword_top_n))
        if not kws:
            clusters.append([rec])
            cluster_keywords.append(set())
            continue
        placed = False
        for idx, existing in enumerate(cluster_keywords):
            if not existing:
                continue
            score = _jaccard(kws, existing)
            if score >= similarity_threshold:
                clusters[idx].append(rec)
                cluster_keywords[idx] = existing | kws
                placed = True
                break
        if not placed:
            clusters.append([rec])
            cluster_keywords.append(set(kws))

    groups: list[IterationGroup] = []
    used_names: set[str] = set()
    untagged_idx = 0
    for members, kws in zip(clusters, cluster_keywords):
        if kws:
            label = "-".join(sorted(kws)[:keyword_top_n])
            base = _slugify(f"topic-{label}")
        else:
            untagged_idx += 1
            base = f"topic-untagged-{untagged_idx}"
        name = base
        suffix = 2
        while name in used_names:
            name = f"{base}-{suffix}"
            suffix += 1
        used_names.add(name)
        groups.append(_summarize_group(name, members))
    return groups


# ── Branch creation ────────────────────────────────────────────────


def _default_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Production git runner — calls real ``git`` via subprocess."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def create_finalize_branch(
    group: IterationGroup,
    *,
    repo_root: Path,
    base_ref: str = "main",
    git: Optional[GitCallable] = None,
) -> str:
    """Create a finalize branch and cherry-pick the group's commits onto it.

    The branch name is ``experiment-finalize/<group.name>``. On a
    cherry-pick conflict we abort the cherry-pick, rename the branch
    to ``experiment-finalize/CONFLICT-<group.name>`` so the operator
    sees it in ``/experiment_finalize_status``, and return the
    conflict-prefixed name. Other failures (missing base ref, branch
    already exists) raise ``RuntimeError`` so the caller can decide
    whether to skip or abort the run.
    """
    git_run = git if git is not None else _default_git
    branch = f"{BRANCH_PREFIX}{group.name}"

    # Create the branch at base_ref. ``git branch <name> <base>`` fails
    # cleanly if <name> already exists, which matches our intent — we
    # never want to silently overwrite an operator's review branch.
    branch_create = git_run(["branch", branch, base_ref], repo_root)
    if branch_create.returncode != 0:
        raise RuntimeError(
            f"git branch {branch} {base_ref} failed: {branch_create.stderr.strip()}"
        )

    # Switch to the new branch for cherry-picks.
    checkout = git_run(["checkout", branch], repo_root)
    if checkout.returncode != 0:
        raise RuntimeError(
            f"git checkout {branch} failed: {checkout.stderr.strip()}"
        )

    for member in group.members:
        if not member.commit_sha:
            log.warning(
                "iter %s has no commit_sha; skipping cherry-pick onto %s",
                member.iter_id, branch,
            )
            continue
        pick = git_run(["cherry-pick", member.commit_sha], repo_root)
        if pick.returncode != 0:
            # Abort the half-applied cherry-pick before renaming the
            # branch. Best-effort: if the abort itself fails, we still
            # want to surface the conflict to the operator.
            git_run(["cherry-pick", "--abort"], repo_root)
            conflict_name = f"{CONFLICT_PREFIX}{group.name}"
            rename = git_run(["branch", "-m", branch, conflict_name], repo_root)
            if rename.returncode != 0:
                log.warning(
                    "could not rename %s to %s after conflict: %s",
                    branch, conflict_name, rename.stderr.strip(),
                )
            log.warning(
                "cherry-pick conflict on %s for iter %s; left branch as %s",
                member.commit_sha, member.iter_id, conflict_name,
            )
            return conflict_name

    return branch


# ── Report writer ──────────────────────────────────────────────────


def _format_report(report: FinalizeReport) -> str:
    """Build the markdown text body for a ``FinalizeReport``."""
    lines: list[str] = []
    lines.append("# Experiment finalize report")
    lines.append("")
    lines.append(f"- Window start: `{report.window_start_iso}`")
    lines.append(f"- Window end:   `{report.window_end_iso}`")
    lines.append(f"- Grouping mode: `{report.grouping_mode}`")
    lines.append(f"- Iterations grouped: {report.total_iterations}")
    lines.append(f"- Groups: {len(report.groups)}")
    lines.append(f"- Branches created: {len(report.branches_created)}")
    lines.append(f"- Duration: {report.duration_seconds:.2f}s")
    lines.append("")
    if not report.groups:
        lines.append("_No keep iterations in window._")
        lines.append("")
        return "\n".join(lines)
    for group in report.groups:
        lines.append(f"## `{BRANCH_PREFIX}{group.name}`")
        lines.append("")
        lines.append(f"- Members: {len(group.members)}")
        lines.append(f"- Total fitness Δ: {group.total_fitness_delta:+.4f}")
        lines.append(f"- Total cost: ${group.total_cost_usd:.4f}")
        lines.append(f"- Files touched ({len(group.union_files_touched)}):")
        for f in group.union_files_touched[:20]:
            lines.append(f"  - `{f}`")
        if len(group.union_files_touched) > 20:
            lines.append(f"  - …and {len(group.union_files_touched) - 20} more")
        lines.append("")
        lines.append("| iter_id | sha | Δ fitness | cost | subject |")
        lines.append("|---|---|---|---|---|")
        for m in group.members:
            sha_short = (m.commit_sha or "")[:8] or "_(none)_"
            subject = m.commit_subject or "_(no subject)_"
            # Pipe-escape so the markdown table doesn't break.
            subject = subject.replace("|", "\\|")
            lines.append(
                f"| {m.iter_id} | `{sha_short}` | {m.fitness_delta:+.4f} "
                f"| ${m.cost_usd:.4f} | {subject} |"
            )
        lines.append("")
    return "\n".join(lines)


def write_finalize_report(report: FinalizeReport, *, output_path: Path) -> None:
    """Atomic markdown report writer.

    Same write-and-rename pattern as ``experiment_loop.append_experiments_md``
    so a mid-write crash never leaves a partial report.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    body = _format_report(report)
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp.write_text(body)
    tmp.replace(output_path)


# ── CLI ────────────────────────────────────────────────────────────


def _parse_window(value: str | None) -> Optional[datetime]:
    """Parse a ``YYYY-MM-DD`` or full ISO-8601 string into a UTC datetime."""
    if not value:
        return None
    dt = _parse_iso(value)
    if dt is not None:
        return dt
    # Fall back to plain date.
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise SystemExit(f"finalize_experiments: cannot parse date '{value}'")


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Group experiment-loop keep iterations into reviewable branches."
    )
    parser.add_argument(
        "--jsonl-path",
        type=Path,
        default=Path("data/experiments.jsonl"),
        help="Path to experiments.jsonl (default: data/experiments.jsonl).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repo root (default: cwd).",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=None,
        help="Where to write the markdown report (default: data/experiments-finalize-<ts>.md).",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Window start (YYYY-MM-DD or ISO-8601). Default: 30 days ago.",
    )
    parser.add_argument(
        "--until",
        type=str,
        default=None,
        help="Window end (YYYY-MM-DD or ISO-8601). Default: now.",
    )
    parser.add_argument(
        "--mode",
        choices=("files", "topic"),
        default="files",
        help="Grouping mode (default: files).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Jaccard similarity threshold (default: 0.5).",
    )
    parser.add_argument(
        "--keyword-top-n",
        type=int,
        default=3,
        help="Topic-mode keyword count (default: 3).",
    )
    parser.add_argument(
        "--base-ref",
        default="main",
        help="Branch / ref to fork finalize branches from (default: main).",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=30,
        help="Default window size in days when --since not provided (default: 30).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute groups + write the report but skip branch creation.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point. Returns process exit code."""
    parser = _build_argparser()
    ns = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    started = time.monotonic()
    until = _parse_window(ns.until) or datetime.now(tz=timezone.utc)
    since = _parse_window(ns.since) or (until - timedelta(days=ns.window_days))

    iterations = load_keep_iterations(
        jsonl_path=ns.jsonl_path, since=since, until=until
    )

    if ns.mode == "files":
        groups = group_by_files(iterations, similarity_threshold=ns.threshold)
    else:
        groups = group_by_topic(
            iterations,
            keyword_top_n=ns.keyword_top_n,
            similarity_threshold=ns.threshold,
        )

    branches: list[str] = []
    if not ns.dry_run:
        for group in groups:
            try:
                branch_name = create_finalize_branch(
                    group, repo_root=ns.repo_root, base_ref=ns.base_ref
                )
                branches.append(branch_name)
            except RuntimeError as exc:
                log.warning("group %s: skipping branch (%s)", group.name, exc)

    duration = time.monotonic() - started
    report = FinalizeReport(
        window_start_iso=since.isoformat(timespec="seconds"),
        window_end_iso=until.isoformat(timespec="seconds"),
        grouping_mode=ns.mode,
        total_iterations=len(iterations),
        groups=tuple(groups),
        branches_created=tuple(branches),
        duration_seconds=duration,
    )

    if ns.report_path is not None:
        report_path = ns.report_path
    else:
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S")
        # Default sits under whichever data dir the JSONL lives in.
        data_dir = ns.jsonl_path.parent if ns.jsonl_path.parent.name else Path("data")
        report_path = data_dir / f"experiments-finalize-{ts}.md"

    try:
        write_finalize_report(report, output_path=report_path)
    except OSError as exc:
        log.error("failed to write report at %s: %s", report_path, exc)
        return 1

    log.info(
        "finalize complete: %d iterations → %d groups → %d branches (mode=%s)",
        len(iterations), len(groups), len(branches), ns.mode,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
