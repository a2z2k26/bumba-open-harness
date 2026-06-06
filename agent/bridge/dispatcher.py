"""WorkOrder dispatcher — routes WorkOrders to execution environments."""

from __future__ import annotations

import asyncio
import json
import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from bridge.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from bridge.executors import (
    DepartmentExecutor,
    E2BExecutor,
    Executor,
    SubagentExecutor,
    TmuxExecutor,
    WorktreeExecutor,
)
from bridge.work_order import (
    Environment,
    WorkOrder,
    WorkOrderOutput,
    WorkOrderStatus,
)
from bridge.wiring import WiringMissingError
from bridge.z3_metrics import (
    Z3Spans,
    record_dispatch_fallthrough,
    record_subagent_error,
    record_subagent_success,
    record_subagent_timeout,
)
from bridge.tracing import get_tracer

if TYPE_CHECKING:
    from bridge.claude_runner import ClaudeResult, ClaudeRunner
    from bridge.recursive_decomposer import RecursiveDecomposer
    from teams._registry import DepartmentRegistry

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DispatchResult:
    """Result of a dispatcher routing attempt.

    Fallthrough semantics: if ``handled`` is False the caller MUST execute
    the fallthrough path (direct ``claude_runner.invoke``).  The dispatcher
    is additive — it never silently swallows a request.

    Fields:
        valid:     False means the WorkOrder was rejected before dispatch
                   (missing environment, wrong status, unknown route).
        reason:    Human-readable explanation for logging / debugging.
        handled:   True when the dispatcher fully handled the WorkOrder and
                   produced a result.  False when the caller must fall through
                   to the direct invocation path.
        result:    The ClaudeResult produced by the executor, or None when
                   ``handled`` is False or an error occurred before execution.
        workorder: The post-transition WorkOrder instance (status advanced
                   beyond ASSIGNED). Populated by ``_run_executor`` so the
                   verification and completion sprints (03.02 / 03.03) can
                   chain further transitions. None when the executor was
                   never reached (validation failure, dojo gate, circuit
                   breaker open, unknown route).
    """
    valid: bool
    reason: str = ""
    handled: bool = False
    result: "ClaudeResult | None" = None
    workorder: WorkOrder | None = None


# Sprint S3.2 (Backend Operability, #2283) — operator-surface payload helper.
#
# The dispatcher already exposes ``get_executor_statuses()`` (D-R5 #1935) and
# the environment selector already encodes routability via
# ``is_environment_routable`` (S2.3 #2280). This helper composes the two so
# operator surfaces (REST + Discord commands) can render a single payload
# that answers both "what status is the lane?" and "is the lane routable?"
# without each callsite reimplementing the predicate.
def executor_status_payload(
    statuses: dict[str, str],
) -> dict[str, dict[str, object]]:
    """Annotate a status map with the routable flag for each lane.

    Args:
        statuses: ``{executor_name: status}`` map, typically the output
            of :meth:`Dispatcher.get_executor_statuses`.

    Returns:
        ``{executor_name: {"status": status, "routable": bool}}``. The
        ``routable`` flag is sourced from
        :func:`bridge.environment_selector.is_environment_routable`, which
        is the single predicate shared with the dispatcher's route-selection
        guard. Statuses absent from the routable set (``stub``,
        ``conditional_unwired``, ``unknown``) report ``routable=False``.
    """
    from bridge.environment_selector import is_environment_routable

    return {
        name: {"status": status, "routable": is_environment_routable(status)}
        for name, status in statuses.items()
    }


def _load_skill_floors(skills_yaml: Path) -> dict[str, float]:
    """Load per-skill trust floors from skills.yaml.

    Returns an empty dict if the file doesn't exist or can't be parsed.
    """
    if not skills_yaml.exists():
        return {}
    try:
        import yaml
        data = yaml.safe_load(skills_yaml.read_text()) or {}
        out: dict[str, float] = {}
        for s in data.get("skills", []):
            if isinstance(s, dict):
                out[s.get("name", "")] = float(s.get("trust_floor", 0.0))
        return out
    except Exception as e:
        log.warning("Could not load skill floors from %s: %s", skills_yaml, e)
        return {}


