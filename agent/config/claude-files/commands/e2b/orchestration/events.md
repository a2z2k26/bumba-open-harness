---
name: events
description: View orchestrator events
---

# /orchestrator-events Command

Displays the complete event log for the current orchestration session, showing all agent lifecycle events, state changes, errors, and system activities. Essential for debugging, monitoring, and auditing orchestrated workflows.

## Usage

```
/orchestrator-events [options]
```

## Parameters

- `--filter <type>` (optional): Filter by event type - options: `spawn`, `complete`, `fail`, `pause`, `resume`, `error`, `all`
- `--limit <n>` (optional): Number of events to show - default: 50, max: 1000
- `--since <time>` (optional): Show events since time - formats: `10m`, `2h`, `2025-01-18T10:00:00Z`
- `--agent <id>` (optional): Filter events for specific agent/issue number
- `--format <format>` (optional): Output format - options: `table` (default), `json`, `csv`, `timeline`
- `--follow` (optional): Stream events in real-time (like `tail -f`) - default: false
- `--export <file>` (optional): Export events to file
- `--verbose` (optional): Show detailed event information - default: false

## Workflow

### Step 1: Event Log Loading

```
📋 Orchestration Event Log
═══════════════════════════════════════════════

Loading event log...
  Session: orch_xyz789abc
  Started: 2025-01-18 08:30:15 UTC
  Duration: 4h 32m 17s
  Status: Active

Event Statistics:
  Total Events: 247
  Agent Spawns: 23
  Completions: 18
  Failures: 3
  Pauses: 2
  Resumes: 2
  Errors: 4

───────────────────────────────────────────────
```

### Step 2: Event Display (Table Format)

```
Recent Events (last 50):

Timestamp           | Type     | Agent | Details
--------------------|----------|-------|----------------------------------------
2025-01-18 13:02:15 | complete | #50   | ✅ Tests passed, PR #127 created
2025-01-18 13:01:42 | info     | #50   | Running final test suite
2025-01-18 12:58:33 | info     | #50   | Code synced to worktree
2025-01-18 12:55:21 | spawn    | #51   | 🚀 Dependencies met, spawning agent
2025-01-18 12:52:10 | info     | #51   | Queued (waiting for slot)
2025-01-18 12:48:44 | complete | #49   | ✅ Implementation complete
2025-01-18 12:45:33 | info     | #49   | Building project (95%)
2025-01-18 12:42:18 | fail     | #47   | ❌ Tests failed (3 failures)
2025-01-18 12:40:05 | error    | #47   | Database connection timeout
2025-01-18 12:35:22 | resume   | ALL   | ▶️ Orchestration resumed
2025-01-18 10:30:00 | pause    | ALL   | ⏸️ Orchestration paused (Emergency)
2025-01-18 10:15:33 | complete | #45   | ✅ PR #125 merged successfully
2025-01-18 10:12:08 | info     | #45   | Waiting for CI checks
2025-01-18 09:58:44 | info     | #45   | PR #125 created
2025-01-18 09:45:10 | spawn    | #50   | 🚀 Agent spawned (sbx_mno345)
2025-01-18 09:42:30 | spawn    | #49   | 🚀 Agent spawned (sbx_jkl012)
2025-01-18 09:38:15 | spawn    | #47   | 🚀 Agent spawned (sbx_ghi789)
2025-01-18 09:15:42 | complete | #42   | ✅ Feature complete, PR merged
2025-01-18 09:12:28 | info     | #42   | Running integration tests
2025-01-18 08:58:12 | spawn    | #45   | 🚀 Agent spawned (sbx_def456)
2025-01-18 08:45:33 | info     | orch  | Strategy: balanced, max agents: 5
2025-01-18 08:30:15 | start    | orch  | 🎬 Orchestration started
2025-01-18 08:30:10 | spawn    | #42   | 🚀 Agent spawned (sbx_abc123)

Event Type Distribution:
  spawn     ████████████████░░░░ 23 (23%)
  complete  ███████████████░░░░░ 18 (18%)
  info      ███████████████████░ 32 (32%)
  fail      ███░░░░░░░░░░░░░░░░░  3 (3%)
  pause     █░░░░░░░░░░░░░░░░░░░  2 (2%)
  resume    █░░░░░░░░░░░░░░░░░░░  2 (2%)
  error     ██░░░░░░░░░░░░░░░░░░  4 (4%)
  other     ████████████████░░░░ 16 (16%)

───────────────────────────────────────────────

Filter by type:
  /orchestrator-events --filter spawn
  /orchestrator-events --filter complete
  /orchestrator-events --filter fail

Export to file:
  /orchestrator-events --format json --export events.json
```

