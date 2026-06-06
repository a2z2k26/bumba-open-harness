---
name: status
description: Check sandbox status and metrics
---

# /sandbox-status Command

Displays detailed status of all Bumba Sandbox instances with hook-based activity monitoring.

## Usage

```
/sandbox-status [--detail] [--sort <sort-field>]
```

## Parameters

- `--detail` (optional): Show extended information including hook logs and resource graphs
- `--sort <field>` (optional): Sort sandboxes by field (default: uptime)
  - `cost`: Sort by total cost (highest first)
  - `uptime`: Sort by runtime (longest first)
  - `activity`: Sort by last activity (most recent first)
  - `issue`: Sort by issue number (lowest first)

## Workflow

### Step 1: Query Active Sandboxes via MCP

1. **Call monitor_agents MCP Tool**:
   - Retrieve all active sandbox agents
   - Get sandbox IDs, issue numbers, and status
   - Filter for only sandboxed agents (exclude local)

2. **Get Sandbox Details**:
   - For each sandbox, query Bumba Sandbox API for:
     - Current status (running, stopped, failed)
     - Template used
     - Creation timestamp
     - Resource usage (CPU, memory, disk)

### Step 2: Query Hook Logs for Activity

1. **Parse Hook Logs**:
   - Read logs from `apps/sandbox_agent_working_dir/logs/agent-{issue}-*.log`
   - Extract PostToolUse hook entries for tool usage
   - Extract Stop hook entries for token/cost tracking
   - Identify last activity timestamp

2. **Analyze Activity Patterns**:
   - Count tool uses in last hour, 24 hours
   - Identify most frequently used tools
   - Detect if sandbox is idle (no activity > 1 hour)
   - Extract current task from log context

### Step 3: Calculate Costs from Hook Logs

1. **Extract Stop Hook Data**:
   - Parse Stop hook entries for token usage
   - Calculate API costs using Anthropic pricing:
     - Input tokens: $3.00 / 1M tokens
     - Output tokens: $15.00 / 1M tokens

2. **Calculate Sandbox Runtime Costs**:
   - Get sandbox uptime from creation time
   - Calculate sandbox costs: ~$0.02/hour
   - Factor in free tier: 100 hours/month free

3. **Aggregate Total Costs**:
   - Total = API costs + Sandbox runtime costs
   - Show per-sandbox and grand total

### Step 4: Check E2B Limits

1. **Check 24-Hour Timeout**:
   - Bumba Sandbox instances auto-terminate after 24 hours
   - Calculate remaining time before timeout
   - Warn if sandbox approaching timeout (< 2 hours left)

2. **Check Free Tier Usage**:
   - Track total sandbox hours used this month
   - Calculate free tier remaining (100 hours)
   - Warn if approaching free tier limit

### Step 5: Format and Display Status

Generate comprehensive sandbox status report:

```
🏖️  Bumba Sandbox Status
═══════════════════════════════════════════════

Active Sandboxes: 3
Total Runtime: 5h 47m
Total Cost: $0.35 (sandbox) + $1.24 (API) = $1.59
Free Tier Used: 5.8 hours of 100 hours (5.8%)

─────────────────────────────────────────────────

Sandbox 1: sbx_abc123xyz
═══════════════════════════════════════════════

Issue:           #42 - Implement user authentication
Template:        node-typescript
Status:          🟢 Running (Active)
Uptime:          2h 15m (21h 45m remaining before timeout)

Activity:
  Last Active:   3 minutes ago
  Current Task:  Running tests
  Tools Used:    47 total (23 in last hour)
  Top Tools:     execute_command (18), files_write (12), files_read (9)

Resources:
  CPU:           18.5% (low)
  Memory:        312 MB / 2 GB (15.6%)
  Disk:          156 MB used

Costs:
  Sandbox:       $0.04 (2.25 hours × $0.02/hr)
  API:           $0.42 (Input: $0.12, Output: $0.30)
  Total:         $0.46

Next Action:    Monitor completion, ready to sync code back

─────────────────────────────────────────────────

Sandbox 2: sbx_def456uvw
═══════════════════════════════════════════════

Issue:           #43 - Add database migration system
Template:        python-postgres
Status:          🟡 Running (Idle - no activity 1h 23m) ⚠️
Uptime:          3h 8m (20h 52m remaining)

Activity:
  Last Active:   1h 23m ago
  Last Task:     Database migration test
  Tools Used:    62 total (0 in last hour)
  Top Tools:     execute_command (31), files_write (18)

Resources:
  CPU:           2.1% (idle)
  Memory:        189 MB / 2 GB (9.5%)
  Disk:          223 MB used

Costs:
  Sandbox:       $0.06 (3.13 hours × $0.02/hr)
  API:           $0.67
  Total:         $0.73

⚠️  Warning:     Idle for over 1 hour
Recommendation:  Consider cleanup with /cleanup-sandboxes

─────────────────────────────────────────────────

Sandbox 3: sbx_ghi789rst
═══════════════════════════════════════════════

Issue:           #44 - Performance optimization
Template:        node-typescript
Status:          🟢 Running (Active)
Uptime:          24m (23h 36m remaining)

Activity:
  Last Active:   30 seconds ago
  Current Task:  Load testing
  Tools Used:    12 total (12 in last hour)
  Top Tools:     execute_command (8), files_read (3)

Resources:
  CPU:           45.2% (moderate)
  Memory:        892 MB / 2 GB (44.6%)
  Disk:          98 MB used

Costs:
  Sandbox:       $0.01 (0.40 hours × $0.02/hr)
  API:           $0.15
  Total:         $0.16

Next Action:    Active development in progress

═══════════════════════════════════════════════

💰 Cost Summary
═══════════════════════════════════════════════

Sandbox Runtime Costs:
  sbx_abc123xyz:  $0.04
  sbx_def456uvw:  $0.06
  sbx_ghi789rst:  $0.01
  ──────────────────
  Total:          $0.11

API Costs (from Stop hooks):
  sbx_abc123xyz:  $0.42
  sbx_def456uvw:  $0.67
  sbx_ghi789rst:  $0.15
  ──────────────────
  Total:          $1.24

Grand Total:      $1.35

⏱️  Free Tier Status
═══════════════════════════════════════════════

Hours Used:       5.8 hours of 100 hours free
Remaining:        94.2 hours
Percentage:       5.8%
Estimated Cost:   $0.00 (within free tier)

At Current Rate:  17.4 hours per day
Free Tier Lasts:  ~5.4 days

⚠️  Recommendations
═══════════════════════════════════════════════

1. Sandbox sbx_def456uvw has been idle for 1h 23m
   → Run /cleanup-sandboxes to terminate if no longer needed
   → Potential savings: $0.02/hour

2. All sandboxes are within free tier limits ✓

3. Monitor sbx_abc123xyz - approaching 2 hours runtime
   → Consider completing work or pausing if long-running
```

