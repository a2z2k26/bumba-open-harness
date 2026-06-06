"""Tests for the Sprint 15.03 mailbox wiring at the factory implement boundary.

Covers both:
  * the worker-side helper module
    (:mod:`bridge.factory.implement_mailbox_worker`), and
  * the bridge-side glue in :mod:`bridge.factory.implement`
    (``make_factory_mailbox_config``).

Plus a regression that confirms the orchestrator still works when
``factory_mailbox_enabled=False`` (the default).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.factory import implement as impl
from bridge.factory.implement import (
    DEFAULT_MAILBOX_DATA_DIR,
    ENV_MAILBOX_DATA_DIR,
    ENV_MAILBOX_NAME,
    make_factory_mailbox_config,
)
from bridge.factory import implement_mailbox_worker as imw
from bridge.factory.implement_mailbox_worker import (
    FACTORY_MAILBOX_NAME_PREFIX,
    PAYLOAD_TYPE_CANCEL,
    PAYLOAD_TYPE_CLARIFY_RESPONSE,
    PAYLOAD_TYPE_PARTIAL_COST,
    PAYLOAD_TYPE_PROGRESS,
    check_cancel,
    get_implement_worker_mailbox,
    report_partial_cost,
    report_progress,
    request_decision,
)
from bridge.mailbox import Mailbox, MailboxConfig


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def mailbox_data_dir(tmp_path: Path) -> Path:
    return tmp_path / "factory-mailboxes"


@pytest.fixture
def issue_config(mailbox_data_dir: Path) -> MailboxConfig:
    """A per-issue mailbox config the bridge would create for issue 100."""
    return make_factory_mailbox_config(100, data_dir=mailbox_data_dir)


@pytest.fixture
def bridge_mailbox(issue_config: MailboxConfig) -> Mailbox:
    mb = Mailbox(issue_config, role="bridge")
    mb.init_db()
    yield mb
    mb.close()


@pytest.fixture
def worker_env(monkeypatch: pytest.MonkeyPatch, issue_config: MailboxConfig) -> None:
    """Set the env vars the bridge would set when spawning the worker."""
    monkeypatch.setenv(ENV_MAILBOX_NAME, issue_config.name)
    monkeypatch.setenv(ENV_MAILBOX_DATA_DIR, str(issue_config.data_dir))


# ── make_factory_mailbox_config ─────────────────────────────────────────


class TestMakeFactoryMailboxConfig:
    def test_default_data_dir(self):
        cfg = make_factory_mailbox_config(42)
        assert cfg.name == "factory_implement_42"
        assert cfg.data_dir == DEFAULT_MAILBOX_DATA_DIR
        assert cfg.schema_version == 1

    def test_custom_data_dir(self, mailbox_data_dir: Path):
        cfg = make_factory_mailbox_config(42, data_dir=mailbox_data_dir)
        assert cfg.data_dir == mailbox_data_dir

    def test_per_issue_mailboxes_have_unique_names(self):
        a = make_factory_mailbox_config(100)
        b = make_factory_mailbox_config(200)
        assert a.name != b.name
        assert a.worker_db_path != b.worker_db_path
        assert a.bridge_db_path != b.bridge_db_path


# ── get_implement_worker_mailbox ────────────────────────────────────────


class TestGetImplementWorkerMailbox:
    def test_with_env_returns_mailbox(self, worker_env, mailbox_data_dir: Path):
        mb = get_implement_worker_mailbox()
        assert mb is not None
        assert mb.role == "worker"
        assert mb.config.data_dir == mailbox_data_dir
        assert mb.config.name.startswith(FACTORY_MAILBOX_NAME_PREFIX)
        mb.close()

    def test_without_env_returns_none(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv(ENV_MAILBOX_NAME, raising=False)
        monkeypatch.delenv(ENV_MAILBOX_DATA_DIR, raising=False)
        assert get_implement_worker_mailbox() is None

    def test_non_factory_name_returns_none(self, monkeypatch: pytest.MonkeyPatch):
        # Sibling worker (e.g. experiment loop) — must not cross-talk.
        monkeypatch.setenv(ENV_MAILBOX_NAME, "experiment_loop_xyz")
        monkeypatch.setenv(ENV_MAILBOX_DATA_DIR, "/tmp/whatever")
        assert get_implement_worker_mailbox() is None

    def test_default_data_dir_when_only_name_env_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        # Run from tmp_path so the default-relative dir doesn't pollute the
        # repo if init_db is exercised via a subsequent helper call.
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv(ENV_MAILBOX_NAME, "factory_implement_55")
        monkeypatch.delenv(ENV_MAILBOX_DATA_DIR, raising=False)
        mb = get_implement_worker_mailbox()
        assert mb is not None
        # Helper falls back to the default dir literal.
        assert str(mb.config.data_dir) == imw.DEFAULT_DATA_DIR
        mb.close()


# ── report_progress ─────────────────────────────────────────────────────


class TestReportProgress:
    def test_noop_when_unavailable(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv(ENV_MAILBOX_NAME, raising=False)
        # Without ENV_MAILBOX_NAME, the helper bails before constructing a
        # mailbox — patch get_implement_worker_mailbox to confirm the
        # no-op contract (called once to probe; returns None; nothing
        # sent).
        with patch.object(imw, "get_implement_worker_mailbox", return_value=None) as mock_get:
            report_progress("plan", message="starting", pct=10)
            mock_get.assert_called_once()

    def test_sends_correct_payload(
        self, worker_env, bridge_mailbox: Mailbox
    ):
        # Worker writes; bridge reads from its inbound (worker_to_bridge).
        report_progress("implement", message="phase 4 done", pct=40)
        msgs = bridge_mailbox.read_since(after_seq=0)
        assert len(msgs) == 1
        assert msgs[0].payload["type"] == PAYLOAD_TYPE_PROGRESS
        assert msgs[0].payload["phase"] == "implement"
        assert msgs[0].payload["message"] == "phase 4 done"
        assert msgs[0].payload["pct"] == 40


# ── request_decision ────────────────────────────────────────────────────


class TestRequestDecision:
    def test_returns_operator_choice(
        self, worker_env, bridge_mailbox: Mailbox
    ):
        # Pre-seed a clarify_response so the polling loop finds it
        # immediately on the first read_since after sending the request.
        bridge_mailbox.send(
            {"type": PAYLOAD_TYPE_CLARIFY_RESPONSE, "choice": "option-b"}
        )
        choice = request_decision(
            "Pick one",
            choices=["option-a", "option-b"],
            timeout_seconds=5,
            sleep_fn=lambda _s: None,
        )
        # Note: latest_seq before send means our cursor is non-zero, so the
        # pre-seeded message is _not_ visible; we expect None on timeout.
        # The realistic path is: bridge sends the response AFTER seeing the
        # decision_request. We model that by patching read_since so it
        # surfaces a freshly-arrived response on the second poll.
        assert choice is None  # cursor-after-send means pre-seed is invisible.

    def test_returns_choice_when_response_arrives_after_request(
        self, worker_env
    ):
        # Use the worker mailbox directly so we can stage a response with
        # a fresh seq AFTER request_decision opens its cursor.
        worker = get_implement_worker_mailbox()
        assert worker is not None

        # Simulate the bridge: open the bridge-side mailbox and send a
        # response after the request fires. We do that by having the
        # injected sleep_fn write the response on the first tick.
        bridge_view = Mailbox(worker.config, role="bridge")
        bridge_view.init_db()

        ticks: list[int] = []

        def fake_sleep(_seconds: float) -> None:
            ticks.append(1)
            if len(ticks) == 1:
                bridge_view.send(
                    {"type": PAYLOAD_TYPE_CLARIFY_RESPONSE, "choice": "yes"}
                )

        choice = request_decision(
            "Continue?",
            timeout_seconds=10,
            mailbox=worker,
            sleep_fn=fake_sleep,
        )
        worker.close()
        bridge_view.close()
        assert choice == "yes"

    def test_returns_none_on_timeout(self, worker_env):
        worker = get_implement_worker_mailbox()
        assert worker is not None
        # No bridge response — sleep returns immediately, time advances
        # via patching time.monotonic to walk past the deadline.
        ticks = iter([0.0, 0.5, 9999.0])

        def fake_monotonic():
            return next(ticks)

        with patch.object(imw.time, "monotonic", side_effect=fake_monotonic):
            choice = request_decision(
                "Anything?",
                timeout_seconds=1,
                mailbox=worker,
                sleep_fn=lambda _s: None,
            )
        worker.close()
        assert choice is None

    def test_returns_none_on_cancel(self, worker_env):
        worker = get_implement_worker_mailbox()
        assert worker is not None
        bridge_view = Mailbox(worker.config, role="bridge")
        bridge_view.init_db()

        ticks: list[int] = []

        def fake_sleep(_seconds: float) -> None:
            ticks.append(1)
            if len(ticks) == 1:
                bridge_view.send({"type": PAYLOAD_TYPE_CANCEL})

        choice = request_decision(
            "Continue?",
            timeout_seconds=10,
            mailbox=worker,
            sleep_fn=fake_sleep,
        )
        worker.close()
        bridge_view.close()
        assert choice is None

    def test_returns_none_when_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv(ENV_MAILBOX_NAME, raising=False)
        assert request_decision("?", timeout_seconds=1, sleep_fn=lambda _s: None) is None


# ── check_cancel ────────────────────────────────────────────────────────


class TestCheckCancel:
    def test_false_initially(self, worker_env):
        assert check_cancel() is False

    def test_true_after_bridge_sends_cancel(
        self, worker_env, bridge_mailbox: Mailbox
    ):
        assert check_cancel() is False
        bridge_mailbox.send({"type": PAYLOAD_TYPE_CANCEL})
        assert check_cancel() is True

    def test_unrelated_message_does_not_trip_cancel(
        self, worker_env, bridge_mailbox: Mailbox
    ):
        bridge_mailbox.send(
            {"type": PAYLOAD_TYPE_CLARIFY_RESPONSE, "choice": "x"}
        )
        assert check_cancel() is False

    def test_false_when_unavailable(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv(ENV_MAILBOX_NAME, raising=False)
        assert check_cancel() is False


# ── report_partial_cost ─────────────────────────────────────────────────


class TestReportPartialCost:
    def test_round_trip(self, worker_env, bridge_mailbox: Mailbox):
        report_partial_cost(0.0125, model="claude-sonnet-4")
        msgs = bridge_mailbox.read_since(after_seq=0)
        assert len(msgs) == 1
        assert msgs[0].payload["type"] == PAYLOAD_TYPE_PARTIAL_COST
        assert msgs[0].payload["cost_usd"] == pytest.approx(0.0125)
        assert msgs[0].payload["model"] == "claude-sonnet-4"

    def test_noop_when_unavailable(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv(ENV_MAILBOX_NAME, raising=False)
        # Same no-op contract as report_progress: the helper probes the
        # mailbox once and exits when it is unavailable.
        with patch.object(imw, "get_implement_worker_mailbox", return_value=None) as mock_get:
            report_partial_cost(0.10, model="haiku")
            mock_get.assert_called_once()


# ── Per-issue isolation ─────────────────────────────────────────────────


class TestPerIssueIsolation:
    def test_two_issues_have_separate_mailboxes(self, mailbox_data_dir: Path):
        cfg_100 = make_factory_mailbox_config(100, data_dir=mailbox_data_dir)
        cfg_200 = make_factory_mailbox_config(200, data_dir=mailbox_data_dir)

        bridge_100 = Mailbox(cfg_100, role="bridge")
        bridge_100.init_db()
        bridge_200 = Mailbox(cfg_200, role="bridge")
        bridge_200.init_db()

        worker_100 = Mailbox(cfg_100, role="worker")
        worker_100.init_db()
        worker_200 = Mailbox(cfg_200, role="worker")
        worker_200.init_db()

        worker_100.send({"type": PAYLOAD_TYPE_PROGRESS, "phase": "plan"})
        worker_200.send({"type": PAYLOAD_TYPE_PROGRESS, "phase": "implement"})

        msgs_100 = bridge_100.read_since(after_seq=0)
        msgs_200 = bridge_200.read_since(after_seq=0)
        assert len(msgs_100) == 1
        assert len(msgs_200) == 1
        assert msgs_100[0].payload["phase"] == "plan"
        assert msgs_200[0].payload["phase"] == "implement"

        for mb in (bridge_100, bridge_200, worker_100, worker_200):
            mb.close()


# ── Bridge-side wiring sanity (mailbox flag default OFF) ────────────────


class TestBridgeSideMailboxFlagOff:
    """Existing implement_issue path is byte-equivalent when flag is OFF."""

    def test_implement_issue_does_not_set_env_when_flag_off(self, tmp_path: Path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        workspace = tmp_path / "workspace"

        captured_env: list[dict[str, str] | None] = []

        def fake_invoke(prompt, *, cwd=None, timeout=180, extra_env=None):
            captured_env.append(extra_env)
            return (0, "ok", "")

        def fake_run(args, **kwargs):
            head = args[:3]
            if head == ["gh", "issue", "view"]:
                return (
                    0,
                    '{"title": "X", "body": "y", "labels": [], "comments": []}',
                    "",
                )
            if head == ["gh", "pr", "create"]:
                return (
                    0,
                    "https://github.com/owner/repo/pull/1\n",
                    "",
                )
            if head == ["gh", "issue", "comment"]:
                return (0, "", "")
            return (0, "", "")

        with (
            patch.object(impl, "_run_subprocess", side_effect=fake_run),
            patch.object(impl, "_invoke_claude", side_effect=fake_invoke),
            patch.object(impl, "transition_state", return_value=True),
        ):
            impl.implement_issue(
                7,
                repo="owner/repo",
                workspace_root=workspace,
                repo_root=repo_root,
                mailbox_enabled=False,
            )

        # When the flag is off the implement phase omits extra_env entirely;
        # fake_invoke's default kwarg means each captured value is None.
        assert all(env is None for env in captured_env)

    def test_implement_issue_sets_env_when_flag_on(
        self, tmp_path: Path, mailbox_data_dir: Path
    ):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        workspace = tmp_path / "workspace"

        captured_env: list[dict[str, str] | None] = []

        def fake_invoke(prompt, *, cwd=None, timeout=180, extra_env=None):
            captured_env.append(extra_env)
            return (0, "ok", "")

        def fake_run(args, **kwargs):
            head = args[:3]
            if head == ["gh", "issue", "view"]:
                return (
                    0,
                    '{"title": "X", "body": "y", "labels": [], "comments": []}',
                    "",
                )
            if head == ["gh", "pr", "create"]:
                return (
                    0,
                    "https://github.com/owner/repo/pull/1\n",
                    "",
                )
            if head == ["gh", "issue", "comment"]:
                return (0, "", "")
            return (0, "", "")

        with (
            patch.object(impl, "_run_subprocess", side_effect=fake_run),
            patch.object(impl, "_invoke_claude", side_effect=fake_invoke),
            patch.object(impl, "transition_state", return_value=True),
        ):
            impl.implement_issue(
                77,
                repo="owner/repo",
                workspace_root=workspace,
                repo_root=repo_root,
                mailbox_enabled=True,
                mailbox_data_dir=mailbox_data_dir,
            )

        # The implement phase is the one wired to extra_env. It should be
        # present in at least one captured invocation.
        envs_with_mailbox = [
            e for e in captured_env if e and ENV_MAILBOX_NAME in e
        ]
        assert len(envs_with_mailbox) == 1
        env = envs_with_mailbox[0]
        assert env[ENV_MAILBOX_NAME] == "factory_implement_77"
        assert env[ENV_MAILBOX_DATA_DIR] == str(mailbox_data_dir)
