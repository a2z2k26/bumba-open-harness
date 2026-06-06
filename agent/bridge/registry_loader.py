"""Load + validate agent/config/registry/ entries.

Per E-O6: YAML at agent/config/registry/{events,metrics,actions}/*.yaml.
Each top-level key in a YAML file is one entry. Validation failures are
collected in RegistryIndex.errors; loader does NOT raise — registry is
a contract, not a hard runtime gate (E2.6 is the CI gate).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

import yaml
from pydantic import ValidationError

from config.registry._schema import (
    ActionEntry,
    EventEntry,
    MetricEntry,
)

log = logging.getLogger(__name__)

_EntryModel = Union[EventEntry, MetricEntry, ActionEntry]


@dataclass(frozen=True)
class RegistryEntryError:
    """A single validation or parse failure recorded during load."""

    file: Path
    entry_key: str
    message: str


@dataclass
class RegistryIndex:
    """All loaded registry entries plus any validation errors."""

    events: list[EventEntry] = field(default_factory=list)
    metrics: list[MetricEntry] = field(default_factory=list)
    actions: list[ActionEntry] = field(default_factory=list)
    errors: list[RegistryEntryError] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Query helpers                                                        #
    # ------------------------------------------------------------------ #

    def find_event_by_type(self, event_type: str) -> EventEntry | None:
        """Return the first EventEntry whose event_type matches, or None."""
        for e in self.events:
            if e.event_type == event_type:
                return e
        return None

    def find_metric_by_name(self, name: str) -> MetricEntry | None:
        """Return the first MetricEntry whose metric_name matches, or None."""
        for m in self.metrics:
            if m.metric_name == name:
                return m
        return None

    def find_action_by_path(self, method: str, path: str) -> ActionEntry | None:
        """Return the first ActionEntry matching method + path, or None."""
        for a in self.actions:
            if a.method == method and a.path == path:
                return a
        return None


class RegistryLoader:
    """Walk agent/config/registry/ and return a validated RegistryIndex.

    Usage::

        from pathlib import Path
        from bridge.registry_loader import RegistryLoader

        index = RegistryLoader().load_all(Path("agent/config/registry"))
    """

    KIND_DIRS: dict[str, type[_EntryModel]] = {
        "events": EventEntry,  # type: ignore[dict-item]
        "metrics": MetricEntry,  # type: ignore[dict-item]
        "actions": ActionEntry,  # type: ignore[dict-item]
    }

    def load_all(self, root: Path) -> RegistryIndex:
        """Load all YAML files from root/{events,metrics,actions}/*.yaml.

        Returns a RegistryIndex. Validation errors are collected in
        RegistryIndex.errors and never raised so boot is not blocked.
        """
        index = RegistryIndex()
        for kind, model_cls in self.KIND_DIRS.items():
            kind_dir = root / kind
            if not kind_dir.exists():
                log.debug("registry: %s/ not found, skipping", kind)
                continue
            for yaml_file in sorted(kind_dir.glob("*.yaml")):
                self._load_file(yaml_file, model_cls, index, kind)
        return index

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _load_file(
        self,
        path: Path,
        model_cls: type[_EntryModel],
        index: RegistryIndex,
        kind: str,
    ) -> None:
        try:
            raw = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError as exc:
            index.errors.append(
                RegistryEntryError(
                    file=path,
                    entry_key="<file>",
                    message=str(exc),
                )
            )
            log.warning("registry: YAML parse error in %s: %s", path, exc)
            return

        if not isinstance(raw, dict):
            msg = "top-level YAML must be a mapping of entry-key → fields"
            index.errors.append(
                RegistryEntryError(file=path, entry_key="<file>", message=msg)
            )
            log.warning("registry: %s — %s", path, msg)
            return

        for entry_key, entry_fields in raw.items():
            if not isinstance(entry_fields, dict):
                msg = f"entry '{entry_key}' is not a mapping"
                index.errors.append(
                    RegistryEntryError(file=path, entry_key=entry_key, message=msg)
                )
                log.warning("registry: %s[%s] — %s", path.name, entry_key, msg)
                continue
            try:
                entry = model_cls(**entry_fields)
                getattr(index, kind).append(entry)
            except ValidationError as exc:
                index.errors.append(
                    RegistryEntryError(
                        file=path,
                        entry_key=entry_key,
                        message=str(exc),
                    )
                )
                log.warning(
                    "registry: validation error in %s[%s]: %s",
                    path.name,
                    entry_key,
                    exc,
                )
