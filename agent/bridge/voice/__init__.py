"""VAPI Voice Squads — voice-first agent teams with department routing."""
from __future__ import annotations

from .vapi_squad import VAPIAssistant, VAPISquad, build_bumba_squad
from .department_prompts import DEPARTMENT_PROMPTS
from .department_tools import DepartmentToolHandler

__all__ = [
    "VAPIAssistant",
    "VAPISquad",
    "build_bumba_squad",
    "DEPARTMENT_PROMPTS",
    "DepartmentToolHandler",
]
