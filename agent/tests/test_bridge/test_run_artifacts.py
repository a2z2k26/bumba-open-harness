"""Zone 4 run artifact workspace and manifest primitives."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.config import BridgeConfig, load_config
from bridge.run_artifacts import (
    CHECKPOINT_SCHEMA_VERSION,
    ArtifactEntry,
    CheckpointRecord,
    CheckpointSpecialist,
    RunManifest,
    _checkpoint_payload,
    _specialist_payload,
    build_checkpoint_record,
    create_run_workspace,
    load_checkpoint,
    new_run_id,
    serialize_message_history,
    write_artifact,
    write_checkpoint,
    write_manifest,
)
from teams._types import BridgeDeps, EmployeeResult, TeamResult


def test_zone4_artifact_root_default_and_toml_mapping(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    default_root = Path(BridgeConfig().zone4_artifact_root)
    assert default_root == Path("/opt/bumba-harness/zone4-runs")
    assert not default_root.is_relative_to(repo_root)

    configured_root = tmp_path / "zone4-runs"
    toml = tmp_path / "bridge.toml"
    toml.write_text(
        f'[zone4]\nartifact_root = "{configured_root}"\n',
        encoding="utf-8",
    )

    config = load_config(toml, skip_secrets=True, skip_validation=True)

    assert config.zone4_artifact_root == str(configured_root)


def test_bridge_deps_from_app_threads_artifact_and_project_roots(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "zone4-runs"
    project_root = tmp_path / "target-project"
    app = SimpleNamespace(
        config=SimpleNamespace(
            data_dir=str(tmp_path / "data"),
            zone4_artifact_root=str(artifact_root),
        ),
        _config=SimpleNamespace(operator_discord_id="op-test"),
        memory=MagicMock(),
        knowledge_search=AsyncMock(return_value=[]),
        cost_tracker=MagicMock(),
        event_bus=MagicMock(),
        trust_manager=MagicMock(),
        _db=None,
        project_root=project_root,
    )

    deps = BridgeDeps.from_app(
        app,
        session_id="session-1",
        department="strategy",
    )

    assert deps.artifact_root == artifact_root
    assert deps.project_root == project_root


def test_write_manifest_creates_stable_json(tmp_path: Path) -> None:
    artifact = ArtifactEntry(
        path="specialists/strategy-business-analyst/result.md",
        kind="specialist_result",
        agent="strategy-business-analyst",
        bytes=12,
        sha256="9a0f3d7e8b2c14d5f6a7890b1c2d3e4f5061728394a5b6c7d8e9f00112233445",
    )
    manifest = RunManifest(
        schema_version=1,
        run_id="run-20260521-180610-strategy-a1b2c3",
        session_id="session-1",
        department="strategy",
        directive_id=None,
        started_at_utc="2026-05-21T18:06:10Z",
        completed_at_utc="2026-05-21T18:07:12Z",
        chief="strategy-product-chief",
        status="success",
        artifacts=(artifact,),
        surfaces=("surf-50a3f9729415",),
        telemetry=(
            ("fallback_model", "openrouter:z-ai/glm-5.1"),
            ("primary_model", "anthropic-oauth:claude-sonnet-4-5"),
        ),
    )

    path = write_manifest(tmp_path / "run", manifest)

    expected = {
        "artifacts": [
            {
                "agent": "strategy-business-analyst",
                "bytes": 12,
                "kind": "specialist_result",
                "path": "specialists/strategy-business-analyst/result.md",
                "sha256": artifact.sha256,
            }
        ],
        "chief": "strategy-product-chief",
        "completed_at_utc": "2026-05-21T18:07:12Z",
        "department": "strategy",
        "directive_id": None,
        "project_root": None,
        "run_id": "run-20260521-180610-strategy-a1b2c3",
        "schema_version": 1,
        "session_id": "session-1",
        "started_at_utc": "2026-05-21T18:06:10Z",
        "status": "success",
        "surfaces": ["surf-50a3f9729415"],
        "telemetry": {
            "fallback_model": "openrouter:z-ai/glm-5.1",
            "primary_model": "anthropic-oauth:claude-sonnet-4-5",
        },
    }
    expected_json = json.dumps(expected, indent=2, sort_keys=True) + "\n"

    assert json.loads(path.read_text(encoding="utf-8")) == expected
    assert path.read_text(encoding="utf-8") == expected_json


def test_write_artifact_records_hash_and_blocks_path_escape(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    content = "alpha\n"

    entry = write_artifact(
        run_dir,
        "specialists/strategy-business-analyst/result.md",
        content,
        kind="specialist_result",
        agent="strategy-business-analyst",
    )

    expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert entry.bytes == len(content.encode("utf-8"))
    assert entry.sha256 == expected_hash
    assert (run_dir / entry.path).read_text(encoding="utf-8") == content

    with pytest.raises(ValueError, match="relative artifact path"):
        write_artifact(run_dir, "../escape.md", "bad", kind="raw", agent="chief")


def test_create_run_workspace_uses_artifact_root_outside_repo(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    artifact_root = tmp_path / "zone4-runs"
    now = datetime(2026, 5, 21, 18, 6, 10, tzinfo=timezone.utc)
    expected_run_id = new_run_id("strategy", now=now, entropy="unit-test")

    workspace = create_run_workspace(
        artifact_root,
        session_id="a0ce891c",
        department="strategy",
        directive_id="dir-123",
        chief="strategy-product-chief",
        now=now,
        entropy="unit-test",
        project_root=repo_root,
    )

    assert workspace.run_id == expected_run_id
    assert workspace.run_dir == artifact_root / expected_run_id
    assert workspace.manifest_path == workspace.run_dir / "manifest.json"
    assert workspace.manifest_path.exists()
    assert not workspace.run_dir.resolve().is_relative_to(repo_root.resolve())
    payload = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    assert payload["project_root"] == str(repo_root)
    assert payload["status"] == "running"


def test_checkpoint_schema_version_constant() -> None:
    assert CHECKPOINT_SCHEMA_VERSION == 1


def test_checkpoint_specialist_payload() -> None:
    specialist = CheckpointSpecialist(
        name="backend-architect",
        success=True,
        output_sha256="a" * 64,
        error=None,
    )
    payload = _specialist_payload(specialist)

    assert payload == {
        "name": "backend-architect",
        "success": True,
        "output_sha256": "a" * 64,
        "error": None,
    }
    # JSON-serializable.
    assert json.loads(json.dumps(payload)) == payload


def test_checkpoint_record_payload_roundtrip() -> None:
    record = CheckpointRecord(
        schema_version=CHECKPOINT_SCHEMA_VERSION,
        run_id="run-20260603-strategy-abc123",
        department="strategy",
        chief="strategy-product-chief",
        task="draft the Q3 roadmap",
        directive_id="dir-123",
        checkpoint_at_utc="2026-06-03T12:00:00Z",
        failure_class="timeout",
        resumable=True,
        completed_specialists=(
            CheckpointSpecialist(
                name="market-researcher",
                success=True,
                output_sha256="b" * 64,
                error=None,
            ),
            CheckpointSpecialist(
                name="business-analyst",
                success=False,
                output_sha256="c" * 64,
                error="rate limited",
            ),
        ),
        message_history_ref="message_history.json",
        attempt=2,
    )

    payload = _checkpoint_payload(record)

    assert payload == {
        "schema_version": 1,
        "run_id": "run-20260603-strategy-abc123",
        "department": "strategy",
        "chief": "strategy-product-chief",
        "task": "draft the Q3 roadmap",
        "directive_id": "dir-123",
        "checkpoint_at_utc": "2026-06-03T12:00:00Z",
        "failure_class": "timeout",
        "resumable": True,
        "completed_specialists": [
            {
                "name": "market-researcher",
                "success": True,
                "output_sha256": "b" * 64,
                "error": None,
            },
            {
                "name": "business-analyst",
                "success": False,
                "output_sha256": "c" * 64,
                "error": "rate limited",
            },
        ],
        "message_history_ref": "message_history.json",
        "attempt": 2,
    }
    # dumps/loads roundtrip preserves the payload.
    assert json.loads(json.dumps(payload)) == payload


def _sample_checkpoint_record() -> CheckpointRecord:
    return CheckpointRecord(
        schema_version=CHECKPOINT_SCHEMA_VERSION,
        run_id="run-20260603-strategy-abc123",
        department="strategy",
        chief="strategy-product-chief",
        task="draft the Q3 roadmap",
        directive_id="dir-123",
        checkpoint_at_utc="2026-06-03T12:00:00Z",
        failure_class="timeout",
        resumable=True,
        completed_specialists=(
            CheckpointSpecialist(
                name="market-researcher",
                success=True,
                output_sha256="b" * 64,
                error=None,
            ),
        ),
        message_history_ref="message_history.json",
        attempt=2,
    )


def test_write_then_load_checkpoint(tmp_path: Path) -> None:
    record = _sample_checkpoint_record()

    path = write_checkpoint(tmp_path, record)

    assert path == tmp_path / "checkpoint.json"
    # write_manifest convention: sorted keys + trailing newline.
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert json.loads(text) == _checkpoint_payload(record)

    loaded = load_checkpoint(tmp_path)
    assert loaded == record


def test_load_checkpoint_missing_returns_none(tmp_path: Path) -> None:
    assert load_checkpoint(tmp_path) is None


def test_load_checkpoint_corrupt_returns_none(tmp_path: Path) -> None:
    (tmp_path / "checkpoint.json").write_text("{not json", encoding="utf-8")

    assert load_checkpoint(tmp_path) is None


def test_load_checkpoint_schema_mismatch_returns_none(tmp_path: Path) -> None:
    payload = _checkpoint_payload(_sample_checkpoint_record())
    payload["schema_version"] = CHECKPOINT_SCHEMA_VERSION + 1
    (tmp_path / "checkpoint.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    assert load_checkpoint(tmp_path) is None


# --- WS2.3: serialize_message_history + build_checkpoint_record ---


def _run_relay(run_id: str = "run-20260603-strategy-abc123") -> SimpleNamespace:
    """Stand-in for teams._team._RunRelayContext (only run_id is read)."""
    return SimpleNamespace(
        run_id=run_id,
        run_dir=Path("/tmp/zone4-runs") / run_id,
        manifest_path=Path("/tmp/zone4-runs") / run_id / "manifest.json",
        memory_ref=f"memory:zone4/strategy/{run_id}",
    )


def test_serialize_history_none_run_result(tmp_path: Path) -> None:
    assert serialize_message_history(tmp_path, None) is None
    assert not (tmp_path / "message_history.json").exists()


def test_serialize_history_writes_relative_ref(tmp_path: Path) -> None:
    run_result = SimpleNamespace(
        all_messages_json=lambda: b'[{"role": "user"}]'
    )

    ref = serialize_message_history(tmp_path, run_result)

    assert ref == "message_history.json"
    written = (tmp_path / "message_history.json").read_bytes()
    assert written == b'[{"role": "user"}]'


def test_build_record_resumable_for_timeout() -> None:
    # failure_class_from_result reads the low-cardinality class off telemetry;
    # a "timeout" run carries telemetry.failure_class == "timeout".
    result = TeamResult(
        department="strategy",
        manager_output="partial",
        employee_results=(),
        success=False,
        error="run exceeded timeout after 600s",
        telemetry=SimpleNamespace(failure_class="timeout"),
    )

    record = build_checkpoint_record(
        result,
        _run_relay(),
        task="draft the Q3 roadmap",
        attempt=2,
        run_result=None,
        chief="strategy-product-chief",
        directive_id="dir-123",
    )

    assert record.failure_class == "timeout"
    assert record.resumable is True
    assert record.run_id == "run-20260603-strategy-abc123"
    assert record.department == "strategy"
    assert record.chief == "strategy-product-chief"
    assert record.directive_id == "dir-123"
    assert record.task == "draft the Q3 roadmap"
    assert record.attempt == 2
    assert record.message_history_ref is None


def test_build_record_not_resumable_for_unknown_class() -> None:
    result = TeamResult(
        department="strategy",
        manager_output="done",
        employee_results=(),
        success=False,
        error="something unrecognized blew up",
    )

    record = build_checkpoint_record(
        result,
        _run_relay(),
        task="draft the Q3 roadmap",
        attempt=1,
        run_result=None,
    )

    assert record.failure_class is None
    assert record.resumable is False


def test_completed_specialists_carry_success_flag() -> None:
    result = TeamResult(
        department="strategy",
        manager_output="synth",
        employee_results=(
            EmployeeResult(
                employee_name="market-researcher",
                output="market analysis text",
                success=True,
            ),
            EmployeeResult(
                employee_name="business-analyst",
                output="",
                success=False,
                error="rate limited",
            ),
        ),
        success=False,
        error="timeout",
    )

    record = build_checkpoint_record(
        result,
        _run_relay(),
        task="draft the Q3 roadmap",
        attempt=1,
        run_result=None,
    )

    # BOTH success and failure specialists are carried, with the flag.
    assert len(record.completed_specialists) == 2
    by_name = {s.name: s for s in record.completed_specialists}

    assert by_name["market-researcher"].success is True
    assert by_name["market-researcher"].error is None
    assert by_name["market-researcher"].output_sha256 == hashlib.sha256(
        b"market analysis text"
    ).hexdigest()

    assert by_name["business-analyst"].success is False
    assert by_name["business-analyst"].error == "rate limited"
    assert by_name["business-analyst"].output_sha256 == hashlib.sha256(
        b""
    ).hexdigest()
