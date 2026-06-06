"""Tests for Zone 4 capability manifests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from bridge.capability_manifest import (
    CapabilityManifestError,
    load_capability_manifest,
    load_capability_manifests,
)

AGENT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_ROOT = AGENT_ROOT / "config" / "capabilities" / "zone4"
TEAMS_DIR = AGENT_ROOT / "config" / "teams"


def _write_manifest(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _zone4_teams() -> dict[str, dict[str, object]]:
    teams: dict[str, dict[str, object]] = {}
    for path in sorted(TEAMS_DIR.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        team = data["team"]
        if int(team.get("zone", 0)) == 4:
            teams[str(team["name"])] = team
    return teams


def test_load_capability_manifest_parses_strict_shape(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path / "strategy.yaml",
        """
department: strategy
mode: report_only
defaults:
  mcp_servers: []
  tools:
    - read_file
  skills:
    - mental-model
chief:
  strategy-product-chief:
    tools:
      - search_market_data
specialists:
  strategy-market-researcher:
    skills:
      - market-research
""",
    )

    manifest = load_capability_manifest(path)

    assert manifest.department == "strategy"
    assert manifest.mode == "report_only"
    assert manifest.defaults.tools == ("read_file",)
    assert manifest.chief["strategy-product-chief"].tools == ("search_market_data",)
    assert manifest.specialists["strategy-market-researcher"].skills == (
        "market-research",
    )


def test_unknown_fields_are_rejected(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path / "bad.yaml",
        """
department: strategy
mode: report_only
defaults:
  tools: []
  surprise: true
chief: {}
specialists: {}
""",
    )

    with pytest.raises(CapabilityManifestError, match="unknown"):
        load_capability_manifest(path)


def test_all_repo_zone4_manifests_parse_with_one_strict_department() -> None:
    manifests = load_capability_manifests(MANIFEST_ROOT)

    assert set(manifests) == set(_zone4_teams())
    assert {
        department
        for department, manifest in manifests.items()
        if manifest.mode == "strict"
    } == {"strategy"}


def test_manifest_agents_match_team_yaml_rosters() -> None:
    teams = _zone4_teams()
    manifests = load_capability_manifests(MANIFEST_ROOT)
    mismatches: list[str] = []

    for department, team in teams.items():
        manifest = manifests[department]
        chief_name = str(team["chief"]["name"])
        worker_names = {
            str(worker["name"])
            for worker in team.get("workers", []) or []
        }
        if set(manifest.chief) != {chief_name}:
            mismatches.append(f"{department}: chief {set(manifest.chief)} != {chief_name}")
        extra_specialists = set(manifest.specialists) - worker_names
        if extra_specialists:
            mismatches.append(
                f"{department}: unknown specialists {sorted(extra_specialists)}"
            )
        missing_specialists = worker_names - set(manifest.specialists)
        if missing_specialists and (
            manifest.mode == "strict" or not manifest.defaults
        ):
            mismatches.append(
                f"{department}: missing specialists {sorted(missing_specialists)}"
            )

    assert mismatches == []


def test_job_search_playwright_is_browser_specialist_only() -> None:
    manifest = load_capability_manifest(MANIFEST_ROOT / "job_search.yaml")

    assert manifest.defaults.mcp_servers == ()
    assert manifest.specialists["browser-use-specialist"].mcp_servers == (
        "playwright",
    )
