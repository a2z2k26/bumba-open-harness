"""Tests for Sprint Codex-4 — Codex OAuth auth surface.

Covers the five acceptance cases from the issue body, updated per the
operator-binding amendment on #1838 that supersedes static API-key plumbing
with ChatGPT-OAuth field plumbing.

Test cases:
1. ``.secrets`` parsing populates ``codex_oauth_token`` +
   ``codex_oauth_refresh_token`` + ``codex_oauth_expires_at``.
2. Boot fails-closed when any ``[backends]`` role resolves to ``"codex"``
   and ``codex_oauth_token`` is empty.
3. Boot succeeds in legacy mode (``backends_enabled=false``) regardless of
   the Codex OAuth fields.
4. A ``.secrets`` file with both Claude and Codex OAuth triples parses
   cleanly without cross-talk.
5. An expired Codex token (``expires_at < now``) is flagged for refresh
   via ``CodexAuthHolder.needs_refresh`` — bridge proceeds to boot, the
   refresh attempt is the next-step responsibility (not fail-closed).
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.app import (
    _active_backends_from_config,
    _validate_backend_readiness,
    _validate_codex_oauth,
)
from bridge.backends._auth import (
    CodexAuthHolder,
    CodexRefreshPermanentError,
    _classify_401,
    _decode_jwt_exp,
)
from bridge.config import _load_secrets_file


def _write_private_secrets(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(0o600)


# ---------------------------------------------------------------------------
# Stub config object — mirrors the BridgeConfig surface this PR exercises
# without dragging in Codex-3's sibling fields (which land in a parallel PR).
# Using getattr(...) inside the validator means a test stub with just the
# Codex-4-relevant attributes is sufficient.
# ---------------------------------------------------------------------------


@dataclass
class _StubConfig:
    """Minimal config shape that ``_validate_codex_oauth`` reads from.

    All fields default to the boot-clean state. Each test mutates only what
    its scenario needs, then passes the instance to ``_validate_codex_oauth``.
    """

    # Codex-3 sibling fields (added in a parallel sprint). Defaults match
    # the legacy "no [backends] registry" boot.
    backends_enabled: bool = False
    backends_main: str = ""
    backends_chiefs_default: str = ""
    backends_specialists_default: str = ""
    backends_specialists_overrides: dict = field(default_factory=dict)
    # Codex-4 fields (this PR).
    codex_oauth_token: str = ""
    codex_oauth_refresh_token: str = ""
    codex_oauth_expires_at: int = 0


# ---------------------------------------------------------------------------
# Case 1 — .secrets parser populates the Codex OAuth triple
# ---------------------------------------------------------------------------


def test_secrets_parser_loads_codex_oauth_triple(tmp_path):
    """``.secrets`` with the three Codex OAuth fields is parsed cleanly."""
    secrets_path = tmp_path / ".secrets"
    _write_private_secrets(
        secrets_path,
        "codex_oauth_token=sk-codex-access-xyz\n"
        "codex_oauth_refresh_token=sk-codex-refresh-abc\n"
        "codex_oauth_expires_at=1234567890\n",
    )

    secrets = _load_secrets_file(str(secrets_path))

    assert secrets["codex_oauth_token"] == "sk-codex-access-xyz"
    assert secrets["codex_oauth_refresh_token"] == "sk-codex-refresh-abc"
    assert secrets["codex_oauth_expires_at"] == 1234567890


def test_secrets_parser_handles_empty_codex_expires_at(tmp_path):
    """Empty ``codex_oauth_expires_at`` parses as 0 (matches BridgeConfig default)."""
    secrets_path = tmp_path / ".secrets"
    _write_private_secrets(
        secrets_path,
        "codex_oauth_token=sk-codex-access-xyz\n"
        "codex_oauth_expires_at=\n",
    )

    secrets = _load_secrets_file(str(secrets_path))

    assert secrets["codex_oauth_token"] == "sk-codex-access-xyz"
    assert secrets["codex_oauth_expires_at"] == 0


# ---------------------------------------------------------------------------
# Case 2 — fail-closed boot when codex resolved via registry but token empty
# ---------------------------------------------------------------------------


def test_validator_fails_closed_when_specialist_override_codex_without_token():
    """When a specialist override = ``codex`` and the OAuth token is empty,
    ``_validate_codex_oauth`` refuses to boot with an actionable error."""
    config = _StubConfig(
        backends_enabled=True,
        backends_specialists_overrides={"code-reviewer": "codex"},
        codex_oauth_token="",
    )

    with pytest.raises(RuntimeError, match="codex_oauth_token is missing"):
        _validate_codex_oauth(config)


def test_validator_fails_closed_when_main_backend_is_codex():
    """The validator also catches ``backends_main = codex`` with empty token."""
    config = _StubConfig(
        backends_enabled=True,
        backends_main="codex",
        codex_oauth_token="",
    )

    with pytest.raises(RuntimeError, match="backend 'codex' is configured"):
        _validate_codex_oauth(config)


def test_validator_error_message_names_remediation_workflow():
    """The error message must name both the missing knob and the remediation
    path — mirrors the ``vapi_webhook_secret`` / ``allow_remote_bind``
    precedent of telling the operator exactly what to do."""
    config = _StubConfig(
        backends_enabled=True,
        backends_chiefs_default="codex",
        codex_oauth_token="",
    )

    with pytest.raises(RuntimeError) as excinfo:
        _validate_codex_oauth(config)

    msg = str(excinfo.value)
    assert "codex_oauth_token" in msg
    assert "codex login" in msg
    assert ".secrets" in msg


# ---------------------------------------------------------------------------
# Case 3 — legacy claude-only mode boots clean regardless of codex fields
# ---------------------------------------------------------------------------


def test_validator_noop_when_backends_disabled():
    """``backends_enabled=False`` means the [backends] registry is dormant;
    the validator must not fire even with an empty codex_oauth_token."""
    config = _StubConfig(
        backends_enabled=False,
        backends_main="codex",  # deliberately set; should be ignored
        codex_oauth_token="",
    )

    # Should NOT raise.
    _validate_codex_oauth(config)


def test_validator_noop_when_no_role_is_codex():
    """If no role in the [backends] registry resolves to ``codex``, the
    Codex OAuth fields are irrelevant — boot proceeds cleanly."""
    config = _StubConfig(
        backends_enabled=True,
        backends_main="claude",
        backends_chiefs_default="claude",
        backends_specialists_default="claude",
        backends_specialists_overrides={},
        codex_oauth_token="",  # empty is fine — codex isn't configured
    )

    _validate_codex_oauth(config)


def test_validator_noop_when_codex_configured_with_valid_token():
    """The happy path: codex IS configured, AND the token is populated."""
    config = _StubConfig(
        backends_enabled=True,
        backends_main="codex",
        codex_oauth_token="sk-codex-access-xyz",
    )

    _validate_codex_oauth(config)


def test_validator_tolerates_pre_codex_3_config():
    """When the config object predates Codex-3 (no ``backends_*`` attributes
    at all), the validator must be a no-op so the live Claude-only boot
    path is unaffected."""

    class _BareConfig:
        # Intentionally missing every backends_* and codex_oauth_* field.
        pass

    _validate_codex_oauth(_BareConfig())


# ---------------------------------------------------------------------------
# Case 4 — Claude OAuth + Codex OAuth coexist in .secrets without cross-talk
# ---------------------------------------------------------------------------


def test_secrets_parser_loads_both_oauth_triples_independently(tmp_path):
    """A ``.secrets`` file with BOTH triples parses each into its own keys."""
    secrets_path = tmp_path / ".secrets"
    _write_private_secrets(
        secrets_path,
        "claude_oauth_token=sk-ant-access-1\n"
        "claude_oauth_refresh_token=sk-ant-refresh-1\n"
        "claude_oauth_expires_at=1111111111\n"
        "codex_oauth_token=sk-codex-access-2\n"
        "codex_oauth_refresh_token=sk-codex-refresh-2\n"
        "codex_oauth_expires_at=2222222222\n",
    )

    secrets = _load_secrets_file(str(secrets_path))

    assert secrets["claude_oauth_token"] == "sk-ant-access-1"
    assert secrets["claude_oauth_refresh_token"] == "sk-ant-refresh-1"
    assert secrets["claude_oauth_expires_at"] == 1111111111
    assert secrets["codex_oauth_token"] == "sk-codex-access-2"
    assert secrets["codex_oauth_refresh_token"] == "sk-codex-refresh-2"
    assert secrets["codex_oauth_expires_at"] == 2222222222


# ---------------------------------------------------------------------------
# Case 5 — expired Codex token is flagged for refresh, not fail-closed
# ---------------------------------------------------------------------------


def test_codex_auth_holder_flags_expired_token_for_refresh():
    """An expired access token (``expires_at`` already past + margin) reports
    ``needs_refresh() == True``. The refresh attempt is the next-step
    responsibility; the bridge does NOT fail-closed on staleness alone."""
    past = int(time.time()) - 10_000  # 10k seconds in the past
    holder = CodexAuthHolder(
        access_token="sk-codex-stale",
        refresh_token="sk-codex-refresh",
        expires_at=past,
    )

    assert holder.needs_refresh() is True


def test_codex_auth_holder_does_not_flag_fresh_token():
    """A token whose expiry is comfortably in the future is not refreshed."""
    future = int(time.time()) + 24 * 3600  # 24h from now
    holder = CodexAuthHolder(
        access_token="sk-codex-fresh",
        refresh_token="sk-codex-refresh",
        expires_at=future,
    )

    assert holder.needs_refresh() is False


def test_codex_auth_holder_flags_missing_token_for_refresh():
    """An empty access_token is also flagged for refresh — the holder is
    in an unconfigured state and the caller must decide whether to refresh
    or fail-closed depending on context."""
    holder = CodexAuthHolder(access_token="", refresh_token="", expires_at=0)

    assert holder.needs_refresh() is True


def test_codex_auth_holder_with_no_expiry_treated_as_fresh():
    """``expires_at = 0`` means the seeded triple has no expiry info — the
    holder treats this as fresh so the refresh loop doesn't spin forever.
    Matches the Claude refresher's ``_expires_at == 0`` heuristic."""
    holder = CodexAuthHolder(
        access_token="sk-codex-access",
        refresh_token="sk-codex-refresh",
        expires_at=0,
    )

    assert holder.needs_refresh() is False


