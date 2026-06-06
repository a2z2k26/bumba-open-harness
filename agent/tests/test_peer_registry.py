"""Unit tests for bridge.peer_registry (Issue #78 + #769).

Sprint 07.05 backed PeerRegistry with SQLite. The fixture below routes
every registry to a tmp_path-scoped DB so tests stay isolated and never
touch ``data/memory.db``.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from bridge.peer_registry import (
    PEER_REGISTRY_OWNERSHIP_DOC,
    PeerMetadata,
    PeerRecord,
    PeerRegistry,
    PeerStatus,
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "peers.db"


@pytest.fixture
def registry(db_path: Path) -> PeerRegistry:
    return PeerRegistry(db_path=db_path)


def _make_record(
    peer_id: str = "peer-1",
    name: str = "mac-mini/main",
    status: PeerStatus = PeerStatus.ONLINE,
    capabilities: list[str] | None = None,
    tags: list[str] | None = None,
    last_heartbeat: float | None = None,
) -> PeerRecord:
    return PeerRecord(
        peer_id=peer_id,
        name=name,
        status=status,
        metadata=PeerMetadata(
            machine="mac-mini",
            branch="main",
            model="claude-opus-4-6",
            version="1.0.0",
            capabilities=capabilities or [],
        ),
        last_heartbeat=last_heartbeat or time.time(),
        registered_at=time.time(),
        tags=tags or [],
    )


# ------------------------------------------------------------------
# PeerRecord / PeerMetadata creation
# ------------------------------------------------------------------

class TestPeerRecord:
    def test_create_record(self) -> None:
        r = _make_record()
        assert r.peer_id == "peer-1"
        assert r.name == "mac-mini/main"
        assert r.status == PeerStatus.ONLINE
        assert r.metadata.machine == "mac-mini"
        assert r.metadata.branch == "main"

    def test_frozen(self) -> None:
        r = _make_record()
        with pytest.raises(AttributeError):
            r.name = "changed"  # type: ignore[misc]

    def test_metadata_frozen(self) -> None:
        m = PeerMetadata(
            machine="m", branch="b", model="m", version="v", capabilities=[]
        )
        with pytest.raises(AttributeError):
            m.machine = "changed"  # type: ignore[misc]

    def test_default_tags_empty(self) -> None:
        r = _make_record()
        assert r.tags == []


# ------------------------------------------------------------------
# Register / deregister / get
# ------------------------------------------------------------------

class TestRegisterDeregister:
    def test_register_and_get(self, registry: PeerRegistry) -> None:
        r = _make_record()
        registry.register(r)
        assert registry.get("peer-1") is r

    def test_get_missing_returns_none(self, registry: PeerRegistry) -> None:
        assert registry.get("nope") is None

    def test_deregister_returns_true(self, registry: PeerRegistry) -> None:
        registry.register(_make_record())
        assert registry.deregister("peer-1") is True
        assert registry.get("peer-1") is None

    def test_deregister_missing_returns_false(self, registry: PeerRegistry) -> None:
        assert registry.deregister("nope") is False

    def test_register_replaces_existing(self, registry: PeerRegistry) -> None:
        registry.register(_make_record(name="old"))
        registry.register(_make_record(name="new"))
        assert registry.get("peer-1").name == "new"


# ------------------------------------------------------------------
# list_peers
# ------------------------------------------------------------------

class TestListPeers:
    def test_list_all(self, registry: PeerRegistry) -> None:
        registry.register(_make_record("a"))
        registry.register(_make_record("b"))
        assert len(registry.list_peers()) == 2

    def test_list_by_status(self, registry: PeerRegistry) -> None:
        registry.register(_make_record("a", status=PeerStatus.ONLINE))
        registry.register(_make_record("b", status=PeerStatus.OFFLINE))
        registry.register(_make_record("c", status=PeerStatus.ONLINE))
        online = registry.list_peers(status=PeerStatus.ONLINE)
        assert len(online) == 2
        assert all(p.status == PeerStatus.ONLINE for p in online)

    def test_list_empty(self, registry: PeerRegistry) -> None:
        assert registry.list_peers() == []


# ------------------------------------------------------------------
# Heartbeat
# ------------------------------------------------------------------

class TestHeartbeat:
    def test_update_heartbeat(self, registry: PeerRegistry) -> None:
        old_time = time.time() - 100
        registry.register(_make_record(last_heartbeat=old_time))
        assert registry.update_heartbeat("peer-1") is True
        updated = registry.get("peer-1")
        assert updated.last_heartbeat > old_time

    def test_heartbeat_unknown_peer(self, registry: PeerRegistry) -> None:
        assert registry.update_heartbeat("nope") is False


# ------------------------------------------------------------------
# update_status
# ------------------------------------------------------------------

class TestUpdateStatus:
    def test_update_status(self, registry: PeerRegistry) -> None:
        registry.register(_make_record())
        assert registry.update_status("peer-1", PeerStatus.DEGRADED) is True
        assert registry.get("peer-1").status == PeerStatus.DEGRADED

    def test_update_status_unknown(self, registry: PeerRegistry) -> None:
        assert registry.update_status("nope", PeerStatus.OFFLINE) is False


# ------------------------------------------------------------------
# find_by_capability
# ------------------------------------------------------------------

class TestFindByCapability:
    def test_find_matching(self, registry: PeerRegistry) -> None:
        registry.register(_make_record("a", capabilities=["merge", "deploy"]))
        registry.register(_make_record("b", capabilities=["deploy"]))
        registry.register(_make_record("c", capabilities=["test"]))
        result = registry.find_by_capability("deploy")
        assert len(result) == 2
        ids = {p.peer_id for p in result}
        assert ids == {"a", "b"}

    def test_find_none(self, registry: PeerRegistry) -> None:
        registry.register(_make_record("a", capabilities=["test"]))
        assert registry.find_by_capability("deploy") == []


# ------------------------------------------------------------------
# Prune stale
# ------------------------------------------------------------------

class TestPruneStale:
    def test_prune_marks_offline(self, registry: PeerRegistry) -> None:
        stale_time = time.time() - 300
        registry.register(_make_record("stale", last_heartbeat=stale_time))
        registry.register(_make_record("fresh"))
        pruned = registry.prune_stale(timeout_seconds=180.0)
        assert pruned == ["stale"]
        assert registry.get("stale").status == PeerStatus.OFFLINE
        assert registry.get("fresh").status == PeerStatus.ONLINE

    def test_prune_skips_already_offline(self, registry: PeerRegistry) -> None:
        stale_time = time.time() - 300
        registry.register(
            _make_record("off", status=PeerStatus.OFFLINE, last_heartbeat=stale_time)
        )
        pruned = registry.prune_stale(timeout_seconds=180.0)
        assert pruned == []

    def test_prune_nothing_stale(self, registry: PeerRegistry) -> None:
        registry.register(_make_record("fresh"))
        assert registry.prune_stale() == []


# ------------------------------------------------------------------
# PeerStatus enum
# ------------------------------------------------------------------

class TestPeerStatus:
    def test_values(self) -> None:
        assert PeerStatus.ONLINE.value == "online"
        assert PeerStatus.OFFLINE.value == "offline"
        assert PeerStatus.DEGRADED.value == "degraded"
        assert PeerStatus.UNKNOWN.value == "unknown"


# ------------------------------------------------------------------
# Sprint 07.05 (#769) -- SQLite persistence contract
# ------------------------------------------------------------------

class TestSqlitePersistence:
    """Spec-named tests for issue #769.

    These exercise the contract that PeerRegistry persists rows in the
    ``peers`` table of the configured SQLite DB and that records survive
    a process restart.
    """

    def test_register_persists_to_sqlite(self, db_path: Path) -> None:
        import sqlite3

        registry = PeerRegistry(db_path=db_path)
        registry.register(_make_record(peer_id="persist-me", name="boxA/main"))

        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT agent_id, health_status FROM peers WHERE agent_id = ?",
                ("persist-me",),
            ).fetchone()
        assert row is not None, "expected row to be persisted"
        assert row[0] == "persist-me"
        assert row[1] == PeerStatus.ONLINE.value

    def test_deregister_removes_from_sqlite(self, db_path: Path) -> None:
        import sqlite3

        registry = PeerRegistry(db_path=db_path)
        registry.register(_make_record(peer_id="rm-me"))
        assert registry.deregister("rm-me") is True

        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM peers WHERE agent_id = ?",
                ("rm-me",),
            ).fetchone()
        assert row is None, "row should be deleted from peers table"

    def test_heartbeat_update_visible_to_readers(self, db_path: Path) -> None:
        import sqlite3

        registry = PeerRegistry(db_path=db_path)
        old = time.time() - 500
        registry.register(_make_record(peer_id="hb", last_heartbeat=old))

        # First read raw row to confirm initial value persisted.
        with sqlite3.connect(db_path) as conn:
            initial_hb = conn.execute(
                "SELECT last_heartbeat FROM peers WHERE agent_id = ?",
                ("hb",),
            ).fetchone()[0]

        assert registry.update_heartbeat("hb") is True

        # Independent reader (new connection) sees the bumped value.
        with sqlite3.connect(db_path) as conn:
            new_hb = conn.execute(
                "SELECT last_heartbeat FROM peers WHERE agent_id = ?",
                ("hb",),
            ).fetchone()[0]
        assert new_hb > initial_hb, "heartbeat update must be visible to other readers"

        # And a fresh PeerRegistry instance pointing at the same DB
        # also reflects the new heartbeat.
        reader = PeerRegistry(db_path=db_path)
        record = reader.get("hb")
        assert record is not None
        assert record.last_heartbeat >= new_hb

    def test_records_survive_restart(self, db_path: Path) -> None:
        first = PeerRegistry(db_path=db_path)
        first.register(
            _make_record(
                peer_id="survivor",
                name="mac-mini/main",
                capabilities=["merge", "deploy"],
                tags=["primary"],
            )
        )
        first.register(_make_record(peer_id="other", name="boxB/dev"))
        # Discard the in-memory reference -- simulates a process restart.
        del first

        revived = PeerRegistry(db_path=db_path)
        survivor = revived.get("survivor")
        assert survivor is not None
        assert survivor.peer_id == "survivor"
        assert survivor.name == "mac-mini/main"
        assert survivor.metadata.capabilities == ["merge", "deploy"]
        assert survivor.tags == ["primary"]
        assert survivor.status == PeerStatus.ONLINE
        assert {p.peer_id for p in revived.list_peers()} == {"survivor", "other"}


# ------------------------------------------------------------------
# Issue #2512 -- bridge-owned schema boundary
# ------------------------------------------------------------------

class TestOwnershipBoundary:
    def test_schema_boundary_is_bridge_owned(self, db_path: Path) -> None:
        import sqlite3

        PeerRegistry(db_path=db_path)

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("PRAGMA table_info(peers)").fetchall()

        columns = {row[1] for row in rows}
        assert columns == {
            "agent_id",
            "hostname",
            "api_url",
            "health_status",
            "registered_at",
            "last_heartbeat",
            "metadata",
        }
        assert "machine" not in columns
        assert "last_seen" not in columns
        assert "current_task" not in columns

    def test_ownership_boundary_doc_is_linked(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        assert (repo_root / PEER_REGISTRY_OWNERSHIP_DOC).exists()
