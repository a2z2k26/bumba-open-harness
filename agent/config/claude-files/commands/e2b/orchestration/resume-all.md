---
name: resume-all
description: Resume orchestration
---

# /resume-orchestration Command

Resumes paused orchestration, continuing all agents from their saved state. Agents pick up exactly where they left off with no data loss or duplicate work.

## Usage

```
/resume-orchestration [options]
```

## Parameters

- `--strategy <strategy>` (optional): Override saved strategy - options: `balanced`, `aggressive`, `conservative`
- `--verify-sandboxes` (optional): Verify all sandboxes are healthy before resuming - default: true
- `--selective <agent-ids>` (optional): Resume only specific agents (comma-separated) - e.g., `42,45,47`
- `--skip-queue` (optional): Don't resume queued features, only active agents - default: false
- `--force` (optional): Force resume even if sandboxes are unhealthy - default: false

## Workflow

### Step 1: State Loading and Validation

```
▶️  Resume Orchestration Request
═══════════════════════════════════════════════

Loading orchestrator state...
  State File: .claude/config/orchestrator-state-20250118-103000.json
  ✓ State file found
  ✓ State file valid

Paused Session Details:
  Session ID: orch_xyz789abc
  Paused At: 2025-01-18 10:30:00 UTC
  Pause Duration: 1h 45m
  Pause Reason: Emergency maintenance
  Strategy: balanced

Agent States:
  Agent #42: Paused (build at 75%)
  Agent #45: Paused (tests at 50%)
  Agent #47: Paused (idle, waiting)
  Agent #49: Paused (code synced)
  Agent #50: Paused (PR created)

Queued Features: 3
  #51, #52, #53

───────────────────────────────────────────────
```

### Step 2: Sandbox Health Verification

```
Verifying sandbox health...
  Sandbox sbx_abc123 (Agent #42)
    ✓ Status: Running
    ✓ Uptime: 3h 55m
    ✓ Resources: CPU 15%, Memory 42%
    ✓ Network: Responsive
    ✓ Disk: 67% used

  Sandbox sbx_def456 (Agent #45)
    ✓ Status: Running
    ✓ Uptime: 3h 40m
    ✓ Resources: CPU 8%, Memory 38%
    ✓ Network: Responsive
    ✓ Disk: 54% used

  Sandbox sbx_ghi789 (Agent #47)
    ✓ Status: Running
    ✓ Uptime: 3h 25m
    ✓ Resources: CPU 2%, Memory 31%
    ✓ Network: Responsive
    ✓ Disk: 48% used

  Sandbox sbx_jkl012 (Agent #49)
    ✓ Status: Running
    ✓ Uptime: 3h 10m
    ✓ Resources: CPU 5%, Memory 35%
    ✓ Network: Responsive
    ✓ Disk: 51% used

  Sandbox sbx_mno345 (Agent #50)
    ✓ Status: Running
    ✓ Uptime: 2h 55m
    ✓ Resources: CPU 3%, Memory 29%
    ✓ Network: Responsive
    ✓ Disk: 45% used

All sandboxes healthy and ready to resume.

───────────────────────────────────────────────
```

### Step 3: Agent Resumption

```
Resuming agents...
  Agent #42 (Issue #42 - Authentication)
    ⟳ Restoring context (42 files, 187 events)...
    ⟳ Reconnecting to sandbox sbx_abc123...
    ⟳ Resuming build from 75%...
    ✓ Agent resumed successfully
    ➜ Status: Building (resuming from checkpoint)

  Agent #45 (Issue #45 - Payment Integration)
    ⟳ Restoring context (35 files, 142 events)...
    ⟳ Reconnecting to sandbox sbx_def456...
    ⟳ Resuming tests from 50%...
    ✓ Agent resumed successfully
    ➜ Status: Testing (resuming from checkpoint)

  Agent #47 (Issue #47 - Data Migration)
    ⟳ Restoring context (28 files, 98 events)...
    ⟳ Reconnecting to sandbox sbx_ghi789...
    ⟳ Checking dependencies...
    ✓ Agent resumed successfully
    ➜ Status: Idle (waiting for dependencies)

  Agent #49 (Issue #49 - UI Redesign)
    ⟳ Restoring context (31 files, 115 events)...
    ⟳ Reconnecting to sandbox sbx_jkl012...
    ✓ Agent resumed successfully
    ➜ Status: Ready for next task

  Agent #50 (Issue #50 - API Refactor)
    ⟳ Restoring context (29 files, 103 events)...
    ⟳ Reconnecting to sandbox sbx_mno345...
    ⟳ Verifying PR #127 was created...
    ✓ Agent resumed successfully
    ➜ Status: Ready for next task

All agents resumed successfully.

───────────────────────────────────────────────
```

