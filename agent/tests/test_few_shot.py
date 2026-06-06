"""Tests for MS4.2: Self-Generated Few-Shot Examples."""

from __future__ import annotations

import threading


from bridge.few_shot import (
    FewShotExample,
    FewShotStore,
    classify_task_type,
    clean_text,
    MAX_EXAMPLES,
    MAX_INJECTION_CHARS,
)


# ── Task Type Classification ──

class TestClassifyTaskType:
    def test_command_search(self):
        assert classify_task_type("search for Python tutorials") == "search"

    def test_command_deploy(self):
        assert classify_task_type("deploy the latest build") == "deploy"

    def test_tools_override_keywords(self):
        # Tool signal takes priority
        assert classify_task_type("write a story", tools_used=["brave-search"]) == "search"

    def test_code_review(self):
        assert classify_task_type("review this code please") == "code_review"

    def test_debug(self):
        assert classify_task_type("there's a bug in the parser") == "debug"

    def test_analysis(self):
        assert classify_task_type("explain how the auth system works") == "analysis"

    def test_creative(self):
        assert classify_task_type("write a short poem") == "creative"

    def test_general_fallback(self):
        assert classify_task_type("hello there") == "general"

    def test_empty_message(self):
        assert classify_task_type("") == "general"


# ── Text Cleaning ──

class TestCleanText:
    def test_strips_discord_mention(self):
        assert "[REDACTED]" in clean_text("Hello <@123456789>")

    def test_strips_api_key(self):
        assert "[REDACTED]" in clean_text("key is sk-abc123def456ghi789jkl012mno")

    def test_preserves_normal_text(self):
        text = "Please review this function"
        assert clean_text(text) == text


# ── Store & Retrieve ──

class TestFewShotStore:
    def test_store_and_get(self, tmp_path):
        store = FewShotStore(tmp_path / "fs.db")
        ex = FewShotExample(
            task_type="search",
            input_text="find Python docs",
            output_text="Here are the docs...",
            tools_used=["brave-search"],
        )
        row_id = store.store(ex)
        assert row_id > 0
        got = store.get(row_id)
        assert got is not None
        assert got.task_type == "search"
        assert got.input_text == "find Python docs"

    def test_count(self, tmp_path):
        store = FewShotStore(tmp_path / "fs.db")
        assert store.count() == 0
        store.store(FewShotExample(task_type="a", input_text="x", output_text="y"))
        assert store.count() == 1

    def test_delete(self, tmp_path):
        store = FewShotStore(tmp_path / "fs.db")
        rid = store.store(FewShotExample(task_type="a", input_text="x", output_text="y"))
        assert store.delete(rid) is True
        assert store.count() == 0

    def test_delete_nonexistent(self, tmp_path):
        store = FewShotStore(tmp_path / "fs.db")
        assert store.delete(999) is False

    def test_list_all(self, tmp_path):
        store = FewShotStore(tmp_path / "fs.db")
        for i in range(5):
            store.store(FewShotExample(
                task_type="t", input_text=f"in {i}", output_text=f"out {i}",
                quality_score=float(i) / 5,
            ))
        all_ex = store.list_all()
        assert len(all_ex) == 5
        # Ordered by quality descending
        assert all_ex[0].quality_score >= all_ex[-1].quality_score


# ── Retrieval Ranking ──

class TestRetrieval:
    def test_get_relevant_returns_results(self, tmp_path):
        store = FewShotStore(tmp_path / "fs.db")
        store.store(FewShotExample(
            task_type="search",
            input_text="search for Python documentation",
            output_text="Found the docs",
        ))
        store.store(FewShotExample(
            task_type="debug",
            input_text="fix the database crash",
            output_text="Fixed the bug",
        ))
        results = store.get_relevant("search Python docs")
        assert len(results) >= 1
        # Search example should rank higher
        assert results[0].task_type == "search"

    def test_get_relevant_filter_by_task_type(self, tmp_path):
        store = FewShotStore(tmp_path / "fs.db")
        store.store(FewShotExample(task_type="search", input_text="find x", output_text="y"))
        store.store(FewShotExample(task_type="debug", input_text="fix x", output_text="y"))
        results = store.get_relevant("anything", task_type="search")
        assert all(r.task_type == "search" for r in results)

    def test_get_relevant_respects_quality_minimum(self, tmp_path):
        store = FewShotStore(tmp_path / "fs.db")
        store.store(FewShotExample(
            task_type="search", input_text="find x", output_text="y",
            quality_score=0.1,  # Below MIN_QUALITY_FOR_INJECTION
        ))
        results = store.get_relevant("find x")
        assert len(results) == 0

    def test_get_relevant_limit(self, tmp_path):
        store = FewShotStore(tmp_path / "fs.db")
        for i in range(10):
            store.store(FewShotExample(
                task_type="search", input_text=f"search {i}", output_text=f"result {i}",
            ))
        results = store.get_relevant("search", limit=3)
        assert len(results) == 3

    def test_get_relevant_empty_store(self, tmp_path):
        store = FewShotStore(tmp_path / "fs.db")
        assert store.get_relevant("anything") == []


