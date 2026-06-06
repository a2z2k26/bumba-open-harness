<!-- status: current — authored 2026-05-18 (#2134 / Sprint 5s.02) -->

# Output Quality Bar — `strategy-market-researcher`

**Specialist:** strategy-market-researcher
**Paired workflow:** `strategy.tam_sam_som_for_idea` (#2186, Sprint 5s.05) + `strategy.competitive_landscape` (#2185 supporting role)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A market report saved under `docs/strategy/market/<date>-<topic>.md`, plus a Discord summary on completion.

### Required output sections

1. **Market scope** — what market is being researched, segment definition, geography, time window
2. **Source citations** — every claim cites a source: primary research (interviews/surveys) vs secondary (reports/data) explicitly labeled
3. **Segment breakdown** — TAM / SAM / SOM (or equivalent) with calculation transparency, not just numbers
4. **Findings** — what the data says, ranked by confidence; speculative claims explicitly tagged
5. **What this report doesn't cover** — sample-size limits, geographic gaps, time-currency of sources

---

## 2. The bar (what's acceptable)

**A market report is acceptable when:**

- **Sources cited per claim.** "TAM is $4.2B" carries a source. Aggregated estimates cite the inputs aggregated.
- **Primary vs secondary labeled.** Primary research (interviews, surveys conducted for this report) is distinguished from secondary (third-party reports, public data). Mixing them silently hides confidence variance.
- **Segment math transparent.** TAM/SAM/SOM = arithmetic shown, not just final numbers. Operator can audit assumptions.
- **Confidence-ranked findings.** "Strong evidence: X. Moderate evidence: Y. Speculative: Z." — not flat.
- **Limits stated.** What the report doesn't claim. Where the data is thin.

**Specifically NOT acceptable:**

- Numbers without sources ("TAM is around $4B")
- Primary/secondary blended ("research shows...")
- TAM/SAM/SOM as final numbers without math
- Findings ranked flat (operator can't tell what's confident)
- "Further research recommended" as the only limit

---

## 3. Failure modes

| Mode | Symptom | How to catch |
|---|---|---|
| **Sourceless numbers** | "Market is growing 23% YoY" without citation | Every quantitative claim needs a footnote |
| **Primary/secondary blur** | Report mixes a single interview with third-party reports as equivalent inputs | Section 2 must label every source by type |
| **Opaque sizing math** | TAM/SAM/SOM listed as numbers; calculation hidden | Sizing section must show formula + inputs |
| **Flat confidence** | 15 findings listed; operator can't tell which to act on | Section 4 explicitly tagged by confidence band |
| **No limits** | "Market opportunity is substantial" without acknowledging sample/methodology limits | Section 5 must enumerate gaps |
| **Time-currency silent** | Sources from 2023 used to claim 2026 conditions without flagging | Source citations must include date; report flags stale-source risk |

---

## 4. Recent specialist invocations

| Date | Topic | Sources (primary / secondary) | Sizing math shown? | Notes |
|---|---|---|---|---|
| YYYY-MM-DD | _market topic_ | _P / S counts_ | _yes / partial_ | _what shipped_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has shipped ≥3 real market reports.

- [ ] Healthy — sources cited per claim, primary/secondary distinguished, math transparent
- [ ] Degraded — reports ship but source citations or limits drift thin
- [ ] Stale — operator stopped trusting market reports (back to gut-call)

Date recorded: _____________
