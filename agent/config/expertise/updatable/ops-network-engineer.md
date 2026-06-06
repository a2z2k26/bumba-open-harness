---
agent: ops-network-engineer
zone: 4
department: ops
type: updatable
max_lines: 500
schema_version: 1
---

# ops-network-engineer — Expertise

*This file is updated by ops-network-engineer after each significant session.*

## Domain Patterns

**Bumba's network surface is small and Mac-mini-local.** This is the load-bearing constraint. The bridge listens on:
- `127.0.0.1:8200` — Mission Control REST API (`bridge.api_server`); Bearer-auth for `/api/*`, no auth for `/healthz`.
- `127.0.0.1:8765` — health server (`bridge.health`); used by external uptime monitors.
- Outbound to: Discord WSS (gateway), Anthropic API (HTTPS), OpenRouter (HTTPS), Notion (HTTPS), GitHub (HTTPS), Cal.com (HTTPS), VAPI (HTTPS + webhook callback), various MCP servers (mostly local subprocesses).

There is no LAN exposure by default. The two-knob LAN-exposure opt-in (`[api] host = "0.0.0.0"` AND `allow_remote_bind = true`) is the operator-signed escape hatch from P2.1 #1626 — a fail-closed validator in `APIServer.start` aborts boot if either knob is misconfigured. Network reviews that propose LAN exposure must cite this validator AND propose appropriate firewall rules.

**No CDN, no load balancer, no DNS infrastructure today.** The bridge is single-instance. Network-engineer work for this operator is almost always one of:
- **Outbound dependency review** — when Anthropic, Discord, or another upstream changes its network requirements (new IPs, new TLS minimums, new rate limits).
- **Webhook receiver design** — three webhook routes exist today (GitHub, VAPI, Cal.com), each with its own auth shape. New webhooks need similar care.
- **Future Mission Control web surface** — DNS + TLS + CDN design when the operator decides to ship the dashboard externally.
- **Tunneling / VPN / remote access** — operator uses Remote Desktop into the Mac mini admin account (per session memory). Recommendations involving Tailscale, Cloudflare Tunnel, ngrok belong here.

**Outbound TLS is non-negotiable.** Every external call uses HTTPS or WSS. The runtime's HTTP client is `aiohttp`; default cert verification is on. Recommendations that disable cert verification ("just for this one call") are a CRITICAL finding — surface and refuse.

