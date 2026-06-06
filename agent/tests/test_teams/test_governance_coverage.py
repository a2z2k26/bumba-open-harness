"""Coverage tests for Zone 4 chief governance bundles."""

from __future__ import annotations

from pathlib import Path

import yaml

AGENT_ROOT = Path(__file__).resolve().parents[2]
TEAMS_DIR = AGENT_ROOT / "config" / "teams"
GOVERNANCE_ROOT = AGENT_ROOT / "config" / "governance" / "zone4"
REQUIRED_FILES = ("CLAUDE.md", "SOUL.md", "ARTIFACTS.md")


def _zone4_chief_bundles() -> list[tuple[str, str, Path]]:
    bundles: list[tuple[str, str, Path]] = []
    for path in sorted(TEAMS_DIR.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        team = data["team"]
        if int(team["zone"]) != 4:
            continue
        department = str(team["name"])
        chief_name = str(team["chief"]["name"])
        bundles.append(
            (
                department,
                chief_name,
                GOVERNANCE_ROOT / department / chief_name,
            )
        )
    return bundles


def test_every_zone4_chief_has_governance_bundle() -> None:
    missing: list[str] = []

    for _department, chief_name, bundle in _zone4_chief_bundles():
        for filename in REQUIRED_FILES:
            if not (bundle / filename).is_file():
                missing.append(f"{chief_name}/{filename}")

    assert missing == []


def test_chief_governance_bundles_stay_concise() -> None:
    too_long: list[str] = []

    for _department, chief_name, bundle in _zone4_chief_bundles():
        if not (bundle / "CLAUDE.md").is_file():
            continue
        if not (bundle / "SOUL.md").is_file():
            continue
        claude_lines = (bundle / "CLAUDE.md").read_text(
            encoding="utf-8"
        ).splitlines()
        soul_lines = (bundle / "SOUL.md").read_text(
            encoding="utf-8"
        ).splitlines()
        if len(claude_lines) >= 80:
            too_long.append(f"{chief_name}/CLAUDE.md:{len(claude_lines)}")
        if len(soul_lines) >= 60:
            too_long.append(f"{chief_name}/SOUL.md:{len(soul_lines)}")

    assert too_long == []
