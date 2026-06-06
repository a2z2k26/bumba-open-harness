"""Tests for ``Constraints.usage_limits`` → pydantic-ai ``UsageLimits`` wiring (#1970).

Pre-#1970, ``Constraints.request_limit`` / ``request_token_limit`` /
``response_token_limit`` were loaded from YAML into the dataclass but never
threaded into ``Agent.run()``. The runtime fell back to pydantic-ai's
library default (``request_limit=50``), silently ignoring the operator-
declared caps. This was the next-step blocker after #1963 — exposed when
the first real ``/board`` smoke after the OpenRouter wiring landed tripped
``UsageLimitExceeded`` at 50 requests.

Two layers of coverage:

1. ``_resolve_usage_limits`` unit tests — pin the Constraints → UsageLimits
   mapping and the zero/negative → None convention.
2. End-to-end test asserting ``manager.run`` is invoked with the resolved
   ``UsageLimits`` so a future refactor cannot quietly drop the wiring.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.usage import UsageLimits

from teams._team import DepartmentTeam, _resolve_usage_limits
from teams._types import (
    AgentSpec,
    Constraints,
    DepartmentConfig,
)
from tests.test_teams.conftest import make_deps


class TestResolveUsageLimits:
    def test_request_limit_threaded_through(self) -> None:
        constraints = Constraints(
            request_limit=150,
            request_token_limit=100_000,
            response_token_limit=40_000,
        )
        ul = _resolve_usage_limits(constraints)
        assert isinstance(ul, UsageLimits)
        assert ul.request_limit == 150

    def test_request_token_limit_maps_to_input_tokens_limit(self) -> None:
        # pydantic-ai 1.80 renamed request_tokens_limit → input_tokens_limit;
        # we map the existing Constraints field name to the new kwarg.
        constraints = Constraints(request_token_limit=100_000)
        ul = _resolve_usage_limits(constraints)
        assert ul.input_tokens_limit == 100_000

    def test_response_token_limit_maps_to_output_tokens_limit(self) -> None:
        constraints = Constraints(response_token_limit=40_000)
        ul = _resolve_usage_limits(constraints)
        assert ul.output_tokens_limit == 40_000

    def test_zero_request_limit_becomes_none(self) -> None:
        # Zero means "no cap" by the existing cost_limit_usd convention
        # in this codebase. Pydantic-ai treats None as uncapped.
        constraints = Constraints(request_limit=0)
        ul = _resolve_usage_limits(constraints)
        assert ul.request_limit is None

    def test_negative_request_limit_becomes_none(self) -> None:
        constraints = Constraints(request_limit=-1)
        ul = _resolve_usage_limits(constraints)
        assert ul.request_limit is None

    def test_default_constraints_produce_capped_usage_limits(self) -> None:
        # The Constraints dataclass defaults (request_limit=20,
        # request_token_limit=250_000, response_token_limit=250_000) are
        # the production board-parity ceilings; confirm they survive.
        constraints = Constraints()
        ul = _resolve_usage_limits(constraints)
        assert ul.request_limit == 20
        assert ul.input_tokens_limit == 250_000
        assert ul.output_tokens_limit == 250_000


class TestManagerRunReceivesUsageLimits:
    """End-to-end: confirm DepartmentTeam.run passes the resolved
    UsageLimits to the chief's pydantic-ai Agent.run() call. This is the
    test that would have caught #1970 in the first place — the helper
    above is necessary but not sufficient; the wiring at the call site
    is the load-bearing part."""

    @pytest.fixture
    def department_with_strict_caps(self) -> DepartmentConfig:
        return DepartmentConfig(
            name="test-dept",
            zone=4,
            description="Test fixture",
            manager=AgentSpec(
                name="test-chief",
                model="anthropic:claude-opus-4-6",
                role="Orchestrates",
            ),
            employees=(
                AgentSpec(
                    name="test-worker",
                    model="anthropic:claude-sonnet-4-6",
                    role="Worker",
                ),
            ),
            constraints=Constraints(
                request_limit=42,
                request_token_limit=12345,
                response_token_limit=6789,
                timeout_seconds=10,
                cost_limit_usd=10.0,
            ),
        )

    @pytest.mark.asyncio
    async def test_manager_run_called_with_resolved_usage_limits(
        self, department_with_strict_caps: DepartmentConfig
    ) -> None:
        team = DepartmentTeam(department_with_strict_caps, lazy_build=False)
        deps = make_deps(session_id="t1", department="test-dept")

        # Patch the manager Agent's run method so we can inspect what
        # kwargs it receives. We don't care about the result here —
        # only that usage_limits was threaded through.
        captured_kwargs: dict = {}

        async def fake_run(prompt, **kwargs):
            captured_kwargs.update(kwargs)
            mock_result = MagicMock()
            mock_result.usage = lambda: None
            mock_result.output = MagicMock(
                answer="ok",
                rationale="",
                evidence=[],
                next_actions=[],
            )
            # Make output dump as a dict-like
            mock_result.output.model_dump = lambda: {
                "answer": "ok",
                "rationale": "",
                "evidence": [],
                "next_actions": [],
            }
            return mock_result

        with patch.object(team.manager, "run", new=AsyncMock(side_effect=fake_run)):
            await team.run("test task", deps=deps)

        assert "usage_limits" in captured_kwargs, (
            "DepartmentTeam.run must pass usage_limits to manager.run() — "
            "#1970 regression check"
        )
        resolved = captured_kwargs["usage_limits"]
        assert isinstance(resolved, UsageLimits)
        assert resolved.request_limit == 42
        assert resolved.input_tokens_limit == 12345
        assert resolved.output_tokens_limit == 6789
