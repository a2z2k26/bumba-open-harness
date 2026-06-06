#!/usr/bin/env python3
"""Codex-exec teams-path live smoke (#2566 canary proof).

Backend-agnostic complement to ``codex_e2e_smoke.py``. That script proves the
``CodexBackend`` (Discord / ``backends_enabled``) path; THIS script proves the
Zone 4 *teams* path — ``teams._factory._resolve_model`` → ``CodexExecModel`` →
``codex exec`` — by building a real department team from its YAML and firing
one live delegated run.

Runs with the **production venv** (stdlib + bridge deps only — NO pytest). The
department's required ``BridgeDeps`` subsystems are stubbed with
``unittest.mock`` (stdlib), mirroring ``tests/test_teams/conftest.py::make_deps``;
the model resolution + subprocess + parse path are exercised for real.

Usage::

    # From agent/, as the daemon user, with ANTHROPIC_API_KEY (+ OPENROUTER_API_KEY
    # if the department still has openrouter: seats) exported.
    .venv/bin/python scripts/codex_teams_smoke.py --department ops

Exit codes:
    0 — PASS (run succeeded, all verification gates passed)
    1 — FAIL (run errored or a gate failed)
    2 — pre-flight blocker (config missing / no codex-exec seat in the dept)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Resolve the agent/ package root so this runs from any cwd.
_AGENT_ROOT = Path(__file__).resolve().parent.parent
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from teams._config import load_department_config
from teams._team import DepartmentTeam
from teams._types import BridgeDeps
from teams._verify import verify_team_result

_CONFIG_DIR = _AGENT_ROOT / "config" / "teams"
_SMOKE_PROMPT = (
    "Give a one-sentence summary of your primary responsibility as a department. "
    "Be concise."
)
_CODEX_EXEC_PREFIX = "codex-exec:"


def _make_stub_deps(department: str) -> BridgeDeps:
    """BridgeDeps with stdlib-mock subsystems (mirror of conftest.make_deps)."""
    memory_store = AsyncMock()
    memory_store.get = AsyncMock(return_value=None)
    memory_store.set = AsyncMock(return_value=None)
    return BridgeDeps(
        session_id="codex-teams-smoke",
        department=department,
        operator_id="op-smoke",
        memory_store=memory_store,
        event_bus=MagicMock(),
        trust_manager=MagicMock(),
        cost_tracker=MagicMock(),
        knowledge_search=AsyncMock(return_value=[]),
        cost_limit_usd=2.0,
    )


def _department_has_codex_seat(config_path: Path) -> bool:
    """True if any seat in the YAML declares a ``codex-exec:`` model."""
    text = config_path.read_text()
    return _CODEX_EXEC_PREFIX in text


async def _run(department: str) -> int:
    config_path = _CONFIG_DIR / f"{department}.yaml"
    if not config_path.exists():
        print(json.dumps({"status": "BLOCKER", "error": f"no config at {config_path}"}))
        return 2
    if not _department_has_codex_seat(config_path):
        print(json.dumps({
            "status": "BLOCKER",
            "error": f"{department} has no codex-exec: seat — nothing to prove",
        }))
        return 2

    config = load_department_config(config_path)
    team = DepartmentTeam(config, lazy_build=False)
    deps = _make_stub_deps(config.name)

    result = await team.run(_SMOKE_PROMPT, deps=deps)
    violations = verify_team_result(result, config)

    summary = {
        "department": result.department,
        "gates_passed": violations == [],
        "violations": violations,
        "total_cost_usd": round(getattr(result, "total_cost_usd", 0.0), 4),
        "total_tokens": getattr(result, "total_tokens", 0),
        "status": "PASS" if (result.department == config.name and not violations) else "FAIL",
    }
    print(json.dumps(summary, indent=2))
    return 0 if summary["status"] == "PASS" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--department", default="ops", help="department YAML stem (default: ops)")
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.department))


if __name__ == "__main__":
    raise SystemExit(main())
