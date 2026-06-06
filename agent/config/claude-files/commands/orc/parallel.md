---
name: parallel
description: Multi-feature parallel execution with E2B sandboxes (Implementation stage)
---

# /parallel-implement-features Command

Orchestrates parallel implementation of multiple GitHub issues with intelligent dependency management and resource allocation.

## Usage

```
/parallel-implement-features #<issue1> [#<issue2>...] [options]
```

### Syntax Options

**Basic usage** (all issues, auto mode):
```
/parallel-implement-features #42 #43 #44
```

**Per-issue mode specification**:
```
/parallel-implement-features #42:sandbox #43:local #44:sandbox
```

**Global mode override**:
```
/parallel-implement-features #42 #43 #44 --mode sandbox
```

**Strategy selection**:
```
/parallel-implement-features #42 #43 #44 --strategy max-speed
/parallel-implement-features #42 #43 #44 --strategy cost-optimized
/parallel-implement-features #42 #43 #44 --strategy balanced
```

**Concurrency control**:
```
/parallel-implement-features #42 #43 #44 --max-concurrent 5
```

## Parameters

- `#<issue>` (required): One or more issue numbers to implement
- `#<issue>:mode` (optional): Per-issue mode (`:local`, `:sandbox`, `:auto`)
- `--mode <mode>` (optional): Global mode for all issues (overridden by per-issue modes)
  - `local`: Run all in local worktrees
  - `sandbox`: Run all in E2B sandboxes
  - `auto`: Intelligent mode selection per issue
- `--strategy <strategy>` (optional): Orchestration strategy (default: balanced)
  - `max-speed`: Maximum parallelism, highest cost
  - `cost-optimized`: Sequential execution, lowest cost
  - `balanced`: Optimal parallelism with cost control
- `--max-concurrent <n>` (optional): Maximum concurrent sandboxes (default: 10)
- `--yes` (optional): Skip confirmation prompts
- `--dry-run` (optional): Preview execution plan without executing

## Workflow

### Step 1: Input Parsing and Validation

1. **Parse Issue Numbers**:
   - Extract all issue numbers from command arguments
   - Support formats: `#42`, `42`, `#42:sandbox`, `42:local`
   - Validate all issue numbers are valid integers
   - Remove duplicates if present

2. **Parse Mode Specifications**:
   - Extract per-issue modes from colon syntax
   - Extract global mode from --mode flag
   - Validate mode values (local, sandbox, auto)
   - Build mode map: `{issueNumber: mode}`

3. **Parse Flags and Options**:
   - Extract --strategy flag (default: balanced)
   - Extract --max-concurrent flag (default: 10)
   - Extract --yes flag (default: false)
   - Extract --dry-run flag (default: false)
   - Validate all flag values

4. **Display Parsed Configuration**:
   ```
   📋 Parallel Implementation Configuration
   ═══════════════════════════════════════════════

   Issues to Implement: 5
     #42 (mode: sandbox)
     #43 (mode: local)
     #44 (mode: auto → sandbox)
     #45 (mode: auto → local)
     #46 (mode: sandbox)

   Strategy: balanced
   Max Concurrent: 5
   Dry Run: false
   ```

5. **Validate Issues Exist**:
   - For each issue, fetch from GitHub API
   - Verify issue exists and is not closed
   - Display issue titles for confirmation
   - Abort if any issue is invalid

### Step 2: Dependency Analysis

1. **Call analyze_dependencies MCP Tool**:
   - Pass all issue numbers to MCP tool
   - Receive dependency graph with ready/blocked issues
   - Detect circular dependencies (abort if found)
   - Build topological execution order

2. **Display Dependency Graph**:
   ```
   🔗 Dependency Analysis
   ═══════════════════════════════════════════════

   Ready to Start (3 issues):
     #42: User Authentication (no dependencies)
     #43: Database Schema (no dependencies)
     #45: Frontend Components (no dependencies)

   Blocked Issues (2 issues):
     #44: API Endpoints → depends on #42, #43
     #46: Integration Tests → depends on #44

   Execution Order:
     Wave 1: #42, #43, #45 (parallel)
     Wave 2: #44 (after #42, #43 complete)
     Wave 3: #46 (after #44 complete)

   Total Waves: 3
   Critical Path: #42 → #44 → #46
   ```

