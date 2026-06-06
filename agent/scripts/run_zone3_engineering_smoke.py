"""Z3-06 — Zone 3 engineering smoke matrix.

Lets the operator test the engineering team separately from Zone 4 and verify
that cross-zone escalations are explicit. Default mode uses a FAKE executor so
local CI never spawns real Claude. ``--live`` intentionally uses the real
``claude -p`` executor.

Usage:
    python -m scripts.run_zone3_engineering_smoke          # fake executor
    python -m scripts.run_zone3_engineering_smoke --live   # real claude -p

Exits nonzero if any required smoke case fails. Prints manifest paths for
successful live runs.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from zone3.claude_p_executor import EngineeringRunResult, run_claude_p_specialist
from zone3.engineering_config import load_engineering_team_config
from zone3.engineering_dispatcher import EngineeringDispatcher


# (case_name, prompt) — mirrors docs/operator/zone3-engineering-smoke-matrix.md
SMOKE_CASES: tuple[tuple[str, str], ...] = (
    ("readiness", "ready to work?"),
    ("code_review", "review the latest diff"),
    ("backend_design", "sketch the safest API boundary for team artifacts"),
    ("qa_escalation", "verify this needs broader QA coverage"),
    ("ops_escalation", "prepare deploy risk notes for production infra"),
)


@dataclass(frozen=True)
class SmokeOutcome:
    case_name: str
    prompt: str
    passed: bool
    specialist: str
    stdout: str


class FakeEngineeringExecutor:
    """Records calls; returns canned success. Never spawns Claude."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def run(
        self,
        *,
        specialist: str,
        prompt: str,
        cwd: Path,
        timeout_seconds: int,
    ) -> EngineeringRunResult:
        self.calls.append({"specialist": specialist, "prompt": prompt})
        return EngineeringRunResult(
            specialist=specialist,
            success=True,
            stdout=f"[fake] {specialist} would run",
            stderr="",
            exit_code=0,
            duration_seconds=0.0,
        )


class LiveClaudePExecutor:
    """Real ``claude -p`` executor adapter for ``--live`` runs only."""

    def __init__(self, *, claude_binary: str = "claude") -> None:
        self._binary = claude_binary

    async def run(
        self,
        *,
        specialist: str,
        prompt: str,
        cwd: Path,
        timeout_seconds: int,
    ) -> EngineeringRunResult:
        return await run_claude_p_specialist(
            claude_binary=self._binary,
            specialist=specialist,
            prompt=prompt,
            cwd=str(cwd),
            timeout_seconds=timeout_seconds,
        )


def build_smoke_dispatcher(*, executor=None) -> EngineeringDispatcher:
    """Build a dispatcher for the smoke run (fake executor by default)."""
    return EngineeringDispatcher(
        config=load_engineering_team_config(),
        executor=executor or FakeEngineeringExecutor(),
    )


def _evaluate(case_name: str, result: EngineeringRunResult) -> bool:
    """Per-case pass criteria — independent of fake/live executor."""
    if not result.success:
        return False
    text = result.stdout.lower()
    if case_name == "readiness":
        return "engineering-chief" in result.stdout and "zone 3" in text
    if case_name in ("qa_escalation", "ops_escalation"):
        dept = "qa" if case_name == "qa_escalation" else "ops"
        return "handoff" in text and dept in text
    # Substantive cases pass on a successful executor run.
    return True


async def run_engineering_smoke(
    dispatcher: EngineeringDispatcher,
    *,
    cwd: Path,
) -> list[SmokeOutcome]:
    outcomes: list[SmokeOutcome] = []
    for case_name, prompt in SMOKE_CASES:
        result = await dispatcher.route(prompt, cwd=cwd)
        outcomes.append(
            SmokeOutcome(
                case_name=case_name,
                prompt=prompt,
                passed=_evaluate(case_name, result),
                specialist=result.specialist,
                stdout=result.stdout,
            )
        )
    return outcomes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use the real claude -p executor instead of the fake one.",
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=Path.cwd(),
        help="Working directory for engineering runs.",
    )
    args = parser.parse_args(argv)

    executor = LiveClaudePExecutor() if args.live else FakeEngineeringExecutor()
    dispatcher = build_smoke_dispatcher(executor=executor)
    outcomes = asyncio.run(run_engineering_smoke(dispatcher, cwd=args.cwd))

    failed = [o for o in outcomes if not o.passed]
    for outcome in outcomes:
        marker = "PASS" if outcome.passed else "FAIL"
        sys.stdout.write(
            f"[{marker}] {outcome.case_name}: {outcome.specialist}\n"
        )
    if args.live:
        sys.stdout.write("(live run — see artifact manifests for full output)\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
