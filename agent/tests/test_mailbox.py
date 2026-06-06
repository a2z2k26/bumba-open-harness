"""Tests for ``bridge.mailbox`` — dual-DB single-writer subprocess primitive."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from bridge.mailbox import (
    Mailbox,
    MailboxConfig,
    MailboxMessage,
    open_mailbox,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mailbox_dir(tmp_path: Path) -> Path:
    return tmp_path / "mbox-data"


@pytest.fixture
def config(mailbox_dir: Path) -> MailboxConfig:
    return MailboxConfig(name="test_loop", data_dir=mailbox_dir)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


def test_config_paths_use_role_suffix(config: MailboxConfig, mailbox_dir: Path):
    assert config.worker_db_path == mailbox_dir / "test_loop-mbox-worker.sqlite"
    assert config.bridge_db_path == mailbox_dir / "test_loop-mbox-bridge.sqlite"


# ---------------------------------------------------------------------------
# init / lifecycle
# ---------------------------------------------------------------------------


def test_init_db_idempotent(config: MailboxConfig):
    mb = Mailbox(config, role="bridge")
    mb.init_db()
    mb.init_db()  # second call must not raise
    assert config.bridge_db_path.exists()
    mb.close()


def test_init_db_sets_wal_mode(config: MailboxConfig):
    mb = Mailbox(config, role="bridge")
    mb.init_db()
    with sqlite3.connect(config.bridge_db_path) as conn:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    assert mode.lower() == "wal"
    mb.close()


def test_invalid_role_raises(config: MailboxConfig):
    with pytest.raises(ValueError):
        Mailbox(config, role="other")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# direction routing per role
# ---------------------------------------------------------------------------


def test_bridge_send_writes_to_bridge_db(config: MailboxConfig):
    bridge = Mailbox(config, role="bridge")
    bridge.init_db()
    bridge.send({"hello": "from-bridge"})
    bridge.close()

    assert config.bridge_db_path.exists()
    # Worker DB not yet created.
    assert not config.worker_db_path.exists()

    with sqlite3.connect(config.bridge_db_path) as conn:
        rows = conn.execute(
            "SELECT direction, payload FROM mailbox_messages"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "bridge_to_worker"


def test_worker_send_writes_to_worker_db(config: MailboxConfig):
    worker = Mailbox(config, role="worker")
    worker.init_db()
    worker.send({"hello": "from-worker"})
    worker.close()

    assert config.worker_db_path.exists()
    assert not config.bridge_db_path.exists()

    with sqlite3.connect(config.worker_db_path) as conn:
        rows = conn.execute(
            "SELECT direction, payload FROM mailbox_messages"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "worker_to_bridge"


# ---------------------------------------------------------------------------
# send semantics
# ---------------------------------------------------------------------------


def test_send_returns_monotonic_seqs(config: MailboxConfig):
    bridge = Mailbox(config, role="bridge")
    bridge.init_db()
    seqs = [bridge.send({"i": i}) for i in range(5)]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == 5
    bridge.close()


def test_send_non_serializable_payload_raises(config: MailboxConfig):
    bridge = Mailbox(config, role="bridge")
    bridge.init_db()
    with pytest.raises(ValueError):
        bridge.send({"bad": object()})
    bridge.close()


# ---------------------------------------------------------------------------
# read_since
# ---------------------------------------------------------------------------


def test_read_since_returns_first_n_in_seq_order(config: MailboxConfig):
    bridge = Mailbox(config, role="bridge")
    worker = Mailbox(config, role="worker")
    bridge.init_db()
    worker.init_db()

    for i in range(15):
        bridge.send({"i": i})

    msgs = worker.read_since(after_seq=0, limit=10)
    assert len(msgs) == 10
    assert [m.payload["i"] for m in msgs] == list(range(10))
    assert all(m.direction == "bridge_to_worker" for m in msgs)
    seqs = [m.seq for m in msgs]
    assert seqs == sorted(seqs)

    bridge.close()
    worker.close()


def test_read_since_with_cursor_excludes_seen(config: MailboxConfig):
    bridge = Mailbox(config, role="bridge")
    worker = Mailbox(config, role="worker")
    bridge.init_db()
    worker.init_db()

    seqs = [bridge.send({"i": i}) for i in range(5)]
    cutoff = seqs[2]
    msgs = worker.read_since(after_seq=cutoff, limit=100)
    assert [m.seq for m in msgs] == seqs[3:]

    bridge.close()
    worker.close()


def test_read_since_missing_inbound_db_returns_empty(config: MailboxConfig):
    # bridge has not initialized yet — worker reads nothing rather than crashing.
    worker = Mailbox(config, role="worker")
    worker.init_db()
    msgs = worker.read_since(after_seq=0)
    assert msgs == []
    worker.close()


def test_read_since_zero_or_negative_limit_returns_empty(config: MailboxConfig):
    bridge = Mailbox(config, role="bridge")
    worker = Mailbox(config, role="worker")
    bridge.init_db()
    worker.init_db()
    bridge.send({"i": 1})

    assert worker.read_since(after_seq=0, limit=0) == []
    assert worker.read_since(after_seq=0, limit=-3) == []

    bridge.close()
    worker.close()


# ---------------------------------------------------------------------------
# round-trip
# ---------------------------------------------------------------------------


def test_round_trip_bridge_to_worker(config: MailboxConfig):
    bridge = Mailbox(config, role="bridge")
    worker = Mailbox(config, role="worker")
    bridge.init_db()
    worker.init_db()

    seq = bridge.send({"command": "stop", "arg": 42})
    msgs = worker.read_since()

    assert len(msgs) == 1
    msg = msgs[0]
    assert isinstance(msg, MailboxMessage)
    assert msg.seq == seq
    assert msg.direction == "bridge_to_worker"
    assert msg.payload == {"command": "stop", "arg": 42}
    assert msg.correlation_id is None
    # ISO-8601 timestamp present
    assert "T" in msg.enqueued_at_iso

    bridge.close()
    worker.close()


def test_round_trip_correlation_id_preserved(config: MailboxConfig):
    bridge = Mailbox(config, role="bridge")
    worker = Mailbox(config, role="worker")
    bridge.init_db()
    worker.init_db()

    bridge.send({"x": 1}, correlation_id="req-abc-123")
    msg = worker.read_since()[0]
    assert msg.correlation_id == "req-abc-123"

    bridge.close()
    worker.close()


def test_round_trip_worker_to_bridge(config: MailboxConfig):
    bridge = Mailbox(config, role="bridge")
    worker = Mailbox(config, role="worker")
    bridge.init_db()
    worker.init_db()

    worker.send({"result": "ok"})
    msgs = bridge.read_since()
    assert len(msgs) == 1
    assert msgs[0].payload == {"result": "ok"}
    assert msgs[0].direction == "worker_to_bridge"

    bridge.close()
    worker.close()


# ---------------------------------------------------------------------------
# latest_seq
# ---------------------------------------------------------------------------


def test_latest_seq_returns_highest_inbound(config: MailboxConfig):
    bridge = Mailbox(config, role="bridge")
    worker = Mailbox(config, role="worker")
    bridge.init_db()
    worker.init_db()

    seqs = [bridge.send({"i": i}) for i in range(4)]
    assert worker.latest_seq() == max(seqs)

    bridge.close()
    worker.close()


def test_latest_seq_zero_when_empty(config: MailboxConfig):
    worker = Mailbox(config, role="worker")
    worker.init_db()
    assert worker.latest_seq() == 0
    worker.close()


# ---------------------------------------------------------------------------
# vacuum
# ---------------------------------------------------------------------------


def test_vacuum_keeps_last_n(config: MailboxConfig):
    bridge = Mailbox(config, role="bridge")
    bridge.init_db()
    for i in range(10):
        bridge.send({"i": i})

    deleted = bridge.vacuum(keep_last_n=5)
    assert deleted == 5

    with sqlite3.connect(config.bridge_db_path) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM mailbox_messages"
        ).fetchone()
    assert rows[0] == 5

    bridge.close()


def test_vacuum_under_threshold_deletes_nothing(config: MailboxConfig):
    bridge = Mailbox(config, role="bridge")
    bridge.init_db()
    for i in range(3):
        bridge.send({"i": i})
    assert bridge.vacuum(keep_last_n=10) == 0
    bridge.close()


def test_vacuum_negative_threshold_raises(config: MailboxConfig):
    bridge = Mailbox(config, role="bridge")
    bridge.init_db()
    with pytest.raises(ValueError):
        bridge.vacuum(keep_last_n=-1)
    bridge.close()


# ---------------------------------------------------------------------------
# concurrency safety
# ---------------------------------------------------------------------------


def test_cross_role_concurrent_send_and_read_no_corruption(config: MailboxConfig):
    """Bridge writes while worker reads — separate DBs, no contention.

    Verifies the dual-DB design choice: even with overlapping operations across
    roles, we never block or corrupt the other side's DB.
    """
    bridge = Mailbox(config, role="bridge")
    worker = Mailbox(config, role="worker")
    bridge.init_db()
    worker.init_db()

    errors: list[BaseException] = []
    write_done = threading.Event()
    read_seq_counts: list[int] = []

    def writer() -> None:
        try:
            for i in range(200):
                bridge.send({"i": i})
        except BaseException as exc:  # pragma: no cover - exposed via errors
            errors.append(exc)
        finally:
            write_done.set()

    def reader() -> None:
        try:
            cursor = 0
            while not write_done.is_set() or cursor < 200:
                msgs = worker.read_since(after_seq=cursor, limit=50)
                if msgs:
                    cursor = msgs[-1].seq
                    read_seq_counts.append(len(msgs))
                else:
                    time.sleep(0.005)
                if cursor >= 200:
                    break
        except BaseException as exc:  # pragma: no cover - exposed via errors
            errors.append(exc)

    t_w = threading.Thread(target=writer)
    t_r = threading.Thread(target=reader)
    t_w.start()
    t_r.start()
    t_w.join(timeout=10)
    t_r.join(timeout=10)

    assert errors == []
    assert worker.latest_seq() == 200
    bridge.close()
    worker.close()


# ---------------------------------------------------------------------------
# context manager
# ---------------------------------------------------------------------------


def test_open_mailbox_context_manager(config: MailboxConfig):
    with open_mailbox(config, role="bridge") as bridge:
        assert config.bridge_db_path.exists()
        seq = bridge.send({"x": 1})
        assert seq >= 1
    # After exit, sending again on a fresh instance still works.
    with open_mailbox(config, role="worker") as worker:
        msgs = worker.read_since()
        assert len(msgs) == 1
        assert msgs[0].payload == {"x": 1}


# ---------------------------------------------------------------------------
# perf smoke
# ---------------------------------------------------------------------------


def test_perf_5k_round_trip(config: MailboxConfig):
    """5,000 round-trip messages should complete under 4 seconds.

    Threshold deliberately above the 2s target to absorb shared-CI variance.
    """
    bridge = Mailbox(config, role="bridge")
    worker = Mailbox(config, role="worker")
    bridge.init_db()
    worker.init_db()

    start = time.perf_counter()
    for i in range(5000):
        bridge.send({"i": i})
    msgs = worker.read_since(after_seq=0, limit=10000)
    elapsed = time.perf_counter() - start

    assert len(msgs) == 5000
    assert elapsed < 4.0, f"5k round-trip took {elapsed:.2f}s (>4s threshold)"

    bridge.close()
    worker.close()
