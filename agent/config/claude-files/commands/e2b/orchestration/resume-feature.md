---
name: resume-feature
description: Resume specific feature
---

# /resume-feature Command

Resumes a single paused agent/feature while keeping other orchestration work running. Enables selective feature resumption, sandbox state restoration, and targeted work continuation without affecting other active agents.

## Usage

```
/resume-feature <issue_number> [options]
```

## Parameters

- `<issue_number>` (required): GitHub issue number of the feature to resume (can specify multiple)
- `--new-sandbox` (optional): Create new sandbox instead of reusing preserved one - default: false
- `--snapshot <id>` (optional): Restore from specific sandbox snapshot
- `--skip-health-check` (optional): Skip sandbox health verification - default: false
- `--force` (optional): Force resume even if health checks fail - default: false
- `--reset-progress` (optional): Reset progress and restart from beginning - default: false
- `--priority <level>` (optional): Override feature priority (low, normal, high, urgent)

## Workflow

### Step 1: Resume Request Validation

```
▶️  Resume Single Feature
═══════════════════════════════════════════════

Validating request...
  Issue: #47 - Add OAuth Integration
  Agent ID: agt_xyz456def
  Status: paused
  Paused At: 2025-01-18T10:30:00Z (15 minutes ago)
  Pause Reason: "Fix failing OAuth tests"

Paused State:
  Last Operation: Testing (completed)
  Progress: 68%
  Sandbox: sbx_ghi789jkl (preserved)
  Git Branch: feature/oauth-integration
  Working Directory: /workspace

State File:
  Location: .bumba/orchestration/paused/agent_47.json
  Size: 2.4 KB
  Created: 2025-01-18T10:30:00Z
  Valid: Yes ✓

Active Orchestration:
  Session: orch_abc123xyz
  Strategy: balanced
  Active Agents: 4 (#42, #45, #49, #50)
  Available Slots: 1 (max: 5)

───────────────────────────────────────────────
```

### Step 2: Sandbox Health Verification

```
Verifying sandbox health...
  Sandbox ID: sbx_ghi789jkl
  Status: running (paused state)

Health Checks:
  ✓ Sandbox is alive
  ✓ Network connectivity
  ✓ Filesystem accessible
  ✓ Git repository intact
  ✓ Node.js environment ready
  ✓ Dependencies installed
  ✓ Build artifacts present

Resource Availability:
  CPU: 2 vCPU available
  Memory: 4 GB available
  Disk: 6.8 GB free (68% available)
  Network: 100 Mbps

Git Status:
  Branch: feature/oauth-integration ✓
  Uncommitted Changes: 0
  Untracked Files: 0
  Remote Sync: Up to date

Environment Verification:
  ✓ Environment variables restored (12 vars)
  ✓ Configuration files present
  ✓ Database connection ready
  ✓ API keys configured

All health checks passed ✓

───────────────────────────────────────────────
```

### Step 3: State Restoration

```
Restoring agent state...
  Loading state from: .bumba/orchestration/paused/agent_47.json

Restoring configuration:
  ✓ Feature metadata loaded
  ✓ Progress checkpoint: 68%
  ✓ Last completed: Testing phase
  ✓ Next operation: Create PR
  ✓ Environment variables applied
  ✓ Git context restored

Reconnecting to sandbox:
  ✓ SSH connection established
  ✓ Working directory: /workspace
  ✓ Process environment configured
  ✓ File watchers initialized

Resuming from checkpoint:
  Phase: PR Creation
  Starting Point: All tests passed
  Next Steps:
    1. Commit changes to branch
    2. Push to remote
    3. Create pull request
    4. Run CI/CD validation

───────────────────────────────────────────────
```

### Step 4: Resume Execution

