"""Quality gate checker implementations for QualityChain.

Each checker is a callable matching:
    (project: str, files: list[str]) -> GateCheckResult

Checkers are imported and registered by dispatcher.py at construction.
"""
from __future__ import annotations

from bridge.quality_checkers.lint import LintChecker
from bridge.quality_checkers.typecheck import TypecheckChecker
from bridge.quality_checkers.test import TestChecker
from bridge.quality_checkers.security import SecurityChecker
from bridge.quality_checkers.code_review import CodeReviewChecker
from bridge.quality_checkers.human_approval import HumanApprovalChecker

__all__ = [
    "LintChecker",
    "TypecheckChecker",
    "TestChecker",
    "SecurityChecker",
    "CodeReviewChecker",
    "HumanApprovalChecker",
]
