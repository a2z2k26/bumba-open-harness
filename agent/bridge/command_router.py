"""
Bumba Command Router - intent detection and command routing.

Routes incoming commands to appropriate handlers based on intent detection,
pattern matching, complexity scoring, and confidence scoring.

Intent categories: build, analyze, fix, optimize, test, deploy, document
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Tuple
import re
from bridge.dispatch_metrics import increment_module_counter


class Intent(str, Enum):
    """Recognized command intents."""
    BUILD = "build"
    ANALYZE = "analyze"
    FIX = "fix"
    OPTIMIZE = "optimize"
    TEST = "test"
    DEPLOY = "deploy"
    DOCUMENT = "document"
    # Sprint 04.01 — Board (Zone 4 department) intent. Narrow scope: only
    # explicit /board prefix or board-synthesis verbs. Pairs with the
    # _INTENT_SKILL_MAP entry "board_query" -> "board-query" in app.py,
    # which routes through EnvironmentSelector to Environment.DEPARTMENT.
    BOARD_QUERY = "board_query"
    # Sprint 04.02 — broaden classifier to the 4 remaining Zone 4
    # departments (QA / Ops / Strategy / Design). Same shape as 04.01:
    # narrow regex patterns + _INTENT_SKILL_MAP entry whose skill string
    # passes _SKILL_CLASS_RULES into Environment.DEPARTMENT. Bare single
    # keywords (``qa``, ``ops``, ``design``) are intentionally rejected —
    # patterns require either ``^/<dept>\b`` or an explicit verb-noun
    # phrase to avoid false-positive routing of casual Discord chatter.
    QA_REVIEW = "qa_review"
    OPS_DIAGNOSE = "ops_diagnose"
    STRATEGY_ANALYZE = "strategy_analyze"
    DESIGN_REVIEW = "design_review"
    UNKNOWN = "unknown"


@dataclass
class CommandMatch:
    """Result of command matching and analysis."""
    intent: Intent
    confidence: float  # 0.0 to 1.0
    complexity: int    # 1 (trivial) to 5 (extreme)
    matchedPatterns: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class CommandRouter:
    """
    Routes incoming commands to appropriate handlers based on intent.

    Implements pattern matching, complexity scoring, and confidence scoring.

    Note (#1537): callers should go through ``bridge.intent_classifier.classify``
    rather than instantiating ``CommandRouter`` directly. ``intent_classifier``
    is the canonical surface for intent classification across the routing
    stack; this class is its implementation. Direct instantiation invites
    duplicate cached routers and bypasses the consolidation invariant.
    """

    # Intent patterns — keywords associated with each intent
    INTENT_PATTERNS = {
        # Sprint 04.01 — narrow Board department patterns. Three signals:
        #   1. ``^/board\b`` — explicit slash-command prefix (highest signal)
        #   2. ``\bdebate\b`` — board-synthesis verb (multi-perspective)
        #   3. ``\bdeliberate\b`` — board-synthesis verb (consensus)
        # Bare ``\bboard\b`` is intentionally NOT matched — too noisy
        # ("the board game", "boarding pass"). Slash-prefix or one of the
        # synthesis verbs is required to land on BOARD_QUERY.
        Intent.BOARD_QUERY: [
            r"^/board\b",
            r"\bdebate\b",
            r"\bdeliberate\b",
        ],
        # Sprint 04.02 — narrow QA department patterns. Two-word phrases
        # only (plus slash-prefix). Bare ``\bqa\b`` and ``\breview\b``
        # both intentionally rejected: ``qa`` is a noun in casual chatter
        # ("qa is a great role"), and bare ``\breview\b`` already belongs
        # to ANALYZE intent (``"review the performance"`` should stay
        # ANALYZE, not become QA_REVIEW). The two-word phrase
        # ``\breview\s+code\b`` also matches ANALYZE's ``\breview\b`` —
        # tie is broken in favour of QA_REVIEW because Python ``max``
        # returns the first-encountered key, and dict iteration order is
        # insertion order: QA_REVIEW is declared first in INTENT_PATTERNS.
        Intent.QA_REVIEW: [
            r"^/qa\b",
            r"\breview\s+code\b",
            r"\bsecurity\s+check\b",
        ],
        # Sprint 04.02 — narrow Ops department patterns. ``\bdiagnose\b``
        # and ``\bdebug\b`` overlap with ANALYZE / FIX respectively, but
        # the first-defined-wins tie-break (insertion order) routes these
        # to OPS_DIAGNOSE — this is the intended steering: a diagnostic
        # ask SHOULD reach the Ops department, not be silently
        # reclassified to a generic analyze/fix path.
        Intent.OPS_DIAGNOSE: [
            r"^/ops\b",
            r"\bdiagnose\b",
            r"\bincident\b",
            r"\bdebug\b",
        ],
        # Sprint 04.02 — narrow Strategy department patterns. Bare
        # ``\bstrategy\b`` is too broad ("strategy meeting") and is
        # explicitly excluded; only the slash-prefix or one of three
        # high-signal positioning/competitor verbs lands here.
        Intent.STRATEGY_ANALYZE: [
            r"^/strategy\b",
            r"\bcompetitor\b",
            r"\bpositioning\b",
            r"\bmarket\s+analysis\b",
        ],
        # Sprint 04.02 — narrow Design department patterns. Bare
        # ``\bdesign\b`` rejected — too many false-positives ("design a
        # function", "design pattern"). Two-word review phrases
        # (``design review``, ``ux review``, ``visual review``) plus the
        # slash-prefix are required.
        Intent.DESIGN_REVIEW: [
            r"^/design\b",
            r"\bdesign\s+review\b",
            r"\bux\s+review\b",
            r"\bvisual\s+review\b",
        ],
        Intent.BUILD: [
            r"\bbuild\b",
            r"\bcompile\b",
            r"\bcreate\b",
            r"\bgenerate\b",
            r"\bconstruct\b",
            r"\bscaffold\b",
        ],
        Intent.ANALYZE: [
            r"\banalyze\b",
            r"\banalyse\b",
            r"\breview\b",
            r"\binspect\b",
            r"\bexamine\b",
            r"\bdiagnose\b",
            r"\bassess\b",
        ],
        Intent.FIX: [
            r"\bfix\b",
            r"\brepair\b",
            r"\bpatch\b",
            r"\bresolve\b",
            r"\bcorrect\b",
            r"\bdebugging?\b",
            r"\btroubleshoot\b",
        ],
        Intent.OPTIMIZE: [
            r"\boptimize\b",
            r"\boptimise\b",
            r"\brefactor\b",
            r"\bimprove\b",
            r"\benhance\b",
            r"\bspeedup?\b",
            r"\btune\b",
        ],
        Intent.TEST: [
            r"\btest\b",
            r"\bvalidate\b",
            r"\bverify\b",
            r"\bcheck\b",
            r"\bassert\b",
            r"\bunit test\b",
            r"\bintegration test\b",
        ],
        Intent.DEPLOY: [
            r"\bdeploy\b",
            r"\brelease\b",
            r"\blaunch\b",
            r"\bpublish\b",
            r"\bpush\b",
            r"\bupdate\b",
            r"\broll out\b",
        ],
        Intent.DOCUMENT: [
            r"\bdocument\b",
            r"\bwrite docs?\b",
            r"\breference\b",
            r"\bcomment\b",
            r"\bdescribe\b",
            r"\bexplain\b",
            r"\bguide\b",
        ],
    }

    # Complexity indicators
    COMPLEXITY_KEYWORDS = {
        # Level 1 (trivial)
        1: ["list", "show", "view", "read", "print"],
        # Level 2 (simple)
        2: ["add", "remove", "change", "update", "edit"],
        # Level 3 (moderate)
        3: ["refactor", "reorganize", "restructure", "rewrite"],
        # Level 4 (complex)
        4: ["architecture", "infrastructure", "system", "framework"],
        # Level 5 (extreme)
        5: ["machine learning", "distributed", "sharding", "consensus"],
    }

    def __init__(self):
        """Initialize the command router."""
        self.compiled_patterns = self._compile_patterns()

    def _compile_patterns(self) -> Dict[Intent, List]:
        """Pre-compile regex patterns for performance."""
        compiled = {}
        for intent, patterns in self.INTENT_PATTERNS.items():
            compiled[intent] = [re.compile(p, re.IGNORECASE) for p in patterns]
        return compiled

    def route(self, command: str) -> CommandMatch:
        increment_module_counter("command_router.route", tier=1)
        """
        Route a command and analyze its intent.

        Args:
            command: The command string to analyze

        Returns:
            CommandMatch with detected intent, confidence, and complexity
        """
        if not command or not command.strip():
            return CommandMatch(
                intent=Intent.UNKNOWN,
                confidence=0.0,
                complexity=1,
            )

        command_lower = command.lower()
        matches_by_intent = {}

        # Score each intent based on pattern matches
        for intent, regex_patterns in self.compiled_patterns.items():
            matched = []
            for pattern in regex_patterns:
                if pattern.search(command_lower):
                    matched.append(pattern.pattern)
            if matched:
                matches_by_intent[intent] = matched

        # Determine primary intent
        if not matches_by_intent:
            return CommandMatch(
                intent=Intent.UNKNOWN,
                confidence=0.0,
                complexity=self._score_complexity(command),
            )

        # Primary intent is the one with the most matches
        primary_intent = max(matches_by_intent, key=lambda i: len(matches_by_intent[i]))
        matched_patterns = matches_by_intent[primary_intent]

        # Calculate confidence based on number of matching patterns
        # More pattern matches = higher confidence
        pattern_count = len(matched_patterns)
        confidence = min(0.95, 0.6 + (pattern_count * 0.15))

        # Boost confidence if intent is very specific
        if primary_intent != Intent.UNKNOWN and pattern_count >= 2:
            confidence = min(1.0, confidence + 0.1)

        return CommandMatch(
            intent=primary_intent,
            confidence=confidence,
            complexity=self._score_complexity(command),
            matchedPatterns=matched_patterns,
        )

    def _score_complexity(self, command: str) -> int:
        """
        Score command complexity from 1 (trivial) to 5 (extreme).

        Args:
            command: The command string

        Returns:
            Complexity score (1-5)
        """
        command_lower = command.lower()
        max_complexity = 1

        for complexity_level, keywords in self.COMPLEXITY_KEYWORDS.items():
            for keyword in keywords:
                if keyword in command_lower:
                    max_complexity = max(max_complexity, complexity_level)

        return max_complexity

    def get_confidence_level(self, confidence: float) -> str:
        """
        Categorize confidence score.

        Args:
            confidence: Confidence score (0.0-1.0)

        Returns:
            Confidence level: low, medium, high
        """
        if confidence >= 0.8:
            return "high"
        elif confidence >= 0.5:
            return "medium"
        else:
            return "low"

    def get_complexity_label(self, complexity: int) -> str:
        """
        Get human-readable complexity label.

        Args:
            complexity: Complexity score (1-5)

        Returns:
            Complexity label: trivial, simple, moderate, complex, extreme
        """
        labels = {
            1: "trivial",
            2: "simple",
            3: "moderate",
            4: "complex",
            5: "extreme",
        }
        return labels.get(complexity, "unknown")

    def batch_route(self, commands: List[str]) -> List[CommandMatch]:
        """
        Route multiple commands.

        Args:
            commands: List of command strings

        Returns:
            List of CommandMatch results
        """
        return [self.route(cmd) for cmd in commands]

    def filter_by_intent(
        self, commands: List[str], intent: Intent, min_confidence: float = 0.5
    ) -> List[Tuple[str, CommandMatch]]:
        """
        Filter commands by intent.

        Args:
            commands: List of command strings
            intent: Target intent to filter for
            min_confidence: Minimum confidence threshold

        Returns:
            List of (command, match) tuples matching the intent
        """
        results = []
        for cmd in commands:
            match = self.route(cmd)
            if match.intent == intent and match.confidence >= min_confidence:
                results.append((cmd, match))
        return results

    def filter_by_complexity(
        self, commands: List[str], min_complexity: int = 1, max_complexity: int = 5
    ) -> List[Tuple[str, CommandMatch]]:
        """
        Filter commands by complexity range.

        Args:
            commands: List of command strings
            min_complexity: Minimum complexity (1-5)
            max_complexity: Maximum complexity (1-5)

        Returns:
            List of (command, match) tuples within complexity range
        """
        results = []
        for cmd in commands:
            match = self.route(cmd)
            if min_complexity <= match.complexity <= max_complexity:
                results.append((cmd, match))
        return results

    def explain_routing(self, command: str) -> Dict[str, Any]:
        """
        Provide detailed explanation of routing decision.

        Args:
            command: The command string

        Returns:
            Dictionary with routing explanation
        """
        match = self.route(command)
        return {
            "command": command,
            "intent": match.intent.value,
            "confidence": {
                "score": match.confidence,
                "level": self.get_confidence_level(match.confidence),
            },
            "complexity": {
                "score": match.complexity,
                "label": self.get_complexity_label(match.complexity),
            },
            "matchedPatterns": match.matchedPatterns,
            "metadata": match.metadata,
        }
