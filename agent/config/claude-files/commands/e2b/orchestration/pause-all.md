---
name: pause-all
description: Pause all orchestration
---

# /pause-orchestration Command

Pauses all active orchestration, suspending all running agents while preserving complete state. Useful for emergencies, maintenance windows, resource management, or when you need to temporarily halt all automated work.

## Usage

```
/pause-orchestration [options]
```

## Parameters

- `--reason <reason>` (optional): Reason for pausing - logged for audit trail
- `--graceful` (optional): Wait for current operations to complete - default: false
- `--timeout <seconds>` (optional): Maximum wait time for graceful pause - default: 60
- `--save-snapshots` (optional): Create sandbox snapshots before pausing - default: false
- `--force` (optional): Force pause even if operations are critical - default: false

## Workflow

### Step 1: Orchestration Analysis

```
⏸️  Pause Orchestration Request
═══════════════════════════════════════════════

Analyzing active orchestration...
  Session ID: orch_xyz789abc
  Strategy: balanced
  Started: 2025-01-18 08:30:15 UTC
  Duration: 2h 15m
  Active Agents: 5
  Queued Features: 3

Agent Status:
  #42: Running (sandbox: sbx_abc123, uptime: 2h 10m)
  #45: Running (sandbox: sbx_def456, uptime: 1h 55m)
  #47: Running (sandbox: sbx_ghi789, uptime: 1h 40m)
  #49: Running (sandbox: sbx_jkl012, uptime: 1h 25m)
  #50: Running (sandbox: sbx_mno345, uptime: 1h 10m)

Current Operations:
  #42: Building project (75% complete)
  #45: Running tests (50% complete)
  #47: Idle (waiting for dependencies)
  #49: Syncing code
  #50: Creating pull request

Reason: Emergency maintenance
Pause Mode: Immediate (non-graceful)

───────────────────────────────────────────────
```

### Step 2: State Preservation

```
Saving orchestrator state...
  ✓ Orchestration metadata saved
  ✓ Agent states captured
  ✓ Queue state preserved
  ✓ Resource allocations recorded
  ✓ Event log checkpointed

State file: .claude/config/orchestrator-state-20250118-103000.json

Capturing agent contexts...
  Agent #42: Context saved (42 files, 187 events)
  Agent #45: Context saved (35 files, 142 events)
  Agent #47: Context saved (28 files, 98 events)
  Agent #49: Context saved (31 files, 115 events)
  Agent #50: Context saved (29 files, 103 events)

───────────────────────────────────────────────
```

### Step 3: Agent Suspension

```
Pausing agents...
  Agent #42 (Issue #42 - Authentication)
    ⟳ Interrupting build operation...
    ✓ Build paused at 75%
    ✓ Sandbox sbx_abc123 suspended
    ✓ State saved

  Agent #45 (Issue #45 - Payment Integration)
    ⟳ Interrupting test execution...
    ✓ Tests paused at 50%
    ✓ Sandbox sbx_def456 suspended
    ✓ State saved

  Agent #47 (Issue #47 - Data Migration)
    ✓ Agent already idle
    ✓ Sandbox sbx_ghi789 suspended
    ✓ State saved

  Agent #49 (Issue #49 - UI Redesign)
    ⟳ Waiting for code sync to complete...
    ✓ Sync completed
    ✓ Sandbox sbx_jkl012 suspended
    ✓ State saved

  Agent #50 (Issue #50 - API Refactor)
    ⟳ Finishing PR creation...
    ✓ PR created: #127
    ✓ Sandbox sbx_mno345 suspended
    ✓ State saved

All agents paused successfully.

───────────────────────────────────────────────
```

### Step 4: Pause Confirmation

```
✅ Orchestration Paused Successfully
═══════════════════════════════════════════════

Pause Summary:
  Session: orch_xyz789abc
  Paused At: 2025-01-18 10:30:00 UTC
  Duration Before Pause: 2h 15m
  Reason: Emergency maintenance

Agents Suspended: 5
  #42: Build paused at 75%
  #45: Tests paused at 50%
  #47: Idle (waiting for dependencies)
  #49: Code synced
  #50: PR created (#127)

Sandboxes Preserved: 5
  All sandboxes remain running but suspended
  Resource usage: ~$0.08/hour while paused

State Saved To:
  .claude/config/orchestrator-state-20250118-103000.json

Queued Features: 3
  #51: Queued (not started)
  #52: Queued (not started)
  #53: Queued (not started)

Resume Options:
  Resume all agents:
    /resume-orchestration

  Resume with modifications:
    /resume-orchestration --strategy aggressive

  Resume specific agents:
    /resume-feature #42
    /resume-feature #45

  View detailed state:
    /orchestrator-status

Estimated Resume Time: <30 seconds
```

