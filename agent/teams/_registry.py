"""Department registry — discovery, lazy loading, routing."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from bridge.conversation_log import ConversationLogger
from teams._config import load_department_config
from teams._readiness import is_readiness_prompt, render_readiness
from teams._semaphore import DepartmentSemaphore
from teams._team import DepartmentTeam
from teams._types import BridgeDeps, DepartmentConfig, TeamResult

log = logging.getLogger(__name__)


# Sprint P3.1: transition aliases so legacy slugs continue to route to the
# canonical department. Keep this small — every entry is a temporary kindness
# for stale callers, not a permanent rename pattern. When the legacy slug has
# been retired from all call sites, drop the entry.
DEPARTMENT_ALIASES: dict[str, str] = {
    "job-search": "job_search",
}


def _build_conversation_logger(
    deps: BridgeDeps, department: str
) -> ConversationLogger | None:
    """Construct a ConversationLogger at the canonical Z4 sessions path.

    Returns ``None`` when ``deps.sessions_dir`` is unset (the back-compat
    no-logging branch) or when path construction fails for any reason —
    callers must treat ``None`` as a clean "logging disabled" signal.

    Path layout matches the Z4 reader at
    ``bridge/observability/api_routes.py:_handle_conversation``:

        sessions_dir / <session_id> / <department> / conversation.jsonl
    """
    if deps.sessions_dir is None:
        return None
    try:
        log_path = (
            deps.sessions_dir / deps.session_id / department / "conversation.jsonl"
        )
        return ConversationLogger(log_path)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "department.conversation_logger_init_failed dept=%s sid=%s err=%s",
            department, deps.session_id, exc,
        )
        return None


# ---------------------------------------------------------------------------
# MCP filter helpers for DEPARTMENT write jail (S04)
# ---------------------------------------------------------------------------


def _get_master_mcp_path() -> Path:
    """Return the canonical path to the master .mcp.json file.

    Resolves via :func:`bridge.paths.agent_root` so the post-D6-bis
    layout (``/opt/bumba-harness/agent-flat/agent/.mcp.json``) Just
    Works without the legacy symlink. See #1492.
    """
    from bridge.paths import agent_root
    return agent_root() / ".mcp.json"


def _prepare_filtered_mcp(deps: "BridgeDeps") -> str | None:
    """Build a filtered MCP config for this department invocation.

    Returns the path to a temp file (mode 0600) containing only the
    servers in ``deps.mcp_allowed_servers``. Mode interaction:

    - ``mcp_mode="permissive"`` (default) + empty list → returns ``None``
      (inherit bridge default; preserves pre-P2.4 behaviour).
    - ``mcp_mode="deny_by_default"`` + empty list → emits an empty
      ``{}`` MCP config so the department's subprocess sees no servers
      at all. This is the explicit "lock everything out" path the audit
      called for.
    - Non-empty list (under either mode) → filters the master config
      down to those servers.

    The caller is responsible for cleaning up via ``_cleanup_filtered_mcp``.
    """
    deny_by_default = getattr(deps, "mcp_mode", "permissive") == "deny_by_default"
    if not deps.mcp_allowed_servers and not deny_by_default:
        return None  # empty tuple under permissive → inherit bridge default

    master_path = _get_master_mcp_path()
    if not master_path.exists():
        log.debug("_prepare_filtered_mcp: master MCP config not found at %s", master_path)
        return None

    try:
        master = json.loads(master_path.read_text())
    except Exception as exc:
        log.warning("_prepare_filtered_mcp: failed to parse master MCP config: %s", exc)
        return None

    from bridge.tool_isolation import filter_mcp_config
    filtered = filter_mcp_config(master, list(deps.mcp_allowed_servers))

    fd, path = tempfile.mkstemp(prefix="dept-mcp-", suffix=".json")
    try:
        os.write(fd, json.dumps(filtered, indent=2).encode())
    finally:
        os.close(fd)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    return path


def _cleanup_filtered_mcp(path: str | None) -> None:
    """Delete a filtered MCP config file. No-op if path is None or missing."""
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


class DepartmentRegistry:
    """Discovers department configs, lazy-loads teams, routes tasks."""

    def __init__(
        self,
        configs: dict[str, DepartmentConfig],
        *,
        semaphore: Optional[DepartmentSemaphore] = None,
        tool_tracker: Optional[Any] = None,
    ) -> None:
        self._configs = configs
        self._teams: dict[str, DepartmentTeam] = {}
        # Sprint #1972 — per-department semaphore sized to the YAML
        # `constraints.concurrency_limit`. The fallback path (caller
        # explicitly passes a `semaphore=`) preserves the test-injection
        # contract: when a test passes a custom semaphore, that single
        # instance is used for every department (legacy global-cap shape).
        # Production path lazy-creates one semaphore per department on
        # first acquire, sized to that team's declared cap.
        #
        # Before #1972: a single global semaphore with DEFAULT_LIMIT=2
        # was used regardless of YAML declarations, meaning 5 of 6
        # departments were running at the wrong cap (the conservative
        # default rather than their declared 1/3/4/4/4/2 values).
        self._semaphore_override = semaphore  # None in production
        self._per_dept_semaphores: dict[str, DepartmentSemaphore] = {}
        self._tool_tracker = tool_tracker
        # RR.6 (#2593) — optional RosterRegistryStore, set at boot via
        # set_roster_registry(). Passed to each DepartmentTeam this registry
        # builds so the chief's roster reflects operator registrations. None
        # (the default) preserves back-compat for every test/ad-hoc construction.
        self._roster_registry: Optional[Any] = None

    def set_roster_registry(self, store: Any) -> None:
        """Wire the RosterRegistryStore (RR.6, #2593).

        Called once at bridge boot. Forwarded to every DepartmentTeam built
        after this point so the chief roster carries the operator's overlay.
        Teams already built before this call are not retroactively updated —
        boot wires the registry before any team is lazily built, so in the
        live path this fires first.
        """
        self._roster_registry = store

    def _get_semaphore(self, department: str) -> DepartmentSemaphore:
        """Return the semaphore for ``department``, lazy-creating on first use.

        Sprint #1972 — sizes the semaphore to the department's YAML
        ``constraints.concurrency_limit``. When the caller passed an
        explicit ``semaphore=`` to ``__init__`` (test-injection path),
        that override wins and every department shares the single
        instance (preserves legacy global-cap shape for the tests that
        depend on it).
        """
        if self._semaphore_override is not None:
            return self._semaphore_override
        resolved = self._resolve(department)
        if resolved not in self._per_dept_semaphores:
            try:
                cfg = self._configs[resolved]
                limit = cfg.constraints.concurrency_limit
            except (KeyError, AttributeError):
                # Unknown department or constraints missing — fall back
                # to DEFAULT_LIMIT rather than raising. The route() path
                # catches unknown-department separately; this defensive
                # branch covers test fixtures that construct partial
                # configs.
                from teams._semaphore import DEFAULT_LIMIT
                limit = DEFAULT_LIMIT
            self._per_dept_semaphores[resolved] = DepartmentSemaphore(limit=limit)
        return self._per_dept_semaphores[resolved]

    @classmethod
    def from_directory(
        cls,
        teams_dir: str | Path,
        *,
        tool_tracker: Optional[Any] = None,
    ) -> DepartmentRegistry:
        """Scan a directory for department YAML files and register each."""
        teams_dir = Path(teams_dir)
        if not teams_dir.exists():
            log.warning("Teams directory not found: %s", teams_dir)
            return cls(configs={}, tool_tracker=tool_tracker)

        configs: dict[str, DepartmentConfig] = {}
        for yaml_file in sorted(teams_dir.glob("*.yaml")):
            # D7.13 #1425 — files prefixed with `_` are non-runtime
            # (e.g. `_template.yaml`, the golden-path scaffold template).
            # Convention mirrors Python's private-module naming used
            # throughout `teams/_*.py`. Skipping at discovery keeps the
            # template loadable by `validate_team_yaml.py` for shape
            # smoke-checks without registering it as a real department.
            if yaml_file.name.startswith("_"):
                continue
            try:
                cfg = load_department_config(yaml_file)
                configs[cfg.name] = cfg
                log.info("department.registered name=%s zone=%d", cfg.name, cfg.zone)
            except Exception as e:  # noqa: BLE001
                log.error(
                    "department.load_failed file=%s error=%s",
                    yaml_file.name, e,
                )
        return cls(configs=configs, tool_tracker=tool_tracker)

    def department_names(self) -> list[str]:
        return sorted(self._configs.keys())

    @staticmethod
    def _resolve(name: str) -> str:
        """Resolve a department name through ``DEPARTMENT_ALIASES``.

        Returns the canonical slug. Unknown names pass through unchanged so
        the caller still sees the original KeyError / "Unknown department"
        path for genuinely unregistered slugs.
        """
        return DEPARTMENT_ALIASES.get(name, name)

    def get_config(self, name: str) -> DepartmentConfig:
        name = self._resolve(name)
        if name not in self._configs:
            raise KeyError(f"Unknown department: {name}")
        return self._configs[name]

    def get_cost_limit(self, department: str) -> float:
        """Return cost_limit_usd for the department from its YAML constraints."""
        department = self._resolve(department)
        config = self._configs.get(department)
        if config is None:
            return 2.0
        return config.constraints.cost_limit_usd

    def get_team(self, name: str) -> DepartmentTeam:
        """Return the DepartmentTeam for this department, building on first access."""
        name = self._resolve(name)
        if name not in self._configs:
            raise KeyError(f"Unknown department: {name}")
        if name not in self._teams:
            config = self._configs[name]
            self._teams[name] = DepartmentTeam(
                config=config,
                lazy_build=True,
                tool_tracker=self._tool_tracker,
                roster_registry=self._roster_registry,
            )
        return self._teams[name]

    def prewarm(self) -> None:
        """Eagerly build all department teams to pay agent-construction cost at startup.

        Safe to call multiple times — teams that are already built are skipped.
        Errors in individual departments are logged but never propagate so that a
        broken config in one department cannot prevent the others from warming.
        """
        for dept in sorted(self._configs):
            if dept in self._teams:
                continue  # already built
            try:
                self.get_team(dept)
                log.info("department.prewarmed name=%s", dept)
            except Exception as exc:  # noqa: BLE001
                log.warning("department.prewarm_failed name=%s error=%s", dept, exc)

    async def route(
        self,
        department: str,
        task: str,
        deps: BridgeDeps,
        *,
        directive_id: str | None = None,
        resume_from: str | None = None,
    ) -> TeamResult:
        """Route a task to a department, gated by the semaphore.

        Never raises. Unknown departments return TeamResult with success=False.

        Sprint 20 (Phase 5B): when ``directive_id`` is provided, the chief
        receives the task with a ``[directive_id: <id>]`` prefix and
        ``DepartmentTeam.run`` records lifecycle transitions to the
        directive_store (IN_PROGRESS at start, DONE on success, BLOCKED on
        timeout / exception). When omitted, behaviour is unchanged.

        WS2.6 (#2570): ``resume_from`` is threaded through to
        ``DepartmentTeam.run`` unchanged. When set it names a prior run
        directory under ``deps.artifact_root`` whose checkpoint reseeds the
        run; when ``None`` (the default) behaviour is unchanged.
        """
        department = self._resolve(department)
        if department not in self._configs:
            return TeamResult(
                department=department,
                manager_output="",
                success=False,
                error=f"Unknown department: {department}",
            )

        if directive_id is None and is_readiness_prompt(task):
            return render_readiness(self._configs[department])

        team = self.get_team(department)

        # Publish task started event (best-effort — never blocks routing)
        try:
            from bridge.event_bus import EventBus, DEPARTMENT_TASK_STARTED
            bus = EventBus.get_instance()
            bus.publish(DEPARTMENT_TASK_STARTED, {
                "department": department,
                "task": task[:200],
                "session_id": getattr(deps, "session_id", None),
                "directive_id": directive_id,
            })
        except Exception:
            pass

        # Sprint 20: prepend directive correlation marker to the task. The
        # chief's prompt doctrine (roster block from Sprint 19) tells it to
        # call acknowledge_directive(directive_id) on its first action.
        chief_task = (
            f"[directive_id: {directive_id}] {task}" if directive_id else task
        )

        # Sprint 04.08: attach a per-call ConversationLogger keyed on
        # session_id+department. The per-department semaphore (#1972)
        # caps concurrent runs at the department's YAML-declared
        # `constraints.concurrency_limit`. Mutating
        # ``team._conversation_logger`` is safe under that lock for runs
        # of the same department; DepartmentTeam instances are cached
        # across calls but each acquire path through this method swaps
        # the logger before run() and clears it after. ``None`` if
        # deps.sessions_dir is unset, in which case DepartmentTeam.run
        # becomes a logging no-op.
        async with self._get_semaphore(department).acquire(department):
            team._conversation_logger = _build_conversation_logger(
                deps, department
            )
            try:
                result = await team.run(
                    chief_task,
                    deps=deps,
                    directive_id=directive_id,
                    resume_from=resume_from,
                )
            finally:
                # Drop the reference so the next caller picks up its own
                # logger (or None) — never re-uses the previous session's.
                team._conversation_logger = None

        # Publish completed/failed event (best-effort)
        try:
            from bridge.event_bus import EventBus, DEPARTMENT_TASK_COMPLETED, DEPARTMENT_TASK_FAILED
            bus = EventBus.get_instance()
            event_type = DEPARTMENT_TASK_COMPLETED if result.success else DEPARTMENT_TASK_FAILED
            bus.publish(event_type, {
                "department": department,
                "success": result.success,
                "duration_seconds": result.duration_seconds,
                "error": result.error,
            })
        except Exception:
            pass

        return result

    async def run_parallel(
        self,
        department: str,
        tasks: list[str],
        deps: "BridgeDeps | None" = None,
    ) -> list[TeamResult]:
        """Route multiple tasks to one department and run them in parallel.

        Returns one TeamResult per task. Individual failures do not abort the batch.
        """
        team = self.get_team(department)
        return await team.run_parallel(tasks, deps=deps)
