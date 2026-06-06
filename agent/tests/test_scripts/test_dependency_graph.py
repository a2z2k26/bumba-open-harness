"""Tests for scripts/build_sprint_dependency_graph.py (D7.6)."""
from __future__ import annotations

import json
from pathlib import Path


from scripts.build_sprint_dependency_graph import (
    Issue,
    build_graph,
    main as build_main,
    parse_deps,
    render_json,
    render_markdown,
)


# ---------------------------------------------------------------------------
# parse_deps — pattern coverage
# ---------------------------------------------------------------------------

def _issue(num: int, title: str, body: str = "") -> Issue:
    return Issue(number=num, title=title, state="OPEN", labels=(), body=body)


def test_parse_deps_extracts_prereq_issue_numbers() -> None:
    """**Prerequisites:** with #NNN refs → prereq_issues populated."""
    issue = _issue(
        100,
        "[D-test] sprint",
        body="**Prerequisites:** #50, #60 must be merged",
    )
    deps = parse_deps(issue)
    assert deps.prereq_issues == [50, 60]


def test_parse_deps_extracts_prereq_slugs() -> None:
    """**Prerequisites:** with sprint slugs → prereq_slugs populated."""
    issue = _issue(
        100,
        "[Z3-S10b]",
        body="**Prerequisites:** S10a (baseline exists, M1 gate met)",
    )
    deps = parse_deps(issue)
    assert "S10a" in deps.prereq_slugs


def test_parse_deps_extracts_unblocks() -> None:
    """**Unblocks:** populates the unblocks lists."""
    issue = _issue(
        100,
        "[Z3-S10a]",
        body="**Unblocks:** S10b\n",
    )
    deps = parse_deps(issue)
    assert "S10b" in deps.unblocks_slugs


def test_parse_deps_handles_colon_inside_or_outside_asterisks() -> None:
    """Both **Prerequisites:** and **Prerequisites**: forms are accepted."""
    issue1 = _issue(1, "x", body="**Prerequisites:** #5")
    issue2 = _issue(2, "y", body="**Prerequisites**: #5")
    assert parse_deps(issue1).prereq_issues == [5]
    assert parse_deps(issue2).prereq_issues == [5]


def test_parse_deps_extracts_inline_requires_slug() -> None:
    """`Requires DN.N` inline reference → prereq_slugs."""
    issue = _issue(
        1424,
        "Sprint D7.12: Perpetual-proactive work loop",
        body="## Dependencies\n- Requires D7.6 (dependency graph)\n- Requires D7.9",
    )
    deps = parse_deps(issue)
    assert "D7.6" in deps.prereq_slugs
    assert "D7.9" in deps.prereq_slugs


def test_parse_deps_extracts_inline_requires_issue() -> None:
    """`Requires #NNNN` → prereq_issues."""
    issue = _issue(
        1,
        "Sprint X",
        body="**Dependencies:**\n- Requires #100\n- Requires #200",
    )
    deps = parse_deps(issue)
    assert 100 in deps.prereq_issues
    assert 200 in deps.prereq_issues


def test_parse_deps_extracts_parent_plan() -> None:
    """**Parent plan:** captured as a string."""
    issue = _issue(
        1,
        "x",
        body="**Parent plan:** docs/plans/2026-04-25-reference-audit/plan-01-rtk.md",
    )
    deps = parse_deps(issue)
    assert deps.parent_plan is not None
    assert "plan-01-rtk" in deps.parent_plan


def test_parse_deps_no_match_when_body_empty() -> None:
    """Empty body → empty deps."""
    deps = parse_deps(_issue(1, "x", body=""))
    assert deps.prereq_issues == []
    assert deps.unblocks_issues == []
    assert deps.parent_plan is None


def test_parse_deps_dedupes_repeated_references() -> None:
    """Duplicate refs collapse to single entries."""
    issue = _issue(
        1,
        "x",
        body="**Prerequisites:** #5, #5, #5\nRequires #5",
    )
    deps = parse_deps(issue)
    assert deps.prereq_issues.count(5) == 1


# ---------------------------------------------------------------------------
# build_graph — slug resolution + coverage
# ---------------------------------------------------------------------------

