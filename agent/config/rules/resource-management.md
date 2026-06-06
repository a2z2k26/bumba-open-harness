# Resource Management Rules

These rules exist because the agent consumed 65 GB of disk in /private/tmp and .claude/worktrees/ by spawning dozens of uncleaned parallel build trees, leaking Playwright daemons, and running an xctest for 8 days straight (April 2026 incident). Removing any of these rules risks a repeat.

## Disk Awareness

**Check before creating.** Before any operation that produces large artifacts — git worktrees, repo clones, Swift builds, npm installs, Playwright browsers — check available disk space. If free space is below 20 GB, stop and alert the operator. Do not proceed with "I'll clean up after."

**Hard ceiling.** If disk usage exceeds 85%, enter a read-only posture for disk-heavy operations. Only lightweight actions (reads, searches, message responses) are permitted until the operator acknowledges.

## Worktree Discipline

**Clean up in the same session.** Every git worktree you create must be removed before the session or task ends. Use `git worktree remove`, not just `rm`.

**Maximum 2 concurrent worktrees.** Before creating a new worktree, list existing ones with `git worktree list`. If 2+ exist, remove stale ones first.

**Never leave worktrees in `.claude/worktrees/` across sessions.** If a worktree operation fails, clean up the partial worktree before exiting.

## /private/tmp Discipline

**Unique prefixes, mandatory cleanup.** Every temp directory you create must use a unique, descriptive prefix. Clean it up when the task completes — success or failure.

**Maximum 3 working directories in /private/tmp at any time.** Check `ls /private/tmp | grep bumba` before creating new ones. If 3+ exist, clean old ones first.

**No full project builds for targeted operations.** Never clone, checkout, or build an entire project repo just to search for or modify a single file. Use `git show`, `git log`, `grep`, or targeted reads instead.

## Subprocess Lifecycle

**Every spawned process must have a timeout.** Builds: 30 minutes max. Tests: 10 minutes max. Playwright sessions: 5 minutes max. No exceptions.

**Never spawn detached background processes.** Playwright daemons, headless Chrome, test runners, and build tools must be children of the current process so they die when the parent exits. If you must use `--daemon` mode, register a cleanup handler.

**Kill before exit.** If you spawned subprocesses during a task, verify they are dead before reporting completion. A `ps aux | grep` check is required.

## Build Scope

**Proportional response.** A one-file change does not need a full project build. A search does not need a clone. Match the scope of your tooling to the scope of the task.

**Never duplicate large repos into temp directories.** If you need to work on bumba-desktop or another large project, use the existing checkout — do not create parallel copies.

## Enforcement

Violations of these rules are treated the same as security violations: stop, clean up, and alert the operator. "I was going to clean up later" is not an acceptable justification — later never came, and that's why these rules exist.
