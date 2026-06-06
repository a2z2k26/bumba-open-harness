---
name: pause-feature
description: Pause specific feature
---

# /pause-feature Command

Pauses a single active agent/feature while keeping other orchestration work running. Useful for selectively stopping problematic features, applying targeted fixes, or managing resource constraints without disrupting the entire orchestration session.

## Usage

```
/pause-feature <issue_number> [options]
```

## Parameters

- `<issue_number>` (required): GitHub issue number of the feature to pause
- `--snapshot` (optional): Create sandbox snapshot before pausing - default: false
- `--graceful` (optional): Wait for current operation to complete before pausing - default: false
- `--timeout <seconds>` (optional): Graceful pause timeout in seconds - default: 60
- `--reason <text>` (optional): Reason for pausing (logged to event system)
- `--preserve-sandbox` (optional): Keep sandbox running in paused state - default: true
- `--force` (optional): Force immediate pause without graceful shutdown - default: false

## Workflow

### Step 1: Feature Identification and Validation

```
⏸️  Pause Single Feature
═══════════════════════════════════════════════

Validating request...
  Issue: #47 - Add OAuth Integration
  Agent ID: agt_xyz456def
  Sandbox: sbx_ghi789jkl
  Status: active (running tests)
  Progress: 68%

Current Operation:
  Phase: Testing
  Running: npm test -- src/auth/oauth.test.ts
  Started: 2025-01-18T10:25:00Z
  Duration: 4m 32s

Active Orchestration:
  Session ID: orch_abc123xyz
  Strategy: balanced
  Active Agents: 5 (#42, #45, #47, #49, #50)
  Total Features: 8

───────────────────────────────────────────────
```

### Step 2: Pause Strategy Selection

```
Pause Configuration:
  Mode: graceful (wait for current operation)
  Timeout: 60 seconds
  Snapshot: No
  Preserve Sandbox: Yes
  Reason: "Fix failing OAuth tests"

Impact Analysis:
  Affected: 1 agent (#47)
  Unaffected: 4 agents (continue running)
  Orchestration: Continues
  Resource Impact: -20% CPU, -512MB memory (preserved)

State Preservation:
  ✓ Current test run will complete
  ✓ Sandbox preserved in paused state
  ✓ Git branch remains checked out
  ✓ Environment variables preserved
  ✓ Build artifacts retained
  ✓ Resume position: after test completion

───────────────────────────────────────────────
```

### Step 3: Graceful Pause Execution

```
Initiating graceful pause...
  ⟳ Waiting for current operation to complete...

Current Operation Progress:
  [████████████████░░░░] 78% - Running test suite

  Tests Completed: 23/30
  Time Remaining: ~12 seconds

  ⟳ Monitoring test execution...
  ✓ Test suite completed (30/30 passed)
  ✓ Operation finished successfully

Pausing agent...
  ⏸️ Suspending agent process
  ✓ Agent state saved to disk
  ✓ Sandbox marked as paused
  ✓ Git worktree preserved
  ✓ Environment snapshot created
  ✓ Network connections closed gracefully

Updating orchestration state...
  ✓ Agent #47 status: active → paused
  ✓ Removed from active pool
  ✓ Added to paused queue
  ✓ Resource allocation updated
  ✓ Event logged

───────────────────────────────────────────────
```

### Step 4: Pause Confirmation

```
✅ Feature Paused Successfully
═══════════════════════════════════════════════

Paused Feature:
  Issue: #47 - Add OAuth Integration
  Agent ID: agt_xyz456def
  Sandbox: sbx_ghi789jkl (preserved)
  Paused At: 2025-01-18T10:29:32Z
  Last Operation: Testing (completed)
  Progress: 68%

State File:
  Location: .bumba/orchestration/paused/agent_47.json
  Size: 2.4 KB
  Includes: Agent state, sandbox config, environment

Resume Options:
  Resume this feature:
    /resume-feature 47

  Resume with fresh sandbox:
    /resume-feature 47 --new-sandbox

  Resume all paused features:
    /resume-orchestration --only-paused

Active Orchestration:
  Session: orch_abc123xyz
  Active Agents: 4 (#42, #45, #49, #50)
  Paused Agents: 1 (#47)
  Status: Running

───────────────────────────────────────────────
```

