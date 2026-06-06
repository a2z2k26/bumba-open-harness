"""Tests for ``bridge.second_brain.contributor`` — Sprint 05.04.

Covers the SecondBrainContributor Protocol, the in-memory
ContributorRegistry, and the bumba-contributions/ subtree bootstrap.

Per the ADR (operator-signed 2026-05-01), Bumba never writes to
canonical wiki pages directly — every contribution lands under
``bumba-contributions/staging/`` (daily_log, reflection, ingest) or
``bumba-contributions/curated/`` (consolidation outputs). This file
exercises the interface + wiring; specific contributor implementations
(05.05/05.06/05.07/05.11) are out of scope for this sprint.
"""

from __future__ import annotations

import pytest

from bridge.second_brain.contributor import (
    Contribution,
    ContributorRegistry,
    SecondBrainContributor,
    ensure_subtree,
)


# ---------- helpers ----------


def _make_contribution(
    *,
    name: str = "fixture_contributor",
    relpath: str = "bumba-contributions/staging/2026-05-01.md",
    body: str = "hello world",
    source: str = "daily_log",
    destination: str = "staging",
    session_id: str = "session-x",
    authored_at: str = "2026-05-01T12:00:00Z",
    provenance: str = "test",
) -> Contribution:
    return Contribution(
        relpath=relpath,
        body=body,
        source=source,  # type: ignore[arg-type]
        destination=destination,  # type: ignore[arg-type]
        session_id=session_id,
        authored_at=authored_at,
        provenance=provenance,
    )


class _StubContributor:
    """Minimal class that satisfies the SecondBrainContributor Protocol."""

    def __init__(self, name: str, contributions: list[Contribution] | None = None):
        self._name = name
        self._contributions = contributions or []
        self.last_since: str | None | object = "<unset>"

    @property
    def contributor_name(self) -> str:
        return self._name

    def collect(self, since: str | None) -> list[Contribution]:
        self.last_since = since
        return list(self._contributions)


class _NoCollect:
    """Class missing ``collect`` — used to verify Protocol enforcement."""

    @property
    def contributor_name(self) -> str:
        return "broken"


# ---------- Contribution dataclass ----------


def test_contribution_dataclass_round_trips():
    c = _make_contribution()
    assert c.relpath == "bumba-contributions/staging/2026-05-01.md"
    assert c.body == "hello world"
    assert c.source == "daily_log"
    assert c.destination == "staging"
    assert c.session_id == "session-x"
    assert c.authored_at == "2026-05-01T12:00:00Z"
    assert c.provenance == "test"


def test_contribution_is_frozen():
    c = _make_contribution()
    with pytest.raises(Exception):  # FrozenInstanceError subclasses Exception
        c.body = "mutated"  # type: ignore[misc]


# ---------- Protocol conformance ----------


def test_protocol_satisfied_by_stub():
    stub = _StubContributor("daily_log")
    assert isinstance(stub, SecondBrainContributor)


def test_runtime_checkable_rejects_missing_collect():
    broken = _NoCollect()
    assert not isinstance(broken, SecondBrainContributor)


# ---------- ContributorRegistry ----------


def test_register_then_iterate_round_trip():
    reg = ContributorRegistry()
    a = _StubContributor("alpha")
    reg.register(a)
    assert reg.all() == [a]


def test_register_rejects_duplicate_name():
    reg = ContributorRegistry()
    reg.register(_StubContributor("dup"))
    with pytest.raises(ValueError, match="already registered"):
        reg.register(_StubContributor("dup"))


def test_all_returns_sorted_by_name():
    reg = ContributorRegistry()
    z = _StubContributor("zulu")
    a = _StubContributor("alpha")
    m = _StubContributor("mike")
    # Register in non-sorted order.
    reg.register(z)
    reg.register(m)
    reg.register(a)
    assert [c.contributor_name for c in reg.all()] == ["alpha", "mike", "zulu"]


def test_collect_all_aggregates_from_every_contributor():
    reg = ContributorRegistry()
    c1 = _make_contribution(relpath="bumba-contributions/staging/a.md")
    c2 = _make_contribution(relpath="bumba-contributions/staging/b.md")
    c3 = _make_contribution(
        relpath="bumba-contributions/curated/c.md",
        source="consolidation",
        destination="curated",
    )
    reg.register(_StubContributor("alpha", [c1]))
    reg.register(_StubContributor("bravo", [c2, c3]))
    out = reg.collect_all(since="2026-05-01T00:00:00Z")
    # Order respects sorted contributor_name (alpha then bravo).
    assert out == [c1, c2, c3]


def test_collect_all_since_none_triggers_full_sweep():
    reg = ContributorRegistry()
    a = _StubContributor("alpha")
    b = _StubContributor("bravo")
    reg.register(a)
    reg.register(b)
    reg.collect_all(since=None)
    assert a.last_since is None
    assert b.last_since is None


def test_collect_all_default_since_is_none():
    reg = ContributorRegistry()
    a = _StubContributor("alpha")
    reg.register(a)
    reg.collect_all()  # no since arg
    assert a.last_since is None


def test_collect_all_empty_registry_returns_empty_list():
    reg = ContributorRegistry()
    assert reg.collect_all() == []


# ---------- ensure_subtree ----------


def test_ensure_subtree_creates_staging_curated_and_readme(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    ensure_subtree(vault)
    base = vault / "bumba-contributions"
    assert (base / "staging").is_dir()
    assert (base / "curated").is_dir()
    readme = base / "README.md"
    assert readme.is_file()
    body = readme.read_text(encoding="utf-8")
    assert "Bumba Contributions" in body
    assert "/promote" in body
    assert "/reject_wiki" in body


def test_ensure_subtree_is_idempotent(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    ensure_subtree(vault)
    # Edit the README to confirm a second call does not overwrite it.
    readme = vault / "bumba-contributions" / "README.md"
    readme.write_text("operator-edited", encoding="utf-8")
    # Second call must not raise and must not overwrite.
    ensure_subtree(vault)
    assert readme.read_text(encoding="utf-8") == "operator-edited"
    # Directories still present.
    assert (vault / "bumba-contributions" / "staging").is_dir()
    assert (vault / "bumba-contributions" / "curated").is_dir()


def test_ensure_subtree_does_not_mutate_canonical_content(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    # Pre-existing operator-canonical content above bumba-contributions/.
    (vault / "Daily").mkdir()
    canonical = vault / "Daily" / "2026-05-01.md"
    canonical.write_text("# Operator note\n", encoding="utf-8")
    sibling = vault / "Index.md"
    sibling.write_text("# Index", encoding="utf-8")
    ensure_subtree(vault)
    assert canonical.read_text(encoding="utf-8") == "# Operator note\n"
    assert sibling.read_text(encoding="utf-8") == "# Index"


def test_ensure_subtree_missing_vault_raises(tmp_path):
    missing = tmp_path / "no-such-vault"
    with pytest.raises(FileNotFoundError):
        ensure_subtree(missing)


# ---------- Config field ----------


def test_bridge_config_exposes_second_brain_fields():
    """Sanity: BridgeConfig advertises the new fields with safe defaults."""
    from bridge.config import BridgeConfig

    cfg = BridgeConfig()
    assert getattr(cfg, "second_brain_enabled") is False
    assert getattr(cfg, "second_brain_vault_root") == ""
