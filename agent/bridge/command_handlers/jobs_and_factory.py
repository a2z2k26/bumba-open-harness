"""Job-search pipeline + Dark Factory + experiment harness command handlers.

Verbs: job_status, job_funnel, funnel, rubric_evidence, soak_status,
soak_verify, factory (+ _handle_factory_status / pause / resume /
escalate helpers), experiment_branches, experiment_finalize,
experiment_finalize_status.

Mixed into `bridge.commands.CommandHandler` via multiple inheritance.

Demote-split tracked under issue #1305 (umbrella). Pattern: PR #1687.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class JobsAndFactoryMixin:
    """Job-search, Dark Factory, and experiment harness command handlers."""

    async def _cmd_job_status(self, chat_id: str, args: str) -> str:
        """Show today's job-search funnel counters (Z2-S2.1).

        Usage:
            /job-status          — today's funnel summary
            /job-status <date>   — funnel for a specific ISO date (YYYY-MM-DD)
        """
        from job_search.funnel import FunnelStore, format_funnel_discord, today_key

        data_dir = Path(self._db.db_path).parent
        store = FunnelStore(data_dir)
        date_key = args.strip() or today_key()
        day = store.get(date_key)
        return format_funnel_discord(day, date_key)

    async def _cmd_job_funnel(self, chat_id: str, args: str) -> str:
        """Alias for /job-status — show today's job-search funnel (Z2-S2.1)."""
        return await self._cmd_job_status(chat_id, args)

    async def _cmd_funnel(self, chat_id: str, args: str) -> str:
        """Structured funnel-failure aggregator — per-board/ATS/step report (D5.8).

        Usage:
            /funnel                      — job-search funnel, last 7 days
            /funnel job-search           — job-search funnel, last 7 days
            /funnel job-search 7d        — last 7 days
            /funnel job-search 30d       — last 30 days
            /funnel job-search all       — all-time
        """
        parts = args.strip().split() if args.strip() else []
        subcommand = parts[0] if parts else "job-search"
        window = parts[1] if len(parts) > 1 else "7d"
        if subcommand == "job-search":
            try:
                from job_search.funnel import aggregate_funnel, format_funnel_report_text
                report = aggregate_funnel(window=window)
                return format_funnel_report_text(report)
            except Exception as exc:
                return f"Funnel error: {exc}"
        return f"Unknown funnel subcommand: {subcommand}"

    async def _cmd_rubric_evidence(self, chat_id: str, args: str) -> str:
        """Show the rolling 14-day rubric-gate evidence summary (Sprint 06.08).

        Usage:
            /rubric_evidence            — re-aggregate window then format
            /rubric_evidence cached     — read summary.json without re-aggregating

        The harness writes daily JSONL records at
        ``data/rubric-evidence/YYYY-MM-DD.jsonl`` and a rolling summary at
        ``data/rubric-evidence/summary.json``. Refer to issue #1029 for the
        observation plan and Sprint 06.08 for the post-soak operator decision.
        """
        from job_search.rubric_evidence import (
            aggregate_window,
            format_summary_for_discord,
            load_summary,
        )

        data_dir = Path(self._db.db_path).parent
        evidence_dir = data_dir / "rubric-evidence"

        mode = args.strip().lower()
        try:
            if mode == "cached":
                summary = load_summary(evidence_dir=evidence_dir)
            else:
                summary = aggregate_window(evidence_dir=evidence_dir)
        except Exception as exc:  # pragma: no cover — defensive
            return f"rubric-evidence load failed: {exc}"

        return format_summary_for_discord(summary)

    async def _cmd_soak_status(self, chat_id: str, args: str) -> str:
        """Show the 14-day Dark Factory soak harness summary (Sprint 14.11).

        Usage:
            /soak_status                — 14d window ending today
            /soak_status <days>         — custom window (positive int)

        The harness writes JSONL records at
        ``data/factory-soak/soak-YYYY-MM-DD.jsonl``. Refer to issue
        #1050 for the production-enable gate spec.
        """
        from bridge.factory.soak_harness import (
            aggregate_soak_window,
            format_report_for_discord,
        )

        days = 14
        arg = args.strip()
        if arg:
            try:
                requested = int(arg)
                if requested > 0:
                    days = requested
            except ValueError:
                return (
                    f"Invalid argument: `{arg}`. Usage: `/soak_status` "
                    f"or `/soak_status <days>` (positive integer)."
                )

        # Pull operator-tunable thresholds from the live config when available.
        min_correctness = 0.80
        min_verified = 5
        try:
            from bridge.config import load_config
            cfg = load_config()
            min_correctness = float(
                getattr(cfg, "factory_soak_min_correctness_rate", 0.80)
            )
            min_verified = int(
                getattr(cfg, "factory_soak_min_verified_count", 5)
            )
        except Exception:
            pass  # Use defaults

        data_dir = Path(self._db.db_path).parent
        log_dir = data_dir / "factory-soak"
        try:
            report = aggregate_soak_window(
                days=days,
                log_dir=log_dir,
                min_correctness_rate=min_correctness,
                min_verified_count=min_verified,
            )
        except Exception as exc:  # pragma: no cover — defensive
            return f"soak-status load failed: {exc}"

        return format_report_for_discord(report)

    async def _cmd_soak_verify(self, chat_id: str, args: str) -> str:
        """Record an operator verification for a soak entry (Sprint 14.11).

        Usage:
            /soak_verify <issue_number> <correct|incorrect|skipped> [notes]

        The most-recent soak record for ``issue_number`` is updated with
        the operator's verdict. After 5 ``correct`` verdicts at ≥80%
        correctness over ≥14 days, ``/soak_status`` reports
        ``ready_to_enable=True``.
        """
        from bridge.factory.soak_harness import update_verification

        parts = args.strip().split(maxsplit=2)
        if len(parts) < 2:
            return (
                "Usage: `/soak_verify <issue_number> <correct|incorrect|skipped> [notes]`\n"
                "Example: `/soak_verify 1234 correct factory's call matched mine`"
            )

        try:
            issue_number = int(parts[0])
        except ValueError:
            return (
                f"Invalid issue number: `{parts[0]}`. "
                f"Pass an integer (e.g. `1234`)."
            )

        verdict = parts[1].lower().strip()
        if verdict not in ("correct", "incorrect", "skipped"):
            return (
                f"Invalid verdict: `{parts[1]}`. "
                f"Must be one of: `correct`, `incorrect`, `skipped`."
            )

        notes = parts[2] if len(parts) > 2 else ""

        data_dir = Path(self._db.db_path).parent
        log_dir = data_dir / "factory-soak"
        try:
            updated = update_verification(
                issue_number,
                verification=verdict,  # type: ignore[arg-type]
                notes=notes,
                log_dir=log_dir,
            )
        except Exception as exc:  # pragma: no cover — defensive
            return f"soak-verify failed: {exc}"

        if not updated:
            return (
                f"No soak entry found for issue #{issue_number}. "
                f"The factory soak harness must have processed it first."
            )

        return (
            f"Recorded `{verdict}` verification for issue #{issue_number}. "
            f"Run `/soak_status` to check production-enable readiness."
        )

    async def _cmd_factory(self, chat_id: str, args: str) -> str:
        """Operator UX for the Dark Factory loop (Sprint 14.11, issue #1049).

        Subcommands:
            /factory status                   — orchestrator + soak summary
            /factory pause [reason]           — set the pause flag
            /factory resume                   — clear the pause flag
            /factory escalate <issue#> [why]  — manually route to needs-human

        The pause flag lives at ``data/factory-paused.flag``. Both the
        production orchestrator and the soak harness check it at the top
        of each tick — a paused factory is a no-op factory.
        """
        from bridge.factory import operator_commands as ops

        parts = args.strip().split(maxsplit=1)
        subcommand = parts[0].lower() if parts else ""
        rest = parts[1] if len(parts) > 1 else ""

        if subcommand in ("", "status"):
            return await self._handle_factory_status(ops)
        if subcommand == "pause":
            return self._handle_factory_pause(ops, rest)
        if subcommand == "resume":
            return self._handle_factory_resume(ops)
        if subcommand == "escalate":
            return self._handle_factory_escalate(ops, rest)

        return (
            f"Unknown subcommand: `{subcommand}`. "
            f"Valid: `status`, `pause`, `resume`, `escalate`.\n"
            f"Examples:\n"
            f"  `/factory status`\n"
            f"  `/factory pause stuck on lock contention`\n"
            f"  `/factory resume`\n"
            f"  `/factory escalate 1234 per-target lock held for 3h`"
        )

    async def _handle_factory_status(self, ops_module: Any) -> str:
        """Compose ``/factory status`` output. Defensive on every source."""
        data_dir = Path(self._db.db_path).parent
        flag_path = data_dir / "factory-paused.flag"
        soak_log_dir = data_dir / "factory-soak"

        orchestrator_enabled = False
        try:
            from bridge.config import load_config
            cfg = load_config()
            orchestrator_enabled = bool(
                getattr(cfg, "factory_orchestrator_enabled", False)
            )
        except Exception:
            pass  # leave False — defensive default

        try:
            status = ops_module.collect_status(
                orchestrator_enabled=orchestrator_enabled,
                log_dir=data_dir,
                soak_log_dir=soak_log_dir,
                flag_path=flag_path,
                cost_tracker=self._cost_tracker,
            )
        except Exception as exc:  # pragma: no cover — defensive
            return f"Factory status load failed: {exc}"
        return ops_module.format_status_for_discord(status)

    def _handle_factory_pause(self, ops_module: Any, reason: str) -> str:
        """Compose ``/factory pause`` output."""
        data_dir = Path(self._db.db_path).parent
        flag_path = data_dir / "factory-paused.flag"
        if ops_module.is_paused(flag_path):
            return (
                "Factory already paused. Run `/factory resume` to re-enable.\n"
                "Use `/factory status` for pause metadata."
            )
        try:
            ops_module.pause(flag_path, by="operator", reason=reason.strip())
        except Exception as exc:
            return f"Pause failed: {exc}"
        if reason.strip():
            return (
                f"Factory paused. Reason: _{reason.strip()}_.\n"
                f"Run `/factory resume` to re-enable."
            )
        return "Factory paused. Run `/factory resume` to re-enable."

    def _handle_factory_resume(self, ops_module: Any) -> str:
        """Compose ``/factory resume`` output."""
        data_dir = Path(self._db.db_path).parent
        flag_path = data_dir / "factory-paused.flag"
        try:
            removed = ops_module.resume(flag_path)
        except Exception as exc:
            return f"Resume failed: {exc}"
        if removed:
            return "Factory resumed. Next tick will run normally."
        return "Factory was not paused. No change."

    def _handle_factory_escalate(self, ops_module: Any, rest: str) -> str:
        """Compose ``/factory escalate <issue> [reason]`` output."""
        if not rest.strip():
            return (
                "Usage: `/factory escalate <issue_number> [reason]`\n"
                "Example: `/factory escalate 1234 lock contended for 3h`"
            )
        parts = rest.strip().split(maxsplit=1)
        try:
            issue_number = int(parts[0])
        except ValueError:
            return (
                f"Invalid issue number: `{parts[0]}`. "
                f"Pass an integer (e.g. `1234`)."
            )
        reason = parts[1] if len(parts) > 1 else ""
        try:
            outcome = ops_module.escalate_issue(
                issue_number, reason=reason, actor="operator"
            )
        except Exception as exc:  # pragma: no cover — escalate_issue swallows
            return f"Escalate failed: {exc}"

        if not outcome.get("transitioned"):
            prior = outcome.get("prior_state") or "<unknown>"
            return (
                f"Escalate for issue #{issue_number} did not change state "
                f"(prior=`{prior}`). The label move failed — check `gh` auth "
                f"or that the issue carries a `factory:*` state label."
            )
        return (
            f"Issue #{issue_number} escalated to "
            f"`{outcome.get('new_state')}` (was `{outcome.get('prior_state') or 'none'}`). "
            f"Comment posted: {bool(outcome.get('comment_posted'))}."
        )


    async def _cmd_experiment_branches(self, chat_id: str, args: str) -> str:
        """List the append-only ``autoresearch/iter-*`` audit-branch trail.

        Sprint 02.04 / spec ref-audit-02-04 (issue #978). Read-only — this
        command never creates, deletes, or pushes branches. The audit
        trail itself is maintained by ``scripts/experiment_loop.py``.

        Usage:
            /experiment_branches              — last 10 branches
            /experiment_branches <iter_id>    — diff stat + metadata for one
        """
        # Feature-flag check first: if the audit trail isn't enabled,
        # there are no branches to list and the operator should know
        # how to turn it on.
        try:
            from ..config import load_config

            cfg = load_config(skip_secrets=True, skip_validation=True)
            enabled = bool(getattr(cfg, "experiment_audit_branches_enabled", False))
        except Exception as exc:  # noqa: BLE001 — config errors are non-fatal here
            return f"audit-branches: config lookup failed: {exc}"

        if not enabled:
            return (
                "audit-branches feature is OFF. Enable in `bridge.toml`:\n"
                "```\n[experiment_loop]\naudit_branches_enabled = true\n```\n"
                "Then restart the bridge. Branches accumulate at "
                "`autoresearch/iter-*`."
            )

        # Imports are local so this module stays test-importable without
        # the experiment_audit_branches script on sys.path.
        # NOTE(commands demote-split): file moved from bridge/commands.py to
        # bridge/command_handlers/jobs_and_factory.py — one level deeper. Was:
        # .resolve().parent.parent; now: .resolve().parent.parent.parent.
        agent_dir = Path(__file__).resolve().parent.parent.parent
        scripts_dir = agent_dir / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        try:
            from experiment_audit_branches import (
                list_audit_branches,
                make_branch_name,
                read_branch_outcome,
            )
        except ImportError as exc:
            return f"audit-branches: import failed: {exc}"

        repo_root = agent_dir.parent
        jsonl_path = agent_dir / "data" / "experiments.jsonl"
        target = args.strip()

        # Branch detail mode: ``/experiment_branches <iter_id>``.
        if target:
            branch_name = (
                target if target.startswith("autoresearch/iter-")
                else make_branch_name(target)
            )
            try:
                summaries = await asyncio.to_thread(
                    list_audit_branches,
                    repo_root=repo_root,
                    jsonl_path=jsonl_path,
                )
            except Exception as exc:  # noqa: BLE001 — defensive
                return f"audit-branches: list failed: {exc}"

            match = next(
                (s for s in summaries if s.branch_name == branch_name),
                None,
            )
            if match is None:
                return f"audit-branches: branch `{branch_name}` not found."

            # Diff stat against main — fail-soft.
            diff_stat = ""
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git",
                    "diff",
                    f"main..{branch_name}",
                    "--stat",
                    cwd=str(repo_root),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
                diff_stat = stdout.decode().strip()
            except Exception as exc:  # noqa: BLE001 — defensive
                diff_stat = f"(diff lookup failed: {exc})"

            note_outcome = await asyncio.to_thread(
                read_branch_outcome,
                branch_name,
                repo_root=repo_root,
            )

            outcome = match.outcome or note_outcome or "(unknown)"
            fitness = (
                f"{match.fitness_value:+.4f}"
                if match.fitness_value is not None
                else "—"
            )
            cost = (
                f"${match.cost_usd:.4f}" if match.cost_usd is not None else "—"
            )
            lines = [
                f"**{branch_name}**",
                f"  iter_id: `{match.iter_id}`",
                f"  commit: `{match.commit_sha[:12]}` — {match.commit_subject}",
                f"  authored: {match.authored_at_iso}",
                f"  outcome: {outcome}",
                f"  fitness Δ: {fitness}",
                f"  cost: {cost}",
                "",
                "**diff stat (vs main):**",
                f"```\n{diff_stat or '(no diff)'}\n```",
            ]
            return "\n".join(lines)

        # Listing mode: last 10 branches.
        try:
            summaries = await asyncio.to_thread(
                list_audit_branches,
                repo_root=repo_root,
                jsonl_path=jsonl_path,
            )
        except Exception as exc:  # noqa: BLE001 — defensive
            return f"audit-branches: list failed: {exc}"

        if not summaries:
            return (
                "audit-branches: no `autoresearch/iter-*` branches yet.\n"
                "(The trail starts populating on the next experiment-loop iteration.)"
            )

        # Most recent last in `for-each-ref` sort; show the tail.
        recent = list(summaries)[-10:]
        lines = [f"**Audit Branches** — showing {len(recent)} of {len(summaries)}:"]
        for s in reversed(recent):
            outcome = s.outcome or "(unknown)"
            subj = (s.commit_subject or "").strip()[:60]
            lines.append(
                f"  • `{s.branch_name}` — {outcome} — {s.commit_sha[:12]} — {subj}"
            )
        return "\n".join(lines)


    async def _cmd_experiment_finalize(self, chat_id: str, args: str) -> str:
        """Group keep iterations into reviewable branches (Sprint 02.08).

        Usage:
            /experiment_finalize [--mode files|topic] [--since YYYY-MM-DD]
                                 [--until YYYY-MM-DD] [--dry-run]

        Spawns ``scripts/finalize_experiments.py`` in the bridge runtime
        repo. Reads the resulting markdown report and posts a summary to
        Discord. Gated on ``experiment_finalize_enabled`` per
        ``BridgeConfig`` (Tier 3 + flag).
        """
        # Flag check: pull the live config so the operator gets a useful
        # message when the flag is off, instead of silently running.
        try:
            from bridge.config import load_config
            cfg = load_config()
            enabled = bool(getattr(cfg, "experiment_finalize_enabled", False))
        except Exception:  # pragma: no cover — defensive, config errors logged elsewhere
            enabled = False
        if not enabled:
            return (
                "/experiment_finalize is gated on "
                "`experiment_finalize_enabled` in `bridge.toml`. "
                "Set `[experiment_loop] finalize_enabled = true` and restart."
            )

        import shlex

        # NOTE(commands demote-split): see agent_dir comment above — one level
        # deeper, so add an extra `.parent`.
        repo_root = Path(__file__).resolve().parent.parent.parent
        script = repo_root / "scripts" / "finalize_experiments.py"
        if not script.exists():
            return f"finalize_experiments.py not found at {script}"

        # Forward operator args verbatim (split via shlex so quoted
        # tokens survive). The script validates flags itself.
        try:
            user_args = shlex.split(args) if args else []
        except ValueError as exc:
            return f"Could not parse args: {exc}"

        cmd = [sys.executable, str(script), *user_args]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(repo_root),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
        except asyncio.TimeoutError:
            return "/experiment_finalize timed out after 120s."
        except Exception as exc:  # pragma: no cover — defensive
            return f"/experiment_finalize failed to spawn: {exc}"

        out = stdout.decode(errors="replace") if stdout else ""
        err = stderr.decode(errors="replace") if stderr else ""
        if proc.returncode != 0:
            return (
                f"finalize_experiments exited {proc.returncode}.\n"
                f"```\n{(err or out)[-600:]}\n```"
            )

        # Discover the most recent finalize report under data_dir.
        data_dir = Path(getattr(self._db, "db_path", "")).parent
        if not data_dir.exists():
            data_dir = repo_root / "data"
        try:
            reports = sorted(data_dir.glob("experiments-finalize-*.md"))
        except OSError:
            reports = []
        latest = reports[-1] if reports else None

        # Parse a few summary fields out of the markdown header.
        summary_lines: list[str] = []
        if latest is not None:
            try:
                head = latest.read_text().splitlines()[:10]
                summary_lines = [line for line in head if line.startswith("- ")]
            except OSError:
                summary_lines = []

        body = ["**Experiment finalize complete**"]
        if summary_lines:
            body.extend(summary_lines)
        if latest is not None:
            body.append(f"Report: `{latest}`")
        if err.strip():
            body.append(f"_(stderr trimmed)_:\n```\n{err.strip()[-300:]}\n```")
        return "\n".join(body)

    async def _cmd_experiment_finalize_status(self, chat_id: str, args: str) -> str:
        """List existing experiment-finalize branches and the last report.

        Usage:
            /experiment_finalize_status

        Walks ``git for-each-ref`` for branches starting with
        ``experiment-finalize/`` and shows the most recent finalize
        markdown report. Read-only.
        """
        import subprocess as _subproc  # local alias — keep top imports lean

        # NOTE(commands demote-split): see agent_dir comment above — one level
        # deeper, so add an extra `.parent`.
        repo_root = Path(__file__).resolve().parent.parent.parent
        try:
            proc = _subproc.run(
                [
                    "git", "for-each-ref",
                    "--format=%(refname:short)\t%(objectname:short)",
                    "refs/heads/experiment-finalize/",
                ],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=10.0,
                check=False,
            )
        except Exception as exc:  # pragma: no cover — defensive
            return f"git for-each-ref failed: {exc}"

        branches = [
            line.strip() for line in (proc.stdout or "").splitlines() if line.strip()
        ]
        lines = [f"**Experiment-finalize branches** — {len(branches)}"]
        if not branches:
            lines.append("_(none)_")
        else:
            for entry in branches[:30]:
                parts = entry.split("\t")
                name = parts[0] if parts else entry
                sha = parts[1] if len(parts) > 1 else ""
                marker = " (CONFLICT)" if "/CONFLICT-" in name else ""
                lines.append(f"- `{name}` `{sha}`{marker}")
            if len(branches) > 30:
                lines.append(f"_(…and {len(branches) - 30} more)_")

        # Append the most recent report path so the operator can
        # `gh attach` or open it directly.
        data_dir = Path(getattr(self._db, "db_path", "")).parent
        if not data_dir.exists():
            data_dir = repo_root / "data"
        try:
            reports = sorted(data_dir.glob("experiments-finalize-*.md"))
        except OSError:
            reports = []
        if reports:
            lines.append("")
            lines.append(f"Latest report: `{reports[-1]}`")
        return "\n".join(lines)


