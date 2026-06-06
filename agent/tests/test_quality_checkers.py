"""Tests for quality gate checker implementations (#568, #569)."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch


from bridge.quality_chain import GateLevel
from bridge.quality_checkers.lint import LintChecker
from bridge.quality_checkers.typecheck import TypecheckChecker
from bridge.quality_checkers.test import TestChecker
from bridge.quality_checkers.security import SecurityChecker
from bridge.quality_checkers.code_review import CodeReviewChecker
from bridge.quality_checkers.human_approval import HumanApprovalChecker


# ---------------------------------------------------------------------------
# LintChecker
# ---------------------------------------------------------------------------

def test_lint_no_python_files():
    checker = LintChecker()
    result = checker("myproject", ["README.md", "config.yaml"])
    assert result.passed is True
    assert result.gate_level == GateLevel.LINT


def test_lint_no_existing_files():
    checker = LintChecker()
    result = checker("myproject", ["/nonexistent/path.py"])
    assert result.passed is True


def test_lint_ruff_not_installed():
    checker = LintChecker()
    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = checker("myproject", [__file__])
    assert result.passed is True
    assert "not installed" in result.reason


def test_lint_ruff_passes():
    checker = LintChecker()
    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch("subprocess.run", return_value=mock_result):
        result = checker("myproject", [__file__])
    assert result.passed is True


def test_lint_ruff_fails():
    checker = LintChecker()
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = "path.py:1:1 E501 line too long\npath.py:2:1 F401 unused import"
    with patch("subprocess.run", return_value=mock_result):
        result = checker("myproject", [__file__])
    assert result.passed is False
    assert "2 lint issue" in result.reason
    assert result.gate_level == GateLevel.LINT


def test_lint_timeout():
    checker = LintChecker()
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ruff", 60)):
        result = checker("myproject", [__file__])
    assert result.passed is False
    assert "timed out" in result.reason


# ---------------------------------------------------------------------------
# TypecheckChecker
# ---------------------------------------------------------------------------

def test_typecheck_no_python_files():
    checker = TypecheckChecker()
    result = checker("myproject", [])
    assert result.passed is True
    assert result.gate_level == GateLevel.TYPECHECK


def test_typecheck_mypy_not_installed():
    checker = TypecheckChecker()
    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = checker("myproject", [__file__])
    assert result.passed is True
    assert "not installed" in result.reason


def test_typecheck_passes():
    checker = TypecheckChecker()
    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch("subprocess.run", return_value=mock_result):
        result = checker("myproject", [__file__])
    assert result.passed is True


def test_typecheck_fails():
    checker = TypecheckChecker()
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = (
        "path.py:1: error: Incompatible types\n"
        "path.py:2: error: Cannot assign to method\n"
        "Found 2 errors in 1 file"
    )
    with patch("subprocess.run", return_value=mock_result):
        result = checker("myproject", [__file__])
    assert result.passed is False
    assert "2 type error" in result.reason


# ---------------------------------------------------------------------------
# TestChecker
# ---------------------------------------------------------------------------

def test_test_checker_pytest_not_installed():
    checker = TestChecker()
    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = checker("myproject", [])
    assert result.passed is True
    assert "not installed" in result.reason


def test_test_checker_passes():
    checker = TestChecker()
    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch("subprocess.run", return_value=mock_result):
        result = checker("myproject", [])
    assert result.passed is True


def test_test_checker_fails():
    checker = TestChecker()
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = "FAILED tests/test_foo.py::test_bar - assert False"
    mock_result.stderr = ""
    with patch("subprocess.run", return_value=mock_result):
        result = checker("myproject", [])
    assert result.passed is False
    assert "failed" in result.reason.lower()


def test_test_checker_timeout():
    checker = TestChecker()
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("pytest", 600)):
        result = checker("myproject", [])
    assert result.passed is False
    assert "timed out" in result.reason


# ---------------------------------------------------------------------------
# SecurityChecker
# ---------------------------------------------------------------------------

def test_security_no_python_files():
    checker = SecurityChecker()
    result = checker("myproject", [])
    assert result.passed is True


def test_security_bandit_not_installed():
    checker = SecurityChecker()
    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = checker("myproject", [__file__])
    assert result.passed is True
    assert "not installed" in result.reason


def test_security_passes():
    checker = SecurityChecker()
    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch("subprocess.run", return_value=mock_result):
        result = checker("myproject", [__file__])
    assert result.passed is True


def test_security_high_issue_fails():
    import json
    checker = SecurityChecker(fail_severity="HIGH")
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = json.dumps({
        "results": [
            {
                "filename": "path.py",
                "line_number": 10,
                "issue_severity": "HIGH",
                "issue_text": "Hardcoded password",
            }
        ]
    })
    with patch("subprocess.run", return_value=mock_result):
        result = checker("myproject", [__file__])
    assert result.passed is False
    assert "HIGH" in result.reason


def test_security_low_issue_passes_with_high_threshold():
    import json
    checker = SecurityChecker(fail_severity="HIGH")
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = json.dumps({
        "results": [
            {
                "filename": "path.py",
                "line_number": 10,
                "issue_severity": "LOW",
                "issue_text": "Some minor issue",
            }
        ]
    })
    with patch("subprocess.run", return_value=mock_result):
        result = checker("myproject", [__file__])
    assert result.passed is True


# ---------------------------------------------------------------------------
# CodeReviewChecker (#569)
# ---------------------------------------------------------------------------

def test_code_review_returns_requires_human():
    checker = CodeReviewChecker()
    result = checker("myproject", ["a.py", "b.py"])
    assert result.passed is True
    assert result.requires_human is True
    assert result.gate_level == GateLevel.CODE_REVIEW
    assert "review_id=" in result.reason


# ---------------------------------------------------------------------------
# HumanApprovalChecker (#569)
# ---------------------------------------------------------------------------

def test_human_approval_returns_requires_human():
    checker = HumanApprovalChecker()
    result = checker("myproject", [])
    assert result.passed is True
    assert result.requires_human is True
    assert result.gate_level == GateLevel.HUMAN_APPROVAL
    assert "approval_id=" in result.reason


# ---------------------------------------------------------------------------
# QualityChain.run_for_skill integration
# ---------------------------------------------------------------------------

def test_run_for_skill_no_profile():
    from bridge.quality_chain import QualityChain
    chain = QualityChain()
    result = chain.run_for_skill("unknown-skill", "proj", [])
    assert result.passed is True
    assert result.gate_results == []


def test_run_for_skill_with_lint_only():
    from bridge.quality_chain import QualityChain, GateLevel

    lint_checker = MagicMock()
    from bridge.quality_chain import GateCheckResult
    lint_checker.return_value = GateCheckResult(passed=True, gate_level=GateLevel.LINT)

    chain = QualityChain()
    chain.register(GateLevel.LINT, lint_checker)
    chain.register_skill("fix-test", [GateLevel.LINT])

    result = chain.run_for_skill("fix-test", "proj", [])
    assert result.passed is True
    lint_checker.assert_called_once()


def test_run_for_skill_stops_on_requires_human():
    from bridge.quality_chain import QualityChain, GateLevel, GateCheckResult

    lint_checker = MagicMock(return_value=GateCheckResult(passed=True, gate_level=GateLevel.LINT))
    review_checker = MagicMock(return_value=GateCheckResult(
        passed=True,
        gate_level=GateLevel.CODE_REVIEW,
        requires_human=True,
        escalation_reason="needs review",
    ))

    chain = QualityChain()
    chain.register(GateLevel.LINT, lint_checker)
    chain.register(GateLevel.CODE_REVIEW, review_checker)
    chain.register_skill("ship-feature", [GateLevel.LINT, GateLevel.CODE_REVIEW])

    result = chain.run_for_skill("ship-feature", "proj", [])
    assert result.requires_human is True
    assert result.passed is True
