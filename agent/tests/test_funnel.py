"""Tests for D5.8 funnel aggregator (aggregate_funnel)."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from job_search.funnel import aggregate_funnel, format_funnel_report_text


def _write_convo_log(base: Path, run_id: str, events: list[dict]) -> None:
    path = base / f"{run_id}.jsonl"
    with path.open("w") as fh:
        for ev in events:
            ev.setdefault("ts", time.time())
            fh.write(json.dumps(ev) + "\n")


def test_aggregate_funnel_empty_dir(tmp_path):
    report = aggregate_funnel(conversations_root=tmp_path / "empty", window="all")
    assert report.total_attempts == 0
    assert report.overall_submission_rate == 0.0


def test_aggregate_funnel_buckets_per_board(tmp_path):
    _write_convo_log(tmp_path, "run1", [
        {"event": "browser_completed", "board": "remotive", "ats_kind": "greenhouse", "last_step": "submit_click", "status": "submitted"},
        {"event": "browser_completed", "board": "remotive", "ats_kind": "greenhouse", "last_step": "captcha_detect", "status": "blocked"},
        {"event": "browser_completed", "board": "himalayas", "ats_kind": "lever", "last_step": "submit_click", "status": "submitted"},
    ])
    report = aggregate_funnel(conversations_root=tmp_path, window="all")
    assert report.total_attempts == 3
    assert report.total_submitted == 2
    assert report.total_blocked == 1
    boards = {b.board for b in report.buckets}
    assert "remotive" in boards
    assert "himalayas" in boards


def test_aggregate_funnel_time_window_filters(tmp_path):
    old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
    recent_ts = time.time()
    _write_convo_log(tmp_path, "run2", [
        {"event": "browser_completed", "board": "old", "ats_kind": "", "last_step": "submit_click", "status": "submitted", "ts": old_ts},
        {"event": "browser_completed", "board": "recent", "ats_kind": "", "last_step": "submit_click", "status": "submitted", "ts": recent_ts},
    ])
    report = aggregate_funnel(conversations_root=tmp_path, window="7d")
    assert report.total_attempts == 1
    assert report.buckets[0].board == "recent"


def test_aggregate_funnel_all_window_includes_old(tmp_path):
    old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
    _write_convo_log(tmp_path, "run3", [
        {"event": "browser_completed", "board": "old", "ats_kind": "", "last_step": "navigating", "status": "error", "ts": old_ts},
    ])
    report = aggregate_funnel(conversations_root=tmp_path, window="all")
    assert report.total_attempts == 1


def test_aggregate_funnel_submission_rate(tmp_path):
    _write_convo_log(tmp_path, "run4", [
        {"event": "browser_completed", "board": "b", "ats_kind": "a", "last_step": "submit_click", "status": "submitted"},
        {"event": "browser_completed", "board": "b", "ats_kind": "a", "last_step": "submit_click", "status": "submitted"},
        {"event": "browser_completed", "board": "b", "ats_kind": "a", "last_step": "captcha_detect", "status": "blocked"},
        {"event": "browser_completed", "board": "b", "ats_kind": "a", "last_step": "captcha_detect", "status": "blocked"},
    ])
    report = aggregate_funnel(conversations_root=tmp_path, window="all")
    assert report.overall_submission_rate == pytest.approx(0.5)


def test_format_funnel_report_text(tmp_path):
    _write_convo_log(tmp_path, "run5", [
        {"event": "browser_completed", "board": "remotive", "ats_kind": "greenhouse", "last_step": "submit_click", "status": "submitted"},
    ])
    report = aggregate_funnel(conversations_root=tmp_path, window="all")
    text = format_funnel_report_text(report)
    assert "Funnel" in text
    assert "remotive" in text
