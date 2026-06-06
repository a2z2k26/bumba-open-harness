<!-- status: current — authored 2026-05-18 (#2133 / Sprint 5o.02) -->

# Output Quality Bar — `ops-sre-engineer`

**Specialist:** ops-sre-engineer
**Paired workflow:** Manual invocation (no Phase 5 workflow yet; future `ops.incident_response` candidate)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

An incident response artifact: a markdown incident record saved under `docs/ops/incidents/<date>-<incident-name>.md`, plus a Discord summary with severity + mitigation status + post-mortem link.

Each incident response follows a 4-phase shape: acknowledge → scope → mitigate → post-mortem.

### Required output sections

1. **Acknowledge** — incident detected at timestamp, severity, scope of affected surface, who/what was paged
2. **Scope** — what's broken (specific symptoms), what's NOT broken (negative space), blast radius (users / systems / data affected)
3. **Mitigate** — actions taken in chronological order with timestamps, current state
4. **Post-mortem** — root cause, timeline, what worked, what didn't, action items with owners + deadlines
5. **Trigger conditions for re-evaluation** — what should fire a similar incident response in the future

---

## 2. The bar (what's acceptable)

**An incident response is acceptable when:**

- **Acknowledge fires fast.** Sub-5-minute acknowledge timestamp from incident detection. The mitigation can take hours; the acknowledge cannot.
- **Scope is bounded with negative space.** "API errors" is not scope. "POST /api/v1/voice/webhook 401s; GET /healthz green; all other endpoints unaffected" is scope.
- **Mitigation is timestamped.** Every action carries a wall-clock time so post-mortem reconstruction is possible.
- **Post-mortem doesn't blame humans.** Root cause is process / system / contract drift, not "Bumba should have noticed sooner."
- **Action items have owners + deadlines.** Vague "improve monitoring" is not an action item. "Add /api/v1/voice/webhook to /healthz dependency tree, owner: ops-monitoring-specialist, by 2026-05-25" is.

**Specifically NOT acceptable:**

- Acknowledge >15 min after detection
- Scope without negative space (what's NOT broken)
- Mitigation steps without timestamps
- Blame-the-individual post-mortems
- Action items without owners or deadlines
- "We'll get to it" closes (an incident with no follow-through invites recurrence)

---

## 3. Failure modes (what degraded output looks like)

| Mode | Symptom | How to catch |
|---|---|---|
| **Late acknowledge** | Incident timestamp - acknowledge timestamp > 15 min | First section header must compute the delta |
| **Unbounded scope** | "Things are broken" without listing what isn't | Scope section must have BOTH "affected" and "unaffected" subsections |
| **Untimestamped mitigation** | Steps listed in order but no times | Each mitigation step needs HH:MM prefix |
| **Blame attribution** | Post-mortem reads "Bumba should have caught this" | Root cause sentence must reference process/system/contract, not actor |
| **Orphan action items** | "Improve X" without owner or date | Action item table must require owner column + by-date column |
| **No trigger-condition update** | Same class of incident recurs because nothing surfaced the trigger | Section 5 must list specific signals that should fire next time |

---

## 4. Recent specialist invocations

> Operator-fill table populated post-invocation. Each incident response gets a row; reference the incident doc.

| Date | Incident | Severity | Acknowledge delta | Action items still open | Notes |
|---|---|---|---|---|---|
| YYYY-MM-DD | _name_ | _SEV1-4_ | _X min_ | _N_ | _what worked, what to do better_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has handled ≥3 real incidents. Verdict slot:

- [ ] Healthy — fast acknowledge, bounded scope, timestamped mitigation, actionable post-mortems
- [ ] Degraded — incidents handled but acknowledge slow OR post-mortems thin OR action items orphaned
- [ ] Stale — running but operator stopped reading post-mortems

Date recorded: _____________
