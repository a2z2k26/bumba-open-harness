# Bumba System Build Plan — Zones of Influence

*Derived from operator design discussion, 2026-03-02*

---

## Architecture Model

Concentric zones radiating outward from center. Each zone is a prerequisite for the next. Zone 1 must be complete before multi-track work begins.

---

## Zone 1 — Core Identity (PREREQUISITE GATE)

**What it is:** Soul, rhythm, guiding principles, understanding of operator, sense of purpose and intent.

**Must contain:**
- [ ] System prompt rewritten to reflect the bullseye architecture explicitly
- [ ] Operator profile fully documented (Example User — values, working style, priorities, context)
- [ ] Core guiding principles stated and locked (not implicit — written and committed)
- [ ] Zone architecture encoded in persistent memory
- [ ] Self-improvement protocol defined (how I learn, update, and evolve safely)

**Completion criteria:** Zone 1 is "done" when I can be restarted cold and immediately operate with the correct identity, purpose, and operator model — without reconstruction.

**Status:** Substantially built. System prompt (`agent/config/system-prompt.md`, version `2026-05-08-d7-7-voice-register`) and CLAUDE.md encode the zone model; operator profile + guiding principles + self-improvement protocol are LOCKED. Discord is the primary interface (Telegram no longer in scope). Remaining work tracked under #1112 Zone 1 reconciliation sweep.

---

## Zone 2 — Always-On Functions (Spinning Plates)

**What it is:** Evergreen, persistent, baseline actions that keep the operator safe and high-performing. Cron-driven. Cannot miss a beat.

**Target behaviors (initial list, to be refined):**
- Email management
- Calendar management
- Notes / knowledge capture
- Morning briefing / daily context load
- Proactive escalation on anomalies
- Periodic self-health checks

**Implementation approach:**
- Each function maps to: a cron schedule, a trigger condition, and an output format
- Already partially specced in `proactive-jobs.md`, `rhythm-schema.md`, `escalation-logic.md`
- Needs: completion, deployment, and testing

**Status:** Specced but not deployed. Dependent on Zone 1 completion.

---

## Zone 3 — Engineering (Primary Working Modality)

**What it is:** CTO function. The core use case. Complex software projects built securely and substantially, repeatedly.

**Key architectural challenge — multi-project context:**
- Multiple projects may be active simultaneously
- Projects must be callable on demand without polluting persistent memory when idle
- Solution: project registry (one memory file per project, structured schema)

**Project registry schema (per project):**
```
project: [name]
status: [active | suspended | deprecated]
stack: [...]
description: [1-2 sentences]
last_worked: [date]
where_we_left_off: [current state]
next_steps: [list]
key_files: [paths]
decisions: [list of architectural decisions made]
```

**Track switching protocol:**
- "Switch to [Project Name]" → load project registry → resume
- "Switch to System" → load zone plan → resume system work
- Suspended projects: registry retained, no context loaded until activated

**Engineering methodology — Specification-Driven Development (SDD):**
- Standard: GitHub Spec-Kit (`specify` CLI)
- New projects initialized with `specify init --ai claude`
- Each feature follows: constitution → specify → plan → tasks → implement
- Specifications are executable artifacts — code serves specs, not the reverse
- Reference: `agent/config/claude-files/docs/spec-kit-full-audit-report.md`

**Status:** Framework defined. Registry not yet created. Ready to instantiate on first project.

---

## Zone 4 — Departments (/board)

**What it is:** Ancillary sub-agent departments organized as pie slices around Zone 3 engineering. Each has a department chief (sub-agent), niche focus, semi-autonomous operation.

**Known departments (initial):**
- Engineering (resides in Zone 3 — the core)
- Marketing
- Image Gen
- [others TBD]

**My role:** Orchestrator at center. Route tasks to the right department. Synthesize outputs. Maintain coherence across the board.

**Implementation approach:**
- Each department: a sub-agent spec (persona, tools, scope, escalation path)
- Department chief agent: persistent, callable, context-loaded on demand
- /board command: list active departments, status, last activity

**Status:** Concept defined. No departments instantiated. Dependent on Zone 3 framework being stable.

---

## Cross-Cutting Infrastructure (All Zones)

These capabilities span all zones and are deployed progressively:

