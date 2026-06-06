"""Unit tests for advanced_memory package — dual_write pipeline.

Hindsight/obsidian coverage removed by P2.3 partial-delete (#1719); see
``agent/bridge/advanced_memory/__init__.py`` docstring for scope.

Sprint Mem-4 (#1845) retrofitted the dual-write surface — the previous
``write(category, content, ...)`` signature targeted a fictitious schema and
had no production callers. The new contract is keyword-only with
``(key, value, tier, destinations, ...)`` against the real ``knowledge``
table. See ``tests/test_dual_write_wiring.py`` for the integrated tests that
also cover the ``KnowledgeMixin`` wire and tier-policy routing.
"""
from __future__ import annotations

import pytest

from bridge.advanced_memory.dual_write import DualWritePipeline, DualWriteResult


class _RecordingDestination:
    """Test double — records write kwargs, optionally raises."""

    def __init__(self, name: str, raise_on_write: Exception | None = None) -> None:
        self.name = name
        self.calls: list[dict] = []
        self._raise = raise_on_write

    async def write(self, **kwargs) -> str:  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        if self._raise is not None:
            raise self._raise
        return f"{self.name}:{kwargs['key']}"


# ---------------------------------------------------------------------------
# DualWriteResult shape
# ---------------------------------------------------------------------------

class TestDualWriteResult:
    def test_frozen(self):
        dwr = DualWriteResult(primary_success=True, secondary_success=False)
        with pytest.raises(AttributeError):
            dwr.primary_success = False  # type: ignore[misc]

    def test_defaults(self):
        dwr = DualWriteResult(primary_success=True, secondary_success=True)
        assert dwr.primary_id == ""
        assert dwr.secondary_id == ""
        assert dwr.error == ""


# ---------------------------------------------------------------------------
# DualWritePipeline behaviour against the Mem-4 contract
# ---------------------------------------------------------------------------

class TestDualWritePipeline:
    @pytest.mark.asyncio
    async def test_primary_only_write(self):
        """Primary-only destinations tuple → only primary fires; secondary
        success is False on the result (no secondary attempted)."""
        primary = _RecordingDestination("sqlite")
        pipeline = DualWritePipeline(destinations={"sqlite": primary})
        result = await pipeline.write(
            key="k1", value="content", tier="context",
            destinations=("sqlite",),
        )
        assert result.primary_success is True
        assert result.secondary_success is False
        assert result.primary_id == "sqlite:k1"
        assert len(primary.calls) == 1

    @pytest.mark.asyncio
    async def test_dual_write_success(self):
        """Primary + one secondary both succeed → both flags True on result."""
        primary = _RecordingDestination("sqlite")
        secondary = _RecordingDestination("second_brain")
        pipeline = DualWritePipeline(
            destinations={"sqlite": primary, "second_brain": secondary},
        )
        result = await pipeline.write(
            key="k2", value="chose X over Y", source="session-1",
            tier="preference", destinations=("sqlite", "second_brain"),
        )
        assert result.primary_success is True
        assert result.secondary_success is True
        assert result.secondary_id == "second_brain:k2"

    @pytest.mark.asyncio
    async def test_secondary_failure_is_best_effort(self):
        """Secondary raising → primary still succeeds, error captured on result."""
        primary = _RecordingDestination("sqlite")
        secondary = _RecordingDestination(
            "second_brain", raise_on_write=ConnectionError("offline"),
        )
        pipeline = DualWritePipeline(
            destinations={"sqlite": primary, "second_brain": secondary},
        )
        result = await pipeline.write(
            key="k3", value="test", tier="preference",
            destinations=("sqlite", "second_brain"),
        )
        assert result.primary_success is True
        assert result.secondary_success is False
        assert "offline" in result.error

    @pytest.mark.asyncio
    async def test_primary_failure_raises(self):
        """Primary raising → exception propagates, no result returned."""
        primary = _RecordingDestination(
            "sqlite", raise_on_write=RuntimeError("DB down"),
        )
        pipeline = DualWritePipeline(destinations={"sqlite": primary})
        with pytest.raises(RuntimeError, match="DB down"):
            await pipeline.write(
                key="k4", value="test", tier="context",
                destinations=("sqlite",),
            )