class Dispatcher:
    def __init__(
        self,
        *,
        tmux_manager: object | None = None,
        event_bus: object | None = None,
        claude_runner: "ClaudeRunner | None" = None,
        department_registry: "DepartmentRegistry | None" = None,
        app: object | None = None,
        trust_manager: object | None = None,
        config: object | None = None,
    ) -> None:
        self._tmux = tmux_manager
        self._event_bus = event_bus
        self._claude_runner = claude_runner
        self._department_registry = department_registry
        self._app = app
        self._trust_manager = trust_manager
        # Sprint 03.03 follow-up: thread BridgeConfig through so the
        # ``verification_enabled`` knob (read in ``_run_executor`` via
        # ``getattr(self, "_config", None)``) is no longer inert. Defaults
        # to None to preserve backward compatibility with every existing
        # construction site (tests, ``Dispatcher.from_config``, the
        # ``Dispatcher.__new__`` bypass in tests/test_dispatcher_timeout.py).
        self._config = config
        # Sprint D1.6 -- optional injected RecursiveDecomposer for WO fan-out.
        self._recursive_decomposer: "RecursiveDecomposer | None" = None

        _repo_root = Path(__file__).resolve().parent.parent.parent
        # S15: Load skill trust floors
        self._skill_floors = _load_skill_floors(_repo_root / "config" / "skills.yaml")

        # Load master MCP config + subagent allowlist for write jail (S03)
        _mcp_path = _repo_root / ".mcp.json"
        _master_mcp: dict = {}
        if _mcp_path.exists():
            try:
                _master_mcp = json.loads(_mcp_path.read_text())
            except Exception:
                log.warning("Dispatcher: failed to load master MCP config from %s", _mcp_path)

        _allowlist_path = _repo_root / "config" / "subagent-mcp-allowlist.toml"
        _allowed_servers: list[str] = []
        if _allowlist_path.exists():
            try:
                with open(_allowlist_path, "rb") as _f:
                    _allowed_servers = tomllib.load(_f).get("allowed", [])
            except Exception:
                log.warning("Dispatcher: failed to load subagent allowlist from %s", _allowlist_path)

        self._executors: dict[Environment, Executor] = {
            Environment.SUBAGENT: SubagentExecutor(
                claude_runner=claude_runner,
                master_mcp_config=_master_mcp,
                allowed_mcp_servers=_allowed_servers,
            ),
            Environment.DEPARTMENT: DepartmentExecutor(
                department_registry=department_registry,
                app=app,
                event_bus=event_bus,
            ),
            Environment.WORKTREE: WorktreeExecutor(
                claude_runner=claude_runner,
                repo_root=_repo_root,
            ),
            # E2B: flag/credential/runner gate (#416 / S4.2 #2345). When all
            # three are present the executor drives a real sandbox run via the
            # bumba-sandbox MCP (filtered to that server only); otherwise it
            # reports conditional_unwired and execute() raises.
            Environment.E2B: E2BExecutor(
                enabled=bool(getattr(config, "e2b_executor_enabled", False)),
                api_key=str(getattr(config, "e2b_api_key", "")),
                claude_runner=claude_runner,
                master_mcp_config=_master_mcp,
            ),
        }
        # Register TMUX only if manager is available (None → fallthrough to unknown route)
        if tmux_manager is not None:
            self._executors[Environment.TMUX] = TmuxExecutor(tmux_mgr=tmux_manager)

        # Per-environment circuit breakers (S16: #636).
        # failure_threshold=3, recovery_timeout=180s.  A tripped breaker causes
        # a graceful fallthrough rather than a 6th (or Nth) failing attempt.
        _breaker_cfg = CircuitBreakerConfig(
            failure_threshold=3,
            success_threshold=1,
            timeout_seconds=180.0,
        )
        self._breakers: dict[str, CircuitBreaker] = {
            env.value: CircuitBreaker(config=_breaker_cfg)
            for env in Environment
        }
        # D1.4 — QualityChain gate. Injected by BridgeApp._build_quality_chain()
        # after construction when quality_chain_enabled=true. None means disabled;
        # behaviour is identical to pre-D1.4 (auto-complete after VERIFYING).
        self._quality_chain: object | None = None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_for_dispatch(self, wo: WorkOrder) -> DispatchResult:
        _tracer = get_tracer("z3.dispatcher")
        with _tracer.context_span(
            Z3Spans.DISPATCHER_VALIDATE,
            attributes={"wo.id": wo.id[:8], "wo.skill": wo.skill},
        ):
            if wo.environment is None:
                return DispatchResult(
                    valid=False,
                    reason="WorkOrder has no execution environment selected. "
                           "The Chief Engineer must select an environment before dispatch.",
                )
            if wo.status != WorkOrderStatus.ASSIGNED:
                return DispatchResult(
                    valid=False,
                    reason=f"WorkOrder must be in ASSIGNED status for dispatch, "
                           f"currently {wo.status.value}.",
                )
            # Sprint S2.3 (Backend Operability, #2280) — route-selection guard.
            # Reject explicit assignments to non-routable executors (e.g. E2B
            # while its status is ``stub``) BEFORE we call ``executor.execute``
            # so the operator-facing reason mentions the routable-status
            # taxonomy rather than the raw ``NotImplementedError`` from the
            # executor body. Operator-facing status (``get_executor_statuses``)
            # still surfaces the executor as registered + stubbed.
            from bridge.environment_selector import is_environment_routable
            route = wo.environment.value
            status = self.get_executor_statuses().get(route, "unknown")
            if not is_environment_routable(status):
                return DispatchResult(
                    valid=False,
                    reason=(
                        f"{route} executor is registered but not routable: "
                        f"status={status}"
                    ),
                )
            return DispatchResult(valid=True)

    def get_route(self, env: Environment) -> str:
        return env.value

    # ------------------------------------------------------------------
    # Sprint D-R3 (#1933) -- observability surface
    # ------------------------------------------------------------------

    def get_circuit_breaker_states(self) -> dict[str, str]:
        """Return per-executor circuit-breaker state.

        Maps each executor route (``subagent``, ``tmux``, ``worktree``,
        ``e2b``, ``department``) to the current ``State.value``
        (``CLOSED``, ``OPEN``, or ``HALF_OPEN``). Surfaced through
        ``/status --full`` so the operator can see at a glance which
        executor lanes are currently tripped.
        """
        return {
            route: breaker.state.value
            for route, breaker in self._breakers.items()
        }

    def get_executor_statuses(self) -> dict[str, str]:
        """Return per-executor activation status.

        Sprint D-R5 (#1935). Status reflects whether the executor is
        wired into the dispatcher and routable:

        - ``active``  — wired, production primary
        - ``active_low_traffic`` — wired but rarely selected
        - ``conditional_unwired`` — registered but blocked by a missing
          dependency, disabled flag, or absent credential
        - ``conditional_active`` — registered and optional dependency wired
        - ``stub`` — class exists but ``execute()`` raises
                     ``NotImplementedError``

        The canonical roadmap with activation criteria for each
        executor lives at ``docs/architecture/executor-roadmap.md``.
        Surfaced through ``/status --full``.
        """
        e2b_executor = self._executors.get(Environment.E2B)
        e2b_status = (
            e2b_executor.get_status()
            if isinstance(e2b_executor, E2BExecutor)
            else "unknown"
        )
        # Map of route → status. Encodes the operator-facing roadmap; the
        # detailed activation criteria live in the doc cited above.
        _statuses = {
            "subagent": "active",
            "department": "active",
            "worktree": "active_low_traffic",
            "e2b": e2b_status,
        }
        # TMUX is conditional — registered only when tmux_manager is
        # wired. If Environment.TMUX is in self._executors, the
        # condition was met at construction.
        if Environment.TMUX in self._executors:
            _statuses["tmux"] = "conditional_active"
        else:
            _statuses["tmux"] = "conditional_unwired"
        return _statuses

    def get_executor_status_payload(self) -> dict[str, dict[str, object]]:
        """Return per-executor activation status enriched with routability.

        Sprint S3.2 (Backend Operability, #2283). Operator surfaces need
        the activation status (from :meth:`get_executor_statuses`) AND
        an at-a-glance answer to "is this lane currently routable?" so
        ``stub`` and ``conditional_unwired`` executors don't masquerade
        as dispatch targets.

        See :func:`executor_status_payload` for the helper used to
        render the shape; this method is the canonical Dispatcher
        accessor for the enriched payload.
        """
        return executor_status_payload(self.get_executor_statuses())

    # ------------------------------------------------------------------
    # Sprint D1.6 -- Decomposition gate
    # ------------------------------------------------------------------

    DEFAULT_DECOMPOSITION_THRESHOLD: int = 7

    def set_recursive_decomposer(self, decomposer: "RecursiveDecomposer") -> None:
        """Inject a RecursiveDecomposer instance for WorkOrder fan-out."""
        self._recursive_decomposer = decomposer

    async def _maybe_decompose(self, wo: WorkOrder) -> list[WorkOrder]:
        """Return [wo] when decomposition is off or below threshold."""
        from bridge.recursive_decomposer import heuristic_complexity_score

        config = getattr(self, "_config", None)
        if not (config and getattr(config, "workorder_decomposition_enabled", False)):
            return [wo]

        threshold = (
            getattr(config, "workorder_decomposition_complexity_threshold", None)
            or self.DEFAULT_DECOMPOSITION_THRESHOLD
        )
        score = getattr(wo, "complexity_score", None) or heuristic_complexity_score(wo)
        if score < threshold:
            return [wo]

        decomposer = getattr(self, "_recursive_decomposer", None)
        if decomposer is None:
            raise WiringMissingError(
                "Dispatcher decomposition is enabled but no RecursiveDecomposer "
                "was registered via set_recursive_decomposer()."
            )

        log.info("dispatcher.decompose wo=%s score=%d threshold=%d", wo.id[:8], score, threshold)
        decomposed = decomposer.decompose_recursive(wo, max_depth=1)
        decomp = decomposed.decomposition
        if decomp is None or decomp.atomic or not decomp.children:
            log.info("dispatcher.decompose wo=%s collapsed to atomic", wo.id[:8])
            event_bus = getattr(self, "_event_bus", None)
            if event_bus is not None:
                event_bus.publish("workorder.decompose.collapsed", {"workorder_id": wo.id, "reason": "no_children"})
            return [wo]

        children = list(decomp.children)
        log.info("dispatcher.decompose wo=%s -> %d children", wo.id[:8], len(children))
        event_bus = getattr(self, "_event_bus", None)
        if event_bus is not None:
            event_bus.publish("workorder.decomposed", {"workorder_id": wo.id, "child_count": len(children), "child_ids": [c.id[:8] for c in children]})
        return children

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, wo: WorkOrder) -> DispatchResult:
        """Route a WorkOrder to its execution environment.

        Returns ``handled=False`` when the caller must fall through to direct
        ``claude_runner.invoke``.  This invariant is preserved through all Z3 sprints.
        """
        # Sprint D-R2 (#1932) — defensive boundary. Conversational text used
        # to flow here as raw strings before the intent gate landed; the
        # AttributeError that resulted was deep inside validate_for_dispatch
        # and obscured the real bug. Surface it at the entry instead.
        if not isinstance(wo, WorkOrder):
            raise TypeError(
                f"Dispatcher.dispatch() requires a WorkOrder instance, "
                f"got {type(wo).__name__!r}. Conversational messages must go "
                f"directly to the warm process. See epic: dispatcher-re-envision."
            )

        validation = self.validate_for_dispatch(wo)
        if not validation.valid:
            return validation

        # S15: Dojo floor check — refuse dispatch if agent proficiency below floor
        if self._trust_manager is not None and wo.assignment.agent_id:
            floor = self._skill_floors.get(wo.skill, 0.0)
            if floor > 0.0:
                prof = self._trust_manager.get_skill_proficiency(  # type: ignore[attr-defined]
                    wo.assignment.agent_id, wo.skill
                )
                if prof < floor:
                    log.warning(
                        "Dojo gate: agent %s proficiency %.2f < floor %.2f for skill %s",
                        wo.assignment.agent_id, prof, floor, wo.skill,
                    )
                    if self._event_bus is not None:
                        self._event_bus.publish("dojo.gated", {
                            "workorder_id": wo.id,
                            "agent_id": wo.assignment.agent_id,
                            "skill": wo.skill,
                            "proficiency": prof,
                            "floor": floor,
                        })
                    return DispatchResult(
                        valid=True,
                        handled=False,  # fall through to direct invoke; event bus + metrics still fire
                        reason=f"dojo floor: agent proficiency {prof:.2f} < floor {floor:.2f}",
                    )

        route = self.get_route(wo.environment)

        # S16: Circuit breaker gate — don't attempt a 6th (Nth) failing executor call.
        breaker = self._breakers.get(route)
        if breaker is not None and not breaker.is_available:
            log.warning("dispatcher.breaker_open env=%s wo=%s", route, wo.id[:8])
            if self._event_bus is not None:
                self._event_bus.publish("dispatcher.breaker_open", {
                    "workorder_id": wo.id,
                    "environment": route,
                    "skill": wo.skill,
                })
            record_dispatch_fallthrough(f"{route}_circuit_open")
            return DispatchResult(
                valid=True,
                handled=False,
                reason=f"{route} circuit open",
            )

        log.info("Dispatching WorkOrder %s to %s", wo.id[:8], route)
        self._publish_dispatch_event(wo, route)

        executor = self._executors.get(wo.environment)
        if executor is not None:
            _tracer = get_tracer("z3.dispatcher")
            with _tracer.context_span(
                Z3Spans.DISPATCHER_ROUTE,
                attributes={"env": route, "wo.id": wo.id[:8]},
            ):
                return await self._run_executor(executor, wo, route, breaker)

        record_dispatch_fallthrough("unknown_route")
        return DispatchResult(valid=False, reason=f"Unknown route: {route}")

    def _publish_dispatch_event(self, wo: WorkOrder, route: str) -> None:
        if self._event_bus is not None:
            self._event_bus.publish(
                "workorder.dispatched",
                {"workorder_id": wo.id, "environment": route, "skill": wo.skill, "intent": wo.intent},
            )

    async def _run_executor(
        self,
        executor: "Executor",
        wo: WorkOrder,
        route: str,
        breaker: CircuitBreaker | None = None,
    ) -> DispatchResult:
        # Sprint D-R3 (#1933) — config-level ceiling. WorkOrder may request
        # a tighter timeout via constraints, but config caps the upper
        # bound. The 600s effective default (from WorkOrderConstraints
        # default) is what surfaced the 10-min latency in D-R1 (#1931).
        _wo_timeout = wo.constraints.timeout_ms / 1000.0
        _cfg = getattr(self, "_config", None)
        _cfg_ceiling = getattr(_cfg, "executor_timeout_seconds", None) if _cfg else None
        if isinstance(_cfg_ceiling, (int, float)) and _cfg_ceiling > 0:
            timeout_s = min(_wo_timeout, float(_cfg_ceiling))
        else:
            timeout_s = _wo_timeout
        try:
            # Sprint 03.01 — first of three state-machine transitions.
            # Advance ASSIGNED → EXECUTING and publish the matching event
            # BEFORE invoking the executor so the executor sees the
            # post-transition WorkOrder and downstream observers see the
            # state change in real time.  Inside the try so an exception
            # raised by transition() (e.g. invalid source state) is caught
            # by the same except-Exception path the executor uses.
            wo = wo.transition(WorkOrderStatus.EXECUTING)
            # ``getattr`` keeps us compatible with the ``Dispatcher.__new__``
            # bypass used by tests/test_dispatcher_timeout.py — that path
            # never runs ``__init__`` so ``_event_bus`` is absent.
            event_bus = getattr(self, "_event_bus", None)
            if event_bus is not None:
                event_bus.publish(
                    "workorder.executing",
                    {
                        "workorder_id": wo.id,
                        "environment": route,
                        "skill": wo.skill,
                        "intent": wo.intent,
                    },
                )
            result = await asyncio.wait_for(
                executor.execute(wo),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            log.warning(
                "dispatcher.executor_timeout",
                extra={
                    "wo_id": str(wo.id),
                    "intent": wo.intent,
                    "env": route,
                    "timeout_used_s": timeout_s,
                    "wo_timeout_s": _wo_timeout,
                },
            )
            record_dispatch_fallthrough("timeout")
            record_subagent_timeout(intent=wo.intent or "unknown", env=route)
            wo = self._mark_failed(
                wo,
                route,
                f"executor timeout after {timeout_s}s",
            )
            return DispatchResult(
                valid=True,
                handled=False,
                reason="executor timeout",
                workorder=wo,
            )
        except Exception as exc:
            log.exception("Executor %s failed for WO %s", route, wo.id[:8])
            if breaker is not None:
                breaker.record_failure(exc)
            record_dispatch_fallthrough(f"{route}_exception")
            record_subagent_error(
                intent=wo.intent or "unknown",
                env=route,
                error_type=type(exc).__name__,
            )
            wo = self._mark_failed(wo, route, str(exc))
            return DispatchResult(
                valid=True, handled=False, reason=str(exc), workorder=wo,
            )
        if result.is_error:
            if breaker is not None:
                breaker.record_failure()
            record_dispatch_fallthrough(f"{route}_error")
            record_subagent_error(
                intent=wo.intent or "unknown",
                env=route,
                error_type=result.error_type or "unknown",
            )
            wo = self._mark_failed(wo, route, result.error_type)
            return DispatchResult(
                valid=True, handled=False,
                reason=f"{route} error: {result.error_type}",
                workorder=wo,
            )
        # Success — allow breaker to close
        if breaker is not None:
            breaker.record_success()
        # Sprint D-R3 (#1933) — success counter
        record_subagent_success(intent=wo.intent or "unknown", env=route)
        # Sprint 03.02 — second of three state-machine transitions.
        # EXECUTING → VERIFYING after a clean executor return.  Publish
        # ``workorder.verifying`` so downstream observers (synthesizer,
        # quality-gate) can pick up the post-execution WorkOrder.
        wo = wo.transition(WorkOrderStatus.VERIFYING)
        event_bus = getattr(self, "_event_bus", None)
        if event_bus is not None:
            event_bus.publish(
                "workorder.verifying",
                {
                    "workorder_id": wo.id,
                    "environment": route,
                    "skill": wo.skill,
                    "intent": wo.intent,
                },
            )
        # Sprint 03.03 / D1.4 — third of three state-machine transitions.
        # VERIFYING → COMPLETE (or FAILED if a quality gate rejects the WO).
        #
        # D1.4 replaces the placeholder with a real QualityChain gate:
        #   - If quality_chain_enabled (chain is not None): run the chain.
        #     Hard failure → FAILED.  requires_human (soft) → log + COMPLETE
        #     (HITL scope-trimmed to no-op pass; follow-up sprint for full
        #     AWAITING_HUMAN state).
        #   - If chain is None (flag off, dark-deploy default): legacy
        #     auto-complete path, identical to pre-D1.4 behaviour.
        #
        # Defensive coding (works pre-/post-03.02): the ``if wo.status ==
        # VERIFYING`` guard is a no-op on pre-03.02 deployments where the
        # success path leaves the WO in EXECUTING.
        if wo.status == WorkOrderStatus.VERIFYING:
            quality_chain = getattr(self, "_quality_chain", None)
            if quality_chain is not None:
                # D1.4: real quality gate
                project = getattr(wo, "project", "") or ""
                files = list(getattr(wo, "changed_files", None) or [])
                chain_result = quality_chain.run(project, files)
                if not chain_result.passed:
                    failed_gate = chain_result.failed_at.name if chain_result.failed_at else "unknown"
                    log.warning(
                        "quality_chain.failed wo=%s gate=%s reason=%s",
                        wo.id[:8], failed_gate, chain_result.reason,
                    )
                    if event_bus is not None:
                        event_bus.publish("workorder.quality_chain.failed", {
                            "workorder_id": wo.id,
                            "environment": route,
                            "skill": wo.skill,
                            "failed_at": failed_gate,
                            "reason": chain_result.reason,
                        })
                    wo = self._mark_failed(
                        wo, route, f"quality_chain.{failed_gate}: {chain_result.reason}"
                    )
                    dept = getattr(wo, "department_target", None)
                    reason_str = f"department {dept} quality failed" if dept else f"{route} quality failed"
                    return DispatchResult(
                        valid=True, handled=True, result=result,
                        reason=reason_str, workorder=wo,
                    )
                if chain_result.requires_human:
                    # HITL scope-trim (D1.4): log and proceed to COMPLETE;
                    # full AWAITING_HUMAN state is a follow-up sprint.
                    log.info(
                        "quality_chain.requires_human wo=%s (proceeding — HITL not yet wired)",
                        wo.id[:8],
                    )
                    if event_bus is not None:
                        event_bus.publish("workorder.quality_chain.human_required", {
                            "workorder_id": wo.id,
                            "skill": wo.skill,
                            "escalation_reasons": chain_result.escalation_reasons,
                        })
                # Chain passed (or soft-warnings only) → COMPLETE
                wo = wo.transition(WorkOrderStatus.COMPLETE)
                output_text = str(getattr(result, "response_text", "") or "")
                wo = wo.with_output(
                    WorkOrderOutput(
                        result=output_text,
                        verification_status="quality_chain",
                    )
                )
                self._publish_complete_events(
                    wo,
                    route,
                    verification_status="quality_chain",
                    output_text=output_text,
                )
                self._persist_terminal(wo)
            else:
                # Auto-complete — quality chain disabled (dark deploy default).
                # Preserve pre-D1.4 behaviour exactly.
                config = getattr(self, "_config", None)
                verification_enabled = bool(
                    config and getattr(config, "verification_enabled", False)
                )
                if not verification_enabled:
                    wo = wo.transition(WorkOrderStatus.COMPLETE)
                    output_text = str(getattr(result, "response_text", "") or "")
                    wo = wo.with_output(
                        WorkOrderOutput(
                            result=output_text,
                            verification_status="auto",
                        )
                    )
                    self._publish_complete_events(
                        wo,
                        route,
                        verification_status="auto",
                        output_text=output_text,
                    )
                    self._persist_terminal(wo)
                else:
                    log.warning(
                        "verification gate unwired — WO %s will stall in VERIFYING",
                        wo.id[:8],
                    )
                    if event_bus is not None:
                        event_bus.publish(
                            "workorder.verifying.stalled",
                            {
                                "workorder_id": wo.id,
                                "environment": route,
                                "skill": wo.skill,
                            },
                        )
        dept = getattr(wo, "department_target", None)
        reason = f"department {dept} completed" if dept else f"{route} completed"
        return DispatchResult(
            valid=True, handled=True, result=result, reason=reason, workorder=wo,
        )

    def _publish_complete_events(
        self,
        wo: WorkOrder,
        route: str,
        *,
        verification_status: str,
        output_text: str,
    ) -> None:
        """Publish canonical completion plus the legacy compatibility event."""
        event_bus = getattr(self, "_event_bus", None)
        if event_bus is None:
            return

        event_bus.publish(
            "workorder.completed",
            {
                "workorder_id": wo.id,
                "environment": route,
                "skill": wo.skill,
                "project": wo.project,
                "output_text": output_text,
                "verification_status": verification_status,
            },
        )
        event_bus.publish(
            "workorder.complete",
            {
                "workorder_id": wo.id,
                "environment": route,
                "skill": wo.skill,
                "verification_status": verification_status,
            },
        )

    def _mark_failed(self, wo: WorkOrder, route: str, error_reason: str) -> WorkOrder:
        """Sprint 03.02 — drive the failure half of EXECUTING → FAILED.

        Transitions the WorkOrder to FAILED, captures ``error_reason`` in
        ``wo.output.result`` with ``verification_status="error"``, and
        publishes ``workorder.failed`` on the event bus.  Returns the
        post-transition WorkOrder so the caller can thread it through the
        DispatchResult.

        Failure-only side effects live here (not in the success path) so
        the success branch stays linear and the four failure call sites
        — TimeoutError, generic Exception, ``result.is_error=True``, and
        any future failure paths — share one implementation.
        """
        wo = wo.transition(WorkOrderStatus.FAILED)
        wo = wo.with_output(
            WorkOrderOutput(result=error_reason, verification_status="error")
        )
        event_bus = getattr(self, "_event_bus", None)
        if event_bus is not None:
            event_bus.publish(
                "workorder.failed",
                {
                    "workorder_id": wo.id,
                    "environment": route,
                    "reason": error_reason,
                    "skill": wo.skill,
                },
            )
        # Sprint 03.03 — terminal-state persistence.  FAILED is one of
        # the two terminal states the dispatcher produces; persist it
        # alongside COMPLETE so a single store query can find every WO
        # the dispatcher has finished with.
        self._persist_terminal(wo)
        return wo

    def _persist_terminal(self, wo: WorkOrder) -> None:
        """Sprint 03.03 — defensively persist a terminal-state WorkOrder.

        Resolves the WorkOrderStore via two layered ``getattr`` reads so
        this works pre-/post-Sprint 03.06:

          1. ``self._workorder_store`` — set by a future sprint that
             wires the store directly into the Dispatcher.
          2. ``self._app._workorder_store`` — set by Sprint 03.06 on
             BridgeApp during ``_initialize``.

        Returns silently when no store is reachable.  Any exception
        from ``store.save()`` is logged at warning level and swallowed
        so a persistence failure never derails the dispatch loop.
        """
        store = getattr(self, "_workorder_store", None)
        if store is None:
            app = getattr(self, "_app", None)
            store = getattr(app, "_workorder_store", None) if app is not None else None
        if store is None:
            return
        try:
            store.save(wo)
        except Exception as exc:  # pragma: no cover — defensive
            log.warning("WorkOrderStore.save failed for WO %s: %s", wo.id[:8], exc)

    @classmethod
    def from_config(
        cls,
        config_path: str | Path,
        *,
        tmux_manager: object | None = None,
        event_bus: object | None = None,
        app: object | None = None,
    ) -> "Dispatcher":
        """Factory method for bridge-independent instantiation.

        Loads routing rules from YAML config. The config is currently
        reference material (not machine-parsed for routing decisions),
        but this entry point ensures the Dispatcher can be created
        without bridge-specific wiring.
        """
        return cls(tmux_manager=tmux_manager, event_bus=event_bus, app=app)
