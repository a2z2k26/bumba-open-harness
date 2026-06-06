"""Tests for ``scripts/finalize_experiments`` (Sprint 02.08, issue #983).

Covers the four pure helpers (``load_keep_iterations``, ``group_by_files``,
``group_by_topic``, ``write_finalize_report``), the
``create_finalize_branch`` driver under a recorded fake-git callable,
the CLI ``main`` end-to-end (dry-run + happy-path), and the
``/experiment_finalize`` + ``/experiment_finalize_status`` operator
commands.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

# The script imports cleanly as a module; the Sprint 02.08 deliverable
# also says it must be importable. Add the scripts dir to sys.path
# defensively (mirrors test_experiment_loop.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import finalize_experiments as fe  # noqa: E402

from bridge.commands import CommandHandler  # noqa: E402


# ── Fixtures ───────────────────────────────────────────────────────


def _record_line(
    *,
    iter_id: int,
    status: str = "keep",
    diff_summary: str = "",
    description: str = "",
    fitness_delta: float = 0.0,
    cost_usd: float = 0.0,
    commit_hash: str = "",
    created_at: Optional[str] = None,
) -> str:
    rec = {
        "iter_id": iter_id,
        "commit_hash": commit_hash or f"sha{iter_id:04d}",
        "branch": f"autoresearch/iter-{iter_id}",
        "tests_passed": 1,
        "tests_failed": 0,
        "tests_total": 1,
        "status": status,
        "description": description or f"iter {iter_id} subject",
        "diff_summary": diff_summary,
        "cost_usd": cost_usd,
        "duration_seconds": 1.0,
        "fitness_delta": fitness_delta,
        "confidence_seconds": None,
        "significant": False,
        "created_at": created_at or "2026-04-30T12:00:00",
        "notes": {},
    }
    return json.dumps(rec)


@pytest.fixture
def jsonl_path(tmp_path: Path) -> Path:
    return tmp_path / "experiments.jsonl"


# ── load_keep_iterations ───────────────────────────────────────────


class TestLoadKeepIterations:
    def test_filters_to_keep_only(self, jsonl_path: Path):
        jsonl_path.write_text(
            _record_line(iter_id=1, status="keep") + "\n"
            + _record_line(iter_id=2, status="discard") + "\n"
            + _record_line(iter_id=3, status="crash") + "\n"
            + _record_line(iter_id=4, status="keep") + "\n"
        )
        records = fe.load_keep_iterations(jsonl_path=jsonl_path)
        assert [r.iter_id for r in records] == ["1", "4"]

    def test_window_filter_since_and_until(self, jsonl_path: Path):
        jsonl_path.write_text(
            _record_line(iter_id=1, created_at="2026-04-01T00:00:00") + "\n"
            + _record_line(iter_id=2, created_at="2026-04-15T00:00:00") + "\n"
            + _record_line(iter_id=3, created_at="2026-05-01T00:00:00") + "\n"
        )
        since = datetime(2026, 4, 10, tzinfo=timezone.utc)
        until = datetime(2026, 4, 20, tzinfo=timezone.utc)
        records = fe.load_keep_iterations(
            jsonl_path=jsonl_path, since=since, until=until
        )
        assert [r.iter_id for r in records] == ["2"]

    def test_missing_file_returns_empty(self, tmp_path: Path):
        records = fe.load_keep_iterations(jsonl_path=tmp_path / "absent.jsonl")
        assert records == []

    def test_skips_malformed_lines(self, jsonl_path: Path):
        jsonl_path.write_text(
            _record_line(iter_id=1) + "\n"
            + "not json at all\n"
            + _record_line(iter_id=2) + "\n"
        )
        records = fe.load_keep_iterations(jsonl_path=jsonl_path)
        assert [r.iter_id for r in records] == ["1", "2"]

    def test_parses_files_from_diff_summary(self, jsonl_path: Path):
        diff = (
            "agent/bridge/foo.py | 12 ++++++++----\n"
            "agent/tests/test_foo.py |  5 ++++-\n"
            " 2 files changed, 13 insertions(+), 4 deletions(-)\n"
        )
        jsonl_path.write_text(_record_line(iter_id=1, diff_summary=diff) + "\n")
        records = fe.load_keep_iterations(jsonl_path=jsonl_path)
        assert records[0].files_touched == (
            "agent/bridge/foo.py", "agent/tests/test_foo.py",
        )


# ── group_by_files ─────────────────────────────────────────────────


def _iter(iter_id: int, files: tuple[str, ...], *, subject: str = "", delta: float = 0.0) -> fe.IterationRecord:
    return fe.IterationRecord(
        iter_id=str(iter_id),
        completed_at_iso="2026-04-30T12:00:00",
        files_touched=files,
        fitness_before=0.0,
        fitness_after=0.0,
        fitness_delta=delta,
        cost_usd=0.0,
        commit_subject=subject or f"iter {iter_id}",
        commit_sha=f"sha{iter_id:04d}",
    )


class TestGroupByFiles:
    def test_clusters_overlapping_files(self):
        a = _iter(1, ("agent/bridge/A.py", "agent/bridge/B.py"))
        b = _iter(2, ("agent/bridge/A.py", "agent/bridge/B.py"))
        c = _iter(3, ("agent/tests/C.py", "agent/tests/D.py"))
        d = _iter(4, ("agent/tests/C.py", "agent/tests/D.py"))
        groups = fe.group_by_files([a, b, c, d])
        assert len(groups) == 2
        members = sorted(len(g.members) for g in groups)
        assert members == [2, 2]

    def test_threshold_drives_fusion(self):
        a = _iter(1, ("x.py", "y.py", "z.py"))
        b = _iter(2, ("y.py", "z.py", "w.py"))  # Jaccard 0.5 vs a
        # At 0.5 (default) → fused; at 0.6 → split.
        fused = fe.group_by_files([a, b], similarity_threshold=0.5)
        split = fe.group_by_files([a, b], similarity_threshold=0.6)
        assert len(fused) == 1
        assert len(split) == 2

    def test_empty_input_returns_empty(self):
        assert fe.group_by_files([]) == []

    def test_single_iteration_yields_single_group(self):
        groups = fe.group_by_files([_iter(1, ("agent/foo.py",))])
        assert len(groups) == 1
        assert len(groups[0].members) == 1

    def test_group_name_uses_common_prefix(self):
        a = _iter(1, ("agent/bridge/A.py", "agent/bridge/B.py"))
        b = _iter(2, ("agent/bridge/A.py", "agent/bridge/B.py"))
        groups = fe.group_by_files([a, b])
        assert "agent/bridge" in groups[0].name or "agent" in groups[0].name


# ── group_by_topic ─────────────────────────────────────────────────


class TestGroupByTopic:
    def test_clusters_by_keyword_overlap(self):
        a = _iter(1, (), subject="optimize import resolution in router")
        b = _iter(2, (), subject="trim import paths and lint warnings")
        c = _iter(3, (), subject="cache invalidation perf hotpath")
        # Top-3 tokens (subject minus stopwords/dedup): a→{optimize,import,
        # resolution}, b→{trim,import,paths}, c→{cache,invalidation,perf}.
        # Jaccard(a,b)=1/5=0.20, Jaccard(a,c)=Jaccard(b,c)=0. Lower the
        # threshold below 0.20 so the shared "import" token fuses a+b
        # while c stays alone.
        groups = fe.group_by_topic(
            [a, b, c], keyword_top_n=3, similarity_threshold=0.15,
        )
        sizes = sorted(len(g.members) for g in groups)
        assert sizes == [1, 2]

    def test_singleton_when_no_overlap(self):
        a = _iter(1, (), subject="alpha beta gamma")
        b = _iter(2, (), subject="delta epsilon zeta")
        groups = fe.group_by_topic([a, b])
        assert len(groups) == 2

    def test_untagged_when_subject_empty_or_stopwords(self):
        a = _iter(1, (), subject="the of and")  # all stopwords
        groups = fe.group_by_topic([a])
        assert len(groups) == 1
        assert "untagged" in groups[0].name


# ── create_finalize_branch ─────────────────────────────────────────


class _FakeGit:
    """Records every call. Returns CompletedProcess; default rc=0.

    Tests can prime ``rc_overrides`` to fail specific subcommands by
    matching on a tuple key (the leading args).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.rc_overrides: dict[tuple[str, ...], int] = {}

    def __call__(
        self, args: list[str], cwd: Path
    ) -> subprocess.CompletedProcess:
        self.calls.append(tuple(args))
        rc = 0
        for key, value in self.rc_overrides.items():
            if tuple(args[: len(key)]) == key:
                rc = value
                break
        return subprocess.CompletedProcess(
            args=args, returncode=rc, stdout="", stderr="forced-fail" if rc else "",
        )


