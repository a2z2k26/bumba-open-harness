"""VAPI Squad architecture — frozen dataclass models and squad builder."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .department_prompts import DEPARTMENT_PROMPTS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VAPIAssistant:
    """A single VAPI assistant within a squad."""

    assistant_id: str
    name: str
    department: str
    system_prompt: str
    tools: list[str]
    model: str = "gpt-4"


@dataclass(frozen=True)
class VAPISquad:
    """A VAPI squad — a group of assistants with a designated entry point."""

    squad_id: str
    name: str
    entry_assistant_id: str
    assistants: list[VAPIAssistant]


def build_bumba_squad() -> VAPISquad:
    """Build the default Bumba voice squad with receptionist + 3 department agents.

    Returns a VAPISquad with:
    - Receptionist (entry point): routes calls to the right department
    - Engineering: handles code, PR, deployment questions
    - QA: handles testing, quality, and validation questions
    - Ops: handles infrastructure, monitoring, and system health questions
    """
    receptionist = VAPIAssistant(
        assistant_id="bumba-receptionist",
        name="Bumba Receptionist",
        department="receptionist",
        system_prompt=DEPARTMENT_PROMPTS["receptionist"],
        tools=["transfer_to_department", "get_system_status"],
        model="gpt-4",
    )

    engineering = VAPIAssistant(
        assistant_id="bumba-engineering",
        name="Bumba Engineering",
        department="engineering",
        system_prompt=DEPARTMENT_PROMPTS["engineering"],
        tools=["get_pr_status", "run_tests", "list_active_sessions"],
        model="gpt-4",
    )

    qa = VAPIAssistant(
        assistant_id="bumba-qa",
        name="Bumba QA",
        department="qa",
        system_prompt=DEPARTMENT_PROMPTS["qa"],
        tools=["run_tests", "get_pr_status"],
        model="gpt-4",
    )

    ops = VAPIAssistant(
        assistant_id="bumba-ops",
        name="Bumba Ops",
        department="ops",
        system_prompt=DEPARTMENT_PROMPTS["ops"],
        tools=["check_mcp_health", "get_system_status", "list_active_sessions"],
        model="gpt-4",
    )

    squad = VAPISquad(
        squad_id="bumba-voice-squad",
        name="Bumba Voice Squad",
        entry_assistant_id="bumba-receptionist",
        assistants=[receptionist, engineering, qa, ops],
    )

    logger.info(
        "Built Bumba voice squad: %d assistants, entry=%s",
        len(squad.assistants),
        squad.entry_assistant_id,
    )
    return squad
