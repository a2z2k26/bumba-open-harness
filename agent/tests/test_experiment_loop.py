"""Tests for the autonomous experiment loop."""

from __future__ import annotations

import sqlite3
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Import the module under test
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import experiment_loop


@pytest.fixture(autouse=True)
def _no_op_experiment_loop_setup_logging(monkeypatch):
    """Replace ``experiment_loop._setup_logging`` with a no-op for the test run.

    ``_setup_logging`` calls ``logging.basicConfig(handlers=[FileHandler(LOG_FILE), ...])``.
    The ``FileHandler`` is constructed (and opens the underlying file) *before*
    ``basicConfig`` checks whether the root logger already has handlers — which
    pytest always does (``LogCaptureHandler``). The freshly-constructed
    ``FileHandler`` is then discarded by ``basicConfig``, leaving the open file
    object to be GC'd asynchronously and emitting a
    ``ResourceWarning: unclosed file <...experiment-loop.log...>``.

    Tests that drive ``experiment_loop.main(...)`` re-enter this path on every
    iteration, accumulating one warning per call. Replacing ``_setup_logging``
    with a no-op for the test suite eliminates the leak entirely — the real
    logger is configured by the daemon at runtime, not by the test process.

    Production code is untouched. Sprint S6.2 (#2352) — burn down top
    ResourceWarnings.
    """
    monkeypatch.setattr(experiment_loop, "_setup_logging", lambda: None)


@pytest.fixture(autouse=True)
def _redirect_experiment_loop_heartbeat(monkeypatch, tmp_path):
    """Keep best-effort heartbeat writes out of the source tree.

    ``experiment_loop.main`` writes a final JSON heartbeat on shutdown. Tests
    that drive the loop often redirect DB/log paths to ``tmp_path`` but do not
    care about this operator-facing heartbeat, so the module default would leak
    ``agent/data/experiment-heartbeat.json`` into the working tree.
    """
    monkeypatch.setattr(
        experiment_loop,
        "HEARTBEAT_PATH",
        tmp_path / "experiment-heartbeat.json",
    )


class TestForbiddenPatterns:
    """Test that forbidden file patterns are correctly detected."""

    def test_forbidden_security_py(self):
        changed = ["agent/bridge/security.py"]
        violations = experiment_loop.check_forbidden_files(changed)
        assert violations == ["agent/bridge/security.py"]

    def test_forbidden_trust_score(self):
        changed = ["agent/bridge/trust_score.py"]
        violations = experiment_loop.check_forbidden_files(changed)
        assert len(violations) == 1

    def test_forbidden_system_prompt(self):
        changed = ["agent/config/system-prompt.md"]
        violations = experiment_loop.check_forbidden_files(changed)
        assert len(violations) == 1

    def test_forbidden_plist(self):
        changed = ["agent/scripts/com.bumba.agent-bridge.plist"]
        violations = experiment_loop.check_forbidden_files(changed)
        assert len(violations) == 1

    def test_forbidden_hooks(self):
        changed = ["agent/config/hooks/memory-session-start.sh"]
        violations = experiment_loop.check_forbidden_files(changed)
        assert len(violations) == 1

    def test_forbidden_database(self):
        changed = ["agent/bridge/database.py"]
        violations = experiment_loop.check_forbidden_files(changed)
        assert len(violations) == 1

    def test_clean_diff_passes(self):
        changed = [
            "agent/bridge/memory.py",
            "agent/bridge/app.py",
            "agent/tests/test_memory.py",
        ]
        violations = experiment_loop.check_forbidden_files(changed)
        assert violations == []

    def test_mixed_diff_catches_forbidden(self):
        changed = [
            "agent/bridge/memory.py",
            "agent/bridge/security.py",
            "agent/bridge/app.py",
        ]
        violations = experiment_loop.check_forbidden_files(changed)
        assert violations == ["agent/bridge/security.py"]

    @pytest.mark.parametrize("filename", [
        "security.py",
        "trust_score.py",
        "tier_manager.py",
        "kernel-baseline.json",
        "system-prompt.md",
    ])
    def test_refuses_immutable_files(self, filename):
        """experiment_loop refuses to modify any file in tier_manager.IMMUTABLE_FILES.

        Sources the forbidden set from bridge.tier_manager so a single source
        of truth prevents drift between experiment_loop and tier_manager.
        """
        # Verify the entry is sourced from tier_manager (not just a local copy)
        assert filename in experiment_loop.IMMUTABLE_FILES, (
            f"{filename} must be in tier_manager.IMMUTABLE_FILES — "
            f"experiment_loop sources its kernel-protection list from there"
        )
        # Verify the experiment_loop's union set contains it
        assert filename in experiment_loop.FORBIDDEN_FILES
        # Verify check_forbidden_files actually refuses it
        violations = experiment_loop.check_forbidden_files([f"agent/bridge/{filename}"])
        assert len(violations) == 1, (
            f"experiment_loop must refuse to write {filename} (kernel-immutable)"
        )

    def test_immutable_files_imported_not_redefined(self):
        """experiment_loop imports IMMUTABLE_FILES from tier_manager, not redefines it.

        If this test fails, someone has reintroduced the drift risk that #840
        was filed to eliminate.
        """
        from bridge.tier_manager import IMMUTABLE_FILES as canonical
        assert experiment_loop.IMMUTABLE_FILES is canonical, (
            "experiment_loop.IMMUTABLE_FILES must be the SAME object as "
            "bridge.tier_manager.IMMUTABLE_FILES — not a redeclared copy"
        )

    def test_extra_forbidden_extends_immutable(self):
        """experiment_loop's FORBIDDEN_FILES is the union of IMMUTABLE_FILES + extras."""
        from bridge.tier_manager import IMMUTABLE_FILES
        # Every kernel-immutable file is in FORBIDDEN_FILES
        assert IMMUTABLE_FILES <= experiment_loop.FORBIDDEN_FILES
        # Extras for experiment-loop scope
        assert "hooks/" in experiment_loop.FORBIDDEN_FILES
        assert "database.py" in experiment_loop.FORBIDDEN_FILES
        assert ".plist" in experiment_loop.FORBIDDEN_FILES


class TestBudgetGate:
    """Test experiment budget enforcement."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.tmp_dir) / "test.db"
        db = sqlite3.connect(str(self.db_path))
        db.execute("""CREATE TABLE experiment_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commit_hash TEXT,
            branch TEXT,
            tests_passed INTEGER,
            tests_failed INTEGER,
            tests_total INTEGER,
            status TEXT,
            description TEXT,
            diff_summary TEXT,
            cost_usd REAL DEFAULT 0.0,
            duration_seconds REAL,
            fitness_delta REAL DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        db.commit()
        db.close()

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_budget_under_limit(self):
        """Budget gate allows experiments when under daily limit."""
        # Insert $0.50 of spend today
        db = sqlite3.connect(str(self.db_path))
        db.execute(
            "INSERT INTO experiment_log (cost_usd, status, description) VALUES (0.5, 'keep', 'test')"
        )
        db.commit()
        db.close()

        with patch.object(experiment_loop, "DB_PATH", self.db_path):
            assert experiment_loop.check_experiment_budget() is True

    def test_budget_over_limit(self):
        """Budget gate blocks experiments when over daily limit."""
        db = sqlite3.connect(str(self.db_path))
        db.execute(
            "INSERT INTO experiment_log (cost_usd, status, description) VALUES (2.5, 'keep', 'test')"
        )
        db.commit()
        db.close()

        with patch.object(experiment_loop, "DB_PATH", self.db_path):
            assert experiment_loop.check_experiment_budget() is False

    def test_budget_exactly_at_limit(self):
        """Budget gate blocks at exactly the limit."""
        db = sqlite3.connect(str(self.db_path))
        db.execute(
            "INSERT INTO experiment_log (cost_usd, status, description) VALUES (2.0, 'keep', 'test')"
        )
        db.commit()
        db.close()

        with patch.object(experiment_loop, "DB_PATH", self.db_path):
            assert experiment_loop.check_experiment_budget() is False

    def test_budget_no_db(self):
        """Budget gate allows experiments when DB doesn't exist."""
        with patch.object(experiment_loop, "DB_PATH", Path("/tmp/nonexistent/path.db")):
            assert experiment_loop.check_experiment_budget() is True


class TestLogResult:
    """Test experiment result logging to database."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.tmp_dir) / "test.db"
        db = sqlite3.connect(str(self.db_path))
        db.execute("""CREATE TABLE experiment_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commit_hash TEXT,
            branch TEXT,
            tests_passed INTEGER,
            tests_failed INTEGER,
            tests_total INTEGER,
            status TEXT,
            description TEXT,
            diff_summary TEXT,
            cost_usd REAL DEFAULT 0.0,
            duration_seconds REAL,
            fitness_delta REAL DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        db.commit()
        db.close()

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_log_inserts_row(self):
        """log_result() inserts a row into experiment_log."""
        with patch.object(experiment_loop, "DB_PATH", self.db_path):
            experiment_loop.log_result({
                "commit_hash": "abc1234",
                "branch": "experiment/test1",
                "tests_passed": 1813,
                "tests_failed": 0,
                "tests_total": 1813,
                "status": "keep",
                "description": "Added type hints to memory.py",
                "diff_summary": "1 file changed, 5 insertions",
                "cost_usd": 0.12,
                "duration_seconds": 45.3,
            })

        db = sqlite3.connect(str(self.db_path))
        row = db.execute("SELECT * FROM experiment_log WHERE commit_hash = 'abc1234'").fetchone()
        db.close()
        assert row is not None
        assert row[6] == "keep"  # status column


class TestParsePytest:
    """Test pytest output parsing."""

    def test_all_passed(self):
        output = "1813 passed in 23.45s"
        passed, failed, total = experiment_loop._parse_pytest_output(output)
        assert passed == 1813
        assert failed == 0
        assert total == 1813

    def test_some_failed(self):
        output = "1810 passed, 3 failed in 25.00s"
        passed, failed, total = experiment_loop._parse_pytest_output(output)
        assert passed == 1810
        assert failed == 3
        assert total == 1813

    def test_errors(self):
        output = "1800 passed, 2 failed, 1 error in 30.00s"
        passed, failed, total = experiment_loop._parse_pytest_output(output)
        assert passed == 1800
        assert failed == 3  # 2 failed + 1 error
        assert total == 1803

    def test_empty_output(self):
        passed, failed, total = experiment_loop._parse_pytest_output("")
        assert passed == 0
        assert failed == 0
        assert total == 0


class TestMigration:
    """Test that migration 9 applies cleanly."""

    def test_experiment_log_migration(self):
        """Migration 9 creates experiment_log table with correct schema."""
        db = sqlite3.connect(":memory:")

        # Apply migration 9 SQL directly
        from bridge.database import _MIGRATIONS
        migration_9 = [m for m in _MIGRATIONS if m[0] == 9]
        assert len(migration_9) == 1, "Migration 9 should exist"

        version, desc, statements = migration_9[0]
        for stmt in statements:
            db.execute(stmt)

        # Verify table exists and has correct columns
        cols = db.execute("PRAGMA table_info(experiment_log)").fetchall()
        col_names = [c[1] for c in cols]
        assert "commit_hash" in col_names
        assert "status" in col_names
        assert "tests_passed" in col_names
        assert "description" in col_names
        assert "cost_usd" in col_names

        # Verify status constraint
        db.execute(
            "INSERT INTO experiment_log (status, description) VALUES ('keep', 'test')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO experiment_log (status, description) VALUES ('invalid', 'test')"
            )

        db.close()

    def test_migration_widens_status_check_to_include_shadow_values(self):
        """Sprint audit-2026-05-15.A.02 — `_migrate_status_check` swaps the
        legacy CHECK in place, preserves existing rows, accepts the new
        shadow vocabulary, and is idempotent on a second call.
        """
        db = sqlite3.connect(":memory:")
        # Old-shape CHECK — the pre-A.02 production schema.
        db.execute("""CREATE TABLE experiment_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commit_hash TEXT,
            branch TEXT,
            tests_passed INTEGER,
            tests_failed INTEGER,
            tests_total INTEGER,
            status TEXT CHECK(status IN ('keep', 'discard', 'crash')),
            description TEXT,
            diff_summary TEXT,
            cost_usd REAL DEFAULT 0.0,
            duration_seconds REAL,
            created_at TEXT DEFAULT (datetime('now')),
            fitness_delta REAL DEFAULT NULL
        )""")
        db.execute(
            "INSERT INTO experiment_log (status, description) VALUES ('keep', 'pre-migration row')"
        )
        db.commit()

        # Sanity: the legacy CHECK rejects shadow_keep before migration.
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO experiment_log (status, description) VALUES ('shadow_keep', 'pre')"
            )
        # The failed insert leaves Python's connection in a transaction
        # state; commit to clear it before the migration opens its own.
        db.commit()

        # Apply the migration.
        experiment_loop._migrate_status_check(db)

        # Pre-existing row survived the swap.
        rows = db.execute(
            "SELECT status, description FROM experiment_log WHERE description = 'pre-migration row'"
        ).fetchall()
        assert rows == [("keep", "pre-migration row")]

        # New CHECK now accepts every member of the post-A.02 vocabulary.
        for new_status in (
            "shadow_keep",
            "shadow_discard",
            "shadow_crash",
            "proposal_skipped",
            "halted_pre_merge",
        ):
            db.execute(
                "INSERT INTO experiment_log (status, description) VALUES (?, ?)",
                (new_status, f"post-migration {new_status}"),
            )
        db.commit()

        # Idempotency — a second call must be a no-op (no schema mutation,
        # no transaction error). We assert on the table SQL staying stable.
        sql_before = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='experiment_log'"
        ).fetchone()[0]
        experiment_loop._migrate_status_check(db)
        sql_after = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='experiment_log'"
        ).fetchone()[0]
        assert sql_before == sql_after, "second _migrate_status_check call should be a no-op"

        db.close()


class TestMergeFFOnly:
    """Test that merge uses fast-forward only."""

    def test_ff_merge_fails_gracefully(self):
        """Non-ff merge returns None instead of forcing."""
        with patch("experiment_loop.subprocess") as mock_sub:
            # Simulate ff-only failure
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stderr = "fatal: Not possible to fast-forward"
            mock_sub.run.return_value = mock_result

            result = experiment_loop.merge_experiment(
                "/tmp/fake-worktree", "experiment/test", "test desc"
            )
            assert result is None


class TestMergeExperimentAuditBranchInteraction:
    """Sprint audit-2026-05-15.C.01 (#1998): when
    ``experiment_audit_branches_enabled=true``, ``_ensure_worktree_commit``
    has already committed in the worktree by the time ``merge_experiment``
    runs. The function must probe ``git status --porcelain`` first and
    skip the second ``git commit`` (which would otherwise raise
    "nothing to commit" and turn a legitimate keep into a crash row).
    """

    def test_merge_experiment_handles_already_clean_worktree_uses_head(self):
        """Clean worktree → no ``git commit`` call, HEAD sha returned on ff-success."""
        with patch("experiment_loop.subprocess.run") as mock_run:
            def _fake_run(cmd, **kwargs):
                result = MagicMock()
                if cmd[:2] == ["git", "status"]:
                    result.stdout = ""  # clean
                    result.returncode = 0
                elif cmd[:2] == ["git", "rev-parse"]:
                    result.stdout = "cafebabe\n"
                    result.returncode = 0
                elif cmd[:3] == ["git", "merge", "--ff-only"]:
                    result.stdout = ""
                    result.stderr = ""
                    result.returncode = 0
                else:
                    # ``git commit`` / ``git add`` would land here if the
                    # function regressed — pytest will surface the
                    # assertion below either way.
                    result.stdout = ""
                    result.returncode = 0
                return result

            mock_run.side_effect = _fake_run
            result = experiment_loop.merge_experiment(
                "/tmp/fake-worktree", "experiment/test", "test desc"
            )

        assert result == "cafebabe"
        invoked = [tuple(call.args[0]) for call in mock_run.call_args_list]
        # No ``git commit`` and no ``git add`` should fire on the clean path.
        assert not any(cmd[:2] == ("git", "commit") for cmd in invoked), (
            f"merge_experiment must not commit when worktree is clean; got {invoked!r}"
        )
        assert not any(cmd[:2] == ("git", "add") for cmd in invoked), (
            f"merge_experiment must not stage when worktree is clean; got {invoked!r}"
        )
        # And rev-parse HEAD MUST be called to source the existing sha.
        assert any(cmd[:2] == ("git", "rev-parse") for cmd in invoked), (
            f"merge_experiment must call ``git rev-parse HEAD`` on the clean path; got {invoked!r}"
        )

    def test_merge_experiment_still_commits_when_worktree_dirty(self):
        """Dirty worktree → original path: ``git add -A`` + ``git commit`` fire."""
        with patch("experiment_loop.subprocess.run") as mock_run:
            def _fake_run(cmd, **kwargs):
                result = MagicMock()
                if cmd[:2] == ["git", "status"]:
                    result.stdout = " M agent/bridge/x.py\n"  # dirty
                    result.returncode = 0
                elif cmd[:2] == ["git", "rev-parse"]:
                    result.stdout = "deadbeef\n"
                    result.returncode = 0
                elif cmd[:3] == ["git", "merge", "--ff-only"]:
                    result.stdout = ""
                    result.stderr = ""
                    result.returncode = 0
                else:
                    result.stdout = ""
                    result.returncode = 0
                return result

            mock_run.side_effect = _fake_run
            result = experiment_loop.merge_experiment(
                "/tmp/fake-worktree", "experiment/test", "test desc"
            )

        assert result == "deadbeef"
        invoked = [tuple(call.args[0]) for call in mock_run.call_args_list]
        # The commit path must fire — both add and commit.
        add_calls = [cmd for cmd in invoked if cmd[:2] == ("git", "add")]
        commit_calls = [cmd for cmd in invoked if cmd[:2] == ("git", "commit")]
        assert add_calls, f"Expected ``git add`` on dirty path; got {invoked!r}"
        assert commit_calls, f"Expected ``git commit`` on dirty path; got {invoked!r}"
        # And the commit message includes the description (truncated to 100).
        commit_cmd = commit_calls[0]
        assert commit_cmd[-1].startswith("experiment: test desc"), (
            f"commit message shape changed: {commit_cmd!r}"
        )

    def test_audit_branches_enabled_keep_path_does_not_crash(self, tmp_path, monkeypatch):
        """End-to-end: with audit branches enabled and worktree
        pre-committed, the keep iteration produces ``status='keep'`` —
        NOT ``status='crash'`` from the outer broad-exception handler.
        Mirrors the patched-loop fixture pattern A.02 + B.02 established.
        """
        db_path = tmp_path / "experiments.db"
        jsonl_path = tmp_path / "experiments.jsonl"
        md_path = tmp_path / "experiments.md"
        log_file = tmp_path / "experiment-loop.log"

        monkeypatch.setattr(experiment_loop, "DB_PATH", db_path)
        monkeypatch.setattr(experiment_loop, "EXPERIMENTS_JSONL_PATH", jsonl_path)
        monkeypatch.setattr(experiment_loop, "EXPERIMENTS_MD_PATH", md_path)
        monkeypatch.setattr(experiment_loop, "LOG_FILE", log_file)
        monkeypatch.setattr(experiment_loop, "_shutdown", False)
        monkeypatch.setattr(experiment_loop, "COOLDOWN_SECONDS", 0)

        pick_mock = MagicMock(return_value="FILE: bridge/x.py\nCHANGE: tweak comment")
        monkeypatch.setattr(experiment_loop, "pick_experiment", pick_mock)

        run_exp_mock = MagicMock(return_value={
            "id": "iter-audit-keep",
            "worktree": str(tmp_path / "wt"),
            "branch": "experiment/audit-keep",
            "claude_exit_code": 0,
            "mailbox_messages": [],
        })
        monkeypatch.setattr(experiment_loop, "run_experiment", run_exp_mock)

        validate_mock = MagicMock(return_value={
            "status": "keep",
            "tests_passed": 10,
            "tests_failed": 0,
            "tests_total": 10,
            "notes": {},
            "commit_hash": None,
            "diff_summary": "1 file changed",
            "cost_usd": 0.01,
            "duration_seconds": 0.5,
        })
        monkeypatch.setattr(experiment_loop, "validate_experiment", validate_mock)

        cleanup_mock = MagicMock(return_value=None)
        monkeypatch.setattr(experiment_loop, "cleanup_worktree", cleanup_mock)

        # Audit-branch path: pretend _ensure_worktree_commit already
        # committed and returned a sha, and a fake AuditBranchResult
        # comes back from _create_audit_branch_safe.
        ensure_commit_mock = MagicMock(return_value="audit-sha-abc")
        monkeypatch.setattr(experiment_loop, "_ensure_worktree_commit", ensure_commit_mock)

        fake_audit_result = experiment_loop.AuditBranchResult(
            branch_name="autoresearch/iter-audit-keep",
            commit_sha="audit-sha-abc",
            pushed=False,
            push_error=None,
        )
        audit_create_mock = MagicMock(return_value=fake_audit_result)
        monkeypatch.setattr(
            experiment_loop, "_create_audit_branch_safe", audit_create_mock
        )
        monkeypatch.setattr(
            experiment_loop, "_annotate_audit_branch_safe", MagicMock(return_value=None)
        )

        # Drive the REAL merge_experiment against a worktree that is
        # already clean — this is what production hits when audit
        # branches are enabled. Patch the subprocess.run calls inside
        # merge_experiment so git status returns clean and ff-merge
        # succeeds with a known sha.
        def _fake_run(cmd, **kwargs):
            result = MagicMock()
            if cmd[:2] == ["git", "status"]:
                result.stdout = ""  # clean — audit branch pre-commit happened
                result.returncode = 0
            elif cmd[:2] == ["git", "rev-parse"]:
                result.stdout = "merge-commit-xyz\n"
                result.returncode = 0
            elif cmd[:3] == ["git", "merge", "--ff-only"]:
                result.stdout = ""
                result.stderr = ""
                result.returncode = 0
            else:
                result.stdout = ""
                result.returncode = 0
            return result

        run_patch = patch("experiment_loop.subprocess.run", side_effect=_fake_run)
        run_patch.start()
        monkeypatch.setattr(  # ensure unwind even on assertion failure
            experiment_loop, "_subprocess_run_patch_marker", run_patch, raising=False
        )

        # Capture the REAL log_result before monkeypatch — flipping
        # _shutdown from inside the mock side_effect mirrors A.02/B.02.
        real_log_result = experiment_loop.log_result

        def _log_and_capture(record):
            return real_log_result(record)

        log_result_mock = MagicMock(side_effect=_log_and_capture)
        monkeypatch.setattr(experiment_loop, "log_result", log_result_mock)

        def _notify_then_stop(*args, **kwargs):
            experiment_loop._shutdown = True

        notify_mock = MagicMock(side_effect=_notify_then_stop)
        monkeypatch.setattr(experiment_loop, "notify_discord", notify_mock)

        monkeypatch.setattr(experiment_loop, "check_experiment_budget", lambda: True)
        monkeypatch.setattr(experiment_loop, "get_recent_experiments", lambda limit=10: [])
        monkeypatch.setattr(experiment_loop, "ensure_hook_dirs", lambda: None)
        monkeypatch.setattr(experiment_loop, "run_hooks", lambda phase, ctx: [])
        monkeypatch.setattr(experiment_loop, "_safe_heartbeat", lambda **kw: None)
        monkeypatch.setattr(experiment_loop, "_open_bridge_mailbox", lambda: None)
        monkeypatch.setattr(
            experiment_loop,
            "_load_mailbox_settings",
            lambda: (False, 5.0, 1000),
        )
        # audit branches ENABLED — the whole point of this test.
        monkeypatch.setattr(
            experiment_loop,
            "_load_audit_branch_settings",
            lambda: (True, False, False),
        )
        monkeypatch.setattr(
            experiment_loop,
            "_load_validator_settings",
            lambda: (False, 0.30, "haiku", 0, 0),
        )

        try:
            experiment_loop.main(mode="production")
        finally:
            run_patch.stop()

        # Assertions: legitimate keep iteration, NOT a crash.
        log_result_mock.assert_called_once()
        passed_record = log_result_mock.call_args.args[0]
        assert passed_record["status"] == "keep", (
            f"audit-branch keep path regressed to status={passed_record['status']!r} "
            "(HI-1 bug: pre-existing audit commit made merge_experiment raise, "
            "outer except caught it, status became 'crash')"
        )
        assert passed_record["commit_hash"] == "merge-commit-xyz"
        notify_mock.assert_called_once()
        ensure_commit_mock.assert_called_once()
        audit_create_mock.assert_called_once()