3. **Handle Circular Dependencies**:
   ```
   ❌ Circular Dependency Detected!

   Dependency Chain:
     #42 depends on #43
     #43 depends on #44
     #44 depends on #42

   Action Required: Fix dependencies before proceeding.
   ```

### Step 3: Resource Allocation Planning

1. **Call plan_sandbox_allocation MCP Tool**:
   - Pass ready issues and constraints
   - Pass strategy preference
   - Pass max concurrent limit
   - Pass current budget usage
   - Receive allocation plan

2. **Display Allocation Plan**:
   ```
   💡 Resource Allocation Plan
   ═══════════════════════════════════════════════

   Strategy: balanced

   Immediate Execution (3 issues):
     #42 (sandbox) - Start now
     #43 (local) - Start now
     #45 (sandbox) - Start now

   Queued for Later (2 issues):
     #44 (sandbox) - After #42, #43 complete
     #46 (sandbox) - After #44 complete

   Resource Summary:
     Sandboxes to spawn: 3 (now) + 2 (later) = 5 total
     Local worktrees: 1
     Max concurrent: 5 (within limit ✓)
     Current active: 0
     Available slots: 5

   Cost Estimate:
     Sandbox runtime: ~$0.40 (20 hours @ $0.02/hr)
     API costs: ~$2.50 (estimated)
     Total estimated: ~$2.90

   Budget Status:
     Monthly limit: $100.00
     Used so far: $12.45
     After this run: ~$15.35
     Remaining: ~$84.65 ✓

   Estimated Completion: ~2-3 hours (parallel execution)
   ```

3. **Strategy Comparison**:
   - If user hasn't confirmed, show strategy comparison

   ```
   📊 Strategy Comparison
   ═══════════════════════════════════════════════

                   Max-Speed    Balanced    Cost-Optimized
   ──────────────────────────────────────────────────────
   Duration:       1.5 hours    2.5 hours   8 hours
   Sandboxes:      5 parallel   3 parallel  1 sequential
   Cost:           $4.50        $2.90       $1.20
   Success Rate:   High         High        High
   Complexity:     High         Medium      Low

   Recommended: balanced (selected)
   ```

### Step 4: User Confirmation

1. **Display Summary and Ask for Confirmation**:
   ```
   ⚡ Ready to Execute Parallel Implementation
   ═══════════════════════════════════════════════

   Summary:
     Total Issues: 5
     Parallel Waves: 3
     First Wave: 3 issues (#42, #43, #45)
     Strategy: balanced
     Estimated Cost: $2.90
     Estimated Time: 2-3 hours

   This will:
     1. Create 4 worktrees (feature-42, feature-43, feature-44, feature-45, feature-46)
     2. Spawn 4 E2B sandboxes (#42, #44, #45, #46)
     3. Run #43 locally in worktree
     4. Monitor all agents in real-time
     5. Auto-spawn dependent issues when unblocked
     6. Report progress every 30 seconds

   Continue with execution? (yes/no/adjust)
   ```

2. **Handle User Response**:
   - **yes**: Proceed to execution
   - **no**: Abort and exit
   - **adjust**: Allow user to modify settings
     - Change strategy
     - Change max-concurrent
     - Change per-issue modes
     - Re-calculate and re-display plan

### Step 5: Parallel Agent Spawning

1. **Initialize Parallel Executor**:
   - Load parallel-executor module from Phase 2 (Sprint 2.20)
   - Initialize worker pool (max-concurrent workers)
   - Create task queue
   - Set up progress tracking

2. **Create Worktrees for All Issues**:
   - For each issue in execution plan (all waves)
   - Create git worktree: `worktrees/feature-{issue}`
   - Create feature branch: `feature/{issue}-{title-slug}`
   - Track worktree paths in orchestrator state

3. **Spawn First Wave (Immediate Issues)**:
   ```
   🚀 Spawning Agents (Wave 1)
   ═══════════════════════════════════════════════

   [1/3] Issue #42 (sandbox)
         ✓ Worktree created: worktrees/feature-42
         ✓ Branch created: feature/42-user-authentication
         → Spawning sandbox agent...
         ✓ Sandbox created: sbx_abc123xyz
         ✓ Code uploaded to sandbox
         ✓ Dependencies installed
         ✓ Agent spawned with hooks enabled
         Status: Running

   [2/3] Issue #43 (local)
         ✓ Worktree created: worktrees/feature-43
         ✓ Branch created: feature/43-database-schema
         ✓ Local agent started with hooks
         Status: Running

   [3/3] Issue #45 (sandbox)
         ✓ Worktree created: worktrees/feature-45
         ✓ Branch created: feature/45-frontend-components
         → Spawning sandbox agent...
         ✓ Sandbox created: sbx_def456uvw
         ✓ Code uploaded to sandbox
         ✓ Dependencies installed
         ✓ Agent spawned with hooks enabled
         Status: Running

   Wave 1 Complete: 3 agents running
   Next Wave: Waiting for dependencies to complete
   ```

