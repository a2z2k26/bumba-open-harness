---
name: cleanup
description: Cleanup idle sandboxes
---

# /cleanup-sandboxes Command

Identifies and terminates idle, completed, or failed Bumba Sandbox sandboxes to optimize costs and resources.

## Usage

```
/cleanup-sandboxes [--criteria <criteria>] [--yes] [--dry-run]
```

## Parameters

- `--criteria <criteria>` (optional): Cleanup criteria (default: smart)
  - `idle`: Remove sandboxes idle for 1+ hours
  - `completed`: Remove sandboxes for merged PRs
  - `failed`: Remove sandboxes that crashed/failed
  - `all`: Remove all sandboxes (dangerous!)
  - `smart`: Auto-detect based on status (recommended)
- `--yes` (optional): Skip confirmation prompts
- `--dry-run` (optional): Preview what would be cleaned up

## Workflow

### Step 1: Identify Cleanup Candidates

1. **Query All Active Sandboxes**:
   - Call `monitor_agents` MCP tool
   - Get all sandbox IDs and associated issues
   - Get current status and metadata

2. **Categorize Sandboxes**:

   **Idle Sandboxes**:
   - Parse hook logs for last activity timestamp
   - No PostToolUse hook entries in last 1+ hours
   - Sandbox is running but doing nothing

   **Completed Sandboxes**:
   - Check associated PR status via GitHub API
   - PR is merged to main branch
   - Feature implementation is complete

   **Failed Sandboxes**:
   - Sandbox status is "failed" or "crashed"
   - Multiple consecutive errors in hook logs
   - Agent stopped responding

   **Timeout Warning Sandboxes**:
   - Uptime > 22 hours (approaching 24h limit)
   - Will auto-terminate soon anyway

### Step 2: Analyze Each Candidate

For each sandbox identified for cleanup:

1. **Calculate Costs Being Wasted**:
   - Idle time × $0.02/hour
   - Projected waste if left running until 24h timeout

2. **Check for Unsaved Work**:
   - Query sandbox for uncommitted changes
   - Check if code has been synced to worktree
   - Warn if unsaved work exists

3. **Estimate Savings**:
   - Calculate cost savings from termination
   - Project monthly savings if behavior continues

### Step 3: Display Cleanup Preview

Show detailed preview before any action:

```
🧹 Sandbox Cleanup Analysis
═══════════════════════════════════════════════

Cleanup Criteria: Smart (idle + completed + failed)

Candidates for Cleanup: 4 sandboxes
Potential Savings: $0.68 per day

─────────────────────────────────────────────────

IDLE SANDBOXES (2)
═══════════════════════════════════════════════

1. sbx_abc123xyz - Issue #42 (User Authentication)
   Status:        Idle for 2h 15m
   Uptime:        3h 47m
   Cost So Far:   $0.08
   Waste Rate:    $0.02/hour
   Last Activity: execute_command (npm test)
   Last Sync:     15 minutes ago ✓
   Unsaved Work:  None ✓
   Action:        SAFE TO REMOVE

2. sbx_def456uvw - Issue #43 (Database Migration)
   Status:        Idle for 5h 12m
   Uptime:        8h 23m
   Cost So Far:   $0.17
   Waste Rate:    $0.02/hour
   Last Activity: files_write (migration.sql)
   Last Sync:     5 hours ago ⚠️
   Unsaved Work:  3 uncommitted files ⚠️
   Action:        SYNC FIRST, THEN REMOVE

─────────────────────────────────────────────────

COMPLETED SANDBOXES (1)
═══════════════════════════════════════════════

3. sbx_ghi789rst - Issue #44 (Performance Optimization)
   Status:        PR #85 merged 2 days ago ✓
   Uptime:        15h 32m (approaching timeout)
   Cost So Far:   $0.31
   Waste Rate:    $0.02/hour
   Last Sync:     2 days ago ✓
   Unsaved Work:  None ✓
   Action:        SAFE TO REMOVE

─────────────────────────────────────────────────

FAILED SANDBOXES (1)
═══════════════════════════════════════════════

4. sbx_jkl012mno - Issue #45 (API Integration)
   Status:        Crashed 6 hours ago ❌
   Uptime:        12h 8m
   Cost So Far:   $0.24
   Error:         Out of memory (exit code: 137)
   Last Sync:     Never ⚠️
   Unsaved Work:  Unknown ⚠️
   Action:        ATTEMPT RECOVERY, THEN REMOVE

═══════════════════════════════════════════════

💰 Cost Analysis
═══════════════════════════════════════════════

Current Waste:
  Idle sandboxes:      $0.04/hour (2 × $0.02)
  Completed sandboxes: $0.02/hour (1 × $0.02)
  Failed sandboxes:    $0.02/hour (1 × $0.02)
  ──────────────────────────────
  Total:               $0.08/hour

Projected Savings:
  Next 1 hour:         $0.08
  Next 24 hours:       $1.92
  Next 30 days:        $57.60

Already Wasted:
  Total cost of candidates: $0.80
  Time idle/complete: ~8 hours average
  Wasted so far: ~$0.16

⚠️  Warnings
═══════════════════════════════════════════════

Sandboxes with unsaved work:
  - sbx_def456uvw: 3 uncommitted files
  - sbx_jkl012mno: Unable to check (crashed)

Recommended Actions:
  1. Sync sbx_def456uvw before cleanup
  2. Attempt recovery of sbx_jkl012mno
  3. Safe to immediately remove: sbx_abc123xyz, sbx_ghi789rst

Continue with cleanup? (yes/no/selective)
```

