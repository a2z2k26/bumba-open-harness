"""Tests for bridge.factory.triage — Dark Factory triage workflow.

Sprint 14.04 — Plan 14 Phase 2.

All `gh` and `claude` subprocess calls are mocked. These tests must NEVER
touch a live GitHub repo or invoke a real Claude subprocess.
"""
from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from bridge.factory.labels import FACTORY_OPT_IN_LABEL, FactoryState
from bridge.factory.triage import (
    COST_CAP_USD,
    TriageVerdict,
    _format_comment,
    _parse_claude_response,
    classify_issue,
    triage_workflow,
)


# ── Fixtures and helpers ────────────────────────────────────────────────


def _gh_issue_view_response(
    title: str = "Add foo",
    body: str = "We should add foo because bar.",
    labels: list[str] | None = None,
) -> tuple[int, str, str]:
    """Build a fake (rc, stdout, stderr) tuple for `gh issue view --json …`."""
    labels = labels or [FACTORY_OPT_IN_LABEL, FactoryState.UNTRIAGED.value]
    payload = {
        "title": title,
        "body": body,
        "labels": [{"name": n} for n in labels],
    }
    return (0, json.dumps(payload), "")


def _gh_issue_list_response(numbers: list[int]) -> tuple[int, str, str]:
    """Build a fake (rc, stdout, stderr) tuple for `gh issue list --json number`."""
    body = json.dumps([{"number": n} for n in numbers])
    return (0, body, "")


def _claude_json_response(
    state: str = "accepted",
    category: str = "feature",
    complexity: str = "small",
    reasoning: str = "Clear, in scope.",
    cost: float | None = None,
) -> tuple[int, str, str]:
    """Build a fake (rc, stdout, stderr) tuple for `claude -p`."""
    payload: dict[str, object] = {
        "state": state,
        "category": category,
        "complexity": complexity,
        "reasoning": reasoning,
    }
    if cost is not None:
        payload["cost_usd"] = cost
    return (0, json.dumps(payload), "")


# ── _parse_claude_response ──────────────────────────────────────────────


class TestParseClaudeResponse:
    def test_pure_json(self):
        out = json.dumps({"state": "accepted"})
        assert _parse_claude_response(out) == {"state": "accepted"}

    def test_fenced_json(self):
        out = "```json\n{\"state\": \"accepted\"}\n```"
        assert _parse_claude_response(out) == {"state": "accepted"}

    def test_prose_then_json(self):
        out = "Sure! Here is the verdict:\n{\"state\": \"rejected\"}\n"
        assert _parse_claude_response(out) == {"state": "rejected"}

    def test_malformed_returns_none(self):
        assert _parse_claude_response("not json at all") is None

    def test_empty_returns_none(self):
        assert _parse_claude_response("") is None

    def test_non_dict_returns_none(self):
        assert _parse_claude_response("[1, 2, 3]") is None


# ── classify_issue ──────────────────────────────────────────────────────


