# Phase 5 Comprehensive Test Suite

**Version**: 1.0
**Created**: 2025-01-18
**Commands Tested**: 18 Phase 5 Priority 3 Commands
**Test Categories**: Functional, Error Handling, Integration, Performance, Security

---

## Test Suite Overview

### Test Coverage Goals
- **Functional Tests**: 100% of documented examples
- **Error Tests**: 100% of documented error scenarios (108+ total)
- **Integration Tests**: All cross-command workflows
- **Performance Tests**: Resource usage and speed benchmarks
- **Security Tests**: Permission checks, data sanitization

### Test Execution Strategy
1. **Unit Tests**: Individual command functionality
2. **Error Tests**: All error scenarios with recovery paths
3. **Integration Tests**: Multi-command workflows
4. **Performance Tests**: Speed and resource benchmarks
5. **Security Tests**: Permission, authentication, data safety

---

## 1. Testing Infrastructure Commands (3 commands)

### 1.1 test-matrix.md Tests

#### Functional Tests (12 examples)
```yaml
- name: "Example 1: Simple 2x2 Matrix"
  command: /test-matrix --node 18,20 --os linux,macos
  expected_sandboxes: 4
  expected_duration: <5 minutes
  assertions:
    - All 4 combinations execute
    - Test results aggregated correctly
    - Cost calculated per combination
    - Summary shows pass/fail rates

- name: "Example 2: 3x3x2 Matrix (18 combinations)"
  command: /test-matrix --node 18,20,22 --os linux,macos,windows --db postgres,mysql
  expected_sandboxes: 18
  expected_duration: <10 minutes
  assertions:
    - All 18 combinations execute in parallel
    - No duplicate combinations
    - Results grouped by dimension
    - Performance comparison across configs

- name: "Example 3: Filter Specific Tests"
  command: /test-matrix --node 18,20 --os linux,macos --tests "src/auth/**"
  assertions:
    - Only auth tests run
    - All other tests skipped
    - Time savings vs full suite

- name: "Example 4: Focus on Failed Combinations"
  command: /test-matrix --only-failed
  assertions:
    - Re-runs only previous failures
    - Same configurations used
    - Validates if transient or persistent

- name: "Example 5: Cost-Optimized Matrix"
  command: /test-matrix --optimize-cost --node 18,20 --os linux,macos
  assertions:
    - Reduced to 3 combinations (vs 4)
    - Smart reduction strategy applied
    - Still covers critical paths

- name: "Example 6: Export Results"
  command: /test-matrix --node 18,20 --os linux,macos --export json
  assertions:
    - JSON file created
    - Contains all combinations
    - Includes timing and cost data

- name: "Example 7: Timeout Handling"
  command: /test-matrix --node 18,20 --timeout 120
  assertions:
    - Combinations respect timeout
    - Timeout failures reported separately
    - Partial results still captured

- name: "Example 8: Dry Run"
  command: /test-matrix --node 18,20,22 --os linux,macos --dry-run
  assertions:
    - No sandboxes created
    - Shows planned combinations (6)
    - Estimates cost and time

- name: "Example 9: Custom Test Command"
  command: /test-matrix --node 18,20 --os linux,macos --test-command "npm run test:integration"
  assertions:
    - Custom command executed
    - Results captured correctly

- name: "Example 10: Database Matrix"
  command: /test-matrix --db postgres:14,postgres:15,mysql:8.0
  assertions:
    - 3 database versions tested
    - Database-specific tests run
    - Schema compatibility verified

- name: "Example 11: Browser Matrix"
  command: /test-matrix --browser chrome,firefox,safari
  assertions:
    - E2E tests run in 3 browsers
    - Screenshots captured
    - Cross-browser issues detected

- name: "Example 12: Minimal Matrix"
  command: /test-matrix --node 18 --os linux
  assertions:
    - Single combination (1x1)
    - Fast execution (<2 min)
    - Baseline for comparison
```

