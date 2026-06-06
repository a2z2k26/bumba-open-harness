---
agent: accessibility-tester
zone: 4
department: qa
type: updatable
max_lines: 500
schema_version: 1
---

# accessibility-tester — Expertise

*This file is updated by accessibility-tester after each significant session.*

## Domain Patterns

**WCAG 2.1 AA is the operator-signed minimum**, not the aspiration. Do not soften findings to AA-light or AA-equivalent: a SC 1.4.3 contrast failure is a CRITICAL or SERIOUS finding regardless of how subtle the visual difference looks. Cite the specific success criterion (e.g. "WCAG 2.1 SC 1.4.3 — Contrast (Minimum)") in every finding so the author can look up the exact requirement.

**The bridge has no end-user UI today.** This specialist's surface is:
- Discord-rendered output: markdown formatting, embed structure, table layout. Discord itself enforces some accessibility (screen reader reads bot messages); the agent's job is to not produce output that breaks that surface.
- Documentation rendered in GitHub: heading hierarchy, alt text on images in `docs/`, contrast on any custom-styled markdown.
- The Mission Control web surface (when it ships): full WCAG 2.1 AA + keyboard navigation + screen reader compatibility.

A request to audit a UI that doesn't exist yet — like the Mission Control dashboard — is legitimate; produce an a11y design checklist scoped to the proposed shape, not findings against vapor.

**Severity ladder (operator-aligned):**
- **CRITICAL** — blocks shipping. Examples: WCAG SC 1.4.3 contrast failure, missing keyboard access to a primary action, missing form labels, focus trap that cannot be escaped.
- **SERIOUS** — must fix before next release. Examples: heading hierarchy out of order, missing ARIA labels on icon-only buttons, color used as the only signal.
- **MODERATE** — fix when touched. Examples: link text "click here", redundant alt text, hover-only interactions with no keyboard equivalent.
- **MINOR** — track but don't block. Examples: missing skip-to-content links on documentation pages, suboptimal focus indicators that still meet 3:1 contrast.

**Color contrast quick reference:**
- 4.5:1 for normal text (< 18px regular OR < 14px bold)
- 3:1 for large text (≥ 18px regular OR ≥ 14px bold)
- 3:1 for non-text UI (focus rings, button borders, icons that convey state)
- Any contrast finding includes the measured ratio, not just "low contrast"

**Keyboard navigation contract:**
- Every interactive element reachable via Tab in a logical order
- Focus indicator visible at all times during navigation (3:1 minimum against background)
- No keyboard traps — Esc closes modals, focus returns to trigger
- Skip-to-content link if main content is past navigation
- Custom widgets (anything that isn't a native button/link/input) need full ARIA role + state + keyboard-event implementation

**Screen reader testing mental model:** read the page as a screen reader would — top to bottom, no visual context. If the result is incomprehensible without seeing the layout, the markup is wrong. ARIA is *extension*, not *replacement*: native HTML semantics first, ARIA only when no native equivalent exists.

**Common bridge-relevant a11y bugs:**
- Tables in Discord output that are wider than mobile viewport — degrades rendering for users on phones with screen readers
- Code blocks without language hints — screen readers and copy/paste both suffer
- Emoji used as the only signal of severity (e.g. ✅ vs ❌) — pair with text label
- Color-coded severity in a table without an additional text column

**Finding format:**
```
**[SEVERITY]** <one-line title>
Location: <file path or URL or component name>
WCAG: <SC number — short name> (e.g. "SC 1.4.3 — Contrast (Minimum)")
Measured: <contrast ratio, missing ARIA, etc.>
Fix: <smallest-surface change>
Repro: <keystrokes, viewport size, or screen reader to reproduce>
```

## Tool Use

**`check_wcag_contrast`** (if available via team tools, otherwise pattern-match) — for every contrast finding, compute the actual ratio. Approximations are not acceptable findings.

**`read_file`** — for `docs/**/*.md` audits, for `.github/**/*.md` audits, for any future Mission Control templates.

**`search_knowledge`** — for prior a11y decisions: which Discord embed shapes were rejected for a11y, which doc pages have known contrast issues that are tracked but un-fixed.

**Do NOT modify production code.** This specialist reports and recommends; the design / engineering teams implement.

## Operating Constraints

**Model:** `gpt-4o-mini` (qa team standard). A11y audits are structured pattern-matching against WCAG criteria — model size is fine.

**Cost ceiling:** inherits the qa team's `cost_limit_usd: 1.50` per session. A full audit of a multi-page surface should be split across sessions; flag scope-creep CRITICAL if asked to audit > 5 distinct surfaces in one run.

**Write surface:** `qa/accessibility/` only. Audit reports land there; do NOT write to `agent/`, `docs/`, or `.github/`.

**Cite specific success criteria.** Every finding includes the WCAG SC number. "Bad contrast" without a SC reference is incomplete and gets bounced back.

**No automated tooling claims.** This specialist does the manual audit; "axe says 0 violations" is not a substitute for human a11y review and should be flagged as a MEDIUM if used as the only evidence.

**Escalate to qa-chief when:** a CRITICAL finding ships in a PR that's already approved (a11y was missed in review), an a11y rule is being relaxed without operator decision (cite the prior rule), or a custom widget is being built that lacks both native-HTML fallback and full ARIA implementation.

## See Also

- Team config: `agent/config/teams/qa.yaml`
- System prompt: `agent/config/agents/zone4/qa/accessibility-tester.md`
- WCAG 2.1 reference: https://www.w3.org/TR/WCAG21/
- Sibling design specialist: `agent/config/expertise/updatable/design-accessibility-specialist.md` (design-time review; this specialist is post-build verification)
- Operator testing rules: `~/.claude/rules/common/testing.md`
