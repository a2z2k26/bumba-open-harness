"""Tests for bridge.paths.agent_root — closes #1492.

The helper resolves runtime tree root via env var → cwd → cwd/agent →
canonical fallback. Production callers depend on the cwd branch (which
the launchd plist's WorkingDirectory drives); tests cover all four.
"""
from __future__ import annotations

from pathlib import Path


from bridge.paths import _CANONICAL_AGENT_ROOT, _CANONICAL_DATA_ROOT, agent_root, data_root


def _make_fake_agent_tree(root: Path) -> None:
    """Create the minimum structure that ``agent_root()`` validates against."""
    (root / "bridge").mkdir(parents=True, exist_ok=True)
    (root / "bridge" / "__init__.py").write_text("")


class TestAgentRoot:
    def test_env_var_override_wins(self, tmp_path, monkeypatch):
        """BUMBA_AGENT_ROOT, when set and pointing at a real agent tree, takes priority."""
        custom = tmp_path / "custom-agent"
        _make_fake_agent_tree(custom)
        monkeypatch.setenv("BUMBA_AGENT_ROOT", str(custom))
        # cwd is somewhere else; env var should still win.
        monkeypatch.chdir(tmp_path)
        assert agent_root() == custom

    def test_env_var_pointing_at_non_agent_tree_falls_through(self, tmp_path, monkeypatch):
        """A typo'd env var (no bridge/__init__.py present) falls through to cwd resolution."""
        bogus = tmp_path / "bogus"
        bogus.mkdir()
        monkeypatch.setenv("BUMBA_AGENT_ROOT", str(bogus))
        # cwd is also not an agent tree → falls through to canonical.
        monkeypatch.chdir(tmp_path)
        assert agent_root() == _CANONICAL_AGENT_ROOT

    def test_cwd_is_agent_tree(self, tmp_path, monkeypatch):
        """cwd contains bridge/__init__.py → cwd wins."""
        monkeypatch.delenv("BUMBA_AGENT_ROOT", raising=False)
        _make_fake_agent_tree(tmp_path)
        monkeypatch.chdir(tmp_path)
        assert agent_root() == tmp_path

    def test_cwd_has_agent_subtree(self, tmp_path, monkeypatch):
        """cwd is the repo root; cwd/agent contains bridge/__init__.py."""
        monkeypatch.delenv("BUMBA_AGENT_ROOT", raising=False)
        _make_fake_agent_tree(tmp_path / "agent")
        monkeypatch.chdir(tmp_path)
        assert agent_root() == tmp_path / "agent"

    def test_canonical_fallback(self, tmp_path, monkeypatch):
        """Empty env var + cwd has no agent tree → canonical fallback."""
        monkeypatch.delenv("BUMBA_AGENT_ROOT", raising=False)
        # tmp_path has no bridge/ or agent/bridge/ — falls through.
        monkeypatch.chdir(tmp_path)
        assert agent_root() == _CANONICAL_AGENT_ROOT

    def test_returns_path_not_string(self, tmp_path, monkeypatch):
        """Always returns Path so callers can compose with ``/``."""
        monkeypatch.delenv("BUMBA_AGENT_ROOT", raising=False)
        monkeypatch.chdir(tmp_path)
        result = agent_root()
        assert isinstance(result, Path)

    def test_cwd_wins_over_cwd_agent(self, tmp_path, monkeypatch):
        """If both cwd AND cwd/agent are agent trees, cwd takes priority (innermost wins)."""
        monkeypatch.delenv("BUMBA_AGENT_ROOT", raising=False)
        _make_fake_agent_tree(tmp_path)
        _make_fake_agent_tree(tmp_path / "agent")
        monkeypatch.chdir(tmp_path)
        # cwd is checked before cwd/agent, so cwd wins.
        assert agent_root() == tmp_path

    def test_env_var_with_tilde_expands(self, tmp_path, monkeypatch):
        """env var supports ~ expansion."""
        # Create a fake agent tree under what we'll call HOME.
        fake_home = tmp_path / "home"
        agent_dir = fake_home / "agent"
        _make_fake_agent_tree(agent_dir)
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setenv("BUMBA_AGENT_ROOT", "~/agent")
        monkeypatch.chdir(tmp_path)
        assert agent_root() == agent_dir


class TestDataRoot:
    """Issue #1501 F4 — data_root() resolves via env var or canonical fallback."""

    def test_env_var_override_wins(self, tmp_path, monkeypatch):
        """BUMBA_DATA_ROOT, when set and pointing at a real dir, takes priority."""
        custom = tmp_path / "custom-data"
        custom.mkdir()
        monkeypatch.setenv("BUMBA_DATA_ROOT", str(custom))
        assert data_root() == custom

    def test_env_var_pointing_at_missing_dir_falls_through(self, tmp_path, monkeypatch):
        """env var must point at a real dir; otherwise falls through to canonical."""
        monkeypatch.setenv("BUMBA_DATA_ROOT", str(tmp_path / "does-not-exist"))
        assert data_root() == _CANONICAL_DATA_ROOT

    def test_canonical_fallback(self, monkeypatch):
        """No env var → canonical /opt/bumba-harness/data."""
        monkeypatch.delenv("BUMBA_DATA_ROOT", raising=False)
        assert data_root() == _CANONICAL_DATA_ROOT

    def test_returns_path_not_string(self, monkeypatch):
        """Always returns Path so callers can compose with /."""
        monkeypatch.delenv("BUMBA_DATA_ROOT", raising=False)
        assert isinstance(data_root(), Path)