#### Error Tests (10 scenarios)
```yaml
- name: "Error 1: Invalid Matrix Dimension"
  command: /test-matrix --invalid-dimension value
  expected_error: "Invalid dimension: invalid-dimension"
  recovery_options:
    - List valid dimensions
    - Show example command

- name: "Error 2: Insufficient Resources"
  command: /test-matrix --node 18,20,22 --os linux,macos,windows
  setup: Set max sandboxes to 3
  expected_error: "Insufficient resources (need 9, have 3)"
  recovery_options:
    - Reduce matrix size
    - Use --sequential flag
    - Wait for resources

- name: "Error 3: Matrix Too Large"
  command: /test-matrix --node 16,18,20,22 --os linux,macos,windows --db postgres,mysql
  expected_error: "Matrix too large (24 combinations > 20 limit)"
  recovery_options:
    - Use --optimize-cost
    - Reduce dimensions
    - Increase limit (admin)

- name: "Error 4: All Tests Failed"
  setup: Use broken test suite
  command: /test-matrix --node 18,20 --os linux,macos
  expected_result: All 4 combinations fail
  assertions:
    - Failure report generated
    - Common failures highlighted
    - Suggests root cause

- name: "Error 5: Sandbox Provisioning Failed"
  setup: Simulate E2B API error
  command: /test-matrix --node 18,20 --os linux,macos
  expected_error: "Failed to provision sandbox for node:20 + macos"
  recovery_options:
    - Retry failed combination
    - Skip and continue
    - Abort entire matrix

- name: "Error 6: Timeout Exceeded"
  command: /test-matrix --node 18,20 --timeout 30
  setup: Use slow test suite
  expected_error: "Timeout exceeded for node:18 + linux"
  recovery_options:
    - Increase timeout
    - Skip slow tests
    - Run in smaller batches

- name: "Error 7: Test Command Not Found"
  command: /test-matrix --node 18,20 --test-command "npm run nonexistent"
  expected_error: "Test command failed: npm run nonexistent"
  assertions:
    - Error reported for all combinations
    - Suggests checking package.json

- name: "Error 8: Cost Budget Exceeded"
  command: /test-matrix --node 18,20,22 --os linux,macos,windows --budget 5.00
  setup: Matrix costs $8.50
  expected_error: "Matrix cost ($8.50) exceeds budget ($5.00)"
  recovery_options:
    - Use --optimize-cost
    - Reduce matrix size
    - Increase budget

- name: "Error 9: Conflicting Dimensions"
  command: /test-matrix --node 18 --browser safari --os linux
  expected_error: "Conflicting configuration: Safari not available on Linux"
  recovery_options:
    - Remove Safari
    - Change OS to macOS
    - Use Chrome/Firefox

- name: "Error 10: No Tests Found"
  command: /test-matrix --node 18,20 --tests "nonexistent/**"
  expected_error: "No tests found matching pattern"
  recovery_options:
    - Check test path
    - List available tests
    - Remove filter
```

---

### 1.2 sandbox-debug.md Tests

#### Functional Tests (8 examples)
```yaml
- name: "Example 1: Basic Interactive Session"
  command: /sandbox-debug sbx_abc123xyz
  assertions:
    - Interactive shell opens
    - Can execute commands (ls, pwd, etc.)
    - Exit command closes session
    - Session duration logged

- name: "Example 2: Tail Logs in Real-Time"
  command: /sandbox-debug sbx_abc123xyz --tail-logs
  assertions:
    - Log stream displayed
    - Real-time updates shown
    - Can filter by level
    - Ctrl+C stops tailing

- name: "Example 3: Inspect Environment Variables"
  command: /sandbox-debug sbx_abc123xyz --env
  assertions:
    - All env vars listed
    - Values displayed (or masked if secret)
    - Can search/filter
    - Export option available

- name: "Example 4: Browse File System"
  command: /sandbox-debug sbx_abc123xyz --browse /workspace
  assertions:
    - Directory tree displayed
    - File sizes shown
    - Can navigate directories
    - Can view file contents

- name: "Example 5: Check Running Processes"
  command: /sandbox-debug sbx_abc123xyz --ps
  assertions:
    - Process list displayed
    - CPU/memory usage shown
    - Can kill processes
    - Can restart processes

- name: "Example 6: Test Network Connectivity"
  command: /sandbox-debug sbx_abc123xyz --network
  assertions:
    - Network interfaces listed
    - DNS resolution tested
    - Port connectivity checked
    - Curl commands work

- name: "Example 7: Quick Health Check"
  command: /sandbox-debug sbx_abc123xyz --health
  assertions:
    - System health displayed
    - Disk/memory/CPU status
    - Service status checked
    - Issues highlighted

- name: "Example 8: Multi-Command Session"
  command: /sandbox-debug sbx_abc123xyz
  sequence:
    - cd /workspace
    - npm install
    - npm test
    - exit
  assertions:
    - All commands execute
    - Working directory preserved
    - Exit code captured
```

