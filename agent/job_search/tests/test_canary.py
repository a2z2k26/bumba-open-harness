"""Tests for the post-submit funnel canary (Z2-S2.5)."""
from __future__ import annotations


from job_search.canary import (
    CanaryAlert,
    CanaryDedupe,
    check_funnel_canary,
    DEDUP_SCRAPE_THRESHOLD,
)
from job_search.funnel import FunnelDay


# ---------------------------------------------------------------------------
# check_funnel_canary — pure function tests
# ---------------------------------------------------------------------------

class TestCheckFunnelCanary:
    # --- submitted_no_stage ---

    def test_submitted_no_stage_fires(self):
        day = FunnelDay(scraped=50, deduped=30, covered=12, submitted=12, staged=0)
        alert = check_funnel_canary(day)
        assert alert is not None
        assert alert.tag == "submitted_no_stage"

    def test_submitted_with_stage_does_not_fire(self):
        day = FunnelDay(scraped=50, deduped=30, covered=12, submitted=12, staged=12)
        alert = check_funnel_canary(day)
        assert alert is None

    def test_zero_submitted_does_not_fire_submitted_no_stage(self):
        day = FunnelDay(scraped=50, deduped=30, covered=0, submitted=0, staged=0)
        alert = check_funnel_canary(day)
        # No covered means covered_no_submit doesn't fire either
        assert alert is None

    # --- dedup_dropped_all ---

    def test_dedup_dropped_all_fires_above_threshold(self):
        day = FunnelDay(scraped=DEDUP_SCRAPE_THRESHOLD + 1, deduped=0)
        alert = check_funnel_canary(day)
        assert alert is not None
        assert alert.tag == "dedup_dropped_all"

    def test_dedup_dropped_all_does_not_fire_below_threshold(self):
        # Only 10 scraped and 0 deduped — scrape count too low to be anomalous
        day = FunnelDay(scraped=10, deduped=0)
        alert = check_funnel_canary(day)
        assert alert is None

    def test_dedup_dropped_all_does_not_fire_when_deduped_gt_zero(self):
        day = FunnelDay(scraped=100, deduped=80)
        alert = check_funnel_canary(day)
        assert alert is None

    def test_custom_dedup_threshold(self):
        day = FunnelDay(scraped=5, deduped=0)
        alert = check_funnel_canary(day, dedup_scrape_threshold=4)
        assert alert is not None
        assert alert.tag == "dedup_dropped_all"

    # --- covered_no_submit ---

    def test_covered_no_submit_fires(self):
        day = FunnelDay(scraped=50, deduped=30, covered=15, submitted=0)
        alert = check_funnel_canary(day)
        assert alert is not None
        assert alert.tag == "covered_no_submit"

    def test_covered_with_submit_does_not_fire(self):
        day = FunnelDay(scraped=50, deduped=30, covered=15, submitted=10, staged=10)
        alert = check_funnel_canary(day)
        assert alert is None

    def test_zero_covered_does_not_fire_covered_no_submit(self):
        day = FunnelDay(scraped=50, deduped=30, covered=0, submitted=0, staged=0)
        alert = check_funnel_canary(day)
        assert alert is None

    # --- zero activity day ---

    def test_zero_activity_returns_none(self):
        day = FunnelDay()
        assert check_funnel_canary(day) is None

    def test_all_zeros_returns_none(self):
        day = FunnelDay(scraped=0, deduped=0, covered=0, submitted=0, staged=0)
        assert check_funnel_canary(day) is None

    # --- priority: submitted_no_stage fires before covered_no_submit ---

    def test_submitted_no_stage_takes_priority(self):
        # Both submitted_no_stage AND covered_no_submit conditions met.
        # submitted_no_stage is checked first → should fire that one.
        day = FunnelDay(scraped=60, deduped=30, covered=10, submitted=5, staged=0)
        alert = check_funnel_canary(day)
        assert alert is not None
        assert alert.tag == "submitted_no_stage"

    # --- partial stage (should NOT fire) ---

    def test_partial_staging_does_not_fire(self):
        # 10 submitted, 2 staged — partial is OK per spec
        day = FunnelDay(scraped=60, deduped=40, covered=15, submitted=10, staged=2)
        alert = check_funnel_canary(day)
        assert alert is None

    # --- alert content ---

    def test_alert_has_tag_and_message(self):
        day = FunnelDay(scraped=60, deduped=30, covered=15, submitted=12, staged=0)
        alert = check_funnel_canary(day)
        assert isinstance(alert, CanaryAlert)
        assert len(alert.tag) > 0
        assert len(alert.message) > 0

    def test_message_includes_counter_values(self):
        day = FunnelDay(scraped=60, deduped=30, covered=15, submitted=12, staged=0)
        alert = check_funnel_canary(day)
        assert "12" in alert.message  # submitted count


# ---------------------------------------------------------------------------
# CanaryDedupe — store tests
# ---------------------------------------------------------------------------

class TestCanaryDedupe:
    def test_first_fire_should_fire(self, tmp_path):
        dedup = CanaryDedupe(tmp_path)
        assert dedup.should_fire("2026-04-17", "submitted_no_stage") is True

    def test_after_record_should_not_fire(self, tmp_path):
        dedup = CanaryDedupe(tmp_path)
        dedup.record("2026-04-17", "submitted_no_stage")
        assert dedup.should_fire("2026-04-17", "submitted_no_stage") is False

    def test_different_date_fires_again(self, tmp_path):
        dedup = CanaryDedupe(tmp_path)
        dedup.record("2026-04-17", "submitted_no_stage")
        assert dedup.should_fire("2026-04-18", "submitted_no_stage") is True

    def test_different_tag_fires_again(self, tmp_path):
        dedup = CanaryDedupe(tmp_path)
        dedup.record("2026-04-17", "submitted_no_stage")
        assert dedup.should_fire("2026-04-17", "covered_no_submit") is True

    def test_record_persists_across_instances(self, tmp_path):
        dedup1 = CanaryDedupe(tmp_path)
        dedup1.record("2026-04-17", "submitted_no_stage")
        dedup2 = CanaryDedupe(tmp_path)
        assert dedup2.should_fire("2026-04-17", "submitted_no_stage") is False

    def test_corrupted_file_resets_gracefully(self, tmp_path):
        state_dir = tmp_path / "service_state"
        state_dir.mkdir()
        (state_dir / "canary_alerts.json").write_text("{{NOT JSON")
        dedup = CanaryDedupe(tmp_path)
        # Should not raise
        assert dedup.should_fire("2026-04-17", "any_tag") is True
