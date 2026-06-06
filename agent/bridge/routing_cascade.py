"""
Routing Cascade — command routing (rules → semantic → explicit no-route).

Tier 1 (rules): fast prefix/keyword matching against department patterns.
Tier 2 (semantic): keyword overlap scoring between command and agent capabilities.
Tier 3 (LLM): unavailable until a real LLM router is configured.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from .modality_detector import ModalityDetector

# Note (#1537): RoutingCascade does department-keyword routing (see
# DEPARTMENT_PREFIXES below), not intent classification. It intentionally
# does NOT import CommandRouter or intent_classifier — that surface is owned
# by routing_brain.py for intent-based decisions. The two routers operate on
# orthogonal axes (department vs intent) and must stay decoupled.


# Department keyword prefixes for rules-based routing
DEPARTMENT_PREFIXES: Dict[str, List[str]] = {
    "engineering": ["build", "code", "fix", "deploy", "test"],
    "research": ["analyze", "research", "investigate"],
    "qa": ["verify", "check", "review", "audit"],
    "comms": ["draft", "write", "email", "message"],
    "planning": ["plan", "design", "architect", "roadmap"],
}


@dataclass
class RoutingDecision:
    """Result of a routing decision."""
    agent_id: str
    confidence: float
    tier_used: str          # "rules" | "semantic" | "llm"
    reasoning: str


class RoutingUnavailableError(RuntimeError):
    """Raised when no configured routing tier can select a real agent."""


class RoutingCascade:
    """
    Routes a command to an available agent via a 3-tier fallback cascade.

    Tier 1 — rules_routing:   checks department prefix keywords, confidence 0.9
    Tier 2 — semantic_routing: scores keyword overlap with agent capabilities, confidence 0.6-0.8
    Tier 3 — llm_routing:     fail-loud fence until a real router is configured
    """

    def __init__(self) -> None:
        self._modality_detector = ModalityDetector()

    def route(self, command: str, available_agents: List[Dict]) -> RoutingDecision:
        """
        Route command to the best available agent.

        available_agents is a list of dicts, each expected to have at minimum:
            {
                "agent_id": str,
                "department": str,          # optional
                "capabilities": list[str],  # optional
            }
        """
        decision = self._rules_routing(command, available_agents)
        if decision is not None:
            return decision

        decision = self._semantic_routing(command, available_agents)
        if decision is not None:
            return decision

        return self._llm_routing(command, available_agents)

    # ------------------------------------------------------------------
    # Tier 1 — rules
    # ------------------------------------------------------------------

    def _rules_routing(
        self, command: str, agents: List[Dict]
    ) -> Optional[RoutingDecision]:
        """
        Match command tokens against DEPARTMENT_PREFIXES.

        If a match is found, pick the first agent whose 'department' matches,
        falling back to the first agent in the list.
        """
        tokens = command.lower().split()
        matched_dept: Optional[str] = None

        for dept, keywords in DEPARTMENT_PREFIXES.items():
            for kw in keywords:
                if kw in tokens or command.lower().startswith(kw):
                    matched_dept = dept
                    break
            if matched_dept:
                break

        if matched_dept is None:
            return None

        target = self._find_agent_by_department(agents, matched_dept)
        if target is None:
            raise RoutingUnavailableError(
                f"No agent available for matched department '{matched_dept}'"
            )
        return RoutingDecision(
            agent_id=target,
            confidence=0.9,
            tier_used="rules",
            reasoning=f"Rules match: command token matched department '{matched_dept}'",
        )

    # ------------------------------------------------------------------
    # Tier 2 — semantic
    # ------------------------------------------------------------------

    def _semantic_routing(
        self, command: str, agents: List[Dict]
    ) -> Optional[RoutingDecision]:
        """
        Score each agent by keyword overlap between command and capabilities.

        Returns None if no agent scores above a minimum threshold.
        """
        if not agents:
            return None

        command_tokens = set(command.lower().split())
        best_agent_id: Optional[str] = None
        best_score = 0.0

        for agent in agents:
            caps = agent.get("capabilities", [])
            if not caps:
                continue
            cap_tokens = set(" ".join(caps).lower().split())
            overlap = len(command_tokens & cap_tokens)
            if cap_tokens:
                score = overlap / len(cap_tokens)
            else:
                score = 0.0
            if score > best_score:
                best_score = score
                best_agent_id = agent.get("agent_id", "")

        if best_agent_id is None or best_score == 0:
            return None

        # Scale confidence from 0.6 to 0.8 based on overlap score
        confidence = 0.6 + min(0.2, best_score * 0.4)
        return RoutingDecision(
            agent_id=best_agent_id,
            confidence=round(confidence, 3),
            tier_used="semantic",
            reasoning=(
                f"Semantic match: keyword overlap score {best_score:.3f} "
                f"with agent '{best_agent_id}'"
            ),
        )

    # ------------------------------------------------------------------
    # Tier 3 — LLM (stub)
    # ------------------------------------------------------------------

    def _llm_routing(
        self, command: str, agents: List[Dict]
    ) -> RoutingDecision:
        """
        Fail-loud fence for LLM-based routing.

        A real implementation must inject/configure an LLM router before this
        tier can select an agent. Defaulting to the first available agent would
        fabricate successful routing and send work to the wrong specialist.
        """
        raise RoutingUnavailableError(
            "No routing rule or semantic match found; LLM routing is not configured"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_agent_by_department(
        self, agents: List[Dict], department: str
    ) -> Optional[str]:
        """Return agent_id for the first agent matching the department."""
        for agent in agents:
            if agent.get("department", "").lower() == department.lower():
                return agent.get("agent_id", "unknown")
        return None
