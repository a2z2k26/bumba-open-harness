"""Tests for command_suggester.py: keyword-based command/skill discovery."""

from __future__ import annotations


import pytest

from bridge.command_suggester import CommandSuggester, _extract_keywords, _jaccard


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def test_extract_keywords():
    """Keywords are lowercase tokens of 3+ characters."""
    kw = _extract_keywords("Run a full health-check on the system")
    assert "run" in kw
    assert "full" in kw
    assert "health" in kw
    assert "check" in kw
    assert "system" in kw
    # Short tokens excluded
    assert "on" not in kw
    assert "the" not in kw


def test_jaccard_identical():
    """Identical sets have Jaccard = 1.0."""
    a = {"foo", "bar"}
    b = frozenset({"foo", "bar"})
    assert _jaccard(a, b) == pytest.approx(1.0)


def test_jaccard_disjoint():
    """Disjoint sets have Jaccard = 0.0."""
    a = {"foo", "bar"}
    b = frozenset({"baz", "qux"})
    assert _jaccard(a, b) == pytest.approx(0.0)


def test_jaccard_partial():
    """Partial overlap gives expected similarity."""
    a = {"foo", "bar", "baz"}
    b = frozenset({"foo", "qux"})
    # intersection=1, union=4
    assert _jaccard(a, b) == pytest.approx(0.25)


def test_jaccard_empty():
    """Empty sets return 0."""
    assert _jaccard(set(), frozenset()) == 0.0


# ---------------------------------------------------------------------------
# CommandSuggester with real .md files
# ---------------------------------------------------------------------------

@pytest.fixture
def commands_dir(tmp_path):
    """Create a temp commands directory with sample .md files."""
    d = tmp_path / "commands"
    d.mkdir()
    (d / "deploy.md").write_text(
        "---\ndescription: Deploy the bridge to production\n---\nDeploy instructions."
    )
    (d / "health-check.md").write_text(
        "---\ndescription: Run a full system health check\n---\nCheck health."
    )
    (d / "search-knowledge.md").write_text(
        "---\ndescription: Search the knowledge store for information\n---\nSearch."
    )
    return d


@pytest.fixture
def skills_dir(tmp_path):
    """Create a temp skills directory with sample SKILL.md files."""
    d = tmp_path / "skills"
    d.mkdir()
    (d / "git-workflows").mkdir()
    (d / "git-workflows" / "SKILL.md").write_text(
        "---\nname: git-workflows\ndescription: Advanced git branching and merge strategies\n---\nGit."
    )
    (d / "testing-patterns").mkdir()
    (d / "testing-patterns" / "SKILL.md").write_text(
        "---\nname: testing-patterns\ndescription: Test fixture patterns and pytest best practices\n---\nTest."
    )
    return d


@pytest.fixture
def suggester(commands_dir, skills_dir):
    return CommandSuggester(commands_dir, skills_dir)


def test_index_built(suggester):
    """Suggester indexes all commands and skills."""
    assert len(suggester._index) == 5


def test_suggest_keyword_match(suggester):
    """Suggestions based on keyword overlap with message."""
    suggestions = suggester.suggest("how do I deploy the bridge?")
    assert "deploy" in suggestions


def test_suggest_health(suggester):
    """Health-related message suggests health-check command."""
    suggestions = suggester.suggest("check system health and status")
    assert "health-check" in suggestions


def test_suggest_no_match(suggester):
    """Unrelated message returns no suggestions."""
    suggestions = suggester.suggest("hello there")
    assert len(suggestions) == 0


def test_suggest_tool_pattern(suggester):
    """Tool-use patterns trigger related suggestions."""
    suggestions = suggester.suggest("working on code", tools_used=["git"])
    assert any("git" in s for s in suggestions)


def test_suggest_complexity_signal(suggester):
    """High num_turns suggests planning command."""
    suggestions = suggester.suggest("complex refactoring task", num_turns=8)
    assert "orc/plan-feature" in suggestions


def test_suggest_max_three(suggester):
    """At most 3 suggestions returned."""
    suggestions = suggester.suggest(
        "deploy health check search knowledge git test",
        tools_used=["git", "pytest"],
        num_turns=10,
    )
    assert len(suggestions) <= 3


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_dirs(tmp_path):
    """Suggester handles empty/missing directories gracefully."""
    empty = tmp_path / "empty"
    empty.mkdir()
    s = CommandSuggester(empty, empty)
    assert s._index == []
    assert s.suggest("anything") == []


def test_malformed_frontmatter(tmp_path):
    """Suggester skips files with bad frontmatter."""
    d = tmp_path / "cmds"
    d.mkdir()
    (d / "bad.md").write_text("no frontmatter here")
    (d / "also-bad.md").write_text("---\ninvalid: [yaml: broken\n---\n")
    s = CommandSuggester(d, tmp_path / "nonexistent")
    assert len(s._index) == 0
