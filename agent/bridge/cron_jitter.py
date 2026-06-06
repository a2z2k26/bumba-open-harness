"""Cron jitter and ScanThrottle — anti-thundering-herd measures.

Prevents synchronized scans across multiple peers by adding randomized delays
to cron job schedules.

Components:
- JitterConfig: Immutable jitter configuration (base interval, percent, cap)
- CronJitter: Calculates randomized delays for single cron jobs
- ScanThrottle: Distributes multi-peer scans across time windows
"""

import random
import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class JitterConfig:
    """
    Immutable cron jitter configuration.

    Attributes:
        base_interval_seconds: Base interval between cron executions (e.g., 600 for 10 min)
        jitter_percent: Jitter as percentage of base interval (0.0 - 100.0)
        jitter_cap_seconds: Maximum jitter duration (cap the absolute jitter duration)
    """

    base_interval_seconds: int
    jitter_percent: float
    jitter_cap_seconds: int


class CronJitter:
    """
    Calculates randomized delays for cron jobs.

    Adds a random delay (up to jitter_percent % of base_interval) to prevent
    synchronized execution across multiple peers (thundering herd problem).

    Formula: delay = min(base_interval * jitter_percent / 100, jitter_cap)
    """

    def __init__(self, config: JitterConfig, seed: Optional[int] = None):
        """
        Initialize CronJitter.

        Args:
            config: JitterConfig instance
            seed: Optional seed for reproducible random (used in tests)
        """
        self.config = config
        # Use instance-level Random to avoid global state issues
        self.rng = random.Random(seed)

    def calculate_jitter(self) -> float:
        """
        Calculate a randomized delay.

        Returns:
            Delay in seconds (0 to min(base_interval * percent/100, cap))
        """
        # Calculate max jitter: percentage of base interval
        max_jitter_from_percent = (
            self.config.base_interval_seconds * self.config.jitter_percent / 100.0
        )

        # Apply cap
        max_jitter = min(max_jitter_from_percent, self.config.jitter_cap_seconds)

        # Return random delay from 0 to max_jitter
        return self.rng.uniform(0, max_jitter)


class ScanThrottle:
    """
    Distributes multi-peer scans across time windows.

    Prevents thundering herd by staggering peer scans: if there are N peers,
    each peer's scan interval is multiplied by N, and each peer gets a unique
    offset within that window.

    Useful for health checks, consolidation scans, knowledge expiry cleanup,
    and other periodic operations across distributed peers.
    """

    def __init__(
        self,
        base_interval_seconds: int,
        peer_count: int,
        jitter_percent: float = 10.0,
        seed: Optional[int] = None,
    ):
        """
        Initialize ScanThrottle.

        Args:
            base_interval_seconds: Base scan interval (e.g., 600 for 10 min)
            peer_count: Number of peers in the system
            jitter_percent: Jitter percentage (default 10%)
            seed: Optional seed for reproducible random
        """
        self.base_interval_seconds = base_interval_seconds
        self.peer_count = peer_count
        self.jitter_percent = jitter_percent
        self.rng = random.Random(seed)

    def calculate_interval(self) -> float:
        """
        Calculate throttled interval for a peer.

        Returns:
            Interval in seconds (base_interval * peer_count + jitter)
        """
        # Base interval is multiplied by peer count
        base = self.base_interval_seconds * self.peer_count

        # Add jitter
        jitter_config = JitterConfig(
            base_interval_seconds=base,
            jitter_percent=self.jitter_percent,
            jitter_cap_seconds=int(self.base_interval_seconds * 1.5),  # Cap at 1.5x base
        )
        jitter_obj = CronJitter(jitter_config)
        jitter_amount = jitter_obj.calculate_jitter()

        return base + jitter_amount

    def calculate_offset(self, peer_id: int) -> float:
        """
        Calculate offset for a specific peer within the scan window.

        Distributes peers evenly across base interval, with random jitter.

        Args:
            peer_id: ID of the peer (0-indexed)

        Returns:
            Offset in seconds within the base interval
        """
        # Base offset: distribute peers evenly within base interval
        base_offset = (peer_id % self.peer_count) * (
            self.base_interval_seconds / max(1, self.peer_count)
        )

        # Add small jitter around the base offset (±5% of base interval)
        jitter_config = JitterConfig(
            base_interval_seconds=self.base_interval_seconds,
            jitter_percent=5.0,
            jitter_cap_seconds=int(self.base_interval_seconds * 0.05),
        )
        jitter_obj = CronJitter(jitter_config)
        jitter_amount = jitter_obj.calculate_jitter()

        offset = base_offset + (jitter_amount - jitter_amount / 2)  # Center jitter around 0
        return max(0, min(offset, self.base_interval_seconds))

    def next_scan_time(self, peer_id: int, last_scan_time: float) -> float:
        """
        Calculate the next scan time for a peer.

        Args:
            peer_id: ID of the peer
            last_scan_time: Unix timestamp of last scan (or current time to start immediately)

        Returns:
            Unix timestamp of next scheduled scan
        """
        interval = self.calculate_interval()
        offset = self.calculate_offset(peer_id)

        # Next scan = last_scan + interval + offset
        return last_scan_time + interval + offset

    def should_scan_now(
        self, peer_id: int, last_scan_time: float, current_time: Optional[float] = None
    ) -> bool:
        """
        Check if a peer should perform a scan now.

        Args:
            peer_id: ID of the peer
            last_scan_time: Unix timestamp of last scan
            current_time: Current time (defaults to time.time())

        Returns:
            True if enough time has elapsed for this peer to scan
        """
        if current_time is None:
            current_time = time.time()

        next_time = self.next_scan_time(peer_id, last_scan_time)
        return current_time >= next_time


class ThrottledScheduler:
    """
    Utility for scheduling throttled tasks across multiple peers.

    Tracks multiple peer scan schedules and provides simple interface for
    checking if any peer should scan now.
    """

    def __init__(self, base_interval_seconds: int, peer_count: int):
        """
        Initialize ThrottledScheduler.

        Args:
            base_interval_seconds: Base scan interval
            peer_count: Number of peers
        """
        self.throttle = ScanThrottle(
            base_interval_seconds=base_interval_seconds,
            peer_count=peer_count,
        )
        self.last_scan_times: dict[int, float] = {}

    def mark_scanned(self, peer_id: int, timestamp: Optional[float] = None) -> None:
        """
        Mark a peer as having scanned.

        Args:
            peer_id: ID of the peer
            timestamp: Scan time (defaults to current time)
        """
        if timestamp is None:
            timestamp = time.time()
        self.last_scan_times[peer_id] = timestamp

    def should_scan(self, peer_id: int) -> bool:
        """
        Check if a peer should scan now.

        Args:
            peer_id: ID of the peer

        Returns:
            True if peer should scan
        """
        last_scan = self.last_scan_times.get(peer_id, 0)
        return self.throttle.should_scan_now(peer_id, last_scan)

    def next_scan_times(self) -> dict[int, float]:
        """
        Get next scan times for all tracked peers.

        Returns:
            Dict mapping peer_id to next scan Unix timestamp
        """
        return {
            peer_id: self.throttle.next_scan_time(peer_id, last_scan_time)
            for peer_id, last_scan_time in self.last_scan_times.items()
        }
