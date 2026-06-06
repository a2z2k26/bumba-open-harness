<!--
  Handoff slot template — Phase 1 of #1112.
  Loaded by ``compose_handoff`` in a later sprint. Every slot below
  corresponds to a field on ``bridge.handoff.HandoffDraft``. If you
  add a slot here, add the field there (and vice versa) — the test
  ``agent/tests/test_handoff.py::test_handoff_template_file_exists_and_has_slots``
  enforces the slot-name correspondence.
-->

# Handoff Template

This is the slot template for `compose_handoff`. Every field is required.

## Slots

- **from_harness**: The harness composing the handoff (auto-filled from `config.harness_id`).
- **to_harness**: The target harness (operator names this explicitly; must appear in `config.peer_harness_ids`).
- **topic**: A short noun phrase (≤ 60 chars).
- **context_summary**: 2–5 sentences. What is the situation?
- **work_done**: What has the sending harness already done? Be specific — file paths, PR numbers, decisions.
- **ask**: What is the receiving harness being asked to do? Imperative voice.
- **boundaries**: What should the receiving harness NOT do? Surgical-changes doctrine.
- **references**: List of URLs / file paths / issue numbers the receiver should read before starting.
- **response_protocol**: Always `operator-only`. The receiver replies to the operator, never directly to the sender.
- **trust_level**: `review` (operator confirms before fire). `auto` is reserved for trust-escalation work.

## Composition discipline

A handoff is **not** a transcript. It is a compressed, structured ask. If you would not be comfortable sending this to a colleague at another company, do not fire it.

Rules of thumb:

1. State the ask in one sentence at the top. The receiving operator should know what is being requested before reading paragraph two.
2. List concrete references, not "the codebase" or "the recent work".
3. Boundaries are not optional. Even a permissive boundary ("anything in `agent/bridge/handoff/`") is more useful than silence.
4. If the sender cannot articulate `work_done` and `boundaries` clearly, the handoff is premature.
