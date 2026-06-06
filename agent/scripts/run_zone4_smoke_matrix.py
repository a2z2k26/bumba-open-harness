"""Local Zone 4 end-to-end smoke matrix runner + release gate (Z4-22 #2448).

Drives :func:`teams._smoke_matrix.run_smoke_matrix` against the **real**
production department registry (loaded from ``agent/config/teams/*.yaml``),
fully offline:

- readiness legs hit the deterministic ``render_readiness`` path (zero
  provider requests);
- substantive legs drive a real ``DepartmentTeam.run`` with deterministic
  models against a temp ``artifact_root``, capturing a real manifest +
  telemetry — no live API call.

This is the local release gate. It does NOT call OpenRouter or Anthropic:
46/52 Zone 4 seats are on a dead OpenRouter key (2026-05-21), so a live
matrix would mostly fail until the provider cutover. Live-smoke
instructions are operator-gated and documented in
``docs/operator/zone4-smoke-matrix.md``.

Usage
-----
::

    cd agent
    .venv/bin/python scripts/run_zone4_smoke_matrix.py
    .venv/bin/python scripts/run_zone4_smoke_matrix.py --json
    .venv/bin/python scripts/run_zone4_smoke_matrix.py --teams-dir config/teams

Exit codes
----------
- ``0`` — gate passed (every non-expected-fail case ok).
- ``1`` — gate failed (at least one required case failed).
- ``2`` — internal harness error (registry load failed, import error).
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import tempfile
from pathlib import Path


def _default_teams_dir() -> Path:
    """Resolve the production teams dir relative to this script."""
    # scripts/ -> agent/ -> agent/config/teams
    agent_root = Path(__file__).resolve().parent.parent
    return agent_root / "config" / "teams"


async def _run(teams_dir: Path, artifact_root: Path):
    from teams._registry import DepartmentRegistry
    from teams._smoke_matrix import run_smoke_matrix

    registry = DepartmentRegistry.from_directory(teams_dir)
    return await run_smoke_matrix(registry, artifact_root=artifact_root)


def render_text(result) -> str:
    lines = [
        "Zone 4 smoke matrix (offline)",
        f"  gate_ok:     {result.gate_ok}",
        f"  cases:       {len(result.cases)}",
        f"  passed:      {sum(1 for c in result.cases if c.ok)}",
        f"  failed:      {sum(1 for c in result.cases if not c.ok)}",
        "",
    ]
    for case in result.cases:
        mark = "ok" if case.ok else ("xfail" if case.expected_fail else "FAIL")
        extra = []
        if case.leg == "substantive" and case.manifest_path:
            extra.append(f"manifest={case.manifest_path}")
        if case.leg == "substantive":
            extra.append(f"telemetry={'yes' if case.telemetry_captured else 'no'}")
        if case.failure_class:
            extra.append(f"class={case.failure_class}")
        if case.error:
            extra.append(f"error={case.error}")
        suffix = ("  " + " ".join(extra)) if extra else ""
        lines.append(
            f"  [{mark:<5}] {case.department:<12} {case.leg:<12}{suffix}"
        )
    return "\n".join(lines) + "\n"


def render_json(result) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the offline Zone 4 smoke matrix and emit a release-gate "
            "verdict. Readiness legs spend zero provider requests; "
            "substantive legs capture a manifest + telemetry via "
            "deterministic models. No live API call."
        )
    )
    parser.add_argument(
        "--teams-dir",
        default=None,
        help="Department YAML directory (default: agent/config/teams).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON summary instead of human-readable text.",
    )
    args = parser.parse_args(argv)

    teams_dir = (
        Path(args.teams_dir).expanduser()
        if args.teams_dir
        else _default_teams_dir()
    )

    try:
        with tempfile.TemporaryDirectory(prefix="z4-smoke-matrix-") as tmp:
            result = asyncio.run(_run(teams_dir, Path(tmp)))
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(
            f"run_zone4_smoke_matrix: internal harness error: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2

    if args.json:
        sys.stdout.write(render_json(result))
    else:
        sys.stdout.write(render_text(result))

    return 0 if result.gate_ok else 1


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        sys.exit(main())