```
Starting agent execution...
  ▶️ Resuming agent agt_xyz456def
  ✓ Agent process started
  ✓ Added to active pool
  ✓ Resource allocation updated
  ✓ Event logged

Agent Activity:
  [10:45:02] 📝 Preparing to create PR
  [10:45:03] 🔄 Committing changes to feature/oauth-integration
  [10:45:05] 📤 Pushing to remote
  [10:45:08] 🎯 Creating pull request
  [10:45:12] ✅ PR created: #127

✅ Feature Resumed Successfully
═══════════════════════════════════════════════

Resumed Feature:
  Issue: #47 - Add OAuth Integration
  Agent ID: agt_xyz456def
  Sandbox: sbx_ghi789jkl (reused)
  Resumed At: 2025-01-18T10:45:00Z
  Downtime: 15 minutes

Current Status:
  Phase: Creating PR → Running CI/CD
  Progress: 68% → 85%
  Next: Wait for CI/CD validation

Active Orchestration:
  Session: orch_abc123xyz
  Active Agents: 5 (#42, #45, #47, #49, #50)
  Paused Agents: 0
  Available Slots: 0 (at capacity)

───────────────────────────────────────────────
```

## Examples

### Example 1: Simple Resume

```
/resume-feature 47
```

**Output**:
```
▶️  Resume Feature #47

Validating state...
  ✓ Paused state found
  ✓ Sandbox healthy: sbx_ghi789jkl

Restoring agent...
  ✓ State loaded
  ✓ Environment restored
  ✓ Sandbox reconnected

▶️ Resuming from: Create PR phase
✓ Agent active

Active: 5 agents
```

### Example 2: Resume with New Sandbox

```
/resume-feature 47 --new-sandbox
```

**Output**:
```
▶️  Resume Feature #47 (New Sandbox)

Creating new sandbox...
  🏗️ Template: node18-typescript
  ⟳ Provisioning resources...
  ✓ Sandbox created: sbx_new789xyz

Restoring state to new sandbox:
  ✓ Cloning repository
  ✓ Checking out branch: feature/oauth-integration
  ✓ Installing dependencies
  ✓ Applying environment variables
  ✓ Restoring build artifacts

Progress Restoration:
  Previous: 68% (testing complete)
  Resuming from: Create PR phase
  ✓ State synchronized

Old Sandbox:
  sbx_ghi789jkl → Terminated
  Resources released

▶️ Agent resumed on new sandbox
Active: 5 agents
```

### Example 3: Resume from Snapshot

```
/resume-feature 47 --snapshot snap_oauth_debug_20250118
```

**Output**:
```
▶️  Resume Feature #47 from Snapshot

Snapshot Details:
  ID: snap_oauth_debug_20250118
  Created: 2025-01-18T10:30:00Z
  Size: 2.8 GB
  State: Ready

Restoring sandbox from snapshot...
  ⟳ Loading snapshot data...
  ✓ Filesystem restored (2.8 GB)
  ✓ Git state: feature/oauth-integration
  ✓ Environment variables: 12 restored
  ✓ Build artifacts: Present

Snapshot State:
  Progress: 68% (at snapshot time)
  Last Operation: Testing (completed)
  Uncommitted Changes: 0

Resume Point:
  Starting from: Create PR phase
  ✓ Agent resumed

Note: Resuming from snapshot at capture point (68%)
Active: 5 agents
```

### Example 4: Resume Multiple Features

```
/resume-feature 47 49 51
```

**Output**:
```
▶️  Resume Multiple Features

Feature #47:
  ✓ State validated
  ✓ Sandbox healthy: sbx_ghi789jkl
  ▶️ Resumed

Feature #49:
  ✓ State validated
  ✓ Sandbox healthy: sbx_mno234pqr
  ▶️ Resumed

Feature #51:
  ⚠️ Sandbox capacity exceeded (max: 5)
  ⏳ Queued for next available slot

Summary:
  Resumed: #47, #49 (2 agents)
  Queued: #51 (1 agent)
  Active: 5 agents (at capacity)

Note: #51 will resume automatically when slot available
```

### Example 5: Force Resume Despite Health Warnings

```
/resume-feature 47 --force
```

