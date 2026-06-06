"""Tests for ``bridge.second_brain.contributors`` — Sprint 05.07 (#1015).

Covers the three concrete contributor implementations
(:class:`DailyLogContributor`, :class:`ReflectionContributor`,
:class:`ConsolidationContributor`) and verifies they integrate
cleanly with :class:`ContributorRegistry`,
:class:`bridge.second_brain.wiki_repo.WikiRepo`, and
:class:`bridge.config.BridgeConfig`.

Per ADR Decision 3 (signed 2026-05-01,
``agent/docs/architecture/second-brain.md``): hybrid quarantine — the
two staging contributors must drop into
``bumba-contributions/staging/`` and the consolidation contributor must
drop into ``bumba-contributions/curated/``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from bridge.second_brain import (
    ContributorRegistry,
    SecondBrainContributor,
    WikiRepo,
)
from bridge.second_brain.contributors import (
    ConsolidationContributor,
    DailyLogContributor,
    ReflectionContributor,
)


# ---------------- helpers ---------------- #


def _seed_daily_log(root: Path, iso_dates: list[str]) -> list[Path]:
    """Materialize ``YYYY/MM/YYYY-MM-DD.md`` files under ``root``."""
    out: list[Path] = []
    for iso in iso_dates:
        year, month, _ = iso.split("-")
        target_dir = root / year / month
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{iso}.md"
        target.write_text(
            f"# Daily log for {iso}\n- entry\n",
            encoding="utf-8",
        )
        out.append(target)
    return out


def _seed_consolidation_digest(root: Path, iso_dates: list[str]) -> list[Path]:
    """Materialize ``YYYY-MM-DD-digest.md`` files under ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for iso in iso_dates:
        target = root / f"{iso}-digest.md"
        target.write_text(
            f"# Consolidation digest {iso}\n\n- one\n- two\n- three\n",
            encoding="utf-8",
        )
        out.append(target)
    return out


@dataclass
class _StubReflectionResult:
    """Minimal stand-in for :class:`bridge.reflection.ReflectionResult`."""

    week_key: str = ""
    achievements: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    contradictions: list[dict] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    raw_text: str = ""


class _StubReflectionStore:
    """Minimal duck-typed reflection store."""

    def __init__(self, results: list[_StubReflectionResult]) -> None:
        self._results = list(results)

    def count(self) -> int:
        return len(self._results)

    def get_recent(self, limit: int = 4) -> list[_StubReflectionResult]:
        return list(self._results[:limit])

    def format_reflection(self, result: _StubReflectionResult) -> str:
        lines = [f"# Reflection: {result.week_key}", ""]
        if result.achievements:
            lines.append("## Achievements")
            for a in result.achievements:
                lines.append(f"- {a}")
            lines.append("")
        if result.recommendations:
            lines.append("## Focus Next Week")
            for r in result.recommendations:
                lines.append(f"- {r}")
            lines.append("")
        return "\n".join(lines)


# ---------------- DailyLogContributor ---------------- #


def test_daily_log_collect_full_sweep_returns_one_per_file(tmp_path):
    root = tmp_path / "logs"
    _seed_daily_log(root, ["2026-04-29", "2026-04-30", "2026-05-01"])
    contrib = DailyLogContributor(daily_log_root=root, session_id="s-1")
    out = contrib.collect()
    assert len(out) == 3
    relpaths = sorted(c.relpath for c in out)
    assert relpaths == [
        "bumba-contributions/staging/daily-logs/2026-04-29.md",
        "bumba-contributions/staging/daily-logs/2026-04-30.md",
        "bumba-contributions/staging/daily-logs/2026-05-01.md",
    ]
    for c in out:
        assert c.source == "daily_log"
        assert c.destination == "staging"
        assert c.session_id == "s-1"
        assert "Daily log mirror for" in c.provenance


def test_daily_log_collect_since_filters_by_mtime(tmp_path):
    root = tmp_path / "logs"
    files = _seed_daily_log(root, ["2026-04-29", "2026-04-30", "2026-05-01"])
    # Set mtime: file[0] = old, file[1]/[2] = new.
    old_t = 1_700_000_000.0
    new_t = 1_800_000_000.0
    os.utime(files[0], (old_t, old_t))
    os.utime(files[1], (new_t, new_t))
    os.utime(files[2], (new_t, new_t))
    contrib = DailyLogContributor(daily_log_root=root, session_id="s-1")
    # Cutoff between old and new — strictly greater wins.
    cutoff_iso = "2026-01-01T00:00:00Z"  # ~ 1735689600 — between old and new
    out = contrib.collect(since=cutoff_iso)
    relpaths = sorted(c.relpath for c in out)
    assert relpaths == [
        "bumba-contributions/staging/daily-logs/2026-04-30.md",
        "bumba-contributions/staging/daily-logs/2026-05-01.md",
    ]


def test_daily_log_missing_root_returns_empty(tmp_path):
    missing = tmp_path / "no-such-root"
    contrib = DailyLogContributor(daily_log_root=missing, session_id="s-1")
    assert contrib.collect() == []
    assert contrib.collect(since="2026-04-30T00:00:00Z") == []


