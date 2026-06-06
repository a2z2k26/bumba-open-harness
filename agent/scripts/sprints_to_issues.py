"""Sprint-to-GitHub-issue factory for the phase-based sprint plan (P7.2).

Parses a phase-based sprint plan markdown file (e.g.
`/home/operator/Desktop/bumba-harness-audit-plan/02-phase-based-sprint-plan.md`)
and emits, for every sprint section it finds, either:

  - a ready-to-pipe `gh issue create` command line, or
  - a JSON payload (one object per sprint) that the operator can pipe to
    `gh api repos/{owner}/{repo}/issues` if they prefer the REST surface.

The default mode is `--dry-run`, which prints the issue bodies (and the
commands or JSON that would create them) to stdout WITHOUT calling out
to `gh` or the network. The acceptance criterion for sprint P7.2 is
satisfied by the dry-run mode alone — actual issue creation is
operator-driven and stays a separate, explicit step.

Sprint front-matter shape this parser expects:

    ### Sprint P7.2 — Issue factory for sprint execution

    ```yaml
    id: P7.2
    title: Generate GitHub issues from sprint front matter
    zone: "Developer Experience"
    complexity: 5
    risk: low
    depends_on: ["P0.4"]
    ```

    **Files:**
    - Create: `agent/scripts/sprints_to_issues.py`

    **Tasks:**
    - [ ] Parse sprint sections in this plan.

    **Acceptance:**
    - [ ] Dry run generates issue bodies for every sprint without network calls.

Stdlib only. No third-party dependencies.

Usage:

    python3 agent/scripts/sprints_to_issues.py \\
        --plan /home/operator/Desktop/bumba-harness-audit-plan/02-phase-based-sprint-plan.md \\
        --dry-run

    python3 agent/scripts/sprints_to_issues.py \\
        --plan <path-to-plan.md> --dry-run --format json

    python3 agent/scripts/sprints_to_issues.py \\
        --plan <path-to-plan.md> --dry-run --only P7.2,P7.3

    python3 agent/scripts/sprints_to_issues.py \\
        --plan <path-to-plan.md> --dry-run --label type:governance --label phase:7
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

# ---------------------------------------------------------------------------
# Parsing primitives
# ---------------------------------------------------------------------------

# A sprint section header. Matches lines like:
#   "### Sprint P7.2 — Issue factory for sprint execution"
#   "### Sprint P0.1 — Remove stale External Product residue and restore pytest collection"
# The em-dash is the separator the plan uses; ASCII "-" is also accepted.
_SPRINT_HEADER = re.compile(
    r"^###\s+Sprint\s+(?P<id>[A-Z]\d+\.\d+[a-z]?)\s+[—-]\s+(?P<title>.+?)\s*$",
    re.MULTILINE,
)

# A phase header. Matches lines like:
#   "## Phase 0 — Truth Baseline"
_PHASE_HEADER = re.compile(
    r"^##\s+Phase\s+(?P<num>\d+[a-z]?)\s+[—-]\s+(?P<name>.+?)\s*$",
    re.MULTILINE,
)

# Inside the YAML fence: key/value pairs we care about.
_YAML_KV = re.compile(
    r"^(?P<key>id|title|zone|complexity|risk|depends_on)\s*:\s*(?P<val>.+?)\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class SprintFrontMatter:
    """Parsed YAML front-matter for a single sprint."""

    sprint_id: str
    title: str
    zone: str
    complexity: str
    risk: str
    depends_on: tuple[str, ...]


@dataclass(frozen=True)
class Sprint:
    """One parsed sprint section, with body preserved verbatim."""

    sprint_id: str
    header_title: str
    phase_num: str
    phase_name: str
    front_matter: SprintFrontMatter
    body: str  # everything between the section header and the next ### / ##

    @property
    def issue_title(self) -> str:
        """The GitHub issue title for this sprint."""
        # Mirror the convention already in use (see issue #1596):
        #   "Sprint P7.2: Issue factory for sprint execution"
        return f"Sprint {self.sprint_id}: {self.header_title}"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _strip_yaml_quotes(value: str) -> str:
    """Strip a single pair of surrounding single or double quotes."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def _parse_depends_on(raw: str) -> tuple[str, ...]:
    """Parse a YAML inline list like '["P0.4", "P1.1"]' or '[]'."""
    raw = raw.strip()
    if raw in ("[]", ""):
        return ()
    # Strip surrounding brackets if present, then split on commas.
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return tuple(_strip_yaml_quotes(p) for p in parts)


