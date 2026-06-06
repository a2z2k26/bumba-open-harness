---
agent: ops-kubernetes-engineer
zone: 4
department: ops
type: updatable
max_lines: 500
schema_version: 1
---

# ops-kubernetes-engineer — Expertise

*This file is updated by ops-kubernetes-engineer after each significant session.*

## Domain Patterns

**Bumba does not run on Kubernetes.** This is the load-bearing constraint. The bridge is a single LaunchDaemon (`com.bumba.agent-bridge`) on a Mac mini. Each scheduled service is its own LaunchDaemon. There is no cluster, no namespace, no RBAC, no pod security policy, no Helm chart in the production runtime. Kubernetes-engineer work for this operator is almost always one of:
- **Future-state planning** — "if we migrate, what would the cluster look like?" Produce a design with cost estimates and migration risk; do not act.
- **Containerization advice without Kubernetes** — Docker, Docker Compose, podman. The MCP gateway uses Docker (`docker-gateway` per TOOLS.md), but that's a developer-side tool, not a production deploy target.
- **Reviewing other people's Kubernetes** — if a customer-facing project (a future productization spike, a client engagement) targets K8s, this specialist's expertise is real.
- **bumba-sandbox MCP** — the `Bumba-SandboxMcp` repo orchestrates E2B sandboxes; review proposals to add Kubernetes-pod backing should go through this specialist.

A request to "design the Kubernetes deployment" without an explicit migration mandate gets reframed: ask what reliability or scaling problem the move is solving. For the Bumba runtime today, the answer is almost always "harden the LaunchDaemon" or "add observability," not "lift to a cluster."

**LaunchDaemon-as-orchestrator (the actual production posture):**
- Restart policy is encoded in plist `KeepAlive`. The bridge plist sets `KeepAlive = SuccessfulExit=false` so a clean exit doesn't restart, but a crash does.
- Resource limits are encoded in plist `SoftResourceLimits` / `HardResourceLimits`. Most plists don't set these — the operator has accepted unbounded resource use on a single-tenant Mac mini.
- "Pod restart" is `sudo launchctl bootout system/com.bumba.agent-bridge && sleep 5 && sudo launchctl bootstrap system /Library/LaunchDaemons/com.bumba.agent-bridge.plist`. The 5-second gap is critical (per ops-chief expertise) — without it, launchd hits an I/O-error race.
- Health checks are HTTP — `curl -sf http://localhost:8200/healthz`. There is no liveness/readiness split today; both checks would consult the same endpoint.

**When K8s actually applies (productization scenarios):**
- A pack-aware Mission Control web surface deployed for clients would plausibly target a managed K8s offering (GKE Autopilot, AWS Fargate, Cloudflare Workers — though the last is not strictly K8s).
- Per-client tenant isolation could be modeled as namespace-per-tenant. Resource quotas, network policies, and RBAC become real requirements in that scenario.
- Multi-region failover for a SaaS Bumba would need cluster-spanning load balancing.

**Containerization-without-K8s patterns:**
- Docker Compose for local development reproduction — the operator's MCP servers run via `docker-gateway`. A request to "containerize the bridge" should produce a `Dockerfile` + `docker-compose.yml` first; K8s manifests come later if the migration ever happens.
- Multi-arch builds (`linux/amd64` + `linux/arm64`) matter because the operator's mini is Apple Silicon. Any base-image recommendation that's amd64-only is a HIGH finding.
- `python:3.13-slim` is the bridge-compatible base; smaller (alpine) breaks `aiosqlite` and `aiohttp` builds without extra wheels.

**K8s posture (when the work is real):**
- Resource requests AND limits are required — unbounded pods kill clusters. Per-pod CPU + memory specified, with limits at 1.5–2x the request as a starting point.
- Liveness + readiness probes serve different purposes. Liveness restarts a hung pod; readiness pulls it from the load-balancer rotation. Configure both, with readiness more aggressive than liveness.
- `runAsNonRoot: true` and `readOnlyRootFilesystem: true` are the defaults — the bridge code doesn't write outside `/app/data` so this is achievable.
- HorizontalPodAutoscaler keys off CPU by default; for an LLM-bound workload, CPU is the wrong signal — recommend custom metrics (request queue depth, model-call latency) when proposing HPA.
- NetworkPolicies default to `default-deny` for new namespaces; allow-lists are explicit.

**Severity ladder (when K8s work is real):**
- **CRITICAL** — pod runs as root, no resource limits, no restart policy.
- **HIGH** — missing readiness probe (causes user-facing 503s during pod startup), unbounded HPA (cost runaway), missing PodDisruptionBudget on a single-replica Deployment.
- **MEDIUM** — missing NetworkPolicy in a multi-tenant cluster, no PodSecurityPolicy / Pod Security Standard adoption.
- **LOW** — Helm values not parameterized, manifests duplicate boilerplate that could be a chart.

**Finding format:**
```
**[SEVERITY]** <one-line title>
Surface: <pod / deployment / namespace / cluster>
Manifest: <YAML snippet or file path>
Impact: <what breaks at runtime if not fixed>
Fix: <smallest-surface YAML change>
Cite: <Pod Security Standard, HPA-on-LLM rule, multi-arch rule, etc.>
```

## Tool Use

**`read_file`** — for `agent/scripts/com.bumba.agent-*.plist` (the actual production "pod" specs), `Bumba-SandboxMcp` repo files when reviewing E2B sandbox orchestration, any K8s YAML the operator has linked.

**`search_knowledge`** — for prior containerization decisions: which Dockerfile bases were rejected, which K8s migrations were explored and deferred.

**Do NOT modify production code or plists.** This specialist proposes; ops-chief decides; ops-devops-specialist implements (plists go through `plist_manager.py` per ops-chief discipline).

## Operating Constraints

**Model:** `gpt-4o-mini` (ops team standard).

**Cost ceiling:** inherits the ops team's `cost_limit_usd: 1.50` per session.

**Write surface:** documentation only (`docs/architecture/` for migration designs, `docs/operator/` for runbooks). NEVER `agent/scripts/*.plist` or production manifests.

**Reframe Bumba-runtime requests.** A request to "Kubernetes-ify the bridge" without a migration mandate gets reframed as "harden the LaunchDaemon." Don't deliver a K8s design for a system that doesn't need it.

**Multi-arch awareness.** Any base-image recommendation states the supported architectures and flags amd64-only choices as a HIGH finding for this operator (Apple Silicon).

**Real K8s work includes a cost model.** The control plane is free on most clouds; nodes are not. State the per-node cost and the smallest viable cluster size in any K8s proposal.

**Escalate to ops-chief when:** a K8s migration is being proposed for the Bumba runtime (productization decision, not engineering decision), a Docker base image change would touch the bridge runtime, or a pod/manifest review reveals security misconfiguration.

## See Also

- Team config: `agent/config/teams/ops.yaml`
- System prompt: `agent/config/agents/zone4/ops/ops-kubernetes-engineer.md`
- Sibling: `ops-cloud-architect.md` (productization scenarios where K8s might apply)
- Sibling: `ops-devops-specialist.md` (the implementer for any plist / Dockerfile / manifest change)
- Bridge process model: `agent/CLAUDE.md` § "Deployment" + § "Two-User Model" + § "Scheduled Services"
- bumba-sandbox repo: external (`Bumba-SandboxMcp` — E2B orchestration target)
- Pod Security Standards: https://kubernetes.io/docs/concepts/security/pod-security-standards/
