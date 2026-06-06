---
name: execute
description: Execute pre-generated implementation plan (Implementation stage)
---

# /build Command

Executes an implementation plan step-by-step with progress tracking and validation.

**Pattern Source**: Adapted from agent-sandboxes `/build` command

## Usage

```
/build <plan-file> [--start-step <n>] [--end-step <n>] [--auto-continue]
```

## Parameters

- `<plan-file>` (required): Path to plan markdown file (from `/plan`)
- `--start-step <n>` (optional): Start from specific step number (default: 1)
- `--end-step <n>` (optional): Stop at specific step number (default: last)
- `--auto-continue` (optional): Skip confirmation between steps

## Workflow

### Step 1: Load and Parse Plan

1. **Read Plan File**:
   - Load plan from specified path
   - Verify file exists and is readable
   - Parse markdown structure

2. **Extract Steps**:
   - Identify all numbered steps
   - Parse step goals, files, commands, code changes
   - Build step dependency graph
   - Validate step sequence

3. **Display Plan Overview**:
   ```
   📋 Implementation Plan: User Authentication
   ═══════════════════════════════════════════════

   Plan File:   specs/plan-42-20251118-143022.md
   Total Steps: 14
   Phases:      4
   Estimated:   6-8 hours

   Phases:
     Phase 1: Setup & Preparation (Steps 1-2)
     Phase 2: Core Implementation (Steps 3-9)
     Phase 3: Testing & Validation (Steps 10-12)
     Phase 4: Documentation & Cleanup (Steps 13-14)

   Starting from: Step 1
   Ending at:     Step 14

   Ready to begin? (yes/no)
   ```

### Step 2: Execute Steps Sequentially

For each step in the plan:

#### 2.1: Display Step Information
```
─────────────────────────────────────────────────
Step 3 of 14: Create Authentication Service
─────────────────────────────────────────────────

Goal: Implement core authentication logic

Files to modify/create:
  - src/services/auth.service.ts (create)
  - src/types/auth.types.ts (create)

Phase: Core Implementation (Step 3 of 9 in this phase)
```

#### 2.2: Execute Step Actions

**For Commands**:
```bash
Running: npm install passport passport-google-oauth20

[Stream command output in real-time]

✓ Command completed successfully (exit code: 0)
```

**For Code Changes**:
```typescript
Creating file: src/services/auth.service.ts

[Display code being written]

✓ File created (234 lines)
```

**For File Modifications**:
```typescript
Modifying: src/app.ts

[Show diff of changes]

✓ File updated
```

#### 2.3: Validate Step Completion

After each step:
1. **Verify Expected Outcomes**:
   - Check files were created/modified
   - Verify commands succeeded
   - Confirm no errors occurred

2. **Run Quick Validation**:
   - Compile TypeScript (if applicable)
   - Run linter on modified files
   - Quick syntax check

3. **Display Step Result**:
   ```
   ✅ Step 3 Complete!

   Files Changed:
     ✓ src/services/auth.service.ts (created, 234 lines)
     ✓ src/types/auth.types.ts (created, 45 lines)

   Commands Executed:
     ✓ npm install passport passport-google-oauth20

   Validation:
     ✓ TypeScript compilation: success
     ✓ Linting: no errors
     ✓ Files exist: confirmed

   Duration: 2m 34s
   ```

#### 2.4: Checkpoint (if not --auto-continue)

Between steps, pause for confirmation:
```
Continue to Step 4? (yes/no/skip/abort)
  yes   - Continue to next step
  no    - Pause and let me review
  skip  - Skip next step
  abort - Stop execution
```

### Step 3: Handle Testing Steps

When executing test-related steps:

1. **Run Tests**:
   ```
   Step 10: Write and Run Unit Tests
   ─────────────────────────────────────────────────

   Creating: src/__tests__/auth.service.test.ts

   [Display test code]

   Running: npm test src/__tests__/auth.service.test.ts

   Test Results:
   ═══════════════════════════════════════════════
     ✓ AuthService › validates credentials
     ✓ AuthService › generates JWT tokens
     ✓ AuthService › handles OAuth callbacks
     ✓ AuthService › refreshes expired tokens

   Tests: 4 passed, 4 total
   Time:  3.2s

   ✅ All tests passed!
   ```

2. **Handle Test Failures**:
   ```
   ❌ Tests Failed!

   Failed Tests:
     ✗ AuthService › handles OAuth callbacks
       Error: Expected status 200, got 401

   Would you like to:
     1. Debug this step
     2. Skip this step and continue
     3. Abort execution
     4. Let me fix the tests
   ```

### Step 4: Progress Tracking

Throughout execution:

