"""DepartmentTeam runtime facade.

Wraps a department's manager and employees, enforces timeouts,
returns structured TeamResult. Never raises.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace as dataclass_replace
from pathlib import Path
from typing import Any, Optional

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.usage import UsageLimits

from bridge.conversation_log import ConversationLogger, MessageType
from bridge.run_artifacts import (
    build_checkpoint_record,
    load_checkpoint,
    load_message_history,
    serialize_message_history,
    write_checkpoint,
)
from teams._agent_cache import AgentCache
from teams._circuit import CircuitOpenError, get_registry
from teams._factory import (
    build_employee_agents,
    build_manager_agent,
    capability_telemetry_fields,
)
from teams._openrouter_route_policy import classify_openrouter_zone4_route
from teams._post_run import should_checkpoint
from teams._run_telemetry import (
    RunTelemetry,
    normalize_failure_class,
    telemetry_with_failure,
    total_tokens_from_usage,
    usage_telemetry,
)
from teams._usage_policy import (
    UsagePolicy,
    classify_model_provider,
    estimate_preflight_context_chars,
    resolve_usage_policy,
    usage_limit_failure_class,
)
from teams._types import (
    BridgeDeps,
    Constraints,
    DepartmentConfig,
    EmployeeResult,
    TeamOutput,
    TeamResult,
)
from teams._verify import verify_team_result

log = logging.getLogger(__name__)

RUN_MEMORY_NOTE_MAX_CHARS = 4_000
RUN_MEMORY_SUMMARY_MAX_CHARS = 1_200
_OPENROUTER_PREFIX = "openrouter:"
_OPENROUTER_ZONE4_POLICY_FAILURE = "openrouter_zone4_route_policy"


@dataclass(frozen=True)
class _RunRelayContext:
    run_id: str
    run_dir: Path
    manifest_path: Path
    memory_ref: str


@dataclass(frozen=True)
class _ResumeContext:
    """A successfully-loaded resume state for ``DepartmentTeam.run``.

    WS2.5 (#2570). ``attempt`` is ``record.attempt + 1`` — the attempt number
    the NEXT checkpoint write should record. ``message_history`` is the
    reloaded transcript (None when the prior run had no serialized history).
    ``completed_specialists`` pre-seed the run collector so Gate 8's specialist
    floor counts prior work.
    """

    run_dir: Path
    message_history: list[Any] | None
    completed_specialists: tuple[EmployeeResult, ...]
    attempt: int


def _is_model_rate_limit_error(exc: BaseException) -> bool:
    """Return True for provider HTTP 429 rate-limit errors."""
    if not isinstance(exc, ModelHTTPError):
        return False
    if exc.status_code != 429:
        return False

    body = exc.body
    if not isinstance(body, Mapping):
        return True

    body_type = body.get("type")
    if isinstance(body_type, str) and "rate_limit" in body_type:
        return True

    error = body.get("error")
    if isinstance(error, Mapping):
        error_type = error.get("type")
        if isinstance(error_type, str) and "rate_limit" in error_type:
            return True

    return True


def _resolve_usage_policy(config: DepartmentConfig) -> UsagePolicy:
    provider = classify_model_provider(config.manager.model)
    return resolve_usage_policy(
        provider=provider,
        configured_request_limit=config.constraints.request_limit,
        configured_input_limit=config.constraints.request_token_limit,
        configured_output_limit=config.constraints.response_token_limit,
    )


def _config_uses_openrouter(config: DepartmentConfig) -> bool:
    specs = (config.manager, *config.employees)
    return any(spec.model.startswith(_OPENROUTER_PREFIX) for spec in specs)


def _openrouter_zone4_policy_refusal(
    config: DepartmentConfig,
) -> TeamResult | None:
    if config.zone != 4 or not _config_uses_openrouter(config):
        return None

    verdict = classify_openrouter_zone4_route(config)
    if verdict.classification == "safe":
        return None

    missing = ", ".join(verdict.missing_capabilities) or "none"
    error = (
        "OpenRouter Zone 4 route refused before provider request: "
        f"{verdict.route} classified as {verdict.classification}; "
        f"missing_capabilities={missing}; reason={verdict.reason}"
    )
    extra = (
        ("openrouter_route", verdict.route),
        ("openrouter_route_classification", verdict.classification),
        ("openrouter_missing_capabilities", missing),
    )
    return TeamResult(
        department=config.name,
        manager_output="",
        success=False,
        error=error,
        telemetry=_build_run_telemetry(
            config,
            failure_class=_OPENROUTER_ZONE4_POLICY_FAILURE,
            extra=extra,
        ),
    )


def _resolve_usage_limits(
    constraints: Constraints,
    *,
    model: str = "",
) -> UsageLimits:
    """Build a pydantic-ai ``UsageLimits`` from team-level ``Constraints``.

    Issue #1970 — ``Constraints.request_limit``, ``request_token_limit``,
    and ``response_token_limit`` were loaded from YAML into the dataclass
    but never passed to ``Agent.run()``. Pydantic-ai's default
    ``UsageLimits(request_limit=50, ...)`` won every time, ignoring the
    operator-declared caps. This helper closes that loop.

    Mapping (Constraints → provider-aware policy → pydantic-ai 1.80+
    UsageLimits kwargs):

    - ``request_limit`` → ``request_limit`` (same name)
    - ``request_token_limit`` → ``input_tokens_limit`` (pydantic-ai's
      v1.80 rename of the historical ``request_tokens_limit``)
    - ``response_token_limit`` → ``output_tokens_limit`` (likewise)

    Zero or negative values resolve to ``None`` so pydantic-ai
    treats them as "no cap" rather than "cap of zero" — matches the
    convention used for ``cost_limit_usd`` elsewhere in the codebase.
    """
    policy = resolve_usage_policy(
        provider=classify_model_provider(model),
        configured_request_limit=constraints.request_limit,
        configured_input_limit=constraints.request_token_limit,
        configured_output_limit=constraints.response_token_limit,
    )

    return UsageLimits(
        request_limit=policy.request_limit,
        input_tokens_limit=policy.input_tokens_limit,
        output_tokens_limit=policy.output_tokens_limit,
    )


def _build_run_telemetry(
    config: DepartmentConfig,
    *,
    usage: object | None = None,
    employee_results: tuple[EmployeeResult, ...] = (),
    fallback_model: str | None = None,
    fallback_reason: str | None = None,
    failure_class: str | None = None,
    duration_seconds: float = 0.0,
    surfaces_written: int = 0,
    artifacts_written: int = 0,
    extra: tuple[tuple[str, str], ...] = (),
) -> RunTelemetry:
    counts = usage_telemetry(usage)
    return RunTelemetry(
        department=config.name,
        chief_name=config.manager.name,
        primary_model=config.manager.model,
        fallback_model=fallback_model,
        fallback_reason=fallback_reason,
        input_tokens=counts.input_tokens,
        output_tokens=counts.output_tokens,
        request_count=counts.request_count,
        duration_seconds=duration_seconds,
        specialists_expected_min=config.constraints.expected_min_specialists,
        specialists_returned=len(employee_results),
        specialists_successful=sum(1 for er in employee_results if er.success),
        surfaces_written=surfaces_written,
        artifacts_written=artifacts_written,
        failure_class=failure_class,
        extra=extra,
    )


def _department_memory_slug(department: str) -> str:
    allowed: list[str] = []
    for char in department.lower():
        if char.isalnum():
            allowed.append(char)
        elif char in {"-", "_"}:
            allowed.append(char)
        elif char.isspace():
            allowed.append("-")
    slug = "".join(allowed).strip("-_")
    return slug or "unknown"


def _memory_ref_for_run(department: str, run_id: str) -> str:
    return f"memory:zone4/{_department_memory_slug(department)}/{run_id}"


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def _summary_for_memory(result: TeamResult) -> str:
    summary = (result.manager_output or result.error or "").strip()
    if not summary:
        summary = "No summary returned."
    return _truncate_text(summary, RUN_MEMORY_SUMMARY_MAX_CHARS)


def _open_blockers(result: TeamResult) -> list[str]:
    blockers: list[str] = []
    if not result.success and result.error:
        blockers.append(result.error.strip())
    for employee in result.employee_results:
        if not employee.success and employee.error:
            blockers.append(f"{employee.employee_name}: {employee.error.strip()}")
    return blockers


def _read_manifest_payload(manifest_path: Path | str) -> dict[str, Any]:
    path = Path(manifest_path).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def build_run_memory_note(result: TeamResult, manifest_path: Path | str) -> str:
    """Build the compact Z4-05 memory pointer note for a completed run."""
    path = Path(manifest_path).expanduser()
    manifest = _read_manifest_payload(path)
    artifacts = [
        artifact
        for artifact in manifest.get("artifacts", [])
        if isinstance(artifact, dict)
    ]
    blockers = _open_blockers(result)
    status = "success" if result.success else "failed"
    lines = [
        f"Zone4 run: {result.department}",
        f"Status: {status}",
        f"Manifest: {path}",
    ]
    if result.memory_ref:
        lines.append(f"Memory ref: {result.memory_ref}")
    lines.extend(["", "Summary:", _summary_for_memory(result), "", "Artifacts:"])
    if artifacts:
        for artifact in artifacts:
            artifact_path = str(artifact.get("path", ""))
            artifact_kind = str(artifact.get("kind", "artifact"))
            artifact_agent = str(artifact.get("agent", "unknown"))
            lines.append(f"- {artifact_path} ({artifact_kind}, {artifact_agent})")
    else:
        lines.append("- none")
    lines.extend(["", "Open blockers:"])
    if blockers:
        lines.extend(f"- {_truncate_text(blocker, 500)}" for blocker in blockers)
    else:
        lines.append("- none")
    lines.extend(["", "Follow-up actions:"])
    if blockers:
        lines.append("- Resolve blockers before rerunning or continuing the work.")
    else:
        lines.append("- none")
    return _truncate_text("\n".join(lines), RUN_MEMORY_NOTE_MAX_CHARS)


def build_run_relay_payload(
    result: TeamResult,
    manifest_path: Path | str,
    *,
    memory_ref: str,
) -> dict[str, object]:
    manifest = _read_manifest_payload(manifest_path)
    artifacts = manifest.get("artifacts", [])
    artifact_count = len(artifacts) if isinstance(artifacts, list) else 0
    run_id = str(manifest.get("run_id") or result.run_id or "")
    return {
        "run_id": run_id,
        "manifest_path": str(Path(manifest_path).expanduser()),
        "summary": _summary_for_memory(result),
        "artifact_count": artifact_count,
        "memory_ref": memory_ref,
        "open_blockers": _open_blockers(result),
    }


def _manifest_telemetry(result: TeamResult) -> tuple[tuple[str, str], ...]:
    telemetry = result.telemetry
    if telemetry is None:
        return ()
    names = (
        "primary_model",
        "fallback_model",
        "fallback_reason",
        "input_tokens",
        "output_tokens",
        "request_count",
        "duration_seconds",
        "specialists_expected_min",
        "specialists_returned",
        "specialists_successful",
        "surfaces_written",
        "artifacts_written",
        "failure_class",
    )
    entries: list[tuple[str, str]] = []
    for name in names:
        value = getattr(telemetry, name, None)
        if value is None:
            continue
        entries.append((name, str(value)))
    entries.extend((key, str(value)) for key, value in telemetry.extra)
    return tuple(entries)


def _prepare_run_relay(
    deps: BridgeDeps,
    config: DepartmentConfig,
    *,
    directive_id: str | None,
) -> tuple[BridgeDeps, _RunRelayContext | None]:
    existing_dir = getattr(deps, "run_artifact_dir", None)
    if existing_dir is not None:
        run_dir = Path(existing_dir).expanduser()
        run_id = run_dir.name
        return deps, _RunRelayContext(
            run_id=run_id,
            run_dir=run_dir,
            manifest_path=run_dir / "manifest.json",
            memory_ref=_memory_ref_for_run(config.name, run_id),
        )

    artifact_root = getattr(deps, "artifact_root", None)
    if artifact_root is None:
        return deps, None

    try:
        from bridge.run_artifacts import create_run_workspace

        workspace = create_run_workspace(
            Path(artifact_root).expanduser(),
            session_id=getattr(deps, "session_id", "") or "",
            department=config.name,
            directive_id=directive_id,
            chief=config.manager.name,
            project_root=getattr(deps, "project_root", None),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "run_relay.workspace_create_failed department=%s error=%s",
            config.name,
            exc,
        )
        return deps, None

    relayed_deps = dataclass_replace(deps, run_artifact_dir=workspace.run_dir)
    return relayed_deps, _RunRelayContext(
        run_id=workspace.run_id,
        run_dir=workspace.run_dir,
        manifest_path=workspace.manifest_path,
        memory_ref=_memory_ref_for_run(config.name, workspace.run_id),
    )


def _resolve_resume(
    deps: BridgeDeps,
    resume_from: str,
) -> _ResumeContext | str:
    """Resolve a ``resume_from`` run id into a loaded resume state.

    WS2.5 (#2570). Returns a ``_ResumeContext`` when the prior run's checkpoint
    is present AND resumable; otherwise returns a failure-class string that the
    caller turns into a short-circuit failure ``TeamResult`` without invoking
    the manager:

    * ``'checkpoint_missing'`` — no resolvable artifact_root, or no readable
      ``checkpoint.json`` under ``artifact_root / resume_from``;
    * ``'checkpoint_unresumable'`` — the checkpoint exists but
      ``record.resumable`` is False (its failure class is not in
      ``RECOVERABLE_FAILURE_CLASSES``).

    SEAM AUDIT: ``record.resumable`` is the single source of resume eligibility
    (written by ``build_checkpoint_record`` from ``RECOVERABLE_FAILURE_CLASSES``
    in WS2.3); this loader trusts it rather than re-deriving the class.
    """
    artifact_root = getattr(deps, "artifact_root", None)
    if artifact_root is None:
        return "checkpoint_missing"
    run_dir = Path(artifact_root).expanduser() / resume_from
    record = load_checkpoint(run_dir)
    if record is None:
        return "checkpoint_missing"
    if not record.resumable:
        return "checkpoint_unresumable"

    message_history = load_message_history(run_dir, record.message_history_ref)
    completed = tuple(
        EmployeeResult(
            employee_name=spec.name,
            output="",
            success=spec.success,
            error=spec.error,
        )
        for spec in record.completed_specialists
    )
    return _ResumeContext(
        run_dir=run_dir,
        message_history=message_history,
        completed_specialists=completed,
        attempt=record.attempt + 1,
    )


async def _write_run_memory_note(
    deps: BridgeDeps,
    result: TeamResult,
    manifest_path: Path,
) -> None:
    if not should_checkpoint(result, result.telemetry):
        return
    memory_store = getattr(deps, "memory_store", None)
    if memory_store is None or not hasattr(memory_store, "set"):
        return
    if not result.memory_ref:
        return
    try:
        await memory_store.set(
            result.memory_ref,
            build_run_memory_note(result, manifest_path),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "run_relay.memory_write_failed department=%s memory_ref=%s error=%s",
            result.department,
            result.memory_ref,
            exc,
        )


async def _write_run_checkpoint(
    deps: BridgeDeps,
    result: TeamResult,
    relay: _RunRelayContext,
    *,
    task: str,
    run_result: Any | None,
    attempt: int = 1,
) -> None:
    """Persist a resume checkpoint beside the run-memory note.

    WS2.4 (#2570). Gated by the SAME ``should_checkpoint`` predicate as
    ``_write_run_memory_note`` so the note and the checkpoint never diverge.
    Best-effort: any failure logs a WARNING and is swallowed so a
    checkpoint-write failure can never break the team run. ``attempt`` is 1 on
    the first run; WS2.5 resumes pass ``record.attempt + 1``.
    """
    if not should_checkpoint(result, result.telemetry):
        return
    try:
        message_history_ref = serialize_message_history(relay.run_dir, run_result)
        record = build_checkpoint_record(
            result,
            relay,
            task=task,
            attempt=attempt,
            run_result=run_result,
        )
        if message_history_ref is not None:
            record = dataclass_replace(
                record, message_history_ref=message_history_ref
            )
        write_checkpoint(relay.run_dir, record)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "run_relay.checkpoint_write_failed department=%s run_id=%s error=%s",
            result.department,
            relay.run_id,
            exc,
        )


def _append_run_artifacts_footer(output: str, manifest_path: str | None) -> str:
    if not output.strip() or not manifest_path:
        return output
    if "Run artifacts:" in output:
        return output
    return f"{output}\n\nRun artifacts: `{manifest_path}`"


async def _finalize_run_relay(
    deps: BridgeDeps,
    result: TeamResult,
    relay: _RunRelayContext | None,
    *,
    surface_ids: tuple[str, ...] = (),
    task: str = "",
    run_result: Any | None = None,
    attempt: int = 1,
) -> TeamResult:
    if relay is None:
        return result
    try:
        from bridge.run_artifacts import finalize_run_manifest

        manifest_path = finalize_run_manifest(
            relay.run_dir,
            status="success" if result.success else "failed",
            surfaces=surface_ids,
            telemetry=_manifest_telemetry(result),
        )
        manifest = _read_manifest_payload(manifest_path)
        artifacts = manifest.get("artifacts", [])
        artifact_count = len(artifacts) if isinstance(artifacts, list) else 0
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "run_relay.manifest_finalize_failed department=%s run_id=%s error=%s",
            result.department,
            relay.run_id,
            exc,
        )
        return result

    telemetry = result.telemetry
    if telemetry is not None:
        telemetry = dataclass_replace(telemetry, artifacts_written=artifact_count)
    relayed = dataclass_replace(
        result,
        run_id=relay.run_id,
        manifest_path=str(manifest_path),
        memory_ref=relay.memory_ref,
        telemetry=telemetry,
    )
    await _write_run_memory_note(deps, relayed, manifest_path)
    await _write_run_checkpoint(
        deps, relayed, relay, task=task, run_result=run_result, attempt=attempt
    )
    return dataclass_replace(
        relayed,
        manager_output=_append_run_artifacts_footer(
            relayed.manager_output,
            relayed.manifest_path,
        ),
    )


def _resolve_board_cross_vendor_flag() -> bool:
    """Read ``BridgeConfig.board_cross_vendor_enabled`` if importable.

    Sprint P3.3 / #1724 — production callers go through the real
    ``BridgeConfig`` so the live flag value (default ``False``) gates the
    Strategy Board's openrouter seats. Lightweight ``teams``-only unit
    fixtures may not have the bridge package available; in that case we
    fall back to ``True`` (include everything) which preserves pre-#1724
    behaviour and keeps offline tests green. Any unexpected exception is
    swallowed for the same reason — the fallback is the safer default
    than a hard import error at agent-construction time.
    """
    try:
        from bridge.config import BridgeConfig

        return bool(BridgeConfig().board_cross_vendor_enabled)
    except Exception:  # noqa: BLE001 — see docstring rationale
        return True


# Sprint 04.08 mapping (the ConversationLogger MessageType enum is intentionally
# small — DELEGATION, RESULT, BROADCAST, ERROR — and Sprint 04.08 spec is
# explicit about NOT extending it). The four conceptual events in the spec map
# to the existing enum as follows:
#
#   DIRECTIVE  (operator → manager)   → MessageType.DELEGATION
#   DELEGATION (manager  → employee)  → MessageType.DELEGATION
#   RESPONSE   (employee → manager)   → MessageType.RESULT
#   SYNTHESIS  (manager  → operator)  → MessageType.RESULT
#
# The from_agent / to_agent fields disambiguate. Readers can detect the
# directive vs delegate variant by checking from_agent == "operator", and the
# synthesis vs response variant by checking to_agent == "operator".
_OPERATOR_AGENT = "operator"


def _safe_log(
    logger: Optional[ConversationLogger],
    *,
    message_type: MessageType,
    from_agent: str,
    to_agent: str,
    content: str,
    session_id: str,
) -> None:
    """Append one conversation message; swallow any exception.

    A logging failure must never break a department run — drift telemetry can
    be partially missing without compromising the answer the operator gets.
    """
    if logger is None:
        return
    try:
        # ConversationLogger constructs ConversationMessage internally for
        # each message type; we use the public log_* helpers so message_id +
        # timestamp generation stays in one place.
        if message_type == MessageType.DELEGATION:
            logger.log_delegation(
                from_agent=from_agent,
                to_agent=to_agent,
                task=content,
                session_id=session_id,
            )
        elif message_type == MessageType.RESULT:
            logger.log_result(
                from_agent=from_agent,
                to_agent=to_agent,
                summary=content,
                session_id=session_id,
            )
        else:  # BROADCAST / ERROR — currently unused by DepartmentTeam.run
            logger.log_broadcast(
                from_agent=from_agent,
                content=content,
                session_id=session_id,
            )
    except Exception:  # noqa: BLE001
        log.exception(
            "department_team.conversation_log.append failed "
            "type=%s from=%s to=%s session=%s",
            message_type, from_agent, to_agent, session_id,
        )


def _format_timeout_error(
    timeout_seconds: int,
    employee_results: list[EmployeeResult],
) -> str:
    """Return an operator-actionable timeout summary."""
    total = len(employee_results)
    successful = sum(1 for er in employee_results if er.success)
    failed = total - successful
    parts = [
        f"Timeout after {timeout_seconds}s",
        f"partial_specialists={total}",
        f"successful={successful}",
        f"failed={failed}",
    ]

    last_failure = next(
        (er for er in reversed(employee_results) if not er.success),
        None,
    )
    if last_failure is not None:
        raw_error = (last_failure.error or "unknown").replace("\n", " ")
        if len(raw_error) > 160:
            raw_error = raw_error[:157].rstrip() + "..."
        parts.append(f"last_failure={last_failure.employee_name}: {raw_error}")

    return f"{parts[0]} ({'; '.join(parts[1:])})"


async def _synthesize_missing_result_surfaces(
    deps: BridgeDeps,
    directive_id: Optional[str],
    chief_name: str,
    employee_results: list,
) -> None:
    """Generate RESULT surfaces for specialists that forgot to call surface().

    Sprint 22 (Phase 5C): walks the per-(directive, chief) tasks in
    chronological order, pairs them positionally with the EmployeeResult
    entries from the run, and emits a synthesised RESULT surface
    (``payload.synthesized=true``) for any task that lacks one. Best-effort
    — failures log a warning but never raise.

    No-ops when ``deps.database`` is None or ``directive_id`` is None.
    Without a directive, we can't reliably pair Tasks to EmployeeResults
    (they're not joined by any other key today), so the synthesis is
    bounded to the directive flow. This is the spec's primary use case.
    """
    if directive_id is None or getattr(deps, "database", None) is None:
        return
    if not employee_results:
        return
    try:
        from datetime import datetime, timezone

        from bridge import surface_store, task_store
        from teams._types import Surface, SurfaceKind, Urgency

        # Fetch the tasks we created during this run (chronologically)
        tasks_for_directive = await task_store.list_by_directive(
            deps.database, directive_id
        )
        # Filter to tasks issued by this chief (defensive — list_by_directive
        # could in principle return tasks from cross-team delegations)
        own_tasks = [t for t in tasks_for_directive if t.from_chief == chief_name]
        # Pair positionally with employee_results in order
        for er, task in zip(employee_results, own_tasks):
            try:
                if await surface_store.task_has_result_surface(
                    deps.database, task.task_id
                ):
                    continue
                synthetic = Surface(
                    surface_id=surface_store.new_surface_id(),
                    from_agent=er.employee_name,
                    to_agent=chief_name,
                    kind=SurfaceKind.RESULT,
                    urgency=Urgency.FYI,
                    correlation_id=task.task_id,
                    payload={
                        "synthesized": True,
                        "output": er.output,
                        "success": er.success,
                        "error": er.error,
                    },
                    created_at_utc=datetime.now(timezone.utc),
                )
                await surface_store.insert_surface(deps.database, synthetic)
                log.warning(
                    "surface.synthesized_result task_id=%s specialist=%s "
                    "(specialist did not emit RESULT surface)",
                    task.task_id, er.employee_name,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "surface.synthesize_failed task_id=%s error=%s",
                    task.task_id, exc,
                )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "surface.synthesize_walk_failed directive_id=%s error=%s",
            directive_id, exc,
        )


async def _emit_chief_synthesis_surface(
    deps: BridgeDeps,
    directive_id: Optional[str],
    chief_name: str,
    manager_text: str,
    success: bool,
    relay_payload: Mapping[str, object] | None = None,
) -> Optional[str]:
    """Emit a RESULT surface from the chief to ``main`` on synthesis return.

    Sprint 22 (Phase 5C): even if the chief's LLM doesn't proactively call
    surface(), the dashboard wants a chief-to-main RESULT row per
    completed directive so the `/api/directives/{id}/tree` reader (Sprint
    23) can render the full graph.

    Sprint P3.5 (2026-05-11 audit): returns the chief→main RESULT
    ``surface_id``. If the chief proactively emitted one earlier in the
    run, that id is returned (no double-emit). If we synthesise a new
    one, the newly-minted id is returned. Returns None when database or
    directive_id is missing, or when emission failed best-effort.

    No-ops when database or directive_id is missing. Best-effort.
    """
    if directive_id is None or getattr(deps, "database", None) is None:
        return None
    try:
        from datetime import datetime, timezone

        from bridge import surface_store
        from teams._types import Surface, SurfaceKind, Urgency

        # Was a chief→main RESULT already emitted? Don't double-emit if the
        # chief's LLM proactively called surface(kind='result'). Return the
        # existing surface_id so callers can attach it to TeamResult.
        existing = await surface_store.list_by_correlation(deps.database, directive_id)
        for s in existing:
            if (
                s.from_agent == chief_name
                and s.to_agent == "main"
                and s.kind == SurfaceKind.RESULT
            ):
                return s.surface_id

        payload: dict[str, object] = {
            "synthesized": True,
            "answer": manager_text,
            "success": success,
        }
        if relay_payload:
            payload.update(relay_payload)

        synthesis = Surface(
            surface_id=surface_store.new_surface_id(),
            from_agent=chief_name,
            to_agent="main",
            kind=SurfaceKind.RESULT,
            urgency=Urgency.FYI,
            correlation_id=directive_id,
            payload=payload,
            created_at_utc=datetime.now(timezone.utc),
        )
        await surface_store.insert_surface(deps.database, synthesis)
        return synthesis.surface_id
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "surface.chief_synthesis_failed directive_id=%s error=%s",
            directive_id, exc,
        )
        return None


async def _safe_directive_status(
    deps: BridgeDeps,
    directive_id: Optional[str],
    new_status: str,
    *,
    note: Optional[str] = None,
) -> None:
    """Best-effort directive status transition.

    No-op when ``directive_id`` is None or ``deps.database`` is None.
    Catches every exception and logs a warning — directive lifecycle
    writes are observability, never flow control. The chief's actual
    work must not be gated on a successful audit-log write.

    Sprint 20 (Phase 5B).
    """
    if directive_id is None or getattr(deps, "database", None) is None:
        return
    try:
        from bridge import directive_store
        from teams._types import DirectiveStatus

        await directive_store.update_status(
            deps.database,
            directive_id,
            DirectiveStatus(new_status),
            note=note,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "directive.status_write_failed id=%s target_status=%s error=%s",
            directive_id, new_status, exc,
        )


# Sprint P3.4 (#1586) — mid-run cost-cap enforcement at the team boundary.
# WarmChief already enforces a session-level cost cap on its pre/post-flight
# (Z4-S41 #1399) but that path only fires when WarmChief is wrapping the
# call. Direct ``DepartmentTeam.run`` callers (cron, /route, tests) bypass
# WarmChief entirely. The team-side seam below adds the same kill at the
# team boundary so the cap holds regardless of who initiated the run.
#
# The check estimates this run's cost from ``total_tokens`` × the manager
# model's pricing (mirroring the D2.5 record path below) and compares it
# against ``config.constraints.cost_limit_usd``. The estimate uses the same
# 50/50 input/output split as the D2.5 record so the team-record price and
# the cap-check price agree. A breach flips ``success=False`` with a
# ``COST_CAP_EXCEEDED`` prefix on the error so observers (dispatcher,
# tests, daily log) can pattern-match the breach.
_COST_CAP_ERROR_PREFIX = "COST_CAP_EXCEEDED"


def _estimate_team_cost_usd(
    team_result: TeamResult, config: DepartmentConfig,
) -> float:
    """Estimate this run's cost in USD from token usage and manager model.

    Best-effort: a pricing-lookup failure returns 0.0 (the team_result
    field's default). The split mirrors the D2.5 record convention
    (50/50 input/output) so the cap-check value matches the recorded
    value for any downstream reader that pairs the two.
    """
    try:
        from bridge.cost_tracker import estimate_cost
    except Exception:  # noqa: BLE001
        return 0.0
    model_hint = getattr(config.manager, "model", None) or "sonnet"
    half = team_result.total_tokens // 2
    try:
        return float(estimate_cost(str(model_hint), half, half))
    except Exception:  # noqa: BLE001
        return 0.0


def _enforce_team_cost_cap(
    team_result: TeamResult, config: DepartmentConfig,
) -> TeamResult:
    """Return a new TeamResult flipped to failure if cost cap exceeded.

    P3.4 (#1586). The cap lives on ``config.constraints.cost_limit_usd``
    — the same value WarmChief's post-flight reads. A non-positive cap
    is treated as "no cap configured" and the team_result passes
    through unchanged. Existing violations on ``team_result.error``
    are preserved by joining the cap-error in front (so gate violators
    that also bust the cap still expose both).

    Under-cap (or no-cap) calls leave ``total_cost_usd`` untouched —
    cost attribution stays the responsibility of the existing
    ``cost_tracker.record`` call below and the WarmChief add_cost path.
    Only on the BREACH path do we populate ``total_cost_usd`` so the
    chief-session row carries the offending estimate downstream.
    """
    cap = float(getattr(config.constraints, "cost_limit_usd", 0.0) or 0.0)
    if cap <= 0:
        # No cap configured — pure passthrough.
        return team_result
    estimated = _estimate_team_cost_usd(team_result, config)
    if estimated <= cap:
        # Under cap — leave team_result alone. Attribution stays with
        # the existing D2.5 cost_tracker.record path below; we don't
        # double-write here.
        return team_result

    cap_error = (
        f"{_COST_CAP_ERROR_PREFIX}: estimated ${estimated:.4f} "
        f"exceeds cap ${cap:.4f} for department {config.name!r}"
    )
    combined_error = (
        f"{cap_error}; {team_result.error}"
        if team_result.error
        else cap_error
    )
    log.warning(
        "department_team.cost_cap_exceeded name=%s estimated=%.4f cap=%.4f",
        config.name, estimated, cap,
    )
    telemetry = telemetry_with_failure(team_result.telemetry, "cost_cap_exceeded")
    return dataclass_replace(
        team_result,
        total_cost_usd=estimated,
        success=False,
        error=combined_error,
        telemetry=telemetry,
    )


def _emit_daily_log(
    daily_log: Any,
    config: DepartmentConfig,
    result: TeamResult,
    session_id: str,
) -> None:
    """Emit one structured line to the daily log for a completed department run.

    Safe to call with daily_log=None (no-op). Never raises.
    """
    if daily_log is None:
        return
    try:
        status = "OK" if result.success else "FAIL"
        entry = (
            f"[Z4][{config.name.upper()}][{status} "
            f"cost=${result.total_cost_usd:.3f} "
            f"dur={result.duration_seconds:.1f}s "
            f"specialists={len(result.employee_results)}/{len(config.employees)}]"
        )
        daily_log.append(
            entry=entry,
            category="z4",
            correlation_id=session_id[:8] if session_id else None,
        )
    except Exception:  # noqa: BLE001
        # Never let logging failures propagate out of run()
        log.debug("department_team.daily_log_failed name=%s", config.name, exc_info=True)


def _extract_structured(raw_output: Any) -> tuple[str, Optional[TeamOutput]]:
    """Extract (manager_output_str, structured_TeamOutput) from raw agent output.

    Sprint B2.2: the manager returns a plain ``str``.  We attempt to parse it
    as a ``TeamOutput`` JSON object.  If parsing succeeds, we store the
    structured form; otherwise ``structured`` is ``None`` and the raw string
    is exposed as-is in ``manager_output``.

    This keeps backward-compatibility with ``TestModel(custom_output_text=...)``
    while allowing live managers to return structured JSON.
    """
    import json

    if isinstance(raw_output, TeamOutput):
        # Defensive: in case someone passes a TeamOutput directly
        return raw_output.answer, raw_output

    text = str(raw_output)

    # Attempt to parse as TeamOutput JSON
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "answer" in data:
            structured = TeamOutput.model_validate(data)
            return structured.answer, structured
    except Exception:  # noqa: BLE001
        pass

    # Plain text fallback — structured is None so gate 3 is skipped
    return text, None


class DepartmentTeam:
    """Runtime facade for a single department's Pydantic AI team.

    Lazy-builds agents on first access to the `manager` property.
    The `run()` method enforces the department's timeout and never raises.
    """

    def __init__(
        self,
        config: DepartmentConfig,
        *,
        lazy_build: bool = True,
        tool_tracker: Optional[Any] = None,
        daily_log: Optional[Any] = None,
        conversation_logger: Optional[ConversationLogger] = None,
        chief_session_id: str = "",
        skill_allocator: Optional[Any] = None,
        roster_registry: Optional[Any] = None,
    ) -> None:
        self._config = config
        self._manager: Optional[Agent[BridgeDeps, TeamOutput]] = None
        self._manager_fallback: Optional[Agent[BridgeDeps, TeamOutput]] = None
        self._employees: Optional[dict[str, Agent[BridgeDeps, str]]] = None
        self._tool_tracker = tool_tracker
        self._daily_log = daily_log
        self._conversation_logger = conversation_logger
        self._employee_results_collector: list[EmployeeResult] = []
        # Sprint #1112/4.03 (#2150) — SkillAllocator handed down by
        # WarmChief. Forwarded to build_*_agent at _build() time so each
        # agent's allowed-skill set is filtered by the central manifest
        # at construction. None (the default) preserves back-compat for
        # ad-hoc test fixtures — the factory treats None as "skip filter."
        self._skill_allocator: Optional[Any] = skill_allocator
        # Sprint RR.2 (issue #2593) — optional RosterRegistryStore handed down
        # by the dispatcher/WarmChief. At _build() time the team reads the
        # operator's runtime overlay (registered specialists) for this
        # department and passes it to build_manager_agent so the chief's
        # roster reflects registrations without a YAML redeploy. None (the
        # default) preserves back-compat for every test fixture and ad-hoc
        # construction site — the factory treats an empty overlay as "YAML
        # base only" (byte-identical to pre-RR.2). Cache-staleness is handled
        # store-side: register/unregister fire on_change → AgentCache.invalidate
        # so the next _build picks up the change.
        self._roster_registry: Optional[Any] = roster_registry
        # Sprint audit-2026-05-16.D.05 (#2066) — chief-session attribution
        # for the team's cost-record call. Threaded down from WarmChief
        # (which owns the canonical ``ChiefSession.session_id``) so
        # ``cost_tracker.last_session_measurement`` can answer "what did
        # this chief's last run cost?" against a populated field. Default
        # "" preserves back-compat for every test fixture and direct
        # construction site that doesn't run inside the dispatcher path.
        self._chief_session_id: str = chief_session_id
        # zone4-warmth.B.02 (#2294) — stash the PydanticAI RunResult from the
        # most recent ``run()`` call so the WarmChief lifecycle can serialize
        # ``message_history`` on the success path. Populated inside
        # ``run()`` after ``manager.run`` returns and reset to None on each
        # new ``run()`` invocation so a previous run's transcript never
        # leaks into the next session's persisted blob. None means "no run
        # has completed against this team instance yet" — the persistence
        # helper treats that as a no-op and leaves the column NULL.
        self._last_run_result: Optional[Any] = None
        if not lazy_build:
            self._build()

    def _registered_overlay(self) -> tuple[Any, ...]:
        """Read the operator's registered-specialist overlay for this dept.

        RR.2 (#2593). Returns the tuple of ``RegisteredSpecialist`` for this
        department from the wired ``RosterRegistryStore``, or an empty tuple
        when no registry is wired or the read fails. Best-effort: a registry
        read must never break chief construction — a registry hiccup degrades
        to the YAML-base roster, not a crashed build.
        """
        registry = self._roster_registry
        if registry is None:
            return ()
        try:
            return tuple(registry.list_for_department(self._config.name))
        except Exception:  # noqa: BLE001
            log.warning(
                "roster_overlay.read_failed department=%s — "
                "falling back to YAML base roster",
                self._config.name,
                exc_info=True,
            )
            return ()

    @property
    def config(self) -> DepartmentConfig:
        return self._config

    @property
    def manager(self) -> Agent[BridgeDeps, TeamOutput]:
        if self._manager is None:
            self._build()
        assert self._manager is not None
        return self._manager

    @property
    def employees(self) -> dict[str, Agent[BridgeDeps, str]]:
        if self._employees is None:
            self._build()
        assert self._employees is not None
        return self._employees

    def _capability_telemetry_fields(self) -> tuple[tuple[str, str], ...]:
        agents: list[Agent[BridgeDeps, Any]] = []
        if self._manager is not None:
            agents.append(self._manager)
        if self._employees is not None:
            agents.extend(self._employees.values())
        return capability_telemetry_fields(agents)

    def _build(self) -> None:
        log.info("department_team.build name=%s", self._config.name)
        # Reset collector on rebuild so a reused team doesn't accumulate across runs
        self._employee_results_collector = []
        # Sprint P3.3 / #1724 — consult BridgeConfig for the board cross-vendor
        # gate. Default ``True`` (back-compat) when the bridge package can't
        # be imported (e.g. teams-only unit fixtures); production wiring
        # reads the live flag so the chief's roster + employee map are
        # filtered consistently when the flag is OFF.
        cross_vendor_enabled = _resolve_board_cross_vendor_flag()
        self._employees = build_employee_agents(
            self._config,
            tracker=self._tool_tracker,
            cross_vendor_enabled=cross_vendor_enabled,
            skill_allocator=self._skill_allocator,
        )
        # RR.2 (#2593): read the operator's runtime roster overlay for this
        # department. Empty tuple when no registry is wired (tests, ad-hoc) or
        # nothing is registered — byte-identical to the pre-RR.2 YAML-only path.
        registered = self._registered_overlay()
        self._manager = build_manager_agent(
            self._config,
            self._employees,
            tracker=self._tool_tracker,
            employee_results_collector=self._employee_results_collector,
            cross_vendor_enabled=cross_vendor_enabled,
            skill_allocator=self._skill_allocator,
            registered=registered,
        )
        self._manager_fallback = None
        fallback_model = self._config.manager.fallback_model
        if fallback_model:
            fallback_config = dataclass_replace(
                self._config,
                manager=dataclass_replace(
                    self._config.manager,
                    model=fallback_model,
                ),
            )
            self._manager_fallback = build_manager_agent(
                fallback_config,
                self._employees,
                tracker=self._tool_tracker,
                employee_results_collector=self._employee_results_collector,
                cross_vendor_enabled=cross_vendor_enabled,
                skill_allocator=self._skill_allocator,
                registered=registered,
                # Keep fallback construction out of the global chief cache:
                # the production cache key is (team, chief_name), while this
                # agent deliberately uses the same chief name with a different
                # model.
                agent_cache=AgentCache(),
            )

    async def run(
        self,
        task: str,
        deps: BridgeDeps,
        *,
        directive_id: str | None = None,
        message_history: list[Any] | None = None,
        resume_from: str | None = None,
    ) -> TeamResult:
        """Execute a task through the department's manager.

        Never raises. Errors produce TeamResult with success=False.
        Emits one structured line to the daily log on completion (if wired).
        Populates employee_results from delegation tool captures (sprint B2.1).

        Sprint 20 (Phase 5B): when ``directive_id`` is supplied AND
        ``deps.database`` is non-None, lifecycle transitions are written to
        the directive_store: IN_PROGRESS just before the manager runs, DONE
        on clean return, BLOCKED on timeout or unhandled exception. Status
        writes are best-effort — a failed audit-log write never blocks the
        chief's actual work. When ``directive_id`` is None, no status writes
        happen and the existing flow is preserved exactly.

        WS2.5 (#2570): when ``resume_from`` names a prior run directory under
        ``deps.artifact_root``, the checkpoint there is loaded before the
        manager runs. A missing checkpoint or an unresumable one short-circuits
        to a failure ``TeamResult`` (``failure_class`` ``checkpoint_missing`` /
        ``checkpoint_unresumable``) WITHOUT invoking the manager. A resumable
        checkpoint reloads its ``message_history`` (overriding any caller-passed
        history), pre-seeds the run collector with the prior
        ``completed_specialists`` so Gate 8 counts them, writes new artifacts
        into the SAME run directory, and increments the checkpoint ``attempt``.
        """
        # zone4-warmth.B.02 (#2294) — reset the captured run result at the
        # top of each run so a prior run's transcript never bleeds into a
        # subsequent call, including early policy refusals.
        self._last_run_result = None

        resume_seed: tuple[EmployeeResult, ...] = ()
        next_attempt = 1
        if resume_from is not None:
            resume = _resolve_resume(deps, resume_from)
            if isinstance(resume, str):
                return TeamResult(
                    department=self._config.name,
                    manager_output="",
                    success=False,
                    error=f"resume failed: {resume} (run_id={resume_from})",
                    telemetry=_build_run_telemetry(
                        self._config,
                        failure_class=resume,
                        extra=self._capability_telemetry_fields(),
                    ),
                )
            message_history = resume.message_history
            resume_seed = resume.completed_specialists
            next_attempt = resume.attempt
            # Resume writes its new artifacts into the SAME run directory so the
            # checkpoint is overwritten in place (attempt N → N+1).
            deps = dataclass_replace(deps, run_artifact_dir=resume.run_dir)

        if policy_refusal := _openrouter_zone4_policy_refusal(self._config):
            log.warning(
                "department_team.openrouter_zone4_route_refused "
                "name=%s error=%s",
                self._config.name,
                policy_refusal.error,
            )
            return policy_refusal

        breaker = get_registry().get(self._config.name)

        # Sprint P3.5 (2026-05-11 audit): in production directive flows the
        # chief→main RESULT surface is a required handoff artifact. Refuse
        # to start the run when a directive_id is supplied but the surface
        # store can't be reached. Tests pass allow_no_surface_store=True to
        # keep the lightweight no-DB construction valid.
        allow_no_store = bool(getattr(deps, "allow_no_surface_store", False))
        if (
            directive_id is not None
            and getattr(deps, "database", None) is None
            and not allow_no_store
        ):
            return TeamResult(
                department=self._config.name,
                manager_output="",
                success=False,
                error=(
                    "missing surface store: directive_id supplied but "
                    "BridgeDeps.database is None and "
                    "allow_no_surface_store=False"
                ),
                telemetry=_build_run_telemetry(
                    self._config,
                    failure_class="missing_surface_store",
                    extra=self._capability_telemetry_fields(),
                ),
            )

        try:
            breaker.before_call()
        except CircuitOpenError:
            return TeamResult(
                department=self._config.name,
                manager_output="",
                success=False,
                error=f"circuit open for {self._config.name}: retry after cooldown",
                telemetry=_build_run_telemetry(
                    self._config,
                    failure_class="circuit_open",
                    extra=self._capability_telemetry_fields(),
                ),
            )

        # Use a fresh collector for each run. DepartmentTeam instances are
        # cached and may handle concurrent invocations for the same
        # department; reusing ``self._employee_results_collector`` lets one
        # run clear another run's specialist results before Gate 8.
        #
        # WS2.5 (#2570): on a resume, pre-seed the collector with the prior
        # run's completed specialists so Gate 8's floor counts prior work; the
        # manager's new delegations append after the seed.
        run_employee_results_collector: list[EmployeeResult] = list(resume_seed)

        manager_name = self._config.manager.name
        session_id = getattr(deps, "session_id", "") or ""
        deps, run_relay = _prepare_run_relay(
            deps,
            self._config,
            directive_id=directive_id,
        )

        # Sprint 04.08: directive (operator → manager) — fired before the
        # manager call so the JSONL captures intent even if the manager errors.
        _safe_log(
            self._conversation_logger,
            message_type=MessageType.DELEGATION,
            from_agent=_OPERATOR_AGENT,
            to_agent=manager_name,
            content=task,
            session_id=session_id,
        )

        start = time.monotonic()
        timeout = self._config.constraints.timeout_seconds

        # Sprint 20: mark IN_PROGRESS just before the manager runs. If the
        # chief calls acknowledge_directive() during the run that overwrites
        # IN_PROGRESS with ACCEPTED — both transitions are recorded in
        # directive_history so the order is reconstructible. This is a
        # belt-and-braces marker that the run reached the manager call site.
        await _safe_directive_status(
            deps, directive_id, "in_progress", note="manager run started"
        )

        # Issue #1970 + Z4-18 — resolve Constraints.usage_limits through the
        # provider-aware policy before passing pydantic-ai's run-time cap.
        # The first policy rollout preserves configured caps and adds
        # provider/preflight telemetry; it does not lower production limits.
        usage_policy = _resolve_usage_policy(self._config)
        usage_limits = _resolve_usage_limits(
            self._config.constraints,
            model=self._config.manager.model,
        )
        preflight_context_chars = estimate_preflight_context_chars(
            task=task,
            message_history=message_history,
        )
        log.info(
            "department_team.preflight_context_estimate "
            "name=%s provider=%s model=%s preflight_context_chars=%d "
            "policy_limit_chars=%d provider_context_window_tokens=%d "
            "clear_warm_context_after_tokens=%d",
            self._config.name,
            usage_policy.provider,
            self._config.manager.model,
            preflight_context_chars,
            usage_policy.preflight_context_chars,
            usage_policy.provider_context_window_tokens,
            usage_policy.clear_warm_context_after_tokens,
        )

        # Sprint zone4-warmth (#2313, 2026-05-18): thread this run's
        # ``employee_results_collector`` through deps so the chief's
        # ``delegate`` tool reads it from ``ctx.deps`` rather than from a
        # closure captured at chief-build time. Required because the chief
        # Agent is cached (A.02 / #2306); without per-run deps the delegate
        # tool would forever append to the FIRST team's collector, leaving
        # ``team.employee_results`` empty on every warm-reuse run. Use
        # ``dataclasses.replace`` because ``BridgeDeps`` is frozen — never
        # mutate the caller's deps object. When the caller already supplied
        # a collector via deps (custom test fixtures), we respect it and
        # do not overwrite.
        if getattr(deps, "employee_results_collector", None) is None:
            deps = dataclass_replace(
                deps, employee_results_collector=run_employee_results_collector
            )
        else:
            run_employee_results_collector = deps.employee_results_collector

        # zone4-warmth.C.03 (#2297) — pass ``message_history`` only when
        # supplied. PydanticAI's ``Agent.run`` accepts ``None`` for this
        # kwarg, but threading the kwarg conditionally keeps test mocks
        # that assert on call_args clean — the unset case looks identical
        # to pre-C.03 callers (no extra kwarg in ``manager.run`` calls
        # without history).
        manager_run_kwargs: dict[str, Any] = {
            "deps": deps,
            "usage_limits": usage_limits,
        }
        if message_history is not None:
            manager_run_kwargs["message_history"] = message_history
            log.info(
                "department_team.reload_history department=%s n_messages=%d",
                self._config.name,
                len(message_history),
            )
        active_manager_model = self._config.manager.model
        fallback_model_used: str | None = None
        fallback_reason: str | None = None
        try:
            async with asyncio.timeout(timeout):
                try:
                    result = await self.manager.run(task, **manager_run_kwargs)
                except Exception as exc:
                    fallback_model = self._config.manager.fallback_model
                    if (
                        not fallback_model
                        or self._manager_fallback is None
                        or not _is_model_rate_limit_error(exc)
                    ):
                        raise
                    run_employee_results_collector.clear()
                    # WS2.5 (#2570): clearing discards only the primary
                    # attempt's delegations; restore the resume pre-seed so the
                    # fallback run still counts prior work.
                    run_employee_results_collector.extend(resume_seed)
                    log.warning(
                        "department_team.manager_rate_limited_fallback "
                        "name=%s primary_model=%s fallback_model=%s error=%s",
                        self._config.name,
                        self._config.manager.model,
                        fallback_model,
                        exc,
                    )
                    # audit-2026-06-11: surface the fallback transition on the
                    # EventBus so the operator sees rate-limit → fallback
                    # switches, not just a process-log line. Best-effort —
                    # never blocks the fallback run itself.
                    try:
                        from bridge.event_bus import (
                            DEPARTMENT_MANAGER_FALLBACK,
                            EventBus,
                        )

                        EventBus.get_instance().publish(
                            DEPARTMENT_MANAGER_FALLBACK,
                            {
                                "department": self._config.name,
                                "primary_model": self._config.manager.model,
                                "fallback_model": fallback_model,
                                "reason": "http_429",
                            },
                        )
                    except Exception:
                        pass
                    result = await self._manager_fallback.run(
                        task, **manager_run_kwargs
                    )
                    active_manager_model = fallback_model
                    fallback_model_used = fallback_model
                    fallback_reason = "http_429"
            # zone4-warmth.B.02 (#2294) — capture the PydanticAI RunResult so
            # WarmChief can serialize ``result.all_messages()`` on success.
            # Stored unconditionally; the WarmChief helper only reads on the
            # AWAITING_EVALUATION success path so a verify-gate failure or
            # cost-cap breach won't trigger persistence.
            self._last_run_result = result
            duration = time.monotonic() - start

            usage = result.usage() if hasattr(result, "usage") and callable(result.usage) else None
            total_tokens = total_tokens_from_usage(usage)

            manager_text, structured = _extract_structured(result.output)

            # Sprint 04.08: emit one DELEGATION + one RESULT pair per
            # captured employee result, then a single synthesis line. Done
            # AFTER the manager run so the order in the JSONL reflects the
            # delegation order recorded by employee_results_collector.
            for er in run_employee_results_collector:
                _safe_log(
                    self._conversation_logger,
                    message_type=MessageType.DELEGATION,
                    from_agent=manager_name,
                    to_agent=er.employee_name,
                    # The collector does not carry the per-delegation prompt
                    # (only the response). Use the originating task as the
                    # delegation content — this is the most faithful proxy
                    # available without a second collection pass.
                    content=task,
                    session_id=session_id,
                )
                _safe_log(
                    self._conversation_logger,
                    message_type=MessageType.RESULT,
                    from_agent=er.employee_name,
                    to_agent=manager_name,
                    content=er.output,
                    session_id=session_id,
                )

            # Synthesis (manager → operator) — content is the manager's final
            # answer text; structured form is preserved separately in
            # team_result.structured.
            _safe_log(
                self._conversation_logger,
                message_type=MessageType.RESULT,
                from_agent=manager_name,
                to_agent=_OPERATOR_AGENT,
                content=manager_text,
                session_id=session_id,
            )

            breaker.record_success()
            team_result = TeamResult(
                department=self._config.name,
                manager_output=manager_text,
                employee_results=tuple(run_employee_results_collector),
                total_tokens=total_tokens,
                duration_seconds=duration,
                success=True,
                error=None,
                structured=structured,
                telemetry=_build_run_telemetry(
                    self._config,
                    usage=usage,
                    employee_results=tuple(run_employee_results_collector),
                    fallback_model=fallback_model_used,
                    fallback_reason=fallback_reason,
                    duration_seconds=duration,
                    extra=self._capability_telemetry_fields(),
                ),
            )

            # Sprint B2.3: run 7 output gates; on violation, flip success=False
            violations = verify_team_result(team_result, self._config)
            if violations:
                team_result = dataclass_replace(
                    team_result,
                    success=False,
                    error="; ".join(violations),
                    telemetry=telemetry_with_failure(
                        team_result.telemetry,
                        "output_gate_violation",
                    ),
                )

            # P3.4 (#1586): team-side mid-run cost-cap check. Populates
            # ``total_cost_usd`` from the run's token usage and flips
            # ``success=False`` with a ``COST_CAP_EXCEEDED:`` error when
            # the estimated cost exceeds ``config.constraints.cost_limit_usd``.
            # Runs after the verify gates so a gate violator that ALSO busts
            # the cap surfaces both (the cap error is prepended to the
            # existing error string). When no cap is configured this is a
            # pure passthrough that still attributes the estimated cost
            # back onto ``team_result.total_cost_usd`` for the WarmChief
            # add_cost path.
            cost_config = self._config
            if active_manager_model != self._config.manager.model:
                cost_config = dataclass_replace(
                    self._config,
                    manager=dataclass_replace(
                        self._config.manager,
                        model=active_manager_model,
                    ),
                )
            team_result = _enforce_team_cost_cap(team_result, cost_config)

            # Sprint 22 (Phase 5C): synthesise missing specialist→chief
            # RESULT surfaces and emit the chief→main synthesis surface.
            # Both are best-effort; failures never affect team_result.
            await _synthesize_missing_result_surfaces(
                deps, directive_id, manager_name,
                run_employee_results_collector,
            )
            relay_payload = None
            if run_relay is not None:
                relay_payload = build_run_relay_payload(
                    team_result,
                    run_relay.manifest_path,
                    memory_ref=run_relay.memory_ref,
                )
            chief_surface_id = await _emit_chief_synthesis_surface(
                deps, directive_id, manager_name, manager_text,
                team_result.success,
                relay_payload=relay_payload,
            )

            # Sprint P3.5 (2026-05-11 audit): expose the chief→main RESULT
            # surface_id on TeamResult so callers (ChiefDispatcher, REST
            # readers, daily log) can correlate the session to its handoff
            # row. Immutable update via reconstruction; defaults to None
            # when no directive_id was supplied.
            if chief_surface_id is not None:
                telemetry = team_result.telemetry
                if telemetry is not None:
                    telemetry = dataclass_replace(
                        telemetry,
                        surfaces_written=telemetry.surfaces_written + 1,
                    )
                team_result = dataclass_replace(
                    team_result,
                    surface_id=chief_surface_id,
                    telemetry=telemetry,
                )

            team_result = await _finalize_run_relay(
                deps,
                team_result,
                run_relay,
                surface_ids=(chief_surface_id,) if chief_surface_id else (),
                task=task,
                run_result=self._last_run_result,
                attempt=next_attempt,
            )

            # Sprint 20: terminal transition. Synthesis-gate violations land
            # success=False on team_result; reflect that in the directive
            # status as BLOCKED rather than DONE.
            if team_result.success:
                await _safe_directive_status(
                    deps, directive_id, "done", note="manager synthesis returned"
                )
            else:
                await _safe_directive_status(
                    deps, directive_id, "blocked",
                    note=f"output gate violations: {team_result.error}",
                )

            _emit_daily_log(self._daily_log, self._config, team_result, deps.session_id)

            # D2.5: record team cost into cost_tracker so per-team summaries work.
            # Best-effort — never let cost-recording failure propagate.
            #
            # Sprint audit-2026-05-16.D.05 (#2066, audit M-2): also pass
            # ``chief_session_id`` (owned by the constructor; threaded down
            # from WarmChief in the dispatcher path) so per-chief-session
            # cost queries see this entry. Empty when the team was
            # constructed outside the dispatcher path — preserves the
            # legacy un-attributed bucket for back-compat.
            try:
                ct = getattr(deps, "cost_tracker", None)
                if ct is not None and hasattr(ct, "record"):
                    model_hint = getattr(
                        cost_config.manager, "model", None
                    ) or "sonnet"
                    ct.record(
                        model=str(model_hint),
                        input_tokens=team_result.total_tokens // 2,
                        output_tokens=team_result.total_tokens // 2,
                        task_type="team_run",
                        session_id=deps.session_id,
                        team=self._config.name,
                        chief_session_id=self._chief_session_id,
                        # WS3.2 (#2570): tag this existing team_run row with the
                        # workflow name when the call originates from a workflow
                        # step. We do NOT add a second record — that would
                        # double-count the same route()'s tokens in the daily
                        # total. Empty when not a workflow-driven run.
                        workflow=getattr(deps, "workflow", ""),
                    )
            except Exception:  # noqa: BLE001
                pass

            return team_result
        except asyncio.TimeoutError:
            breaker.record_failure()
            duration = time.monotonic() - start
            log.warning(
                "department_team.timeout name=%s duration=%.1fs",
                self._config.name, duration,
            )
            await _safe_directive_status(
                deps, directive_id, "blocked",
                note=f"manager timeout after {timeout}s",
            )
            team_result = TeamResult(
                department=self._config.name,
                manager_output="",
                employee_results=tuple(run_employee_results_collector),
                duration_seconds=duration,
                success=False,
                error=_format_timeout_error(
                    timeout,
                    run_employee_results_collector,
                ),
                telemetry=_build_run_telemetry(
                    self._config,
                    employee_results=tuple(run_employee_results_collector),
                    fallback_model=fallback_model_used,
                    fallback_reason=fallback_reason,
                    failure_class="timeout",
                    duration_seconds=duration,
                    extra=self._capability_telemetry_fields(),
                ),
            )
            team_result = await _finalize_run_relay(
                deps,
                team_result,
                run_relay,
                task=task,
                run_result=self._last_run_result,
                attempt=next_attempt,
            )
            _emit_daily_log(self._daily_log, self._config, team_result, deps.session_id)
            return team_result
        except Exception as e:  # noqa: BLE001
            breaker.record_failure()
            duration = time.monotonic() - start
            log.exception(
                "department_team.error name=%s error=%s",
                self._config.name, e,
            )
            await _safe_directive_status(
                deps, directive_id, "blocked",
                note=f"{type(e).__name__}: {e}",
            )
            team_result = TeamResult(
                department=self._config.name,
                manager_output="",
                employee_results=tuple(run_employee_results_collector),
                duration_seconds=duration,
                success=False,
                error=f"{type(e).__name__}: {e}",
                telemetry=_build_run_telemetry(
                    self._config,
                    employee_results=tuple(run_employee_results_collector),
                    fallback_model=fallback_model_used,
                    fallback_reason=fallback_reason,
                    failure_class=(
                        usage_limit_failure_class(e) or normalize_failure_class(e)
                    ),
                    duration_seconds=duration,
                    extra=self._capability_telemetry_fields(),
                ),
            )
            team_result = await _finalize_run_relay(
                deps,
                team_result,
                run_relay,
                task=task,
                run_result=self._last_run_result,
                attempt=next_attempt,
            )
            _emit_daily_log(self._daily_log, self._config, team_result, deps.session_id)
            return team_result

    async def run_parallel(
        self,
        tasks: list[str],
        deps: "BridgeDeps | None" = None,
    ) -> list[TeamResult]:
        """Run multiple tasks concurrently. Returns one TeamResult per task.

        Uses asyncio.gather(return_exceptions=True) so individual task failures
        do not abort the batch. Failed tasks return a TeamResult with success=False.
        """

        async def _run_one(task: str) -> TeamResult:
            try:
                return await self.run(task, deps=deps)
            except Exception as exc:
                return TeamResult(
                    department=self._config.name,
                    manager_output="",
                    success=False,
                    error=str(exc),
                    telemetry=_build_run_telemetry(
                        self._config,
                        failure_class=(
                            usage_limit_failure_class(exc)
                            or normalize_failure_class(exc)
                        ),
                        extra=self._capability_telemetry_fields(),
                    ),
                )

        results = await asyncio.gather(*[_run_one(t) for t in tasks], return_exceptions=False)
        return list(results)
