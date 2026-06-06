"""Tests for Z4.0 — tool registration on department agents."""

from __future__ import annotations

import inspect

import pytest

from teams._factory import build_employee_agents, build_manager_agent
from teams._namespace import get_guard
from teams._tool_registry import (
    TOOL_CALLABLES,
    make_tracked,
    memory_recall,
    resolve_tools,
)
from tests.test_teams.conftest import make_deps
from teams._types import (
    AgentSpec,
    BridgeDeps,
    DepartmentConfig,
)


# ---------- fixtures ----------

@pytest.fixture(autouse=True)
def _clean_guard():
    """Reset the namespace guard before each test."""
    get_guard().clear()
    yield
    get_guard().clear()


def _make_config(
    name: str,
    common_tools: tuple[str, ...] = (),
    department_tools: tuple[str, ...] = (),
    per_employee_tools: dict[str, tuple[str, ...]] | None = None,
) -> DepartmentConfig:
    return DepartmentConfig(
        name=name,
        zone=4,
        description=f"{name} department",
        manager=AgentSpec(
            name=f"{name}-chief",
            model="anthropic:claude-opus-4-6",
            role=f"Orchestrates {name}",
        ),
        employees=(
            AgentSpec(
                name=f"{name}-worker-a",
                model="anthropic:claude-sonnet-4-6",
                role="Worker A",
            ),
        ),
        common_tools=common_tools,
        department_tools=department_tools,
        per_employee_tools=per_employee_tools or {},
    )


@pytest.fixture
def qa_config() -> DepartmentConfig:
    return _make_config(
        "qa",
        common_tools=("read_file", "search_knowledge", "memory_recall"),
        department_tools=("run_tests", "coverage_report", "security_scan"),
    )


@pytest.fixture
def strategy_config() -> DepartmentConfig:
    return _make_config(
        "strategy",
        common_tools=("read_file", "search_knowledge", "memory_recall"),
        department_tools=("search_market_data", "analyze_competitor", "recall_decision"),
    )


@pytest.fixture
def board_config() -> DepartmentConfig:
    return _make_config(
        "board",
        common_tools=("search_knowledge", "recall_decision"),
        department_tools=("recall_past_decisions",),
    )


@pytest.fixture
def bridge_deps() -> BridgeDeps:
    return make_deps(session_id="test-reg", department="qa")


# ---------- TOOL_CALLABLES coverage ----------

class TestToolCallables:
    def test_all_implemented_tools_present(self):
        expected = {
            "read_file", "search_knowledge", "memory_recall",
            "pending_handoffs",
            # job_search
            "scrape_boards", "score_and_deduplicate", "generate_cover_letter",
            "stage_listing_to_notion", "get_approved_listings", "update_notion_status",
            "send_discord_alert", "research_contacts",
            # qa
            "run_tests", "coverage_report", "security_scan",
            # ops
            "check_service_status", "tail_log", "query_metrics",
            # strategy
            "search_market_data", "analyze_competitor", "recall_decision",
            "initiate_handoff", "continue_handoff",
            # design
            "search_design_system", "lookup_component", "recall_brand_guidelines",
            "check_wcag_contrast",
            # board
            "recall_past_decisions",
            # shared — LSP code-navigation tools (teams/tools/_lsp.py)
            "lsp_find_definition", "lsp_find_references", "lsp_diagnostics",
        }
        assert expected == set(TOOL_CALLABLES.keys())

    def test_all_callables_are_async(self):
        for name, fn in TOOL_CALLABLES.items():
            assert inspect.iscoroutinefunction(fn), f"{name} is not async"


# ---------- make_tracked signature preservation ----------

class TestMakeTracked:
    def test_preserves_function_name(self):
        from teams.tools._qa import run_tests
        wrapped = make_tracked(
            run_tests, department="qa", tool_name="run_tests"
        )
        assert wrapped.__name__ == "run_tests"

    def test_preserves_docstring(self):
        from teams.tools._qa import run_tests
        wrapped = make_tracked(
            run_tests, department="qa", tool_name="run_tests"
        )
        assert wrapped.__doc__ == run_tests.__doc__

    def test_preserves_signature_parameters(self):
        from teams.tools._qa import run_tests
        wrapped = make_tracked(
            run_tests, department="qa", tool_name="run_tests"
        )
        orig_sig = inspect.signature(run_tests)
        wrap_sig = inspect.signature(wrapped)
        assert list(orig_sig.parameters.keys()) == list(wrap_sig.parameters.keys())

    def test_preserves_annotations(self):
        from teams.tools._design import check_wcag_contrast
        wrapped = make_tracked(
            check_wcag_contrast, department="design", tool_name="check_wcag_contrast"
        )
        assert wrapped.__annotations__ == check_wcag_contrast.__annotations__


