"""Tests for zone4-warmth.D.01 (#2299) — extended idle timeout + blob cleanup.

The D.01 sprint changes three things in the chief-session reaper:

1. Default idle timeout flips 1800s (30 min) -> 14400s (4 hours) at the
   ``BridgeConfig.chief_dispatcher_idle_timeout_seconds`` level.
2. Per-team overrides land via ``team.constraints.warm_idle_timeout_seconds``
   so high-volume departments (Ops/JobSearch) can keep a 10-minute window
   while low-volume departments (Board/Strategy) ride the 4h default.
3. On reap, the persisted ``message_history_blob`` column is cleared to
   NULL and a ``chief_session.history_cleared`` event fires so observability
   can pin the bloat-prevention behavior in production.

These tests cover the seven mandatory cases from the sprint spec and use
the ``InMemoryChiefSessionStore`` because the reaper-store contract is
the same shape for both the SQLite and in-memory impls.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bridge.background_loops import (
    _resolve_team_idle_timeout,
    chief_session_reaper_loop,
)
from bridge.chief_session import ChiefSession, ChiefSessionState
from bridge.chief_session_store import InMemoryChiefSessionStore


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _make_idle_session(
    *,
    session_id: str = "cs-d01000000",
    work_order_id: str = "wo-d01",
    department: str = "board",
    idle_seconds: float = 3600.0,
) -> ChiefSession:
    """Build an AWAITING_EVALUATION session that has been idle for ``idle_seconds``."""
    return ChiefSession(
        session_id=session_id,
        work_order_id=work_order_id,
        department=department,
        chief_name=f"{department}-chief",
        state=ChiefSessionState.AWAITING_EVALUATION,
        idle_since_utc=_utc_now() - timedelta(seconds=idle_seconds),
    )


def _make_registry(timeouts: dict[str, int | None]):
    """Build a minimal DepartmentRegistry-shaped stub.

    ``timeouts`` maps department name -> warm_idle_timeout_seconds (or None
    when the department has no override). Used by ``_resolve_team_idle_timeout``
    and the reaper's per-team filter path.
    """
    def _get_config(name: str):
        if name not in timeouts:
            raise KeyError(name)
        return SimpleNamespace(
            constraints=SimpleNamespace(
                warm_idle_timeout_seconds=timeouts[name],
            )
        )

    registry = MagicMock()
    registry.get_config.side_effect = _get_config
    registry.department_names.return_value = list(timeouts.keys())
    return registry


# ---------------------------------------------------------------------------
# Test 1 — A session within the 4h window stays warm.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_within_4h_window_not_reaped():
    """AWAITING_EVALUATION session 1h old, 4h window — stays warm."""
    store = InMemoryChiefSessionStore()
    session = _make_idle_session(
        session_id="cs-warm000001",
        department="board",
        idle_seconds=3600,  # 1h
    )
    await store.create(session)
    # Seed a blob so we can assert it survives.
    await store.update_message_history(session.session_id, b"warm-bytes")

    shutdown = asyncio.Event()
    shutdown.set()

    await chief_session_reaper_loop(
        shutdown,
        chief_session_store=store,
        idle_timeout_seconds=14400,  # 4 hours
        event_bus=None,
    )

    final = await store.get(session.session_id)
    assert final.state == ChiefSessionState.AWAITING_EVALUATION
    # Blob still present — reap-only clearing semantics.
    blob = await store.get_message_history_blob(session.session_id)
    assert blob == b"warm-bytes"


# ---------------------------------------------------------------------------
# Test 2 — A session past the 4h window is reaped and its blob cleared.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_past_4h_window_reaped_and_blob_cleared():
    """AWAITING_EVALUATION session 5h old, 4h window — reaped + blob NULL'd."""
    store = InMemoryChiefSessionStore()
    event_bus = MagicMock()
    event_bus.publish = MagicMock(return_value=None)

    session = _make_idle_session(
        session_id="cs-cold000001",
        department="board",
        idle_seconds=5 * 3600,  # 5h
    )
    await store.create(session)
    await store.update_message_history(session.session_id, b"stale-bytes")

    shutdown = asyncio.Event()
    shutdown.set()

    await chief_session_reaper_loop(
        shutdown,
        chief_session_store=store,
        idle_timeout_seconds=14400,
        event_bus=event_bus,
    )

    # Session walked AWAITING_EVALUATION -> TIMED_OUT -> SHUTDOWN.
    final = await store.get(session.session_id)
    assert final.state == ChiefSessionState.SHUTDOWN

    # Blob cleared to NULL (in-memory dict drops the entry).
    blob = await store.get_message_history_blob(session.session_id)
    assert blob is None

    # Both events fired.
    event_types = [call.args[0] for call in event_bus.publish.call_args_list]
    assert "chief_session.history_cleared" in event_types
    assert "chief_session.timed_out" in event_types

    # history_cleared payload shape.
    history_call = next(
        call for call in event_bus.publish.call_args_list
        if call.args[0] == "chief_session.history_cleared"
    )
    history_payload = history_call.args[1]
    assert history_payload["session_id"] == "cs-cold000001"
    assert history_payload["reason"] == "idle_timeout"


