<!-- status: current — authored 2026-05-18 (#2134 / Sprint 5s.02) -->

# Output Quality Bar — `strategy-product-metrics-analyst`

**Specialist:** strategy-product-metrics-analyst
**Paired workflow:** `strategy.weekly_pulse` (#2187, Sprint 5s.06)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A metrics report saved under `docs/strategy/metrics/<date>-<period>-pulse.md`, plus a Discord summary on completion.

The report compares period-over-period (week-over-week by default) metric changes and surfaces what changed, why it changed (hypothesis), and what action the change implies.

### Required output sections

1. **Period scope** — comparison window (this week vs last week, this month vs last month)
2. **What changed** — per metric: current value, prior value, delta, statistical-noise vs signal label
3. **Why-hypothesis per significant change** — what theory explains the delta; ranked by confidence
4. **Action implication** — for each signal-level change: what should the operator/team do (or not do) about it
5. **What didn't change but maybe should** — metrics holding flat where movement was expected

---

## 2. The bar (what's acceptable)

**A metrics report is acceptable when:**

- **Noise vs signal labeled.** Random week-over-week variance is noise. Labeled deltas separate "this is real" from "this is variance".
- **Hypothesis per signal change.** Every signal-level delta has at least one why-hypothesis; multiple alternatives ranked.
- **Action implication explicit.** Not "engagement dropped 8%" — "engagement dropped 8% (signal); hypothesis: changelog email got blocked; action: verify email deliverability".
- **Flat-where-expected-movement flagged.** Sometimes the absence of change is the signal — call it out.
- **Comparison window declared.** Period-over-period needs an explicit period definition.

**Specifically NOT acceptable:**

- Deltas without noise/signal labels
- "Engagement dropped 8%" with no hypothesis
- Hypotheses without action implications
- Reports that list movement without flagging flat-where-expected
- Comparison window inconsistent or unstated

---

## 3. Failure modes

| Mode | Symptom | How to catch |
|---|---|---|
| **All-noise-reported** | 30 metric deltas listed, all flagged as movement worth noting | Healthy: most deltas are noise; few are signal. Inflation = report fatigue. |
| **Hypothesis absent** | Signal change reported without why-theory | Each signal-level delta needs ≥1 hypothesis |
| **Action-less hypothesis** | "Engagement dropped, possibly because of X" with no recommended action | Hypotheses chain to action implications |
| **Flat-blindness** | Report only lists what changed; misses meaningful non-changes | Section 5 required |
| **Window drift** | This week vs "last few weeks" — inconsistent comparison | Period definition fixed per report; cross-window comparisons explicit |
| **Statistical sloppiness** | 5% delta on N=10 sample flagged as "significant" | Sample-size + variance considered in noise/signal labeling |

---

## 4. Recent specialist invocations

| Date | Period | Signal deltas / noise deltas | Actions implied | Notes |
|---|---|---|---|---|
| YYYY-MM-DD | _window_ | _S / N_ | _N actions_ | _what shipped, what was missed_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has shipped ≥3 real pulse reports.

- [ ] Healthy — noise/signal calibrated, hypotheses tested, actions implied, flat-where-expected flagged
- [ ] Degraded — reports ship but noise/signal calibration off OR actions thin
- [ ] Stale — operator stopped acting on metrics reports (skimming, not reading)

Date recorded: _____________
