<!-- status: current — authored 2026-05-18 (#2131 / Sprint 5d.02) -->

# Output Quality Bar — `design-chief`

**Specialist:** design-chief
**Paired workflow:** Orchestration across all design.* workflows (#2169-#2173)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A markdown design-orchestration artifact saved under `docs/design/<date>-<workflow>-<target>.md`, plus a Discord summary on completion. The chief consolidates specialist output into one operator-facing decision.

For each invocation, the chief routes to specialists per the workflow definition, collects their reports, and produces synthesis that names disagreements, surfaces the contrarian read, and offers a weighted recommendation.

### Required output sections

1. **Workflow framing** — which design workflow, what target, what specialists were invoked
2. **Specialist views** — one block per specialist invoked; verbatim summary of their output bar's deliverable
3. **Points of agreement / disagreement** — where the specialists converged + where they diverged
4. **Chief recommendation** — weighted view with rationale, naming which specialist's input weighed heaviest and why
5. **Operator action requested** — concrete next step (approve / iterate / escalate)

---

## 2. The bar (what's acceptable)

**A design-chief synthesis is acceptable when:**

- Every invoked specialist gets a labeled block (no silent absorption of one specialist's view into another's)
- Disagreements are named, not papered over. If ui-designer says one thing and visual-designer says another, the synthesis surfaces the conflict.
- The chief recommendation is weighted (this specialist's input mattered most here, because...) — not averaged
- Operator action is one of: approve, iterate (with specific revision direction), or escalate (with the open question)
- Cross-references the specialist's output bar deliverable so the operator can drill into source if needed

**Specifically NOT acceptable:**

- "Specialists agreed" without naming the agreement
- Hiding minority views to present clean consensus
- Recommendation without weighting rationale ("all good — ship it")
- Operator action that doesn't terminate ("considering next steps")

---

## 3. Failure modes (what degraded output looks like)

| Mode | Symptom | How to catch |
|---|---|---|
| **Consensus inflation** | Synthesis reads "all specialists agreed" when one was clearly skeptical | Verify against the underlying specialist reports |
| **Specialist absorption** | Visual-designer's distinctive view rephrased into UI-designer's words | Each specialist block should retain that specialist's voice + terminology |
| **Unweighted recommendation** | Chief recommendation reads like an average of inputs without naming which weighed more | "I weight X most because Y" must be explicit |
| **Open-ended close** | Operator action says "we'll see what happens" | Final section must be one of approve/iterate/escalate |
| **Bridge-bypass** | Chief tries to operate Bumba Design Bridge directly instead of consuming bridge output | Per Sitting 3: bridge stays operator-paired; chief consumes bridge artifacts, doesn't trigger them |

---

## 4. Recent specialist invocations

> Operator-fill table populated post-invocation. Each design.* workflow completion gets a row.

| Date | Workflow | Specialists invoked | Synthesis verdict | Operator action |
|---|---|---|---|---|
| YYYY-MM-DD | _workflow id_ | _list_ | _approve / iterate / escalate_ | _what was done_ |

---

## 5. Specialist performance verdict

> **PENDING** until chief has orchestrated ≥3 design workflows in production. Verdict slot:

- [ ] Healthy — disagreements surfaced, weighting rationales clear, operator actions terminate cleanly
- [ ] Degraded — synthesis reads clean but specialist views get blurred OR weighting is hidden
- [ ] Stale — operator stopped engaging with chief synthesis (going direct to specialists)

Date recorded: _____________