```
📊 Build Progress
═══════════════════════════════════════════════

Progress: ████████████░░░░ 75% (Step 10 of 14)

Completed:
  ✓ Step 1: Install dependencies (2m 15s)
  ✓ Step 2: Create project structure (0m 45s)
  ✓ Step 3: Create auth service (2m 34s)
  ✓ Step 4: Create auth routes (1m 52s)
  ✓ Step 5: Configure middleware (1m 12s)
  ✓ Step 6: Add OAuth providers (3m 28s)
  ✓ Step 7: Create user model (1m 45s)
  ✓ Step 8: Implement session management (2m 18s)
  ✓ Step 9: Add error handling (1m 35s)
  ✓ Step 10: Write unit tests (3m 12s)

In Progress:
  ⟳ Step 11: Write integration tests

Remaining:
  ○ Step 12: Manual testing
  ○ Step 13: Update documentation
  ○ Step 14: Code review prep

Time Elapsed: 21m 16s
Estimated Remaining: ~7m
```

### Step 5: Final Summary

After completing all steps:

```
✅ Build Complete!

📊 Execution Summary
═══════════════════════════════════════════════

Plan:             User Authentication
Total Steps:      14
Completed:        14
Skipped:          0
Failed:           0
Duration:         28m 42s

Files Created:    8 files
Files Modified:   3 files
Total Lines:      1,247 lines

Tests:
  Unit Tests:     12 passed
  Integration:    5 passed
  Total:          17 passed

Commands Executed: 6
  ✓ npm install packages
  ✓ TypeScript compilation
  ✓ Linting
  ✓ Test runs

✅ All Acceptance Criteria Met:
  ✓ Users can login with Google
  ✓ Users can login with GitHub
  ✓ Sessions persist across page refreshes
  ✓ Tokens refresh automatically
  ✓ All tests pass
  ✓ Code is linted and formatted

📋 Next Steps:
  1. Review the implementation
  2. Run manual testing: /test
  3. Create PR: /create-pull-request
  4. Update any additional documentation

💾 Progress Saved:
  Log: logs/build-42-20251118-143022.log
  State: .claude/state/build-42.json
```

## Examples

### Example 1: Execute Full Plan
```
/build specs/plan-42-20251118-143022.md
```
Executes all steps from beginning to end.

### Example 2: Resume from Step 5
```
/build specs/plan-42-20251118-143022.md --start-step 5
```
Continues execution from step 5.

### Example 3: Execute Steps 3-7 Only
```
/build specs/plan-42-20251118-143022.md --start-step 3 --end-step 7
```
Runs specific range of steps.

### Example 4: Auto-Continue Mode
```
/build specs/plan-42-20251118-143022.md --auto-continue
```
Runs all steps without confirmation prompts.

## Error Handling

### Build Errors
```
❌ Step 5 Failed!

Error: Command failed with exit code 1
Command: npm run build
Output:
  [error output]

Recovery Options:
  1. Retry this step
  2. Fix the issue and retry
  3. Skip this step
  4. Abort build
  5. Save progress and exit

Choose option:
```

### File Conflicts
```
⚠️  File Already Exists!

File: src/services/auth.service.ts
Action: Create

Options:
  1. Overwrite file
  2. Skip this file
  3. Create backup and overwrite
  4. Abort step

Choose option:
```

## Progress Persistence

Build progress is saved automatically:

1. **State File**: `.claude/state/build-<issue>.json`
   - Current step
   - Completed steps
   - Files created/modified
   - Time tracking

2. **Log File**: `logs/build-<issue>-<timestamp>.log`
   - Detailed execution log
   - Command outputs
   - Error messages

3. **Resume Capability**:
   ```
   Detected incomplete build for issue #42
   Last step completed: Step 7

   Would you like to:
     1. Resume from Step 8
     2. Start from beginning
     3. Cancel
   ```

## Hook Integration

Build execution is tracked via hooks:
- **PostToolUse Hook**: Logs all file operations and commands
- **Stop Hook**: Tracks time and token costs for each step

## Configuration

Configure in `.claude/config/bumba-sandbox-config.json`:
- `build.autoContinue`: Skip step confirmations (default: false)
- `build.validateSteps`: Run validation after each step (default: true)
- `build.saveProgress`: Auto-save progress (default: true)
- `build.stopOnTestFailure`: Abort if tests fail (default: true)

## Notes

- Plans must be in the format generated by `/plan`
- Progress is saved automatically for resume capability
- Test failures can optionally stop execution
- You can pause and resume builds at any step
- All file changes are tracked for rollback if needed
- Use `--auto-continue` for fully automated builds
- Combine with `/plan` using `/wf_plan_build` for one-command workflow
