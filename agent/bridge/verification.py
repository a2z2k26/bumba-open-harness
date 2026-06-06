"""
Verification Layer — generator-critic output verification.

Three tiers of rigour:
  DRAFT    — fast schema/type check only
  STANDARD — checks result presence, confidence, non-emptiness
  VERIFIED — cross-checks confidence, scans for contradictions in list results
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional


class VerificationTier(str, Enum):
    DRAFT = "draft"
    STANDARD = "standard"
    VERIFIED = "verified"


@dataclass
class VerificationResult:
    passed: bool
    tier: VerificationTier
    score: float
    issues: List[str]
    verified_at: str


class VerificationLayer:
    """
    Verifies agent output at configurable rigour levels.

    Usage:
        layer = VerificationLayer()
        result = layer.verify(output_dict, tier=VerificationTier.STANDARD)
    """

    def verify(
        self,
        output: Dict,
        tier: VerificationTier = VerificationTier.STANDARD,
        schema: Optional[Dict] = None,
    ) -> VerificationResult:
        """Dispatch to the appropriate verification method."""
        if tier == VerificationTier.DRAFT:
            return self._draft_verify(output, schema)
        elif tier == VerificationTier.STANDARD:
            return self._standard_verify(output)
        else:
            return self._verified_verify(output)

    # ------------------------------------------------------------------
    # Tier implementations
    # ------------------------------------------------------------------

    def _draft_verify(
        self, output: Dict, schema: Optional[Dict]
    ) -> VerificationResult:
        """
        Quick schema / type check.

        If a JSON Schema dict is provided, validate with jsonschema when
        available, falling back to a basic isinstance check.
        """
        issues: List[str] = []
        verified_at = datetime.now(timezone.utc).isoformat()

        if schema is not None:
            try:
                import jsonschema  # type: ignore
                try:
                    jsonschema.validate(output, schema)
                except jsonschema.ValidationError as exc:
                    issues.append(f"Schema validation error: {exc.message}")
            except ImportError:
                # Basic type check fallback
                if not isinstance(output, dict):
                    issues.append(f"Output is not a dict (got {type(output).__name__})")

        passed = len(issues) == 0
        return VerificationResult(
            passed=passed,
            tier=VerificationTier.DRAFT,
            score=1.0 if passed else 0.0,
            issues=issues,
            verified_at=verified_at,
        )

    def _standard_verify(self, output: Dict) -> VerificationResult:
        """
        Standard verification:
          - output must contain 'result' key
          - confidence >= 0.5
          - result must be non-empty
        Score range: 0.7–0.9
        """
        issues: List[str] = []
        verified_at = datetime.now(timezone.utc).isoformat()

        if "result" not in output:
            issues.append("Missing required key 'result'")
        else:
            result_val = output["result"]
            if result_val is None or (isinstance(result_val, (str, list, dict)) and not result_val):
                issues.append("'result' value is empty")

        confidence = output.get("confidence")
        if confidence is None:
            issues.append("Missing 'confidence' field")
        elif float(confidence) < 0.5:
            issues.append(f"Confidence {confidence} is below threshold 0.5")

        passed = len(issues) == 0
        # Score: 0.9 when all good, 0.7 when minor issues, 0.0 when failed
        if passed:
            score = 0.9
        elif len(issues) == 1:
            score = 0.7
        else:
            score = 0.0

        return VerificationResult(
            passed=passed,
            tier=VerificationTier.STANDARD,
            score=score,
            issues=issues,
            verified_at=verified_at,
        )

    def _verified_verify(self, output: Dict) -> VerificationResult:
        """
        Strict verification:
          - output must contain 'result' key
          - confidence >= 0.8
          - for list results, checks for duplicate/contradicting entries
        Score range: 0.8–1.0
        """
        issues: List[str] = []
        verified_at = datetime.now(timezone.utc).isoformat()

        if "result" not in output:
            issues.append("Missing required key 'result'")
        else:
            result_val = output["result"]
            if result_val is None or (isinstance(result_val, (str, list, dict)) and not result_val):
                issues.append("'result' value is empty")

            # Contradiction check for list results
            if isinstance(result_val, list):
                seen: set = set()
                for item in result_val:
                    item_str = str(item)
                    if item_str in seen:
                        issues.append(f"Duplicate/contradicting item in result list: {item_str!r}")
                    seen.add(item_str)

        confidence = output.get("confidence")
        if confidence is None:
            issues.append("Missing 'confidence' field")
        elif float(confidence) < 0.8:
            issues.append(f"Confidence {confidence} is below verified threshold 0.8")

        passed = len(issues) == 0
        if passed:
            score = 1.0
        elif len(issues) == 1:
            score = 0.8
        else:
            score = 0.0

        return VerificationResult(
            passed=passed,
            tier=VerificationTier.VERIFIED,
            score=score,
            issues=issues,
            verified_at=verified_at,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_tier_from_context(self, context: str) -> VerificationTier:
        """Infer VerificationTier from a context string."""
        ctx = context.lower()
        if "draft" in ctx:
            return VerificationTier.DRAFT
        elif "verified" in ctx:
            return VerificationTier.VERIFIED
        return VerificationTier.STANDARD
