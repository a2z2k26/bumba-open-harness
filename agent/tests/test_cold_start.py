"""Tests for MS1.1: Zone 1 Cold-Start Hardening."""

from __future__ import annotations

import pathlib

import pytest


BOOTSTRAP_DIR = pathlib.Path(__file__).resolve().parent.parent / "config" / "bootstrap"
BOOTSTRAP_FILES = ["SOUL.md", "AGENTS.md", "USER.md", "TOOLS.md"]


class TestBootstrapFileLoading:
    """T1.1.1: All 4 bootstrap files exist and are non-empty."""

    def test_bootstrap_directory_exists(self):
        assert BOOTSTRAP_DIR.exists(), f"Bootstrap directory missing: {BOOTSTRAP_DIR}"
        assert BOOTSTRAP_DIR.is_dir()

    @pytest.mark.parametrize("fname", BOOTSTRAP_FILES)
    def test_bootstrap_file_exists(self, fname):
        fpath = BOOTSTRAP_DIR / fname
        assert fpath.exists(), f"Bootstrap file missing: {fpath}"
        content = fpath.read_text()
        assert len(content) > 50, f"Bootstrap file too short: {fpath} ({len(content)} chars)"

    def test_bootstrap_token_budget(self):
        """Combined bootstrap files fit within token budget."""
        total_chars = 0
        for fname in BOOTSTRAP_FILES:
            fpath = BOOTSTRAP_DIR / fname
            if fpath.exists():
                total_chars += len(fpath.read_text())
        # Rough estimate: 1 token ~ 4 chars
        estimated_tokens = total_chars // 4
        assert estimated_tokens < 8000, f"Bootstrap too large: ~{estimated_tokens} tokens (max 8000)"

    def test_bootstrap_concatenation_order(self):
        """Bootstrap files concatenate in SOUL -> AGENTS -> USER -> TOOLS order."""
        combined = ""
        for fname in BOOTSTRAP_FILES:
            fpath = BOOTSTRAP_DIR / fname
            if fpath.exists():
                combined += fpath.read_text() + "\n\n---\n\n"

        # SOUL should appear before AGENTS
        soul_pos = combined.find("# Bumba")
        agents_pos = combined.find("# Sub-Agents")
        user_pos = combined.find("# Operator: the operator")
        tools_pos = combined.find("# Toolbox")

        assert soul_pos < agents_pos, "SOUL must appear before AGENTS"
        assert agents_pos < user_pos, "AGENTS must appear before USER"
        assert user_pos < tools_pos, "USER must appear before TOOLS"


class TestBootstrapContent:
    """T1.1.1: Bootstrap files contain required identity content."""

    def test_soul_contains_identity(self):
        content = (BOOTSTRAP_DIR / "SOUL.md").read_text()
        assert "Bumba" in content, "SOUL must contain agent name"
        assert "Chief of Staff" in content, "SOUL must contain role"
        assert "Zone" in content, "SOUL must contain zone architecture"
        assert "Non-negotiable" in content.lower() or "non-negotiable" in content.lower(), \
            "SOUL must contain non-negotiables"

    def test_soul_contains_principles(self):
        content = (BOOTSTRAP_DIR / "SOUL.md").read_text()
        assert "P1" in content, "SOUL must reference guiding principles"
        assert "P25" in content, "SOUL must reference all principles through P25"

    def test_soul_contains_self_improvement(self):
        content = (BOOTSTRAP_DIR / "SOUL.md").read_text()
        assert "Tier A" in content, "SOUL must contain self-improvement tiers"
        assert "Tier C" in content, "SOUL must contain all tiers"
        assert "Self-Improvement Protocol" in content, "SOUL must contain self-improvement protocol"

    def test_user_contains_operator(self):
        content = (BOOTSTRAP_DIR / "USER.md").read_text()
        assert "Example User" in content, "USER must contain operator name"
        assert "NYC" in content or "New York" in content, "USER must contain location"
        assert "EST" in content, "USER must contain timezone"
        assert "your-org" in content, "USER must contain GitHub handle"

    def test_user_contains_communication_style(self):
        content = (BOOTSTRAP_DIR / "USER.md").read_text()
        assert "Lead with answer" in content, "USER must contain communication preferences"
        assert "No preamble" in content, "USER must contain preamble rule"

    def test_agents_contains_all_four(self):
        content = (BOOTSTRAP_DIR / "AGENTS.md").read_text()
        for agent in ["Strategist", "Analyst", "Critic", "Researcher"]:
            assert agent in content, f"AGENTS must contain {agent}"

    def test_tools_contains_mcp_servers(self):
        content = (BOOTSTRAP_DIR / "TOOLS.md").read_text()
        assert "MCP Servers" in content, "TOOLS must list MCP servers"
        assert "github" in content.lower(), "TOOLS must include github server"
        assert "notion" in content.lower(), "TOOLS must include notion server"

    def test_tools_contains_commands(self):
        content = (BOOTSTRAP_DIR / "TOOLS.md").read_text()
        assert "Commands" in content, "TOOLS must list commands"
        assert "/deploy" in content, "TOOLS must include deploy command"
        assert "/validate" in content, "TOOLS must include validate command"


class TestDirectoryVerification:
    """T1.1.4: Agent directory verification."""

    def test_required_files_dict_structure(self):
        """The _REQUIRED_FILES dict is importable and well-structured."""
        from bridge.app import BridgeApp
        rf = BridgeApp._REQUIRED_FILES
        assert "critical" in rf
        assert "warning" in rf
        assert isinstance(rf["critical"], list)
        assert isinstance(rf["warning"], list)
        assert len(rf["critical"]) > 0
        assert len(rf["warning"]) > 0

    def test_critical_files_listed(self):
        from bridge.app import BridgeApp
        critical = BridgeApp._REQUIRED_FILES["critical"]
        assert any("SOUL.md" in f for f in critical), "SOUL.md must be critical"
        assert any("kernel-baseline" in f for f in critical), "kernel-baseline must be critical"


class TestZoneKnowledgeEntries:
    """T1.1.3: Zone architecture encoded in knowledge."""

    @pytest.mark.asyncio
    async def test_zone_entries_searchable(self, memory, migrated_db):
        """Zone entries should be storable and searchable."""
        await memory.store_knowledge(
            "zone:architecture",
            "Concentric zones radiating outward: Zone 1 -> Zone 2 -> Zone 3 -> Zone 4",
            tags="zone,architecture",
            category="process",
            source="zone-plan",
        )
        results = await memory.search_knowledge("zone")
        assert len(results) >= 1
        assert any("zone:architecture" == r["key"] for r in results)

    @pytest.mark.asyncio
    async def test_zone_identity_searchable(self, memory, migrated_db):
        await memory.store_knowledge(
            "zone:1:identity",
            "Zone 1 — Core Identity. Soul, rhythm, guiding principles.",
            tags="zone,identity",
            category="process",
            source="zone-plan",
        )
        results = await memory.search_knowledge("identity")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_zone_rules_searchable(self, memory, migrated_db):
        await memory.store_knowledge(
            "zone:rules",
            "Architecture design rules: each zone is a prerequisite for the next.",
            tags="zone,rules",
            category="process",
            source="zone-plan",
        )
        results = await memory.search_knowledge("architecture rules")
        assert len(results) >= 1
