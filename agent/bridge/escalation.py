"""MS2.5 — Proactive Escalation Engine.

4-level escalation system that monitors service states, applies cooldowns
and quiet-hours logic, and formats alerts for Discord delivery.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

EASTERN = ZoneInfo("US/Eastern")


class EscalationLevel(IntEnum):
    """Alert severity levels."""

    SILENCE = 0  # log only
    CASUAL = 1   # low-priority Discord message, batchable
    NUDGE = 2    # direct message, within 5 min
    URGENT = 3   # immediate message + mention


@dataclass
class EscalationTrigger:
    """Defines a condition that can produce an alert."""

    source: str                # Service or subsystem name
    condition: str             # Human-readable condition description
    level: EscalationLevel
    message_template: str      # Message template with {field} placeholders
    cooldown_s: int = 300


@dataclass
class ActiveAlert:
    """An alert that has been triggered and is currently active."""

    source: str
    level: EscalationLevel
    message: str
    triggered_at: str      # ISO timestamp
    last_notified_at: str  # ISO timestamp
    deferred: bool = False


def _most_recent_activity(state: dict) -> str | None:
    """Return the most recent ISO timestamp across all activity signals.

    Considers ``last_run``, ``last_success_time``, and ``last_skipped_at``
    (#1683 — a recent correct skip is activity, not silence). None-safe:
    missing, null, or unparseable fields are ignored, and an entirely fresh
    state returns None. Returns the ISO-8601 string corresponding to the
    most recent parseable datetime.
    """
    candidates = [
        state.get("last_run"),
        state.get("last_success_time"),
        state.get("last_skipped_at"),
    ]
    parsed: list[tuple[datetime, str]] = []
    for c in candidates:
        if not isinstance(c, str) or not c:
            continue
        parsed_dt = _parse_activity_datetime(c)
        if parsed_dt is None:
            continue
        parsed.append((parsed_dt, c))
    if not parsed:
        return None
    return max(parsed, key=lambda item: item[0])[1]


def _parse_activity_datetime(value: str) -> datetime | None:
    """Parse service activity timestamps as tz-aware UTC datetimes.

    New service writers emit ``datetime.now(timezone.utc).isoformat()``, but
    older state files may contain naive ISO strings. Treat those legacy values
    as UTC so stale scans and de-escalation can compare them safely.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Built-in trigger matrix
# ---------------------------------------------------------------------------

_TRIGGER_MATRIX: list[EscalationTrigger] = [
    EscalationTrigger(
        source="{service}",
        condition="consecutive_failures >= 5",
        level=EscalationLevel.URGENT,
        message_template="{service} has {consecutive_failures} consecutive failures: {last_error}",
        cooldown_s=300,
    ),
    EscalationTrigger(
        source="{service}",
        condition="consecutive_failures >= 3",
        level=EscalationLevel.NUDGE,
        message_template="{service} has {consecutive_failures} consecutive failures: {last_error}",
        cooldown_s=300,
    ),
    EscalationTrigger(
        source="email",
        condition="has_urgent == True",
        level=EscalationLevel.CASUAL,
        message_template="Urgent email detected",
        cooldown_s=300,
    ),
    EscalationTrigger(
        source="calendar",
        condition="has_conflict == True",
        level=EscalationLevel.CASUAL,
        message_template="Calendar conflict detected",
        cooldown_s=300,
    ),
    EscalationTrigger(
        source="token_refresher",
        condition="last_error not None",
        level=EscalationLevel.URGENT,
        message_template="Token refresh error: {last_error}",
        cooldown_s=300,
    ),
    EscalationTrigger(
        source="disk",
        condition="disk_usage_pct > 95",
        level=EscalationLevel.URGENT,
        message_template="Disk usage critical: {disk_usage_pct}%",
        cooldown_s=600,
    ),
    EscalationTrigger(
        source="disk",
        condition="disk_usage_pct > 90",
        level=EscalationLevel.NUDGE,
        message_template="Disk usage high: {disk_usage_pct}%",
        cooldown_s=600,
    ),
    EscalationTrigger(
        source="{service}_casual",
        condition="consecutive_failures == 1",
        level=EscalationLevel.CASUAL,
        message_template="{service} failed once: {last_error}",
        cooldown_s=3600,  # 1h — at most once per service per hour (Sprint D2.4)
    ),
]


class EscalationEngine:
    """Evaluates service states against a trigger matrix and manages alerts."""

    # Expected run intervals (seconds) for stale-service detection.
    # If a service hasn't run in 2x this interval, a NUDGE alert fires.
    _expected_intervals: dict[str, int] = {
        "job_search_execute": 7200,   # 2 hours
        "job_search": 86400,          # 24 hours
        "briefing": 86400,            # 24 hours
        "checkin": 43200,             # 12 hours
        "monitor": 3600,              # 1 hour
    }

    def __init__(self, state_dir: str | Path, operator_mention: str = "") -> None:
        self._state_dir = Path(state_dir)
        self._active_alerts: dict[str, ActiveAlert] = {}
        self._deferred_queue: list[ActiveAlert] = []
        self._cooldowns: dict[str, float] = {}  # source -> monotonic time of last alert
        self._operator_mention = operator_mention

    # ------------------------------------------------------------------
    # State scanning
    # ------------------------------------------------------------------

    def scan_service_states(self) -> dict[str, dict]:
        """Read all *-state.json files from state_dir.

        Returns {service_name: state_dict}.
        """
        states: dict[str, dict] = {}
        if not self._state_dir.is_dir():
            return states

        for path in sorted(self._state_dir.iterdir()):
            if path.suffix == ".json" and path.name.endswith("-state.json"):
                service_name = path.name.removesuffix("-state.json")
                try:
                    raw = json.loads(path.read_text())
                    if isinstance(raw, dict):
                        states[service_name] = raw
                except (json.JSONDecodeError, OSError) as e:
                    log.warning("Failed to read state file %s: %s", path, e)
        return states

    # ------------------------------------------------------------------
    # Trigger evaluation
    # ------------------------------------------------------------------

    def evaluate_triggers(self, states: dict[str, dict]) -> list[ActiveAlert]:
        """Evaluate the trigger matrix against current states.

        Returns new alerts (not already active and not in cooldown).
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        now_mono = time.monotonic()
        new_alerts: list[ActiveAlert] = []

        for service_name, state in states.items():
            consecutive = state.get("consecutive_failures", 0)
            last_error = state.get("last_error") or "unknown"

            # 5+ failures -> URGENT (check first so it takes priority)
            if consecutive >= 5:
                alert = self._try_create_alert(
                    source=service_name,
                    level=EscalationLevel.URGENT,
                    message=f"{service_name} has {consecutive} consecutive failures: {last_error}",
                    cooldown_s=300,
                    now_iso=now_iso,
                    now_mono=now_mono,
                )
                if alert:
                    new_alerts.append(alert)
            # 3+ failures -> NUDGE
            elif consecutive >= 3:
                alert = self._try_create_alert(
                    source=service_name,
                    level=EscalationLevel.NUDGE,
                    message=f"{service_name} has {consecutive} consecutive failures: {last_error}",
                    cooldown_s=300,
                    now_iso=now_iso,
                    now_mono=now_mono,
                )
                if alert:
                    new_alerts.append(alert)
            # 1 failure -> CASUAL (Sprint D2.4 — first-failure visibility)
            elif consecutive == 1:
                alert = self._try_create_alert(
                    source=f"{service_name}_casual",
                    level=EscalationLevel.CASUAL,
                    message=f"{service_name} failed once: {last_error}",
                    cooldown_s=3600,
                    now_iso=now_iso,
                    now_mono=now_mono,
                )
                if alert:
                    new_alerts.append(alert)

        # Stale service detection — services that stopped running entirely.
        # #1683: also consider last_skipped_at so a service that correctly
        # skips (e.g. checkin during active operator windows) does not trip
        # a false stale-alert. See docs/operator/2026-05-12-1615-checkin-incident-investigation.md.
        for service_name, expected_interval_s in self._expected_intervals.items():
            state = states.get(service_name, {})
            last_activity = _most_recent_activity(state)
            if last_activity is None:
                continue
            try:
                last_run_dt = _parse_activity_datetime(last_activity)
                if last_run_dt is None:
                    continue
                age_s = (datetime.now(timezone.utc) - last_run_dt).total_seconds()
                if age_s > expected_interval_s * 2:
                    hours = int(age_s // 3600)
                    alert = self._try_create_alert(
                        source=f"{service_name}_stale",
                        level=EscalationLevel.NUDGE,
                        message=f"{service_name} hasn't run in {hours}h (expected every {expected_interval_s // 3600}h)",
                        cooldown_s=expected_interval_s,
                        now_iso=now_iso,
                        now_mono=now_mono,
                    )
                    if alert:
                        new_alerts.append(alert)
            except (ValueError, TypeError):
                continue

        # Email urgent flag
        email_state = states.get("email", {})
        if email_state.get("has_urgent") is True:
            alert = self._try_create_alert(
                source="email_urgent",
                level=EscalationLevel.CASUAL,
                message="Urgent email detected",
                cooldown_s=300,
                now_iso=now_iso,
                now_mono=now_mono,
            )
            if alert:
                new_alerts.append(alert)

        # Calendar conflict
        calendar_state = states.get("calendar", {})
        if calendar_state.get("has_conflict") is True:
            alert = self._try_create_alert(
                source="calendar_conflict",
                level=EscalationLevel.CASUAL,
                message="Calendar conflict detected",
                cooldown_s=300,
                now_iso=now_iso,
                now_mono=now_mono,
            )
            if alert:
                new_alerts.append(alert)

        # Token refresher error
        token_state = states.get("token_refresher", {})
        if token_state.get("last_error") is not None:
            alert = self._try_create_alert(
                source="token_refresher",
                level=EscalationLevel.URGENT,
                message=f"Token refresh error: {token_state['last_error']}",
                cooldown_s=300,
                now_iso=now_iso,
                now_mono=now_mono,
            )
            if alert:
                new_alerts.append(alert)

        # Disk usage
        disk_state = states.get("disk", {})
        disk_pct = disk_state.get("disk_usage_pct", 0)
        if disk_pct > 95:
            alert = self._try_create_alert(
                source="disk",
                level=EscalationLevel.URGENT,
                message=f"Disk usage critical: {disk_pct}%",
                cooldown_s=600,
                now_iso=now_iso,
                now_mono=now_mono,
            )
            if alert:
                new_alerts.append(alert)
        elif disk_pct > 90:
            alert = self._try_create_alert(
                source="disk",
                level=EscalationLevel.NUDGE,
                message=f"Disk usage high: {disk_pct}%",
                cooldown_s=600,
                now_iso=now_iso,
                now_mono=now_mono,
            )
            if alert:
                new_alerts.append(alert)

        return new_alerts

    def _try_create_alert(
        self,
        *,
        source: str,
        level: EscalationLevel,
        message: str,
        cooldown_s: int,
        now_iso: str,
        now_mono: float,
    ) -> ActiveAlert | None:
        """Create an alert if not already active and not in cooldown."""
        # Already active?
        if source in self._active_alerts:
            return None

        # In cooldown?
        last_alert_time = self._cooldowns.get(source)
        if last_alert_time is not None and (now_mono - last_alert_time) < cooldown_s:
            return None

        alert = ActiveAlert(
            source=source,
            level=level,
            message=message,
            triggered_at=now_iso,
            last_notified_at=now_iso,
        )
        self._active_alerts[source] = alert
        self._cooldowns[source] = now_mono
        return alert

    # ------------------------------------------------------------------
    # De-escalation
    # ------------------------------------------------------------------

    def check_de_escalation(self, states: dict[str, dict]) -> list[str]:
        """Check active alerts whose trigger condition has cleared.

        Returns list of source names to clear.
        """
        cleared: list[str] = []

        for source, alert in list(self._active_alerts.items()):
            should_clear = False

            # Service failure alerts — check if consecutive_failures is back to 0
            if source in states:
                state = states[source]
                if state.get("consecutive_failures", 0) == 0:
                    should_clear = True

            # CASUAL first-failure alerts (source = "{service}_casual", Sprint D2.4)
            if source.endswith("_casual"):
                svc_name = source.removesuffix("_casual")
                if svc_name in states:
                    state = states[svc_name]
                    if state.get("consecutive_failures", 0) == 0:
                        should_clear = True

            # Email urgent
            if source == "email_urgent":
                email_state = states.get("email", {})
                if not email_state.get("has_urgent", False):
                    should_clear = True

            # Calendar conflict
            if source == "calendar_conflict":
                cal_state = states.get("calendar", {})
                if not cal_state.get("has_conflict", False):
                    should_clear = True

            # Token refresher
            if source == "token_refresher":
                token_state = states.get("token_refresher", {})
                if token_state.get("last_error") is None:
                    should_clear = True

            # Disk usage
            if source == "disk":
                disk_state = states.get("disk", {})
                if disk_state.get("disk_usage_pct", 0) <= 90:
                    should_clear = True

            # Stale service alerts — clear if service has run recently.
            # #1683: consider last_skipped_at alongside last_run/last_success_time
            # so a service that resumes correct skipping clears its stale alert.
            if source.endswith("_stale"):
                svc_name = source.removesuffix("_stale")
                state = states.get(svc_name, {})
                last_activity = _most_recent_activity(state)
                if last_activity:
                    try:
                        last_run_dt = _parse_activity_datetime(last_activity)
                        if last_run_dt is None:
                            continue
                        interval = self._expected_intervals.get(svc_name, 86400)
                        age_s = (datetime.now(timezone.utc) - last_run_dt).total_seconds()
                        if age_s <= interval * 2:
                            should_clear = True
                    except (ValueError, TypeError):
                        pass

            if should_clear:
                cleared.append(source)

        # Remove cleared alerts
        for source in cleared:
            del self._active_alerts[source]

        return cleared

    # ------------------------------------------------------------------
    # Quiet hours
    # ------------------------------------------------------------------

    def is_quiet_hours(self) -> bool:
        """Returns True during 01:00-09:00 US/Eastern.

        Aligned with the operator-schedule doctrine in `agent/OPERATOR.md` and
        `agent/config/zone1/operator-profile.md` (#2194). Pre-fix this was
        01:00-07:00, which delivered 7am-9am ET alerts at full volume contrary
        to the stated quiet window.
        """
        now_et = datetime.now(EASTERN)
        return 1 <= now_et.hour < 9

    def apply_quiet_hours(
        self, alerts: list[ActiveAlert]
    ) -> tuple[list[ActiveAlert], list[ActiveAlert]]:
        """Split alerts into (deliver_now, defer).

        During quiet hours:
        - URGENT delivers now
        - NUDGE deferred to queue
        - SILENCE/CASUAL unchanged (SILENCE is no-op, CASUAL can batch)
        """
        if not self.is_quiet_hours():
            return alerts, []

        deliver_now: list[ActiveAlert] = []
        defer: list[ActiveAlert] = []

        for alert in alerts:
            if alert.level == EscalationLevel.URGENT:
                deliver_now.append(alert)
            elif alert.level == EscalationLevel.NUDGE:
                alert.deferred = True
                defer.append(alert)
                self._deferred_queue.append(alert)
            else:
                # SILENCE and CASUAL pass through unchanged
                deliver_now.append(alert)

        return deliver_now, defer

    def flush_deferred(self) -> list[ActiveAlert]:
        """Return all deferred alerts and clear the queue. Called at 09:00 (quiet-hours end)."""
        flushed = list(self._deferred_queue)
        self._deferred_queue.clear()
        return flushed

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def format_alert(self, alert: ActiveAlert) -> str:
        """Format alert for Discord delivery based on level."""
        if alert.level == EscalationLevel.SILENCE:
            return ""
        if alert.level == EscalationLevel.CASUAL:
            return f"\u2139\ufe0f {alert.message}"
        if alert.level == EscalationLevel.NUDGE:
            return f"\u26a0\ufe0f {alert.message}"
        if alert.level == EscalationLevel.URGENT:
            mention = f"{self._operator_mention} " if self._operator_mention else ""
            return f"\U0001f6a8 {mention}{alert.message}\nAction needed"
        return alert.message

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_state(self) -> None:
        """Persist active alerts and cooldowns to escalation-state.json."""
        data = {
            "active_alerts": {
                source: asdict(alert)
                for source, alert in self._active_alerts.items()
            },
            "deferred_queue": [asdict(a) for a in self._deferred_queue],
            # Cooldowns use monotonic time so we store relative offsets
            # from current monotonic; on load we reconstruct.
            "cooldowns_relative": {
                source: time.monotonic() - ts
                for source, ts in self._cooldowns.items()
            },
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }

        path = self._state_dir / "escalation-state.json"
        fd, tmp_path = tempfile.mkstemp(dir=self._state_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def load_state(self) -> None:
        """Load active alerts and cooldowns from escalation-state.json."""
        path = self._state_dir / "escalation-state.json"
        if not path.exists():
            return

        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load escalation state: %s", e)
            return

        now_mono = time.monotonic()

        # Restore active alerts
        self._active_alerts.clear()
        for source, alert_dict in data.get("active_alerts", {}).items():
            alert_dict["level"] = EscalationLevel(alert_dict["level"])
            self._active_alerts[source] = ActiveAlert(**alert_dict)

        # Restore deferred queue
        self._deferred_queue.clear()
        for alert_dict in data.get("deferred_queue", []):
            alert_dict["level"] = EscalationLevel(alert_dict["level"])
            self._deferred_queue.append(ActiveAlert(**alert_dict))

        # Restore cooldowns — convert relative offsets back to monotonic times
        self._cooldowns.clear()
        for source, elapsed in data.get("cooldowns_relative", {}).items():
            self._cooldowns[source] = now_mono - elapsed