## Examples

### Example 1: Simple Pause

```
/pause-feature 47
```

**Output**:
```
⏸️  Pause Feature #47

Current Operation: Testing (in progress)
Mode: immediate (interrupt current operation)

⏸️ Interrupting test run...
✓ Agent paused
✓ Sandbox preserved: sbx_ghi789jkl

Resume: /resume-feature 47
```

### Example 2: Graceful Pause with Timeout

```
/pause-feature 47 --graceful --timeout 120
```

**Output**:
```
⏸️  Graceful Pause Feature #47

Current Operation: Building (2m 15s elapsed)
Timeout: 120 seconds

⟳ Waiting for build to complete...
  [████████████████████] 100% - Build completed

✓ Build finished successfully
⏸️ Pausing agent...
✓ Agent paused gracefully
✓ Sandbox preserved: sbx_ghi789jkl

Last Completed: Build (successful)
Resume: /resume-feature 47
```

### Example 3: Pause with Snapshot

```
/pause-feature 47 --snapshot --reason "Debug OAuth flow"
```

**Output**:
```
⏸️  Pause Feature #47 with Snapshot

Reason: "Debug OAuth flow"

Creating sandbox snapshot...
  Sandbox: sbx_ghi789jkl
  Size: 2.8 GB
  ⟳ Snapshotting filesystem...
  ✓ Snapshot created: snap_oauth_debug_20250118

Pausing agent...
  ✓ Agent paused
  ✓ Sandbox preserved
  ✓ Snapshot available for restore

Snapshot Details:
  ID: snap_oauth_debug_20250118
  Created: 2025-01-18T10:30:00Z
  Size: 2.8 GB
  Restore: /sandbox-restore sbx_ghi789jkl snap_oauth_debug_20250118

Resume: /resume-feature 47
```

### Example 4: Force Pause (Immediate)

```
/pause-feature 47 --force
```

**Output**:
```
⏸️  Force Pause Feature #47

⚠️ Warning: Force pause will interrupt current operation

Current Operation: Running database migrations
Progress: 3/8 migrations completed

Forcing immediate pause...
  ⏸️ Interrupting operation
  ⚠️ Migration #4 interrupted (will retry on resume)
  ✓ Agent terminated
  ✓ Sandbox preserved
  ✓ Checkpoint saved

Resume: /resume-feature 47
Note: Interrupted migration will restart from checkpoint
```

### Example 5: Pause Without Preserving Sandbox

```
/pause-feature 47 --preserve-sandbox=false
```

**Output**:
```
⏸️  Pause Feature #47 (Terminate Sandbox)

⚠️ Warning: Sandbox will be terminated

Current State:
  Sandbox: sbx_ghi789jkl
  Resources: 2 vCPU, 4GB RAM
  Disk Usage: 3.2 GB

Saving state...
  ✓ Git changes committed to branch
  ✓ Environment variables exported
  ✓ Configuration saved
  ✓ Progress checkpoint created

Terminating sandbox...
  ⏸️ Pausing agent
  🗑️ Terminating sandbox sbx_ghi789jkl
  ✓ Resources released

Resume: /resume-feature 47 --new-sandbox
Note: Resume will create new sandbox from saved state
```

### Example 6: Pause Multiple Features

```
/pause-feature 47 --graceful && /pause-feature 49 --graceful
```

**Output**:
```
⏸️  Pause Feature #47

⟳ Waiting for testing to complete...
✓ Tests completed
✓ Agent paused

⏸️  Pause Feature #49

⟳ Waiting for PR creation to complete...
✓ PR created successfully
✓ Agent paused

Summary:
  Paused: #47, #49
  Active: #42, #45, #50 (3 agents)
  Resume: /resume-feature 47 49
```

### Example 7: Pause with Detailed Reason

```
/pause-feature 47 --reason "OAuth tests failing with CORS errors; need to update test environment configuration before continuing"
```