## Examples

### Example 1: Simple Pause
```
/pause-orchestration
```

**Use Case**: Immediately pause all orchestration without waiting.

**Output**:
```
⏸️  Pause Orchestration Request
═══════════════════════════════════════════════

Analyzing active orchestration...
  Active Agents: 5

Pausing agents...
  ✓ All 5 agents paused

✅ Orchestration Paused
Resume with: /resume-orchestration
```

### Example 2: Pause with Reason
```
/pause-orchestration --reason "Emergency hotfix deployment"
```

**Use Case**: Pause with audit trail for why the pause occurred.

**Output**:
```
⏸️  Pause Orchestration Request
═══════════════════════════════════════════════

Reason: Emergency hotfix deployment
Active Agents: 5

Saving state with reason...
  ✓ Reason logged to audit trail

Pausing agents...
  ✓ All 5 agents paused

✅ Orchestration Paused
Reason logged for compliance/audit
```

### Example 3: Graceful Pause
```
/pause-orchestration --graceful --timeout 120
```

**Use Case**: Allow in-progress operations to complete before pausing.

**Output**:
```
⏸️  Pause Orchestration Request
═══════════════════════════════════════════════

Mode: Graceful pause
Timeout: 120 seconds

Waiting for operations to complete...
  Agent #42: Building... (estimated 45s remaining)
  Agent #45: Testing... (estimated 30s remaining)
  Agent #50: Creating PR... (estimated 10s remaining)

Progress:
  [00:10] Agent #50 completed PR creation
  [00:35] Agent #45 completed tests
  [00:48] Agent #42 completed build

All operations completed gracefully.

Pausing agents...
  ✓ All 5 agents paused

✅ Orchestration Paused (Graceful)
Total wait time: 48 seconds
```

### Example 4: Pause with Snapshots
```
/pause-orchestration --save-snapshots
```

**Use Case**: Create sandbox snapshots before pausing for extra safety.

**Output**:
```
⏸️  Pause Orchestration Request
═══════════════════════════════════════════════

Creating sandbox snapshots...
  Snapshot sbx_abc123: snap_abc_20250118_103000
  Snapshot sbx_def456: snap_def_20250118_103000
  Snapshot sbx_ghi789: snap_ghi_20250118_103000
  Snapshot sbx_jkl012: snap_jkl_20250118_103000
  Snapshot sbx_mno345: snap_mno_20250118_103000

All snapshots created successfully.

Pausing agents...
  ✓ All 5 agents paused

✅ Orchestration Paused
Snapshots available for restore if needed
```

### Example 5: Force Pause Critical Operations
```
/pause-orchestration --force
```

**Use Case**: Force pause even if agents are performing critical operations.

**Output**:
```
⏸️  Pause Orchestration Request
═══════════════════════════════════════════════

⚠️  Force mode enabled
⚠️  Critical operations will be interrupted

Critical operations detected:
  Agent #42: Deploying to production
  Agent #45: Running database migration

Forcing pause...
  ⚠️ Agent #42 deployment interrupted
  ⚠️ Agent #45 migration interrupted
  ✓ All agents forcefully paused

✅ Orchestration Paused (Force)
⚠️  Manual verification required before resume
```

### Example 6: Pause During Low Activity
```
/pause-orchestration --graceful --timeout 300
```

**Use Case**: Pause when agents are between tasks or idle.

**Output**:
```
⏸️  Pause Orchestration Request
═══════════════════════════════════════════════

Mode: Graceful pause
Timeout: 300 seconds (5 minutes)

Current activity:
  Agent #42: Idle
  Agent #45: Idle
  Agent #47: Idle
  Agent #49: Waiting for CI
  Agent #50: Idle

All agents idle or waiting.
Pausing immediately...

✅ Orchestration Paused (Graceful)
No operations interrupted
```

## Common Pause Scenarios

