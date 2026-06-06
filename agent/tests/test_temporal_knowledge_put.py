"""Regression tests pinning the TemporalKnowledgeStore.put() API surface.

The production `.put()` caller is dormant until Phase 5 Team Protocol directive
persistence activates (issues #661-#668, `blocked-by-activation` label set).
This file exercises `.put/.get/.get_at/.rollback` end-to-end so the API does
not silently rot while no production consumer is calling it.

See `agent/bridge/temporal_knowledge.py` module docstring for context, and
`docs/plans/2026-04-24-activation-plans/plan-05-intelligence-memory-activation.md`
§9 "Deferred wiring — temporal_knowledge.put()".
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from bridge.temporal_knowledge import TemporalKnowledgeStore, VersionedEntry


@pytest.fixture
def store(tmp_path: Path) -> TemporalKnowledgeStore:
    """Return a TemporalKnowledgeStore backed by a tmp_path SQLite file."""
    return TemporalKnowledgeStore(db_path=tmp_path / "temporal_put.db")


class TestPutGetRoundTrip:
    """Sprint 05.11 — verify `.put()` followed by `.get()` returns the same value."""

    def test_put_then_get_matches(self, store: TemporalKnowledgeStore) -> None:
        entry = store.put(
            "directive.tone",
            "concise",
            reason="Phase 5 directive scaffold",
            changed_by="operator",
        )
        assert isinstance(entry, VersionedEntry)
        assert entry.key == "directive.tone"
        assert entry.value == "concise"
        assert entry.version == 1
        assert entry.change_type == "create"
        assert entry.valid_to is None

        fetched = store.get("directive.tone")
        assert fetched is not None
        assert fetched.key == entry.key
        assert fetched.value == entry.value
        assert fetched.version == entry.version
        assert fetched.valid_from == entry.valid_from
        assert fetched.valid_to is None
        assert fetched.reason == "Phase 5 directive scaffold"
        assert fetched.changed_by == "operator"

    def test_put_overwrite_advances_version(self, store: TemporalKnowledgeStore) -> None:
        store.put("directive.persona", "blunt")
        second = store.put("directive.persona", "warm", reason="iteration")
        assert second.version == 2
        assert second.change_type == "update"

        current = store.get("directive.persona")
        assert current is not None
        assert current.value == "warm"
        assert current.version == 2


class TestPutGetAtTemporalQuery:
    """Sprint 05.11 — verify temporal queries return the version active at a given time."""

    def test_get_at_returns_correct_version_per_timestamp(
        self, store: TemporalKnowledgeStore
    ) -> None:
        first = store.put("policy.review_cadence", "weekly")
        t1 = first.valid_from

        # Small delay to ensure SQLite-stored timestamps are distinct
        time.sleep(0.01)

        second = store.put("policy.review_cadence", "biweekly", reason="ramp down")
        t2 = second.valid_from

        at_t1 = store.get_at("policy.review_cadence", t1)
        assert at_t1 is not None
        assert at_t1.value == "weekly"
        assert at_t1.version == 1

        at_t2 = store.get_at("policy.review_cadence", t2)
        assert at_t2 is not None
        assert at_t2.value == "biweekly"
        assert at_t2.version == 2


class TestPutThenRollback:
    """Sprint 05.11 — verify `.rollback()` restores an earlier value as a new version."""

    def test_rollback_round_trip(self, store: TemporalKnowledgeStore) -> None:
        store.put("config.retry_limit", "3")
        store.put("config.retry_limit", "5", reason="loosen")
        store.put("config.retry_limit", "10", reason="loosen further")

        current = store.get("config.retry_limit")
        assert current is not None
        assert current.value == "10"
        assert current.version == 3

        rolled = store.rollback("config.retry_limit", to_version=1, reason="revert to baseline")
        assert rolled is not None
        assert rolled.value == "3"
        assert rolled.version == 4
        assert rolled.change_type == "rollback"
        assert rolled.valid_to is None

        after = store.get("config.retry_limit")
        assert after is not None
        assert after.value == "3"
        assert after.version == 4

    def test_rollback_unknown_version_returns_none(
        self, store: TemporalKnowledgeStore
    ) -> None:
        store.put("config.timeout", "30s")
        result = store.rollback("config.timeout", to_version=99, reason="bogus")
        assert result is None
        # Original version should still be active
        current = store.get("config.timeout")
        assert current is not None
        assert current.value == "30s"
        assert current.version == 1
