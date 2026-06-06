"""S01 sprint contract: no code under agent/ imports from bridge.orchestration."""
from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENT_ROOT = REPO_ROOT  # this test file lives at agent/tests/
ORCH_IMPORT_RE = re.compile(r"^\s*from\s+bridge\.orchestration\b|\s+import\s+bridge\.orchestration\b")


def _collect_python_files() -> list[pathlib.Path]:
    exclude = {"__pycache__", ".worktrees", ".venv"}
    return [
        p for p in AGENT_ROOT.rglob("*.py")
        if not any(part in exclude for part in p.parts)
    ]


def test_no_orchestration_imports_anywhere():
    offenders: list[tuple[str, int, str]] = []
    for path in _collect_python_files():
        # skip the test file itself
        if path.name == "test_z3_s01_no_orchestration_imports.py":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            if ORCH_IMPORT_RE.search(line):
                offenders.append((str(path.relative_to(AGENT_ROOT)), lineno, line.rstrip()))
    assert not offenders, (
        "The following files still import from bridge.orchestration:\n"
        + "\n".join(f"  {p}:{ln} {text}" for p, ln, text in offenders)
    )


def test_consolidated_modules_importable_at_root():
    """After collapse, each moved module resolves at bridge.<name>."""
    import importlib
    for modname in (
        "bridge.agent_lifecycle",
        "bridge.command_router",
        "bridge.dependency_manager",
        "bridge.error_recovery",
        "bridge.lifecycle_manager",
        "bridge.modality_detector",
        "bridge.model_assignments",
        "bridge.routing_cascade",
        "bridge.token_cost",
        "bridge.verification",
    ):
        importlib.import_module(modname)  # raises ModuleNotFoundError if missing