# ---------- resolve_tools ----------

class TestResolveTools:
    def test_resolves_known_tools(self):
        pairs = resolve_tools(("run_tests", "security_scan"), "qa")
        names = [n for n, _ in pairs]
        assert names == ["run_tests", "security_scan"]

    def test_skips_unknown_tools(self, caplog):
        pairs = resolve_tools(("run_tests", "nonexistent_tool"), "qa")
        names = [n for n, _ in pairs]
        assert names == ["run_tests"]
        assert "nonexistent_tool" in caplog.text

    def test_registers_with_namespace_guard(self):
        resolve_tools(("run_tests",), "qa")
        assert "run_tests" in get_guard().list_tools("qa")

    def test_empty_tuple_returns_empty(self):
        pairs = resolve_tools((), "qa")
        assert pairs == []


# ---------- factory integration ----------

class TestManagerToolRegistration:
    def test_qa_manager_has_run_tests(self, qa_config):
        employees = build_employee_agents(qa_config)
        manager = build_manager_agent(qa_config, employees)
        tool_names = list(manager._function_toolset.tools.keys())
        assert "run_tests" in tool_names

    def test_qa_manager_has_delegation_tools(self, qa_config):
        """Sprint 19: chiefs expose unified `delegate` + `list_specialists`,
        not per-specialist `delegate_to_<name>` tools."""
        employees = build_employee_agents(qa_config)
        manager = build_manager_agent(qa_config, employees)
        tool_names = list(manager._function_toolset.tools.keys())
        assert "delegate" in tool_names
        assert "list_specialists" in tool_names
        # No per-specialist tools should remain on the chief
        assert not any(t.startswith("delegate_to_") for t in tool_names)

    def test_strategy_manager_has_search_market_data(self, strategy_config):
        employees = build_employee_agents(strategy_config)
        manager = build_manager_agent(strategy_config, employees)
        tool_names = list(manager._function_toolset.tools.keys())
        assert "search_market_data" in tool_names

    def test_board_manager_has_recall_past_decisions(self, board_config):
        employees = build_employee_agents(board_config)
        manager = build_manager_agent(board_config, employees)
        tool_names = list(manager._function_toolset.tools.keys())
        assert "recall_past_decisions" in tool_names


class TestEmployeeToolRegistration:
    def test_qa_employee_has_common_tools(self, qa_config):
        employees = build_employee_agents(qa_config)
        agent = employees["qa-worker-a"]
        tool_names = list(agent._function_toolset.tools.keys())
        assert "read_file" in tool_names
        assert "search_knowledge" in tool_names

    def test_qa_employee_has_department_tools(self, qa_config):
        employees = build_employee_agents(qa_config)
        agent = employees["qa-worker-a"]
        tool_names = list(agent._function_toolset.tools.keys())
        assert "run_tests" in tool_names


class TestMemoryRecall:
    @pytest.mark.asyncio
    async def test_returns_value_from_store(self):
        class FakeStore:
            async def get(self, key):
                return "found-value" if key == "test-key" else None

        deps = make_deps(
            session_id="test",
            department="qa",
            memory_store=FakeStore(),
        )

        class FakeCtx:
            def __init__(self, deps):
                self.deps = deps

        result = await memory_recall(FakeCtx(deps), "test-key")
        assert result == "found-value"

    @pytest.mark.asyncio
    async def test_returns_not_found_for_missing_key(self):
        class FakeStore:
            async def get(self, key):
                return None

        deps = make_deps(
            session_id="test",
            department="qa",
            memory_store=FakeStore(),
        )

        class FakeCtx:
            def __init__(self, deps):
                self.deps = deps

        result = await memory_recall(FakeCtx(deps), "missing")
        assert "No entry found" in result

        result = await memory_recall(FakeCtx(deps), "any")
        assert "No entry found" in result
