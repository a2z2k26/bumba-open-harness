"""Tool name → callable registry for department agent factory.

Maps the string tool names declared in YAML configs (e.g. ``run_tests``,
``search_knowledge``) to actual async callables that pydantic-ai can register
on agent instances.
"""

from __future__ import annotations

import functools
import logging
import re
import time
from pathlib import PurePosixPath
from typing import Any, Callable, Optional

from pydantic_ai import RunContext

from teams._namespace import get_guard
from teams._types import BridgeDeps

from teams.tools._board import recall_past_decisions
from teams.tools._common import pending_handoffs, read_file, search_knowledge
from teams.tools._design import (
    check_wcag_contrast,
    lookup_component,
    recall_brand_guidelines,
    search_design_system,
)
from teams.tools._lsp import (
    lsp_diagnostics,
    lsp_find_definition,
    lsp_find_references,
)
from teams.tools._job_search import (
    generate_cover_letter,
    get_approved_listings,
    research_contacts,
    score_and_deduplicate,
    scrape_boards,
    send_discord_alert,
    stage_listing_to_notion,
    update_notion_status,
)
from teams.tools._ops import check_service_status, continue_handoff, query_metrics, tail_log
from teams.tools._qa import coverage_report, run_tests, security_scan
from teams.tools._strategy import (
    analyze_competitor,
    initiate_handoff,
    recall_decision,
    search_market_data,
)

log = logging.getLogger(__name__)

TOOL_CALLABLES: dict[str, Callable[..., Any]] = {
    # common
    "read_file": read_file,
    "search_knowledge": search_knowledge,
    "memory_recall": None,  # placeholder — implemented below
    "pending_handoffs": pending_handoffs,
    # job_search
    "scrape_boards": scrape_boards,
    "score_and_deduplicate": score_and_deduplicate,
    "generate_cover_letter": generate_cover_letter,
    "stage_listing_to_notion": stage_listing_to_notion,
    "get_approved_listings": get_approved_listings,
    "update_notion_status": update_notion_status,
    "send_discord_alert": send_discord_alert,
    "research_contacts": research_contacts,
    # qa
    "run_tests": run_tests,
    "coverage_report": coverage_report,
    "security_scan": security_scan,
    # ops
    "check_service_status": check_service_status,
    "tail_log": tail_log,
    "query_metrics": query_metrics,
    "continue_handoff": continue_handoff,
    # lsp (Z4-20, #2446) — LSP-backed code intelligence via Serena.
    # Granted only to code-oriented QA/Ops roles (Z4-21 capability manifests).
    "lsp_find_definition": lsp_find_definition,
    "lsp_find_references": lsp_find_references,
    "lsp_diagnostics": lsp_diagnostics,
    # strategy
    "search_market_data": search_market_data,
    "analyze_competitor": analyze_competitor,
    "recall_decision": recall_decision,
    "initiate_handoff": initiate_handoff,
    # design
    "search_design_system": search_design_system,
    "lookup_component": lookup_component,
    "recall_brand_guidelines": recall_brand_guidelines,
    "check_wcag_contrast": check_wcag_contrast,
    # board
    "recall_past_decisions": recall_past_decisions,
}


async def memory_recall(ctx: RunContext[BridgeDeps], key: str) -> str:
    """Recall a value from the shared memory store by key."""
    try:
        result = await ctx.deps.memory_store.get(key)
        return str(result) if result else f"No entry found for key: {key}"
    except Exception as e:  # noqa: BLE001
        log.exception("memory_recall failed for key=%s", key)
        return f"ERROR: {e}"


TOOL_CALLABLES["memory_recall"] = memory_recall


