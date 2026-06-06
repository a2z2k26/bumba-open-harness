"""Operator dashboard routes (Board Phase 2 WS1, #2391).

A single-page status view served over REST. The dashboard is a pure READ
aggregation over surfaces that already exist:

- service states + cumulative cost  ← ``data/service_state/*-state.json``
                                       (Board Phase 1 ``total_cost_usd``, #2390)
- active escalations                ← ``EscalationEngine._active_alerts``
- halt status                       ← ``SecurityManager.is_halted`` / reason
- wiring manifest summary           ← ``BridgeApp._wiring_report`` (#2391)
- cost totals                       ← ``CostTracker.get_daily_summary`` /
                                       ``get_weekly_summary``

It adds no new producer — every field is sourced from a component already
wired into ``BridgeApp``. This keeps the seam shallow: the consumer
(``/api/v1/dashboard`` JSON + ``/dashboard`` HTML) reads the same shapes the
existing ``/healthz``, ``/api/escalation``, and ``/api/cost`` endpoints read.

Path note: ``/api/v1/dashboard`` is deliberately distinct from the Zone 4
cost-report endpoint (owned by a separate workstream) — no collision.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from aiohttp import web

from ..staleness import is_service_stale
from ._helpers import _ok


def _aggregate_service_runs(service_dir: Path) -> list[dict]:
    """Read every known service-state file into a dashboard row.

    Each service contributes its most-recent run plus its lifetime cumulative
    cost (``total_cost_usd``, Board Phase 1). There is no per-run history in
    the state schema, so "surface runs" is one freshest row per service. Rows
    are sorted most-recent-activity first and the caller slices to 10.
    """
    from ..services.state_inventory import iter_known_service_state_files

    rows: list[dict] = []
    if not service_dir.exists():
        return rows

    for name, state_file in iter_known_service_state_files(service_dir):
        try:
            data = json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            rows.append({
                "service": name,
                "last_status": "error",
                "error": str(exc),
                "last_run": None,
                "total_cost_usd": 0.0,
                "stale": True,
            })
            continue
        last_run = data.get("last_run")
        rows.append({
            "service": name,
            "last_run": last_run,
            "last_status": data.get("last_status", "unknown"),
            "last_error": data.get("last_error"),
            "total_cost_usd": round(float(data.get("total_cost_usd", 0.0) or 0.0), 6),
            "total_runs": int(data.get("total_runs", 0) or 0),
            "stale": is_service_stale(last_run, name),
        })

    # Sort most-recent first; None last_run (never-run) sorts to the end.
    rows.sort(key=lambda r: (r.get("last_run") or ""), reverse=True)
    return rows


def _serialize_workflow_run(run) -> dict:
    """Render a durable ``WorkflowRun`` into a dashboard row (WS3.6, #2570).

    Mirrors ``routes_workflows._serialize_store_run`` minus the verbose
    ``context`` blob — the dashboard wants a compact recent-runs strip, so it
    carries the cost-reconciliation field (``cost_usd``) and run identity, not
    the full step context.
    """
    return {
        "id": run.id,
        "workflow_name": run.workflow_name,
        "status": run.status,
        "current_step": run.current_step,
        "cost_usd": run.cost_usd,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
    }


def _wiring_summary(report) -> dict:
    """Reduce a ``WiringReport`` to operator-facing counts + failure names.

    ``None`` (boot not yet complete) renders as a zeroed summary with
    ``available=False`` so the dashboard never 500s on early scrape.
    """
    if report is None:
        return {
            "available": False,
            "active": 0,
            "pending": 0,
            "errors": 0,
            "failed": 0,
            "failed_setters": [],
        }
    return {
        "available": True,
        "active": int(getattr(report, "active", 0)),
        "pending": len(getattr(report, "pending", []) or []),
        "errors": len(getattr(report, "errors", []) or []),
        "failed": len(getattr(report, "failed", []) or []),
        "failed_setters": [name for name, _reason in (getattr(report, "failed", []) or [])],
    }


class _DashboardRoutesMixin:
    """Provides the ``/api/v1/dashboard`` JSON + ``/dashboard`` HTML handlers."""

    def _register_dashboard_routes(self, app: web.Application) -> None:
        app.router.add_get("/api/v1/dashboard", self._handle_dashboard_json)
        app.router.add_get("/dashboard", self._handle_dashboard_html)

    # ------------------------------------------------------------------
    # JSON aggregation
    # ------------------------------------------------------------------

    async def _build_dashboard(self) -> dict:
        """Aggregate the read surfaces into the dashboard payload."""
        bridge = self._bridge

        # Service states + per-service cumulative cost (last 10 by activity).
        config = getattr(bridge, "_config", None)
        service_runs: list[dict] = []
        if config is not None:
            service_dir = Path(config.data_dir) / "service_state"
            service_runs = _aggregate_service_runs(service_dir)

        # Active escalations (reuse EscalationEngine shape from /api/escalation).
        active_escalations: list[dict] = []
        autonomy = getattr(bridge, "_autonomy", None)
        if autonomy is not None and getattr(autonomy, "escalation", None) is not None:
            engine = autonomy.escalation
            for source, alert in engine._active_alerts.items():
                active_escalations.append({
                    "source": source,
                    "level": int(alert.level),
                    "message": alert.message,
                    "triggered_at": alert.triggered_at,
                    "deferred": alert.deferred,
                })

        # Halt status.
        halt = {"halted": False, "reason": None}
        security = getattr(bridge, "_security", None)
        if security is not None:
            try:
                halted = security.is_halted()
                halt = {
                    "halted": bool(halted),
                    "reason": security.check_halt_flag() if halted else None,
                }
            except Exception:  # noqa: BLE001 — dashboard never 500s on a probe
                halt = {"halted": False, "reason": None}

        # Wiring manifest summary.
        wiring = _wiring_summary(getattr(bridge, "_wiring_report", None))

        # Cost totals + per-workflow attribution (WS3.3 by_workflow, #2570).
        cost: dict = {"daily": {}, "weekly": {}, "by_workflow": {}}
        tracker = getattr(bridge, "_cost_tracker", None)
        if tracker is not None:
            try:
                cost = {
                    "daily": tracker.get_daily_summary(),
                    "weekly": tracker.get_weekly_summary(),
                    "by_workflow": tracker.get_cost_by_workflow(),
                }
            except Exception:  # noqa: BLE001
                cost = {"daily": {}, "weekly": {}, "by_workflow": {}}

        # Recent workflow runs across all workflows (WS3.4 list_all_runs,
        # #2570). Sources the durable store; absent store -> empty list, never
        # 500s, mirroring the cost/escalation graceful-degradation pattern.
        workflow_runs: list[dict] = []
        store = getattr(bridge, "_workorder_store", None)
        if store is not None:
            try:
                workflow_runs = [
                    _serialize_workflow_run(r) for r in store.list_all_runs(limit=10)
                ]
            except Exception:  # noqa: BLE001
                workflow_runs = []

        return {
            "generated_at": time.time(),
            "halt": halt,
            "wiring": wiring,
            "active_escalations": active_escalations,
            "escalation_count": len(active_escalations),
            "service_runs": service_runs[:10],
            "cost": cost,
            "workflow_runs": workflow_runs,
        }

    async def _handle_dashboard_json(self, request: web.Request) -> web.Response:
        return _ok(await self._build_dashboard())

    # ------------------------------------------------------------------
    # Minimal HTML view
    # ------------------------------------------------------------------

    async def _handle_dashboard_html(self, request: web.Request) -> web.Response:
        """Serve a dependency-free, inline-CSS dashboard that polls the JSON.

        No external assets, no WebSocket. The page fetches
        ``/api/v1/dashboard`` on load and every 30s. Auth: the page itself is
        served behind the same bearer middleware as the JSON endpoint.
        """
        return web.Response(text=_DASHBOARD_HTML, content_type="text/html")


# Self-contained page. The fetch sends the same path the browser is on, so the
# bearer token from the operator's session/header flows through unchanged.
_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bumba Operator Dashboard</title>
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; font: 14px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace;
       background: #0b0d10; color: #d7dce1; padding: 24px; }
h1 { font-size: 18px; letter-spacing: .04em; margin: 0 0 4px; color: #f0c674; }
.sub { color: #6b7077; font-size: 12px; margin-bottom: 20px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
.card { background: #14171c; border: 1px solid #21262d; border-radius: 8px; padding: 16px; }
.card h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .08em;
           color: #8b949e; margin: 0 0 12px; }
.kv { display: flex; justify-content: space-between; padding: 3px 0; }
.kv b { color: #9ecbff; font-weight: 600; }
.pill { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; }
.ok { background: #18351f; color: #6fcf97; }
.warn { background: #3a2e12; color: #f0c674; }
.bad { background: #3a1a1a; color: #f08a8a; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th, td { text-align: left; padding: 4px 6px; border-bottom: 1px solid #21262d; }
th { color: #6b7077; font-weight: 500; }
.empty { color: #6b7077; font-style: italic; }
#err { color: #f08a8a; margin-bottom: 12px; }
</style>
</head>
<body>
<h1>BUMBA OPERATOR DASHBOARD</h1>
<div class="sub">Polls /api/v1/dashboard every 30s &middot; last update <span id="ts">—</span></div>
<div id="err"></div>
<div class="grid">
  <div class="card"><h2>Halt</h2><div id="halt"></div></div>
  <div class="card"><h2>Wiring</h2><div id="wiring"></div></div>
  <div class="card"><h2>Cost</h2><div id="cost"></div></div>
  <div class="card" style="grid-column: 1 / -1"><h2>Active Escalations</h2><div id="esc"></div></div>
  <div class="card" style="grid-column: 1 / -1"><h2>Recent Surface Runs</h2><div id="runs"></div></div>
  <div class="card" style="grid-column: 1 / -1"><h2>Recent Workflow Runs</h2><div id="wfruns"></div></div>
</div>
<script>
function kv(k, v) { return '<div class="kv"><span>' + k + '</span><b>' + v + '</b></div>'; }
function num(n) { return (n === undefined || n === null) ? '—' : n; }
function usd(n) { return '$' + (Number(n || 0)).toFixed(4); }
async function refresh() {
  try {
    const r = await fetch('/api/v1/dashboard', { headers: {} });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    document.getElementById('err').textContent = '';
    document.getElementById('ts').textContent = new Date().toLocaleTimeString();

    const h = d.halt || {};
    document.getElementById('halt').innerHTML =
      '<span class="pill ' + (h.halted ? 'bad' : 'ok') + '">' +
      (h.halted ? 'HALTED' : 'RUNNING') + '</span>' +
      (h.reason ? '<div class="kv"><span>reason</span><b>' + h.reason + '</b></div>' : '');

    const w = d.wiring || {};
    document.getElementById('wiring').innerHTML =
      kv('active', num(w.active)) + kv('pending', num(w.pending)) +
      kv('errors', num(w.errors)) + kv('failed', num(w.failed)) +
      ((w.failed_setters && w.failed_setters.length)
        ? '<div class="kv"><span>failed</span><b>' + w.failed_setters.join(', ') + '</b></div>' : '');

    const c = (d.cost && d.cost.daily) || {};
    const cw = (d.cost && d.cost.weekly) || {};
    const bw = (d.cost && d.cost.by_workflow) || {};
    const wfKeys = Object.keys(bw);
    document.getElementById('cost').innerHTML =
      kv('today', usd(c.total_cost)) + kv('today requests', num(c.request_count)) +
      kv('7-day', usd(cw.total_cost)) +
      (wfKeys.length
        ? wfKeys.map(function(k){ return kv('wf: ' + k, usd(bw[k].cost)); }).join('')
        : '');

    const esc = d.active_escalations || [];
    document.getElementById('esc').innerHTML = esc.length
      ? '<table><tr><th>source</th><th>level</th><th>message</th><th>at</th></tr>' +
        esc.map(function(e){ return '<tr><td>' + e.source + '</td><td>' + e.level +
          '</td><td>' + e.message + '</td><td>' + (e.triggered_at || '') + '</td></tr>'; }).join('') +
        '</table>'
      : '<div class="empty">none</div>';

    const runs = d.service_runs || [];
    document.getElementById('runs').innerHTML = runs.length
      ? '<table><tr><th>service</th><th>status</th><th>last run</th><th>cum. cost</th><th>runs</th></tr>' +
        runs.map(function(s){
          var cls = s.last_status === 'success' ? 'ok' : (s.last_status === 'failure' ? 'bad' : 'warn');
          return '<tr><td>' + s.service + '</td><td><span class="pill ' + cls + '">' +
            (s.last_status || '?') + (s.stale ? ' (stale)' : '') + '</span></td><td>' +
            (s.last_run || '—') + '</td><td>' + usd(s.total_cost_usd) + '</td><td>' +
            num(s.total_runs) + '</td></tr>'; }).join('') + '</table>'
      : '<div class="empty">no service state</div>';

    const wf = d.workflow_runs || [];
    document.getElementById('wfruns').innerHTML = wf.length
      ? '<table><tr><th>workflow</th><th>status</th><th>step</th><th>cost</th><th>created</th></tr>' +
        wf.map(function(r){
          var cls = r.status === 'completed' ? 'ok' : (r.status === 'failed' ? 'bad' : 'warn');
          return '<tr><td>' + r.workflow_name + '</td><td><span class="pill ' + cls + '">' +
            (r.status || '?') + '</span></td><td>' + num(r.current_step) + '</td><td>' +
            usd(r.cost_usd) + '</td><td>' + (r.created_at || '—') + '</td></tr>'; }).join('') + '</table>'
      : '<div class="empty">no workflow runs</div>';
  } catch (e) {
    document.getElementById('err').textContent = 'fetch failed: ' + e.message;
  }
}
refresh();
setInterval(refresh, 30000);
</script>
</body>
</html>"""
