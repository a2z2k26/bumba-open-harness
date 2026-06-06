"""Tests for ``bridge.invocation_pipeline`` (Sprint P6.1, #1591).

The pipeline module was extracted verbatim from
``BridgeApp._invoke_claude``. These tests cover:

1. Module surface — public entry point + the narrow seam.
2. ``BridgeApp._decide_use_warm`` delegation matrix — the seam must
   forward (model, intent, has_tools, is_workorder) to
   ``warm_policy.should_use_warm_path`` without altering semantics.
3. ``BridgeApp._invoke_claude`` delegates to
   ``invocation_pipeline.invoke_claude_pipeline``.

Behavioral integration of the full pipeline is covered indirectly by
the existing ``test_app*`` suites, which exercise BridgeApp end-to-end.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from bridge import invocation_pipeline
from bridge.model_router import CAREFUL_OPUS_MODEL


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


def test_module_exposes_invoke_claude_pipeline_async_function() -> None:
    """The public entry point is ``invoke_claude_pipeline`` — async, two-arg."""
    fn = getattr(invocation_pipeline, "invoke_claude_pipeline", None)
    assert fn is not None, "invocation_pipeline must export invoke_claude_pipeline"
    assert inspect.iscoroutinefunction(fn), "invoke_claude_pipeline must be async"
    sig = inspect.signature(fn)
    # Two positional args: app (BridgeApp), ctx (MessageContext)
    assert list(sig.parameters.keys()) == ["app", "ctx"], (
        f"unexpected signature: {sig}"
    )


def test_module_does_not_reexport_intent_helpers() -> None:
    """The four ``_INTENT_*`` helpers must stay in ``bridge.app`` (source-grep
    contract, see test_workorder_skill_populated.py). The pipeline imports
    them lazily; it must not re-export or shadow them as module-level names.
    """
    for name in (
        "_INTENT_SKILL_MAP",
        "_INTENT_TO_MODALITY",
        "_intent_to_skill",
        "_intent_to_modality_name",
    ):
        assert not hasattr(invocation_pipeline, name), (
            f"invocation_pipeline must not own '{name}' — it lives in bridge.app"
        )


def test_module_imports_message_context_lazily() -> None:
    """The module must NOT import MessageContext at module top (would create
    a circular import). Instead the function body imports it lazily.
    """
    src = inspect.getsource(invocation_pipeline)
    # Top-level import would be `from .app import MessageContext` outside any function
    # The accepted pattern is `from .app import (MessageContext, ...)` inside
    # the function body. We assert the lazy form is the only one present.
    top_level_app_imports = [
        line for line in src.splitlines()
        if line.startswith("from .app import")
    ]
    assert not top_level_app_imports, (
        f"invocation_pipeline must not import from .app at module top level "
        f"(would circular). Found: {top_level_app_imports}"
    )


# ---------------------------------------------------------------------------
# BridgeApp._decide_use_warm — narrow seam delegation
# ---------------------------------------------------------------------------


def _make_bare_bridge_app():
    """Construct a ``BridgeApp`` instance with no init side effects so we
    can call ``_decide_use_warm`` directly. The seam touches no instance
    state — it forwards to a pure-function policy module — so the
    skipped __init__ is harmless here.
    """
    from bridge.app import BridgeApp
    return BridgeApp.__new__(BridgeApp)


@pytest.mark.parametrize(
    "model,intent,has_tools,is_workorder,expected",
    [
        # opus → False regardless
        ("opus", "chat", False, False, False),
        (CAREFUL_OPUS_MODEL, "chat", False, False, False),
        ("opus", "analyze", False, False, False),
        # workorder → False
        ("haiku", "chat", False, True, False),
        ("sonnet", "chat", False, True, False),
        # has_tools → False
        ("haiku", "chat", True, False, False),
        ("sonnet", "chat", True, False, False),
        # intent None → False (operator-mandated fail-safe)
        ("haiku", None, False, False, False),
        ("sonnet", None, False, False, False),
        # high-risk intents → False
        ("haiku", "deploy", False, False, False),
        ("sonnet", "fix", False, False, False),
        ("haiku", "build", False, False, False),
        # low-risk chat → True
        ("haiku", "chat", False, False, True),
        ("sonnet", "chat", False, False, True),
        ("haiku", "analyze", False, False, True),
    ],
)
def test_decide_use_warm_matches_policy_matrix(
    model: str,
    intent: str | None,
    has_tools: bool,
    is_workorder: bool,
    expected: bool,
) -> None:
    """The narrow seam must forward to ``warm_policy.should_use_warm_path``
    with identical semantics. We exercise every cell of the audit-plan
    Option C decision tree (P1.3 #1571).
    """
    from bridge.warm_policy import should_use_warm_path

    app = _make_bare_bridge_app()
    seam_result = app._decide_use_warm(
        model=model,
        intent=intent,
        has_tools=has_tools,
        is_workorder=is_workorder,
    )
    policy_result = should_use_warm_path(
        model=model,
        intent=intent,
        has_tools=has_tools,
        is_workorder=is_workorder,
    )
    assert seam_result is policy_result
    assert seam_result is expected


def test_decide_use_warm_is_keyword_only() -> None:
    """The seam mirrors warm_policy's keyword-only signature — positional
    calls must raise. This guards against silent argument-order regressions.
    """
    app = _make_bare_bridge_app()
    with pytest.raises(TypeError):
        app._decide_use_warm("haiku", "chat", False, False)  # type: ignore[misc]


def test_decide_use_warm_consults_warm_policy_module(monkeypatch) -> None:
    """The seam delegates to ``warm_policy.should_use_warm_path`` — a
    monkeypatched policy must change the seam's return value. This is
    the load-bearing property that makes warm-policy swappable without
    touching the invocation pipeline.
    """
    import bridge.warm_policy as wp

    captured: dict = {}

    def fake_policy(*, model, intent, has_tools, is_workorder):
        captured["args"] = {
            "model": model,
            "intent": intent,
            "has_tools": has_tools,
            "is_workorder": is_workorder,
        }
        return True  # always-warm sentinel

    monkeypatch.setattr(wp, "should_use_warm_path", fake_policy)

    app = _make_bare_bridge_app()
    # Even with opus (which the real policy would force one-shot), the
    # patched policy returns True — proving the seam routes through.
    result = app._decide_use_warm(
        model="opus",
        intent=None,
        has_tools=True,
        is_workorder=True,
    )
    assert result is True
    assert captured["args"] == {
        "model": "opus",
        "intent": None,
        "has_tools": True,
        "is_workorder": True,
    }


# ---------------------------------------------------------------------------
# BridgeApp._invoke_claude delegation to the pipeline
# ---------------------------------------------------------------------------


def test_invoke_claude_delegates_to_pipeline(monkeypatch) -> None:
    """``BridgeApp._invoke_claude`` is a 2-line delegation: it must call
    ``invocation_pipeline.invoke_claude_pipeline(self, ctx)`` and return
    the awaited result unchanged.
    """
    sentinel_result = object()
    captured: dict = {}

    async def fake_pipeline(app, ctx):
        captured["app"] = app
        captured["ctx"] = ctx
        return sentinel_result

    monkeypatch.setattr(
        invocation_pipeline, "invoke_claude_pipeline", fake_pipeline
    )

    app = _make_bare_bridge_app()
    fake_ctx = object()
    result = asyncio.run(app._invoke_claude(fake_ctx))  # type: ignore[arg-type]

    assert result is sentinel_result
    assert captured["app"] is app
    assert captured["ctx"] is fake_ctx


def test_invoke_claude_method_body_is_thin() -> None:
    """``BridgeApp._invoke_claude`` should now be a thin delegation, not
    the 440-LOC body it used to host. We enforce <=15 lines including
    docstring; the actual body is closer to 4 lines plus a docstring.
    """
    from bridge.app import BridgeApp

    src = inspect.getsource(BridgeApp._invoke_claude)
    line_count = len(src.splitlines())
    assert line_count <= 15, (
        f"_invoke_claude should be a thin delegation post-P6.1; got "
        f"{line_count} lines:\n{src}"
    )


def test_warm_timeout_is_configured_not_hardcoded_300s() -> None:
    """Warm Claude must fast-fail from config, not spend 300s before fallback."""
    src = inspect.getsource(invocation_pipeline.invoke_claude_pipeline)
    assert "warm_response_timeout_seconds" in src
    assert "timeout_s=300.0" not in src


def test_decide_use_warm_method_present_on_bridge_app() -> None:
    """The narrow seam method must be defined on BridgeApp itself (not
    inherited or attached at runtime) so subclasses/tests can override it.
    """
    from bridge.app import BridgeApp

    assert "_decide_use_warm" in BridgeApp.__dict__, (
        "_decide_use_warm must be a direct method of BridgeApp (P6.1 seam)"
    )
