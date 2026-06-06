"""Tests for E4.1 — BundleResult + three *Bundle families.

Round-trip contract: every rendered YAML must pass ``load_department_config``
without raising ``InvalidConfigError``.
"""
from __future__ import annotations

import io

import pytest
import yaml

from scripts._scaffolding_templates import (
    DEFAULT_ZONE4_TOOL_CAPABLE_ADAPTER,
    DEFAULT_ZONE4_TOOL_CAPABLE_MODEL,
    AgentTeamBundle,
    BundleResult,
    ChiefSpecialistBundle,
    SingleAgentBundle,
    worker_yaml_block_for,
)


# ---------------------------------------------------------------------------
# BundleResult
# ---------------------------------------------------------------------------


class TestBundleResult:
    def test_frozen(self):
        br = BundleResult(files=(("a/b.md", "content"),))
        with pytest.raises((AttributeError, TypeError)):
            br.files = ()  # type: ignore[misc]

    def test_files_is_tuple(self):
        br = BundleResult(files=(("path", "body"),))
        assert isinstance(br.files, tuple)

    def test_empty_files(self):
        br = BundleResult(files=())
        assert len(br.files) == 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_team_yaml(result: BundleResult) -> str:
    """Return the content of the first .yaml file in a BundleResult."""
    for path, content in result.files:
        if path.endswith(".yaml"):
            return content
    raise AssertionError("No YAML file found in BundleResult")


def _round_trip_yaml(yaml_content: str) -> None:
    """Assert that yaml_content passes _RootSchema validation."""

    # load_department_config reads from the filesystem, so we use a tmp fixture.
    # Since we only need schema validation, parse the YAML directly here.
    from teams._config import _RootSchema

    raw = yaml.safe_load(io.StringIO(yaml_content))
    try:
        _RootSchema.model_validate(raw)
    except Exception as exc:
        raise AssertionError(f"Schema validation failed: {exc}\n\nYAML:\n{yaml_content}") from exc


def _assert_default_members_use_tool_capable_backend(yaml_content: str) -> None:
    data = yaml.safe_load(io.StringIO(yaml_content))
    team = data["team"]
    members = [team["chief"], *(team.get("workers") or [])]
    assert members
    for member in members:
        assert member["model"] == DEFAULT_ZONE4_TOOL_CAPABLE_MODEL
        assert member["adapter"] == DEFAULT_ZONE4_TOOL_CAPABLE_ADAPTER


# ---------------------------------------------------------------------------
# SingleAgentBundle
# ---------------------------------------------------------------------------


class TestSingleAgentBundle:
    def setup_method(self):
        self.bundle = SingleAgentBundle()
        self.result = self.bundle.render(
            name="clio",
            team="research",
            role="Handles all research tasks autonomously.",
        )

    def test_returns_bundle_result(self):
        assert isinstance(self.result, BundleResult)

    def test_produces_three_files(self):
        assert len(self.result.files) == 3

    def test_expertise_file_present(self):
        paths = [p for p, _ in self.result.files]
        assert "agent/config/expertise/updatable/clio.md" in paths

    def test_prompt_file_present(self):
        paths = [p for p, _ in self.result.files]
        assert "agent/config/agents/zone4/research/clio.md" in paths

    def test_yaml_file_present(self):
        paths = [p for p, _ in self.result.files]
        assert "agent/config/teams/research.yaml" in paths

    def test_yaml_passes_schema_validation(self):
        _round_trip_yaml(_extract_team_yaml(self.result))

    def test_yaml_has_empty_workers(self):
        data = yaml.safe_load(io.StringIO(_extract_team_yaml(self.result)))
        assert data["team"]["workers"] == []

    def test_yaml_chief_name_matches_agent(self):
        data = yaml.safe_load(io.StringIO(_extract_team_yaml(self.result)))
        assert data["team"]["chief"]["name"] == "clio"

    def test_default_chief_uses_tool_capable_backend(self):
        _assert_default_members_use_tool_capable_backend(
            _extract_team_yaml(self.result)
        )

    def test_default_role_used_when_omitted(self):
        result = SingleAgentBundle().render(name="agent", team="solo")
        data = yaml.safe_load(io.StringIO(_extract_team_yaml(result)))
        assert data["team"]["chief"]["role"].strip() != ""


# ---------------------------------------------------------------------------
# AgentTeamBundle
# ---------------------------------------------------------------------------