**Webhook receiver patterns (pre-existing):**
- **GitHub** — HMAC-SHA256 via `X-Hub-Signature-256`. Implementation: `bridge/webhook_receiver.py`. Secret in `.secrets` as `github_webhook_secret`.
- **VAPI** — shared secret via `X-VAPI-SECRET` header + `secrets.compare_digest`. Implementation: `bridge/api/routes_webhooks.py` (R1.2 #1889). Fail-closed boot validator in `APIServer.start` requires the secret when `voice_enabled=true`.
- **Cal.com** — HMAC-SHA256. Implementation: `bridge/calcom_webhook.py`. Secret per Cal.com account (operator memory: dual personal + External Product accounts).

A new webhook proposal MUST mirror one of these three patterns: HMAC over the body, or shared-secret in a custom header with constant-time compare. Bearer-token on a webhook surface is wrong shape — VAPI and GitHub callbacks don't carry one.

**TLS posture for inbound (when a real surface exists):**
- TLS 1.2 minimum, prefer 1.3.
- Certificate management: Let's Encrypt via certbot for any future public-facing surface; cert renewal cron is a separate ops concern (overlap with ops-devops-specialist).
- HSTS: 6+ months on a stable production surface; shorter (or omitted) on staging.
- CSP, X-Frame-Options, etc.: not applicable until there's a real web UI.

**DNS contract (when relevant):**
- TTLs affect failover time. Default 300s for stable records; 60s for records that need quick failover; 86400s for records that never change (e.g. MX).
- Split-horizon (different DNS for internal vs external) is overkill for this operator's scale. Don't propose it.
- DNS-based failover (multiple A records) is a reasonable load-balancing escape hatch for low-traffic surfaces; document the TTL trade-off.

**CDN posture (when a public web surface ships):**
- Cloudflare free tier is the obvious starting point. Document the limits (no SSL ciphers control, no log retention beyond 24h on free tier).
- Cache invalidation strategy: prefer short TTLs over manual purge for content that updates. Cache-Control headers from origin > Cloudflare's edge defaults.
- Origin protection: Cloudflare-only inbound IPs via firewall rules, not just trust-the-edge.

**Severity ladder:**
- **CRITICAL** — disabled TLS verification, hardcoded credentials in firewall config, LAN-exposure misconfiguration that bypasses the two-knob opt-in, webhook route without HMAC/secret verification.
- **HIGH** — missing rate limiting on a public-facing webhook surface, DNS TTL set to 60s for a record that doesn't need failover (cost on busy resolvers), CDN cache headers that leak PII via shared cache.
- **MEDIUM** — missing HSTS on a public surface, suboptimal DNS provider choice (vendor lock-in without justification), firewall rule without a documented justification.
- **LOW** — TLS cipher list could be tightened beyond default, missing CAA record on the apex domain.

**Finding format:**
```
**[SEVERITY]** <one-line title>
Surface: <listening address, outbound destination, DNS record, etc.>
Current: <what exists today>
Proposed: <what the change looks like>
Risk if not fixed: <impact on availability, security, or cost>
Cite: <fail-closed validator, webhook auth pattern, TLS minimum, etc.>
```

## Tool Use

**`read_file`** — for `agent/config/bridge.toml` `[api]` block (the LAN-exposure validator), `agent/bridge/api_server.py` (the validator itself), `agent/bridge/api/routes_webhooks.py` (VAPI auth pattern), `agent/bridge/webhook_receiver.py` (GitHub HMAC pattern), `agent/bridge/calcom_webhook.py` (Cal.com HMAC pattern).

**`search_knowledge`** — for prior network decisions: which TLS minimums were enforced, which webhook routes were rejected for missing auth, which Cloudflare features were considered free-tier-incompatible.

**Do NOT modify production network config or routes.** This specialist proposes; ops-chief decides; ops-devops-specialist or api-engineer implements.

## Operating Constraints

**Model:** `gpt-4o-mini` (ops team standard).

**Cost ceiling:** inherits the ops team's `cost_limit_usd: 1.50` per session.

**Write surface:** documentation only. NEVER `agent/config/bridge.toml`, NEVER firewall config, NEVER DNS records.

**Cite fail-closed validators when relevant.** The LAN-exposure validator (P2.1 #1626) and the VAPI fail-closed validator (P2.3 #1578) are operator-signed safety rails. Any proposal that would bypass them is a CRITICAL finding.

**Free-tier-first.** Same as ops-cloud-architect: free tier is the default; paid alternatives need justification.

**TLS verification is non-negotiable.** Any code path that disables cert verification gets a CRITICAL finding regardless of context.

**Document the rate-limiter contract.** The bridge's API has a 120-req/min token-bucket rate limiter (`bridge.rate_limiter`). New endpoints inherit it; recommendations to disable or relax it for a specific route need explicit operator sign-off.

**Escalate to ops-chief when:** LAN exposure is being proposed (two-knob validator triggers operator decision anyway), a webhook surface is being added without HMAC/secret pattern, TLS verification is being disabled anywhere, or DNS / CDN architecture is being changed for a production surface.

## See Also

- Team config: `agent/config/teams/ops.yaml`
- System prompt: `agent/config/agents/zone4/ops/ops-network-engineer.md`
- LAN-exposure validator: `agent/bridge/api_server.py::APIServer.start` (P2.1 #1626) + `agent/CLAUDE.md` § "API bind — two-knob opt-in"
- VAPI webhook auth: `agent/bridge/api/routes_webhooks.py` + `agent/tests/test_vapi_webhook_auth.py` (R1.2)
- GitHub webhook HMAC: `agent/bridge/webhook_receiver.py`
- Cal.com webhook: `agent/bridge/calcom_webhook.py` + operator memory `project_calcom_multi_account`
- Sibling: `ops-cloud-architect.md` (DNS / CDN cost decisions)
- Sibling: `ops-monitoring-specialist.md` (network observability)
- Operator network constraint: Mac mini behind home network; Remote Desktop for admin access
