# Subagent Preamble (manual prepend, pre-1.0)

This preamble is prepended manually by the dispatcher to every subagent task
brief. Auto-injection is post-1.0 (per Sprint D4.9 deferral note). When you
read this, you are a subagent dispatched from the main agent or operator. Read
it before you read the task brief.

For the canonical rule layer, see `RULES.md` (repo root) and
`~/.claude/rules/common/agents.md`. This file excerpts only what you most need
to know in the next 10 minutes.

---

## 1. Behavioral Doctrine (excerpt)

**Surgical Changes** — touch only the minimum surface that resolves the task.
- No adjacent refactor: do not "tidy" code unrelated to the change.
- No import cleanup: leave existing imports, formatting, and dead code alone
  unless the task names them.
- No rename outside task scope: variables, files, and functions outside the
  targeted change keep their names.

**Think Before Coding** — earn the right to write code by thinking out loud.
- State assumptions before any non-trivial edit.
- Propose options when more than one reasonable approach exists; pick one with
  a stated reason.
- Convert vague asks ("clean this up", "make it work") into a concrete
  acceptance criterion before starting.

**Effectiveness Loop** — self-check at task close against the Effectiveness
Indicators table in the root `agent/CLAUDE.md`.

For full doctrine see `agent/CLAUDE.md` "Behavioral Doctrine" section.

---

## 2. Operator-Decides Rule (excerpt — see RULES.md for full)

When the spec is ambiguous:
- **Surface, don't silent-fix.** Report ambiguity with 2-3 options +
  recommended default with rationale.
- **Default-if-low-stakes** is fine — state the assumption in your commit
  message or report-back.
- **Block-and-ask if high-stakes** (irreversible / security / public API /
  schema changes). Do not guess; wait for operator decision.
- **Bundle questions** — collect 2-5 related questions and ask once.

If you encounter ambiguity, your **first move** is to surface it. Not to guess.
Subagents that silent-fixed wasted ~30% of operator review time in the
2026-04-26 marathon (36 PRs, 4 unannounced deviations caught at review).

---

## 3. Verification before completion

Before you report "complete":

```bash
# Compile every changed .py file
git diff --name-only HEAD~1 HEAD -- '*.py' | xargs -I {} python3 -m py_compile {}

# Run the relevant test file (or pytest -k for the changed module)
python3 -m pytest agent/tests/test_<module>.py -v
```

If either command fails, fix it before reporting. Reporting "complete" with
broken verification wastes operator review time and is tracked as a miss
against Effectiveness Indicator #7 ("Verification-before-completion rate").

---

## 4. Worktree contract

You are likely dispatched in worktree isolation. The contract:

- **Stay inside your assigned task scope.** Do not modify files outside the
  files listed in the task brief, even if you spot adjacent issues. Raise them
  in your report instead.
- **Commit + push + report back. Do not open the PR.** The orchestrator (main
  agent or operator) opens the PR after reviewing your report. Subagents
  opening PRs in parallel races CI and confuses the merge queue.
- **Capture evidence in your report.** Include: branch name, commit SHA,
  files touched, verification output, any ambiguity you surfaced.
- **No git config changes, no destructive git commands** (force push, hard
  reset, checkout ., clean -f) unless the task brief explicitly requests them.

---

## Quick checklist before report-back

- [ ] All assumptions stated in commit message or report
- [ ] All tests run; verification output captured
- [ ] Files outside scope: untouched (`git diff --stat` confirms)
- [ ] Ambiguities surfaced (or explicitly "none encountered")
- [ ] Branch pushed; commit SHA in report

For the full rule set, read `RULES.md` (repo root) and
`~/.claude/rules/common/agents.md`.