### Step 4: Resume Confirmation

```
✅ Orchestration Resumed Successfully
═══════════════════════════════════════════════

Resume Summary:
  Session: orch_xyz789abc
  Resumed At: 2025-01-18 12:15:00 UTC
  Total Pause Duration: 1h 45m
  Strategy: balanced (unchanged)

Active Agents: 5
  #42: Building (resumed from 75%)
  #45: Testing (resumed from 50%)
  #47: Idle (waiting for dependencies)
  #49: Ready for next task
  #50: Ready for next task

Queued Features: 3
  #51: Queued (will start when slot available)
  #52: Queued (will start when slot available)
  #53: Queued (will start when slot available)

Monitoring:
  ✓ Real-time monitoring enabled
  ✓ Event logging active
  ✓ Cost tracking resumed
  ✓ Auto-spawn enabled (max 10 agents)

Resource Usage:
  Active Sandboxes: 5
  Estimated Cost: ~$0.25/hour
  CPU Utilization: 33%
  Memory Utilization: 35%

Next Actions:
  View orchestrator status:
    /orchestrator-status

  View real-time events:
    /orchestrator-events --follow

  Adjust strategy if needed:
    /set-orchestration-strategy aggressive

  Pause again if needed:
    /pause-orchestration
```

## Examples

### Example 1: Simple Resume
```
/resume-orchestration
```

**Use Case**: Resume orchestration with original settings.

**Output**:
```
▶️  Resume Orchestration Request
═══════════════════════════════════════════════

Loading state...
  ✓ State loaded: orch_xyz789abc

Verifying sandboxes...
  ✓ All 5 sandboxes healthy

Resuming agents...
  ✓ All 5 agents resumed

✅ Orchestration Resumed
Strategy: balanced
Agents: 5 active, 3 queued
```

### Example 2: Resume with Strategy Change
```
/resume-orchestration --strategy aggressive
```

**Use Case**: Resume but switch to aggressive strategy for faster completion.

**Output**:
```
▶️  Resume Orchestration Request
═══════════════════════════════════════════════

Loading state...
  ✓ State loaded: orch_xyz789abc
  Previous Strategy: balanced
  New Strategy: aggressive

Strategy Changes:
  ⚙️ Max Agents: 5 → 10
  ⚙️ Auto-spawn: enabled → enabled
  ⚙️ Parallelism: moderate → high

Resuming agents...
  ✓ All 5 agents resumed

Auto-spawning queued features...
  ⟳ Starting agent for #51...
  ⟳ Starting agent for #52...
  ⟳ Starting agent for #53...
  ✓ 3 additional agents started

✅ Orchestration Resumed (Aggressive)
Active Agents: 8
Strategy: aggressive
```

### Example 3: Selective Resume
```
/resume-orchestration --selective 42,45
```

**Use Case**: Resume only specific agents, leave others paused.

**Output**:
```
▶️  Resume Orchestration Request (Selective)
═══════════════════════════════════════════════

Loading state...
  ✓ State loaded: orch_xyz789abc

Selected Agents: 2
  Agent #42: Authentication
  Agent #45: Payment Integration

Resuming selected agents...
  ✓ Agent #42 resumed
  ✓ Agent #45 resumed

Remaining Paused: 3
  Agent #47: Data Migration (still paused)
  Agent #49: UI Redesign (still paused)
  Agent #50: API Refactor (still paused)

✅ Selective Resume Complete
Active: 2 agents
Paused: 3 agents
```

