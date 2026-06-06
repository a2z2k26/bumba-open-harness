"""Specialist retrieval — embedding-ranked top-K replacement for full enumeration.

Sprint #1112/4.06 (#2153) — Initial entry #1 in the master plan asked us to
stop enumerating every specialist in every chief prompt. As the roster grows,
the prompt grows linearly. This module ranks specialists by cosine similarity
between the incoming directive and each specialist's declared
``description:`` frontmatter from ``~/.claude/agents/<dept>-*.md``, then
returns the top K matches.

Wiring (per spec):

- ``SpecialistRetriever`` is feature-flagged via
  ``BridgeConfig.specialist_retrieval_enabled`` (default ``False``).
- When the flag is OFF, this module is dormant — the chief sees the full
  roster as it always has.
- When the flag is ON, the caller passes the directive text and the
  department name, gets back ``list[SpecialistMatch]``, and substitutes
  them in place of the full roster.

Cache: per-department in-process dict, invalidated when relevant specialist
files' path/mtime/size signature changes. Ancillary no-prefix specialists are
included only in the engineering bucket.

Cosine similarity is inlined here (``_cosine``) rather than re-using
``local_embeddings.cosine_similarity``: both implementations are 4 lines and
keeping the helper local makes this module self-contained and avoids a
cross-module dependency for what is effectively trivial math.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path

from bridge.local_embeddings import LocalEmbeddingEngine

log = logging.getLogger(__name__)

_DEPARTMENT_PREFIXES: frozenset[str] = frozenset(
    {"design", "engineering", "qa", "ops", "strategy", "board"}
)
_IndexEntry = tuple[str, str, list[float]]
_FileSignature = tuple[str, int, int]


# --- frontmatter parser ----------------------------------------------------

# Specialist files at ``~/.claude/agents/*.md`` open with YAML frontmatter:
#
#     ---
#     name: design-ui-designer
#     description: "You are a UI Designer ..."
#     model: opus
#     color: red
#     ---
#
# We only need ``name`` and ``description``. Avoid importing PyYAML for a
# 2-field parse (no PyYAML dep in this codebase; ``bridge/config.py`` uses
# ``tomllib``). Lightweight regex-based extraction handles both unquoted
# and double-quoted ``description:`` values.
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_FIELD_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*):\s*(.*?)\s*$", re.MULTILINE)


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Return YAML-frontmatter top-level string fields from ``text``.

    Only parses scalar string values (the two fields we need). Quoted values
    have their surrounding ``"..."`` stripped. Missing frontmatter returns
    an empty dict — the caller treats that as "skip this file".
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    body = match.group(1)
    fields: dict[str, str] = {}
    for key, value in _FIELD_RE.findall(body):
        v = value.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
            v = v[1:-1]
        fields[key] = v
    return fields


# --- cosine similarity (inline) -------------------------------------------


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors. Returns 0.0 if either is zero."""
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


# --- public types ----------------------------------------------------------


@dataclass(frozen=True)
class SpecialistMatch:
    """One ranked specialist returned by ``retrieve_top_k``."""

    name: str
    score: float
    description: str


# --- main class ------------------------------------------------------------