**Output**:
```
▶️  Force Resume Feature #47

Health Check Results:
  ⚠️ Sandbox warnings detected

Warnings:
  ⚠️ Disk space low: 1.2 GB available (12%)
  ⚠️ npm cache corrupted
  ✓ Git repository intact
  ✓ Network connectivity

Force resume requested - proceeding despite warnings

Attempting recovery:
  ⟳ Clearing npm cache...
  ✓ Cache cleared (freed 340 MB)
  ⟳ Running npm install...
  ✓ Dependencies reinstalled

▶️ Agent resumed with warnings
⚠️ Monitor disk space: /orchestrator-status

Active: 5 agents
```

### Example 6: Resume with Priority Override

```
/resume-feature 47 --priority urgent
```

**Output**:
```
▶️  Resume Feature #47 (Priority: urgent)

Original Priority: normal
New Priority: urgent

Impact:
  Position in Queue: Last → First
  Resource Allocation: Standard → Priority
  Attention: Regular → Elevated

⚠️ Capacity at maximum (5/5 agents)

Options:
  1. Pause lower priority agent to make room
  2. Queue as urgent (resume when slot available)

Selected: Queue as urgent

▶️ Feature queued with urgent priority
⏳ Will resume immediately when slot available
🔔 Notification enabled for resume event

Current Queue:
  1. #47 (urgent) ← Your feature
  2. #51 (normal)
  3. #52 (low)
```

### Example 7: Resume with Progress Reset

```
/resume-feature 47 --reset-progress
```

**Output**:
```
▶️  Resume Feature #47 (Reset Progress)

⚠️ Warning: This will discard all progress and restart

Current State:
  Progress: 68%
  Completed:
    ✓ Implementation
    ✓ Unit tests
    ✓ Integration tests

  Remaining:
    ⏳ Create PR
    ⏳ CI/CD validation

Resetting progress...
  🔄 Resetting to 0%
  🗑️ Discarding completed work
  ✓ Fresh start configuration

Resume Point: Beginning (implementation phase)

Reason: Full restart requested
Use Case: Major approach change, start over

▶️ Agent resumed from beginning
Progress: 0%
Phase: Implementation
```

### Example 8: Skip Health Check (Fast Resume)

```
/resume-feature 47 --skip-health-check
```

**Output**:
```
▶️  Resume Feature #47 (Skip Health Check)

⚠️ Skipping sandbox health verification

Loading state:
  ✓ Agent state loaded
  ✓ Sandbox ID: sbx_ghi789jkl

Assuming:
  ✓ Sandbox is healthy
  ✓ Environment is intact
  ✓ Dependencies available

▶️ Agent resumed immediately
Active: 5 agents

Note: If issues occur, use:
  /pause-feature 47
  /resume-feature 47 --new-sandbox
```

## Error Handling

### Error 1: Feature Not Paused

```
❌ Error: Feature is not paused

Issue: #47 - Add OAuth Integration
Current Status: active (running)

The requested feature is currently active, not paused.

Current Activity:
  Agent: agt_xyz456def
  Phase: Testing
  Progress: 78%
  Operation: Running integration tests

Available Actions:

  View feature status:
    /orchestrator-status --feature 47

  Pause the feature:
    /pause-feature 47

  View all paused features:
    /orchestrator-status --only-paused

Note: /resume-feature only works on paused features.
      Active features are already running.
```

### Error 2: Sandbox Terminated

