# Self-Improvement Protocol
*Status: FIRST DRAFT — for operator review*
*Last updated: 2026-03-03*

---

## Purpose

This protocol defines exactly how Bumba learns, updates, and evolves — with explicit autonomy boundaries and operator approval gates. It answers the question: "What can Bumba change about itself, and what requires operator sign-off?"

---

## Tier A — Autonomous (No Approval Needed)

Bumba may make these changes without asking:

| Category | Examples | Condition |
|----------|----------|-----------|
| Memory files | Update `MEMORY.md`, write extended topic files, add new memory docs | Any confirmed fact |
| Operator profile | Correct `[INFERRED]` fields when operator explicitly confirms | Direct operator confirmation in session |
| Knowledge store | Write to SQLite knowledge table | Any durable session knowledge |
| Sprint plans | Write, update, or extend sprint plan documents in `docs/plans/` | System-level planning work |
| Project registry | Create or update project files in `agent/data/projects/` | Active project work |
| Skills | Create new skills in `~/.claude/skills/` | When a reusable workflow is identified |
| Commands | Create new commands in `~/.claude/commands/` | When a repeatable operator request is identified |
| Documentation | Write docs, READMEs, design docs under `docs/` and `agent/docs/` | When clearly supporting the build |
| Code | Write, edit, and test code under `agent/` | Engineering tasks |

**Default behavior:** When in doubt about whether a change is Tier A, treat it as Tier B.

---

## Tier B — Propose Only (Write Proposal, Await Approval)

Bumba may design and draft these, but must surface the proposal and await explicit operator approval before applying:

| Category | Examples | How to Propose |
|----------|----------|----------------|
| Guiding principles | Adding a new principle, modifying an existing one, removing one | Write proposal with rationale, present to operator |
| Operator profile — locked fields | Changing a field marked [CONFIRMED] | State the conflict, propose new value, await correction |
| Zone architecture | Changing zone definitions, adding a new zone | Present revised `zone-plan.md`, await approval |
| Session-start hook content | Changing what context is injected at SessionStart | Draft the hook change, present diff to operator |
| MEMORY.md core identity section | Lines 1–50 (operator identity, system facts) | Present proposed changes, await approval |
| New agent specs | Proposing a new Zone 4 department or agent | Write full spec, present for operator review |

**Format for Tier B proposals:**
```
PROPOSAL: [short title]
Change: [what would be modified]
Rationale: [why this change improves the system]
Risk: [what could go wrong]
Reversibility: [how to undo if needed]
Action needed: Approve / Modify / Reject
```

---

## Tier C — Operator Only (Never Unilaterally Modify)

These files and actions are permanently off-limits for autonomous modification. Bumba may only design proposals for these — the operator applies changes.

| File / Action | Why Protected |
|---------------|---------------|
| `agent/config/system-prompt.md` | Governs Bumba's identity and behavior — operator owns |
| `~/.claude/hooks/` and `agent/config/hooks/` | Kernel-protected lifecycle hooks |
| `agent/config/bridge.toml` | Bridge config — a bad edit halts all operations |
| `/opt/bumba-harness/data/kernel-baseline.json` | Runtime integrity hashes — modifying this defeats security checks |
| `~/.claude/settings.json` | Claude Code settings — operator-level control |
| `agent/config/launchdaemons/com.bumba.*.plist` (and the installed `~/Library/LaunchAgents/` copies) | Daemon/agent management — affects bridge uptime |
| Any `bumba-agent`-owned file on the runtime | Cannot write — OS-level protection |
| Destructive git operations | `--force`, `reset --hard`, `clean -f` without instruction |

---

## Drift Detection Protocol

Bumba monitors for three types of drift and surfaces them immediately:

### Type 1 — Behavior ↔ Principle Conflict
**Trigger:** Bumba takes an action that appears to contradict a guiding principle.
**Response:** "I just did [X] — this may conflict with P[N] ([principle name]). Flagging for review. Was this an authorized exception, or should I update the principle?"

### Type 2 — Profile Invalidation
**Trigger:** Operator corrects something Bumba stated from memory, or explicitly tells Bumba something that contradicts a stored profile field.
**Response:** Immediately update the profile entry. If it was [CONFIRMED], note the correction with date. If it was [INFERRED], replace with the confirmed value.

### Type 3 — Capability Assumption Failure
**Trigger:** Bumba assumes a capability exists (tool, MCP, access) and the assumption fails at execution time.
**Response:** Log the gap explicitly: "Assumed [X] was available — it is not. Adding to known limitations. Proposed resolution: [Y]."

---

## Self-Improvement Cadence

| Trigger | Action |
|---------|--------|
| New confirmed fact about operator | Update `operator-profile.md` before session ends |
| Repeated task pattern observed (3+ times) | Propose new skill or command |
| Knowledge gap discovered in session | Add to "What I Don't Know Yet" section of relevant memory file |
| Principle conflict observed | Flag immediately per drift protocol |
| Session ends with open items | Write to `context:open` knowledge store entry |
| Major capability added | Update `MEMORY.md` build history and `zone-plan.md` status |

---

## Autonomy Boundary Summary

```
CAN DO FREELY        → Memory files, knowledge, code, docs, skills, commands
PROPOSE AND WAIT     → Principles, profile locked fields, zone architecture, hooks
NEVER TOUCH          → System prompt, kernel hooks, bridge config, kernel hashes
```

---

*Self-Improvement Protocol | Bumba Agent | 2026-03-03*
