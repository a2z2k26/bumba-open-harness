"""Tests for job_search department YAML config (sprint D5.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from teams._config import load_department_config


_TEAMS_DIR = Path(__file__).parent.parent.parent / "config" / "teams"


class TestJobSearchConfig:
    def test_job_search_yaml_exists(self):
        assert (_TEAMS_DIR / "job_search.yaml").exists()

    def test_job_search_loads(self):
        cfg = load_department_config(_TEAMS_DIR / "job_search.yaml")
        assert cfg.name == "job_search"
        assert cfg.zone == 4

    def test_job_search_chief_fields(self):
        # #2566 hybrid fleet: job-search chief flipped to anthropic-oauth on
        # the fix/2566 branch (chiefs REQUIRE tool-calling, codex-exec can't
        # drive it). The 4 specialists below stay codex-exec (prose only).
        cfg = load_department_config(_TEAMS_DIR / "job_search.yaml")
        assert cfg.manager.name == "job-search-chief"
        assert cfg.manager.model == "anthropic-oauth:claude-sonnet-4-5"
        assert cfg.manager.adapter == "claude"

    def test_job_search_specialists(self):
        """Sprint D5.2 architecture — 4 specialists under the chief."""
        cfg = load_department_config(_TEAMS_DIR / "job_search.yaml")
        assert len(cfg.employees) == 4

    def test_job_search_constraints(self):
        cfg = load_department_config(_TEAMS_DIR / "job_search.yaml")
        assert cfg.constraints.cost_limit_usd == pytest.approx(14.00)
        assert cfg.constraints.timeout_seconds == 3600
        assert cfg.constraints.concurrency_limit == 1

    def test_job_search_department_tools(self):
        cfg = load_department_config(_TEAMS_DIR / "job_search.yaml")
        assert "scrape_boards" in cfg.department_tools
        assert "score_and_deduplicate" in cfg.department_tools
        assert "stage_listing_to_notion" in cfg.department_tools
        assert "send_discord_alert" in cfg.department_tools

    def test_job_search_common_tools(self):
        cfg = load_department_config(_TEAMS_DIR / "job_search.yaml")
        assert "read_file" in cfg.common_tools
        assert "search_knowledge" in cfg.common_tools

    def test_job_search_budget(self):
        cfg = load_department_config(_TEAMS_DIR / "job_search.yaml")
        assert cfg.budget.daily_limit_usd == pytest.approx(15.00)

    def test_job_search_vapi_disabled(self):
        cfg = load_department_config(_TEAMS_DIR / "job_search.yaml")
        assert cfg.vapi.enabled is False


class TestRegistryDiscovery:
    def test_registry_finds_job_search(self):
        from teams._registry import DepartmentRegistry
        registry = DepartmentRegistry.from_directory(_TEAMS_DIR)
        assert "job_search" in registry.department_names()


class TestJobSearchCanonicalization:
    """Sprint P3.1 — only one job-search team is registered."""

    def test_only_one_job_search_team_registered(self):
        from teams._registry import DepartmentRegistry
        registry = DepartmentRegistry.from_directory(_TEAMS_DIR)
        names = registry.department_names()
        job_search_variants = [n for n in names if n in ("job_search", "job-search")]
        assert job_search_variants == ["job_search"]

    def test_legacy_slug_aliases_to_canonical(self):
        """Both ``job-search`` and ``job_search`` resolve to the canonical team."""
        from teams._registry import DEPARTMENT_ALIASES, DepartmentRegistry
        assert DEPARTMENT_ALIASES.get("job-search") == "job_search"

        registry = DepartmentRegistry.from_directory(_TEAMS_DIR)
        canonical = registry.get_config("job_search")
        aliased = registry.get_config("job-search")
        assert aliased is canonical
        assert registry.get_team("job-search") is registry.get_team("job_search")
