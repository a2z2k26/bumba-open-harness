"""Build the sprint dependency graph from open GitHub issues (D7.6).

Reads every open issue's body, extracts dependency-declaration patterns,
and writes:

  - docs/sprint-dependency-graph.json — machine-readable graph
  - docs/sprint-dependency-graph.md   — human-readable summary with
                                         chains highlighted

Surveyed declaration patterns (across the 2026-05-08 open-issue corpus):

  **Prerequisites:** ...        bold-prefix on its own line, optionally
                                with the colon inside or outside the **
  **Unblocks:** ...             same shape, dual to Prerequisites
  **Parent plan:** ...          link to docs/plans/... master plan
  Requires D<N>.<N>             inline reference to a sprint slug
  Requires #<NNNN>              inline issue-number reference
  Closes #<NNNN>                PR-style closing keyword (some issue
                                bodies preview this)

Sprint slugs (D8.4, S10a, Z4-S00) are resolved to issue numbers by
matching the slug against open issue titles. Unresolved slugs land in
a `dangling_refs` bucket so the operator can backfill them.

Usage (run as a module from the agent/ directory):

    python -m scripts.build_sprint_dependency_graph                    # writes both
    python -m scripts.build_sprint_dependency_graph --json-only        # json only
    python -m scripts.build_sprint_dependency_graph --md-only          # md only
    python -m scripts.build_sprint_dependency_graph --output-dir /tmp  # alt dest

Stdlib only — fetches issues via `gh issue list ... --json ...`.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs"

# ---------------------------------------------------------------------------
# Pattern definitions — observed declarations in the issue corpus
# ---------------------------------------------------------------------------

# Bold-prefix patterns. The colon can be inside (**Prerequisites:**) or
# outside (**Prerequisites**:) the asterisks; we accept both.
PATTERN_PREREQ = re.compile(r"\*\*Prerequisites?:?\*\*:?\s*(.+)", re.IGNORECASE)
PATTERN_UNBLOCKS = re.compile(r"\*\*Unblocks?:?\*\*:?\s*(.+)", re.IGNORECASE)
PATTERN_PARENT_PLAN = re.compile(r"\*\*Parent plan:?\*\*:?\s*(.+)", re.IGNORECASE)
PATTERN_DEPENDS_ON = re.compile(r"\*\*Depends on:?\*\*:?\s*(.+)", re.IGNORECASE)

# Inline reference patterns
PATTERN_REQUIRES_SLUG = re.compile(r"\bRequires\s+([A-Z]\d+\.\d+(?:\.\d+)?[a-z]?)", re.IGNORECASE)
PATTERN_REQUIRES_ISSUE = re.compile(r"\bRequires\s+#(\d+)")
PATTERN_BLOCKS_ISSUE = re.compile(r"\bblocks?\s+#(\d+)", re.IGNORECASE)
PATTERN_CLOSES_ISSUE = re.compile(r"\bcloses\s+#(\d+)", re.IGNORECASE)

# Sprint-slug pattern used to extract individual references from
# Prerequisites/Unblocks lines. Matches D6.9, D6-bis.5, S10a, Z4-S00,
# 01.05a, etc.
PATTERN_SPRINT_SLUG = re.compile(
    r"\b(?:D\d+(?:[\.-]bis)?\.\d+(?:\.\d+)?[a-z]?"
    r"|Z\d-S\d+[a-z]?"
    r"|S\d+[a-z]?"
    r"|\d{2}\.\d{2}[a-z]?)\b"
)


@dataclass(frozen=True)
class Issue:
    """One open GitHub issue, normalised."""
    number: int
    title: str
    state: str
    labels: tuple[str, ...]
    body: str

    @property
    def slug(self) -> str | None:
        """Extract the sprint slug from the title (e.g. 'D7.6', 'S10a')."""
        m = PATTERN_SPRINT_SLUG.search(self.title)
        return m.group(0) if m else None


@dataclass
class IssueDeps:
    """Dependencies extracted from one issue body."""
    issue_number: int
    prereq_issues: list[int] = field(default_factory=list)
    prereq_slugs: list[str] = field(default_factory=list)
    unblocks_issues: list[int] = field(default_factory=list)
    unblocks_slugs: list[str] = field(default_factory=list)
    parent_plan: str | None = None
    raw_lines: list[str] = field(default_factory=list)


@dataclass
class GraphReport:
    """Final graph + coverage report."""
    issues: dict[int, Issue]
    deps: dict[int, IssueDeps]
    dangling_slugs: dict[int, list[str]]   # issue → unresolved slug refs
    no_deps_declared: list[int]            # issues with no deps at all


# ---------------------------------------------------------------------------
# Issue fetching
# ---------------------------------------------------------------------------

def fetch_open_issues(limit: int = 500) -> list[Issue]:
    """Fetch open issues via `gh issue list`. Returns normalised Issue objects."""
    result = subprocess.run(
        [
            "gh", "issue", "list",
            "--state", "open",
            "--limit", str(limit),
            "--json", "number,title,state,labels,body",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    raw = json.loads(result.stdout)
    return [
        Issue(
            number=item["number"],
            title=item.get("title", ""),
            state=item.get("state", "OPEN"),
            labels=tuple(label["name"] for label in (item.get("labels") or [])),
            body=item.get("body", "") or "",
        )
        for item in raw
    ]


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------

def _extract_issue_numbers(text: str) -> list[int]:
    """Pull #NNNN references out of a free-text snippet."""
    return [int(m) for m in re.findall(r"#(\d+)", text)]


