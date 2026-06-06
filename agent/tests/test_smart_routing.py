"""Tests for MS3.10 — Three-Tier Smart Routing.

Covers:
- classify() with 15+ sample messages across all tiers
- Explicit @override prefixes
- strip_model_override()
- CostTracker.record(), get_daily_summary(), get_weekly_summary()
- Cost calculation accuracy (estimate_cost)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bridge.cost_tracker import CostEntry, CostTracker, estimate_cost
from bridge.model_router import classify, strip_model_override


# ======================================================================
# classify() — tier routing
# ======================================================================


class TestClassifyHaiku:
    """Messages that should route to haiku."""

    def test_greeting(self):
        assert classify("hi") == "haiku"

    def test_yes_no(self):
        assert classify("yes") == "haiku"
        assert classify("no") == "haiku"

    def test_thanks(self):
        assert classify("thanks") == "haiku"
        assert classify("thank you") == "haiku"

    def test_good_morning(self):
        assert classify("good morning") == "haiku"

    def test_status_check(self):
        assert classify("status") == "haiku"

    def test_simple_question(self):
        assert classify("what is Python?") == "haiku"

    def test_formatting_request(self):
        assert classify("format this text nicely") == "haiku"

    def test_empty_message(self):
        assert classify("") == "haiku"

    def test_short_no_indicators(self):
        assert classify("ok cool") == "haiku"

    def test_display_command(self):
        assert classify("show logs") == "haiku"


class TestClassifySonnet:
    """Messages that should route to sonnet (default tier)."""

    def test_code_review(self):
        assert classify("review this pull request and check for issues in the auth flow") == "sonnet"

    def test_analysis_request(self):
        assert classify("analyze the error logs from today and summarize the most common failures") == "sonnet"

    def test_moderate_coding(self):
        assert classify("write a function to parse CSV files with header detection") == "sonnet"

    def test_summary_request(self):
        msg = "summarize the key points from the meeting notes I sent yesterday about the product launch"
        assert classify(msg) == "sonnet"

    def test_code_block_present(self):
        msg = "what does this do?\n```python\nprint('hello')\n```"
        assert classify(msg) == "sonnet"

    def test_moderate_length(self):
        msg = "I need you to help me understand how the authentication " + "flow works " * 8
        assert classify(msg) == "sonnet"

    def test_default_fallback(self):
        # A message that doesn't match haiku or opus patterns
        msg = "I have a question about configuring the deployment pipeline for staging"
        assert classify(msg) == "sonnet"


class TestClassifyOpus:
    """Messages that should route to opus."""

    def test_architecture_decision(self):
        msg = "design the system architecture for our new microservices migration with a long-term roadmap"
        assert classify(msg) == "opus"

    def test_multi_file_refactoring(self):
        msg = "refactoring the authentication system across multiple files to use a new token format"
        assert classify(msg) == "opus"

    def test_complex_debugging(self):
        msg = "we have a race condition in the worker pool that causes a deadlock under high concurrency"
        assert classify(msg) == "opus"

    def test_creative_writing(self):
        msg = "write a short story about a robot discovering consciousness in a world where AI is feared"
        assert classify(msg) == "opus"

    def test_security_audit(self):
        msg = "perform a security audit of our API endpoints and create a threat model for the auth system"
        assert classify(msg) == "opus"

    def test_multiple_opus_signals(self):
        msg = "design a novel architecture with complex trade-offs for our migration strategy"
        assert classify(msg) == "opus"

    def test_long_multistep_with_code(self):
        msg = (
            "step 1: read all the config files\n"
            "step 2: then refactor them\n"
            "step 3: finally update tests\n"
            "```python\n# existing code\n```\n"
            + "context " * 80
        )
        assert classify(msg) == "opus"


# ======================================================================
# Explicit overrides via @prefix
# ======================================================================


class TestClassifyOverrides:
    """@haiku:, @sonnet:, @opus: prefix overrides."""

    def test_opus_override(self):
        assert classify("@opus: just say hi") == "opus"

    def test_sonnet_override(self):
        assert classify("@sonnet: design the whole architecture from scratch") == "sonnet"

    def test_haiku_override(self):
        msg = "@haiku: analyze and refactor the entire codebase with a security audit"
        assert classify(msg) == "haiku"

    def test_override_case_insensitive(self):
        assert classify("@OPUS: hello") == "opus"
        assert classify("@Sonnet: hello") == "sonnet"
        assert classify("@HAIKU: hello") == "haiku"

    def test_no_override_without_prefix(self):
        # "opus" in message body should NOT trigger override
        assert classify("I want to use opus for this") != "opus"  # it's short, haiku or sonnet


# ======================================================================
# strip_model_override()
# ======================================================================


class TestStripModelOverride:
    """strip_model_override returns (cleaned_message, tier_or_None)."""

    def test_opus_prefix(self):
        cleaned, tier = strip_model_override("@opus: refactor this code")
        assert tier == "opus"
        assert cleaned == "refactor this code"

    def test_sonnet_prefix(self):
        cleaned, tier = strip_model_override("@sonnet: what is 2+2")
        assert tier == "sonnet"
        assert cleaned == "what is 2+2"

    def test_haiku_prefix(self):
        cleaned, tier = strip_model_override("@haiku: yes")
        assert tier == "haiku"
        assert cleaned == "yes"

    def test_no_prefix(self):
        cleaned, tier = strip_model_override("just a normal message")
        assert tier is None
        assert cleaned == "just a normal message"

    def test_prefix_case_insensitive(self):
        cleaned, tier = strip_model_override("@OPUS: big task")
        assert tier == "opus"
        assert cleaned == "big task"

    def test_prefix_mid_message_ignored(self):
        # Override must be at the start
        cleaned, tier = strip_model_override("please @opus: do this")
        assert tier is None
        assert cleaned == "please @opus: do this"


# ======================================================================
# estimate_cost()
# ======================================================================


class TestEstimateCost:
    """Cost calculation with known pricing."""

    def test_haiku_cost(self):
        # 1M input + 1M output at haiku: $0.25 + $1.25 = $1.50
        cost = estimate_cost("haiku", 1_000_000, 1_000_000)
        assert abs(cost - 1.50) < 1e-6

    def test_sonnet_cost(self):
        # 1M input + 1M output at sonnet: $3 + $15 = $18
        cost = estimate_cost("sonnet", 1_000_000, 1_000_000)
        assert abs(cost - 18.0) < 1e-6

    def test_opus_cost(self):
        # 1M input + 1M output at opus: $15 + $75 = $90
        cost = estimate_cost("opus", 1_000_000, 1_000_000)
        assert abs(cost - 90.0) < 1e-6

    def test_small_request(self):
        # 1000 input, 500 output at sonnet
        cost = estimate_cost("sonnet", 1000, 500)
        expected = (1000 * 3.0 + 500 * 15.0) / 1_000_000  # 0.003 + 0.0075
        assert abs(cost - expected) < 1e-9

    def test_unknown_model_defaults_to_sonnet(self):
        cost = estimate_cost("gpt-4", 1_000_000, 1_000_000)
        assert abs(cost - 18.0) < 1e-6


# ======================================================================
# CostTracker
# ======================================================================


class TestCostTracker:
    """CostTracker record + summary."""

    @pytest.fixture
    def tracker(self, tmp_path: Path) -> CostTracker:
        return CostTracker(data_dir=tmp_path)

    def test_record_creates_file(self, tracker: CostTracker):
        tracker.record("haiku", 100, 50, task_type="test")
        assert tracker.path.exists()

    def test_record_returns_entry(self, tracker: CostTracker):
        entry = tracker.record("sonnet", 1000, 500, task_type="code_review")
        assert isinstance(entry, CostEntry)
        assert entry.model == "sonnet"
        assert entry.input_tokens == 1000
        assert entry.output_tokens == 500
        assert entry.task_type == "code_review"
        assert entry.was_override is False
        assert entry.estimated_cost > 0

    def test_record_with_override(self, tracker: CostTracker):
        entry = tracker.record("opus", 500, 200, task_type="debug", was_override=True)
        assert entry.was_override is True

    def test_record_appends_jsonl(self, tracker: CostTracker):
        tracker.record("haiku", 100, 50)
        tracker.record("sonnet", 200, 100)
        tracker.record("opus", 300, 150)
        lines = tracker.path.read_text().strip().split("\n")
        assert len(lines) == 3
        for line in lines:
            data = json.loads(line)
            assert "model" in data
            assert "estimated_cost" in data

    def test_daily_summary_empty(self, tracker: CostTracker):
        summary = tracker.get_daily_summary()
        assert summary["request_count"] == 0
        assert summary["total_cost"] == 0.0

    def test_daily_summary_with_records(self, tracker: CostTracker):
        tracker.record("haiku", 1000, 500, task_type="a")
        tracker.record("sonnet", 1000, 500, task_type="b")
        tracker.record("opus", 1000, 500, task_type="c")
        summary = tracker.get_daily_summary()
        assert summary["request_count"] == 3
        assert summary["total_cost"] > 0
        assert "haiku" in summary["by_model"]
        assert "sonnet" in summary["by_model"]
        assert "opus" in summary["by_model"]

    def test_daily_summary_by_model_counts(self, tracker: CostTracker):
        tracker.record("haiku", 100, 50)
        tracker.record("haiku", 100, 50)
        tracker.record("sonnet", 200, 100)
        summary = tracker.get_daily_summary()
        assert summary["by_model"]["haiku"]["count"] == 2
        assert summary["by_model"]["sonnet"]["count"] == 1

    def test_weekly_summary_empty(self, tracker: CostTracker):
        summary = tracker.get_weekly_summary()
        assert summary["period"] == "7d"
        assert summary["request_count"] == 0

    def test_weekly_summary_includes_recent(self, tracker: CostTracker):
        tracker.record("sonnet", 5000, 2000)
        summary = tracker.get_weekly_summary()
        assert summary["request_count"] == 1
        assert summary["total_cost"] > 0

    def test_weekly_summary_excludes_old_entries(self, tracker: CostTracker, tmp_path: Path):
        # Write an old entry manually
        old_ts = "2020-01-01T00:00:00+00:00"
        old_entry = {
            "timestamp": old_ts,
            "model": "haiku",
            "input_tokens": 999999,
            "output_tokens": 999999,
            "estimated_cost": 999.0,
            "task_type": "old",
            "was_override": False,
        }
        with open(tracker.path, "w") as f:
            f.write(json.dumps(old_entry) + "\n")
        # Add a fresh entry
        tracker.record("sonnet", 100, 50)
        summary = tracker.get_weekly_summary()
        assert summary["request_count"] == 1  # only the fresh one

    def test_cost_calculation_in_record(self, tracker: CostTracker):
        entry = tracker.record("haiku", 1_000_000, 1_000_000)
        assert abs(entry.estimated_cost - 1.50) < 1e-6

    def test_jsonl_atomic_write(self, tracker: CostTracker):
        """Verify entries are valid JSON on each line after multiple writes."""
        for i in range(10):
            tracker.record("sonnet", 100 * (i + 1), 50 * (i + 1))
        lines = tracker.path.read_text().strip().split("\n")
        assert len(lines) == 10
        for line in lines:
            json.loads(line)  # should not raise

    def test_malformed_line_skipped(self, tracker: CostTracker):
        """Malformed JSONL lines are skipped without crashing."""
        with open(tracker.path, "w") as f:
            f.write("not valid json\n")
        tracker.record("haiku", 100, 50)
        summary = tracker.get_daily_summary()
        # Only the valid record should count
        assert summary["request_count"] == 1
