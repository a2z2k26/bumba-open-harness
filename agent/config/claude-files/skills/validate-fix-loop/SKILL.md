---
name: validate-fix-loop
description: Generate code, test it, iterate on failures, and ship validated changes
---

# Validate-Fix Loop Skill

Implements the generate → test → iterate → ship methodology. Ensures all code changes pass validation before deployment.

## Methodology

### The Loop

```
1. Make change (implement feature / apply fix)
2. Run /validate
3. If failures:
   a. Analyze each error — read test + source
   b. Identify root cause
   c. Apply targeted fix
   d. Go to step 2
4. If max iterations (3) reached:
   a. Stop iterating
   b. Report to operator with analysis of remaining failures
   c. Include what was tried and why it didn't work
5. If all passing:
   a. Commit changes
   b. Optionally /deploy
```

### Decision Tree

**When to use local testing:**
- Project code is already on disk
- Tests don't have destructive side effects
- Standard test frameworks (pytest, jest, etc.)
- bumba-open-harness system itself

**When to use sandbox testing (`--sandbox`):**
- Untrusted dependencies (new packages, npm modules from unknown sources)
- Destructive operations (database migrations, file system modifications)
- Multi-language projects where local env may not be configured
- New frameworks or runtimes not installed locally

**When to escalate vs iterate:**
- After 3 failed iterations
- When the fix would require changing test expectations (tests might be right)
- When the failure is in external dependencies
- When the fix would touch kernel files (Tier C — can't self-deploy)

## Error Analysis Strategy

For each failing test:
1. Read the full test code to understand what it expects
2. Read the source code being tested
3. Check if the error is:
   - **Import error** → missing module, wrong path, circular import
   - **Assertion error** → logic bug, wrong return value, state issue
   - **Attribute error** → API mismatch, refactoring missed a reference
   - **Type error** → wrong argument types, missing arguments
4. Apply the minimal fix — don't over-engineer

## Integration Points

| Command/Tool | When to Use |
|---|---|
| `/validate` | Run tests, get pass/fail report |
| `/validate --fix` | Auto-enter this loop on failure |
| `/validate --sandbox` | Run in E2B sandbox for safety |
| `/deploy` | After validation passes, deploy changes |
| `/testing/all` | Run full test matrix (all test files) |

## Exit Conditions

The loop terminates when:
1. **All tests pass** → commit + optional deploy
2. **Max iterations reached (3)** → report to operator
3. **Operator interrupts** → stop and report current state
4. **Cannot fix without Tier C changes** → report with explanation

## Trigger Detection

Activate when:
- User says "validate and fix", "test and fix", "make it pass"
- `/validate --fix` is invoked
- After implementing a feature: "validate this", "does it work?"
- "Ship it" / "deploy it" (validate first, then deploy)

## Example Flow

```
Operator: "Add email notifications to the briefing service"

1. Read briefing.py, understand current sources
2. Add @register_source("Today's Schedule") with calendar data
3. /validate → 196 passed, 2 failed
   - test_briefing.py::test_sources_registered: expected 4 sources, got 5
   - test_briefing.py::test_compile_empty_db: "Schedule" not expected in output
4. Fix test: update expected source count to 5, handle empty calendar
5. /validate → 198 passed, 0 failed
6. Commit: "Add calendar source to morning briefing"
7. /deploy (Tier A, auto-execute)
```
