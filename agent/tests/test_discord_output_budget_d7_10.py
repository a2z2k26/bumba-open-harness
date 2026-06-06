"""Tests for D7.10 — pre-emptive output-length budget for Discord (#1422)."""
from __future__ import annotations

from bridge.config import BridgeConfig


def test_default_discord_output_target_is_1800() -> None:
    """Default leaves headroom under the 2000-char free-account Discord cap."""
    cfg = BridgeConfig(data_dir="/tmp/test")
    assert cfg.discord_output_target_chars == 1800


def test_discord_output_target_can_be_disabled_via_zero() -> None:
    """Setting to 0 in TOML disables the hint (per docstring contract)."""
    cfg = BridgeConfig(data_dir="/tmp/test", discord_output_target_chars=0)
    assert cfg.discord_output_target_chars == 0


def test_discord_output_target_accepts_custom_value() -> None:
    """Operator can tune the cap (e.g. for Nitro accounts)."""
    cfg = BridgeConfig(data_dir="/tmp/test", discord_output_target_chars=3500)
    assert cfg.discord_output_target_chars == 3500


def test_toml_map_contains_discord_output_target_key() -> None:
    """TOML key resolves to the new field via _TOML_MAP."""
    from bridge.config import _TOML_MAP
    assert "discord.output_target_chars" in _TOML_MAP
    assert _TOML_MAP["discord.output_target_chars"] == "discord_output_target_chars"


def test_app_py_appends_budget_hint_to_context() -> None:
    """Source-level smoke: the budget-hint string template lands in the pipeline.

    Avoids the cost of a full BridgeApp fixture by reading source and
    confirming the hint template is wired in. Sprint P6.1 (#1591) moved
    the wiring out of ``app.py`` into ``bridge/invocation_pipeline.py``;
    we now scan the combined text of both files.
    """
    from pathlib import Path
    bridge = Path(__file__).resolve().parents[1] / "bridge"
    content = (bridge / "app.py").read_text(encoding="utf-8") + "\n" + (
        bridge / "invocation_pipeline.py"
    ).read_text(encoding="utf-8")
    assert "OUTPUT BUDGET (Discord)" in content
    assert "discord_output_target_chars" in content
    # Hint must be guarded — disabled when target is 0
    assert "_discord_target > 0" in content