## Detailed Mode (--detail)

When `--detail` flag is used, additional information is shown:

```
Hook Log Activity (Last 10 Entries):
─────────────────────────────────────────────────
[2025-11-18 14:32:45] PostToolUse: execute_command
  Command: npm test
  Duration: 12.3s
  Exit Code: 0

[2025-11-18 14:32:01] PostToolUse: files_write
  File: src/tests/auth.test.ts
  Size: 1,234 bytes

[2025-11-18 14:31:12] Stop
  Input Tokens: 2,345
  Output Tokens: 567
  Cost: $0.015

... (7 more entries)

Resource Usage Graph (Last Hour):
─────────────────────────────────────────────────
CPU:
14:00 ▁▂▃▅▆▇▇▆▅▃▂▁ 14:30 ▂▃▅▆▆▅▃▂ 15:00
      15%  →  45%  →  18%

Memory:
14:00 ▃▃▃▄▄▄▄▄▃▃▃▃ 14:30 ▄▄▄▄▄▄▄▄ 15:00
      280MB → 310MB → 312MB
```

## Examples

### Example 1: Show All Sandboxes
```
/sandbox-status
```
Displays status of all active sandboxes.

### Example 2: Sort by Cost
```
/sandbox-status --sort cost
```
Shows sandboxes sorted by total cost (highest first).

### Example 3: Detailed View
```
/sandbox-status --detail
```
Includes hook logs and resource graphs.

## Status Indicators

- 🟢 **Active**: Recent activity within last hour
- 🟡 **Idle**: No activity for 1+ hours
- 🔴 **Failed**: Sandbox crashed or terminated
- ⏸️ **Paused**: Manually paused
- ⏳ **Timeout Warning**: < 2 hours before 24h timeout

## Warnings and Alerts

### Idle Sandbox Warning
Shown when sandbox has no activity for > 1 hour.

### Timeout Warning
Shown when sandbox has < 2 hours before 24-hour timeout.

### Free Tier Warning
Shown when > 80% of free tier is used.

### High Cost Warning
Shown when individual sandbox cost > $1.00.

## Hook-Based Activity Tracking

This command relies heavily on hook logs:

- **PostToolUse Hook**: Tracks all tool usage with timestamps
- **Stop Hook**: Provides accurate token usage and costs
- **UserPromptSubmit Hook**: Shows user interactions and decisions

Benefits of hook-based tracking:
- More accurate than polling sandbox metrics
- Lower latency - no need to query sandbox API repeatedly
- Historical context - can see past activity
- Cost tracking - precise token usage data

**MCP Integration**: Uses `monitor_agents` and `sandbox_status` MCP tools to query sandbox state and metrics.

## Configuration

Configure in `.claude/config/bumba-sandbox-config.json`:
- `sandbox.idleThreshold`: Hours before marking as idle (default: 1)
- `sandbox.timeoutWarning`: Hours before timeout to warn (default: 2)
- `sandbox.freeTierLimit`: Free tier hours limit (default: 100)
- `sandbox.showResources`: Show resource usage (default: true)
- `sandbox.showCosts`: Show cost information (default: true)

## Cost Calculation

**Sandbox Runtime Costs**:
- $0.02 per hour (sandbox pricing)
- First 100 hours per month free
- Billed per second

**API Costs** (from Stop hooks):
- Claude Sonnet: $3/1M input tokens, $15/1M output tokens
- Calculated from actual usage in hook logs

## Notes

- Sandboxes automatically terminate after 24 hours (platform limit)
- Idle sandboxes waste money - cleanup recommended after 1+ hour idle
- Free tier resets monthly (100 hours free)
- Hook logs provide more accurate data than E2B metrics
- Use `/cleanup-sandboxes` to terminate idle sandboxes
- Use `/pause-feature` to pause sandbox without losing progress
- Paused sandboxes don't count toward runtime costs

## Error Handling

**Common Issues**:
- **Sandbox Not Found**: Sandbox may have been terminated or never created
- **Connection Timeout**: Sandbox service may be experiencing issues
- **Permission Denied**: Check sandbox API key is valid
- **Hook Logs Missing**: Agent may not have started properly
- **Resource Data Unavailable**: Sandbox may be in transition state

All errors are logged and can be reviewed in `apps/sandbox_agent_working_dir/logs/`
