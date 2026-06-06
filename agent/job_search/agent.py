"""Job Search Agent — phased pipeline orchestrator.

Two-cron model:
  PREPARE (08:00): Research → Cover Letters → Outreach Research → Outreach Drafts → Stage in Notion
  EXECUTE (every 2hrs): Check Notion approvals → Submit applications → Send outreach emails
"""
from __future__ import annotations

import asyncio
import json as json_mod
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from bridge.paths import data_root

from .approval import (
    RubricStageData,
    check_approvals,
    execute_approved,
    stage_listing,
)
from .ats.applicant import apply_to_job
from .ats.detector import detect_ats
from .boards.ashby_jobs import AshbyJobsBoard
from .boards.base import JobListing
from .boards.behance import BehanceBoard
from .boards.builtin import BuiltInBoard
from .boards.coroflot import CoroflotBoard
from .boards.dice import DiceBoard
from .boards.dribbble import DribbbleBoard
from .boards.greenhouse_jobs import GreenhouseBoard
from .boards.himalayas import HimalayasBoard
from .boards.jobicy import JobicyBoard
from .boards.lever_jobs import LeverBoard
from .boards.nodesk import NodeskBoard
from .boards.remoteok import RemoteOKBoard
from .boards.remotive import RemotiveBoard
from .boards.weworkremotely import WeWorkRemotelyBoard
from .boards.workingnomads import WorkingNomadsBoard
from .boards.yc_workatastartup import YCombinatorBoard
from .cover_letter import generate_cover_letter
from .criteria import Candidate, SearchCriteria
from .deduplication import Deduplicator
from .lint import lint_cover_letter
from .notifier import NotionNotifier
from .outreach import Contact, OutreachDraft, draft_outreach_email, research_decision_makers
from .preflight import phase_gate, start_audit, update_audit
from .quality_wiring import bump_today, get_funnel_store, get_snapshot_store
from .rubric import DEFAULT_RUBRIC_PATH, Rubric, RubricResult, evaluate as rubric_evaluate
from .rubric_evidence import (
    ATSYieldEvent,
    CoverLetterOutcome,
    DECISION_FAILED_EVAL,
    DECISION_FILTERED,
    DECISION_NOT_APPLICABLE,
    DECISION_PASSED,
    GateDecision,
    append_ats_yield,
    append_cover_letter_outcome,
    append_decision,
    read_last_notion_scan,
    write_last_notion_scan,
)

log = logging.getLogger(__name__)

_HERE = Path(__file__).parent
DEFAULT_CRITERIA = _HERE / "criteria.json"
DEFAULT_CANDIDATE = _HERE / "candidate.json"
DEFAULT_DB = data_root() / "job_search.db"

# Max companies to do full outreach for per run
OUTREACH_CAP = 4

# Module-level set of Cloudflare-quarantined domains for this run.
# When apply_to_job() returns cloudflare_blocked=True, the domain is added here
# and all subsequent listings on the same domain skip the browser entirely.
_cloudflare_quarantine_domains: set[str] = set()


def quarantine_domain(domain: str) -> None:
    """Add a domain to the Cloudflare quarantine list for this run."""
    _cloudflare_quarantine_domains.add(domain.lower())


def _is_quarantined(url: str) -> bool:
    """Return True if the URL's domain is in the Cloudflare quarantine list."""
    host = urlparse(url).netloc.lower()
    return any(host.endswith(d) for d in _cloudflare_quarantine_domains)


