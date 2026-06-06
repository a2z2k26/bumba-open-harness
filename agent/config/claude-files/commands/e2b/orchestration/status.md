---
name: status
description: Check orchestrator status
---

# /orchestrator-status Command

Displays comprehensive orchestrator state including active sessions, issue tracking, agent status, resource utilization, costs, and progress toward completion.

## Usage

```
/orchestrator-status [--detail] [--format <table|json>]
```

## Parameters

- `--detail` (optional): Show extended details including dependency graph and event log
- `--format <format>` (optional): Output format (default: table)
  - `table`: Human-readable table format
  - `json`: Machine-readable JSON format

## Workflow

### Step 1: Load Orchestrator State

1. **Read State File**:
   ```bash
   cat .claude/config/orchestrator-state.json
   ```

2. **Parse State Data**:
   - Session information
   - Issue tracking
   - Agent states
   - Sandbox allocations
   - Resource usage
   - Cost tracking
   - Event log

### Step 2: Display Session Information

```
🎯 Orchestrator Session
═══════════════════════════════════════════════

Session ID: orch-20251118-143215
Started: 2025-11-18 14:32:15 (2h 15m ago)
Strategy: balanced
Status: Active

Current Wave: 2/3
Issues in Session: 12
  ✓ Completed: 5
  ⚡ In Progress: 3
  ⏳ Queued: 2
  ❌ Failed: 2
```

### Step 3: Display Issue Tracking

```
📋 Issue Tracking
═══════════════════════════════════════════════

COMPLETED Issues (5):
  ✓ #42: User Authentication
      Started: 2h 15m ago
      Completed: 2h ago (15m duration)
      Agent: Local worktree
      Status: PR merged
      Cost: $0.53

  ✓ #43: Database Schema
      Started: 2h 15m ago
      Completed: 1h 50m ago (25m duration)
      Agent: Local worktree
      Status: PR merged
      Cost: $0.38

  ✓ #44: API Endpoints
      Started: 1h 50m ago
      Completed: 1h 15m ago (35m duration)
      Agent: Sandbox (sbx_ghi789rst)
      Status: PR created (#87)
      Cost: $0.67

  ✓ #45: Frontend Components
      Started: 2h 15m ago
      Completed: 1h 30m ago (45m duration)
      Agent: Sandbox (sbx_jkl012mno)
      Status: PR merged
      Cost: $0.82

  ✓ #46: Integration Tests
      Started: 1h 15m ago
      Completed: 45m ago (30m duration)
      Agent: Sandbox (sbx_pqr345stu)
      Status: PR created (#89)
      Cost: $0.58

IN PROGRESS Issues (3):
  ⚡ #47: Search Feature
      Started: 45m ago
      Progress: 65%
      Agent: Sandbox (sbx_vwx678yza)
      Last Activity: 2m ago
      Current Task: Writing search tests
      ETA: ~15m remaining
      Cost so far: $0.34

  ⚡ #48: Email Notifications
      Started: 45m ago
      Progress: 40%
      Agent: Local worktree
      Last Activity: 5m ago
      Current Task: Implementing templates
      ETA: ~30m remaining
      Cost so far: $0.15

  ⚡ #49: User Dashboard
      Started: 20m ago
      Progress: 25%
      Agent: Sandbox (sbx_abc123def)
      Last Activity: 1m ago
      Current Task: Building React components
      ETA: ~40m remaining
      Cost so far: $0.12

QUEUED Issues (2):
  ⏳ #50: Analytics Dashboard
      Blocked By: #47 (65% complete)
      Queue Position: 1
      Estimated Start: ~15m
      Mode: Sandbox

  ⏳ #51: Admin Panel
      Blocked By: #50 (not started)
      Queue Position: 2
      Estimated Start: ~1h 30m
      Mode: Sandbox

FAILED Issues (2):
  ❌ #52: Real-time Chat
      Started: 1h ago
      Failed: 30m ago (30m duration)
      Agent: Sandbox (sbx_failed123)
      Error: Out of memory (exit code: 137)
      Cost: $0.28
      Action: Sandbox preserved for debugging

  ❌ #53: File Upload
      Started: 50m ago
      Failed: 20m ago (30m duration)
      Agent: Local worktree
      Error: Tests failed (5/12 failing)
      Cost: $0.18
      Action: Worktree preserved
```

