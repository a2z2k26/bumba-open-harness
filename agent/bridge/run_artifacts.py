"""Zone 4 run artifact workspace and manifest primitives."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
CHECKPOINT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CheckpointSpecialist:
    name: str
    success: bool
    output_sha256: str
    error: str | None


@dataclass(frozen=True)
class CheckpointRecord:
    schema_version: int
    run_id: str
    department: str
    chief: str | None
    task: str
    directive_id: str | None
    checkpoint_at_utc: str
    failure_class: str | None
    resumable: bool
    completed_specialists: tuple[CheckpointSpecialist, ...]
    message_history_ref: str | None
    attempt: int


@dataclass(frozen=True)
class ArtifactEntry:
    path: str
    kind: str
    agent: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class RunManifest:
    schema_version: int
    run_id: str
    session_id: str
    department: str
    directive_id: str | None
    started_at_utc: str
    completed_at_utc: str | None = None
    chief: str | None = None
    status: str = "running"
    artifacts: tuple[ArtifactEntry, ...] = ()
    surfaces: tuple[str, ...] = ()
    telemetry: tuple[tuple[str, str], ...] = ()
    project_root: str | None = None


@dataclass(frozen=True)
class RunWorkspace:
    run_id: str
    run_dir: Path
    manifest_path: Path
    manifest: RunManifest


def utc_timestamp(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_run_id(
    department: str,
    *,
    now: datetime | None = None,
    entropy: str | None = None,
) -> str:
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    stamp = dt.strftime("%Y%m%d-%H%M%S")
    slug = _slug(department)
    token = entropy or uuid.uuid4().hex
    suffix = hashlib.sha256(
        f"{slug}:{stamp}:{token}".encode("utf-8")
    ).hexdigest()[:6]
    return f"run-{stamp}-{slug}-{suffix}"


def create_run_workspace(
    artifact_root: Path | str,
    *,
    session_id: str,
    department: str,
    directive_id: str | None,
    chief: str | None,
    now: datetime | None = None,
    entropy: str | None = None,
    project_root: Path | str | None = None,
) -> RunWorkspace:
    started = now or datetime.now(timezone.utc)
    run_id = new_run_id(department, now=started, entropy=entropy)
    run_dir = Path(artifact_root).expanduser() / run_id
    manifest = RunManifest(
        schema_version=SCHEMA_VERSION,
        run_id=run_id,
        session_id=session_id,
        department=department,
        directive_id=directive_id,
        started_at_utc=utc_timestamp(started),
        chief=chief,
        project_root=str(Path(project_root).expanduser()) if project_root else None,
    )
    manifest_path = write_manifest(run_dir, manifest)
    return RunWorkspace(
        run_id=run_id,
        run_dir=run_dir,
        manifest_path=manifest_path,
        manifest=manifest,
    )


def write_manifest(root: Path | str, manifest: RunManifest) -> Path:
    run_dir = Path(root).expanduser()
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "manifest.json"
    path.write_text(
        json.dumps(_manifest_payload(manifest), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def append_manifest_artifact(
    root: Path | str,
    entry: ArtifactEntry,
) -> Path:
    run_dir = Path(root).expanduser()
    path = run_dir / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    artifacts = list(payload.get("artifacts") or [])
    artifacts.append(_artifact_payload(entry))
    payload["artifacts"] = artifacts
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def finalize_run_manifest(
    root: Path | str,
    *,
    status: str,
    completed_at_utc: str | None = None,
    surfaces: tuple[str, ...] = (),
    telemetry: tuple[tuple[str, str], ...] = (),
) -> Path:
    run_dir = Path(root).expanduser()
    path = run_dir / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["status"] = status
    payload["completed_at_utc"] = completed_at_utc or utc_timestamp()
    if surfaces:
        payload["surfaces"] = list(surfaces)
    if telemetry:
        payload["telemetry"] = dict(telemetry)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def write_artifact(
    run_dir: Path | str,
    relative_path: str,
    content: str | bytes,
    *,
    kind: str,
    agent: str,
) -> ArtifactEntry:
    artifact_path = _safe_relative_path(relative_path)
    payload = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    absolute_path = Path(run_dir).expanduser() / artifact_path
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    absolute_path.write_bytes(payload)
    return ArtifactEntry(
        path=artifact_path.as_posix(),
        kind=kind,
        agent=agent,
        bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def write_checkpoint(run_dir: Path | str, record: CheckpointRecord) -> Path:
    run_path = Path(run_dir).expanduser()
    run_path.mkdir(parents=True, exist_ok=True)
    path = run_path / "checkpoint.json"
    path.write_text(
        json.dumps(_checkpoint_payload(record), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def load_checkpoint(run_dir: Path | str) -> CheckpointRecord | None:
    path = Path(run_dir).expanduser() / "checkpoint.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("checkpoint at %s is unreadable: %s", path, exc)
        return None
    if not isinstance(payload, dict):
        logger.warning("checkpoint at %s is not a JSON object", path)
        return None
    schema_version = payload.get("schema_version")
    if schema_version != CHECKPOINT_SCHEMA_VERSION:
        logger.warning(
            "checkpoint at %s has schema_version %r, expected %r",
            path,
            schema_version,
            CHECKPOINT_SCHEMA_VERSION,
        )
        return None
    try:
        specialists = tuple(
            CheckpointSpecialist(
                name=item["name"],
                success=item["success"],
                output_sha256=item["output_sha256"],
                error=item["error"],
            )
            for item in payload["completed_specialists"]
        )
        return CheckpointRecord(
            schema_version=schema_version,
            run_id=payload["run_id"],
            department=payload["department"],
            chief=payload["chief"],
            task=payload["task"],
            directive_id=payload["directive_id"],
            checkpoint_at_utc=payload["checkpoint_at_utc"],
            failure_class=payload["failure_class"],
            resumable=payload["resumable"],
            completed_specialists=specialists,
            message_history_ref=payload["message_history_ref"],
            attempt=payload["attempt"],
        )
    except (KeyError, TypeError) as exc:
        logger.warning("checkpoint at %s is missing fields: %s", path, exc)
        return None


MESSAGE_HISTORY_FILENAME = "message_history.json"


def serialize_message_history(
    run_dir: Path | str,
    run_result: object | None,
) -> str | None:
    """Persist a PydanticAI run result's message history to disk.

    Writes ``<run_dir>/message_history.json`` using the run result's
    ``all_messages_json()`` (PydanticAI returns ``bytes``). Returns the
    relative ref ``'message_history.json'`` on success, or ``None`` when
    ``run_result`` is ``None``. Best-effort: any serialization failure is
    logged and ``None`` is returned so a checkpoint write never breaks a run.
    """
    if run_result is None:
        return None

    dump = getattr(run_result, "all_messages_json", None)
    if not callable(dump):
        logger.warning(
            "run_result %r has no all_messages_json(); skipping history",
            type(run_result).__name__,
        )
        return None

    try:
        payload = dump()
        data = payload if isinstance(payload, (bytes, bytearray)) else str(payload).encode("utf-8")
        run_path = Path(run_dir).expanduser()
        run_path.mkdir(parents=True, exist_ok=True)
        (run_path / MESSAGE_HISTORY_FILENAME).write_bytes(bytes(data))
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("message history serialization failed: %s", exc)
        return None

    return MESSAGE_HISTORY_FILENAME


def load_message_history(
    run_dir: Path | str,
    ref: str | None = MESSAGE_HISTORY_FILENAME,
) -> list[object] | None:
    """Reload a serialized message history into a PydanticAI message list.

    The inverse of :func:`serialize_message_history`: reads
    ``<run_dir>/<ref>`` (default ``message_history.json``) and validates it
    through PydanticAI's ``ModelMessagesTypeAdapter`` so the result is a valid
    ``list[ModelMessage]`` suitable for the ``message_history`` kwarg on
    ``Agent.run``. Returns ``None`` when ``ref`` is falsy, the file is absent,
    or deserialization fails — best-effort, so a resume that can't reload its
    transcript starts fresh rather than crashing.
    """
    if not ref:
        return None
    path = Path(run_dir).expanduser() / ref
    if not path.exists():
        return None
    try:
        from pydantic_ai.messages import ModelMessagesTypeAdapter

        return list(ModelMessagesTypeAdapter.validate_json(path.read_bytes()))
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("message history at %s failed to load: %s", path, exc)
        return None


def build_checkpoint_record(
    result: object,
    run_relay: object,
    *,
    task: str,
    attempt: int,
    run_result: object | None,
    chief: str | None = None,
    directive_id: str | None = None,
    now: datetime | None = None,
) -> CheckpointRecord:
    """Assemble a CheckpointRecord from a finished (or failed) team run.

    ``failure_class`` is resolved via the post-run policy helper; ``resumable``
    is True iff that class is in ``RECOVERABLE_FAILURE_CLASSES``. Every
    EmployeeResult — success AND failure — is carried in
    ``completed_specialists`` with its success flag, error, and an
    output_sha256 hashed from the specialist's output text.

    The ``message_history_ref`` is left None here; callers serialize the
    history separately (``serialize_message_history``) and may set the ref via
    dataclasses.replace, keeping this builder pure of disk I/O.
    """
    from teams._post_run import (
        RECOVERABLE_FAILURE_CLASSES,
        failure_class_from_result,
    )

    failure_class = failure_class_from_result(
        result, getattr(result, "telemetry", None)
    )
    resumable = failure_class in RECOVERABLE_FAILURE_CLASSES

    specialists = tuple(
        CheckpointSpecialist(
            name=employee.employee_name,
            success=bool(employee.success),
            output_sha256=hashlib.sha256(
                (employee.output or "").encode("utf-8")
            ).hexdigest(),
            error=employee.error,
        )
        for employee in getattr(result, "employee_results", ()) or ()
    )

    return CheckpointRecord(
        schema_version=CHECKPOINT_SCHEMA_VERSION,
        run_id=getattr(run_relay, "run_id", ""),
        department=getattr(result, "department", ""),
        chief=chief,
        task=task,
        directive_id=directive_id,
        checkpoint_at_utc=utc_timestamp(now),
        failure_class=failure_class,
        resumable=resumable,
        completed_specialists=specialists,
        message_history_ref=None,
        attempt=attempt,
    )


def _manifest_payload(manifest: RunManifest) -> dict[str, object]:
    return {
        "schema_version": manifest.schema_version,
        "run_id": manifest.run_id,
        "session_id": manifest.session_id,
        "department": manifest.department,
        "directive_id": manifest.directive_id,
        "started_at_utc": manifest.started_at_utc,
        "completed_at_utc": manifest.completed_at_utc,
        "chief": manifest.chief,
        "status": manifest.status,
        "artifacts": [_artifact_payload(entry) for entry in manifest.artifacts],
        "surfaces": list(manifest.surfaces),
        "telemetry": dict(manifest.telemetry),
        "project_root": manifest.project_root,
    }


def _artifact_payload(entry: ArtifactEntry) -> dict[str, object]:
    return {
        "path": entry.path,
        "kind": entry.kind,
        "agent": entry.agent,
        "bytes": entry.bytes,
        "sha256": entry.sha256,
    }


def _checkpoint_payload(record: CheckpointRecord) -> dict[str, object]:
    return {
        "schema_version": record.schema_version,
        "run_id": record.run_id,
        "department": record.department,
        "chief": record.chief,
        "task": record.task,
        "directive_id": record.directive_id,
        "checkpoint_at_utc": record.checkpoint_at_utc,
        "failure_class": record.failure_class,
        "resumable": record.resumable,
        "completed_specialists": [
            _specialist_payload(specialist)
            for specialist in record.completed_specialists
        ],
        "message_history_ref": record.message_history_ref,
        "attempt": record.attempt,
    }


def _specialist_payload(specialist: CheckpointSpecialist) -> dict[str, object]:
    return {
        "name": specialist.name,
        "success": specialist.success,
        "output_sha256": specialist.output_sha256,
        "error": specialist.error,
    }


def _safe_relative_path(relative_path: str) -> Path:
    path = Path(relative_path)
    if not relative_path.strip() or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"invalid relative artifact path: {relative_path!r}")
    return path


def _slug(value: str) -> str:
    allowed = []
    for char in value.lower():
        if char.isalnum():
            allowed.append(char)
        elif char in {"-", "_"}:
            allowed.append(char)
        elif char.isspace():
            allowed.append("-")
    slug = "".join(allowed).strip("-_")
    return slug or "unknown"
