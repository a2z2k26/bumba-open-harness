"""Multi-agent Board of Directors.

Each agent has a reasoning framework and system prompt. The board meeting
pattern invokes all agents sequentially, then synthesizes their responses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from bridge.dispatch_metrics import increment_module_counter

log = logging.getLogger(__name__)


@dataclass
class AgentProfile:
    """Definition of an agent persona."""

    name: str
    description: str
    system_prompt: str
    reasoning_framework: str  # "ToT", "CoT", "DevAdv", "ReAct"


@dataclass
class AgentResponse:
    """Response from a single agent."""

    agent_name: str
    response: str
    framework: str


@dataclass
class BoardResult:
    """Synthesized result from a board meeting."""

    responses: list[AgentResponse] = field(default_factory=list)
    synthesis: str = ""
    question: str = ""

    def format_for_display(self) -> str:
        """Format the board result for operator display."""
        lines = [f"**Board Meeting: {self.question}**\n"]
        for resp in self.responses:
            lines.append(f"**{resp.agent_name}** ({resp.framework}):")
            lines.append(resp.response)
            lines.append("")
        if self.synthesis:
            lines.append("**Synthesis:**")
            lines.append(self.synthesis)
        return "\n".join(lines)


# Built-in agent profiles
_DEFAULT_AGENTS: dict[str, AgentProfile] = {
    "strategist": AgentProfile(
        name="Strategist",
        description="Long-term thinking, explores multiple paths",
        system_prompt=(
            "You are the Strategist agent. Use Tree of Thought (ToT) reasoning. "
            "For each question, generate 2-3 possible approaches, evaluate each "
            "for pros/cons, then recommend the best path forward. Think about "
            "long-term implications and scalability."
        ),
        reasoning_framework="ToT",
    ),
    "analyst": AgentProfile(
        name="Analyst",
        description="Systematic step-by-step analysis",
        system_prompt=(
            "You are the Analyst agent. Use Chain of Thought (CoT) reasoning. "
            "Break down the problem step by step. Show your reasoning process "
            "explicitly. Focus on data, evidence, and logical progression."
        ),
        reasoning_framework="CoT",
    ),
    "critic": AgentProfile(
        name="Critic",
        description="Devil's advocate, finds flaws and risks",
        system_prompt=(
            "You are the Critic agent. Play Devil's Advocate. "
            "Challenge assumptions, identify risks, edge cases, and potential "
            "failures. Point out what could go wrong. Be constructive but "
            "thorough in finding weaknesses."
        ),
        reasoning_framework="DevAdv",
    ),
    "researcher": AgentProfile(
        name="Researcher",
        description="Information gathering and fact-checking",
        system_prompt=(
            "You are the Researcher agent. Use ReAct (Reason + Act) framework. "
            "Think about what information is needed, what tools to use, and "
            "what to verify. Focus on gathering relevant facts and context "
            "before making recommendations."
        ),
        reasoning_framework="ReAct",
    ),
}


class AgentRouter:
    """Routes questions to specialist agents and orchestrates board meetings."""

    def __init__(
        self,
        max_depth: int = 3,
        agents: dict[str, AgentProfile] | None = None,
    ) -> None:
        self._max_depth = max_depth
        self._agents = agents or dict(_DEFAULT_AGENTS)

    @property
    def available_agents(self) -> list[str]:
        """List of available agent names."""
        return list(self._agents.keys())

    def get_agent(self, name: str) -> AgentProfile | None:
        """Get an agent profile by name."""
        return self._agents.get(name.lower())

    def invoke_agent(
        self,
        name: str,
        message: str,
        context: str = "",
        depth: int = 0,
    ) -> AgentResponse:
        """Invoke a single agent with a message.

        In production, this would call Claude via subprocess with the
        agent's system prompt. For now, returns a structured prompt
        that can be passed to Claude.

        Args:
            name: Agent name (strategist, analyst, critic, researcher)
            message: The question or task
            context: Additional context
            depth: Current invocation depth (prevents infinite loops)
        """
        if depth >= self._max_depth:
            return AgentResponse(
                agent_name=name,
                response=f"[Max invocation depth ({self._max_depth}) reached]",
                framework="none",
            )

        agent = self._agents.get(name.lower())
        if not agent:
            return AgentResponse(
                agent_name=name,
                response=f"Unknown agent: {name}",
                framework="none",
            )

        # Build the prompt for Claude invocation
        prompt = f"{agent.system_prompt}\n\n"
        if context:
            prompt += f"Context:\n{context}\n\n"
        prompt += f"Question:\n{message}"

        log.info("Agent '%s' invoked (depth=%d): %s", name, depth, message[:80])

        return AgentResponse(
            agent_name=agent.name,
            response=prompt,
            framework=agent.reasoning_framework,
        )

    def board_meeting(self, question: str, context: str = "") -> BoardResult:
        """Run a board meeting — all agents weigh in, then synthesize.

        Returns BoardResult with individual responses and synthesis prompt.
        """
        result = BoardResult(question=question)

        for name, agent in self._agents.items():
            response = self.invoke_agent(name, question, context)
            result.responses.append(response)

        # Build synthesis prompt (the "general" orchestrator)
        synthesis_parts = [
            "You are the General Orchestrator. You've received input from "
            "all board members. Synthesize their perspectives into a final "
            "recommendation.\n",
            f"Question: {question}\n",
        ]
        for resp in result.responses:
            synthesis_parts.append(
                f"--- {resp.agent_name} ({resp.framework}) ---\n{resp.response}\n"
            )
        synthesis_parts.append(
            "\nProvide a clear, actionable recommendation that weighs "
            "all perspectives. Highlight key points of agreement and "
            "areas where the board disagrees."
        )
        result.synthesis = "\n".join(synthesis_parts)

        log.info("Board meeting completed for: %s (%d agents)", question[:60], len(result.responses))
        return result

    def get_board_prompt(self, question: str, context: str = "") -> str:
        increment_module_counter("agent_router.get_board_prompt", tier=3)
        """Get the full board meeting prompt for Claude invocation.

        This is the prompt that should be sent to Claude to get
        the synthesized board response.
        """
        meeting = self.board_meeting(question, context)
        return meeting.synthesis
