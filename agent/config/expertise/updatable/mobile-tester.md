---
agent: mobile-tester
zone: 4
department: qa
type: updatable
max_lines: 500
schema_version: 1
---

# mobile-tester — Expertise

*This file is updated by mobile-tester after each significant session.*

## Domain Patterns

**The bridge has no mobile UI today.** This specialist's surface is:
- Discord on iOS / Android — the operator's primary mobile interaction with the agent. Output that renders cleanly on desktop Discord but breaks on mobile Discord (table overflow, code-block scroll, embed truncation) is a real bug.
- The Mission Control web surface (when it ships) — full mobile-responsive testing.
- Future operator-facing apps — the bumba-desktop project flagged in operator memory has companion mobile considerations not yet surfaced as a sprint.

A request to audit a mobile UI that does not exist yet is legitimate; produce a mobile-readiness checklist scoped to the proposed shape, not findings against vapor.

**Standard viewports (operator-sourced):**
- 320px — smallest iPhone SE; if it works here, larger sizes follow
- 375px — modern iPhone (X/11/12/13/14 base width)
- 390px — iPhone 14 Pro
- 414px — iPhone Plus / Max widths
- 768px — iPad portrait
- 1024px — iPad landscape

Test the smallest viewport first. A layout that breaks at 320px but works at 375px is still a CRITICAL bug — iPhone SE is a real device the operator may use.

**Touch target standard:** 44×44pt minimum (Apple HIG) / 48×48dp (Material). Tap targets that visually look like buttons but are smaller than the minimum are a SERIOUS finding even if the click area extends past the visible bounds — operators don't know the invisible hitbox exists.

**Severity ladder (mobile-specific):**
- **CRITICAL** — iPhone SE renders horizontally scrolled, primary action unreachable on iOS Safari, taps register on the wrong element, content auto-zoom on input focus (iOS bug from missing viewport meta tag).
- **MAJOR** — Touch target < 44×44pt for primary action, swipe gesture conflicts with browser back, font < 16px causes iOS zoom on focus, hover-only state unreachable.
- **MINOR** — Suboptimal use of safe-area inset, missing landscape optimization, animation that bypasses `prefers-reduced-motion`.

**Discord-mobile-specific patterns this specialist guards:**
- Tables wider than ~30 chars wrap badly on mobile Discord — prefer pipe-separated lists or vertical key/value pairs
- Code blocks with long lines force horizontal scroll on mobile — break into smaller blocks or use ASCII art alternatives
- Embed images that don't have explicit width — Discord auto-fits desktop but can crop weirdly on mobile
- Multi-line messages that exceed Discord's mobile expand-on-tap threshold (~2000 chars) get truncated; budget output accordingly per `agent/CLAUDE.md` § "[discord_output_budget]"

**Platform contract (when a real mobile UI ships):**
- iOS Safari + Android Chrome are the two minimum platforms
- Test on actual devices when possible; simulators miss font rendering, touch precision, and PWA install flow
- iOS-specific: viewport meta `width=device-width, initial-scale=1.0`, no `maximum-scale` < 1.0 (a11y violation), respect safe-area insets via `env(safe-area-inset-*)`
- Android-specific: respect Android system back button (don't trap navigation), test both gesture and 3-button nav modes

**Performance budgets (mobile-specific):**
- Time to interactive < 3.5s on 3G simulated network
- JavaScript bundle < 200KB gzipped for initial render
- Web fonts deferred or subsetted; no layout shift from font swap (use `font-display: swap` carefully)
- Images responsive (srcset / sizes) — no full-resolution hero images on mobile

**Finding format:**
```
**[SEVERITY]** <one-line title>
Platform: iOS Safari | Android Chrome | Both
Viewport: <width>px (or device name)
Repro: <step-by-step on the device>
Fix: <smallest-surface change; cite the touch-target rule, viewport meta requirement, etc.>
```

## Tool Use

**`read_file`** — for HTML/CSS/JS sources, viewport meta declarations, touch-handler implementations.

**`search_knowledge`** — for prior mobile decisions: which Discord output shape was rejected for mobile rendering, which font was switched out for mobile-readability reasons.

**Manual device testing** — when possible. The operator owns iPhone + iPad; coordinate device-time access through qa-chief if a real-device test is needed. Simulator findings are valid but flag as "simulator-only" and recommend real-device verification before merge for CRITICAL issues.

**Do NOT modify production code.** This specialist reports and recommends; design / engineering implements.

## Operating Constraints

**Model:** `gpt-4o-mini` (qa team standard). Mobile audits are structured pattern-matching against viewport math + platform conventions — model size is fine.

**Cost ceiling:** inherits the qa team's `cost_limit_usd: 1.50` per session.

**Write surface:** `qa/mobile/` and `tests/mobile/` only.

**Document exact viewport dimensions for every finding.** "Looks bad on mobile" is not a finding; "renders horizontally scrolled at 320px iPhone SE simulated viewport" is.

**Touch target measurements include the actual visible bounds**, not the invisible hitbox. A 32×32 button with a 44×44 invisible hitbox still fails the visible-affordance contract — operators tap what they see.

**Escalate to qa-chief when:** a mobile-CRITICAL bug is being deferred to a future sprint without operator sign-off, a viewport-meta tag is being removed (auto-zoom is an a11y violation), or a touch-target rule is being relaxed below 44×44pt.

## See Also

- Team config: `agent/config/teams/qa.yaml`
- System prompt: `agent/config/agents/zone4/qa/mobile-tester.md`
- Discord output budget: `agent/CLAUDE.md` § "[discord_output_budget]" (D7.10 #1422)
- Sibling: `agent/config/expertise/updatable/accessibility-tester.md` (a11y findings often surface as mobile findings on small viewports)
- Apple HIG touch targets: https://developer.apple.com/design/human-interface-guidelines/inputs/touch
- Material touch targets: https://m3.material.io/foundations/accessible-design/accessibility-basics
