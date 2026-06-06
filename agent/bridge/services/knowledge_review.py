"""Knowledge review service — daily maintenance of the knowledge base.

Extends ServiceBase. Runs daily at 11pm (or configurable time).
Reviews low-salience entries approaching archive, detects duplicates,
suggests consolidation.

Sprint 05.09 (issue #1017) of the 2026-04-25 reference-audit bundle —
optional second-brain vault lint stage runs after the existing review
when ``second_brain_enabled`` AND ``second_brain_lint_enabled`` are
both True. Lint failures NEVER fail the existing knowledge-review
work; they are reported in-line and continue. ADR Decision 5 signed
2026-05-01 — wiki = SoT, lint flags but never blocks.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from .base import ServiceBase

log = logging.getLogger(__name__)


class KnowledgeReviewService(ServiceBase):
    """Daily knowledge base review and maintenance service."""

    def __init__(
        self,
        data_dir: str | Path,
        db_path: str | Path,
        chat_id: str,
        *,
        event_callback=None,
        review_hour: int = 23,
        review_minute: int = 0,
        archive_threshold: float = 0.1,
        warning_threshold: float = 0.3,
        second_brain_enabled: bool = False,
        second_brain_lint_enabled: bool = False,
        second_brain_vault_root: str = "",
        second_brain_lint_schema_version: int = 1,
    ) -> None:
        super().__init__(data_dir, event_callback=event_callback)
        self.db_path = Path(db_path)
        self.chat_id = chat_id
        self.review_hour = review_hour
        self.review_minute = review_minute
        self.archive_threshold = archive_threshold
        self.warning_threshold = warning_threshold
        self.second_brain_enabled = second_brain_enabled
        self.second_brain_lint_enabled = second_brain_lint_enabled
        self.second_brain_vault_root = second_brain_vault_root
        self.second_brain_lint_schema_version = second_brain_lint_schema_version

    def should_run(self) -> bool:
        """Check time window and dedup."""
        now = datetime.now()
        target = now.replace(
            hour=self.review_hour,
            minute=self.review_minute,
            second=0,
            microsecond=0,
        )
        if abs((now - target).total_seconds()) > 1800:
            return False

        state = self.load_state(filename="knowledge-review-state.json")
        last_review = state.get("last_review_date", "")
        return last_review != now.strftime("%Y-%m-%d")

    def _find_low_salience(self, conn: sqlite3.Connection) -> list[dict]:
        """Find entries approaching archive threshold."""
        try:
            rows = conn.execute(
                """SELECT key, category, salience FROM knowledge
                   WHERE salience IS NOT NULL
                   AND salience <= ?
                   AND salience > ?
                   AND (archived IS NULL OR archived = 0)
                   ORDER BY salience ASC
                   LIMIT 10""",
                (self.warning_threshold, self.archive_threshold),
            ).fetchall()
            return [{"key": r[0], "category": r[1], "salience": r[2]} for r in rows]
        except sqlite3.OperationalError:
            # salience column might not exist yet
            return []

    def _find_recently_archived(self, conn: sqlite3.Connection) -> int:
        """Count entries archived in the last 24h."""
        try:
            row = conn.execute(
                """SELECT COUNT(*) FROM knowledge
                   WHERE archived = 1
                   AND updated_at > datetime('now', '-24 hours')"""
            ).fetchone()
            return row[0] if row else 0
        except sqlite3.OperationalError:
            return 0

    def _find_potential_duplicates(self, conn: sqlite3.Connection) -> list[tuple[str, str]]:
        """Find entries with similar keys that might be duplicates."""
        try:
            rows = conn.execute(
                """SELECT a.key, b.key FROM knowledge a, knowledge b
                   WHERE a.rowid < b.rowid
                   AND a.category = b.category
                   AND (a.archived IS NULL OR a.archived = 0)
                   AND (b.archived IS NULL OR b.archived = 0)
                   AND (
                       a.key LIKE '%' || b.key || '%'
                       OR b.key LIKE '%' || a.key || '%'
                   )
                   LIMIT 5"""
            ).fetchall()
            return [(r[0], r[1]) for r in rows]
        except sqlite3.OperationalError:
            return []

    def _get_stats(self, conn: sqlite3.Connection) -> dict:
        """Get knowledge base stats."""
        stats = {}
        try:
            row = conn.execute("SELECT COUNT(*) FROM knowledge WHERE archived IS NULL OR archived = 0").fetchone()
            stats["active_count"] = row[0] if row else 0

            row = conn.execute("SELECT COUNT(*) FROM knowledge WHERE archived = 1").fetchone()
            stats["archived_count"] = row[0] if row else 0

            row = conn.execute(
                "SELECT COUNT(*) FROM knowledge WHERE updated_at > datetime('now', '-24 hours')"
            ).fetchone()
            stats["updated_24h"] = row[0] if row else 0
        except sqlite3.OperationalError:
            pass
        return stats

    def compile(self) -> str | None:
        """Compile knowledge review report."""
        try:
            conn = sqlite3.connect(str(self.db_path))
        except Exception as e:
            log.error("Failed to connect to knowledge DB: %s", e)
            return None

        try:
            stats = self._get_stats(conn)
            low_salience = self._find_low_salience(conn)
            recently_archived = self._find_recently_archived(conn)
            duplicates = self._find_potential_duplicates(conn)
        finally:
            conn.close()

        # Only report if there's something noteworthy
        if not low_salience and not duplicates and recently_archived == 0:
            return None

        lines = [f"**Knowledge Review** ({stats.get('active_count', '?')} active entries)\n"]

        if low_salience:
            lines.append(f"**Approaching archive** ({len(low_salience)} entries):")
            for entry in low_salience:
                lines.append(f"  - `{entry['key']}` ({entry['category']}) — salience: {entry['salience']:.2f}")

        if recently_archived:
            lines.append(f"\n**Recently archived**: {recently_archived} entries in the last 24h")

        if duplicates:
            lines.append(f"\n**Potential duplicates** ({len(duplicates)}):")
            for a, b in duplicates:
                lines.append(f"  - `{a}` ↔ `{b}`")

        if stats.get("updated_24h", 0) > 0:
            lines.append(f"\n**Updated today**: {stats['updated_24h']} entries")

        return "\n".join(lines)

    # ---------------- second-brain lint stage (Sprint 05.09) ---------------- #

    def _lint_report_path(self, today_iso: str) -> Path:
        """Return ``data/second-brain-lint/YYYY-MM-DD.json`` (atomic write target)."""
        return self.data_dir / "second-brain-lint" / f"{today_iso}.json"

    def _atomic_write_json(self, target: Path, payload: dict) -> None:
        """Atomically write ``payload`` as JSON to ``target``."""
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=target.name + ".",
            suffix=".tmp",
            dir=str(target.parent),
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, target)
        except BaseException:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
            raise

    def _run_second_brain_lint(self) -> str | None:
        """Run the lint pass when both flags are on; return Discord summary or None.

        Defensive: every failure path returns None and logs. The caller
        wraps the whole stage in try/except so a lint crash cannot
        affect the existing knowledge-review work.
        """
        if not (self.second_brain_enabled and self.second_brain_lint_enabled):
            return None
        vault_root_str = (self.second_brain_vault_root or "").strip()
        if not vault_root_str:
            log.info("second-brain lint: vault_root not configured — skipping")
            return None
        vault_root = Path(vault_root_str)
        if not vault_root.is_dir():
            log.warning(
                "second-brain lint: vault_root %s is not a directory — skipping",
                vault_root,
            )
            return None

        # Late import — second_brain has heavier deps and the lint stage
        # is opt-in. Avoids paying the import cost when the flag is off.
        from bridge.second_brain.baseline import load_baseline
        from bridge.second_brain.lint import lint_vault

        try:
            baseline = load_baseline()
        except Exception as exc:
            log.warning("second-brain lint: baseline load failed (%s)", exc)
            baseline = {}

        report = lint_vault(
            vault_root,
            baseline=baseline or None,
            schema_version=self.second_brain_lint_schema_version,
        )

        # Persist full report as JSON (atomic).
        today_iso = datetime.now().strftime("%Y-%m-%d")
        report_path = self._lint_report_path(today_iso)
        payload = {
            "date": today_iso,
            "vault_root": str(vault_root),
            "schema_version": self.second_brain_lint_schema_version,
            "total_notes_scanned": report.total_notes_scanned,
            "grandfathered_skipped": report.grandfathered_skipped,
            "duration_seconds": report.duration_seconds,
            "findings": [
                {
                    "relpath": f.relpath,
                    "rule": f.rule,
                    "severity": f.severity,
                    "message": f.message,
                }
                for f in report.findings
            ],
        }
        try:
            self._atomic_write_json(report_path, payload)
        except OSError as exc:
            log.warning(
                "second-brain lint: report write failed (%s) — continuing",
                exc,
            )

        if not report.findings:
            return (
                f"\n\n**Second-brain lint** — clean "
                f"({report.total_notes_scanned} notes scanned, "
                f"{report.grandfathered_skipped} grandfathered)."
            )

        # Severity weight for "top 5 most severe": error > warning > info.
        severity_weight = {"error": 0, "warning": 1, "info": 2}
        top = sorted(
            report.findings,
            key=lambda f: (severity_weight.get(f.severity, 9), f.relpath, f.rule),
        )[:5]
        lines = [
            f"\n\n**Second-brain lint** — {len(report.findings)} finding(s) "
            f"across {report.total_notes_scanned} notes "
            f"({report.grandfathered_skipped} grandfathered):",
        ]
        for f in top:
            lines.append(
                f"  - `{f.relpath}` [{f.severity}/{f.rule}] {f.message}",
            )
        if len(report.findings) > 5:
            lines.append(f"  - ... and {len(report.findings) - 5} more")
        lines.append(f"  Full report: `{report_path}`")
        return "\n".join(lines)

    def run(self) -> "ServiceResult":
        """Execute knowledge review (Z2-S0.1)."""
        import time as _time

        from bridge.services.result import ServiceResult

        _start = _time.monotonic()

        if not self.should_run():
            self.record_skipped(
                "outside review window or already ran today",
                filename="knowledge-review-state.json",
            )
            return ServiceResult(
                service="knowledge_review",
                ok=True,
                work_items=0,
                duration_ms=int((_time.monotonic() - _start) * 1000),
                cost_usd=0.0,
                skip_reason="outside_window_or_already_ran",
            )

        try:
            review = self.compile()

            state = self.load_state(filename="knowledge-review-state.json")
            state["last_review_date"] = datetime.now().strftime("%Y-%m-%d")
            self.save_state(state, filename="knowledge-review-state.json")

            # Sprint 05.09 — second-brain lint stage. Defensive: any failure
            # logs and falls through; lint must NEVER fail knowledge_review.
            lint_summary: str | None = None
            try:
                lint_summary = self._run_second_brain_lint()
            except Exception as exc:
                log.warning(
                    "second-brain lint stage raised %s — continuing without it",
                    exc,
                    exc_info=True,
                )

            if review is None and lint_summary is None:
                log.info("Knowledge review: nothing noteworthy")
                self.record_skipped(
                    "nothing noteworthy in knowledge base",
                    filename="knowledge-review-state.json",
                )
                return ServiceResult(
                    service="knowledge_review",
                    ok=True,
                    work_items=0,
                    duration_ms=int((_time.monotonic() - _start) * 1000),
                    cost_usd=0.0,
                    skip_reason="no_new_items",
                )

            # Compose outbound: review body + lint suffix.
            parts: list[str] = []
            if review is not None:
                parts.append(review)
            if lint_summary is not None:
                # Strip leading newlines we baked into the suffix when
                # there's no review prefix to attach to.
                parts.append(
                    lint_summary.lstrip("\n") if not parts else lint_summary,
                )
            outbound = "\n\n".join(p for p in parts if p)

            self.deliver_message(self.chat_id, outbound, source="knowledge-review")

            duration_ms = int((_time.monotonic() - _start) * 1000)
            self.record_success(duration_ms, filename="knowledge-review-state.json")
            log.info("Knowledge review sent (%dms)", duration_ms)
            return ServiceResult(
                service="knowledge_review",
                ok=True,
                work_items=1,
                duration_ms=duration_ms,
                cost_usd=0.0,
            )

        except Exception as e:
            duration_ms = int((_time.monotonic() - _start) * 1000)
            self.record_failure(str(e)[:500], filename="knowledge-review-state.json")
            log.error("Knowledge review failed after %dms: %s", duration_ms, e)
            raise