### Step 4: Display Dependency Relationships

```
🔗 Dependency Graph
═══════════════════════════════════════════════

Wave 1 (Completed):
  #42 → #44 (completed)
  #43 → #44 (completed)
  #45 (completed, no deps)

Wave 2 (In Progress):
  #47 → #50 (blocked)
  #48 (no deps)
  #49 (no deps)

Wave 3 (Queued):
  #50 → #51 (blocked)

Critical Path:
  #47 → #50 → #51 (1h 45m remaining)

Dependency Status:
  ✓ Resolved: 5
  ⚡ In Progress: 3
  ⏳ Pending: 4
  ❌ Blocked by failures: 0
```

### Step 5: Display Resource Utilization

```
💻 Resource Utilization
═══════════════════════════════════════════════

Active Agents: 3

Sandboxes:
  Current: 3/10 (30% capacity)
  Peak: 5/10 (1h ago)
  Total Created: 8
  Destroyed: 5
  Failed: 1
  Average Uptime: 42m

Sandbox Details:
  sbx_vwx678yza (#47)
    Template: node-typescript
    Status: Running (active)
    Uptime: 45m (23h 15m remaining)
    CPU: 24.5% | Memory: 512 MB / 2 GB (25.6%)
    Cost: $0.34

  sbx_abc123def (#49)
    Template: node-typescript
    Status: Running (active)
    Uptime: 20m (23h 40m remaining)
    CPU: 18.2% | Memory: 380 MB / 2 GB (19%)
    Cost: $0.12

  sbx_failed123 (#52)
    Template: node-typescript
    Status: Failed (preserved for debug)
    Uptime: 30m (crashed)
    CPU: N/A | Memory: N/A
    Cost: $0.28

Local Worktrees:
  Active: 1
  Total Created: 4
  Deleted: 3

Worktree Details:
  worktrees/feature-48 (#48)
    Branch: feature/48-email-notifications
    Status: Active
    Last Modified: 5m ago
```

### Step 6: Display Cost Breakdown

```
💰 Cost Tracking
═══════════════════════════════════════════════

Session Costs:
  Sandbox Runtime: $1.28
  API Costs: $2.45
  ─────────────────────
  Total: $3.73

Monthly Costs:
  This Session: $3.73
  Other Sessions: $8.92
  ─────────────────────
  Month-to-Date: $12.65
  Monthly Limit: $100.00
  Remaining: $87.35 (87.4%)
  Utilization: 12.7%

Cost by Issue:
  #42: $0.53 (sandbox: $0.08, API: $0.45)
  #43: $0.38 (sandbox: $0, API: $0.38)
  #44: $0.67 (sandbox: $0.22, API: $0.45)
  #45: $0.82 (sandbox: $0.28, API: $0.54)
  #46: $0.58 (sandbox: $0.18, API: $0.40)
  #47: $0.34 (sandbox: $0.15, API: $0.19) [in progress]
  #48: $0.15 (sandbox: $0, API: $0.15) [in progress]
  #49: $0.12 (sandbox: $0.07, API: $0.05) [in progress]
  #52: $0.28 (sandbox: $0.18, API: $0.10) [failed]
  #53: $0.18 (sandbox: $0, API: $0.18) [failed]

Projected Costs:
  Remaining Issues: 2
  Estimated Cost: $1.50
  ─────────────────────
  Projected Total: $5.23

E2B Free Tier:
  Used This Month: 3.2 hours / 100 hours
  Remaining: 96.8 hours (96.8%)
```

### Step 7: Display Progress and Estimates

```
📊 Progress Tracking
═══════════════════════════════════════════════

Overall Progress: 58% (7/12 issues)
  Completed: 5 (42%)
  In Progress: 3 (25%)
  Queued: 2 (17%)
  Failed: 2 (17%)

Success Rate: 71% (5 completed / 7 attempted)

Time Tracking:
  Session Duration: 2h 15m
  Total Active Time: 4h 30m (across agents)
  Average per Issue: 27m
  Parallel Efficiency: 2.0x

Completion Estimates:
  Current Wave (#47-49): ~40m remaining
  Next Wave (#50): ~1h (after #47)
  Final Wave (#51): ~1h (after #50)
  ─────────────────────────────
  Estimated Total: ~2h 40m remaining

  Session End ETA: ~4h 55m total (2h 40m from now)
  Completion Date: 2025-11-18 ~17:15
```

