"""Tests for the WorkOrder decomposition contract (Sprint 07.01).

Concept-only port of TinyAGI/fractals (MIT). These tests cover the
contract surface — enum, dataclass, Protocol stub, and round-trip
persistence — without exercising any real decomposer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bridge.decomposer import Decomposer, _DefaultDecomposer
from bridge.work_order import (
    BatchStrategy,
    Decomposition,
    WorkOrder,
)
from bridge.work_order_store import WorkOrderStore


# ---------------------------------------------------------------------------
# BatchStrategy enum
# ---------------------------------------------------------------------------


def test_batch_strategy_concurrency_values() -> None:
    """User-facing concurrency strategies are present and stable."""
    assert BatchStrategy.SEQUENTIAL.value == "sequential"
    assert BatchStrategy.PARALLEL_FANOUT.value == "parallel_fanout"
    assert BatchStrategy.RACE.value == "race"


def test_batch_strategy_traversal_values() -> None:
    """Spec-documented traversal strategies are present and stable."""
    assert BatchStrategy.DEPTH_FIRST.value == "depth_first"
    assert BatchStrategy.BREADTH_FIRST.value == "breadth_first"
    assert BatchStrategy.LAYER_SEQUENTIAL.value == "layer_sequential"


def test_batch_strategy_total_count() -> None:
    """Lock the enum surface so future additions are intentional."""
    assert len(list(BatchStrategy)) == 6


# ---------------------------------------------------------------------------
# Decomposition dataclass — frozen + immutable
# ---------------------------------------------------------------------------


def test_decomposition_is_frozen() -> None:
    """Frozen dataclass — direct mutation raises FrozenInstanceError."""
    decomp = Decomposition(strategy=BatchStrategy.SEQUENTIAL)
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError or AttributeError
        decomp.strategy = BatchStrategy.RACE  # type: ignore[misc]


def test_decomposition_children_is_tuple() -> None:
    """Children stored as a tuple — list input is coerced."""
    child = WorkOrder.create(intent="leaf", skill="x", project="p")
    decomp = Decomposition(
        strategy=BatchStrategy.PARALLEL_FANOUT,
        children=[child],  # list input
        atomic=False,
    )
    assert isinstance(decomp.children, tuple)
    assert len(decomp.children) == 1
    assert decomp.children[0].id == child.id


def test_decomposition_atomic_explicit_default_false() -> None:
    """``atomic`` must be set explicitly — default False is documented."""
    decomp = Decomposition(strategy=BatchStrategy.SEQUENTIAL)
    assert decomp.atomic is False


def test_decomposition_to_from_dict_round_trip() -> None:
    """Decomposition survives JSON serialize → deserialize."""
    leaf = WorkOrder.create(intent="leaf", skill="x", project="p")
    decomp = Decomposition(
        strategy=BatchStrategy.RACE,
        children=(leaf,),
        atomic=False,
    )
    data = decomp.to_dict()
    restored = Decomposition.from_dict(data)
    assert restored.strategy == BatchStrategy.RACE
    assert len(restored.children) == 1
    assert restored.children[0].id == leaf.id
    assert restored.atomic is False


# ---------------------------------------------------------------------------
# WorkOrder integration — decomposition field
# ---------------------------------------------------------------------------


def test_work_order_default_decomposition_is_none() -> None:
    """Existing call sites continue to work — decomposition defaults to None."""
    wo = WorkOrder.create(intent="task", skill="x", project="p")
    assert wo.decomposition is None


def test_work_order_with_decomposition_helper() -> None:
    """``with_decomposition`` returns a new instance (immutable update)."""
    wo = WorkOrder.create(intent="task", skill="x", project="p")
    decomp = Decomposition(strategy=BatchStrategy.SEQUENTIAL, atomic=True)
    wo2 = wo.with_decomposition(decomp)
    assert wo.decomposition is None  # original unchanged
    assert wo2.decomposition is decomp
    assert wo2.id == wo.id


def test_recursive_nesting_two_levels() -> None:
    """A WorkOrder with a Decomposition whose children also have decompositions."""
    grandchild = WorkOrder.create(intent="leaf", skill="x", project="p")
    child = WorkOrder.create(intent="branch", skill="x", project="p")
    child = child.with_decomposition(
        Decomposition(strategy=BatchStrategy.SEQUENTIAL, children=(grandchild,))
    )
    root = WorkOrder.create(intent="root", skill="x", project="p")
    root = root.with_decomposition(
        Decomposition(strategy=BatchStrategy.PARALLEL_FANOUT, children=(child,))
    )

    assert root.decomposition is not None
    assert root.decomposition.strategy == BatchStrategy.PARALLEL_FANOUT
    assert len(root.decomposition.children) == 1
    inner = root.decomposition.children[0]
    assert inner.decomposition is not None
    assert inner.decomposition.strategy == BatchStrategy.SEQUENTIAL
    assert len(inner.decomposition.children) == 1
    assert inner.decomposition.children[0].id == grandchild.id


def test_work_order_to_from_dict_with_decomposition() -> None:
    """to_dict / from_dict round-trips a recursive decomposition tree."""
    leaf = WorkOrder.create(intent="leaf", skill="x", project="p")
    root = WorkOrder.create(intent="root", skill="x", project="p")
    root = root.with_decomposition(
        Decomposition(strategy=BatchStrategy.RACE, children=(leaf,), atomic=False)
    )
    data = root.to_dict()
    restored = WorkOrder.from_dict(data)
    assert restored.decomposition is not None
    assert restored.decomposition.strategy == BatchStrategy.RACE
    assert len(restored.decomposition.children) == 1
    assert restored.decomposition.children[0].id == leaf.id


def test_work_order_to_from_dict_without_decomposition() -> None:
    """Legacy path — decomposition field absent from dict yields None."""
    wo = WorkOrder.create(intent="legacy", skill="x", project="p")
    data = wo.to_dict()
    assert data["decomposition"] is None
    restored = WorkOrder.from_dict(data)
    assert restored.decomposition is None


def test_work_order_from_dict_legacy_missing_key() -> None:
    """Backward compat — rows persisted before 07.01 lack the key entirely."""
    wo = WorkOrder.create(intent="legacy", skill="x", project="p")
    data = wo.to_dict()
    # Simulate a legacy row written before the field existed.
    data.pop("decomposition", None)
    restored = WorkOrder.from_dict(data)
    assert restored.decomposition is None


# ---------------------------------------------------------------------------
# Persistence round-trip — composite WorkOrder through WorkOrderStore
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> WorkOrderStore:
    return WorkOrderStore(tmp_path / "test_workorders.db")


def test_persistence_round_trip_composite_workorder(store: WorkOrderStore) -> None:
    """Insert composite WO, fetch, verify children + strategy preserved."""
    leaf_a = WorkOrder.create(intent="a", skill="x", project="p")
    leaf_b = WorkOrder.create(intent="b", skill="x", project="p")
    root = WorkOrder.create(intent="root", skill="x", project="p")
    root = root.with_decomposition(
        Decomposition(
            strategy=BatchStrategy.PARALLEL_FANOUT,
            children=(leaf_a, leaf_b),
            atomic=False,
        )
    )
    store.save(root)
    fetched = store.get(root.id)
    assert fetched is not None
    assert fetched.decomposition is not None
    assert fetched.decomposition.strategy == BatchStrategy.PARALLEL_FANOUT
    assert len(fetched.decomposition.children) == 2
    fetched_ids = {c.id for c in fetched.decomposition.children}
    assert fetched_ids == {leaf_a.id, leaf_b.id}


def test_persistence_round_trip_atomic_workorder(store: WorkOrderStore) -> None:
    """Existing atomic WorkOrders persist unchanged."""
    wo = WorkOrder.create(intent="atomic", skill="x", project="p")
    store.save(wo)
    fetched = store.get(wo.id)
    assert fetched is not None
    assert fetched.decomposition is None


def test_decomposition_metadata_column_populated(store: WorkOrderStore) -> None:
    """The projection column carries the JSON plan when present."""
    leaf = WorkOrder.create(intent="leaf", skill="x", project="p")
    root = WorkOrder.create(intent="root", skill="x", project="p")
    root = root.with_decomposition(
        Decomposition(strategy=BatchStrategy.SEQUENTIAL, children=(leaf,))
    )
    store.save(root)
    row = store._conn.execute(
        "SELECT decomposition_metadata FROM work_orders WHERE id = ?",
        (root.id,),
    ).fetchone()
    assert row is not None
    assert row[0] is not None
    # Atomic WOs leave the column NULL.
    atomic = WorkOrder.create(intent="atomic", skill="x", project="p")
    store.save(atomic)
    row = store._conn.execute(
        "SELECT decomposition_metadata FROM work_orders WHERE id = ?",
        (atomic.id,),
    ).fetchone()
    assert row is not None
    assert row[0] is None


def test_schema_migration_idempotent(tmp_path: Path) -> None:
    """Running the migration twice does not raise — opening the store
    again hits the column-existence check and skips the ALTER TABLE."""
    db_path = tmp_path / "test_idempotent.db"
    store_a = WorkOrderStore(db_path)
    store_a.close()
    # Second open — the constructor re-runs all migrations.
    store_b = WorkOrderStore(db_path)
    cols = {
        row[1]
        for row in store_b._conn.execute("PRAGMA table_info(work_orders)").fetchall()
    }
    assert "decomposition_metadata" in cols
    store_b.close()


# ---------------------------------------------------------------------------
# Decomposer Protocol + default stub
# ---------------------------------------------------------------------------


def test_default_decomposer_classifies_atomic() -> None:
    """Stub guard — every WorkOrder is atomic for the default decomposer."""
    dec = _DefaultDecomposer()
    wo = WorkOrder.create(intent="anything", skill="x", project="p")
    assert dec.classify(wo) == "atomic"


def test_default_decomposer_decompose_raises() -> None:
    """The default stub never decomposes — calling decompose is a contract bug."""
    dec = _DefaultDecomposer()
    wo = WorkOrder.create(intent="anything", skill="x", project="p")
    with pytest.raises(RuntimeError):
        dec.decompose(wo)


def test_default_decomposer_satisfies_protocol() -> None:
    """The stub ducks-types as ``Decomposer`` (runtime_checkable)."""
    dec: Decomposer = _DefaultDecomposer()
    assert isinstance(dec, Decomposer)
