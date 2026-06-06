"""Unit tests for bridge.executor_availability (audit-2026-05-16.F.02, #2075).

Audit finding **SW-4**: executor availability had duplicate operator
surfaces (``bridge.executors.availability_snapshot`` + dispatcher
``get_executor_statuses``) and an incomplete static snapshot — output
could drift from actual ``WORKTREE`` / ``SUBAGENT`` / ``E2B`` state.

These tests pin the new single-provider contract:

* Provider snapshot returns one entry per registered executor.
* The canonical known-executor set is locked behind a drift test so
  any future addition/removal forces an intentional change.
* The renderer (``status_render.format_executor_section``) is wired to
  the provider's snapshot, not to its own private map.
* The legacy ``bridge.executors.availability_snapshot()`` is now a thin
  facade over the provider — two consumers, one source.
"""

from __future__ import annotations

import pytest

from bridge.executor_availability import (
    ExecutorAvailabilityProvider,
    ExecutorStatus,
    default_provider,
    snapshot_as_legacy_dict,
)


# ---------------------------------------------------------------------------
# ExecutorStatus dataclass — frozen contract
# ---------------------------------------------------------------------------


def test_executor_status_is_frozen():
    """ExecutorStatus is immutable so callers can't mutate cached snapshots."""
    status = ExecutorStatus(name="WORKTREE", available=True, reason="")
    with pytest.raises(Exception):  # FrozenInstanceError subclasses Exception
        status.available = False  # type: ignore[misc]


def test_executor_status_default_reason_is_empty_string():
    """reason defaults to empty string when omitted."""
    status = ExecutorStatus(name="WORKTREE", available=True)
    assert status.reason == ""


# ---------------------------------------------------------------------------
# Provider snapshot — surface contract
# ---------------------------------------------------------------------------


def test_provider_snapshot_returns_all_known_executors():
    """A provider built from a fixture check-map returns one entry per name."""
    calls: list[str] = []

    def _make_check(name: str, available: bool, reason: str = "") -> callable:
        def _check() -> ExecutorStatus:
            calls.append(name)
            return ExecutorStatus(name=name, available=available, reason=reason)
        return _check

    provider = ExecutorAvailabilityProvider({
        "FOO": _make_check("FOO", True),
        "BAR": _make_check("BAR", False, "boom"),
        "BAZ": _make_check("BAZ", True),
    })
    snap = provider.snapshot()
    assert set(snap.keys()) == {"FOO", "BAR", "BAZ"}
    assert snap["FOO"].available is True
    assert snap["BAR"].available is False
    assert snap["BAR"].reason == "boom"
    # Each check was called exactly once during snapshot
    assert sorted(calls) == ["BAR", "BAZ", "FOO"]


def test_provider_snapshot_is_a_dict_of_executor_status():
    """Return type is dict[str, ExecutorStatus] — not raw strings."""
    snap = default_provider().snapshot()
    assert all(isinstance(v, ExecutorStatus) for v in snap.values())


def test_provider_constructor_defensive_copy():
    """Mutating the check map after construction must not affect the provider."""
    checks = {
        "WORKTREE": lambda: ExecutorStatus(name="WORKTREE", available=True),
    }
    provider = ExecutorAvailabilityProvider(checks)
    checks["INJECTED"] = lambda: ExecutorStatus(name="INJECTED", available=True)
    assert provider.known_executor_names == frozenset({"WORKTREE"})


# ---------------------------------------------------------------------------
# Drift test on the canonical set — audit SW-4
# ---------------------------------------------------------------------------


def test_known_executor_names_drift():
    """Pin the canonical executor availability set.

    Failing this test means a known executor was added/removed from the
    default provider without intentional acknowledgement. If the change
    IS intentional (e.g. TMUX or DEPARTMENT joins the availability
    surface), update this assertion in the same PR that changes the
    provider and document the rationale.
    """
    assert default_provider().known_executor_names == frozenset({
        "WORKTREE",
        "SUBAGENT",
        "E2B",
    })


# ---------------------------------------------------------------------------
# Legacy wire-format compatibility — preserves format_executor_section input
# ---------------------------------------------------------------------------


def test_snapshot_as_legacy_dict_preserves_wire_format():
    """Legacy form: available → "available", unavailable → reason string."""
    legacy = snapshot_as_legacy_dict()
    assert legacy["WORKTREE"] == "available"
    assert legacy["SUBAGENT"] == "available"
    # E2B operability landed (#416): the static surface reports the
    # config-gated default (it can't read runtime config); live routable
    # status is on /status --full.
    assert legacy["E2B"] == (
        "config-gated: set e2b_executor_enabled + e2b_api_key (see /status --full)"
    )


def test_snapshot_as_legacy_dict_accepts_custom_provider():
    """A test provider can be passed to render its snapshot in legacy form."""
    provider = ExecutorAvailabilityProvider({
        "FAKE": lambda: ExecutorStatus(name="FAKE", available=False, reason="test-only"),
    })
    legacy = snapshot_as_legacy_dict(provider)
    assert legacy == {"FAKE": "test-only"}


def test_snapshot_as_legacy_dict_unavailable_with_no_reason_falls_back():
    """An unavailable executor with empty reason renders the fallback token."""
    provider = ExecutorAvailabilityProvider({
        "BLANK": lambda: ExecutorStatus(name="BLANK", available=False, reason=""),
    })
    legacy = snapshot_as_legacy_dict(provider)
    assert legacy == {"BLANK": "unavailable"}


# ---------------------------------------------------------------------------
# Cross-consumer wiring — proves "one provider, two consumers"
# ---------------------------------------------------------------------------


def test_executors_availability_snapshot_delegates_to_provider(monkeypatch):
    """``bridge.executors.availability_snapshot`` reads from the provider.

    First consumer: the legacy executors-package facade. Mock the
    provider's snapshot and observe the legacy function's output —
    proves the facade isn't returning its own private dict anymore.
    """
    from bridge import executor_availability as ea
    from bridge.executors import availability_snapshot

    fake_provider = ExecutorAvailabilityProvider({
        "PROVIDER_WIRED": lambda: ExecutorStatus(
            name="PROVIDER_WIRED", available=True, reason=""
        ),
    })
    monkeypatch.setattr(ea, "default_provider", lambda: fake_provider)
    out = availability_snapshot()
    assert out == {"PROVIDER_WIRED": "available"}


def test_status_render_executor_section_consumes_provider_output():
    """``format_executor_section`` consumes provider-shaped dicts.

    Second consumer: the renderer. Render a section from a custom
    provider's legacy-rendered snapshot — proves the renderer is
    wired off the provider, not a parallel hard-coded source.
    """
    from bridge.status_render import format_executor_section

    custom_provider = ExecutorAvailabilityProvider({
        "ALPHA": lambda: ExecutorStatus(name="ALPHA", available=True),
        "BETA": lambda: ExecutorStatus(
            name="BETA", available=False, reason="custom-block-reason"
        ),
    })
    snapshot = snapshot_as_legacy_dict(custom_provider)
    lines = format_executor_section(snapshot)
    flat = "\n".join(lines)
    assert "Executors:" in flat
    assert "executor.ALPHA" in flat
    assert "executor.BETA" in flat
    assert "custom-block-reason" in flat