# ---------------------------------------------------------------------------
# Codex-7-followup (#1872) — refresh() and materialize_auth_json() wired
# against the documented contracts (codex-oauth-refresh.md +
# codex-auth-json-schema.md). The two stubs that previously raised
# NotImplementedError now exercise live primitives; the cases below replace
# the old "still not implemented" assertions.
# ---------------------------------------------------------------------------


def _build_jwt(exp_claim: int) -> str:
    """Build a minimal unsigned JWT with the given ``exp`` claim.

    Only the payload segment carries useful data — ``_decode_jwt_exp`` only
    inspects the middle segment. Header / signature are arbitrary placeholders.
    """
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload_bytes = json.dumps({"exp": exp_claim}).encode()
    payload = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


def test_decode_jwt_exp_happy_path():
    """A well-formed JWT with an ``exp`` claim decodes to its integer value."""
    target_exp = int(time.time()) + 3600
    jwt = _build_jwt(target_exp)
    assert _decode_jwt_exp(jwt) == target_exp


def test_decode_jwt_exp_malformed_returns_zero():
    """Garbage input must NOT raise — return 0 so callers can fall back."""
    # Various malformations: empty string, single segment, non-base64
    # payload, valid base64 but not JSON, JSON without exp claim.
    assert _decode_jwt_exp("") == 0
    assert _decode_jwt_exp("only-one-segment") == 0
    assert _decode_jwt_exp("aaa.!!!.bbb") == 0
    junk_b64 = base64.urlsafe_b64encode(b"not json").rstrip(b"=").decode()
    assert _decode_jwt_exp(f"hdr.{junk_b64}.sig") == 0
    empty_payload = base64.urlsafe_b64encode(b"{}").rstrip(b"=").decode()
    assert _decode_jwt_exp(f"hdr.{empty_payload}.sig") == 0


