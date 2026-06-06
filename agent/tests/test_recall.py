"""Tests for the /recall fan-out memory search (Sprint D2.1, issue #1186)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.recall import (
    RecallResult,
    _label_for,
    _safe_search_conv,
    _safe_search_edits,
    _safe_search_fewshot,
    _safe_search_knowledge,
    _safe_search_log,
    _safe_search_mcp,
    _safe_search_reflect,
    _safe_search_temporal,
    _safe_search_wiki,
    recall,
    render_recall,
)


def _make_app(**kwargs: Any) -> MagicMock:
    app = MagicMock(spec=[])
    for key, val in kwargs.items():
        setattr(app, key, val)
    return app


def test_recall_result_is_frozen() -> None:
    r = RecallResult(store="conv", snippet="hello")
    with pytest.raises((AttributeError, TypeError)):
        r.snippet = "other"  # type: ignore[misc]


def test_recall_result_defaults() -> None:
    r = RecallResult(store="knowledge", snippet="val")
    assert r.ref == ""
    assert r.score == 0.0
    assert r.unavailable is False
    assert r.error == ""


@pytest.mark.asyncio
async def test_safe_search_conv_no_memory() -> None:
    app = _make_app()
    results = await _safe_search_conv(app, "foo", 3)
    assert len(results) == 1
    assert results[0].unavailable
    assert results[0].store == "conv"


@pytest.mark.asyncio
async def test_safe_search_conv_memory_raises() -> None:
    mem = MagicMock()
    mem.search_messages = AsyncMock(side_effect=RuntimeError("boom"))
    app = _make_app(memory=mem)
    results = await _safe_search_conv(app, "foo", 3)
    assert len(results) == 1
    assert results[0].unavailable
    assert "boom" in results[0].error


@pytest.mark.asyncio
async def test_safe_search_conv_returns_hits() -> None:
    mem = MagicMock()
    mem.search_messages = AsyncMock(
        return_value=[
            {"content": "hello world", "session_id": "s1"},
            {"content": "another hit", "session_id": "s2"},
        ]
    )
    app = _make_app(memory=mem)
    results = await _safe_search_conv(app, "hello", 3)
    assert not any(r.unavailable for r in results)
    assert any("hello world" in r.snippet for r in results)
    assert results[0].ref == "s1"


@pytest.mark.asyncio
async def test_safe_search_knowledge_no_memory() -> None:
    app = _make_app()
    results = await _safe_search_knowledge(app, "test", 3)
    assert results[0].unavailable


@pytest.mark.asyncio
async def test_safe_search_knowledge_returns_hits() -> None:
    mem = MagicMock()
    mem.search_knowledge = AsyncMock(
        return_value=[{"key": "my-key", "value": "some value"}]
    )
    app = _make_app(memory=mem)
    results = await _safe_search_knowledge(app, "my-key", 3)
    assert len(results) == 1
    assert "my-key" in results[0].snippet
    assert results[0].ref == "my-key"


@pytest.mark.asyncio
async def test_safe_search_temporal_not_wired() -> None:
    app = _make_app()
    results = await _safe_search_temporal(app, "test", 3)
    assert results[0].unavailable


@pytest.mark.asyncio
async def test_safe_search_temporal_key_match() -> None:
    tkb = MagicMock()
    tkb.list_keys.return_value = ["skill:python", "skill:go", "other"]
    entry = MagicMock()
    entry.value = "Python expertise"
    tkb.get.return_value = entry
    app = _make_app(_temporal_kb=tkb)
    results = await _safe_search_temporal(app, "python", 3)
    assert len(results) >= 1
    assert "python" in results[0].snippet.lower()


@pytest.mark.asyncio
async def test_safe_search_fewshot_not_wired() -> None:
    app = _make_app()
    results = await _safe_search_fewshot(app, "test", 3)
    assert results[0].unavailable


@pytest.mark.asyncio
async def test_safe_search_fewshot_returns_hits() -> None:
    ex = MagicMock()
    ex.input_text = "write a function"
    ex.task_type = "code"
    fs = MagicMock()
    fs.get_relevant.return_value = [ex]
    app = _make_app(_few_shot_store=fs)
    results = await _safe_search_fewshot(app, "write", 3)
    assert len(results) == 1
    assert "write a function" in results[0].snippet


@pytest.mark.asyncio
async def test_safe_search_reflect_not_wired() -> None:
    app = _make_app()
    results = await _safe_search_reflect(app, "test", 3)
    assert results[0].unavailable


@pytest.mark.asyncio
async def test_safe_search_reflect_text_filter() -> None:
    rs = MagicMock()
    rs.get_recent.return_value = [
        {"content": "This week I learned about async patterns."},
        {"content": "Completed the roadmap review."},
    ]
    app = _make_app(_reflection_store=rs)
    results = await _safe_search_reflect(app, "async", 3)
    assert len(results) == 1
    assert "async patterns" in results[0].snippet


@pytest.mark.asyncio
async def test_safe_search_log_not_wired() -> None:
    app = _make_app()
    results = await _safe_search_log(app, "test", 3)
    assert results[0].unavailable


@pytest.mark.asyncio
async def test_safe_search_log_grep(tmp_path) -> None:
    log_file = tmp_path / "2026-05-01.md"
    log_file.write_text("- [session] started bridge\n- [error] connection timeout occurred\n")
    app = _make_app(_log_dir=tmp_path)
    results = await _safe_search_log(app, "timeout", 3)
    assert len(results) >= 1
    assert "timeout" in results[0].snippet.lower()


@pytest.mark.asyncio
async def test_safe_search_edits_not_wired() -> None:
    app = _make_app()
    results = await _safe_search_edits(app, "test", 3)
    assert results[0].unavailable


@pytest.mark.asyncio
async def test_safe_search_edits_filters_by_query() -> None:
    se = MagicMock()
    se.get_pending_edits.return_value = [
        {"id": "1", "category": "preference", "proposed_value": "prefer async IO"},
        {"id": "2", "category": "rule", "proposed_value": "always test before PR"},
    ]
    app = _make_app(_self_edit=se)
    results = await _safe_search_edits(app, "async", 3)
    assert len(results) == 1
    assert "async" in results[0].snippet.lower()


@pytest.mark.asyncio
async def test_safe_search_wiki_not_wired() -> None:
    app = _make_app()
    results = await _safe_search_wiki(app, "test", 3)
    assert results[0].unavailable


@pytest.mark.asyncio
async def test_safe_search_mcp_always_unavailable() -> None:
    app = _make_app()
    results = await _safe_search_mcp(app, "anything", 3)
    assert len(results) == 1
    assert results[0].unavailable
    assert results[0].store == "mcp"
    assert "Claude" in results[0].snippet


@pytest.mark.asyncio
async def test_recall_returns_flat_list_per_store() -> None:
    app = _make_app()
    results = await recall(app, "test", limit_per_source=1)
    assert len(results) >= 9
    stores = {r.store for r in results}
    assert "mcp" in stores


@pytest.mark.asyncio
async def test_recall_store_failure_isolated() -> None:
    mem = MagicMock()
    mem.search_messages = AsyncMock(side_effect=RuntimeError("network error"))
    mem.search_knowledge = AsyncMock(return_value=[])
    app = _make_app(memory=mem)
    results = await recall(app, "query", limit_per_source=1)
    conv_results = [r for r in results if r.store == "conv"]
    assert len(conv_results) == 1
    assert conv_results[0].unavailable


@pytest.mark.asyncio
async def test_recall_limit_per_source_respected() -> None:
    mem = MagicMock()
    mem.search_messages = AsyncMock(
        return_value=[{"content": f"hit {i}", "session_id": f"s{i}"} for i in range(10)]
    )
    mem.search_knowledge = AsyncMock(return_value=[])
    app = _make_app(memory=mem)
    results = await recall(app, "hit", limit_per_source=1)
    conv_hits = [r for r in results if r.store == "conv" and not r.unavailable]
    assert len(conv_hits) <= 1


def test_label_for_log_with_ref() -> None:
    r = RecallResult(store="log", snippet="x", ref="2026-05-01")
    assert _label_for("log", r) == "log 2026-05-01"


def test_label_for_log_without_ref() -> None:
    r = RecallResult(store="log", snippet="x", ref="")
    assert _label_for("log", r) == "daily log"


def test_label_for_mcp() -> None:
    r = RecallResult(store="mcp", snippet="", unavailable=True)
    assert _label_for("mcp", r) == "mcp:unreachable"


def test_label_for_other_store() -> None:
    r = RecallResult(store="conv", snippet="x")
    assert _label_for("conv", r) == "conversation memory"


def test_render_recall_no_hits() -> None:
    results = [RecallResult(store="conv", snippet="", unavailable=True, error="not wired")]
    out = render_recall(results, query="foo")
    assert "No matches" in out


def test_render_recall_with_hits() -> None:
    results = [
        RecallResult(store="conv", snippet="hello world", ref="s1"),
        RecallResult(store="knowledge", snippet="kb entry", ref="k1"),
    ]
    out = render_recall(results, query="hello")
    assert "[conversation memory]" in out
    assert "hello world" in out
    assert "[knowledge store]" in out
    assert "kb entry" in out


def test_render_recall_truncates_at_discord_limit() -> None:
    long_snippet = "x" * 300
    results = [
        RecallResult(store="conv", snippet=long_snippet)
        for _ in range(10)
    ]
    out = render_recall(results, query="x")
    assert len(out) <= 2000


def test_render_recall_hit_count_in_header() -> None:
    results = [
        RecallResult(store="conv", snippet="hit one"),
        RecallResult(store="knowledge", snippet="hit two"),
        RecallResult(store="mcp", snippet="", unavailable=True),
    ]
    out = render_recall(results, query="test")
    assert "2 hit" in out


# ---------- second_brain query-param threading (D1.10 #1182) ----------


@pytest.mark.asyncio
async def test_safe_search_wiki_passes_config_query_params() -> None:
    """_safe_search_wiki must forward second_brain_query_* flags from
    app._config to the query() call when config is wired."""
    import importlib
    from unittest.mock import AsyncMock, MagicMock, patch

    _sb_ingest_mod = importlib.import_module("bridge.second_brain.ingest")
    _sb_query_mod = importlib.import_module("bridge.second_brain.query")

    wiki_repo = MagicMock()
    wiki_repo.vault_root = "/fake/vault"

    cfg = MagicMock()
    cfg.second_brain_query_strategy = "index_only"
    cfg.second_brain_query_k = 5
    cfg.second_brain_query_fallthrough_threshold = 1

    app = _make_app(_wiki_repo=wiki_repo, _config=cfg)

    fake_response = MagicMock()
    fake_response.results = []

    mock_ingest = AsyncMock(return_value=((), MagicMock()))
    mock_query = AsyncMock(return_value=fake_response)

    with patch.object(_sb_ingest_mod, "ingest_vault", mock_ingest), \
         patch.object(_sb_query_mod, "query", mock_query):
        await _safe_search_wiki(app, "test query", 3)

    mock_query.assert_called_once()
    _, kwargs = mock_query.call_args
    assert kwargs.get("strategy") == "index_only"
    assert kwargs.get("k") == 5
    assert kwargs.get("fallthrough_threshold") == 1


@pytest.mark.asyncio
async def test_safe_search_wiki_defaults_when_no_config() -> None:
    """When app._config is absent, query() falls back to function defaults."""
    import importlib
    from unittest.mock import AsyncMock, MagicMock, patch

    _sb_ingest_mod = importlib.import_module("bridge.second_brain.ingest")
    _sb_query_mod = importlib.import_module("bridge.second_brain.query")

    wiki_repo = MagicMock()
    wiki_repo.vault_root = "/fake/vault"
    app = _make_app(_wiki_repo=wiki_repo)  # no _config attribute

    fake_response = MagicMock()
    fake_response.results = []

    mock_ingest = AsyncMock(return_value=((), MagicMock()))
    mock_query = AsyncMock(return_value=fake_response)

    with patch.object(_sb_ingest_mod, "ingest_vault", mock_ingest), \
         patch.object(_sb_query_mod, "query", mock_query):
        await _safe_search_wiki(app, "test query", 3)

    mock_query.assert_called_once()
    _, kwargs = mock_query.call_args
    assert kwargs.get("strategy") == "index_first"
    assert kwargs.get("k") == 10
    assert kwargs.get("fallthrough_threshold") == 3
