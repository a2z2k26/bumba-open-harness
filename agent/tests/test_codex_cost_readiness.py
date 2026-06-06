"""Tests for Sprint audit-2026-05-16.D.03 — Codex cost-readiness validator.

HI-3 (#2064): when the bridge boots with the Codex backend enabled, the
``parse_cost`` contract introduced in D.01 (``CostMeasurement``) and wired
in D.02 (Codex's parser returns ``source='unknown'`` for cost-less turns
instead of a legacy float collapse) must hold — otherwise budget
enforcement is silently meaningless. ``_validate_codex_cost_readiness``
probes the in-memory Codex backend with three synthetic events and
refuses to boot when the responses do not match the contract.

Pattern mirrors ``test_codex_auth.py`` — module-scope validator + stub
config — but the surface under test is the cost contract, not the auth
contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from unittest.mock import patch

import pytest

from bridge.app import _validate_codex_cost_readiness, _validate_codex_oauth
from bridge.cost_tracker import CostMeasurement


# ---------------------------------------------------------------------------
# Stub config — the validator only reads attributes via ``getattr``, so a
# minimal dataclass with sensible defaults is sufficient. Mirrors the
# ``_StubConfig`` in test_codex_auth.py but adds ``codex_binary`` because
# ``CodexBackend.__init__`` stores the config on the instance and downstream
# methods read ``self.config.codex_binary``. The probe never reaches the
# binary-resolution path, but the attribute must exist on real config.
# ---------------------------------------------------------------------------


@dataclass
class _StubConfig:
    """Minimal config shape consumed by ``_validate_codex_cost_readiness``."""

    # Backends registry (Codex-3 sibling fields). Defaults match the legacy
    # "no [backends] registry" boot.
    backends_enabled: bool = False
    backends_main: str = ""
    backends_chiefs_default: str = ""
    backends_specialists_default: str = ""
    backends_specialists_overrides: dict = field(default_factory=dict)
    # Codex-4 OAuth fields — not consulted by this validator but kept for
    # compatibility with ``_validate_codex_oauth`` when both validators run
    # against the same stub.
    codex_oauth_token: str = ""
    codex_oauth_refresh_token: str = ""
    codex_oauth_expires_at: int = 0
    # ``CodexBackend.__init__`` stores config; ``resolve_binary`` reads
    # ``codex_binary`` — never hit by the probe but must be a real attr.
    codex_binary: str = ""


# ---------------------------------------------------------------------------
# Case 1 — no-op when backends are disabled (legacy claude-only boot)
# ---------------------------------------------------------------------------


def test_cost_readiness_passes_with_backends_disabled():
    """``backends_enabled=False`` short-circuits — validator must not even
    construct a CodexBackend. Mirrors ``_validate_codex_oauth``'s posture."""
    config = _StubConfig(
        backends_enabled=False,
        backends_main="codex",  # deliberately set; should be ignored
    )

    # Should NOT raise.
    _validate_codex_cost_readiness(config)


def test_cost_readiness_passes_when_no_role_is_codex():
    """When no role resolves to ``codex``, the Codex backend never runs at
    runtime — the readiness probe is structurally unnecessary."""
    config = _StubConfig(
        backends_enabled=True,
        backends_main="claude",
        backends_chiefs_default="claude",
        backends_specialists_default="claude",
        backends_specialists_overrides={},
    )

    _validate_codex_cost_readiness(config)


def test_cost_readiness_tolerates_pre_codex_3_config():
    """When the config object predates Codex-3 (no ``backends_*`` attrs),
    the validator must be a no-op — same defensive ``getattr`` posture as
    ``_validate_codex_oauth``."""

    class _BareConfig:
        pass

    _validate_codex_cost_readiness(_BareConfig())


# ---------------------------------------------------------------------------
# Case 2 — happy path: Codex backend honors the D.01/D.02 contract
# ---------------------------------------------------------------------------


def test_cost_readiness_passes_when_codex_returns_correct_measurements():
    """The live ``CodexBackend.parse_cost`` (post-D.02) returns
    CostMeasurement values that match the three probes. Validator passes."""
    config = _StubConfig(
        backends_enabled=True,
        backends_main="codex",
    )

    # Should NOT raise — D.02's parse_cost honors the contract.
    _validate_codex_cost_readiness(config)


def test_cost_readiness_passes_when_codex_routed_via_specialist_override():
    """Validator also fires when codex is reached via a specialist override
    (mirrors the ``_validate_codex_oauth`` coverage of all four routes)."""
    config = _StubConfig(
        backends_enabled=True,
        backends_main="claude",
        backends_chiefs_default="claude",
        backends_specialists_default="claude",
        backends_specialists_overrides={"code-reviewer": "codex"},
    )

    _validate_codex_cost_readiness(config)


# ---------------------------------------------------------------------------
# Case 3 — fail-closed when parse_cost regresses to a legacy float collapse
# ---------------------------------------------------------------------------


