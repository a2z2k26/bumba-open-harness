"""Live-smoke harness for Zone 4 departments (sprint B2.4).

Opt-in, cost-capped, CI-skipped. Fires one real Anthropic API call per
department, asserts all 7 verification gates pass, asserts cost within cap.

Invoke with:
    uv run pytest tests/test_teams/test_live_smoke.py -v -m live

Requires:
    - ANTHROPIC_API_KEY env var
    - (Optional) LIVE_COST_CAP=0.75 to override per-run cost ceiling

Cost budget: ~$0.05-0.15 per department per run with haiku.
Full sweep (5 depts): typically < $0.50.

These tests are intentionally @pytest.mark.live gated and are skipped in CI.
They exist for:
  - pre-flag-flip validation (before enabling a new department in production)
  - pre-deploy sanity checks after changes to department YAML or tools
  - on-demand verification after prompt or model changes
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from teams._config import load_department_config
from teams._team import DepartmentTeam
from teams._verify import verify_team_result
from teams._types import BridgeDeps
from tests.test_teams.conftest import make_deps

# Locate the config directory relative to this file
_AGENT_ROOT = Path(__file__).parent.parent.parent
_CONFIG_DIR = _AGENT_ROOT / "config" / "teams"

# Soft per-test token ceiling (Anthropic haiku is very cheap; this is a safety net)
_SOFT_TOKEN_CEILING = 4000

# Simple smoke prompt that exercises manager → specialist delegation
_SMOKE_PROMPT = (
    "Give a one-sentence summary of your primary responsibility as a department. "
    "Be concise."
)


def _make_live_deps(department: str) -> BridgeDeps:
    """Build a BridgeDeps suitable for live tests (real API, no real bridge)."""
    return make_deps(
        session_id="live-smoke",
        department=department,
    )


def _discover_configs() -> list[Path]:
    """Return all department YAML config paths, sorted by name."""
    if not _CONFIG_DIR.exists():
        return []
    return sorted(_CONFIG_DIR.glob("*.yaml"))


def _department_uses_openrouter(config_path: Path) -> bool:
    """Lightweight YAML scan — True if any chief or worker model: line
    starts with 'openrouter:'. Used by ``test_live_smoke_department`` to
    short-circuit with an informative skip when OPENROUTER_API_KEY is absent.
    """
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return "model: openrouter:" in text or "model: \"openrouter:" in text


@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config_path",
    _discover_configs(),
    ids=lambda p: p.stem,
)
async def test_live_smoke_department(config_path: Path) -> None:
    """Live-smoke a single department: one real API call, all 7 gates must pass.

    Skipped automatically when ANTHROPIC_API_KEY is not set. Departments that
    declare ``model: openrouter:*`` also skip when OPENROUTER_API_KEY is
    absent (Sprint 04.07 / #1961 — prefix-based routing means an openrouter:*
    model string MUST hit OpenRouter; running the smoke without the key
    surfaces a 401 that is environmental, not a real test failure).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set — skipping live tests")

    if _department_uses_openrouter(config_path):
        openrouter_key = os.environ.get("OPENROUTER_API_KEY")
        if not openrouter_key:
            pytest.skip(
                f"OPENROUTER_API_KEY not set — {config_path.stem} uses "
                "openrouter:* model strings (Sprint 04.07/#1961)"
            )

    live_cost_cap = float(os.environ.get("LIVE_COST_CAP", "0.50"))

    # Load config
    config = load_department_config(config_path)

    # Build the team (uses real model names from YAML)
    team = DepartmentTeam(config, lazy_build=False)
    deps = _make_live_deps(config.name)

    # Run one smoke task
    result = await team.run(_SMOKE_PROMPT, deps=deps)

    # --- Assertions ---

    # 1. The run must succeed
    assert result.department == config.name, (
        f"department mismatch: expected {config.name!r}, got {result.department!r}"
    )

    # 2. All 7 verification gates must pass
    violations = verify_team_result(result, config)
    assert violations == [], (
        f"Department {config.name!r} failed verification gates:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )

    # 3. Cost must be within the per-test cap
    assert result.total_cost_usd <= live_cost_cap, (
        f"Department {config.name!r} cost ${result.total_cost_usd:.4f} "
        f"exceeds live cap ${live_cost_cap:.2f}"
    )

    # 4. Token count sanity check (catches runaway loops)
    assert result.total_tokens <= _SOFT_TOKEN_CEILING, (
        f"Department {config.name!r} used {result.total_tokens} tokens, "
        f"exceeding soft ceiling {_SOFT_TOKEN_CEILING}"
    )


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_smoke_no_configs_is_not_an_error() -> None:
    """If no department YAML configs exist yet, the smoke suite should pass vacuously."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set — skipping live tests")
    configs = _discover_configs()
    if not configs:
        pytest.skip("No department YAML configs found — nothing to smoke-test")
    # At least one config exists: the parametrized tests above cover them.
    assert len(configs) >= 1
