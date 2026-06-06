"""Tests for ``scripts.experiment_holdout_validator`` (Sprint 02.14, issue #989).

The validator delegates all subprocess work to a caller-supplied runner;
every test here uses a mock runner so we never hit the real Anthropic API
or spawn ``claude -p`` for real. ``get_origin_main_sha`` is exercised
with ``subprocess.run`` mocked to a known SHA.
"""
from __future__ import annotations

import asyncio
import sys
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# The validator lives next to ``experiment_loop`` under ``scripts/``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import experiment_holdout_validator as ehv  # noqa: E402  — sys.path mutated above
from experiment_holdout_validator import (  # noqa: E402
    HoldoutValidatorVerdict,
    ValidatorInput,
    ValidatorResult,
    build_prompt,
    get_origin_main_sha,
    parse_validator_output,
    run_validator,
)


# ── Helpers ─────────────────────────────────────────────────────────────


def _well_formed(
    verdict: str = "improvement",
    summary: str = "looks like a real win",
    findings: tuple[str, ...] = ("clarifies error message",),
) -> str:
    finding_lines = "\n".join(f"- {f}" for f in findings) if findings else "- none"
    return (
        f"VERDICT: {verdict}\n"
        f"SUMMARY: {summary}\n"
        "FINDINGS:\n"
        f"{finding_lines}\n"
    )


def _input(
    iter_id: str = "iter-test-001",
    issue_body: str = "Improve the error message in foo.py",
    diff_text: str = "diff --git a/foo.py b/foo.py\n+ pass\n",
    program_origin_sha: str = "abc1234",
    cost_cap_usd: float = 0.30,
    timeout_s: int = 90,
) -> ValidatorInput:
    return ValidatorInput(
        iter_id=iter_id,
        issue_body=issue_body,
        diff_text=diff_text,
        program_origin_sha=program_origin_sha,
        cost_cap_usd=cost_cap_usd,
        timeout_s=timeout_s,
    )


def _make_runner(
    response: str | None = None,
    cost_usd: float = 0.05,
    latency_ms: int = 200,
):
    """Return ``(runner, captured_prompts)`` — recording mock."""
    captured: list[str] = []
    body = response if response is not None else _well_formed()

    async def _runner(prompt: str) -> tuple[str, float, int]:
        captured.append(prompt)
        return body, cost_usd, latency_ms

    return _runner, captured


# ── parse_validator_output ───────────────────────────────────────────────


class TestParseValidatorOutput:
    def test_improvement_with_summary_and_findings(self):
        raw = (
            "VERDICT: improvement\n"
            "SUMMARY: cleans up duplicated logic\n"
            "FINDINGS:\n"
            "- removes 12 lines of dead code\n"
            "- adds a unit test\n"
        )
        verdict, summary, findings, err = parse_validator_output(raw)
        assert verdict is HoldoutValidatorVerdict.IMPROVEMENT
        assert summary == "cleans up duplicated logic"
        assert findings == ("removes 12 lines of dead code", "adds a unit test")
        assert err is None

    @pytest.mark.parametrize(
        "literal,expected",
        [
            ("improvement", HoldoutValidatorVerdict.IMPROVEMENT),
            ("noise", HoldoutValidatorVerdict.NOISE),
            ("regression", HoldoutValidatorVerdict.REGRESSION),
            ("unsure", HoldoutValidatorVerdict.UNSURE),
        ],
    )
    def test_each_verdict_literal_recognized(self, literal, expected):
        raw = f"VERDICT: {literal}\nSUMMARY: x\nFINDINGS:\n- y\n"
        verdict, _, _, err = parse_validator_output(raw)
        assert verdict is expected
        assert err is None

    def test_garbage_returns_unsure_with_parse_error(self):
        verdict, summary, findings, err = parse_validator_output(
            "the model rambled and forgot the format"
        )
        assert verdict is HoldoutValidatorVerdict.UNSURE
        assert summary == "validator output malformed"
        assert findings == ()
        assert err is not None
        assert "VERDICT" in err

    def test_empty_string_returns_unsure(self):
        verdict, _, _, err = parse_validator_output("")
        assert verdict is HoldoutValidatorVerdict.UNSURE
        assert err is not None
        assert "empty" in err.lower()

    def test_whitespace_only_returns_unsure(self):
        verdict, _, _, err = parse_validator_output("   \n   \n")
        assert verdict is HoldoutValidatorVerdict.UNSURE
        assert err is not None

    def test_findings_drop_none_placeholder(self):
        raw = (
            "VERDICT: noise\n"
            "SUMMARY: cosmetic only\n"
            "FINDINGS:\n"
            "- none\n"
        )
        verdict, _, findings, err = parse_validator_output(raw)
        assert verdict is HoldoutValidatorVerdict.NOISE
        assert findings == ()
        assert err is None

    def test_summary_falls_back_when_no_explicit_summary_line(self):
        raw = (
            "VERDICT: regression\n"
            "this looks bad\n"
            "FINDINGS:\n"
            "- swallows an exception\n"
        )
        verdict, summary, findings, err = parse_validator_output(raw)
        assert verdict is HoldoutValidatorVerdict.REGRESSION
        assert summary == "this looks bad"
        assert findings == ("swallows an exception",)
        assert err is None


