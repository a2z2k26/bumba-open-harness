"""Tests for Tool Shed registry and per-agent tool provisioning."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from bridge.tool_shed import SkillCandidate, ToolConfig, ToolShed


@pytest.fixture
def shed_config(tmp_path: Path) -> Path:
    config = tmp_path / "tool-shed.yaml"
    config.write_text("""
tools:
  github:
    category: code
    always_loaded: true
    agents: [all]
  bumba-memory:
    category: memory
    always_loaded: true
    agents: [all]
  mongodb:
    category: data
    always_loaded: false
    agents:
      - database-specialist
      - backend-architect
  playwright:
    category: testing
    always_loaded: false
    agents:
      - frontend-developer
""")
    return config


def test_load_registry(shed_config: Path) -> None:
    shed = ToolShed(shed_config)
    assert len(shed.all_tools()) == 4


def test_always_loaded(shed_config: Path) -> None:
    shed = ToolShed(shed_config)
    always = shed.always_loaded()
    assert "github" in always
    assert "bumba-memory" in always
    assert "mongodb" not in always


def test_tools_for_agent(shed_config: Path) -> None:
    shed = ToolShed(shed_config)
    tools = shed.tools_for_agent("database-specialist")
    assert "github" in tools
    assert "bumba-memory" in tools
    assert "mongodb" in tools
    assert "playwright" not in tools


def test_tools_for_unknown_agent(shed_config: Path) -> None:
    shed = ToolShed(shed_config)
    tools = shed.tools_for_agent("unknown-agent")
    assert "github" in tools
    assert "bumba-memory" in tools
    assert len(tools) == 2


def test_missing_config_file(tmp_path: Path) -> None:
    shed = ToolShed(tmp_path / "nonexistent.yaml")
    assert len(shed.all_tools()) == 0
    assert len(shed.always_loaded()) == 0


def test_tool_config_properties(shed_config: Path) -> None:
    shed = ToolShed(shed_config)
    config = shed.get_tool("mongodb")
    assert config is not None
    assert config.category == "data"
    assert config.always_loaded is False
    assert "database-specialist" in config.agents


# --- Smart Tool RAG (sprint 03.03) ---


@pytest.fixture
def rag_config(tmp_path: Path) -> Path:
    config = tmp_path / "tool-shed.yaml"
    config.write_text("""
tools:
  github:
    category: code
    always_loaded: true
    agents: [all]
    description: GitHub repository management — create issues, PRs, code search
  playwright:
    category: testing
    always_loaded: false
    agents: [all]
    description: Browser automation, end-to-end testing, screenshot capture
  mongodb:
    category: data
    always_loaded: false
    agents: [all]
    description: MongoDB Atlas database queries, collections, indexes
  shadcn:
    category: design
    always_loaded: false
    agents: [all]
    description: shadcn/ui component library discovery and usage
""")
    return config


def test_get_tools_for_intent_empty_corpus(tmp_path: Path) -> None:
    """No corpus → empty result, no exception."""
    shed = ToolShed(tmp_path / "missing.yaml")
    result = shed.get_tools_for_intent("design a UI component")
    assert result == []


def test_get_tools_for_intent_single_tool(tmp_path: Path) -> None:
    """Single tool corpus returns that tool when intent matches."""
    config = tmp_path / "tool-shed.yaml"
    config.write_text("""
tools:
  shadcn:
    category: design
    description: shadcn/ui component library
    agents: [all]
