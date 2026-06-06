"""Tests for MS5.1: Trust Score System."""

from __future__ import annotations

import math
import threading
import time

import pytest

from bridge.trust_score import (
    CAPABILITY_DOMAINS,
    INITIAL_SCORE,
    MIN_SAMPLE_SIZE,
    PENALTY_CRITICAL,
    PENALTY_MAJOR,
    TIER_APPROVAL_REQUIRED,
    TIER_AUTO_LOGGED,
    TIER_AUTO_SILENT,
    TIER_DISABLED,
    TrustScoreEngine,
    score_to_tier,
)


@pytest.fixture
def engine(tmp_path):
    return TrustScoreEngine(data_dir=tmp_path)


@pytest.fixture
def mem_engine():
    """In-memory engine (no persistence)."""
    return TrustScoreEngine()


# ── Tier Classification ──


class TestScoreToTier:
    def test_disabled_at_0(self):
        assert score_to_tier(0) == TIER_DISABLED

    def test_disabled_at_29(self):
        assert score_to_tier(29) == TIER_DISABLED

    def test_approval_at_30(self):
        assert score_to_tier(30) == TIER_APPROVAL_REQUIRED

    def test_approval_at_59(self):
        assert score_to_tier(59) == TIER_APPROVAL_REQUIRED

    def test_auto_logged_at_60(self):
        assert score_to_tier(60) == TIER_AUTO_LOGGED

    def test_auto_logged_at_89(self):
        assert score_to_tier(89) == TIER_AUTO_LOGGED

    def test_auto_silent_at_90(self):
        assert score_to_tier(90) == TIER_AUTO_SILENT

    def test_auto_silent_at_100(self):
        assert score_to_tier(100) == TIER_AUTO_SILENT


# ── Initial State ──


class TestInitialState:
    def test_all_domains_present(self, engine):
        for cap in CAPABILITY_DOMAINS:
            assert engine.get_score(cap) == INITIAL_SCORE

    def test_seven_domains(self, engine):
        assert len(CAPABILITY_DOMAINS) == 7

    def test_initial_tier(self, engine):
        # Score 50 → APPROVAL_REQUIRED
        for cap in CAPABILITY_DOMAINS:
            assert engine.get_tier(cap) == TIER_APPROVAL_REQUIRED

    def test_unknown_capability(self, engine):
        assert engine.get_score("nonexistent") == INITIAL_SCORE

    def test_get_all_scores(self, engine):
        scores = engine.get_all_scores()
        assert len(scores) == 7
        assert all(s == INITIAL_SCORE for s in scores.values())


# ── Score Updates ──


class TestScoreUpdates:
    def test_success_increases_score(self, mem_engine):
        old = mem_engine.get_score("deploy")
        mem_engine.record_event("deploy", "success", reason="test deploy")
        new = mem_engine.get_score("deploy")
        assert new > old

    def test_minor_failure_decreases_score(self, mem_engine):
        old = mem_engine.get_score("deploy")
        mem_engine.record_event("deploy", "failure", severity="minor")
        new = mem_engine.get_score("deploy")
        assert new < old

    def test_major_failure_penalty(self, mem_engine):
        old = mem_engine.get_score("search")
        mem_engine.record_event("search", "failure", severity="major")
        new = mem_engine.get_score("search")
        assert old - new >= PENALTY_MAJOR - 1  # allow rounding

    def test_critical_failure_penalty(self, mem_engine):
        old = mem_engine.get_score("routing")
        mem_engine.record_event("routing", "failure", severity="critical")
        new = mem_engine.get_score("routing")
        assert old - new >= PENALTY_CRITICAL - 1

    def test_rollback_treated_as_major(self, mem_engine):
        old = mem_engine.get_score("deploy")
        mem_engine.record_event("deploy", "rollback")
        new = mem_engine.get_score("deploy")
        assert old - new >= PENALTY_MAJOR - 1

    def test_operator_approved_increases(self, mem_engine):
        old = mem_engine.get_score("deploy")
        mem_engine.record_event("deploy", "operator_approved")
        assert mem_engine.get_score("deploy") > old

    def test_operator_rejected_decreases(self, mem_engine):
        old = mem_engine.get_score("deploy")
        mem_engine.record_event("deploy", "operator_rejected")
        assert mem_engine.get_score("deploy") < old

    def test_score_clamped_at_zero(self, mem_engine):
        for _ in range(10):
            mem_engine.record_event("deploy", "failure", severity="critical")
        assert mem_engine.get_score("deploy") >= 0.0

    def test_score_clamped_at_100(self, mem_engine):
        for _ in range(200):
            mem_engine.record_event("search", "success")
        assert mem_engine.get_score("search") <= 100.0


# ── Score Computation ──