### Example 4: Resume Without Queue
```
/resume-orchestration --skip-queue
```

**Use Case**: Resume active agents but don't start queued features yet.

**Output**:
```
▶️  Resume Orchestration Request
═══════════════════════════════════════════════

Loading state...
  ✓ State loaded: orch_xyz789abc
  Previously Active: 5 agents
  Previously Queued: 3 features

Resuming active agents...
  ✓ All 5 agents resumed

Queued Features: 3
  #51: Queued (not started, --skip-queue)
  #52: Queued (not started, --skip-queue)
  #53: Queued (not started, --skip-queue)

✅ Orchestration Resumed (Active Only)
Active Agents: 5
Queued: 3 (will not auto-start)

To start queued features:
  /implement-feature #51 --mode orchestrated
```

### Example 5: Force Resume with Unhealthy Sandboxes
```
/resume-orchestration --force
```

**Use Case**: Force resume even if some sandboxes have issues.

**Output**:
```
▶️  Resume Orchestration Request (Force)
═══════════════════════════════════════════════

⚠️  Force mode enabled
⚠️  Sandbox health checks will be skipped

Loading state...
  ✓ State loaded: orch_xyz789abc

Sandbox Status:
  sbx_abc123: ✓ Healthy
  sbx_def456: ✓ Healthy
  sbx_ghi789: ⚠️ High CPU (95%)
  sbx_jkl012: ✓ Healthy
  sbx_mno345: ✓ Healthy

Resuming agents (forced)...
  ✓ Agent #42 resumed
  ✓ Agent #45 resumed
  ⚠️ Agent #47 resumed (sandbox unhealthy)
  ✓ Agent #49 resumed
  ✓ Agent #50 resumed

✅ Orchestration Resumed (Force)
⚠️  Agent #47 may experience issues
Monitor: /orchestrator-status
```

### Example 6: Resume with Verification
```
/resume-orchestration --verify-sandboxes
```

**Use Case**: Thoroughly verify all sandboxes before resuming.

**Output**:
```
▶️  Resume Orchestration Request
═══════════════════════════════════════════════

Loading state...
  ✓ State loaded: orch_xyz789abc

Running comprehensive sandbox verification...
  Sandbox sbx_abc123:
    ✓ Process health check
    ✓ Network connectivity
    ✓ Disk space (33% free)
    ✓ Memory available (58% free)
    ✓ File system integrity
    ✓ Git repository status

  [... verification for other sandboxes ...]

All sandboxes verified healthy.

Resuming agents...
  ✓ All 5 agents resumed

✅ Orchestration Resumed (Verified)
All systems nominal
```

## Common Resume Scenarios

### Scenario 1: Morning Resume After Overnight Pause
```bash
# Monday morning, resume weekend pause
/resume-orchestration --verify-sandboxes

# Check what happened overnight
/orchestrator-status

# Adjust if needed
/set-orchestration-strategy balanced
```

### Scenario 2: Resume After Emergency Maintenance
```bash
# Maintenance complete, resume work
/resume-orchestration --strategy aggressive

# Monitor for issues
/orchestrator-events --follow

# Verify all agents working
/orchestrator-status
```

### Scenario 3: Selective Resume for Priorities
```bash
# Resume only high-priority agents
/resume-orchestration --selective 42,45

# Let them complete
# Later resume the rest
/resume-feature #47
/resume-feature #49
/resume-feature #50
```

### Scenario 4: Resume with Resource Constraints
```bash
# Resume with conservative strategy
/resume-orchestration --strategy conservative --skip-queue

# Monitor resource usage
/cost-report --current

# Start queue gradually as resources allow
/implement-feature #51 --mode orchestrated
```

## Error Handling

### Error 1: No Paused Session

