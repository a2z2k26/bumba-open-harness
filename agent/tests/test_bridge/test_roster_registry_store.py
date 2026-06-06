"""Tests for RosterRegistryStore — the overlay persistence behind the
self-serve roster registry (Sprint RR.1, issue #2593).

The store holds operator-registered specialists that the chief-roster build
appends to the YAML base (RR.2). RR.1 covers persistence + validation +
the cache-invalidation ``on_change`` hook that is the load-bearing seam
(without it a registration is invisible until restart).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bridge.roster_registry_store import (
    RegisteredSpecialist,
    RegisterResult,
    RosterRegistryStore,
)


# ---------------------------------------------------------------------------
# Fakes — a config-lookup handle the store consults for validation.
# ---------------------------------------------------------------------------


class _FakeEmployee:
    """Minimal stand-in for an AgentSpec employee (only ``name`` is read)."""

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeConfig:
    """Minimal stand-in for a DepartmentConfig (only ``employees`` is read)."""

    def __init__(self, name: str, employee_names: list[str]) -> None:
        self.name = name
        self.employees = tuple(_FakeEmployee(n) for n in employee_names)


def _make_lookup(configs: dict[str, _FakeConfig]):
    """Return a ``config_lookup`` callable: dept name -> config | None."""

    def _lookup(department: str):
        return configs.get(department)

    return _lookup


@pytest.fixture
def configs() -> dict[str, _FakeConfig]:
    return {
        "engineering": _FakeConfig(
            "engineering",
            ["backend-architect", "frontend-developer", "performance-engineer"],
        ),
        "qa": _FakeConfig("qa", ["qa-engineer", "security-auditor"]),
    }


@pytest.fixture
def store(tmp_path: Path, configs: dict[str, _FakeConfig]) -> RosterRegistryStore:
    db_path = tmp_path / "test_roster_registry.db"
    s = RosterRegistryStore(db_path, config_lookup=_make_lookup(configs))
    yield s
    s.close()


# ---------------------------------------------------------------------------
# register — happy path
# ---------------------------------------------------------------------------


def test_register_valid(store: RosterRegistryStore) -> None:
    result = store.register("engineering", "perf-2", "performance-engineer")
    assert isinstance(result, RegisterResult)
    assert result.ok is True
    assert result.error is None
    assert result.specialist is not None
    assert isinstance(result.specialist, RegisteredSpecialist)
    assert result.specialist.department == "engineering"
    assert result.specialist.name == "perf-2"
    assert result.specialist.agent_ref == "performance-engineer"
    assert result.specialist.registered_by == "operator"
    assert result.specialist.registered_at  # ISO-8601 string, non-empty

    # Persisted and readable.
    rows = store.list_for_department("engineering")
    assert len(rows) == 1
    assert rows[0].name == "perf-2"


def test_register_records_custom_by(store: RosterRegistryStore) -> None:
    result = store.register(
        "engineering", "perf-2", "performance-engineer", by="dashboard"
    )
    assert result.ok is True
    assert result.specialist is not None
    assert result.specialist.registered_by == "dashboard"


# ---------------------------------------------------------------------------
# register — rejections (each a distinct, clear error; never silent-insert)
# ---------------------------------------------------------------------------


def test_register_rejects_unknown_department(store: RosterRegistryStore) -> None:
    result = store.register("nope", "x", "performance-engineer")
    assert result.ok is False
    assert result.specialist is None
    assert result.error is not None
    assert "department" in result.error.lower()
    # Nothing written.
    assert store.list_all() == ()


def test_register_rejects_unresolvable_agent_ref(store: RosterRegistryStore) -> None:
    result = store.register("engineering", "perf-2", "no-such-agent")
    assert result.ok is False
    assert result.specialist is None
    assert result.error is not None
    assert "agent_ref" in result.error.lower() or "agent ref" in result.error.lower()
    assert store.list_all() == ()


def test_register_rejects_duplicate(store: RosterRegistryStore) -> None:
    first = store.register("engineering", "perf-2", "performance-engineer")
    assert first.ok is True
    second = store.register("engineering", "perf-2", "backend-architect")
    assert second.ok is False
    assert second.specialist is None
    assert second.error is not None
    assert "already registered" in second.error.lower() or "duplicate" in second.error.lower()
    # The original row is untouched.
    rows = store.list_for_department("engineering")
    assert len(rows) == 1
    assert rows[0].agent_ref == "performance-engineer"


def test_register_rejects_shadow_of_builtin(store: RosterRegistryStore) -> None:
    # ``backend-architect`` IS a YAML built-in employee in engineering.
    result = store.register("engineering", "backend-architect", "performance-engineer")
    assert result.ok is False
    assert result.specialist is None
    assert result.error is not None
    assert "built-in" in result.error.lower() or "builtin" in result.error.lower() or "shadow" in result.error.lower()
    assert store.list_all() == ()


# ---------------------------------------------------------------------------
# unregister
# ---------------------------------------------------------------------------


def test_unregister(store: RosterRegistryStore) -> None:
    store.register("engineering", "perf-2", "performance-engineer")
    assert store.unregister("engineering", "perf-2") is True
    assert store.list_for_department("engineering") == ()
    # Removing an absent row returns False.
    assert store.unregister("engineering", "perf-2") is False


# ---------------------------------------------------------------------------
# list reads
# ---------------------------------------------------------------------------


def test_list_for_department(store: RosterRegistryStore) -> None:
    store.register("engineering", "perf-2", "performance-engineer")
    store.register("engineering", "perf-3", "backend-architect")
    store.register("qa", "sec-2", "security-auditor")

    eng = store.list_for_department("engineering")
    assert {r.name for r in eng} == {"perf-2", "perf-3"}
    assert all(r.department == "engineering" for r in eng)

    qa = store.list_for_department("qa")
    assert {r.name for r in qa} == {"sec-2"}

    assert store.list_for_department("strategy") == ()

    all_rows = store.list_all()
    assert len(all_rows) == 3
    assert {(r.department, r.name) for r in all_rows} == {
        ("engineering", "perf-2"),
        ("engineering", "perf-3"),
        ("qa", "sec-2"),
    }


# ---------------------------------------------------------------------------
# on_change cache-invalidation hook — the load-bearing seam (RR.1+RR.2)
# ---------------------------------------------------------------------------


def test_on_change_fires_on_write(
    tmp_path: Path, configs: dict[str, _FakeConfig]
) -> None:
    seen: list[str] = []
    store = RosterRegistryStore(
        tmp_path / "rr.db",
        config_lookup=_make_lookup(configs),
        on_change=seen.append,
    )
    try:
        store.register("engineering", "perf-2", "performance-engineer")
        assert seen == ["engineering"]
        store.unregister("engineering", "perf-2")
        assert seen == ["engineering", "engineering"]
    finally:
        store.close()


def test_on_change_not_fired_on_rejected_register(
    tmp_path: Path, configs: dict[str, _FakeConfig]
) -> None:
    seen: list[str] = []
    store = RosterRegistryStore(
        tmp_path / "rr.db",
        config_lookup=_make_lookup(configs),
        on_change=seen.append,
    )
    try:
        # unknown department — rejected, no write, no callback
        store.register("nope", "x", "performance-engineer")
        # unresolvable agent_ref — rejected
        store.register("engineering", "perf-2", "no-such-agent")
        # shadow of built-in — rejected
        store.register("engineering", "backend-architect", "performance-engineer")
        assert seen == []
    finally:
        store.close()


def test_on_change_absent_is_clean_noop(
    tmp_path: Path, configs: dict[str, _FakeConfig]
) -> None:
    # No on_change supplied — register/unregister must not raise.
    store = RosterRegistryStore(
        tmp_path / "rr.db", config_lookup=_make_lookup(configs)
    )
    try:
        assert store.register("engineering", "perf-2", "performance-engineer").ok is True
        assert store.unregister("engineering", "perf-2") is True
    finally:
        store.close()


def test_unregister_absent_does_not_fire_on_change(
    tmp_path: Path, configs: dict[str, _FakeConfig]
) -> None:
    seen: list[str] = []
    store = RosterRegistryStore(
        tmp_path / "rr.db",
        config_lookup=_make_lookup(configs),
        on_change=seen.append,
    )
    try:
        assert store.unregister("engineering", "ghost") is False
        assert seen == []
    finally:
        store.close()


# ---------------------------------------------------------------------------
# cross-restart durability (RR.5 proves end-to-end; RR.1 proves the store layer)
# ---------------------------------------------------------------------------


def test_persists_across_store_reopen(
    tmp_path: Path, configs: dict[str, _FakeConfig]
) -> None:
    db_path = tmp_path / "rr.db"
    s1 = RosterRegistryStore(db_path, config_lookup=_make_lookup(configs))
    s1.register("engineering", "perf-2", "performance-engineer")
    s1.close()

    s2 = RosterRegistryStore(db_path, config_lookup=_make_lookup(configs))
    try:
        rows = s2.list_for_department("engineering")
        assert len(rows) == 1
        assert rows[0].name == "perf-2"
        assert rows[0].agent_ref == "performance-engineer"
    finally:
        s2.close()
