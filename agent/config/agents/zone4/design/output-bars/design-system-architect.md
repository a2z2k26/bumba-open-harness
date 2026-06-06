<!-- status: current — authored 2026-05-18 (#2131 / Sprint 5d.02) -->

# Output Quality Bar — `design-system-architect`

**Specialist:** design-system-architect
**Paired workflow:** `design.design_system_audit` (#2169, Sprint 5d.03), `design.component_spec_to_implementation` (#2171, Sprint 5d.05)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A design-system artifact: token specification (color/type/spacing/shadow tokens), component specification (props/variants/states/composition rules), or system-level audit report. Saved under `docs/design/system/<date>-<artifact>.md` with Figma source references.

### Required output sections

1. **Artifact description** — what's being specified or audited, what surface it affects, which framework(s) consume it
2. **Token / component definition** — explicit names, values, types; for components: props with types, variants enumerated, composition rules stated
3. **Consumer impact** — which existing components / surfaces this affects; migration path for any breaking change
4. **Code Connect / handoff binding** — how this maps to the target framework's primitives; binding declared
5. **Audit trail (for audit artifacts)** — inconsistencies surfaced, severity-bucketed, with remediation suggestions

---

## 2. The bar (what's acceptable)

**A design-system artifact is acceptable when:**

- **Names are stable.** Token names follow the existing convention (no surprise renames mid-stream). Component names match the system's naming pattern.
- **Composition rules explicit.** "This component can contain X, Y, Z; cannot contain W; nests inside parent set {A, B}." No mystery composition.
- **Breaking changes have migration.** Any rename/removal/signature-change ships with a migration path naming every affected consumer.
- **Code Connect binding present.** For frameworks the system targets, the Figma → code binding is declared so engineering-frontend-developer can implement without re-divining intent.
- **Audit findings are severity-bucketed.** Inconsistencies are critical (system-breaking) / high (drift accumulating) / medium (cleanup opportunity) / low (cosmetic).
- **Backward compatibility considered.** New tokens / components are additive when possible; deprecations have grace periods.

**Specifically NOT acceptable:**

- New tokens introduced without rationale or naming convention compliance
- Component composition rules implicit ("you'll figure it out")
- Breaking changes without migration path
- Code Connect binding skipped because "the dev can figure it out"
- Audit findings without severity
- Silent deprecation of existing tokens

---

## 3. Failure modes (what degraded output looks like)

| Mode | Symptom | How to catch |
|---|---|---|
| **Naming inconsistency** | New token uses different convention than existing ones | Cross-check against the system's existing naming rules in `design-create-design-system-rules` output |
| **Composition silence** | Component spec doesn't say what can/can't be nested | Section 2 must include composition rules |
| **Breaking change without migration** | Existing component renamed; consumers break on next pull | Section 3 must enumerate affected consumers + migration |
| **Code Connect absent** | Component intended for React/Vue handoff has no binding | Section 4 must declare binding or explicit "not yet bound, tracked at #NNN" |
| **Audit no-severity** | Findings listed flat; operator can't tell what's urgent | Severity bucket required per finding |
| **Silent deprecation** | Old token removed without grace period or successor named | Deprecations get a release with `@deprecated` annotation + successor token reference |

---

## 4. Recent specialist invocations

> Operator-fill table populated post-invocation.

| Date | Artifact | New tokens / components | Breaking changes? | Notes |
|---|---|---|---|---|
| YYYY-MM-DD | _name_ | _N / M_ | _yes-migrated / no_ | _what shipped, what to watch_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has shipped ≥3 real system artifacts. Verdict slot:

- [ ] Healthy — names stable, composition explicit, migration paths complete
- [ ] Degraded — system additions clean but audit work or Code Connect bindings slip
- [ ] Stale — operator working around system architect with ad-hoc tokens/components

Date recorded: _____________
