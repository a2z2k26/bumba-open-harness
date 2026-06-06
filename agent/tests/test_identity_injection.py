"""Test that SOUL/OPERATOR/RULES are injected into assemble_context when flag is set.

Sprint 17 / issue #637 — identity injection tests.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch



# ---------------------------------------------------------------------------
# Static / structural tests
# ---------------------------------------------------------------------------

def test_inject_identity_config_field_exists():
    """Config must have inject_identity field."""
    src = Path("bridge/config.py").read_text()
    assert "inject_identity" in src, "inject_identity config field not found in config.py"


def test_inject_identity_default_is_false():
    """inject_identity must default to False for safe rollout."""
    src = Path("bridge/config.py").read_text()
    assert "inject_identity: bool = False" in src, \
        "inject_identity must default to False"


def test_identity_max_bytes_config_field_exists():
    """Config must have identity_max_bytes field."""
    src = Path("bridge/config.py").read_text()
    assert "identity_max_bytes" in src, "identity_max_bytes config field not found"


def test_identity_max_bytes_default_value():
    """identity_max_bytes must default to 24576 (24 KB)."""
    src = Path("bridge/config.py").read_text()
    assert "identity_max_bytes: int = 24576" in src, \
        "identity_max_bytes must default to 24576"


def test_assemble_context_reads_identity_files():
    """assemble_context must check inject_identity flag and reference identity files."""
    # Post refs #1305 demote-split: identity-injection code lives in
    # bridge/memory/knowledge.py (was bridge/memory.py).
    src = Path("bridge/memory/knowledge.py").read_text()
    assert "inject_identity" in src, "memory/knowledge.py must check inject_identity flag"
    assert "SOUL.md" in src, "memory/knowledge.py must reference SOUL.md"
    assert "OPERATOR.md" in src, "memory/knowledge.py must reference OPERATOR.md"
    assert "RULES.md" in src, "memory/knowledge.py must reference RULES.md"


def test_identity_max_bytes_cap_exists():
    """Identity injection must be capped to prevent context window exhaustion."""
    src = Path("bridge/memory/knowledge.py").read_text()
    assert "identity_max" in src or "24576" in src, \
        "Identity injection must have a size cap"


def test_identity_files_constant_defined():
    """IDENTITY_FILES tuple must be defined at module level in memory/knowledge.py."""
    src = Path("bridge/memory/knowledge.py").read_text()
    assert "IDENTITY_FILES" in src, "IDENTITY_FILES constant not found in memory/knowledge.py"


def test_identity_searched_at_multiple_locations():
    """Code must search both repo root and agent/ subdirectory for identity files."""
    src = Path("bridge/memory/knowledge.py").read_text()
    assert "project_root" in src, "memory/knowledge.py must resolve project_root for identity lookup"
    # candidate search at both root and agent/ subdir
    assert '"agent"' in src or "'agent'" in src, \
        "memory/knowledge.py must check agent/ subdirectory as identity file fallback"


def test_toml_identity_section_present():
    """bridge.toml must have [identity] section with inject_identity = false."""
    src = Path("config/bridge.toml").read_text()
    assert "[identity]" in src, "[identity] section not found in bridge.toml"
    assert "inject_identity = false" in src, "inject_identity must default to false in TOML"


def test_toml_identity_max_bytes_present():
    """bridge.toml must specify identity_max_bytes."""
    src = Path("config/bridge.toml").read_text()
    assert "identity_max_bytes" in src, "identity_max_bytes not found in bridge.toml"


# ---------------------------------------------------------------------------
# Runtime behavioural tests (no real DB / disk I/O needed)
# ---------------------------------------------------------------------------

def _make_memory(inject_identity: bool = False, identity_max_bytes: int = 24576):
    """Build a Memory instance with a mock config and database."""
    from bridge.config import BridgeConfig
    from bridge.memory import Memory

    config = BridgeConfig(
        inject_identity=inject_identity,
        identity_max_bytes=identity_max_bytes,
    )
    db = MagicMock()
    db.fetchall = AsyncMock(return_value=[])
    return Memory(db, config)


def _run(coro):
    return asyncio.run(coro)


def test_identity_not_injected_when_flag_false(tmp_path):
    """When inject_identity=False, no identity content appears in assembled context."""
    mem = _make_memory(inject_identity=False)
    # Patch get_session_summaries, get_recent_messages to return nothing
    mem.get_session_summaries = AsyncMock(return_value=[])
    mem.get_recent_messages = AsyncMock(return_value=[])

    ctx = _run(mem.assemble_context("chat1", "sess1"))
    assert "SOUL.md" not in ctx
    assert "OPERATOR.md" not in ctx
    assert "RULES.md" not in ctx


def test_identity_injected_when_flag_true(tmp_path):
    """When inject_identity=True and identity files exist, content appears first in context."""
    mem = _make_memory(inject_identity=True)
    mem.get_session_summaries = AsyncMock(return_value=[])
    mem.get_recent_messages = AsyncMock(return_value=[])

    # Create temp identity files and make project_root resolve to tmp_path
    (tmp_path / "SOUL.md").write_text("# Soul\nI am Bumba.")
    (tmp_path / "OPERATOR.md").write_text("# the operator\nthe operator's profile.")
    (tmp_path / "RULES.md").write_text("# Rules\nDo good work.")

    import bridge.memory.knowledge as knowledge_mod

    # Patch Path(__file__).resolve().parent.parent.parent → tmp_path
    class _FakePath:
        def __init__(self, *args):
            self._path = Path(*args)

        def resolve(self):
            return _FakeResolved(self._path)

        def __truediv__(self, other):
            return self._path / other

        def exists(self):
            return self._path.exists()

        def read_text(self, **kw):
            return self._path.read_text(**kw)

        def __str__(self):
            return str(self._path)

    class _FakeResolved:
        def __init__(self, p):
            self._p = p

        @property
        def parent(self):
            # Return self so chained .parent.parent.parent still gives tmp_path
            return _FakeResolved(tmp_path)

        def __truediv__(self, other):
            return tmp_path / other

    # Directly patch project_root derivation by monkeypatching the module's Path
    with patch.object(knowledge_mod, "Path", side_effect=lambda *a, **k: _FakePath(*a, **k)):
        ctx = _run(mem.assemble_context("chat1", "sess1"))

    assert "## SOUL.md" in ctx
    assert "I am Bumba." in ctx
    assert "## OPERATOR.md" in ctx
    assert "the operator's profile." in ctx
    assert "## RULES.md" in ctx
    assert "Do good work." in ctx

    # Identity content must come first
    soul_pos = ctx.index("## SOUL.md")
    operator_pos = ctx.index("## OPERATOR.md")
    rules_pos = ctx.index("## RULES.md")
    assert soul_pos < operator_pos < rules_pos


def test_identity_truncated_at_cap(tmp_path):
    """Content beyond identity_max_bytes is truncated with a clear marker."""
    small_cap = 50  # tiny cap
    mem = _make_memory(inject_identity=True, identity_max_bytes=small_cap)
    mem.get_session_summaries = AsyncMock(return_value=[])
    mem.get_recent_messages = AsyncMock(return_value=[])

    (tmp_path / "SOUL.md").write_text("A" * 200)
    (tmp_path / "OPERATOR.md").write_text("B" * 200)
    (tmp_path / "RULES.md").write_text("C" * 200)

    import bridge.memory.knowledge as knowledge_mod

    class _FakeResolved:
        def __init__(self, p):
            self._p = p

        @property
        def parent(self):
            return _FakeResolved(tmp_path)

        def __truediv__(self, other):
            return tmp_path / other

    class _FakePath:
        def __init__(self, *a, **k):
            self._path = Path(*a, **k)

        def resolve(self):
            return _FakeResolved(self._path)

        def __truediv__(self, other):
            return self._path / other

        def exists(self):
            return self._path.exists()

        def read_text(self, **kw):
            return self._path.read_text(**kw)

    with patch.object(knowledge_mod, "Path", side_effect=lambda *a, **k: _FakePath(*a, **k)):
        ctx = _run(mem.assemble_context("chat1", "sess1"))

    assert "[...truncated for context window...]" in ctx
    # Only SOUL.md (first file) should appear given the tiny cap
    assert "## SOUL.md" in ctx
