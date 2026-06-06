# Toolbox

Broad integrations available through MCP servers, CLI tools, skills, and commands. Use the right tool for the job.

## MCP Servers (23)

Auto-discovered via `.mcp.json`. Prefix tool calls with the server name.

| Server | Capability |
|--------|-----------|
| `github` | Issues, PRs, repos, code search |
| `bumba-sandbox` | E2B cloud sandboxes — isolated code execution (23 tools) |
| `bumba-memory` | Shared memory DB for multi-agent coordination (22 tools) |
| `notion` | Notion pages, databases, search |
| `filesystem` | Read/write files on the local machine |
| `memory` | MCP-native key-value memory |
| `sequential-thinking` | Structured reasoning chains |
| `brave-search` | Web search |
| `exa` | Semantic web search |
| `context7` | Library documentation lookup |
| `pinecone` | Vector similarity search |
| `chroma` | Local vector store |
| `mongodb` | MongoDB Atlas operations |
| `cloudflare` | Workers, KV, R2, D1 |
| `supabase` | Postgres, auth, storage |
| `digitalocean` | Droplets, databases, apps |
| `stripe` | Payments, subscriptions, invoices |
| `firebase` | Firestore, auth, hosting |
| `playwright` | Headless browser automation |
| `fetch` | HTTP requests |
| `mermaid` | Diagram generation |
| `gitmcp` | Git documentation |
| `ref-tools` | Reference/citation tools |

## Design Bridge CLI

Headless design-to-code transformation. Operates on `.design/` directories.

**Invoke:** `node tools/design-bridge/server/cli.js <command>`

Commands: `transform --all --framework <name>`, `status`, `register-all`, `analyze`, `promote`, `generate`

Supported frameworks: react, vue, angular, svelte, flutter, swiftui, jetpack-compose, react-native, web-components, next.

## Persona Archive

169 domain-expert reference files at `docs/persona-archive/`. Knowledge library for specialized reasoning (e.g., `security-engineer.md` before audits, `flutter-expert.md` before mobile work).

## Commands

All commands in `config/claude-files/commands/`. Run via `/command-name`.

| Group | Purpose |
|-------|---------|
| `/gh/*` | GitHub workflow (create-pr, review-pr, merge-pr, create-issues, address-feedback) |
| `/git/*` | Branch management (feature-branch, hotfix-branch, sync-branch) |
| `/orc/*` | Orchestrated planning (brainstorm, plan-feature, plan-sprints, parallel, quick) |
| `/project/*` | Project registry (init, register, config, status) |
| `/sandbox/*` | E2B sandbox lifecycle (init, exec, orchestrate) |
| `/notion/*` | GitHub-Notion sync (sync, project, status) |
| `/design-*` | Design token transformation (10 frameworks, 7 layout targets) |
| `/deploy` | Self-deploy via deploy helper daemon (Tier A/B/C) |
| `/validate` | Test execution with optional fix loop |

## Skills

Skills in `config/claude-files/skills/`. Read the relevant skill before specialized work.

| Category | Skills |
|----------|--------|
| Design transforms | transform-{react, vue, angular, svelte, flutter, swiftui, jetpack-compose, react-native} |
| Notion workflows | notion-github-bridge, notion-knowledge-capture, notion-meeting-intelligence |
| Engineering | architecture-patterns, async-python-patterns, error-handling-patterns, fastapi-templates |
| AI/Agent | swarm-orchestration, configured-agent, memory-agent-protocol, prompt-engineering-patterns |
| DevOps/Quality | code-review-excellence, git-advanced-workflows, github-actions-templates |
| Validation | validate-fix-loop, sandbox-validation, track-switching |
| Operations | tmux-agents (parallel agent spawning, monitoring, lifecycle) |

## Tmux Agent Spawning

You can spawn independent Claude Code agents in tmux sessions for parallel work. Each agent runs in its own session with full tool access.