def _parse_front_matter(yaml_text: str) -> SprintFrontMatter | None:
    """Parse the YAML fence body into a SprintFrontMatter.

    Returns None if a required field is missing — the caller decides what
    to do (we skip incomplete sections rather than crash).
    """
    found: dict[str, str] = {}
    for match in _YAML_KV.finditer(yaml_text):
        key = match.group("key")
        value = _strip_yaml_quotes(match.group("val").strip())
        found[key] = value

    required = ("id", "title", "zone", "complexity", "risk", "depends_on")
    if not all(k in found for k in required):
        return None

    return SprintFrontMatter(
        sprint_id=found["id"],
        title=found["title"],
        zone=found["zone"],
        complexity=found["complexity"],
        risk=found["risk"],
        depends_on=_parse_depends_on(found["depends_on"]),
    )


def parse_plan(plan_text: str) -> list[Sprint]:
    """Parse a sprint plan markdown document into a list of Sprint records.

    The plan must follow the shape documented at the top of this module.
    Sections that lack a complete YAML front-matter are skipped silently;
    re-run with --verbose to see which ones.
    """
    # Build a lookup of (line_offset -> phase) so each sprint can be
    # attributed to the phase it lives under.
    phase_markers: list[tuple[int, str, str]] = []
    for match in _PHASE_HEADER.finditer(plan_text):
        phase_markers.append((match.start(), match.group("num"), match.group("name")))

    def _phase_at(offset: int) -> tuple[str, str]:
        current = ("0", "Uncategorized")
        for start, num, name in phase_markers:
            if start > offset:
                break
            current = (num, name)
        return current

    headers = list(_SPRINT_HEADER.finditer(plan_text))
    sprints: list[Sprint] = []

    for idx, match in enumerate(headers):
        section_start = match.end()
        section_end = (
            headers[idx + 1].start() if idx + 1 < len(headers) else len(plan_text)
        )
        # Stop at the next phase header if it comes before the next sprint.
        for phase_offset, _num, _name in phase_markers:
            if section_start < phase_offset < section_end:
                section_end = phase_offset
                break

        body = plan_text[section_start:section_end].strip()

        # Extract YAML fence body — first ```yaml ... ``` after the header.
        yaml_open = body.find("```yaml")
        if yaml_open == -1:
            continue
        yaml_close = body.find("```", yaml_open + len("```yaml"))
        if yaml_close == -1:
            continue
        yaml_text = body[yaml_open + len("```yaml") : yaml_close]

        fm = _parse_front_matter(yaml_text)
        if fm is None:
            continue

        phase_num, phase_name = _phase_at(match.start())
        sprints.append(
            Sprint(
                sprint_id=fm.sprint_id,
                header_title=match.group("title").strip(),
                phase_num=phase_num,
                phase_name=phase_name,
                front_matter=fm,
                body=body,
            )
        )

    return sprints


# ---------------------------------------------------------------------------
# Issue body assembly
# ---------------------------------------------------------------------------


def build_issue_body(sprint: Sprint, plan_path: Path) -> str:
    """Build the GitHub issue body for one sprint.

    Mirrors the body shape used by issue #1596 (this very sprint's tracking
    issue), so the rest of the harness's tooling sees consistent structure:

        ## Source
        Sprint <ID> from `<plan_path>` (<date stamp>).

        ### Sprint <ID> — <title>
        ```yaml
        ...
        ```
        **Files:** ...
        **Tasks:** ...
        **Acceptance:** ...
    """
    lines = [
        "## Source",
        "",
        f"Sprint {sprint.sprint_id} from `{plan_path}`.",
        "",
        f"### Sprint {sprint.sprint_id} — {sprint.header_title}",
        "",
        sprint.body,
        "",
    ]
    return "\n".join(lines)


