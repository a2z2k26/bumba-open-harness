"""Zone 4 Layer 2 WorkflowRegistry.

Loads all YAML workflow definitions from ``config/workflows/``, validates them
via the Pydantic schema, and exposes list / get / trigger / cancel operations.

The registry is intentionally lightweight — it does NOT run workflows itself.
Execution is delegated to ``WorkflowEngine`` (sprint F-W.6+). The registry
provides the operator-facing view and the triggering entry point.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from bridge.dispatch_metrics import increment_module_counter

log = logging.getLogger(__name__)

# Deferred import so the registry can be instantiated without pydantic/yaml
# (tests that only test list/get operations don't need the full schema).
_CONFIG_DIR_DEFAULT = Path(__file__).parent.parent / "config" / "workflows"


class WorkflowRegistry:
    """Load, validate, and provide access to workflow definitions.

    Parameters
    ----------
    config_dir:
        Directory containing ``*.yaml`` workflow definitions.
        Defaults to ``agent/config/workflows/``.
    store:
        Optional ``WorkOrderStore`` instance. When present, ``last_run()``
        queries are backed by the ``workflow_runs`` table.
    """

    def __init__(
        self,
        config_dir: Path | None = None,
        store: Any | None = None,
    ) -> None:
        self._config_dir = Path(config_dir) if config_dir else _CONFIG_DIR_DEFAULT
        self._store = store
        self._workflows: dict[str, Any] = {}  # name → WorkflowConfig
        self._load_all()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_all(self) -> None:
        """(Re)load all YAML files from the config directory."""
        from config.workflows._schema import load_workflow_config

        self._workflows.clear()
        if not self._config_dir.exists():
            log.warning(
                "Workflow config directory does not exist: %s", self._config_dir
            )
            return

        for yaml_file in sorted(self._config_dir.glob("*.yaml")):
            try:
                cfg = load_workflow_config(yaml_file.read_text())
                self._workflows[cfg.name] = cfg
                log.debug("Loaded workflow: %s", cfg.name)
            except Exception as exc:  # noqa: BLE001
                log.error("Failed to load workflow %s: %s", yaml_file.name, exc)

    def reload(self) -> int:
        """Reload all workflow definitions. Returns count of loaded workflows."""
        self._load_all()
        return len(self._workflows)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def list(self) -> list[dict[str, Any]]:
        """Return summary info for all loaded workflows.

        Each entry contains:
        - ``name`` — workflow identifier
        - ``trigger`` — explicit | schedule | webhook
        - ``schedule`` — cron expression or None
        - ``webhook`` — event name or None
        - ``steps`` — number of steps
        - ``budget_usd`` — max_cost_usd cap
        - ``last_run`` — most recent WorkflowRun or None (if store attached)
        """
        result = []
        for cfg in self._workflows.values():
            entry: dict[str, Any] = {
                "name": cfg.name,
                "trigger": cfg.trigger,
                "schedule": cfg.schedule,
                "webhook": cfg.webhook,
                "steps": len(cfg.steps),
                "budget_usd": cfg.budget.max_cost_usd,
                "last_run": None,
            }
            if self._store is not None:
                runs = self._store.list_runs_for_workflow(cfg.name, limit=1)
                if runs:
                    r = runs[0]
                    entry["last_run"] = {
                        "id": r.id,
                        "status": r.status,
                        "created_at": r.created_at,
                        "cost_usd": r.cost_usd,
                    }
            result.append(entry)
        return result

    def get(self, name: str) -> Any | None:
        increment_module_counter("workflow_registry.get", tier=1)
        """Return a WorkflowConfig by name, or None if not found."""
        return self._workflows.get(name)

    def names(self) -> list[str]:
        """Return all loaded workflow names."""
        return sorted(self._workflows.keys())

    # ------------------------------------------------------------------
    # Matching (Sprint 5.00c / #2155) — workflow-first dispatch
    # ------------------------------------------------------------------

    def match(self, directive: str) -> dict[str, Any] | None:
        """Return the best workflow match for an operator directive, or None.

        Rule-based matching (no embeddings) — looks for the workflow name
        as a substring in the directive. Workflows use dotted names like
        ``design.design_system_audit``; the matcher considers BOTH the full
        dotted name and the trailing portion after the last dot, plus a
        ``slug-form`` variant where ``_`` becomes space.

        Returns a dict with:
        - ``name``: the workflow name
        - ``confidence``: float in [0.0, 1.0]
        - ``matched_token``: the substring that triggered the match

        Returns None when no workflow's name (or recognized variant)
        appears in the directive.

        Confidence is heuristic:
        - 1.0 — full dotted name appears verbatim
        - 0.8 — trailing token appears verbatim (e.g. "design_system_audit")
        - 0.6 — slug-form appears (e.g. "design system audit")

        The dispatcher applies a threshold (default 0.6 — accept any
        recognized match) and short-circuits to ``workflow_engine.execute``
        when ``workflow_first_dispatch_enabled`` is True.
        """
        if not directive or not isinstance(directive, str):
            return None
        directive_lower = directive.lower()
        best: dict[str, Any] | None = None
        for name in self._workflows:
            # Full dotted name match (highest confidence)
            if name.lower() in directive_lower:
                candidate = {"name": name, "confidence": 1.0, "matched_token": name}
                if best is None or candidate["confidence"] > best["confidence"]:
                    best = candidate
                continue
            # Trailing-token match (after last dot)
            if "." in name:
                trailing = name.rsplit(".", 1)[-1]
                if trailing.lower() in directive_lower:
                    candidate = {"name": name, "confidence": 0.8, "matched_token": trailing}
                    if best is None or candidate["confidence"] > best["confidence"]:
                        best = candidate
                    continue
                # Slug-form match (underscores → spaces)
                slug = trailing.replace("_", " ")
                if slug.lower() in directive_lower:
                    candidate = {"name": name, "confidence": 0.6, "matched_token": slug}
                    if best is None or candidate["confidence"] > best["confidence"]:
                        best = candidate
        return best

    # ------------------------------------------------------------------
    # Triggering (stub — engine integration in F-W.6+)
    # ------------------------------------------------------------------

    def trigger(
        self,
        name: str,
        inputs: dict[str, Any] | None = None,
        *,
        engine: Any | None = None,
    ) -> str | None:
        """Trigger a workflow by name.

        If ``engine`` is provided, delegates to ``engine.start(cfg, inputs)``.
        Otherwise returns None and logs a warning (for operator feedback).

        Returns the new run_id, or None if no engine is configured.
        """
        cfg = self.get(name)
        if cfg is None:
            raise KeyError(f"No workflow named {name!r}")
        if engine is None:
            log.warning(
                "WorkflowRegistry.trigger('%s') called but no engine is attached. "
                "Set engine= to execute workflows.",
                name,
            )
            return None
        return engine.start(cfg, inputs or {})

    async def cancel(self, run_id: str, *, engine: Any | None = None) -> bool:
        """Cancel an active workflow run.

        Delegates to ``engine.cancel(run_id)`` if engine is provided.
        Returns True if the cancellation was accepted.

        C.06 (#2061): ``engine.cancel`` is now an async coroutine — it
        cancels the executing asyncio Task and awaits cleanup before
        returning. This delegator follows the same shape.
        """
        if engine is None:
            log.warning(
                "WorkflowRegistry.cancel('%s') called but no engine is attached.",
                run_id,
            )
            return False
        return await engine.cancel(run_id)

    # ------------------------------------------------------------------
    # Formatting helpers (used by /workflows command)
    # ------------------------------------------------------------------

    def format_list(self) -> str:
        """Return a human-readable summary of all workflows for Discord."""
        entries = self.list()
        if not entries:
            return "No workflows loaded."

        lines = ["**Workflows**\n"]
        for e in entries:
            last = e["last_run"]
            last_str = (
                f"last run: {last['status']} ({last['created_at'][:10]})"
                if last
                else "never run"
            )
            lines.append(
                f"• **{e['name']}** — {e['trigger']} | "
                f"{e['steps']} steps | ${e['budget_usd']:.2f} cap | {last_str}"
            )
        return "\n".join(lines)

    def format_detail(self, name: str) -> str:
        """Return detailed info about a single workflow for Discord."""
        cfg = self.get(name)
        if cfg is None:
            return f"Workflow {name!r} not found."

        lines = [f"**{cfg.name}**", f"Trigger: `{cfg.trigger}`"]
        if cfg.schedule:
            lines.append(f"Schedule: `{cfg.schedule}`")
        if cfg.webhook:
            lines.append(f"Webhook: `{cfg.webhook}`")
        lines.append(
            f"Budget: ${cfg.budget.max_cost_usd:.2f} / "
            f"{cfg.budget.max_duration_seconds}s"
        )
        lines.append(f"\nSteps ({len(cfg.steps)}):")
        for step in cfg.steps:
            stype = getattr(step, "type", "?")
            lines.append(f"  {step.name} [{stype}]")

        if self._store is not None:
            runs = self._store.list_runs_for_workflow(name, limit=5)
            if runs:
                lines.append("\nRecent runs:")
                for r in runs:
                    lines.append(
                        f"  {r.id[:8]}… {r.status} "
                        f"${r.cost_usd:.3f} ({r.created_at[:10]})"
                    )

        return "\n".join(lines)
