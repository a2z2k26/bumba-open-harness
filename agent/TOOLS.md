# Tools

## MCP Servers (13 entries / 12 effective)

All auto-discovered via `.mcp.json`. Credentials resolved from `.secrets` via `${VAR}` references. Canonical mirror of runtime: `config/mcp-servers.canonical.json` (verified via operator probe 2026-05-12, issue #1735). Template `config/mcp-servers.template.json` is a 23-server historical reference used as a test fixture, NOT a deploy target.

> **Canonical tool surface:** see `docs/architecture/main-agent-tool-surface.md` for the full inventory of built-in tools, MCP servers, bash patterns, and filesystem scope — the baseline against which drift is measured.

| Server | Category | Purpose |
|--------|----------|---------|
| github | Code | GitHub API — repos, issues, PRs, code search |
| brave-search | Search | Web search via Brave API |
| context7 | Knowledge | Library documentation lookup |
| pinecone | Knowledge | Vector similarity search |
| mongodb | Data | MongoDB Atlas operations — queries, collections, indexes |
| bumba-memory | Agent | Persistent shared memory for multi-agent coordination |
| bumba-sandbox | Agent | E2B sandbox orchestration for isolated code execution |
| playwright | Code | Headless browser automation, E2E testing, screenshots |
| chrome-devtools | Code | Chrome DevTools inspection and debugging |
| digitalocean | DevOps | DigitalOcean apps, databases, droplets management |
| shadcn | Design | shadcn/ui component library discovery and usage |
| paper | Design | Paper.design — read/write canvas, create artboards, export JSX |
| _cloudflare_disabled | DevOps | **Parked stub** — disabled 2026-05-09 (4-day crash loop). Underscore-keyed entry preserves re-enable hint; not loaded by Claude at runtime. |

## CLI Tools

| Tool | Purpose |
|------|---------|
| `claude` | Claude Code CLI — subprocess invocation via `claude -p` |
| `python3` | Python 3 runtime (macOS default) |
| `pytest` | Test runner for bridge and job search tests |
| `git` | Version control |
| `gh` | GitHub CLI — PRs, issues, repos, actions, code search |
| `tmux` | Terminal multiplexer — persistent agent sessions |
| `docker` | Container runtime and MCP gateway |
| `npm` / `npx` | Node.js package management (MCP servers) |
| `node` | Node.js runtime (MCP servers, hooks) |
| `gws` | Google Workspace CLI — email sending for job search outreach |
| `playwright` | Playwright CLI — browser automation, E2E testing |
| `codeql` | CodeQL CLI — code analysis and security scanning |
| `obsidian` | Obsidian CLI — note management |
| `runpodctl` | RunPod CLI — GPU cloud management |
| `launchctl` | macOS service management (operator-only, via deploy scripts) |
| `sqlite3` | Direct database queries when needed |

## Commands (80+)

**Design Pipeline**: `/design-init`, `/design-search`, `/design-explore-ui`, `/design-explore-ux`, `/design-layout-to-*` (jsx, html, tailwind, vue, flutter, swiftui, compose), `/design-transform-*` (react, vue, angular, svelte, flutter, swiftui, compose, react-native, web-components), `/design-layout-refine`, `/design-promote`, `/design-generate-styles`, `/design-nlp`, `/design-bridge`, `/design-sync-monitor`
**Design Director**: `/design-director-*` (init, vision, roadmap, data-model, section-spec, shell-spec, screen-spec, sample-data, export, run)
**Orchestration**: `/orc:brainstorm`, `/orc:requirements`, `/orc:review-spec`, `/orc:plan-sprints`, `/orc:plan-feature`, `/orc:quick`, `/orc:parallel`, `/orc:export`
**GitHub**: `/gh:create-issues`, `/gh:create-pr`, `/gh:merge-pr`, `/gh:review-pr`, `/gh:address-feedback`, `/gh:sync-notion`
**Git**: `/git:feature-branch`, `/git:hotfix-branch`, `/git:sync-branch`
**E2B**: `/e2b:management:*` (start, status, debug, exec, test, snapshot, restore, cleanup), `/e2b:orchestration:*` (status, events, pause/resume), `/e2b:templates:*`, `/e2b:cost-report`, `/e2b:optimize`
**Testing**: `/testing:all`, `/testing:feature`, `/testing:matrix`
**Project**: `/project:init`, `/project:register`, `/project:config`, `/project:status`
**Notion**: `/notion:sync`, `/notion:project`, `/notion:status`
**Sandbox**: `/sandbox:init`, `/sandbox:exec`, `/sandbox:orchestrate`
**Lifecycle**: `/deploy`, `/validate`, `/idea` (Obsidian capture)
**Operations**: `/audit-review`, `/backup-knowledge`, `/disk-check`, `/health-check`, `/memory-action`, `/recent-errors`, `/run-maintenance`, `/search-knowledge`, `/session-stats`, `/summarize-logs`, `/what-do-you-know`

## Agents (55)

Agents are markdown definitions in `~/.claude/agents/`. They load on-demand — zero context cost until invoked. Source of truth: `ls ~/.claude/agents | wc -l`.

> **Snapshot caveat:** the agent and plugin counts below are point-in-time snapshots, not live gospel. The tool landscape evolves; trust the source-of-truth commands over the numbers in this header.

**Design (8)**: chief, ui-designer, visual-designer, ux-researcher, interaction-designer, system-architect, prototyper, accessibility-specialist
**Engineering (8)**: chief, backend-architect, frontend-developer, api-engineer, code-reviewer, database-specialist, devops-engineer, performance-engineer
**QA (8)**: chief, engineer, automation-engineer, api-tester, performance-tester, security-auditor, accessibility-tester, mobile-tester
**Operations (8)**: chief, cloud-architect, database-admin, devops-specialist, kubernetes-engineer, monitoring-specialist, network-engineer, sre-engineer
**Strategy (8)**: product-chief, business-analyst, market-researcher, requirement-engineer, roadmap-strategist, product-metrics-analyst, competitive-intelligence-analyst, user-analyst
**Ancillary (15)**: ai-engineer, cli-developer, data-engineer, fastapi-pro-developer, flutter-expert, graphql-architect, llm-architect, mcp-developer, nextjs-developer, penetration-tester, prompt-engineer, react-specialist, seo-specialist, swift-expert, terraform-engineer

## Plugins (27 installed)

Source of truth: `cat ~/.claude/plugins/installed_plugins.json` (top-level `plugins` keys).

**Marketplaces (3)**: `claude-plugins-official` (22 plugins), `anthropic-agent-skills` (2), plus single-source marketplaces (`obsidian-skills`, `karpathy-skills`, `everything-claude-code`).

**Currently installed (selected, by capability):**
- **Code/dev (10)**: code-review, feature-dev, code-simplifier, pr-review-toolkit, superpowers, agent-sdk-dev, semgrep, typescript-lsp, swift-lsp, serena
- **Design (3)**: figma, frontend-design, playground
- **Knowledge (4)**: context7, pinecone, Notion, skill-creator
- **Productivity (5)**: document-skills, example-skills, ralph-loop, claude-code-setup, obsidian
- **Platform (3)**: playwright, github, supabase
- **Ecosystem (2)**: everything-claude-code, andrej-karpathy-skills

## Bumba Ecosystem

| Component | Purpose |
|-----------|---------|
| Bumba Agents (this system) | 24/7 agent — zone-based architecture, Discord bridge |
| Bumba Design | Design components, Figma plugin, design tokens |
| Bumba Design Bridge | Socket server connecting Figma to code transforms |
| Bumba Memory MCP | Persistent memory server for agent recall |
| Bumba Sandbox MCP | E2B sandbox orchestration server |
| Bumba Notion | Notion integration layer |
| Bumba CLI 1.0 | Original 40-agent hierarchical system (legacy, reference only) |
| Marcion | Sibling harness for emergence and exploration work |
| Muse | Sibling harness for creative production studio work |
| Achilles | Mobile capture harness — pushes notes into the Obsidian vault |
| Obsidian vault | Shared memory layer across sibling harnesses |

## Scheduled Services

These run as independent LaunchDaemons — the agent's autonomous operational backbone:

| Service | Schedule | Purpose |
|---------|----------|---------|
| `bridge` | Always-on | Discord bot, message processing, health endpoint |
| `briefing` | Daily 08:00 | Morning briefing to operator |
| `checkin` | Multiple daily | Proactive check-ins |
| `monitor` | Hourly | System health checks |
| `job_search` | Daily 08:00 | PREPARE — scrape, dedup, stage in Notion |
| `job_search_execute` | Every 2hrs 10-20:00 | EXECUTE — send approved outreach |
| `knowledge_review` | Daily 23:00 | Knowledge maintenance |
| `retro` | Daily 18:00 | End-of-day retrospective |
| `weekly_review` | Sunday 18:00 | Weekly summary |
| `deploy-helper` | Always-on | Process deploy requests (Tier A/B/C) |
