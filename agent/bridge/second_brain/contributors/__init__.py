"""Concrete second-brain contributors — Sprint 05.07 (issue #1015).

Wires three existing bridge subsystems into the
:class:`bridge.second_brain.contributor.SecondBrainContributor` Protocol
so they emit :class:`Contribution` objects into the operator's vault
``bumba-contributions/`` quarantine subtree.

Per ADR Decision 3 (signed 2026-05-01,
``agent/docs/architecture/second-brain.md``) — Bumba never writes to
canonical wiki pages directly. Hybrid quarantine:

- :class:`DailyLogContributor` mirrors append-only daily markdown logs
  into ``bumba-contributions/staging/daily-logs/{YYYY-MM-DD}.md``.
- :class:`ReflectionContributor` mirrors weekly reflections from the
  :class:`bridge.reflection.ReflectionStore` into
  ``bumba-contributions/staging/reflections/{YYYY-Www}.md``.
- :class:`ConsolidationContributor` emits curated consolidation digests
  from a per-run output directory into
  ``bumba-contributions/curated/consolidation/{YYYY-MM-DD}-digest.md``.

Each contributor is **idempotent** — repeated calls with the same
``since`` produce the same :class:`Contribution` list (sha256-stable
bodies). Source data missing → empty list (no exception).

Concept-only port — no third-party source copied
(``concept-only-no-license``; Karpathy gist informs the markdown shape
only).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from ..contributor import Contribution

if TYPE_CHECKING:  # pragma: no cover — typing only
    from bridge.reflection import ReflectionStore

logger = logging.getLogger(__name__)


# Quarantine subtree relpath prefixes (mirror wiki_repo constants but
# kept as module-local strings so the contributors package does not
# require wiki_repo to be importable in tests that only construct
# Contributions). Matches ``WikiRepo.STAGING_PREFIX`` / ``CURATED_PREFIX``.
_STAGING_DAILY_LOGS = "bumba-contributions/staging/daily-logs/"
_STAGING_REFLECTIONS = "bumba-contributions/staging/reflections/"
_CURATED_CONSOLIDATION = "bumba-contributions/curated/consolidation/"


def _parse_iso_since(since: Optional[str]) -> Optional[float]:
    """Parse an ISO8601 timestamp into a POSIX epoch seconds float.

    Returns ``None`` when ``since`` is ``None`` (full-sweep signal) or
    unparseable (defensive — treat malformed input as a full sweep so
    a partial filter never silently drops legitimate contributions).
    """
    if since is None:
        return None
    try:
        # ``datetime.fromisoformat`` accepts both naive and aware ISO
        # strings; we coerce naive into UTC for a stable epoch.
        dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("could not parse since=%r as ISO8601 — full sweep", since)
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _utc_now_iso() -> str:
    """Render ``datetime.now(UTC)`` in ISO8601 with explicit ``Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Pattern for daily-log filenames written by :class:`DailyLogWriter` —
# ``data/logs/YYYY/MM/YYYY-MM-DD.md``. We anchor on the basename only so
# the file walk is robust to absolute/relative roots.
_DAILY_LOG_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.md$")