**Output**:
```
⏸️  Pause Feature #47

Reason: "OAuth tests failing with CORS errors; need to update
         test environment configuration before continuing"

⏸️ Pausing agent...
✓ Agent paused
✓ Sandbox preserved: sbx_ghi789jkl
✓ Reason logged to event system

Event Log:
  [10:30:15] PAUSE #47 - OAuth tests failing with CORS errors
             Agent: agt_xyz456def
             Sandbox: sbx_ghi789jkl

Resume: /resume-feature 47
View logs: /orchestrator-events --filter issue:47
```

### Example 8: Pause During Long-Running Operation

```
/pause-feature 51 --graceful --timeout 300
```

**Output**:
```
⏸️  Graceful Pause Feature #51

Current Operation: Database seeding (long-running)
Estimated Time: 4m 12s remaining
Timeout: 300 seconds

⟳ Waiting for seeding to complete...

Progress:
  [████████████░░░░░░░░] 62% - Seeding users table
  Records: 15,420 / 25,000

  ⟳ Monitoring operation...

  [████████████████████] 100% - Seeding completed
  Total Records: 25,000
  Duration: 3m 48s

✓ Seeding completed successfully
⏸️ Pausing agent...
✓ Agent paused

Last Completed: Database seeding (25,000 records)
Resume: /resume-feature 51
```

## Error Handling

### Error 1: Feature Not Found

```
❌ Error: Feature not found

Issue Number: #99
Reason: No active or queued feature found for issue #99

Active Features:
  #42 - User Authentication (active)
  #45 - Payment Integration (active)
  #47 - OAuth Integration (active)

Paused Features:
  (none)

Queued Features:
  #51 - Email Notifications
  #52 - File Upload
  #53 - Search Functionality

Did you mean:
  /pause-feature 47  (OAuth Integration)

Troubleshooting:
  View all features:
    /orchestrator-status

  Pause orchestration:
    /pause-orchestration
```

### Error 2: Feature Already Paused

```
❌ Error: Feature already paused

Issue: #47 - Add OAuth Integration
Status: paused
Paused At: 2025-01-18T10:15:00Z (15 minutes ago)
Reason: "Fix failing tests"

Current State:
  Agent: agt_xyz456def (paused)
  Sandbox: sbx_ghi789jkl (preserved)
  Progress: 68%

Available Actions:

  Resume this feature:
    /resume-feature 47

  View pause details:
    /orchestrator-events --filter issue:47

  Force re-pause (recreate state):
    /pause-feature 47 --force

Recommendation: Use /resume-feature to resume work
```

### Error 3: Graceful Timeout Exceeded

```
❌ Error: Graceful pause timeout exceeded

Issue: #47 - Add OAuth Integration
Operation: Integration tests (still running)
Timeout: 60 seconds
Elapsed: 62 seconds

Current Operation:
  Running: npm test -- --testPathPattern=integration
  Duration: 5m 02s
  Status: Still executing
  Progress: Unknown

Timeout exceeded waiting for operation to complete.

Recovery Options:

  Option 1: Force Pause (Interrupt)
  ───────────────────────────────────────
    /pause-feature 47 --force

  Consequence: Test run will be interrupted
  Resume Impact: Tests will restart from beginning

  Option 2: Extend Timeout
  ───────────────────────────────────────
    /pause-feature 47 --graceful --timeout 180

  Extended wait: Additional 120 seconds
  Use if: Tests are about to complete

  Option 3: Let Complete Then Pause
  ───────────────────────────────────────
    Wait for tests to finish manually, then:
    /pause-feature 47

Recommendation: If tests are almost done, use Option 3.
                Otherwise, use Option 1 to force pause.
```

### Error 4: Sandbox Snapshot Failed