#### Error Tests (10 scenarios)
```yaml
- name: "Error 1: Sandbox Not Found"
  command: /sandbox-debug sbx_invalid123
  expected_error: "Sandbox not found: sbx_invalid123"
  recovery_options:
    - List active sandboxes
    - Check sandbox ID spelling

- name: "Error 2: Sandbox Not Running"
  command: /sandbox-debug sbx_stopped123
  expected_error: "Sandbox is not running (status: stopped)"
  recovery_options:
    - Start sandbox
    - Use different sandbox

- name: "Error 3: Connection Timeout"
  setup: Simulate network issues
  command: /sandbox-debug sbx_abc123xyz
  expected_error: "Connection timeout (30s)"
  recovery_options:
    - Retry connection
    - Check network
    - Increase timeout

- name: "Error 4: Permission Denied"
  command: /sandbox-debug sbx_abc123xyz
  setup: Use non-owner user
  expected_error: "Permission denied (not owner)"
  recovery_options:
    - Request access
    - Use owned sandbox

- name: "Error 5: Disk Space Exhausted"
  command: /sandbox-debug sbx_abc123xyz
  setup: Fill disk to 100%
  expected_error: "Disk space exhausted (100% full)"
  recovery_options:
    - Clean build artifacts
    - Clear npm cache
    - Increase disk size

- name: "Error 6: Command Execution Failed"
  command: /sandbox-debug sbx_abc123xyz
  sequence: ["invalid-command"]
  expected_error: "Command not found: invalid-command"
  assertions:
    - Error displayed
    - Session continues
    - Can execute more commands

- name: "Error 7: Multiple Sessions Conflict"
  command: /sandbox-debug sbx_abc123xyz
  setup: Another user already debugging
  expected_error: "Sandbox locked by another debug session"
  recovery_options:
    - Wait for session to end
    - Request session takeover (admin)

- name: "Error 8: File Not Found"
  command: /sandbox-debug sbx_abc123xyz --browse /nonexistent
  expected_error: "Path not found: /nonexistent"
  recovery_options:
    - Check path spelling
    - Browse from root

- name: "Error 9: Process Kill Failed"
  command: /sandbox-debug sbx_abc123xyz --kill 1
  expected_error: "Cannot kill PID 1 (init process)"
  recovery_options:
    - Kill different process
    - Restart sandbox

- name: "Error 10: Session Terminated"
  command: /sandbox-debug sbx_abc123xyz
  setup: Terminate sandbox mid-session
  expected_error: "Session terminated (sandbox stopped)"
  recovery_options:
    - Acknowledge termination
    - View session log
```

---

### 1.3 sandbox-exec.md Tests

#### Functional Tests (12 examples)
```yaml
- name: "Example 1: Simple Command"
  command: /sandbox-exec sbx_abc123xyz "npm test"
  assertions:
    - Command executes
    - Output captured
    - Exit code returned
    - Duration logged

- name: "Example 2: Command with Timeout"
  command: /sandbox-exec sbx_abc123xyz "npm test" --timeout 300
  assertions:
    - Timeout respected
    - Kills if exceeded
    - Partial output captured

- name: "Example 3: Multiple Commands"
  command: /sandbox-exec sbx_abc123xyz "npm install && npm test && npm run build"
  assertions:
    - All commands execute sequentially
    - Stops on first failure
    - Exit code from failed command

- name: "Example 4: Background Execution"
  command: /sandbox-exec sbx_abc123xyz "npm start" --background
  assertions:
    - Command runs in background
    - PID returned
    - Can monitor later

- name: "Example 5: Capture Output to File"
  command: /sandbox-exec sbx_abc123xyz "npm test" --output test-results.txt
  assertions:
    - Output saved to file
    - File created in sandbox
    - Can retrieve later

- name: "Example 6: Environment Variables"
  command: /sandbox-exec sbx_abc123xyz "npm test" --env NODE_ENV=test,DEBUG=true
  assertions:
    - Env vars passed correctly
    - Available in command
    - Don't persist after command

- name: "Example 7: Working Directory"
  command: /sandbox-exec sbx_abc123xyz "npm test" --cwd /workspace/src
  assertions:
    - Command runs in specified directory
    - Relative paths work correctly

- name: "Example 8: Retry on Failure"
  command: /sandbox-exec sbx_abc123xyz "flaky-command" --retry 3
  assertions:
    - Retries up to 3 times
    - Reports attempt count
    - Succeeds if any attempt succeeds

- name: "Example 9: Script Upload and Execute"
  command: /sandbox-exec sbx_abc123xyz --script ./local-script.sh
  assertions:
    - Script uploaded to sandbox
    - Made executable
    - Executed successfully
    - Cleanup after execution

- name: "Example 10: Batch Execution"
  commands:
    - /sandbox-exec sbx_abc123xyz "npm install"
    - /sandbox-exec sbx_abc123xyz "npm test"
    - /sandbox-exec sbx_abc123xyz "npm run build"
  assertions:
    - All execute in sequence
    - Each completion logged
    - Total time calculated

- name: "Example 11: Parallel Execution (Multiple Sandboxes)"
  commands:
    - /sandbox-exec sbx_1 "npm test"
    - /sandbox-exec sbx_2 "npm test"
    - /sandbox-exec sbx_3 "npm test"
  execution: parallel
  assertions:
    - All run simultaneously
    - Complete in ~same time
    - Results aggregated

- name: "Example 12: CI/CD Integration"
  command: /sandbox-exec sbx_abc123xyz "npm ci && npm run lint && npm test && npm run build"
  assertions:
    - Full CI pipeline runs
    - Stops on first failure
    - Exit code returned for CI
```