class SpecialistRetriever:
    """Rank specialists by embedding similarity to a directive.

    Specialist descriptions are sourced from
    ``<agents_dir>/<dept-prefix>-*.md`` frontmatter. Each department's index
    is built lazily on first ``retrieve_top_k`` call for that department and
    cached until the relevant specialist files change.

    Department prefix mapping (per the master spec):

    - ``design``, ``engineering``, ``qa``, ``ops``, ``strategy``, ``board``
      — match ``<dept>-*.md`` directly.

    Ancillary agents without a department prefix (e.g. ``ai-engineer.md``,
    ``fastapi-pro-developer.md``) are included under the engineering bucket.
    """

    def __init__(self, embeddings: LocalEmbeddingEngine, agents_dir: Path) -> None:
        self._embeddings = embeddings
        self._agents_dir = agents_dir
        # name → list of (specialist_name, description, embedding_vec)
        self._cache: dict[str, list[_IndexEntry]] = {}
        self._cache_signatures: dict[str, tuple[_FileSignature, ...]] = {}

    def retrieve_top_k(
        self, directive: str, department: str, k: int = 3
    ) -> list[SpecialistMatch]:
        """Return the top-``k`` specialists for ``department`` ranked by
        cosine similarity between their description and ``directive``.

        Args:
            directive: The incoming task text. The chief's directive body
                is the strongest signal we have at delegation time.
            department: Department prefix (``design`` / ``engineering`` /
                etc). Used to filter ``<agents_dir>/<dept>-*.md``.
            k: Number of matches to return. ``k == 0`` returns ``[]``;
                ``k`` greater than the available roster returns the full
                ranked roster.

        Returns:
            A list of ``SpecialistMatch`` sorted by descending score.

        Raises:
            ValueError: When the resolved department directory contains no
                matching ``<dept>-*.md`` files. The error message includes
                the scanned glob so the operator can verify the layout.
        """
        if k < 0:
            raise ValueError(f"k must be >= 0, got {k}")
        if k == 0:
            return []

        paths = self._candidate_paths(department)
        signature = self._signature(paths)
        if (
            department not in self._cache
            or self._cache_signatures.get(department) != signature
        ):
            self._cache[department] = self._build_index(department, paths)
            self._cache_signatures[department] = signature

        index = self._cache[department]
        if not index:
            # _build_index already cached an empty list — raise here so
            # repeat calls surface the same informative error rather than
            # silently returning [].
            raise ValueError(
                f"No specialists found for department {department!r}. "
                f"Scanned glob: {self._agents_dir}/{department}-*.md"
            )

        directive_vec = self._embeddings.embed(directive)
        scored: list[tuple[str, str, float]] = [
            (name, desc, _cosine(directive_vec, vec))
            for name, desc, vec in index
        ]
        scored.sort(key=lambda t: -t[2])
        return [
            SpecialistMatch(name=n, score=s, description=d)
            for n, d, s in scored[:k]
        ]

    def _candidate_paths(self, department: str) -> tuple[Path, ...]:
        """Return specialist files that belong to ``department``.

        Department-prefixed files stay scoped to their matching department.
        Ancillary files without a known department prefix are scoped to
        engineering because Zone 3 engineering owns code-specialist delegation.
        """
        if not self._agents_dir.exists():
            return ()

        paths: set[Path] = set(self._agents_dir.glob(f"{department}-*.md"))
        if department == "engineering":
            for path in self._agents_dir.glob("*.md"):
                if not any(
                    path.name.startswith(f"{prefix}-")
                    for prefix in _DEPARTMENT_PREFIXES
                ):
                    paths.add(path)

        return tuple(sorted(paths))

    def _signature(self, paths: tuple[Path, ...]) -> tuple[_FileSignature, ...]:
        """Return a cheap file signature for cache invalidation."""
        signature: list[_FileSignature] = []
        for path in paths:
            try:
                stat = path.stat()
            except OSError:
                continue
            signature.append((str(path), stat.st_mtime_ns, stat.st_size))
        return tuple(signature)

    def _build_index(self, department: str, paths: tuple[Path, ...]) -> list[_IndexEntry]:
        """Scan, parse, and embed every specialist file for ``department``.

        Returns a list of
        ``(specialist_name, description, embedding_vec)`` tuples in
        filesystem-iteration order (order is irrelevant — the caller
        sorts by score).
        """
        index: list[_IndexEntry] = []
        if not self._agents_dir.exists():
            log.warning(
                "specialist_retrieval.agents_dir_missing dir=%s department=%s",
                self._agents_dir, department,
            )
            return index

        for path in paths:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                log.warning(
                    "specialist_retrieval.read_failed path=%s error=%s",
                    path, exc,
                )
                continue
            fields = _parse_frontmatter(text)
            name = fields.get("name", "").strip()
            desc = fields.get("description", "").strip()
            if not name or not desc:
                log.debug(
                    "specialist_retrieval.skipping_no_frontmatter path=%s",
                    path,
                )
                continue
            vec = self._embeddings.embed(desc)
            index.append((name, desc, vec))

        log.info(
            "specialist_retrieval.index_built department=%s count=%d",
            department, len(index),
        )
        return index
