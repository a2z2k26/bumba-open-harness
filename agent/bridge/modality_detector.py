"""
Modality Intent Detector — detect execution modality from command text.

Identifies how a command should be executed:
- SOLO: Single agent, sequential
- ORCHESTRATED: Multiple agents coordinated
- SEQUENTIAL: Multiple steps, strict order
- PARALLEL: Independent parallel execution
- REVIEW: Requires verification/approval
"""

from enum import Enum
from dataclasses import dataclass
from typing import Dict, List
import re


class Modality(str, Enum):
    """Execution modalities."""
    SOLO = "solo"
    ORCHESTRATED = "orchestrated"
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    REVIEW = "review"


@dataclass
class ModalityMatch:
    """Result of modality detection."""
    modality: Modality
    confidence: float  # 0.0 to 1.0
    matched_keywords: List[str]


class ModalityDetector:
    """
    Detects execution modality from command text.

    Modalities:
    - SOLO: Single-agent execution
    - ORCHESTRATED: Coordinated multi-agent execution
    - SEQUENTIAL: Sequential multi-step execution
    - PARALLEL: Parallel independent execution
    - REVIEW: Requires human verification
    """

    MODALITY_PATTERNS = {
        Modality.SOLO: [
            r"\bsingle\b",
            r"\balone\b",
            r"\bme\b",
            r"\binvoke\b",
            r"\brun\b",
            r"\bexecute\b",
        ],
        Modality.ORCHESTRATED: [
            r"\bcoordinate\b",
            r"\borchestrate\b",
            r"\bteam\b",
            r"\bcollab",
            r"\btogether\b",
            r"\bsynchronize\b",
        ],
        Modality.SEQUENTIAL: [
            r"\bstep\b",
            r"\bsequence\b",
            r"\blinear\b",
            r"\bstrictly?\s+order",
            r"\bone after",
            r"\bthen\b",
        ],
        Modality.PARALLEL: [
            r"\bparallel\b",
            r"\bconcurrent\b",
            r"\bsimultaneous\b",
            r"\bindependent\b",
            r"\ball at once\b",
            r"\bsimultaneously\b",
        ],
        Modality.REVIEW: [
            r"\breview\b",
            r"\bapprove\b",
            r"\bverify\b",
            r"\bcheck\b",
            r"\bvalidate\b",
            r"\bconfirm\b",
        ],
    }

    def __init__(self):
        """Initialize the modality detector."""
        self.compiled_patterns = self._compile_patterns()

    def _compile_patterns(self) -> Dict[Modality, List]:
        """Pre-compile regex patterns."""
        compiled = {}
        for modality, patterns in self.MODALITY_PATTERNS.items():
            compiled[modality] = [re.compile(p, re.IGNORECASE) for p in patterns]
        return compiled

    def detect(self, command: str) -> ModalityMatch:
        """
        Detect execution modality from command text.

        Args:
            command: Command string to analyze

        Returns:
            ModalityMatch with detected modality and confidence
        """
        if not command or not command.strip():
            return ModalityMatch(
                modality=Modality.SOLO,
                confidence=0.0,
                matched_keywords=[],
            )

        command_lower = command.lower()
        matches_by_modality = {}

        # Score each modality
        for modality, regex_patterns in self.compiled_patterns.items():
            matched = []
            for pattern in regex_patterns:
                if pattern.search(command_lower):
                    matched.append(pattern.pattern)
            if matched:
                matches_by_modality[modality] = matched

        # Default to SOLO if no matches
        if not matches_by_modality:
            return ModalityMatch(
                modality=Modality.SOLO,
                confidence=0.5,  # Default confidence for SOLO
                matched_keywords=[],
            )

        # Primary modality is the one with most matches
        # Break ties by preferring non-SOLO modalities
        primary = max(
            matches_by_modality,
            key=lambda m: (
                len(matches_by_modality[m]),
                0 if m != Modality.SOLO else -1
            )
        )
        matched_keywords = matches_by_modality[primary]

        # Calculate confidence
        match_count = len(matched_keywords)
        confidence = min(0.95, 0.6 + (match_count * 0.15))

        return ModalityMatch(
            modality=primary,
            confidence=confidence,
            matched_keywords=matched_keywords,
        )

    def get_confidence_level(self, confidence: float) -> str:
        """
        Categorize confidence.

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

    def detect_multi(self, commands: List[str]) -> List[ModalityMatch]:
        """
        Detect modality for multiple commands.

        Args:
            commands: List of command strings

        Returns:
            List of ModalityMatch results
        """
        return [self.detect(cmd) for cmd in commands]

    def is_multi_agent(self, modality: Modality) -> bool:
        """
        Check if modality involves multiple agents.

        Args:
            modality: Modality to check

        Returns:
            True if modality involves multi-agent execution
        """
        return modality in (Modality.ORCHESTRATED, Modality.SEQUENTIAL, Modality.PARALLEL)

    def requires_coordination(self, modality: Modality) -> bool:
        """
        Check if modality requires coordination.

        Args:
            modality: Modality to check

        Returns:
            True if modality requires coordination
        """
        return modality in (Modality.ORCHESTRATED, Modality.SEQUENTIAL, Modality.PARALLEL)

    def requires_review(self, modality: Modality) -> bool:
        """
        Check if modality requires review/approval.

        Args:
            modality: Modality to check

        Returns:
            True if modality involves review
        """
        return modality == Modality.REVIEW

    def explain(self, command: str) -> Dict:
        """
        Provide detailed explanation of modality detection.

        Args:
            command: Command to analyze

        Returns:
            Dictionary with explanation details
        """
        match = self.detect(command)
        return {
            "command": command,
            "modality": match.modality.value,
            "confidence": {
                "score": match.confidence,
                "level": self.get_confidence_level(match.confidence),
            },
            "matched_keywords": match.matched_keywords,
            "is_multi_agent": self.is_multi_agent(match.modality),
            "requires_coordination": self.requires_coordination(match.modality),
            "requires_review": self.requires_review(match.modality),
        }