class TestCreateFinalizeBranch:
    def test_happy_path_runs_branch_and_cherry_picks(self, tmp_path: Path):
        a = _iter(1, ("agent/foo.py",))
        b = _iter(2, ("agent/foo.py",))
        group = fe._summarize_group("agent", [a, b])
        git = _FakeGit()
        name = fe.create_finalize_branch(group, repo_root=tmp_path, git=git)
        assert name == "experiment-finalize/agent"
        # Expect: branch create, checkout, two cherry-picks.
        cmds = [c[0] for c in git.calls]
        assert cmds[:2] == ["branch", "checkout"]
        assert cmds.count("cherry-pick") == 2

    def test_cherry_pick_conflict_renames_branch(self, tmp_path: Path):
        a = _iter(1, ("agent/foo.py",))
        b = _iter(2, ("agent/foo.py",))
        group = fe._summarize_group("agent", [a, b])
        git = _FakeGit()
        # Fail the cherry-pick of b's sha.
        git.rc_overrides[("cherry-pick", "sha0002")] = 1
        name = fe.create_finalize_branch(group, repo_root=tmp_path, git=git)
        assert name.startswith("experiment-finalize/CONFLICT-")
        # Abort + rename should both have been attempted.
        cmds = [tuple(c[:2]) for c in git.calls]
        assert ("cherry-pick", "--abort") in cmds
        assert any(c[0] == "branch" and c[1] == "-m" for c in git.calls)

    def test_branch_create_failure_raises(self, tmp_path: Path):
        a = _iter(1, ("agent/foo.py",))
        group = fe._summarize_group("agent", [a])
        git = _FakeGit()
        git.rc_overrides[("branch",)] = 1
        with pytest.raises(RuntimeError):
            fe.create_finalize_branch(group, repo_root=tmp_path, git=git)


