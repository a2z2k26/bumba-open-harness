<!-- status: current — authored 2026-05-18 (#2132 / Sprint 5q.02) -->

# Output Quality Bar — `qa-security-auditor`

**Specialist:** qa-security-auditor
**Paired workflow:** `qa.security_review_pre_release` (#2176, Sprint 5q.04)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A markdown security review report saved under `docs/qa/<date>-security-review-<target>.md`, plus a Discord summary with **explicit release-gate verdict** (pass / pass-with-findings / **block**).

The report covers a release-candidate artifact (PR ready to merge, branch ready to deploy, or shipped artifact under post-mortem) against OWASP Top 10 + Bumba-specific security checks.

### Required output sections

1. **Target description** — what artifact, what commit/branch, deploy-readiness context
2. **OWASP Top 10 coverage** — per category: relevant + finding / relevant + clean / not-applicable + rationale
3. **Bumba-specific checks** — secrets in code, halt-flag respect, auth surface, kernel integrity, MCP scope
4. **Finding inventory** — per finding: severity (critical / high / medium / low) + CWE if applicable + reproduction + remediation
5. **Release-gate verdict** — pass / pass-with-findings / **block** + rationale

---

## 2. The bar (what's acceptable)

**A security review is acceptable when:**

- Every OWASP Top 10 category is explicitly evaluated against the artifact
- Bumba-specific checks run: `grep -rE "(api[_-]?key|password|secret|token|bearer)\s*=\s*['\"]"` against the diff, halt-flag respect verified at all `claude_runner.invoke` callers, auth/permission boundaries checked at every new endpoint
- **Critical findings block the release.** This is the load-bearing rule — security-auditor's verdict is operator-merge-gating.
- Every finding ties to a CWE where applicable (not required for Bumba-specific findings outside the catalog)
- Remediations cite specific files + lines, not "rotate the credential" abstractions

**Specifically NOT acceptable:**

- "LGTM" without category coverage
- Critical findings rendered as "high" to avoid blocking
- Findings without remediation
- Skipping OWASP categories without rationale
- Verdict that doesn't match finding severity (3 criticals + "pass" verdict = corruption)

---

## 3. Failure modes (what degraded output looks like)

| Mode | Symptom | How to catch |
|---|---|---|
| **Verdict-finding mismatch** | Report lists 2 critical findings but verdict is "pass-with-findings" | Verdict must escalate to BLOCK when any critical exists. Programmatic check. |
| **OWASP coverage gap** | Top 10 has 10 categories; report addresses 6, the other 4 silently absent | Every category appears in the report — N/A is acceptable with rationale, silent skip is not |
| **Secret-scan false negative** | Grep wasn't run, or was run with too-narrow regex; new secret slipped past | Verify the exact grep command in the report; cross-check against `.secrets.baseline` if it exists |
| **Bumba-specific blind spot** | OWASP covered well but halt-respect / kernel integrity / MCP scope check skipped | Bumba-specific section must list every check + result |
| **Auth boundary glossing** | "Looks fine" on a new endpoint without naming the auth middleware that gates it | Each new endpoint should list its auth gate by module:line reference |
| **Severity inflation/deflation** | All findings "medium" — too easy to wave through OR all "critical" — same effect via fatigue | Healthy distribution skews to low/medium with rare high/critical |

---

## 4. Recent specialist invocations

> Operator-fill table populated post-invocation. The `qa.security_review_pre_release` workflow (#2176) emits Discord summaries with release-gate verdicts; record them here.

| Date | Target (PR/branch) | Findings (C/H/M/L) | Verdict | Operator agreed? |
|---|---|---|---|---|
| YYYY-MM-DD | _PR #NNNN_ | _N/N/N/N_ | _pass / pass-with-findings / BLOCK_ | _yes / overrode / partial_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has been invoked ≥3 times on real release candidates. Verdict slot:

- [ ] Healthy — findings are real, severity calibrated, verdicts match operator's read
- [ ] Degraded — finds bugs but severity calibration is off (false positives or false negatives)
- [ ] Stale — running but operator stopped trusting verdicts; bar needs re-calibration

Date recorded: _____________
