"""Tests for compound pressure detection (budget + context)."""
from __future__ import annotations

from bridge.compound_pressure import should_auto_compact


class TestCompoundPressure:
    def test_both_ok_returns_false(self):
        assert not should_auto_compact(budget_level="ok", context_recommendation="ok")

    def test_budget_critical_context_ok_returns_false(self):
        # Budget alone isn't enough — context must also be stressed
        assert not should_auto_compact(budget_level="critical", context_recommendation="ok")

    def test_budget_ok_context_compact_returns_false(self):
        # Context alone isn't enough — budget must also be stressed
        assert not should_auto_compact(budget_level="ok", context_recommendation="compact_now")

    def test_both_warning_returns_true(self):
        assert should_auto_compact(budget_level="warning", context_recommendation="warn")

    def test_budget_critical_context_warn_returns_true(self):
        assert should_auto_compact(budget_level="critical", context_recommendation="warn")

    def test_both_critical_returns_true(self):
        assert should_auto_compact(budget_level="critical", context_recommendation="critical")
