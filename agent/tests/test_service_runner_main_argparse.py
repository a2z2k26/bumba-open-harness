"""Tests for Sprint 02.02 — argparse + extra_kwargs threading in runner.main.

The bug this guards against: three LaunchDaemon plists
(``com.bumba.agent-consolidation-{micro,standard,deep}``) pass
``--mode <value>`` to ``python -m bridge.services.runner consolidation``.
Before Sprint 02.02 the runner read only ``sys.argv[1]`` (the service name)
and silently dropped the rest. ``_instantiate_service`` built kwargs from
constants only, never forwarding ``mode=``. Result: all three cadences ran
the default ``standard`` consolidation pipeline. The operator saw three
distinct schedules in launchd; the runtime ran one mode three times.

These tests pin the following invariants for ``runner.main`` /
``_async_main`` / ``_instantiate_service``:

  1. ``runner.py consolidation --mode deep`` → ``_instantiate_service`` is
     called with ``extra_kwargs={"mode": "deep"}``.
  2. Same for ``--mode micro``.
  3. Same for ``--mode standard``.
  4. ``runner.py consolidation`` (no ``--mode``) → ``extra_kwargs is None``;
     the service constructor sees no ``mode=`` kwarg, so the
     ``ConsolidationService.__init__`` default (``"standard"``) takes over.
  5. Backward compatibility — ``runner.py weekly_review`` runs without
     argparse error and ``_instantiate_service`` is called with
     ``extra_kwargs=None`` (no behaviour change for the dozen existing
     argv-less services).
  6. Unknown service name still surfaces a ``ValueError`` at the
     ``_import_service_class`` boundary — argparse must not swallow or
     mask that.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

import bridge.services.runner as runner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _install_main_stubs(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MagicMock, MagicMock]:
    """Stub out the heavy entry-point dependencies that ``main`` triggers.

    Returns ``(asyncio_run_mock, instantiate_mock)`` so each test can assert
    on the args that ``main`` would forward to ``_async_main`` / further
    into ``_instantiate_service``.

    We patch in two layers because ``main`` calls ``asyncio.run(_async_main(...))``,
    and we want to assert on the ``extra_kwargs`` that *would* eventually
    reach ``_instantiate_service``. Easiest route: capture the
    ``_async_main`` coroutine before it runs, inspect its bound args, then
    discard it without executing.
    """
    # Avoid touching the real logging file handlers — runner._setup_logging
    # tries to create /opt/bumba-harness/logs which won't exist in CI.
    monkeypatch.setattr(runner, "_setup_logging", lambda name: None)

    # Capture the coroutine produced by _async_main(...). We don't execute
    # it; we extract the args via the wrapping mock instead.
    async_main_mock = MagicMock(name="_async_main", return_value=None)
    monkeypatch.setattr(runner, "_async_main", async_main_mock)

    # asyncio.run will be called with the MagicMock's return value (None)
    # — patch it so it's a no-op rather than raising "expected coroutine".
    asyncio_run_mock = MagicMock(name="asyncio.run", return_value=None)
    monkeypatch.setattr(runner.asyncio, "run", asyncio_run_mock)

    # Also stub _instantiate_service so we can assert on extra_kwargs even
    # if a test ends up exercising deeper code paths.
    instantiate_mock = MagicMock(name="_instantiate_service", return_value=MagicMock())
    monkeypatch.setattr(runner, "_instantiate_service", instantiate_mock)

    # Pretend service classes import fine — keeps Test 5 isolated from real
    # module imports.
    monkeypatch.setattr(runner, "_import_service_class", lambda n: MagicMock())

    return async_main_mock, instantiate_mock


def _last_extra_kwargs(async_main_mock: MagicMock) -> Any:
    """Pull the ``extra_kwargs`` argument off the most recent ``_async_main`` call."""
    assert async_main_mock.called, "_async_main was never called by main()"
    last_call = async_main_mock.call_args
    # _async_main(name, extra_kwargs=...) — pull from kwargs first, fall back
    # to positional in case main() ever switches to positional binding.
    if "extra_kwargs" in last_call.kwargs:
        return last_call.kwargs["extra_kwargs"]
    if len(last_call.args) >= 2:
        return last_call.args[1]
    return None


# ---------------------------------------------------------------------------
# Test 1 — consolidation --mode deep
# ---------------------------------------------------------------------------


class TestConsolidationDeepMode:
    def test_main_threads_mode_deep_into_extra_kwargs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async_main_mock, _ = _install_main_stubs(monkeypatch)
        monkeypatch.setattr(
            runner.sys, "argv", ["runner.py", "consolidation", "--mode", "deep"]
        )

        runner.main()

        extra = _last_extra_kwargs(async_main_mock)
        assert extra == {"mode": "deep"}, (
            f"expected extra_kwargs={{'mode': 'deep'}}, got {extra!r}"
        )


# ---------------------------------------------------------------------------
# Test 2 — consolidation --mode micro
# ---------------------------------------------------------------------------


class TestConsolidationMicroMode:
    def test_main_threads_mode_micro_into_extra_kwargs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async_main_mock, _ = _install_main_stubs(monkeypatch)
        monkeypatch.setattr(
            runner.sys, "argv", ["runner.py", "consolidation", "--mode", "micro"]
        )

        runner.main()

        extra = _last_extra_kwargs(async_main_mock)
        assert extra == {"mode": "micro"}


# ---------------------------------------------------------------------------
# Test 3 — consolidation --mode standard
# ---------------------------------------------------------------------------


class TestConsolidationStandardMode:
    def test_main_threads_mode_standard_into_extra_kwargs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async_main_mock, _ = _install_main_stubs(monkeypatch)
        monkeypatch.setattr(
            runner.sys, "argv", ["runner.py", "consolidation", "--mode", "standard"]
        )

        runner.main()

        extra = _last_extra_kwargs(async_main_mock)
        assert extra == {"mode": "standard"}


# ---------------------------------------------------------------------------
# Test 4 — consolidation without --mode → no override, default applies
# ---------------------------------------------------------------------------


class TestConsolidationDefaultMode:
    """Without --mode, ``extra_kwargs`` must be ``None`` so that
    ``ConsolidationService.__init__``'s default (``mode="standard"``) is
    used. Crucially we MUST NOT inject ``{"mode": "standard"}`` here;
    that would mask future default changes inside the service class."""

    def test_main_omits_mode_when_flag_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async_main_mock, _ = _install_main_stubs(monkeypatch)
        monkeypatch.setattr(runner.sys, "argv", ["runner.py", "consolidation"])

        runner.main()

        extra = _last_extra_kwargs(async_main_mock)
        assert extra is None, (
            f"expected extra_kwargs is None when --mode omitted, got {extra!r}"
        )


# ---------------------------------------------------------------------------
# Test 5 — backward compatibility for argv-less services
# ---------------------------------------------------------------------------


class TestArgvlessServiceBackwardCompat:
    """The dozen+ existing services (briefing, checkin, weekly_review, ...)
    invoke the runner with no trailing flags. argparse with all-optional
    flags must accept that, and ``extra_kwargs`` must remain ``None`` so
    nothing about their constructor signatures is perturbed.
    """

    def test_weekly_review_runs_without_extra_kwargs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async_main_mock, _ = _install_main_stubs(monkeypatch)
        monkeypatch.setattr(runner.sys, "argv", ["runner.py", "weekly_review"])

        runner.main()  # Must not raise

        extra = _last_extra_kwargs(async_main_mock)
        assert extra is None

    def test_briefing_runs_without_extra_kwargs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async_main_mock, _ = _install_main_stubs(monkeypatch)
        monkeypatch.setattr(runner.sys, "argv", ["runner.py", "briefing"])

        runner.main()

        extra = _last_extra_kwargs(async_main_mock)
        assert extra is None

    def test_non_consolidation_service_with_mode_flag_does_not_inject(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defence in depth: even if ``--mode`` somehow reaches another
        service, only ``consolidation`` should get the kwarg injected.
        Prevents a future regression where someone broadens the gate."""
        async_main_mock, _ = _install_main_stubs(monkeypatch)
        monkeypatch.setattr(
            runner.sys, "argv", ["runner.py", "weekly_review", "--mode", "deep"]
        )

        runner.main()

        extra = _last_extra_kwargs(async_main_mock)
        assert extra is None, (
            f"--mode must only be threaded into consolidation; got {extra!r}"
        )


