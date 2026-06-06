"""Skill registry, session hooks, and orchestration command handlers.

Verbs: skills, failures, features, skill_audit, careful, freeze, relax,
hooks, verify, redundancy, deprecation_report, proactive, project,
projects, dispatch, workflows.

Mixed into `bridge.commands.CommandHandler` via multiple inheritance.

Demote-split tracked under issue #1305 (umbrella). Pattern: PR #1687.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..skill_allocator import AgentSkillReport, Role, SkillAllocator, Zone

logger = logging.getLogger(__name__)

# Department-prefix convention for ``<dept>-<role-or-name>.md`` agents.
# Zone 3 has a single department (engineering); zone 4 has the autonomous
# department family. Anything not in either set falls through to the
# manifest-lookup path in ``_resolve_agent_identity``.
_ZONE3_DEPARTMENTS: frozenset[str] = frozenset({"engineering"})
_ZONE4_DEPARTMENTS: frozenset[str] = frozenset(
    {"design", "qa", "ops", "strategy", "job_search", "board", "outreach"}
)


def _resolve_agent_identity(
    agent_name: str,
    allocator: "SkillAllocator",
) -> tuple["Zone", str | None, "Role | None"]:
    """Map an agent name to (zone, department, role).

    Heuristic:
      1. Department-prefix convention: ``engineering-foo`` → zone 3 /
         engineering; ``design-foo`` / ``qa-foo`` / ``ops-foo`` /
         ``strategy-foo`` / ``job_search-foo`` / ``board-foo`` /
         ``outreach-foo`` → zone 4 / that department.
      2. Role: agents ending in ``-chief`` are chiefs; everything else
         under a known department is a specialist.
      3. Ancillary agents (no known prefix — e.g. ``ai-engineer``,
         ``swift-expert``): scan the manifest for any agent-narrowed
         rule that names this agent and adopt that rule's
         ``(zone, department)``. Falls back to zone 3 / no dept / no
         role when nothing matches, which yields an empty report
         (default-deny) rather than raising.
    """
    head, _, _ = agent_name.partition("-")
    role: "Role | None"
    role = "chief" if agent_name.endswith("-chief") else "specialist"

    if head in _ZONE3_DEPARTMENTS:
        return 3, head, role
    if head in _ZONE4_DEPARTMENTS:
        return 4, head, role

    # Ancillary: walk rules looking for an agent-narrowed match.
    for rule in allocator.rules:
        if agent_name in rule.agents:
            # Best-effort role: if the rule narrows by role, adopt it;
            # otherwise leave it as specialist (the common case for
            # ancillary engineering agents like ai-engineer).
            ancillary_role: "Role | None" = rule.role if rule.role else "specialist"
            return rule.zone, rule.department, ancillary_role

    # Unknown agent — return zone 3 / no department so default-deny
    # produces an empty report. The operator gets a clear "0 skills"
    # rendering rather than an error.
    return 3, None, None


def _format_agent_skill_report(report: "AgentSkillReport") -> str:
    """Render an ``AgentSkillReport`` as a Discord-friendly markdown block."""
    lines: list[str] = []
    role_str = report.role or "?"
    dept_str = report.department or "?"
    header = (
        f"**Skills for `{report.agent_name}`** "
        f"(zone={report.zone}, dept={dept_str}, role={role_str})"
    )
    lines.append(header)
    lines.append(f"Allowed: {len(report.allowed_skills)} skill(s)")

    if not report.allowed_skills:
        lines.append("")
        lines.append(
            "(default-deny — no allocation rule matched this agent. "
            "Add an allocation in `config/skill-allocation/manifest.yaml` "
            "and reload to grant access.)"
        )
        return "\n".join(lines)

    lines.append("")
    lines.append("```")
    # Width the skill column to the longest name (capped at 40) so
    # the rule column lines up without dominating the table.
    skill_width = min(40, max(len(s) for s, _ in report.source_rules))
    lines.append(f"{'skill'.ljust(skill_width)} | source rule")
    lines.append(f"{'-' * skill_width}-+-{'-' * 30}")
    for skill, rule_summary in report.source_rules:
        lines.append(f"{skill.ljust(skill_width)} | {rule_summary}")
    lines.append("```")

    body = "\n".join(lines)
    # Discord 2000-char cap — truncate with notice if we overflow.
    if len(body) > 1900:
        body = body[:1880] + "\n... (truncated)\n```"
    return body


class SkillsAndHooksMixin:
    """Skill registry, session hooks, project + workflow dispatch handlers."""

    async def _cmd_skills(self, chat_id: str, args: str) -> str:
        """Per-agent skill discovery (Sprint 4.04 / #2151) + skill-evolution view.

        Usage:
            /skills                          — list skill-evolution proposals
            /skills <agent-name>             — show allowed skills + provenance
                                               for a named agent via the
                                               default-deny SkillAllocator
            /skills --gotchas <skill-name>   — render failure-pattern gotchas

        The per-agent surface answers "what skills does this agent have?"
        from the allocator manifest. The proposals surface (no args) is
        kept for backwards-compat with the skill-evolution view that
        predates the allocator.
        """
        stripped = args.strip()

        # /skills --gotchas <skill-name> — keep first so a skill name that
        # happens to look like an agent name doesn't get routed wrong.
        if stripped.startswith("--gotchas"):
            if not self._skill_evolution:
                return "No skills engine — not initialized."
            try:
                parts = stripped.split(None, 1)
                if len(parts) < 2 or not parts[1].strip():
                    return "Usage: /skills --gotchas <skill-name>"
                skill_name = parts[1].strip()
                gotchas = self._skill_evolution.generate_gotchas(skill_name)
                if not gotchas:
                    return f"No failure data found for skill `{skill_name}`."
                return f"**Gotchas for `{skill_name}`**\n\n{gotchas}"
            except Exception as e:
                return f"Skills error: {e}"

        # /skills <agent-name> — per-agent discovery via SkillAllocator.
        # Detect by presence of an arg that doesn't start with "--": the
        # proposals view is the only no-arg form.
        if stripped and not stripped.startswith("--"):
            return self._render_agent_skill_report(stripped)

        # /skills — backwards-compat: skill-evolution proposals view.
        if not self._skill_evolution:
            return "No skills engine — not initialized."
        try:
            proposals = self._skill_evolution.get_proposals()
            if not proposals:
                return "No skill proposals yet. Proposals are generated from recurring failure patterns."
            lines = [f"**Skill Proposals** — {len(proposals)} total\n"]
            for p in proposals[:10]:
                lines.append(
                    f"• [{p.status}] [{p.tier}] **{p.name}** (score: {p.score:.1f})\n"
                    f"  {p.description[:100]}"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"Skills error: {e}"

    def _render_agent_skill_report(self, agent_name: str) -> str:
        """Format an ``AgentSkillReport`` for the operator.

        Resolves ``agent_name`` to (zone, dept, role) by following the
        department-prefix convention (``<dept>-<role-or-name>``) and the
        ``*-chief`` suffix. Ancillary agents without a known prefix are
        attempted against the manifest's agent-narrowed rules to find
        the dept they appear under; if still unresolved, falls back to
        zone 3 / no department / no role so the allocator's default-deny
        path returns an empty report rather than raising.
        """
        allocator = (
            getattr(self._app, "_skill_allocator", None)
            if self._app is not None
            else None
        )
        if allocator is None:
            return (
                "Skill allocator not wired. Per-agent discovery requires "
                "the SkillAllocator (loaded from "
                "`config/skill-allocation/manifest.yaml` at bridge startup)."
            )

        zone, department, role = _resolve_agent_identity(agent_name, allocator)

        try:
            report = allocator.describe_agent(
                zone=zone,
                department=department,
                role=role,
                agent_name=agent_name,
            )
        except Exception as e:
            return f"Skill discovery error for `{agent_name}`: {e}"

        return _format_agent_skill_report(report)

    async def _cmd_failures(self, chat_id: str, args: str) -> str:
        """Show recurring failure patterns detected by skill evolution."""
        if not self._skill_evolution:
            return "Skill evolution engine not initialized."
        try:
            total = self._skill_evolution.failure_count()
            patterns = self._skill_evolution.detect_recurring_failures()
            if not patterns:
                return f"No recurring failure patterns detected ({total} total failures recorded)."
            lines = [f"**Recurring Failures** — {len(patterns)} patterns ({total} total)\n"]
            for fp in patterns[:10]:
                lines.append(
                    f"• **{fp.task_type}** / {fp.error_type}: {fp.count}x "
                    f"(first: {fp.first_seen[:10]}, last: {fp.last_seen[:10]})"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"Failures error: {e}"


    async def _cmd_features(self, chat_id: str, args: str) -> str:
        """List bridge capabilities from feature-spec JSON. Use --module <name> to filter."""
        # NOTE(commands demote-split): file moved from bridge/commands.py to
        # bridge/command_handlers/skills_and_hooks.py, so the depth to `agent/`
        # is one level deeper. Was: parent.parent; now: parent.parent.parent.
        spec_path = Path(__file__).parent.parent.parent / "config" / "feature-specs" / "bridge-capabilities.json"
        try:
            with open(spec_path) as f:
                data = json.load(f)
        except FileNotFoundError:
            return "Feature spec not found. Expected: config/feature-specs/bridge-capabilities.json"
        except json.JSONDecodeError as e:
            return f"Feature spec parse error: {e}"

        features = data.get("features", [])
        module_filter = args.strip().replace("--module", "").strip() if "--module" in args else ""

        if module_filter:
            features = [f for f in features if module_filter.lower() in f.get("module", "").lower()]

        if not features:
            msg = "No features found"
            if module_filter:
                msg += f" matching module '{module_filter}'"
            return msg + "."

        status_icon = {"active": "✓", "beta": "β", "deprecated": "✗", "planned": "○"}
        lines = [f"**Bridge Capabilities** — {len(features)} features"]
        if module_filter:
            lines[0] += f" (module: {module_filter})"
        lines.append("")

        for feat in features:
            icon = status_icon.get(feat.get("status", ""), "?")
            deps = feat.get("depends_on", [])
            dep_str = f" [deps: {', '.join(deps)}]" if deps else ""
            lines.append(
                f"{icon} **{feat['name']}** `{feat['id']}` v{feat['version']}"
            )
            lines.append(f"  {feat['description']}{dep_str}")

        return "\n".join(lines)


    async def _cmd_skill_audit(self, chat_id: str, args: str) -> str:
        """Run frontmatter audit on all SKILL.md files. Shows summary + top issues."""
        import subprocess
        # NOTE(commands demote-split): see /features comment above.
        script = Path(__file__).parent.parent.parent / "scripts" / "audit_skill_frontmatter.py"
        if not script.exists():
            return "Audit script not found at scripts/audit_skill_frontmatter.py"
        try:
            proc = await asyncio.create_subprocess_exec(
                "python3", str(script), "--output", "json",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            if proc.returncode not in (0, 1):  # 0=pass, 1=issues found
                return f"Audit script error (exit {proc.returncode}): {stderr.decode()[:200]}"
        except asyncio.TimeoutError:
            return "Audit timed out after 30s."
        except Exception as e:
            return f"Audit failed: {e}"

        try:
            report = json.loads(stdout.decode())
        except json.JSONDecodeError:
            return f"Audit output parse error: {stdout.decode()[:200]}"

        lines = [
            f"**Skill Frontmatter Audit** — {report['total']} skills scanned",
            f"Passing: {report['passing']} | Issues: {report['with_issues']} | Warnings: {report['with_warnings']}",
        ]
        issues = report.get("issues", [])
        if issues:
            lines.append(f"\n**Issues ({len(issues)} skills):**")
            for r in issues[:10]:
                lines.append(f"• `{r['name']}`: {', '.join(r['missing'])}")
        else:
            lines.append("\nNo required field issues found.")

        warnings_only = report.get("warnings_only", [])
        if warnings_only:
            lines.append(f"\n**Top warnings ({len(warnings_only)} skills have recommendations missing):**")
            for r in warnings_only[:5]:
                lines.append(f"• `{r['name']}`: {r['warnings'][0] if r['warnings'] else ''}")

        return "\n".join(lines)

    # -- Session hook commands (#19) --

    async def _cmd_careful(self, chat_id: str, args: str) -> str:
        """Activate /careful hook: force Opus model + thoroughness signal."""
        if not self._session_hooks:
            return "Session hooks not initialized."
        ok = self._session_hooks.activate("careful")
        if ok:
            return "Careful mode ON. Model forced to Opus. Extra thoroughness enabled."
        return "Hook 'careful' not registered."

    async def _cmd_freeze(self, chat_id: str, args: str) -> str:
        """Activate /freeze hook: read-only mode, no file modifications."""
        if not self._session_hooks:
            return "Session hooks not initialized."
        ok = self._session_hooks.activate("freeze")
        if ok:
            return "Freeze mode ON. Read-only — file modifications blocked."
        return "Hook 'freeze' not registered."

    async def _cmd_relax(self, chat_id: str, args: str) -> str:
        """Deactivate /careful and /freeze hooks."""
        if not self._session_hooks:
            return "Session hooks not initialized."
        deactivated = []
        for name in ("careful", "freeze"):
            if self._session_hooks.deactivate(name):
                deactivated.append(name)
        if deactivated:
            return f"Normal mode. Deactivated: {', '.join(deactivated)}."
        return "No active hooks to deactivate."

    async def _cmd_hooks(self, chat_id: str, args: str) -> str:
        """List all available session hooks and their status."""
        if not self._session_hooks:
            return "Session hooks not initialized."
        available = self._session_hooks.list_available()
        if not available:
            return "No session hooks registered."
        lines = ["**Session Hooks:**"]
        for h in available:
            status = "ON" if h["active"] else "off"
            lines.append(f"  [{status}] **{h['name']}** — {h['description']}")
        return "\n".join(lines)

    async def _cmd_verify(self, chat_id: str, args: str) -> str:
        """Toggle self-verification. /verify on | /verify off | /verify status."""
        if not self._self_verifier:
            return "Self-verifier not initialized."
        sub = args.strip().lower()
        if sub == "on":
            self._self_verifier.enabled = True
            return "Self-verification enabled. Localhost URLs in responses will be verified."
        elif sub == "off":
            self._self_verifier.enabled = False
            return "Self-verification disabled."
        else:
            status = "enabled" if self._self_verifier.enabled else "disabled"
            return f"Self-verification is {status}. Use `/verify on` or `/verify off`."

    async def _cmd_redundancy(self, chat_id: str, args: str) -> str:
        """Show candidate module usage telemetry table (#22)."""
        try:
            from ..metrics import (
                CANDIDATE_MODULE_KEYS,
                CANDIDATE_MODULE_LABELS,
            )
        except ImportError:
            return "Metrics module not available."

        if not self._metrics:
            return "Metrics collector not initialized."

        header = "**Module Usage Telemetry**"
        col_header = f"{'Module':<22} | {'Count':>7} | Last Used"
        separator = f"{'-' * 22}-+-{'-' * 7}-+-{'-' * 18}"
        rows = [col_header, separator]
        for key in CANDIDATE_MODULE_KEYS:
            label = CANDIDATE_MODULE_LABELS.get(key, key)
            count = self._metrics.get_counter(key)
            last = self._metrics.get_last_used(key) or "never"
            rows.append(f"{label:<22} | {count:>7} | {last}")
        table = chr(96) * 3 + chr(10) + chr(10).join(rows) + chr(10) + chr(96) * 3
        return header + chr(10) + table

    async def _cmd_deprecation_report(self, chat_id: str, args: str) -> str:
        """Run the module deprecation analysis and return the report (#24)."""
        import asyncio
        from pathlib import Path
        # NOTE(commands demote-split): file moved one level deeper, so
        # `bridge/` is `Path(__file__).parent.parent` now (was `.parent`).
        bridge_dir = Path(__file__).parent.parent
        report_script = bridge_dir.parent / "scripts" / "module_deprecation_report.py"
        if not report_script.exists():
            return f"Deprecation report script not found at {report_script}"

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(report_script),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            output = stdout.decode(errors="replace").strip()
            if stderr:
                err = stderr.decode(errors="replace").strip()
                logger.warning("Deprecation report stderr: %s", err)
            return output or "Deprecation report produced no output."
        except asyncio.TimeoutError:
            return "Deprecation report timed out after 30s."
        except Exception as e:
            return f"Deprecation report failed: {e}"


    async def _cmd_proactive(self, chat_id: str, args: str) -> str:
        """Enable, disable, or query proactive tick mode.

        Usage:
            /proactive on      — enable proactive (tick) mode
            /proactive off     — disable proactive mode
            /proactive status  — show current state and config
        """
        if self._tick_manager is None:
            return "TickManager not initialized."

        sub = args.strip().lower()
        if sub == "on":
            self._tick_manager.enable()
            return "Proactive mode enabled. Tick loop is now IDLE."
        elif sub == "off":
            self._tick_manager.disable()
            return "Proactive mode disabled."
        elif sub in ("status", ""):
            state = self._tick_manager.state
            enabled = self._tick_manager.enabled
            state_label = state.value.upper()
            lines = [
                f"Proactive mode: {'ENABLED' if enabled else 'DISABLED'}",
                f"State: {state_label}",
                f"Default sleep: {self._tick_manager._default_sleep}s",
                f"Min sleep: {self._tick_manager._min_sleep}s  "
                f"Max sleep: {self._tick_manager._max_sleep}s",
            ]
            # D7.12 #1424 — append the last-7-days scheduler activity if
            # the ProactiveScheduler is wired. Phone-readable shape per
            # D7.11 late-night profile: ≤8 lines added.
            if self._proactive_scheduler is not None:
                try:
                    from bridge.proactive_scheduler import (
                        read_ledger_window,
                        summarize_ledger_for_status,
                    )
                    seven_days_ago = time.time() - 7 * 24 * 3600
                    rows = read_ledger_window(
                        self._proactive_scheduler.ledger_path,
                        since_ts=seven_days_ago,
                    )
                    summary = summarize_ledger_for_status(rows)
                    lines.append("")
                    lines.append("--- Scheduler (last 7 days) ---")
                    dry_label = (
                        "dry-run" if self._proactive_scheduler.dry_run else "live"
                    )
                    sched_running = self._proactive_scheduler.is_running
                    lines.append(
                        f"Scheduler: "
                        f"{'RUNNING' if sched_running else 'STOPPED'} "
                        f"({dry_label})"
                    )
                    lines.append(
                        f"Ticks: {summary['total_ticks']}  "
                        f"by_action: {summary['by_action']}"
                    )
                    if summary["by_skip_reason"]:
                        lines.append(
                            f"Skip reasons: {summary['by_skip_reason']}"
                        )
                    last_picks = summary["last_picks"]
                    if last_picks:
                        lines.append("Last picks:")
                        for p in last_picks:
                            title = (p.get("title") or "")[:60]
                            lines.append(
                                f"  #{p['number']}: {title}"
                            )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "proactive_scheduler status surface failed: %s", exc
                    )
            return "\n".join(lines)
        else:
            return f"Unknown sub-command: {args!r}. Use: /proactive on | off | status"

    async def _cmd_project(self, chat_id: str, args: str) -> str:
        """Show active project details or switch projects.

        Usage:
            /project          — show active project
            /project <name>   — switch to named project
        """
        if self._project_registry is None:
            return "ProjectRegistry not initialized."
        name = args.strip()
        if not name:
            active = self._project_registry.get_active_project_name()
            if not active:
                return "No active project. Use `/project <name>` to switch."
            ctx = self._project_registry.get_active_project_context()
            return ctx or f"Active project: {active}"
        try:
            self._project_registry.set_active_project(name)
            return f"Switched to project: {name}"
        except (KeyError, ValueError) as e:
            return f"Failed to switch project: {e}"

    async def _cmd_projects(self, chat_id: str, args: str) -> str:
        """List all registered projects."""
        if self._project_registry is None:
            return "ProjectRegistry not initialized."
        projects = self._project_registry.list_all()
        if not projects:
            return "No projects registered."
        active = self._project_registry.get_active_project_name()
        lines = [f"**Projects** ({len(projects)} registered):"]
        for p in projects:
            name = p.get("project", p.get("name", "unknown"))
            status = p.get("status", "active")
            marker = " (active)" if name == active else ""
            lines.append(f"  - {name} [{status}]{marker}")
        return "\n".join(lines)

    # -- Dispatch command (Zone 3) --

    async def _cmd_dispatch(self, chat_id: str, args: str) -> str:
        """Route text through RoutingBrain -> WorkOrder -> Dispatcher and report result."""
        verbose = args.startswith("-v ")
        text = args[3:].strip() if verbose else args.strip()

        if not text:
            return "Usage: /dispatch <text> or /dispatch -v <text>"

        brain = self._routing_brain
        if brain is None:
            return "RoutingBrain not configured. Wire set_routing_brain() in app.py startup."

        # Sprint 03.05 — RoutingBrain exposes decide(), not route(). Calling the
        # wrong method silently failed pre-03.05 because brain was always None;
        # now that the manifest wires a real instance, the method-name bug
        # surfaces. Fixed to use the actual API.
        try:
            decision = brain.decide(text)
        except Exception as e:
            return f"Routing error: {e}"

        from ..work_order import Environment, WorkOrder, WorkOrderStatus
        env_map = {
            "subagent": Environment.SUBAGENT,
            "tmux": Environment.TMUX,
            "worktree": Environment.WORKTREE,
            "e2b": Environment.E2B,
            "department": Environment.SUBAGENT,  # department executes via subagent path
        }
        # RoutingDecision.environment is a string literal aligned with Environment
        # enum values; map to the enum, falling back to SUBAGENT for safety.
        environment = env_map.get(
            getattr(decision, "environment", None) or "subagent",
            Environment.SUBAGENT,
        )
        wo = WorkOrder.create(intent=text, skill="manual", project="operator")
        wo = wo.with_environment(environment, rationale=getattr(decision, "reason", ""))
        # Sprint 03.04 — plumb department_target. /dispatch always uses
        # skill="manual" (a non-department skill), so _derive_department
        # returns None and with_department is skipped. Wired here for
        # completeness and to keep parity with the other two creation
        # sites; if /dispatch ever accepts a department-class skill the
        # plumbing is already in place.
        from ..environment_selector import _derive_department
        _derived_dept = _derive_department(wo.skill)
        if _derived_dept is not None and environment is Environment.DEPARTMENT:
            wo = wo.with_department(_derived_dept)
        wo = wo.transition(WorkOrderStatus.ASSIGNED)

        dispatcher = self._dispatcher
        intent_val = getattr(getattr(decision, "intent", None), "value", "unknown")
        complexity = getattr(decision, "complexity", "?")
        confidence = getattr(decision, "confidence", 0.0)
        reason = getattr(decision, "reason", "")
        dept_hint = getattr(decision, "department_hint", None)
        if dispatcher is None:
            lines = [
                "**Routing decision** (no dispatcher wired)",
                f"Intent: `{intent_val}` | Complexity: `{complexity}` | Confidence: `{confidence:.2f}`",
                f"Environment: `{environment.value}`"
                + (f" (dept: `{dept_hint}`)" if dept_hint else ""),
                f"Reason: {reason}",
            ]
            return "\n".join(lines)

        try:
            result = await dispatcher.dispatch(wo)
        except Exception as e:
            return f"Dispatch error: {e}"

        handled_icon = "OK" if result.handled else "NO"
        valid_icon = "OK" if result.valid else "NO"
        lines = [
            "**Dispatch result**",
            f"Intent: `{intent_val}` | Complexity: `{complexity}` | Confidence: `{confidence:.2f}`",
            f"Environment: `{environment.value}`"
            + (f" (dept: `{dept_hint}`)" if dept_hint else ""),
            f"Dispatched: {handled_icon} | Valid: {valid_icon}",
        ]
        if verbose:
            lines.append(f"Reason: {result.reason}")
            res = getattr(result, "result", None)
            if res is not None:
                resp = getattr(res, "response_text", "") or ""
                lines.append(f"Response: {resp[:200]}...")
        return "\n".join(lines)

    async def _cmd_workflows(self, chat_id: str, args: str) -> str:
        """List defined workflows and their status, or trigger/cancel/detail.

        Usage:
          /workflows                  — list all workflows
          /workflows <name>           — details + recent runs
          /workflows trigger <name>   — manually trigger a workflow
          /workflows cancel <run_id>  — cancel an active run
          /workflows reload           — reload YAML definitions from disk
        """
        if self._workflow_registry is None:
            return "WorkflowRegistry is not initialised."

        parts = args.strip().split(None, 1) if args.strip() else []

        if not parts:
            return self._workflow_registry.format_list()

        subcommand = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if subcommand == "reload":
            count = self._workflow_registry.reload()
            return f"Reloaded {count} workflow(s)."

        if subcommand == "trigger":
            name = rest.strip()
            if not name:
                return "Usage: /workflows trigger <name>"
            try:
                run_id = self._workflow_registry.trigger(
                    name, engine=self._workflow_engine
                )
            except KeyError:
                return f"No workflow named {name!r}."
            if run_id is None:
                return (
                    f"Workflow {name!r} queued (no engine attached — "
                    "set engine via set_workflow_engine)."
                )
            return f"Workflow {name!r} started. Run ID: `{run_id}`"

        if subcommand == "cancel":
            run_id = rest.strip()
            if not run_id:
                return "Usage: /workflows cancel <run_id>"
            ok = await self._workflow_registry.cancel(
                run_id, engine=self._workflow_engine
            )
            return (
                f"Run `{run_id}` cancelled."
                if ok
                else f"Could not cancel run `{run_id}` (not found or already terminal)."
            )

        # Default: treat subcommand as a workflow name → details
        return self._workflow_registry.format_detail(subcommand)

    # -- Sprint 05.10 — second-brain operator UX (#1020) --

