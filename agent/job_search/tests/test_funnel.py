"""Tests for the job-search funnel store (Z2-S2.1)."""
from __future__ import annotations

import json


from job_search.funnel import (
    FunnelDay,
    FunnelStore,
    STAGE_ORDER,
    format_funnel_discord,
    today_key,
)


# ---------------------------------------------------------------------------
# FunnelDay — unit tests
# ---------------------------------------------------------------------------

class TestFunnelDay:
    def test_defaults_are_zero(self):
        day = FunnelDay()
        for stage in STAGE_ORDER:
            assert getattr(day, stage) == 0

    def test_bump_known_stage(self):
        day = FunnelDay()
        day.bump("scraped", 10)
        assert day.scraped == 10

    def test_bump_accumulates(self):
        day = FunnelDay()
        day.bump("scraped", 5)
        day.bump("scraped", 7)
        assert day.scraped == 12

    def test_bump_default_count_is_1(self):
        day = FunnelDay()
        day.bump("deduped")
        assert day.deduped == 1

    def test_bump_unknown_stage_goes_to_extras(self):
        day = FunnelDay()
        day.bump("custom_stage", 3)
        assert day.extras["custom_stage"] == 3

    def test_round_trip_via_dict(self):
        day = FunnelDay(scraped=50, deduped=40, covered=10, staged=8)
        restored = FunnelDay.from_dict(day.to_dict())
        assert restored.scraped == 50
        assert restored.deduped == 40
        assert restored.covered == 10
        assert restored.staged == 8

    def test_from_dict_missing_fields_default_zero(self):
        day = FunnelDay.from_dict({"scraped": 5})
        assert day.scraped == 5
        assert day.deduped == 0

    def test_from_dict_preserves_extras(self):
        d = {"scraped": 1, "my_custom_field": 99}
        day = FunnelDay.from_dict(d)
        assert day.extras.get("my_custom_field") == 99


# ---------------------------------------------------------------------------
# FunnelStore — integration tests (using tmp_path)
# ---------------------------------------------------------------------------

class TestFunnelStore:
    def test_get_returns_zeroed_day_for_unknown_date(self, tmp_path):
        store = FunnelStore(tmp_path)
        day = store.get("2026-04-17")
        assert day.scraped == 0

    def test_bump_persists(self, tmp_path):
        store = FunnelStore(tmp_path)
        store.bump("2026-04-17", "scraped", 45)
        day = store.get("2026-04-17")
        assert day.scraped == 45

    def test_bump_accumulates_across_calls(self, tmp_path):
        store = FunnelStore(tmp_path)
        store.bump("2026-04-17", "scraped", 20)
        store.bump("2026-04-17", "scraped", 25)
        day = store.get("2026-04-17")
        assert day.scraped == 45

    def test_multiple_dates_independent(self, tmp_path):
        store = FunnelStore(tmp_path)
        store.bump("2026-04-17", "scraped", 10)
        store.bump("2026-04-18", "scraped", 20)
        assert store.get("2026-04-17").scraped == 10
        assert store.get("2026-04-18").scraped == 20

    def test_all_dates_sorted(self, tmp_path):
        store = FunnelStore(tmp_path)
        store.bump("2026-04-19", "scraped", 1)
        store.bump("2026-04-17", "scraped", 1)
        store.bump("2026-04-18", "scraped", 1)
        assert store.all_dates() == ["2026-04-17", "2026-04-18", "2026-04-19"]

    def test_set_day_overwrites(self, tmp_path):
        store = FunnelStore(tmp_path)
        store.bump("2026-04-17", "scraped", 100)
        new_day = FunnelDay(scraped=5)
        store.set_day("2026-04-17", new_day)
        assert store.get("2026-04-17").scraped == 5

    def test_corrupted_file_resets_gracefully(self, tmp_path):
        state_dir = tmp_path / "service_state"
        state_dir.mkdir()
        (state_dir / "funnel.json").write_text("NOT VALID JSON{{")
        store = FunnelStore(tmp_path)
        # Should not raise; returns zeroed day
        day = store.get("2026-04-17")
        assert day.scraped == 0

    def test_concurrent_bumps_final_count(self, tmp_path):
        """Simulate 20 sequential bump() calls — final counter must be 20."""
        store = FunnelStore(tmp_path)
        for _ in range(20):
            store.bump("2026-04-17", "scraped", 1)
        assert store.get("2026-04-17").scraped == 20

    def test_state_dir_created_if_missing(self, tmp_path):
        new_dir = tmp_path / "nested" / "data"
        store = FunnelStore(new_dir)
        store.bump("2026-04-17", "scraped", 1)
        assert (new_dir / "service_state" / "funnel.json").exists()

    def test_json_is_valid_after_bump(self, tmp_path):
        store = FunnelStore(tmp_path)
        store.bump("2026-04-17", "covered", 3)
        funnel_path = tmp_path / "service_state" / "funnel.json"
        data = json.loads(funnel_path.read_text())
        assert "2026-04-17" in data
        assert data["2026-04-17"]["covered"] == 3


# ---------------------------------------------------------------------------
# format_funnel_discord — rendering tests
# ---------------------------------------------------------------------------

class TestFormatFunnelDiscord:
    def test_zero_activity_shows_skip(self):
        day = FunnelDay()
        msg = format_funnel_discord(day, "2026-04-17")
        assert "no_activity" in msg
        assert "2026-04-17" in msg

    def test_nonzero_activity_shows_counters(self):
        day = FunnelDay(scraped=120, deduped=98, covered=15, submitted=12, staged=10)
        msg = format_funnel_discord(day, "2026-04-17")
        assert "120" in msg
        assert "98" in msg
        assert "15" in msg
        assert "12" in msg
        assert "10" in msg

    def test_includes_date_key(self):
        day = FunnelDay(scraped=1)
        msg = format_funnel_discord(day, "2026-04-17")
        assert "2026-04-17" in msg

    def test_shows_core_stages_even_when_zero(self):
        # scraped/deduped/submitted/staged always appear
        day = FunnelDay(covered=5)
        msg = format_funnel_discord(day, "2026-04-17")
        assert "Scraped" in msg
        assert "Staged" in msg

    def test_extras_shown(self):
        day = FunnelDay()
        day.extras["my_metric"] = 7
        msg = format_funnel_discord(day, "2026-04-17")
        assert "my_metric" in msg
        assert "7" in msg


# ---------------------------------------------------------------------------
# today_key
# ---------------------------------------------------------------------------

class TestTodayKey:
    def test_returns_iso_date_string(self):
        key = today_key()
        import re
        assert re.match(r"\d{4}-\d{2}-\d{2}", key)
        assert len(key) == 10