## Examples

### Example 1: View Recent Events
```
/orchestrator-events
```

**Output**:
```
📋 Orchestration Event Log (Last 50 Events)

Timestamp           | Type     | Agent | Details
--------------------|----------|-------|------------------------
2025-01-18 13:02:15 | complete | #50   | ✅ Tests passed
2025-01-18 12:55:21 | spawn    | #51   | 🚀 Agent spawned
2025-01-18 12:48:44 | complete | #49   | ✅ Complete
[...]

Showing 50 of 247 total events
```

### Example 2: Filter by Event Type
```
/orchestrator-events --filter complete --limit 20
```

**Output**:
```
📋 Completions (Last 20)

Timestamp           | Agent | Duration | Details
--------------------|-------|----------|---------------------------
2025-01-18 13:02:15 | #50   | 3h 17m   | Tests passed, PR created
2025-01-18 12:48:44 | #49   | 3h 10m   | Implementation complete
2025-01-18 10:15:33 | #45   | 1h 30m   | PR merged successfully
2025-01-18 09:15:42 | #42   | 45m      | Feature complete, PR merged
[...]

Total completions: 18
Average duration: 2h 15m
Success rate: 85.7%
```

### Example 3: View Events for Specific Agent
```
/orchestrator-events --agent 42
```

**Output**:
```
📋 Events for Agent #42 (Authentication Feature)

Timestamp           | Type     | Details
--------------------|----------|----------------------------------------
2025-01-18 09:15:42 | complete | ✅ Feature complete, PR merged
2025-01-18 09:12:28 | info     | Running integration tests
2025-01-18 09:08:15 | info     | Tests passed (42/42)
2025-01-18 09:05:33 | info     | Building project
2025-01-18 08:58:12 | info     | Dependencies installed
2025-01-18 08:52:45 | info     | Worktree created
2025-01-18 08:48:22 | info     | Sandbox created (sbx_abc123)
2025-01-18 08:45:15 | info     | Starting implementation
2025-01-18 08:30:10 | spawn    | 🚀 Agent spawned (sbx_abc123)

Agent #42 Lifecycle:
  Spawned: 2025-01-18 08:30:10
  Completed: 2025-01-18 09:15:42
  Duration: 45m 32s
  Total Events: 27
  Status: ✅ Success
```

### Example 4: View Events Since Time
```
/orchestrator-events --since 2h
```

**Output**:
```
📋 Events in Last 2 Hours

Timestamp           | Type     | Agent | Details
--------------------|----------|-------|------------------------
2025-01-18 13:02:15 | complete | #50   | ✅ Tests passed
2025-01-18 12:55:21 | spawn    | #51   | 🚀 Agent spawned
2025-01-18 12:48:44 | complete | #49   | ✅ Complete
2025-01-18 12:42:18 | fail     | #47   | ❌ Tests failed
2025-01-18 12:35:22 | resume   | ALL   | ▶️ Resumed
[...]

Events in period: 47
Time range: 11:02:15 - 13:02:15
```

### Example 5: Follow Events in Real-Time
```
/orchestrator-events --follow
```

**Output**:
```
📋 Following Orchestration Events (Live)
═══════════════════════════════════════════════

Press Ctrl+C to stop following

2025-01-18 13:05:22 | info     | #51   | Installing dependencies...
2025-01-18 13:06:15 | info     | #51   | Running npm install
2025-01-18 13:07:33 | info     | #51   | Dependencies installed
2025-01-18 13:08:45 | info     | #51   | Creating worktree
2025-01-18 13:09:12 | info     | #51   | Analyzing requirements
2025-01-18 13:10:28 | info     | #51   | Implementing feature
^C

Stopped following events.
```

### Example 6: Export to JSON
```
/orchestrator-events --format json --limit 100 --export events.json
```

**Output**:
```
📋 Exporting Events to JSON

Collecting events...
  Total: 100 events
  Time Range: 2025-01-18 08:30:15 - 13:02:15

Exporting to: events.json
  Format: JSON
  Size: 42.3 KB

✅ Export Complete

File contents:
  events.json (42.3 KB, 100 events)

Preview:
  {
    "session": "orch_xyz789abc",
    "events": [
      {
        "timestamp": "2025-01-18T13:02:15Z",
        "type": "complete",
        "agent": 50,
        "details": "Tests passed, PR created",
        "duration": "3h17m"
      },
      ...
    ]
  }

Usage:
  jq '.events[] | select(.type=="complete")' events.json
```

