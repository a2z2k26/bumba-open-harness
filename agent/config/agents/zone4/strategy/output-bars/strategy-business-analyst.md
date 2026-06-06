<!-- status: current — authored 2026-05-18 (#2134 / Sprint 5s.02) -->

# Output Quality Bar — `strategy-business-analyst`

**Specialist:** strategy-business-analyst
**Paired workflow:** `strategy.tam_sam_som_for_idea` (#2186, Sprint 5s.05)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A financial analysis artifact saved under `docs/strategy/financial/<date>-<topic>.md`, plus a Discord summary on completion.

Covers pricing model design, unit economics, scenario analysis, payback-period projection, or business-health diagnostics.

### Required output sections

1. **Analysis scope** — what's being modeled, what decision the analysis supports
2. **Assumptions** — every assumption stated, sourced where possible, categorized (load-bearing / context / placeholder)
3. **Calculations** — math shown, not just outputs; intermediate values named
4. **Sensitivity ranges** — best-case / base-case / worst-case per output; which assumptions drive sensitivity most
5. **Decision relevance** — how this analysis answers the question that prompted it; what would change the recommendation

---

## 2. The bar (what's acceptable)

**A financial analysis is acceptable when:**

- **Assumptions explicit.** Every input variable named + valued + sourced. Hidden assumptions = analysis fraud.
- **Math shown.** Reader can audit by re-running calculations. Not a number with a confident tone.
- **Sensitivity ranges per output.** Single-point estimates lie. Best / base / worst plus the assumption that drives the spread.
- **Load-bearing vs context.** Some assumptions matter (sensitivity-driving); others are context. The analysis flags which is which.
- **Decision relevance closes the loop.** "If we believe assumption X, then decision Y; if assumption X is wrong, then decision Z."

**Specifically NOT acceptable:**

- Numbers without assumptions stated
- Point estimates without ranges
- Math hidden ("our model shows...")
- Treating placeholder assumptions as load-bearing
- Analysis disconnected from the decision it should inform

---

## 3. Failure modes

| Mode | Symptom | How to catch |
|---|---|---|
| **Hidden assumptions** | Analysis presents conclusions; inputs unstated or buried | Section 2 must enumerate every assumption |
| **Math by assertion** | "Our payback is 14 months" without the calculation | Calculation section must show formula + intermediate values |
| **Point-estimate fraud** | Single number presented as truth ("revenue will be $4.2M") | Sensitivity ranges required per output |
| **All-assumptions-equal** | 12 assumptions listed flat; no signal which matter most | Load-bearing vs context categorization required |
| **Placeholder inflation** | Placeholder assumption ("assume 20% conversion") treated as load-bearing fact | Placeholders explicitly labeled, sensitivity tests on them |
| **No decision tie** | Analysis ships; decision-maker can't act on it | Section 5 must answer "what would change my decision?" |

---

## 4. Recent specialist invocations

| Date | Topic | Assumptions (load-bearing / context) | Sensitivity range tightness | Notes |
|---|---|---|---|---|
| YYYY-MM-DD | _topic_ | _L / C counts_ | _tight / wide_ | _what shipped_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has shipped ≥3 real analyses.

- [ ] Healthy — assumptions explicit, math auditable, sensitivity ranges, decision-tied
- [ ] Degraded — analyses ship but assumption density or sensitivity testing thins
- [ ] Stale — operator stopped acting on financial analyses (back to gut-call)

Date recorded: _____________