def _extract_slugs(text: str) -> list[str]:
    """Pull sprint slugs (D7.6, S10a, ...) out of a free-text snippet."""
    return PATTERN_SPRINT_SLUG.findall(text)


def parse_deps(issue: Issue) -> IssueDeps:
    """Extract declared dependencies from the issue body.

    Body lines are scanned for the bold-prefix patterns. When a match is
    found, the rest of the line is parsed for both #NNNN issue numbers
    and sprint slugs (D7.6, S10a, ...). Inline `Requires DN.N` /
    `Requires #NNN` patterns are scanned across the whole body.
    """
    deps = IssueDeps(issue_number=issue.number)

    for line in issue.body.split("\n"):
        m = PATTERN_PREREQ.search(line)
        if m:
            deps.raw_lines.append(line.strip())
            rest = m.group(1)
            deps.prereq_issues.extend(_extract_issue_numbers(rest))
            deps.prereq_slugs.extend(_extract_slugs(rest))
            continue

        m = PATTERN_UNBLOCKS.search(line)
        if m:
            deps.raw_lines.append(line.strip())
            rest = m.group(1)
            deps.unblocks_issues.extend(_extract_issue_numbers(rest))
            deps.unblocks_slugs.extend(_extract_slugs(rest))
            continue

        m = PATTERN_PARENT_PLAN.search(line)
        if m:
            deps.raw_lines.append(line.strip())
            deps.parent_plan = m.group(1).strip()
            continue

        m = PATTERN_DEPENDS_ON.search(line)
        if m:
            deps.raw_lines.append(line.strip())
            rest = m.group(1)
            deps.prereq_issues.extend(_extract_issue_numbers(rest))
            deps.prereq_slugs.extend(_extract_slugs(rest))

    # Inline patterns scan the whole body
    for m in PATTERN_REQUIRES_SLUG.finditer(issue.body):
        deps.prereq_slugs.append(m.group(1))
    for m in PATTERN_REQUIRES_ISSUE.finditer(issue.body):
        deps.prereq_issues.append(int(m.group(1)))
    for m in PATTERN_BLOCKS_ISSUE.finditer(issue.body):
        deps.unblocks_issues.append(int(m.group(1)))

    # Dedupe while preserving order
    deps.prereq_issues = list(dict.fromkeys(deps.prereq_issues))
    deps.prereq_slugs = list(dict.fromkeys(deps.prereq_slugs))
    deps.unblocks_issues = list(dict.fromkeys(deps.unblocks_issues))
    deps.unblocks_slugs = list(dict.fromkeys(deps.unblocks_slugs))
    return deps


