"""Sprint P2.5 (#1721): assert the background embedding-generation task
scheduled by ``KnowledgeMixin.store_knowledge`` is retained on
``self._pending_tasks`` for the duration of its run. Source:
combined-audit.md HI-8 (Lane A H-6).

Anti-pattern under repair: ``asyncio.create_task(self._generate_embedding(...))``
without a strong reference means the embedding write can be GC'd under
load. The fix follows the named-task convention at ``app.py:3033-3203``.
"""

from __future__ import annotations

import asyncio

import pytest


class TestKnowledgePendingTaskRetention:
    @pytest.mark.asyncio
    async def test_store_knowledge_retains_embedding_task(
        self, migrated_db, sample_config
    ) -> None:
        """``store_knowledge`` must retain the embedding task on
        ``self._pending_tasks`` while it runs; the done_callback must
        drain the set once the task completes."""
        from bridge.embeddings import LocalEmbeddingClient
        from bridge.local_embeddings import LocalEmbeddingEngine
        from bridge.memory import Memory

        engine = LocalEmbeddingEngine()
        client = LocalEmbeddingClient(engine)
        memory = Memory(migrated_db, sample_config, embedding_client=client)

        # P2.5 contract: every Memory instance has a _pending_tasks set.
        assert hasattr(memory, "_pending_tasks"), (
            "Memory must expose _pending_tasks for P2.5 task retention"
        )
        assert isinstance(memory._pending_tasks, set)
        assert len(memory._pending_tasks) == 0

        # Replace _generate_embedding with one that blocks on an event so
        # we can observe the task while it is in-flight.
        release = asyncio.Event()
        observed_name: dict[str, str] = {}

        async def slow_generate(key: str, text: str) -> None:
            observed_name["task_name"] = asyncio.current_task().get_name()
            await release.wait()

        memory._generate_embedding = slow_generate  # type: ignore[assignment]

        await memory.store_knowledge("k1", "alpha beta gamma")

        # Yield to the loop so the create_task call runs into
        # slow_generate up to the wait().
        await asyncio.sleep(0.05)

        # Core assertion: the embedding task is being held by the memory.
        assert len(memory._pending_tasks) == 1, (
            f"Expected 1 pending embedding task while it runs, got "
            f"{len(memory._pending_tasks)}"
        )
        pending = next(iter(memory._pending_tasks))
        assert isinstance(pending, asyncio.Task)
        assert not pending.done()
        # Convention check: named task per P2.5.
        assert pending.get_name().startswith("knowledge-embed-"), (
            f"Expected named task 'knowledge-embed-<key>', got "
            f"{pending.get_name()!r}"
        )
        assert "k1" in pending.get_name()
        assert observed_name["task_name"] == pending.get_name()

        # Release the embedding task, await it, and confirm the
        # done_callback drains the set.
        release.set()
        await pending
        await asyncio.sleep(0.05)
        assert len(memory._pending_tasks) == 0, (
            "done_callback should remove the embedding task from "
            "_pending_tasks"
        )