def test_daily_log_ignores_non_dated_files(tmp_path):
    root = tmp_path / "logs"
    _seed_daily_log(root, ["2026-05-01"])
    # Drop a non-date file alongside a date file in the same directory.
    (root / "2026" / "05" / "README.md").write_text("ignore me", encoding="utf-8")
    contrib = DailyLogContributor(daily_log_root=root, session_id="s-1")
    out = contrib.collect()
    assert len(out) == 1
    assert out[0].relpath == (
        "bumba-contributions/staging/daily-logs/2026-05-01.md"
    )


def test_daily_log_idempotent_same_since_same_relpaths(tmp_path):
    root = tmp_path / "logs"
    _seed_daily_log(root, ["2026-04-30", "2026-05-01"])
    contrib = DailyLogContributor(daily_log_root=root, session_id="s-1")
    a = contrib.collect()
    b = contrib.collect()
    assert [c.relpath for c in a] == [c.relpath for c in b]
    assert [c.body for c in a] == [c.body for c in b]


def test_daily_log_rejects_empty_session_id(tmp_path):
    with pytest.raises(ValueError, match="session_id"):
        DailyLogContributor(daily_log_root=tmp_path, session_id="")


# ---------------- ReflectionContributor ---------------- #


def test_reflection_collect_two_results_emits_two_contributions():
    store = _StubReflectionStore(
        [
            _StubReflectionResult(
                week_key="reflection-2026-W17",
                achievements=["shipped Plan 03"],
                recommendations=["land Plan 05"],
            ),
            _StubReflectionResult(
                week_key="reflection-2026-W18",
                achievements=["wired contributors"],
            ),
        ]
    )
    contrib = ReflectionContributor(reflection_store=store, session_id="s-1")
    out = contrib.collect()
    assert len(out) == 2
    relpaths = sorted(c.relpath for c in out)
    assert relpaths == [
        "bumba-contributions/staging/reflections/2026-W17.md",
        "bumba-contributions/staging/reflections/2026-W18.md",
    ]
    for c in out:
        assert c.source == "reflection"
        assert c.destination == "staging"
        assert c.session_id == "s-1"
        assert c.provenance.startswith("Weekly reflection for week ")


def test_reflection_collect_empty_store_returns_empty():
    contrib = ReflectionContributor(
        reflection_store=_StubReflectionStore([]),
        session_id="s-1",
    )
    assert contrib.collect() == []


def test_reflection_skips_malformed_week_key():
    store = _StubReflectionStore(
        [
            _StubReflectionResult(week_key="reflection-2026-W18"),
            _StubReflectionResult(week_key="not-a-week-key"),
        ]
    )
    contrib = ReflectionContributor(reflection_store=store, session_id="s-1")
    out = contrib.collect()
    assert [c.relpath for c in out] == [
        "bumba-contributions/staging/reflections/2026-W18.md",
    ]


def test_reflection_idempotent():
    store = _StubReflectionStore(
        [_StubReflectionResult(week_key="reflection-2026-W18")]
    )
    contrib = ReflectionContributor(reflection_store=store, session_id="s-1")
    a = contrib.collect()
    b = contrib.collect()
    assert [c.relpath for c in a] == [c.relpath for c in b]
    assert [c.body for c in a] == [c.body for c in b]


def test_reflection_rejects_none_store():
    with pytest.raises(ValueError, match="reflection_store"):
        ReflectionContributor(reflection_store=None, session_id="s-1")


# ---------------- ConsolidationContributor ---------------- #


def test_consolidation_collect_one_digest_returns_one_contribution(tmp_path):
    root = tmp_path / "consolidation"
    _seed_consolidation_digest(root, ["2026-05-01"])
    contrib = ConsolidationContributor(
        consolidation_output_dir=root,
        session_id="s-1",
    )
    out = contrib.collect()
    assert len(out) == 1
    c = out[0]
    assert c.relpath == (
        "bumba-contributions/curated/consolidation/2026-05-01-digest.md"
    )
    assert c.source == "consolidation"
    assert c.destination == "curated"
    assert c.session_id == "s-1"
    assert c.provenance.startswith("Consolidation digest from ")


def test_consolidation_missing_dir_returns_empty(tmp_path):
    missing = tmp_path / "no-consolidation"
    contrib = ConsolidationContributor(
        consolidation_output_dir=missing,
        session_id="s-1",
    )
    assert contrib.collect() == []


def test_consolidation_ignores_non_digest_files(tmp_path):
    root = tmp_path / "consolidation"
    _seed_consolidation_digest(root, ["2026-05-01"])
    (root / "stray-note.md").write_text("ignore", encoding="utf-8")
    contrib = ConsolidationContributor(
        consolidation_output_dir=root,
        session_id="s-1",
    )
    out = contrib.collect()
    assert len(out) == 1


