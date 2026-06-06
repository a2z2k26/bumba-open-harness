# Ops Chief Artifacts

Write artifacts when operations work creates procedures, evidence, or state
that should survive the run.

Write artifacts for:

- runbooks;
- incident notes;
- deployment and rollback plans;
- monitoring findings;
- infrastructure decision notes;
- unresolved operational blockers.

Artifact rules:

- Write under the active Zone 4 run workspace.
- Include commands as evidence only when they are safe to repeat.
- Mark operator-only steps clearly.
- Link manifest and memory pointers in blocker or result surfaces.
- Never write ops artifacts into the Bumba Mac repository by default.

If the answer is a short status judgment, use the final response instead of an
empty artifact.
