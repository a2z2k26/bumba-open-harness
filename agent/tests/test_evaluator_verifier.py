"""Tests for ResponseEvaluator + SelfVerifier integration (#21)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.response_evaluator import ResponseEvaluator
from bridge.self_verifier import VerificationResult


@pytest.fixture
def evaluator(tmp_path):
    return ResponseEvaluator(data_dir=str(tmp_path), enabled=True)


def _mock_runner_passing():
    """Return a mock runner whose invoke returns a passing JSON eval."""
    mock_result = MagicMock()
    mock_result.is_error = False
    mock_result.response_text = json.dumps({
        "completeness": 8, "correctness": 8, "actionability": 8,
        "safety": 8, "overall": 8.0, "issues": [], "verdict": "pass"
    })
    runner = AsyncMock()
    runner.invoke = AsyncMock(return_value=mock_result)
    return runner


# Long enough to bypass the short-response skip
_LONG = "x" * 200


class TestEvaluatorVerifierIntegration:
    """#21: Verifier wired into evaluator — verification failures appear in issues."""

    @pytest.mark.asyncio
    async def test_verifier_failures_appended_to_issues(self, evaluator):
        evaluator.set_runner(_mock_runner_passing())

        mock_verifier = AsyncMock()
        mock_verifier.verify_response = AsyncMock(
            return_value=VerificationResult(
                passed=False,
                errors=["HTTP 500 from http://localhost:3000/"],
                urls_checked=1,
            )
        )
        evaluator.set_verifier(mock_verifier)

        result = await evaluator.evaluate(
            "Build the dashboard page",
            "App at http://localhost:3000/" + _LONG,
        )
        assert "HTTP 500" in str(result.issues)
        mock_verifier.verify_response.assert_called_once()

    @pytest.mark.asyncio
    async def test_verifier_pass_no_extra_issues(self, evaluator):
        evaluator.set_runner(_mock_runner_passing())

        mock_verifier = AsyncMock()
        mock_verifier.verify_response = AsyncMock(
            return_value=VerificationResult(passed=True, errors=[], urls_checked=1)
        )
        evaluator.set_verifier(mock_verifier)

        result = await evaluator.evaluate(
            "Build the dashboard", "Dashboard built" + _LONG,
        )
        assert result.issues == []
        assert result.verdict == "pass"

    @pytest.mark.asyncio
    async def test_verifier_returns_none_no_urls(self, evaluator):
        evaluator.set_runner(_mock_runner_passing())

        mock_verifier = AsyncMock()
        mock_verifier.verify_response = AsyncMock(return_value=None)
        evaluator.set_verifier(mock_verifier)

        result = await evaluator.evaluate(
            "Explain the code", "Here is the explanation" + _LONG,
        )
        assert result.issues == []

    @pytest.mark.asyncio
    async def test_verifier_timeout_nonblocking(self, evaluator):
        import asyncio
        evaluator.set_runner(_mock_runner_passing())

        async def slow_verify(text):
            await asyncio.sleep(100)

        mock_verifier = AsyncMock()
        mock_verifier.verify_response = slow_verify
        evaluator.set_verifier(mock_verifier)

        result = await evaluator.evaluate(
            "Build the app", "App at http://localhost:3000/" + _LONG,
        )
        assert result.verdict == "pass"

    @pytest.mark.asyncio
    async def test_verifier_exception_nonblocking(self, evaluator):
        evaluator.set_runner(_mock_runner_passing())

        mock_verifier = AsyncMock()
        mock_verifier.verify_response = AsyncMock(side_effect=RuntimeError("boom"))
        evaluator.set_verifier(mock_verifier)

        result = await evaluator.evaluate(
            "Fix the bug", "Bug fixed in auth module" + _LONG,
        )
        assert result.verdict == "pass"
        assert result.issues == []

    @pytest.mark.asyncio
    async def test_no_verifier_identical_behavior(self, evaluator):
        """Without verifier set, behavior is identical to before #21."""
        mock_result = MagicMock()
        mock_result.is_error = False
        mock_result.response_text = json.dumps({
            "completeness": 6, "correctness": 5, "actionability": 4,
            "safety": 8, "overall": 5.2, "issues": ["incomplete"], "verdict": "flag"
        })
        runner = AsyncMock()
        runner.invoke = AsyncMock(return_value=mock_result)
        evaluator.set_runner(runner)

        result = await evaluator.evaluate(
            "Implement the full authentication system with SSO support",
            "Here is partial auth" + _LONG,
        )
        assert result.verdict == "flag"
        assert result.issues == ["incomplete"]


