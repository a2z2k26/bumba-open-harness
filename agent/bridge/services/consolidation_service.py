"""Consolidation service — scheduled knowledge base maintenance.

Extends ServiceBase. Orchestrates the 6-phase consolidation pipeline,
reading knowledge entries from the database, running pure-function logic,
and writing updates back.

Modes:
- micro:    Decay only (every 6 hours)
- standard: Full pipeline (daily 02:00)
- deep:     Full pipeline + LLM contradiction pass — stubbed (weekly Sun 02:00)
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path

from .base import ServiceBase
from bridge.consolidation_lock import ConsolidationLock, STALE_THRESHOLD_S

log = logging.getLogger(__name__)


class ConsolidationService(ServiceBase):
    """Scheduled knowledge base consolidation service."""

    def __init__(
        self,
        data_dir: str | Path,
        db_path: str | Path,
        chat_id: str,
        *,
        event_callback=None,
        mode: str = "standard",
    ) -> None:
        super().__init__(data_dir, event_callback=event_callback)
        self.db_path = Path(db_path)
        self.chat_id = chat_id
        self.mode = mode
        self._lock = ConsolidationLock(data_dir)
        self._dream_agent = None  # injected via set_dream_agent() for testability
        self._config = None       # injected via set_config() for DreamAgent construction

        self._log_source = None    # injected via set_log_source() for daily log input
        self._session_scanner = None  # injected via set_session_scanner()
        self._date_detector = None    # injected via set_date_detector()

    def _load_knowledge_rows(self, conn: sqlite3.Connection) -> list[dict]:
        """Load all active knowledge entries as dicts."""
        try:
            cursor = conn.execute(
                """SELECT key, value, category, source, salience,
                          access_count, created_at, updated_at, accessed_at
                   FROM knowledge
                   WHERE archived IS NULL OR archived = 0"""
            )
            columns = [desc[0] for desc in cursor.description]
            rows = []
            for row in cursor.fetchall():
                rows.append(dict(zip(columns, row)))
            return rows
        except sqlite3.OperationalError as e:
            log.error("Failed to load knowledge rows: %s", e)
            return []

    def _apply_decay_updates(
        self,
        conn: sqlite3.Connection,
        rows: list[dict],
    ) -> int:
        """Write decay results back to the database.

        Returns count of rows updated.
        """
        updated = 0
        for row in rows:
            action = row.get("_action")
            key = row.get("key")
            if not key:
                continue

            if action == "prune":
                conn.execute(
                    "UPDATE knowledge SET archived = 1, updated_at = datetime('now') WHERE key = ?",
                    (key,),
                )
                updated += 1
            elif action == "decay":
                new_sal = row.get("_new_salience")
                if new_sal is not None:
                    conn.execute(
                        "UPDATE knowledge SET salience = ?, updated_at = datetime('now') WHERE key = ?",
                        (new_sal, key),
                    )
                    updated += 1
        return updated

    def _apply_merge_updates(
        self,
        conn: sqlite3.Connection,
        rows: list[dict],
    ) -> int:
        """Archive merged-away entries. Returns count of rows archived."""
        archived = 0
        for row in rows:
            if row.get("_merge_action") == "archive":
                key = row.get("key")
                if key:
                    conn.execute(
                        "UPDATE knowledge SET archived = 1, updated_at = datetime('now') WHERE key = ?",
                        (key,),
                    )
                    archived += 1
        return archived

    def _apply_promotion_updates(
        self,
        conn: sqlite3.Connection,
        rows: list[dict],
    ) -> int:
        """Write promotion/demotion salience changes. Returns count updated."""
        updated = 0
        for row in rows:
            action = row.get("_promotion_action")
            if action in ("promote", "demote"):
                new_sal = row.get("_new_salience")
                key = row.get("key")
                if new_sal is not None and key:
                    conn.execute(
                        "UPDATE knowledge SET salience = ?, updated_at = datetime('now') WHERE key = ?",
                        (new_sal, key),
                    )
                    updated += 1
        return updated

    def _emit(self, event_type: str, payload: dict) -> None:
        """Emit an event if callback is configured."""
        if self._event_callback:
            try:
                self._event_callback(event_type, payload)
            except Exception:
                log.debug("Event callback failed", exc_info=True)

    # ---- gate: min-interval (hours) per mode ----
    _MIN_INTERVAL_H: dict[str, float] = {
        "micro": 6.0,
        "standard": 22.0,  # allow slight drift from 24h
        "deep": 166.0,     # allow drift from 168h (7 days)
    }

    def should_consolidate(self, mode: str | None = None) -> bool:
        """Three-gate cascade: lock exists + interval elapsed + mode eligible.

        Gate 1: Is another consolidation already running (fresh lock + live PID)?
        Gate 2: Has the minimum interval elapsed since last consolidation?
        Gate 3: Is the mode valid?

        Returns True only if all three gates pass.
        """
        effective_mode = mode or self.mode
        if effective_mode not in self._MIN_INTERVAL_H:
            log.warning("Unknown consolidation mode: %s", effective_mode)
            return False

        # Gate 1: check for live lock
        lock_path = self._lock._lock_path
        if lock_path.exists():
            stat = lock_path.stat()
            age_s = time.time() - stat.st_mtime
            if age_s < STALE_THRESHOLD_S:
                try:
                    holder_pid = int(lock_path.read_text().strip())
                    try:
                        os.kill(holder_pid, 0)
                        log.debug("Consolidation skipped: lock held by PID %d", holder_pid)
                        return False
                    except (OSError, ProcessLookupError):
                        pass  # stale holder, continue
                except (ValueError, OSError):
                    pass  # unreadable lock, continue

        # Gate 2: min interval
        last_run = self._lock.read_last_consolidated_at()
        elapsed_h = (time.time() - last_run) / 3600.0
        min_h = self._MIN_INTERVAL_H[effective_mode]
        if elapsed_h < min_h:
            log.debug(
                "Consolidation skipped: %.1fh elapsed, need %.1fh (mode=%s)",
                elapsed_h,
                min_h,
                effective_mode,
            )
            return False

        # Gate 3: mode is valid (already checked above)
        return True

    def run(self, mode: str | None = None) -> "ServiceResult":
        """Execute the consolidation pipeline (Z2-S0.1)."""
        from bridge.consolidation import run_pipeline
        from bridge.services.result import ServiceResult

        effective_mode = mode or self.mode
        start = time.monotonic()
        state_file = "consolidation-state.json"

        # Acquire consolidation lock
        lock_result = self._lock.try_acquire()
        if not lock_result.acquired:
            log.warning(
                "Consolidation skipped: lock held by PID %s",
                lock_result.holder_pid,
            )
            return ServiceResult(
                service="consolidation",
                ok=True,
                work_items=0,
                duration_ms=int((time.monotonic() - start) * 1000),
                cost_usd=0.0,
                skip_reason=f"lock_held_by_pid_{lock_result.holder_pid}",
            )

        self._emit("consolidation.started", {"mode": effective_mode})

        try:
            conn = sqlite3.connect(str(self.db_path))
        except Exception as e:
            log.error("Failed to connect to DB: %s", e)
            self.record_failure(str(e)[:500], filename=state_file)
            return ServiceResult(
                service="consolidation",
                ok=False,
                work_items=0,
                duration_ms=int((time.monotonic() - start) * 1000),
                cost_usd=0.0,
                anomalies=("db_connect_failed",),
            )

        try:
            rows = self._load_knowledge_rows(conn)
            log.info(
                "Consolidation: loaded %d knowledge rows (mode=%s)",
                len(rows),
                effective_mode,
            )

            # Build session_ids for deep mode so run_pipeline can drive the
            # DreamAgent call itself (Sprint 05.09 — single source of truth
            # for deep_resolution status).
            session_ids = (
                [str(r.get("key", "")) for r in rows]
                if effective_mode == "deep"
                else None
            )

            # Run pure-function pipeline. In deep mode this also invokes
            # the wired DreamAgent (if any) and the resulting status lands
            # in report.phase_results["deep_resolution"]["status"].
            report = run_pipeline(
                rows,
                mode=effective_mode,
                session_ids=session_ids,
                _dream_agent=self._dream_agent if effective_mode == "deep" else None,
            )

            # Apply DB updates based on pipeline annotations
            total_updates = 0

            # Decay updates (always applied)
            decay_updates = self._apply_decay_updates(conn, rows)
            total_updates += decay_updates

            # Merge updates (standard + deep only)
            if effective_mode in ("standard", "deep"):
                merge_updates = self._apply_merge_updates(conn, rows)
                total_updates += merge_updates

                # Promotion updates
                promo_updates = self._apply_promotion_updates(conn, rows)
                total_updates += promo_updates

            # If deep mode succeeded, mark daily logs as consolidated.
            deep_payload = report.phase_results.get("deep_resolution") or {}
            deep_status = (
                deep_payload.get("status") if isinstance(deep_payload, dict) else None
            )
            if (
                effective_mode == "deep"
                and deep_status == "completed"
                and self._log_source is not None
            ):
                try:
                    from datetime import datetime, timezone
                    now_ts = datetime.now(timezone.utc)
                    for _log_date, _log_content in self._log_source.get_recent_logs(days=7):
                        if not self._log_source.is_already_consolidated(_log_content):
                            log_paths = self._log_source._daily_log.list_recent(days=7)
                            for lp in log_paths:
                                if lp.stem == str(_log_date):
                                    self._log_source.mark_consolidated(lp, now_ts)
                                    break
                except Exception as mark_exc:
                    log.error(
                        "Marking daily logs consolidated failed: %s", mark_exc
                    )
            elif effective_mode == "deep" and deep_status == "error":
                log.warning(
                    "DreamAgent pass failed: %s",
                    deep_payload.get("error") if isinstance(deep_payload, dict) else None,
                )

            conn.commit()

            duration_ms = int((time.monotonic() - start) * 1000)

            log.info(
                "Consolidation complete: mode=%s, updates=%d, duration=%dms, deep=%s",
                effective_mode,
                total_updates,
                duration_ms,
                deep_status,
            )

            self.record_success(duration_ms, filename=state_file)
            self._lock.record_completion()
            self._lock.release()

            self._emit("consolidation.completed", {
                "mode": effective_mode,
                "total_updates": total_updates,
                "duration_ms": duration_ms,
                "deep_resolution_status": deep_status,
                "report_summary": {
                    "phases": list(report.phase_results.keys()),
                    "total_rows": len(rows),
                },
            })

            # Deliver a summary message if significant work was done
            if total_updates > 0:
                summary = self._format_summary(report, total_updates)
                self.deliver_message(
                    self.chat_id,
                    summary,
                    source="consolidation",
                )

            if total_updates == 0:
                return ServiceResult(
                    service="consolidation",
                    ok=True,
                    work_items=0,
                    duration_ms=duration_ms,
                    cost_usd=0.0,
                    skip_reason="no_updates_needed",
                )
            return ServiceResult(
                service="consolidation",
                ok=True,
                work_items=total_updates,
                duration_ms=duration_ms,
                cost_usd=0.0,
            )

        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            log.error("Consolidation failed after %dms: %s", duration_ms, e)
            self.record_failure(str(e)[:500], filename=state_file)
            self._lock.rollback(lock_result.prior_mtime)
            self._emit("consolidation.failed", {
                "mode": effective_mode,
                "error": str(e)[:200],
                "duration_ms": duration_ms,
            })
            raise
        finally:
            conn.close()

    def _format_summary(self, report, total_updates: int) -> str:
        """Format a human-readable consolidation summary."""
        from bridge.consolidation import (
            DecayResult,
            InventoryReport,
            MergeResult,
            PromotionResult,
        )

        lines = [f"**Consolidation** ({report.mode}) - {total_updates} updates\n"]

        inv = report.phase_results.get("inventory")
        if isinstance(inv, InventoryReport):
            lines.append(f"Inventory: {inv.total} active entries")

        dec = report.phase_results.get("decay")
        if isinstance(dec, DecayResult):
            lines.append(f"Decay: {dec.decayed} decayed, {dec.pruned} pruned, {dec.exempt} exempt")

        merge = report.phase_results.get("merge")
        if isinstance(merge, MergeResult):
            if merge.merged > 0:
                lines.append(f"Merge: {merge.merged} duplicates archived")

        promo = report.phase_results.get("promotion")
        if isinstance(promo, PromotionResult):
            if promo.promoted > 0 or promo.demoted > 0:
                lines.append(f"Promotion: {promo.promoted} promoted, {promo.demoted} demoted")

        lines.append(f"\nDuration: {report.total_duration_ms}ms")
        return "\n".join(lines)

    def set_dream_agent(self, agent) -> None:
        """Inject a DreamAgent instance (or mock) for deep consolidation."""
        self._dream_agent = agent

    def set_config(self, config) -> None:
        """Inject a BridgeConfig instance for constructing DreamAgent on demand."""
        self._config = config


    def set_log_source(self, source) -> None:
        """Inject a LogConsolidationSource to read daily logs during deep runs."""
        self._log_source = source

    def set_session_scanner(self, scanner) -> None:
        """Inject a SessionTranscriptScanner for session mtime scanning."""
        self._session_scanner = scanner

    def set_date_detector(self, detector) -> None:
        """Inject a DateChangeDetector for midnight rollover detection."""
        self._date_detector = detector

