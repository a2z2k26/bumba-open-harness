"""Tests for Sprint 02.01 — `run_service_with_timeout` async-aware dispatch.

The bug this guards against: ``run_service_with_timeout`` previously always
wrapped ``svc.run`` in ``asyncio.to_thread``. When ``svc.run`` was ``async def``
the call inside the thread returned an unawaited coroutine object, which fell
through the result-normalisation else-branch and synthesised a fake
``ServiceResult(ok=True, anomalies=("non_standard_return",))`` — silent
success. The real workflow never executed.

These tests pin three invariants:
  1. ``async def run`` returning a real ``ServiceResult`` is awaited inline
     and the result is preserved (no ``non_standard_return`` anomaly).
  2. Sync ``run`` returning a real ``ServiceResult`` still works (regression
     guard for the synchronous path).
  3. Errors raised from ``async def run`` propagate out of
     ``run_service_with_timeout`` and ``record_failure`` is invoked, matching
     the contract of the synchronous error path.
  4. A sync ``run`` that returns a bare coroutine (the future-regression
     scenario) is caught by the defensive ``isinstance(result, CoroutineType)``
     branch — the coroutine is awaited, the resulting ``ServiceResult`` is
     used, and we do NOT fall through to ``non_standard_return``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import bridge.services.runner as runner
from bridge.services.base import ServiceBase
from bridge.services.result import ServiceResult


# ---------------------------------------------------------------------------
# Test fixtures — fake services
# ---------------------------------------------------------------------------


class _AsyncOkService(ServiceBase):
    """Async service that returns a real ServiceResult."""

    SERVICE_NAME = "fake_async_ok"

    def __init__(self, data_dir: str | Path) -> None:
        super().__init__(data_dir=data_dir)

    async def run(self) -> ServiceResult:  # type: ignore[override]
        return ServiceResult(
            service=self.SERVICE_NAME,
            ok=True,
            work_items=3,
            duration_ms=10,
            cost_usd=0.0,
        )


class _SyncOkService(ServiceBase):
    """Sync service that returns a real ServiceResult — regression guard."""

    SERVICE_NAME = "fake_sync_ok"

    def __init__(self, data_dir: str | Path) -> None:
        super().__init__(data_dir=data_dir)

    def run(self) -> ServiceResult:  # type: ignore[override]
        return ServiceResult(
            service=self.SERVICE_NAME,
            ok=True,
            work_items=1,
            duration_ms=5,
            cost_usd=0.0,
        )


class _AsyncRaisingService(ServiceBase):
    """Async service whose run() raises — covers the error-propagation path."""

    SERVICE_NAME = "fake_async_raise"

    def __init__(self, data_dir: str | Path) -> None:
        super().__init__(data_dir=data_dir)

    async def run(self) -> ServiceResult:  # type: ignore[override]
        raise RuntimeError("kaboom")


class _BareCoroService(ServiceBase):
    """Sync run() that returns a bare coroutine — defensive-catch regression.

    ``run`` itself is ``def`` (not ``async def``), so
    ``asyncio.iscoroutinefunction(svc.run)`` is False and the runner takes
    the to_thread branch. The thread call returns an unawaited coroutine
    object — exactly the bug Sprint 02.01 fixes.

    This simulates a future regression where a service is partially migrated
    to async without updating its declaration. The defensive
    ``isinstance(result, types.CoroutineType)`` check inside
    ``run_service_with_timeout`` must catch the coroutine, await it, and
    return a real ``ServiceResult``.
    """

    SERVICE_NAME = "fake_bare_coro"

    def __init__(self, data_dir: str | Path) -> None:
        super().__init__(data_dir=data_dir)

    def run(self):  # type: ignore[override]
        async def _inner() -> ServiceResult:
            return ServiceResult(
                service=self.SERVICE_NAME,
                ok=True,
                work_items=7,
                duration_ms=2,
                cost_usd=0.0,
            )

        # Return the bare coroutine without awaiting it — the dispatcher
        # is expected to clean up after this regression.
        return _inner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_fake_service(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    cls: type,
    timeout: int = 30,
) -> None:
    """Inject a fake service into SERVICE_MAP / SERVICE_TIMEOUTS.

    The runner's ``_import_service_class`` reads ``SERVICE_MAP``; we install
    the fake under a unique name so each test stays isolated. ``monkeypatch``
    rolls these dict mutations back at the end of the test.
    """
    monkeypatch.setitem(runner.SERVICE_MAP, name, ("__test_module__", cls.__name__))
    monkeypatch.setitem(runner.SERVICE_TIMEOUTS, name, timeout)


def _patch_runner_to_use_fake(svc: ServiceBase, cls: type):
    """Patch the runner's loader/instantiator to use the in-test instance."""
    return (
        patch("bridge.services.runner._import_service_class", return_value=cls),
        patch("bridge.services.runner._instantiate_service", return_value=svc),
    )


# ---------------------------------------------------------------------------
# Test 1 — async run returning a real ServiceResult
# ---------------------------------------------------------------------------


