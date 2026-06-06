"""Tests for Codex-6 (#1840) — per-backend cost tracking + /cost UI extension.

Per the #1841 operator broadcast:
- Claude turns continue tracking ``estimated_cost`` via the existing
  per-token PRICING table (Anthropic API is per-token billed).
- Codex turns are subscription-billed — ``estimated_cost`` is forced
  to ``0.0`` regardless of token counts, and the ``/cost`` UI surfaces
  ``subscription-billed`` instead of a misleading ``$0.00`` figure.
- Token counts are still recorded for Codex so the operator can see
  utilization without a (fake) dollar figure.

Coverage:
- ``CostEntry.backend`` field round-trips through JSONL
- Legacy entries without ``backend`` parse cleanly and bucket as
  ``"claude"`` in the new ``by_backend`` aggregate (historical accuracy:
  every pre-Codex entry was Claude)
- ``record(backend="codex", ...)`` forces ``estimated_cost = 0.0``
  regardless of token math
- ``get_daily_summary()`` and ``get_weekly_summary()`` both surface
  ``by_backend`` with ``{cost, count, input_tokens, output_tokens}``
- ``CostAndZ4Mixin._append_backend_breakdown`` renders Claude as a
  dollar figure and Codex as ``subscription-billed`` (never ``$0.00``)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bridge.command_handlers.cost_and_z4 import CostAndZ4Mixin
from bridge.cost_tracker import CostEntry, CostTracker


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture()
def tracker(tmp_path: Path) -> CostTracker:
    return CostTracker(data_dir=tmp_path)


# ---------------------------------------------------------------------
# CostEntry.backend field
# ---------------------------------------------------------------------


class TestCostEntryBackendField:
    def test_default_is_empty_string(self) -> None:
        entry = CostEntry(
            timestamp="2026-05-12T12:00:00+00:00",
            model="sonnet",
            input_tokens=10,
            output_tokens=5,
            estimated_cost=0.0,
            task_type="",
            was_override=False,
        )
        assert entry.backend == ""

    def test_round_trip_through_jsonl_claude(self, tracker: CostTracker) -> None:
        tracker.record(
            model="sonnet",
            input_tokens=100,
            output_tokens=50,
            backend="claude",
        )
        raw = tracker.path.read_text(encoding="utf-8").strip()
        data = json.loads(raw)
        assert data["backend"] == "claude"
        # Claude cost still uses per-token PRICING math.
        assert data["estimated_cost"] > 0.0

        entries = tracker._read_entries()
        assert len(entries) == 1
        assert entries[0].backend == "claude"

    def test_round_trip_through_jsonl_codex(self, tracker: CostTracker) -> None:
        tracker.record(
            model="gpt-5-codex",
            input_tokens=100,
            output_tokens=50,
            backend="codex",
        )
        raw = tracker.path.read_text(encoding="utf-8").strip()
        data = json.loads(raw)
        assert data["backend"] == "codex"
        # Codex is subscription-billed — cost MUST be 0.0 regardless
        # of model name / token counts. Per #1841 broadcast.
        assert data["estimated_cost"] == 0.0
        # But token counts are still preserved for visibility.
        assert data["input_tokens"] == 100
        assert data["output_tokens"] == 50


# ---------------------------------------------------------------------
# Backward compatibility — legacy JSONL without `backend`
# ---------------------------------------------------------------------


class TestBackendBackwardCompatibility:
    def test_legacy_jsonl_without_backend_parses(self, tracker: CostTracker) -> None:
        legacy_line = json.dumps({
            "timestamp": "2026-03-01T00:00:00+00:00",
            "model": "sonnet",
            "input_tokens": 100,
            "output_tokens": 50,
            "estimated_cost": 0.00125,
            "task_type": "chat",
            "was_override": False,
            "agent_id": "",
            "feature": "",
            "session_id": "",
        })
        tracker.path.write_text(legacy_line + "\n", encoding="utf-8")

        entries = tracker._read_entries()
        assert len(entries) == 1
        assert entries[0].backend == ""  # default for legacy rows

    def test_legacy_entries_bucket_as_claude_in_by_backend(
        self, tracker: CostTracker
    ) -> None:
        """Empty backend → bucket as 'claude' (historical accuracy)."""
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        legacy_line = json.dumps({
            "timestamp": f"{today}T12:00:00+00:00",
            "model": "sonnet",
            "input_tokens": 100,
            "output_tokens": 50,
            "estimated_cost": 0.00125,
            "task_type": "chat",
            "was_override": False,
            "agent_id": "",
            "feature": "",
            "session_id": "",
        })
        tracker.path.write_text(legacy_line + "\n", encoding="utf-8")

        daily = tracker.get_daily_summary()
        assert "by_backend" in daily
        assert "claude" in daily["by_backend"]
        assert daily["by_backend"]["claude"]["count"] == 1
        assert daily["by_backend"]["claude"]["input_tokens"] == 100
        assert daily["by_backend"]["claude"]["output_tokens"] == 50


# ---------------------------------------------------------------------
# Codex cost forcing
# ---------------------------------------------------------------------


class TestCodexCostForcedToZero:
    def test_codex_record_forces_cost_zero_even_for_known_model(
        self, tracker: CostTracker
    ) -> None:
        """If backend=codex, cost is 0.0 even if model name is in PRICING."""
        # sonnet would normally bill ~$0.001050 for 100 in / 50 out
        entry = tracker.record(
            model="sonnet",
            input_tokens=100,
            output_tokens=50,
            backend="codex",
        )
        assert entry.estimated_cost == 0.0

    def test_claude_record_uses_pricing_table(self, tracker: CostTracker) -> None:
        entry = tracker.record(
            model="sonnet",
            input_tokens=100,
            output_tokens=50,
            backend="claude",
        )
        assert entry.estimated_cost > 0.0

    def test_empty_backend_uses_pricing_table(self, tracker: CostTracker) -> None:
        """Empty backend (pre-Codex-6 callers) preserves Claude semantics."""
        entry = tracker.record(
            model="sonnet",
            input_tokens=100,
            output_tokens=50,
        )
        assert entry.backend == ""
        assert entry.estimated_cost > 0.0


# ---------------------------------------------------------------------
# Aggregation — daily + weekly
# ---------------------------------------------------------------------


class TestByBackendAggregation:
    def test_daily_summary_has_by_backend_with_mixed_entries(
        self, tracker: CostTracker
    ) -> None:
        tracker.record(model="sonnet", input_tokens=100, output_tokens=50, backend="claude")
        tracker.record(model="haiku", input_tokens=20, output_tokens=10, backend="claude")
        tracker.record(model="gpt-5-codex", input_tokens=200, output_tokens=80, backend="codex")
        tracker.record(model="gpt-5-codex", input_tokens=400, output_tokens=120, backend="codex")

        daily = tracker.get_daily_summary()
        bk = daily["by_backend"]
        assert set(bk.keys()) == {"claude", "codex"}

        # Claude rolls up cost + tokens
        assert bk["claude"]["count"] == 2
        assert bk["claude"]["input_tokens"] == 120
        assert bk["claude"]["output_tokens"] == 60
        assert bk["claude"]["cost"] > 0.0

        # Codex rolls up tokens, cost stays zero
        assert bk["codex"]["count"] == 2
        assert bk["codex"]["input_tokens"] == 600
        assert bk["codex"]["output_tokens"] == 200
        assert bk["codex"]["cost"] == 0.0

    def test_weekly_summary_has_by_backend(self, tracker: CostTracker) -> None:
        tracker.record(model="sonnet", input_tokens=100, output_tokens=50, backend="claude")
        tracker.record(model="gpt-5-codex", input_tokens=200, output_tokens=80, backend="codex")

        weekly = tracker.get_weekly_summary()
        assert "by_backend" in weekly
        assert set(weekly["by_backend"].keys()) == {"claude", "codex"}

    def test_by_model_unchanged_alongside_by_backend(self, tracker: CostTracker) -> None:
        """Existing per-model keying preserved — no regression for Claude-only operators."""
        tracker.record(model="sonnet", input_tokens=100, output_tokens=50, backend="claude")
        tracker.record(model="haiku", input_tokens=20, output_tokens=10, backend="claude")

        daily = tracker.get_daily_summary()
        assert "sonnet" in daily["by_model"]
        assert "haiku" in daily["by_model"]
        assert daily["by_model"]["sonnet"]["count"] == 1
        assert daily["by_model"]["haiku"]["count"] == 1


# ---------------------------------------------------------------------
# /cost UI rendering — _append_backend_breakdown
# ---------------------------------------------------------------------


class TestBackendBreakdownRendering:
    def test_empty_by_backend_renders_nothing(self) -> None:
        lines: list[str] = []
        CostAndZ4Mixin._append_backend_breakdown(lines, {})
        assert lines == []

    def test_claude_only_renders_dollar_figure(self) -> None:
        lines: list[str] = []
        CostAndZ4Mixin._append_backend_breakdown(
            lines,
            {"claude": {"cost": 0.0123, "count": 5, "input_tokens": 1234, "output_tokens": 567}},
        )
        joined = "\n".join(lines)
        assert "Backend breakdown:" in joined
        assert "claude" in joined
        assert "$0.0123" in joined
        assert "5 requests" in joined
        assert "1,234 in" in joined
        assert "567 out" in joined

    def test_codex_renders_subscription_billed_not_dollar_zero(self) -> None:
        """Codex MUST surface honest language — never '$0.00'."""
        lines: list[str] = []
        CostAndZ4Mixin._append_backend_breakdown(
            lines,
            {"codex": {"cost": 0.0, "count": 3, "input_tokens": 456, "output_tokens": 123}},
        )
        joined = "\n".join(lines)
        assert "subscription-billed" in joined
        # The hard constraint: no $0.00 leak.
        assert "$0.00" not in joined
        assert "3 turns" in joined  # codex uses "turns" not "requests"
        assert "456 in" in joined
        assert "123 out" in joined

    def test_mixed_backends_render_both_styles(self) -> None:
        lines: list[str] = []
        CostAndZ4Mixin._append_backend_breakdown(
            lines,
            {
                "claude": {"cost": 0.05, "count": 10, "input_tokens": 5000, "output_tokens": 2500},
                "codex": {"cost": 0.0, "count": 4, "input_tokens": 800, "output_tokens": 200},
            },
        )
        joined = "\n".join(lines)
        assert "$0.0500" in joined          # claude line, dollars
        assert "subscription-billed" in joined  # codex line, honest
        # Hard constraint again — no fake-dollar leak for the codex line.
        assert "$0.00 " not in joined
        assert "10 requests" in joined
        assert "4 turns" in joined