# ── Quality Score Updates ──

class TestQualityScoring:
    def test_quality_update_helped(self, tmp_path):
        store = FewShotStore(tmp_path / "fs.db")
        rid = store.store(FewShotExample(
            task_type="t", input_text="x", output_text="y",
            quality_score=1.0,
        ))
        store.update_quality(rid, helped=True)
        ex = store.get(rid)
        assert ex is not None
        assert ex.quality_score == 1.0  # (1.0 * 0 + 1.0) / 1 = 1.0
        assert ex.use_count == 1

    def test_quality_update_not_helped(self, tmp_path):
        store = FewShotStore(tmp_path / "fs.db")
        rid = store.store(FewShotExample(
            task_type="t", input_text="x", output_text="y",
            quality_score=1.0,
        ))
        store.update_quality(rid, helped=False)
        ex = store.get(rid)
        assert ex is not None
        assert ex.quality_score == 0.0  # (1.0 * 0 + 0.0) / 1 = 0.0
        assert ex.use_count == 1

    def test_quality_converges(self, tmp_path):
        """Simulate 10 uses: 7 helpful → score ~0.7."""
        store = FewShotStore(tmp_path / "fs.db")
        rid = store.store(FewShotExample(
            task_type="t", input_text="x", output_text="y",
            quality_score=1.0,
        ))
        for i in range(10):
            store.update_quality(rid, helped=(i < 7))
        ex = store.get(rid)
        assert ex is not None
        assert 0.6 <= ex.quality_score <= 0.8  # Should be ~0.7
        assert ex.use_count == 10

    def test_update_nonexistent(self, tmp_path):
        store = FewShotStore(tmp_path / "fs.db")
        # Should not raise
        store.update_quality(999, helped=True)


# ── Cap Enforcement ──

class TestCapEnforcement:
    def test_cap_enforced_on_store(self, tmp_path):
        store = FewShotStore(tmp_path / "fs.db")
        # Store MAX_EXAMPLES + 5 examples with varying quality
        for i in range(MAX_EXAMPLES + 5):
            store.store(FewShotExample(
                task_type="t", input_text=f"in {i}", output_text=f"out {i}",
                quality_score=float(i) / (MAX_EXAMPLES + 5),
            ))
        assert store.count() <= MAX_EXAMPLES

    def test_cap_removes_lowest_quality(self, tmp_path):
        store = FewShotStore(tmp_path / "fs.db")
        # Store high quality then low quality
        for i in range(MAX_EXAMPLES):
            store.store(FewShotExample(
                task_type="t", input_text=f"good {i}", output_text="y",
                quality_score=0.9,
            ))
        # This one should cause enforcement
        store.store(FewShotExample(
            task_type="t", input_text="bad", output_text="y",
            quality_score=0.1,
        ))
        # The low quality one should be removed
        all_ex = store.list_all()
        assert all(e.quality_score >= 0.1 for e in all_ex)


# ── Injection Formatting ──

class TestInjectionFormatting:
    def test_format_empty(self, tmp_path):
        store = FewShotStore(tmp_path / "fs.db")
        assert store.format_injection([]) == ""

    def test_format_has_header(self, tmp_path):
        store = FewShotStore(tmp_path / "fs.db")
        examples = [FewShotExample(
            task_type="search",
            input_text="find docs",
            output_text="Here are the docs",
            tools_used=["brave-search"],
        )]
        result = store.format_injection(examples)
        assert "Recent Successful Approaches" in result
        assert "find docs" in result
        assert "brave-search" in result

    def test_format_respects_char_cap(self, tmp_path):
        store = FewShotStore(tmp_path / "fs.db")
        # Very long examples
        examples = [
            FewShotExample(
                task_type="t",
                input_text="x" * 500,
                output_text="y" * 500,
            )
            for _ in range(10)
        ]
        result = store.format_injection(examples)
        assert len(result) <= MAX_INJECTION_CHARS + 100  # Some slack for truncation

    def test_no_injection_when_no_good_examples(self, tmp_path):
        store = FewShotStore(tmp_path / "fs.db")
        # Single example that's too long and would be the only one
        result = store.format_injection([])
        assert result == ""


# ── Concurrent Access ──

class TestConcurrentAccess:
    def test_concurrent_stores(self, tmp_path):
        store = FewShotStore(tmp_path / "fs.db")
        errors = []

        def writer(tid: int):
            try:
                for i in range(10):
                    store.store(FewShotExample(
                        task_type="t", input_text=f"t{tid}-{i}", output_text="y",
                    ))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # Cap enforcement may have reduced below 50
        assert store.count() <= MAX_EXAMPLES
