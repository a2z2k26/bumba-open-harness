"""Helpers for public service-state inventory surfaces."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from .runner import SERVICE_ALIASES, SERVICE_MAP

_STATE_FILE_ALIASES: dict[str, str] = {
    "prebrief": "meeting_prebrief",
}
_EXTRA_STATE_NAMES: frozenset[str] = frozenset({
    "mcp_monitor",
})


def _canonical_state_name(name: str) -> str:
    if name in SERVICE_ALIASES:
        return SERVICE_ALIASES[name]
    normalized = name.replace("-", "_")
    return _STATE_FILE_ALIASES.get(normalized, normalized)


def is_known_service_state_name(name: str) -> bool:
    """Return True when a ``*-state.json`` file belongs on service surfaces."""
    canonical = _canonical_state_name(name)
    return canonical in SERVICE_MAP or canonical in _EXTRA_STATE_NAMES


def iter_known_service_state_files(service_dir: Path) -> Iterator[tuple[str, Path]]:
    """Yield ``(canonical_name, path)`` for known service state files only.

    Both the public name and the deduplicated winner use the canonical
    (underscore) form.  When two files map to the same canonical name — e.g.
    ``knowledge-review-state.json`` and ``knowledge_review-state.json`` — only
    the file whose state data contains the more recent ``last_run`` timestamp is
    yielded.  This prevents ghost duplicate entries in health surfaces such as
    ``/health``.
    """
    # First pass: collect all candidates keyed by canonical name.
    candidates: dict[str, list[Path]] = {}
    for state_file in sorted(service_dir.glob("*-state.json")):
        stem = state_file.name.removesuffix("-state.json")
        if not is_known_service_state_name(stem):
            continue
        canonical = _canonical_state_name(stem)
        candidates.setdefault(canonical, []).append(state_file)

    # Second pass: for each canonical name pick the file with the most recent
    # last_run, falling back to the lexicographically first path when both are
    # absent or unreadable.
    for canonical_name, paths in sorted(candidates.items()):
        if len(paths) == 1:
            yield canonical_name, paths[0]
            continue

        best_path = paths[0]
        best_last_run: str | None = None
        for path in paths:
            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            last_run = data.get("last_run")
            if last_run is not None and (
                best_last_run is None or last_run > best_last_run
            ):
                best_last_run = last_run
                best_path = path

        yield canonical_name, best_path
