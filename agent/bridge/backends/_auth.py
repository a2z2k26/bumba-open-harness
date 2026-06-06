"""Codex backend auth holder — ChatGPT-OAuth lifecycle for the Codex CLI.

Sprint Codex-4 (issue #1838). Per the operator-binding amendment on #1838,
the active Codex auth path is **ChatGPT-OAuth** (subscription-billed,
seeded by ``codex login`` writing ``~/.codex/auth.json``), not the static
``CODEX_API_KEY`` env var. The static key path is intentionally NOT plumbed
because ``bridge.cross_model.openrouter_client`` already provides per-token
API access for OpenAI models; duplicating that surface adds no capability.

Sprint Codex-7-followup (issue #1872) wires the two ``NotImplementedError``
stubs against the now-documented contracts:

  - ``refresh()`` — calls ``https://auth.openai.com/oauth/token`` per
    ``docs/architecture/codex-oauth-refresh.md``.
  - ``materialize_auth_json()`` — round-trips ``~/.codex/auth.json`` per
    ``docs/architecture/codex-auth-json-schema.md``.

The rotation *primitive* is now live; the *loop that calls it on a
schedule* is still a follow-up (see "Promoting to 5b-1" below).

Architectural choice — path 5b-2 (sibling class, not generalized refresher):
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Codex-4 spec offered two paths:

  5b-1: Generalize ``bridge.token_refresher.TokenRefresher`` to accept a
        per-provider config (refresh URL, client_id, secret-field names) so
        one rotation loop services both Anthropic + OpenAI.
  5b-2: Add a sibling holder class here that mirrors the lifecycle surface
        but keeps the Claude OAuth loop untouched.

Chose **5b-2** for three reasons:

  1. ``TokenRefresher`` runs the live Claude auth path on every running
     bridge; the Surgical Changes doctrine ("touch the minimum surface
     that resolves the task") argues against invasive refactor of a
     load-bearing module when a sibling suffices.
  2. OpenAI's OAuth refresh endpoint used by ``codex login`` was not
     publicly documented when Codex-4 shipped; Codex-7-followup pulls
     the contract from the public ``openai/codex`` Rust source and
     locks it in. Promoting to 5b-1 (one refresher, two providers) is
     a clean follow-up now that both endpoint shapes are known.
  3. The sprint's primary deliverable is the **auth surface** — fields in
     ``.secrets``, plumbing in ``BridgeConfig``, and fail-closed boot
     validation. The rotation loop remains dormant scaffolding until
     ``backends_enabled`` flips on. A sibling class lets us ship the
     surface today and graft the loop later without disturbing the
     Claude path.

Surface
~~~~~~~

``CodexAuthHolder`` exposes the same minimal contract that
``CodexBackend.auth_env()`` and any future warm-process refresh hook can
call against:

  - ``access_token`` (property) — current bearer token (may be empty).
  - ``refresh_token`` (property) — long-lived rotation credential.
  - ``expires_at`` (property) — unix epoch seconds; 0 means "unknown".
  - ``id_token`` (property) — raw JWT, used by ``materialize_auth_json``.
  - ``needs_refresh(now=None)`` — True when the token is within the
    refresh margin or missing entirely.
  - ``start()`` / ``stop()`` — async lifecycle no-ops by default; the
    refresh loop wires in here once Codex-7-followup-loop lands.
  - ``refresh()`` — wired against the documented endpoint.
  - ``materialize_auth_json(path)`` — wired against the documented schema.

The class is deliberately quiet at construction: empty token triples are
legal (matches ``BridgeConfig`` defaults). The fail-closed boot validator
in ``BridgeApp._initialize`` is the layer that enforces "must be set when
a codex backend is configured" — this holder just carries values.

Follow-up issues to file post-merge
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

  - Promote to 5b-1 once a real refresh exchange has been observed on
    the Mac mini: one refresher class, per-provider configs, one
    ``start()``/``stop()`` lifecycle. Both endpoint contracts are now
    in code; the blocker is "actually run the loop in production once
    to confirm shape".

Independent of Claude's OAuth refresher
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Nothing here touches ``bridge.token_refresher.TokenRefresher``. The two
providers' lifecycles are independent — Anthropic rotation continues on
the existing 6h cycle regardless of whether ``CodexAuthHolder`` is
constructed.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Refresh proactively: 1h before expiry mirrors the Claude refresher's
# margin (``bridge.token_refresher._REFRESH_MARGIN_S``). Centralised so a
# future 5b-1 promotion can pull both providers' margins from one place.
_REFRESH_MARGIN_S = 3600

# ---------------------------------------------------------------------------
# OAuth refresh endpoint (Codex-7-followup #1872)
# ---------------------------------------------------------------------------
# Sourced from openai/codex@main: codex-rs/login/src/auth/manager.rs:93-96,
# 921. See docs/architecture/codex-oauth-refresh.md for the full contract.
_CODEX_REFRESH_URL = "https://auth.openai.com/oauth/token"
_CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"

# 401-response error codes the Codex CLI treats as permanent. The bridge
# mirrors the classification: a 401 carrying one of these codes means the
# operator must re-run ``codex login`` on the Mac mini.
_PERMANENT_401_CODES = frozenset(
    {
        "refresh_token_expired",
        "refresh_token_reused",
        "refresh_token_invalidated",
    }
)


class CodexRefreshPermanentError(RuntimeError):
    """Raised when the OAuth refresh fails permanently (401 with a known code).

    The operator must re-run ``codex login`` on the Mac mini and re-seed
    ``.secrets`` from the new ``~/.codex/auth.json``. The exception message
    carries the specific error code (``refresh_token_expired``,
    ``refresh_token_reused``, ``refresh_token_invalidated``, or
    ``"unknown_401"`` when the body shape couldn't be parsed) so the caller
    can fan that detail out to the operator surface.
    """


def _decode_jwt_exp(jwt: str) -> int:
    """Extract the ``exp`` claim from a JWT's payload segment.

    Returns 0 on any decode error (malformed JWT, missing ``exp``, etc.) —
    callers handle 0 as "unknown expiry" without crashing the refresh.

    JWTs use base64url WITHOUT padding by spec; this helper pads manually
    before decoding, matching the Codex CLI's
    ``codex-rs/login/src/token_data.rs::parse_jwt_expiration`` behaviour.
    """
    try:
        parts = jwt.split(".")
        if len(parts) < 2:
            return 0
        payload_b64 = parts[1]
        padding = "=" * (-len(payload_b64) % 4)
        payload_raw = base64.urlsafe_b64decode(payload_b64 + padding)
        payload = json.loads(payload_raw)
        return int(payload.get("exp", 0))
    except (ValueError, json.JSONDecodeError, KeyError, TypeError):
        return 0


def _classify_401(body_text: str) -> str:
    """Extract the error code from a 401 refresh response body.

    Returns the code (e.g. ``"refresh_token_expired"``) for known-permanent
    failures, or ``"unknown_401"`` if the body shape can't be parsed.

    Sourced from ``codex-rs/login/src/auth/manager.rs``: the CLI inspects
    both nested ``error.code`` and top-level ``code`` shapes. We honour both.
    """
    try:
        data = json.loads(body_text)
    except (json.JSONDecodeError, ValueError):
        return "unknown_401"

    code: Optional[str] = None
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        code = err.get("code")
    if not code and isinstance(data, dict):
        code = data.get("code")

    if isinstance(code, str) and code in _PERMANENT_401_CODES:
        return code
    return "unknown_401"


class CodexAuthHolder:
    """In-memory holder for the Codex ChatGPT-OAuth credential triple.

    Constructed at bridge boot from ``BridgeConfig.codex_oauth_*`` fields
    (which are populated either from ``.secrets`` parsing or from the
    ``BridgeConfig`` defaults of empty/zero). Lives for the duration of
    the bridge process.

    Empty token triples are legal at construction — the fail-closed boot
    validator in ``BridgeApp._initialize`` is responsible for refusing
    to boot when a Codex backend is configured but the triple is missing.
    This class is the carrier, not the gate.

    Codex-7-followup (#1872) wires ``refresh()`` and ``materialize_auth_json()``
    against the documented contracts; both are now live primitives. The
    *scheduled rotation loop* that calls them is still a follow-up sprint —
    today the holder rotates on explicit call only.
    """

    def __init__(
        self,
        access_token: str = "",
        refresh_token: str = "",
        expires_at: int = 0,
        id_token: str = "",
    ) -> None:
        # Per the rule "immutability where reasonable", these are stored as
        # private attributes mutated only by ``refresh()``. Public access
        # goes through properties so callers never see an in-flight rotation.
        self._access_token = access_token
        self._refresh_token = refresh_token
        # Stored as float-seconds-since-epoch internally to match the
        # Claude refresher's ``_expires_at`` shape. ``int`` input from
        # ``.secrets`` (unix seconds) is implicitly upcast.
        self._expires_at = float(expires_at)
        # Codex-7-followup (#1872) — fourth field. Raw JWT string; expiry
        # is derived from its ``exp`` claim on refresh. Seeded from
        # ``codex_oauth_id_token`` in ``.secrets``.
        self._id_token = id_token
        self._started = False

    @property
    def access_token(self) -> str:
        """Current bearer token. Empty string when unconfigured."""
        return self._access_token

    @property
    def refresh_token(self) -> str:
        """Long-lived rotation credential. Empty when unconfigured."""
        return self._refresh_token

    @property
    def expires_at(self) -> int:
        """Unix epoch seconds when ``access_token`` expires. 0 = unknown."""
        return int(self._expires_at)

    @property
    def id_token(self) -> str:
        """Raw JWT string from the most recent successful refresh / seed.

        Used by ``materialize_auth_json`` to populate ``tokens.id_token``
        in the file the Codex CLI reads. Expiry is derived from this
        JWT's ``exp`` claim — see ``_decode_jwt_exp``.
        """
        return self._id_token

    def needs_refresh(self, now: Optional[float] = None) -> bool:
        """Return True when the current token is stale or missing.

        A token is "stale" if its expiry is within ``_REFRESH_MARGIN_S``
        seconds, mirroring the Claude refresher's policy. A missing token
        (empty access_token) also returns True — caller is expected to
        either run the refresh path or fail-closed depending on context.

        Args:
            now: Override for ``time.time()``. Tests pin this; production
                callers leave it as None.
        """
        if not self._access_token:
            return True
        if self._expires_at <= 0:
            # No expiry info: treat as fresh — refresher would otherwise
            # loop endlessly. The Claude refresher uses the same heuristic.
            return False
        clock = time.time() if now is None else now
        return (self._expires_at - clock) <= _REFRESH_MARGIN_S

    def start(self) -> None:
        """Lifecycle hook called from ``BridgeApp._initialize``.

        No-op today. The Codex-7-followup-loop sprint will wire a
        background refresh task here, mirroring ``TokenRefresher.start()``.
        Idempotent: calling twice is fine.
        """
        if self._started:
            return
        self._started = True
        # The Codex auth surface lands dormant per Codex-4. Log at INFO
        # so the operator can see at boot whether the holder is loaded;
        # this is the only durable signal until ``backends_enabled`` flips.
        if self._access_token:
            logger.info(
                "CodexAuthHolder ready (refresh loop dormant, expires_at=%d)",
                int(self._expires_at),
            )
        else:
            logger.info(
                "CodexAuthHolder constructed without tokens — "
                "codex backend will fail-closed at boot if configured"
            )

    async def stop(self) -> None:
        """Async lifecycle hook to mirror ``TokenRefresher.stop()``.

        No-op today; will cancel the refresh task once Codex-7-followup-loop
        lands.
        """
        self._started = False

    async def refresh(self) -> None:
        """Rotate the access_token via OpenAI's OAuth refresh endpoint.

        Sourced from ``docs/architecture/codex-oauth-refresh.md`` (which
        in turn cites ``openai/codex@main``). Updates the in-memory triple
        (and ``id_token``) using update-only-if-present semantics: fields
        the server omits stay at their current value, matching the Codex
        CLI's ``persist_tokens()`` behaviour.

        The bridge calls the same endpoint with the same ``client_id`` that
        the public ``codex`` CLI does. This is functionally fine (we're
        rotating the same triple); the operator should be aware we identify
        as the Codex CLI to OpenAI's auth service.

        Raises:
            CodexRefreshPermanentError: 401 with a known-permanent error
                code. Operator must re-run ``codex login``.
            RuntimeError: network/HTTP error (caller may retry); or holder
                has no refresh_token seeded.
        """
        if not self._refresh_token:
            raise RuntimeError(
                "CodexAuthHolder.refresh() called with empty refresh_token"
            )

        # Mirror token_refresher.py: blocking urllib call in a thread.
        # Avoids adding httpx as a runtime dep for one endpoint; consistent
        # with the existing Claude refresh path.
        data: dict[str, Any] = await asyncio.to_thread(self._call_refresh_endpoint)

        # Update-only-if-present (mirrors CLI's persist_tokens behaviour).
        if data.get("access_token"):
            self._access_token = data["access_token"]
        if data.get("refresh_token"):
            self._refresh_token = data["refresh_token"]
        if data.get("id_token"):
            self._id_token = data["id_token"]
            exp = _decode_jwt_exp(data["id_token"])
            if exp:
                self._expires_at = float(exp)

    def _call_refresh_endpoint(self) -> dict[str, Any]:
        """Synchronous HTTP POST to the Codex OAuth refresh endpoint.

        Runs in a worker thread via ``asyncio.to_thread`` (see ``refresh``).
        Raises ``CodexRefreshPermanentError`` on permanent-401 codes;
        ``RuntimeError`` on transient/HTTP errors.

        Diverges from RFC 6749 by using JSON body instead of
        ``application/x-www-form-urlencoded`` — the Codex CLI's wire format
        is what we must match, not the OAuth spec.
        """
        body = json.dumps(
            {
                "client_id": _CODEX_CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            _CODEX_REFRESH_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                payload = resp.read().decode("utf-8")
                parsed = json.loads(payload)
                if not isinstance(parsed, dict):
                    raise RuntimeError(
                        f"Codex OAuth refresh returned non-dict payload: "
                        f"{type(parsed).__name__}"
                    )
                # Narrow the parsed JSON object to dict[str, Any] at the
                # boundary. Server is contractually JSON-object; non-string
                # keys would be a server-side bug, not something to coerce
                # silently downstream.
                return {str(k): v for k, v in parsed.items()}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            if e.code == 401:
                raise CodexRefreshPermanentError(_classify_401(err_body)) from e
            logger.error(
                "Codex OAuth refresh HTTP %d: %s", e.code, err_body[:500]
            )
            raise RuntimeError(
                f"Codex OAuth refresh failed: HTTP {e.code}"
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Codex OAuth refresh network error: {e.reason}"
            ) from e

    def materialize_auth_json(self, path: Optional[Path] = None) -> None:
        """Write the current token quartet to ``~/.codex/auth.json``.

        The Codex CLI reads its auth from ``$CODEX_HOME/auth.json``
        (default ``~/.codex/auth.json``). On token refresh, the bridge
        overwrites that file so the next ``codex`` subprocess sees the
        new tokens.

        Implementation per ``docs/architecture/codex-auth-json-schema.md``:

          - Load existing file (if any) to preserve unmanaged fields
            (``account_id``, ``agent_identity``, ``OPENAI_API_KEY``).
          - Merge in the current managed fields (access/refresh/id tokens).
          - Stamp ``auth_mode = "chatgpt"`` and ``last_refresh`` to now.
          - Atomic write via ``os.replace`` of a ``*.json.tmp`` sibling.
          - Mode 0600 (matches the Codex CLI's
            ``codex-rs/login/src/auth/storage.rs:148``).

        Args:
            path: Override for the target file. Defaults to
                ``$CODEX_HOME/auth.json`` (or ``~/.codex/auth.json`` when
                the env var is unset). Tests pin this.
        """
        if path is None:
            codex_home = os.environ.get("CODEX_HOME", "~/.codex")
            target = Path(codex_home).expanduser() / "auth.json"
        else:
            target = Path(path)

        target.parent.mkdir(parents=True, exist_ok=True)

        # Load existing to preserve unmanaged fields (account_id,
        # agent_identity, OPENAI_API_KEY). A corrupt file is treated as
        # empty rather than blocking the rotation — the next write fixes it.
        existing: dict[str, Any] = {}
        if target.exists():
            try:
                existing = json.loads(target.read_text())
                if not isinstance(existing, dict):
                    existing = {}
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(
                    "Codex auth.json at %s is unreadable (%s); overwriting",
                    target, e,
                )
                existing = {}

        tokens_existing = existing.get("tokens") or {}
        if not isinstance(tokens_existing, dict):
            tokens_existing = {}
        tokens = dict(tokens_existing)
        tokens["access_token"] = self._access_token
        tokens["refresh_token"] = self._refresh_token
        if self._id_token:
            tokens["id_token"] = self._id_token
        # tokens["account_id"] is preserved from existing (if present);
        # the bridge never sets or clears it.

        payload: dict[str, Any] = {
            **existing,
            "auth_mode": "chatgpt",
            "tokens": tokens,
            "last_refresh": (
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            ),
        }

        # Atomic write: tmp sibling on the same filesystem, chmod 0600,
        # then os.replace. Mirrors token_refresher.py's _update_secrets_file
        # pattern.
        tmp = target.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(payload, indent=2))
            os.chmod(tmp, 0o600)
            os.replace(tmp, target)
        except Exception:
            # Best-effort cleanup of the tmp file if anything between
            # write and replace failed. Don't mask the original error.
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise
