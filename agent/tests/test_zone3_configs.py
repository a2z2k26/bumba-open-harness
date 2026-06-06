"""Tests for Zone 3 config loading and bridge independence (#225)."""

from __future__ import annotations

from pathlib import Path



# ---------------------------------------------------------------------------
# ToolShed
# ---------------------------------------------------------------------------

class TestToolShed:
    def test_loads_from_config(self):
        from bridge.tool_shed import ToolShed
        config_path = Path(__file__).parent.parent / "config" / "tool-shed.yaml"
        shed = ToolShed(config_path)
        assert len(shed.all_tools()) >= 16

    def test_from_config_factory(self):
        from bridge.tool_shed import ToolShed
        config_path = Path(__file__).parent.parent / "config" / "tool-shed.yaml"
        shed = ToolShed.from_config(config_path)
        assert len(shed.all_tools()) >= 16

    def test_get_tools_for_agent_returns_configs(self):
        from bridge.tool_shed import ToolShed, ToolConfig
        config_path = Path(__file__).parent.parent / "config" / "tool-shed.yaml"
        shed = ToolShed.from_config(config_path)
        tools = shed.get_tools_for_agent("engineering-chief")
        assert len(tools) > 0
        assert all(isinstance(t, ToolConfig) for t in tools)

    def test_always_loaded_included(self):
        from bridge.tool_shed import ToolShed
        config_path = Path(__file__).parent.parent / "config" / "tool-shed.yaml"
        shed = ToolShed.from_config(config_path)
        # github and bumba-memory are always_loaded
        names = shed.tools_for_agent("nobody")
        assert "github" in names
        assert "bumba-memory" in names

    def test_context7_added(self):
        from bridge.tool_shed import ToolShed
        config_path = Path(__file__).parent.parent / "config" / "tool-shed.yaml"
        shed = ToolShed.from_config(config_path)
        tool = shed.get_tool("context7")
        assert tool is not None
        assert "engineering-chief" in tool.agents

    def test_missing_agents_added(self):
        from bridge.tool_shed import ToolShed
        config_path = Path(__file__).parent.parent / "config" / "tool-shed.yaml"
        shed = ToolShed.from_config(config_path)
        brave = shed.get_tool("brave-search")
        assert brave is not None
        assert "engineering-architect-reviewer" in brave.agents
        assert "engineering-refactoring-specialist" in brave.agents

    def test_no_bridge_imports(self):
        """ToolShed must be importable without bridge.app."""
        import importlib
        mod = importlib.import_module("bridge.tool_shed")
        source = Path(mod.__file__).read_text()
        assert "bridge.app" not in source
        assert "bridge.discord_bot" not in source


# ---------------------------------------------------------------------------
# QualityChain
# ---------------------------------------------------------------------------

class TestQualityChainConfig:
    def test_loads_from_yaml(self):
        from bridge.quality_chain import QualityChainConfig
        config_path = Path(__file__).parent.parent / "config" / "quality-chain.yaml"
        cfg = QualityChainConfig.from_config(config_path)
        assert len(cfg.gates) == 7
        assert cfg.coverage_threshold == 80

    def test_gate_ordering(self):
        from bridge.quality_chain import QualityChainConfig
        config_path = Path(__file__).parent.parent / "config" / "quality-chain.yaml"
        cfg = QualityChainConfig.from_config(config_path)
        levels = [g.level for g in cfg.gates]
        assert levels == sorted(levels)

    def test_architecture_is_warning_only(self):
        from bridge.quality_chain import QualityChainConfig
        config_path = Path(__file__).parent.parent / "config" / "quality-chain.yaml"
        cfg = QualityChainConfig.from_config(config_path)
        arch_gate = next(g for g in cfg.gates if g.level == 5)
        assert arch_gate.strict is False

    def test_human_approval_disabled(self):
        from bridge.quality_chain import QualityChainConfig
        config_path = Path(__file__).parent.parent / "config" / "quality-chain.yaml"
        cfg = QualityChainConfig.from_config(config_path)
        human_gate = next(g for g in cfg.gates if g.level == 7)
        assert human_gate.enabled is False

    def test_security_escalates(self):
        from bridge.quality_chain import QualityChainConfig
        config_path = Path(__file__).parent.parent / "config" / "quality-chain.yaml"
        cfg = QualityChainConfig.from_config(config_path)
        sec_gate = next(g for g in cfg.gates if g.level == 4)
        assert sec_gate.escalate_on_failure is True

    def test_missing_file_returns_defaults(self, tmp_path: Path):
        from bridge.quality_chain import QualityChainConfig
        cfg = QualityChainConfig.from_config(tmp_path / "nonexistent.yaml")
        assert len(cfg.gates) == 0
        assert cfg.coverage_threshold == 80

    def test_no_bridge_imports(self):
        import importlib
        mod = importlib.import_module("bridge.quality_chain")
        source = Path(mod.__file__).read_text()
        assert "bridge.app" not in source
        assert "bridge.discord_bot" not in source


# ---------------------------------------------------------------------------
# Synthesizer
# ---------------------------------------------------------------------------

class TestSynthesizerConfig:
    def test_loads_from_yaml(self):
        from bridge.synthesizer import SynthesizerConfig
        config_path = Path(__file__).parent.parent / "config" / "synthesizer.yaml"
        cfg = SynthesizerConfig.from_config(config_path)
        assert cfg.default_mode == "concatenate"
        assert cfg.default_merge_key == "findings"

    def test_skill_overrides(self):
        from bridge.synthesizer import SynthesizerConfig
        config_path = Path(__file__).parent.parent / "config" / "synthesizer.yaml"
        cfg = SynthesizerConfig.from_config(config_path)
        assert "code-reviewer" in cfg.skill_overrides
        assert cfg.skill_overrides["code-reviewer"]["mode"] == "structured_merge"

    def test_missing_file_returns_defaults(self, tmp_path: Path):
        from bridge.synthesizer import SynthesizerConfig
        cfg = SynthesizerConfig.from_config(tmp_path / "nonexistent.yaml")
        assert cfg.default_mode == "concatenate"


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

class TestDispatcherConfig:
    def test_from_config_factory(self):
        from bridge.dispatcher import Dispatcher
        config_path = Path(__file__).parent.parent / "config" / "dispatcher.yaml"
        d = Dispatcher.from_config(config_path)
        assert d is not None

    def test_dispatcher_yaml_exists(self):
        config_path = Path(__file__).parent.parent / "config" / "dispatcher.yaml"
        assert config_path.exists()
        content = config_path.read_text()
        assert "pydantic_ai" in content  # future-ready environment type