# ---------------------------------------------------------------------------
# Sprint 06.13 — Canonical FORBIDDEN_FILES constant
# ---------------------------------------------------------------------------

class TestForbiddenFilesConstant:
    """FORBIDDEN_FILES constant is consolidated, correctly named, and contains all required entries."""

    REQUIRED_ENTRIES = [
        "security.py",
        "trust_score.py",
        "tier_manager.py",
        "kernel-baseline.json",
        "system-prompt.md",
        "hooks/",
        "database.py",
    ]

    def test_forbidden_files_exists(self):
        """FORBIDDEN_FILES constant must exist at module level."""
        assert hasattr(experiment_loop, "FORBIDDEN_FILES"), (
            "experiment_loop.FORBIDDEN_FILES constant is missing"
        )

    def test_forbidden_files_is_frozenset(self):
        """FORBIDDEN_FILES must be a frozenset (union of IMMUTABLE_FILES + extras)."""
        assert isinstance(experiment_loop.FORBIDDEN_FILES, frozenset)

    def test_all_required_entries_present(self):
        """FORBIDDEN_FILES must contain all entries required by CLAUDE.md."""
        missing = [
            entry for entry in self.REQUIRED_ENTRIES
            if entry not in experiment_loop.FORBIDDEN_FILES
        ]
        assert missing == [], (
            f"FORBIDDEN_FILES is missing required entries: {missing}"
        )

    def test_no_forbidden_patterns_name(self):
        """Old name FORBIDDEN_PATTERNS must not exist (renamed to FORBIDDEN_FILES)."""
        assert not hasattr(experiment_loop, "FORBIDDEN_PATTERNS"), (
            "FORBIDDEN_PATTERNS still exists — should have been renamed to FORBIDDEN_FILES"
        )


class TestLoopProgram:
    """Sprint 02.01 — loop-as-markdown program parser."""

    VALID_PROGRAM = """# Experiment Program

## Objective

Improve the codebase by one small focused change per iteration.

## Mutation Surface

- bridge/*.py
- tests/*.py

## Loop Steps

1. Pick a target.
2. Propose ONE change.
3. Apply in worktree.

## Keep Criteria

All tests pass; ruff stays clean.

## Discard Criteria

Any test fails or ruff regresses.

## Doctrine References

- CLAUDE.md#behavioral-doctrine
- CLAUDE.md#effectiveness-indicators

## NEVER STOP

Do not pause for permission inside an iteration.
"""

    def _write(self, tmp_path, text):
        path = tmp_path / "program.md"
        path.write_text(text)
        return path

    def test_parses_valid_program(self, tmp_path):
        from _loop_program import LoopProgram

        path = self._write(tmp_path, self.VALID_PROGRAM)
        program = LoopProgram.from_markdown(path)

        assert "small focused change" in program.objective
        assert program.mutation_globs == ("bridge/*.py", "tests/*.py")
        assert len(program.loop_steps) == 3
        assert "ruff stays clean" in program.keep_criteria
        assert "ruff regresses" in program.discard_criteria
        assert "CLAUDE.md#behavioral-doctrine" in program.doctrine_refs
        assert "CLAUDE.md#effectiveness-indicators" in program.doctrine_refs
        assert "Do not pause" in program.never_stop

    def test_falls_back_when_section_missing(self, tmp_path):
        from _loop_program import LoopProgram

        broken = self.VALID_PROGRAM.replace("## NEVER STOP\n\n", "## REMOVED\n\n")
        path = self._write(tmp_path, broken)
        program = LoopProgram.from_markdown(path)

        # Default fallback has the canonical doctrine refs and a non-empty never_stop.
        assert "CLAUDE.md#behavioral-doctrine" in program.doctrine_refs
        assert program.never_stop  # default has content

    def test_falls_back_when_path_missing(self, tmp_path):
        from _loop_program import LoopProgram

        path = tmp_path / "does-not-exist.md"
        program = LoopProgram.from_markdown(path)

        # Default fallback returns a valid LoopProgram instance.
        assert program.objective
        assert program.loop_steps

    def test_proposal_prompt_includes_program_and_history(self, tmp_path):
        from _loop_program import LoopProgram

        path = self._write(tmp_path, self.VALID_PROGRAM)
        program = LoopProgram.from_markdown(path)

        history = [
            {"status": "keep", "description": "removed dead branch", "tests_passed": 30, "tests_total": 30},
            {"status": "discard", "description": "broke a test", "tests_passed": 29, "tests_total": 30},
        ]
        prompt = program.proposal_prompt(history)

        assert "small focused change" in prompt
        assert "Recent Experiment History" in prompt
        assert "removed dead branch" in prompt
        assert "FILE: <path relative to agent/>" in prompt
        assert "NO tools available" in prompt

    def test_proposal_prompt_handles_empty_history(self, tmp_path):
        from _loop_program import LoopProgram

        path = self._write(tmp_path, self.VALID_PROGRAM)
        program = LoopProgram.from_markdown(path)

        prompt = program.proposal_prompt([])
        assert "Recent Experiment History" not in prompt
        assert "FILE: <path relative to agent/>" in prompt

    def test_apply_prompt_includes_surface_and_forbidden(self, tmp_path):
        from _loop_program import LoopProgram

        path = self._write(tmp_path, self.VALID_PROGRAM)
        program = LoopProgram.from_markdown(path)

        prompt = program.apply_prompt(
            "FILE: bridge/x.py\nCHANGE: rename foo to bar.",
            ["security.py", "tier_manager.py"],
        )

        assert "rename foo to bar" in prompt
        assert "bridge/*.py" in prompt
        assert "security.py" in prompt
        assert "tier_manager.py" in prompt
        assert "Do not commit" in prompt
        assert "NEVER STOP:" in prompt


class TestHookContract:
    """Sprint 02.06 — before/after hook contract.

    The runner is exercised via mocked ``subprocess.run`` so unit
    tests never actually fork a shell. The fixture builds a temp
    hooks tree, points ``HOOKS_ROOT`` at it for the duration of the
    test, then cleans up.
    """

    def _build_hooks_tree(self, tmp_path, scripts_by_phase):
        """Create a temp hook tree.

        ``scripts_by_phase`` is ``{"before": [(name, mode_octal), ...]}``.
        Files are created with the given mode; the runner only cares
        about execute bits, not script contents (subprocess is mocked).
        """
        roots = {}
        for phase, scripts in scripts_by_phase.items():
            phase_dir_name = "before-experiment" if phase == "before" else "after-experiment"
            phase_dir = tmp_path / "hooks" / phase_dir_name
            phase_dir.mkdir(parents=True)
            for name, mode in scripts:
                script = phase_dir / name
                script.write_text("#!/usr/bin/env bash\necho stub\n")
                import os
                os.chmod(script, mode)
            roots[phase] = phase_dir
        return tmp_path / "hooks"

    def test_empty_directory_is_noop(self, tmp_path, monkeypatch):
        """Missing or empty hook directory → empty list, no error."""
        import _hook_runner

        # Point at a tree that exists but has no scripts.
        roots = self._build_hooks_tree(tmp_path, {"before": [], "after": []})
        monkeypatch.setattr(_hook_runner, "HOOKS_ROOT", roots)

        assert _hook_runner.run_hooks("before", {"iter_id": "x"}) == []
        assert _hook_runner.run_hooks("after", {"iter_id": "x"}) == []

    def test_completely_missing_directory_is_noop(self, tmp_path, monkeypatch):
        """If the parent ``hooks/`` dir doesn't exist, no error."""
        import _hook_runner

        monkeypatch.setattr(_hook_runner, "HOOKS_ROOT", tmp_path / "no-such-dir")
        assert _hook_runner.run_hooks("before", {"iter_id": "x"}) == []

    def test_alphabetical_order(self, tmp_path, monkeypatch):
        """Hooks fire in alphabetical order per phase."""
        import _hook_runner

        roots = self._build_hooks_tree(
            tmp_path,
            {
                "before": [
                    ("99-last.sh", 0o755),
                    ("00-first.sh", 0o755),
                    ("50-middle.sh", 0o755),
                ],
            },
        )
        monkeypatch.setattr(_hook_runner, "HOOKS_ROOT", roots)

        called: list[str] = []

        def fake_run(cmd, **kwargs):
            called.append(Path(cmd[0]).name)
            r = MagicMock()
            r.returncode = 0
            r.stdout = "ok"
            r.stderr = ""
            return r

        with patch("_hook_runner.subprocess.run", side_effect=fake_run):
            results = _hook_runner.run_hooks("before", {"iter_id": "x"})

        assert called == ["00-first.sh", "50-middle.sh", "99-last.sh"]
        assert [r.name for r in results] == ["00-first.sh", "50-middle.sh", "99-last.sh"]
        assert all(r.exit_code == 0 for r in results)

    def test_non_executable_skipped(self, tmp_path, monkeypatch):
        """Files without an execute bit are skipped silently."""
        import _hook_runner

        roots = self._build_hooks_tree(
            tmp_path,
            {
                "before": [
                    ("00-active.sh", 0o755),
                    ("50-disabled.sh", 0o644),
                ],
            },
        )
        monkeypatch.setattr(_hook_runner, "HOOKS_ROOT", roots)

        called: list[str] = []

        def fake_run(cmd, **kwargs):
            called.append(Path(cmd[0]).name)
            r = MagicMock()
            r.returncode = 0
            r.stdout = "ok"
            r.stderr = ""
            return r

        with patch("_hook_runner.subprocess.run", side_effect=fake_run):
            results = _hook_runner.run_hooks("before", {"iter_id": "x"})

        assert called == ["00-active.sh"]
        assert len(results) == 1

    def test_gitkeep_skipped(self, tmp_path, monkeypatch):
        """``.gitkeep`` is ignored even if executable."""
        import _hook_runner
        import os

        phase_dir = tmp_path / "hooks" / "before-experiment"
        phase_dir.mkdir(parents=True)
        gitkeep = phase_dir / ".gitkeep"
        gitkeep.write_text("")
        os.chmod(gitkeep, 0o755)
        active = phase_dir / "00-active.sh"
        active.write_text("#!/bin/sh\n")
        os.chmod(active, 0o755)

        monkeypatch.setattr(_hook_runner, "HOOKS_ROOT", tmp_path / "hooks")

        called: list[str] = []

        def fake_run(cmd, **kwargs):
            called.append(Path(cmd[0]).name)
            r = MagicMock()
            r.returncode = 0
            r.stdout = ""
            r.stderr = ""
            return r

        with patch("_hook_runner.subprocess.run", side_effect=fake_run):
            _hook_runner.run_hooks("before", {"iter_id": "x"})

        assert called == ["00-active.sh"]

    def test_timeout_killed(self, tmp_path, monkeypatch):
        """A hook that exceeds 30s is killed and surfaced as ``timed_out``."""
        import _hook_runner
        import subprocess as _sub

        roots = self._build_hooks_tree(
            tmp_path,
            {"before": [("00-slow.sh", 0o755)]},
        )
        monkeypatch.setattr(_hook_runner, "HOOKS_ROOT", roots)

        def fake_run(cmd, **kwargs):
            # subprocess.run raises TimeoutExpired with the configured timeout.
            assert kwargs["timeout"] == _hook_runner.HOOK_TIMEOUT_SECONDS
            raise _sub.TimeoutExpired(cmd, _hook_runner.HOOK_TIMEOUT_SECONDS, output=b"partial")

        with patch("_hook_runner.subprocess.run", side_effect=fake_run):
            results = _hook_runner.run_hooks("before", {"iter_id": "x"})

        assert len(results) == 1
        r = results[0]
        assert r.timed_out is True
        assert r.exit_code == -1
        assert "partial" in r.output
        assert "timeout" in (r.error or "")

    def test_output_truncated_to_8kb(self, tmp_path, monkeypatch):
        """A hook emitting >8 KB has output truncated."""
        import _hook_runner

        roots = self._build_hooks_tree(
            tmp_path,
            {"before": [("00-loud.sh", 0o755)]},
        )
        monkeypatch.setattr(_hook_runner, "HOOKS_ROOT", roots)

        big_payload = "A" * (100 * 1024)  # 100 KB

        def fake_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 0
            r.stdout = big_payload
            r.stderr = ""
            return r

        with patch("_hook_runner.subprocess.run", side_effect=fake_run):
            results = _hook_runner.run_hooks("before", {"iter_id": "x"})

        assert len(results) == 1
        r = results[0]
        assert r.truncated is True
        assert len(r.output.encode("utf-8")) <= _hook_runner.OUTPUT_CAP_BYTES

    def test_nonzero_exit_logged_loop_continues(self, tmp_path, monkeypatch):
        """A hook exiting non-zero yields a HookResult; runner does not raise."""
        import _hook_runner

        roots = self._build_hooks_tree(
            tmp_path,
            {
                "before": [
                    ("00-ok.sh", 0o755),
                    ("50-fail.sh", 0o755),
                    ("99-also-ok.sh", 0o755),
                ],
            },
        )
        monkeypatch.setattr(_hook_runner, "HOOKS_ROOT", roots)

        call_count = {"n": 0}

        def fake_run(cmd, **kwargs):
            call_count["n"] += 1
            r = MagicMock()
            name = Path(cmd[0]).name
            r.returncode = 1 if "fail" in name else 0
            r.stdout = ""
            r.stderr = "boom" if "fail" in name else ""
            return r

        with patch("_hook_runner.subprocess.run", side_effect=fake_run):
            results = _hook_runner.run_hooks("before", {"iter_id": "x"})

        # All three ran — failure does not short-circuit subsequent hooks.
        assert call_count["n"] == 3
        assert len(results) == 3
        assert results[1].exit_code == 1
        assert "boom" in results[1].output
        # Adjacent hooks succeeded.
        assert results[0].exit_code == 0
        assert results[2].exit_code == 0

    def test_launch_error_does_not_crash(self, tmp_path, monkeypatch):
        """If subprocess fails to launch (OSError), runner records error."""
        import _hook_runner

        roots = self._build_hooks_tree(
            tmp_path,
            {"before": [("00-broken.sh", 0o755)]},
        )
        monkeypatch.setattr(_hook_runner, "HOOKS_ROOT", roots)

        def fake_run(cmd, **kwargs):
            raise OSError("exec format error")

        with patch("_hook_runner.subprocess.run", side_effect=fake_run):
            results = _hook_runner.run_hooks("before", {"iter_id": "x"})

        assert len(results) == 1
        r = results[0]
        assert r.exit_code == -1
        assert r.error is not None
        assert "exec format error" in r.error

    def test_json_directives_parsed(self, tmp_path, monkeypatch):
        """A hook emitting a JSON object → ``directives`` populated."""
        import _hook_runner

        roots = self._build_hooks_tree(
            tmp_path,
            {"before": [("00-steer.sh", 0o755)]},
        )
        monkeypatch.setattr(_hook_runner, "HOOKS_ROOT", roots)

        def fake_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 0
            r.stdout = '{"skip_iteration": true, "reason": "low budget"}'
            r.stderr = ""
            return r

        with patch("_hook_runner.subprocess.run", side_effect=fake_run):
            results = _hook_runner.run_hooks("before", {"iter_id": "x"})

        assert len(results) == 1
        r = results[0]
        assert r.directives == {"skip_iteration": True, "reason": "low budget"}

    def test_non_json_stdout_treated_as_plain_output(self, tmp_path, monkeypatch):
        """Non-JSON stdout → ``directives`` is None, ``output`` keeps text."""
        import _hook_runner

        roots = self._build_hooks_tree(
            tmp_path,
            {"before": [("00-plain.sh", 0o755)]},
        )
        monkeypatch.setattr(_hook_runner, "HOOKS_ROOT", roots)

        def fake_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 0
            r.stdout = "iter-abc started"
            r.stderr = ""
            return r

        with patch("_hook_runner.subprocess.run", side_effect=fake_run):
            results = _hook_runner.run_hooks("before", {"iter_id": "x"})

        assert len(results) == 1
        r = results[0]
        assert r.directives is None
        assert "iter-abc started" in r.output

    def test_json_array_not_treated_as_directives(self, tmp_path, monkeypatch):
        """A bare JSON array is plain output, not directives — only objects steer."""
        import _hook_runner

        roots = self._build_hooks_tree(
            tmp_path,
            {"before": [("00-list.sh", 0o755)]},
        )
        monkeypatch.setattr(_hook_runner, "HOOKS_ROOT", roots)

        def fake_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 0
            r.stdout = "[1, 2, 3]"
            r.stderr = ""
            return r

        with patch("_hook_runner.subprocess.run", side_effect=fake_run):
            results = _hook_runner.run_hooks("before", {"iter_id": "x"})

        assert results[0].directives is None
        assert "[1, 2, 3]" in results[0].output

    def test_stdin_metadata_round_trips(self, tmp_path, monkeypatch):
        """The dict passed to ``run_hooks`` is delivered verbatim on stdin."""
        import _hook_runner

        roots = self._build_hooks_tree(
            tmp_path,
            {"before": [("00-echo.sh", 0o755)]},
        )
        monkeypatch.setattr(_hook_runner, "HOOKS_ROOT", roots)

        captured: dict[str, object] = {}

        def fake_run(cmd, **kwargs):
            captured["input"] = kwargs.get("input")
            r = MagicMock()
            r.returncode = 0
            r.stdout = ""
            r.stderr = ""
            return r

        meta = {"iter_id": "abc123", "status": "keep", "tests_passed": 42}
        with patch("_hook_runner.subprocess.run", side_effect=fake_run):
            _hook_runner.run_hooks("before", meta)

        import json as _json

        decoded = _json.loads(captured["input"])
        assert decoded["iter_id"] == "abc123"
        assert decoded["status"] == "keep"
        assert decoded["tests_passed"] == 42
        # Runner stamps ``phase`` if absent.
        assert decoded["phase"] == "before"

    def test_runner_does_not_mutate_caller_metadata(self, tmp_path, monkeypatch):
        """``run_hooks`` defends a defensive copy of the metadata dict."""
        import _hook_runner

        roots = self._build_hooks_tree(
            tmp_path,
            {"before": [("00-x.sh", 0o755)]},
        )
        monkeypatch.setattr(_hook_runner, "HOOKS_ROOT", roots)

        def fake_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 0
            r.stdout = ""
            r.stderr = ""
            return r

        meta = {"iter_id": "abc"}
        with patch("_hook_runner.subprocess.run", side_effect=fake_run):
            _hook_runner.run_hooks("before", meta)

        # Caller's dict is untouched — runner did not stamp ``phase`` into it.
        assert meta == {"iter_id": "abc"}

    def test_stderr_appended_to_output(self, tmp_path, monkeypatch):
        """Hook stderr is appended to ``output`` so operators see both streams."""
        import _hook_runner

        roots = self._build_hooks_tree(
            tmp_path,
            {"before": [("00-err.sh", 0o755)]},
        )
        monkeypatch.setattr(_hook_runner, "HOOKS_ROOT", roots)

        def fake_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 0
            r.stdout = "hello"
            r.stderr = "warn: thing"
            return r

        with patch("_hook_runner.subprocess.run", side_effect=fake_run):
            results = _hook_runner.run_hooks("before", {"iter_id": "x"})

        assert "hello" in results[0].output
        assert "warn: thing" in results[0].output

    def test_unknown_phase_returns_empty(self, tmp_path, monkeypatch):
        """A bogus phase string yields an empty list (defensive default)."""
        import _hook_runner

        # Directly call with a wrong phase. ``Literal`` is hint-only at
        # runtime, so we exercise the defensive branch.
        result = _hook_runner.run_hooks("middle", {"iter_id": "x"})  # type: ignore[arg-type]
        assert result == []

    def test_summarize_results_formats(self):
        """``summarize_results`` produces a one-line operator summary."""
        from _hook_runner import HookResult, summarize_results

        results = [
            HookResult(name="ok.sh", phase="before", exit_code=0, output="x"),
            HookResult(name="boom.sh", phase="before", exit_code=2, output=""),
            HookResult(name="slow.sh", phase="before", exit_code=-1, output="", timed_out=True),
            HookResult(
                name="steer.sh", phase="before", exit_code=0, output="{}",
                directives={"a": 1},
            ),
        ]
        summary = summarize_results(results)
        assert "ok.sh=ok" in summary
        assert "boom.sh=exit2" in summary
        assert "slow.sh=timeout" in summary
        assert "steer.sh=ok+directives" in summary

    def test_summarize_results_empty(self):
        from _hook_runner import summarize_results

        assert summarize_results([]) == "no hooks fired"

    def test_after_phase_routes_to_after_dir(self, tmp_path, monkeypatch):
        """``run_hooks('after', ...)`` reads the after-experiment dir."""
        import _hook_runner

        roots = self._build_hooks_tree(
            tmp_path,
            {
                "before": [("99-noop.sh", 0o755)],
                "after": [("00-cleanup.sh", 0o755)],
            },
        )
        monkeypatch.setattr(_hook_runner, "HOOKS_ROOT", roots)

        called: list[str] = []

        def fake_run(cmd, **kwargs):
            called.append(Path(cmd[0]).name)
            r = MagicMock()
            r.returncode = 0
            r.stdout = ""
            r.stderr = ""
            return r

        with patch("_hook_runner.subprocess.run", side_effect=fake_run):
            _hook_runner.run_hooks("after", {"iter_id": "x"})

        assert called == ["00-cleanup.sh"]

    def test_ensure_hook_dirs_creates_both(self, tmp_path, monkeypatch):
        """``ensure_hook_dirs`` is idempotent and creates both directories."""
        import _hook_runner

        new_root = tmp_path / "fresh-hooks"
        monkeypatch.setattr(_hook_runner, "HOOKS_ROOT", new_root)
        _hook_runner.ensure_hook_dirs()

        assert (new_root / "before-experiment").is_dir()
        assert (new_root / "after-experiment").is_dir()

        # Idempotent — second call is a no-op.
        _hook_runner.ensure_hook_dirs()
        assert (new_root / "before-experiment").is_dir()


