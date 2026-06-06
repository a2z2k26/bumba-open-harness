"""Tests for MS5.2: Operator Review Digest."""

from __future__ import annotations

import pytest

from bridge.digest import (
    aggregate_deploys,
    aggregate_incidents,
    aggregate_resources,
    build_digest_data,
    format_digest,
    save_digest,
)


# ── Deploy Aggregation ──


class TestAggregateDeploys:
    def test_empty(self):
        stats = aggregate_deploys([])
        assert stats.total == 0
        assert stats.success_rate == 0.0

    def test_all_successes(self):
        deploys = [{"status": "success"} for _ in range(5)]
        stats = aggregate_deploys(deploys)
        assert stats.total == 5
        assert stats.successes == 5
        assert stats.success_rate == 1.0

    def test_mixed_results(self):
        deploys = [
            {"status": "success"},
            {"status": "success"},
            {"status": "failed", "file": "app.py", "reason": "test failed"},
            {"status": "rollback", "file": "config.py"},
        ]
        stats = aggregate_deploys(deploys)
        assert stats.total == 4
        assert stats.successes == 2
        assert stats.failures == 1
        assert stats.rollbacks == 1
        assert stats.success_rate == 0.5

    def test_notable_failures_recorded(self):
        deploys = [
            {"status": "failed", "file": "bridge.py", "reason": "import error"},
        ]
        stats = aggregate_deploys(deploys)
        assert len(stats.notable) == 1
        assert "import error" in stats.notable[0]

    def test_notable_successes(self):
        deploys = [
            {"status": "success", "notable": True, "description": "New voice pipeline"},
        ]
        stats = aggregate_deploys(deploys)
        assert any("voice pipeline" in n.lower() for n in stats.notable)


# ── Incident Aggregation ──


class TestAggregateIncidents:
    def test_empty(self):
        stats = aggregate_incidents([])
        assert stats.total == 0

    def test_auto_recovered(self):
        incidents = [
            {"resolution": "auto_recovered", "recovery_minutes": 2.5, "summary": "Token refresh"},
            {"resolution": "auto_recovered", "recovery_minutes": 5.0, "summary": "Service restart"},
        ]
        stats = aggregate_incidents(incidents)
        assert stats.total == 2
        assert stats.auto_recovered == 2
        assert stats.avg_recovery_minutes == 3.75

    def test_mixed_resolutions(self):
        incidents = [
            {"resolution": "auto_recovered", "recovery_minutes": 1.0},
            {"resolution": "escalated"},
            {"resolution": "unresolved"},
        ]
        stats = aggregate_incidents(incidents)
        assert stats.auto_recovered == 1
        assert stats.escalated == 1
        assert stats.unresolved == 1

    def test_summaries_captured(self):
        incidents = [
            {"resolution": "escalated", "summary": "Disk full alert"},
        ]
        stats = aggregate_incidents(incidents)
        assert "Disk full alert" in stats.summaries


# ── Resource Aggregation ──


class TestAggregateResources:
    def test_empty(self):
        res = aggregate_resources([])
        assert res.total_tokens == 0
        assert res.cost_estimate_usd == 0.0

    def test_token_aggregation(self):
        entries = [
            {"tokens": 10000, "api_calls": 5, "service": "bridge"},
            {"tokens": 5000, "api_calls": 3, "service": "briefing"},
        ]
        res = aggregate_resources(entries)
        assert res.total_tokens == 15000
        assert res.api_calls == 8
        assert res.by_service["bridge"] == 10000
        assert res.by_service["briefing"] == 5000

    def test_cost_estimate(self):
        entries = [{"tokens": 1_000_000, "api_calls": 100, "service": "bridge"}]
        res = aggregate_resources(entries)
        assert res.cost_estimate_usd == pytest.approx(3.0, rel=0.1)


# ── Build Digest Data ──