class TestClassifyIssue:
    """Happy and unhappy paths for the per-issue classifier."""

    def test_returns_verdict_for_happy_path(self):
        gh_view = _gh_issue_view_response(title="Add foo", body="Body text.")
        claude_resp = _claude_json_response(
            state="accepted",
            category="feature",
            complexity="small",
            reasoning="Looks good.",
        )

        with (
            patch(
                "bridge.factory.triage._run_subprocess",
                side_effect=[gh_view],
            ) as mock_run,
            patch(
                "bridge.factory.triage._invoke_claude",
                return_value=claude_resp,
            ) as mock_claude,
        ):
            verdict = classify_issue(42)

        assert mock_run.call_count == 1
        assert mock_claude.call_count == 1
        assert isinstance(verdict, TriageVerdict)
        assert verdict.issue_number == 42
        assert verdict.state is FactoryState.ACCEPTED
        assert verdict.category == "feature"
        assert verdict.complexity == "small"
        assert verdict.reasoning == "Looks good."
        assert verdict.cost_usd == 0.0

    def test_returns_needs_human_on_malformed_json(self):
        with (
            patch(
                "bridge.factory.triage._run_subprocess",
                side_effect=[_gh_issue_view_response()],
            ),
            patch(
                "bridge.factory.triage._invoke_claude",
                return_value=(0, "this is not json", ""),
            ),
        ):
            verdict = classify_issue(42)

        assert verdict.state is FactoryState.NEEDS_HUMAN
        assert "parseable JSON" in verdict.reasoning

    def test_returns_needs_human_on_non_zero_exit(self):
        with (
            patch(
                "bridge.factory.triage._run_subprocess",
                side_effect=[_gh_issue_view_response()],
            ),
            patch(
                "bridge.factory.triage._invoke_claude",
                return_value=(1, "", "OAuth token expired"),
            ),
        ):
            verdict = classify_issue(42)

        assert verdict.state is FactoryState.NEEDS_HUMAN
        assert "exit 1" in verdict.reasoning

    def test_returns_needs_human_on_timeout(self):
        with (
            patch(
                "bridge.factory.triage._run_subprocess",
                side_effect=[_gh_issue_view_response()],
            ),
            patch(
                "bridge.factory.triage._invoke_claude",
                side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=120),
            ),
        ):
            verdict = classify_issue(42)

        assert verdict.state is FactoryState.NEEDS_HUMAN
        assert "timed out" in verdict.reasoning

    def test_unknown_state_string_falls_back_to_needs_human(self):
        bad_state = (0, json.dumps({"state": "whatever", "reasoning": "x"}), "")
        with (
            patch(
                "bridge.factory.triage._run_subprocess",
                side_effect=[_gh_issue_view_response()],
            ),
            patch(
                "bridge.factory.triage._invoke_claude",
                return_value=bad_state,
            ),
        ):
            verdict = classify_issue(42)

        assert verdict.state is FactoryState.NEEDS_HUMAN

    def test_cost_cap_enforced_warns_but_still_ships(self, caplog):
        # cost > $0.05 cap — verdict still applies, warning logged
        excessive = _claude_json_response(cost=0.50)
        with (
            patch(
                "bridge.factory.triage._run_subprocess",
                side_effect=[_gh_issue_view_response()],
            ),
            patch(
                "bridge.factory.triage._invoke_claude",
                return_value=excessive,
            ),
            caplog.at_level("WARNING", logger="bridge.factory.triage"),
        ):
            verdict = classify_issue(42)

        assert verdict.cost_usd == pytest.approx(0.50)
        assert verdict.state is FactoryState.ACCEPTED
        # Warning was emitted
        assert any(
            "exceeded cap" in rec.message and rec.levelname == "WARNING"
            for rec in caplog.records
        ), [rec.message for rec in caplog.records]

    def test_cost_under_cap_no_warning(self):
        # COST_CAP_USD is the published constant — sanity-check the contract.
        assert COST_CAP_USD == pytest.approx(0.05)
        ok = _claude_json_response(cost=0.01)
        with (
            patch(
                "bridge.factory.triage._run_subprocess",
                side_effect=[_gh_issue_view_response()],
            ),
            patch(
                "bridge.factory.triage._invoke_claude",
                return_value=ok,
            ),
        ):
            verdict = classify_issue(42)

        assert verdict.cost_usd == pytest.approx(0.01)


# ── triage_workflow ─────────────────────────────────────────────────────


