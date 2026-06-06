"""Unit tests for bridge.wiring — Sprint 01.01.

Tests the WiringEntry dataclass + apply_wiring_manifest helper that Sprint 01.02
will use to migrate the 28 scattered self._commands.set_*(...) calls in app.py
into a single declarative manifest.
"""

from __future__ import annotations

import logging
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from typing import Any

import pytest

from bridge.wiring import (
    WiringEntry,
    WiringMissingError,
    WiringReport,
    apply_wiring_manifest,
    log_wiring_report,
)


class _RecordingTarget:
    """Minimal stand-in for CommandHandler / BridgeApp setter targets."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def set_session_hooks(self, value: Any) -> None:
        self.calls.append(("set_session_hooks", value))

    def set_security(self, value: Any) -> None:
        self.calls.append(("set_security", value))

    def set_dispatcher(self, value: Any) -> None:
        self.calls.append(("set_dispatcher", value))

    def set_explodes(self, value: Any) -> None:
        raise RuntimeError("setter blew up")


def _make_app(**source_attrs: Any) -> SimpleNamespace:
    """Construct a SimpleNamespace acting as the BridgeApp source-attribute holder."""
    return SimpleNamespace(**source_attrs)


# ── Dataclass invariants ──────────────────────────────────────────────────────

def test_wiring_entry_is_frozen() -> None:
    target = _RecordingTarget()
    entry = WiringEntry(
        target_name="CommandHandler",
        target=target,
        setter_name="set_session_hooks",
        source_attr="_session_hooks",
        required=True,
        reason_if_none="session hooks must be live",
        group="command-handler",
    )
    with pytest.raises(FrozenInstanceError):
        entry.target_name = "Mutated"  # type: ignore[misc]


def test_wiring_report_default_is_empty() -> None:
    report = WiringReport()
    assert report.active == 0
    assert report.pending == []
    assert report.errors == []


# ── apply_wiring_manifest behavior ────────────────────────────────────────────

def test_apply_wiring_manifest_calls_setter_when_source_present(
    caplog: pytest.LogCaptureFixture,
) -> None:
    target = _RecordingTarget()
    sentinel = object()
    app = _make_app(_session_hooks=sentinel)
    manifest = [
        WiringEntry(
            target_name="CommandHandler",
            target=target,
            setter_name="set_session_hooks",
            source_attr="_session_hooks",
            required=True,
            reason_if_none="session hooks must be live",
            group="command-handler",
        ),
    ]

    report = apply_wiring_manifest(app, manifest, logging.getLogger("test.wiring"))

    assert target.calls == [("set_session_hooks", sentinel)]
    assert report.active == 1
    assert report.pending == []
    assert report.errors == []


def test_apply_wiring_manifest_skips_when_source_none() -> None:
    target = _RecordingTarget()
    app = _make_app(_dispatcher=None)
    manifest = [
        WiringEntry(
            target_name="CommandHandler",
            target=target,
            setter_name="set_dispatcher",
            source_attr="_dispatcher",
            required=False,
            reason_if_none="Plan 04 owns dispatcher construction",
            group="command-handler",
        ),
    ]

    report = apply_wiring_manifest(app, manifest, logging.getLogger("test.wiring"))

    assert target.calls == []
    assert report.active == 0
    assert report.pending == [("set_dispatcher", "Plan 04 owns dispatcher construction")]
    assert report.errors == []


def test_apply_wiring_manifest_skips_when_source_attr_missing() -> None:
    """getattr(app, source_attr, None) returns None when the attribute is absent —
    treat as pending (not error) so manifest entries can be declared before the
    BridgeApp instantiates the source attribute."""
    target = _RecordingTarget()
    app = _make_app()  # no _dispatcher attribute at all
    manifest = [
        WiringEntry(
            target_name="CommandHandler",
            target=target,
            setter_name="set_dispatcher",
            source_attr="_dispatcher",
            required=False,
            reason_if_none="Plan 04 owns dispatcher construction",
            group="command-handler",
        ),
    ]

    report = apply_wiring_manifest(app, manifest, logging.getLogger("test.wiring"))

    assert target.calls == []
    assert report.pending == [("set_dispatcher", "Plan 04 owns dispatcher construction")]
    assert report.errors == []


def test_apply_wiring_manifest_logs_reason_when_pending(
    caplog: pytest.LogCaptureFixture,
) -> None:
    target = _RecordingTarget()
    app = _make_app(_dispatcher=None)
    manifest = [
        WiringEntry(
            target_name="CommandHandler",
            target=target,
            setter_name="set_dispatcher",
            source_attr="_dispatcher",
            required=False,
            reason_if_none="Plan 04 owns dispatcher construction",
            group="command-handler",
        ),
    ]

    logger = logging.getLogger("test.wiring.pending")
    with caplog.at_level(logging.DEBUG, logger="test.wiring.pending"):
        apply_wiring_manifest(app, manifest, logger)

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert "Plan 04 owns dispatcher construction" in rendered
    assert "set_dispatcher" in rendered


def test_apply_wiring_manifest_captures_setter_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    target = _RecordingTarget()
    sentinel = object()
    app = _make_app(_explodes_src=sentinel)
    manifest = [
        WiringEntry(
            target_name="CommandHandler",
            target=target,
            setter_name="set_explodes",
            source_attr="_explodes_src",
            required=False,
            reason_if_none="never None — setter raises by design",
            group="command-handler",
        ),
    ]

    logger = logging.getLogger("test.wiring.errors")
    with caplog.at_level(logging.ERROR, logger="test.wiring.errors"):
        report = apply_wiring_manifest(app, manifest, logger)

    assert report.active == 0
    assert report.pending == []
    assert len(report.errors) == 1
    setter_name, exc = report.errors[0]
    assert setter_name == "set_explodes"
    assert isinstance(exc, RuntimeError)
    assert "setter blew up" in str(exc)


def test_required_entry_with_none_source_raises() -> None:
    """A required=True entry with a None source MUST raise RuntimeError —
    silent skipping is the anti-pattern this manifest is designed to eliminate."""
    target = _RecordingTarget()
    app = _make_app(_session_hooks=None)
    manifest = [
        WiringEntry(
            target_name="CommandHandler",
            target=target,
            setter_name="set_session_hooks",
            source_attr="_session_hooks",
            required=True,
            reason_if_none="session hooks must be live",
            group="command-handler",
        ),
    ]

    with pytest.raises(RuntimeError, match="set_session_hooks"):
        apply_wiring_manifest(app, manifest, logging.getLogger("test.wiring"))


def test_apply_wiring_manifest_does_not_mutate_manifest() -> None:
    """The helper is pure — it must not mutate the manifest sequence."""
    target = _RecordingTarget()
    app = _make_app(_session_hooks=object())
    entry = WiringEntry(
        target_name="CommandHandler",
        target=target,
        setter_name="set_session_hooks",
        source_attr="_session_hooks",
        required=True,
        reason_if_none="session hooks must be live",
        group="command-handler",
    )
    manifest: list[WiringEntry] = [entry]
    snapshot = tuple(manifest)

    apply_wiring_manifest(app, manifest, logging.getLogger("test.wiring"))

    assert tuple(manifest) == snapshot
    assert manifest[0] is entry


def test_apply_wiring_manifest_runs_entries_in_order() -> None:
    target = _RecordingTarget()
    src1, src2, src3 = object(), object(), object()
    app = _make_app(_a=src1, _b=src2, _c=src3)
    manifest = [
        WiringEntry("CH", target, "set_session_hooks", "_a", True, "", "command-handler"),
        WiringEntry("CH", target, "set_security", "_b", True, "", "command-handler"),
        WiringEntry("CH", target, "set_dispatcher", "_c", False, "", "command-handler"),
    ]

    apply_wiring_manifest(app, manifest, logging.getLogger("test.wiring"))

    assert [name for name, _ in target.calls] == [
        "set_session_hooks",
        "set_security",
        "set_dispatcher",
    ]


# ── log_wiring_report ─────────────────────────────────────────────────────────

def test_log_wiring_report_emits_summary_and_pending_lines(
    caplog: pytest.LogCaptureFixture,
) -> None:
    report = WiringReport(
        active=27,
        pending=[
            ("set_workflow_engine", "Plan 02 owns WorkflowEngine"),
            ("set_routing_brain", "Plan 03 owns RoutingBrain"),
        ],
        errors=[],
    )
    logger = logging.getLogger("test.wiring.report")

    with caplog.at_level(logging.DEBUG, logger="test.wiring.report"):
        log_wiring_report(report, logger)

    info_lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    debug_lines = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]

    assert any("Wiring complete" in m and "27 active" in m and "2 pending" in m and "0 errors" in m for m in info_lines)
    assert any("set_workflow_engine" in m and "Plan 02 owns WorkflowEngine" in m for m in debug_lines)
    assert any("set_routing_brain" in m and "Plan 03 owns RoutingBrain" in m for m in debug_lines)


def test_log_wiring_report_emits_error_lines_at_error_level(
    caplog: pytest.LogCaptureFixture,
) -> None:
    err = RuntimeError("boom")
    report = WiringReport(active=1, pending=[], errors=[("set_explodes", err)])
    logger = logging.getLogger("test.wiring.report.err")

    with caplog.at_level(logging.DEBUG, logger="test.wiring.report.err"):
        log_wiring_report(report, logger)

    error_lines = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    info_lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("set_explodes" in m and "boom" in m for m in error_lines)
    assert any("1 errors" in m for m in info_lines)


# ── Sprint #1614 — WiringMissingError + failed_marker_attr ────────────────────


def test_wiring_missing_error_is_runtime_error_subclass() -> None:
    """WiringMissingError must be catchable as RuntimeError so existing
    exception handlers in scheduler loops don't have to special-case it.
    """
    err = WiringMissingError("test")
    assert isinstance(err, RuntimeError)


def test_failed_marker_attr_defaults_to_none() -> None:
    """Existing WiringEntry call sites omit the new field; preserve their
    original PENDING-vs-active semantics by defaulting to None.
    """
    target = _RecordingTarget()
    entry = WiringEntry(
        target_name="CH", target=target, setter_name="set_dispatcher",
        source_attr="_dispatcher", required=False, reason_if_none="",
        group="command-handler",
    )
    assert entry.failed_marker_attr is None


def test_pending_entry_with_failed_marker_set_routes_to_failed() -> None:
    """Sprint #1614 AC: when failed_marker_attr is set AND the marker is
    truthy on the app, the entry is recorded in report.failed instead of
    report.pending.
    """
    target = _RecordingTarget()
    app = _make_app(
        _proactive_scheduler=None,
        _proactive_scheduler_init_failed=True,  # init exception happened
    )
    manifest = [
        WiringEntry(
            target_name="CH", target=target,
            setter_name="set_proactive_scheduler",
            source_attr="_proactive_scheduler", required=False,
            reason_if_none="Deferred; D7.12 #1424",
            group="command-handler",
            failed_marker_attr="_proactive_scheduler_init_failed",
        ),
    ]
    report = apply_wiring_manifest(
        app, manifest, logging.getLogger("test.wiring.failed"),
    )
    assert report.pending == []
    assert report.failed == [
        ("set_proactive_scheduler", "Deferred; D7.12 #1424"),
    ]


def test_pending_entry_with_failed_marker_unset_stays_pending() -> None:
    """When the marker is False (or absent), the entry remains in pending
    — i.e. "deferred by future plan", not "tried and crashed".
    """
    target = _RecordingTarget()
    app = _make_app(
        _proactive_scheduler=None,
        _proactive_scheduler_init_failed=False,
    )
    manifest = [
        WiringEntry(
            target_name="CH", target=target,
            setter_name="set_proactive_scheduler",
            source_attr="_proactive_scheduler", required=False,
            reason_if_none="Deferred; D7.12 #1424",
            group="command-handler",
            failed_marker_attr="_proactive_scheduler_init_failed",
        ),
    ]
    report = apply_wiring_manifest(
        app, manifest, logging.getLogger("test.wiring.pending"),
    )
    assert report.failed == []
    assert report.pending == [
        ("set_proactive_scheduler", "Deferred; D7.12 #1424"),
    ]


def test_pending_entry_with_missing_failed_marker_attr_stays_pending() -> None:
    """When the named marker attribute doesn't exist on the app at all
    (e.g. the init block hasn't run yet), getattr's default of False keeps
    the entry in pending. No AttributeError.
    """
    target = _RecordingTarget()
    app = _make_app(_proactive_scheduler=None)  # marker attr is absent
    manifest = [
        WiringEntry(
            target_name="CH", target=target,
            setter_name="set_proactive_scheduler",
            source_attr="_proactive_scheduler", required=False,
            reason_if_none="Deferred; D7.12 #1424",
            group="command-handler",
            failed_marker_attr="_proactive_scheduler_init_failed",
        ),
    ]
    report = apply_wiring_manifest(
        app, manifest, logging.getLogger("test.wiring.absent"),
    )
    assert report.failed == []
    assert len(report.pending) == 1


def test_log_wiring_report_emits_failed_at_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Sprint #1614: FAILED entries log at WARNING (not DEBUG like
    pending), so the operator notices them in stderr without an explicit
    grep.
    """
    report = WiringReport(
        active=5,
        pending=[],
        errors=[],
        failed=[("set_proactive_scheduler", "Deferred; D7.12 #1424")],
    )
    logger = logging.getLogger("test.wiring.failed.log")
    with caplog.at_level(logging.DEBUG, logger="test.wiring.failed.log"):
        log_wiring_report(report, logger)
    info_lines = [
        r.getMessage() for r in caplog.records if r.levelno == logging.INFO
    ]
    warning_lines = [
        r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
    ]
    # Summary line contains the failed count
    assert any("1 failed" in m for m in info_lines)
    # Per-entry warning line names the setter
    assert any("set_proactive_scheduler" in m for m in warning_lines)
