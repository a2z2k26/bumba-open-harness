<!-- status: current — authored 2026-05-18 (#2133 / Sprint 5o.02) -->

# Output Quality Bar — `ops-monitoring-specialist`

**Specialist:** ops-monitoring-specialist
**Paired workflow:** `ops.health_check_pass` (#2181, Sprint 5o.04)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A markdown health-check report saved under `docs/ops/<date>-health-check.md`, plus a Discord summary with overall verdict + flagged services.

The report wraps `/healthz` + per-service state-files (`data/service_state/<name>-state.json` per the #1806 schema) + halt-flag state into one operator-readable snapshot.

### Required output sections

1. **Overall verdict** — healthy / degraded / broken + one-line rationale
2. **Bridge daemon health** — `/healthz` response (raw), kernel-baseline status, uptime, halt-flag state
3. **Scheduled-service inventory** — per service: last_run / last_status / consecutive_failures / bucket (per Zone 2 audit convention)
4. **Flagged services** — services bucketed as degraded / broken / stale, ordered by severity
5. **Recommended next action** — what should the operator do today based on this snapshot

---

## 2. The bar (what's acceptable)

**A health-check report is acceptable when:**

- **Right metric per surface.** Bridge daemon = `/healthz` + kernel baseline. Service = state-file fields per #1806 schema. Halt flag = single boolean. Don't conflate surfaces.
- **Alert ergonomics: signal > noise.** Section 4 (flagged services) only lists services that need operator action. Healthy services are summarized in section 3, not flagged.
- **Verdict reflects reality.** "Healthy" overall verdict requires zero broken services + zero halt-flag + green `/healthz`. Otherwise downgrade to "degraded" or "broken" honestly.
- **Recommended action is concrete.** Not "investigate the briefing service" but "check `data/service_state/briefing-state.json:last_error` and restart the launchctl bootstrap if needed".
- **Stale services explicitly named.** A service with `total_skipped > 0.5 * total_runs` is stale; this is its own bucket per Zone 2 doctrine, not silently lumped into "degraded".

**Specifically NOT acceptable:**

- "All good" verdict when any service is broken (verdict inflation)
- Listing every service status when only flagged ones need action (alert noise)
- Wrong metric per surface (e.g. `/healthz` text describing a scheduled service state)
- Recommended action that says "look into it"

---

## 3. Failure modes (what degraded output looks like)

| Mode | Symptom | How to catch |
|---|---|---|
| **Verdict inflation** | Overall "healthy" with broken services in the inventory | Verdict must match worst-bucket in section 3 |
| **Alert flood** | Section 4 lists 15 services when only 2 actually need operator action | Flagged section restricted to broken + degraded buckets only |
| **Wrong-metric-per-surface** | Daemon health described via service-state fields, or vice versa | Section structure enforces surface separation |
| **Stale-stale conflation** | Service-stale (no-op for a reason) lumped with broken | Stale must be its own bucket explicitly named |
| **Vague action** | "Check the logs" without naming the log file or what to look for | Recommended-action must cite specific file + signal |
| **Halt-flag glossed** | Halt is set but report still lists overall verdict as healthy | Halt-flag state must override verdict to "degraded" minimum |

---

## 4. Recent specialist invocations

> Operator-fill table populated post-invocation. The `ops.health_check_pass` workflow (#2181) emits Discord summaries; record them here.

| Date | Verdict | Flagged services | Action taken? | Notes |
|---|---|---|---|---|
| YYYY-MM-DD | _healthy/degraded/broken_ | _list_ | _yes / deferred_ | _what caught, what was missed_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has run ≥3 health-check passes. Verdict slot:

- [ ] Healthy — verdict matches reality, alert ergonomics tight, recommended actions concrete
- [ ] Degraded — verdict mostly right but alert noise OR vague actions reduce trust
- [ ] Stale — running but operator stopped reading flagged-services section

Date recorded: _____________