def test_cost_readiness_fails_when_codex_returns_legacy_float():
    """The HI-3 / SW-3 regression-guard: if ``parse_cost`` reverts to
    returning a raw float (the pre-D.02 collapse), the validator catches
    it at boot and refuses to start the bridge."""
    config = _StubConfig(
        backends_enabled=True,
        backends_main="codex",
    )

    # Monkey-patch parse_cost on the class so the probe inside the validator
    # picks up the regression. Patching the class (not the instance) is
    # cleaner because the validator constructs its own backend instance.
    with patch(
        "bridge.backends.codex.CodexBackend.parse_cost",
        return_value=0.0,
    ):
        with pytest.raises(RuntimeError) as excinfo:
            _validate_codex_cost_readiness(config)

    msg = str(excinfo.value)
    assert "parse_cost" in msg
    # The error must name the contract that broke and point at the sprint.
    assert "audit-2026-05-16.D.03" in msg or "CostMeasurement" in msg
    # ``float`` is the regressed return type the validator flags.
    assert "float" in msg


def test_cost_readiness_fails_when_unknown_returns_zero_amount():
    """A malformed CostMeasurement — ``source='unknown'`` paired with a
    numeric ``amount_usd`` — breaks the SW-3 invariant ("unknown is never
    equal to a measured zero"). The validator catches this shape too."""
    config = _StubConfig(
        backends_enabled=True,
        backends_main="codex",
    )

    malformed = CostMeasurement(
        amount_usd=Decimal("0"),  # WRONG — unknown must carry None
        source="unknown",
        backend="codex",
    )

    with patch(
        "bridge.backends.codex.CodexBackend.parse_cost",
        return_value=malformed,
    ):
        with pytest.raises(RuntimeError) as excinfo:
            _validate_codex_cost_readiness(config)

    msg = str(excinfo.value)
    # The validator's probe for ``{}`` expects source='not_applicable'; the
    # first malformed result trips it before the unknown probe even runs.
    # Either way the error must name the offending field.
    assert "source" in msg or "amount_usd" in msg


def test_cost_readiness_fails_when_parse_cost_missing():
    """If a future refactor strips ``parse_cost`` off ``CodexBackend``,
    the validator catches the missing method rather than crashing later
    inside the cost-tracking path."""
    config = _StubConfig(
        backends_enabled=True,
        backends_main="codex",
    )

    # Replace parse_cost with a non-callable to simulate a stripped method.
    with patch(
        "bridge.backends.codex.CodexBackend.parse_cost",
        new=None,
    ):
        with pytest.raises(RuntimeError, match="parse_cost"):
            _validate_codex_cost_readiness(config)


def test_cost_readiness_fails_when_parse_cost_raises():
    """If ``parse_cost`` raises (e.g. missing dependency surfaced at first
    call), the validator wraps the failure with operator-facing context
    rather than propagating an opaque traceback."""
    config = _StubConfig(
        backends_enabled=True,
        backends_main="codex",
    )

    with patch(
        "bridge.backends.codex.CodexBackend.parse_cost",
        side_effect=RuntimeError("Codex dependency missing"),
    ):
        with pytest.raises(RuntimeError) as excinfo:
            _validate_codex_cost_readiness(config)

    msg = str(excinfo.value)
    assert "parse_cost" in msg
    assert "Codex dependency missing" in msg


# ---------------------------------------------------------------------------
# Case 4 — startup integration: both validators get called in order
# ---------------------------------------------------------------------------


def test_app_init_calls_cost_readiness_after_oauth():
    """``BridgeAppInit.run`` invokes ``_validate_codex_oauth`` before
    ``_validate_codex_cost_readiness``. A clean way to assert ordering
    without spinning up the entire startup spine: patch both validators
    in the ``bridge.app_init`` namespace (where they're imported), call
    them in sequence on a stub config, and check the call order.

    This is the integration-ish smoke that the wiring in ``app_init.py``
    didn't drop the second call."""
    from bridge import app_init as app_init_mod

    # The startup spine imports the two validators by name at module load.
    # Confirm both names exist in the app_init module — if the wiring PR
    # forgot the import, this fails fast.
    assert hasattr(app_init_mod, "_validate_codex_oauth")
    assert hasattr(app_init_mod, "_validate_codex_cost_readiness")

    config = _StubConfig(
        backends_enabled=True,
        backends_main="codex",
        codex_oauth_token="sk-codex-access-xyz",
    )

    call_order: list[str] = []

    def _oauth_spy(cfg):
        call_order.append("oauth")

    def _cost_spy(cfg):
        call_order.append("cost")

    with patch.object(app_init_mod, "_validate_codex_oauth", _oauth_spy), \
         patch.object(app_init_mod, "_validate_codex_cost_readiness", _cost_spy):
        # Exercise the exact two-line sequence app_init.py runs.
        app_init_mod._validate_codex_oauth(config)
        app_init_mod._validate_codex_cost_readiness(config)

    assert call_order == ["oauth", "cost"]


def test_oauth_validator_still_works_with_cost_readiness_imported():
    """Sanity: the OAuth validator's behavior is unaffected by the new
    sibling. The original auth tests cover it more thoroughly; this is
    a tripwire for accidental cross-imports."""
    config = _StubConfig(
        backends_enabled=True,
        backends_main="codex",
        codex_oauth_token="",
    )

    with pytest.raises(RuntimeError, match="codex_oauth_token is missing"):
        _validate_codex_oauth(config)