**When to spawn agents:**
- Complex tasks that benefit from parallel workstreams
- Background research while you handle the operator's immediate request
- Independent analysis tasks (code audit, test coverage, documentation review)
- Any task where you'd otherwise say "this will take a while"

**When NOT to spawn agents:**
- Simple questions or quick lookups
- Tasks requiring real-time operator interaction
- Tasks that depend on the current conversation context

**How to use:**

| Command | Purpose |
|---------|---------|
| `bash scripts/tmux-agent.sh spawn "task"` | Spawn an agent, returns agent_id |
| `bash scripts/tmux-agent.sh spawn "task" --max-turns 50` | Spawn with custom turn limit |
| `bash scripts/tmux-agent.sh list` | List all active agents |
| `bash scripts/tmux-agent.sh status <id>` | Check agent status + recent output |
| `bash scripts/tmux-agent.sh output <id>` | Get agent's final result |
| `bash scripts/tmux-agent.sh kill <id>` | Kill a running agent |

**Limits:** Max 3 concurrent agents. Max 4-hour lifetime per agent. Agents inherit your OAuth token.

**Result delivery:** When an agent completes, the bridge automatically delivers its result to Discord. You can also poll with `status` or `output`.

**Example — parallel code audit:**
1. `bash scripts/tmux-agent.sh spawn "Audit bridge/*.py for security vulnerabilities. Report findings as a markdown table."`
2. `bash scripts/tmux-agent.sh spawn "Review tests/ for coverage gaps. List untested functions."`
3. Continue handling the operator's current request
4. Check results: `bash scripts/tmux-agent.sh output <id1>` and `bash scripts/tmux-agent.sh output <id2>`
5. Synthesize findings and report to operator

## Autonomy Modules

Phase 5 systems for self-governing operation:

| Module | Purpose |
|--------|---------|
| `trust_score.py` | Per-capability trust scoring (0-100), 7 domains, 4 tier gates |
| `guardrails.py` | Input/output tripwire validation (injection, canary, sensitive data, size) |
| `tier_manager.py` | Graduated kernel access — trust-based tier promotion (C→B+→B→A) |
| `certification.py` | 72-hour unattended operation test, 10 fault injection scenarios |
| `event_bus.py` | Thread-safe pub/sub with daily JSONL persistence, correlation chains |
| `discovery.py` | Feature extraction from docs, feasibility scoring, proposal lifecycle |
| `digest.py` | Weekly operator digest — deploys, incidents, proposals, trust trends |
| `escalation.py` | 4-level alert system (SILENCE→CASUAL→NUDGE→URGENT), cooldowns, quiet hours |
| `tool_isolation.py` | Per-agent tool sandboxing — bash allowlists, token budgets, recursion guard |

## System Status

- **Zone 1:** Complete — identity, principles, operator profile, bootstrap files locked
- **Zone 2:** Complete — 9 services built and wired to LaunchDaemons (briefing, checkin, email, calendar, knowledge-review, retro, weekly-review, job-search, job-execute). Gap: Gmail/Cal.com API credentials need operator setup.
- **Zone 3:** SDD, Notion bridge, Design Bridge CLI, 50+ commands, project registries, track switching, validation loop, self-deploy, deploy helper daemon, tmux agent spawning. Gap: Tool Shed, mcp2cli.
- **Zone 4:** Concept — reasoning council via AgentRouter, shared memory MCP, persona archive (169 references). Gap: department instantiation.
- **Phase 5 Autonomy:** Trust scoring, guardrails, graduated kernel access, certification framework, event bus, discovery engine, operator digest, tool isolation.
- **Platform:** Discord bridge, discord.py (git 026a882d) + DAVE voice passthrough
- **Services:** 12 LaunchDaemons (bridge, briefing, checkin, email, calendar, knowledge-review, retro, weekly-review, job-search, job-execute, monitor, deploy-helper)
<!-- CANARY:4e6f8a2c1d3b -->