| Capability | Current Status |
|------------|----------------|
| MCP tools | Wired (see `agent/config/mcp-servers.canonical.json`) |
| Cron jobs | Multiple LaunchAgents deployed (see `agent/config/launchdaemons/`) |
| Commands | Many deployed under `~/.claude/commands/` |
| Skills | Many deployed under `~/.claude/skills/` |
| Hooks | Full lifecycle coverage under `agent/config/hooks/` (PreToolUse, PostToolUse, SessionStart, SessionEnd, Stop, SubagentStop, UserPromptSubmit, Notification, Error, PreCompact, PostCompact, PreModelInvoke, PostModelInvoke) |
| Plugins | Catalogued in `~/.claude/CLAUDE.md` / `TOOLS.md` (repo root) |

---

## Execution Plan

### Phase A — Zone 1 Hardening (Next dedicated session)
1. Rewrite system prompt to embed zone architecture
2. Complete operator profile (questionnaire or synthesis from conversation history)
3. Write and lock core guiding principles
4. Update MEMORY.md to reflect zone model as canonical structure
5. Define self-improvement protocol

### Phase B — Parallel Tracks (Post Zone 1)
- **Track: System** — Build Zone 2 functions, Zone 3 framework, Zone 4 departments incrementally
- **Track: Project [Name]** — Active engineering work, context-switched on demand
- Tracks are switchable. One active at a time. Both maintain continuity via registry.

### Phase C — /board Instantiation (When Zone 3 is stable)
- Define department taxonomy
- Write sub-agent specs
- Wire orchestration routing

---

## Track Switch Protocol

```
"Switch to System"         → load zone-plan.md, resume system work
"Switch to [ProjectName]"  → load projects/[name].md, resume engineering
"New project: [Name]"      → create project registry, activate track
"Suspend [ProjectName]"    → mark suspended, preserve registry
```

---

## Master Function Registry

*The 15 functions Bumba is designed to perform across all zones. Each function maps to one or more zones. This is the "what it does" layer — the capability roadmap that all zone work delivers against.*

| # | Function | Description | Primary Zone |
|---|----------|-------------|-------------|
| 1 | CAPTURE | Get thoughts in from anywhere | Zone 2 |
| 2 | ORGANISE | Put things in the right place | Zone 2 |
| 3 | REMEMBER | Know the operator, learn about him over time | Zone 1 + Zone 2 |
| 4 | RESEARCH | Find information, validate assumptions | Zone 3 + Zone 4 |
| 5 | THINK | Analyse, spot patterns, find contradictions | Zone 3 + Zone 4 |
| 6 | PRIORITISE | Tell the operator what matters most right now | Zone 2 |
| 7 | COACH | Push, give feedback, challenge, hold accountable | Zone 2 + Zone 4 |
| 8 | DESIGN | Architect solutions, blueprint products | Zone 3 |
| 9 | BUILD | Code it, make it real | Zone 3 |
| 10 | COMMUNICATE | Write and speak as the operator | Zone 2 + Zone 4 |
| 11 | TEACH | As any good teacher would | Zone 4 |
| 12 | MONITOR | Watch the world, alert when things change | Zone 2 |
| 13 | ANTICIPATE | Predict what's coming, be a futurist | Zone 2 + Zone 4 |
| 14 | PROTECT | Keep everything safe, portable, private | Zone 1 + all zones |
| 15 | ADAPT | The system improves itself | Zone 1 (self-improvement protocol) |

---

## Architecture Design Rules

*The 15 non-negotiable design principles that govern how Bumba is built — not what it does, but how it must be built to be trustworthy and durable.*

**Foundation** (without these, nothing else works):
1. **Own everything** — data is private and portable. the operator owns all data, always.
2. **Data safe** — all data is recoverable. No single point of loss.
3. **No work lost** — consolidate, commit, capture before switching contexts.

**Core** (the system's character):
4. **Brain swappable** — interoperable. Not locked to any single AI model or provider.
5. **Always on** — bridge runs 24/7, crash recovery, self-healing.
6. **Access from anywhere** — Discord as the universal interface.

**Behaviour** (how it acts):
7. **Acts first** — proactive, not reactive. Doesn't wait to be asked.
8. **Learns** — remembers the operator, updates the profile, builds on every interaction.
9. **Human in the loop** — for anything irreversible, the operator decides.

**Usability** (how the operator uses it):
10. **Voice-first** — fast, frictionless. Voice is the primary input target.
11. **Simple for the operator** — complexity is Bumba's problem, not the operator's.
12. **Mess-free** — clean outputs, clean state, no cognitive overhead.

**Growth** (what it becomes):
13. **Can grow** — extensible architecture. New zones, agents, capabilities added incrementally.
14. **Builds things** — real-world links. Ships working software, not just plans.
15. **Affordable** — sustainable cost model as capabilities expand.

**Meta-rule:**
16. **Rules are living** — rewrite when evidence proves a better way.

---

*This document is living. Update as zones are completed and new information emerges.*