# ---------------------------------------------------------------------------
# Test 3 — Per-team override shortens the window for high-churn teams.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_team_override_reaps_ops_session_at_10_minutes():
    """Ops team has a 600s override; a session 30 min old falls past it."""
    store = InMemoryChiefSessionStore()
    event_bus = MagicMock()
    event_bus.publish = MagicMock(return_value=None)

    session = _make_idle_session(
        session_id="cs-ops0000001",
        department="ops",
        idle_seconds=1800,  # 30 min
    )
    await store.create(session)
    await store.update_message_history(session.session_id, b"ops-bytes")

    registry = _make_registry({"ops": 600})  # 10 min override

    shutdown = asyncio.Event()
    shutdown.set()

    await chief_session_reaper_loop(
        shutdown,
        chief_session_store=store,
        idle_timeout_seconds=14400,  # global 4h; ops override wins
        event_bus=event_bus,
        department_registry=registry,
    )

    final = await store.get(session.session_id)
    assert final.state == ChiefSessionState.SHUTDOWN

    blob = await store.get_message_history_blob(session.session_id)
    assert blob is None

    # team_timeout_seconds plumbed into the timed_out payload at 600s.
    timed_out_call = next(
        call for call in event_bus.publish.call_args_list
        if call.args[0] == "chief_session.timed_out"
    )
    assert timed_out_call.args[1]["team_timeout_seconds"] == 600.0


# ---------------------------------------------------------------------------
# Test 4 — Resolver falls back to the global default when no team override.
# ---------------------------------------------------------------------------


def test_resolve_team_idle_timeout_falls_back_to_global():
    """If a team has no override, the global default applies."""
    registry = _make_registry({"board": None})
    result = _resolve_team_idle_timeout("board", 14400.0, registry)
    assert result == 14400.0


def test_resolve_team_idle_timeout_uses_per_team_when_set():
    """When the team has a numeric override, it wins."""
    registry = _make_registry({"ops": 600})
    result = _resolve_team_idle_timeout("ops", 14400.0, registry)
    assert result == 600.0


def test_resolve_team_idle_timeout_no_registry_uses_global():
    """A None registry collapses to the global default."""
    result = _resolve_team_idle_timeout("anything", 14400.0, None)
    assert result == 14400.0


# ---------------------------------------------------------------------------
# Test 5 — REGRESSION: EXECUTING sessions are never reaped.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executing_sessions_never_reaped():
    """In-flight runs (EXECUTING) must not be targeted by the reaper.

    ``list_idle`` filters on state=AWAITING_EVALUATION at the store layer,
    so an EXECUTING session — no matter how old its created_at_utc — is
    invisible to the reaper.
    """
    store = InMemoryChiefSessionStore()
    session = ChiefSession(
        session_id="cs-exec000001",
        work_order_id="wo-exec",
        department="board",
        chief_name="board-chief",
        state=ChiefSessionState.EXECUTING,
        execution_started_at_utc=_utc_now() - timedelta(hours=10),
    )
    await store.create(session)

    shutdown = asyncio.Event()
    shutdown.set()

    await chief_session_reaper_loop(
        shutdown,
        chief_session_store=store,
        idle_timeout_seconds=14400,
        event_bus=None,
    )

    final = await store.get(session.session_id)
    assert final.state == ChiefSessionState.EXECUTING


# ---------------------------------------------------------------------------
# Test 6 — BridgeConfig default is 14400.
# ---------------------------------------------------------------------------


def test_config_default_is_14400():
    """Phase 4 (D.01) flipped 1800 -> 14400 to match warm-reuse intent."""
    from bridge.config import BridgeConfig

    cfg = BridgeConfig()
    assert cfg.chief_dispatcher_idle_timeout_seconds == 14400.0


# ---------------------------------------------------------------------------
# Test 7 — Team YAML schema accepts warm_idle_timeout_seconds round-trip.
# ---------------------------------------------------------------------------


def test_team_yaml_supports_warm_idle_timeout():
    """The new Constraints field round-trips through the YAML loader."""
    from teams._config import load_department_config_from_string

    yaml_text = """
team:
  name: testteam
  zone: 4
  description: test
  chief:
    name: test-chief
    model: openrouter:deepseek/deepseek-chat
    adapter: openrouter
    role: chief
    system_prompt: test
    expertise: test
  workers: []
  constraints:
    cost_limit_usd: 1.50
    timeout_seconds: 600
    concurrency_limit: 4
    expected_min_specialists: 0
    warm_idle_timeout_seconds: 600
    usage_limits:
      request_limit: 20
      request_token_limit: 50000
      response_token_limit: 20000
  budget:
    daily_limit_usd: 5.00
    alert_thresholds: [0.50, 0.75, 0.90]
  tools:
    common: []
    department: []
    per_employee: {}
    allowed_tools: []
    denied_tools: []
  mcp:
    mode: permissive
    allowed_servers: []
  vapi:
    enabled: false
"""
    cfg = load_department_config_from_string(yaml_text, source="<test>")
    assert cfg.constraints.warm_idle_timeout_seconds == 600


def test_team_yaml_warm_idle_timeout_optional():
    """Omitting warm_idle_timeout_seconds is valid — defaults to None."""
    from teams._config import load_department_config_from_string

    yaml_text = """
team:
  name: testteam
  zone: 4
  description: test
  chief:
    name: test-chief
    model: openrouter:deepseek/deepseek-chat
    adapter: openrouter
    role: chief
    system_prompt: test
    expertise: test
  workers: []
  constraints:
    cost_limit_usd: 1.50
    timeout_seconds: 600
    concurrency_limit: 4
    expected_min_specialists: 0
    usage_limits:
      request_limit: 20
      request_token_limit: 50000
      response_token_limit: 20000
  budget:
    daily_limit_usd: 5.00
    alert_thresholds: [0.50, 0.75, 0.90]
  tools:
    common: []
    department: []
    per_employee: {}
    allowed_tools: []
    denied_tools: []
  mcp:
    mode: permissive
    allowed_servers: []
  vapi:
    enabled: false
"""
    cfg = load_department_config_from_string(yaml_text, source="<test>")
    assert cfg.constraints.warm_idle_timeout_seconds is None
