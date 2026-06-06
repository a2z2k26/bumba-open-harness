<!-- status: current — authored 2026-05-18 (#2131 / Sprint 5d.02) -->

# Output Quality Bar — `design-ui-designer`

**Specialist:** design-ui-designer
**Paired workflow:** `design.design_system_audit` (#2169, Sprint 5d.03), `design.component_spec_to_implementation` (#2171, Sprint 5d.05)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A Figma artifact (file, page, component, or variant set) plus a markdown spec saved under `docs/design/<date>-ui-<target>.md` linking to the Figma source.

The Figma artifact follows component-spec discipline: every reusable element is a component with declared variants, auto-layout, and design-system token references — not a free-floating frame.

### Required output sections (in the spec doc)

1. **Target description** — what was designed, what surface it lands on, which platform/breakpoints
2. **Component inventory** — per component: name, variants, props, token references
3. **Auto-layout discipline** — every container uses auto-layout (or has explicit rationale why not); padding/gap/sizing values cite design-system tokens
4. **Design-system fidelity** — every color/type/spacing/shadow references a token (not a raw value)
5. **Handoff readiness** — Code Connect bindings present where applicable; Figma file shared with appropriate access

---

## 2. The bar (what's acceptable)

**A UI design artifact is acceptable when:**

- **Component-based, not frame-based.** Every reusable element is a component with variants — even if there's only one instance today. Future reuse needs the structure.
- **Auto-layout everywhere.** Containers use auto-layout with token-referenced padding/gap. Free-positioned frames are an exception that needs explicit rationale.
- **Token-referenced, not hardcoded.** Every color/typography/spacing/shadow value comes from the design system tokens. `#FF5733` in a fill = bug; `color/brand/primary` = correct.
- **Variants over duplicates.** A button with hover, disabled, loading states is ONE component with 3 variants — not 3 separate components.
- **Code-handoff ready.** Code Connect bindings present on components that ship to a registered framework; Figma file permissions allow operator + engineering-frontend-developer access.

**Specifically NOT acceptable:**

- Loose frames pretending to be components
- Hardcoded color/type values that bypass tokens
- Duplicate variants when a single component + variants would suffice
- Auto-layout skipped because "this one's special" without rationale
- Figma file in operator's private space; engineering can't access for implementation

---

## 3. Failure modes (what degraded output looks like)

| Mode | Symptom | How to catch |
|---|---|---|
| **Frame masquerade** | Reusable element is a frame, not a component; future reuse requires duplication | Inspect the layers panel — components have a diamond icon |
| **Token drift** | Color value `#FF5733` inline instead of `color/brand/primary` | Audit the fill/text/stroke styles for raw values vs token references |
| **Auto-layout skipped** | Free-positioned children inside a container that should resize | Toggle auto-layout off on the container; if children jump, the layout was fake |
| **Variant explosion** | 12 separate components named `Button-Default`, `Button-Hover`, `Button-Disabled`, `Button-Loading-Primary`, etc. | One component, four variants is the target shape |
| **No Code Connect** | Component intended for React/Vue/Svelte handoff has no Code Connect binding | Code Connect tab on the component in Figma should show a binding |
| **Permission silo** | File shared "just with the operator" so engineering can't pull | File access verified at PR-merge time |

---

## 4. Recent specialist invocations

> Operator-fill table populated post-invocation.

| Date | Target | Components / variants | Token-clean? | Notes |
|---|---|---|---|---|
| YYYY-MM-DD | _surface_ | _N comp / M variants_ | _yes / partial_ | _what shipped, what to polish_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has shipped ≥3 real artifacts. Verdict slot:

- [ ] Healthy — component-based, token-clean, handoff-ready every time
- [ ] Degraded — components mostly clean but auto-layout or tokens slip occasionally
- [ ] Stale — operator stopped engaging with ui-designer output (going direct to engineering-frontend-developer)

Date recorded: _____________
