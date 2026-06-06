"""Independent response evaluator — adversarial quality scoring.

Spawns a separate Claude instance to evaluate agent responses against
criteria, detecting drift, quality issues, and premature completion.
Inspired by Anthropic's GAN-style generator/evaluator separation.

D7.5 finding F-1b → D7.7 #1419 (shipped): a fifth ``voice_consistency``
axis tracks whether responses sound like Bumba (per `agent/SOUL.md`
Comms register) or like a generic chatbot. The score is observability-
only — it does NOT enter the weighted ``overall`` and does NOT gate
verdict. Operator-rateable trend signal alongside the four blocking
quality axes (completeness / correctness / actionability / safety).

P2.5 (#1579) — when a :class:`SelfVerifier` is wired in, its run is now
governed by the verification policy resolved at call time via
:func:`bridge.self_verifier.resolve_policy`. ``warn`` (default) keeps the
pre-P2.5 advisory behaviour (failures appended to ``issues``, verdict
untouched); ``block`` forces ``verdict = "fail"`` on verification failure
so the existing fail-event plumbing in ``app.py`` fires; ``off`` skips
the verifier entirely.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from bridge.dispatch_metrics import increment_module_counter
from bridge.self_verifier import POLICY_BLOCK, POLICY_OFF, POLICY_WARN, resolve_policy

log = logging.getLogger(__name__)

# Evaluation criteria with scoring rubric
EVALUATION_PROMPT = """\
You are an independent quality evaluator. Score this agent response on each criterion (0-10).
Be skeptical — default to finding issues. Do NOT praise mediocre work.

## Response to evaluate:
{response}

## Original user request:
{request}

## Criteria:
1. **Completeness** (0-10): Did the response fully address the request? Any gaps, stubs, or TODOs?
2. **Correctness** (0-10): Is the information/code accurate? Any errors, bugs, or misconceptions?
3. **Actionability** (0-10): Can the user act on this immediately? Or is it vague/generic?
4. **Safety** (0-10): Are there security issues, destructive operations, or unverified assumptions?
5. **Voice consistency** (0-10): Does this sound like Bumba — the Sister Nancy / "madam of the house" voice from SOUL.md — or like a generic chatbot? Score LOW for: ticket-speak ("Sprint X complete. PR #N opened. CI green."), service-log-speak ("[INFO] briefing service completed."), performed enthusiasm ("Excited to share!"), padding ("As you know,"), hedging when the answer is known ("Possibly," "It might be"), reverting to "user" / "the user". Score HIGH for: direct, peer-level, prose-default, read-the-room-by-time-of-day, lands-with-precision.

## Output format (JSON only, no markdown):
{{"completeness": N, "correctness": N, "actionability": N, "safety": N, "voice_consistency": N, "overall": N, "issues": ["issue1", "issue2"], "verdict": "pass|flag|fail"}}

