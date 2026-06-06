"""Routing brain — composes IntentClassification + modality + environment into RoutingDecision.

This module is the single decision point that converts a raw message into
a fully-specified RoutingDecision, telling downstream executors exactly
which environment to use and why.

Complexity heuristic (hard rules):
    complexity >= 5  → "worktree"   (extreme work always isolates)
    complexity >= 4 AND modality=="text" → "worktree"  (complex code isolation)
    complexity <= 2  → "subagent"   (trivial — quick subagent)
    complexity 3-4   → "subagent"   (default for moderate work)

EnvironmentSelector (from bridge.environment_selector) is an optional hint
layer wired by Z3.9. The hard rules above always take precedence; the selector
can only influence the moderate range (complexity 3-4).
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from bridge.intent_classifier import classify, Intent, IntentClassification
from bridge.modality_detector import Modality

# Guard the EnvironmentSelector import — it may not be importable in test env
# (work_order dependency may be absent).  Accept None gracefully.
try:
    from bridge.environment_selector import EnvironmentSelector as _EnvironmentSelector  # noqa: F401
    EnvironmentSelector = _EnvironmentSelector
except ImportError:  # pragma: no cover
    EnvironmentSelector = None  # type: ignore[assignment,misc]

if TYPE_CHECKING:
    # Type-only import so mypy can resolve the annotation without a runtime import.
    pass


# Recognised environment literals (mirrors bridge.work_order.Environment values).
_ENV_SUBAGENT = "subagent"
_ENV_TMUX = "tmux"
_ENV_WORKTREE = "worktree"
_ENV_E2B = "e2b"
_ENV_DEPARTMENT = "department"

_VALID_ENVIRONMENTS = frozenset({
    _ENV_SUBAGENT, _ENV_TMUX, _ENV_WORKTREE, _ENV_E2B, _ENV_DEPARTMENT,
})

# ---------------------------------------------------------------------------
# Intent × Modality → (Environment, department_hint | None)
#
# Department mappings route analytical, testing, deployment, and documentation
# intents to Zone 4 department execution environments.  Non-DEPARTMENT targets
# carry None as the hint.
# ---------------------------------------------------------------------------
_INTENT_MODALITY_TO_ENV: dict[tuple[Intent, Modality], tuple[str, str | None]] = {
    # Strategy / analysis
    (Intent.ANALYZE, Modality.SOLO): (_ENV_DEPARTMENT, "strategy"),
    (Intent.ANALYZE, Modality.REVIEW): (_ENV_DEPARTMENT, "board"),
    (Intent.ANALYZE, Modality.ORCHESTRATED): (_ENV_DEPARTMENT, "board"),
    # QA / testing
    (Intent.TEST, Modality.PARALLEL): (_ENV_DEPARTMENT, "qa"),
    (Intent.TEST, Modality.SOLO): (_ENV_DEPARTMENT, "qa"),
    # Operations / deployment
    (Intent.DEPLOY, Modality.SEQUENTIAL): (_ENV_DEPARTMENT, "ops"),
    (Intent.DEPLOY, Modality.SOLO): (_ENV_DEPARTMENT, "ops"),
    # Design / documentation
    (Intent.DOCUMENT, Modality.SOLO): (_ENV_DEPARTMENT, "design"),
}


@dataclass(frozen=True)
class RoutingDecision:
    """Fully-resolved routing decision for a single message.

    Fields
    ------
    intent: Intent
        The classified intent of the message.
    confidence: float
        Classifier confidence, 0.0–1.0.
    complexity: int
        Complexity score, 1 (trivial) to 5 (extreme).
    modality: str
        Input modality, e.g. "text", "voice", "file".
    environment: str | None
        Execution environment to use.  None means "use system default".
        Otherwise one of: "subagent", "tmux", "worktree", "e2b".
    reason: str
        Human-readable explanation of why this environment was chosen.
    """

    intent: Intent
    confidence: float
    complexity: int
    modality: str
    environment: Optional[str]
    reason: str
    department_hint: Optional[str] = None


# ---------------------------------------------------------------------------
# LRU cache for routing decisions (S09 sub-bet 2)
# ---------------------------------------------------------------------------

_CACHE_MAX_SIZE = 128
_CACHE_TTL_S = 86_400  # 24h


class _LRUCache:
    """Simple TTL-aware LRU cache keyed on (intent_hash, modality_hash)."""

    def __init__(self, maxsize: int = _CACHE_MAX_SIZE, ttl_s: float = _CACHE_TTL_S) -> None:
        self._maxsize = maxsize
        self._ttl = ttl_s
        self._cache: dict[tuple[str, str], tuple[RoutingDecision, float]] = {}
        self._order: list[tuple[str, str]] = []

    def _key(self, message: str, modality: str) -> tuple[str, str]:
        ih = hashlib.sha256(message.encode()).hexdigest()[:16]
        mh = hashlib.md5(modality.encode()).hexdigest()[:8]
        return (ih, mh)

    def get(self, message: str, modality: str) -> RoutingDecision | None:
        key = self._key(message, modality)
        entry = self._cache.get(key)
        if entry is None:
            return None
        decision, ts = entry
        if time.time() - ts > self._ttl:
            self._cache.pop(key, None)
            try:
                self._order.remove(key)
            except ValueError:
                pass
            return None
        # Move to end (most recently used)
        try:
            self._order.remove(key)
        except ValueError:
            pass
        self._order.append(key)
        return decision

    def put(self, message: str, modality: str, decision: RoutingDecision) -> None:
        key = self._key(message, modality)
        if key in self._cache:
            try:
                self._order.remove(key)
            except ValueError:
                pass
        elif len(self._cache) >= self._maxsize:
            # Evict LRU
            if self._order:
                oldest = self._order.pop(0)
                self._cache.pop(oldest, None)
        self._cache[key] = (decision, time.time())
        self._order.append(key)

    def clear(self) -> None:
        self._cache.clear()
        self._order.clear()


class RoutingBrain:
    """Composes IntentClassification + modality + environment into a RoutingDecision.

    Parameters
    ----------
    selector:
        Optional EnvironmentSelector instance.  When provided and the task
        lands in the moderate (3-4) complexity band, the selector's
        ``suggest`` method (if present) is called for a hint.  Hard rules
        always override any selector hint.
    """

    def __init__(
        self,
        selector: Optional[object] = None,  # EnvironmentSelectorT | None
        cache_enabled: bool = True,
    ) -> None:
        self._selector = selector
        self._cache = _LRUCache() if cache_enabled else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def decide(
        self,
        message_text: str,
        *,
        modality: str = "text",
    ) -> RoutingDecision:
        """Produce a RoutingDecision for *message_text*.

        Parameters
        ----------
        message_text:
            The raw message text to route.
        modality:
            Input modality (default ``"text"``).  Affects routing when
            combined with high complexity — complex text work gets worktree
            isolation.

        Returns
        -------
        RoutingDecision
            Frozen dataclass with all fields populated.
        """
        # S09: LRU cache lookup
        if self._cache is not None:
            cached = self._cache.get(message_text, modality)
            if cached is not None:
                try:
                    from bridge.z3_metrics import record_routing_brain_cache
                    record_routing_brain_cache(hit=True)
                except ImportError:
                    pass
                return cached
            try:
                from bridge.z3_metrics import record_routing_brain_cache
                record_routing_brain_cache(hit=False)
            except ImportError:
                pass

        classification: IntentClassification = classify(message_text)
        intent = classification.intent
        confidence = classification.confidence
        complexity = classification.complexity

        # Detect execution modality from message text for department routing.
        from bridge.modality_detector import ModalityDetector
        detected_modality = ModalityDetector().detect(message_text).modality

        environment, reason, dept_hint = self._select_environment(
            intent=intent,
            complexity=complexity,
            modality=modality,
            detected_modality=detected_modality,
        )

        decision = RoutingDecision(
            intent=intent,
            confidence=confidence,
            complexity=complexity,
            modality=modality,
            environment=environment,
            reason=reason,
            department_hint=dept_hint,
        )

        # Store in cache
        if self._cache is not None:
            self._cache.put(message_text, modality, decision)

        return decision

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _select_environment(
        self,
        *,
        intent: Intent,
        complexity: int,
        modality: str,
        detected_modality: Modality | None = None,
    ) -> tuple[str, str, str | None]:
        """Apply heuristics and return (environment, reason, department_hint).

        Hard rules (evaluated first, cannot be overridden):
        1. complexity >= 5  → worktree
        2. complexity >= 4 AND modality == "text" → worktree
        3. complexity <= 2  → check department table first, then subagent

        Department mapping (checked before default subagent):
        - If (intent, detected_modality) exists in _INTENT_MODALITY_TO_ENV,
          route to DEPARTMENT with the specified department hint.

        Moderate range (complexity 3-4, non-text, or non-hard-rule path):
        - Check department mapping table.
        - Consult EnvironmentSelector.suggest() if available.
        - Default: subagent.
        """
        # --- Hard rule 1: extreme complexity always isolates ----------------
        if complexity >= 5:
            return (
                _ENV_WORKTREE,
                f"Complexity {complexity} (extreme) — worktree isolation required.",
                None,
            )

        # --- Hard rule 2: high-complexity text work isolates ----------------
        if complexity >= 4 and modality == "text":
            return (
                _ENV_WORKTREE,
                f"Complexity {complexity} text task — worktree isolation for code safety.",
                None,
            )

        # --- Department routing via (Intent, Modality) table ----------------
        if detected_modality is not None:
            dept_entry = _INTENT_MODALITY_TO_ENV.get((intent, detected_modality))
            if dept_entry is not None:
                env, dept_hint = dept_entry
                return (
                    env,
                    (
                        f"Intent '{intent.value}' + modality '{detected_modality.value}' "
                        f"→ department '{dept_hint}'."
                    ),
                    dept_hint,
                )

        # --- Hard rule 3: trivial → quick subagent --------------------------
        if complexity <= 2:
            return (
                _ENV_SUBAGENT,
                f"Complexity {complexity} (trivial) — subagent is sufficient.",
                None,
            )

        # --- Moderate range: consult selector for a hint --------------------
        selector_hint: Optional[str] = None
        if self._selector is not None:
            suggest_fn = getattr(self._selector, "suggest", None)
            if callable(suggest_fn):
                raw = suggest_fn(intent=intent.value, complexity=complexity)
                if isinstance(raw, str) and raw in _VALID_ENVIRONMENTS:
                    selector_hint = raw

        if selector_hint is not None:
            return (
                selector_hint,
                (
                    f"Complexity {complexity} — EnvironmentSelector suggested "
                    f"'{selector_hint}' for intent '{intent.value}'."
                ),
                None,
            )

        # Default for moderate range
        return (
            _ENV_SUBAGENT,
            f"Complexity {complexity} (moderate) — defaulting to subagent.",
            None,
        )