```
❌ Error: Sandbox snapshot failed

Issue: #47 - Add OAuth Integration
Sandbox: sbx_ghi789jkl
Snapshot Mode: Requested

Snapshot Error:
  Code: INSUFFICIENT_DISK_SPACE
  Message: Not enough disk space for snapshot
  Required: 3.2 GB
  Available: 1.8 GB

Disk Usage:
  Sandbox Size: 3.2 GB
  Snapshot Space: 3.2 GB (1:1 ratio)
  Available: 1.8 GB
  Shortfall: 1.4 GB

Recovery Options:

  Option 1: Pause Without Snapshot
  ───────────────────────────────────────
    /pause-feature 47

  Consequence: No snapshot created
  Resume Impact: Resume from current state (no rollback point)

  Option 2: Clean Sandbox First
  ───────────────────────────────────────
    /sandbox-exec sbx_ghi789jkl "npm run clean"
    /pause-feature 47 --snapshot

  Expected Cleanup: ~800MB-1.2GB
  Use if: Build artifacts can be safely removed

  Option 3: Terminate Sandbox
  ───────────────────────────────────────
    /pause-feature 47 --preserve-sandbox=false

  Consequence: Sandbox terminated, no snapshot
  Resume Impact: New sandbox created on resume

Recommendation: Option 1 for quick pause, Option 2 for snapshot
```

### Error 5: Concurrent Operation Lock

```
❌ Error: Feature locked by concurrent operation

Issue: #47 - Add OAuth Integration
Lock Status: Locked
Lock Owner: /sandbox-exec command
Lock Acquired: 2025-01-18T10:28:00Z (30 seconds ago)
Operation: Running manual test command

Cannot pause while feature is locked.

Active Lock Details:
  Command: /sandbox-exec sbx_ghi789jkl "npm run test:oauth"
  User: @developer
  Process ID: pid_xyz123
  Expected Duration: ~2 minutes

Recovery Options:

  Option 1: Wait for Operation to Complete
  ───────────────────────────────────────
    Wait ~2 minutes for /sandbox-exec to finish, then:
    /pause-feature 47

  Option 2: Cancel Concurrent Operation
  ───────────────────────────────────────
    Cancel the /sandbox-exec command first, then pause:
    (Cancel via Ctrl+C if you own the process)

  Option 3: Force Pause (Override Lock)
  ───────────────────────────────────────
    /pause-feature 47 --force

  ⚠️ Warning: Will interrupt the running command

Recommendation: Option 1 if operation is almost done,
                Option 2 if you own the process,
                Option 3 only if necessary
```

### Error 6: No Active Orchestration

```
❌ Error: No active orchestration session

Issue: #47
Reason: Cannot pause feature without active orchestration

There is no active orchestration session to pause from.

Available Actions:

  Check orchestration status:
    /orchestrator-status

  Start new orchestration:
    /parallel-implement-features #42 #45 #47

  View paused sessions:
    ls .e2b/orchestration/sessions/

Note: /pause-feature only works during active orchestration.
      To pause the entire orchestration, use /pause-orchestration.
```

### Error 7: Insufficient Permissions

```
❌ Error: Insufficient permissions

Issue: #47 - Add OAuth Integration
Owner: @lead-developer
Current User: @developer

You do not have permission to pause this feature.

Permission Details:
  Feature Owner: @lead-developer
  Orchestration Owner: @lead-developer
  Your Role: contributor

Features You Can Pause:
  #49 - Email Notifications (your feature)
  #52 - File Upload (your feature)

Recovery Options:

  Option 1: Request Permission
  ───────────────────────────────────────
    Contact @lead-developer to pause #47

  Option 2: Pause Your Own Features
  ───────────────────────────────────────
    /pause-feature 49
    /pause-feature 52

  Option 3: Override (If Admin)
  ───────────────────────────────────────
    /pause-feature 47 --force --admin

  ⚠️ Requires admin privileges

Recommendation: Option 1 or Option 2
```

### Error 8: State Corruption Detected

```
❌ Error: Cannot pause due to state corruption

Issue: #47 - Add OAuth Integration
Agent ID: agt_xyz456def
Corruption Detected: Yes

State Issues Found:
  ✗ Agent state file missing timestamp
  ✗ Sandbox metadata inconsistent
  ✗ Git worktree path invalid
  ⚠️ Progress data may be inaccurate

Pause operation blocked to prevent data loss.

Recovery Options:

  Option 1: Repair State and Pause
  ───────────────────────────────────────
    /orchestrator-repair --agent 47
    /pause-feature 47

  Attempts to repair agent state first

  Option 2: Force Pause (Discard Corrupted State)
  ───────────────────────────────────────
    /pause-feature 47 --force

  ⚠️ Warning: May lose some progress data
  Resume Impact: May need to retry some operations

  Option 3: Terminate and Restart
  ───────────────────────────────────────
    /stop-feature 47
    /parallel-implement-features #47

  Starts fresh implementation from beginning

Recommendation: Try Option 1 first.
                Use Option 2 if repair fails.
                Option 3 as last resort.
```

