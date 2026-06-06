"""Runtime path resolution for the bridge — closes #1492.

Pre-D6-bis (2026-05-09), the bridge had multiple modules hardcoding
``/opt/bumba-harness/agent`` as the runtime root. After the D6-bis
migration moved the runtime to ``/opt/bumba-harness/agent-flat/agent``,
those hardcodes broke; the bridge survived only because operators
created a ``/opt/bumba-harness/agent`` symlink pointing at the new
canonical path. This module exists so the next migration doesn't need
that symlink.

The single function exposed here, :func:`agent_root`, returns the
canonical runtime root, layered in priority order:

1. ``BUMBA_AGENT_ROOT`` env var (operator/test override).
2. ``Path.cwd()`` — the launchd plist sets ``WorkingDirectory`` to the
   runtime tree's ``agent/`` dir, so this resolves to the canonical
   path automatically for production startups. Validated by checking
   that ``<cwd>/bridge/__init__.py`` exists (cheap structural check
   that distinguishes "the bridge tree is here" from "we're somewhere
   else").
3. ``<cwd>/agent`` if cwd is a repo root rather than the inner agent
   subtree (covers ``cd /opt/bumba-harness/agent-flat && ...``).
4. ``/opt/bumba-harness/agent-flat/agent`` — the post-D6-bis canonical
   path. Returned as a last resort so callers see a deterministic
   value even if cwd resolution fails (e.g., transient filesystem
   weirdness during launchd startup).

Callers should treat the return value as opaque and use it to compose
paths — ``agent_root() / "config" / "bridge.toml"`` etc. No caller
should assume any specific string value.

The legacy ``/opt/bumba-harness/agent`` (without ``-flat``) is NOT in
the fallback chain. Pre-D6-bis hardcodes that referenced it are being
migrated to this module's helper as part of the same PR; the legacy
path is reachable today only via the operator-installed symlink and
that symlink is documented for removal.
"""
from __future__ import annotations

import os
from pathlib import Path

__all__ = ["agent_root", "data_root"]


# Post-D6-bis canonical runtime root. The deep fallback when nothing else
# resolves; if this is wrong, the operator already has bigger problems.
_CANONICAL_AGENT_ROOT = Path("/opt/bumba-harness/agent-flat/agent")

# Canonical data dir. Lives at user-home level (not inside the runtime tree),
# so it's unaffected by D6-bis. Provided here as a companion to ``agent_root``
# so callers don't have to know whether each path is in-tree or sibling.
_CANONICAL_DATA_ROOT = Path("/opt/bumba-harness/data")


def agent_root() -> Path:
    """Return the canonical runtime tree root for the bridge.

    Resolution priority (first hit wins):

    1. ``BUMBA_AGENT_ROOT`` env var, if set and pointing at a directory
       that contains ``bridge/__init__.py``. Lets operators or test
       harnesses override without touching code.
    2. ``Path.cwd()`` if it contains ``bridge/__init__.py``. The launchd
       plist's ``WorkingDirectory`` drives this for production startups.
    3. ``Path.cwd() / "agent"`` if THAT contains ``bridge/__init__.py``.
       Covers invocations from the repo root rather than the agent
       subtree (e.g., ``cd /opt/bumba-harness/agent-flat && python -m
       bridge.services.runner ...``).
    4. ``/opt/bumba-harness/agent-flat/agent`` — last-resort canonical
       path. Returned even if it doesn't exist on the filesystem; the
       caller will fail on a downstream operation rather than here, so
       the failure surfaces with a clear path in the traceback.

    Returns:
        The first path in the chain that contains ``bridge/__init__.py``,
        or the canonical fallback if no candidate validates. The return
        value is always a ``Path`` (never ``None``).
    """
    candidates: list[Path] = []

    env_override = os.environ.get("BUMBA_AGENT_ROOT", "").strip()
    if env_override:
        candidates.append(Path(env_override).expanduser())

    cwd = Path.cwd()
    candidates.append(cwd)
    candidates.append(cwd / "agent")

    for candidate in candidates:
        if (candidate / "bridge" / "__init__.py").is_file():
            return candidate

    return _CANONICAL_AGENT_ROOT


def data_root() -> Path:
    """Return the canonical data dir for the bridge.

    Resolution priority (first hit wins):

    1. ``BUMBA_DATA_ROOT`` env var, if set and pointing at a directory.
       Lets operators or test harnesses override.
    2. The ``BridgeConfig.data_dir`` field if a config is loaded — but
       this helper is import-time-safe and does NOT try to load config,
       so this priority lives in callers that have a ``cfg`` already.
    3. Canonical ``/opt/bumba-harness/data``.

    The data dir lives at user-home level, not inside the runtime tree.
    D6-bis (2026-05-09) moved the runtime tree but did NOT move the
    data dir, so the canonical path is stable across migrations.

    Returns:
        The first path in the chain that exists, or the canonical
        fallback. Always a ``Path`` (never ``None``).
    """
    env_override = os.environ.get("BUMBA_DATA_ROOT", "").strip()
    if env_override:
        candidate = Path(env_override).expanduser()
        if candidate.is_dir():
            return candidate

    return _CANONICAL_DATA_ROOT