### Scenario 1: Emergency Maintenance
```bash
# Pause everything immediately
/pause-orchestration --reason "Emergency database maintenance"

# Perform maintenance
# ...

# Resume when ready
/resume-orchestration
```

### Scenario 2: End of Work Day
```bash
# Graceful pause at end of day
/pause-orchestration --graceful --reason "End of work day"

# Create snapshots for safety
/pause-orchestration --save-snapshots

# Next day, resume
/resume-orchestration
```

### Scenario 3: Resource Constraints
```bash
# Pause to free up resources
/pause-orchestration --reason "High server load"

# Check status
/orchestrator-status

# Resume with different strategy
/resume-orchestration --strategy conservative
```

### Scenario 4: Priority Change
```bash
# Pause all current work
/pause-orchestration --graceful --reason "Priority shift"

# Cancel low-priority items
# Requeue with new priorities

# Resume with aggressive strategy for high priority
/resume-orchestration --strategy aggressive
```

## Error Handling

### Error 1: No Active Orchestration

```
⚠️  Warning: No active orchestration to pause

Orchestration Status:
  Session: None
  Active Agents: 0
  Queue: Empty

Current State:
  Last session: orch_xyz789abc
  Ended: 2025-01-18 09:15:23 UTC
  Reason: Completed

Nothing to pause.

Available Actions:
  View completed sessions:
    /orchestrator-status --history

  Start new orchestration:
    /parallel-implement-features #42 #45 #47

  View individual feature status:
    /show-status #42
```

### Error 2: Already Paused

```
⚠️  Warning: Orchestration already paused

Orchestration Status:
  Session: orch_xyz789abc
  Status: Paused
  Paused At: 2025-01-18 09:30:00 UTC
  Paused Duration: 1h 5m
  Reason: Emergency maintenance

Paused Agents: 5
  All agents suspended

Available Actions:
  Resume orchestration:
    /resume-orchestration

  View pause details:
    /orchestrator-status

  Resume specific agent:
    /resume-feature #42

  Cancel pause and restart:
    /resume-orchestration --force
```

### Error 3: Graceful Pause Timeout

```
❌ Error: Graceful pause timeout

Pause Request:
  Mode: Graceful
  Timeout: 60 seconds
  Elapsed: 60 seconds

Operations Still Running:
  Agent #42: Build in progress (estimated 2m remaining)
    Operation: npm run build
    Progress: 85%
    Started: 1h 15m ago

Timeout Actions Taken:
  ⟳ Attempted graceful shutdown
  ⚠️ Operation did not complete in time
  ✗ Graceful pause failed

Automatic Recovery Options:

  Option 1: Force Pause
  ───────────────────────────────────────
  Pause was automatically converted to force mode:
    ✓ Agent #42 forcefully paused
    ✓ Build interrupted at 85%

  Use caution when resuming - may need to restart build.

  Option 2: Extend Timeout and Retry
  ───────────────────────────────────────
  If you want to wait longer:
    /pause-orchestration --graceful --timeout 180

  Try with 3 minute timeout instead.

Manual Recovery Options:
  Resume and let build complete:
    /resume-orchestration
    Wait for build, then pause again

  Force pause now:
    /pause-orchestration --force

Recommendation: Option 1 (auto-converted to force pause) completed
```

### Error 4: State Save Failed

```
❌ Error: Failed to save orchestrator state

Save Operation:
  Target: .claude/config/orchestrator-state.json
  Error: EACCES (Permission denied)

Orchestration Status:
  Agents: Still running (not paused)
  Reason: Cannot pause without saving state
  Risk: Would lose session context

Automatic Recovery Actions:
  ⟳ Checking file permissions...
  ✗ File owned by root, current user cannot write
  ⟳ Attempting alternate location...
  ✓ Saved to: /tmp/orchestrator-state-20250118-103000.json

Manual Recovery Options:

  Option 1: Fix Permissions
  ───────────────────────────────────────
    sudo chown $(whoami) .claude/config/orchestrator-state.json

  Then retry:
    /pause-orchestration

  Option 2: Use Alternate State Directory
  ───────────────────────────────────────
  Configure alternate state directory:
    /config set orchestrator.stateDir /tmp/orchestration

  Then retry:
    /pause-orchestration

  Option 3: Continue with Temp State
  ───────────────────────────────────────
  State was saved to temp location.
  Orchestration can be paused now.

  ⚠️  Warning: Temp state may be lost on system restart

  Proceed with pause:
    /pause-orchestration --force

Recommendation: Option 1 (fix permissions) for persistent state
```

