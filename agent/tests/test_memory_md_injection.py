"""Tests for the MEMORY.md context-injection wire (#2599).

Incident 2026-06-04: the runtime Bumba reported "running outside the harness."
Root cause (corrected) was a DORMANT, two-sided wire:

  - Producer: ``MemoryFile`` was never constructed in the live boot path, so
    ``BridgeApp.set_memory_file`` was never called and ``_memory_file`` stayed
    ``None`` (healthz: ``memory_file -> disabled``).
  - Consumer: nothing read ``_memory_file`` to inject MEMORY.md content into the
    assembled Claude context, so even a populated file would never reach the
    prompt.

This module locks both sides:

  - ``memory_md_block(app)`` (consumer helper in ``bridge.invocation_pipeline``)
    returns a formatted MEMORY.md block, or ``""`` when the wire is absent or the
    file is empty — never raises.
  - The producer wiring is covered by ``test_app_init_constructs_memory_file``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from bridge.invocation_pipeline import memory_md_block
from bridge.memory_file import MemoryEntry, MemoryFile


# ── Consumer side: memory_md_block ─────────────────────────────────────────


class TestMemoryMdBlock:
    """The injection helper that puts MEMORY.md into the Claude context."""

    def test_none_memory_file_returns_empty(self) -> None:
        """A dormant wire (_memory_file is None) injects nothing, no raise."""
        app = SimpleNamespace(_memory_file=None)
        assert memory_md_block(app) == ""

    def test_missing_attr_returns_empty(self) -> None:
        """An app without the attribute at all degrades cleanly."""
        app = SimpleNamespace()
        assert memory_md_block(app) == ""

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        """A wired-but-never-written MemoryFile injects nothing."""
        mf = MemoryFile(memory_dir=tmp_path)  # file does not exist yet
        app = SimpleNamespace(_memory_file=mf)
        assert memory_md_block(app) == ""

    def test_populated_file_is_injected(self, tmp_path: Path) -> None:
        """A populated MEMORY.md surfaces its content in the returned block."""
        mf = MemoryFile(memory_dir=tmp_path)
        mf.update([MemoryEntry(key="runtime", value="agent-flat is canonical", category="project")])
        app = SimpleNamespace(_memory_file=mf)
        block = memory_md_block(app)
        assert "agent-flat is canonical" in block
        # The block is labelled so Claude can recognise the distilled index.
        assert "MEMORY.md" in block or "Memory Index" in block

    def test_block_never_raises_on_bad_memory_file(self) -> None:
        """A memory_file whose accessor raises must not break context assembly."""
        class Boom:
            def get_memory_context(self) -> str:
                raise RuntimeError("disk gone")

        app = SimpleNamespace(_memory_file=Boom())
        assert memory_md_block(app) == ""


# ── Producer side: boot wiring ──────────────────────────────────────────────


class TestProducerWiring:
    """app_init must construct a MemoryFile and call set_memory_file."""

    def test_set_memory_file_sets_attribute(self) -> None:
        """The setter wires the instance (guards against silent rename)."""
        from bridge.app import BridgeApp

        app = BridgeApp.__new__(BridgeApp)  # no __init__; just exercise the setter
        app._memory_file = None
        sentinel = object()
        app.set_memory_file(sentinel)
        assert app._memory_file is sentinel

    def test_app_init_source_constructs_memory_file(self) -> None:
        """The boot path actually CONSTRUCTS a MemoryFile + calls the setter.

        Source-grep contract (mirrors the project's other wiring tests): the
        dormant ``self._memory_file = None`` stub must be replaced by a real
        construction + ``set_memory_file`` call. This fails RED while the wire
        is dormant and passes once app_init constructs it.
        """
        import inspect

        from bridge import app_init

        src = inspect.getsource(app_init)
        assert "MemoryFile(" in src, "app_init must construct a MemoryFile"
        assert "set_memory_file(" in src, "app_init must call set_memory_file()"