class JobSearchAgent:
    """Orchestrates the job search pipeline."""

    def __init__(
        self,
        criteria_path: str | Path = DEFAULT_CRITERIA,
        candidate_path: str | Path = DEFAULT_CANDIDATE,
        db_path: str | Path = DEFAULT_DB,
        notion_db_id: str = "",
        outreach_cap: int = OUTREACH_CAP,
        *,
        data_dir: str | Path | None = None,
        rubric_gate_enabled: bool = False,
        rubric_threshold: str = "B",
        rubric_path: str | Path | None = None,
        evidence_dir: str | Path | None = None,
        avg_cover_letter_cost_usd: float = 1.00,
    ) -> None:
        self.criteria = SearchCriteria.from_file(criteria_path)
        self.candidate = Candidate.from_file(candidate_path)
        self.db_path = Path(db_path)
        self.dedup = Deduplicator()
        self.notifier = NotionNotifier(database_id=notion_db_id)
        self.outreach_cap = outreach_cap
        # Sprint 02.10: wire quality primitives (funnel + snapshot stores).
        # Both default to the production DATA_DIR; tests pass tmp_path via
        # the data_dir kwarg.
        self._data_dir = data_dir
        self.funnel_store = get_funnel_store(data_dir)
        self.snapshot_store = get_snapshot_store(data_dir)
        # Sprint 06.03 — rubric gate. Default OFF for safe rollout. The
        # rubric definition is loaded lazily on first use so test paths
        # that never enable the gate don't pay the YAML-load cost.
        self._rubric_gate_enabled = rubric_gate_enabled
        self._rubric_threshold = rubric_threshold
        self._rubric_path: Path = (
            Path(rubric_path) if rubric_path is not None else DEFAULT_RUBRIC_PATH
        )
        self._rubric_def: Rubric | None = None
        if rubric_gate_enabled:
            try:
                self._rubric_def = Rubric.load_from_yaml(self._rubric_path)
            except (FileNotFoundError, ValueError) as e:
                # Fail-safe: log and disable the gate rather than crash the
                # whole prepare cron. Operator sees the warning + can fix
                # the YAML; the pipeline keeps running unfiltered.
                log.error(
                    "rubric gate: failed to load rubric YAML at %s: %s — disabling gate",
                    self._rubric_path, e,
                )
                self._rubric_gate_enabled = False
        # Sprint 06.08 — rubric evidence harness. Default location matches
        # the production data_dir (resolved via ``bridge.paths.data_root() /
        # "rubric-evidence"``) when ``data_dir`` is set; tests pass an
        # explicit ``evidence_dir`` to keep writes inside ``tmp_path``.
        if evidence_dir is not None:
            self._evidence_dir: Path = Path(evidence_dir)
        elif data_dir is not None:
            self._evidence_dir = Path(data_dir) / "rubric-evidence"
        else:
            self._evidence_dir = data_root() / "rubric-evidence"
        # Estimated cover-letter spend per listing — used for the
        # ``estimated_savings`` projection on filtered decisions. Operator
        # can override via constructor arg once 14-day data shows the
        # actual mean. Default ($1.00) is the spec's working assumption.
        self._avg_cover_letter_cost_usd = float(avg_cover_letter_cost_usd)
        self._boards = [
            # Tier 1: Public APIs (highest reliability)
            RemotiveBoard(),
            HimalayasBoard(),
            JobicyBoard(),
            RemoteOKBoard(),
            WorkingNomadsBoard(),
            WeWorkRemotelyBoard(),
            YCombinatorBoard(),
            # Tier 1b: ATS direct APIs (operator-curated company seeds in
            # config/companies.yaml; empty seed list means graceful no-op)
            AshbyJobsBoard(),
            GreenhouseBoard(),
            LeverBoard(),
            # Tier 2: HTML scrapers (design-specific)
            DribbbleBoard(),
            BehanceBoard(),
            CoroflotBoard(),
            BuiltInBoard(),
            NodeskBoard(),
            DiceBoard(),
        ]

    # -- DB Setup --

    def _init_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                fingerprint TEXT NOT NULL,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                board TEXT NOT NULL,
                ats TEXT,
                location TEXT,
                remote TEXT,
                compensation TEXT,
                description TEXT,
                raw_json TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                applied_at TEXT,
                notion_page_id TEXT,
                cover_letter TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jl_fingerprint ON job_listings(fingerprint);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jl_status ON job_listings(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jl_board ON job_listings(board);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jl_created ON job_listings(created_at);")
        self._ensure_column(conn, "cover_letter", "TEXT")
        # Sprint 06.03 — rubric gate columns. Idempotent (the helper
        # checks PRAGMA table_info first), so re-running _init_db on a
        # populated DB never errors. These columns stay populated even
        # when the gate flag is OFF only because filters are skipped;
        # nothing depends on them being non-NULL.
        self._ensure_column(conn, "job_listings", "rubric_grade", "TEXT")
        self._ensure_column(conn, "job_listings", "rubric_score", "REAL")
        self._ensure_column(conn, "job_listings", "rubric_rationale", "TEXT")
        self._ensure_column(conn, "job_listings", "rubric_evaluated_at", "TEXT")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS outreach_contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_fingerprint TEXT NOT NULL,
                name TEXT NOT NULL,
                title TEXT NOT NULL,
                email TEXT NOT NULL,
                company TEXT NOT NULL,
                personalization_hook TEXT,
                draft_subject TEXT,
                draft_email TEXT,
                slot INTEGER NOT NULL,
                approved INTEGER DEFAULT 0,
                sent INTEGER DEFAULT 0,
                sent_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (listing_fingerprint) REFERENCES job_listings(fingerprint)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_oc_fingerprint ON outreach_contacts(listing_fingerprint);"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_oc_sent ON outreach_contacts(sent);")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS run_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_type TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                phase_results TEXT,
                errors TEXT,
                success INTEGER DEFAULT 1
            )
        """)
        conn.commit()
        return conn

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection,
        column_or_table: str,
        col_type_or_column: str,
        col_type: str | None = None,
    ) -> None:
        """Idempotent ALTER TABLE ADD COLUMN.

        Two call shapes are supported (Sprint 06.03):

        * ``_ensure_column(conn, column, col_type)`` — legacy 3-arg form,
          targets the ``job_listings`` table (kept for backward compat).
        * ``_ensure_column(conn, table, column, col_type)`` — explicit
          table form used by the rubric-gate migration.

        Identifiers come exclusively from internal callers passing string
        literals; SQLite ALTER TABLE does not accept parameterized
        identifiers. Sprint 08.03 (#781). Revisit 2026-09-01.
        """
        if col_type is None:
            table = "job_listings"
            column = column_or_table
            ctype = col_type_or_column
        else:
            table = column_or_table
            column = col_type_or_column
            ctype = col_type
        cursor = conn.execute(f"PRAGMA table_info({table})")  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
        columns = {row[1] for row in cursor.fetchall()}
        if column not in columns:
            conn.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
                f"ALTER TABLE {table} ADD COLUMN {column} {ctype}"
            )

    def _seed_dedup_from_db(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("SELECT fingerprint FROM job_listings").fetchall()
        for (fp,) in rows:
            self.dedup.add_fingerprint(fp)
        log.info("Seeded dedup with %d existing fingerprints", len(rows))

    def _save_listing(
        self,
        conn: sqlite3.Connection,
        listing: JobListing,
        ats: str,
        fp: str,
        *,
        rubric: RubricResult | None = None,
    ) -> None:
        conn.execute(
            """INSERT OR IGNORE INTO job_listings
                (url, fingerprint, title, company, board, ats, location, remote,
                 compensation, description, raw_json, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')""",
            (
                listing.url,
                fp,
                listing.title,
                listing.company,
                listing.board,
                ats,
                listing.location,
                listing.remote,
                listing.compensation,
                listing.description,
                json_mod.dumps(listing.raw),
            ),
        )
        if rubric is not None:
            # Sprint 06.03 — persist rubric eval alongside the listing.
            # ``per_dim_rationale`` is serialized so 06.04 (Notion columns)
            # can render the per-dimension breakdown without a re-eval.
            conn.execute(
                """UPDATE job_listings
                   SET rubric_grade = ?, rubric_score = ?,
                       rubric_rationale = ?, rubric_evaluated_at = ?
                   WHERE fingerprint = ?""",
                (
                    rubric.letter_grade,
                    rubric.weighted_score,
                    json_mod.dumps(rubric.per_dim_rationale),
                    rubric.evaluated_at.isoformat(),
                    fp,
                ),
            )
        conn.commit()

    # -- Sprint 06.08 — ATS yield scan (operator-tracker → evidence harness) --

    # Notion ``Status`` values that count as a yield event. Operator
    # configures these on the staging DB; if they're missing we record no
    # events and the scan is a graceful no-op.
    _ATS_YIELD_STATUSES: dict[str, str] = {
        "Interview Scheduled": "interview_scheduled",
        "Response Received": "response_received",
        "Rejected": "rejection",
    }

    def _scan_notion_for_yield_events(self) -> int:
        """Scan the staging Notion DB for yield-event status changes.

        Reads the last-scan cursor from
        ``<evidence_dir>/.last_notion_scan``, queries Notion for pages
        whose ``Status`` matches one of :data:`_ATS_YIELD_STATUSES` and
        whose ``last_edited_time`` is newer than the cursor, then emits
        an :class:`ATSYieldEvent` for each. Advances the cursor on
        success.

        Never raises — returns the number of events emitted, or 0 on any
        failure (logged). Idempotent across cron retries because
        :func:`append_ats_yield` dedupes on
        ``(listing_id, event_at_iso, event_kind)``.
        """
        if not self.notifier.database_id or not getattr(self.notifier, "_token", ""):
            return 0
        try:
            client = self.notifier._get_client()
        except Exception as e:  # pragma: no cover — defensive
            log.warning("rubric-evidence: notifier client unavailable: %s", e)
            return 0

        cursor = read_last_notion_scan(evidence_dir=self._evidence_dir)
        now_iso = datetime.now(timezone.utc).isoformat()

        try:
            filter_body: dict = {
                "filter": {
                    "or": [
                        {"property": "Status", "select": {"equals": status_name}}
                        for status_name in self._ATS_YIELD_STATUSES
                    ]
                }
            }
            if cursor:
                filter_body["filter"] = {
                    "and": [
                        filter_body["filter"],
                        {
                            "timestamp": "last_edited_time",
                            "last_edited_time": {"after": cursor},
                        },
                    ]
                }

            resp = client.post(
                f"/databases/{self.notifier.database_id}/query",
                json=filter_body,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.warning("rubric-evidence: Notion yield-scan failed: %s", e)
            return 0

        emitted = 0
        for page in data.get("results", []) or []:
            page_id = page.get("id", "") or ""
            edited = page.get("last_edited_time", "") or now_iso
            props = page.get("properties", {}) or {}
            status_prop = props.get("Status", {}) or {}
            status_name = (
                (status_prop.get("select") or {}).get("name", "")
                if isinstance(status_prop, dict)
                else ""
            )
            event_kind = self._ATS_YIELD_STATUSES.get(status_name)
            if not event_kind or not page_id:
                continue
            try:
                if append_ats_yield(
                    ATSYieldEvent(
                        listing_id=page_id,
                        event_at_iso=edited,
                        event_kind=event_kind,
                    ),
                    evidence_dir=self._evidence_dir,
                ):
                    emitted += 1
            except Exception as e:  # pragma: no cover — defensive
                log.warning("rubric-evidence: ats yield emit failed: %s", e)

        try:
            write_last_notion_scan(now_iso, evidence_dir=self._evidence_dir)
        except Exception as e:  # pragma: no cover — defensive
            log.warning("rubric-evidence: scan-cursor write failed: %s", e)

        return emitted

    # -- PREPARE Pipeline --

    async def prepare(self) -> dict:
        """Morning cron: Research → Cover Letters → Outreach Research → Outreach Drafts → Stage."""
        conn = self._init_db()
        audit_id = start_audit(conn, "prepare")
        errors: list[str] = []
        phase_results: dict = {}

        try:
            # Sprint 06.08 — scan Notion for ATS yield events at the
            # start of each cron tick. Best-effort + idempotent (handled
            # inside the helper); never blocks the rest of the pipeline.
            try:
                yield_count = self._scan_notion_for_yield_events()
                phase_results["ats_yield_scan"] = {"emitted": yield_count}
            except Exception as e:  # pragma: no cover — defensive
                log.warning("rubric-evidence: yield scan raised: %s", e)
                phase_results["ats_yield_scan"] = {"emitted": 0, "error": str(e)}

            # Phase 1: Research
            self._seed_dedup_from_db(conn)
            research = await self._research_phase(conn)
            phase_results["research"] = research

            proceed, msg = phase_gate("research", research)
            log.info("Phase gate [research]: %s — %s", "PASS" if proceed else "STOP", msg)
            if not proceed:
                update_audit(conn, audit_id, phase_results, [msg], success=True)
                conn.close()
                return {"phase": "research", "skipped": msg, **research}

            # Get the new listings for outreach (capped)
            new_listings = self._load_new_listings(conn)
            top_listings = new_listings[: self.outreach_cap]

            # Sprint 06.03 — rubric gate splits top_listings into
            # ``passed`` (cover letters + submit + outreach run) and
            # ``filtered`` (still staged in Notion w/ rubric data so the
            # operator can override). When the flag is OFF, ``passed``
            # equals ``top_listings`` and ``filtered`` is empty.
            passed, filtered = self._apply_rubric_gate(conn, top_listings)
            gate_results = {
                "enabled": self._rubric_gate_enabled,
                "threshold": self._rubric_threshold,
                "passed": len(passed),
                "filtered": len(filtered),
                "total": len(top_listings),
            }
            phase_results["rubric_gate"] = gate_results
            proceed, msg = phase_gate("rubric_gate", gate_results)
            log.info("Phase gate [rubric_gate]: %s — %s", "PASS" if proceed else "STOP", msg)

            # Phase 2: Cover Letters — only for listings that passed the gate.
            cl_results = await self._cover_letter_phase(conn, passed)
            phase_results["cover_letters"] = cl_results
            proceed, msg = phase_gate("cover_letters", cl_results)
            log.info("Phase gate [cover_letters]: %s — %s", "PASS" if proceed else "STOP", msg)

            # Phase 3: Auto-Submit Applications (passed only)
            submit_results = await self._submit_phase(conn, passed)
            phase_results["submissions"] = submit_results

            # Phase 4: Outreach Research (passed only — outreach implies intent)
            outreach_results = await self._outreach_research_phase(conn, passed)
            phase_results["outreach_research"] = outreach_results
            proceed, msg = phase_gate("outreach_research", outreach_results)
            log.info("Phase gate [outreach_research]: %s — %s", "PASS" if proceed else "STOP", msg)

            # Phase 5: Outreach Drafts (passed only)
            draft_results = await self._outreach_draft_phase(conn, passed)
            phase_results["outreach_drafts"] = draft_results

            # Phase 6: Stage in Notion — both passed AND filtered are staged
            # so the operator sees the full picture and can override.
            stage_results = await self._staging_phase(conn, top_listings)
            phase_results["staging"] = stage_results
            proceed, msg = phase_gate("staging", stage_results)
            log.info("Phase gate [staging]: %s — %s", "PASS" if proceed else "STOP", msg)

            update_audit(conn, audit_id, phase_results, errors, success=True)

        except Exception as e:
            errors.append(str(e))
            log.error("Prepare pipeline error: %s", e, exc_info=True)
            update_audit(conn, audit_id, phase_results, errors, success=False)
        finally:
            conn.close()

        summary = {
            "run_at": datetime.now().isoformat(),
            "run_type": "prepare",
            "phases": phase_results,
            "errors": errors,
        }
        log.info("Prepare complete: %s", summary)
        return summary

    async def _research_phase(self, conn: sqlite3.Connection) -> dict:
        """Phase 1: Fetch from boards, dedup, filter, save."""
        keywords = self.criteria.keyword_list()
        location = self.criteria.location

        tasks = [board.fetch(keywords, location) for board in self._boards]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_listings: list[JobListing] = []
        for board, result in zip(self._boards, results):
            if isinstance(result, Exception):
                log.error("Board %s raised: %s", board.name, result)
            else:
                all_listings.extend(result)
                # Sprint 02.10: bump scraped per board on success.
                bump_today("scraped", count=len(result), data_dir=self._data_dir)

        saved = 0
        skipped_dup = 0
        skipped_excluded = 0

        for listing in all_listings:
            if saved >= self.criteria.daily_cap:
                break

            combined_text = f"{listing.title} {listing.description}"
            if self.criteria.matches_exclusions(combined_text):
                skipped_excluded += 1
                continue

            if self.dedup.is_duplicate(listing.url, listing.title, listing.company):
                # Sprint 02.10: surface dedup decisions on the funnel.
                bump_today("deduped", data_dir=self._data_dir)
                skipped_dup += 1
                continue

            ats_result = detect_ats(listing.url)
            fp = self.dedup.mark_seen(listing.url, listing.title, listing.company)

            # Sprint 06.03 — score the listing immediately so the rubric
            # result lives in the job_listings table. When the gate flag
            # is OFF (default), skip evaluation entirely so the cron does
            # not pay the Haiku subprocess cost.
            rubric_result: RubricResult | None = None
            if self._rubric_gate_enabled and self._rubric_def is not None:
                try:
                    rubric_result = await rubric_evaluate(
                        listing, self.candidate, self._rubric_def
                    )
                except Exception as e:  # pragma: no cover — defensive
                    log.error(
                        "rubric gate: evaluate raised for '%s' @ %s: %s",
                        listing.title, listing.company, e,
                    )
                    rubric_result = None

            self._save_listing(conn, listing, ats_result.ats, fp, rubric=rubric_result)
            saved += 1

        return {
            "fetched": len(all_listings),
            "saved": saved,
            "skipped_dup": skipped_dup,
            "skipped_excluded": skipped_excluded,
        }

    def _load_new_listings(self, conn: sqlite3.Connection) -> list[tuple[str, JobListing, str]]:
        """Load new listings from DB, ranked by relevance. Returns (fingerprint, listing, ats)."""
        rows = conn.execute(
            "SELECT fingerprint, url, title, company, board, ats, location, compensation, description "
            "FROM job_listings WHERE status = 'new' ORDER BY created_at DESC"
        ).fetchall()
        result = []
        for row in rows:
            fp, url, title, company, board, ats, location, comp, desc = row
            listing = JobListing(
                url=url,
                title=title,
                company=company,
                board=board,
                location=location or "",
                compensation=comp or "",
                description=desc or "",
            )
            result.append((fp, listing, ats or "unknown"))

        # Sort by relevance score (highest first)
        result.sort(key=lambda x: self._score_listing(x[1], x[2]), reverse=True)
        return result

    # Sprint 06.03 — letter grades ordered best → worst. ``_apply_rubric_gate``
    # reads ``self._rubric_threshold`` and includes every grade at-or-better.
    _GRADE_ORDER: tuple[str, ...] = ("A", "B", "C", "D", "F")

    def _apply_rubric_gate(
        self,
        conn: sqlite3.Connection,
        top_listings: list[tuple],
    ) -> tuple[list[tuple], list[tuple]]:
        """Split ``top_listings`` by rubric grade against ``rubric_threshold``.

        Returns ``(passed, filtered)`` preserving the input order. When the
        gate is disabled, every listing is returned in ``passed`` and
        ``filtered`` is empty — callers still get the same shape.

        ``filtered`` listings are NOT discarded — caller is expected to
        keep them in the staging pipeline so the operator can override.
        """
        if not self._rubric_gate_enabled:
            # Sprint 06.08 — gate disabled: emit one ``not_applicable``
            # decision per listing so the harness still records the
            # population. ``rubric_cost_usd`` is 0 in this branch (we
            # didn't pay for an eval). ``estimated_cover_letter_cost``
            # mirrors the operator-set average.
            for entry in top_listings:
                self._emit_gate_decision(
                    listing_id=entry[0],
                    grade="",
                    score=0.0,
                    rubric_cost_usd=0.0,
                    decision=DECISION_NOT_APPLICABLE,
                )
            return list(top_listings), []

        threshold = self._rubric_threshold
        if threshold not in self._GRADE_ORDER:
            log.warning(
                "rubric gate: unknown threshold %r — defaulting to 'B'",
                threshold,
            )
            threshold = "B"
        # Grades at-or-better than threshold pass.
        cutoff_index = self._GRADE_ORDER.index(threshold)
        passing_grades = set(self._GRADE_ORDER[: cutoff_index + 1])

        passed: list[tuple] = []
        filtered: list[tuple] = []
        for entry in top_listings:
            fp = entry[0]
            row = conn.execute(
                "SELECT rubric_grade, rubric_score FROM job_listings WHERE fingerprint = ?",
                (fp,),
            ).fetchone()
            grade = row[0] if row and row[0] else None
            score_raw = row[1] if row and len(row) > 1 else None
            try:
                score = float(score_raw) if score_raw is not None else 0.0
            except (TypeError, ValueError):
                score = 0.0
            if grade in passing_grades:
                passed.append(entry)
                decision_tag = DECISION_PASSED
            elif grade is None:
                # P8.6 / MD-19: Haiku eval call raised earlier (see
                # agent.py prepare path's try/except around
                # rubric_evaluate); the row's rubric_grade was never
                # written. Still fail-closed (listing goes into the
                # filtered bucket so the operator can override in
                # Notion), but emit DECISION_FAILED_EVAL so the daily
                # roll-up can distinguish silent eval failure from a
                # real low-grade reject.
                filtered.append(entry)
                decision_tag = DECISION_FAILED_EVAL
            else:
                # Missing grade (None) is treated as filtered — fail-closed
                # when the gate is enabled. Operator can still override in
                # Notion staging.
                filtered.append(entry)
                decision_tag = DECISION_FILTERED
            # Sprint 06.08 — rubric_cost_usd is not persisted on the
            # listing row (only the grade/score/rationale are), so the
            # cost-saved projection nets the eval against the cover-letter
            # average rather than the per-listing eval cost. The harness
            # stores 0.0 here and ``CoverLetterOutcome.actual_cost_usd``
            # carries the real spend on the passed branch. Sprint 06.08
            # report subtracts a separate aggregate eval cost from a future
            # rubric-cost-tracker sprint.
            self._emit_gate_decision(
                listing_id=fp,
                grade=grade or "",
                score=score,
                rubric_cost_usd=0.0,
                decision=decision_tag,
            )
        return passed, filtered

    def _emit_gate_decision(
        self,
        *,
        listing_id: str,
        grade: str,
        score: float,
        rubric_cost_usd: float,
        decision: str,
    ) -> None:
        """Best-effort GateDecision emission — never raises (Sprint 06.08).

        Wraps the JSONL append in a try/except so a failed evidence write
        never blocks the prepare cron. The harness aims for completeness
        in steady state; we accept dropped records over crashed runs.
        """
        try:
            append_decision(
                GateDecision(
                    listing_id=listing_id,
                    decided_at_iso=datetime.now(timezone.utc).isoformat(),
                    rubric_grade=grade,
                    rubric_score=score,
                    threshold=self._rubric_threshold,
                    decision=decision,
                    rubric_cost_usd=rubric_cost_usd,
                    estimated_cover_letter_cost_usd=self._avg_cover_letter_cost_usd,
                ),
                evidence_dir=self._evidence_dir,
            )
        except Exception as e:  # pragma: no cover — defensive
            log.warning("rubric-evidence: gate decision emit failed: %s", e)

    # Boards that require login to apply — auto-submit will always fail
    _ACCOUNT_REQUIRED_BOARDS: frozenset[str] = frozenset({"dice"})

    # Staffing agency keywords — deprioritize intermediaries
    _STAFFING_KEYWORDS: frozenset[str] = frozenset(
        {
            "staffing",
            "consulting",
            "tek systems",
            "teksystems",
            "bcforward",
            "apex systems",
            "insight global",
            "robert half",
            "randstad",
            "adecco",
            "manpower",
            "kelly services",
            "hays",
        }
    )

    def _score_listing(self, listing: JobListing, ats: str) -> int:
        """Score a listing for relevance ranking. Higher = better fit."""
        score = 0
        title_lower = listing.title.lower()

        # Exact role phrase match (strongest signal)
        for role in self.criteria.roles:
            if role.lower() in title_lower:
                score += 100
                break

        # Seniority match (boosts listings at the right level)
        for level in self.criteria.seniority:
            if level.lower() in title_lower:
                score += 20
                break

        # Supported ATS — can actually auto-submit
        if ats in ("greenhouse", "lever", "ashby"):
            score += 50

        # Has compensation info (transparency signal)
        if listing.compensation:
            score += 10

        # Penalize boards that require login (auto-submit will fail)
        if listing.board in self._ACCOUNT_REQUIRED_BOARDS:
            score -= 200

        # Penalize staffing agencies (prefer direct employers)
        company_lower = listing.company.lower()
        if any(kw in company_lower for kw in self._STAFFING_KEYWORDS):
            score -= 50

        return score

    async def _cover_letter_phase(self, conn: sqlite3.Connection, listings: list[tuple]) -> dict:
        """Phase 2: Generate cover letters for top listings.

        Sprint 02.10: every generated letter is run through
        :func:`lint_cover_letter`. Letters with unresolved placeholder
        tokens, missing company name, or below the minimum word count are
        BLOCKED — the cover letter is not persisted on the listing row, so
        ``_submit_phase`` will pick up an empty cover_letter and the listing
        will not be auto-submitted by the standard happy path.
        """
        generated = 0
        lint_failed = 0
        for fp, listing, _ats in listings:
            if self.candidate.cover_letter_mode != "ai_generated":
                break
            cl = await generate_cover_letter(listing, self.candidate)
            if not cl:
                continue

            # --- Lint gate (Z2-S2.2 wiring, Sprint 02.10) ---
            lint_result = lint_cover_letter(cl, company=listing.company)
            if not lint_result.ok:
                lint_failed += 1
                reason = ",".join(lint_result.failures) or "unknown"
                log.warning(
                    "Cover letter lint failed for fp=%s company=%s: %s",
                    fp, listing.company, reason,
                )
                bump_today("lint_failed", data_dir=self._data_dir)
                # BLOCK: do not persist the letter — submit phase reads an
                # empty cover_letter and skips the auto-submit happy path.
                continue

            bump_today("lint_passed", data_dir=self._data_dir)
            bump_today("covered", data_dir=self._data_dir)

            conn.execute(
                "UPDATE job_listings SET cover_letter = ? WHERE fingerprint = ?", (cl, fp)
            )
            conn.commit()
            generated += 1
            # Sprint 06.08 — emit CoverLetterOutcome immediately after the
            # letter is persisted. ``actual_cost_usd`` falls back to the
            # operator-tunable average until ``generate_cover_letter``
            # exposes per-call cost (separate sprint). ``submitted`` is
            # False here; the submit phase runs next and a follow-up
            # sprint will amend with the post-submit signal.
            try:
                append_cover_letter_outcome(
                    CoverLetterOutcome(
                        listing_id=fp,
                        completed_at_iso=datetime.now(timezone.utc).isoformat(),
                        actual_cost_usd=self._avg_cover_letter_cost_usd,
                        submitted=False,
                    ),
                    evidence_dir=self._evidence_dir,
                )
            except Exception as e:  # pragma: no cover — defensive
                log.warning(
                    "rubric-evidence: cover-letter outcome emit failed: %s", e
                )
        return {
            "generated": generated,
            "lint_failed": lint_failed,
            "attempted": len(listings),
        }

    async def _submit_phase(self, conn: sqlite3.Connection, listings: list[tuple]) -> dict:
        """Phase 3: Auto-submit applications via Playwright browser automation.

        Cloudflare-blocked listings are recorded with status='blocked' rather than 'failed'.
        After the first Cloudflare block on a domain, that domain is quarantined for the
        remainder of this run so subsequent listings on the same domain are skipped immediately.
        """
        submitted = 0
        blocked = 0
        failed = 0

        for fp, listing, ats in listings:
            # Skip quarantined domains without launching the browser
            if _is_quarantined(listing.url):
                log.info(
                    "Skipping '%s' @ %s — domain quarantined (Cloudflare) this run",
                    listing.title,
                    listing.company,
                )
                conn.execute(
                    "UPDATE job_listings SET status = 'blocked' WHERE fingerprint = ?", (fp,)
                )
                conn.commit()
                blocked += 1
                continue

            # Get cover letter
            row = conn.execute(
                "SELECT cover_letter FROM job_listings WHERE fingerprint = ?", (fp,)
            ).fetchone()
            cover_letter = row[0] if row and row[0] else ""

            result = await apply_to_job(listing, self.candidate, cover_letter)

            if result.cloudflare_blocked:
                # Quarantine this domain for the remainder of the run
                domain = urlparse(listing.url).netloc.lower()
                quarantine_domain(domain)
                log.warning(
                    "Cloudflare block — quarantining domain '%s' for this run ('%s' @ %s)",
                    domain,
                    listing.title,
                    listing.company,
                )
                conn.execute(
                    "UPDATE job_listings SET status = 'blocked' WHERE fingerprint = ?", (fp,)
                )
                conn.commit()
                blocked += 1
            elif result.submitted:
                conn.execute(
                    "UPDATE job_listings SET status = 'applied', applied_at = datetime('now') "
                    "WHERE fingerprint = ?",
                    (fp,),
                )
                conn.commit()
                submitted += 1
                # Sprint 02.10: surface successful submits on the funnel.
                bump_today("submitted", data_dir=self._data_dir)
                log.info("Submitted application for '%s' @ %s", listing.title, listing.company)
            elif result.success:
                # Form was filled but submit wasn't confirmed
                failed += 1
                log.warning(
                    "Form filled but submit unconfirmed for '%s': %s",
                    listing.title,
                    result.notes[:200],
                )
            elif "Blocked:" in result.notes:
                blocked += 1
                log.info("Application blocked for '%s': %s", listing.title, result.notes)
            else:
                failed += 1
                log.error(
                    "Application failed for '%s': %s", listing.title, result.notes[:200]
                )

        return {"submitted": submitted, "blocked": blocked, "failed": failed, "attempted": len(listings)}

    async def _outreach_research_phase(
        self, conn: sqlite3.Connection, listings: list[tuple]
    ) -> dict:
        """Phase 4: Research decision-makers at each company."""
        total_contacts = 0
        failed_companies = 0

        for fp, listing, _ats in listings:
            contacts = await research_decision_makers(listing.company, listing.url, listing.title)

            if not contacts:
                failed_companies += 1
                continue

            for slot, contact in enumerate(contacts[:2], start=1):
                conn.execute(
                    """INSERT INTO outreach_contacts
                        (listing_fingerprint, name, title, email, company, personalization_hook, slot)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        fp,
                        contact.name,
                        contact.title,
                        contact.email,
                        contact.company,
                        contact.hook,
                        slot,
                    ),
                )
                total_contacts += 1

            conn.commit()

        return {
            "total_contacts": total_contacts,
            "failed_companies": failed_companies,
            "attempted": len(listings),
        }

    async def _outreach_draft_phase(self, conn: sqlite3.Connection, listings: list[tuple]) -> dict:
        """Phase 5: Draft outreach emails for each contact."""
        drafted = 0

        for fp, listing, _ats in listings:
            rows = conn.execute(
                "SELECT id, name, title, email, company, personalization_hook, slot "
                "FROM outreach_contacts WHERE listing_fingerprint = ? AND draft_email IS NULL",
                (fp,),
            ).fetchall()

            for row in rows:
                cid, name, title, email, company, hook, slot = row
                contact = Contact(name=name, title=title, email=email, company=company, hook=hook or "")

                draft = await draft_outreach_email(contact, listing, self.candidate)
                if draft:
                    conn.execute(
                        "UPDATE outreach_contacts SET draft_subject = ?, draft_email = ? WHERE id = ?",
                        (draft.subject, draft.body, cid),
                    )
                    conn.commit()
                    drafted += 1

        return {"drafted": drafted}

    async def _staging_phase(self, conn: sqlite3.Connection, listings: list[tuple]) -> dict:
        """Phase 6: Stage everything in Notion.

        Status mapping:
          applied  → "Applied"  (auto-submitted in Phase 3)
          blocked  → "Blocked"  (Cloudflare-quarantined)
          other    → "Staged"   (awaiting operator approval)
        """
        staged = 0
        stage_errors = 0

        for fp, listing, ats in listings:
            row = conn.execute(
                "SELECT cover_letter, status, rubric_grade, rubric_score, "
                "rubric_rationale, rubric_evaluated_at "
                "FROM job_listings WHERE fingerprint = ?",
                (fp,),
            ).fetchone()
            cover_letter = row[0] if row and row[0] else ""
            current_status = row[1] if row else "new"

            # Sprint 06.04 — package rubric data for Notion. ``rubric_rationale``
            # is stored as JSON-encoded ``per_dim_rationale`` (Sprint 06.03);
            # we surface the raw string and let Notion render it. Decision is
            # always ``"pending"`` at write time — operator flips to
            # ``"approved"`` / ``"rejected"`` from the Notion side.
            rubric_stage: RubricStageData | None = None
            if row and row[2] and row[5]:
                rubric_stage = RubricStageData(
                    letter_grade=str(row[2]),
                    weighted_score=float(row[3]) if row[3] is not None else 0.0,
                    rationale=str(row[4] or ""),
                    evaluated_at=str(row[5]),
                    decision="pending",
                )

            # Load contacts and drafts
            contact_rows = conn.execute(
                "SELECT name, title, email, company, personalization_hook, "
                "draft_subject, draft_email, slot "
                "FROM outreach_contacts WHERE listing_fingerprint = ? ORDER BY slot",
                (fp,),
            ).fetchall()

            contacts: list[Contact] = []
            drafts: list[OutreachDraft] = []
            for cr in contact_rows:
                c = Contact(name=cr[0], title=cr[1], email=cr[2], company=cr[3], hook=cr[4] or "")
                contacts.append(c)
                if cr[5] and cr[6]:  # draft_subject and draft_email
                    drafts.append(OutreachDraft(contact=c, subject=cr[5], body=cr[6], slot=cr[7]))

            if current_status == "applied":
                notion_status = "Applied"
            elif current_status == "blocked":
                notion_status = "Blocked"
            else:
                notion_status = "Staged"

            page_id = stage_listing(
                self.notifier,
                listing,
                ats,
                cover_letter,
                contacts,
                drafts,
                status=notion_status,
                # Sprint 02.10: record approval-time snapshot so EXECUTE
                # can detect edit-after-approval drift (Z2-S2.3).
                snapshot_store=self.snapshot_store,
                # Sprint 06.04: thread rubric data + gate-state so the
                # operator sees grade / score / rationale / decision in
                # Notion and can override the gate's call.
                rubric=rubric_stage,
                rubric_gate_enabled=self._rubric_gate_enabled,
            )
            if page_id:
                conn.execute(
                    "UPDATE job_listings SET notion_page_id = ? WHERE fingerprint = ?",
                    (page_id, fp),
                )
                # Don't overwrite 'applied' or 'blocked' statuses
                if current_status not in ("applied", "blocked"):
                    conn.execute(
                        "UPDATE job_listings SET status = 'staged' WHERE fingerprint = ?",
                        (fp,),
                    )
                conn.commit()
                staged += 1
                # Sprint 02.10: surface successful Notion stages on the funnel.
                bump_today("staged", data_dir=self._data_dir)
            else:
                stage_errors += 1

        return {"staged": staged, "errors": stage_errors, "total": len(listings)}

    # -- EXECUTE Pipeline --

    async def execute(self) -> dict:
        """Execution cron: Check Notion approvals → Submit → Send."""
        conn = self._init_db()
        audit_id = start_audit(conn, "execute")
        errors: list[str] = []

        approved_items = check_approvals(self.notifier)

        # P8.6 / MD-16: applications are auto-submitted in PREPARE; EXECUTE
        # only sends outreach. Per ``execute_approved`` docstring + the
        # ``ExecutionResult.application_submitted is False`` assertion in
        # ``test_approval.py``, EXECUTE never increments an apply counter.
        # The previous ``applications`` counter was structurally always 0
        # and confused operators reading the run summary. Removed.
        outreach_sent = 0
        exec_errors = 0

        for item in approved_items:
            # Resolve fingerprint from Notion page_id
            from .approval import resolve_fingerprint

            item.fingerprint = resolve_fingerprint(conn, item.page_id)
            if not item.fingerprint:
                errors.append(f"No fingerprint for page {item.page_id}")
                exec_errors += 1
                continue

            # Sprint 02.10: thread snapshot_store so the edit-after-approval
            # drift gate runs on every outreach send.
            result = execute_approved(
                item,
                self.candidate,
                conn,
                self.notifier,
                snapshot_store=self.snapshot_store,
                data_dir=Path(self._data_dir) if self._data_dir else None,
            )

            if result.outreach_1_sent:
                outreach_sent += 1
                bump_today("sent", data_dir=self._data_dir)
            if result.outreach_2_sent:
                outreach_sent += 1
                bump_today("sent", data_dir=self._data_dir)
            if result.errors:
                errors.extend(result.errors)
                exec_errors += len(result.errors)

        phase_results = {
            "approved_count": len(approved_items),
            "outreach_sent": outreach_sent,
            "errors": exec_errors,
        }

        update_audit(conn, audit_id, phase_results, errors, success=exec_errors == 0)
        conn.close()

        summary = {
            "run_at": datetime.now().isoformat(),
            "run_type": "execute",
            "executed": outreach_sent,
            **phase_results,
        }
        log.info("Execute complete: %s", summary)
        return summary


async def main() -> None:
    """Entry point for standalone testing."""
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stdout,
    )
    mode = sys.argv[1] if len(sys.argv) > 1 else "prepare"
    agent = JobSearchAgent()
    if mode == "execute":
        summary = await agent.execute()
    else:
        summary = await agent.prepare()
    print(summary)


if __name__ == "__main__":
    asyncio.run(main())