#### Error Tests (8 scenarios)
```yaml
- name: "Error 1: Sandbox Not Found"
  command: /sandbox-exec sbx_invalid123 "ls"
  expected_error: "Sandbox not found: sbx_invalid123"
  recovery_options:
    - List active sandboxes
    - Check sandbox ID

- name: "Error 2: Command Timeout"
  command: /sandbox-exec sbx_abc123xyz "sleep 300" --timeout 10
  expected_error: "Command timeout (10s exceeded)"
  recovery_options:
    - Increase timeout
    - Optimize command
    - Run in background

- name: "Error 3: Command Failed"
  command: /sandbox-exec sbx_abc123xyz "npm test"
  setup: Tests fail
  expected_error: "Command failed (exit code 1)"
  assertions:
    - Error output captured
    - Exit code returned
    - Can retry

- name: "Error 4: Permission Denied"
  command: /sandbox-exec sbx_abc123xyz "rm -rf /system"
  expected_error: "Permission denied"
  assertions:
    - Command blocked
    - Sandbox protected

- name: "Error 5: Command Not Found"
  command: /sandbox-exec sbx_abc123xyz "nonexistent-command"
  expected_error: "Command not found: nonexistent-command"
  recovery_options:
    - Check spelling
    - Install package
    - Use full path

- name: "Error 6: Network Error"
  command: /sandbox-exec sbx_abc123xyz "npm install"
  setup: Disconnect network
  expected_error: "Network error during npm install"
  recovery_options:
    - Check network
    - Retry with backoff
    - Use cached packages

- name: "Error 7: Disk Full"
  command: /sandbox-exec sbx_abc123xyz "npm install"
  setup: Fill disk
  expected_error: "ENOSPC: no space left on device"
  recovery_options:
    - Clean workspace
    - Increase disk size

- name: "Error 8: Concurrent Lock"
  command: /sandbox-exec sbx_abc123xyz "npm test"
  setup: Another command running
  expected_error: "Sandbox locked by another operation"
  recovery_options:
    - Wait for completion
    - Force terminate
```

---

## 2. Orchestration Commands (4 commands)

### 2.1 pause-orchestration.md Tests

#### Functional Tests (6 examples)
```yaml
- name: "Example 1: Simple Pause"
  setup: Active orchestration with 5 agents
  command: /pause-orchestration
  assertions:
    - All agents pause
    - State saved
    - Resources preserved
    - Can resume later

- name: "Example 2: Graceful Pause"
  command: /pause-orchestration --graceful --timeout 60
  assertions:
    - Current operations complete
    - Then agents pause
    - No partial state
    - Timeout respected

- name: "Example 3: Pause with Snapshots"
  command: /pause-orchestration --snapshot
  assertions:
    - State saved
    - Snapshots created for each sandbox
    - Can rollback if needed

- name: "Example 4: Force Pause"
  command: /pause-orchestration --force
  assertions:
    - Immediate pause
    - Current operations interrupted
    - State saved anyway
    - Fast completion (<10s)

- name: "Example 5: Pause with Reason"
  command: /pause-orchestration --reason "Emergency maintenance"
  assertions:
    - Reason logged
    - Included in state file
    - Visible in events

- name: "Example 6: Pause and Terminate Sandboxes"
  command: /pause-orchestration --preserve-sandbox=false
  assertions:
    - Sandboxes terminated
    - Resources released
    - State saved for resume
    - New sandboxes on resume
```

