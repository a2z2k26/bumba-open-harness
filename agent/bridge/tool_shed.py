"""Tool Shed — per-agent MCP tool provisioning registry."""

from __future__ import annotations

import logging
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Union

# E2.2 (#1239) — OTEL-shape tracing facade
from bridge.tracing import get_otel_tracer

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolConfig:
    name: str = ""
    category: str = ""
    always_loaded: bool = False
    agents: tuple[str, ...] = ()
    description: str = ""
    kind: Literal["tool", "skill"] = "tool"

    def __init__(
        self,
        name: str = "",
        category: str = "",
        always_loaded: bool = False,
        agents: list[str] | tuple[str, ...] = (),
        description: str = "",
        kind: Literal["tool", "skill"] = "tool",
    ) -> None:
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "always_loaded", always_loaded)
        object.__setattr__(self, "agents", tuple(agents))
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "kind", kind)


@dataclass(frozen=True)
class SkillCandidate:
    """Sprint 07.05 (#1034) — markdown-skill adapter for the Smart Tool RAG corpus.

    Concept-only port of browser-harness's git-friendly skill directory
    (MIT, paraphrased). Mirrors the ``ToolConfig`` surface used by the
    BM25 + RRF pipeline so skills slot into the same fused ranking.
    Carries a ``path`` and ``domain`` so callers can distinguish
    a skill from a YAML-registered tool without re-walking the tree.
    """

    name: str = ""
    domain: str = ""
    description: str = ""
    path: Path | None = None
    frontmatter: dict[str, object] = field(default_factory=dict)
    kind: Literal["tool", "skill"] = "skill"
    # ToolConfig-shape fields kept stub-compatible so the BM25 corpus
    # builder can treat both types uniformly.
    category: str = ""
    always_loaded: bool = False
    agents: tuple[str, ...] = ()


# Union returned when discovery is enabled. Existing callers keep the
# narrower ``list[ToolConfig]`` surface by leaving ``include_markdown=False``.
ToolOrSkill = Union[ToolConfig, SkillCandidate]


