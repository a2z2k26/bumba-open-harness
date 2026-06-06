<!-- status: current — authored 2026-05-18 (#2134 / Sprint 5s.02) -->

# Output Quality Bar — `strategy-user-analyst`

**Specialist:** strategy-user-analyst
**Paired workflow:** Cross-cutting (informs `strategy.prd_authoring` #2184 + `strategy.competitive_landscape` #2185)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A user-research-synthesis artifact saved under `docs/strategy/users/<date>-<topic>.md`, plus a Discord summary on completion.

Covers user-segment analysis, persona depth, journey-step instrumentation reads, NPS/sentiment synthesis, or behavioral cohort analysis.

### Required output sections

1. **Research scope** — what user-question, what data source(s), sample size, recruitment / collection criteria
2. **Themes** — each theme: statement, supporting evidence (quotes / observations / data), frequency / density
3. **Synthesis** — what the themes collectively suggest; ranked by confidence
4. **Recommendations** — actionable, ranked, addressed to the right downstream consumer (strategy-product-chief / design-ux-researcher / engineering)
5. **Sample limits** — what this synthesis can't claim; bias considerations; what would require further research

---

## 2. The bar (what's acceptable)

**A user analysis is acceptable when:**

- **Sample size + collection criteria stated.** "Synthesis from 5 operator interviews recruited via Discord" beats "users said".
- **Themes density-honest.** Theme mentioned by 1 of 5 = "minority view"; mentioned by 4 of 5 = "strong signal". Don't conflate.
- **Evidence primary, not secondary.** Quotes / observations / data points, not paraphrased summaries.
- **Recommendations addressed to downstream consumer.** Not just "act on this" — "strategy-product-chief: consider X for next PRD" or "engineering-frontend-developer: prioritize Y in component refactor".
- **Bias considerations explicit.** Sample-bias, recruitment-bias, interview-bias, self-selection-bias acknowledged where they could shift conclusions.

**Specifically NOT acceptable:**

- "Users want" without sample size or evidence
- Single-participant themes elevated to "users want"
- Paraphrase-summary instead of primary evidence
- Recommendations without downstream owner
- "Talked to some users" methodology

---

## 3. Failure modes

| Mode | Symptom | How to catch |
|---|---|---|
| **Sample handwave** | "Research shows users want X" — sample unknown | Section 1 must declare N + criteria |
| **Theme inflation** | One participant's gripe → general theme | Frequency / density required per theme |
| **Secondary evidence** | "Users feel confused" without a primary citation | Each theme cites primary evidence |
| **Orphan recommendations** | "Make it more intuitive" with no owner | Recommendations addressed to specific downstream agent |
| **Bias-blind** | Self-selected sample treated as representative | Section 5 must address selection / methodology biases |
| **Cross-source blur** | Interview data + analytics data treated as equivalent | Sources distinguished by type (qualitative interview, quantitative log, etc.) |

---

## 4. Recent specialist invocations

| Date | Topic | Sample size | Themes (strong / minority) | Recommendation owner | Notes |
|---|---|---|---|---|---|
| YYYY-MM-DD | _topic_ | _N_ | _S/M_ | _owner_ | _what shipped_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has shipped ≥3 real syntheses.

- [ ] Healthy — sample explicit, themes density-honest, primary evidence cited, recs owned, biases stated
- [ ] Degraded — syntheses ship but theme density drifts OR bias considerations thin
- [ ] Stale — operator stopped acting on user analyses

Date recorded: _____________
