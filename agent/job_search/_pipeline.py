"""Shared pipeline helpers for the job-search cron entry points.

Sprint P5.3 (#1588) — "one job-search pipeline path".

Before this sprint, ``_preflight_paths``, ``_run_preflight``, ``_failure_key``,
and ``_get_notion_db_id`` lived inside ``job_search.service`` next to the two
service classes. Both ``JobSearchPrepareService`` and ``JobSearchExecuteService``
called them; ``__main__.py`` had its own divergent execution shape that didn't.

This module extracts those helpers into a single common surface so:

  1. The two cron services stay thin — they just compose ``_run_preflight`` →
     ``BridgeDeps.for_cron`` → ``department.run_{prepare,execute}``.
  2. The CLI entry in ``__main__.py`` can join the same canonical path by
     routing through ``department.run_{prepare,execute}`` (which carries the
     ``asyncio.timeout`` protection that the previous direct
     ``registry.route(...)`` call bypassed).
  3. Test code that patches ``job_search.service._run_preflight`` continues to
     work because ``service`` re-exports the helpers from this module — pytest
     ``patch`` rebinds the attribute on whichever module looked it up.

The single canonical path is now:

   cron LaunchDaemon (bridge.services.runner)
        ↓
   job_search.service.{JobSearchPrepareService,JobSearchExecuteService}.run()
        ↓
   job_search._pipeline._run_preflight()          ← gate (P3.1 + Sprint 02.09)
        ↓
   teams._types.BridgeDeps.for_cron(...)
        ↓
   job_search.department.run_{prepare,execute}(deps)   ← timeout-wrapped
        ↓
   teams._registry.DepartmentRegistry.route("job_search", intent, deps)
        ↓
   teams._factory.build_manager_agent()           ← job-search-chief
        ↓
   chief.delegate(specialist, task) × N

And from the CLI side:

   python -m job_search [prepare|execute]
        ↓
   __main__._is_team_enabled()
        ├─ True → job_search.department.run_{prepare,execute}(deps)  [same path]
        └─ False → JobSearchAgent.{prepare,execute}() [legacy fallback, kept]

Nothing here imports ``service`` or ``department``; the dependency arrow
points one way (``service``/``__main__``/``department`` → ``_pipeline``) to
avoid circular imports.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bridge.halt import HaltPolicy


_STATE_FILE = "job_search-state.json"


def _resolve_agent_root() -> Path:
    """Resolve runtime tree root via the canonical helper (#1492)."""
    from bridge.paths import agent_root
    return agent_root()


def _resolve_data_root() -> Path:
    """Resolve data dir via the canonical helper (#1501 F4)."""
    from bridge.paths import data_root
    return data_root()


def _build_halt_policy(data_dir: Path | None = None) -> "HaltPolicy":
    """Build a HaltPolicy bound to ``<data_dir>/halt.flag``.

    Audit-2026-05-16.C.04 (#2059) — job-search runs in two separate
    subprocess contexts (cron LaunchDaemon and direct CLI). Neither
    boots the full bridge stack, so dragging
    :func:`bridge.config.build_default_halt_policy` (which needs a
    constructed ``SecurityManager`` + ``Database``) is overkill.

    Instead, mirror what ``SecurityManager.is_halted`` /
    ``check_halt_flag`` do on the daemon side — read the same on-disk
    halt flag — through the C.01 ``HaltPolicy`` contract. The policy is
    pure; the halt source is just two callables. Both surfaces converge
    on the same file the operator's ``/halt`` writes.

    Args:
        data_dir: Override the data root (tests use this). When None,
            resolves via ``_resolve_data_root`` (canonical helper).
    """
    from bridge.halt import HaltPolicy

    if data_dir is None:
        data_dir = _resolve_data_root()
    halt_path = Path(data_dir) / "halt.flag"

    def _is_halted() -> bool:
        return halt_path.exists()

    def _halt_reason() -> str | None:
        if not halt_path.exists():
            return None
        try:
            return halt_path.read_text().strip() or "halted"
        except OSError:
            return "halted"

    return HaltPolicy(is_halted=_is_halted, halt_reason=_halt_reason)


def _preflight_paths(data_dir: Path) -> dict[str, Path]:
    """Resolve the on-disk paths preflight_check needs.

    Centralised so PrepareService and ExecuteService stay in sync and the
    test suite can monkeypatch a single seam.

    The paths match what's already wired throughout the cron path:
      - secrets:   ``<data_dir>/.secrets``                      (DATA_DIR convention)
      - criteria:  ``job_search/criteria.json``                 (agent.DEFAULT_CRITERIA)
      - candidate: ``job_search/candidate.json``                (agent.DEFAULT_CANDIDATE)
      - db:        ``<data_dir>/job_search.db``                 (agent.DEFAULT_DB)
      - state:     ``<data_dir>``                               (preflight reads job-search-state.json from here)
    """
    job_search_dir = Path(__file__).parent
    return {
        "secrets_path": data_dir / ".secrets",
        "criteria_path": job_search_dir / "criteria.json",
        "candidate_path": job_search_dir / "candidate.json",
        "db_path": data_dir / "job_search.db",
        "state_dir": data_dir,
    }


def _run_preflight(data_dir: Path, run_type: str) -> tuple[bool, list[str]]:
    """Invoke ``preflight_check`` with the standard cron-side paths.

    Wrapper exists so tests can monkeypatch ``_run_preflight`` to return a
    curated result without having to fabricate a full
    secrets/criteria/candidate fixture tree.

    Returns ``(ok, errors)`` exactly as ``preflight_check`` does:
      - ok=True, errors=[]                — proceed
      - ok=False, errors=["...", ...]     — abort, first error becomes the
                                            ``preflight_failed:<key>`` skip
                                            reason after slug-mangling.
    """
    from job_search.preflight import preflight_check

    paths = _preflight_paths(data_dir)
    return preflight_check(
        secrets_path=paths["secrets_path"],
        criteria_path=paths["criteria_path"],
        candidate_path=paths["candidate_path"],
        db_path=paths["db_path"],
        state_dir=paths["state_dir"],
        run_type=run_type,
    )


def _failure_key(error: str) -> str:
    """Derive a stable, log-grep-friendly slug from a preflight error string.

    ``preflight_check`` returns full English sentences ("notion_api_token
    missing from .secrets"). The skip_reason field is used by /services and
    grepped from log lines, so we want a short stable token rather than a
    free-form sentence. Strategy: take the first whitespace-delimited
    segment and strip punctuation. Falls back to ``"unknown"`` for the
    pathological empty case.
    """
    if not error or not error.strip():
        return "unknown"
    first_token = error.strip().split()[0].strip(":,.")
    return first_token or "unknown"


def _get_notion_db_id(data_dir: Path | None = None) -> str:
    """Get Notion DB ID from env var, .secrets, or hardcoded default.

    Accepts ``data_dir`` so callers can override the secrets-lookup root;
    defaults to the canonical runtime ``data_root()`` when not supplied,
    matching the legacy behaviour from ``service.py``.

    Sprint audit-2026-05-16.B.02 (#2051, M-1) — delegates the ``.secrets``
    read to :class:`bridge.runtime_secrets.RuntimeSecrets`. Env-var
    precedence stays here because it is a job-search-specific contract, not
    part of the canonical secret-file reader.
    """
    env_val = os.environ.get("BUMBA_NOTION_JOB_DB_ID")
    if env_val:
        return env_val
    root = data_dir if data_dir is not None else _resolve_data_root()
    secrets_path = root / ".secrets"
    if secrets_path.exists():
        from bridge.runtime_secrets import RuntimeSecrets
        try:
            # ``enforce_permissions=False`` preserves the pre-B.02 contract;
            # the canonical BridgeConfig loader enforces the B.01 guard, so
            # a perm anomaly will have surfaced before this code runs.
            rs = RuntimeSecrets(secrets_path=secrets_path, enforce_permissions=False)
            db_id = rs.notion_db_id(required=False)
            if db_id:
                return db_id
        except (PermissionError, OSError):
            pass
    raise RuntimeError(
        "Job-search Notion database is not configured. Set "
        "BUMBA_NOTION_JOB_DB_ID or notion_job_db_id in the local .secrets file."
    )
