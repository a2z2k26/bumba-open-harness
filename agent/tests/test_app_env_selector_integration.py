"""app.py EnvironmentSelector integration — AC-1 and AC-7 (#564).

Sprint P6.1 (#1591) extracted the dispatch path body into
``bridge/invocation_pipeline.py``. Source-grep tests now scan the combined
text of both files so the contract assertions still hold against the
extracted pipeline.
"""
from __future__ import annotations

import pathlib


def _bridge_dir() -> pathlib.Path:
    return pathlib.Path(__file__).parent.parent / "bridge"


def _combined_pipeline_source() -> str:
    """Concatenate app.py and invocation_pipeline.py source for grep assertions."""
    bridge = _bridge_dir()
    return (bridge / "app.py").read_text() + "\n" + (bridge / "invocation_pipeline.py").read_text()


def test_app_does_not_hardcode_subagent_in_dispatch_path():
    """AC-1: dispatch path no longer contains Environment.SUBAGENT as a literal
    without going through selector.

    If the selector is properly wired, we expect either:
    - No bare 'Environment.SUBAGENT' in the dispatch block, or
    - An 'env_selector.select' call is present alongside it.
    """
    text = _combined_pipeline_source()

    # The dispatch path comment + the hardcoded line should be gone
    assert "wo.with_environment(Environment.SUBAGENT, \"dispatcher routing\")" not in text, (
        "dispatch path still hardcodes Environment.SUBAGENT with 'dispatcher routing' rationale. "
        "This must be replaced by env_selector.select(wo)."
    )


def test_app_uses_env_selector_select_in_dispatch_path():
    """AC-1: dispatch path calls _env_selector.select(wo)."""
    text = _combined_pipeline_source()
    assert "_env_selector.select" in text, (
        "dispatch path must call self._env_selector.select(wo) (app.py + invocation_pipeline.py)"
    )


def test_app_calls_record_usage_after_dispatch():
    """AC-7: dispatch path calls _env_selector.record_usage after dispatch."""
    text = _combined_pipeline_source()
    assert "_env_selector.record_usage" in text, (
        "dispatch path must call self._env_selector.record_usage(env) after dispatch"
    )


def test_dispatch_path_threads_executor_statuses_into_select():
    """Sprint S2.3 followup (#2326): the automatic-selection seam at
    ``invocation_pipeline:160`` must thread the dispatcher's
    executor-status map into ``env_selector.select(...)``. Before this
    wiring, ``select(wo)`` was called positionally with no status map
    and the routability guard added in S2.3 was silently bypassed —
    meaning a stubbed executor (e.g. E2B) could be returned as the
    chosen environment whenever it sat in the fallback walk.

    This is a source-grep regression — the behavioural semantics
    (would-have-picked-E2B → SUBAGENT-instead) are covered by
    ``test_environment_selector_excludes_stubbed_e2b`` and
    ``test_environment_selector_skips_e2b_when_default_unroutable`` in
    ``test_environment_selector.py``. This test locks in the call-site
    contract so the wiring can't silently regress.
    """
    text = _combined_pipeline_source()
    assert "executor_statuses=" in text, (
        "dispatch path must pass executor_statuses=... when calling "
        "_env_selector.select(...) (S2.3 followup #2326)"
    )
    assert "get_executor_statuses" in text, (
        "dispatch path must source the status map from "
        "Dispatcher.get_executor_statuses() (S2.3 followup #2326)"
    )


def test_dispatcher_no_dispatch_e2b_stub():
    """AC-6: _dispatch_e2b is fully removed from dispatcher.py."""
    path = pathlib.Path(__file__).parent.parent / "bridge" / "dispatcher.py"
    text = path.read_text()
    assert "_dispatch_e2b" not in text, (
        "dispatcher.py still contains the _dispatch_e2b stub — must be deleted in S02d"
    )


def test_dispatcher_no_e2b_fallthrough_branch():
    """AC-6: The 'if route == e2b' fallthrough branch is removed."""
    path = pathlib.Path(__file__).parent.parent / "bridge" / "dispatcher.py"
    text = path.read_text()
    assert 'route == "e2b"' not in text, (
        "dispatcher.py still contains 'if route == \"e2b\"' fallthrough — must be deleted"
    )