def test_consolidation_since_filters_by_mtime(tmp_path):
    root = tmp_path / "consolidation"
    files = _seed_consolidation_digest(
        root, ["2026-04-29", "2026-04-30", "2026-05-01"]
    )
    old_t = 1_700_000_000.0
    new_t = 1_800_000_000.0
    os.utime(files[0], (old_t, old_t))
    os.utime(files[1], (new_t, new_t))
    os.utime(files[2], (new_t, new_t))
    contrib = ConsolidationContributor(
        consolidation_output_dir=root,
        session_id="s-1",
    )
    out = contrib.collect(since="2026-01-01T00:00:00Z")
    relpaths = sorted(c.relpath for c in out)
    assert relpaths == [
        "bumba-contributions/curated/consolidation/2026-04-30-digest.md",
        "bumba-contributions/curated/consolidation/2026-05-01-digest.md",
    ]


# ---------------- Protocol conformance ---------------- #


def test_all_contributors_satisfy_protocol(tmp_path):
    daily = DailyLogContributor(
        daily_log_root=tmp_path / "logs", session_id="s",
    )
    reflection = ReflectionContributor(
        reflection_store=_StubReflectionStore([]),
        session_id="s",
    )
    consolidation = ConsolidationContributor(
        consolidation_output_dir=tmp_path / "consolidation",
        session_id="s",
    )
    assert isinstance(daily, SecondBrainContributor)
    assert isinstance(reflection, SecondBrainContributor)
    assert isinstance(consolidation, SecondBrainContributor)


# ---------------- Registry integration ---------------- #


def test_registry_registers_all_three_and_collect_all_aggregates(tmp_path):
    log_root = tmp_path / "logs"
    _seed_daily_log(log_root, ["2026-05-01"])
    consolidation_dir = tmp_path / "consolidation"
    _seed_consolidation_digest(consolidation_dir, ["2026-05-01"])
    store = _StubReflectionStore(
        [_StubReflectionResult(week_key="reflection-2026-W18")]
    )
    reg = ContributorRegistry()
    reg.register(
        DailyLogContributor(daily_log_root=log_root, session_id="s")
    )
    reg.register(
        ReflectionContributor(reflection_store=store, session_id="s")
    )
    reg.register(
        ConsolidationContributor(
            consolidation_output_dir=consolidation_dir, session_id="s",
        )
    )
    assert [c.contributor_name for c in reg.all()] == [
        "consolidation",
        "daily_log",
        "reflection",
    ]
    out = reg.collect_all()
    assert len(out) == 3
    sources = sorted(c.source for c in out)
    assert sources == ["consolidation", "daily_log", "reflection"]


# ---------------- WikiRepo integration ---------------- #


def test_wiki_repo_writes_each_contribution_to_the_correct_subtree(tmp_path):
    """Each Contribution lands at the relpath the contributor advertised."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "bumba-contributions" / "staging" / "daily-logs").mkdir(parents=True)
    (vault / "bumba-contributions" / "staging" / "reflections").mkdir(parents=True)
    (vault / "bumba-contributions" / "curated" / "consolidation").mkdir(parents=True)
    log_root = tmp_path / "logs"
    _seed_daily_log(log_root, ["2026-05-01"])
    consolidation_dir = tmp_path / "consolidation"
    _seed_consolidation_digest(consolidation_dir, ["2026-05-01"])
    store = _StubReflectionStore(
        [_StubReflectionResult(week_key="reflection-2026-W18")]
    )
    contributors = [
        DailyLogContributor(daily_log_root=log_root, session_id="s"),
        ReflectionContributor(reflection_store=store, session_id="s"),
        ConsolidationContributor(
            consolidation_output_dir=consolidation_dir, session_id="s",
        ),
    ]
    repo = WikiRepo(vault)
    written: list[Path] = []
    for contrib in contributors:
        for c in contrib.collect():
            from bridge.second_brain import WikiNote
            note = WikiNote(
                relpath=c.relpath,
                content_body=c.body,
                source=c.source,
                session_id=c.session_id,
                authored_at=c.authored_at,
                provenance=c.provenance,
            )
            written.append(repo.write(note))
    assert (
        vault
        / "bumba-contributions"
        / "staging"
        / "daily-logs"
        / "2026-05-01.md"
    ).is_file()
    assert (
        vault
        / "bumba-contributions"
        / "staging"
        / "reflections"
        / "2026-W18.md"
    ).is_file()
    assert (
        vault
        / "bumba-contributions"
        / "curated"
        / "consolidation"
        / "2026-05-01-digest.md"
    ).is_file()
    # Frontmatter sanity on the daily-log mirror.
    daily_text = (
        vault
        / "bumba-contributions"
        / "staging"
        / "daily-logs"
        / "2026-05-01.md"
    ).read_text(encoding="utf-8")
    assert daily_text.startswith("---\n")
    assert "source: daily_log" in daily_text
    assert "schema_version: 1" in daily_text


# ---------------- Config integration ---------------- #


def test_bridge_config_exposes_contributor_flags():
    """All three granular flags advertised with default True."""
    from bridge.config import BridgeConfig

    cfg = BridgeConfig()
    assert cfg.second_brain_contributor_dailylog_enabled is True
    assert cfg.second_brain_contributor_reflection_enabled is True
    assert cfg.second_brain_contributor_consolidation_enabled is True
