# Experiment Program

This file is the **loop-as-markdown** definition for the autonomous
experiment loop (see `agent/scripts/experiment_loop.py`). The Python
orchestrator parses the seven `##` sections below at the start of every
iteration; tuning loop behavior happens here, not in code.

The parser is in `agent/scripts/_loop_program.py`. A malformed edit
falls back to a baked-in default rather than bricking the loop —
check `agent/logs/experiment-loop.log` for parse warnings after
editing.

## Objective

Propose and implement ONE small, focused code change per iteration that
improves the Bumba codebase along the canonical fitness metric (defined
in Sprint 02.02; until that lands, success is "all existing tests pass
and ruff stays clean"). Prefer removing code over adding code; prefer
clarity over cleverness; prefer surgical changes over refactors.

## Mutation Surface

You may modify any file matching the globs below. Anything else is out
of scope for the iteration.

- bridge/*.py
- bridge/services/*.py
- tests/*.py

Files explicitly forbidden are enumerated by the orchestrator (union of
`tier_manager.IMMUTABLE_FILES` and `EXPERIMENT_LOOP_EXTRA_FORBIDDEN`)
and passed into the apply prompt at runtime — do not duplicate them
here.

## Loop Steps

Each iteration runs these steps in order. Steps 1-2 are the proposal
subprocess; steps 3-9 are orchestrated by the Python loop and listed
here so the proposal subprocess understands the full lifecycle.

1. Read the recent experiment history (last few iterations) and the
   mutation surface; pick a target file.
2. Propose ONE specific change in the exact format
   `FILE: <path relative to agent/>` followed by
   `CHANGE: <what to do, in 2-3 sentences>`.
3. Orchestrator creates a fresh git worktree off `HEAD` for the
   iteration.
4. Apply subprocess opens the worktree and edits files (Edit/Read/Glob/
   Grep/Write/Bash allowed); does not commit.
5. Orchestrator stages + commits the change in the worktree with a
   conventional-commit message.
6. Orchestrator runs `pytest` in the worktree.
7. Orchestrator evaluates Keep/Discard criteria below.
8. On keep: fast-forward merge to `main` (or cherry-pick once Sprint
   02.04 lands). On discard or crash: log + clean up worktree.
9. Notify Discord with status, fitness delta, and confidence band
   (delta + band added in Sprints 02.05 / 02.10).

## Keep Criteria

- All existing tests pass after the change.
- `ruff check agent/` stays clean (no new warnings introduced).
- No forbidden file was modified (orchestrator double-checks).
- The change is localized to the mutation surface above.
- (Once Sprint 02.02 lands) fitness delta is non-negative.

## Discard Criteria

- Any test failure, including newly added tests that fail.
- Ruff regression (lint count higher than baseline at iteration start).
- Any forbidden-file modification (immediate discard, no human review).
- Change exceeds the mutation surface.
- Apply subprocess timed out, crashed, or exited non-zero.

## Doctrine References

The `## Behavioral Doctrine` and `## Effectiveness Indicators` sections
of the project `CLAUDE.md` are load-bearing for every iteration.

- CLAUDE.md#behavioral-doctrine
- CLAUDE.md#effectiveness-indicators

The doctrine names three principles — Surgical Changes, Think Before
Coding, Effectiveness Loop — that the proposal and apply subprocesses
must respect. Concretely: no adjacent refactor, no import cleanup, no
rename outside the named change, state assumptions before editing.

## NEVER STOP

Do not pause for permission inside an iteration. If a step fails, log
the failure and let the orchestrator handle the discard. Do not ask
clarifying questions, do not request additional context, do not emit
"I would propose X but I'm waiting for confirmation" — output the
proposal in the required format or output nothing. The orchestrator's
budget gate, fitness gate, and operator-side `/halt` flag are the only
permission boundaries that matter.