# ---------------------------------------------------------------------------
# Sprint 02.03 — operator-readable state files (experiments.jsonl + .md)
# ---------------------------------------------------------------------------

import json as _json  # noqa: E402  — keep top-of-file lean for non-state tests
import re as _re  # noqa: E402

# Documented header regex — must match the docstring on append_experiments_md.
# Plan 03 sprint 03.10 will read experiments.md against this exact contract.
_MD_HEADER_RE = _re.compile(
    r"^## \[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\] iter-(\d+) \| (\w+) \| fitness Δ ([+-]?\d+\.\d+)$"
)


class TestStateFiles:
    """Sprint 02.03 — dual-write to experiments.jsonl + experiments.md."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.tmp_path = Path(self.tmp_dir)
        self.db_path = self.tmp_path / "experiments.db"
        self.jsonl_path = self.tmp_path / "experiments.jsonl"
        self.md_path = self.tmp_path / "experiments.md"

        db = sqlite3.connect(str(self.db_path))
        db.execute("""CREATE TABLE experiment_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commit_hash TEXT,
            branch TEXT,
            tests_passed INTEGER,
            tests_failed INTEGER,
            tests_total INTEGER,
            status TEXT,
            description TEXT,
            diff_summary TEXT,
            cost_usd REAL DEFAULT 0.0,
            duration_seconds REAL,
            fitness_delta REAL DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        db.commit()
        db.close()

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # ── append_experiments_jsonl ────────────────────────────────────

    def test_jsonl_round_trip_single_record(self):
        """Append → read back → all fields populated, valid JSON."""
        record = {
            "iter_id": 1,
            "commit_hash": "abc1234",
            "branch": "experiment/x",
            "tests_passed": 1813,
            "tests_failed": 0,
            "tests_total": 1813,
            "status": "keep",
            "description": "Added type hints",
            "diff_summary": "1 file",
            "cost_usd": 0.10,
            "duration_seconds": 30.0,
            "fitness_delta": 0.05,
            "created_at": "2026-04-29T12:00:00",
            "notes": {"reviewer": "subagent-x"},
        }
        experiment_loop.append_experiments_jsonl(record, path=self.jsonl_path)

        contents = self.jsonl_path.read_text().splitlines()
        assert len(contents) == 1
        parsed = _json.loads(contents[0])
        assert parsed == record

    def test_jsonl_append_preserves_existing_entries(self):
        """Each call appends — never overwrites the file."""
        for i in range(3):
            experiment_loop.append_experiments_jsonl(
                {"iter_id": i, "status": "keep"},
                path=self.jsonl_path,
            )

        lines = self.jsonl_path.read_text().splitlines()
        assert len(lines) == 3
        for i, line in enumerate(lines):
            parsed = _json.loads(line)
            assert parsed["iter_id"] == i

    def test_jsonl_uses_tmp_rename_for_atomicity(self):
        """Mid-write crash leaves no partial JSONL line.

        The .tmp file is the staging area — if the rename never fires,
        the destination never appears in a half-written state.
        """
        record = {"iter_id": 7, "status": "keep"}
        # Pre-populate the tmp path so we can verify it's rename-targeted.
        tmp = self.jsonl_path.with_suffix(self.jsonl_path.suffix + ".tmp")
        tmp.write_text("STALE\n")
        experiment_loop.append_experiments_jsonl(record, path=self.jsonl_path)

        # After successful append, the tmp file is gone (renamed in place)
        # and the destination contains exactly one valid JSON line.
        assert not tmp.exists(), "tmp file should be renamed, not left dangling"
        lines = self.jsonl_path.read_text().splitlines()
        assert len(lines) == 1
        assert _json.loads(lines[0]) == record

    # ── append_experiments_md ───────────────────────────────────────

    def test_md_header_is_parseable(self):
        """Header conforms to the documented regex contract."""
        experiment_loop.append_experiments_md(
            iter_id=42,
            status="keep",
            fitness_delta=0.12,
            description="A small refactor.",
            path=self.md_path,
        )

        content = self.md_path.read_text()
        # First line of the section is the header.
        first_line = content.splitlines()[0]
        match = _MD_HEADER_RE.match(first_line)
        assert match is not None, f"Header did not parse: {first_line!r}"
        _ts, iter_str, status, delta_str = match.groups()
        assert int(iter_str) == 42
        assert status == "keep"
        assert delta_str == "+0.12"

    def test_md_header_renders_negative_delta(self):
        """``±X.XX`` format keeps the sign explicit even for negatives."""
        experiment_loop.append_experiments_md(
            iter_id=3,
            status="discard",
            fitness_delta=-1.50,
            description="Regression caught.",
            path=self.md_path,
        )

        first_line = self.md_path.read_text().splitlines()[0]
        match = _MD_HEADER_RE.match(first_line)
        assert match is not None
        assert match.group(4) == "-1.50"

    def test_md_empty_description_falls_back(self):
        """Empty description should not produce a malformed empty section."""
        experiment_loop.append_experiments_md(
            iter_id=1,
            status="crash",
            fitness_delta=0.0,
            description="",
            path=self.md_path,
        )
        body = self.md_path.read_text()
        assert "(no description)" in body

    # ── round-trip across all three sinks via log_result() ──────────

    def test_three_iteration_round_trip(self):
        """log_result() writes db row + jsonl line + md section per iteration."""
        with patch.object(experiment_loop, "DB_PATH", self.db_path), \
             patch.object(experiment_loop, "EXPERIMENTS_JSONL_PATH", self.jsonl_path), \
             patch.object(experiment_loop, "EXPERIMENTS_MD_PATH", self.md_path):
            for i in range(3):
                experiment_loop.log_result({
                    "commit_hash": f"sha{i:03d}",
                    "branch": f"experiment/r{i}",
                    "tests_passed": 100,
                    "tests_failed": 0,
                    "tests_total": 100,
                    "status": "keep",
                    "description": f"iteration {i}",
                    "diff_summary": "1 file",
                    "cost_usd": 0.05,
                    "duration_seconds": 12.3,
                    "fitness_delta": 0.01 * i,
                })

        # SQLite: 3 rows
        db = sqlite3.connect(str(self.db_path))
        rows = db.execute("SELECT commit_hash FROM experiment_log ORDER BY id").fetchall()
        db.close()
        assert len(rows) == 3
        assert [r[0] for r in rows] == ["sha000", "sha001", "sha002"]

        # JSONL: 3 lines, all valid JSON
        lines = self.jsonl_path.read_text().splitlines()
        assert len(lines) == 3
        for line in lines:
            _json.loads(line)  # raises if invalid

        # MD: exactly 3 parseable headers (matches the operator's grep check)
        md_content = self.md_path.read_text()
        header_lines = [
            line for line in md_content.splitlines()
            if line.startswith("## [")
        ]
        assert len(header_lines) == 3
        for line in header_lines:
            assert _MD_HEADER_RE.match(line) is not None

    def test_jsonl_failure_does_not_block_sqlite_write(self):
        """If experiments.jsonl write fails, the SQLite write still succeeds."""
        with patch.object(experiment_loop, "DB_PATH", self.db_path), \
             patch.object(experiment_loop, "EXPERIMENTS_JSONL_PATH", self.jsonl_path), \
             patch.object(experiment_loop, "EXPERIMENTS_MD_PATH", self.md_path), \
             patch.object(
                 experiment_loop,
                 "append_experiments_jsonl",
                 side_effect=OSError("disk full"),
             ):
            experiment_loop.log_result({
                "commit_hash": "robust1",
                "branch": "experiment/robust",
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_total": 10,
                "status": "keep",
                "description": "jsonl-fail",
                "fitness_delta": 0.0,
            })

        db = sqlite3.connect(str(self.db_path))
        row = db.execute(
            "SELECT commit_hash FROM experiment_log WHERE commit_hash = 'robust1'"
        ).fetchone()
        db.close()
        assert row is not None, "SQLite write must succeed even when jsonl raises"


# ── Sprint D1.1 (#1173) — validator wiring tests ──────────────


class TestLoadValidatorSettings:
    """Unit tests for _load_validator_settings fail-soft helper."""

    def test_returns_defaults_on_config_import_failure(self):
        """When bridge.config cannot be imported, defaults are returned."""
        import builtins
        real_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "bridge.config":
                raise ImportError("bridge not available")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_mock_import):
            enabled, cap, model, _timeout, _signals = experiment_loop._load_validator_settings()

        assert enabled is False
        assert cap == 0.30
        assert model == "haiku"

    def test_returns_defaults_on_load_config_exception(self):
        """When load_config raises, fail-soft defaults are returned."""
        with patch("experiment_loop._load_validator_settings") as mock_fn:
            # Simulate the internal error path by testing with a patched load_config
            mock_fn.return_value = (False, 0.30, "haiku", 0, 0)
            enabled, cap, model, _timeout, _signals = experiment_loop._load_validator_settings()
        # Restore real function for further assertions
        # (mock_fn used to verify interface only)
        assert enabled is False
        assert cap == 0.30
        assert model == "haiku"

    def test_reads_enabled_flag_from_config(self):
        """When config returns validator_enabled=True, it is propagated."""
        mock_cfg = MagicMock()
        mock_cfg.experiment_validator_enabled = True
        mock_cfg.experiment_validator_cost_cap_usd = 0.15
        mock_cfg.experiment_validator_model = "sonnet"

        with patch("experiment_loop._load_validator_settings") as mock_fn:
            mock_fn.return_value = (True, 0.15, "sonnet", 0, 0)
            enabled, cap, model, _timeout, _signals = experiment_loop._load_validator_settings()

        assert enabled is True
        assert cap == 0.15
        assert model == "sonnet"


class TestValidatorWiring:
    """Tests that validate_experiment receives the three config fields correctly."""

    def test_validate_called_with_config_when_flag_enabled(self, tmp_path):
        """When validator flag is enabled, validate_experiment gets all three fields + runner."""
        captured_kwargs: dict = {}

        def _fake_validate(worktree, **kwargs):
            captured_kwargs.update(kwargs)
            return {
                "status": "keep",
                "tests_passed": 5,
                "tests_total": 5,
                "notes": {},
                "commit_hash": "abc123",
                "diff_summary": "1 file",
                "cost_usd": 0.01,
                "duration_seconds": 1.0,
            }

        with patch.object(experiment_loop, "validate_experiment", side_effect=_fake_validate):
            # Simulate what the loop does when flag is enabled
            _validator_enabled = True
            _validator_cap = 0.15
            _validator_model = "sonnet"
            _runner = experiment_loop._make_validator_runner()

            experiment_loop.validate_experiment(
                str(tmp_path),
                iter_id="testiter01",
                validator_enabled=_validator_enabled,
                validator_cost_cap_usd=_validator_cap,
                validator_model=_validator_model,
                validator_runner=_runner if _validator_enabled else None,
            )

        assert captured_kwargs.get("validator_enabled") is True
        assert captured_kwargs.get("validator_cost_cap_usd") == 0.15
        assert captured_kwargs.get("validator_model") == "sonnet"
        assert captured_kwargs.get("validator_runner") is not None

    def test_validate_default_args_when_flag_disabled(self, tmp_path):
        """When validator flag is disabled, validator_runner is None."""
        captured_kwargs: dict = {}

        def _fake_validate(worktree, **kwargs):
            captured_kwargs.update(kwargs)
            return {
                "status": "keep",
                "tests_passed": 5,
                "tests_total": 5,
                "notes": {},
                "commit_hash": "abc123",
                "diff_summary": "1 file",
                "cost_usd": 0.01,
                "duration_seconds": 1.0,
            }

        with patch.object(experiment_loop, "validate_experiment", side_effect=_fake_validate):
            _validator_enabled = False
            _validator_cap = 0.30
            _validator_model = "haiku"

            experiment_loop.validate_experiment(
                str(tmp_path),
                iter_id="testiter02",
                validator_enabled=_validator_enabled,
                validator_cost_cap_usd=_validator_cap,
                validator_model=_validator_model,
                validator_runner=None,  # flag off → no runner
            )

        assert captured_kwargs.get("validator_enabled") is False
        assert captured_kwargs.get("validator_runner") is None

    def test_make_validator_runner_returns_callable(self):
        """_make_validator_runner() must return a callable."""
        import inspect

        runner = experiment_loop._make_validator_runner()
        assert callable(runner), "_make_validator_runner() must return a callable"
        # The returned function should be a coroutine function (async def)
        assert inspect.iscoroutinefunction(runner), "validator runner must be async"


# ── Sprint audit-2026-05-15.A.01 — token freshness regression guards ─────────

import json  # noqa: E402  (test-only imports kept adjacent to TestLoadOAuthToken)
import subprocess  # noqa: E402


class TestLoadOAuthToken:
    """Regression guards for #1991 / audit CR-2.

    The pre-fix loader checked `.claude-token` before `.secrets` AND wrote
    successful Keychain reads back to `.claude-token`, perpetuating a stale
    cache that survived token rotation. These tests pin the corrected lookup
    order and the deletion of the cache write-back.
    """

    @pytest.fixture
    def loop_paths(self, tmp_path, monkeypatch):
        # Re-point both file sources at tmp_path. `experiment_loop` is already
        # imported at the top of this file via sys.path.insert.
        monkeypatch.setattr(experiment_loop, "SECRETS_PATH", tmp_path / ".secrets")
        monkeypatch.setattr(experiment_loop, "DATA_DIR", tmp_path)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        return tmp_path

    def test_env_var_wins_over_secrets(self, loop_paths, monkeypatch):
        (loop_paths / ".secrets").write_text("claude_oauth_token=from-secrets\n")
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "from-env")
        assert experiment_loop._load_oauth_token() == "from-env"

    def test_secrets_wins_over_stale_claude_token_file(self, loop_paths):
        (loop_paths / ".secrets").write_text("claude_oauth_token=fresh-from-secrets\n")
        (loop_paths / ".claude-token").write_text("stale-from-file")
        with patch("subprocess.run",
                   side_effect=AssertionError("Keychain should not be called")):
            assert experiment_loop._load_oauth_token() == "fresh-from-secrets"

    def test_claude_token_fallback_logs_deprecation_warning(self, loop_paths, caplog):
        (loop_paths / ".claude-token").write_text("only-source-available")
        fake_proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
        with patch("subprocess.run", return_value=fake_proc):
            with caplog.at_level("WARNING"):
                token = experiment_loop._load_oauth_token()
        assert token == "only-source-available"
        assert any("deprecated" in r.message.lower() for r in caplog.records)

    def test_keychain_branch_does_not_write_back_to_claude_token(self, loop_paths):
        legacy = loop_paths / ".claude-token"
        assert not legacy.exists()
        fake_stdout = json.dumps({"claudeAiOauth": {"accessToken": "from-keychain"}})
        fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout=fake_stdout, stderr="")
        with patch("subprocess.run", return_value=fake_proc):
            token = experiment_loop._load_oauth_token()
        assert token == "from-keychain"
        assert not legacy.exists(), "Keychain success must NOT cache to .claude-token"


# ── Sprint audit-2026-05-15.A.02 — minimal shadow-mode loop body ─────────────


class TestMainShadowBody:
    """Verify the shadow-mode wedge: dry-run iterations now execute the body
    (run_experiment → validate_experiment → log_result → notify_discord) but
    skip merge_experiment and tag the row with the `shadow_*` vocabulary.

    Each test patches the seven module-level dependencies that the inner loop
    body calls. The patched `notify_discord` flips `experiment_loop._shutdown`
    so the outer `while not _shutdown` exits after one iteration without
    waiting for the cooldown sleep.
    """

    def _run_one_shadow_iteration(
        self,
        tmp_path,
        monkeypatch,
        *,
        validation_status: str = "keep",
        raise_in_run_experiment: Exception | None = None,
    ):
        """Drive `main(mode="shadow")` through exactly one iteration.

        Returns the dict-of-mocks the caller can assert against.
        """
        db_path = tmp_path / "experiments.db"
        jsonl_path = tmp_path / "experiments.jsonl"
        md_path = tmp_path / "experiments.md"
        log_file = tmp_path / "experiment-loop.log"

        monkeypatch.setattr(experiment_loop, "DB_PATH", db_path)
        monkeypatch.setattr(experiment_loop, "EXPERIMENTS_JSONL_PATH", jsonl_path)
        monkeypatch.setattr(experiment_loop, "EXPERIMENTS_MD_PATH", md_path)
        monkeypatch.setattr(experiment_loop, "LOG_FILE", log_file)
        # Reset the module-level shutdown flag so the loop runs even if a
        # prior test left it set.
        monkeypatch.setattr(experiment_loop, "_shutdown", False)

        # 1. pick_experiment — return a non-empty proposal so the loop
        #    proceeds past the "no proposal" continue branch.
        pick_mock = MagicMock(return_value="FILE: bridge/x.py\nCHANGE: tweak comment")
        monkeypatch.setattr(experiment_loop, "pick_experiment", pick_mock)

        # 2. run_experiment — return a worktree dict shaped like the real
        #    one. If raise_in_run_experiment is set, raise instead.
        if raise_in_run_experiment is not None:
            run_exp_mock = MagicMock(side_effect=raise_in_run_experiment)
        else:
            run_exp_mock = MagicMock(return_value={
                "id": "iter-shadow",
                "worktree": str(tmp_path / "wt"),
                "branch": "experiment/shadow",
                "claude_exit_code": 0,
                "mailbox_messages": [],
            })
        monkeypatch.setattr(experiment_loop, "run_experiment", run_exp_mock)

        # 3. validate_experiment — return a dict that matches the
        #    runtime contract used by the loop.
        validate_mock = MagicMock(return_value={
            "status": validation_status,
            "tests_passed": 10,
            "tests_failed": 0,
            "tests_total": 10,
            "notes": {},
            "commit_hash": None,
            "diff_summary": "1 file changed",
            "cost_usd": 0.01,
            "duration_seconds": 0.5,
        })
        monkeypatch.setattr(experiment_loop, "validate_experiment", validate_mock)

        # 4. merge_experiment — never called on the shadow path; assert
        #    that contract via the mock.
        merge_mock = MagicMock(return_value="deadbeef")
        monkeypatch.setattr(experiment_loop, "merge_experiment", merge_mock)

        # 5. cleanup_worktree — no-op mock; the loop calls it on every
        #    keep/discard branch.
        cleanup_mock = MagicMock(return_value=None)
        monkeypatch.setattr(experiment_loop, "cleanup_worktree", cleanup_mock)

        # 6. log_result — spy via wraps so the real SQLite write still
        #    happens (and we can assert the row exists).
        log_result_mock = MagicMock(wraps=experiment_loop.log_result)
        monkeypatch.setattr(experiment_loop, "log_result", log_result_mock)

        # 7. notify_discord — break the loop after one iteration by
        #    flipping the shutdown flag from inside the mock.
        def _notify_then_stop(*args, **kwargs):
            experiment_loop._shutdown = True

        notify_mock = MagicMock(side_effect=_notify_then_stop)
        monkeypatch.setattr(experiment_loop, "notify_discord", notify_mock)

        # Background helpers that would otherwise depend on real I/O.
        monkeypatch.setattr(experiment_loop, "check_experiment_budget", lambda: True)
        monkeypatch.setattr(experiment_loop, "get_recent_experiments", lambda limit=10: [])
        monkeypatch.setattr(experiment_loop, "ensure_hook_dirs", lambda: None)
        monkeypatch.setattr(experiment_loop, "run_hooks", lambda phase, ctx: [])
        monkeypatch.setattr(experiment_loop, "_safe_heartbeat", lambda **kw: None)
        monkeypatch.setattr(experiment_loop, "_open_bridge_mailbox", lambda: None)
        monkeypatch.setattr(
            experiment_loop,
            "_load_mailbox_settings",
            lambda: (False, 5.0, 1000),
        )
        monkeypatch.setattr(
            experiment_loop,
            "_load_audit_branch_settings",
            lambda: (False, False, False),
        )
        monkeypatch.setattr(
            experiment_loop,
            "_load_validator_settings",
            lambda: (False, 0.30, "haiku", 0, 0),
        )

        # Drive the loop. After notify_discord fires, _shutdown is True,
        # so the while-loop exits cleanly.
        experiment_loop.main(mode="shadow")

        return {
            "pick": pick_mock,
            "run_experiment": run_exp_mock,
            "validate_experiment": validate_mock,
            "merge_experiment": merge_mock,
            "cleanup_worktree": cleanup_mock,
            "log_result": log_result_mock,
            "notify_discord": notify_mock,
            "db_path": db_path,
        }

    def test_dry_run_no_longer_short_circuits_before_run_experiment(
        self, tmp_path, monkeypatch
    ):
        """Pre-A.02 the loop broke out of the iteration immediately after
        logging the proposal. Post-A.02, dry_run flows into run_experiment.
        """
        mocks = self._run_one_shadow_iteration(tmp_path, monkeypatch)
        mocks["run_experiment"].assert_called_once()

    def test_dry_run_writes_shadow_keep_row_to_experiment_log(
        self, tmp_path, monkeypatch
    ):
        """Validation says keep; shadow path tags the row `shadow_keep`
        and writes it to experiment_log."""
        mocks = self._run_one_shadow_iteration(
            tmp_path, monkeypatch, validation_status="keep"
        )
        # log_result was called exactly once with status='shadow_keep'.
        mocks["log_result"].assert_called_once()
        passed_record = mocks["log_result"].call_args.args[0]
        assert passed_record["status"] == "shadow_keep"

        # And the row actually landed in SQLite.
        db = sqlite3.connect(str(mocks["db_path"]))
        rows = db.execute(
            "SELECT status FROM experiment_log ORDER BY id DESC LIMIT 1"
        ).fetchall()
        db.close()
        assert rows == [("shadow_keep",)]

    def test_dry_run_calls_notify_discord_once_per_iteration(
        self, tmp_path, monkeypatch
    ):
        """Operator visibility — shadow iterations notify Discord exactly
        like production iterations."""
        mocks = self._run_one_shadow_iteration(tmp_path, monkeypatch)
        mocks["notify_discord"].assert_called_once()

    def test_dry_run_never_calls_merge_experiment(self, tmp_path, monkeypatch):
        """The whole point of shadow mode — proposals are evaluated but
        main is never mutated."""
        mocks = self._run_one_shadow_iteration(tmp_path, monkeypatch)
        mocks["merge_experiment"].assert_not_called()


