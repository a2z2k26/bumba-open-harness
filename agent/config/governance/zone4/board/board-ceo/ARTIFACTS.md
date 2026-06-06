# Board CEO Artifacts

Write artifacts when the board creates material the operator may need to
inspect, compare, or revisit.

Write artifacts for:

- decision memos;
- option matrices;
- dissent logs;
- assumption registers;
- architecture or strategy trade-off notes;
- unresolved blockers that should survive the run.

Artifact rules:

- Write under the active Zone 4 run workspace.
- Include the decision, recommendation, dissent, and evidence quality.
- Link the manifest and memory pointer in the final board synthesis.
- Keep raw board-member bodies out of memory; preserve pointers instead.
- Never write board artifacts into the Bumba Mac repository by default.

If the board run is exploratory only, keep the final answer compact and skip
empty artifact files.
