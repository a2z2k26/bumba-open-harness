# Agents

> Zone 1 core identity file. Sits alongside `OPERATOR.md`, `SOUL.md`, `RULES.md`, `TOOLS.md`. Cold-start reads this to know the constellation and the in-house roster.

## Ecosystem

Bumba does not run alone. There is a four-harness constellation, connected by a shared memory layer.

- **Bumba** — this harness. The 24/7 Mac Mini operation. Deterministic, reliable, production-facing. The system the operator leans on when something must work the same way every time.
- **Marcion** — sibling harness. Built for emergence and exploration where Bumba is built for reliability. Little brother — wider tolerance for novelty, lower expectation of consistency. Where new ideas get tried before they earn a place here.
- **Muse** — creative production harness. The studio. Where polished outputs are made — design comps, motion work, narrative, visual artifacts.
- **Achilles** — mobile harness. Lives on the operator's phone. Captures ideas wherever the operator is, pushes them into the vault so the rest of the constellation can pick them up.
- **Obsidian vault** — the shared memory layer. The nervous system. Every harness reads from it and writes to it. Continuity across machines, sessions, and weeks lives there, not in any one harness's process.

The design intent: four harnesses with distinct temperaments, one shared knowledge substrate. Each harness specialises. The vault is what keeps them coherent.

## Internal Agent Registry

Living document. Roster of departments, chiefs, and specialists *inside this harness.* For implementation depth (state machine, dispatcher, expertise injection, lifecycle), see [`agent/CLAUDE.md` — Zone 4 section](./CLAUDE.md). New agents get appended here as they're defined; retired agents stay listed with a strikethrough or note.

### How routing works (one paragraph)

A WorkOrder arrives at the chief dispatcher. The router picks a department based on a 4-tier rule chain (explicit target → keyword → batch strategy → default). The department's chief warms up, reads its expertise file, and decides how many specialists to call via the `delegate` tool. Specialists return synthesised outputs into the chief's context; the chief produces the final answer; the team shuts down. Chiefs run WARM single-run — one `manager.run()` per deliberation, then teardown. Cost is metered per department against `constraints.cost_limit_usd` declared in YAML.

### Departments (6 live)

Source of truth for the roster: `agent/config/agents/zone4/<department>/` and `agent/config/teams/<department>.yaml`. Source of truth for chief and specialist prompts: `agent/config/expertise/{updatable,read-only}/`.

#### Design

Visual design, UX research, interaction design, accessibility, prototyping, design systems. The team that produces or evaluates anything the operator would put his name on visually.

- **Chief:** `design-chief` — orchestrates the design team, synthesises across specialists.
- **Specialists (7):** `design-ui-designer`, `design-visual-designer`, `design-ux-researcher`, `design-interaction-designer`, `design-prototyper`, `design-system-architect`, `design-accessibility-specialist`.

#### QA

Test strategy, code review, security review, accessibility testing, mobile and API testing. The gate before anything ships.

- **Chief:** `qa-chief` — owns the test plan, synthesises across testers.
- **Specialists (8):** `qa-engineer`, `qa-code-reviewer`, `qa-automation-engineer`, `qa-api-tester`, `qa-performance-tester`, `qa-security-auditor`, `qa-accessibility-tester`, `qa-mobile-tester`.

#### Ops

Infrastructure, cloud, database admin, monitoring, networking, SRE. The team Bumba calls when the house itself needs work.

- **Chief:** `ops-chief` — synthesises operational decisions across specialists.
- **Specialists (7):** `ops-cloud-architect`, `ops-database-admin`, `ops-devops-specialist`, `ops-kubernetes-engineer`, `ops-monitoring-specialist`, `ops-network-engineer`, `ops-sre-engineer`.

#### Strategy

Product strategy, market research, requirements engineering, roadmap, metrics, competitive intelligence, user analysis. The team that turns intent into spec.

- **Chief:** `strategy-product-chief` — frames the product question, synthesises across analysts.
- **Specialists (7):** `strategy-business-analyst`, `strategy-market-researcher`, `strategy-requirement-engineer`, `strategy-roadmap-strategist`, `strategy-product-metrics-analyst`, `strategy-competitive-intelligence-analyst`, `strategy-user-analyst`.

#### Board (Strategy Board)

Deliberation pattern, not a standard chief-and-specialists team. The CEO frames a high-stakes question; the seven board members reason through it from their distinct perspectives in parallel; the CEO synthesises into a decision memo. Use for complexity-9+ decisions where adversarial perspectives add value (build-vs-buy, strategic pivots, architectural choices).

- **CEO:** `board-ceo` — frames the question, synthesises the memo.
- **Members (7):** `board-product-strategist`, `board-technical-architect`, `board-revenue`, `board-compounder`, `board-contrarian`, `board-moonshot`, `board-drunken-master`.
- **Also available:** `board-systems-thinker`, `board-openrouter-generalist`, `board-cross-vendor-strategist` (defined as expertise, not always seated).
- Triggered via `/board <question>` operator command. Deliberation engine: `bridge/peer_ranking.py`.

#### Job Search

Operational department — runs as a single-agent director, not a chief+specialists team. End-to-end outbound job-search pipeline: source roles, dedup, verify emails, stage outreach in Notion, send via `gws-gmail`. The cron-driven cousin of the deliberation departments.

- **Director:** `job-search-chief` (single-agent pattern; no chief synthesis layer).
- **Specialists (4, called inline):** `acquire-and-prepare-specialist`, `email-verification-specialist`, `outreach-execute-specialist`, `browser-use-specialist`.

### Where engineering work happens

There is no `engineering` Zone 4 department in this harness. Engineering execution lives at the Main Agent layer (Tier 1, Anthropic OAuth) — `claude -p` running in Zone 3 execution environments (SUBAGENT, WORKTREE, TMUX, E2B). Zone 4 is for multi-perspective deliberation, not code execution. The Main Agent is the engineer.

### Adding a new agent

When a new chief, specialist, or department is defined:

1. Add the YAML at `agent/config/teams/<dept>.yaml` (or extend an existing one).
2. Add the agent definition at `agent/config/agents/zone4/<dept>/<agent>.md`.
3. Add the expertise file at `agent/config/expertise/updatable/<agent>.md`.
4. Append the entry to this file under the right department.
5. Register the event types and metrics in `agent/config/registry/` (CI gate `registry-completeness` enforces this).

If the addition crosses ~30 specialists in a department, revisit the deferred sub-chiefs decision (see Memory: "Sub-chiefs deferred").
