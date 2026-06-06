"""Drift test: the remaining single-liner model literals must source the
canonical constants from bridge.model_defaults (P0.01)."""
import inspect
from bridge import model_router as mr
from bridge.lifecycle_manager import WorkLifecycleManager
from bridge.peer_registration import RegistrationConfig
from bridge import commands as commands_mod
from bridge import model_defaults


def test_careful_override_sources_canonical():
    assert mr.CAREFUL_OPUS_MODEL == model_defaults.DEFAULT_CAREFUL_MODEL
    assert model_defaults.DEFAULT_CAREFUL_MODEL == "claude-opus-4-5-20251001"


def test_router_tiers_source_canonical():
    tiers = mr.ModelRouter.TIERS
    assert tiers["simple"]["model"] == model_defaults.DEFAULT_TIER_SIMPLE
    assert tiers["medium"]["model"] == model_defaults.DEFAULT_TIER_MEDIUM
    assert tiers["complex"]["model"] == model_defaults.DEFAULT_TIER_COMPLEX


def test_peer_registration_default_sources_canonical(monkeypatch):
    monkeypatch.delenv("BUMBA_MODEL", raising=False)
    cfg = RegistrationConfig.from_environment()
    assert cfg.model == model_defaults.DEFAULT_REGISTRATION_MODEL
    assert model_defaults.DEFAULT_REGISTRATION_MODEL == "claude-opus-4-6"


def test_lifecycle_assignment_model_sources_canonical():
    src = inspect.getsource(WorkLifecycleManager.assign)
    assert "model_defaults.DEFAULT_PAID_MODEL" in src
    assert '"claude-sonnet-4-6"' not in src


def test_commands_engineering_assignment_sources_canonical():
    # The /engineering route literal must be replaced by the canonical paid default.
    src = inspect.getsource(commands_mod)
    assert '"claude-sonnet-4-5"' not in src
    assert model_defaults.DEFAULT_PAID_MODEL == "claude-sonnet-4-6"
