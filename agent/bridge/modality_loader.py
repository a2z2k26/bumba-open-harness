"""Modality supplement loader for the Chameleon agent system.

Loads and manages modality-specific context supplements that get
injected into the agent's operating context based on active mode.
"""

from __future__ import annotations

import enum
import logging
from pathlib import Path

log = logging.getLogger(__name__)


class Modality(enum.Enum):
    """Agent operating modalities."""

    ENGINEER = "engineer"
    ORCHESTRATOR = "orchestrator"
    PA = "pa"
    COMMUNICATOR = "communicator"


# Orchestrator extends Engineer — loads both supplements
_EXTENDS: dict[Modality, list[Modality]] = {
    Modality.ORCHESTRATOR: [Modality.ENGINEER, Modality.ORCHESTRATOR],
}


class ModalityLoader:
    """Loads and manages modality supplement files.

    Each modality has a corresponding .md file in the modalities directory.
    When activated, the supplement content is made available for context injection.
    When deactivated or replaced, the previous supplement is removed.
    """

    def __init__(self, modalities_dir: Path, *, default: Modality | None = None) -> None:
        self._dir = modalities_dir
        self._active: Modality | None = None
        self._supplement: str = ""

        if default is not None:
            self.activate(default)

    @property
    def active_modality(self) -> Modality | None:
        return self._active

    @property
    def active_supplement(self) -> str:
        return self._supplement

    def load_supplement(self, modality: Modality) -> str:
        """Load a single modality supplement file. Returns empty string if missing."""
        path = self._dir / f"{modality.value}.md"
        if not path.exists():
            log.warning("Modality supplement not found: %s", path)
            return ""
        return path.read_text(encoding="utf-8")

    def activate(self, modality: Modality) -> None:
        """Activate a modality, loading its supplement(s).

        If the modality extends another (e.g., Orchestrator extends Engineer),
        both supplements are loaded and concatenated.
        """
        chain = _EXTENDS.get(modality, [modality])
        parts: list[str] = []
        for m in chain:
            content = self.load_supplement(m)
            if content:
                parts.append(content)
        self._active = modality
        self._supplement = "\n\n".join(parts)
        log.info("Activated modality: %s", modality.value)

    def deactivate(self) -> None:
        """Deactivate the current modality, clearing the supplement."""
        prev = self._active
        self._active = None
        self._supplement = ""
        if prev is not None:
            log.info("Deactivated modality: %s", prev.value)


def load_for_intent(intent: str | None, modalities_dir: Path) -> str:
    """Load a modality supplement for a given intent string.

    Convenience function for one-shot preamble lookup.  Fails silently so
    callers never need to guard against missing supplement files or unknown
    intent strings.

    Args:
        intent: Intent value string (e.g. ``"engineer"``, ``"communicator"``).
                Accepts any value in ``Modality`` enum; unknown strings return ``""``.
        modalities_dir: Directory that contains the ``<modality>.md`` files.

    Returns:
        Supplement text, or empty string if intent is None / unknown / file missing.
    """
    if not intent:
        return ""
    try:
        modality = Modality(intent)
        loader = ModalityLoader(modalities_dir)
        loader.activate(modality)
        return loader.active_supplement or ""
    except (ValueError, Exception):
        return ""