4. **For Each Issue in Wave**:
   - **Sandbox Mode**:
     - Call spawn_sandbox_agent MCP tool
     - Pass worktree path for code upload
     - Pass issue specification
     - Register hooks (PreToolUse, PostToolUse, Stop)
     - Configure hybrid tool access
     - Track agent in orchestrator state

   - **Local Mode**:
     - Start agent in worktree directory
     - Register hooks for path restrictions (temp/ only)
     - Pass issue specification
     - Track agent in orchestrator state

5. **Handle Spawn Failures**:
   - If spawn fails, log error
   - Mark issue as failed in state
   - Continue spawning other issues
   - Report failures to user
   - Don't block entire orchestration

### Step 6: Real-Time Monitoring and Auto-Spawn

1. **Start Monitoring Loop** (every 30 seconds):
   ```
   📊 Live Progress Monitor
   ═══════════════════════════════════════════════
   [Update every 30 seconds - Press Ctrl+C to stop]

   Active Agents: 3 running, 0 completed, 0 failed

   #42 (sandbox - sbx_abc123xyz) ████████░░░░░░░░░░░░ 40%
       Last Activity: 15s ago
       Current Task: Writing authentication tests
       Tools Used: 23 (execute_command: 12, files_write: 8, files_read: 3)
       Runtime: 12m 34s
       Cost: $0.15

   #43 (local - worktrees/feature-43) ██████████████░░░░░░ 70%
       Last Activity: 5s ago
       Current Task: Creating migration files
       Tools Used: 18 (files_write: 10, execute_command: 5, files_read: 3)
       Runtime: 11m 02s
       Cost: $0.08 (API only)

   #45 (sandbox - sbx_def456uvw) ██████░░░░░░░░░░░░░░ 30%
       Last Activity: 8s ago
       Current Task: Building React components
       Tools Used: 15 (files_write: 8, execute_command: 4, files_read: 3)
       Runtime: 10m 15s
       Cost: $0.12

   Queued Issues: 2 waiting
     #44 → blocked by #42, #43 (waiting...)
     #46 → blocked by #44 (waiting...)

   Total Progress: 46% (3/5 issues started)
   Total Cost: $0.35
   Elapsed Time: 12m 34s
   ```

2. **Monitor Agent Progress**:
   - Call monitor_agents MCP tool periodically
   - Extract progress from hook logs (Stop hook data)
   - Parse PostToolUse hook entries for activity
   - Calculate percentage complete (heuristic)
   - Display real-time updates

3. **Detect Completion Events**:
   - Watch for agent completion signals
   - Agent reports "task complete" or similar
   - Agent stops making progress for 5+ minutes
   - Tests pass and code is committed
   - Call handle_agent_event MCP tool with completion event

4. **Auto-Spawn Dependent Issues**:
   ```
   ✅ Issue #42 Completed! (12m 34s)
   ═══════════════════════════════════════════════

   Results:
     ✓ Implementation complete
     ✓ Tests passing (15/15)
     ✓ Code committed to feature/42-user-authentication
     ✓ Ready for PR creation

   Checking Dependency Graph...
     #44 was blocked by #42, #43
     #42 is now complete ✓
     #43 is still running (70% complete)
     → Waiting for #43 to complete before spawning #44

   ---

   ✅ Issue #43 Completed! (15m 12s)
   ═══════════════════════════════════════════════

   Results:
     ✓ Implementation complete
     ✓ Migrations created
     ✓ Code committed to feature/43-database-schema

   Checking Dependency Graph...
     #44 was blocked by #42, #43
     #42 is complete ✓
     #43 is now complete ✓
     → All dependencies satisfied! Auto-spawning #44...

   🚀 Auto-Spawning Issue #44 (Wave 2)
   ═══════════════════════════════════════════════

   [1/1] Issue #44 (sandbox)
         ✓ Worktree created: worktrees/feature-44
         ✓ Branch created: feature/44-api-endpoints
         → Spawning sandbox agent...
         ✓ Sandbox created: sbx_ghi789rst
         ✓ Code uploaded to sandbox
         ✓ Dependencies installed
         ✓ Agent spawned with hooks enabled
         Status: Running

   Wave 2 Complete: 1 agent running
   Active Agents: 2 total (1 new, 1 still running from Wave 1)
   ```

