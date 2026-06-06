"""Tests for the experiment-loop ↔ worker mailbox wiring (Sprint 15.02, issue #1052).

Spec: ``docs/specs/2026-04-25-reference-audit/spec-15-02-wire-mailbox-into-experimentloop-worktree-boundary-plan-02.md``

Covers:
- Worker-side helpers in ``agent/scripts/experiment_mailbox_worker.py``
- Bridge-side wiring in ``agent/scripts/experiment_loop.py`` (env-var
  contract, drain on subprocess exit, default-OFF regression).

The mailbox primitive itself is exercised by ``tests/test_mailbox.py``;
this file pins the **integration contract** between the two scripts.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

# Make ``scripts/`` importable so the worker module + experiment_loop
# can be exercised directly.
_AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AGENT_DIR))
sys.path.insert(0, str(_AGENT_DIR / "scripts"))

import experiment_mailbox_worker as worker  # noqa: E402
from bridge.mailbox import Mailbox, MailboxConfig  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_worker_state(monkeypatch):
    """Reset module-level cache before each test so env-var changes take effect."""
    worker._reset_for_tests()
    # Strip any inherited mailbox env vars so default-OFF tests are pristine.
    monkeypatch.delenv(worker.ENV_MAILBOX_NAME, raising=False)
    monkeypatch.delenv(worker.ENV_MAILBOX_DATA_DIR, raising=False)
    yield
    worker._reset_for_tests()


@pytest.fixture
def mbox_dir(tmp_path: Path) -> Path:
    return tmp_path / "mbox-data"


@pytest.fixture
def config(mbox_dir: Path) -> MailboxConfig:
    return MailboxConfig(name="test_experiment_loop", data_dir=mbox_dir)


@pytest.fixture
def bridge_mailbox(config: MailboxConfig) -> Mailbox:
    mb = Mailbox(config, role="bridge")
    mb.init_db()
    yield mb
    mb.close()


@pytest.fixture
def env_setup(monkeypatch, config: MailboxConfig):
    """Set the env vars the worker module reads."""
    monkeypatch.setenv(worker.ENV_MAILBOX_NAME, config.name)
    monkeypatch.setenv(worker.ENV_MAILBOX_DATA_DIR, str(config.data_dir))


# ---------------------------------------------------------------------------
# get_worker_mailbox
# ---------------------------------------------------------------------------


def test_get_worker_mailbox_with_env(env_setup, config: MailboxConfig):
    mbox = worker.get_worker_mailbox()
    assert mbox is not None
    assert isinstance(mbox, Mailbox)
    assert mbox.role == "worker"
    assert mbox.config.name == config.name


def test_get_worker_mailbox_without_env_returns_none():
    # _reset_worker_state already stripped the env vars.
    assert worker.get_worker_mailbox() is None


def test_get_worker_mailbox_caches_instance(env_setup):
    first = worker.get_worker_mailbox()
    second = worker.get_worker_mailbox()
    assert first is second


def test_get_worker_mailbox_caches_negative_lookup(monkeypatch):
    # First call: env absent → returns None.
    assert worker.get_worker_mailbox() is None
    # Even if env is set later, the cache should still return None
    # (the loop-spawned subprocess only ever serves a single iteration;
    # this avoids surprising stateful behavior across calls).
    monkeypatch.setenv(worker.ENV_MAILBOX_NAME, "late")
    assert worker.get_worker_mailbox() is None


# ---------------------------------------------------------------------------
# report_progress / report_intermediate_fitness / report_crash
# ---------------------------------------------------------------------------


def test_report_progress_no_op_when_unavailable():
    # No env → get_worker_mailbox returns None → report_progress must
    # exit before sending. Patch the probe to track the contract.
    with patch.object(worker, "get_worker_mailbox", return_value=None) as mock_get:
        worker.report_progress("anything", pct=42)
        mock_get.assert_called_once()


def test_report_progress_sends_correct_payload(env_setup, bridge_mailbox: Mailbox):
    worker.report_progress("ran pytest, all green", pct=70)

    msgs = bridge_mailbox.read_since(after_seq=0)
    assert len(msgs) == 1
    payload = msgs[0].payload
    assert payload["kind"] == "progress"
    assert payload["message"] == "ran pytest, all green"
    assert payload["pct"] == 70
    assert msgs[0].direction == "worker_to_bridge"


def test_report_progress_omits_pct_when_none(env_setup, bridge_mailbox: Mailbox):
    worker.report_progress("phase started")
    msgs = bridge_mailbox.read_since(after_seq=0)
    assert len(msgs) == 1
    assert "pct" not in msgs[0].payload
    assert msgs[0].payload["message"] == "phase started"


def test_report_intermediate_fitness_round_trip(env_setup, bridge_mailbox: Mailbox):
    worker.report_intermediate_fitness(0.83, sample_count=12)
    msgs = bridge_mailbox.read_since(after_seq=0)
    assert len(msgs) == 1
    payload = msgs[0].payload
    assert payload["kind"] == "intermediate_fitness"
    assert payload["value"] == pytest.approx(0.83)
    assert payload["sample_count"] == 12


def test_report_crash_payload_includes_traceback(env_setup, bridge_mailbox: Mailbox):
    worker.report_crash("ValueError", "bad input", "Traceback:\n  line 1\n  line 2")
    msgs = bridge_mailbox.read_since(after_seq=0)
    assert len(msgs) == 1
    payload = msgs[0].payload
    assert payload["kind"] == "crash"
    assert payload["error_type"] == "ValueError"
    assert payload["message"] == "bad input"
    assert "line 1" in payload["traceback"]


def test_report_crash_no_op_when_unavailable():
    # Same no-op contract as report_progress.
    with patch.object(worker, "get_worker_mailbox", return_value=None) as mock_get:
        worker.report_crash("RuntimeError", "boom")
        mock_get.assert_called_once()


# ---------------------------------------------------------------------------
# check_cancel
# ---------------------------------------------------------------------------


def test_check_cancel_false_when_no_cancel_sent(env_setup, bridge_mailbox: Mailbox):
    # Bridge sends an unrelated message — should not flip cancel.
    bridge_mailbox.send({"kind": "budget_warning", "remaining_usd": 0.1})
    assert worker.check_cancel() is False


def test_check_cancel_true_after_bridge_sends_cancel(
    env_setup, bridge_mailbox: Mailbox
):
    bridge_mailbox.send({"kind": "cancel", "reason": "operator-halt"})
    assert worker.check_cancel() is True


def test_check_cancel_idempotent_after_first_true(env_setup, bridge_mailbox: Mailbox):
    bridge_mailbox.send({"kind": "cancel"})
    assert worker.check_cancel() is True
    # Second call must not re-read SQLite — cached path returns True.
    assert worker.check_cancel() is True


def test_check_cancel_returns_false_without_mailbox():
    # No env, no mailbox.
    assert worker.check_cancel() is False


def test_check_cancel_advances_cursor_past_unrelated_messages(
    env_setup, bridge_mailbox: Mailbox
):
    bridge_mailbox.send({"kind": "budget_warning"})
    bridge_mailbox.send({"kind": "info"})
    assert worker.check_cancel() is False
    # Cursor should now be at seq=2 (or whatever the latest seq was).
    assert worker._last_cancel_check_seq >= 2
    bridge_mailbox.send({"kind": "cancel"})
    assert worker.check_cancel() is True


# ---------------------------------------------------------------------------
# Integration: bridge env wiring + worker drain
# ---------------------------------------------------------------------------


def test_integration_bridge_opens_then_worker_uses_it(env_setup, bridge_mailbox: Mailbox):
    """Bridge opens mailbox + sets env; worker uses it; bridge reads progress.

    Mirrors the contract between ``experiment_loop.run_experiment`` and
    ``experiment_mailbox_worker.report_progress`` without spawning an
    actual subprocess.
    """
    # Worker reports several events in sequence.
    worker.report_progress("step 1", pct=25)
    worker.report_progress("step 2", pct=50)
    worker.report_intermediate_fitness(0.71, sample_count=5)
    worker.report_progress("done", pct=100)

    # Bridge drains.
    msgs = bridge_mailbox.read_since(after_seq=0)
    assert len(msgs) == 4
    kinds = [m.payload["kind"] for m in msgs]
    assert kinds == [
        "progress",
        "progress",
        "intermediate_fitness",
        "progress",
    ]


# ---------------------------------------------------------------------------
# Vacuum bound
# ---------------------------------------------------------------------------


def test_vacuum_keeps_outbound_table_bounded(env_setup, config: MailboxConfig):
    """After many writes + vacuum, the worker DB stays bounded."""
    mb = worker.get_worker_mailbox()
    assert mb is not None
    for i in range(50):
        worker.report_progress(f"tick {i}")

    deleted = mb.vacuum(keep_last_n=10)
    assert deleted >= 40  # 50 - 10

    # Read everything from the bridge side; should be at most 10 rows now
    bridge = Mailbox(config, role="bridge")
    bridge.init_db()
    try:
        msgs = bridge.read_since(after_seq=0, limit=1000)
        assert len(msgs) <= 10
    finally:
        bridge.close()


# ---------------------------------------------------------------------------
# Concurrency: bridge cancel + worker progress writes
# ---------------------------------------------------------------------------


def test_concurrent_bridge_cancel_and_worker_progress(
    env_setup, bridge_mailbox: Mailbox
):
    """Bridge sends cancel while worker writes progress — no corruption."""
    errors: list[Exception] = []

    def writer():
        try:
            for i in range(20):
                worker.report_progress(f"step {i}")
        except Exception as exc:
            errors.append(exc)

    def canceler():
        try:
            bridge_mailbox.send({"kind": "cancel"})
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=writer)
    t2 = threading.Thread(target=canceler)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f"concurrent ops raised: {errors}"
    # Worker side: 20 progress messages written
    msgs = bridge_mailbox.read_since(after_seq=0, limit=100)
    assert len(msgs) == 20
    assert all(m.payload["kind"] == "progress" for m in msgs)
    # Cancel landed on the bridge side — worker can observe it.
    assert worker.check_cancel() is True


# ---------------------------------------------------------------------------
# experiment_loop.run_experiment env-var contract
# ---------------------------------------------------------------------------


def test_run_experiment_sets_mailbox_env_when_provided(
    monkeypatch, tmp_path: Path
):
    """When a Mailbox is passed, run_experiment must export the env vars.

    Verifies the bridge-side end of the contract that
    ``experiment_mailbox_worker.get_worker_mailbox`` relies on. We patch
    ``subprocess.run`` so no real ``claude -p`` is spawned and inspect
    the ``env`` dict the loop would have exported.
    """
    import experiment_loop  # noqa: E402

    captured_env: dict[str, str] = {}

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, *args, **kwargs):
        # First call is `git worktree add`; second is `claude -p`. We
        # only care about the second — its env carries the mailbox vars.
        env = kwargs.get("env") or {}
        if cmd and cmd[0] == str(experiment_loop.CLAUDE_BIN):
            captured_env.update(env)
        return _Result()

    monkeypatch.setattr(experiment_loop.subprocess, "run", fake_run)
    # Stub out file-system bits the test doesn't need.
    monkeypatch.setattr(experiment_loop, "_load_oauth_token", lambda: "")
    fake_program = type(
        "P",
        (),
        {"apply_prompt": staticmethod(lambda d, f: "stub-prompt")},
    )()
    monkeypatch.setattr(
        experiment_loop,
        "WORKTREE_BASE",
        tmp_path / "worktrees",
    )

    # Patch the local import of LoopProgram inside run_experiment.
    import _loop_program  # noqa: E402

    monkeypatch.setattr(
        _loop_program.LoopProgram, "from_markdown", staticmethod(lambda p: fake_program)
    )

    cfg = MailboxConfig(name="test_run_experiment", data_dir=tmp_path / "mbox")
    mb = Mailbox(cfg, role="bridge")
    mb.init_db()
    try:
        exp = experiment_loop.run_experiment(
            "stub description", iter_id="iter-test", mailbox=mb
        )
    finally:
        mb.close()

    assert captured_env.get(worker.ENV_MAILBOX_NAME) == cfg.name
    assert captured_env.get(worker.ENV_MAILBOX_DATA_DIR) == str(cfg.data_dir)
    assert exp["mailbox_messages"] == []  # subprocess never wrote anything


def test_run_experiment_default_off_does_not_set_env(monkeypatch, tmp_path: Path):
    """Regression: with mailbox=None (default), env must NOT carry mailbox vars.

    Pins the contract that ``experiment_mailbox_enabled=False`` keeps
    current behavior unchanged — the worker side helpers see no env vars
    and silently no-op.
    """
    import experiment_loop  # noqa: E402

    captured_env: dict[str, str] = {}

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, *args, **kwargs):
        env = kwargs.get("env") or {}
        if cmd and cmd[0] == str(experiment_loop.CLAUDE_BIN):
            captured_env.update(env)
        return _Result()

    monkeypatch.setattr(experiment_loop.subprocess, "run", fake_run)
    monkeypatch.setattr(experiment_loop, "_load_oauth_token", lambda: "")
    monkeypatch.setattr(experiment_loop, "WORKTREE_BASE", tmp_path / "worktrees")

    fake_program = type(
        "P",
        (),
        {"apply_prompt": staticmethod(lambda d, f: "stub-prompt")},
    )()
    import _loop_program  # noqa: E402

    monkeypatch.setattr(
        _loop_program.LoopProgram, "from_markdown", staticmethod(lambda p: fake_program)
    )

    exp = experiment_loop.run_experiment("stub description", iter_id="iter-test")

    # Mailbox env vars MUST NOT be set when the feature is off (default).
    assert worker.ENV_MAILBOX_NAME not in captured_env
    assert worker.ENV_MAILBOX_DATA_DIR not in captured_env
    # The result still carries the new key (empty) so log_result's plumbing
    # doesn't KeyError; this is a defensive default, not a behavior change.
    assert exp.get("mailbox_messages") == []


def test_load_mailbox_settings_default_off():
    """When config import fails (or flag absent), feature degrades to OFF."""
    import experiment_loop  # noqa: E402

    enabled, poll, vacuum = experiment_loop._load_mailbox_settings()
    # Default OFF — the operator opts in via bridge.toml.
    assert enabled is False
    # Defaults match BridgeConfig field defaults.
    assert poll == 2
    assert vacuum == 5000