# ── write_finalize_report ──────────────────────────────────────────


class TestWriteFinalizeReport:
    def test_atomic_write_and_well_formed(self, tmp_path: Path):
        a = _iter(1, ("agent/foo.py",), subject="add foo", delta=0.05)
        b = _iter(2, ("agent/foo.py",), subject="trim foo", delta=0.02)
        group = fe._summarize_group("agent", [a, b])
        report = fe.FinalizeReport(
            window_start_iso="2026-04-01T00:00:00",
            window_end_iso="2026-05-01T00:00:00",
            grouping_mode="files",
            total_iterations=2,
            groups=(group,),
            branches_created=("experiment-finalize/agent",),
            duration_seconds=0.42,
        )
        out = tmp_path / "report.md"
        fe.write_finalize_report(report, output_path=out)
        body = out.read_text()
        assert "# Experiment finalize report" in body
        assert "experiment-finalize/agent" in body
        assert "Total fitness Δ" in body
        # No leftover .tmp file.
        assert not (tmp_path / "report.md.tmp").exists()

    def test_empty_report_renders(self, tmp_path: Path):
        report = fe.FinalizeReport(
            window_start_iso="2026-04-01T00:00:00",
            window_end_iso="2026-05-01T00:00:00",
            grouping_mode="files",
            total_iterations=0,
            groups=(),
            branches_created=(),
            duration_seconds=0.0,
        )
        out = tmp_path / "report.md"
        fe.write_finalize_report(report, output_path=out)
        assert "_No keep iterations" in out.read_text()


# ── main / CLI ─────────────────────────────────────────────────────


class TestMain:
    def test_dry_run_writes_report_no_branches(
        self, tmp_path: Path, monkeypatch
    ):
        jsonl = tmp_path / "experiments.jsonl"
        diff = "agent/bridge/foo.py | 1 +\n agent/tests/test_foo.py | 1 +\n"
        jsonl.write_text(
            _record_line(iter_id=1, diff_summary=diff) + "\n"
            + _record_line(iter_id=2, diff_summary=diff) + "\n"
        )
        report = tmp_path / "out.md"

        # Spy on create_finalize_branch — must not be called.
        called: list[bool] = []

        def _fail(*a, **kw):
            called.append(True)
            raise AssertionError("create_finalize_branch should not run in --dry-run")

        monkeypatch.setattr(fe, "create_finalize_branch", _fail)

        rc = fe.main([
            "--jsonl-path", str(jsonl),
            "--report-path", str(report),
            "--repo-root", str(tmp_path),
            "--dry-run",
            "--since", "2026-04-01",
            "--until", "2026-12-31",
        ])
        assert rc == 0
        assert report.exists()
        assert called == []

    def test_happy_path_creates_branches_and_records_them(
        self, tmp_path: Path, monkeypatch
    ):
        jsonl = tmp_path / "experiments.jsonl"
        diff_a = "agent/bridge/foo.py | 1 +\n"
        diff_b = "agent/tests/test_foo.py | 1 +\n"
        jsonl.write_text(
            _record_line(iter_id=1, diff_summary=diff_a) + "\n"
            + _record_line(iter_id=2, diff_summary=diff_a) + "\n"
            + _record_line(iter_id=3, diff_summary=diff_b) + "\n"
            + _record_line(iter_id=4, diff_summary=diff_b) + "\n"
        )
        report = tmp_path / "out.md"

        created: list[str] = []

        def _fake_create(group, *, repo_root, base_ref="main", git=None):
            name = f"experiment-finalize/{group.name}"
            created.append(name)
            return name

        monkeypatch.setattr(fe, "create_finalize_branch", _fake_create)

        rc = fe.main([
            "--jsonl-path", str(jsonl),
            "--report-path", str(report),
            "--repo-root", str(tmp_path),
            "--since", "2026-04-01",
            "--until", "2026-12-31",
        ])
        assert rc == 0
        # Two clusters: bridge/foo.py iters and tests/test_foo.py iters.
        assert len(created) == 2
        body = report.read_text()
        assert "Branches created: 2" in body

    def test_zero_keep_iterations_produces_empty_report(
        self, tmp_path: Path, monkeypatch
    ):
        jsonl = tmp_path / "experiments.jsonl"
        jsonl.write_text(_record_line(iter_id=1, status="discard") + "\n")
        report = tmp_path / "out.md"

        def _fake_create(*a, **kw):
            raise AssertionError("should not create branches when input is empty")

        monkeypatch.setattr(fe, "create_finalize_branch", _fake_create)

        rc = fe.main([
            "--jsonl-path", str(jsonl),
            "--report-path", str(report),
            "--repo-root", str(tmp_path),
        ])
        assert rc == 0
        assert "Iterations grouped: 0" in report.read_text()


