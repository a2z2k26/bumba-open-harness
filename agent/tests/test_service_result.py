"""Tests for ServiceResult — the Zone 2 BET 1 (keystone) output contract.

Covers:
- ServiceResult frozen dataclass shape + defaults
- format_completion_line for OK / FAIL / SKIP
- write_last_run atomic merge
- Runner emits completion line + writes last_run.json, with bool backwards-compat
- Every entry in SERVICE_MAP has run() annotated as ServiceResult
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bridge.services.result import (
    ServiceResult,
    format_completion_line,
    render_services_table,
    write_last_run,
)


# ── Task 0.1.1: ServiceResult dataclass + formatter ───────────────────────────


def test_service_result_is_frozen():
    r = ServiceResult(
        service="briefing",
        ok=True,
        work_items=3,
        duration_ms=1234,
        cost_usd=0.012,
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        r.work_items = 99  # type: ignore[misc]


def test_service_result_defaults():
    r = ServiceResult(
        service="briefing",
        ok=True,
        work_items=0,
        duration_ms=10,
        cost_usd=0.0,
    )
    assert r.artifacts == ()
    assert r.anomalies == ()
    assert r.skip_reason is None
    assert r.narration is None


def test_format_completion_line_ok():
    r = ServiceResult(
        service="retro",
        ok=True,
        work_items=7,
        duration_ms=4500,
        cost_usd=0.34,
    )
    line = format_completion_line(r)
    assert line == "[SERVICE][OK retro work_items=7 duration=4.5s cost=$0.34]"


def test_format_completion_line_fail():
    r = ServiceResult(
        service="email",
        ok=False,
        work_items=0,
        duration_ms=50,
        cost_usd=0.0,
        anomalies=("oauth_401",),
    )
    line = format_completion_line(r)
    assert (
        line
        == "[SERVICE][FAIL email work_items=0 duration=0.1s cost=$0.00 anomalies=oauth_401]"
    )


def test_format_completion_line_skip():
    r = ServiceResult(
        service="email",
        ok=True,
        work_items=0,
        duration_ms=20,
        cost_usd=0.0,
        skip_reason="no_new_mail",
    )
    line = format_completion_line(r)
    assert line == "[SERVICE][SKIP email reason=no_new_mail duration=0.0s]"


def test_format_completion_line_is_greppable():
    """FR-008: completion lines MUST be greppable with `\\[SERVICE\\]\\[(OK|FAIL|SKIP) `."""
    import re

    pattern = re.compile(r"\[SERVICE\]\[(OK|FAIL|SKIP) ")
    for r in (
        ServiceResult(service="a", ok=True, work_items=1, duration_ms=1, cost_usd=0.0),
        ServiceResult(service="b", ok=False, work_items=0, duration_ms=1, cost_usd=0.0),
        ServiceResult(
            service="c",
            ok=True,
            work_items=0,
            duration_ms=1,
            cost_usd=0.0,
            skip_reason="no_work",
        ),
    ):
        assert pattern.match(format_completion_line(r))


# ── Task 0.1.2: last_run.json atomic writer ───────────────────────────────────


def test_write_last_run_creates_aggregate(tmp_path: Path):
    state_dir = tmp_path / "service_state"
    state_dir.mkdir()
    r1 = ServiceResult(
        service="briefing",
        ok=True,
        work_items=3,
        duration_ms=1200,
        cost_usd=0.01,
    )
    write_last_run(state_dir, r1)
    data = json.loads((state_dir / "last_run.json").read_text())
    assert data["briefing"]["ok"] is True
    assert data["briefing"]["work_items"] == 3
    assert data["briefing"]["completion_line"].startswith("[SERVICE][OK briefing")
    assert "completed_at" in data["briefing"]


def test_write_last_run_merges_existing(tmp_path: Path):
    state_dir = tmp_path / "service_state"
    state_dir.mkdir()
    write_last_run(
        state_dir,
        ServiceResult(
            service="briefing",
            ok=True,
            work_items=3,
            duration_ms=10,
            cost_usd=0.0,
        ),
    )
    write_last_run(
        state_dir,
        ServiceResult(
            service="email",
            ok=False,
            work_items=0,
            duration_ms=20,
            cost_usd=0.0,
        ),
    )
    data = json.loads((state_dir / "last_run.json").read_text())
    assert "briefing" in data and "email" in data
    assert data["email"]["ok"] is False


def test_write_last_run_recovers_from_corrupt_json(tmp_path: Path):
    """Edge case from spec: corrupt JSON → reset to {} and continue."""
    state_dir = tmp_path / "service_state"
    state_dir.mkdir()
    (state_dir / "last_run.json").write_text("{not valid json")
    write_last_run(
        state_dir,
        ServiceResult(
            service="briefing",
            ok=True,
            work_items=1,
            duration_ms=5,
            cost_usd=0.0,
        ),
    )
    data = json.loads((state_dir / "last_run.json").read_text())
    assert "briefing" in data


# ── Task 0.1.3: Runner emits completion line + writes last_run.json ──────────


def test_runner_writes_completion_line_and_last_run(
    tmp_path: Path,
    monkeypatch,
    caplog,
):
    """Given a ServiceResult return, runner logs the completion line and
    writes the aggregate. Validates FR-002 and FR-003."""
    monkeypatch.setattr("bridge.services.runner.DATA_DIR", tmp_path)

    fake_svc = MagicMock()
    fake_svc.run.return_value = ServiceResult(
        service="briefing",
        ok=True,
        work_items=2,
        duration_ms=500,
        cost_usd=0.05,
    )
    fake_cls = MagicMock(return_value=fake_svc)

    caplog.set_level(logging.INFO, logger="bridge.services.runner")
    with (
        patch(
            "bridge.services.runner._import_service_class",
            return_value=fake_cls,
        ),
        patch(
            "bridge.services.runner._instantiate_service",
            return_value=fake_svc,
        ),
        patch(
            "bridge.services.runner._create_event_callback",
            return_value=(None, None),
        ),
    ):
        from bridge.services.runner import run_service_with_timeout

        asyncio.run(run_service_with_timeout("briefing"))

    messages = [r.getMessage() for r in caplog.records]
    assert any("[SERVICE][OK briefing" in m for m in messages), messages

    last_run_path = tmp_path / "service_state" / "last_run.json"
    assert last_run_path.exists()
    data = json.loads(last_run_path.read_text())
    assert data["briefing"]["work_items"] == 2
    assert data["briefing"]["ok"] is True


def test_runner_backwards_compat_bool_true(tmp_path: Path, monkeypatch, caplog):
    """FR-005: if a service still returns bool, runner synthesizes a ServiceResult."""
    monkeypatch.setattr("bridge.services.runner.DATA_DIR", tmp_path)

    fake_svc = MagicMock()
    fake_svc.run.return_value = True
    fake_cls = MagicMock(return_value=fake_svc)

    caplog.set_level(logging.INFO, logger="bridge.services.runner")
    with (
        patch(
            "bridge.services.runner._import_service_class",
            return_value=fake_cls,
        ),
        patch(
            "bridge.services.runner._instantiate_service",
            return_value=fake_svc,
        ),
        patch(
            "bridge.services.runner._create_event_callback",
            return_value=(None, None),
        ),
    ):
        from bridge.services.runner import run_service_with_timeout

        asyncio.run(run_service_with_timeout("email"))

    messages = [r.getMessage() for r in caplog.records]
    assert any("[SERVICE][OK email" in m for m in messages), messages
    data = json.loads((tmp_path / "service_state" / "last_run.json").read_text())
    assert data["email"]["ok"] is True
    assert data["email"]["work_items"] == 0


def test_runner_backwards_compat_bool_false_emits_fail(
    tmp_path: Path,
    monkeypatch,
    caplog,
):
    monkeypatch.setattr("bridge.services.runner.DATA_DIR", tmp_path)

    fake_svc = MagicMock()
    fake_svc.run.return_value = False
    fake_cls = MagicMock(return_value=fake_svc)

    caplog.set_level(logging.INFO, logger="bridge.services.runner")
    with (
        patch(
            "bridge.services.runner._import_service_class",
            return_value=fake_cls,
        ),
        patch(
            "bridge.services.runner._instantiate_service",
            return_value=fake_svc,
        ),
        patch(
            "bridge.services.runner._create_event_callback",
            return_value=(None, None),
        ),
    ):
        from bridge.services.runner import run_service_with_timeout

        asyncio.run(run_service_with_timeout("email"))

    messages = [r.getMessage() for r in caplog.records]
    assert any("[SERVICE][FAIL email" in m for m in messages), messages


def test_runner_non_standard_return_records_anomaly(
    tmp_path: Path,
    monkeypatch,
    caplog,
):
    monkeypatch.setattr("bridge.services.runner.DATA_DIR", tmp_path)

    fake_svc = MagicMock()
    fake_svc.run.return_value = {"weird": "dict"}
    fake_cls = MagicMock(return_value=fake_svc)

    caplog.set_level(logging.INFO, logger="bridge.services.runner")
    with (
        patch(
            "bridge.services.runner._import_service_class",
            return_value=fake_cls,
        ),
        patch(
            "bridge.services.runner._instantiate_service",
            return_value=fake_svc,
        ),
        patch(
            "bridge.services.runner._create_event_callback",
            return_value=(None, None),
        ),
    ):
        from bridge.services.runner import run_service_with_timeout

        asyncio.run(run_service_with_timeout("email"))

    data = json.loads((tmp_path / "service_state" / "last_run.json").read_text())
    assert "non_standard_return" in data["email"]["anomalies"]


# ── Task 0.1.4: Regression guard — every service in SERVICE_MAP annotates ─────


def test_all_services_return_service_result_type():
    """FR-004: every service's run() MUST be annotated as ServiceResult.

    Accepts either the resolved class (when the module eagerly evaluates
    annotations) or a stringified name such as ``ServiceResult`` or
    ``"ServiceResult"`` (when ``from __future__ import annotations`` defers
    evaluation).
    """
    from bridge.services.runner import SERVICE_MAP

    accepted_strings = {"ServiceResult", "'ServiceResult'", '"ServiceResult"'}

    for name, (mod_path, cls_name) in SERVICE_MAP.items():
        mod = __import__(mod_path, fromlist=[cls_name])
        cls = getattr(mod, cls_name)
        sig = inspect.signature(cls.run)
        ann = sig.return_annotation
        if ann is ServiceResult:
            continue
        if isinstance(ann, str) and ann.strip("'\"") == "ServiceResult":
            continue
        if ann in accepted_strings:
            continue
        raise AssertionError(
            f"{name}.run() must be annotated -> ServiceResult, got {ann!r}"
        )


# ── Task 0.1.5: /services Discord command ─────────────────────────────────────


def test_render_services_table_missing_file(tmp_path: Path):
    out = render_services_table(tmp_path)
    assert "No service runs recorded yet" in out


def test_render_services_table_with_data(tmp_path: Path):
    state_dir = tmp_path / "service_state"
    state_dir.mkdir()
    (state_dir / "last_run.json").write_text(
        json.dumps(
            {
                "briefing": {
                    "ok": True,
                    "work_items": 3,
                    "completion_line": "[SERVICE][OK briefing work_items=3 duration=1.2s cost=$0.01]",
                    "completed_at": "2026-04-18T08:00:00+00:00",
                },
                "email": {
                    "ok": False,
                    "work_items": 0,
                    "completion_line": "[SERVICE][FAIL email work_items=0 duration=0.1s cost=$0.00 anomalies=oauth_401]",
                    "completed_at": "2026-04-18T10:00:00+00:00",
                },
            }
        )
    )
    out = render_services_table(tmp_path)
    assert "briefing" in out and "OK" in out
    assert "email" in out and "FAIL" in out and "oauth_401" in out


def test_render_services_table_handles_corrupt_file(tmp_path: Path):
    state_dir = tmp_path / "service_state"
    state_dir.mkdir()
    (state_dir / "last_run.json").write_text("{not valid")
    out = render_services_table(tmp_path)
    assert "Could not read" in out
