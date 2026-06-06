"""Zone 4 model-allocation policy guardrails (Z4-17, issue #2443).

Z4-17's outcome — "migrate Zone 4 model allocation away from OpenRouter where
certified" — is **decision-complete on direction** (operator 2026-06-01: the
OpenRouter key is retired and the strategic target is Codex / ChatGPT-OAuth)
but **not buildable as a live YAML migration yet**: the PydanticAI Zone 4 path
has no certified Codex adapter and the OpenAI-API canary failed a live 401
(issue comments 2026-05-22). No autonomous migration may flip live provider
config without operator action.

This test file is the SAFE prep the sprint can land now. It does three things:

1. **Pins the allowed-prefix policy** for every Zone 4 team YAML, so a future
   migration changes models inside a known, tested envelope instead of
   inventing prefixes ad hoc.
2. **Asserts the producer↔consumer seam** between the two model-string readers:
   ``teams._usage_policy.classify_model_provider`` (the budget/telemetry side)
   and ``teams._factory._resolve_model`` (the construction side). Every prefix
   that appears in a real YAML MUST be routable by ``_resolve_model`` to a
   pydantic-ai ``Model`` instance — never left as a pass-through string that
   pydantic-ai then fails to resolve at run time.
3. **Guards the codex-exec gap.** ``classify_model_provider`` already knows
   ``codex-exec:`` (→ ``codex-cli``, 200K budget) and a live probe script
   exists, but ``_resolve_model`` has NO ``codex-exec:`` branch and
   ``ALLOWED_ADAPTERS`` does not include it. A team YAML migrated to
   ``codex-exec:*`` today would fall through to the raw-string path and crash.
   This test fails loudly if any YAML adopts ``codex-exec:`` before the
   factory grows a certified branch — the exact migration footgun #2443 must
   not step on.

The certified Codex adapter landed in Z4-17a (#2566): ``_resolve_model`` now has
a ``codex-exec:`` branch returning a ``CodexExecModel``, ``ALLOWED_ADAPTERS``
includes ``codex-exec``, and ``codex-exec:`` is in ``_ROUTABLE_PREFIXES`` /
``_ALLOWED_MODEL_PREFIXES`` below. The pre-adapter footgun-guard +
characterization tests were replaced by
``test_classify_and_resolve_agree_on_codex_exec_being_routed`` and the
construction/validation guards at the bottom of this file.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic_ai.models import Model

from teams._factory import _resolve_model
from teams._types import AgentSpec
from teams._usage_policy import classify_model_provider

_TEAMS_DIR = Path(__file__).parent.parent.parent / "config" / "teams"

# Prefixes a Zone 4 ``model:`` string is allowed to carry. Mirrors the four
# branches in ``teams._factory._resolve_model`` plus the bare-string
# anthropic/shortcut path (no prefix). ``codex-exec:`` is DELIBERATELY ABSENT —
# it is recognised by ``classify_model_provider`` for budgeting but is NOT yet
# routable by ``_resolve_model``. See module docstring.
_ALLOWED_MODEL_PREFIXES: tuple[str, ...] = (
    "openrouter:",
    "openai:",
    "anthropic-oauth:",
    "anthropic:",
    "codex-exec:",
)

# Bare model shortcuts that resolve via pydantic-ai's own path (no prefix).
_BARE_SHORTCUT_PREFIXES: tuple[str, ...] = (
    "claude-",
    "sonnet-",
    "opus-",
    "haiku-",
    "gpt-",
)

# Prefixes ``_resolve_model`` constructs a real pydantic-ai ``Model`` for.
# A YAML model carrying one of these must NOT come back as a pass-through str.
_ROUTABLE_PREFIXES: tuple[str, ...] = (
    "openrouter:",
    "openai:",
    "anthropic-oauth:",
    "codex-exec:",
)


def _real_team_yaml_paths() -> list[Path]:
    """Every department-team YAML, excluding the ``_template.yaml`` scaffold."""
    return [p for p in sorted(_TEAMS_DIR.glob("*.yaml")) if p.name != "_template.yaml"]


def _iter_zone4_member_models() -> list[tuple[str, str, str]]:
    """Yield ``(yaml_name, member_name, model)`` for every chief + worker.

    Members without a ``model:`` (e.g. the ``manager.model`` synthesis knob is
    read separately) are skipped — only agent specs carry the policy contract.
    """
    rows: list[tuple[str, str, str]] = []
    for path in _real_team_yaml_paths():
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        team = data["team"]
        members = [team["chief"], *(team.get("workers", []) or [])]
        for member in members:
            model = str(member.get("model", "")).strip()
            if model:
                rows.append((path.name, str(member.get("name")), model))
    return rows


_MEMBER_MODELS = _iter_zone4_member_models()


def test_zone4_yamls_exist_and_declare_models() -> None:
    """Sanity floor: the collector found real members across the 6 teams."""
    assert _MEMBER_MODELS, "no Zone 4 team members with a model: were collected"
    yaml_names = {row[0] for row in _MEMBER_MODELS}
    # The six live department YAMLs Z4-17 owns.
    assert yaml_names >= {
        "board.yaml",
        "design.yaml",
        "job_search.yaml",
        "ops.yaml",
        "qa.yaml",
        "strategy.yaml",
    }


@pytest.mark.parametrize(
    ("yaml_name", "member_name", "model"),
    _MEMBER_MODELS,
    ids=[f"{y}:{n}" for y, n, _ in _MEMBER_MODELS],
)
def test_every_zone4_model_prefix_is_known(
    yaml_name: str, member_name: str, model: str
) -> None:
    """Every Zone 4 model string uses an allowed prefix or a bare shortcut.

    This is the policy assertion the Z4-17 sprint sketch asked for, adapted to
    the prefixes ``_resolve_model`` actually supports today.
    """
    known = model.startswith(_ALLOWED_MODEL_PREFIXES) or model.startswith(
        _BARE_SHORTCUT_PREFIXES
    )
    assert known, (
        f"{yaml_name}: {member_name!r} declares model={model!r} with an "
        f"unrecognised prefix. Allowed: {_ALLOWED_MODEL_PREFIXES} or bare "
        f"shortcuts {_BARE_SHORTCUT_PREFIXES}. If this is a deliberate "
        f"provider migration, teach teams._factory._resolve_model the new "
        f"branch and add the prefix to _ALLOWED_MODEL_PREFIXES first."
    )


@pytest.mark.parametrize(
    ("yaml_name", "member_name", "model"),
    _MEMBER_MODELS,
    ids=[f"{y}:{n}" for y, n, _ in _MEMBER_MODELS],
)
def test_routable_prefixes_resolve_to_a_model_not_a_string(
    yaml_name: str, member_name: str, model: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Producer↔consumer seam: a prefix the budget layer classifies as a
    real provider must be CONSTRUCTABLE by ``_resolve_model``.

    Without this, a YAML can declare ``model: codex-exec:gpt-5.4``, get a
    sensible ``codex-cli`` budget from ``classify_model_provider``, and still
    fail at agent construction because ``_resolve_model`` hands the raw string
    to pydantic-ai. We only assert the branches that are SUPPOSED to construct
    a Model today (``_ROUTABLE_PREFIXES``); bare shortcuts and ``anthropic:``
    are pass-through by design.
    """
    if not model.startswith(_ROUTABLE_PREFIXES):
        pytest.skip("pass-through model string by design")
    # OpenAI canary path requires a credential to be present; provide a dummy
    # so construction does not raise MissingProviderCredentialError. We never
    # make a network call — _resolve_model only builds the Model object.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    resolved = _resolve_model(AgentSpec(name=member_name, model=model))
    assert isinstance(resolved, Model), (
        f"{yaml_name}: {member_name!r} model={model!r} resolved to a raw "
        f"{type(resolved).__name__} instead of a pydantic-ai Model — the "
        f"runtime would fail at agent construction."
    )