#### Error Tests (6 scenarios)
```yaml
- name: "Error 1: No Active Orchestration"
  command: /pause-orchestration
  expected_error: "No active orchestration to pause"
  recovery_options:
    - Check status
    - Start orchestration first

- name: "Error 2: Already Paused"
  command: /pause-orchestration
  setup: Orchestration already paused
  expected_error: "Orchestration already paused"
  recovery_options:
    - Resume first
    - View paused state

- name: "Error 3: Graceful Timeout"
  command: /pause-orchestration --graceful --timeout 30
  setup: Operations take >30s
  expected_error: "Graceful timeout exceeded"
  recovery_options:
    - Force pause
    - Increase timeout
    - Let operations complete

- name: "Error 4: Snapshot Failed"
  command: /pause-orchestration --snapshot
  setup: Disk full
  expected_error: "Snapshot creation failed (disk full)"
  recovery_options:
    - Pause without snapshot
    - Clean disk space
    - Snapshot later

- name: "Error 5: State Save Failed"
  command: /pause-orchestration
  setup: Filesystem error
  expected_error: "Failed to save state"
  recovery_options:
    - Check filesystem
    - Retry pause
    - Force terminate (data loss risk)

- name: "Error 6: Insufficient Permissions"
  command: /pause-orchestration
  setup: Non-owner user
  expected_error: "Permission denied (not orchestration owner)"
  recovery_options:
    - Contact owner
    - Request admin override
```

---

### 2.2 resume-orchestration.md Tests

#### Functional Tests (6 examples)
```yaml
- name: "Example 1: Simple Resume"
  setup: Paused orchestration
  command: /resume-orchestration
  assertions:
    - All agents resume
    - State restored
    - Work continues
    - Same strategy applied

- name: "Example 2: Selective Resume"
  command: /resume-orchestration --agents 42,45,47
  assertions:
    - Only specified agents resume
    - Others remain paused
    - Partial orchestration active

- name: "Example 3: Resume with Strategy Override"
  command: /resume-orchestration --strategy aggressive
  assertions:
    - Strategy changed from balanced → aggressive
    - Max agents increased
    - Auto-spawn enabled

- name: "Example 4: Resume with New Sandboxes"
  setup: Paused with terminated sandboxes
  command: /resume-orchestration --new-sandboxes
  assertions:
    - New sandboxes created
    - State restored to new sandboxes
    - Work continues

- name: "Example 5: Resume from Snapshot"
  command: /resume-orchestration --from-snapshot snap_backup_123
  assertions:
    - Sandboxes restored from snapshot
    - Exact state recovered
    - Work continues from snapshot point

- name: "Example 6: Skip Queue and Resume Active Only"
  command: /resume-orchestration --skip-queue
  assertions:
    - Only in-progress agents resume
    - Queued features stay queued
    - Faster resume
```

#### Error Tests (6 scenarios)
```yaml
- name: "Error 1: No Paused Orchestration"
  command: /resume-orchestration
  expected_error: "No paused orchestration found"
  recovery_options:
    - Check status
    - List available sessions

- name: "Error 2: State File Corrupted"
  command: /resume-orchestration
  setup: Corrupt state file
  expected_error: "State file corrupted (invalid JSON)"
  recovery_options:
    - Restore from backup
    - Restore from snapshot
    - Start fresh orchestration

- name: "Error 3: Sandbox Health Check Failed"
  command: /resume-orchestration
  setup: Sandbox unhealthy
  expected_error: "Sandbox health check failed for agent #42"
  recovery_options:
    - Create new sandbox
    - Restore from snapshot
    - Skip failed agent

- name: "Error 4: Capacity Exceeded"
  command: /resume-orchestration
  setup: Max capacity = 3, paused agents = 5
  expected_error: "Cannot resume all agents (capacity: 3, need: 5)"
  recovery_options:
    - Resume subset
    - Increase capacity
    - Change strategy

- name: "Error 5: Strategy Conflict"
  command: /resume-orchestration --strategy aggressive
  setup: Resources insufficient for aggressive
  expected_error: "Insufficient resources for aggressive strategy"
  recovery_options:
    - Use balanced strategy
    - Clean up resources
    - Resume fewer agents

- name: "Error 6: Permission Denied"
  command: /resume-orchestration
  setup: Non-owner user
  expected_error: "Permission denied (not orchestration owner)"
  recovery_options:
    - Contact owner
    - Request admin override
```