```
❌ Error: Sandbox no longer available

Issue: #47 - Add OAuth Integration
Paused Sandbox: sbx_ghi789jkl
Status: Terminated

The sandbox for this feature was terminated and cannot be resumed.

Termination Details:
  Terminated At: 2025-01-18T11:00:00Z
  Reason: Manual cleanup
  State: Lost

Recovery Options:

  Option 1: Resume with New Sandbox
  ───────────────────────────────────────
    /resume-feature 47 --new-sandbox

  Creates fresh sandbox from saved state
  Progress: Restored from checkpoint (68%)
  Duration: ~3-5 minutes to provision

  Option 2: Resume from Snapshot (if available)
  ───────────────────────────────────────
    /resume-feature 47 --snapshot snap_oauth_debug_20250118

  Restores exact sandbox state from snapshot
  Progress: Exact state at snapshot time
  Duration: ~2-4 minutes to restore

  Option 3: Restart Feature from Beginning
  ───────────────────────────────────────
    /resume-feature 47 --reset-progress

  Starts fresh implementation
  Progress: 0% (full restart)

Available Snapshots:
  snap_oauth_debug_20250118 (2.8 GB) - 30 minutes ago

Recommendation: Option 2 if snapshot recent, otherwise Option 1
```

### Error 3: State File Corrupted

```
❌ Error: Cannot resume due to corrupted state

Issue: #47 - Add OAuth Integration
State File: .bumba/orchestration/paused/agent_47.json
Status: Corrupted

Corruption Details:
  ✗ Invalid JSON syntax at line 42
  ✗ Missing required field: 'sandboxId'
  ✗ Progress value out of range: 150%
  ⚠️ Unable to parse state file

Cannot safely resume from corrupted state.

Recovery Options:

  Option 1: Restart with Fresh Sandbox
  ───────────────────────────────────────
    /resume-feature 47 --new-sandbox --reset-progress

  Ignores corrupted state, starts fresh
  Progress: 0% (full restart)
  Use if: Corruption is severe

  Option 2: Restore from Snapshot
  ───────────────────────────────────────
    /resume-feature 47 --snapshot snap_oauth_debug_20250118

  Uses snapshot instead of corrupted state
  Progress: State at snapshot time (68%)
  Use if: Recent snapshot available

  Option 3: Manual State Repair
  ───────────────────────────────────────
    Edit: .e2b/orchestration/paused/agent_47.json
    Fix JSON syntax and required fields
    Then: /resume-feature 47

  Use if: Corruption is minor and repairable

Recommendation: Option 2 if snapshot available, otherwise Option 1
```

### Error 4: Capacity Limit Reached

```
❌ Error: Cannot resume - capacity limit reached

Issue: #47 - Add OAuth Integration
Reason: Maximum concurrent agents reached

Current Orchestration State:
  Strategy: balanced
  Max Agents: 5
  Active Agents: 5 (#42, #45, #49, #50, #51)
  Available Slots: 0

Cannot resume - all slots occupied.

Recovery Options:

  Option 1: Queue for Next Available Slot
  ───────────────────────────────────────
    Feature will auto-resume when slot available

  Estimated Wait: ~15-30 minutes
  Position in Queue: 1st

  Accept: Press Enter to queue

  Option 2: Pause Another Feature
  ───────────────────────────────────────
    /pause-feature 51
    /resume-feature 47

  Manually free up a slot for #47

  Option 3: Increase Capacity (Change Strategy)
  ───────────────────────────────────────
    /set-orchestration-strategy aggressive
    /resume-feature 47

  Increases max agents: 5 → 10
  Cost Impact: +$0.04/hour per agent

  Option 4: Wait for Completion
  ───────────────────────────────────────
    Wait for an active agent to complete
    Estimated: Agent #42 ~10 minutes

    Then: /resume-feature 47

Recommendation: Option 1 for automatic resume,
                Option 2 if you control another feature
```

### Error 5: Git Worktree Conflict