### Error 5: Sandbox Suspension Failed

```
❌ Error: Failed to suspend sandbox

Suspension Details:
  Agent: #42 (Authentication feature)
  Sandbox: sbx_abc123xyz
  Error: Sandbox not responding

Sandbox Status:
  Status: Running (unresponsive)
  Last Heartbeat: 5 minutes ago
  CPU: 95%
  Memory: 89%

Other Agents:
  ✓ Agent #45 paused successfully
  ✓ Agent #47 paused successfully
  ✗ Agent #42 suspension failed
  ⏳ Agent #49 waiting...
  ⏳ Agent #50 waiting...

Automatic Recovery Actions:
  ⟳ Attempting force suspend...
  ⟳ Sending SIGTERM to sandbox...
  ⚠️ Sandbox not responding to signals
  ⟳ Checking E2B API status...
  ✓ E2B API operational

Manual Recovery Options:

  Option 1: Force Terminate Sandbox
  ───────────────────────────────────────
    /sandbox-status sbx_abc123xyz --terminate

  Then continue pause:
    /pause-orchestration --force

  ⚠️  Warning: Agent #42 will need to restart from last checkpoint

  Option 2: Wait and Retry
  ───────────────────────────────────────
  Wait for sandbox to become responsive:
    [Wait 2-3 minutes]
    /pause-orchestration

  Option 3: Pause Other Agents Only
  ───────────────────────────────────────
  Pause all except #42:
    /pause-feature #45
    /pause-feature #47
    /pause-feature #49
    /pause-feature #50

  Then manually handle #42

  Option 4: Debug Sandbox
  ───────────────────────────────────────
  Investigate what's causing unresponsiveness:
    /sandbox-debug sbx_abc123xyz

  May reveal process using 95% CPU

Recommendation: Option 4 (debug) to understand issue, then Option 1 if needed
```

### Error 6: Insufficient Permissions

```
❌ Error: Insufficient permissions

Permission Check:
  User: developer
  Role: contributor
  Required: orchestrator-admin

Operation Denied:
  Action: Pause orchestration
  Reason: Only orchestration admins can pause all agents

Current Orchestration:
  Session: orch_xyz789abc
  Owner: senior-dev
  Active Agents: 5
  Strategy: aggressive

Your Agents:
  You own 2 of 5 active agents:
    #42: Authentication (you)
    #47: Data Migration (you)

Available Actions:

  Option 1: Pause Your Agents Only
  ───────────────────────────────────────
    /pause-feature #42
    /pause-feature #47

  You can pause agents you own.

  Option 2: Request Orchestration Admin
  ───────────────────────────────────────
  Contact orchestration owner or admin:
    senior-dev@company.com

  Request permission to pause orchestration.

  Option 3: Emergency Override (Admin Only)
  ───────────────────────────────────────
  For emergencies, contact system administrator
  to grant temporary orchestrator-admin role.

Recommendation: Option 1 (pause your agents) if urgent, otherwise Option 2
```

## State Preservation Details

### What Gets Saved

**Orchestration Metadata**:
- Session ID and creation timestamp
- Current strategy (balanced/aggressive/conservative)
- Pause timestamp and reason
- Resume count (if resumed before)
- Total duration before pause

**Agent States**:
- Agent ID and issue number
- Current operation and progress
- Sandbox ID and status
- Last checkpoint timestamp
- Event log position
- Resource usage stats

**Queue State**:
- Queued feature list
- Priority ordering
- Dependencies
- Estimated start times

**Resource Allocations**:
- Active sandboxes
- Resource reservations
- Cost tracking data

**Event Log**:
- Log checkpoint position
- Recent events buffer
- Critical events flag

### State File Format

```json
{
  "version": "1.0",
  "sessionId": "orch_xyz789abc",
  "pausedAt": "2025-01-18T10:30:00Z",
  "reason": "Emergency maintenance",
  "strategy": "balanced",
  "agents": [
    {
      "agentId": 42,
      "issue": 42,
      "status": "paused",
      "sandbox": "sbx_abc123xyz",
      "operation": "build",
      "progress": 0.75,
      "checkpoint": "2025-01-18T10:29:45Z"
    }
  ],
  "queue": [51, 52, 53],
  "resources": {
    "sandboxes": 5,
    "costPerHour": 0.08
  },
  "eventLogPosition": 1247
}
```

