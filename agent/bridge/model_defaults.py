"""Canonical default-model + backend constants (P0.04).

Single source of truth for the model identifiers and backend name that were
previously hardcoded as bare string literals across config.py,
model_assignments.py, token_cost.py, the OpenRouter client/adapter, the VAPI
voice path, model_router.py, lifecycle_manager.py, peer_registration.py, and
commands.py.

The model-agnostic workstream (Phase 2) redirects each of those call sites to
the constants below so a backend/model change is a one-line edit here rather
than a grep-and-replace across the tree.

**No behaviour change on introduction** — every value is the literal that was
already in place at the call site. Bumping a value here is a deliberate,
test-documented act (see ``tests/test_model_defaults.py``).

Foundation note: the Phase 2 sprint specs attributed this module to P0.01,
but P0.01's real scope was stream-parsing delegation. The module was missing
from the plan; P0.04 fills the gap so the de-hardcode sprints have a target.
"""

from __future__ import annotations

# --- Backend selection -----------------------------------------------------
# The default execution backend when config/TOML does not specify one.
DEFAULT_BACKEND_NAME: str = "claude"

# --- Cross-vendor / fallback models ----------------------------------------
# OpenRouter model id used as the fallback-chain default and the
# ``fallback.openrouter_model`` config default.
DEFAULT_OPENROUTER_MODEL: str = "anthropic/claude-3.5-sonnet"

# --- Paid / domain-routing model -------------------------------------------
# The general-purpose paid model: ``DOMAIN_ASSIGNMENTS[Domain.GENERAL]`` and the
# ``get_model`` fallback in model_assignments.py, plus the engineering work-order
# route in commands.py and the lifecycle WorkOrder assignment default.
DEFAULT_PAID_MODEL: str = "claude-sonnet-4-6"

# --- Cost / pricing model --------------------------------------------------
# The model whose token pricing is the default for ``can_afford`` budget checks.
DEFAULT_PRICING_MODEL: str = "claude-opus-4-6"

# --- Voice (VAPI) model ----------------------------------------------------
# The model the VAPI squad assistants are provisioned with.
DEFAULT_VOICE_MODEL: str = "claude-sonnet-4-5"

# --- Operator-mode model overrides -----------------------------------------
# The Opus pin used by the ``/careful`` hook override in model_router.py.
DEFAULT_CAREFUL_MODEL: str = "claude-opus-4-5-20251001"

# The model a peer registers itself with by default (BUMBA_MODEL env fallback).
DEFAULT_REGISTRATION_MODEL: str = "claude-opus-4-6"

# --- Routing-tier model ids -------------------------------------------------
# The ModelRouter.TIERS entries — coarse model families used when not on a
# subscription. These are family names, not pinned versions, by design.
DEFAULT_TIER_SIMPLE: str = "claude-haiku"
DEFAULT_TIER_MEDIUM: str = "claude-sonnet"
DEFAULT_TIER_COMPLEX: str = "claude-opus"
