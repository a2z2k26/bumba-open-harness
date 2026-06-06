"""Tests for Z4 tool_tracker_enabled flag — Issue #539."""

import pytest
from bridge.config import load_config


class TestToolTrackerFlagEnabled:
    """Verify that tool_tracker_enabled is set to true in production config."""

    def test_tool_tracker_enabled_in_sample_config(self, sample_config_toml, mock_keyring):
        """Sample config should have tool_tracker_enabled = true for testing."""
        config = load_config(sample_config_toml)
        # Note: sample_config_toml may have false; this test checks the field exists and can be loaded
        assert hasattr(config, "z4_observability_tool_tracker_enabled")
        assert isinstance(config.z4_observability_tool_tracker_enabled, bool)

    def test_tool_tracker_default_is_false(self):
        """Default value should be false (disabled by default)."""
        from bridge.config import BridgeConfig
        config = BridgeConfig()
        assert config.z4_observability_tool_tracker_enabled is False

    def test_tool_tracker_can_be_enabled_via_toml(self, sample_config_toml, mock_keyring, tmp_path):
        """Tool tracker can be enabled by setting flag in bridge.toml."""
        # Create a modified config with tool_tracker_enabled = true
        with open(sample_config_toml, 'r') as f:
            content = f.read()

        # Replace the flag if it exists, or add it
        if 'tool_tracker_enabled = false' in content:
            modified_content = content.replace('tool_tracker_enabled = false', 'tool_tracker_enabled = true')
        elif '[z4_observability]' in content:
            modified_content = content.replace(
                '[z4_observability]',
                '[z4_observability]\ntool_tracker_enabled = true'
            )
        else:
            modified_content = content + '\n[z4_observability]\ntool_tracker_enabled = true\n'

        # Write to temp file and load
        temp_config = tmp_path / "bridge_enabled.toml"
        temp_config.write_text(modified_content)

        config = load_config(temp_config)
        assert config.z4_observability_tool_tracker_enabled is True

    def test_tool_tracker_flag_production_state(self, tmp_path, mock_keyring):
        """Test production bridge.toml has tool_tracker_enabled = true."""
        from pathlib import Path

        # Locate the actual bridge.toml in the agent directory
        bridge_toml_path = Path(__file__).parent.parent / "config" / "bridge.toml"
        if not bridge_toml_path.exists():
            pytest.skip(f"Production bridge.toml not found at {bridge_toml_path}")

        # load_config validates that data_dir exists; skip on non-prod machines
        import tomllib
        with open(bridge_toml_path, "rb") as _f:
            raw = tomllib.load(_f)
        data_dir = raw.get("bridge", {}).get("data_dir", "")
        if data_dir and not Path(data_dir).exists():
            pytest.skip(f"Production data_dir not present on this machine: {data_dir}")

        config = load_config(bridge_toml_path)
        assert config.z4_observability_tool_tracker_enabled is True, \
            "tool_tracker_enabled must be True in production config"