def test_classify_401_known_codes():
    """``error.code`` and top-level ``code`` shapes both map known values."""
    nested = '{"error": {"code": "refresh_token_expired"}}'
    assert _classify_401(nested) == "refresh_token_expired"
    top_level = '{"code": "refresh_token_reused"}'
    assert _classify_401(top_level) == "refresh_token_reused"
    invalidated = '{"error": {"code": "refresh_token_invalidated"}}'
    assert _classify_401(invalidated) == "refresh_token_invalidated"


def test_classify_401_unknown_returns_unknown_401():
    """Anything not in the known set falls back to ``unknown_401``."""
    assert _classify_401("garbage") == "unknown_401"
    assert _classify_401("") == "unknown_401"
    assert _classify_401('{"error": {"code": "rate_limited"}}') == "unknown_401"
    assert _classify_401('{"unrelated": "shape"}') == "unknown_401"


# ---------------------------------------------------------------------------
# Codex-7-followup — refresh() against a mocked endpoint
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Tiny stand-in for ``urllib.request.urlopen``'s context manager.

    Yields a body via ``.read()``. Codex-7-followup's refresh path reads
    + decodes JSON — that's all the surface this fixture needs to cover.
    """

    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _mock_urlopen_returning(payload: dict) -> object:
    """Build a callable that mimics urllib's ``urlopen``, returning ``payload``."""

    def _fake(*args, **kwargs):
        return _FakeResponse(json.dumps(payload))

    return _fake