class TestVoiceConsistencyAxis:
    """D7.7 #1419 — fifth ``voice_consistency`` axis is operator-rateable
    trend signal, NOT a blocking gate.

    Contract:
    - Parsed from evaluator JSON when present (0-10 float)
    - Defaults to 0.0 when absent (back-compat with pre-D7.7 evaluator output)
    - Does NOT affect ``overall`` (model still computes the weighted average
      from the four blocking axes per the prompt's stated weights)
    - Does NOT change ``verdict`` thresholds
    """

    @pytest.mark.asyncio
    async def test_voice_consistency_parses_from_json(self, evaluator):
        mock_result = MagicMock()
        mock_result.is_error = False
        mock_result.response_text = json.dumps({
            "completeness": 8, "correctness": 8, "actionability": 8,
            "safety": 8, "voice_consistency": 7,
            "overall": 8.0, "issues": [], "verdict": "pass",
        })
        runner = AsyncMock()
        runner.invoke = AsyncMock(return_value=mock_result)
        evaluator.set_runner(runner)

        result = await evaluator.evaluate("Tell me about the codebase", "pong" + _LONG)
        assert result.voice_consistency == 7.0

    @pytest.mark.asyncio
    async def test_voice_consistency_defaults_to_zero_when_absent(self, evaluator):
        """Back-compat: pre-D7.7 evaluator JSON (no voice_consistency key)
        still parses cleanly and the field defaults to 0.0.
        """
        mock_result = MagicMock()
        mock_result.is_error = False
        mock_result.response_text = json.dumps({
            "completeness": 8, "correctness": 8, "actionability": 8,
            "safety": 8, "overall": 8.0, "issues": [], "verdict": "pass",
        })
        runner = AsyncMock()
        runner.invoke = AsyncMock(return_value=mock_result)
        evaluator.set_runner(runner)

        result = await evaluator.evaluate("Tell me about the codebase", "pong" + _LONG)
        assert result.voice_consistency == 0.0
        assert result.verdict == "pass"

    @pytest.mark.asyncio
    async def test_voice_consistency_does_not_affect_verdict(self, evaluator):
        """A low voice score does NOT push verdict to fail — voice is
        operator-rateable observability, not a blocking gate.
        """
        mock_result = MagicMock()
        mock_result.is_error = False
        mock_result.response_text = json.dumps({
            "completeness": 9, "correctness": 9, "actionability": 9,
            "safety": 9, "voice_consistency": 1,
            "overall": 9.0, "issues": [], "verdict": "pass",
        })
        runner = AsyncMock()
        runner.invoke = AsyncMock(return_value=mock_result)
        evaluator.set_runner(runner)

        result = await evaluator.evaluate("Tell me about the codebase", "pong" + _LONG)
        assert result.voice_consistency == 1.0
        assert result.verdict == "pass"
        assert result.overall == 9.0

    @pytest.mark.asyncio
    async def test_voice_consistency_logged_to_jsonl(self, evaluator, tmp_path):
        """The new axis lands in the JSONL evaluation log so trend analysis
        has a stable source of truth.
        """
        mock_result = MagicMock()
        mock_result.is_error = False
        mock_result.response_text = json.dumps({
            "completeness": 8, "correctness": 8, "actionability": 8,
            "safety": 8, "voice_consistency": 6,
            "overall": 8.0, "issues": [], "verdict": "pass",
        })
        runner = AsyncMock()
        runner.invoke = AsyncMock(return_value=mock_result)
        evaluator.set_runner(runner)

        await evaluator.evaluate("Tell me about the codebase", "pong" + _LONG)

        log_path = evaluator.data_dir / "evaluation_log.jsonl"
        assert log_path.exists()
        last_line = log_path.read_text().strip().splitlines()[-1]
        entry = json.loads(last_line)
        assert entry["voice_consistency"] == 6.0
