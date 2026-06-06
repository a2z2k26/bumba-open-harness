"""Tests for scripts/regenerate_kernel_baseline.py.

Sprint 1 (#621): Verify recursive globs cover bridge subpackages and teams.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import patch



def _load_module():
    """Import regenerate_kernel_baseline.py as a module.

    The script lives at repo-root /scripts/, NOT /agent/scripts/, because
    Plan 00 explicitly preserved /scripts/ at repo root as an exception to
    the everything-under-/agent/ rule (see Plan 00 §2 Out of scope and
    services.runner --validate Rule 0 allowlist for /scripts/).

    Path resolution from this file: agent/tests/<f>.py → parent (agent/tests)
    → parent (agent) → parent (REPO ROOT) → scripts/
    """
    spec = importlib.util.spec_from_file_location(
        "regenerate_kernel_baseline",
        Path(__file__).resolve().parent.parent.parent / "scripts" / "regenerate_kernel_baseline.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestGlobCoverage:
    """Verify BRIDGE_GLOBS covers all required directories."""

    def test_module_has_bridge_globs(self):
        mod = _load_module()
        assert hasattr(mod, "BRIDGE_GLOBS"), "Expected BRIDGE_GLOBS (plural) after Sprint 1 fix"

    def test_globs_include_recursive_bridge(self):
        mod = _load_module()
        patterns = mod.BRIDGE_GLOBS
        has_recursive = any("bridge/**" in p for p in patterns)
        assert has_recursive, f"BRIDGE_GLOBS must include recursive bridge/**/*.py, got {patterns}"

    def test_globs_include_teams(self):
        mod = _load_module()
        patterns = mod.BRIDGE_GLOBS
        has_teams = any("teams/**" in p for p in patterns)
        assert has_teams, f"BRIDGE_GLOBS must include teams/**/*.py, got {patterns}"

    def test_globs_include_hooks(self):
        mod = _load_module()
        patterns = mod.BRIDGE_GLOBS
        has_hooks = any("hooks" in p for p in patterns)
        assert has_hooks, f"BRIDGE_GLOBS must include hooks pattern, got {patterns}"


class TestBaselineGeneration:
    """Test the actual baseline generation against a fixture tree."""

    def test_generates_baseline_with_submodules(self, tmp_path):
        """Build a fixture tree mimicking the runtime layout, verify submodule files are hashed."""
        mod = _load_module()

        # Create fixture dirs
        agent_dir = tmp_path / "agent"
        bridge_dir = agent_dir / "bridge"
        services_dir = bridge_dir / "services"
        executors_dir = bridge_dir / "executors"
        teams_dir = agent_dir / "teams"
        teams_tools_dir = teams_dir / "tools"
        config_dir = agent_dir / "config"
        hooks_dir = config_dir / "hooks"

        for d in [services_dir, executors_dir, teams_tools_dir, hooks_dir]:
            d.mkdir(parents=True)

        # Create fixture files
        (bridge_dir / "__init__.py").write_text("")
        (bridge_dir / "app.py").write_text("# app")
        (bridge_dir / "security.py").write_text("# security")
        (services_dir / "__init__.py").write_text("")
        (services_dir / "runner.py").write_text("# runner")
        (executors_dir / "__init__.py").write_text("")
        (executors_dir / "base.py").write_text("# base executor")
        (teams_dir / "__init__.py").write_text("")
        (teams_dir / "_team.py").write_text("# team")
        (teams_tools_dir / "__init__.py").write_text("")
        (teams_tools_dir / "_common.py").write_text("# common tools")
        (hooks_dir / "memory-session-start.sh").write_text("#!/bin/bash")

        # Create fixed files
        settings = tmp_path / "settings.json"
        settings.write_text("{}")
        system_prompt = config_dir / "system-prompt.md"
        system_prompt.write_text("# prompt")
        disallowed = config_dir / "disallowed-tools.txt"
        disallowed.write_text("")
        bridge_toml = config_dir / "bridge.toml"
        bridge_toml.write_text("[api]")
        mcp_json = agent_dir / ".mcp.json"
        mcp_json.write_text("{}")

        baseline_path = tmp_path / "kernel-baseline.json"

        # Patch the module's constants to point to fixture tree
        fixture_fixed = [
            str(hooks_dir / "memory-session-start.sh"),
            str(settings),
            str(system_prompt),
            str(disallowed),
            str(bridge_toml),
            str(mcp_json),
        ]
        fixture_globs = [
            str(bridge_dir / "**" / "*.py"),
            str(teams_dir / "**" / "*.py"),
            str(hooks_dir / "*.sh"),
        ]

        with patch.object(mod, "FIXED_FILES", fixture_fixed), \
             patch.object(mod, "BRIDGE_GLOBS", fixture_globs), \
             patch.object(mod, "BASELINE_PATH", baseline_path), \
             patch("pwd.getpwnam") as mock_pwd, \
             patch("os.chown"), \
             patch("os.chmod"):
            mock_pwd.return_value.pw_uid = os.getuid()
            mock_pwd.return_value.pw_gid = os.getgid()
            ret = mod.main()

        assert ret == 0
        assert baseline_path.exists()

        data = json.loads(baseline_path.read_text())
        hashed_files = list(data["files"].keys())

        # Verify submodule files are included
        hashed_basenames = [os.path.basename(f) for f in hashed_files]
        assert "runner.py" in hashed_basenames, "bridge/services/runner.py must be hashed"
        assert "base.py" in hashed_basenames, "bridge/executors/base.py must be hashed"
        assert "_team.py" in hashed_basenames, "teams/_team.py must be hashed"
        assert "_common.py" in hashed_basenames, "teams/tools/_common.py must be hashed"

    def test_baseline_count_exceeds_threshold(self, tmp_path):
        """With a realistic fixture, verify we get enough entries."""
        mod = _load_module()

        # Create a fixture with > 10 files to prove recursion works
        agent_dir = tmp_path / "agent"
        bridge_dir = agent_dir / "bridge"
        services_dir = bridge_dir / "services"
        teams_dir = agent_dir / "teams"

        for d in [services_dir, teams_dir]:
            d.mkdir(parents=True)

        # Create 15 bridge files (root + subdir)
        for i in range(10):
            (bridge_dir / f"mod_{i}.py").write_text(f"# mod {i}")
        for i in range(5):
            (services_dir / f"svc_{i}.py").write_text(f"# svc {i}")
        # 3 team files
        for i in range(3):
            (teams_dir / f"team_{i}.py").write_text(f"# team {i}")

        baseline_path = tmp_path / "baseline.json"

        with patch.object(mod, "FIXED_FILES", []), \
             patch.object(mod, "BRIDGE_GLOBS", [
                 str(bridge_dir / "**" / "*.py"),
                 str(teams_dir / "**" / "*.py"),
             ]), \
             patch.object(mod, "BASELINE_PATH", baseline_path), \
             patch("pwd.getpwnam") as mock_pwd, \
             patch("os.chown"), \
             patch("os.chmod"):
            mock_pwd.return_value.pw_uid = os.getuid()
            mock_pwd.return_value.pw_gid = os.getgid()
            mod.main()

        data = json.loads(baseline_path.read_text())
        assert len(data["files"]) >= 18, f"Expected >=18 hashed files, got {len(data['files'])}"

    def test_no_old_bridge_glob_variable(self):
        """Ensure the old non-recursive BRIDGE_GLOB (singular) is removed."""
        mod = _load_module()
        assert not hasattr(mod, "BRIDGE_GLOB"), \
            "Old BRIDGE_GLOB (singular, non-recursive) should be removed"