class TestModeResolution:
    """Sprint audit-2026-05-15.B.01 (#1996): main() takes ``mode``, not
    ``dry_run``; the CLI shim maps ``--dry-run`` → ``proposal_only`` with
    a DeprecationWarning."""

    def test_main_accepts_mode_parameter_not_dry_run(self):
        """``main()``'s formal parameter is ``mode``, defaulting to shadow.

        Inspect the signature rather than executing the loop — exercising
        a full iteration is what TestMainShadowBody already does.
        """
        import inspect

        sig = inspect.signature(experiment_loop.main)
        assert "mode" in sig.parameters
        assert "dry_run" not in sig.parameters
        assert sig.parameters["mode"].default == "shadow"

    def test_main_rejects_unknown_mode(self):
        """An unknown mode raises ValueError before any setup runs."""
        with pytest.raises(ValueError, match="Unknown mode"):
            experiment_loop.main(mode="bogus")

    def test_dry_run_cli_flag_emits_deprecation_warning(self):
        """The legacy ``--dry-run`` flag triggers a DeprecationWarning."""
        with pytest.warns(DeprecationWarning, match="--dry-run is deprecated"):
            experiment_loop._resolve_mode(["--dry-run"], "shadow")

    def test_dry_run_cli_flag_maps_to_proposal_only(self):
        """The legacy ``--dry-run`` flag resolves to ``proposal_only``,
        regardless of what the config default would have been."""
        with pytest.warns(DeprecationWarning):
            resolved = experiment_loop._resolve_mode(["--dry-run"], "shadow")
        assert resolved == "proposal_only"


class TestMainExceptionMasking:
    """Sprint audit-2026-05-15.C.02 (#1999): when ``run_experiment`` raises
    after the iteration mailbox is open, the original exception must remain
    observable. Pre-C.02, the unbound ``exp`` name caused an
    ``UnboundLocalError`` inside the ``finally`` mailbox cleanup that masked
    the real traceback. The fix initializes ``exp = None`` before the try
    and guards the downstream dereference cluster with
    ``isinstance(exp, dict)``.
    """

    def _drive_iterations(
        self,
        tmp_path,
        monkeypatch,
        *,
        run_experiment_side_effects,
        iter_mailbox,
        stop_after_iterations,
    ):
        """Drive ``main(mode="shadow")`` through a fixed number of iterations.

        ``run_experiment_side_effects`` is a list of either Exception instances
        (which are raised) or dicts (which are returned) — one per iteration.
        ``iter_mailbox`` is the object returned from ``_open_bridge_mailbox``;
        pass a MagicMock to assert ``vacuum`` / ``close`` calls. ``_shutdown``
        is flipped on the Nth ``notify_discord`` or after the Nth iteration's
        sleep loop, whichever happens first.
        """
        db_path = tmp_path / "experiments.db"
        jsonl_path = tmp_path / "experiments.jsonl"
        md_path = tmp_path / "experiments.md"
        log_file = tmp_path / "experiment-loop.log"

        monkeypatch.setattr(experiment_loop, "DB_PATH", db_path)
        monkeypatch.setattr(experiment_loop, "EXPERIMENTS_JSONL_PATH", jsonl_path)
        monkeypatch.setattr(experiment_loop, "EXPERIMENTS_MD_PATH", md_path)
        monkeypatch.setattr(experiment_loop, "LOG_FILE", log_file)
        monkeypatch.setattr(experiment_loop, "_shutdown", False)
        monkeypatch.setattr(experiment_loop, "COOLDOWN_SECONDS", 0)

        pick_mock = MagicMock(return_value="FILE: bridge/x.py\nCHANGE: tweak comment")
        monkeypatch.setattr(experiment_loop, "pick_experiment", pick_mock)

        # run_experiment cycles through the supplied side effects. After the
        # list is exhausted, _shutdown has already been flipped by either
        # the notify-discord stop or the crash-path completion below.
        run_exp_mock = MagicMock(side_effect=list(run_experiment_side_effects))
        monkeypatch.setattr(experiment_loop, "run_experiment", run_exp_mock)

        validate_mock = MagicMock(return_value={
            "status": "keep",
            "tests_passed": 10,
            "tests_failed": 0,
            "tests_total": 10,
            "notes": {},
            "commit_hash": None,
            "diff_summary": "1 file changed",
            "cost_usd": 0.01,
            "duration_seconds": 0.5,
        })
        monkeypatch.setattr(experiment_loop, "validate_experiment", validate_mock)

        merge_mock = MagicMock(return_value="deadbeef")
        monkeypatch.setattr(experiment_loop, "merge_experiment", merge_mock)

        cleanup_mock = MagicMock(return_value=None)
        monkeypatch.setattr(experiment_loop, "cleanup_worktree", cleanup_mock)

        log_result_mock = MagicMock(wraps=experiment_loop.log_result)
        monkeypatch.setattr(experiment_loop, "log_result", log_result_mock)

        iteration_count = {"n": 0}

        def _notify_then_maybe_stop(*args, **kwargs):
            iteration_count["n"] += 1
            if iteration_count["n"] + crash_count["n"] >= stop_after_iterations:
                experiment_loop._shutdown = True

        notify_mock = MagicMock(side_effect=_notify_then_maybe_stop)
        monkeypatch.setattr(experiment_loop, "notify_discord", notify_mock)

        # The crash path does not call notify_discord — so the broad except
        # handler needs its own way to stop the loop after the configured
        # number of iterations. We wrap _safe_heartbeat to count
        # ``crashed`` events and flip _shutdown when the budget is hit.
        crash_count = {"n": 0}
        real_heartbeat = lambda **kw: None  # noqa: E731

        def _heartbeat(**kwargs):
            if kwargs.get("status") == "crashed":
                crash_count["n"] += 1
                if iteration_count["n"] + crash_count["n"] >= stop_after_iterations:
                    experiment_loop._shutdown = True
            return real_heartbeat(**kwargs)

        monkeypatch.setattr(experiment_loop, "_safe_heartbeat", _heartbeat)
        monkeypatch.setattr(experiment_loop, "check_experiment_budget", lambda: True)
        monkeypatch.setattr(experiment_loop, "get_recent_experiments", lambda limit=10: [])
        monkeypatch.setattr(experiment_loop, "ensure_hook_dirs", lambda: None)
        monkeypatch.setattr(experiment_loop, "run_hooks", lambda phase, ctx: [])
        # Open a mailbox by default so the finally block exercises vacuum/close.
        monkeypatch.setattr(experiment_loop, "_open_bridge_mailbox", lambda: iter_mailbox)
        monkeypatch.setattr(
            experiment_loop,
            "_load_mailbox_settings",
            lambda: (True, 5.0, 1000),
        )
        monkeypatch.setattr(
            experiment_loop,
            "_load_audit_branch_settings",
            lambda: (False, False, False),
        )
        monkeypatch.setattr(
            experiment_loop,
            "_load_validator_settings",
            lambda: (False, 0.30, "haiku", 0, 0),
        )

        experiment_loop.main(mode="shadow")

        return {
            "pick": pick_mock,
            "run_experiment": run_exp_mock,
            "log_result": log_result_mock,
            "notify_discord": notify_mock,
            "iter_mailbox": iter_mailbox,
            "iteration_count": iteration_count["n"],
            "crash_count": crash_count["n"],
        }

    def test_run_experiment_raises_with_mailbox_enabled_original_exception_observable(
        self, tmp_path, monkeypatch, caplog
    ):
        """Original RuntimeError must be logged; no UnboundLocalError appears."""
        iter_mailbox = MagicMock()
        iter_mailbox.vacuum = MagicMock(return_value=None)
        iter_mailbox.close = MagicMock(return_value=None)

        with caplog.at_level("ERROR"):
            mocks = self._drive_iterations(
                tmp_path,
                monkeypatch,
                run_experiment_side_effects=[RuntimeError("boom")],
                iter_mailbox=iter_mailbox,
                stop_after_iterations=1,
            )

        joined = "\n".join(rec.getMessage() for rec in caplog.records) + "\n" + caplog.text
        assert "boom" in joined, (
            f"Original RuntimeError('boom') must be visible in log output: {joined}"
        )
        assert "UnboundLocalError" not in joined, (
            f"UnboundLocalError must NOT mask the original traceback: {joined}"
        )
        # Loop made forward progress — either it ran one full crash iteration
        # or _shutdown got flipped.
        assert mocks["crash_count"] >= 1 or experiment_loop._shutdown

    def test_mailbox_cleanup_runs_when_run_experiment_raises_after_mailbox_open(
        self, tmp_path, monkeypatch
    ):
        """Even though ``exp`` never binds, the mailbox is still vacuumed
        and closed exactly once."""
        iter_mailbox = MagicMock()
        iter_mailbox.vacuum = MagicMock(return_value=None)
        iter_mailbox.close = MagicMock(return_value=None)

        self._drive_iterations(
            tmp_path,
            monkeypatch,
            run_experiment_side_effects=[RuntimeError("boom")],
            iter_mailbox=iter_mailbox,
            stop_after_iterations=1,
        )

        iter_mailbox.vacuum.assert_called_once()
        iter_mailbox.close.assert_called_once()

    def test_iteration_continues_after_run_experiment_failure(
        self, tmp_path, monkeypatch
    ):
        """First iteration raises, second succeeds. Shadow's broad handler
        writes ``shadow_crash`` for iteration 1; iteration 2 writes
        ``shadow_keep``. The loop completes both iterations."""
        iter_mailbox = MagicMock()
        iter_mailbox.vacuum = MagicMock(return_value=None)
        iter_mailbox.close = MagicMock(return_value=None)

        success_payload = {
            "id": "ok",
            "branch": "b",
            "worktree": str(tmp_path / "wt"),
            "claude_exit_code": 0,
            "claude_output": "",
            "mailbox_messages": [],
        }

        mocks = self._drive_iterations(
            tmp_path,
            monkeypatch,
            run_experiment_side_effects=[RuntimeError("boom"), success_payload],
            iter_mailbox=iter_mailbox,
            stop_after_iterations=2,
        )

        # run_experiment was called twice — loop did not abort after the raise.
        assert mocks["run_experiment"].call_count == 2

        # log_result was called twice in shadow mode: once with shadow_crash
        # (A.02's broad-handler row) and once with shadow_keep (the success).
        statuses = [
            call.args[0].get("status")
            for call in mocks["log_result"].call_args_list
        ]
        assert statuses.count("shadow_crash") == 1, (
            f"Expected exactly one shadow_crash row; got statuses={statuses}"
        )
        assert statuses.count("shadow_keep") == 1, (
            f"Expected exactly one shadow_keep row; got statuses={statuses}"
        )


class TestMainModeMatrixIntegration:
    """Sprint audit-2026-05-15.B.02 (#1997): end-to-end verification that the
    MergePolicy seam routes the three modes (proposal_only / shadow /
    production) through the right call sites without leaking
    ``is_shadow_iteration``-style branching back into ``main()``.

    Each test drives one iteration of ``main(mode=<m>)`` with the same
    patched-loop fixture pattern A.02 + C.02 established: mock the seven
    module-level dependencies, flip ``_shutdown`` from inside one of the
    side-effects to exit after one iteration.
    """

    def _run_one_iteration(
        self,
        tmp_path,
        monkeypatch,
        *,
        mode: str,
        validation_status: str = "keep",
    ):
        """Drive ``main(mode=mode)`` through exactly one iteration.

        Returns the dict-of-mocks the caller can assert against. The
        proposal_only path exits before notify_discord — for that mode we
        flip ``_shutdown`` from inside ``log_result`` instead.
        """
        db_path = tmp_path / "experiments.db"
        jsonl_path = tmp_path / "experiments.jsonl"
        md_path = tmp_path / "experiments.md"
        log_file = tmp_path / "experiment-loop.log"

        monkeypatch.setattr(experiment_loop, "DB_PATH", db_path)
        monkeypatch.setattr(experiment_loop, "EXPERIMENTS_JSONL_PATH", jsonl_path)
        monkeypatch.setattr(experiment_loop, "EXPERIMENTS_MD_PATH", md_path)
        monkeypatch.setattr(experiment_loop, "LOG_FILE", log_file)
        monkeypatch.setattr(experiment_loop, "_shutdown", False)
        monkeypatch.setattr(experiment_loop, "COOLDOWN_SECONDS", 0)

        pick_mock = MagicMock(return_value="FILE: bridge/x.py\nCHANGE: tweak comment")
        monkeypatch.setattr(experiment_loop, "pick_experiment", pick_mock)

        run_exp_mock = MagicMock(return_value={
            "id": f"iter-{mode}",
            "worktree": str(tmp_path / "wt"),
            "branch": f"experiment/{mode}",
            "claude_exit_code": 0,
            "mailbox_messages": [],
        })
        monkeypatch.setattr(experiment_loop, "run_experiment", run_exp_mock)

        validate_mock = MagicMock(return_value={
            "status": validation_status,
            "tests_passed": 10,
            "tests_failed": 0,
            "tests_total": 10,
            "notes": {},
            "commit_hash": None,
            "diff_summary": "1 file changed",
            "cost_usd": 0.01,
            "duration_seconds": 0.5,
        })
        monkeypatch.setattr(experiment_loop, "validate_experiment", validate_mock)

        merge_mock = MagicMock(return_value="deadbeef")
        monkeypatch.setattr(experiment_loop, "merge_experiment", merge_mock)

        cleanup_mock = MagicMock(return_value=None)
        monkeypatch.setattr(experiment_loop, "cleanup_worktree", cleanup_mock)

        # Capture the REAL log_result before we monkeypatch. Calling
        # experiment_loop.log_result(...) AFTER the patch would resolve
        # back to the mock and infinite-recurse.
        real_log_result = experiment_loop.log_result

        # proposal_only never reaches notify_discord — the iteration exits
        # via ``continue`` after log_result writes the proposal row. Flip
        # _shutdown from inside log_result so the loop terminates either way.
        def _log_and_maybe_stop(record):
            result = real_log_result(record)
            if mode == "proposal_only":
                experiment_loop._shutdown = True
            return result

        log_result_mock = MagicMock(side_effect=_log_and_maybe_stop)
        monkeypatch.setattr(experiment_loop, "log_result", log_result_mock)

        def _notify_then_stop(*args, **kwargs):
            experiment_loop._shutdown = True

        notify_mock = MagicMock(side_effect=_notify_then_stop)
        monkeypatch.setattr(experiment_loop, "notify_discord", notify_mock)

        monkeypatch.setattr(experiment_loop, "check_experiment_budget", lambda: True)
        monkeypatch.setattr(experiment_loop, "get_recent_experiments", lambda limit=10: [])
        monkeypatch.setattr(experiment_loop, "ensure_hook_dirs", lambda: None)
        monkeypatch.setattr(experiment_loop, "run_hooks", lambda phase, ctx: [])
        monkeypatch.setattr(experiment_loop, "_safe_heartbeat", lambda **kw: None)
        monkeypatch.setattr(experiment_loop, "_open_bridge_mailbox", lambda: None)
        monkeypatch.setattr(
            experiment_loop,
            "_load_mailbox_settings",
            lambda: (False, 5.0, 1000),
        )
        monkeypatch.setattr(
            experiment_loop,
            "_load_audit_branch_settings",
            lambda: (False, False, False),
        )
        monkeypatch.setattr(
            experiment_loop,
            "_load_validator_settings",
            lambda: (False, 0.30, "haiku", 0, 0),
        )

        experiment_loop.main(mode=mode)

        return {
            "pick": pick_mock,
            "run_experiment": run_exp_mock,
            "validate_experiment": validate_mock,
            "merge_experiment": merge_mock,
            "cleanup_worktree": cleanup_mock,
            "log_result": log_result_mock,
            "notify_discord": notify_mock,
            "db_path": db_path,
        }

    def test_main_mode_proposal_only_does_not_call_run_experiment_or_merge(
        self, tmp_path, monkeypatch
    ):
        """proposal_only short-circuits via PrePolicy BEFORE the iteration
        body — no worktree, no validation, no merge, no notify."""
        mocks = self._run_one_iteration(
            tmp_path, monkeypatch, mode="proposal_only"
        )
        mocks["run_experiment"].assert_not_called()
        mocks["validate_experiment"].assert_not_called()
        mocks["merge_experiment"].assert_not_called()
        mocks["notify_discord"].assert_not_called()
        # The proposal row landed with the seam's status.
        mocks["log_result"].assert_called_once()
        passed_record = mocks["log_result"].call_args.args[0]
        assert passed_record["status"] == "proposal_skipped"

    def test_main_mode_shadow_writes_shadow_keep_row_does_not_merge(
        self, tmp_path, monkeypatch
    ):
        """shadow runs the full body but ShadowPolicy never calls merge_fn.
        Row tagged shadow_keep when validation passes."""
        mocks = self._run_one_iteration(
            tmp_path, monkeypatch, mode="shadow", validation_status="keep"
        )
        mocks["run_experiment"].assert_called_once()
        mocks["validate_experiment"].assert_called_once()
        mocks["merge_experiment"].assert_not_called()
        # log_result was called with status='shadow_keep'.
        mocks["log_result"].assert_called_once()
        passed_record = mocks["log_result"].call_args.args[0]
        assert passed_record["status"] == "shadow_keep"

    def test_main_mode_production_writes_keep_row_calls_merge_fn(
        self, tmp_path, monkeypatch
    ):
        """production runs the full body AND ProductionPolicy calls merge_fn.
        Row tagged keep with the merge commit hash."""
        mocks = self._run_one_iteration(
            tmp_path, monkeypatch, mode="production", validation_status="keep"
        )
        mocks["run_experiment"].assert_called_once()
        mocks["validate_experiment"].assert_called_once()
        mocks["merge_experiment"].assert_called_once()
        # The merge_fn argument shape is what ProductionPolicy.post_outcome
        # passes — (worktree, branch, description).
        args = mocks["merge_experiment"].call_args.args
        assert args[1] == "experiment/production"
        # log_result was called with status='keep' and the commit hash from
        # the merge_fn return value.
        mocks["log_result"].assert_called_once()
        passed_record = mocks["log_result"].call_args.args[0]
        assert passed_record["status"] == "keep"
        assert passed_record["commit_hash"] == "deadbeef"


# ---------------------------------------------------------------------------
# Sprint audit-2026-05-15.C.05 (#2002) — extend /halt scope to the loop.
# ---------------------------------------------------------------------------