```
❌ Error: Git worktree conflict detected

Issue: #47 - Add OAuth Integration
Branch: feature/oauth-integration
Worktree Path: /workspace

Conflict:
  Another process has modified the git worktree
  Uncommitted changes detected: 12 files
  Branch diverged from remote: +3 -2 commits

Cannot safely resume without resolving conflicts.

Git Status:
  Modified Files: 12
    src/auth/oauth.ts
    src/auth/oauth.test.ts
    package.json
    ... (9 more)

  Local Commits: 3 ahead, 2 behind remote
  Merge Required: Yes

Recovery Options:

  Option 1: Stash Changes and Resume
  ───────────────────────────────────────
    /sandbox-exec sbx_ghi789jkl "git stash"
    /resume-feature 47

  Stashes uncommitted changes
  Safe: Changes preserved in stash

  Option 2: Reset to Clean State
  ───────────────────────────────────────
    /sandbox-exec sbx_ghi789jkl "git reset --hard HEAD"
    /resume-feature 47

  ⚠️ Discards uncommitted changes
  Use if: Changes are unwanted

  Option 3: Resume with New Sandbox
  ───────────────────────────────────────
    /resume-feature 47 --new-sandbox

  Creates clean sandbox, avoids conflicts
  Progress: Restored from checkpoint

Recommendation: Option 1 to preserve changes,
                Option 3 for clean start
```

### Error 6: Health Check Failed

```
❌ Error: Sandbox health check failed

Issue: #47 - Add OAuth Integration
Sandbox: sbx_ghi789jkl

Health Check Results:
  ✓ Sandbox is running
  ✓ Network connectivity
  ✗ Filesystem errors detected
  ✗ Node.js environment broken
  ✓ Git repository intact

Critical Issues:
  1. /workspace/node_modules corrupted
     Error: ENOENT multiple missing files

  2. Node.js binary not found
     Path: /usr/bin/node
     Expected: v18.17.0
     Actual: Not found

Cannot resume with failed health checks.

Recovery Options:

  Option 1: Auto-Repair and Resume
  ───────────────────────────────────────
    /sandbox-exec sbx_ghi789jkl "npm install"
    /resume-feature 47

  Attempts to repair automatically
  Duration: ~2-3 minutes
  Success Rate: High for npm issues

  Option 2: Force Resume (Ignore Health)
  ───────────────────────────────────────
    /resume-feature 47 --force

  Resumes despite health failures
  ⚠️ May cause runtime errors

  Option 3: New Sandbox
  ───────────────────────────────────────
    /resume-feature 47 --new-sandbox

  Creates fresh, healthy sandbox
  Duration: ~3-5 minutes
  Guaranteed clean state

Recommendation: Try Option 1, fallback to Option 3
```

### Error 7: No Active Orchestration

```
❌ Error: No active orchestration session

Issue: #47
Reason: Cannot resume feature without active orchestration

State Found:
  Paused State: Yes
  File: .e2b/orchestration/paused/agent_47.json
  Valid: Yes

However, there is no active orchestration session to resume into.

Available Actions:

  Option 1: Resume Orchestration First
  ───────────────────────────────────────
    /resume-orchestration
    (Feature #47 will auto-resume with session)

  Resumes entire orchestration session
  Includes: All paused features

  Option 2: Start New Orchestration
  ───────────────────────────────────────
    /parallel-implement-features #47

  Starts fresh orchestration with just #47
  Previous state: Ignored

  Option 3: View Paused Sessions
  ───────────────────────────────────────
    ls .e2b/orchestration/sessions/

  Lists all paused orchestration sessions
  Then: /resume-orchestration --session <id>

Recommendation: Option 1 to resume full session
```

### Error 8: Dependency Not Ready

```
❌ Error: Cannot resume - dependency not ready

Issue: #49 - Email Notifications
Depends On: #47 - OAuth Integration
Blocker Status: Still in progress

Dependency Details:
  Blocked By: #47 (active, 85% complete)
  Reason: Email service requires OAuth tokens from #47
  Estimated Completion: ~15 minutes

Cannot resume #49 until #47 completes.

Current State:
  #47: Active (Creating PR, 85% done)
  #49: Paused (Blocked by #47)

Recovery Options:

  Option 1: Wait for Dependency
  ───────────────────────────────────────
    Wait ~15 minutes for #47 to complete
    Then: /resume-feature 49

  Note: Can auto-resume when ready:
    /resume-feature 49 --wait-for-dependencies

  Option 2: Resume Without Dependency (Force)
  ───────────────────────────────────────
    /resume-feature 49 --force

  ⚠️ Warning: Will likely fail without OAuth
  Use if: Dependency actually not needed

  Option 3: Remove Dependency
  ───────────────────────────────────────
    Update feature #49 to not require #47
    Then: /resume-feature 49

Recommendation: Option 1 - wait for dependency to complete
```