# Smart Tool RAG constants — paraphrased from OpenSpace concept (MIT).
_RRF_K = 60
_WEIGHT_BM25 = 0.4
_WEIGHT_VECTOR = 0.6
_BM25_K1 = 1.5
_BM25_B = 0.75
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokenization for BM25 + tool-name splitting."""
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _bm25_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    doc_freq: dict[str, int],
    avg_dl: float,
    n_docs: int,
    k1: float = _BM25_K1,
    b: float = _BM25_B,
) -> float:
    """Compute BM25 score for a single document.

    Standard BM25 formula. Pure Python — no FTS5 dependency since the
    tool corpus is small (typically <50 entries).
    """
    if not doc_tokens or n_docs == 0:
        return 0.0
    tf = Counter(doc_tokens)
    dl = len(doc_tokens)
    score = 0.0
    for term in query_tokens:
        if term not in tf:
            continue
        df = doc_freq.get(term, 0)
        if df == 0:
            continue
        idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
        freq = tf[term]
        denom = freq + k1 * (1 - b + b * (dl / avg_dl if avg_dl > 0 else 1.0))
        if denom > 0:
            score += idf * (freq * (k1 + 1)) / denom
    return score


def _rrf(rank: int | None, k: int = _RRF_K) -> float:
    """Reciprocal Rank Fusion contribution (rank is 1-indexed)."""
    if rank is None:
        return 0.0
    return 1.0 / (k + rank)


def _tool_corpus_text(tool: ToolOrSkill) -> str:
    """Build the searchable text for a tool/skill from its metadata.

    Falls back to name + category when description is absent (precondition
    gap: existing tool-shed.yaml has no description field). For
    ``SkillCandidate`` the domain is folded into the corpus alongside
    the name so domain queries surface skills.
    """
    parts: list[str] = []
    if tool.name:
        # Split hyphenated/underscored names into separate tokens.
        parts.append(tool.name.replace("-", " ").replace("_", " "))
    domain = getattr(tool, "domain", "")
    if domain:
        parts.append(domain.replace("-", " ").replace("_", " "))
    if tool.category:
        parts.append(tool.category)
    if tool.description:
        parts.append(tool.description)
    return " ".join(parts)


# Sprint 07.05 cache constants — operator-tunable. Filesystem walks during
# every Smart Tool RAG call would amplify p99 latency on Discord paths;
# caching mirrors the existing tool-shed.yaml load-once pattern while
# still picking up edits via mtime invalidation.
_MARKDOWN_SKILL_CACHE_TTL_SECONDS: float = 60.0

# Module-level OTEL tracer for Smart Tool RAG resolve spans (E2.2 #1239)
_otel_tracer = get_otel_tracer("bumba.tool_shed")


class ToolShed:
    def __init__(self, config_path: Path) -> None:
        self._tools: dict[str, ToolConfig] = {}
        # Sprint 07.05 (#1034) — markdown-skill discovery cache. Keyed by
        # the absolute directory string so different operator-supplied
        # paths get isolated TTLs.
        self._md_cache: dict[str, tuple[float, float, list[SkillCandidate]]] = {}
        self._load(config_path)

    def _load(self, path: Path) -> None:
        if not path.exists():
            log.warning("Tool Shed config not found: %s", path)
            return
        import yaml
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            log.exception("Failed to parse Tool Shed config: %s", path)
            return
        tools = data.get("tools", {})
        if not isinstance(tools, dict):
            return
        for name, config in tools.items():
            if not isinstance(config, dict):
                continue
            agents = config.get("agents", [])
            if isinstance(agents, list):
                agents = [str(a) for a in agents]
            self._tools[name] = ToolConfig(
                name=name,
                category=config.get("category", ""),
                always_loaded=config.get("always_loaded", False),
                agents=agents,
                description=config.get("description", ""),
            )
        log.info("Tool Shed loaded %d tools from %s", len(self._tools), path)

    def all_tools(self) -> list[str]:
        return sorted(self._tools.keys())

    def always_loaded(self) -> list[str]:
        return sorted(name for name, c in self._tools.items() if c.always_loaded)

    def tools_for_agent(self, agent_name: str) -> list[str]:
        result: set[str] = set()
        for name, config in self._tools.items():
            if config.always_loaded:
                result.add(name)
            elif "all" in config.agents or agent_name in config.agents:
                result.add(name)
        return sorted(result)

    def get_tool(self, name: str) -> ToolConfig | None:
        return self._tools.get(name)

    def get_tools_for_agent(self, agent_name: str) -> list[ToolConfig]:
        """Return full ToolConfig objects for an agent.

        Bridge-independent API — usable by Pydantic AI agents
        and any Python consumer without bridge imports.
        """
        result: list[ToolConfig] = []
        for config in self._tools.values():
            if config.always_loaded:
                result.append(config)
            elif "all" in config.agents or agent_name in config.agents:
                result.append(config)
        return sorted(result, key=lambda t: t.name)

    def get_tools_for_intent(
        self,
        intent_text: str,
        top_k: int = 5,
        *,
        rerank: bool = False,
        embed_fn: Callable[[str], list[float]] | None = None,
        rerank_fn: Callable[[str, list[ToolConfig]], list[ToolConfig]] | None = None,
        include_markdown: bool = False,
        markdown_skills_dir: Path | None = None,
    ) -> list[ToolOrSkill]:
        """Smart-Tool-RAG selection: hybrid BM25 + embedding + optional rerank.

        Concept-only port of the OpenSpace Smart Tool RAG idea (MIT). Returns
        the top_k tools most relevant to the operator's stated intent.

        Pipeline:
          1. BM25 over each tool's corpus text (name + category + description).
          2. Embedding cosine similarity using ``embed_fn`` (lazy-loaded
             ``LocalEmbeddingEngine`` if not provided). Skipped silently when
             unavailable, leaving BM25-only behavior.
          3. RRF fusion of the two rankings.
          4. Optional LLM rerank (Haiku) of the fused top candidates when
             ``rerank=True``. Default False keeps cost ≤$0.005/call; rerank
             enabled targets ≤$0.05/call.

        Args:
            intent_text: The natural-language intent. Empty / whitespace falls
                back to ``get_tools_for_agent("all")`` shape (always-loaded
                tools), preserving the existing return type.
            top_k: Maximum tools to return.
            rerank: If True, invoke ``rerank_fn`` on fused top candidates.
            embed_fn: Optional embedding function. When None, attempts to
                instantiate ``LocalEmbeddingEngine`` lazily; falls back to
                BM25-only on any error.
            rerank_fn: Optional rerank callable invoked with
                ``(intent_text, candidates) -> reordered_candidates``. Bypassed
                when ``rerank=False``.

        Returns:
            Up to ``top_k`` ToolConfig (or SkillCandidate when
            ``include_markdown=True``) objects ordered by fused score. Result
            items expose a ``kind`` field — ``"tool"`` for YAML-registered
            tools, ``"skill"`` for discovered markdown skills.

        Precondition gap: the existing ``config/tool-shed.yaml`` has no
        ``description`` field, so the corpus relies on name + category. Tools
        gain better intent matching once descriptions are added — see PR
        body. No fabricated descriptions are injected.

        Sprint 07.05 (#1034): when ``include_markdown=True``, discovered
        markdown skills (via ``SkillEvolutionEngine.discover_markdown_skills``)
        join the candidate corpus alongside YAML tools. Discovery results
        cache for ``_MARKDOWN_SKILL_CACHE_TTL_SECONDS`` seconds with
        directory-mtime invalidation so edits are picked up without a
        bridge restart. Backwards-compatible: default ``include_markdown=False``
        returns the original tool-only shape. Concept-only port of
        browser-harness's git-friendly skill directory (MIT, paraphrased).
        """
        if top_k <= 0:
            return []
        if not intent_text or not intent_text.strip():
            # Empty intent → degrade to always-loaded (matches existing shape).
            return [t for t in sorted(self._tools.values(), key=lambda x: x.name) if t.always_loaded][:top_k]

        tools: list[ToolOrSkill] = list(self._tools.values())
        if include_markdown:
            md_skills = self._discover_cached_markdown_skills(markdown_skills_dir)
            tools.extend(md_skills)
        if not tools:
            return []

        # E2.2 (#1239) — emit one OTEL span per resolve with BM25/vector/RRF score attributes.
        with _otel_tracer.start_as_current_span(
            "tool_shed.resolve",
            attributes={"query": intent_text[:120], "corpus_size": len(tools)},
        ) as _span:
            # --- Step 1: BM25 over tool corpus ---
            query_tokens = _tokenize(intent_text)
            doc_token_lists: list[list[str]] = [_tokenize(_tool_corpus_text(t)) for t in tools]
            n_docs = len(tools)
            avg_dl = sum(len(d) for d in doc_token_lists) / n_docs if n_docs else 0.0
            doc_freq: dict[str, int] = {}
            for tokens in doc_token_lists:
                for term in set(tokens):
                    doc_freq[term] = doc_freq.get(term, 0) + 1

            bm25_scored: list[tuple[int, float]] = []
            for idx, doc_tokens in enumerate(doc_token_lists):
                score = _bm25_score(query_tokens, doc_tokens, doc_freq, avg_dl, n_docs)
                if score > 0:
                    bm25_scored.append((idx, score))
            bm25_scored.sort(key=lambda x: x[1], reverse=True)
            bm25_rank: dict[int, int] = {idx: rank for rank, (idx, _s) in enumerate(bm25_scored, start=1)}

            # --- Step 2: Embedding cosine (best-effort) ---
            vector_rank: dict[int, int] = {}
            vector_scores: dict[int, float] = {}  # idx → raw cosine score for span attrs
            embed = embed_fn or self._default_embed_fn()
            if embed is not None:
                try:
                    q_vec = embed(intent_text)
                    vector_scored: list[tuple[int, float]] = []
                    for idx, t in enumerate(tools):
                        corpus = _tool_corpus_text(t)
                        if not corpus.strip():
                            continue
                        d_vec = embed(corpus)
                        sim = _cosine(q_vec, d_vec)
                        vector_scored.append((idx, sim))
                    vector_scored.sort(key=lambda x: x[1], reverse=True)
                    vector_rank = {idx: rank for rank, (idx, _s) in enumerate(vector_scored, start=1)}
                    vector_scores = {idx: s for idx, s in vector_scored}
                except Exception as exc:  # pragma: no cover — defensive
                    log.debug("Smart-Tool-RAG embedding step skipped: %s", exc)

            # --- Step 3: RRF fusion ---
            fused: list[tuple[int, float]] = []
            for idx in range(n_docs):
                score = (
                    _WEIGHT_BM25 * _rrf(bm25_rank.get(idx))
                    + _WEIGHT_VECTOR * _rrf(vector_rank.get(idx))
                )
                if score > 0:
                    fused.append((idx, score))
            fused.sort(key=lambda x: x[1], reverse=True)

            # Deterministic candidate cap: 3x top_k for rerank, top_k otherwise.
            cap = max(top_k * 3, top_k) if rerank else top_k
            candidates = [tools[idx] for idx, _s in fused[:cap]]

            if not candidates:
                return []

            # --- Step 4: Optional LLM rerank ---
            if rerank and rerank_fn is not None and len(candidates) > 1:
                try:
                    reranked = rerank_fn(intent_text, candidates)
                    if reranked:
                        candidates = reranked
                except Exception as exc:  # pragma: no cover — defensive
                    log.warning("Smart-Tool-RAG rerank failed, keeping fused order: %s", exc)

            result = candidates[:top_k]

            # Record winner attributes on the span (best-effort; never raises).
            if result and fused:
                winner_idx = fused[0][0]
                winner = result[0]
                _span.attributes["winner_name"] = str(winner.name)
                # Raw BM25 score for winner (0.0 when not in ranked list)
                bm25_score_val = next(
                    (s for i, s in bm25_scored if i == winner_idx), 0.0
                )
                _span.attributes["bm25_score"] = float(bm25_score_val)
                # Raw vector cosine score for winner (0.0 when embedding skipped)
                _span.attributes["vector_score"] = float(vector_scores.get(winner_idx, 0.0))
                # RRF fused score for winner
                _span.attributes["rrf_score"] = float(fused[0][1])

            return result

    def _default_embed_fn(self) -> Callable[[str], list[float]] | None:
        """Return a lazy LocalEmbeddingEngine.embed callable, or None on failure."""
        try:
            from .local_embeddings import LocalEmbeddingEngine

            engine = LocalEmbeddingEngine()
            return engine.embed
        except Exception as exc:  # pragma: no cover — defensive
            log.debug("LocalEmbeddingEngine unavailable, BM25-only: %s", exc)
            return None

    # --- Sprint 07.05 (#1034) markdown-skill discovery integration ---

    def _discover_cached_markdown_skills(
        self,
        skills_dir: Path | None,
    ) -> list[SkillCandidate]:
        """Return discovered markdown skills with TTL + mtime caching.

        Cache key is the resolved directory string. Two calls within
        ``_MARKDOWN_SKILL_CACHE_TTL_SECONDS`` of each other reuse the
        in-memory result. A directory mtime change invalidates the
        cached entry early so operator edits land without a restart.

        Discovery delegates to ``SkillEvolutionEngine.discover_markdown_skills``;
        any unexpected error degrades to an empty list with a warning so
        retrieval never crashes.
        """
        try:
            target_dir = self._resolve_skills_dir(skills_dir)
        except Exception as exc:  # pragma: no cover — defensive
            log.warning("tool_shed markdown discovery: skills_dir resolution failed: %s", exc)
            return []

        if target_dir is None or not target_dir.is_dir():
            return []

        try:
            current_mtime = target_dir.stat().st_mtime
        except OSError as exc:  # pragma: no cover — defensive
            log.warning("tool_shed markdown discovery: stat(%s) failed: %s", target_dir, exc)
            return []

        cache_key = str(target_dir.resolve())
        now = time.monotonic()
        cached = self._md_cache.get(cache_key)
        if cached is not None:
            cached_at, cached_mtime, cached_skills = cached
            fresh = (now - cached_at) < _MARKDOWN_SKILL_CACHE_TTL_SECONDS
            if fresh and cached_mtime == current_mtime:
                return cached_skills

        skills = self._discover_markdown_skills_uncached(target_dir)
        self._md_cache[cache_key] = (now, current_mtime, skills)
        return skills

    @staticmethod
    def _resolve_skills_dir(skills_dir: Path | None) -> Path | None:
        """Pick the markdown-skills directory; fall back to the engine default."""
        if skills_dir is not None:
            return Path(skills_dir)
        try:
            from .skill_evolution import DEFAULT_MARKDOWN_SKILLS_DIR
        except Exception as exc:  # pragma: no cover — defensive
            log.debug("tool_shed markdown discovery: skill_evolution import failed: %s", exc)
            return None
        return Path(DEFAULT_MARKDOWN_SKILLS_DIR)

    @staticmethod
    def _discover_markdown_skills_uncached(target_dir: Path) -> list[SkillCandidate]:
        """One filesystem walk; convert MarkdownSkill → SkillCandidate.

        Errors on a single file are swallowed inside ``discover_markdown_skills``
        with a warning log — this method only guards the engine import and
        instantiation. An empty directory simply yields ``[]``.
        """
        try:
            from .skill_evolution import SkillEvolutionEngine
        except Exception as exc:  # pragma: no cover — defensive
            log.warning("tool_shed markdown discovery: engine import failed: %s", exc)
            return []
        try:
            engine = SkillEvolutionEngine()
            md_skills = engine.discover_markdown_skills(target_dir)
        except Exception as exc:
            log.warning("tool_shed markdown discovery: walk failed: %s", exc)
            return []

        candidates: list[SkillCandidate] = []
        for skill in md_skills:
            description = ""
            fm = skill.frontmatter if isinstance(skill.frontmatter, dict) else {}
            raw_desc = fm.get("description")
            if isinstance(raw_desc, str):
                description = raw_desc
            candidates.append(
                SkillCandidate(
                    name=skill.name,
                    domain=skill.domain,
                    description=description,
                    path=skill.path,
                    frontmatter=fm,
                )
            )
        return candidates

    @classmethod
    def from_config(cls, config_path: str | Path) -> ToolShed:
        """Factory method for bridge-independent instantiation."""
        return cls(config_path=Path(config_path))


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity (local copy to avoid hard import dependency)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    mag_a = 0.0
    mag_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        mag_a += x * x
        mag_b += y * y
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (math.sqrt(mag_a) * math.sqrt(mag_b))
