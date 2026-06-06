"""bumba scaffold-zone4 <kind> <name> — single-command Zone 4 scaffolding.

D7.5 finding F-FS: frictionless team setup is the future-state goal.
The seam exists here. D7.13 (#1425) adds the golden-path template +
validator + doctor on top so first-run is healthy by default.


Dispatches to the correct bundle family based on <kind>:

  single-agent       Solo agent (chief = worker, empty workers list).
                     Produces: expertise, system_prompt, team YAML (3 files).

  chief-specialist   Chief + one named specialist.
                     Produces: chief expertise, chief prompt, specialist
                     expertise, specialist prompt, team YAML (5 files).

  agent-team         Chief + N workers via new_team.py interactive or
                     --config path. Delegates entirely to new_team.main().

For single-agent and chief-specialist, files are written atomically
(tmp + rename) and a post-write DepartmentRegistry discovery check is run.

Exit codes:
  0  scaffold succeeded
  1  validation failure (bad kind, collision, discovery failure)
  2  unexpected I/O error
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Iterable


from scripts import new_team
from teams._config import InvalidConfigError, load_department_config
from scripts._scaffolding_templates import (
    BundleResult,
    ChiefSpecialistBundle,
    SingleAgentBundle,
)

# Repo root: agent/scripts/ → agent/ → repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
TEAMS_DIR = REPO_ROOT / "agent" / "config" / "teams"

VALID_KINDS = ("single-agent", "chief-specialist", "agent-team")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_name(name: str) -> str:
    """Enforce kebab-case and non-empty. Returns name or exits 1."""
    import re
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
        sys.stderr.write(
            f"[bumba] ERROR: name {name!r} must be kebab-case (a-z, 0-9, -).\n"
        )
        raise SystemExit(1)
    return name


def _verify_no_team_collision(team_name: str) -> None:
    target = TEAMS_DIR / f"{team_name}.yaml"
    if target.exists():
        sys.stderr.write(
            f"[bumba] ERROR: team {team_name!r} already exists at {target}.\n"
            f"        To update an existing team, edit the YAML directly.\n"
        )
        raise SystemExit(1)


def _verify_no_file_collisions(result: BundleResult) -> None:
    for rel_path, _ in result.files:
        p = REPO_ROOT / rel_path
        if p.exists():
            sys.stderr.write(
                f"[bumba] ERROR: {p} already exists.\n"
                f"        Refusing to overwrite operator-authored content.\n"
            )
            raise SystemExit(1)


def _write_file(rel_path: str, content: str) -> None:
    """Atomic write: mkdir -p, write to .tmp, rename."""
    p = REPO_ROOT / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.rename(p)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _write_bundle(result: BundleResult) -> None:
    for rel_path, content in result.files:
        _write_file(rel_path, content)


def _check_registry_discovery(team_name: str) -> None:
    """Assert the new team YAML is loadable. Exits 1 on failure."""
    team_yaml = TEAMS_DIR / f"{team_name}.yaml"
    try:
        load_department_config(team_yaml)
    except (InvalidConfigError, Exception) as exc:
        sys.stderr.write(
            f"[bumba] ERROR: post-write registry discovery failed for {team_name!r}.\n"
            f"        load_department_config raised: {exc}\n"
            f"        The files were written but the YAML did not validate.\n"
            f"        Fix the YAML manually or re-scaffold.\n"
        )
        raise SystemExit(1)


def _print_bundle_paths(result: BundleResult, elapsed: float) -> None:
    n = len(result.files)
    sys.stdout.write(f"[bumba] done in {elapsed:.1f}s — {n} files written\n")
    for rel_path, _ in result.files:
        sys.stdout.write(f"[bumba]   {rel_path}\n")


# ---------------------------------------------------------------------------
# Dispatch functions
# ---------------------------------------------------------------------------


def _dispatch_single_agent(name: str) -> int:
    """Render and write a synthetic single-agent team scaffold."""
    _validate_name(name)
    _verify_no_team_collision(name)

    bundle = SingleAgentBundle()
    result = bundle.render(name=name, team=name)
    _verify_no_file_collisions(result)

    started = time.monotonic()
    try:
        _write_bundle(result)
    except OSError as exc:
        sys.stderr.write(f"[bumba] ERROR: I/O failure: {exc}\n")
        return 2

    _check_registry_discovery(name)

    elapsed = time.monotonic() - started
    _print_bundle_paths(result, elapsed)
    sys.stdout.write(
        f"[bumba] DepartmentRegistry will discover '{name}' on next prewarm().\n"
    )
    return 0


def _dispatch_chief_specialist(name: str, specialist_suffix: str = "specialist") -> int:
    """Render and write a chief + one specialist scaffold."""
    _validate_name(name)
    _verify_no_team_collision(name)

    chief_name = f"{name}-chief"
    specialist_name = f"{name}-{specialist_suffix}"

    bundle = ChiefSpecialistBundle()
    result = bundle.render(
        team=name,
        prefix=name,
        description=f"{name.replace('-', ' ').title()} department.",
        chief_name=chief_name,
        chief_role=f"Leads the {name} department.",
        chief_mission=f"<!-- Describe the {name} department mission (3-5 sentences). -->",
        specialist_name=specialist_name,
    )
    _verify_no_file_collisions(result)

    started = time.monotonic()
    try:
        _write_bundle(result)
    except OSError as exc:
        sys.stderr.write(f"[bumba] ERROR: I/O failure: {exc}\n")
        return 2

    _check_registry_discovery(name)

    elapsed = time.monotonic() - started
    _print_bundle_paths(result, elapsed)
    sys.stdout.write(
        f"[bumba] Chief: {chief_name}\n"
        f"[bumba] Specialist: {specialist_name}\n"
        f"[bumba] DepartmentRegistry will discover '{name}' on next prewarm().\n"
    )
    return 0


def _dispatch_agent_team(name: str, config_path: str | None) -> int:
    """Forward to new_team.main() for interactive or config-driven team scaffold."""
    argv: list[str] = [name]
    if config_path is not None:
        argv += ["--config", config_path]

    return new_team.main(argv)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bumba scaffold-zone4",
        description="Scaffold a Zone 4 department in one command.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Kinds:\n"
            "  single-agent       Solo agent (no delegation). 3 files.\n"
            "  chief-specialist   Chief + one specialist. 5 files.\n"
            "  agent-team         Chief + N workers (interactive or --config). N+3 files.\n"
        ),
    )
    parser.add_argument(
        "kind",
        choices=list(VALID_KINDS),
        metavar="kind",
        help=f"scaffold family: {', '.join(VALID_KINDS)}",
    )
    parser.add_argument("name", help="new team/agent name in kebab-case")
    parser.add_argument(
        "--config",
        metavar="YAML",
        help="(agent-team only) path to a new_team config YAML for non-interactive mode",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.kind == "single-agent":
        return _dispatch_single_agent(args.name)
    elif args.kind == "chief-specialist":
        return _dispatch_chief_specialist(args.name)
    else:
        return _dispatch_agent_team(args.name, args.config)


if __name__ == "__main__":
    raise SystemExit(main())
