# Dark Factory Pipeline

The factory pipeline picks up issues tagged `factory:accepted` and runs them
through a fixed sequence — implement → quality → validate → synthesize →
route — terminating at a draft PR. The pipeline never auto-merges; every PR
requires operator review before landing.

## Label State Machine

| Label | Color | Description |
|---|---|---|
| `factory:opt-in` | `#0e8a16` | Gate marker — controls whether the factory touches an issue at all |
| `factory:untriaged` | `#ededed` | Awaiting triage decision |
| `factory:accepted` | `#c2e0c6` | Triaged and accepted into the pipeline |
| `factory:rejected` | `#e99695` | Triaged and rejected (recoverable) |
| `factory:rate-limited` | `#fbca04` | Deferred — rate limit hit |
| `factory:in-progress` | `#1d76db` | Agent is working |
| `factory:needs-review` | `#0052cc` | PR open, awaiting review |
| `factory:approved-pending-merge` | `#0e8a16` | Review approved, queued to merge |
| `factory:rejected-final` | `#b60205` | Rejected after fix attempts (terminal) |
| `factory:needs-human` | `#d93f0b` | Escalated to operator (terminal-pending) |
| `factory:fix-attempt-1` | `#fbca04` | First fix attempt in progress |
| `factory:fix-attempt-2` | `#d93f0b` | Second (final) fix attempt in progress |

Canonical source: `bridge/factory/labels.py` (`_LABEL_METADATA`).
