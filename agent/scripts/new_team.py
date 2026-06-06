"""bumba new-team <name> — scaffold a complete Z4 department in <5s.

Two modes:
  Interactive  python -m agent.scripts.new_team <name>
               Prompts for prefix, chief role/mission, and specialist roster.
  Config       python -m agent.scripts.new_team <name> --config team.yaml
               Reads a YAML spec; no stdin prompts.

Generated files (8-12 depending on roster size):
  agent/config/teams/<name>.yaml
  agent/config/expertise/updatable/<prefix>-chief.md
  agent/config/agents/zone4/<name>/<prefix>-chief.md
  agent/config/expertise/updatable/<prefix>-<specialist>.md  (one per worker)
  agent/config/agents/zone4/<name>/<prefix>-<specialist>.md  (one per worker)
  agent/data/scaffolding/<name>-team-checklist.md

Exit codes:
  0  scaffold succeeded
  1  validation failure (duplicate team, bad config, invalid input)
  2  unexpected I/O error
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import yaml

from scripts._scaffolding_templates import (
    TeamScaffoldPaths,
    chief_expertise_for,
    chief_prompt_for,
    expertise_for,
    team_yaml_for,
    worker_prompt_for,
    worker_yaml_block_for,
)


# Repo root: agent/scripts/ → agent/ → repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
TEAMS_DIR = REPO_ROOT / "agent" / "config" / "teams"

# Minimum and maximum workers allowed in a single scaffold call.
MIN_WORKERS = 1
MAX_WORKERS = 8


# ---------------------------------------------------------------------------
# Dataclass-lite: team spec coming from config or interactive prompts
# ---------------------------------------------------------------------------

class TeamSpec:
    """Collected parameters for a new team scaffold."""

    __slots__ = (
        "name", "prefix", "description",
        "chief_role", "chief_mission",
        "workers",  # list of {"name": ..., "role": ...}
    )

    def __init__(
        self,
        name: str,
        prefix: str,
        description: str,
        chief_role: str,
        chief_mission: str,
        workers: list[dict[str, str]],
    ) -> None:
        self.name = name
        self.prefix = prefix
        self.description = description
        self.chief_role = chief_role
        self.chief_mission = chief_mission
        self.workers = workers


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _verify_no_duplicate_team(name: str) -> None:
    """Abort with exit 1 if a team YAML already exists for this name."""
    target = TEAMS_DIR / f"{name}.yaml"
    if target.exists():
        existing = sorted(p.stem for p in TEAMS_DIR.glob("*.yaml"))
        sys.stderr.write(
            f"[bumba] ERROR: team {name!r} already exists.\n"
            f"        {target}\n"
            f"        Existing teams: {', '.join(existing)}\n"
            f"        To add specialists to an existing team, use `bumba new-specialist`.\n"
        )
        raise SystemExit(1)


def _validate_name(name: str, label: str = "name") -> str:
    """Validate and return a kebab-case identifier, or abort."""
    name = name.strip()
    if not name:
        sys.stderr.write(f"[bumba] ERROR: {label} must not be empty.\n")
        raise SystemExit(1)
    if not all(c.isalnum() or c == "-" for c in name):
        sys.stderr.write(
            f"[bumba] ERROR: {label} {name!r} must be kebab-case "
            f"(lowercase letters, digits, hyphens only).\n"
        )
        raise SystemExit(1)
    if name.startswith("-") or name.endswith("-"):
        sys.stderr.write(
            f"[bumba] ERROR: {label} {name!r} must not start or end with a hyphen.\n"
        )
        raise SystemExit(1)
    return name.lower()


def _validate_spec(spec: TeamSpec) -> None:
    """Run cross-field validation on a TeamSpec."""
    if len(spec.workers) < MIN_WORKERS:
        sys.stderr.write(
            f"[bumba] ERROR: at least {MIN_WORKERS} worker(s) required.\n"
        )
        raise SystemExit(1)
    if len(spec.workers) > MAX_WORKERS:
        sys.stderr.write(
            f"[bumba] ERROR: max {MAX_WORKERS} workers per scaffold call.\n"
            f"        Provided: {len(spec.workers)}. Add more later with `bumba new-specialist`.\n"
        )
        raise SystemExit(1)
    # Check for duplicate worker names
    worker_names = [w["name"] for w in spec.workers]
    seen: set[str] = set()
    for wn in worker_names:
        if wn in seen:
            sys.stderr.write(
                f"[bumba] ERROR: duplicate worker name {wn!r} in roster.\n"
            )
            raise SystemExit(1)
        seen.add(wn)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _resolve_paths(spec: TeamSpec) -> TeamScaffoldPaths:
    """Build all on-disk targets for the team scaffold."""
    chief_name = f"{spec.prefix}-chief"
    team_yaml = str(TEAMS_DIR / f"{spec.name}.yaml")
    chief_expertise = str(
        REPO_ROOT / f"agent/config/expertise/updatable/{chief_name}.md"
    )
    chief_prompt = str(
        REPO_ROOT / f"agent/config/agents/zone4/{spec.name}/{chief_name}.md"
    )
    worker_expertises = tuple(
        str(REPO_ROOT / f"agent/config/expertise/updatable/{w['name']}.md")
        for w in spec.workers
    )
    worker_prompts = tuple(
        str(REPO_ROOT / f"agent/config/agents/zone4/{spec.name}/{w['name']}.md")
        for w in spec.workers
    )
    checklist = str(
        REPO_ROOT / f"agent/data/scaffolding/{spec.name}-team-checklist.md"
    )
    return TeamScaffoldPaths(
        team_yaml=team_yaml,
        chief_expertise=chief_expertise,
        chief_prompt=chief_prompt,
        worker_expertises=worker_expertises,
        worker_prompts=worker_prompts,
        checklist=checklist,
    )


def _verify_no_file_collisions(paths: TeamScaffoldPaths) -> None:
    """Abort with exit 1 if any target file already exists."""
    targets = [
        paths.team_yaml,
        paths.chief_expertise,
        paths.chief_prompt,
        paths.checklist,
        *paths.worker_expertises,
        *paths.worker_prompts,
    ]
    for target in targets:
        if Path(target).exists():
            sys.stderr.write(
                f"[bumba] ERROR: {target} already exists.\n"
                f"        Refusing to overwrite operator-authored content.\n"
            )
            raise SystemExit(1)


# ---------------------------------------------------------------------------
# File writing
# ---------------------------------------------------------------------------

def _write_file(path: str, content: str) -> None:
    """Atomic write: mkdir -p, write to .tmp, rename."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.rename(p)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _build_workers_yaml_block(spec: TeamSpec) -> str:
    """Build the indented workers YAML block for embedding in team YAML."""
    blocks: list[str] = []
    for w in spec.workers:
        blocks.append(worker_yaml_block_for(w["name"], spec.name, w["role"]))
    return "".join(blocks)