```
❌ Error: No paused orchestration to resume

Orchestration Status:
  Session: None
  Status: No saved state
  Last Session: orch_xyz789abc (completed 2 days ago)

State File:
  Searched: .claude/config/orchestrator-state*.json
  Found: None

Possible Causes:
  1. Orchestration was never paused
  2. State file was deleted or moved
  3. Orchestration completed and state was cleaned up
  4. Different working directory

Available Actions:

  Option 1: Start New Orchestration
  ───────────────────────────────────────
    /parallel-implement-features #42 #45 #47

  Start fresh orchestration session.

  Option 2: Check for State Files
  ───────────────────────────────────────
    ls -la .claude/config/orchestrator-state*.json

  Verify state file location.

  Option 3: Restore from Backup
  ───────────────────────────────────────
  If state file was accidentally deleted:
    cp .claude/config/backup/orchestrator-state*.json .claude/config/

  Option 4: View Completed Sessions
  ───────────────────────────────────────
    /orchestrator-status --history

  See past orchestration sessions.

Recommendation: Option 1 (start new) if no state file available
```

### Error 2: Sandbox Terminated

```
❌ Error: Sandbox no longer exists

Resume Attempt:
  Session: orch_xyz789abc
  Agents to Resume: 5

Sandbox Status:
  sbx_abc123 (Agent #42): ✗ Terminated
  sbx_def456 (Agent #45): ✓ Running
  sbx_ghi789 (Agent #47): ✓ Running
  sbx_jkl012 (Agent #49): ✗ Terminated
  sbx_mno345 (Agent #50): ✓ Running

Terminated Sandboxes: 2
  sbx_abc123: Terminated 45 minutes ago (timeout)
  sbx_jkl012: Terminated 30 minutes ago (timeout)

Automatic Recovery Actions:
  ⟳ Checking for snapshots...
  ✗ No snapshots found
  ⟳ Checking worktree sync...
  ✓ Agent #42 synced 50 minutes ago
  ✓ Agent #49 synced 35 minutes ago

Manual Recovery Options:

  Option 1: Recreate Sandboxes
  ───────────────────────────────────────
  Recreate terminated sandboxes:
    /implement-feature #42 --mode sandbox
    /implement-feature #49 --mode sandbox

  Then resume orchestration:
    /resume-orchestration

  ⚠️  Agents will restart from last worktree sync

  Option 2: Resume Partial Orchestration
  ───────────────────────────────────────
  Resume only agents with running sandboxes:
    /resume-orchestration --selective 45,47,50

  Handle #42 and #49 separately.

  Option 3: Restore from Snapshots
  ───────────────────────────────────────
  If snapshots exist:
    /sandbox-restore sbx_abc123 --snapshot snap_abc_*
    /sandbox-restore sbx_jkl012 --snapshot snap_jkl_*

  Then resume:
    /resume-orchestration

  Option 4: Start Fresh
  ───────────────────────────────────────
  Cancel pause and start new orchestration:
    /parallel-implement-features #42 #45 #47 #49 #50

Recommendation: Option 1 (recreate sandboxes) if recent sync, otherwise Option 4
```

### Error 3: State File Corrupted

```
❌ Error: Corrupted orchestrator state

State File: .claude/config/orchestrator-state-20250118-103000.json
Error: JSON parse error at line 247
Details: Unexpected token in JSON at position 12847

File Information:
  Size: 13.2 KB
  Modified: 2025-01-18 10:30:00 UTC
  Readable: Yes
  Valid JSON: No

Automatic Recovery Actions:
  ⟳ Attempting to repair JSON...
  ✗ Auto-repair failed
  ⟳ Checking for backup...
  ✓ Backup found: orchestrator-state-20250118-103000.json.backup

Manual Recovery Options:

  Option 1: Use Backup State
  ───────────────────────────────────────
    cp .claude/config/orchestrator-state-20250118-103000.json.backup \
       .claude/config/orchestrator-state-20250118-103000.json

  Then retry:
    /resume-orchestration

  Option 2: Manually Repair JSON
  ───────────────────────────────────────
  Edit state file to fix JSON:
    vim .claude/config/orchestrator-state-20250118-103000.json

  Look for syntax errors around line 247.

  Option 3: Partial State Recovery
  ───────────────────────────────────────
  Extract partial state and reconstruct:
    [Manual process - contact support]

  Option 4: Resume Individual Agents
  ───────────────────────────────────────
  If you remember which agents were paused:
    /resume-feature #42
    /resume-feature #45
    /resume-feature #47

Recommendation: Option 1 (use backup) if backup exists
```