### Example 7: Verbose Event Details
```
/orchestrator-events --verbose --limit 5
```

**Output**:
```
📋 Orchestration Events (Verbose)

Event 1/5:
─────────────────────────────────────────────
Timestamp: 2025-01-18 13:02:15 UTC
Type: complete
Agent: #50 (API Refactor)
Sandbox: sbx_mno345
Duration: 3h 17m 22s

Details:
  Tests passed: 42/42 (100%)
  Coverage: 94.2%
  PR created: #127
  Branch: feature/issue-50-api-refactor
  Files changed: 15
  Additions: 847
  Deletions: 423

Metadata:
  Started: 2025-01-18 09:45:10
  Completed: 2025-01-18 13:02:15
  Cost: $0.42
  Resource Usage: CPU 35%, Memory 2.1GB
─────────────────────────────────────────────

Event 2/5:
[...]
```

### Example 8: Timeline View
```
/orchestrator-events --format timeline --since 4h
```

**Output**:
```
📋 Orchestration Timeline (Last 4 Hours)

08:30 ┬ 🎬 Start orchestration
      ├ 🚀 Spawn #42
      │
09:00 ├ 🚀 Spawn #45
      ├ ℹ️  #42 Building
      │
09:30 ├ ℹ️  #42 Testing
      ├ 🚀 Spawn #47, #49, #50
      │
10:00 ├ ℹ️  #45 Creating PR
      ├ ✅ #42 Complete
      │
10:30 ├ ⏸️ PAUSE ALL (Emergency)
      │
12:00 ├ ▶️ RESUME ALL
      │
12:30 ├ ❌ #47 Failed (tests)
      ├ ✅ #49 Complete
      │
13:00 ├ ✅ #50 Complete
      └ 🚀 Spawn #51

Active: 3 agents (#45, #47, #51)
Completed: 3 features (#42, #49, #50)
Failed: 1 feature (#47 - preserved)
```

### Example 9: Filter Failed Events
```
/orchestrator-events --filter fail --verbose
```

**Output**:
```
📋 Failed Events (Verbose)

Total Failures: 3

Failure 1/3:
─────────────────────────────────────────────
Agent: #47 (Data Migration)
Timestamp: 2025-01-18 12:42:18 UTC
Duration: 3h 3m 33s

Failure Details:
  Type: Test failures
  Failed Tests: 3/45 (6.7%)
  Exit Code: 1

Test Failures:
  1. migration.test.ts:42 - Database connection timeout
  2. migration.test.ts:67 - Data integrity check failed
  3. migration.test.ts:89 - Rollback test failed

Error Log:
  Error: connect ETIMEDOUT 10.0.0.5:5432
  at TCPConnectWrap.afterConnect [as oncomplete]

State: Preserved (code synced to worktree)
Sandbox: sbx_ghi789 (still running)

Recovery Actions:
  Debug: /sandbox-debug sbx_ghi789
  Retry: /implement-feature #47 --mode sandbox
  View: /show-status #47
─────────────────────────────────────────────

Failure 2/3:
[...]
```

### Example 10: Export Filtered Events
```
/orchestrator-events --filter complete --format csv --export completions.csv
```

**Output**:
```
📋 Exporting Completion Events

Filtering events...
  Type: complete
  Total matches: 18 events

Exporting to: completions.csv
  Format: CSV
  Columns: timestamp, agent, issue, duration, pr_number

✅ Export Complete

File: completions.csv (2.1 KB, 18 events)

Preview:
  timestamp,agent,issue,duration,pr_number
  2025-01-18T13:02:15Z,50,50,3h17m,127
  2025-01-18T12:48:44Z,49,49,3h10m,126
  2025-01-18T10:15:33Z,45,45,1h30m,125
  [...]

Usage:
  Import into spreadsheet for analysis
  python analyze_completions.py completions.csv
```

## Event Types

### spawn
Agent spawned and started working on a feature.

**Fields**: agent_id, sandbox_id, issue_number, timestamp

### complete
Agent successfully completed a feature.

**Fields**: agent_id, duration, pr_number, tests_passed, coverage

### fail
Agent encountered failure during implementation.

**Fields**: agent_id, error_type, error_message, exit_code, state

### pause
Orchestration or agent paused.

**Fields**: scope (ALL or agent_id), reason, paused_at