# ---------------------------------------------------------------------------
# Sprint 04.05 (2026-04-30) — deny_write_paths enforcement at tool time
# ---------------------------------------------------------------------------
#
# Before this sprint, ``AgentSpec.deny_write_paths`` was loaded from YAML
# but never consulted at runtime. Per Round 1 §7 R1, that meant declared
# restrictions like "Board cannot write outside docs/board/" were
# theatre — the live runtime enforced nothing.
#
# This sprint wires the deny list into ``make_tracked`` so every
# write-capable tool checks its target path against the agent's deny
# list before invoking the underlying tool. Violations return a
# DomainViolationError string (NOT an exception) so the chief's LLM
# sees the violation, recovers, and either retries or surfaces upward.
#
# Empty ``deny_write_paths`` means no enforcement — opt-in by config.
# Today's YAMLs mostly have empty lists; departments opt in by
# populating their domain.deny_write list (e.g. board → ["agent/**",
# "config/**"] but not docs/board/**).
#
# The ``_WRITE_TOOLS`` allowlist enumerates the tools known to mutate
# state. Anything not on this list is treated as read-only and bypasses
# enforcement. Operator MUST eyeball-review this list when new write-
# capable tools land (per the spec's pre-merge action item).

_WRITE_TOOLS: frozenset[str] = frozenset({
    "write_file",
    "edit_file",
    "apply_patch",
    "bash",
})

# Sprint P3.5 (#1726, 2026-05-12) — read-side enforcement.
#
# Mirrors _WRITE_TOOLS exactly: enumerates the tools known to read
# arbitrary file contents back to the LLM. ``read_file`` (in
# ``teams.tools._common``) is the only entry today — it does a raw
# ``Path.read_text`` with no path validation, so a specialist with
# ``domain.read: ["job_search/**"]`` could exfiltrate
# ``/opt/bumba-harness/data/.secrets`` without enforcement at the tool
# seam. ``search_knowledge`` and ``memory_recall`` are NOT here — they
# query the in-process knowledge store and key/value memory, neither
# of which reads filesystem paths. Operator MUST eyeball-review this
# allowlist when new file-read tools land.
_READ_TOOLS: frozenset[str] = frozenset({
    "read_file",
})

# Tool argument names that carry a target file path. When a write tool
# fires, we look at these arg names (in priority order) to find the path
# to validate.
_PATH_ARG_NAMES: tuple[str, ...] = ("path", "file_path", "target", "filename")


def _path_matches_deny_rule(target: str, rule: str) -> bool:
    """Glob-match a candidate file path against a single deny rule.

    Uses ``pathlib.PurePosixPath.match`` for tight glob semantics
    (``*`` matches a single path segment, ``**`` matches any number).
    Both target and rule are normalised to POSIX form so behaviour is
    identical on macOS/Linux runtimes.
    """
    if not target or not rule:
        return False
    try:
        # PurePosixPath.match normalises trailing slashes and handles
        # both relative and absolute targets. Wrap in try/except so a
        # malformed glob never blows up tool dispatch.
        return PurePosixPath(target).match(rule)
    except (ValueError, TypeError):
        return False


def _is_path_denied(
    target: str, deny_paths: tuple[str, ...]
) -> Optional[str]:
    """Return the matching deny rule if ``target`` is denied, else None."""
    for rule in deny_paths:
        if _path_matches_deny_rule(target, rule):
            return rule
    return None


def _is_path_allowed_for_read(
    target: str, read_paths: tuple[str, ...]
) -> bool:
    """Return True if ``target`` matches at least one allowlist glob.

    Sprint P3.5 (#1726): mirror image of ``_is_path_denied`` — the
    write-side checks "is the target on the deny list?", the read-side
    checks "is the target on the allow list?". Empty ``read_paths`` is
    handled at the caller (treated as "no enforcement"). When non-empty,
    the target must match at least one glob to pass.
    """
    if not target:
        return False
    for rule in read_paths:
        if _path_matches_deny_rule(target, rule):
            return True
    return False


