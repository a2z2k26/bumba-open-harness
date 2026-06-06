"""Browser and computer-use trace artifacts for Zone 4 run workspaces."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class BrowserTraceEvent:
    ts: str
    agent: str
    action: str
    target: str
    url: str | None
    screenshot: str | None
    result: str


class BrowserTraceWriter:
    """Append-only browser trace writer bound to one run workspace."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).expanduser()
        self._trace_path = self._root / "browser-trace.jsonl"
        self._manifest_path = self._root / "manifest.json"

    @property
    def trace_path(self) -> Path:
        return self._trace_path

    def append_event(self, event: BrowserTraceEvent) -> None:
        """Append one browser action event to JSONL and expose it in manifest."""
        self._require_manifest()
        if event.screenshot is not None:
            _safe_screenshot_path(event.screenshot)
        self._trace_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(asdict(event), sort_keys=True)
        with self._trace_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        self._upsert_manifest_artifact(
            self._trace_path,
            relative_path="browser-trace.jsonl",
            kind="browser_trace",
            agent=event.agent,
        )

    def add_screenshot(
        self,
        relative_path: str,
        content: bytes,
        *,
        agent: str,
    ) -> str:
        """Write a screenshot under screenshots/ and expose it in manifest."""
        self._require_manifest()
        screenshot_path = _safe_screenshot_path(relative_path)
        absolute_path = self._root / screenshot_path
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        absolute_path.write_bytes(content)
        rel = screenshot_path.as_posix()
        self._upsert_manifest_artifact(
            absolute_path,
            relative_path=rel,
            kind="browser_screenshot",
            agent=agent,
        )
        return rel

    def _require_manifest(self) -> None:
        if not self._manifest_path.exists():
            raise RuntimeError(
                f"run artifact manifest is not available: {self._manifest_path}"
            )

    def _upsert_manifest_artifact(
        self,
        artifact_path: Path,
        *,
        relative_path: str,
        kind: str,
        agent: str,
    ) -> None:
        payload = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        artifacts = payload.get("artifacts") or []
        if not isinstance(artifacts, list):
            artifacts = []
        artifacts = [
            entry
            for entry in artifacts
            if not (
                isinstance(entry, dict)
                and entry.get("path") == relative_path
            )
        ]
        raw = artifact_path.read_bytes()
        artifacts.append(
            {
                "agent": agent,
                "bytes": len(raw),
                "kind": kind,
                "path": relative_path,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        payload["artifacts"] = artifacts
        self._manifest_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _safe_screenshot_path(value: str) -> Path:
    path = Path(value)
    if (
        not value.strip()
        or path.is_absolute()
        or ".." in path.parts
        or len(path.parts) < 2
        or path.parts[0] != "screenshots"
    ):
        raise ValueError(
            "screenshot path must be a relative path inside screenshots/"
        )
    return path
