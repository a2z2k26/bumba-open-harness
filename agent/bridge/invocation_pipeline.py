"""Invocation pipeline — Stage 2 of BridgeApp message processing.

Sprint P6.1 (#1591) — extracted verbatim from ``BridgeApp._invoke_claude``
to make the long stage independently readable, testable, and replaceable.
Public behavior is identical to the inline body that lived in ``app.py``
prior to this extraction.

Entry point:
    ``await invoke_claude_pipeline(app, ctx)`` — takes the ``BridgeApp``
    instance as a dependency bag and returns a new ``MessageContext``.

Narrow seam preserved on the BridgeApp side:
    ``app._decide_use_warm(model, intent, has_tools, is_workorder)`` — the
    warm-vs-one-shot decision delegates to that method instead of calling
    ``should_use_warm_path`` inline. This keeps the warm-policy module
    swappable without touching this pipeline.

The four ``_INTENT_*`` helpers (``_INTENT_SKILL_MAP``, ``_intent_to_skill``,
``_INTENT_TO_MODALITY``, ``_intent_to_modality_name``) intentionally stay
in ``bridge.app`` to honor the source-grep contract used by
``test_workorder_skill_populated.py``. This module imports them lazily
from ``bridge.app`` at call time to avoid a circular import.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .claude_runner import ClaudeResult  # noqa: F401  (re-exported in app.py docstrings)
from .few_shot import classify_task_type
from .intent_classifier import classify as _classify_message_intent
from .lifecycle import State as LifecycleState
from .model_router import CAREFUL_OPUS_MODEL, classify, strip_model_override
from .modality_loader import load_for_intent as _load_modality_for_intent
from .self_healing import invoke_with_retry

if TYPE_CHECKING:  # pragma: no cover — typing only
    from .app import BridgeApp, MessageContext


logger = logging.getLogger(__name__)


def memory_md_block(app: "BridgeApp") -> str:
    """Return the MEMORY.md distilled index as a context block, or ``""``.

    Consumer side of the MEMORY.md injection wire (#2599). Reads the
    ``MemoryFile`` set via ``BridgeApp.set_memory_file`` and formats its
    content for prepending into the assembled Claude context. Returns an
    empty string — never raises — when:

    - the wire is dormant (``_memory_file`` is ``None`` or absent), or
    - MEMORY.md has not been written yet (empty content).

    Best-effort: any failure reading the file degrades to ``""`` so a
    memory-file problem can never break context assembly (the exact
    fail-open discipline used by the modality/few-shot injectors below).
    """
    memory_file = getattr(app, "_memory_file", None)
    if memory_file is None:
        return ""
    try:
        content = memory_file.get_memory_context()
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory_md_block: get_memory_context failed: %s", exc)
        return ""
    if not content or not content.strip():
        return ""
    return (
        "## DISTILLED MEMORY (MEMORY.md)\n"
        "Your long-term distilled knowledge index. Treat as background context.\n\n"
        f"{content}"
    )


async def invoke_claude_pipeline(app: "BridgeApp", ctx: "MessageContext") -> "MessageContext":
    """Stage 2: Session resolution, context assembly, Claude subprocess call.

    Returns a new ``MessageContext`` with ``result``, ``session_id``, and
    ``resume_id`` populated.

    Dispatcher branch (feature-flagged):
    If ``config.dispatcher_enabled`` is True and a Dispatcher is wired, this
    method first creates a WorkOrder from the incoming message and hands it off
    to the Dispatcher.  If the Dispatcher returns ``handled=True``, its result
    is returned directly and the rest of the stage is skipped.

    Fallthrough invariant: if ``dispatch_result.handled`` is False (because the
    Dispatcher chose not to handle the order, encountered an error, or the flag
    is off), execution ALWAYS continues through the normal session-resolve /
    context-assemble / claude-invoke path below.  The Dispatcher is purely
    additive — it never silently swallows a request.
    """
    # Lazy imports to avoid circular dependency with app.py — the four
    # _INTENT_* helpers (per source-grep contract) and the MessageContext
    # dataclass live in app.py.
    from .app import (
        MessageContext,
        _intent_to_skill,
        _intent_to_modality_name,
    )

    msg = ctx.msg

    # Sprint D-R4 (#1934) — MessageClassifier is the primary routing
    # decision. Computed once at the top of the pipeline; the result
    # drives both the dispatcher branch (ZONE4_EXPLICIT only) and the
    # task-framing preamble injection (TASK type) below. For
    # CONVERSATIONAL and INFORMATION_REQUEST the dispatcher branch is
    # skipped entirely — no intent_classifier call needed.
    from .message_classifier import (
        MessageType as _MessageType,
        classify as _classify_message,
    )
    _mc = _classify_message(msg.text)
    logger.debug(
        "message_classifier: type=%s confidence=%.2f signal=%s elapsed=%.1fms",
        _mc.message_type.value,
        _mc.confidence,
        _mc.matched_signal,
        _mc.elapsed_ms,
    )
    # Emit per-type metric — registered in
    # config/registry/metrics/message-classifier.yaml.
    if app._metrics is not None:
        try:
            app._metrics.increment(
                f"message_classifier.{_mc.message_type.value}"
            )
        except Exception as _mc_metric_exc:
            logger.debug(
                "message_classifier metric emit failed (non-fatal): %s",
                _mc_metric_exc,
            )

    # Stage 2 dispatcher branch (Zone 3 keystone — flag stays False until Z3.11)
    # Invariant: if dispatch_result.handled is False, fall through to direct invoke.
    #
    # Sprint D-R2 (#1932) — intent gate. Before D-R2, every operator message
    # built a WorkOrder and dispatched it (10-min latency cascade per #1931).
    # The gate restricts dispatcher entry to messages whose classified intent
    # is in ZONE4_INTENTS with confidence >= DISPATCHER_MIN_CONFIDENCE. All
    # other traffic falls through to the warm-process direct-invoke path.
    #
    # Sprint D-R4 (#1934) — the D-R2 gate is now a *secondary* guard
    # gated by MessageClassifier above. Only ZONE4_EXPLICIT messages
    # reach this block; everything else skipped the dispatcher entirely.
    if (
        _mc.message_type == _MessageType.ZONE4_EXPLICIT
        and app._config is not None
        and getattr(app._config, "dispatcher_enabled", False)
        and app._dispatcher is not None
    ):
        from .intent_classifier import (
            DISPATCHER_MIN_CONFIDENCE,
            ZONE4_INTENTS,
            classify as _classify_intent_for_gate,
        )
        _gate_classification = _classify_intent_for_gate(msg.text)
        _gate_pass = (
            _gate_classification.intent in ZONE4_INTENTS
            and _gate_classification.confidence >= DISPATCHER_MIN_CONFIDENCE
        )
        if not _gate_pass:
            logger.debug(
                "Dispatcher gate: skipping (intent=%s confidence=%.2f) "
                "— routing to warm process",
                _gate_classification.intent.value,
                _gate_classification.confidence,
            )
    else:
        _gate_pass = False

    if _gate_pass:
        try:
            from .work_order import WorkOrder, WorkOrderStatus
            classified_skill = _intent_to_skill(
                _classify_message_intent(msg.text).intent.value
            )
            wo = WorkOrder.create(
                intent=msg.text[:200],
                skill=classified_skill,
                project="",
            )
            # Consult EnvironmentSelector to choose environment (S02d).
            # Falls back to SUBAGENT if selector not yet initialized.
            #
            # Sprint S2.3 followup (#2326) — thread the dispatcher's
            # executor-status map into select() so the automatic path
            # cannot return a stubbed/non-routable executor. The
            # selector treats a None map as "preserve historical
            # behaviour", so the guard only applies when a dispatcher
            # is wired.
            if app._env_selector is not None:
                executor_statuses = (
                    app._dispatcher.get_executor_statuses()
                    if app._dispatcher is not None
                    else None
                )
                env, rationale = app._env_selector.select(
                    wo, executor_statuses=executor_statuses
                )
                # Sprint 03.07 — convert skew warning into a first-class
                # dispatch signal: log at WARNING, publish on the
                # autonomy event bus, and thread the warning into the
                # WorkOrder rationale so downstream observers (synth,
                # WorkOrder store, audit) see it. validate_selection
                # returns None when there is no skew. Note: when
                # force_alternative=True the selector has already
                # rebalanced, so the chosen env will not itself be in
                # the skew report and validate returns None — the
                # warning fires only when the default was kept.
                skew_warning = app._env_selector.validate_selection(env, rationale)
                if skew_warning is not None:
                    logger.warning(
                        "dispatcher: env_selector skew detected for "
                        "workorder=%s env=%s — %s",
                        wo.id, env.value, skew_warning,
                    )
                    _evt_bus = (
                        app._autonomy.event_bus
                        if app._autonomy is not None
                        else None
                    )
                    if _evt_bus is not None:
                        _evt_bus.publish(
                            "dispatcher.selector_skew_warning",
                            {
                                "workorder_id": wo.id,
                                "environment": env.value,
                                "skew_warning": skew_warning,
                            },
                        )
                    rationale = f"{rationale} | skew_warning: {skew_warning}"
            else:
                from .work_order import Environment
                env, rationale = Environment.SUBAGENT, "selector-unavailable: subagent default"
            wo = wo.with_environment(env, rationale)
            # Sprint 03.04 — plumb department_target so DepartmentExecutor
            # can resolve the team via the registry. Without this the
            # executor raises ValueError("unknown department: ") and
            # every department dispatch silently burns a retry.
            from .environment_selector import _derive_department
            from .work_order import Environment as _Env
            _derived_dept = _derive_department(classified_skill)
            if _derived_dept is not None and env is _Env.DEPARTMENT:
                wo = wo.with_department(_derived_dept)
            wo = wo.transition(WorkOrderStatus.ASSIGNED)
            dispatch_result = await app._dispatcher.dispatch(wo)
            # Record selector usage after dispatch (AC-7)
            if app._env_selector is not None:
                app._env_selector.record_usage(env)
            logger.info(
                "Dispatcher result: handled=%s reason=%s",
                dispatch_result.handled,
                dispatch_result.reason,
            )
            if dispatch_result.handled and dispatch_result.result is not None:
                # Dispatcher fully handled the request — advance lifecycle through
                # SPAWNING → ACTIVE so that the COMPLETING transition in
                # _process_single_message does not raise InvalidTransition.
                if app._lifecycle:
                    app._lifecycle.reset()
                    app._lifecycle.transition(LifecycleState.SPAWNING)
                    app._lifecycle.transition(LifecycleState.ACTIVE)
                # Resolve a session so downstream stages have a session_id.
                _disp_session_id = await app._session_mgr.resolve_session(msg.chat_id)
                if _disp_session_id is None:
                    _disp_session_id = await app._session_mgr.create_session(msg.chat_id)
                _disp_resume_id = await app._session_mgr.get_resume_id(msg.chat_id)
                # Build a full MessageContext so downstream stages (post-process,
                # deliver, telemetry) have all the fields they expect.
                return MessageContext(
                    msg=msg,
                    correlation_id=ctx.correlation_id,
                    msg_start=ctx.msg_start,
                    claude_breaker=ctx.claude_breaker,
                    session_id=_disp_session_id,
                    resume_id=_disp_resume_id,
                    result=dispatch_result.result,
                )
            # handled=False → fall through to direct invocation below
        except Exception as _disp_exc:
            logger.warning("Dispatcher error (falling through to direct invoke): %s", _disp_exc)
        # Direct invoke path continues below (flag off OR handled=False OR error)

    # Lifecycle: IDLE -> SPAWNING
    if app._lifecycle:
        app._lifecycle.reset()
        app._lifecycle.transition(LifecycleState.SPAWNING)

    # Resolve session
    session_id = await app._session_mgr.resolve_session(msg.chat_id)
    _new_session = session_id is None
    if _new_session:
        session_id = await app._session_mgr.create_session(msg.chat_id)

    # Get Claude's real session_id for --resume (None for new sessions)
    resume_id = await app._session_mgr.get_resume_id(msg.chat_id)

    # Record session start in project progress (non-blocking)
    if _new_session and app._project_registry:
        _active_proj = app._project_registry.get_active_project_name()
        if _active_proj:
            try:
                app._project_registry.record_session_start(_active_proj, session_id)
                logger.debug("Progress: session start recorded for project '%s'", _active_proj)
            except Exception as _pse:
                logger.debug("Progress session start failed (non-fatal): %s", _pse)

    # Assemble context and write temp file
    context = await app._memory.assemble_context(msg.chat_id, session_id, user_message=msg.text)

    # MEMORY.md distilled-index injection (#2599). Prepend the distilled
    # long-term memory index so it sits near the top of the context window
    # (Claude weights the beginning heavily). Empty string when the wire is
    # dormant or the file is unwritten — a no-op in that case, so flag-free.
    _memory_md = memory_md_block(app)
    if _memory_md:
        context = _memory_md + "\n\n" + context

    # Operator priority instruction — at BOTH start and end of context
    # (Claude weights beginning and end of context most heavily)
    operator_priority = (
        "## OPERATOR PRIORITY\n"
        "You are receiving a NEW message from the operator. "
        "This message takes ABSOLUTE PRIORITY over any prior task, plan, or in-progress work. "
        "Read and respond to the operator's current message directly. "
        "Do NOT continue prior work unless the operator explicitly says 'continue'.\n"
        "Do NOT modify files in /opt/bumba-harness/agent-flat/ directly — work in /tmp/ for code changes, then PR.\n"
        "All code changes must go through git branches and PRs on GitHub."
    )
    context = operator_priority + "\n\n" + context + "\n\n" + operator_priority

    # Modality preamble injection (D1.3) — prepend the Chameleon supplement
    # that matches the message's classified intent so engineering-class messages
    # arrive at Claude with the engineer-modality preamble, design messages with
    # the communicator preamble, etc.  Seam: app.py::_invoke_claude because
    # intent_classifier is already imported here and "context" is assembled here
    # before being written to the system_prompt_file temp file.
    if app._config is not None:
        _modalities_dir = Path(app._config.claude_working_dir) / "config" / "modalities"
        _classified_intent = _classify_message_intent(msg.text).intent.value
        _modality_name = _intent_to_modality_name(_classified_intent)
        _modality_preamble = _load_modality_for_intent(_modality_name, _modalities_dir)
        if _modality_preamble:
            context = _modality_preamble + "\n\n" + context
            logger.debug(
                "Modality preamble injected: modality=%s intent=%s",
                _modality_name,
                _classified_intent,
            )

    # Sprint D-R4 (#1934) — task-framing preamble. When the message
    # classifier marked this turn as TASK, prepend the task-mode system
    # prompt so the warm process arrives with the engineer-style framing
    # (read first, state assumptions, propose, implement surgically,
    # verify). Best-effort; if the file is missing the preamble is
    # silently skipped — the modality preamble above remains in place.
    if (
        app._config is not None
        and _mc.message_type == _MessageType.TASK
    ):
        _task_framing_path = (
            Path(app._config.claude_working_dir)
            / "config"
            / "system-prompts"
            / "task-framing.md"
        )
        try:
            _task_preamble = _task_framing_path.read_text(encoding="utf-8")
            context = _task_preamble + "\n\n" + context
            logger.debug(
                "Task-framing preamble injected (mc signal=%s)",
                _mc.matched_signal,
            )
        except FileNotFoundError:
            logger.debug(
                "Task-framing preamble file not found at %s; skipped",
                _task_framing_path,
            )
        except Exception as _task_pre_exc:
            logger.debug(
                "Task-framing preamble injection failed (non-fatal): %s",
                _task_pre_exc,
            )

    # /search command: inject FTS5 search results into context
    if "Search past conversations for:" in msg.text:
        search_query = msg.text.split("Search past conversations for:", 1)[1].split(".")[0].strip()
        if search_query:
            try:
                search_results = await app._memory.search_conversations(search_query, limit=20)
                if search_results:
                    search_ctx = "\n\n## Search Results\n"
                    for session in search_results[:10]:
                        search_ctx += (
                            f"\n### Session {session['session_id'][:8]} "
                            f"({session['match_count']} match{'es' if session['match_count'] != 1 else ''})\n"
                        )
                        for match in session["matches"][:5]:
                            search_ctx += f"- **{match['role']}**: {match['snippet']}\n"
                    context += search_ctx
            except Exception as e:
                logger.warning("Search injection failed: %s", e)

    # Budget pressure injection
    budget_pressure: str | None = None
    budget_alert_level: str | None = None  # P8.2 #1748 — kept for compound_pressure
    if app._budget:
        budget_status = await app._budget.check()
        budget_pressure = app._budget.get_pressure_signal(budget_status)
        budget_alert_level = budget_status.get("alert_level")
        if budget_pressure:
            context += f"\n\n{budget_pressure}"

    # Context pressure injection (> 0.7 threshold)
    ctx_pressure_value: float | None = None  # P8.2 #1748 — kept for compound_pressure
    if resume_id:
        try:
            ctx_pressure = await app._session_mgr.context_pressure(resume_id)
            ctx_pressure_value = ctx_pressure
            if ctx_pressure > 0.7:
                pct = int(ctx_pressure * 100)
                context += (
                    f"\n\nCONTEXT PRESSURE: {pct}% — "
                    "Prioritize completing current task. Avoid starting new large subtasks."
                )
                logger.debug("Context pressure injection: %.2f (%.0f%%)", ctx_pressure, ctx_pressure * 100)
        except Exception as _cpe:
            logger.debug("Context pressure check failed (non-fatal): %s", _cpe)

    # P8.2 #1748 — compound-pressure auto-compact trigger. When both budget and
    # context pressure are simultaneously elevated, fire ``compaction.recommended``
    # so downstream consumers (compaction_checkpoint, future PreCompact
    # externalization) can pre-stash the high-value transcript before the next
    # turn dilutes it. ``should_auto_compact`` is the single-source predicate
    # (bridge/compound_pressure.py); composite-score → recommendation mapping
    # mirrors ``ContextPressureMonitor.get_pressure`` thresholds at
    # context_pressure.py:115-123. Advances #1420 / D7.8.
    if budget_alert_level is not None and ctx_pressure_value is not None:
        try:
            from .compound_pressure import should_auto_compact

            # Map the session-manager float onto the recommendation enum.
            if ctx_pressure_value >= 0.90:
                _ctx_rec = "critical"
            elif ctx_pressure_value >= 0.75:
                _ctx_rec = "compact_now"
            elif ctx_pressure_value >= 0.60:
                _ctx_rec = "warn"
            else:
                _ctx_rec = "ok"

            if should_auto_compact(budget_alert_level, _ctx_rec):
                _bus = app._autonomy.event_bus if app._autonomy else None
                if _bus is not None:
                    _bus.publish(
                        "compaction.recommended",
                        payload={
                            "reason": "compound_pressure=high",
                            "budget_level": budget_alert_level,
                            "context_recommendation": _ctx_rec,
                            "context_pressure": round(ctx_pressure_value, 3),
                        },
                        source="compound_pressure",
                    )
                    logger.info(
                        "compaction.recommended fired "
                        "(budget=%s ctx=%s pressure=%.2f)",
                        budget_alert_level, _ctx_rec, ctx_pressure_value,
                    )
        except Exception as _cpe:
            logger.debug("compound_pressure check failed (non-fatal): %s", _cpe)

    # Inject few-shot examples (Patch D) — gated by config flag (#23)
    _few_shot_active = bool(app._config and getattr(app._config, "few_shot_enabled", True))
    if app._few_shot and _few_shot_active:
        try:
            task_type = classify_task_type(msg.text or "", [])
            examples = app._few_shot.get_relevant(msg.text or "", task_type=task_type, limit=2)
            if examples:
                # Pass metrics so format_injection can count injections (#22)
                few_shot_injection = app._few_shot.format_injection(
                    examples, metrics=app._metrics
                )
                if few_shot_injection:
                    context = few_shot_injection + "\n\n" + context
                    logger.debug(
                        "Injected %d few-shot example(s) (task_type=%s)",
                        len(examples), task_type,
                    )
        except Exception as _fse:
            logger.debug("Few-shot injection failed (non-fatal): %s", _fse)
    elif app._few_shot and not _few_shot_active:
        logger.debug("Few-shot injection skipped (few_shot_enabled=False)")

    # Inject active project context
    if app._project_registry:
        project_ctx = app._project_registry.get_active_project_context()
        if project_ctx:
            context = project_ctx + "\n\n" + context

    # Inject reflexion context from previous failed attempts
    if app._reflexion_ctx and app._reflexion_ctx.count > 0:
        reflexion_text = app._reflexion_ctx.get_context()
        if reflexion_text:
            context = reflexion_text + "\n\n" + context

    # Lifecycle: SPAWNING -> ACTIVE
    if app._lifecycle:
        app._lifecycle.transition(LifecycleState.ACTIVE)

    # Smart model routing — strip any @model: override, then classify
    clean_text, override_tier = strip_model_override(msg.text)
    tier = override_tier or classify(clean_text)
    model = {"haiku": "haiku", "sonnet": "sonnet", "opus": "opus"}.get(tier, "sonnet")

    # Check routing feedback for model escalation
    if app._routing_feedback and not override_tier:
        _task_type = classify_task_type(msg.text or "", []) if app._few_shot else "general"
        escalated = app._routing_feedback.check_escalation(model, _task_type)
        if escalated:
            logger.info("Model escalated: %s → %s for task_type=%s", model, escalated, _task_type)
            model = escalated

    # Session hook overrides (#19)
    if app._session_hooks:
        if app._session_hooks.is_active("careful"):
            model = CAREFUL_OPUS_MODEL
            context += "\n\nSESSION HOOK [careful]: Be extra thorough. Double-check all assumptions. Verify code correctness before presenting."
            logger.info("Session hook 'careful' active — forced model=%s", CAREFUL_OPUS_MODEL)
        if app._session_hooks.is_active("freeze"):
            context += "\n\nSESSION HOOK [freeze]: READ-ONLY MODE. DO NOT modify any files. Do not use Edit, Write, or Bash commands that change files. Only read, search, and analyze."

    # D7.10 (#1422) — pre-emptive output-length budget for Discord.
    # Operator messages flow through Discord today; the soft target
    # tells the model to stay under the 2000-char free-account cap
    # so split/file-fallback rarely fires. Set discord_output_target_chars
    # to 0 in bridge.toml to disable.
    _discord_target = (
        getattr(app._config, "discord_output_target_chars", 1800)
        if app._config is not None
        else 1800
    )
    if _discord_target > 0:
        context += (
            f"\n\nOUTPUT BUDGET (Discord): target ≤{_discord_target} characters "
            f"in your response. Use brevity; prefer tight prose to bullet "
            f"lists when prose is clearer. If the answer genuinely needs "
            f"more, the bridge attaches a file — the operator can read it."
        )

    logger.info("Model routing: tier=%s model=%s msg=%r", tier, model, msg.text[:60])

    # Issue #1540 — record the routing decision on the process-wide ring
    # buffer so ``/status`` can surface the last 5. Best-effort: if any
    # field lookup fails we still record the model decision rather than
    # skipping the entry entirely.
    try:
        from .routing_history import record_routing_decision
        from .departments import detect_department as _detect_department_for_history

        _intent_value: str | None
        _severity_value: str | None
        try:
            _intent_cls = _classify_message_intent(msg.text)
            _intent_value = _intent_cls.intent.value
            _severity_value = str(_intent_cls.complexity)
        except Exception:
            _intent_value = None
            _severity_value = None

        try:
            _department_value = _detect_department_for_history(msg.text)
        except Exception:
            _department_value = None

        record_routing_decision(
            message_id=str(getattr(msg, "id", None)) if getattr(msg, "id", None) is not None else None,
            router_used="model_router+command_router",
            intent=_intent_value,
            severity=_severity_value,
            model_selected=model,
            department_routed_to=_department_value,
        )
    except Exception as _rh_exc:
        logger.debug("routing_history.record failed (non-fatal): %s", _rh_exc)

    # Decide path: warm process (persistent) vs one-shot (subprocess per message).
    #
    # Sprint P1.3 (#1571) — warm-session isolation policy (Option C):
    # warm only for low-risk chat; one-shot for workorder / tool-bearing /
    # code-mutation / security / deploy paths. The actual safe/unsafe
    # decision lives in ``bridge.warm_policy.should_use_warm_path``;
    # availability (process exists + is_alive) stays here.
    #
    # is_workorder=False: dispatcher (above, line ~3534) short-circuits
    # workorders before they reach this gate; pass False explicitly.
    # has_tools=False: per-message tool flag does not exist today; the
    # warm process inherits MCP config at spawn time. Sprint P1.4 narrows
    # that surface; future per-message tool routing will set this true.
    # intent=None on classifier exception: operator-mandated fail-safe to
    # one-shot (warm_policy treats None as not-safe).
    #
    # Sprint P6.1 (#1591) — the warm-policy call is now delegated to the
    # ``BridgeApp._decide_use_warm`` narrow seam so warm-policy module
    # behavior can be swapped without touching the pipeline.
    try:
        _warm_intent_value: str | None = _classify_message_intent(msg.text).intent.value
    except Exception:
        _warm_intent_value = None
    use_warm = (
        app._warm_claude is not None
        and app._warm_claude.is_alive
        and app._decide_use_warm(
            model=model,
            intent=_warm_intent_value,
            has_tools=False,
            is_workorder=False,
        )
    )

    _invoke_span = app._tracer.start_span("invoke_claude", attributes={"model": model, "warm": use_warm}) if app._tracer else None

    # P6.4 (#1599) — warm-path latency telemetry. Two histograms:
    #   warm_path.enqueue_to_start_seconds — time from message dequeue
    #     (ctx.msg_start) to the moment we're about to invoke the warm
    #     subprocess. Captures the bridge's own per-message overhead.
    #   warm_path.total_seconds — full warm send_message wall-clock.
    # Both observe only when the warm path is actually taken so the
    # operator can baseline narrow MCP wins separately from one-shot.
    _warm_send_start: float | None = None

    result = None
    if use_warm:
        # Warm path: prepend context to the user message
        user_text = clean_text if override_tier else msg.text
        warm_message = f"<context>\n{context}\n</context>\n\n{user_text}"
        _warm_send_start = time.monotonic()
        if app._metrics is not None:
            try:
                app._metrics.observe(
                    "warm_path.enqueue_to_start_seconds",
                    _warm_send_start - ctx.msg_start,
                )
            except Exception as _wpm_exc:  # noqa: BLE001
                logger.debug(
                    "warm_path.enqueue_to_start observe failed (non-fatal): %s",
                    _wpm_exc,
                )
        warm_timeout = float(
            getattr(app._config, "warm_response_timeout_seconds", 60)
        )
        result = await app._warm_claude.send_message(
            warm_message,
            timeout_s=warm_timeout,
        )
        if app._metrics is not None and _warm_send_start is not None:
            try:
                app._metrics.observe(
                    "warm_path.total_seconds",
                    time.monotonic() - _warm_send_start,
                )
            except Exception as _wpm_exc:  # noqa: BLE001
                logger.debug(
                    "warm_path.total observe failed (non-fatal): %s",
                    _wpm_exc,
                )
        if result.is_error:
            logger.warning("Warm process failed (%s), falling back to one-shot", result.error_type)
            result = None  # fall through to one-shot

    if result is None:
        # One-shot path: opus, warm process unavailable, or warm process failed
        context_file = await asyncio.to_thread(app._memory.write_context_file, context)
        try:
            result = await invoke_with_retry(
                app._claude,
                message=clean_text if override_tier else msg.text,
                session_id=resume_id,
                system_prompt_file=str(context_file),
                model=model,
            )
        finally:
            app._memory.cleanup_context_file()

    if app._tracer and _invoke_span:
        app._tracer.end_span(_invoke_span)

    return MessageContext(
        msg=msg,
        correlation_id=ctx.correlation_id,
        msg_start=ctx.msg_start,
        claude_breaker=ctx.claude_breaker,
        session_id=session_id,
        resume_id=resume_id,
        result=result,
        budget_pressure=budget_pressure,
    )
