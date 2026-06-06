---
name: quick
description: Plan and build in single command (Implementation stage)
---

# /wf_plan_build Command

Combines `/plan` and `/build` into a single workflow for streamlined development.

**Pattern Source**: Adapted from agent-sandboxes `/wf_plan_build` command

## Usage

```
/wf_plan_build <prompt> [--issue <number>] [--auto-continue] [--mode <mode>]
```

## Parameters

- `<prompt>` (required): What to implement
- `--issue <number>` (optional): GitHub issue number for context
- `--auto-continue` (optional): Skip all confirmations
- `--mode <mode>` (optional): Execution mode (local/sandbox/auto)

## Workflow

This command combines the full `/plan` and `/build` workflow:

### Step 1: Generate Plan (from /plan)

1. **Parse Requirements**:
   - Use provided prompt
   - Optionally fetch GitHub issue if `--issue` provided
   - Gather context from codebase

2. **Create Implementation Plan**:
   - Generate detailed step-by-step plan
   - Include all phases (setup, implementation, testing, docs)
   - Estimate time and complexity

3. **Display Plan for Review**:
   ```
   📋 Generated Implementation Plan
   ═══════════════════════════════════════════════

   Feature: User Authentication with OAuth2
   Steps:   14 across 4 phases
   Time:    Estimated 6-8 hours
   Complexity: Medium

   Phase 1: Setup & Preparation (2 steps)
     Step 1: Install dependencies
     Step 2: Create project structure

   Phase 2: Core Implementation (7 steps)
     Step 3: Create authentication service
     Step 4: Create auth routes
     ... (5 more steps)

   Phase 3: Testing & Validation (3 steps)
     Step 10: Write unit tests
     Step 11: Write integration tests
     Step 12: Manual testing

   Phase 4: Documentation & Cleanup (2 steps)
     Step 13: Update documentation
     Step 14: Code review prep

   📄 Plan saved to: specs/plan-auth-20251118-143022.md

   Review plan? (yes/edit/continue)
   ```

4. **Allow Plan Review/Edit**:
   - **yes**: Show full plan details
   - **edit**: Open plan in editor for modifications
   - **continue**: Proceed directly to build

### Step 2: Execute Plan (from /build)

After plan approval, automatically execute:

1. **Parse Plan**:
   - Load the generated plan
   - Extract all steps
   - Prepare for execution

2. **Execute Steps Sequentially**:
   ```
   🔨 Executing Plan
   ═══════════════════════════════════════════════

   Step 1 of 14: Install dependencies
   ─────────────────────────────────────────────────

   Running: npm install passport passport-google-oauth20

   [Stream output]

   ✓ Step 1 complete (2m 15s)

   Progress: █░░░░░░░░░░░░░░ 7%

   Continue to Step 2? (yes/no/skip) [auto: 5s]
   ```

   If `--auto-continue`, skip confirmation and proceed automatically.

3. **Track Progress**:
   - Show real-time progress bar
   - Display step-by-step results
   - Log all actions

4. **Handle Validation**:
   - Run tests at appropriate steps
   - Validate file changes
   - Check compilation/linting

### Step 3: Complete and Report

```
✅ Workflow Complete!

📊 Summary
═══════════════════════════════════════════════

Feature:        User Authentication with OAuth2
Plan:           specs/plan-auth-20251118-143022.md
Duration:       28m 42s

Planning:       3m 12s
Execution:      25m 30s

Steps:
  Completed:    14 of 14
  Skipped:      0
  Failed:       0

Implementation:
  Files Created:   8 files
  Files Modified:  3 files
  Lines Added:     1,247 lines

Tests:
  Unit Tests:      12 passed
  Integration:     5 passed
  Total:           17 passed

Quality:
  ✓ TypeScript compilation: success
  ✓ Linting: no errors
  ✓ Tests: all passing

📋 Next Steps:
  1. Review implementation
  2. Run /test for additional testing
  3. Create PR with /create-pull-request
  4. Or continue with /implement-feature for next issue

💾 Artifacts:
  Plan:  specs/plan-auth-20251118-143022.md
  Log:   logs/wf-auth-20251118-143022.log
  State: .claude/state/wf-auth.json
```

## Examples