## Integration

### Integration with Agent Management
- Communicates pause signal to all active agents
- Waits for agent acknowledgment (in graceful mode)
- Preserves agent context and state
- Updates agent status to "paused"

### Integration with Bumba Sandbox Sandboxes
- Does NOT terminate sandboxes (keeps them running)
- Suspends sandbox activity
- Preserves sandbox state for resume
- Continues to accrue sandbox costs (reduced activity)

### Integration with Event System
- Logs "orchestration.paused" event
- Records pause reason and timestamp
- Captures pre-pause state
- Enables audit trail for compliance

### Integration with Resource Manager
- Updates resource allocation status
- Maintains resource reservations
- Tracks paused resource costs
- Enables cost reporting during pause

### Integration with Resume Command
- State file enables `/resume-orchestration`
- Resume continues from exact pause point
- No data loss or duplicate work
- Seamless continuation

## Use Cases

### Use Case 1: Emergency Hotfix
**Scenario**: Critical production bug requires immediate attention; pause all feature work.

**Workflow**:
```bash
/pause-orchestration --reason "P0 production bug"
# Fix critical bug
# Deploy hotfix
/resume-orchestration
```

### Use Case 2: End of Sprint
**Scenario**: Sprint ends; want to pause all work until planning complete.

**Workflow**:
```bash
/pause-orchestration --graceful --reason "Sprint boundary"
# Sprint review and planning
# Adjust priorities if needed
/resume-orchestration --strategy balanced
```

### Use Case 3: Resource Constraints
**Scenario**: Server running low on resources; need to free up capacity.

**Workflow**:
```bash
/pause-orchestration --reason "High server load"
/cleanup-sandboxes --aggressive
# System recovers
/resume-orchestration --strategy conservative
```

### Use Case 4: Long Weekend
**Scenario**: Friday afternoon; want to pause all work for the weekend.

**Workflow**:
```bash
/pause-orchestration --save-snapshots --reason "Weekend pause"
# Weekend break
# Monday morning
/resume-orchestration
```

### Use Case 5: Strategy Change
**Scenario**: Current strategy not working well; want to change mid-flight.

**Workflow**:
```bash
/pause-orchestration --graceful
/set-orchestration-strategy conservative
/resume-orchestration
```

## Performance Considerations

### Pause Speed
- Immediate mode: <5 seconds for most orchestrations
- Graceful mode: Depends on operation completion (configurable timeout)
- Snapshot mode: Adds 10-30 seconds per sandbox

### Resume Impact
- Resume typically takes <30 seconds
- Agents continue from exact pause point
- No re-work or duplication
- Minimal warm-up time

### Resource Usage While Paused
- Sandboxes continue to run (reduced cost)
- Estimated: ~30% of active cost
- Can manually terminate sandboxes to reduce further
- State file is small (<100 KB typically)

## Security Considerations

### Permission Requirements
- Requires `orchestrator-admin` role
- Or ownership of orchestration session
- Individual agents can be paused by owner
- Audit log tracks all pause events

### State File Security
- Contains sensitive orchestration data
- Stored in `.claude/config/` (gitignored)
- Should not be committed to version control
- May contain API keys or credentials in context

### Force Pause Risks
- Can interrupt critical operations
- May leave systems in inconsistent state
- Use with caution
- Document reason in audit log

## Notes

- **Preserves All State**: Complete orchestration state saved for resume
- **Sandboxes Keep Running**: Remain active but suspended (reduces cost slightly)
- **Graceful by Default**: Can wait for operations to complete with `--graceful`
- **Audit Trail**: All pauses logged with reason and timestamp
- **Resume Anytime**: Use `/resume-orchestration` to continue
- **No Data Loss**: Agents continue exactly where they left off
- **Cost Reduction**: Paused orchestration costs ~30% of active
- **Safety Feature**: Useful for emergencies, maintenance, or breaks
- **Snapshot Option**: Can create sandbox snapshots for extra safety
- **Individual Control**: Can pause specific agents with `/pause-feature`