### Step 4: User Confirmation

Provide three options:

1. **Yes**: Cleanup all candidates
2. **No**: Abort cleanup
3. **Selective**: Choose which sandboxes to cleanup

For selective mode:
```
Select sandboxes to cleanup:
  [1] sbx_abc123xyz (idle, safe)
  [2] sbx_def456uvw (idle, has unsaved work)
  [3] sbx_ghi789rst (completed, safe)
  [4] sbx_jkl012mno (failed, needs recovery)

Enter numbers (e.g., 1,3,4) or 'all':
```

### Step 5: Pre-Cleanup Actions

Before terminating each sandbox:

1. **Sync Unsaved Work**:
   - For sandboxes with uncommitted changes
   - Download all modified files
   - Save to worktree with timestamp
   - Create emergency backup

2. **Attempt Recovery** (for failed sandboxes):
   - Try to reconnect to sandbox
   - If successful, sync any accessible files
   - Extract error logs for debugging
   - Save crash dump if available

3. **Update Orchestrator State**:
   - Mark sandbox as "terminated by cleanup"
   - Log final metrics (uptime, cost, tools used)
   - Update issue status

### Step 6: Execute Cleanup

For each approved sandbox:

1. **Terminate Sandbox**:
   - Call `sandbox_kill` MCP tool
   - Wait for confirmation of termination
   - Handle errors gracefully

2. **Cleanup Local State**:
   - Remove sandbox from orchestrator state
   - Archive logs to `logs/archived/`
   - Update cost tracking

3. **Display Progress**:
   ```
   Cleaning up sandboxes...
   ✓ sbx_abc123xyz terminated (saved $0.47/day)
   ✓ sbx_def456uvw synced and terminated (saved $0.47/day)
   ✓ sbx_ghi789rst terminated (saved $0.47/day)
   ⚠ sbx_jkl012mno recovery failed, terminated (saved $0.47/day)
   ```

### Step 7: Generate Cleanup Report

```
✅ Cleanup Complete!

📊 Summary:
═══════════════════════════════════════════════

Sandboxes Terminated: 4
Successful Cleanups:  4
Failed Cleanups:      0

Files Recovered:
  sbx_def456uvw: 3 files synced to worktrees/feature-43/
  sbx_jkl012mno: Logs saved to logs/archived/sbx_jkl012mno/

Costs Saved:
  Immediate:            $0.08/hour
  Daily:                $1.92/day
  Monthly (projected):  $57.60/month

Total Cost of Cleaned Sandboxes: $0.80
Time Saved: Prevented $1.92 in waste per day

Active Sandboxes Remaining: 2
  sbx_pqr345stu: Issue #46 (Active, 45m uptime)
  sbx_vwx678yza: Issue #47 (Active, 1h 12m uptime)

💡 Recommendations:
═══════════════════════════════════════════════

1. Run /cleanup-sandboxes daily to prevent waste
2. Consider configuring auto-cleanup in bumba-sandbox-config.json
3. Monitor sandbox activity with /sandbox-status
4. Set idle threshold to match your workflow

Archived Logs:
  logs/archived/cleanup-2025-11-18-1432.json
```