5. **Handle Failure Events**:
   ```
   ❌ Issue #45 Failed! (18m 45s)
   ═══════════════════════════════════════════════

   Error: Tests failed (3/18 failing)
   Last Activity: 5m ago (agent may have crashed)

   Failed Tests:
     - Frontend › Component › renders correctly
     - Frontend › Component › handles edge cases
     - Frontend › Component › integrates with API

   Agent Sandbox: sbx_def456uvw (still running)

   Options:
     1. Leave sandbox running for debugging
     2. Destroy sandbox and mark as failed
     3. Retry implementation with new agent

   Checking Dependency Graph...
     No issues depend on #45
     → Failure does not block other issues

   Action: Leaving sandbox running for debugging
   ```

6. **Continue Until All Complete**:
   - Keep monitoring until all agents finish
   - Update progress display every 30 seconds
   - Auto-spawn new waves as dependencies clear
   - Handle completions and failures gracefully
   - Maintain orchestrator state throughout

### Step 7: Final Summary and Cleanup

1. **Display Final Results**:
   ```
   ✅ Parallel Implementation Complete!
   ═══════════════════════════════════════════════

   📊 Execution Summary
   ═══════════════════════════════════════════════

   Total Issues: 5
   Completed: 4 ✓
   Failed: 1 ❌
   Success Rate: 80%

   Completed Issues:
     ✓ #42: User Authentication (12m 34s, $0.15)
     ✓ #43: Database Schema (15m 12s, $0.08)
     ✓ #44: API Endpoints (22m 45s, $0.18)
     ✓ #46: Integration Tests (18m 30s, $0.14)

   Failed Issues:
     ❌ #45: Frontend Components (18m 45s, $0.12)
         Error: Tests failed (3/18 failing)
         Sandbox: sbx_def456uvw (left running for debug)

   Execution Waves:
     Wave 1: #42, #43, #45 (started immediately)
     Wave 2: #44 (started after 15m 12s)
     Wave 3: #46 (started after 37m 57s)

   Performance Metrics:
     Total Duration: 41m 23s
     Parallel Efficiency: 72% (vs 2h 15m sequential)
     Time Saved: 1h 34m (69% faster)

   Cost Breakdown:
     Sandbox Runtime: $0.47 (4 sandboxes × avg 35m)
     API Costs: $1.12
     Total Cost: $1.59
     Budget Used: 1.59% of monthly limit

   Resource Usage:
     Peak Sandboxes: 3 concurrent
     Max Memory: 2.1 GB
     Total Tool Calls: 156

   Next Steps:
     ✓ #42: Run /create-pull-request #42
     ✓ #43: Run /create-pull-request #43
     ✓ #44: Run /create-pull-request #44
     ❌ #45: Debug with /sandbox-debug (sbx_def456uvw)
     ✓ #46: Run /create-pull-request #46

   Worktrees Created:
     - worktrees/feature-42 (ready for PR)
     - worktrees/feature-43 (ready for PR)
     - worktrees/feature-44 (ready for PR)
     - worktrees/feature-45 (needs fixes)
     - worktrees/feature-46 (ready for PR)

   Active Sandboxes:
     - sbx_def456uvw (#45) - left running for debugging
     - All other sandboxes destroyed ✓
   ```

2. **Cleanup Operations**:
   - For completed issues:
     - Sync final code from sandbox to worktree
     - Destroy sandbox (unless --keep-sandbox flag)
     - Update orchestrator state to "completed"

   - For failed issues:
     - Option to keep sandbox running for debugging
     - Option to retry with new agent
     - Log error details to orchestrator state

3. **Update Orchestrator State**:
   - Save final state to `.claude/config/orchestrator-state.json`
   - Record all events in audit log
   - Update resource tracking
   - Update cost tracking
   - Save for future sessions