def _check_bash_command_for_writes(
    command: str, deny_paths: tuple[str, ...]
) -> Optional[tuple[str, str]]:
    """Scan a bash command for write redirects targeting denied paths.

    Returns ``(matched_path, matched_rule)`` if the command appears to
    write to a denied path, else None. Conservative scanner — false
    positives are preferred over missed writes:

    - ``> path`` and ``>> path`` redirects
    - ``tee path``
    - ``cp/mv/rm/install ... path`` for the destination/target arg
    - ``sed -i path``, ``sed -i '' path``
    - ``mkdir path``, ``touch path``
    - ``echo "x" > path`` (covered by the ``>`` rule)

    Only the destination-side of write operations is checked. The
    scanner does NOT try to be clever about quoting, command
    substitution, or chained pipelines — anything that smells like a
    write to a deny-listed path triggers a violation.
    """
    if not command or not deny_paths:
        return None

    # Tokenise on whitespace + redirect operators. Conservative: keeps
    # quotes intact so quoted paths still match path globs.
    tokens = re.split(r"(\s+|;|&&|\|\||\|)", command)

    write_verbs = {"cp", "mv", "rm", "install", "touch", "mkdir", "tee"}
    redirect_ops = {">", ">>"}

    i = 0
    while i < len(tokens):
        tok = tokens[i].strip().strip("'\"")
        if not tok:
            i += 1
            continue

        # Redirect operator → next non-empty token is the target.
        if tok in redirect_ops:
            for j in range(i + 1, len(tokens)):
                target = tokens[j].strip().strip("'\"")
                if target:
                    matched = _is_path_denied(target, deny_paths)
                    if matched:
                        return (target, matched)
                    break
            i += 1
            continue

        # `cmd > path` form embedded in a single token (no whitespace)
        if ">" in tok:
            for sep in (">>", ">"):
                if sep in tok:
                    _, target = tok.split(sep, 1)
                    target = target.strip().strip("'\"")
                    if target:
                        matched = _is_path_denied(target, deny_paths)
                        if matched:
                            return (target, matched)

        # Write-verb commands — every subsequent positional arg that
        # looks like a path is checked. Skip flags (start with "-").
        if tok in write_verbs:
            for j in range(i + 1, len(tokens)):
                cand = tokens[j].strip().strip("'\"")
                if not cand or cand.startswith("-") or cand in {";", "&&", "||", "|"}:
                    if cand in {";", "&&", "||", "|"}:
                        break
                    continue
                matched = _is_path_denied(cand, deny_paths)
                if matched:
                    return (cand, matched)

        # `sed -i path` is treated like a write — scan forward looking
        # for the in-place flag, then look for the first plausible path
        # arg afterwards.
        if tok == "sed":
            in_place = False
            for j in range(i + 1, len(tokens)):
                cand = tokens[j].strip().strip("'\"")
                if cand in {";", "&&", "||", "|"}:
                    break
                if cand in {"-i", "--in-place"}:
                    in_place = True
                    continue
                if in_place and cand and not cand.startswith("-"):
                    # Heuristic: a real path contains "/" and doesn't
                    # look like a sed substitution script (which
                    # typically starts with "s/").
                    looks_like_path = "/" in cand and not cand.startswith("s/")
                    if looks_like_path:
                        matched = _is_path_denied(cand, deny_paths)
                        if matched:
                            return (cand, matched)

        i += 1

    return None


def _format_violation(
    agent_name: str, target: str, deny_paths: tuple[str, ...]
) -> str:
    """Return the canonical DOMAIN_VIOLATION error string for the LLM."""
    allow_hint = ", ".join(deny_paths) if deny_paths else "(none)"
    return (
        f"DOMAIN_VIOLATION: agent {agent_name} cannot write to {target}. "
        f"Denied paths: {allow_hint}."
    )


def _format_read_violation(
    agent_name: str, target: str, read_paths: tuple[str, ...]
) -> str:
    """Return the canonical DOMAIN_VIOLATION error string for the LLM (read).

    Sprint P3.5 (#1726): read-side analogue of ``_format_violation``. The
    string uses the same ``DOMAIN_VIOLATION:`` prefix the chief's LLM
    already recognises, with verb ``read`` instead of ``write`` and
    ``Allowed paths:`` (the allowlist) instead of ``Denied paths:`` (the
    denylist) so the LLM can self-correct.
    """
    allow_hint = ", ".join(read_paths) if read_paths else "(none)"
    return (
        f"DOMAIN_VIOLATION: agent {agent_name} cannot read {target}. "
        f"Allowed paths: {allow_hint}."
    )