### Error 4: Strategy Conflict

```
❌ Error: Strategy conflict detected

Resume Request:
  Requested Strategy: aggressive
  Saved Strategy: balanced

Conflict Analysis:
  Current Active Agents: 5
  Aggressive Strategy Limit: 10
  Queued Features: 3

Resource Check:
  ⚠️ Current resource usage: 75%
  ⚠️ Aggressive strategy would increase to ~95%
  ⚠️ May exceed resource limits

Automatic Recovery Actions:
  ⟳ Calculating safe maximum...
  ✓ Can safely add 2 more agents (not 5)

Manual Recovery Options:

  Option 1: Resume with Balanced Strategy
  ───────────────────────────────────────
    /resume-orchestration

  Keep original balanced strategy.

  Option 2: Resume with Conservative Strategy
  ───────────────────────────────────────
    /resume-orchestration --strategy conservative

  Use even more conservative approach.

  Option 3: Resume and Scale Gradually
  ───────────────────────────────────────
    /resume-orchestration --skip-queue
    [Monitor resources]
    /set-orchestration-strategy aggressive

  Start conservative, scale up later.

  Option 4: Clean Up Resources First
  ───────────────────────────────────────
    /cleanup-sandboxes --aggressive
    /resume-orchestration --strategy aggressive

  Free resources, then resume aggressively.

Recommendation: Option 3 (gradual scale) for safety
```

### Error 5: Agent Context Lost

```
❌ Error: Agent context data missing

Resume Attempt:
  Session: orch_xyz789abc
  Agents: 5

Context Status:
  Agent #42: ✓ Context available (42 files)
  Agent #45: ✗ Context missing
  Agent #47: ✓ Context available (28 files)
  Agent #49: ✓ Context available (31 files)
  Agent #50: ✓ Context available (29 files)

Missing Context:
  Agent #45: Payment Integration
    Last Known State: Tests at 50%
    Context File: Missing or corrupted
    Last Sync: 55 minutes ago

Automatic Recovery Actions:
  ⟳ Checking worktree for recent state...
  ✓ Worktree has code from 55 minutes ago
  ⟳ Checking event log...
  ✓ Found 142 events for agent #45

Manual Recovery Options:

  Option 1: Resume with Partial Context
  ───────────────────────────────────────
  Agent #45 will restart from worktree state:
    /resume-orchestration --force

  ⚠️  Agent may redo some work from last 55 minutes

  Option 2: Resume Other Agents Only
  ───────────────────────────────────────
    /resume-orchestration --selective 42,47,49,50

  Handle agent #45 separately:
    /implement-feature #45 --mode sandbox

  Option 3: Reconstruct Context
  ───────────────────────────────────────
  Use event log to rebuild context:
    [Advanced - requires manual intervention]

  Option 4: Start Agent Fresh
  ───────────────────────────────────────
  Cancel pause for #45 and restart:
    /implement-feature #45 --mode sandbox --force

Recommendation: Option 1 (partial context) if <1 hour of work lost
```

### Error 6: Permission Denied

```
❌ Error: Insufficient permissions to resume

Permission Check:
  User: developer
  Role: contributor
  Required: orchestrator-admin

Orchestration Session:
  Session: orch_xyz789abc
  Owner: senior-dev
  Paused By: senior-dev (orchestrator-admin)
  Paused At: 2025-01-18 10:30:00 UTC

Access Control:
  ✗ Cannot resume orchestration owned by others
  ✓ Can resume your own agents only

Your Agents in Session:
  Agent #42: Authentication (you)
  Agent #47: Data Migration (you)

Available Actions:

  Option 1: Resume Your Agents
  ───────────────────────────────────────
    /resume-feature #42
    /resume-feature #47

  You can resume agents you own.

  Option 2: Request Permission
  ───────────────────────────────────────
  Contact orchestration owner:
    senior-dev@company.com

  Request permission to resume full orchestration.

  Option 3: Wait for Owner
  ───────────────────────────────────────
  Wait for owner to resume orchestration:
    [Owner will run: /resume-orchestration]

Recommendation: Option 1 (resume your agents) if urgent
```