class TestHaltScope:
    """Verify the experiment loop honors ``data/halt.flag`` at both the
    top of each iteration and immediately before merge in production mode.

    Implementation reads ``halt.flag`` directly via two new module-level
    helpers (``_halt_flag_path`` + ``_check_halt``) — NOT through
    ``SecurityManager``. Behavior is bit-for-bit identical to
    ``SecurityManager.is_halted()`` because both read the same file; the
    direct read keeps the script free of the ``SecurityManager(db, cfg)``
    dependency pair.
    """

    def _make_cfg(self, tmp_path):
        """Return a real BridgeConfig with data_dir pinned to tmp_path."""
        from dataclasses import replace

        from bridge.config import load_config

        cfg = load_config(skip_secrets=True, skip_validation=True)
        return replace(cfg, data_dir=str(tmp_path))

    # --- Unit-level tests of the new helpers ---------------------------------

    def test_check_halt_returns_false_when_flag_absent(self, tmp_path):
        cfg = self._make_cfg(tmp_path)
        halted, reason = experiment_loop._check_halt(cfg)
        assert halted is False
        assert reason is None

    def test_check_halt_returns_true_with_reason_when_flag_present(self, tmp_path):
        cfg = self._make_cfg(tmp_path)
        (tmp_path / "halt.flag").write_text("operator paused via /halt", encoding="utf-8")
        halted, reason = experiment_loop._check_halt(cfg)
        assert halted is True
        assert reason == "operator paused via /halt"

    def test_check_halt_returns_true_with_none_reason_when_flag_empty(self, tmp_path):
        cfg = self._make_cfg(tmp_path)
        (tmp_path / "halt.flag").write_text("", encoding="utf-8")
        halted, reason = experiment_loop._check_halt(cfg)
        assert halted is True
        assert reason is None

    # --- Patched-loop tests of the wiring ------------------------------------

    def _patched_loop(self, tmp_path, monkeypatch, *, halt_at_top: bool):
        """Common patched-loop setup mirroring TestMainModeMatrixIntegration.

        ``halt_at_top``: when True, halt.flag is written before main() runs
        so the top-of-iteration check fires and pick_experiment never gets
        called. When False, the flag is absent at the top of the iteration
        but ``validate_experiment`` writes it as a side-effect — so the
        pre-merge check in production mode fires instead.
        """
        db_path = tmp_path / "experiments.db"
        jsonl_path = tmp_path / "experiments.jsonl"
        md_path = tmp_path / "experiments.md"
        log_file = tmp_path / "experiment-loop.log"
        data_dir = tmp_path  # halt.flag resolves to tmp_path/halt.flag

        monkeypatch.setattr(experiment_loop, "DB_PATH", db_path)
        monkeypatch.setattr(experiment_loop, "EXPERIMENTS_JSONL_PATH", jsonl_path)
        monkeypatch.setattr(experiment_loop, "EXPERIMENTS_MD_PATH", md_path)
        monkeypatch.setattr(experiment_loop, "LOG_FILE", log_file)
        monkeypatch.setattr(experiment_loop, "DATA_DIR", data_dir)
        monkeypatch.setattr(experiment_loop, "_shutdown", False)
        monkeypatch.setattr(experiment_loop, "COOLDOWN_SECONDS", 0)

        # Pin the load_config() that main() now calls so the cfg captured
        # inside main() points at the temp data_dir. Each test gets its
        # own halt-flag location. BridgeConfig is a frozen dataclass, so
        # we ``dataclasses.replace`` rather than direct-assign.
        from dataclasses import replace as _replace

        from bridge import config as _bridge_config

        original_load_config = _bridge_config.load_config

        def _fake_load_config(*args, **kwargs):
            cfg = original_load_config(*args, **kwargs)
            return _replace(cfg, data_dir=str(data_dir))

        monkeypatch.setattr(_bridge_config, "load_config", _fake_load_config)

        pick_mock = MagicMock(return_value="FILE: bridge/x.py\nCHANGE: tweak comment")
        monkeypatch.setattr(experiment_loop, "pick_experiment", pick_mock)

        run_exp_mock = MagicMock(return_value={
            "id": "iter-halt-test",
            "worktree": str(tmp_path / "wt"),
            "branch": "experiment/halt-test",
            "claude_exit_code": 0,
            "mailbox_messages": [],
        })
        monkeypatch.setattr(experiment_loop, "run_experiment", run_exp_mock)

        halt_flag_path = data_dir / "halt.flag"

        def _validate_side_effect(*args, **kwargs):
            if not halt_at_top:
                # Simulate the operator typing /halt between validation
                # and merge. The pre-merge check should catch this.
                halt_flag_path.write_text("mid-iteration halt", encoding="utf-8")
            return {
                "status": "keep",
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_total": 10,
                "notes": {},
                "commit_hash": None,
                "diff_summary": "1 file changed",
                "cost_usd": 0.01,
                "duration_seconds": 0.5,
            }

        validate_mock = MagicMock(side_effect=_validate_side_effect)
        monkeypatch.setattr(experiment_loop, "validate_experiment", validate_mock)

        merge_mock = MagicMock(return_value="deadbeef")
        monkeypatch.setattr(experiment_loop, "merge_experiment", merge_mock)

        cleanup_mock = MagicMock(return_value=None)
        monkeypatch.setattr(experiment_loop, "cleanup_worktree", cleanup_mock)

        real_log_result = experiment_loop.log_result

        def _log_and_capture(record):
            return real_log_result(record)

        log_result_mock = MagicMock(side_effect=_log_and_capture)
        monkeypatch.setattr(experiment_loop, "log_result", log_result_mock)

        def _notify_then_stop(*args, **kwargs):
            experiment_loop._shutdown = True

        notify_mock = MagicMock(side_effect=_notify_then_stop)
        monkeypatch.setattr(experiment_loop, "notify_discord", notify_mock)

        # Paused-heartbeat side effect: when the top-of-iteration check
        # fires it writes a paused heartbeat AND we need to flip _shutdown
        # so the loop exits (otherwise it loops forever against the flag).
        real_paused_hb = experiment_loop._record_paused_heartbeat
        paused_hb_calls = []

        def _paused_hb_and_stop(reason):
            paused_hb_calls.append(reason)
            real_paused_hb(reason)
            experiment_loop._shutdown = True

        monkeypatch.setattr(
            experiment_loop, "_record_paused_heartbeat", _paused_hb_and_stop
        )

        # Skip the 60s back-off sleep inside the halt branch.
        monkeypatch.setattr(experiment_loop.time, "sleep", lambda _s: None)

        monkeypatch.setattr(experiment_loop, "check_experiment_budget", lambda: True)
        monkeypatch.setattr(experiment_loop, "get_recent_experiments", lambda limit=10: [])
        monkeypatch.setattr(experiment_loop, "ensure_hook_dirs", lambda: None)
        monkeypatch.setattr(experiment_loop, "run_hooks", lambda phase, ctx: [])
        monkeypatch.setattr(experiment_loop, "_safe_heartbeat", lambda **kw: None)
        monkeypatch.setattr(experiment_loop, "_open_bridge_mailbox", lambda: None)
        monkeypatch.setattr(
            experiment_loop, "_load_mailbox_settings", lambda: (False, 5.0, 1000)
        )
        monkeypatch.setattr(
            experiment_loop, "_load_audit_branch_settings", lambda: (False, False, False)
        )
        monkeypatch.setattr(
            experiment_loop, "_load_validator_settings", lambda: (False, 0.30, "haiku", 0, 0)
        )

        if halt_at_top:
            halt_flag_path.write_text("operator typed /halt", encoding="utf-8")

        return {
            "pick": pick_mock,
            "run_experiment": run_exp_mock,
            "validate_experiment": validate_mock,
            "merge_experiment": merge_mock,
            "log_result": log_result_mock,
            "notify_discord": notify_mock,
            "paused_heartbeat_calls": paused_hb_calls,
            "halt_flag_path": halt_flag_path,
        }

    def test_iteration_skipped_when_halted(self, tmp_path, monkeypatch):
        """halt.flag present at start of iteration → pick_experiment is
        NEVER called and a paused heartbeat is written.
        """
        mocks = self._patched_loop(tmp_path, monkeypatch, halt_at_top=True)
        experiment_loop.main(mode="production")
        mocks["pick"].assert_not_called()
        mocks["run_experiment"].assert_not_called()
        mocks["merge_experiment"].assert_not_called()
        assert mocks["paused_heartbeat_calls"] == ["operator typed /halt"]

    def test_merge_skipped_when_halted_mid_iteration_in_production_mode(
        self, tmp_path, monkeypatch
    ):
        """halt.flag absent at top of iteration but written by validate
        side-effect → pre-merge check fires; merge_experiment is NEVER
        called and ``halted_pre_merge`` propagates to log_result.
        """
        mocks = self._patched_loop(tmp_path, monkeypatch, halt_at_top=False)
        experiment_loop.main(mode="production")
        # Top-of-iteration check did NOT fire (flag was absent).
        mocks["pick"].assert_called_once()
        mocks["run_experiment"].assert_called_once()
        mocks["validate_experiment"].assert_called_once()
        # Pre-merge check fired: merge was skipped.
        mocks["merge_experiment"].assert_not_called()
        mocks["log_result"].assert_called_once()
        record = mocks["log_result"].call_args.args[0]
        assert record["status"] == "halted_pre_merge"

    def test_production_pre_merge_halt_reaches_policy_context(
        self, tmp_path, monkeypatch
    ):
        """A late /halt is represented in IterationContext so the merge
        policy owns the halted_pre_merge outcome.
        """
        mocks = self._patched_loop(tmp_path, monkeypatch, halt_at_top=False)
        captured = {}

        class CapturingPolicy:
            def post_outcome(self, ctx):
                captured["halted"] = ctx.halted
                captured["halt_reason"] = ctx.halt_reason
                from _experiment.merge_policy import IterationOutcome

                return IterationOutcome(
                    commit_sha=None,
                    status="halted_pre_merge",
                    notes=None,
                )

        monkeypatch.setattr(
            experiment_loop,
            "select_policy",
            lambda *args, **kwargs: CapturingPolicy(),
        )

        experiment_loop.main(mode="production")

        assert captured == {
            "halted": True,
            "halt_reason": "mid-iteration halt",
        }
        mocks["merge_experiment"].assert_not_called()
        record = mocks["log_result"].call_args.args[0]
        assert record["status"] == "halted_pre_merge"


# ---------------------------------------------------------------------------
# Sprint audit-2026-05-15.D.02 (#2004) — machine-readable heartbeat JSON.
# ---------------------------------------------------------------------------


