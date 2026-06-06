<!-- status: current — authored 2026-05-18 (#2134 / Sprint 5s.02) -->

# Output Quality Bar — `strategy-competitive-intelligence-analyst`

**Specialist:** strategy-competitive-intelligence-analyst
**Paired workflow:** `strategy.competitive_landscape` (#2185, Sprint 5s.04)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A competitive landscape report saved under `docs/strategy/competitive/<date>-<topic>.md`, plus a Discord summary on completion.

### Required output sections

1. **Landscape scope** — what market / use-case, what we're competing on, what we're explicitly NOT competing on
2. **Named competitors** — actual product names, not categories; per competitor: positioning, target customer, pricing tier, distinguishing capability
3. **Differentiation matrix** — feature/capability axes × competitors; our position explicit + defensible
4. **Threat assessment** — per competitor: threat-level (high/medium/low) + rationale + early-warning signals
5. **Counter-moves available** — what we could do if a competitor accelerates; ranked by feasibility

---

## 2. The bar (what's acceptable)

**A competitive landscape is acceptable when:**

- **Named competitors, not categories.** "Vercel V0" beats "AI coding assistants". Categories are useless for decision-making.
- **Differentiation framing explicit.** Not "we're better" — what specific dimension we're better on, where we're worse, where we're equivalent.
- **Threat assessment per competitor.** Each competitor gets a rating + rationale + early-warning signal.
- **Counter-moves listed.** What we could do if threat materializes — feasibility-ranked.
- **Our weaknesses honest.** Dimensions where competitors are stronger are listed; pretending otherwise hides risk.

**Specifically NOT acceptable:**

- "We compete with AI tools" without naming products
- "We're better because we're focused on quality" — meaningless without specifics
- Threat-blind (every competitor "low threat")
- No counter-moves (operator surprised when threat lands)
- Weakness-blind (only listing our strengths)

---

## 3. Failure modes

| Mode | Symptom | How to catch |
|---|---|---|
| **Category competition** | "Other AI tools" listed instead of product names | Section 2 must enumerate actual product names |
| **Vague differentiation** | "Better UX" without naming the dimension | Differentiation matrix must use specific feature/capability columns |
| **Threat inflation** | Every competitor "high threat" → operator can't prioritize | Healthy distribution skews to medium; high/low both rare with rationale |
| **Threat deflation** | Everyone "low threat" — reads like complacency | Each "low" requires rationale (why not high?) |
| **No counter-moves** | Threats listed; what-to-do absent | Section 5 required |
| **Cherry-picked dimensions** | Differentiation matrix only uses axes where we win | Matrix must include axes where we lose + tie |

---

## 4. Recent specialist invocations

| Date | Market | Competitors named | Threats (H/M/L) | Counter-moves listed? | Notes |
|---|---|---|---|---|---|
| YYYY-MM-DD | _scope_ | _N_ | _H/M/L counts_ | _yes / partial_ | _what shipped_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has shipped ≥3 real landscapes.

- [ ] Healthy — named competitors, honest differentiation matrix, calibrated threat assessment, counter-moves ranked
- [ ] Degraded — landscapes ship but threat calibration drifts or counter-moves absent
- [ ] Stale — operator stopped trusting competitive reads (back to first-principles)

Date recorded: _____________
