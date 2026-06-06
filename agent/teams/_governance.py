"""Zone 4 per-agent governance bundle loading."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

GOVERNANCE_FILES = ("CLAUDE.md", "SOUL.md", "ARTIFACTS.md")
GOVERNANCE_LINE_CAP = 240
_SECTION_SEPARATOR = "\n\n---\n\n"


def resolve_governance_bundle_path(
    root: Path | str,
    *,
    department: str,
    agent_name: str,
    zone: int,
) -> Path:
    return (
        Path(root).expanduser()
        / f"zone{zone}"
        / department
        / agent_name
    )


def load_governance_bundle(
    root: Path | str,
    *,
    department: str,
    agent_name: str,
    zone: int,
    line_cap: int = GOVERNANCE_LINE_CAP,
) -> str:
    """Load a compact governance bundle for one Zone 4 agent."""
    bundle_dir = resolve_governance_bundle_path(
        root,
        department=department,
        agent_name=agent_name,
        zone=zone,
    )
    if not bundle_dir.exists():
        log.info(
            "governance.bundle_missing zone=%s department=%s agent=%s path=%s",
            zone,
            department,
            agent_name,
            bundle_dir,
        )
        return ""

    sections: list[str] = []
    for filename in GOVERNANCE_FILES:
        path = bundle_dir / filename
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8").strip()
        if content:
            sections.append(content)

    text = _SECTION_SEPARATOR.join(sections)
    if not text:
        return ""

    lines = text.splitlines()
    if len(lines) <= line_cap:
        return text

    log.warning(
        "governance.bundle_over_cap zone=%s department=%s agent=%s lines=%d cap=%d",
        zone,
        department,
        agent_name,
        len(lines),
        line_cap,
    )
    return "\n".join(lines[:line_cap])