### Example 1: Simple Feature
```
/wf_plan_build Add user profile page with avatar upload
```
Plans and implements the feature in one command.

### Example 2: From GitHub Issue
```
/wf_plan_build Implement caching --issue 42
```
Uses GitHub issue #42 for requirements, then plans and builds.

### Example 3: Fully Automated
```
/wf_plan_build Add password reset flow --auto-continue
```
Runs entire workflow without confirmations.

### Example 4: Sandbox Mode
```
/wf_plan_build Complex database migration --mode sandbox
```
Executes in isolated Bumba Sandbox sandbox for safety.

## Comparison with Separate Commands

### Using /wf_plan_build (1 command):
```bash
/wf_plan_build Add user authentication
# Automatic plan generation
# Automatic plan execution
# Single workflow
```

### Using /plan + /build (2 commands):
```bash
/plan Add user authentication
# Review and edit plan
/build specs/plan-auth-20251118-143022.md
# Execute plan
```

**Use /wf_plan_build when**:
- You want quick implementation
- You trust auto-generated plans
- You want streamlined workflow

**Use /plan + /build separately when**:
- You want to review/edit plan first
- You want to share plan for approval
- You want to execute plan later

## Workflow Modes

### Auto Mode (Default)
- Generates plan
- Shows brief summary
- Asks for confirmation
- Executes with step confirmations

### Auto-Continue Mode (`--auto-continue`)
- Generates plan
- Shows brief summary
- Asks for confirmation ONCE
- Executes all steps without pausing

### Review Mode
- Generates plan
- Shows FULL plan details
- Allows editing
- Waits for explicit approval
- Executes with confirmations

## Integration with /implement-feature

`/wf_plan_build` can be used within `/implement-feature`:

```bash
# From implement-feature sandbox mode
/implement-feature #42 --mode sandbox

# Inside sandbox agent, uses:
/wf_plan_build <issue spec> --auto-continue

# Completes full implementation automatically
```

## Error Handling

### Plan Generation Errors
```
❌ Failed to Generate Plan

Error: Unable to analyze codebase structure

Options:
  1. Provide more context
  2. Specify files/modules manually
  3. Use simpler prompt
  4. Abort

Choose option:
```

### Build Execution Errors
```
❌ Step 5 Failed!

Error: Command failed: npm run build

The workflow has been paused.

Options:
  1. Debug and fix issue
  2. Edit plan and retry
  3. Skip this step
  4. Abort workflow
  5. Save progress for later

Choose option:
```

## Hook Integration

Workflow is fully tracked:
- **PostToolUse Hook**: Logs all operations
- **Stop Hook**: Tracks time and costs
- **UserPromptSubmit Hook**: Logs confirmations

All data available in `logs/wf-<name>-<timestamp>.log`

## Configuration

Configure in `.claude/config/bumba-sandbox-config.json`:
```json
{
  "workflow": {
    "autoContinue": false,
    "reviewPlanByDefault": true,
    "saveProgressAutomatically": true,
    "stopOnTestFailure": true,
    "defaultMode": "auto"
  }
}
```

## Use Cases

### Use Case 1: Rapid Prototyping
```
/wf_plan_build Build a simple todo list API --auto-continue
```
Quick end-to-end implementation.

### Use Case 2: Issue-Based Development
```
/wf_plan_build --issue 42 --auto-continue
```
Implement GitHub issue automatically.

### Use Case 3: Complex Features
```
/wf_plan_build Implement multi-tenant architecture
# Review plan carefully
# Edit if needed
# Execute with step confirmations
```

### Use Case 4: Learning/Exploration
```
/wf_plan_build Add GraphQL support
# Review plan to understand approach
# Execute step-by-step to learn
```

## Advantages

✅ **Streamlined**: Single command for full workflow
✅ **Consistent**: Always follows plan-driven approach
✅ **Traceable**: Complete log of planning + execution
✅ **Resumable**: Can pause and resume at any point
✅ **Validated**: Built-in testing and validation

## Notes

- Combines best of `/plan` and `/build`
- Perfect for `/implement-feature` automation
- All plans are saved for future reference
- Progress is tracked and resumable
- Can switch between modes (local/sandbox)
- Particularly powerful with `--auto-continue` in sandboxes
- Used heavily by agent-sandboxes for automation
- Enables true plan-driven development workflow
