"""Tests for agent/scripts/check_service_inventory_drift.py — Sprint F.03 (issue #2076).

These tests exercise the drift checker by feeding it synthetic authoritative
and secondary maps, plus one live-repo test that asserts the current state is
clean (so future drift fails CI fast).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CHECKER_PATH = REPO_ROOT / "agent" / "scripts" / "check_service_inventory_drift.py"


def _load_checker_module():
    """Import the checker as a module without going through site-packages."""
    spec = importlib.util.spec_from_file_location(
        "check_service_inventory_drift", CHECKER_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_checker_passes_on_aligned_inventory() -> None:
    """No drift when all four secondary surfaces match SERVICE_MAP exactly."""
    mod = _load_checker_module()
    authoritative = {
        "alpha": ("pkg.alpha", "AlphaService"),
        "beta": ("pkg.beta", "BetaService"),
    }
    secondary = {
        "SERVICE_NARRATIONS": {"alpha", "beta"},
        "SERVICE_SCHEDULES": {"alpha", "beta"},
        "SERVICE_TIMEOUTS": {"alpha", "beta"},
    }
    # Plist labels with underscore→hyphen conversion ("alpha" → "alpha", "beta" → "beta")
    plist_labels = {"alpha", "beta"}
    errors = mod.check_drift(authoritative, secondary, plist_labels)
    assert errors == [], f"expected no drift, got: {errors}"


def test_checker_fails_on_seeded_missing_service() -> None:
    """Drop one service from SERVICE_NARRATIONS — checker must flag it."""
    mod = _load_checker_module()
    authoritative = {
        "alpha": ("pkg.alpha", "AlphaService"),
        "beta": ("pkg.beta", "BetaService"),
    }
    secondary = {
        "SERVICE_NARRATIONS": {"alpha"},  # missing 'beta'
        "SERVICE_SCHEDULES": {"alpha", "beta"},
        "SERVICE_TIMEOUTS": {"alpha", "beta"},
    }
    plist_labels = {"alpha", "beta"}
    errors = mod.check_drift(authoritative, secondary, plist_labels)
    assert len(errors) == 1, f"expected exactly 1 error, got {len(errors)}: {errors}"
    assert "SERVICE_NARRATIONS" in errors[0]
    assert "'beta'" in errors[0]
    assert "missing" in errors[0]


def test_checker_fails_on_seeded_extra_service() -> None:
    """Add a key to SERVICE_TIMEOUTS that's not in SERVICE_MAP — checker must flag it."""
    mod = _load_checker_module()
    authoritative = {"alpha": ("pkg.alpha", "AlphaService")}
    secondary = {
        "SERVICE_NARRATIONS": {"alpha"},
        "SERVICE_SCHEDULES": {"alpha"},
        "SERVICE_TIMEOUTS": {"alpha", "ghost_service"},  # ghost_service is drift
    }
    plist_labels = {"alpha"}
    errors = mod.check_drift(authoritative, secondary, plist_labels)
    assert any(
        "ghost_service" in err and "extra" in err and "SERVICE_TIMEOUTS" in err
        for err in errors
    ), f"expected extra-key error for ghost_service, got: {errors}"


def test_checker_fails_on_unaccounted_plist_label() -> None:
    """A plist label that's neither in SERVICE_MAP nor on the ON_DEMAND_PLISTS allowlist must flag."""
    mod = _load_checker_module()
    authoritative = {"alpha": ("pkg.alpha", "AlphaService")}
    secondary = {
        "SERVICE_NARRATIONS": {"alpha"},
        "SERVICE_SCHEDULES": {"alpha"},
        "SERVICE_TIMEOUTS": {"alpha"},
    }
    # 'mystery' is not in SERVICE_MAP and not on ON_DEMAND_PLISTS — drift.
    plist_labels = {"alpha", "mystery"}
    errors = mod.check_drift(authoritative, secondary, plist_labels)
    assert any(
        "mystery" in err and "plist" in err.lower() for err in errors
    ), f"expected unaccounted-plist error, got: {errors}"


def test_checker_passes_on_current_repo_state() -> None:
    """Live test: the actual repo state must currently be drift-free.

    This is the load-bearing assertion. If a future PR adds a service to
    SERVICE_MAP and forgets to add a SERVICE_NARRATIONS entry, this test
    fails on the same PR — which is the whole point.
    """
    result = subprocess.run(
        [sys.executable, str(CHECKER_PATH), "--quiet"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"live-repo drift detected (exit {result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