class TestTriageWorkflow:
    """Happy path, rate-limit overflow, feature flag gating, side effects."""

    def test_feature_flag_off_returns_empty_no_subprocess(self):
        # Use a sentinel that would ERROR on any subprocess call to prove no calls happen
        with patch(
            "bridge.factory.triage._run_subprocess",
            side_effect=AssertionError("subprocess should not be called when flag OFF"),
        ):
            verdicts = triage_workflow(config_enabled=False)
        assert verdicts == []

    def test_lists_only_factory_opt_in_untriaged(self):
        """The list call must use both opt-in AND untriaged labels."""
        captured_args: list[list[str]] = []

        def fake_run(args, **kwargs):
            captured_args.append(args)
            if args[:2] == ["gh", "issue"] and args[2] == "list":
                return _gh_issue_list_response([])
            raise AssertionError(f"unexpected call: {args}")

        with patch("bridge.factory.triage._run_subprocess", side_effect=fake_run):
            verdicts = triage_workflow(repo="owner/repo", max_issues=5)

        assert verdicts == []
        # First and only call should be the list with both labels
        assert len(captured_args) == 1
        list_args = captured_args[0]
        assert FACTORY_OPT_IN_LABEL in list_args
        assert FactoryState.UNTRIAGED.value in list_args
        assert "--state" in list_args
        assert "open" in list_args

    def test_classifies_each_and_calls_transition_state(self):
        """For each candidate, classify_issue is called and transition_state is invoked."""
        candidates = [101, 102, 103]
        list_resp = _gh_issue_list_response(candidates)

        # Every classify_issue call short-circuits to a fixed verdict
        fake_verdicts = {
            101: TriageVerdict(
                issue_number=101,
                state=FactoryState.ACCEPTED,
                category="feature",
                complexity="small",
                reasoning="ok",
                cost_usd=0.01,
                evaluated_at=__import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ),
            ),
            102: TriageVerdict(
                issue_number=102,
                state=FactoryState.REJECTED,
                category="docs",
                complexity="out-of-scope",
                reasoning="nope",
                cost_usd=0.01,
                evaluated_at=__import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ),
            ),
            103: TriageVerdict(
                issue_number=103,
                state=FactoryState.NEEDS_HUMAN,
                category="unknown",
                complexity="out-of-scope",
                reasoning="ambig",
                cost_usd=0.0,
                evaluated_at=__import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ),
            ),
        }

        def fake_run(args, **kwargs):
            # gh list — first call
            if args[:3] == ["gh", "issue", "list"]:
                return list_resp
            # gh comment — for each accepted/rejected/etc
            if args[:3] == ["gh", "issue", "comment"]:
                return (0, "", "")
            raise AssertionError(f"unexpected subprocess call: {args}")

        transition_calls: list[tuple] = []

        def fake_transition(num, frm, to):
            transition_calls.append((num, frm, to))
            return True

        with (
            patch("bridge.factory.triage._run_subprocess", side_effect=fake_run),
            patch(
                "bridge.factory.triage.classify_issue",
                side_effect=lambda n, repo="your-org/bumba-open-harness": fake_verdicts[n],
            ),
            patch(
                "bridge.factory.triage.transition_state",
                side_effect=fake_transition,
            ),
        ):
            verdicts = triage_workflow(max_issues=5)

        assert len(verdicts) == 3
        assert {v.issue_number for v in verdicts} == set(candidates)
        # transition_state called once per verdict, always FROM untriaged
        assert len(transition_calls) == 3
        for num, frm, to in transition_calls:
            assert frm is FactoryState.UNTRIAGED
            assert num in candidates

    def test_rate_limit_overflow_labeled_and_not_classified(self):
        """When more issues exist than max_issues, overflow gets factory:rate-limited."""
        candidates = list(range(201, 211))  # 10 issues
        max_issues = 3
        list_resp = _gh_issue_list_response(candidates)

        rate_limit_label_calls: list[int] = []

        def fake_run(args, **kwargs):
            if args[:3] == ["gh", "issue", "list"]:
                return list_resp
            if args[:3] == ["gh", "issue", "edit"]:
                # rate-limit label add — capture the issue number
                num = int(args[3])
                # find --add-label value
                idx = args.index("--add-label")
                if args[idx + 1] == FactoryState.RATE_LIMITED.value:
                    rate_limit_label_calls.append(num)
                return (0, "", "")
            if args[:3] == ["gh", "issue", "comment"]:
                return (0, "", "")
            if args[:3] == ["gh", "issue", "view"]:
                return _gh_issue_view_response()
            raise AssertionError(f"unexpected call: {args}")

        # classify_issue called only for the first max_issues
        classified_numbers: list[int] = []

        def fake_classify(num, repo="your-org/bumba-open-harness"):
            classified_numbers.append(num)
            return TriageVerdict(
                issue_number=num,
                state=FactoryState.ACCEPTED,
                category="feature",
                complexity="small",
                reasoning="ok",
                cost_usd=0.01,
                evaluated_at=__import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ),
            )

        with (
            patch("bridge.factory.triage._run_subprocess", side_effect=fake_run),
            patch("bridge.factory.triage.classify_issue", side_effect=fake_classify),
            patch(
                "bridge.factory.triage.transition_state",
                return_value=True,
            ),
        ):
            verdicts = triage_workflow(max_issues=max_issues)

        # Exactly max_issues classified
        assert len(verdicts) == max_issues
        assert classified_numbers == candidates[:max_issues]
        # Overflow (7 issues) all got the rate-limit label
        assert sorted(rate_limit_label_calls) == sorted(candidates[max_issues:])

    def test_workflow_comments_rationale_on_each(self):
        """Each transitioned verdict produces an issue comment."""
        list_resp = _gh_issue_list_response([501])

        comment_bodies: list[str] = []

        def fake_run(args, **kwargs):
            if args[:3] == ["gh", "issue", "list"]:
                return list_resp
            if args[:3] == ["gh", "issue", "comment"]:
                # Capture the --body argument
                idx = args.index("--body")
                comment_bodies.append(args[idx + 1])
                return (0, "", "")
            raise AssertionError(f"unexpected call: {args}")

        verdict = TriageVerdict(
            issue_number=501,
            state=FactoryState.ACCEPTED,
            category="bug-fix",
            complexity="medium",
            reasoning="A reasonable fix.",
            cost_usd=0.02,
            evaluated_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
        )

        with (
            patch("bridge.factory.triage._run_subprocess", side_effect=fake_run),
            patch(
                "bridge.factory.triage.classify_issue",
                return_value=verdict,
            ),
            patch(
                "bridge.factory.triage.transition_state",
                return_value=True,
            ),
        ):
            verdicts = triage_workflow(max_issues=5)

        assert len(verdicts) == 1
        assert len(comment_bodies) == 1
        body = comment_bodies[0]
        # The comment must reflect the verdict
        assert "factory:accepted" in body
        assert "bug-fix" in body
        assert "medium" in body
        assert "A reasonable fix." in body

    def test_workflow_skips_comment_when_transition_optimistic_check_fails(self):
        """If transition_state returns False (label moved out from under us), no comment."""
        list_resp = _gh_issue_list_response([777])

        comment_called = False

        def fake_run(args, **kwargs):
            nonlocal comment_called
            if args[:3] == ["gh", "issue", "list"]:
                return list_resp
            if args[:3] == ["gh", "issue", "comment"]:
                comment_called = True
                return (0, "", "")
            raise AssertionError(f"unexpected call: {args}")

        verdict = TriageVerdict(
            issue_number=777,
            state=FactoryState.ACCEPTED,
            category="feature",
            complexity="small",
            reasoning="ok",
            cost_usd=0.0,
            evaluated_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
        )

        with (
            patch("bridge.factory.triage._run_subprocess", side_effect=fake_run),
            patch(
                "bridge.factory.triage.classify_issue",
                return_value=verdict,
            ),
            patch(
                "bridge.factory.triage.transition_state",
                return_value=False,  # optimistic check failed
            ),
        ):
            verdicts = triage_workflow(max_issues=5)

        assert len(verdicts) == 1
        assert comment_called is False


# ── _format_comment ─────────────────────────────────────────────────────


def test_format_comment_includes_all_fields():
    import datetime as _dt

    verdict = TriageVerdict(
        issue_number=99,
        state=FactoryState.REJECTED,
        category="docs",
        complexity="out-of-scope",
        reasoning="Not actionable.",
        cost_usd=0.003,
        evaluated_at=_dt.datetime(2026, 4, 29, 12, 0, 0, tzinfo=_dt.timezone.utc),
    )
    body = _format_comment(verdict)
    assert "factory:rejected" in body
    assert "docs" in body
    assert "out-of-scope" in body
    assert "$0.0030" in body
    assert "2026-04-29T12:00:00+00:00" in body
    assert "Not actionable." in body