### resume
Orchestration or agent resumed.

**Fields**: scope (ALL or agent_id), resumed_at, pause_duration

### error
Error occurred during orchestration.

**Fields**: error_type, error_message, agent_id (optional), severity

### info
Informational event (progress updates, state changes).

**Fields**: agent_id (optional), message, category

### start
Orchestration session started.

**Fields**: session_id, strategy, max_agents

### stop
Orchestration session stopped.

**Fields**: session_id, reason, total_duration, completions

## Error Handling

### Error 1: No Active Orchestration

```
❌ Error: No active orchestration session

Event Log Status:
  Active Session: None
  Last Session: orch_xyz789abc (ended 2 days ago)

No events to display.

Available Actions:
  View historical events:
    /orchestrator-events --session orch_xyz789abc

  Start new orchestration:
    /parallel-implement-features #42 #45 #47

  View orchestrator status:
    /orchestrator-status
```

### Error 2: Invalid Filter Type

```
❌ Error: Invalid event filter

Requested Filter: "success"
Valid Filters: spawn, complete, fail, pause, resume, error, info, all

Did you mean:
  /orchestrator-events --filter complete

Available filters:
  spawn     - Agent spawn events
  complete  - Successful completions
  fail      - Failures
  pause     - Pause events
  resume    - Resume events
  error     - Error events
  info      - Informational events
  all       - All event types
```

### Error 3: Export File Exists

```
❌ Error: Export file already exists

Target File: events.json
File exists: Yes (42.3 KB, modified 1 hour ago)

Cannot overwrite existing file without confirmation.

Options:
  1. Use different filename:
     /orchestrator-events --export events-2.json

  2. Overwrite (add --force):
     /orchestrator-events --export events.json --force

  3. Append timestamp:
     /orchestrator-events --export events-20250118-130215.json

Recommendation: Option 3 (timestamped filename)
```

## Integration

### Integration with Orchestrator State
- Reads events from orchestration state file
- Events persisted across pause/resume
- Complete history available for session
- Real-time updates in follow mode

### Integration with Agent Events
- Agent lifecycle events captured automatically
- Progress updates logged periodically
- Error events logged immediately
- Completion events include metrics

### Integration with Monitoring
- Powers orchestrator status display
- Enables real-time monitoring
- Provides audit trail
- Supports debugging workflows

### Integration with Export Tools
- JSON export for programmatic access
- CSV export for spreadsheet analysis
- Timeline view for visualization
- Integrates with external monitoring tools

## Use Cases

### Use Case 1: Monitor Orchestration Progress
**Scenario**: Want to see what's happening in real-time.

**Command**:
```bash
/orchestrator-events --follow
```

### Use Case 2: Debug Failed Agent
**Scenario**: Agent failed; need to understand why.

**Command**:
```bash
/orchestrator-events --agent 47 --verbose
/orchestrator-events --filter error --since 1h
```

### Use Case 3: Performance Analysis
**Scenario**: Analyze completion times and success rates.

**Command**:
```bash
/orchestrator-events --filter complete --format json --export completions.json
# Analyze with jq or Python
```

### Use Case 4: Audit Trail
**Scenario**: Need complete record of orchestration session.

**Command**:
```bash
/orchestrator-events --format json --export audit-trail.json
```

### Use Case 5: Understand Pause/Resume
**Scenario**: Want to see when and why orchestration was paused.

**Command**:
```bash
/orchestrator-events --filter pause
/orchestrator-events --filter resume
```

## Performance Considerations

### Event Volume
- Large sessions may have 1000+ events
- Use `--limit` to control output
- Filter by type for faster queries
- Export to file for offline analysis

### Real-Time Following
- Follow mode streams events live
- Minimal performance impact
- Press Ctrl+C to stop
- Events buffered for smooth display

### Export Performance
- JSON export: Fast (<1 second for 1000 events)
- CSV export: Fast (<1 second for 1000 events)
- Large exports: Use `--limit` to chunk
- Timeline view: Most resource-intensive

## Notes

- **Persistent**: Events stored across pause/resume cycles
- **Complete**: All agent lifecycle events captured
- **Filterable**: Filter by type, agent, time range
- **Exportable**: JSON, CSV, timeline formats
- **Real-Time**: Follow mode for live monitoring
- **Verbose**: Detailed event information available
- **Audit Trail**: Complete history for compliance
- **Debug Tool**: Essential for troubleshooting
- **Performance**: Efficient even with large event logs
- **Flexible**: Multiple output formats for different uses
