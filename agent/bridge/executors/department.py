"""DepartmentExecutor — runs a WorkOrder through a Zone 4 department team.

S04: Threads mcp_allowed_servers through BridgeDeps from the department's
YAML config so each department runs against a filtered MCP subset.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bridge.claude_runner import ClaudeResult
    from bridge.work_order import WorkOrder
    from teams._registry import DepartmentRegistry

log = logging.getLogger(__name__)

# Default location of per-department YAML configs (relative to repo root)
_CONFIG_TEAMS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "config" / "teams"


class DepartmentExecutor:
    """Executes a WorkOrder by routing it to a Zone 4 department.

    **Status: ACTIVE** — see ``docs/architecture/executor-roadmap.md``.

    S04: Loads the department's mcp_servers subset from its YAML config
    and injects it into BridgeDeps.mcp_allowed_servers so the registry
    can build a filtered MCP config for the department run.
    """

    def __init__(
        self,
        *,
        department_registry: "DepartmentRegistry | None",
        app: object | None,
        event_bus: object | None,
    ) -> None:
        self._registry = department_registry
        self._app = app
        self._event_bus = event_bus

    @property
    def _teams_config_dir(self) -> Path:
        """Directory containing per-department YAML configs."""
        return _CONFIG_TEAMS_DIR

    def _load_dept_mcp_subset(self, dept: str) -> tuple[tuple[str, ...], str]:
        """Load the MCP-server allowlist + mode from the department's YAML config.

        Sprint P2.4 (2026-05-11) — prefers the structured `team.mcp` block
        over the legacy top-level `mcp_servers` list. Both are accepted:

        - `team.mcp.allowed_servers` is the documented post-P2.4 surface and
          composes with `team.mcp.mode` to express "permissive empty" vs
          "deny-by-default empty" intent.
        - The legacy top-level `mcp_servers` (kept for backward compat with
          unmigrated YAMLs) is read only when the structured block is absent.
          Legacy callers always run under `mode="permissive"`.

        Returns ``(servers, mode)`` — empty tuple under "permissive" mode
        means "inherit bridge default."
        """
        yaml_path = self._teams_config_dir / f"{dept}.yaml"
        if not yaml_path.exists():
            return ((), "permissive")
        try:
            import yaml  # PyYAML — available in the bridge venv
            cfg = yaml.safe_load(yaml_path.read_text()) or {}
            team_block = cfg.get("team", {}) or {}
            mcp_block = team_block.get("mcp", None)
            if isinstance(mcp_block, dict):
                # Structured P2.4 block present — use its mode + servers
                servers = tuple(mcp_block.get("allowed_servers") or ())
                mode = mcp_block.get("mode", "permissive")
                return (servers, mode)
            # Legacy top-level fallback — kept for unmigrated YAMLs.
            servers = cfg.get("mcp_servers", ())
            return (tuple(servers) if servers else (), "permissive")
        except Exception as exc:
            log.warning("_load_dept_mcp_subset: failed to parse %s: %s", yaml_path, exc)
            return ((), "permissive")

    async def execute(self, wo: "WorkOrder") -> "ClaudeResult":
        """Route the WorkOrder to its target department and return the result.

        Raises:
            RuntimeError: If registry is not configured.
            ValueError: If the target department is not registered.
            RuntimeError: If the team result indicates failure.
            Any exception from registry.route propagates unchanged.
        """
        if self._registry is None:
            raise RuntimeError("department registry not configured")

        dept = wo.department_target or ""
        if dept not in self._registry.department_names():
            raise ValueError(f"unknown department: {dept}")

        from teams._types import BridgeDeps

        cost_limit = 2.0
        try:
            cost_limit = self._registry.get_cost_limit(dept)
        except Exception:
            pass

        # Load MCP subset + mode for this department (S04 write jail; P2.4)
        mcp_subset, mcp_mode = self._load_dept_mcp_subset(dept)

        # #630: thread permission_mode from WorkOrder constraints into BridgeDeps
        perm_mode = getattr(wo.constraints, "permission_mode", "bypassPermissions")

        if self._app is not None:
            deps = BridgeDeps.from_app(
                self._app,
                session_id=wo.id[:12],
                department=dept,
                cost_limit_usd=cost_limit,
                mcp_allowed_servers=mcp_subset,
                mcp_mode=mcp_mode,
                permission_mode=perm_mode,
            )
        else:
            deps = BridgeDeps(
                session_id=wo.id[:12],
                department=dept,
                operator_id="",
                memory_store=None,
                event_bus=self._event_bus,
                trust_manager=None,
                cost_tracker=None,
                knowledge_search=None,
                cost_limit_usd=cost_limit,
                mcp_allowed_servers=mcp_subset,
                mcp_mode=mcp_mode,
                permission_mode=perm_mode,
            )

        log.info(
            "DepartmentExecutor: WO %s → %s (mcp_mode=%s, servers: %s)",
            wo.id[:8], dept, mcp_mode,
            ", ".join(mcp_subset) or "<empty>",
        )
        t0 = time.monotonic()
        team_result = await self._registry.route(dept, wo.intent, deps)
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        if not team_result.success:
            raise RuntimeError(
                f"department {dept} failed: {team_result.error}"
            )

        from bridge.claude_runner import ClaudeResult

        return ClaudeResult(
            response_text=team_result.manager_output,
            session_id=f"dept-{dept}-{wo.id[:8]}",
            cost_usd=team_result.total_cost_usd,
            num_turns=0,
            duration_ms=elapsed_ms,
            is_error=False,
        )
