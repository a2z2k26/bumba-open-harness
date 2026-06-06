# engineering-chief — ARTIFACTS

Write scope: n/a (delegates).

Every run must produce, via the Zone 3 artifact layer:
- a run manifest (zone 3, department engineering) recording worktree, branch,
  changed files, and validation commands with pass/fail status;
- a memory pointer summarizing the run (run id, specialist, manifest, files);
- on failure, preserved stderr, exit code, and partial artifact references.

Do not write outside the declared write scope. Surface a dirty worktree in the
result rather than hiding it.
