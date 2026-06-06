"""Browser action trace artifacts for Zone 4 run workspaces."""

from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.browser_trace import BrowserTraceEvent, BrowserTraceWriter
from bridge.run_artifacts import create_run_workspace
from teams._types import BridgeDeps
from teams.job_search._browser_profiles import browser_trace_writer_from_deps


def _workspace(tmp_path: Path):
    return create_run_workspace(
        tmp_path / "zone4-runs",
        session_id="s1",
        department="job_search",
        directive_id="dir-123",
        chief="job-search-chief",
        entropy="unit-test",
    )


def _manifest_artifacts(manifest_path: Path) -> list[dict[str, object]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = payload.get("artifacts")
    assert isinstance(artifacts, list)
    return artifacts


def test_append_event_writes_jsonl_and_manifest_entry(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    writer = BrowserTraceWriter(workspace.run_dir)

    writer.append_event(
        BrowserTraceEvent(
            ts="2026-05-21T18:10:01Z",
            agent="job-search-workday-specialist",
            action="click",
            target="Apply button",
            url="https://example.com/jobs/123",
            screenshot="screenshots/0001-click-apply.png",
            result="success",
        )
    )

    trace_path = workspace.run_dir / "browser-trace.jsonl"
    lines = trace_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row == {
        "action": "click",
        "agent": "job-search-workday-specialist",
        "result": "success",
        "screenshot": "screenshots/0001-click-apply.png",
        "target": "Apply button",
        "ts": "2026-05-21T18:10:01Z",
        "url": "https://example.com/jobs/123",
    }

    artifacts = _manifest_artifacts(workspace.manifest_path)
    assert [entry["path"] for entry in artifacts] == ["browser-trace.jsonl"]
    assert artifacts[0]["kind"] == "browser_trace"
    assert artifacts[0]["agent"] == "job-search-workday-specialist"


def test_add_screenshot_writes_under_screenshots_and_updates_manifest(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    writer = BrowserTraceWriter(workspace.run_dir)

    relpath = writer.add_screenshot(
        "screenshots/0001-click-apply.png",
        b"png bytes",
        agent="job-search-workday-specialist",
    )

    assert relpath == "screenshots/0001-click-apply.png"
    assert (workspace.run_dir / relpath).read_bytes() == b"png bytes"

    artifacts = _manifest_artifacts(workspace.manifest_path)
    assert [entry["path"] for entry in artifacts] == [
        "screenshots/0001-click-apply.png"
    ]
    assert artifacts[0]["kind"] == "browser_screenshot"
    assert artifacts[0]["bytes"] == len(b"png bytes")


@pytest.mark.parametrize(
    "screenshot",
    [
        "/tmp/outside.png",
        "../outside.png",
        "screenshots/../outside.png",
        "not-screenshots/outside.png",
        "",
    ],
)
def test_add_screenshot_rejects_paths_outside_screenshot_dir(
    tmp_path: Path,
    screenshot: str,
) -> None:
    workspace = _workspace(tmp_path)
    writer = BrowserTraceWriter(workspace.run_dir)

    with pytest.raises(ValueError, match="screenshots"):
        writer.add_screenshot(
            screenshot,
            b"png bytes",
            agent="job-search-workday-specialist",
        )

    assert _manifest_artifacts(workspace.manifest_path) == []


@pytest.mark.parametrize(
    "screenshot",
    [
        "/tmp/outside.png",
        "../outside.png",
        "screenshots/../outside.png",
        "not-screenshots/outside.png",
    ],
)
def test_append_event_rejects_invalid_screenshot_reference(
    tmp_path: Path,
    screenshot: str,
) -> None:
    workspace = _workspace(tmp_path)
    writer = BrowserTraceWriter(workspace.run_dir)

    with pytest.raises(ValueError, match="screenshots"):
        writer.append_event(
            BrowserTraceEvent(
                ts="2026-05-21T18:10:01Z",
                agent="job-search-workday-specialist",
                action="click",
                target="Apply button",
                url="https://example.com/jobs/123",
                screenshot=screenshot,
                result="success",
            )
        )

    assert not (workspace.run_dir / "browser-trace.jsonl").exists()
    assert _manifest_artifacts(workspace.manifest_path) == []


def test_trace_writer_requires_manifest_before_touching_disk(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-without-manifest"
    writer = BrowserTraceWriter(run_dir)

    with pytest.raises(RuntimeError, match="manifest"):
        writer.append_event(
            BrowserTraceEvent(
                ts="2026-05-21T18:10:01Z",
                agent="job-search-workday-specialist",
                action="navigate",
                target="Job listing",
                url="https://example.com/jobs/123",
                screenshot=None,
                result="success",
            )
        )

    with pytest.raises(RuntimeError, match="manifest"):
        writer.add_screenshot(
            "screenshots/0001-page.png",
            b"png bytes",
            agent="job-search-workday-specialist",
        )

    assert not (run_dir / "browser-trace.jsonl").exists()
    assert not (run_dir / "screenshots").exists()


def test_bridge_deps_can_carry_browser_trace_writer(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    writer = BrowserTraceWriter(workspace.run_dir)

    deps = BridgeDeps(
        session_id="s1",
        department="job_search",
        operator_id="op",
        memory_store=AsyncMock(),
        event_bus=MagicMock(),
        trust_manager=MagicMock(),
        cost_tracker=MagicMock(),
        knowledge_search=AsyncMock(return_value=[]),
        browser_trace=writer,
    )

    assert browser_trace_writer_from_deps(deps) is writer


def test_browser_trace_writer_can_be_derived_from_run_artifact_dir(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    deps = SimpleNamespace(browser_trace=None, run_artifact_dir=workspace.run_dir)

    writer = browser_trace_writer_from_deps(deps)

    assert isinstance(writer, BrowserTraceWriter)
    assert writer.trace_path == workspace.run_dir / "browser-trace.jsonl"
