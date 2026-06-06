#!/usr/bin/env python3
"""Autonomous Self-Improvement Experiment Loop.

Autonomous self-improvement loop. Runs as a KeepAlive LaunchDaemon under
the `bumba` user on the source repo. Each iteration:
  1. Pick an experiment idea (via claude -p)
  2. Apply changes in an isolated git worktree
  3. Run pytest — if all pass, fast-forward merge to main
  4. Log result and notify Discord

Modeled on scripts/deploy_helper.py.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sqlite3
import subprocess
import sys
import time
import types
import uuid
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Sprint audit-2026-05-15.B.01 (issue #1996) — runtime mode trichotomy.
VALID_MODES = frozenset({"proposal_only", "shadow", "production"})

# Sprint audit-2026-05-15.B.02 (issue #1997) — per-mode merge policy seam.
# The seam collapses the three "if is_shadow_iteration" branches the
# original loop carried into one ``policy.pre_outcome(...)`` (proposal_only)
# or ``policy.post_outcome(ctx)`` (shadow / production) call. The
# ``_experiment`` package sits next to this script and is loaded via the
# same ``sys.path.insert(...)`` shim the test suite uses.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from _experiment.merge_policy import (  # noqa: E402 — sys.path tweak above
    IterationContext,
    PrePolicy,
    select_policy,
)

# ── Configuration ──────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # bumba-open-harness
AGENT_DIR = REPO_ROOT / "agent"
PROGRAM_PATH = AGENT_DIR / "config" / "experiment-program.md"
WORKTREE_BASE = Path("/tmp/bumba-experiments")
DATA_DIR = AGENT_DIR / "data"
DB_PATH = DATA_DIR / "experiments.db"
# Sprint audit-2026-05-15.D.02 (#2004) — machine-readable iteration
# snapshot. Distinct from EXPERIMENT_HEARTBEAT_PATH (defined further
# down) which is the bridge's /healthz heartbeat. This file is for
# operator tooling (/status, readiness.sh, jq) that wants live mode +
# iteration cadence without grepping log files. C.05 (#2002) seeded
# the path with a "paused_halt" placeholder write; D.02 extends it
# into a per-iteration JSON snapshot.
HEARTBEAT_PATH = DATA_DIR / "experiment-heartbeat.json"
SECRETS_PATH = Path("/opt/bumba-harness/data/.secrets")
# Where Claude looks for its own state (OAuth, settings.json, ~/.claude/).
# Override these when running the loop under a dedicated runtime account.
CLAUDE_HOME = Path(os.environ.get("BUMBA_CLAUDE_HOME", "/opt/bumba-harness"))
LOG_FILE = AGENT_DIR / "logs" / "experiment-loop.log"
CLAUDE_BIN = Path(os.environ.get("BUMBA_CLAUDE_BIN", "claude"))

EXPERIMENT_BUDGET_USD = 2.0   # per-day budget for experiments
COOLDOWN_SECONDS = 600        # 10 min between experiments
CLAUDE_TIMEOUT = 600          # 10 min for code generation (raised 300→600 2026-05-10 in lockstep with bridge claude_timeout — research-heavy prompts can go silent for >300s while Claude synthesizes results)
PYTEST_TIMEOUT = 300          # 5 min for test suite

# Sprint 02.04 / spec ref-audit-02-05 (issue #979) — MAD confidence
# scoring on fitness deltas. Window = number of recent iterations to
# pull from experiments.jsonl when computing the noise floor; K =
# multiplier on MAD that produces the confidence band (~95% CI under
# typical non-Gaussian noise at K = 2.0). The same defaults are
# mirrored on bridge.config.BridgeConfig.experiment_mad_*.
MAD_WINDOW = 20
MAD_K = 2.0

# Forbidden-files set: kernel-immutable files (canonical from tier_manager)
# unioned with experiment-loop-specific concerns (database, hooks, plists).
# Single source of truth for the kernel files; the extras here document
# experiment-loop's broader write-protection scope.
sys.path.insert(0, str(AGENT_DIR))
from bridge.tier_manager import IMMUTABLE_FILES  # noqa: E402
from bridge.config import BridgeConfig  # noqa: E402 — sys.path mutated above

EXPERIMENT_LOOP_EXTRA_FORBIDDEN: frozenset[str] = frozenset({
    "hooks/",
    "database.py",
    ".plist",
})
FORBIDDEN_FILES: frozenset[str] = IMMUTABLE_FILES | EXPERIMENT_LOOP_EXTRA_FORBIDDEN

# Sprint 02.06: before/after hook contract. The runner is a sibling
# module (kept private with a leading underscore so launchd doesn't
# load it as a service entry point).
from _hook_runner import (  # noqa: E402  — sys.path mutated above
    HookResult,
    ensure_hook_dirs,
    run_hooks,
    summarize_results,
)

# Sprint 02.07b — backpressure gates (ruff + mypy) after pytest. Spec:
# docs/specs/2026-04-25-reference-audit/spec-02-07b-add-ruff-mypy-backpressure-gates-after-pytest.md
# Issue #982. Imported here (not lazily) because the gate is a hard
# dependency of validate_experiment — failing to import means the whole
# loop should fail loudly, not silently skip the gate.
from experiment_quality_gates import (  # noqa: E402  — sys.path mutated above
    GateResult,
    all_passed as quality_gates_all_passed,
    run_quality_gates,
    summarize as summarize_quality_gates,
)

# Sprint audit-2026-05-16.E.04 (#2072, Section 8.6) — first three leaf
# seams moved to ``bridge.experiment_runtime`` ahead of the formal
# demote-split (still scheduled for 2026-05-30). The trailer key,
# trailer-append helper, validator-cost parser, and halt-policy
# factory are re-exported here so existing call sites keep working
# bit-for-bit. The dependency direction is one-way: this module
# imports from ``bridge.experiment_runtime``; the reverse is forbidden.
from bridge.experiment_runtime import (  # noqa: E402, F401
    _EXPERIMENT_TRAILER_KEY,
    _append_experiment_trailers,
    _build_halt_policy as _build_halt_policy_runtime,
    _parse_validator_subprocess_cost,
)


# Sprint 02.14 / spec ref-audit-02-14 (issue #989) — holdout validator
# subprocess that judges the diff against the program from origin/main.
# Imported here so any import-time failure (e.g. missing dependency) is
# loud — but invocation is gated by the operator-controlled feature flag
# ``BridgeConfig.experiment_validator_enabled`` and wrapped in a fail-
# soft try/except in validate_experiment.
from experiment_holdout_validator import (  # noqa: E402 — sys.path mutated above
    HoldoutValidatorVerdict,
    ValidatorInput,
    ValidatorResult,
    get_origin_main_sha,
    run_validator,
)

# Sprint 15.02 / spec ref-audit-15-02 (issue #1052) — wire the mailbox
# primitive (PR #1153) into the experiment-loop worktree boundary so the
# subprocess can stream progress / intermediate-fitness / crash messages
# back to the bridge during the run, and the bridge can ship cancel
# requests in the other direction. Default is OFF; the operator opts in
# via ``BridgeConfig.experiment_mailbox_enabled``.
from bridge.mailbox import (  # noqa: E402 — sys.path mutated above
    Mailbox,
    MailboxConfig,
    MailboxMessage,
)
from experiment_mailbox_worker import (  # noqa: E402 — sys.path mutated above
    ENV_MAILBOX_DATA_DIR,
    ENV_MAILBOX_NAME,
)

# Sprint 02.04 / spec ref-audit-02-04 (issue #978) — append-only
# ``autoresearch/iter-NNNN`` audit-branch trail. Default OFF; the
# operator opts in via ``BridgeConfig.experiment_audit_branches_enabled``.
# Push to origin is a separate flag because pushing 1000+ branches/year
# is a storage decision the operator must opt into independently.
from experiment_audit_branches import (  # noqa: E402 — sys.path mutated above
    AuditBranchResult,
    create_audit_branch,
    annotate_branch_with_outcome,
)

# Mailbox name + data dir for the experiment-loop bridge↔worker channel.
# The schema_version is kept at 1 — bumps come with a migration story.
EXPERIMENT_MAILBOX_NAME = "experiment_loop"
EXPERIMENT_MAILBOX_CONFIG = MailboxConfig(
    name=EXPERIMENT_MAILBOX_NAME,
    data_dir=DATA_DIR,
    schema_version=1,
)

# ── Logging ────────────────────────────────────────────────────

log = logging.getLogger("experiment-loop")


def _setup_logging() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout),
        ],
    )


def _ensure_column(db: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    """Idempotently add ``column`` to ``table`` if missing.

    Mirrors the ``JobSearchAgent._ensure_column`` pattern at
    ``agent/job_search/agent.py:193`` — SQLite does not parameterize
    DDL identifiers, and ``column`` / ``col_type`` come exclusively
    from internal callers passing string literals.
    """
    cursor = db.execute(f"PRAGMA table_info({table})")  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
    columns = {row[1] for row in cursor.fetchall()}
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query


def _migrate_status_check(db: sqlite3.Connection) -> None:
    """Widen experiment_log.status CHECK to include shadow + proposal + halt values.

    Idempotent — detects the new CHECK on the live table and skips if already
    migrated. SQLite cannot ALTER a CHECK constraint, so we use the standard
    swap-table recipe.
    """
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='experiment_log'"
    ).fetchone()
    if row is None or "shadow_keep" in (row[0] or ""):
        return  # fresh DB (new CHECK already in CREATE) OR already migrated
    # Python's sqlite3 implicitly opens a tx; close it before our explicit one.
    # Without this, `BEGIN` raises "cannot start a transaction within a transaction".
    db.commit()
    db.execute("BEGIN")
    try:
        db.execute("""
            CREATE TABLE experiment_log_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                commit_hash TEXT,
                branch TEXT,
                tests_passed INTEGER,
                tests_failed INTEGER,
                tests_total INTEGER,
                status TEXT CHECK(status IN (
                    'keep', 'discard', 'crash',
                    'shadow_keep', 'shadow_discard', 'shadow_crash',
                    'proposal_skipped', 'halted_pre_merge'
                )),
                description TEXT,
                diff_summary TEXT,
                cost_usd REAL DEFAULT 0.0,
                duration_seconds REAL,
                created_at TEXT DEFAULT (datetime('now')),
                fitness_delta REAL DEFAULT NULL
            )
        """)
        db.execute("INSERT INTO experiment_log_new SELECT * FROM experiment_log")
        db.execute("DROP TABLE experiment_log")
        db.execute("ALTER TABLE experiment_log_new RENAME TO experiment_log")
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise


def _ensure_db() -> None:
    """Create the experiments DB and table if they don't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH))
    db.execute("""CREATE TABLE IF NOT EXISTS experiment_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        commit_hash TEXT,
        branch TEXT,
        tests_passed INTEGER,
        tests_failed INTEGER,
        tests_total INTEGER,
        status TEXT CHECK(status IN (
            'keep', 'discard', 'crash',
            'shadow_keep', 'shadow_discard', 'shadow_crash',
            'proposal_skipped', 'halted_pre_merge'
        )),
        description TEXT,
        diff_summary TEXT,
        cost_usd REAL DEFAULT 0.0,
        duration_seconds REAL,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    # Sprint 02.02 — fitness metric column. Idempotent for existing DBs.
    _ensure_column(db, "experiment_log", "fitness_delta", "REAL DEFAULT NULL")
    # Sprint audit-2026-05-15.A.02 — widen the CHECK on legacy DBs that
    # were created with only ('keep', 'discard', 'crash'). Must run AFTER
    # _ensure_column(fitness_delta) so the swap-table INSERT can copy
    # the column shape.
    _migrate_status_check(db)
    db.commit()
    db.close()


# ── Signal handling ────────────────────────────────────────────

_shutdown = False


def _handle_signal(signum: int, frame: object) -> None:
    global _shutdown
    log.info("Received signal %d, shutting down gracefully", signum)
    _shutdown = True


# ── Halt-flag honoring ─────────────────────────────────────────
# Sprint audit-2026-05-15.C.05 (issue #2002) — extend the `/halt` operator
# command's scope from the bridge daemon to this loop. The bridge's
# ``SecurityManager.is_halted()`` reads ``Path(config.data_dir) / "halt.flag"``
# (see ``bridge/security.py``). We deliberately do NOT instantiate
# ``SecurityManager`` here: it requires a ``Database`` + ``BridgeConfig``
# constructor pair this script doesn't otherwise own. Reading the same file
# directly is bit-for-bit identical and keeps the script's dependency surface
# narrow.

def _halt_flag_path(cfg: BridgeConfig) -> Path:
    """Resolve halt.flag path the same way SecurityManager does."""
    return Path(cfg.data_dir) / "halt.flag"


def _check_halt(cfg: BridgeConfig | None) -> tuple[bool, str | None]:
    """Return (halted, reason). reason is None when not halted or unreadable.

    ``cfg=None`` (the fail-soft path when ``load_config`` raised at
    startup) degrades to "not halted" so the loop keeps making progress
    rather than wedging on a config-lookup error.
    """
    if cfg is None:
        return False, None
    path = _halt_flag_path(cfg)
    if not path.exists():
        return False, None
    try:
        reason = path.read_text(encoding="utf-8").strip() or None
    except OSError:
        reason = None
    return True, reason


# ── Sprint audit-2026-05-16.C.03 (#2058) ───────────────────────
# Halt checkpoints + cancellable subprocesses. C.05 already extended
# /halt to the iteration-boundary top-of-loop check and the production
# pre-merge check. C.03 closes the in-flight gap: long-running
# subprocesses (pytest validator, claude apply) now consult the shared
# ``bridge.halt`` contract via a thin adapter around ``_check_halt`` and
# abort cleanly when halt fires mid-run. The HaltPolicy object is built
# once per loop lifetime and reused across iterations; the underlying
# halt-flag read is the same one C.05 wired so behavior is bit-for-bit
# identical to ``SecurityManager.is_halted()`` and the two helpers
# share a single source of truth (one file).


class _HaltCancelled(RuntimeError):
    """Raised by ``_run_subprocess_cancellable`` when halt fires mid-run.

    Internal control-flow signal — caught at iteration boundaries in
    ``main()`` and inside ``validate_experiment`` to translate the
    abort into a structured ``halted_in_flight`` record rather than
    leaking up as a crash. The message embeds the surface key + halt
    reason for operator logs.
    """


def _build_loop_halt_policy(cfg: BridgeConfig | None):
    """Build a ``HaltPolicy`` bound to ``<data_dir>/halt.flag``.

    Thin wrapper over ``bridge.experiment_runtime._build_halt_policy``
    (moved out by Sprint audit-2026-05-16.E.04, #2072). Resolves
    ``cfg.data_dir`` to a Path so the runtime factory stays decoupled
    from BridgeConfig, and degrades to a permanently-unblocked policy
    when ``cfg is None`` (mirrors ``_check_halt(None)`` fail-soft
    semantics — startup config-load failures must not wedge the loop).
    """
    from bridge.halt import HaltPolicy

    if cfg is None:
        # Permanently-unblocked policy — load_config failed at startup
        # and there is no halt.flag path to consult.
        return HaltPolicy(is_halted=lambda: False, halt_reason=lambda: None)
    return _build_halt_policy_runtime(Path(cfg.data_dir))


def _run_subprocess_cancellable(
    cmd: list[str],
    *,
    halt_policy,
    surface: str,
    timeout: float,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    capture_output: bool = True,
    text: bool = True,
    poll_interval: float = 0.25,
):
    """Run ``cmd`` with cooperative cancellation on halt.

    Polls ``halt_policy.check_continue(surface)`` every ``poll_interval``
    seconds while the subprocess runs. On halt: ``terminate()`` →
    ``wait(timeout=3)`` → ``kill()`` fallback so we never leave a
    zombie. On halt-cancel raises :class:`_HaltCancelled` carrying the
    surface-tagged reason from the policy decision. On per-call
    ``timeout`` raises :class:`subprocess.TimeoutExpired` (drop-in
    compatible with the existing ``subprocess.run(..., timeout=...)``
    call sites — every caller already had a ``except TimeoutExpired``
    branch).

    Returns a ``subprocess.CompletedProcess``-compatible namespace
    carrying ``returncode``, ``stdout``, ``stderr`` so existing call
    sites that read those fields don't need to change.
    """
    stdout_pipe = subprocess.PIPE if capture_output else None
    stderr_pipe = subprocess.PIPE if capture_output else None
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        stdout=stdout_pipe,
        stderr=stderr_pipe,
        text=text,
    )
    deadline = time.monotonic() + float(timeout)
    try:
        while True:
            decision = halt_policy.check_continue(surface)
            if decision.blocked:
                _terminate_subprocess_cleanly(proc)
                raise _HaltCancelled(
                    decision.reason or f"halt flag set (surface={surface})"
                )
            try:
                stdout_data, stderr_data = proc.communicate(timeout=poll_interval)
            except subprocess.TimeoutExpired:
                # poll_interval elapsed; check halt again before retrying.
                if time.monotonic() >= deadline:
                    _terminate_subprocess_cleanly(proc)
                    raise subprocess.TimeoutExpired(cmd, timeout)
                continue
            return _CompletedProcessLike(
                returncode=proc.returncode,
                stdout=stdout_data if stdout_data is not None else "",
                stderr=stderr_data if stderr_data is not None else "",
            )
    except _HaltCancelled:
        raise
    except subprocess.TimeoutExpired:
        raise
    except BaseException:
        # Belt-and-suspenders: any unexpected exception (KeyboardInterrupt
        # from operator Ctrl+C, OSError mid-poll, ...) must still leave
        # no zombie behind.
        _terminate_subprocess_cleanly(proc)
        raise


def _terminate_subprocess_cleanly(proc) -> None:
    """terminate → wait(3) → kill fallback. Never raises into caller."""
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
    except Exception as exc:  # noqa: BLE001 — termination is best-effort
        log.warning("subprocess termination failed: %s", exc)


class _CompletedProcessLike:
    """Tiny duck-type for ``subprocess.CompletedProcess`` so callers
    that read ``.returncode`` / ``.stdout`` / ``.stderr`` work
    unchanged. Distinct from the real class because Popen + communicate
    doesn't construct one for us.
    """

    __slots__ = ("returncode", "stdout", "stderr")

    def __init__(self, *, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _iterations_today() -> int | None:
    """Count ``experiment_log`` rows created since 00:00 UTC today.

    Sprint audit-2026-05-15.D.02 (#2004). Drives the
    ``iteration_count_today`` field in the heartbeat JSON so operators
    can spot-check iteration cadence without opening the SQLite DB.

    Returns ``None`` when the DB is unavailable — heartbeat is
    best-effort and must never raise into the loop.

    Schema note: ``experiment_log`` has ``created_at TEXT DEFAULT
    (datetime('now'))`` (UTC by SQLite's contract), not a
    ``started_at`` column. We compare ``created_at`` against an
    ISO start-of-day timestamp. The default value SQLite writes is
    ``YYYY-MM-DD HH:MM:SS`` (no ``T``, no timezone suffix); the
    comparison is still lexicographically sound because both sides
    share the ``YYYY-MM-DD`` prefix and the start-of-day value will
    sort below any later same-day timestamp.
    """
    try:
        start = datetime.now(tz=timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(str(DB_PATH)) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM experiment_log WHERE created_at >= ?",
                (start,),
            ).fetchone()
        return int(row[0]) if row else 0
    except Exception:  # noqa: BLE001 — heartbeat is best-effort
        return None


# ── Sprint audit-2026-05-16.A.05 (#2049, Section 8.3) ─────────
# Operator throttle for the first production unhalt. Two opt-in knobs:
# hourly iteration cap + cooldown after a successful merge. Both default
# to "no throttle" so pre-A.05 behaviour is preserved when the operator
# leaves the new ``[experiment_loop]`` fields unset.


@dataclass(frozen=True)
class ExperimentThrottle:
    """A.05 (#2049) — operator throttle for first production unhalt.

    Both fields opt-in: ``None`` / ``0`` mean "no throttle" and preserve
    the pre-A.05 behaviour. Heartbeat surfaces every throttle decision
    so operators can spot-check throttle headroom without grepping logs.
    """

    max_iterations_per_hour: int | None = None
    cooldown_after_merge_seconds: int = 0


def _iterations_in_last_hour() -> int | None:
    """Count ``experiment_log`` rows created in the last 60 minutes.

    Sprint audit-2026-05-16.A.05 (#2049). Mirrors ``_iterations_today``
    shape — best-effort, returns ``None`` on DB error so the throttle
    fail-open in observability surfaces but the decision logic interprets
    ``None`` as "unknown count" (see ``_should_start_iteration``).

    Schema note: ``experiment_log.created_at`` is ``TEXT DEFAULT
    (datetime('now'))`` which writes UTC ``YYYY-MM-DD HH:MM:SS``
    (lexicographically sortable with the threshold we build below).
    """
    try:
        cutoff = (
            datetime.now(tz=timezone.utc) - timedelta(hours=1)
        ).strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(str(DB_PATH)) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM experiment_log WHERE created_at >= ?",
                (cutoff,),
            ).fetchone()
        return int(row[0]) if row else 0
    except Exception:  # noqa: BLE001 — throttle is best-effort
        return None


def _seconds_since_last_merge() -> float | None:
    """Return wall-clock seconds since the most recent merged iteration.

    Sprint audit-2026-05-16.A.05 (#2049). ``None`` means "no prior
    merge" (and therefore no cooldown anchor) OR "DB unavailable" —
    both fail-open from the throttle's perspective.

    Reads ``experiment_log`` for rows whose ``status = 'merged'`` and
    diffs the most recent ``created_at`` against ``datetime.now(utc)``.
    Parses the SQLite default-value format (``YYYY-MM-DD HH:MM:SS``,
    UTC) defensively — any parse failure degrades to ``None``.
    """
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            row = conn.execute(
                "SELECT MAX(created_at) FROM experiment_log "
                "WHERE status = 'merged'"
            ).fetchone()
        if not row or row[0] is None:
            return None
        try:
            last = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return None
        delta = datetime.now(tz=timezone.utc) - last
        return max(0.0, delta.total_seconds())
    except Exception:  # noqa: BLE001 — throttle is best-effort
        return None


def _should_start_iteration(
    throttle: ExperimentThrottle,
    *,
    now_iter_count_last_hour: int | None,
    now_seconds_since_merge: float | None,
) -> tuple[bool, str | None]:
    """Decide whether the next iteration may start under the throttle.

    Sprint audit-2026-05-16.A.05 (#2049). Returns ``(ok, reason)``.
    ``reason`` is ``None`` on ``ok=True``; on ``ok=False`` it is a short
    string fit for heartbeat + log surfaces (e.g. ``"hourly_throttle"``
    or ``"merge_cooldown:42s_remaining"``).

    Fail-open on unknown counts: if ``_iterations_in_last_hour`` returns
    ``None`` (DB unavailable), treat as "throttle doesn't apply" and let
    the iteration proceed — the operator's observation gate (E.05)
    catches DB-availability regressions separately. Same fail-open
    posture applies to ``now_seconds_since_merge`` (``None`` means "no
    prior merge" so no cooldown anchor).
    """
    cap = throttle.max_iterations_per_hour
    if (
        cap is not None
        and now_iter_count_last_hour is not None
        and now_iter_count_last_hour >= cap
    ):
        return False, f"hourly_throttle:{now_iter_count_last_hour}/{cap}"

    cooldown = throttle.cooldown_after_merge_seconds
    if (
        cooldown > 0
        and now_seconds_since_merge is not None
        and now_seconds_since_merge < cooldown
    ):
        remaining = int(cooldown - now_seconds_since_merge)
        return False, f"merge_cooldown:{remaining}s_remaining"

    return True, None


def _write_heartbeat(
    mode: str,
    status: str,
    branch: str | None,
    *,
    throttle: ExperimentThrottle | None = None,
    throttle_decision: str | None = None,
    audit_branches_enabled: bool | None = None,
    audit_branches_mode: str | None = None,
    audit_branches_local_cleanup: bool | None = None,
    audit_branches_last_branch: str | None = None,
    audit_branches_last_cleanup_status: str | None = None,
) -> None:
    """Write a one-line JSON heartbeat snapshot atomically.

    Sprint audit-2026-05-15.D.02 (#2004). Surfaced by ``/status`` and
    ``readiness.sh`` so operators can see live mode + iteration cadence
    without grepping ``experiment-loop.log``. Best-effort: any write
    failure is logged and swallowed so the experiment loop continues.

    Sprint audit-2026-05-16.A.05 (#2049) extends the payload with a
    ``throttle`` block when the loop passes in its active
    ``ExperimentThrottle`` + the most recent throttle decision label.
    Back-compat: callers that omit the kwargs (legacy halt / shutdown
    paths) get the pre-A.05 schema with ``throttle`` absent.

    Sprint audit-2026-05-16.E.02 (#2070) extends the payload with an
    ``audit_branches`` block when the caller passes any of the
    ``audit_branches_*`` kwargs. The block surfaces the
    off/local/remote mode, the local-cleanup gate, and the most recent
    branch + cleanup status so the operator can spot-check trial
    lifecycle from ``/status`` without grepping logs.

    Payload shape::

        {
          "mode":                   "shadow",
          "last_iteration_at":      "2026-05-16T03:30:00+00:00",
          "last_status":            "shadow_keep",
          "last_branch":            "experiment/iter-abc123",
          "iteration_count_today":  7,
          "throttle":               {                       # A.05, optional
              "max_per_hour":      3,
              "cooldown_seconds":  600,
              "last_decision":     "ok"
          },
          "audit_branches":         {                       # E.02, optional
              "enabled":             true,
              "mode":                "local",
              "local_cleanup":       true,
              "last_branch":         "autoresearch/iter-abc123",
              "last_cleanup_status": "ok"
          }
        }

    Atomicity follows the temp-file + rename pattern A.02 used for
    ``experiments.jsonl``: write to ``<path>.tmp`` then ``replace`` so
    a reader never observes a partial file.
    """
    payload: dict[str, object] = {
        "mode": mode,
        "last_iteration_at": _now_iso(),
        "last_status": status,
        "last_branch": branch,
        "iteration_count_today": _iterations_today(),
    }
    if throttle is not None:
        # A.05: surface throttle headroom + most recent decision label.
        # ``last_decision`` is the short label produced by
        # ``_should_start_iteration`` (e.g. "ok", "hourly_throttle:3/3",
        # "merge_cooldown:42s_remaining") or whatever the caller passed
        # — operators read it via /status and jq.
        payload["throttle"] = {
            "max_per_hour": throttle.max_iterations_per_hour,
            "cooldown_seconds": throttle.cooldown_after_merge_seconds,
            "last_decision": throttle_decision or "ok",
        }
    # E.02 (#2070): surface audit-branch lifecycle. The block is included
    # iff ANY of the audit_branches_* kwargs was supplied so legacy
    # callers (halt path, shutdown) keep the pre-E.02 payload shape.
    if any(
        v is not None
        for v in (
            audit_branches_enabled,
            audit_branches_mode,
            audit_branches_local_cleanup,
            audit_branches_last_branch,
            audit_branches_last_cleanup_status,
        )
    ):
        payload["audit_branches"] = {
            "enabled": bool(audit_branches_enabled)
            if audit_branches_enabled is not None
            else False,
            "mode": audit_branches_mode or "off",
            "local_cleanup": bool(audit_branches_local_cleanup)
            if audit_branches_local_cleanup is not None
            else False,
            "last_branch": audit_branches_last_branch,
            "last_cleanup_status": audit_branches_last_cleanup_status or "n/a",
        }
    tmp = HEARTBEAT_PATH.with_suffix(HEARTBEAT_PATH.suffix + ".tmp")
    try:
        HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        try:
            tmp.chmod(0o644)
        except OSError:  # noqa: BLE001 — chmod is advisory
            pass
        tmp.replace(HEARTBEAT_PATH)
    except Exception as exc:  # noqa: BLE001 — best-effort observability
        log.warning("experiment-heartbeat write failed: %s", exc)
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:  # noqa: BLE001
            pass


def _record_paused_heartbeat(reason: str | None) -> None:
    """Write a heartbeat indicating the loop is paused for halt.

    Sprint audit-2026-05-15.C.05 (#2002) introduced this helper. Sprint
    audit-2026-05-15.D.02 (#2004) reroutes it through ``_write_heartbeat``
    so the paused state shares the canonical JSON schema. ``reason`` is
    accepted for back-compat with the C.05 call site and existing tests;
    operators read the underlying halt.flag for the human-readable
    reason, so we deliberately do not surface it in the JSON payload.
    """
    _ = reason  # surfaced via halt.flag itself; kept for signature stability
    _write_heartbeat(mode="halted", status="paused_halt", branch=None)


def _record_throttled_heartbeat(
    mode: str, throttle: ExperimentThrottle, reason: str
) -> None:
    """Write a heartbeat indicating the loop is paused for throttle.

    Sprint audit-2026-05-16.A.05 (#2049). Distinct from
    ``_record_paused_heartbeat`` (halt-flag) so operators can tell the
    two paused states apart from /status alone. The throttle block in
    the payload carries the active cap + the specific decision label
    (``hourly_throttle:N/cap`` or ``merge_cooldown:Ns_remaining``).
    """
    _write_heartbeat(
        mode=mode,
        status="paused_throttle",
        branch=None,
        throttle=throttle,
        throttle_decision=reason,
    )


# ── Secrets & Auth ─────────────────────────────────────────────

def _read_secrets() -> dict[str, str]:
    """Read .secrets file into a dict. Returns empty dict on any error.

    Sprint audit-2026-05-16.B.02 (#2051, M-1) — thin wrapper around
    :class:`bridge.runtime_secrets.RuntimeSecrets`. The canonical parse
    lives in the helper module; we pass ``enforce_permissions=False``
    here so the experiment loop's long-standing soft-fail contract
    (return empty on any read problem) is preserved bit-for-bit. The
    B.01 perm guard runs in the BridgeConfig path; this loop runs after
    the bridge boots, so a perm violation will already have surfaced.
    """
    try:
        from bridge.runtime_secrets import RuntimeSecrets
        rs = RuntimeSecrets(secrets_path=SECRETS_PATH, enforce_permissions=False)
        return rs.as_dict()
    except (PermissionError, OSError):
        return {}


def _load_oauth_token() -> str:
    """Load Claude OAuth token. Canonical source is .secrets; legacy file deprecated.

    Sprint audit-2026-05-16.B.02 (#2051, M-1) — delegates the .secrets read
    and the deprecated ``<data-dir>/.claude-token`` fallback to
    :class:`bridge.runtime_secrets.RuntimeSecrets`. Env-var precedence and
    the Keychain branch stay here because they are loop-specific concerns
    (operator-side env override; interactive-session Keychain), not part of
    the canonical secret-file contract.
    """
    # 1. Env var override (operator-controlled)
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if token:
        return token

    # 2. .secrets — CANONICAL for daemon contexts.
    secrets = _read_secrets()
    token = secrets.get("claude_oauth_token", "")
    if token:
        return token

    # 3. macOS Keychain — interactive sessions only. NOTE: no longer
    #    writes the token back to .claude-token; that write-back created
    #    the stale-cache hazard that #1991 documents.
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            creds = json.loads(result.stdout.strip())
            token = creds.get("claudeAiOauth", {}).get("accessToken", "")
            if token:
                return token  # ← write-back to .claude-token deliberately removed
    except Exception:
        pass

    # 4. DEPRECATED legacy file fallback — owned by RuntimeSecrets so the
    #    deprecation warning fires once and the lookup path matches the
    #    canonical contract documented at #1991 / A.01. RuntimeSecrets
    #    derives the legacy path from SECRETS_PATH's parent, which equals
    #    DATA_DIR for this loop's call-site (both point at the agent data
    #    directory in production; tests monkeypatch SECRETS_PATH and
    #    DATA_DIR to the same tmp_path).
    try:
        from bridge.runtime_secrets import RuntimeSecrets
        rs = RuntimeSecrets(secrets_path=SECRETS_PATH, enforce_permissions=False)
        token = rs.claude_oauth_token(required=False)
        if token:
            return token
    except (PermissionError, OSError):
        pass

    return ""  # caller handles empty-token branch (existing contract)


def _load_discord_webhook() -> str:
    """Load Discord webhook URL from .secrets or env."""
    secrets = _read_secrets()
    return secrets.get("discord_webhook_url", os.environ.get("DISCORD_WEBHOOK_URL", ""))


# ── Budget Gate ────────────────────────────────────────────────

def check_experiment_budget() -> bool:
    """Check if we can afford another experiment today (UTC)."""
    if not DB_PATH.exists():
        return True
    try:
        db = sqlite3.connect(str(DB_PATH))
        # Use date('now') in SQL to match created_at's datetime('now') — both UTC
        row = db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM experiment_log WHERE date(created_at) = date('now')",
        ).fetchone()
        db.close()
        spent = row[0] if row else 0.0
        return spent < EXPERIMENT_BUDGET_USD
    except Exception as e:
        log.warning("Budget check failed (allowing experiment): %s", e)
        return True


# ── Experiment History ─────────────────────────────────────────

def get_recent_experiments(limit: int = 10) -> list[dict]:
    """Fetch recent experiment results for context."""
    if not DB_PATH.exists():
        return []
    try:
        db = sqlite3.connect(str(DB_PATH))
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT status, description, tests_passed, tests_total, created_at "
            "FROM experiment_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        db.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ── Forbidden Pattern Check ───────────────────────────────────

def check_forbidden_files(changed_files: list[str]) -> list[str]:
    """Return list of forbidden files found in the changeset."""
    violations = []
    for f in changed_files:
        for pattern in FORBIDDEN_FILES:
            if pattern in f:
                violations.append(f)
                break
    return violations


# ── Pick Experiment ────────────────────────────────────────────

def pick_experiment(history: list[dict], iter_id: str | None = None) -> str:
    """Ask Claude to propose one experiment based on program + history.

    Sprint 02.09 — when *iter_id* is provided, the BUMBA_EXPERIMENT_ITER
    env var is set on the subprocess so any cost recording inside that
    Claude invocation gets attributed to the iteration via
    ``CostTracker.record``'s env-var fallback.
    """
    from _loop_program import LoopProgram  # local import keeps top of file lean

    program = LoopProgram.from_markdown(PROGRAM_PATH)
    prompt = program.proposal_prompt(history)

    oauth_token = _load_oauth_token()
    env = os.environ.copy()
    env["HOME"] = str(CLAUDE_HOME)
    if oauth_token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
        log.info("OAuth token set (%d chars)", len(oauth_token))
    if iter_id:
        env["BUMBA_EXPERIMENT_ITER"] = iter_id

    result = subprocess.run(
        [
            str(CLAUDE_BIN), "-p",
            "--output-format", "text",
            "--max-turns", "0",
            "--setting-sources", "user",  # Skip project CLAUDE.md and .mcp.json
        ],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=CLAUDE_TIMEOUT,
        cwd=str(AGENT_DIR),
        env=env,
    )

    if result.returncode != 0:
        log.warning(
            "Claude proposal failed (exit %d): stderr=%s stdout=%s",
            result.returncode, result.stderr[:300], result.stdout[:300],
        )
        return None

    output = result.stdout.strip()

    # Strip preamble noise — Claude sometimes adds "permissions" text before the proposal
    for marker in ("FILE:", "**FILE:**", "**File:**"):
        idx = output.find(marker)
        if idx > 0:
            output = output[idx:]
            break

    return output


# ── Run Experiment ─────────────────────────────────────────────

def _open_bridge_mailbox() -> Mailbox | None:
    """Open the bridge-side experiment_loop mailbox. Returns ``None`` on error.

    Sprint 15.02 (#1052) — fail-soft helper so a transient SQLite error
    NEVER kills an iteration; the loop simply degrades to the pre-PR-#1153
    behavior where the worker writes nothing back.
    """
    try:
        mbox = Mailbox(EXPERIMENT_MAILBOX_CONFIG, role="bridge")
        mbox.init_db()
        return mbox
    except Exception as exc:  # noqa: BLE001 — mailbox failure must not block
        log.warning("experiment-loop mailbox: open failed: %s", exc)
        return None


def _drain_mailbox(
    mbox: Mailbox | None, *, after_seq: int = 0
) -> tuple[list[MailboxMessage], int]:
    """Read all worker→bridge messages with seq > after_seq.

    Returns ``(messages, last_seen_seq)``. Defensive: any error returns the
    input cursor unchanged so a partial read can be retried later.
    """
    if mbox is None:
        return [], after_seq
    try:
        msgs = mbox.read_since(after_seq=after_seq, limit=1000)
    except Exception as exc:  # noqa: BLE001 — mailbox failure must not block
        log.warning("experiment-loop mailbox: read_since failed: %s", exc)
        return [], after_seq
    if not msgs:
        return [], after_seq
    last_seq = max(m.seq for m in msgs)
    return msgs, last_seq


def _surface_progress_message(payload: dict) -> None:
    """Forward a worker ``progress`` payload to the bridge logger.

    Sprint 15.02 (#1052) — a thin shim into the existing notifier path
    (Sprint 02.10 / PR #1137). Today we just log; the operator-facing
    surfacing is handled by the notifier when it composes the iteration's
    Discord summary in ``_build_notification`` (which now includes the
    ``mailbox_messages`` array on the result record).
    """
    kind = payload.get("kind", "?")
    if kind == "progress":
        log.info(
            "experiment-loop mailbox progress: %s%s",
            payload.get("message", ""),
            f" (pct={payload['pct']})" if "pct" in payload else "",
        )
    elif kind == "intermediate_fitness":
        log.info(
            "experiment-loop mailbox intermediate_fitness: value=%s n=%s",
            payload.get("value"),
            payload.get("sample_count"),
        )
    elif kind == "crash":
        log.warning(
            "experiment-loop mailbox crash: %s: %s",
            payload.get("error_type", "?"),
            payload.get("message", ""),
        )


def run_experiment(
    description: str,
    iter_id: str | None = None,
    *,
    mailbox: Mailbox | None = None,
) -> dict:
    """Create a worktree, have Claude apply the change, return worktree info.

    Sprint 02.09 — when *iter_id* is provided, the BUMBA_EXPERIMENT_ITER
    env var is set on the subprocess so any cost recording inside that
    Claude invocation gets attributed to the iteration.

    Sprint 15.02 (#1052) — when *mailbox* is provided (a bridge-side
    ``Mailbox``), the worker subprocess gets ``BUMBA_MAILBOX_NAME`` and
    ``BUMBA_MAILBOX_DATA_DIR`` env vars so it can open the worker side
    of the channel (via ``experiment_mailbox_worker``) and emit
    progress / intermediate_fitness / crash messages mid-run. The result
    dict carries a ``mailbox_messages`` list (drained after the
    subprocess exits) for downstream persistence by ``log_result``.
    Default ``mailbox=None`` keeps the pre-PR-#1153 behavior.
    """
    exp_id = uuid.uuid4().hex[:12]
    branch_name = f"experiment/{exp_id}"
    worktree_path = WORKTREE_BASE / exp_id

    WORKTREE_BASE.mkdir(parents=True, exist_ok=True)

    # Create worktree from current HEAD
    subprocess.run(
        ["git", "worktree", "add", str(worktree_path), "-b", branch_name],
        cwd=str(REPO_ROOT),
        capture_output=True,
        check=True,
    )

    # Build prompt for Claude to apply the change (loop-as-markdown)
    from _loop_program import LoopProgram  # local import keeps top of file lean

    program = LoopProgram.from_markdown(PROGRAM_PATH)
    prompt = program.apply_prompt(description, sorted(FORBIDDEN_FILES))

    oauth_token = _load_oauth_token()
    env = os.environ.copy()
    if oauth_token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
    if iter_id:
        env["BUMBA_EXPERIMENT_ITER"] = iter_id

    # Sprint 15.02 (#1052) — pass mailbox identity to the subprocess so
    # the worker-side helpers can lazy-open their role of the channel.
    if mailbox is not None:
        env[ENV_MAILBOX_NAME] = mailbox.config.name
        env[ENV_MAILBOX_DATA_DIR] = str(mailbox.config.data_dir)

    worktree_agent_dir = worktree_path / "agent"
    result = subprocess.run(
        [
            str(CLAUDE_BIN), "-p",
            "--allowedTools", "Edit,Read,Glob,Grep,Write,Bash",
            "--output-format", "text",
            "--max-turns", "5",
            prompt,
        ],
        capture_output=True,
        text=True,
        timeout=CLAUDE_TIMEOUT,
        cwd=str(worktree_agent_dir),
        env=env,
    )

    # Sprint 15.02 (#1052) — drain final mailbox state after subprocess
    # exits. The during-run polling in main() already surfaced any
    # progress messages; this final drain captures anything the worker
    # wrote in its closing breath.
    mailbox_messages: list[dict] = []
    if mailbox is not None:
        msgs, _ = _drain_mailbox(mailbox)
        for m in msgs:
            mailbox_messages.append(
                {
                    "seq": m.seq,
                    "direction": m.direction,
                    "payload": m.payload,
                    "enqueued_at_iso": m.enqueued_at_iso,
                }
            )

    return {
        "id": exp_id,
        "branch": branch_name,
        "worktree": str(worktree_path),
        "claude_exit_code": result.returncode,
        "claude_output": result.stdout[:2000],
        "mailbox_messages": mailbox_messages,
    }


# ── Validate Experiment ───────────────────────────────────────

def validate_experiment(
    worktree: str,
    *,
    iter_id: str | None = None,
    issue_body: str | None = None,
    validator_runner: object | None = None,
    validator_enabled: bool = False,
    validator_cost_cap_usd: float = 0.30,
    validator_model: str = "haiku",
    validator_timeout_seconds: int = 0,
    validator_min_signals: int = 0,
    halt_policy: object | None = None,
) -> dict:
    """Check forbidden files and run tests in the worktree.

    Sprint 02.14 (#989) — when ``validator_enabled`` is True AND
    ``validator_runner`` is supplied, the holdout validator runs after
    the quality gates pass. Verdict + reasoning are persisted into the
    returned ``notes`` dict and may flip ``status`` to ``"discard"``
    when the verdict is ``REGRESSION`` or ``NOISE``.

    Validator failure NEVER blocks the iteration — every error path
    degrades to ``UNSURE`` (advisory) and lets the caller proceed.

    Sprint audit-2026-05-16.C.03 (#2058) — when ``halt_policy`` is
    supplied (a ``bridge.halt.HaltPolicy``), the pytest subprocess
    runs through :func:`_run_subprocess_cancellable` so the
    operator's ``/halt`` interrupts in-flight tests rather than
    waiting up to ``PYTEST_TIMEOUT`` (5 min) to next-iteration. On
    halt-cancel returns a structured ``status="halted_in_flight"``
    record (does NOT re-raise) so the caller's outer loop sees the
    deliberate abort distinct from a pytest crash. Default
    ``halt_policy=None`` preserves the pre-C.03 direct ``subprocess.run``
    path bit-for-bit.
    """
    worktree_path = Path(worktree)
    agent_dir = worktree_path / "agent"
    start = time.time()

    # Get changed files
    diff_result = subprocess.run(
        ["git", "diff", "--name-only"],
        capture_output=True,
        text=True,
        cwd=worktree,
    )
    changed_files = [f for f in diff_result.stdout.strip().splitlines() if f]

    if not changed_files:
        return {
            "tests_passed": 0,
            "tests_failed": 0,
            "tests_total": 0,
            "status": "discard",
            "diff_summary": "No files changed",
            "duration_seconds": time.time() - start,
        }

    # Check forbidden patterns
    violations = check_forbidden_files(changed_files)
    if violations:
        return {
            "tests_passed": 0,
            "tests_failed": 0,
            "tests_total": 0,
            "status": "discard",
            "diff_summary": f"Forbidden files modified: {', '.join(violations)}",
            "duration_seconds": time.time() - start,
        }

    # Get diff summary
    diff_stat = subprocess.run(
        ["git", "diff", "--stat"],
        capture_output=True,
        text=True,
        cwd=worktree,
    )
    diff_summary = diff_stat.stdout.strip()[:500]

    # Run pytest
    # Sprint audit-2026-05-16.C.03 (#2058) — when halt_policy is
    # supplied, route the pytest subprocess through the cancellable
    # wrapper so an operator /halt mid-tests aborts inside one
    # poll-interval boundary (0.25s) rather than waiting up to 5min.
    # Default path (halt_policy=None) preserves the legacy direct call.
    pytest_cmd = [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=short"]
    try:
        if halt_policy is not None:
            test_result = _run_subprocess_cancellable(
                pytest_cmd,
                halt_policy=halt_policy,
                surface="experiment_loop",
                timeout=PYTEST_TIMEOUT,
                cwd=str(agent_dir),
                capture_output=True,
                text=True,
            )
        else:
            test_result = subprocess.run(
                pytest_cmd,
                capture_output=True,
                text=True,
                timeout=PYTEST_TIMEOUT,
                cwd=str(agent_dir),
            )
        test_output = test_result.stdout + test_result.stderr

        # Parse pytest output for counts
        tests_passed, tests_failed, tests_total = _parse_pytest_output(test_output)

        status = "keep" if test_result.returncode == 0 else "discard"

    except subprocess.TimeoutExpired:
        tests_passed, tests_failed, tests_total = 0, 0, 0
        status = "crash"
        diff_summary += " (pytest timed out)"

    except _HaltCancelled as halt_exc:
        # Sprint audit-2026-05-16.C.03 (#2058) — translate cooperative
        # cancellation into a structured discardable record. The caller
        # (main loop) checks for ``halted_in_flight`` and routes through
        # cleanup + paused-heartbeat instead of treating this as a
        # crash. Re-raising would land in main()'s broad ``except
        # Exception`` and tag the iteration ``shadow_crash`` / crash,
        # masking the operator's deliberate halt.
        log.warning(
            "validate_experiment: halt fired mid-pytest — aborting iteration "
            "(reason=%s)",
            halt_exc,
        )
        return {
            "tests_passed": 0,
            "tests_failed": 0,
            "tests_total": 0,
            "status": "halted_in_flight",
            "diff_summary": (
                diff_summary + f" (halted in-flight: {halt_exc})"
            )[:500],
            "duration_seconds": time.time() - start,
            "notes": {},
            "validator_verdict": None,
            "validator_summary": None,
            "validator_findings": [],
        }

    # Sprint 02.07b — backpressure gates after pytest (issue #982). Only
    # gate when pytest itself is green; if pytest already failed or
    # timed out, skip the lint/typecheck pass — the iteration is
    # already going to be discarded for the more obvious reason and
    # we'd rather not pay the mypy cost on a doomed change.
    quality_notes: dict[str, object] = {}
    if status == "keep":
        # Resolve changed files relative to the worktree root; the gates
        # run in `agent_dir` (`worktree/agent/`) so paths must be
        # absolute or relative to that cwd. Using absolute paths keeps
        # the gate independent of the working directory.
        changed_paths = [worktree_path / f for f in changed_files]
        gate_results: tuple[GateResult, ...] = run_quality_gates(
            changed_paths,
            cwd=agent_dir,
        )
        quality_notes = {
            "lint_regressions": _gate_results_to_notes(gate_results),
        }
        if not quality_gates_all_passed(gate_results):
            status = "discard"
            gate_summary = summarize_quality_gates(gate_results)
            # Tag the diff_summary so the operator can see the gate
            # decision in the daily digest without opening notes.
            extra = f" (lint-regression: {gate_summary})" if gate_summary else " (lint-regression)"
            diff_summary = (diff_summary + extra)[:500]

    # Sprint 02.14 (#989) — holdout validator slots in AFTER quality gates
    # pass. Only invoke when status is still "keep" and the operator has
    # opted in via the feature flag + supplied a runner.
    validator_verdict: str | None = None
    validator_summary: str | None = None
    validator_findings: tuple[str, ...] = ()
    if (
        status == "keep"
        and validator_enabled
        and validator_runner is not None
        and iter_id is not None
    ):
        try:
            diff_full = subprocess.run(
                ["git", "diff", "main..HEAD"],
                cwd=worktree,
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout
        except Exception as exc:  # noqa: BLE001 — fail-soft on git errors
            log.warning("validator: git diff failed: %s", exc)
            diff_full = "\n".join(changed_files)

        validator_input = ValidatorInput(
            iter_id=iter_id,
            issue_body=issue_body or "(no proposal body recorded)",
            diff_text=diff_full[:32000],  # bound the prompt size
            program_origin_sha=get_origin_main_sha(cwd=str(REPO_ROOT)),
            cost_cap_usd=validator_cost_cap_usd,
        )
        try:
            validator_result: ValidatorResult = asyncio.run(
                run_validator(
                    validator_input,
                    runner=validator_runner,  # type: ignore[arg-type]
                    model=validator_model,
                )
            )
            validator_verdict = validator_result.verdict.value
            validator_summary = validator_result.summary
            validator_findings = validator_result.findings
            # Sprint audit-2026-05-16.D.06 (#2067) — validator-subprocess
            # cost is now parsed from stream-json (see
            # ``_parse_validator_subprocess_cost``); the runner returns
            # ``float('nan')`` when no usable cost field is present so
            # we can record ``iteration_cost_unknown=True`` rather than
            # silently coerce missing data to 0.0 (the SW-3 collapse
            # the CostMeasurement contract from D.01 exists to prevent).
            import math as _math
            _cost = validator_result.cost_usd
            _cost_is_unknown = _math.isnan(_cost) if isinstance(_cost, float) else False
            if _cost_is_unknown:
                log.warning(
                    "validator: iter %s cost_usd unknown (no result event "
                    "or missing cost_usd field) — recording with "
                    "iteration_cost_unknown=True instead of zero",
                    iter_id,
                )
            quality_notes["validator"] = {
                "verdict": validator_verdict,
                "summary": validator_summary,
                "findings": list(validator_findings),
                # Preserve numeric cost only when measured; unknown
                # writes ``None`` so a downstream consumer that reads
                # this field cannot misinterpret it as $0.00 spend.
                "cost_usd": None if _cost_is_unknown else _cost,
                "cost_source": "unknown" if _cost_is_unknown else "measured",
                "iteration_cost_unknown": _cost_is_unknown,
                "latency_ms": validator_result.latency_ms,
                "parse_error": validator_result.parse_error,
            }
            # Discard on REGRESSION or NOISE; IMPROVEMENT and UNSURE
            # proceed to merge (UNSURE = fail-soft default).
            if validator_result.verdict in (
                HoldoutValidatorVerdict.REGRESSION,
                HoldoutValidatorVerdict.NOISE,
            ):
                status = "discard"
                tail = f" (holdout: {validator_verdict} — {validator_summary})"
                diff_summary = (diff_summary + tail)[:500]
        except Exception as exc:  # noqa: BLE001 — validator must never block
            log.warning("validator: invocation failed (degrading to UNSURE): %s", exc)
            validator_verdict = HoldoutValidatorVerdict.UNSURE.value
            validator_summary = "validator dispatch failed"
            quality_notes["validator"] = {
                "verdict": validator_verdict,
                "summary": validator_summary,
                "findings": [],
                "parse_error": f"{type(exc).__name__}: {exc}",
            }

    return {
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "tests_total": tests_total,
        "status": status,
        "diff_summary": diff_summary,
        "duration_seconds": time.time() - start,
        "notes": quality_notes,
        "validator_verdict": validator_verdict,
        "validator_summary": validator_summary,
        "validator_findings": list(validator_findings),
    }


def _gate_results_to_notes(results: tuple[GateResult, ...]) -> dict[str, dict]:
    """Render gate results as a JSONL-friendly notes dict.

    Sprint 02.07b — keeps experiments.jsonl human-readable by stripping
    the long stdout/stderr to a short prefix and surfacing only the
    structured fields the operator actually consumes (outcome, summary,
    duration). Full output stays in the worktree's gate logs if
    needed; the JSONL is the long-lived record.
    """
    out: dict[str, dict] = {}
    for r in results:
        out[r.name] = {
            "outcome": r.outcome,
            "summary": r.summary,
            "duration_seconds": round(r.duration_seconds, 3),
            # Trim to keep the JSONL line bounded; the full output stays
            # in stderr/stdout of the actual gate run for debugging.
            "stdout_head": r.stdout[:500],
            "stderr_head": r.stderr[:500],
        }
    return out


def _parse_pytest_output(output: str) -> tuple[int, int, int]:
    """Parse pytest -q output for pass/fail counts."""
    import re

    # Match patterns like "1813 passed", "2 failed", "1813 passed, 2 failed"
    passed = 0
    failed = 0

    m = re.search(r"(\d+) passed", output)
    if m:
        passed = int(m.group(1))

    m = re.search(r"(\d+) failed", output)
    if m:
        failed = int(m.group(1))

    m = re.search(r"(\d+) error", output)
    if m:
        failed += int(m.group(1))

    return passed, failed, passed + failed


# ── Merge Experiment ───────────────────────────────────────────

def merge_experiment(
    worktree: str,
    branch: str,
    description: str,
    *,
    run_id: str | None = None,
    mode: str | None = None,
) -> str | None:
    """Commit in worktree (if dirty) and fast-forward merge to main. Returns commit hash or None.

    Sprint audit-2026-05-16.E.01 (#2069) — when ``run_id`` and ``mode``
    are supplied (the main-loop call site always supplies both), the
    commit message carries the stable
    ``Bumba-Agent-Experiment: true`` / ``Experiment-Run-Id`` /
    ``Experiment-Mode`` trailer trio. Trailer wiring is idempotent: if
    ``_ensure_worktree_commit`` already added trailers earlier in the
    iteration, the commit on this path was a no-op anyway (the status
    probe below skips the commit when clean), so no double-stamping is
    possible. The optional-with-default signature preserves call-site
    compatibility for direct callers and tests that don't yet thread
    run/mode through.
    """
    # Sprint audit-2026-05-15.C.01 (#1998) — when
    # ``experiment_audit_branches_enabled`` is true,
    # ``_ensure_worktree_commit()`` already committed in the worktree
    # earlier in the iteration so the audit branch has a SHA. Probe
    # before committing again; an unconditional ``git commit`` raises
    # here because the worktree is clean ("nothing to commit"), the
    # outer broad-except catches it, and a legitimate ``keep``
    # iteration becomes a ``crash`` row.
    status_proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    if status_proc.stdout.strip():
        # Dirty — original commit path, unchanged.
        subprocess.run(
            ["git", "add", "-A"],
            cwd=worktree,
            capture_output=True,
            check=True,
        )
        commit_msg = f"experiment: {description[:100]}"
        if run_id is not None and mode is not None:
            commit_msg = _append_experiment_trailers(
                commit_msg, run_id=run_id, mode=mode
            )
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=worktree,
            capture_output=True,
            check=True,
        )
    else:
        log.info(
            "merge_experiment: worktree already clean for %s — "
            "using existing HEAD (audit branch pre-commit path)",
            branch,
        )

    # Get the commit hash
    hash_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=worktree,
        capture_output=True,
        text=True,
    )
    commit_hash = hash_result.stdout.strip()

    # Fast-forward merge on main
    result = subprocess.run(
        ["git", "merge", "--ff-only", branch],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        log.warning("FF merge failed (main moved): %s", result.stderr[:200])
        return None

    return commit_hash


# ── Audit Branch Trail (Sprint 02.04 / issue #978) ─────────────


def _ensure_worktree_commit(
    worktree: str,
    description: str,
    *,
    run_id: str | None = None,
    mode: str | None = None,
) -> str | None:
    """Stage + commit the worktree if dirty; return the worktree HEAD SHA.

    Sprint 02.04 (#978) — the audit-branch trail anchors on a real commit
    SHA, but the merge / discard fork is downstream. This helper makes
    the commit idempotent so audit-branch creation works on both paths:

    - Keep: a no-op (``merge_experiment`` will commit later, but if we
      already did, ``git add -A`` finds nothing and the second commit
      is skipped).
    - Discard / crash: we still want a SHA for the audit branch, so we
      commit here even though the changes never reach main.

    Sprint audit-2026-05-16.E.01 (#2069) — when ``run_id`` and ``mode``
    are supplied, the commit message carries the stable trailer trio so
    operator tooling can filter the log on
    ``Bumba-Agent-Experiment: true``. Optional-with-default keeps any
    legacy direct callers / tests compatible.

    Returns the HEAD SHA on success; ``None`` if there's nothing to
    commit (no diff vs HEAD) AND HEAD itself can't be resolved (test
    fixture worktree). Never raises — the caller's iteration must not
    be killed by a git hiccup in the audit-trail layer.
    """
    try:
        # Are there staged or unstaged changes? ``git status --porcelain``
        # is empty iff the tree is clean.
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if status.returncode != 0:
            return None
        dirty = bool(status.stdout.strip())

        if dirty:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=worktree,
                capture_output=True,
                check=True,
                timeout=10,
            )
            commit_msg = f"experiment: {description[:100]}"
            if run_id is not None and mode is not None:
                commit_msg = _append_experiment_trailers(
                    commit_msg, run_id=run_id, mode=mode
                )
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=worktree,
                capture_output=True,
                check=True,
                timeout=15,
            )

        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if head.returncode != 0:
            return None
        sha = head.stdout.strip()
        return sha or None
    except Exception as exc:  # noqa: BLE001 — audit trail must not block
        log.warning("audit-trail: ensure-commit failed: %s", exc)
        return None


def _create_audit_branch_safe(
    *,
    iter_id: str,
    head_sha: str,
    push_to_origin: bool,
) -> AuditBranchResult | None:
    """Wrap ``create_audit_branch`` with full fail-soft semantics.

    Sprint 02.04 (#978) — every code path inside this helper logs and
    returns ``None`` rather than propagating; the caller MUST treat
    audit-branch creation as best-effort observability. The iteration's
    keep/discard/crash branch is the operator's source of truth, not
    this audit trail.
    """
    try:
        return create_audit_branch(
            iter_id=iter_id,
            head_sha=head_sha,
            repo_root=REPO_ROOT,
            push_to_origin=push_to_origin,
        )
    except Exception as exc:  # noqa: BLE001 — audit trail must not block
        log.warning("audit-trail: create_audit_branch failed: %s", exc)
        return None


def _annotate_audit_branch_safe(
    branch_name: str,
    *,
    outcome: str,
) -> None:
    """Wrap ``annotate_branch_with_outcome`` with full fail-soft semantics."""
    try:
        annotate_branch_with_outcome(
            branch_name,
            outcome=outcome,  # type: ignore[arg-type]
            repo_root=REPO_ROOT,
        )
    except Exception as exc:  # noqa: BLE001 — audit trail must not block
        log.warning("audit-trail: annotate_branch_with_outcome failed: %s", exc)


def _load_audit_branch_settings() -> tuple[bool, bool, bool]:
    """Read the audit-branch feature flags from BridgeConfig. Fail-soft.

    Returns ``(enabled, push_to_origin, local_cleanup)``. On any
    config-load error, falls back to ``(False, False, False)`` so the
    loop keeps working.

    Sprint audit-2026-05-16.E.02 (#2070) — the trichotomy off/local/remote
    is encoded by the first two fields (``enabled=False`` → off;
    ``enabled=True, push_to_origin=False`` → local;
    ``enabled=True, push_to_origin=True`` → remote). The third field
    ``local_cleanup`` only takes effect in the LOCAL combination and
    auto-deletes the local audit branch after a successful merge so
    multi-day trial windows don't accumulate dead branches.
    """
    try:
        from bridge.config import load_config

        cfg = load_config(skip_secrets=True, skip_validation=True)
        return (
            bool(getattr(cfg, "experiment_audit_branches_enabled", False)),
            bool(getattr(cfg, "experiment_audit_branches_push_to_origin", False)),
            bool(
                getattr(cfg, "experiment_audit_branches_local_cleanup", False)
            ),
        )
    except Exception as exc:  # noqa: BLE001 — config lookup must not block
        log.warning("audit-trail: config lookup failed: %s", exc)
        return (False, False, False)


# ── Worktree Cleanup ──────────────────────────────────────────


def _cleanup_local_audit_branch(branch_name: str | None) -> tuple[bool, str | None]:
    """E.02 (#2070) — delete a local audit branch post-merge.

    Returns ``(success, error_message)``. Fail-soft: NEVER raises into
    the loop. The audit branch is best-effort observability; its
    lifecycle must not gate the iteration's outcome.

    Skips silently when ``branch_name`` is ``None`` or empty (returns
    ``(True, None)``). Uses ``git branch -D <name>`` (force delete
    because the branch is local-only and may carry commits that aren't
    reachable from main after a fast-forward merge).
    """
    if not branch_name:
        return (True, None)
    try:
        result = subprocess.run(
            ["git", "branch", "-D", branch_name],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return (True, None)
        return (False, result.stderr.strip() or "unknown error")
    except Exception as exc:  # noqa: BLE001 — fail-soft
        return (False, str(exc))


def cleanup_worktree(worktree: str, branch: str | None = None) -> None:
    """Remove a git worktree and its branch."""
    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", worktree],
            cwd=str(REPO_ROOT),
            capture_output=True,
            timeout=30,
        )
    except Exception as e:
        log.warning("Worktree cleanup failed for %s: %s", worktree, e)

    if branch:
        try:
            subprocess.run(
                ["git", "branch", "-D", branch],
                cwd=str(REPO_ROOT),
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass


# ── Logging to DB ──────────────────────────────────────────────

FITNESS_HISTORY_PATH = DATA_DIR / "fitness_history.jsonl"

# Sprint 02.03 — operator-readable state files alongside experiments.db.
# Concept ported from pi-autoresearch (MIT) — paraphrased, not copied.
EXPERIMENTS_JSONL_PATH = DATA_DIR / "experiments.jsonl"
EXPERIMENTS_MD_PATH = DATA_DIR / "experiments.md"

# Sprint 02.13 / spec ref-audit-02-13 (issue #988) — heartbeat surfacing
# in /healthz + /health. The bridge daemon reads this file; the loop
# writes it on iteration boundaries. Failures are swallowed inside
# ``_safe_heartbeat`` so a heartbeat-write error never blocks the loop.
EXPERIMENT_HEARTBEAT_PATH = DATA_DIR / "experiment-loop-heartbeat.json"


def _now_iso() -> str:
    """UTC timestamp in ISO-8601 — used by heartbeat writes."""
    return datetime.now(tz=timezone.utc).isoformat()


def _safe_heartbeat(
    *,
    iter_id: str,
    started_at_iso: str,
    completed_at_iso: str | None,
    status: str,
    fitness_value: float | None = None,
) -> None:
    """Write the experiment-loop heartbeat without ever raising.

    Sprint 02.13 (#988) — observability hook. The heartbeat write is best
    effort: any failure is logged but never propagates so an iteration
    can't be killed by a missing data dir or a transient I/O error.
    """
    try:
        from bridge.experiment_heartbeat import (
            ExperimentLoopState,
            write_heartbeat,
        )

        state = ExperimentLoopState(
            last_iter_id=iter_id,
            last_started_at_iso=started_at_iso,
            last_completed_at_iso=completed_at_iso,
            pid=os.getpid(),
            status=status,  # type: ignore[arg-type]
            fitness_value=fitness_value,
        )
        write_heartbeat(state, path=EXPERIMENT_HEARTBEAT_PATH)
    except Exception as exc:  # pragma: no cover — defensive
        log.warning("experiment heartbeat write failed: %s", exc)


def _append_fitness_history(snapshot: dict) -> None:
    """Append a fitness snapshot to ``fitness_history.jsonl`` atomically.

    Sprint 02.02 — write-and-rename pattern keeps the file durable under
    a crash mid-write. Each line is one JSON object with the snapshot
    fields plus the iteration's ``commit_hash`` / ``branch`` for cross-
    referencing back to ``experiment_log``.
    """
    try:
        FITNESS_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing = ""
        if FITNESS_HISTORY_PATH.exists():
            existing = FITNESS_HISTORY_PATH.read_text()
        tmp = FITNESS_HISTORY_PATH.with_suffix(FITNESS_HISTORY_PATH.suffix + ".tmp")
        tmp.write_text(existing + json.dumps(snapshot) + "\n")
        tmp.replace(FITNESS_HISTORY_PATH)
    except Exception as e:
        log.warning("Failed to append fitness history: %s", e)


def append_experiments_jsonl(record: dict, *, path: Path | None = None) -> None:
    """Append one iteration record to ``experiments.jsonl`` atomically.

    Sprint 02.03 — same write-and-rename pattern as
    ``_append_fitness_history`` so a mid-write crash leaves no
    partial JSON line. The caller-visible contract: each line is a
    standalone JSON object containing the ``experiment_log`` columns
    plus a ``notes`` dict for free-form metadata.
    """
    target = path if path is not None else EXPERIMENTS_JSONL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if target.exists():
        existing = target.read_text()
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(existing + json.dumps(record) + "\n")
    tmp.replace(target)


def append_experiments_md(
    iter_id: int,
    status: str,
    fitness_delta: float,
    description: str,
    *,
    path: Path | None = None,
) -> None:
    """Append a parseable section to ``experiments.md`` atomically.

    Sprint 02.03 — Plan 03 sprint 03.10 reads this file, so the header
    format is part of the cross-plan contract. Header regex (documented
    in tests):
      ``^## \\[(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2})\\] iter-(\\d+) \\| (\\w+) \\| fitness Δ ([+-]?\\d+\\.\\d+)$``
    """
    target = path if path is not None else EXPERIMENTS_MD_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    delta_str = f"{fitness_delta:+.2f}"
    header = f"## [{timestamp}] iter-{iter_id:04d} | {status} | fitness Δ {delta_str}"
    body = (description or "").strip() or "(no description)"
    section = f"{header}\n\n{body}\n\n"

    existing = ""
    if target.exists():
        existing = target.read_text()
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(existing + section)
    tmp.replace(target)


def log_result(result: dict) -> None:
    """Insert experiment result into experiment_log table.

    Sprint 02.02: persists ``fitness_delta`` (REAL, nullable) and, when
    the iteration carries a ``fitness_snapshot`` dict, appends one line
    to ``fitness_history.jsonl``.

    Sprint 02.03: dual-writes each iteration to ``experiments.jsonl``
    (machine-parseable) and ``experiments.md`` (operator-readable).
    The SQLite write is the system of record — JSONL/MD failures are
    logged but never propagated, since both files are reconstructible
    from the database.
    """
    iter_id: int | None = None
    try:
        db = sqlite3.connect(str(DB_PATH))
        cursor = db.execute(
            "INSERT INTO experiment_log "
            "(commit_hash, branch, tests_passed, tests_failed, tests_total, "
            "status, description, diff_summary, cost_usd, duration_seconds, "
            "fitness_delta) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                result.get("commit_hash"),
                result.get("branch"),
                result.get("tests_passed", 0),
                result.get("tests_failed", 0),
                result.get("tests_total", 0),
                result.get("status", "crash"),
                result.get("description", ""),
                result.get("diff_summary", ""),
                result.get("cost_usd", 0.0),
                result.get("duration_seconds", 0.0),
                result.get("fitness_delta"),
            ),
        )
        iter_id = cursor.lastrowid
        db.commit()
        db.close()
    except Exception as e:
        log.error("Failed to log experiment result: %s", e)

    snapshot = result.get("fitness_snapshot")
    if isinstance(snapshot, dict):
        record = dict(snapshot)
        record.setdefault("commit_hash", result.get("commit_hash"))
        record.setdefault("branch", result.get("branch"))
        record.setdefault("fitness_delta", result.get("fitness_delta"))
        _append_fitness_history(record)

    # Sprint 02.03 — operator-readable mirrors of the iteration record.
    # Failures here MUST NOT mask the SQLite write; both files are
    # reconstructible from ``experiments.db``.
    fitness_delta = result.get("fitness_delta")
    fitness_delta_float = float(fitness_delta) if fitness_delta is not None else 0.0
    status = result.get("status", "crash")
    description = result.get("description", "") or ""

    # Sprint 02.04 — compute MAD-based confidence band on the trailing
    # window BEFORE persisting this iteration. We read deltas from the
    # existing experiments.jsonl, so the new line we're about to write
    # never sees its own delta (correct: noise floor reflects history).
    # ``significant`` is a separate field so Sprint 02.05 can consume
    # it without re-deriving. Failures degrade silently to None / False.
    confidence_seconds: float | None = None
    significant: bool = False
    try:
        from bridge import mad_confidence

        recent = mad_confidence.load_recent_fitness(
            EXPERIMENTS_JSONL_PATH, window=MAD_WINDOW
        )
        mad = mad_confidence.mad_result(recent, k=MAD_K)
        if mad.sample_count >= mad_confidence.MIN_SAMPLES_FOR_SIGNIFICANCE:
            confidence_seconds = mad.confidence_seconds
        if fitness_delta is not None:
            significant = mad_confidence.is_significant(fitness_delta_float, mad)
    except Exception as exc:
        log.warning("MAD confidence computation failed: %s", exc)

    jsonl_record = {
        "iter_id": iter_id,
        "commit_hash": result.get("commit_hash"),
        "branch": result.get("branch"),
        "tests_passed": result.get("tests_passed", 0),
        "tests_failed": result.get("tests_failed", 0),
        "tests_total": result.get("tests_total", 0),
        "status": status,
        "description": description,
        "diff_summary": result.get("diff_summary", ""),
        "cost_usd": result.get("cost_usd", 0.0),
        "duration_seconds": result.get("duration_seconds", 0.0),
        "fitness_delta": fitness_delta,
        "confidence_seconds": confidence_seconds,
        "significant": significant,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "notes": dict(result.get("notes") or {}),
        # Sprint 02.14 (#989) — holdout validator verdict surfaced to the
        # operator via experiments.jsonl. None when the validator was
        # disabled or didn't run; one of HoldoutValidatorVerdict's values
        # otherwise.
        "validator_verdict": result.get("validator_verdict"),
        "validator_summary": result.get("validator_summary"),
        "validator_findings": list(result.get("validator_findings") or ()),
        # Sprint 15.02 (#1052) — mailbox messages drained from the worker
        # subprocess. Empty list when the mailbox feature flag is off
        # (current default) so existing JSONL parsers are unaffected.
        "mailbox_messages": list(result.get("mailbox_messages") or ()),
    }
    try:
        append_experiments_jsonl(jsonl_record)
    except Exception as e:
        log.warning("Failed to append experiments.jsonl: %s", e)

    if iter_id is not None:
        try:
            append_experiments_md(
                iter_id=iter_id,
                status=status,
                fitness_delta=fitness_delta_float,
                description=description,
            )
        except Exception as e:
            log.warning("Failed to append experiments.md: %s", e)


# ── Discord Notification ──────────────────────────────────────

def _build_notification(result: dict, *, iter_id: str | None = None):
    """Build an ``ExperimentNotification`` from the loop's local state.

    Sprint 02.10 — extracts the message-shape concerns out of
    ``notify_discord`` so the formatter is pure and testable. Cost
    attribution (Sprint 02.09 / PR #1128) is best-effort: failures
    default to zero spend so notification never blocks on cost lookup.
    """
    from bridge.experiment_notifier import ExperimentNotification

    snapshot_before = None
    snapshot_after = None
    snapshot = result.get("fitness_snapshot")
    if isinstance(snapshot, dict):
        snapshot_before = snapshot.get("before_value")
        snapshot_after = snapshot.get("after_value")

    cost_usd = 0.0
    cost_breakdown: dict = {}
    notif_iter = iter_id or result.get("iter_id") or ""
    if notif_iter:
        try:
            from bridge.cost_tracker import CostTracker

            tracker = CostTracker(data_dir=DATA_DIR)
            summary = tracker.get_experiment_summary(notif_iter)
            cost_usd = float(getattr(summary, "total_usd", 0.0) or 0.0)
            cost_breakdown = dict(getattr(summary, "model_breakdown", {}) or {})
        except Exception as exc:
            log.warning("Cost summary lookup failed for iter %s: %s", notif_iter, exc)
            cost_usd = float(result.get("cost_usd", 0.0) or 0.0)
            cost_breakdown = {}

    # MAD confidence band: Sprint 02.04 / spec ref-audit-02-05 (issue #979).
    # Reads the last ``MAD_WINDOW`` deltas from experiments.jsonl and
    # returns ``K * MAD`` in seconds, or ``None`` during the warm-up
    # window. Failures degrade silently — notification must never block
    # on confidence-band lookup.
    mad_seconds: float | None = None
    try:
        from bridge import mad_confidence

        mad_seconds = mad_confidence.confidence_band_seconds(
            metric_name="mean_test_runtime_seconds",
            jsonl_path=EXPERIMENTS_JSONL_PATH,
            window=MAD_WINDOW,
            k=MAD_K,
        )
    except Exception as exc:
        log.warning("MAD confidence lookup failed: %s", exc)
        mad_seconds = None

    return ExperimentNotification(
        iter_id=str(notif_iter or "unknown"),
        outcome=str(result.get("status", "unknown")).lower(),
        fitness_before=snapshot_before,
        fitness_after=snapshot_after,
        cost_usd=cost_usd,
        cost_breakdown=cost_breakdown,
        mad_confidence_seconds=mad_seconds,
        jsonl_relpath=str(EXPERIMENTS_JSONL_PATH.relative_to(REPO_ROOT))
        if EXPERIMENTS_JSONL_PATH.is_relative_to(REPO_ROOT)
        else str(EXPERIMENTS_JSONL_PATH),
        md_relpath=str(EXPERIMENTS_MD_PATH.relative_to(REPO_ROOT))
        if EXPERIMENTS_MD_PATH.is_relative_to(REPO_ROOT)
        else str(EXPERIMENTS_MD_PATH),
    )


def notify_discord(result: dict, *, iter_id: str | None = None) -> None:
    """Send experiment result to Discord via webhook.

    Sprint 02.10 — message body now comes from
    ``bridge.experiment_notifier.format_discord_summary`` so the format
    is reusable and unit-testable. Discards are still suppressed (the
    daily digest covers them) — only ``keep`` and ``crash`` post.
    """
    from bridge.experiment_notifier import format_discord_summary

    status = (result.get("status") or "unknown").lower()
    if status not in {"keep", "crash"}:
        return  # Don't notify on routine discards

    notification = _build_notification(result, iter_id=iter_id)
    content = format_discord_summary(notification)

    webhook_url = _load_discord_webhook()
    if not webhook_url:
        # Preserve the dry-run/no-webhook stdout path so the operator
        # still sees the formatted message during local runs.
        log.info("No Discord webhook configured; would have posted:\n%s", content)
        return

    try:
        import urllib.request
        data = json.dumps({"content": content}).encode()
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log.warning("Discord notification failed: %s", e)


# ── Main Loop ──────────────────────────────────────────────────

def _load_mailbox_settings() -> tuple[bool, int, int]:
    """Read the mailbox feature flag + tunables from BridgeConfig.

    Sprint 15.02 (#1052) — fail-soft helper. If config import / load
    fails, the loop falls back to the default OFF posture (current
    behavior) so a config-loader bug never bricks the experiment loop.
    """
    try:
        from bridge.config import load_config

        cfg = load_config(skip_secrets=True, skip_validation=True)
        return (
            bool(getattr(cfg, "experiment_mailbox_enabled", False)),
            int(getattr(cfg, "experiment_mailbox_poll_interval_seconds", 2)),
            int(getattr(cfg, "experiment_mailbox_vacuum_keep_n", 5000)),
        )
    except Exception as exc:  # noqa: BLE001 — config lookup must not block
        log.warning("experiment-loop mailbox: config lookup failed: %s", exc)
        return (False, 2, 5000)


def _load_validator_settings() -> tuple[bool, float, str, int, int]:
    """Read holdout-validator flags from BridgeConfig. Fail-soft.

    Sprint D1.1 (#1173) — mirrors ``_load_mailbox_settings``. If config
    import / load fails, the loop falls back to the default OFF posture
    so a config-loader bug never bricks the experiment loop.

    Sprint audit-2026-05-16.E.03 (#2071) — extended return to thread the
    two readiness-contract bounding fields (``validator_timeout_seconds``
    and ``validator_min_signals``). Defaults of 0 preserve pre-E.03
    behavior in this fail-soft path: the readiness gate in
    ``bridge.config._validate`` only fires when ``validator_enabled`` is
    True, so an empty/zero bound here is harmless when the loop is
    running with the validator disabled.
    """
    try:
        from bridge.config import load_config

        cfg = load_config(skip_secrets=True, skip_validation=True)
        return (
            bool(getattr(cfg, "experiment_validator_enabled", False)),
            float(getattr(cfg, "experiment_validator_cost_cap_usd", 0.30)),
            str(getattr(cfg, "experiment_validator_model", "haiku")),
            int(getattr(cfg, "experiment_validator_timeout_seconds", 0)),
            int(getattr(cfg, "experiment_validator_min_signals", 0)),
        )
    except Exception as exc:  # noqa: BLE001 — config lookup must not block
        log.warning("experiment-loop validator: config lookup failed: %s", exc)
        return (False, 0.30, "haiku", 0, 0)


# ``_parse_validator_subprocess_cost`` was moved to
# ``bridge.experiment_runtime`` by Sprint audit-2026-05-16.E.04
# (#2072); see the re-export block near the top of this module. The
# module-level ``_MISSING`` sentinel moved with it (it was only used
# inside that parser).


def _make_validator_runner() -> object:
    """Return an async ValidatorRunner backed by a claude -p subprocess.

    Sprint D1.1 (#1173) — builds the runner callable required by
    ``validate_experiment(..., validator_runner=...)``. The runner:
      - invokes CLAUDE_BIN with ``--allowedTools ""`` (empty-tools contract),
      - returns ``(response_text, cost_usd, latency_ms)``,
      - times out after 60 s (well inside CLAUDE_TIMEOUT),
      - is fully fail-soft: exceptions propagate to ``run_validator``'s
        existing error handler which converts them to UNSURE verdicts.

    Sprint audit-2026-05-16.D.06 (#2067) — the runner now invokes the
    Claude CLI with ``--output-format stream-json --verbose`` so the
    terminal ``result`` event carries ``cost_usd``. The parser
    ``_parse_validator_subprocess_cost`` returns a ``CostMeasurement``;
    when ``source == 'unknown'`` the runner returns ``float('nan')``
    rather than the prior hardcoded ``0.0`` so downstream code can
    distinguish measured-zero from missing-data. The last assistant
    text content is extracted to keep the legacy
    ``(response, cost, latency_ms)`` tuple shape that
    ``run_validator`` consumes.
    """
    oauth_token = _load_oauth_token()

    async def _runner(prompt: str) -> tuple[str, float, int]:
        import math as _math
        import time as _time

        env = os.environ.copy()
        env["HOME"] = str(CLAUDE_HOME)
        if oauth_token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token

        started = _time.monotonic()
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                [
                    str(CLAUDE_BIN), "-p",
                    "--output-format", "stream-json",
                    "--verbose",
                    "--max-turns", "0",
                    "--allowedTools", "",
                    "--setting-sources", "user",
                ],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(AGENT_DIR),
                env=env,
            ),
        )
        latency_ms = int((_time.monotonic() - started) * 1000)

        # Sprint D.06: parse cost from stream-json instead of zeroing it.
        # Empty stdout (non-zero exit, crash) parses to unknown — the
        # runner's contract with ``run_validator`` is fail-soft; the
        # parser's ``unknown`` state propagates through the NaN sentinel
        # so validate_experiment can record ``iteration_cost_unknown``
        # rather than silently coercing to 0.0.
        measurement = _parse_validator_subprocess_cost(result.stdout)
        response_text = _extract_assistant_text(result.stdout)
        if measurement.source == "measured" and measurement.amount_usd is not None:
            cost_for_legacy: float = float(measurement.amount_usd)
        else:
            cost_for_legacy = _math.nan
        return (response_text, cost_for_legacy, latency_ms)

    return _runner


def _extract_assistant_text(stdout: str) -> str:
    """Reassemble assistant text from Claude stream-json output.

    Sprint audit-2026-05-16.D.06 (#2067) — the runner switched from
    ``--output-format text`` (which returned the full response on
    stdout as plain text) to ``--output-format stream-json``, so the
    visible answer must be reconstructed from the assistant events.
    Walks every ``type=="assistant"`` event and concatenates the
    ``text`` blocks from ``message.content``. The terminal
    ``type=="result"`` event also carries the final ``result`` text;
    we prefer the result event's ``result`` field when present (it's
    the post-stream-coalesced final answer) and fall back to the
    accumulated assistant chunks otherwise.
    """
    if not stdout:
        return ""

    accumulated_chunks: list[str] = []
    result_text: str = ""
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(event, dict):
            continue
        etype = event.get("type")
        if etype == "assistant":
            message = event.get("message", {})
            if isinstance(message, dict):
                for block in message.get("content", []) or ():
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        text_chunk = block.get("text", "")
                        if isinstance(text_chunk, str) and text_chunk:
                            accumulated_chunks.append(text_chunk)
        elif etype == "result":
            rt = event.get("result", "")
            if isinstance(rt, str):
                result_text = rt

    return (result_text or "".join(accumulated_chunks)).strip()


def main(mode: str = "shadow") -> None:
    """Main experiment loop.

    Sprint audit-2026-05-15.B.01 (#1996) replaced the legacy ``dry_run``
    boolean with ``mode`` — one of ``proposal_only`` / ``shadow`` /
    ``production``. Sprint audit-2026-05-15.B.02 (#1997) collapsed the
    three per-mode ``if`` branches that A.02 left in this body into one
    ``MergePolicy`` seam constructed via :func:`select_policy`.
    """
    if mode not in VALID_MODES:
        raise ValueError(f"Unknown mode: {mode!r}")
    _setup_logging()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    _ensure_db()

    log.info("Experiment loop started (mode=%s)", mode)
    ensure_hook_dirs()

    # Sprint audit-2026-05-15.C.05 (#2002) — load BridgeConfig once so
    # ``_check_halt(cfg)`` can resolve ``halt.flag`` on every iteration.
    # Uses the existing ``load_config`` factory (matches the fail-soft
    # pattern in ``_load_audit_branch_settings`` / ``_load_mailbox_settings``).
    # Failure to load is fail-soft: halt-honoring degrades to a no-op
    # rather than blocking the loop from running at all.
    try:
        from bridge.config import load_config

        cfg = load_config(skip_secrets=True, skip_validation=True)
    except Exception as exc:  # noqa: BLE001 — config lookup must not block
        log.warning(
            "halt-honoring: load_config() failed (%s) — halt.flag will be ignored",
            exc,
        )
        cfg = None

    # Sprint audit-2026-05-16.C.03 (#2058) — construct the loop's
    # HaltPolicy once. Reused across every iteration; the callables
    # read fresh halt.flag state on every check so a halt that fires
    # mid-iteration is seen by the next checkpoint without rebuilding
    # the policy. cfg=None degrades to a permanently-unblocked
    # policy (fail-soft, matches _check_halt(None)).
    halt_policy = _build_loop_halt_policy(cfg)

    # Sprint audit-2026-05-16.A.05 (#2049) — operator throttle for the
    # first production unhalt. cfg=None preserves the pre-A.05 defaults
    # (no cap, no cooldown) so the fail-soft config-load path doesn't
    # accidentally throttle the loop.
    throttle = ExperimentThrottle(
        max_iterations_per_hour=(
            getattr(cfg, "experiment_max_iterations_per_hour", None)
            if cfg is not None
            else None
        ),
        cooldown_after_merge_seconds=(
            getattr(cfg, "experiment_cooldown_after_merge_seconds", 0)
            if cfg is not None
            else 0
        ),
    )
    log.info(
        "experiment-loop throttle: max_per_hour=%s cooldown_seconds=%s",
        throttle.max_iterations_per_hour,
        throttle.cooldown_after_merge_seconds,
    )

    # Sprint audit-2026-05-15.B.02 (#1997) — single per-mode seam. The
    # policy owns the keep/discard fork; ``proposal_only`` short-circuits
    # the iteration body via ``PrePolicy``, ``shadow``/``production`` use
    # ``PostPolicy``.
    #
    # Sprint audit-2026-05-16.E.01 (#2069) — policy construction is now
    # per-iteration so the ``merge_fn`` closure can capture the
    # per-iteration ``iter_id`` for the autonomous-commit trailers
    # (Bumba-Agent-Experiment / Experiment-Run-Id / Experiment-Mode).
    # The shadow + proposal_only paths discard merge_fn anyway, so the
    # extra construction is microsecond-scale.

    # Sprint 15.02 (#1052) — operator opt-in mailbox channel between this
    # loop and the worktree subprocess. We read the flag once at startup
    # so a mid-run config change doesn't change behavior; a restart picks
    # up the new value.
    mailbox_enabled, _poll_interval, vacuum_keep_n = _load_mailbox_settings()
    log.info("experiment-loop mailbox: enabled=%s", mailbox_enabled)

    # Sprint 02.04 (#978) — append-only audit-branch trail.
    # Sprint audit-2026-05-16.E.02 (#2070) — third bool ``audit_local_cleanup``
    # gates post-merge local-branch deletion (only effective when
    # enabled=True AND push_to_origin=False; off + remote modes ignore it).
    audit_enabled, audit_push, audit_local_cleanup = _load_audit_branch_settings()
    log.info(
        "experiment-loop audit-branches: enabled=%s push_to_origin=%s local_cleanup=%s",
        audit_enabled,
        audit_push,
        audit_local_cleanup,
    )
    # E.02 (#2070) — derive the operator-facing mode label once.
    if not audit_enabled:
        audit_mode = "off"
    elif audit_push:
        audit_mode = "remote"
    else:
        audit_mode = "local"

    # Sprint D1.1 (#1173) — holdout validator flags read once at startup.
    # Sprint audit-2026-05-16.E.03 (#2071) — extended to read timeout +
    # min-signals bounding fields; gate at _validate enforces > 0 when
    # _validator_enabled is True.
    (
        _validator_enabled,
        _validator_cap,
        _validator_model,
        _validator_timeout_seconds,
        _validator_min_signals,
    ) = _load_validator_settings()
    log.info("experiment-loop validator: enabled=%s model=%s", _validator_enabled, _validator_model)

    while not _shutdown:
        # Sprint 02.13 (#988) — initialize iter_id outside the try so the
        # crash-path heartbeat below can reference it even if we fail
        # before the regular start-of-iteration heartbeat fires.
        iter_id = uuid.uuid4().hex[:12]
        started_iso = _now_iso()
        # Sprint audit-2026-05-16.E.01 (#2069) — bind the per-iteration
        # iter_id + mode into the merge_fn closure so production-merge
        # commits carry stable Bumba-Agent-Experiment trailers. Captured
        # in default args to avoid the late-binding closure trap.
        def _merge_with_trailers(
            worktree: str,
            branch: str,
            description: str,
            *,
            _iter_id: str = iter_id,
            _mode: str = mode,
        ) -> str | None:
            return merge_experiment(
                worktree, branch, description, run_id=_iter_id, mode=_mode
            )
        policy = select_policy(mode, merge_fn=_merge_with_trailers)
        try:
            # Sprint audit-2026-05-15.C.05 (#2002) — honor /halt at the
            # top of every iteration BEFORE pick_experiment fires. If
            # halted, write a paused heartbeat and sleep so the loop
            # backs off without burning Claude calls.
            halted, halt_reason = _check_halt(cfg)
            if halted:
                log.warning(
                    "Halt flag active (%s) — skipping iteration %s",
                    halt_reason or "(no reason recorded)",
                    iter_id,
                )
                _record_paused_heartbeat(halt_reason)
                time.sleep(60)
                continue

            # Sprint audit-2026-05-16.A.05 (#2049, Section 8.3) —
            # operator throttle. Sits AFTER the halt-policy check
            # (C.03/C.05) and BEFORE any expensive work (budget /
            # pick_experiment / claude). On block: write a paused
            # heartbeat tagged with the throttle decision and sleep
            # one cooldown cycle before re-checking. Iteration is not
            # logged to experiment_log, so the cap-overrun + cooldown
            # windows do NOT increment iteration_count_today
            # (documented in the F.03 runbook).
            ok, throttle_reason = _should_start_iteration(
                throttle,
                now_iter_count_last_hour=_iterations_in_last_hour(),
                now_seconds_since_merge=_seconds_since_last_merge(),
            )
            if not ok:
                log.info(
                    "Throttle active (%s) — skipping iteration %s",
                    throttle_reason,
                    iter_id,
                )
                _record_throttled_heartbeat(
                    mode, throttle, throttle_reason or "throttled"
                )
                time.sleep(60)
                continue

            if not check_experiment_budget():
                log.info("Daily experiment budget exhausted, sleeping 1h")
                for _ in range(3600):
                    if _shutdown:
                        break
                    time.sleep(1)
                continue

            # Sprint 02.13 (#988) — heartbeat at iteration start so a
            # stuck pick_experiment / Claude call still produces a
            # discoverable "running" state. completed_at stays None
            # until the iteration finishes.
            _safe_heartbeat(
                iter_id=iter_id,
                started_at_iso=started_iso,
                completed_at_iso=None,
                status="running",
            )

            # Sprint 02.06: fire before-experiment hooks. Hook output
            # is logged but not allowed to abort the iteration.
            before_results: list[HookResult] = run_hooks(
                "before",
                {"iter_id": iter_id, "phase": "before"},
            )
            if before_results:
                log.info(
                    "before-experiment hooks: %s",
                    summarize_results(before_results),
                )

            # 1. Pick experiment
            history = get_recent_experiments(limit=10)
            log.info("Picking experiment (history: %d entries)", len(history))
            description = pick_experiment(history, iter_id=iter_id)
            if not description:
                log.info("No proposal received, retrying next cycle")
                continue
            log.info("Experiment proposed: %s", description[:200])

            # Sprint audit-2026-05-15.B.02 (#1997) — proposal_only
            # short-circuit. PrePolicy executes BEFORE any worktree work;
            # the iteration records the proposal row and exits. No
            # run_experiment, no validate_experiment, no notify_discord —
            # proposal_only is observability-only.
            if isinstance(policy, PrePolicy):
                outcome = policy.pre_outcome({"description": description})
                log.info(
                    "Proposal-only iteration: %s",
                    description[:200],
                )
                try:
                    log_result({
                        "status": outcome.status,
                        "description": description[:400],
                    })
                except Exception as log_exc:  # noqa: BLE001
                    log.warning("proposal_skipped log_result failed: %s", log_exc)
                continue

            if mode == "shadow":
                log.info(
                    "Shadow iteration: proposed %s — will execute without merge",
                    description[:200],
                )

            # 2. Run experiment in worktree
            #    Sprint 15.02 (#1052) — open the bridge-side mailbox if
            #    the operator has opted in. Messages from the worker are
            #    surfaced to the existing notifier path; on-iteration
            #    cleanup vacuums the outbound table per the configured
            #    cap.
            # Sprint audit-2026-05-15.C.02 (#1999) — bind ``exp`` before the
            # try so that if ``run_experiment`` raises, the ``finally`` and
            # the post-finally guard can read ``exp`` without an
            # ``UnboundLocalError`` masking the original traceback.
            exp: dict | None = None
            iter_mailbox: Mailbox | None = (
                _open_bridge_mailbox() if mailbox_enabled else None
            )
            start_time = time.time()
            try:
                exp = run_experiment(
                    description, iter_id=iter_id, mailbox=iter_mailbox
                )
            finally:
                # Surface anything the worker emitted (best-effort) and
                # vacuum so the bridge DB stays bounded.
                if iter_mailbox is not None:
                    for m in exp.get("mailbox_messages", []) if isinstance(exp, dict) else []:
                        _surface_progress_message(m.get("payload", {}))
                    try:
                        iter_mailbox.vacuum(keep_last_n=vacuum_keep_n)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("experiment-loop mailbox: vacuum failed: %s", exc)
                    iter_mailbox.close()

            # Sprint audit-2026-05-15.C.02 (#1999) — guard the downstream
            # ``exp[...]`` dereference cluster. ``run_experiment`` may return
            # a non-dict on edge paths; raising paths are already caught by
            # the outer ``except Exception`` handler below, so reaching here
            # with ``exp`` unbound to a dict is the empty/wrong-shape case.
            if not isinstance(exp, dict):
                log.error(
                    "Iteration %s: run_experiment did not return a dict (raised or empty) — "
                    "skipping result composition for this iteration",
                    iter_id,
                )
                continue

            log.info("Experiment %s: Claude exit code %d", exp["id"], exp["claude_exit_code"])

            # Sprint audit-2026-05-16.C.03 (#2058) — checkpoint after the
            # long claude-apply subprocess returns. C.05 has the top-of-
            # iteration and pre-merge checks; this is the gap between
            # them. If /halt fired during the apply (~minutes long), the
            # iteration drops here: cleanup the worktree, write a paused
            # heartbeat, skip validate/merge/notify. Applies to all
            # modes (shadow + production) so halt always interrupts in-
            # flight work regardless of merge eligibility.
            decision = halt_policy.check_continue("experiment_loop")
            if decision.blocked:
                log.error(
                    "Halt active mid-iteration (%s) — skipping validate+merge for %s",
                    decision.reason or "(no reason recorded)",
                    exp.get("branch"),
                )
                cleanup_worktree(exp["worktree"], exp.get("branch"))
                _record_paused_heartbeat(decision.reason)
                continue

            # 3. Validate
            # Sprint D1.1 (#1173) — thread validator config fields into the call.
            # Sprint audit-2026-05-16.C.03 (#2058) — thread halt_policy so
            # the pytest subprocess is cancellable mid-run.
            validation = validate_experiment(
                exp["worktree"],
                iter_id=iter_id,
                validator_enabled=_validator_enabled,
                validator_cost_cap_usd=_validator_cap,
                validator_model=_validator_model,
                validator_timeout_seconds=_validator_timeout_seconds,
                validator_min_signals=_validator_min_signals,
                validator_runner=_make_validator_runner() if _validator_enabled else None,
                halt_policy=halt_policy,
            )
            # Sprint audit-2026-05-16.C.03 (#2058) — if pytest was
            # cancelled mid-flight, validate_experiment returned a
            # structured halted_in_flight record. Cleanup + paused
            # heartbeat + continue (don't reach log_result/notify).
            if validation.get("status") == "halted_in_flight":
                log.error(
                    "Iteration %s: pytest halted in-flight — cleaning up %s",
                    iter_id,
                    exp.get("branch"),
                )
                cleanup_worktree(exp["worktree"], exp.get("branch"))
                _record_paused_heartbeat(validation.get("diff_summary"))
                continue
            duration = time.time() - start_time
            validation["duration_seconds"] = duration

            log.info(
                "Experiment %s: status=%s tests=%d/%d",
                exp["id"],
                validation["status"],
                validation["tests_passed"],
                validation["tests_total"],
            )

            result_record = {
                **validation,
                "branch": exp["branch"],
                "description": description[:500],
                # Sprint 15.02 (#1052) — surface mailbox messages on the
                # iteration record so log_result can persist them into
                # experiments.jsonl for operator inspection.
                "mailbox_messages": exp.get("mailbox_messages", []),
            }

            # 3.5. Audit branch (Sprint 02.04 / #978) — create permanent
            #      ``autoresearch/iter-{iter_id}`` branch BEFORE the
            #      keep/discard fork so the audit trail survives even on
            #      the discard / crash paths. Wrapped in full fail-soft
            #      semantics; never blocks the iteration.
            audit_branch_result: AuditBranchResult | None = None
            if audit_enabled:
                # Sprint audit-2026-05-16.E.01 (#2069) — thread iter_id +
                # mode so the worktree-side pre-commit (audit-branch path)
                # carries the same Bumba-Agent-Experiment trailers as the
                # merge-path commit.
                audit_sha = _ensure_worktree_commit(
                    exp["worktree"], description, run_id=iter_id, mode=mode
                )
                if audit_sha:
                    audit_branch_result = _create_audit_branch_safe(
                        iter_id=iter_id,
                        head_sha=audit_sha,
                        push_to_origin=audit_push,
                    )
                    if audit_branch_result is not None:
                        log.info(
                            "audit-trail: created %s at %s (pushed=%s)",
                            audit_branch_result.branch_name,
                            audit_branch_result.commit_sha[:12],
                            audit_branch_result.pushed,
                        )
                        if audit_branch_result.push_error:
                            log.warning(
                                "audit-trail: push error: %s",
                                audit_branch_result.push_error,
                            )

            # 4. Sprint audit-2026-05-15.B.02 (#1997) — single seam call.
            #    PostPolicy owns the merge/discard fork and the final
            #    status vocabulary:
            #      - ShadowPolicy   → ``shadow_keep`` / ``shadow_discard``
            #      - ProductionPolicy → ``keep`` / ``discard`` (and calls
            #        ``merge_experiment`` via the injected merge_fn)
            #    ShadowPolicy never holds a merge_fn — by construction it
            #    cannot merge — so the invariant is in the type, not in a
            #    runtime ``if``. ``shadow_crash`` is the exception
            #    wrapper's responsibility (see ``except`` below).
            ctx_validation = types.SimpleNamespace(
                status=validation["status"],
                summary=validation.get("summary"),
            )
            halted_pre_merge = False
            halt_reason_pre_merge: str | None = None
            # Sprint audit-2026-05-15.C.05 (#2002) — pre-merge halt check
            # (production only). If /halt fired between validation and
            # merge, pass the state through IterationContext so the
            # merge-policy seam owns the ``halted_pre_merge`` outcome.
            if mode == "production":
                halted_pre_merge, halt_reason_pre_merge = _check_halt(cfg)
                if halted_pre_merge:
                    log.error(
                        "Halt active mid-iteration (%s) — skipping merge for %s",
                        halt_reason_pre_merge or "(no reason recorded)",
                        exp["branch"],
                    )

            ctx = IterationContext(
                worktree=exp["worktree"],
                branch=exp["branch"],
                description=description,
                validation=ctx_validation,
                exp=exp,
                audit_enabled=audit_enabled,
                audit_branch_sha=(
                    audit_branch_result.commit_sha
                    if audit_branch_result is not None
                    else None
                ),
                halted=halted_pre_merge,
                halt_reason=halt_reason_pre_merge,
            )
            outcome = policy.post_outcome(ctx)
            commit = outcome.commit_sha
            if commit:
                result_record["commit_hash"] = commit
                log.info("Experiment merged: %s", commit[:12])
            elif (
                outcome.status == "discard"
                and validation["status"] == "keep"
            ):
                # Production keep that failed to fast-forward — preserve
                # A.02's "(main moved)" suffix so operator-visible
                # behavior is unchanged across the refactor.
                result_record["description"] = description[:400] + " (main moved)"
                log.info("Experiment discarded (main moved during run)")
            cleanup_worktree(exp["worktree"], exp["branch"])

            result_record["status"] = outcome.status

            # 4.5. Annotate audit branch with the finalized outcome
            #      (Sprint 02.04 / #978). Idempotent + fail-soft.
            if audit_branch_result is not None:
                _annotate_audit_branch_safe(
                    audit_branch_result.branch_name,
                    outcome=str(result_record.get("status", "crash")),
                )

            # 4.6. Sprint audit-2026-05-16.E.02 (#2070) — auto-cleanup of
            #      local audit branches after a successful merge. Gate:
            #      enabled AND not push_to_origin AND local_cleanup AND
            #      the iteration actually merged (commit_sha non-None,
            #      i.e. status == "keep"). The keep-vs-discard fork is
            #      captured by ``commit is not None`` — discards never
            #      delete the audit branch so forensic inspection of the
            #      discard path still has a branch to read.
            audit_cleanup_status: str = "n/a"
            if audit_branch_result is not None:
                if (
                    audit_enabled
                    and not audit_push
                    and audit_local_cleanup
                    and commit is not None
                ):
                    cleanup_ok, cleanup_err = _cleanup_local_audit_branch(
                        audit_branch_result.branch_name
                    )
                    if cleanup_ok:
                        log.info(
                            "audit-trail: cleaned up local audit branch %s",
                            audit_branch_result.branch_name,
                        )
                        audit_cleanup_status = "ok"
                    else:
                        log.warning(
                            "audit-trail: cleanup of %s failed: %s",
                            audit_branch_result.branch_name,
                            cleanup_err,
                        )
                        audit_cleanup_status = "failed"
                else:
                    audit_cleanup_status = "skipped"

            # 5. Log and notify
            log_result(result_record)
            notify_discord(result_record, iter_id=iter_id)

            # Sprint 02.06: fire after-experiment hooks. Pass the
            # logged record so hooks can attribute output to the
            # iteration; result is best-effort observability.
            after_results = run_hooks(
                "after",
                {
                    "iter_id": iter_id,
                    "phase": "after",
                    "status": result_record.get("status"),
                    "branch": result_record.get("branch"),
                    "commit_hash": result_record.get("commit_hash"),
                    "tests_passed": result_record.get("tests_passed"),
                    "tests_total": result_record.get("tests_total"),
                },
            )
            if after_results:
                log.info(
                    "after-experiment hooks: %s",
                    summarize_results(after_results),
                )

            # Sprint 02.13 (#988) — iteration complete heartbeat. Fitness
            # comes from the validation snapshot when present; otherwise
            # left None so /health surfaces the status without claiming a
            # synthetic value.
            fitness = None
            snapshot = result_record.get("fitness_snapshot")
            if isinstance(snapshot, dict):
                fitness = snapshot.get("after_value")
            try:
                fitness_float = float(fitness) if fitness is not None else None
            except (TypeError, ValueError):
                fitness_float = None
            _safe_heartbeat(
                iter_id=iter_id,
                started_at_iso=started_iso,
                completed_at_iso=_now_iso(),
                status="idle",
                fitness_value=fitness_float,
            )

            # Sprint audit-2026-05-15.D.02 (#2004) — operator-facing JSON
            # heartbeat. Distinct from _safe_heartbeat above: this one is
            # consumed by /status and readiness.sh and uses the
            # iteration's final result status (shadow_keep / keep /
            # discard / halted_pre_merge / etc.) rather than the
            # /healthz idle|running|crashed lifecycle vocabulary. Wrapped
            # in its own try/except so a heartbeat-JSON failure cannot
            # cascade into the per-iteration handler below.
            try:
                _write_heartbeat(
                    mode=mode,
                    status=str(result_record.get("status", "unknown")),
                    branch=exp.get("branch") if isinstance(exp, dict) else None,
                    # Sprint audit-2026-05-16.A.05 (#2049) — surface
                    # throttle config + most recent decision ("ok"
                    # because this iteration cleared the gate).
                    throttle=throttle,
                    throttle_decision="ok",
                    # Sprint audit-2026-05-16.E.02 (#2070) — surface
                    # audit-branch trial lifecycle for the operator.
                    audit_branches_enabled=audit_enabled,
                    audit_branches_mode=audit_mode,
                    audit_branches_local_cleanup=audit_local_cleanup,
                    audit_branches_last_branch=(
                        audit_branch_result.branch_name
                        if audit_branch_result is not None
                        else None
                    ),
                    audit_branches_last_cleanup_status=audit_cleanup_status,
                )
            except Exception as hb_exc:  # noqa: BLE001
                log.warning("D.02 heartbeat write failed: %s", hb_exc)

        except Exception as e:
            log.exception("Experiment loop error: %s", e)
            # Sprint 02.13 (#988) — record the crash so /healthz surfaces
            # it; the operator can see *which* iteration crashed.
            _safe_heartbeat(
                iter_id=iter_id,
                started_at_iso=started_iso,
                completed_at_iso=_now_iso(),
                status="crashed",
            )
            # Sprint audit-2026-05-15.A.02 — shadow iterations that crash
            # before reaching log_result still need an experiment_log row
            # so #987's evidence trail is complete. Production crash path
            # is intentionally unchanged (no log_result call) to preserve
            # the pre-A.02 audit-trail behavior.
            #
            # Sprint audit-2026-05-15.B.02 (#1997) — this wrapper is the
            # ONLY producer of ``shadow_crash``. ``ShadowPolicy.post_outcome``
            # MUST NOT set it (see type-design note 5 in the plan): the
            # crash happens before ``post_outcome`` is ever called, so the
            # policy module has no way to know. Keep the assignment here.
            if mode == "shadow":
                try:
                    log_result({
                        "status": "shadow_crash",
                        "description": (
                            locals().get("description", "")[:400]
                            if isinstance(locals().get("description"), str)
                            else ""
                        ),
                    })
                except Exception as log_exc:  # noqa: BLE001
                    log.warning("shadow_crash log_result failed: %s", log_exc)

        # Sleep in short intervals so Ctrl+C / SIGTERM responds quickly
        for _ in range(COOLDOWN_SECONDS):
            if _shutdown:
                break
            time.sleep(1)

    # Sprint audit-2026-05-15.D.02 (#2004) — final JSON heartbeat so a
    # readiness probe after graceful shutdown sees ``"stopped"`` rather
    # than a stale iteration record. Wrapped to ensure shutdown logging
    # below still fires even if the heartbeat write fails.
    try:
        _write_heartbeat(mode=mode, status="stopped", branch=None)
    except Exception as hb_exc:  # noqa: BLE001
        log.warning("D.02 shutdown heartbeat write failed: %s", hb_exc)

    log.info("Experiment loop stopped")


def _resolve_mode(argv: list[str], config_mode: str) -> str:
    """Resolve the runtime mode from CLI argv + config default.

    Sprint audit-2026-05-15.B.01 (#1996). Precedence: ``--dry-run``
    (deprecated, maps to ``proposal_only``) > ``--mode <m>`` > config
    default. The deprecation warning is emitted with ``stacklevel=2``
    so the caller's location appears in the warning.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--mode", choices=sorted(VALID_MODES), default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DEPRECATED — use --mode proposal_only",
    )
    args, _ = parser.parse_known_args(argv)
    if args.dry_run:
        warnings.warn(
            "--dry-run is deprecated; use --mode proposal_only",
            DeprecationWarning,
            stacklevel=2,
        )
        return "proposal_only"
    return args.mode or config_mode


if __name__ == "__main__":
    # Sprint audit-2026-05-15.F.03 (#2017) — `BridgeConfig.load()` is an
    # AttributeError (no classmethod exists on the frozen dataclass); the
    # correct factory is the module-level `load_config()` at config.py:1643.
    # See feedback_bridgeconfig_no_load_classmethod memory.
    from bridge.config import load_config

    cfg = load_config(skip_secrets=True, skip_validation=True)
    resolved_mode = _resolve_mode(sys.argv[1:], cfg.experiment_mode)
    main(mode=resolved_mode)
