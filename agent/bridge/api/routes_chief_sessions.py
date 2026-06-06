"""ChiefSession routes (Sprint P6.2 split).

Pure reorg from ``bridge.api_server``. These routes are conditionally
registered when ``chief_dispatcher_enabled = true`` is set on the
BridgeConfig (Z4-S12 #1383); the cost endpoint requires both the store
and the cost tracker to be wired (Z4-S42 #1401).

The conditional registration logic stays in ``APIServer._register_routes``;
this mixin contributes only the handlers themselves.

zone4-warmth.D.02 (#2300) added two observability extensions:

- The list handler now surfaces ``idle_seconds`` +
  ``warm_window_remaining_seconds`` on each AWAITING_EVALUATION row so the
  operator can spot a session minutes before the reaper sweeps it.
- A new aggregate endpoint ``GET /api/chief_sessions/warmth_stats`` returns
  a population summary (counts by state, average/oldest warm-session age,
  24h reuse-vs-cold dispatch counts). Bearer-token auth applies via the
  global middleware — no per-route auth code.
"""
from __future__ import annotations

import collections
import logging
from datetime import datetime, timedelta, timezone

from aiohttp import web

from ._helpers import _error, _ok

logger = logging.getLogger(__name__)


class _ChiefSessionsRoutesMixin:
    """Provides /api/chief_sessions/* handlers (conditional registration)."""

    # ------------------------------------------------------------------
    # Z4-S12 (#1383) — ChiefSession REST endpoints
    # ------------------------------------------------------------------

    async def _handle_list_chief_sessions(
        self, request: web.Request
    ) -> web.Response:
        """GET /api/chief_sessions — list chief sessions with optional filters.

        Query params (all optional):
            work_order_id: return only sessions for this WorkOrder; uses
                ``ChiefSessionStore.list_by_work_order`` so the requeue
                lineage is preserved (oldest first).
            state: return only sessions in this lifecycle state. Must match
                a ``ChiefSessionState`` enum value (lowercase: "warm",
                "executing", etc.). Unknown values yield a 400.
            department: post-filter by department slug. Composes with the
                other two — the protocol does not expose a department index
                today, so this filter runs in Python after the store call.
            limit (default 50) / offset (default 0): pagination over the
                final filtered list.

        When neither ``work_order_id`` nor ``state`` is supplied, the
        handler returns the union of all non-SHUTDOWN sessions — matches
        the issue spec ("array of all non-SHUTDOWN sessions").

        Filtering precedence: ``work_order_id`` wins; if absent, ``state``
        is used; otherwise the non-SHUTDOWN aggregate. ``department``
        always composes on top.
        """
        store = getattr(self._bridge, "_chief_session_store", None)
        if store is None:
            return _error("Chief session store not initialized", 503)

        from bridge.chief_session import ChiefSessionState

        query = request.rel_url.query
        work_order_id = query.get("work_order_id")
        state_filter = query.get("state")
        department_filter = query.get("department")

        try:
            limit = int(query.get("limit", "50"))
            offset = int(query.get("offset", "0"))
        except ValueError:
            return _error("'limit' and 'offset' must be integers", 400)
        if limit < 0 or offset < 0:
            return _error("'limit' and 'offset' must be non-negative", 400)

        try:
            if work_order_id is not None:
                sessions = await store.list_by_work_order(work_order_id)
            elif state_filter is not None:
                try:
                    state = ChiefSessionState(state_filter)
                except ValueError:
                    return _error(f"Unknown state: {state_filter}", 400)
                sessions = await store.list_by_state(state)
            else:
                # Non-SHUTDOWN aggregate — one list_by_state call per non-
                # terminal state. Cheaper than scanning the whole table for
                # the small N (8 states, SHUTDOWN excluded).
                sessions = []
                for s in ChiefSessionState:
                    if s == ChiefSessionState.SHUTDOWN:
                        continue
                    sessions.extend(await store.list_by_state(s))
        except Exception as exc:
            logger.exception("ChiefSession list lookup failed")
            return _error(str(exc), 500)

        if department_filter is not None:
            sessions = [
                s for s in sessions if s.department == department_filter
            ]

        total = len(sessions)
        page = sessions[offset : offset + limit]

        # zone4-warmth.D.02 (#2300) — surface per-session idle telemetry on
        # AWAITING_EVALUATION rows. EXECUTING / WARM / COLD / terminal rows
        # do not carry these fields (the idle clock is meaningless when the
        # chief is mid-run or already shut down). The per-team timeout is
        # resolved via the D.01 helper so departments with shorter overrides
        # show the correct remaining window.
        from bridge.background_loops import _resolve_team_idle_timeout

        bridge_config = getattr(self._bridge, "_config", None)
        department_registry = getattr(self._bridge, "_departments", None)
        global_timeout = float(getattr(
            bridge_config, "chief_dispatcher_idle_timeout_seconds", 14400.0
        )) if bridge_config is not None else 14400.0

        now = datetime.now(timezone.utc)
        rows: list[dict] = []
        for s in page:
            d = s.to_dict()
            if (
                s.state == ChiefSessionState.AWAITING_EVALUATION
                and s.idle_since_utc is not None
            ):
                idle_seconds = (now - s.idle_since_utc).total_seconds()
                team_timeout = _resolve_team_idle_timeout(
                    s.department, global_timeout, department_registry
                )
                d["idle_seconds"] = idle_seconds
                d["warm_window_remaining_seconds"] = max(
                    0.0, team_timeout - idle_seconds
                )
            rows.append(d)

        return _ok({
            "sessions": rows,
            "count": len(rows),
            "total": total,
            "limit": limit,
            "offset": offset,
        })

    async def _handle_get_chief_session(
        self, request: web.Request
    ) -> web.Response:
        """GET /api/chief_sessions/{session_id} — single session detail.

        Returns ``404`` if the session is not found (not 503 — a missing
        row is not a configuration error). Returns ``503`` only when the
        store itself isn't wired.
        """
        store = getattr(self._bridge, "_chief_session_store", None)
        if store is None:
            return _error("Chief session store not initialized", 503)

        from bridge.chief_session_store import ChiefSessionNotFoundError

        session_id = request.match_info["session_id"]
        try:
            session = await store.get(session_id)
        except ChiefSessionNotFoundError:
            return _error(f"Chief session not found: {session_id}", 404)
        except Exception as exc:
            logger.exception(
                "ChiefSession get failed for %s", session_id
            )
            return _error(str(exc), 500)

        return _ok(session.to_dict())

    async def _handle_get_chief_session_cost(
        self, request: web.Request
    ) -> web.Response:
        """GET /api/chief_sessions/{session_id}/cost — per-session cost.

        Z4-S42 (#1401). Surfaces both the store-side cached total
        (``ChiefSession.cost_usd``, accumulated via ``add_cost`` on each
        run) and the live JSONL recompute (``CostTracker.get_session_cost``,
        Z4-S40). The two values can drift if a cost write landed before
        the store update — exposing both lets the dashboard detect that.

        Query params:
            include_entries (bool, default false): when truthy
                ("1"/"true"/"yes"), also return the list of CostEntry rows
                tagged with this ``chief_session_id``. Off by default
                because the entries can be large for long-running
                sessions.

        Returns:
            200 with ``{session_id, session_cost_usd, total_usd,
            entries?}`` on success. ``entries`` is included only when
            ``include_entries`` is truthy. The list may be empty if no
            JSONL rows are tagged with this session yet.
            404 when the session id is unknown.
            503 when the store or cost tracker isn't wired (defensive —
            the route registration already guards both).
        """
        store = getattr(self._bridge, "_chief_session_store", None)
        if store is None:
            return _error("Chief session store not initialized", 503)

        cost_tracker = getattr(self._bridge, "_cost_tracker", None)
        if cost_tracker is None:
            return _error("Cost tracker not initialized", 503)

        from bridge.chief_session_store import ChiefSessionNotFoundError

        session_id = request.match_info["session_id"]
        try:
            session = await store.get(session_id)
        except ChiefSessionNotFoundError:
            return _error(f"Chief session not found: {session_id}", 404)
        except Exception as exc:
            logger.exception(
                "ChiefSession cost lookup failed for %s", session_id
            )
            return _error(str(exc), 500)

        # Live JSONL recompute. Independent of session.cost_usd; the two
        # may differ if a cost write landed before the store update.
        try:
            live_total = cost_tracker.get_session_cost(session_id)
        except Exception as exc:
            logger.exception(
                "CostTracker.get_session_cost failed for %s", session_id
            )
            return _error(str(exc), 500)

        # ``include_entries`` is opt-in to keep the default response
        # small. Accept the common truthy spellings; anything else
        # (including empty) is treated as false.
        include_param = request.rel_url.query.get(
            "include_entries", ""
        ).strip().lower()
        include_entries = include_param in {"1", "true", "yes"}

        payload: dict = {
            "session_id": session_id,
            "session_cost_usd": session.cost_usd,
            "total_usd": live_total,
        }

        if include_entries:
            # Linear scan via the public reader; matches the
            # get_session_cost path so the two values share semantics.
            try:
                all_entries = cost_tracker._read_entries()
            except Exception as exc:
                logger.exception(
                    "CostTracker._read_entries failed for %s", session_id
                )
                return _error(str(exc), 500)
            from dataclasses import asdict
            payload["entries"] = [
                asdict(e) for e in all_entries
                if e.chief_session_id == session_id
            ]

        return _ok(payload)

    # ------------------------------------------------------------------
    # zone4-warmth.D.02 (#2300) — warm-session population summary
    # ------------------------------------------------------------------

    async def _handle_chief_sessions_warmth_stats(
        self, request: web.Request
    ) -> web.Response:
        """GET /api/chief_sessions/warmth_stats — aggregate warm-session stats.

        Returns a snapshot of the warm-session population intended for the
        operator to read at a glance (Discord ``/warmth_stats`` wraps this).
        Six fields:

        - ``by_state``: counter keyed on ``ChiefSessionState.value``; all
          non-SHUTDOWN sessions are summed. SHUTDOWN rows are archival and
          intentionally excluded — they would dwarf the live counts in any
          long-running bridge.
        - ``warm_session_count``: convenience alias for the
          ``AWAITING_EVALUATION`` bucket.
        - ``warm_session_average_age_seconds`` /
          ``warm_session_oldest_age_seconds``: idle-clock ages, computed
          from ``idle_since_utc``. Sessions whose ``idle_since_utc`` is
          None are skipped from the age aggregation (they should not exist
          in AWAITING_EVALUATION but we don't trust the data — a partial
          row should never crash the endpoint).
        - ``warmth_reused_events_24h`` / ``cold_start_events_24h``: counts
          of ``chief_dispatcher.warmth_reused`` and ``chief_dispatcher.routed``
          events emitted in the last 24h (UTC). Read by replaying the
          JSONL ledger; cheap because the daily files cap at one read each.
        - ``reuse_rate_24h``: ``warmth_reused / (warmth_reused + cold)``,
          clipped to ``0.0`` when the denominator is zero so a quiet bridge
          surfaces a value rather than NaN/None.

        503 when the store isn't wired (matches the rest of this mixin).
        The event bus is best-effort — when it's None or the replay fails,
        the 24h counts fall back to zero so the warm-population fields stay
        meaningful in degraded wiring.
        """
        store = getattr(self._bridge, "_chief_session_store", None)
        if store is None:
            return _error("Chief session store not initialized", 503)

        from bridge.chief_session import ChiefSessionState

        # ---- Walk all non-SHUTDOWN sessions ------------------------
        try:
            sessions: list = []
            for state in ChiefSessionState:
                if state == ChiefSessionState.SHUTDOWN:
                    continue
                sessions.extend(await store.list_by_state(state))
        except Exception as exc:
            logger.exception("warmth_stats list lookup failed")
            return _error(str(exc), 500)

        by_state: dict[str, int] = dict(
            collections.Counter(s.state.value for s in sessions)
        )

        now = datetime.now(timezone.utc)
        warm = [
            s for s in sessions
            if s.state == ChiefSessionState.AWAITING_EVALUATION
        ]
        ages = [
            (now - s.idle_since_utc).total_seconds()
            for s in warm
            if s.idle_since_utc is not None
        ]
        avg_age = sum(ages) / len(ages) if ages else 0.0
        max_age = max(ages) if ages else 0.0

        # ---- Replay the JSONL event ledger -------------------------
        # ``EventBus.replay`` is sync and reads the persisted daily
        # files; we filter to the last 24h in Python because the bus
        # API exposes ``since_timestamp`` as an ISO-8601 string rather
        # than a delta. Failures (no event bus, no data dir, malformed
        # JSONL) all fall through to zero counts — observability never
        # blocks on its own degraded wiring.
        reused = 0
        routed = 0
        try:
            event_bus = self._resolve_event_bus()
            if event_bus is not None:
                cutoff_iso = (
                    now - timedelta(hours=24)
                ).isoformat()
                reused_events = event_bus.replay(
                    event_type="chief_dispatcher.warmth_reused",
                    since_timestamp=cutoff_iso,
                )
                routed_events = event_bus.replay(
                    event_type="chief_dispatcher.routed",
                    since_timestamp=cutoff_iso,
                )
                reused = len(reused_events)
                routed = len(routed_events)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "warmth_stats event replay failed (counts default to 0): %s",
                exc,
            )

        total_dispatches = reused + routed
        reuse_rate = (
            (reused / total_dispatches) if total_dispatches > 0 else 0.0
        )

        return _ok({
            "by_state": by_state,
            "warm_session_count": len(warm),
            "warm_session_average_age_seconds": avg_age,
            "warm_session_oldest_age_seconds": max_age,
            "reuse_rate_24h": reuse_rate,
            "warmth_reused_events_24h": reused,
            "cold_start_events_24h": routed,
        })

    def _resolve_event_bus(self):
        """Return the live ``EventBus`` (or None) via the autonomy layer.

        The bridge keeps the bus on the ``AutonomyLayer`` (see
        ``BridgeApp._autonomy.event_bus``). When autonomy is unwired we
        return None so the caller can degrade gracefully.
        """
        autonomy = getattr(self._bridge, "_autonomy", None)
        if autonomy is None:
            return None
        return getattr(autonomy, "event_bus", None)