def resolve_slugs_to_issues(
    deps_by_issue: dict[int, IssueDeps],
    issues_by_slug: dict[str, int],
) -> dict[int, list[str]]:
    """Resolve slug references to issue numbers in-place; return dangling refs.

    For each IssueDeps, for every slug that maps to a known issue number,
    add the resolved number to ``prereq_issues`` / ``unblocks_issues``.
    Slugs that don't resolve land in the returned ``dangling`` map.
    """
    dangling: dict[int, list[str]] = defaultdict(list)
    for issue_num, deps in deps_by_issue.items():
        for slug in deps.prereq_slugs:
            resolved = issues_by_slug.get(slug.upper())
            if resolved is not None:
                if resolved not in deps.prereq_issues:
                    deps.prereq_issues.append(resolved)
            else:
                dangling[issue_num].append(slug)
        for slug in deps.unblocks_slugs:
            resolved = issues_by_slug.get(slug.upper())
            if resolved is not None:
                if resolved not in deps.unblocks_issues:
                    deps.unblocks_issues.append(resolved)
            else:
                dangling[issue_num].append(slug)
    return dict(dangling)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph(issues: Iterable[Issue]) -> GraphReport:
    """Top-level: parse every issue, resolve slugs, identify coverage."""
    issues_list = list(issues)
    issues_by_num = {i.number: i for i in issues_list}

    # Build slug → issue-number map. Multiple issues may share a slug
    # (rare); keep the lowest-numbered (oldest) assumed canonical.
    # Index BOTH the full slug ("Z3-S10a") and the bare tail ("S10a")
    # — issue titles use the prefixed form but bodies often reference
    # the bare tail.
    issues_by_slug: dict[str, int] = {}
    for i in issues_list:
        s = i.slug
        if not s:
            continue
        s_upper = s.upper()
        if s_upper not in issues_by_slug:
            issues_by_slug[s_upper] = i.number
        # Also index the tail-only form (Z3-S10a → S10a)
        if "-" in s:
            tail = s.rsplit("-", 1)[-1].upper()
            if tail not in issues_by_slug:
                issues_by_slug[tail] = i.number

    deps_by_issue = {i.number: parse_deps(i) for i in issues_list}
    dangling = resolve_slugs_to_issues(deps_by_issue, issues_by_slug)

    no_deps = [
        n
        for n, d in deps_by_issue.items()
        if not d.prereq_issues and not d.unblocks_issues and not d.parent_plan
    ]

    return GraphReport(
        issues=issues_by_num,
        deps=deps_by_issue,
        dangling_slugs=dangling,
        no_deps_declared=no_deps,
    )


# ---------------------------------------------------------------------------
# Output renderers
# ---------------------------------------------------------------------------

def render_json(report: GraphReport) -> str:
    """Machine-readable graph: nodes + edges + coverage buckets."""
    nodes = []
    for n, issue in sorted(report.issues.items()):
        nodes.append({
            "number": n,
            "title": issue.title,
            "labels": list(issue.labels),
            "slug": issue.slug,
        })
    edges = []
    for n, deps in sorted(report.deps.items()):
        for prereq in deps.prereq_issues:
            if prereq in report.issues:
                edges.append({"from": prereq, "to": n, "kind": "prereq"})
        for unblocked in deps.unblocks_issues:
            if unblocked in report.issues:
                edges.append({"from": n, "to": unblocked, "kind": "unblocks"})
    payload = {
        "nodes": nodes,
        "edges": edges,
        "coverage": {
            "total_open_issues": len(report.issues),
            "with_declared_deps": len(report.issues) - len(report.no_deps_declared),
            "no_deps_declared": sorted(report.no_deps_declared),
            "dangling_slug_refs": {
                str(k): v for k, v in sorted(report.dangling_slugs.items())
            },
        },
    }
    return json.dumps(payload, indent=2, sort_keys=False)