class TestAsyncRunReturnsServiceResult:
    """An ``async def run`` that returns a real ``ServiceResult`` is awaited
    inline and the result is preserved verbatim — no fake fallback."""

    @pytest.mark.asyncio
    async def test_async_service_result_is_preserved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _register_fake_service(monkeypatch, "fake_async_ok", _AsyncOkService)
        svc = _AsyncOkService(data_dir=tmp_path)

        # Capture the result_normalised inside the runner via patching
        # write_last_run so we can assert against the actual ServiceResult.
        captured: dict = {}

        from bridge.services import result as result_mod

        original_write = result_mod.write_last_run

        def _capture(state_dir, r):  # type: ignore[no-untyped-def]
            captured["result"] = r
            return original_write(state_dir, r)

        monkeypatch.setattr(result_mod, "write_last_run", _capture)

        import_p, inst_p = _patch_runner_to_use_fake(svc, _AsyncOkService)
        with import_p, inst_p:
            ok = await runner.run_service_with_timeout("fake_async_ok")

        assert ok is True

        result = captured.get("result")
        assert isinstance(result, ServiceResult)
        assert result.ok is True
        assert result.service == "fake_async_ok"
        assert result.work_items == 3
        assert "non_standard_return" not in result.anomalies


# ---------------------------------------------------------------------------
# Test 2 — sync path regression guard
# ---------------------------------------------------------------------------


class TestSyncRunRegressionGuard:
    """The sync-run path still works after the async branch is added."""

    @pytest.mark.asyncio
    async def test_sync_service_result_is_preserved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _register_fake_service(monkeypatch, "fake_sync_ok", _SyncOkService)
        svc = _SyncOkService(data_dir=tmp_path)

        captured: dict = {}

        from bridge.services import result as result_mod

        original_write = result_mod.write_last_run

        def _capture(state_dir, r):  # type: ignore[no-untyped-def]
            captured["result"] = r
            return original_write(state_dir, r)

        monkeypatch.setattr(result_mod, "write_last_run", _capture)

        import_p, inst_p = _patch_runner_to_use_fake(svc, _SyncOkService)
        with import_p, inst_p:
            ok = await runner.run_service_with_timeout("fake_sync_ok")

        assert ok is True

        result = captured.get("result")
        assert isinstance(result, ServiceResult)
        assert result.ok is True
        assert result.service == "fake_sync_ok"
        assert result.work_items == 1
        assert "non_standard_return" not in result.anomalies


# ---------------------------------------------------------------------------
# Test 3 — async run that raises propagates and records failure
# ---------------------------------------------------------------------------


class TestAsyncRunRaises:
    """``async def run`` that raises matches the sync error path:
    exception propagates out and ``record_failure`` is invoked.
    """

    @pytest.mark.asyncio
    async def test_async_runtime_error_propagates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _register_fake_service(monkeypatch, "fake_async_raise", _AsyncRaisingService)
        svc = _AsyncRaisingService(data_dir=tmp_path)

        import_p, inst_p = _patch_runner_to_use_fake(svc, _AsyncRaisingService)
        with import_p, inst_p:
            with pytest.raises(RuntimeError, match="kaboom"):
                await runner.run_service_with_timeout("fake_async_raise")

        # ``record_failure`` should have been invoked, leaving consecutive
        # failures incremented and ``last_error`` set — same contract as the
        # synchronous ``CrashService`` test in test_service_runner.py.
        state = svc.load_state()
        assert state["consecutive_failures"] == 1
        assert "kaboom" in (state.get("last_error") or "")


# ---------------------------------------------------------------------------
# Test 4 — defensive coroutine catch (future regression guard)
# ---------------------------------------------------------------------------


class TestBareCoroutineDefensiveCatch:
    """A sync ``run`` returning a bare coroutine is caught by the defensive
    ``isinstance(result, types.CoroutineType)`` branch, awaited, and the
    underlying ``ServiceResult`` is returned. We MUST NOT synthesise a
    ``non_standard_return`` anomaly in this case.
    """

    @pytest.mark.asyncio
    async def test_bare_coroutine_is_awaited_defensively(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        _register_fake_service(monkeypatch, "fake_bare_coro", _BareCoroService)
        svc = _BareCoroService(data_dir=tmp_path)

        captured: dict = {}

        from bridge.services import result as result_mod

        original_write = result_mod.write_last_run

        def _capture(state_dir, r):  # type: ignore[no-untyped-def]
            captured["result"] = r
            return original_write(state_dir, r)

        monkeypatch.setattr(result_mod, "write_last_run", _capture)

        import_p, inst_p = _patch_runner_to_use_fake(svc, _BareCoroService)
        import logging

        with import_p, inst_p:
            with caplog.at_level(logging.WARNING, logger="bridge.services.runner"):
                ok = await runner.run_service_with_timeout("fake_bare_coro")

        assert ok is True

        result = captured.get("result")
        assert isinstance(result, ServiceResult)
        assert result.ok is True
        assert result.service == "fake_bare_coro"
        assert result.work_items == 7
        assert "non_standard_return" not in result.anomalies

        # The defensive branch must announce itself so future regressions
        # surface in the log rather than passing silently.
        assert any(
            "bare coroutine" in record.getMessage()
            for record in caplog.records
        ), "Expected a WARNING log when the defensive coroutine catch fires"
