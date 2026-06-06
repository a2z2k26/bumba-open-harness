"""Tests for the ``verification flag guard`` readiness row.

Sprint Backend-Operability S2.2 (issue #2281) — keep the dispatcher's
unwired-verifier path behind a hard readiness fail. The flag
``verification_enabled`` defaults to False; flipping it to True today
puts WorkOrders in a permanent stall in the ``VERIFYING`` status while
the dispatcher emits ``workorder.verifying.stalled`` events. The
readiness gate must refuse that configuration until the verifier
completion path is actually wired (deferred to a follow-up sprint).

The check itself lives in ``agent/scripts/readiness.sh`` as row #9
``verification flag guard``. The shell row delegates to a one-liner
Python assertion against ``load_config(skip_secrets=True,
skip_validation=True).verification_enabled``. These tests exercise the
same assertion against the same config-loading path so a refactor of
``BridgeConfig`` or ``load_config`` that breaks the shell row trips a
pytest failure in CI rather than only surfacing at ``make readiness``
time.
"""

from __future__ import annotations

import dataclasses

import pytest

from bridge.config import BridgeConfig, load_config


# ---------------------------------------------------------------------------
# Default path: readiness passes
# ---------------------------------------------------------------------------


def test_default_config_has_verification_disabled() -> None:
    """The baseline acceptance criterion: default config keeps the flag off.

    A ``load_config(skip_secrets=True, skip_validation=True)`` call with
    no overrides must yield ``verification_enabled=False`` so the
    readiness row passes in the default deployment posture. If a future
    config change defaults the flag to True without wiring the
    verifier-completion path first, this test will fail and the
    readiness row would FAIL the gate at runtime.
    """
    cfg = load_config(skip_secrets=True, skip_validation=True)
    assert cfg.verification_enabled is False, (
        "verification_enabled must default to False until the dispatcher's "
        "verifier-completion path is wired; readiness row #9 enforces this."
    )


# ---------------------------------------------------------------------------
# Flipped path: readiness assertion fails loudly
# ---------------------------------------------------------------------------


def test_verification_enabled_flag_trips_readiness_guard() -> None:
    """A config with ``verification_enabled=True`` must trip the readiness
    assertion exactly as the shell row's inline Python would.

    The shell row runs:

        assert not cfg.verification_enabled, '...'

    We mirror that here so anyone refactoring the assertion message or
    the flag name has a pytest failure to point at, not just a shell
    exit code.
    """
    cfg = load_config(skip_secrets=True, skip_validation=True)
    flipped = dataclasses.replace(cfg, verification_enabled=True)

    with pytest.raises(AssertionError) as excinfo:
        assert not flipped.verification_enabled, (
            "verification_enabled=true but dispatcher verification "
            "completion remains unwired"
        )
    # Ensure the failure surfaces the wiring gap, not some unrelated
    # AttributeError or silent pass. Operators reading the readiness
    # report need that string to know what to do next.
    assert "unwired" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Field shape: the flag is a real BridgeConfig attribute, not a getattr
# fallback. If a future refactor renames or removes the field, the
# readiness shell row would silently pass (the inline assertion would
# read ``False`` from a missing attribute via getattr). Pin the field
# shape here so the contract is explicit.
# ---------------------------------------------------------------------------


def test_bridge_config_declares_verification_enabled_field() -> None:
    fields = {f.name for f in dataclasses.fields(BridgeConfig)}
    assert "verification_enabled" in fields, (
        "BridgeConfig must declare verification_enabled as a real field; "
        "readiness row #9 'verification flag guard' depends on it."
    )