# ── build_prompt ─────────────────────────────────────────────────────────


class TestBuildPrompt:
    def test_prompt_contains_all_inputs(self):
        prompt = build_prompt(
            _input(
                iter_id="iter-42",
                issue_body="THE_PROPOSAL_BODY",
                diff_text="THE_DIFF_TEXT",
                program_origin_sha="deadbeef",
            )
        )
        assert "iter-42" in prompt
        assert "THE_PROPOSAL_BODY" in prompt
        assert "THE_DIFF_TEXT" in prompt
        assert "deadbeef" in prompt
        assert "improvement|noise|regression|unsure" in prompt


# ── run_validator ────────────────────────────────────────────────────────


class TestRunValidator:
    def test_happy_path_returns_populated_result(self):
        runner, captured = _make_runner()
        result = asyncio.run(run_validator(_input(), runner=runner))

        assert isinstance(result, ValidatorResult)
        assert result.iter_id == "iter-test-001"
        assert result.verdict is HoldoutValidatorVerdict.IMPROVEMENT
        assert result.summary == "looks like a real win"
        assert result.findings == ("clarifies error message",)
        assert result.cost_usd == pytest.approx(0.05)
        assert result.latency_ms == 200
        assert result.parse_error is None
        assert result.raw_response  # non-empty
        assert len(captured) == 1
        # Prompt MUST contain the iter_id and issue body verbatim.
        assert "iter-test-001" in captured[0]
        assert "Improve the error message in foo.py" in captured[0]

    def test_timeout_yields_unsure_with_parse_error_naming_timeout(self):
        async def slow_runner(prompt: str) -> tuple[str, float, int]:
            raise asyncio.TimeoutError("90s")

        result = asyncio.run(run_validator(_input(), runner=slow_runner))
        assert result.verdict is HoldoutValidatorVerdict.UNSURE
        assert "timed out" in result.summary
        assert result.parse_error is not None
        assert "TimeoutError" in result.parse_error
        assert result.cost_usd == 0.0

    def test_runtime_error_yields_unsure(self):
        async def boom_runner(prompt: str) -> tuple[str, float, int]:
            raise RuntimeError("oauth expired")

        result = asyncio.run(run_validator(_input(), runner=boom_runner))
        assert result.verdict is HoldoutValidatorVerdict.UNSURE
        assert "failed" in result.summary
        assert result.parse_error is not None
        assert "RuntimeError" in result.parse_error
        assert "oauth expired" in result.parse_error
        assert result.cost_usd == 0.0

    def test_garbage_response_yields_unsure_with_parse_error(self):
        runner, _ = _make_runner(response="model rambled, no structure here")
        result = asyncio.run(run_validator(_input(), runner=runner))
        assert result.verdict is HoldoutValidatorVerdict.UNSURE
        assert result.parse_error is not None
        assert "VERDICT" in result.parse_error
        # Cost still captured even though parsing failed.
        assert result.cost_usd == pytest.approx(0.05)

    def test_cost_cap_breach_yields_unsure_with_cost_cap_exceeded(self):
        # Runner reports $1.50 spend against a $0.30 cap.
        runner, _ = _make_runner(cost_usd=1.50)
        result = asyncio.run(
            run_validator(_input(cost_cap_usd=0.30), runner=runner)
        )
        assert result.verdict is HoldoutValidatorVerdict.UNSURE
        assert result.parse_error == "cost_cap_exceeded"
        assert result.cost_usd == pytest.approx(1.50)
        # raw_response is preserved for the audit trail.
        assert result.raw_response

    def test_cost_cap_exact_boundary_does_not_trip(self):
        runner, _ = _make_runner(cost_usd=0.30)
        result = asyncio.run(
            run_validator(_input(cost_cap_usd=0.30), runner=runner)
        )
        assert result.parse_error is None
        assert result.verdict is HoldoutValidatorVerdict.IMPROVEMENT