class TestScoreComputation:
    def test_high_success_rate_high_score(self, mem_engine):
        # Record many successes, few failures
        for _ in range(50):
            mem_engine.record_event("search", "success")
        for _ in range(2):
            mem_engine.record_event("search", "failure", severity="minor")
        score = mem_engine.get_score("search")
        assert score > 70  # should be high with 96% success

    def test_low_success_rate_low_score(self, mem_engine):
        for _ in range(5):
            mem_engine.record_event("search", "success")
        for _ in range(15):
            mem_engine.record_event("search", "failure", severity="minor")
        score = mem_engine.get_score("search")
        assert score < 50  # should be below neutral with 25% success

    def test_minimum_sample_size(self, mem_engine):
        # With fewer than MIN_SAMPLE_SIZE actions, score stays near initial
        for _ in range(MIN_SAMPLE_SIZE - 2):
            mem_engine.record_event("deploy", "success")
        # Score should still be driven by incremental changes, not formula
        score = mem_engine.get_score("deploy")
        # After 8 successes from initial 50, should be around 58
        assert 50 < score < 70

    def test_formula_kicks_in_at_sample_size(self, mem_engine):
        # Record exactly MIN_SAMPLE_SIZE events (all success)
        for _ in range(MIN_SAMPLE_SIZE):
            mem_engine.record_event("deploy", "success")
        # Formula should now compute; with 100% success, 0 failures, 0 rollbacks
        score = mem_engine.get_score("deploy")
        assert score > 80  # should be very high


# ── Recovery Mechanics ──


class TestRecovery:
    def test_recovery_starts_after_failure(self, mem_engine):
        mem_engine.record_event("deploy", "failure", severity="major")
        cs = mem_engine.get_capability_state("deploy")
        assert cs.recovery.active is True
        assert cs.recovery.successes_needed == math.ceil(PENALTY_MAJOR / 3)

    def test_recovery_progresses_with_successes(self, mem_engine):
        mem_engine.record_event("deploy", "failure", severity="minor")
        cs = mem_engine.get_capability_state("deploy")
        needed = cs.recovery.successes_needed
        for _ in range(needed - 1):
            mem_engine.record_event("deploy", "success")
        cs = mem_engine.get_capability_state("deploy")
        assert cs.recovery.active is True
        assert cs.recovery.successes_so_far == needed - 1

    def test_recovery_completes(self, mem_engine):
        mem_engine.record_event("deploy", "failure", severity="minor")
        cs = mem_engine.get_capability_state("deploy")
        needed = cs.recovery.successes_needed
        for _ in range(needed):
            mem_engine.record_event("deploy", "success")
        cs = mem_engine.get_capability_state("deploy")
        assert cs.recovery.active is False

    def test_recovery_points_restore_score(self, mem_engine):
        pre_failure = mem_engine.get_score("deploy")
        mem_engine.record_event("deploy", "failure", severity="minor")
        post_failure = mem_engine.get_score("deploy")
        cs = mem_engine.get_capability_state("deploy")
        needed = cs.recovery.successes_needed
        for _ in range(needed):
            mem_engine.record_event("deploy", "success")
        post_recovery = mem_engine.get_score("deploy")
        # Score should be close to pre-failure (recovery restores penalty points)
        assert post_recovery > post_failure


# ── Cooldown ──


class TestCooldown:
    def test_critical_failure_sets_cooldown(self, mem_engine):
        mem_engine.record_event("deploy", "failure", severity="critical")
        cs = mem_engine.get_capability_state("deploy")
        assert cs.cooldown_until > time.time()

    def test_cooldown_blocks_access(self, mem_engine):
        mem_engine.record_event("deploy", "failure", severity="critical")
        result = mem_engine.check_access("deploy")
        assert result.allowed is False
        assert result.cooldown_remaining > 0

    def test_no_cooldown_for_minor_failure(self, mem_engine):
        mem_engine.record_event("deploy", "failure", severity="minor")
        cs = mem_engine.get_capability_state("deploy")
        assert cs.cooldown_until <= time.time()


# ── Access Checks ──


class TestAccessChecks:
    def test_approval_required_at_initial(self, mem_engine):
        result = mem_engine.check_access("deploy")
        assert result.allowed is False
        assert result.requires_approval is True
        assert result.tier == TIER_APPROVAL_REQUIRED

    def test_disabled_blocks_completely(self, mem_engine):
        # Drop score below 30
        for _ in range(5):
            mem_engine.record_event("deploy", "failure", severity="critical")
        result = mem_engine.check_access("deploy")
        assert result.allowed is False
        assert result.requires_approval is False

    def test_auto_logged_allows(self, mem_engine):
        # Build up score above 60
        for _ in range(50):
            mem_engine.record_event("search", "success")
        result = mem_engine.check_access("search")
        assert result.allowed is True

    def test_unknown_capability_denied(self, mem_engine):
        result = mem_engine.check_access("nonexistent")
        assert result.allowed is False


# ── Operator Override ──