---

### 2.3 orchestrator-events.md Tests

#### Functional Tests (10 examples)
```yaml
- name: "Example 1: View Recent Events"
  command: /orchestrator-events
  assertions:
    - Last 50 events shown (default)
    - Newest first
    - Event types indicated
    - Timestamps displayed

- name: "Example 2: Filter by Type"
  command: /orchestrator-events --type ERROR
  assertions:
    - Only ERROR events shown
    - Other types filtered out
    - Count of errors displayed

- name: "Example 3: Filter by Agent"
  command: /orchestrator-events --agent 42
  assertions:
    - Only events for agent #42
    - Full lifecycle visible
    - From spawn to completion

- name: "Example 4: Filter by Time Range"
  command: /orchestrator-events --from "2025-01-18T10:00" --to "2025-01-18T12:00"
  assertions:
    - Only events in range shown
    - Boundary events included
    - Count displayed

- name: "Example 5: Follow Mode (Real-time)"
  command: /orchestrator-events --follow
  assertions:
    - Live stream of events
    - Updates in real-time
    - Ctrl+C to stop
    - Last event timestamp shown

- name: "Example 6: Export to JSON"
  command: /orchestrator-events --export json --output events.json
  assertions:
    - JSON file created
    - All events included
    - Proper JSON structure
    - Can reimport

- name: "Example 7: Export to CSV"
  command: /orchestrator-events --export csv
  assertions:
    - CSV file created
    - Headers included
    - Can open in Excel
    - All fields captured

- name: "Example 8: Timeline View"
  command: /orchestrator-events --timeline
  assertions:
    - Visual timeline displayed
    - Events positioned chronologically
    - Key events highlighted
    - Easy to scan

- name: "Example 9: Filter by Severity"
  command: /orchestrator-events --severity high,critical
  assertions:
    - Only high/critical events
    - Warnings excluded
    - Info excluded

- name: "Example 10: Search Events"
  command: /orchestrator-events --search "OAuth"
  assertions:
    - Only events matching "OAuth"
    - Full-text search
    - Case-insensitive
```

#### Error Tests (3 scenarios)
```yaml
- name: "Error 1: No Events Found"
  command: /orchestrator-events --type INVALID
  expected_error: "No events found matching criteria"
  recovery_options:
    - Check filter criteria
    - List available event types
    - Remove filters

- name: "Error 2: Invalid Time Range"
  command: /orchestrator-events --from "invalid-date"
  expected_error: "Invalid time format"
  recovery_options:
    - Use ISO 8601 format
    - Show example
    - Use relative times

- name: "Error 3: Export Failed"
  command: /orchestrator-events --export json --output /protected/events.json
  expected_error: "Permission denied writing to /protected"
  recovery_options:
    - Change output path
    - Check permissions
    - Use default location
```

---

### 2.4 set-orchestration-strategy.md Tests

#### Functional Tests (5 examples)
```yaml
- name: "Example 1: Switch to Aggressive"
  setup: Current strategy = balanced
  command: /set-orchestration-strategy aggressive
  assertions:
    - Strategy changed
    - Max agents: 5 → 10
    - Auto-spawn enabled
    - Queued features spawn

- name: "Example 2: Switch to Conservative"
  setup: Current strategy = balanced
  command: /set-orchestration-strategy conservative
  assertions:
    - Strategy changed
    - Max agents: 5 → 2
    - Auto-spawn disabled
    - Active agents continue

- name: "Example 3: Dry Run Analysis"
  command: /set-orchestration-strategy aggressive --dry-run
  assertions:
    - No changes made
    - Impact analysis shown
    - Cost/time projections
    - Resource check performed

- name: "Example 4: Force Change"
  command: /set-orchestration-strategy aggressive --force
  assertions:
    - No confirmation prompt
    - Immediate change
    - Logged to events

- name: "Example 5: Apply to Active Agents"
  command: /set-orchestration-strategy conservative --apply-now
  assertions:
    - Requires pause/resume
    - Active agents adjust to new limits
    - Excess agents queued
```