class TestAgentTeamBundle:
    def setup_method(self):
        workers_block = worker_yaml_block_for("aria", "design", "Visual design specialist")
        self.bundle = AgentTeamBundle(
            worker_specs=(("aria", "design", "Visual design specialist"),)
        )
        self.result = self.bundle.render(
            name="design",
            prefix="design",
            description="Design department that handles UI/UX work.",
            chief_name="design-chief",
            chief_role="Leads the design department.",
            chief_mission="Produce beautiful, functional design artifacts.",
            workers_block=workers_block,
        )

    def test_returns_bundle_result(self):
        assert isinstance(self.result, BundleResult)

    def test_chief_expertise_present(self):
        paths = [p for p, _ in self.result.files]
        assert "agent/config/expertise/updatable/design-chief.md" in paths

    def test_chief_prompt_present(self):
        paths = [p for p, _ in self.result.files]
        assert "agent/config/agents/zone4/design/design-chief.md" in paths

    def test_worker_expertise_present(self):
        paths = [p for p, _ in self.result.files]
        assert "agent/config/expertise/updatable/aria.md" in paths

    def test_worker_prompt_present(self):
        paths = [p for p, _ in self.result.files]
        assert "agent/config/agents/zone4/design/aria.md" in paths

    def test_yaml_passes_schema_validation(self):
        _round_trip_yaml(_extract_team_yaml(self.result))

    def test_yaml_has_worker_entry(self):
        data = yaml.safe_load(io.StringIO(_extract_team_yaml(self.result)))
        worker_names = [w["name"] for w in data["team"]["workers"]]
        assert "aria" in worker_names

    def test_default_members_use_tool_capable_backend(self):
        _assert_default_members_use_tool_capable_backend(
            _extract_team_yaml(self.result)
        )

    def test_no_worker_specs_produces_minimal_bundle(self):
        bundle = AgentTeamBundle()
        result = bundle.render(
            name="ops",
            prefix="ops",
            description="Ops department.",
            chief_name="ops-chief",
            chief_role="Ops chief.",
            chief_mission="Ensure reliability.",
            workers_block="",
        )
        # 3 files: chief expertise, chief prompt, team yaml
        assert len(result.files) == 3

    def test_multiple_worker_specs(self):
        workers_block = (
            worker_yaml_block_for("w1", "eng", "Worker one")
            + worker_yaml_block_for("w2", "eng", "Worker two")
        )
        bundle = AgentTeamBundle(
            worker_specs=(("w1", "eng", "Worker one"), ("w2", "eng", "Worker two"))
        )
        result = bundle.render(
            name="eng",
            prefix="eng",
            description="Engineering team.",
            chief_name="eng-chief",
            chief_role="Engineering chief.",
            chief_mission="Ship solid code.",
            workers_block=workers_block,
        )
        paths = [p for p, _ in result.files]
        assert "agent/config/expertise/updatable/w1.md" in paths
        assert "agent/config/expertise/updatable/w2.md" in paths


# ---------------------------------------------------------------------------
# ChiefSpecialistBundle
# ---------------------------------------------------------------------------


class TestChiefSpecialistBundle:
    def setup_method(self):
        self.bundle = ChiefSpecialistBundle()
        self.result = self.bundle.render(
            team="qa",
            prefix="qa",
            description="QA department for automated testing.",
            chief_name="qa-chief",
            chief_role="Leads the QA department.",
            chief_mission="Ensure code ships bug-free.",
            specialist_name="qa-tester",
            specialist_role="Runs automated test suites.",
        )

    def test_returns_bundle_result(self):
        assert isinstance(self.result, BundleResult)

    def test_produces_five_files(self):
        # chief expertise, chief prompt, specialist expertise, specialist prompt, yaml
        assert len(self.result.files) == 5

    def test_chief_expertise_present(self):
        paths = [p for p, _ in self.result.files]
        assert "agent/config/expertise/updatable/qa-chief.md" in paths

    def test_specialist_expertise_present(self):
        paths = [p for p, _ in self.result.files]
        assert "agent/config/expertise/updatable/qa-tester.md" in paths

    def test_yaml_passes_schema_validation(self):
        _round_trip_yaml(_extract_team_yaml(self.result))

    def test_yaml_has_exactly_one_worker(self):
        data = yaml.safe_load(io.StringIO(_extract_team_yaml(self.result)))
        assert len(data["team"]["workers"]) == 1
        assert data["team"]["workers"][0]["name"] == "qa-tester"

    def test_default_members_use_tool_capable_backend(self):
        _assert_default_members_use_tool_capable_backend(
            _extract_team_yaml(self.result)
        )

    def test_default_specialist_role_used_when_omitted(self):
        result = ChiefSpecialistBundle().render(
            team="misc",
            prefix="misc",
            description="Misc dept.",
            chief_name="misc-chief",
            chief_role="Misc chief.",
            chief_mission="Do misc things.",
            specialist_name="misc-worker",
        )
        data = yaml.safe_load(io.StringIO(_extract_team_yaml(result)))
        assert data["team"]["workers"][0]["role"].strip() != ""

    def test_yaml_chief_name_matches(self):
        data = yaml.safe_load(io.StringIO(_extract_team_yaml(self.result)))
        assert data["team"]["chief"]["name"] == "qa-chief"