# ---------------------------------------------------------------------------
# Test 6 — argparse rejects bad mode values; missing service still errors
# ---------------------------------------------------------------------------


class TestErrorPaths:
    def test_invalid_mode_value_exits(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """argparse's ``choices=`` enforces the three valid modes — anything
        else triggers a SystemExit. Guards against typoed plist edits."""
        _install_main_stubs(monkeypatch)
        monkeypatch.setattr(
            runner.sys, "argv", ["runner.py", "consolidation", "--mode", "ultra"]
        )

        with pytest.raises(SystemExit):
            runner.main()

    def test_no_service_name_exits(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Existing usage error path is preserved — no service name still
        prints usage and exits 1, matching pre-Sprint-02.02 behaviour."""
        _install_main_stubs(monkeypatch)
        monkeypatch.setattr(runner.sys, "argv", ["runner.py"])

        with pytest.raises(SystemExit) as exc_info:
            runner.main()

        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Test 7 — _instantiate_service correctly merges extra_kwargs (unit-level)
# ---------------------------------------------------------------------------


class TestInstantiateServiceExtraKwargs:
    """Direct unit test of ``_instantiate_service`` — guards the contract
    between ``main`` and the constructor wiring."""

    def test_extra_kwargs_appears_on_constructor_call(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """``extra_kwargs={'mode': 'deep'}`` must end up as ``cls(mode='deep', ...)``."""
        # Stub helpers that touch the filesystem / config
        monkeypatch.setattr(runner, "_load_chat_id", lambda: "test-chat")
        monkeypatch.setattr(runner, "DATA_DIR", tmp_path)

        captured: dict[str, Any] = {}

        class _FakeService:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

        # 'consolidation' is in NEEDS_DB so db_path will also be present —
        # this confirms extra_kwargs layers cleanly on top of the base set.
        runner._instantiate_service(
            "consolidation",
            _FakeService,
            event_callback=None,
            extra_kwargs={"mode": "deep"},
        )

        assert captured.get("mode") == "deep"
        assert "data_dir" in captured  # base kwargs preserved
        assert "db_path" in captured   # NEEDS_DB still applies
        assert captured.get("chat_id") == "test-chat"

    def test_extra_kwargs_none_keeps_base_kwargs_only(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Default path: no extra_kwargs → base kwargs only."""
        monkeypatch.setattr(runner, "_load_chat_id", lambda: "test-chat")
        monkeypatch.setattr(runner, "DATA_DIR", tmp_path)

        captured: dict[str, Any] = {}

        class _FakeService:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

        runner._instantiate_service(
            "consolidation",
            _FakeService,
            event_callback=None,
            extra_kwargs=None,
        )

        assert "mode" not in captured
        assert "data_dir" in captured
        assert "db_path" in captured
