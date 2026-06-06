---
agent: api-tester
zone: 4
department: qa
type: updatable
max_lines: 500
schema_version: 1
---

# api-tester — Expertise

*This file is updated by api-tester after each significant session.*

## Domain Patterns

**The bridge's API surface is `agent/bridge/api/routes_*.py`.** 71 endpoints maximum (48 always-registered + 3 ChiefSession-conditional + 14 Z4-observability-conditional + 6 peer-coordination-conditional). All `/api/*` routes require Bearer-token auth (the `api_token` secret); `/healthz` is the only un-authed route. New routes register via the per-domain modules, never directly in `api_server.py` — that file is the orchestrator after the P6.2 demote-split (PR #1593).

**Two webhook routes have their own auth contracts that are NOT Bearer-token:**
- `/api/webhooks/github` — HMAC-SHA256 via `X-Hub-Signature-256` (`bridge/webhook_receiver.py`)
- `/api/v1/voice/webhook` — shared secret via `X-VAPI-SECRET` + `secrets.compare_digest` (`bridge/api/routes_webhooks.py`, P2.3 #1578)
- `/api/webhooks/calcom` — HMAC-SHA256 (`bridge/calcom_webhook.py`)

A test that bypasses these by using Bearer-token auth on a webhook route is the wrong shape — the live request never has Bearer, so the test proves nothing about production. Mirror the pattern in `agent/tests/test_vapi_webhook_auth.py` (R1.2 #1889): exercise missing header, wrong header, correct header, empty expected secret, and the `compare_digest` boundary.

**Fail-closed boot validation is operator-signed.** `APIServer.start()` aborts boot when `voice_enabled = true` but `vapi_webhook_secret` is empty (P2.3). Same shape applies to `[api] host = "0.0.0.0"` without `allow_remote_bind = true` (P2.1 #1624 + #1626). API tests that mock past these boot validators are testing the wrong layer — surface as MEDIUM.

**Status code conventions:**
- 200 — success with body
- 401 — missing or invalid auth (Bearer OR webhook secret OR HMAC)
- 403 — authenticated but unauthorized (rare; most surfaces are operator-only so this collapses to 401)
- 404 — unknown route OR conditional route disabled (e.g. `chief_dispatcher_enabled = false` returns 404 for `/api/chief_sessions`)
- 422 — schema validation failure (Pydantic body)
- 503 — health-check soft-fail (component degraded but route alive)

A test that asserts 200 but the route emits 503 in production (degraded mode) is silently passing — always test the failure modes alongside the happy path.

**Rate limiter is token-bucket: 120 req/min per IP** (`bridge.rate_limiter`). New endpoints inherit this; tests that hammer an endpoint without honoring the limiter will see 429s after ~120 hits. Use the test fixture that bypasses the limiter rather than fighting it.

**Conditional routes are gated by feature flags** — verify by reading `bridge.app::_register_routes` for the gating logic. A test that asserts a Z4 observability endpoint exists when `z4_observability_tool_tracker_enabled = false` is wrong; the route legitimately 404s. Mirror `tests/test_peer_routes_mounted.py` for the conditional-mount pattern.

**WebSocket endpoints** — `/ws/events`, `/ws/events?filter=<prefix>`, `/ws/workorders/{wo_id}`. All require Bearer auth on the initial handshake. Filter syntax uses dot-prefix matching (e.g. `?filter=chief_session.` matches `chief_session.created`, `chief_session.state_changed`, etc.). Test fixture pattern in `tests/test_chief_session_ws_events.py`.

**Finding format:**
```
**[SEVERITY]** <one-line title>
Endpoint: <METHOD> /api/path  (or webhook path)
Repro: curl ... (with auth header noted)
Fix: <smallest-surface change; cite the canonical pattern>
Cite: <Bearer-auth rule, fail-closed validator, conditional gate, etc.>
```

## Tool Use

**`run_tests`** — primary verification. Always invoke before claiming an endpoint contract holds. Targeted invocation: `pytest tests/test_api_server.py tests/test_vapi_webhook_auth.py tests/test_peer_api*.py -q` (the API-test cluster).

**`read_file`** — for `agent/bridge/api/routes_*.py`, `agent/bridge/api_server.py`, `agent/bridge/webhook_receiver.py`, `agent/bridge/calcom_webhook.py`, `agent/tests/test_api_*.py`, `agent/tests/test_vapi_webhook_auth.py`, `agent/tests/test_chief_session_ws_events.py`.

**`search_knowledge`** — for prior route decisions: why a route was deleted (PR #1613 dropped `/api/merge-queue*`), why a webhook secret was added (audit C8), why a conditional gate was introduced.

**Do NOT run `security_scan`** — that's `security-auditor`. Webhook auth findings that look like injection or secret-exposure should hand off to security-auditor as CRITICAL; this specialist owns the contract correctness layer.

## Operating Constraints

**Model:** `gpt-4o-mini` (qa team standard). API contract validation is structured pattern-matching against the route definition — model size is fine.

**Cost ceiling:** inherits the qa team's `cost_limit_usd: 1.50` per session.

**Write surface:** `tests/api/`, `tests/`, and `qa/api/` only. Do NOT modify production routes — those belong to `api-engineer` / `backend-architect`.

**Test fixtures must use `aiohttp.test_utils`** — never make real HTTP calls in unit tests. Bridge integration tests use the `_make_mock_bridge_with_real_event_bus` pattern from `tests/test_chief_session_ws_events.py`.

**Auth coverage is mandatory.** A test for a new endpoint that does not exercise (a) missing Bearer, (b) wrong Bearer, (c) correct Bearer is incomplete. Surface as MEDIUM if a PR ships an endpoint without all three.

**Rate-limiter and pagination behavior** are part of the contract — don't skip testing them just because they're harder to exercise. The 120-req/min limit and the per-route pagination defaults are operator-visible behavior that downstream automation depends on.

**Escalate to qa-chief when:** a webhook auth surface is being added without a fail-closed boot validator, a conditional route is being added without a feature-flag gate, or a route bypasses the Bearer-auth pattern without explicit operator sign-off (only `/healthz` is exempt today).

## See Also

- Team config: `agent/config/teams/qa.yaml`
- System prompt: `agent/config/agents/zone4/qa/api-tester.md`
- Per-domain route modules: `agent/bridge/api/routes_*.py`
- VAPI auth pattern: `agent/bridge/api/routes_webhooks.py` + `agent/tests/test_vapi_webhook_auth.py`
- WebSocket pattern: `agent/tests/test_chief_session_ws_events.py`
- Conditional-mount pattern: `agent/tests/test_peer_routes_mounted.py`
- Bridge module reference: `agent/CLAUDE.md` § "Mission Control REST API"
- Operator testing rules: `~/.claude/rules/common/testing.md`
