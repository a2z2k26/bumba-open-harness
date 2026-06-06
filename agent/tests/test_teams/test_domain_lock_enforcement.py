"""Tests for Sprint 04.05 — deny_write_paths enforcement at tool time.

Before this sprint, ``AgentSpec.deny_write_paths`` was loaded from YAML
but never consulted at runtime. This module verifies that
``make_tracked`` now gates every write-capable tool call against the
agent's deny list, returning a ``DOMAIN_VIOLATION:`` error string
(not raising) and emitting a ``z4.domain.violation`` EventBus event.

Five canonical scenarios per the spec:

1. Write to allowed path → passes through to the underlying tool.
2. Write to denied path → returns DomainViolationError + emits event.
3. Bash command with redirect to denied path → returns DomainViolationError.
4. Bash command with no writes → passes through.
5. Empty ``deny_write_paths`` → passes (opt-in enforcement).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from teams._tool_registry import (
    _check_bash_command_for_writes,
    _format_violation,
    _is_path_denied,
    _path_matches_deny_rule,
    _WRITE_TOOLS,
    make_tracked,
)


# ---------------------------------------------------------------------------
# Pure helper coverage
# ---------------------------------------------------------------------------


class TestPathMatchesDenyRule:
    @pytest.mark.parametrize("target,rule,expected", [
        ("agent/bridge/x.py", "agent/bridge/*", True),
        ("agent/bridge/sub/y.py", "agent/bridge/*", False),  # * is one segment
        ("agent/bridge/sub/y.py", "agent/bridge/**/*", True),
        ("docs/board/notes.md", "docs/board/*", True),
        ("docs/strategy/notes.md", "docs/board/*", False),
        ("config/teams/strategy.yaml", "config/**/*.yaml", True),
        ("", "agent/*", False),
        ("agent/x.py", "", False),
    ])
    def test_glob_matching(self, target: str, rule: str, expected: bool) -> None:
        assert _path_matches_deny_rule(target, rule) is expected

    def test_malformed_rule_returns_false(self) -> None:
        # PurePosixPath.match raises on some malformed rules — wrapper
        # should swallow and return False rather than blow up dispatch.
        assert _path_matches_deny_rule("agent/x.py", None) is False  # type: ignore[arg-type]


class TestIsPathDenied:
    def test_returns_matching_rule_when_denied(self) -> None:
        deny = ("agent/bridge/*", "config/**/*.yaml")
        assert _is_path_denied("agent/bridge/x.py", deny) == "agent/bridge/*"

    def test_returns_none_when_allowed(self) -> None:
        deny = ("agent/bridge/*",)
        assert _is_path_denied("docs/x.md", deny) is None

    def test_empty_deny_list_allows_everything(self) -> None:
        assert _is_path_denied("agent/bridge/x.py", ()) is None


class TestFormatViolation:
    def test_includes_agent_target_and_rules(self) -> None:
        msg = _format_violation(
            "qa-chief", "agent/bridge/x.py", ("agent/bridge/*",)
        )
        assert "DOMAIN_VIOLATION:" in msg
        assert "qa-chief" in msg
        assert "agent/bridge/x.py" in msg
        assert "agent/bridge/*" in msg


# ---------------------------------------------------------------------------
# Bash-command write detection
# ---------------------------------------------------------------------------


class TestCheckBashCommandForWrites:
    DENY = ("agent/bridge/*", "config/**/*")

    def test_redirect_to_denied(self) -> None:
        result = _check_bash_command_for_writes(
            "echo hello > agent/bridge/x.py", self.DENY
        )
        assert result is not None
        assert result[0] == "agent/bridge/x.py"

    def test_append_redirect_to_denied(self) -> None:
        result = _check_bash_command_for_writes(
            "echo hi >> config/teams/strategy.yaml", self.DENY
        )
        assert result is not None
        assert "config/teams/strategy.yaml" in result[0]

    def test_redirect_to_allowed(self) -> None:
        assert _check_bash_command_for_writes(
            "echo hello > docs/notes.md", self.DENY
        ) is None

    def test_cp_to_denied(self) -> None:
        result = _check_bash_command_for_writes(
            "cp /tmp/x.py agent/bridge/y.py", self.DENY
        )
        assert result is not None
        assert result[0] == "agent/bridge/y.py"

    def test_mv_to_denied(self) -> None:
        result = _check_bash_command_for_writes(
            "mv old.py agent/bridge/new.py", self.DENY
        )
        assert result is not None

    def test_touch_denied(self) -> None:
        result = _check_bash_command_for_writes(
            "touch agent/bridge/marker", self.DENY
        )
        assert result is not None

    def test_sed_in_place_denied_simple_form(self) -> None:
        # sed -i without a quoted script — the simple form is caught.
        result = _check_bash_command_for_writes(
            "sed -i s/x/y/ agent/bridge/file.py", self.DENY
        )
        assert result is not None
        assert "agent/bridge/file.py" in result[0]

    def test_sed_in_place_with_quoted_script_caught(self) -> None:
        # The path-shape heuristic ("contains / and doesn't look like
        # 's/x/y/' substitution") lets the scanner skip the quoted
        # script and land on the real file path argument.
        result = _check_bash_command_for_writes(
            "sed -i 's/x/y/' agent/bridge/file.py", self.DENY
        )
        assert result is not None
        assert "agent/bridge/file.py" in result[0]

    def test_read_only_command_passes(self) -> None:
        assert _check_bash_command_for_writes("ls -la /tmp", self.DENY) is None
        assert _check_bash_command_for_writes("grep foo /etc/hosts", self.DENY) is None
        assert _check_bash_command_for_writes("cat README.md", self.DENY) is None

    def test_empty_command_passes(self) -> None:
        assert _check_bash_command_for_writes("", self.DENY) is None

    def test_empty_deny_list_passes(self) -> None:
        assert _check_bash_command_for_writes("rm -rf /", ()) is None


# ---------------------------------------------------------------------------
# make_tracked — end-to-end wrapper behaviour
# ---------------------------------------------------------------------------


def _ctx_with_event_bus() -> object:
    """Build a minimal RunContext-shaped object with a mock event_bus."""
    ctx = MagicMock()
    ctx.deps = MagicMock()
    ctx.deps.event_bus = MagicMock()
    ctx.deps.event_bus.publish = MagicMock()
    ctx.deps.session_id = "test-session"
    ctx.deps.department = "test-dept"
    return ctx


@pytest.mark.asyncio
class TestMakeTrackedEnforcement:
    """The five canonical scenarios from the spec, exercised through
    the real ``make_tracked`` wrapper."""

    async def test_1_allowed_write_passes(self) -> None:
        async def write_file(ctx, path: str, contents: str) -> str:
            return f"wrote {path}"

        wrapped = make_tracked(
            write_file,
            department="qa",
            tool_name="write_file",
            deny_write_paths=("agent/bridge/*",),
            agent_name="qa-chief",
        )
        ctx = _ctx_with_event_bus()
        result = await wrapped(ctx, path="docs/notes.md", contents="x")
        assert "wrote docs/notes.md" in result
        ctx.deps.event_bus.publish.assert_not_called()

    async def test_2_denied_write_returns_violation(self) -> None:
        async def write_file(ctx, path: str, contents: str) -> str:
            return f"wrote {path}"

        wrapped = make_tracked(
            write_file,
            department="qa",
            tool_name="write_file",
            deny_write_paths=("agent/bridge/*",),
            agent_name="qa-chief",
        )
        ctx = _ctx_with_event_bus()
        result = await wrapped(ctx, path="agent/bridge/secret.py", contents="x")
        assert result.startswith("DOMAIN_VIOLATION:")
        assert "qa-chief" in result
        assert "agent/bridge/secret.py" in result
        # Event published
        ctx.deps.event_bus.publish.assert_called_once()
        evt_args = ctx.deps.event_bus.publish.call_args
        assert evt_args[0][0] == "z4.domain.violation"
        payload = evt_args[0][1]
        assert payload["agent_name"] == "qa-chief"
        assert payload["tool_name"] == "write_file"

    async def test_3_bash_redirect_to_denied(self) -> None:
        async def bash(ctx, command: str) -> str:
            return "ran"

        wrapped = make_tracked(
            bash,
            department="ops",
            tool_name="bash",
            deny_write_paths=("agent/bridge/*",),
            agent_name="ops-chief",
        )
        ctx = _ctx_with_event_bus()
        result = await wrapped(
            ctx, command="echo hello > agent/bridge/leak.py"
        )
        assert result.startswith("DOMAIN_VIOLATION:")
        ctx.deps.event_bus.publish.assert_called_once()

    async def test_4_bash_with_no_writes_passes(self) -> None:
        async def bash(ctx, command: str) -> str:
            return "ran ls"

        wrapped = make_tracked(
            bash,
            department="ops",
            tool_name="bash",
            deny_write_paths=("agent/bridge/*",),
            agent_name="ops-chief",
        )
        ctx = _ctx_with_event_bus()
        result = await wrapped(ctx, command="ls -la /tmp")
        assert result == "ran ls"
        ctx.deps.event_bus.publish.assert_not_called()

    async def test_5_empty_deny_list_no_enforcement(self) -> None:
        async def write_file(ctx, path: str, contents: str) -> str:
            return f"wrote {path}"

        wrapped = make_tracked(
            write_file,
            department="qa",
            tool_name="write_file",
            deny_write_paths=(),
            agent_name="qa-chief",
        )
        ctx = _ctx_with_event_bus()
        # Even writing to what would be a denied path elsewhere passes
        # cleanly when this agent has no deny list.
        result = await wrapped(ctx, path="agent/bridge/anywhere.py", contents="x")
        assert "wrote" in result
        ctx.deps.event_bus.publish.assert_not_called()


# ---------------------------------------------------------------------------
# Edge cases beyond the canonical 5
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEdgeCases:
    async def test_apply_patch_denied_target(self) -> None:
        async def apply_patch(ctx, patch: str) -> str:
            return "applied"

        wrapped = make_tracked(
            apply_patch,
            department="qa",
            tool_name="apply_patch",
            deny_write_paths=("agent/bridge/*",),
            agent_name="qa-chief",
        )
        patch = (
            "--- a/agent/bridge/old.py\n"
            "+++ b/agent/bridge/new.py\n"
            "@@ -1 +1 @@\n"
            "-x\n+y\n"
        )
        ctx = _ctx_with_event_bus()
        result = await wrapped(ctx, patch=patch)
        assert result.startswith("DOMAIN_VIOLATION:")
        assert "agent/bridge/new.py" in result

    async def test_apply_patch_allowed_target_passes(self) -> None:
        async def apply_patch(ctx, patch: str) -> str:
            return "applied"

        wrapped = make_tracked(
            apply_patch,
            department="qa",
            tool_name="apply_patch",
            deny_write_paths=("agent/bridge/*",),
            agent_name="qa-chief",
        )
        patch = (
            "--- a/docs/x.md\n"
            "+++ b/docs/x.md\n"
            "@@ -1 +1 @@\n"
            "-x\n+y\n"
        )
        ctx = _ctx_with_event_bus()
        result = await wrapped(ctx, patch=patch)
        assert result == "applied"

    async def test_non_write_tool_bypasses_enforcement(self) -> None:
        # read_file is NOT in _WRITE_TOOLS — the wrapper should never
        # try to deny-check, even with a deny list configured.
        async def read_file(ctx, path: str) -> str:
            return "contents"

        assert "read_file" not in _WRITE_TOOLS
        wrapped = make_tracked(
            read_file,
            department="qa",
            tool_name="read_file",
            deny_write_paths=("agent/bridge/*",),
            agent_name="qa-chief",
        )
        ctx = _ctx_with_event_bus()
        result = await wrapped(ctx, path="agent/bridge/secret.py")
        assert result == "contents"
        ctx.deps.event_bus.publish.assert_not_called()


class TestWriteToolsAllowlist:
    """Operator MUST eyeball-review _WRITE_TOOLS when new write-capable
    tools land. This test is a tripwire: if anyone accidentally adds a
    non-write tool to _WRITE_TOOLS or removes a known write tool,
    review is forced."""

    def test_known_write_tools_present(self) -> None:
        assert "write_file" in _WRITE_TOOLS
        assert "edit_file" in _WRITE_TOOLS
        assert "apply_patch" in _WRITE_TOOLS
        assert "bash" in _WRITE_TOOLS

    def test_known_read_tools_absent(self) -> None:
        for read_tool in (
            "read_file",
            "search_knowledge",
            "memory_recall",
            "search_market_data",
            "analyze_competitor",
        ):
            assert read_tool not in _WRITE_TOOLS, (
                f"{read_tool} should not be in _WRITE_TOOLS"
            )