def test_classify_and_resolve_agree_on_codex_exec_being_routed() -> None:
    """Producer↔consumer seam for codex-exec (Z4-17a / #2566).

    Both readers of a ``codex-exec:`` model string now AGREE it is a real
    provider: ``classify_model_provider`` budgets it as ``codex-cli`` (200K
    window) and ``_resolve_model`` constructs a real pydantic-ai ``Model``
    (``CodexExecModel``) rather than returning the raw string. This replaces
    the pre-adapter characterization test that pinned the DISAGREEMENT — the
    certified Codex adapter has landed, so the seam is now closed.
    """
    from teams._codex_model import CodexExecModel

    assert classify_model_provider("codex-exec:gpt-5-codex") == "codex-cli"
    resolved = _resolve_model(AgentSpec(name="t", model="codex-exec:gpt-5-codex"))
    assert isinstance(resolved, CodexExecModel), (
        "codex-exec: must resolve to a CodexExecModel now that the adapter has "
        f"landed; got {type(resolved).__name__}."
    )


def test_codex_exec_resolves_to_codex_model_without_a_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``codex-exec:`` spec resolves to a ``CodexExecModel`` with no codex
    binary on the box.

    Construction must not touch the filesystem for the codex binary — binary
    resolution is deferred to ``request()`` (subprocess spawn time). We still
    point ``BUMBA_CODEX_BINARY`` at a sentinel to prove the env override is
    honoured and the test never needs a real codex install.
    """
    from teams._codex_model import CodexExecModel

    monkeypatch.setenv("BUMBA_CODEX_BINARY", "/nonexistent/codex-test-shim")
    resolved = _resolve_model(
        AgentSpec(name="codex-canary", model="codex-exec:gpt-5-codex")
    )
    assert isinstance(resolved, CodexExecModel)
    assert resolved.model_name == "gpt-5-codex"
    assert resolved.system == "codex-exec"


def test_adapter_codex_exec_passes_config_validation() -> None:
    """``adapter: codex-exec`` is an allowed value in the team-YAML validator.

    ``ALLOWED_ADAPTERS`` gained ``codex-exec`` so a YAML can declare the
    adapter without a load-time ValueError. The adapter field does NOT control
    routing (model-string prefix does) — this is purely the validator
    allow-list. We exercise the same ``_MemberSchema`` validation path the
    config loader uses.
    """
    from teams._config import ALLOWED_ADAPTERS, _AgentSpecSchema

    assert "codex-exec" in ALLOWED_ADAPTERS
    # Should construct without raising (model_post_init validates adapter).
    member = _AgentSpecSchema(
        name="codex-canary",
        role="specialist",
        model="codex-exec:gpt-5-codex",
        adapter="codex-exec",
    )
    assert member.adapter == "codex-exec"
