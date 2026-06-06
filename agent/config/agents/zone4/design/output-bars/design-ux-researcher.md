<!-- status: current — authored 2026-05-18 (#2131 / Sprint 5d.02) -->

# Output Quality Bar — `design-ux-researcher`

**Specialist:** design-ux-researcher
**Paired workflow:** `design.user_journey_to_wireframes` (#2173, Sprint 5d.07)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A research artifact (interview synthesis, journey map, persona, problem framing, or recommendation canvas) saved under `docs/design/research/<date>-<artifact-type>-<target>.md`, plus a Discord summary on completion.

### Required output sections

1. **Research question** — what was investigated, who/what was the data source, sample size + recruitment criteria
2. **Methodology** — interviews / observation / synthesis / canvas / journey-map / etc., with explicit method choice rationale
3. **Findings** — themes with primary-evidence citations (quote / observation / data point) — not summary-of-summary
4. **Recommendations** — actionable, ranked by confidence; each recommendation cites which findings support it
5. **What this DOESN'T tell us** — explicit limits of the research; sample-size caveats; what would require further investigation

---

## 2. The bar (what's acceptable)

**A research artifact is acceptable when:**

- **Primary evidence cited.** Findings reference actual interview quotes, observation timestamps, or specific data points. Not "users said they want..." without a who/when.
- **Sample size + recruitment stated.** "5 interviews with current operators recruited via Discord" beats "user research showed..."
- **Methodology rationale present.** Why journey-map and not interview here? Why this canvas? The choice should be defensible.
- **Theme density honest.** Themes mentioned by 1 of 5 participants are flagged as such, not promoted to "users want X".
- **Recommendations are actionable + ranked.** Each recommendation can be acted on; high-confidence vs low-confidence is explicit.
- **Limits stated.** What sample size doesn't cover, what bias the methodology introduces, what would require follow-up research.

**Specifically NOT acceptable:**

- "Users want X" without citing which users, when, or what they actually said
- Single-participant themes promoted to general findings
- Recommendations without confidence ranking
- "Further research recommended" as the only limit (vague non-answer)
- Methodology unstated or "talked to some people"

---

## 3. Failure modes (what degraded output looks like)

| Mode | Symptom | How to catch |
|---|---|---|
| **Summary-of-summary** | Findings are second-hand summaries; no primary quotes/observations | Section 3 should contain primary evidence blocks |
| **Sample bait-and-switch** | "Research showed..." when N=1 or sample wasn't representative | Section 1 must declare sample size + recruitment criteria |
| **Theme inflation** | One participant's gripe promoted to "users want" | Each theme should declare participant frequency: "mentioned by 3 of 5 interviewees" |
| **Unactionable recs** | "Improve the experience" as a recommendation | Each recommendation must name what changes, where, who acts |
| **No confidence ranking** | 12 recommendations listed flat; operator can't tell which to prioritize | Recs must be ranked (high / medium / low confidence) |
| **No limits stated** | "Research recommends X" without acknowledging the sample / methodology limits | Section 5 must exist with concrete caveats |
| **Methodology silent** | Output doesn't say HOW the research was conducted | Section 2 must declare method + rationale |

---

## 4. Recent specialist invocations

> Operator-fill table populated post-invocation.

| Date | Target | Sample size | Themes (high-conf / low-conf) | Operator action |
|---|---|---|---|---|
| YYYY-MM-DD | _research target_ | _N_ | _H / L_ | _what was decided_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has shipped ≥3 real research artifacts. Verdict slot:

- [ ] Healthy — primary evidence cited, themes honest about frequency, recs actionable + ranked
- [ ] Degraded — research sound but theme density inflated OR limits hidden
- [ ] Stale — operator stopped acting on research recommendations

Date recorded: _____________