def _checklist_source(spec: TeamSpec, paths: TeamScaffoldPaths) -> str:
    chief_name = f"{spec.prefix}-chief"
    worker_lines = "\n".join(
        f"   - `{w['name']}` — role: {w['role']}" for w in spec.workers
    )
    return f"""\
# {spec.name} team — operator fill-in checklist

Generated by `bumba new-team {spec.name}`.

---

## Team summary

- **Department name:** {spec.name}
- **Prefix:** {spec.prefix}
- **Chief:** {chief_name}
- **Workers ({len(spec.workers)}):**
{worker_lines}

---

## Required actions

### 1. agent/config/teams/{spec.name}.yaml

- `escalation.triggers` — replace placeholder strings with real routing keywords
- `tools.department` — add department-specific tools once known
- `tools.per_employee` — narrow per-worker tool allowlists after first use
- `domain.write` paths on each worker — narrow to actual write paths

### 2. agent/config/agents/zone4/{spec.name}/{chief_name}.md (chief system prompt)

- Replace `<!-- 3-5 sentences describing department mission -->` with real mission
- Add 2-3 `## Examples` of correct orchestration patterns

### 3. agent/config/expertise/updatable/{chief_name}.md

- `## Delegation Patterns` — which specialist owns what; when chief handles solo
- `## Synthesis Patterns` — how to merge specialist outputs

### 4. Each worker system prompt (agent/config/agents/zone4/{spec.name}/)

- Replace `<!-- 3-5 sentences ... -->` mission placeholder with real missions

### 5. Each worker expertise stub (agent/config/expertise/updatable/)

- `## Domain Patterns` — add ≥3 patterns per specialist

---

## Verification

```bash
# Confirm team YAML re-parses cleanly
python3 -c "import yaml; yaml.safe_load(open('agent/config/teams/{spec.name}.yaml'))"

# Offline construction test (no API key needed)
python3 -m pytest agent/tests/test_teams/ -m offline -v -k {spec.name}
```
"""


# ---------------------------------------------------------------------------
# Interactive prompting
# ---------------------------------------------------------------------------