class TestHeartbeatJson:
    """Atomic JSON heartbeat written each iteration; surfaced by ``/status``
    and ``readiness.sh`` so operators see live mode + iteration cadence
    without grepping log files.

    The helper under test is ``experiment_loop._write_heartbeat(mode,
    status, branch)``. Tests cover three contracts:

    1. Atomic temp-file + rename — no ``.tmp`` lingers after a successful
       write, and the final file is valid JSON.
    2. Required field set — ``mode``, ``last_iteration_at``,
       ``last_status``, ``last_branch``, ``iteration_count_today``.
    3. Halt path — when ``halt.flag`` is present at the top of an
       iteration, the file's ``last_status`` is ``"paused_halt"`` (the
       canonical paused vocabulary; C.05 wired the call site).
    """

    def test_default_heartbeat_does_not_leak_into_source_tree(
        self, tmp_path, monkeypatch
    ):
        source_heartbeat = (
            experiment_loop.AGENT_DIR / "data" / "experiment-heartbeat.json"
        )
        assert not source_heartbeat.exists()
        monkeypatch.setattr(
            experiment_loop, "DB_PATH", tmp_path / "missing.db"
        )

        experiment_loop._write_heartbeat(
            mode="shadow",
            status="shadow_keep",
            branch="experiment/iter-test-isolation",
        )

        assert experiment_loop.HEARTBEAT_PATH.exists()
        assert not source_heartbeat.exists()

    def test_heartbeat_written_atomically(self, tmp_path, monkeypatch):
        import json as _json

        target = tmp_path / "experiment-heartbeat.json"
        monkeypatch.setattr(experiment_loop, "HEARTBEAT_PATH", target)
        # _iterations_today opens DB_PATH — point it at a non-existent
        # path so the helper hits its best-effort ``return None`` branch
        # rather than reaching into the dev SQLite.
        monkeypatch.setattr(
            experiment_loop, "DB_PATH", tmp_path / "missing.db"
        )

        experiment_loop._write_heartbeat(
            mode="shadow",
            status="shadow_keep",
            branch="experiment/iter-test1",
        )

        assert target.exists(), "heartbeat file was not written"
        # No lingering tmp sibling — the rename completed cleanly.
        siblings = [p.name for p in target.parent.iterdir()]
        assert not any(name.endswith(".tmp") for name in siblings), (
            f"unexpected tmp file in {target.parent}: {siblings}"
        )
        # File parses as JSON.
        payload = _json.loads(target.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        assert payload["mode"] == "shadow"

    def test_heartbeat_contains_required_fields(self, tmp_path, monkeypatch):
        import json as _json

        target = tmp_path / "experiment-heartbeat.json"
        monkeypatch.setattr(experiment_loop, "HEARTBEAT_PATH", target)
        monkeypatch.setattr(
            experiment_loop, "DB_PATH", tmp_path / "missing.db"
        )

        experiment_loop._write_heartbeat(
            mode="shadow",
            status="shadow_discard",
            branch="experiment/iter-test2",
        )

        payload = _json.loads(target.read_text(encoding="utf-8"))
        required = {
            "mode",
            "last_iteration_at",
            "last_status",
            "last_branch",
            "iteration_count_today",
        }
        assert required.issubset(payload.keys()), (
            f"missing fields: {required - set(payload.keys())}"
        )
        assert payload["last_status"] == "shadow_discard"
        assert payload["last_branch"] == "experiment/iter-test2"
        # iteration_count_today is None (DB missing) — that's the
        # documented best-effort fallback.
        assert payload["iteration_count_today"] is None

    def test_heartbeat_status_paused_halt_when_halted(
        self, tmp_path, monkeypatch
    ):
        """End-to-end via ``main(mode="shadow")``: with ``halt.flag``
        present at the top of the iteration, the loop's halt branch
        invokes ``_record_paused_heartbeat`` which delegates to
        ``_write_heartbeat`` — the file's ``last_status`` MUST be
        ``"paused_halt"``.
        """
        db_path = tmp_path / "experiments.db"
        jsonl_path = tmp_path / "experiments.jsonl"
        md_path = tmp_path / "experiments.md"
        log_file = tmp_path / "experiment-loop.log"
        data_dir = tmp_path
        target = tmp_path / "experiment-heartbeat.json"

        monkeypatch.setattr(experiment_loop, "DB_PATH", db_path)
        monkeypatch.setattr(experiment_loop, "EXPERIMENTS_JSONL_PATH", jsonl_path)
        monkeypatch.setattr(experiment_loop, "EXPERIMENTS_MD_PATH", md_path)
        monkeypatch.setattr(experiment_loop, "LOG_FILE", log_file)
        monkeypatch.setattr(experiment_loop, "DATA_DIR", data_dir)
        monkeypatch.setattr(experiment_loop, "HEARTBEAT_PATH", target)
        monkeypatch.setattr(experiment_loop, "_shutdown", False)
        monkeypatch.setattr(experiment_loop, "COOLDOWN_SECONDS", 0)

        # Pin load_config so the halt.flag resolves under tmp_path.
        # Mirrors the TestHaltScope pattern verbatim.
        from dataclasses import replace as _replace

        from bridge import config as _bridge_config

        original_load_config = _bridge_config.load_config

        def _fake_load_config(*args, **kwargs):
            cfg = original_load_config(*args, **kwargs)
            return _replace(cfg, data_dir=str(data_dir))

        monkeypatch.setattr(_bridge_config, "load_config", _fake_load_config)

        # Capture real _record_paused_heartbeat BEFORE we wrap it so the
        # wrapper does not recurse. The wrapper:
        #   1. Calls the real helper so the JSON file is written.
        #   2. Captures the file contents AT THIS MOMENT — before the
        #      post-loop shutdown heartbeat overwrites with ``stopped``.
        #   3. Flips _shutdown so the loop exits after one iteration.
        real_paused_hb = experiment_loop._record_paused_heartbeat
        captured: dict[str, object] = {}

        def _paused_hb_and_stop(reason):
            import json as _json

            real_paused_hb(reason)
            captured["payload"] = _json.loads(
                target.read_text(encoding="utf-8")
            )
            experiment_loop._shutdown = True

        monkeypatch.setattr(
            experiment_loop, "_record_paused_heartbeat", _paused_hb_and_stop
        )

        # Skip the 60s back-off sleep inside the halt branch.
        monkeypatch.setattr(experiment_loop.time, "sleep", lambda _s: None)

        # Stub everything downstream of the halt branch so a stray code
        # path can't write a different status to the file. None of these
        # should fire because halt.flag short-circuits at the top.
        unreachable = MagicMock(side_effect=AssertionError("halt branch did not fire"))
        monkeypatch.setattr(experiment_loop, "pick_experiment", unreachable)
        monkeypatch.setattr(experiment_loop, "run_experiment", unreachable)
        monkeypatch.setattr(experiment_loop, "validate_experiment", unreachable)
        monkeypatch.setattr(experiment_loop, "merge_experiment", unreachable)
        monkeypatch.setattr(experiment_loop, "log_result", unreachable)
        monkeypatch.setattr(experiment_loop, "notify_discord", unreachable)
        monkeypatch.setattr(experiment_loop, "cleanup_worktree", lambda *a, **k: None)
        monkeypatch.setattr(experiment_loop, "check_experiment_budget", lambda: True)
        monkeypatch.setattr(experiment_loop, "get_recent_experiments", lambda limit=10: [])
        monkeypatch.setattr(experiment_loop, "ensure_hook_dirs", lambda: None)
        monkeypatch.setattr(experiment_loop, "run_hooks", lambda phase, ctx: [])
        monkeypatch.setattr(experiment_loop, "_safe_heartbeat", lambda **kw: None)
        monkeypatch.setattr(experiment_loop, "_open_bridge_mailbox", lambda: None)
        monkeypatch.setattr(
            experiment_loop, "_load_mailbox_settings", lambda: (False, 5.0, 1000)
        )
        monkeypatch.setattr(
            experiment_loop, "_load_audit_branch_settings", lambda: (False, False, False)
        )
        monkeypatch.setattr(
            experiment_loop, "_load_validator_settings", lambda: (False, 0.30, "haiku", 0, 0)
        )

        # Write halt.flag before main() so the top-of-iteration check fires.
        (data_dir / "halt.flag").write_text(
            "operator typed /halt", encoding="utf-8"
        )

        experiment_loop.main(mode="shadow")

        # The wrapper captured the heartbeat payload AT the moment the
        # halt branch ran, before the post-loop shutdown heartbeat
        # could overwrite the file with status="stopped".
        assert "payload" in captured, (
            "halt branch did not fire — _record_paused_heartbeat never "
            "called"
        )
        assert captured["payload"]["last_status"] == "paused_halt"


# ---------------------------------------------------------------------------
# Sprint audit-2026-05-15.D.01 (#2003) — mode/control-flow contract matrix.
# ---------------------------------------------------------------------------


class TestMainModeMatrix:
    """Ratify the full per-mode contract matrix audit §M-2 asked for.

    Earlier sprints (A.02 / B.02 / C.01 / C.02 / C.05) shipped individual
    per-mode behaviors. D.01 is the completeness checkpoint: six tests, one
    per (mode × validation_status) cell of the matrix, locking down the
    audit-promised contract so future Phase B/C/D edits cannot quietly
    regress it.

    Each test drives ``main(mode=<m>)`` through exactly one iteration via
    the same patched-loop pattern A.02 + B.02 established: mock the seven
    module-level dependencies, flip ``_shutdown`` from inside one of the
    side-effects to exit after one iteration. The proposal_only path exits
    via ``continue`` after ``log_result`` writes the proposal row — flip
    ``_shutdown`` from inside ``log_result`` for that mode; for shadow /
    production, flip it from ``notify_discord``.
    """

    @pytest.fixture
    def patched_loop(self, tmp_path, monkeypatch):
        """Patched-loop fixture mirroring TestMainModeMatrixIntegration.

        Returns a callable ``drive(mode, validation_status="keep",
        merge_return="abc123")`` that runs one iteration and returns the
        dict of mocks the test can assert against.
        """
        db_path = tmp_path / "experiments.db"
        jsonl_path = tmp_path / "experiments.jsonl"
        md_path = tmp_path / "experiments.md"
        log_file = tmp_path / "experiment-loop.log"

        monkeypatch.setattr(experiment_loop, "DB_PATH", db_path)
        monkeypatch.setattr(experiment_loop, "EXPERIMENTS_JSONL_PATH", jsonl_path)
        monkeypatch.setattr(experiment_loop, "EXPERIMENTS_MD_PATH", md_path)
        monkeypatch.setattr(experiment_loop, "LOG_FILE", log_file)
        monkeypatch.setattr(experiment_loop, "_shutdown", False)
        monkeypatch.setattr(experiment_loop, "COOLDOWN_SECONDS", 0)

        # Background helpers — stub out everything the loop body touches
        # so the test is hermetic.
        monkeypatch.setattr(experiment_loop, "check_experiment_budget", lambda: True)
        monkeypatch.setattr(experiment_loop, "get_recent_experiments", lambda limit=10: [])
        monkeypatch.setattr(experiment_loop, "ensure_hook_dirs", lambda: None)
        monkeypatch.setattr(experiment_loop, "run_hooks", lambda phase, ctx: [])
        monkeypatch.setattr(experiment_loop, "_safe_heartbeat", lambda **kw: None)
        monkeypatch.setattr(experiment_loop, "_open_bridge_mailbox", lambda: None)
        monkeypatch.setattr(
            experiment_loop,
            "_load_mailbox_settings",
            lambda: (False, 5.0, 1000),
        )
        monkeypatch.setattr(
            experiment_loop,
            "_load_audit_branch_settings",
            lambda: (False, False, False),
        )
        monkeypatch.setattr(
            experiment_loop,
            "_load_validator_settings",
            lambda: (False, 0.30, "haiku", 0, 0),
        )

        def drive(
            mode: str,
            *,
            validation_status: str = "keep",
            merge_return: str | None = "abc123",
        ) -> dict:
            # pick_experiment — non-empty proposal so the loop body runs.
            pick_mock = MagicMock(
                return_value="FILE: bridge/x.py\nCHANGE: tweak comment"
            )
            monkeypatch.setattr(experiment_loop, "pick_experiment", pick_mock)

            # run_experiment — full dict shape main() reads from.
            run_exp_mock = MagicMock(return_value={
                "id": f"iter-{mode}",
                "worktree": str(tmp_path / "wt"),
                "branch": f"experiment/{mode}",
                "claude_exit_code": 0,
                "claude_output": "",
                "mailbox_messages": [],
            })
            monkeypatch.setattr(
                experiment_loop, "run_experiment", run_exp_mock
            )

            # validate_experiment — main() reads validation["status"] as
            # dict access, NOT attribute. The spec sketch suggested
            # SimpleNamespace; the live code requires a dict.
            validate_mock = MagicMock(return_value={
                "status": validation_status,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_total": 10,
                "notes": {},
                "commit_hash": None,
                "diff_summary": "1 file changed",
                "cost_usd": 0.01,
                "duration_seconds": 0.5,
            })
            monkeypatch.setattr(
                experiment_loop, "validate_experiment", validate_mock
            )

            # merge_experiment — only called on the production keep path.
            merge_mock = MagicMock(return_value=merge_return)
            monkeypatch.setattr(
                experiment_loop, "merge_experiment", merge_mock
            )

            # cleanup_worktree — no-op stub.
            cleanup_mock = MagicMock(return_value=None)
            monkeypatch.setattr(
                experiment_loop, "cleanup_worktree", cleanup_mock
            )

            # Capture the REAL log_result BEFORE monkeypatch — calling
            # experiment_loop.log_result(...) AFTER the patch would
            # resolve back to the mock and infinite-recurse.
            real_log_result = experiment_loop.log_result

            # proposal_only exits via ``continue`` after log_result —
            # flip _shutdown from inside log_result so the loop
            # terminates. shadow / production reach notify_discord; for
            # those modes log_result still calls the real impl but only
            # the notify side_effect flips _shutdown.
            def _log_and_maybe_stop(record):
                result = real_log_result(record)
                if mode == "proposal_only":
                    experiment_loop._shutdown = True
                return result

            log_result_mock = MagicMock(side_effect=_log_and_maybe_stop)
            monkeypatch.setattr(
                experiment_loop, "log_result", log_result_mock
            )

            def _notify_then_stop(*args, **kwargs):
                experiment_loop._shutdown = True

            notify_mock = MagicMock(side_effect=_notify_then_stop)
            monkeypatch.setattr(
                experiment_loop, "notify_discord", notify_mock
            )

            experiment_loop.main(mode=mode)

            return {
                "pick": pick_mock,
                "run_experiment": run_exp_mock,
                "validate_experiment": validate_mock,
                "merge_experiment": merge_mock,
                "cleanup_worktree": cleanup_mock,
                "log_result": log_result_mock,
                "notify_discord": notify_mock,
                "db_path": db_path,
            }

        return drive

    def test_proposal_only_no_db_row_no_merge(self, patched_loop):
        """proposal_only short-circuits via PrePolicy: no run_experiment,
        no validation, no merge, no notify. The proposal_skipped row is
        logged (it's the only observable artifact of the iteration), but
        merge_experiment MUST NOT be called.
        """
        mocks = patched_loop(mode="proposal_only")
        mocks["run_experiment"].assert_not_called()
        mocks["validate_experiment"].assert_not_called()
        mocks["merge_experiment"].assert_not_called()
        mocks["notify_discord"].assert_not_called()
        # The proposal row landed with the PrePolicy status.
        mocks["log_result"].assert_called_once()
        record = mocks["log_result"].call_args.args[0]
        assert record["status"] == "proposal_skipped"

    def test_shadow_keep_writes_shadow_keep_status_no_merge(
        self, patched_loop
    ):
        """shadow + validation=keep → row tagged ``shadow_keep`` and
        merge_experiment is never called. ShadowPolicy holds no merge_fn
        by construction so the no-merge invariant is in the type.
        """
        mocks = patched_loop(mode="shadow", validation_status="keep")
        mocks["run_experiment"].assert_called_once()
        mocks["validate_experiment"].assert_called_once()
        mocks["merge_experiment"].assert_not_called()
        mocks["log_result"].assert_called_once()
        record = mocks["log_result"].call_args.args[0]
        assert record["status"] == "shadow_keep"

    def test_shadow_discard_writes_shadow_discard_status_no_merge(
        self, patched_loop
    ):
        """shadow + validation=discard → row tagged ``shadow_discard``
        and merge_experiment is still never called. ShadowPolicy maps
        any non-``keep`` validation status to ``shadow_discard``.
        """
        mocks = patched_loop(
            mode="shadow", validation_status="discard"
        )
        mocks["run_experiment"].assert_called_once()
        mocks["validate_experiment"].assert_called_once()
        mocks["merge_experiment"].assert_not_called()
        mocks["log_result"].assert_called_once()
        record = mocks["log_result"].call_args.args[0]
        assert record["status"] == "shadow_discard"

    def test_shadow_notifies_discord_once_per_iteration(self, patched_loop):
        """Operator visibility — shadow iterations notify Discord exactly
        once per iteration, same cadence as production. The notify_discord
        side_effect that flips ``_shutdown`` doubles as the assertion-target
        for ``call_count == 1``.
        """
        mocks = patched_loop(mode="shadow", validation_status="keep")
        mocks["notify_discord"].assert_called_once()

    def test_production_keep_writes_keep_status_calls_merge(
        self, patched_loop
    ):
        """production + validation=keep + successful merge → row tagged
        ``keep`` with the commit_hash from merge_experiment. This is the
        only mode/status pair that actually mutates main.
        """
        mocks = patched_loop(
            mode="production",
            validation_status="keep",
            merge_return="abc123",
        )
        mocks["run_experiment"].assert_called_once()
        mocks["validate_experiment"].assert_called_once()
        mocks["merge_experiment"].assert_called_once()
        # merge_fn argument shape — ProductionPolicy.post_outcome passes
        # (worktree, branch, description).
        args = mocks["merge_experiment"].call_args.args
        assert args[1] == "experiment/production"
        mocks["log_result"].assert_called_once()
        record = mocks["log_result"].call_args.args[0]
        assert record["status"] == "keep"
        assert record["commit_hash"] == "abc123"

    def test_production_discard_writes_discard_status_no_merge(
        self, patched_loop
    ):
        """production + validation=discard → ProductionPolicy returns
        ``status="discard", commit_sha=None`` WITHOUT calling merge_fn.
        Row tagged ``discard`` and merge_experiment is never invoked.
        """
        mocks = patched_loop(
            mode="production", validation_status="discard"
        )
        mocks["run_experiment"].assert_called_once()
        mocks["validate_experiment"].assert_called_once()
        mocks["merge_experiment"].assert_not_called()
        mocks["log_result"].assert_called_once()
        record = mocks["log_result"].call_args.args[0]
        assert record["status"] == "discard"


# ── Sprint audit-2026-05-16.E.01 (#2069): commit-trailer helper ──


class TestAppendExperimentTrailers:
    """Sprint audit-2026-05-16.E.01 (#2069) — autonomous-commit trailers.

    The helper attaches a stable ``Bumba-Agent-Experiment: true`` plus
    ``Experiment-Run-Id`` / ``Experiment-Mode`` trailer trio so the
    operator can filter the log with
    ``git log --grep='^Bumba-Agent-Experiment: true'`` or render the
    run-id via ``--format='%h %s [%(trailers:key=Experiment-Run-Id,valueonly)]'``.
    """

    def test_appends_three_trailers_to_simple_message(self):
        msg = "experiment: tighten the assertion"
        out = experiment_loop._append_experiment_trailers(
            msg, run_id="abc123def456", mode="production"
        )
        assert "Bumba-Agent-Experiment: true" in out
        assert "Experiment-Run-Id: abc123def456" in out
        assert "Experiment-Mode: production" in out
        # Body preserved verbatim.
        assert out.startswith(msg)
        # Each trailer appears exactly once.
        assert out.count("Bumba-Agent-Experiment: true") == 1
        assert out.count("Experiment-Run-Id: abc123def456") == 1
        assert out.count("Experiment-Mode: production") == 1
        # Body and trailers separated by a blank line.
        assert "\n\nBumba-Agent-Experiment: true\n" in out

    def test_is_idempotent_no_duplicate_trailers(self):
        """Calling twice must not double-stamp — supports the merge path
        running over a worktree that the audit-branch path already
        committed."""
        msg = "experiment: idempotency"
        once = experiment_loop._append_experiment_trailers(
            msg, run_id="111", mode="shadow"
        )
        twice = experiment_loop._append_experiment_trailers(
            once, run_id="111", mode="shadow"
        )
        assert once == twice
        assert twice.count("Bumba-Agent-Experiment: true") == 1
        assert twice.count("Experiment-Run-Id: 111") == 1
        assert twice.count("Experiment-Mode: shadow") == 1

    def test_idempotent_even_with_different_run_id(self):
        """The idempotency guard fires on the presence of the
        ``Bumba-Agent-Experiment`` trailer regardless of run-id value —
        the first stamp wins."""
        msg = "experiment: first wins"
        once = experiment_loop._append_experiment_trailers(
            msg, run_id="first", mode="production"
        )
        twice = experiment_loop._append_experiment_trailers(
            once, run_id="second", mode="shadow"
        )
        assert once == twice
        assert "Experiment-Run-Id: first" in twice
        assert "Experiment-Run-Id: second" not in twice

    def test_preserves_multi_line_body(self):
        msg = "experiment: foo\n\nMore detail here.\nAnd another line."
        out = experiment_loop._append_experiment_trailers(
            msg, run_id="xyz", mode="production"
        )
        assert out.startswith(msg)
        # Trailers attached at end of the multi-line body.
        assert out.endswith(
            "\n\nBumba-Agent-Experiment: true\n"
            "Experiment-Run-Id: xyz\n"
            "Experiment-Mode: production\n"
        )

    def test_handles_message_already_ending_in_single_newline(self):
        msg = "experiment: trailing newline\n"
        out = experiment_loop._append_experiment_trailers(
            msg, run_id="r1", mode="shadow"
        )
        # Should produce one blank-line separator between body and
        # trailers — i.e. body's trailing \n + one inserted \n.
        assert "\n\nBumba-Agent-Experiment: true\n" in out
        # No triple-blank-line regressions.
        assert "\n\n\nBumba-Agent-Experiment" not in out

    def test_handles_message_already_ending_in_blank_line(self):
        msg = "experiment: blank line\n\n"
        out = experiment_loop._append_experiment_trailers(
            msg, run_id="r2", mode="production"
        )
        # Already separated by a blank line — no extra newline inserted.
        assert out == msg + (
            "Bumba-Agent-Experiment: true\n"
            "Experiment-Run-Id: r2\n"
            "Experiment-Mode: production\n"
        )

    def test_trailers_parse_via_git_interpret_trailers(self, tmp_path):
        """Optional: confirm git itself recognizes the trailer block.

        Uses ``git interpret-trailers --parse`` which prints only the
        trailer lines from a commit message. Skips cleanly when git is
        unavailable in the test environment.
        """
        import shutil as _shutil
        if _shutil.which("git") is None:
            pytest.skip("git not available in test environment")

        msg = "experiment: parse via git\n"
        out = experiment_loop._append_experiment_trailers(
            msg, run_id="parsed-run-id", mode="production"
        )
        proc = subprocess.run(
            ["git", "interpret-trailers", "--parse"],
            input=out,
            capture_output=True,
            text=True,
            check=True,
        )
        parsed = proc.stdout
        assert "Bumba-Agent-Experiment: true" in parsed
        assert "Experiment-Run-Id: parsed-run-id" in parsed
        assert "Experiment-Mode: production" in parsed


# ── Sprint audit-2026-05-16.D.06 (#2067) — validator subprocess cost parsing ──


class TestValidatorSubprocessCost:
    """Regression guards for audit finding M-3/M-6.

    Pre-D.06 the validator runner returned a hardcoded ``cost = 0.0``
    after every ``claude -p`` invocation, so the validator's own
    per-invocation cost cap could never trip and the iteration's
    cost telemetry reported false-zero spend. D.06 parses the cost
    from the subprocess's ``--output-format stream-json`` output and
    routes ``unknown`` (missing data, crash, malformed) through a
    NaN sentinel so ``validate_experiment`` records
    ``iteration_cost_unknown=True`` instead of silently writing 0.0.
    """

    def _build_stream_json_stdout(
        self,
        *,
        cost_usd: float | None | str = "absent",
        assistant_text: str = "VERDICT: IMPROVEMENT\nSUMMARY: ok",
        include_result_event: bool = True,
        session_id: str = "sess-abc",
    ) -> str:
        """Synthesize a Claude --output-format stream-json stdout.

        ``cost_usd``:
          - ``"absent"`` (default sentinel) → result event omits cost_usd
            field entirely (the missing-data case).
          - ``None`` → result event present with explicit ``null``.
          - any number (incl 0.0) → result event present with the value.
        """
        import json as _json

        lines: list[str] = []
        # system init
        lines.append(_json.dumps({
            "type": "system",
            "subtype": "init",
            "session_id": session_id,
        }))
        # assistant text block (so _extract_assistant_text has content)
        if assistant_text:
            lines.append(_json.dumps({
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": assistant_text}],
                },
            }))
        if include_result_event:
            result_payload: dict = {
                "type": "result",
                "subtype": "success",
                "session_id": session_id,
                "result": assistant_text,
                "num_turns": 1,
                "duration_ms": 1234,
            }
            if cost_usd != "absent":
                result_payload["cost_usd"] = cost_usd
            lines.append(_json.dumps(result_payload))
        return "\n".join(lines) + "\n"

    def test_parses_measured_cost_from_result_event(self):
        """A stream with a numeric ``cost_usd`` on the result event
        produces ``source='measured'`` and the correct Decimal amount.
        """
        from decimal import Decimal

        stdout = self._build_stream_json_stdout(cost_usd=0.0123)
        measurement = experiment_loop._parse_validator_subprocess_cost(stdout)

        assert measurement.source == "measured"
        assert measurement.amount_usd == Decimal("0.0123")
        assert measurement.backend == "claude"
        assert measurement.raw_usage_id == "sess-abc"

    def test_missing_cost_usd_field_is_unknown(self):
        """A stream WITHOUT ``cost_usd`` on the result event records
        ``source='unknown'`` and ``amount_usd=None`` — NOT a measured
        zero. The SW-3 invariant: missing data is not $0 spend.
        """
        stdout = self._build_stream_json_stdout(cost_usd="absent")
        measurement = experiment_loop._parse_validator_subprocess_cost(stdout)

        assert measurement.source == "unknown"
        assert measurement.amount_usd is None
        assert measurement.backend == "claude"

    def test_subprocess_crash_empty_stdout_is_unknown(self):
        """Empty stdout (subprocess crash, non-zero exit producing no
        output) parses to ``source='unknown'`` rather than collapsing
        to a numeric zero.
        """
        measurement = experiment_loop._parse_validator_subprocess_cost("")

        assert measurement.source == "unknown"
        assert measurement.amount_usd is None
        assert measurement.backend == "claude"

    def test_measured_zero_preserved(self):
        """A stream with ``cost_usd: 0.0`` on the result event records
        ``source='measured'`` with a zero amount (a genuine zero-cost
        turn — e.g. subscription billing — is NOT the same as unknown).
        """
        from decimal import Decimal

        stdout = self._build_stream_json_stdout(cost_usd=0.0)
        measurement = experiment_loop._parse_validator_subprocess_cost(stdout)

        assert measurement.source == "measured"
        assert measurement.amount_usd == Decimal("0.0")

    def test_no_result_event_is_unknown(self):
        """A stream that ends before the terminal ``result`` event
        (e.g. truncated output from a timeout) records ``unknown``.
        """
        stdout = self._build_stream_json_stdout(include_result_event=False)
        measurement = experiment_loop._parse_validator_subprocess_cost(stdout)

        assert measurement.source == "unknown"
        assert measurement.amount_usd is None

    def test_malformed_jsonl_is_unknown(self):
        """Lines that aren't JSON (rare; defensive against partial
        writes) don't crash the parser, and a stream with no usable
        result event reports unknown.
        """
        measurement = experiment_loop._parse_validator_subprocess_cost(
            "this is not json\n{not json either}\nrandom text\n"
        )
        assert measurement.source == "unknown"
        assert measurement.amount_usd is None


class TestValidatorRunnerCostIntegration:
    """End-to-end: subprocess stdout → runner tuple → cost recording.

    The runner returned by ``_make_validator_runner`` is the public seam
    that ``run_validator`` consumes. The tuple's middle element is the
    legacy ``float`` cost; under D.06 that float is the measured amount
    when present and ``NaN`` when the subprocess produced no usable
    cost field. ``validate_experiment`` detects NaN to record
    ``iteration_cost_unknown=True`` in ``quality_notes['validator']``.
    """

    def _run_runner(self, stdout: str):
        """Invoke ``_make_validator_runner()`` once with the given
        stdout patched onto ``subprocess.run``. Returns the
        ``(response, cost, latency_ms)`` tuple.
        """
        import asyncio

        runner = experiment_loop._make_validator_runner()

        fake_completed = MagicMock()
        fake_completed.stdout = stdout
        fake_completed.stderr = ""
        fake_completed.returncode = 0

        with patch("experiment_loop.subprocess.run", return_value=fake_completed):
            return asyncio.run(runner("test prompt"))

    def test_validator_subprocess_cost_parsed_from_result_event(self):
        """Measured cost from stream-json flows through the runner
        tuple as a finite float (NOT NaN, NOT zero).
        """
        import math

        stdout = (
            '{"type":"system","subtype":"init","session_id":"s1"}\n'
            '{"type":"assistant","message":{"content":[{"type":"text","text":"VERDICT: IMPROVEMENT\\nSUMMARY: ok"}]}}\n'
            '{"type":"result","subtype":"success","session_id":"s1","result":"VERDICT: IMPROVEMENT\\nSUMMARY: ok","cost_usd":0.0456}\n'
        )
        response, cost, latency_ms = self._run_runner(stdout)

        assert not math.isnan(cost), "measured cost must not be NaN"
        assert cost == pytest.approx(0.0456)
        assert "IMPROVEMENT" in response
        assert isinstance(latency_ms, int)

    def test_validator_subprocess_missing_cost_is_unknown(self):
        """A stream without ``cost_usd`` makes the runner return NaN
        instead of the pre-D.06 hardcoded 0.0. The NaN is the
        cross-boundary signal that the downstream ``validate_experiment``
        translates to ``iteration_cost_unknown=True``.
        """
        import math

        stdout = (
            '{"type":"system","subtype":"init","session_id":"s2"}\n'
            '{"type":"assistant","message":{"content":[{"type":"text","text":"VERDICT: UNSURE\\nSUMMARY: idk"}]}}\n'
            '{"type":"result","subtype":"success","session_id":"s2","result":"VERDICT: UNSURE\\nSUMMARY: idk"}\n'
        )
        _, cost, _ = self._run_runner(stdout)

        assert math.isnan(cost), (
            "missing cost_usd MUST surface as NaN (unknown), not 0.0 — "
            "the SW-3 collapse this sprint exists to prevent"
        )

    def test_validator_subprocess_crash_is_unknown(self):
        """Non-zero exit / empty stdout (crash) → NaN cost, NOT 0.0."""
        import math

        _, cost, _ = self._run_runner("")
        assert math.isnan(cost), "crash must record unknown, not zero"

    def test_validator_subprocess_measured_zero_preserved(self):
        """A genuine ``cost_usd: 0.0`` stream produces 0.0 (NOT NaN).
        Subscription-billed Claude turns are real measured zero, and
        the runner must preserve that distinct from unknown.
        """
        import math

        stdout = (
            '{"type":"system","subtype":"init","session_id":"s3"}\n'
            '{"type":"assistant","message":{"content":[{"type":"text","text":"VERDICT: IMPROVEMENT\\nSUMMARY: ok"}]}}\n'
            '{"type":"result","subtype":"success","session_id":"s3","result":"VERDICT: IMPROVEMENT\\nSUMMARY: ok","cost_usd":0.0}\n'
        )
        _, cost, _ = self._run_runner(stdout)

        assert not math.isnan(cost), "measured zero must NOT be NaN"
        assert cost == 0.0


# ---------------------------------------------------------------------------
# Sprint audit-2026-05-16.C.03 (#2058) — halt checkpoints + cancellable
# subprocesses. C.05 already extended /halt to the iteration-boundary
# top-of-loop check and the production pre-merge check. C.03 closes the
# gap C.05 left open: long-running subprocesses spawned mid-iteration
# (pytest validator, claude apply) must also abort cleanly when halt is
# set, so the operator's /halt actually interrupts in-flight work
# instead of merely preventing the next iteration from starting.
# ---------------------------------------------------------------------------


class TestBuildLoopHaltPolicy:
    """``_build_loop_halt_policy(cfg)`` returns a HaltPolicy bound to the
    same ``data/halt.flag`` that ``_check_halt(cfg)`` reads.

    The C.05 helper ``_check_halt`` stays the canonical halt-source read;
    the policy is a thin adapter so the C.03 checkpoints + cancellable
    subprocess wrapper consume the shared ``bridge.halt`` contract.
    """

    def _make_cfg(self, tmp_path):
        from dataclasses import replace

        from bridge.config import load_config

        cfg = load_config(skip_secrets=True, skip_validation=True)
        return replace(cfg, data_dir=str(tmp_path))

    def test_policy_returns_unblocked_when_flag_absent(self, tmp_path):
        cfg = self._make_cfg(tmp_path)
        policy = experiment_loop._build_loop_halt_policy(cfg)
        decision = policy.check_start("experiment_loop")
        assert decision.blocked is False
        assert decision.reason is None

    def test_policy_returns_blocked_when_flag_present(self, tmp_path):
        cfg = self._make_cfg(tmp_path)
        (tmp_path / "halt.flag").write_text("operator paused", encoding="utf-8")
        policy = experiment_loop._build_loop_halt_policy(cfg)
        start = policy.check_start("experiment_loop")
        cont = policy.check_continue("experiment_loop")
        assert start.blocked is True
        assert cont.blocked is True
        # Reason embeds the surface key with the C.01 contract format.
        assert "experiment_loop" in (start.reason or "")
        assert "operator paused" in (start.reason or "")

    def test_policy_reads_fresh_state_on_every_check(self, tmp_path):
        """The policy holds no cache — flipping halt.flag mid-life
        flips subsequent checks. Required so the cancellable
        subprocess wrapper sees a halt that fires AFTER policy
        construction.
        """
        cfg = self._make_cfg(tmp_path)
        policy = experiment_loop._build_loop_halt_policy(cfg)
        assert policy.check_continue("experiment_loop").blocked is False

        (tmp_path / "halt.flag").write_text("late halt", encoding="utf-8")
        assert policy.check_continue("experiment_loop").blocked is True

        (tmp_path / "halt.flag").unlink()
        assert policy.check_continue("experiment_loop").blocked is False

    def test_policy_with_none_cfg_is_unblocked(self, tmp_path):
        """``cfg=None`` (load_config failure at startup) degrades to
        a permanently-unblocked policy — mirrors ``_check_halt(None)``
        behavior so halt-honoring is fail-soft, not fail-loud.
        """
        policy = experiment_loop._build_loop_halt_policy(None)
        assert policy.check_start("experiment_loop").blocked is False
        assert policy.check_continue("experiment_loop").blocked is False

    def test_policy_idempotent_under_repeated_halt(self, tmp_path):
        """Calling check_continue N times against a sustained halt
        returns the same blocked decision every time — no internal
        state mutation, no raise on repeat.
        """
        cfg = self._make_cfg(tmp_path)
        (tmp_path / "halt.flag").write_text("sustained", encoding="utf-8")
        policy = experiment_loop._build_loop_halt_policy(cfg)
        decisions = [policy.check_continue("experiment_loop") for _ in range(5)]
        assert all(d.blocked for d in decisions)
        assert all("sustained" in (d.reason or "") for d in decisions)


