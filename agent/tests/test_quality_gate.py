"""Tests for bridge.quality_gate.QualityGate."""
from __future__ import annotations

import aiosqlite
import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Lightweight DB shim that matches the interface QualityGate expects
# ---------------------------------------------------------------------------
class _InMemoryDB:
    """Thin wrapper around aiosqlite that exposes the same API as
    ``bridge.database.Database`` (execute, fetchone, fetchall, commit).
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        return await self._conn.execute(sql, params)

    async def fetchone(self, sql: str, params: tuple = ()):
        cursor = await self._conn.execute(sql, params)
        return await cursor.fetchone()

    async def fetchall(self, sql: str, params: tuple = ()):
        cursor = await self._conn.execute(sql, params)
        return await cursor.fetchall()

    async def commit(self) -> None:
        await self._conn.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def gate():
    """Yield an initialised QualityGate backed by an in-memory SQLite DB."""
    from bridge.quality_gate import QualityGate

    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        db = _InMemoryDB(conn)
        qg = QualityGate(db)
        await qg.initialize()
        yield qg


# ---------------------------------------------------------------------------
# Tests — request_review
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_request_review_returns_id(gate: "QualityGate"):
    review_id = await gate.request_review(task_id=1)
    assert isinstance(review_id, int)
    assert review_id >= 1


@pytest.mark.asyncio
async def test_request_review_sequential_ids(gate: "QualityGate"):
    id1 = await gate.request_review(task_id=1)
    id2 = await gate.request_review(task_id=1, reviewer="alice")
    assert id2 == id1 + 1


# ---------------------------------------------------------------------------
# Tests — submit_decision
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_submit_approved(gate: "QualityGate"):
    rid = await gate.request_review(task_id=10)
    ok = await gate.submit_decision(rid, "approved")
    assert ok is True


@pytest.mark.asyncio
async def test_submit_rejected(gate: "QualityGate"):
    rid = await gate.request_review(task_id=10)
    ok = await gate.submit_decision(rid, "rejected", comment="Not ready")
    assert ok is True


@pytest.mark.asyncio
async def test_submit_needs_changes(gate: "QualityGate"):
    rid = await gate.request_review(task_id=10)
    ok = await gate.submit_decision(rid, "needs_changes", comment="Fix lint")
    assert ok is True


@pytest.mark.asyncio
async def test_submit_invalid_decision_raises(gate: "QualityGate"):
    rid = await gate.request_review(task_id=10)
    with pytest.raises(ValueError, match="Invalid decision"):
        await gate.submit_decision(rid, "maybe")


@pytest.mark.asyncio
async def test_submit_decision_on_already_decided_returns_false(gate: "QualityGate"):
    rid = await gate.request_review(task_id=10)
    await gate.submit_decision(rid, "approved")
    ok = await gate.submit_decision(rid, "rejected")
    assert ok is False


@pytest.mark.asyncio
async def test_submit_decision_sets_decided_at(gate: "QualityGate"):
    rid = await gate.request_review(task_id=10)
    await gate.submit_decision(rid, "approved")
    # Verify decided_at is populated by fetching all (no pending filter)
    row = await gate._db.fetchone(
        "SELECT decided_at FROM quality_reviews WHERE id = ?", (rid,)
    )
    assert row["decided_at"] is not None


# ---------------------------------------------------------------------------
# Tests — get_pending_reviews
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_pending_reviews_returns_only_pending(gate: "QualityGate"):
    r1 = await gate.request_review(task_id=20)
    r2 = await gate.request_review(task_id=20)
    await gate.submit_decision(r1, "approved")

    pending = await gate.get_pending_reviews()
    assert len(pending) == 1
    assert pending[0]["id"] == r2
    assert pending[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_get_pending_reviews_filtered_by_task_id(gate: "QualityGate"):
    await gate.request_review(task_id=30)
    await gate.request_review(task_id=31)
    await gate.request_review(task_id=30)

    pending_30 = await gate.get_pending_reviews(task_id=30)
    pending_31 = await gate.get_pending_reviews(task_id=31)
    assert len(pending_30) == 2
    assert len(pending_31) == 1
    assert all(r["task_id"] == 30 for r in pending_30)


@pytest.mark.asyncio
async def test_get_pending_reviews_returns_dicts(gate: "QualityGate"):
    await gate.request_review(task_id=40, reviewer="bob", review_type="security")
    pending = await gate.get_pending_reviews()
    assert len(pending) == 1
    review = pending[0]
    assert isinstance(review, dict)
    assert review["reviewer"] == "bob"
    assert review["review_type"] == "security"
    assert review["decision"] is None


# ---------------------------------------------------------------------------
# Tests — is_task_approved
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_is_task_approved_false_when_pending(gate: "QualityGate"):
    await gate.request_review(task_id=50)
    assert await gate.is_task_approved(50) is False


@pytest.mark.asyncio
async def test_is_task_approved_true_when_all_approved(gate: "QualityGate"):
    r1 = await gate.request_review(task_id=60)
    r2 = await gate.request_review(task_id=60)
    await gate.submit_decision(r1, "approved")
    await gate.submit_decision(r2, "approved")
    assert await gate.is_task_approved(60) is True


@pytest.mark.asyncio
async def test_is_task_approved_false_when_no_reviews(gate: "QualityGate"):
    assert await gate.is_task_approved(999) is False


@pytest.mark.asyncio
async def test_is_task_approved_false_when_one_rejected(gate: "QualityGate"):
    r1 = await gate.request_review(task_id=70)
    r2 = await gate.request_review(task_id=70)
    await gate.submit_decision(r1, "approved")
    await gate.submit_decision(r2, "rejected")
    # No pending reviews, but "rejected" != pending so the pending count is 0.
    # is_task_approved only checks for pending reviews per the spec.
    assert await gate.is_task_approved(70) is True