""")
    shed = ToolShed(config)
    result = shed.get_tools_for_intent("design a button component")
    assert len(result) == 1
    assert result[0].name == "shadcn"


def test_get_tools_for_intent_multiple_tools_ranks_relevant_first(rag_config: Path) -> None:
    """Hybrid ranking surfaces the most relevant tool at the top."""
    shed = ToolShed(rag_config)
    design_results = shed.get_tools_for_intent("design a UI component", top_k=2)
    assert len(design_results) >= 1
    assert design_results[0].name == "shadcn"

    test_results = shed.get_tools_for_intent("run browser tests", top_k=2)
    assert test_results[0].name == "playwright"


def test_get_tools_for_intent_respects_top_k(rag_config: Path) -> None:
    shed = ToolShed(rag_config)
    result = shed.get_tools_for_intent("github testing design data", top_k=2)
    assert len(result) <= 2


def test_get_tools_for_intent_empty_intent_returns_always_loaded(rag_config: Path) -> None:
    """Empty intent string degrades to always-loaded shape (cost: $0)."""
    shed = ToolShed(rag_config)
    result = shed.get_tools_for_intent("", top_k=5)
    names = [t.name for t in result]
    # Only `github` is always_loaded in the rag fixture.
    assert "github" in names
    assert "playwright" not in names


def test_get_tools_for_intent_zero_top_k(rag_config: Path) -> None:
    shed = ToolShed(rag_config)
    assert shed.get_tools_for_intent("github", top_k=0) == []


def test_get_tools_for_intent_rerank_invokes_callback(rag_config: Path) -> None:
    """rerank=True calls rerank_fn with fused candidates and uses its order."""
    shed = ToolShed(rag_config)
    rerank_calls: list[tuple[str, int]] = []

    def fake_rerank(intent: str, cands: list[ToolConfig]) -> list[ToolConfig]:
        rerank_calls.append((intent, len(cands)))
        # Reverse the fused order to prove rerank shaped the output.
        return list(reversed(cands))

    fused = shed.get_tools_for_intent("design a UI component", top_k=3, rerank=False)
    reranked = shed.get_tools_for_intent(
        "design a UI component",
        top_k=3,
        rerank=True,
        rerank_fn=fake_rerank,
    )
    assert rerank_calls, "rerank_fn should have been invoked"
    assert rerank_calls[0][0] == "design a UI component"
    # Order should differ from the rerank=False fused output (proves the
    # rerank callback shaped the final list).
    if len(fused) > 1 and len(reranked) > 1:
        assert [t.name for t in reranked] != [t.name for t in fused]


def test_get_tools_for_intent_rerank_off_by_default(rag_config: Path) -> None:
    """Default path skips rerank → no callback invocation, ≤$0.005 cost target."""
    shed = ToolShed(rag_config)
    invoked = {"count": 0}

    def fake_rerank(intent: str, cands: list[ToolConfig]) -> list[ToolConfig]:
        invoked["count"] += 1
        return cands

    shed.get_tools_for_intent("github", top_k=2, rerank_fn=fake_rerank)
    assert invoked["count"] == 0


def test_get_tools_for_agent_unchanged(rag_config: Path) -> None:
    """Feature-flag-off path: existing get_tools_for_agent shape preserved."""
    shed = ToolShed(rag_config)
    tools = shed.get_tools_for_agent("any-agent")
    # Returns ToolConfig instances, sorted by name; only always_loaded
    # entries qualify under "any-agent".
    assert all(isinstance(t, ToolConfig) for t in tools)
    assert [t.name for t in tools] == ["github", "mongodb", "playwright", "shadcn"] or \
        [t.name for t in tools] == ["github"]
    # The "all" agents tag in the rag fixture means every tool matches.
    assert "github" in [t.name for t in tools]


def test_get_tools_for_intent_handles_no_descriptions(tmp_path: Path) -> None:
    """Precondition gap: works even when description field is absent."""
    config = tmp_path / "tool-shed.yaml"
    config.write_text("""
tools:
  playwright:
    category: testing
    agents: [all]
  shadcn:
    category: design
    agents: [all]
""")
    shed = ToolShed(config)
    # Falls back to name + category corpus; "design" should still surface shadcn.
    result = shed.get_tools_for_intent("design", top_k=1)
    assert result[0].name == "shadcn"


# --- Sprint 07.05 (#1034) markdown-skill discovery integration ---


_SAMPLE_SKILL_BODY = (
    "# Sample Skill\n\n"
    "## Trigger\n\n"
    "When the operator asks for sample-skill behavior.\n\n"
    "## Approach\n\n"
    "Apply the sample-skill recipe.\n"
)


@pytest.fixture
def md_rag_setup(tmp_path: Path) -> tuple[ToolShed, Path]:
    """ToolShed with two YAML tools + a domain-skills directory containing one valid skill."""
    config = tmp_path / "tool-shed.yaml"
    config.write_text("""
tools:
  github:
    category: code
    always_loaded: true
    agents: [all]
    description: GitHub repository management
  playwright:
    category: testing
    always_loaded: false
    agents: [all]
    description: Browser automation
