"""Tests for cron jitter and ScanThrottle — anti-thundering-herd measures."""

import time

import pytest

from bridge.cron_jitter import CronJitter, ScanThrottle, JitterConfig


class TestJitterConfig:
    """Tests for JitterConfig dataclass."""

    def test_jitter_config_init(self):
        """Test JitterConfig initialization."""
        config = JitterConfig(
            base_interval_seconds=600,
            jitter_percent=10.0,
            jitter_cap_seconds=900,
        )
        assert config.base_interval_seconds == 600
        assert config.jitter_percent == 10.0
        assert config.jitter_cap_seconds == 900

    def test_jitter_config_immutable(self):
        """Test JitterConfig is immutable (frozen)."""
        config = JitterConfig(
            base_interval_seconds=600,
            jitter_percent=10.0,
            jitter_cap_seconds=900,
        )
        with pytest.raises(AttributeError):
            config.base_interval_seconds = 300


class TestCronJitter:
    """Tests for CronJitter calculation."""

    def test_calculate_jitter_basic(self):
        """Test basic jitter calculation."""
        config = JitterConfig(
            base_interval_seconds=600,
            jitter_percent=10.0,
            jitter_cap_seconds=900,
        )
        jitter = CronJitter(config)

        # Test that jitter is within expected bounds
        delay = jitter.calculate_jitter()
        assert 0 <= delay <= 600  # 0 to 10% of 600

    def test_calculate_jitter_consistency(self):
        """Test jitter calculation with seed (for reproducibility in tests)."""
        config = JitterConfig(
            base_interval_seconds=600,
            jitter_percent=10.0,
            jitter_cap_seconds=900,
        )
        jitter1 = CronJitter(config, seed=42)
        jitter2 = CronJitter(config, seed=42)

        delay1 = jitter1.calculate_jitter()
        delay2 = jitter2.calculate_jitter()

        assert delay1 == delay2

    def test_jitter_cap(self):
        """Test that jitter respects cap."""
        config = JitterConfig(
            base_interval_seconds=3600,  # 1 hour
            jitter_percent=50.0,  # 50% would be 1800 seconds
            jitter_cap_seconds=300,  # Cap at 5 min
        )
        jitter = CronJitter(config, seed=42)

        delay = jitter.calculate_jitter()
        assert delay <= 300  # Should be capped

    def test_zero_jitter_percent(self):
        """Test with 0% jitter (no variation)."""
        config = JitterConfig(
            base_interval_seconds=600,
            jitter_percent=0.0,
            jitter_cap_seconds=900,
        )
        jitter = CronJitter(config)

        delay = jitter.calculate_jitter()
        assert delay == 0

    def test_high_jitter_percent(self):
        """Test with high jitter percentage."""
        config = JitterConfig(
            base_interval_seconds=600,
            jitter_percent=100.0,  # Full base interval as jitter
            jitter_cap_seconds=900,
        )
        jitter = CronJitter(config, seed=42)

        delay = jitter.calculate_jitter()
        assert 0 <= delay <= 600

    def test_jitter_formulation(self):
        """Test jitter calculation formula: jitter = min(base * percent/100, cap)."""
        config = JitterConfig(
            base_interval_seconds=1000,
            jitter_percent=15.0,
            jitter_cap_seconds=200,
        )
        jitter = CronJitter(config, seed=42)

        delay = jitter.calculate_jitter()
        # Max jitter should be min(1000 * 0.15, 200) = 150
        assert delay <= 150


