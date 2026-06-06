"""CLI entry point for the job_search agent.

Usage:
  python -m job_search                       # Run the full prepare pipeline
  python -m job_search execute               # Run the execute pipeline
  python -m job_search --test-url <url>      # Smoke-test a single URL
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stdout,
    )


async def _run_smoke_test(url: str) -> int:
    """Smoke-test a single URL. Returns exit code (0 = pass, 1 = blocked/fail)."""
    from .ats.applicant import smoke_test_url

    print(f"Smoke-testing: {url}")
    result = await smoke_test_url(url)

    if result.cloudflare_blocked:
        print(f"BLOCKED (Cloudflare): {result.notes[:300]}")
        return 1
    if result.success:
        print("OK — page loaded successfully")
        print(result.notes[:500])
        return 0
    else:
        print(f"FAIL: {result.notes[:300]}")
        return 1


def _is_team_enabled() -> bool:
    """Return True when job_search_team_enabled is set in BridgeConfig."""
    try:
        from pathlib import Path
        from bridge.config import load_config

        config_path = Path(__file__).parent.parent / "config" / "bridge.toml"
        if not config_path.exists():
            return False
        cfg = load_config(config_path, skip_secrets=True, skip_validation=True)
        return bool(cfg.job_search_team_enabled)
    except Exception:
        return False


async def _run_via_team(mode: str) -> str:
    """Delegate PREPARE / EXECUTE to the Zone 4 job-search-chief.

    Sprint D5.2 — delegation seam only. Specialists are stubs; full logic
    migration is D5.3+. Falls back to direct JobSearchAgent on any error.

    Sprint P5.3 (#1588) — routes through
    :func:`job_search.department.run_prepare` / ``run_execute`` instead of
    calling ``DepartmentRegistry.route`` directly. The department wrappers
    add ``asyncio.timeout`` protection (default 3600s, mirrors
    ``job_search.yaml constraints.timeout_seconds``) and publish typed
    ``job_search.{prepare,execute}.timeout`` events on hang — protections
    the previous direct ``registry.route`` call silently bypassed. This
    is the canonical CLI ↔ cron join point: both paths now resolve to
    the same ``department.run_{prepare,execute}`` function.
    """
    try:
        from teams._types import BridgeDeps
        from .department import run_execute, run_prepare

        session_id = f"jobsearch-cli-{mode}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        deps = await BridgeDeps.for_cron(
            department="job_search",
            session_id=session_id,
        )
        if mode == "execute":
            result = await run_execute(deps)
        else:
            result = await run_prepare(deps)
        return result.manager_output or f"job-search-chief completed {mode} (no output)"
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Zone 4 delegation failed (%s); falling back to direct path", exc
        )
        from .agent import JobSearchAgent

        agent = JobSearchAgent()
        if mode == "execute":
            return await agent.execute()
        return await agent.prepare()


def main() -> None:
    _setup_logging()

    parser = argparse.ArgumentParser(
        description="Bumba job-search agent CLI",
        prog="python -m job_search",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        default="prepare",
        choices=["prepare", "execute"],
        help="Pipeline mode (default: prepare)",
    )
    parser.add_argument(
        "--test-url",
        metavar="URL",
        help="Smoke-test a single job URL and exit",
    )

    args = parser.parse_args()

    # Halt gate (audit-2026-05-16.C.04, #2059) — operator's bridge halt
    # propagates to the direct CLI surface too. Without this check, an
    # operator who runs `/halt` to pause the daemon could still trigger
    # autonomous job-search work via `python -m job_search`. Exit 0 (not
    # non-zero) so scripted callers do not interpret halt as a noisy
    # failure — it is a deliberate operator state. Reason is printed to
    # stderr so log scrapers can grep it.
    from ._pipeline import _build_halt_policy

    halt_policy = _build_halt_policy()
    decision = halt_policy.check_start("job-search")
    if decision.blocked:
        print(f"blocked by halt: {decision.reason}", file=sys.stderr)
        sys.exit(0)

    if args.test_url:
        exit_code = asyncio.run(_run_smoke_test(args.test_url))
        sys.exit(exit_code)

    if _is_team_enabled():
        summary = asyncio.run(_run_via_team(args.mode))
    else:
        from .agent import JobSearchAgent

        agent = JobSearchAgent()
        if args.mode == "execute":
            summary = asyncio.run(agent.execute())
        else:
            summary = asyncio.run(agent.prepare())

    print(summary)


if __name__ == "__main__":
    main()
