"""Tests for bridge.factory.channels and orchestrator wiring — Sprint 15.04.

Concept-only port (Dark Factory channels-as-branches) — no source copied.

Pure helpers are tested directly. Orchestrator integration uses the same
``patch``-the-collaborators pattern as ``test_factory_orchestrator.py`` so
``gh`` is never invoked.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.factory.channels import (
    ChannelInfo,
    ChannelLabelError,
    integration_branch_name,
    is_channel_close_ready,
    make_channel_close_issue_body,
    parse_channel_from_labels,
)
from bridge.factory.labels import FactoryState
from bridge.factory.seven_rule_synthesizer import (
    FactorySynthesisOutcome,
    SynthesisDecision,
)
from bridge.factory.validate import ValidateResult
from bridge.services.factory_orchestrator import (
    DEFAULT_COST_CAP_PER_ISSUE_USD,
    DEFAULT_COST_CAP_PER_TICK_USD,
    GLOBAL_LOCK_FILENAME,
    FactoryOrchestrator,
)


# ── Pure helpers ────────────────────────────────────────────────────────


class TestParseChannelFromLabels:
    def test_member_label_returns_channel_info(self):
        info = parse_channel_from_labels(
            ["factory:accepted", "factory:channel:export-redesign"]
        )
        assert info == ChannelInfo(
            name="export-redesign",
            integration_branch="factory/channel/export-redesign/integration",
            is_close_issue=False,
        )

    def test_close_label_marks_is_close_issue(self):
        info = parse_channel_from_labels(["factory:channel-close:foo"])
        assert info is not None
        assert info.is_close_issue is True
        assert info.name == "foo"
        assert info.integration_branch == "factory/channel/foo/integration"

    def test_two_distinct_member_channels_raises(self):
        with pytest.raises(ChannelLabelError):
            parse_channel_from_labels(
                ["factory:channel:a", "factory:channel:b"]
            )

    def test_member_and_close_for_same_channel_raises(self):
        # The orchestrator never files close on top of an existing
        # member; this combination is a state-machine violation.
        with pytest.raises(ChannelLabelError):
            parse_channel_from_labels(
                ["factory:channel:foo", "factory:channel-close:foo"]
            )

    def test_no_channel_labels_returns_none(self):
        assert parse_channel_from_labels([]) is None
        assert parse_channel_from_labels(["factory:accepted"]) is None
        assert (
            parse_channel_from_labels(
                ["factory:accepted", "type:bug", "size/M"]
            )
            is None
        )

    def test_duplicate_same_label_is_no_op(self):
        # GitHub already deduplicates, but we tolerate the input shape.
        info = parse_channel_from_labels(
            [
                "factory:channel:foo",
                "factory:channel:foo",
            ]
        )
        assert info is not None and info.name == "foo"

    def test_empty_channel_name_after_prefix_is_ignored(self):
        # ``factory:channel:`` with nothing after is malformed → None.
        assert parse_channel_from_labels(["factory:channel:"]) is None

    def test_non_string_entries_are_skipped(self):
        info = parse_channel_from_labels(
            [None, 42, "factory:channel:ok"]  # type: ignore[list-item]
        )
        assert info is not None and info.name == "ok"


class TestIntegrationBranchName:
    def test_format(self):
        assert (
            integration_branch_name("export-redesign")
            == "factory/channel/export-redesign/integration"
        )

    def test_does_not_normalize_input(self):
        # Pure function — surface bad input as a real error downstream
        # rather than silently rewriting kebab-case.
        assert integration_branch_name("Foo Bar") == (
            "factory/channel/Foo Bar/integration"
        )

    def test_custom_prefix(self):
        assert (
            integration_branch_name("feat", prefix="org/integration")
            == "org/integration/feat/integration"
        )


class TestBranchPrefixThreading:
    """Verify branch_prefix flows from parse_channel_from_labels and
    make_channel_close_issue_body when a custom prefix is supplied."""

    def test_parse_channel_uses_custom_prefix(self):
        info = parse_channel_from_labels(
            ["factory:channel:alpha"],
            branch_prefix="custom/prefix",
        )
        assert info is not None
        assert info.integration_branch == "custom/prefix/alpha/integration"

    def test_make_close_body_uses_custom_prefix(self):
        _, body = make_channel_close_issue_body(
            "alpha",
            closed_issue_numbers=[1, 2],
            branch_prefix="custom/prefix",
        )
        assert "custom/prefix/alpha/integration" in body


class TestIsChannelCloseReady:
    def test_true_when_no_open_members(self):
        # Only an unrelated issue + a close issue for a different channel.
        labels_by_number: dict[int, list[str]] = {
            10: ["type:bug"],
            11: ["factory:channel-close:other"],
        }
        assert (
            is_channel_close_ready(
                "foo", open_issue_labels_by_number=labels_by_number
            )
            is True
        )

    def test_false_when_open_member_exists(self):
        labels_by_number: dict[int, list[str]] = {
            10: ["factory:channel:foo", "factory:accepted"],
        }
        assert (
            is_channel_close_ready(
                "foo", open_issue_labels_by_number=labels_by_number
            )
            is False
        )

    def test_close_issue_for_same_channel_does_not_block(self):
        labels_by_number: dict[int, list[str]] = {
            10: ["factory:channel-close:foo"],
        }
        assert (
            is_channel_close_ready(
                "foo", open_issue_labels_by_number=labels_by_number
            )
            is True
        )

    def test_empty_input_is_ready(self):
        assert (
            is_channel_close_ready("foo", open_issue_labels_by_number={})
            is True
        )


class TestMakeChannelCloseIssueBody:
    def test_title_and_body_shape(self):
        title, body = make_channel_close_issue_body(
            "export-redesign", closed_issue_numbers=[12, 13, 14],
        )
        assert title == "Close channel: export-redesign"
        assert "factory/channel/export-redesign/integration" in body
        assert "- #12" in body and "- #13" in body and "- #14" in body
        assert "Concept-only" in body and "no LICENSE" in body

    def test_empty_children_lists_placeholder(self):
        _title, body = make_channel_close_issue_body(
            "empty-chan", closed_issue_numbers=[],
        )
        assert "(no children" in body


# ── Orchestrator integration ────────────────────────────────────────────


@dataclass
class _FakeImplementResult:
    issue_number: int
    pr_number: int | None
    pr_url: str | None
    final_state: FactoryState
    failed_phase: str | None
    cost_usd: float


def _make_validate_pass(*, cost: float = 0.05) -> ValidateResult:
    return ValidateResult(
        reviewer_results=(),
        aggregate_verdict="pass",  # type: ignore[arg-type]
        block_reasons=(),
        total_cost_usd=cost,
    )


def _make_orchestrator(
    tmp_path: Path,
    *,
    channels_enabled: bool,
    impl_result: _FakeImplementResult | None = None,
) -> tuple[FactoryOrchestrator, MagicMock]:
    """Build an orchestrator + return the implement-runner mock for assertions."""
    impl_result = impl_result or _FakeImplementResult(
        issue_number=1,
        pr_number=99,
        pr_url="https://example/pr/99",
        final_state=FactoryState.NEEDS_REVIEW,
        failed_phase=None,
        cost_usd=0.50,
    )
    implement_runner = MagicMock(return_value=impl_result)
    validate_runner = AsyncMock(return_value=_make_validate_pass())
    synthesizer = MagicMock(
        return_value=SynthesisDecision(
            outcome=FactorySynthesisOutcome.READY_FOR_OPERATOR,
            rule_fired=1,
            explanation="ok",
        )
    )
    orch = FactoryOrchestrator(
        data_dir=tmp_path,
        chat_id="",
        config_enabled=True,
        implement_runner=implement_runner,
        validate_runner=validate_runner,
        synthesizer=synthesizer,
        global_lock_path=tmp_path / GLOBAL_LOCK_FILENAME,
        per_target_lock_dir=tmp_path / "factory-locks",
        cost_cap_per_tick_usd=DEFAULT_COST_CAP_PER_TICK_USD,
        cost_cap_per_issue_usd=DEFAULT_COST_CAP_PER_ISSUE_USD,
        channels_enabled=channels_enabled,
    )
    return orch, implement_runner


@pytest.mark.asyncio
class TestOrchestratorChannelsRouting:
    async def test_member_issue_routes_implement_to_integration_branch(
        self, tmp_path: Path
    ):
        orch, implement_runner = _make_orchestrator(
            tmp_path, channels_enabled=True,
        )
        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[
                {
                    "number": 7,
                    "title": "child of channel",
                    "body": "do thing",
                    "labels": [
                        {"name": "factory:accepted"},
                        {"name": "factory:channel:export-redesign"},
                    ],
                }
            ],
        ), patch(
            "bridge.services.factory_orchestrator._gh_pr_diff",
            return_value="diff",
        ), patch(
            "bridge.services.factory_orchestrator._gh_issue_comment"
        ), patch(
            "bridge.services.factory_orchestrator._gh_pr_ready_for_review"
        ), patch(
            "bridge.services.factory_orchestrator.transition_state",
            return_value=True,
        ), patch(
            "bridge.services.factory_orchestrator._gh_branch_exists",
            return_value=True,
        ), patch(
            "bridge.services.factory_orchestrator._gh_list_open_issues_with_labels",
            return_value={},
        ), patch(
            "bridge.services.factory_orchestrator._gh_create_channel_close_issue",
            return_value=None,
        ), patch(
            "bridge.services.factory_orchestrator._run_gh",
            return_value=(0, "[]", ""),
        ):
            tick = await orch.tick()
        # Implement runner received base_branch = integration ref.
        assert implement_runner.call_count == 1
        kwargs = implement_runner.call_args.kwargs
        assert (
            kwargs.get("base_branch")
            == "factory/channel/export-redesign/integration"
        )
        assert tick.error is None
        assert len(tick.issues_processed) == 1

    async def test_channel_close_issue_triggers_fast_forward(
        self, tmp_path: Path
    ):
        orch, implement_runner = _make_orchestrator(
            tmp_path, channels_enabled=True,
        )
        ff_mock = MagicMock(return_value=True)
        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[
                {
                    "number": 42,
                    "title": "Close channel: export-redesign",
                    "body": "...",
                    "labels": [
                        {"name": "factory:accepted"},
                        {"name": "factory:channel-close:export-redesign"},
                    ],
                }
            ],
        ), patch(
            "bridge.services.factory_orchestrator._gh_issue_comment"
        ), patch(
            "bridge.services.factory_orchestrator.transition_state",
            return_value=True,
        ), patch(
            "bridge.services.factory_orchestrator."
            "_gh_fast_forward_integration_to_main",
            ff_mock,
        ):
            tick = await orch.tick()
        # Fast-forward called exactly once with the right channel.
        assert ff_mock.call_count == 1
        chan_arg = ff_mock.call_args.args[0]
        assert chan_arg.name == "export-redesign"
        # Implement pipeline NOT invoked for channel-close issues.
        assert implement_runner.call_count == 0
        ipr = tick.issues_processed[0]
        assert ipr.final_state == FactoryState.NEEDS_REVIEW.value

    async def test_channels_disabled_ignores_channel_labels(
        self, tmp_path: Path
    ):
        orch, implement_runner = _make_orchestrator(
            tmp_path, channels_enabled=False,
        )
        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[
                {
                    "number": 7,
                    "title": "channel-attached but flag off",
                    "body": "y",
                    "labels": [
                        {"name": "factory:accepted"},
                        {"name": "factory:channel:export-redesign"},
                    ],
                }
            ],
        ), patch(
            "bridge.services.factory_orchestrator._gh_pr_diff",
            return_value="diff",
        ), patch(
            "bridge.services.factory_orchestrator._gh_issue_comment"
        ), patch(
            "bridge.services.factory_orchestrator._gh_pr_ready_for_review"
        ), patch(
            "bridge.services.factory_orchestrator.transition_state",
            return_value=True,
        ):
            tick = await orch.tick()
        # base_branch NOT injected — implement runner called only with
        # ``repo`` (legacy behaviour). Assert no channel-only kwargs leak in.
        assert implement_runner.call_count == 1
        kwargs = implement_runner.call_args.kwargs
        assert "base_branch" not in kwargs
        assert tick.error is None

    async def test_multi_channel_label_routes_to_needs_human(
        self, tmp_path: Path
    ):
        orch, implement_runner = _make_orchestrator(
            tmp_path, channels_enabled=True,
        )
        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[
                {
                    "number": 7,
                    "title": "two channels",
                    "body": "y",
                    "labels": [
                        {"name": "factory:accepted"},
                        {"name": "factory:channel:a"},
                        {"name": "factory:channel:b"},
                    ],
                }
            ],
        ):
            tick = await orch.tick()
        assert implement_runner.call_count == 0
        assert len(tick.issues_processed) == 1
        ipr = tick.issues_processed[0]
        assert ipr.final_state == FactoryState.NEEDS_HUMAN.value
        assert ipr.error is not None and "multiple" in ipr.error.lower()

    async def test_channel_member_files_close_issue_when_last_member_done(
        self, tmp_path: Path
    ):
        orch, _implement_runner = _make_orchestrator(
            tmp_path, channels_enabled=True,
        )
        create_mock = MagicMock(return_value=4242)
        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[
                {
                    "number": 7,
                    "title": "last member",
                    "body": "y",
                    "labels": [
                        {"name": "factory:accepted"},
                        {"name": "factory:channel:rubric"},
                    ],
                }
            ],
        ), patch(
            "bridge.services.factory_orchestrator._gh_pr_diff",
            return_value="diff",
        ), patch(
            "bridge.services.factory_orchestrator._gh_issue_comment"
        ), patch(
            "bridge.services.factory_orchestrator._gh_pr_ready_for_review"
        ), patch(
            "bridge.services.factory_orchestrator.transition_state",
            return_value=True,
        ), patch(
            "bridge.services.factory_orchestrator._gh_branch_exists",
            return_value=True,
        ), patch(
            "bridge.services.factory_orchestrator."
            "_gh_list_open_issues_with_labels",
            # Only the issue we just processed is open; gets dropped before
            # the close-readiness check.
            return_value={
                7: ["factory:accepted", "factory:channel:rubric"],
            },
        ), patch(
            "bridge.services.factory_orchestrator."
            "_gh_create_channel_close_issue",
            create_mock,
        ), patch(
            "bridge.services.factory_orchestrator._run_gh",
            return_value=(0, "[]", ""),
        ):
            tick = await orch.tick()
        assert tick.error is None
        # Last member → close issue filed.
        assert create_mock.call_count == 1
        kwargs = create_mock.call_args.kwargs
        assert kwargs["channel"].name == "rubric"

    async def test_channel_member_skips_close_when_other_open_members(
        self, tmp_path: Path
    ):
        orch, _impl = _make_orchestrator(tmp_path, channels_enabled=True)
        create_mock = MagicMock(return_value=4242)
        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[
                {
                    "number": 7,
                    "title": "not last",
                    "body": "y",
                    "labels": [
                        {"name": "factory:accepted"},
                        {"name": "factory:channel:rubric"},
                    ],
                }
            ],
        ), patch(
            "bridge.services.factory_orchestrator._gh_pr_diff",
            return_value="diff",
        ), patch(
            "bridge.services.factory_orchestrator._gh_issue_comment"
        ), patch(
            "bridge.services.factory_orchestrator._gh_pr_ready_for_review"
        ), patch(
            "bridge.services.factory_orchestrator.transition_state",
            return_value=True,
        ), patch(
            "bridge.services.factory_orchestrator._gh_branch_exists",
            return_value=True,
        ), patch(
            "bridge.services.factory_orchestrator."
            "_gh_list_open_issues_with_labels",
            # Issue 8 still open in the same channel — close NOT ready.
            return_value={
                7: ["factory:accepted", "factory:channel:rubric"],
                8: ["factory:accepted", "factory:channel:rubric"],
            },
        ), patch(
            "bridge.services.factory_orchestrator."
            "_gh_create_channel_close_issue",
            create_mock,
        ):
            tick = await orch.tick()
        assert tick.error is None
        # No close issue filed because #8 still open in the same channel.
        assert create_mock.call_count == 0