## Examples

### Example 1: Basic Parallel Implementation
```
/parallel-implement-features #42 #43 #44
```
I'll analyze dependencies, create an execution plan, and implement all three features in parallel using auto mode.

### Example 2: Mixed Modes
```
/parallel-implement-features #42:sandbox #43:local #44:sandbox
```
I'll run #42 and #44 in sandboxes, and #43 locally in a worktree.

### Example 3: Cost-Optimized Strategy
```
/parallel-implement-features #42 #43 #44 #45 #46 --strategy cost-optimized
```
I'll implement features sequentially to minimize costs, even if they have no dependencies.

### Example 4: Max-Speed Strategy
```
/parallel-implement-features #42 #43 #44 #45 #46 --strategy max-speed --max-concurrent 10
```
I'll spawn up to 10 agents in parallel for maximum speed.

### Example 5: Dry Run Preview
```
/parallel-implement-features #42 #43 #44 --dry-run
```
I'll show the execution plan without actually spawning any agents.

### Example 6: Auto-Confirm
```
/parallel-implement-features #42 #43 #44 --yes
```
I'll skip confirmation prompts and start execution immediately.

## Orchestration Strategies

### Max-Speed Strategy
- **Goal**: Minimum total time
- **Approach**: Spawn all ready issues immediately
- **Parallelism**: Maximum (up to --max-concurrent)
- **Cost**: Highest (all sandboxes running simultaneously)
- **Use Case**: Critical deadlines, budget not a concern

**Example Execution**:
```
Wave 1: #42, #43, #44, #45, #46 (all start immediately)
Duration: ~1-2 hours
Cost: $4-5 (all sandboxes running full duration)
```

### Cost-Optimized Strategy
- **Goal**: Minimum total cost
- **Approach**: Sequential execution even without dependencies
- **Parallelism**: 1 at a time
- **Cost**: Lowest (only one sandbox at a time)
- **Use Case**: Budget constraints, no time pressure

**Example Execution**:
```
Wave 1: #42 (complete before starting #43)
Wave 2: #43 (complete before starting #44)
Wave 3: #44, #45, #46 (one at a time)
Duration: ~6-8 hours
Cost: $1-2 (sequential sandbox usage)
```

### Balanced Strategy (Recommended)
- **Goal**: Optimal time/cost ratio
- **Approach**: Respect dependencies, limit parallelism
- **Parallelism**: 3-5 concurrent sandboxes
- **Cost**: Moderate (controlled parallelism)
- **Use Case**: Most common use case

**Example Execution**:
```
Wave 1: #42, #43, #45 (3 parallel)
Wave 2: #44 (after #42, #43)
Wave 3: #46 (after #44)
Duration: ~2-3 hours
Cost: $2-3 (controlled parallelism)
```

## Error Handling

### Common Errors

**Invalid Issue Numbers**:
```
❌ Error: Issue #999 not found

Please verify the issue number and try again.
```

**Circular Dependencies**:
```
❌ Error: Circular dependency detected

Dependency chain: #42 → #43 → #44 → #42

Fix dependencies in GitHub before proceeding.
```

**Budget Exceeded**:
```
❌ Error: Budget limit would be exceeded

Current usage: $95.00
Estimated cost: $8.50
Monthly limit: $100.00

Options:
  1. Increase budget limit with /config set budgetLimit 150
  2. Use --strategy cost-optimized to reduce costs
  3. Reduce --max-concurrent to limit parallelism
```

**Spawn Failures**:
```
⚠️  Warning: Failed to spawn agent for #44

Error: E2B API timeout
Sandbox: Not created
Action: Retrying once...

[Retry 1/1] Spawning #44...
✓ Success on retry
```

**Agent Crashes**:
```
❌ Agent Crashed: Issue #45

Sandbox: sbx_def456uvw (crashed after 18m)
Error: Out of memory
Exit Code: 137

Sandbox preserved for debugging.
Use /sandbox-debug sbx_def456uvw to investigate.
```

### Recovery Options

**Mid-Execution Cancellation**:
- Press Ctrl+C to stop monitoring
- All running agents continue in background
- State is saved
- Resume with /resume-orchestration

**Failure Recovery**:
- Failed issues can be retried individually
- Use /implement-feature #<issue> to retry
- Or include in new /parallel-implement-features call

