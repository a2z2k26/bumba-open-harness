"""Fail-loud guards for orchestration routing fallback behavior."""

from __future__ import annotations

import pytest

from bridge.routing_cascade import RoutingCascade, RoutingUnavailableError


def test_rules_route_to_matching_department_agent() -> None:
    cascade = RoutingCascade()
    decision = cascade.route(
        "fix the failing deploy",
        [
            {
                "agent_id": "qa-01",
                "department": "qa",
                "capabilities": ["review"],
            },
            {
                "agent_id": "eng-01",
                "department": "engineering",
                "capabilities": ["fix"],
            },
        ],
    )

    assert decision.agent_id == "eng-01"
    assert decision.tier_used == "rules"


def test_rules_route_does_not_fallback_to_first_agent_when_department_missing() -> None:
    cascade = RoutingCascade()

    with pytest.raises(RoutingUnavailableError, match="engineering"):
        cascade.route(
            "fix the failing deploy",
            [
                {
                    "agent_id": "qa-01",
                    "department": "qa",
                    "capabilities": ["review"],
                }
            ],
        )


def test_tier3_no_match_raises_no_route_instead_of_selecting_first_agent() -> None:
    cascade = RoutingCascade()

    with pytest.raises(RoutingUnavailableError, match="No routing rule"):
        cascade.route(
            "summarize contract language",
            [
                {
                    "agent_id": "eng-01",
                    "department": "engineering",
                    "capabilities": ["build", "deploy"],
                },
                {
                    "agent_id": "qa-01",
                    "department": "qa",
                    "capabilities": ["test", "audit"],
                },
            ],
        )
