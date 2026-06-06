"""Fan-out memory recall across all in-bridge search stores.

Implements the /recall <query> operator command substrate.  Each store
is called concurrently via asyncio.gather; individual store failures are
caught and returned as "unavailable" entries so one bad store cannot abort
the run.

Sprint D2.1 -- issue #1186.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Stable render order -- operator's eye learns the layout over time.
_RENDER_ORDER = (
    "conv",
    "knowledge",
    "temporal",
    "fewshot",
    "reflect",
    "log",
    "edits",
    "wiki",
    "mcp",
)

# Human-readable store labels used in Discord output.
_STORE_LABELS: dict[str, str] = {
    "conv": "conversation memory",
    "knowledge": "knowledge store",
    "temporal": "temporal KB",
    "fewshot": "few-shot examples",
    "reflect": "reflections",
    "log": "daily log",
    "edits": "memory edits",
    "wiki": "second-brain wiki",
    "mcp": "mcp",
}


@dataclass(frozen=True)
class RecallResult:
    """A single search hit from one of the in-bridge memory stores."""

    store: str
    snippet: str
    ref: str = ""
    score: float = 0.0
    unavailable: bool = False
    error: str = ""


async def recall(
    app: Any,
    query: str,
    *,
    limit_per_source: int = 3,
) -> list[RecallResult]:
    """Fan out query across 9 in-bridge memory stores."""
    tasks = (
        _safe_search_conv(app, query, limit_per_source),
        _safe_search_knowledge(app, query, limit_per_source),
        _safe_search_temporal(app, query, limit_per_source),
        _safe_search_fewshot(app, query, limit_per_source),
        _safe_search_reflect(app, query, limit_per_source),
        _safe_search_log(app, query, limit_per_source),
        _safe_search_edits(app, query, limit_per_source),
        _safe_search_wiki(app, query, limit_per_source),
        _safe_search_mcp(app, query, limit_per_source),
    )
    batches = await asyncio.gather(*tasks, return_exceptions=False)
    flat: list[RecallResult] = []
    for batch in batches:
        flat.extend(batch)
    return flat


def _truncate(text: str, max_len: int = 240) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "..."


async def _safe_search_conv(app: Any, query: str, n: int) -> list[RecallResult]:
    mem = getattr(app, "memory", None) or getattr(app, "_memory", None)
    if mem is None:
        return [RecallResult(store="conv", snippet="", unavailable=True, error="Memory not wired")]
    try:
        rows = await mem.search_messages(query, limit=n)
        results: list[RecallResult] = []
        for row in rows[:n]:
            if isinstance(row, dict):
                snippet = _truncate(str(row.get("content", row.get("snippet", ""))))
                ref = str(row.get("session_id", ""))
            else:
                snippet = _truncate(str(getattr(row, "content", getattr(row, "snippet", ""))))
                ref = str(getattr(row, "session_id", ""))
            if snippet:
                results.append(RecallResult(store="conv", snippet=snippet, ref=ref))
        return results
    except Exception as exc:
        logger.debug("recall:conv error: %s", exc)
        return [RecallResult(store="conv", snippet="", unavailable=True, error=str(exc))]


async def _safe_search_knowledge(app: Any, query: str, n: int) -> list[RecallResult]:
    mem = getattr(app, "memory", None) or getattr(app, "_memory", None)
    if mem is None:
        return [RecallResult(store="knowledge", snippet="", unavailable=True, error="Memory not wired")]
    try:
        rows = await mem.search_knowledge(query, limit=n)
        results: list[RecallResult] = []
        for row in rows[:n]:
            if isinstance(row, dict):
                key = str(row.get("key", ""))
                value = str(row.get("value", ""))
                snippet = _truncate(f"{key}: {value}" if key else value)
            else:
                key = str(getattr(row, "key", ""))
                value = str(getattr(row, "value", ""))
                snippet = _truncate(f"{key}: {value}" if key else value)
            if snippet.strip():
                results.append(RecallResult(store="knowledge", snippet=snippet, ref=key))
        return results
    except Exception as exc:
        logger.debug("recall:knowledge error: %s", exc)
        return [RecallResult(store="knowledge", snippet="", unavailable=True, error=str(exc))]


async def _safe_search_temporal(app: Any, query: str, n: int) -> list[RecallResult]:
    tkb = getattr(app, "_temporal_kb", None)
    if tkb is None:
        return [RecallResult(store="temporal", snippet="", unavailable=True, error="Temporal KB not wired")]
    try:
        results: list[RecallResult] = []
        query_lower = query.lower()
        try:
            keys = tkb.list_keys()
        except Exception:
            keys = []
        for key in keys:
            if query_lower in key.lower():
                try:
                    entry = tkb.get(key)
                    if entry:
                        value = str(getattr(entry, "value", ""))
                        snippet = _truncate(f"{key}: {value}")
                        results.append(RecallResult(store="temporal", snippet=snippet, ref=key))
                        if len(results) >= n:
                            break
                except Exception as exc:
                    logger.warning("recall:temporal entry fetch failed for key %s: %s", key, exc)
        return results
    except Exception as exc:
        logger.debug("recall:temporal error: %s", exc)
        return [RecallResult(store="temporal", snippet="", unavailable=True, error=str(exc))]


async def _safe_search_fewshot(app: Any, query: str, n: int) -> list[RecallResult]:
    fs = getattr(app, "_few_shot_store", None)
    if fs is None:
        return [RecallResult(store="fewshot", snippet="", unavailable=True, error="Few-shot store not wired")]
    try:
        examples = fs.get_relevant(query, limit=n)
        results: list[RecallResult] = []
        for ex in (examples or [])[:n]:
            if isinstance(ex, dict):
                text = str(ex.get("input_text", ex.get("text", "")))
                task_type = str(ex.get("task_type", ""))
            else:
                text = str(getattr(ex, "input_text", getattr(ex, "text", "")))
                task_type = str(getattr(ex, "task_type", ""))
            snippet = _truncate(f"[{task_type}] {text}" if task_type else text)
            if snippet.strip():
                results.append(RecallResult(store="fewshot", snippet=snippet))
        return results
    except Exception as exc:
        logger.debug("recall:fewshot error: %s", exc)
        return [RecallResult(store="fewshot", snippet="", unavailable=True, error=str(exc))]


async def _safe_search_reflect(app: Any, query: str, n: int) -> list[RecallResult]:
    rs = getattr(app, "_reflection_store", None)
    if rs is None:
        return [RecallResult(store="reflect", snippet="", unavailable=True, error="Reflection store not wired")]
    try:
        recent = rs.get_recent(limit=20)
        query_lower = query.lower()
        results: list[RecallResult] = []
        for r in (recent or []):
            text = ""
            if isinstance(r, dict):
                text = str(r.get("content", r.get("text", r.get("summary", ""))))
            else:
                text = str(getattr(r, "content", getattr(r, "summary", getattr(r, "text", ""))))
            if query_lower in text.lower():
                snippet = _truncate(text)
                results.append(RecallResult(store="reflect", snippet=snippet))
                if len(results) >= n:
                    break
        return results
    except Exception as exc:
        logger.debug("recall:reflect error: %s", exc)
        return [RecallResult(store="reflect", snippet="", unavailable=True, error=str(exc))]


async def _safe_search_log(app: Any, query: str, n: int) -> list[RecallResult]:
    log_dir: Path | None = getattr(app, "_log_dir", None)
    if log_dir is None:
        daily_log = getattr(app, "_daily_log", None)
        if daily_log is not None:
            log_dir = getattr(daily_log, "_log_dir", None)
    if log_dir is None:
        return [RecallResult(store="log", snippet="", unavailable=True, error="Log directory not wired")]
    try:
        log_dir = Path(log_dir)
        query_lower = query.lower()
        results: list[RecallResult] = []
        log_files: list[Path] = sorted(
            log_dir.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True
        )[:7]
        for log_file in log_files:
            try:
                content = log_file.read_text(errors="replace")
            except OSError:
                continue
            for line in content.splitlines():
                if query_lower in line.lower() and line.strip():
                    snippet = _truncate(line.strip())
                    results.append(
                        RecallResult(store="log", snippet=snippet, ref=log_file.stem)
                    )
                    if len(results) >= n:
                        return results
        return results
    except Exception as exc:
        logger.debug("recall:log error: %s", exc)
        return [RecallResult(store="log", snippet="", unavailable=True, error=str(exc))]


async def _safe_search_edits(app: Any, query: str, n: int) -> list[RecallResult]:
    se = getattr(app, "_self_edit", None)
    if se is None:
        return [RecallResult(store="edits", snippet="", unavailable=True, error="Self-edit memory not wired")]
    try:
        pending = se.get_pending_edits() or []
        query_lower = query.lower()
        results: list[RecallResult] = []
        for edit in pending:
            if isinstance(edit, dict):
                val = str(edit.get("proposed_value", edit.get("value", "")))
                cat = str(edit.get("category", ""))
                edit_id = str(edit.get("id", ""))
            else:
                val = str(getattr(edit, "proposed_value", getattr(edit, "value", "")))
                cat = str(getattr(edit, "category", ""))
                edit_id = str(getattr(edit, "id", ""))
            combined = f"{cat} {val}"
            if query_lower in combined.lower():
                snippet = _truncate(f"[{cat}] {val}" if cat else val)
                results.append(RecallResult(store="edits", snippet=snippet, ref=edit_id))
                if len(results) >= n:
                    break
        return results
    except Exception as exc:
        logger.debug("recall:edits error: %s", exc)
        return [RecallResult(store="edits", snippet="", unavailable=True, error=str(exc))]


async def _safe_search_wiki(app: Any, query: str, n: int) -> list[RecallResult]:
    wiki_repo = getattr(app, "_wiki_repo", None)
    if wiki_repo is None:
        return [RecallResult(store="wiki", snippet="", unavailable=True, error="Second-brain not wired")]
    try:
        import importlib
        sb_ingest = importlib.import_module("bridge.second_brain.ingest")
        sb_query_mod = importlib.import_module("bridge.second_brain.query")
    except ImportError:
        return [RecallResult(store="wiki", snippet="", unavailable=True, error="second_brain module not available")]
    try:
        notes_tuple, _ = await sb_ingest.ingest_vault(
            wiki_repo.vault_root,
            summarize_canonical_only=False,
            dream_agent_runner=None,
        )
        _cfg = getattr(app, "_config", None)
        response = await sb_query_mod.query(
            query,
            notes=notes_tuple,
            strategy=getattr(_cfg, "second_brain_query_strategy", "index_first"),
            k=getattr(_cfg, "second_brain_query_k", 10),
            fallthrough_threshold=getattr(_cfg, "second_brain_query_fallthrough_threshold", 3),
        )
        hits = list(getattr(response, "results", []))[:n]
        results: list[RecallResult] = []
        for r in hits:
            title = getattr(r, "title", "") or ""
            snippet_text = (getattr(r, "snippet", "") or "").replace("\n", " ")
            ref = getattr(r, "relpath", "") or ""
            combined = f"{title}: {snippet_text}" if title else snippet_text
            snippet = _truncate(combined)
            if snippet.strip():
                results.append(RecallResult(store="wiki", snippet=snippet, ref=ref))
        return results
    except Exception as exc:
        logger.debug("recall:wiki error: %s", exc)
        return [RecallResult(store="wiki", snippet="", unavailable=True, error=str(exc))]


async def _safe_search_mcp(app: Any, query: str, n: int) -> list[RecallResult]:  # noqa: ARG001
    """The bumba-memory MCP is not reachable from the bridge process."""
    return [
        RecallResult(
            store="mcp",
            snippet="bumba-memory MCP is not reachable from the bridge; query via Claude Code",
            unavailable=True,
        )
    ]


def render_recall(results: list[RecallResult], *, query: str) -> str:
    """Format fan-out results as a Discord-ready string."""
    by_store: dict[str, list[RecallResult]] = {tag: [] for tag in _RENDER_ORDER}
    for r in results:
        by_store.setdefault(r.store, []).append(r)

    hit_count = sum(1 for r in results if not r.unavailable and r.snippet)
    lines: list[str] = [f"`/recall {query}` -- {hit_count} hit(s) across 9 stores\n"]

    for tag in _RENDER_ORDER:
        bucket = by_store.get(tag, [])
        if not bucket:
            continue
        for r in bucket:
            label = _label_for(tag, r)
            if r.unavailable:
                lines.append(f"[{label}] unavailable" + (f": {r.error}" if r.error else ""))
            elif r.snippet:
                lines.append(f"[{label}] {r.snippet}")

    if hit_count == 0:
        return f"No matches for `{query}` across 9 memory stores."

    full = "\n".join(lines)
    if len(full) <= 1990:
        return full
    return full[:1970] + "\n...(truncated)"


def _label_for(tag: str, r: RecallResult) -> str:
    """Build the provenance label shown in brackets before each result."""
    if tag == "log" and r.ref:
        return f"log {r.ref}"
    if tag == "mcp":
        return "mcp:unreachable"
    return _STORE_LABELS.get(tag, tag)