def _publish_violation(
    deps: BridgeDeps, agent_name: str, tool_name: str, target: str
) -> None:
    """Best-effort EventBus publish for a deny-write violation."""
    try:
        bus = getattr(deps, "event_bus", None)
        if bus is None:
            return
        bus.publish(
            "z4.domain.violation",
            {
                "agent_name": agent_name,
                "tool_name": tool_name,
                "target": target,
                "department": getattr(deps, "department", ""),
            },
            source="teams._tool_registry",
            correlation_id=getattr(deps, "session_id", "") or "",
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("z4.domain.violation publish_failed error=%s", exc)


def _extract_path_from_args(
    tool_name: str, args: tuple, kwargs: dict
) -> Optional[str]:
    """Extract the target path from tool-call args for write tools.

    Looks at well-known kwarg names first (``path``, ``file_path``,
    ``target``, ``filename``), then falls back to the first positional
    arg if it looks like a path string. Returns ``None`` if no plausible
    path is found — the caller treats that as "can't validate, allow
    through" (write tools without an inspectable path are rare and
    operator can extend ``_PATH_ARG_NAMES`` if needed).
    """
    for name in _PATH_ARG_NAMES:
        if name in kwargs and isinstance(kwargs[name], str):
            return kwargs[name]
    if args and isinstance(args[0], str):
        return args[0]
    return None


def make_tracked(
    fn: Callable[..., Any],
    *,
    department: str,
    tool_name: str,
    guard: Optional[Any] = None,
    tracker: Optional[Any] = None,
    deny_write_paths: tuple[str, ...] = (),
    read_paths: tuple[str, ...] = (),
    agent_name: str = "",
) -> Callable[..., Any]:
    """Wrap a tool callable with namespace validation + optional call tracking.

    Preserves the original function signature via ``functools.wraps`` so
    pydantic-ai's ``inspect.signature``-based schema extraction still works.

    Sprint 04.05 (2026-04-30): when ``deny_write_paths`` is non-empty
    and ``tool_name`` is in ``_WRITE_TOOLS``, every invocation is
    checked against the deny list before the underlying tool runs. A
    match returns a ``DOMAIN_VIOLATION:`` string and emits a
    ``z4.domain.violation`` EventBus event — the agent's LLM sees the
    error and can recover. Empty ``deny_write_paths`` is opt-out
    (default) — backward-compat with every existing caller.

    Sprint P3.5 (#1726, 2026-05-12): mirror image for reads. When
    ``read_paths`` is non-empty and ``tool_name`` is in ``_READ_TOOLS``,
    the requested path must match at least one allowlist glob or the
    wrapper returns ``DOMAIN_VIOLATION:`` and emits the same
    ``z4.domain.violation`` event with ``tool_name="read_file"``. Empty
    ``read_paths`` (default) is opt-out — preserves the 5 teams whose
    YAML declares ``read: ["*"]`` (collapsed to ``()`` at the loader)
    and the 1 team (job_search) whose 5 entries declare a non-wildcard
    allowlist.
    """

    @functools.wraps(fn)
    async def wrapper(ctx: RunContext[BridgeDeps], *args: Any, **kwargs: Any) -> str:
        if guard is not None:
            guard.validate(department, tool_name)

        # Sprint P3.5 (#1726) enforcement — runs BEFORE the underlying tool.
        # Read-side allowlist check, mirroring the deny_write_paths block
        # below. Order matters only insofar as a tool cannot be in both
        # _READ_TOOLS and _WRITE_TOOLS (read_file is read-only); the
        # checks are independent.
        if read_paths and tool_name in _READ_TOOLS:
            target = _extract_path_from_args(tool_name, args, kwargs)
            if target and not _is_path_allowed_for_read(target, read_paths):
                resolved_agent = agent_name or department
                _publish_violation(
                    ctx.deps, resolved_agent, tool_name, target
                )
                log.warning(
                    "domain_violation agent=%s tool=%s target=%s read_paths=%s",
                    resolved_agent, tool_name, target, read_paths,
                )
                return _format_read_violation(
                    resolved_agent, target, read_paths
                )

        # Sprint 04.05 enforcement — runs BEFORE the underlying tool.
        if deny_write_paths and tool_name in _WRITE_TOOLS:
            violation_target: Optional[str] = None
            violation_rule: Optional[str] = None

            if tool_name == "bash":
                # bash arg is the command string — scan for write redirects
                cmd = kwargs.get("command")
                if cmd is None and args and isinstance(args[0], str):
                    cmd = args[0]
                if isinstance(cmd, str):
                    found = _check_bash_command_for_writes(cmd, deny_write_paths)
                    if found is not None:
                        violation_target, violation_rule = found
            elif tool_name == "apply_patch":
                # apply_patch's argument is a unified-diff string; scan
                # every "+++ b/<path>" header for denied targets.
                patch = kwargs.get("patch") or kwargs.get("diff")
                if patch is None and args and isinstance(args[0], str):
                    patch = args[0]
                if isinstance(patch, str):
                    for line in patch.splitlines():
                        if line.startswith("+++ "):
                            target = line[4:].strip()
                            # strip "b/" or "a/" prefix common in unified diffs
                            for prefix in ("b/", "a/"):
                                if target.startswith(prefix):
                                    target = target[len(prefix):]
                            matched = _is_path_denied(
                                target, deny_write_paths
                            )
                            if matched:
                                violation_target = target
                                violation_rule = matched
                                break
            else:
                # write_file, edit_file — single path argument
                target = _extract_path_from_args(tool_name, args, kwargs)
                if target:
                    matched = _is_path_denied(target, deny_write_paths)
                    if matched:
                        violation_target = target
                        violation_rule = matched

            if violation_target is not None:
                resolved_agent = agent_name or department
                _publish_violation(
                    ctx.deps, resolved_agent, tool_name, violation_target
                )
                log.warning(
                    "domain_violation agent=%s tool=%s target=%s rule=%s",
                    resolved_agent, tool_name, violation_target,
                    violation_rule,
                )
                return _format_violation(
                    resolved_agent, violation_target, deny_write_paths
                )

        start = time.monotonic()
        result = await fn(ctx, *args, **kwargs)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        if tracker is not None:
            merged_args: dict = {}
            for i, a in enumerate(args):
                merged_args[f"arg{i}"] = a
            merged_args.update(kwargs)
            tracker.log_call(
                agent_name=department,
                department=ctx.deps.department,
                session_id=ctx.deps.session_id,
                tool_name=tool_name,
                args=merged_args,
                result=str(result)[:200],
                duration_ms=elapsed_ms,
            )
        return result

    return wrapper


COMMON_TOOL_NAMES: frozenset[str] = frozenset({
    "read_file", "search_knowledge", "memory_recall", "pending_handoffs",
})


def resolve_tools(
    tool_names: tuple[str, ...],
    department: str,
    *,
    tracker: Optional[Any] = None,
    deny_write_paths: tuple[str, ...] = (),
    read_paths: tuple[str, ...] = (),
    agent_name: str = "",
) -> list[tuple[str, Callable[..., Any]]]:
    """Resolve a tuple of tool name strings into (name, wrapped_callable) pairs.

    Unknown names are logged as warnings and skipped.
    Common tools (read_file, search_knowledge, memory_recall) are shared across
    departments and are NOT registered with the namespace guard.

    Sprint 04.05 (2026-04-30): ``deny_write_paths`` and ``agent_name``
    are forwarded to ``make_tracked`` so per-agent write-path
    enforcement fires at tool call time. Both default to empty/empty —
    backward compat with every existing caller, opt-in via the agent's
    YAML ``domain.deny_write`` field.

    Sprint P3.5 (#1726, 2026-05-12): ``read_paths`` is the read-side
    analogue, plumbed from the agent's YAML ``domain.read`` block via
    the loader (``teams._config._collapse_wildcard_reads``). Default
    empty tuple = no enforcement — backward compat with every existing
    caller.
    """
    guard = get_guard()
    resolved: list[tuple[str, Callable[..., Any]]] = []
    dept_only_names: list[str] = []

    for name in tool_names:
        fn = TOOL_CALLABLES.get(name)
        if fn is None:
            log.warning(
                "tool_registry.unknown_tool department=%s tool=%s — skipping",
                department,
                name,
            )
            continue
        wrapped = make_tracked(
            fn,
            department=department,
            tool_name=name,
            guard=guard if name not in COMMON_TOOL_NAMES else None,
            tracker=tracker,
            deny_write_paths=deny_write_paths,
            read_paths=read_paths,
            agent_name=agent_name,
        )
        resolved.append((name, wrapped))
        if name not in COMMON_TOOL_NAMES:
            dept_only_names.append(name)

    if dept_only_names:
        guard.register(department, dept_only_names)

    return resolved