def labels_for(sprint: Sprint, extra_labels: Sequence[str]) -> list[str]:
    """Derive labels for one sprint.

    Defaults:
      - `agent-task` (matches `.github/ISSUE_TEMPLATE/agent-task.md`)
      - `phase:<N>` from the phase header
      - `risk:<low|medium|high>` from the YAML
      - `sprint:<ID>` for grep-ability

    Any --label flags from the CLI are appended verbatim.
    Order-preserved, deduplicated.
    """
    derived = [
        "agent-task",
        f"phase:{sprint.phase_num}",
        f"risk:{sprint.front_matter.risk}",
        f"sprint:{sprint.sprint_id}",
    ]
    out: list[str] = []
    seen: set[str] = set()
    for label in [*derived, *extra_labels]:
        if label and label not in seen:
            out.append(label)
            seen.add(label)
    return out


# ---------------------------------------------------------------------------
# Output formats
# ---------------------------------------------------------------------------


def render_gh_command(sprint: Sprint, body: str, labels: Sequence[str]) -> str:
    """Render a single `gh issue create` shell command line.

    Uses shlex.quote on every interpolated value so the operator can pipe
    the output to `bash` safely.
    """
    parts: list[str] = [
        "gh",
        "issue",
        "create",
        "--title",
        shlex.quote(sprint.issue_title),
        "--body",
        shlex.quote(body),
    ]
    for label in labels:
        parts.extend(["--label", shlex.quote(label)])
    return " ".join(parts)


def render_json_payload(sprint: Sprint, body: str, labels: Sequence[str]) -> dict:
    """Render a single REST-friendly JSON payload."""
    return {
        "sprint_id": sprint.sprint_id,
        "phase": sprint.phase_num,
        "title": sprint.issue_title,
        "body": body,
        "labels": list(labels),
        "depends_on": list(sprint.front_matter.depends_on),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_only(only: str | None) -> set[str] | None:
    if not only:
        return None
    return {s.strip() for s in only.split(",") if s.strip()}


def _filter_sprints(
    sprints: Iterable[Sprint], only: set[str] | None
) -> list[Sprint]:
    if only is None:
        return list(sprints)
    return [s for s in sprints if s.sprint_id in only]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Parse a phase-based sprint plan and emit GitHub issue payloads "
            "(dry-run by default; no network calls)."
        )
    )
    parser.add_argument(
        "--plan",
        type=Path,
        required=True,
        help="Path to the sprint plan markdown file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print issue payloads / commands to stdout without invoking gh "
            "or the network. This is the default mode and the only mode "
            "currently implemented."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("gh", "json"),
        default="gh",
        help=(
            "Output format. 'gh' emits one `gh issue create` shell command "
            "per sprint (default). 'json' emits a JSON array."
        ),
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help=(
            "Comma-separated list of sprint IDs to emit (e.g. 'P7.2,P7.3'). "
            "Default: all sprints."
        ),
    )
    parser.add_argument(
        "--label",
        action="append",
        dest="labels",
        default=[],
        help=(
            "Extra label to attach to every emitted issue. Repeat the flag "
            "for multiple labels."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print parse stats and skipped sections to stderr.",
    )

    args = parser.parse_args(argv)

    if not args.plan.exists():
        print(f"error: plan file not found: {args.plan}", file=sys.stderr)
        return 2

    plan_text = args.plan.read_text(encoding="utf-8")
    all_sprints = parse_plan(plan_text)

    only = _parse_only(args.only)
    sprints = _filter_sprints(all_sprints, only)

    if args.verbose:
        print(
            f"parsed {len(all_sprints)} sprints from {args.plan}; "
            f"emitting {len(sprints)} after --only filter",
            file=sys.stderr,
        )
        if only is not None:
            missing = only - {s.sprint_id for s in all_sprints}
            for sid in sorted(missing):
                print(f"warning: --only id {sid} not found in plan", file=sys.stderr)

    if not sprints:
        print("error: no sprints matched", file=sys.stderr)
        return 1

    # --dry-run is the only currently-implemented mode. We accept it as a
    # flag for forward-compatibility but treat its absence as an error so
    # nobody accidentally assumes network mode is wired up.
    if not args.dry_run:
        print(
            "error: only --dry-run mode is implemented. Re-run with --dry-run.",
            file=sys.stderr,
        )
        return 2

    if args.format == "json":
        payloads = [
            render_json_payload(s, build_issue_body(s, args.plan), labels_for(s, args.labels))
            for s in sprints
        ]
        json.dump(payloads, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    # gh format: one command per sprint, separated by blank lines.
    for sprint in sprints:
        body = build_issue_body(sprint, args.plan)
        labels = labels_for(sprint, args.labels)
        print(render_gh_command(sprint, body, labels))
        print()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
