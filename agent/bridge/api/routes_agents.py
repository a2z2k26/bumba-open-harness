"""Agents + sessions routes (Sprint P6.2 split).

Pure reorg from ``bridge.api_server``. Agents and sessions are
co-located because both deal with the lifecycle of long-running
processes the bridge spawns (tmux agents and Claude sessions); the
audit-plan brief calls for an agents module, and sessions are a
natural cohabitant.
"""
from __future__ import annotations

import json

from aiohttp import web

from ._helpers import _error, _ok


class _AgentsRoutesMixin:
    """Provides /api/agents/* and /api/sessions/* handlers."""

    def _register_agents_routes(self, app: web.Application) -> None:
        # Agents
        app.router.add_get("/api/agents", self._handle_list_agents)
        app.router.add_get("/api/agents/{agent_id}", self._handle_get_agent)
        app.router.add_post("/api/agents/spawn", self._handle_spawn_agent)
        app.router.add_post(
            "/api/agents/{agent_id}/kill", self._handle_kill_agent
        )

        # Sessions
        app.router.add_get("/api/sessions", self._handle_list_sessions)
        app.router.add_post("/api/sessions/reset", self._handle_reset_session)

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    async def _handle_list_agents(self, request: web.Request) -> web.Response:
        """List all tmux agents."""
        tmux = self._bridge._tmux_agents
        if tmux is None:
            return _ok({"agents": [], "count": 0})
        try:
            agents = await tmux.list_agents()
            return _ok({
                "agents": [
                    {
                        "id": a.agent_id,
                        "name": a.name,
                        "status": a.status,
                        "created_at": a.created_at,
                        "task": a.task,
                    }
                    for a in agents
                ],
                "count": len(agents),
            })
        except Exception as e:
            return _error(str(e), 500)

    async def _handle_get_agent(self, request: web.Request) -> web.Response:
        """Get a specific agent by ID."""
        agent_id = request.match_info["agent_id"]
        tmux = self._bridge._tmux_agents
        if tmux is None:
            return _error("Agent system not available", 503)
        try:
            agent = await tmux.get_agent(agent_id)
            if agent is None:
                return _error(f"Agent {agent_id} not found", 404)
            return _ok({
                "id": agent.agent_id,
                "name": agent.name,
                "status": agent.status,
                "created_at": agent.created_at,
                "task": agent.task,
            })
        except Exception as e:
            return _error(str(e), 500)

    async def _handle_spawn_agent(self, request: web.Request) -> web.Response:
        """Spawn a new agent."""
        tmux = self._bridge._tmux_agents
        if tmux is None:
            return _error("Agent system not available", 503)
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return _error("Invalid JSON body")
        name = body.get("name", "")
        task = body.get("task", "")
        if not task:
            return _error("'task' field is required")
        try:
            agent = await tmux.spawn_agent(name=name, task=task)
            return _ok({
                "id": agent.agent_id,
                "name": agent.name,
                "status": agent.status,
            }, status=201)
        except Exception as e:
            return _error(str(e), 500)

    async def _handle_kill_agent(self, request: web.Request) -> web.Response:
        """Kill a running agent."""
        agent_id = request.match_info["agent_id"]
        tmux = self._bridge._tmux_agents
        if tmux is None:
            return _error("Agent system not available", 503)
        try:
            killed = await tmux.kill_agent(agent_id)
            if not killed:
                return _error(f"Agent {agent_id} not found", 404)
            return _ok({"killed": agent_id})
        except Exception as e:
            return _error(str(e), 500)

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    async def _handle_list_sessions(
        self, request: web.Request
    ) -> web.Response:
        """List active sessions."""
        session_mgr = self._bridge._session_mgr
        if session_mgr is None:
            return _ok({"sessions": []})
        try:
            sessions = await session_mgr.list_active()
            return _ok({
                "sessions": [
                    {
                        "chat_id": s.get("chat_id", ""),
                        "session_id": s.get("session_id", ""),
                        "created_at": s.get("created_at", ""),
                        "last_activity": s.get("last_activity", ""),
                        "message_count": s.get("message_count", 0),
                    }
                    for s in sessions
                ],
                "count": len(sessions),
            })
        except Exception as e:
            return _error(str(e), 500)

    async def _handle_reset_session(
        self, request: web.Request
    ) -> web.Response:
        """Reset a session for a given chat_id."""
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return _error("Invalid JSON body")
        chat_id = body.get("chat_id", "")
        if not chat_id:
            return _error("'chat_id' field is required")
        session_mgr = self._bridge._session_mgr
        if session_mgr is None:
            return _error("Session manager not available", 503)
        try:
            await session_mgr.expire_session(chat_id, reason="api_reset")
            return _ok({"reset": True, "chat_id": chat_id})
        except Exception as e:
            return _error(str(e), 500)
