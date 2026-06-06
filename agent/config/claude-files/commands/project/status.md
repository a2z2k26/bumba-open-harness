---
name: status
description: View project status and metrics
---

# /show-status Command

Displays comprehensive status of all active features, worktrees, and Bumba Sandbox sandboxes with hook-based monitoring.

## Usage

```
/show-status [--detail] [--mode <local|sandbox|all>]
```

## Parameters

- `--detail` (optional): Show detailed information for each feature
- `--mode <mode>` (optional): Filter by execution mode (default: all)
  - `local`: Show only local worktrees
  - `sandbox`: Show only sandboxed features
  - `all`: Show everything

## Workflow

### Step 1: Gather Local Worktree Information

1. **List Git Worktrees**:
   - Run `git worktree list` to get all active worktrees
   - Parse worktree paths, branches, and commit hashes
   - Extract issue numbers from branch names

2. **Analyze Each Worktree**:
   - Check git status (uncommitted changes, unpushed commits)
   - Determine if branch has associated PR (using gh CLI)
   - Get last commit timestamp and author
   - Count files changed since branching from main

### Step 2: Query Hook Logs for Activity

1. **Read Hook Logs**:
   - Query `apps/sandbox_agent_working_dir/logs/` for agent logs
   - Parse log files to extract activity timestamps
   - Identify which features have recent activity (last 1 hour, 24 hours)

2. **Extract Progress Indicators**:
   - Count tool uses from PostToolUse hook logs
   - Identify current task from log messages
   - Calculate time since last activity
   - Extract any error messages or warnings

### Step 3: Query Sandbox Status via MCP

1. **Call monitor_agents MCP Tool**:
   - Retrieve status of all active sandbox agents
   - Get sandbox IDs, issue numbers, and current status
   - Retrieve resource usage (CPU, memory, uptime)
   - Get cost information from Stop hook logs

2. **Match Sandboxes to Worktrees**:
   - Link sandboxes to worktrees by issue number
   - Identify orphaned sandboxes (no worktree) or orphaned worktrees (no sandbox)

### Step 4: Aggregate and Format Status

1. **Calculate Summary Statistics**:
   - Total features in progress
   - Total worktrees (local + sandbox)
   - Total active sandboxes
   - Total cost (sandbox + API costs)
   - Average progress across all features
   - Estimated time to completion

2. **Categorize Features by Status**:
   - **Active**: Recent activity within last hour
   - **Stale**: No activity for 1-24 hours
   - **Idle**: No activity for > 24 hours
   - **Ready for PR**: Implementation complete, tests passing
   - **Blocked**: Waiting on dependencies or reviews

### Step 5: Display Status Report

Generate formatted status report with sections:

#### Overview Section
```
📊 Bumba Sandbox Orchestrator Status
═══════════════════════════════════════════════

Session: <session-id>
Started: <timestamp> (<duration> ago)
Strategy: <max-speed|balanced|cost-optimized>

Features in Progress: <total>
  - Active:  <count> (recent activity)
  - Stale:   <count> (no activity 1-24h)
  - Idle:    <count> (no activity >24h)

Execution Breakdown:
  - Local worktrees:   <count>
  - Sandbox agents:    <count>
  - Total cost:        $<amount>
```

#### Features Detail Section

For each feature, display:

**Local Mode Features**:
```
#42: Implement user authentication
  Branch:     feature/issue-42
  Worktree:   worktrees/feature-42/
  Status:     Active (15m ago)
  Progress:   Implementation phase
  Changes:    5 files modified, 234 lines added
  Tests:      Passing (12/12)
  Next:       Ready for PR creation
```

**Sandbox Mode Features**:
```
#43: Add database migration system
  Branch:      feature/issue-43
  Worktree:    worktrees/feature-43/
  Sandbox:     sbx_abc123xyz
  Status:      Active (2m ago)
  Progress:    Testing phase (80%)
  Uptime:      1h 23m
  Resources:   CPU: 15%, Memory: 245MB
  Cost:        $0.03 (sandbox) + $0.12 (API) = $0.15
  Activity:    Last tool use: execute_command (npm test)
  Next:        Monitor completion, then sync code back
```

**Idle/Stale Features**:
```
#44: Update documentation
  Branch:      feature/issue-44
  Status:      Idle (3d 5h ago) ⚠️
  Note:        Consider cleanup with /cleanup-sandboxes
```

#### Resource Summary Section
```
💰 Cost Tracking
═══════════════════════════════════════════════

Sandbox Costs:      $0.15
API Costs:          $0.87
──────────────────────────
Total Costs:        $1.02
Budget Used:        1.02% of $100.00
Budget Remaining:   $98.98

⏱️  Time Tracking
═══════════════════════════════════════════════

Total Session Time:    4h 23m
Average per Feature:   1h 27m
Estimated Completion:  ~2h 15m (2 features remaining)
```

## Examples

### Example 1: Show All Status
```
/show-status
```
Displays status of all local and sandbox features.

### Example 2: Show Only Sandbox Features
```
/show-status --mode sandbox
```
Displays only features running in E2B sandboxes.

### Example 3: Show Detailed Status
```
/show-status --detail
```
Includes additional details like hook logs, file diffs, and recent commits.

## Status Indicators

### Activity Status
- 🟢 **Active**: Activity within last hour
- 🟡 **Stale**: No activity for 1-24 hours
- 🔴 **Idle**: No activity for >24 hours
- ✅ **Ready**: Tests passing, ready for PR
- ⏸️ **Paused**: Manually paused
- ❌ **Failed**: Implementation or tests failed
- ⏳ **Blocked**: Waiting on dependencies

### Progress Indicators
- **Planning**: Creating implementation plan
- **Implementation**: Actively writing code
- **Testing**: Running tests
- **Fixing**: Addressing test failures
- **Complete**: All tests passing, ready for PR

## Hook-Based Monitoring

This command leverages hook logs for real-time activity:

- **PostToolUse Hook**: Shows last tool used and when
- **Stop Hook**: Provides token usage and cost data
- **UserPromptSubmit Hook**: Shows decision points and user interactions

All this data is parsed from logs in `apps/sandbox_agent_working_dir/logs/`.

## Configuration

Configure display preferences in `.claude/config/bumba-sandbox-config.json`:
- `status.showCosts`: Show cost information (default: true)
- `status.showProgress`: Show progress percentages (default: true)
- `status.staleThreshold`: Hours before marking as stale (default: 1)
- `status.idleThreshold`: Hours before marking as idle (default: 24)
- `status.groupByStatus`: Group features by status (default: false)

## Output Formats

### Compact Mode (Default)
Shows essential information in a table format.

### Detail Mode (--detail)
Shows expanded information including:
- Recent hook log entries
- File-level git diff summary
- Recent commits and messages
- Test output summaries
- Sandbox resource graphs (if available)

## Next Steps Recommendations

Based on status, I'll suggest appropriate actions:

- **For Active Features**: "Continue monitoring"
- **For Stale Features**: "Resume work or cleanup?"
- **For Idle Features**: "Run /cleanup-sandboxes to free resources"
- **For Ready Features**: "Run /create-pull-request #<issue>"
- **For Failed Features**: "Review errors and retry"

## Notes

- Hook logs provide more accurate activity tracking than sandbox metrics alone
- Costs are calculated in real-time from Stop hook token usage logs
- Idle sandboxes waste money (~$0.02/hour each) - cleanup recommended
- You can pause/resume features without losing progress
- Status is persisted in orchestrator state for session recovery