def _mock_urlopen_raising_401(body: str):
    """Build a callable that mimics urllib's ``urlopen``, raising HTTPError 401."""
    import urllib.error
    import io

    def _fake(*args, **kwargs):
        raise urllib.error.HTTPError(
            url="https://auth.openai.com/oauth/token",
            code=401,
            msg="Unauthorized",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(body.encode("utf-8")),
        )

    return _fake


def test_refresh_happy_path_updates_all_fields():
    """200 OK with all three fields rotates the in-memory quartet, and
    ``_expires_at`` is derived from the new id_token JWT's ``exp`` claim."""
    target_exp = int(time.time()) + 3600
    new_id_token = _build_jwt(target_exp)

    holder = CodexAuthHolder(
        access_token="old-access",
        refresh_token="old-refresh",
        expires_at=int(time.time()) - 100,
        id_token=_build_jwt(int(time.time()) - 200),
    )

    response = {
        "access_token": "new-access",
        "refresh_token": "new-refresh",
        "id_token": new_id_token,
    }

    with patch(
        "bridge.backends._auth.urllib.request.urlopen",
        side_effect=_mock_urlopen_returning(response),
    ):
        asyncio.run(holder.refresh())

    assert holder.access_token == "new-access"
    assert holder.refresh_token == "new-refresh"
    assert holder.id_token == new_id_token
    assert holder.expires_at == target_exp


def test_refresh_partial_response_does_not_overwrite():
    """200 OK omitting fields keeps the existing values intact
    (update-only-if-present, mirrors Codex CLI persist_tokens behaviour)."""
    old_id_token = _build_jwt(int(time.time()) + 7200)
    holder = CodexAuthHolder(
        access_token="old-access",
        refresh_token="old-refresh",
        expires_at=int(time.time()) + 7200,
        id_token=old_id_token,
    )

    # Server omits id_token; only rotates access_token.
    response = {"access_token": "new-access"}

    with patch(
        "bridge.backends._auth.urllib.request.urlopen",
        side_effect=_mock_urlopen_returning(response),
    ):
        asyncio.run(holder.refresh())

    assert holder.access_token == "new-access"
    assert holder.refresh_token == "old-refresh"  # unchanged
    assert holder.id_token == old_id_token  # unchanged
    assert holder.expires_at == int(time.time()) + 7200 or holder.expires_at > 0


def test_refresh_401_permanent_raises():
    """A 401 with a known-permanent error code raises
    ``CodexRefreshPermanentError`` carrying the code as its message."""
    holder = CodexAuthHolder(
        access_token="old-access",
        refresh_token="old-refresh",
        expires_at=int(time.time()) - 10,
        id_token=_build_jwt(int(time.time()) - 10),
    )

    body = '{"error": {"code": "refresh_token_expired"}}'
    with patch(
        "bridge.backends._auth.urllib.request.urlopen",
        side_effect=_mock_urlopen_raising_401(body),
    ):
        with pytest.raises(CodexRefreshPermanentError) as excinfo:
            asyncio.run(holder.refresh())

    assert "refresh_token_expired" in str(excinfo.value)


def test_refresh_401_unknown_raises_unknown_401():
    """A 401 with a malformed body raises ``CodexRefreshPermanentError`` with
    ``unknown_401`` as its message — operator still must re-auth."""
    holder = CodexAuthHolder(
        access_token="old-access",
        refresh_token="old-refresh",
        expires_at=int(time.time()) - 10,
    )

    with patch(
        "bridge.backends._auth.urllib.request.urlopen",
        side_effect=_mock_urlopen_raising_401("not json at all"),
    ):
        with pytest.raises(CodexRefreshPermanentError) as excinfo:
            asyncio.run(holder.refresh())

    assert "unknown_401" in str(excinfo.value)