# ── operator commands ─────────────────────────────────────────────


@pytest_asyncio.fixture
async def cmd_handler(migrated_db, message_queue, session_manager):
    return CommandHandler(
        db=migrated_db,
        queue=message_queue,
        session_manager=session_manager,
        claude_runner=None,
    )


class TestExperimentFinalizeCommand:
    @pytest.mark.asyncio
    async def test_disabled_flag_returns_helpful_message(
        self, cmd_handler, monkeypatch
    ):
        # Spoof load_config returning a config with the flag off.
        from bridge import config as cfg_mod
        fake_cfg = MagicMock(experiment_finalize_enabled=False)
        monkeypatch.setattr(cfg_mod, "load_config", lambda *a, **kw: fake_cfg)
        out = await cmd_handler.handle("chat-1", "experiment_finalize", "")
        assert "experiment_finalize_enabled" in out
        assert "bridge.toml" in out

    @pytest.mark.asyncio
    async def test_happy_path_runs_subprocess(
        self, cmd_handler, monkeypatch, tmp_path: Path
    ):
        from bridge import config as cfg_mod
        fake_cfg = MagicMock(experiment_finalize_enabled=True)
        monkeypatch.setattr(cfg_mod, "load_config", lambda *a, **kw: fake_cfg)

        # Stub subprocess: return rc=0.
        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.communicate = AsyncMock(return_value=(b"ok\n", b""))

        async def _spawn(*args, **kwargs):
            return fake_proc

        monkeypatch.setattr(
            "asyncio.create_subprocess_exec", _spawn,
        )

        # Place a fake report next to the test DB so the handler finds it.
        db_path = Path(cmd_handler._db.db_path)
        report = db_path.parent / "experiments-finalize-20260501T000000.md"
        report.write_text(
            "# Experiment finalize report\n\n"
            "- Window start: x\n- Iterations grouped: 4\n- Branches created: 2\n"
        )

        out = await cmd_handler.handle("chat-1", "experiment_finalize", "")
        assert "Experiment finalize complete" in out
        assert "Branches created" in out

    @pytest.mark.asyncio
    async def test_status_lists_branches(
        self, cmd_handler, monkeypatch
    ):
        # Stub subprocess.run for git for-each-ref.
        fake = MagicMock()
        fake.stdout = (
            "experiment-finalize/agent\tdeadbeef\n"
            "experiment-finalize/CONFLICT-tests\tcafebabe\n"
        )
        fake.returncode = 0
        monkeypatch.setattr(
            "subprocess.run", lambda *a, **kw: fake,
        )

        out = await cmd_handler.handle(
            "chat-1", "experiment_finalize_status", "",
        )
        assert "Experiment-finalize branches" in out
        assert "experiment-finalize/agent" in out
        assert "(CONFLICT)" in out

    @pytest.mark.asyncio
    async def test_status_when_no_branches(self, cmd_handler, monkeypatch):
        fake = MagicMock()
        fake.stdout = ""
        fake.returncode = 0
        monkeypatch.setattr(
            "subprocess.run", lambda *a, **kw: fake,
        )
        out = await cmd_handler.handle(
            "chat-1", "experiment_finalize_status", "",
        )
        assert "0" in out
        assert "(none)" in out