def _prompt(prompt_text: str, default: str | None = None) -> str:
    """Prompt user for input; re-prompt if empty and no default."""
    suffix = f" [{default}]" if default else ""
    while True:
        sys.stdout.write(f"{prompt_text}{suffix}: ")
        sys.stdout.flush()
        value = sys.stdin.readline().rstrip("\n")
        if not value and default is not None:
            return default
        if value.strip():
            return value.strip()
        sys.stderr.write("  (required — please enter a value)\n")


def _collect_interactive(name: str) -> TeamSpec:
    """Run the interactive prompt flow to collect team parameters."""
    sys.stdout.write(f"\n[bumba] new-team: scaffolding '{name}'\n\n")

    # Department prefix
    sys.stdout.write(
        "Department prefix — used to name the chief and workers.\n"
        "  Example: for team 'data-science', prefix might be 'ds'\n"
    )
    prefix = _validate_name(_prompt("Prefix (kebab-case)"), "prefix")

    # Description
    sys.stdout.write("\nDepartment description (1-2 sentences):\n")
    description = _prompt("Description")

    # Chief role
    sys.stdout.write(
        f"\nChief role — one sentence describing what {prefix}-chief orchestrates.\n"
    )
    chief_role = _prompt("Chief role")

    # Chief mission
    sys.stdout.write(
        "\nChief mission — 3-5 sentences: what outcomes does this department own?\n"
    )
    chief_mission = _prompt("Chief mission")

    # Specialist roster
    sys.stdout.write(
        f"\nSpecialist roster — enter each specialist name (kebab-case), then its role.\n"
        f"  Names will be prefixed with '{prefix}-' automatically.\n"
        f"  Enter a blank name to finish (min {MIN_WORKERS}, max {MAX_WORKERS} workers).\n\n"
    )
    workers: list[dict[str, str]] = []
    worker_idx = 1
    while len(workers) < MAX_WORKERS:
        sys.stdout.write(f"  Worker {worker_idx} name (or blank to finish): ")
        sys.stdout.flush()
        raw_name = sys.stdin.readline().rstrip("\n").strip()
        if not raw_name:
            if len(workers) < MIN_WORKERS:
                sys.stderr.write(
                    f"  (at least {MIN_WORKERS} worker required — enter a name)\n"
                )
                continue
            break
        full_name = _validate_name(f"{prefix}-{raw_name}", f"worker {worker_idx} name")
        sys.stdout.write(f"  Worker {worker_idx} role: ")
        sys.stdout.flush()
        role = sys.stdin.readline().rstrip("\n").strip()
        if not role:
            sys.stderr.write("  (role required — re-entering this worker)\n")
            continue
        workers.append({"name": full_name, "role": role})
        worker_idx += 1

    return TeamSpec(
        name=name,
        prefix=prefix,
        description=description,
        chief_role=chief_role,
        chief_mission=chief_mission,
        workers=workers,
    )


# ---------------------------------------------------------------------------
# Config-file parsing
# ---------------------------------------------------------------------------

def _parse_config(name: str, config_path: Path) -> TeamSpec:
    """Parse a YAML config file into a TeamSpec."""
    if not config_path.exists():
        sys.stderr.write(
            f"[bumba] ERROR: config file not found: {config_path}\n"
        )
        raise SystemExit(1)

    raw: Any
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        sys.stderr.write(f"[bumba] ERROR: invalid YAML in {config_path}: {exc}\n")
        raise SystemExit(1)

    if not isinstance(raw, dict):
        sys.stderr.write(
            f"[bumba] ERROR: config must be a YAML mapping, got {type(raw).__name__}.\n"
        )
        raise SystemExit(1)

    def _require(key: str) -> Any:
        if key not in raw:
            sys.stderr.write(
                f"[bumba] ERROR: missing required key '{key}' in {config_path}.\n"
            )
            raise SystemExit(1)
        return raw[key]

    prefix = _validate_name(str(_require("prefix")), "prefix")
    description = str(_require("description"))
    chief_role = str(_require("chief_role"))
    chief_mission = str(_require("chief_mission"))

    raw_workers = _require("workers")
    if not isinstance(raw_workers, list):
        sys.stderr.write(
            f"[bumba] ERROR: 'workers' must be a list in {config_path}.\n"
        )
        raise SystemExit(1)

    workers: list[dict[str, str]] = []
    for i, w in enumerate(raw_workers):
        if not isinstance(w, dict):
            sys.stderr.write(
                f"[bumba] ERROR: workers[{i}] must be a mapping.\n"
            )
            raise SystemExit(1)
        if "name" not in w or "role" not in w:
            sys.stderr.write(
                f"[bumba] ERROR: workers[{i}] must have 'name' and 'role' keys.\n"
            )
            raise SystemExit(1)
        full_name = _validate_name(f"{prefix}-{w['name']}", f"workers[{i}].name")
        workers.append({"name": full_name, "role": str(w["role"])})

    return TeamSpec(
        name=name,
        prefix=prefix,
        description=description,
        chief_role=chief_role,
        chief_mission=chief_mission,
        workers=workers,
    )