def test_refresh_with_empty_refresh_token_raises_runtime():
    """An empty refresh_token short-circuits with RuntimeError before any
    network call — guards against silently posting an empty refresh."""
    holder = CodexAuthHolder(
        access_token="",
        refresh_token="",
        expires_at=0,
    )

    with pytest.raises(RuntimeError, match="empty refresh_token"):
        asyncio.run(holder.refresh())


# ---------------------------------------------------------------------------
# Codex-7-followup — materialize_auth_json() round-trip + atomic write
# ---------------------------------------------------------------------------


def test_materialize_auth_json_round_trip(tmp_path):
    """``materialize_auth_json`` writes a valid ``auth.json`` at mode 0600
    with all four managed fields populated and an ISO-8601 ``last_refresh``."""
    target_exp = int(time.time()) + 3600
    holder = CodexAuthHolder(
        access_token="acc-1",
        refresh_token="ref-1",
        expires_at=target_exp,
        id_token=_build_jwt(target_exp),
    )

    target = tmp_path / "auth.json"
    holder.materialize_auth_json(path=target)

    # File exists and is mode 0600.
    assert target.exists()
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0o600, got 0o{mode:o}"

    # File parses, has the contractual shape.
    data = json.loads(target.read_text())
    assert data["auth_mode"] == "chatgpt"
    assert data["tokens"]["access_token"] == "acc-1"
    assert data["tokens"]["refresh_token"] == "ref-1"
    assert data["tokens"]["id_token"] == _build_jwt(target_exp)
    # ISO-8601 UTC with trailing Z (no microsecond suffix mandated, but
    # the format must end in Z so the Codex CLI's chrono parser accepts it).
    last_refresh = data["last_refresh"]
    assert isinstance(last_refresh, str)
    assert last_refresh.endswith("Z")


def test_materialize_preserves_unmanaged_fields(tmp_path):
    """Pre-existing ``account_id``, ``agent_identity``, and the literal
    uppercase ``OPENAI_API_KEY`` field must round-trip untouched."""
    target = tmp_path / "auth.json"

    pre_existing = {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": "sk-some-static-key",
        "tokens": {
            "access_token": "stale-access",
            "refresh_token": "stale-refresh",
            "id_token": "stale-id",
            "account_id": "acc-workspace-42",
        },
        "agent_identity": "operator-jwt-blob",
        "last_refresh": "2026-01-01T00:00:00Z",
    }
    target.write_text(json.dumps(pre_existing, indent=2))

    holder = CodexAuthHolder(
        access_token="fresh-access",
        refresh_token="fresh-refresh",
        expires_at=int(time.time()) + 3600,
        id_token=_build_jwt(int(time.time()) + 3600),
    )

    holder.materialize_auth_json(path=target)

    data = json.loads(target.read_text())
    # Unmanaged fields preserved exactly.
    assert data["OPENAI_API_KEY"] == "sk-some-static-key"
    assert data["agent_identity"] == "operator-jwt-blob"
    assert data["tokens"]["account_id"] == "acc-workspace-42"
    # Managed fields rotated.
    assert data["tokens"]["access_token"] == "fresh-access"
    assert data["tokens"]["refresh_token"] == "fresh-refresh"
    assert data["auth_mode"] == "chatgpt"
    # last_refresh got bumped (not the seeded 2026-01-01 value).
    assert data["last_refresh"] != "2026-01-01T00:00:00Z"


def test_materialize_overwrites_corrupt_existing(tmp_path):
    """If the file on disk is corrupt JSON, the bridge overwrites it
    rather than refusing — the rotation must always succeed."""
    target = tmp_path / "auth.json"
    target.write_text("{ this is not valid json")

    holder = CodexAuthHolder(
        access_token="acc-1",
        refresh_token="ref-1",
        expires_at=int(time.time()) + 3600,
        id_token=_build_jwt(int(time.time()) + 3600),
    )

    holder.materialize_auth_json(path=target)

    data = json.loads(target.read_text())
    assert data["tokens"]["access_token"] == "acc-1"


def test_materialize_creates_parent_directory(tmp_path):
    """When the parent directory doesn't exist (first-time seeding), the
    bridge creates it. Mirrors the schema doc's ``mkdir(parents=True)``."""
    target = tmp_path / "deep" / "nested" / "auth.json"
    assert not target.parent.exists()

    holder = CodexAuthHolder(
        access_token="acc-1",
        refresh_token="ref-1",
        expires_at=int(time.time()) + 3600,
        id_token=_build_jwt(int(time.time()) + 3600),
    )

    holder.materialize_auth_json(path=target)

    assert target.exists()