## Integration

### Integration with Orchestration System
- Updates orchestration state to reflect paused agent
- Removes agent from active pool
- Preserves agent in paused queue
- Maintains feature priority for resume
- Logs pause event to orchestration event log

### Integration with Sandbox Management
- Preserves or terminates sandbox based on `--preserve-sandbox` flag
- Creates sandbox snapshots if requested
- Maintains sandbox metadata for resume
- Releases resources if sandbox terminated
- Updates sandbox registry

### Integration with Git Worktree
- Preserves git worktree for paused feature
- Commits any uncommitted changes
- Maintains branch checkout
- Preserves stash entries
- Enables resume from exact git state

### Integration with State Persistence
- Saves agent state to `.bumba/orchestration/paused/agent_<issue>.json`
- Includes progress information
- Stores environment variables
- Preserves operation checkpoints
- Enables exact resume

### Integration with Event System
- Logs pause event with timestamp
- Records pause reason
- Tracks pause initiator
- Enables audit trail
- Supports event filtering

## Use Cases

### Use Case 1: Fix Failing Tests
**Scenario**: Feature #47 has failing tests; need to update test configuration before continuing.

**Command**:
```bash
/pause-feature 47 --graceful --reason "Fix OAuth CORS configuration"
```

**Result**: Agent pauses after current test run completes, allowing manual fixes.

### Use Case 2: Resource Constraints
**Scenario**: System under heavy load; need to temporarily reduce active agents.

**Command**:
```bash
/pause-feature 47 --preserve-sandbox=false
/pause-feature 49 --preserve-sandbox=false
```

**Result**: Two features paused and sandboxes terminated, freeing resources.

### Use Case 3: Debug Single Feature
**Scenario**: Need to debug feature in isolation without affecting others.

**Command**:
```bash
/pause-feature 47 --snapshot
/sandbox-debug sbx_ghi789jkl
```

**Result**: Feature paused with snapshot, ready for interactive debugging.

### Use Case 4: Change Priority
**Scenario**: Higher priority work arrived; pause lower priority feature.

**Command**:
```bash
/pause-feature 53 --graceful
/parallel-implement-features #60  # High priority
```

**Result**: Lower priority feature paused, resources available for urgent work.

### Use Case 5: Dependency Blocker
**Scenario**: Feature #49 depends on API changes in feature #47; pause until unblocked.

**Command**:
```bash
/pause-feature 49 --reason "Blocked waiting for #47 API changes"
```

**Result**: Dependent feature paused until blocker resolved.

## Performance Considerations

### Pause Speed
- Immediate pause: <1 second
- Graceful pause: 10-120 seconds (depends on operation)
- Snapshot creation: 30-180 seconds (depends on sandbox size)

### Resource Impact
- Paused agent: Minimal CPU, preserves memory if sandbox kept
- Terminated sandbox: Full resource release
- State file: <5KB per paused agent

### State Preservation
- All agent state preserved in JSON file
- Sandbox state preserved if `--preserve-sandbox=true`
- Git worktree maintained
- Resume capability preserved indefinitely

## Notes

- **Selective Pause**: Only affects specified feature, others continue
- **Graceful Default**: Use `--graceful` for clean operation completion
- **State Preservation**: Agent state always saved, sandbox optional
- **Resume Ready**: Paused features can be resumed anytime
- **Event Logging**: All pauses logged with timestamp and reason
- **Snapshot Optional**: Use `--snapshot` for rollback capability
- **Resource Control**: Use `--preserve-sandbox=false` to free resources
- **Concurrent Safe**: Cannot pause feature locked by other operations
- **Permissions**: May require owner or admin permissions
- **Multiple Pause**: Can pause multiple features independently
- **Orchestration Continues**: Other agents unaffected by single pause