## Examples

### Example 1: Smart Cleanup (Recommended)
```
/cleanup-sandboxes
```
Auto-detects idle, completed, and failed sandboxes.

### Example 2: Cleanup Idle Only
```
/cleanup-sandboxes --criteria idle
```
Only removes sandboxes with no recent activity.

### Example 3: Preview Without Action
```
/cleanup-sandboxes --dry-run
```
Shows what would be cleaned up without actually doing it.

### Example 4: Auto-Confirm Cleanup
```
/cleanup-sandboxes --yes
```
Skips confirmation prompts, proceeds with cleanup.

## Cleanup Criteria Details

### Idle Criteria
- No PostToolUse hook activity in last 1+ hours
- Sandbox is running but agent is not working
- Default threshold: 1 hour (configurable)

### Completed Criteria
- Associated GitHub PR is merged
- All code synced back to main branch
- No active development needed

### Failed Criteria
- Sandbox status is "failed" or "crashed"
- Agent stopped responding
- Multiple consecutive errors in logs

### Smart Criteria (Recommended)
Combines all three:
- Idle sandboxes (1+ hours)
- Completed sandboxes (merged PRs)
- Failed sandboxes (crashed)

## Safety Features

### Unsaved Work Detection
- Scans for uncommitted git changes
- Checks last sync timestamp
- Warns before proceeding

### Automatic Sync
- Syncs unsaved work before cleanup
- Creates timestamped backups
- Logs sync operations

### Recovery Attempts
- Tries to reconnect to failed sandboxes
- Extracts logs and error information
- Saves crash dumps for debugging

### Confirmation Prompts
- Always confirms before cleanup (unless --yes)
- Shows detailed preview
- Allows selective cleanup

## Configuration

Configure in `.claude/config/bumba-sandbox-config.json`:

```json
{
  "cleanup": {
    "idleThreshold": 1,
    "autoCleanup": false,
    "autoCleanupInterval": 3600,
    "syncBeforeCleanup": true,
    "archiveLogs": true,
    "criteria": "smart"
  }
}
```

- `idleThreshold`: Hours before marking as idle
- `autoCleanup`: Enable automatic cleanup
- `autoCleanupInterval`: Seconds between auto-cleanup runs
- `syncBeforeCleanup`: Auto-sync unsaved work
- `archiveLogs`: Save logs before cleanup
- `criteria`: Default cleanup criteria

## Cost Savings Examples

**Example 1: Single Idle Sandbox**
- Idle for: 5 hours
- Cost wasted: $0.10
- If left until timeout (24h): $0.48 total waste
- Cleanup savings: $0.38

**Example 2: Daily Cleanup Habit**
- Average idle sandboxes: 2
- Average idle time: 3 hours
- Daily waste without cleanup: $1.44
- Monthly savings: ~$43.20

**Example 3: Completed PRs**
- Average time between merge and cleanup: 2 days
- Cost per abandoned sandbox: $0.96
- With 5 PRs per week: $240 monthly waste
- Cleanup savings: $240/month

## Error Handling

- **Sandbox Not Found**: Skip and continue with others
- **Sync Failed**: Retry once, then prompt user
- **Recovery Failed**: Log error and continue
- **API Error**: Retry with exponential backoff
- **Partial Failure**: Report which succeeded/failed

## Hook System Integration

Cleanup operations are logged:
- **PostToolUse Hook**: Logs sandbox_kill actions
- **Stop Hook**: Records final costs saved

**MCP Integration**: Uses `monitor_agents`, `sandbox_kill`, and `optimize_resources` MCP tools for comprehensive cleanup operations.

## Notes

- Run cleanup regularly to minimize waste (daily recommended)
- Auto-cleanup can be enabled for hands-off operation
- Always preview with --dry-run first
- Idle threshold can be customized for your workflow
- Completed PR sandboxes are safe to remove immediately
- Failed sandboxes may contain valuable error logs - archive them
- Monitor usage carefully to optimize costs
- Synced work is always safe in your worktree
- Archived logs are kept for 30 days by default