## Integration

### Integration with Orchestration System
- Validates orchestration session is active
- Checks capacity limits before resuming
- Adds agent to active pool
- Updates orchestration state
- Logs resume event to event system

### Integration with Sandbox Management
- Verifies sandbox health before resume
- Reconnects to existing sandbox or provisions new one
- Restores sandbox from snapshot if requested
- Validates resource availability
- Updates sandbox registry

### Integration with State Persistence
- Loads agent state from `.bumba/orchestration/paused/agent_<issue>.json`
- Validates state file integrity
- Restores progress checkpoints
- Applies environment variables
- Resumes from last successful operation

### Integration with Git Worktree
- Validates git worktree integrity
- Checks for uncommitted changes
- Verifies branch sync with remote
- Handles merge conflicts
- Restores working directory state

### Integration with Resource Manager
- Checks resource availability
- Allocates CPU and memory
- Validates disk space
- Updates resource reservations
- Monitors resource usage

## Use Cases

### Use Case 1: Resume After Fix
**Scenario**: Fixed OAuth test configuration; ready to continue feature #47.

**Command**:
```bash
/resume-feature 47
```

**Result**: Feature resumes from Create PR phase with fixed tests.

### Use Case 2: Resume with Fresh Environment
**Scenario**: Sandbox environment corrupted; need clean slate.

**Command**:
```bash
/resume-feature 47 --new-sandbox
```

**Result**: New sandbox created, state restored, work continues from checkpoint.

### Use Case 3: Resume from Debugging Snapshot
**Scenario**: Created snapshot while debugging; want to resume from that exact state.

**Command**:
```bash
/resume-feature 47 --snapshot snap_oauth_debug_20250118
```

**Result**: Sandbox restored from snapshot, resume from snapshot point.

### Use Case 4: Batch Resume After Pause
**Scenario**: Paused multiple features for maintenance; now ready to resume all.

**Command**:
```bash
/resume-feature 47 49 51
```

**Result**: All three features resume (capacity permitting).

### Use Case 5: Urgent Priority Resume
**Scenario**: Paused feature now urgent; need immediate attention.

**Command**:
```bash
/resume-feature 47 --priority urgent
```

**Result**: Feature queued with urgent priority, resumes immediately when slot available.

## Performance Considerations

### Resume Speed
- State validation: <1 second
- Sandbox health check: 2-5 seconds
- State restoration: 1-3 seconds
- New sandbox creation: 3-5 minutes
- Snapshot restoration: 2-4 minutes

### Resource Impact
- Resumed agent: Standard resource allocation
- Health checks: Minimal overhead
- State loading: <100ms

### Recovery Time
- Simple resume: 5-10 seconds
- Resume with health issues: 2-5 minutes
- Resume with new sandbox: 3-5 minutes
- Resume from snapshot: 2-4 minutes

## Notes

- **State Preservation**: Agent state always preserved during pause
- **Health Checks**: Sandbox verified before resume (skip with `--skip-health-check`)
- **Flexible Resume**: Can reuse sandbox, create new, or restore snapshot
- **Capacity Aware**: Respects orchestration capacity limits
- **Priority Support**: Can override priority for urgent work
- **Batch Resume**: Can resume multiple features simultaneously
- **Dependency Aware**: Checks feature dependencies before resume
- **Git Safe**: Validates git state and handles conflicts
- **Progress Continuity**: Resumes from exact checkpoint
- **Event Logged**: All resumes logged with timestamp and method
- **Force Option**: Can force resume despite warnings (use cautiously)
- **Auto-Queue**: Queues automatically if capacity exceeded