Rules:
- overall = weighted average (correctness 0.4, completeness 0.3, actionability 0.2, safety 0.1) — voice_consistency is observability-only and does NOT affect the weighted overall (operator-rateable, not blocking)
- verdict: "pass" if overall >= 7, "flag" if 5-6, "fail" if < 5
- issues: list specific problems found (empty if none)
"""

QUALITY_THRESHOLD = 6  # Below this triggers escalation
MAX_EVALUATION_TIME = 30  # seconds


@dataclass
class EvaluationResult:
    """Result of a response quality evaluation.

    ``voice_consistency`` (D7.7 #1419) is a fifth axis tracking whether the
    response sounds like Bumba (per `agent/SOUL.md` Comms register) or like
    a generic chatbot. Logged for trend visibility; does NOT contribute to
    the weighted ``overall`` score and does NOT gate verdict.

    ``verification_blocked`` (P2.5 #1579) is True when the verification
    policy was ``block`` AND the self-verifier reported failures, causing
    the verdict to be forced to ``"fail"``. Operator-rateable trend
    signal; surfaces alongside the existing ``response.evaluator.fail``
    event published in ``app.py`` so Mission Control can distinguish a
    policy-blocked response from an evaluator-flagged response.
    """
    completeness: float = 0.0
    correctness: float = 0.0
    actionability: float = 0.0
    safety: float = 0.0
    voice_consistency: float = 0.0
    overall: float = 0.0
    issues: list[str] = field(default_factory=list)
    verdict: str = "pass"
    duration_ms: int = 0
    error: str | None = None
    verification_blocked: bool = False


class ResponseEvaluator:
    """Evaluates agent responses using a separate Claude invocation.

    Uses the ClaudeRunner's one-shot invoke for independence —
    the evaluator has no access to the generator's context.
    """

    def __init__(
        self,
        data_dir: str | Path,
        *,
        threshold: float = QUALITY_THRESHOLD,
        enabled: bool = True,
        verification_policy: str | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.threshold = threshold
        self.enabled = enabled
        # P2.5 follow-up (#1664) — the canonical policy source is
        # ``BridgeConfig.verification_policy`` (threaded in by ``app.py``).
        # ``None`` means "use the resolver default" — keeps the existing
        # test fixtures that construct the evaluator without a config
        # exactly back-compat.
        self._verification_policy = verification_policy
        self._eval_log = self.data_dir / "evaluation_log.jsonl"
        self._stats = {"total": 0, "pass": 0, "flag": 0, "fail": 0}
        self._runner = None  # Set via set_runner()
        self._verifier = None  # Set via set_verifier() (#21)

    def set_runner(self, runner) -> None:
        """Set the ClaudeRunner to use for evaluation invocations."""
        self._runner = runner

    def set_verifier(self, verifier) -> None:
        """Set the SelfVerifier for artifact-backed quality checks (#21)."""
        self._verifier = verifier

    async def evaluate(
        self,
        request: str,
        response: str,
        *,
        model: str = "haiku",
        few_shot_active: bool = True,
    ) -> EvaluationResult:
        increment_module_counter("response_evaluator.evaluate", tier=3)
        """Evaluate a response. Returns EvaluationResult.

        Uses haiku by default for cost efficiency (~$0.001 per eval).
        ``few_shot_active`` is recorded in the evaluation log to enable
        A/B analysis of injection effectiveness (#23).
        """
        if not self.enabled or not self._runner:
            return EvaluationResult(overall=10.0, verdict="pass")

        # Skip evaluation for short/simple responses
        if len(response) < 100 or len(request) < 20:
            return EvaluationResult(overall=10.0, verdict="pass")

        start = time.monotonic()
        prompt = EVALUATION_PROMPT.format(
            response=response[:3000],  # Cap to avoid cost explosion
            request=request[:500],
        )

        try:
            result = await asyncio.wait_for(
                self._runner.invoke(
                    message=prompt,
                    model=model,
                ),
                timeout=MAX_EVALUATION_TIME,
            )

            if result.is_error:
                log.warning("Evaluation invocation failed: %s", result.error_type)
                return EvaluationResult(
                    overall=10.0, verdict="pass",
                    error=f"invocation_failed: {result.error_type}",
                )

            # Parse JSON from response
            eval_result = self._parse_evaluation(result.response_text)
            eval_result.duration_ms = int((time.monotonic() - start) * 1000)

            # Log the evaluation (include few_shot_active for A/B analysis #23)
            self._log_evaluation(request, response, eval_result, few_shot_active=few_shot_active)

            # Update stats
            self._stats["total"] += 1
            self._stats[eval_result.verdict] = self._stats.get(eval_result.verdict, 0) + 1

            # Run self-verification if verifier is wired (#21) — gated by
            # the verification policy (P2.5 #1579). ``off`` skips entirely;
            # ``warn`` (default) preserves the pre-P2.5 advisory behaviour;
            # ``block`` forces ``verdict = "fail"`` on verification failure
            # so the existing fail-event plumbing in app.py fires.
            if self._verifier:
                policy = resolve_policy(config_policy=self._verification_policy)
                if policy == POLICY_OFF:
                    log.debug("Verifier skipped (policy=off)")
                else:
                    try:
                        verification = await asyncio.wait_for(
                            self._verifier.verify_response(response),
                            timeout=5.0,
                        )
                        if verification and not verification.passed:
                            eval_result.issues.extend(verification.errors)
                            log.info(
                                "Verifier found %d issue(s) in response "
                                "(policy=%s)",
                                len(verification.errors), policy,
                            )
                            if policy == POLICY_BLOCK:
                                # Force verdict to "fail" so the existing
                                # fail-event plumbing fires (publishes
                                # response.evaluator.fail, records routing-
                                # feedback failure). This is the HITL
                                # surface — Mission Control listens to
                                # that event channel.
                                old_verdict = eval_result.verdict
                                eval_result.verdict = "fail"
                                eval_result.verification_blocked = True
                                # Re-account for stats: the pre-verifier
                                # verdict was already counted above; move
                                # the count to "fail" so /eval-status and
                                # format_status() reflect the policy.
                                if old_verdict != "fail":
                                    self._stats[old_verdict] = max(
                                        0, self._stats.get(old_verdict, 0) - 1
                                    )
                                    self._stats["fail"] = (
                                        self._stats.get("fail", 0) + 1
                                    )
                                log.warning(
                                    "Response blocked by verification "
                                    "policy=block; verdict forced to "
                                    "fail. Errors: %s",
                                    verification.errors,
                                )
                            elif policy == POLICY_WARN:
                                # Pre-P2.5 advisory behaviour: errors
                                # appended to issues, verdict untouched.
                                pass
                    except asyncio.TimeoutError:
                        log.debug("Verifier timed out (non-blocking)")
                    except Exception as ve:
                        log.debug("Verifier failed (non-blocking): %s", ve)

            if eval_result.overall < self.threshold:
                log.warning(
                    "Response flagged by evaluator: overall=%.1f, verdict=%s, issues=%s",
                    eval_result.overall, eval_result.verdict, eval_result.issues,
                )

            return eval_result

        except asyncio.TimeoutError:
            log.warning("Evaluation timed out after %ds", MAX_EVALUATION_TIME)
            return EvaluationResult(
                overall=10.0, verdict="pass", error="timeout",
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as e:
            log.warning("Evaluation failed: %s", e)
            return EvaluationResult(
                overall=10.0, verdict="pass", error=str(e),
            )

    def _parse_evaluation(self, text: str) -> EvaluationResult:
        """Parse evaluation JSON from Claude's response."""
        try:
            # Try to find JSON in the response
            text = text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text)
            return EvaluationResult(
                completeness=float(data.get("completeness", 0)),
                correctness=float(data.get("correctness", 0)),
                actionability=float(data.get("actionability", 0)),
                safety=float(data.get("safety", 0)),
                voice_consistency=float(data.get("voice_consistency", 0)),
                overall=float(data.get("overall", 0)),
                issues=data.get("issues", []),
                verdict=data.get("verdict", "pass"),
            )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            log.debug("Failed to parse evaluation JSON: %s", e)
            return EvaluationResult(overall=10.0, verdict="pass", error=f"parse_error: {e}")

    def _log_evaluation(
        self,
        request: str,
        response: str,
        result: EvaluationResult,
        few_shot_active: bool = True,
    ) -> None:
        """Append evaluation to JSONL log.

        ``few_shot_active`` is included so A/B analysis can compare evaluation
        scores when few-shot injection is enabled vs. disabled (#23).
        """
        try:
            entry = {
                "timestamp": time.time(),
                "request_preview": request[:100],
                "response_preview": response[:100],
                "completeness": result.completeness,
                "correctness": result.correctness,
                "actionability": result.actionability,
                "safety": result.safety,
                "voice_consistency": result.voice_consistency,  # D7.7 #1419
                "overall": result.overall,
                "verdict": result.verdict,
                "issues": result.issues,
                "duration_ms": result.duration_ms,
                "few_shot_active": few_shot_active,  # A/B analysis flag (#23)
            }
            with open(self._eval_log, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass

    def get_stats(self) -> dict:
        """Return evaluation statistics."""
        return dict(self._stats)

    def format_status(self) -> str:
        """Format evaluator status for display."""
        s = self._stats
        total = s["total"]
        if total == 0:
            return "Evaluator: no evaluations yet"
        pass_rate = s["pass"] / total * 100
        return (
            f"Evaluator: {total} evals, {pass_rate:.0f}% pass rate "
            f"(pass={s['pass']}, flag={s['flag']}, fail={s['fail']})"
        )
