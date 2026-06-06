"""
api_routes.py — Zone 4 Sprint 11

14 REST API routes under /api/z4/ for Zone 4 department observability.
Registers onto an existing aiohttp app, reusing bearer auth + CORS middleware.

Also defines Zone 4 event types for WebSocket streaming.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from aiohttp import web

logger = logging.getLogger(__name__)


# ── Zone 4 event types for WebSocket streaming ───────────────────────────────

Z4_EVENT_TYPES = frozenset({
    "z4.session.created",
    "z4.session.completed",
    "z4.session.failed",
    "z4.session.timeout",
    "z4.delegation.started",
    "z4.delegation.completed",
    "z4.delegation.failed",
    "z4.domain_violation",
    "z4.escalation.requested",
    "z4.escalation.completed",
    "z4.budget.warning",
    "z4.budget.exceeded",
})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _error(message: str, status: int = 400) -> web.Response:
    return web.json_response({"error": message}, status=status)


def _ok(data: Any, status: int = 200) -> web.Response:
    return web.json_response(data, status=status)


def _int_param(request: web.Request, name: str, default: int) -> int:
    """Extract an integer query parameter with a default."""
    try:
        return int(request.query.get(name, str(default)))
    except ValueError:
        return default


# ── Route handler class ──────────────────────────────────────────────────────

class Zone4Routes:
    """
    14 Zone 4 API routes.

    Requires:
    - sessions_dir: Path to the sessions directory
    - teams_dir: Path to the teams config directory
    - expertise_dir: Path to the expertise directory

    Optional (for richer responses):
    - tracker: ToolTracker instance
    - attributor: CostAttributor instance
    - aggregator: MetricsAggregator instance
    """

    def __init__(
        self,
        *,
        sessions_dir: Path,
        teams_dir: Path,
        expertise_dir: Path,
        tracker: Optional[Any] = None,
        attributor: Optional[Any] = None,
        aggregator: Optional[Any] = None,
    ) -> None:
        self._sessions_dir = sessions_dir
        self._teams_dir = teams_dir
        self._expertise_dir = expertise_dir
        self._tracker = tracker
        self._attributor = attributor
        self._aggregator = aggregator

    def register(self, app: web.Application) -> None:
        """Register all Zone 4 routes on an aiohttp application.

        Tolerates a frozen router (i.e. called after app.start()) — aiohttp
        does not allow route registration after the router is frozen, and
        the current BridgeApp startup order calls this after the API server
        has already started. Rather than crash the whole bridge, we log and
        skip registration. Z4 observability endpoints will simply be absent
        until the caller is fixed to wire routes before start().
        """
        try:
            self._register_routes(app)
        except RuntimeError as exc:
            if "frozen router" in str(exc).lower():
                import logging
                logging.getLogger(__name__).warning(
                    "Zone4Routes: router is frozen; skipping /api/z4/* registration. "
                    "Bridge will run without Z4 observability endpoints. "
                    "Fix: call set_zone4_routes() before api_server.start()."
                )
                return
            raise

    def _register_routes(self, app: web.Application) -> None:
        # Sessions
        app.router.add_get("/api/z4/sessions", self._handle_sessions)
        app.router.add_get("/api/z4/sessions/{sid}", self._handle_session_detail)
        app.router.add_get(
            "/api/z4/sessions/{sid}/cost", self._handle_session_cost
        )
        app.router.add_get(
            "/api/z4/sessions/{sid}/departments/{dept}/conversation",
            self._handle_conversation,
        )
        app.router.add_get(
            "/api/z4/sessions/{sid}/departments/{dept}/tools/{agent}",
            self._handle_agent_tools,
        )

        # Departments
        app.router.add_get("/api/z4/departments", self._handle_departments)
        app.router.add_get(
            "/api/z4/departments/{dept}/health", self._handle_department_health
        )

        # Agents
        app.router.add_get("/api/z4/agents", self._handle_agents)
        app.router.add_get(
            "/api/z4/agents/{name}/expertise", self._handle_agent_expertise
        )

        # Board
        app.router.add_get("/api/z4/board/briefs", self._handle_board_briefs)
        app.router.add_get("/api/z4/board/memos", self._handle_board_memos)

        # Metrics
        app.router.add_get(
            "/api/z4/metrics/cost/daily", self._handle_daily_cost
        )
        app.router.add_get(
            "/api/z4/metrics/agents", self._handle_agent_metrics
        )
        app.router.add_get(
            "/api/z4/metrics/violations", self._handle_violations
        )

    # ── Endpoint index (for inclusion in the main API index) ──────────────────

    @staticmethod
    def endpoint_index() -> list[dict]:
        """Return route descriptors for inclusion in the main API index."""
        return [
            {"method": "GET", "path": "/api/z4/sessions",
             "description": "List Zone 4 sessions with pagination"},
            {"method": "GET", "path": "/api/z4/sessions/{id}",
             "description": "Full session detail"},
            {"method": "GET", "path": "/api/z4/sessions/{id}/cost",
             "description": "Session cost breakdown"},
            {"method": "GET",
             "path": "/api/z4/sessions/{id}/departments/{dept}/conversation",
             "description": "Department conversation log"},
            {"method": "GET",
             "path": "/api/z4/sessions/{id}/departments/{dept}/tools/{agent}",
             "description": "Agent tool calls"},
            {"method": "GET", "path": "/api/z4/departments",
             "description": "Configured departments"},
            {"method": "GET", "path": "/api/z4/departments/{dept}/health",
             "description": "Department health"},
            {"method": "GET", "path": "/api/z4/agents",
             "description": "All agents with expertise status"},
            {"method": "GET", "path": "/api/z4/agents/{name}/expertise",
             "description": "Agent expertise content"},
            {"method": "GET", "path": "/api/z4/board/briefs",
             "description": "Board briefs archive"},
            {"method": "GET", "path": "/api/z4/board/memos",
             "description": "Board memos archive"},
            {"method": "GET", "path": "/api/z4/metrics/cost/daily",
             "description": "Daily cost totals"},
            {"method": "GET", "path": "/api/z4/metrics/agents",
             "description": "Agent utilization metrics"},
            {"method": "GET", "path": "/api/z4/metrics/violations",
             "description": "Domain violations"},
        ]

    # ── Sessions ──────────────────────────────────────────────────────────────

    async def _handle_sessions(self, request: web.Request) -> web.Response:
        """List Zone 4 sessions with offset/limit pagination."""
        offset = _int_param(request, "offset", 0)
        limit = _int_param(request, "limit", 20)
        status_filter = request.query.get("status")

        sessions = self._list_sessions(status_filter)
        total = len(sessions)
        page = sessions[offset : offset + limit]

        return _ok({
            "sessions": page,
            "total": total,
            "offset": offset,
            "limit": limit,
        })

    async def _handle_session_detail(
        self, request: web.Request
    ) -> web.Response:
        """Full detail for a single session."""
        sid = request.match_info["sid"]
        meta = self._read_session_meta(sid)
        if meta is None:
            return _error(f"Session {sid} not found", 404)

        # Include cost if available
        cost = None
        if self._attributor:
            try:
                summary = self._attributor.compute_session_cost(sid)
                cost = summary.to_dict()
            except Exception:
                pass

        # Include department list
        departments = self._list_session_departments(sid)

        return _ok({
            "session_id": sid,
            "meta": meta,
            "cost": cost,
            "departments": departments,
        })

    async def _handle_session_cost(
        self, request: web.Request
    ) -> web.Response:
        """Cost breakdown for a session."""
        sid = request.match_info["sid"]
        if not self._attributor:
            return _error("Cost attribution not available", 503)

        meta = self._read_session_meta(sid)
        if meta is None:
            return _error(f"Session {sid} not found", 404)

        try:
            summary = self._attributor.compute_session_cost(sid)
            return _ok(summary.to_dict())
        except Exception as e:
            return _error(str(e), 500)

    async def _handle_conversation(
        self, request: web.Request
    ) -> web.Response:
        """Conversation log for a department in a session."""
        sid = request.match_info["sid"]
        dept = request.match_info["dept"]

        conv_path = (
            self._sessions_dir / sid / dept / "conversation.jsonl"
        )
        if not conv_path.exists():
            return _error(
                f"No conversation log for {dept} in session {sid}", 404
            )

        messages = []
        try:
            for line in conv_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            return _error(str(e), 500)

        return _ok({"session_id": sid, "department": dept, "messages": messages})

    async def _handle_agent_tools(
        self, request: web.Request
    ) -> web.Response:
        """Tool calls for a specific agent in a department session."""
        sid = request.match_info["sid"]
        dept = request.match_info["dept"]
        agent = request.match_info["agent"]

        if not self._tracker:
            return _error("Tool tracker not available", 503)

        try:
            records = self._tracker.get_agent_calls(sid, dept, agent)
            return _ok({
                "session_id": sid,
                "department": dept,
                "agent": agent,
                "calls": [r.to_dict() for r in records],
                "count": len(records),
            })
        except Exception as e:
            return _error(str(e), 500)

    # ── Departments ───────────────────────────────────────────────────────────

    async def _handle_departments(
        self, request: web.Request
    ) -> web.Response:
        """List all configured departments (team YAML files)."""
        departments = []
        if self._teams_dir.exists():
            for yaml_file in sorted(self._teams_dir.glob("*.yaml")):
                departments.append({
                    "name": yaml_file.stem,
                    "config_file": yaml_file.name,
                })
        return _ok({"departments": departments, "count": len(departments)})

    async def _handle_department_health(
        self, request: web.Request
    ) -> web.Response:
        """Health info for a specific department."""
        dept = request.match_info["dept"]
        config_path = self._teams_dir / f"{dept}.yaml"
        if not config_path.exists():
            return _error(f"Department '{dept}' not configured", 404)

        # Count recent sessions for this department
        recent_sessions = 0
        total_calls = 0
        violations = 0
        if self._sessions_dir.exists():
            for session_dir in self._sessions_dir.iterdir():
                if not session_dir.is_dir():
                    continue
                dept_dir = session_dir / dept
                if dept_dir.exists():
                    recent_sessions += 1
                    if self._tracker:
                        calls = self._tracker.get_department_calls(
                            session_dir.name, dept
                        )
                        total_calls += len(calls)
                        violations += sum(
                            1 for c in calls if c.is_domain_violation
                        )

        return _ok({
            "department": dept,
            "configured": True,
            "recent_sessions": recent_sessions,
            "total_calls": total_calls,
            "domain_violations": violations,
        })

    # ── Agents ────────────────────────────────────────────────────────────────

    async def _handle_agents(self, request: web.Request) -> web.Response:
        """List all known agents with expertise status."""
        agents: list[dict] = []

        # Scan expertise directory for known agents
        if self._expertise_dir.exists():
            for md_file in sorted(self._expertise_dir.glob("*.md")):
                if md_file.name == "README.md":
                    continue
                agent_name = md_file.stem
                agents.append({
                    "name": agent_name,
                    "has_expertise": True,
                    "expertise_size": md_file.stat().st_size,
                })

        # Also check read-only expertise
        ro_dir = self._expertise_dir / "read-only"
        ro_files = []
        if ro_dir.exists():
            ro_files = [f.name for f in sorted(ro_dir.glob("*.md"))]

        return _ok({
            "agents": agents,
            "count": len(agents),
            "read_only_expertise": ro_files,
        })

    async def _handle_agent_expertise(
        self, request: web.Request
    ) -> web.Response:
        """Return the expertise file content for an agent."""
        name = request.match_info["name"]
        expertise_path = self._expertise_dir / f"{name}.md"

        if not expertise_path.exists():
            return _error(f"No expertise file for agent '{name}'", 404)

        try:
            content = expertise_path.read_text(encoding="utf-8")
            return _ok({
                "agent": name,
                "content": content,
                "size": len(content),
            })
        except Exception as e:
            return _error(str(e), 500)

    # ── Board ─────────────────────────────────────────────────────────────────

    async def _handle_board_briefs(
        self, request: web.Request
    ) -> web.Response:
        """List board briefs from session archives."""
        limit = _int_param(request, "limit", 20)
        briefs = self._collect_board_files("brief")
        return _ok({"briefs": briefs[:limit], "total": len(briefs)})

    async def _handle_board_memos(
        self, request: web.Request
    ) -> web.Response:
        """List board memos from session archives."""
        limit = _int_param(request, "limit", 20)
        memos = self._collect_board_files("memo")
        return _ok({"memos": memos[:limit], "total": len(memos)})

    # ── Metrics ───────────────────────────────────────────────────────────────

    async def _handle_daily_cost(
        self, request: web.Request
    ) -> web.Response:
        """Daily cost totals."""
        if not self._aggregator:
            return _error("Metrics aggregator not available", 503)

        start = request.query.get("start")
        end = request.query.get("end")
        try:
            entries = self._aggregator.daily_cost(
                start_date=start, end_date=end
            )
            return _ok({
                "entries": [e.to_dict() for e in entries],
                "count": len(entries),
            })
        except Exception as e:
            return _error(str(e), 500)

    async def _handle_agent_metrics(
        self, request: web.Request
    ) -> web.Response:
        """Agent utilization metrics."""
        if not self._aggregator:
            return _error("Metrics aggregator not available", 503)

        try:
            utils = self._aggregator.agent_utilization()
            return _ok({
                "agents": [u.to_dict() for u in utils],
                "count": len(utils),
            })
        except Exception as e:
            return _error(str(e), 500)

    async def _handle_violations(
        self, request: web.Request
    ) -> web.Response:
        """Domain violations across sessions."""
        if not self._tracker:
            return _error("Tool tracker not available", 503)

        session_id = request.query.get("session_id")
        department = request.query.get("department")
        agent = request.query.get("agent")

        try:
            if session_id:
                violations = self._tracker.get_domain_violations(
                    session_id, department=department, agent_name=agent
                )
            else:
                # Scan all sessions
                violations = []
                if self._sessions_dir.exists():
                    for session_dir in sorted(self._sessions_dir.iterdir()):
                        if not session_dir.is_dir():
                            continue
                        sv = self._tracker.get_domain_violations(
                            session_dir.name,
                            department=department,
                            agent_name=agent,
                        )
                        violations.extend(sv)

            return _ok({
                "violations": [v.to_dict() for v in violations],
                "count": len(violations),
            })
        except Exception as e:
            return _error(str(e), 500)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _list_sessions(self, status_filter: Optional[str] = None) -> list[dict]:
        """List all sessions with basic info from meta.json."""
        if not self._sessions_dir.exists():
            return []

        sessions = []
        for session_dir in sorted(
            self._sessions_dir.iterdir(), reverse=True
        ):
            if not session_dir.is_dir():
                continue
            meta = self._read_session_meta(session_dir.name)
            if meta is None:
                meta = {"session_id": session_dir.name}
            else:
                meta["session_id"] = session_dir.name

            if status_filter and meta.get("status") != status_filter:
                continue

            sessions.append(meta)

        return sessions

    def _read_session_meta(self, session_id: str) -> Optional[dict]:
        """Read meta.json for a session."""
        meta_path = self._sessions_dir / session_id / "meta.json"
        if not meta_path.exists():
            return None
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _list_session_departments(self, session_id: str) -> list[str]:
        """List department directories within a session."""
        session_dir = self._sessions_dir / session_id
        if not session_dir.exists():
            return []
        return sorted(
            d.name
            for d in session_dir.iterdir()
            if d.is_dir() and d.name not in ("expertise_snapshots",)
        )

    def _collect_board_files(self, kind: str) -> list[dict]:
        """
        Collect board brief or memo files from session archives.

        Looks for files named board-brief.md or board-memo.md in
        sessions/{id}/board/ directories.
        """
        results = []
        if not self._sessions_dir.exists():
            return results

        for session_dir in sorted(
            self._sessions_dir.iterdir(), reverse=True
        ):
            board_dir = session_dir / "board"
            if not board_dir.exists():
                continue
            target = board_dir / f"board-{kind}.md"
            if target.exists():
                try:
                    content = target.read_text(encoding="utf-8")
                    results.append({
                        "session_id": session_dir.name,
                        "content": content,
                        "size": len(content),
                    })
                except Exception:
                    continue

        return results
