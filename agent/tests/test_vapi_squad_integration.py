"""Integration tests for VAPI squad — end-to-end squad construction and validation."""
from __future__ import annotations

import pytest

from bridge.voice.vapi_squad import build_bumba_squad
from bridge.voice.department_prompts import DEPARTMENT_PROMPTS
from bridge.voice.department_tools import DepartmentToolHandler
from bridge.voice.vapi_tool_registry import VAPI_TOOLS


class TestSquadHasEntryAssistant:
    """#90: Verify squad has a receptionist as the entry assistant."""

    def test_entry_assistant_exists_in_squad(self):
        squad = build_bumba_squad()
        entry_ids = {a.assistant_id for a in squad.assistants}
        assert squad.entry_assistant_id in entry_ids

    def test_entry_assistant_is_receptionist(self):
        squad = build_bumba_squad()
        entry = next(a for a in squad.assistants if a.assistant_id == squad.entry_assistant_id)
        assert entry.department == "receptionist"


class TestSquadHasFourAssistants:
    """#90: Verify squad has exactly 4 assistants."""

    def test_total_count(self):
        squad = build_bumba_squad()
        assert len(squad.assistants) == 4

    def test_all_departments_present(self):
        squad = build_bumba_squad()
        departments = {a.department for a in squad.assistants}
        assert departments == {"receptionist", "engineering", "qa", "ops"}


class TestDepartmentAssistantsHaveTools:
    """#91: Verify each department assistant has at least one tool."""

    def test_all_have_tools(self):
        squad = build_bumba_squad()
        for asst in squad.assistants:
            assert len(asst.tools) > 0, f"{asst.department} has no tools"

    def test_engineering_has_expected_tools(self):
        squad = build_bumba_squad()
        eng = next(a for a in squad.assistants if a.department == "engineering")
        assert "get_pr_status" in eng.tools
        assert "run_tests" in eng.tools

    def test_ops_has_expected_tools(self):
        squad = build_bumba_squad()
        ops = next(a for a in squad.assistants if a.department == "ops")
        assert "check_mcp_health" in ops.tools
        assert "get_system_status" in ops.tools


class TestFrozenDataclasses:
    """#90: Verify all dataclasses are immutable."""

    def test_assistant_immutable(self):
        squad = build_bumba_squad()
        asst = squad.assistants[0]
        with pytest.raises(AttributeError):
            asst.name = "modified"  # type: ignore[misc]

    def test_squad_immutable(self):
        squad = build_bumba_squad()
        with pytest.raises(AttributeError):
            squad.name = "modified"  # type: ignore[misc]


class TestDepartmentPromptsExist:
    """#91: Verify prompts exist for all departments in the squad."""

    def test_all_squad_departments_have_prompts(self):
        squad = build_bumba_squad()
        for asst in squad.assistants:
            assert asst.department in DEPARTMENT_PROMPTS, (
                f"No prompt for department: {asst.department}"
            )

    def test_prompts_match_squad_assignments(self):
        """Each assistant's system_prompt should match the department prompt."""
        squad = build_bumba_squad()
        for asst in squad.assistants:
            expected = DEPARTMENT_PROMPTS[asst.department]
            assert asst.system_prompt == expected, (
                f"{asst.department} prompt mismatch"
            )


class TestToolHandlerIntegration:
    """Every advertised squad tool must resolve to either real read-only data,
    a shaped dependency/input failure, or a capability-gated ``not_wired``
    payload.
    """

    @pytest.mark.asyncio
    async def test_all_squad_tools_are_handled(self):
        squad = build_bumba_squad()
        handler = DepartmentToolHandler()

        # Collect all unique tools declared across all assistants
        # (skip transfer_to_department — VAPI routing action, not a
        # bridge-side handler; tracked separately by the registry).
        all_tools = set()
        for asst in squad.assistants:
            for tool in asst.tools:
                if tool != "transfer_to_department":
                    all_tools.add((asst.department, tool))

        for dept, tool in all_tools:
            result = await handler.handle_tool_call(dept, tool, {})
            spec = VAPI_TOOLS[tool]
            if spec.implemented:
                assert result.get("status") != "not_wired"
                assert result.get("owner_issue") is None
                if result["success"] is False:
                    assert result.get("status") in {
                        "invalid_request",
                        "unavailable",
                        "timeout",
                        "error",
                    }, (
                        f"Implemented tool {tool} failed with an unshaped "
                        f"status for {dept}: {result!r}"
                    )
            else:
                assert result["success"] is False, (
                    f"Tool {tool} unexpectedly returned success=True for {dept}"
                )
                assert result.get("status") == "not_wired", (
                    f"Tool {tool} returned success=False but without the "
                    f"not_wired marker for {dept}: {result!r}"
                )
                assert result.get("owner_issue"), (
                    f"Tool {tool} missing owner_issue for {dept}: {result!r}"
                )
                assert result.get("backend"), (
                    f"Tool {tool} missing backend for {dept}: {result!r}"
                )
            assert result.get("department") == dept
