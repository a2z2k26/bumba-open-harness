"""Quality primitive accessors for the job-search pipeline (Sprint 02.10).

Four quality primitives shipped in PR #588 — :class:`FunnelStore`,
:func:`lint_cover_letter`, :class:`SnapshotStore`, and
:func:`check_funnel_canary` — but had **zero non-test callers** in the live
PREPARE/EXECUTE pipeline. Sprint 02.10 wires them into both the legacy
``JobSearchAgent`` (Path B) and the Z4 director tools at
``teams/tools/_job_search.py`` (Path A).

This module provides per-data_dir cached singleton accessors so every call
site in either path writes to the **same** ``funnel.json`` /
``send_snapshots.json``. The 22:00 ``FunnelPostService`` therefore reads
aggregate counts regardless of which pipeline ran.

Why a singleton (and not threaded through ``BridgeDeps``)?

``BridgeDeps`` is a frozen dataclass; adding new fields would ripple through
every department and every test fixture. The quality primitives are
file-system-rooted (one JSON file per data_dir) and stateless beyond their
backing file, so a tiny per-data_dir cache is the minimum-complexity seam
that lets both paths share state.

The default ``data_dir`` matches :data:`bridge.config.BridgeConfig.data_dir`
(resolved via :func:`bridge.paths.data_root`); tests override it via the
``BUMBA_JOB_SEARCH_DATA_DIR`` env var or the explicit ``data_dir=`` arg.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from bridge.paths import data_root

from .canary import check_funnel_canary  # re-exported for convenience
from .funnel import FunnelStore, today_key
from .snapshot import SnapshotStore

log = logging.getLogger(__name__)

# Production default — must match ``bridge.config.BridgeConfig.data_dir``
# and ``job_search.service.DATA_DIR``.
_DEFAULT_DATA_DIR = data_root()

# Per-data_dir caches. Keyed by the resolved absolute path so two different
# tests using two different tmp_paths each get their own store.
_FUNNEL_STORES: dict[Path, FunnelStore] = {}
_SNAPSHOT_STORES: dict[Path, SnapshotStore] = {}


def _resolve_data_dir(data_dir: str | Path | None) -> Path:
    """Resolve a data_dir argument to an absolute :class:`Path`.

    Resolution order:
      1. Explicit ``data_dir`` argument (test override).
      2. ``BUMBA_JOB_SEARCH_DATA_DIR`` env var (cron / debug override).
      3. The hardcoded production default.
    """
    if data_dir is not None:
        return Path(data_dir).resolve()
    env_val = os.environ.get("BUMBA_JOB_SEARCH_DATA_DIR")
    if env_val:
        return Path(env_val).resolve()
    return _DEFAULT_DATA_DIR


def get_funnel_store(data_dir: str | Path | None = None) -> FunnelStore:
    """Return a cached :class:`FunnelStore` for *data_dir*.

    Both PREPARE paths (Z4 director tools, legacy ``JobSearchAgent``) call
    this so they share one ``funnel.json`` per cron run. The 22:00
    ``FunnelPostService`` reads from the same file.
    """
    resolved = _resolve_data_dir(data_dir)
    store = _FUNNEL_STORES.get(resolved)
    if store is None:
        store = FunnelStore(resolved)
        _FUNNEL_STORES[resolved] = store
    return store


def get_snapshot_store(data_dir: str | Path | None = None) -> SnapshotStore:
    """Return a cached :class:`SnapshotStore` for *data_dir*.

    Used by both staging tools and the EXECUTE-phase ``execute_approved`` to
    record approval-time payload hashes and detect edit-after-approval drift
    (the Z2-S2.3 "HIGHEST STAKES" disaster scenario).
    """
    resolved = _resolve_data_dir(data_dir)
    store = _SNAPSHOT_STORES.get(resolved)
    if store is None:
        store = SnapshotStore(resolved)
        _SNAPSHOT_STORES[resolved] = store
    return store


def bump_today(stage: str, count: int = 1, *, data_dir: str | Path | None = None) -> None:
    """Increment *stage* by *count* on today's :class:`FunnelDay`.

    Logs and swallows exceptions: a quality-counter failure must never break
    the pipeline. The funnel is observability, not control flow.
    """
    try:
        store = get_funnel_store(data_dir)
        store.bump(today_key(), stage, count)
    except Exception as exc:  # pragma: no cover — defensive
        log.warning("funnel bump failed (stage=%s, count=%d): %s", stage, count, exc)


def reset_caches() -> None:
    """Clear per-data_dir caches. Tests call this between cases."""
    _FUNNEL_STORES.clear()
    _SNAPSHOT_STORES.clear()


__all__ = [
    "bump_today",
    "check_funnel_canary",
    "get_funnel_store",
    "get_snapshot_store",
    "reset_caches",
]
