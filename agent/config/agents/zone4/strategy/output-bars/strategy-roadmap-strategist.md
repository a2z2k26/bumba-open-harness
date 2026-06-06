<!-- status: current — authored 2026-05-18 (#2134 / Sprint 5s.02) -->

# Output Quality Bar — `strategy-roadmap-strategist`

**Specialist:** strategy-roadmap-strategist
**Paired workflow:** `strategy.prd_authoring` (#2184) + future `strategy.roadmap_authoring` candidate
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A roadmap artifact saved under `docs/strategy/roadmaps/<date>-<topic>.md` (or Notion equivalent), plus a Discord summary on completion.

### Required output sections

1. **Roadmap scope** — what surface/product/initiative, what time horizon
2. **Milestones** — each: name, definition-of-done, expected date range, owner
3. **Sequencing logic** — why milestone B follows A; dependencies explicit; parallelizable tracks named
4. **Risk markers** — per milestone: known risks + mitigation + early-warning signals
5. **Re-plan triggers** — what should trigger a roadmap revision (date slips beyond X, scope changes, market shifts)

---

## 2. The bar (what's acceptable)

**A roadmap is acceptable when:**

- **Milestones have definition-of-done.** Not "ship feature X" — what specifically counts as shipped.
- **Sequencing rationale explicit.** "B follows A because A's API surface is required for B's implementation" — not "felt right".
- **Risk markers per milestone.** Each milestone has at least one named risk + mitigation + early-warning signal.
- **Parallelizable tracks identified.** If C is independent of A/B, the roadmap shows that — operator knows what can run concurrently.
- **Re-plan triggers explicit.** What condition fires a revision? Without this, roadmaps drift and operators stop trusting them.

**Specifically NOT acceptable:**

- Milestones without DoD ("ship X")
- Sequencing without rationale (looks ordered, isn't)
- No risk markers ("we'll deal with issues as they come")
- Sequential layout when work is actually parallelizable (operator burns calendar time)
- No re-plan triggers (roadmap becomes a wish-list, not a plan)

---

## 3. Failure modes

| Mode | Symptom | How to catch |
|---|---|---|
| **DoD absent** | "Ship voice feature" without "voice handles outbound + inbound + handles 3 ATS families" | Every milestone gets a DoD checklist |
| **Sequence-by-vibe** | Milestones ordered without dependency rationale | Each non-first milestone cites its predecessor + why |
| **Risk-blind** | Roadmap reads like everything ships on time | Every milestone has a risks subsection (even if low) |
| **Forced sequential** | C listed after B even though C has no B-dependency | Parallel-tracks section must enumerate what can run concurrently |
| **No re-plan triggers** | Date slips happen silently; roadmap stays "as planned" | Section 5 must list conditions that force revision |
| **Owner-orphan** | Milestones listed without an owner | Owner column required per milestone |

---

## 4. Recent specialist invocations

| Date | Roadmap topic | Milestones | DoD per? | Risks per? | Notes |
|---|---|---|---|---|---|
| YYYY-MM-DD | _topic_ | _N_ | _all / partial_ | _all / partial_ | _what worked, what to refine_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has authored ≥3 real roadmaps.

- [ ] Healthy — DoD per milestone, sequencing rational, risks named, parallelism identified
- [ ] Degraded — roadmaps ship but DoD or risk markers thin
- [ ] Stale — operator stopped trusting roadmaps (dates drift, no re-plan)

Date recorded: _____________