class TestBuildDigestData:
    def test_all_sources(self):
        data = build_digest_data(
            deploys=[{"status": "success"}],
            incidents=[{"resolution": "auto_recovered", "recovery_minutes": 1}],
            usage=[{"tokens": 1000, "api_calls": 1, "service": "bridge"}],
            trust_scores={"deploy": 75.0},
            improvements=["Added caching"],
            pending_proposals=[{"name": "auto-retry", "priority_score": 8}],
            action_items=["Review proposal"],
            week_start="2026-03-09",
            week_end="2026-03-15",
        )
        assert data.deploys.total == 1
        assert data.incidents.total == 1
        assert data.resources.total_tokens == 1000
        assert data.trust_scores["deploy"] == 75.0
        assert len(data.missing_sources) == 0

    def test_missing_sources_noted(self):
        data = build_digest_data()
        assert "deploy_history" in data.missing_sources
        assert "incidents" in data.missing_sources
        assert "resource_usage" in data.missing_sources

    def test_partial_data(self):
        data = build_digest_data(
            deploys=[{"status": "success"}],
        )
        assert data.deploys.total == 1
        assert "incidents" in data.missing_sources
        assert "deploy_history" not in data.missing_sources


# ── Digest Formatting ──


class TestFormatDigest:
    def test_full_digest(self):
        data = build_digest_data(
            deploys=[{"status": "success"}, {"status": "failed", "file": "x.py", "reason": "err"}],
            incidents=[{"resolution": "auto_recovered", "recovery_minutes": 3, "summary": "Token refresh"}],
            usage=[{"tokens": 50000, "api_calls": 10, "service": "bridge"}],
            trust_scores={"deploy": 75.0, "search": 60.0},
            trust_changes=[{"capability": "deploy", "old_score": 70, "new_score": 75}],
            improvements=["Added retry logic"],
            pending_proposals=[{"name": "auto-retry", "priority_score": 8}],
            action_items=["Approve retry proposal"],
            week_start="2026-03-09",
            week_end="2026-03-15",
        )
        md = format_digest(data)
        assert "Weekly Digest" in md
        assert "Executive Summary" in md
        assert "Deployments" in md
        assert "Self-Improvements" in md
        assert "Incidents" in md
        assert "Proposals Pending" in md
        assert "Trust Score" in md
        assert "Resource Usage" in md
        assert "Action Items" in md

    def test_empty_week(self):
        data = build_digest_data(
            deploys=[],
            incidents=[],
            usage=[],
            trust_scores={},
        )
        md = format_digest(data)
        assert "No deployments" in md
        assert "No incidents" in md
        assert "Quiet week" in md

    def test_has_all_eight_sections(self):
        data = build_digest_data(
            deploys=[{"status": "success"}],
            incidents=[],
            usage=[],
        )
        md = format_digest(data)
        sections = [
            "Executive Summary",
            "Deployments",
            "Self-Improvements",
            "Incidents",
            "Proposals Pending",
            "Trust Score",
            "Resource Usage",
            "Action Items",
        ]
        for section in sections:
            assert section in md, f"Missing section: {section}"

    def test_trust_trend_arrows(self):
        data = build_digest_data(
            trust_scores={"deploy": 75.0},
            trust_changes=[{"capability": "deploy", "old_score": 60, "new_score": 75}],
        )
        md = format_digest(data)
        # Should show up arrow for deploy
        assert "\u2191" in md  # ↑

    def test_missing_sources_noted_in_output(self):
        data = build_digest_data()
        md = format_digest(data)
        assert "data unavailable" in md.lower()

    def test_action_items_numbered(self):
        data = build_digest_data(
            deploys=[],
            incidents=[],
            usage=[],
            action_items=["First item", "Second item"],
        )
        md = format_digest(data)
        assert "1. First item" in md
        assert "2. Second item" in md


# ── Digest Saving ──


class TestSaveDigest:
    def test_save_creates_file(self, tmp_path):
        md = "# Test Digest"
        path = save_digest(md, tmp_path, week_label="2026-W11")
        assert path.exists()
        assert path.read_text() == md

    def test_save_creates_digests_dir(self, tmp_path):
        save_digest("content", tmp_path, week_label="2026-W11")
        assert (tmp_path / "digests").is_dir()

    def test_save_auto_labels(self, tmp_path):
        path = save_digest("content", tmp_path)
        assert "W" in path.name
        assert path.name.endswith("-digest.md")
