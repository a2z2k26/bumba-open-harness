"""Sprint D5.2 (#1207) — job-search-chief smoke tests.

Verifies:
- The job_search team YAML loads without error.
- The team manifest has the correct chief + 4 specialist names.
- The chief system prompt and expertise files exist on disk.
- DepartmentRegistry auto-discovers job_search from teams dir.
"""
from __future__ import annotations

from pathlib import Path


AGENT_DIR = Path(__file__).parent.parent.parent
TEAMS_DIR = AGENT_DIR / "config" / "teams"
AGENTS_DIR = AGENT_DIR / "config" / "agents" / "zone4" / "job_search"
EXPERTISE_DIR = AGENT_DIR / "config" / "expertise" / "updatable"


class TestJobSearchYaml:
    def test_yaml_loads(self):
        from teams._config import load_department_config

        cfg = load_department_config(TEAMS_DIR / "job_search.yaml")
        assert cfg.name == "job_search"
        assert cfg.zone == 4

    def test_chief_name(self):
        from teams._config import load_department_config

        cfg = load_department_config(TEAMS_DIR / "job_search.yaml")
        assert cfg.manager.name == "job-search-chief"

    def test_four_specialists(self):
        from teams._config import load_department_config

        cfg = load_department_config(TEAMS_DIR / "job_search.yaml")
        names = {e.name for e in cfg.employees}
        assert names == {
            "acquire-and-prepare-specialist",
            "outreach-execute-specialist",
            "browser-use-specialist",
            "email-verification-specialist",
        }

    def test_vapi_disabled(self):
        from teams._config import load_department_config

        cfg = load_department_config(TEAMS_DIR / "job_search.yaml")
        assert not cfg.vapi.enabled


class TestJobSearchChiefFiles:
    def test_chief_system_prompt_exists(self):
        prompt = AGENTS_DIR / "job-search-chief.md"
        assert prompt.exists(), f"Missing chief system prompt: {prompt}"

    def test_chief_expertise_exists(self):
        expertise = EXPERTISE_DIR / "job-search-chief.md"
        assert expertise.exists(), f"Missing chief expertise: {expertise}"

    def test_specialist_prompts_exist(self):
        specialists = [
            "acquire-and-prepare-specialist.md",
            "outreach-execute-specialist.md",
            "browser-use-specialist.md",
            "email-verification-specialist.md",
        ]
        for name in specialists:
            path = AGENTS_DIR / name
            assert path.exists(), f"Missing specialist prompt: {path}"

    def test_chief_prompt_contains_mandate(self):
        prompt = (AGENTS_DIR / "job-search-chief.md").read_text()
        assert "PREPARE" in prompt
        assert "EXECUTE" in prompt
        assert "Never auto-submit" in prompt


class TestRegistryAutoDiscovery:
    def test_job_search_discovered(self):
        from teams._registry import DepartmentRegistry

        registry = DepartmentRegistry.from_directory(TEAMS_DIR)
        assert "job_search" in registry.department_names()

    def test_get_team_returns_department_team(self):
        from teams._registry import DepartmentRegistry
        from teams._team import DepartmentTeam

        registry = DepartmentRegistry.from_directory(TEAMS_DIR)
        team = registry.get_team("job_search")
        assert isinstance(team, DepartmentTeam)