def render_markdown(report: GraphReport) -> str:
    """Human-readable summary with chains highlighted."""
    lines: list[str] = []
    lines.append("# Sprint Dependency Graph")
    lines.append("")
    lines.append(
        "Auto-generated by `scripts/build_sprint_dependency_graph.py`. "
        "Reads every open GitHub issue body, extracts "
        "`**Prerequisites:**` / `**Unblocks:**` / `**Parent plan:**` / "
        "`Requires DN.N` / `Requires #NNN` patterns, and renders the "
        "result. Sprint slugs (D7.6, S10a, ...) resolved to issue "
        "numbers via title scan."
    )
    lines.append("")
    lines.append("## Coverage")
    total = len(report.issues)
    with_deps = total - len(report.no_deps_declared)
    pct = (with_deps / total * 100) if total else 0
    lines.append(f"- **Total open issues:** {total}")
    lines.append(f"- **With declared deps:** {with_deps} ({pct:.0f}%)")
    lines.append(f"- **No deps declared:** {len(report.no_deps_declared)}")
    lines.append(f"- **Dangling slug refs:** {len(report.dangling_slugs)}")
    lines.append("")

    # Chains: walk the prereq edges to find connected components
    chains = _identify_chains(report)
    lines.append(f"## Chains ({len(chains)})")
    lines.append("")
    if chains:
        for i, chain in enumerate(chains, 1):
            chain_titles = []
            for issue_num in chain:
                issue = report.issues[issue_num]
                slug = issue.slug or f"#{issue_num}"
                chain_titles.append(f"#{issue_num} ({slug})")
            lines.append(f"### Chain {i} — {len(chain)} sprints")
            lines.append("")
            lines.append("  → ".join(chain_titles))
            lines.append("")
            for issue_num in chain:
                issue = report.issues[issue_num]
                lines.append(f"- **#{issue_num}** {issue.title}")
            lines.append("")
    else:
        lines.append("(no multi-sprint chains detected)")
        lines.append("")

    # Dangling refs bucket
    if report.dangling_slugs:
        lines.append("## Dangling slug references")
        lines.append("")
        lines.append(
            "These issues reference sprint slugs that don't match any "
            "open-issue title. Either the referenced sprint is closed, "
            "or the slug is a typo, or the referenced sprint hasn't "
            "been filed yet."
        )
        lines.append("")
        for issue_num, slugs in sorted(report.dangling_slugs.items()):
            issue = report.issues[issue_num]
            lines.append(f"- **#{issue_num}** ({issue.title}) → {', '.join(slugs)}")
        lines.append("")

    # No-deps bucket (backfill candidates)
    if report.no_deps_declared:
        lines.append("## Issues with no declared dependencies")
        lines.append("")
        lines.append(
            f"{len(report.no_deps_declared)} issues lack declared deps. "
            "These are presumed independent unless backfilled. Backfill "
            "by adding `**Prerequisites:**` and/or `**Unblocks:**` lines "
            "to the issue body."
        )
        lines.append("")
        # Limit output to first 30 to keep the doc readable
        for issue_num in sorted(report.no_deps_declared)[:30]:
            issue = report.issues[issue_num]
            lines.append(f"- **#{issue_num}** {issue.title}")
        if len(report.no_deps_declared) > 30:
            lines.append(f"- _… and {len(report.no_deps_declared) - 30} more_")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "Generated from open issues at `gh issue list --state open --limit 500`. "
        "To regenerate: `cd agent && python -m scripts.build_sprint_dependency_graph`."
    )
    return "\n".join(lines) + "\n"


def _identify_chains(report: GraphReport) -> list[list[int]]:
    """Find connected components in the prereq graph; return as ordered chains."""
    # Build undirected adjacency (chains = connected components)
    adj: dict[int, set[int]] = defaultdict(set)
    for n, deps in report.deps.items():
        for p in deps.prereq_issues:
            if p in report.issues:
                adj[n].add(p)
                adj[p].add(n)
        for u in deps.unblocks_issues:
            if u in report.issues:
                adj[n].add(u)
                adj[u].add(n)

    visited: set[int] = set()
    chains: list[list[int]] = []
    for start in sorted(adj.keys()):
        if start in visited:
            continue
        component: set[int] = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            component.add(cur)
            stack.extend(adj[cur] - visited)
        if len(component) >= 2:
            # Order by topological priority: issues with fewer prereqs first
            ordered = sorted(
                component,
                key=lambda x: (
                    len(report.deps[x].prereq_issues) if x in report.deps else 99,
                    x,
                ),
            )
            chains.append(ordered)
    chains.sort(key=lambda c: -len(c))
    return chains


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for output files (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Max open issues to fetch (default: 500)",
    )
    parser.add_argument("--json-only", action="store_true", help="Skip markdown output")
    parser.add_argument("--md-only", action="store_true", help="Skip JSON output")
    parser.add_argument(
        "--issues-from-file",
        type=Path,
        help="Read issues from JSON file instead of running `gh` (for tests)",
    )
    args = parser.parse_args(argv)

    if args.issues_from_file:
        with args.issues_from_file.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        issues = [
            Issue(
                number=item["number"],
                title=item.get("title", ""),
                state=item.get("state", "OPEN"),
                labels=tuple(label["name"] for label in (item.get("labels") or [])),
                body=item.get("body", "") or "",
            )
            for item in raw
        ]
    else:
        try:
            issues = fetch_open_issues(limit=args.limit)
        except subprocess.CalledProcessError as exc:
            print(f"ERROR: gh issue list failed: {exc.stderr}", file=sys.stderr)
            return 2

    report = build_graph(issues)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if not args.md_only:
        json_path = args.output_dir / "sprint-dependency-graph.json"
        json_path.write_text(render_json(report), encoding="utf-8")
        print(f"Wrote {json_path}")

    if not args.json_only:
        md_path = args.output_dir / "sprint-dependency-graph.md"
        md_path.write_text(render_markdown(report), encoding="utf-8")
        print(f"Wrote {md_path}")

    print(
        f"Coverage: {len(report.issues)} open issues, "
        f"{len(report.issues) - len(report.no_deps_declared)} with deps, "
        f"{len(report.no_deps_declared)} need backfill"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
