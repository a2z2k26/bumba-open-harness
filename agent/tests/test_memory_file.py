"""Tests for bridge.memory_file.MemoryFile (Sprint 11, issue #143; renamed Sprint 05.06)."""

from __future__ import annotations

import pytest
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_index(tmp_path: Path):
    from bridge.memory_file import MemoryFile
    return MemoryFile(tmp_path / "memory")


def _make_entry(key: str = "k", value: str = "v", category: str = "general"):
    from bridge.memory_file import MemoryEntry
    return MemoryEntry(key=key, value=value, category=category)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_max_lines(self):
        from bridge.memory_file import MemoryFile
        assert MemoryFile.MAX_LINES == 200

    def test_max_bytes(self):
        from bridge.memory_file import MemoryFile
        assert MemoryFile.MAX_BYTES == 25_000


# ---------------------------------------------------------------------------
# read()
# ---------------------------------------------------------------------------

class TestRead:
    def test_read_returns_empty_string_if_missing(self, tmp_path):
        idx = _make_index(tmp_path)
        assert idx.read() == ""

    def test_read_returns_file_content(self, tmp_path):
        idx = _make_index(tmp_path)
        idx._memory_dir.mkdir(parents=True, exist_ok=True)
        idx._path.write_text("hello world", encoding="utf-8")
        assert idx.read() == "hello world"


# ---------------------------------------------------------------------------
# Parent directory creation
# ---------------------------------------------------------------------------

class TestDirectoryCreation:
    def test_update_creates_parent_directory(self, tmp_path):
        idx = _make_index(tmp_path)
        # memory/ dir does NOT exist yet
        assert not idx._memory_dir.exists()
        idx.update([_make_entry()])
        assert idx._memory_dir.exists()


# ---------------------------------------------------------------------------
# update()
# ---------------------------------------------------------------------------

class TestUpdate:
    def test_update_writes_entries(self, tmp_path):
        idx = _make_index(tmp_path)
        entry = _make_entry(key="name", value="the operator", category="person")
        idx.update([entry])
        content = idx.read()
        assert "name" in content
        assert "the operator" in content
        assert "person" in content

    def test_update_calls_truncate_if_needed(self, tmp_path, monkeypatch):
        idx = _make_index(tmp_path)
        calls = []
        monkeypatch.setattr(idx, "truncate_if_needed", lambda: calls.append(1) or False)
        idx.update([_make_entry()])
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# truncate_if_needed()
# ---------------------------------------------------------------------------

class TestTruncateIfNeeded:
    def test_returns_false_if_under_limits(self, tmp_path):
        idx = _make_index(tmp_path)
        idx._memory_dir.mkdir(parents=True, exist_ok=True)
        idx._path.write_text("short content\n", encoding="utf-8")
        assert idx.truncate_if_needed() is False

    def test_returns_false_if_file_missing(self, tmp_path):
        idx = _make_index(tmp_path)
        assert idx.truncate_if_needed() is False

    def test_truncates_to_max_lines(self, tmp_path):
        from bridge.memory_file import MemoryFile
        idx = _make_index(tmp_path)
        idx._memory_dir.mkdir(parents=True, exist_ok=True)
        # Write 250 lines
        lines = [f"line {i}\n" for i in range(250)]
        idx._path.write_text("".join(lines), encoding="utf-8")
        result = idx.truncate_if_needed()
        assert result is True
        written = idx._path.read_text(encoding="utf-8")
        assert len(written.splitlines()) == MemoryFile.MAX_LINES

    def test_truncates_to_max_bytes(self, tmp_path):
        from bridge.memory_file import MemoryFile
        idx = _make_index(tmp_path)
        idx._memory_dir.mkdir(parents=True, exist_ok=True)
        # Write content that exceeds 25KB — each line ~100 bytes, 300 lines = 30KB
        content = ("x" * 99 + "\n") * 300
        idx._path.write_text(content, encoding="utf-8")
        result = idx.truncate_if_needed()
        assert result is True
        written = idx._path.read_bytes()
        assert len(written) <= MemoryFile.MAX_BYTES


# ---------------------------------------------------------------------------
# get_memory_context()
# ---------------------------------------------------------------------------

class TestGetMemoryContext:
    def test_returns_content_when_under_limit(self, tmp_path):
        idx = _make_index(tmp_path)
        idx._memory_dir.mkdir(parents=True, exist_ok=True)
        idx._path.write_text("# Memory\nSome content", encoding="utf-8")
        ctx = idx.get_memory_context()
        assert "Memory" in ctx
        assert "Some content" in ctx

    def test_caps_at_25kb(self, tmp_path):
        from bridge.memory_file import MemoryFile
        idx = _make_index(tmp_path)
        idx._memory_dir.mkdir(parents=True, exist_ok=True)
        # 50KB of content
        content = "a" * 50_000
        idx._path.write_text(content, encoding="utf-8")
        ctx = idx.get_memory_context()
        assert len(ctx.encode("utf-8")) <= MemoryFile.MAX_BYTES

    def test_returns_empty_string_if_no_file(self, tmp_path):
        idx = _make_index(tmp_path)
        assert idx.get_memory_context() == ""


# ---------------------------------------------------------------------------
# Health-probe surface (Sprint 05.06): path / exists / file_size_bytes
# ---------------------------------------------------------------------------

class TestHealthProbeSurface:
    def test_path_property_returns_memory_md_path(self, tmp_path):
        idx = _make_index(tmp_path)
        assert idx.path == tmp_path / "memory" / "MEMORY.md"

    def test_exists_false_before_write(self, tmp_path):
        idx = _make_index(tmp_path)
        assert idx.exists is False

    def test_exists_true_after_update(self, tmp_path):
        idx = _make_index(tmp_path)
        idx.update([_make_entry()])
        assert idx.exists is True

    def test_file_size_bytes_zero_before_write(self, tmp_path):
        idx = _make_index(tmp_path)
        assert idx.file_size_bytes == 0

    def test_file_size_bytes_nonzero_after_update(self, tmp_path):
        idx = _make_index(tmp_path)
        idx.update([_make_entry(key="k", value="v")])
        assert idx.file_size_bytes > 0


# ---------------------------------------------------------------------------
# BridgeApp integration — set_memory_file setter
# ---------------------------------------------------------------------------

class TestBridgeAppSetter:
    def test_bridge_app_has_set_memory_file(self):
        from bridge.app import BridgeApp
        assert hasattr(BridgeApp, "set_memory_file"), (
            "BridgeApp must expose set_memory_file() setter"
        )
        assert callable(getattr(BridgeApp, "set_memory_file"))

    @pytest.mark.asyncio
    async def test_set_memory_file_stores_instance(self, tmp_path, sample_config_toml, mock_keyring):
        from bridge.app import BridgeApp
        from bridge.memory_file import MemoryFile
        app = BridgeApp(config_path=str(sample_config_toml))
        await app._initialize()
        try:
            mf = MemoryFile(tmp_path / "memory")
            app.set_memory_file(mf)
            assert app._memory_file is mf
        finally:
            if app._db:
                await app._db.close()
