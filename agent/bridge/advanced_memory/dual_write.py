"""Dual-write pipeline — write to primary (SQLite/FTS5) and optional secondary stores.

Sprint Mem-4 — Memory-Tier Architecture epic (#1845, Phase A foundation,
final). Retrofit of a previously DORMANT module: the original ``write()``
signature targeted a fictitious ``(id, category, content, source, metadata,
created_at)`` schema that does not match the live ``knowledge`` table. The
module had no production callers (verified by grep at retrofit time), so the
signature change is safe.

What changed
------------
* ``write()`` is now keyword-only and takes ``key`` (the real primary key on
  the ``knowledge`` table) plus the tier and the resolved destinations tuple
  from the ``TierPolicy``.
* The pipeline holds ``destinations: dict[str, DestinationProtocol]`` keyed
  by destination name (``"sqlite"``, ``"second_brain"``, ``"vector"``). The
  primary destination is always the FIRST entry in the call-site's
  ``destinations`` tuple. The default policies in ``bridge.memory_tiers``
  put ``"sqlite"`` first for every tier.
* The :class:`DualWriteResult` dataclass is unchanged in shape but its
  ``secondary_success`` field now collapses across all secondary destinations
  (True iff at least one secondary destination's write succeeded). The
  ``error`` field carries the first secondary error string seen.

Failure model
-------------
* **Primary** write is MANDATORY. A failure raises the underlying exception.
  This matches the original module's contract and the Mem-4 operator
  decision (Q-failure-model).
* **Secondary** writes are BEST-EFFORT. Each is wrapped in try/except;
  failures log at WARNING and are recorded on the result. The pipeline never
  raises on a secondary failure.

Order
-----
Destinations are processed in the order supplied by the caller — the first
entry is treated as primary, subsequent entries as secondaries. This matches
the natural reading order of the ``TierPolicy.destinations`` tuples in
``bridge.memory_tiers``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .destinations import DestinationProtocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DualWriteResult:
    """Result of a dual-write operation.

    ``primary_success`` is always True on return — a False primary success
    would have raised before reaching the result. ``secondary_success`` is
    True iff at least one secondary destination's write succeeded (it
    collapses across the secondary list; the individual destinations'
    successes can be reconstructed from logs).
    """

    primary_success: bool
    secondary_success: bool
    primary_id: str = ""
    secondary_id: str = ""
    error: str = ""


class DualWritePipeline:
    """Writes memory entries to a primary store and zero-or-more secondary stores.

    The primary store (always SQLite/FTS5 in default policies) is mandatory —
    failures raise exceptions. Secondary stores (second_brain, vector) are
    best-effort — failures are logged but do not propagate.

    Destinations are resolved by name from the ``destinations`` dict passed
    at construction time. The caller supplies the ordered ``destinations``
    tuple on each ``write()`` call (from the matching ``TierPolicy``); the
    first entry is treated as primary, the rest as secondaries.
    """

    def __init__(self, destinations: dict[str, DestinationProtocol]) -> None:
        """Initialise the pipeline with a name → destination map.

        Args:
            destinations: Mapping from destination name (e.g. ``"sqlite"``)
                to the adapter implementing :class:`DestinationProtocol`.
                Names must match the values in ``TierPolicy.destinations``.
        """
        self._destinations = destinations

    async def write(
        self,
        *,
        key: str,
        value: str,
        tags: str = "",
        source: str = "",
        category: str = "reference",
        tier: str,
        destinations: tuple[str, ...],
        metadata: dict[str, Any] | None = None,
    ) -> DualWriteResult:
        """Write a memory entry to primary and (optionally) secondary stores.

        The first name in ``destinations`` is treated as the primary; the rest
        are best-effort secondaries.

        Args:
            key: Primary key on the ``knowledge`` table.
            value: Entry body (the memory content).
            tags: Comma-separated tag string (matches the schema column).
            source: Source label (``"operator"``, ``"agent"``, etc.).
            category: Knowledge category (``"preference"``, ``"decision"``, …).
            tier: Memory tier string value (``MemoryTier.<...>.value``).
            destinations: Ordered tuple of destination names. The first is
                primary; the rest are secondaries.
            metadata: Optional opaque metadata passed through to destinations.

        Returns:
            :class:`DualWriteResult` with status of both writes.

        Raises:
            ValueError: ``destinations`` is empty.
            KeyError: a name in ``destinations`` is not registered with this
                pipeline.
            Exception: any exception raised by the primary destination
                propagates unchanged.
        """
        if not destinations:
            raise ValueError("destinations must be non-empty")

        primary_name, *secondary_names = destinations

        primary = self._destinations.get(primary_name)
        if primary is None:
            raise KeyError(
                f"primary destination {primary_name!r} not registered with pipeline"
            )

        # Primary write — must succeed. Any exception propagates so callers
        # can react (and the WAL stays armed to retry).
        primary_id = await primary.write(
            key=key,
            value=value,
            tags=tags,
            source=source,
            category=category,
            tier=tier,
            metadata=metadata,
        )
        logger.info(
            "dual_write: primary=%s succeeded key=%s tier=%s",
            primary_name, key, tier,
        )

        # Secondary writes — best-effort. Each in its own try/except so one
        # failing destination does not skip the others.
        secondary_success = False
        secondary_id = ""
        error = ""

        for sec_name in secondary_names:
            sec = self._destinations.get(sec_name)
            if sec is None:
                # Mis-configured policy. Log + skip — don't break primary.
                msg = f"secondary destination {sec_name!r} not registered with pipeline"
                logger.warning("dual_write: %s (skipping)", msg)
                if not error:
                    error = msg
                continue
            try:
                sec_id = await sec.write(
                    key=key,
                    value=value,
                    tags=tags,
                    source=source,
                    category=category,
                    tier=tier,
                    metadata=metadata,
                )
                secondary_success = True
                if not secondary_id:
                    secondary_id = str(sec_id) if sec_id else ""
                logger.info(
                    "dual_write: secondary=%s succeeded key=%s",
                    sec_name, key,
                )
            except Exception as exc:
                if not error:
                    error = f"{sec_name}: {exc}"
                logger.warning(
                    "dual_write: secondary=%s failed (best-effort) key=%s: %s",
                    sec_name, key, exc,
                )

        return DualWriteResult(
            primary_success=True,
            secondary_success=secondary_success,
            primary_id=str(primary_id) if primary_id else "",
            secondary_id=secondary_id,
            error=error,
        )