class TestOverride:
    def test_override_changes_tier(self, mem_engine):
        # Initially APPROVAL_REQUIRED (score 50)
        assert mem_engine.get_tier("deploy") == TIER_APPROVAL_REQUIRED
        mem_engine.set_override("deploy", TIER_AUTO_LOGGED, reason="operator trust")
        assert mem_engine.get_tier("deploy") == TIER_AUTO_LOGGED

    def test_override_makes_accessible(self, mem_engine):
        mem_engine.set_override("deploy", TIER_AUTO_SILENT)
        result = mem_engine.check_access("deploy")
        assert result.allowed is True
        assert result.tier == TIER_AUTO_SILENT

    def test_clear_override(self, mem_engine):
        mem_engine.set_override("deploy", TIER_AUTO_SILENT)
        mem_engine.clear_override("deploy")
        assert mem_engine.get_tier("deploy") == TIER_APPROVAL_REQUIRED

    def test_invalid_tier_rejected(self, mem_engine):
        assert mem_engine.set_override("deploy", "INVALID_TIER") is False

    def test_override_nonexistent_capability(self, mem_engine):
        assert mem_engine.set_override("nonexistent", TIER_AUTO_LOGGED) is False


# ── History ──


class TestHistory:
    def test_events_recorded(self, engine):
        engine.record_event("deploy", "success", reason="test")
        history = engine.get_history("deploy")
        assert len(history) == 1
        assert history[0].event_type == "success"
        assert history[0].reason == "test"

    def test_history_filtered_by_capability(self, engine):
        engine.record_event("deploy", "success")
        engine.record_event("search", "failure", severity="minor")
        deploy_hist = engine.get_history("deploy")
        assert len(deploy_hist) == 1
        assert deploy_hist[0].capability == "deploy"

    def test_history_limit(self, engine):
        for i in range(20):
            engine.record_event("deploy", "success", reason=f"event-{i}")
        recent = engine.get_history("deploy", limit=5)
        assert len(recent) == 5

    def test_history_persisted(self, tmp_path):
        engine1 = TrustScoreEngine(data_dir=tmp_path)
        engine1.record_event("deploy", "success", reason="persisted")
        engine2 = TrustScoreEngine(data_dir=tmp_path)
        history = engine2.get_history("deploy")
        assert len(history) >= 1
        assert history[-1].reason == "persisted"

    def test_prune_history(self, engine):
        engine.record_event("deploy", "success", reason="recent")
        removed = engine.prune_history(retention_days=365)
        assert removed == 0  # just-recorded event should not be pruned
        remaining = engine.get_history("deploy")
        assert len(remaining) == 1


# ── Persistence ──


class TestPersistence:
    def test_scores_saved_and_loaded(self, tmp_path):
        engine1 = TrustScoreEngine(data_dir=tmp_path)
        for _ in range(5):
            engine1.record_event("deploy", "success")
        score1 = engine1.get_score("deploy")

        engine2 = TrustScoreEngine(data_dir=tmp_path)
        score2 = engine2.get_score("deploy")
        assert score1 == score2

    def test_override_persisted(self, tmp_path):
        engine1 = TrustScoreEngine(data_dir=tmp_path)
        engine1.set_override("deploy", TIER_AUTO_SILENT)

        engine2 = TrustScoreEngine(data_dir=tmp_path)
        assert engine2.get_tier("deploy") == TIER_AUTO_SILENT

    def test_recovery_state_persisted(self, tmp_path):
        engine1 = TrustScoreEngine(data_dir=tmp_path)
        engine1.record_event("deploy", "failure", severity="major")

        engine2 = TrustScoreEngine(data_dir=tmp_path)
        cs = engine2.get_capability_state("deploy")
        assert cs.recovery.active is True


# ── Formatting ──


class TestFormatting:
    def test_trust_table(self, mem_engine):
        table = mem_engine.format_trust_table()
        assert "Capability" in table
        assert "deploy" in table
        assert "search" in table
        assert "Score" in table

    def test_trust_table_has_all_domains(self, mem_engine):
        table = mem_engine.format_trust_table()
        for cap in CAPABILITY_DOMAINS:
            assert cap in table

    def test_capability_detail(self, mem_engine):
        mem_engine.record_event("deploy", "success", reason="test event")
        detail = mem_engine.format_capability_detail("deploy")
        assert detail is not None
        assert "Trust: deploy" in detail
        assert "Score" in detail
        assert "test event" in detail

    def test_capability_detail_nonexistent(self, mem_engine):
        assert mem_engine.format_capability_detail("nonexistent") is None

    def test_detail_shows_recovery(self, mem_engine):
        mem_engine.record_event("deploy", "failure", severity="major")
        detail = mem_engine.format_capability_detail("deploy")
        assert "Recovery In Progress" in detail


# ── Concurrent Access ──


class TestConcurrentAccess:
    def test_concurrent_updates(self, mem_engine):
        errors = []

        def worker(cap, n):
            try:
                for _ in range(n):
                    mem_engine.record_event(cap, "success")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=("deploy", 50)),
            threading.Thread(target=worker, args=("search", 50)),
            threading.Thread(target=worker, args=("deploy", 50)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        cs = mem_engine.get_capability_state("deploy")
        assert cs.total_actions == 100  # 50 + 50