## Integration

### Integration with Agent Management
- Loads saved agent states from pause
- Restores agent context and progress
- Reconnects agents to sandboxes
- Updates agent status to "running"

### Integration with Bumba Sandbox Sandboxes
- Verifies sandboxes still exist and are running
- Reconnects to sandbox sessions
- Validates sandbox health before resuming
- Handles sandbox recreation if needed

### Integration with Event System
- Logs "orchestration.resumed" event
- Continues event logging from checkpoint
- Replays missed events if any
- Maintains event continuity

### Integration with Resource Manager
- Validates resource availability
- Updates resource allocations
- Resumes cost tracking
- Adjusts for strategy changes

### Integration with Queue Management
- Loads queued feature list
- Continues auto-spawn if enabled
- Respects dependency ordering
- Starts queued features based on strategy

## Use Cases

### Use Case 1: Resume After Overnight Pause
**Scenario**: Paused work on Friday evening, resuming Monday morning.

**Workflow**:
```bash
# Monday morning
/resume-orchestration --verify-sandboxes

# Check progress
/orchestrator-status

# Adjust if needed
/set-orchestration-strategy balanced
```

### Use Case 2: Resume After Emergency
**Scenario**: Paused for emergency hotfix, now resuming normal work.

**Workflow**:
```bash
# Emergency resolved
/resume-orchestration

# Monitor for stability
/orchestrator-events --follow

# Ensure everything running smoothly
/show-status --all
```

### Use Case 3: Resume with Priority Changes
**Scenario**: Business priorities changed during pause; need to adjust.

**Workflow**:
```bash
# Resume only high-priority agents
/resume-orchestration --selective 42,45 --strategy aggressive

# Cancel low-priority work
/cancel-feature #47

# Requeue with new priority
/implement-feature #51 --mode orchestrated --priority high
```

### Use Case 4: Resume After Resource Cleanup
**Scenario**: Paused due to resource constraints, cleaned up, now resuming.

**Workflow**:
```bash
# Clean up first
/cleanup-sandboxes --aggressive

# Verify resources available
/cost-report --current

# Resume conservatively
/resume-orchestration --strategy conservative --skip-queue
```

### Use Case 5: Partial Resume for Testing
**Scenario**: Want to test resume functionality with subset of agents.

**Workflow**:
```bash
# Resume one agent
/resume-orchestration --selective 42

# Verify it works
/show-status #42

# Resume the rest
/resume-orchestration --selective 45,47,49,50
```

## Performance Considerations

### Resume Speed
- State loading: <1 second
- Sandbox verification: ~2 seconds per sandbox
- Agent reconnection: ~5 seconds per agent
- Total resume time: Usually <30 seconds

### Context Restoration
- Agent context restored from saved state
- Event log replayed if gaps exist
- File system state from sandbox (not re-synced)
- Minimal overhead for state restoration

### Resource Impact
- Resume uses same resources as before pause
- Strategy changes affect resource usage
- Auto-spawn may increase resource usage
- Monitor with `/orchestrator-status`

## Security Considerations

### Permission Requirements
- Requires `orchestrator-admin` role
- Or ownership of orchestration session
- Individual agents can be resumed by owner
- Resume logged to audit trail

### State File Integrity
- State file validated before resume
- Checksums verified if available
- Backup state used if primary corrupted
- Malformed state safely rejected

### Sandbox Security
- Sandbox health verified before resume
- Network connectivity checked
- File system integrity validated
- Compromised sandboxes detected and flagged

## Notes

- **Exact Resume**: Agents continue from exact pause point
- **No Data Loss**: All progress and context preserved
- **Sandbox Verification**: Health checks ensure safe resume
- **Strategy Override**: Can change strategy on resume
- **Selective Resume**: Can resume specific agents only
- **Queue Control**: Can skip queued features if needed
- **Force Mode**: Can force resume despite warnings
- **Fast Resume**: Typically <30 seconds for full orchestration
- **Context Restoration**: Full agent context restored
- **Monitoring Enabled**: All monitoring resumes automatically
