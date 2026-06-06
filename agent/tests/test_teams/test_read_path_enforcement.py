"""Tests for Sprint P3.5 (#1726) — read_file domain enforcement.

Mirror image of ``test_domain_lock_enforcement.py`` (Sprint 04.05). Before
this sprint, ``AgentSpec.read_paths`` did not exist and ``read_file`` was a
raw ``Path.read_text`` with no allowlist — a specialist with
``domain.read: ["job_search/**"]`` in YAML could exfiltrate
``/opt/bumba-harness/data/.secrets`` because the YAML field was never
plumbed to the tool seam (Lane B M4 / MD-12 in the 2026-05-12 audit).

This module verifies that:

1. The loader plumbs ``domain.read`` through to ``AgentSpec.read_paths``
   and collapses the ``["*"]`` wildcard idiom to ``()`` for backward
   compat with the 5 wildcard-declaring teams.
2. ``make_tracked`` gates every read-capable tool call against the
   allowlist, returning ``DOMAIN_VIOLATION:`` (not raising) and emitting
   the same ``z4.domain.violation`` EventBus event the write-side uses.
3. Backward-compat: empty ``read_paths`` = no enforcement, identical to
   pre-P3.5 behaviour.
4. End-to-end: the exact ``read: ["config/job-search/**", "job_search/**"]``
   declaration from ``config/teams/job_search.yaml`` blocks a read of
   ``/opt/bumba-harness/data/.secrets``.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from teams._config import _collapse_wildcard_reads
from teams._tool_registry import (
    _format_read_violation,
    _is_path_allowed_for_read,
    _READ_TOOLS,
    _WRITE_TOOLS,
    make_tracked,
)


# ---------------------------------------------------------------------------
# Loader-side collapse helper
# ---------------------------------------------------------------------------


class TestCollapseWildcardReads:
    """``read: ["*"]`` is the established YAML idiom for read-anywhere.
    The loader collapses it to ``()`` so the downstream wrapper's
    "empty = no enforcement" contract holds without a wildcard token
    check in the hot path."""

    def test_wildcard_collapses_to_empty(self) -> None:
        assert _collapse_wildcard_reads(["*"]) == ()

    def test_empty_list_collapses_to_empty(self) -> None:
        assert _collapse_wildcard_reads([]) == ()

    def test_wildcard_with_other_globs_still_collapses(self) -> None:
        # Wildcard-dominant: any ``*`` in the list means read-anywhere.
        assert _collapse_wildcard_reads(["*", "data/"]) == ()

    def test_non_wildcard_preserved(self) -> None:
        result = _collapse_wildcard_reads(
            ["config/job-search/**", "job_search/**"]
        )
        assert result == ("config/job-search/**", "job_search/**")

    def test_single_non_wildcard_preserved(self) -> None:
        assert _collapse_wildcard_reads(["data/"]) == ("data/",)


# ---------------------------------------------------------------------------
# Pure helper coverage
# ---------------------------------------------------------------------------


class TestIsPathAllowedForRead:
    def test_returns_true_when_match(self) -> None:
        allow = ("config/job-search/**", "job_search/**")
        assert _is_path_allowed_for_read("job_search/listings.json", allow)
        assert _is_path_allowed_for_read("config/job-search/scoring.yaml", allow)

    def test_returns_false_when_no_match(self) -> None:
        allow = ("config/job-search/**", "job_search/**")
        assert not _is_path_allowed_for_read(
            "/opt/bumba-harness/data/.secrets", allow
        )
        assert not _is_path_allowed_for_read("agent/bridge/config.py", allow)

    def test_empty_target_returns_false(self) -> None:
        # No target = nothing to allow. Wrapper treats this as deny-safe.
        assert not _is_path_allowed_for_read("", ("job_search/**",))


class TestFormatReadViolation:
    def test_includes_agent_target_and_allowed_paths(self) -> None:
        msg = _format_read_violation(
            "acquire-and-prepare-specialist",
            "/opt/bumba-harness/data/.secrets",
            ("config/job-search/**", "job_search/**"),
        )
        assert "DOMAIN_VIOLATION:" in msg
        assert "acquire-and-prepare-specialist" in msg
        assert "/opt/bumba-harness/data/.secrets" in msg
        assert "config/job-search/**" in msg
        # Uses verb "read" (not "write") so the LLM self-corrects.
        assert "cannot read" in msg
        assert "Allowed paths:" in msg


# ---------------------------------------------------------------------------
# make_tracked — end-to-end wrapper behaviour (mirror of the 04.05 5)
# ---------------------------------------------------------------------------


def _ctx_with_event_bus() -> object:
    """Build a minimal RunContext-shaped object with a mock event_bus.

    Identical shape to the deny_write_paths test fixture — see
    ``test_domain_lock_enforcement._ctx_with_event_bus``.
    """
    ctx = MagicMock()
    ctx.deps = MagicMock()
    ctx.deps.event_bus = MagicMock()
    ctx.deps.event_bus.publish = MagicMock()
    ctx.deps.session_id = "test-session"
    ctx.deps.department = "job_search"
    return ctx


@pytest.mark.asyncio
class TestMakeTrackedReadEnforcement:
    """The five canonical read-side scenarios — symmetric to the
    deny_write_paths cases."""

    async def test_1_allowed_read_passes(self) -> None:
        async def read_file(ctx, path: str) -> str:
            return f"<contents of {path}>"

        wrapped = make_tracked(
            read_file,
            department="job_search",
            tool_name="read_file",
            read_paths=("config/job-search/**", "job_search/**"),
            agent_name="acquire-and-prepare-specialist",
        )
        ctx = _ctx_with_event_bus()
        result = await wrapped(ctx, path="job_search/listings.json")
        assert "<contents of job_search/listings.json>" == result
        ctx.deps.event_bus.publish.assert_not_called()

    async def test_2_blocked_read_returns_violation(self) -> None:
        # The headline finding: a job_search specialist with
        # restrictive read_paths cannot exfiltrate .secrets.
        async def read_file(ctx, path: str) -> str:  # pragma: no cover
            # Unreachable — wrapper short-circuits before the body runs.
            return "<would have leaked .secrets>"

        wrapped = make_tracked(
            read_file,
            department="job_search",
            tool_name="read_file",
            read_paths=("config/job-search/**", "job_search/**"),
            agent_name="acquire-and-prepare-specialist",
        )
        ctx = _ctx_with_event_bus()
        result = await wrapped(
            ctx, path="/opt/bumba-harness/data/.secrets"
        )
        assert result.startswith("DOMAIN_VIOLATION:")
        assert "acquire-and-prepare-specialist" in result
        assert "/opt/bumba-harness/data/.secrets" in result
        assert "cannot read" in result
        # Event published using the SAME event name as the write-side.
        ctx.deps.event_bus.publish.assert_called_once()
        evt_args = ctx.deps.event_bus.publish.call_args
        assert evt_args[0][0] == "z4.domain.violation"
        payload = evt_args[0][1]
        assert payload["agent_name"] == "acquire-and-prepare-specialist"
        assert payload["tool_name"] == "read_file"
        assert payload["target"] == "/opt/bumba-harness/data/.secrets"

    async def test_3_empty_read_paths_no_enforcement(self) -> None:
        # Backward compat: the 5 teams with ``read: ["*"]`` collapse to
        # ``()`` at the loader; their read_file calls pass through.
        async def read_file(ctx, path: str) -> str:
            return f"<contents of {path}>"

        wrapped = make_tracked(
            read_file,
            department="design",
            tool_name="read_file",
            read_paths=(),
            agent_name="visual-designer",
        )
        ctx = _ctx_with_event_bus()
        # Even reading what would be a denied path elsewhere passes
        # cleanly when this agent has no allowlist.
        result = await wrapped(
            ctx, path="/opt/bumba-harness/data/.secrets"
        )
        assert "<contents of" in result
        ctx.deps.event_bus.publish.assert_not_called()

    async def test_4_non_read_tool_bypasses_enforcement(self) -> None:
        # ``search_knowledge`` is NOT in ``_READ_TOOLS`` — it queries
        # the in-process knowledge store, not the filesystem. The
        # wrapper should never try to allowlist-check it, even with
        # a read_paths configured.
        async def search_knowledge(ctx, query: str) -> str:
            return "knowledge result"

        assert "search_knowledge" not in _READ_TOOLS
        wrapped = make_tracked(
            search_knowledge,
            department="job_search",
            tool_name="search_knowledge",
            read_paths=("job_search/**",),
            agent_name="acquire-and-prepare-specialist",
        )
        ctx = _ctx_with_event_bus()
        # The path-shaped query argument would be denied if we
        # allowlist-checked it; the wrapper bypasses entirely.
        result = await wrapped(ctx, query="/opt/bumba-harness/data/.secrets")
        assert result == "knowledge result"
        ctx.deps.event_bus.publish.assert_not_called()

    async def test_5_positional_path_arg_validated(self) -> None:
        # ``read_file`` signature is ``(ctx, path)`` — the wrapper must
        # extract the path from a positional call too, not just from
        # keyword args. Mirrors ``_extract_path_from_args`` fallback.
        async def read_file(ctx, path: str) -> str:  # pragma: no cover
            return "<unreachable>"

        wrapped = make_tracked(
            read_file,
            department="job_search",
            tool_name="read_file",
            read_paths=("job_search/**",),
            agent_name="acquire-and-prepare-specialist",
        )
        ctx = _ctx_with_event_bus()
        # Pass the path positionally — not as `path=`.
        result = await wrapped(ctx, "/opt/bumba-harness/data/.secrets")
        assert result.startswith("DOMAIN_VIOLATION:")
        ctx.deps.event_bus.publish.assert_called_once()


# ---------------------------------------------------------------------------
# Operator tripwire — _READ_TOOLS allowlist hygiene
# ---------------------------------------------------------------------------


class TestReadToolsAllowlist:
    """Operator MUST eyeball-review _READ_TOOLS when new file-read
    tools land. This tripwire forces a manual review if anyone
    accidentally adds a non-read tool to _READ_TOOLS or removes the
    known read tool. Symmetric to the deny_write_paths tripwire."""

    def test_known_read_tools_present(self) -> None:
        assert "read_file" in _READ_TOOLS

    def test_read_tools_and_write_tools_are_disjoint(self) -> None:
        # A tool cannot be both read- and write-side in the same call;
        # the wrapper checks them independently and the deny_write_paths
        # vs read_paths semantics would conflict.
        assert _READ_TOOLS.isdisjoint(_WRITE_TOOLS)

    def test_knowledge_tools_absent(self) -> None:
        # In-process queries — not filesystem reads. Adding them would
        # silently break ``search_knowledge`` / ``memory_recall`` for
        # every agent with a non-empty read_paths.
        for non_fs_tool in (
            "search_knowledge",
            "memory_recall",
            "pending_handoffs",
            "search_market_data",
            "analyze_competitor",
        ):
            assert non_fs_tool not in _READ_TOOLS, (
                f"{non_fs_tool} is not a filesystem read tool; "
                "do not add to _READ_TOOLS"
            )