#### Error Tests (3 scenarios)
```yaml
- name: "Error 1: Invalid Strategy"
  command: /set-orchestration-strategy super-fast
  expected_error: "Invalid strategy: super-fast"
  recovery_options:
    - List valid strategies
    - Show example

- name: "Error 2: No Active Orchestration"
  command: /set-orchestration-strategy aggressive
  expected_error: "No active orchestration"
  recovery_options:
    - Start orchestration first
    - View status

- name: "Error 3: Insufficient Resources"
  command: /set-orchestration-strategy aggressive
  setup: Resources at 95%
  expected_error: "Insufficient resources (projected: 120%)"
  recovery_options:
    - Use balanced
    - Clean resources
    - Force anyway (risky)
```

---

## 3. Feature Lifecycle Commands (2 commands)

### 3.1 pause-feature.md Tests

#### Functional Tests (8 examples)
```yaml
- name: "Example 1: Simple Pause"
  setup: Active agent #47
  command: /pause-feature 47
  assertions:
    - Agent pauses
    - Others continue
    - State saved
    - Can resume

- name: "Example 2: Graceful Pause"
  command: /pause-feature 47 --graceful --timeout 120
  assertions:
    - Current operation completes
    - Then pauses
    - Timeout respected

- name: "Example 3: Pause with Snapshot"
  command: /pause-feature 47 --snapshot --reason "Debug OAuth"
  assertions:
    - Agent paused
    - Snapshot created
    - Reason logged

- name: "Example 4: Force Pause"
  command: /pause-feature 47 --force
  assertions:
    - Immediate pause
    - Operation interrupted
    - State saved

- name: "Example 5: Pause Without Sandbox"
  command: /pause-feature 47 --preserve-sandbox=false
  assertions:
    - Sandbox terminated
    - Resources released
    - State saved

- name: "Example 6: Pause Multiple"
  commands:
    - /pause-feature 47 --graceful
    - /pause-feature 49 --graceful
  assertions:
    - Both pause
    - Others continue
    - Independent states

- name: "Example 7: Pause with Reason"
  command: /pause-feature 47 --reason "Fix failing tests before PR"
  assertions:
    - Reason logged
    - Visible in events
    - Included in state

- name: "Example 8: Pause During Long Operation"
  command: /pause-feature 51 --graceful --timeout 300
  setup: Database seeding in progress
  assertions:
    - Waits for seeding
    - Then pauses
    - No partial data
```

#### Error Tests (8 scenarios)
```yaml
- name: "Error 1: Feature Not Found"
  command: /pause-feature 99
  expected_error: "Feature not found: #99"
  recovery_options:
    - List active features
    - Check issue number

- name: "Error 2: Already Paused"
  command: /pause-feature 47
  setup: Agent already paused
  expected_error: "Feature #47 already paused"
  recovery_options:
    - Resume first
    - View pause details

- name: "Error 3: Graceful Timeout"
  command: /pause-feature 47 --graceful --timeout 60
  setup: Operation takes >60s
  expected_error: "Graceful timeout exceeded"
  recovery_options:
    - Force pause
    - Increase timeout
    - Let complete

- name: "Error 4: Snapshot Failed"
  command: /pause-feature 47 --snapshot
  setup: Disk full
  expected_error: "Snapshot failed (disk full)"
  recovery_options:
    - Pause without snapshot
    - Clean disk
    - Retry

- name: "Error 5: Concurrent Lock"
  command: /pause-feature 47
  setup: /sandbox-exec active
  expected_error: "Feature locked by /sandbox-exec"
  recovery_options:
    - Wait for completion
    - Cancel other operation
    - Force pause

- name: "Error 6: No Active Orchestration"
  command: /pause-feature 47
  expected_error: "No active orchestration"
  recovery_options:
    - Start orchestration
    - Check status

- name: "Error 7: Permission Denied"
  command: /pause-feature 47
  setup: Non-owner user
  expected_error: "Permission denied (not feature owner)"
  recovery_options:
    - Contact owner
    - Pause own features

- name: "Error 8: State Corruption"
  command: /pause-feature 47
  setup: Corrupt agent state
  expected_error: "Cannot pause due to state corruption"
  recovery_options:
    - Repair state
    - Force pause (lose data)
    - Terminate and restart
```