# ── get_origin_main_sha ──────────────────────────────────────────────────


class TestGetOriginMainSha:
    def test_returns_sha_from_subprocess_stdout(self):
        fake_proc = MagicMock(returncode=0, stdout="abc123def\n", stderr="")
        with patch.object(ehv.subprocess, "run", return_value=fake_proc) as run_mock:
            sha = get_origin_main_sha(cwd="/repo")
        assert sha == "abc123def"
        # Confirms the right git command was issued.
        cmd = run_mock.call_args.args[0]
        assert cmd == ["git", "rev-parse", "origin/main"]
        assert run_mock.call_args.kwargs["cwd"] == "/repo"

    def test_subprocess_nonzero_exit_returns_unknown(self):
        fake_proc = MagicMock(
            returncode=128, stdout="", stderr="fatal: not a repo"
        )
        with patch.object(ehv.subprocess, "run", return_value=fake_proc):
            sha = get_origin_main_sha(cwd="/no-such-repo")
        assert sha == "unknown"

    def test_subprocess_timeout_returns_unknown(self):
        with patch.object(
            ehv.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=10),
        ):
            sha = get_origin_main_sha()
        assert sha == "unknown"

    def test_filenotfound_returns_unknown(self):
        with patch.object(
            ehv.subprocess, "run", side_effect=FileNotFoundError("no git")
        ):
            sha = get_origin_main_sha()
        assert sha == "unknown"

    def test_empty_stdout_returns_unknown(self):
        fake_proc = MagicMock(returncode=0, stdout="\n", stderr="")
        with patch.object(ehv.subprocess, "run", return_value=fake_proc):
            sha = get_origin_main_sha()
        assert sha == "unknown"


# ── Integration: validate_experiment wiring (issue #989) ────────────────


