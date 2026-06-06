"""Design-department model construction under the #2566 hybrid fleet.

History: this file originally pinned the #2301 prompt-caching cohort —
``design-visual-designer`` was the singular Claude/OpenRouter exception and
was constructed with ``CachingOpenRouterChatModel`` (a subclass that injects
``cache_control: {type: ephemeral}`` on the last system-prompt block), while
every other design specialist stayed on plain ``OpenAIChatModel``.

That premise is dead. The #2566 hybrid-fleet migration (fleet recovery #2595)
killed OpenRouter and moved EVERY design worker — visual-designer included —
to ``model: "codex-exec:"`` / ``adapter: "codex-exec"``. codex `exec` is a
local CLI subprocess (prose only, no tool-calling), so the factory builds a
``CodexExecModel`` for all seven specialists. There is no longer any
OpenRouter/Anthropic seat in the design roster, so no design agent constructs
``CachingOpenRouterChatModel`` and none carries a ``cache_control`` marker.

What we pin now: ALL design specialists build the same ``CodexExecModel``;
the "visual-designer is special" carve-out no longer exists in code.

The ``CachingOpenRouterChatModel`` seam itself still lives in
``teams/_factory.py`` (it fires only for ``openrouter:anthropic/*`` agents in
the ``_CACHE_CONTROL_AGENTS`` cohort, which design no longer populates). The
pure injection helper ``_annotate_last_system_block_with_cache_control`` is
still exercised directly by ``TestAnnotateLastSystemBlockHelper`` below —
those unit tests are unaffected by the fleet migration and stay as-is.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from teams._codex_model import CodexExecModel
from teams._config import load_department_config
from teams._factory import (
    _annotate_last_system_block_with_cache_control,
    build_employee_agents,
)


@pytest.fixture
def design_config():
    """Load the real ``agent/config/teams/design.yaml``.

    Post-#2566/#2595 every worker — including ``design-visual-designer`` —
    declares ``model: "codex-exec:"`` / ``adapter: "codex-exec"``.
    """
    repo_root = Path(__file__).parent.parent.parent
    yaml_path = repo_root / "config" / "teams" / "design.yaml"
    return load_department_config(yaml_path)


class TestDesignSpecialistModelConstruction:
    """Pin the #2566 hybrid-fleet reality: all design workers are codex-exec."""

    @pytest.mark.parametrize(
        "specialist_name",
        [
            "design-visual-designer",
            "design-ux-researcher",
            "design-prototyper",
            "design-ui-designer",
            "design-interaction-designer",
            "design-system-architect",
            "design-accessibility-specialist",
        ],
    )
    def test_all_design_specialists_use_codex_exec_model(
        self, design_config, specialist_name: str
    ) -> None:
        """Every design specialist builds a ``CodexExecModel``.

        The fleet migration (#2595) moved design-visual-designer — formerly
        the singular OpenRouter/Claude caching exception — onto codex-exec
        like the rest of the roster. There is no caching carve-out left to
        distinguish; all seven specialists construct identically.
        """
        employees = build_employee_agents(design_config)
        agent = employees[specialist_name]
        assert type(agent.model) is CodexExecModel, (
            f"{specialist_name} must build CodexExecModel under the #2566 "
            f"hybrid fleet (model: codex-exec:); got {type(agent.model)}"
        )


class TestAnnotateLastSystemBlockHelper:
    """Unit-level tests of the cache_control injection helper.

    The full ``_map_messages`` path is async + requires building the entire
    pydantic-ai request pipeline. These tests pin the pure helper that does
    the actual injection — fast, deterministic, no event loop.
    """

    def test_string_content_converted_to_structured_block(self) -> None:
        """A plain-string system message becomes a one-block list with cache_control."""
        mapped = [
            {"role": "system", "content": "You are a visual designer."},
            {"role": "user", "content": "Design a logo."},
        ]
        result = _annotate_last_system_block_with_cache_control(mapped)
        sys_msg = result[0]
        assert isinstance(sys_msg["content"], list)
        assert sys_msg["content"] == [
            {
                "type": "text",
                "text": "You are a visual designer.",
                "cache_control": {"type": "ephemeral"},
            }
        ]
        # User message untouched.
        assert result[1] == {"role": "user", "content": "Design a logo."}

    def test_existing_list_content_annotates_last_block(self) -> None:
        """If content is already a list, cache_control goes on the LAST block."""
        mapped = [
            {
                "role": "system",
                "content": [
                    {"type": "text", "text": "first"},
                    {"type": "text", "text": "second"},
                ],
            }
        ]
        result = _annotate_last_system_block_with_cache_control(mapped)
        blocks = result[0]["content"]
        assert "cache_control" not in blocks[0]
        assert blocks[1]["cache_control"] == {"type": "ephemeral"}

    def test_multiple_system_messages_annotates_last_one_only(self) -> None:
        """When there are multiple system messages, only the LAST gets marked.

        Anthropic's cache breakpoint goes at the END of the cacheable prefix,
        which corresponds to the final system block in the request.
        """
        mapped = [
            {"role": "system", "content": "instruction one"},
            {"role": "system", "content": "instruction two"},
            {"role": "user", "content": "do it"},
        ]
        result = _annotate_last_system_block_with_cache_control(mapped)
        # First system unchanged (still plain string)
        assert result[0] == {"role": "system", "content": "instruction one"}
        # Last system converted with cache_control
        assert result[1]["content"] == [
            {
                "type": "text",
                "text": "instruction two",
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def test_no_system_message_is_noop(self) -> None:
        """User-only message list should pass through unchanged."""
        mapped = [{"role": "user", "content": "hello"}]
        result = _annotate_last_system_block_with_cache_control(mapped)
        assert result == [{"role": "user", "content": "hello"}]
