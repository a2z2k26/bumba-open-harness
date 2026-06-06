<!-- status: current — authored 2026-05-18 (#2132 / Sprint 5q.02) -->

# Output Quality Bar — `qa-performance-tester`

**Specialist:** qa-performance-tester
**Paired workflow:** `qa.performance_baseline` (#2178, Sprint 5q.06)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A markdown performance baseline report saved under `docs/qa/<date>-performance-baseline-<target>.md`, plus a Discord summary on completion.

The report establishes a measured baseline for a new endpoint, feature, or workflow so future regressions become detectable. Subsequent runs against the same target produce delta reports.

### Required output sections

1. **Target description** — what's being measured, what version/commit, what test environment
2. **Baseline measurements** — per measured dimension: p50 / p95 / p99 / max + sample size + measurement window
3. **Regression thresholds** — for each measured dimension, the operator-tunable threshold beyond which a future run triggers a regression alert
4. **Reproducibility notes** — exact load profile, dataset/fixture used, environment specifics that could shift results
5. **Recommended re-baseline cadence** — when this baseline should be refreshed (load profile change, infrastructure change, major feature touching this surface)

---

## 2. The bar (what's acceptable)

**A performance baseline is acceptable when:**

- Every measured dimension reports p50, p95, p99 — not just averages. Tail latency is the load-bearing signal.
- Sample size is stated and large enough to be meaningful (≥100 runs for endpoint-level, ≥10 for end-to-end workflow)
- Regression thresholds are concrete numbers tied to measured baseline (e.g. "p99 > 2x baseline = regression alert"), not abstract policy
- Test environment + load profile are reproducible from the doc alone
- The doc names what NOT to compare across (e.g. "don't compare against pre-D6-bis baselines, runtime layout changed")

**Specifically NOT acceptable:**

- Average-only reporting (p99 is what hurts users)
- Single-run baselines (variance unknown)
- Thresholds that say "looks slow" without a number
- "Run this on the mini" without naming the load profile

---

## 3. Failure modes (what degraded output looks like)

| Mode | Symptom | How to catch |
|---|---|---|
| **Average-only metrics** | Report shows mean latency; no tail measurements | Every dimension must have p50/p95/p99 trio |
| **One-run baseline** | Sample size = 1; variance unmeasurable | Sample size column required; <10 for end-to-end OR <100 for endpoint should fail review |
| **Threshold without rationale** | "Alert if p99 > 500ms" — why 500? | Each threshold needs a multiplier-of-baseline rationale or a hard-product-SLA citation |
| **Environment drift** | Baseline run on operator's laptop; future regression measured on mini | Environment section must lock the where + how |
| **Stale baseline still in use** | Code changed, baseline didn't get refreshed, regressions are silent | Re-baseline cadence section must specify triggers |
| **Wrong load profile** | Measured under 1 req/s; production runs at 100 req/s | Load profile section must document target production rate |

---

## 4. Recent specialist invocations

> Operator-fill table populated post-invocation. The `qa.performance_baseline` workflow (#2178) emits Discord summaries; record them here.

| Date | Target | p50 / p95 / p99 | Baseline locked? | Notes |
|---|---|---|---|---|
| YYYY-MM-DD | _endpoint or workflow_ | _Xms / Yms / Zms_ | _yes / pending_ | _what shifted, what's locked_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has been invoked ≥3 times against real targets. Verdict slot:

- [ ] Healthy — baselines are reproducible, thresholds catch real regressions, environment locks hold
- [ ] Degraded — baselines drift between runs or thresholds miss real regressions
- [ ] Stale — running but baselines no longer reflect production reality

Date recorded: _____________