# ---------------------------------------------------------------------------
# Scaffold execution
# ---------------------------------------------------------------------------

def _scaffold(spec: TeamSpec) -> TeamScaffoldPaths:
    """Write all files for the team scaffold. Returns resolved paths."""
    paths = _resolve_paths(spec)
    _verify_no_file_collisions(paths)

    chief_name = f"{spec.prefix}-chief"

    # Build team YAML
    workers_block = _build_workers_yaml_block(spec)
    team_yaml_content = team_yaml_for(
        name=spec.name,
        prefix=spec.prefix,
        description=spec.description,
        chief_name=chief_name,
        chief_role=spec.chief_role,
        chief_mission=spec.chief_mission,
        workers_block=workers_block,
    )

    # Verify the generated YAML re-parses cleanly before writing anything.
    try:
        yaml.safe_load(team_yaml_content)
    except yaml.YAMLError as exc:
        sys.stderr.write(
            f"[bumba] INTERNAL ERROR: generated team YAML failed to parse: {exc}\n"
            f"        This is a bug in new_team.py; please report it.\n"
        )
        raise SystemExit(2)

    # All pre-flight checks done — write atomically.
    _write_file(paths.team_yaml, team_yaml_content)
    _write_file(paths.chief_expertise, chief_expertise_for(chief_name, spec.name))
    _write_file(
        paths.chief_prompt,
        chief_prompt_for(
            name=chief_name,
            team=spec.name,
            prefix=spec.prefix,
            role=spec.chief_role,
            mission=spec.chief_mission,
        ),
    )

    for i, worker in enumerate(spec.workers):
        _write_file(
            paths.worker_expertises[i],
            expertise_for(worker["name"], spec.name),
        )
        _write_file(
            paths.worker_prompts[i],
            worker_prompt_for(worker["name"], spec.name, worker["role"]),
        )

    _write_file(paths.checklist, _checklist_source(spec, paths))
    return paths


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bumba new-team",
        description="Scaffold a complete Zone 4 department in < 5 seconds.",
    )
    parser.add_argument("name", help="new team name in kebab-case (e.g. data-science)")
    parser.add_argument(
        "--config",
        metavar="YAML",
        help="Non-interactive mode: path to a YAML spec file (see docs for schema).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    started = time.monotonic()

    # Validate team name first.
    name = _validate_name(args.name, "team name")

    # Abort if team already exists.
    _verify_no_duplicate_team(name)

    # Collect spec: config file or interactive.
    if args.config:
        spec = _parse_config(name, Path(args.config))
    else:
        spec = _collect_interactive(name)

    _validate_spec(spec)

    sys.stdout.write(f"\n[bumba] new-team: building scaffold for '{name}'...\n")
    try:
        paths = _scaffold(spec)
    except OSError as exc:
        sys.stderr.write(f"[bumba] ERROR: I/O failure during scaffold: {exc}\n")
        raise SystemExit(2)

    n_files = 3 + 2 * len(spec.workers) + 1  # yaml + chief(2) + workers(2 each) + checklist
    elapsed = time.monotonic() - started

    sys.stdout.write(
        f"[bumba] done in {elapsed:.1f}s — {n_files} files written\n"
        f"\n"
        f"[bumba] team YAML:       {paths.team_yaml}\n"
        f"[bumba] chief expertise: {paths.chief_expertise}\n"
        f"[bumba] chief prompt:    {paths.chief_prompt}\n"
    )
    for i, w in enumerate(spec.workers):
        sys.stdout.write(
            f"[bumba] worker:          {paths.worker_expertises[i]}\n"
            f"                         {paths.worker_prompts[i]}\n"
        )
    sys.stdout.write(
        f"[bumba] checklist:       {paths.checklist}\n"
        f"\n"
        f"[bumba] Next: open the checklist and fill in the required fields.\n"
        f"[bumba] DepartmentRegistry will pick up '{name}' on next prewarm() call.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
