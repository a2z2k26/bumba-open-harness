"""Unit tests for voice package — vapi_squad, department_prompts, department_tools."""
from __future__ import annotations

import pytest

from bridge.voice.vapi_squad import VAPIAssistant, VAPISquad, build_bumba_squad
from bridge.voice.department_prompts import DEPARTMENT_PROMPTS
from bridge.voice.department_tools import DepartmentToolHandler


# ---------------------------------------------------------------------------
# vapi_squad
# ---------------------------------------------------------------------------

class TestVAPIAssistant:
    def test_frozen(self):
        asst = VAPIAssistant(
            assistant_id="test",
            name="Test",
            department="test",
            system_prompt="prompt",
            tools=["tool1"],
        )
        with pytest.raises(AttributeError):
            asst.name = "other"  # type: ignore[misc]

    def test_default_model(self):
        asst = VAPIAssistant(
            assistant_id="test",
            name="Test",
            department="test",
            system_prompt="prompt",
            tools=[],
        )
        assert asst.model == "gpt-4"

    def test_custom_model(self):
        asst = VAPIAssistant(
            assistant_id="test",
            name="Test",
            department="test",
            system_prompt="prompt",
            tools=[],
            model="gpt-4o",
        )
        assert asst.model == "gpt-4o"


class TestVAPISquad:
    def test_frozen(self):
        squad = VAPISquad(
            squad_id="test",
            name="Test Squad",
            entry_assistant_id="entry",
            assistants=[],
        )
        with pytest.raises(AttributeError):
            squad.name = "other"  # type: ignore[misc]


class TestBuildBumbaSquad:
    def test_returns_squad(self):
        squad = build_bumba_squad()
        assert isinstance(squad, VAPISquad)

    def test_has_four_assistants(self):
        squad = build_bumba_squad()
        assert len(squad.assistants) == 4

    def test_entry_is_receptionist(self):
        squad = build_bumba_squad()
        assert squad.entry_assistant_id == "bumba-receptionist"

    def test_departments_covered(self):
        squad = build_bumba_squad()
        departments = {a.department for a in squad.assistants}
        assert departments == {"receptionist", "engineering", "qa", "ops"}

    def test_all_assistants_have_tools(self):
        squad = build_bumba_squad()
        for asst in squad.assistants:
            assert len(asst.tools) > 0

    def test_all_assistants_have_prompts(self):
        squad = build_bumba_squad()
        for asst in squad.assistants:
            assert len(asst.system_prompt) > 0

    def test_squad_id(self):
        squad = build_bumba_squad()
        assert squad.squad_id == "bumba-voice-squad"

    def test_assistant_ids_unique(self):
        squad = build_bumba_squad()
        ids = [a.assistant_id for a in squad.assistants]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# department_prompts
# ---------------------------------------------------------------------------

class TestDepartmentPrompts:
    def test_has_all_departments(self):
        expected = {"receptionist", "engineering", "qa", "ops"}
        assert set(DEPARTMENT_PROMPTS.keys()) == expected

    def test_prompts_are_nonempty_strings(self):
        for dept, prompt in DEPARTMENT_PROMPTS.items():
            assert isinstance(prompt, str), f"{dept} prompt is not a string"
            assert len(prompt) > 50, f"{dept} prompt is too short"

    def test_receptionist_mentions_routing(self):
        assert "route" in DEPARTMENT_PROMPTS["receptionist"].lower()

    def test_engineering_mentions_pr(self):
        prompt = DEPARTMENT_PROMPTS["engineering"].lower()
        assert "pull request" in prompt or "pr" in prompt

    def test_qa_mentions_tests(self):
        assert "test" in DEPARTMENT_PROMPTS["qa"].lower()

    def test_ops_mentions_health(self):
        assert "health" in DEPARTMENT_PROMPTS["ops"].lower()

    def test_all_mention_escalation(self):
        for dept, prompt in DEPARTMENT_PROMPTS.items():
            assert "escalation" in prompt.lower(), f"{dept} missing escalation rules"

    def test_all_mention_voice(self):
        for dept, prompt in DEPARTMENT_PROMPTS.items():
            assert "voice" in prompt.lower(), f"{dept} missing voice style guidance"


# ---------------------------------------------------------------------------
# department_tools
# ---------------------------------------------------------------------------

class TestDepartmentToolHandler:
    """Advertised department tools must return real data, shaped dependency
    failures, or loud invalid-request errors — never fabricated success."""

    @pytest.fixture
    def handler(self):
        return DepartmentToolHandler()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "department,tool_name,provider_kw,args",
        [
            (
                "engineering",
                "get_pr_status",
                "pr_status_provider",
                {"pr": 2410},
            ),
            ("qa", "run_tests", "test_runner_provider", {"lane": "fast"}),
            (
                "engineering",
                "list_active_sessions",
                "active_sessions_provider",
                {"limit": 3},
            ),
        ],
    )
    async def test_implemented_department_tools_return_real_status(
        self,
        department: str,
        tool_name: str,
        provider_kw: str,
        args: dict,
    ) -> None:
        async def provider(call_args):
            assert call_args == args
            return {"status": "ok"}

        handler = DepartmentToolHandler(**{provider_kw: provider})
        result = await handler.handle_tool_call(department, tool_name, args)

        assert result["success"] is True
        assert result["status"] == "ok"
        assert "owner_issue" not in result
        assert result["department"] == department
        assert result["tool"] == tool_name

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "department,tool_name",
        [
            ("ops", "check_mcp_health"),
            ("ops", "get_system_status"),
        ],
    )
    async def test_readonly_tools_return_real_status(
        self, handler, department: str, tool_name: str
    ) -> None:
        result = await handler.handle_tool_call(department, tool_name, {})

        assert result["success"] is True
        assert result["status"] != "not_wired"
        assert "owner_issue" not in result
        assert result["department"] == department
        assert result["tool"] == tool_name

    @pytest.mark.asyncio
    async def test_unknown_tool(self, handler):
        result = await handler.handle_tool_call("ops", "nonexistent_tool", {})
        assert result["success"] is False
        assert "Unknown tool" in result["error"]
        # Unknown tools still surface the calling department so traces
        # show which assistant attempted the call.
        assert result["department"] == "ops"

    @pytest.mark.asyncio
    async def test_department_tracked_in_result(self, handler):
        result = await handler.handle_tool_call("qa", "run_tests", {})
        assert result["department"] == "qa"
