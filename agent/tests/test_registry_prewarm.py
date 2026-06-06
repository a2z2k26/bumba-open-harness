"""Tests for DepartmentRegistry.prewarm() — sprint E-O.6."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch


from teams._registry import DepartmentRegistry
from teams._types import (
    AgentSpec,
    Budget,
    Constraints,
    DepartmentConfig,
    VAPIReceptionist,
)


def _make_config(name: str) -> DepartmentConfig:
    mgr = AgentSpec(name=f"{name}-chief", model="gpt-4o-mini")
    return DepartmentConfig(
        name=name,
        zone=4,
        description=f"Test department {name}",
        manager=mgr,
        employees=(mgr,),
        constraints=Constraints(),
        budget=Budget(),
        vapi=VAPIReceptionist(),
    )


def _registry_with(*names: str) -> DepartmentRegistry:
    configs = {n: _make_config(n) for n in names}
    return DepartmentRegistry(configs=configs)


class TestPrewarm:
    def test_prewarm_builds_all_teams(self) -> None:
        """prewarm() populates _teams for every config entry."""
        registry = _registry_with("engineering", "qa", "ops")

        with patch("teams._registry.DepartmentTeam") as MockTeam:
            MockTeam.return_value = MagicMock()
            registry.prewarm()

        assert set(registry._teams.keys()) == {"engineering", "qa", "ops"}

    def test_prewarm_skips_already_built(self) -> None:
        """prewarm() does not rebuild teams that are already in _teams."""
        registry = _registry_with("engineering", "qa")

        existing_team = MagicMock()
        registry._teams["engineering"] = existing_team

        with patch("teams._registry.DepartmentTeam") as MockTeam:
            MockTeam.return_value = MagicMock()
            registry.prewarm()

        # engineering was skipped — MockTeam called only once (for qa)
        assert MockTeam.call_count == 1
        assert registry._teams["engineering"] is existing_team

    def test_prewarm_idempotent(self) -> None:
        """Calling prewarm() twice does not double-build teams."""
        registry = _registry_with("engineering")

        with patch("teams._registry.DepartmentTeam") as MockTeam:
            MockTeam.return_value = MagicMock()
            registry.prewarm()
            registry.prewarm()

        assert MockTeam.call_count == 1

    def test_prewarm_survives_broken_department(self) -> None:
        """A config that raises during team build must not abort prewarm for others."""
        registry = _registry_with("good", "broken")

        good_team = MagicMock()

        def _side_effect(config, **kwargs: Any) -> MagicMock:
            if config.name == "broken":
                raise RuntimeError("bad config")
            return good_team

        with patch("teams._registry.DepartmentTeam", side_effect=_side_effect):
            # Should not raise
            registry.prewarm()

        # good was built, broken was not
        assert "good" in registry._teams
        assert "broken" not in registry._teams

    def test_prewarm_empty_registry(self) -> None:
        """prewarm() on an empty registry is a no-op."""
        registry = DepartmentRegistry(configs={})
        registry.prewarm()  # must not raise
        assert registry._teams == {}