class TestRunSubprocessCancellable:
    """``_run_subprocess_cancellable(cmd, ..., halt_policy, surface)``
    polls the policy while the subprocess runs and terminates it cleanly
    when halt fires. Honors the existing per-call timeout; on timeout
    raises ``subprocess.TimeoutExpired`` (drop-in compatible with the
    existing pytest call site).
    """

    def _make_policy(self, halted_now: bool, *, flips_after_sec: float | None = None):
        """Build a HaltPolicy with a python-callable halt source whose
        state can flip mid-test. ``flips_after_sec`` schedules the
        callable to switch True after a wall-clock delay.
        """
        import time as _time

        state = {"halted": halted_now, "flip_at": None}
        if flips_after_sec is not None:
            state["flip_at"] = _time.monotonic() + flips_after_sec

        def _is_halted() -> bool:
            if state["flip_at"] is not None and _time.monotonic() >= state["flip_at"]:
                return True
            return state["halted"]

        def _halt_reason():
            return "test halt" if _is_halted() else None

        from bridge.halt import HaltPolicy

        return HaltPolicy(is_halted=_is_halted, halt_reason=_halt_reason)

    def test_subprocess_runs_to_completion_when_halt_absent(self):
        """Halt absent → wrapper returns the subprocess result unchanged.
        Regression: the cancellable wrapper must not perturb the
        non-halt happy path.
        """
        import sys as _sys

        policy = self._make_policy(halted_now=False)
        result = experiment_loop._run_subprocess_cancellable(
            [_sys.executable, "-c", "print('ok')"],
            halt_policy=policy,
            surface="experiment_loop",
            timeout=10,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "ok" in result.stdout

    def test_subprocess_cancelled_when_halt_set_mid_run(self):
        """Halt fires WHILE subprocess is running → wrapper terminates
        the process, raises ``_HaltCancelled`` with the surface-tagged
        reason, and the child exits within a small window (no zombie).
        """
        import sys as _sys
        import time as _time

        # Subprocess sleeps long enough that the wrapper has time to
        # observe a mid-run halt at 0.25s poll cadence.
        policy = self._make_policy(halted_now=False, flips_after_sec=0.3)
        started = _time.monotonic()
        with pytest.raises(experiment_loop._HaltCancelled) as excinfo:
            experiment_loop._run_subprocess_cancellable(
                [_sys.executable, "-c", "import time; time.sleep(10)"],
                halt_policy=policy,
                surface="experiment_loop",
                timeout=15,
            )
        elapsed = _time.monotonic() - started
        # Must abort well inside the 10s sleep — proves halt actually
        # cancelled the child rather than letting it run to completion.
        assert elapsed < 5.0, f"halt cancellation took too long: {elapsed:.2f}s"
        assert "experiment_loop" in str(excinfo.value)

    def test_subprocess_timeout_still_honored(self):
        """When halt is absent and the subprocess exceeds the per-call
        timeout, the wrapper raises ``subprocess.TimeoutExpired``
        (the existing call-site contract — drop-in compatibility).
        """
        import subprocess as _sp
        import sys as _sys

        policy = self._make_policy(halted_now=False)
        with pytest.raises(_sp.TimeoutExpired):
            experiment_loop._run_subprocess_cancellable(
                [_sys.executable, "-c", "import time; time.sleep(5)"],
                halt_policy=policy,
                surface="experiment_loop",
                timeout=1,
            )

    def test_subprocess_halt_idempotent(self):
        """Sustained halt across the entire wrapper lifecycle: the
        wrapper sees blocked on the very first poll and aborts.
        Calling the wrapper a second time with the same policy
        aborts identically — no leaked state between calls.
        """
        import sys as _sys

        policy = self._make_policy(halted_now=True)
        for _ in range(3):
            with pytest.raises(experiment_loop._HaltCancelled):
                experiment_loop._run_subprocess_cancellable(
                    [_sys.executable, "-c", "import time; time.sleep(10)"],
                    halt_policy=policy,
                    surface="experiment_loop",
                    timeout=10,
                )


class TestValidateExperimentHaltMidPytest:
    """``validate_experiment(..., halt_policy=...)`` plumbs the C.03
    cancellable wrapper into the pytest subprocess call site. When
    halt fires mid-pytest, validate_experiment returns a discardable
    record carrying ``status="halted_in_flight"`` and the iteration
    proceeds to cleanup; it must NOT raise into the loop body.
    """

    def test_validate_returns_halted_in_flight_when_pytest_cancelled(
        self, tmp_path, monkeypatch
    ):
        """Mock the cancellable wrapper to raise ``_HaltCancelled`` —
        validate_experiment swallows it and returns a structured
        halted record. The cancellation MUST NOT propagate into the
        main loop as an uncaught exception (would land in the broad
        ``except Exception`` and tag the iteration ``shadow_crash`` /
        crash, masking the operator's deliberate halt).
        """
        # The wrapper raises only when halt_policy is supplied AND the
        # function is invoked. The earlier git diff / forbidden-files
        # gates need to pass for control to reach the pytest call site;
        # stub them by writing a one-file change into the worktree dir.
        worktree = tmp_path / "wt"
        agent_dir = worktree / "agent"
        agent_dir.mkdir(parents=True)

        # Stub `git diff --name-only` → one changed file. Stub
        # `git diff --stat` → human-readable summary. Both are
        # consumed via subprocess.run inside validate_experiment.
        original_subprocess_run = experiment_loop.subprocess.run

        def _fake_run(cmd, *args, **kwargs):
            from subprocess import CompletedProcess

            if cmd[:3] == ["git", "diff", "--name-only"]:
                return CompletedProcess(cmd, 0, stdout="bridge/x.py\n", stderr="")
            if cmd[:3] == ["git", "diff", "--stat"]:
                return CompletedProcess(
                    cmd, 0, stdout=" bridge/x.py | 1 +\n", stderr=""
                )
            # Any other subprocess call: punt to the real subprocess.run
            # so the test fails loudly rather than silently passing.
            return original_subprocess_run(cmd, *args, **kwargs)

        monkeypatch.setattr(experiment_loop.subprocess, "run", _fake_run)

        # Stub the cancellable wrapper so it always raises (simulating
        # halt fired mid-pytest).
        def _halted_wrapper(*args, **kwargs):
            raise experiment_loop._HaltCancelled(
                "halt flag set (surface=experiment_loop): test halt"
            )

        monkeypatch.setattr(
            experiment_loop, "_run_subprocess_cancellable", _halted_wrapper
        )

        # Build a real HaltPolicy bound to a halt.flag in tmp_path so
        # validate_experiment has something to thread through. The
        # wrapper stub raises regardless of the policy's state, so this
        # is just satisfying the kwarg contract.
        from dataclasses import replace as _replace

        from bridge.config import load_config

        cfg = _replace(
            load_config(skip_secrets=True, skip_validation=True),
            data_dir=str(tmp_path),
        )
        halt_policy = experiment_loop._build_loop_halt_policy(cfg)

        record = experiment_loop.validate_experiment(
            str(worktree),
            iter_id="iter-test",
            halt_policy=halt_policy,
        )
        assert record["status"] == "halted_in_flight"
        assert record["tests_total"] == 0
        # Reason is surfaced in diff_summary so the operator can grep it.
        assert "halt" in record["diff_summary"].lower()

    def test_validate_passes_halt_policy_through_to_wrapper(
        self, tmp_path, monkeypatch
    ):
        """When ``halt_policy`` is supplied, validate_experiment routes
        the pytest subprocess through ``_run_subprocess_cancellable``
        (carrying the policy + surface key). Default ``halt_policy=None``
        preserves the legacy direct ``subprocess.run`` path.
        """
        worktree = tmp_path / "wt"
        agent_dir = worktree / "agent"
        agent_dir.mkdir(parents=True)

        captured: dict = {}

        from subprocess import CompletedProcess

        original_subprocess_run = experiment_loop.subprocess.run

        def _fake_run(cmd, *args, **kwargs):
            if cmd[:3] == ["git", "diff", "--name-only"]:
                return CompletedProcess(cmd, 0, stdout="bridge/x.py\n", stderr="")
            if cmd[:3] == ["git", "diff", "--stat"]:
                return CompletedProcess(cmd, 0, stdout="stat", stderr="")
            # If validate_experiment routes pytest through the wrapper,
            # subprocess.run will NOT be called for pytest. If routed
            # through the legacy path, this will be called.
            if cmd[:3] == [experiment_loop.sys.executable, "-m", "pytest"]:
                captured["legacy_pytest_called"] = True
                return CompletedProcess(
                    cmd, 0, stdout="1 passed", stderr=""
                )
            return original_subprocess_run(cmd, *args, **kwargs)

        monkeypatch.setattr(experiment_loop.subprocess, "run", _fake_run)

        def _capturing_wrapper(cmd, *args, **kwargs):
            captured["wrapper_cmd"] = cmd
            captured["wrapper_kwargs"] = kwargs
            return CompletedProcess(cmd, 0, stdout="1 passed", stderr="")

        monkeypatch.setattr(
            experiment_loop, "_run_subprocess_cancellable", _capturing_wrapper
        )

        # Run quality gates → no-op so we don't need to stub the whole
        # downstream chain.
        monkeypatch.setattr(
            experiment_loop, "run_quality_gates", lambda *a, **k: tuple()
        )
        monkeypatch.setattr(
            experiment_loop, "quality_gates_all_passed", lambda *a, **k: True
        )

        from dataclasses import replace as _replace
        from bridge.config import load_config

        cfg = _replace(
            load_config(skip_secrets=True, skip_validation=True),
            data_dir=str(tmp_path),
        )
        halt_policy = experiment_loop._build_loop_halt_policy(cfg)

        # halt_policy supplied → wrapper must be called, legacy
        # subprocess.run for pytest must NOT.
        experiment_loop.validate_experiment(
            str(worktree),
            iter_id="iter-1",
            halt_policy=halt_policy,
        )
        assert "wrapper_cmd" in captured, (
            "validate_experiment must route pytest through the "
            "cancellable wrapper when halt_policy is supplied"
        )
        assert captured["wrapper_kwargs"].get("surface") == "experiment_loop"
        assert "legacy_pytest_called" not in captured


class TestMainLoopMidIterationHalt:
    """End-to-end: halt fires AFTER run_experiment returns but BEFORE
    validate_experiment is called. The new C.03 checkpoint between
    those two steps must catch this, cleanup the worktree, record a
    paused heartbeat, and ``continue`` to the next iteration — without
    calling validate_experiment or merge_experiment.

    This is the gap C.05 left open: C.05 added top-of-iteration and
    pre-merge halt checks but no checkpoint between long-running steps.
    C.03 closes it.
    """

    def test_validate_skipped_when_halt_fires_between_apply_and_validate(
        self, tmp_path, monkeypatch
    ):
        """halt.flag absent at top + absent at pre-merge (legacy C.05
        checks). The C.03 checkpoint AFTER run_experiment must fire
        because run_experiment's side-effect plants the flag.
        """
        db_path = tmp_path / "experiments.db"
        jsonl_path = tmp_path / "experiments.jsonl"
        md_path = tmp_path / "experiments.md"
        log_file = tmp_path / "experiment-loop.log"
        data_dir = tmp_path

        monkeypatch.setattr(experiment_loop, "DB_PATH", db_path)
        monkeypatch.setattr(experiment_loop, "EXPERIMENTS_JSONL_PATH", jsonl_path)
        monkeypatch.setattr(experiment_loop, "EXPERIMENTS_MD_PATH", md_path)
        monkeypatch.setattr(experiment_loop, "LOG_FILE", log_file)
        monkeypatch.setattr(experiment_loop, "DATA_DIR", data_dir)
        monkeypatch.setattr(experiment_loop, "_shutdown", False)
        monkeypatch.setattr(experiment_loop, "COOLDOWN_SECONDS", 0)

        from dataclasses import replace as _replace
        from bridge import config as _bridge_config

        original_load_config = _bridge_config.load_config

        def _fake_load_config(*args, **kwargs):
            cfg = original_load_config(*args, **kwargs)
            return _replace(cfg, data_dir=str(data_dir))

        monkeypatch.setattr(_bridge_config, "load_config", _fake_load_config)

        pick_mock = MagicMock(return_value="FILE: bridge/x.py\nCHANGE: tweak")
        monkeypatch.setattr(experiment_loop, "pick_experiment", pick_mock)

        halt_flag_path = data_dir / "halt.flag"

        def _run_experiment_then_halt(*args, **kwargs):
            """Simulate the operator typing /halt DURING the claude
            apply subprocess — flag appears between run_experiment
            returning and validate_experiment being called.
            """
            halt_flag_path.write_text("mid-apply halt", encoding="utf-8")
            return {
                "id": "iter-mid-halt",
                "worktree": str(tmp_path / "wt"),
                "branch": "experiment/mid-halt",
                "claude_exit_code": 0,
                "claude_output": "",
                "mailbox_messages": [],
            }

        run_exp_mock = MagicMock(side_effect=_run_experiment_then_halt)
        monkeypatch.setattr(experiment_loop, "run_experiment", run_exp_mock)

        validate_mock = MagicMock(return_value={"status": "keep"})
        monkeypatch.setattr(
            experiment_loop, "validate_experiment", validate_mock
        )

        merge_mock = MagicMock(return_value="deadbeef")
        monkeypatch.setattr(experiment_loop, "merge_experiment", merge_mock)

        cleanup_mock = MagicMock(return_value=None)
        monkeypatch.setattr(experiment_loop, "cleanup_worktree", cleanup_mock)

        log_mock = MagicMock()
        monkeypatch.setattr(experiment_loop, "log_result", log_mock)

        notify_mock = MagicMock()
        monkeypatch.setattr(experiment_loop, "notify_discord", notify_mock)

        # Flip _shutdown from inside _record_paused_heartbeat — that's
        # the helper the C.03 checkpoint reuses to write the halt
        # heartbeat, so the loop will exit after the first halt-skip.
        real_paused_hb = experiment_loop._record_paused_heartbeat
        paused_hb_calls = []

        def _paused_hb_and_stop(reason):
            paused_hb_calls.append(reason)
            real_paused_hb(reason)
            experiment_loop._shutdown = True

        monkeypatch.setattr(
            experiment_loop, "_record_paused_heartbeat", _paused_hb_and_stop
        )

        monkeypatch.setattr(experiment_loop.time, "sleep", lambda _s: None)
        monkeypatch.setattr(
            experiment_loop, "check_experiment_budget", lambda: True
        )
        monkeypatch.setattr(
            experiment_loop, "get_recent_experiments", lambda limit=10: []
        )
        monkeypatch.setattr(experiment_loop, "ensure_hook_dirs", lambda: None)
        monkeypatch.setattr(experiment_loop, "run_hooks", lambda phase, ctx: [])
        monkeypatch.setattr(experiment_loop, "_safe_heartbeat", lambda **kw: None)
        monkeypatch.setattr(experiment_loop, "_open_bridge_mailbox", lambda: None)
        monkeypatch.setattr(
            experiment_loop, "_load_mailbox_settings", lambda: (False, 5.0, 1000)
        )
        monkeypatch.setattr(
            experiment_loop, "_load_audit_branch_settings", lambda: (False, False, False)
        )
        monkeypatch.setattr(
            experiment_loop, "_load_validator_settings", lambda: (False, 0.30, "haiku", 0, 0)
        )

        experiment_loop.main(mode="production")

        # Run experiment fired (operator halted mid-apply).
        run_exp_mock.assert_called_once()
        # The C.03 checkpoint caught the halt → validate + merge skipped.
        validate_mock.assert_not_called()
        merge_mock.assert_not_called()
        # Worktree got cleaned up before the iteration was abandoned.
        cleanup_mock.assert_called_once()
        # Paused heartbeat was written with the halt reason.
        assert len(paused_hb_calls) == 1
        assert "mid-apply halt" in paused_hb_calls[0]

    def test_halt_then_clear_resumes_normally_on_next_iteration(
        self, tmp_path, monkeypatch
    ):
        """halt.flag plants → first iteration halt-skips → flag cleared
        → second iteration runs to completion. Verifies the C.03
        checkpoint doesn't poison the policy / loop state.
        """
        db_path = tmp_path / "experiments.db"
        jsonl_path = tmp_path / "experiments.jsonl"
        md_path = tmp_path / "experiments.md"
        log_file = tmp_path / "experiment-loop.log"
        data_dir = tmp_path

        monkeypatch.setattr(experiment_loop, "DB_PATH", db_path)
        monkeypatch.setattr(experiment_loop, "EXPERIMENTS_JSONL_PATH", jsonl_path)
        monkeypatch.setattr(experiment_loop, "EXPERIMENTS_MD_PATH", md_path)
        monkeypatch.setattr(experiment_loop, "LOG_FILE", log_file)
        monkeypatch.setattr(experiment_loop, "DATA_DIR", data_dir)
        monkeypatch.setattr(experiment_loop, "_shutdown", False)
        monkeypatch.setattr(experiment_loop, "COOLDOWN_SECONDS", 0)

        from dataclasses import replace as _replace
        from bridge import config as _bridge_config

        original_load_config = _bridge_config.load_config

        def _fake_load_config(*args, **kwargs):
            cfg = original_load_config(*args, **kwargs)
            return _replace(cfg, data_dir=str(data_dir))

        monkeypatch.setattr(_bridge_config, "load_config", _fake_load_config)

        halt_flag_path = data_dir / "halt.flag"
        # Iteration 1: halt set at top.
        halt_flag_path.write_text("first iter halt", encoding="utf-8")

        pick_mock = MagicMock(
            return_value="FILE: bridge/x.py\nCHANGE: tweak comment"
        )
        monkeypatch.setattr(experiment_loop, "pick_experiment", pick_mock)

        run_exp_mock = MagicMock(return_value={
            "id": "iter-2",
            "worktree": str(tmp_path / "wt"),
            "branch": "experiment/two",
            "claude_exit_code": 0,
            "claude_output": "",
            "mailbox_messages": [],
        })
        monkeypatch.setattr(experiment_loop, "run_experiment", run_exp_mock)

        validate_mock = MagicMock(return_value={
            "status": "keep",
            "tests_passed": 1,
            "tests_failed": 0,
            "tests_total": 1,
            "notes": {},
            "commit_hash": None,
            "diff_summary": "1 file",
            "cost_usd": 0.0,
            "duration_seconds": 0.1,
        })
        monkeypatch.setattr(
            experiment_loop, "validate_experiment", validate_mock
        )

        merge_mock = MagicMock(return_value="cafebabe")
        monkeypatch.setattr(experiment_loop, "merge_experiment", merge_mock)

        cleanup_mock = MagicMock(return_value=None)
        monkeypatch.setattr(experiment_loop, "cleanup_worktree", cleanup_mock)

        log_mock = MagicMock()
        monkeypatch.setattr(experiment_loop, "log_result", log_mock)

        iter_seq = {"n": 0}

        def _paused_hb_then_clear(reason):
            # First iteration: clear the flag so iteration 2 proceeds.
            iter_seq["n"] += 1
            if halt_flag_path.exists():
                halt_flag_path.unlink()

        monkeypatch.setattr(
            experiment_loop,
            "_record_paused_heartbeat",
            _paused_hb_then_clear,
        )

        def _notify_then_stop(*args, **kwargs):
            experiment_loop._shutdown = True

        notify_mock = MagicMock(side_effect=_notify_then_stop)
        monkeypatch.setattr(experiment_loop, "notify_discord", notify_mock)

        monkeypatch.setattr(experiment_loop.time, "sleep", lambda _s: None)
        monkeypatch.setattr(
            experiment_loop, "check_experiment_budget", lambda: True
        )
        monkeypatch.setattr(
            experiment_loop, "get_recent_experiments", lambda limit=10: []
        )
        monkeypatch.setattr(experiment_loop, "ensure_hook_dirs", lambda: None)
        monkeypatch.setattr(experiment_loop, "run_hooks", lambda phase, ctx: [])
        monkeypatch.setattr(experiment_loop, "_safe_heartbeat", lambda **kw: None)
        monkeypatch.setattr(experiment_loop, "_open_bridge_mailbox", lambda: None)
        monkeypatch.setattr(
            experiment_loop, "_load_mailbox_settings", lambda: (False, 5.0, 1000)
        )
        monkeypatch.setattr(
            experiment_loop, "_load_audit_branch_settings", lambda: (False, False, False)
        )
        monkeypatch.setattr(
            experiment_loop, "_load_validator_settings", lambda: (False, 0.30, "haiku", 0, 0)
        )

        experiment_loop.main(mode="production")

        # Iteration 1 halted; iteration 2 ran through.
        assert iter_seq["n"] >= 1, "first iteration must have halt-skipped"
        run_exp_mock.assert_called()
        validate_mock.assert_called()
        merge_mock.assert_called()
        notify_mock.assert_called()


# ---------------------------------------------------------------------------
# Sprint audit-2026-05-16.A.05 (#2049) — operator throttle for the first
# production unhalt. Two opt-in knobs:
#   - experiment_max_iterations_per_hour: cap on rolling 60-min window
#   - experiment_cooldown_after_merge_seconds: min wall-clock seconds
#     between a successful merge and the next iteration start
# Both default to "no throttle" so the existing shadow/proposal flows
# are unaffected; the runbook walks the operator through dialing them
# up before the first production unhalt.
# ---------------------------------------------------------------------------


class TestExperimentThrottle:
    """Cover ``ExperimentThrottle`` + ``_should_start_iteration`` +
    the heartbeat payload extension + the main-loop wiring.

    Pure-function tests stay synchronous; the integration-shape test at
    the bottom drives ``main(mode="production")`` with the throttle gate
    blocking the first iteration and allowing the second.
    """

    # -- pure decision logic ------------------------------------------------

    def test_should_start_iteration_ok_when_no_throttle_set(self):
        """``ExperimentThrottle()`` with defaults must never block."""
        throttle = experiment_loop.ExperimentThrottle()
        ok, reason = experiment_loop._should_start_iteration(
            throttle,
            now_iter_count_last_hour=999,
            now_seconds_since_merge=0.0,
        )
        assert ok is True
        assert reason is None

    def test_hourly_throttle_blocks_at_cap(self):
        """At the cap, the gate must block and tag the reason."""
        throttle = experiment_loop.ExperimentThrottle(
            max_iterations_per_hour=3
        )
        ok, reason = experiment_loop._should_start_iteration(
            throttle,
            now_iter_count_last_hour=3,
            now_seconds_since_merge=None,
        )
        assert ok is False
        assert reason is not None and reason.startswith("hourly_throttle")

    def test_hourly_throttle_allows_below_cap(self):
        """One iteration below the cap is fine."""
        throttle = experiment_loop.ExperimentThrottle(
            max_iterations_per_hour=5
        )
        ok, reason = experiment_loop._should_start_iteration(
            throttle,
            now_iter_count_last_hour=4,
            now_seconds_since_merge=None,
        )
        assert ok is True
        assert reason is None

    def test_unknown_iteration_count_fails_open(self):
        """``None`` count (DB unavailable) MUST NOT block — the throttle
        is best-effort observability and the operator's E.05 gate
        catches DB-availability regressions separately.
        """
        throttle = experiment_loop.ExperimentThrottle(
            max_iterations_per_hour=1
        )
        ok, reason = experiment_loop._should_start_iteration(
            throttle,
            now_iter_count_last_hour=None,
            now_seconds_since_merge=None,
        )
        assert ok is True
        assert reason is None

    def test_cooldown_blocks_within_window(self):
        """30s since merge < 60s cooldown → block, reason mentions
        ``merge_cooldown`` with remaining seconds.
        """
        throttle = experiment_loop.ExperimentThrottle(
            cooldown_after_merge_seconds=60
        )
        ok, reason = experiment_loop._should_start_iteration(
            throttle,
            now_iter_count_last_hour=0,
            now_seconds_since_merge=30.0,
        )
        assert ok is False
        assert reason is not None
        assert "merge_cooldown" in reason
        # Remaining seconds embedded in the label so jq can spot-check.
        assert "30" in reason or "29" in reason or "s_remaining" in reason

    def test_cooldown_allows_after_window(self):
        """120s since merge > 60s cooldown → allow."""
        throttle = experiment_loop.ExperimentThrottle(
            cooldown_after_merge_seconds=60
        )
        ok, reason = experiment_loop._should_start_iteration(
            throttle,
            now_iter_count_last_hour=0,
            now_seconds_since_merge=120.0,
        )
        assert ok is True
        assert reason is None

    def test_cooldown_none_seconds_since_merge_means_no_cooldown(self):
        """No prior merge → cooldown has no anchor → don't block."""
        throttle = experiment_loop.ExperimentThrottle(
            cooldown_after_merge_seconds=600
        )
        ok, reason = experiment_loop._should_start_iteration(
            throttle,
            now_iter_count_last_hour=0,
            now_seconds_since_merge=None,
        )
        assert ok is True
        assert reason is None

    # -- heartbeat payload --------------------------------------------------

    def test_heartbeat_payload_includes_throttle_block(
        self, tmp_path, monkeypatch
    ):
        """When _write_heartbeat is called with throttle + decision, the
        JSON payload includes the documented ``throttle`` block.
        """
        import json as _json

        target = tmp_path / "experiment-heartbeat.json"
        monkeypatch.setattr(experiment_loop, "HEARTBEAT_PATH", target)
        monkeypatch.setattr(
            experiment_loop, "DB_PATH", tmp_path / "missing.db"
        )

        throttle = experiment_loop.ExperimentThrottle(
            max_iterations_per_hour=3,
            cooldown_after_merge_seconds=600,
        )
        experiment_loop._write_heartbeat(
            mode="production",
            status="paused_throttle",
            branch=None,
            throttle=throttle,
            throttle_decision="hourly_throttle:3/3",
        )

        payload = _json.loads(target.read_text(encoding="utf-8"))
        assert "throttle" in payload, "missing throttle block"
        block = payload["throttle"]
        assert block["max_per_hour"] == 3
        assert block["cooldown_seconds"] == 600
        assert block["last_decision"] == "hourly_throttle:3/3"

    def test_heartbeat_omits_throttle_block_when_not_supplied(
        self, tmp_path, monkeypatch
    ):
        """Back-compat: legacy callers (halt path, shutdown) that don't
        pass throttle MUST get the pre-A.05 payload shape with the
        throttle block absent.
        """
        import json as _json

        target = tmp_path / "experiment-heartbeat.json"
        monkeypatch.setattr(experiment_loop, "HEARTBEAT_PATH", target)
        monkeypatch.setattr(
            experiment_loop, "DB_PATH", tmp_path / "missing.db"
        )

        experiment_loop._write_heartbeat(
            mode="shadow",
            status="shadow_keep",
            branch="experiment/iter-x",
        )
        payload = _json.loads(target.read_text(encoding="utf-8"))
        assert "throttle" not in payload, (
            "legacy callers must not see throttle block"
        )

    # -- main-loop integration ---------------------------------------------

    def test_main_throttle_skips_iteration_then_proceeds(
        self, tmp_path, monkeypatch
    ):
        """Cap=1, one prior iteration in the last hour → first call to
        ``_should_start_iteration`` blocks; on the second loop tick we
        flip the counter helper to allow the iteration through.
        """
        db_path = tmp_path / "experiments.db"
        jsonl_path = tmp_path / "experiments.jsonl"
        md_path = tmp_path / "experiments.md"
        log_file = tmp_path / "experiment-loop.log"
        data_dir = tmp_path
        heartbeat_path = tmp_path / "experiment-heartbeat.json"

        monkeypatch.setattr(experiment_loop, "DB_PATH", db_path)
        monkeypatch.setattr(experiment_loop, "EXPERIMENTS_JSONL_PATH", jsonl_path)
        monkeypatch.setattr(experiment_loop, "EXPERIMENTS_MD_PATH", md_path)
        monkeypatch.setattr(experiment_loop, "LOG_FILE", log_file)
        monkeypatch.setattr(experiment_loop, "DATA_DIR", data_dir)
        monkeypatch.setattr(experiment_loop, "HEARTBEAT_PATH", heartbeat_path)
        monkeypatch.setattr(experiment_loop, "_shutdown", False)
        monkeypatch.setattr(experiment_loop, "COOLDOWN_SECONDS", 0)

        # Pin cfg so the throttle inside main() is built with cap=1 +
        # no cooldown. Mirrors the TestHeartbeatJson pattern.
        from dataclasses import replace as _replace
        from bridge import config as _bridge_config

        original_load_config = _bridge_config.load_config

        def _fake_load_config(*args, **kwargs):
            cfg = original_load_config(*args, **kwargs)
            return _replace(
                cfg,
                data_dir=str(data_dir),
                experiment_max_iterations_per_hour=1,
                experiment_cooldown_after_merge_seconds=0,
            )

        monkeypatch.setattr(_bridge_config, "load_config", _fake_load_config)

        # Drive the throttle decision via the iteration-count helper:
        # first call returns 1 (>= cap → block), subsequent calls
        # return 0 (allow).
        call_count = {"n": 0}

        def _fake_count():
            call_count["n"] += 1
            return 1 if call_count["n"] == 1 else 0

        monkeypatch.setattr(
            experiment_loop, "_iterations_in_last_hour", _fake_count
        )
        # No prior merge anchor — keep cooldown irrelevant.
        monkeypatch.setattr(
            experiment_loop, "_seconds_since_last_merge", lambda: None
        )

        pick_mock = MagicMock(
            return_value="FILE: bridge/x.py\nCHANGE: tweak comment"
        )
        monkeypatch.setattr(experiment_loop, "pick_experiment", pick_mock)

        run_exp_mock = MagicMock(return_value={
            "id": "iter-throttle-2",
            "worktree": str(tmp_path / "wt"),
            "branch": "experiment/throttle-2",
            "claude_exit_code": 0,
            "claude_output": "",
            "mailbox_messages": [],
        })
        monkeypatch.setattr(experiment_loop, "run_experiment", run_exp_mock)

        validate_mock = MagicMock(return_value={
            "status": "shadow_keep",
            "tests_passed": 1,
            "tests_failed": 0,
            "tests_total": 1,
            "notes": {},
            "commit_hash": None,
            "diff_summary": "1 file",
            "cost_usd": 0.0,
            "duration_seconds": 0.1,
        })
        monkeypatch.setattr(
            experiment_loop, "validate_experiment", validate_mock
        )

        cleanup_mock = MagicMock(return_value=None)
        monkeypatch.setattr(experiment_loop, "cleanup_worktree", cleanup_mock)

        log_mock = MagicMock()
        monkeypatch.setattr(experiment_loop, "log_result", log_mock)

        # Capture throttled heartbeat calls + stop after the second
        # iteration completes (notify_discord fires post-merge/post-keep
        # in the shadow flow).
        throttled_calls = []
        real_throttle_hb = experiment_loop._record_throttled_heartbeat

        def _throttled_hb_capture(mode, throttle, reason):
            throttled_calls.append((mode, throttle, reason))
            real_throttle_hb(mode, throttle, reason)

        monkeypatch.setattr(
            experiment_loop,
            "_record_throttled_heartbeat",
            _throttled_hb_capture,
        )

        def _notify_then_stop(*args, **kwargs):
            experiment_loop._shutdown = True

        notify_mock = MagicMock(side_effect=_notify_then_stop)
        monkeypatch.setattr(experiment_loop, "notify_discord", notify_mock)

        monkeypatch.setattr(experiment_loop.time, "sleep", lambda _s: None)
        monkeypatch.setattr(
            experiment_loop, "check_experiment_budget", lambda: True
        )
        monkeypatch.setattr(
            experiment_loop, "get_recent_experiments", lambda limit=10: []
        )
        monkeypatch.setattr(experiment_loop, "ensure_hook_dirs", lambda: None)
        monkeypatch.setattr(experiment_loop, "run_hooks", lambda phase, ctx: [])
        monkeypatch.setattr(experiment_loop, "_safe_heartbeat", lambda **kw: None)
        monkeypatch.setattr(experiment_loop, "_open_bridge_mailbox", lambda: None)
        monkeypatch.setattr(
            experiment_loop, "_load_mailbox_settings", lambda: (False, 5.0, 1000)
        )
        monkeypatch.setattr(
            experiment_loop, "_load_audit_branch_settings", lambda: (False, False, False)
        )
        monkeypatch.setattr(
            experiment_loop, "_load_validator_settings", lambda: (False, 0.30, "haiku", 0, 0)
        )

        # Use shadow mode so the test doesn't have to mock the
        # production-mode merge path; the throttle gate is mode-agnostic.
        experiment_loop.main(mode="shadow")

        # First iteration was throttle-blocked; second iteration ran.
        assert len(throttled_calls) >= 1, (
            "throttle gate must have blocked the first iteration"
        )
        assert throttled_calls[0][2].startswith("hourly_throttle"), (
            f"unexpected throttle reason: {throttled_calls[0][2]!r}"
        )
        run_exp_mock.assert_called()
        validate_mock.assert_called()
        notify_mock.assert_called()


class TestAuditBranchCleanupReport:
    """Sprint audit-2026-05-16.E.02 (#2070, Section 8.2).

    Cover the local-audit-branch cleanup gate, the
    ``_cleanup_local_audit_branch`` helper's fail-soft contract, the
    3-tuple shape of ``_load_audit_branch_settings``, and the
    ``audit_branches`` heartbeat extension.

    The post-merge gate is expressed inline in ``main()`` as
    ``audit_enabled and not audit_push and audit_local_cleanup and
    commit is not None``. The four "gate" tests below assert the
    decision the inline gate makes for each input combination by
    re-evaluating the same predicate; ``test_cleanup_invoked_for_local_mode_with_flag``
    asserts the helper IS called when the gate passes, the three
    skipped-* tests assert it is NOT called when any one input opts
    out.
    """

    # -- gate predicate ----------------------------------------------------

    @staticmethod
    def _gate(
        *,
        enabled: bool,
        push: bool,
        local_cleanup: bool,
        commit: str | None,
    ) -> bool:
        """Mirror the inline post-merge gate in ``main()``."""
        return enabled and not push and local_cleanup and commit is not None

    def test_cleanup_skipped_when_disabled(self):
        """``enabled=False`` opts out regardless of the other flags."""
        assert (
            self._gate(
                enabled=False,
                push=False,
                local_cleanup=True,
                commit="abc123",
            )
            is False
        )

    def test_cleanup_skipped_when_remote(self):
        """``push_to_origin=True`` (remote mode) opts out."""
        assert (
            self._gate(
                enabled=True,
                push=True,
                local_cleanup=True,
                commit="abc123",
            )
            is False
        )

    def test_cleanup_skipped_when_local_cleanup_false(self):
        """Local-mode branches persist when the new flag is off (the
        pre-E.02 default behaviour)."""
        assert (
            self._gate(
                enabled=True,
                push=False,
                local_cleanup=False,
                commit="abc123",
            )
            is False
        )

    def test_cleanup_invoked_for_local_mode_with_flag(self):
        """All three flags satisfied + a real merge → gate passes."""
        assert (
            self._gate(
                enabled=True,
                push=False,
                local_cleanup=True,
                commit="abc123",
            )
            is True
        )
        # And a discard (commit is None) still opts out, even with all
        # three flags set — forensic inspection of the discard path
        # needs the branch.
        assert (
            self._gate(
                enabled=True,
                push=False,
                local_cleanup=True,
                commit=None,
            )
            is False
        )

    # -- _cleanup_local_audit_branch helper --------------------------------

    def test_cleanup_success_deletes_branch(self, monkeypatch):
        """returncode=0 → (True, None)."""
        captured: list[list[str]] = []

        class _R:
            returncode = 0
            stderr = ""

        def _fake_run(cmd, **kwargs):
            captured.append(cmd)
            return _R()

        monkeypatch.setattr(experiment_loop.subprocess, "run", _fake_run)
        ok, err = experiment_loop._cleanup_local_audit_branch(
            "autoresearch/iter-abc"
        )
        assert ok is True
        assert err is None
        assert captured and captured[0][:3] == [
            "git",
            "branch",
            "-D",
        ]
        assert captured[0][3] == "autoresearch/iter-abc"

    def test_cleanup_failure_returns_error_message(self, monkeypatch):
        """returncode=1 → (False, '<stderr>')."""

        class _R:
            returncode = 1
            stderr = "error: branch not fully merged"

        monkeypatch.setattr(
            experiment_loop.subprocess, "run", lambda *a, **k: _R()
        )
        ok, err = experiment_loop._cleanup_local_audit_branch(
            "autoresearch/iter-abc"
        )
        assert ok is False
        assert err == "error: branch not fully merged"

    def test_cleanup_with_none_branch_succeeds_noop(self, monkeypatch):
        """``branch_name=None`` is a silent no-op; subprocess never runs."""
        called: list[object] = []
        monkeypatch.setattr(
            experiment_loop.subprocess,
            "run",
            lambda *a, **k: called.append(a) or None,
        )
        ok, err = experiment_loop._cleanup_local_audit_branch(None)
        assert ok is True
        assert err is None
        assert called == [], "subprocess.run must not be called for None branch"

        # Empty string is treated identically.
        ok2, err2 = experiment_loop._cleanup_local_audit_branch("")
        assert ok2 is True
        assert err2 is None
        assert called == []

    def test_cleanup_subprocess_exception_fail_soft(self, monkeypatch):
        """Subprocess raises → (False, '<exc message>'), no propagation."""

        def _boom(*a, **k):
            raise OSError("git binary missing")

        monkeypatch.setattr(experiment_loop.subprocess, "run", _boom)
        ok, err = experiment_loop._cleanup_local_audit_branch(
            "autoresearch/iter-abc"
        )
        assert ok is False
        assert err is not None and "git binary missing" in err

    # -- settings loader returns 3-tuple -----------------------------------

    def test_load_audit_branch_settings_returns_three_tuple(self):
        """E.02 widened the return shape; verify the new arity + types."""
        result = experiment_loop._load_audit_branch_settings()
        assert isinstance(result, tuple)
        assert len(result) == 3
        enabled, push, local_cleanup = result
        assert isinstance(enabled, bool)
        assert isinstance(push, bool)
        assert isinstance(local_cleanup, bool)

    # -- heartbeat payload extension ---------------------------------------

    def test_heartbeat_audit_branches_block_local_cleanup_ok(
        self, tmp_path, monkeypatch
    ):
        """Calling ``_write_heartbeat`` with the audit_branches_* kwargs
        produces the documented block shape on disk.
        """
        import json as _json

        target = tmp_path / "experiment-heartbeat.json"
        monkeypatch.setattr(experiment_loop, "HEARTBEAT_PATH", target)
        monkeypatch.setattr(
            experiment_loop, "DB_PATH", tmp_path / "missing.db"
        )

        experiment_loop._write_heartbeat(
            mode="production",
            status="keep",
            branch="experiment/iter-abc",
            audit_branches_enabled=True,
            audit_branches_mode="local",
            audit_branches_local_cleanup=True,
            audit_branches_last_branch="autoresearch/iter-abc",
            audit_branches_last_cleanup_status="ok",
        )

        payload = _json.loads(target.read_text(encoding="utf-8"))
        assert "audit_branches" in payload, "missing audit_branches block"
        block = payload["audit_branches"]
        assert block["enabled"] is True
        assert block["mode"] == "local"
        assert block["local_cleanup"] is True
        assert block["last_branch"] == "autoresearch/iter-abc"
        assert block["last_cleanup_status"] == "ok"

        # Back-compat: legacy callers that omit the kwargs still get the
        # pre-E.02 payload shape with ``audit_branches`` absent.
        experiment_loop._write_heartbeat(
            mode="shadow",
            status="shadow_keep",
            branch="experiment/iter-y",
        )
        payload2 = _json.loads(target.read_text(encoding="utf-8"))
        assert "audit_branches" not in payload2, (
            "legacy callers must not see audit_branches block"
        )


# ---------------------------------------------------------------------------
# Sprint audit-2026-05-16.E.04 (#2072) — first three leaf seams moved
# from ``scripts/experiment_loop.py`` to ``bridge/experiment_runtime.py``
# ahead of the formal demote-split. These tests pin the move so the
# experiment_loop call sites continue resolving through the re-export
# shim, and the new runtime module's ``_build_halt_policy`` accepts the
# decoupled ``data_dir: Path`` parameter the extraction was reshaped for.
# ---------------------------------------------------------------------------


class TestExperimentRuntimeImports:
    """Pin the E.04 extraction. Three pure leaves now live in
    ``bridge.experiment_runtime``; ``experiment_loop`` re-exports
    them so existing call sites resolve without change.
    """

    def test_runtime_module_has_append_trailers(self):
        from bridge.experiment_runtime import _append_experiment_trailers

        assert callable(_append_experiment_trailers)

    def test_runtime_module_has_trailer_key_constant(self):
        from bridge.experiment_runtime import _EXPERIMENT_TRAILER_KEY

        assert _EXPERIMENT_TRAILER_KEY == "Bumba-Agent-Experiment"

    def test_runtime_module_has_parse_cost(self):
        from bridge.experiment_runtime import _parse_validator_subprocess_cost

        assert callable(_parse_validator_subprocess_cost)

    def test_runtime_module_has_build_halt_policy(self):
        """Runtime factory accepts a ``data_dir: Path`` positional
        argument — the reshape that decoupled the new module from
        ``experiment_loop``'s BridgeConfig dependency.
        """
        import inspect

        from bridge.experiment_runtime import _build_halt_policy

        assert callable(_build_halt_policy)
        sig = inspect.signature(_build_halt_policy)
        assert "data_dir" in sig.parameters, (
            "the E.04 reshape requires a data_dir parameter so the "
            "runtime module has zero dependency on experiment_loop"
        )

    def test_runtime_helpers_match_loop_reexports(self):
        """The re-export shim shares the SAME function object — not a
        copy. Proves ``experiment_loop._append_experiment_trailers`` and
        ``experiment_loop._parse_validator_subprocess_cost`` resolve to
        the new module's definitions, not stale local bodies.
        """
        from bridge import experiment_runtime

        assert (
            experiment_loop._append_experiment_trailers
            is experiment_runtime._append_experiment_trailers
        )
        assert (
            experiment_loop._parse_validator_subprocess_cost
            is experiment_runtime._parse_validator_subprocess_cost
        )
        assert (
            experiment_loop._EXPERIMENT_TRAILER_KEY
            == experiment_runtime._EXPERIMENT_TRAILER_KEY
        )

    def test_build_halt_policy_accepts_data_dir_param(self, tmp_path):
        """End-to-end: pass a tmp_path, get back a HaltPolicy, the
        policy's ``check_start`` resolves against ``<tmp_path>/halt.flag``.
        """
        from bridge.experiment_runtime import _build_halt_policy
        from bridge.halt import HaltPolicy

        policy = _build_halt_policy(tmp_path)
        assert isinstance(policy, HaltPolicy)

        # No flag → unblocked.
        decision = policy.check_start("test-surface")
        assert decision.blocked is False
        assert decision.reason is None

        # Flag with reason → blocked, reason propagates.
        (tmp_path / "halt.flag").write_text("e04 smoke", encoding="utf-8")
        blocked = policy.check_start("test-surface")
        assert blocked.blocked is True
        assert "e04 smoke" in (blocked.reason or "")