class DailyLogContributor:
    """Mirror append-only daily markdown logs into the staging quarantine.

    ``DailyLogWriter`` (``bridge/daily_log.py``) writes one file per day
    at ``data/logs/YYYY/MM/YYYY-MM-DD.md``. This contributor walks that
    tree and emits one :class:`Contribution` per day-file, dropping the
    mirror under ``bumba-contributions/staging/daily-logs/{YYYY-MM-DD}.md``.

    Bodies are the raw daily-log markdown verbatim — provenance is
    advertised via the frontmatter that
    :meth:`bridge.second_brain.wiki_repo.WikiRepo.write` stamps on top.
    """

    contributor_name: str = "daily_log"

    def __init__(self, *, daily_log_root: Path, session_id: str) -> None:
        """Bind the contributor to a daily-log root + originating session.

        Args:
            daily_log_root: ``data/logs`` directory. May be missing —
                :meth:`collect` returns an empty list in that case.
            session_id: Session id stamped into every Contribution for
                provenance + audit.
        """
        if not session_id:
            raise ValueError("session_id must be non-empty")
        # Immutable state — never mutate after init.
        self._daily_log_root = Path(daily_log_root)
        self._session_id = session_id

    def collect(self, since: Optional[str] = None) -> list[Contribution]:
        """Walk the daily-log root and emit one Contribution per day-file.

        ``since=None`` → full sweep. ``since`` ISO8601 string → only
        emit Contributions for files whose mtime is strictly greater
        than the given timestamp. Tolerant of a missing root (returns
        ``[]``).
        """
        root = self._daily_log_root
        if not root.is_dir():
            logger.debug("daily_log root %s missing — empty sweep", root)
            return []

        cutoff = _parse_iso_since(since)
        out: list[Contribution] = []
        # Walk year/month/day files. Sorting by stringified path keeps
        # the output stable across platforms (POSIX-style ordering).
        for path in sorted(root.rglob("*.md")):
            if not path.is_file():
                continue
            match = _DAILY_LOG_DATE_RE.match(path.name)
            if not match:
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError as exc:
                logger.debug("daily_log stat failed for %s: %s", path, exc)
                continue
            if cutoff is not None and mtime <= cutoff:
                continue
            try:
                body = path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning("daily_log read failed for %s: %s", path, exc)
                continue
            year, month, day = match.group(1), match.group(2), match.group(3)
            iso_date = f"{year}-{month}-{day}"
            relpath = f"{_STAGING_DAILY_LOGS}{iso_date}.md"
            out.append(
                Contribution(
                    relpath=relpath,
                    body=body,
                    source="daily_log",
                    destination="staging",
                    session_id=self._session_id,
                    authored_at=_utc_now_iso(),
                    provenance=f"Daily log mirror for {iso_date}",
                )
            )
        return out


class ReflectionContributor:
    """Mirror weekly reflections from ``ReflectionStore`` into staging.

    Each ``ReflectionResult`` carries a ``week_key`` like
    ``reflection-2026-W18``. The contributor maps that to a
    ``YYYY-Www`` filename (e.g. ``2026-W18.md``) under
    ``bumba-contributions/staging/reflections/`` and emits the formatted
    markdown body produced by :meth:`ReflectionStore.format_reflection`.

    The store does not record per-row mtimes, so ``since`` filtering is
    best-effort: when ``since`` is provided we limit the lookup to the
    most recent reflections (the store's own ``get_recent`` is the
    cheapest way to bound the work). When ``since`` is ``None`` we sweep
    the full store.
    """

    contributor_name: str = "reflection"

    # Cap on the recent-window pull when ``since`` is supplied. The
    # store has no time index — keeping this cap small avoids a full
    # table scan on the hot path. 32 is large enough to absorb several
    # weeks of weekly cycles without missing one.
    _RECENT_WINDOW = 32

    def __init__(
        self,
        *,
        reflection_store: "ReflectionStore",
        session_id: str,
    ) -> None:
        """Bind the contributor to a reflection store + session id."""
        if not session_id:
            raise ValueError("session_id must be non-empty")
        if reflection_store is None:
            raise ValueError("reflection_store must not be None")
        self._store = reflection_store
        self._session_id = session_id

    def collect(self, since: Optional[str] = None) -> list[Contribution]:
        """Emit one Contribution per stored reflection.

        ``since=None`` → full sweep over all reflections. ``since`` ISO
        timestamp → bounded recent window (cheapest cut against a store
        without a time index). Tolerant of an empty store (returns
        ``[]``).
        """
        try:
            if since is None:
                count = self._store.count()
                limit = max(count, 1)
                results = self._store.get_recent(limit=limit)
            else:
                results = self._store.get_recent(limit=self._RECENT_WINDOW)
        except Exception as exc:  # noqa: BLE001 — defensive on store I/O
            logger.warning("reflection_store sweep failed: %s", exc)
            return []

        out: list[Contribution] = []
        # Stable order for idempotent output: sort by week_key.
        for result in sorted(results, key=lambda r: getattr(r, "week_key", "")):
            week_key = getattr(result, "week_key", "") or ""
            short_key = self._short_week_key(week_key)
            if not short_key:
                logger.debug("skipping reflection with malformed week_key %r", week_key)
                continue
            try:
                body = self._store.format_reflection(result)
            except Exception as exc:  # noqa: BLE001 — defensive on formatter
                logger.warning(
                    "reflection format failed for %s: %s", week_key, exc
                )
                continue
            relpath = f"{_STAGING_REFLECTIONS}{short_key}.md"
            out.append(
                Contribution(
                    relpath=relpath,
                    body=body,
                    source="reflection",
                    destination="staging",
                    session_id=self._session_id,
                    authored_at=_utc_now_iso(),
                    provenance=f"Weekly reflection for week {short_key}",
                )
            )
        return out

    @staticmethod
    def _short_week_key(week_key: str) -> str:
        """Convert ``reflection-2026-W18`` → ``2026-W18``.

        Returns an empty string on any week_key that does not match
        the expected shape — caller skips empties.
        """
        if not week_key.startswith("reflection-"):
            return ""
        tail = week_key[len("reflection-"):]
        if not re.fullmatch(r"\d{4}-W\d{2}", tail):
            return ""
        return tail