def test_build_graph_resolves_slugs_to_issue_numbers() -> None:
    """Slug refs resolve to issue numbers via title-scan."""
    issues = [
        _issue(573, "[Z3-S10a] Flag flip prep — 24h off-soak + baseline"),
        _issue(574, "[Z3-S10b] Flag flip execute", body="**Prerequisites:** S10a"),
    ]
    report = build_graph(issues)

    deps_574 = report.deps[574]
    assert 573 in deps_574.prereq_issues  # slug S10a resolved to #573


def test_build_graph_dangles_unresolved_slugs() -> None:
    """Slug refs that don't match any open-issue title land in dangling_slugs."""
    issues = [
        _issue(100, "[D7.6] dep graph", body="**Prerequisites:** D99.99"),
    ]
    report = build_graph(issues)

    assert 100 in report.dangling_slugs
    assert "D99.99" in report.dangling_slugs[100]


def test_build_graph_marks_no_deps_declared() -> None:
    """Issues with no Prerequisites/Unblocks/Parent plan lines are flagged."""
    issues = [
        _issue(1, "naked sprint", body="just some content, no deps declared"),
        _issue(2, "another", body="**Prerequisites:** #1"),
    ]
    report = build_graph(issues)

    assert 1 in report.no_deps_declared
    assert 2 not in report.no_deps_declared


def test_build_graph_recovers_chain_from_runbook_fixtures() -> None:
    """Dogfood: tonight's Z3 chain (S10a → S10b → S10c) recovers correctly."""
    issues = [
        _issue(573, "[Z3-S10a] Flag flip prep"),
        _issue(
            574, "[Z3-S10b] Flag flip execute",
            body="**Prerequisites:** S10a\n**Unblocks:** S10c",
        ),
        _issue(
            575, "[Z3-S10c] Flag flip results",
            body="**Prerequisites:** S10b",
        ),
    ]
    report = build_graph(issues)

    # 574 has 573 as prereq, 575 as unblocks
    assert 573 in report.deps[574].prereq_issues
    assert 575 in report.deps[574].unblocks_issues
    # 575 has 574 as prereq
    assert 574 in report.deps[575].prereq_issues


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def test_render_json_includes_nodes_edges_coverage() -> None:
    """JSON output has the three top-level sections."""
    issues = [
        _issue(573, "[Z3-S10a]"),
        _issue(574, "[Z3-S10b]", body="**Prerequisites:** S10a"),
    ]
    report = build_graph(issues)
    payload = json.loads(render_json(report))

    assert "nodes" in payload
    assert "edges" in payload
    assert "coverage" in payload
    # Edge from 573 → 574 with kind=prereq
    assert {"from": 573, "to": 574, "kind": "prereq"} in payload["edges"]


def test_render_markdown_includes_chain_section() -> None:
    """Markdown render lists the chain when one exists."""
    issues = [
        _issue(573, "[Z3-S10a]"),
        _issue(574, "[Z3-S10b]", body="**Prerequisites:** S10a"),
    ]
    report = build_graph(issues)
    md = render_markdown(report)

    assert "## Chains" in md
    assert "#573" in md and "#574" in md


def test_render_markdown_lists_no_deps_bucket() -> None:
    """Markdown surfaces issues missing the convention."""
    issues = [_issue(99, "naked sprint", body="no deps here")]
    report = build_graph(issues)
    md = render_markdown(report)

    assert "no declared dependencies" in md.lower()
    assert "#99" in md


# ---------------------------------------------------------------------------
# main() entry — file-based execution path
# ---------------------------------------------------------------------------

def test_main_writes_both_files_from_fixture(tmp_path: Path) -> None:
    """Running main() with --issues-from-file produces both outputs."""
    fixture = tmp_path / "issues.json"
    fixture.write_text(json.dumps([
        {
            "number": 573,
            "title": "[Z3-S10a]",
            "state": "OPEN",
            "labels": [{"name": "zone-3"}],
            "body": "",
        },
        {
            "number": 574,
            "title": "[Z3-S10b]",
            "state": "OPEN",
            "labels": [{"name": "zone-3"}],
            "body": "**Prerequisites:** S10a",
        },
    ]))

    rc = build_main([
        "--issues-from-file", str(fixture),
        "--output-dir", str(tmp_path),
    ])
    assert rc == 0
    assert (tmp_path / "sprint-dependency-graph.json").exists()
    assert (tmp_path / "sprint-dependency-graph.md").exists()

    # Sanity-check JSON
    data = json.loads((tmp_path / "sprint-dependency-graph.json").read_text())
    assert data["coverage"]["total_open_issues"] == 2
