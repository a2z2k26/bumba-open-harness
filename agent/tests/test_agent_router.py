"""Tests for bridge.agent_router (Multi-Agent Board of Directors)."""

from __future__ import annotations

from bridge.agent_router import AgentProfile, AgentRouter, BoardResult


class TestAgentProfile:
    """Agent profile dataclass."""

    def test_create_profile(self):
        profile = AgentProfile(
            name="Test",
            description="A test agent",
            system_prompt="You are a test agent.",
            reasoning_framework="CoT",
        )
        assert profile.name == "Test"
        assert profile.reasoning_framework == "CoT"


class TestAgentRouter:
    """Agent routing and invocation."""

    def test_available_agents(self):
        router = AgentRouter()
        agents = router.available_agents
        assert "strategist" in agents
        assert "analyst" in agents
        assert "critic" in agents
        assert "researcher" in agents
        assert len(agents) == 4

    def test_get_agent(self):
        router = AgentRouter()
        agent = router.get_agent("strategist")
        assert agent is not None
        assert agent.name == "Strategist"
        assert agent.reasoning_framework == "ToT"

    def test_get_unknown_agent(self):
        router = AgentRouter()
        assert router.get_agent("nonexistent") is None

    def test_invoke_agent(self):
        router = AgentRouter()
        response = router.invoke_agent("analyst", "What is the best approach?")
        assert response.agent_name == "Analyst"
        assert response.framework == "CoT"
        assert "Chain of Thought" in response.response

    def test_invoke_unknown_agent(self):
        router = AgentRouter()
        response = router.invoke_agent("unknown", "test")
        assert "Unknown agent" in response.response

    def test_invoke_max_depth(self):
        router = AgentRouter(max_depth=2)
        response = router.invoke_agent("analyst", "test", depth=2)
        assert "Max invocation depth" in response.response

    def test_invoke_with_context(self):
        router = AgentRouter()
        response = router.invoke_agent(
            "strategist",
            "How should we scale?",
            context="Current: 100 users. Target: 10K users.",
        )
        assert "Current: 100 users" in response.response

    def test_custom_agents(self):
        custom = {
            "planner": AgentProfile(
                name="Planner",
                description="Plans things",
                system_prompt="You plan.",
                reasoning_framework="Custom",
            ),
        }
        router = AgentRouter(agents=custom)
        assert router.available_agents == ["planner"]


class TestBoardMeeting:
    """Board meeting orchestration."""

    def test_board_meeting_returns_all_agents(self):
        router = AgentRouter()
        result = router.board_meeting("Should we refactor the auth module?")
        assert len(result.responses) == 4
        names = [r.agent_name for r in result.responses]
        assert "Strategist" in names
        assert "Analyst" in names
        assert "Critic" in names
        assert "Researcher" in names

    def test_board_meeting_has_synthesis(self):
        router = AgentRouter()
        result = router.board_meeting("What's our priority?")
        assert result.synthesis != ""
        assert "General Orchestrator" in result.synthesis

    def test_board_meeting_stores_question(self):
        router = AgentRouter()
        result = router.board_meeting("Test question")
        assert result.question == "Test question"

    def test_board_result_format(self):
        result = BoardResult(
            question="Test?",
            responses=[],
            synthesis="Final answer",
        )
        formatted = result.format_for_display()
        assert "Board Meeting" in formatted
        assert "Test?" in formatted

    def test_get_board_prompt(self):
        router = AgentRouter()
        prompt = router.get_board_prompt("How to improve performance?")
        assert "General Orchestrator" in prompt
        assert "performance" in prompt
        assert "Strategist" in prompt
