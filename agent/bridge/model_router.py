"""Budget-aware model routing.

Classifies message complexity and tracks costs for model selection.
Infrastructure-only for now (logs decisions while on subscription).

D7.5 finding F-5: operator notes naturalness has improved (haiku route for
short/conversational queries is the likely cause). Persona pass D7.7 (#1419)
will subsume any remaining naturalness gap.

MS3.10 additions:
- classify() — three-tier smart routing (haiku/sonnet/opus), rule-based < 5ms
- strip_model_override() — extract @haiku:/@sonnet:/@opus: prefix overrides
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

from . import model_defaults  # P0.01 canonical default-model constants
from .departments import detect_department

log = logging.getLogger(__name__)

# Hard model override for /careful session hook (#19 — Tier B decision by operator)
# This exact model ID is used regardless of smart routing tier. Sourced from
# canonical constant (P0.01); current value "claude-opus-4-5-20251001" preserved.
CAREFUL_OPUS_MODEL = model_defaults.DEFAULT_CAREFUL_MODEL


@dataclass
class RoutingDecision:
    """Result of model routing decision."""

    tier: str  # "simple", "medium", "complex"
    model: str
    reason: str
    budget_remaining: float = 0.0
    downgraded: bool = False


# Patterns indicating complex queries
_COMPLEX_PATTERNS = [
    re.compile(r"(?i)(refactor|redesign|architect|implement|build|create|develop)\s"),
    re.compile(r"(?i)(analyze|debug|investigate|diagnose|audit)\s"),
    re.compile(r"(?i)(code|function|class|module|api|database|schema)\s"),
    re.compile(r"(?i)(\bwrite\b.*\b(test|code|script|program)\b)"),
    re.compile(r"(?i)(how (do|does|can|should|would))"),
    re.compile(r"(?i)(explain|compare|evaluate|review)"),
]

# Patterns indicating simple queries
_SIMPLE_PATTERNS = [
    re.compile(r"(?i)^(hi|hey|hello|thanks|thank you|ok|okay|yes|no|sure)\b"),
    re.compile(r"(?i)^(what time|what day|what date)"),
    re.compile(r"(?i)^(remind me|set (a )?reminder)"),
    re.compile(r"(?i)^(good (morning|afternoon|evening|night))"),
]


# --- MS3.10: Three-Tier Smart Routing ---

# Override prefix pattern: @haiku: / @sonnet: / @opus: at start of message
_OVERRIDE_RE = re.compile(r"^@(haiku|sonnet|opus):\s*", re.IGNORECASE)

# Haiku indicators — simple Q&A, status checks, yes/no, formatting
_HAIKU_PATTERNS = [
    re.compile(r"(?i)^(yes|no|ok|okay|sure|thanks|thank you|hi|hey|hello|bye)\b"),
    re.compile(r"(?i)^(good (morning|afternoon|evening|night))"),
    re.compile(r"(?i)^(what time|what day|what date|what is the date)"),
    re.compile(r"(?i)^(remind me|set (a )?reminder)"),
    re.compile(r"(?i)^(status|ping|health|uptime)\b"),
    re.compile(r"(?i)\b(format|reformat|capitalize|uppercase|lowercase|indent)\b"),
    re.compile(r"(?i)^(is (it|this|that)|are (you|we|they)|do (you|we)|does (it|this))"),
    re.compile(r"(?i)^(list|show|display|print|echo)\s"),
    re.compile(r"(?i)^(what|who|when|where)\s+(is|was|are|were)\s+\w+\??$"),
]

# Opus indicators — architecture, multi-file, creative, novel problems
_OPUS_PATTERNS = [
    re.compile(r"(?i)\b(architect(ure)?|redesign|system design|design pattern)\b"),
    re.compile(r"(?i)\b(multi[- ]?file|across (multiple |several )?files|refactor(ing)?\s+(the|this|our)\s+\w+\s+(system|module|codebase))\b"),
    re.compile(r"(?i)\b(complex|novel|creative|innovative|from scratch)\b"),
    re.compile(r"(?i)\b(trade[- ]?off|pros and cons|compare .+ (approaches|architectures|designs))\b"),
    re.compile(r"(?i)\b(strategic|long[- ]?term|roadmap|migration plan|migration strategy)\b"),
    re.compile(r"(?i)\b(security (audit|review|analysis)|threat model)\b"),
    re.compile(r"(?i)\b(write (a |an )?(short story|poem|essay|article|blog post))\b"),
    re.compile(r"(?i)\b(performance (optimization|profiling)|memory leak)\b"),
    re.compile(r"(?i)\b(race condition|deadlock|concurrency (issue|bug|problem))\b"),
]

# Code block detection
_CODE_BLOCK_RE = re.compile(r"```")

# Multi-step / multi-part indicators
_MULTI_STEP_RE = re.compile(
    r"(?i)(step[s ]?\d|first.*then.*finally|1\.\s|2\.\s|3\.\s|"
    r"multiple (steps|parts|phases)|and also|additionally)"
)


DEFAULT_MODEL = "haiku"  # Safe fallback when trust gate denies routing


def classify(message: str, trust: object | None = None) -> str:
    """Classify message into model tier: 'haiku', 'sonnet', or 'opus'.

    Args:
        message: The operator message to classify.
        trust: Optional TrustScoreEngine instance. When provided, calls
               ``trust.check_access("routing")`` before routing. If access
               is denied, returns DEFAULT_MODEL ("haiku") as a safe fallback.

    Rule-based only (no LLM calls). Designed to run in < 5ms.

    Rules:
        haiku  — simple Q&A (<50 words, no code, yes/no, status, formatting)
        sonnet — standard coding, analysis, summaries, code review (default)
        opus   — architecture, multi-file refactoring, complex debugging,
                 creative writing, novel problems
    """
    # Trust gate — if trust is wired, verify routing capability is allowed
    if trust is not None:
        try:
            access = trust.check_access("routing")
            if not access.allowed:
                log.warning(
                    "model_router: trust gate denied routing access (tier=%s) — "
                    "falling back to %s",
                    getattr(access, "tier", "unknown"),
                    DEFAULT_MODEL,
                )
                return DEFAULT_MODEL
        except Exception as _trust_err:
            log.debug("model_router: trust.check_access error (ignored): %s", _trust_err)

    # Strip override prefix first (classify works on cleaned text)
    cleaned, override = strip_model_override(message)
    if override:
        return override

    text = cleaned.strip()
    if not text:
        return "haiku"

    words = text.split()
    word_count = len(words)
    has_code_block = bool(_CODE_BLOCK_RE.search(text))
    has_multi_step = bool(_MULTI_STEP_RE.search(text))

    # --- Opus checks (most specific first) ---
    opus_score = sum(1 for p in _OPUS_PATTERNS if p.search(text))
    if opus_score >= 2:
        return "opus"
    # Long message with code blocks + multi-step → opus
    if has_code_block and has_multi_step and word_count > 100:
        return "opus"
    # Single strong opus signal with non-trivial message (> 10 words)
    if opus_score >= 1 and word_count > 10:
        return "opus"

    # --- Haiku checks ---
    if word_count < 50 and not has_code_block:
        for pattern in _HAIKU_PATTERNS:
            if pattern.search(text):
                # Engineering department overrides haiku for non-trivial messages
                dept = detect_department(text)
                if dept == "engineering" and word_count >= 5:
                    break  # Fall through to sonnet
                return "haiku"
        # Very short, no complex indicators → haiku
        if word_count < 10 and opus_score == 0:
            return "haiku"

    # --- Department hint — sonnet/haiku boundary ---
    dept = detect_department(text)
    if dept == "data" and word_count < 10 and not has_code_block and opus_score == 0:
        return "haiku"

    # --- Sonnet (default) ---
    return "sonnet"


def strip_model_override(message: str, metrics: object | None = None) -> tuple[str, str | None]:
    """Extract and remove model override prefix from a message.

    Supported prefixes: ``@opus:``, ``@sonnet:``, ``@haiku:``

    Returns:
        Tuple of (cleaned_message, override_tier_or_None).
        If no override prefix is found, returns (original_message, None).
    Increments the ``model_router_overrides`` counter when an override is found (#22).
    """
    m = _OVERRIDE_RE.match(message)
    if m:
        tier = m.group(1).lower()
        cleaned = message[m.end():]
        # Increment override counter when an explicit model override is detected (#22)
        if metrics is not None:
            try:
                from .metrics import MODEL_ROUTER_OVERRIDES
                metrics.increment(MODEL_ROUTER_OVERRIDES)
            except Exception:
                pass
        return cleaned, tier
    return message, None


def classify_complexity(text: str) -> str:
    """Classify message complexity as simple/medium/complex."""
    text = text.strip()

    # Very short messages are usually simple
    if len(text) < 20:
        for pattern in _SIMPLE_PATTERNS:
            if pattern.search(text):
                return "simple"

    # Check for complex patterns
    complex_score = sum(1 for p in _COMPLEX_PATTERNS if p.search(text))

    if complex_score >= 2:
        return "complex"
    elif complex_score == 1:
        return "medium"

    # Length-based heuristic
    if len(text) > 500:
        return "complex"
    elif len(text) > 100:
        return "medium"

    return "simple"


class ModelRouter:
    """Budget-aware model routing with cost tracking."""

    # Model tiers (for future use when not on subscription)
    TIERS = {
        "simple": {"model": model_defaults.DEFAULT_TIER_SIMPLE, "cost_per_msg": 0.001},
        "medium": {"model": model_defaults.DEFAULT_TIER_MEDIUM, "cost_per_msg": 0.01},
        "complex": {"model": model_defaults.DEFAULT_TIER_COMPLEX, "cost_per_msg": 0.05},
    }

    def __init__(self, daily_budget: float = 0.0) -> None:
        """Initialize router.

        Args:
            daily_budget: Daily budget in USD. 0 = unlimited.
        """
        self._daily_budget = daily_budget
        self._cost_log: list[tuple[float, float]] = []  # (timestamp, cost)

    def route(self, message: str) -> RoutingDecision:
        """Route a message to the appropriate model tier."""
        tier = classify_complexity(message)
        model_info = self.TIERS[tier]

        # Calculate 24h rolling cost
        rolling_cost = self._get_rolling_cost_24h()
        remaining = self._daily_budget - rolling_cost if self._daily_budget > 0 else float("inf")

        downgraded = False
        original_tier = tier

        # Auto-downgrade if over budget
        if self._daily_budget > 0 and remaining < model_info["cost_per_msg"]:
            if tier == "complex":
                tier = "medium"
                model_info = self.TIERS[tier]
                downgraded = True
            if remaining < model_info["cost_per_msg"]:
                tier = "simple"
                model_info = self.TIERS[tier]
                downgraded = True

        reason = f"Classified as {original_tier}"
        if downgraded:
            reason += f" → downgraded to {tier} (budget: ${remaining:.2f} remaining)"

        decision = RoutingDecision(
            tier=tier,
            model=model_info["model"],
            reason=reason,
            budget_remaining=remaining if self._daily_budget > 0 else 0.0,
            downgraded=downgraded,
        )

        log.info("Routing: %s → %s (%s)", message[:50], tier, reason)
        return decision

    def log_cost(self, cost_usd: float) -> None:
        """Log a cost entry for budget tracking."""
        self._cost_log.append((time.time(), cost_usd))

    def _get_rolling_cost_24h(self) -> float:
        """Get total cost in the last 24 hours."""
        cutoff = time.time() - 86400
        # Prune old entries
        self._cost_log = [(t, c) for t, c in self._cost_log if t > cutoff]
        return sum(c for _, c in self._cost_log)

    def get_daily_spend(self) -> float:
        """Get total spend in the last 24 hours."""
        return self._get_rolling_cost_24h()

    def get_budget_status(self) -> dict:
        """Get current budget status."""
        spent = self._get_rolling_cost_24h()
        return {
            "daily_budget": self._daily_budget,
            "spent_24h": spent,
            "remaining": self._daily_budget - spent if self._daily_budget > 0 else float("inf"),
            "is_unlimited": self._daily_budget == 0,
        }