def test_holder_constructed_with_id_token_exposes_property():
    """The fourth field round-trips through the property accessor —
    operator-seeded id_token reaches ``materialize_auth_json``."""
    jwt = _build_jwt(int(time.time()) + 3600)
    holder = CodexAuthHolder(
        access_token="acc-1",
        refresh_token="ref-1",
        expires_at=int(time.time()) + 3600,
        id_token=jwt,
    )
    assert holder.id_token == jwt


def test_holder_id_token_defaults_to_empty():
    """Existing call sites that don't pass ``id_token`` see ``""`` —
    keeps the Codex-4 surface back-compat for any test fixture that hasn't
    migrated to the four-field constructor yet."""
    holder = CodexAuthHolder(
        access_token="acc-1",
        refresh_token="ref-1",
        expires_at=0,
    )
    assert holder.id_token == ""


# ---------------------------------------------------------------------------
# Backend Operability S2.1 (#2279) — _validate_backend_readiness wires
# ``readiness_for_flip`` into bridge startup. Mirrors the no-op / fail-closed
# pattern of ``_validate_codex_oauth`` above: token-present is no longer
# enough when Codex cost is not computable.
# ---------------------------------------------------------------------------


def test_active_backends_from_config_collects_all_roles():
    """``_active_backends_from_config`` returns the union of main + chiefs +
    specialists + override values, with empties filtered."""
    config = _StubConfig(
        backends_enabled=True,
        backends_main="codex",
        backends_chiefs_default="claude",
        backends_specialists_default="",
        backends_specialists_overrides={"code-reviewer": "codex", "ui": ""},
    )

    active = _active_backends_from_config(config)

    assert "codex" in active
    assert "claude" in active
    # Empty specialists_default + the empty override value are filtered out.
    assert "" not in active


def test_active_backends_from_config_returns_empty_for_bare_config():
    """A config missing every ``backends_*`` attribute returns an empty
    tuple — matches the pre-Codex-3 legacy path."""

    class _BareConfig:
        pass

    assert _active_backends_from_config(_BareConfig()) == ()


def test_codex_backend_with_token_still_fails_when_cost_not_computable():
    """The acceptance case from issue #2279 — a Codex deployment with an
    OAuth token populated still fails ``_validate_backend_readiness`` while
    ``codex_cost_computable()`` returns False. Without this guard, the
    daemon would boot and silently lose Codex cost accounting."""
    config = _StubConfig(
        backends_enabled=True,
        backends_main="codex",
        codex_oauth_token="token-present",
    )

    with pytest.raises(RuntimeError, match="codex_cost_computable"):
        _validate_backend_readiness(config)


def test_backend_readiness_passes_for_claude_only():
    """Claude-only backend configs still boot — the readiness guard only
    refuses on ``codex`` in the active set."""
    config = _StubConfig(
        backends_enabled=True,
        backends_main="claude",
        backends_chiefs_default="claude",
        backends_specialists_default="claude",
        codex_oauth_token="",
    )

    # Must not raise.
    _validate_backend_readiness(config)


def test_backend_readiness_noop_when_backends_disabled():
    """``backends_enabled=False`` is the legacy boot path — the guard is a
    no-op even when ``backends_main`` literally says ``codex``."""
    config = _StubConfig(
        backends_enabled=False,
        backends_main="codex",
        codex_oauth_token="token-present",
    )

    _validate_backend_readiness(config)


def test_backend_readiness_catches_codex_in_specialist_override():
    """The guard walks every role — a specialist override that resolves to
    ``codex`` is enough to refuse the flip even when ``backends_main`` is
    claude. Mirrors the Codex-4 OAuth validator's coverage."""
    config = _StubConfig(
        backends_enabled=True,
        backends_main="claude",
        backends_chiefs_default="claude",
        backends_specialists_default="claude",
        backends_specialists_overrides={"code-reviewer": "codex"},
        codex_oauth_token="token-present",
    )

    with pytest.raises(RuntimeError, match="codex_cost_computable"):
        _validate_backend_readiness(config)


def test_backend_readiness_tolerates_pre_codex_3_config():
    """When the config object predates the Codex-3 ``backends_*`` fields
    entirely, the readiness guard must be a no-op — same posture as the
    OAuth validator so the live claude-only boot path is unaffected."""

    class _BareConfig:
        # Intentionally missing every backends_* attribute.
        pass

    _validate_backend_readiness(_BareConfig())