# Pattern for consolidation digest filenames in the output directory —
# ``YYYY-MM-DD-digest.md``. Anything else is ignored so a stray operator
# note in the directory cannot trip the contributor.
_CONSOLIDATION_DIGEST_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-digest\.md$")


class ConsolidationContributor:
    """Emit curated consolidation digests into ``bumba-contributions/curated/``.

    Reads ``YYYY-MM-DD-digest.md`` files from a per-run output directory
    and mirrors each one into
    ``bumba-contributions/curated/consolidation/{YYYY-MM-DD}-digest.md``.
    The directory is the contract surface — the consolidation pipeline
    is responsible for materializing the digest files there before this
    contributor runs.

    Provenance is rendered as ``"Consolidation digest from {N} sources"``
    where ``N`` is the count of non-blank lines in the digest body — a
    cheap proxy for "input rows" without re-reading the consolidation
    inventory.
    """

    contributor_name: str = "consolidation"

    def __init__(
        self,
        *,
        consolidation_output_dir: Path,
        session_id: str,
    ) -> None:
        """Bind the contributor to a digest directory + session id."""
        if not session_id:
            raise ValueError("session_id must be non-empty")
        self._output_dir = Path(consolidation_output_dir)
        self._session_id = session_id

    def collect(self, since: Optional[str] = None) -> list[Contribution]:
        """Emit one Contribution per digest file in the output directory.

        ``since=None`` → full sweep. ``since`` ISO timestamp → only
        files with mtime strictly greater than the cutoff. Tolerant of
        a missing directory (returns ``[]``).
        """
        if not self._output_dir.is_dir():
            logger.debug(
                "consolidation_output_dir %s missing — empty sweep",
                self._output_dir,
            )
            return []

        cutoff = _parse_iso_since(since)
        out: list[Contribution] = []
        for path in sorted(self._output_dir.iterdir()):
            if not path.is_file():
                continue
            match = _CONSOLIDATION_DIGEST_RE.match(path.name)
            if not match:
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError as exc:
                logger.debug("consolidation stat failed for %s: %s", path, exc)
                continue
            if cutoff is not None and mtime <= cutoff:
                continue
            try:
                body = path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning("consolidation read failed for %s: %s", path, exc)
                continue
            iso_date = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
            relpath = f"{_CURATED_CONSOLIDATION}{iso_date}-digest.md"
            input_count = sum(1 for line in body.splitlines() if line.strip())
            out.append(
                Contribution(
                    relpath=relpath,
                    body=body,
                    source="consolidation",
                    destination="curated",
                    session_id=self._session_id,
                    authored_at=_utc_now_iso(),
                    provenance=(
                        f"Consolidation digest from {input_count} sources"
                    ),
                )
            )
        return out


__all__ = [
    "ConsolidationContributor",
    "DailyLogContributor",
    "ReflectionContributor",
]
