"""Canonical ``.secrets`` reader for the bridge runtime.

Sprint audit-2026-05-16.B.02 (#2051 / M-1) — collapses four duplicate
secret-reading sites into one helper:

  * ``bridge.config._load_secrets_file`` — BridgeConfig key=value parse
  * ``bridge.claude_runner._load_secrets_as_env`` — raw env injection
  * ``scripts.experiment_loop._read_secrets`` — autonomous loop reader
  * ``job_search._pipeline._get_notion_db_id`` — line-scan for one key

All four sites now delegate to :class:`RuntimeSecrets`. The helper owns the
``.secrets`` parse, integrates the B.01 permission guard
(``bridge.config._require_private_file``), and exposes typed accessors so
callers stop hand-rolling deprecation fallbacks and int-parsing.

Out of scope (follow-ups):
  * ``bridge/calcom_webhook.py::_read_secret`` — Cal.com module-level secret
    reader, deliberately deferred per sprint frontmatter.

Env-override precedence (e.g. ``BUMBA_*`` env vars beating ``BridgeConfig``
fields) is owned by ``bridge.config._apply_env_overrides`` and is unchanged
by this helper. This module reads files, nothing more.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from bridge.config import ConfigError, _require_private_file

logger = logging.getLogger(__name__)


# Canonical runtime secrets path. Matches the existing default used by
# ``bridge.config._load_secrets_file`` (``Path.home() / "data" / ".secrets"``
# under the ``bumba-agent`` account) and ``scripts.experiment_loop.SECRETS_PATH``.
_DEFAULT_SECRETS_PATH = Path("/opt/bumba-harness/data/.secrets")


# Keys the Claude Code CLI interprets as auth credentials. They must NOT
# bleed into the subprocess environment via ``as_env_dict`` because Claude
# Code would then use them instead of ``CLAUDE_CODE_OAUTH_TOKEN`` (causing
# "Invalid API key" errors). Mirrors ``_CLAUDE_AUTH_KEYS`` in the legacy
# ``claude_runner._load_secrets_as_env``.
_CLAUDE_AUTH_KEYS_BLOCKLIST = frozenset({"ANTHROPIC_API_KEY"})


class RuntimeSecrets:
    """Single canonical reader for the runtime ``.secrets`` file.

    Lazy + cached: the file is parsed on first access and re-used until
    :meth:`reload` is called (tests) or the instance is discarded. Thread-safe
    via a lock around the cache slot. Permission enforcement delegates to
    :func:`bridge.config._require_private_file` (B.01 contract).

    The helper does NOT consult environment variables — that responsibility
    stays with the BridgeConfig env-override layer.
    """

    def __init__(
        self,
        secrets_path: Path | None = None,
        *,
        enforce_permissions: bool = True,
    ) -> None:
        """Construct a reader bound to ``secrets_path``.

        ``enforce_permissions`` (default ``True``) integrates the B.01
        fail-closed perm guard from :func:`bridge.config._require_private_file`.
        Callers that historically tolerated permissive ``.secrets`` files
        (the experiment loop's long-running soft-fail contract; the
        job-search pipeline's optional read path) pass ``False`` to
        preserve pre-B.02 behaviour. The canonical bridge config loader
        (:func:`bridge.config._load_secrets_file`) leaves it on.
        """
        self._path: Path = secrets_path if secrets_path is not None else _DEFAULT_SECRETS_PATH
        self._enforce_permissions = enforce_permissions
        self._cache: dict[str, str] | None = None
        self._lock = threading.Lock()

    # ── Loading ────────────────────────────────────────────────

    def _load(self) -> dict[str, str]:
        """Parse the ``.secrets`` file and cache the result.

        Returns an empty dict if the file does not exist (mirrors the
        long-standing soft-fail contract used by all four legacy call sites).
        When ``enforce_permissions=True`` (default), raises
        :class:`ConfigError` if the file is group/world-readable — the B.01
        fail-closed guard.
        """
        with self._lock:
            if self._cache is not None:
                return self._cache

            if self._enforce_permissions:
                try:
                    _require_private_file(self._path, purpose="canonical secrets file")
                except ConfigError:
                    # Surface perm errors — do NOT swallow. B.01 contract.
                    raise

            parsed: dict[str, str] = {}
            try:
                raw = self._path.read_text()
            except FileNotFoundError:
                self._cache = parsed
                return self._cache
            except OSError as exc:
                logger.warning("RuntimeSecrets: cannot read %s: %s", self._path, exc)
                self._cache = parsed
                return self._cache

            for line in raw.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if not key:
                    continue
                parsed[key] = val

            self._cache = parsed
            return self._cache

    def reload(self) -> None:
        """Drop the cached parse so the next accessor re-reads the file.

        Tests use this after mutating the underlying ``.secrets`` file.
        """
        with self._lock:
            self._cache = None

    # ── Generic accessors ──────────────────────────────────────

    def as_dict(self) -> dict[str, str]:
        """Return a shallow copy of the parsed key→value map."""
        return dict(self._load())

    def as_env_dict(self) -> dict[str, str]:
        """Return the parse filtered for safe subprocess env injection.

        Excludes the Claude Code auth blocklist (``ANTHROPIC_API_KEY``) so
        the subprocess's ``CLAUDE_CODE_OAUTH_TOKEN`` route stays canonical.
        Keys are preserved as-written (no case transformation) to match the
        legacy ``_load_secrets_as_env`` behaviour and the existing
        ``${VAR}`` references in ``.mcp.json``.
        """
        return {
            k: v for k, v in self._load().items() if k not in _CLAUDE_AUTH_KEYS_BLOCKLIST
        }

    def get(self, key: str, *, required: bool = False) -> str | None:
        """Generic accessor; ``required=True`` raises :class:`ConfigError` when missing."""
        val = self._load().get(key)
        if not val:
            if required:
                raise ConfigError(f"Required secret missing: {key}")
            return None
        return val

    # ── Typed accessors ────────────────────────────────────────

    def claude_oauth_token(self, *, required: bool = False) -> str | None:
        """Return the Claude OAuth access token.

        When ``required=True`` and the primary lookup yields nothing, falls
        back to the deprecated ``<secrets-dir>/.claude-token`` cache file
        (with a deprecation warning). Mirrors the contract documented in
        ``scripts.experiment_loop._load_oauth_token`` so the migration is
        behaviour-preserving for the experiment loop's existing callers.
        Raises :class:`ConfigError` when both sources are empty and
        ``required=True``.
        """
        val = self._load().get("claude_oauth_token", "")
        if val:
            return val

        # Deprecated fallback — preserves #1991 / A.01 contract.
        legacy = self._path.parent / ".claude-token"
        try:
            if legacy.exists():
                logger.warning(
                    "RuntimeSecrets: falling back to deprecated %s — "
                    "migrate to .secrets and remove the legacy file",
                    legacy,
                )
                content = legacy.read_text().strip()
                if content:
                    return content
        except (PermissionError, OSError) as exc:
            logger.warning("RuntimeSecrets: cannot read %s: %s", legacy, exc)

        if required:
            raise ConfigError("Required secret missing: claude_oauth_token")
        return None

    def claude_oauth_refresh_token(self, *, required: bool = False) -> str | None:
        """Return the Claude OAuth refresh token."""
        return self.get("claude_oauth_refresh_token", required=required)

    def claude_oauth_expires_at(self) -> int | None:
        """Return the Claude OAuth expiry as an int, or None if missing/unparseable."""
        val = self._load().get("claude_oauth_expires_at", "")
        if not val:
            return None
        try:
            return int(val)
        except ValueError:
            # Mirrors the silent-skip behaviour in config.py:1553.
            return None

    def notion_db_id(self, *, required: bool = False) -> str | None:
        """Return the configured Notion job-search DB ID.

        Reads the ``bumba_notion_job_db_id`` key (the existing convention in
        ``job_search._pipeline._get_notion_db_id``). Callers that want the
        env-var override or the hard-coded fallback should layer those
        themselves; this helper only consults ``.secrets``.
        """
        return self.get("bumba_notion_job_db_id", required=required)


# ── Module-level default singleton ─────────────────────────────

_DEFAULT: RuntimeSecrets | None = None
_DEFAULT_LOCK = threading.Lock()


def get_runtime_secrets() -> RuntimeSecrets:
    """Return the process-wide :class:`RuntimeSecrets` instance.

    Lazy-constructed so test code that swaps the default path before any
    consumer runs does not have to wrestle with import-time side effects.
    """
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = RuntimeSecrets()
        return _DEFAULT