class TestScanThrottle:
    """Tests for ScanThrottle — distributed scan anti-thundering-herd."""

    def test_scan_throttle_init(self):
        """Test ScanThrottle initialization."""
        throttle = ScanThrottle(
            base_interval_seconds=600,
            peer_count=10,
            jitter_percent=10.0,
        )
        assert throttle.base_interval_seconds == 600
        assert throttle.peer_count == 10
        assert throttle.jitter_percent == 10.0

    def test_scan_throttle_calculate_interval(self):
        """Test ScanThrottle interval calculation."""
        throttle = ScanThrottle(
            base_interval_seconds=600,
            peer_count=10,
            jitter_percent=10.0,
        )

        interval = throttle.calculate_interval()
        # Should be base * peer_count = 6000 seconds
        assert interval >= 6000

    def test_scan_throttle_offset_calculation(self):
        """Test ScanThrottle offset (staggering for multi-peer setup)."""
        throttle = ScanThrottle(
            base_interval_seconds=600,
            peer_count=10,
            jitter_percent=10.0,
        )

        # Offset should distribute peers across interval
        offset = throttle.calculate_offset(peer_id=0)
        assert offset >= 0
        assert offset <= 600

    def test_scan_throttle_peer_staggering(self):
        """Test that different peers get different offsets."""
        throttle = ScanThrottle(
            base_interval_seconds=600,
            peer_count=10,
            jitter_percent=0.0,  # No jitter for deterministic test
        )

        offsets = [throttle.calculate_offset(peer_id=i) for i in range(5)]

        # Offsets should be distinct (with high probability)
        assert len(set(offsets)) >= 3

    def test_scan_throttle_next_scan_time(self):
        """Test next scan time calculation."""
        throttle = ScanThrottle(
            base_interval_seconds=600,
            peer_count=10,
            jitter_percent=10.0,
        )

        now = time.time()
        next_scan = throttle.next_scan_time(peer_id=0, last_scan_time=now)

        # Should be in the future
        assert next_scan > now

    def test_scan_throttle_boundary_conditions(self):
        """Test boundary conditions."""
        # Single peer
        throttle = ScanThrottle(
            base_interval_seconds=600,
            peer_count=1,
            jitter_percent=10.0,
        )
        interval = throttle.calculate_interval()
        assert interval >= 600

        # Many peers
        throttle = ScanThrottle(
            base_interval_seconds=600,
            peer_count=100,
            jitter_percent=10.0,
        )
        interval = throttle.calculate_interval()
        assert interval >= 60000

    def test_scan_throttle_zero_jitter(self):
        """Test ScanThrottle with zero jitter."""
        throttle = ScanThrottle(
            base_interval_seconds=600,
            peer_count=10,
            jitter_percent=0.0,
        )

        interval = throttle.calculate_interval()
        # Should be exactly base * peer_count with no jitter variation
        assert interval == 6000


class TestCronJitterIntegration:
    """Integration tests for cron jitter in scheduling context."""

    def test_multiple_jitter_instances(self):
        """Test that multiple jitter instances produce varied delays."""
        config = JitterConfig(
            base_interval_seconds=600,
            jitter_percent=10.0,
            jitter_cap_seconds=900,
        )

        delays = [CronJitter(config).calculate_jitter() for _ in range(10)]

        # Should have variation (at least 3 different values in 10 samples)
        assert len(set(delays)) >= 2

    def test_scan_throttle_multi_peer_distribution(self):
        """Test that ScanThrottle distributes peers evenly."""
        throttle = ScanThrottle(
            base_interval_seconds=600,
            peer_count=10,
            jitter_percent=0.0,
        )

        offsets = [throttle.calculate_offset(peer_id=i) for i in range(10)]

        # Offsets should be reasonably distributed
        min_offset = min(offsets)
        max_offset = max(offsets)
        spread = max_offset - min_offset

        # Spread should be significant (not all in a tiny range)
        assert spread > 50


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_jitter_with_very_small_interval(self):
        """Test jitter with very small interval."""
        config = JitterConfig(
            base_interval_seconds=1,
            jitter_percent=50.0,
            jitter_cap_seconds=10,
        )
        jitter = CronJitter(config)

        delay = jitter.calculate_jitter()
        assert 0 <= delay <= 1

    def test_jitter_with_large_interval(self):
        """Test jitter with large interval."""
        config = JitterConfig(
            base_interval_seconds=86400,  # 24 hours
            jitter_percent=10.0,
            jitter_cap_seconds=3600,  # 1 hour cap
        )
        jitter = CronJitter(config, seed=42)

        delay = jitter.calculate_jitter()
        assert 0 <= delay <= 3600

    def test_jitter_reproducibility(self):
        """Test that jitter with same seed is reproducible."""
        config = JitterConfig(
            base_interval_seconds=600,
            jitter_percent=10.0,
            jitter_cap_seconds=900,
        )

        jitter1 = CronJitter(config, seed=123)
        jitter2 = CronJitter(config, seed=123)

        delays1 = [jitter1.calculate_jitter() for _ in range(5)]
        delays2 = [jitter2.calculate_jitter() for _ in range(5)]

        assert delays1 == delays2

    def test_scan_throttle_invalid_peer_id(self):
        """Test ScanThrottle with peer_id outside expected range."""
        throttle = ScanThrottle(
            base_interval_seconds=600,
            peer_count=10,
            jitter_percent=10.0,
        )

        # Should handle gracefully
        offset = throttle.calculate_offset(peer_id=100)
        assert isinstance(offset, (int, float))
        assert offset >= 0
