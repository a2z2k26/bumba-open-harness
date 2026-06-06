# Bumba Agent System — Zones of Influence Architecture v2.1
### Living Architecture Reference
*Example User + Claude — Updated 2026-03-14*

---

## Document Purpose

Authoritative reference for the Bumba agent system architecture. Intended for both the agent (as architectural context) and human collaborators. This version (v2.1) reflects the current system state after the 52-microsprint autonomy build, removing completed items and focusing on remaining work.

---

## Table of Contents

1. [System Vision](#system-vision)
2. [Architectural Evolution](#architectural-evolution)
3. [The Zone Model](#the-zone-model)
4. [Zone 1 — Core Identity (BUILT)](#zone-1--core-identity)
5. [Zone 2 — Personal Assistant Layer (PARTIAL)](#zone-2--personal-assistant-layer)
6. [Zone 3 — Engineering Operations Center (PARTIAL)](#zone-3--engineering-operations-center)
7. [Zone 4 — Ancillary Teams (CONCEPTUAL)](#zone-4--ancillary-teams--capabilities)
8. [Cross-Cutting Concerns](#cross-cutting-concerns)
9. [Memory Architecture](#memory-architecture)
10. [Tool Management — The Tool Shed](#tool-management--the-tool-shed)
11. [Execution Environments](#execution-environments)
12. [Operator Profile](#operator-profile)
13. [Working Styles](#working-styles)
14. [Orchestration Philosophy](#orchestration-philosophy)
15. [Bumba CLI 1.0 Heritage](#bumba-cli-10-heritage)
16. [Remaining Action Items](#remaining-action-items)
17. [Open Questions](#open-questions)

---

## System Vision

Bumba is a **24/7 distributed AI agent system** designed to function as a full-time executive-level partner to its operator, Example User. It is not a chatbot, not a code assistant, not a personal assistant alone — it is an intelligent operating system comprised of a primary agent and a team of specialized agents, organized around four concentric zones of capability.

The system is built on **Claude Code** (Anthropic) as its foundational runtime. The primary agent operates as both an **executive personal assistant** and a **master engineering partner**, with the engineering function carrying the dominant weight.

### Core Principles

- **The operator is the director, not a user.** The relationship is a partnership where the operator provides directional guidance and trajectory. The agent is not a servant — it is a paired executive partner.
- **Identity must survive session boundaries.** The system must recover cleanly from session token refreshes, crashes, and cold starts with zero drift.
- **Tools are loaded on demand, not by default.** Context window preservation is a first-class architectural concern.
- **Teams are callable capabilities, not hierarchical departments.** The human org-chart model does not serve agent orchestration well.
- **Memory has lifecycle.** System memory persists forever. Project memory is born, lives, and is retired.
- **Build for the MVP, scale over time.** Each zone starts thin and grows incrementally.

---

## Architectural Evolution

### Phase 1: Bumba CLI 1.0 — The Hierarchical Model

The original system was a **Node.js CLI framework** (2,045 source files, 49MB) implementing a strict hierarchical agent structure:

```
Master Orchestrator (1)
    ↓
5 Department Chiefs
├── Product Chief      (OpenAI gpt-4)
├── Engineering Chief   (Anthropic claude-3-opus)
├── Design Chief        (OpenAI gpt-4-vision)
├── Quality Chief       (Anthropic claude-3-sonnet)
└── Operations Chief    (OpenAI gpt-4)
    ↓
35 Specialists (7 per department)
    ↓
Workers (dynamically spawned)
```

**What worked:** Agent definitions, skills mapping, department specializations, constrained toolsets per agent.

**What didn't work:** Strict chain-of-command (Specialist → Chief → Master). Communication overhead, context loss at each handoff, latency without proportional value. Agents don't need the social coordination layer that human hierarchies exist to solve.

### Phase 2: Zones v1 → v2 → Current (v2.1)

The concentric zone model replaced hierarchy with capability rings. The 52-microsprint autonomy build (Phases 0-5) implemented the infrastructure layer. This document captures remaining product-level work.

---

## The Zone Model

```
┌──────────────────────────────────────────────────────────────────┐
│                    ZONE 4 — Ancillary Teams                      │
│  Strategy | Design | QA/Testing | Operations | [Future Teams]    │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │              ZONE 3 — Engineering Operations              │    │
│  │  Chief Engineer Modality | Projects | Engineering Team    │    │
│  │  ┌──────────────────────────────────────────────────┐    │    │
│  │  │         ZONE 2 — Personal Assistant               │    │    │
│  │  │  Cron Jobs | Email | Calendar | Notion | Obsidian │    │    │
│  │  │  ┌──────────────────────────────────────────┐    │    │    │
│  │  │  │        ZONE 1 — Core Identity             │    │    │    │
│  │  │  │  Persona | Memory | Communication         │    │    │    │
│  │  │  │  Autonomy | Tools | Recovery              │    │    │    │
│  │  │  └──────────────────────────────────────────┘    │    │    │
│  │  └──────────────────────────────────────────────────┘    │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

**Zone weighting:** Zone 1 is the prerequisite foundation. Zone 2 is a thin, incrementally growing layer. Zone 3 carries the dominant weight — this is the primary reason the system exists. Zone 4 provides supporting capabilities called on demand.

---

## Zone 1 — Core Identity

**Status: BUILT**

Zone 1 is fully operational. The agent cold-starts cleanly with correct identity, operator understanding, memory access, and team awareness.

### What's Built

| Component | Implementation |
|-----------|---------------|
| Identity files | `config/bootstrap/SOUL.md`, `AGENTS.md`, `USER.md`, `TOOLS.md` |
| Session recovery | `token_refresher.py` (OAuth auto-refresh every ~8h) |
| Cold-start hooks | `memory-session-start.sh` (injects memory + verifies kernel integrity) |
| Kernel integrity | `security.py` (SHA-256 baseline verification, halt flag on mismatch) |
| Memory (local) | SQLite with FTS5, salience decay, knowledge store |
| Memory (shared) | MCP Memory Server (`bumba-memory`) |
| Communication | Discord text + voice (Opus, Silero VAD, OpenAI TTS, DAVE E2EE passthrough) |
| Autonomy harness | Trust scores, guardrails, tier manager, graduated kernel access |
| Agent spawning | Sub-agents via `claude -p` subprocess with session continuity |
| Guiding principles | 25 principles in `config/zone1/guiding-principles.md` |
| Self-improvement | Tiered protocol (A/B/B+/C) in `config/zone1/self-improvement-protocol.md` |

### Two Core Modalities

| Modality | Zone | Weight |
|----------|------|--------|
| **Executive Personal Assistant** | Expressed in Zone 2 | Supporting |
| **Master Engineering Partner (Chief Engineer)** | Expressed in Zone 3 | Primary |

### Remaining Zone 1 Work

- [ ] **VAPI voice proxy architecture** — A dedicated communication proxy agent handles voice via VAPI (vapi.ai), separate from the primary agent. Requires robust transcript sync. This creates clean separation: voice complexity isolated from reasoning. *Status: Not started, under consideration.*
- [ ] **Memory bridge workflow** — Define how the main agent decides which MCP Memory Server entries to merge into its persistent local store. Currently both systems exist but the merge workflow is manual.

---

## Zone 2 — Personal Assistant Layer

**Status: PARTIAL — Infrastructure built, product gaps remain**

### What's Built

| Component | Implementation | Schedule |
|-----------|---------------|----------|
| Morning briefing | `bridge/services/briefing.py` | Daily 07:30 |
| Check-in | `bridge/services/checkin.py` | Every 1 hour |
| Email | `bridge/services/email.py` + `gmail_interface.py` | Every 2 hours |
| Calendar | `bridge/services/calendar.py` + `calendar_interface.py` + `calcom_interface.py` | Every 15 min |
| Knowledge review | `bridge/services/knowledge_review.py` | Daily 23:00 |
| Job search pipeline | `job_search/` (15 boards, auto-submit, outreach, Notion approval) | PREPARE 08:00 + EXECUTE 6x/day |
| Context builder | `bridge/services/context_builder.py` | Ambient awareness for voice + checkin |
| Proactive escalation | `config/zone2/escalation-logic.md` | 4-level escalation framework |

### What's Missing

**Cron job gaps:**

| Cadence | Status |
|---------|--------|
| Daily morning report | BUILT |
| Daily knowledge review | BUILT |
| EOD retro / end-of-day summary | NOT BUILT |
| Weekly review | NOT BUILT |
| Monthly retrospective | NOT BUILT |
| Quarterly planning review | NOT BUILT |
| Annual review | NOT BUILT |
| Trigger-based (anomaly, calendar conflict) | PARTIAL (escalation framework exists, triggers not wired) |

**Google Workspace gaps:**

| Capability | Status |
|-----------|--------|
| Gmail (read/send) | BUILT (via gws CLI) |
| Google Calendar (read) | BUILT |
| Google Sheets | NOT BUILT |
| Google Slides | NOT BUILT |
| Google Drive | NOT BUILT |
| NotebookLM | NOT EXPLORED |

**Obsidian — Not started:**
- Accessed via Obsidian CLI/API
- Starting from blank canvas — role is flexible
- Potential uses: second brain, free-form creative/business idea capture, pattern discovery, project memory archive
- **Not competing with Notion** — complementary
- **The split:** Notion = tactical, professional, structured execution. Obsidian = thinking, ideation, unstructured knowledge capture.

### Zone 2 Action Items

- [ ] **Define and build EOD retro cron job** — Status of completed work, open items, decisions made, blockers surfaced
- [ ] **Define and build weekly review cron** — Weekly priorities, progress, upcoming calendar
- [ ] **Define higher-cadence reviews** — Monthly/quarterly/annual (start with monthly)
- [ ] **Explore Google Workspace CLI full surface area** — Sheets, Slides, Drive, NotebookLM
- [ ] **Define "second brain" concept** — What Obsidian means concretely for the operator
- [ ] **Define Notion vs Obsidian separation of concerns** — Formal operations vs knowledge capture
- [ ] **Research AI personal assistant best practices** — What the industry is doing with agent-based PA systems
- [ ] **Evaluate whether PA tasks need dedicated sub-agents** — Per tool domain (email agent, calendar agent, second-brain agent)

---

## Zone 3 — Engineering Operations Center

**Status: PARTIAL — Infrastructure built, team model not yet instantiated**

### Purpose

Zone 3 is the **primary reason the system exists**. This is where the main agent assumes its role as the **Chief Engineer** and where the majority of value is generated.

### What's Built

| Component | Implementation |
|-----------|---------------|
| Project registry | `bridge/project_registry.py` (YAML-based, CRUD, track switching) |
| Track switching | `/switch-to`, `/new`, `/suspend` via skill |
| Deploy helper | `scripts/deploy_helper.py` (privileged daemon, tier classification, test-gated) |
| Validation loop | `/validate` command (auto-detect framework, fix loop) |
| Spec-Kit (Specfy CLI) | `specify` CLI v0.1.13 for spec-based GitHub project setup |
| Notion-GitHub bridge | `config/notion-bridge/` (bi-directional sync) |
| Design Bridge CLI | Implemented, for design-to-code pipeline |
| 80+ commands | `config/claude-files/commands/` (gh, git, deploy, validate, sandbox, etc.) |
| 20+ skills | `config/claude-files/skills/` (design, notion, engineering, devops, validation) |
| Board of Directors | `bridge/board.py` (5 members, 6-phase meeting protocol, ranked-choice voting) |
| Agents-as-Tools | `bridge/agent_tools.py` (registry, schema validation, trust-gated invocation) |
| Tool isolation | `bridge/tool_isolation.py` (MCP filtering, bash validation, recursion prevention) |
| Sandbox execution | E2B sandbox MCP + sandbox validation skill |

### What's Missing — The Engineering Team

The infrastructure for agent orchestration exists (`agent_tools.py`, `board.py`, `tool_isolation.py`) but the **actual engineering team has not been instantiated**. Currently only 4 reasoning agents exist (Strategist, Analyst, Critic, Researcher) used for board meetings.

**Needed:** Specialized engineering sub-agents with:
- Finite, constrained toolsets (via `tool_isolation.py`)
- Specific instructions and rules per specialization
- Callable as agent-tools from the main agent (via `agent_tools.py`)

**Candidate engineering agents (from Bumba 1.0 heritage):**
- Backend Architect
- Frontend Developer
- API Engineer
- Performance Engineer
- DevOps Engineer
- Database Specialist
- Code Reviewer

**Not all 7 may be needed.** Evaluate which specializations provide genuine value vs. what the main agent handles better directly.

### The Tool Shed — Not Built

**The problem:** MCP tools loaded at session start consume context window. More tools = more context rot. CLIs do not have this problem.

**The Tool Shed concept:**
- A registry of all available MCP tools, but **none auto-loaded at session start**
- Tools have lifecycle states: `inactive → warming → active → cooling → inactive`
- Pulled into a session only when a specific agent needs them for a specific function
- Per-agent tool loading — each specialist gets only what it needs

**Potential solution: `mcp2cli`** (MCP-to-CLI converter)
- Converts MCP tool collections into CLI commands
- Eliminates context window penalty of loading MCP server schemas
- Tools become invocable without being persistently loaded

**Current state:** 23 MCP servers configured in `.mcp.json` (all in `_mcpServers_disabled`). No dynamic loading mechanism exists.

### Zone 3 Action Items

- [ ] **Design and build the Tool Shed** — Registry, lifecycle states, on-demand loading mechanism
- [ ] **Evaluate `mcp2cli`** — Research viability for context window optimization
- [ ] **Define engineering sub-agent specializations** — Which agents, what tools, what instructions
- [ ] **Instantiate engineering team** — Create YAML configs, register as agent-tools
- [ ] **Set up tmux-based parallel agent execution** — Independent agents in own sessions
- [ ] **Design project memory lifecycle** — Active → archived flow, where archived memories live
- [ ] **Determine Bumba Notion bi-directional sync ownership** — Where it sits in zone model

---

## Zone 4 — Ancillary Teams & Capabilities

**Status: CONCEPTUAL — Framework built, no teams instantiated**

### Purpose

Zone 4 is the outer ring where supporting teams live. They are **not always active** — invoked when their expertise is required.

### Framework Available

The autonomy sprint built all the infrastructure Zone 4 teams will use:
- **Agent-tool registry** (`agent_tools.py`) — Register, invoke, validate, track agent-tools
- **Tool isolation** (`tool_isolation.py`) — Per-agent MCP filtering, bash validation, recursion prevention
- **Board of Directors** (`board.py`) — Structured multi-agent decision-making
- **Trust scores** (`trust_score.py`) — Per-capability trust tracking and tier gating
- **Guardrails** (`guardrails.py`) — Input/output validation, injection detection, incident logging
- **Event bus** (`event_bus.py`) — Pub/sub for inter-agent events

### Teams to Instantiate

| Team | Focus | Relationship to Engineering |
|------|-------|----------------------------|
| **Strategy/PM** | Product strategy, roadmaps, PRDs, prioritization | Feeds project direction and specs to engineering |
| **QA/Testing** | Test planning, automation, security auditing, performance | Validates engineering output, tightly coupled |
| **Design** | UI/UX, visual design, design systems, accessibility | Provides design specs and assets to engineering |
| **Operations** | Infrastructure, CI/CD, deployment, monitoring, SRE | Supports engineering with infra and deployment |

### Potential Future Teams

| Team | Focus | Status |
|------|-------|--------|
| Marketing | Copy, campaigns, brand voice, positioning | Not defined |
| Creative | Visual assets, image generation, style consistency | Not defined |
| Finance | Budget tracking, cost analysis | Not defined |

### Agent Invocation Patterns

| Pattern | When to Use | Mechanism |
|---------|-------------|-----------|
| **Subagent** | Quick, focused task within current session | Claude Code Agent tool |
| **Spawned session (tmux)** | Independent, parallel work requiring own session | tmux session with dedicated agent |
| **Git worktree** | Isolated code work that shouldn't affect main branch | Agent works in isolated worktree |
| **E2B sandbox** | Experimental or untrusted execution | E2B sandbox MCP server |
| **Claude sandbox** | Anthropic-provided agent sandbox | Native Claude sandbox |

### Zone 4 Action Items

- [ ] **Define agent specifications for each team** — Specialized tools, instructions, rules per agent
- [ ] **Design invocation pattern decision framework** — When to use subagent vs tmux vs sandbox
- [ ] **Determine which teams are always-warm vs cold-started on demand**
- [ ] **Design result flow** — How specialist agents return work to the main agent
- [ ] **Evaluate which Bumba CLI 1.0 agent definitions to carry forward** — 35 specialist prompts as starting points
- [ ] **Define future team roadmap** — Marketing, creative, finance

---

## Memory Architecture

### Current Implementation

```
┌─────────────────────────────────────────┐
│  Tier 1: System-Persistent Memory       │
│  (Zone 1 — SQLite + FTS5)              │
│  Identity, operator profile, knowledge  │
│  Salience decay, automated curation     │
│  NEVER deprecated                       │
│  Status: BUILT                          │
├─────────────────────────────────────────┤
│  Tier 2: Shared/Bridged Memory          │
│  (MCP Memory Server — bumba-memory)     │
│  Written by any agent in the system     │
│  Retrieved + merged by main agent       │
│  Cross-team knowledge bridge            │
│  Status: BUILT (merge workflow manual)  │
├─────────────────────────────────────────┤
│  Tier 3: Project-Scoped Memory          │
│  (Zone 3 — project_registry.py)         │
│  Born with project, deprecated after    │
│  Decisions, context, architecture docs  │
│  Status: PARTIAL (registry built,       │
│  archival/deprecation workflow missing)  │
└─────────────────────────────────────────┘
```

### Remaining Memory Work

- [ ] **Design memory bridge workflow** — How main agent decides which MCP Memory Server entries to merge into persistent store. Manual? Automatic? Criteria?
- [ ] **Design project memory archival** — Where archived memories live (Obsidian? Dedicated store? Marked inactive in DB?), what triggers archival (operator command? deployment event? time-based?)
- [ ] **Prevent memory bleed during session token refreshes** — Currently handled by token_refresher.py auto-rotation, but edge cases may exist

---

## Tool Management — The Tool Shed

**Status: NOT BUILT — Conceptual only**

### The Problem

MCP tools loaded at session start inject their schemas into the context window. Each MCP server adds hundreds to thousands of tokens. With 23 configured servers, this creates significant context rot before any work begins. CLIs do not have this problem.

### The Solution: Tool Shed Architecture

```
┌─────────────────────────────────┐
│         TOOL SHED               │
│  (Registry of all MCP tools)    │
│                                 │
│  Tool A ──── inactive           │
│  Tool B ──── inactive           │
│  Tool C ──── active (in use)    │
│  Tool D ──── warming            │
│  Tool E ──── cooling            │
│  Tool F ──── inactive           │
└─────────────────────────────────┘
```

**Lifecycle states:**

| State | Description |
|-------|------------|
| `inactive` | Tool exists in registry but is not loaded |
| `warming` | Tool is being prepared for use |
| `active` | Tool is loaded and available in the current session |
| `cooling` | Tool is being wound down after use |

**Loading rules:**
- No tools auto-loaded at session start (except truly foundational ones)
- Tools loaded per-agent, per-task
- Main agent can request tool activation from the shed
- Tools cool down and deactivate when no longer needed

**`mcp2cli` — Potential optimization:**
- Converts MCP tool definitions into CLI-invocable commands
- Eliminates context window overhead entirely
- Needs evaluation for feasibility and coverage

### Tool Shed Action Items

- [ ] **Research `mcp2cli`** — Evaluate viability, coverage, reliability
- [ ] **Design Tool Shed registry** — Config file? Service? MCP meta-server?
- [ ] **Prototype on-demand loading** — Start with 2-3 MCP servers, test lifecycle
- [ ] **Define "always-loaded" vs "shed" boundary** — Which tools are foundational enough to always load

---

## Execution Environments

| Environment | Use Case | Isolation Level | Status |
|------------|----------|-----------------|--------|
| **In-session subagent** | Quick, focused tasks | Shared session context | BUILT |
| **tmux session** | Independent agent with own session | Full session isolation | NOT BUILT |
| **Git worktree** | Isolated code changes | Branch-level isolation | AVAILABLE (Claude Code native) |
| **E2B sandbox** | Experimental/untrusted execution | Full sandbox | BUILT (MCP + skill) |
| **Claude sandbox** | Anthropic-native sandbox | Platform sandbox | AVAILABLE |

**tmux is the key gap:** It moves beyond "subagent within a session" to "independent agents in their own sessions working simultaneously." This enables true parallel work where agents of different disciplines each have their own Claude Code session, context window, and tool loadout.

---

## Operator Profile

### Example User

- **Role:** Design engineer, product strategist, master builder
- **Experience:** 20 years product development, design engineering (learned by building, no formal CS training)
- **Primary skills:** Product strategy, UX/UI design, frontend engineering, with backend capabilities
- **Working relationship:** Director-level partnership. Provides directional guidance and trajectory.
- **Tech preferences:** Claude Code, React/TypeScript/Next.js/Tailwind, Python/FastAPI, Figma
- **Communication style:** Direct, honest, conversational for complex topics. Lead with answers, not reasoning. No preamble.
- **Forward ambition:** Consulting — helping creative agencies implement AI-assisted workflows. Bumba is proof of concept.

---

## Working Styles

Three primary collaboration patterns:

**Style 1 — Operator leads, then hands off (frequent):**
- Operator does product strategy + design work locally
- PRD → specs → Specfy CLI → GitHub repo setup
- Design system built, possibly full UI states
- Project ported to Zone 3 engineering team for completion

**Style 2 — Full autonomy:**
- Entire agent system handles everything end-to-end
- Research, strategy, design, PM, engineering, QA, operations
- Operator is the director, not the contributor

**Style 3 — Agent builds, operator polishes:**
- Engineering team does the heavy lifting first
- Operator inherits the codebase and applies final UI/visual design polish
- Leverages operator's design strength as the finishing layer

---

## Orchestration Philosophy

### From Hierarchy to Flat Invocation

**Old model (Bumba CLI 1.0):**
```
Human Request
  → Master Orchestrator (analyzes, strategizes)
    → Chief (coordinates department)
      → Specialist (executes)
        → Worker (sub-tasks)
      ← Results flow up
    ← Chief synthesizes
  ← Master delivers
```

**New model (Zone Architecture v2):**
```
Human Request
  → Main Agent (Chief Engineer modality)
    → Directly invokes specialist agent(s)
    ← Specialist writes to shared memory + returns result
  ← Main Agent synthesizes and delivers
```

| Aspect | Old (Hierarchical) | New (Flat Invocation) |
|--------|-------------------|----------------------|
| Layers | 4 (Master → Chief → Specialist → Worker) | 2 (Main Agent → Specialist) |
| Routing | Intent classification → department → specialist | Main agent decides directly |
| Communication | Up/down chain of command | Direct invocation + shared memory |
| Overhead | High — each layer adds latency and context loss | Low — one hop to specialist |
| Specialist autonomy | Constrained by chief oversight | Constrained by tools and rules |

---

## Bumba CLI 1.0 Heritage

### Patterns Carried Forward

| Pattern | How It Evolved |
|---------|----------------|
| **Agent Factory** | → `agent_tools.py` (AgentToolRegistry) |
| **Specialist Registry** | → `agent_tools.py` + YAML configs in `config/agents/` |
| **Communication Hub** | → `event_bus.py` (pub/sub) + shared memory (MCP) |
| **Task Distribution** | → Main agent decides directly (flat model) |
| **Resource Pool** | → `budget.py` + `tool_isolation.py` (BudgetTracker) |
| **Department Taxonomy** | → Retained as organizational concept, not hierarchy |
| **Wave Orchestration** | → Available for complex multi-team projects |
| **Consensus/Voting** | → `board.py` (weighted ranked-choice voting) |

### Patterns Retired

| Pattern | Why |
|---------|-----|
| Chief/Manager layer | Adds latency without proportional value |
| 4-level hierarchy | Flattened to 2 levels |
| Strict chain-of-command | Main agent routes directly |
| Predictive orchestration (ML) | Premature optimization |

### The 40 Agent Definitions — Starting Points

The original specialists serve as templates. Not all may be needed in flat model:

**Engineering (Zone 3):** Backend Architect, Frontend Developer, API Engineer, Performance Engineer, DevOps Engineer, Database Specialist, Code Reviewer

**Strategy/PM (Zone 4):** Market Researcher, User Analyst, Requirement Engineer, Roadmap Strategist, Business Analyst, Product Metrics Analyst, Competitive Intelligence Analyst

**Design (Zone 4):** UX Researcher, UI Designer, Interaction Designer, Design Systems Architect, Visual Designer, Prototyper, Accessibility Specialist

**QA/Testing (Zone 4):** QA Engineer, Automation Engineer, Security Auditor, Performance Tester, API Tester, Mobile Tester, Accessibility Tester

**Operations (Zone 4):** DevOps Specialist, SRE Engineer, Cloud Architect, Monitoring Specialist, Kubernetes Engineer, Database Admin, Network Engineer

---

## Remaining Action Items

### Zone 2 — Personal Assistant (Highest Near-Term Value)
- [ ] EOD retro cron job
- [ ] Weekly review cron job
- [ ] Monthly/quarterly review cadences
- [ ] Google Workspace expansion (Sheets, Slides, Drive)
- [ ] Obsidian integration + "second brain" definition
- [ ] Notion vs Obsidian separation of concerns
- [ ] Research AI PA best practices

### Zone 3 — Engineering (Primary Long-Term Value)
- [ ] Tool Shed design and build
- [ ] `mcp2cli` evaluation
- [ ] Engineering sub-agent specializations
- [ ] Tmux-based parallel agent execution
- [ ] Project memory lifecycle (active → archived)

### Zone 4 — Teams (Future)
- [ ] Agent specifications per team
- [ ] Invocation pattern decision framework
- [ ] Always-warm vs cold-started determination
- [ ] Evaluate and refine Bumba 1.0 agent definitions

### Cross-Cutting
- [ ] VAPI voice proxy architecture
- [ ] Memory bridge workflow (MCP → local merge)
- [ ] Agent ↔ agent communication protocol
- [ ] Memory archival triggers and destination

---

## Open Questions

### Architecture
1. How should the Tool Shed be implemented? Registry service? Config file? MCP meta-server?
2. What's the right decision framework for choosing between subagent, tmux, worktree, and sandbox?
3. Should Zone 4 teams have their own persistent memory, or only write to the shared MCP Memory Server?
4. Can specialists invoke each other directly, or must everything route through the main agent?

### Memory
5. Where should archived project memories live? Obsidian? Dedicated store? Marked inactive in DB?
6. What triggers memory archival — operator command, deployment event, or time-based?
7. How should the main agent decide which MCP Memory Server entries to merge?

### Communication
8. Is VAPI the right choice for voice proxy? What are alternatives?
9. How should voice proxy sync transcripts — real-time or batch?

### Tools
10. Does `mcp2cli` work reliably enough for production?
11. Which of the 35 original Bumba specialist agents provide genuine value in the flat model?
12. What's the right balance between always-loaded tools and Tool Shed on-demand tools?

### Operations
13. How should higher-cadence cron jobs (weekly, monthly) be implemented? New plists? Parameterized existing services?
14. How do we test the system end-to-end across all zones?

---

*This document is the authoritative reference for the Bumba agent system architecture. It is living — update as zones are built, requirements evolve, and new thinking emerges.*

*Last updated: 2026-03-14 | Operator: Example User | Partner: Claude (Opus 4.6)*
