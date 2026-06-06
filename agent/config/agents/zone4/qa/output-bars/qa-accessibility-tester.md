<!-- status: current — authored 2026-05-18 (#2132 / Sprint 5q.02) -->

# Output Quality Bar — `qa-accessibility-tester`

**Specialist:** qa-accessibility-tester
**Paired workflow:** `qa.accessibility_audit` (#2175, Sprint 5q.03)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A markdown accessibility audit report saved under `docs/qa/<date>-accessibility-audit-<target>.md`, plus a Discord summary on completion (pass / pass-with-findings / fail + finding count).

The report covers a shipped artifact (UI component, page, design system, or full app surface) against WCAG 2.1 AA criteria plus Bumba-specific accessibility checks.

### Required output sections

1. **Target description** — what artifact was audited, what version/commit, what surfaces were in scope
2. **WCAG 2.1 AA findings** — per criterion: pass / fail / not-applicable + evidence
3. **Bumba-specific findings** — focus management, aria coverage on dynamic content, keyboard navigation completeness
4. **Severity-bucketed fix list** — critical (blocks ship), high (ship-with-fix-PR-open), medium (next-sprint), low (backlog)
5. **Re-audit recommendation** — re-run cadence + trigger conditions

---

## 2. The bar (what's acceptable)

**An accessibility audit is acceptable when:**

- Every WCAG 2.1 AA criterion is explicitly evaluated — pass, fail, or N/A with rationale. No silent skips.
- Every fail finding has reproduction steps and a concrete remediation suggestion (not just "fix this").
- Severity bucketing reflects user-impact, not implementer-cost. A focus trap is critical even if the fix is small.
- Bumba-specific checks beyond WCAG are run: dynamic-content aria-live regions, focus return after modal close, skip-link presence on long pages, keyboard-only completion of every interactive flow.

**Specifically NOT acceptable:**

- "Looks good" without evaluation against criteria
- Findings without severity bucket
- Severity buckets driven by fix difficulty rather than user impact
- Skipping criteria because "this doesn't apply" without a written rationale

---

## 3. Failure modes (what degraded output looks like)

| Mode | Symptom | How to catch |
|---|---|---|
| **Coverage gap** | Report lists 12 criteria checked when WCAG 2.1 AA has ~50; the missing 38 are silently skipped | Cross-reference report against the standard's full criterion list |
| **Severity inflation** | Every finding marked "critical" so nothing gets fixed | Look at fix-list distribution; healthy = pyramid (few critical, more high/medium) |
| **Vague remediation** | "Improve aria coverage" instead of "add aria-live=polite to the toast container at components/Toast.tsx:42" | Spot-check 3 random findings for actionable concreteness |
| **Browser-only audit** | Static evaluation of code; never opened the actual artifact in a screen reader or keyboard-only flow | Report should cite the screen reader used + keyboard-flow evidence |
| **Stale against current artifact** | Audit run against commit X but artifact has shipped commits since; report doesn't disclose | Header must include exact commit/version audited |

---

## 4. Recent specialist invocations

> Operator-fill table populated post-invocation. The `qa.accessibility_audit` workflow (#2175) emits a Discord summary; copy the relevant details here.

| Date | Target | Findings (C/H/M/L) | Verdict | Notes |
|---|---|---|---|---|
| YYYY-MM-DD | _artifact_ | _N/N/N/N_ | _pass / partial / fail_ | _what was caught, what was missed_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has been invoked ≥3 times in production. Verdict slot:

- [ ] Healthy — findings are specific, severity-bucketed correctly, remediations actionable
- [ ] Degraded — finds bugs but bucketing or specificity has slipped
- [ ] Stale — running but operator stopped engaging; bar needs re-set

Date recorded: _____________