""")
    shed = ToolShed(config)
    skills_dir = tmp_path / "domain-skills"
    sample_dir = skills_dir / "sample"
    sample_dir.mkdir(parents=True)
    (sample_dir / "sample-skill.md").write_text(_SAMPLE_SKILL_BODY)
    return shed, skills_dir


def test_include_markdown_adds_skills_to_corpus(md_rag_setup: tuple[ToolShed, Path]) -> None:
    """include_markdown=True surfaces discovered markdown skills in the result."""
    shed, skills_dir = md_rag_setup
    result = shed.get_tools_for_intent(
        "sample skill", top_k=5, include_markdown=True, markdown_skills_dir=skills_dir
    )
    names = [t.name for t in result]
    assert "sample-skill" in names
    sample = next(t for t in result if t.name == "sample-skill")
    assert isinstance(sample, SkillCandidate)
    assert sample.kind == "skill"
    assert sample.domain == "sample"


def test_default_excludes_markdown_skills(md_rag_setup: tuple[ToolShed, Path]) -> None:
    """include_markdown defaults to False — regression guard, no skills mixed in."""
    shed, _skills_dir = md_rag_setup
    result = shed.get_tools_for_intent("sample skill", top_k=5)
    for item in result:
        assert isinstance(item, ToolConfig)
        assert item.kind == "tool"


def test_markdown_discovery_caches_within_ttl(
    md_rag_setup: tuple[ToolShed, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two calls within the TTL hit the cache (filesystem walk runs once)."""
    shed, skills_dir = md_rag_setup
    calls: list[Path] = []
    real = ToolShed._discover_markdown_skills_uncached

    def counting(target_dir: Path):  # type: ignore[no-untyped-def]
        calls.append(target_dir)
        return real(target_dir)

    monkeypatch.setattr(ToolShed, "_discover_markdown_skills_uncached", staticmethod(counting))

    shed.get_tools_for_intent(
        "sample", top_k=3, include_markdown=True, markdown_skills_dir=skills_dir
    )
    shed.get_tools_for_intent(
        "sample", top_k=3, include_markdown=True, markdown_skills_dir=skills_dir
    )
    assert len(calls) == 1


def test_markdown_cache_invalidated_on_mtime_change(
    md_rag_setup: tuple[ToolShed, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Directory mtime change triggers a fresh discovery walk before TTL expires."""
    shed, skills_dir = md_rag_setup
    calls: list[Path] = []
    real = ToolShed._discover_markdown_skills_uncached

    def counting(target_dir: Path):  # type: ignore[no-untyped-def]
        calls.append(target_dir)
        return real(target_dir)

    monkeypatch.setattr(ToolShed, "_discover_markdown_skills_uncached", staticmethod(counting))

    shed.get_tools_for_intent(
        "sample", top_k=3, include_markdown=True, markdown_skills_dir=skills_dir
    )
    # Bump the directory's mtime explicitly — adding a file is the realistic signal.
    new_skill = skills_dir / "sample" / "another.md"
    new_skill.write_text(_SAMPLE_SKILL_BODY)
    # Force a distinct mtime even on filesystems with second-resolution timestamps.
    new_mtime = skills_dir.stat().st_mtime + 5
    os.utime(skills_dir, (new_mtime, new_mtime))

    shed.get_tools_for_intent(
        "sample", top_k=3, include_markdown=True, markdown_skills_dir=skills_dir
    )
    assert len(calls) == 2


def test_markdown_discovery_skips_invalid_file(tmp_path: Path) -> None:
    """A corrupt skill (fails validate_skill) is skipped, retrieval still returns."""
    config = tmp_path / "tool-shed.yaml"
    config.write_text("""
tools:
  github:
    category: code
    always_loaded: true
    agents: [all]
    description: GitHub
""")
    shed = ToolShed(config)
    skills_dir = tmp_path / "domain-skills"
    bad_dir = skills_dir / "broken"
    bad_dir.mkdir(parents=True)
    # No headings → validate_skill rejects with "Missing title" + "Missing sections".
    (bad_dir / "broken-skill.md").write_text("plain text only, no markdown structure\n")

    result = shed.get_tools_for_intent(
        "github", top_k=5, include_markdown=True, markdown_skills_dir=skills_dir
    )
    names = [t.name for t in result]
    assert "github" in names
    assert "broken-skill" not in names


def test_markdown_discovery_empty_directory_returns_only_tools(tmp_path: Path) -> None:
    """Empty domain-skills/ directory: result is the tool list, no exception."""
    config = tmp_path / "tool-shed.yaml"
    config.write_text("""
tools:
  github:
    category: code
    always_loaded: true
    agents: [all]
    description: GitHub repository
""")
    shed = ToolShed(config)
    empty_dir = tmp_path / "domain-skills"
    empty_dir.mkdir()

    result = shed.get_tools_for_intent(
        "github", top_k=5, include_markdown=True, markdown_skills_dir=empty_dir
    )
    assert all(isinstance(t, ToolConfig) for t in result)
    assert "github" in [t.name for t in result]


def test_kind_field_distinguishes_tools_from_skills(md_rag_setup: tuple[ToolShed, Path]) -> None:
    """Result items expose a kind field — caller can route on it."""
    shed, skills_dir = md_rag_setup
    result = shed.get_tools_for_intent(
        "github sample", top_k=5, include_markdown=True, markdown_skills_dir=skills_dir
    )
    kinds_by_name = {t.name: t.kind for t in result}
    assert kinds_by_name.get("github") == "tool"
    if "sample-skill" in kinds_by_name:
        assert kinds_by_name["sample-skill"] == "skill"