### Step 8: Display Event Log (if --detail)

```
📜 Event Log (Last 20 Events)
═══════════════════════════════════════════════

[16:47:15] Agent spawned: #49 (sbx_abc123def)
[16:32:20] Issue completed: #46
[16:32:18] PR created: #89 (issue #46)
[16:32:05] Agent spawned: #47 (sbx_vwx678yza)
[16:32:05] Agent spawned: #48 (worktree)
[16:17:45] Issue completed: #44
[16:17:42] PR created: #87 (issue #44)
[16:15:30] Agent failed: #52 (Out of memory)
[16:00:12] Issue completed: #45
[15:50:08] Agent spawned: #46 (sbx_pqr345stu)
[15:45:20] Issue completed: #43
[15:42:10] Issue completed: #42
[15:42:08] PR merged: #85 (issue #42)
[15:30:05] Agent failed: #53 (Tests failed)
[14:47:00] Agent spawned: #44 (sbx_ghi789rst)
[14:32:15] Session started: orch-20251118-143215
[14:32:15] Agent spawned: #42 (worktree)
[14:32:15] Agent spawned: #43 (worktree)
[14:32:15] Agent spawned: #45 (sbx_jkl012mno)
[14:32:10] Orchestrator initialized
```

## Examples

### Example 1: Basic Status
```
/orchestrator-status
```
Shows current orchestrator state with summary information.

### Example 2: Detailed View
```
/orchestrator-status --detail
```
Shows extended details including event log and dependency graph.

### Example 3: JSON Output
```
/orchestrator-status --format json
```
Outputs state in machine-readable JSON format for automation.

## JSON Format

```json
{
  "session": {
    "id": "orch-20251118-143215",
    "startedAt": "2025-11-18T14:32:15Z",
    "strategy": "balanced",
    "status": "active",
    "duration": "2h 15m"
  },
  "issues": {
    "total": 12,
    "completed": 5,
    "inProgress": 3,
    "queued": 2,
    "failed": 2
  },
  "agents": [
    {
      "issue": 47,
      "sandboxId": "sbx_vwx678yza",
      "status": "running",
      "progress": 65,
      "startedAt": "2025-11-18T15:47:15Z",
      "lastActivity": "2025-11-18T16:45:30Z",
      "currentTask": "Writing search tests",
      "eta": "15m"
    }
  ],
  "resources": {
    "sandboxes": {
      "current": 3,
      "max": 10,
      "totalCreated": 8,
      "destroyed": 5,
      "failed": 1
    },
    "worktrees": {
      "active": 1,
      "total": 4
    }
  },
  "costs": {
    "session": {
      "sandbox": 1.28,
      "api": 2.45,
      "total": 3.73
    },
    "monthly": {
      "total": 12.65,
      "limit": 100.00,
      "remaining": 87.35
    }
  },
  "progress": {
    "percentage": 58,
    "successRate": 71,
    "eta": "2h 40m"
  }
}
```

## Configuration

Configure in `.claude/config/bumba-sandbox-config.json`:

```json
{
  "orchestrator": {
    "stateFile": ".claude/config/orchestrator-state.json",
    "autoSave": true,
    "saveInterval": 30,
    "maxEventLog": 1000
  }
}
```

## Integration

**Monitor During Parallel Execution**:
```bash
# In one terminal
/parallel-implement-features #42 #43 #44

# In another terminal (watch mode)
watch -n 30 /orchestrator-status
```

## Notes

- State is automatically saved every 30 seconds
- Event log is limited to last 1000 events
- JSON format is useful for dashboards and monitoring
- Detailed view includes full dependency graph
- Cost tracking includes both sandbox and API costs
- ETA is estimated based on current progress
- Failed issues preserve state for debugging
- Use this before `/cleanup-sandboxes` to review resources