---

### 3.2 resume-feature.md Tests

#### Functional Tests (8 examples)
```yaml
- name: "Example 1: Simple Resume"
  setup: Paused agent #47
  command: /resume-feature 47
  assertions:
    - Agent resumes
    - State restored
    - Work continues
    - From checkpoint

- name: "Example 2: Resume with New Sandbox"
  command: /resume-feature 47 --new-sandbox
  assertions:
    - New sandbox created
    - State restored
    - Work continues
    - Old sandbox terminated

- name: "Example 3: Resume from Snapshot"
  command: /resume-feature 47 --snapshot snap_oauth_debug
  assertions:
    - Sandbox restored from snapshot
    - Exact state recovered
    - Work continues

- name: "Example 4: Resume Multiple"
  command: /resume-feature 47 49 51
  assertions:
    - All three resume
    - If capacity allows
    - Otherwise queued

- name: "Example 5: Force Resume Despite Warnings"
  command: /resume-feature 47 --force
  setup: Health warnings
  assertions:
    - Resumes anyway
    - Warnings logged
    - May need fixing

- name: "Example 6: Resume with Priority"
  command: /resume-feature 47 --priority urgent
  assertions:
    - Priority elevated
    - Queue position: first
    - Notified when resumed

- name: "Example 7: Reset Progress"
  command: /resume-feature 47 --reset-progress
  assertions:
    - Progress reset to 0%
    - Starts from beginning
    - Previous work discarded

- name: "Example 8: Skip Health Check"
  command: /resume-feature 47 --skip-health-check
  assertions:
    - No health verification
    - Faster resume
    - Risk accepted
```

#### Error Tests (8 scenarios)
```yaml
- name: "Error 1: Not Paused"
  command: /resume-feature 47
  setup: Agent is active
  expected_error: "Feature #47 is not paused"
  recovery_options:
    - Check status
    - Pause first if needed

- name: "Error 2: Sandbox Terminated"
  command: /resume-feature 47
  setup: Sandbox was terminated
  expected_error: "Sandbox no longer available"
  recovery_options:
    - Use --new-sandbox
    - Restore from snapshot
    - Reset progress

- name: "Error 3: State Corrupted"
  command: /resume-feature 47
  setup: Corrupt state file
  expected_error: "State file corrupted"
  recovery_options:
    - Restart with fresh sandbox
    - Restore from snapshot
    - Manual repair

- name: "Error 4: Capacity Exceeded"
  command: /resume-feature 47
  setup: Max capacity reached
  expected_error: "Cannot resume (capacity full)"
  recovery_options:
    - Queue for next slot
    - Pause another feature
    - Increase capacity

- name: "Error 5: Git Conflict"
  command: /resume-feature 47
  setup: Branch diverged
  expected_error: "Git worktree conflict detected"
  recovery_options:
    - Stash changes
    - Reset to clean
    - New sandbox

- name: "Error 6: Health Check Failed"
  command: /resume-feature 47
  setup: Node modules corrupted
  expected_error: "Sandbox health check failed"
  recovery_options:
    - Auto-repair (npm install)
    - Force resume
    - New sandbox

- name: "Error 7: No Active Orchestration"
  command: /resume-feature 47
  expected_error: "No active orchestration"
  recovery_options:
    - Resume orchestration first
    - Start new orchestration

- name: "Error 8: Dependency Not Ready"
  command: /resume-feature 49
  setup: Depends on #47 (still in progress)
  expected_error: "Dependency #47 not ready"
  recovery_options:
    - Wait for dependency
    - Force resume (will fail)
    - Remove dependency
```

---

## Test Execution Summary

**Total Test Cases**: 200+
- Functional Tests: 120+
- Error Tests: 80+
- Integration Tests: (to be defined in next section)
- Performance Tests: (to be defined)
- Security Tests: (to be defined)

**Estimated Test Execution Time**:
- Unit Tests: 2-3 hours
- Integration Tests: 1-2 hours
- Full Suite: 4-6 hours

---

*This test suite continues for all 18 commands...*
*The remaining 12 commands (sandbox-snapshot, sandbox-restore, list-sandbox-templates, brainstorm-ideas, review-product-requirements, export-session, emergency-hotfix) will follow the same comprehensive pattern.*

**Status**: Part 1 of test suite (7/18 commands documented)
**Next**: Complete remaining 11 commands + integration/performance/security tests