**State Recovery**:
- Orchestrator state is saved continuously
- Recover from crashes with /resume-orchestration
- All agent progress is preserved

## Configuration

Configure in `.claude/config/bumba-sandbox-config.json`:

```json
{
  "parallel": {
    "defaultStrategy": "balanced",
    "maxConcurrent": 10,
    "defaultMode": "auto",
    "autoSpawn": true,
    "monitorInterval": 30,
    "keepFailedSandboxes": true
  }
}
```

**Options**:
- `defaultStrategy`: Default orchestration strategy
- `maxConcurrent`: Default max concurrent sandboxes
- `defaultMode`: Default execution mode if not specified
- `autoSpawn`: Enable auto-spawning of dependent issues
- `monitorInterval`: Seconds between progress updates
- `keepFailedSandboxes`: Keep failed sandboxes for debugging

## Integration with Other Commands

**Before Parallel Implementation**:
1. `/create-product-requirements` - Define features
2. `/plan-development-sprints` - Break into sprints
3. `/create-specifications` - Create GitHub issues with dependencies

**During Parallel Implementation**:
1. `/show-status` - View all features
2. `/sandbox-status` - View sandbox resources
3. `/orchestrator-status` - View orchestration state
4. `/pause-orchestration` - Pause all agents

**After Parallel Implementation**:
1. `/create-pull-request #<issue>` - Create PRs for completed features
2. `/test #<issue>` - Run tests for specific feature
3. `/cleanup-sandboxes` - Clean up idle/failed sandboxes

## MCP Tools Used

This command uses the following Phase 2 MCP tools:
- `analyze_dependencies` - Dependency graph analysis
- `plan_sandbox_allocation` - Resource allocation planning
- `spawn_sandbox_agent` - Agent spawning
- `monitor_agents` - Progress monitoring
- `handle_agent_event` - Event handling and auto-spawn
- `sandbox_kill` - Sandbox cleanup
- `execute_command` - Command execution (local mode)

## Hook System Integration

All agents spawned by this command have hooks enabled:
- **PreToolUse**: Validates file paths (temp/ restriction for local)
- **PostToolUse**: Logs all tool usage
- **Stop**: Tracks token usage and costs
- **UserPromptSubmit**: Logs user interactions

Hook logs provide:
- Real-time activity monitoring
- Accurate cost tracking
- Security enforcement (path restrictions)
- Audit trail for all operations

## Cost Estimation

**Per Issue Costs** (estimated averages):
- **Sandbox Mode**:
  - Sandbox runtime: $0.02/hour × 1-2 hours = $0.02-0.04
  - API costs: $0.50-1.50
  - Total: ~$0.60-1.60 per issue

- **Local Mode**:
  - Sandbox runtime: $0
  - API costs: $0.50-1.50
  - Total: ~$0.50-1.50 per issue

**Parallel Execution Savings**:
- Sequential (5 issues): ~8 hours wall time
- Parallel balanced (5 issues): ~2-3 hours wall time
- Time saved: ~5-6 hours (60-75% faster)
- Cost increase: ~30% (multiple sandboxes running)

**Strategy Cost Comparison** (5 issues):
- Max-speed: $4-5, 1.5-2 hours
- Balanced: $2-3, 2-3 hours (recommended)
- Cost-optimized: $1-2, 6-8 hours

## Performance Characteristics

**Scalability**:
- Tested with up to 20 concurrent issues
- Recommended max: 10 concurrent sandboxes
- Monitor usage carefully to optimize costs

**Efficiency**:
- Dependency-aware execution minimizes wait time
- Auto-spawn eliminates manual intervention
- Hook-based monitoring reduces polling overhead

**Reliability**:
- Automatic retry on spawn failures
- Graceful handling of agent crashes
- State persistence for recovery

## Notes

- Orchestration state is saved continuously for recovery
- Failed sandboxes are kept running by default for debugging
- Auto-spawn cascade can trigger rapidly - monitor costs
- Use --dry-run first to preview execution plan
- Parallel execution uses Worker Threads (Node.js)
- Each agent runs in independent event loop
- Thread-safe state updates with mutex locks
- Hook logs provide accurate real-time monitoring
- Budget limits are enforced before spawning agents
- Monitor sandbox usage when using max-speed strategy
- Local mode is always cheaper but less isolated
- Sandbox mode provides better isolation and reproducibility