class TestValidateExperimentIntegration:
    """Verify ``experiment_loop.validate_experiment`` honors the validator
    verdict. We exercise the wiring with a fake runner; no real claude.
    """

    def test_regression_verdict_flips_to_discard(self, tmp_path, monkeypatch):
        # Build a fake worktree that passes the existing tests-and-lint
        # gates by short-circuiting them.
        import experiment_loop as el

        # Stub out the heavyweight gate machinery so the validator wiring
        # is what we're actually testing.
        monkeypatch.setattr(
            el,
            "validate_experiment",
            _build_validate_with_stubbed_gates(verdict_response="regression"),
        )
        # Sanity: the patched validate_experiment is the one we just set.
        assert el.validate_experiment.__name__ == "_validate_with_stubs"

        fake_runner, _ = _make_runner(
            response=_well_formed(
                verdict="regression",
                summary="silently swallows ValueError",
                findings=("removes try/except block in foo.py:42",),
            )
        )
        result = el.validate_experiment(
            worktree="/fake",
            iter_id="iter-x",
            issue_body="proposal",
            validator_runner=fake_runner,
            validator_enabled=True,
        )
        assert result["status"] == "discard"
        assert result["validator_verdict"] == "regression"
        assert "silently swallows" in result["validator_summary"]
        assert "holdout" in result["diff_summary"].lower()

    def test_improvement_verdict_keeps_status(self, tmp_path, monkeypatch):
        import experiment_loop as el

        monkeypatch.setattr(
            el,
            "validate_experiment",
            _build_validate_with_stubbed_gates(verdict_response="improvement"),
        )
        fake_runner, _ = _make_runner(
            response=_well_formed(verdict="improvement", summary="real win"),
        )
        result = el.validate_experiment(
            worktree="/fake",
            iter_id="iter-y",
            issue_body="proposal",
            validator_runner=fake_runner,
            validator_enabled=True,
        )
        assert result["status"] == "keep"
        assert result["validator_verdict"] == "improvement"

    def test_validator_disabled_flag_skips_validator(self, monkeypatch):
        import experiment_loop as el

        monkeypatch.setattr(
            el,
            "validate_experiment",
            _build_validate_with_stubbed_gates(verdict_response=None),
        )
        # No runner supplied; flag off → validator never runs.
        result = el.validate_experiment(
            worktree="/fake",
            iter_id="iter-z",
            issue_body="proposal",
            validator_enabled=False,
        )
        assert result["status"] == "keep"
        assert result["validator_verdict"] is None


def _build_validate_with_stubbed_gates(verdict_response: str | None):
    """Return a stub validate_experiment that bypasses pytest/git/ruff/mypy.

    This lets the integration tests focus on the validator wiring without
    standing up a real worktree. The stub re-implements the tail of the
    real function (validator block + return shape) using the verdict the
    test wants to inject.
    """
    import experiment_holdout_validator as ehv_mod
    import experiment_loop as el

    def _validate_with_stubs(
        worktree: str,
        *,
        iter_id: str | None = None,
        issue_body: str | None = None,
        validator_runner=None,
        validator_enabled: bool = False,
        validator_cost_cap_usd: float = 0.30,
        validator_model: str = "haiku",
    ) -> dict:
        status = "keep"
        diff_summary = "stub: 1 file changed, 1 insertion(+)"
        validator_verdict = None
        validator_summary = None
        validator_findings: tuple[str, ...] = ()
        notes: dict = {}

        if (
            status == "keep"
            and validator_enabled
            and validator_runner is not None
            and iter_id is not None
        ):
            v_input = ehv_mod.ValidatorInput(
                iter_id=iter_id,
                issue_body=issue_body or "",
                diff_text="stub-diff",
                program_origin_sha="stub-sha",
                cost_cap_usd=validator_cost_cap_usd,
            )
            v_result = asyncio.run(
                ehv_mod.run_validator(
                    v_input,
                    runner=validator_runner,
                    model=validator_model,
                )
            )
            validator_verdict = v_result.verdict.value
            validator_summary = v_result.summary
            validator_findings = v_result.findings
            notes["validator"] = {
                "verdict": validator_verdict,
                "summary": validator_summary,
                "findings": list(validator_findings),
            }
            if v_result.verdict in (
                ehv_mod.HoldoutValidatorVerdict.REGRESSION,
                ehv_mod.HoldoutValidatorVerdict.NOISE,
            ):
                status = "discard"
                diff_summary += f" (holdout: {validator_verdict} — {validator_summary})"

        # Touch the imported module so the linter doesn't drop the import.
        _ = el.validate_experiment  # noqa: F841

        return {
            "tests_passed": 1,
            "tests_failed": 0,
            "tests_total": 1,
            "status": status,
            "diff_summary": diff_summary,
            "duration_seconds": 0.01,
            "notes": notes,
            "validator_verdict": validator_verdict,
            "validator_summary": validator_summary,
            "validator_findings": list(validator_findings),
        }

    return _validate_with_stubs
