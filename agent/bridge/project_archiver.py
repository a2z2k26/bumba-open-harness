"""Project archival workflow."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArchiveResult:
    success: bool = False
    archived_files: int = 0
    reason: str = ""


class ProjectArchiver:
    def __init__(self, *, data_dir: Path, projects_dir: Path) -> None:
        self._data_dir = data_dir
        self._projects_dir = projects_dir

    def archive(self, project_name: str, *, purge_working: bool = False) -> ArchiveResult:
        project_file = self._projects_dir / f"{project_name}.yaml"
        if not project_file.exists():
            return ArchiveResult(success=False, reason=f"Project file not found: {project_file}")

        archive_dir = self._data_dir / "archive" / project_name
        archive_dir.mkdir(parents=True, exist_ok=True)

        archived_count = 0

        wo_dir = self._data_dir / "workorder-outputs"
        if wo_dir.exists():
            archive_wo = archive_dir / "workorder-outputs"
            archive_wo.mkdir(exist_ok=True)
            for item in wo_dir.iterdir():
                if item.is_dir():
                    dest = archive_wo / item.name
                    if not dest.exists():
                        shutil.copytree(item, dest)
                        archived_count += 1

        progress_dir = self._data_dir / "project_progress"
        progress_file = progress_dir / f"{project_name}-progress.json"
        if progress_file.exists():
            shutil.copy2(progress_file, archive_dir / "progress.json")
            archived_count += 1

        manifest = {
            "project": project_name,
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "files_archived": archived_count,
        }
        (archive_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        archived_count += 1

        content = project_file.read_text(encoding="utf-8")
        current_status = self._extract_status(content)
        if current_status:
            updated = content.replace(f"status: {current_status}", "status: archived")
        else:
            updated = content
        project_file.write_text(updated, encoding="utf-8")

        if purge_working and wo_dir.exists():
            for item in wo_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)

        log.info("Archived project '%s': %d files to %s", project_name, archived_count, archive_dir)
        return ArchiveResult(success=True, archived_files=archived_count)

    @staticmethod
    def _extract_status(yaml_content: str) -> str:
        for line in yaml_content.split("\n"):
            if line.startswith("status:"):
                return line.split(":", 1)[1].strip()
        return ""
