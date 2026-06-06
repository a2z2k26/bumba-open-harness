"""Tests for bridge.specialist_retrieval — embedding-ranked specialist top-K.

Sprint #1112/4.06 (#2153). Covers:

- top-K ranking by cosine similarity (controlled mock embeddings)
- per-department index caching with file-change invalidation
- non-existent department raises informative ValueError
- k=0 returns []
- k > available specialists returns the full ranked roster
- ancillary no-prefix specialists are surfaced under engineering
- BridgeConfig.specialist_retrieval_enabled defaults to False
- Frontmatter parser handles both quoted and unquoted descriptions
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bridge.config import BridgeConfig
from bridge.specialist_retrieval import (
    SpecialistMatch,
    SpecialistRetriever,
    _cosine,
    _parse_frontmatter,
)


# ---------------------------------------------------------------------------
# Mock embedding engine
# ---------------------------------------------------------------------------


class _MockEmbeddings:
    """Tiny embedding stub — maps text fragments to fixed vectors so the test
    can assert ranking outcomes deterministically without loading a real
    model. Also records call counts so the caching test can verify that
    descriptions are embedded only once per department.
    """

    def __init__(self, mapping: dict[str, list[float]]) -> None:
        self._mapping = mapping
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        for key, vec in self._mapping.items():
            if key in text:
                return vec
        # Default — orthogonal-ish vector that scores ~0 against any keyed vec.
        return [0.0, 0.0, 1.0]


# ---------------------------------------------------------------------------
# Fixture: a fake ~/.claude/agents directory with three "design-*" files
# ---------------------------------------------------------------------------


@pytest.fixture
def agents_dir(tmp_path: Path) -> Path:
    """Create an agents directory with 3 design specialists + 1 unrelated."""
    d = tmp_path / "agents"
    d.mkdir()

    (d / "design-ui-designer.md").write_text(
        '---\nname: design-ui-designer\ndescription: "UI keyword designs interfaces"\n---\n\nbody\n',
        encoding="utf-8",
    )
    (d / "design-ux-researcher.md").write_text(
        "---\nname: design-ux-researcher\ndescription: UX keyword research interviews users\n---\n\nbody\n",
        encoding="utf-8",
    )
    (d / "design-visual-designer.md").write_text(
        '---\nname: design-visual-designer\ndescription: "VIS keyword visual brand"\n---\n\nbody\n',
        encoding="utf-8",
    )
    # An unrelated department — must not appear in design queries.
    (d / "engineering-code-reviewer.md").write_text(
        '---\nname: engineering-code-reviewer\ndescription: "ENG keyword reviews"\n---\n',
        encoding="utf-8",
    )
    return d


@pytest.fixture
def mock_embeddings() -> _MockEmbeddings:
    """Three orthogonal unit vectors so cosine ordering is fully controlled."""
    return _MockEmbeddings(
        {
            "UI keyword": [1.0, 0.0, 0.0],
            "UX keyword": [0.0, 1.0, 0.0],
            "VIS keyword": [0.0, 0.0, 1.0],
            "ENG keyword": [0.5, 0.5, 0.5],
            "FASTAPI keyword": [1.0, 1.0, 0.0],
            "BACKEND keyword": [1.0, 0.0, 1.0],
            # Directive vectors — each aligns strongest with one specialist.
            "DIRECTIVE-UI": [1.0, 0.0, 0.0],
            "DIRECTIVE-UX": [0.0, 1.0, 0.0],
            "DIRECTIVE-BACKEND": [1.0, 0.0, 1.0],
        }
    )


# ---------------------------------------------------------------------------
# _parse_frontmatter
# ---------------------------------------------------------------------------


class TestParseFrontmatter:
    def test_unquoted(self) -> None:
        text = "---\nname: foo\ndescription: bar baz\n---\nbody\n"
        assert _parse_frontmatter(text) == {"name": "foo", "description": "bar baz"}

    def test_double_quoted(self) -> None:
        text = '---\nname: "foo"\ndescription: "bar baz"\n---\nbody\n'
        assert _parse_frontmatter(text) == {"name": "foo", "description": "bar baz"}

    def test_no_frontmatter(self) -> None:
        assert _parse_frontmatter("just body text\n") == {}


# ---------------------------------------------------------------------------
# _cosine
# ---------------------------------------------------------------------------


class TestCosine:
    def test_identical(self) -> None:
        assert _cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal(self) -> None:
        assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_zero_vector(self) -> None:
        assert _cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


# ---------------------------------------------------------------------------
# SpecialistRetriever.retrieve_top_k
# ---------------------------------------------------------------------------


class TestRetrieveTopK:
    def test_returns_top_k_by_cosine(
        self, agents_dir: Path, mock_embeddings: _MockEmbeddings
    ) -> None:
        retriever = SpecialistRetriever(mock_embeddings, agents_dir)
        result = retriever.retrieve_top_k("DIRECTIVE-UI text", "design", k=1)

        assert len(result) == 1
        assert isinstance(result[0], SpecialistMatch)
        assert result[0].name == "design-ui-designer"
        # Identical vectors → score 1.0.
        assert result[0].score == pytest.approx(1.0)

    def test_returns_full_ranking_when_k_exceeds_roster(
        self, agents_dir: Path, mock_embeddings: _MockEmbeddings
    ) -> None:
        retriever = SpecialistRetriever(mock_embeddings, agents_dir)
        result = retriever.retrieve_top_k(
            "DIRECTIVE-UX text", "design", k=100,
        )

        assert len(result) == 3
        # UX directive aligns with UX researcher.
        assert result[0].name == "design-ux-researcher"
        # Scores are descending.
        for i in range(len(result) - 1):
            assert result[i].score >= result[i + 1].score

    def test_k_zero_returns_empty(
        self, agents_dir: Path, mock_embeddings: _MockEmbeddings
    ) -> None:
        retriever = SpecialistRetriever(mock_embeddings, agents_dir)
        assert retriever.retrieve_top_k("anything", "design", k=0) == []

    def test_k_negative_raises(
        self, agents_dir: Path, mock_embeddings: _MockEmbeddings
    ) -> None:
        retriever = SpecialistRetriever(mock_embeddings, agents_dir)
        with pytest.raises(ValueError, match="k must be >= 0"):
            retriever.retrieve_top_k("x", "design", k=-1)

    def test_nonexistent_department_raises(
        self, agents_dir: Path, mock_embeddings: _MockEmbeddings
    ) -> None:
        retriever = SpecialistRetriever(mock_embeddings, agents_dir)
        with pytest.raises(ValueError) as excinfo:
            retriever.retrieve_top_k("x", "nonexistent", k=3)
        # Error message includes the scanned glob for operator debugging.
        assert "nonexistent-*.md" in str(excinfo.value)

    def test_missing_agents_dir_raises_on_first_call(
        self, tmp_path: Path, mock_embeddings: _MockEmbeddings
    ) -> None:
        retriever = SpecialistRetriever(
            mock_embeddings, tmp_path / "does-not-exist",
        )
        with pytest.raises(ValueError):
            retriever.retrieve_top_k("x", "design", k=3)

    def test_only_filters_department_prefix(
        self, agents_dir: Path, mock_embeddings: _MockEmbeddings
    ) -> None:
        """``design-*`` must not pull in ``engineering-*`` files."""
        retriever = SpecialistRetriever(mock_embeddings, agents_dir)
        result = retriever.retrieve_top_k("anything", "design", k=10)
        names = {m.name for m in result}
        assert "engineering-code-reviewer" not in names
        assert names == {
            "design-ui-designer",
            "design-ux-researcher",
            "design-visual-designer",
        }

    def test_engineering_includes_ancillary_no_prefix_specialists(
        self, agents_dir: Path, mock_embeddings: _MockEmbeddings
    ) -> None:
        (agents_dir / "fastapi-pro-developer.md").write_text(
            '---\nname: fastapi-pro-developer\ndescription: "FASTAPI keyword backend APIs"\n---\n',
            encoding="utf-8",
        )

        retriever = SpecialistRetriever(mock_embeddings, agents_dir)
        result = retriever.retrieve_top_k("DIRECTIVE-BACKEND text", "engineering", k=10)
        names = {m.name for m in result}

        assert "engineering-code-reviewer" in names
        assert "fastapi-pro-developer" in names

    def test_non_engineering_excludes_ancillary_no_prefix_specialists(
        self, agents_dir: Path, mock_embeddings: _MockEmbeddings
    ) -> None:
        (agents_dir / "fastapi-pro-developer.md").write_text(
            '---\nname: fastapi-pro-developer\ndescription: "FASTAPI keyword backend APIs"\n---\n',
            encoding="utf-8",
        )

        retriever = SpecialistRetriever(mock_embeddings, agents_dir)
        result = retriever.retrieve_top_k("DIRECTIVE-BACKEND text", "design", k=10)
        names = {m.name for m in result}

        assert "fastapi-pro-developer" not in names


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


class TestCaching:
    def test_second_call_does_not_reembed_descriptions(
        self, agents_dir: Path, mock_embeddings: _MockEmbeddings
    ) -> None:
        retriever = SpecialistRetriever(mock_embeddings, agents_dir)

        retriever.retrieve_top_k("DIRECTIVE-UI a", "design", k=3)
        # First call: 3 description embeds + 1 directive embed = 4 calls.
        first_round = list(mock_embeddings.calls)
        description_count = sum(
            1 for c in first_round
            if "keyword" in c and "DIRECTIVE" not in c
        )
        assert description_count == 3, (
            f"expected 3 description embeds, saw {first_round}"
        )

        # Second call: should only embed the new directive (descriptions cached).
        mock_embeddings.calls.clear()
        retriever.retrieve_top_k("DIRECTIVE-UX b", "design", k=3)
        second_round = mock_embeddings.calls
        description_count_2 = sum(
            1 for c in second_round
            if "keyword" in c and "DIRECTIVE" not in c
        )
        assert description_count_2 == 0, (
            f"expected 0 re-embeds, saw {second_round}"
        )

    def test_agent_file_edit_invalidates_cached_department_index(
        self, agents_dir: Path, mock_embeddings: _MockEmbeddings
    ) -> None:
        retriever = SpecialistRetriever(mock_embeddings, agents_dir)

        first = retriever.retrieve_top_k("DIRECTIVE-UI a", "design", k=1)
        assert first[0].name == "design-ui-designer"

        (agents_dir / "design-ui-designer.md").write_text(
            '---\nname: design-ui-designer\ndescription: "UX keyword updated interface research"\n---\n\nbody\n',
            encoding="utf-8",
        )

        second = retriever.retrieve_top_k("DIRECTIVE-UX b", "design", k=1)
        assert second[0].name == "design-ui-designer"

    def test_new_agent_file_invalidates_cached_department_index(
        self, agents_dir: Path, mock_embeddings: _MockEmbeddings
    ) -> None:
        retriever = SpecialistRetriever(mock_embeddings, agents_dir)

        first = retriever.retrieve_top_k("DIRECTIVE-BACKEND a", "engineering", k=10)
        first_names = {m.name for m in first}
        assert "backend-architect" not in first_names

        (agents_dir / "backend-architect.md").write_text(
            '---\nname: backend-architect\ndescription: "BACKEND keyword service boundaries"\n---\n\nbody\n',
            encoding="utf-8",
        )

        second = retriever.retrieve_top_k("DIRECTIVE-BACKEND b", "engineering", k=10)
        second_names = {m.name for m in second}
        assert "backend-architect" in second_names


# ---------------------------------------------------------------------------
# BridgeConfig flag default
# ---------------------------------------------------------------------------


class TestConfigFlagDefault:
    def test_specialist_retrieval_enabled_defaults_false(self) -> None:
        cfg = BridgeConfig()
        assert cfg.specialist_retrieval_enabled is False
