<!-- status: current — authored 2026-05-18 (#2132 / Sprint 5q.02) -->

# Output Quality Bar — `qa-api-tester`

**Specialist:** qa-api-tester
**Paired workflow:** `qa.api_contract_test` (#2177, Sprint 5q.05)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A markdown API contract conformance report saved under `docs/qa/<date>-api-contract-<target>.md`, plus a Discord summary on completion.

The report validates an implementation (REST endpoint, MCP tool, websocket event) against its declared schema (OpenAPI, JSON Schema, Pydantic model, registry YAML).

### Required output sections

1. **Target description** — which endpoint/tool/event, which schema spec is the source of truth, what version/commit
2. **Schema coverage matrix** — per declared field: required-and-present / optional-and-handled / extra-undeclared-field
3. **Contract conformance findings** — per finding: severity + reproduction + remediation (fix the impl OR fix the schema)
4. **Drift inventory** — fields present in impl but missing from schema, fields in schema but never returned by impl
5. **Recommendation** — schema authoritative (impl needs fix) OR impl authoritative (schema needs update) per finding

---

## 2. The bar (what's acceptable)

**An API contract test is acceptable when:**

- Every field declared in the schema is checked against the implementation — required, optional, present, absent
- Drift is flagged in both directions: impl has fields the schema doesn't know about, AND schema declares fields the impl never returns
- Each drift finding has a directional recommendation: which side is authoritative (impl or schema), and what gets changed
- Edge cases probed: null handling, empty arrays, unicode, schema-max-length boundaries
- Auth-boundary fields (anything sensitive) explicitly checked for redaction conformance with declared schema

**Specifically NOT acceptable:**

- "Schema matches" without per-field evidence
- One-directional drift checking (only impl→schema, ignoring schema→impl)
- Findings without authority recommendation (which side wins?)
- Skipping edge cases because "the happy path works"
- Sensitive-field handling not explicitly checked

---

## 3. Failure modes (what degraded output looks like)

| Mode | Symptom | How to catch |
|---|---|---|
| **One-directional drift** | Report lists impl-extra fields, doesn't list schema-declared-but-impl-missing fields | Drift inventory must have both columns populated or have explicit "no schema-side drift" statement |
| **Happy-path-only** | All findings cover the documented payload; nulls, edge cases, boundary values absent | Edge cases section must show explicit probes (null / empty / boundary / unicode) |
| **No authority recommendation** | Drift listed; reader can't tell whether to fix the impl or update the schema | Each finding tagged with `[schema-authoritative]` or `[impl-authoritative]` + rationale |
| **Sensitive-field gloss** | API returns user data but field-level redaction conformance never validated | Sensitive fields enumerated in their own subsection |
| **Stale against current spec** | Report run against schema X.Y but X.Z is what main now declares | Header must include schema commit/version compared |
| **Tool surface ignored** | REST endpoints tested but MCP tools / websocket events skipped despite same conformance need | Scope section must declare which surfaces were in/out |

---

## 4. Recent specialist invocations

> Operator-fill table populated post-invocation. The `qa.api_contract_test` workflow (#2177) emits Discord summaries; record them here.

| Date | Target | Drift count (impl-extra / schema-orphan) | Verdict | Notes |
|---|---|---|---|---|
| YYYY-MM-DD | _endpoint / tool / event_ | _N / N_ | _conformant / partial / non-conformant_ | _which side won, what changed_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has been invoked ≥3 times against real targets. Verdict slot:

- [ ] Healthy — drift is caught both directions, authority recommendations are right
- [ ] Degraded — drift caught but authority calls are wrong (operator overrides frequently)
- [ ] Stale — running but operator has stopped trusting the recommendations

Date recorded: _____________
